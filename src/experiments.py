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

from simulation import (
    SimulationConfig,
    run_shock_simulation,
    run_shock_recovery_simulation,
)
from liquidation import LiquidationConfig
from confidence import ConfidenceConfig
from dai_market import DAIMarketConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "outputs" / "results"


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


def compute_oracle_delay_metrics(
    scenario_name: str,
    results: pd.DataFrame,
) -> dict:
    """
    Compute summary metrics for oracle-delay experiments.

    These metrics focus on hidden risk created when the oracle price lags
    behind the market price.
    """
    final = results.iloc[-1]

    hidden_bad_debt = results["hidden_bad_debt"]
    hidden_positive = hidden_bad_debt > 0

    if hidden_positive.any():
        first_hidden_step = int(results.loc[hidden_positive, "step"].iloc[0])
        last_hidden_step = int(results.loc[hidden_positive, "step"].iloc[-1])
        hidden_duration = int(hidden_positive.sum())
    else:
        first_hidden_step = None
        last_hidden_step = None
        hidden_duration = 0

    peg_deviation = (results["dai_price"] - 1.0).abs()

    return {
        "scenario": scenario_name,
        "oracle_delay_steps": int(final["oracle_delay_steps"]),
        "final_dai_price": float(final["dai_price"]),
        "min_dai_price": float(results["dai_price"].min()),
        "max_abs_peg_deviation": float(peg_deviation.max()),
        "max_hidden_bad_debt": float(results["hidden_bad_debt"].max()),
        "final_hidden_bad_debt": float(final["hidden_bad_debt"]),
        "hidden_bad_debt_duration": hidden_duration,
        "first_hidden_bad_debt_step": first_hidden_step,
        "last_hidden_bad_debt_step": last_hidden_step,
        "max_market_bad_debt_active": float(
            results["market_total_bad_debt_active"].max()
        ),
        "max_oracle_bad_debt_active": float(
            results["oracle_total_bad_debt_active"].max()
        ),
        "final_market_bad_debt_active": float(
            final["market_total_bad_debt_active"]
        ),
        "final_oracle_bad_debt_active": float(
            final["oracle_total_bad_debt_active"]
        ),
        "cumulative_keeper_profit": float(final["keeper_profit_cumulative"]),
        "cumulative_debt_repaid": float(final["debt_repaid_cumulative"]),
        "cumulative_bad_debt_realised": float(
            final["bad_debt_realised_cumulative"]
        ),
        "cumulative_unprofitable_attempts": int(
            final["unprofitable_liquidations_cumulative"]
        ),
    }


def compute_shock_severity_metrics(
    scenario_name: str,
    results: pd.DataFrame,
) -> dict:
    """
    Compute summary metrics for shock-severity experiments.

    These metrics focus on how different ETH shock sizes affect peg stability,
    liquidation pressure, bad debt and keeper activity.
    """
    final = results.iloc[-1]

    peg_deviation = (results["dai_price"] - 1.0).abs()

    panic_mask = results["regime_after"] == "panic"
    if panic_mask.any():
        first_panic_step = int(results.loc[panic_mask, "step"].iloc[0])
    else:
        first_panic_step = None

    material_depeg_mask = results["dai_price"] < 0.99
    if material_depeg_mask.any():
        first_material_depeg_step = int(
            results.loc[material_depeg_mask, "step"].iloc[0]
        )
    else:
        first_material_depeg_step = None

    return {
        "scenario": scenario_name,
        "shock_size": float(final["shock_size_experiment"]),
        "final_dai_price": float(final["dai_price"]),
        "min_dai_price": float(results["dai_price"].min()),
        "max_abs_peg_deviation": float(peg_deviation.max()),
        "first_material_depeg_step": first_material_depeg_step,
        "first_panic_step": first_panic_step,
        "final_regime": str(final["regime_after"]),
        "max_liquidatable_vaults": int(
            results["n_liquidatable_before_liquidation"].max()
        ),
        "final_liquidatable_vaults": int(final["n_liquidatable"]),
        "max_market_bad_debt_active": float(
            results["market_total_bad_debt_active"].max()
        ),
        "final_market_bad_debt_active": float(
            final["market_total_bad_debt_active"]
        ),
        "cumulative_keeper_profit": float(final["keeper_profit_cumulative"]),
        "cumulative_debt_repaid": float(final["debt_repaid_cumulative"]),
        "cumulative_bad_debt_realised": float(
            final["bad_debt_realised_cumulative"]
        ),
        "cumulative_unprofitable_attempts": int(
            final["unprofitable_liquidations_cumulative"]
        ),
        "cumulative_capacity_limited_attempts": int(
            final["capacity_limited_liquidations_cumulative"]
        ),
    }


def compute_confidence_sensitivity_metrics(
    scenario_name: str,
    results: pd.DataFrame,
) -> dict:
    """
    Compute summary metrics for confidence-sensitivity experiments.

    These metrics focus on how market confidence and panic sensitivity affect
    DAI peg stability under the same collateral shock and liquidation setting.
    """
    final = results.iloc[-1]

    peg_deviation = (results["dai_price"] - 1.0).abs()

    panic_mask = results["regime_after"] == "panic"
    if panic_mask.any():
        first_panic_step = int(results.loc[panic_mask, "step"].iloc[0])
        panic_duration = int(panic_mask.sum())
    else:
        first_panic_step = None
        panic_duration = 0

    stress_mask = results["regime_after"] == "stress"
    stress_duration = int(stress_mask.sum())

    material_depeg_mask = results["dai_price"] < 0.99
    if material_depeg_mask.any():
        first_material_depeg_step = int(
            results.loc[material_depeg_mask, "step"].iloc[0]
        )
        material_depeg_duration = int(material_depeg_mask.sum())
    else:
        first_material_depeg_step = None
        material_depeg_duration = 0

    return {
        "scenario": scenario_name,
        "final_dai_price": float(final["dai_price"]),
        "min_dai_price": float(results["dai_price"].min()),
        "max_abs_peg_deviation": float(peg_deviation.max()),
        "first_material_depeg_step": first_material_depeg_step,
        "material_depeg_duration": material_depeg_duration,
        "first_panic_step": first_panic_step,
        "panic_duration": panic_duration,
        "stress_duration": stress_duration,
        "final_regime": str(final["regime_after"]),
        "mean_confidence_after": float(results["confidence_after"].mean()),
        "min_confidence_after": float(results["confidence_after"].min()),
        "max_panic_selling_pressure": float(
            results["panic_selling_pressure_after"].max()
        ),
        "final_market_bad_debt_active": float(
            final["market_total_bad_debt_active"]
        ),
        "max_market_bad_debt_active": float(
            results["market_total_bad_debt_active"].max()
        ),
        "cumulative_keeper_profit": float(final["keeper_profit_cumulative"]),
        "cumulative_debt_repaid": float(final["debt_repaid_cumulative"]),
        "cumulative_bad_debt_realised": float(
            final["bad_debt_realised_cumulative"]
        ),
        "cumulative_unprofitable_attempts": int(
            final["unprofitable_liquidations_cumulative"]
        ),
    }


def compute_recovery_metrics(
    scenario_name: str,
    results: pd.DataFrame,
    shock_time: int = 30,
) -> dict:
    """
    Compute summary metrics for peg-recovery experiments.

    Recovery is measured in several ways:

    1. Price recovery:
       Whether DAI returns close to the peg after first breaching a threshold.

    2. Full system recovery:
       Whether DAI is close to peg, active bad debt is cleared, and the system
       has exited the panic regime.

    3. Recovery half-life:
       After DAI reaches its post-shock trough, how many steps it takes to
       recover half of the distance back to the peg.
    """
    final = results.iloc[-1]

    peg_deviation = (results["dai_price"] - 1.0).abs()

    post_shock = results["step"] >= shock_time
    post_shock_results = results.loc[post_shock].copy()

    # ------------------------------------------------------------------
    # Basic below-peg duration metrics
    # ------------------------------------------------------------------
    below_099 = post_shock & (results["dai_price"] < 0.99)
    below_995 = post_shock & (results["dai_price"] < 0.995)

    below_099_duration = int(below_099.sum())
    below_995_duration = int(below_995.sum())

    # ------------------------------------------------------------------
    # First breach and recovery above 0.99
    # Recovery is only counted if the price first breaches the threshold.
    # ------------------------------------------------------------------
    breach_099 = post_shock & (results["dai_price"] < 0.99)

    if breach_099.any():
        first_breach_099_step = int(results.loc[breach_099, "step"].iloc[0])

        recovery_after_breach_099 = (
            (results["step"] > first_breach_099_step)
            & (results["dai_price"] >= 0.99)
        )

        if recovery_after_breach_099.any():
            first_price_recovery_099_step = int(
                results.loc[recovery_after_breach_099, "step"].iloc[0]
            )
        else:
            first_price_recovery_099_step = None
    else:
        first_breach_099_step = None
        first_price_recovery_099_step = None

    # ------------------------------------------------------------------
    # First breach and recovery above 0.995
    # This is stricter and more useful for near-peg recovery.
    # ------------------------------------------------------------------
    breach_995 = post_shock & (results["dai_price"] < 0.995)

    if breach_995.any():
        first_breach_995_step = int(results.loc[breach_995, "step"].iloc[0])

        recovery_after_breach_995 = (
            (results["step"] > first_breach_995_step)
            & (results["dai_price"] >= 0.995)
        )

        if recovery_after_breach_995.any():
            first_price_recovery_995_step = int(
                results.loc[recovery_after_breach_995, "step"].iloc[0]
            )
        else:
            first_price_recovery_995_step = None
    else:
        first_breach_995_step = None
        first_price_recovery_995_step = None

    # ------------------------------------------------------------------
    # Full system recovery:
    # DAI close to peg, active bad debt cleared, and no longer in panic.
    # ------------------------------------------------------------------
    full_system_recovery_099 = (
        post_shock
        & (results["dai_price"] >= 0.99)
        & (results["market_total_bad_debt_active"] <= 1e-6)
        & (results["regime_after"] != "panic")
    )

    if full_system_recovery_099.any():
        first_full_system_recovery_099_step = int(
            results.loc[full_system_recovery_099, "step"].iloc[0]
        )
    else:
        first_full_system_recovery_099_step = None

    full_system_recovery_995 = (
        post_shock
        & (results["dai_price"] >= 0.995)
        & (results["market_total_bad_debt_active"] <= 1e-6)
        & (results["regime_after"] != "panic")
    )

    if full_system_recovery_995.any():
        first_full_system_recovery_995_step = int(
            results.loc[full_system_recovery_995, "step"].iloc[0]
        )
    else:
        first_full_system_recovery_995_step = None

    # ------------------------------------------------------------------
    # Recovery half-life:
    # Find the post-shock trough, then measure how long it takes to recover
    # half of the distance from trough price back to the peg.
    # ------------------------------------------------------------------
    if post_shock_results.empty:
        trough_step = None
        trough_price = None
        half_recovery_target = None
        half_recovery_step = None
        recovery_half_life = None
    else:
        trough_index = post_shock_results["dai_price"].idxmin()
        trough_step = int(results.loc[trough_index, "step"])
        trough_price = float(results.loc[trough_index, "dai_price"])

        half_recovery_target = trough_price + 0.5 * (1.0 - trough_price)

        half_recovery_mask = (
            (results["step"] > trough_step)
            & (results["dai_price"] >= half_recovery_target)
        )

        if half_recovery_mask.any():
            half_recovery_step = int(
                results.loc[half_recovery_mask, "step"].iloc[0]
            )
            recovery_half_life = half_recovery_step - trough_step
        else:
            half_recovery_step = None
            recovery_half_life = None

    # ------------------------------------------------------------------
    # Regime durations
    # ------------------------------------------------------------------
    panic_mask = post_shock & (results["regime_after"] == "panic")
    stress_mask = post_shock & (results["regime_after"] == "stress")
    normal_mask = post_shock & (results["regime_after"] == "normal")

    return {
        "scenario": scenario_name,
        "recovery_fraction": float(final["recovery_fraction_experiment"]),
        "final_eth_price": float(final["market_eth_price"]),
        "final_dai_price": float(final["dai_price"]),
        "min_dai_price": float(results["dai_price"].min()),
        "max_abs_peg_deviation": float(peg_deviation.max()),

        # Threshold breach / recovery metrics.
        "below_099_duration": below_099_duration,
        "below_995_duration": below_995_duration,
        "first_breach_099_step": first_breach_099_step,
        "first_breach_995_step": first_breach_995_step,
        "first_price_recovery_099_step": first_price_recovery_099_step,
        "first_price_recovery_995_step": first_price_recovery_995_step,

        # Full system recovery metrics.
        "first_full_system_recovery_099_step": (
            first_full_system_recovery_099_step
        ),
        "first_full_system_recovery_995_step": (
            first_full_system_recovery_995_step
        ),

        # Recovery half-life metrics.
        "trough_step": trough_step,
        "trough_dai_price": trough_price,
        "half_recovery_target": half_recovery_target,
        "half_recovery_step": half_recovery_step,
        "recovery_half_life": recovery_half_life,

        # Regime metrics.
        "panic_duration": int(panic_mask.sum()),
        "stress_duration": int(stress_mask.sum()),
        "normal_duration": int(normal_mask.sum()),
        "final_regime": str(final["regime_after"]),

        # Bad debt and recovery pressure.
        "max_market_bad_debt_active": float(
            results["market_total_bad_debt_active"].max()
        ),
        "final_market_bad_debt_active": float(
            final["market_total_bad_debt_active"]
        ),
        "max_total_recovery_pressure": float(
            results["total_recovery_pressure"].max()
        ),
        "max_arbitrage_recovery_pressure": float(
            results["arbitrage_recovery_pressure"].max()
        ),
        "max_policy_feedback_pressure": float(
            results["policy_feedback_pressure"].max()
        ),

        # Liquidation outcome metrics.
        "cumulative_keeper_profit": float(final["keeper_profit_cumulative"]),
        "cumulative_debt_repaid": float(final["debt_repaid_cumulative"]),
        "cumulative_bad_debt_realised": float(
            final["bad_debt_realised_cumulative"]
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

    sim_config = create_base_simulation_config(
        oracle_delay_steps=0,
    )
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


def run_oracle_delay_experiment(
    delay_values: list[int] | None = None,
    shock_time: int = 30,
    shock_size: float = -0.43,
    initial_dai_price: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run oracle-delay sensitivity experiment.

    This experiment keeps liquidation and market parameters fixed, but varies
    the number of steps by which the oracle ETH price lags the market ETH price.

    Parameters
    ----------
    delay_values:
        Oracle delay values to test.
    shock_time:
        ETH shock time.
    shock_size:
        ETH shock size.
    initial_dai_price:
        Initial DAI price.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        Combined oracle-delay results and summary table.
    """
    if delay_values is None:
        delay_values = [0, 1, 3, 5, 10]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    base_confidence = create_base_confidence_config()
    base_market = create_base_dai_market_config()

    # Use a medium/high friction setting so oracle delay has visible effects.
    liquidation_config = LiquidationConfig(
        liquidation_penalty=0.13,
        gas_cost=250.0,
        risk_cost_rate=0.00,
        max_close_factor=0.5,
        max_liquidations_per_step=5,
    )

    all_results = []
    summary_records = []

    for delay in delay_values:
        scenario_name = f"oracle_delay_{delay}"

        print(f"Running oracle delay scenario: {scenario_name}")

        sim_config = create_base_simulation_config(
            oracle_delay_steps=delay,
        )

        results = run_shock_simulation(
            config=sim_config,
            liquidation_config=liquidation_config,
            confidence_config=base_confidence,
            dai_market_config=base_market,
            shock_time=shock_time,
            shock_size=shock_size,
            initial_dai_price=initial_dai_price,
            execute_liquidations=True,
        )

        results.insert(0, "scenario", scenario_name)
        results.insert(1, "oracle_delay_steps_experiment", delay)

        scenario_path = RESULTS_DIR / f"{scenario_name}_results.csv"
        results.to_csv(scenario_path, index=False)

        all_results.append(results)
        summary_records.append(
            compute_oracle_delay_metrics(
                scenario_name=scenario_name,
                results=results,
            )
        )

    combined_results = pd.concat(all_results, ignore_index=True)
    summary_df = pd.DataFrame(summary_records)

    combined_path = RESULTS_DIR / "oracle_delay_combined_results.csv"
    summary_path = RESULTS_DIR / "oracle_delay_summary.csv"

    combined_results.to_csv(combined_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    return combined_results, summary_df


def run_shock_severity_experiment(
    shock_values: list[float] | None = None,
    shock_time: int = 30,
    initial_dai_price: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run experiments across different ETH shock severities.

    This experiment tests how increasingly severe collateral shocks affect
    DAI peg stability, liquidation pressure, bad debt and keeper activity.
    """
    if shock_values is None:
        shock_values = [-0.20, -0.35, -0.43, -0.55, -0.70]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    all_results = []
    summary_records = []

    # Use a medium/high friction setting as the baseline for severity testing.
    # This avoids making the system either too easy or completely impossible.
    liquidation_config = LiquidationConfig(
        liquidation_penalty=0.13,
        gas_cost=250.0,
        risk_cost_rate=0.00,
        max_close_factor=0.5,
        max_liquidations_per_step=5,
    )

    confidence_config = create_base_confidence_config()
    dai_market_config = create_base_dai_market_config()

    for shock_size in shock_values:
        scenario_name = f"shock_{abs(int(shock_size * 100))}pct"

        print(f"Running shock severity scenario: {scenario_name}")

        sim_config = create_base_simulation_config(oracle_delay_steps=0)

        results = run_shock_simulation(
            config=sim_config,
            liquidation_config=liquidation_config,
            confidence_config=confidence_config,
            dai_market_config=dai_market_config,
            shock_time=shock_time,
            shock_size=shock_size,
            initial_dai_price=initial_dai_price,
            execute_liquidations=True,
        )

        results["scenario"] = scenario_name
        results["shock_size_experiment"] = shock_size

        scenario_path = RESULTS_DIR / f"{scenario_name}_results.csv"
        results.to_csv(scenario_path, index=False)

        all_results.append(results)
        summary_records.append(
            compute_shock_severity_metrics(
                scenario_name=scenario_name,
                results=results,
            )
        )

    combined_results = pd.concat(all_results, ignore_index=True)
    summary = pd.DataFrame(summary_records)

    combined_path = RESULTS_DIR / "shock_severity_combined_results.csv"
    summary_path = RESULTS_DIR / "shock_severity_summary.csv"

    combined_results.to_csv(combined_path, index=False)
    summary.to_csv(summary_path, index=False)

    return combined_results, summary


def run_confidence_sensitivity_experiment(
    shock_time: int = 30,
    shock_size: float = -0.43,
    initial_dai_price: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run confidence-sensitivity experiments.

    The collateral shock and liquidation setting are fixed. Only the confidence
    and DAI market response parameters vary across scenarios.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    all_results = []
    summary_records = []

    sim_config = create_base_simulation_config(oracle_delay_steps=0)

    liquidation_config = LiquidationConfig(
        liquidation_penalty=0.13,
        gas_cost=250.0,
        risk_cost_rate=0.00,
        max_close_factor=0.5,
        max_liquidations_per_step=5,
    )

    scenario_configs = create_confidence_sensitivity_configs()

    for scenario_name, scenario_config in scenario_configs.items():
        print(f"Running confidence sensitivity scenario: {scenario_name}")

        results = run_shock_simulation(
            config=sim_config,
            liquidation_config=liquidation_config,
            confidence_config=scenario_config["confidence_config"],
            dai_market_config=scenario_config["dai_market_config"],
            shock_time=shock_time,
            shock_size=shock_size,
            initial_dai_price=initial_dai_price,
            execute_liquidations=True,
        )

        results["scenario"] = scenario_name
        results["confidence_scenario"] = scenario_name

        scenario_path = RESULTS_DIR / f"{scenario_name}_confidence_results.csv"
        results.to_csv(scenario_path, index=False)

        all_results.append(results)

        summary_records.append(
            compute_confidence_sensitivity_metrics(
                scenario_name=scenario_name,
                results=results,
            )
        )

    combined_results = pd.concat(all_results, ignore_index=True)
    summary = pd.DataFrame(summary_records)

    combined_path = RESULTS_DIR / "confidence_sensitivity_combined_results.csv"
    summary_path = RESULTS_DIR / "confidence_sensitivity_summary.csv"

    combined_results.to_csv(combined_path, index=False)
    summary.to_csv(summary_path, index=False)

    return combined_results, summary


def run_peg_recovery_experiment(
    recovery_fractions: list[float] | None = None,
    shock_time: int = 30,
    shock_size: float = -0.43,
    recovery_start: int = 40,
    recovery_end: int = 90,
    initial_dai_price: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run peg-recovery experiments using different ETH recovery paths.

    The initial ETH shock is fixed. The experiment varies how much of the ETH
    price loss is recovered after the shock.
    """
    if recovery_fractions is None:
        recovery_fractions = [0.0, 0.25, 0.50, 0.75, 1.0]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    all_results = []
    summary_records = []

    liquidation_config = LiquidationConfig(
        liquidation_penalty=0.13,
        gas_cost=250.0,
        risk_cost_rate=0.00,
        max_close_factor=0.5,
        max_liquidations_per_step=5,
    )

    confidence_config = create_base_confidence_config()
    dai_market_config = create_recovery_dai_market_config()

    for recovery_fraction in recovery_fractions:
        scenario_name = f"recovery_{int(recovery_fraction * 100)}pct"

        print(f"Running peg recovery scenario: {scenario_name}")

        sim_config = create_base_simulation_config(oracle_delay_steps=0)

        results = run_shock_recovery_simulation(
            config=sim_config,
            liquidation_config=liquidation_config,
            confidence_config=confidence_config,
            dai_market_config=dai_market_config,
            shock_time=shock_time,
            shock_size=shock_size,
            recovery_start=recovery_start,
            recovery_end=recovery_end,
            recovery_fraction=recovery_fraction,
            initial_dai_price=initial_dai_price,
            execute_liquidations=True,
        )

        results["scenario"] = scenario_name
        results["recovery_fraction_experiment"] = recovery_fraction

        scenario_path = RESULTS_DIR / f"{scenario_name}_results.csv"
        results.to_csv(scenario_path, index=False)

        all_results.append(results)
        summary_records.append(
            compute_recovery_metrics(
                scenario_name=scenario_name,
                results=results,
                shock_time=shock_time,
            )
        )

    combined_results = pd.concat(all_results, ignore_index=True)
    summary = pd.DataFrame(summary_records)

    combined_path = RESULTS_DIR / "peg_recovery_combined_results.csv"
    summary_path = RESULTS_DIR / "peg_recovery_summary.csv"

    combined_results.to_csv(combined_path, index=False)
    summary.to_csv(summary_path, index=False)

    return combined_results, summary


if __name__ == "__main__":
    # Run:
    # python src/experiments.py

    combined_results, summary = run_all_scenarios(
        shock_time=30,
        shock_size=-0.43,
        initial_dai_price=1.0,
    )
    print("\nScenario summary:")
    print(summary)

    oracle_results, oracle_summary = run_oracle_delay_experiment(
        delay_values=[0, 1, 3, 5, 10],
        shock_time=30,
        shock_size=-0.43,
        initial_dai_price=1.0,
    )
    print("\nOracle delay summary:")
    print(oracle_summary)

    shock_results, shock_summary = run_shock_severity_experiment(
        shock_values=[-0.20, -0.35, -0.43, -0.55, -0.70],
        shock_time=30,
        initial_dai_price=1.0,
    )
    print("\nShock severity summary:")
    print(shock_summary)

    confidence_results, confidence_summary = run_confidence_sensitivity_experiment(
        shock_time=30,
        shock_size=-0.43,
        initial_dai_price=1.0,
    )
    print("\nConfidence sensitivity summary:")
    print(confidence_summary)

    recovery_results, recovery_summary = run_peg_recovery_experiment(
        recovery_fractions=[0.0, 0.25, 0.50, 0.75, 1.0],
        shock_time=30,
        shock_size=-0.43,
        recovery_start=40,
        recovery_end=90,
        initial_dai_price=1.0,
    )
    print("\nPeg recovery summary:")
    print(recovery_summary)