"""
simulation.py

Base simulation engine for the simplified ETH-backed DAI model.

Version 2:
- ETH price paths;
- synthetic vault population;
- vault collateral ratios;
- liquidation eligibility;
- keeper liquidation decisions;
- gas-cost frictions;
- bad debt measurement.

Version 3:
- DAI market price dynamics;
- confidence/panic regimes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

import numpy as np

from confidence import (
    ConfidenceConfig,
    get_confidence_state,
)

from dai_market import (
    DAIMarketConfig,
    update_dai_price,
)

from price_process import (
    PriceProcessConfig,
    add_oracle_price,
    generate_constant_price_path,
    generate_gbm_price_path,
    generate_shock_price_path,
    generate_shock_recovery_price_path,
)

from vault import (
    Vault,
    generate_random_vaults,
    vaults_to_dataframe,
)

from liquidation import (
    LiquidationConfig,
    liquidate_vaults,
    summarise_liquidations,
)


@dataclass(frozen=True)
class SimulationConfig:
    """
    Configuration for the base simulation.

    Attributes
    ----------
    n_steps:
        Number of simulation time steps.
    n_vaults:
        Number of synthetic vaults.
    initial_eth_price:
        Initial ETH price in USD.
    liquidation_ratio:
        Liquidation ratio for vaults. Example: 1.5 means 150%.
    debt_mean:
        Mean initial DAI debt per vault.
    debt_std:
        Standard deviation of initial DAI debt.
    collateral_ratio_mean:
        Mean initial collateral ratio.
    collateral_ratio_std:
        Standard deviation of initial collateral ratio.
    random_seed:
        Random seed for reproducibility.
    """

    n_steps: int = 200
    n_vaults: int = 100
    initial_eth_price: float = 2_000.0
    liquidation_ratio: float = 1.5
    oracle_delay_steps: int = 0

    debt_mean: float = 5_000.0
    debt_std: float = 1_000.0
    collateral_ratio_mean: float = 2.0
    collateral_ratio_std: float = 0.25

    random_seed: Optional[int] = 42

    def validate(self) -> None:
        """Validate basic simulation inputs."""
        if self.n_steps <= 0:
            raise ValueError("n_steps must be positive.")
        if self.n_vaults <= 0:
            raise ValueError("n_vaults must be positive.")
        if self.initial_eth_price <= 0:
            raise ValueError("initial_eth_price must be positive.")
        if self.liquidation_ratio <= 1:
            raise ValueError("liquidation_ratio must be greater than 1.")
        if self.debt_mean <= 0:
            raise ValueError("debt_mean must be positive.")
        if self.debt_std < 0:
            raise ValueError("debt_std cannot be negative.")
        if self.collateral_ratio_mean <= self.liquidation_ratio:
            raise ValueError(
                "collateral_ratio_mean should be greater than liquidation_ratio."
            )
        if self.collateral_ratio_std < 0:
            raise ValueError("collateral_ratio_std cannot be negative.")
        if self.oracle_delay_steps < 0:
            raise ValueError("oracle_delay_steps cannot be negative.")


def create_initial_vaults(config: SimulationConfig) -> list[Vault]:
    """
    Create the initial synthetic vault population.

    Parameters
    ----------
    config:
        SimulationConfig object.

    Returns
    -------
    list[Vault]
        Initial vault population.
    """
    config.validate()

    return generate_random_vaults(
        n_vaults=config.n_vaults,
        eth_price=config.initial_eth_price,
        liquidation_ratio=config.liquidation_ratio,
        debt_mean=config.debt_mean,
        debt_std=config.debt_std,
        collateral_ratio_mean=config.collateral_ratio_mean,
        collateral_ratio_std=config.collateral_ratio_std,
        random_seed=config.random_seed,
    )


def summarise_vault_system(
    vaults: list[Vault],
    eth_price: float,
    step: int,
) -> dict:
    """
    Summarise vault system state at one time step.

    Parameters
    ----------
    vaults:
        List of Vault objects.
    eth_price:
        Current ETH price.
    step:
        Current simulation step.

    Returns
    -------
    dict
        System-level summary.
    """
    vault_df = vaults_to_dataframe(vaults, eth_price=eth_price)

    active_df = vault_df[vault_df["is_active"]].copy()

    total_debt = active_df["debt_dai"].sum()
    total_collateral_value = active_df["collateral_value"].sum()
    total_bad_debt = active_df["bad_debt"].sum()

    n_active_vaults = len(active_df)
    n_liquidated_vaults = int(vault_df["is_liquidated"].sum())

    if n_active_vaults > 0:
        n_liquidatable = int(active_df["is_liquidatable"].sum())
        share_liquidatable = n_liquidatable / n_active_vaults
    else:
        n_liquidatable = 0
        share_liquidatable = 0.0

    if total_debt > 0:
        system_collateral_ratio = total_collateral_value / total_debt
    else:
        system_collateral_ratio = float("inf")

    return {
        "step": step,
        "eth_price": eth_price,
        "n_vaults_total": len(vault_df),
        "n_vaults_active": n_active_vaults,
        "n_vaults_liquidated_cumulative": n_liquidated_vaults,
        "total_debt_active": total_debt,
        "total_collateral_value_active": total_collateral_value,
        "system_collateral_ratio": system_collateral_ratio,
        "n_liquidatable": n_liquidatable,
        "share_liquidatable": share_liquidatable,
        "total_bad_debt_active": total_bad_debt,
    }


def run_simulation_with_price_path(
    config: SimulationConfig,
    price_path: pd.DataFrame,
    liquidation_config: LiquidationConfig,
    confidence_config: ConfidenceConfig | None = None,
    dai_market_config: DAIMarketConfig | None = None,
    initial_dai_price: float = 1.0,
    execute_liquidations: bool = True,
) -> pd.DataFrame:
    """
    Run the simulation using a provided ETH price path.

    This version includes:
    - vault dynamics;
    - keeper liquidations;
    - confidence regime;
    - DAI market price updates.

    Parameters
    ----------
    config:
        SimulationConfig object.
    price_path:
        DataFrame containing columns 'step' and 'eth_price'.
    liquidation_config:
        LiquidationConfig object.
    confidence_config:
        ConfidenceConfig object. If None, default config is used.
    dai_market_config:
        DAIMarketConfig object. If None, default config is used.
    initial_dai_price:
        Initial DAI market price.
    execute_liquidations:
        Whether keepers should actually execute profitable liquidations.

    Returns
    -------
    pd.DataFrame
        System-level simulation results by time step.
    """
    config.validate()
    liquidation_config.validate()

    if confidence_config is None:
        confidence_config = ConfidenceConfig()
    if dai_market_config is None:
        dai_market_config = DAIMarketConfig()

    confidence_config.validate()
    dai_market_config.validate()

    if initial_dai_price <= 0:
        raise ValueError("initial_dai_price must be positive.")

    required_cols = {"step", "eth_price"}
    missing_cols = required_cols - set(price_path.columns)
    if missing_cols:
        raise ValueError(f"price_path is missing columns: {missing_cols}")

    price_path = add_oracle_price(
        price_path=price_path,
        delay_steps=config.oracle_delay_steps,
        price_col="eth_price",
        oracle_col="oracle_eth_price",
    )

    rng = np.random.default_rng(config.random_seed)

    vaults = create_initial_vaults(config)

    records = []

    dai_price = initial_dai_price

    cumulative_keeper_profit = 0.0
    cumulative_debt_repaid = 0.0
    cumulative_collateral_liquidated = 0.0
    cumulative_bad_debt_realised = 0.0
    cumulative_unprofitable_attempts = 0
    cumulative_capacity_limited_attempts = 0

    for _, row in price_path.iterrows():
        step = int(row["step"])
        eth_price = float(row["eth_price"])
        oracle_eth_price = float(row["oracle_eth_price"])

        # State before keeper action using oracle price.
        # This is what the protocol sees.
        pre_summary = summarise_vault_system(
            vaults=vaults,
            eth_price=oracle_eth_price,
            step=step,
        )

        # State before keeper action using true market price.
        # This captures hidden economic stress when the oracle is delayed.
        market_pre_summary = summarise_vault_system(
            vaults=vaults,
            eth_price=eth_price,
            step=step,
        )

        confidence_state_before = get_confidence_state(
            dai_price=dai_price,
            share_liquidatable=market_pre_summary["share_liquidatable"],
            active_bad_debt=market_pre_summary["total_bad_debt_active"],
            config=confidence_config,
        )

        # Update DAI market price using confidence state
        # Additional system-level selling pressure from liquidation stress.
        # This links vault-system stress directly to DAI market confidence.
        if market_pre_summary["total_debt_active"] > 0:
            bad_debt_ratio = (
                    market_pre_summary["total_bad_debt_active"]
                    / market_pre_summary["total_debt_active"]
            )
        else:
            bad_debt_ratio = 0.0

        systemic_stress_pressure = (
                0.005 * market_pre_summary["share_liquidatable"]
                + 0.5 * bad_debt_ratio
        )

        combined_panic_pressure = (
                confidence_state_before["panic_selling_pressure"]
                + systemic_stress_pressure
        )

        new_dai_price, dai_pressures = update_dai_price(
            dai_price=dai_price,
            confidence=confidence_state_before["confidence"],
            panic_selling_pressure=combined_panic_pressure,
            market_config=dai_market_config,
            rng=rng,
            active_bad_debt=market_pre_summary["total_bad_debt_active"],
            total_debt_active=market_pre_summary["total_debt_active"],
        )

        dai_price_before = dai_price
        dai_price = new_dai_price

        liquidation_summary = {
            "n_attempted": 0,
            "n_liquidated": 0,
            "n_fully_liquidated": 0,
            "n_unprofitable": 0,
            "n_capacity_limited": 0,
            "keeper_profit": 0.0,
            "bad_debt_realised": 0.0,
            "debt_repaid": 0.0,
            "collateral_liquidated": 0.0,
        }

        if execute_liquidations and pre_summary["n_liquidatable"] > 0:
            liquidation_df = liquidate_vaults(
                vaults=vaults,
                eth_price=oracle_eth_price,
                config=liquidation_config,
            )
            liquidation_summary = summarise_liquidations(liquidation_df)

            cumulative_keeper_profit += float(liquidation_summary["keeper_profit"])
            cumulative_debt_repaid += float(liquidation_summary["debt_repaid"])
            cumulative_collateral_liquidated += float(
                liquidation_summary["collateral_liquidated"]
            )
            cumulative_bad_debt_realised += float(
                liquidation_summary["bad_debt_realised"]
            )
            cumulative_unprofitable_attempts += int(
                liquidation_summary["n_unprofitable"]
            )
            cumulative_capacity_limited_attempts += int(
                liquidation_summary["n_capacity_limited"]
            )

        # State after keeper action using oracle price.
        post_summary = summarise_vault_system(
            vaults=vaults,
            eth_price=oracle_eth_price,
            step=step,
        )

        # State after keeper action using true market price.
        market_post_summary = summarise_vault_system(
            vaults=vaults,
            eth_price=eth_price,
            step=step,
        )

        confidence_state_after = get_confidence_state(
            dai_price=dai_price,
            share_liquidatable=market_post_summary["share_liquidatable"],
            active_bad_debt=market_post_summary["total_bad_debt_active"],
            config=confidence_config,
        )

        record = {
            **post_summary,
            "market_eth_price": eth_price,
            "oracle_eth_price": oracle_eth_price,
            "oracle_delay_steps": config.oracle_delay_steps,
            "oracle_system_collateral_ratio": post_summary["system_collateral_ratio"],
            "market_system_collateral_ratio": market_post_summary["system_collateral_ratio"],
            "oracle_total_bad_debt_active": post_summary["total_bad_debt_active"],
            "market_total_bad_debt_active": market_post_summary["total_bad_debt_active"],
            "oracle_share_liquidatable": post_summary["share_liquidatable"],
            "market_share_liquidatable": market_post_summary["share_liquidatable"],
            "hidden_bad_debt": max(
                market_post_summary["total_bad_debt_active"]
                - post_summary["total_bad_debt_active"],
                0.0,
            ),
            "dai_price_before": dai_price_before,
            "dai_price": dai_price,
            "dai_price_change": dai_price - dai_price_before,
            "regime_before": confidence_state_before["regime"],
            "confidence_before": confidence_state_before["confidence"],
            "panic_selling_pressure_before": confidence_state_before[
                "panic_selling_pressure"
            ],
            "regime_after": confidence_state_after["regime"],
            "confidence_after": confidence_state_after["confidence"],
            "panic_selling_pressure_after": confidence_state_after[
                "panic_selling_pressure"
            ],
            "dai_demand_pressure": dai_pressures["demand_pressure"],
            "dai_above_peg_supply_pressure": dai_pressures[
                "above_peg_supply_pressure"
            ],
            "dai_panic_pressure": dai_pressures["panic_pressure"],
            "dai_total_supply_pressure": dai_pressures["total_supply_pressure"],
            "dai_net_pressure": dai_pressures["net_pressure"],
            "dai_price_noise": dai_pressures["noise"],
            "peg_gap": dai_pressures["peg_gap"],
            "recovery_bad_debt_ratio": dai_pressures["bad_debt_ratio"],
            "recovery_discount": dai_pressures["recovery_discount"],
            "arbitrage_recovery_pressure": dai_pressures["arbitrage_recovery_pressure"],
            "policy_feedback_pressure": dai_pressures["policy_feedback_pressure"],
            "total_recovery_pressure": dai_pressures["total_recovery_pressure"],
            "n_liquidatable_before_liquidation": pre_summary["n_liquidatable"],
            "n_attempted_liquidations": int(liquidation_summary["n_attempted"]),
            "n_successful_liquidations": int(liquidation_summary["n_liquidated"]),
            "n_fully_liquidated": int(liquidation_summary["n_fully_liquidated"]),
            "n_unprofitable_liquidations": int(liquidation_summary["n_unprofitable"]),
            "n_capacity_limited_liquidations": int(
                liquidation_summary["n_capacity_limited"]
            ),
            "keeper_profit_step": float(liquidation_summary["keeper_profit"]),
            "debt_repaid_step": float(liquidation_summary["debt_repaid"]),
            "collateral_liquidated_step": float(
                liquidation_summary["collateral_liquidated"]
            ),
            "bad_debt_realised_step": float(liquidation_summary["bad_debt_realised"]),
            "keeper_profit_cumulative": cumulative_keeper_profit,
            "debt_repaid_cumulative": cumulative_debt_repaid,
            "collateral_liquidated_cumulative": cumulative_collateral_liquidated,
            "bad_debt_realised_cumulative": cumulative_bad_debt_realised,
            "unprofitable_liquidations_cumulative": cumulative_unprofitable_attempts,
            "capacity_limited_liquidations_cumulative": cumulative_capacity_limited_attempts,
            "systemic_bad_debt_ratio": bad_debt_ratio,
            "systemic_stress_pressure": systemic_stress_pressure,
            "combined_panic_pressure": combined_panic_pressure,
        }

        records.append(record)

    return pd.DataFrame(records)


def run_constant_price_simulation(
    config: SimulationConfig,
    liquidation_config: LiquidationConfig,
    confidence_config: ConfidenceConfig | None = None,
    dai_market_config: DAIMarketConfig | None = None,
    initial_dai_price: float = 1.0,
    execute_liquidations: bool = True,
) -> pd.DataFrame:
    """
    Run simulation with constant ETH price.

    Parameters
    ----------
    config:
        SimulationConfig object.
    liquidation_config:
        LiquidationConfig object.
    confidence_config:
        Optional ConfidenceConfig object. If None, default config is used.
    dai_market_config:
        Optional DAIMarketConfig object. If None, default config is used.
    initial_dai_price:
        Initial DAI market price.
    execute_liquidations:
        Whether to execute profitable keeper liquidations.
    Returns
    -------
    pd.DataFrame
        System-level simulation results.
    """
    price_config = PriceProcessConfig(
        n_steps=config.n_steps,
        initial_price=config.initial_eth_price,
        random_seed=config.random_seed,
    )
    price_path = generate_constant_price_path(price_config)

    return run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=liquidation_config,
        confidence_config=confidence_config,
        dai_market_config=dai_market_config,
        initial_dai_price=initial_dai_price,
        execute_liquidations=execute_liquidations,
    )


def run_gbm_simulation(
    config: SimulationConfig,
    liquidation_config: LiquidationConfig,
    confidence_config: ConfidenceConfig | None = None,
    dai_market_config: DAIMarketConfig | None = None,
    mu: float = 0.0,
    sigma: float = 0.80,
    dt: float = 1 / 365,
    initial_dai_price: float = 1.0,
    execute_liquidations: bool = True,
) -> pd.DataFrame:
    """
    Run simulation with GBM ETH price path.
    """
    price_config = PriceProcessConfig(
        n_steps=config.n_steps,
        initial_price=config.initial_eth_price,
        random_seed=config.random_seed,
    )
    price_path = generate_gbm_price_path(
        config=price_config,
        mu=mu,
        sigma=sigma,
        dt=dt,
    )

    return run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=liquidation_config,
        confidence_config=confidence_config,
        dai_market_config=dai_market_config,
        initial_dai_price=initial_dai_price,
        execute_liquidations=execute_liquidations,
    )


def run_shock_simulation(
    config: SimulationConfig,
    liquidation_config: LiquidationConfig,
    confidence_config: ConfidenceConfig | None = None,
    dai_market_config: DAIMarketConfig | None = None,
    shock_time: int = 50,
    shock_size: float = -0.43,
    initial_dai_price: float = 1.0,
    execute_liquidations: bool = True,
) -> pd.DataFrame:
    """
    Run simulation with a deterministic ETH price shock.

    Parameters
    ----------
    config:
        SimulationConfig object.
    liquidation_config:
        LiquidationConfig object.
    shock_time:
        Time step at which the ETH shock occurs.
    shock_size:
        Percentage ETH price shock.
        Example: -0.43 means ETH falls by 43%.
    execute_liquidations:
        Whether to execute profitable liquidations.

    Returns
    -------
    pd.DataFrame
        System-level simulation results.
    """
    price_config = PriceProcessConfig(
        n_steps=config.n_steps,
        initial_price=config.initial_eth_price,
        random_seed=config.random_seed,
    )
    price_path = generate_shock_price_path(
        config=price_config,
        shock_time=shock_time,
        shock_size=shock_size,
    )

    return run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=liquidation_config,
        confidence_config=confidence_config,
        dai_market_config=dai_market_config,
        initial_dai_price=initial_dai_price,
        execute_liquidations=execute_liquidations,
    )


def run_shock_recovery_simulation(
    config: SimulationConfig,
    liquidation_config: LiquidationConfig,
    confidence_config: ConfidenceConfig | None = None,
    dai_market_config: DAIMarketConfig | None = None,
    shock_time: int = 30,
    shock_size: float = -0.43,
    recovery_start: int = 40,
    recovery_end: int = 90,
    recovery_fraction: float = 0.5,
    initial_dai_price: float = 1.0,
    execute_liquidations: bool = True,
) -> pd.DataFrame:
    """
    Run a simulation with an ETH shock followed by gradual collateral recovery.
    """
    price_config = PriceProcessConfig(
        n_steps=config.n_steps,
        initial_price=config.initial_eth_price,
        random_seed=config.random_seed,
    )

    price_path = generate_shock_recovery_price_path(
        config=price_config,
        shock_time=shock_time,
        shock_size=shock_size,
        recovery_start=recovery_start,
        recovery_end=recovery_end,
        recovery_fraction=recovery_fraction,
    )

    results = run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=liquidation_config,
        confidence_config=confidence_config,
        dai_market_config=dai_market_config,
        initial_dai_price=initial_dai_price,
        execute_liquidations=execute_liquidations,
    )

    results["shock_size_experiment"] = shock_size
    results["recovery_start_experiment"] = recovery_start
    results["recovery_end_experiment"] = recovery_end
    results["recovery_fraction_experiment"] = recovery_fraction

    return results


if __name__ == "__main__":
    # Quick smoke test. Run:
    # python src/simulation.py

    sim_config = SimulationConfig(
        n_steps=100,
        n_vaults=100,
        initial_eth_price=2_000.0,
        liquidation_ratio=1.5,
        oracle_delay_steps=3,
        random_seed=42,
    )

    high_gas_config = LiquidationConfig(
        liquidation_penalty=0.13,
        gas_cost=250.0,
        risk_cost_rate=0.00,
        max_close_factor=0.5,
        max_liquidations_per_step=5,
    )

    confidence_config = ConfidenceConfig(
        normal_lower_price=0.99,
        normal_upper_price=1.01,
        stress_lower_price=0.97,
        max_normal_liquidatable_share=0.05,
        max_stress_liquidatable_share=0.30,
        bad_debt_panic_threshold=1_000.0,
        normal_confidence=1.0,
        stress_confidence=0.5,
        panic_confidence=0.1,
        panic_selling_multiplier=2.0,
    )

    dai_market_config = DAIMarketConfig(
        peg_price=1.0,
        price_adjustment_speed=0.02,
        arbitrage_strength=1.0,
        above_peg_supply_strength=1.0,
        panic_strength=0.5, # was 1.0
        noise_std=0.0005,
        min_price=0.50,
        max_price=1.50,
    )

    results = run_shock_simulation(
        config=sim_config,
        liquidation_config=high_gas_config,
        confidence_config=confidence_config,
        dai_market_config=dai_market_config,
        shock_time=30,
        shock_size=-0.43,
        initial_dai_price=1.0,
        execute_liquidations=True,
    )

    columns_to_show = [
        "step",
        "market_eth_price",
        "oracle_eth_price",
        "dai_price",
        "regime_before",
        "regime_after",
        "n_vaults_active",
        "n_liquidatable_before_liquidation",
        "n_successful_liquidations",
        "n_fully_liquidated",
        "n_unprofitable_liquidations",
        "n_capacity_limited_liquidations",
        "n_liquidatable",
        "oracle_total_bad_debt_active",
        "market_total_bad_debt_active",
        "hidden_bad_debt",
        "dai_net_pressure",
        "keeper_profit_cumulative",
        "bad_debt_realised_cumulative",
    ]

    print("Results around shock:")
    print(results.loc[27:40, columns_to_show])

    print("\nFinal row:")
    print(results.tail(1)[columns_to_show].T)