"""Validation helpers for the portable scientific-evidence boundary.

The submitted repository contains compact evidence contracts rather than the
large historical checkpoint trees.  These helpers validate the compact
boundary without replaying any scientific workflow.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file


PORTABILITY_ROOT = (
    REPOSITORY_ROOT / "data/provenance/maintenance/submission_portability"
)
CONTRACTS_PATH = PORTABILITY_ROOT / "historical_reconstruction_contracts.json"
SPECIFICATION_PATH = PORTABILITY_ROOT / "portability_specification.json"
DECISION_PATH = PORTABILITY_ROOT / "portability_decision.json"
REPRODUCIBILITY_PATH = PORTABILITY_ROOT / "portability_reproducibility.json"
MAINTENANCE_HISTORY_PATH = PORTABILITY_ROOT / "maintenance_executable_history.json"
PORTABLE_SUBMISSION_CLASSIFICATION = "portable_submission_evidence_v1"


def canonical_sha256(value: object) -> str:
    """Return the SHA-256 of deterministic compact JSON."""
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_reconstruction_contracts(
    path: Path = CONTRACTS_PATH,
    *,
    expected_study_count: int | None = 10,
) -> dict[str, Any]:
    """Load and validate every tracked historical reconstruction contract."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    studies = payload.get("studies")
    if payload.get("schema_version") != 1 or not isinstance(studies, list):
        raise ValueError("Historical reconstruction contracts are malformed.")
    identifiers = [study.get("study_identifier") for study in studies]
    if (
        expected_study_count is not None
        and len(studies) != expected_study_count
    ) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Historical reconstruction study ownership differs.")
    for study in studies:
        if study.get("reconstruction_status") != "external_artifacts_optional":
            raise ValueError("Historical reconstruction status differs.")
        for field in ("specification", "decision"):
            owner = study[field]
            source = REPOSITORY_ROOT / owner["path"]
            if sha256_file(source) != owner["sha256"]:
                raise ValueError(
                    f"Historical {field} changed: {study['study_identifier']}."
                )
        compact = study.get("compact_evidence")
        if not isinstance(compact, list) or len(compact) < 3:
            raise ValueError("Compact evidence ownership is incomplete.")
        for owner in compact:
            source = REPOSITORY_ROOT / owner["path"]
            if sha256_file(source) != owner["sha256"]:
                raise ValueError(f"Compact evidence changed: {owner['path']}.")
    expected = payload.get("registry_content_sha256")
    identity_payload = dict(payload)
    identity_payload.pop("registry_content_sha256", None)
    if expected != canonical_sha256(identity_payload):
        raise ValueError("Historical reconstruction registry identity differs.")
    return payload


def submission_identity_payload(
    specification: Mapping[str, Any],
    contract_registry_sha256: str,
) -> dict[str, Any]:
    """Return the content-addressed portable-submission identity payload."""
    return {
        "classification": specification["classification"],
        "first_portable_runtime_identity": specification[
            "first_portable_runtime_identity"
        ],
        "stage1_derivative_sha256": specification["stage1"]["derivative_sha256"],
        "oracle_inventory_sha256": specification["oracle_delay"][
            "inventory_sha256"
        ],
        "reconstruction_contract_registry_sha256": contract_registry_sha256,
        "test_support_sources": specification["test_support_sources"],
        "clean_checkout_suite_contract": specification[
            "clean_checkout_suite_contract"
        ],
        "excluded_source_categories": specification[
            "excluded_source_categories"
        ],
        "network_calls": specification["network_calls"],
    }


def validate_portability_bundle() -> dict[str, Any]:
    """Validate the complete second submission-portability contract."""
    contracts = load_reconstruction_contracts()
    specification = json.loads(SPECIFICATION_PATH.read_text(encoding="utf-8"))
    decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))
    reproducibility = json.loads(
        REPRODUCIBILITY_PATH.read_text(encoding="utf-8")
    )
    maintenance_history = json.loads(
        MAINTENANCE_HISTORY_PATH.read_text(encoding="utf-8")
    )
    expected_identity = canonical_sha256(
        submission_identity_payload(
            specification,
            sha256_file(CONTRACTS_PATH),
        )
    )
    identities = {
        specification.get("portable_submission_identity"),
        decision.get("portable_submission_identity"),
        reproducibility.get("portable_submission_identity"),
    }
    if identities != {expected_identity}:
        raise ValueError("Portable-submission identity differs.")
    support_paths = {
        "stage1_loader": REPOSITORY_ROOT / "src/dai_sim/inputs/stage1.py",
        "stage1_derivative_builder": REPOSITORY_ROOT
        / "workflows/inputs/build_stage1_residual_source.py",
        "stage1_runtime_adapter": REPOSITORY_ROOT
        / "src/dai_sim/calibration/event_simulation.py",
        "keeper_compact_fallback": REPOSITORY_ROOT
        / "src/dai_sim/calibration/keeper_execution.py",
        "oracle_inventory_fallback": REPOSITORY_ROOT
        / "src/dai_sim/calibration/oracle_delay.py",
        "structural_registry_fallback": REPOSITORY_ROOT
        / "src/dai_sim/calibration/structural_incompatibility.py",
        "experiment_compact_fallback": REPOSITORY_ROOT
        / "src/dai_sim/experiments/final/stable_collateral_tradeoff.py",
    }
    historical_support = maintenance_history.get("historical_test_support_sources", {})
    observed_support = {
        name: sha256_file(path) for name, path in support_paths.items()
    }
    observed_support.update(
        {
            name: historical_support[name]["sha256"]
            for name in ("portability_validator", "external_verifier")
        }
    )
    if specification.get("test_support_sources") != observed_support:
        raise ValueError("Portable test-support source checksum differs.")
    verifier_relocation = next(
        item
        for item in maintenance_history.get("relocations", [])
        if item.get("classification") == "user_verification"
    )
    current_verifier = REPOSITORY_ROOT / verifier_relocation["current_path"]
    if sha256_file(current_verifier) != verifier_relocation["current_sha256"]:
        raise ValueError("Current external verifier checksum differs.")
    if maintenance_history.get("portable_submission_evidence_identity") != expected_identity:
        raise ValueError("Maintenance history changed portable-submission identity.")
    required = {
        "historical_scientific_identities_preserved": True,
        "full_historical_checkpoints_packaged": False,
        "full_raw_source_inventory_packaged": False,
        "ordinary_suite_self_contained": True,
        "scientific_value_changes": 0,
    }
    if any(decision.get(key) != value for key, value in required.items()):
        raise ValueError("Portable-submission decision differs.")
    if reproducibility.get("network_calls") != 0:
        raise ValueError("Network access entered portability reconstruction.")
    return {
        "status": "passed",
        "portable_submission_identity": expected_identity,
        "study_count": len(contracts["studies"]),
        "readiness": decision["readiness"],
    }
