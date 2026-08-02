"""Semantic validators for tracked compact scientific evidence.

These helpers deliberately validate registered artefacts without reading the
ignored worker, checkpoint or diagnostic trees that produced them.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from tests.support import REPOSITORY_ROOT


CONFIDENCE_EVIDENCE = REPOSITORY_ROOT / "data/provenance/calibration/confidence"
CALIBRATION_MANIFEST = REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
KEEPER_EVIDENCE = REPOSITORY_ROOT / "data/provenance/calibration/keeper"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_rows(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return tuple(reader.fieldnames or ()), list(reader)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_manifest_entries(paths: tuple[Path, ...]) -> None:
    artefacts = {
        item["path"]: item
        for item in _json(CALIBRATION_MANIFEST)["artefacts"]
    }
    for path in paths:
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        assert relative in artefacts, f"Compact evidence is unregistered: {relative}"
        assert artefacts[relative]["sha256"] == _sha256(path)
        assert artefacts[relative]["size_bytes"] == path.stat().st_size


def validate_structural_factorial_compact_evidence() -> dict[str, Any]:
    """Validate factorial and precision evidence by semantic identifiers."""
    names = (
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
    paths = tuple(CONFIDENCE_EVIDENCE / name for name in names)
    _validate_manifest_entries(paths)

    specification = _json(paths[0])
    registry = _json(paths[1])
    cell_columns, cells = _csv_rows(paths[2])
    effect_columns, effects = _csv_rows(paths[3])
    interaction_columns, interactions = _csv_rows(paths[4])
    decision = _json(paths[7])
    reproducibility = _json(paths[8])
    precision_specification = _json(paths[10])
    precision_columns, precision = _csv_rows(paths[11])
    precision_decision = _json(paths[12])
    precision_reproducibility = _json(paths[13])

    factorial_identity = specification["factorial_identity"]
    precision_identity = specification["precision_validation_identity"]
    assert factorial_identity == registry["factorial_identity"]
    assert factorial_identity == reproducibility["factorial_identity"]
    assert factorial_identity == precision_specification["source_factorial_identity"]
    assert factorial_identity == precision_decision["factorial_identity"]
    assert factorial_identity == precision_reproducibility["factorial_identity"]
    assert precision_identity == reproducibility["precision_validation_identity"]
    assert precision_identity == precision_specification["precision_validation_identity"]
    assert precision_identity == precision_decision["precision_validation_identity"]
    assert precision_identity == precision_reproducibility["precision_validation_identity"]

    candidates = tuple(str(value) for value in specification["candidate_panel"])
    cells_registered = tuple(specification["cells"])
    moments = tuple(item["moment"] for item in specification["empirical_bands"])
    factors = tuple(specification["factor_order"])
    effects_registered = ("A", "B", "C", "AB", "AC", "BC", "ABC")
    interaction_cells = ("110", "101", "011", "111")

    assert factors == tuple(registry["factor_order"])
    assert len(factors) == 3
    assert len(cells_registered) == registry["cell_count"] == 8
    assert {item["binary_code"] for item in registry["cells"]} == set(cells_registered)
    assert len(candidates) == 16
    assert specification["events"] == 74
    assert specification["replications"] == 128
    assert len(moments) == 5

    assert {row["cell_id"].zfill(3) for row in cells} == set(cells_registered)
    assert {row["candidate_index"] for row in cells} == set(candidates)
    assert {row["moment"] for row in cells} == set(moments)
    assert len(cells) == len(cells_registered) * len(candidates) * len(moments)
    assert len({(row["cell_id"], row["candidate_index"], row["moment"]) for row in cells}) == len(cells)

    assert {row["candidate_index"] for row in effects} == set(candidates)
    assert {row["moment"] for row in effects} == set(moments)
    assert {row["effect"] for row in effects} == set(effects_registered)
    assert len(effects) == len(candidates) * len(moments) * len(effects_registered)
    assert len({(row["candidate_index"], row["moment"], row["effect"]) for row in effects}) == len(effects)

    assert {row["interaction_cell"].zfill(3) for row in interactions} == set(interaction_cells)
    assert {row["candidate_index"] for row in interactions} == set(candidates)
    assert {row["moment"] for row in interactions} == set(moments)
    assert len(interactions) == len(interaction_cells) * len(candidates) * len(moments)

    prefixes = tuple(
        str(value)
        for value in (
            *precision_specification["nested_prefixes"],
            precision_specification["extended_replications"],
        )
    )
    assert {row["replication_prefix"] for row in precision} == set(prefixes)
    assert {row["candidate_index"] for row in precision} == set(candidates)
    assert {row["moment"] for row in precision} == set(moments)
    assert {row["effect"] for row in precision} == set(effects_registered)
    assert len(precision) == len(prefixes) * len(candidates) * len(moments) * len(effects_registered)
    assert all(row["event_count"] == "74" for row in precision)
    assert all(row["replication_count"] == row["replication_prefix"] for row in precision)

    assert len(reproducibility["new_checkpoint_checksums"]) == 64
    assert len(precision_reproducibility["original_checkpoint_identities"]) == 64
    assert len(precision_reproducibility["extension_checkpoint_identities"]) == 128
    assert len(precision_reproducibility["prefix_checksums"]) == 128
    assert precision_decision["gate_pass"]
    assert precision_decision["validity_status"] == "passed"
    assert decision["final_classification"] == "factorial_interactions_reveal_tradeoffs"
    assert decision["selected_cell"] is None
    assert decision["selected_parameter"] is None
    assert not any(
        payload.get("runtime_adopted")
        for payload in (
            specification,
            registry,
            decision,
            reproducibility,
            precision_specification,
            precision_decision,
            precision_reproducibility,
        )
    )
    return {
        "status": "passed",
        "mismatch_classification": "missing_runtime_context_only",
        "factorial_identity": factorial_identity,
        "precision_identity": precision_identity,
        "cell_rows": len(cells),
        "effect_rows": len(effects),
        "interaction_rows": len(interactions),
        "precision_audit_rows": len(precision),
        "cell_columns": cell_columns,
        "effect_columns": effect_columns,
        "interaction_columns": interaction_columns,
        "precision_columns": precision_columns,
        "final_classification": decision["final_classification"],
        "reused_cell_identities": reproducibility["reused_cell_identities"],
        "reused_cell_order": specification["reused_cells"],
        "new_cell_identities": reproducibility["new_cell_identities"],
        "reused_evaluations": reproducibility["reused_evaluations"],
        "new_evaluations": reproducibility["new_evaluations"],
        "total_represented_evaluations": reproducibility[
            "total_represented_evaluations"
        ],
    }


def validate_keeper_execution_compact_evidence() -> dict[str, Any]:
    """Validate the frozen keeper design and results without raw panels."""
    names = (
        "keeper_execution_specification.json",
        "keeper_execution_decision.json",
        "keeper_execution_reproducibility.json",
        "keeper_execution_registry.csv",
        "keeper_capacity_frontier.csv",
        "keeper_hourly_panel_summary.csv",
        "keeper_profit_hurdle.csv",
        "keeper_collateral_comparability.csv",
        "keeper_execution_benchmark.json",
    )
    paths = tuple(KEEPER_EVIDENCE / name for name in names)
    _validate_manifest_entries(paths)
    specification = _json(paths[0])
    decision = _json(paths[1])
    reproducibility = _json(paths[2])
    registry_columns, registry = _csv_rows(paths[3])
    frontier_columns, frontier = _csv_rows(paths[4])
    panel_columns, panel = _csv_rows(paths[5])
    hurdle_columns, hurdle = _csv_rows(paths[6])

    assert _sha256(paths[0]) == reproducibility["preregistration_sha256"]
    assert specification["source_checksums"] == reproducibility["source_checksums"]
    assert specification["no_final_validation_use"]
    assert specification["no_runtime_adoption"]
    assert "usdc_svb" in specification["scope"]["excluded_estimation_windows"]
    assert not reproducibility["final_validation_used"]
    assert not reproducibility["usdc_svb_used_for_estimation"]
    assert reproducibility["deterministic_serialisation"]
    assert reproducibility["live_acquisition_calls"] == 0
    assert not reproducibility["network_access"]

    capacities = tuple(int(row["shared_capacity_value"]) for row in registry)
    hurdle_values = {row["hurdle_identifier"]: float(row["hurdle_value"]) for row in registry}
    assert capacities == (14, 26, 45)
    assert hurdle_values["direct_cost_only"] == 0.0
    assert 0.0 < hurdle_values["keeper_hurdle_low"] < hurdle_values["keeper_hurdle_high"]
    assert all(row["capacity_status"] == "shared_capacity_partially_identified" for row in registry)
    assert all(row["composition_status"] == "composition_unresolved" for row in registry)
    assert all(row["runtime_adopted"] == "False" for row in registry)
    assert _sha256(paths[3]) == "58c5754ed95dead1ad283a7961fb0588496804a94f58ddb0e196a57601ee1e1b"

    capacity = decision["capacity"]
    profit = decision["profit_hurdle"]
    assert capacity["profiles"] == {"central": 26, "high": 45, "low": 14}
    assert capacity["classification"] == "shared_capacity_partially_identified"
    assert decision["composition_classification"] == "composition_unresolved"
    assert decision["no_physical_maximum_claim"]
    assert profit["classification"] == "profit_hurdle_partially_identified"
    assert profit["direct_cost_only_hurdle"] == 0.0
    assert profit["genuinely_negative_or_rejected_evidence_count"] == 0
    assert not decision["runtime_adopted"]
    assert not decision["default_profiles_changed"]

    sample_ids = {row["sample_identifier"] for row in panel}
    assert "window=quiet_mature;scope=SYSTEM_ALL" in sample_ids
    assert "window=terra_cefi;scope=SYSTEM_ALL" in sample_ids
    assert not any("usdc" in value.lower() or "svb" in value.lower() for value in sample_ids)
    assert {row["row_type"] for row in frontier} >= {"frontier", "calendar_block_p90", "composition"}
    system_rows = [row for row in panel if row["sample_identifier"] in {
        "window=quiet_mature;scope=SYSTEM_ALL",
        "window=terra_cefi;scope=SYSTEM_ALL",
    }]
    assert sum(int(row["observation_count"]) for row in system_rows) == 1_800
    terra = next(row for row in system_rows if "terra_cefi" in row["sample_identifier"])
    assert round(float(terra["closure_mean"]) * int(terra["observation_count"])) == 649
    assert any(row["scope"] == "SYSTEM_ALL" for row in hurdle)
    return {
        "status": "passed",
        "specification": specification,
        "decision": decision,
        "reproducibility": reproducibility,
        "registry": registry,
        "frontier": frontier,
        "panel": panel,
        "hurdle": hurdle,
        "registry_columns": registry_columns,
        "frontier_columns": frontier_columns,
        "panel_columns": panel_columns,
        "hurdle_columns": hurdle_columns,
    }


def validate_monte_carlo_estimator_audit() -> dict[str, Any]:
    """Validate the registered negative eligibility audit without its cache."""
    path = CONFIDENCE_EVIDENCE / "monte_carlo_estimator_audit.json"
    _validate_manifest_entries((path,))
    audit = _json(path)
    assert audit["existing_estimator_classification"] == "correct_hierarchical_mcse"
    assert audit["existing_replication_index_values_reproduced"]
    assert audit["committed_failure_reproduction"] == {
        "candidate_count": 256,
        "mcse_valid": 0,
        "next_stage_eligible": 0,
        "numerical_bound_valid": 53,
        "objective_valid": 256,
        "structural_valid": 256,
    }
    implication = audit["search_eligibility_implication"]
    assert implication["committed_mcse_valid_candidates"] == 0
    assert implication["audited_mcse_valid_candidates"] == 0
    assert not implication["eligibility_result_changes"]
    assert not audit["candidate_selected"]
    assert not audit["runtime_adopted"]
    return audit


def validate_partial_identification_compact_evidence() -> dict[str, Any]:
    """Validate partial-identification ownership without ignored run context."""
    names = (
        "partial_identification_specification.json",
        "partial_identification_candidates.csv",
        "partial_identification_constraints.csv",
        "partial_identification_representatives.json",
        "partial_identification_set.json",
        "partial_identification_reproducibility.json",
        "structural_incompatibility_specification.json",
        "structural_incompatibility_decision.json",
        "structural_incompatibility_reproducibility.json",
        "structural_variant_results.csv",
    )
    paths = tuple(CONFIDENCE_EVIDENCE / name for name in names)
    _validate_manifest_entries(paths)
    specification = _json(paths[0])
    candidate_columns, candidates = _csv_rows(paths[1])
    constraint_columns, constraints = _csv_rows(paths[2])
    decision = _json(paths[4])
    reproducibility = _json(paths[5])
    structural_specification = _json(paths[6])
    structural_decision = _json(paths[7])
    structural_reproducibility = _json(paths[8])
    variant_columns, variants = _csv_rows(paths[9])

    set_id = specification["partial_identification_identity"]
    assert set_id == decision["set_id"]
    assert set_id == reproducibility["set_id"]
    assert set_id == structural_specification["fixed_baseline"]["partial_identification_identity"]
    assert set_id == structural_reproducibility["source_partial_identification_identity"]
    assert specification["event_count"] == reproducibility["event_count"] == 74
    assert specification["replication_count"] == reproducibility["replication_count"] == 64
    assert specification["sobol_candidate_count"] == reproducibility["evaluated_candidates"] == 256
    assert len(candidates) == 256
    assert len(constraints) == 5
    assert len(structural_specification["candidate_panel"]) == 16
    assert structural_specification["events"] == 74
    assert structural_specification["replications"] == 64
    assert len(variants) == 12 * 16 * 5

    cache_identity = specification["cache_identity"]
    assert cache_identity == reproducibility["source_cache_identity"]
    assert cache_identity["cache_root_sha256"] == structural_reproducibility["all_event_cache_root_sha256"]
    assert structural_specification["candidate_panel_sha256"] == structural_reproducibility["panel_sha256"]
    assert decision["final_classification"] == "model_evidence_incompatibility"
    assert structural_decision["overall_classification"] == "multiple_structural_families_contribute"
    assert not decision["runtime_adopted"]
    assert not reproducibility["runtime_adopted"]
    assert not reproducibility["parameter_selected"]
    assert reproducibility["candidate_rankings"] == 0
    assert reproducibility["scalar_objective_evaluations"] == 0
    assert not structural_reproducibility["objective_ranking_used"]
    assert not structural_reproducibility["parameter_selected"]
    assert not structural_reproducibility["structural_model_selected"]
    return {
        "status": "passed",
        "partial_identification_identity": set_id,
        "all_event_cache_root_sha256": cache_identity["cache_root_sha256"],
        "panel_sha256": structural_specification["candidate_panel_sha256"],
        "baseline_rows_reused": 16 * 74 * 64,
        "candidate_columns": candidate_columns,
        "constraint_columns": constraint_columns,
        "variant_columns": variant_columns,
    }
