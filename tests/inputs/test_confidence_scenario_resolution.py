"""Typed confidence-scenario registry and resolution tests."""

from __future__ import annotations

import ast
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from dai_sim.inputs.confidence_scenarios import (
    DEFAULT_REGISTRY_PATH,
    EXPECTED_SCENARIO_ORDER,
    SOURCE_DOMAIN_PATH,
    SOURCE_DOMAIN_SHA256,
    TRANSFORM_OWNER_PATH,
    load_confidence_scenario_registry,
    registry_csv_bytes,
    resolve_confidence_scenario,
    resolve_experiment_confidence,
    validate_source_domain,
)


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_ACTIVE = {
    "confidence_resilient": {
        "canonical": ("0.25", "0.75", "0.75", "0.25"),
        "derived": ("0.25", "0.75", "0.1875", "0.75", "0.688635"),
    },
    "confidence_central": {
        "canonical": ("0.50", "0.50", "0.50", "0.50"),
        "derived": ("0.50", "0.50", "0.25", "0.50", "1.37727"),
    },
    "confidence_fragile": {
        "canonical": ("0.75", "0.25", "0.25", "0.75"),
        "derived": ("0.75", "0.25", "0.1875", "0.25", "2.065905"),
    },
}


def _yaml_payload() -> dict:
    payload = yaml.safe_load(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_registry(path: Path, payload: dict) -> Path:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_source_domain_and_authoritative_transform_are_frozen() -> None:
    validate_source_domain()
    assert sha256(SOURCE_DOMAIN_PATH.read_bytes()).hexdigest() == SOURCE_DOMAIN_SHA256
    source = TRANSFORM_OWNER_PATH.read_text(encoding="utf-8")
    assert "recovery = float(deterioration * unit[1])" in source
    assert "PANIC_RESPONSE_UPPER_BOUND = 2.75454" in source


def test_registry_has_exact_order_and_activation_count() -> None:
    registry = load_confidence_scenario_registry()
    assert tuple(item.identifier for item in registry.scenarios) == (
        EXPECTED_SCENARIO_ORDER
    )
    assert tuple(item.order for item in registry.scenarios) == (1, 2, 3, 4)
    assert len({item.identifier for item in registry.scenarios}) == 4
    assert [item.enabled for item in registry.scenarios] == [
        False,
        True,
        True,
        True,
    ]


def test_stage1_only_has_no_synthetic_stage2_vector() -> None:
    stage1 = load_confidence_scenario_registry().by_identifier("stage1_only")
    assert not stage1.enabled
    assert (
        stage1.u_d,
        stage1.u_r,
        stage1.u_C,
        stage1.u_P,
        stage1.deterioration_adjustment,
        stage1.recovery_ratio,
        stage1.recovery_adjustment,
        stage1.confidence_floor,
        stage1.panic_response,
    ) == (None,) * 9


@pytest.mark.parametrize("identifier", tuple(EXPECTED_ACTIVE))
def test_active_scenario_coordinates_and_derived_values_are_exact(
    identifier: str,
) -> None:
    scenario = load_confidence_scenario_registry().by_identifier(identifier)
    expected = EXPECTED_ACTIVE[identifier]
    canonical = (scenario.u_d, scenario.u_r, scenario.u_C, scenario.u_P)
    derived = (
        scenario.deterioration_adjustment,
        scenario.recovery_ratio,
        scenario.recovery_adjustment,
        scenario.confidence_floor,
        scenario.panic_response,
    )
    assert canonical == tuple(Decimal(value) for value in expected["canonical"])
    assert derived == tuple(Decimal(value) for value in expected["derived"])
    assert scenario.recovery_ratio == (
        scenario.recovery_adjustment / scenario.deterioration_adjustment
    )


def test_independent_coordinate_ordering_is_explicit() -> None:
    registry = load_confidence_scenario_registry()
    resilient = registry.by_identifier("confidence_resilient")
    central = registry.by_identifier("confidence_central")
    fragile = registry.by_identifier("confidence_fragile")
    assert (
        fragile.deterioration_adjustment
        > central.deterioration_adjustment
        > resilient.deterioration_adjustment
    )
    assert resilient.recovery_ratio > central.recovery_ratio > fragile.recovery_ratio
    assert (
        resilient.confidence_floor
        > central.confidence_floor
        > fragile.confidence_floor
    )
    assert fragile.panic_response > central.panic_response > resilient.panic_response


def test_coupled_raw_recovery_ordering_is_not_reinterpreted() -> None:
    registry = load_confidence_scenario_registry()
    resilient = registry.by_identifier("confidence_resilient")
    central = registry.by_identifier("confidence_central")
    fragile = registry.by_identifier("confidence_fragile")
    assert (
        central.recovery_adjustment
        > resilient.recovery_adjustment
        == fragile.recovery_adjustment
    )


def test_active_canonical_coordinates_exclude_endpoints() -> None:
    active = load_confidence_scenario_registry().scenarios[1:]
    assert all(
        Decimal("0") < coordinate < Decimal("1")
        for scenario in active
        for coordinate in (scenario.u_d, scenario.u_r, scenario.u_C, scenario.u_P)
        if coordinate is not None
    )


def test_registry_identifiers_do_not_claim_empirical_selection() -> None:
    identifiers = " ".join(EXPECTED_SCENARIO_ORDER)
    for forbidden in ("calibrated", "empirical", "preferred", "realistic", "best"):
        assert forbidden not in identifiers


def test_missing_and_explicit_stage1_activation_are_identical() -> None:
    missing = resolve_confidence_scenario()
    explicit = resolve_confidence_scenario("stage1_only")
    assert missing == explicit
    assert missing.persistent_config is None
    assert missing.panic_response == 0.0
    assert missing.metadata["recovery_gate_active"] is False
    assert missing.metadata["stage1_coefficients_active"] is True
    assert missing.metadata["moving_block_residual_process_active"] is True


@pytest.mark.parametrize("identifier", tuple(EXPECTED_ACTIVE))
def test_active_scenarios_resolve_exact_runtime_values(identifier: str) -> None:
    activation = resolve_confidence_scenario(identifier)
    expected = EXPECTED_ACTIVE[identifier]["derived"]
    assert activation.persistent_config is not None
    assert activation.persistent_config.deterioration_adjustment == float(expected[0])
    assert activation.persistent_config.recovery_adjustment == float(expected[2])
    assert activation.persistent_config.confidence_floor == float(expected[3])
    assert activation.panic_response == float(expected[4])
    assert activation.metadata["parameter_source"] == "scenario_defined"
    assert activation.metadata["runtime_adopted"] is False
    assert activation.metadata["recovery_gate_active"] is True


def test_unknown_scenario_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown confidence scenario"):
        resolve_confidence_scenario("confidence_best")


@pytest.mark.parametrize(
    "experiment",
    (
        {"confidence_scenario": "confidence_central", "confidence_floor": 0.5},
        {
            "confidence_scenario": "confidence_central",
            "parameters": {"recovery_adjustment": 0.25},
        },
        {
            "confidence_scenario": "confidence_central",
            "stage2_parameters": {},
        },
    ),
)
def test_manual_or_partial_stage2_overrides_are_rejected(experiment: dict) -> None:
    with pytest.raises(ValueError, match="must use confidence_scenario"):
        resolve_experiment_confidence(experiment)


def test_experiment_resolver_accepts_only_registered_scenario_field() -> None:
    activation = resolve_experiment_confidence(
        {
            "name": "controlled_smoke",
            "confidence_scenario": "confidence_resilient",
            "seed": 1729,
        }
    )
    assert activation.scenario.identifier == "confidence_resilient"


def test_source_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = _yaml_payload()
    payload["source_domain"]["sha256"] = "0" * 64
    path = _write_registry(tmp_path / "registry.yaml", payload)
    with pytest.raises(ValueError, match="source-domain checksum"):
        load_confidence_scenario_registry(path)


def test_transform_declaration_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = _yaml_payload()
    payload["source_domain"]["inverse_transform"]["recovery_adjustment"] = (
        "alpha_r = u_r"
    )
    path = _write_registry(tmp_path / "registry.yaml", payload)
    with pytest.raises(ValueError, match="inverse-transform"):
        load_confidence_scenario_registry(path)


def test_derived_value_mismatch_is_rejected_without_repair(tmp_path: Path) -> None:
    payload = _yaml_payload()
    payload["scenarios"][1]["derived"]["recovery_adjustment"] = "0.20"
    path = _write_registry(tmp_path / "registry.yaml", payload)
    with pytest.raises(ValueError, match="coupled transform"):
        load_confidence_scenario_registry(path)


def test_fixed_canonical_coordinate_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = _yaml_payload()
    payload["scenarios"][2]["canonical"]["u_d"] = "0.51"
    payload["scenarios"][2]["derived"]["deterioration_adjustment"] = "0.51"
    payload["scenarios"][2]["derived"]["recovery_adjustment"] = "0.255"
    path = _write_registry(tmp_path / "registry.yaml", payload)
    with pytest.raises(ValueError, match="canonical coordinates"):
        load_confidence_scenario_registry(path)


def test_panic_response_scale_mismatch_is_rejected(tmp_path: Path) -> None:
    payload = _yaml_payload()
    payload["source_domain"]["panic_response_upper_bound"] = "2.75"
    path = _write_registry(tmp_path / "registry.yaml", payload)
    with pytest.raises(ValueError, match="panic-response scale"):
        load_confidence_scenario_registry(path)


def test_factorial_structural_variant_is_unavailable(tmp_path: Path) -> None:
    payload = _yaml_payload()
    payload["structural_formulation"]["vault_state"] = "historical_p25"
    path = _write_registry(tmp_path / "registry.yaml", payload)
    with pytest.raises(ValueError, match="structural formulation"):
        load_confidence_scenario_registry(path)


def test_registry_has_no_dependency_on_search_or_factorial_modules() -> None:
    tree = ast.parse(
        (
            ROOT / "src/dai_sim/inputs/confidence_scenarios.py"
        ).read_text(encoding="utf-8")
    )
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    forbidden_fragments = (
        "simulated_moments_search",
        "partial_identification",
        "structural_factorial",
        "structural_incompatibility",
    )
    assert not any(
        fragment in module
        for module in imported
        for fragment in forbidden_fragments
    )


def test_registry_csv_is_deterministic_and_content_addressed() -> None:
    registry = load_confidence_scenario_registry()
    first = registry_csv_bytes(registry)
    second = registry_csv_bytes(load_confidence_scenario_registry())
    assert first == second
    assert sha256(first).hexdigest() == registry.registry_sha256
    assert first.count(b"\n") == 5

def test_configuration_owner_and_registry_checksum_are_stable() -> None:
    registry = load_confidence_scenario_registry()
    assert registry.configuration_path == DEFAULT_REGISTRY_PATH.resolve()
    assert registry.configuration_sha256 == sha256(
        DEFAULT_REGISTRY_PATH.read_bytes()
    ).hexdigest()
    assert registry.source_domain_sha256 == SOURCE_DOMAIN_SHA256
