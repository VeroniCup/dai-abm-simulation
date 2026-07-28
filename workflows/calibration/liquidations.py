"""Run the local-only Phase 2C liquidation and stress-tail review."""

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
from dai_sim.calibration.liquidations import (
    DEFAULT_OUTPUT,
    Phase2CConfig,
    run_phase2c,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=20_260_726)
    parser.add_argument("--bootstrap-replications", type=int, default=400)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_phase2c(Phase2CConfig(
        output_dir=args.output_dir,
        random_seed=args.seed,
        bootstrap_replications=args.bootstrap_replications,
    ))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
