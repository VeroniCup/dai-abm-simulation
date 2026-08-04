"""Structural diagnosis for the dormant persistent-confidence experiment.

The module decomposes the committed partial-identification failure and runs a
fixed, objective-blind panel of one-factor diagnostic interventions.  It never
ranks candidates, estimates parameters, selects a structural model, or changes
production behaviour.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing as mp
from pathlib import Path
import shutil
import time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file
from dai_sim.inputs.liquidations import LiquidationDemandProcess
from dai_sim.inputs.vaults import (
    DEFAULT_TRANCHE_B_CONFIG_PATH,
    load_tranche_b_configuration,
)

from . import simulated_moments_search as search
from .event_simulation import (
    ConditionalEventSimulationConfig,
    ConditionalInitialState,
    PRIMARY_COLLATERAL_MODE,
    _liquidation_demand_config,
    load_stage1_owners,
    simulate_candidate_invariant_liquidation_path,
)
from .market import CONFIDENCE_EVIDENCE
from .partial_identification import (
    NATURAL_SUPPORTS,
    NUMERICAL_BOUND_LIMIT,
    construct_mc_interval,
)
from .simulated_moments import (
    DEFAULT_REGISTRY_IDS,
    STAGE2_ACTIVE_MOMENTS,
    sobol_candidates,
)
from .simulated_moments_diagnostics import (
    MEAN_MOMENTS,
    analytic_contrast_mcse,
    analytic_equal_event_mcse,
)


SCHEMA_VERSION = 1
REGISTRY_A = DEFAULT_REGISTRY_IDS[0]
PARTIAL_IDENTIFICATION_ID = (
    "39d01a3dfa07053dbe31c8189d88ab5f5fdfaa8003d3ddb28606179fd8413e6d"
)
SOBOL_SHA256 = (
    "fc56a12f0066cd84a15f5df52254ccf4a678847168af45e7f235757b3b1adde5"
)
ALL_EVENT_CACHE_SHA256 = (
    "3e0f2263eb379a2ef9fa43ea1dc11f186f159e365165ae61c07c727e01595ccf"
)
PANEL_INDICES = (0, 94, 171, 42, 193, 100, 116, 127, 36, 252, 222, 97, 134, 103, 203, 126)
PANEL_SHA256 = (
    "7ca9475da16b6e2a971d8adfe8bda6714c0841191e596e45d51bbcf2a26108f9"
)
EVENT_COUNT = 74
REPLICATION_COUNT = 64
EXPECTED_EVALUATIONS_PER_VARIANT = len(PANEL_INDICES) * EVENT_COUNT * REPLICATION_COUNT
MINIMUM_FREE_BYTES = 10 * 1024**3
MAX_NEW_STORAGE_BYTES = 750 * 1024**2
DEFAULT_ROOT = (
    REPOSITORY_ROOT
    / "outputs/diagnostics/calibration/confidence/structural_incompatibility"
    / PARTIAL_IDENTIFICATION_ID
)
FROZEN_VARIANT_REGISTRY = (
    CONFIDENCE_EVIDENCE / "structural_variant_registry.json"
)
PARTIAL_ROOT = (
    REPOSITORY_ROOT
    / "outputs/diagnostics/calibration/confidence/partial_identification"
    / PARTIAL_IDENTIFICATION_ID
)
PRECISION_ROOT = (
    REPOSITORY_ROOT
    / "outputs/diagnostics/calibration/confidence/monte_carlo_precision"
    / "fd5c3a6730a9b119cd98a0e983145e4606fe0fdd92b2965b152d8e2f18e230a6"
)
VAULT_SNAPSHOT_ROOT = REPOSITORY_ROOT / "data/vaults/processed/representative_regimes"
GAS_PANEL = (
    REPOSITORY_ROOT / "data/gas/processed/dune_ethereum_hourly_gas_processed.csv"
)
EVIDENCE_NAMES = (
    "structural_incompatibility_specification.json",
    "structural_baseline_mismatch.csv",
    "structural_parameter_boundary_trends.csv",
    "structural_variant_registry.json",
    "structural_variant_results.csv",
    "structural_family_summary.json",
    "structural_incompatibility_decision.json",
    "structural_incompatibility_reproducibility.json",
    "structural_incompatibility_benchmark.json",
)
DETERMINISTIC_EVIDENCE_NAMES = EVIDENCE_NAMES[:-1]
MOMENT_KEYS = {
    "first_six_hour_burden_mean": "first_six_hour_burden",
    "maximum_downside_deviation_mean": "maximum_downside_deviation",
    "recovery_completion_hours_mean": "recovery_completion_hours",
    "failed_recovery_attempts_mean": "failed_recovery_attempts",
    "initial_gap_q4_q1_burden_contrast": "initial_gap_q4_q1_burden_contrast",
}
PARAMETER_COLUMNS = {
    "confidence_floor": "transformed_C_min",
    "deterioration_adjustment": "transformed_alpha_d",
    "panic_response": "transformed_kappa_P",
    "recovery_adjustment": "transformed_alpha_r",
}
FAMILIES = (
    "vault_state",
    "liquidation_capacity",
    "gas_treatment",
    "residual_process",
    "stress_construction",
    "recovery_gates",
)


@dataclass(frozen=True)
class StructuralVariant:
    """One diagnostic intervention with exactly one changed assumption family."""

    family: str
    variant_id: str
    baseline_assumption: str
    changed_assumption: str
    evidence_owner: str
    source_status: str
    scientific_rationale: str
    settings: dict[str, Any]

    def as_registry_record(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "unchanged_assumptions": [
                family for family in FAMILIES if family != self.family
            ],
            "candidate_panel": list(PANEL_INDICES),
            "candidate_panel_sha256": PANEL_SHA256,
            "event_count": EVENT_COUNT,
            "replication_count": REPLICATION_COUNT,
            "registry": REGISTRY_A,
            "one_factor_audit": True,
            "diagnostic_only": True,
            "fit_field": None,
            "selected": False,
            "runtime_adopted": False,
        }


def _canonical_json(payload: Any) -> bytes:
    return search.canonical_json_bytes(payload)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    search._atomic_json(path, payload)


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    search._atomic_csv(path, frame)


def signed_band_gap(value: float, lower: float, upper: float) -> float:
    """Return signed distance to a closed empirical support band."""
    value = float(value)
    lower = float(lower)
    upper = float(upper)
    if not all(math.isfinite(item) for item in (value, lower, upper)):
        raise ValueError("Band-gap inputs must be finite.")
    if lower > upper:
        raise ValueError("Empirical band endpoints are reversed.")
    if value < lower:
        return value - lower
    if value > upper:
        return value - upper
    return 0.0


def interval_location(
    interval_lower: float,
    interval_upper: float,
    band_lower: float,
    band_upper: float,
) -> str:
    """Classify an interval as below, overlapping or above a band."""
    if interval_lower > interval_upper or band_lower > band_upper:
        raise ValueError("Interval endpoints are reversed.")
    if interval_upper < band_lower:
        return "below"
    if interval_lower > band_upper:
        return "above"
    return "overlap"


def classify_baseline_mismatch(
    *,
    candidate_count: int,
    intervals_below: int,
    intervals_above: int,
    means_inside: int,
    inner_passes: int,
    otherwise_outer_hard_gate_failures: int = 0,
) -> str:
    """Apply the fixed, ordered baseline mismatch classification rules."""
    if candidate_count <= 0:
        raise ValueError("candidate_count must be positive.")
    if otherwise_outer_hard_gate_failures / candidate_count >= 0.25:
        return "hard_gate_dominated"
    if intervals_below / candidate_count >= 0.90:
        return "systematically_below_band"
    if intervals_above / candidate_count >= 0.90:
        return "systematically_above_band"
    if (
        intervals_below / candidate_count >= 0.25
        and intervals_above / candidate_count >= 0.25
    ):
        return "mixed_location_mismatch"
    if means_inside / candidate_count >= 0.25 and inner_passes / candidate_count < 0.10:
        return "overlap_prevented_mainly_by_mc_uncertainty"
    return "no_systematic_location_mismatch"


def _constraints(evidence_dir: Path = CONFIDENCE_EVIDENCE) -> pd.DataFrame:
    frame = pd.read_csv(evidence_dir / "partial_identification_constraints.csv")
    if tuple(frame["moment"]) != STAGE2_ACTIVE_MOMENTS:
        raise ValueError("Partial-identification constraints changed.")
    return frame.set_index("moment", drop=False)


def _candidates(evidence_dir: Path = CONFIDENCE_EVIDENCE) -> pd.DataFrame:
    frame = pd.read_csv(evidence_dir / "partial_identification_candidates.csv")
    if len(frame) != 256 or set(frame["candidate_index"]) != set(range(256)):
        raise ValueError("The fixed partial-identification grid is incomplete.")
    return frame.sort_values("candidate_index", kind="mergesort").reset_index(drop=True)


def decompose_baseline_mismatch(
    candidates: pd.DataFrame,
    constraints: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Construct per-constraint location summaries and co-failure diagnostics."""
    constraints = constraints.set_index("moment", drop=False)
    failing = {
        moment: ~candidates[f"{MOMENT_KEYS[moment]}__outer_pass"].astype(bool)
        for moment in STAGE2_ACTIVE_MOMENTS
    }
    rows: list[dict[str, Any]] = []
    co_rows: list[dict[str, Any]] = []
    all_outer = np.logical_and.reduce(
        [candidates[f"{MOMENT_KEYS[m]}__outer_pass"].astype(bool) for m in STAGE2_ACTIVE_MOMENTS]
    )
    hard_fail = ~(
        candidates["numerical_bound_pass"].astype(bool)
        & candidates["structural_pass"].astype(bool)
        & candidates["stage1_preservation_pass"].astype(bool)
    )
    for moment in STAGE2_ACTIVE_MOMENTS:
        key = MOMENT_KEYS[moment]
        lower = float(constraints.loc[moment, "adjusted_band_lower"])
        upper = float(constraints.loc[moment, "adjusted_band_upper"])
        scale = float(constraints.loc[moment, "empirical_scale"])
        means = candidates[f"{key}__simulated_mean"].astype(float)
        lows = candidates[f"{key}__adjusted_mc_lower"].astype(float)
        highs = candidates[f"{key}__adjusted_mc_upper"].astype(float)
        locations = [
            interval_location(lo, hi, lower, upper)
            for lo, hi in zip(lows, highs, strict=True)
        ]
        counts = Counter(locations)
        gaps = means.map(lambda value: signed_band_gap(value, lower, upper))
        failures = failing[moment]
        only = failures.copy()
        for other in STAGE2_ACTIVE_MOMENTS:
            if other != moment:
                only &= ~failing[other]
        otherwise_outer_hard = int((all_outer & hard_fail).sum())
        numerical_failed = ~candidates["numerical_bound_pass"].astype(bool)
        mean_below = means.lt(lower)
        mean_inside = means.between(lower, upper, inclusive="both")
        mean_above = means.gt(upper)
        row = {
            "moment": moment,
            "empirical_band_lower": lower,
            "empirical_band_upper": upper,
            "empirical_scale": scale,
            "simulated_mean_minimum": float(means.min()),
            "simulated_mean_p05": float(means.quantile(0.05)),
            "simulated_mean_median": float(means.median()),
            "simulated_mean_p95": float(means.quantile(0.95)),
            "simulated_mean_maximum": float(means.max()),
            "mc_lower_minimum": float(lows.min()),
            "mc_lower_maximum": float(lows.max()),
            "mc_upper_minimum": float(highs.min()),
            "mc_upper_maximum": float(highs.max()),
            "intervals_below_band": counts["below"],
            "intervals_overlapping_band": counts["overlap"],
            "intervals_above_band": counts["above"],
            "means_inside_band": int(means.between(lower, upper, inclusive="both").sum()),
            "inner_passes": int(candidates[f"{key}__inner_pass"].astype(bool).sum()),
            "minimum_absolute_gap": float(gaps.abs().min()),
            "median_absolute_gap": float(gaps.abs().median()),
            "maximum_absolute_gap": float(gaps.abs().max()),
            "minimum_absolute_gap_scales": float(gaps.abs().min() / scale),
            "median_absolute_gap_scales": float(gaps.abs().median() / scale),
            "maximum_absolute_gap_scales": float(gaps.abs().max() / scale),
            "median_signed_gap": float(gaps.median()),
            "median_signed_gap_scales": float(gaps.median() / scale),
            "failing_only_this_moment": int(only.sum()),
            "otherwise_outer_hard_gate_failures": otherwise_outer_hard,
            "numerical_bound_failures": int(numerical_failed.sum()),
            "numerical_failures_with_mean_below": int(
                (numerical_failed & mean_below).sum()
            ),
            "numerical_failures_with_mean_inside": int(
                (numerical_failed & mean_inside).sum()
            ),
            "numerical_failures_with_mean_above": int(
                (numerical_failed & mean_above).sum()
            ),
            "structural_failures": int(
                (~candidates["structural_pass"].astype(bool)).sum()
            ),
            "stage1_preservation_failures": int(
                (~candidates["stage1_preservation_pass"].astype(bool)).sum()
            ),
            "numerical_failures_with_active_bad_debt": int(
                (
                    numerical_failed
                    & candidates["active_bad_debt_occurrence"].astype(bool)
                ).sum()
            ),
            "numerical_failures_with_unresolved_backlog": int(
                (
                    numerical_failed
                    & candidates["unresolved_backlog_occurrence"].astype(bool)
                ).sum()
            ),
        }
        row["cofailure_counts"] = json.dumps(
            {
                other: int((failures & failing[other]).sum())
                for other in STAGE2_ACTIVE_MOMENTS
                if other != moment
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        row["baseline_mismatch_classification"] = classify_baseline_mismatch(
            candidate_count=len(candidates),
            intervals_below=counts["below"],
            intervals_above=counts["above"],
            means_inside=row["means_inside_band"],
            inner_passes=row["inner_passes"],
            otherwise_outer_hard_gate_failures=otherwise_outer_hard,
        )
        rows.append(row)
        for other in STAGE2_ACTIVE_MOMENTS:
            if other != moment:
                co_rows.append(
                    {
                        "moment": moment,
                        "cofailed_moment": other,
                        "cofailure_count": int((failures & failing[other]).sum()),
                    }
                )
    return pd.DataFrame(rows), pd.DataFrame(co_rows)


def _monotonicity(values: Sequence[float]) -> tuple[float, str]:
    changes = np.diff(np.asarray(values, dtype=float))
    nonzero = changes[np.abs(changes) > 1e-15]
    if not len(nonzero):
        return 1.0, "flat"
    positive = float(np.mean(nonzero > 0))
    negative = float(np.mean(nonzero < 0))
    share = max(positive, negative)
    direction = "increasing" if positive >= negative else "decreasing"
    return share, direction


def parameter_boundary_trends(
    candidates: pd.DataFrame,
    constraints: pd.DataFrame,
) -> pd.DataFrame:
    """Audit fixed-domain boundary direction without extrapolating parameters."""
    constraints = constraints.set_index("moment", drop=False)
    rows = []
    for parameter, transformed_column in PARAMETER_COLUMNS.items():
        ordered = candidates.sort_values(
            [transformed_column, "candidate_index"], kind="mergesort"
        )
        deciles = pd.qcut(
            ordered[transformed_column],
            10,
            labels=False,
            duplicates="raise",
        )
        for moment in STAGE2_ACTIVE_MOMENTS:
            key = MOMENT_KEYS[moment]
            outcome = f"{key}__simulated_mean"
            lower = float(constraints.loc[moment, "adjusted_band_lower"])
            upper = float(constraints.loc[moment, "adjusted_band_upper"])
            scale = float(constraints.loc[moment, "empirical_scale"])
            low = float(ordered.loc[deciles.eq(0), outcome].median())
            high = float(ordered.loc[deciles.eq(9), outcome].median())
            binned = ordered.assign(_bin=deciles).groupby("_bin", sort=True)[outcome].median()
            monotonic_share, monotonic_direction = _monotonicity(binned.tolist())
            low_gap = signed_band_gap(low, lower, upper)
            high_gap = signed_band_gap(high, lower, upper)
            towards = (
                "low"
                if abs(low_gap) < abs(high_gap)
                else "high"
                if abs(high_gap) < abs(low_gap)
                else "neither"
            )
            correlation = spearmanr(
                ordered[transformed_column].to_numpy(dtype=float),
                ordered[outcome].to_numpy(dtype=float),
            ).statistic
            change_scales = (high - low) / scale
            boundary_signal = bool(
                abs(change_scales) >= 0.5
                and monotonic_share >= 0.75
                and towards in {"low", "high"}
                and (
                    (towards == "low" and low_gap != 0.0)
                    or (towards == "high" and high_gap != 0.0)
                )
            )
            rows.append(
                {
                    "parameter": parameter,
                    "moment": moment,
                    "low_decile_median": low,
                    "high_decile_median": high,
                    "high_minus_low_scales": float(change_scales),
                    "rank_correlation": float(correlation),
                    "adjacent_bin_monotonic_share": monotonic_share,
                    "monotonic_direction": monotonic_direction,
                    "low_boundary_gap_scales": low_gap / scale,
                    "high_boundary_gap_scales": high_gap / scale,
                    "movement_towards_band_boundary": towards,
                    "boundary_signal": boundary_signal,
                    "extrapolated_parameter_value": None,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["parameter", "moment"], kind="mergesort"
    ).reset_index(drop=True)


def parameter_domain_signal(trends: pd.DataFrame) -> dict[str, Any]:
    """Apply the fixed possible-domain-truncation rule."""
    signals = []
    for parameter, group in trends.groupby("parameter", sort=True):
        for boundary in ("low", "high"):
            pointing = group.loc[
                group["boundary_signal"].astype(bool)
                & group["movement_towards_band_boundary"].eq(boundary)
            ]
            other = group.loc[~group.index.isin(pointing.index)]
            worsening = int(
                (
                    other[
                        f"{boundary}_boundary_gap_scales"
                    ].abs()
                    - other[
                        f"{'high' if boundary == 'low' else 'low'}_boundary_gap_scales"
                    ].abs()
                    >= 1.0
                ).sum()
            )
            if len(pointing) >= 3 and worsening <= 1:
                signals.append(
                    {
                        "parameter": parameter,
                        "boundary": boundary,
                        "supporting_moments": sorted(pointing["moment"].tolist()),
                        "worsened_other_moments": worsening,
                    }
                )
    return {"possible": bool(signals), "signals": signals}


def hard_gate_decomposition(candidates: pd.DataFrame) -> dict[str, Any]:
    """Describe numerical failures without changing the fixed price bounds."""
    failed = ~candidates["numerical_bound_pass"].astype(bool)
    if int(failed.sum()) != 203:
        raise ValueError("Baseline numerical-bound failure count changed.")
    if (~candidates["structural_pass"].astype(bool)).sum() or (
        ~candidates["stage1_preservation_pass"].astype(bool)
    ).sum():
        raise ValueError("Baseline structural or Stage 1 failures changed.")
    records: dict[str, Any] = {
        "numerical_bound_failures": 203,
        "structural_failures": 0,
        "stage1_preservation_failures": 0,
        "by_parameter_quartile": {},
    }
    for parameter in PARAMETER_COLUMNS:
        quartile = pd.qcut(
            candidates[parameter].rank(method="first"),
            4,
            labels=("Q1", "Q2", "Q3", "Q4"),
        )
        records["by_parameter_quartile"][parameter] = {
            str(label): int((failed & quartile.eq(label)).sum())
            for label in quartile.cat.categories
        }
    censor_quartile = pd.qcut(
        candidates["right_censoring_share"].rank(method="first"),
        4,
        labels=("Q1", "Q2", "Q3", "Q4"),
    )
    records["by_censoring_quartile"] = {
        str(label): int((failed & censor_quartile.eq(label)).sum())
        for label in censor_quartile.cat.categories
    }
    for field in ("active_bad_debt_occurrence", "unresolved_backlog_occurrence"):
        records[f"by_{field}"] = {
            "present": int((failed & candidates[field].astype(bool)).sum()),
            "absent": int((failed & ~candidates[field].astype(bool)).sum()),
        }
    direction: dict[str, dict[str, int]] = {}
    constraints = _constraints()
    for moment in STAGE2_ACTIVE_MOMENTS:
        key = MOMENT_KEYS[moment]
        lower = float(constraints.loc[moment, "adjusted_band_lower"])
        upper = float(constraints.loc[moment, "adjusted_band_upper"])
        values = candidates[f"{key}__simulated_mean"].astype(float)
        direction[moment] = {
            "below": int((failed & values.lt(lower)).sum()),
            "inside": int((failed & values.between(lower, upper)).sum()),
            "above": int((failed & values.gt(upper)).sum()),
        }
    records["by_moment_direction"] = direction
    max_quartile_share = max(
        count / 203
        for item in records["by_parameter_quartile"].values()
        for count in item.values()
    )
    mechanism_shares = [
        records["by_active_bad_debt_occurrence"]["present"] / 203,
        records["by_unresolved_backlog_occurrence"]["present"] / 203,
    ]
    records["concentration_classification"] = (
        "concentrated_in_parameter_region"
        if max_quartile_share >= 0.50
        else "associated_with_structural_mechanism"
        if max(mechanism_shares) >= 0.90 and min(mechanism_shares) < 0.50
        else "broadly_distributed"
    )
    return records


def _snapshot_catalogue() -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    source_records = []
    for path in sorted(VAULT_SNAPSHOT_ROOT.glob("*/reconstructed_vault_snapshots.csv")):
        frame = pd.read_csv(path)
        required = {
            "timestamp_utc", "ilk", "debt_dai", "collateral_ratio",
            "liquidation_ratio", "active", "state_label",
        }
        if not required.issubset(frame):
            raise ValueError(f"Historical vault snapshot schema differs: {path}.")
        frame["timestamp_utc"] = pd.to_datetime(
            frame["timestamp_utc"], utc=True, format="mixed"
        )
        frame["_source_path"] = path.relative_to(REPOSITORY_ROOT).as_posix()
        frames.append(frame)
        source_records.append(
            {
                "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
                "sha256": sha256_file(path),
            }
        )
    if not frames:
        raise ValueError("Reviewed historical vault snapshots are unavailable.")
    combined = pd.concat(frames, ignore_index=True)
    eligible = combined.loc[
        combined["active"].astype(bool)
        & combined["ilk"].str.startswith("ETH-")
        & pd.to_numeric(combined["debt_dai"], errors="coerce").gt(0.0)
        & pd.to_numeric(combined["collateral_ratio"], errors="coerce").notna()
        & pd.to_numeric(combined["liquidation_ratio"], errors="coerce").notna()
    ].copy()
    if eligible.empty:
        raise ValueError("No complete ETH historical vault snapshot is eligible.")
    summaries = []
    for (timestamp, source, state_label), group in eligible.groupby(
        ["timestamp_utc", "_source_path", "state_label"], sort=True
    ):
        debt = group["debt_dai"].to_numpy(dtype=float)
        ratio = group["collateral_ratio"].to_numpy(dtype=float)
        summaries.append(
            {
                "timestamp_utc": timestamp,
                "source_path": source,
                "state_label": state_label,
                "system_collateral_ratio": float(np.average(ratio, weights=debt)),
                "eligible_vault_count": len(group),
                "total_debt_dai": float(debt.sum()),
            }
        )
    return eligible, pd.DataFrame(summaries).sort_values(
        ["timestamp_utc", "source_path", "state_label"], kind="mergesort"
    )


def select_snapshot_percentile(
    summaries: pd.DataFrame, quantile: float
) -> dict[str, Any]:
    """Select the earliest snapshot nearest a fixed SCR percentile."""
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("Snapshot quantile must lie in [0, 1].")
    target = float(summaries["system_collateral_ratio"].quantile(quantile))
    selected = (
        summaries.assign(
            _distance=(summaries["system_collateral_ratio"] - target).abs()
        )
        .sort_values(
            ["_distance", "timestamp_utc", "source_path", "state_label"],
            kind="mergesort",
        )
        .iloc[0]
    )
    return {
        "target_quantile": quantile,
        "target_system_collateral_ratio": target,
        "timestamp_utc": pd.Timestamp(selected["timestamp_utc"]).isoformat(),
        "source_path": str(selected["source_path"]),
        "state_label": str(selected["state_label"]),
        "system_collateral_ratio": float(selected["system_collateral_ratio"]),
        "eligible_vault_count": int(selected["eligible_vault_count"]),
        "total_debt_dai": float(selected["total_debt_dai"]),
    }


def _selected_snapshot_distribution(
    eligible: pd.DataFrame,
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    timestamp = pd.Timestamp(snapshot["timestamp_utc"])
    selected = eligible.loc[
        eligible["timestamp_utc"].eq(timestamp)
        & eligible["_source_path"].eq(snapshot["source_path"])
        & eligible["state_label"].eq(snapshot["state_label"])
    ]
    if selected.empty:
        raise ValueError("Selected historical vault snapshot is empty.")
    debt = selected["debt_dai"].to_numpy(dtype=float)
    ratios = selected["collateral_ratio"].to_numpy(dtype=float)
    liquidation = selected["liquidation_ratio"].to_numpy(dtype=float)
    return {
        "debt_dai": {
            f"p{int(quantile * 100):02d}": float(np.quantile(debt, quantile))
            for quantile in (0.05, 0.25, 0.50, 0.75, 0.95)
        },
        "collateral_ratio": {
            f"p{int(quantile * 100):02d}": float(np.quantile(ratios, quantile))
            for quantile in (0.05, 0.25, 0.50, 0.75, 0.95)
        },
        "liquidation_ratio": {
            f"p{int(quantile * 100):02d}": float(
                np.quantile(liquidation, quantile)
            )
            for quantile in (0.05, 0.25, 0.50, 0.75, 0.95)
        },
        "source_initially_liquidatable_count": int(
            np.sum(ratios < liquidation)
        ),
    }


def _source_status() -> dict[str, Any]:
    eligible, summaries = _snapshot_catalogue()
    p25 = select_snapshot_percentile(summaries, 0.25)
    median = select_snapshot_percentile(summaries, 0.50)
    p25["distribution_summary"] = _selected_snapshot_distribution(eligible, p25)
    median["distribution_summary"] = _selected_snapshot_distribution(
        eligible, median
    )
    events = pd.read_csv(CONFIDENCE_EVIDENCE / "event_catalogue.csv")
    calibration = events.loc[events["partition"].eq("calibration")].copy()
    earliest_event = pd.to_datetime(calibration["onset_timestamp_utc"], utc=True).min()
    gas_header = pd.read_csv(GAS_PANEL, nrows=1)
    gas_time_column = "timestamp_utc"
    if gas_time_column not in gas_header:
        raise ValueError("Historical gas timestamp ownership changed.")
    gas_first = pd.to_datetime(
        pd.read_csv(GAS_PANEL, usecols=[gas_time_column])[gas_time_column],
        utc=True,
    ).min()
    gas_complete = bool(gas_first <= earliest_event - pd.Timedelta(hours=48))
    return {
        "vault": {
            "status": "available",
            "eligible_rows": len(eligible),
            "snapshot_count": len(summaries),
            "p25": p25,
            "median": median,
        },
        "gas": {
            "status": "available" if gas_complete else "source_unavailable",
            "earliest_required_event": earliest_event.isoformat(),
            "earliest_validated_gas_hour": gas_first.isoformat(),
            "causal_complete": gas_complete,
            "reason": None if gas_complete else (
                "The calibration event catalogue begins before validated hourly "
                "gas coverage; missing pre-coverage hours cannot be invented."
            ),
        },
    }


def _vault_state_audit(
    *,
    root: Path,
    registry: Mapping[str, Any],
) -> Path:
    """Record deterministic vault-state ownership without storing trajectories."""
    owner = _load_cache_owner()
    eligible, _ = _snapshot_catalogue()
    variants = [
        item for item in registry["variants"] if item["family"] == "vault_state"
    ]
    rows = []
    for event_id, replication in sorted(owner["entries"]):
        entry = owner["entries"][(event_id, replication)]
        metadata = json.loads(
            (
                owner["cache_root"] / "cache_primary" / entry["metadata_filename"]
            ).read_text()
        )
        package = search.CachedPackage(
            metadata=metadata,
            arrays={"eth_prices": np.asarray([1.0], dtype="<f8")},
        )
        for variant in variants:
            state = _historical_state(
                package,
                variant["settings"]["snapshot"],
                eligible,
            )
            ratios = np.asarray(state.collateral_ratios, dtype=float)
            liquidation = np.asarray(state.liquidation_ratios, dtype=float)
            rows.append(
                {
                    "variant_id": variant["variant_id"],
                    "event_id": event_id,
                    "replication": replication,
                    "source_timestamp": variant["settings"]["snapshot"][
                        "timestamp_utc"
                    ],
                    "source_system_collateral_ratio": variant["settings"][
                        "snapshot"
                    ]["system_collateral_ratio"],
                    "initially_liquidatable_vault_count": int(
                        np.sum(ratios < liquidation)
                    ),
                    "total_debt_dai": state.total_debt_dai,
                    "state_checksum": state.state_checksum,
                }
            )
    frame = pd.DataFrame(rows).sort_values(
        ["variant_id", "event_id", "replication"], kind="mergesort"
    )
    if (
        len(frame) != len(variants) * EVENT_COUNT * REPLICATION_COUNT
        or frame["state_checksum"].isna().any()
    ):
        raise ValueError("Historical vault-state audit is incomplete.")
    path = Path(root) / "vault_state_audit.csv"
    _atomic_csv(path, frame)
    return path


def build_variant_registry() -> dict[str, Any]:
    """Build the fixed one-factor registry after source ownership checks."""
    if not any(VAULT_SNAPSHOT_ROOT.glob("*/reconstructed_vault_snapshots.csv")):
        if not FROZEN_VARIANT_REGISTRY.is_file():
            raise ValueError(
                "Reviewed historical vault snapshots and the frozen variant "
                "registry are unavailable."
            )
        registry = json.loads(
            FROZEN_VARIANT_REGISTRY.read_text(encoding="utf-8")
        )
        portable_owner = FROZEN_VARIANT_REGISTRY.relative_to(
            REPOSITORY_ROOT
        ).as_posix()
        for variant in registry["variants"]:
            historical_owner = variant["evidence_owner"]
            if (
                variant["source_status"] == "available"
                and not (REPOSITORY_ROOT / historical_owner).exists()
            ):
                variant["historical_evidence_owner"] = historical_owner
                variant["evidence_owner"] = portable_owner
        return registry
    status = _source_status()
    variants = [
        StructuralVariant(
            "vault_state", "vault_historical_p25_scr",
            "current reviewed pooled vault initialisation",
            "historical snapshot nearest calibration-period p25 system SCR",
            status["vault"]["p25"]["source_path"], "available",
            "Diagnose sensitivity to lower historical system collateralisation.",
            {"snapshot": status["vault"]["p25"]},
        ),
        StructuralVariant(
            "vault_state", "vault_historical_median_scr",
            "current reviewed pooled vault initialisation",
            "historical snapshot nearest calibration-period median system SCR",
            status["vault"]["median"]["source_path"], "available",
            "Diagnose sensitivity to the historical median initial state.",
            {"snapshot": status["vault"]["median"]},
        ),
    ]
    capacity_owners = {
        20: "config/sensitivities/liquidations/capacity_high.yaml",
        10: "src/dai_sim/experiments/scenarios.py",
        5: "config/sensitivities/liquidations/capacity_low.yaml",
    }
    for capacity in (20, 10, 5):
        variants.append(
            StructuralVariant(
                "liquidation_capacity", f"capacity_{capacity}",
                "no keeper-capacity ceiling",
                f"maximum {capacity} successful liquidations per hourly step",
                capacity_owners[capacity],
                "available",
                "Diagnose the structural effect of bounded keeper throughput.",
                {"maximum_liquidations_per_step": capacity, "gas_cost_dai": 100.0},
            )
        )
    variants.append(
        StructuralVariant(
            "gas_treatment", "historical_hourly_gas", "fixed 100 DAI gas treatment",
            "causal historical hourly gas costs",
            GAS_PANEL.relative_to(REPOSITORY_ROOT).as_posix(),
            status["gas"]["status"],
            "Diagnose historical transaction-cost ownership where complete.",
            status["gas"],
        )
    )
    variants.extend(
        [
            StructuralVariant(
                "residual_process", "residual_zero", "24-hour moving-block residuals",
                "zero innovation at every hour",
                "data/provenance/calibration/confidence/stage1_residual_summary.json",
                "available", "Separate deterministic mechanisms from innovations.",
                {"mode": "zero"},
            ),
            StructuralVariant(
                "residual_process", "residual_iid_empirical",
                "24-hour moving-block residuals",
                "independent draws from the accepted centred residual sequence",
                "data/provenance/calibration/confidence/stage1_residual_summary.json",
                "available", "Diagnose serial-block rather than marginal effects.",
                {"mode": "iid_empirical"},
            ),
            StructuralVariant(
                "stress_construction", "stress_eth_dominant", "peg/ETH weights 0.50/0.50",
                "peg/ETH weights 0.25/0.75",
                "data/provenance/calibration/confidence/sparse_predictor_scaling.json",
                "available", "Diagnose greater collateral-stress ownership.",
                {"peg_weight": 0.25, "collateral_weight": 0.75},
            ),
            StructuralVariant(
                "stress_construction", "stress_peg_dominant", "peg/ETH weights 0.50/0.50",
                "peg/ETH weights 0.75/0.25",
                "data/provenance/calibration/confidence/sparse_predictor_scaling.json",
                "available", "Diagnose greater peg-stress ownership.",
                {"peg_weight": 0.75, "collateral_weight": 0.25},
            ),
            StructuralVariant(
                "recovery_gates", "gate_backlog_only",
                "price stability, acceptable backlog and no material active bad debt",
                "ignore active bad debt while retaining price and backlog gates",
                "data/provenance/calibration/confidence/recovery_gate_specification.json",
                "available", "Isolate the active-bad-debt gate.",
                {"backlog": True, "bad_debt": False},
            ),
            StructuralVariant(
                "recovery_gates", "gate_bad_debt_only",
                "price stability, acceptable backlog and no material active bad debt",
                "ignore backlog while retaining price and active-bad-debt gates",
                "data/provenance/calibration/confidence/recovery_gate_specification.json",
                "available", "Isolate the unresolved-backlog gate.",
                {"backlog": False, "bad_debt": True},
            ),
            StructuralVariant(
                "recovery_gates", "gate_price_only",
                "price stability, acceptable backlog and no material active bad debt",
                "retain only the fixed price-stability gate",
                "data/provenance/calibration/confidence/recovery_gate_specification.json",
                "available", "Measure the joint contribution of liquidation gates.",
                {"backlog": False, "bad_debt": False},
            ),
        ]
    )
    records = [variant.as_registry_record() for variant in variants]
    if len({record["variant_id"] for record in records}) != len(records):
        raise ValueError("Structural variant identifiers are not unique.")
    if any(not record["one_factor_audit"] for record in records):
        raise ValueError("A structural variant changes more than one family.")
    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_variant_id": "primary_conditional_event",
        "variants": records,
        "source_validation": status,
        "variant_count": len(records),
        "executable_variant_count": sum(
            record["source_status"] == "available" for record in records
        ),
        "objective_used": False,
        "variant_selected": False,
        "runtime_adopted": False,
    }


def _baseline_ladder() -> pd.DataFrame:
    """Load the preserved 16-candidate, 64-replication baseline ladder."""
    context = json.loads((PRECISION_ROOT / "run_context.json").read_text())
    event_ids = tuple(context["design"]["all_event_ids"])
    digest_map = {
        hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:16]: event_id
        for event_id in event_ids
    }
    rows = []
    for path in sorted((PRECISION_ROOT / "ladder").glob("*.npz")):
        if "__r000_031" not in path.name and "__r032_063" not in path.name:
            continue
        arrays = search._load_npz(path)
        frame = pd.DataFrame(
            {key: value for key, value in arrays.items() if key != "result_checksum"}
        )
        frame["event_id"] = digest_map[path.name.split("__", 1)[0]]
        rows.append(frame)
    baseline = pd.concat(rows, ignore_index=True).sort_values(
        ["candidate_index", "event_id", "replication"], kind="mergesort"
    )
    expected = len(PANEL_INDICES) * EVENT_COUNT * REPLICATION_COUNT
    if (
        len(baseline) != expected
        or set(baseline["candidate_index"]) != set(PANEL_INDICES)
        or baseline[["candidate_index", "event_id", "replication"]].duplicated().any()
    ):
        raise ValueError("Preserved objective-blind baseline ladder is incomplete.")
    return baseline.reset_index(drop=True)


def _load_cache_owner() -> dict[str, Any]:
    context = json.loads((PARTIAL_ROOT / "run_context.json").read_text())
    if context["set_id"] != PARTIAL_IDENTIFICATION_ID:
        raise ValueError("Partial-identification context changed.")
    cache_root = Path(context["source_cache_directory"])
    manifest = json.loads(
        (cache_root / "cache_primary_manifest.json").read_text()
    )
    if manifest["cache_root_sha256"] != ALL_EVENT_CACHE_SHA256:
        raise ValueError("All-event cache root changed.")
    entries = {
        (entry["event_id"], int(entry["replication"])): entry
        for entry in manifest["packages"]
        if int(entry["replication"]) < REPLICATION_COUNT
    }
    if len(entries) != EVENT_COUNT * REPLICATION_COUNT:
        raise ValueError("All-event primary cache does not contain the fixed design.")
    transformed, candidates = sobol_candidates()
    structural_array = np.asarray(
        [
            [
                item.deterioration_adjustment,
                item.recovery_adjustment,
                item.confidence_floor,
                item.panic_response,
            ]
            for item in candidates
        ],
        dtype="<f8",
    )
    if search.array_sha256(structural_array) != SOBOL_SHA256:
        raise ValueError("Fixed Sobol grid changed.")
    return {
        "context": context,
        "cache_root": cache_root,
        "entries": entries,
        "candidates": tuple(candidates),
        "transformed": np.asarray(transformed, dtype="<f8"),
    }


def _package(owner: Mapping[str, Any], event_id: str, replication: int) -> search.CachedPackage:
    entry = owner["entries"][(event_id, replication)]
    metadata = json.loads(
        (
            owner["cache_root"] / "cache_primary" / entry["metadata_filename"]
        ).read_text()
    )
    arrays = search._load_npz(
        owner["cache_root"] / "cache_primary" / entry["arrays_filename"]
    )
    package = search.CachedPackage(metadata=metadata, arrays=arrays)
    return search.CachedPackage(
        metadata=metadata,
        arrays=arrays,
        path=search._path_from_package(package),
    )


def _state_from_package(package: search.CachedPackage) -> ConditionalInitialState:
    a = package.arrays
    m = package.metadata
    return ConditionalInitialState(
        event_id=m["event_id"],
        replication=int(m["replication"]),
        registry_id=REGISTRY_A,
        vault_seed=int(m["vault_seed"]),
        starting_eth_price=float(a["eth_prices"][0]),
        vault_count=len(a["debt_dai"]),
        total_debt_dai=float(np.sum(a["debt_dai"])),
        debt_dai=tuple(float(x) for x in a["debt_dai"]),
        collateral_ratios=tuple(float(x) for x in a["collateral_ratios"]),
        liquidation_ratios=tuple(float(x) for x in a["liquidation_ratios"]),
        initial_active_bad_debt_dai=0.0,
        initial_realised_bad_debt_dai=0.0,
        initial_unresolved_tab_dai=0.0,
        initial_trailing_cleared_tab_dai=0.0,
        initial_confidence=1.0,
        initial_stability_counter=0,
        collateral_mode=PRIMARY_COLLATERAL_MODE,
        state_checksum=m["initial_state_checksum"],
    )


def _historical_state(
    package: search.CachedPackage,
    snapshot: Mapping[str, Any],
    eligible: pd.DataFrame,
) -> ConditionalInitialState:
    timestamp = pd.Timestamp(snapshot["timestamp_utc"])
    selected = eligible.loc[
        eligible["timestamp_utc"].eq(timestamp)
        & eligible["_source_path"].eq(snapshot["source_path"])
        & eligible["state_label"].eq(snapshot["state_label"])
    ].sort_values(["ilk", "urn"], kind="mergesort")
    if selected.empty:
        raise ValueError("Registered historical snapshot has no eligible vaults.")
    rng = np.random.default_rng(int(package.metadata["vault_seed"]))
    positions = rng.choice(len(selected), size=500, replace=True)
    sampled = selected.iloc[positions]
    raw_debt = sampled["debt_dai"].to_numpy(dtype=float)
    debt = raw_debt * (2_500_000.0 / raw_debt.sum())
    ratios = sampled["collateral_ratio"].to_numpy(dtype=float)
    liquidation = sampled["liquidation_ratio"].to_numpy(dtype=float)
    payload = {
        "source_timestamp": timestamp.isoformat(),
        "debt_dai": debt.tolist(),
        "collateral_ratios": ratios.tolist(),
        "liquidation_ratios": liquidation.tolist(),
        "total_debt_dai": 2_500_000.0,
    }
    return ConditionalInitialState(
        event_id=package.metadata["event_id"],
        replication=int(package.metadata["replication"]),
        registry_id=REGISTRY_A,
        vault_seed=int(package.metadata["vault_seed"]),
        starting_eth_price=float(package.arrays["eth_prices"][0]),
        vault_count=500,
        total_debt_dai=2_500_000.0,
        debt_dai=tuple(float(x) for x in debt),
        collateral_ratios=tuple(float(x) for x in ratios),
        liquidation_ratios=tuple(float(x) for x in liquidation),
        initial_active_bad_debt_dai=0.0,
        initial_realised_bad_debt_dai=0.0,
        initial_unresolved_tab_dai=0.0,
        initial_trailing_cleared_tab_dai=0.0,
        initial_confidence=1.0,
        initial_stability_counter=0,
        collateral_mode=PRIMARY_COLLATERAL_MODE,
        state_checksum=search.payload_sha256(payload),
    )


def _variant_package(
    package: search.CachedPackage,
    variant: Mapping[str, Any],
    *,
    config: ConditionalEventSimulationConfig,
    eligible_snapshots: pd.DataFrame,
    residual_values: np.ndarray,
    base_liquidation_config: Any | None = None,
    demand_template: LiquidationDemandProcess | None = None,
) -> tuple[search.CachedPackage, ConditionalEventSimulationConfig]:
    arrays = dict(package.arrays)
    metadata = dict(package.metadata)
    settings = variant["settings"]
    variant_config = config
    family = variant["family"]
    if family == "vault_state":
        state = _historical_state(package, settings["snapshot"], eligible_snapshots)
        arrays.update(
            simulate_candidate_invariant_liquidation_path(
                state=state,
                path=package.path,
                replication=int(package.metadata["replication"]),
                registry_id=REGISTRY_A,
                config=config,
                maximum_liquidations_per_step=None,
                base_liquidation_config=base_liquidation_config,
                demand_template=demand_template,
            )
        )
        metadata["initial_state_checksum"] = state.state_checksum
    elif family == "liquidation_capacity":
        capacity = int(settings["maximum_liquidations_per_step"])
        # If the uncapped path never reaches the proposed ceiling, identical
        # streams and mechanics make the intervention exactly non-binding.
        if int(np.max(arrays["liquidation_attempts"])) > capacity:
            arrays.update(
                simulate_candidate_invariant_liquidation_path(
                    state=_state_from_package(package),
                    path=package.path,
                    replication=int(package.metadata["replication"]),
                    registry_id=REGISTRY_A,
                    config=config,
                    maximum_liquidations_per_step=capacity,
                    base_liquidation_config=base_liquidation_config,
                    demand_template=demand_template,
                )
            )
    elif family == "residual_process":
        if settings["mode"] == "zero":
            arrays["residual_innovations"] = np.zeros_like(
                arrays["residual_innovations"], dtype="<f8"
            )
        else:
            rng = np.random.default_rng(int(metadata["market_seed"]))
            arrays["residual_innovations"] = rng.choice(
                residual_values,
                size=len(arrays["residual_innovations"]),
                replace=True,
            ).astype("<f8")
    elif family == "stress_construction":
        variant_config = replace(
            config,
            peg_stress_weight=float(settings["peg_weight"]),
            collateral_stress_weight=float(settings["collateral_weight"]),
        )
        variant_config.validate()
    elif family == "recovery_gates":
        if not settings["backlog"]:
            arrays["liquidation_gate_open"] = np.ones_like(
                arrays["liquidation_gate_open"], dtype="?"
            )
        if not settings["bad_debt"]:
            arrays["material_active_bad_debt"] = np.zeros_like(
                arrays["material_active_bad_debt"], dtype="?"
            )
    else:
        raise ValueError(f"Unsupported executable structural family: {family}.")
    return (
        search.CachedPackage(
            metadata=metadata,
            arrays=arrays,
            path=package.path,
        ),
        variant_config,
    )


def _moment_estimate(frame: pd.DataFrame, moment: str) -> Any:
    if moment in MEAN_MOMENTS:
        return analytic_equal_event_mcse(frame, outcome=MEAN_MOMENTS[moment])
    return analytic_contrast_mcse(
        frame,
        outcome="first_six_hour_burden",
        stratifier="initial_peg_gap",
    )


def _candidate_variant_checkpoint(
    *,
    candidate_index: int,
    variant: Mapping[str, Any],
    variant_frame: pd.DataFrame,
    baseline_frame: pd.DataFrame,
    structural_pass: bool,
    constraints: pd.DataFrame,
) -> dict[str, Any]:
    joined = baseline_frame.merge(
        variant_frame,
        on=["event_id", "replication"],
        suffixes=("_baseline", "_variant"),
        validate="one_to_one",
    )
    rows = []
    for moment in STAGE2_ACTIVE_MOMENTS:
        baseline_estimate = _moment_estimate(baseline_frame, moment)
        variant_estimate = _moment_estimate(variant_frame, moment)
        if moment in MEAN_MOMENTS:
            source = MEAN_MOMENTS[moment]
            differences = joined.assign(
                paired_difference=joined[f"{source}_variant"]
                - joined[f"{source}_baseline"]
            )
            paired = analytic_equal_event_mcse(
                differences,
                outcome="paired_difference",
            )
        else:
            differences = joined.assign(
                paired_difference=joined["first_six_hour_burden_variant"]
                - joined["first_six_hour_burden_baseline"],
                initial_peg_gap=joined["initial_peg_gap_baseline"],
            )
            paired = analytic_contrast_mcse(
                differences,
                outcome="paired_difference",
                stratifier="initial_peg_gap",
            )
        band = constraints.loc[moment]
        lower = float(band["adjusted_band_lower"])
        upper = float(band["adjusted_band_upper"])
        scale = float(band["empirical_scale"])
        baseline_interval = construct_mc_interval(
            estimate=baseline_estimate.point_estimate,
            mcse=baseline_estimate.analytic_mcse,
            natural_support=NATURAL_SUPPORTS[moment],
        )
        variant_interval = construct_mc_interval(
            estimate=variant_estimate.point_estimate,
            mcse=variant_estimate.analytic_mcse,
            natural_support=NATURAL_SUPPORTS[moment],
        )
        baseline_gap = signed_band_gap(
            baseline_estimate.point_estimate, lower, upper
        )
        variant_gap = signed_band_gap(
            variant_estimate.point_estimate, lower, upper
        )
        rows.append(
            {
                "moment": moment,
                "baseline_moment": baseline_estimate.point_estimate,
                "variant_moment": variant_estimate.point_estimate,
                "paired_shift": paired.point_estimate,
                "paired_mcse": paired.analytic_mcse,
                "paired_snr": (
                    math.inf
                    if paired.analytic_mcse == 0.0 and paired.point_estimate != 0.0
                    else 0.0
                    if paired.analytic_mcse == 0.0
                    else abs(paired.point_estimate) / paired.analytic_mcse
                ),
                "shift_scales": paired.point_estimate / scale,
                "baseline_signed_gap": baseline_gap,
                "variant_signed_gap": variant_gap,
                "baseline_gap_scales": baseline_gap / scale,
                "variant_gap_scales": variant_gap / scale,
                "absolute_band_gap_reduction": abs(baseline_gap) - abs(variant_gap),
                "absolute_band_gap_reduction_scales": (
                    abs(baseline_gap) - abs(variant_gap)
                ) / scale,
                "movement_towards_band": abs(variant_gap) < abs(baseline_gap),
                "baseline_outer_pass": (
                    baseline_interval.adjusted_upper >= lower
                    and baseline_interval.adjusted_lower <= upper
                ),
                "variant_outer_pass": (
                    variant_interval.adjusted_upper >= lower
                    and variant_interval.adjusted_lower <= upper
                ),
            }
        )
    def numerical_pass(frame: pd.DataFrame) -> bool:
        durations = frame["recovery_completion_hours"].astype(float) + 1.0
        share = float(
            (
                frame["numerical_bound_binding_share"].astype(float) * durations
            ).sum()
            / durations.sum()
        )
        return share <= NUMERICAL_BOUND_LIMIT

    diagnostics = {
        "baseline_numerical_bound_pass": numerical_pass(baseline_frame),
        "variant_numerical_bound_pass": numerical_pass(variant_frame),
        "structural_pass": bool(structural_pass),
        "stage1_preservation_pass": True,
        "censoring_change": float(
            variant_frame["right_censored"].mean()
            - baseline_frame["right_censored"].mean()
        ),
        "active_bad_debt_change": float(
            variant_frame["maximum_active_bad_debt_dai"].gt(0.0).mean()
            - baseline_frame["maximum_active_bad_debt_dai"].gt(0.0).mean()
        ),
        "unresolved_backlog_change": float(
            variant_frame["maximum_unresolved_tab_dai"].gt(0.0).mean()
            - baseline_frame["maximum_unresolved_tab_dai"].gt(0.0).mean()
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_index": candidate_index,
        "variant_id": variant["variant_id"],
        "family": variant["family"],
        "event_count": EVENT_COUNT,
        "replication_count": REPLICATION_COUNT,
        "registry": REGISTRY_A,
        "moment_results": rows,
        "diagnostics": diagnostics,
        "objective_calculated": False,
        "rank_calculated": False,
        "candidate_selected": False,
        "variant_selected": False,
        "runtime_adopted": False,
    }


_WORKER_OWNER: dict[str, Any] | None = None


def _worker_initialise(root_text: str) -> None:
    global _WORKER_OWNER
    search._thread_cap()
    owner = _load_cache_owner()
    context = owner["context"]
    owner["config"] = ConditionalEventSimulationConfig(**context["config"])
    owner["constraints"] = _constraints()
    owner["baseline"] = _baseline_ladder()
    eligible, _ = _snapshot_catalogue()
    owner["eligible_snapshots"] = eligible
    _, _, stage1 = load_stage1_owners()
    owner["residual_values"] = np.asarray(
        stage1["source"].centred_residuals, dtype="<f8"
    )
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    owner["base_liquidation_config"] = bundle.base_bundle.liquidation_config
    owner["demand_template"] = LiquidationDemandProcess(
        _liquidation_demand_config(DEFAULT_TRANCHE_B_CONFIG_PATH, seed=0)
    )
    owner["root"] = Path(root_text)
    _WORKER_OWNER = owner


def _checkpoint_path(root: Path, variant_id: str, candidate_index: int) -> Path:
    return root / "checkpoints" / variant_id / f"candidate_{candidate_index:03d}.json"


def _shard_path(root: Path, shard_index: int) -> Path:
    return root / "shards" / f"event_shard_{shard_index:02d}.npz"


def _event_shard(
    task: tuple[int, tuple[str, ...], tuple[dict[str, Any], ...]]
) -> dict[str, Any]:
    if _WORKER_OWNER is None:
        raise RuntimeError("Structural-diagnosis worker is not initialised.")
    shard_index, event_ids, variants = task
    owner = _WORKER_OWNER
    output_path = _shard_path(owner["root"], shard_index)
    if output_path.is_file():
        arrays = search._load_npz(output_path)
        expected = len(event_ids) * REPLICATION_COUNT * len(variants) * len(PANEL_INDICES)
        if len(arrays["candidate_index"]) != expected:
            raise ValueError(f"Incomplete structural event shard: {output_path}.")
        return {
            "shard_index": shard_index,
            "event_count": len(event_ids),
            "evaluations": 0,
            "resumed": True,
        }
    records: list[dict[str, Any]] = []
    for event_id in sorted(event_ids):
        for replication in range(REPLICATION_COUNT):
            package = _package(owner, event_id, replication)
            for variant in variants:
                variant_package, variant_config = _variant_package(
                    package,
                    variant,
                    config=owner["config"],
                    eligible_snapshots=owner["eligible_snapshots"],
                    residual_values=owner["residual_values"],
                    base_liquidation_config=owner["base_liquidation_config"],
                    demand_template=owner["demand_template"],
                )
                worker_context = search.WorkerContext(
                    run_dir=owner["root"],
                    search_id=PARTIAL_IDENTIFICATION_ID,
                    event_ids=(event_id,),
                    config=variant_config,
                    stage1=owner["context"]["stage1"],
                    scaling=owner["context"]["scaling"],
                    ordinary_preservation=owner["context"]["ordinary_preservation"],
                    objective={},
                    candidates=owner["candidates"],
                    transformed=owner["transformed"],
                    packages={(event_id, replication): variant_package},
                )
                for index in PANEL_INDICES:
                    metrics, _, flags = search._evaluate_cached_event(
                        worker_context,
                        candidate=owner["candidates"][index],
                        event_id=event_id,
                        replication=replication,
                    )
                    records.append(
                        {
                            "candidate_index": index,
                            "variant_id": variant["variant_id"],
                            **metrics,
                            "structural_pass": search.structural_event_flags_pass(
                                flags
                            ),
                        }
                    )
    frame = pd.DataFrame(records).sort_values(
        ["variant_id", "candidate_index", "event_id", "replication"],
        kind="mergesort",
    )
    arrays = {}
    for column in frame.columns:
        values = frame[column].to_numpy()
        if values.dtype == object:
            values = values.astype(str)
        arrays[column] = values
    search._atomic_npz(output_path, arrays)
    return {
        "shard_index": shard_index,
        "event_count": len(event_ids),
        "evaluations": len(frame),
        "resumed": False,
    }


def _write_candidate_checkpoints_from_shards(
    *,
    root: Path,
    variants: Sequence[Mapping[str, Any]],
    shard_count: int,
) -> int:
    baseline = _baseline_ladder()
    constraints = _constraints()
    frames = []
    for shard_index in range(shard_count):
        arrays = search._load_npz(_shard_path(root, shard_index))
        frames.append(pd.DataFrame(arrays))
    combined = pd.concat(frames, ignore_index=True)
    written = 0
    for variant in variants:
        for index in PANEL_INDICES:
            path = _checkpoint_path(root, variant["variant_id"], index)
            if path.is_file():
                continue
            frame = combined.loc[
                combined["variant_id"].eq(variant["variant_id"])
                & combined["candidate_index"].eq(index)
            ].copy()
            frame["candidate_index"] = pd.to_numeric(
                frame["candidate_index"], errors="raise"
            ).astype(int)
            frame["replication"] = pd.to_numeric(
                frame["replication"], errors="raise"
            ).astype(int)
            baseline_frame = baseline.loc[
                baseline["candidate_index"].eq(index)
            ].copy()
            checkpoint = _candidate_variant_checkpoint(
                candidate_index=index,
                variant=variant,
                variant_frame=frame,
                baseline_frame=baseline_frame,
                structural_pass=bool(frame["structural_pass"].astype(bool).all()),
                constraints=constraints,
            )
            deterministic = dict(checkpoint)
            checkpoint["result_checksum"] = search.payload_sha256(deterministic)
            _atomic_json(path, checkpoint)
            written += 1
    return written


def validate_inputs(
    *,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    root: Path = DEFAULT_ROOT,
) -> dict[str, Any]:
    """Validate immutable evidence, cache ownership, sources and storage."""
    if sha256_file(
        evidence_dir / "partial_identification_candidates.csv"
    ) != json.loads(
        (evidence_dir / "partial_identification_reproducibility.json").read_text()
    )["deterministic_evidence_checksums"][
        "partial_identification_candidates.csv"
    ]:
        raise ValueError("Committed candidate evidence checksum changed.")
    panel = json.loads(
        (evidence_dir / "monte_carlo_candidate_panel.json").read_text()
    )
    if (
        tuple(panel["candidate_indices"]) != PANEL_INDICES
        or panel["panel_checksum"] != PANEL_SHA256
    ):
        raise ValueError("Objective-blind candidate panel changed.")
    owner = _load_cache_owner()
    baseline = _baseline_ladder()
    candidates = _candidates(evidence_dir)
    for index in PANEL_INDICES:
        observed = float(
            baseline.loc[
                baseline["candidate_index"].eq(index),
                "first_six_hour_burden",
            ].mean()
        )
        expected = float(
            candidates.loc[
                candidates["candidate_index"].eq(index),
                "first_six_hour_burden__simulated_mean",
            ].iloc[0]
        )
        if not math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-14):
            raise ValueError("Preserved baseline ladder does not reproduce.")
    free = shutil.disk_usage(REPOSITORY_ROOT).free
    existing_size = sum(
        path.stat().st_size for path in Path(root).rglob("*") if path.is_file()
    ) if Path(root).exists() else 0
    if free < MINIMUM_FREE_BYTES:
        raise ValueError("Fewer than 10 GiB are free.")
    if existing_size > MAX_NEW_STORAGE_BYTES:
        raise ValueError("Structural diagnostics exceed the 750 MB cap.")
    registry = build_variant_registry()
    return {
        "status": "passed",
        "partial_identification_identity": owner["context"]["set_id"],
        "all_event_cache_root_sha256": ALL_EVENT_CACHE_SHA256,
        "panel_sha256": PANEL_SHA256,
        "baseline_rows_reused": len(baseline),
        "free_bytes": free,
        "existing_structural_diagnostics_bytes": existing_size,
        "projected_new_storage_bytes": 25 * 1024**2,
        "variant_count": registry["variant_count"],
        "executable_variant_count": registry["executable_variant_count"],
        "gas_source_status": registry["source_validation"]["gas"]["status"],
        "vault_source_status": registry["source_validation"]["vault"]["status"],
    }


def run_structural_panel(
    *,
    root: Path = DEFAULT_ROOT,
    workers: int = 4,
    resume: bool = False,
) -> dict[str, Any]:
    """Run or resume the fixed process-parallel one-factor panel."""
    if workers < 1 or workers > 6:
        raise ValueError("workers must be between one and six.")
    validation = validate_inputs(root=root)
    registry = build_variant_registry()
    variants = tuple(
        record for record in registry["variants"]
        if record["source_status"] == "available"
    )
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    existing = [
        path for path in (root / "checkpoints").glob("*/*.json")
    ] if (root / "checkpoints").exists() else []
    existing_shards = (
        list((root / "shards").glob("event_shard_*.npz"))
        if (root / "shards").exists()
        else []
    )
    if (existing or existing_shards) and not resume:
        raise ValueError("Structural checkpoints or shards exist; use explicit resume.")
    event_ids = tuple(sorted(_load_cache_owner()["context"]["event_ids"]))
    event_shards = tuple(
        tuple(event_ids[offset::workers]) for offset in range(workers)
        if event_ids[offset::workers]
    )
    tasks = tuple(
        (index, event_shard, variants)
        for index, event_shard in enumerate(event_shards)
    )
    started = time.perf_counter()
    context = mp.get_context("spawn")
    with context.Pool(
        processes=len(tasks),
        initializer=_worker_initialise,
        initargs=(str(root),),
    ) as pool:
        results = pool.map(_event_shard, tasks)
    checkpoints_written = _write_candidate_checkpoints_from_shards(
        root=root,
        variants=variants,
        shard_count=len(tasks),
    )
    elapsed = time.perf_counter() - started
    checkpoint_count = len(list((root / "checkpoints").glob("*/*.json")))
    expected_checkpoints = len(variants) * len(PANEL_INDICES)
    if checkpoint_count != expected_checkpoints:
        raise ValueError("Structural panel checkpoints are incomplete.")
    history_path = root / "run_history.json"
    history = (
        json.loads(history_path.read_text()) if history_path.is_file()
        else {"schema_version": SCHEMA_VERSION, "runs": []}
    )
    history["runs"].append(
        {
            "action": "resume" if resume else "run",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "workers": workers,
            "duration_seconds": elapsed,
            "evaluations": sum(item["evaluations"] for item in results),
            "checkpoint_count": checkpoint_count,
            "event_shard_count": len(tasks),
            "checkpoints_written": checkpoints_written,
        }
    )
    _atomic_json(history_path, history)
    return {
        **validation,
        "status": "completed",
        "workers": workers,
        "duration_seconds": elapsed,
        "executed_variant_count": len(variants),
        "unavailable_variant_count": registry["variant_count"] - len(variants),
        "checkpoint_count": checkpoint_count,
        "evaluation_count": len(variants) * EXPECTED_EVALUATIONS_PER_VARIANT,
        "new_evaluations_this_run": sum(item["evaluations"] for item in results),
    }


def _load_checkpoints(root: Path = DEFAULT_ROOT) -> pd.DataFrame:
    registry = build_variant_registry()
    family = {
        item["variant_id"]: item["family"] for item in registry["variants"]
    }
    rows = []
    for path in sorted((Path(root) / "checkpoints").glob("*/*.json")):
        payload = json.loads(path.read_text())
        deterministic = {
            key: value for key, value in payload.items() if key != "result_checksum"
        }
        if search.payload_sha256(deterministic) != payload["result_checksum"]:
            raise ValueError(f"Structural checkpoint checksum differs: {path}.")
        for moment in payload["moment_results"]:
            rows.append(
                {
                    "family": family[payload["variant_id"]],
                    "variant_id": payload["variant_id"],
                    "candidate_index": payload["candidate_index"],
                    **moment,
                    **payload["diagnostics"],
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["family", "variant_id", "candidate_index", "moment"], kind="mergesort"
    ).reset_index(drop=True)


def material_directional_effect(group: pd.DataFrame) -> bool:
    """Apply the fixed 12/16, 8/16, SNR and median-gap rule."""
    if group["candidate_index"].nunique() != 16:
        raise ValueError("Material-effect classification requires 16 candidates.")
    towards = int(group["movement_towards_band"].astype(bool).sum())
    large_and_precise = int(
        (
            group["shift_scales"].abs().ge(0.5)
            & group["paired_snr"].ge(2.0)
        ).sum()
    )
    median_reduction = float(
        group["absolute_band_gap_reduction_scales"].median()
    )
    return towards >= 12 and large_and_precise >= 8 and median_reduction >= 0.5


def constraint_resolved(group: pd.DataFrame) -> bool:
    """Apply the fixed candidate-panel diagnostic resolution rule."""
    baseline_valid = int(group["baseline_numerical_bound_pass"].astype(bool).sum())
    variant_valid = int(group["variant_numerical_bound_pass"].astype(bool).sum())
    return bool(
        group["variant_outer_pass"].astype(bool).sum() >= 12
        and group["structural_pass"].astype(bool).all()
        and group["stage1_preservation_pass"].astype(bool).all()
        and variant_valid >= baseline_valid - 4
    )


def classify_variant(group: pd.DataFrame) -> dict[str, Any]:
    """Classify one executed variant without ranking it."""
    if not group["structural_pass"].astype(bool).all() or not group[
        "stage1_preservation_pass"
    ].astype(bool).all():
        return {
            "classification": "structurally_invalid",
            "material": [],
            "resolved": [],
            "tradeoff": False,
            "large_worsening": False,
        }
    material = sorted(
        moment for moment, values in group.groupby("moment", sort=True)
        if material_directional_effect(values)
    )
    resolved = sorted(
        moment for moment, values in group.groupby("moment", sort=True)
        if constraint_resolved(values)
    )
    large_worsening = any(
        int(
            (
                values["movement_towards_band"].eq(False)
                & (
                    values["variant_gap_scales"].abs()
                    - values["baseline_gap_scales"].abs()
                ).ge(1.0)
            ).sum()
        ) >= 12
        for _, values in group.groupby("moment", sort=True)
    )
    tradeoff = bool((resolved or material) and large_worsening)
    if tradeoff:
        classification = "tradeoff"
    elif len(resolved) >= 2:
        classification = "multi_constraint_resolution"
    elif len(resolved) == 1:
        classification = "single_constraint_resolution"
    elif material:
        classification = "directionally_helpful_but_insufficient"
    else:
        classification = "no_material_effect"
    return {
        "classification": classification,
        "material": material,
        "resolved": resolved,
        "tradeoff": tradeoff,
        "large_worsening": large_worsening,
    }


def classify_family(variant_summaries: Sequence[Mapping[str, Any]]) -> str:
    """Apply fixed family-level explanatory-signal rules."""
    if all(item["classification"] == "source_unavailable" for item in variant_summaries):
        return "unavailable"
    if any(item["classification"] == "tradeoff" for item in variant_summaries):
        return "tradeoff_family"
    if any(
        len(item["resolved"]) >= 3
        and len(set(item["material"]) - set(item["resolved"])) >= 1
        for item in variant_summaries
    ):
        return "strong_explanatory_signal"
    if any(
        1 <= len(item["resolved"]) <= 2 or len(item["material"]) >= 2
        for item in variant_summaries
    ):
        return "partial_explanatory_signal"
    return "no_explanatory_signal"


def overall_classification(
    family_classes: Mapping[str, str],
    domain_signal: Mapping[str, Any],
) -> tuple[str, str]:
    """Apply the pre-registered overall diagnosis hierarchy."""
    strong = [key for key, value in family_classes.items() if value == "strong_explanatory_signal"]
    partial = [key for key, value in family_classes.items() if value == "partial_explanatory_signal"]
    if len(strong) == 1 and not partial:
        return (
            "single_structural_family_dominant",
            "Pre-register a revised experiment changing only the dominant family.",
        )
    if len(strong) + len(partial) >= 2:
        return (
            "multiple_structural_families_contribute",
            "Pre-register a small objective-blind factorial structural experiment.",
        )
    if not strong and domain_signal["possible"]:
        return (
            "parameter_domain_truncation_possible",
            "Externally justify amended bounds before any new parameter grid.",
        )
    return (
        "conditional_event_design_mismatch_unresolved",
        "Cease empirical Stage 2 calibration and retain confidence parameters as scenarios.",
    )


def summarise_structural_diagnosis(
    *,
    root: Path = DEFAULT_ROOT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    register_manifest: bool = True,
) -> dict[str, Any]:
    """Build deterministic compact evidence from preserved and new checkpoints."""
    input_validation = validate_inputs(evidence_dir=evidence_dir, root=root)
    candidates = _candidates(evidence_dir)
    constraints = _constraints(evidence_dir)
    mismatch, cofailure = decompose_baseline_mismatch(candidates, constraints)
    trends = parameter_boundary_trends(candidates, constraints)
    domain = parameter_domain_signal(trends)
    hard_gates = hard_gate_decomposition(candidates)
    registry = build_variant_registry()
    results = _load_checkpoints(root)
    variant_summaries = []
    for variant in registry["variants"]:
        if variant["source_status"] != "available":
            summary = {
                "variant_id": variant["variant_id"],
                "family": variant["family"],
                "classification": "source_unavailable",
                "material": [],
                "resolved": [],
                "tradeoff": False,
                "large_worsening": False,
            }
        else:
            summary = {
                "variant_id": variant["variant_id"],
                "family": variant["family"],
                **classify_variant(
                    results.loc[results["variant_id"].eq(variant["variant_id"])]
                ),
            }
        variant_summaries.append(summary)
    family_classes = {
        family: classify_family(
            [item for item in variant_summaries if item["family"] == family]
        )
        for family in FAMILIES
    }
    overall, next_boundary = overall_classification(family_classes, domain)
    specification = {
        "schema_version": SCHEMA_VERSION,
        "fixed_baseline": {
            "partial_identification_identity": PARTIAL_IDENTIFICATION_ID,
            "classification": "model_evidence_incompatibility",
            "inner_admissible": 0,
            "outer_admissible": 0,
            "rejected": 256,
        },
        "baseline_bands": [
            {
                "moment": row["moment"],
                "lower": row["adjusted_band_lower"],
                "upper": row["adjusted_band_upper"],
                "scale": row["empirical_scale"],
            }
            for _, row in constraints.reset_index(drop=True).iterrows()
        ],
        "mismatch_rules": {
            "systematic": "at least 90% of intervals on one side",
            "mixed": "at least 25% below and at least 25% above",
            "mc_uncertainty": "at least 25% means inside and fewer than 10% inner-pass",
            "hard_gate": "at least 25% otherwise outer-pass and fail a hard gate",
        },
        "one_factor_rule": True,
        "variant_families": list(FAMILIES),
        "candidate_panel": list(PANEL_INDICES),
        "candidate_panel_sha256": PANEL_SHA256,
        "events": EVENT_COUNT,
        "replications": REPLICATION_COUNT,
        "registry": REGISTRY_A,
        "paired_effect_rules": {
            "towards_band": "at least 12/16 candidates",
            "large_precise_shift": "at least 8/16 with |shift|>=0.5s and SNR>=2",
            "median_gap_reduction": "at least 0.5s",
        },
        "constraint_resolution_rule": (
            "at least 12/16 outer passes, zero structural and Stage 1 failures, "
            "and no decline of more than four numerical-valid candidates"
        ),
        "variant_classification_rule": (
            "fixed mutually exclusive no-effect, helpful-insufficient, single- "
            "or multi-resolution, trade-off, invalid and unavailable classes"
        ),
        "family_classification_rule": (
            "fixed strong, partial, trade-off, unavailable and no-signal classes"
        ),
        "overall_classification_rule": (
            "single dominant family; multiple contributors; possible parameter-"
            "domain truncation; unresolved design mismatch; or invalid diagnosis"
        ),
        "scalar_objective": None,
        "candidate_ranking": False,
        "parameter_selected": False,
        "structural_model_selected": False,
        "runtime_adopted": False,
    }
    family_payload = {
        "schema_version": SCHEMA_VERSION,
        "variant_classifications": variant_summaries,
        "family_classifications": family_classes,
        "source_unavailable_variants": [
            item["variant_id"] for item in variant_summaries
            if item["classification"] == "source_unavailable"
        ],
        "constraint_resolution_counts": {
            item["variant_id"]: len(item["resolved"])
            for item in variant_summaries
        },
        "tradeoff_variants": [
            item["variant_id"]
            for item in variant_summaries
            if item["classification"] == "tradeoff"
        ],
        "large_worsening_variants": [
            item["variant_id"]
            for item in variant_summaries
            if item["large_worsening"]
        ],
        "model_adopted": False,
        "variant_selected": False,
        "runtime_adopted": False,
    }
    decision = {
        "schema_version": SCHEMA_VERSION,
        "overall_classification": overall,
        "dominant_or_contributing_families": [
            family for family, classification in family_classes.items()
            if classification in {"strong_explanatory_signal", "partial_explanatory_signal"}
        ],
        "parameter_domain_signal": domain,
        "unresolved_constraints": sorted(
            set(STAGE2_ACTIVE_MOMENTS).difference(
                moment
                for item in variant_summaries
                for moment in item["resolved"]
            )
        ),
        "authorised_next_boundary": next_boundary,
        "parameter_selected": False,
        "structural_model_selected": False,
        "runtime_adopted": False,
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(evidence_dir / EVIDENCE_NAMES[0], specification)
    _atomic_csv(evidence_dir / EVIDENCE_NAMES[1], mismatch)
    _atomic_csv(evidence_dir / EVIDENCE_NAMES[2], trends)
    _atomic_json(evidence_dir / EVIDENCE_NAMES[3], registry)
    _atomic_csv(evidence_dir / EVIDENCE_NAMES[4], results)
    _atomic_json(evidence_dir / EVIDENCE_NAMES[5], family_payload)
    _atomic_json(evidence_dir / EVIDENCE_NAMES[6], decision)
    diagnostic_files = [
        Path(root) / "constraint_cofailures.csv",
        Path(root) / "hard_gate_decomposition.json",
    ]
    _atomic_csv(diagnostic_files[0], cofailure)
    _atomic_json(diagnostic_files[1], hard_gates)
    vault_state_audit = _vault_state_audit(root=Path(root), registry=registry)
    deterministic_paths = [
        evidence_dir / name for name in EVIDENCE_NAMES[:7]
    ]
    checkpoint_paths = sorted((Path(root) / "checkpoints").glob("*/*.json"))
    reproducibility = {
        "schema_version": SCHEMA_VERSION,
        "source_partial_identification_identity": PARTIAL_IDENTIFICATION_ID,
        "fixed_sobol_sha256": SOBOL_SHA256,
        "all_event_cache_root_sha256": ALL_EVENT_CACHE_SHA256,
        "panel_sha256": PANEL_SHA256,
        "variant_identities": {
            item["variant_id"]: search.payload_sha256(item)
            for item in registry["variants"]
        },
        "paired_stream_ownership": (
            "identical registry-A event, replication, vault, market and "
            "liquidation stream identities wherever the intervention permits"
        ),
        "checkpoint_count": len(checkpoint_paths),
        "checkpoint_checksums": {
            path.relative_to(Path(root)).as_posix(): sha256_file(path)
            for path in checkpoint_paths
        },
        "vault_state_audit": {
            "path": vault_state_audit.relative_to(Path(root)).as_posix(),
            "sha256": sha256_file(vault_state_audit),
            "row_count": 2 * EVENT_COUNT * REPLICATION_COUNT,
        },
        "deterministic_evidence_checksums": {
            path.name: sha256_file(path) for path in deterministic_paths
        },
        "objective_ranking_used": False,
        "final_validation_data_used": False,
        "parameter_selected": False,
        "structural_model_selected": False,
        "runtime_adopted": False,
    }
    _atomic_json(evidence_dir / EVIDENCE_NAMES[7], reproducibility)
    history = json.loads((Path(root) / "run_history.json").read_text())
    run_seconds = sum(float(item["duration_seconds"]) for item in history["runs"])
    executed = registry["executable_variant_count"] * EXPECTED_EVALUATIONS_PER_VARIANT
    ignored_size = sum(
        path.stat().st_size for path in Path(root).rglob("*") if path.is_file()
    )
    benchmark = {
        "schema_version": SCHEMA_VERSION,
        "variant_count": registry["variant_count"],
        "executed_variant_count": registry["executable_variant_count"],
        "evaluation_count": executed,
        "baseline_evaluations_reused": len(_baseline_ladder()),
        "cache_packages_reused_without_duplication": EVENT_COUNT * REPLICATION_COUNT,
        "wall_time_seconds": run_seconds,
        "throughput_evaluations_per_second": executed / run_seconds,
        "worker_count": max(int(item["workers"]) for item in history["runs"]),
        "ignored_output_size_bytes": ignored_size,
        "host_dependent": True,
        "projected_next_pass_cost": "not authorised; requires pre-registration",
    }
    _atomic_json(evidence_dir / EVIDENCE_NAMES[8], benchmark)
    if register_manifest:
        _register_manifest(evidence_dir)
    return {
        **input_validation,
        "status": "completed",
        "overall_classification": overall,
        "family_classifications": family_classes,
        "variant_classifications": variant_summaries,
        "parameter_domain_signal": domain,
        "evaluation_count": executed,
        "compact_evidence": {
            name: sha256_file(evidence_dir / name) for name in EVIDENCE_NAMES
        },
        "runtime_adopted": False,
    }


def _register_manifest(evidence_dir: Path) -> None:
    manifest_path = REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    artefacts = {
        item["path"]: item for item in manifest["artefacts"]
    }
    for name in EVIDENCE_NAMES:
        path = evidence_dir / name
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        artefacts[relative] = {
            "path": relative,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "producer": "dai_sim.calibration.structural_incompatibility",
            "classification": "snapshot",
            "semantic_name": Path(name).stem,
            "schema": "Compact structural-incompatibility calibration evidence.",
            "context": (
                "Objective-blind one-factor diagnosis; no candidate, structural "
                "model or runtime value is selected."
            ),
            "runtime_adopted": False,
        }
    manifest["artefacts"] = [artefacts[key] for key in sorted(artefacts)]
    search._atomic_bytes(
        manifest_path,
        (
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False)
            + "\n"
        ).encode("utf-8"),
    )


def validate_completed_diagnosis(
    *,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> dict[str, Any]:
    """Validate schemas, manifest checksums and all non-selection boundaries."""
    manifest_path = REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
    manifest = {
        item["path"]: item
        for item in json.loads(manifest_path.read_text())["artefacts"]
    }
    invalid = []
    for name in EVIDENCE_NAMES:
        path = evidence_dir / name
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        if (
            not path.is_file()
            or relative not in manifest
            or manifest[relative]["sha256"] != sha256_file(path)
        ):
            invalid.append(relative)
    if invalid:
        raise ValueError(f"Structural evidence is invalid: {invalid}.")
    specification = json.loads((evidence_dir / EVIDENCE_NAMES[0]).read_text())
    registry = json.loads((evidence_dir / EVIDENCE_NAMES[3]).read_text())
    results = pd.read_csv(evidence_dir / EVIDENCE_NAMES[4])
    decision = json.loads((evidence_dir / EVIDENCE_NAMES[6]).read_text())
    reproducibility = json.loads((evidence_dir / EVIDENCE_NAMES[7]).read_text())
    if (
        specification["scalar_objective"] is not None
        or specification["candidate_ranking"]
        or specification["parameter_selected"]
        or specification["structural_model_selected"]
        or decision["parameter_selected"]
        or decision["structural_model_selected"]
        or reproducibility["objective_ranking_used"]
        or reproducibility["final_validation_data_used"]
    ):
        raise ValueError("Selection, ranking, objective or validation data entered.")
    expected_rows = (
        registry["executable_variant_count"] * len(PANEL_INDICES) * len(STAGE2_ACTIVE_MOMENTS)
    )
    if len(results) != expected_rows:
        raise ValueError("Structural result table dimensions differ.")
    if any(
        payload.get("runtime_adopted")
        for payload in (specification, registry, decision, reproducibility)
    ):
        raise ValueError("Structural diagnostics cannot be runtime adopted.")
    return {
        "status": "passed",
        "overall_classification": decision["overall_classification"],
        "variant_count": registry["variant_count"],
        "executed_variant_count": registry["executable_variant_count"],
        "result_rows": len(results),
        "parameter_selected": False,
        "structural_model_selected": False,
        "runtime_adopted": False,
    }


def run_structural_review(
    *,
    action: str,
    root: Path = DEFAULT_ROOT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    workers: int = 4,
) -> dict[str, Any]:
    """Dispatch explicit local-only structural-diagnosis operations."""
    if action == "validate-inputs":
        return validate_inputs(evidence_dir=evidence_dir, root=root)
    if action == "decompose-baseline":
        mismatch, _ = decompose_baseline_mismatch(
            _candidates(evidence_dir), _constraints(evidence_dir)
        )
        return {"status": "completed", "constraints": mismatch.to_dict("records")}
    if action == "audit-boundaries":
        trends = parameter_boundary_trends(
            _candidates(evidence_dir), _constraints(evidence_dir)
        )
        return {"status": "completed", "domain_signal": parameter_domain_signal(trends)}
    if action == "build-registry":
        return build_variant_registry()
    if action == "validate-sources":
        return build_variant_registry()["source_validation"]
    if action == "run-panel":
        return run_structural_panel(root=root, workers=workers, resume=False)
    if action == "resume-panel":
        return run_structural_panel(root=root, workers=workers, resume=True)
    if action in {"summarise", "reconstruct-evidence", "classify"}:
        return summarise_structural_diagnosis(
            root=root, evidence_dir=evidence_dir
        )
    if action == "validate":
        return validate_completed_diagnosis(evidence_dir=evidence_dir)
    raise ValueError(f"Unsupported structural-diagnosis action: {action}.")
