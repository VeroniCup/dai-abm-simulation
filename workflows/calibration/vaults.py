"""Estimate review-only Phase 2B candidates from local vault evidence."""

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
from dai_sim.calibration.vaults import (
    DEFAULT_OUTPUT,
    Phase2BConfig,
    run_phase2b,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit local-only command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=20_260_726)
    parser.add_argument("--bootstrap-replications", type=int, default=400)
    parser.add_argument("--recommended-simulation-vaults", type=int, default=500)
    return parser


def main() -> int:
    """Run estimation without acquiring data or writing configuration."""
    args = build_parser().parse_args()
    result = run_phase2b(Phase2BConfig(
        output_dir=args.output_dir,
        random_seed=args.seed,
        bootstrap_replications=args.bootstrap_replications,
        recommended_simulation_vaults=args.recommended_simulation_vaults,
    ))
    print(json.dumps({
        "candidate_count": result["candidate_count"],
        "metadata_path": result["metadata_path"],
        "output_dir": result["output_dir"],
        "registry_path": result["registry_path"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
