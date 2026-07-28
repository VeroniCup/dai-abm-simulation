"""Stage 4 semantic profile and explicit sensitivity contracts."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys

import pytest
import yaml

from tests.support import REPOSITORY_ROOT as ROOT
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dai_sim.inputs.configuration import (
    apply_configuration_overrides,
    load_configuration_payload,
)
from dai_sim.inputs.environment import (
    configuration_behaviour_payload,
    configuration_behaviour_sha256,
    load_configuration_profile,
    load_tranche_d_configuration,
)
from dai_sim.model.confidence import ConfidenceConfig
from dai_sim.model.liquidation import LiquidationConfig
from dai_sim.model.market import DAIMarketConfig
from dai_sim.model.simulation import SimulationConfig


PROFILE_DIR = ROOT / "config" / "profiles"
EMPIRICAL = PROFILE_DIR / "empirical.yaml"
STRESS = PROFILE_DIR / "empirical_stress.yaml"
LEGACY = PROFILE_DIR / "legacy.yaml"
STRESS_SENSITIVITIES = (
    ROOT / "config/sensitivities/gas/high_q90.yaml",
    ROOT / "config/sensitivities/liquidations/hurdle_high.yaml",
    ROOT / "config/sensitivities/liquidations/capacity_low.yaml",
)
COMPLETE_COMPONENTS = {
    "simulation",
    "collateral_portfolio",
    "liquidation",
    "confidence",
    "dai_market",
    "vault_initialisation",
    "market_process",
    "gas_process",
    "liquidation_demand",
}


def _yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _leaves(value, prefix=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _leaves(child, prefix + (str(key),))
    else:
        yield prefix, value


@pytest.mark.parametrize("path", (LEGACY, EMPIRICAL, STRESS))
def test_complete_semantic_profiles_parse_without_inheritance(path: Path) -> None:
    payload = _yaml(path)
    assert COMPLETE_COMPONENTS <= set(payload)
    assert "base_config" not in payload
    assert "parent_profile" not in payload
    assert "phase2" not in str(payload["bundle_name"])
    assert "tranche_" not in str(payload["mode"])
    load_configuration_profile(path)


def test_legacy_profile_matches_executable_defaults() -> None:
    bundle = load_configuration_profile(LEGACY)
    base = bundle.tranche_c_bundle.tranche_b_bundle.base_bundle
    simulation = asdict(base.simulation_config)
    executable = asdict(SimulationConfig())
    simulation.pop("collateral_portfolio")
    executable.pop("collateral_portfolio")
    assert simulation == executable
    assert base.simulation_config.collateral_portfolio.collateral_names == ("ETH",)
    assert base.liquidation_config == LiquidationConfig()
    assert base.confidence_config == ConfidenceConfig()
    assert base.dai_market_config == DAIMarketConfig()
    assert bundle.tranche_c_bundle.tranche_b_bundle.initialisation.mode == "legacy_gaussian"
    assert bundle.tranche_c_bundle.market_process.mode == "legacy_gbm"
    assert bundle.tranche_c_bundle.gas_process.mode == "legacy_scalar"
    assert bundle.liquidation_demand.mode == "legacy_all_eligible"


def test_empirical_profile_behaviour_is_frozen() -> None:
    semantic = load_configuration_profile(EMPIRICAL)
    assert configuration_behaviour_sha256(semantic) == (
        "8f5c7864ad03fd7d4e24e41f79c1511024459e4b67d8d2e81ef0f653188498e9"
    )


def test_stress_sources_have_disjoint_behavioural_leaf_paths() -> None:
    paths = []
    for source in STRESS_SENSITIVITIES:
        overrides = _yaml(source)["overrides"]
        paths.append({path for path, _ in _leaves(overrides)})
    assert not (paths[0] & paths[1])
    assert not (paths[0] & paths[2])
    assert not (paths[1] & paths[2])


def test_materialised_stress_equals_ordered_override_result() -> None:
    materialised = load_configuration_profile(STRESS)
    composed = load_configuration_profile(
        EMPIRICAL,
        sensitivity_paths=STRESS_SENSITIVITIES,
    )
    assert configuration_behaviour_payload(materialised) == configuration_behaviour_payload(
        composed
    )
    assert configuration_behaviour_sha256(materialised) == configuration_behaviour_sha256(
        composed
    )


def test_stress_has_exactly_three_behavioural_differences() -> None:
    empirical = dict(_leaves(configuration_behaviour_payload(
        load_configuration_profile(EMPIRICAL)
    )))
    stress = dict(_leaves(configuration_behaviour_payload(
        load_configuration_profile(STRESS)
    )))
    differences = {
        ".".join(path): (empirical[path], stress[path])
        for path in empirical
        if empirical[path] != stress[path]
    }
    assert differences == {
        "gas_process.network_gas_column": (
            "median_effective_gas_price_gwei",
            "p90_effective_gas_price_gwei",
        ),
        "liquidation.max_liquidations_per_step": (None, 5),
        "liquidation_demand.hurdle_probability": (
            0.34782608695652173,
            0.43478260869565216,
        ),
    }


def test_recursive_override_contract_and_ordering() -> None:
    profile = {
        "simulation": {"n_vaults": 1, "labels": [1, 2]},
        "confidence": {"enabled": True},
    }
    first = {
        "overrides": {"simulation": {"n_vaults": 2, "labels": [3]}}
    }
    second = {"overrides": {"simulation": {"n_vaults": 4}}}
    result = apply_configuration_overrides(profile, [first, second])
    assert result == {
        "simulation": {"n_vaults": 4, "labels": [3]},
        "confidence": {"enabled": True},
    }
    assert profile == {
        "simulation": {"n_vaults": 1, "labels": [1, 2]},
        "confidence": {"enabled": True},
    }


@pytest.mark.parametrize(
    "override, message",
    (
        ({"overrides": {"simulation": 2}}, "mapping required"),
        ({"overrides": {"unknown": {"x": 1}}}, "unsupported override keys"),
        ({"overrides": {}}, "non-empty mapping"),
        ({"unexpected": True, "overrides": {"simulation": {}}}, "Unknown sensitivity"),
    ),
)
def test_malformed_or_conflicting_overrides_fail(override: dict, message: str) -> None:
    profile = {"a": {"x": 1}, "simulation": {"n_vaults": 100}}
    with pytest.raises(ValueError, match=message):
        apply_configuration_overrides(profile, [override])


def test_semantic_sensitivity_files_are_explicit_partial_overrides() -> None:
    files = sorted((ROOT / "config/sensitivities").glob("*/*.yaml"))
    assert len(files) == 14
    for path in files:
        payload = _yaml(path)
        assert set(payload) == {
            "sensitivity_name",
            "description",
            "source_path",
            "source_sha256",
            "overrides",
        }
        assert payload["overrides"]
        assert len(payload["source_sha256"]) == 64


def test_explicit_sensitivity_application_runs_final_validation(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        "\n".join(
            (
                "sensitivity_name: invalid",
                "description: invalid close factor",
                "source_path: config/profiles/empirical.yaml",
                "source_sha256: 31bcc1f038311e2de2355114adbcc599f257105fe5bef3a0181e7b0e95b8f6fc",
                "overrides:",
                "  liquidation:",
                "    max_close_factor: 2.0",
                "",
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="max_close_factor"):
        load_configuration_profile(EMPIRICAL, sensitivity_paths=(invalid,))


def test_loading_profile_payload_does_not_apply_sensitivities_implicitly() -> None:
    plain = load_configuration_payload(EMPIRICAL)
    assert plain["gas_process"]["network_gas_column"] == (
        "median_effective_gas_price_gwei"
    )
