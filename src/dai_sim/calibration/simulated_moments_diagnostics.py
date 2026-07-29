"""Monte Carlo precision and recovery-censoring diagnostics for confidence SMM.

This module is calibration-only.  It audits the completed Sobol search,
constructs an objective-blind numerical panel, evaluates a cumulative
replication ladder, and diagnoses recovery censoring without selecting a
parameter vector or changing the registered SMM objective.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file

from .event_simulation import (
    CALIBRATION_MANIFEST,
    ConditionalEventSimulationConfig,
    default_event_config,
    load_stage1_owners,
    prepare_event_path,
)
from .market import CONFIDENCE_EVIDENCE, CONFIDENCE_PANEL
from .simulated_moments import (
    DEFAULT_REGISTRY_IDS,
    SIMULATED_CORE_MOMENT_ORDER,
    StructuralParameters,
    array_sha256,
    sobol_candidates,
)
from . import simulated_moments_search as search


DIAGNOSTIC_SCHEMA = 1
REGISTRY_A = DEFAULT_REGISTRY_IDS[0]
PRIMARY_HORIZON = 792
HORIZON_ONE = 1_584
HORIZON_TWO = 2_376
PANEL_SIZE = 16
LADDER_REPLICATIONS = (32, 64, 128, 256)
REPLICATION_TRANCHES = ((0, 32), (32, 64), (64, 128), (128, 256))
AGREEMENT_TOLERANCE = 0.15
REQUIRED_REPLICATION_CAP = 8_192
SEARCH_ID = (
    "5f3dc71ae6bbcadff06aa639a774960511a8a0e8f1a0ed316ce418c32a55795d"
)
SEARCH_ROOT = (
    REPOSITORY_ROOT
    / "outputs/diagnostics/calibration/confidence/smm_search"
    / SEARCH_ID
)
DEFAULT_DIAGNOSTIC_ROOT = (
    REPOSITORY_ROOT
    / "outputs/diagnostics/calibration/confidence/monte_carlo_precision"
)
TRACKED_EVIDENCE_NAMES = (
    "monte_carlo_precision_specification.json",
    "monte_carlo_estimator_audit.json",
    "monte_carlo_candidate_panel.json",
    "monte_carlo_replication_ladder.csv",
    "recovery_censoring_diagnosis.json",
    "monte_carlo_precision_decision.json",
    "monte_carlo_precision_benchmark.json",
)

MEAN_MOMENTS = {
    "first_six_hour_burden_mean": "first_six_hour_burden",
    "maximum_downside_deviation_mean": "maximum_downside_deviation",
    "recovery_completion_hours_mean": "recovery_completion_hours",
    "failed_recovery_attempts_mean": "failed_recovery_attempts",
}
CONTRAST_MOMENTS = {
    "initial_gap_q4_q1_burden_contrast": (
        "initial_peg_gap",
        "first_six_hour_burden",
    ),
    "eth_recovery_q4_q1_duration_contrast": (
        "eth_recovery_24h",
        "recovery_completion_hours",
    ),
}
METRIC_COLUMNS = (
    "first_six_hour_burden",
    "maximum_downside_deviation",
    "recovery_completion_hours",
    "failed_recovery_attempts",
    "initial_peg_gap",
    "eth_recovery_24h",
    "numerical_bound_binding_share",
    "right_censored",
    "minimum_confidence",
    "maximum_unresolved_tab_dai",
    "maximum_active_bad_debt_dai",
)


@dataclass(frozen=True)
class MCSEEstimate:
    """Conditional Monte Carlo uncertainty for a fixed empirical catalogue."""

    point_estimate: float
    analytic_mcse: float
    replication_index_mcse: float
    diagnostic_mcse: float
    relative_disagreement: float
    agreement_pass: bool
    total_mc_variance: float
    event_variances: dict[str, float]
    event_variance_contributions: dict[str, float]
    dominant_event: str | None
    dominant_event_share: float
    effective_event_count: float
    event_count: int
    replication_count: int
    finite_sample_warning: bool


def _canonical_json_bytes(payload: Any) -> bytes:
    return search.canonical_json_bytes(payload)


def _atomic_bytes(path: Path, content: bytes) -> None:
    search._atomic_bytes(path, content)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_bytes(path, _canonical_json_bytes(payload))


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    search._atomic_csv(path, frame)


def _atomic_npz(path: Path, arrays: Mapping[str, np.ndarray]) -> None:
    search._atomic_npz(path, arrays)


def _load_npz(path: Path) -> dict[str, np.ndarray]:
    return search._load_npz(path)


def _payload_sha256(payload: Any) -> str:
    return search.payload_sha256(payload)


def _validate_metric_frame(
    records: pd.DataFrame,
    *,
    outcome: str,
    event_col: str,
    replication_col: str,
) -> pd.DataFrame:
    required = {event_col, replication_col, outcome}
    missing = required - set(records.columns)
    if missing:
        raise ValueError(f"Metric records are missing columns: {sorted(missing)}.")
    frame = records.loc[:, [event_col, replication_col, outcome]].copy()
    if frame.isna().any().any():
        raise ValueError("Metric records contain missing event, replication or outcome.")
    frame[outcome] = pd.to_numeric(frame[outcome], errors="raise")
    if not np.isfinite(frame[outcome].to_numpy(dtype=float)).all():
        raise ValueError("Metric outcomes must be finite.")
    if frame[[event_col, replication_col]].duplicated().any():
        raise ValueError("Each event-replication metric must be unique.")
    counts = frame.groupby(event_col, sort=True)[replication_col].nunique()
    if counts.empty or counts.nunique() != 1:
        raise ValueError("Every event must contain the same replication count.")
    expected = set(range(int(counts.iloc[0])))
    for event_id, group in frame.groupby(event_col, sort=True):
        observed = set(int(value) for value in group[replication_col])
        if observed != expected:
            raise ValueError(
                f"Event {event_id} does not contain replications 0..{len(expected)-1}."
            )
    return frame


def _effective_event_count(contributions: Mapping[str, float]) -> float:
    values = np.asarray(list(contributions.values()), dtype=float)
    total = float(values.sum())
    if total <= 0.0:
        return float(len(values))
    shares = values / total
    return float(1.0 / np.sum(shares**2))


def _finalise_mcse(
    *,
    point_estimate: float,
    analytic_variance: float,
    replication_values: Sequence[float],
    event_variances: Mapping[str, float],
    contributions: Mapping[str, float],
    event_count: int,
    replication_count: int,
) -> MCSEEstimate:
    analytic = math.sqrt(max(0.0, analytic_variance))
    index = (
        float(np.std(np.asarray(replication_values, dtype=float), ddof=1))
        / math.sqrt(replication_count)
        if replication_count > 1
        else math.nan
    )
    if not math.isfinite(index):
        raise ValueError("At least two replications are required for MCSE.")
    denominator = max(analytic, index)
    disagreement = abs(analytic - index) / denominator if denominator else 0.0
    dominant = (
        max(contributions, key=contributions.get) if contributions else None
    )
    dominant_share = (
        float(contributions[dominant] / analytic_variance)
        if dominant is not None and analytic_variance > 0.0
        else 0.0
    )
    return MCSEEstimate(
        point_estimate=float(point_estimate),
        analytic_mcse=float(analytic),
        replication_index_mcse=float(index),
        diagnostic_mcse=float(max(analytic, index)),
        relative_disagreement=float(disagreement),
        agreement_pass=bool(disagreement <= AGREEMENT_TOLERANCE),
        total_mc_variance=float(analytic_variance),
        event_variances={key: float(value) for key, value in event_variances.items()},
        event_variance_contributions={
            key: float(value) for key, value in contributions.items()
        },
        dominant_event=dominant,
        dominant_event_share=dominant_share,
        effective_event_count=_effective_event_count(contributions),
        event_count=int(event_count),
        replication_count=int(replication_count),
        finite_sample_warning=bool(replication_count < 16),
    )


def analytic_equal_event_mcse(
    records: pd.DataFrame,
    *,
    outcome: str,
    event_col: str = "event_id",
    replication_col: str = "replication",
) -> MCSEEstimate:
    """Estimate conditional MCSE without treating event heterogeneity as noise."""
    frame = _validate_metric_frame(
        records,
        outcome=outcome,
        event_col=event_col,
        replication_col=replication_col,
    )
    grouped = frame.groupby(event_col, sort=True)[outcome]
    event_means = grouped.mean()
    event_variances = grouped.var(ddof=1).fillna(0.0)
    event_count = len(event_means)
    replication_count = int(
        frame.groupby(event_col, sort=True)[replication_col].nunique().iloc[0]
    )
    contributions = {
        str(event_id): float(variance / replication_count / event_count**2)
        for event_id, variance in event_variances.items()
    }
    replication_values = (
        frame.groupby(replication_col, sort=True)[outcome].mean().tolist()
    )
    return _finalise_mcse(
        point_estimate=float(event_means.mean()),
        analytic_variance=float(sum(contributions.values())),
        replication_values=replication_values,
        event_variances={
            str(event_id): float(value)
            for event_id, value in event_variances.items()
        },
        contributions=contributions,
        event_count=event_count,
        replication_count=replication_count,
    )


def quartile_event_sets(
    records: pd.DataFrame,
    *,
    stratifier: str,
    event_col: str = "event_id",
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return deterministic Q1 and Q4 memberships for a fixed event catalogue."""
    if stratifier not in records:
        raise ValueError(f"Missing quartile stratifier: {stratifier}.")
    per_event = (
        records[[event_col, stratifier]]
        .drop_duplicates()
        .sort_values(event_col, kind="mergesort")
        .reset_index(drop=True)
    )
    if per_event[event_col].duplicated().any():
        raise ValueError("A fixed event has multiple stratifier values.")
    quartiles = pd.qcut(per_event[stratifier], 4, labels=False)
    low = tuple(
        str(value)
        for value in per_event.loc[quartiles.eq(0), event_col].tolist()
    )
    high = tuple(
        str(value)
        for value in per_event.loc[quartiles.eq(3), event_col].tolist()
    )
    if not low or not high:
        raise ValueError("Q1 and Q4 must both contain events.")
    return low, high


def analytic_contrast_mcse(
    records: pd.DataFrame,
    *,
    outcome: str,
    stratifier: str,
    event_col: str = "event_id",
    replication_col: str = "replication",
) -> MCSEEstimate:
    """Estimate conditional Q4-minus-Q1 MCSE with within-event variances."""
    frame = _validate_metric_frame(
        records,
        outcome=outcome,
        event_col=event_col,
        replication_col=replication_col,
    )
    frame[stratifier] = records.set_index(
        [event_col, replication_col]
    ).loc[
        pd.MultiIndex.from_frame(frame[[event_col, replication_col]]),
        stratifier,
    ].to_numpy()
    low, high = quartile_event_sets(frame, stratifier=stratifier, event_col=event_col)
    grouped = frame.groupby(event_col, sort=True)[outcome]
    means = grouped.mean()
    variances = grouped.var(ddof=1).fillna(0.0)
    replication_count = int(
        frame.groupby(event_col, sort=True)[replication_col].nunique().iloc[0]
    )
    contributions: dict[str, float] = {}
    for event_id in low:
        contributions[event_id] = float(
            variances.loc[event_id] / replication_count / len(low) ** 2
        )
    for event_id in high:
        contributions[event_id] = float(
            variances.loc[event_id] / replication_count / len(high) ** 2
        )
    replication_values = []
    for _, replication_frame in frame.groupby(replication_col, sort=True):
        values = replication_frame.set_index(event_col)[outcome]
        replication_values.append(
            float(values.loc[list(high)].mean() - values.loc[list(low)].mean())
        )
    return _finalise_mcse(
        point_estimate=float(means.loc[list(high)].mean() - means.loc[list(low)].mean()),
        analytic_variance=float(sum(contributions.values())),
        replication_values=replication_values,
        event_variances={
            str(event_id): float(value)
            for event_id, value in variances.loc[list(low) + list(high)].items()
        },
        contributions=contributions,
        event_count=len(low) + len(high),
        replication_count=replication_count,
    )


def fixed_moment_mcse(
    records: pd.DataFrame,
    moment: str,
    *,
    ordinary_preservation: Mapping[str, float] | None = None,
) -> MCSEEstimate:
    """Apply the fixed moment ownership to one event-replication table."""
    if moment in {"ordinary_below_mean", "ordinary_above_mean"}:
        if ordinary_preservation is None or moment not in ordinary_preservation:
            raise ValueError("Ordinary preservation values are required.")
        replication_count = int(records["replication"].nunique())
        event_count = int(records["event_id"].nunique())
        return MCSEEstimate(
            point_estimate=float(ordinary_preservation[moment]),
            analytic_mcse=0.0,
            replication_index_mcse=0.0,
            diagnostic_mcse=0.0,
            relative_disagreement=0.0,
            agreement_pass=True,
            total_mc_variance=0.0,
            event_variances={},
            event_variance_contributions={},
            dominant_event=None,
            dominant_event_share=0.0,
            effective_event_count=float(event_count),
            event_count=event_count,
            replication_count=replication_count,
            finite_sample_warning=bool(replication_count < 16),
        )
    if moment in MEAN_MOMENTS:
        return analytic_equal_event_mcse(records, outcome=MEAN_MOMENTS[moment])
    if moment in CONTRAST_MOMENTS:
        stratifier, outcome = CONTRAST_MOMENTS[moment]
        return analytic_contrast_mcse(
            records, outcome=outcome, stratifier=stratifier
        )
    raise ValueError(f"Unknown fixed core moment: {moment}.")


def convergence_slope(
    replications: Sequence[int],
    mcse_values: Sequence[float],
) -> tuple[float, str]:
    """Fit log(MCSE) on log(R) and apply fixed convergence labels."""
    r = np.asarray(replications, dtype=float)
    values = np.asarray(mcse_values, dtype=float)
    if len(r) != len(values) or len(r) < 2:
        raise ValueError("Convergence requires aligned replication levels.")
    if np.any(r <= 0.0) or np.any(values < 0.0):
        raise ValueError("Replication levels and MCSE values cannot be negative.")
    if np.all(values == 0.0):
        return math.nan, "faster_than_expected_or_floor_effect"
    positive = values > 0.0
    if np.count_nonzero(positive) < 2:
        return math.nan, "faster_than_expected_or_floor_effect"
    slope = float(np.polyfit(np.log(r[positive]), np.log(values[positive]), 1)[0])
    if -0.65 <= slope <= -0.35:
        label = "regular_convergence"
    elif slope > -0.35:
        label = "slow_or_unstable_convergence"
    else:
        label = "faster_than_expected_or_floor_effect"
    return slope, label


def next_power_of_two(value: float) -> int:
    if not math.isfinite(value) or value < 0.0:
        raise ValueError("Required replication projection cannot be negative.")
    if value <= 1.0:
        return 1
    return 1 << math.ceil(math.log2(value))


def projected_required_replications(
    *,
    replication_count: int,
    mcse: float,
    threshold: float,
    convergence_classification: str,
) -> int | str | None:
    """Project and cap required replications only under regular convergence."""
    if convergence_classification != "regular_convergence":
        return None
    projected = next_power_of_two(
        replication_count * (mcse / threshold) ** 2
    )
    return f">{REQUIRED_REPLICATION_CAP}" if projected > REQUIRED_REPLICATION_CAP else projected


def objective_blind_candidate_panel(
    *,
    size: int = PANEL_SIZE,
) -> dict[str, Any]:
    """Select a deterministic space-filling panel without fit outcomes."""
    transformed, structural = sobol_candidates()
    if size != PANEL_SIZE:
        raise ValueError("The precision diagnosis panel must contain 16 candidates.")
    selected = [0]
    while len(selected) < size:
        remaining = [index for index in range(len(transformed)) if index not in selected]
        distances = {
            index: min(
                float(np.linalg.norm(transformed[index] - transformed[prior]))
                for prior in selected
            )
            for index in remaining
        }
        maximum = max(distances.values())
        selected.append(
            min(
                index
                for index, value in distances.items()
                if math.isclose(value, maximum, rel_tol=0.0, abs_tol=1e-15)
            )
        )
    pairwise = [
        float(np.linalg.norm(transformed[left] - transformed[right]))
        for position, left in enumerate(selected)
        for right in selected[position + 1 :]
    ]
    rows = [
        {
            "candidate_index": int(index),
            "transformed_vector": [
                float(value) for value in transformed[index]
            ],
            "structural_vector": asdict(structural[index]),
        }
        for index in selected
    ]
    panel_checksum = _payload_sha256(
        {
            "candidate_indices": selected,
            "transformed_array_sha256": array_sha256(transformed[selected]),
            "selection_algorithm": "deterministic_farthest_point",
        }
    )
    return {
        "schema_version": DIAGNOSTIC_SCHEMA,
        "purpose": "objective-blind Monte Carlo diagnosis; not a shortlist",
        "selection_algorithm": (
            "start at candidate 0; maximise minimum Euclidean distance in "
            "transformed Sobol space; lower-index tie-break"
        ),
        "candidate_count": size,
        "candidate_indices": selected,
        "candidates": rows,
        "pairwise_distance_summary": {
            "minimum": min(pairwise),
            "median": float(np.median(pairwise)),
            "maximum": max(pairwise),
        },
        "panel_checksum": panel_checksum,
        "objective_fields_present": False,
        "candidate_selection_performed": False,
        "runtime_adopted": False,
    }


def censoring_imbalance(low_rate: float, high_rate: float) -> dict[str, Any]:
    difference = abs(float(high_rate) - float(low_rate))
    lower = min(float(low_rate), float(high_rate))
    upper = max(float(low_rate), float(high_rate))
    ratio = upper / lower if lower > 0.0 else (math.inf if upper > 0.0 else 1.0)
    return {
        "absolute_difference": difference,
        "rate_ratio": ratio if math.isfinite(ratio) else "infinite",
        "material": bool(difference > 0.10 or (lower > 0.0 and ratio > 2.0)),
    }


def classify_recovery_censoring(
    *,
    censored_at_h0: int,
    recovered_by_h1: int,
    recovered_by_h2: int,
) -> str:
    if censored_at_h0 <= 0:
        return "mainly_administrative_censoring"
    h1_share = recovered_by_h1 / censored_at_h0
    h2_share = recovered_by_h2 / censored_at_h0
    if h1_share > 0.50:
        return "mainly_administrative_censoring"
    if 0.10 <= h1_share <= 0.50 or h2_share >= 0.10:
        return "mixed_administrative_and_structural_censoring"
    return "predominantly_structural_non_recovery"


def paired_difference_precision(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    outcome: str,
) -> dict[str, float]:
    """Compare paired CRN precision with an unpaired variance calculation."""
    keys = ["event_id", "replication"]
    merged = left[keys + [outcome]].merge(
        right[keys + [outcome]],
        on=keys,
        how="outer",
        suffixes=("_left", "_right"),
        validate="one_to_one",
        indicator=True,
    )
    if not merged["_merge"].eq("both").all():
        raise ValueError("Candidate difference inputs do not share identical streams.")
    per_replication = merged.assign(
        difference=merged[f"{outcome}_right"] - merged[f"{outcome}_left"]
    ).groupby("replication", sort=True)["difference"].mean()
    paired = float(per_replication.std(ddof=1) / math.sqrt(len(per_replication)))
    left_values = (
        left.groupby("replication", sort=True)[outcome].mean().to_numpy(dtype=float)
    )
    right_values = (
        right.groupby("replication", sort=True)[outcome].mean().to_numpy(dtype=float)
    )
    unpaired = float(
        math.sqrt(
            np.var(left_values, ddof=1) / len(left_values)
            + np.var(right_values, ddof=1) / len(right_values)
        )
    )
    return {
        "paired_difference_mcse": paired,
        "unpaired_mcse": unpaired,
        "common_random_numbers_used": True,
        "absolute_mcse_gate_replaced": False,
    }


def _candidate_recovery_contrast(
    records: pd.DataFrame,
    *,
    low_events: Sequence[str],
    high_events: Sequence[str],
) -> pd.DataFrame:
    """Return one registered recovery contrast per replication."""
    low = (
        records.loc[records["event_id"].isin(low_events)]
        .groupby("replication", sort=True)["recovery_completion_hours"]
        .mean()
    )
    high = (
        records.loc[records["event_id"].isin(high_events)]
        .groupby("replication", sort=True)["recovery_completion_hours"]
        .mean()
    )
    if not low.index.equals(high.index):
        raise ValueError("Recovery-contrast strata do not share replications.")
    return pd.DataFrame(
        {
            "event_id": "eth_recovery_q4_q1_duration_contrast",
            "replication": low.index.to_numpy(dtype=int),
            "recovery_contrast": high.to_numpy(dtype=float)
            - low.to_numpy(dtype=float),
        }
    )


def summarise_pairing_and_interactions(
    run_dir: Path,
) -> dict[str, Any]:
    """Diagnose CRN differences and recovery-gate associations descriptively."""
    run_dir = Path(run_dir)
    frame = _load_ladder_frame(run_dir)
    context = json.loads((run_dir / "run_context.json").read_text())
    source_context = json.loads((SEARCH_ROOT / "run_context.json").read_text())
    panel = context["design"]["candidate_panel"]
    panel_indices = panel["candidate_indices"]
    catalogue = pd.read_csv(CONFIDENCE_EVIDENCE / "event_catalogue.csv")
    calibration = catalogue.loc[catalogue["partition"].eq("calibration")]
    eth_low, eth_high = quartile_event_sets(
        calibration,
        stratifier="eth_recovery_24h",
    )
    selected = frame.loc[frame["replication"].lt(256)].copy()

    paired_rows = []
    for pair_index in range(0, len(panel_indices), 2):
        left_index = int(panel_indices[pair_index])
        right_index = int(panel_indices[pair_index + 1])
        left = _candidate_recovery_contrast(
            selected.loc[selected["candidate_index"].eq(left_index)],
            low_events=eth_low,
            high_events=eth_high,
        )
        right = _candidate_recovery_contrast(
            selected.loc[selected["candidate_index"].eq(right_index)],
            low_events=eth_low,
            high_events=eth_high,
        )
        result = paired_difference_precision(
            left,
            right,
            outcome="recovery_contrast",
        )
        paired_rows.append(
            {
                "pair_index": pair_index // 2,
                "left_panel_position": pair_index,
                "right_panel_position": pair_index + 1,
                "left_candidate_index": left_index,
                "right_candidate_index": right_index,
                "replication_count": 256,
                "moment": "eth_recovery_q4_q1_duration_contrast",
                **result,
                "pair_ranked": False,
            }
        )
    paired = pd.DataFrame(paired_rows)

    floor_by_candidate = {
        int(row["candidate_index"]): float(
            row["structural_vector"]["confidence_floor"]
        )
        for row in panel["candidates"]
    }
    interaction_rows = []
    ordinary = source_context["ordinary_preservation"]
    for candidate_index in panel_indices:
        candidate = selected.loc[
            selected["candidate_index"].eq(candidate_index)
        ]
        estimate = fixed_moment_mcse(
            candidate,
            "eth_recovery_q4_q1_duration_contrast",
            ordinary_preservation=ordinary,
        )
        confidence_floor = floor_by_candidate[int(candidate_index)]
        interaction_rows.append(
            {
                "candidate_index": int(candidate_index),
                "diagnostic_mcse": estimate.diagnostic_mcse,
                "price_bound_binding_share": float(
                    candidate["numerical_bound_binding_share"].mean()
                ),
                "confidence_floor": confidence_floor,
                "confidence_floor_binding_share": float(
                    (
                        candidate["minimum_confidence"]
                        <= confidence_floor + 1e-12
                    ).mean()
                ),
                "right_censoring_share": float(
                    candidate["right_censored"].mean()
                ),
                "unresolved_backlog_positive_share": float(
                    (candidate["maximum_unresolved_tab_dai"] > 0.0).mean()
                ),
                "mean_maximum_unresolved_tab_dai": float(
                    candidate["maximum_unresolved_tab_dai"].mean()
                ),
                "active_bad_debt_positive_share": float(
                    (candidate["maximum_active_bad_debt_dai"] > 0.0).mean()
                ),
                "mean_maximum_active_bad_debt_dai": float(
                    candidate["maximum_active_bad_debt_dai"].mean()
                ),
            }
        )
    interactions = pd.DataFrame(interaction_rows)
    diagnostic_columns = [
        name
        for name in interactions.columns
        if name not in {"candidate_index", "diagnostic_mcse", "confidence_floor"}
    ]
    correlations = {
        name: float(
            interactions["diagnostic_mcse"].corr(interactions[name])
        )
        for name in diagnostic_columns
    }
    grouped = {}
    cross_tabs = {}
    for name in diagnostic_columns:
        median = float(interactions[name].median())
        label = np.where(interactions[name] > median, "above_median", "at_or_below_median")
        grouped[name] = {
            group_name: {
                "candidate_count": int(mask.sum()),
                "diagnostic_mcse_mean": float(
                    interactions.loc[mask, "diagnostic_mcse"].mean()
                ),
                "diagnostic_mcse_median": float(
                    interactions.loc[mask, "diagnostic_mcse"].median()
                ),
            }
            for group_name in ("at_or_below_median", "above_median")
            if (mask := label == group_name).any()
        }
        cross_tabs[name] = {
            "median_split_value": median,
            "at_or_below_median_candidates": [
                int(value)
                for value in interactions.loc[
                    label == "at_or_below_median", "candidate_index"
                ]
            ],
            "above_median_candidates": [
                int(value)
                for value in interactions.loc[
                    label == "above_median", "candidate_index"
                ]
            ],
        }
    _atomic_csv(run_dir / "paired_candidate_differences.csv", paired)
    _atomic_csv(run_dir / "recovery_gate_interactions.csv", interactions)
    _atomic_json(
        run_dir / "recovery_gate_interaction_summary.json",
        {
            "correlations": correlations,
            "grouped_summaries": grouped,
            "deterministic_cross_tabs": cross_tabs,
        },
    )
    return {
        "paired_candidate_differences": paired.to_dict(orient="records"),
        "paired_result_count": len(paired),
        "common_random_numbers_may_improve_comparative_precision": True,
        "absolute_mcse_gate_replaced": False,
        "candidate_pairs_ranked": False,
        "numerical_bound_and_gate_interactions": {
            "candidate_count": len(interactions),
            "correlations": correlations,
            "grouped_summaries": grouped,
            "deterministic_cross_tabs": cross_tabs,
            "causal_interpretation": False,
            "parameter_bounds_changed": False,
        },
    }


def _search_metric_frame(run_dir: Path, candidate_index: int) -> pd.DataFrame:
    context = json.loads((run_dir / "run_context.json").read_text(encoding="utf-8"))
    event_ids = tuple(sorted(context["event_ids"]))
    arrays = _load_npz(
        run_dir / "candidates" / f"candidate_{candidate_index:03d}_metrics.npz"
    )
    frame = pd.DataFrame(
        {
            "event_id": [event_ids[int(value)] for value in arrays["event_index"]],
            **{name: arrays[name] for name in arrays},
        }
    )
    return frame


def audit_completed_search(
    run_dir: Path = SEARCH_ROOT,
    *,
    write_path: Path | None = None,
) -> dict[str, Any]:
    """Audit the committed replication-index estimator against analytic MCSE."""
    run_dir = Path(run_dir)
    validation = search.validate_completed_search(
        run_dir, evidence_dir=CONFIDENCE_EVIDENCE
    )
    if validation["search_id"] != SEARCH_ID:
        raise ValueError("The authoritative completed search ID differs.")
    context = json.loads((run_dir / "run_context.json").read_text(encoding="utf-8"))
    threshold_by_moment = {
        name: 0.10 * float(context["objective"]["scales"][name])
        for name in SIMULATED_CORE_MOMENT_ORDER
    }
    ordinary = context["ordinary_preservation"]
    audits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    existing_reproduced = True
    for candidate_index in range(256):
        payload = json.loads(
            (
                run_dir
                / "candidates"
                / f"candidate_{candidate_index:03d}.json"
            ).read_text(encoding="utf-8")
        )
        records = _search_metric_frame(run_dir, candidate_index)
        for moment in SIMULATED_CORE_MOMENT_ORDER:
            estimate = fixed_moment_mcse(
                records, moment, ordinary_preservation=ordinary
            )
            existing = float(payload["mcse_by_moment"][moment])
            if not math.isclose(
                existing,
                estimate.replication_index_mcse,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                existing_reproduced = False
            audits[moment].append(
                {
                    "candidate_index": candidate_index,
                    "existing_mcse": existing,
                    "analytic_mcse": estimate.analytic_mcse,
                    "replication_index_mcse": estimate.replication_index_mcse,
                    "diagnostic_mcse": estimate.diagnostic_mcse,
                    "relative_disagreement": estimate.relative_disagreement,
                    "agreement_pass": estimate.agreement_pass,
                    "existing_pass": existing <= threshold_by_moment[moment],
                    "audited_pass": estimate.diagnostic_mcse
                    <= threshold_by_moment[moment],
                }
            )
    if not existing_reproduced:
        classification = "incorrect_replication_aggregation"
    else:
        systematic = np.mean(
            [
                not row["agreement_pass"]
                for rows in audits.values()
                for row in rows
                if row["diagnostic_mcse"] > 0.0
            ]
        ) > 0.25
        classification = (
            "incorrect_replication_aggregation"
            if systematic
            else "correct_hierarchical_mcse"
        )
    moment_summary = {}
    for moment, rows in audits.items():
        moment_summary[moment] = {
            "existing_formula": (
                "sd of equal-event replication-index moment divided by sqrt(R)"
            ),
            "audited_formula": (
                "within-event analytic conditional MCSE cross-checked against "
                "replication-index MCSE; larger used for diagnostic gate"
            ),
            "threshold": threshold_by_moment[moment],
            "existing_mcse_distribution": _distribution(
                [row["existing_mcse"] for row in rows]
            ),
            "analytic_mcse_distribution": _distribution(
                [row["analytic_mcse"] for row in rows]
            ),
            "replication_index_mcse_distribution": _distribution(
                [row["replication_index_mcse"] for row in rows]
            ),
            "existing_pass_count": sum(row["existing_pass"] for row in rows),
            "audited_pass_count": sum(row["audited_pass"] for row in rows),
            "agreement_failure_count": sum(
                not row["agreement_pass"] for row in rows
            ),
        }
    audited_all_pass = []
    for index in range(256):
        audited_all_pass.append(
            all(
                moment_summary[moment]["threshold"]
                >= audits[moment][index]["diagnostic_mcse"]
                for moment in SIMULATED_CORE_MOMENT_ORDER
            )
        )
    result = {
        "schema_version": DIAGNOSTIC_SCHEMA,
        "search_id": SEARCH_ID,
        "committed_failure_reproduction": {
            "candidate_count": 256,
            "structural_valid": sum(
                json.loads(
                    (
                        run_dir / "candidates" / f"candidate_{index:03d}.json"
                    ).read_text()
                )["structural_validity"]
                for index in range(256)
            ),
            "objective_valid": sum(
                json.loads(
                    (
                        run_dir / "candidates" / f"candidate_{index:03d}.json"
                    ).read_text()
                )["objective_validity"]
                for index in range(256)
            ),
            "numerical_bound_valid": sum(
                json.loads(
                    (
                        run_dir / "candidates" / f"candidate_{index:03d}.json"
                    ).read_text()
                )["numerical_bound_pass"]
                for index in range(256)
            ),
            "mcse_valid": sum(
                json.loads(
                    (
                        run_dir / "candidates" / f"candidate_{index:03d}.json"
                    ).read_text()
                )["mcse_pass"]
                for index in range(256)
            ),
            "next_stage_eligible": int(validation["top16_count"]),
        },
        "existing_estimator_classification": classification,
        "estimand": (
            "simulation uncertainty conditional on the fixed empirical event "
            "catalogue and fixed quartile membership"
        ),
        "between_event_heterogeneity_counted_as_mc_noise": False,
        "existing_replication_index_values_reproduced": existing_reproduced,
        "agreement_tolerance": AGREEMENT_TOLERANCE,
        "core_moments": moment_summary,
        "search_eligibility_implication": {
            "committed_mcse_valid_candidates": 0,
            "audited_mcse_valid_candidates": int(sum(audited_all_pass)),
            "eligibility_result_changes": bool(any(audited_all_pass)),
        },
        "correction_required": classification
        != "correct_hierarchical_mcse",
        "old_evidence_preserved": True,
        "candidate_selected": False,
        "runtime_adopted": False,
    }
    if write_path is not None:
        _atomic_json(Path(write_path), result)
    return result


def _distribution(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    return {
        "minimum": float(np.min(array)),
        "q25": float(np.quantile(array, 0.25)),
        "median": float(np.median(array)),
        "q75": float(np.quantile(array, 0.75)),
        "q90": float(np.quantile(array, 0.90)),
        "q95": float(np.quantile(array, 0.95)),
        "maximum": float(np.max(array)),
    }


def build_diagnostic_identity(
    *,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> tuple[str, dict[str, Any]]:
    """Hash the fixed diagnosis boundary without host-dependent fields."""
    identity, design = search.load_search_identity(evidence_dir)
    catalogue = pd.read_csv(Path(evidence_dir) / "event_catalogue.csv")
    calibration = catalogue.loc[catalogue["partition"].eq("calibration")].copy()
    event_ids = tuple(sorted(calibration["event_id"].astype(str)))
    if len(event_ids) != 74 or len(set(event_ids)) != 74:
        raise ValueError("The diagnosis requires exactly 74 calibration events.")
    panel = objective_blind_candidate_panel()
    payload = {
        "schema_version": DIAGNOSTIC_SCHEMA,
        "source_search_id": identity.search_id,
        "all_event_ids": event_ids,
        "all_event_ids_sha256": _payload_sha256(event_ids),
        "candidate_panel_checksum": panel["panel_checksum"],
        "replication_ladder": LADDER_REPLICATIONS,
        "registry_id": REGISTRY_A,
        "primary_horizon": PRIMARY_HORIZON,
        "extended_horizons": (HORIZON_ONE, HORIZON_TWO),
        "scientific_inputs": identity.inputs,
    }
    return _payload_sha256(payload), {
        **payload,
        "source_search_event_ids": tuple(sorted(design["event_ids"])),
        "candidate_panel": panel,
    }


def diagnostic_directory(
    root: Path = DEFAULT_DIAGNOSTIC_ROOT,
    *,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> Path:
    identity, _ = build_diagnostic_identity(evidence_dir=evidence_dir)
    return Path(root).resolve() / identity


_CACHE_CONTEXT: dict[str, Any] | None = None


def _cache_worker_initialise(
    run_dir_text: str,
    panel_path_text: str,
    evidence_dir_text: str,
    horizon: int,
) -> None:
    global _CACHE_CONTEXT
    search._thread_cap()
    run_dir = Path(run_dir_text)
    panel, events, stage1 = load_stage1_owners(
        Path(panel_path_text), Path(evidence_dir_text)
    )
    base_config = default_event_config(events)
    config = replace(base_config, maximum_event_horizon_hours=int(horizon))
    config.validate()
    selected = events.loc[events["partition"].eq("calibration")].copy()
    rows = {
        str(row["event_id"]): row
        for _, row in selected.iterrows()
    }
    paths = {
        event_id: prepare_event_path(
            panel=panel, event_row=row, config=config
        )
        for event_id, row in rows.items()
    }
    diagnosis_id, design = build_diagnostic_identity(
        evidence_dir=Path(evidence_dir_text)
    )
    source_identity, _ = search.load_search_identity(Path(evidence_dir_text))
    identity = search.SearchIdentity(
        search_id=f"{diagnosis_id}__h{horizon}",
        inputs=source_identity.inputs,
        event_subset_sha256=design["all_event_ids_sha256"],
        candidate_sha256=design["candidate_panel_checksum"],
        event_simulation_schema=search.EVENT_SIMULATION_SCHEMA,
        search_execution_schema=DIAGNOSTIC_SCHEMA,
        replication_count=256 if horizon == PRIMARY_HORIZON else 64,
        registry_id=REGISTRY_A,
        event_count=74,
        candidate_count=PANEL_SIZE if horizon == PRIMARY_HORIZON else 8,
    )
    profile_path = run_dir / ".worker_profiles" / f"empirical_{os.getpid()}.yaml"
    from dai_sim.inputs.vaults import DEFAULT_TRANCHE_B_CONFIG_PATH

    _atomic_bytes(profile_path, DEFAULT_TRANCHE_B_CONFIG_PATH.read_bytes())
    search._ACTIVE_CACHE_CONFIG = config
    _CACHE_CONTEXT = {
        "run_dir": run_dir,
        "identity": identity,
        "rows": rows,
        "paths": paths,
        "stage1": stage1,
        "config": config,
        "profile_path": profile_path,
        "horizon": horizon,
    }


def _cache_entry_from_files(
    *,
    event_id: str,
    replication: int,
    metadata_path: Path,
    arrays_path: Path,
    source: str,
) -> dict[str, Any]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return {
        "event_id": event_id,
        "replication": replication,
        "registry_id": metadata["registry_id"],
        "metadata_filename": metadata_path.name,
        "arrays_filename": arrays_path.name,
        "metadata_size_bytes": metadata_path.stat().st_size,
        "arrays_size_bytes": arrays_path.stat().st_size,
        "metadata_sha256": sha256_file(metadata_path),
        "arrays_sha256": sha256_file(arrays_path),
        "state_checksum": metadata["initial_state_checksum"],
        "residual_checksum": metadata.get("residual_checksum", ""),
        "schema_version": search.CACHE_SCHEMA,
        "source": source,
    }


def _build_event_packages(task: tuple[str, int, int]) -> dict[str, Any]:
    if _CACHE_CONTEXT is None:
        raise RuntimeError("Diagnostic cache worker is not initialised.")
    event_id, start, end = task
    context = _CACHE_CONTEXT
    cache_dir = context["run_dir"] / (
        "cache_primary" if context["horizon"] == PRIMARY_HORIZON else "cache_extended"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    built = 0
    reused = 0
    for replication in range(start, end):
        stem = search._package_stem(event_id, replication)
        metadata_path = cache_dir / f"{stem}.json"
        arrays_path = cache_dir / f"{stem}.npz"
        if metadata_path.is_file() and arrays_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if (
                sha256_file(arrays_path) != metadata["arrays_sha256"]
                or metadata["event_id"] != event_id
                or int(metadata["replication"]) != replication
            ):
                raise ValueError(
                    f"Incompatible cached package: {event_id} r{replication}."
                )
            reused += 1
        else:
            entry = search._build_package(
                identity=context["identity"],
                cache_dir=cache_dir,
                event_row=context["rows"][event_id],
                path=context["paths"][event_id],
                replication=replication,
                stage1=context["stage1"],
                config=context["config"],
                profile_path=context["profile_path"],
            )
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["residual_checksum"] = entry["residual_checksum"]
            _atomic_json(metadata_path, metadata)
            built += 1
        entries.append(
            _cache_entry_from_files(
                event_id=event_id,
                replication=replication,
                metadata_path=metadata_path,
                arrays_path=arrays_path,
                source="diagnostic_cache",
            )
        )
    return {
        "event_id": event_id,
        "start": start,
        "end": end,
        "built": built,
        "reused": reused,
        "entries": entries,
    }


def prepare_diagnostic_cache(
    *,
    run_dir: Path,
    panel_path: Path = CONFIDENCE_PANEL,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    workers: int = 4,
    horizon: int = PRIMARY_HORIZON,
) -> dict[str, Any]:
    """Build or resume the fixed all-event candidate-invariant cache."""
    if workers < 1 or workers > 6:
        raise ValueError("Diagnostic cache workers must be between one and six.")
    if horizon not in {PRIMARY_HORIZON, HORIZON_TWO}:
        raise ValueError("Only the registered primary or H2 cache is allowed.")
    replication_count = 256 if horizon == PRIMARY_HORIZON else 64
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    diagnosis_id, design = build_diagnostic_identity(evidence_dir=evidence_dir)
    context_payload = {
        "diagnosis_id": diagnosis_id,
        "design": design,
        "primary_horizon": PRIMARY_HORIZON,
        "extended_horizons": [HORIZON_ONE, HORIZON_TWO],
        "runtime_adopted": False,
    }
    _atomic_json(run_dir / "run_context.json", context_payload)
    started = time.perf_counter()
    tasks = [
        (event_id, 0, replication_count)
        for event_id in design["all_event_ids"]
    ]
    process_context = mp.get_context("spawn")
    profiles = run_dir / ".worker_profiles"
    try:
        if workers == 1:
            _cache_worker_initialise(
                str(run_dir), str(panel_path), str(evidence_dir), horizon
            )
            results = [_build_event_packages(task) for task in tasks]
        else:
            with process_context.Pool(
                processes=workers,
                initializer=_cache_worker_initialise,
                initargs=(
                    str(run_dir),
                    str(Path(panel_path).resolve()),
                    str(Path(evidence_dir).resolve()),
                    horizon,
                ),
            ) as pool:
                results = list(
                    pool.imap_unordered(_build_event_packages, tasks, chunksize=1)
                )
    finally:
        if profiles.exists():
            shutil.rmtree(profiles)
    entries = sorted(
        [entry for result in results for entry in result["entries"]],
        key=lambda item: (item["event_id"], item["replication"]),
    )
    expected = 74 * replication_count
    if len(entries) != expected:
        raise ValueError(f"Diagnostic cache contains {len(entries)} of {expected} packages.")
    manifest = {
        "schema_version": DIAGNOSTIC_SCHEMA,
        "diagnosis_id": diagnosis_id,
        "horizon": horizon,
        "event_count": 74,
        "replication_count": replication_count,
        "package_count": len(entries),
        "registry_id": REGISTRY_A,
        "packages": entries,
        "cache_root_sha256": search._cache_root(entries),
    }
    suffix = "primary" if horizon == PRIMARY_HORIZON else "extended"
    _atomic_json(run_dir / f"cache_{suffix}_manifest.json", manifest)
    return {
        "diagnosis_id": diagnosis_id,
        "horizon": horizon,
        "package_count": len(entries),
        "built": sum(result["built"] for result in results),
        "reused": sum(result["reused"] for result in results),
        "cache_root_sha256": manifest["cache_root_sha256"],
        "aggregate_bytes": sum(
            entry["metadata_size_bytes"] + entry["arrays_size_bytes"]
            for entry in entries
        ),
        "wall_seconds": time.perf_counter() - started,
        "workers": workers,
        "status": "passed",
    }


def validate_diagnostic_cache(
    run_dir: Path,
    *,
    horizon: int = PRIMARY_HORIZON,
) -> dict[str, Any]:
    suffix = "primary" if horizon == PRIMARY_HORIZON else "extended"
    manifest_path = Path(run_dir) / f"cache_{suffix}_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_replications = 256 if horizon == PRIMARY_HORIZON else 64
    expected = 74 * expected_replications
    if (
        manifest["horizon"] != horizon
        or manifest["package_count"] != expected
        or manifest["registry_id"] != REGISTRY_A
    ):
        raise ValueError("Diagnostic cache manifest does not match the fixed design.")
    cache_dir = Path(run_dir) / f"cache_{suffix}"
    identities = []
    invalid = []
    for entry in manifest["packages"]:
        identities.append((entry["event_id"], int(entry["replication"])))
        metadata_path = cache_dir / entry["metadata_filename"]
        arrays_path = cache_dir / entry["arrays_filename"]
        if (
            not metadata_path.is_file()
            or not arrays_path.is_file()
            or sha256_file(metadata_path) != entry["metadata_sha256"]
            or sha256_file(arrays_path) != entry["arrays_sha256"]
        ):
            invalid.append(identities[-1])
    if len(set(identities)) != expected or invalid:
        raise ValueError(
            f"Diagnostic cache identity/checksum failure: {invalid[:5]}."
        )
    root = search._cache_root(manifest["packages"])
    if root != manifest["cache_root_sha256"]:
        raise ValueError("Diagnostic cache root checksum differs.")
    return {
        "status": "passed",
        "horizon": horizon,
        "event_count": len({value[0] for value in identities}),
        "replication_count": len({value[1] for value in identities}),
        "package_count": len(identities),
        "duplicate_identities": len(identities) - len(set(identities)),
        "invalid_packages": len(invalid),
        "registry_b_packages": 0,
        "final_validation_events": 0,
        "cache_root_sha256": root,
    }


_LADDER_CONTEXT: dict[str, Any] | None = None


def _ladder_worker_initialise(run_dir_text: str) -> None:
    global _LADDER_CONTEXT
    search._thread_cap()
    run_dir = Path(run_dir_text)
    context = json.loads((run_dir / "run_context.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (run_dir / "cache_primary_manifest.json").read_text(encoding="utf-8")
    )
    transformed, structural = sobol_candidates()
    panel_indices = tuple(context["design"]["candidate_panel"]["candidate_indices"])
    source_context = json.loads(
        (SEARCH_ROOT / "run_context.json").read_text(encoding="utf-8")
    )
    config = ConditionalEventSimulationConfig(**source_context["config"])
    entry_map = {
        (entry["event_id"], int(entry["replication"])): entry
        for entry in manifest["packages"]
    }
    _LADDER_CONTEXT = {
        "run_dir": run_dir,
        "entries": entry_map,
        "config": config,
        "stage1": source_context["stage1"],
        "scaling": source_context["scaling"],
        "ordinary": source_context["ordinary_preservation"],
        "objective": source_context["objective"],
        "candidates": tuple(structural),
        "transformed": transformed,
        "panel_indices": panel_indices,
        "diagnosis_id": context["diagnosis_id"],
        "paths": {},
    }


def _checkpoint_path(run_dir: Path, event_id: str, start: int, end: int) -> Path:
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:16]
    return run_dir / "ladder" / f"{digest}__r{start:03d}_{end-1:03d}.npz"


def _load_cached_package(
    context: Mapping[str, Any],
    *,
    event_id: str,
    replication: int,
    suffix: str = "primary",
) -> search.CachedPackage:
    entry = context["entries"][(event_id, replication)]
    cache_dir = context["run_dir"] / f"cache_{suffix}"
    metadata = json.loads(
        (cache_dir / entry["metadata_filename"]).read_text(encoding="utf-8")
    )
    arrays = _load_npz(cache_dir / entry["arrays_filename"])
    path = context["paths"].get(event_id)
    package = search.CachedPackage(metadata=metadata, arrays=arrays, path=path)
    if path is None:
        path = search._path_from_package(package)
        context["paths"][event_id] = path
        package = search.CachedPackage(metadata=metadata, arrays=arrays, path=path)
    return package


def _ladder_event_tranche(task: tuple[str, int, int]) -> dict[str, Any]:
    if _LADDER_CONTEXT is None:
        raise RuntimeError("Replication-ladder worker is not initialised.")
    event_id, start, end = task
    context = _LADDER_CONTEXT
    output_path = _checkpoint_path(context["run_dir"], event_id, start, end)
    if output_path.is_file():
        arrays = _load_npz(output_path)
        if len(arrays["candidate_index"]) != PANEL_SIZE * (end - start):
            raise ValueError(f"Incomplete ladder checkpoint: {output_path}.")
        return {
            "event_id": event_id,
            "start": start,
            "end": end,
            "reused": True,
            "path": output_path.as_posix(),
            "sha256": sha256_file(output_path),
        }
    rows: dict[str, list[Any]] = defaultdict(list)
    worker_context = search.WorkerContext(
        run_dir=context["run_dir"],
        search_id=context["diagnosis_id"],
        event_ids=(event_id,),
        config=context["config"],
        stage1=context["stage1"],
        scaling=context["scaling"],
        ordinary_preservation=context["ordinary"],
        objective=context["objective"],
        candidates=context["candidates"],
        transformed=context["transformed"],
        packages={},
    )
    for replication in range(start, end):
        package = _load_cached_package(
            context, event_id=event_id, replication=replication
        )
        worker_context.packages[(event_id, replication)] = package
        for candidate_index in context["panel_indices"]:
            metrics, checksum, structural = search._evaluate_cached_event(
                worker_context,
                candidate=context["candidates"][candidate_index],
                event_id=event_id,
                replication=replication,
            )
            rows["candidate_index"].append(candidate_index)
            rows["replication"].append(replication)
            for name in METRIC_COLUMNS:
                rows[name].append(metrics[name])
            rows["result_checksum"].append(checksum)
            rows["structural_valid"].append(
                search.structural_event_flags_pass(structural)
            )
        worker_context.packages.clear()
    arrays = {
        "candidate_index": np.asarray(rows["candidate_index"], dtype="<i8"),
        "replication": np.asarray(rows["replication"], dtype="<i8"),
        "first_six_hour_burden": np.asarray(
            rows["first_six_hour_burden"], dtype="<f8"
        ),
        "maximum_downside_deviation": np.asarray(
            rows["maximum_downside_deviation"], dtype="<f8"
        ),
        "recovery_completion_hours": np.asarray(
            rows["recovery_completion_hours"], dtype="<i8"
        ),
        "failed_recovery_attempts": np.asarray(
            rows["failed_recovery_attempts"], dtype="<i8"
        ),
        "initial_peg_gap": np.asarray(rows["initial_peg_gap"], dtype="<f8"),
        "eth_recovery_24h": np.asarray(rows["eth_recovery_24h"], dtype="<f8"),
        "numerical_bound_binding_share": np.asarray(
            rows["numerical_bound_binding_share"], dtype="<f8"
        ),
        "right_censored": np.asarray(rows["right_censored"], dtype="?"),
        "minimum_confidence": np.asarray(rows["minimum_confidence"], dtype="<f8"),
        "maximum_unresolved_tab_dai": np.asarray(
            rows["maximum_unresolved_tab_dai"], dtype="<f8"
        ),
        "maximum_active_bad_debt_dai": np.asarray(
            rows["maximum_active_bad_debt_dai"], dtype="<f8"
        ),
        "result_checksum": np.asarray(rows["result_checksum"], dtype="<U64"),
        "structural_valid": np.asarray(rows["structural_valid"], dtype="?"),
    }
    _atomic_npz(output_path, arrays)
    return {
        "event_id": event_id,
        "start": start,
        "end": end,
        "reused": False,
        "path": output_path.as_posix(),
        "sha256": sha256_file(output_path),
    }


def run_replication_ladder(
    *,
    run_dir: Path,
    workers: int = 4,
    resume: bool = False,
) -> dict[str, Any]:
    """Evaluate all objective-blind candidates on fixed cumulative tranches."""
    if workers < 1 or workers > 6:
        raise ValueError("Ladder workers must be between one and six.")
    validate_diagnostic_cache(run_dir, horizon=PRIMARY_HORIZON)
    context = json.loads((Path(run_dir) / "run_context.json").read_text())
    tasks = [
        (event_id, start, end)
        for start, end in REPLICATION_TRANCHES
        for event_id in context["design"]["all_event_ids"]
    ]
    existing = [
        task for task in tasks if _checkpoint_path(Path(run_dir), *task).is_file()
    ]
    if existing and not resume:
        raise ValueError("Ladder checkpoints exist; use explicit resume.")
    started = time.perf_counter()
    process_context = mp.get_context("spawn")
    if workers == 1:
        _ladder_worker_initialise(str(run_dir))
        results = [_ladder_event_tranche(task) for task in tasks]
    else:
        with process_context.Pool(
            processes=workers,
            initializer=_ladder_worker_initialise,
            initargs=(str(Path(run_dir).resolve()),),
        ) as pool:
            results = list(
                pool.imap_unordered(_ladder_event_tranche, tasks, chunksize=1)
            )
    result = {
        "diagnosis_id": context["diagnosis_id"],
        "candidate_count": PANEL_SIZE,
        "event_count": 74,
        "maximum_replications": 256,
        "event_replication_runs": PANEL_SIZE * 74 * 256,
        "checkpoint_count": len(results),
        "reused_checkpoints": sum(item["reused"] for item in results),
        "new_checkpoints": sum(not item["reused"] for item in results),
        "workers": workers,
        "wall_seconds": time.perf_counter() - started,
        "candidate_failures": 0,
        "runtime_adopted": False,
    }
    history_path = Path(run_dir) / "ladder_history.json"
    history = (
        json.loads(history_path.read_text())
        if history_path.is_file()
        else {"operations": []}
    )
    history["operations"].append(result)
    _atomic_json(history_path, history)
    return result


def _load_ladder_frame(run_dir: Path) -> pd.DataFrame:
    context = json.loads((Path(run_dir) / "run_context.json").read_text())
    frames = []
    for event_id in context["design"]["all_event_ids"]:
        for start, end in REPLICATION_TRANCHES:
            path = _checkpoint_path(Path(run_dir), event_id, start, end)
            if not path.is_file():
                raise ValueError(f"Missing replication-ladder checkpoint: {path}.")
            arrays = _load_npz(path)
            frame = pd.DataFrame(arrays)
            frame.insert(0, "event_id", event_id)
            frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    expected = PANEL_SIZE * 74 * 256
    if len(combined) != expected:
        raise ValueError(f"Ladder has {len(combined)} of {expected} results.")
    if combined[["candidate_index", "event_id", "replication"]].duplicated().any():
        raise ValueError("Replication ladder contains duplicate results.")
    if not combined["structural_valid"].all():
        raise ValueError("A ladder event result failed structural validation.")
    return combined


def validate_search_prefix(run_dir: Path) -> dict[str, Any]:
    """Require exact first-32 metric identity for overlapping search events."""
    frame = _load_ladder_frame(run_dir)
    context = json.loads((Path(run_dir) / "run_context.json").read_text())
    source_context = json.loads((SEARCH_ROOT / "run_context.json").read_text())
    subset = set(source_context["event_ids"])
    panel = context["design"]["candidate_panel"]["candidate_indices"]
    checked = 0
    for candidate_index in panel:
        source = _search_metric_frame(SEARCH_ROOT, candidate_index)
        source = source.loc[source["event_id"].isin(subset)]
        observed = frame.loc[
            frame["candidate_index"].eq(candidate_index)
            & frame["event_id"].isin(subset)
            & frame["replication"].lt(32)
        ]
        keys = ["event_id", "replication"]
        merged = source.merge(
            observed, on=keys, suffixes=("_source", "_diagnostic"), validate="one_to_one"
        )
        if len(merged) != 32 * 32:
            raise ValueError("Search-prefix comparison is incomplete.")
        for name in (
            "first_six_hour_burden",
            "maximum_downside_deviation",
            "recovery_completion_hours",
            "failed_recovery_attempts",
            "initial_peg_gap",
            "eth_recovery_24h",
            "numerical_bound_binding_share",
            "right_censored",
        ):
            if not np.array_equal(
                merged[f"{name}_source"].to_numpy(),
                merged[f"{name}_diagnostic"].to_numpy(),
            ):
                raise ValueError(
                    f"First-32 diagnostic results differ for {candidate_index}:{name}."
                )
        checked += len(merged)
    return {
        "status": "passed",
        "candidate_count": len(panel),
        "overlapping_event_count": len(subset),
        "replication_count": 32,
        "event_replication_results_checked": checked,
        "exact_metric_equality": True,
    }


def _event_set_ids(
    design: Mapping[str, Any],
    event_set: str,
) -> tuple[str, ...]:
    if event_set == "search_32":
        return tuple(design["source_search_event_ids"])
    if event_set == "all_74":
        return tuple(design["all_event_ids"])
    raise ValueError(f"Unknown diagnostic event set: {event_set}.")


def summarise_replication_ladder(
    *,
    run_dir: Path,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build fixed per-moment ladder evidence without evaluating objectives."""
    frame = _load_ladder_frame(run_dir)
    context = json.loads((Path(run_dir) / "run_context.json").read_text())
    source_context = json.loads((SEARCH_ROOT / "run_context.json").read_text())
    ordinary = source_context["ordinary_preservation"]
    scales = source_context["objective"]["scales"]
    rows = []
    contribution_rows = []
    for candidate_index in context["design"]["candidate_panel"]["candidate_indices"]:
        candidate = frame.loc[frame["candidate_index"].eq(candidate_index)]
        for event_set in ("search_32", "all_74"):
            event_ids = _event_set_ids(context["design"], event_set)
            selected_events = candidate.loc[candidate["event_id"].isin(event_ids)]
            for replication_count in LADDER_REPLICATIONS:
                records = selected_events.loc[
                    selected_events["replication"].lt(replication_count)
                ]
                for moment in SIMULATED_CORE_MOMENT_ORDER:
                    estimate = fixed_moment_mcse(
                        records,
                        moment,
                        ordinary_preservation=ordinary,
                    )
                    threshold = 0.10 * float(scales[moment])
                    rows.append(
                        {
                            "candidate_index": candidate_index,
                            "event_set": event_set,
                            "replication_count": replication_count,
                            "moment": moment,
                            "event_count": len(event_ids),
                            "point_estimate": estimate.point_estimate,
                            "analytic_mcse": estimate.analytic_mcse,
                            "replication_index_mcse": estimate.replication_index_mcse,
                            "diagnostic_mcse": estimate.diagnostic_mcse,
                            "relative_disagreement": estimate.relative_disagreement,
                            "agreement_pass": estimate.agreement_pass,
                            "threshold": threshold,
                            "pass": estimate.diagnostic_mcse <= threshold,
                            "dominant_event": estimate.dominant_event or "",
                            "dominant_event_mc_variance_share": (
                                estimate.dominant_event_share
                            ),
                            "effective_event_count": estimate.effective_event_count,
                            "right_censoring_share": float(
                                records["right_censored"].mean()
                            ),
                        }
                    )
                    for event_id, contribution in (
                        estimate.event_variance_contributions.items()
                    ):
                        contribution_rows.append(
                            {
                                "candidate_index": candidate_index,
                                "event_set": event_set,
                                "replication_count": replication_count,
                                "moment": moment,
                                "event_id": event_id,
                                "mc_variance_contribution": contribution,
                            }
                        )
    ladder = pd.DataFrame(rows)
    for keys, group in ladder.groupby(
        ["candidate_index", "event_set", "moment"], sort=True
    ):
        slope, classification = convergence_slope(
            group["replication_count"], group["diagnostic_mcse"]
        )
        mask = (
            ladder["candidate_index"].eq(keys[0])
            & ladder["event_set"].eq(keys[1])
            & ladder["moment"].eq(keys[2])
        )
        ladder.loc[mask, "convergence_slope"] = slope
        ladder.loc[mask, "convergence_classification"] = classification
        maximum = group.loc[group["replication_count"].idxmax()]
        projection = projected_required_replications(
            replication_count=int(maximum["replication_count"]),
            mcse=float(maximum["diagnostic_mcse"]),
            threshold=float(maximum["threshold"]),
            convergence_classification=classification,
        )
        ladder.loc[mask, "projected_required_replications"] = (
            "" if projection is None else str(projection)
        )
    _atomic_csv(
        Path(run_dir) / "event_mc_variance_contributions.csv",
        pd.DataFrame(contribution_rows),
    )
    return ladder, {
        "row_count": len(ladder),
        "candidate_count": int(ladder["candidate_index"].nunique()),
        "event_sets": sorted(ladder["event_set"].unique()),
        "replication_levels": sorted(
            int(value) for value in ladder["replication_count"].unique()
        ),
        "core_moments": sorted(ladder["moment"].unique()),
    }


def _extended_worker_initialise(run_dir_text: str) -> None:
    global _LADDER_CONTEXT
    _ladder_worker_initialise(run_dir_text)
    if _LADDER_CONTEXT is None:
        raise RuntimeError("Extended worker context was not initialised.")
    manifest = json.loads(
        (
            Path(run_dir_text) / "cache_extended_manifest.json"
        ).read_text(encoding="utf-8")
    )
    _LADDER_CONTEXT["entries"] = {
        (entry["event_id"], int(entry["replication"])): entry
        for entry in manifest["packages"]
    }
    _LADDER_CONTEXT["paths"] = {}


def _truncate_package(
    package: search.CachedPackage,
    *,
    horizon: int,
) -> search.CachedPackage:
    arrays = {
        name: (
            values[:horizon]
            if len(values) == len(package.arrays["timestamps_ns"])
            else values
        )
        for name, values in package.arrays.items()
    }
    metadata = dict(package.metadata)
    metadata["path_length"] = horizon
    metadata["maximum_end_position"] = horizon - 1
    base = search.CachedPackage(metadata=metadata, arrays=arrays)
    return search.CachedPackage(
        metadata=metadata,
        arrays=arrays,
        path=search._path_from_package(base),
    )


def _extended_checkpoint_path(run_dir: Path, event_id: str) -> Path:
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:16]
    return run_dir / "extended" / f"{digest}__r000_063.npz"


def _extended_event_task(event_id: str) -> dict[str, Any]:
    if _LADDER_CONTEXT is None:
        raise RuntimeError("Extended worker is not initialised.")
    context = _LADDER_CONTEXT
    output_path = _extended_checkpoint_path(context["run_dir"], event_id)
    if output_path.is_file():
        arrays = _load_npz(output_path)
        expected = 8 * 64 * 3
        if len(arrays["candidate_index"]) != expected:
            raise ValueError(f"Incomplete extended checkpoint: {output_path}.")
        return {"event_id": event_id, "reused": True, "path": output_path.as_posix()}
    rows: dict[str, list[Any]] = defaultdict(list)
    candidate_indices = context["panel_indices"][:8]
    for replication in range(64):
        package = _load_cached_package(
            context,
            event_id=event_id,
            replication=replication,
            suffix="extended",
        )
        for horizon in (PRIMARY_HORIZON, HORIZON_ONE, HORIZON_TWO):
            truncated = _truncate_package(package, horizon=horizon)
            worker_context = search.WorkerContext(
                run_dir=context["run_dir"],
                search_id=context["diagnosis_id"],
                event_ids=(event_id,),
                config=replace(context["config"], maximum_event_horizon_hours=horizon),
                stage1=context["stage1"],
                scaling=context["scaling"],
                ordinary_preservation=context["ordinary"],
                objective=context["objective"],
                candidates=context["candidates"],
                transformed=context["transformed"],
                packages={(event_id, replication): truncated},
            )
            for candidate_index in candidate_indices:
                metrics, checksum, structural = search._evaluate_cached_event(
                    worker_context,
                    candidate=context["candidates"][candidate_index],
                    event_id=event_id,
                    replication=replication,
                )
                rows["candidate_index"].append(candidate_index)
                rows["replication"].append(replication)
                rows["horizon"].append(horizon)
                for name in METRIC_COLUMNS:
                    rows[name].append(metrics[name])
                rows["result_checksum"].append(checksum)
                rows["structural_valid"].append(
                    search.structural_event_flags_pass(structural)
                )
    arrays = {
        name: np.asarray(values)
        for name, values in rows.items()
    }
    _atomic_npz(output_path, arrays)
    return {"event_id": event_id, "reused": False, "path": output_path.as_posix()}


def run_extended_horizon_diagnosis(
    *,
    run_dir: Path,
    workers: int = 4,
    resume: bool = False,
) -> dict[str, Any]:
    """Evaluate fixed H0/H1/H2 prefixes for the first eight panel candidates."""
    validate_diagnostic_cache(run_dir, horizon=HORIZON_TWO)
    context = json.loads((Path(run_dir) / "run_context.json").read_text())
    event_ids = list(context["design"]["all_event_ids"])
    existing = [
        event_id
        for event_id in event_ids
        if _extended_checkpoint_path(Path(run_dir), event_id).is_file()
    ]
    if existing and not resume:
        raise ValueError("Extended checkpoints exist; use explicit resume.")
    started = time.perf_counter()
    process_context = mp.get_context("spawn")
    if workers == 1:
        _extended_worker_initialise(str(run_dir))
        results = [_extended_event_task(event_id) for event_id in event_ids]
    else:
        with process_context.Pool(
            processes=workers,
            initializer=_extended_worker_initialise,
            initargs=(str(Path(run_dir).resolve()),),
        ) as pool:
            results = list(
                pool.imap_unordered(_extended_event_task, event_ids, chunksize=1)
            )
    result = {
        "candidate_count": 8,
        "event_count": 74,
        "replications": 64,
        "horizons": [PRIMARY_HORIZON, HORIZON_ONE, HORIZON_TWO],
        "checkpoint_count": len(results),
        "reused_checkpoints": sum(item["reused"] for item in results),
        "new_checkpoints": sum(not item["reused"] for item in results),
        "wall_seconds": time.perf_counter() - started,
        "workers": workers,
        "runtime_adopted": False,
    }
    history_path = Path(run_dir) / "extended_history.json"
    history = (
        json.loads(history_path.read_text())
        if history_path.is_file()
        else {"operations": []}
    )
    history["operations"].append(result)
    _atomic_json(history_path, history)
    return result


def _load_extended_frame(run_dir: Path) -> pd.DataFrame:
    context = json.loads((Path(run_dir) / "run_context.json").read_text())
    frames = []
    for event_id in context["design"]["all_event_ids"]:
        arrays = _load_npz(_extended_checkpoint_path(Path(run_dir), event_id))
        frame = pd.DataFrame(arrays)
        frame.insert(0, "event_id", event_id)
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    expected = 8 * 74 * 64 * 3
    if len(result) != expected:
        raise ValueError(f"Extended diagnosis has {len(result)} of {expected} rows.")
    if result[["candidate_index", "event_id", "replication", "horizon"]].duplicated().any():
        raise ValueError("Extended diagnosis contains duplicate results.")
    return result


def _restricted_mean(durations: np.ndarray, horizon: int) -> float:
    return float(np.minimum(durations, horizon - 1).mean())


def kaplan_meier_curve(
    durations: Sequence[float],
    observed: Sequence[bool],
) -> pd.DataFrame:
    """Return a deterministic right-censoring-aware recovery curve."""
    frame = pd.DataFrame(
        {
            "duration": np.asarray(durations, dtype=float),
            "observed": np.asarray(observed, dtype=bool),
        }
    ).sort_values(["duration", "observed"], kind="mergesort")
    if frame.empty or (frame["duration"] < 0.0).any():
        raise ValueError("Recovery-curve inputs must be non-empty and non-negative.")
    at_risk = len(frame)
    survival = 1.0
    rows = []
    for duration, group in frame.groupby("duration", sort=True):
        recovered = int(group["observed"].sum())
        censored = int((~group["observed"]).sum())
        if recovered:
            survival *= 1.0 - recovered / at_risk
        rows.append(
            {
                "duration": float(duration),
                "at_risk": at_risk,
                "recovered": recovered,
                "censored": censored,
                "survival_probability": survival,
                "recovery_probability": 1.0 - survival,
            }
        )
        at_risk -= recovered + censored
    return pd.DataFrame(rows)


def validate_extended_primary_prefix(run_dir: Path) -> dict[str, Any]:
    """Require exact H0 equality before interpreting longer continuations."""
    run_dir = Path(run_dir)
    context = json.loads((run_dir / "run_context.json").read_text())
    candidate_indices = context["design"]["candidate_panel"]["candidate_indices"][:8]
    primary = _load_ladder_frame(run_dir)
    primary = primary.loc[
        primary["candidate_index"].isin(candidate_indices)
        & primary["replication"].lt(64)
    ]
    extended = _load_extended_frame(run_dir)
    extended = extended.loc[extended["horizon"].eq(PRIMARY_HORIZON)]
    keys = ["candidate_index", "event_id", "replication"]
    merged = primary.merge(
        extended,
        on=keys,
        suffixes=("_primary", "_extended"),
        validate="one_to_one",
    )
    if len(merged) != 8 * 74 * 64:
        raise ValueError("The extended H0 comparison is incomplete.")
    for name in METRIC_COLUMNS:
        left = merged[f"{name}_primary"].to_numpy()
        right = merged[f"{name}_extended"].to_numpy()
        if not np.array_equal(left, right, equal_nan=True):
            raise ValueError(f"Extended H0 differs from the primary run: {name}.")
    return {
        "status": "passed",
        "candidate_count": 8,
        "event_count": 74,
        "replication_count": 64,
        "event_replication_results_checked": len(merged),
        "metric_count": len(METRIC_COLUMNS),
        "exact_metric_equality": True,
    }


def summarise_primary_censoring_audit(run_dir: Path) -> dict[str, Any]:
    """Audit primary-horizon censoring at every fixed replication level."""
    run_dir = Path(run_dir)
    frame = _load_ladder_frame(run_dir)
    context = json.loads((run_dir / "run_context.json").read_text())
    catalogue = pd.read_csv(CONFIDENCE_EVIDENCE / "event_catalogue.csv")
    calibration = catalogue.loc[catalogue["partition"].eq("calibration")].copy()
    eth_low, eth_high = quartile_event_sets(
        calibration,
        stratifier="eth_recovery_24h",
    )
    burden_low, burden_high = quartile_event_sets(
        calibration,
        stratifier="first_six_hour_burden",
    )
    quartiles = {
        "eth_recovery_q1": eth_low,
        "eth_recovery_q4": eth_high,
        "first_six_hour_burden_q1": burden_low,
        "first_six_hour_burden_q4": burden_high,
    }
    summary_rows = []
    event_rows = []
    quartile_rows = []
    for candidate_index in context["design"]["candidate_panel"]["candidate_indices"]:
        candidate = frame.loc[frame["candidate_index"].eq(candidate_index)]
        for replication_count in LADDER_REPLICATIONS:
            selected = candidate.loc[
                candidate["replication"].lt(replication_count)
            ]
            total_squared = 0.0
            censored_squared = 0.0
            for event_id, event in selected.groupby("event_id", sort=True):
                durations = event["recovery_completion_hours"].to_numpy(dtype=float)
                squared = (durations - durations.mean()) ** 2
                event_total = float(squared.sum())
                event_censored = float(
                    squared[event["right_censored"].to_numpy(dtype=bool)].sum()
                )
                total_squared += event_total
                censored_squared += event_censored
                event_rows.append(
                    {
                        "candidate_index": int(candidate_index),
                        "replication_count": replication_count,
                        "event_id": event_id,
                        "run_count": len(event),
                        "right_censored_count": int(
                            event["right_censored"].sum()
                        ),
                        "right_censored_share": float(
                            event["right_censored"].mean()
                        ),
                    }
                )
            for label, event_ids in quartiles.items():
                group = selected.loc[selected["event_id"].isin(event_ids)]
                quartile_rows.append(
                    {
                        "candidate_index": int(candidate_index),
                        "replication_count": replication_count,
                        "quartile": label,
                        "event_count": len(event_ids),
                        "run_count": len(group),
                        "right_censored_count": int(
                            group["right_censored"].sum()
                        ),
                        "right_censored_share": float(
                            group["right_censored"].mean()
                        ),
                    }
                )
            censored_durations = sorted(
                float(value)
                for value in selected.loc[
                    selected["right_censored"], "recovery_completion_hours"
                ].unique()
            )
            summary_rows.append(
                {
                    "candidate_index": int(candidate_index),
                    "replication_count": replication_count,
                    "event_count": 74,
                    "run_count": len(selected),
                    "right_censored_count": int(
                        selected["right_censored"].sum()
                    ),
                    "right_censored_share": float(
                        selected["right_censored"].mean()
                    ),
                    "censored_squared_deviation_share": (
                        censored_squared / total_squared
                        if total_squared > 0.0
                        else 0.0
                    ),
                    "censoring_duration_sentinels": "|".join(
                        f"{value:.12g}" for value in censored_durations
                    ),
                    "censoring_duration_mass": float(
                        selected["right_censored"].mean()
                    ),
                }
            )
    summary = pd.DataFrame(summary_rows)
    _atomic_csv(run_dir / "primary_censoring_audit.csv", summary)
    _atomic_csv(run_dir / "primary_censoring_by_event.csv", pd.DataFrame(event_rows))
    _atomic_csv(
        run_dir / "primary_censoring_by_quartile.csv",
        pd.DataFrame(quartile_rows),
    )
    return {
        "candidate_replication_rows": summary.to_dict(orient="records"),
        "event_detail_row_count": len(event_rows),
        "quartile_detail_row_count": len(quartile_rows),
        "primary_horizon_steps": PRIMARY_HORIZON,
        "numeric_censoring_sentinel": 743.0,
        "sentinel_explanation": (
            "The fixed 792-step event package includes the registered pre-event "
            "positioning; the unchanged core metric records 743 hours at "
            "right-censoring."
        ),
    }


def summarise_censoring(run_dir: Path) -> dict[str, Any]:
    """Summarise fixed-horizon and continuation censoring without a new objective."""
    primary = _load_ladder_frame(run_dir)
    extended = _load_extended_frame(run_dir)
    context = json.loads((Path(run_dir) / "run_context.json").read_text())
    catalogue = pd.read_csv(CONFIDENCE_EVIDENCE / "event_catalogue.csv")
    calibration = catalogue.loc[catalogue["partition"].eq("calibration")]
    eth_low, eth_high = quartile_event_sets(
        calibration.rename(columns={"event_id": "event_id"}),
        stratifier="eth_recovery_24h",
    )
    first_eight = context["design"]["candidate_panel"]["candidate_indices"][:8]
    h0 = extended.loc[extended["horizon"].eq(PRIMARY_HORIZON)]
    h1 = extended.loc[extended["horizon"].eq(HORIZON_ONE)]
    h2 = extended.loc[extended["horizon"].eq(HORIZON_TWO)]
    key = ["candidate_index", "event_id", "replication"]
    merged = (
        h0[key + ["right_censored", "recovery_completion_hours"]]
        .rename(
            columns={
                "right_censored": "censored_h0",
                "recovery_completion_hours": "duration_h0",
            }
        )
        .merge(
            h1[key + ["right_censored", "recovery_completion_hours"]].rename(
                columns={
                    "right_censored": "censored_h1",
                    "recovery_completion_hours": "duration_h1",
                }
            ),
            on=key,
            validate="one_to_one",
        )
        .merge(
            h2[key + ["right_censored", "recovery_completion_hours"]].rename(
                columns={
                    "right_censored": "censored_h2",
                    "recovery_completion_hours": "duration_h2",
                }
            ),
            on=key,
            validate="one_to_one",
        )
    )
    censored = merged.loc[merged["censored_h0"]]
    recovered_h1 = int((~censored["censored_h1"]).sum())
    recovered_h2 = int((~censored["censored_h2"]).sum())
    by_candidate = []
    for candidate_index, group in merged.groupby("candidate_index", sort=True):
        source = group.loc[group["censored_h0"]]
        by_candidate.append(
            {
                "candidate_index": int(candidate_index),
                "censored_h0": len(source),
                "recovered_by_h1": int((~source["censored_h1"]).sum()),
                "recovered_by_h2": int((~source["censored_h2"]).sum()),
            }
        )
    low_rate = float(
        primary.loc[
            primary["candidate_index"].isin(first_eight)
            & primary["replication"].lt(64)
            & primary["event_id"].isin(eth_low),
            "right_censored",
        ].mean()
    )
    high_rate = float(
        primary.loc[
            primary["candidate_index"].isin(first_eight)
            & primary["replication"].lt(64)
            & primary["event_id"].isin(eth_high),
            "right_censored",
        ].mean()
    )
    survival = {}
    survival_curves = []
    for quartile, ids in (("q1", eth_low), ("q4", eth_high)):
        group = merged.loc[merged["event_id"].isin(ids)]
        durations = np.where(
            group["censored_h2"],
            HORIZON_TWO,
            group["duration_h2"],
        )
        curve = kaplan_meier_curve(durations, ~group["censored_h2"].to_numpy())
        curve.insert(0, "eth_recovery_quartile", quartile)
        survival_curves.append(curve)
        survival[quartile] = {
            "restricted_mean_792": _restricted_mean(durations, PRIMARY_HORIZON),
            "restricted_mean_1584": _restricted_mean(durations, HORIZON_ONE),
            "recovery_probability_168": float(np.mean(durations <= 168)),
            "recovery_probability_336": float(np.mean(durations <= 336)),
            "recovery_probability_792": float(np.mean(durations <= 792)),
            "recovery_probability_1584": float(np.mean(durations <= 1_584)),
        }
    curve_frame = pd.concat(survival_curves, ignore_index=True)
    _atomic_csv(Path(run_dir) / "survival_curves.csv", curve_frame)
    result = {
        "schema_version": DIAGNOSTIC_SCHEMA,
        "primary_horizon": PRIMARY_HORIZON,
        "extended_horizons": [HORIZON_ONE, HORIZON_TWO],
        "candidate_count": 8,
        "event_count": 74,
        "replications": 64,
        "censored_at_h0": len(censored),
        "recovered_by_h1": recovered_h1,
        "recovered_by_h2": recovered_h2,
        "h1_recovery_share_of_h0_censored": (
            recovered_h1 / len(censored) if len(censored) else 1.0
        ),
        "h2_recovery_share_of_h0_censored": (
            recovered_h2 / len(censored) if len(censored) else 1.0
        ),
        "classification": classify_recovery_censoring(
            censored_at_h0=len(censored),
            recovered_by_h1=recovered_h1,
            recovered_by_h2=recovered_h2,
        ),
        "by_candidate": by_candidate,
        "eth_recovery_q1_censoring_rate": low_rate,
        "eth_recovery_q4_censoring_rate": high_rate,
        "q1_q4_imbalance": censoring_imbalance(low_rate, high_rate),
        "survival_aware_diagnostics": {
            **survival,
            "curve_row_count": len(curve_frame),
            "curve_method": "Kaplan-Meier with recovery as the observed event",
            "restricted_mean_q4_minus_q1_792": (
                survival["q4"]["restricted_mean_792"]
                - survival["q1"]["restricted_mean_792"]
            ),
            "restricted_mean_q4_minus_q1_1584": (
                survival["q4"]["restricted_mean_1584"]
                - survival["q1"]["restricted_mean_1584"]
            ),
        },
        "core_moment_replaced": False,
        "future_observed_dai_used": False,
        "final_validation_used": False,
        "runtime_adopted": False,
        "primary_prefix_validation": validate_extended_primary_prefix(run_dir),
        "primary_horizon_audit": summarise_primary_censoring_audit(run_dir),
    }
    return result


def _projection_distribution(values: Sequence[str]) -> dict[str, Any]:
    numeric = []
    over_cap = 0
    unavailable = 0
    for value in values:
        if not value:
            unavailable += 1
        elif value.startswith(">"):
            over_cap += 1
            numeric.append(REQUIRED_REPLICATION_CAP * 2)
        else:
            numeric.append(int(value))
    return {
        **(_distribution(numeric) if numeric else {}),
        "over_8192_count": over_cap,
        "unavailable_count": unavailable,
    }


def precision_feasibility(
    ladder: pd.DataFrame,
    *,
    censoring: Mapping[str, Any],
) -> dict[str, Any]:
    target = ladder.loc[
        ladder["event_set"].eq("all_74")
        & ladder["moment"].eq("eth_recovery_q4_q1_duration_contrast")
    ]
    at_256 = target.loc[target["replication_count"].eq(256)]
    passes = int(at_256["pass"].sum())
    slow_share = float(
        at_256["convergence_classification"]
        .eq("slow_or_unstable_convergence")
        .mean()
    )
    projections = [
        value
        for value in at_256["projected_required_replications"].astype(str)
        if value
    ]
    operational = [
        (
            REQUIRED_REPLICATION_CAP * 2
            if value.startswith(">")
            else int(float(value))
        )
        for value in projections
    ]
    q90 = float(np.quantile(operational, 0.90)) if operational else math.inf
    variance_floor = slow_share > 0.25
    if passes >= 12 or (q90 <= 512 and not variance_floor):
        band = "practically_recoverable"
    elif q90 <= 2_048 and not variance_floor:
        band = "recoverable_but_computationally_heavy"
    else:
        band = "operationally_impractical_under_current_moment"
    censoring_class = censoring["classification"]
    if (
        band == "practically_recoverable"
        and censoring_class != "predominantly_structural_non_recovery"
    ):
        diagnosis = "precision_recoverable_under_fixed_design"
        next_boundary = (
            "A future pass may pre-register a higher-replication all-event Sobol rerun."
        )
    elif (
        q90 <= 2_048
        or censoring_class
        in {
            "mainly_administrative_censoring",
            "mixed_administrative_and_structural_censoring",
        }
    ):
        diagnosis = "precision_recoverable_only_with_design_amendment"
        next_boundary = (
            "Pre-register the search-stage or horizon amendment before any rerun."
        )
    else:
        diagnosis = "recovery_moment_not_operationally_identifiable"
        next_boundary = (
            "Pre-register simplification or replacement of the recovery moment."
        )
    return {
        "precision_feasibility_band": band,
        "all_74_passes_at_256": passes,
        "slow_or_unstable_candidate_share": slow_share,
        "projected_requirement_q90": q90 if math.isfinite(q90) else ">8192",
        "non_vanishing_variance_floor_detected": variance_floor,
        "final_diagnosis_classification": diagnosis,
        "authorised_next_methodological_boundary": next_boundary,
        "candidate_selected": False,
        "runtime_adopted": False,
    }


def summarise_precision_diagnosis(
    *,
    run_dir: Path,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    register_manifest: bool = True,
) -> dict[str, Any]:
    """Create compact deterministic evidence from completed ignored checkpoints."""
    run_dir = Path(run_dir)
    audit = audit_completed_search(SEARCH_ROOT)
    panel = objective_blind_candidate_panel()
    prefix = validate_search_prefix(run_dir)
    ladder, ladder_summary = summarise_replication_ladder(
        run_dir=run_dir, evidence_dir=evidence_dir
    )
    censoring = summarise_censoring(run_dir)
    interactions = summarise_pairing_and_interactions(run_dir)
    censoring.update(interactions)
    decision = precision_feasibility(ladder, censoring=censoring)
    context = json.loads((run_dir / "run_context.json").read_text())
    diagnosis_id = context["diagnosis_id"]
    benchmark_history = json.loads(
        (run_dir / "ladder_history.json").read_text()
    )
    cache_primary = json.loads(
        (run_dir / "cache_primary_manifest.json").read_text()
    )
    cache_extended = json.loads(
        (run_dir / "cache_extended_manifest.json").read_text()
    )
    extended_history_path = run_dir / "extended_history.json"
    extended_history = (
        json.loads(extended_history_path.read_text())
        if extended_history_path.is_file()
        else {"operations": []}
    )
    observations_path = run_dir / "benchmark_observations.json"
    observations = (
        json.loads(observations_path.read_text())
        if observations_path.is_file()
        else {}
    )
    specification = {
        "schema_version": DIAGNOSTIC_SCHEMA,
        "diagnosis_id": diagnosis_id,
        "fixed_failure": audit["committed_failure_reproduction"],
        "estimand": audit["estimand"],
        "analytic_equal_event_variance_formula": (
            "sum_e(s_e^2/R)/|E|^2"
        ),
        "analytic_q4_q1_variance_formula": (
            "sum_Q4(s_e^2/R)/|E4|^2 + sum_Q1(s_e^2/R)/|E1|^2"
        ),
        "replication_index_formula": "sd(m_r)/sqrt(R)",
        "agreement_tolerance": AGREEMENT_TOLERANCE,
        "candidate_panel_algorithm": panel["selection_algorithm"],
        "candidate_panel_checksum": panel["panel_checksum"],
        "replication_ladder": list(LADDER_REPLICATIONS),
        "event_sets": {
            "search_32": context["design"]["source_search_event_ids"],
            "all_74": context["design"]["all_event_ids"],
        },
        "registry": REGISTRY_A,
        "primary_horizon": PRIMARY_HORIZON,
        "extended_horizons": [HORIZON_ONE, HORIZON_TWO],
        "threshold_rule": "0.10 * registered empirical scale",
        "parameter_selection_performed": False,
        "runtime_adopted": False,
    }
    ladder_wall = float(
        sum(item["wall_seconds"] for item in benchmark_history["operations"])
    )
    ladder_throughput = (PANEL_SIZE * 74 * 256) / ladder_wall
    primary_cache_bytes = int(
        sum(
            int(item["metadata_size_bytes"]) + int(item["arrays_size_bytes"])
            for item in cache_primary["packages"]
        )
    )
    extended_cache_bytes = int(
        sum(
            int(item["metadata_size_bytes"]) + int(item["arrays_size_bytes"])
            for item in cache_extended["packages"]
        )
    )
    checkpoint_bytes = int(
        sum(
            path.stat().st_size
            for path in (run_dir / "ladder").glob("*.npz")
        )
    )
    projected = {}
    for event_count in (32, 74):
        projected[str(event_count)] = {}
        for replications in (64, 128, 256, 512, 1_024):
            runs = 256 * event_count * replications
            projected[str(event_count)][str(replications)] = {
                "event_replication_runs": runs,
                "projected_wall_seconds": runs / ladder_throughput,
                "executed": False,
            }
    benchmark = {
        "schema_version": DIAGNOSTIC_SCHEMA,
        "diagnosis_id": diagnosis_id,
        "host_dependent": True,
        "ladder_operations": benchmark_history["operations"],
        "extended_operations": extended_history["operations"],
        "primary_cache_packages": cache_primary["package_count"],
        "primary_cache_bytes": primary_cache_bytes,
        "primary_cache_root_sha256": cache_primary["cache_root_sha256"],
        "extended_cache_packages": cache_extended["package_count"],
        "extended_cache_bytes": extended_cache_bytes,
        "extended_cache_root_sha256": cache_extended["cache_root_sha256"],
        "cache_reuse": {
            "primary_built_packages": int(
                observations.get("primary_cache", {}).get(
                    "built_packages", cache_primary["package_count"]
                )
            ),
            "primary_reused_packages": int(
                observations.get("primary_cache", {}).get("reused_packages", 0)
            ),
            "extended_built_packages": int(
                observations.get("extended_cache", {}).get(
                    "built_packages", cache_extended["package_count"]
                )
            ),
            "extended_reused_packages": int(
                observations.get("extended_cache", {}).get("reused_packages", 0)
            ),
            "candidate_invariant_packages_reused_across_candidates": True,
        },
        "new_event_replication_runs": PANEL_SIZE * 74 * 256,
        "extended_event_replication_runs": 8 * 74 * 64,
        "extended_horizon_prefix_evaluations": 8 * 74 * 64 * 3,
        "ladder_wall_seconds": ladder_wall,
        "ladder_throughput_event_replication_runs_per_second": ladder_throughput,
        "peak_memory_bytes": observations.get(
            "peak_memory_bytes", "not_measured_portably"
        ),
        "checkpoint_size_bytes": checkpoint_bytes,
        "observed_cache_builds": {
            "primary": observations.get(
                "primary_cache",
                {"wall_seconds": "not_recorded_by_initial_runner"},
            ),
            "extended": observations.get(
                "extended_cache",
                {"wall_seconds": "not_recorded_by_initial_runner"},
            ),
        },
        "projected_unexecuted_full_search": projected,
        "projections_executed": False,
        "timing_not_used_to_change_statistical_design": True,
        "runtime_adopted": False,
    }
    evidence_dir = Path(evidence_dir)
    paths = {
        "monte_carlo_precision_specification.json": specification,
        "monte_carlo_estimator_audit.json": audit,
        "monte_carlo_candidate_panel.json": panel,
        "recovery_censoring_diagnosis.json": censoring,
        "monte_carlo_precision_decision.json": decision,
        "monte_carlo_precision_benchmark.json": benchmark,
    }
    for name, payload in paths.items():
        _atomic_json(evidence_dir / name, payload)
    _atomic_csv(evidence_dir / "monte_carlo_replication_ladder.csv", ladder)
    tracked = [evidence_dir / name for name in TRACKED_EVIDENCE_NAMES]
    if register_manifest:
        _register_evidence(tracked)
    return {
        "diagnosis_id": diagnosis_id,
        "estimator_classification": audit["existing_estimator_classification"],
        "panel_indices": panel["candidate_indices"],
        "panel_checksum": panel["panel_checksum"],
        "search_prefix": prefix,
        "ladder": ladder_summary,
        "censoring_classification": censoring["classification"],
        "decision": decision,
        "tracked_evidence": [
            path.relative_to(REPOSITORY_ROOT).as_posix() for path in tracked
        ],
        "runtime_adopted": False,
    }


def _register_evidence(paths: Sequence[Path]) -> None:
    manifest = json.loads(CALIBRATION_MANIFEST.read_text(encoding="utf-8"))
    records = {record["path"]: record for record in manifest["artefacts"]}
    for path in paths:
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        records[relative] = {
            "path": relative,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "semantic_name": path.stem,
            "context": (
                "Pre-registered Monte Carlo precision and recovery-censoring "
                "diagnosis; no parameter selection or runtime adoption."
            ),
            "classification": "snapshot",
            "producer": "dai_sim.calibration.simulated_moments_diagnostics",
            "schema": (
                "Compact deterministic calibration evidence; host timing is "
                "confined to the benchmark artefact."
            ),
            "source_inputs": [
                "data/provenance/calibration/confidence/sobol_search_specification.json",
                "data/provenance/calibration/confidence/sobol_search_candidates.csv",
            ],
        }
    manifest["artefacts"] = [records[name] for name in sorted(records)]
    _atomic_bytes(
        CALIBRATION_MANIFEST,
        (
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False)
            + "\n"
        ).encode("utf-8"),
    )


def validate_completed_diagnosis(
    *,
    run_dir: Path,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> dict[str, Any]:
    """Validate completed ignored state and compact evidence boundaries."""
    primary_cache = validate_diagnostic_cache(
        run_dir, horizon=PRIMARY_HORIZON
    )
    extended_cache = validate_diagnostic_cache(run_dir, horizon=HORIZON_TWO)
    prefix = validate_search_prefix(run_dir)
    extended_prefix = validate_extended_primary_prefix(run_dir)
    frame = _load_ladder_frame(run_dir)
    extended = _load_extended_frame(run_dir)
    manifest = {
        record["path"]: record
        for record in json.loads(CALIBRATION_MANIFEST.read_text())["artefacts"]
    }
    missing = []
    invalid = []
    for name in TRACKED_EVIDENCE_NAMES:
        path = Path(evidence_dir) / name
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        if not path.is_file() or relative not in manifest:
            missing.append(relative)
        elif sha256_file(path) != manifest[relative]["sha256"]:
            invalid.append(relative)
    decision = json.loads(
        (Path(evidence_dir) / "monte_carlo_precision_decision.json").read_text()
    )
    top16 = json.loads(
        (Path(evidence_dir) / "sobol_search_top16.json").read_text()
    )
    if top16["candidates"]:
        raise ValueError("The committed top-16 result is no longer empty.")
    if missing or invalid:
        raise ValueError(f"Missing/invalid diagnosis evidence: {missing}, {invalid}.")
    return {
        "status": "passed",
        "primary_cache": primary_cache,
        "extended_cache": extended_cache,
        "search_prefix": prefix,
        "extended_primary_prefix": extended_prefix,
        "ladder_rows": len(frame),
        "extended_rows": len(extended),
        "tracked_evidence_count": len(TRACKED_EVIDENCE_NAMES),
        "final_diagnosis": decision["final_diagnosis_classification"],
        "candidate_selected": False,
        "top16_count": 0,
        "powell_evaluations": 0,
        "registry_b_evaluations": 0,
        "usdc_svb_simulations": 0,
        "final_validation_simulations": 0,
        "runtime_adopted": False,
    }
