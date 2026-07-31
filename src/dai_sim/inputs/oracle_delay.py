"""Typed resolver for the result-blind final oracle-delay registry."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_PATH = (
    REPOSITORY_ROOT / "config/sensitivities/final_oracle_delay_registry.yaml"
)
EXPECTED_TREATMENT_IDS = (
    "oracle_delay_low",
    "oracle_delay_central",
    "oracle_delay_high",
)
VALID_SOURCE_CLASSIFICATIONS = {
    "oracle_delay_empirically_identified",
    "oracle_delay_partially_identified_from_update_intervals",
    "oracle_delay_partially_identified_from_documented_rule",
    "transparent_sensitivity_not_empirically_identified",
}
EXPECTED_PARAMETER_NAME = "SimulationConfig.oracle_delay_steps"
EXPECTED_SEMANTIC_OWNER = (
    "src/dai_sim/model/collateral_prices.py::_apply_oracle_delay"
)


def sha256_file(path: Path) -> str:
    """Return a streaming file digest."""
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return exactly the scientific fields bound by the registry identity."""
    treatments = payload["treatments"]
    return {
        "parent_commit": payload["parent_commit"],
        "parameter_semantic_owner": payload["parameter_semantic_owner"],
        "simulation_step_duration_hours": payload["simulation_step"][
            "duration_hours"
        ],
        "source_inventory_sha256": payload["evidence"][
            "source_inventory_sha256"
        ],
        "eligible_source_sha256": payload["evidence"][
            "eligible_source_sha256"
        ],
        "evidence_tier": payload["evidence"]["tier"],
        "calibration_boundary": payload["evidence"]["calibration_boundary"],
        "derivation_formula": payload["derivation"]["formula"],
        "rounding_rule": payload["derivation"]["rounding_rule"],
        "treatments": {
            identifier: int(treatments[identifier]["delay_steps"])
            for identifier in EXPECTED_TREATMENT_IDS
        },
        "held_out_exclusion": payload["evidence"]["held_out_exclusion"],
        "runtime_adopted": payload["runtime_adopted"],
    }


def registry_identity(payload: dict[str, Any]) -> str:
    """Return the content-addressed scientific registry identity."""
    encoded = json.dumps(
        _identity_payload(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class OracleDelayTreatment:
    """One system-wide, non-adopted oracle-delay treatment."""

    identifier: str
    delay_steps: int
    equivalent_hours: int
    status: str
    source_tier: int


@dataclass(frozen=True)
class OracleDelayRegistry:
    """Validated owner of the three Experiment E delay coordinates."""

    path: Path
    configuration_checksum: str
    identity: str
    source_classification: str
    readiness_classification: str
    parameter_name: str
    parameter_semantic_owner: str
    step_duration_hours: int
    horizon_steps: int
    treatments: tuple[OracleDelayTreatment, ...]
    runtime_adopted: bool

    def by_identifier(self, identifier: str) -> OracleDelayTreatment:
        """Resolve one exact pre-registered treatment identifier."""
        for treatment in self.treatments:
            if treatment.identifier == identifier:
                return treatment
        raise KeyError(f"Unknown oracle-delay treatment: {identifier}")


def load_oracle_delay_registry(
    path: Path | str = DEFAULT_REGISTRY_PATH,
) -> OracleDelayRegistry:
    """Load and fully validate the non-operational delay registry."""
    resolved = Path(path)
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Unsupported oracle-delay registry schema.")
    if payload.get("registry_identifier") != "final_oracle_delay_registry":
        raise ValueError("Unexpected oracle-delay registry identifier.")
    if payload.get("runtime_adopted") is not False:
        raise ValueError("Oracle-delay registry must not be runtime adopted.")
    if payload.get("unit") != "simulation_steps":
        raise ValueError("Oracle-delay registry unit must be simulation_steps.")
    if payload.get("parameter_name") != EXPECTED_PARAMETER_NAME:
        raise ValueError("Unsupported oracle-delay parameter semantics.")
    if payload.get("parameter_semantic_owner") != EXPECTED_SEMANTIC_OWNER:
        raise ValueError("Unsupported oracle-delay parameter semantics.")
    if payload.get("scope", {}).get("global") is not True:
        raise ValueError("Experiment E requires one system-wide delay registry.")
    source_classification = str(payload.get("source_classification"))
    if source_classification not in VALID_SOURCE_CLASSIFICATIONS:
        raise ValueError("Unsupported oracle-delay source classification.")
    treatments_raw = payload.get("treatments")
    if not isinstance(treatments_raw, dict) or tuple(treatments_raw) != (
        EXPECTED_TREATMENT_IDS
    ):
        raise ValueError("Registry must contain exactly the three delay treatments.")
    treatments: list[OracleDelayTreatment] = []
    for identifier, treatment in treatments_raw.items():
        steps = treatment.get("delay_steps")
        hours = treatment.get("equivalent_hours")
        if isinstance(steps, bool) or not isinstance(steps, int):
            raise ValueError("Oracle-delay treatment values must be integers.")
        if isinstance(hours, bool) or not isinstance(hours, int):
            raise ValueError("Equivalent delay hours must be integers.")
        treatments.append(
            OracleDelayTreatment(
                identifier=identifier,
                delay_steps=steps,
                equivalent_hours=hours,
                status=str(treatment["status"]),
                source_tier=int(treatment["source_tier"]),
            )
        )
    values = tuple(treatment.delay_steps for treatment in treatments)
    horizon = int(payload["simulation_step"]["horizon_steps"])
    if values[0] != 0 or values[1] < 1 or values[2] <= values[1]:
        raise ValueError("Oracle-delay treatment ordering is invalid.")
    if values[2] >= horizon:
        raise ValueError("Oracle delay exceeds the simulation horizon.")
    expected_identity = registry_identity(payload)
    if payload.get("registry_identity") != expected_identity:
        raise ValueError("Oracle-delay registry identity differs.")
    return OracleDelayRegistry(
        path=resolved,
        configuration_checksum=sha256_file(resolved),
        identity=expected_identity,
        source_classification=source_classification,
        readiness_classification=str(payload["readiness_classification"]),
        parameter_name=str(payload["parameter_name"]),
        parameter_semantic_owner=str(payload["parameter_semantic_owner"]),
        step_duration_hours=int(payload["simulation_step"]["duration_hours"]),
        horizon_steps=horizon,
        treatments=tuple(treatments),
        runtime_adopted=False,
    )


def resolve_oracle_delay_treatment(
    identifier: str,
    *,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
) -> OracleDelayTreatment:
    """Resolve a treatment explicitly without affecting runtime defaults."""
    return load_oracle_delay_registry(registry_path).by_identifier(identifier)
