"""
metrics.py

Summary metric utilities for the DAI stability simulation.

This module reads experiment outputs and computes clean scenario-level
metrics for reporting and dissertation tables.

Output organisation
-------------------
outputs/results/
    01_baseline_scenarios/
    02_oracle_delay/
    03_shock_severity/
    04_confidence_sensitivity/
    05_peg_recovery/
    06_multicollateral/
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
RESULTS_DIR = OUTPUTS_DIR / "results"

BASELINE_RESULTS_DIR = RESULTS_DIR / "01_baseline_scenarios"
ORACLE_DELAY_RESULTS_DIR = RESULTS_DIR / "02_oracle_delay"
SHOCK_SEVERITY_RESULTS_DIR = RESULTS_DIR / "03_shock_severity"
CONFIDENCE_RESULTS_DIR = RESULTS_DIR / "04_confidence_sensitivity"
PEG_RECOVERY_RESULTS_DIR = RESULTS_DIR / "05_peg_recovery"
MULTICOLLATERAL_RESULTS_DIR = RESULTS_DIR / "06_multicollateral"


EXPERIMENT_DIRS = {
    "baseline": BASELINE_RESULTS_DIR,
    "oracle_delay": ORACLE_DELAY_RESULTS_DIR,
    "shock_severity": SHOCK_SEVERITY_RESULTS_DIR,
    "confidence_sensitivity": CONFIDENCE_RESULTS_DIR,
    "peg_recovery": PEG_RECOVERY_RESULTS_DIR,
    "multicollateral": MULTICOLLATERAL_RESULTS_DIR,
}


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

    Tiny random deviations from the peg are not counted as material depegs.

    Parameters
    ----------
    scenario_name:
        Scenario name.
    results:
        Scenario result DataFrame.
    shock_time:
        ETH shock time.
    peg_price:
        DAI peg price.
    material_depeg_threshold:
        Threshold below which DAI is considered materially below peg.

    Returns
    -------
    dict
        Clean scenario-level metrics.
    """
    if results.empty:
        raise ValueError(f"Results are empty for scenario: {scenario_name}")

    required_columns = {
        "step",
        "dai_price",
        "regime_after",
        "n_vaults_active",
        "n_liquidatable",
        "total_bad_debt_active",
        "keeper_profit_cumulative",
        "bad_debt_realised_cumulative",
        "debt_repaid_cumulative",
        "unprofitable_liquidations_cumulative",
        "capacity_limited_liquidations_cumulative",
    }

    missing_columns = required_columns - set(results.columns)

    if missing_columns:
        raise ValueError(
            f"Scenario '{scenario_name}' is missing required columns: "
            f"{sorted(missing_columns)}"
        )

    results = results.sort_values("step").reset_index(drop=True)

    final = results.iloc[-1]
    post_shock = results.loc[results["step"] >= shock_time].copy()

    if post_shock.empty:
        raise ValueError(
            f"No observations at or after shock_time={shock_time} "
            f"for scenario '{scenario_name}'."
        )

    abs_peg_deviation = (results["dai_price"] - peg_price).abs()
    post_shock_abs_peg_deviation = (
        post_shock["dai_price"] - peg_price
    ).abs()

    material_depeg = (
        post_shock["dai_price"] < material_depeg_threshold
    )
    panic_after_shock = post_shock["regime_after"] == "panic"

    if "market_total_bad_debt_active" in results.columns:
        max_market_bad_debt_active = float(
            results["market_total_bad_debt_active"].max()
        )
        final_market_bad_debt_active = float(
            final["market_total_bad_debt_active"]
        )
    else:
        max_market_bad_debt_active = float(
            results["total_bad_debt_active"].max()
        )
        final_market_bad_debt_active = float(
            final["total_bad_debt_active"]
        )

    if "hidden_bad_debt" in results.columns:
        max_hidden_bad_debt = float(results["hidden_bad_debt"].max())
        final_hidden_bad_debt = float(final["hidden_bad_debt"])
    else:
        max_hidden_bad_debt = 0.0
        final_hidden_bad_debt = 0.0

    return {
        "scenario": scenario_name,
        "final_dai_price": float(final["dai_price"]),
        "min_dai_price": float(results["dai_price"].min()),
        "min_dai_price_post_shock": float(
            post_shock["dai_price"].min()
        ),
        "max_abs_peg_deviation": float(abs_peg_deviation.max()),
        "max_abs_peg_deviation_post_shock": float(
            post_shock_abs_peg_deviation.max()
        ),
        "first_material_depeg_step_post_shock": first_step_condition(
            post_shock,
            material_depeg,
        ),
        "material_depeg_duration_post_shock": int(
            material_depeg.sum()
        ),
        "first_panic_step_post_shock": first_step_condition(
            post_shock,
            panic_after_shock,
        ),
        "panic_duration_post_shock": int(
            panic_after_shock.sum()
        ),
        "final_regime": str(final["regime_after"]),
        "final_active_vaults": int(final["n_vaults_active"]),
        "final_liquidatable_vaults": int(
            final["n_liquidatable"]
        ),
        "final_active_bad_debt": float(
            final["total_bad_debt_active"]
        ),
        "max_market_bad_debt_active": (
            max_market_bad_debt_active
        ),
        "final_market_bad_debt_active": (
            final_market_bad_debt_active
        ),
        "max_hidden_bad_debt": max_hidden_bad_debt,
        "final_hidden_bad_debt": final_hidden_bad_debt,
        "cumulative_keeper_profit": float(
            final["keeper_profit_cumulative"]
        ),
        "cumulative_bad_debt_realised": float(
            final["bad_debt_realised_cumulative"]
        ),
        "cumulative_debt_repaid": float(
            final["debt_repaid_cumulative"]
        ),
        "cumulative_unprofitable_attempts": int(
            final["unprofitable_liquidations_cumulative"]
        ),
        "cumulative_capacity_limited_attempts": int(
            final["capacity_limited_liquidations_cumulative"]
        ),
    }


def build_clean_summary_from_combined_results(
    combined_results: pd.DataFrame,
    shock_time: int = 30,
    peg_price: float = 1.0,
    material_depeg_threshold: float = 0.99,
) -> pd.DataFrame:
    """
    Build a clean summary table from combined scenario results.
    """
    if "scenario" not in combined_results.columns:
        raise ValueError(
            "combined_results must contain a 'scenario' column."
        )

    summary_records = []

    for scenario_name, scenario_df in combined_results.groupby(
        "scenario",
        sort=False,
    ):
        scenario_df = (
            scenario_df
            .sort_values("step")
            .reset_index(drop=True)
        )

        summary_records.append(
            compute_clean_scenario_metrics(
                scenario_name=str(scenario_name),
                results=scenario_df,
                shock_time=shock_time,
                peg_price=peg_price,
                material_depeg_threshold=material_depeg_threshold,
            )
        )

    return pd.DataFrame(summary_records)


def get_experiment_results_dir(
    experiment_name: str,
) -> Path:
    """
    Return the results directory for a named experiment.

    Valid names
    -----------
    baseline
    oracle_delay
    shock_severity
    confidence_sensitivity
    peg_recovery
    multicollateral
    """
    if experiment_name not in EXPERIMENT_DIRS:
        valid_names = ", ".join(EXPERIMENT_DIRS)

        raise ValueError(
            f"Unknown experiment name: '{experiment_name}'. "
            f"Valid names are: {valid_names}."
        )

    return EXPERIMENT_DIRS[experiment_name]


def load_combined_results(
    experiment_name: str = "baseline",
    path: Path | None = None,
) -> pd.DataFrame:
    """
    Load combined results for one experiment.

    Parameters
    ----------
    experiment_name:
        Experiment directory key.
    path:
        Optional explicit path. If provided, it overrides experiment_name.

    Returns
    -------
    pd.DataFrame
        Combined experiment results.
    """
    if path is None:
        experiment_dir = get_experiment_results_dir(
            experiment_name
        )
        path = experiment_dir / "combined_results.csv"

    if not path.exists():
        raise FileNotFoundError(
            f"Could not find combined results file: {path}"
        )

    return pd.read_csv(path)


def save_clean_summary(
    summary_df: pd.DataFrame,
    experiment_name: str = "baseline",
    path: Path | None = None,
) -> Path:
    """
    Save a clean summary table for one experiment.

    Parameters
    ----------
    summary_df:
        Summary DataFrame.
    experiment_name:
        Experiment directory key.
    path:
        Optional explicit save path.

    Returns
    -------
    Path
        Save path.
    """
    if path is None:
        experiment_dir = get_experiment_results_dir(
            experiment_name
        )
        path = experiment_dir / "summary_clean.csv"

    path.parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(path, index=False)

    return path


def build_and_save_clean_summary(
    experiment_name: str = "baseline",
    shock_time: int = 30,
    peg_price: float = 1.0,
    material_depeg_threshold: float = 0.99,
) -> tuple[pd.DataFrame, Path]:
    """
    Load, build and save a clean summary for one experiment.
    """
    combined_results = load_combined_results(
        experiment_name=experiment_name
    )

    summary = build_clean_summary_from_combined_results(
        combined_results=combined_results,
        shock_time=shock_time,
        peg_price=peg_price,
        material_depeg_threshold=material_depeg_threshold,
    )

    save_path = save_clean_summary(
        summary_df=summary,
        experiment_name=experiment_name,
    )

    return summary, save_path


if __name__ == "__main__":
    # Run:
    # python src/metrics.py

    clean_summary, save_path = build_and_save_clean_summary(
        experiment_name="baseline",
        shock_time=30,
        peg_price=1.0,
        material_depeg_threshold=0.99,
    )

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 260)

    print("Clean baseline scenario summary:")
    print(clean_summary)

    print("\nSaved clean summary to:")
    print(save_path)