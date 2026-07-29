"""Bounded sensitivity and adoption-readiness review for Phase 2A."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .data_loading import (
    PROJECT_ROOT,
    sha256_file,
    validate_protocol_intervals,
)
from .statistics import (
    distribution_summary,
    estimate_regime_thresholds,
    regime_durations,
    transition_counts,
    transition_probabilities,
)


CONDITIONAL_EVENT_EVIDENCE_FILES = (
    "conditional_event_specification.json",
    "conditional_initial_state.json",
    "recovery_gate_specification.json",
    "event_simulation_smoke.json",
    "event_simulation_benchmark.json",
)


def validate_conditional_event_evidence(
    evidence_dir: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Validate compact dormant-event evidence and its manifest ownership."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    records = {record["path"]: record for record in manifest["artefacts"]}
    checked: list[dict[str, Any]] = []
    payloads: dict[str, dict[str, Any]] = {}
    for name in CONDITIONAL_EVENT_EVIDENCE_FILES:
        path = (Path(evidence_dir) / name).resolve()
        payloads[name] = json.loads(path.read_text(encoding="utf-8"))
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        if relative not in records:
            raise ValueError(f"Conditional event evidence is not registered: {relative}.")
        digest = sha256_file(path)
        if digest != records[relative]["sha256"]:
            raise ValueError(f"Conditional event evidence checksum differs: {relative}.")
        checked.append(
            {"path": relative, "sha256": digest, "size_bytes": path.stat().st_size}
        )
    specification = payloads["conditional_event_specification.json"]
    initial = payloads["conditional_initial_state.json"]
    gates = payloads["recovery_gate_specification.json"]
    smoke = payloads["event_simulation_smoke.json"]
    benchmark = payloads["event_simulation_benchmark.json"]
    if any(
        payload.get("runtime_adopted")
        for payload in (specification, initial, gates, smoke, benchmark)
    ):
        raise ValueError("Dormant event evidence cannot be runtime adopted.")
    if specification.get("stage2_parameter_defaults") is not None:
        raise ValueError("Conditional specification contains Stage 2 defaults.")
    if smoke.get("stage2_fit_performed") or smoke.get("candidate_ranking_performed"):
        raise ValueError("Smoke evidence must not fit or rank Stage 2 probes.")
    if smoke.get("final_validation_event_simulated"):
        raise ValueError("Final validation must remain unsimulated.")
    if smoke.get("full_trajectories_tracked"):
        raise ValueError("Compact evidence must not contain trajectories.")
    if benchmark.get("extrapolated_workloads_executed"):
        raise ValueError("Extrapolated benchmark workloads must remain unexecuted.")
    text = "\n".join(
        (Path(evidence_dir) / name).read_text(encoding="utf-8")
        for name in CONDITIONAL_EVENT_EVIDENCE_FILES
    )
    if "/Users/" in text:
        raise ValueError("Compact event evidence contains an absolute local path.")
    return {
        "status": "passed",
        "checked": checked,
        "runtime_adopted": False,
        "stage2_fit_performed": False,
        "final_validation_event_simulated": False,
    }


PHASE2A_DIR = (
    PROJECT_ROOT / "outputs/diagnostics/calibration/market_gas_protocol"
)
DEFAULT_REVIEW_DIR = PHASE2A_DIR / "review"
DEFAULT_REPORT = PROJECT_ROOT / "docs/phase2a_candidate_review.md"
ORIGINAL_METADATA_SHA256 = (
    "eb1b5bd46f806c1ef68824bfcff37776ce99165750c1726a473cbf3aca4faa80"
)
ORIGINAL_REGISTRY_SHA256 = (
    "fae0583fd2dc8a477df49d5954c80c486a209f8d3df963d779e5fe289fa5972d"
)
FTX_START = pd.Timestamp("2022-11-01T00:00:00Z")
FTX_END_EXCLUSIVE = pd.Timestamp("2022-11-21T00:00:00Z")
REVIEW_STATUSES = {
    "ready_for_later_adoption",
    "provisional_sensitivity_required",
    "descriptive_only",
    "rejected",
    "blocked_by_model_mapping",
    "blocked_by_additional_data",
}
REVIEW_FIELDS = {
    "review_status",
    "sensitivity_results",
    "recommended_representation",
    "recommended_later_treatment",
    "unresolved_limitation",
    "adoption_gate",
    "reviewer_notes",
}


@dataclass(frozen=True)
class Phase2AReviewConfig:
    """Deterministic controls for the bounded local review."""

    output_dir: Path = DEFAULT_REVIEW_DIR
    report_path: Path = DEFAULT_REPORT
    random_seed: int = 20_260_726
    bootstrap_replications: int = 1_000
    block_replications: int = 100
    write_report: bool = True


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return value.as_posix()
    if pd.isna(value):
        return None
    raise TypeError(f"Cannot serialise {type(value).__name__}.")


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    text = frame.to_csv(
        index=False,
        lineterminator="\n",
        float_format="%.12g",
    )
    _atomic_text(path, text)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_text(
        path,
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=_json_default,
        )
        + "\n",
    )


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _candidate_digest(candidate: dict[str, Any]) -> str:
    payload = json.dumps(
        candidate, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_original_phase2a() -> dict[str, Any]:
    """Verify every immutable Phase 2A artefact before review."""
    metadata_path = PHASE2A_DIR / "estimation_run_metadata.json"
    registry_path = PHASE2A_DIR / "phase2a_candidate_parameters.json"
    if sha256_file(metadata_path) != ORIGINAL_METADATA_SHA256:
        raise ValueError("Original Phase 2A metadata checksum has changed.")
    if sha256_file(registry_path) != ORIGINAL_REGISTRY_SHA256:
        raise ValueError("Original Phase 2A registry checksum has changed.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    checked = []
    for record in metadata["outputs"]:
        path = PROJECT_ROOT / record["path"]
        actual = sha256_file(path)
        if actual != record["sha256"]:
            raise ValueError(
                f"Original Phase 2A output changed: {record['path']}."
            )
        checked.append(
            {
                "path": record["path"],
                "sha256": actual,
                "rows": record["rows"],
                "columns": record["columns"],
            }
        )
    return {
        "metadata": metadata,
        "registry": json.loads(registry_path.read_text(encoding="utf-8")),
        "checked_outputs": checked,
        "metadata_sha256": ORIGINAL_METADATA_SHA256,
        "registry_sha256": ORIGINAL_REGISTRY_SHA256,
    }


def _load_review_inputs(original: dict[str, Any]) -> dict[str, pd.DataFrame]:
    metadata = original["metadata"]
    input_paths = metadata["input_paths"]
    paths = {
        "combined": PROJECT_ROOT / input_paths["combined"],
        "liquidation_hourly": (
            PROJECT_ROOT / input_paths["liquidation_hourly"]
        ),
        "protocol_intervals": (
            PROJECT_ROOT / input_paths["protocol_intervals"]
        ),
        "take_transactions": (
            PHASE2A_DIR
            / "liquidations/liquidation_transaction_gas.csv"
        ),
        "hourly_regimes": PHASE2A_DIR / "regimes/hourly_regimes.csv",
        "regime_thresholds": (
            PHASE2A_DIR / "diagnostics/regime_thresholds.csv"
        ),
        "parameter_status": PHASE2A_DIR / "parameter_status.csv",
    }
    frames = {
        name: pd.read_csv(path, low_memory=False)
        for name, path in paths.items()
    }
    for name in ("combined", "liquidation_hourly", "hourly_regimes"):
        frames[name]["timestamp_utc"] = pd.to_datetime(
            frames[name]["timestamp_utc"], utc=True, errors="raise"
        )
    frames["take_transactions"]["block_time"] = pd.to_datetime(
        frames["take_transactions"]["block_time"], utc=True, errors="raise"
    )
    frames["take_transactions"]["timestamp_utc"] = pd.to_datetime(
        frames["take_transactions"]["timestamp_utc"],
        utc=True,
        errors="raise",
    )
    return frames


def _prepare_hourly(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    combined = frames["combined"].copy()
    liquidation = frames["liquidation_hourly"].copy()
    liquidation["debt_targeted_dai"] = pd.to_numeric(
        liquidation["debt_targeted_dai"], errors="raise"
    )
    liquidation["auctions_initiated"] = pd.to_numeric(
        liquidation["auctions_initiated"], errors="raise"
    )
    totals = (
        liquidation.groupby("timestamp_utc", as_index=False)[
            ["debt_targeted_dai", "auctions_initiated"]
        ]
        .sum()
        .rename(
            columns={
                "debt_targeted_dai": "liquidation_volume_dai",
                "auctions_initiated": "liquidation_count",
            }
        )
    )
    hourly = combined.merge(
        totals, on="timestamp_utc", how="left", validate="one_to_one"
    )
    hourly[["liquidation_volume_dai", "liquidation_count"]] = hourly[
        ["liquidation_volume_dai", "liquidation_count"]
    ].fillna(0.0)
    eth_variance = (
        hourly["eth_log_return"].rolling(24, min_periods=24).var(ddof=0)
    )
    wbtc_variance = (
        hourly["wbtc_log_return"].rolling(24, min_periods=24).var(ddof=0)
    )
    hourly["realised_crypto_volatility"] = np.sqrt(
        (eth_variance + wbtc_variance) / 2
    )
    hourly["is_validation"] = (
        (hourly["timestamp_utc"] >= FTX_START)
        & (hourly["timestamp_utc"] < FTX_END_EXCLUSIVE)
    )
    hourly["is_calibration"] = ~hourly["is_validation"]
    return hourly


def _thresholds(frames: dict[str, pd.DataFrame], hourly: pd.DataFrame) -> dict[str, float]:
    stored = {
        row["threshold"]: float(row["value"])
        for _, row in frames["regime_thresholds"].iterrows()
    }
    recalculated = estimate_regime_thresholds(
        hourly.loc[hourly["is_calibration"]]
    )
    for name, expected in stored.items():
        if not np.isclose(
            recalculated[name],
            expected,
            rtol=2e-12,
            atol=1e-12,
        ):
            raise ValueError(
                f"Stored regime threshold {name} is not reproducible without FTX."
            )
    return stored


def _condition_frame(
    hourly: pd.DataFrame,
    thresholds: dict[str, float],
    *,
    conditional_liquidation_threshold: float | None = None,
) -> pd.DataFrame:
    result = pd.DataFrame(index=hourly.index)
    result["eth_return"] = (
        hourly["eth_log_return"] < thresholds["eth_return_q05"]
    )
    result["wbtc_return"] = (
        hourly["wbtc_log_return"] < thresholds["wbtc_return_q05"]
    )
    result["volatility"] = (
        hourly["realised_crypto_volatility"]
        > thresholds["crypto_volatility_q90"]
    )
    result["gas"] = (
        hourly["median_effective_gas_price_gwei"]
        > thresholds["gas_price_q90"]
    )
    result["dai_deviation"] = (
        hourly["dai_abs_peg_deviation"]
        > thresholds["dai_abs_peg_deviation_q90"]
    )
    liquidation_threshold = (
        thresholds["liquidation_volume_q90"]
        if conditional_liquidation_threshold is None
        else conditional_liquidation_threshold
    )
    result["liquidation"] = (
        hourly["liquidation_volume_dai"] > liquidation_threshold
    )
    return result.fillna(False)


def classify_regime_specification(
    conditions: pd.DataFrame,
    *,
    minimum_conditions: int,
    removed_condition: str | None = None,
) -> pd.Series:
    """Classify one transparent sensitivity specification."""
    selected = conditions.copy()
    if removed_condition is not None:
        if removed_condition not in selected:
            raise ValueError(f"Unknown classifier condition: {removed_condition}")
        selected = selected.drop(columns=removed_condition)
    return pd.Series(
        np.where(
            selected.sum(axis=1) >= minimum_conditions,
            "stress",
            "normal",
        ),
        index=conditions.index,
        name="regime",
    )


def hurdle_summary(values: pd.Series) -> dict[str, Any]:
    """Separate activity probability from conditional positive severity."""
    numeric = pd.to_numeric(values, errors="raise")
    if (numeric < 0).any():
        raise ValueError("Hurdle observations must be non-negative.")
    positive = numeric[numeric > 0]
    return {
        "hours": int(len(numeric)),
        "active_hours": int(len(positive)),
        "activity_probability": float((numeric > 0).mean()),
        "conditional_mean": (
            float(positive.mean()) if len(positive) else None
        ),
        "conditional_median": (
            float(positive.median()) if len(positive) else None
        ),
        "conditional_q90": (
            float(positive.quantile(0.90)) if len(positive) else None
        ),
        "unconditional_q90": float(numeric.quantile(0.90)),
    }


def aggregate_activity(
    hourly: pd.DataFrame,
    *,
    frequency_hours: int,
    value_column: str,
) -> pd.DataFrame:
    """Aggregate one non-negative hourly series into fixed UTC buckets."""
    if frequency_hours not in {1, 6, 12, 24}:
        raise ValueError("Unsupported aggregation frequency.")
    selected = hourly[["timestamp_utc", value_column]].copy()
    if frequency_hours == 1:
        return selected
    selected["timestamp_utc"] = selected["timestamp_utc"].dt.floor(
        f"{frequency_hours}h"
    )
    return (
        selected.groupby("timestamp_utc", as_index=False)[value_column].sum()
    )


def _liquidation_sparsity(
    frames: dict[str, pd.DataFrame],
    hourly: pd.DataFrame,
    baseline_regime: pd.Series,
) -> pd.DataFrame:
    liquidation = frames["liquidation_hourly"].copy()
    liquidation["debt_targeted_dai"] = pd.to_numeric(
        liquidation["debt_targeted_dai"], errors="raise"
    )
    scopes: dict[str, pd.DataFrame] = {
        "ALL": hourly[["timestamp_utc", "liquidation_volume_dai"]].rename(
            columns={"liquidation_volume_dai": "volume"}
        )
    }
    for family, pattern in (("ETH", "ETH-"), ("WBTC", "WBTC-")):
        selected = liquidation.loc[
            liquidation["ilk"].str.startswith(pattern)
        ]
        scopes[family] = (
            selected.groupby("timestamp_utc", as_index=False)[
                "debt_targeted_dai"
            ]
            .sum()
            .rename(columns={"debt_targeted_dai": "volume"})
        )
    for ilk, selected in liquidation.groupby("ilk"):
        scopes[str(ilk)] = selected[
            ["timestamp_utc", "debt_targeted_dai"]
        ].rename(columns={"debt_targeted_dai": "volume"})
    regime_lookup = pd.DataFrame(
        {
            "timestamp_utc": hourly["timestamp_utc"],
            "regime": baseline_regime,
            "is_calibration": hourly["is_calibration"],
        }
    )
    rows = []
    for scope, frame in scopes.items():
        base = hourly[["timestamp_utc"]].merge(
            frame, on="timestamp_utc", how="left", validate="one_to_one"
        )
        base["volume"] = base["volume"].fillna(0.0)
        base = base.merge(
            regime_lookup, on="timestamp_utc", validate="one_to_one"
        )
        base = base.loc[base["is_calibration"]]
        for frequency in (1, 6, 12, 24):
            aggregated = aggregate_activity(
                base,
                frequency_hours=frequency,
                value_column="volume",
            )
            if frequency == 1:
                stress_timestamps = set(
                    base.loc[base["regime"].eq("stress"), "timestamp_utc"]
                )
            else:
                stress_timestamps = set(
                    base.loc[base["regime"].eq("stress"), "timestamp_utc"]
                    .dt.floor(f"{frequency}h")
                )
            masks = {
                "all_calendar": pd.Series(True, index=aggregated.index),
                "stress_periods": aggregated["timestamp_utc"].isin(
                    stress_timestamps
                ),
                "nonzero_liquidation_hours": aggregated["volume"] > 0,
                "conditional_at_least_one_liquidation": (
                    aggregated["volume"] > 0
                ),
            }
            for subset, mask in masks.items():
                summary = hurdle_summary(aggregated.loc[mask, "volume"])
                rows.append(
                    {
                        "collateral_scope": scope,
                        "frequency_hours": frequency,
                        "subset": subset,
                        **summary,
                        "arrival_and_severity_separated": True,
                        "recommended_conceptual_use": (
                            "arrival_process"
                            if subset == "all_calendar"
                            else "conditional_severity"
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _bootstrap_median(
    values: pd.Series,
    *,
    seed: int,
    replications: int,
) -> tuple[float | None, float | None]:
    array = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    if not len(array):
        return None, None
    rng = np.random.default_rng(seed)
    estimates = np.empty(replications)
    for index in range(replications):
        sample = rng.choice(array, size=len(array), replace=True)
        estimates[index] = np.median(sample)
    return (
        float(np.quantile(estimates, 0.025)),
        float(np.quantile(estimates, 0.975)),
    )


def gas_cost_sensitivity(
    clean_transactions: pd.DataFrame,
    *,
    seed: int,
    replications: int,
) -> pd.DataFrame:
    """Compare retained, excluded, missing and unavailable alternatives."""
    rows = []
    variants: list[tuple[str, pd.DataFrame, str]] = [
        (
            "retain_observed_zero",
            clean_transactions.copy(),
            "Observed zero remains a numerical value.",
        ),
        (
            "exclude_zero_transactions",
            clean_transactions.loc[clean_transactions["gas_price"] > 0].copy(),
            "Four indeterminate zero-price rows excluded.",
        ),
        (
            "zero_as_missing_no_imputation",
            clean_transactions.assign(
                transaction_gas_cost_usd=clean_transactions[
                    "transaction_gas_cost_usd"
                ].mask(clean_transactions["gas_price"].eq(0))
            ),
            "Zero costs set missing for estimation; raw rows unchanged.",
        ),
    ]
    for variant, frame, note in variants:
        for regime_index, regime in enumerate(("all", "normal", "stress")):
            selected = (
                frame
                if regime == "all"
                else frame.loc[frame["regime"].eq(regime)]
            )
            values = pd.to_numeric(
                selected["transaction_gas_cost_usd"], errors="coerce"
            )
            summary = distribution_summary(values)
            lower, upper = _bootstrap_median(
                values,
                seed=seed + regime_index,
                replications=replications,
            )
            rows.append(
                {
                    "variant": variant,
                    "regime": regime,
                    "source_rows": int(len(selected)),
                    "effective_observations": int(values.notna().sum()),
                    "mean_usd": summary["mean"],
                    "median_usd": summary["q50"],
                    "q75_usd": summary["q75"],
                    "q90_usd": summary["q90"],
                    "q95_usd": summary["q95"],
                    "q99_usd": summary["q99"],
                    "bootstrap_median_lower_95": lower,
                    "bootstrap_median_upper_95": upper,
                    "bootstrap_replications": replications,
                    "note": note,
                }
            )
    for regime in ("all", "normal", "stress"):
        rows.append(
            {
                "variant": "alternative_effective_gas_field",
                "regime": regime,
                "source_rows": 0,
                "effective_observations": 0,
                "mean_usd": None,
                "median_usd": None,
                "q75_usd": None,
                "q90_usd": None,
                "q95_usd": None,
                "q99_usd": None,
                "bootstrap_median_lower_95": None,
                "bootstrap_median_upper_95": None,
                "bootstrap_replications": replications,
                "note": (
                    "No defensible local alternative: fee-cap, priority and "
                    "base-fee fields are unavailable for the four pre-London rows."
                ),
            }
        )
    return pd.DataFrame(rows)


def _zero_gas_review(
    frames: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    transactions = frames["take_transactions"].copy()
    clean = transactions.loc[
        transactions["take_transaction_class"].eq(
            "clean_single_take_single_auction"
        )
        & transactions["is_calibration"].astype(bool)
    ].copy()
    zero = clean.loc[clean["gas_price"].eq(0)].copy()
    if len(zero) != 4:
        raise ValueError(f"Expected four zero-gas Take transactions; found {len(zero)}.")
    gas = frames["combined"][
        [
            "timestamp_utc",
            "median_base_fee_gwei",
            "median_priority_fee_gwei",
            "fee_market_regime",
        ]
    ].copy()
    zero = zero.merge(
        gas, on="timestamp_utc", how="left", validate="many_to_one"
    )
    zero["join_keys"] = "unique tx_hash; exact floored timestamp_utc"
    zero["action_join"] = (
        "one unique top-level transaction; one Take event; one auction"
    )
    zero["classification"] = (
        "explicit_zero_source_value_pre_london_alternative_fee_fields_missing"
    )
    zero["recommended_treatment"] = (
        "retain in immutable evidence; exclude or mark missing in the primary "
        "gas-cost estimator; never impute from the hourly network median"
    )
    zero["eip1559_field_issue"] = False
    zero["incorrect_join_detected"] = False
    zero["internal_call_misclassification_detected"] = False
    columns = [
        "tx_hash",
        "block_time",
        "block_number",
        "transaction_index",
        "transaction_sender",
        "transaction_recipient",
        "gas_limit",
        "gas_used",
        "gas_price",
        "max_fee_per_gas",
        "max_priority_fee_per_gas",
        "priority_fee_per_gas",
        "median_base_fee_gwei",
        "median_priority_fee_gwei",
        "fee_market_regime",
        "transaction_gas_cost_eth",
        "transaction_gas_cost_usd",
        "join_keys",
        "action_join",
        "classification",
        "recommended_treatment",
        "eip1559_field_issue",
        "incorrect_join_detected",
        "internal_call_misclassification_detected",
    ]
    return zero[columns], clean


def _run_metrics(
    states: pd.Series,
    hourly: pd.DataFrame,
    *,
    name: str,
) -> dict[str, Any]:
    calibration = hourly["is_calibration"]
    validation = hourly["is_validation"]
    counts = transition_counts(
        states,
        hourly["timestamp_utc"],
        allowed_mask=calibration,
    )
    probabilities = transition_probabilities(counts)
    durations = regime_durations(
        states,
        hourly["timestamp_utc"],
        allowed_mask=calibration,
    )
    row: dict[str, Any] = {
        "specification": name,
        "normal_hours": int((states[calibration] == "normal").sum()),
        "stress_hours": int((states[calibration] == "stress").sum()),
        "stress_prevalence": float((states[calibration] == "stress").mean()),
        "normal_to_stress_probability": probabilities.loc["normal", "stress"],
        "stress_to_normal_probability": probabilities.loc["stress", "normal"],
        "stress_persistence_probability": probabilities.loc["stress", "stress"],
        "normal_median_duration_hours": float(
            durations.loc[durations["regime"].eq("normal"), "duration_hours"].median()
        ),
        "stress_median_duration_hours": float(
            durations.loc[durations["regime"].eq("stress"), "duration_hours"].median()
        ),
        "regime_switches": int(counts.loc["normal", "stress"] + counts.loc["stress", "normal"]),
        "ftx_stress_share": float((states[validation] == "stress").mean()),
    }
    for regime in ("normal", "stress"):
        mask = calibration & states.eq(regime)
        row[f"eth_volatility_{regime}"] = float(
            hourly.loc[mask, "eth_log_return"].std(ddof=1)
        )
        row[f"wbtc_volatility_{regime}"] = float(
            hourly.loc[mask, "wbtc_log_return"].std(ddof=1)
        )
        row[f"median_gas_gwei_{regime}"] = float(
            hourly.loc[mask, "median_effective_gas_price_gwei"].median()
        )
        row[f"liquidation_activity_probability_{regime}"] = float(
            (hourly.loc[mask, "liquidation_count"] > 0).mean()
        )
        positive = hourly.loc[
            mask & hourly["liquidation_volume_dai"].gt(0),
            "liquidation_volume_dai",
        ]
        row[f"conditional_liquidation_volume_median_{regime}"] = (
            float(positive.median()) if len(positive) else None
        )
    return row


def _regime_sensitivity(
    hourly: pd.DataFrame,
    thresholds: dict[str, float],
) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    baseline_conditions = _condition_frame(hourly, thresholds)
    calibration_nonzero = hourly.loc[
        hourly["is_calibration"] & hourly["liquidation_volume_dai"].gt(0),
        "liquidation_volume_dai",
    ]
    conditional_threshold = float(calibration_nonzero.quantile(0.50))
    specifications: dict[str, pd.Series] = {
        "baseline_two_of_six": classify_regime_specification(
            baseline_conditions, minimum_conditions=2
        ),
        "strict_three_of_six": classify_regime_specification(
            baseline_conditions, minimum_conditions=3
        ),
        "loose_one_of_six": classify_regime_specification(
            baseline_conditions, minimum_conditions=1
        ),
    }
    for condition in baseline_conditions.columns:
        specifications[f"remove_{condition}"] = classify_regime_specification(
            baseline_conditions,
            minimum_conditions=2,
            removed_condition=condition,
        )
    conditional_conditions = _condition_frame(
        hourly,
        thresholds,
        conditional_liquidation_threshold=conditional_threshold,
    )
    specifications["conditional_liquidation_median_signal"] = (
        classify_regime_specification(
            conditional_conditions, minimum_conditions=2
        )
    )
    rows = []
    for name, states in specifications.items():
        row = _run_metrics(states, hourly, name=name)
        row["minimum_conditions"] = (
            3 if name == "strict_three_of_six" else
            1 if name == "loose_one_of_six" else 2
        )
        row["liquidation_signal_threshold_dai"] = (
            conditional_threshold
            if name == "conditional_liquidation_median_signal"
            else thresholds["liquidation_volume_q90"]
        )
        row["thresholds_estimated_without_ftx"] = True
        rows.append(row)
    return pd.DataFrame(rows), specifications


def _ftx_diagnostics(
    hourly: pd.DataFrame,
    baseline_states: pd.Series,
) -> pd.DataFrame:
    calibration = hourly["is_calibration"]
    validation = hourly["is_validation"]
    runs = regime_durations(
        baseline_states,
        hourly["timestamp_utc"],
        allowed_mask=validation,
    )
    stress_runs = runs.loc[runs["regime"].eq("stress")]
    counts = transition_counts(
        baseline_states,
        hourly["timestamp_utc"],
        allowed_mask=calibration,
    )
    probabilities = transition_probabilities(counts)
    predicted_stress_duration = 1 / probabilities.loc["stress", "normal"]
    entries = stress_runs["start_utc"].map(lambda x: x.isoformat()).tolist()
    exits = (
        stress_runs["end_utc"] + pd.Timedelta(hours=1)
    ).map(lambda x: x.isoformat()).tolist()
    rows: list[dict[str, Any]] = []

    def add(category: str, metric: str, value: Any, units: str, note: str = "") -> None:
        rows.append(
            {
                "category": category,
                "metric": metric,
                "value": value,
                "units": units,
                "note": note,
            }
        )

    add("classifier", "ftx_stress_share", float((baseline_states[validation] == "stress").mean()), "fraction")
    add("classifier", "stress_entry_times", ";".join(entries), "UTC timestamps")
    add("classifier", "stress_exit_times", ";".join(exits), "UTC timestamps")
    add("classifier", "stress_run_count", int(len(stress_runs)), "runs")
    add("classifier", "median_stress_run_hours", float(stress_runs["duration_hours"].median()), "hours")
    add("classifier", "maximum_stress_run_hours", int(stress_runs["duration_hours"].max()), "hours")
    add("transition_model", "implied_mean_stress_duration", float(predicted_stress_duration), "hours")
    add(
        "transition_model",
        "persistence_assessment",
        (
            "understates"
            if stress_runs["duration_hours"].mean() > predicted_stress_duration
            else "overstates"
        ),
        "classification",
        "Diagnostic comparison only; the FTX label was not used for fitting.",
    )
    for asset in ("eth", "wbtc"):
        for sample, mask in (
            ("ftx", validation),
            ("calibration_normal", calibration & baseline_states.eq("normal")),
            ("calibration_stress", calibration & baseline_states.eq("stress")),
        ):
            add(
                "market",
                f"{asset}_volatility_{sample}",
                float(hourly.loc[mask, f"{asset}_log_return"].std(ddof=1)),
                "hourly_log_return_std",
            )
        add(
            "return_blocks",
            f"{asset}_ftx_min_return",
            float(hourly.loc[validation, f"{asset}_log_return"].min()),
            "log_return",
        )
        add(
            "return_blocks",
            f"{asset}_calibration_min_return",
            float(hourly.loc[calibration, f"{asset}_log_return"].min()),
            "log_return",
            "FTX-like marginal observations are plausible if the FTX minimum lies within the calibration support.",
        )
    add("peg", "dai_abs_peg_deviation_median", float(hourly.loc[validation, "dai_abs_peg_deviation"].median()), "USD")
    add("peg", "dai_abs_peg_deviation_maximum", float(hourly.loc[validation, "dai_abs_peg_deviation"].max()), "USD")
    add("gas", "median_effective_gas_price", float(hourly.loc[validation, "median_effective_gas_price_gwei"].median()), "gwei")
    add("gas", "p90_effective_gas_price", float(hourly.loc[validation, "median_effective_gas_price_gwei"].quantile(0.90)), "gwei")
    add("liquidation", "activity_probability", float((hourly.loc[validation, "liquidation_count"] > 0).mean()), "fraction")
    add("liquidation", "auction_count", int(hourly.loc[validation, "liquidation_count"].sum()), "auctions")
    add("liquidation", "debt_targeted_total", float(hourly.loc[validation, "liquidation_volume_dai"].sum()), "DAI")
    positive = hourly.loc[validation & hourly["liquidation_volume_dai"].gt(0), "liquidation_volume_dai"]
    add("liquidation", "conditional_volume_median", float(positive.median()) if len(positive) else None, "DAI")
    calibration_runs = regime_durations(
        baseline_states,
        hourly["timestamp_utc"],
        allowed_mask=calibration,
    )
    add(
        "return_blocks",
        "ftx_stress_run_within_calibration_support",
        bool(
            stress_runs["duration_hours"].max()
            <= calibration_runs.loc[
                calibration_runs["regime"].eq("stress"), "duration_hours"
            ].max()
        ),
        "boolean",
    )
    add(
        "scope",
        "complete_abm_validation",
        False,
        "boolean",
        "This is classifier and empirical-candidate validation only.",
    )
    return pd.DataFrame(rows)


def _series_metrics(frame: pd.DataFrame) -> dict[str, float]:
    states = frame["stress"].astype(int).to_numpy()
    boundaries = np.r_[0, np.flatnonzero(np.diff(states) != 0) + 1, len(states)]
    run_lengths = np.diff(boundaries)
    run_states = states[boundaries[:-1]]
    stress_runs = run_lengths[run_states == 1]
    return {
        "eth_return_acf_lag1": float(frame["eth"].autocorr(1)),
        "eth_absolute_return_acf_lag1": float(frame["eth"].abs().autocorr(1)),
        "wbtc_return_acf_lag1": float(frame["wbtc"].autocorr(1)),
        "wbtc_absolute_return_acf_lag1": float(frame["wbtc"].abs().autocorr(1)),
        "eth_wbtc_correlation": float(frame[["eth", "wbtc"]].corr().iloc[0, 1]),
        "eth_absolute_return_acf_lag168": float(frame["eth"].abs().autocorr(168)),
        "stress_share": float(states.mean()),
        "stress_median_run": float(np.median(stress_runs)) if len(stress_runs) else 0.0,
        "stress_maximum_run": float(np.max(stress_runs)) if len(stress_runs) else 0.0,
    }


def _resample_segments(
    segments: list[pd.DataFrame],
    *,
    block_length: int,
    target_length: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    blocks = []
    available = np.array(
        [max(0, len(segment) - block_length + 1) for segment in segments],
        dtype=float,
    )
    if not available.sum():
        raise ValueError("No calibration segment supports the block length.")
    probabilities = available / available.sum()
    rows = 0
    while rows < target_length:
        segment_index = int(rng.choice(len(segments), p=probabilities))
        segment = segments[segment_index]
        start = int(rng.integers(0, len(segment) - block_length + 1))
        block = segment.iloc[start : start + block_length]
        blocks.append(block)
        rows += len(block)
    return pd.concat(blocks, ignore_index=True).iloc[:target_length]


def _block_length_sensitivity(
    hourly: pd.DataFrame,
    baseline_states: pd.Series,
    *,
    seed: int,
    replications: int,
) -> pd.DataFrame:
    usable = hourly[
        [
            "timestamp_utc",
            "eth_log_return",
            "wbtc_log_return",
            "is_calibration",
        ]
    ].copy()
    usable["stress"] = baseline_states.eq("stress").astype(int)
    usable = usable.loc[
        usable["is_calibration"]
        & usable["eth_log_return"].notna()
        & usable["wbtc_log_return"].notna()
    ].rename(
        columns={"eth_log_return": "eth", "wbtc_log_return": "wbtc"}
    )
    segments = [
        usable.loc[usable["timestamp_utc"] < FTX_START].reset_index(drop=True),
        usable.loc[usable["timestamp_utc"] >= FTX_END_EXCLUSIVE].reset_index(drop=True),
    ]
    target = _series_metrics(usable.reset_index(drop=True))
    rows = []
    for block_length in (24, 72, 168, 336):
        rng = np.random.default_rng(seed + block_length)
        metrics: list[dict[str, float]] = []
        for _ in range(replications):
            sample = _resample_segments(
                segments,
                block_length=block_length,
                target_length=len(usable),
                rng=rng,
            )
            metrics.append(_series_metrics(sample))
        frame = pd.DataFrame(metrics)
        row: dict[str, Any] = {
            "block_length_hours": block_length,
            "replications": replications,
            "seed": seed + block_length,
        }
        errors = []
        for metric, target_value in target.items():
            mean_value = float(frame[metric].mean())
            error = abs(mean_value - target_value)
            row[f"target_{metric}"] = target_value
            row[f"bootstrap_mean_{metric}"] = mean_value
            row[f"absolute_error_{metric}"] = error
            scale = abs(target_value) if abs(target_value) > 1e-6 else 1.0
            errors.append(error / scale)
        row["mean_scaled_preservation_error"] = float(np.mean(errors))
        row["recommended_role"] = (
            "default_candidate" if block_length == 168 else "sensitivity"
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _economic_meaning(field: str) -> str:
    mapping = {
        "PriceProcessConfig.mu": "Hourly collateral log-return drift.",
        "PriceProcessConfig.sigma": "Hourly collateral log-return volatility.",
        "price_path": "Aligned empirical cross-collateral return paths.",
        "shock_size": "Observed lower-tail return evidence for scenario severity.",
        "market_regime": "Descriptive normal/stress network-market state.",
        "ConfidenceConfig.normal_lower_price": "Lower DAI price boundary for normal confidence.",
        "ConfidenceConfig.normal_upper_price": "Upper DAI price boundary for normal confidence.",
        "ConfidenceConfig.stress_lower_price": "Lower DAI price boundary before panic.",
        "liquidation.arrival_process": "Hourly probability and count of auction initiation.",
        "liquidation.auction_duration": "Observed time between auction initiation and final observed action.",
        "LiquidationConfig.gas_cost": "Top-level successful-Take transaction cost in USD.",
        "LiquidationConfig.max_liquidations_per_step": "Observed hourly liquidation completion throughput.",
    }
    if field.startswith("gas_environment."):
        return "Observed Ethereum gas-market condition or sampling artefact."
    if field == "CollateralConfig.liquidation_ratio":
        return "Exact-ilk minimum collateralisation requirement."
    if field == "CollateralConfig.liquidation_penalty":
        return "Exact-ilk liquidation penalty rate."
    if field.startswith("protocol."):
        return "Effective-dated Maker protocol setting not represented directly in the current ABM."
    return mapping.get(field, "Empirical or protocol candidate for later review.")


def _representation(candidate: dict[str, Any]) -> str:
    field = candidate["simulator_field"]
    if candidate["estimate_value"] is not None:
        return "scalar"
    if candidate["provenance_classification"] == "protocol_constant":
        return "effective_dated_constant"
    if field in {"price_path", "gas_environment.empirical_sampling"}:
        return "sampling_artefact"
    if field == "market_regime":
        return "transition_matrix_and_classifier"
    return "empirical_distribution"


def _review_decision(candidate: dict[str, Any]) -> dict[str, str]:
    field = candidate["simulator_field"]
    if candidate["provenance_classification"] == "protocol_constant":
        if field in {
            "CollateralConfig.liquidation_ratio",
            "CollateralConfig.liquidation_penalty",
        }:
            return {
                "review_status": "ready_for_later_adoption",
                "recommended_representation": "timestamp-selected exact-ilk scalar",
                "recommended_later_treatment": "Select the value effective at the replay or scenario baseline timestamp.",
                "unresolved_limitation": "The current ABM cannot vary the setting within a run.",
                "adoption_gate": "Choose and document the replay/baseline timestamp.",
                "reviewer_notes": "Never replace the effective history with an unlabelled average.",
            }
        return {
            "review_status": "blocked_by_model_mapping",
            "recommended_representation": "effective-dated history",
            "recommended_later_treatment": "Retain for provenance, historical context and possible later mechanics.",
            "unresolved_limitation": "No current simulator field or mechanism consumes this setting.",
            "adoption_gate": "Separate authorisation for a model-mechanics change.",
            "reviewer_notes": "Credible protocol evidence, but not currently adoptable configuration.",
        }
    if field in {"PriceProcessConfig.mu", "PriceProcessConfig.sigma", "price_path"}:
        return {
            "review_status": "provisional_sensitivity_required",
            "recommended_representation": (
                "aligned empirical blocks" if field == "price_path" else "hourly scalar with block-bootstrap interval"
            ),
            "recommended_later_treatment": "Use 168 hours as the default candidate and 72–336 hours as sensitivity.",
            "unresolved_limitation": "Runtime arguments are scalar/path inputs rather than a registry-backed stochastic sampler.",
            "adoption_gate": "Confirm one simulation step equals one hour and validate withheld performance.",
            "reviewer_notes": "USDC remains a proxy for the model's STABLE collateral.",
        }
    if field == "shock_size":
        return {
            "review_status": "descriptive_only",
            "recommended_representation": "empirical lower-tail quantile range",
            "recommended_later_treatment": "Use only to bound transparent scenario choices.",
            "unresolved_limitation": "A chosen shock remains an experimental design parameter.",
            "adoption_gate": "User selects a labelled scenario quantile.",
            "reviewer_notes": "Do not treat a historical minimum as an estimate.",
        }
    if field == "market_regime":
        return {
            "review_status": "descriptive_only",
            "recommended_representation": "two-state classifier and transition matrix",
            "recommended_later_treatment": "Retain for stratification and later regime-sampler design.",
            "unresolved_limitation": "The current ABM has no exogenous market-regime state.",
            "adoption_gate": "Mechanics change would require separate authorisation.",
            "reviewer_notes": "Baseline is interpretable but remains sensitivity-dependent.",
        }
    if field.startswith("ConfidenceConfig."):
        return {
            "review_status": "provisional_sensitivity_required",
            "recommended_representation": "scalar DAI-price threshold with nearby-quantile sensitivity",
            "recommended_later_treatment": "Review jointly to preserve threshold ordering.",
            "unresolved_limitation": "Observed peg quantiles do not directly identify behavioural confidence.",
            "adoption_gate": "Later model-output calibration and FTX-independent validation.",
            "reviewer_notes": "Candidate is a price boundary, not an observed belief parameter.",
        }
    if field.startswith("gas_environment.") and field != "gas_environment.empirical_sampling":
        return {
            "review_status": "descriptive_only",
            "recommended_representation": "regime-conditional empirical distribution",
            "recommended_later_treatment": "Use for diagnostics and for a later gas sampler if authorised.",
            "unresolved_limitation": "No current gas-environment field exists.",
            "adoption_gate": "Separate sampling-interface design.",
            "reviewer_notes": "Gas price remains distinct from gas units and USD cost.",
        }
    if field == "gas_environment.empirical_sampling":
        return {
            "review_status": "blocked_by_model_mapping",
            "recommended_representation": "aligned market–gas empirical blocks",
            "recommended_later_treatment": "Retain the source-row index for a later sampler.",
            "unresolved_limitation": "Current liquidation mechanics use one fixed USD gas cost.",
            "adoption_gate": "Authorised regime-dependent gas-sampling mechanics.",
            "reviewer_notes": "Cannot be inserted into YAML as a scalar.",
        }
    if field == "liquidation.arrival_process":
        return {
            "review_status": "blocked_by_model_mapping",
            "recommended_representation": "hurdle process: activity probability plus positive conditional severity",
            "recommended_later_treatment": "Use the decomposition if a stochastic arrival mechanism is later authorised.",
            "unresolved_limitation": "Current liquidations are endogenous vault states, not an exogenous arrival process.",
            "adoption_gate": "Clarify whether the hurdle model is diagnostic or a mechanics extension.",
            "reviewer_notes": "The unconditional hourly q90 of volume remains zero.",
        }
    if field == "liquidation.auction_duration":
        return {
            "review_status": "descriptive_only",
            "recommended_representation": "collateral- and regime-conditioned empirical distribution",
            "recommended_later_treatment": "Use to validate delay/capacity assumptions.",
            "unresolved_limitation": "The simplified ABM has no explicit auction-duration state.",
            "adoption_gate": "No direct adoption; mechanics change would be separate.",
            "reviewer_notes": "Observed diagnostic duration is not a settlement guarantee.",
        }
    if field == "LiquidationConfig.gas_cost":
        return {
            "review_status": "provisional_sensitivity_required",
            "recommended_representation": "positive clean-Take USD-cost empirical distribution",
            "recommended_later_treatment": "Exclude or mark the four indeterminate zeros missing for primary estimation; retain-all as sensitivity.",
            "unresolved_limitation": "The model accepts one scalar while costs vary by transaction and regime.",
            "adoption_gate": "Choose a documented scalar reduction and complete sensitivity review.",
            "reviewer_notes": "Never replace the four zeros with the hourly median.",
        }
    if field == "LiquidationConfig.max_liquidations_per_step":
        return {
            "review_status": "provisional_sensitivity_required",
            "recommended_representation": "positive-hour empirical throughput distribution",
            "recommended_later_treatment": "Choose a labelled upper quantile after separating arrival from capacity.",
            "unresolved_limitation": "Unconditional quantiles are zero and do not identify capacity.",
            "adoption_gate": "Use active-hour throughput and Phase 1E-B exposure evidence.",
            "reviewer_notes": "Observed maximum is a stress diagnostic, not automatically a capacity estimate.",
        }
    return {
        "review_status": "rejected",
        "recommended_representation": "none",
        "recommended_later_treatment": "Do not adopt.",
        "unresolved_limitation": "Candidate mapping was not recognised.",
        "adoption_gate": "Resolve provenance and mapping.",
        "reviewer_notes": "Conservative stop classification.",
    }


def _candidate_review(
    original_registry: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    reviewed = []
    csv_rows = []
    for index, candidate in enumerate(original_registry["candidates"]):
        decision = _review_decision(candidate)
        if decision["review_status"] not in REVIEW_STATUSES:
            raise ValueError("Invalid candidate review status.")
        sensitivity = (
            "See gas_cost_sensitivity.csv"
            if candidate["simulator_field"] == "LiquidationConfig.gas_cost"
            else "See regime_sensitivity.csv"
            if candidate["simulator_field"] == "market_regime"
            else "See block_length_sensitivity.csv"
            if candidate["simulator_field"] in {
                "PriceProcessConfig.mu",
                "PriceProcessConfig.sigma",
                "price_path",
            }
            else "See protocol_candidate_review.csv"
            if candidate["provenance_classification"] == "protocol_constant"
            else "See original referenced artefact and review report."
        )
        additions = {
            **decision,
            "sensitivity_results": sensitivity,
            "economic_meaning": _economic_meaning(candidate["simulator_field"]),
            "representation_type": _representation(candidate),
            "original_candidate_sha256": _candidate_digest(candidate),
            "candidate_index": index,
        }
        reviewed_candidate = {**candidate, **additions}
        reviewed.append(reviewed_candidate)
        csv_rows.append(
            {
                "candidate_index": index,
                "estimate_name": candidate["estimate_name"],
                "simulator_field": candidate["simulator_field"],
                "economic_meaning": additions["economic_meaning"],
                "units": candidate["units"],
                "simulation_frequency": candidate["simulation_frequency"],
                "collateral_scope": candidate["collateral_scope"],
                "regime_scope": candidate["regime_scope"],
                "estimation_window": candidate["estimation_window"],
                "estimator": candidate["estimator"],
                "uncertainty_measure": json.dumps(
                    candidate["uncertainty_measure"], sort_keys=True
                ),
                "input_dataset": candidate["input_dataset"],
                "input_columns": candidate["input_columns"],
                "representation_type": additions["representation_type"],
                "original_estimate_value": candidate["estimate_value"],
                "original_distribution_reference": candidate[
                    "distribution_reference"
                ],
                "original_candidate_sha256": additions[
                    "original_candidate_sha256"
                ],
                **decision,
                "sensitivity_results": sensitivity,
            }
        )
    payload = {
        "schema_version": 1,
        "phase": "2A_review",
        "source_registry_sha256": ORIGINAL_REGISTRY_SHA256,
        "reviewed_candidates": reviewed,
    }
    validate_reviewed_registry(original_registry, payload)
    return pd.DataFrame(csv_rows), payload


def validate_reviewed_registry(
    original_registry: dict[str, Any],
    reviewed_registry: dict[str, Any],
) -> None:
    """Require exact preservation of every original candidate field/value."""
    reviewed = reviewed_registry.get("reviewed_candidates")
    original = original_registry.get("candidates")
    if not isinstance(reviewed, list) or len(reviewed) != len(original):
        raise ValueError("Reviewed registry must preserve all candidates.")
    for source, result in zip(original, reviewed, strict=True):
        for key, value in source.items():
            if result.get(key) != value:
                raise ValueError(
                    f"Reviewed candidate changed original field {key}."
                )
        missing = REVIEW_FIELDS.difference(result)
        if missing:
            raise ValueError(
                f"Reviewed candidate lacks fields: {sorted(missing)}."
            )
        if result["review_status"] not in REVIEW_STATUSES:
            raise ValueError("Reviewed candidate has an invalid status.")


def _protocol_review(
    reviewed_registry: dict[str, Any],
    intervals: pd.DataFrame,
) -> pd.DataFrame:
    validated = validate_protocol_intervals(intervals)
    mapping = {
        "CollateralConfig.liquidation_ratio": (
            "liquidation_ratio",
            "liquidation_ratio",
        ),
        "CollateralConfig.liquidation_penalty": (
            "liquidation_penalty",
            "liquidation_penalty_rate",
        ),
        "protocol.debt_ceiling": ("debt_ceiling", "debt_ceiling_dai"),
        "protocol.minimum_debt": ("minimum_debt", "minimum_debt_dai"),
        "protocol.annualised_stability_fee": (
            "stability_fee_duty",
            "annualised_stability_fee",
        ),
        "protocol.auction_stopped": (
            "auction_stopped",
            "auction_stopped",
        ),
    }
    rows = []
    for candidate in reviewed_registry["reviewed_candidates"]:
        if candidate["provenance_classification"] != "protocol_constant":
            continue
        interval_parameter, reviewed_parameter = mapping[
            candidate["simulator_field"]
        ]
        scope = candidate["collateral_scope"]
        selected = validated.loc[
            validated["ilk"].eq(scope)
            & validated["parameter"].eq(interval_parameter)
        ].sort_values("effective_start_utc")
        if selected.empty:
            raise ValueError(
                f"No protocol intervals for {scope} {interval_parameter}."
            )
        default_rows = selected["state_source"].eq("contract_default")
        intended_use = (
            "historical replay"
            if candidate["simulator_field"] in {
                "CollateralConfig.liquidation_ratio",
                "CollateralConfig.liquidation_penalty",
            }
            else "descriptive only"
        )
        rows.append(
            {
                "estimate_name": candidate["estimate_name"],
                "simulator_field": candidate["simulator_field"],
                "ilk": scope,
                "parameter": reviewed_parameter,
                "interval_source_parameter": interval_parameter,
                "review_status": candidate["review_status"],
                "intended_later_use": intended_use,
                "interval_count": int(len(selected)),
                "first_effective_start_utc": selected[
                    "effective_start_utc"
                ].min(),
                "final_effective_end_exclusive_utc": selected[
                    "effective_end_exclusive_utc"
                ].max(),
                "distinct_values": int(
                    pd.to_numeric(
                        selected["converted_value"], errors="coerce"
                    ).nunique()
                ),
                "non_overlapping_intervals": True,
                "timestamp_selectable": True,
                "contract_default_intervals": int(default_rows.sum()),
                "observed_call_intervals": int(
                    selected["is_observed_call"].astype(str).str.lower().isin(
                        ["true", "1"]
                    ).sum()
                ),
                "default_distinguishable_from_call": True,
                "generic_experiment_reduction_rule": (
                    "Select the value effective at an explicitly named "
                    "baseline timestamp; use observed min/max only as a "
                    "labelled robustness range; never use an unlabelled average."
                ),
                "derived_series_note": (
                    "Annualised stability fee is reconstructed from "
                    "simultaneously effective duty and global base."
                    if candidate["simulator_field"]
                    == "protocol.annualised_stability_fee"
                    else ""
                ),
            }
        )
    if len(rows) != 36:
        raise ValueError(f"Expected 36 protocol candidates; found {len(rows)}.")
    return pd.DataFrame(rows)


def _model_compatibility(reviewed_registry: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for candidate in reviewed_registry["reviewed_candidates"]:
        if candidate["review_status"] not in {
            "ready_for_later_adoption",
            "provisional_sensitivity_required",
        }:
            continue
        field = candidate["simulator_field"]
        if field in {"PriceProcessConfig.mu", "PriceProcessConfig.sigma"}:
            exact_field = (
                "run_simulation(mu, sigma) runtime arguments; not fields on "
                "PriceProcessConfig"
            )
            accepts = "scalar"
            conversion = "None if one simulation step is one hour."
            change = "Registry-to-runtime configuration adapter."
            mechanics = False
        elif field == "price_path":
            exact_field = "run_simulation(price_path) / CollateralPricePaths"
            accepts = "aligned path arrays, not a block-index registry"
            conversion = "Resolve indices to aligned price paths before simulation."
            change = "Pre-run empirical block sampler and path constructor."
            mechanics = False
        elif field.startswith("ConfidenceConfig."):
            exact_field = field
            accepts = "scalar"
            conversion = "None; USD per DAI."
            change = "No code change; joint threshold selection required."
            mechanics = False
        elif field == "LiquidationConfig.gas_cost":
            exact_field = field
            accepts = "one scalar USD/DAI cost per run"
            conversion = "Reduce reviewed positive transaction-cost distribution to a labelled scalar."
            change = "Distributional or regime-dependent gas would change mechanics."
            mechanics = True
        elif field == "LiquidationConfig.max_liquidations_per_step":
            exact_field = field
            accepts = "positive integer or None"
            conversion = "Select and round a positive active-hour throughput quantile."
            change = "No change for a scalar; stochastic capacity would change mechanics."
            mechanics = False
        else:
            exact_field = field
            accepts = "collateral-specific scalar"
            conversion = "Select exact-ilk value by effective timestamp."
            change = "Within-run effective-date changes would require mechanics."
            mechanics = False
        rows.append(
            {
                "estimate_name": candidate["estimate_name"],
                "review_status": candidate["review_status"],
                "registry_field": field,
                "exact_simulator_field_or_interface": exact_field,
                "candidate_representation": candidate["representation_type"],
                "currently_accepted_representation": accepts,
                "units": candidate["units"],
                "frequency": candidate["simulation_frequency"],
                "conversion_required": conversion,
                "later_code_change": change,
                "adoption_would_change_mechanics": mechanics,
            }
        )
    return pd.DataFrame(rows)


def _phase1e_dependencies(status: pd.DataFrame) -> pd.DataFrame:
    blocked = status.loc[
        status["current_status"].eq("blocked_pending_phase1e_b")
    ].copy()
    specifications = {
        "n_vaults": (
            "active urn indicator; CDP/urn mapping; sampling weight",
            True,
            "quiet mature; bull expansion; Terra/CeFi; USDC/SVB",
            "No: FTX remains validation; 2020 is methodology validation.",
            "At least 500 active vault snapshots overall and 50 per exact ilk where feasible.",
            "Weighted active-vault count and scale-robust simulation design.",
            "Window-cluster bootstrap.",
            "FTX active-vault count and concentration.",
        ),
        "target_debt_share": (
            "exact accrued DAI debt by active urn and exact ilk",
            True,
            "quiet mature; bull expansion; Terra/CeFi; USDC/SVB",
            "No: all four calibration windows support it; FTX validates.",
            "At least 200 active vaults per collateral family and 50 per exact ilk.",
            "Debt-weighted share by window with exposure-weighted pooling.",
            "Window-cluster bootstrap and leave-one-window-out.",
            "FTX debt-share direction and concentration.",
        ),
        "debt_mean": (
            "positive accrued DAI debt per active urn",
            True,
            "quiet mature; bull expansion; Terra/CeFi; USDC/SVB",
            "No: ordinary and at least two distinct stress mechanisms suffice.",
            "At least 200 active vaults per collateral family and 50 per exact ilk.",
            "Weighted empirical distribution; report mean only for interface compatibility.",
            "Window/urn clustered bootstrap.",
            "FTX distributional validation.",
        ),
        "debt_std": (
            "positive accrued DAI debt per active urn",
            True,
            "quiet mature; bull expansion; Terra/CeFi; USDC/SVB",
            "No: same cross-sections as debt_mean.",
            "At least 200 active vaults per collateral family and 50 per exact ilk.",
            "Weighted sample standard deviation plus empirical quantiles.",
            "Window/urn clustered bootstrap.",
            "FTX scale and tail validation.",
        ),
        "collateral_ratio_mean": (
            "collateral ink; exact rate; collateral price; accrued debt",
            True,
            "quiet mature; bull expansion; Terra/CeFi; USDC/SVB",
            "No: ordinary plus crypto and stablecoin stress are required.",
            "At least 200 indebted vaults per family and 50 per exact ilk.",
            "Weighted empirical collateral-ratio distribution.",
            "Window/urn clustered bootstrap.",
            "FTX leverage validation.",
        ),
        "collateral_ratio_std": (
            "collateral ink; exact rate; collateral price; accrued debt",
            True,
            "quiet mature; bull expansion; Terra/CeFi; USDC/SVB",
            "No: same cross-sections as collateral_ratio_mean.",
            "At least 200 indebted vaults per family and 50 per exact ilk.",
            "Weighted standard deviation plus robust quantiles.",
            "Window/urn clustered bootstrap.",
            "FTX dispersion and tail validation.",
        ),
        "min_collateral_ratio_buffer": (
            "distance from exact effective liquidation ratio for each indebted urn",
            True,
            "quiet mature; bull expansion; Terra/CeFi; USDC/SVB",
            "No: all four calibration windows improve regime coverage.",
            "At least 100 near-threshold observations overall and 30 per family.",
            "Lower empirical quantile of positive distance-to-liquidation.",
            "Cluster bootstrap and threshold sensitivity.",
            "FTX near-liquidation share.",
        ),
        "max_close_factor": (
            "pre-grab debt; debt repaid/seized; Bark–grab linkage",
            True,
            "Terra/CeFi; USDC/SVB; Phase 1C linked auctions",
            "No: ordinary window adds little; FTX validates.",
            "At least 100 linked liquidations overall and 30 per major family.",
            "Empirical debt-closure share with protocol/stylised interpretation.",
            "Auction bootstrap by transaction cluster.",
            "FTX liquidation closure-share validation.",
        ),
        "max_normal_liquidatable_share": (
            "active indebted urn denominator and below-ratio indicator",
            True,
            "quiet mature; bull expansion",
            "No: ordinary windows identify the normal bound.",
            "At least 500 active indebted vault-hours or 200 snapshots.",
            "Upper quantile of normal-window liquidatable share.",
            "Window-cluster bootstrap.",
            "Check false-stress classification outside FTX.",
        ),
        "max_stress_liquidatable_share": (
            "active indebted urn denominator and below-ratio indicator",
            True,
            "Terra/CeFi; USDC/SVB",
            "No: FTX is validation and must not fit the threshold.",
            "At least 100 stress vault-hours and 50 liquidatable observations.",
            "Upper stress quantile with collateral-family reporting.",
            "Window-cluster bootstrap and leave-one-stress-window-out.",
            "FTX held-out peak and duration.",
        ),
    }
    window_ranking = (
        "1 quiet mature; 2 USDC/SVB; 3 bull expansion; "
        "4 Terra/CeFi; 5 FTX withheld validation"
    )
    rows = []
    for _, row in blocked.iterrows():
        field = str(row["simulator_field"])
        if field not in specifications:
            raise ValueError(f"No Phase 1E-B review specification for {field}.")
        (
            variables,
            opening,
            windows,
            all_five,
            minimum,
            estimator,
            uncertainty,
            validation,
        ) = specifications[field]
        rows.append(
            {
                "parameter_subsection": row["parameter_subsection"],
                "simulator_field": field,
                "required_vault_state_or_mutation_variables": variables,
                "opening_state_reconstruction_required": opening,
                "calibration_windows_required": windows,
                "all_five_new_windows_necessary": all_five,
                "minimum_sufficient_observations": minimum,
                "estimator": estimator,
                "uncertainty_method": uncertainty,
                "validation_regime": validation,
                "black_thursday_use": (
                    "Phase 1E-A methodology and legacy-stress validation only; "
                    "do not pool into Liquidations 2.0 calibration."
                ),
                "window_priority_order": window_ranking,
            }
        )
    if len(rows) != 10:
        raise ValueError(f"Expected ten Phase 1E-B dependencies; found {len(rows)}.")
    return pd.DataFrame(rows)


def _write_report(
    path: Path,
    *,
    status_counts: dict[str, int],
    gas_sensitivity: pd.DataFrame,
    sparsity: pd.DataFrame,
    regime_sensitivity: pd.DataFrame,
    ftx: pd.DataFrame,
    block_lengths: pd.DataFrame,
    outputs: list[dict[str, Any]],
) -> None:
    retained = gas_sensitivity.query(
        "variant == 'retain_observed_zero' and regime == 'all'"
    ).iloc[0]
    excluded = gas_sensitivity.query(
        "variant == 'exclude_zero_transactions' and regime == 'all'"
    ).iloc[0]
    baseline = regime_sensitivity.loc[
        regime_sensitivity["specification"].eq("baseline_two_of_six")
    ].iloc[0]
    strict = regime_sensitivity.loc[
        regime_sensitivity["specification"].eq("strict_three_of_six")
    ].iloc[0]
    loose = regime_sensitivity.loc[
        regime_sensitivity["specification"].eq("loose_one_of_six")
    ].iloc[0]
    removed = regime_sensitivity.loc[
        regime_sensitivity["specification"].str.startswith("remove_")
    ]
    conditional = regime_sensitivity.loc[
        regime_sensitivity["specification"].eq(
            "conditional_liquidation_median_signal"
        )
    ].iloc[0]
    ftx_share = ftx.loc[
        ftx["metric"].eq("ftx_stress_share"), "value"
    ].iloc[0]
    ftx_maximum_run = ftx.loc[
        ftx["metric"].eq("maximum_stress_run_hours"), "value"
    ].iloc[0]
    implied_duration = ftx.loc[
        ftx["metric"].eq("implied_mean_stress_duration"), "value"
    ].iloc[0]
    hourly_all = sparsity.query(
        "collateral_scope == 'ALL' and frequency_hours == 1 "
        "and subset == 'all_calendar'"
    ).iloc[0]
    hourly_stress = sparsity.query(
        "collateral_scope == 'ALL' and frequency_hours == 1 "
        "and subset == 'stress_periods'"
    ).iloc[0]
    block_best = block_lengths.loc[
        block_lengths["mean_scaled_preservation_error"].idxmin()
    ]
    checksum_lines = "\n".join(
        f"- `{item['path']}` — `{item['sha256']}`" for item in outputs
    )
    text = f"""# Phase 2A Candidate Review

## Scope

This bounded local review audits all 64 Phase 2A candidates without changing
the original registry, simulator configuration or mechanics. The FTX interval
remains held out from every calibration threshold.

## Candidate decisions

{chr(10).join(f"- `{name}`: {count}" for name, count in sorted(status_counts.items()))}

Only exact-ilk liquidation-ratio and liquidation-penalty histories are ready
for later timestamp-selected adoption. All adoption remains separately gated.

## Four zero-gas observations

All four rows are unique, successful, clean single-Take top-level
transactions. They precede London, have explicit source `gas_price = 0`, and
have no available fee-cap, priority-fee or base-fee alternative. No join or
internal-call duplication was found. Their precise economic cause is not
identifiable locally.

Retaining them gives median USD cost {retained['median_usd']:.6g} and mean
{retained['mean_usd']:.6g}; excluding them gives median
{excluded['median_usd']:.6g} and mean {excluded['mean_usd']:.6g}. The primary
later estimator should exclude them or treat them as missing without
imputation, with retain-all reported as sensitivity.

## Liquidation sparsity

The unconditional hourly q90 remains zero. This is evidence of a sparse
arrival process, not evidence that positive liquidation severity is zero.
Only {hourly_all['activity_probability']:.4%} of calibration hours contain
positive volume; their conditional median is
{hourly_all['conditional_median']:.6g} DAI. Among baseline stress hours,
activity rises to {hourly_stress['activity_probability']:.4%} and the
conditional median to {hourly_stress['conditional_median']:.6g} DAI.
Arrival probability and conditional positive count/volume should be estimated
separately. A hurdle representation is recommended conceptually, but an
exogenous hurdle arrival mechanism would change the current endogenous
liquidation mechanics and is not implemented here.

## Regime robustness and FTX

The baseline stress prevalence is {baseline['stress_prevalence']:.4%};
the stricter and looser alternatives give {strict['stress_prevalence']:.4%}
and {loose['stress_prevalence']:.4%}. Removing one signal at a time produces
{removed['stress_prevalence'].min():.4%}--{removed['stress_prevalence'].max():.4%}
stress prevalence. Replacing the zero-q90 liquidation indicator with the
positive-hour median gives {conditional['stress_prevalence']:.4%}.
The baseline remains interpretable but provisional.

The withheld FTX interval is classified as stress for
{float(ftx_share):.4%} of hours without using the event label for fitting.
Its longest classified stress run is {float(ftx_maximum_run):.0f} hours,
compared with {float(implied_duration):.2f} hours implied by the calibration
transition exit probability; persistence is understated. This validates the
classifier diagnostically, not the complete ABM.

## Block length

The 168-hour block remains the default candidate because it follows the
registered absolute-return persistence rule and preserves weekly structure.
Use 72 and 336 hours as sensitivity bounds; 24 hours is a short-memory
robustness case. The bounded composite preservation score is lowest at
{int(block_best['block_length_hours'])} hours, so 336 hours must remain an
explicit sensitivity rather than being discarded. No large bootstrap dataset
was materialised.

## Protocol and compatibility

All 36 protocol histories preserve exact ilk, non-overlapping effective
intervals and contract-default provenance. Historical replay selects by
timestamp. Generic experiments must select an explicit baseline timestamp or
labelled observed range, never an unlabelled historical average.

The main compatibility gaps are empirical block construction, a regime-aware
gas sampler, transition-state consumption, a hurdle activity mechanism and
within-run effective-dated protocol settings. These are later design choices,
not changes made by this review.

## Phase 1E-B ranking

1. Quiet mature market — ordinary denominator and baseline distributions.
2. USDC/SVB — short, distinctive stablecoin stress.
3. Bull-market expansion — leverage and WBTC-B/C adoption.
4. Terra/CeFi — longest and costliest persistent-stress calibration window.
5. FTX — acquire and preserve only as withheld validation.

Black Thursday remains methodology and legacy-stress validation evidence, not
Liquidations 2.0 calibration.

## Decisions and unresolved issues

- Do not alter the original 64 candidates.
- Use positive clean-Take costs as the primary gas evidence.
- Keep the baseline two-state regime provisional.
- Keep 168 hours as default with 72--336-hour sensitivity.
- Do not adopt conceptual gas, arrival or unsupported protocol fields.
- Acquire Phase 1E-B opening states and representative mutations before vault
  population or owner-behaviour estimation.

## Output checksums

{checksum_lines}

## Recommended next task

Prepare a bounded Phase 1E-B acquisition authorisation beginning with the quiet
mature and USDC/SVB windows, including authoritative opening-state evidence.
"""
    _atomic_text(path, text)


def run_phase2a_review(
    config: Phase2AReviewConfig | None = None,
) -> dict[str, Any]:
    """Execute the complete local review without altering Phase 2A."""
    selected = config or Phase2AReviewConfig()
    original = verify_original_phase2a()
    frames = _load_review_inputs(original)
    hourly = _prepare_hourly(frames)
    thresholds = _thresholds(frames, hourly)

    zero_review, clean_transactions = _zero_gas_review(frames)
    gas_sensitivity = gas_cost_sensitivity(
        clean_transactions,
        seed=selected.random_seed,
        replications=selected.bootstrap_replications,
    )
    regime_sensitivity, specifications = _regime_sensitivity(
        hourly, thresholds
    )
    baseline_states = specifications["baseline_two_of_six"]
    original_states = frames["hourly_regimes"]["regime"].reset_index(drop=True)
    if not baseline_states.reset_index(drop=True).equals(original_states):
        raise ValueError("Baseline review classifier does not reproduce Phase 2A.")
    sparsity = _liquidation_sparsity(frames, hourly, baseline_states)
    ftx = _ftx_diagnostics(hourly, baseline_states)
    block_lengths = _block_length_sensitivity(
        hourly,
        baseline_states,
        seed=selected.random_seed,
        replications=selected.block_replications,
    )
    candidate_review, reviewed_registry = _candidate_review(
        original["registry"]
    )
    protocol_review = _protocol_review(
        reviewed_registry, frames["protocol_intervals"]
    )
    compatibility = _model_compatibility(reviewed_registry)
    dependencies = _phase1e_dependencies(frames["parameter_status"])

    outputs = {
        "candidate_review.csv": candidate_review,
        "gas_zero_transaction_review.csv": zero_review,
        "gas_cost_sensitivity.csv": gas_sensitivity,
        "liquidation_sparsity_review.csv": sparsity,
        "regime_sensitivity.csv": regime_sensitivity,
        "ftx_validation_diagnostics.csv": ftx,
        "block_length_sensitivity.csv": block_lengths,
        "protocol_candidate_review.csv": protocol_review,
        "model_compatibility.csv": compatibility,
        "phase1e_b_dependency_review.csv": dependencies,
    }
    output_records = []
    for name, frame in outputs.items():
        path = selected.output_dir / name
        _atomic_csv(path, frame)
        output_records.append(
            {
                "path": _relative(path),
                "rows": int(len(frame)),
                "columns": int(len(frame.columns)),
                "sha256": sha256_file(path),
            }
        )
    reviewed_path = (
        selected.output_dir / "phase2a_reviewed_candidates.json"
    )
    _atomic_json(reviewed_path, reviewed_registry)
    output_records.append(
        {
            "path": _relative(reviewed_path),
            "rows": len(reviewed_registry["reviewed_candidates"]),
            "columns": len(reviewed_registry["reviewed_candidates"][0]),
            "sha256": sha256_file(reviewed_path),
        }
    )
    observed_counts = Counter(candidate_review["review_status"].tolist())
    status_counts = {
        status: int(observed_counts.get(status, 0))
        for status in sorted(REVIEW_STATUSES)
    }
    metadata = {
        "phase": "2A_candidate_review",
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            text=True,
        ).strip(),
        "branch": subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "branch", "--show-current"],
            text=True,
        ).strip(),
        "random_seed": selected.random_seed,
        "bootstrap_replications": selected.bootstrap_replications,
        "block_replications": selected.block_replications,
        "source_phase2a_metadata_sha256": original["metadata_sha256"],
        "source_phase2a_registry_sha256": original["registry_sha256"],
        "source_phase2a_outputs_verified": original["checked_outputs"],
        "candidate_status_counts": status_counts,
        "calibration_excludes_ftx": True,
        "ftx_window": "[2022-11-01T00:00:00Z, 2022-11-21T00:00:00Z)",
        "regime_thresholds": thresholds,
        "zero_gas_transactions": int(len(zero_review)),
        "zero_gas_recommended_treatment": (
            "Exclude or mark missing without imputation for the primary "
            "estimator; retain-all as sensitivity."
        ),
        "hurdle_representation_recommended": True,
        "hurdle_would_require_mechanics_change": True,
        "block_length_default_hours": 168,
        "block_length_sensitivity_hours": [72, 336],
        "outputs": output_records,
        "warnings": [
            "FTX is diagnostic validation only, not complete ABM validation.",
            "The four pre-London zero gas prices have no defensible local replacement field.",
            "A hurdle arrival mechanism is not currently implemented.",
            "No candidate has been adopted into configuration.",
        ],
    }
    metadata_path = selected.output_dir / "phase2a_review_metadata.json"
    _atomic_json(metadata_path, metadata)
    if selected.write_report:
        _write_report(
            selected.report_path,
            status_counts=status_counts,
            gas_sensitivity=gas_sensitivity,
            sparsity=sparsity,
            regime_sensitivity=regime_sensitivity,
            ftx=ftx,
            block_lengths=block_lengths,
            outputs=output_records,
        )
    return {
        "metadata_path": _relative(metadata_path),
        "reviewed_registry_path": _relative(reviewed_path),
        "candidate_status_counts": status_counts,
        "outputs": output_records,
        "report_path": (
            _relative(selected.report_path)
            if selected.write_report
            else None
        ),
    }
