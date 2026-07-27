"""Tests for opt-in Tranche B distribution-aware vault initialisation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPOSITORY_ROOT / "src"
for path in (REPOSITORY_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import experiments  # noqa: E402
from empirical_config import load_empirical_configuration_bundle, sha256_file  # noqa: E402
from simulation import create_initial_vaults, run_simulation_with_collateral_metrics  # noqa: E402
from vault import vaults_to_dataframe  # noqa: E402
from vault_initialisation import (  # noqa: E402
    DEFAULT_POOL_PATH,
    DEFAULT_TRANCHE_B_CONFIG_PATH,
    ParametricFamilyConfig,
    VaultInitialisationConfig,
    compare_sample_to_pool,
    initialise_vaults,
    load_pool,
    load_tranche_b_configuration,
)


def test_default_mode_is_legacy_gaussian() -> None:
    config = VaultInitialisationConfig()
    assert config.mode == "legacy_gaussian"
    config.validate()


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown vault initialisation mode"):
        VaultInitialisationConfig(mode="surprise").validate()


def test_legacy_initialisation_matches_existing_create_initial_vaults() -> None:
    sim = experiments.create_base_simulation_config()
    legacy = create_initial_vaults(sim)
    result = initialise_vaults(sim, VaultInitialisationConfig())
    legacy_frame = vaults_to_dataframe(legacy, sim.initial_eth_price)
    result_frame = vaults_to_dataframe(result.vaults, sim.initial_eth_price)
    pd.testing.assert_frame_equal(result_frame, legacy_frame)


def test_tranche_a_configuration_values_are_unchanged() -> None:
    bundle = load_empirical_configuration_bundle()
    assert bundle.config_sha256 == "ba5b835065c7749650c24ecba85a993fdfc6f8ac2aa0960ce27e54817d13ed3e"
    assert bundle.simulation_config.n_vaults == 500
    assert bundle.liquidation_config.max_close_factor == 1.0


def test_pool_schema_and_checksum() -> None:
    pool = load_pool(
        DEFAULT_POOL_PATH,
        "5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892",
    )
    assert len(pool) == 7208
    assert set(pool["regime_label"]) == {"normal", "moderate_stress", "severe_stress"}
    assert set(pool["collateral_family"]) == {"ETH", "WBTC"}
    assert (pool["debt_dai"] > 0).all()
    assert (pool["absolute_buffer"] >= 0).all()


def test_tranche_b_config_parses_and_uses_empirical_joint_mode() -> None:
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    assert bundle.initialisation.mode == "empirical_joint"
    assert bundle.initialisation.regime == "normal"
    assert bundle.initialisation.by_ilk is True
    assert bundle.base_bundle.simulation_config.n_vaults == 500


def test_empirical_joint_sampling_is_deterministic() -> None:
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    first = initialise_vaults(bundle.base_bundle.simulation_config, bundle.initialisation)
    second = initialise_vaults(bundle.base_bundle.simulation_config, bundle.initialisation)
    pd.testing.assert_frame_equal(first.sampled_rows, second.sampled_rows)
    assert first.provenance == second.provenance


def test_empirical_joint_preserves_debt_ratio_pairs() -> None:
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    result = initialise_vaults(bundle.base_bundle.simulation_config, bundle.initialisation)
    pool = load_pool(DEFAULT_POOL_PATH)
    joined = result.sampled_rows.merge(
        pool[["pool_row_id", "debt_dai", "collateral_ratio"]],
        on="pool_row_id",
        suffixes=("_sample", "_pool"),
    )
    assert len(joined) == len(result.sampled_rows)
    assert np.allclose(joined["debt_dai_sample"], joined["debt_dai_pool"])
    assert np.allclose(
        joined["collateral_ratio_sample"],
        joined["collateral_ratio_pool"],
    )


def test_exact_ilk_fallback_hierarchy_uses_family_pool_for_small_ilk() -> None:
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    config = replace(bundle.initialisation, regime="severe_stress")
    result = initialise_vaults(bundle.base_bundle.simulation_config, config)
    assert result.provenance["fallback_counts"]["family_pool"] > 0
    assert result.provenance["fallback_counts"]["exact_ilk_pool"] > 0


def test_sampling_with_replacement_is_recorded() -> None:
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    config = replace(bundle.base_bundle.simulation_config, n_vaults=2500)
    result = initialise_vaults(config, bundle.initialisation)
    assert result.provenance["replacement_used"] is True
    assert result.provenance["duplicate_empirical_row_draw_count"] > 0


def test_parametric_truncated_sampling_is_positive_and_bounded() -> None:
    bundle = load_tranche_b_configuration(
        REPOSITORY_ROOT / "config/empirical/sensitivity/phase2_empirical_parametric_truncated.yaml"
    )
    result = initialise_vaults(bundle.base_bundle.simulation_config, bundle.initialisation)
    rows = result.sampled_rows
    assert len(rows) == 500
    assert (rows["debt_dai"] > 0).all()
    assert (rows["absolute_buffer"] >= 0).all()
    assert np.allclose(
        rows["collateral_ratio"],
        rows["liquidation_ratio"] + rows["absolute_buffer"],
    )


def test_parametric_max_attempt_failure() -> None:
    bad = VaultInitialisationConfig(
        mode="parametric_truncated",
        seed=1,
        regime="normal",
        max_sampling_attempts=3,
        parametric={
            "ETH": ParametricFamilyConfig(
                debt_log_mean=10,
                debt_log_std=1,
                buffer_log_mean=1,
                buffer_log_std=1,
                liquidation_ratio=1.45,
                minimum_debt=1,
                maximum_debt=2,
                minimum_buffer=0,
                maximum_buffer=1,
            ),
            "WBTC": ParametricFamilyConfig(
                debt_log_mean=10,
                debt_log_std=1,
                buffer_log_mean=1,
                buffer_log_std=1,
                liquidation_ratio=1.75,
                minimum_debt=1,
                maximum_debt=2,
                minimum_buffer=0,
                maximum_buffer=1,
            ),
        },
    )
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    with pytest.raises(ValueError, match="Could not generate"):
        initialise_vaults(replace(bundle.base_bundle.simulation_config, n_vaults=4), bad)


def test_population_count_and_debt_share_diagnostics() -> None:
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    result = initialise_vaults(bundle.base_bundle.simulation_config, bundle.initialisation)
    frame = vaults_to_dataframe(
        result.vaults,
        bundle.base_bundle.simulation_config.collateral_portfolio.initial_prices,
    )
    assert len(frame) == 500
    debt_share = frame.groupby("collateral_type")["debt_dai"].sum()
    debt_share = debt_share / debt_share.sum()
    assert set(debt_share.index) == {"BTC", "ETH"}
    assert debt_share["ETH"] > 0
    assert debt_share["BTC"] > 0


def test_no_initial_liquidatable_vault_under_zero_threshold() -> None:
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    result = initialise_vaults(bundle.base_bundle.simulation_config, bundle.initialisation)
    assert result.provenance["initial_liquidatable_count"] == 0
    assert result.provenance["initial_liquidatable_share"] == 0.0


def test_simulation_accepts_explicit_tranche_b_initial_vaults() -> None:
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    sim = replace(bundle.base_bundle.simulation_config, n_steps=4)
    init = initialise_vaults(sim, bundle.initialisation)
    prices = {
        "ETH": np.full(sim.n_steps, 2000.0),
        "BTC": np.full(sim.n_steps, 30000.0),
    }
    system, collateral = run_simulation_with_collateral_metrics(
        config=sim,
        price_path=prices,
        liquidation_config=bundle.base_bundle.liquidation_config,
        confidence_config=bundle.base_bundle.confidence_config,
        dai_market_config=bundle.base_bundle.dai_market_config,
        initial_vaults=init.vaults,
    )
    assert len(system) == 4
    assert set(collateral["collateral_type"]) == {"ETH", "BTC"}


def test_distribution_comparison_contains_dependence_rows() -> None:
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    result = initialise_vaults(bundle.base_bundle.simulation_config, bundle.initialisation)
    pool = load_pool(DEFAULT_POOL_PATH)
    comparison = compare_sample_to_pool(
        result.sampled_rows,
        pool.loc[pool["regime_label"].eq("normal")],
    )
    assert {"debt_dai", "collateral_ratio", "absolute_buffer", "debt_buffer_dependence"} <= set(
        comparison["variable"]
    )


def test_loader_rejects_unknown_initialisation_field(tmp_path: Path) -> None:
    payload = yaml.safe_load(DEFAULT_TRANCHE_B_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["vault_initialisation"]["unexpected"] = True
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown vault_initialisation keys"):
        load_tranche_b_configuration(bad)


def test_pool_builder_is_deterministic(tmp_path: Path) -> None:
    from scripts import build_vault_initialisation_pools as builder

    first_pool, first_audit = builder.build_pool()
    second_pool, second_audit = builder.build_pool()
    pd.testing.assert_frame_equal(first_pool, second_pool)
    pd.testing.assert_frame_equal(first_audit, second_audit)


def test_tracked_pool_manifest_matches_file() -> None:
    manifest = yaml.safe_load(
        (REPOSITORY_ROOT / "config/empirical/data/vault_initialisation_pools_manifest.json")
        .read_text(encoding="utf-8")
    )
    assert manifest["output_sha256"] == sha256_file(DEFAULT_POOL_PATH)
