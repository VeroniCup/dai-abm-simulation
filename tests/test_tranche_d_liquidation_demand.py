"""Tests for opt-in Tranche D liquidation-arrival demand."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPOSITORY_ROOT / "src"
for path in (REPOSITORY_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from empirical_config import sha256_file  # noqa: E402
from environment_inputs import (  # noqa: E402
    DEFAULT_TRANCHE_D_CONFIG_PATH,
    generate_environment_inputs,
    load_tranche_d_configuration,
)
from experiments import create_base_simulation_config  # noqa: E402
from liquidation import LiquidationConfig, liquidate_vaults  # noqa: E402
from liquidation_demand import (  # noqa: E402
    DEFAULT_LIQUIDATION_ARRIVAL_POOL_PATH,
    LiquidationDemandConfig,
    LiquidationDemandProcess,
    arrival_pool_statistics,
    load_liquidation_arrival_pool,
)
from price_process import PriceProcessConfig, generate_constant_price_path  # noqa: E402
from simulation import run_simulation_with_price_path  # noqa: E402
from vault import Vault  # noqa: E402


ARRIVAL_POOL_SHA = "cc29435bb0434237aba438ee98bded77f086704c7400bb5016e2b58703258c8a"
SEQUENCE_POOL_SHA = "9fdd5f3b5fb97e2dd41d0201bad34909ad05e423ad6b52f65219f49f02a1c7ed"
MARKET_POOL_SHA = "b69276801bacf789f8ae91789983cc98a8a6d42d0a992940c0bcfa109ca25b7d"
GAS_POOL_SHA = "37a5f49f4cc273b9d0d9526609be7f14b91b78939acf26e4dce00b66443e1594"
VAULT_POOL_SHA = "5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892"


def _vaults(n: int = 6, *, debt: float = 1000.0) -> list[Vault]:
    return [
        Vault(
            vault_id=index,
            owner_id=index,
            collateral_amount=0.6,
            debt_dai=debt,
            liquidation_ratio=1.5,
        )
        for index in range(1, n + 1)
    ]


def _constant_path(n_steps: int) -> pd.DataFrame:
    return generate_constant_price_path(
        PriceProcessConfig(n_steps=n_steps, initial_price=1000.0)
    )


def test_default_demand_mode_remains_legacy() -> None:
    config = LiquidationDemandConfig()
    config.validate()
    assert config.mode == "legacy_all_eligible"


def test_invalid_demand_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown liquidation demand mode"):
        LiquidationDemandConfig(mode="surprise").validate()


def test_runtime_pool_reproduces_phase2c_counts() -> None:
    pool = load_liquidation_arrival_pool(
        DEFAULT_LIQUIDATION_ARRIVAL_POOL_PATH,
        ARRIVAL_POOL_SHA,
    )
    stats = arrival_pool_statistics(pool)
    assert len(pool) == 1104
    assert int(pool["bark_count"].sum()) == 649
    assert int(pool["grab_count"].sum()) == 649
    assert int((pool["grab_count"] > 0).sum()) == 65
    assert stats["conditional_inventory_positive_hours"] == 138
    assert stats["conditional_activity_count"] == 48
    assert stats["positive_count_pool_size"] == 65
    assert stats["positive_count_maximum"] == 46
    assert stats["source_maximum_liquidatable_share"] == pytest.approx(
        0.0284697508896797,
    )
    assert sha256_file(DEFAULT_LIQUIDATION_ARRIVAL_POOL_PATH) == ARRIVAL_POOL_SHA
    assert sha256_file(
        REPOSITORY_ROOT
        / "data"
        / "liquidations"
        / "model_inputs"
        / "arrival"
        / "sequence_pool.csv"
    ) == SEQUENCE_POOL_SHA


def test_sequence_pool_reproduces_54_sequences() -> None:
    sequence = pd.read_csv(
        REPOSITORY_ROOT
        / "data"
        / "liquidations"
        / "model_inputs"
        / "arrival"
        / "sequence_pool.csv"
    )
    assert len(sequence) == 54
    assert int(sequence["sequence_size"].sum()) == 649
    assert int(sequence["sequence_size"].median()) == 5
    assert sequence["sequence_size"].mean() == pytest.approx(12.0185185185)
    assert int(sequence["sequence_size"].max()) == 84
    assert int(sequence["duration_seconds"].max()) == 7194


def test_hurdle_process_is_reproducible_and_uses_separate_rng() -> None:
    config = LiquidationDemandConfig(
        mode="empirical_hurdle_count",
        pool_sha256=ARRIVAL_POOL_SHA,
        seed=123,
    )
    first = LiquidationDemandProcess(config)
    second = LiquidationDemandProcess(config)
    draws_a = [
        first.sample_step(step=i, liquidatable_inventory=100, keeper_capacity=10).as_record()
        for i in range(20)
    ]
    draws_b = [
        second.sample_step(step=i, liquidatable_inventory=100, keeper_capacity=10).as_record()
        for i in range(20)
    ]
    assert draws_a == draws_b
    assert first.provenance()["hurdle_probability"] == pytest.approx(
        0.34782608695652173,
    )


def test_zero_inventory_forces_zero_demand() -> None:
    process = LiquidationDemandProcess(
        LiquidationDemandConfig(mode="empirical_hurdle_count", seed=1)
    )
    decision = process.sample_step(
        step=0,
        liquidatable_inventory=0,
        keeper_capacity=5,
    )
    assert decision.sampled_demand == 0
    assert decision.bounded_demand == 0
    assert decision.attempt_budget == 0


def test_inventory_and_capacity_truncation() -> None:
    process = LiquidationDemandProcess(
        LiquidationDemandConfig(
            mode="empirical_hurdle_count",
            seed=1,
            hurdle_probability=1.0,
        )
    )
    decision = process.sample_step(
        step=0,
        liquidatable_inventory=3,
        keeper_capacity=2,
    )
    assert decision.raw_positive_count_draw >= 1
    assert decision.bounded_demand <= 3
    assert decision.attempt_budget <= 2
    assert decision.attempt_budget <= decision.bounded_demand


def test_hurdle_inactivity_forces_zero_sampled_demand() -> None:
    process = LiquidationDemandProcess(
        LiquidationDemandConfig(
            mode="empirical_hurdle_count",
            seed=1,
            hurdle_probability=0.0,
        )
    )
    decision = process.sample_step(
        step=0,
        liquidatable_inventory=100,
        keeper_capacity=None,
    )
    assert not decision.activity_draw
    assert decision.sampled_demand == 0
    assert decision.bounded_demand == 0
    assert decision.attempt_budget == 0


def test_positive_count_draws_are_empirical_and_with_replacement() -> None:
    process = LiquidationDemandProcess(
        LiquidationDemandConfig(
            mode="empirical_hurdle_count",
            seed=3,
            hurdle_probability=1.0,
        )
    )
    empirical_support = set(process.positive_counts.tolist())
    draws = [
        process.sample_step(
            step=step,
            liquidatable_inventory=1000,
            keeper_capacity=None,
        ).sampled_demand
        for step in range(200)
    ]
    assert set(draws) <= empirical_support
    assert len(draws) > len(set(draws))


def test_bounded_liquidation_uses_existing_profit_ordering_and_preserves_inventory() -> None:
    vaults = _vaults(5)
    result = liquidate_vaults(
        vaults=vaults,
        prices=1000.0,
        config=LiquidationConfig(max_liquidations_per_step=10),
        bounded_demand=2,
        attempt_budget=1,
    )
    assert int(result["attempted"].sum()) == 1
    assert int(result["liquidated"].sum()) == 1
    assert int((result["reason"] == "capacity_limited").sum()) == 1
    assert int((result["reason"] == "demand_not_sampled").sum()) == 3
    assert sum(vault.is_liquidatable(1000.0) for vault in vaults) == 4


def test_unprofitable_selected_opportunities_remain_unprofitable() -> None:
    result = liquidate_vaults(
        vaults=_vaults(3, debt=500.0),
        prices=1000.0,
        config=LiquidationConfig(gas_cost=10_000.0),
        bounded_demand=3,
        attempt_budget=3,
    )
    assert int(result["attempted"].sum()) == 3
    assert int(result["liquidated"].sum()) == 0
    assert set(result["reason"]) == {"unprofitable"}


def test_empirical_full_close_factor_closes_selected_profitable_vault() -> None:
    vaults = _vaults(1)
    result = liquidate_vaults(
        vaults=vaults,
        prices=1000.0,
        config=LiquidationConfig(max_close_factor=1.0),
        bounded_demand=1,
        attempt_budget=1,
    )
    assert bool(result.loc[0, "liquidated"])
    assert vaults[0].debt_dai == pytest.approx(0.0)
    assert result.loc[0, "remaining_debt"] == pytest.approx(0.0)


def test_legacy_partial_close_scenario_is_unchanged() -> None:
    legacy_vaults = [
        Vault(
            vault_id=1,
            owner_id=1,
            collateral_amount=14.0,
            debt_dai=10_000.0,
            liquidation_ratio=1.5,
        )
    ]
    explicit_legacy_vaults = [
        Vault(
            vault_id=1,
            owner_id=1,
            collateral_amount=14.0,
            debt_dai=10_000.0,
            liquidation_ratio=1.5,
        )
    ]
    legacy = liquidate_vaults(
        vaults=legacy_vaults,
        prices=1000.0,
        config=LiquidationConfig(max_close_factor=0.25),
    )
    explicit_legacy = liquidate_vaults(
        vaults=explicit_legacy_vaults,
        prices=1000.0,
        config=LiquidationConfig(max_close_factor=0.25),
    )
    pd.testing.assert_frame_equal(legacy, explicit_legacy)
    assert legacy_vaults[0].debt_dai == pytest.approx(7500.0)
    assert legacy.loc[0, "remaining_debt"] == pytest.approx(7500.0)


def test_legacy_simulation_output_is_unchanged_with_default_demand_mode() -> None:
    config = replace(create_base_simulation_config(), n_steps=3, n_vaults=6)
    price_path = _constant_path(config.n_steps)
    liquidation = LiquidationConfig(max_liquidations_per_step=2)
    legacy = run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=liquidation,
        initial_vaults=_vaults(6),
    )
    explicit_legacy = run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=liquidation,
        initial_vaults=_vaults(6),
        liquidation_demand_process=LiquidationDemandProcess(LiquidationDemandConfig()),
    )
    pd.testing.assert_frame_equal(legacy, explicit_legacy)
    assert not any("liquidation_demand" in column for column in legacy.columns)


def test_empirical_simulation_demand_invariants() -> None:
    config = replace(create_base_simulation_config(), n_steps=4, n_vaults=10)
    result = run_simulation_with_price_path(
        config=config,
        price_path=_constant_path(config.n_steps),
        liquidation_config=LiquidationConfig(max_liquidations_per_step=2),
        initial_vaults=_vaults(10),
        liquidation_demand_process=LiquidationDemandProcess(
            LiquidationDemandConfig(
                mode="empirical_hurdle_count",
                seed=1,
                hurdle_probability=1.0,
            )
        ),
    )
    assert (result["bounded_liquidation_demand"] <= result["n_liquidatable_before_liquidation"]).all()
    assert (result["liquidation_attempt_budget"] <= result["bounded_liquidation_demand"]).all()
    assert (result["liquidation_attempt_budget"] <= 2).all()
    assert (result["n_successful_liquidations"] <= result["n_attempted_liquidations"]).all()
    assert (result["n_attempted_liquidations"] <= result["liquidation_attempt_budget"]).all()
    assert (result["liquidation_unresolved_inventory_after_step"] >= 0).all()


def test_tranche_d_configuration_loads_and_preserves_tranche_c_pools() -> None:
    bundle = load_tranche_d_configuration(DEFAULT_TRANCHE_D_CONFIG_PATH)
    assert bundle.liquidation_demand.mode == "empirical_hurdle_count"
    assert bundle.tranche_c_bundle.market_process.mode == "empirical_block_bootstrap"
    assert bundle.tranche_c_bundle.gas_process.mode == "empirical_components"
    assert bundle.tranche_c_bundle.gas_process.pool_sha256 == GAS_POOL_SHA
    assert bundle.tranche_c_bundle.market_process.pool_sha256 == MARKET_POOL_SHA
    assert bundle.tranche_c_bundle.tranche_b_bundle.initialisation.pool_sha256 == VAULT_POOL_SHA
    generated = generate_environment_inputs(bundle)
    assert generated.liquidation_demand is not None
    assert generated.provenance["liquidation_demand"]["positive_count_pool_size"] == 65


def test_tranche_d_sensitivity_base_config_overrides() -> None:
    lower = load_tranche_d_configuration(
        DEFAULT_TRANCHE_D_CONFIG_PATH,
        sensitivity_paths=(
            REPOSITORY_ROOT / "config/sensitivities/liquidations/hurdle_low.yaml",
        ),
    )
    capacity = load_tranche_d_configuration(
        DEFAULT_TRANCHE_D_CONFIG_PATH,
        sensitivity_paths=(
            REPOSITORY_ROOT / "config/sensitivities/liquidations/capacity_low.yaml",
        ),
    )
    legacy = load_tranche_d_configuration(
        DEFAULT_TRANCHE_D_CONFIG_PATH,
        sensitivity_paths=(
            REPOSITORY_ROOT / "config/sensitivities/liquidations/legacy_demand.yaml",
        ),
    )
    assert lower.liquidation_demand.hurdle_probability == pytest.approx(
        0.2608695652173913,
    )
    assert capacity.tranche_c_bundle.tranche_b_bundle.base_bundle.liquidation_config.max_liquidations_per_step == 5
    assert legacy.liquidation_demand.mode == "legacy_all_eligible"
