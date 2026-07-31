"""Focused gates for the registered H4 recovery evidence synthesis."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
from pathlib import Path

import pytest

from dai_sim.experiments.final import recovery_behaviour_synthesis as synthesis
from tests.support import REPOSITORY_ROOT


WORKFLOW = (
    REPOSITORY_ROOT
    / "workflows/experiments/final/recovery_behaviour_synthesis.py"
)


def test_exact_registered_source_identities_and_decisions() -> None:
    rows = synthesis.build_source_registry()
    assert len(rows) == 12
    assert [row["source_identifier"] for row in rows] == [
        source.identifier for source in synthesis.SOURCE_DEFINITIONS
    ]
    assert rows[5]["experiment_or_calibration_identity"] == (
        "68afcef1166bb6b13813d0e481ce7bddff7605c0ac7326bf8b9d1400eacff20b"
    )
    assert rows[5]["evidence_status"] == "conditional_channel_absence"
    assert rows[6]["experiment_or_calibration_identity"] == (
        "6cfbd19384fc95fe8b06de74704d0b2a76638722b100242e0bc87a9ee3e05acc"
    )
    assert [row["registered_classification"] for row in rows[7:]] == [
        "H3_idiosyncratic_diversification_supported",
        "H3_correlation_deterioration_supported",
        "H3_stable_tradeoff_partially_supported",
        "H1_no_clear_shared_capacity_effect",
        "H2_oracle_delay_partially_supported",
    ]


def test_every_source_file_is_committed_and_checksum_valid() -> None:
    for source in synthesis.SOURCE_DEFINITIONS:
        synthesis._validate_source_files(source)


def test_missing_or_changed_source_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(synthesis, "_is_committed_source", lambda _relative: False)
    with pytest.raises(ValueError, match="not committed"):
        synthesis._validate_file(
            synthesis.SOURCE_DEFINITIONS[0].decision_path,
            synthesis.SOURCE_DEFINITIONS[0].decision_sha256,
        )


def test_duplicate_and_held_out_sources_fail() -> None:
    rows = synthesis.build_source_registry()
    with pytest.raises(ValueError, match="order or population"):
        synthesis.validate_source_registry([*rows, rows[0]])
    held_out = [dict(row) for row in rows]
    held_out[0]["source_identifier"] = "held_out_usdc_svb"
    with pytest.raises(ValueError):
        synthesis.validate_source_registry(held_out)


def test_historical_component_labels_are_not_dissertation_hypotheses() -> None:
    specification = synthesis.specification_payload("registry")
    assert specification["historical_labels"] == {
        "H5a_to_H5d": (
            "internal constrained-recovery component labels, not dissertation "
            "hypotheses"
        )
    }
    assert specification["hypothesis"] == "H4"


def test_registered_decision_hierarchy_cannot_be_overridden_by_matrix_prose() -> None:
    matrix = synthesis.build_evidence_matrix()
    decision = synthesis.classify_synthesis()
    assert len(matrix) == 18
    assert decision["overall_h4_classification"] == (
        "H4_recovery_conditionally_supported"
    )
    assert all(row["tier"] in {1, 2} for row in matrix)
    assert synthesis.specification_payload("registry")["source_inclusion_rules"][
        "reports_cannot_override_decisions"
    ]


@pytest.mark.parametrize(
    ("immediate", "constrained", "valid", "expected"),
    [
        (False, True, True, "conditionally_operational"),
        (True, True, True, "generally_operational"),
        (False, False, True, "not_operational"),
        (True, False, True, "inconsistent"),
        (False, True, False, "invalid"),
    ],
)
def test_s1_classification_branches(
    immediate: bool, constrained: bool, valid: bool, expected: str
) -> None:
    assert (
        synthesis.classify_s1(
            immediate_channel=immediate,
            constrained_channel=constrained,
            valid=valid,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("interaction", "capacity", "count", "expected"),
    [
        (True, True, 3, "supported"),
        (True, False, 1, "partially_supported"),
        (False, False, 1, "not_supported"),
        (True, True, 0, "not_supported"),
    ],
)
def test_s2_classification_branches(
    interaction: bool, capacity: bool, count: int, expected: str
) -> None:
    assert (
        synthesis.classify_s2(
            interaction_clear=interaction,
            capacity_effect_clear=capacity,
            operational_count=count,
        )
        == expected
    )


def test_s2_context_specific_qualifier() -> None:
    assert synthesis.s2_generalisability(final_capacity_clear=False) == (
        "context_specific"
    )
    assert synthesis.s2_generalisability(final_capacity_clear=True) == "general"


@pytest.mark.parametrize(
    ("calibrated", "effects", "directions", "expected"),
    [
        (False, (True, False, False), (-1, 0, 0), "scenario_dependent_not_identified"),
        (False, (True, True, True), (-1, -1, -1), "robustly_supported"),
        (False, (False, False), (0, 0), "not_operational"),
        (True, (False,), (0,), "empirically_identified"),
    ],
)
def test_s3_classification_branches(
    calibrated: bool,
    effects: tuple[bool, ...],
    directions: tuple[int, ...],
    expected: str,
) -> None:
    assert (
        synthesis.classify_s3(
            calibrated_vector=calibrated,
            active_effects=effects,
            active_directions=directions,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("backlog", "condition", "isolated", "assessed", "expected"),
    [
        (True, True, False, False, "mechanism_condition_supported"),
        (True, True, True, True, "peg_gate_effect_supported"),
        (True, True, False, True, "mechanism_present_peg_effect_unresolved"),
        (False, False, False, False, "not_operational"),
    ],
)
def test_s4_classification_branches(
    backlog: bool,
    condition: bool,
    isolated: bool,
    assessed: bool,
    expected: str,
) -> None:
    assert synthesis.classify_s4(
        backlog_operational=backlog,
        mechanism_condition=condition,
        isolated_peg_gate=isolated,
        peg_effect_assessed=assessed,
    ) == expected


@pytest.mark.parametrize(
    ("constrained", "count", "contradictions", "expected"),
    [
        (True, 4, 0, "strongly_supported"),
        (True, 1, 0, "supported"),
        (True, 4, 1, "mixed"),
        (False, 4, 0, "not_supported"),
    ],
)
def test_s5_classification_branches(
    constrained: bool, count: int, contradictions: int, expected: str
) -> None:
    assert synthesis.classify_s5(
        constrained_decoupling=constrained,
        final_decoupling_count=count,
        contradiction_count=contradictions,
    ) == expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            ("generally_operational", "supported", "general", "robustly_supported", "peg_gate_effect_supported", "supported", True),
            "H4_joint_recovery_supported",
        ),
        (
            ("conditionally_operational", "supported", "context_specific", "scenario_dependent_not_identified", "mechanism_present_peg_effect_unresolved", "strongly_supported", True),
            "H4_recovery_conditionally_supported",
        ),
        (
            ("conditionally_operational", "supported", "context_specific", "not_operational", "mechanism_condition_supported", "supported", True),
            "H4_solvency_recovery_without_peg_recovery",
        ),
        (
            ("generally_operational", "supported", "context_specific", "scenario_dependent_not_identified", "not_operational", "supported", True),
            "H4_behavioural_recovery_unresolved",
        ),
        (
            ("not_operational", "not_supported", "general", "not_operational", "not_operational", "not_supported", True),
            "H4_no_clear_recovery_evidence",
        ),
        (
            ("conditionally_operational", "supported", "context_specific", "scenario_dependent_not_identified", "mechanism_present_peg_effect_unresolved", "strongly_supported", False),
            "H4_recovery_synthesis_invalid",
        ),
    ],
)
def test_every_h4_classification_branch(
    values: tuple[str, str, str, str, str, str, bool], expected: str
) -> None:
    s1, s2, qualifier, s3, s4, s5, valid = values
    assert synthesis.classify_h4(
        s1=s1,
        s2=s2,
        s2_qualifier=qualifier,
        s3=s3,
        s4=s4,
        s5=s5,
        valid=valid,
    ) == expected


def test_required_claim_crosswalk_is_complete_and_bounded() -> None:
    rows = synthesis.build_claim_crosswalk()
    assert len(rows) == 14
    assert [row["claim_identifier"] for row in rows] == [
        f"C{number:02d}" for number in range(1, 15)
    ]
    assert all(
        row["supporting_source_ids"] or row["limiting_source_ids"] for row in rows
    )
    assert all(row["prohibited_overstatement"] for row in rows)
    combined = json.dumps(rows).lower()
    assert "empirically preferred" in combined
    assert "backlog alone causes" in combined
    assert "collateral recovery always" in combined


def test_no_execution_or_checkpoint_interface_exists() -> None:
    source_tree = ast.parse(Path(synthesis.__file__).read_text(encoding="utf-8"))
    workflow_tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    imports = {
        node.module or ""
        for node in ast.walk(source_tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(name.startswith("dai_sim.model") for name in imports)
    assert not any(name.endswith("runner") for name in imports)
    tracked_source_paths = {
        path
        for source in synthesis.SOURCE_DEFINITIONS
        for path in (
            source.specification_path,
            source.decision_path,
            source.reproducibility_path,
            *(relative for relative, _digest in source.supporting_paths),
        )
    }
    assert all(not path.startswith("outputs/") for path in tracked_source_paths)
    assert all("checkpoint" not in path for path in tracked_source_paths)
    parser_choices = WORKFLOW.read_text(encoding="utf-8")
    assert '"run"' not in parser_choices
    assert '"simulate"' not in parser_choices
    assert '"resume"' not in parser_choices
    assert '"smoke"' not in parser_choices
    assert '"workers"' not in parser_choices
    assert not any(
        isinstance(node, ast.Name) and node.id == "run_matrix"
        for node in ast.walk(workflow_tree)
    )


def test_evidence_payloads_are_deterministic_and_execution_free() -> None:
    first = synthesis.build_evidence_payloads()
    second = synthesis.build_evidence_payloads()
    assert first == second
    assert tuple(first) == synthesis.COMPACT_FILENAMES
    reproducibility = json.loads(first[synthesis.COMPACT_FILENAMES[-1]])
    assert reproducibility["simulations_executed"] == 0
    assert reproducibility["checkpoints_read"] == 0
    assert reproducibility["network_calls"] == 0
    assert reproducibility["held_out_observations"] == 0
    assert reproducibility["scenario_rankings"] == 0
    assert reproducibility["runtime_changes"] == 0


def test_constructed_evidence_and_manifest_are_valid() -> None:
    payloads = synthesis.build_evidence_payloads()
    manifest = json.loads(synthesis.MANIFEST_PATH.read_text(encoding="utf-8"))
    records = {str(row["path"]): row for row in manifest["artefacts"]}
    assert manifest["artefact_count"] == 81
    for name, payload in payloads.items():
        path = synthesis.EVIDENCE_DIR / name
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        assert path.read_bytes() == payload
        assert records[relative]["sha256"] == hashlib.sha256(payload).hexdigest()
    sources = list(
        csv.DictReader(
            (synthesis.EVIDENCE_DIR / synthesis.COMPACT_FILENAMES[1]).open(
                encoding="utf-8", newline=""
            )
        )
    )
    claims = list(
        csv.DictReader(
            (synthesis.EVIDENCE_DIR / synthesis.COMPACT_FILENAMES[3]).open(
                encoding="utf-8", newline=""
            )
        )
    )
    reproducibility = json.loads(
        (synthesis.EVIDENCE_DIR / synthesis.COMPACT_FILENAMES[-1]).read_text()
    )
    assert len(sources) == 12
    assert len(claims) == 14
    assert reproducibility["simulations_executed"] == 0
    assert reproducibility["checkpoints_read"] == 0


def test_exactly_six_compact_artefacts_and_no_detailed_output() -> None:
    files = sorted(path.name for path in synthesis.EVIDENCE_DIR.iterdir() if path.is_file())
    assert files == sorted(synthesis.COMPACT_FILENAMES)
    decision = json.loads(
        (synthesis.EVIDENCE_DIR / synthesis.COMPACT_FILENAMES[4]).read_text()
    )
    assert decision["runtime_adopted"] is False
    assert decision["confidence_scenario_ranked"] is False
    assert decision["confidence_scenario_selected"] is None
    assert not (REPOSITORY_ROOT / "outputs/experiments/final/recovery_behaviour_synthesis").exists()


def test_source_registry_has_no_held_out_or_usdc_svb_source() -> None:
    with (synthesis.EVIDENCE_DIR / synthesis.COMPACT_FILENAMES[1]).open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    text = json.dumps(rows).lower()
    assert "held_out" not in text
    assert "usdc/svb" not in text
    assert hashlib.sha256(
        (synthesis.EVIDENCE_DIR / synthesis.COMPACT_FILENAMES[1]).read_bytes()
    ).hexdigest()
