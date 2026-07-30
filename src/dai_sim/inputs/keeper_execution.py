"""Typed, opt-in resolver for keeper-execution calibration candidates.

The resolver deliberately does not participate in ordinary configuration
loading.  It exposes reviewed candidate bundles to bounded diagnostics while
leaving every established runtime profile unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KEEPER_EXECUTION_REGISTRY = (
    REPOSITORY_ROOT / "config/sensitivities/keeper_execution.yaml"
)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 checksum of a local file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class KeeperExecutionCandidate:
    """One explicitly selected, non-adopted keeper-execution candidate."""

    capacity_profile_id: str
    hurdle_profile_id: str
    maximum_liquidations_per_step: int
    risk_cost_rate: float
    system_wide_status: str
    capacity_identification_classification: str
    included_collateral_types: tuple[str, ...]
    source_sample: tuple[str, ...]
    collateral_composition_status: str
    population_mapping_status: str
    hurdle_unit: str
    hurdle_identification_status: str
    direct_gas_treatment: str
    profitability_equation_checksum: str
    registry_checksum: str
    parameter_source: str
    source_file: Path
    source_checksum: str
    runtime_adopted: bool

    def validate(self) -> None:
        """Validate the typed candidate and its non-adoption boundary."""
        if self.maximum_liquidations_per_step <= 0:
            raise ValueError("Keeper capacity must be a positive integer.")
        if self.risk_cost_rate < 0:
            raise ValueError("Keeper hurdle rate cannot be negative.")
        if self.runtime_adopted:
            raise ValueError(
                "Keeper-execution candidates must not be runtime adopted."
            )
        if self.capacity_identification_classification not in {
            "shared_effective_capacity_frontier_identified",
            "shared_capacity_partially_identified",
            "shared_capacity_not_identified_use_sensitivity",
        }:
            raise ValueError(
                "Unsupported keeper-execution source classification."
            )
        if self.collateral_composition_status not in {
            "composition_stable",
            "composition_sensitive_shared_capacity",
            "composition_unresolved",
        }:
            raise ValueError("Unsupported collateral-composition status.")
        if self.hurdle_identification_status not in {
            "profit_hurdle_estimated",
            "profit_hurdle_partially_identified",
            "profit_hurdle_not_identified",
        }:
            raise ValueError("Unsupported keeper-hurdle status.")


def _load_registry(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Keeper-execution registry must be a YAML mapping.")
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported keeper-execution registry schema.")
    if payload.get("runtime_adopted") is not False:
        raise ValueError("Keeper-execution registry must remain non-adopted.")
    return payload


def resolve_keeper_execution_candidate(
    capacity_profile_id: str,
    hurdle_profile_id: str,
    *,
    registry_path: Path | str = DEFAULT_KEEPER_EXECUTION_REGISTRY,
) -> KeeperExecutionCandidate:
    """Resolve one opt-in capacity/hurdle pair from the candidate registry."""
    path = Path(registry_path)
    payload = _load_registry(path)
    capacity_profiles = payload.get("shared_capacity_profiles", {})
    hurdle_profiles = payload.get("profit_hurdle_profiles", {})
    if set(capacity_profiles) != {
        "shared_keeper_capacity_low",
        "shared_keeper_capacity_central",
        "shared_keeper_capacity_high",
    }:
        raise ValueError(
            "Registry must contain exactly the three authorised shared "
            "capacity profile IDs."
        )
    if capacity_profile_id not in capacity_profiles:
        raise KeyError(f"Unknown keeper capacity profile: {capacity_profile_id}")
    if hurdle_profile_id not in hurdle_profiles:
        raise KeyError(f"Unknown keeper hurdle profile: {hurdle_profile_id}")

    capacity = capacity_profiles[capacity_profile_id]
    hurdle = hurdle_profiles[hurdle_profile_id]
    candidate = KeeperExecutionCandidate(
        capacity_profile_id=capacity_profile_id,
        hurdle_profile_id=hurdle_profile_id,
        maximum_liquidations_per_step=int(
            capacity["maximum_liquidations_per_step"]
        ),
        risk_cost_rate=float(hurdle["risk_cost_rate"]),
        system_wide_status=str(payload["system_wide_status"]),
        capacity_identification_classification=str(
            payload["capacity_identification_classification"]
        ),
        included_collateral_types=tuple(
            str(value) for value in payload["included_collateral_types"]
        ),
        source_sample=tuple(
            str(value) for value in payload["source_sample"]
        ),
        collateral_composition_status=str(
            payload["composition_status"]
        ),
        population_mapping_status=str(
            payload["population_mapping_status"]
        ),
        hurdle_unit="fraction of debt repaid",
        hurdle_identification_status=str(
            payload["hurdle_identification_status"]
        ),
        direct_gas_treatment=str(payload["direct_gas_treatment"]),
        profitability_equation_checksum=str(
            payload["profitability_equation_checksum"]
        ),
        registry_checksum=sha256_file(path),
        parameter_source=str(payload["parameter_source"]),
        source_file=path,
        source_checksum=str(
            payload["source_evidence_checksums"][
                "keeper_execution_specification.json"
            ]
        ),
        runtime_adopted=bool(payload["runtime_adopted"]),
    )
    candidate.validate()
    return candidate
