"""Operate the pre-registered constrained-liquidation ETH recovery study."""

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

from dai_sim.experiments.constrained_eth_recovery import (
    audit_checkpoints,
    build_cell_registry,
    build_evidence_payloads,
    build_paths,
    experiment_identity,
    load_design,
    preflight,
    run_matrix,
    run_smoke,
    validate_evidence,
    write_evidence,
    write_preregistration,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the constrained-liquidation ETH-recovery experiment without "
            "altering runtime profiles."
        )
    )
    parser.add_argument(
        "operation",
        choices=(
            "validate",
            "build-cell-registry",
            "build-seeds",
            "pre-register",
            "run-smoke",
            "run",
            "resume",
            "audit-checkpoints",
            "aggregate",
            "pair-vault-outcomes",
            "calculate-contrasts",
            "calculate-interactions",
            "classify",
            "reconstruct-evidence",
            "validate-completed",
        ),
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-replications", type=int)
    parser.add_argument("--benchmark-json", type=Path)
    return parser


def _benchmark(path: Path | None, evidence_dir: Path) -> dict:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    existing = evidence_dir / "constrained_recovery_benchmark.json"
    if not existing.is_file():
        raise FileNotFoundError(
            "Evidence construction requires measured benchmark metadata."
        )
    return json.loads(existing.read_text(encoding="utf-8"))


def main() -> int:
    args = build_parser().parse_args()
    design = load_design(args.config) if args.config else load_design()
    operation = args.operation
    if operation == "validate":
        result = preflight(design)
    elif operation == "build-cell-registry":
        cells = build_cell_registry(design, build_paths(design))
        result = {
            "experiment_identity": experiment_identity(design, cells),
            "cell_count": len(cells),
            "cells": [cell.identifier for cell in cells],
        }
    elif operation == "build-seeds":
        from dai_sim.experiments.constrained_eth_recovery import (
            seed_record,
            seed_registry_checksum,
        )

        result = {
            "registry_id": design.registry_id,
            "replication_count": design.replications,
            "registry_sha256": seed_registry_checksum(design.replications),
            "first_record": seed_record(0),
        }
    elif operation == "pre-register":
        result = write_preregistration(design)
    elif operation == "run-smoke":
        result = run_smoke(design)
    elif operation in {"run", "resume"}:
        result = run_matrix(
            design,
            workers=args.workers,
            resume=operation == "resume",
            max_replications=args.max_replications,
        )
    elif operation == "audit-checkpoints":
        result = audit_checkpoints(design)
    elif operation in {
        "aggregate",
        "pair-vault-outcomes",
        "calculate-contrasts",
        "calculate-interactions",
        "classify",
    }:
        result = build_evidence_payloads(
            design=design,
            benchmark=_benchmark(args.benchmark_json, design.evidence_dir),
        )
        result = {
            "operation": operation,
            "experiment_identity": result["reproducibility"][
                "experiment_identity"
            ],
            "result_checksum": result["reproducibility"]["result_checksums"],
        }
    elif operation == "reconstruct-evidence":
        result = write_evidence(
            design,
            benchmark=_benchmark(args.benchmark_json, design.evidence_dir),
        )
    else:
        result = validate_evidence(design)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
