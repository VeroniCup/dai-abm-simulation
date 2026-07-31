"""Freeze and execute the final held-out validation sequence without retuning."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy

_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
runpy.run_path(str(_BOOTSTRAP))["bootstrap_runtime"](__file__)

from dai_sim.validation import final_validation as validation  # noqa: E402


_SCIENTIFIC_STAGE_SUMMARY = validation.stage_summary


def _stage_summary(stage: str) -> dict[str, object]:
    """Attach USDC attribution from frozen rows at the evidence boundary."""
    if stage != "usdc_svb":
        return _SCIENTIFIC_STAGE_SUMMARY(stage)
    frame = validation.load_stage_results(stage)
    stable = frame.loc[frame["portfolio"].eq("stable_supported")]
    attribution = {
        metric: validation._distribution(
            validation.pd.to_numeric(stable[metric], errors="raise").tolist()
        )
        for metric in (
            "stable_initial_debt_exposure",
            "stable_liquidated_debt",
            "stable_backlog_area",
        )
    }
    scientific_classifier = validation.classify_usdc_svb_validation

    def classify(
        *,
        negative_control_passed: bool,
        stable_supported: object,
    ) -> str:
        del stable_supported
        return scientific_classifier(
            negative_control_passed=negative_control_passed,
            stable_supported=attribution,
        )

    validation.classify_usdc_svb_validation = classify
    try:
        summary = _SCIENTIFIC_STAGE_SUMMARY(stage)
    finally:
        validation.classify_usdc_svb_validation = scientific_classifier
    summary["stable_channel"] = attribution
    summary["evidence_boundary_repair"] = (
        "stable_attribution_summarised_from_frozen_checkpoint_rows"
    )
    return summary


def _write_stage_summary(stage: str) -> dict[str, object]:
    summary = _stage_summary(stage)
    name = (
        validation.COMPACT_FILENAMES[4]
        if stage == "ftx"
        else validation.COMPACT_FILENAMES[5]
    )
    validation.robustness._atomic_json(validation.EVIDENCE_DIR / name, summary)
    return summary


def _reconstruct_evidence(benchmark: dict[str, object]) -> dict[str, object]:
    original = validation.stage_summary
    validation.stage_summary = _stage_summary
    try:
        return validation.reconstruct_evidence(benchmark)
    finally:
        validation.stage_summary = original


def _reconstruction_benchmark(workers: int) -> dict[str, object]:
    path = validation.EVIDENCE_DIR / validation.COMPACT_FILENAMES[10]
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return validation.benchmark_payload(
        workers=workers,
        ftx_seconds=0.0,
        usdc_seconds=0.0,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("inventory", "freeze", "quiet", "ftx", "usdc-svb", "reconstruct", "all"),
    )
    parser.add_argument("--workers", type=int, default=4)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.operation == "inventory":
        result = validation.window_inventory().where(
            validation.pd.notna(validation.window_inventory()), None
        ).to_dict(orient="records")
    elif args.operation == "freeze":
        result = validation.write_freeze()
    elif args.operation == "quiet":
        result = {
            "classification": "quiet_validation_not_separately_registered",
            "simulation_count": 0,
        }
    elif args.operation == "ftx":
        execution = validation.run_stage("ftx", workers=args.workers, resume=True)
        if not execution["complete"]:
            raise ValueError("FTX validation did not complete.")
        result = {"execution": execution, "summary": _write_stage_summary("ftx")}
    elif args.operation == "usdc-svb":
        execution = validation.run_stage("usdc_svb", workers=args.workers, resume=True)
        if not execution["complete"]:
            raise ValueError("USDC/SVB validation did not complete.")
        result = {"execution": execution, "summary": _write_stage_summary("usdc_svb")}
    elif args.operation == "reconstruct":
        result = _reconstruct_evidence(_reconstruction_benchmark(args.workers))
    else:
        freeze = validation.write_freeze()
        ftx = validation.run_stage("ftx", workers=args.workers, resume=True)
        if not ftx["complete"]:
            raise ValueError("FTX validation did not complete.")
        ftx_summary = _write_stage_summary("ftx")
        usdc = validation.run_stage("usdc_svb", workers=args.workers, resume=True)
        if not usdc["complete"]:
            raise ValueError("USDC/SVB validation did not complete.")
        benchmark = validation.benchmark_payload(
            workers=args.workers,
            ftx_seconds=float(ftx["elapsed_seconds"]),
            usdc_seconds=float(usdc["elapsed_seconds"]),
        )
        result = {
            "freeze": freeze,
            "quiet": "quiet_validation_not_separately_registered",
            "ftx_execution": ftx,
            "ftx_summary": ftx_summary,
            "usdc_svb_execution": usdc,
            "evidence": _reconstruct_evidence(benchmark),
            "validation": validation.validate_evidence(),
        }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
