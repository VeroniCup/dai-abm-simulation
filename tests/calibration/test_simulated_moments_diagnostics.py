"""Tests for the pre-registered Monte Carlo precision diagnosis."""

from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dai_sim.calibration.simulated_moments_diagnostics import (
    AGREEMENT_TOLERANCE,
    HORIZON_ONE,
    HORIZON_TWO,
    LADDER_REPLICATIONS,
    PANEL_SIZE,
    PRIMARY_HORIZON,
    SEARCH_ROOT,
    analytic_contrast_mcse,
    analytic_equal_event_mcse,
    audit_completed_search,
    censoring_imbalance,
    classify_recovery_censoring,
    convergence_slope,
    kaplan_meier_curve,
    next_power_of_two,
    objective_blind_candidate_panel,
    paired_difference_precision,
    projected_required_replications,
    quartile_event_sets,
    recovery_empirical_evidence,
    _recovery_replacement_decision,
)


def _records(
    event_values: dict[str, list[float]],
    *,
    outcome: str = "outcome",
) -> pd.DataFrame:
    rows = []
    for event_id, values in event_values.items():
        for replication, value in enumerate(values):
            rows.append(
                {
                    "event_id": event_id,
                    "replication": replication,
                    outcome: value,
                }
            )
    return pd.DataFrame(rows)


def test_analytic_equal_event_formula_excludes_between_event_heterogeneity() -> None:
    frame = _records({"a": [0.0, 2.0], "b": [100.0, 102.0]})
    result = analytic_equal_event_mcse(frame, outcome="outcome")
    expected_variance = (2.0 / 2 / 4) + (2.0 / 2 / 4)
    assert result.point_estimate == pytest.approx(51.0)
    assert result.total_mc_variance == pytest.approx(expected_variance)
    assert result.analytic_mcse == pytest.approx(math.sqrt(expected_variance))
    shifted = _records({"a": [0.0, 2.0], "b": [10_000.0, 10_002.0]})
    shifted_result = analytic_equal_event_mcse(shifted, outcome="outcome")
    assert shifted_result.analytic_mcse == result.analytic_mcse


def test_analytic_contrast_formula_handles_unequal_event_counts() -> None:
    values = {
        "a": [0.0, 2.0, 4.0, 6.0],
        "b": [1.0, 3.0, 5.0, 7.0],
        "c": [2.0, 4.0, 6.0, 8.0],
        "d": [3.0, 5.0, 7.0, 9.0],
        "e": [4.0, 6.0, 8.0, 10.0],
    }
    frame = _records(values)
    strata = {"a": 0.0, "b": 1.0, "c": 2.0, "d": 3.0, "e": 4.0}
    frame["stratifier"] = frame["event_id"].map(strata)
    low, high = quartile_event_sets(frame, stratifier="stratifier")
    result = analytic_contrast_mcse(
        frame, outcome="outcome", stratifier="stratifier"
    )
    assert low
    assert high
    assert result.event_count == len(low) + len(high)
    assert result.analytic_mcse > 0.0


def test_replication_index_agrees_on_synthetic_independent_streams() -> None:
    rng = np.random.default_rng(20260729)
    values = {
        f"e{event:02d}": rng.normal(event, 1.0, 4096).tolist()
        for event in range(8)
    }
    result = analytic_equal_event_mcse(_records(values), outcome="outcome")
    assert result.relative_disagreement <= AGREEMENT_TOLERANCE
    assert result.agreement_pass


def test_zero_within_event_variance_has_zero_mcse() -> None:
    result = analytic_equal_event_mcse(
        _records({"a": [1.0] * 8, "b": [9.0] * 8}),
        outcome="outcome",
    )
    assert result.analytic_mcse == 0.0
    assert result.replication_index_mcse == 0.0


@pytest.mark.parametrize(
    "values",
    [
        {"a": [1.0, 2.0], "b": [1.0]},
        {"a": [1.0, np.nan], "b": [1.0, 2.0]},
    ],
)
def test_missing_or_unequal_replications_are_rejected(
    values: dict[str, list[float]],
) -> None:
    with pytest.raises(ValueError):
        analytic_equal_event_mcse(_records(values), outcome="outcome")


def test_right_censored_values_are_used_at_fixed_numeric_duration() -> None:
    frame = _records({"a": [792.0, 792.0], "b": [100.0, 200.0]})
    result = analytic_equal_event_mcse(frame, outcome="outcome")
    assert result.point_estimate == pytest.approx((792.0 + 150.0) / 2)


def test_objective_blind_panel_is_exact_and_contains_no_fit_fields() -> None:
    panel = objective_blind_candidate_panel()
    assert panel["candidate_count"] == PANEL_SIZE
    assert panel["candidate_indices"] == [
        0,
        94,
        171,
        42,
        193,
        100,
        116,
        127,
        36,
        252,
        222,
        97,
        134,
        103,
        203,
        126,
    ]
    assert panel["panel_checksum"] == (
        "7ca9475da16b6e2a971d8adfe8bda6714c0841191e596e45d51bbcf2a26108f9"
    )
    assert all(
        set(candidate)
        == {"candidate_index", "transformed_vector", "structural_vector"}
        for candidate in panel["candidates"]
    )
    assert not any(
        "objective" in candidate or "validation" in candidate
        for candidate in panel["candidates"]
    )
    assert not panel["candidate_selection_performed"]


def test_candidate_panel_lower_index_tie_break_is_stable() -> None:
    first = objective_blind_candidate_panel()
    second = objective_blind_candidate_panel()
    assert first == second
    assert first["candidate_indices"][0] == 0


def test_replication_ladder_and_horizons_are_fixed() -> None:
    assert LADDER_REPLICATIONS == (32, 64, 128, 256)
    assert PRIMARY_HORIZON == 792
    assert HORIZON_ONE == 1_584
    assert HORIZON_TWO == 2_376


@pytest.mark.parametrize(
    ("slope_values", "expected"),
    [
        ([1.0, 2**-0.5, 4**-0.5, 8**-0.5], "regular_convergence"),
        ([1.0, 0.9, 0.8, 0.7], "slow_or_unstable_convergence"),
        ([1.0, 0.4, 0.16, 0.064], "faster_than_expected_or_floor_effect"),
    ],
)
def test_convergence_classification(
    slope_values: list[float],
    expected: str,
) -> None:
    _, classification = convergence_slope(
        LADDER_REPLICATIONS, slope_values
    )
    assert classification == expected


def test_required_replication_rounding_and_cap() -> None:
    assert next_power_of_two(257.0) == 512
    assert (
        projected_required_replications(
            replication_count=256,
            mcse=1.0,
            threshold=0.5,
            convergence_classification="regular_convergence",
        )
        == 1024
    )
    assert (
        projected_required_replications(
            replication_count=256,
            mcse=10.0,
            threshold=0.1,
            convergence_classification="regular_convergence",
        )
        == ">8192"
    )
    assert (
        projected_required_replications(
            replication_count=256,
            mcse=1.0,
            threshold=0.5,
            convergence_classification="slow_or_unstable_convergence",
        )
        is None
    )


@pytest.mark.parametrize(
    ("censored", "h1", "h2", "expected"),
    [
        (100, 51, 60, "mainly_administrative_censoring"),
        (100, 25, 40, "mixed_administrative_and_structural_censoring"),
        (100, 5, 9, "predominantly_structural_non_recovery"),
    ],
)
def test_censoring_classification(
    censored: int,
    h1: int,
    h2: int,
    expected: str,
) -> None:
    assert (
        classify_recovery_censoring(
            censored_at_h0=censored,
            recovered_by_h1=h1,
            recovered_by_h2=h2,
        )
        == expected
    )


def test_censoring_imbalance_uses_registered_rules() -> None:
    assert censoring_imbalance(0.10, 0.21)["material"]
    assert censoring_imbalance(0.05, 0.11)["material"]
    assert not censoring_imbalance(0.20, 0.25)["material"]


def test_kaplan_meier_curve_keeps_censoring_distinct_from_recovery() -> None:
    curve = kaplan_meier_curve(
        [2.0, 2.0, 4.0, 6.0],
        [True, False, True, False],
    )
    assert curve["duration"].tolist() == [2.0, 4.0, 6.0]
    assert curve["recovered"].tolist() == [1, 1, 0]
    assert curve["censored"].tolist() == [1, 0, 1]
    assert curve["survival_probability"].tolist() == pytest.approx(
        [0.75, 0.375, 0.375]
    )


def test_paired_difference_preserves_absolute_gate_boundary() -> None:
    left = _records({"a": [1.0, 2.0, 3.0, 4.0]})
    right = _records({"a": [2.0, 3.0, 4.0, 5.0]})
    result = paired_difference_precision(left, right, outcome="outcome")
    assert result["paired_difference_mcse"] == 0.0
    assert result["unpaired_mcse"] > 0.0
    assert not result["absolute_mcse_gate_replaced"]


def test_completed_estimator_audit_preserves_negative_eligibility() -> None:
    audit = audit_completed_search(SEARCH_ROOT)
    assert audit["existing_estimator_classification"] == (
        "correct_hierarchical_mcse"
    )
    assert audit["existing_replication_index_values_reproduced"]
    assert audit["committed_failure_reproduction"] == {
        "candidate_count": 256,
        "structural_valid": 256,
        "objective_valid": 256,
        "numerical_bound_valid": 53,
        "mcse_valid": 0,
        "next_stage_eligible": 0,
    }
    implication = audit["search_eligibility_implication"]
    assert implication["committed_mcse_valid_candidates"] == 0
    assert implication["audited_mcse_valid_candidates"] == 0
    assert not implication["eligibility_result_changes"]


def test_committed_top16_remains_empty() -> None:
    path = Path(
        "data/provenance/calibration/confidence/sobol_search_top16.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["candidates"] == []
    assert payload["status"] == "insufficient_valid_candidates"
    assert not payload["runtime_adopted"]


def test_compact_precision_evidence_preserves_registered_boundary() -> None:
    root = Path("data/provenance/calibration/confidence")
    specification = json.loads(
        (root / "monte_carlo_precision_specification.json").read_text()
    )
    decision = json.loads(
        (root / "monte_carlo_precision_decision.json").read_text()
    )
    censoring = json.loads(
        (root / "recovery_censoring_diagnosis.json").read_text()
    )
    assert specification["replication_ladder"] == [32, 64, 128, 256]
    assert specification["threshold_rule"] == "0.10 * registered empirical scale"
    assert not specification["parameter_selection_performed"]
    assert not specification["runtime_adopted"]
    assert decision["final_diagnosis_classification"] == (
        "recovery_moment_not_operationally_identifiable"
    )
    assert not decision["candidate_selected"]
    assert not censoring["core_moment_replaced"]
    assert not censoring["final_validation_used"]
    assert len(
        censoring["primary_horizon_audit"]["candidate_replication_rows"]
    ) == 64
    assert censoring["primary_horizon_audit"]["numeric_censoring_sentinel"] == 743.0
    assert censoring["survival_aware_diagnostics"]["curve_method"].startswith(
        "Kaplan-Meier"
    )


def test_precision_evidence_manifest_checksums_are_exact() -> None:
    root = Path("data/provenance/calibration/confidence")
    names = {
        "monte_carlo_precision_specification.json",
        "monte_carlo_estimator_audit.json",
        "monte_carlo_candidate_panel.json",
        "monte_carlo_replication_ladder.csv",
        "recovery_censoring_diagnosis.json",
        "monte_carlo_precision_decision.json",
        "monte_carlo_precision_benchmark.json",
    }
    manifest = json.loads(
        Path("data/provenance/calibration/manifest.json").read_text()
    )
    records = {Path(item["path"]).name: item for item in manifest["artefacts"]}
    assert names <= set(records)
    for name in names:
        path = root / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == records[name]["sha256"]


def test_recovery_empirical_evidence_uses_fixed_stratified_bootstrap() -> None:
    catalogue = pd.read_csv(
        "data/provenance/calibration/confidence/event_catalogue.csv"
    )
    evidence, first, influence = recovery_empirical_evidence(catalogue)
    repeated, second, _ = recovery_empirical_evidence(catalogue)
    pd.testing.assert_frame_equal(evidence, repeated)
    pd.testing.assert_frame_equal(first, second)
    primary = evidence.loc[evidence["role"].eq("primary")].set_index(
        "candidate_moment"
    )
    assert set(primary.index) == {
        "fixed_horizon_probability",
        "restricted_mean_recovery_time",
    }
    assert (primary["q1_event_count"] == 19).all()
    assert (primary["q4_event_count"] == 19).all()
    assert not primary["empirical_gate_passed"].any()
    assert len(first) == 6 * 2_000
    assert influence["event_id"].nunique() <= 38


@pytest.mark.parametrize(
    ("a_empirical", "a_precision", "b_empirical", "b_precision", "expected"),
    [
        (True, True, True, True, "fixed_horizon_probability_replacement_accepted"),
        (False, True, True, True, "restricted_mean_replacement_accepted"),
        (False, True, False, True, "conditional_recovery_moment_unsupported"),
    ],
)
def test_recovery_replacement_hierarchy_is_fixed(
    a_empirical,
    a_precision,
    b_empirical,
    b_precision,
    expected,
) -> None:
    empirical = pd.DataFrame(
        [
            {
                "candidate_moment": "fixed_horizon_probability",
                "role": "primary",
                "empirical_gate_passed": a_empirical,
            },
            {
                "candidate_moment": "restricted_mean_recovery_time",
                "role": "primary",
                "empirical_gate_passed": b_empirical,
            },
        ]
    )
    summary = {
        "fixed_horizon_probability": {
            "precision_gate_passed": a_precision,
            "sensitivity": {"sensitivity_gate_passed": True},
        },
        "restricted_mean_recovery_time": {
            "precision_gate_passed": b_precision,
            "sensitivity": {"sensitivity_gate_passed": True},
        },
    }
    result = _recovery_replacement_decision(empirical, summary)
    assert result["status"] == expected
    assert not result["candidate_selected"]


def test_paired_evidence_neither_ranks_nor_replaces_absolute_gate() -> None:
    payload = json.loads(
        Path(
            "data/provenance/calibration/confidence/"
            "recovery_censoring_diagnosis.json"
        ).read_text()
    )
    assert payload["paired_result_count"] == 8
    assert not payload["candidate_pairs_ranked"]
    assert not payload["absolute_mcse_gate_replaced"]
    assert all(
        not item["pair_ranked"]
        and not item["absolute_mcse_gate_replaced"]
        for item in payload["paired_candidate_differences"]
    )


def test_precision_benchmark_projections_are_unexecuted() -> None:
    payload = json.loads(
        Path(
            "data/provenance/calibration/confidence/"
            "monte_carlo_precision_benchmark.json"
        ).read_text()
    )
    assert not payload["projections_executed"]
    assert payload["timing_not_used_to_change_statistical_design"]
    assert set(payload["projected_unexecuted_full_search"]) == {"32", "74"}
    assert all(
        not projection["executed"]
        for by_replication in payload["projected_unexecuted_full_search"].values()
        for projection in by_replication.values()
    )
