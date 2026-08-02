"""Tests for opt-in empirical configuration resolution."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import sys

import numpy as np
import pytest
import yaml


from tests.support import REPOSITORY_ROOT
SRC_ROOT = REPOSITORY_ROOT / "src"
for path in (REPOSITORY_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dai_sim.experiments import runner as experiments  # noqa: E402
from dai_sim.inputs import configuration as tranche_a  # noqa: E402
from dai_sim.inputs.environment import load_configuration_profile  # noqa: E402
from dai_sim.model.simulation import run_simulation_with_collateral_metrics  # noqa: E402


PRIMARY_CONFIG = REPOSITORY_ROOT / "config/profiles/empirical.yaml"
LOW_CONFIG = (
    REPOSITORY_ROOT
    / "config/sensitivities/vaults/population_100.yaml"
)
HIGH_CONFIG = (
    REPOSITORY_ROOT
    / "config/sensitivities/vaults/population_1000.yaml"
)
MANIFEST = (
    REPOSITORY_ROOT
    / "data"
    / "protocol"
    / "provenance"
    / "parameter_adoption"
    / "manifest.json"
)


def test_adoption_review_input_checksums_match_manifest() -> None:
    observed = tranche_a.verify_adoption_review_checksums()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert observed == manifest["candidate_registry_checksums"]


def test_primary_empirical_configuration_parses_to_existing_dataclasses() -> None:
    bundle = tranche_a.load_empirical_configuration_bundle(PRIMARY_CONFIG)
    assert bundle.bundle_name == "empirical"
    assert bundle.simulation_config.n_vaults == 500
    assert bundle.liquidation_config.max_close_factor == 1.0
    assert bundle.confidence_config.normal_lower_price == pytest.approx(0.9992875)
    assert bundle.confidence_config.normal_upper_price == pytest.approx(
        1.0030259166666666
    )
    assert bundle.confidence_config.stress_lower_price == pytest.approx(
        0.9967380166666668
    )
    assert bundle.confidence_config.max_normal_liquidatable_share == 0.0
    assert bundle.simulation_config.collateral_portfolio.target_debt_shares == {
        "ETH": pytest.approx(0.8483941126796408),
        "BTC": pytest.approx(0.1516058873203592),
    }


@pytest.mark.parametrize(
    ("path", "expected_vaults", "expected_btc_share"),
    (
        (LOW_CONFIG, 100, 0.08485334085946024),
        (HIGH_CONFIG, 1000, 0.2451900989821847),
    ),
)
def test_sensitivity_configurations_parse(
    path: Path,
    expected_vaults: int,
    expected_btc_share: float,
) -> None:
    bundle = (
        load_configuration_profile(PRIMARY_CONFIG, sensitivity_paths=(path,))
        .tranche_c_bundle.tranche_b_bundle.base_bundle
    )
    shares = bundle.simulation_config.collateral_portfolio.target_debt_shares
    assert bundle.simulation_config.n_vaults == expected_vaults
    assert shares["BTC"] == pytest.approx(expected_btc_share)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_unknown_field_rejection(tmp_path: Path) -> None:
    payload = yaml.safe_load(PRIMARY_CONFIG.read_text(encoding="utf-8"))
    payload["simulation"]["unexpected"] = 1
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown simulation keys"):
        tranche_a.load_empirical_configuration_bundle(bad)


def test_target_debt_shares_must_sum_to_one(tmp_path: Path) -> None:
    payload = yaml.safe_load(PRIMARY_CONFIG.read_text(encoding="utf-8"))
    payload["collateral_portfolio"]["target_debt_shares"]["BTC"] = 0.2
    bad = tmp_path / "bad_shares.yaml"
    bad.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="sum to 1.0"):
        tranche_a.load_empirical_configuration_bundle(bad)


def test_close_factor_validation_rejects_out_of_range_value(tmp_path: Path) -> None:
    payload = yaml.safe_load(PRIMARY_CONFIG.read_text(encoding="utf-8"))
    payload["liquidation"]["max_close_factor"] = 1.2
    bad = tmp_path / "bad_close.yaml"
    bad.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="max_close_factor"):
        tranche_a.load_empirical_configuration_bundle(bad)


def test_manifest_excludes_unsafe_configuration_ready_candidates() -> None:
    manifest = tranche_a.manifest_records(MANIFEST)
    included = {row["parameter"] for row in manifest["included_parameters"]}
    excluded = {row["parameter"] for row in manifest["excluded_parameters"]}
    assert "auction_duration" not in included
    assert {
        "min_collateral_ratio_buffer",
        "mu",
        "sigma",
        "liquidation_ratio",
        "liquidation_penalty",
    } <= excluded
    assert {
        "n_vaults",
        "target_debt_share",
        "max_close_factor",
        "normal_lower_price",
        "normal_upper_price",
        "stress_lower_price",
        "max_normal_liquidatable_share",
    } <= included


def test_legacy_default_factories_remain_unchanged() -> None:
    sim = experiments.create_base_simulation_config()
    confidence = experiments.create_base_confidence_config()
    scenarios = experiments.create_scenario_configs()
    assert sim.n_vaults == 100
    assert sim.collateral_portfolio is None
    assert confidence.normal_lower_price == 0.99
    assert scenarios["high_gas"]["liquidation_config"].max_close_factor == 0.5
    assert scenarios["extreme_panic"]["liquidation_config"].max_close_factor == 0.3


def test_empirical_bundle_is_opt_in_only() -> None:
    source = Path(experiments.__file__).read_text(encoding="utf-8")
    assert "load_empirical_configuration_bundle" not in source
    assert "config/profiles/empirical.yaml" not in source


def test_empirical_smoke_run_completes_with_provenance() -> None:
    bundle = tranche_a.load_empirical_configuration_bundle(PRIMARY_CONFIG)
    config = replace(bundle.simulation_config, n_steps=8, random_seed=7)
    price_path = {
        "ETH": np.full(config.n_steps, 2000.0),
        "BTC": np.full(config.n_steps, 30000.0),
    }
    system, collateral = run_simulation_with_collateral_metrics(
        config=config,
        price_path=price_path,
        liquidation_config=bundle.liquidation_config,
        confidence_config=bundle.confidence_config,
        dai_market_config=bundle.dai_market_config,
    )
    assert len(system) == 8
    assert set(collateral["collateral_type"]) == {"ETH", "BTC"}
    assert (system["total_debt_active"] >= 0).all()
    assert (collateral["collateral_value"] >= 0).all()
    provenance = tranche_a.empirical_run_provenance(
        bundle,
        seed=config.random_seed,
        experiment_name="tranche_a_smoke",
    )
    assert provenance["mode"] == "empirical_tranche_a"
    assert provenance["configuration_bundle_name"] == "empirical"
    assert provenance["configuration_sha256"] == bundle.config_sha256
