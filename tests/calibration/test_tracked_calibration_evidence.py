"""Tracked-only reproducibility checks for compact calibration evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess

from dai_sim.calibration import adoption
from dai_sim.inputs import configuration

from tests.support import REPOSITORY_ROOT


MANIFEST_PATH = (
    REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_ignored(relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative_path],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    return result.returncode == 0


def test_tracked_calibration_evidence_is_content_addressed() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert len(manifest["artefacts"]) == 105
    structural_paths = {
        (
            "data/provenance/calibration/confidence/"
            f"{name}"
        )
        for name in (
            "structural_incompatibility_specification.json",
            "structural_baseline_mismatch.csv",
            "structural_parameter_boundary_trends.csv",
            "structural_variant_registry.json",
            "structural_variant_results.csv",
            "structural_family_summary.json",
            "structural_incompatibility_decision.json",
            "structural_incompatibility_reproducibility.json",
            "structural_incompatibility_benchmark.json",
            "structural_factorial_specification.json",
            "structural_factorial_registry.json",
            "structural_factorial_cells.csv",
            "structural_factorial_effects.csv",
            "structural_factorial_interactions.csv",
            "structural_factorial_cell_summary.json",
            "structural_factorial_interaction_summary.json",
            "structural_factorial_decision.json",
            "structural_factorial_reproducibility.json",
            "structural_factorial_benchmark.json",
            "structural_factorial_precision_specification.json",
            "structural_factorial_precision_audit.csv",
            "structural_factorial_precision_decision.json",
            "structural_factorial_precision_reproducibility.json",
            "structural_factorial_precision_benchmark.json",
        )
    }
    assert structural_paths.issubset(
        {record["path"] for record in manifest["artefacts"]}
    )
    oracle_delay_paths = {
        (
            "data/provenance/calibration/oracle_delay/"
            f"{name}"
        )
        for name in (
            "oracle_delay_freeze_specification.json",
            "oracle_delay_source_inventory.csv",
            "oracle_delay_estimates.csv",
            "oracle_delay_registry.csv",
            "oracle_delay_decision.json",
            "oracle_delay_reproducibility.json",
        )
    }
    assert oracle_delay_paths.issubset(
        {record["path"] for record in manifest["artefacts"]}
    )
    for record in manifest["artefacts"]:
        path = REPOSITORY_ROOT / record["path"]
        assert path.is_file(), record["semantic_name"]
        assert not _is_ignored(record["path"]), record["semantic_name"]
        assert path.stat().st_size == record["size_bytes"]
        assert _sha256(path) == record["sha256"]
        assert record["classification"] in {"snapshot", "runtime_input"}


def test_parameter_adoption_snapshot_has_canonical_schema() -> None:
    path = (
        REPOSITORY_ROOT
        / "data/provenance/calibration/parameter_adoption/"
        "parameter_adoption_matrix.csv"
    )
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 56
    assert len(rows[0]) == 31
    assert {row["parameter_subsection"] for row in rows} == {
        f"4.{section}.{parameter}"
        for section, count in ((1, 7), (2, 8), (3, 12), (4, 6), (5, 10), (6, 13))
        for parameter in range(1, count + 1)
    }
    assert {row["adopted"] for row in rows} == {"False"}


def test_candidate_registry_counts_and_statuses_are_preserved() -> None:
    root = REPOSITORY_ROOT / "data/provenance/calibration"
    market = json.loads(
        (root / "market_gas_protocol/candidate_parameters.json").read_text(
            encoding="utf-8"
        )
    )
    vaults = json.loads(
        (root / "vaults/candidate_parameters.json").read_text(
            encoding="utf-8"
        )
    )
    liquidations = json.loads(
        (root / "liquidations/candidate_parameters.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(market["candidates"]) == 64
    assert len(vaults["candidates"]) == 9
    assert len(liquidations["candidates"]) == 7
    assert liquidations["no_candidate_adopted"] is True


def test_canonical_consumers_use_tracked_evidence() -> None:
    assert configuration.CONFIGURATION_READY_CANDIDATES.is_file()
    assert all(
        relative.startswith("data/provenance/calibration/")
        for relative in configuration.EXPECTED_ADOPTION_REVIEW_CHECKSUMS
    )
    assert all(
        path.is_file()
        and path.is_relative_to(
            REPOSITORY_ROOT / "data/provenance/calibration"
        )
        for path in adoption.REGISTRIES.values()
    )
    assert adoption.PHASE2A_STATUS.is_file()


def test_ignored_diagnostic_copies_remain_optional() -> None:
    ignored = (
        "outputs/diagnostics/calibration/parameter_adoption/"
        "parameter_adoption_matrix.csv",
        "outputs/diagnostics/calibration/market_gas_protocol/"
        "phase2a_candidate_parameters.json",
    )
    assert all(_is_ignored(path) for path in ignored)
    automatic_consumers = (
        REPOSITORY_ROOT / "src/dai_sim/inputs/configuration.py",
        REPOSITORY_ROOT / "src/dai_sim/calibration/adoption.py",
    )
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in automatic_consumers
    )
    assert not any(path in text for path in ignored)


def test_large_empirical_sources_remain_ignored() -> None:
    ignored = (
        "data/market/processed/combined/hourly_market_gas_panel.csv",
        "data/vaults/processed/representative_regimes/"
        "quiet_mature_2024-02-01_2024-03-01/opening_vault_state.csv",
    )
    assert all(_is_ignored(path) for path in ignored)


def test_keeper_execution_evidence_is_partial_and_non_adopted() -> None:
    root = REPOSITORY_ROOT / "data/provenance/calibration/keeper"
    decision = json.loads(
        (root / "keeper_execution_decision.json").read_text(encoding="utf-8")
    )
    reproducibility = json.loads(
        (root / "keeper_execution_reproducibility.json").read_text(
            encoding="utf-8"
        )
    )
    with (
        root / "keeper_execution_registry.csv"
    ).open(encoding="utf-8", newline="") as handle:
        registry = list(csv.DictReader(handle))

    assert decision["capacity"]["classification"] == (
        "shared_capacity_partially_identified"
    )
    assert decision["composition_classification"] == "composition_unresolved"
    assert decision["profit_hurdle"]["classification"] == (
        "profit_hurdle_partially_identified"
    )
    assert decision["overall_classification"] == (
        "shared_keeper_execution_registry_ready_with_partial_identification"
    )
    assert not decision["runtime_adopted"]
    assert not decision["final_validation_used"]
    assert not decision["usdc_svb_used_for_estimation"]
    assert {row["identifier"] for row in registry} == {
        "shared_keeper_capacity_low",
        "shared_keeper_capacity_central",
        "shared_keeper_capacity_high",
    }
    assert [int(row["order"]) for row in registry] == [1, 2, 3]
    assert {row["hurdle_identifier"] for row in registry} == {
        "direct_cost_only",
        "keeper_hurdle_low",
        "keeper_hurdle_high",
    }
    assert all(
        row["population_mapping"] == "direct_system_count"
        for row in registry
    )
    assert {row["runtime_adopted"] for row in registry} == {"False"}
    assert not reproducibility["runtime_adopted"]
    assert not reproducibility["network_access"]
    assert not reproducibility["final_validation_used"]


def test_recovery_redesign_evidence_is_compact_and_non_adopted() -> None:
    root = REPOSITORY_ROOT / "data/provenance/calibration/confidence"
    decision = json.loads(
        (root / "recovery_moment_decision.json").read_text(encoding="utf-8")
    )
    reproducibility = json.loads(
        (root / "recovery_moment_reproducibility.json").read_text(
            encoding="utf-8"
        )
    )
    assert decision["status"] == "conditional_recovery_moment_unsupported"
    assert decision["selected_moment"] is None
    assert decision["stage2_estimate"] is None
    assert not decision["runtime_adopted"]
    assert not reproducibility["objective_values_used"]
    assert not reproducibility["final_validation_data_used"]
    assert not reproducibility["registry_b_used"]
    assert reproducibility["full_search_evaluations"] == 0


def test_objective_identification_evidence_records_the_operationality_stop() -> None:
    root = REPOSITORY_ROOT / "data/provenance/calibration/confidence"
    decision = json.loads(
        (root / "objective_identification_decision.json").read_text(
            encoding="utf-8"
        )
    )
    design = json.loads(
        (root / "identification_design.json").read_text(encoding="utf-8")
    )
    reproducibility = json.loads(
        (root / "identification_reproducibility.json").read_text(
            encoding="utf-8"
        )
    )
    assert decision["status"] == "seven_moment_specification_not_operational"
    assert decision["stage2_estimate"] is None
    assert not decision["candidate_selected"]
    assert not decision["runtime_adopted"]
    assert not design["selection_performed"]
    assert design["anchor_indices"] == []
    assert reproducibility["new_simulation_evaluations"] == 0
    assert not reproducibility["candidate_objective_ranking"]
    assert not reproducibility["registry_b_used"]
    assert reproducibility["usdc_svb_simulations"] == 0
    assert reproducibility["powell_evaluations"] == 0
    assert reproducibility["full_search_evaluations"] == 0


def test_partial_identification_evidence_is_set_valued_and_non_adopted() -> None:
    root = REPOSITORY_ROOT / "data/provenance/calibration/confidence"
    specification = json.loads(
        (root / "partial_identification_specification.json").read_text(
            encoding="utf-8"
        )
    )
    set_summary = json.loads(
        (root / "partial_identification_set.json").read_text(encoding="utf-8")
    )
    representatives = json.loads(
        (root / "partial_identification_representatives.json").read_text(
            encoding="utf-8"
        )
    )
    reproducibility = json.loads(
        (root / "partial_identification_reproducibility.json").read_text(
            encoding="utf-8"
        )
    )
    with (
        root / "partial_identification_candidates.csv"
    ).open(encoding="utf-8", newline="") as handle:
        candidates = list(csv.DictReader(handle))

    assert len(candidates) == 256
    assert {int(row["candidate_index"]) for row in candidates} == set(range(256))
    assert not any(
        token in column.lower()
        for column in candidates[0]
        for token in ("objective", "rank")
    )
    assert specification["scalar_objective"] is None
    assert set_summary["parameter_estimate"] is None
    assert representatives["parameter_estimate"] is None
    assert not representatives["candidate_62_preference"]
    assert representatives["representative_count"] <= 24
    assert not reproducibility["parameter_selected"]
    assert not reproducibility["runtime_adopted"]
    assert not reproducibility["registry_b_used"]
    assert not reproducibility["validation_data_used"]
