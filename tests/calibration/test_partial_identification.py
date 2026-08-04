"""Tests for finite-grid partial identification of dormant confidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dai_sim.calibration import partial_identification as partial
from dai_sim.calibration.simulated_moments import STAGE2_ACTIVE_MOMENTS
from dai_sim.calibration.simulated_moments_search import payload_sha256


def _moment_flags(*, inner: bool = True, outer: bool = True):
    return {
        name: {"inner_pass": inner, "outer_pass": outer}
        for name in STAGE2_ACTIVE_MOMENTS
    }


def _candidate_frame(count: int = 32) -> pd.DataFrame:
    rows = []
    for index in range(count):
        unit = np.array(
            [
                index / max(1, count - 1),
                ((index * 7) % count) / max(1, count - 1),
                ((index * 11) % count) / max(1, count - 1),
                ((index * 13) % count) / max(1, count - 1),
            ]
        )
        row = {
            "candidate_index": index,
            "price_bound_share": index / 10_000,
            "right_censoring_share": index / 100,
        }
        for moment in STAGE2_ACTIVE_MOMENTS:
            prefix = moment.removesuffix("_mean")
            row[f"{prefix}__inner_pass"] = index % 2 == 0
            row[f"{prefix}__outer_pass"] = index % 4 != 0
        for name, symbol, value in zip(
            partial.PARAMETER_NAMES,
            partial.PARAMETER_SYMBOLS,
            unit,
            strict=True,
        ):
            row[name] = float(value)
            row[f"z_{symbol}"] = float(value)
            row[f"transformed_{symbol}"] = float(value)
        rows.append(row)
    return pd.DataFrame(rows)


def test_support_band_is_exact_registered_plus_minus_two_scales() -> None:
    result = partial.construct_support_band(
        moment="burden",
        empirical_value=0.10,
        empirical_scale=0.08,
        natural_support=(0.0, 1.0),
    )
    assert result.raw_lower == pytest.approx(-0.06)
    assert result.raw_upper == pytest.approx(0.26)
    assert result.adjusted_lower == 0.0
    assert result.adjusted_upper == pytest.approx(0.26)


def test_support_multiplier_cannot_change_after_results() -> None:
    with pytest.raises(ValueError, match="fixed at 2"):
        partial.construct_support_band(
            moment="burden",
            empirical_value=0.1,
            empirical_scale=0.01,
            multiplier=3.0,
        )


def test_registered_constraint_rows_retain_owned_order_and_values() -> None:
    bands, constraints, stage1 = partial._constraint_inputs()
    assert tuple(constraints["moment"]) == STAGE2_ACTIVE_MOMENTS
    assert tuple(bands) == STAGE2_ACTIVE_MOMENTS
    assert tuple(stage1.index) == partial.STAGE1_PRESERVATION_MOMENTS
    assert (constraints["support_multiplier"] == 2.0).all()
    assert (constraints["mc_interval_critical_value"] == 1.645).all()


def test_mc_interval_is_exact_90_percent_and_support_clipped() -> None:
    result = partial.construct_mc_interval(
        estimate=0.005,
        mcse=0.01,
        natural_support=(0.0, None),
    )
    assert result.raw_lower == pytest.approx(0.005 - 1.645 * 0.01)
    assert result.raw_upper == pytest.approx(0.005 + 1.645 * 0.01)
    assert result.adjusted_lower == 0.0


def test_zero_mcse_produces_point_interval() -> None:
    result = partial.construct_mc_interval(estimate=2.0, mcse=0.0)
    assert result.adjusted_lower == result.adjusted_upper == 2.0


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_non_finite_mc_inputs_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        partial.construct_mc_interval(estimate=value, mcse=1.0)


def test_moment_classification_distinguishes_inner_outer_and_fail() -> None:
    band = partial.construct_support_band(
        moment="x", empirical_value=1.0, empirical_scale=0.1
    )
    inner = partial.construct_mc_interval(estimate=1.0, mcse=0.01)
    outer = partial.construct_mc_interval(estimate=1.2, mcse=0.02)
    fail = partial.construct_mc_interval(estimate=1.5, mcse=0.01)
    assert partial.classify_moment(inner, band)["classification"] == "inner_pass"
    assert partial.classify_moment(outer, band)["classification"] == "outer_pass"
    assert partial.classify_moment(fail, band)["classification"] == "fail"
    assert partial.classify_moment(inner, band)["outer_pass"]


def test_candidate_classification_applies_all_hard_gates() -> None:
    assert (
        partial.classify_candidate(
            moment_results=_moment_flags(),
            structural_pass=True,
            numerical_bound_pass=True,
            stage1_preservation_pass=True,
        )
        == "inner_admissible"
    )
    flags = _moment_flags(inner=False, outer=True)
    assert (
        partial.classify_candidate(
            moment_results=flags,
            structural_pass=True,
            numerical_bound_pass=True,
            stage1_preservation_pass=True,
        )
        == "outer_only"
    )
    assert (
        partial.classify_candidate(
            moment_results=flags,
            structural_pass=False,
            numerical_bound_pass=True,
            stage1_preservation_pass=True,
        )
        == "rejected"
    )


@pytest.mark.parametrize(
    ("numerical_bound_pass", "stage1_preservation_pass"),
    [(False, True), (True, False)],
)
def test_candidate_classification_enforces_other_hard_gates(
    numerical_bound_pass: bool,
    stage1_preservation_pass: bool,
) -> None:
    assert (
        partial.classify_candidate(
            moment_results=_moment_flags(),
            structural_pass=True,
            numerical_bound_pass=numerical_bound_pass,
            stage1_preservation_pass=stage1_preservation_pass,
        )
        == "rejected"
    )


def test_set_summary_reports_grid_envelope_and_contraction() -> None:
    frame = _candidate_frame(20)
    summary = partial.summarise_candidate_set(frame, total_candidates=256)
    assert summary["candidate_count"] == 20
    assert summary["candidate_fraction"] == pytest.approx(20 / 256)
    assert "Finite-grid" in summary["grid_envelope_warning"]
    assert set(summary["prior_range_contraction"]["by_parameter"]) == set(
        partial.PARAMETER_SYMBOLS
    )
    assert summary["failure_reason_counts_by_moment"][
        "first_six_hour_burden_mean"
    ] == {"inner_failures": 10, "outer_failures": 5}
    assert summary["parameter_summary"]["alpha_d"]["median"] == pytest.approx(0.5)
    assert len(summary["pairwise_feasible_ranges"]) == 6
    assert summary["pairwise_rank_correlations"]["alpha_d"]["alpha_d"] == 1.0
    assert summary["parameter_summary"]["alpha_d"][
        "lower_boundary_occupancy"
    ] > 0.0


def test_representatives_include_extrema_medoids_and_are_bounded() -> None:
    frame = _candidate_frame(32)
    result = partial.select_representatives(
        frame, inner_indices={3, 4, 5, 6}, maximum=24
    )
    assert len(result["representative_indices"]) == 24
    roles = [role for values in result["roles"].values() for role in values]
    assert "outer_medoid" in roles
    assert "inner_medoid" in roles
    for symbol in partial.PARAMETER_SYMBOLS:
        assert f"minimum_{symbol}" in roles
        assert f"maximum_{symbol}" in roles
    assert len(result["representative_checksum"]) == 64


def test_representative_selection_is_order_independent() -> None:
    frame = _candidate_frame(30)
    first = partial.select_representatives(frame, maximum=12)
    second = partial.select_representatives(
        frame.sample(frac=1.0, random_state=1), maximum=12
    )
    assert first["representative_indices"] == second["representative_indices"]
    assert first["representative_checksum"] == second["representative_checksum"]


def test_representative_ties_break_on_lower_candidate_index() -> None:
    frame = _candidate_frame(3)
    frame.loc[:, [f"z_{name}" for name in partial.PARAMETER_SYMBOLS]] = [
        [0.0] * 4,
        [0.5] * 4,
        [1.0] * 4,
    ]
    result = partial.select_representatives(frame, maximum=3)
    assert result["representative_indices"] == [0, 2, 1]


def test_empty_outer_set_produces_no_representative_or_preference() -> None:
    result = partial.select_representatives(_candidate_frame(0), maximum=24)
    assert result["representative_indices"] == []
    assert result["coverage_radius"] is None
    assert result["representative_checksum"] == hashlib.sha256(b"[]").hexdigest()


@pytest.mark.parametrize(
    ("inner", "outer", "outer_only", "contraction", "expected"),
    [
        (4, 20, 8, {"alpha_d": 0.30}, "partial_identification_established"),
        (1, 20, 19, {"alpha_d": 0.30}, "weak_partial_identification"),
        (1, 8, 7, {"alpha_d": 0.30}, "sparse_admissible_set"),
        (0, 0, 0, {"alpha_d": None}, "model_evidence_incompatibility"),
    ],
)
def test_final_classification_hierarchy(
    inner: int,
    outer: int,
    outer_only: int,
    contraction: dict[str, float | None],
    expected: str,
) -> None:
    classification, _ = partial.classify_partial_identification(
        inner_count=inner,
        outer_count=outer,
        outer_only_count=outer_only,
        outer_contraction=contraction,
        deterministic_evidence_reproduces=True,
        regressions_unchanged=True,
    )
    assert classification == expected


def test_invalid_reproducibility_overrides_set_counts() -> None:
    classification, _ = partial.classify_partial_identification(
        inner_count=20,
        outer_count=30,
        outer_only_count=10,
        outer_contraction={"alpha_d": 0.5},
        deterministic_evidence_reproduces=False,
        regressions_unchanged=True,
    )
    assert classification == "partial_identification_analysis_invalid"


def test_checkpoint_identity_and_checksum_are_enforced(tmp_path: Path) -> None:
    deterministic = {
        "schema_version": partial.CANDIDATE_SCHEMA,
        "set_id": "fixed",
        "candidate_index": 0,
        "event_count": partial.EVENT_COUNT,
        "replication_count": partial.REPLICATION_COUNT,
        "event_replication_count": partial.EVENT_COUNT * partial.REPLICATION_COUNT,
        "event_sufficient_statistics": [
            {"event_id": str(index)} for index in range(partial.EVENT_COUNT)
        ],
        "scalar_objective_calculated": False,
        "candidate_rank_calculated": False,
    }
    payload = {
        **deterministic,
        "result_checksum": payload_sha256(deterministic),
        "execution_duration_seconds": 1.0,
    }
    path = tmp_path / "candidates" / "candidate_000.json"
    path.parent.mkdir()
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = partial.validate_partial_candidate_checkpoint(
        tmp_path, 0, expected_set_id="fixed"
    )
    assert result["candidate_index"] == 0
    with pytest.raises(ValueError, match="identity differs"):
        partial.validate_partial_candidate_checkpoint(
            tmp_path, 0, expected_set_id="other"
        )
    payload["result_checksum"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum differs"):
        partial.validate_partial_candidate_checkpoint(
            tmp_path, 0, expected_set_id="fixed"
        )


def test_scientific_identity_excludes_output_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benchmark = json.loads(
        (
            partial.CONFIDENCE_EVIDENCE
            / "monte_carlo_precision_benchmark.json"
        ).read_text(encoding="utf-8")
    )
    registered_cache = {
        "event_count": partial.EVENT_COUNT,
        "cache_root_sha256": benchmark["primary_cache_root_sha256"],
        "package_count": benchmark["primary_cache_packages"],
    }
    monkeypatch.setattr(
        partial,
        "validate_diagnostic_cache",
        lambda *_args, **_kwargs: registered_cache,
    )
    registered_identity = json.loads(
        (
            partial.CONFIDENCE_EVIDENCE
            / "partial_identification_reproducibility.json"
        ).read_text(encoding="utf-8")
    )["set_id"]
    first, _ = partial.partial_identification_identity()
    second = partial.partial_identification_directory(root=tmp_path / "one").name
    third = partial.partial_identification_directory(root=tmp_path / "two").name
    assert first == second == third == registered_identity
