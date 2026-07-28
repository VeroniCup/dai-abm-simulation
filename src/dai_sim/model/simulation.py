"""
simulation.py

Base simulation engine for the simplified collateral-backed DAI model.

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

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Optional

import pandas as pd

import numpy as np

from .confidence import (
    ConfidenceConfig,
    get_confidence_state,
)

from .market import (
    DAIMarketConfig,
    update_dai_price,
)

from .collateral import (
    CollateralPortfolioConfig,
    create_eth_only_portfolio,
    normalise_collateral_prices,
)

from .collateral_prices import (
    PricePathInput,
    PriceProcessConfig,
    generate_constant_price_path,
    generate_gbm_price_path,
    generate_shock_price_path,
    generate_shock_recovery_price_path,
    normalise_collateral_price_paths,
)

from .vault import (
    Vault,
    generate_portfolio_vaults,
    vaults_to_dataframe,
)

from .liquidation import (
    LiquidationConfig,
    liquidate_vaults,
    summarise_liquidations,
)

if TYPE_CHECKING:
    from dai_sim.inputs.liquidations import LiquidationDemandProcess


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
    collateral_portfolio:
        Portfolio used to assign one collateral type to each initial vault.
        ``None`` preserves the legacy ETH-only configuration.
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
    collateral_portfolio: CollateralPortfolioConfig | None = None

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
        if (
            self.collateral_portfolio is not None
            and not isinstance(
                self.collateral_portfolio,
                CollateralPortfolioConfig,
            )
        ):
            raise TypeError(
                "collateral_portfolio must be a CollateralPortfolioConfig or None."
            )


def get_collateral_portfolio(
    config: SimulationConfig,
) -> CollateralPortfolioConfig:
    """Return the configured portfolio or the default ETH-only portfolio."""
    if config.collateral_portfolio is None:
        return create_eth_only_portfolio()
    return config.collateral_portfolio


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

    portfolio = get_collateral_portfolio(config)
    initial_prices = portfolio.initial_prices

    # Preserve the existing SimulationConfig ETH price as the source for ETH
    # vault initialisation. Other collateral prices come from the portfolio.
    if "ETH" in initial_prices:
        initial_prices["ETH"] = config.initial_eth_price

    return generate_portfolio_vaults(
        n_vaults=config.n_vaults,
        prices=initial_prices,
        portfolio=portfolio,
        liquidation_ratio=config.liquidation_ratio,
        debt_mean=config.debt_mean,
        debt_std=config.debt_std,
        collateral_ratio_mean=config.collateral_ratio_mean,
        collateral_ratio_std=config.collateral_ratio_std,
        random_seed=config.random_seed,
    )


def summarise_vault_system(
    vaults: list[Vault],
    prices: float | dict[str, float],
    step: int,
) -> dict:
    """
    Summarise vault system state at one time step.

    Parameters
    ----------
    vaults:
        List of Vault objects.
    prices:
        Scalar ETH price or collateral price map.
    step:
        Current simulation step.

    Returns
    -------
    dict
        System-level summary.
    """
    price_map = normalise_collateral_prices(prices)
    vault_df = vaults_to_dataframe(vaults, prices=price_map)

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
        "eth_price": price_map["ETH"],
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


def summarise_vaults_by_collateral(
    vaults: list[Vault],
    prices: float | dict[str, float],
    step: int,
    collateral_types: tuple[str, ...] | None = None,
    realised_bad_debt: dict[str, float] | None = None,
    liquidation_results: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return long-format post-action metrics by collateral type."""
    price_map = normalise_collateral_prices(prices)
    vault_df = vaults_to_dataframe(vaults, prices=price_map)

    if collateral_types is None:
        collateral_types = tuple(
            dict.fromkeys(vault_df["collateral_type"].astype(str))
        )

    if realised_bad_debt is None:
        realised_bad_debt = {}

    records = []

    for collateral_type in collateral_types:
        collateral_df = vault_df.loc[
            vault_df["collateral_type"] == collateral_type
        ]
        active_df = collateral_df.loc[collateral_df["is_active"]]
        realised_bad_debt_value = float(
            realised_bad_debt.get(collateral_type, 0.0)
        )
        debt_repaid = 0.0
        successful_liquidations = 0
        unprofitable_attempts = 0
        keeper_profit = 0.0

        if liquidation_results is not None and not liquidation_results.empty:
            collateral_liquidations = liquidation_results.loc[
                liquidation_results["collateral_type"] == collateral_type
            ]
            successful_rows = collateral_liquidations.loc[
                collateral_liquidations["liquidated"]
            ]
            realised_bad_debt_value = float(
                successful_rows["bad_debt"].sum()
            )
            debt_repaid = float(
                collateral_liquidations["debt_repaid"].sum()
            )
            successful_liquidations = int(
                collateral_liquidations["liquidated"].sum()
            )
            unprofitable_attempts = int(
                (
                    collateral_liquidations["reason"] == "unprofitable"
                ).sum()
            )
            keeper_profit = float(
                collateral_liquidations["realised_keeper_profit"].sum()
            )

        records.append(
            {
                "step": step,
                "collateral_type": collateral_type,
                "active_vaults": int(len(active_df)),
                "active_debt": float(active_df["debt_dai"].sum()),
                "collateral_value": float(
                    active_df["collateral_value"].sum()
                ),
                "liquidatable_vaults": int(
                    active_df["is_liquidatable"].sum()
                ),
                "realised_bad_debt": realised_bad_debt_value,
                "debt_repaid": debt_repaid,
                "successful_liquidations": successful_liquidations,
                "unprofitable_attempts": unprofitable_attempts,
                "keeper_profit": keeper_profit,
            }
        )

    return pd.DataFrame(records)


def _run_simulation_with_price_path(
    config: SimulationConfig,
    price_path: PricePathInput,
    liquidation_config: LiquidationConfig,
    confidence_config: ConfidenceConfig | None = None,
    dai_market_config: DAIMarketConfig | None = None,
    initial_dai_price: float = 1.0,
    execute_liquidations: bool = True,
    initial_vaults: list[Vault] | None = None,
    gas_cost_path: Sequence[float] | None = None,
    liquidation_demand_process: LiquidationDemandProcess | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run the simulation and return system and collateral-level results.

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
        Legacy ETH price path or a mapping of collateral types to aligned paths.
        All inputs are converted to the canonical collateral price-path
        representation before the simulation loop starts.
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
    tuple[pd.DataFrame, pd.DataFrame]
        System-level and long-format collateral-level results.
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
    if gas_cost_path is not None:
        if len(gas_cost_path) != config.n_steps:
            raise ValueError("gas_cost_path length must match config.n_steps.")
        gas_cost_values = np.asarray(gas_cost_path, dtype=float)
        if not np.isfinite(gas_cost_values).all() or (gas_cost_values < 0).any():
            raise ValueError("gas_cost_path must contain finite non-negative values.")
    else:
        gas_cost_values = None
    empirical_liquidation_demand = (
        liquidation_demand_process is not None
        and liquidation_demand_process.config.mode != "legacy_all_eligible"
    )

    collateral_price_paths = normalise_collateral_price_paths(
        price_paths=price_path,
        delay_steps=config.oracle_delay_steps,
    )

    portfolio = get_collateral_portfolio(config)
    missing_price_paths = (
        set(portfolio.collateral_names)
        - set(collateral_price_paths.market_prices)
    )
    if missing_price_paths:
        raise ValueError(
            "Missing price paths for portfolio collateral types: "
            f"{sorted(missing_price_paths)}."
        )

    if "ETH" not in collateral_price_paths.market_prices:
        raise ValueError(
            "ETH price path is required to preserve the existing system-level "
            "ETH price columns."
        )

    rng = np.random.default_rng(config.random_seed)

    vaults = (
        create_initial_vaults(config)
        if initial_vaults is None
        else list(initial_vaults)
    )

    records = []
    collateral_records = []

    dai_price = initial_dai_price

    cumulative_keeper_profit = 0.0
    cumulative_debt_repaid = 0.0
    cumulative_collateral_liquidated = 0.0
    cumulative_bad_debt_realised = 0.0
    cumulative_unprofitable_attempts = 0
    cumulative_capacity_limited_attempts = 0

    for step_index, (step, market_prices, oracle_prices) in enumerate(
        collateral_price_paths.iter_price_maps()
    ):
        step_liquidation_config = (
            liquidation_config
            if gas_cost_values is None
            else replace(liquidation_config, gas_cost=float(gas_cost_values[step_index]))
        )
        # These scalar values are retained for the legacy ETH-only output schema.
        eth_price = market_prices["ETH"]
        oracle_eth_price = oracle_prices["ETH"]

        # State before keeper action using collateral-specific oracle prices.
        # This is what the protocol sees.
        pre_summary = summarise_vault_system(
            vaults=vaults,
            prices=oracle_prices,
            step=step,
        )

        # State before keeper action using collateral-specific market prices.
        # This captures hidden economic stress when the oracle is delayed.
        market_pre_summary = summarise_vault_system(
            vaults=vaults,
            prices=market_prices,
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
        liquidation_df: pd.DataFrame | None = None
        liquidation_demand_decision = None

        if execute_liquidations and pre_summary["n_liquidatable"] > 0:
            if empirical_liquidation_demand:
                liquidation_demand_decision = liquidation_demand_process.sample_step(
                    step=step,
                    liquidatable_inventory=int(pre_summary["n_liquidatable"]),
                    keeper_capacity=step_liquidation_config.max_liquidations_per_step,
                )
                liquidation_df = liquidate_vaults(
                    vaults=vaults,
                    prices=oracle_prices,
                    config=step_liquidation_config,
                    portfolio=portfolio,
                    bounded_demand=liquidation_demand_decision.bounded_demand,
                    attempt_budget=liquidation_demand_decision.attempt_budget,
                )
            else:
                liquidation_df = liquidate_vaults(
                    vaults=vaults,
                    prices=oracle_prices,
                    config=step_liquidation_config,
                    portfolio=portfolio,
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

        # State after keeper action using collateral-specific oracle prices.
        post_summary = summarise_vault_system(
            vaults=vaults,
            prices=oracle_prices,
            step=step,
        )

        # State after keeper action using collateral-specific market prices.
        market_post_summary = summarise_vault_system(
            vaults=vaults,
            prices=market_prices,
            step=step,
        )

        collateral_step = summarise_vaults_by_collateral(
            vaults=vaults,
            prices=market_prices,
            step=step,
            collateral_types=portfolio.collateral_names,
            liquidation_results=liquidation_df,
        )
        collateral_records.extend(
            collateral_step.to_dict(orient="records")
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
        if empirical_liquidation_demand:
            if liquidation_demand_decision is None:
                liquidation_demand_decision = liquidation_demand_process.sample_step(
                    step=step,
                    liquidatable_inventory=int(pre_summary["n_liquidatable"]),
                    keeper_capacity=step_liquidation_config.max_liquidations_per_step,
                )
            record.update(
                {
                    "liquidation_demand_mode": liquidation_demand_process.config.mode,
                    "sampled_liquidation_demand": liquidation_demand_decision.sampled_demand,
                    "bounded_liquidation_demand": liquidation_demand_decision.bounded_demand,
                    "liquidation_attempt_budget": liquidation_demand_decision.attempt_budget,
                    "liquidation_demand_activity": liquidation_demand_decision.activity_draw,
                    "liquidation_demand_truncated_by_inventory": (
                        liquidation_demand_decision.demand_truncated_by_inventory
                    ),
                    "liquidation_demand_truncated_by_capacity": (
                        liquidation_demand_decision.demand_truncated_by_capacity
                    ),
                    "liquidation_unresolved_inventory_after_step": int(
                        market_post_summary["n_liquidatable"]
                    ),
                }
            )

        records.append(record)

    return pd.DataFrame(records), pd.DataFrame(collateral_records)


def run_simulation_with_price_path(
    config: SimulationConfig,
    price_path: PricePathInput,
    liquidation_config: LiquidationConfig,
    confidence_config: ConfidenceConfig | None = None,
    dai_market_config: DAIMarketConfig | None = None,
    initial_dai_price: float = 1.0,
    execute_liquidations: bool = True,
    initial_vaults: list[Vault] | None = None,
    gas_cost_path: Sequence[float] | None = None,
    liquidation_demand_process: LiquidationDemandProcess | None = None,
) -> pd.DataFrame:
    """Run a simulation and return the existing system-level DataFrame."""
    system_results, _ = _run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=liquidation_config,
        confidence_config=confidence_config,
        dai_market_config=dai_market_config,
        initial_dai_price=initial_dai_price,
        execute_liquidations=execute_liquidations,
        initial_vaults=initial_vaults,
        gas_cost_path=gas_cost_path,
        liquidation_demand_process=liquidation_demand_process,
    )
    return system_results


def run_simulation_with_collateral_metrics(
    config: SimulationConfig,
    price_path: PricePathInput,
    liquidation_config: LiquidationConfig,
    confidence_config: ConfidenceConfig | None = None,
    dai_market_config: DAIMarketConfig | None = None,
    initial_dai_price: float = 1.0,
    execute_liquidations: bool = True,
    initial_vaults: list[Vault] | None = None,
    gas_cost_path: Sequence[float] | None = None,
    liquidation_demand_process: LiquidationDemandProcess | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run a simulation and return system and collateral-level DataFrames."""
    return _run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=liquidation_config,
        confidence_config=confidence_config,
        dai_market_config=dai_market_config,
        initial_dai_price=initial_dai_price,
        execute_liquidations=execute_liquidations,
        initial_vaults=initial_vaults,
        gas_cost_path=gas_cost_path,
        liquidation_demand_process=liquidation_demand_process,
    )


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
    # Quick smoke test: PYTHONPATH=src python -m dai_sim.model.simulation

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
