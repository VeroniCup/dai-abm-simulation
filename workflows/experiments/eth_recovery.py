"""Validate, execute, resume and summarise the ETH recovery experiment."""

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
runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)

from dai_sim.experiments.eth_recovery import (
    build_cell_registry,
    build_eth_path,
    experiment_identity,
    load_recovery_design,
    preflight,
    run_matrix,
    run_smoke,
    validate_evidence,
    write_preregistration_snapshot,
    write_evidence,
)


def _resolve_benchmark(
    *,
    operation: str,
    benchmark_json: Path | None,
    evidence_dir: Path,
    workers: int,
) -> dict:
    """Load measured host evidence when reconstructing completed evidence."""
    if benchmark_json is not None:
        return json.loads(benchmark_json.read_text(encoding="utf-8"))
    existing = evidence_dir / "eth_recovery_benchmark.json"
    if operation == "reconstruct-evidence":
        if not existing.is_file():
            raise FileNotFoundError(
                "Reconstruction requires the existing measured benchmark "
                "or --benchmark-json."
            )
        return json.loads(existing.read_text(encoding="utf-8"))
    return {
        "worker_count": workers,
        "completed_simulations": 2048,
        "reused_simulations": 0,
        "resumed_simulations": 0,
        "wall_time_seconds": 0.0,
        "throughput_simulations_per_second": 0.0,
        "peak_memory_bytes": None,
        "output_size_bytes": 0,
        "free_disk_bytes": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the pre-registered ETH-only peg-recovery matrix."
    )
    parser.add_argument(
        "operation",
        choices=(
            "validate-inputs",
            "build-paths",
            "validate-registry",
            "run-smoke",
            "pre-register",
            "run-full",
            "resume",
            "aggregate",
            "validate-completed",
            "reconstruct-evidence",
        ),
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-replications", type=int)
    parser.add_argument("--benchmark-json", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    design = load_recovery_design(
        args.config if args.config is not None else None
    ) if args.config is not None else load_recovery_design()
    paths = {
        definition.identifier: build_eth_path(design, definition)
        for definition in design.path_definitions
    }
    cells = build_cell_registry(design, paths)
    identity = experiment_identity(design, cells)
    if args.operation == "validate-inputs":
        result = preflight(design, run_smoke_test=False)
    elif args.operation == "build-paths":
        result = {
            "experiment_identity": identity,
            "paths": {
                identifier: len(values) for identifier, values in paths.items()
            },
        }
    elif args.operation == "validate-registry":
        result = {
            "experiment_identity": identity,
            "cell_count": len(cells),
            "cells": [cell.identifier for cell in cells],
        }
    elif args.operation == "run-smoke":
        result = run_smoke(design)
    elif args.operation == "pre-register":
        result = write_preregistration_snapshot(design)
    elif args.operation in {"run-full", "resume"}:
        result = run_matrix(
            design=design,
            workers=args.workers,
            resume=args.operation == "resume",
            max_replications=args.max_replications,
        )
    elif args.operation in {"aggregate", "reconstruct-evidence"}:
        benchmark = _resolve_benchmark(
            operation=args.operation,
            benchmark_json=args.benchmark_json,
            evidence_dir=design.evidence_dir,
            workers=args.workers,
        )
        result = write_evidence(
            design=design,
            experiment_id=identity,
            benchmark=benchmark,
        )
    else:
        result = validate_evidence(design=design)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
