"""Grid-based partial identification for dormant confidence parameters.

This calibration-only module classifies the fixed 256-point Sobol design
against pre-registered empirical support bands.  It never evaluates a scalar
objective, ranks candidates, selects an estimate, or changes production
configuration.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.special import expit

from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file

from . import simulated_moments_search as search
from .event_simulation import ConditionalEventSimulationConfig
from .market import CONFIDENCE_EVIDENCE
from .simulated_moments import (
    DEFAULT_REGISTRY_IDS,
    STAGE1_PRESERVATION_MOMENTS,
    STAGE2_ACTIVE_MOMENTS,
    StructuralParameters,
    array_sha256,
    sobol_candidates,
)
from .simulated_moments_diagnostics import (
    MEAN_MOMENTS,
    METRIC_COLUMNS,
    PRIMARY_HORIZON,
    SEARCH_ROOT,
    analytic_contrast_mcse,
    analytic_equal_event_mcse,
    diagnostic_directory,
    objective_blind_candidate_panel,
    validate_diagnostic_cache,
)


SCHEMA_VERSION = 1
CANDIDATE_SCHEMA = 1
REGISTRY_A = DEFAULT_REGISTRY_IDS[0]
CANDIDATE_COUNT = 256
EVENT_COUNT = 74
REPLICATION_COUNT = 64
MC_INTERVAL_LEVEL = 0.90
MC_INTERVAL_CRITICAL_VALUE = 1.645
SUPPORT_MULTIPLIER = 2.0
NUMERICAL_BOUND_LIMIT = 0.01
MAX_REPRESENTATIVES = 24
MAX_NEW_STORAGE_BYTES = 500 * 1024**2
MINIMUM_FREE_BYTES = 10 * 1024**3
EXPECTED_CANDIDATE_SHA256 = (
    "fc56a12f0066cd84a15f5df52254ccf4a678847168af45e7f235757b3b1adde5"
)
PARAMETER_NAMES = (
    "deterioration_adjustment",
    "recovery_adjustment",
    "confidence_floor",
    "panic_response",
)
PARAMETER_SYMBOLS = ("alpha_d", "alpha_r", "C_min", "kappa_P")
DEFAULT_ROOT = (
    REPOSITORY_ROOT
    / "outputs/diagnostics/calibration/confidence/partial_identification"
)
EVIDENCE_NAMES = (
    "partial_identification_specification.json",
    "partial_identification_constraints.csv",
    "partial_identification_candidates.csv",
    "partial_identification_set.json",
    "partial_identification_representatives.json",
    "partial_identification_reproducibility.json",
    "partial_identification_benchmark.json",
)
DETERMINISTIC_EVIDENCE_NAMES = EVIDENCE_NAMES[:-1]
NATURAL_SUPPORTS: dict[str, tuple[float | None, float | None]] = {
    "first_six_hour_burden_mean": (0.0, 1.0),
    "maximum_downside_deviation_mean": (0.0, None),
    "recovery_completion_hours_mean": (0.0, 792.0),
    "failed_recovery_attempts_mean": (0.0, None),
    "initial_gap_q4_q1_burden_contrast": (-1.0, 1.0),
}


@dataclass(frozen=True)
class SupportBand:
    """Pre-registered empirical compatibility band for one moment."""

    moment: str
    empirical_value: float
    empirical_scale: float
    raw_lower: float
    raw_upper: float
    adjusted_lower: float
    adjusted_upper: float
    natural_lower: float | None
    natural_upper: float | None


@dataclass(frozen=True)
class MonteCarloInterval:
    """Support-adjusted 90% Monte Carlo interval."""

    estimate: float
    mcse: float
    raw_lower: float
    raw_upper: float
    adjusted_lower: float
    adjusted_upper: float


def _finite(value: float, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite.")
    return result


def construct_support_band(
    *,
    moment: str,
    empirical_value: float,
    empirical_scale: float,
    multiplier: float = SUPPORT_MULTIPLIER,
    natural_support: tuple[float | None, float | None] | None = None,
) -> SupportBand:
    """Construct the fixed empirical value ±2 scale support band."""
    value = _finite(empirical_value, "Empirical value")
    scale = _finite(empirical_scale, "Empirical scale")
    width = _finite(multiplier, "Support multiplier")
    if scale <= 0.0 or width != SUPPORT_MULTIPLIER:
        raise ValueError("The empirical scale must be positive and the multiplier fixed at 2.")
    support = natural_support if natural_support is not None else (None, None)
    lower_support, upper_support = support
    if lower_support is not None:
        lower_support = _finite(lower_support, "Natural lower support")
    if upper_support is not None:
        upper_support = _finite(upper_support, "Natural upper support")
    if (
        lower_support is not None
        and upper_support is not None
        and lower_support > upper_support
    ):
        raise ValueError("Natural support endpoints are reversed.")
    raw_lower = value - width * scale
    raw_upper = value + width * scale
    adjusted_lower = (
        raw_lower if lower_support is None else max(raw_lower, lower_support)
    )
    adjusted_upper = (
        raw_upper if upper_support is None else min(raw_upper, upper_support)
    )
    if adjusted_lower > adjusted_upper:
        raise ValueError("Natural support removes the empirical band.")
    return SupportBand(
        moment=moment,
        empirical_value=value,
        empirical_scale=scale,
        raw_lower=raw_lower,
        raw_upper=raw_upper,
        adjusted_lower=adjusted_lower,
        adjusted_upper=adjusted_upper,
        natural_lower=lower_support,
        natural_upper=upper_support,
    )


def construct_mc_interval(
    *,
    estimate: float,
    mcse: float,
    natural_support: tuple[float | None, float | None] = (None, None),
    critical_value: float = MC_INTERVAL_CRITICAL_VALUE,
) -> MonteCarloInterval:
    """Construct the fixed support-adjusted 90% Monte Carlo interval."""
    centre = _finite(estimate, "Simulated estimate")
    uncertainty = _finite(mcse, "MCSE")
    critical = _finite(critical_value, "MC interval critical value")
    if uncertainty < 0.0 or critical != MC_INTERVAL_CRITICAL_VALUE:
        raise ValueError("MCSE cannot be negative and the 90% rule is fixed.")
    raw_lower = centre - critical * uncertainty
    raw_upper = centre + critical * uncertainty
    lower_support, upper_support = natural_support
    adjusted_lower = (
        raw_lower if lower_support is None else max(raw_lower, float(lower_support))
    )
    adjusted_upper = (
        raw_upper if upper_support is None else min(raw_upper, float(upper_support))
    )
    if adjusted_lower > adjusted_upper:
        raise ValueError("The simulated interval is outside its natural support.")
    return MonteCarloInterval(
        estimate=centre,
        mcse=uncertainty,
        raw_lower=raw_lower,
        raw_upper=raw_upper,
        adjusted_lower=adjusted_lower,
        adjusted_upper=adjusted_upper,
    )


def classify_moment(
    interval: MonteCarloInterval,
    band: SupportBand,
) -> dict[str, Any]:
    """Classify interval containment and overlap without centre distance."""
    inner = (
        interval.adjusted_lower >= band.adjusted_lower
        and interval.adjusted_upper <= band.adjusted_upper
    )
    outer = (
        interval.adjusted_upper >= band.adjusted_lower
        and interval.adjusted_lower <= band.adjusted_upper
    )
    return {
        "classification": "inner_pass" if inner else "outer_pass" if outer else "fail",
        "inner_pass": bool(inner),
        "outer_pass": bool(outer),
    }


def classify_candidate(
    *,
    moment_results: Mapping[str, Mapping[str, Any]],
    structural_pass: bool,
    numerical_bound_pass: bool,
    stage1_preservation_pass: bool,
) -> str:
    """Return the non-ranked candidate admissibility class."""
    if set(moment_results) != set(STAGE2_ACTIVE_MOMENTS):
        raise ValueError("Candidate classification requires exactly five moments.")
    hard = structural_pass and numerical_bound_pass and stage1_preservation_pass
    all_outer = all(bool(value["outer_pass"]) for value in moment_results.values())
    all_inner = all(bool(value["inner_pass"]) for value in moment_results.values())
    if hard and all_inner:
        return "inner_admissible"
    if hard and all_outer:
        return "outer_only"
    return "rejected"


def prior_range_contraction(frame: pd.DataFrame) -> dict[str, Any]:
    """Summarise grid-supported contraction in prior-normalised coordinates."""
    contractions: dict[str, float | None] = {}
    for symbol in PARAMETER_SYMBOLS:
        column = f"z_{symbol}"
        contractions[symbol] = (
            None
            if frame.empty
            else float(1.0 - (frame[column].max() - frame[column].min()))
        )
    finite = [value for value in contractions.values() if value is not None]
    return {
        "by_parameter": contractions,
        "minimum": None if not finite else float(min(finite)),
        "median": None if not finite else float(np.median(finite)),
        "maximum": None if not finite else float(max(finite)),
    }


def _parameter_summary(frame: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, symbol in zip(PARAMETER_NAMES, PARAMETER_SYMBOLS, strict=True):
        if frame.empty:
            result[symbol] = {
                "minimum": None,
                "q05": None,
                "q25": None,
                "median": None,
                "q75": None,
                "q95": None,
                "maximum": None,
                "prior_normalised_width": None,
                "lower_boundary_occupancy": None,
                "upper_boundary_occupancy": None,
            }
            continue
        values = frame[name].astype(float)
        unit = frame[f"z_{symbol}"].astype(float)
        quantiles = values.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
        result[symbol] = {
            "minimum": float(values.min()),
            "q05": float(quantiles.loc[0.05]),
            "q25": float(quantiles.loc[0.25]),
            "median": float(quantiles.loc[0.5]),
            "q75": float(quantiles.loc[0.75]),
            "q95": float(quantiles.loc[0.95]),
            "maximum": float(values.max()),
            "prior_normalised_width": float(unit.max() - unit.min()),
            "lower_boundary_occupancy": float(unit.le(0.05).mean()),
            "upper_boundary_occupancy": float(unit.ge(0.95).mean()),
        }
    return result


def _rank_correlations(frame: pd.DataFrame) -> dict[str, Any]:
    if len(frame) < 2:
        return {left: {right: None for right in PARAMETER_SYMBOLS} for left in PARAMETER_SYMBOLS}
    columns = [f"z_{name}" for name in PARAMETER_SYMBOLS]
    matrix = frame[columns].corr(method="spearman")
    return {
        left: {
            right: float(matrix.loc[f"z_{left}", f"z_{right}"])
            for right in PARAMETER_SYMBOLS
        }
        for left in PARAMETER_SYMBOLS
    }


def _pairwise_ranges(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for left_index, left in enumerate(PARAMETER_SYMBOLS):
        for right in PARAMETER_SYMBOLS[left_index + 1 :]:
            rows.append(
                {
                    "parameter_x": left,
                    "parameter_y": right,
                    "x_min": None if frame.empty else float(frame[f"z_{left}"].min()),
                    "x_max": None if frame.empty else float(frame[f"z_{left}"].max()),
                    "y_min": None if frame.empty else float(frame[f"z_{right}"].min()),
                    "y_max": None if frame.empty else float(frame[f"z_{right}"].max()),
                }
            )
    return rows


def summarise_candidate_set(
    frame: pd.DataFrame,
    *,
    total_candidates: int = CANDIDATE_COUNT,
) -> dict[str, Any]:
    """Summarise a finite grid set without implying a continuous region."""
    if total_candidates <= 0:
        raise ValueError("Total candidate count must be positive.")
    return {
        "candidate_count": int(len(frame)),
        "candidate_fraction": float(len(frame) / total_candidates),
        "parameter_summary": _parameter_summary(frame),
        "prior_range_contraction": prior_range_contraction(frame),
        "pairwise_rank_correlations": _rank_correlations(frame),
        "pairwise_feasible_ranges": _pairwise_ranges(frame),
        "numerical_bound_distribution": _distribution(frame, "price_bound_share"),
        "censoring_distribution": _distribution(frame, "right_censoring_share"),
        "failure_reason_counts_by_moment": {
            moment: {
                "inner_failures": int(
                    (
                        ~frame[
                            f"{moment.removesuffix('_mean')}__inner_pass"
                        ].astype(bool)
                    ).sum()
                ),
                "outer_failures": int(
                    (
                        ~frame[
                            f"{moment.removesuffix('_mean')}__outer_pass"
                        ].astype(bool)
                    ).sum()
                ),
            }
            for moment in STAGE2_ACTIVE_MOMENTS
        },
        "grid_envelope_warning": (
            "Finite-grid supported envelope; continuous vectors inside the "
            "reported bounds are not thereby admissible."
        ),
    }


def _distribution(frame: pd.DataFrame, column: str) -> dict[str, float | None]:
    if frame.empty:
        return {"minimum": None, "median": None, "q95": None, "maximum": None}
    values = frame[column].astype(float)
    return {
        "minimum": float(values.min()),
        "median": float(values.median()),
        "q95": float(values.quantile(0.95)),
        "maximum": float(values.max()),
    }


def select_representatives(
    outer: pd.DataFrame,
    *,
    inner_indices: set[int] | None = None,
    maximum: int = MAX_REPRESENTATIVES,
) -> dict[str, Any]:
    """Select an objective-blind coverage set in prior-normalised space."""
    if maximum < 1 or maximum > MAX_REPRESENTATIVES:
        raise ValueError("Representative count must be between one and 24.")
    if outer.empty:
        return {
            "representative_indices": [],
            "roles": {},
            "coverage_radius": None,
            "pairwise_distance": {},
            "representative_checksum": hashlib.sha256(b"[]").hexdigest(),
        }
    ordered = outer.sort_values("candidate_index", kind="mergesort").reset_index(drop=True)
    indices = ordered["candidate_index"].astype(int).to_numpy()
    points = ordered[[f"z_{name}" for name in PARAMETER_SYMBOLS]].to_numpy(float)
    by_index = {int(index): position for position, index in enumerate(indices)}
    roles: dict[int, list[str]] = {}

    def include(index: int, role: str) -> None:
        roles.setdefault(int(index), []).append(role)

    for dimension, symbol in enumerate(PARAMETER_SYMBOLS):
        values = points[:, dimension]
        minimum_value = values.min()
        maximum_value = values.max()
        include(int(indices[np.flatnonzero(values == minimum_value)[0]]), f"minimum_{symbol}")
        include(int(indices[np.flatnonzero(values == maximum_value)[0]]), f"maximum_{symbol}")

    distances = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)
    totals = distances.sum(axis=1)
    include(int(indices[np.flatnonzero(totals == totals.min())[0]]), "outer_medoid")

    inner = set() if inner_indices is None else set(inner_indices)
    inner_positions = [by_index[index] for index in sorted(inner) if index in by_index]
    if inner_positions:
        sub = distances[np.ix_(inner_positions, inner_positions)]
        totals = sub.sum(axis=1)
        local = int(np.flatnonzero(totals == totals.min())[0])
        include(int(indices[inner_positions[local]]), "inner_medoid")

    selected = list(roles)
    while len(selected) < min(maximum, len(indices)):
        selected_positions = [by_index[index] for index in selected]
        candidates = [index for index in indices if int(index) not in roles]
        scored = []
        for raw_index in candidates:
            index = int(raw_index)
            position = by_index[index]
            score = float(distances[position, selected_positions].min())
            scored.append((score, -index, index))
        _, _, chosen = max(scored)
        include(chosen, "farthest_point")
        selected.append(chosen)
    selected = list(roles)
    selected_positions = [by_index[index] for index in selected]
    coverage = float(distances[:, selected_positions].min(axis=1).max())
    if len(selected) > 1:
        pairwise = distances[np.ix_(selected_positions, selected_positions)]
        upper = pairwise[np.triu_indices(len(selected), k=1)]
        distance_summary = {
            "minimum": float(upper.min()),
            "median": float(np.median(upper)),
            "maximum": float(upper.max()),
        }
    else:
        distance_summary = {"minimum": 0.0, "median": 0.0, "maximum": 0.0}
    canonical = [
        {
            "candidate_index": index,
            "roles": roles[index],
            "z": [float(value) for value in points[by_index[index]]],
        }
        for index in selected
    ]
    checksum = search.payload_sha256(canonical)
    return {
        "representative_indices": selected,
        "roles": {str(index): roles[index] for index in selected},
        "coverage_radius": coverage,
        "pairwise_distance": distance_summary,
        "representative_checksum": checksum,
    }


def classify_partial_identification(
    *,
    inner_count: int,
    outer_count: int,
    outer_only_count: int,
    outer_contraction: Mapping[str, float | None],
    deterministic_evidence_reproduces: bool,
    regressions_unchanged: bool,
) -> tuple[str, str]:
    """Apply the fixed final classification hierarchy."""
    if not deterministic_evidence_reproduces or not regressions_unchanged:
        return (
            "partial_identification_analysis_invalid",
            "repair_reproducibility_or_regression_failure_before_inference",
        )
    if outer_count == 0:
        return (
            "model_evidence_incompatibility",
            "review_structural_model_assumptions_or_empirical_support_bands",
        )
    if outer_count <= 15:
        return (
            "sparse_admissible_set",
            "pre_register_denser_objective_blind_grid_around_supported_region",
        )
    values = [value for value in outer_contraction.values() if value is not None]
    strong = (
        inner_count >= 4
        and bool(values)
        and max(values) >= 0.25
        and outer_only_count / outer_count <= 0.50
    )
    if strong:
        return (
            "partial_identification_established",
            "run_mechanism_and_policy_experiments_across_fixed_representatives",
        )
    return (
        "weak_partial_identification",
        "run_only_broad_sensitivity_experiments_without_calibrated_range_claims",
    )


def _manifest_records() -> dict[str, dict[str, Any]]:
    manifest = json.loads(
        (REPOSITORY_ROOT / "data/provenance/calibration/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return {record["path"]: record for record in manifest["artefacts"]}


def _registered_checksum(path: Path) -> str:
    relative = path.relative_to(REPOSITORY_ROOT).as_posix()
    records = _manifest_records()
    if relative not in records:
        raise ValueError(f"Calibration evidence is not registered: {relative}.")
    digest = sha256_file(path)
    if records[relative]["sha256"] != digest:
        raise ValueError(f"Calibration evidence checksum differs: {relative}.")
    return digest


def _constraint_inputs(
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> tuple[dict[str, SupportBand], pd.DataFrame, pd.DataFrame]:
    evidence_dir = Path(evidence_dir)
    moments_path = evidence_dir / "objective_simplification_moments.csv"
    _registered_checksum(moments_path)
    moments = pd.read_csv(moments_path)
    if tuple(moments["moment"]) != (
        *STAGE1_PRESERVATION_MOMENTS,
        *STAGE2_ACTIVE_MOMENTS,
    ):
        raise ValueError("The registered seven-moment ordering changed.")
    active = moments.set_index("moment").loc[list(STAGE2_ACTIVE_MOMENTS)]
    bands = {
        name: construct_support_band(
            moment=name,
            empirical_value=float(active.loc[name, "empirical_value"]),
            empirical_scale=float(active.loc[name, "scale"]),
            natural_support=NATURAL_SUPPORTS[name],
        )
        for name in STAGE2_ACTIVE_MOMENTS
    }
    rows = []
    for name in STAGE2_ACTIVE_MOMENTS:
        band = bands[name]
        rows.append(
            {
                "moment": name,
                "empirical_value": band.empirical_value,
                "empirical_scale": band.empirical_scale,
                "natural_lower": (
                    "" if band.natural_lower is None else band.natural_lower
                ),
                "natural_upper": (
                    "" if band.natural_upper is None else band.natural_upper
                ),
                "raw_band_lower": band.raw_lower,
                "raw_band_upper": band.raw_upper,
                "adjusted_band_lower": band.adjusted_lower,
                "adjusted_band_upper": band.adjusted_upper,
                "support_multiplier": SUPPORT_MULTIPLIER,
                "mc_interval_level": MC_INTERVAL_LEVEL,
                "mc_interval_critical_value": MC_INTERVAL_CRITICAL_VALUE,
                "classification_rule": (
                    "inner iff C subset B; outer iff C intersects B; fail otherwise"
                ),
                "prior_evidence_reference": str(
                    active.loc[name, "prior_evidence_reference"]
                ),
            }
        )
    stage1 = moments.set_index("moment").loc[list(STAGE1_PRESERVATION_MOMENTS)]
    return bands, pd.DataFrame(rows), stage1


def _scientific_identity_payload(
    *,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    evidence_dir = Path(evidence_dir)
    source_cache = (
        diagnostic_directory(evidence_dir=evidence_dir)
        if cache_dir is None
        else Path(cache_dir)
    )
    bands, constraints, stage1 = _constraint_inputs(evidence_dir)
    transformed, structural = sobol_candidates()
    structural_array = np.asarray(
        [
            [
                item.deterioration_adjustment,
                item.recovery_adjustment,
                item.confidence_floor,
                item.panic_response,
            ]
            for item in structural
        ],
        dtype="<f8",
    )
    candidate_checksum = array_sha256(structural_array)
    if candidate_checksum != EXPECTED_CANDIDATE_SHA256:
        raise ValueError("The registered Sobol grid does not reproduce.")
    cache_validation = validate_diagnostic_cache(
        source_cache, horizon=PRIMARY_HORIZON
    )
    if cache_validation["event_count"] != EVENT_COUNT:
        raise ValueError("The all-event cache does not contain 74 events.")
    required_paths = {
        "stage1_market_estimates": evidence_dir / "stage1_market_estimates.json",
        "stage1_residual_summary": evidence_dir / "stage1_residual_summary.json",
        "empirical_moments": evidence_dir / "empirical_moments.csv",
        "parameter_bounds": evidence_dir / "parameter_bounds.json",
        "event_catalogue": evidence_dir / "event_catalogue.csv",
        "seed_registry": evidence_dir / "seed_registry.json",
        "conditional_event_specification": (
            evidence_dir / "conditional_event_specification.json"
        ),
        "conditional_initial_state": evidence_dir / "conditional_initial_state.json",
        "recovery_gate_specification": evidence_dir / "recovery_gate_specification.json",
    }
    evidence_checksums = {
        name: _registered_checksum(path) for name, path in required_paths.items()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "method": "finite_grid_partial_identification",
        "formal_confidence_region": False,
        "stage1_evidence_checksums": {
            name: evidence_checksums[name]
            for name in ("stage1_market_estimates", "stage1_residual_summary")
        },
        "empirical_moment_evidence_checksum": evidence_checksums["empirical_moments"],
        "stage1_preservation": [
            {
                "moment": name,
                "empirical_value": float(stage1.loc[name, "empirical_value"]),
                "empirical_scale": float(stage1.loc[name, "scale"]),
                "tolerance_scales": 2.0,
            }
            for name in STAGE1_PRESERVATION_MOMENTS
        ],
        "compatibility_constraints": constraints.to_dict(orient="records"),
        "support_multiplier": SUPPORT_MULTIPLIER,
        "mc_interval_level": MC_INTERVAL_LEVEL,
        "mc_interval_critical_value": MC_INTERVAL_CRITICAL_VALUE,
        "parameter_bounds_checksum": evidence_checksums["parameter_bounds"],
        "sobol_candidate_checksum": candidate_checksum,
        "sobol_candidate_count": CANDIDATE_COUNT,
        "event_catalogue_checksum": evidence_checksums["event_catalogue"],
        "event_count": EVENT_COUNT,
        "replication_count": REPLICATION_COUNT,
        "registry": REGISTRY_A,
        "seed_registry_checksum": evidence_checksums["seed_registry"],
        "conditional_event_specification_checksum": evidence_checksums[
            "conditional_event_specification"
        ],
        "conditional_initial_state_checksum": evidence_checksums[
            "conditional_initial_state"
        ],
        "recovery_gate_specification_checksum": evidence_checksums[
            "recovery_gate_specification"
        ],
        "cache_identity": {
            "cache_root_sha256": cache_validation["cache_root_sha256"],
            "package_count": cache_validation["package_count"],
            "replication_prefix": [0, REPLICATION_COUNT - 1],
        },
        "hard_gates": {
            "structural_validity": True,
            "maximum_numerical_bound_share": NUMERICAL_BOUND_LIMIT,
            "stage1_preservation_tolerance_scales": 2.0,
            "right_censoring_is_hard_gate": False,
        },
        "candidate_classes": [
            "inner_admissible",
            "outer_only",
            "rejected",
        ],
        "implementation_schema": {
            "partial_identification": SCHEMA_VERSION,
            "candidate_checkpoint": CANDIDATE_SCHEMA,
        },
        "scalar_objective": None,
        "candidate_ranking": False,
        "runtime_adopted": False,
    }


def partial_identification_identity(
    *,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    cache_dir: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return the content-addressed scientific identity."""
    payload = _scientific_identity_payload(
        evidence_dir=evidence_dir,
        cache_dir=cache_dir,
    )
    return search.payload_sha256(payload), payload


def partial_identification_directory(
    *,
    root: Path = DEFAULT_ROOT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    cache_dir: Path | None = None,
) -> Path:
    """Return the ignored directory for the fixed scientific identity."""
    identity, _ = partial_identification_identity(
        evidence_dir=evidence_dir,
        cache_dir=cache_dir,
    )
    return Path(root) / identity


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def prepare_partial_identification(
    *,
    root: Path = DEFAULT_ROOT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate fixed inputs and create only the ignored run context."""
    free = shutil.disk_usage(REPOSITORY_ROOT).free
    if free < MINIMUM_FREE_BYTES:
        raise ValueError("At least 10 GiB free space is required.")
    source_cache = (
        diagnostic_directory(evidence_dir=evidence_dir)
        if cache_dir is None
        else Path(cache_dir)
    )
    identity, scientific = partial_identification_identity(
        evidence_dir=evidence_dir,
        cache_dir=source_cache,
    )
    run_dir = Path(root) / identity
    run_dir.mkdir(parents=True, exist_ok=True)
    source_context = json.loads(
        (SEARCH_ROOT / "run_context.json").read_text(encoding="utf-8")
    )
    precision_context = json.loads(
        (source_cache / "run_context.json").read_text(encoding="utf-8")
    )
    context = {
        "schema_version": SCHEMA_VERSION,
        "set_id": identity,
        "scientific_inputs": scientific,
        "event_ids": precision_context["design"]["all_event_ids"],
        "source_cache_directory": source_cache.resolve().as_posix(),
        "source_cache_manifest_sha256": sha256_file(
            source_cache / "cache_primary_manifest.json"
        ),
        "source_search_context_sha256": sha256_file(
            SEARCH_ROOT / "run_context.json"
        ),
        "config": source_context["config"],
        "stage1": source_context["stage1"],
        "scaling": source_context["scaling"],
        "ordinary_preservation": source_context["ordinary_preservation"],
        "candidate_count": CANDIDATE_COUNT,
        "event_count": EVENT_COUNT,
        "replication_count": REPLICATION_COUNT,
        "registry": REGISTRY_A,
        "runtime_adopted": False,
    }
    path = run_dir / "run_context.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != context:
            raise ValueError("Existing partial-identification context differs.")
    else:
        search._atomic_json(path, context)
    return {
        "status": "passed",
        "set_id": identity,
        "run_directory": run_dir.as_posix(),
        "event_count": EVENT_COUNT,
        "replication_count": REPLICATION_COUNT,
        "candidate_count": CANDIDATE_COUNT,
        "cache_reused": True,
        "cache_root_sha256": scientific["cache_identity"]["cache_root_sha256"],
        "available_disk_bytes": free,
        "projected_new_ignored_bytes": 40 * 1024**2,
        "runtime_adopted": False,
    }


_PARTIAL_CONTEXT: dict[str, Any] | None = None


def _worker_initialise(run_dir_text: str) -> None:
    global _PARTIAL_CONTEXT
    search._thread_cap()
    run_dir = Path(run_dir_text)
    context = json.loads((run_dir / "run_context.json").read_text(encoding="utf-8"))
    cache_dir = Path(context["source_cache_directory"])
    manifest = json.loads(
        (cache_dir / "cache_primary_manifest.json").read_text(encoding="utf-8")
    )
    selected = [
        entry
        for entry in manifest["packages"]
        if int(entry["replication"]) < REPLICATION_COUNT
    ]
    if len(selected) != EVENT_COUNT * REPLICATION_COUNT:
        raise ValueError("The fixed 64-replication cache prefix is incomplete.")
    packages: dict[tuple[str, int], search.CachedPackage] = {}
    paths: dict[str, Any] = {}
    for entry in selected:
        metadata = json.loads(
            (cache_dir / "cache_primary" / entry["metadata_filename"]).read_text(
                encoding="utf-8"
            )
        )
        arrays = search._load_npz(
            cache_dir / "cache_primary" / entry["arrays_filename"]
        )
        event_id = str(entry["event_id"])
        path = paths.get(event_id)
        package = search.CachedPackage(metadata=metadata, arrays=arrays, path=path)
        if path is None:
            path = search._path_from_package(package)
            paths[event_id] = path
            package = search.CachedPackage(
                metadata=metadata,
                arrays=arrays,
                path=path,
            )
        packages[(event_id, int(entry["replication"]))] = package
    transformed, candidates = sobol_candidates()
    bands, _, stage1 = _constraint_inputs(CONFIDENCE_EVIDENCE)
    worker_context = search.WorkerContext(
        run_dir=run_dir,
        search_id=context["set_id"],
        event_ids=tuple(context["event_ids"]),
        config=ConditionalEventSimulationConfig(**context["config"]),
        stage1=context["stage1"],
        scaling=context["scaling"],
        ordinary_preservation=context["ordinary_preservation"],
        objective={},
        candidates=tuple(candidates),
        transformed=np.asarray(transformed, dtype="<f8"),
        packages=packages,
    )
    _PARTIAL_CONTEXT = {
        "run_dir": run_dir,
        "context": context,
        "worker": worker_context,
        "bands": bands,
        "stage1": stage1,
        "panel_indices": set(
            objective_blind_candidate_panel()["candidate_indices"]
        ),
    }


def _event_sufficient_statistics(frame: pd.DataFrame) -> list[dict[str, Any]]:
    metrics = (
        "first_six_hour_burden",
        "maximum_downside_deviation",
        "recovery_completion_hours",
        "failed_recovery_attempts",
    )
    rows = []
    for event_id, group in frame.groupby("event_id", sort=True):
        row: dict[str, Any] = {
            "event_id": str(event_id),
            "count": int(len(group)),
            "censoring_count": int(group["right_censored"].astype(bool).sum()),
            "numerical_bound_occurrence_count": int(
                group["numerical_bound_binding_share"].gt(0.0).sum()
            ),
            "active_bad_debt_occurrence_count": int(
                group["maximum_active_bad_debt_dai"].gt(0.0).sum()
            ),
            "unresolved_backlog_occurrence_count": int(
                group["maximum_unresolved_tab_dai"].gt(0.0).sum()
            ),
            "initial_peg_gap": float(group["initial_peg_gap"].iloc[0]),
        }
        for metric in metrics:
            values = group[metric].astype(float)
            row[f"{metric}_sum"] = float(values.sum())
            row[f"{metric}_sum_squares"] = float(np.square(values).sum())
        rows.append(row)
    return rows


def _evaluate_candidate(candidate_index: int) -> dict[str, Any]:
    if _PARTIAL_CONTEXT is None:
        raise RuntimeError("Partial-identification worker is not initialised.")
    started = time.perf_counter()
    owner = _PARTIAL_CONTEXT
    context: search.WorkerContext = owner["worker"]
    candidate = context.candidates[candidate_index]
    records = []
    structural_pass = True
    digest = hashlib.sha256()
    for event_id in sorted(context.event_ids):
        for replication in range(REPLICATION_COUNT):
            metrics, checksum, structural = search._evaluate_cached_event(
                context,
                candidate=candidate,
                event_id=event_id,
                replication=replication,
            )
            records.append(metrics)
            structural_pass &= search.structural_event_flags_pass(structural)
            digest.update(event_id.encode("utf-8"))
            digest.update(replication.to_bytes(2, "little"))
            digest.update(checksum.encode("ascii"))
    frame = pd.DataFrame(records).sort_values(
        ["event_id", "replication"], kind="mergesort"
    )
    if len(frame) != EVENT_COUNT * REPLICATION_COUNT:
        raise ValueError("Candidate event results are incomplete.")
    moment_results: dict[str, dict[str, Any]] = {}
    for moment in STAGE2_ACTIVE_MOMENTS:
        if moment in MEAN_MOMENTS:
            estimate = analytic_equal_event_mcse(
                frame, outcome=MEAN_MOMENTS[moment]
            )
        else:
            estimate = analytic_contrast_mcse(
                frame,
                outcome="first_six_hour_burden",
                stratifier="initial_peg_gap",
            )
        interval = construct_mc_interval(
            estimate=estimate.point_estimate,
            mcse=estimate.analytic_mcse,
            natural_support=NATURAL_SUPPORTS[moment],
        )
        classification = classify_moment(interval, owner["bands"][moment])
        moment_results[moment] = {
            "simulated_mean": estimate.point_estimate,
            "analytic_mcse": estimate.analytic_mcse,
            "replication_index_mcse": (
                estimate.replication_index_mcse
                if candidate_index in owner["panel_indices"]
                else None
            ),
            "raw_mc_lower": interval.raw_lower,
            "raw_mc_upper": interval.raw_upper,
            "adjusted_mc_lower": interval.adjusted_lower,
            "adjusted_mc_upper": interval.adjusted_upper,
            "empirical_band_lower": owner["bands"][moment].adjusted_lower,
            "empirical_band_upper": owner["bands"][moment].adjusted_upper,
            **classification,
        }
    durations = frame["recovery_completion_hours"].astype(float) + 1.0
    bound_steps = (
        frame["numerical_bound_binding_share"].astype(float) * durations
    ).sum()
    price_bound_share = float(bound_steps / durations.sum())
    source_stage1 = context.ordinary_preservation
    stage1_rows = owner["stage1"]
    stage1_results = {}
    for name in STAGE1_PRESERVATION_MOMENTS:
        empirical = float(stage1_rows.loc[name, "empirical_value"])
        scale = float(stage1_rows.loc[name, "scale"])
        simulated = float(source_stage1[name])
        stage1_results[name] = {
            "simulated_value": simulated,
            "empirical_value": empirical,
            "empirical_scale": scale,
            "within_two_scales": abs(simulated - empirical) <= 2.0 * scale,
        }
    stage1_pass = all(
        item["within_two_scales"] for item in stage1_results.values()
    )
    numerical_bound_pass = price_bound_share <= NUMERICAL_BOUND_LIMIT
    candidate_class = classify_candidate(
        moment_results=moment_results,
        structural_pass=structural_pass,
        numerical_bound_pass=numerical_bound_pass,
        stage1_preservation_pass=stage1_pass,
    )
    transformed = np.asarray(context.transformed[candidate_index], dtype=float)
    unit = expit(transformed)
    deterministic = {
        "schema_version": CANDIDATE_SCHEMA,
        "set_id": context.search_id,
        "candidate_index": candidate_index,
        "candidate_checksum": search._candidate_checksum(
            candidate_index, candidate, transformed
        ),
        "structural_parameters": asdict(candidate),
        "transformed_parameters": {
            symbol: float(value)
            for symbol, value in zip(PARAMETER_SYMBOLS, transformed, strict=True)
        },
        "prior_normalised_parameters": {
            symbol: float(value)
            for symbol, value in zip(PARAMETER_SYMBOLS, unit, strict=True)
        },
        "event_count": EVENT_COUNT,
        "replication_count": REPLICATION_COUNT,
        "event_replication_count": len(frame),
        "registry": REGISTRY_A,
        "moment_results": moment_results,
        "stage1_preservation": stage1_results,
        "hard_gates": {
            "structural_pass": bool(structural_pass),
            "numerical_bound_pass": bool(numerical_bound_pass),
            "stage1_preservation_pass": bool(stage1_pass),
        },
        "diagnostics": {
            "right_censoring_share": float(frame["right_censored"].mean()),
            "price_bound_share": price_bound_share,
            "confidence_floor_binding_share": float(
                np.isclose(
                    frame["minimum_confidence"].astype(float),
                    candidate.confidence_floor,
                    rtol=0.0,
                    atol=1e-12,
                ).mean()
            ),
            "unresolved_backlog_occurrence": bool(
                frame["maximum_unresolved_tab_dai"].gt(0.0).any()
            ),
            "unresolved_backlog_occurrence_share": float(
                frame["maximum_unresolved_tab_dai"].gt(0.0).mean()
            ),
            "active_bad_debt_occurrence": bool(
                frame["maximum_active_bad_debt_dai"].gt(0.0).any()
            ),
            "active_bad_debt_occurrence_share": float(
                frame["maximum_active_bad_debt_dai"].gt(0.0).mean()
            ),
            "maximum_unresolved_tab_dai": float(
                frame["maximum_unresolved_tab_dai"].max()
            ),
            "maximum_active_bad_debt_dai": float(
                frame["maximum_active_bad_debt_dai"].max()
            ),
            "recovery_probability_48h": float(
                (
                    ~frame["right_censored"].astype(bool)
                    & frame["recovery_completion_hours"].le(48)
                ).mean()
            ),
            "recovery_probability_168h": float(
                (
                    ~frame["right_censored"].astype(bool)
                    & frame["recovery_completion_hours"].le(168)
                ).mean()
            ),
            "recovery_probability_792h": float(
                (~frame["right_censored"].astype(bool)).mean()
            ),
            "failed_recovery_attempts_mean": float(
                frame["failed_recovery_attempts"].mean()
            ),
        },
        "event_sufficient_statistics": _event_sufficient_statistics(frame),
        "event_result_checksum": digest.hexdigest(),
        "candidate_classification": candidate_class,
        "scalar_objective_calculated": False,
        "candidate_rank_calculated": False,
        "runtime_adopted": False,
    }
    deterministic["result_checksum"] = search.payload_sha256(deterministic)
    return {
        **deterministic,
        "execution_duration_seconds": time.perf_counter() - started,
    }


def _candidate_path(run_dir: Path, index: int) -> Path:
    return Path(run_dir) / "candidates" / f"candidate_{index:03d}.json"


def validate_partial_candidate_checkpoint(
    run_dir: Path,
    index: int,
    *,
    expected_set_id: str,
) -> dict[str, Any]:
    """Validate one complete candidate-level atomic checkpoint."""
    path = _candidate_path(run_dir, index)
    if not path.is_file():
        raise ValueError(f"Candidate {index:03d} checkpoint is missing.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != CANDIDATE_SCHEMA
        or payload.get("set_id") != expected_set_id
        or payload.get("candidate_index") != index
        or payload.get("event_count") != EVENT_COUNT
        or payload.get("replication_count") != REPLICATION_COUNT
        or payload.get("event_replication_count")
        != EVENT_COUNT * REPLICATION_COUNT
    ):
        raise ValueError(f"Candidate {index:03d} checkpoint identity differs.")
    deterministic = {
        key: value
        for key, value in payload.items()
        if key not in {"execution_duration_seconds", "result_checksum"}
    }
    if search.payload_sha256(deterministic) != payload.get("result_checksum"):
        raise ValueError(f"Candidate {index:03d} result checksum differs.")
    if len(payload.get("event_sufficient_statistics", [])) != EVENT_COUNT:
        raise ValueError(f"Candidate {index:03d} event summaries are incomplete.")
    if payload.get("scalar_objective_calculated") or payload.get(
        "candidate_rank_calculated"
    ):
        raise ValueError("Partial-identification checkpoints cannot fit or rank.")
    return payload


def _worker_candidate(index: int) -> dict[str, Any]:
    try:
        return _evaluate_candidate(int(index))
    except Exception as error:
        raise RuntimeError(
            f"Partial-identification candidate {index:03d} failed: "
            f"{type(error).__name__}: {error}"
        ) from error


def run_partial_identification_grid(
    *,
    root: Path = DEFAULT_ROOT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    cache_dir: Path | None = None,
    workers: int = 4,
    resume: bool = False,
    recover_stale_lock: bool = False,
) -> dict[str, Any]:
    """Evaluate or resume the fixed 256-vector grid without an objective."""
    if workers < 1 or workers > 6:
        raise ValueError("Workers must be between one and six.")
    prepared = prepare_partial_identification(
        root=root,
        evidence_dir=evidence_dir,
        cache_dir=cache_dir,
    )
    run_dir = Path(prepared["run_directory"])
    set_id = prepared["set_id"]
    existing = []
    for index in range(CANDIDATE_COUNT):
        path = _candidate_path(run_dir, index)
        if path.is_file():
            validate_partial_candidate_checkpoint(
                run_dir, index, expected_set_id=set_id
            )
            existing.append(index)
    if existing and not resume:
        raise ValueError("Candidate checkpoints exist; use explicit resume.")
    pending = [index for index in range(CANDIDATE_COUNT) if index not in existing]
    started = time.perf_counter()
    free_before = shutil.disk_usage(REPOSITORY_ROOT).free
    with search.search_lock(
        run_dir,
        "resume_partial_identification" if resume else "run_partial_identification",
        recover_stale=recover_stale_lock,
    ):
        if pending:
            if workers == 1:
                _worker_initialise(str(run_dir))
                iterator = map(_worker_candidate, pending)
                for payload in iterator:
                    search._atomic_json(
                        _candidate_path(run_dir, payload["candidate_index"]),
                        payload,
                    )
                    validate_partial_candidate_checkpoint(
                        run_dir,
                        payload["candidate_index"],
                        expected_set_id=set_id,
                    )
            else:
                context = mp.get_context("spawn")
                with context.Pool(
                    processes=workers,
                    initializer=_worker_initialise,
                    initargs=(str(run_dir.resolve()),),
                ) as pool:
                    for payload in pool.imap_unordered(
                        _worker_candidate, pending, chunksize=1
                    ):
                        search._atomic_json(
                            _candidate_path(
                                run_dir, payload["candidate_index"]
                            ),
                            payload,
                        )
                        validate_partial_candidate_checkpoint(
                            run_dir,
                            payload["candidate_index"],
                            expected_set_id=set_id,
                        )
                        if _directory_size(run_dir) > MAX_NEW_STORAGE_BYTES:
                            raise ValueError(
                                "New partial-identification storage exceeds 500 MB."
                            )
    completed = [
        index
        for index in range(CANDIDATE_COUNT)
        if _candidate_path(run_dir, index).is_file()
    ]
    if len(completed) != CANDIDATE_COUNT:
        raise ValueError("The partial-identification grid is incomplete.")
    operation = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "set_id": set_id,
        "workers": workers,
        "resumed": bool(resume),
        "reused_candidates": len(existing),
        "new_candidates": len(pending),
        "completed_candidates": len(completed),
        "event_replication_evaluations": len(pending)
        * EVENT_COUNT
        * REPLICATION_COUNT,
        "wall_seconds": time.perf_counter() - started,
        "free_bytes_before": free_before,
        "free_bytes_after": shutil.disk_usage(REPOSITORY_ROOT).free,
        "ignored_output_bytes": _directory_size(run_dir),
        "scalar_objective_evaluations": 0,
        "candidate_rankings": 0,
        "runtime_adopted": False,
    }
    history_path = run_dir / "run_history.json"
    history = (
        json.loads(history_path.read_text(encoding="utf-8"))
        if history_path.is_file()
        else {"operations": []}
    )
    history["operations"].append(operation)
    search._atomic_json(history_path, history)
    return operation


def _candidate_frame(run_dir: Path) -> pd.DataFrame:
    context = json.loads((Path(run_dir) / "run_context.json").read_text())
    rows = []
    for index in range(CANDIDATE_COUNT):
        payload = validate_partial_candidate_checkpoint(
            run_dir, index, expected_set_id=context["set_id"]
        )
        row: dict[str, Any] = {"candidate_index": index}
        row.update(payload["structural_parameters"])
        for symbol, value in payload["transformed_parameters"].items():
            row[f"transformed_{symbol}"] = value
        for symbol, value in payload["prior_normalised_parameters"].items():
            row[f"z_{symbol}"] = value
        for moment in STAGE2_ACTIVE_MOMENTS:
            result = payload["moment_results"][moment]
            prefix = moment.removesuffix("_mean")
            for name in (
                "simulated_mean",
                "analytic_mcse",
                "raw_mc_lower",
                "raw_mc_upper",
                "adjusted_mc_lower",
                "adjusted_mc_upper",
                "empirical_band_lower",
                "empirical_band_upper",
                "inner_pass",
                "outer_pass",
            ):
                row[f"{prefix}__{name}"] = result[name]
        row.update(payload["hard_gates"])
        row.update(payload["diagnostics"])
        row["candidate_classification"] = payload["candidate_classification"]
        row["result_checksum"] = payload["result_checksum"]
        rows.append(row)
    frame = pd.DataFrame(rows).sort_values(
        "candidate_index", kind="mergesort"
    ).reset_index(drop=True)
    if (
        len(frame) != CANDIDATE_COUNT
        or set(frame["candidate_index"]) != set(range(CANDIDATE_COUNT))
    ):
        raise ValueError("Compact candidate evidence is incomplete.")
    forbidden = {"objective", "rank"}
    if any(
        any(token in column.lower() for token in forbidden)
        for column in frame.columns
    ):
        raise ValueError("Candidate evidence cannot contain an objective or rank.")
    return frame


def _failure_counts(frame: pd.DataFrame) -> dict[str, Any]:
    moment_failures = {}
    for moment in STAGE2_ACTIVE_MOMENTS:
        prefix = moment.removesuffix("_mean")
        moment_failures[moment] = int((~frame[f"{prefix}__outer_pass"].astype(bool)).sum())
    return {
        "by_moment": moment_failures,
        "structural_gate": int((~frame["structural_pass"].astype(bool)).sum()),
        "numerical_bound_gate": int(
            (~frame["numerical_bound_pass"].astype(bool)).sum()
        ),
        "stage1_preservation_gate": int(
            (~frame["stage1_preservation_pass"].astype(bool)).sum()
        ),
    }


def _diagnostic_set_summary(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "candidate_count": int(len(frame)),
        "recovery_completion_censoring": _distribution(
            frame, "right_censoring_share"
        ),
        "recovery_probability_48h": _distribution(
            frame, "recovery_probability_48h"
        ),
        "recovery_probability_168h": _distribution(
            frame, "recovery_probability_168h"
        ),
        "recovery_probability_792h": _distribution(
            frame, "recovery_probability_792h"
        ),
        "failed_recovery_attempts": _distribution(
            frame, "failed_recovery_attempts_mean"
        ),
        "maximum_unresolved_tab_dai": _distribution(
            frame, "maximum_unresolved_tab_dai"
        ),
        "maximum_active_bad_debt_dai": _distribution(
            frame, "maximum_active_bad_debt_dai"
        ),
    }


def _representative_payload(
    frame: pd.DataFrame,
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    records = []
    by_index = frame.set_index("candidate_index")
    for index in selection["representative_indices"]:
        row = by_index.loc[index]
        records.append(
            {
                "candidate_index": int(index),
                "selection_roles": selection["roles"][str(index)],
                "structural_parameters": {
                    name: float(row[name]) for name in PARAMETER_NAMES
                },
                "transformed_parameters": {
                    symbol: float(row[f"transformed_{symbol}"])
                    for symbol in PARAMETER_SYMBOLS
                },
                "prior_normalised_parameters": {
                    symbol: float(row[f"z_{symbol}"])
                    for symbol in PARAMETER_SYMBOLS
                },
                "candidate_classification": str(
                    row["candidate_classification"]
                ),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "robustness_experiment_only",
        "selection_algorithm": (
            "parameter extrema; outer medoid; inner medoid where available; "
            "iterative transformed-space farthest point; lower-index tie-break"
        ),
        "maximum_representatives": MAX_REPRESENTATIVES,
        "representative_count": len(records),
        "representative_indices": selection["representative_indices"],
        "representatives": records,
        "pairwise_distance_summary": selection["pairwise_distance"],
        "coverage_radius": selection["coverage_radius"],
        "representative_checksum": selection["representative_checksum"],
        "objective_values_used": False,
        "moment_centre_distances_used": False,
        "old_candidate_ranks_used": False,
        "candidate_62_preference": False,
        "parameter_estimate": None,
        "runtime_adopted": False,
    }


def _register_evidence(paths: Sequence[Path]) -> None:
    manifest_path = REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = {record["path"]: record for record in manifest["artefacts"]}
    for path in paths:
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        records[relative] = {
            "classification": "snapshot",
            "context": (
                "Finite-grid partial-identification evidence for dormant "
                "persistent-confidence parameters; no estimate or runtime adoption."
            ),
            "path": relative,
            "producer": "dai_sim.calibration.partial_identification",
            "schema": "Compact partial-identification evidence.",
            "semantic_name": path.stem,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "source_inputs": [
                "data/provenance/calibration/confidence/objective_simplification_moments.csv",
                "data/provenance/calibration/confidence/monte_carlo_precision_specification.json",
                "data/provenance/calibration/confidence/sobol_search_specification.json",
            ],
        }
    manifest["artefacts"] = [records[name] for name in sorted(records)]
    search._atomic_bytes(
        manifest_path,
        (
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False)
            + "\n"
        ).encode("utf-8"),
    )


def summarise_partial_identification(
    *,
    root: Path = DEFAULT_ROOT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    cache_dir: Path | None = None,
    register_manifest: bool = True,
) -> dict[str, Any]:
    """Build compact evidence from all 256 validated candidate checkpoints."""
    prepared = prepare_partial_identification(
        root=root, evidence_dir=evidence_dir, cache_dir=cache_dir
    )
    run_dir = Path(prepared["run_directory"])
    candidate_frame = _candidate_frame(run_dir)
    inner = candidate_frame.loc[
        candidate_frame["candidate_classification"].eq("inner_admissible")
    ].copy()
    outer_only = candidate_frame.loc[
        candidate_frame["candidate_classification"].eq("outer_only")
    ].copy()
    outer = pd.concat([inner, outer_only], ignore_index=True).sort_values(
        "candidate_index", kind="mergesort"
    )
    rejected = candidate_frame.loc[
        candidate_frame["candidate_classification"].eq("rejected")
    ].copy()
    set_frames = {
        "inner_admissible": inner,
        "outer_admissible": outer,
        "outer_only": outer_only,
        "rejected": rejected,
    }
    set_summaries = {
        name: summarise_candidate_set(frame) for name, frame in set_frames.items()
    }
    failure_counts = _failure_counts(candidate_frame)
    selection = select_representatives(
        outer,
        inner_indices=set(inner["candidate_index"].astype(int)),
    )
    representatives = _representative_payload(candidate_frame, selection)
    outer_contraction = set_summaries["outer_admissible"][
        "prior_range_contraction"
    ]["by_parameter"]
    classification, next_boundary = classify_partial_identification(
        inner_count=len(inner),
        outer_count=len(outer),
        outer_only_count=len(outer_only),
        outer_contraction=outer_contraction,
        deterministic_evidence_reproduces=True,
        regressions_unchanged=True,
    )
    set_payload = {
        "schema_version": SCHEMA_VERSION,
        "set_id": prepared["set_id"],
        "interpretation": (
            "Grid-supported approximation to a partially identified set; "
            "not a formal asymptotic confidence region."
        ),
        "counts": {
            "inner_admissible": len(inner),
            "outer_admissible": len(outer),
            "outer_only": len(outer_only),
            "rejected": len(rejected),
        },
        "set_summaries": set_summaries,
        "failure_counts": failure_counts,
        "diagnostic_recovery_summaries": {
            name: _diagnostic_set_summary(frame)
            for name, frame in set_frames.items()
        },
        "final_classification": classification,
        "authorised_next_boundary": next_boundary,
        "candidate_probability_interpretation": False,
        "continuous_envelope_interpretation": False,
        "parameter_estimate": None,
        "runtime_adopted": False,
    }
    bands, constraints, stage1 = _constraint_inputs(evidence_dir)
    identity, scientific = partial_identification_identity(
        evidence_dir=evidence_dir, cache_dir=cache_dir
    )
    specification = {
        **scientific,
        "partial_identification_identity": identity,
        "fixed_grid": {
            "candidate_indices": [0, 255],
            "candidate_count": CANDIDATE_COUNT,
            "sobol_checksum": EXPECTED_CANDIDATE_SHA256,
            "grid_refined": False,
        },
        "all_event_design": {
            "events": EVENT_COUNT,
            "replications_per_event_candidate": REPLICATION_COUNT,
            "event_replication_evaluations": (
                CANDIDATE_COUNT * EVENT_COUNT * REPLICATION_COUNT
            ),
            "registry": REGISTRY_A,
            "validation_events_used": False,
        },
        "inner_definition": "all five 90% MC intervals contained in support bands",
        "outer_definition": "all five 90% MC intervals overlap support bands",
        "final_classification_rules": {
            "partial_identification_established": (
                "outer>=16, inner>=4, max outer contraction>=0.25, "
                "outer-only share<=0.50"
            ),
            "weak_partial_identification": (
                "outer>=16 and stronger conditions fail"
            ),
            "sparse_admissible_set": "1<=outer<=15",
            "model_evidence_incompatibility": "outer=0",
            "partial_identification_analysis_invalid": (
                "cache, deterministic, Stage 1, regression or evidence boundary failure"
            ),
        },
        "scalar_objective": None,
        "runtime_adopted": False,
    }
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    search._atomic_json(
        evidence_dir / "partial_identification_specification.json",
        specification,
    )
    search._atomic_csv(
        evidence_dir / "partial_identification_constraints.csv", constraints
    )
    search._atomic_csv(
        evidence_dir / "partial_identification_candidates.csv", candidate_frame
    )
    search._atomic_json(
        evidence_dir / "partial_identification_set.json", set_payload
    )
    search._atomic_json(
        evidence_dir / "partial_identification_representatives.json",
        representatives,
    )
    deterministic_paths = [
        evidence_dir / name
        for name in DETERMINISTIC_EVIDENCE_NAMES
        if name != "partial_identification_reproducibility.json"
    ]
    context = json.loads((run_dir / "run_context.json").read_text())
    checkpoint_checksums = {
        f"{index:03d}": json.loads(
            _candidate_path(run_dir, index).read_text(encoding="utf-8")
        )["result_checksum"]
        for index in range(CANDIDATE_COUNT)
    }
    reproducibility = {
        "schema_version": SCHEMA_VERSION,
        "set_id": identity,
        "source_cache_identity": scientific["cache_identity"],
        "source_cache_manifest_sha256": context[
            "source_cache_manifest_sha256"
        ],
        "evaluated_candidates": CANDIDATE_COUNT,
        "event_count": EVENT_COUNT,
        "replication_count": REPLICATION_COUNT,
        "event_replication_evaluations": (
            CANDIDATE_COUNT * EVENT_COUNT * REPLICATION_COUNT
        ),
        "resume_audit": json.loads(
            (run_dir / "run_history.json").read_text(encoding="utf-8")
        ),
        "candidate_result_checksums": checkpoint_checksums,
        "deterministic_evidence_checksums": {
            path.name: sha256_file(path) for path in deterministic_paths
        },
        "scalar_objective_evaluations": 0,
        "candidate_rankings": 0,
        "top16_created": False,
        "registry_b_used": False,
        "validation_data_used": False,
        "powell_evaluations": 0,
        "usdc_svb_simulations": 0,
        "parameter_selected": False,
        "runtime_adopted": False,
    }
    search._atomic_json(
        evidence_dir / "partial_identification_reproducibility.json",
        reproducibility,
    )
    history = reproducibility["resume_audit"]["operations"]
    wall = float(sum(item["wall_seconds"] for item in history))
    new_evaluations = int(sum(item["event_replication_evaluations"] for item in history))
    ignored_bytes = _directory_size(run_dir)
    benchmark = {
        "schema_version": SCHEMA_VERSION,
        "host_dependent": True,
        "cache_reused": True,
        "new_evaluations": new_evaluations,
        "worker_counts": sorted({int(item["workers"]) for item in history}),
        "wall_time_seconds": wall,
        "throughput_event_replications_per_second": (
            None if wall == 0.0 else new_evaluations / wall
        ),
        "peak_memory_bytes": "not_measured_portably",
        "ignored_output_size_bytes": ignored_bytes,
        "ignored_storage_cap_bytes": MAX_NEW_STORAGE_BYTES,
        "storage_cap_pass": ignored_bytes <= MAX_NEW_STORAGE_BYTES,
        "projected_future_representative_experiments": {
            "representatives": len(
                representatives["representative_indices"]
            ),
            "design_not_yet_authorised_or_executed": True,
        },
        "runtime_adopted": False,
    }
    search._atomic_json(
        evidence_dir / "partial_identification_benchmark.json", benchmark
    )
    tracked = [evidence_dir / name for name in EVIDENCE_NAMES]
    if register_manifest:
        _register_evidence(tracked)
    return {
        "status": classification,
        "set_id": identity,
        "counts": set_payload["counts"],
        "failure_counts": failure_counts,
        "representative_indices": representatives["representative_indices"],
        "representative_checksum": representatives["representative_checksum"],
        "authorised_next_boundary": next_boundary,
        "tracked_evidence": [
            path.relative_to(REPOSITORY_ROOT).as_posix() for path in tracked
        ],
        "candidate_selected": False,
        "runtime_adopted": False,
    }


def validate_partial_identification_evidence(
    *,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> dict[str, Any]:
    """Validate compact evidence and all non-selection boundaries."""
    evidence_dir = Path(evidence_dir)
    manifest = _manifest_records()
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
        raise ValueError(f"Invalid partial-identification evidence: {invalid}.")
    specification = json.loads(
        (evidence_dir / "partial_identification_specification.json").read_text()
    )
    candidates = pd.read_csv(
        evidence_dir / "partial_identification_candidates.csv"
    )
    set_payload = json.loads(
        (evidence_dir / "partial_identification_set.json").read_text()
    )
    representatives = json.loads(
        (evidence_dir / "partial_identification_representatives.json").read_text()
    )
    reproducibility = json.loads(
        (evidence_dir / "partial_identification_reproducibility.json").read_text()
    )
    if (
        len(candidates) != CANDIDATE_COUNT
        or set(candidates["candidate_index"]) != set(range(CANDIDATE_COUNT))
    ):
        raise ValueError("Candidate evidence must contain indices 0–255 once.")
    if any(
        token in column.lower()
        for column in candidates.columns
        for token in ("objective", "rank")
    ):
        raise ValueError("Candidate evidence contains objective or rank fields.")
    if specification["scalar_objective"] is not None:
        raise ValueError("Partial identification cannot contain an objective.")
    if (
        set_payload["parameter_estimate"] is not None
        or representatives["parameter_estimate"] is not None
        or reproducibility["parameter_selected"]
    ):
        raise ValueError("Partial-identification evidence selected a parameter.")
    if (
        reproducibility["top16_created"]
        or reproducibility["registry_b_used"]
        or reproducibility["validation_data_used"]
        or reproducibility["powell_evaluations"]
        or reproducibility["usdc_svb_simulations"]
    ):
        raise ValueError("Blocked calibration work entered partial identification.")
    if any(
        payload.get("runtime_adopted")
        for payload in (
            specification,
            set_payload,
            representatives,
            reproducibility,
        )
    ):
        raise ValueError("Partial-identification evidence cannot be runtime adopted.")
    return {
        "status": "passed",
        "final_classification": set_payload["final_classification"],
        "candidate_count": len(candidates),
        "counts": set_payload["counts"],
        "representative_count": representatives["representative_count"],
        "tracked_evidence_count": len(EVIDENCE_NAMES),
        "candidate_selected": False,
        "runtime_adopted": False,
    }


def run_partial_identification_review(
    *,
    action: str,
    root: Path = DEFAULT_ROOT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    cache_dir: Path | None = None,
    workers: int = 4,
    recover_stale_lock: bool = False,
    register_manifest: bool = True,
) -> dict[str, Any]:
    """Dispatch explicit bounded partial-identification operations."""
    if action == "validate-inputs":
        return prepare_partial_identification(
            root=root, evidence_dir=evidence_dir, cache_dir=cache_dir
        )
    if action == "construct-bands":
        _, constraints, _ = _constraint_inputs(evidence_dir)
        return {
            "status": "passed",
            "constraint_count": len(constraints),
            "constraints": constraints.to_dict(orient="records"),
        }
    if action == "validate-cache":
        source = (
            diagnostic_directory(evidence_dir=evidence_dir)
            if cache_dir is None
            else Path(cache_dir)
        )
        return validate_diagnostic_cache(source, horizon=PRIMARY_HORIZON)
    if action in {"run-grid", "resume-grid"}:
        return run_partial_identification_grid(
            root=root,
            evidence_dir=evidence_dir,
            cache_dir=cache_dir,
            workers=workers,
            resume=action == "resume-grid",
            recover_stale_lock=recover_stale_lock,
        )
    if action in {
        "summarise-sets",
        "select-representatives",
        "reconstruct-evidence",
    }:
        return summarise_partial_identification(
            root=root,
            evidence_dir=evidence_dir,
            cache_dir=cache_dir,
            register_manifest=register_manifest,
        )
    if action == "validate":
        return validate_partial_identification_evidence(
            evidence_dir=evidence_dir
        )
    raise ValueError(f"Unsupported partial-identification action: {action}.")
