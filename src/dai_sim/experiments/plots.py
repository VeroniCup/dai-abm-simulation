"""
plot_results.py

Plotting utilities for the DAI stability simulation.

This module creates dissertation-ready figures from saved experiment outputs.

Output organisation
-------------------
    outputs/
        experiments/<experiment>/
        figures/<experiment>/
        tables/<experiment>/
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.image import AxesImage
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

RESULTS_DIR = OUTPUTS_DIR / "experiments"
FIGURES_DIR = OUTPUTS_DIR / "figures"
TABLES_DIR = OUTPUTS_DIR / "tables"

BASELINE_RESULTS_DIR = RESULTS_DIR / "baseline"
ORACLE_DELAY_RESULTS_DIR = RESULTS_DIR / "oracle_delay"
SHOCK_SEVERITY_RESULTS_DIR = RESULTS_DIR / "shock_severity"
CONFIDENCE_RESULTS_DIR = RESULTS_DIR / "confidence"
PEG_RECOVERY_RESULTS_DIR = RESULTS_DIR / "peg_recovery"
MULTICOLLATERAL_RESULTS_DIR = RESULTS_DIR / "multi_collateral"

BASELINE_FIGURES_DIR = FIGURES_DIR / "baseline"
ORACLE_DELAY_FIGURES_DIR = FIGURES_DIR / "oracle_delay"
SHOCK_SEVERITY_FIGURES_DIR = FIGURES_DIR / "shock_severity"
CONFIDENCE_FIGURES_DIR = FIGURES_DIR / "confidence"
PEG_RECOVERY_FIGURES_DIR = FIGURES_DIR / "peg_recovery"
MULTICOLLATERAL_FIGURES_DIR = FIGURES_DIR / "multi_collateral"

BASELINE_TABLES_DIR = TABLES_DIR / "baseline"
ORACLE_DELAY_TABLES_DIR = TABLES_DIR / "oracle_delay"
SHOCK_SEVERITY_TABLES_DIR = TABLES_DIR / "shock_severity"
CONFIDENCE_TABLES_DIR = TABLES_DIR / "confidence"
PEG_RECOVERY_TABLES_DIR = TABLES_DIR / "peg_recovery"
MULTICOLLATERAL_TABLES_DIR = TABLES_DIR / "multi_collateral"


EXPERIMENT_DIRS = {
    "baseline": {
        "results": BASELINE_RESULTS_DIR,
        "figures": BASELINE_FIGURES_DIR,
        "tables": BASELINE_TABLES_DIR,
    },
    "oracle_delay": {
        "results": ORACLE_DELAY_RESULTS_DIR,
        "figures": ORACLE_DELAY_FIGURES_DIR,
        "tables": ORACLE_DELAY_TABLES_DIR,
    },
    "shock_severity": {
        "results": SHOCK_SEVERITY_RESULTS_DIR,
        "figures": SHOCK_SEVERITY_FIGURES_DIR,
        "tables": SHOCK_SEVERITY_TABLES_DIR,
    },
    "confidence_sensitivity": {
        "results": CONFIDENCE_RESULTS_DIR,
        "figures": CONFIDENCE_FIGURES_DIR,
        "tables": CONFIDENCE_TABLES_DIR,
    },
    "peg_recovery": {
        "results": PEG_RECOVERY_RESULTS_DIR,
        "figures": PEG_RECOVERY_FIGURES_DIR,
        "tables": PEG_RECOVERY_TABLES_DIR,
    },
    "multicollateral": {
        "results": MULTICOLLATERAL_RESULTS_DIR,
        "figures": MULTICOLLATERAL_FIGURES_DIR,
        "tables": MULTICOLLATERAL_TABLES_DIR,
    },
}


CONFIDENCE_SCENARIO_ORDER = [
    "resilient_confidence",
    "baseline_confidence",
    "fragile_confidence",
    "panic_sensitive",
    "extreme_confidence_breakdown",
]


# ---------------------------------------------------------------------
# Generic loaders and helpers
# ---------------------------------------------------------------------

def get_experiment_dir(
    experiment_name: str,
    directory_type: str,
) -> Path:
    """
    Return the results or figures directory for an experiment.

    Parameters
    ----------
    experiment_name:
        Experiment key.
    directory_type:
        One of "results", "figures" or "tables".
    """
    if experiment_name not in EXPERIMENT_DIRS:
        valid_names = ", ".join(EXPERIMENT_DIRS)

        raise ValueError(
            f"Unknown experiment name: '{experiment_name}'. "
            f"Valid names are: {valid_names}."
        )

    if directory_type not in {"results", "figures", "tables"}:
        raise ValueError(
            "directory_type must be 'results', 'figures' or 'tables'."
        )

    return EXPERIMENT_DIRS[experiment_name][directory_type]


def load_experiment_results(
    experiment_name: str,
    filename: str = "combined_results.csv",
    path: Path | None = None,
) -> pd.DataFrame:
    """
    Load a results file for one experiment.
    """
    if path is None:
        tables_dir = get_experiment_dir(
            experiment_name,
            directory_type="tables",
        )
        path = tables_dir / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Could not find experiment results file: {path}"
        )

    return pd.read_csv(path)


def load_experiment_summary(
    experiment_name: str,
    filename: str = "summary.csv",
    path: Path | None = None,
) -> pd.DataFrame:
    """
    Load a summary file for one experiment.
    """
    if path is None:
        results_dir = get_experiment_dir(
            experiment_name,
            directory_type="results",
        )
        path = results_dir / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Could not find experiment summary file: {path}"
        )

    return pd.read_csv(path)


def ensure_figure_directory(
    experiment_name: str,
) -> Path:
    """
    Create and return the figure directory for one experiment.
    """
    figure_dir = get_experiment_dir(
        experiment_name,
        directory_type="figures",
    )

    figure_dir.mkdir(parents=True, exist_ok=True)

    return figure_dir


def save_figure(
    fig: plt.Figure,
    save_path: Path,
) -> Path:
    """
    Save and close one Matplotlib figure.
    """
    save_path.parent.mkdir(parents=True, exist_ok=True)

    fig.tight_layout()
    fig.savefig(save_path, dpi=300)
    plt.close(fig)

    return save_path


def order_confidence_scenarios(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Order confidence scenarios from resilient to most fragile.
    """
    ordered = df.copy()

    order_map = {
        name: position
        for position, name in enumerate(CONFIDENCE_SCENARIO_ORDER)
    }

    ordered["confidence_order"] = ordered["scenario"].map(order_map)

    return ordered.sort_values("confidence_order")


def format_scenario_label(
    scenario_name: str,
) -> str:
    """
    Convert an internal scenario name into a readable plot label.
    """
    return scenario_name.replace("_", " ")


# ---------------------------------------------------------------------
# 01 Baseline scenarios
# ---------------------------------------------------------------------

def plot_baseline_dai_price(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot DAI price by baseline scenario.
    """
    if save_path is None:
        save_path = (
            BASELINE_FIGURES_DIR
            / "dai_price_by_scenario.png"
        )

    fig, ax = plt.subplots(figsize=(10, 6))

    for scenario_name, scenario_df in results.groupby(
        "scenario",
        sort=False,
    ):
        scenario_df = scenario_df.sort_values("step")

        ax.plot(
            scenario_df["step"],
            scenario_df["dai_price"],
            label=format_scenario_label(str(scenario_name)),
        )

    ax.axhline(
        1.0,
        linestyle="--",
        linewidth=1,
        label="DAI peg",
    )
    ax.axvline(
        shock_time,
        linestyle=":",
        linewidth=1,
        label="ETH shock",
    )

    ax.set_title("DAI Price under ETH Collateral Shock")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def plot_baseline_active_bad_debt(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot active bad debt by baseline scenario.
    """
    if save_path is None:
        save_path = (
            BASELINE_FIGURES_DIR
            / "active_bad_debt_by_scenario.png"
        )

    bad_debt_column = (
        "market_total_bad_debt_active"
        if "market_total_bad_debt_active" in results.columns
        else "total_bad_debt_active"
    )

    fig, ax = plt.subplots(figsize=(10, 6))

    for scenario_name, scenario_df in results.groupby(
        "scenario",
        sort=False,
    ):
        scenario_df = scenario_df.sort_values("step")

        ax.plot(
            scenario_df["step"],
            scenario_df[bad_debt_column],
            label=format_scenario_label(str(scenario_name)),
        )

    ax.axvline(
        shock_time,
        linestyle=":",
        linewidth=1,
        label="ETH shock",
    )

    ax.set_title("Active Bad Debt under ETH Collateral Shock")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("Active bad debt")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def plot_baseline_liquidatable_vaults(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot liquidatable vaults by baseline scenario.
    """
    if save_path is None:
        save_path = (
            BASELINE_FIGURES_DIR
            / "liquidatable_vaults_by_scenario.png"
        )

    fig, ax = plt.subplots(figsize=(10, 6))

    for scenario_name, scenario_df in results.groupby(
        "scenario",
        sort=False,
    ):
        scenario_df = scenario_df.sort_values("step")

        ax.plot(
            scenario_df["step"],
            scenario_df["n_liquidatable"],
            label=format_scenario_label(str(scenario_name)),
        )

    ax.axvline(
        shock_time,
        linestyle=":",
        linewidth=1,
        label="ETH shock",
    )

    ax.set_title("Liquidatable Vaults under ETH Collateral Shock")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("Number of liquidatable vaults")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def plot_baseline_keeper_profit(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot cumulative keeper profit by baseline scenario.
    """
    if save_path is None:
        save_path = (
            BASELINE_FIGURES_DIR
            / "keeper_profit_by_scenario.png"
        )

    fig, ax = plt.subplots(figsize=(10, 6))

    for scenario_name, scenario_df in results.groupby(
        "scenario",
        sort=False,
    ):
        scenario_df = scenario_df.sort_values("step")

        ax.plot(
            scenario_df["step"],
            scenario_df["keeper_profit_cumulative"],
            label=format_scenario_label(str(scenario_name)),
        )

    ax.axvline(
        shock_time,
        linestyle=":",
        linewidth=1,
        label="ETH shock",
    )

    ax.set_title(
        "Cumulative Keeper Profit under ETH Collateral Shock"
    )
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("Cumulative keeper profit")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def create_baseline_figures(
    results: pd.DataFrame,
    shock_time: int = 30,
) -> list[Path]:
    """
    Create all baseline scenario figures.
    """
    ensure_figure_directory("baseline")

    return [
        plot_baseline_dai_price(
            results,
            shock_time=shock_time,
        ),
        plot_baseline_active_bad_debt(
            results,
            shock_time=shock_time,
        ),
        plot_baseline_liquidatable_vaults(
            results,
            shock_time=shock_time,
        ),
        plot_baseline_keeper_profit(
            results,
            shock_time=shock_time,
        ),
    ]


# ---------------------------------------------------------------------
# 02 Oracle delay
# ---------------------------------------------------------------------

def plot_hidden_bad_debt_by_oracle_delay(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot hidden bad debt over time by oracle delay.
    """
    if save_path is None:
        save_path = (
            ORACLE_DELAY_FIGURES_DIR
            / "hidden_bad_debt_by_oracle_delay.png"
        )

    fig, ax = plt.subplots(figsize=(10, 6))

    scenario_order = (
        results[
            [
                "scenario",
                "oracle_delay_steps_experiment",
            ]
        ]
        .drop_duplicates()
        .sort_values("oracle_delay_steps_experiment")
    )

    for _, row in scenario_order.iterrows():
        scenario_name = row["scenario"]
        delay = int(row["oracle_delay_steps_experiment"])

        scenario_df = (
            results.loc[results["scenario"] == scenario_name]
            .sort_values("step")
        )

        ax.plot(
            scenario_df["step"],
            scenario_df["hidden_bad_debt"],
            label=f"Delay = {delay}",
        )

    ax.axvline(
        shock_time,
        linestyle=":",
        linewidth=1,
        label="ETH shock",
    )

    ax.set_title("Hidden Bad Debt under Oracle Delay")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("Hidden bad debt")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def plot_final_dai_price_by_oracle_delay(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot final DAI price by oracle delay.
    """
    if save_path is None:
        save_path = (
            ORACLE_DELAY_FIGURES_DIR
            / "final_dai_price_by_oracle_delay.png"
        )

    summary = summary.sort_values("oracle_delay_steps")

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.plot(
        summary["oracle_delay_steps"],
        summary["final_dai_price"],
        marker="o",
    )

    ax.axhline(
        1.0,
        linestyle="--",
        linewidth=1,
        label="DAI peg",
    )

    ax.set_title("Final DAI Price by Oracle Delay")
    ax.set_xlabel("Oracle delay steps")
    ax.set_ylabel("Final DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def plot_hidden_bad_debt_duration_by_oracle_delay(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot hidden bad debt duration by oracle delay.
    """
    if save_path is None:
        save_path = (
            ORACLE_DELAY_FIGURES_DIR
            / "hidden_bad_debt_duration_by_oracle_delay.png"
        )

    summary = summary.sort_values("oracle_delay_steps")

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.bar(
        summary["oracle_delay_steps"].astype(str),
        summary["hidden_bad_debt_duration"],
    )

    ax.set_title("Hidden Bad Debt Duration by Oracle Delay")
    ax.set_xlabel("Oracle delay steps")
    ax.set_ylabel("Duration with hidden bad debt")
    ax.grid(True, axis="y", alpha=0.3)

    return save_figure(fig, save_path)


def create_oracle_delay_figures(
    results: pd.DataFrame,
    summary: pd.DataFrame,
    shock_time: int = 30,
) -> list[Path]:
    """
    Create all oracle-delay figures.
    """
    ensure_figure_directory("oracle_delay")

    return [
        plot_hidden_bad_debt_by_oracle_delay(
            results,
            shock_time=shock_time,
        ),
        plot_final_dai_price_by_oracle_delay(summary),
        plot_hidden_bad_debt_duration_by_oracle_delay(summary),
    ]


# ---------------------------------------------------------------------
# 03 Shock severity
# ---------------------------------------------------------------------

def plot_dai_price_by_shock_severity(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot DAI price over time by ETH shock severity.
    """
    if save_path is None:
        save_path = (
            SHOCK_SEVERITY_FIGURES_DIR
            / "dai_price_by_shock_severity.png"
        )

    fig, ax = plt.subplots(figsize=(10, 6))

    scenario_order = (
        results[
            [
                "scenario",
                "shock_size_experiment",
            ]
        ]
        .drop_duplicates()
        .sort_values(
            "shock_size_experiment",
            ascending=False,
        )
    )

    for _, row in scenario_order.iterrows():
        scenario_name = row["scenario"]
        shock_size = float(row["shock_size_experiment"])

        scenario_df = (
            results.loc[results["scenario"] == scenario_name]
            .sort_values("step")
        )

        ax.plot(
            scenario_df["step"],
            scenario_df["dai_price"],
            label=f"{abs(shock_size):.0%} shock",
        )

    ax.axhline(
        1.0,
        linestyle="--",
        linewidth=1,
        label="DAI peg",
    )
    ax.axvline(
        shock_time,
        linestyle=":",
        linewidth=1,
        label="ETH shock",
    )

    ax.set_title(
        "DAI Price under Different ETH Shock Severities"
    )
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def plot_final_dai_price_by_shock_severity(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot final DAI price by shock severity.
    """
    if save_path is None:
        save_path = (
            SHOCK_SEVERITY_FIGURES_DIR
            / "final_dai_price_by_shock_severity.png"
        )

    summary = summary.sort_values(
        "shock_size",
        ascending=False,
    )

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.plot(
        summary["shock_size"].abs() * 100,
        summary["final_dai_price"],
        marker="o",
    )

    ax.axhline(
        1.0,
        linestyle="--",
        linewidth=1,
        label="DAI peg",
    )

    ax.set_title("Final DAI Price by ETH Shock Severity")
    ax.set_xlabel("ETH shock size (%)")
    ax.set_ylabel("Final DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def plot_max_bad_debt_by_shock_severity(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot maximum active bad debt by shock severity.
    """
    if save_path is None:
        save_path = (
            SHOCK_SEVERITY_FIGURES_DIR
            / "max_bad_debt_by_shock_severity.png"
        )

    summary = summary.sort_values(
        "shock_size",
        ascending=False,
    )

    shock_labels = (
        summary["shock_size"]
        .abs()
        .mul(100)
        .astype(int)
        .astype(str)
    )

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.bar(
        shock_labels,
        summary["max_market_bad_debt_active"],
    )

    ax.set_title(
        "Maximum Active Bad Debt by ETH Shock Severity"
    )
    ax.set_xlabel("ETH shock size (%)")
    ax.set_ylabel("Maximum active bad debt")
    ax.grid(True, axis="y", alpha=0.3)

    return save_figure(fig, save_path)


def plot_realised_bad_debt_by_shock_severity(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot cumulative realised bad debt by shock severity.
    """
    if save_path is None:
        save_path = (
            SHOCK_SEVERITY_FIGURES_DIR
            / "realised_bad_debt_by_shock_severity.png"
        )

    summary = summary.sort_values(
        "shock_size",
        ascending=False,
    )

    shock_labels = (
        summary["shock_size"]
        .abs()
        .mul(100)
        .astype(int)
        .astype(str)
    )

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.bar(
        shock_labels,
        summary["cumulative_bad_debt_realised"],
    )

    ax.set_title(
        "Cumulative Realised Bad Debt by ETH Shock Severity"
    )
    ax.set_xlabel("ETH shock size (%)")
    ax.set_ylabel("Cumulative realised bad debt")
    ax.grid(True, axis="y", alpha=0.3)

    return save_figure(fig, save_path)


def create_shock_severity_figures(
    results: pd.DataFrame,
    summary: pd.DataFrame,
    shock_time: int = 30,
) -> list[Path]:
    """
    Create all shock-severity figures.
    """
    ensure_figure_directory("shock_severity")

    return [
        plot_dai_price_by_shock_severity(
            results,
            shock_time=shock_time,
        ),
        plot_final_dai_price_by_shock_severity(summary),
        plot_max_bad_debt_by_shock_severity(summary),
        plot_realised_bad_debt_by_shock_severity(summary),
    ]


# ---------------------------------------------------------------------
# 04 Confidence sensitivity
# ---------------------------------------------------------------------

def plot_dai_price_by_confidence_sensitivity(
    results: pd.DataFrame,
    shock_time: int = 30,
    save_path: Path | None = None,
) -> Path:
    """
    Plot DAI price by confidence scenario.
    """
    if save_path is None:
        save_path = (
            CONFIDENCE_FIGURES_DIR
            / "dai_price_by_confidence_sensitivity.png"
        )

    scenario_order = order_confidence_scenarios(
        results[["scenario"]].drop_duplicates()
    )

    fig, ax = plt.subplots(figsize=(10, 6))

    for scenario_name in scenario_order["scenario"]:
        scenario_df = (
            results.loc[results["scenario"] == scenario_name]
            .sort_values("step")
        )

        ax.plot(
            scenario_df["step"],
            scenario_df["dai_price"],
            label=format_scenario_label(scenario_name),
        )

    ax.axhline(
        1.0,
        linestyle="--",
        linewidth=1,
        label="DAI peg",
    )
    ax.axvline(
        shock_time,
        linestyle=":",
        linewidth=1,
        label="ETH shock",
    )

    ax.set_title(
        "DAI Price under Different Confidence Assumptions"
    )
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def plot_final_dai_price_by_confidence_sensitivity(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot final DAI price by confidence scenario.
    """
    if save_path is None:
        save_path = (
            CONFIDENCE_FIGURES_DIR
            / "final_dai_price_by_confidence_sensitivity.png"
        )

    summary = order_confidence_scenarios(summary)

    labels = summary["scenario"].str.replace(
        "_",
        "\n",
        regex=False,
    )

    fig, ax = plt.subplots(figsize=(10, 5))

    ax.bar(
        labels,
        summary["final_dai_price"],
    )

    y_min = max(
        0.0,
        float(summary["final_dai_price"].min()) - 0.03,
    )

    ax.set_ylim(y_min, 1.01)

    ax.axhline(
        1.0,
        linestyle="--",
        linewidth=1,
        label="DAI peg",
    )

    ax.set_title("Final DAI Price by Confidence Scenario")
    ax.set_xlabel("Confidence scenario")
    ax.set_ylabel("Final DAI price")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)

    return save_figure(fig, save_path)


def plot_material_depeg_duration_by_confidence(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot material depeg duration by confidence scenario.
    """
    if save_path is None:
        save_path = (
            CONFIDENCE_FIGURES_DIR
            / "material_depeg_duration_by_confidence_sensitivity.png"
        )

    summary = order_confidence_scenarios(summary)

    labels = summary["scenario"].str.replace(
        "_",
        "\n",
        regex=False,
    )

    fig, ax = plt.subplots(figsize=(10, 5))

    ax.bar(
        labels,
        summary["material_depeg_duration"],
    )

    ax.set_title(
        "Material Depeg Duration by Confidence Scenario"
    )
    ax.set_xlabel("Confidence scenario")
    ax.set_ylabel("Steps with DAI below 0.99")
    ax.grid(True, axis="y", alpha=0.3)

    return save_figure(fig, save_path)


def plot_mean_confidence_by_scenario(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot mean confidence level by confidence scenario.
    """
    if save_path is None:
        save_path = (
            CONFIDENCE_FIGURES_DIR
            / "mean_confidence_by_confidence_sensitivity.png"
        )

    summary = order_confidence_scenarios(summary)

    labels = summary["scenario"].str.replace(
        "_",
        "\n",
        regex=False,
    )

    fig, ax = plt.subplots(figsize=(10, 5))

    ax.bar(
        labels,
        summary["mean_confidence_after"],
    )

    ax.set_title(
        "Mean Confidence Level by Confidence Scenario"
    )
    ax.set_xlabel("Confidence scenario")
    ax.set_ylabel("Mean confidence level")
    ax.grid(True, axis="y", alpha=0.3)

    return save_figure(fig, save_path)


def create_confidence_figures(
    results: pd.DataFrame,
    summary: pd.DataFrame,
    shock_time: int = 30,
) -> list[Path]:
    """
    Create all confidence-sensitivity figures.
    """
    ensure_figure_directory("confidence_sensitivity")

    return [
        plot_dai_price_by_confidence_sensitivity(
            results,
            shock_time=shock_time,
        ),
        plot_final_dai_price_by_confidence_sensitivity(summary),
        plot_material_depeg_duration_by_confidence(summary),
        plot_mean_confidence_by_scenario(summary),
    ]


# ---------------------------------------------------------------------
# 05 Peg recovery
# ---------------------------------------------------------------------

def plot_dai_price_by_recovery_fraction(
    results: pd.DataFrame,
    shock_time: int = 30,
    recovery_start: int = 40,
    save_path: Path | None = None,
) -> Path:
    """
    Plot DAI price by ETH recovery fraction.
    """
    if save_path is None:
        save_path = (
            PEG_RECOVERY_FIGURES_DIR
            / "dai_price_by_recovery_fraction.png"
        )

    scenario_order = (
        results[
            [
                "scenario",
                "recovery_fraction_experiment",
            ]
        ]
        .drop_duplicates()
        .sort_values("recovery_fraction_experiment")
    )

    fig, ax = plt.subplots(figsize=(10, 6))

    for _, row in scenario_order.iterrows():
        scenario_name = row["scenario"]
        recovery_fraction = float(
            row["recovery_fraction_experiment"]
        )

        scenario_df = (
            results.loc[results["scenario"] == scenario_name]
            .sort_values("step")
        )

        ax.plot(
            scenario_df["step"],
            scenario_df["dai_price"],
            label=f"{recovery_fraction:.0%} recovery",
        )

    ax.axhline(
        1.0,
        linestyle="--",
        linewidth=1,
        label="DAI peg",
    )
    ax.axhline(
        0.995,
        linestyle="--",
        linewidth=1,
        label="Full-recovery threshold",
    )
    ax.axvline(
        shock_time,
        linestyle=":",
        linewidth=1,
        label="ETH shock",
    )
    ax.axvline(
        recovery_start,
        linestyle="-.",
        linewidth=1,
        label="ETH recovery begins",
    )

    ax.set_title("DAI Price under Different ETH Recovery Paths")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def plot_eth_price_by_recovery_fraction(
    results: pd.DataFrame,
    shock_time: int = 30,
    recovery_start: int = 40,
    save_path: Path | None = None,
) -> Path:
    """
    Plot ETH price paths used in the recovery experiment.
    """
    if save_path is None:
        save_path = (
            PEG_RECOVERY_FIGURES_DIR
            / "eth_price_by_recovery_fraction.png"
        )

    scenario_order = (
        results[
            [
                "scenario",
                "recovery_fraction_experiment",
            ]
        ]
        .drop_duplicates()
        .sort_values("recovery_fraction_experiment")
    )

    fig, ax = plt.subplots(figsize=(10, 6))

    for _, row in scenario_order.iterrows():
        scenario_name = row["scenario"]
        recovery_fraction = float(
            row["recovery_fraction_experiment"]
        )

        scenario_df = (
            results.loc[results["scenario"] == scenario_name]
            .sort_values("step")
        )

        ax.plot(
            scenario_df["step"],
            scenario_df["market_eth_price"],
            label=f"{recovery_fraction:.0%} recovery",
        )

    ax.axvline(
        shock_time,
        linestyle=":",
        linewidth=1,
        label="ETH shock",
    )
    ax.axvline(
        recovery_start,
        linestyle="-.",
        linewidth=1,
        label="ETH recovery begins",
    )

    ax.set_title("ETH Price Paths in Peg Recovery Experiment")
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("ETH price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def plot_final_dai_price_by_recovery_fraction(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot final DAI price by recovery fraction.
    """
    if save_path is None:
        save_path = (
            PEG_RECOVERY_FIGURES_DIR
            / "final_dai_price_by_recovery_fraction.png"
        )

    summary = summary.sort_values("recovery_fraction")

    x_values = summary["recovery_fraction"] * 100

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.plot(
        x_values,
        summary["final_dai_price"],
        marker="o",
    )

    for x_value, y_value in zip(
            x_values,
            summary["final_dai_price"],
    ):
        ax.annotate(
            f"{y_value:.4f}",
            (x_value, y_value),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
        )

    ax.axhline(
        1.0,
        linestyle="--",
        linewidth=1,
        label="DAI peg",
    )

    y_min = max(
        0.0,
        float(summary["final_dai_price"].min()) - 0.003,
    )
    ax.set_ylim(y_min, 1.001)

    ax.set_title("Final DAI Price by ETH Recovery Fraction")
    ax.set_xlabel("Recovered fraction of ETH price loss (%)")
    ax.set_ylabel("Final DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(fig, save_path)


def plot_full_system_recovery_step(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot the first full-system recovery step.

    Scenarios that do not recover are shown with an explicit marker and
    a 'Not reached' annotation rather than a zero-height bar.
    """
    if save_path is None:
        save_path = (
            PEG_RECOVERY_FIGURES_DIR
            / "full_system_recovery_step.png"
        )

    summary = (
        summary
        .sort_values("recovery_fraction")
        .reset_index(drop=True)
    )

    labels = (
        summary["recovery_fraction"]
        .mul(100)
        .astype(int)
        .astype(str)
        + "%"
    )

    recovery_column = "first_full_system_recovery_995_step"
    x_positions = list(range(len(summary)))

    fig, ax = plt.subplots(figsize=(8, 5))

    successful_steps = summary[recovery_column].dropna()

    if successful_steps.empty:
        y_min = 0
        y_max = 100
    else:
        y_min = max(
            0,
            int(successful_steps.min()) - 15,
        )
        y_max = int(successful_steps.max()) + 8

    annotation_y = y_min + 2

    for x_position, recovery_step in zip(
        x_positions,
        summary[recovery_column],
    ):
        if pd.isna(recovery_step):
            ax.scatter(
                x_position,
                annotation_y,
                marker="x",
                s=80,
                linewidths=2,
            )

            ax.annotate(
                "Not reached",
                xy=(x_position, annotation_y),
                xytext=(0, 10),
                textcoords="offset points",
                ha="center",
                va="bottom",
            )
        else:
            bar = ax.bar(
                x_position,
                recovery_step,
                width=0.8,
            )[0]

            ax.annotate(
                f"{int(recovery_step)}",
                xy=(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height(),
                ),
                xytext=(0, 7),
                textcoords="offset points",
                ha="center",
                va="bottom",
            )

    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels)
    ax.set_ylim(y_min, y_max)

    ax.set_title(
        "First Full System Recovery Step by ETH Recovery Fraction"
    )
    ax.set_xlabel(
        "Recovered fraction of ETH price loss"
    )
    ax.set_ylabel("Simulation step")
    ax.grid(True, axis="y", alpha=0.3)

    return save_figure(fig, save_path)


def plot_realised_bad_debt_by_recovery_fraction(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot cumulative realised bad debt by recovery fraction.
    """
    if save_path is None:
        save_path = (
            PEG_RECOVERY_FIGURES_DIR
            / "realised_bad_debt_by_recovery_fraction.png"
        )

    summary = summary.sort_values("recovery_fraction")

    labels = (
        summary["recovery_fraction"]
        .mul(100)
        .astype(int)
        .astype(str)
        + "%"
    )

    fig, ax = plt.subplots(figsize=(8, 5))

    bars = ax.bar(
        labels,
        summary["cumulative_bad_debt_realised"],
    )

    for bar, value in zip(
            bars,
            summary["cumulative_bad_debt_realised"],
    ):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{value:,.0f}",
            ha="center",
            va="bottom",
        )

    ax.set_ylim(
        0,
        summary["cumulative_bad_debt_realised"].max() * 1.08,
    )

    ax.set_title(
        "Cumulative Realised Bad Debt by ETH Recovery Fraction"
    )
    ax.set_xlabel("Recovered fraction of ETH price loss")
    ax.set_ylabel("Cumulative realised bad debt")
    ax.grid(True, axis="y", alpha=0.3)

    return save_figure(fig, save_path)


def plot_regime_duration_by_recovery_fraction(
    summary: pd.DataFrame,
    save_path: Path | None = None,
) -> Path:
    """
    Plot post-shock regime composition by recovery fraction.

    Panic, stress and normal durations are stacked so that each bar shows
    how the fixed post-shock simulation horizon is distributed across
    confidence regimes.
    """
    if save_path is None:
        save_path = (
            PEG_RECOVERY_FIGURES_DIR
            / "regime_duration_by_recovery_fraction.png"
        )

    summary = (
        summary
        .sort_values("recovery_fraction")
        .reset_index(drop=True)
    )

    labels = (
        summary["recovery_fraction"]
        .mul(100)
        .astype(int)
        .astype(str)
        + "%"
    )

    panic = summary["panic_duration"]
    stress = summary["stress_duration"]
    normal = summary["normal_duration"]

    fig, ax = plt.subplots(figsize=(10, 5))

    panic_bars = ax.bar(
        labels,
        panic,
        label="Panic",
    )

    stress_bars = ax.bar(
        labels,
        stress,
        bottom=panic,
        label="Stress",
    )

    normal_bars = ax.bar(
        labels,
        normal,
        bottom=panic + stress,
        label="Normal",
    )

    for bar, value in zip(panic_bars, panic):
        if value > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value / 2,
                f"{int(value)}",
                ha="center",
                va="center",
            )

    for bar, panic_value, stress_value in zip(
        stress_bars,
        panic,
        stress,
    ):
        if stress_value > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                panic_value + stress_value / 2,
                f"{int(stress_value)}",
                ha="center",
                va="center",
            )

    for bar, panic_value, stress_value, normal_value in zip(
        normal_bars,
        panic,
        stress,
        normal,
    ):
        if normal_value > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                panic_value + stress_value + normal_value / 2,
                f"{int(normal_value)}",
                ha="center",
                va="center",
            )

    total_post_shock_steps = (
        panic + stress + normal
    ).max()

    ax.set_ylim(
        0,
        total_post_shock_steps * 1.04,
    )

    ax.set_title(
        "Post-Shock Regime Duration by ETH Recovery Fraction"
    )
    ax.set_xlabel(
        "Recovered fraction of ETH price loss"
    )
    ax.set_ylabel(
        "Number of simulation steps"
    )
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)

    return save_figure(fig, save_path)


def create_peg_recovery_figures(
    results: pd.DataFrame,
    summary: pd.DataFrame,
    shock_time: int = 30,
    recovery_start: int = 40,
) -> list[Path]:
    """
    Create all peg-recovery figures.
    """
    ensure_figure_directory("peg_recovery")

    return [
        plot_dai_price_by_recovery_fraction(
            results,
            shock_time=shock_time,
            recovery_start=recovery_start,
        ),
        plot_eth_price_by_recovery_fraction(
            results,
            shock_time=shock_time,
            recovery_start=recovery_start,
        ),
        plot_final_dai_price_by_recovery_fraction(summary),
        plot_full_system_recovery_step(summary),
        plot_realised_bad_debt_by_recovery_fraction(summary),
        plot_regime_duration_by_recovery_fraction(summary),
    ]


# ---------------------------------------------------------------------
# 06 Multi-collateral portfolios
# ---------------------------------------------------------------------

def _heatmap_annotation_colour(
    image: AxesImage,
    value: float,
) -> str:
    """Return black or white, whichever contrasts most with the cell colour."""
    red, green, blue, _ = image.to_rgba(value)

    def linearise(channel: float) -> float:
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    luminance = (
        0.2126 * linearise(float(red))
        + 0.7152 * linearise(float(green))
        + 0.0722 * linearise(float(blue))
    )
    black_contrast = (luminance + 0.05) / 0.05
    white_contrast = 1.05 / (luminance + 0.05)

    return "black" if black_contrast >= white_contrast else "white"

def _plot_multicollateral_summary_heatmap(
    summary: pd.DataFrame,
    value_column: str,
    title: str,
    colourbar_label: str,
    value_format: str,
    save_path: Path,
) -> Path:
    """Plot a generic portfolio-by-shock summary heatmap."""
    portfolio_order = list(dict.fromkeys(summary["portfolio"].astype(str)))
    shock_order = list(dict.fromkeys(summary["shock_scenario"].astype(str)))
    matrix = summary.pivot(
        index="portfolio",
        columns="shock_scenario",
        values=value_column,
    ).reindex(index=portfolio_order, columns=shock_order)

    fig, ax = plt.subplots(figsize=(12, 6.5))
    image = ax.imshow(matrix.to_numpy(dtype=float), aspect="auto", cmap="viridis")
    colourbar = fig.colorbar(image, ax=ax)
    colourbar.set_label(colourbar_label)

    ax.set_xticks(range(len(shock_order)))
    ax.set_xticklabels(
        [format_scenario_label(name) for name in shock_order],
        rotation=25,
        ha="right",
    )
    ax.set_yticks(range(len(portfolio_order)))
    ax.set_yticklabels(
        [format_scenario_label(name) for name in portfolio_order]
    )

    for row_index, portfolio in enumerate(portfolio_order):
        for column_index, shock_scenario in enumerate(shock_order):
            value = float(matrix.loc[portfolio, shock_scenario])
            ax.text(
                column_index,
                row_index,
                f"{value:{value_format}}",
                ha="center",
                va="center",
                color=_heatmap_annotation_colour(image, value),
                fontsize=8,
            )

    ax.set_title(title)
    ax.set_xlabel("Shock scenario")
    ax.set_ylabel("Collateral portfolio")

    return save_figure(fig, save_path)


def plot_multicollateral_peak_peg_deviation(
    system_summary: pd.DataFrame,
    figure_dir: Path = MULTICOLLATERAL_FIGURES_DIR,
) -> Path:
    """Plot peak absolute peg deviation across the experiment grid."""
    return _plot_multicollateral_summary_heatmap(
        summary=system_summary,
        value_column="peak_peg_deviation",
        title="Peak DAI Peg Deviation by Portfolio and Shock",
        colourbar_label="Peak absolute peg deviation",
        value_format=".4f",
        save_path=figure_dir / "peak_peg_deviation_heatmap.png",
    )


def plot_multicollateral_realised_bad_debt(
    system_summary: pd.DataFrame,
    figure_dir: Path = MULTICOLLATERAL_FIGURES_DIR,
) -> Path:
    """Plot realised bad debt across the experiment grid."""
    return _plot_multicollateral_summary_heatmap(
        summary=system_summary,
        value_column="realised_bad_debt",
        title="Realised Bad Debt by Portfolio and Shock",
        colourbar_label="Realised bad debt (DAI)",
        value_format=",.0f",
        save_path=figure_dir / "realised_bad_debt_heatmap.png",
    )


def plot_multicollateral_dai_price(
    system_results: pd.DataFrame,
    shock_scenario: str = "systemic_shock",
    shock_time: int = 30,
    figure_dir: Path = MULTICOLLATERAL_FIGURES_DIR,
) -> Path:
    """Plot DAI price paths by portfolio for one shock scenario."""
    selected = system_results.loc[
        system_results["shock_scenario"] == shock_scenario
    ]
    if selected.empty:
        raise ValueError(
            f"No system results found for shock scenario '{shock_scenario}'."
        )

    fig, ax = plt.subplots(figsize=(10, 6))
    for portfolio, portfolio_results in selected.groupby(
        "portfolio",
        sort=False,
    ):
        portfolio_results = portfolio_results.sort_values("step")
        ax.plot(
            portfolio_results["step"],
            portfolio_results["dai_price"],
            label=format_scenario_label(str(portfolio)),
        )

    ax.axhline(1.0, linestyle="--", linewidth=1, color="black", label="DAI peg")
    ax.axvline(shock_time, linestyle=":", linewidth=1, color="grey")
    ax.set_title(
        "DAI Price by Collateral Portfolio under Systemic Shock"
    )
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("DAI price")
    ax.legend()
    ax.grid(True, alpha=0.3)

    return save_figure(
        fig,
        figure_dir / "dai_price_systemic_shock.png",
    )


def plot_multicollateral_bad_debt_by_collateral(
    collateral_summary: pd.DataFrame,
    shock_scenario: str = "systemic_shock",
    figure_dir: Path = MULTICOLLATERAL_FIGURES_DIR,
) -> Path:
    """Plot dynamically grouped collateral bad debt for one shock scenario."""
    selected = collateral_summary.loc[
        collateral_summary["shock_scenario"] == shock_scenario
    ]
    if selected.empty:
        raise ValueError(
            f"No collateral summary found for shock scenario '{shock_scenario}'."
        )

    portfolio_order = list(dict.fromkeys(selected["portfolio"].astype(str)))
    collateral_order = list(
        dict.fromkeys(selected["collateral_type"].astype(str))
    )
    matrix = selected.pivot(
        index="portfolio",
        columns="collateral_type",
        values="realised_bad_debt",
    ).reindex(index=portfolio_order, columns=collateral_order).fillna(0.0)

    fig, ax = plt.subplots(figsize=(10, 6))
    matrix.plot(kind="bar", stacked=True, ax=ax)
    ax.set_title("Realised Bad Debt Composition under Systemic Shock")
    ax.set_xlabel("Collateral portfolio")
    ax.set_ylabel("Realised bad debt (DAI)")
    ax.set_xticklabels(
        [format_scenario_label(name) for name in portfolio_order],
        rotation=20,
        ha="right",
    )
    ax.legend(title="Collateral type")
    ax.grid(True, axis="y", alpha=0.3)

    return save_figure(
        fig,
        figure_dir / "collateral_bad_debt_systemic_shock.png",
    )


def create_multicollateral_figures(
    system_results: pd.DataFrame,
    system_summary: pd.DataFrame,
    collateral_summary: pd.DataFrame,
    shock_time: int = 30,
    figure_dir: Path = MULTICOLLATERAL_FIGURES_DIR,
) -> list[Path]:
    """Create all Experiment 06 dissertation figures."""
    figure_dir.mkdir(parents=True, exist_ok=True)

    return [
        plot_multicollateral_peak_peg_deviation(
            system_summary,
            figure_dir=figure_dir,
        ),
        plot_multicollateral_realised_bad_debt(
            system_summary,
            figure_dir=figure_dir,
        ),
        plot_multicollateral_dai_price(
            system_results,
            shock_time=shock_time,
            figure_dir=figure_dir,
        ),
        plot_multicollateral_bad_debt_by_collateral(
            collateral_summary,
            figure_dir=figure_dir,
        ),
    ]


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def create_all_experiment_figures(
    shock_time: int = 30,
    recovery_start: int = 40,
) -> list[Path]:
    """
    Load all completed experiment outputs and create all figures.
    """
    all_paths: list[Path] = []

    baseline_results = load_experiment_results("baseline")
    all_paths.extend(
        create_baseline_figures(
            baseline_results,
            shock_time=shock_time,
        )
    )

    oracle_results = load_experiment_results("oracle_delay")
    oracle_summary = load_experiment_summary("oracle_delay")
    all_paths.extend(
        create_oracle_delay_figures(
            oracle_results,
            oracle_summary,
            shock_time=shock_time,
        )
    )

    shock_results = load_experiment_results("shock_severity")
    shock_summary = load_experiment_summary("shock_severity")
    all_paths.extend(
        create_shock_severity_figures(
            shock_results,
            shock_summary,
            shock_time=shock_time,
        )
    )

    confidence_results = load_experiment_results(
        "confidence_sensitivity"
    )
    confidence_summary = load_experiment_summary(
        "confidence_sensitivity"
    )
    all_paths.extend(
        create_confidence_figures(
            confidence_results,
            confidence_summary,
            shock_time=shock_time,
        )
    )

    recovery_results = load_experiment_results("peg_recovery")
    recovery_summary = load_experiment_summary("peg_recovery")
    all_paths.extend(
        create_peg_recovery_figures(
            recovery_results,
            recovery_summary,
            shock_time=shock_time,
            recovery_start=recovery_start,
        )
    )

    return all_paths


if __name__ == "__main__":
    paths = create_all_experiment_figures(
        shock_time=30,
        recovery_start=40,
    )

    print("Saved figures:")

    for path in paths:
        print(path)
