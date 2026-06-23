"""
experiments.py

Scenario runner for the simplified DAI stability simulation.

This module runs several stress-test scenarios and saves the results.

Scenarios:
- low_gas: efficient liquidation environment;
- medium_gas: moderate liquidation friction;
- high_gas: strong liquidation friction;
- extreme_panic: strong liquidation friction plus stronger panic feedback.

The aim is to compare how keeper incentives and confidence feedback affect:
- DAI peg deviation;
- liquidation success;
- active bad debt;
- keeper profit;
- unresolved liquidatable vaults.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from simulation import SimulationConfig, run_shock_simulation
from liquidation import LiquidationConfig
from confidence import ConfidenceConfig
from dai_market import DAIMarketConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "outputs" / "results"


def create_base_simulation_config() -> SimulationConfig:
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
                gas_cost=100.0,
                risk_cost_rate=0.00,
                max_close_factor=1.0,
                max_liquidations_per_step=20,
            ),
            "confidence_config": base_confidence,
            "dai_market_config": base_market,
        },
        "medium_gas": {
            "liquidation_config": LiquidationConfig(
                liquidation_penalty=0.13,
                gas_cost=400.0,
                risk_cost_rate=0.00,
                max_close_factor=1.0,
                max_liquidations_per_step=10,
            ),
            "confidence_config": base_confidence,
            "dai_market_config": base_market,
        },
        "high_gas": {
            "liquidation_config": LiquidationConfig(
                liquidation_penalty=0.13,
                gas_cost=700.0,
                risk_cost_rate=0.00,
                max_close_factor=1.0,
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
                max_close_factor=1.0,
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


def compute_summary_metrics(
    scenario_name: str,
    results: pd.DataFrame,
) -> dict:
    """
    Compute scenario-level summary metrics.

    Parameters
    ----------
    scenario_name:
        Name of the scenario.
    results:
        Simulation result DataFrame.

    Returns
    -------
    dict
        Summary metrics.
    """
    final = results.iloc[-1]

    peg_deviation = (results["dai_price"] - 1.0).abs()
    below_peg = results["dai_price"] < 1.0

    if below_peg.any():
        first_below_peg_step = int(results.loc[below_peg, "step"].iloc[0])
    else:
        first_below_peg_step = None

    if (results["regime_after"] == "panic").any():
        first_panic_step = int(
            results.loc[results["regime_after"] == "panic", "step"].iloc[0]
        )
    else:
        first_panic_step = None

    return {
        "scenario": scenario_name,
        "final_dai_price": float(final["dai_price"]),
        "min_dai_price": float(results["dai_price"].min()),
        "max_dai_price": float(results["dai_price"].max()),
        "max_abs_peg_deviation": float(peg_deviation.max()),
        "first_below_peg_step": first_below_peg_step,
        "first_panic_step": first_panic_step,
        "final_regime": final["regime_after"],
        "final_active_vaults": int(final["n_vaults_active"]),
        "final_liquidatable_vaults": int(final["n_liquidatable"]),
        "final_active_bad_debt": float(final["total_bad_debt_active"]),
        "cumulative_keeper_profit": float(final["keeper_profit_cumulative"]),
        "cumulative_bad_debt_realised": float(
            final["bad_debt_realised_cumulative"]
        ),
        "cumulative_debt_repaid": float(final["debt_repaid_cumulative"]),
        "cumulative_unprofitable_attempts": int(
            final["unprofitable_liquidations_cumulative"]
        ),
    }


def run_all_scenarios(
    shock_time: int = 30,
    shock_size: float = -0.43,
    initial_dai_price: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run all configured scenarios.

    Parameters
    ----------
    shock_time:
        ETH shock time.
    shock_size:
        ETH shock size. Example: -0.43 means a 43% fall.
    initial_dai_price:
        Initial DAI price.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        Combined time-series results and scenario summary results.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    sim_config = create_base_simulation_config()
    scenarios = create_scenario_configs()

    all_results = []
    summary_records = []

    for scenario_name, configs in scenarios.items():
        print(f"Running scenario: {scenario_name}")

        results = run_shock_simulation(
            config=sim_config,
            liquidation_config=configs["liquidation_config"],
            confidence_config=configs["confidence_config"],
            dai_market_config=configs["dai_market_config"],
            shock_time=shock_time,
            shock_size=shock_size,
            initial_dai_price=initial_dai_price,
            execute_liquidations=True,
        )

        results.insert(0, "scenario", scenario_name)

        scenario_path = RESULTS_DIR / f"{scenario_name}_results.csv"
        results.to_csv(scenario_path, index=False)

        all_results.append(results)
        summary_records.append(
            compute_summary_metrics(
                scenario_name=scenario_name,
                results=results,
            )
        )

    combined_results = pd.concat(all_results, ignore_index=True)
    summary_df = pd.DataFrame(summary_records)

    combined_results_path = RESULTS_DIR / "combined_results.csv"
    summary_path = RESULTS_DIR / "scenario_summary.csv"

    combined_results.to_csv(combined_results_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    return combined_results, summary_df


if __name__ == "__main__":
    # Run:
    # python src/experiments.py

    combined_results, summary_df = run_all_scenarios(
        shock_time=30,
        shock_size=-0.43,
        initial_dai_price=1.0,
    )

    print("\nScenario summary:")
    print(summary_df)

    print("\nSaved results to:")
    print(RESULTS_DIR)