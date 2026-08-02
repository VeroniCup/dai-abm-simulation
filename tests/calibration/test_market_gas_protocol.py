"""Focused tests for bounded market, gas and protocol estimators."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


from tests.support import REPOSITORY_ROOT
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from dai_sim.calibration.data_loading import (
    InputSpec,
    load_inputs,
    require_hourly_index,
    validate_protocol_intervals,
)
from dai_sim.calibration.market import (
    REQUIRED_CANDIDATE_FIELDS,
    aggregate_liquidation_volume,
    build_parameter_status,
    validate_candidate_registry,
)
from dai_sim.calibration.gas import calculate_transaction_gas_cost
from dai_sim.calibration.statistics import (
    aligned_dependence,
    calculate_log_returns,
    classify_regimes,
    estimate_regime_thresholds,
    moving_block_indices,
    overdispersion_summary,
    regime_durations,
    transition_counts,
    transition_probabilities,
)


def _regime_frame(rows: int = 20) -> pd.DataFrame:
    values = np.linspace(0.0, 1.0, rows)
    return pd.DataFrame(
        {
            "eth_log_return": -values,
            "wbtc_log_return": -(values / 2),
            "realised_crypto_volatility": values,
            "median_effective_gas_price_gwei": values * 100,
            "dai_abs_peg_deviation": values / 100,
            "liquidation_volume_dai": values * 1_000,
        }
    )


def _candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "simulator_field": "PriceProcessConfig.mu",
        "estimate_name": "eth_mean_return",
        "estimate_value": 0.0,
        "distribution_reference": "",
        "units": "log_return_per_hour",
        "simulation_frequency": "hourly",
        "collateral_scope": "ETH",
        "regime_scope": "normal",
        "estimator": "sample mean",
        "input_dataset": "Phase 1A",
        "input_columns": "eth_log_return",
        "estimation_window": "calibration excluding validation",
        "sample_size": 10,
        "uncertainty_measure": "moving-block bootstrap",
        "validation_status": "passed",
        "provenance_classification": "empirical_estimation",
        "implementation_status": "extracted_not_adopted",
        "notes": "Review required.",
        "review_required_before_adoption": True,
    }
    candidate.update(overrides)
    assert set(candidate) == REQUIRED_CANDIDATE_FIELDS
    return candidate


def test_schema_validation_rejects_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "market.csv"
    pd.DataFrame({"timestamp_utc": ["2024-01-01T00:00:00Z"]}).to_csv(
        path, index=False
    )
    spec = InputSpec("market", path, "", 1, 1)
    with pytest.raises(ValueError, match="missing required columns"):
        load_inputs([spec])


def test_log_returns_and_invalid_prices() -> None:
    prices = pd.Series([1.0, np.e, np.e**3], name="price")
    result = calculate_log_returns(prices)
    assert np.isnan(result.iloc[0])
    assert result.iloc[1:].tolist() == pytest.approx([1.0, 2.0])
    with pytest.raises(ValueError, match="non-positive"):
        calculate_log_returns(pd.Series([1.0, 0.0]))


def test_hourly_timestamp_alignment_detects_gap() -> None:
    valid = pd.Series(pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC"))
    require_hourly_index(valid, name="valid")
    invalid = valid.drop(index=1).reset_index(drop=True)
    with pytest.raises(ValueError, match="missing hourly"):
        require_hourly_index(invalid, name="invalid")


def test_thresholds_exclude_withheld_validation_extreme() -> None:
    calibration = _regime_frame()
    expected = estimate_regime_thresholds(calibration)
    validation = _regime_frame(1)
    validation.loc[0, :] = 1e12
    combined = pd.concat([calibration, validation], ignore_index=True)
    actual = estimate_regime_thresholds(combined.iloc[:-1])
    assert actual == expected
    assert estimate_regime_thresholds(combined) != expected


def test_regime_classification_counts_conditions() -> None:
    frame = _regime_frame(3)
    thresholds = {
        "eth_return_q05": -0.5,
        "wbtc_return_q05": -0.25,
        "crypto_volatility_q90": 0.5,
        "gas_price_q90": 50.0,
        "dai_abs_peg_deviation_q90": 0.005,
        "liquidation_volume_q90": 500.0,
    }
    result = classify_regimes(frame, thresholds, minimum_conditions=2)
    assert result["regime"].tolist() == ["normal", "normal", "stress"]
    assert result["stress_condition_count"].iloc[-1] == 6
    assert result["panic_candidate"].iloc[-1] == 1


def test_transition_counts_probabilities_and_withheld_gap() -> None:
    states = pd.Series(["normal", "stress", "stress", "normal"])
    times = pd.Series(pd.date_range("2024-01-01", periods=4, freq="h", tz="UTC"))
    allowed = pd.Series([True, True, False, True])
    counts = transition_counts(states, times, allowed_mask=allowed)
    assert counts.loc["normal", "stress"] == 1
    assert counts.to_numpy().sum() == 1
    probabilities = transition_probabilities(counts)
    assert probabilities.loc["normal", "stress"] == 1.0
    assert probabilities.loc["stress"].isna().all()


def test_regime_duration_runs_are_deterministic() -> None:
    states = pd.Series(["normal", "normal", "stress", "stress", "normal"])
    times = pd.Series(pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC"))
    runs = regime_durations(states, times)
    assert runs["duration_hours"].tolist() == [2, 2, 1]
    assert runs["regime"].tolist() == ["normal", "stress", "normal"]


def test_moving_block_indices_are_seeded_and_valid() -> None:
    first = moving_block_indices(20, 4, np.random.default_rng(17))
    second = moving_block_indices(20, 4, np.random.default_rng(17))
    assert np.array_equal(first, second)
    assert len(first) == 20
    assert first.min() >= 0 and first.max() < 20


def test_dependence_uses_only_aligned_observations() -> None:
    frame = pd.DataFrame(
        {"a": [1.0, 2.0, np.nan, 4.0], "b": [2.0, 4.0, 6.0, 8.0]}
    )
    covariance, pearson, spearman, observations = aligned_dependence(
        frame, ["a", "b"]
    )
    assert observations == 3
    assert covariance.shape == pearson.shape == spearman.shape == (2, 2)
    assert pearson.loc["a", "b"] == pytest.approx(1.0)


def test_gas_units_price_and_usd_conversion_remain_separate() -> None:
    result = calculate_transaction_gas_cost(
        pd.Series([100_000.0]),
        pd.Series([20_000_000_000.0]),
        pd.Series([2_000.0]),
    )
    assert result.loc[0, "cost_eth"] == pytest.approx(0.002)
    assert result.loc[0, "cost_usd"] == pytest.approx(4.0)


def test_liquidation_aggregation_retains_zero_activity_hours() -> None:
    hours = pd.Series(pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC"))
    liquidation = pd.DataFrame(
        {
            "timestamp_utc": [hours.iloc[1], hours.iloc[1]],
            "debt_targeted_dai": [10.0, 15.0],
        }
    )
    result = aggregate_liquidation_volume(liquidation, hours)
    assert result["liquidation_volume_dai"].tolist() == [0.0, 25.0, 0.0]


def test_overdispersion_reports_empirical_zero_heavy_counts() -> None:
    counts = pd.Series([0] * 95 + [1] * 4 + [20])
    result = overdispersion_summary(counts)
    assert result["variance"] > result["mean"]
    assert result["dispersion_index"] > 1
    assert result["recommended_representation"] == "empirical_distribution"


def test_protocol_interval_loader_accepts_adjacency_and_rejects_overlap() -> None:
    frame = pd.DataFrame(
        {
            "module": ["Vat", "Vat"],
            "ilk": ["ETH-A", "ETH-A"],
            "parameter": ["line", "line"],
            "effective_start_utc": [
                "2024-01-01T00:00:00Z",
                "2024-01-02T00:00:00Z",
            ],
            "effective_end_exclusive_utc": [
                "2024-01-02T00:00:00Z",
                "2024-01-03T00:00:00Z",
            ],
            "converted_value": [1.0, 2.0],
        }
    )
    parsed = validate_protocol_intervals(frame)
    assert str(parsed["effective_start_utc"].dtype) == "datetime64[ns, UTC]"
    overlap = frame.copy()
    overlap.loc[1, "effective_start_utc"] = "2024-01-01T12:00:00Z"
    with pytest.raises(ValueError, match="overlaps"):
        validate_protocol_intervals(overlap)


def test_candidate_registry_schema_and_blocked_guard() -> None:
    validate_candidate_registry({"candidates": [_candidate()]})
    blocked = _candidate(implementation_status="blocked_pending_phase1e_b")
    with pytest.raises(ValueError, match="Blocked parameters"):
        validate_candidate_registry({"candidates": [blocked]})
    malformed = _candidate()
    malformed.pop("units")
    with pytest.raises(ValueError, match="missing fields"):
        validate_candidate_registry({"candidates": [malformed]})


def test_parameter_audit_has_no_values_for_blocked_parameters() -> None:
    audit = build_parameter_status()
    assert len(audit) == 56
    blocked = audit.loc[
        audit["current_status"].isin(
            ["blocked_pending_phase1e_b", "requires_model_calibration"]
        )
    ]
    assert len(blocked) > 0
    assert blocked.loc[
        blocked["current_status"].eq("blocked_pending_phase1e_b"),
        "output_artefact",
    ].eq("").all()
    assert "stable_depeg_size" in " ".join(audit["simulator_field"])


def test_candidate_payload_serialises_deterministically() -> None:
    payload = {"candidates": [_candidate()], "seed": 17}
    first = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    second = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert first.encode("utf-8") == second.encode("utf-8")
