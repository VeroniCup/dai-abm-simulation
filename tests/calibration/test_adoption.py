"""Focused synthetic and structural tests for the adoption-review tooling."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest


from tests.support import REPOSITORY_ROOT
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from dai_sim.calibration import adoption as review


def test_authoritative_parameter_count_reconciles_to_56() -> None:
    headings = review.authoritative_parameter_headings()
    assert len(headings) == 56
    assert len({code for code, _ in headings}) == 56
    assert headings[0][0] == "4.1.1"
    assert headings[-1][0] == "4.6.13"


def test_complete_implemented_field_coverage() -> None:
    candidates = review.consolidate_candidates()
    matrix = review.parameter_adoption_matrix(candidates)
    assert set(review.IMPLEMENTED_CONFIG_FIELDS.values()) <= set(
        matrix["parameter_subsection"]
    )
    assert len(review.IMPLEMENTED_CONFIG_FIELDS) >= 65
    assert review.discover_dataclass_fields() <= set(
        review.IMPLEMENTED_CONFIG_FIELDS
    )


def test_every_parameter_has_one_valid_primary_class() -> None:
    matrix = review.parameter_adoption_matrix(review.consolidate_candidates())
    assert matrix["parameter_subsection"].is_unique
    assert not matrix["primary_adoption_class"].isna().any()
    assert set(matrix["primary_adoption_class"]) <= review.ADOPTION_CLASSES


def test_candidate_consolidation_preserves_all_provenance() -> None:
    candidates = review.consolidate_candidates()
    assert len(candidates) == 80
    assert candidates["candidate_key"].is_unique
    assert candidates["phase"].value_counts().to_dict() == {
        "2A": 64,
        "2B": 9,
        "2C": 7,
    }
    assert candidates["source_registry_sha256"].str.len().eq(64).all()
    assert candidates.loc[
        candidates["phase"].eq("2A"), "original_candidate_sha256"
    ].str.len().eq(64).all()
    assert "sample_size" in candidates.columns


def test_phase2c_duration_sample_size_conflict_is_preserved_and_flagged() -> None:
    candidates = review.consolidate_candidates()
    duration = candidates.loc[
        candidates["phase"].eq("2C")
        & candidates["parameter"].eq("auction_duration")
    ].iloc[0]
    assert duration["sample_size"] == "581"
    assert "durable auction identity" in duration["notes"]
    assert "649 auctions" in duration["notes"]


def test_conflicting_candidates_are_not_silently_overwritten() -> None:
    candidates = review.consolidate_candidates()
    stress = candidates.loc[
        candidates["canonical_parameter"].eq("4.5.5")
    ]
    assert {"2B", "2C"} <= set(stress["phase"])
    assert len(stress) >= 2


def test_units_and_frequency_are_explicit_for_ready_rows() -> None:
    matrix = review.parameter_adoption_matrix(review.consolidate_candidates())
    ready = matrix.loc[matrix["primary_adoption_class"].isin({
        "configuration_ready",
        "configuration_ready_with_sensitivity",
        "protocol_constant_ready",
    })]
    assert ready["units"].str.len().gt(0).all()
    assert ready["timestep_frequency"].str.len().gt(0).all()
    assert ready["unit_compatibility"].str.len().gt(0).all()
    assert ready["frequency_compatibility"].str.len().gt(0).all()


def test_semantic_mismatch_is_classified() -> None:
    matrix = review.parameter_adoption_matrix(review.consolidate_candidates())
    risk = matrix.loc[
        matrix["parameter_subsection"].eq("4.4.4")
    ].iloc[0]
    close = matrix.loc[
        matrix["parameter_subsection"].eq("4.4.5")
    ].iloc[0]
    assert risk["primary_adoption_class"] == "requires_new_model_mechanism"
    assert risk["semantic_compatibility"].startswith("mismatch")
    assert close["primary_adoption_class"] == "configuration_ready"
    assert "protocol-close" in close["semantic_compatibility"]


def test_implementation_tranche_dependencies_are_ordered() -> None:
    tranches = review.implementation_tranches()
    review.validate_tranche_order(tranches)
    broken = tranches.copy()
    broken.loc[broken["tranche"].eq("B"), "order"] = 0
    with pytest.raises(ValueError, match="dependency"):
        review.validate_tranche_order(broken)


def test_configuration_ready_candidate_schema() -> None:
    matrix = review.parameter_adoption_matrix(review.consolidate_candidates())
    ready = review._configuration_ready(matrix)
    expected = {
        "parameter_subsection", "simulator_field", "current_value",
        "proposed_value", "candidate_source", "uncertainty", "units",
        "primary_adoption_class", "adoption_risk", "required_test",
        "baseline_or_empirical_config",
    }
    assert expected <= set(ready.columns)
    assert not ready.empty


def test_tool_has_no_configuration_or_network_write_path() -> None:
    source = Path(review.__file__).read_text(encoding="utf-8")
    assert "requests." not in source
    assert "urllib" not in source
    assert "yaml.safe_dump" not in source
    assert "config/empirical.yaml" not in source
    assert "config/protocol.yaml" not in source


def test_matrix_generation_is_deterministic() -> None:
    candidates = review.consolidate_candidates()
    first = review.parameter_adoption_matrix(candidates)
    second = review.parameter_adoption_matrix(candidates)
    pd.testing.assert_frame_equal(first, second)


def test_generated_outputs_are_deterministic(tmp_path: Path) -> None:
    output_dir = tmp_path / "adoption_review"
    config = review.AdoptionReviewConfig(output_dir=output_dir)
    review.run_adoption_review(config)
    first = {
        path.name: path.read_bytes()
        for path in sorted(output_dir.iterdir())
        if path.is_file()
    }
    review.run_adoption_review(config)
    second = {
        path.name: path.read_bytes()
        for path in sorted(output_dir.iterdir())
        if path.is_file()
    }
    assert first == second
