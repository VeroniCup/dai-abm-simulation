"""Tests for no-fit historical market evidence and Design C gates."""

from __future__ import annotations

import numpy as np
from pathlib import Path
import pandas as pd
import pytest
import tempfile
from unittest.mock import patch

from dai_sim.calibration.confidence_evidence import (
    ASSET_IDENTITIES,
    FINAL_STRESS_END,
    FINAL_STRESS_START,
    HISTORICAL_END,
    HISTORICAL_START,
    HistoricalMarketEvidenceError,
    build_design_c_origins,
    compare_overlap,
    design_c_partition,
    harmonise_dune_hourly,
    hourly_grid,
    sparse_positive_scale,
)
from workflows.market import acquire as acquisition
from workflows.market import validate as validation


def _raw(start: str = "2024-01-01T00:00:00Z", hours: int = 4) -> pd.DataFrame:
    timestamps = pd.date_range(start, periods=hours, freq="h")
    rows = []
    for asset, identity in ASSET_IDENTITIES.items():
        for position, timestamp in enumerate(timestamps):
            rows.append(
                {
                    "timestamp_utc": timestamp.isoformat(),
                    "asset": asset,
                    "dune_instrument": identity["dune_instrument"],
                    "price_usd": (
                        2_000.0 + position if asset == "ETH" else 1.0 - position / 10_000
                    ),
                    "blockchain": "ethereum",
                    "contract_address": identity["contract_address"].upper(),
                    "source": "coinpaprika",
                    "volume_usd": "<nil>",
                }
            )
    return pd.DataFrame(rows)


def test_harmonisation_preserves_prices_and_constructs_returns_without_filling() -> None:
    raw = _raw()
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    end = pd.Timestamp("2024-01-01T04:00:00Z")
    panel = harmonise_dune_hourly(raw, start, end)

    assert panel.shape == (4, 12)
    assert panel["eth_log_return"].isna().tolist() == [True, False, False, False]
    assert panel["dai_price_usd"].tolist() == [1.0, 0.9999, 0.9998, 0.9997]
    assert panel["dai_source_volume_usd"].isna().all()
    assert panel["dai_data_quality_flags"].eq("source_volume_unavailable").all()


def test_harmonisation_rejects_naive_utc_missing_hours_and_duplicates() -> None:
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    end = pd.Timestamp("2024-01-01T04:00:00Z")
    naive = _raw()
    naive.loc[0, "timestamp_utc"] = "2024-01-01 00:00:00"
    with pytest.raises(HistoricalMarketEvidenceError, match="timezone"):
        harmonise_dune_hourly(naive, start, end)

    missing = _raw().drop(index=0)
    with pytest.raises(HistoricalMarketEvidenceError, match="every requested hour"):
        harmonise_dune_hourly(missing, start, end)

    duplicate = pd.concat([_raw(), _raw().iloc[[0]]], ignore_index=True)
    with pytest.raises(HistoricalMarketEvidenceError, match="Duplicate"):
        harmonise_dune_hourly(duplicate, start, end)


def test_asset_identity_is_contract_based_not_symbol_only() -> None:
    raw = _raw()
    raw.loc[raw["asset"].eq("DAI"), "contract_address"] = ASSET_IDENTITIES["ETH"][
        "contract_address"
    ]
    with pytest.raises(HistoricalMarketEvidenceError, match="contract addresses"):
        harmonise_dune_hourly(
            raw,
            pd.Timestamp("2024-01-01T00:00:00Z"),
            pd.Timestamp("2024-01-01T04:00:00Z"),
        )


def test_positive_quantile_scaling_keeps_zero_and_passes_declared_gate() -> None:
    timestamps = pd.date_range("2020-01-01", periods=36 * 30 * 24, freq="h", tz="UTC")
    values = pd.Series(np.zeros(len(timestamps)))
    positive_positions = np.linspace(0, len(values) - 1, 240, dtype=int)
    values.iloc[positive_positions] = np.tile(np.arange(1, 41), 6)

    scaled, summary = sparse_positive_scale(values, timestamps)

    assert scaled.loc[values.eq(0)].eq(0).all()
    assert summary.positive_count == 240
    assert summary.positive_months >= 12
    assert summary.positive_years >= 2
    assert summary.distinct_positive_values == 40
    assert summary.positive_q95 is not None
    assert summary.gate_passed
    assert scaled.max() == pytest.approx(1.0)


def test_design_c_partitions_keep_final_stress_out_of_calibration() -> None:
    assert design_c_partition(FINAL_STRESS_START) == "final_stress_validation"
    assert (
        design_c_partition(FINAL_STRESS_END - pd.Timedelta(hours=1))
        == "final_stress_validation"
    )
    assert design_c_partition(FINAL_STRESS_END) == "calibration"


def test_overlap_distinguishes_floating_noise_from_label_changes() -> None:
    timestamps = pd.date_range("2021-06-01", periods=8, freq="h", tz="UTC")
    candidate = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "dai_price_usd": [1.0, 0.994, 0.993, 1.0, 1.0, 1.0, 1.0, 1.0],
            "eth_price_usd": np.linspace(2_000.0, 2_100.0, 8),
        }
    )
    existing = candidate.copy()
    existing["dai_price_usd"] += 2e-16
    existing["eth_price_usd"] += 2e-12
    report = compare_overlap(
        candidate,
        existing,
        timestamps[0],
        timestamps[-1] + pd.Timedelta(hours=1),
    )

    disagreements = report["assets"]["DAI"]["label_disagreements"]
    assert disagreements["below_0_995"] == 0
    assert disagreements["six_hour_burden_materially_different"] == 0


def test_design_c_continuous_burden_uses_frozen_six_hour_grid() -> None:
    grid = hourly_grid(HISTORICAL_START, HISTORICAL_END)
    panel = pd.DataFrame(
        {
            "timestamp_utc": grid,
            "dai_price_usd": np.ones(len(grid)),
            "eth_price_usd": np.exp(np.linspace(np.log(100.0), np.log(200.0), len(grid))),
        }
    )
    panel["eth_log_return"] = np.log(panel["eth_price_usd"]).diff()
    origin = pd.Timestamp("2020-02-01T00:00:00Z")
    outcome = pd.date_range(origin, periods=6, freq="h")
    panel.loc[panel["timestamp_utc"].isin(outcome), "dai_price_usd"] = [
        0.995,
        0.994,
        0.993,
        0.992,
        0.991,
        0.990,
    ]

    origins, _ = build_design_c_origins(panel, anchor=0)
    row = origins.loc[origins["timestamp_utc"].eq(origin)].iloc[0]

    assert row["partition"] == "calibration"
    assert row["burden"] == pytest.approx(np.mean([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]))
    assert not origins.loc[
        origins["timestamp_utc"].between(
            FINAL_STRESS_START, FINAL_STRESS_END, inclusive="left"
        ),
        "partition",
    ].eq("calibration").any()


def test_repeated_dune_page_payload_is_rejected() -> None:
    page = b"timestamp_utc,asset\n2024-06-01 00:00:00 UTC,ETH\n"
    responses = [(page, {"X-Dune-Next-Offset": "1"}), (page, {})]
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "raw.csv"
        with patch.object(acquisition, "_request", side_effect=responses):
            with pytest.raises(acquisition.DuneAcquisitionError, match="repeated"):
                acquisition.download_csv_once_per_page(
                    "not-a-real-key", "execution-1", output, 1
                )


def test_non_advancing_or_gapped_dune_offset_is_rejected() -> None:
    page = b"timestamp_utc,asset\n2024-06-01 00:00:00 UTC,ETH\n"
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "raw.csv"
        with patch.object(
            acquisition,
            "_request",
            return_value=(page, {"X-Dune-Next-Offset": "2"}),
        ):
            with pytest.raises(acquisition.DuneAcquisitionError, match="contiguously"):
                acquisition.download_csv_once_per_page(
                    "not-a-real-key", "execution-1", output, 1
                )


def test_full_range_candidate_validation_accepts_only_explicit_asset_subset() -> None:
    raw = _raw(hours=2)
    with tempfile.TemporaryDirectory() as directory:
        raw_path = Path(directory) / "raw.csv"
        raw.to_csv(raw_path, index=False)
        report, failures = validation.validate_prices(
            raw_path,
            requested_start=pd.Timestamp("2024-01-01T00:00:00Z"),
            requested_end=pd.Timestamp("2024-01-01T02:00:00Z"),
            expected_assets=("ETH", "DAI"),
        )

    assert failures == []
    assert report["expected_assets"] == ["DAI", "ETH"]
    assert report["expected_total_rows"] == 4
