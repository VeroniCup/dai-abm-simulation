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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from dai_sim.model.collateral import (
    CollateralPortfolioConfig,
    create_balanced_portfolio,
    create_btc_concentrated_portfolio,
    create_crypto_diversified_portfolio,
    create_eth_only_portfolio,
    create_stable_heavy_portfolio,
)
from dai_sim.model.simulation import (
    SimulationConfig,
    create_initial_vaults,
    run_simulation_with_collateral_metrics,
    run_shock_simulation,
    run_shock_recovery_simulation,
)
from dai_sim.model.collateral_prices import (
    PriceProcessConfig,
    generate_shock_price_path,
)
from dai_sim.model.confidence import ConfidenceConfig
from dai_sim.model.liquidation import LiquidationConfig
from dai_sim.model.market import DAIMarketConfig


from .scenarios import (
    MultiCollateralShockScenario,
    build_multicollateral_price_paths,
    create_base_confidence_config,
    create_base_dai_market_config,
    create_base_simulation_config,
    create_confidence_sensitivity_configs,
    create_multicollateral_portfolios,
    create_multicollateral_shock_scenarios,
    create_recovery_dai_market_config,
    create_scenario_configs,
)
from .summaries import (
    compute_confidence_sensitivity_metrics,
    compute_multicollateral_collateral_summary,
    compute_multicollateral_system_summary,
    compute_oracle_delay_metrics,
    compute_recovery_metrics,
    compute_shock_severity_metrics,
    compute_summary_metrics,
    validate_multicollateral_results,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = PROJECT_ROOT / "outputs" / "results"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
MULTICOLLATERAL_RESULTS_DIR = RESULTS_DIR / "06_multicollateral"
MULTICOLLATERAL_FIGURES_DIR = FIGURES_DIR / "06_multicollateral"
MULTICOLLATERAL_DIAGNOSTICS_DIR = (
    MULTICOLLATERAL_RESULTS_DIR / "diagnostics"
)
























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


# ---------------------------------------------------------------------
# 06 Multi-collateral portfolio experiments
# ---------------------------------------------------------------------

def save_multicollateral_outputs(
    system_results: pd.DataFrame,
    collateral_results: pd.DataFrame,
    system_summary: pd.DataFrame,
    collateral_summary: pd.DataFrame,
    output_dir: Path = MULTICOLLATERAL_RESULTS_DIR,
) -> dict[str, Path]:
    """Save Experiment 06 tables directly in the results directory."""
    paths = {
        "system_results": output_dir / "system_results.csv",
        "collateral_results": output_dir / "collateral_results.csv",
        "system_summary": output_dir / "system_summary.csv",
        "collateral_summary": output_dir / "collateral_summary.csv",
    }
    frames = {
        "system_results": system_results,
        "collateral_results": collateral_results,
        "system_summary": system_summary,
        "collateral_summary": collateral_summary,
    }

    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        frames[name].to_csv(path, index=False)

    return paths


def run_multicollateral_experiment(
    portfolios: Mapping[str, CollateralPortfolioConfig] | None = None,
    shock_scenarios: Mapping[
        str,
        MultiCollateralShockScenario,
    ] | None = None,
    simulation_config: SimulationConfig | None = None,
    liquidation_config: LiquidationConfig | None = None,
    confidence_config: ConfidenceConfig | None = None,
    dai_market_config: DAIMarketConfig | None = None,
    shock_time: int = 30,
    initial_dai_price: float = 1.0,
    output_dir: Path = MULTICOLLATERAL_RESULTS_DIR,
    save_outputs: bool = True,
    generate_figures: bool = True,
    figure_dir: Path = MULTICOLLATERAL_FIGURES_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the complete portfolio-by-shock Experiment 06 grid."""
    if portfolios is None:
        portfolios = create_multicollateral_portfolios()
    if shock_scenarios is None:
        shock_scenarios = create_multicollateral_shock_scenarios()
    if not portfolios:
        raise ValueError("At least one collateral portfolio is required.")
    if not shock_scenarios:
        raise ValueError("At least one shock scenario is required.")

    if simulation_config is None:
        simulation_config = create_base_simulation_config(
            oracle_delay_steps=0,
        )

    default_scenario = create_scenario_configs()["high_gas"]
    if liquidation_config is None:
        liquidation_config = default_scenario["liquidation_config"]
    if confidence_config is None:
        confidence_config = default_scenario["confidence_config"]
    if dai_market_config is None:
        dai_market_config = default_scenario["dai_market_config"]

    system_runs = []
    collateral_runs = []

    for portfolio_name, portfolio in portfolios.items():
        if portfolio_name != portfolio.name:
            raise ValueError(
                "Portfolio mapping keys must match portfolio names: "
                f"'{portfolio_name}' != '{portfolio.name}'."
            )

        portfolio_config = replace(
            simulation_config,
            collateral_portfolio=portfolio,
        )

        for scenario_name, shock_scenario in shock_scenarios.items():
            if scenario_name != shock_scenario.name:
                raise ValueError(
                    "Shock mapping keys must match scenario names: "
                    f"'{scenario_name}' != '{shock_scenario.name}'."
                )

            print(
                "Running Experiment 06: "
                f"portfolio={portfolio_name}, shock={scenario_name}"
            )
            price_paths = build_multicollateral_price_paths(
                portfolio=portfolio,
                shock_scenario=shock_scenario,
                n_steps=portfolio_config.n_steps,
                shock_time=shock_time,
                random_seed=portfolio_config.random_seed,
            )
            system_results, collateral_results = (
                run_simulation_with_collateral_metrics(
                    config=portfolio_config,
                    price_path=price_paths,
                    liquidation_config=liquidation_config,
                    confidence_config=confidence_config,
                    dai_market_config=dai_market_config,
                    initial_dai_price=initial_dai_price,
                    execute_liquidations=True,
                )
            )
            system_results.insert(0, "portfolio", portfolio_name)
            system_results.insert(1, "shock_scenario", scenario_name)
            collateral_results.insert(0, "portfolio", portfolio_name)
            collateral_results.insert(1, "shock_scenario", scenario_name)
            system_runs.append(system_results)
            collateral_runs.append(collateral_results)

    combined_system_results = pd.concat(system_runs, ignore_index=True)
    combined_collateral_results = pd.concat(
        collateral_runs,
        ignore_index=True,
    )
    system_summary = compute_multicollateral_system_summary(
        combined_system_results
    )
    collateral_summary = compute_multicollateral_collateral_summary(
        combined_collateral_results
    )
    validate_multicollateral_results(
        system_results=combined_system_results,
        collateral_results=combined_collateral_results,
        system_summary=system_summary,
        collateral_summary=collateral_summary,
    )

    if save_outputs:
        save_multicollateral_outputs(
            system_results=combined_system_results,
            collateral_results=combined_collateral_results,
            system_summary=system_summary,
            collateral_summary=collateral_summary,
            output_dir=output_dir,
        )

    if generate_figures:
        from .plots import create_multicollateral_figures

        create_multicollateral_figures(
            system_results=combined_system_results,
            system_summary=system_summary,
            collateral_summary=collateral_summary,
            shock_time=shock_time,
            figure_dir=figure_dir,
        )

    return (
        combined_system_results,
        combined_collateral_results,
        system_summary,
        collateral_summary,
    )


# ---------------------------------------------------------------------
# 06 Multi-collateral diagnostics
# ---------------------------------------------------------------------

def create_initial_collateral_risk_diagnostics(
    portfolios: Mapping[str, CollateralPortfolioConfig] | None = None,
    simulation_config: SimulationConfig | None = None,
) -> pd.DataFrame:
    """Describe the seeded initial vault populations in long format."""
    if portfolios is None:
        portfolios = create_multicollateral_portfolios()
    if simulation_config is None:
        simulation_config = create_base_simulation_config(
            oracle_delay_steps=0,
        )

    records = []

    for portfolio_name, portfolio in portfolios.items():
        portfolio_config = replace(
            simulation_config,
            collateral_portfolio=portfolio,
        )
        vaults = create_initial_vaults(portfolio_config)
        initial_prices = portfolio.initial_prices
        if "ETH" in initial_prices:
            initial_prices["ETH"] = portfolio_config.initial_eth_price

        for vault in vaults:
            initial_ratio = float(vault.collateral_ratio(initial_prices))
            distance_to_liquidation = (
                initial_ratio - vault.liquidation_ratio
            )
            critical_decline = (
                1.0 - vault.liquidation_ratio / initial_ratio
            )

            if not 0.0 <= critical_decline < 1.0:
                raise ValueError(
                    "Initial vault diagnostic requires active vaults above "
                    "their liquidation ratios."
                )

            # Check the analytical threshold against the vault's existing
            # liquidatability rule on either side of the strict boundary.
            critical_multiplier = 1.0 - critical_decline
            epsilon = min(1e-9, critical_multiplier / 2.0)
            safe_prices = initial_prices.copy()
            liquidatable_prices = initial_prices.copy()
            initial_price = initial_prices[vault.collateral_type]
            safe_prices[vault.collateral_type] = initial_price * (
                critical_multiplier + epsilon
            )
            liquidatable_prices[vault.collateral_type] = initial_price * (
                critical_multiplier - epsilon
            )

            if vault.is_liquidatable(safe_prices):
                raise ValueError(
                    "Critical price-decline calculation failed above the "
                    f"boundary for vault {vault.vault_id}."
                )
            if not vault.is_liquidatable(liquidatable_prices):
                raise ValueError(
                    "Critical price-decline calculation failed below the "
                    f"boundary for vault {vault.vault_id}."
                )

            records.append(
                {
                    "portfolio": portfolio_name,
                    "collateral_type": vault.collateral_type,
                    "vault_id": vault.vault_id,
                    "debt_dai": float(vault.debt_dai),
                    "initial_collateral_ratio": initial_ratio,
                    "liquidation_ratio": float(vault.liquidation_ratio),
                    "distance_to_liquidation": float(
                        distance_to_liquidation
                    ),
                    "critical_proportional_price_decline": float(
                        critical_decline
                    ),
                }
            )

    return pd.DataFrame(records)


def build_stable_depeg_diagnostic_price_paths(
    portfolio: CollateralPortfolioConfig,
    stable_price_level: float,
    n_steps: int,
    shock_time: int,
    random_seed: int | None = 42,
) -> dict[str, np.ndarray]:
    """Build deterministic paths for one absolute STABLE price level."""
    if not portfolio.contains("STABLE"):
        raise ValueError(
            f"Portfolio '{portfolio.name}' does not contain STABLE collateral."
        )

    stable_initial_price = portfolio.get("STABLE").initial_price
    numeric_level = float(stable_price_level)
    if not 0.0 < numeric_level <= stable_initial_price:
        raise ValueError(
            "stable_price_level must be positive and no greater than the "
            "portfolio's initial STABLE price."
        )

    price_paths: dict[str, np.ndarray] = {}

    for collateral in portfolio.collaterals:
        shock_size = 0.0
        if collateral.name == "STABLE":
            shock_size = numeric_level / collateral.initial_price - 1.0

        generated_path = generate_shock_price_path(
            config=PriceProcessConfig(
                n_steps=n_steps,
                initial_price=collateral.initial_price,
                random_seed=random_seed,
            ),
            shock_time=shock_time,
            shock_size=shock_size,
        )
        price_paths[collateral.name] = generated_path[
            "eth_price"
        ].to_numpy()

    return price_paths


def run_stable_depeg_severity_diagnostic(
    stable_price_levels: Sequence[float] = (
        1.00,
        0.98,
        0.95,
        0.90,
        0.85,
        0.80,
        0.75,
        0.70,
        0.65,
    ),
    portfolios: Mapping[str, CollateralPortfolioConfig] | None = None,
    simulation_config: SimulationConfig | None = None,
    liquidation_config: LiquidationConfig | None = None,
    confidence_config: ConfidenceConfig | None = None,
    dai_market_config: DAIMarketConfig | None = None,
    shock_time: int = 30,
) -> pd.DataFrame:
    """Run the in-memory STABLE depeg severity sweep."""
    all_portfolios = create_multicollateral_portfolios()
    if portfolios is None:
        portfolios = {
            "balanced": all_portfolios["balanced"],
            "stable_heavy": all_portfolios["stable_heavy"],
        }
    if simulation_config is None:
        simulation_config = create_base_simulation_config(
            oracle_delay_steps=0,
        )

    default_scenario = create_scenario_configs()["high_gas"]
    if liquidation_config is None:
        liquidation_config = default_scenario["liquidation_config"]
    if confidence_config is None:
        confidence_config = default_scenario["confidence_config"]
    if dai_market_config is None:
        dai_market_config = default_scenario["dai_market_config"]

    levels = sorted(
        {float(level) for level in stable_price_levels},
        reverse=True,
    )
    if not levels:
        raise ValueError("At least one STABLE price level is required.")

    records = []

    for portfolio_name, portfolio in portfolios.items():
        portfolio_config = replace(
            simulation_config,
            collateral_portfolio=portfolio,
        )
        initial_vaults = create_initial_vaults(portfolio_config)
        stable_vaults = [
            vault
            for vault in initial_vaults
            if vault.collateral_type == "STABLE"
        ]
        initial_stable_debt = float(
            sum(vault.debt_dai for vault in stable_vaults)
        )
        initially_exposed_vaults = len(stable_vaults)
        if initial_stable_debt <= 0 or initially_exposed_vaults <= 0:
            raise ValueError(
                f"Portfolio '{portfolio_name}' has no STABLE exposure."
            )

        for stable_price_level in levels:
            print(
                "Running STABLE diagnostic: "
                f"portfolio={portfolio_name}, level={stable_price_level:.2f}"
            )
            shock_prices = portfolio.initial_prices
            if "ETH" in shock_prices:
                shock_prices["ETH"] = portfolio_config.initial_eth_price
            shock_prices["STABLE"] = stable_price_level
            liquidatable_at_shock = sum(
                vault.is_liquidatable(shock_prices)
                for vault in stable_vaults
            )
            price_paths = build_stable_depeg_diagnostic_price_paths(
                portfolio=portfolio,
                stable_price_level=stable_price_level,
                n_steps=portfolio_config.n_steps,
                shock_time=shock_time,
                random_seed=portfolio_config.random_seed,
            )
            system_results, collateral_results = (
                run_simulation_with_collateral_metrics(
                    config=portfolio_config,
                    price_path=price_paths,
                    liquidation_config=liquidation_config,
                    confidence_config=confidence_config,
                    dai_market_config=dai_market_config,
                    execute_liquidations=True,
                )
            )
            stable_results = collateral_results.loc[
                collateral_results["collateral_type"] == "STABLE"
            ].sort_values("step")
            final_stable = stable_results.iloc[-1]
            peg_deviation = system_results["dai_price"] - 1.0
            realised_bad_debt = float(
                stable_results["realised_bad_debt"].sum()
            )
            debt_repaid = float(stable_results["debt_repaid"].sum())
            successful_liquidations = int(
                stable_results["successful_liquidations"].sum()
            )
            keeper_profit = float(stable_results["keeper_profit"].sum())

            records.append(
                {
                    "portfolio": portfolio_name,
                    "stable_price_level": stable_price_level,
                    "peak_dai_peg_deviation": float(
                        peg_deviation.abs().max()
                    ),
                    "final_dai_peg_deviation": float(
                        peg_deviation.iloc[-1]
                    ),
                    "stable_liquidatable_vaults_at_shock": int(
                        liquidatable_at_shock
                    ),
                    "stable_peak_liquidatable_vaults": int(
                        stable_results["liquidatable_vaults"].max()
                    ),
                    "stable_final_liquidatable_vaults": int(
                        final_stable["liquidatable_vaults"]
                    ),
                    "stable_initial_debt": initial_stable_debt,
                    "stable_active_debt": float(final_stable["active_debt"]),
                    "stable_realised_bad_debt": realised_bad_debt,
                    "stable_debt_repaid": debt_repaid,
                    "stable_successful_liquidations": (
                        successful_liquidations
                    ),
                    "stable_keeper_profit": keeper_profit,
                    "minimum_confidence": float(
                        system_results["confidence_after"].min()
                    ),
                    "final_confidence": float(
                        system_results["confidence_after"].iloc[-1]
                    ),
                    "realised_bad_debt_per_initial_stable_debt": (
                        realised_bad_debt / initial_stable_debt
                    ),
                    "debt_repaid_per_initial_stable_debt": (
                        debt_repaid / initial_stable_debt
                    ),
                    "successful_liquidations_per_exposed_vault": (
                        successful_liquidations / initially_exposed_vaults
                    ),
                    "initially_exposed_stable_vaults": (
                        initially_exposed_vaults
                    ),
                    "first_liquidatable_level": False,
                }
            )

    sweep = pd.DataFrame(records)
    for portfolio_name, portfolio_rows in sweep.groupby(
        "portfolio",
        sort=False,
    ):
        liquidatable_rows = portfolio_rows.loc[
            portfolio_rows["stable_liquidatable_vaults_at_shock"] > 0
        ]
        if not liquidatable_rows.empty:
            first_index = liquidatable_rows.index[0]
            sweep.loc[first_index, "first_liquidatable_level"] = True

    return sweep


def compute_exposure_normalised_diagnostics(
    collateral_results: pd.DataFrame,
    initial_risk: pd.DataFrame,
    shock_scenarios: Mapping[
        str,
        MultiCollateralShockScenario,
    ] | None = None,
) -> pd.DataFrame:
    """Normalise shocked-collateral outcomes by their initial exposures."""
    if shock_scenarios is None:
        shock_scenarios = create_multicollateral_shock_scenarios()

    records = []

    for (portfolio, shock_scenario), run_results in collateral_results.groupby(
        ["portfolio", "shock_scenario"],
        sort=False,
    ):
        scenario = shock_scenarios[str(shock_scenario)]

        for collateral_type, shock_size in scenario.shock_sizes.items():
            exposure = initial_risk.loc[
                (initial_risk["portfolio"] == portfolio)
                & (initial_risk["collateral_type"] == collateral_type)
            ]
            if exposure.empty:
                continue

            initial_debt = float(exposure["debt_dai"].sum())
            initially_exposed_vaults = int(len(exposure))
            if initial_debt <= 0 or initially_exposed_vaults <= 0:
                raise ValueError(
                    "Exposure-normalised diagnostics require positive "
                    "initial debt and vault counts."
                )

            outcomes = run_results.loc[
                run_results["collateral_type"] == collateral_type
            ]
            if outcomes.empty:
                raise ValueError(
                    "Detailed collateral results are missing shocked "
                    f"collateral '{collateral_type}' for "
                    f"{portfolio}/{shock_scenario}."
                )
            realised_bad_debt = float(
                outcomes["realised_bad_debt"].sum()
            )
            debt_repaid = float(outcomes["debt_repaid"].sum())
            successful_liquidations = int(
                outcomes["successful_liquidations"].sum()
            )

            records.append(
                {
                    "portfolio": str(portfolio),
                    "shock_scenario": str(shock_scenario),
                    "shocked_collateral_type": collateral_type,
                    "proportional_price_shock": float(shock_size),
                    "initial_debt": initial_debt,
                    "initially_exposed_vaults": initially_exposed_vaults,
                    "realised_bad_debt": realised_bad_debt,
                    "debt_repaid": debt_repaid,
                    "successful_liquidations": successful_liquidations,
                    "realised_bad_debt_per_initial_debt": (
                        realised_bad_debt / initial_debt
                    ),
                    "debt_repaid_per_initial_debt": (
                        debt_repaid / initial_debt
                    ),
                    "successful_liquidations_per_exposed_vault": (
                        successful_liquidations / initially_exposed_vaults
                    ),
                }
            )

    return pd.DataFrame(records)


def _compare_result_frames(
    first_results: pd.DataFrame,
    second_results: pd.DataFrame,
    tolerance: float,
    columns: Sequence[str] | None = None,
) -> tuple[bool, bool, list[str], float]:
    """Compare aligned result frames exactly and within tolerance."""
    if tolerance < 0:
        raise ValueError("tolerance cannot be negative.")

    ignored_columns = {"shock_scenario"}
    if columns is None:
        comparison_columns = [
            column
            for column in first_results.columns
            if column not in ignored_columns
        ]
    else:
        comparison_columns = list(columns)

    if not set(comparison_columns).issubset(second_results.columns):
        raise ValueError("Result frames do not contain matching columns.")

    first = first_results.loc[:, comparison_columns].reset_index(drop=True)
    second = second_results.loc[:, comparison_columns].reset_index(drop=True)
    if first.shape != second.shape:
        return False, False, comparison_columns, float("inf")

    differing_columns = []
    max_abs_difference = 0.0

    for column in comparison_columns:
        first_column = first[column]
        second_column = second[column]

        if (
            pd.api.types.is_numeric_dtype(first_column)
            and pd.api.types.is_numeric_dtype(second_column)
        ):
            first_values = first_column.to_numpy(dtype=float)
            second_values = second_column.to_numpy(dtype=float)
            equivalent = np.allclose(
                first_values,
                second_values,
                rtol=tolerance,
                atol=tolerance,
                equal_nan=True,
            )
            finite = np.isfinite(first_values) & np.isfinite(second_values)
            if finite.any():
                max_abs_difference = max(
                    max_abs_difference,
                    float(
                        np.max(
                            np.abs(
                                first_values[finite]
                                - second_values[finite]
                            )
                        )
                    ),
                )
        else:
            equivalent = first_column.equals(second_column)

        if not equivalent:
            differing_columns.append(column)

    return (
        first.equals(second),
        not differing_columns,
        differing_columns,
        max_abs_difference,
    )


def compare_named_scenarios(
    portfolio_name: str,
    first_scenario_name: str,
    second_scenario_name: str,
    first_price_paths: Mapping[str, np.ndarray],
    second_price_paths: Mapping[str, np.ndarray],
    first_results: pd.DataFrame,
    second_results: pd.DataFrame,
    tolerance: float = 1e-12,
) -> dict:
    """Compare two named scenarios' price paths and result DataFrames."""
    collateral_types = sorted(
        set(first_price_paths) | set(second_price_paths)
    )
    differing_price_paths = []
    price_paths_numerically_equivalent = True
    price_paths_exactly_identical = True
    max_price_path_difference = 0.0

    for collateral_type in collateral_types:
        if (
            collateral_type not in first_price_paths
            or collateral_type not in second_price_paths
        ):
            differing_price_paths.append(collateral_type)
            price_paths_numerically_equivalent = False
            price_paths_exactly_identical = False
            continue

        first_path = np.asarray(first_price_paths[collateral_type], dtype=float)
        second_path = np.asarray(
            second_price_paths[collateral_type],
            dtype=float,
        )
        exact = np.array_equal(first_path, second_path)
        equivalent = (
            first_path.shape == second_path.shape
            and np.allclose(
                first_path,
                second_path,
                rtol=tolerance,
                atol=tolerance,
            )
        )
        if not exact:
            price_paths_exactly_identical = False
            differing_price_paths.append(collateral_type)
        if not equivalent:
            price_paths_numerically_equivalent = False
        if first_path.shape == second_path.shape:
            max_price_path_difference = max(
                max_price_path_difference,
                float(np.max(np.abs(first_path - second_path))),
            )

    (
        results_exact,
        results_equivalent,
        differing_result_columns,
        max_result_difference,
    ) = _compare_result_frames(
        first_results=first_results,
        second_results=second_results,
        tolerance=tolerance,
    )
    core_outcome_columns = [
        "step",
        "dai_price",
        "total_debt_active",
        "n_liquidatable",
        "confidence_after",
        "regime_after",
        "n_successful_liquidations",
        "debt_repaid_step",
        "bad_debt_realised_step",
        "keeper_profit_step",
    ]
    (
        core_exact,
        core_equivalent,
        differing_core_columns,
        _,
    ) = _compare_result_frames(
        first_results=first_results,
        second_results=second_results,
        tolerance=tolerance,
        columns=core_outcome_columns,
    )

    return {
        "portfolio": portfolio_name,
        "first_scenario": first_scenario_name,
        "second_scenario": second_scenario_name,
        "tolerance": tolerance,
        "price_paths_exactly_identical": price_paths_exactly_identical,
        "price_paths_numerically_equivalent": (
            price_paths_numerically_equivalent
        ),
        "differing_price_paths": ";".join(differing_price_paths),
        "max_price_path_difference": max_price_path_difference,
        "result_frames_exactly_identical": results_exact,
        "result_frames_numerically_equivalent": results_equivalent,
        "differing_result_columns": ";".join(differing_result_columns),
        "max_result_difference": max_result_difference,
        "core_outcomes_exactly_identical": core_exact,
        "core_outcomes_numerically_equivalent": core_equivalent,
        "differing_core_outcome_columns": ";".join(
            differing_core_columns
        ),
    }


def run_scenario_equivalence_diagnostic(
    system_results: pd.DataFrame,
    portfolios: Mapping[str, CollateralPortfolioConfig] | None = None,
    shock_scenarios: Mapping[
        str,
        MultiCollateralShockScenario,
    ] | None = None,
    first_scenario_name: str = "correlated_crypto_crash",
    second_scenario_name: str = "systemic_shock",
    simulation_config: SimulationConfig | None = None,
    shock_time: int = 30,
    tolerance: float = 1e-12,
) -> pd.DataFrame:
    """Compare two saved Experiment 06 scenarios for every portfolio."""
    if portfolios is None:
        portfolios = create_multicollateral_portfolios()
    if shock_scenarios is None:
        shock_scenarios = create_multicollateral_shock_scenarios()
    if simulation_config is None:
        simulation_config = create_base_simulation_config(
            oracle_delay_steps=0,
        )

    first_scenario = shock_scenarios[first_scenario_name]
    second_scenario = shock_scenarios[second_scenario_name]
    records = []

    for portfolio_name, portfolio in portfolios.items():
        first_paths = build_multicollateral_price_paths(
            portfolio=portfolio,
            shock_scenario=first_scenario,
            n_steps=simulation_config.n_steps,
            shock_time=shock_time,
            random_seed=simulation_config.random_seed,
        )
        second_paths = build_multicollateral_price_paths(
            portfolio=portfolio,
            shock_scenario=second_scenario,
            n_steps=simulation_config.n_steps,
            shock_time=shock_time,
            random_seed=simulation_config.random_seed,
        )
        first_results = system_results.loc[
            (system_results["portfolio"] == portfolio_name)
            & (system_results["shock_scenario"] == first_scenario_name)
        ].sort_values("step")
        second_results = system_results.loc[
            (system_results["portfolio"] == portfolio_name)
            & (system_results["shock_scenario"] == second_scenario_name)
        ].sort_values("step")
        if first_results.empty or second_results.empty:
            raise ValueError(
                "System results are missing a scenario required for the "
                f"equivalence diagnostic in portfolio '{portfolio_name}'."
            )

        records.append(
            compare_named_scenarios(
                portfolio_name=portfolio_name,
                first_scenario_name=first_scenario_name,
                second_scenario_name=second_scenario_name,
                first_price_paths=first_paths,
                second_price_paths=second_paths,
                first_results=first_results,
                second_results=second_results,
                tolerance=tolerance,
            )
        )

    return pd.DataFrame(records)


def save_multicollateral_diagnostics(
    diagnostics: Mapping[str, pd.DataFrame],
    output_dir: Path = MULTICOLLATERAL_DIAGNOSTICS_DIR,
) -> dict[str, Path]:
    """Save Milestone 6 diagnostic tables without touching Experiment 06 CSVs."""
    filenames = {
        "stable_depeg_severity": "stable_depeg_severity_sweep.csv",
        "initial_collateral_risk": "initial_collateral_risk.csv",
        "exposure_normalised": "exposure_normalised_metrics.csv",
        "scenario_equivalence": "scenario_equivalence.csv",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {}

    for name, filename in filenames.items():
        path = output_dir / filename
        diagnostics[name].to_csv(path, index=False)
        paths[name] = path

    return paths


def run_multicollateral_diagnostics(
    stable_price_levels: Sequence[float] = (
        1.00,
        0.98,
        0.95,
        0.90,
        0.85,
        0.80,
        0.75,
        0.70,
        0.65,
    ),
    output_dir: Path = MULTICOLLATERAL_DIAGNOSTICS_DIR,
    save_outputs: bool = True,
    tolerance: float = 1e-12,
) -> dict[str, pd.DataFrame]:
    """Build all Milestone 6 diagnostics from existing Experiment 06 outputs."""
    system_path = MULTICOLLATERAL_RESULTS_DIR / "system_results.csv"
    collateral_path = MULTICOLLATERAL_RESULTS_DIR / "collateral_results.csv"
    if not system_path.exists() or not collateral_path.exists():
        raise FileNotFoundError(
            "Experiment 06 detailed outputs are required before diagnostics."
        )

    system_results = pd.read_csv(system_path)
    collateral_results = pd.read_csv(collateral_path)
    portfolios = create_multicollateral_portfolios()
    shock_scenarios = create_multicollateral_shock_scenarios()
    initial_risk = create_initial_collateral_risk_diagnostics(
        portfolios=portfolios
    )
    stable_depeg = run_stable_depeg_severity_diagnostic(
        stable_price_levels=stable_price_levels
    )
    exposure_normalised = compute_exposure_normalised_diagnostics(
        collateral_results=collateral_results,
        initial_risk=initial_risk,
        shock_scenarios=shock_scenarios,
    )
    scenario_equivalence = run_scenario_equivalence_diagnostic(
        system_results=system_results,
        portfolios=portfolios,
        shock_scenarios=shock_scenarios,
        tolerance=tolerance,
    )
    diagnostics = {
        "stable_depeg_severity": stable_depeg,
        "initial_collateral_risk": initial_risk,
        "exposure_normalised": exposure_normalised,
        "scenario_equivalence": scenario_equivalence,
    }

    if save_outputs:
        save_multicollateral_diagnostics(
            diagnostics=diagnostics,
            output_dir=output_dir,
        )

    return diagnostics


if __name__ == "__main__":
    # Run:
    # python src/experiments.py
    diagnostic_results = run_multicollateral_diagnostics()

    first_liquidatable = diagnostic_results[
        "stable_depeg_severity"
    ].loc[lambda frame: frame["first_liquidatable_level"]]
    print("\nFirst liquidatable STABLE sweep levels:")
    print(
        first_liquidatable.loc[
            :,
            [
                "portfolio",
                "stable_price_level",
                "stable_liquidatable_vaults_at_shock",
            ],
        ].to_string(index=False)
    )

    print("\nScenario-equivalence diagnostic:")
    print(
        diagnostic_results["scenario_equivalence"].loc[
            :,
            [
                "portfolio",
                "differing_price_paths",
                "result_frames_exactly_identical",
                "core_outcomes_exactly_identical",
            ],
        ].to_string(index=False)
    )
