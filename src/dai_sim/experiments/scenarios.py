"""Scenario definitions and configuration factories for simulation experiments."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from dai_sim.model.collateral import (
    CollateralPortfolioConfig,
    create_balanced_portfolio,
    create_btc_concentrated_portfolio,
    create_crypto_diversified_portfolio,
    create_eth_only_portfolio,
    create_stable_heavy_portfolio,
)
from dai_sim.model.collateral_prices import (
    PriceProcessConfig,
    generate_shock_price_path,
)
from dai_sim.model.confidence import ConfidenceConfig
from dai_sim.model.liquidation import LiquidationConfig
from dai_sim.model.market import DAIMarketConfig
from dai_sim.model.simulation import SimulationConfig


def create_base_simulation_config(
    oracle_delay_steps: int = 0,
) -> SimulationConfig:
    """
    Create the baseline simulation configuration.

    Returns
    -------
    SimulationConfig
        Baseline simulation configuration.
    """
    return SimulationConfig(
        n_steps=100,
        n_vaults=100,
        initial_eth_price=2_000.0,
        liquidation_ratio=1.5,
        oracle_delay_steps=oracle_delay_steps,
        debt_mean=5_000.0,
        debt_std=1_000.0,
        collateral_ratio_mean=2.0,
        collateral_ratio_std=0.25,
        random_seed=42,
    )

def create_base_confidence_config() -> ConfidenceConfig:
    """
    Create the baseline confidence configuration.

    Returns
    -------
    ConfidenceConfig
        Baseline confidence configuration.
    """
    return ConfidenceConfig(
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

def create_base_dai_market_config() -> DAIMarketConfig:
    """
    Create the baseline DAI market configuration.

    Returns
    -------
    DAIMarketConfig
        Baseline DAI market configuration.
    """
    return DAIMarketConfig(
        peg_price=1.0,
        price_adjustment_speed=0.02,
        arbitrage_strength=1.0,
        above_peg_supply_strength=1.0,
        panic_strength=0.5,
        noise_std=0.0005,
        min_price=0.50,
        max_price=1.50,
    )

def create_recovery_dai_market_config() -> DAIMarketConfig:
    """
    Create DAI market config with peg-recovery feedback enabled.
    """
    return DAIMarketConfig(
        peg_price=1.0,
        price_adjustment_speed=0.02,
        arbitrage_strength=1.0,
        above_peg_supply_strength=1.0,
        panic_strength=0.5,
        noise_std=0.0005,
        min_price=0.50,
        max_price=1.50,
        enable_peg_recovery=True,
        arbitrage_recovery_strength=2.0,
        policy_feedback_strength=1.5,
        bad_debt_recovery_drag=5.0,
        min_recovery_confidence=0.1,
    )

def create_scenario_configs() -> dict:
    """
    Create scenario-specific configurations.

    Returns
    -------
    dict
        Dictionary of scenario names and configuration dictionaries.
    """
    base_confidence = create_base_confidence_config()
    base_market = create_base_dai_market_config()

    scenarios = {
        "low_gas": {
            "liquidation_config": LiquidationConfig(
                liquidation_penalty=0.13,
                gas_cost=50.0,
                risk_cost_rate=0.00,
                max_close_factor=0.5,
                max_liquidations_per_step=20,
            ),
            "confidence_config": base_confidence,
            "dai_market_config": base_market,
        },
        "medium_gas": {
            "liquidation_config": LiquidationConfig(
                liquidation_penalty=0.13,
                gas_cost=150.0,
                risk_cost_rate=0.00,
                max_close_factor=0.5,
                max_liquidations_per_step=10,
            ),
            "confidence_config": base_confidence,
            "dai_market_config": base_market,
        },
        "high_gas": {
            "liquidation_config": LiquidationConfig(
                liquidation_penalty=0.13,
                gas_cost=250.0,
                risk_cost_rate=0.00,
                max_close_factor=0.5,
                max_liquidations_per_step=5,
            ),
            "confidence_config": base_confidence,
            "dai_market_config": base_market,
        },
        "extreme_panic": {
            "liquidation_config": LiquidationConfig(
                liquidation_penalty=0.13,
                gas_cost=700.0,
                risk_cost_rate=0.02,
                max_close_factor=0.3,
                max_liquidations_per_step=2,
            ),
            "confidence_config": ConfidenceConfig(
                normal_lower_price=0.99,
                normal_upper_price=1.01,
                stress_lower_price=0.97,
                max_normal_liquidatable_share=0.05,
                max_stress_liquidatable_share=0.20,
                bad_debt_panic_threshold=500.0,
                normal_confidence=1.0,
                stress_confidence=0.4,
                panic_confidence=0.05,
                panic_selling_multiplier=3.0,
            ),
            "dai_market_config": DAIMarketConfig(
                peg_price=1.0,
                price_adjustment_speed=0.02,
                arbitrage_strength=0.7,
                above_peg_supply_strength=1.0,
                panic_strength=1.0,
                noise_std=0.0005,
                min_price=0.50,
                max_price=1.50,
            ),
        },
    }

    return scenarios

def create_confidence_sensitivity_configs() -> dict:
    """
    Create confidence and market configurations for sensitivity analysis.

    The scenarios are ordered from resilient to extreme confidence breakdown.
    Moving down the ladder:
    - the market becomes less tolerant of peg deviation;
    - the system becomes more sensitive to liquidation pressure and bad debt;
    - stress/panic confidence falls;
    - panic selling pressure increases;
    - arbitrage demand weakens.
    """
    return {
        "resilient_confidence": {
            "confidence_config": ConfidenceConfig(
                normal_lower_price=0.990,
                normal_upper_price=1.010,
                stress_lower_price=0.960,
                max_normal_liquidatable_share=0.10,
                max_stress_liquidatable_share=0.40,
                bad_debt_panic_threshold=3000.0,
                normal_confidence=1.0,
                stress_confidence=0.75,
                panic_confidence=0.35,
                panic_selling_multiplier=1.0,
            ),
            "dai_market_config": DAIMarketConfig(
                peg_price=1.0,
                price_adjustment_speed=0.02,
                arbitrage_strength=1.30,
                above_peg_supply_strength=1.0,
                panic_strength=0.25,
                noise_std=0.0005,
                min_price=0.50,
                max_price=1.50,
            ),
        },

        "baseline_confidence": {
            "confidence_config": ConfidenceConfig(
                normal_lower_price=0.990,
                normal_upper_price=1.010,
                stress_lower_price=0.970,
                max_normal_liquidatable_share=0.05,
                max_stress_liquidatable_share=0.30,
                bad_debt_panic_threshold=1000.0,
                normal_confidence=1.0,
                stress_confidence=0.50,
                panic_confidence=0.10,
                panic_selling_multiplier=2.0,
            ),
            "dai_market_config": DAIMarketConfig(
                peg_price=1.0,
                price_adjustment_speed=0.02,
                arbitrage_strength=1.00,
                above_peg_supply_strength=1.0,
                panic_strength=0.50,
                noise_std=0.0005,
                min_price=0.50,
                max_price=1.50,
            ),
        },

        "fragile_confidence": {
            "confidence_config": ConfidenceConfig(
                normal_lower_price=0.995,
                normal_upper_price=1.005,
                stress_lower_price=0.980,
                max_normal_liquidatable_share=0.04,
                max_stress_liquidatable_share=0.22,
                bad_debt_panic_threshold=750.0,
                normal_confidence=1.0,
                stress_confidence=0.40,
                panic_confidence=0.08,
                panic_selling_multiplier=2.4,
            ),
            "dai_market_config": DAIMarketConfig(
                peg_price=1.0,
                price_adjustment_speed=0.02,
                arbitrage_strength=0.80,
                above_peg_supply_strength=1.0,
                panic_strength=0.70,
                noise_std=0.0005,
                min_price=0.50,
                max_price=1.50,
            ),
        },

        "panic_sensitive": {
            "confidence_config": ConfidenceConfig(
                normal_lower_price=0.997,
                normal_upper_price=1.003,
                stress_lower_price=0.985,
                max_normal_liquidatable_share=0.03,
                max_stress_liquidatable_share=0.16,
                bad_debt_panic_threshold=500.0,
                normal_confidence=1.0,
                stress_confidence=0.30,
                panic_confidence=0.06,
                panic_selling_multiplier=2.9,
            ),
            "dai_market_config": DAIMarketConfig(
                peg_price=1.0,
                price_adjustment_speed=0.02,
                arbitrage_strength=0.60,
                above_peg_supply_strength=1.0,
                panic_strength=0.90,
                noise_std=0.0005,
                min_price=0.50,
                max_price=1.50,
            ),
        },

        "extreme_confidence_breakdown": {
            "confidence_config": ConfidenceConfig(
                normal_lower_price=0.998,
                normal_upper_price=1.002,
                stress_lower_price=0.990,
                max_normal_liquidatable_share=0.02,
                max_stress_liquidatable_share=0.10,
                bad_debt_panic_threshold=250.0,
                normal_confidence=1.0,
                stress_confidence=0.20,
                panic_confidence=0.04,
                panic_selling_multiplier=3.5,
            ),
            "dai_market_config": DAIMarketConfig(
                peg_price=1.0,
                price_adjustment_speed=0.02,
                arbitrage_strength=0.40,
                above_peg_supply_strength=1.0,
                panic_strength=1.10,
                noise_std=0.0005,
                min_price=0.50,
                max_price=1.50,
            ),
        },
    }

@dataclass(frozen=True)
class MultiCollateralShockScenario:
    """Deterministic collateral shocks applied from one simulation step."""

    name: str
    shock_sizes: Mapping[str, float]

    def __post_init__(self) -> None:
        scenario_name = self.name.strip()
        if not scenario_name:
            raise ValueError("Shock scenario name must not be empty.")

        normalised_shocks: dict[str, float] = {}
        for collateral_type, shock_size in self.shock_sizes.items():
            normalised_type = str(collateral_type).strip().upper()
            if not normalised_type:
                raise ValueError("Shock collateral types must not be empty.")
            if normalised_type in normalised_shocks:
                raise ValueError(
                    f"Duplicate shock for collateral type '{normalised_type}'."
                )

            numeric_shock = float(shock_size)
            if not -1.0 < numeric_shock < 0.0:
                raise ValueError(
                    "Collateral shock sizes must lie strictly between -1 and 0."
                )
            normalised_shocks[normalised_type] = numeric_shock

        if not normalised_shocks:
            raise ValueError("At least one collateral shock is required.")

        object.__setattr__(self, "name", scenario_name)
        object.__setattr__(self, "shock_sizes", normalised_shocks)

def create_multicollateral_portfolios(
) -> dict[str, CollateralPortfolioConfig]:
    """Return the five agreed Experiment 06 portfolios."""
    portfolios = (
        create_eth_only_portfolio(),
        create_crypto_diversified_portfolio(),
        create_balanced_portfolio(),
        create_stable_heavy_portfolio(),
        create_btc_concentrated_portfolio(),
    )
    return {
        portfolio.name: portfolio
        for portfolio in portfolios
    }

def create_multicollateral_shock_scenarios(
    crypto_crash_size: float = -0.43,
    stable_depeg_size: float = -0.20,
) -> dict[str, MultiCollateralShockScenario]:
    """
    Return the configurable deterministic Experiment 06 shock scenarios.

    The defaults are stylised stress magnitudes rather than empirical
    calibrations. The crypto magnitude matches the existing baseline ETH shock.
    """
    scenarios = (
        MultiCollateralShockScenario(
            name="eth_specific_crash",
            shock_sizes={"ETH": crypto_crash_size},
        ),
        MultiCollateralShockScenario(
            name="btc_specific_crash",
            shock_sizes={"BTC": crypto_crash_size},
        ),
        MultiCollateralShockScenario(
            name="correlated_crypto_crash",
            shock_sizes={
                "ETH": crypto_crash_size,
                "BTC": crypto_crash_size,
            },
        ),
        MultiCollateralShockScenario(
            name="stable_depeg",
            shock_sizes={"STABLE": stable_depeg_size},
        ),
        MultiCollateralShockScenario(
            name="systemic_shock",
            shock_sizes={
                "ETH": crypto_crash_size,
                "BTC": crypto_crash_size,
                "STABLE": stable_depeg_size,
            },
        ),
    )
    return {
        scenario.name: scenario
        for scenario in scenarios
    }

def build_multicollateral_price_paths(
    portfolio: CollateralPortfolioConfig,
    shock_scenario: MultiCollateralShockScenario,
    n_steps: int,
    shock_time: int,
    random_seed: int | None = 42,
) -> dict[str, np.ndarray]:
    """Build portfolio price paths with the existing deterministic generator."""
    price_paths: dict[str, np.ndarray] = {}

    for collateral in portfolio.collaterals:
        price_config = PriceProcessConfig(
            n_steps=n_steps,
            initial_price=collateral.initial_price,
            random_seed=random_seed,
        )
        shock_size = shock_scenario.shock_sizes.get(collateral.name, 0.0)
        generated_path = generate_shock_price_path(
            config=price_config,
            shock_time=shock_time,
            shock_size=shock_size,
        )
        price_paths[collateral.name] = generated_path["eth_price"].to_numpy()

    return price_paths
