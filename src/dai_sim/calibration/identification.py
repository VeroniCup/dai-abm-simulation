"""Objective-blind numerical-identification primitives for confidence SMM.

The functions here are design and diagnostic infrastructure only.  They do
not rank candidates, calculate objective fit, optimise parameters or adopt a
runtime configuration.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np


PRIMARY_STEP = 0.05
SENSITIVITY_STEP = 0.025
PROFILE_GRID = (0.10, 0.30, 0.50, 0.70, 0.90)
INTERIOR_LOWER = 0.15
INTERIOR_UPPER = 0.85
CONDITION_LIMIT = 1_000.0
SINGULAR_RATIO_MINIMUM = 1e-3
COLUMN_COSINE_LIMIT = 0.995
DERIVATIVE_SNR_MINIMUM = 2.0


def _canonical_sha256(payload: Any) -> str:
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def select_objective_blind_anchors(
    unit_coordinates: np.ndarray,
    *,
    candidate_indices: Sequence[int] | None = None,
    count: int = 5,
) -> dict[str, Any]:
    """Select centre-nearest then farthest-point interior Sobol anchors."""
    coordinates = np.asarray(unit_coordinates, dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] != 4:
        raise ValueError("Anchor coordinates must have shape (n, 4).")
    if not np.isfinite(coordinates).all():
        raise ValueError("Anchor coordinates must be finite.")
    indices = (
        np.arange(len(coordinates), dtype=int)
        if candidate_indices is None
        else np.asarray(candidate_indices, dtype=int)
    )
    if indices.shape != (len(coordinates),) or len(set(indices.tolist())) != len(indices):
        raise ValueError("Candidate indices must be unique and align with coordinates.")
    eligible_mask = np.logical_and(
        coordinates >= INTERIOR_LOWER,
        coordinates <= INTERIOR_UPPER,
    ).all(axis=1)
    eligible_positions = np.flatnonzero(eligible_mask)
    if len(eligible_positions) < count:
        raise ValueError("Insufficient central-difference-eligible anchors.")
    centre = np.full(4, 0.5)
    centre_distances = np.linalg.norm(
        coordinates[eligible_positions] - centre, axis=1
    )
    minimum = float(centre_distances.min())
    central_options = eligible_positions[
        np.isclose(centre_distances, minimum, rtol=0.0, atol=1e-15)
    ]
    selected = [
        int(min(central_options, key=lambda position: int(indices[position])))
    ]
    while len(selected) < count:
        remaining = [
            int(position)
            for position in eligible_positions
            if int(position) not in selected
        ]
        minimum_distances = {
            position: min(
                float(np.linalg.norm(coordinates[position] - coordinates[prior]))
                for prior in selected
            )
            for position in remaining
        }
        maximum = max(minimum_distances.values())
        options = [
            position
            for position, distance in minimum_distances.items()
            if math.isclose(distance, maximum, rel_tol=0.0, abs_tol=1e-15)
        ]
        selected.append(min(options, key=lambda position: int(indices[position])))
    selected_indices = [int(indices[position]) for position in selected]
    selected_coordinates = coordinates[selected]
    pairwise = [
        {
            "left": selected_indices[left],
            "right": selected_indices[right],
            "distance": float(
                np.linalg.norm(
                    selected_coordinates[left] - selected_coordinates[right]
                )
            ),
        }
        for left in range(count)
        for right in range(left + 1, count)
    ]
    payload = {
        "candidate_indices": selected_indices,
        "unit_coordinates": selected_coordinates.tolist(),
        "algorithm": (
            "interior [0.15,0.85]; nearest to centre; iterative maximum "
            "minimum Euclidean distance; lower candidate-index tie-break"
        ),
    }
    return {
        **payload,
        "pairwise_distances": pairwise,
        "anchor_checksum": _canonical_sha256(payload),
        "objective_values_used": False,
    }


def paired_central_derivative(
    plus: Sequence[float],
    minus: Sequence[float],
    *,
    step: float,
    scale: float,
) -> dict[str, float]:
    """Estimate one standardised derivative using paired common random numbers."""
    positive = np.asarray(plus, dtype=float)
    negative = np.asarray(minus, dtype=float)
    if positive.shape != negative.shape or positive.ndim != 1 or len(positive) < 2:
        raise ValueError("Paired derivative samples must be aligned one-dimensional arrays.")
    if not np.isfinite(np.concatenate((positive, negative))).all():
        raise ValueError("Paired derivative samples must be finite.")
    if step <= 0.0 or scale <= 0.0:
        raise ValueError("Finite-difference step and empirical scale must be positive.")
    paired = (positive - negative) / (2.0 * step * scale)
    estimate = float(paired.mean())
    mcse = float(paired.std(ddof=1) / math.sqrt(len(paired)))
    snr = math.inf if mcse == 0.0 and estimate != 0.0 else (
        0.0 if mcse == 0.0 else abs(estimate) / mcse
    )
    return {
        "derivative": estimate,
        "derivative_mcse": mcse,
        "snr": float(snr),
        "sign": float(np.sign(estimate)),
        "replication_count": int(len(paired)),
    }


def central_difference_jacobian(
    plus: np.ndarray,
    minus: np.ndarray,
    *,
    scales: Sequence[float],
    step: float,
) -> np.ndarray:
    """Construct an m-by-p standardised central-difference Jacobian."""
    positive = np.asarray(plus, dtype=float)
    negative = np.asarray(minus, dtype=float)
    scale_array = np.asarray(scales, dtype=float)
    if positive.shape != negative.shape or positive.ndim != 2:
        raise ValueError("Plus and minus moment matrices must share shape (m, p).")
    if scale_array.shape != (positive.shape[0],):
        raise ValueError("One empirical scale is required per moment.")
    if step <= 0.0 or np.any(scale_array <= 0.0):
        raise ValueError("Step and scales must be positive.")
    if not np.isfinite(np.concatenate((positive.ravel(), negative.ravel()))).all():
        raise ValueError("Finite-difference moments must be finite.")
    return (positive - negative) / (2.0 * step * scale_array[:, None])


def _column_cosines(matrix: np.ndarray) -> dict[str, float]:
    result: dict[str, float] = {}
    for left in range(matrix.shape[1]):
        for right in range(left + 1, matrix.shape[1]):
            denominator = np.linalg.norm(matrix[:, left]) * np.linalg.norm(
                matrix[:, right]
            )
            cosine = (
                float(np.dot(matrix[:, left], matrix[:, right]) / denominator)
                if denominator
                else math.nan
            )
            result[f"{left}:{right}"] = cosine
    return result


def jacobian_diagnostics(
    matrix: np.ndarray,
    *,
    derivative_snrs: np.ndarray | None = None,
    required_rank: int | None = None,
) -> dict[str, Any]:
    """Calculate fixed rank, conditioning, collinearity and signal gates."""
    values = np.asarray(matrix, dtype=float)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("The Jacobian must be a finite two-dimensional array.")
    target_rank = values.shape[1] if required_rank is None else required_rank
    singular_values = np.linalg.svd(values, compute_uv=False)
    rank = int(np.linalg.matrix_rank(values))
    largest = float(singular_values[0]) if len(singular_values) else 0.0
    smallest = float(singular_values[-1]) if len(singular_values) else 0.0
    ratio = 0.0 if largest == 0.0 else smallest / largest
    condition = math.inf if smallest == 0.0 else largest / smallest
    cosines = _column_cosines(values)
    maximum_cosine = max(
        (abs(value) for value in cosines.values() if math.isfinite(value)),
        default=math.inf,
    )
    if derivative_snrs is None:
        signal = [True] * values.shape[1]
    else:
        snrs = np.asarray(derivative_snrs, dtype=float)
        if snrs.shape != values.shape:
            raise ValueError("Derivative SNRs must align with the Jacobian.")
        signal = [
            bool(np.any(snrs[:, parameter] >= DERIVATIVE_SNR_MINIMUM))
            for parameter in range(values.shape[1])
        ]
    passed = bool(
        rank == target_rank
        and condition <= CONDITION_LIMIT
        and ratio >= SINGULAR_RATIO_MINIMUM
        and maximum_cosine <= COLUMN_COSINE_LIMIT
        and all(signal)
    )
    return {
        "rank": rank,
        "required_rank": target_rank,
        "singular_values": [float(value) for value in singular_values],
        "condition_number": float(condition),
        "singular_value_ratio": float(ratio),
        "column_norms": [
            float(np.linalg.norm(values[:, column]))
            for column in range(values.shape[1])
        ],
        "column_cosines": cosines,
        "maximum_absolute_column_cosine": float(maximum_cosine),
        "parameter_signal": signal,
        "pass": passed,
    }


def stacked_global_jacobian(
    local_jacobians: Sequence[np.ndarray],
) -> np.ndarray:
    """Stack five local Jacobians using the pre-registered 1/sqrt(5) scale."""
    matrices = [np.asarray(matrix, dtype=float) for matrix in local_jacobians]
    if len(matrices) != 5 or len({matrix.shape for matrix in matrices}) != 1:
        raise ValueError("Exactly five equally shaped local Jacobians are required.")
    return np.vstack(matrices) / math.sqrt(5.0)


def step_size_stability(
    primary: np.ndarray,
    sensitivity: np.ndarray,
) -> dict[str, Any]:
    """Compare h=0.05 and h=0.025 without selecting the better result."""
    first = np.asarray(primary, dtype=float)
    second = np.asarray(sensitivity, dtype=float)
    if first.shape != second.shape or first.ndim != 2:
        raise ValueError("Step-size Jacobians must have the same matrix shape.")
    column_cosines = []
    for column in range(first.shape[1]):
        denominator = np.linalg.norm(first[:, column]) * np.linalg.norm(
            second[:, column]
        )
        column_cosines.append(
            float(np.dot(first[:, column], second[:, column]) / denominator)
            if denominator
            else math.nan
        )
    singular_first = np.linalg.svd(first, compute_uv=False)
    singular_second = np.linalg.svd(second, compute_uv=False)
    denominator = np.maximum(np.abs(singular_first), np.finfo(float).eps)
    differences = np.abs(singular_second - singular_first) / denominator
    rank_unchanged = np.linalg.matrix_rank(first) == np.linalg.matrix_rank(second)
    passed = bool(
        all(math.isfinite(value) and value >= 0.90 for value in column_cosines)
        and np.all(differences <= 0.25)
        and rank_unchanged
    )
    return {
        "column_cosines": column_cosines,
        "singular_value_relative_differences": differences.tolist(),
        "rank_unchanged": bool(rank_unchanged),
        "pass": passed,
    }


def classify_parameter_profile(
    moment_values: Sequence[float],
    *,
    empirical_scale: float,
    paired_endpoint_mcse: float,
) -> dict[str, Any]:
    """Classify one active-moment profile using the fixed endpoint rule."""
    values = np.asarray(moment_values, dtype=float)
    if values.shape != (5,) or not np.isfinite(values).all():
        raise ValueError("A profile must contain five finite grid values.")
    if empirical_scale <= 0.0 or paired_endpoint_mcse < 0.0:
        raise ValueError("Profile scale must be positive and MCSE non-negative.")
    movement = float(abs(values[-1] - values[0]))
    threshold = 0.5 * empirical_scale
    precise = bool(
        movement > 0.0 and paired_endpoint_mcse <= 0.25 * movement
    )
    return {
        "endpoint_movement": movement,
        "movement_threshold": threshold,
        "paired_endpoint_mcse": float(paired_endpoint_mcse),
        "non_flat": bool(movement >= threshold and precise),
        "flat": bool(movement < threshold),
        "monotonic_non_decreasing": bool(np.all(np.diff(values) >= 0.0)),
        "monotonic_non_increasing": bool(np.all(np.diff(values) <= 0.0)),
    }


def permitted_restriction(
    *,
    flat_parameters: Sequence[str],
    signal_failures: Sequence[str],
    decisive_collinear_pair: tuple[str, str] | None,
) -> str:
    """Apply the fixed restricted-model hierarchy without objective fit."""
    unsupported = set(flat_parameters) | set(signal_failures)
    if "panic_response" in unsupported:
        return "panic_response_zero"
    if "confidence_floor" in unsupported:
        return "confidence_floor_requires_independent_identification"
    if decisive_collinear_pair is not None and set(decisive_collinear_pair) == {
        "deterioration_adjustment",
        "recovery_adjustment",
    }:
        return "equal_deterioration_and_recovery_adjustment"
    return "identification_unresolved"
