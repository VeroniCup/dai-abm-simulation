"""Summary-table construction and reconciliation for simulation experiments."""

from __future__ import annotations

import numpy as np
import pandas as pd


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

def compute_multicollateral_system_summary(
    system_results: pd.DataFrame,
) -> pd.DataFrame:
    """Build one system summary row per portfolio and shock scenario."""
    summary_records = []

    for (portfolio, shock_scenario), run_results in system_results.groupby(
        ["portfolio", "shock_scenario"],
        sort=False,
    ):
        run_results = run_results.sort_values("step")
        final = run_results.iloc[-1]
        peg_deviation = run_results["dai_price"] - 1.0
        realised_bad_debt = float(final["bad_debt_realised_cumulative"])
        final_active_bad_debt = float(final["total_bad_debt_active"])

        summary_records.append(
            {
                "portfolio": str(portfolio),
                "shock_scenario": str(shock_scenario),
                "peak_peg_deviation": float(peg_deviation.abs().max()),
                "final_peg_deviation": float(peg_deviation.iloc[-1]),
                "final_abs_peg_deviation": float(abs(peg_deviation.iloc[-1])),
                "final_active_bad_debt": final_active_bad_debt,
                "cumulative_bad_debt": (
                    final_active_bad_debt + realised_bad_debt
                ),
                "realised_bad_debt": realised_bad_debt,
                "cumulative_debt_repaid": float(
                    final["debt_repaid_cumulative"]
                ),
                "keeper_profit": float(final["keeper_profit_cumulative"]),
                "liquidation_volume": float(
                    final["collateral_liquidated_cumulative"]
                ),
                "successful_liquidations": int(
                    run_results["n_successful_liquidations"].sum()
                ),
                "final_active_debt": float(final["total_debt_active"]),
            }
        )

    return pd.DataFrame(summary_records)

def compute_multicollateral_collateral_summary(
    collateral_results: pd.DataFrame,
) -> pd.DataFrame:
    """Build long-format collateral summaries for every experiment run."""
    summary_records = []

    for (
        portfolio,
        shock_scenario,
        collateral_type,
    ), run_results in collateral_results.groupby(
        ["portfolio", "shock_scenario", "collateral_type"],
        sort=False,
    ):
        run_results = run_results.sort_values("step")
        final = run_results.iloc[-1]

        summary_records.append(
            {
                "portfolio": str(portfolio),
                "shock_scenario": str(shock_scenario),
                "collateral_type": str(collateral_type),
                "active_debt": float(final["active_debt"]),
                "peak_active_debt": float(run_results["active_debt"].max()),
                "realised_bad_debt": float(
                    run_results["realised_bad_debt"].sum()
                ),
                "liquidations": int(
                    run_results["successful_liquidations"].sum()
                ),
                "keeper_profit": float(run_results["keeper_profit"].sum()),
                "debt_repaid": float(run_results["debt_repaid"].sum()),
            }
        )

    return pd.DataFrame(summary_records)

def validate_multicollateral_results(
    system_results: pd.DataFrame,
    collateral_results: pd.DataFrame,
    system_summary: pd.DataFrame,
    collateral_summary: pd.DataFrame,
) -> None:
    """Validate detailed and summary reconciliation for every experiment run."""
    step_fields = {
        "realised_bad_debt": "bad_debt_realised_step",
        "debt_repaid": "debt_repaid_step",
        "keeper_profit": "keeper_profit_step",
        "successful_liquidations": "n_successful_liquidations",
    }

    for (portfolio, shock_scenario), system_run in system_results.groupby(
        ["portfolio", "shock_scenario"],
        sort=False,
    ):
        collateral_run = collateral_results.loc[
            (collateral_results["portfolio"] == portfolio)
            & (collateral_results["shock_scenario"] == shock_scenario)
        ]
        collateral_by_step = collateral_run.groupby("step", sort=True).sum(
            numeric_only=True
        )
        system_by_step = system_run.sort_values("step").set_index("step")

        for collateral_field, system_field in step_fields.items():
            if not np.allclose(
                collateral_by_step[collateral_field],
                system_by_step[system_field],
            ):
                raise ValueError(
                    "Collateral results do not reconcile for "
                    f"{portfolio}/{shock_scenario}: {collateral_field}."
                )

        system_summary_row = system_summary.loc[
            (system_summary["portfolio"] == portfolio)
            & (system_summary["shock_scenario"] == shock_scenario)
        ].iloc[0]
        collateral_summary_rows = collateral_summary.loc[
            (collateral_summary["portfolio"] == portfolio)
            & (collateral_summary["shock_scenario"] == shock_scenario)
        ]
        summary_fields = {
            "realised_bad_debt": "realised_bad_debt",
            "debt_repaid": "cumulative_debt_repaid",
            "keeper_profit": "keeper_profit",
            "liquidations": "successful_liquidations",
            "active_debt": "final_active_debt",
        }

        for collateral_field, system_field in summary_fields.items():
            if not np.isclose(
                collateral_summary_rows[collateral_field].sum(),
                system_summary_row[system_field],
            ):
                raise ValueError(
                    "Collateral summary does not reconcile for "
                    f"{portfolio}/{shock_scenario}: {collateral_field}."
                )
