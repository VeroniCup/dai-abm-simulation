"""Frozen confidence-scenario mechanism and evidence validation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dai_sim.inputs.confidence_scenarios import PROFILE_BEHAVIOUR_CHECKSUMS
from dai_sim.inputs.environment import (
    configuration_behaviour_sha256,
    load_configuration_profile,
)
from dai_sim.validation.confidence_scenarios import (
    controlled_mechanism_smoke,
    evidence_payloads,
    validate_confidence_scenario_evidence,
    write_confidence_scenario_evidence,
)


ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = ROOT / "config/profiles"


def test_mechanism_smoke_is_deterministic_bounded_and_non_substantive() -> None:
    first = controlled_mechanism_smoke()
    second = controlled_mechanism_smoke()
    assert first == second
    assert first["default_equals_explicit_stage1_only"]
    assert first["substantive_experiment"] is False
    assert first["runtime_adopted"] is False
    for result in first["scenario_results"].values():
        assert all(0.0 <= value <= 1.0 for value in result["confidence_path"])


def test_mechanism_smoke_has_required_deterioration_recovery_and_panic_ordering() -> None:
    smoke = controlled_mechanism_smoke()
    results = smoke["scenario_results"]
    assert (
        results["confidence_resilient"]["confidence_path"][0]
        > results["confidence_central"]["confidence_path"][0]
        > results["confidence_fragile"]["confidence_path"][0]
    )
    assert (
        results["confidence_central"]["common_start_one_step_recovery"]
        > results["confidence_resilient"]["common_start_one_step_recovery"]
        == results["confidence_fragile"]["common_start_one_step_recovery"]
    )
    panic = smoke["panic_magnitude_at_common_state"]
    assert (
        panic["confidence_fragile"]
        > panic["confidence_central"]
        > panic["confidence_resilient"]
    )
    assert results["stage1_only"]["confidence_path"] == [1.0] * 30
    assert results["stage1_only"]["panic_component_path"] == [0.0] * 30


def test_evidence_payloads_are_deterministic_and_preserve_scientific_boundaries() -> None:
    first = evidence_payloads()
    second = evidence_payloads()
    assert first == second
    specification = json.loads(first["confidence_scenario_specification.json"])
    reproducibility = json.loads(
        first["confidence_scenario_reproducibility.json"]
    )
    decision = json.loads(first["confidence_scenario_decision.json"])
    assert specification["no_model_selection"]
    assert specification["final_validation_used"] is False
    assert "central > resilient = fragile" in (
        specification["raw_recovery_adjustment_ordering"]
    )
    assert reproducibility["sobol_candidate_used"] is False
    assert reproducibility["factorial_cell_used"] is False
    assert reproducibility["objective_value_used"] is False
    assert decision["scenario_ranked"] is False
    assert decision["scenario_selected"] is None


def test_evidence_writes_and_validates_twice_byte_identically(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_manifest = tmp_path / "first_manifest.json"
    second_manifest = tmp_path / "second_manifest.json"
    unrelated_record = {
        "path": "data/provenance/experiments/recovery/unrelated.json",
        "sha256": "a" * 64,
        "size_bytes": 17,
        "classification": "pre_registered_recovery_experiment",
        "runtime_adopted": False,
    }
    shared_manifest = {
        "schema_version": 1,
        "purpose": "Shared experiment evidence.",
        "artefact_count": 1,
        "artefacts": [unrelated_record],
    }
    for manifest_path in (first_manifest, second_manifest):
        manifest_path.write_text(
            json.dumps(shared_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    first = write_confidence_scenario_evidence(
        evidence_dir=first_dir,
        manifest_path=first_manifest,
    )
    second = write_confidence_scenario_evidence(
        evidence_dir=second_dir,
        manifest_path=second_manifest,
    )
    assert first == second
    assert first_manifest.read_bytes() == second_manifest.read_bytes()
    for name in first:
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes()
    manifest = json.loads(first_manifest.read_text(encoding="utf-8"))
    assert unrelated_record in manifest["artefacts"]
    assert manifest["artefact_count"] == 5
    report = validate_confidence_scenario_evidence(
        evidence_dir=first_dir,
        manifest_path=first_manifest,
    )
    assert report["scenario_count"] == 4
    assert report["manifest_entry_count"] == 4
    assert report["manifest_total_entry_count"] == 5


@pytest.mark.parametrize("profile", ("legacy", "empirical", "empirical_stress"))
def test_existing_profile_behaviour_remains_frozen(profile: str) -> None:
    bundle = load_configuration_profile(PROFILE_DIR / f"{profile}.yaml")
    assert configuration_behaviour_sha256(bundle) == PROFILE_BEHAVIOUR_CHECKSUMS[
        profile
    ]


def test_scenario_documentation_records_coupling_and_prohibited_interpretation() -> None:
    text = (
        ROOT / "docs/experiments/confidence_scenarios.md"
    ).read_text(encoding="utf-8")
    required = (
        r"\rho_r=u_r",
        r"\alpha_r=\alpha_d\rho_r",
        "central therefore recovers faster",
        "No scenario represents truth",
        "not an empirical mean",
        "`confidence_central` is not an implicit default",
    )
    assert all(fragment in text for fragment in required)
    assert "resilient has the greatest raw recovery" not in text.lower()
    assert "calibrated central estimate" not in text.lower()


def test_active_guides_link_the_scenario_registry() -> None:
    paths = (
        "docs/experiments/README.md",
        "docs/experiments/confidence.md",
        "docs/calibration/README.md",
        "docs/calibration/confidence_and_behaviour.md",
        "docs/calibration/confidence_structural_factorial.md",
        "docs/overview/architecture.md",
        "PROJECT_STATUS.md",
    )
    for relative in paths:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "confidence_scenarios" in text
