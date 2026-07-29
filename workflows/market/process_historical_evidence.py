"""Harmonise full-range DAI/ETH evidence and evaluate Design C without fitting.

This workflow performs local deterministic processing only.  It never contacts
Dune or another provider, and it refuses to overwrite any output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
from typing import Any

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
REPOSITORY_ROOT = runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](
    __file__
)

import pandas as pd

from dai_sim.calibration.confidence_evidence import (
    ASSET_IDENTITIES,
    HISTORICAL_END,
    HISTORICAL_START,
    compare_overlap,
    evaluate_design_c,
    harmonise_dune_hourly,
    hourly_grid,
    identical_price_runs,
)


class HistoricalProcessingError(RuntimeError):
    """Raised when a candidate cannot be promoted without repair."""


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 checksum."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_bytes_atomically(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise HistoricalProcessingError(f"Refusing to overwrite {path}.")
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    """Write deterministic compact JSON with an atomic replacement."""
    rendered = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    _write_bytes_atomically(path, rendered)


def write_csv_atomically(path: Path, frame: pd.DataFrame) -> None:
    """Write deterministic UTF-8 CSV with UTC timestamps."""
    rendered = frame.to_csv(
        index=False,
        lineterminator="\n",
        date_format="%Y-%m-%dT%H:%M:%SZ",
    ).encode("utf-8")
    _write_bytes_atomically(path, rendered)


def build_reports(
    raw_path: Path,
    current_panel_path: Path,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build the candidate and its three compact report classes."""
    raw = pd.read_csv(raw_path, dtype={"contract_address": "string"}, low_memory=False)
    current = pd.read_csv(current_panel_path, low_memory=False)
    panel = harmonise_dune_hourly(raw)
    overlap = compare_overlap(panel, current)
    stale_runs = {
        asset: identical_price_runs(panel, asset.lower())
        for asset in ("DAI", "ETH")
    }
    source_distribution = {
        asset: (
            raw.loc[raw["asset"].eq(asset), "source"]
            .astype(str)
            .value_counts()
            .sort_index()
            .to_dict()
        )
        for asset in ASSET_IDENTITIES
    }
    source_changes = {}
    for asset in ASSET_IDENTITIES:
        sources = (
            raw.loc[raw["asset"].eq(asset)]
            .assign(timestamp=lambda frame: pd.to_datetime(frame["timestamp_utc"], utc=True))
            .sort_values("timestamp")["source"]
            .astype(str)
        )
        source_changes[asset] = int(sources.ne(sources.shift()).sum() - 1)
    coverage = {
        "requested_start_utc": HISTORICAL_START.isoformat(),
        "requested_end_exclusive_utc": HISTORICAL_END.isoformat(),
        "expected_hours_computed": int(len(hourly_grid())),
        "raw_rows": int(len(raw)),
        "raw_columns": int(len(raw.columns)),
        "processed_rows": int(len(panel)),
        "processed_columns": int(len(panel.columns)),
        "assets": sorted(ASSET_IDENTITIES),
        "asset_identities": ASSET_IDENTITIES,
        "source_distribution": source_distribution,
        "source_change_counts": source_changes,
        "missing_hours": {"DAI": 0, "ETH": 0},
        "duplicate_asset_hours": 0,
        "non_finite_prices": 0,
        "non_positive_prices": 0,
        "timestamp_convention": "start-of-hour UTC",
        "price_convention": "Dune prices.hour price field",
        "provider_forward_fill_note": (
            "Dune documents carry-forward when no trade is observed. "
            "Identical-price runs are reported separately."
        ),
        "stale_runs_at_least_six_hours": stale_runs,
        "longest_identical_price_run_hours": {
            asset: max((item["hours"] for item in runs), default=0)
            for asset, runs in stale_runs.items()
        },
        "validation_passed": True,
    }
    maximum_difference = max(
        overlap["assets"][asset]["absolute_difference"]["maximum"]
        for asset in ("DAI", "ETH")
    )
    maximum_relative_difference = max(
        overlap["assets"][asset]["relative_difference_quantiles"]["maximum"]
        for asset in ("DAI", "ETH")
    )
    label_disagreements = overlap["assets"]["DAI"]["label_disagreements"]
    categorical_disagreements = {
        key: value
        for key, value in label_disagreements.items()
        if key != "six_hour_burden_numerically_different"
    }
    exact_extension = (
        not overlap["candidate_missing_timestamps"]
        and not overlap["existing_missing_timestamps"]
        and maximum_relative_difference <= 1e-12
        and not any(categorical_disagreements.values())
    )
    harmonisation = {
        "source_adoption_decision": (
            "adopt_exact_source_extension"
            if exact_extension
            else "stop_for_source_adoption_review"
        ),
        "exact_source_extension": exact_extension,
        "maximum_overlap_price_difference": maximum_difference,
        "maximum_overlap_relative_difference": maximum_relative_difference,
        "floating_representation_tolerance": {
            "relative": 1e-12,
            "six_hour_burden_absolute": 1e-12,
        },
        "overlap": overlap,
        "no_interpolation": True,
        "no_forward_fill_by_repository": True,
    }
    feasibility = evaluate_design_c(panel)
    return panel, coverage, harmonisation, feasibility


def compact_evidence_payloads(
    coverage: dict[str, Any],
    harmonisation: dict[str, Any],
    feasibility: dict[str, Any],
    *,
    query_id: int,
    execution_id: str,
    sql_path: Path,
    usage_before: float,
    usage_after: float,
) -> dict[str, dict[str, Any]]:
    """Build stable tracked evidence without hourly observations."""
    calibration = feasibility["calibration_burden"]
    episode_lookup = {
        item["episode_id"]: item for item in feasibility["episodes"]
    }
    top_episodes = []
    for episode_id, burden in sorted(
        calibration["burden_by_episode"].items(),
        key=lambda item: (-item[1], item[0]),
    )[:10]:
        top_episodes.append(
            {
                "episode_id": episode_id,
                "total_burden": burden,
                **episode_lookup.get(episode_id, {}),
            }
        )
    compact_anchors = {
        anchor: {
            key: value
            for key, value in summary.items()
            if key
            in {
                "retained_origins",
                "nonzero_origins",
                "burden_ge_0_10",
                "burden_ge_0_25",
                "burden_ge_0_50",
                "total_burden",
                "distinct_contributing_episodes",
                "largest_episode_share",
            }
        }
        for anchor, summary in feasibility["anchor_sensitivity"].items()
    }
    return {
        "historical_market_coverage.json": {
            "schema_version": 1,
            "purpose": "Canonical full-range DAI/ETH confidence-calibration coverage.",
            "source": {
                "provider": "Dune",
                "table": "prices.hour",
                "query_type": "private temporary",
                "query_id": query_id,
                "execution_id": execution_id,
                "engine": "small",
                "sql_path": str(sql_path),
                "sql_sha256": sha256_file(sql_path),
            },
            "coverage": coverage,
            "usage": {
                "credits_used_before": usage_before,
                "credits_used_after": usage_after,
                "observed_delta": usage_after - usage_before,
            },
        },
        "historical_market_harmonisation.json": {
            "schema_version": 1,
            "purpose": "Exact-source overlap and source-adoption evidence.",
            **harmonisation,
        },
        "sparse_predictor_scaling.json": {
            "schema_version": 1,
            "purpose": "Frozen sparse non-negative predictor transformation and gates.",
            "transformation": "min(1, x / positive_calibration_q95)",
            "centred_after_scaling": False,
            "calibration_owns_scale": True,
            "validation_used_for_scale": False,
            "minimum_positive_observations": 100,
            "minimum_positive_months": 12,
            "minimum_positive_years": 2,
            "minimum_distinct_positive_values": 20,
            **feasibility["predictor_scaling"],
        },
        "design_c_feasibility.json": {
            "schema_version": 1,
            "purpose": "No-fit Design C burden and predictor feasibility decision.",
            "partition": feasibility["partition"],
            "calibration_burden": calibration,
            "quiet_validation_burden": feasibility["quiet_validation_burden"],
            "final_stress_validation_burden": feasibility[
                "final_stress_validation_burden"
            ],
            "burden_gates": feasibility["burden_gates"],
            "anchor_sensitivity": compact_anchors,
            "largest_contributing_episodes": top_episodes,
            "classification": feasibility["classification"],
            "coefficient_fitted": False,
            "failed_design_c_stop_rule": (
                "Close the predictive stress-proxy regression route and use the "
                "pre-registered constrained simulated-moments fallback."
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    """Parse explicit local input and output paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--current-panel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--coverage-report", type=Path, required=True)
    parser.add_argument("--harmonisation-report", type=Path, required=True)
    parser.add_argument("--feasibility-report", type=Path, required=True)
    parser.add_argument("--compact-evidence-directory", type=Path)
    parser.add_argument("--query-id", type=int)
    parser.add_argument("--execution-id")
    parser.add_argument("--sql-path", type=Path)
    parser.add_argument("--usage-before", type=float)
    parser.add_argument("--usage-after", type=float)
    return parser.parse_args()


def main() -> int:
    """Process one locally persisted raw candidate."""
    args = parse_args()
    for input_path in (args.input, args.current_panel):
        if not input_path.is_file():
            raise SystemExit(f"Required input is missing: {input_path}")
    outputs = (
        args.output,
        args.coverage_report,
        args.harmonisation_report,
        args.feasibility_report,
    )
    existing = [path for path in outputs if path.exists()]
    if existing:
        raise SystemExit(f"Refusing to overwrite existing outputs: {existing}")

    panel, coverage, harmonisation, feasibility = build_reports(
        args.input, args.current_panel
    )
    write_csv_atomically(args.output, panel)
    coverage["raw_path"] = str(args.input)
    coverage["raw_sha256"] = sha256_file(args.input)
    coverage["processed_path"] = str(args.output)
    coverage["processed_sha256"] = sha256_file(args.output)
    write_json_atomically(args.coverage_report, coverage)
    write_json_atomically(args.harmonisation_report, harmonisation)
    write_json_atomically(args.feasibility_report, feasibility)
    if args.compact_evidence_directory is not None:
        required = {
            "--query-id": args.query_id,
            "--execution-id": args.execution_id,
            "--sql-path": args.sql_path,
            "--usage-before": args.usage_before,
            "--usage-after": args.usage_after,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise HistoricalProcessingError(
                f"Compact evidence requires arguments: {missing}."
            )
        payloads = compact_evidence_payloads(
            coverage,
            harmonisation,
            feasibility,
            query_id=args.query_id,
            execution_id=args.execution_id,
            sql_path=args.sql_path,
            usage_before=args.usage_before,
            usage_after=args.usage_after,
        )
        for filename, payload in payloads.items():
            write_json_atomically(
                args.compact_evidence_directory / filename,
                payload,
            )

    print(
        f"Processed {len(panel):,} hours; "
        f"source decision: {harmonisation['source_adoption_decision']}; "
        f"Design C: {feasibility['classification']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
