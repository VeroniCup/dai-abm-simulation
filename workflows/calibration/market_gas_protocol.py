"""Run the bounded, entirely local Phase 2A estimation workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
REPOSITORY_ROOT = runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)
from dai_sim.calibration.market import (
    CONFIDENCE_DIAGNOSTICS,
    CONFIDENCE_EVIDENCE,
    DEFAULT_FIGURES,
    DEFAULT_OUTPUT,
    DEFAULT_REPORT,
    ConfidenceCalibrationConfig,
    Phase2AConfig,
    run_confidence_calibration_infrastructure,
    run_phase2a,
)


def build_parser() -> argparse.ArgumentParser:
    """Build explicit local-only execution arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Estimate Phase 2A empirical candidates from locally validated "
            "Phase 1A–1D inputs, or build the bounded confidence-calibration "
            "infrastructure. This command does not access the network."
        )
    )
    parser.add_argument(
        "operation",
        nargs="?",
        choices=("phase2a", "confidence-infrastructure"),
        default="phase2a",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--figure-dir", type=Path, default=DEFAULT_FIGURES)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seed", type=int, default=20_260_726)
    parser.add_argument("--bootstrap-replications", type=int, default=200)
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument(
        "--input",
        type=Path,
        help=(
            "Ignored canonical historical panel required only by "
            "confidence-infrastructure."
        ),
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=CONFIDENCE_EVIDENCE,
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        default=CONFIDENCE_DIAGNOSTICS,
    )
    parser.add_argument("--validation-only", action="store_true")
    return parser


def main() -> int:
    """Execute once and print only compact provenance, never input rows."""
    parser = build_parser()
    args = parser.parse_args()
    if args.operation == "confidence-infrastructure":
        if args.input is None:
            parser.error(
                "confidence-infrastructure requires an explicit --input path"
            )
        result = run_confidence_calibration_infrastructure(
            ConfidenceCalibrationConfig(
                input_path=args.input.resolve(),
                evidence_dir=args.evidence_dir.resolve(),
                diagnostics_dir=args.diagnostics_dir.resolve(),
                random_seed=args.seed,
                bootstrap_replications=args.bootstrap_replications,
                validation_only=args.validation_only,
            )
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    config = Phase2AConfig(
        output_dir=args.output_dir.resolve(),
        figure_dir=args.figure_dir.resolve(),
        report_path=args.report_path.resolve(),
        random_seed=args.seed,
        bootstrap_replications=args.bootstrap_replications,
        write_figures=not args.no_figures,
        write_report=not args.no_report,
    )
    result = run_phase2a(config)
    print(
        json.dumps(
            {
                "metadata_path": result["metadata_path"],
                "registry_path": result["registry_path"],
                "parameter_count": result["parameter_count"],
                "candidate_count": result["candidate_count"],
                "output_count": len(result["outputs"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
