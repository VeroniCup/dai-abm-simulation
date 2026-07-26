"""Run the bounded, entirely local Phase 2A estimation workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.estimation.phase2a import (  # noqa: E402
    DEFAULT_FIGURES,
    DEFAULT_OUTPUT,
    DEFAULT_REPORT,
    Phase2AConfig,
    run_phase2a,
)


def build_parser() -> argparse.ArgumentParser:
    """Build explicit local-only execution arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Estimate Phase 2A empirical candidates from locally validated "
            "Phase 1A–1D inputs. This command does not access the network."
        )
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--figure-dir", type=Path, default=DEFAULT_FIGURES)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seed", type=int, default=20_260_726)
    parser.add_argument("--bootstrap-replications", type=int, default=200)
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    return parser


def main() -> int:
    """Execute once and print only compact provenance, never input rows."""
    args = build_parser().parse_args()
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
