#!/usr/bin/env python3
"""Run or validate the opt-in integrated empirical ETH profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from dai_sim.calibration.integrated_eth_validation import (  # noqa: E402
    EVIDENCE_DIR,
    execute_integrated_validation,
    validate_compact_evidence,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Validate the candidate integrated empirical ETH profile."
    )
    result.add_argument(
        "--mode",
        required=True,
        choices=("execute", "validate"),
        help="Execute validation or validate existing compact evidence.",
    )
    result.add_argument(
        "--evidence-dir",
        type=Path,
        default=EVIDENCE_DIR,
    )
    result.add_argument("--workers", type=int, default=1)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.mode == "execute":
        result = execute_integrated_validation(
            evidence_dir=args.evidence_dir,
            worker_count=args.workers,
        )
    else:
        result = validate_compact_evidence(args.evidence_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
