"""Operate only the pre-registered final Experiment B."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import subprocess
import time
from typing import Any

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)

from dai_sim.experiments.final.correlated_stress import (  # noqa: E402
    EVIDENCE_DIR,
    EXPERIMENT_B_PARENT_COMMIT,
    audit_checkpoints,
    experiment_a_regression_audit,
    preflight,
    run_matrix,
    run_smoke,
    validate_evidence,
    write_evidence,
    write_preregistration,
)
from dai_sim.experiments.final.programme import load_programme  # noqa: E402
from dai_sim.inputs.configuration import REPOSITORY_ROOT  # noqa: E402


EXPECTED_BRANCH = "feature/multi-collateral"
EXPECTED_UPSTREAM = "origin/feature/multi-collateral"
PRE_EXECUTION_ALLOWED_PATHS = {
    ".gitignore",
    "src/dai_sim/experiments/final/correlated_stress.py",
    "workflows/experiments/final/correlated_stress.py",
    "tests/experiments/final/test_correlated_stress.py",
    "tests/integration/test_test_collection_integrity.py",
    "tests/integration/test_test_hierarchy.py",
    "tests/workflows/test_migration.py",
    (
        "data/provenance/experiments/final/correlated_stress/"
        "correlated_stress_specification.json"
    ),
    (
        "data/provenance/experiments/final/correlated_stress/"
        "correlated_stress_registry.csv"
    ),
}


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def _is_descendant_of_parent(head: str) -> bool:
    result = subprocess.run(
        (
            "git",
            "merge-base",
            "--is-ancestor",
            EXPERIMENT_B_PARENT_COMMIT,
            head,
        ),
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _git_boundary() -> dict[str, Any]:
    """Enforce the original parent or a clean replay-compatible descendant."""
    head = _git("rev-parse", "HEAD").stdout.strip()
    branch = _git("branch", "--show-current").stdout.strip()
    upstream = _git(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    ).stdout.strip()
    staged = _git("diff", "--cached", "--name-only").stdout.splitlines()
    status_lines = _git(
        "status", "--porcelain=v1", "--untracked-files=all"
    ).stdout.splitlines()
    changed_paths = []
    for line in status_lines:
        path = line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        changed_paths.append(path)
    unexpected = sorted(
        path
        for path in changed_paths
        if path not in PRE_EXECUTION_ALLOWED_PATHS
    )
    original_parent = head == EXPERIMENT_B_PARENT_COMMIT
    clean_descendant = bool(
        not original_parent
        and not changed_paths
        and _is_descendant_of_parent(head)
    )
    if (
        not (original_parent or clean_descendant)
        or branch != EXPECTED_BRANCH
        or upstream != EXPECTED_UPSTREAM
        or staged
        or unexpected
    ):
        raise ValueError(
            "Experiment B Git boundary differs: "
            f"head={head}, branch={branch}, upstream={upstream}, "
            f"staged={staged}, unexpected={unexpected}."
        )
    return {
        "head": head,
        "branch": branch,
        "upstream": upstream,
        "index_empty": True,
        "mode": (
            "original_parent_pre_registration"
            if original_parent
            else "clean_descendant_replay"
        ),
        "authorised_changed_paths": sorted(changed_paths),
        "unexpected_changed_paths": [],
    }


def _preregister() -> dict[str, Any]:
    owner = load_programme()
    git_boundary = _git_boundary()
    experiment_a_regression_audit()
    first = write_preregistration(owner.programme_identity)
    second = write_preregistration(owner.programme_identity)
    if first != second:
        raise ValueError(
            "Experiment B pre-registration reconstruction differs."
        )
    return {
        **first,
        "deterministic_reconstruction": True,
        "git_boundary": git_boundary,
    }


def _preflight() -> dict[str, Any]:
    owner = load_programme()
    git_boundary = _git_boundary()
    required = (
        EVIDENCE_DIR / "correlated_stress_specification.json",
        EVIDENCE_DIR / "correlated_stress_registry.csv",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError(
            "Result-blind Experiment B pre-registration must precede "
            f"execution: {missing}."
        )
    return {
        **preflight(owner.programme_identity),
        "git_boundary": git_boundary,
    }


def _benchmark(
    *,
    workers: int,
    smoke_seconds: float,
    execution: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "measurement_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "execution_command": (
            "PYTHONPATH=src python "
            "workflows/experiments/final/correlated_stress.py "
            f"all --workers {workers}"
        ),
        "worker_count": workers,
        "smoke_wall_time_seconds": smoke_seconds,
        "full_wall_time_seconds": execution["wall_time_seconds"],
        "throughput_simulations_per_second": execution[
            "throughput_simulations_per_second"
        ],
        "completed_replications": execution["completed_replications"],
        "reused_replications": execution["reused_replications"],
        "resumed_replications": execution["resumed_replications"],
        "failed_replications": execution["failed_replications"],
        "rerun_replications": execution["rerun_replications"],
        "completed_simulations": execution["completed_simulations"],
        "checkpoint_count": execution["checkpoint_count"],
        "output_size_bytes": execution["output_size_bytes"],
        "free_storage_bytes": execution["free_storage_bytes"],
        "network_calls": 0,
        "calibration_runs": 0,
        "experiment_a_simulations": 0,
        "experiments_c_to_e_simulations": 0,
        "held_out_validation_runs": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-register and operate only the final correlated-stress "
            "Experiment B."
        )
    )
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
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    existing = EVIDENCE_DIR / "correlated_stress_benchmark.json"
    if not existing.is_file():
        raise FileNotFoundError(
            "Evidence reconstruction requires measured benchmark metadata."
        )
    return json.loads(existing.read_text(encoding="utf-8"))


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
        gate = _preflight()
        smoke = run_smoke()
        execution = run_matrix(
            identity,
            workers=args.workers,
            resume=args.operation == "resume",
            max_replications=args.max_replications,
        )
        result = {
            "preflight": gate,
            "smoke": smoke,
            "execution": execution,
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
            raise ValueError(
                "The complete operation cannot truncate replications."
            )
        registration = _preregister()
        gate = _preflight()
        smoke_started = time.perf_counter()
        smoke = run_smoke()
        smoke_seconds = time.perf_counter() - smoke_started
        execution = run_matrix(identity, workers=args.workers, resume=True)
        if not execution["complete"]:
            raise ValueError("Experiment B execution did not complete.")
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
