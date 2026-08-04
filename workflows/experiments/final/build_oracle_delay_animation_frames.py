"""Prepare animation frames from frozen Experiment E hourly evidence.

This workflow is deliberately reporting-only.  It never imports or calls the
Experiment E simulator.  The compact registered checkpoints currently retain
scalar summaries; a valid input must additionally contain the hourly arrays
produced by the frozen run (either as a CSV or embedded checkpoint payloads).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


REPOSITORY_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").is_file() and (parent / "src" / "dai_sim").is_dir()
)
EXPERIMENT_ID = "E_oracle_delay"
EXPERIMENT_IDENTITY = "67ec5a1e03492608c7f847861f7dbd506d2a526dbf4107298241b26c855eb0f8"
ANCHOR = "empirical_crypto__joint_crypto_high_correlation"
PORTFOLIO = "empirical_crypto"
SHOCK = "joint_crypto_high_correlation"
DELAY_TO_TREATMENT = {
    0: "oracle_delay_low",
    1: "oracle_delay_central",
    2: "oracle_delay_high",
}
DEFAULT_SOURCE = (
    REPOSITORY_ROOT
    / "outputs"
    / "experiments"
    / "final"
    / "oracle_delay"
    / EXPERIMENT_IDENTITY
)
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "outputs" / "reporting" / "final" / "animations"
DEFAULT_FRAME_PATH = DEFAULT_OUTPUT_DIR / "oracle_delay_animation_frames.csv"
DEFAULT_METADATA_PATH = (
    DEFAULT_OUTPUT_DIR / "oracle_delay_animation_frames_metadata.json"
)
CELL_SUMMARY_PATH = (
    REPOSITORY_ROOT
    / "data"
    / "provenance"
    / "experiments"
    / "final"
    / "oracle_delay"
    / "oracle_delay_cell_summary.csv"
)
SPECIFICATION_PATH = CELL_SUMMARY_PATH.with_name("oracle_delay_specification.json")
DECISION_PATH = CELL_SUMMARY_PATH.with_name("oracle_delay_decision.json")

CANONICAL_COLUMNS = (
    "replication",
    "hour",
    "delay_hours",
    "market_unsafe_debt",
    "oracle_unsafe_debt",
    "false_safe_debt",
    "dai_price",
)
ALIASES = {
    "step": "hour",
    "oracle_delay_hours": "delay_hours",
    "oracle_delay_steps": "delay_hours",
    "market_unsafe_debt_dai": "market_unsafe_debt",
    "oracle_unsafe_debt_dai": "oracle_unsafe_debt",
    "false_safe_debt_dai": "false_safe_debt",
}


class MissingHourlyEvidenceError(RuntimeError):
    """Raised when compact evidence exists but hourly paths were not retained."""


@dataclass(frozen=True)
class ExperimentContract:
    replications: int = 128
    total_hours: int = 768
    pre_shock_hours: int = 48
    total_debt_dai: float = 2_500_000.0
    delays: tuple[int, ...] = (0, 1, 2)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    renamed = frame.rename(
        columns={key: value for key, value in ALIASES.items() if key in frame}
    )
    missing = sorted(set(CANONICAL_COLUMNS) - set(renamed.columns))
    if missing:
        raise ValueError(f"Hourly evidence is missing columns: {missing}.")
    selected = renamed.copy()
    if "portfolio" in selected:
        selected = selected.loc[selected["portfolio"].eq(PORTFOLIO)]
    if "shock" in selected:
        selected = selected.loc[selected["shock"].eq(SHOCK)]
    if "anchor" in selected:
        selected = selected.loc[selected["anchor"].eq(ANCHOR)]
    if selected.empty:
        raise ValueError(f"Hourly evidence does not contain anchor {ANCHOR!r}.")
    selected = selected.loc[:, CANONICAL_COLUMNS].copy()
    for column in CANONICAL_COLUMNS:
        selected[column] = pd.to_numeric(selected[column], errors="raise")
    selected["replication"] = selected["replication"].astype(int)
    selected["delay_hours"] = selected["delay_hours"].astype(int)
    return selected


def _array_from(mapping: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _checkpoint_hourly_rows(
    payload: Mapping[str, Any], path: Path
) -> list[dict[str, Any]]:
    direct = payload.get("hourly_cell_rows")
    if isinstance(direct, list):
        return [dict(row) for row in direct]
    rows: list[dict[str, Any]] = []
    for cell in payload.get("cell_rows", []):
        if cell.get("portfolio") != PORTFOLIO or cell.get("shock") != SHOCK:
            continue
        hourly = cell.get("hourly") or cell.get("arrays")
        if not isinstance(hourly, Mapping):
            continue
        market = _array_from(hourly, "market_unsafe_debt", "market_unsafe_debt_dai")
        oracle = _array_from(hourly, "oracle_unsafe_debt", "oracle_unsafe_debt_dai")
        false_safe = _array_from(hourly, "false_safe_debt", "false_safe_debt_dai")
        dai = _array_from(hourly, "dai_price", "dai_price_path")
        if dai is None:
            dai = cell.get("dai_price_path")
        arrays = (market, oracle, false_safe, dai)
        if any(value is None for value in arrays):
            continue
        lengths = {len(value) for value in arrays}
        if len(lengths) != 1:
            raise ValueError(f"Hourly arrays have incompatible lengths in {path}.")
        replication = int(payload["replication"])
        delay = int(cell.get("oracle_delay_hours", cell.get("oracle_delay_steps")))
        for hour, values in enumerate(zip(*arrays, strict=True)):
            rows.append(
                {
                    "replication": replication,
                    "hour": hour,
                    "delay_hours": delay,
                    "market_unsafe_debt": values[0],
                    "oracle_unsafe_debt": values[1],
                    "false_safe_debt": values[2],
                    "dai_price": values[3],
                }
            )
    return rows


def load_hourly_evidence(source: Path) -> tuple[pd.DataFrame, list[Path]]:
    """Load detailed frozen output without invoking any simulation code."""
    source = source.resolve()
    if source.is_file():
        if source.suffix.lower() != ".csv":
            raise ValueError(
                "Detailed hourly evidence must be a CSV or checkpoint directory."
            )
        return _normalise_columns(pd.read_csv(source)), [source]
    if not source.is_dir():
        raise FileNotFoundError(f"Experiment E source does not exist: {source}")
    csv_candidates = [
        source / "oracle_delay_hourly_paths.csv",
        source / "hourly_paths.csv",
        source / "detailed" / "oracle_delay_hourly_paths.csv",
    ]
    for candidate in csv_candidates:
        if candidate.is_file():
            return _normalise_columns(pd.read_csv(candidate)), [candidate]
    checkpoints = sorted((source / "checkpoints").glob("replication_*.json"))
    rows: list[dict[str, Any]] = []
    for path in checkpoints:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(_checkpoint_hourly_rows(payload, path))
    if rows:
        return _normalise_columns(pd.DataFrame(rows)), checkpoints
    if checkpoints:
        raise MissingHourlyEvidenceError(
            f"Found {len(checkpoints)} complete Experiment E checkpoints under "
            f"{source}, but they contain scalar cell summaries only. The required "
            "hourly market-unsafe debt, oracle-unsafe debt, false-safe debt and "
            "DAI-price arrays were not retained. Reporting cannot reconstruct them "
            "from scalar summaries without rerunning or fabricating evidence."
        )
    raise MissingHourlyEvidenceError(
        f"No detailed Experiment E hourly evidence found under {source}."
    )


def _validate_detail(frame: pd.DataFrame, contract: ExperimentContract) -> float:
    if frame.duplicated(["replication", "delay_hours", "hour"]).any():
        raise ValueError(
            "Hourly evidence contains duplicate replication/treatment/hour rows."
        )
    delays = tuple(sorted(frame["delay_hours"].unique().tolist()))
    if delays != contract.delays:
        raise ValueError(
            f"Expected delay treatments {contract.delays}, observed {delays}."
        )
    expected_replications = set(range(contract.replications))
    for delay, group in frame.groupby("delay_hours", sort=True):
        observed_replications = set(group["replication"].unique().tolist())
        if observed_replications != expected_replications:
            missing = sorted(expected_replications - observed_replications)
            extra = sorted(observed_replications - expected_replications)
            raise ValueError(
                f"Delay {delay} replication set differs: missing={missing}, extra={extra}."
            )
    expected_hours: np.ndarray | None = None
    timestep: float | None = None
    for (replication, delay), group in frame.groupby(
        ["replication", "delay_hours"], sort=True
    ):
        hours = np.sort(group["hour"].to_numpy(dtype=float))
        if hours.size != contract.total_hours:
            raise ValueError(
                f"Replication {replication}, delay {delay} has {hours.size} hours; "
                f"expected {contract.total_hours}."
            )
        if hours[0] != 0.0 or hours[-1] != float(contract.total_hours - 1):
            raise ValueError(
                f"Replication {replication}, delay {delay} does not span the "
                "registered hour range."
            )
        differences = np.diff(hours)
        if differences.size == 0 or not np.allclose(
            differences, differences[0], rtol=0.0, atol=1e-12
        ):
            raise ValueError("Experiment E hourly grids are not regular.")
        current_timestep = float(differences[0])
        if current_timestep <= 0.0:
            raise ValueError("Experiment E timestep must be positive.")
        if timestep is None:
            timestep = current_timestep
            expected_hours = hours
        elif not math.isclose(
            current_timestep, timestep, rel_tol=0.0, abs_tol=1e-12
        ) or not np.array_equal(hours, expected_hours):
            raise ValueError("Experiment E treatments use incompatible time grids.")
    numeric = frame.loc[:, CANONICAL_COLUMNS]
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("Hourly evidence contains missing or infinite values.")
    debt_columns = ["market_unsafe_debt", "oracle_unsafe_debt", "false_safe_debt"]
    if (frame[debt_columns] < -1e-8).any().any():
        raise ValueError("Hourly debt series contain negative values.")
    if (frame[debt_columns] > contract.total_debt_dai + 1e-6).any().any():
        raise ValueError("Hourly unsafe debt exceeds the frozen initial system debt.")
    if (frame["dai_price"] <= 0.0).any():
        raise ValueError("DAI-price paths must remain positive.")
    zero = frame.loc[frame["delay_hours"].eq(0)]
    if not np.allclose(
        zero["market_unsafe_debt"], zero["oracle_unsafe_debt"], rtol=0.0, atol=1e-8
    ):
        raise ValueError("Zero-delay market-unsafe and oracle-unsafe debt differ.")
    if not np.allclose(zero["false_safe_debt"], 0.0, rtol=0.0, atol=1e-8):
        raise ValueError("Zero-delay false-safe debt is not structural zero.")
    assert timestep is not None
    return timestep


def _summary_mean(summary: pd.DataFrame, delay: int, metric: str) -> float:
    selected = summary.loc[
        summary["portfolio"].eq(PORTFOLIO)
        & summary["shock"].eq(SHOCK)
        & summary["oracle_delay_steps"].eq(delay)
        & summary["metric"].eq(metric),
        "mean",
    ]
    if len(selected) != 1:
        raise ValueError(
            f"Expected one registered summary for delay={delay}, metric={metric}."
        )
    return float(selected.iloc[0])


def reconcile_registered_summaries(
    detail: pd.DataFrame,
    summary: pd.DataFrame,
    contract: ExperimentContract,
    timestep_hours: float,
    *,
    absolute_tolerance: float = 1e-5,
) -> dict[str, Any]:
    """Reconcile exactly equivalent raw-path metrics with registered summaries."""
    post = detail.loc[detail["hour"].ge(contract.pre_shock_hours)]
    checks: list[dict[str, Any]] = []
    for delay in contract.delays:
        treatment = post.loc[post["delay_hours"].eq(delay)]
        by_replication = treatment.groupby("replication", sort=True)
        observed = {
            "false_safe_debt_hours": float(
                by_replication["false_safe_debt"].sum().mean() * timestep_hours
            ),
            "peak_false_safe_debt": float(
                by_replication["false_safe_debt"].max().mean()
            ),
            "minimum_dai_price": float(by_replication["dai_price"].min().mean()),
            "mean_absolute_peg_deviation": float(
                treatment.assign(_deviation=(treatment["dai_price"] - 1.0).abs())
                .groupby("replication", sort=True)["_deviation"]
                .mean()
                .mean()
            ),
        }
        for metric, value in observed.items():
            registered = _summary_mean(summary, delay, metric)
            tolerance = max(absolute_tolerance, abs(registered) * 1e-10)
            passed = math.isclose(value, registered, rel_tol=0.0, abs_tol=tolerance)
            checks.append(
                {
                    "delay_hours": delay,
                    "metric": metric,
                    "observed": value,
                    "registered": registered,
                    "absolute_difference": abs(value - registered),
                    "tolerance": tolerance,
                    "passed": passed,
                }
            )
    failures = [row for row in checks if not row["passed"]]
    if failures:
        raise ValueError(
            f"Hourly evidence does not reconcile with registered summaries: {failures}"
        )
    return {"passed": True, "checks": checks}


def prepare_frames(
    detail: pd.DataFrame,
    contract: ExperimentContract = ExperimentContract(),
) -> tuple[pd.DataFrame, float]:
    """Validate paths, derive share-hour mismatch per run, then aggregate."""
    clean = _normalise_columns(detail)
    timestep = _validate_detail(clean, contract)
    clean = clean.sort_values(["delay_hours", "replication", "hour"], kind="mergesort")
    clean["market_unsafe_debt_share"] = (
        clean["market_unsafe_debt"] / contract.total_debt_dai
    )
    clean["oracle_unsafe_debt_share"] = (
        clean["oracle_unsafe_debt"] / contract.total_debt_dai
    )
    # Animation mismatch is the requested unsafe-debt-share information gap.
    # It is distinct from Experiment E's registered log-price mismatch metric.
    increments = (
        clean["market_unsafe_debt_share"].sub(clean["oracle_unsafe_debt_share"]).abs()
        * timestep
    )
    clean["cumulative_absolute_mismatch"] = increments.groupby(
        [clean["delay_hours"], clean["replication"]], sort=False
    ).cumsum()
    metrics = (
        "market_unsafe_debt_share",
        "oracle_unsafe_debt_share",
        "false_safe_debt",
        "cumulative_absolute_mismatch",
        "dai_price",
    )
    grouped = clean.groupby(["hour", "delay_hours"], sort=True)
    mean = grouped[list(metrics)].mean()
    lower = grouped[list(metrics)].quantile(0.025).add_suffix("_p025")
    upper = grouped[list(metrics)].quantile(0.975).add_suffix("_p975")
    frames = pd.concat([mean, lower, upper], axis=1).reset_index()
    frames.insert(2, "treatment", frames["delay_hours"].map(DELAY_TO_TREATMENT))
    ordered = ["hour", "delay_hours", "treatment"]
    for metric in metrics:
        ordered.extend((metric, f"{metric}_p025", f"{metric}_p975"))
    frames = frames.loc[:, ordered]
    for delay, group in frames.groupby("delay_hours", sort=True):
        cumulative = group["cumulative_absolute_mismatch"].to_numpy()
        if np.any(cumulative < -1e-12) or np.any(np.diff(cumulative) < -1e-12):
            raise ValueError(f"Delay {delay} cumulative mismatch is invalid.")
    zero = frames.loc[frames["delay_hours"].eq(0)]
    if not np.allclose(zero["cumulative_absolute_mismatch"], 0.0, atol=1e-12, rtol=0.0):
        raise ValueError("Zero-delay cumulative mismatch is not structural zero.")
    return frames, timestep


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def build_frame_output(
    source: Path = DEFAULT_SOURCE,
    output_path: Path = DEFAULT_FRAME_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    if not overwrite:
        conflicts = [path for path in (output_path, metadata_path) if path.exists()]
        if conflicts:
            raise FileExistsError(
                f"Refusing to overwrite reporting outputs: {conflicts}"
            )
    detail, source_paths = load_hourly_evidence(source)
    replay_manifest_path = (
        source.parent if source.is_file() else source
    ) / "oracle_delay_reporting_replay_manifest.json"
    replay_manifest = None
    if replay_manifest_path.is_file():
        replay_manifest = json.loads(replay_manifest_path.read_text(encoding="utf-8"))
        source_paths.append(replay_manifest_path)
    contract = ExperimentContract()
    frames, timestep = prepare_frames(detail, contract)
    summary = pd.read_csv(CELL_SUMMARY_PATH)
    reconciliation = reconcile_registered_summaries(detail, summary, contract, timestep)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames.to_csv(output_path, index=False)
    metadata = {
        "schema_version": 1,
        "producer": "workflows.experiments.final.build_oracle_delay_animation_frames",
        "experiment_id": EXPERIMENT_ID,
        "experiment_identity": EXPERIMENT_IDENTITY,
        "anchor": ANCHOR,
        "portfolio": PORTFOLIO,
        "shock": SHOCK,
        "treatments": [
            {"delay_hours": delay, "identifier": DELAY_TO_TREATMENT[delay]}
            for delay in contract.delays
        ],
        "contract": asdict(contract),
        "time_range": [float(frames["hour"].min()), float(frames["hour"].max())],
        "timestep_hours": timestep,
        "aggregation": {
            "centre": "ensemble arithmetic mean across all registered replications",
            "uncertainty": "pointwise empirical 2.5th and 97.5th percentiles",
            "replication_count": contract.replications,
        },
        "derived_metrics": {
            "market_unsafe_debt_share": "canonical market_unsafe_debt / frozen initial total debt DAI",
            "oracle_unsafe_debt_share": "canonical oracle_unsafe_debt / frozen initial total debt DAI",
            "cumulative_absolute_mismatch": (
                "per replication cumulative sum of abs(market_unsafe_debt_share - "
                "oracle_unsafe_debt_share) * observed timestep_hours; units share-hours; "
                "distinct from registered log-price debt_weighted_absolute_mismatch_area"
            ),
        },
        "reconciliation": reconciliation,
        "reporting_replay": replay_manifest,
        "source_paths": [
            {"path": _relative(path), "sha256": sha256_file(path)}
            for path in source_paths
        ]
        + [
            {"path": _relative(path), "sha256": sha256_file(path)}
            for path in (SPECIFICATION_PATH, CELL_SUMMARY_PATH, DECISION_PATH)
        ],
        "output": {"path": _relative(output_path), "sha256": sha256_file(output_path)},
        "git_commit": _git_commit(),
    }
    _write_json(metadata_path, metadata)
    return output_path, metadata_path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_FRAME_PATH)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA_PATH)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output, metadata = build_frame_output(
            args.source, args.output, args.metadata, overwrite=args.overwrite
        )
    except (FileExistsError, MissingHourlyEvidenceError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote {output}")
    print(f"Wrote {metadata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
