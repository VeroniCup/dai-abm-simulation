"""
plot_results.py

Plotting utilities for the DAI stability simulation.

This module creates dissertation-ready figures from saved experiment outputs.

Figures:
- DAI price by scenario;
- active bad debt by scenario;
- liquidatable vaults by scenario;
- cumulative keeper profit by scenario.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "outputs" / "results"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"


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
        Combined results DataFrame.
    """
    if path is None:
        path = RESULTS_DIR / "combined_results.csv"

    if not path.exists():
        raise FileNotFoundError(f"Could not find results file: {path}")

    return pd.read_csv(path)


def plot_dai_price(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot DAI price by scenario.

    Parameters
    ----------
    results:
        Combined scenario results.
    shock_time:
        ETH shock time.
    save_path:
        Optional save path.

    Returns
    -------
    Path
        Saved figure path.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "dai_price_by_scenario.png"

    fig, ax = plt.subplots(figsize=(10, 6))

    for scenario_name, scenario_df in results.groupby("scenario"):
        scenario_df = scenario_df.sort_values("step")
        ax.plot(
            scenario_df["step"],
            scenario_df["dai_price"],
            label=scenario_name,
        )

    ax.axhline(1.0, linestyle="--", linewidth=1, label="DAI peg")
    ax.axvline(shock_time, linestyle=":", linewidth=1, label="ETH shock")

    ax.set_title("DAI Price under ETH Collateral Shock")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_active_bad_debt(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot active bad debt by scenario.

    Parameters
    ----------
    results:
        Combined scenario results.
    shock_time:
        ETH shock time.
    save_path:
        Optional save path.

    Returns
    -------
    Path
        Saved figure path.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "active_bad_debt_by_scenario.png"

    fig, ax = plt.subplots(figsize=(10, 6))

    for scenario_name, scenario_df in results.groupby("scenario"):
        scenario_df = scenario_df.sort_values("step")
        ax.plot(
            scenario_df["step"],
            scenario_df["total_bad_debt_active"],
            label=scenario_name,
        )

    ax.axvline(shock_time, linestyle=":", linewidth=1, label="ETH shock")

    ax.set_title("Active Bad Debt under ETH Collateral Shock")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("Active bad debt")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_liquidatable_vaults(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot number of liquidatable vaults by scenario.

    Parameters
    ----------
    results:
        Combined scenario results.
    shock_time:
        ETH shock time.
    save_path:
        Optional save path.

    Returns
    -------
    Path
        Saved figure path.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "liquidatable_vaults_by_scenario.png"

    fig, ax = plt.subplots(figsize=(10, 6))

    for scenario_name, scenario_df in results.groupby("scenario"):
        scenario_df = scenario_df.sort_values("step")
        ax.plot(
            scenario_df["step"],
            scenario_df["n_liquidatable"],
            label=scenario_name,
        )

    ax.axvline(shock_time, linestyle=":", linewidth=1, label="ETH shock")

    ax.set_title("Liquidatable Vaults under ETH Collateral Shock")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("Number of liquidatable vaults")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_keeper_profit(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot cumulative keeper profit by scenario.

    Parameters
    ----------
    results:
        Combined scenario results.
    shock_time:
        ETH shock time.
    save_path:
        Optional save path.

    Returns
    -------
    Path
        Saved figure path.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "keeper_profit_by_scenario.png"

    fig, ax = plt.subplots(figsize=(10, 6))

    for scenario_name, scenario_df in results.groupby("scenario"):
        scenario_df = scenario_df.sort_values("step")
        ax.plot(
            scenario_df["step"],
            scenario_df["keeper_profit_cumulative"],
            label=scenario_name,
        )

    ax.axvline(shock_time, linestyle=":", linewidth=1, label="ETH shock")

    ax.set_title("Cumulative Keeper Profit under ETH Collateral Shock")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("Cumulative keeper profit")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def create_all_figures(
    results: pd.DataFrame,
    shock_time: int = 30,
) -> list[Path]:
    """
    Create all standard result figures.

    Parameters
    ----------
    results:
        Combined scenario results.
    shock_time:
        ETH shock time.

    Returns
    -------
    list[Path]
        Saved figure paths.
    """
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    figure_paths = [
        plot_dai_price(results, shock_time=shock_time),
        plot_active_bad_debt(results, shock_time=shock_time),
        plot_liquidatable_vaults(results, shock_time=shock_time),
        plot_keeper_profit(results, shock_time=shock_time),
    ]

    return figure_paths


def load_oracle_delay_results(
    path: Path | None = None,
) -> pd.DataFrame:
    """
    Load combined oracle-delay experiment results.

    Parameters
    ----------
    path:
        Optional path to oracle_delay_combined_results.csv.

    Returns
    -------
    pd.DataFrame
        Oracle-delay combined results.
    """
    if path is None:
        path = RESULTS_DIR / "oracle_delay_combined_results.csv"

    if not path.exists():
        raise FileNotFoundError(f"Could not find oracle-delay results file: {path}")

    return pd.read_csv(path)


def load_oracle_delay_summary(
    path: Path | None = None,
) -> pd.DataFrame:
    """
    Load oracle-delay summary results.

    Parameters
    ----------
    path:
        Optional path to oracle_delay_summary.csv.

    Returns
    -------
    pd.DataFrame
        Oracle-delay summary table.
    """
    if path is None:
        path = RESULTS_DIR / "oracle_delay_summary.csv"

    if not path.exists():
        raise FileNotFoundError(f"Could not find oracle-delay summary file: {path}")

    return pd.read_csv(path)


def plot_hidden_bad_debt_by_oracle_delay(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot hidden bad debt over time by oracle-delay scenario.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "hidden_bad_debt_by_oracle_delay.png"

    fig, ax = plt.subplots(figsize=(10, 6))

    scenario_order = (
        results[["scenario", "oracle_delay_steps_experiment"]]
        .drop_duplicates()
        .sort_values("oracle_delay_steps_experiment")
    )

    for _, row in scenario_order.iterrows():
        scenario_name = row["scenario"]
        delay = int(row["oracle_delay_steps_experiment"])

        scenario_df = results[results["scenario"] == scenario_name].sort_values("step")

        ax.plot(
            scenario_df["step"],
            scenario_df["hidden_bad_debt"],
            label=f"delay = {delay}",
        )

    ax.axvline(shock_time, linestyle=":", linewidth=1, label="ETH shock")

    ax.set_title("Hidden Bad Debt under Oracle Delay")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("Hidden bad debt")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_final_dai_price_by_oracle_delay(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot final DAI price by oracle delay.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "final_dai_price_by_oracle_delay.png"

    fig, ax = plt.subplots(figsize=(8, 5))

    summary = summary.sort_values("oracle_delay_steps")

    ax.plot(
        summary["oracle_delay_steps"],
        summary["final_dai_price"],
        marker="o",
    )

    ax.axhline(1.0, linestyle="--", linewidth=1, label="DAI peg")

    ax.set_title("Final DAI Price by Oracle Delay")
    ax.set_xlabel("Oracle delay steps")
    ax.set_ylabel("Final DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_hidden_bad_debt_duration_by_oracle_delay(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot hidden bad debt duration by oracle delay.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "hidden_bad_debt_duration_by_oracle_delay.png"

    fig, ax = plt.subplots(figsize=(8, 5))

    summary = summary.sort_values("oracle_delay_steps")

    ax.bar(
        summary["oracle_delay_steps"].astype(str),
        summary["hidden_bad_debt_duration"],
    )

    ax.set_title("Hidden Bad Debt Duration by Oracle Delay")
    ax.set_xlabel("Oracle delay steps")
    ax.set_ylabel("Duration with hidden bad debt")

    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def create_oracle_delay_figures(
    oracle_results: pd.DataFrame,
    oracle_summary: pd.DataFrame,
    shock_time: int = 30,
) -> list[Path]:
    """
    Create all oracle-delay result figures.
    """
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    figure_paths = [
        plot_hidden_bad_debt_by_oracle_delay(
            oracle_results,
            shock_time=shock_time,
        ),
        plot_final_dai_price_by_oracle_delay(
            oracle_summary,
        ),
        plot_hidden_bad_debt_duration_by_oracle_delay(
            oracle_summary,
        ),
    ]

    return figure_paths


def load_shock_severity_results(
    path: Path | None = None,
) -> pd.DataFrame:
    """
    Load combined shock-severity experiment results.
    """
    if path is None:
        path = RESULTS_DIR / "shock_severity_combined_results.csv"

    if not path.exists():
        raise FileNotFoundError(f"Could not find shock-severity results file: {path}")

    return pd.read_csv(path)


def load_shock_severity_summary(
    path: Path | None = None,
) -> pd.DataFrame:
    """
    Load shock-severity summary results.
    """
    if path is None:
        path = RESULTS_DIR / "shock_severity_summary.csv"

    if not path.exists():
        raise FileNotFoundError(f"Could not find shock-severity summary file: {path}")

    return pd.read_csv(path)


def plot_dai_price_by_shock_severity(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot DAI price over time for different ETH shock severities.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "dai_price_by_shock_severity.png"

    fig, ax = plt.subplots(figsize=(10, 6))

    scenario_order = (
        results[["scenario", "shock_size_experiment"]]
        .drop_duplicates()
        .sort_values("shock_size_experiment", ascending=False)
    )

    for _, row in scenario_order.iterrows():
        scenario_name = row["scenario"]
        shock_size = row["shock_size_experiment"]

        scenario_df = results[results["scenario"] == scenario_name].sort_values("step")

        ax.plot(
            scenario_df["step"],
            scenario_df["dai_price"],
            label=f"{abs(shock_size):.0%} shock",
        )

    ax.axhline(1.0, linestyle="--", linewidth=1, label="DAI peg")
    ax.axvline(shock_time, linestyle=":", linewidth=1, label="ETH shock")

    ax.set_title("DAI Price under Different ETH Shock Severities")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_final_dai_price_by_shock_severity(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot final DAI price by ETH shock severity.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "final_dai_price_by_shock_severity.png"

    summary = summary.sort_values("shock_size", ascending=False)

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.plot(
        summary["shock_size"].abs() * 100,
        summary["final_dai_price"],
        marker="o",
    )

    ax.axhline(1.0, linestyle="--", linewidth=1, label="DAI peg")

    ax.set_title("Final DAI Price by ETH Shock Severity")
    ax.set_xlabel("ETH shock size (%)")
    ax.set_ylabel("Final DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_max_bad_debt_by_shock_severity(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot maximum active bad debt by ETH shock severity.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "max_bad_debt_by_shock_severity.png"

    summary = summary.sort_values("shock_size", ascending=False)

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.bar(
        summary["shock_size"].abs().mul(100).astype(int).astype(str),
        summary["max_market_bad_debt_active"],
    )

    ax.set_title("Maximum Active Bad Debt by ETH Shock Severity")
    ax.set_xlabel("ETH shock size (%)")
    ax.set_ylabel("Maximum active bad debt")
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_realised_bad_debt_by_shock_severity(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot cumulative realised bad debt by ETH shock severity.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "realised_bad_debt_by_shock_severity.png"

    summary = summary.sort_values("shock_size", ascending=False)

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.bar(
        summary["shock_size"].abs().mul(100).astype(int).astype(str),
        summary["cumulative_bad_debt_realised"],
    )

    ax.set_title("Cumulative Realised Bad Debt by ETH Shock Severity")
    ax.set_xlabel("ETH shock size (%)")
    ax.set_ylabel("Cumulative realised bad debt")
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def create_shock_severity_figures(
    shock_results: pd.DataFrame,
    shock_summary: pd.DataFrame,
    shock_time: int = 30,
) -> list[Path]:
    """
    Create all shock-severity result figures.
    """
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    figure_paths = [
        plot_dai_price_by_shock_severity(
            shock_results,
            shock_time=shock_time,
        ),
        plot_final_dai_price_by_shock_severity(
            shock_summary,
        ),
        plot_max_bad_debt_by_shock_severity(
            shock_summary,
        ),
        plot_realised_bad_debt_by_shock_severity(
            shock_summary,
        ),
    ]

    return figure_paths


CONFIDENCE_SCENARIO_ORDER = [
    "resilient_confidence",
    "baseline_confidence",
    "fragile_confidence",
    "panic_sensitive",
    "extreme_confidence_breakdown",
]


def order_confidence_scenarios(df: pd.DataFrame) -> pd.DataFrame:
    """
    Order confidence scenarios from resilient to most fragile.
    """
    ordered = df.copy()
    ordered["confidence_order"] = ordered["scenario"].map(
        {name: i for i, name in enumerate(CONFIDENCE_SCENARIO_ORDER)}
    )
    return ordered.sort_values("confidence_order")


def load_confidence_sensitivity_results(
    path: Path | None = None,
) -> pd.DataFrame:
    """
    Load combined confidence-sensitivity experiment results.
    """
    if path is None:
        path = RESULTS_DIR / "confidence_sensitivity_combined_results.csv"

    if not path.exists():
        raise FileNotFoundError(
            f"Could not find confidence-sensitivity results file: {path}"
        )

    return pd.read_csv(path)


def load_confidence_sensitivity_summary(
    path: Path | None = None,
) -> pd.DataFrame:
    """
    Load confidence-sensitivity summary results.
    """
    if path is None:
        path = RESULTS_DIR / "confidence_sensitivity_summary.csv"

    if not path.exists():
        raise FileNotFoundError(
            f"Could not find confidence-sensitivity summary file: {path}"
        )

    return pd.read_csv(path)


def plot_dai_price_by_confidence_sensitivity(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot DAI price over time across confidence-sensitivity scenarios.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "dai_price_by_confidence_sensitivity.png"

    fig, ax = plt.subplots(figsize=(10, 6))

    scenario_order = order_confidence_scenarios(
        results[["scenario"]].drop_duplicates()
    )

    for scenario_name in scenario_order["scenario"]:
        scenario_df = results[results["scenario"] == scenario_name].sort_values("step")

        label = scenario_name.replace("_", " ")

        ax.plot(
            scenario_df["step"],
            scenario_df["dai_price"],
            label=label,
        )

    ax.axhline(1.0, linestyle="--", linewidth=1, label="DAI peg")
    ax.axvline(shock_time, linestyle=":", linewidth=1, label="ETH shock")

    ax.set_title("DAI Price under Different Confidence Assumptions")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_final_dai_price_by_confidence_sensitivity(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot final DAI price across confidence-sensitivity scenarios.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "final_dai_price_by_confidence_sensitivity.png"

    summary = order_confidence_scenarios(summary)

    fig, ax = plt.subplots(figsize=(10, 5))

    labels = summary["scenario"].str.replace("_", "\n")

    ax.bar(
        labels,
        summary["final_dai_price"],
    )

    ax.set_ylim(0.70, 1.01)
    ax.axhline(1.0, linestyle="--", linewidth=1, label="DAI peg")

    ax.set_title("Final DAI Price by Confidence Scenario")
    ax.set_xlabel("Confidence scenario")
    ax.set_ylabel("Final DAI price")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_material_depeg_duration_by_confidence_sensitivity(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot duration of material below-peg deviation by confidence scenario.
    """
    if save_path is None:
        save_path = (
            FIGURES_DIR / "material_depeg_duration_by_confidence_sensitivity.png"
        )

    summary = order_confidence_scenarios(summary)

    fig, ax = plt.subplots(figsize=(10, 5))

    labels = summary["scenario"].str.replace("_", "\n")

    ax.bar(
        labels,
        summary["material_depeg_duration"],
    )

    ax.set_title("Material Depeg Duration by Confidence Scenario")
    ax.set_xlabel("Confidence scenario")
    ax.set_ylabel("Steps with DAI below 0.99")
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_panic_duration_by_confidence_sensitivity(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot panic-regime duration by confidence scenario.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "panic_duration_by_confidence_sensitivity.png"

    summary = order_confidence_scenarios(summary)

    fig, ax = plt.subplots(figsize=(10, 5))

    labels = summary["scenario"].str.replace("_", "\n")

    ax.bar(
        labels,
        summary["panic_duration"],
    )

    ax.set_title("Panic Regime Duration by Confidence Scenario")
    ax.set_xlabel("Confidence scenario")
    ax.set_ylabel("Steps in panic regime")
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def plot_mean_confidence_by_confidence_sensitivity(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot mean confidence level by confidence scenario.
    """
    if save_path is None:
        save_path = FIGURES_DIR / "mean_confidence_by_confidence_sensitivity.png"

    summary = order_confidence_scenarios(summary)

    fig, ax = plt.subplots(figsize=(10, 5))

    labels = summary["scenario"].str.replace("_", "\n")

    ax.bar(
        labels,
        summary["mean_confidence_after"],
    )

    ax.set_title("Mean Confidence Level by Confidence Scenario")
    ax.set_xlabel("Confidence scenario")
    ax.set_ylabel("Mean confidence level")
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def create_confidence_sensitivity_figures(
    confidence_results: pd.DataFrame,
    confidence_summary: pd.DataFrame,
    shock_time: int = 30,
) -> list[Path]:
    """
    Create all confidence-sensitivity figures.
    """
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    figure_paths = [
        plot_dai_price_by_confidence_sensitivity(
            confidence_results,
            shock_time=shock_time,
        ),
        plot_final_dai_price_by_confidence_sensitivity(
            confidence_summary,
        ),
        plot_material_depeg_duration_by_confidence_sensitivity(
            confidence_summary,
        ),
        plot_mean_confidence_by_confidence_sensitivity(
            confidence_summary,
        ),
    ]

    return figure_paths


if __name__ == "__main__":
    # Run:
    # python src/plot_results.py

    paths = []

    combined_results = load_combined_results()
    paths.extend(create_all_figures(combined_results, shock_time=30))

    oracle_results = load_oracle_delay_results()
    oracle_summary = load_oracle_delay_summary()
    paths.extend(
        create_oracle_delay_figures(
            oracle_results=oracle_results,
            oracle_summary=oracle_summary,
            shock_time=30,
        )
    )

    shock_results = load_shock_severity_results()
    shock_summary = load_shock_severity_summary()
    paths.extend(
        create_shock_severity_figures(
            shock_results=shock_results,
            shock_summary=shock_summary,
            shock_time=30,
        )
    )

    confidence_results = load_confidence_sensitivity_results()
    confidence_summary = load_confidence_sensitivity_summary()
    paths.extend(
        create_confidence_sensitivity_figures(
            confidence_results=confidence_results,
            confidence_summary=confidence_summary,
            shock_time=30,
        )
    )

    print("Saved figures:")
    for path in paths:
        print(path)