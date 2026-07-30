"""Transparent persistent-confidence scenarios for opt-in experiments.

The registry is an experimental-design input, not a calibration result. Its
three active bundles are reconstructed solely from the original Stage 2
domain, the authoritative coupled inverse transform and fixed quartile
coordinates. Production simulation defaults remain untouched.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
import csv
import hashlib
import io
import json
import math
import os
import tempfile

import yaml

from dai_sim.model.confidence import (
    PersistentConfidenceConfig,
    PersistentConfidenceState,
    RecoveryGateInputs,
    update_persistent_confidence,
)
from dai_sim.model.market import coefficient_normalised_market_response


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_PATH = (
    REPOSITORY_ROOT / "config/sensitivities/confidence_scenarios.yaml"
)
DEFAULT_EVIDENCE_DIR = (
    REPOSITORY_ROOT / "data/provenance/experiments/confidence"
)
DEFAULT_MANIFEST_PATH = (
    REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"
)
SOURCE_DOMAIN_PATH = (
    REPOSITORY_ROOT
    / "data/provenance/calibration/confidence/parameter_bounds.json"
)
SOURCE_DOMAIN_RELATIVE_PATH = (
    "data/provenance/calibration/confidence/parameter_bounds.json"
)
SOURCE_DOMAIN_SHA256 = (
    "6e1fcb4dcc3047b03bd24d290946fa532cab70412a867bc640fac8929fb4feda"
)
TRANSFORM_OWNER_PATH = (
    REPOSITORY_ROOT / "src/dai_sim/calibration/simulated_moments.py"
)
TRANSFORM_OWNER_RELATIVE_PATH = "src/dai_sim/calibration/simulated_moments.py"
PANIC_RESPONSE_UPPER_BOUND = Decimal("2.75454")
EXPECTED_SCENARIO_ORDER = (
    "stage1_only",
    "confidence_resilient",
    "confidence_central",
    "confidence_fragile",
)
EXPECTED_COORDINATES = {
    "confidence_resilient": (
        Decimal("0.25"),
        Decimal("0.75"),
        Decimal("0.75"),
        Decimal("0.25"),
    ),
    "confidence_central": (
        Decimal("0.50"),
        Decimal("0.50"),
        Decimal("0.50"),
        Decimal("0.50"),
    ),
    "confidence_fragile": (
        Decimal("0.75"),
        Decimal("0.25"),
        Decimal("0.25"),
        Decimal("0.75"),
    ),
}
STAGE1_MARKET_CHECKSUM = (
    "d86625e268c7e8b8abcb6d37e48f87c3c01578c8a3c09024a57da93978614547"
)
STAGE1_RESIDUAL_EVIDENCE_CHECKSUM = (
    "98299918d452695b96f639aaae4c2344c189a3351bd55f1d86a2441d5bcded0e"
)
RESIDUAL_BLOCK_CHECKSUM = (
    "6f55b51acfc1da23836b3d847153bd4f68e4a38fc33fd967e9d3b795737bf28c"
)
FACTORIAL_DECISION_CHECKSUM = (
    "f9ac6758dcff3597f2541c3ac68f28cb23fe66c1072b025fabf41b141443f8b9"
)
PRECISION_DECISION_CHECKSUM = (
    "b7bd2df0b80b23ffe2b2d5ccc74e3010c59d275c7897c84d574120da4352a2be"
)
PROFILE_BEHAVIOUR_CHECKSUMS = {
    "legacy": "f0f8d60ebecc6ee3d2bad57108ff454443fe92330dccc85252d1516be16e05c6",
    "empirical": "8f5c7864ad03fd7d4e24e41f79c1511024459e4b67d8d2e81ef0f653188498e9",
    "empirical_stress": (
        "3e20c8aa27547004ca92ede6164fd2f1c81c3bcf24e2dde5444106db69a1cc8d"
    ),
}
STAGE1_BELOW_PEG_RESPONSE = Decimal("0.19938097532295382")
STAGE1_ABOVE_PEG_RESPONSE = Decimal("0.10513116022712267")
MANUAL_STAGE2_KEYS = {
    "deterioration_adjustment",
    "recovery_adjustment",
    "recovery_ratio",
    "confidence_floor",
    "panic_response",
    "persistent_confidence",
    "stage2_parameters",
    "confidence_parameters",
}
REGISTRY_COLUMNS = (
    "order",
    "identifier",
    "enabled",
    "u_d",
    "u_r",
    "u_C",
    "u_P",
    "deterioration_adjustment",
    "recovery_ratio",
    "recovery_adjustment",
    "confidence_floor",
    "panic_response",
    "interpretation",
    "status",
    "source_domain_sha256",
    "scenario_defined",
    "row_sha256",
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


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


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be an explicit decimal string.")
    try:
        result = Decimal(str(value))
    except Exception as exc:  # pragma: no cover - Decimal supplies details.
        raise ValueError(f"{name} must be a valid decimal.") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite.")
    return result


@dataclass(frozen=True)
class ConfidenceScenario:
    """One immutable scenario bundle and its canonical coordinates."""

    order: int
    identifier: str
    enabled: bool
    u_d: Decimal | None
    u_r: Decimal | None
    u_C: Decimal | None
    u_P: Decimal | None
    deterioration_adjustment: Decimal | None
    recovery_ratio: Decimal | None
    recovery_adjustment: Decimal | None
    confidence_floor: Decimal | None
    panic_response: Decimal | None
    interpretation: str
    status: str

    def validate(self) -> None:
        """Validate inactivity or exact coupled-transform ownership."""
        canonical = (self.u_d, self.u_r, self.u_C, self.u_P)
        derived = (
            self.deterioration_adjustment,
            self.recovery_ratio,
            self.recovery_adjustment,
            self.confidence_floor,
            self.panic_response,
        )
        if self.identifier == "stage1_only":
            if self.enabled or any(value is not None for value in canonical + derived):
                raise ValueError("stage1_only must have inactive Stage 2 values.")
            return
        if not self.enabled or any(value is None for value in canonical + derived):
            raise ValueError("Active confidence scenarios require complete values.")
        expected = EXPECTED_COORDINATES.get(self.identifier)
        if expected is None or canonical != expected:
            raise ValueError(
                f"Unexpected canonical coordinates for {self.identifier}."
            )
        assert self.u_d is not None
        assert self.u_r is not None
        assert self.u_C is not None
        assert self.u_P is not None
        assert self.deterioration_adjustment is not None
        assert self.recovery_ratio is not None
        assert self.recovery_adjustment is not None
        assert self.confidence_floor is not None
        assert self.panic_response is not None
        expected_values = (
            self.u_d,
            self.u_r,
            self.u_d * self.u_r,
            self.u_C,
            PANIC_RESPONSE_UPPER_BOUND * self.u_P,
        )
        if derived != expected_values:
            raise ValueError(
                f"Derived values for {self.identifier} do not match "
                "the authoritative coupled transform."
            )
        if not all(Decimal("0") < value < Decimal("1") for value in canonical):
            raise ValueError("Active canonical coordinates must exclude endpoints.")
        PersistentConfidenceConfig(
            deterioration_adjustment=float(self.deterioration_adjustment),
            recovery_adjustment=float(self.recovery_adjustment),
            confidence_floor=float(self.confidence_floor),
            stability_hours=24,
        ).validate()

    def persistent_config(self, *, stability_hours: int = 24) -> PersistentConfidenceConfig:
        """Return the exact model configuration for an active scenario."""
        if not self.enabled:
            raise ValueError("stage1_only does not have a persistent configuration.")
        assert self.deterioration_adjustment is not None
        assert self.recovery_adjustment is not None
        assert self.confidence_floor is not None
        config = PersistentConfidenceConfig(
            deterioration_adjustment=float(self.deterioration_adjustment),
            recovery_adjustment=float(self.recovery_adjustment),
            confidence_floor=float(self.confidence_floor),
            stability_hours=stability_hours,
        )
        config.validate()
        return config

    def record(self) -> dict[str, Any]:
        """Return the deterministic registry record without its row checksum."""
        return {
            "order": self.order,
            "identifier": self.identifier,
            "enabled": self.enabled,
            "u_d": _decimal_text(self.u_d),
            "u_r": _decimal_text(self.u_r),
            "u_C": _decimal_text(self.u_C),
            "u_P": _decimal_text(self.u_P),
            "deterioration_adjustment": _decimal_text(
                self.deterioration_adjustment
            ),
            "recovery_ratio": _decimal_text(self.recovery_ratio),
            "recovery_adjustment": _decimal_text(self.recovery_adjustment),
            "confidence_floor": _decimal_text(self.confidence_floor),
            "panic_response": _decimal_text(self.panic_response),
            "interpretation": self.interpretation,
            "status": self.status,
            "source_domain_sha256": SOURCE_DOMAIN_SHA256,
            "scenario_defined": True,
        }


@dataclass(frozen=True)
class ConfidenceScenarioRegistry:
    """Validated registry plus structural and provenance ownership."""

    registry_id: str
    scenarios: tuple[ConfidenceScenario, ...]
    stability_hours: int
    source_domain_path: str
    source_domain_sha256: str
    transform_owner: str
    structural_formulation: Mapping[str, Any]
    configuration_path: Path
    configuration_sha256: str

    def by_identifier(self, identifier: str) -> ConfidenceScenario:
        """Return one scenario, rejecting unknown identifiers."""
        for scenario in self.scenarios:
            if scenario.identifier == identifier:
                return scenario
        raise ValueError(f"Unknown confidence scenario: {identifier}.")

    @property
    def registry_sha256(self) -> str:
        """Return the checksum of the deterministic registry CSV."""
        return _sha256_bytes(registry_csv_bytes(self))


@dataclass(frozen=True)
class ConfidenceScenarioActivation:
    """Resolved opt-in experiment configuration and complete metadata."""

    scenario: ConfidenceScenario
    persistent_config: PersistentConfidenceConfig | None
    panic_response: float
    metadata: Mapping[str, Any]


def validate_source_domain() -> None:
    """Verify the registered domain and coupled transform have not changed."""
    if _sha256_file(SOURCE_DOMAIN_PATH) != SOURCE_DOMAIN_SHA256:
        raise ValueError("The authoritative Stage 2 parameter domain changed.")
    source = TRANSFORM_OWNER_PATH.read_text(encoding="utf-8")
    required = (
        "PANIC_RESPONSE_UPPER_BOUND = 2.75454",
        "recovery = float(deterioration * unit[1])",
        "panic = float(PANIC_RESPONSE_UPPER_BOUND * unit[3])",
    )
    if not all(fragment in source for fragment in required):
        raise ValueError("The authoritative coupled Stage 2 transform changed.")


def _scenario_from_mapping(raw: Mapping[str, Any]) -> ConfidenceScenario:
    canonical = raw.get("canonical")
    derived = raw.get("derived")
    if not isinstance(canonical, Mapping) or not isinstance(derived, Mapping):
        raise ValueError("Scenario canonical and derived fields must be mappings.")
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("Scenario enabled must be Boolean.")

    def optional_decimal(mapping: Mapping[str, Any], key: str) -> Decimal | None:
        value = mapping.get(key)
        return None if value is None else _decimal(value, key)

    scenario = ConfidenceScenario(
        order=int(raw["order"]),
        identifier=str(raw["identifier"]),
        enabled=enabled,
        u_d=optional_decimal(canonical, "u_d"),
        u_r=optional_decimal(canonical, "u_r"),
        u_C=optional_decimal(canonical, "u_C"),
        u_P=optional_decimal(canonical, "u_P"),
        deterioration_adjustment=optional_decimal(
            derived, "deterioration_adjustment"
        ),
        recovery_ratio=optional_decimal(derived, "recovery_ratio"),
        recovery_adjustment=optional_decimal(derived, "recovery_adjustment"),
        confidence_floor=optional_decimal(derived, "confidence_floor"),
        panic_response=optional_decimal(derived, "panic_response"),
        interpretation=str(raw["interpretation"]).strip(),
        status=str(raw["status"]),
    )
    scenario.validate()
    return scenario


def load_confidence_scenario_registry(
    path: Path | str = DEFAULT_REGISTRY_PATH,
) -> ConfidenceScenarioRegistry:
    """Load and validate the sole tracked confidence-scenario owner."""
    validate_source_domain()
    resolved = Path(path).resolve()
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Confidence scenario registry must be a mapping.")
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported confidence scenario schema.")
    if payload.get("registry_id") != "persistent-confidence-scenarios-v1":
        raise ValueError("Unexpected confidence scenario registry identity.")
    source = payload.get("source_domain")
    structural = payload.get("structural_formulation")
    rows = payload.get("scenarios")
    if not isinstance(source, Mapping) or not isinstance(structural, Mapping):
        raise ValueError("Source domain and structural formulation are required.")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("Confidence scenarios must be a sequence.")
    if source.get("path") != SOURCE_DOMAIN_RELATIVE_PATH:
        raise ValueError("Unexpected source-domain path.")
    if source.get("sha256") != SOURCE_DOMAIN_SHA256:
        raise ValueError("Unexpected source-domain checksum.")
    if source.get("transform_owner") != TRANSFORM_OWNER_RELATIVE_PATH:
        raise ValueError("Unexpected transform owner.")
    if str(source.get("panic_response_upper_bound")) != "2.75454":
        raise ValueError("Unexpected panic-response scale.")
    expected_transform = {
        "deterioration_adjustment": "alpha_d = u_d",
        "recovery_ratio": "rho_r = u_r",
        "recovery_adjustment": "alpha_r = alpha_d * rho_r",
        "confidence_floor": "C_min = u_C",
        "panic_response": "kappa_P = 2.75454 * u_P",
    }
    if dict(source.get("inverse_transform", {})) != expected_transform:
        raise ValueError("Unexpected inverse-transform declaration.")
    if not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("Every confidence scenario must be a mapping.")
    scenarios = tuple(_scenario_from_mapping(row) for row in rows)
    if tuple(item.identifier for item in scenarios) != EXPECTED_SCENARIO_ORDER:
        raise ValueError("Confidence scenario order or identifiers changed.")
    if tuple(item.order for item in scenarios) != (1, 2, 3, 4):
        raise ValueError("Confidence scenario order must be 1, 2, 3, 4.")
    if len({item.identifier for item in scenarios}) != 4:
        raise ValueError("Confidence scenario identifiers must be unique.")
    if sum(item.enabled for item in scenarios) != 3:
        raise ValueError("Exactly three confidence scenarios must be active.")
    forbidden = ("calibrated", "empirical", "preferred", "realistic", "best")
    if any(
        token in item.identifier.lower()
        for item in scenarios
        for token in forbidden
    ):
        raise ValueError("Scenario identifiers must not imply empirical selection.")
    required_structural = {
        "vault_state": "production_default",
        "residual_process": "accepted_24_hour_moving_blocks",
        "recovery_gate": "full",
        "unresolved_backlog_condition": "retained",
        "active_bad_debt_condition": "retained",
        "price_stability_condition": "retained",
        "stress_construction": "registered_equal_weight",
        "stability_hours": 24,
    }
    if dict(structural) != required_structural:
        raise ValueError("The baseline structural formulation changed.")
    registry = ConfidenceScenarioRegistry(
        registry_id=str(payload["registry_id"]),
        scenarios=scenarios,
        stability_hours=24,
        source_domain_path=SOURCE_DOMAIN_RELATIVE_PATH,
        source_domain_sha256=SOURCE_DOMAIN_SHA256,
        transform_owner=TRANSFORM_OWNER_RELATIVE_PATH,
        structural_formulation=dict(structural),
        configuration_path=resolved,
        configuration_sha256=_sha256_file(resolved),
    )
    _validate_ordering(registry)
    return registry


def _validate_ordering(registry: ConfidenceScenarioRegistry) -> None:
    resilient = registry.by_identifier("confidence_resilient")
    central = registry.by_identifier("confidence_central")
    fragile = registry.by_identifier("confidence_fragile")
    assert all(item.enabled for item in (resilient, central, fragile))
    if not (
        fragile.deterioration_adjustment
        > central.deterioration_adjustment
        > resilient.deterioration_adjustment
    ):
        raise ValueError("Deterioration ordering changed.")
    if not (
        resilient.recovery_ratio
        > central.recovery_ratio
        > fragile.recovery_ratio
    ):
        raise ValueError("Conditional recovery-ratio ordering changed.")
    if not (
        resilient.confidence_floor
        > central.confidence_floor
        > fragile.confidence_floor
    ):
        raise ValueError("Confidence-floor ordering changed.")
    if not (
        fragile.panic_response
        > central.panic_response
        > resilient.panic_response
    ):
        raise ValueError("Panic-response ordering changed.")
    if not (
        central.recovery_adjustment
        > resilient.recovery_adjustment
        == fragile.recovery_adjustment
    ):
        raise ValueError("Expected coupled raw-recovery ordering changed.")


def registry_csv_bytes(registry: ConfidenceScenarioRegistry) -> bytes:
    """Serialise the four-row registry deterministically."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=REGISTRY_COLUMNS,
        lineterminator="\n",
    )
    writer.writeheader()
    for scenario in registry.scenarios:
        row = scenario.record()
        row_checksum = _sha256_bytes(
            json.dumps(
                row,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        )
        writer.writerow({**row, "row_sha256": row_checksum})
    return output.getvalue().encode("utf-8")


def _activation_metadata(
    registry: ConfidenceScenarioRegistry,
    scenario: ConfidenceScenario,
) -> dict[str, Any]:
    return {
        "confidence_scenario": scenario.identifier,
        "scenario_enabled": scenario.enabled,
        "persistent_confidence_enabled": scenario.enabled,
        "canonical_coordinates": {
            "u_d": _decimal_text(scenario.u_d),
            "u_r_recovery_ratio": _decimal_text(scenario.u_r),
            "u_C": _decimal_text(scenario.u_C),
            "u_P": _decimal_text(scenario.u_P),
        },
        "derived_parameters": {
            "deterioration_adjustment": _decimal_text(
                scenario.deterioration_adjustment
            ),
            "recovery_ratio": _decimal_text(scenario.recovery_ratio),
            "recovery_adjustment": _decimal_text(
                scenario.recovery_adjustment
            ),
            "confidence_floor": _decimal_text(scenario.confidence_floor),
            "panic_response": _decimal_text(scenario.panic_response),
        },
        "parameter_source": "scenario_defined",
        "stage1_coefficients_active": True,
        "moving_block_residual_process_active": True,
        "recovery_gate_active": scenario.enabled,
        "source_domain_sha256": SOURCE_DOMAIN_SHA256,
        "scenario_registry_sha256": registry.registry_sha256,
        "configuration_sha256": registry.configuration_sha256,
        "structural_formulation": dict(registry.structural_formulation),
        "stage1_coefficient_sha256": STAGE1_MARKET_CHECKSUM,
        "residual_block_sha256": RESIDUAL_BLOCK_CHECKSUM,
        "scenario_status": scenario.status,
        "runtime_adopted": False,
    }


def resolve_confidence_scenario(
    identifier: str | None = None,
    *,
    manual_stage2: Mapping[str, Any] | None = None,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
) -> ConfidenceScenarioActivation:
    """Resolve an explicit experiment scenario; missing means Stage 1 only."""
    if manual_stage2:
        raise ValueError(
            "Final experiment configuration must not override Stage 2 values."
        )
    registry = load_confidence_scenario_registry(registry_path)
    scenario = registry.by_identifier(identifier or "stage1_only")
    return ConfidenceScenarioActivation(
        scenario=scenario,
        persistent_config=(
            None
            if not scenario.enabled
            else scenario.persistent_config(
                stability_hours=registry.stability_hours
            )
        ),
        panic_response=(
            0.0 if scenario.panic_response is None else float(scenario.panic_response)
        ),
        metadata=_activation_metadata(registry, scenario),
    )


def resolve_experiment_confidence(
    experiment: Mapping[str, Any],
    *,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
) -> ConfidenceScenarioActivation:
    """Resolve the scenario field while rejecting manual Stage 2 ownership."""
    def manual_paths(
        value: Mapping[str, Any],
        prefix: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        found: list[str] = []
        for key, child in value.items():
            path = (*prefix, str(key))
            if key in MANUAL_STAGE2_KEYS:
                found.append(".".join(path))
            if isinstance(child, Mapping):
                found.extend(manual_paths(child, path))
        return tuple(found)

    manual = manual_paths(experiment)
    if manual:
        raise ValueError(
            "Persistent-confidence experiment values must use "
            f"confidence_scenario; manual fields found: {', '.join(manual)}."
        )
    return resolve_confidence_scenario(
        experiment.get("confidence_scenario"),
        registry_path=registry_path,
    )


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
    manifest = {
        "schema_version": 1,
        "purpose": (
            "Content-addressed experimental-design evidence; no parameter "
            "estimate or selected scenario."
        ),
        "artefact_count": len(payloads),
        "artefacts": [
            {
                "path": _manifest_relative_path(destination / name),
                "sha256": checksums[name],
                "size_bytes": len(payloads[name]),
                "classification": "scenario_defined_experimental_design",
                "runtime_adopted": False,
            }
            for name in sorted(payloads)
        ],
    }
    _atomic_write(Path(manifest_path), _canonical_json_bytes(manifest))
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
    if manifest.get("artefact_count") != 4:
        raise ValueError("Experiment-provenance manifest must contain four artefacts.")
    expected_manifest_records = {
        name: {
            "sha256": _sha256_bytes(payload),
            "size_bytes": len(payload),
        }
        for name, payload in expected.items()
    }
    observed_manifest_records = {
        Path(str(record["path"])).name: {
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
        }
        for record in manifest.get("artefacts", ())
        if isinstance(record, Mapping)
        and "path" in record
        and "sha256" in record
        and "size_bytes" in record
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
        "manifest_entry_count": manifest["artefact_count"],
        "runtime_adopted": False,
    }
