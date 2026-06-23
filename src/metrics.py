"""
metrics.py

Summary metric utilities for the DAI stability simulation.

This module reads scenario simulation outputs and computes cleaner
scenario-level metrics for reporting and dissertation tables.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "outputs" / "results"


def first_step_condition(
    results: pd.DataFrame,
    condition: pd.Series,
) -> int | None:
    """
    Return the first simulation step satisfying a condition.

    Parameters
    ----------
    results:
        Simulation result DataFrame.
    condition:
        Boolean Series aligned with results.

    Returns
    -------
    int | None
        First step satisfying the condition, or None if never satisfied.
    """
    if condition.any():
        return int(results.loc[condition, "step"].iloc[0])
    return None


def compute_clean_scenario_metrics(
    scenario_name: str,
    results: pd.DataFrame,
    shock_time: int = 30,
    peg_price: float = 1.0,
    material_depeg_threshold: float = 0.99,
) -> dict:
    """
    Compute clean scenario-level metrics.

    Compared with the first experiment summary, this version avoids treating
    tiny random noise as meaningful depegging.

    Parameters
    ----------
    scenario_name:
        Scenario name.
    results:
        Scenario result DataFrame.
    shock_time:
        ETH shock time. Used to compute post-shock metrics.
    peg_price:
        DAI peg price.
    material_depeg_threshold:
        Threshold below which DAI is considered materially below peg.
        Example: 0.99 means more than 1% below peg.

    Returns
    -------
    dict
        Clean scenario-level metrics.
    """
    final = results.iloc[-1]
    post_shock = results[results["step"] >= shock_time].copy()

    abs_peg_deviation = (results["dai_price"] - peg_price).abs()
    post_shock_abs_peg_deviation = (post_shock["dai_price"] - peg_price).abs()

    material_depeg = post_shock["dai_price"] < material_depeg_threshold
    panic_after_shock = post_shock["regime_after"] == "panic"

    return {
        "scenario": scenario_name,
        "final_dai_price": float(final["dai_price"]),
        "min_dai_price": float(results["dai_price"].min()),
        "min_dai_price_post_shock": float(post_shock["dai_price"].min()),
        "max_abs_peg_deviation": float(abs_peg_deviation.max()),
        "max_abs_peg_deviation_post_shock": float(
            post_shock_abs_peg_deviation.max()
        ),
        "first_material_depeg_step_post_shock": first_step_condition(
            post_shock, material_depeg
        ),
        "first_panic_step_post_shock": first_step_condition(
            post_shock, panic_after_shock
        ),
        "final_regime": final["regime_after"],
        "final_active_vaults": int(final["n_vaults_active"]),
        "final_liquidatable_vaults": int(final["n_liquidatable"]),
        "final_active_bad_debt": float(final["total_bad_debt_active"]),
        "cumulative_keeper_profit": float(final["keeper_profit_cumulative"]),
        "cumulative_bad_debt_realised": float(final["bad_debt_realised_cumulative"]),
        "cumulative_debt_repaid": float(final["debt_repaid_cumulative"]),
        "cumulative_unprofitable_attempts": int(final["unprofitable_liquidations_cumulative"]),
        "cumulative_capacity_limited_attempts": int(final["capacity_limited_liquidations_cumulative"]),
    }


def build_clean_summary_from_combined_results(
    combined_results: pd.DataFrame,
    shock_time: int = 30,
    peg_price: float = 1.0,
    material_depeg_threshold: float = 0.99,
) -> pd.DataFrame:
    """
    Build clean summary table from combined scenario results.

    Parameters
    ----------
    combined_results:
        Combined result DataFrame containing a scenario column.
    shock_time:
        ETH shock time.
    peg_price:
        DAI peg price.
    material_depeg_threshold:
        Material depeg threshold.

    Returns
    -------
    pd.DataFrame
        Clean scenario summary table.
    """
    if "scenario" not in combined_results.columns:
        raise ValueError("combined_results must contain a 'scenario' column.")

    summary_records = []

    for scenario_name, scenario_df in combined_results.groupby("scenario"):
        scenario_df = scenario_df.sort_values("step").reset_index(drop=True)

        summary_records.append(
            compute_clean_scenario_metrics(
                scenario_name=scenario_name,
                results=scenario_df,
                shock_time=shock_time,
                peg_price=peg_price,
                material_depeg_threshold=material_depeg_threshold,
            )
        )

    return pd.DataFrame(summary_records)


def load_combined_results(
    path: Path | None = None,
) -> pd.DataFrame:
    """
    Load combined simulation results.

    Parameters
    ----------
    path:
        Optional path to combined_results.csv.

    Returns
    -------
    pd.DataFrame
        Combined results.
    """
    if path is None:
        path = RESULTS_DIR / "combined_results.csv"

    if not path.exists():
        raise FileNotFoundError(f"Could not find results file: {path}")

    return pd.read_csv(path)


def save_clean_summary(
    summary_df: pd.DataFrame,
    path: Path | None = None,
) -> Path:
    """
    Save clean summary table.

    Parameters
    ----------
    summary_df:
        Summary DataFrame.
    path:
        Optional save path.

    Returns
    -------
    Path
        Save path.
    """
    if path is None:
        path = RESULTS_DIR / "scenario_summary_clean.csv"

    path.parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(path, index=False)

    return path


if __name__ == "__main__":
    # Run:
    # python src/metrics.py

    combined = load_combined_results()

    clean_summary = build_clean_summary_from_combined_results(
        combined_results=combined,
        shock_time=30,
        peg_price=1.0,
        material_depeg_threshold=0.99,
    )

    save_path = save_clean_summary(clean_summary)

    print("Clean scenario summary:")
    print(clean_summary)

    print("\nSaved clean summary to:")
    print(save_path)