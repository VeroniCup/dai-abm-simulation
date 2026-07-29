"""Pure infrastructure for the pre-registered confidence SMM design.

The functions in this module construct evidence and search designs only. They
do not run the simulator, optimise parameters or alter a runtime profile.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.special import expit, logit


CALIBRATION_START = pd.Timestamp("2019-12-31T00:00:00Z")
CALIBRATION_END = pd.Timestamp("2024-07-01T00:00:00Z")
QUIET_VALIDATION = (
    pd.Timestamp("2022-11-01T00:00:00Z"),
    pd.Timestamp("2022-11-21T00:00:00Z"),
)
FINAL_STRESS_VALIDATION = (
    pd.Timestamp("2023-03-06T00:00:00Z"),
    pd.Timestamp("2023-03-20T00:00:00Z"),
)
EVENT_THRESHOLD = 0.995
PANIC_RESPONSE_UPPER_BOUND = 2.75454
CORE_GROUPS = ("A", "B", "C", "D")
SEED_STREAMS = (
    "vault_sampling",
    "market_innovations",
    "liquidation_randomness",
)
DEFAULT_REGISTRY_IDS = (
    "confidence-smm-registry-a",
    "confidence-smm-registry-b",
)


def evidence_partition(timestamp: pd.Timestamp) -> str:
    """Return the pre-registered evidence partition for one UTC timestamp."""
    value = pd.Timestamp(timestamp)
    if value.tzinfo is None:
        value = value.tz_localize("UTC")
    else:
        value = value.tz_convert("UTC")
    if QUIET_VALIDATION[0] <= value < QUIET_VALIDATION[1]:
        return "quiet_validation"
    if FINAL_STRESS_VALIDATION[0] <= value < FINAL_STRESS_VALIDATION[1]:
        return "final_stress_validation"
    return "calibration"


def _severity(prices: np.ndarray) -> np.ndarray:
    return np.minimum(
        1.0,
        np.maximum(0.0, EVENT_THRESHOLD - prices) / 0.005,
    )


def build_event_catalogue(frame: pd.DataFrame) -> pd.DataFrame:
    """Construct complete, semantically identified material-downside events."""
    required = {"dai_price_usd", "eth_log_return"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Event input is missing columns: {sorted(missing)}.")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("Event input must use a DatetimeIndex.")
    source = frame.sort_index()
    prices = source["dai_price_usd"].to_numpy(dtype=float)
    timestamps = source.index
    rows: list[dict[str, Any]] = []
    active_start: int | None = None
    stable_run = 0
    for position, price in enumerate(prices):
        below = price < EVENT_THRESHOLD
        if active_start is None and below and position >= 24:
            if np.all(prices[position - 24 : position] >= EVENT_THRESHOLD):
                active_start = position
                stable_run = 0
        if active_start is None:
            continue
        stable_run = 0 if below else stable_run + 1
        if stable_run != 24:
            continue

        start = active_start
        completion = position
        stable_start = completion - 23
        event_prices = prices[start : completion + 1]
        event_times = timestamps[start : completion + 1]
        severity = _severity(event_prices)
        trough_local = int(np.argmin(event_prices))
        trough = start + trough_local
        return_positions = np.flatnonzero(event_prices >= EVENT_THRESHOLD)
        first_return_local = (
            int(return_positions[0]) if len(return_positions) else None
        )
        half_target = event_prices[trough_local] + 0.5 * (
            1.0 - event_prices[trough_local]
        )
        half_positions = np.flatnonzero(
            event_prices[trough_local:] >= half_target
        )
        half_life = (
            int(half_positions[0]) if len(half_positions) else np.nan
        )
        recovery_runs: list[int] = []
        current_run = 0
        for event_price in event_prices:
            if event_price >= EVENT_THRESHOLD:
                current_run += 1
            elif current_run:
                recovery_runs.append(current_run)
                current_run = 0
        if current_run:
            recovery_runs.append(current_run)
        failed_recoveries = sum(
            length < 24 for length in recovery_runs[:-1]
        )
        six_hour_burden = pd.Series(severity).rolling(
            6, min_periods=1
        ).mean()
        prior_eth = source["eth_log_return"].iloc[start - 24 : start]
        event_eth = source["eth_log_return"].iloc[start : completion + 1]
        recovery_eth = source["eth_log_return"].iloc[
            trough + 1 : trough + 25
        ]
        following = prices[
            completion + 1 : min(len(prices), completion + 25)
        ]
        overshoot = (
            float(np.maximum(following - 1.0, 0.0).max())
            if len(following)
            else np.nan
        )
        burden_after_return = (
            float(severity[first_return_local:].sum())
            if first_return_local is not None
            else float(severity.sum())
        )
        partitions = {evidence_partition(value) for value in event_times}
        partition = (
            next(iter(partitions))
            if len(partitions) == 1
            else "cross_partition"
        )
        onset = timestamps[start]
        event_id = (
            f"{partition}__"
            f"{onset.strftime('%Y%m%dT%H%M%SZ')}"
        )
        rows.append(
            {
                "event_id": event_id,
                "partition": partition,
                "onset_timestamp_utc": onset,
                "completion_timestamp_utc": timestamps[completion],
                "stable_run_start_timestamp_utc": timestamps[stable_start],
                "trough_timestamp_utc": timestamps[trough],
                "first_return_timestamp_utc": (
                    timestamps[start + first_return_local]
                    if first_return_local is not None
                    else pd.NaT
                ),
                "calendar_year": int(onset.year),
                "event_duration_hours": int(completion - start),
                "hours_below_0995": int(
                    np.count_nonzero(event_prices < EVENT_THRESHOLD)
                ),
                "initial_peg_gap": float(1.0 - event_prices[0]),
                "minimum_price": float(event_prices[trough_local]),
                "maximum_downside_deviation": float(
                    max(0.0, EVENT_THRESHOLD - event_prices[trough_local])
                ),
                "maximum_six_hour_burden": float(six_hour_burden.max()),
                "first_six_hour_burden": float(severity[:6].mean()),
                "first_24_hour_burden": float(severity[:24].mean()),
                "cumulative_downside_burden": float(severity.sum()),
                "burden_after_first_return": burden_after_return,
                "hours_to_minimum": int(trough_local),
                "hours_to_first_return": (
                    int(first_return_local)
                    if first_return_local is not None
                    else np.nan
                ),
                "recovery_completion_hours": int(completion - start),
                "recovery_hours_from_trough": int(completion - trough),
                "recovery_half_life": float(half_life),
                "failed_recovery_attempts": int(failed_recoveries),
                "post_recovery_overshoot": overshoot,
                "onset_eth_downside": max(0.0, -float(prior_eth.sum())),
                "event_eth_downside": max(0.0, -float(event_eth.sum())),
                "eth_recovery_24h": float(recovery_eth.sum()),
                "eligible_first_six_hour_burden": True,
                "eligible_maximum_downside_deviation": True,
                "eligible_recovery_completion_hours": True,
                "eligible_failed_recovery_attempts": True,
                "eligible_initial_gap_contrast": True,
                "eligible_eth_recovery_contrast": len(recovery_eth) == 24,
            }
        )
        active_start = None
        stable_run = 0
    return pd.DataFrame(rows)


def active_event_hours(
    index: pd.DatetimeIndex,
    events: pd.DataFrame,
) -> pd.Series:
    """Return a Boolean event-activity mask on the supplied hourly index."""
    result = pd.Series(False, index=index)
    for row in events.itertuples(index=False):
        result.loc[
            row.onset_timestamp_utc : row.completion_timestamp_utc
        ] = True
    return result


def quartile_contrast(
    events: pd.DataFrame,
    *,
    stratifier: str,
    outcome: str,
) -> tuple[float, int, int]:
    """Calculate deterministic Q4-minus-Q1 equal-event contrast."""
    selected = events[[stratifier, outcome]].dropna().copy()
    quartile = pd.qcut(selected[stratifier], 4, labels=False)
    low = selected.loc[quartile.eq(0), outcome]
    high = selected.loc[quartile.eq(3), outcome]
    return float(high.mean() - low.mean()), int(len(low)), int(len(high))


def fixed_horizon_recovery_indicator(
    recovery_time_hours: float | int | None,
    *,
    horizon_hours: int,
    recovered: bool = True,
) -> float:
    """Represent recovery by a fixed horizon without a censoring sentinel."""
    if horizon_hours <= 0:
        raise ValueError("The recovery horizon must be positive.")
    if not recovered or recovery_time_hours is None:
        return 0.0
    value = float(recovery_time_hours)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError("A recovered duration must be finite and non-negative.")
    return float(value <= horizon_hours)


def restricted_recovery_time(
    recovery_time_hours: float | int | None,
    *,
    restriction_hours: int,
    recovered: bool = True,
) -> float:
    """Cap recovery time while assigning non-recovery the restriction."""
    if restriction_hours <= 0:
        raise ValueError("The recovery-time restriction must be positive.")
    if not recovered or recovery_time_hours is None:
        return float(restriction_hours)
    value = float(recovery_time_hours)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError("A recovered duration must be finite and non-negative.")
    return float(min(value, restriction_hours))


def fixed_strata_q4_q1_contrast(
    records: pd.DataFrame,
    *,
    outcome: str,
    q1_event_ids: Sequence[str],
    q4_event_ids: Sequence[str],
    event_col: str = "event_id",
) -> tuple[float, float, float]:
    """Return an equal-event Q4-minus-Q1 contrast for fixed memberships."""
    required = {event_col, outcome}
    missing = required - set(records.columns)
    if missing:
        raise ValueError(f"Fixed-strata input is missing: {sorted(missing)}.")
    if set(q1_event_ids) & set(q4_event_ids):
        raise ValueError("Q1 and Q4 memberships must not overlap.")
    per_event = records[[event_col, outcome]].copy()
    if per_event[event_col].duplicated().any():
        raise ValueError("Fixed-strata aggregation requires one row per event.")
    per_event = per_event.set_index(event_col)
    expected = set(q1_event_ids) | set(q4_event_ids)
    missing_events = expected - set(per_event.index.astype(str))
    if missing_events:
        raise ValueError(f"Fixed-strata events are missing: {sorted(missing_events)}.")
    q1 = pd.to_numeric(
        per_event.loc[list(q1_event_ids), outcome], errors="raise"
    ).to_numpy(dtype=float)
    q4 = pd.to_numeric(
        per_event.loc[list(q4_event_ids), outcome], errors="raise"
    ).to_numpy(dtype=float)
    if not np.isfinite(np.concatenate((q1, q4))).all():
        raise ValueError("Fixed-strata outcomes must be finite.")
    q1_mean = float(q1.mean())
    q4_mean = float(q4.mean())
    return q4_mean - q1_mean, q1_mean, q4_mean


@dataclass(frozen=True)
class StructuralParameters:
    """Structural coordinates for the future Stage 2 mechanism."""

    deterioration_adjustment: float
    recovery_adjustment: float
    confidence_floor: float
    panic_response: float


def validate_structural_parameters(parameters: StructuralParameters) -> None:
    """Validate the exact pre-registered parameter region."""
    values = tuple(parameters.__dict__.values())
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Structural parameters must be finite.")
    if not (
        0.0
        < parameters.recovery_adjustment
        <= parameters.deterioration_adjustment
        <= 1.0
    ):
        raise ValueError("Require 0 < alpha_r <= alpha_d <= 1.")
    if not 0.0 <= parameters.confidence_floor < 1.0:
        raise ValueError("Require 0 <= confidence_floor < 1.")
    if not 0.0 <= parameters.panic_response <= PANIC_RESPONSE_UPPER_BOUND:
        raise ValueError(
            f"Require panic_response in [0, {PANIC_RESPONSE_UPPER_BOUND}]."
        )


def transformed_to_structural(
    transformed: Sequence[float],
    *,
    epsilon: float = np.finfo(float).eps,
) -> StructuralParameters:
    """Map four unconstrained coordinates into the structural interior."""
    values = np.asarray(transformed, dtype=float)
    if values.shape != (4,) or not np.isfinite(values).all():
        raise ValueError("transformed must contain four finite values.")
    if not 0.0 < epsilon < 0.5:
        raise ValueError("epsilon must be in (0, 0.5).")
    unit = epsilon + (1.0 - 2.0 * epsilon) * expit(values)
    deterioration = float(unit[0])
    recovery = float(deterioration * unit[1])
    floor = float(unit[2])
    panic = float(PANIC_RESPONSE_UPPER_BOUND * unit[3])
    result = StructuralParameters(
        deterioration_adjustment=deterioration,
        recovery_adjustment=recovery,
        confidence_floor=floor,
        panic_response=panic,
    )
    validate_structural_parameters(result)
    return result


def structural_to_transformed(
    parameters: StructuralParameters,
    *,
    epsilon: float = np.finfo(float).eps,
) -> np.ndarray:
    """Map strictly interior structural values to unconstrained coordinates."""
    validate_structural_parameters(parameters)
    values = np.array(
        [
            parameters.deterioration_adjustment,
            (
                parameters.recovery_adjustment
                / parameters.deterioration_adjustment
            ),
            parameters.confidence_floor,
            parameters.panic_response / PANIC_RESPONSE_UPPER_BOUND,
        ],
        dtype=float,
    )
    if np.any(values <= epsilon) or np.any(values >= 1.0 - epsilon):
        raise ValueError(
            "Boundary models are represented explicitly, not transformed."
        )
    scaled = (values - epsilon) / (1.0 - 2.0 * epsilon)
    return logit(scaled)


def boundary_model_descriptions() -> dict[str, str]:
    """Return the four explicit nested/boundary models."""
    return {
        "panic_response_zero": "kappa_P = 0",
        "confidence_floor_zero": "C_min = 0",
        "equal_adjustment_rates": "alpha_d = alpha_r",
        "instantaneous_deterioration_target": "alpha_d = 1",
    }


@dataclass(frozen=True)
class MomentObjective:
    """Detailed value returned by the pure moment objective."""

    total_objective: float
    group_contributions: dict[str, float]
    moment_contributions: dict[str, float]
    standardised_discrepancies: dict[str, float]
    concentration_diagnostics: dict[str, Any]
    acceptance_diagnostics: dict[str, Any]


def moment_objective(
    *,
    simulated: Mapping[str, float],
    empirical: Mapping[str, float],
    scales: Mapping[str, float],
    groups: Mapping[str, str],
    within_group_weights: Mapping[str, float],
) -> MomentObjective:
    """Calculate the four-group objective independently of mapping order."""
    names = sorted(empirical)
    if not names or any(set(mapping) != set(names) for mapping in (
        simulated,
        scales,
        groups,
        within_group_weights,
    )):
        raise ValueError("Every core moment must appear in every input mapping.")
    declared = tuple(sorted(set(groups.values())))
    if declared != CORE_GROUPS:
        raise ValueError("The objective requires exactly groups A, B, C and D.")
    discrepancies: dict[str, float] = {}
    contributions: dict[str, float] = {}
    group_contributions: dict[str, float] = {}
    effective_weights: dict[str, float] = {}
    for group in CORE_GROUPS:
        members = sorted(name for name in names if groups[name] == group)
        raw_weights = np.array(
            [within_group_weights[name] for name in members], dtype=float
        )
        if (
            not np.isfinite(raw_weights).all()
            or np.any(raw_weights <= 0.0)
        ):
            raise ValueError("Within-group weights must be finite and positive.")
        normalised = raw_weights / raw_weights.mean()
        for name, weight in zip(members, normalised, strict=True):
            values = (simulated[name], empirical[name], scales[name])
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Moment inputs must be finite.")
            if scales[name] <= 0.0:
                raise ValueError("Empirical scales must be positive.")
            discrepancy = (simulated[name] - empirical[name]) / scales[name]
            effective = 0.25 * weight / len(members)
            if effective > 0.2 + 1e-12:
                raise ValueError("No ex-ante moment weight may exceed 20%.")
            discrepancies[name] = float(discrepancy)
            effective_weights[name] = float(effective)
            contributions[name] = float(effective * discrepancy**2)
        group_contributions[group] = float(
            sum(contributions[name] for name in members)
        )
    total = float(sum(group_contributions.values()))
    return MomentObjective(
        total_objective=total,
        group_contributions=group_contributions,
        moment_contributions=contributions,
        standardised_discrepancies=discrepancies,
        concentration_diagnostics={
            "effective_total_weights": effective_weights,
            "maximum_effective_weight": max(effective_weights.values()),
            "group_weight_sum": 1.0,
        },
        acceptance_diagnostics={
            "all_core_moments_present": True,
            "positive_scales": True,
            "finite_moments": True,
            "maximum_weight_within_limit": True,
        },
    )


def derive_seed(
    *,
    registry_id: str,
    event_id: str,
    replication: int,
    stream_name: str,
) -> int:
    """Derive a stable 64-bit NumPy seed using SHA-256 bytes 0:8."""
    if not registry_id or not event_id:
        raise ValueError("registry_id and event_id must be non-empty.")
    if isinstance(replication, bool) or replication < 0:
        raise ValueError("replication must be a non-negative integer.")
    if stream_name not in SEED_STREAMS:
        raise ValueError(f"Unknown seed stream: {stream_name}.")
    payload = json.dumps(
        {
            "event_id": event_id,
            "registry_id": registry_id,
            "replication": int(replication),
            "stream_name": stream_name,
            "version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def seed_registry() -> dict[str, Any]:
    """Build compact seed ownership evidence and verification vectors."""
    vectors = []
    for registry_id, event_id, replication, stream in (
        (DEFAULT_REGISTRY_IDS[0], "calibration__20200128T020000Z", 0, SEED_STREAMS[0]),
        (DEFAULT_REGISTRY_IDS[0], "calibration__20200128T020000Z", 31, SEED_STREAMS[1]),
        (DEFAULT_REGISTRY_IDS[1], "calibration__20210301T000000Z", 63, SEED_STREAMS[2]),
    ):
        vectors.append(
            {
                "registry_id": registry_id,
                "event_id": event_id,
                "replication": replication,
                "stream_name": stream,
                "seed": derive_seed(
                    registry_id=registry_id,
                    event_id=event_id,
                    replication=replication,
                    stream_name=stream,
                ),
            }
        )
    return {
        "schema_version": 1,
        "algorithm": "SHA-256 over canonical JSON; bytes 0:8 as unsigned big-endian integer",
        "registry_root_identifiers": list(DEFAULT_REGISTRY_IDS),
        "stream_names": list(SEED_STREAMS),
        "supported_replication_counts": [32, 64],
        "event_id_convention": "<partition>__<UTC onset YYYYMMDDTHHMMSSZ>",
        "verification_vectors": vectors,
    }


def select_search_events(
    events: pd.DataFrame,
    *,
    count: int = 32,
) -> list[str]:
    """Select a stable, content-hashed subset across joint event information."""
    selected = events.loc[events["partition"].eq("calibration")].copy()
    if len(selected) < count:
        raise ValueError("Insufficient calibration events for the search subset.")
    selected["burden_quartile"] = pd.qcut(
        selected["maximum_six_hour_burden"],
        4,
        labels=False,
        duplicates="drop",
    )
    selected["eth_downside_quartile"] = pd.qcut(
        selected["event_eth_downside"].rank(method="first"),
        4,
        labels=False,
        duplicates="drop",
    )
    selected["recovery_quartile"] = pd.qcut(
        selected["recovery_completion_hours"].rank(method="first"),
        4,
        labels=False,
        duplicates="drop",
    )
    selected["_stratum"] = selected[
        [
            "calendar_year",
            "burden_quartile",
            "eth_downside_quartile",
            "recovery_quartile",
        ]
    ].astype(str).agg("|".join, axis=1)
    selected["_hash"] = selected["event_id"].map(
        lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
    )
    selected = selected.sort_values(["_stratum", "_hash", "event_id"])
    groups = {
        name: group["event_id"].tolist()
        for name, group in selected.groupby("_stratum", sort=True)
    }
    result: list[str] = []
    depth = 0
    while len(result) < count:
        progressed = False
        for name in sorted(groups):
            if depth < len(groups[name]):
                result.append(groups[name][depth])
                progressed = True
                if len(result) == count:
                    break
        if not progressed:
            break
        depth += 1
    if len(result) != count:
        raise ValueError("Could not construct the 32-event subset.")
    return sorted(result)


def select_event_smoke_subset(events: pd.DataFrame) -> list[str]:
    """Select one content-hash event from each burden quartile.

    Quartile ownership is deterministic under source-row reordering, including
    tied burden values: ties are broken semantically by event identifier before
    equal-sized rank groups are assigned.  Validation events are ineligible.
    """
    required = {"event_id", "partition", "first_six_hour_burden"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"Smoke-event input is missing: {sorted(missing)}.")
    selected = events.loc[events["partition"].eq("calibration")].copy()
    if len(selected) != 74:
        raise ValueError("Smoke selection requires exactly 74 calibration events.")
    selected = selected.sort_values(
        ["first_six_hour_burden", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    selected["_burden_quartile"] = np.minimum(
        3,
        np.floor(4 * np.arange(len(selected)) / len(selected)).astype(int),
    )
    selected["_content_hash"] = selected["event_id"].map(
        lambda value: hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    )
    result = (
        selected.sort_values(
            ["_burden_quartile", "_content_hash", "event_id"],
            kind="mergesort",
        )
        .groupby("_burden_quartile", sort=True)
        .first()["event_id"]
        .tolist()
    )
    if len(result) != 4:
        raise ValueError("Smoke selection did not reproduce four burden quartiles.")
    return result


SIMULATED_CORE_MOMENT_ORDER = (
    "ordinary_below_mean",
    "ordinary_above_mean",
    "first_six_hour_burden_mean",
    "maximum_downside_deviation_mean",
    "recovery_completion_hours_mean",
    "failed_recovery_attempts_mean",
    "initial_gap_q4_q1_burden_contrast",
    "eth_recovery_q4_q1_duration_contrast",
)


@dataclass(frozen=True)
class SimulatedCoreMoments:
    """Eight fixed simulated moments plus non-objective diagnostics."""

    moments: dict[str, float]
    event_count: int
    replication_count: int
    right_censored_event_replications: int
    equal_event_weighting: bool
    objective_evaluated: bool
    diagnostic_moments_excluded: tuple[str, ...]


def _metric_record(result: Any) -> dict[str, Any]:
    metrics = result.metrics if hasattr(result, "metrics") else result
    if hasattr(metrics, "__dataclass_fields__"):
        return {
            field: getattr(metrics, field)
            for field in metrics.__dataclass_fields__
        }
    if isinstance(metrics, Mapping):
        return dict(metrics)
    raise TypeError("Each supplied result must expose metrics or be a mapping.")


def aggregate_simulated_core_moments(
    results: Sequence[Any],
    *,
    ordinary_preservation: Mapping[str, float],
    expected_event_ids: Sequence[str] | None = None,
) -> SimulatedCoreMoments:
    """Aggregate the fixed eight-moment schema with equal event weighting.

    Replications are averaged within event before events receive equal weight.
    Right-censored recovery durations enter at their explicit censoring time;
    their count remains separately auditable.  This function never evaluates
    the SMM objective.
    """
    if not results:
        raise ValueError("At least one conditional event result is required.")
    required_preservation = {"ordinary_below_mean", "ordinary_above_mean"}
    if set(ordinary_preservation) != required_preservation:
        raise ValueError("Both and only the two Stage 1 preservation moments are required.")
    records = pd.DataFrame([_metric_record(result) for result in results])
    required = {
        "event_id",
        "replication",
        "first_six_hour_burden",
        "maximum_downside_deviation",
        "recovery_completion_hours",
        "failed_recovery_attempts",
        "initial_peg_gap",
        "eth_recovery_24h",
        "right_censored",
        "cumulative_downside_burden",
        "burden_after_first_return",
    }
    missing = required - set(records.columns)
    if missing:
        raise ValueError(f"Conditional metrics are missing: {sorted(missing)}.")
    if records[["event_id", "replication"]].duplicated().any():
        raise ValueError("Each event-replication result must be unique.")
    observed_ids = set(records["event_id"])
    if expected_event_ids is not None and observed_ids != set(expected_event_ids):
        missing_ids = sorted(set(expected_event_ids) - observed_ids)
        extra_ids = sorted(observed_ids - set(expected_event_ids))
        raise ValueError(
            f"Event results are incomplete; missing={missing_ids}, extra={extra_ids}."
        )
    numeric = [
        "first_six_hour_burden",
        "maximum_downside_deviation",
        "recovery_completion_hours",
        "failed_recovery_attempts",
        "initial_peg_gap",
        "eth_recovery_24h",
    ]
    for column in numeric:
        records[column] = pd.to_numeric(records[column], errors="coerce")
        if records[column].isna().any():
            raise ValueError(f"Conditional metric {column} contains missing values.")
    per_event = (
        records.groupby("event_id", sort=True)
        .agg(
            first_six_hour_burden=("first_six_hour_burden", "mean"),
            maximum_downside_deviation=("maximum_downside_deviation", "mean"),
            recovery_completion_hours=("recovery_completion_hours", "mean"),
            failed_recovery_attempts=("failed_recovery_attempts", "mean"),
            initial_peg_gap=("initial_peg_gap", "first"),
            eth_recovery_24h=("eth_recovery_24h", "first"),
        )
        .reset_index()
    )
    initial_contrast = quartile_contrast(
        per_event,
        stratifier="initial_peg_gap",
        outcome="first_six_hour_burden",
    )[0]
    recovery_contrast = quartile_contrast(
        per_event,
        stratifier="eth_recovery_24h",
        outcome="recovery_completion_hours",
    )[0]
    moments = {
        "ordinary_below_mean": float(ordinary_preservation["ordinary_below_mean"]),
        "ordinary_above_mean": float(ordinary_preservation["ordinary_above_mean"]),
        "first_six_hour_burden_mean": float(
            per_event["first_six_hour_burden"].mean()
        ),
        "maximum_downside_deviation_mean": float(
            per_event["maximum_downside_deviation"].mean()
        ),
        "recovery_completion_hours_mean": float(
            per_event["recovery_completion_hours"].mean()
        ),
        "failed_recovery_attempts_mean": float(
            per_event["failed_recovery_attempts"].mean()
        ),
        "initial_gap_q4_q1_burden_contrast": float(initial_contrast),
        "eth_recovery_q4_q1_duration_contrast": float(recovery_contrast),
    }
    if tuple(moments) != SIMULATED_CORE_MOMENT_ORDER:
        raise AssertionError("Simulated core moment order changed unexpectedly.")
    return SimulatedCoreMoments(
        moments=moments,
        event_count=int(len(per_event)),
        replication_count=int(len(records)),
        right_censored_event_replications=int(
            records["right_censored"].astype(bool).sum()
        ),
        equal_event_weighting=True,
        objective_evaluated=False,
        diagnostic_moments_excluded=(
            "cumulative_downside_burden",
            "burden_after_first_return",
        ),
    )


def sobol_candidates(
    *,
    count: int = 256,
    seed: int = 20_260_729,
) -> tuple[np.ndarray, list[StructuralParameters]]:
    """Generate deterministic scrambled Sobol points and structural candidates."""
    from scipy.stats import qmc

    if count != 256:
        raise ValueError("The pre-registered Sobol design contains exactly 256 points.")
    engine = qmc.Sobol(d=4, scramble=True, seed=seed)
    unit = engine.random_base2(m=8)
    epsilon = np.finfo(float).eps
    clipped = np.clip(unit, epsilon, 1.0 - epsilon)
    transformed = logit(clipped)
    structural = [
        transformed_to_structural(row) for row in transformed
    ]
    return transformed, structural


def array_sha256(values: np.ndarray) -> str:
    """Hash an explicitly little-endian float64 array."""
    canonical = np.asarray(values, dtype="<f8")
    return hashlib.sha256(canonical.tobytes(order="C")).hexdigest()
