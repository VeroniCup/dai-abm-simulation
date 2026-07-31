"""Pre-register, execute and reconstruct the selected robustness layer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import time

_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
runpy.run_path(str(_BOOTSTRAP))["bootstrap_runtime"](__file__)

from dai_sim.experiments.final import selected_robustness as robustness  # noqa: E402


def _update_experiment_manifest(paths: list[Path]) -> None:
    """Register robustness evidence in the canonical artefact manifest."""
    manifest = json.loads(robustness.MANIFEST_PATH.read_text(encoding="utf-8"))
    prefix = "data/provenance/experiments/final/selected_robustness/"
    records = [
        {
            "classification": "registered_selected_robustness",
            "path": path.relative_to(robustness.REPOSITORY_ROOT).as_posix(),
            "runtime_adopted": False,
            "sha256": robustness.sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in paths
    ]
    manifest["artefacts"] = sorted(
        [
            entry
            for entry in manifest["artefacts"]
            if not entry["path"].startswith(prefix)
        ]
        + records,
        key=lambda entry: entry["path"],
    )
    manifest["artefact_count"] = len(manifest["artefacts"])
    robustness._atomic_json(robustness.MANIFEST_PATH, manifest)


def _write_evidence(benchmark: dict[str, object]) -> dict[str, object]:
    """Use the canonical manifest schema without changing scientific code."""
    original = robustness.update_manifest
    robustness.update_manifest = _update_experiment_manifest
    try:
        return robustness.write_evidence(benchmark)
    finally:
        robustness.update_manifest = original


def _reconstruction_benchmark(workers: int) -> dict[str, object]:
    path = robustness.EVIDENCE_DIR / robustness.COMPACT_FILENAMES[7]
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return robustness.benchmark_payload(workers=workers, elapsed_seconds=0.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "pre-register",
            "preflight",
            "run-smoke",
            "run",
            "resume",
            "audit-checkpoints",
            "reconstruct-evidence",
            "validate-completed",
            "all",
        ),
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-replications", type=int)
    return parser


def _preflight() -> dict[str, object]:
    spec = robustness.specification_payload()
    cells = robustness.build_cell_registry()
    if len(cells) != 56 or spec["matrix"]["simulations"] != 3584:
        raise ValueError("Selected robustness matrix preflight failed.")
    first = robustness._json_bytes(spec, pretty=True)
    second = robustness._json_bytes(robustness.specification_payload(), pretty=True)
    if first != second:
        raise ValueError("Selected robustness specification is non-deterministic.")
    return {
        "passed": True,
        "robustness_identity": robustness.robustness_identity(),
        "registry_sha256": robustness.sha256_file(robustness.REGISTRY_PATH),
        "cell_count": len(cells),
        "simulations": 3584,
        "held_out_exclusions": True,
        "calibration_runs": 0,
    }


def main() -> int:
    args = build_parser().parse_args()
    if args.operation == "pre-register":
        result = robustness.write_preregistration()
    elif args.operation == "preflight":
        result = _preflight()
    elif args.operation == "run-smoke":
        started = time.perf_counter()
        smoke = robustness.simulate_replication(0)
        result = {
            "elapsed_seconds": time.perf_counter() - started,
            "cell_count": len(smoke["cell_rows"]),
            "recovery_row_count": len(smoke["recovery_rows"]),
        }
    elif args.operation in {"run", "resume"}:
        result = robustness.run_matrix(
            workers=args.workers,
            resume=args.operation == "resume",
            max_replications=args.max_replications,
        )
    elif args.operation == "audit-checkpoints":
        result = robustness.audit_checkpoints()
    elif args.operation == "reconstruct-evidence":
        result = _write_evidence(_reconstruction_benchmark(args.workers))
    elif args.operation == "validate-completed":
        result = robustness.validate_evidence()
    else:
        if args.max_replications is not None:
            raise ValueError("The complete robustness pass cannot be truncated.")
        registration = robustness.write_preregistration()
        preflight = _preflight()
        smoke_started = time.perf_counter()
        smoke = robustness.simulate_replication(0)
        smoke_seconds = time.perf_counter() - smoke_started
        execution = robustness.run_matrix(workers=args.workers, resume=True)
        if not execution["complete"]:
            raise ValueError("Selected robustness execution is incomplete.")
        benchmark = robustness.benchmark_payload(
            workers=args.workers,
            elapsed_seconds=float(execution["elapsed_seconds"]),
            smoke_seconds=smoke_seconds,
        )
        evidence = _write_evidence(benchmark)
        validation = robustness.validate_evidence()
        result = {
            "registration": registration,
            "preflight": preflight,
            "smoke": {
                "cell_count": len(smoke["cell_rows"]),
                "recovery_row_count": len(smoke["recovery_rows"]),
            },
            "execution": execution,
            "evidence": evidence,
            "validation": validation,
        }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
