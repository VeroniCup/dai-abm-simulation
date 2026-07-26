"""Run the bounded local Phase 2A candidate hardening review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.estimation.phase2a_review import (  # noqa: E402
    DEFAULT_REPORT,
    DEFAULT_REVIEW_DIR,
    Phase2AReviewConfig,
    run_phase2a_review,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Review existing Phase 2A candidates locally without acquisition "
            "or simulator changes."
        )
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REVIEW_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seed", type=int, default=20_260_726)
    parser.add_argument("--bootstrap-replications", type=int, default=1_000)
    parser.add_argument("--block-replications", type=int, default=100)
    parser.add_argument("--no-report", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_phase2a_review(
        Phase2AReviewConfig(
            output_dir=args.output_dir.resolve(),
            report_path=args.report_path.resolve(),
            random_seed=args.seed,
            bootstrap_replications=args.bootstrap_replications,
            block_replications=args.block_replications,
            write_report=not args.no_report,
        )
    )
    print(
        json.dumps(
            {
                "metadata_path": result["metadata_path"],
                "reviewed_registry_path": result["reviewed_registry_path"],
                "candidate_status_counts": result[
                    "candidate_status_counts"
                ],
                "output_count": len(result["outputs"]),
                "report_path": result["report_path"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
