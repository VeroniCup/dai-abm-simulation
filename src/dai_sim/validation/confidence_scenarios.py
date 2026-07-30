"""Validation and compact evidence for frozen confidence scenarios."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
import json
import math
import os
import tempfile

from dai_sim.inputs.confidence_scenarios import (
    ConfidenceScenarioRegistry,
    DEFAULT_REGISTRY_PATH,
    EXPECTED_SCENARIO_ORDER,
    FACTORIAL_DECISION_CHECKSUM,
    PRECISION_DECISION_CHECKSUM,
    PROFILE_BEHAVIOUR_CHECKSUMS,
    REPOSITORY_ROOT,
    RESIDUAL_BLOCK_CHECKSUM,
    STAGE1_ABOVE_PEG_RESPONSE,
    STAGE1_BELOW_PEG_RESPONSE,
    STAGE1_MARKET_CHECKSUM,
    STAGE1_RESIDUAL_EVIDENCE_CHECKSUM,
    _sha256_bytes,
    load_confidence_scenario_registry,
    registry_csv_bytes,
    resolve_confidence_scenario,
)
from dai_sim.model.confidence import (
    PersistentConfidenceState,
    RecoveryGateInputs,
    update_persistent_confidence,
)
from dai_sim.model.market import coefficient_normalised_market_response


DEFAULT_EVIDENCE_DIR = (
    REPOSITORY_ROOT / "data/provenance/experiments/confidence"
)
DEFAULT_MANIFEST_PATH = (
    REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"
)
DEFAULT_MANIFEST_PURPOSE = (
    "Content-addressed experimental-design evidence; no parameter "
    "estimate or selected scenario."
)


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def controlled_mechanism_smoke(
    registry: ConfidenceScenarioRegistry | None = None,
) -> dict[str, Any]:
    """Run a compact deterministic mechanism smoke, not an experiment."""
    owner = registry or load_confidence_scenario_registry()
    results: dict[str, Any] = {}
    common_recovery_start = 0.8
    gate_closed = RecoveryGateInputs(False, True, False)
    gate_open = RecoveryGateInputs(True, True, False)
    for scenario in owner.scenarios:
        activation = resolve_confidence_scenario(
            scenario.identifier,
            registry_path=owner.configuration_path,
        )
        if not scenario.enabled:
            confidence_path = [1.0] * 30
            panic_path = [0.0] * 30
            recovery_once = 1.0
        else:
            assert activation.persistent_config is not None
            state = PersistentConfidenceState.initial()
            confidence_path = []
            panic_path = []
            for _ in range(3):
                update = update_persistent_confidence(
                    state,
                    activation.persistent_config,
                    scaled_peg_gap=0.8,
                    scaled_collateral_stress=0.8,
                    recovery_inputs=gate_closed,
                )
                state = update.state
                confidence_path.append(state.confidence)
                response = coefficient_normalised_market_response(
                    dai_price=0.98,
                    confidence=state.confidence,
                    below_peg_response=float(STAGE1_BELOW_PEG_RESPONSE),
                    above_peg_response=float(STAGE1_ABOVE_PEG_RESPONSE),
                    panic_response=activation.panic_response,
                    residual_innovation=0.0,
                    min_price=0.5,
                    max_price=1.5,
                )
                panic_path.append(response.panic_component)
            for _ in range(27):
                update = update_persistent_confidence(
                    state,
                    activation.persistent_config,
                    scaled_peg_gap=0.0,
                    scaled_collateral_stress=0.0,
                    recovery_inputs=gate_open,
                )
                state = update.state
                confidence_path.append(state.confidence)
                response = coefficient_normalised_market_response(
                    dai_price=0.98,
                    confidence=state.confidence,
                    below_peg_response=float(STAGE1_BELOW_PEG_RESPONSE),
                    above_peg_response=float(STAGE1_ABOVE_PEG_RESPONSE),
                    panic_response=activation.panic_response,
                    residual_innovation=0.0,
                    min_price=0.5,
                    max_price=1.5,
                )
                panic_path.append(response.panic_component)
            recovery_state = PersistentConfidenceState(
                common_recovery_start,
                owner.stability_hours - 1,
                False,
            )
            recovery_once = update_persistent_confidence(
                recovery_state,
                activation.persistent_config,
                scaled_peg_gap=0.0,
                scaled_collateral_stress=0.0,
                recovery_inputs=gate_open,
            ).state.confidence
        if not all(math.isfinite(value) for value in confidence_path + panic_path):
            raise ValueError("Confidence scenario smoke produced non-finite values.")
        if not all(0.0 <= value <= 1.0 for value in confidence_path):
            raise ValueError("Confidence scenario smoke left [0, 1].")
        results[scenario.identifier] = {
            "confidence_path": confidence_path,
            "panic_component_path": panic_path,
            "common_start_one_step_recovery": recovery_once,
            "metadata": activation.metadata,
        }
    if _canonical_json_bytes(
        resolve_confidence_scenario(
            None, registry_path=owner.configuration_path
        ).metadata
    ) != _canonical_json_bytes(
        resolve_confidence_scenario(
            "stage1_only", registry_path=owner.configuration_path
        ).metadata
    ):
        raise ValueError("Missing scenario and stage1_only are not identical.")
    resilient = results["confidence_resilient"]
    central = results["confidence_central"]
    fragile = results["confidence_fragile"]
    if not (
        resilient["confidence_path"][0]
        > central["confidence_path"][0]
        > fragile["confidence_path"][0]
    ):
        raise ValueError("Controlled deterioration ordering failed.")
    if not (
        central["common_start_one_step_recovery"]
        > resilient["common_start_one_step_recovery"]
        == fragile["common_start_one_step_recovery"]
    ):
        raise ValueError("Coupled raw-recovery smoke ordering failed.")
    common_confidence = 0.5
    panic = {}
    for identifier in EXPECTED_SCENARIO_ORDER[1:]:
        scenario = owner.by_identifier(identifier)
        assert scenario.panic_response is not None
        panic[identifier] = abs(
            coefficient_normalised_market_response(
                dai_price=0.98,
                confidence=common_confidence,
                below_peg_response=float(STAGE1_BELOW_PEG_RESPONSE),
                above_peg_response=float(STAGE1_ABOVE_PEG_RESPONSE),
                panic_response=float(scenario.panic_response),
                residual_innovation=0.0,
                min_price=0.5,
                max_price=1.5,
            ).panic_component
        )
    if not (
        panic["confidence_fragile"]
        > panic["confidence_central"]
        > panic["confidence_resilient"]
    ):
        raise ValueError("Controlled panic ordering failed.")
    return {
        "schema_version": 1,
        "purpose": "deterministic mechanism integration smoke only",
        "scenario_results": results,
        "panic_magnitude_at_common_state": panic,
        "default_equals_explicit_stage1_only": True,
        "substantive_experiment": False,
        "runtime_adopted": False,
    }


def _default_invariance_payload() -> dict[str, Any]:
    """Return frozen profile behaviour identities without changing profiles."""
    return {
        "profile_behaviour_sha256": dict(PROFILE_BEHAVIOUR_CHECKSUMS),
        "stage1_market_evidence_sha256": STAGE1_MARKET_CHECKSUM,
        "stage1_residual_evidence_sha256": STAGE1_RESIDUAL_EVIDENCE_CHECKSUM,
        "residual_block_sha256": RESIDUAL_BLOCK_CHECKSUM,
        "factorial_decision_sha256": FACTORIAL_DECISION_CHECKSUM,
        "precision_decision_sha256": PRECISION_DECISION_CHECKSUM,
    }


def evidence_payloads(
    registry: ConfidenceScenarioRegistry | None = None,
) -> dict[str, bytes]:
    """Construct all compact scenario evidence deterministically."""
    owner = registry or load_confidence_scenario_registry()
    smoke = controlled_mechanism_smoke(owner)
    smoke_sha256 = _sha256_bytes(_canonical_json_bytes(smoke))
    active_records = [
        scenario.record()
        for scenario in owner.scenarios
        if scenario.enabled
    ]
    specification = {
        "schema_version": 1,
        "purpose": (
            "Pre-register four transparent confidence scenarios after closure "
            "of empirical calibration rescue."
        ),
        "calibration_closure": {
            "classification": "factorial_interactions_reveal_tradeoffs",
            "factorial_identity": (
                "4558b97de3c092b8cec70b9117407333527f517559b7126fa0428c5e9059ad00"
            ),
            "precision_identity": (
                "107c5698528ad433371a7d7f49ffde533691c30c032b92edf47b1cf5611cac52"
            ),
            "factorial_decision_sha256": FACTORIAL_DECISION_CHECKSUM,
        },
        "source_domain": {
            "path": owner.source_domain_path,
            "sha256": owner.source_domain_sha256,
            "transform_owner": owner.transform_owner,
        },
        "authoritative_inverse_transform": {
            "deterioration_adjustment": "alpha_d = u_d",
            "recovery_ratio": "rho_r = u_r",
            "recovery_adjustment": "alpha_r = alpha_d * rho_r",
            "confidence_floor": "C_min = u_C",
            "panic_response": "kappa_P = 2.75454 * u_P",
        },
        "recovery_ratio_interpretation": (
            "Independent canonical recovery strength relative to the same "
            "scenario's deterioration adjustment."
        ),
        "fixed_scenarios": [scenario.record() for scenario in owner.scenarios],
        "valid_ordering": {
            "deterioration": "fragile > central > resilient",
            "recovery_ratio": "resilient > central > fragile",
            "confidence_floor": "resilient > central > fragile",
            "panic_response": "fragile > central > resilient",
        },
        "raw_recovery_adjustment_ordering": (
            "central > resilient = fragile; no resilient-to-fragile ordering "
            "is required"
        ),
        "structural_formulation": dict(owner.structural_formulation),
        "default_scenario": "stage1_only",
        "no_model_selection": True,
        "no_empirical_estimate_claim": True,
        "final_validation_used": False,
        "runtime_adopted": False,
    }
    reproducibility = {
        "schema_version": 1,
        "source_domain_path": owner.source_domain_path,
        "source_domain_sha256": owner.source_domain_sha256,
        "transform_owner": owner.transform_owner,
        "exact_decimal_derivation": (
            "Decimal canonical strings; multiply alpha_d*rho_r and "
            "2.75454*u_P without binary-float scenario construction"
        ),
        "serialisation": (
            "UTF-8; JSON sorted keys with two-space indent and final newline; "
            "CSV fixed columns and LF line endings"
        ),
        "registry_sha256": owner.registry_sha256,
        "configuration_path": str(
            owner.configuration_path.relative_to(REPOSITORY_ROOT)
        ),
        "configuration_sha256": owner.configuration_sha256,
        "default_invariance": _default_invariance_payload(),
        "mechanism_smoke_sha256": smoke_sha256,
        "mechanism_smoke_substantive": False,
        "source_values": active_records,
        "sobol_candidate_used": False,
        "candidate_identity_used": False,
        "objective_value_used": False,
        "partial_identification_result_used_for_values": False,
        "factorial_cell_used": False,
        "interaction_result_used_for_values": False,
        "final_validation_event_used": False,
        "production_adoption": False,
        "runtime_adopted": False,
    }
    decision = {
        "schema_version": 1,
        "confidence_calibration_rescue_closed": True,
        "scenario_count": 4,
        "scenario_order": list(EXPECTED_SCENARIO_ORDER),
        "second_coordinate": "recovery_ratio",
        "no_scenario_represents_truth": True,
        "scenario_ranked": False,
        "scenario_selected": None,
        "production_baseline": "stage1_only",
        "next_authorised_boundary": (
            "Pre-register the ETH-only recovery experiment matrix, then use "
            "the same scenarios as a multi-collateral robustness dimension."
        ),
        "substantive_recovery_experiment_authorised_in_this_pass": False,
        "multi_collateral_experiment_authorised_in_this_pass": False,
        "runtime_adopted": False,
    }
    return {
        "confidence_scenario_specification.json": _canonical_json_bytes(
            specification
        ),
        "confidence_scenario_registry.csv": registry_csv_bytes(owner),
        "confidence_scenario_reproducibility.json": _canonical_json_bytes(
            reproducibility
        ),
        "confidence_scenario_decision.json": _canonical_json_bytes(decision),
    }


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".partial",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _manifest_relative_path(path: Path) -> str:
    """Return repository-relative provenance, with a test-directory fallback."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return resolved.name


def _confidence_manifest_records(
    destination: Path,
    payloads: Mapping[str, bytes],
    checksums: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Return the four confidence-owned records for the shared manifest."""
    return [
        {
            "path": _manifest_relative_path(destination / name),
            "sha256": checksums[name],
            "size_bytes": len(payloads[name]),
            "classification": "scenario_defined_experimental_design",
            "runtime_adopted": False,
        }
        for name in sorted(payloads)
    ]


def _merged_experiment_manifest(
    manifest_path: Path,
    confidence_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge confidence records without replacing other experiment evidence."""
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(existing, Mapping):
            raise ValueError("Experiment-provenance manifest must be a mapping.")
        existing_records = existing.get("artefacts", ())
        if not isinstance(existing_records, list):
            raise ValueError("Experiment-provenance artefacts must be a list.")
        if existing.get("artefact_count") != len(existing_records):
            raise ValueError("Experiment-provenance artefact count is inconsistent.")
        manifest = dict(existing)
    else:
        existing_records = []
        manifest = {
            "schema_version": 1,
            "purpose": DEFAULT_MANIFEST_PURPOSE,
        }

    confidence_paths = {record["path"] for record in confidence_records}
    retained: list[dict[str, Any]] = []
    observed_paths: set[str] = set()
    for record in existing_records:
        if not isinstance(record, Mapping) or not isinstance(
            record.get("path"), str
        ):
            raise ValueError("Experiment-provenance record has no valid path.")
        path = str(record["path"])
        if path in observed_paths:
            raise ValueError(
                f"Duplicate experiment-provenance path: {path}."
            )
        observed_paths.add(path)
        if path not in confidence_paths:
            retained.append(dict(record))

    artefacts = sorted(
        [*retained, *confidence_records],
        key=lambda record: str(record["path"]),
    )
    manifest["artefacts"] = artefacts
    manifest["artefact_count"] = len(artefacts)
    return manifest


def write_confidence_scenario_evidence(
    *,
    evidence_dir: Path | str = DEFAULT_EVIDENCE_DIR,
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
) -> dict[str, str]:
    """Write compact evidence and its experiment-provenance manifest."""
    registry = load_confidence_scenario_registry(registry_path)
    payloads = evidence_payloads(registry)
    destination = Path(evidence_dir)
    checksums: dict[str, str] = {}
    for name, payload in payloads.items():
        _atomic_write(destination / name, payload)
        checksums[name] = _sha256_bytes(payload)
    confidence_records = _confidence_manifest_records(
        destination,
        payloads,
        checksums,
    )
    manifest_destination = Path(manifest_path)
    manifest = _merged_experiment_manifest(
        manifest_destination,
        confidence_records,
    )
    _atomic_write(
        manifest_destination,
        _canonical_json_bytes(manifest),
    )
    return checksums


def validate_confidence_scenario_evidence(
    *,
    evidence_dir: Path | str = DEFAULT_EVIDENCE_DIR,
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    """Validate tracked evidence against deterministic reconstruction."""
    registry = load_confidence_scenario_registry(registry_path)
    expected = evidence_payloads(registry)
    destination = Path(evidence_dir)
    mismatches = [
        name
        for name, payload in expected.items()
        if not (destination / name).is_file()
        or (destination / name).read_bytes() != payload
    ]
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    manifest_artefacts = manifest.get("artefacts", ())
    if not isinstance(manifest_artefacts, list):
        raise ValueError("Experiment-provenance artefacts must be a list.")
    if manifest.get("artefact_count") != len(manifest_artefacts):
        raise ValueError("Experiment-provenance artefact count is inconsistent.")
    expected_manifest_records = {
        _manifest_relative_path(destination / name): {
            "sha256": _sha256_bytes(payload),
            "size_bytes": len(payload),
        }
        for name, payload in expected.items()
    }
    expected_paths = set(expected_manifest_records)
    observed_manifest_records = {
        str(record["path"]): {
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
        }
        for record in manifest_artefacts
        if isinstance(record, Mapping)
        and "path" in record
        and "sha256" in record
        and "size_bytes" in record
        and str(record["path"]) in expected_paths
    }
    if observed_manifest_records != expected_manifest_records:
        raise ValueError("Experiment-provenance manifest contents changed.")
    if mismatches:
        raise ValueError(f"Scenario evidence mismatches: {mismatches}.")
    return {
        "scenario_count": len(registry.scenarios),
        "registry_sha256": registry.registry_sha256,
        "configuration_sha256": registry.configuration_sha256,
        "evidence_checksums": {
            name: _sha256_bytes(payload)
            for name, payload in expected.items()
        },
        "manifest_entry_count": len(observed_manifest_records),
        "manifest_total_entry_count": manifest["artefact_count"],
        "runtime_adopted": False,
    }
