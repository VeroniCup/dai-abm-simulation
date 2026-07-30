"""Tests for the objective-blind structural factorial diagnosis."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dai_sim.calibration import structural_factorial as factorial
from dai_sim.calibration.simulated_moments import STAGE2_ACTIVE_MOMENTS

from tests.support import REPOSITORY_ROOT


def _interaction_group(
    *,
    direction: str,
    large_precise: int = 16,
    agreement: bool = True,
    median_scales: float = 1.0,
) -> pd.DataFrame:
    rows = []
    for position, candidate in enumerate(factorial.PANEL_INDICES):
        value = median_scales if position < large_precise else 0.1
        rows.append(
            {
                "candidate_index": candidate,
                "direction": direction,
                "large_and_precise": position < large_precise,
                "band_gap_reduction_scales": (
                    value if direction == "towards_band" else -value
                ),
                "mcse_agreement_pass": agreement,
            }
        )
    return pd.DataFrame(rows)


def _mini_cells() -> dict[str, pd.DataFrame]:
    cells = {}
    for cell in factorial.build_factorial_cells():
        a, b, c = cell.binary
        rows = []
        for event_position, event_id in enumerate(("event-a", "event-b")):
            for replication in range(4):
                rows.append(
                    {
                        "candidate_index": factorial.PANEL_INDICES[0],
                        "event_id": event_id,
                        "replication": replication,
                        "initial_peg_gap": float(event_position),
                        "value": (
                            2.0
                            + 3.0 * a
                            + 5.0 * b
                            + 7.0 * c
                            + 11.0 * a * b
                            + 13.0 * a * c
                            + 17.0 * b * c
                            + 19.0 * a * b * c
                            + replication / 100.0
                        ),
                    }
                )
        cells[cell.code] = pd.DataFrame(rows)
    return cells


def _precision_cells(replications: int = 64) -> dict[str, pd.DataFrame]:
    cells = {}
    for cell in factorial.build_factorial_cells():
        a, b, c = cell.binary
        rows = []
        for candidate_index in factorial.PANEL_INDICES:
            for event_position, event_id in enumerate(("event-a", "event-b")):
                for replication in range(replications):
                    rows.append(
                        {
                            "candidate_index": candidate_index,
                            "event_id": event_id,
                            "replication": replication,
                            "initial_peg_gap": float(event_position),
                            "failed_recovery_attempts": (
                                1.0
                                + c * ((replication % 3) + event_position)
                                + b * c * (replication % 5)
                                + a * c * ((replication + 1) % 2)
                            ),
                        }
                    )
        cells[cell.code] = pd.DataFrame(rows)
    return cells


def test_factor_order_is_exact() -> None:
    assert factorial.FACTOR_ORDER == (
        "A_vault_state",
        "B_residual_process",
        "C_backlog_gate",
    )


def test_cell_order_is_exact() -> None:
    assert tuple(cell.code for cell in factorial.build_factorial_cells()) == (
        "000",
        "100",
        "010",
        "001",
        "110",
        "101",
        "011",
        "111",
    )


def test_factorial_has_exactly_three_factors() -> None:
    assert len(factorial.FACTOR_ORDER) == 3
    assert all(len(cell.binary) == 3 for cell in factorial.build_factorial_cells())


def test_binary_and_signed_coding_are_registered() -> None:
    cells = {cell.code: cell for cell in factorial.build_factorial_cells()}
    assert cells["000"].binary == (0, 0, 0)
    assert cells["000"].signed == (-1, -1, -1)
    assert cells["111"].binary == (1, 1, 1)
    assert cells["111"].signed == (1, 1, 1)


def test_four_cells_are_reused() -> None:
    assert tuple(
        cell.code for cell in factorial.build_factorial_cells() if cell.reused
    ) == factorial.REUSED_CELLS


def test_four_cells_are_new() -> None:
    assert tuple(
        cell.code for cell in factorial.build_factorial_cells() if not cell.reused
    ) == factorial.NEW_CELLS


@pytest.mark.parametrize(
    ("cell_id", "source"),
    (
        ("000", None),
        ("100", "vault_historical_p25_scr"),
        ("010", "residual_zero"),
        ("001", "gate_bad_debt_only"),
    ),
)
def test_reused_cell_sources_are_exact(cell_id: str, source: str | None) -> None:
    cells = {cell.code: cell for cell in factorial.build_factorial_cells()}
    assert cells[cell_id].source_variant == source


def test_missing_cells_have_no_source_variant() -> None:
    cells = {cell.code: cell for cell in factorial.build_factorial_cells()}
    assert all(cells[code].source_variant is None for code in factorial.NEW_CELLS)


def test_factor_levels_preserve_bad_debt_in_high_gate() -> None:
    factors = factorial._factor_definitions()
    gate = factors["C_backlog_gate"]
    assert gate["high"]["unresolved_backlog"] is False
    assert gate["high"]["active_bad_debt"] is True
    assert gate["high"]["price_stability"] is True


def test_zero_residual_is_mechanism_only() -> None:
    high = factorial._factor_definitions()["B_residual_process"]["high"]
    assert high["mechanism_isolation_only"] is True
    assert high["empirical_residual_model"] is False


def test_p25_state_preserves_fixed_total_debt() -> None:
    high = factorial._factor_definitions()["A_vault_state"]["high"]
    assert high["total_debt_dai"] == 2_500_000.0
    assert high["relative_debt_weights_preserved"] is True
    assert high["event_specific_selection"] is False
    assert high["arbitrary_collateral_ratio_scaling"] is False


def test_baseline_state_checksum_is_fixed() -> None:
    low = factorial._factor_definitions()["A_vault_state"]["low"]
    assert low["state_checksum"] == (
        "93a58910ddcffd488089f4a46e4412e7d0531fa33e97e0734e9429d400e609f0"
    )


def test_factorial_identity_is_deterministic() -> None:
    first, first_payload = factorial.build_factorial_identity()
    second, second_payload = factorial.build_factorial_identity()
    assert first == second
    assert first_payload == second_payload
    assert len(first) == 64


def test_factorial_identity_excludes_results() -> None:
    _, payload = factorial.build_factorial_identity()
    text = json.dumps(payload, sort_keys=True)
    assert "compatibility_count" not in text
    assert "wall_time" not in text
    assert "selected_cell" not in text
    assert payload["result_fields_excluded"] is True


def test_registry_has_no_selection_or_ranking() -> None:
    registry = factorial._cell_registry()
    assert registry["cell_count"] == 8
    assert registry["reused_cell_count"] == 4
    assert registry["new_cell_count"] == 4
    assert not registry["objective_used"]
    assert not registry["candidate_ranked"]
    assert not registry["cell_ranked"]
    assert not registry["cell_selected"]
    assert not registry["parameter_selected"]
    assert not registry["runtime_adopted"]


def test_registry_changes_only_declared_high_factors() -> None:
    registry = factorial._cell_registry()
    for cell in registry["cells"]:
        expected = [
            factorial.FACTOR_ORDER[index]
            for index, value in enumerate(cell["binary_coding"])
            if value
        ]
        assert cell["changed_assumptions"] == expected


@pytest.mark.parametrize(
    ("effect", "expected"),
    (
        ("A", {"000": -0.25, "100": 0.25, "010": -0.25, "001": -0.25}),
        ("B", {"000": -0.25, "100": -0.25, "010": 0.25, "001": -0.25}),
        ("C", {"000": -0.25, "100": -0.25, "010": -0.25, "001": 0.25}),
    ),
)
def test_main_effect_signed_weights(
    effect: str,
    expected: dict[str, float],
) -> None:
    weights = factorial._effect_weights(effect)
    assert all(weights[cell] == value for cell, value in expected.items())
    assert sum(abs(value) for value in weights.values()) == 2.0


@pytest.mark.parametrize("effect", ("AB", "AC", "BC", "ABC"))
def test_interaction_effect_weights_are_balanced(effect: str) -> None:
    weights = factorial._effect_weights(effect)
    assert set(weights) == set(factorial.CELL_ORDER)
    assert sum(weights.values()) == 0.0
    assert set(weights.values()) == {-0.25, 0.25}


def test_factorial_effect_formulas_recover_known_coefficients() -> None:
    cells = _mini_cells()
    expected = {
        "A": 3.0 + 11.0 / 2 + 13.0 / 2 + 19.0 / 4,
        "B": 5.0 + 11.0 / 2 + 17.0 / 2 + 19.0 / 4,
        "C": 7.0 + 13.0 / 2 + 17.0 / 2 + 19.0 / 4,
        "AB": 11.0 / 2 + 19.0 / 4,
        "AC": 13.0 / 2 + 19.0 / 4,
        "BC": 17.0 / 2 + 19.0 / 4,
        "ABC": 19.0 / 4,
    }
    for effect, value in expected.items():
        frame = factorial._linear_combination_frame(
            cells,
            candidate_index=factorial.PANEL_INDICES[0],
            source="value",
            weights=factorial._effect_weights(effect),
        )
        estimate = factorial._estimate_contrast(
            frame.rename(columns={"value": "unused"}),
            moment="maximum_downside_deviation_mean",
        )
        assert estimate.point_estimate == pytest.approx(value)


@pytest.mark.parametrize(
    ("cell_id", "expected"),
    (
        ("110", 11.0),
        ("101", 13.0),
        ("011", 17.0),
        ("111", 60.0),
    ),
)
def test_additive_residual_formulas(cell_id: str, expected: float) -> None:
    cells = _mini_cells()
    frame = factorial._linear_combination_frame(
        cells,
        candidate_index=factorial.PANEL_INDICES[0],
        source="value",
        weights=factorial.ADDITIVE_COMPONENTS[cell_id],
    )
    assert frame["contrast"].mean() == pytest.approx(expected)


def test_synergistic_interaction_classification() -> None:
    result = factorial.classify_interaction(
        _interaction_group(direction="towards_band")
    )
    assert result["classification"] == "synergistic_towards_band"


def test_antagonistic_interaction_classification() -> None:
    result = factorial.classify_interaction(
        _interaction_group(direction="away_from_band")
    )
    assert result["classification"] == "antagonistic_away_from_band"


def test_mixed_interaction_classification() -> None:
    group = _interaction_group(direction="towards_band")
    group.loc[group.index[8:], "direction"] = "away_from_band"
    result = factorial.classify_interaction(group)
    assert result["classification"] == "material_mixed_interaction"


def test_approximately_additive_classification() -> None:
    result = factorial.classify_interaction(
        _interaction_group(
            direction="towards_band",
            large_precise=7,
            median_scales=0.1,
        )
    )
    assert result["classification"] == "approximately_additive"


def test_invalid_interaction_classification() -> None:
    result = factorial.classify_interaction(
        _interaction_group(direction="towards_band", agreement=False)
    )
    assert result["classification"] == "interaction_invalid"


def test_material_rule_requires_twelve_directions() -> None:
    group = _interaction_group(direction="towards_band")
    group.loc[group.index[11:], "direction"] = "away_from_band"
    assert (
        factorial.classify_interaction(group)["classification"]
        == "material_mixed_interaction"
    )


def test_material_rule_requires_eight_large_precise_candidates() -> None:
    group = _interaction_group(
        direction="towards_band",
        large_precise=7,
    )
    assert (
        factorial.classify_interaction(group)["classification"]
        == "approximately_additive"
    )


def test_material_rule_requires_half_scale_median() -> None:
    group = _interaction_group(
        direction="towards_band",
        median_scales=0.49,
    )
    assert (
        factorial.classify_interaction(group)["classification"]
        == "approximately_additive"
    )


def test_material_improvement_uses_fixed_thresholds() -> None:
    group = pd.DataFrame(
        {
            "towards_band": [True] * 12 + [False] * 4,
            "shift_scales": [0.6] * 8 + [0.1] * 8,
            "snr": [2.1] * 8 + [0.0] * 8,
            "gap_reduction_scales": [0.6] * 16,
        }
    )
    assert factorial._material_improvement(group)


def test_tradeoff_worsening_requires_one_scale_and_snr() -> None:
    group = pd.DataFrame(
        {
            "away_from_band": [True] * 12 + [False] * 4,
            "actual_gap_scales": [2.0] * 12 + [0.0] * 4,
            "baseline_gap_scales": [0.5] * 12 + [0.0] * 4,
            "snr": [2.1] * 12 + [0.0] * 4,
        }
    )
    assert factorial._material_worsening(group)
    group["snr"] = 1.99
    assert not factorial._material_worsening(group)


def test_evaluation_counts_are_fixed() -> None:
    assert factorial.EXPECTED_REUSED_EVALUATIONS == 303_104
    assert factorial.EXPECTED_NEW_EVALUATIONS == 303_104
    assert factorial.EXPECTED_TOTAL_EVALUATIONS == 606_208
    assert factorial.EXPECTED_NEW_CHECKPOINTS == 64


def test_factorial_uses_fixed_panel_events_replications_and_registry() -> None:
    assert factorial.PANEL_INDICES == (
        0, 94, 171, 42, 193, 100, 116, 127,
        36, 252, 222, 97, 134, 103, 203, 126,
    )
    assert factorial.PANEL_SHA256 == (
        "7ca9475da16b6e2a971d8adfe8bda6714c0841191e596e45d51bbcf2a26108f9"
    )
    assert factorial.EVENT_COUNT == 74
    assert factorial.REPLICATION_COUNT == 64
    assert factorial.REGISTRY_A == "confidence-smm-registry-a"


def test_reused_cells_reproduce_committed_streams() -> None:
    frames = factorial._reused_cell_frames()
    assert tuple(frames) == factorial.REUSED_CELLS
    assert all(len(frame) == 75_776 for frame in frames.values())


def test_factorial_input_validation_passes() -> None:
    result = factorial.validate_factorial_inputs()
    assert result["status"] == "passed"
    assert result["reused_evaluations"] == 303_104
    assert result["new_evaluations"] == 303_104
    assert result["projected_factorial_storage_bytes"] < 500 * 1024**2


def test_workflow_exposes_factorial_without_optimisation_flags() -> None:
    path = REPOSITORY_ROOT / "workflows/calibration/market_gas_protocol.py"
    text = path.read_text(encoding="utf-8")
    assert '"structural-factorial"' in text
    factorial_section = text[text.index('"--factorial-action"'):]
    assert "run-missing-cells" in factorial_section
    assert "calculate-effects" in factorial_section
    assert "rank-cells" not in factorial_section
    assert "powell" not in factorial_section.lower()


def test_factorial_module_has_no_production_model_import() -> None:
    path = REPOSITORY_ROOT / "src/dai_sim/calibration/structural_factorial.py"
    text = path.read_text(encoding="utf-8")
    assert "from dai_sim.model" not in text
    assert "runtime_adopted\": True" not in text
    assert "selected_cell\": \"" not in text


def test_worker_initialisation_does_not_race_shared_config_temporary_file() -> None:
    path = REPOSITORY_ROOT / "src/dai_sim/calibration/structural_factorial.py"
    text = path.read_text(encoding="utf-8")
    worker = text[
        text.index("def _worker_initialise("):
        text.index("def _apply_cell_package(")
    ]
    runner = text[
        text.index("def run_missing_cells("):
        text.index("def _new_cell_frames(")
    ]
    assert "load_tranche_b_configuration" not in worker
    assert "load_tranche_b_configuration" in runner
    assert "structural._worker_initialise" not in worker
    assert 'owner["stage1"] = stage1' in worker


def test_factorial_does_not_define_a_scalar_objective() -> None:
    path = REPOSITORY_ROOT / "src/dai_sim/calibration/structural_factorial.py"
    text = path.read_text(encoding="utf-8")
    assert "scalar_objective\": None" in text
    assert "objective_value" not in text
    assert "def rank_" not in text
    assert "candidate_ranked\": True" not in text
    assert "cell_ranked\": True" not in text


def test_factorial_evidence_names_exclude_selection_outputs() -> None:
    assert len(factorial.EVIDENCE_NAMES) == 10
    assert not any(
        token in name
        for name in factorial.EVIDENCE_NAMES
        for token in ("selected", "ranking", "top16", "objective")
    )


def test_checkpoint_schema_excludes_optional_nan_metrics() -> None:
    required = {
        "cell_id",
        "candidate_index",
        "event_id",
        "replication",
        *factorial.METRIC_COLUMNS,
        "structural_pass",
    }
    assert "confidence_recovery_time" not in required
    assert "post_recovery_overshoot" not in required
    frame = pd.DataFrame(
        [
            {
                "cell_id": "110",
                "candidate_index": 0,
                "event_id": "event",
                "replication": 0,
                **{
                    column: (
                        False
                        if column == "right_censored"
                        else 0.0
                    )
                    for column in factorial.METRIC_COLUMNS
                },
                "structural_pass": True,
            }
        ]
    )
    assert len(factorial._frame_checksum(frame)) == 64


def test_fixed_empirical_bands_are_preserved() -> None:
    bands = {
        item["moment"]: (item["lower"], item["upper"])
        for item in factorial.build_factorial_identity()[1][
            "empirical_support_bands"
        ]
    }
    assert bands == {
        "first_six_hour_burden_mean": pytest.approx(
            (0.0775611130119999, 0.1758450431439999)
        ),
        "maximum_downside_deviation_mean": pytest.approx(
            (0.0021472894676802, 0.0043219244962797)
        ),
        "recovery_completion_hours_mean": pytest.approx(
            (29.880602871860003, 68.03831604714)
        ),
        "failed_recovery_attempts_mean": pytest.approx(
            (0.5246827842199999, 5.718560459020001)
        ),
        "initial_gap_q4_q1_burden_contrast": pytest.approx(
            (0.4552116432749999, 0.742919643275)
        ),
    }


def test_stage2_active_moment_count_remains_five() -> None:
    assert len(STAGE2_ACTIVE_MOMENTS) == 5


def test_no_hidden_ninth_cell() -> None:
    assert len(factorial.build_factorial_cells()) == 8
    assert set(factorial.CELL_ORDER) == {
        f"{value:03b}" for value in range(8)
    }


def test_precision_identity_is_deterministic_and_keeps_factorial_identity() -> None:
    first, payload = factorial.build_precision_identity()
    second, repeated = factorial.build_precision_identity()
    assert first == second
    assert payload == repeated
    assert payload["source_factorial_identity"] == (
        "4558b97de3c092b8cec70b9117407333527f517559b7126fa0428c5e9059ad00"
    )
    assert payload["relative_tolerance"] == 0.15
    assert payload["minimum_candidate_pass_count"] == 15


def test_precision_extension_is_uniform_and_exact() -> None:
    assert factorial.PRECISION_ADDED_REPLICATIONS == tuple(range(64, 128))
    assert factorial.EXPECTED_PRECISION_REUSED_EVALUATIONS == 606_208
    assert factorial.EXPECTED_PRECISION_NEW_EVALUATIONS == 606_208
    assert factorial.EXPECTED_PRECISION_TOTAL_EVALUATIONS == 1_212_416
    assert factorial.EXPECTED_PRECISION_CHECKPOINTS == 128


def test_precision_effect_is_constructed_before_uncertainty() -> None:
    cells = _precision_cells(replications=16)
    contrast = factorial._linear_combination_frame(
        cells,
        candidate_index=factorial.PANEL_INDICES[0],
        source="failed_recovery_attempts",
        weights=factorial._effect_weights("C"),
    )
    assert len(contrast) == 32
    assert not contrast[["event_id", "replication"]].duplicated().any()
    estimate = factorial._estimate_contrast(
        contrast,
        moment=factorial.PRECISION_MOMENT,
    )
    assert estimate.replication_count == 16
    assert estimate.event_count == 2
    assert estimate.analytic_mcse >= 0.0
    assert estimate.replication_index_mcse >= 0.0


def test_precision_audit_uses_exact_nested_prefixes() -> None:
    audit, summary = factorial.construct_precision_audit(
        _precision_cells(),
        prefixes=(16, 32, 48, 64),
    )
    assert set(audit["replication_prefix"]) == {16, 32, 48, 64}
    assert len(audit) == 4 * 16 * 2
    assert set(audit["moment"]) == {factorial.PRECISION_MOMENT}
    assert set(audit["effect"]) == {"C", "BC"}
    assert summary["final_replication_count"] == 64


def test_precision_audit_rejects_non_nested_prefix_order() -> None:
    with pytest.raises(ValueError, match="unique and increasing"):
        factorial.construct_precision_audit(
            _precision_cells(),
            prefixes=(16, 48, 32, 64),
        )


def test_relative_disagreement_boundary_is_not_weakened() -> None:
    passing = {
        "agreement_pass": True,
        "analytic_mcse": 0.85,
        "replication_index_mcse": 1.0,
        "zero_variance_event_count": 0,
    }
    failing = {**passing, "agreement_pass": False}
    assert factorial._audit_classification(
        passing,
        ownership_passed=True,
    ) == "gate_pass"
    assert factorial._audit_classification(
        failing,
        ownership_passed=True,
    ) == "finite_replication_instability"
    assert factorial.PRECISION_RELATIVE_TOLERANCE == 0.15


def test_precision_formula_error_boundary_precedes_extension() -> None:
    row = {
        "agreement_pass": False,
        "analytic_mcse": 1.0,
        "replication_index_mcse": 2.0,
        "zero_variance_event_count": 0,
    }
    assert factorial._audit_classification(
        row,
        ownership_passed=False,
    ) == "formula_or_ownership_mismatch"


def test_precision_variance_floor_classification_is_explicit() -> None:
    row = {
        "agreement_pass": False,
        "analytic_mcse": 1e-13,
        "replication_index_mcse": 1e-13,
        "zero_variance_event_count": 0,
    }
    assert factorial._audit_classification(
        row,
        ownership_passed=True,
    ) == "variance_floor_or_degeneracy"


def test_precision_comparison_candidates_are_objective_blind() -> None:
    assert factorial._comparison_candidates() == (0, 127, 252)


def test_precision_workflow_has_no_selective_extension_action() -> None:
    path = REPOSITORY_ROOT / "workflows/calibration/market_gas_protocol.py"
    text = path.read_text(encoding="utf-8")
    section = text[text.index('"--factorial-action"'):]
    assert "precision-audit-r64" in section
    assert "precision-extend" in section
    assert "extend-candidate" not in section
    assert "extend-cell" not in section


def test_tracked_precision_evidence_has_complete_fixed_gate() -> None:
    root = REPOSITORY_ROOT / "data/provenance/calibration/confidence"
    audit = pd.read_csv(root / "structural_factorial_precision_audit.csv")
    decision = json.loads(
        (root / "structural_factorial_precision_decision.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(audit) == 5 * 16 * 5 * 7
    assert set(audit["replication_prefix"]) == {16, 32, 48, 64, 128}
    assert set(audit["candidate_index"]) == set(factorial.PANEL_INDICES)
    assert set(audit["moment"]) == set(STAGE2_ACTIVE_MOMENTS)
    assert set(audit["effect"]) == set(factorial.EFFECT_ORDER)
    assert decision["gate_pass"]
    assert decision["final_failing_combinations"] == {}
    assert decision["final_pass_counts"][
        "failed_recovery_attempts_mean|C"
    ] == 15
    assert decision["final_pass_counts"][
        "failed_recovery_attempts_mean|BC"
    ] == 15


def test_tracked_factorial_evidence_has_complete_cells_and_effects() -> None:
    root = REPOSITORY_ROOT / "data/provenance/calibration/confidence"
    cells = pd.read_csv(root / "structural_factorial_cells.csv")
    effects = pd.read_csv(root / "structural_factorial_effects.csv")
    interactions = pd.read_csv(root / "structural_factorial_interactions.csv")
    assert len(cells) == 8 * 16 * 5
    assert len(effects) == 16 * 5 * 7
    assert len(interactions) == 4 * 16 * 5
    assert set(cells["cell_id"].astype(str).str.zfill(3)) == set(
        factorial.CELL_ORDER
    )


def test_factorial_decision_ends_rescue_without_selection() -> None:
    path = (
        REPOSITORY_ROOT
        / "data/provenance/calibration/confidence/"
        "structural_factorial_decision.json"
    )
    decision = json.loads(path.read_text(encoding="utf-8"))
    assert decision["final_classification"] == (
        "factorial_interactions_reveal_tradeoffs"
    )
    assert decision["selected_cell"] is None
    assert decision["selected_parameter"] is None
    assert not decision["candidate_ranked"]
    assert not decision["cell_ranked"]
    assert not decision["structural_model_selected"]
    assert not decision["runtime_adopted"]


def test_factorial_interactions_have_no_synergistic_classification() -> None:
    path = (
        REPOSITORY_ROOT
        / "data/provenance/calibration/confidence/"
        "structural_factorial_interaction_summary.json"
    )
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["synergistic_interactions"] == []
    assert len(summary["antagonistic_interactions"]) == 2
    assert len(summary["mixed_interactions"]) == 3
    assert len(summary["approximately_additive_interactions"]) == 15


def test_factorial_evidence_contains_no_objective_rank_or_selection() -> None:
    root = REPOSITORY_ROOT / "data/provenance/calibration/confidence"
    names = (*factorial.EVIDENCE_NAMES, *factorial.PRECISION_EVIDENCE_NAMES)
    text = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in names
        if name.endswith(".json")
    )
    assert '"runtime_adopted": true' not in text.lower()
    assert '"selected_cell": "' not in text
    assert '"selected_parameter": "' not in text
    assert '"objective_value"' not in text


def test_completed_precision_and_factorial_evidence_validate() -> None:
    result = factorial.validate_completed_precision_reconciliation()
    assert result["status"] == "passed"
    assert result["precision_audit_rows"] == 2_800
    assert result["checkpoint_count"] == 128
    assert result["factorial_final_classification"] == (
        "factorial_interactions_reveal_tradeoffs"
    )
