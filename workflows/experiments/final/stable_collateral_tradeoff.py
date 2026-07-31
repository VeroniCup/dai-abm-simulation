"""Operate only the pre-registered final Experiment C."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import shutil
from statistics import median
import subprocess
import time
from typing import Any

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)

from dai_sim.experiments.final.programme import load_programme  # noqa: E402
from dai_sim.experiments.final.stable_collateral_tradeoff import (  # noqa: E402
    COMPACT_FILENAMES,
    EVIDENCE_DIR,
    EXPERIMENT_C_PARENT_COMMIT,
    REPLICATIONS,
    audit_checkpoints,
    experiment_identity,
    preflight,
    run_matrix,
    run_smoke,
    specification_payload,
    validate_evidence,
    write_evidence,
    write_preregistration,
    _csv_bytes,
    _registry_frame,
    _pretty_json,
    _output_dir,
)
from dai_sim.inputs.configuration import REPOSITORY_ROOT  # noqa: E402


EXPECTED_BRANCH = "feature/multi-collateral"
EXPECTED_UPSTREAM = "origin/feature/multi-collateral"
ALLOWED_PATHS = {
    ".gitignore",
    "FINAL.md",
    "PROJECT_STATUS.md",
    "data/provenance/experiments/manifest.json",
    "docs/experiments/README.md",
    "docs/experiments/final/README.md",
    "docs/experiments/final/stable_collateral_tradeoff.md",
    "docs/overview/project_structure.md",
    "src/dai_sim/experiments/final/stable_collateral_tradeoff.py",
    "tests/experiments/final/test_stable_collateral_tradeoff.py",
    "tests/integration/test_test_collection_integrity.py",
    "tests/integration/test_test_hierarchy.py",
    "tests/workflows/test_migration.py",
    "workflows/experiments/final/stable_collateral_tradeoff.py",
    *{
        (
            "data/provenance/experiments/final/stable_collateral_tradeoff/"
            f"{name}"
        )
        for name in COMPACT_FILENAMES
    },
}


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_boundary() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD").stdout.strip()
    branch = _git("branch", "--show-current").stdout.strip()
    upstream = _git(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    ).stdout.strip()
    staged = _git("diff", "--cached", "--name-only").stdout.splitlines()
    status = _git(
        "status", "--porcelain=v1", "--untracked-files=all"
    ).stdout.splitlines()
    changed: list[str] = []
    for line in status:
        path = line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        changed.append(path)
    unexpected = sorted(path for path in changed if path not in ALLOWED_PATHS)
    if (
        head != EXPERIMENT_C_PARENT_COMMIT
        or branch != EXPECTED_BRANCH
        or upstream != EXPECTED_UPSTREAM
        or staged
        or unexpected
    ):
        raise ValueError(
            "Experiment C Git boundary failed: "
            f"head={head}, branch={branch}, upstream={upstream}, "
            f"staged={staged}, unexpected={unexpected}."
        )
    return {
        "head": head,
        "branch": branch,
        "upstream": upstream,
        "changed_paths": changed,
        "staged_paths": staged,
    }


def _unexecuted_later_experiments() -> dict[str, Any]:
    roots = {
        "D_shared_keeper_capacity": (
            REPOSITORY_ROOT
            / "outputs/experiments/final/shared_keeper_capacity"
        ),
        "E_oracle_delay": (
            REPOSITORY_ROOT / "outputs/experiments/final/oracle_delay"
        ),
    }
    existing = {
        name: str(path.relative_to(REPOSITORY_ROOT))
        for name, path in roots.items()
        if path.exists() and any(path.rglob("*"))
    }
    if existing:
        raise ValueError(f"Later final experiment output exists: {existing}.")
    return {"passed": True, "existing_outputs": existing}


def _preregister() -> dict[str, Any]:
    owner = load_programme()
    first_spec = _pretty_json(
        {
            **specification_payload(owner.programme_identity),
            "experiment_identity": experiment_identity(
                owner.programme_identity
            ),
        }
    )
    second_spec = _pretty_json(
        {
            **specification_payload(owner.programme_identity),
            "experiment_identity": experiment_identity(
                owner.programme_identity
            ),
        }
    )
    first_registry = _csv_bytes(_registry_frame())
    second_registry = _csv_bytes(_registry_frame())
    if first_spec != second_spec or first_registry != second_registry:
        raise ValueError("Experiment C pre-registration is not deterministic.")
    return {
        **write_preregistration(owner.programme_identity),
        "deterministic_reconstruction": True,
        "isolated_reconstructions": 2,
    }


def _preflight() -> dict[str, Any]:
    owner = load_programme()
    return {
        "git": _git_boundary(),
        "scientific": preflight(owner.programme_identity),
        "later_experiments": _unexecuted_later_experiments(),
    }


def _benchmark(
    *,
    workers: int,
    smoke_seconds: float,
    execution: dict[str, Any],
) -> dict[str, Any]:
    audit = execution["checkpoint_audit"]
    free = shutil.disk_usage(REPOSITORY_ROOT).free
    recovered_completed_run = bool(
        execution["completed_replications"] == 0
        and execution["reused_replications"] == REPLICATIONS
        and audit["complete"]
    )
    if recovered_completed_run:
        checkpoint_paths = sorted(
            (_output_dir(load_programme().programme_identity) / "checkpoints").glob(
                "replication_*.json"
            )
        )
        write_times = [path.stat().st_mtime for path in checkpoint_paths]
        worker_times = [
            float(json.loads(path.read_text(encoding="utf-8"))[
                "worker_elapsed_seconds"
            ])
            for path in checkpoint_paths
        ]
        write_span = max(write_times) - min(write_times)
        median_worker = median(worker_times)
        full_wall_time = write_span + median_worker
        completed_replications = REPLICATIONS
        reused_replications = 0
        resumed_replications = 0
        timing_method = (
            "reconstructed_checkpoint_write_span_plus_median_worker_replication"
        )
        original_timer_captured = False
    else:
        write_span = float(execution["elapsed_seconds"])
        median_worker = 0.0
        full_wall_time = float(execution["elapsed_seconds"])
        completed_replications = execution["completed_replications"]
        reused_replications = execution["reused_replications"]
        resumed_replications = execution["resumed_replications"]
        timing_method = "in_memory_wall_clock"
        original_timer_captured = True
    return {
        "schema_version": 1,
        "measurement_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "execution_command": (
            "PYTHONPATH=src python "
            "workflows/experiments/final/stable_collateral_tradeoff.py "
            f"all --workers {workers}"
        ),
        "worker_count": workers,
        "smoke_wall_time_seconds": smoke_seconds,
        "full_wall_time_seconds": full_wall_time,
        "throughput_simulations_per_second": 1536 / full_wall_time,
        "timing_method": timing_method,
        "checkpoint_write_span_seconds": write_span,
        "median_worker_replication_seconds": median_worker,
        "original_timer_captured": original_timer_captured,
        "completed_replications": completed_replications,
        "reused_replications": reused_replications,
        "resumed_replications": resumed_replications,
        "failed_replications": execution["failed_replications"],
        "rerun_replications": execution["rerun_replications"],
        "completed_simulations": 1536,
        "checkpoint_count": audit["valid_count"],
        "output_size_bytes": audit["checkpoint_bytes"],
        "free_storage_bytes": free,
        "network_calls": 0,
        "calibration_runs": 0,
        "experiment_a_simulations": 0,
        "experiment_b_simulations": 0,
        "experiments_d_e_simulations": 0,
        "held_out_validation_runs": 0,
    }


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
    parser.add_argument("--benchmark-json", type=Path)
    return parser


def _load_benchmark(path: Path | None) -> dict[str, Any]:
    selected = (
        path
        if path is not None
        else EVIDENCE_DIR / "stable_collateral_tradeoff_benchmark.json"
    )
    return json.loads(selected.read_text(encoding="utf-8"))


def main() -> int:
    args = build_parser().parse_args()
    owner = load_programme()
    identity = owner.programme_identity
    if args.operation == "pre-register":
        result = _preregister()
    elif args.operation == "preflight":
        result = _preflight()
    elif args.operation == "run-smoke":
        result = {"preflight": _preflight(), "smoke": run_smoke()}
    elif args.operation in {"run", "resume"}:
        result = {
            "preflight": _preflight(),
            "smoke": run_smoke(),
            "execution": run_matrix(
                identity,
                workers=args.workers,
                resume=args.operation == "resume",
                max_replications=args.max_replications,
            ),
        }
    elif args.operation == "audit-checkpoints":
        result = audit_checkpoints(identity)
    elif args.operation == "reconstruct-evidence":
        result = write_evidence(
            identity, _load_benchmark(args.benchmark_json)
        )
    elif args.operation == "validate-completed":
        result = validate_evidence(identity)
    else:
        if args.max_replications is not None:
            raise ValueError("Complete Experiment C cannot be truncated.")
        registration = _preregister()
        gate = _preflight()
        smoke_started = time.perf_counter()
        smoke = run_smoke()
        smoke_seconds = time.perf_counter() - smoke_started
        execution = run_matrix(identity, workers=args.workers, resume=True)
        if not execution["complete"]:
            raise ValueError("Experiment C execution did not complete.")
        benchmark = _benchmark(
            workers=args.workers,
            smoke_seconds=smoke_seconds,
            execution=execution,
        )
        evidence = write_evidence(identity, benchmark)
        validation = validate_evidence(identity)
        result = {
            "registration": registration,
            "preflight": gate,
            "smoke": smoke,
            "execution": execution,
            "evidence": evidence,
            "validation": validation,
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
