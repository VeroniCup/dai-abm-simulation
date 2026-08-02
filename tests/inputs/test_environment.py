"""Tests for opt-in empirical market and gas environment inputs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


from tests.support import REPOSITORY_ROOT
SRC_ROOT = REPOSITORY_ROOT / "src"
for path in (REPOSITORY_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dai_sim.inputs.configuration import sha256_file  # noqa: E402
from dai_sim.inputs.environment import (  # noqa: E402
    DEFAULT_TRANCHE_C_CONFIG_PATH,
    generate_environment_inputs,
    load_tranche_c_configuration,
)
from dai_sim.experiments.runner import create_base_simulation_config  # noqa: E402
from dai_sim.inputs.gas import (  # noqa: E402
    DEFAULT_LIQUIDATION_GAS_POOL_PATH,
    GasProcessConfig,
    component_gas_costs,
    load_liquidation_gas_pool,
    sample_total_gas_costs,
)
from dai_sim.model.liquidation import LiquidationConfig  # noqa: E402
from dai_sim.inputs.market import (  # noqa: E402
    DEFAULT_MARKET_GAS_POOL_PATH,
    MarketProcessConfig,
    generate_empirical_price_paths,
    load_market_gas_pool,
    sample_market_gas_blocks,
    valid_block_starts,
)
from dai_sim.model.collateral_prices import (  # noqa: E402
    PriceProcessConfig,
    generate_gbm_price_path,
)
from dai_sim.model.simulation import run_simulation_with_price_path  # noqa: E402


MARKET_POOL_SHA = "b69276801bacf789f8ae91789983cc98a8a6d42d0a992940c0bcfa109ca25b7d"
GAS_POOL_SHA = "37a5f49f4cc273b9d0d9526609be7f14b91b78939acf26e4dce00b66443e1594"
VAULT_POOL_SHA = "5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892"


def _write_test_gas_pool(path: Path, gas_units: float = 100_000.0) -> None:
    frame = pd.DataFrame(
        [
            {
                "gas_pool_row_id": 1,
                "event_type": "clean_successful_take_transaction",
                "sample_role": "calibration",
                "regime_label": "normal",
                "is_primary_eligible": True,
                "is_zero_gas_observation": False,
                "gas_units": gas_units,
                "effective_gas_price_gwei": 1.0,
                "eth_price_usd": 999.0,
                "transaction_gas_cost_eth": gas_units * 1e-9,
                "transaction_gas_cost_usd": 999.0 * gas_units * 1e-9,
            }
        ]
    )
    frame.to_csv(path, index=False, lineterminator="\n")


def test_default_modes_remain_legacy() -> None:
    market = MarketProcessConfig()
    gas = GasProcessConfig()
    assert market.mode == "legacy_gbm"
    assert gas.mode == "legacy_scalar"
    market.validate()
    gas.validate()


def test_invalid_market_and_gas_modes_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown market process mode"):
        MarketProcessConfig(mode="mystery").validate()
    with pytest.raises(ValueError, match="Unknown gas process mode"):
        GasProcessConfig(mode="mystery").validate()


def test_runtime_pool_schema_and_checksums() -> None:
    market = load_market_gas_pool(DEFAULT_MARKET_GAS_POOL_PATH, MARKET_POOL_SHA)
    gas = load_liquidation_gas_pool(DEFAULT_LIQUIDATION_GAS_POOL_PATH, GAS_POOL_SHA)
    assert len(market) == 27024
    assert len(gas) == 1287
    assert sha256_file(DEFAULT_MARKET_GAS_POOL_PATH) == MARKET_POOL_SHA
    assert sha256_file(DEFAULT_LIQUIDATION_GAS_POOL_PATH) == GAS_POOL_SHA
    assert int(market["is_withheld_ftx"].sum()) == 480
    assert int(gas["is_zero_gas_observation"].sum()) == 4
    forbidden = {"tx_hash", "owner", "urn", "address"}
    assert forbidden.isdisjoint(set(market.columns))
    assert forbidden.isdisjoint(set(gas.columns))


@pytest.mark.parametrize(
    ("block_length", "expected_count"),
    ((72, 26401), (168, 26209), (336, 25873)),
)
def test_valid_block_starts_exclude_ftx_and_missing_returns(
    block_length: int,
    expected_count: int,
) -> None:
    pool = load_market_gas_pool(DEFAULT_MARKET_GAS_POOL_PATH, MARKET_POOL_SHA)
    starts = valid_block_starts(
        pool,
        block_length_hours=block_length,
        pool_label="all_calibration",
    )
    assert len(starts) == expected_count
    assert starts[0] == 1
    for start in starts[:10] + starts[-10:]:
        window = pool.iloc[start : start + block_length]
        assert not window["is_withheld_ftx"].any()
        assert window["return_observation_valid"].all()


def test_empirical_block_sampling_is_deterministic_and_paired() -> None:
    pool = load_market_gas_pool(DEFAULT_MARKET_GAS_POOL_PATH, MARKET_POOL_SHA)
    first, first_meta = sample_market_gas_blocks(
        pool,
        horizon=250,
        block_length_hours=168,
        seed=123,
        pool_label="all_calibration",
    )
    second, second_meta = sample_market_gas_blocks(
        pool,
        horizon=250,
        block_length_hours=168,
        seed=123,
        pool_label="all_calibration",
    )
    pd.testing.assert_frame_equal(first, second)
    assert first_meta == second_meta
    assert len(first) == 250
    assert first_meta["final_truncated_block_length"] == 82
    assert {"eth_log_return", "wbtc_log_return", "median_effective_gas_price_gwei"} <= set(
        first.columns
    )


def test_empirical_price_paths_are_positive_and_reproducible() -> None:
    config = MarketProcessConfig(
        mode="empirical_block_bootstrap",
        pool_path=DEFAULT_MARKET_GAS_POOL_PATH,
        pool_sha256=MARKET_POOL_SHA,
        seed=987,
        block_length_hours=72,
    )
    first = generate_empirical_price_paths(
        n_steps=50,
        initial_prices={"ETH": 2000.0, "BTC": 30000.0},
        config=config,
    )
    second = generate_empirical_price_paths(
        n_steps=50,
        initial_prices={"ETH": 2000.0, "BTC": 30000.0},
        config=config,
    )
    assert set(first.price_paths) == {"ETH", "BTC"}
    assert np.array_equal(first.price_paths["ETH"], second.price_paths["ETH"])
    assert np.array_equal(first.price_paths["BTC"], second.price_paths["BTC"])
    assert (first.price_paths["ETH"] > 0).all()
    assert (first.price_paths["BTC"] > 0).all()


def test_legacy_gbm_seeded_path_is_unchanged() -> None:
    path = generate_gbm_price_path(
        PriceProcessConfig(n_steps=5, initial_price=2000.0, random_seed=42)
    )
    assert path["eth_price"].round(6).tolist() == [
        2000.0,
        2023.907735,
        1935.963718,
        1996.015342,
        2074.377851,
    ]


def test_gas_total_cost_primary_excludes_zero_and_zero_sensitivity_includes_it() -> None:
    primary = sample_total_gas_costs(
        n_steps=200,
        config=GasProcessConfig(
            mode="empirical_total_cost",
            pool_path=DEFAULT_LIQUIDATION_GAS_POOL_PATH,
            pool_sha256=GAS_POOL_SHA,
            seed=1,
            zero_observation_policy="exclude_zero_primary",
        ),
    )
    inclusive = sample_total_gas_costs(
        n_steps=200,
        config=GasProcessConfig(
            mode="empirical_total_cost",
            pool_path=DEFAULT_LIQUIDATION_GAS_POOL_PATH,
            pool_sha256=GAS_POOL_SHA,
            seed=1,
            zero_observation_policy="include_zero_sensitivity",
        ),
    )
    assert primary.provenance["eligible_pool_size"] == 1283
    assert inclusive.provenance["eligible_pool_size"] == 1287
    assert primary.gas_cost_usd.min() > 0
    assert inclusive.provenance["zero_observations_in_source_pool"] == 4


def test_component_gas_formula_uses_units_gwei_and_eth_price() -> None:
    config = MarketProcessConfig(
        mode="empirical_block_bootstrap",
        pool_path=DEFAULT_MARKET_GAS_POOL_PATH,
        pool_sha256=MARKET_POOL_SHA,
        seed=11,
        block_length_hours=72,
    )
    market = generate_empirical_price_paths(
        n_steps=10,
        initial_prices={"ETH": 2000.0, "BTC": 30000.0},
        config=config,
    )
    result = component_gas_costs(
        sampled_market_gas_rows=market.sampled_rows,
        simulated_eth_prices=market.price_paths["ETH"],
        config=GasProcessConfig(
            mode="empirical_components",
            pool_path=DEFAULT_LIQUIDATION_GAS_POOL_PATH,
            pool_sha256=GAS_POOL_SHA,
            seed=12,
        ),
    )
    expected = (
        result.sampled_rows["gas_units"].to_numpy(dtype=float)
        * result.sampled_rows["network_gas_price_gwei"].to_numpy(dtype=float)
        * 1e-9
        * result.sampled_rows["runtime_eth_price_usd"].to_numpy(dtype=float)
    )
    assert np.allclose(result.gas_cost_usd, expected)
    assert (result.gas_cost_usd >= 0).all()
    assert np.array_equal(
        result.sampled_rows["runtime_eth_price_usd"].to_numpy(dtype=float),
        market.price_paths["ETH"],
    )


def test_component_gas_uses_simulated_eth_not_historical_source_price(
    tmp_path: Path,
) -> None:
    gas_pool_path = tmp_path / "gas_pool.csv"
    _write_test_gas_pool(gas_pool_path)
    sampled_rows = pd.DataFrame(
        {
            "median_effective_gas_price_gwei": [10.0, 20.0, 30.0],
            "eth_price_usd": [9_999.0, 8_888.0, 7_777.0],
        }
    )
    simulated_eth_prices = np.array([1_000.0, 2_000.0, 3_000.0])
    result = component_gas_costs(
        sampled_market_gas_rows=sampled_rows,
        simulated_eth_prices=simulated_eth_prices,
        config=GasProcessConfig(
            mode="empirical_components",
            pool_path=gas_pool_path,
            seed=1,
        ),
    )
    expected = np.array([1.0, 4.0, 9.0])
    assert np.allclose(result.gas_cost_usd, expected)
    assert np.allclose(
        result.sampled_rows["runtime_eth_price_usd"].to_numpy(dtype=float),
        simulated_eth_prices,
    )

    changed_history = sampled_rows.copy()
    changed_history["eth_price_usd"] = [1.0, 1.0, 1.0]
    changed = component_gas_costs(
        sampled_market_gas_rows=changed_history,
        simulated_eth_prices=simulated_eth_prices,
        config=GasProcessConfig(
            mode="empirical_components",
            pool_path=gas_pool_path,
            seed=1,
        ),
    )
    assert np.array_equal(result.gas_cost_usd, changed.gas_cost_usd)


def test_component_gas_scales_with_simulated_eth_price(tmp_path: Path) -> None:
    gas_pool_path = tmp_path / "gas_pool.csv"
    _write_test_gas_pool(gas_pool_path)
    sampled_rows = pd.DataFrame({"median_effective_gas_price_gwei": [15.0, 15.0]})
    base = component_gas_costs(
        sampled_market_gas_rows=sampled_rows,
        simulated_eth_prices=[1_000.0, 2_000.0],
        config=GasProcessConfig(
            mode="empirical_components",
            pool_path=gas_pool_path,
            seed=1,
        ),
    )
    doubled = component_gas_costs(
        sampled_market_gas_rows=sampled_rows,
        simulated_eth_prices=[2_000.0, 4_000.0],
        config=GasProcessConfig(
            mode="empirical_components",
            pool_path=gas_pool_path,
            seed=1,
        ),
    )
    assert np.allclose(doubled.gas_cost_usd, 2.0 * base.gas_cost_usd)


def test_component_gas_rejects_misaligned_or_invalid_simulated_eth_prices(
    tmp_path: Path,
) -> None:
    gas_pool_path = tmp_path / "gas_pool.csv"
    _write_test_gas_pool(gas_pool_path)
    sampled_rows = pd.DataFrame({"median_effective_gas_price_gwei": [10.0, 20.0]})
    config = GasProcessConfig(
        mode="empirical_components",
        pool_path=gas_pool_path,
        seed=1,
    )
    component_gas_costs(
        sampled_market_gas_rows=sampled_rows.iloc[:1],
        simulated_eth_prices=[2_000.0],
        config=config,
    )
    with pytest.raises(ValueError, match="simulated_eth_prices length"):
        component_gas_costs(
            sampled_market_gas_rows=sampled_rows,
            simulated_eth_prices=[2_000.0],
            config=config,
        )
    with pytest.raises(ValueError, match="finite and positive"):
        component_gas_costs(
            sampled_market_gas_rows=sampled_rows,
            simulated_eth_prices=[2_000.0, 0.0],
            config=config,
        )


def test_tranche_c_configuration_is_explicit_and_preserves_vault_pool() -> None:
    bundle = load_tranche_c_configuration(DEFAULT_TRANCHE_C_CONFIG_PATH)
    assert bundle.market_process.mode == "empirical_block_bootstrap"
    assert bundle.gas_process.mode == "empirical_components"
    assert bundle.tranche_b_bundle.initialisation.mode == "empirical_joint"
    assert bundle.tranche_b_bundle.initialisation.pool_sha256 == VAULT_POOL_SHA


def test_environment_generation_is_reproducible() -> None:
    bundle = load_tranche_c_configuration(DEFAULT_TRANCHE_C_CONFIG_PATH)
    first = generate_environment_inputs(bundle)
    second = generate_environment_inputs(bundle)
    assert np.array_equal(first.price_paths["ETH"], second.price_paths["ETH"])
    assert np.array_equal(first.price_paths["BTC"], second.price_paths["BTC"])
    assert np.array_equal(first.gas_cost_path, second.gas_cost_path)
    assert first.provenance["market"]["withheld_period_policy"] == "exclude_ftx"
    assert first.provenance["gas"]["gas_process_mode"] == "empirical_components"
    assert first.provenance["gas"]["eth_price_source"] == (
        "reconstructed_simulated_eth_price_path"
    )
    assert np.array_equal(
        first.gas.sampled_rows["runtime_eth_price_usd"].to_numpy(dtype=float),
        first.price_paths["ETH"],
    )


def test_simulation_accepts_optional_gas_cost_path_without_changing_default() -> None:
    config = replace(create_base_simulation_config(), n_steps=5)
    price_path = generate_gbm_price_path(
        PriceProcessConfig(
            n_steps=config.n_steps,
            initial_price=config.initial_eth_price,
            random_seed=config.random_seed,
        )
    )
    legacy = run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=LiquidationConfig(gas_cost=100.0),
    )
    explicit = run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=LiquidationConfig(gas_cost=100.0),
        gas_cost_path=np.full(config.n_steps, 100.0),
    )
    pd.testing.assert_frame_equal(legacy, explicit)
    with pytest.raises(ValueError, match="gas_cost_path length"):
        run_simulation_with_price_path(
            config=config,
            price_path=price_path,
            liquidation_config=LiquidationConfig(),
            gas_cost_path=[1.0, 2.0],
        )
