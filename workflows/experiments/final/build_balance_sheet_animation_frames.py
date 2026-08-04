"""Build validated Experiment A system and representative-vault frame tables."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
from typing import Any

import numpy as np
import pandas as pd

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)

from dai_sim.experiments.final import (  # noqa: E402
    idiosyncratic_diversification as experiment,
)
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file  # noqa: E402
from workflows.experiments.final.replay_balance_sheet_hourly import (  # noqa: E402
    AUTHORIZED_PORTFOLIOS,
    AUTHORIZED_SHOCK,
    OUTPUT_ROOT as REPLAY_ROOT,
)


OUTPUT_DIR = REPOSITORY_ROOT / "outputs/reporting/final/animations"
DEFAULT_SYSTEM_PATH = OUTPUT_DIR / "balance_sheet_system_frames.csv"
DEFAULT_VAULT_PATH = OUTPUT_DIR / "balance_sheet_vault_frames.csv"
DEFAULT_METADATA_PATH = OUTPUT_DIR / "balance_sheet_animation_frames_metadata.json"
REPLAY_SYSTEM_PATH = REPLAY_ROOT / "balance_sheet_system_hourly.csv"
REPLAY_VAULT_PATH = REPLAY_ROOT / "balance_sheet_vault_hourly.csv"
REPLAY_MANIFEST_PATH = REPLAY_ROOT / "balance_sheet_reporting_replay_manifest.json"
CELL_SUMMARY_PATH = (
    experiment.EVIDENCE_DIR / "idiosyncratic_diversification_cell_summary.csv"
)
FAMILY_X = {"ETH": 0.0, "WBTC": 1.0, "STABLE": 2.0}
ENDPOINT_TOLERANCE = 1e-10
SYSTEM_COLUMNS = (
    "hour",
    "treatment",
    "eth_price_index",
    "wbtc_price_index",
    "stable_price_index",
    "unresolved_debt_share_mean",
    "unresolved_debt_share_p025",
    "unresolved_debt_share_p975",
    "cumulative_liquidated_debt_share_mean",
    "cumulative_liquidated_debt_share_p025",
    "cumulative_liquidated_debt_share_p975",
    "dai_price_mean",
    "dai_price_p025",
    "dai_price_p975",
    "replication_count",
)


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def deterministic_vault_jitter(vault_id: int) -> float:
    digest = hashlib.sha256(
        f"balance-sheet-vault-jitter-v1:{int(vault_id)}".encode()
    ).digest()
    unit = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
    return (unit - 0.5) * 0.34


def _validate_raw_system(frame: pd.DataFrame) -> None:
    expected_rows = (
        experiment.REPLICATIONS * len(AUTHORIZED_PORTFOLIOS) * experiment.TOTAL_HOURS
    )
    if len(frame) != expected_rows:
        raise ValueError(
            f"System hourly row count is {len(frame)}, expected {expected_rows}."
        )
    if set(frame["treatment"].unique()) != set(AUTHORIZED_PORTFOLIOS):
        raise ValueError("System hourly treatments differ from the authorised pair.")
    if set(frame["replication"].unique()) != set(range(experiment.REPLICATIONS)):
        raise ValueError("System hourly table does not contain replications 0--127.")
    counts = frame.groupby(["replication", "treatment"])["hour"].nunique()
    if not counts.eq(experiment.TOTAL_HOURS).all():
        raise ValueError("System hourly time grids are incomplete.")
    numeric = frame.drop(columns=["shock", "treatment"]).to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError("System hourly evidence contains missing or infinite values.")
    for metric in ("eth_price_index", "wbtc_price_index", "stable_price_index"):
        pivot = frame.pivot(
            index=["replication", "hour"], columns="treatment", values=metric
        )
        if not np.array_equal(
            pivot[AUTHORIZED_PORTFOLIOS[0]].to_numpy(),
            pivot[AUTHORIZED_PORTFOLIOS[1]].to_numpy(),
        ):
            raise ValueError(f"Paired treatments received different {metric} paths.")
    for _, selected in frame.groupby(["replication", "treatment"], sort=False):
        cumulative = selected.sort_values("hour")[
            "cumulative_liquidated_debt_share"
        ].to_numpy(dtype=float)
        if np.any(np.diff(cumulative) < -1e-15) or np.any(cumulative < 0.0):
            raise ValueError("Cumulative liquidated debt is negative or decreasing.")


def _aggregate_system(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (treatment, hour), selected in frame.groupby(["treatment", "hour"], sort=True):
        record: dict[str, Any] = {
            "hour": int(hour),
            "treatment": treatment,
            "replication_count": int(selected["replication"].nunique()),
        }
        for metric in ("eth_price_index", "wbtc_price_index", "stable_price_index"):
            record[metric] = float(selected[metric].mean())
        for metric in (
            "unresolved_debt_share",
            "cumulative_liquidated_debt_share",
            "dai_price",
        ):
            values = selected[metric].to_numpy(dtype=float)
            record[f"{metric}_mean"] = float(np.mean(values))
            record[f"{metric}_p025"] = float(np.quantile(values, 0.025))
            record[f"{metric}_p975"] = float(np.quantile(values, 0.975))
        rows.append(record)
    result = pd.DataFrame(rows)
    result = result.loc[:, SYSTEM_COLUMNS].sort_values(
        ["treatment", "hour"], kind="mergesort"
    )
    if not result["replication_count"].eq(experiment.REPLICATIONS).all():
        raise ValueError("An ensemble frame does not use all 128 replications.")
    return result.reset_index(drop=True)


def _post_shock_cumulative_liquidation(frame: pd.DataFrame) -> pd.DataFrame:
    """Align the display path with Experiment A's registered post-shock metric."""
    result = frame.copy()
    baseline = (
        result.loc[result["hour"].eq(experiment.PRE_SHOCK_HOURS - 1)]
        .set_index(["replication", "treatment"])["cumulative_liquidated_debt_share"]
        .to_dict()
    )
    keys = list(zip(result["replication"], result["treatment"], strict=True))
    adjusted = result["cumulative_liquidated_debt_share"].to_numpy(
        dtype=float
    ) - np.array([baseline[key] for key in keys], dtype=float)
    adjusted[result["hour"].to_numpy(dtype=int) < experiment.PRE_SHOCK_HOURS] = 0.0
    if np.any(adjusted < -1e-15):
        raise ValueError("Post-shock cumulative liquidation became negative.")
    result["cumulative_liquidated_debt_share"] = np.maximum(adjusted, 0.0)
    return result


def _prepare_vault(frame: pd.DataFrame, selected_replication: int) -> pd.DataFrame:
    if (
        frame["replication"].nunique() != 1
        or int(frame["replication"].iloc[0]) != selected_replication
    ):
        raise ValueError("Vault table differs from the preselected replication.")
    if set(frame["treatment"].unique()) != set(AUTHORIZED_PORTFOLIOS):
        raise ValueError("Vault table treatments differ from the authorised pair.")
    if not set(frame["collateral_family"].unique()) <= set(FAMILY_X):
        raise ValueError("Vault table contains an unknown collateral family.")
    numeric_columns = (
        "hour",
        "replication",
        "vault_id",
        "vault_debt",
        "collateral_ratio",
        "liquidation_ratio",
        "liquidation_margin",
    )
    if not np.isfinite(frame.loc[:, numeric_columns].to_numpy(dtype=float)).all():
        raise ValueError("Active-vault evidence contains missing or infinite values.")
    canonical_margin = frame["collateral_ratio"] / frame["liquidation_ratio"] - 1.0
    differences = np.abs(canonical_margin - frame["liquidation_margin"])
    if float(differences.max()) > 1e-12:
        raise ValueError("Liquidation margin differs from CR / LR - 1.")
    if (
        not frame["canonical_vault_state"]
        .isin(["safe", "liquidatable_unresolved"])
        .all()
    ):
        raise ValueError("Vault table contains a non-canonical reporting state.")
    result = frame.copy()
    result["x_jitter"] = result["vault_id"].map(deterministic_vault_jitter)
    result["family_x"] = result["collateral_family"].map(FAMILY_X)
    result["scatter_x"] = result["family_x"] + result["x_jitter"]
    maximum_debt = float(result["vault_debt"].max())
    result["point_area"] = 9.0 + 46.0 * np.sqrt(result["vault_debt"] / maximum_debt)
    jitter_counts = result.groupby("vault_id")["x_jitter"].nunique()
    if not jitter_counts.eq(1).all():
        raise ValueError("Vault x-jitter is not stable through time.")
    return result.sort_values(
        ["treatment", "hour", "vault_id"], kind="mergesort"
    ).reset_index(drop=True)


def _registered_mean(summary: pd.DataFrame, treatment: str, metric: str) -> float:
    selected = summary.loc[
        summary["cell_identifier"].eq(f"{AUTHORIZED_SHOCK}__{treatment}")
        & summary["metric"].eq(metric),
        "mean",
    ]
    if len(selected) != 1:
        raise ValueError(f"Missing one registered {treatment}/{metric} mean.")
    return float(selected.iloc[0])


def _reconcile_endpoints(system: pd.DataFrame) -> dict[str, Any]:
    summary = pd.read_csv(CELL_SUMMARY_PATH)
    checks = []
    for treatment in AUTHORIZED_PORTFOLIOS:
        final = system.loc[
            system["treatment"].eq(treatment)
            & system["hour"].eq(experiment.TOTAL_HOURS - 1)
        ].iloc[0]
        for column, metric in (
            ("unresolved_debt_share_mean", "unresolved_tab_share"),
            (
                "cumulative_liquidated_debt_share_mean",
                "liquidated_debt_share",
            ),
        ):
            observed = float(final[column])
            registered = _registered_mean(summary, treatment, metric)
            difference = abs(observed - registered)
            passed = difference <= ENDPOINT_TOLERANCE
            checks.append(
                {
                    "treatment": treatment,
                    "frame_metric": column,
                    "registered_metric": metric,
                    "observed": observed,
                    "registered": registered,
                    "absolute_difference": difference,
                    "passed": passed,
                }
            )
    if not all(check["passed"] for check in checks):
        raise ValueError(f"Aggregate endpoint reconciliation failed: {checks}")
    return {
        "passed": True,
        "absolute_tolerance": ENDPOINT_TOLERANCE,
        "maximum_absolute_difference": max(
            check["absolute_difference"] for check in checks
        ),
        "checks": checks,
    }


def build_frames(
    *,
    replay_system_path: Path = REPLAY_SYSTEM_PATH,
    replay_vault_path: Path = REPLAY_VAULT_PATH,
    replay_manifest_path: Path = REPLAY_MANIFEST_PATH,
    system_output_path: Path = DEFAULT_SYSTEM_PATH,
    vault_output_path: Path = DEFAULT_VAULT_PATH,
    metadata_output_path: Path = DEFAULT_METADATA_PATH,
) -> dict[str, Path]:
    conflicts = [
        path
        for path in (system_output_path, vault_output_path, metadata_output_path)
        if path.exists()
    ]
    if conflicts:
        raise FileExistsError(f"Refusing to overwrite animation frames: {conflicts}")
    replay_manifest = json.loads(replay_manifest_path.read_text())
    selected_replication = int(
        replay_manifest["representative_replication_selection"]["selected_replication"]
    )
    raw_system = pd.read_csv(replay_system_path)
    raw_vault = pd.read_csv(replay_vault_path)
    _validate_raw_system(raw_system)
    raw_system = _post_shock_cumulative_liquidation(raw_system)
    system = _aggregate_system(raw_system)
    vault = _prepare_vault(raw_vault, selected_replication)
    endpoints = _reconcile_endpoints(system)
    price_difference = (
        system.pivot(index="hour", columns="treatment", values="eth_price_index")
        .diff(axis=1)
        .abs()
        .max()
        .max()
    )
    if float(price_difference) != 0.0:
        raise ValueError("Aggregated ETH shock paths differ between treatments.")
    difference = system.pivot(
        index="hour", columns="treatment", values="unresolved_debt_share_mean"
    )
    divergence = (difference["eth_only"] - difference["stable_supported"]).abs()
    representative_hour = int(divergence.idxmax())
    system_output_path.parent.mkdir(parents=True, exist_ok=True)
    experiment._atomic_bytes(
        system_output_path, system.to_csv(index=False).encode("utf-8")
    )
    experiment._atomic_bytes(
        vault_output_path, vault.to_csv(index=False).encode("utf-8")
    )
    metadata = {
        "schema_version": 1,
        "producer": "workflows.experiments.final.build_balance_sheet_animation_frames",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "experiment_id": experiment.EXPERIMENT_ID,
        "experiment_identity": experiment.REGISTERED_EXPERIMENT_IDENTITY,
        "shock": AUTHORIZED_SHOCK,
        "treatments": list(AUTHORIZED_PORTFOLIOS),
        "replication_count": experiment.REPLICATIONS,
        "representative_replication": selected_replication,
        "representative_replication_selection": replay_manifest[
            "representative_replication_selection"
        ],
        "shock_hour": experiment.PRE_SHOCK_HOURS,
        "time_range": [0, experiment.TOTAL_HOURS - 1],
        "aggregation": {
            "centre": "arithmetic mean across registered replications",
            "interval": "pointwise empirical 2.5th and 97.5th percentiles",
            "scientific_smoothing": False,
        },
        "derived_metrics": {
            "price_indexes": "collateral price / replication initial price * 100",
            "unresolved_debt_share": "unresolved_tab_dai / initial system debt",
            "cumulative_liquidated_debt_share": (
                "cumulative sum from registered shock hour 48 of hourly "
                "cleared_tab_dai / initial system debt; derived by subtracting "
                "the retained hour-47 cumulative baseline"
            ),
            "liquidation_margin": "collateral_ratio / liquidation_ratio - 1",
            "vault_jitter": (
                "SHA-256 balance-sheet-vault-jitter-v1:vault_id mapped to [-0.17, 0.17]"
            ),
            "point_area": "9 + 46 * sqrt(vault_debt / maximum active vault debt)",
        },
        "validation": {
            "paired_registered_shock_paths_identical": True,
            "all_replication_time_grids_complete": True,
            "all_values_finite": True,
            "cumulative_liquidated_debt_nonnegative_nondecreasing": True,
            "deterministic_jitter": True,
            "liquidation_margin_tolerance": 1e-12,
            "endpoint_reconciliation": endpoints,
        },
        "representative_static_hour": representative_hour,
        "representative_static_rule": (
            "hour of maximum absolute ensemble-mean unresolved-debt-share difference"
        ),
        "source_paths": [
            {"path": _relative(path), "sha256": sha256_file(path)}
            for path in (
                replay_system_path,
                replay_vault_path,
                replay_manifest_path,
                CELL_SUMMARY_PATH,
            )
        ],
        "outputs": {
            "system_frames": {
                "path": _relative(system_output_path),
                "sha256": sha256_file(system_output_path),
                "rows": len(system),
                "columns": list(system.columns),
            },
            "vault_frames": {
                "path": _relative(vault_output_path),
                "sha256": sha256_file(vault_output_path),
                "rows": len(vault),
                "columns": list(vault.columns),
            },
        },
        "replay_manifest": replay_manifest,
    }
    experiment._atomic_json(metadata_output_path, metadata)
    return {
        "system": system_output_path,
        "vault": vault_output_path,
        "metadata": metadata_output_path,
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-system", type=Path, default=REPLAY_SYSTEM_PATH)
    parser.add_argument("--replay-vault", type=Path, default=REPLAY_VAULT_PATH)
    parser.add_argument("--replay-manifest", type=Path, default=REPLAY_MANIFEST_PATH)
    parser.add_argument("--system-output", type=Path, default=DEFAULT_SYSTEM_PATH)
    parser.add_argument("--vault-output", type=Path, default=DEFAULT_VAULT_PATH)
    parser.add_argument("--metadata-output", type=Path, default=DEFAULT_METADATA_PATH)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        outputs = build_frames(
            replay_system_path=args.replay_system,
            replay_vault_path=args.replay_vault,
            replay_manifest_path=args.replay_manifest,
            system_output_path=args.system_output,
            vault_output_path=args.vault_output,
            metadata_output_path=args.metadata_output,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    for label, path in outputs.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
