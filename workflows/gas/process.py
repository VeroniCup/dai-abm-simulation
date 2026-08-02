"""Construct validated gas and joined market--gas panels locally.

This script has no network path. It verifies the immutable market and gas
inputs, preserves every raw gas field, derives transparent descriptive gas
measures, performs an exact UTC join, creates hypothetical gas-cost indices,
and writes validation and descriptive provenance. It does not estimate keeper
gas usage, select final regimes, or modify simulation parameters.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import runpy

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
REPOSITORY_ROOT = runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from workflows.gas.acquire import (
    EXPECTED_COLUMNS as RAW_GAS_COLUMNS,
    FULL_END,
    FULL_START,
    LONDON_HOUR,
    validate_rows,
)
from workflows.market.process import sha256_file


DEFAULT_RAW_GAS = Path(
    "data/gas/processed/dune_ethereum_hourly_gas_assembled_2021-06-01_2024-06-30.csv"
)
DEFAULT_RAW_GAS_VALIDATION = Path(
    "data/gas/provenance/dune_ethereum_hourly_gas_validation.json"
)
DEFAULT_MARKET = Path(
    "data/market/processed/dune_hourly_market_prices_processed.csv"
)
DEFAULT_MANIFEST = Path("data/provenance/data_manifest.csv")
DEFAULT_GAS_OUTPUT_DIR = Path("data/gas/processed")
DEFAULT_JOINED_OUTPUT_DIR = Path("data/market/processed/combined")
DEFAULT_PROVENANCE_DIR = Path("data/gas/provenance")
EXPECTED_RAW_GAS_SHA256 = (
    "694a901ba6cf2a60a95014398900ab77508a9ce8218cb05acd6424fa23637541"
)
EXPECTED_MARKET_SHA256 = (
    "43f8a23aff2ec995a4e1ad5e8fc66f4b5223e8dcc9c8a36bd272d733ae1d4e25"
)

MARKET_COLUMNS = (
    "timestamp_utc",
    "eth_price_usd",
    "wbtc_price_usd",
    "dai_price_usd",
    "usdc_price_usd",
    "eth_log_return",
    "wbtc_log_return",
    "dai_log_return",
    "usdc_log_return",
    "dai_peg_deviation",
    "usdc_peg_deviation",
    "dai_abs_peg_deviation",
    "usdc_abs_peg_deviation",
    "dai_below_peg",
    "usdc_below_peg",
    "dai_source",
    "usdc_source",
)
LOG_PRICE_COLUMNS = (
    "median_effective_gas_price_gwei",
    "p90_effective_gas_price_gwei",
    "p99_effective_gas_price_gwei",
)
LOG_COLUMNS = (
    "log_median_effective_gas_price",
    "log_p90_effective_gas_price",
    "log_p99_effective_gas_price",
)
LOG_CHANGE_COLUMNS = (
    "median_effective_gas_price_log_change",
    "p90_effective_gas_price_log_change",
    "p99_effective_gas_price_log_change",
)
CLASSIFICATION_A_STATES = ("normal", "stress", "extreme")
CLASSIFICATION_B_STATES = (
    "normal",
    "broad_price_elevation",
    "upper_tail_bidding_pressure",
    "congestion_intensity",
    "compound_pressure",
)
DESCRIPTIVE_QUANTILES = (0.01, 0.05, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
GAS_UNIT_SCENARIOS = (100_000, 300_000, 500_000)
GAS_PRICE_SCENARIOS = {
    "median_gas": "median_effective_gas_price_gwei",
    "p90_gas": "p90_effective_gas_price_gwei",
    "p99_gas": "p99_effective_gas_price_gwei",
}
COST_DISCLAIMER = (
    "These variables do not represent empirically estimated Maker liquidation "
    "transaction costs because liquidation-specific gas units have not yet "
    "been acquired. They must not be used to set LiquidationConfig.gas_cost."
)
REGIME_DISCLAIMER = (
    "These full-sample classifications are descriptive candidate regimes, not "
    "final chosen simulator states or calibrated parameters."
)


class GasProcessingError(RuntimeError):
    """Raised when a local processing or validation invariant fails."""


def expected_hourly_index(
    start: pd.Timestamp = FULL_START,
    end_exclusive: pd.Timestamp = FULL_END,
) -> pd.DatetimeIndex:
    """Return the complete half-open hourly UTC index."""
    return pd.date_range(
        start,
        end_exclusive - pd.Timedelta(hours=1),
        freq="1h",
        name="timestamp_utc",
    )


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPOSITORY_ROOT))
    except ValueError:
        return str(resolved)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Write deterministic JSON through an fsync'd temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_csv_atomically(frame: pd.DataFrame, path: Path) -> None:
    """Write a deterministic CSV without exposing a partial result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(
        temporary,
        index=False,
        date_format="%Y-%m-%dT%H:%M:%SZ",
        lineterminator="\n",
    )
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, float_precision="round_trip")


def _parse_utc(frame: pd.DataFrame, label: str) -> pd.DatetimeIndex:
    if "timestamp_utc" not in frame:
        raise GasProcessingError(f"{label} contains no timestamp_utc column.")
    parsed = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    if bool(parsed.isna().any()):
        raise GasProcessingError(f"{label} contains invalid timestamps.")
    return pd.DatetimeIndex(parsed, name="timestamp_utc")


def _validate_exact_index(
    timestamps: pd.DatetimeIndex,
    label: str,
    start: pd.Timestamp = FULL_START,
    end_exclusive: pd.Timestamp = FULL_END,
) -> None:
    expected = expected_hourly_index(start, end_exclusive)
    if len(timestamps) != len(expected):
        raise GasProcessingError(
            f"{label} has {len(timestamps)} rows; expected {len(expected)}."
        )
    if timestamps.has_duplicates:
        raise GasProcessingError(f"{label} contains duplicate timestamps.")
    if not timestamps.equals(expected):
        missing = expected.difference(timestamps)
        unexpected = timestamps.difference(expected)
        raise GasProcessingError(
            f"{label} hourly index mismatch: missing={len(missing)}, "
            f"unexpected={len(unexpected)}."
        )


def validate_raw_gas_integrity(
    raw_path: Path,
    validation_path: Path,
    expected_sha256: str = EXPECTED_RAW_GAS_SHA256,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Enforce the complete raw-gas gate before processing."""
    raw_path = _resolve(raw_path)
    validation_path = _resolve(validation_path)
    if not raw_path.exists() or not validation_path.exists():
        raise GasProcessingError("Raw gas input or validation report is missing.")
    observed_sha = sha256_file(raw_path)
    if observed_sha != expected_sha256:
        raise GasProcessingError(
            f"Raw gas SHA-256 mismatch: expected {expected_sha256}, "
            f"observed {observed_sha}."
        )
    documented = json.loads(validation_path.read_text(encoding="utf-8"))
    if not documented.get("validation_passed"):
        raise GasProcessingError("Documented raw gas validation did not pass.")
    raw = _read_csv(raw_path)
    if raw.shape != (27_024, 20):
        raise GasProcessingError(f"Raw gas dimensions are {raw.shape}, not (27024, 20).")
    if tuple(raw.columns) != RAW_GAS_COLUMNS:
        raise GasProcessingError("Raw gas columns do not match the authorised schema.")
    timestamps = _parse_utc(raw, "raw gas panel")
    _validate_exact_index(timestamps, "raw gas panel")
    raw["timestamp_utc"] = timestamps
    records = raw.where(pd.notna(raw), None).to_dict("records")
    recalculated = validate_rows(records, FULL_START, FULL_END)
    if not recalculated["validation_passed"]:
        raise GasProcessingError(
            "Recalculated raw gas validation failed: "
            + "; ".join(recalculated["failures"])
        )
    required_matches = (
        "row_count", "column_count", "minimum_timestamp_utc",
        "maximum_timestamp_utc", "duplicate_hour_row_count",
        "missing_hour_count", "percentile_ordering_violation_count",
        "gas_reconciliation_violation_count", "null_success_count_total",
        "pre_london_hour_count", "mixed_london_hour_count",
        "fully_post_london_hour_count", "mixed_london_eip1559_block_share",
    )
    discrepancies = {}
    for key in required_matches:
        documented_value = documented.get(key)
        recalculated_value = recalculated.get(key)
        if isinstance(documented_value, float) or isinstance(recalculated_value, float):
            matches = bool(
                np.isclose(
                    float(documented_value),
                    float(recalculated_value),
                    rtol=1e-12,
                    atol=1e-12,
                )
            )
        else:
            matches = documented_value == recalculated_value
        if not matches:
            discrepancies[key] = (documented_value, recalculated_value)
    if discrepancies:
        raise GasProcessingError(
            f"Raw gas validation report discrepancies: {discrepancies}."
        )
    integrity = {
        "raw_gas_sha256": observed_sha,
        "dimensions": {"rows": 27_024, "columns": 20},
        "coverage_start_utc": timestamps.min().isoformat(),
        "coverage_end_utc": timestamps.max().isoformat(),
        "duplicate_hour_count": 0,
        "missing_hour_count": 0,
        "percentile_ordering_violation_count": 0,
        "gas_reconciliation_violation_count": 0,
        "null_success_count_total": 0,
        "pre_london_hour_count": recalculated["pre_london_hour_count"],
        "mixed_london_hour_count": recalculated["mixed_london_hour_count"],
        "mixed_london_eip1559_block_share": recalculated[
            "mixed_london_eip1559_block_share"
        ],
        "post_london_hour_count": recalculated["fully_post_london_hour_count"],
        "raw_validation_report_reconciled": True,
    }
    return raw, integrity


def validate_market_integrity(
    market_path: Path,
    expected_sha256: str = EXPECTED_MARKET_SHA256,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Verify the immutable market panel before the exact UTC join."""
    market_path = _resolve(market_path)
    if not market_path.exists():
        raise GasProcessingError(f"Processed market panel is missing: {market_path}.")
    observed_sha = sha256_file(market_path)
    if observed_sha != expected_sha256:
        raise GasProcessingError(
            f"Market-panel SHA-256 mismatch: expected {expected_sha256}, "
            f"observed {observed_sha}."
        )
    market = _read_csv(market_path)
    if market.shape != (27_024, 17) or tuple(market.columns) != MARKET_COLUMNS:
        raise GasProcessingError(
            f"Market panel has unexpected schema or dimensions: {market.shape}."
        )
    timestamps = _parse_utc(market, "processed market panel")
    _validate_exact_index(timestamps, "processed market panel")
    market["timestamp_utc"] = timestamps
    return market, {
        "market_panel_sha256": observed_sha,
        "dimensions": {"rows": 27_024, "columns": 17},
        "coverage_start_utc": timestamps.min().isoformat(),
        "coverage_end_utc": timestamps.max().isoformat(),
        "duplicate_hour_count": 0,
        "missing_hour_count": 0,
    }


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=numerator.index, dtype=float)
    valid = numerator.notna() & denominator.notna() & denominator.gt(0)
    result.loc[valid] = numerator.loc[valid].astype(float) / denominator.loc[valid].astype(float)
    return result


def _fee_market_regime(timestamps: pd.Series) -> pd.Series:
    values = np.select(
        [timestamps < LONDON_HOUR, timestamps == LONDON_HOUR],
        ["pre_london", "mixed_london_hour"],
        default="post_london",
    )
    return pd.Series(values, index=timestamps.index, dtype="string")


def regime_thresholds(panel: pd.DataFrame) -> dict[str, float]:
    """Estimate full-sample thresholds for two descriptive classifications."""
    median = panel["median_effective_gas_price_gwei"]
    p99 = panel["p99_effective_gas_price_gwei"]
    utilisation = panel["target_normalised_block_utilisation"]
    failed = panel["failed_transaction_share"]
    p99_ratio = _safe_ratio(p99, median)
    median_change = np.log(median).diff()
    return {
        "classification_a_median_p75_gwei": float(median.quantile(0.75)),
        "classification_a_median_p95_gwei": float(median.quantile(0.95)),
        "classification_b_broad_median_p75_gwei": float(median.quantile(0.75)),
        "classification_b_tail_ratio_p95": float(p99_ratio.quantile(0.95)),
        "classification_b_utilisation_p95": float(utilisation.quantile(0.95)),
        "review_median_p95_gwei": float(median.quantile(0.95)),
        "review_p99_p95_gwei": float(p99.quantile(0.95)),
        "review_utilisation_p95": float(utilisation.quantile(0.95)),
        "review_failed_share_p95": float(failed.quantile(0.95)),
        "review_abs_median_log_change_p99": float(median_change.abs().quantile(0.99)),
    }


def build_processed_gas_panel(
    raw: pd.DataFrame,
    thresholds: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, dict[str, float], dict[str, int]]:
    """Preserve raw fields and add explicit gas-derived variables."""
    panel = raw.copy()
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    for column in RAW_GAS_COLUMNS[1:]:
        panel[column] = pd.to_numeric(panel[column], errors="coerce")
    zero_counts = {column: int(panel[column].eq(0).sum()) for column in LOG_PRICE_COLUMNS}
    nonpositive_counts = {
        column: int(panel[column].le(0).sum()) for column in LOG_PRICE_COLUMNS
    }
    if any(nonpositive_counts.values()):
        raise GasProcessingError(
            "Cannot log non-positive gas prices: " + str(nonpositive_counts)
        )

    median = panel["median_effective_gas_price_gwei"]
    panel["effective_gas_price_spread_p90_median_gwei"] = (
        panel["p90_effective_gas_price_gwei"] - median
    )
    panel["effective_gas_price_spread_p99_median_gwei"] = (
        panel["p99_effective_gas_price_gwei"] - median
    )
    panel["effective_gas_price_ratio_p90_median"] = _safe_ratio(
        panel["p90_effective_gas_price_gwei"], median
    )
    panel["effective_gas_price_ratio_p99_median"] = _safe_ratio(
        panel["p99_effective_gas_price_gwei"], median
    )
    panel["fee_market_regime"] = _fee_market_regime(panel["timestamp_utc"])
    fee_valid = panel["fee_market_regime"].ne("pre_london")
    panel["base_fee_share_of_median_effective_price"] = _safe_ratio(
        panel["median_base_fee_gwei"], median
    ).where(fee_valid)
    panel["priority_fee_share_of_median_effective_price"] = _safe_ratio(
        panel["median_priority_fee_gwei"], median
    ).where(fee_valid)

    for source, output in zip(LOG_PRICE_COLUMNS, LOG_COLUMNS, strict=True):
        panel[output] = np.log(panel[source])
    for source, output in zip(LOG_COLUMNS, LOG_CHANGE_COLUMNS, strict=True):
        panel[output] = panel[source].diff()
    panel["failed_transaction_share_change"] = panel[
        "failed_transaction_share"
    ].diff()
    panel["target_normalised_utilisation_change"] = panel[
        "target_normalised_block_utilisation"
    ].diff()

    used_thresholds = thresholds or regime_thresholds(panel)
    p75 = used_thresholds["classification_a_median_p75_gwei"]
    p95 = used_thresholds["classification_a_median_p95_gwei"]
    panel["gas_regime_candidate_a"] = pd.Series(
        np.select(
            [median.le(p75), median.le(p95)],
            ["normal", "stress"],
            default="extreme",
        ),
        index=panel.index,
        dtype="string",
    )

    panel["joint_broad_price_elevation"] = median.gt(
        used_thresholds["classification_b_broad_median_p75_gwei"]
    )
    panel["joint_upper_tail_bidding_pressure"] = panel[
        "effective_gas_price_ratio_p99_median"
    ].gt(used_thresholds["classification_b_tail_ratio_p95"])
    panel["joint_congestion_intensity"] = panel[
        "target_normalised_block_utilisation"
    ].gt(used_thresholds["classification_b_utilisation_p95"])
    joint_flags = panel[
        [
            "joint_broad_price_elevation",
            "joint_upper_tail_bidding_pressure",
            "joint_congestion_intensity",
        ]
    ].astype(int)
    panel["joint_pressure_condition_count"] = joint_flags.sum(axis=1)
    panel["gas_regime_candidate_b"] = pd.Series(
        np.select(
            [
                panel["joint_pressure_condition_count"].ge(2),
                panel["joint_upper_tail_bidding_pressure"],
                panel["joint_congestion_intensity"],
                panel["joint_broad_price_elevation"],
            ],
            [
                "compound_pressure",
                "upper_tail_bidding_pressure",
                "congestion_intensity",
                "broad_price_elevation",
            ],
            default="normal",
        ),
        index=panel.index,
        dtype="string",
    )
    return panel, used_thresholds, zero_counts


def cost_column_name(gas_units: int, scenario: str) -> str:
    return f"cost_usd_{gas_units // 1000}k_{scenario}"


def build_joined_panel(
    market: pd.DataFrame,
    gas: pd.DataFrame,
) -> pd.DataFrame:
    """Perform the exact UTC join and add hypothetical USD cost indices."""
    market_timestamps = pd.DatetimeIndex(pd.to_datetime(market["timestamp_utc"], utc=True))
    gas_timestamps = pd.DatetimeIndex(pd.to_datetime(gas["timestamp_utc"], utc=True))
    if not market_timestamps.equals(gas_timestamps):
        raise GasProcessingError("Market and gas timestamps do not reconcile exactly.")
    joined = market.merge(
        gas,
        on="timestamp_utc",
        how="inner",
        validate="one_to_one",
        sort=False,
    )
    if len(joined) != len(market) or len(joined) != len(gas):
        raise GasProcessingError("Exact market--gas join did not retain every input hour.")
    eth_price = joined["eth_price_usd"]
    for units in GAS_UNIT_SCENARIOS:
        for scenario, gas_price_column in GAS_PRICE_SCENARIOS.items():
            joined[cost_column_name(units, scenario)] = (
                units * joined[gas_price_column] * 1e-9 * eth_price
            )
    return joined


def construct_flagged_runs(
    flags: pd.Series,
    timestamps: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Return deterministic consecutive-hour run IDs and total run lengths."""
    flags = flags.fillna(False).astype(bool)
    consecutive = pd.to_datetime(timestamps, utc=True).diff().eq(pd.Timedelta(hours=1))
    new_run = flags & (~flags.shift(1, fill_value=False) | ~consecutive)
    identifiers = new_run.cumsum().where(flags).astype("Int64")
    lengths = identifiers.map(identifiers.value_counts()).astype("Int64")
    return identifiers, lengths


def build_extreme_review(
    joined: pd.DataFrame,
    thresholds: dict[str, float],
) -> pd.DataFrame:
    """Select every threshold-triggered gas hour without removing observations."""
    review_base = joined.copy()
    trigger_columns = {
        "trigger_median_effective_gas_price_above_p95": review_base[
            "median_effective_gas_price_gwei"
        ].gt(thresholds["review_median_p95_gwei"]),
        "trigger_p99_effective_gas_price_above_p95": review_base[
            "p99_effective_gas_price_gwei"
        ].gt(thresholds["review_p99_p95_gwei"]),
        "trigger_target_normalised_utilisation_above_p95": review_base[
            "target_normalised_block_utilisation"
        ].gt(thresholds["review_utilisation_p95"]),
        "trigger_failed_transaction_share_above_p95": review_base[
            "failed_transaction_share"
        ].gt(thresholds["review_failed_share_p95"]),
        "trigger_abs_median_gas_log_change_above_p99": review_base[
            "median_effective_gas_price_log_change"
        ].abs().gt(thresholds["review_abs_median_log_change_p99"]),
    }
    for name, values in trigger_columns.items():
        review_base[name] = values.astype(bool)
    flagged = review_base[list(trigger_columns)].any(axis=1)
    run_id, run_length = construct_flagged_runs(flagged, review_base["timestamp_utc"])
    review_base["consecutive_flagged_run_id"] = run_id
    review_base["consecutive_flagged_run_length_hours"] = run_length
    for label, column in (
        ("median", "median_effective_gas_price_gwei"),
        ("p90", "p90_effective_gas_price_gwei"),
        ("p99", "p99_effective_gas_price_gwei"),
    ):
        review_base[f"previous_hour_{label}_gas_price_gwei"] = review_base[column].shift(1)
        review_base[f"next_hour_{label}_gas_price_gwei"] = review_base[column].shift(-1)
    columns = [
        "timestamp_utc",
        *trigger_columns,
        "median_effective_gas_price_gwei",
        "p90_effective_gas_price_gwei",
        "p99_effective_gas_price_gwei",
        "median_base_fee_gwei",
        "median_priority_fee_gwei",
        "block_utilisation",
        "target_normalised_block_utilisation",
        "failed_transaction_share",
        "median_effective_gas_price_log_change",
        "eth_price_usd",
        "eth_log_return",
        "dai_peg_deviation",
        "usdc_peg_deviation",
        "gas_regime_candidate_a",
        "gas_regime_candidate_b",
        "consecutive_flagged_run_id",
        "consecutive_flagged_run_length_hours",
        "previous_hour_median_gas_price_gwei",
        "next_hour_median_gas_price_gwei",
        "previous_hour_p90_gas_price_gwei",
        "next_hour_p90_gas_price_gwei",
        "previous_hour_p99_gas_price_gwei",
        "next_hour_p99_gas_price_gwei",
    ]
    return review_base.loc[flagged, columns].reset_index(drop=True)


def transition_matrix(
    regimes: pd.Series,
    timestamps: pd.Series,
    states: Sequence[str],
    classification: str,
) -> list[dict[str, Any]]:
    """Calculate exhaustive transition counts and row probabilities."""
    current = regimes.astype("string")
    previous = current.shift(1)
    consecutive = pd.to_datetime(timestamps, utc=True).diff().eq(pd.Timedelta(hours=1))
    valid = current.isin(states) & previous.isin(states) & consecutive
    pairs = pd.DataFrame({"from": previous[valid], "to": current[valid]})
    counts = pairs.value_counts()
    records: list[dict[str, Any]] = []
    for origin in states:
        origin_total = int(sum(counts.get((origin, destination), 0) for destination in states))
        for destination in states:
            count = int(counts.get((origin, destination), 0))
            records.append(
                {
                    "classification": classification,
                    "from_regime": origin,
                    "to_regime": destination,
                    "transition_count": count,
                    "transition_probability": count / origin_total if origin_total else None,
                    "origin_transition_count": origin_total,
                }
            )
    return records


def regime_runs(
    regimes: pd.Series,
    timestamps: pd.Series,
    classification: str,
) -> pd.DataFrame:
    """Construct deterministic contiguous runs for a categorical series."""
    regimes = regimes.astype("string")
    consecutive = pd.to_datetime(timestamps, utc=True).diff().eq(pd.Timedelta(hours=1))
    new_run = regimes.ne(regimes.shift(1)) | ~consecutive
    run_ids = new_run.cumsum()
    source = pd.DataFrame(
        {"timestamp_utc": pd.to_datetime(timestamps, utc=True), "regime": regimes, "run_id": run_ids}
    )
    records = []
    for run_id, run in source.groupby("run_id", sort=True):
        records.append(
            {
                "classification": classification,
                "regime": str(run["regime"].iloc[0]),
                "run_id": int(run_id),
                "start_utc": run["timestamp_utc"].iloc[0].isoformat(),
                "end_utc": run["timestamp_utc"].iloc[-1].isoformat(),
                "length_hours": int(len(run)),
            }
        )
    return pd.DataFrame(records)


def _series_summary(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    result: dict[str, Any] = {
        "observations": int(len(values)),
        "mean": float(values.mean()),
        "standard_deviation": float(values.std()),
        "minimum": float(values.min()),
        "maximum": float(values.max()),
    }
    result["quantiles"] = {
        f"q{int(quantile * 100):02d}": float(values.quantile(quantile))
        for quantile in DESCRIPTIVE_QUANTILES
    }
    return result


def _run_summary(runs: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for regime, group in runs.groupby("regime", sort=True):
        lengths = group["length_hours"].astype(float)
        longest = group.loc[group["length_hours"].idxmax()]
        result[str(regime)] = {
            "run_count": int(len(group)),
            "mean_hours": float(lengths.mean()),
            "median_hours": float(lengths.median()),
            "p95_hours": float(lengths.quantile(0.95)),
            "maximum_hours": int(lengths.max()),
            "isolated_one_hour_run_count": int(lengths.eq(1).sum()),
            "isolated_one_hour_run_share": float(lengths.eq(1).mean()),
            "longest_run_start_utc": longest["start_utc"],
            "longest_run_end_utc": longest["end_utc"],
        }
    return result


def build_descriptive_summary(
    gas: pd.DataFrame,
    joined: pd.DataFrame,
    review: pd.DataFrame,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    """Build requested descriptive evidence without causal interpretation."""
    gas_series = (
        "median_effective_gas_price_gwei",
        "p90_effective_gas_price_gwei",
        "p99_effective_gas_price_gwei",
    )
    full = {column: _series_summary(gas[column]) for column in gas_series}
    period_masks = {
        "2021_partial": gas["timestamp_utc"].dt.year.eq(2021),
        "2022": gas["timestamp_utc"].dt.year.eq(2022),
        "2023": gas["timestamp_utc"].dt.year.eq(2023),
        "2024_through_june": gas["timestamp_utc"].dt.year.eq(2024),
    }
    annual = {
        period: {column: _series_summary(gas.loc[mask, column]) for column in gas_series}
        for period, mask in period_masks.items()
    }
    pre_post = {
        regime: {
            column: _series_summary(gas.loc[gas["fee_market_regime"].eq(regime), column])
            for column in gas_series
        }
        for regime in ("pre_london", "post_london")
    }
    post = gas.loc[gas["fee_market_regime"].eq("post_london")]
    post_fee = {
        column: _series_summary(post[column])
        for column in ("median_base_fee_gwei", "p95_base_fee_gwei", "median_priority_fee_gwei")
    }
    autocorrelation = {
        str(lag): float(gas["median_effective_gas_price_gwei"].autocorr(lag=lag))
        for lag in (1, 6, 12, 24, 72, 168)
    }
    regime_frequencies = {
        "classification_a": {
            str(key): int(value)
            for key, value in gas["gas_regime_candidate_a"].value_counts().reindex(
                CLASSIFICATION_A_STATES, fill_value=0
            ).items()
        },
        "classification_b": {
            str(key): int(value)
            for key, value in gas["gas_regime_candidate_b"].value_counts().reindex(
                CLASSIFICATION_B_STATES, fill_value=0
            ).items()
        },
    }
    for classification in regime_frequencies.values():
        classification["shares"] = {
            key: value / len(gas)
            for key, value in classification.items()
            if key != "shares"
        }
    transitions = {
        "classification_a": transition_matrix(
            gas["gas_regime_candidate_a"], gas["timestamp_utc"],
            CLASSIFICATION_A_STATES, "classification_a"
        ),
        "classification_b": transition_matrix(
            gas["gas_regime_candidate_b"], gas["timestamp_utc"],
            CLASSIFICATION_B_STATES, "classification_b"
        ),
    }
    runs_a = regime_runs(
        gas["gas_regime_candidate_a"], gas["timestamp_utc"], "classification_a"
    )
    runs_b = regime_runs(
        gas["gas_regime_candidate_b"], gas["timestamp_utc"], "classification_b"
    )
    targets = (
        "eth_log_return",
        "dai_abs_peg_deviation",
        "usdc_abs_peg_deviation",
    )
    correlation_sources = (
        "median_effective_gas_price_gwei",
        "median_effective_gas_price_log_change",
    )
    correlation_data = joined.loc[:, [*correlation_sources, *targets]].copy()
    correlation_data["absolute_eth_log_return"] = correlation_data["eth_log_return"].abs()
    correlations: dict[str, Any] = {}
    for source in correlation_sources:
        correlations[source] = {}
        for target in (*targets, "absolute_eth_log_return"):
            pair = correlation_data[[source, target]].dropna()
            correlations[source][target] = {
                "observations": int(len(pair)),
                "pearson": float(pair[source].corr(pair[target], method="pearson")),
                "spearman": float(pair[source].corr(pair[target], method="spearman")),
            }
    cost_columns = [
        cost_column_name(units, scenario)
        for units in GAS_UNIT_SCENARIOS
        for scenario in GAS_PRICE_SCENARIOS
    ]
    return {
        "scope": "descriptive evidence; no causal or final calibration interpretation",
        "regime_disclaimer": REGIME_DISCLAIMER,
        "cost_index_disclaimer": COST_DISCLAIMER,
        "quantile_method": "pandas linear interpolation over the full observed sample",
        "thresholds": thresholds,
        "full_sample_gas_price_distributions": full,
        "annual_gas_price_distributions": annual,
        "pre_post_london_effective_gas_price_distributions": pre_post,
        "post_london_fee_distributions": post_fee,
        "target_normalised_utilisation_distribution": _series_summary(
            gas["target_normalised_block_utilisation"]
        ),
        "failed_transaction_share_distribution": _series_summary(
            gas["failed_transaction_share"]
        ),
        "median_effective_gas_price_autocorrelation": autocorrelation,
        "candidate_regime_frequencies": regime_frequencies,
        "candidate_regime_transition_matrices": transitions,
        "candidate_regime_run_lengths": {
            "classification_a": _run_summary(runs_a),
            "classification_b": _run_summary(runs_b),
        },
        "extreme_review": {
            "row_count": int(len(review)),
            "trigger_counts": {
                column: int(review[column].astype(bool).sum())
                for column in review.columns
                if column.startswith("trigger_")
            },
            "run_count": int(review["consecutive_flagged_run_id"].nunique()),
            "isolated_one_hour_run_count": int(
                review.loc[
                    review["consecutive_flagged_run_length_hours"].eq(1),
                    "consecutive_flagged_run_id",
                ].nunique()
            ),
        },
        "gas_market_correlations": correlations,
        "standardised_cost_index_distributions": {
            column: _series_summary(joined[column]) for column in cost_columns
        },
    }


def _frame_values_match(left: pd.Series, right: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(left) or pd.api.types.is_datetime64_any_dtype(right):
        left_values = pd.DatetimeIndex(pd.to_datetime(left, utc=True))
        right_values = pd.DatetimeIndex(pd.to_datetime(right, utc=True))
        return left_values.equals(right_values)
    if pd.api.types.is_numeric_dtype(left) or pd.api.types.is_numeric_dtype(right):
        left_values = pd.to_numeric(left, errors="coerce").to_numpy(dtype=float)
        right_values = pd.to_numeric(right, errors="coerce").to_numpy(dtype=float)
        return bool(np.array_equal(left_values, right_values, equal_nan=True))
    return bool(left.fillna("<NA>").astype(str).equals(right.fillna("<NA>").astype(str)))


def _formula_match(observed: pd.Series, expected: pd.Series) -> tuple[bool, float]:
    left = pd.to_numeric(observed, errors="coerce").to_numpy(dtype=float)
    right = pd.to_numeric(expected, errors="coerce").to_numpy(dtype=float)
    match = bool(np.allclose(left, right, rtol=1e-12, atol=1e-12, equal_nan=True))
    finite = np.isfinite(left) & np.isfinite(right)
    error = float(np.max(np.abs(left[finite] - right[finite]))) if finite.any() else 0.0
    return match, error


def validate_processed_gas(
    processed_path: Path,
    raw_path: Path,
    thresholds: dict[str, float],
) -> tuple[dict[str, Any], list[str]]:
    """Validate persisted gas data against raw values and every formula."""
    failures: list[str] = []
    processed = _read_csv(processed_path)
    raw = _read_csv(raw_path)
    processed["timestamp_utc"] = _parse_utc(processed, "processed gas panel")
    raw["timestamp_utc"] = _parse_utc(raw, "raw gas panel")
    try:
        _validate_exact_index(pd.DatetimeIndex(processed["timestamp_utc"]), "processed gas panel")
    except GasProcessingError as exc:
        failures.append(str(exc))
    raw_matches = {}
    for column in RAW_GAS_COLUMNS:
        raw_matches[column] = _frame_values_match(processed[column], raw[column])
        if not raw_matches[column]:
            failures.append(f"raw column changed: {column}")
    expected, _, _ = build_processed_gas_panel(raw, thresholds)
    formula_columns = [column for column in expected.columns if column not in RAW_GAS_COLUMNS]
    formula_matches: dict[str, bool] = {}
    formula_errors: dict[str, float] = {}
    for column in formula_columns:
        if column in ("fee_market_regime", "gas_regime_candidate_a", "gas_regime_candidate_b"):
            match = _frame_values_match(processed[column], expected[column])
            error = 0.0
        elif expected[column].dtype == bool:
            match = _frame_values_match(processed[column], expected[column])
            error = 0.0
        else:
            match, error = _formula_match(processed[column], expected[column])
        formula_matches[column] = match
        formula_errors[column] = error
        if not match:
            failures.append(f"formula mismatch: {column}")
    log_change_missing = {
        column: int(processed[column].isna().sum()) for column in LOG_CHANGE_COLUMNS
    }
    if any(value != 1 for value in log_change_missing.values()):
        failures.append("log-change missing values are not confined to the first row")
    pre = processed["fee_market_regime"].eq("pre_london")
    structural_nulls_preserved = bool(
        processed.loc[
            pre,
            [
                "base_fee_share_of_median_effective_price",
                "priority_fee_share_of_median_effective_price",
            ],
        ].isna().all().all()
    )
    if not structural_nulls_preserved:
        failures.append("pre-London fee-share structural nulls changed")
    numeric = processed.select_dtypes(include=[np.number])
    infinity_count = int(np.isinf(numeric.to_numpy(dtype=float)).sum())
    if infinity_count:
        failures.append(f"processed gas panel contains {infinity_count} infinities")
    exhaustive_a = bool(processed["gas_regime_candidate_a"].isin(CLASSIFICATION_A_STATES).all())
    exhaustive_b = bool(processed["gas_regime_candidate_b"].isin(CLASSIFICATION_B_STATES).all())
    if not exhaustive_a or not exhaustive_b:
        failures.append("candidate regimes are not exhaustive and mutually exclusive")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "dimensions": {"rows": int(len(processed)), "columns": int(len(processed.columns))},
        "coverage_start_utc": processed["timestamp_utc"].min().isoformat(),
        "coverage_end_utc": processed["timestamp_utc"].max().isoformat(),
        "duplicate_timestamp_count": int(processed["timestamp_utc"].duplicated().sum()),
        "missing_hour_count": int(len(expected_hourly_index().difference(processed["timestamp_utc"]))),
        "raw_column_exact_matches": raw_matches,
        "formula_matches": formula_matches,
        "formula_max_absolute_errors": formula_errors,
        "log_change_missing_counts": log_change_missing,
        "structural_pre_london_nulls_preserved": structural_nulls_preserved,
        "infinity_count": infinity_count,
        "classification_a_exhaustive": exhaustive_a,
        "classification_b_exhaustive": exhaustive_b,
    }, failures


def validate_joined_panel(
    joined_path: Path,
    market_path: Path,
    processed_gas_path: Path,
) -> tuple[dict[str, Any], list[str]]:
    """Validate the persisted exact join and every standardised cost index."""
    failures: list[str] = []
    joined = _read_csv(joined_path)
    market = _read_csv(market_path)
    gas = _read_csv(processed_gas_path)
    for frame, label in ((joined, "joined panel"), (market, "market panel"), (gas, "gas panel")):
        frame["timestamp_utc"] = _parse_utc(frame, label)
    try:
        _validate_exact_index(pd.DatetimeIndex(joined["timestamp_utc"]), "joined panel")
    except GasProcessingError as exc:
        failures.append(str(exc))
    market_matches = {}
    for column in MARKET_COLUMNS:
        market_matches[column] = _frame_values_match(joined[column], market[column])
        if not market_matches[column]:
            failures.append(f"Phase 1A column changed: {column}")
    gas_matches = {}
    for column in gas.columns:
        gas_matches[column] = _frame_values_match(joined[column], gas[column])
        if not gas_matches[column]:
            failures.append(f"processed gas column changed in join: {column}")
    cost_formula_matches: dict[str, bool] = {}
    cost_formula_errors: dict[str, float] = {}
    for units in GAS_UNIT_SCENARIOS:
        for scenario, gas_price_column in GAS_PRICE_SCENARIOS.items():
            column = cost_column_name(units, scenario)
            expected = units * joined[gas_price_column] * 1e-9 * joined["eth_price_usd"]
            match, error = _formula_match(joined[column], expected)
            cost_formula_matches[column] = match
            cost_formula_errors[column] = error
            if not match:
                failures.append(f"cost-index formula mismatch: {column}")
    infinity_count = int(
        np.isinf(joined.select_dtypes(include=[np.number]).to_numpy(dtype=float)).sum()
    )
    if infinity_count:
        failures.append(f"joined panel contains {infinity_count} infinities")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "dimensions": {"rows": int(len(joined)), "columns": int(len(joined.columns))},
        "coverage_start_utc": joined["timestamp_utc"].min().isoformat(),
        "coverage_end_utc": joined["timestamp_utc"].max().isoformat(),
        "duplicate_timestamp_count": int(joined["timestamp_utc"].duplicated().sum()),
        "missing_hour_count": int(len(expected_hourly_index().difference(joined["timestamp_utc"]))),
        "unmatched_timestamp_count": 0 if len(joined) == len(market) == len(gas) else None,
        "phase_1a_column_exact_matches": market_matches,
        "processed_gas_column_exact_matches": gas_matches,
        "cost_index_formula_matches": cost_formula_matches,
        "cost_index_formula_max_absolute_errors": cost_formula_errors,
        "infinity_count": infinity_count,
    }, failures


def validate_extreme_review(
    review_path: Path,
    joined: pd.DataFrame,
    thresholds: dict[str, float],
) -> tuple[dict[str, Any], list[str]]:
    """Regenerate the review and verify deterministic selection and runs."""
    observed = _read_csv(review_path)
    observed["timestamp_utc"] = _parse_utc(observed, "extreme review")
    expected = build_extreme_review(joined, thresholds)
    expected["timestamp_utc"] = pd.to_datetime(expected["timestamp_utc"], utc=True)
    failures: list[str] = []
    try:
        pd.testing.assert_frame_equal(
            observed,
            expected,
            check_dtype=False,
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
        )
        deterministic_match = True
    except AssertionError as exc:
        deterministic_match = False
        failures.append(f"extreme review regeneration mismatch: {exc}")
    trigger_columns = [column for column in observed if column.startswith("trigger_")]
    every_row_triggered = bool(observed[trigger_columns].astype(bool).any(axis=1).all())
    if not every_row_triggered:
        failures.append("extreme review contains an untriggered row")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "dimensions": {"rows": int(len(observed)), "columns": int(len(observed.columns))},
        "deterministic_regeneration_match": deterministic_match,
        "every_row_has_trigger": every_row_triggered,
        "duplicate_timestamp_count": int(observed["timestamp_utc"].duplicated().sum()),
        "run_count": int(observed["consecutive_flagged_run_id"].nunique()),
    }, failures


def update_manifest(
    manifest_path: Path,
    raw_gas_path: Path,
    processed_path: Path,
    processed_sha: str,
    joined_path: Path,
    joined_sha: str,
    review_path: Path,
    review_sha: str,
    summary_path: Path,
    summary_sha: str,
    script_path: Path,
    script_sha: str,
    created_at: datetime,
    gas_validation_path: Path,
    joined_validation_path: Path,
    metadata_path: Path,
) -> int:
    """Attach processing provenance to the existing gas manifest row."""
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    additions = (
        "joined_file_path", "joined_file_size_bytes", "joined_sha256",
        "joined_validation_report_path", "gas_extreme_review_path",
        "gas_extreme_review_row_count", "gas_extreme_review_sha256",
        "descriptive_summary_path", "descriptive_summary_sha256",
    )
    for column in additions:
        if column not in fieldnames:
            fieldnames.append(column)
    updated = 0
    for row in rows:
        if row.get("raw_file_path") != _relative(raw_gas_path):
            continue
        existing_notes = row.get("notes", "").strip()
        added_notes = [
            disclaimer
            for disclaimer in (COST_DISCLAIMER, REGIME_DISCLAIMER)
            if disclaimer not in existing_notes
        ]
        notes = " ".join([existing_notes, *added_notes]).strip()
        row.update(
            {
                "processed_file_path": _relative(processed_path),
                "processed_file_size_bytes": str(processed_path.stat().st_size),
                "processed_sha256": processed_sha,
                "processing_script_path": _relative(script_path),
                "processing_script_sha256": script_sha,
                "processing_timestamp_utc": created_at.isoformat(),
                "processed_row_count": "27024",
                "processed_column_count": str(len(_read_csv(processed_path).columns)),
                "processed_validation_status": "passed",
                "processed_validation_report_path": _relative(gas_validation_path),
                "processing_metadata_path": _relative(metadata_path),
                "processed_transformation": (
                    "Raw gas columns preserved; explicit spreads, ratios, fee shares, "
                    "logs and changes; descriptive candidate regimes; exact Phase 1A "
                    "UTC join; hypothetical gas-unit cost indices only."
                ),
                "joined_file_path": _relative(joined_path),
                "joined_file_size_bytes": str(joined_path.stat().st_size),
                "joined_sha256": joined_sha,
                "joined_validation_report_path": _relative(joined_validation_path),
                "gas_extreme_review_path": _relative(review_path),
                "gas_extreme_review_row_count": str(len(_read_csv(review_path))),
                "gas_extreme_review_sha256": review_sha,
                "descriptive_summary_path": _relative(summary_path),
                "descriptive_summary_sha256": summary_sha,
                "notes": notes,
            }
        )
        updated += 1
    if updated != 1:
        raise GasProcessingError(f"Expected one gas manifest row, updated {updated}.")
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, manifest_path)
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gas-input", type=Path, default=DEFAULT_RAW_GAS)
    parser.add_argument("--gas-validation", type=Path, default=DEFAULT_RAW_GAS_VALIDATION)
    parser.add_argument("--market-input", type=Path, default=DEFAULT_MARKET)
    parser.add_argument("--gas-output-directory", type=Path, default=DEFAULT_GAS_OUTPUT_DIR)
    parser.add_argument("--joined-output-directory", type=Path, default=DEFAULT_JOINED_OUTPUT_DIR)
    parser.add_argument("--provenance-directory", type=Path, default=DEFAULT_PROVENANCE_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> int:
    """Run the deterministic local gas-processing workflow."""
    args = parse_args()
    raw_gas_path = _resolve(args.gas_input)
    raw_validation_path = _resolve(args.gas_validation)
    market_path = _resolve(args.market_input)
    manifest_path = _resolve(args.manifest)
    gas_output = _resolve(args.gas_output_directory)
    joined_output = _resolve(args.joined_output_directory)
    provenance_output = _resolve(args.provenance_directory)
    processed_path = gas_output / "dune_ethereum_hourly_gas_processed.csv"
    review_path = gas_output / "gas_extreme_review.csv"
    summary_path = gas_output / "dune_ethereum_hourly_gas_descriptive_summary.json"
    metadata_path = provenance_output / "dune_ethereum_hourly_gas_processing_metadata.json"
    gas_validation_path = provenance_output / "dune_ethereum_hourly_gas_processed_validation.json"
    joined_path = joined_output / "hourly_market_gas_panel.csv"
    joined_validation_path = provenance_output / "hourly_market_gas_panel_validation.json"

    raw, raw_integrity = validate_raw_gas_integrity(raw_gas_path, raw_validation_path)
    market, market_integrity = validate_market_integrity(market_path)
    raw_checksum_before = sha256_file(raw_gas_path)
    market_checksum_before = sha256_file(market_path)
    gas, thresholds, zero_counts = build_processed_gas_panel(raw)
    joined = build_joined_panel(market, gas)
    review = build_extreme_review(joined, thresholds)
    descriptive = build_descriptive_summary(gas, joined, review, thresholds)

    write_csv_atomically(gas, processed_path)
    write_csv_atomically(joined, joined_path)
    write_csv_atomically(review, review_path)
    _atomic_json(summary_path, descriptive)

    gas_validation_report, gas_failures = validate_processed_gas(
        processed_path, raw_gas_path, thresholds
    )
    joined_validation_report, joined_failures = validate_joined_panel(
        joined_path, market_path, processed_path
    )
    review_validation_report, review_failures = validate_extreme_review(
        review_path, joined, thresholds
    )
    if gas_failures or joined_failures or review_failures:
        raise GasProcessingError(
            "Processed validation failed: "
            + "; ".join([*gas_failures, *joined_failures, *review_failures])
        )
    _atomic_json(gas_validation_path, gas_validation_report)
    _atomic_json(joined_validation_path, joined_validation_report)

    raw_checksum_after = sha256_file(raw_gas_path)
    market_checksum_after = sha256_file(market_path)
    if raw_checksum_after != raw_checksum_before or market_checksum_after != market_checksum_before:
        raise GasProcessingError("An immutable input checksum changed during processing.")
    created_at = datetime.now(timezone.utc)
    script_path = Path(__file__).resolve()
    checksums = {
        "raw_gas_sha256": raw_checksum_after,
        "market_panel_sha256": market_checksum_after,
        "processed_gas_sha256": sha256_file(processed_path),
        "joined_panel_sha256": sha256_file(joined_path),
        "extreme_review_sha256": sha256_file(review_path),
        "descriptive_summary_sha256": sha256_file(summary_path),
        "processing_script_sha256": sha256_file(script_path),
    }
    metadata = {
        "creation_timestamp_utc": created_at.isoformat(),
        "inputs": {
            "raw_gas_path": _relative(raw_gas_path),
            "raw_gas_sha256": checksums["raw_gas_sha256"],
            "raw_gas_dimensions": raw_integrity["dimensions"],
            "market_panel_path": _relative(market_path),
            "market_panel_sha256": checksums["market_panel_sha256"],
            "market_panel_dimensions": market_integrity["dimensions"],
        },
        "outputs": {
            "processed_gas_path": _relative(processed_path),
            "processed_gas_dimensions": {"rows": len(gas), "columns": len(gas.columns)},
            "processed_gas_sha256": checksums["processed_gas_sha256"],
            "joined_panel_path": _relative(joined_path),
            "joined_panel_dimensions": {"rows": len(joined), "columns": len(joined.columns)},
            "joined_panel_sha256": checksums["joined_panel_sha256"],
            "extreme_review_path": _relative(review_path),
            "extreme_review_dimensions": {"rows": len(review), "columns": len(review.columns)},
            "extreme_review_sha256": checksums["extreme_review_sha256"],
            "descriptive_summary_path": _relative(summary_path),
            "descriptive_summary_sha256": checksums["descriptive_summary_sha256"],
        },
        "processing_script_path": _relative(script_path),
        "processing_script_sha256": checksums["processing_script_sha256"],
        "coverage": {
            "start_utc": FULL_START.isoformat(),
            "end_exclusive_utc": FULL_END.isoformat(),
            "expected_hours": 27_024,
        },
        "raw_integrity": raw_integrity,
        "market_integrity": market_integrity,
        "gas_price_zero_counts_before_logs": zero_counts,
        "quantile_thresholds": thresholds,
        "definitions": {
            "raw_preservation": "all 20 raw gas columns copied without changing observed values",
            "spread": "upper effective-gas-price percentile minus median effective gas price",
            "ratio": "upper effective-gas-price percentile divided by positive median effective gas price",
            "log_level": "natural logarithm of a strictly positive effective gas price",
            "log_change": "log current positive gas price minus log previous positive gas price",
            "ordinary_change": "current value minus previous-hour value",
            "fee_share": "fee component divided by median effective gas price; structurally missing before London",
            "fee_market_regime": "pre-London before the activation hour, mixed at the activation hour, and post-London afterwards",
            "classification_a": "normal <= full-sample median-gas P75; stress > P75 and <= P95; extreme > P95",
            "classification_b": "median > P75 flags broad price elevation; P99-to-median ratio > its P95 flags upper-tail pressure; utilisation > P95 flags congestion; two or more flags form compound pressure",
            "exact_join": "one-to-one inner join on identical UTC hourly timestamps; no repair or fill",
            "cost_index": "gas units multiplied by gas price gwei, 1e-9, and observed ETH/USD",
            "extreme_review": "union of the five documented strict-above-threshold triggers",
            "review_run": "consecutive flagged UTC hours; no repair or observation removal",
        },
        "london_treatment": {
            "activation_hour_utc": LONDON_HOUR.isoformat(),
            "pre_london": "base-fee and priority-fee shares remain structurally missing",
            "mixed_hour": "observed EIP-1559 share and fee values preserved without coercion",
            "post_london": "fee shares calculated only with observed fees and positive median effective price",
        },
        "standardised_cost_warning": COST_DISCLAIMER,
        "candidate_regime_warning": REGIME_DISCLAIMER,
        "validation": {
            "processed_gas": "passed",
            "joined_panel": "passed",
            "extreme_review": "passed",
            "processed_gas_report": _relative(gas_validation_path),
            "joined_panel_report": _relative(joined_validation_path),
        },
        "no_imputation_or_raw_value_change": True,
        "network_access": False,
    }
    _atomic_json(metadata_path, metadata)
    update_manifest(
        manifest_path,
        raw_gas_path,
        processed_path,
        checksums["processed_gas_sha256"],
        joined_path,
        checksums["joined_panel_sha256"],
        review_path,
        checksums["extreme_review_sha256"],
        summary_path,
        checksums["descriptive_summary_sha256"],
        script_path,
        checksums["processing_script_sha256"],
        created_at,
        gas_validation_path,
        joined_validation_path,
        metadata_path,
    )
    print(
        json.dumps(
            {
                "processed_gas": metadata["outputs"]["processed_gas_path"],
                "joined_panel": metadata["outputs"]["joined_panel_path"],
                "extreme_review": metadata["outputs"]["extreme_review_path"],
                "checksums": checksums,
                "validation": metadata["validation"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
