"""Run the pre-registered Experiment E oracle-delay matrix."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

from dai_sim.experiments.final.oracle_delay import (
    EVIDENCE_DIR,
    EXPERIMENT_E_PARENT_COMMIT,
    audit_checkpoints,
    preflight,
    run_matrix,
    run_smoke,
    validate_evidence,
    write_evidence,
    write_preregistration,
)
from dai_sim.experiments.final.programme import load_programme
from dai_sim.inputs.configuration import REPOSITORY_ROOT


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
    subject = _git("log", "-1", "--format=%s").stdout.strip()
    staged = _git("diff", "--cached", "--name-only").stdout.splitlines()
    if head != EXPERIMENT_E_PARENT_COMMIT:
        raise ValueError("Experiment E parent commit changed.")
    if subject != "Freeze oracle delay sensitivities":
        raise ValueError("Experiment E parent subject changed.")
    if staged:
        raise ValueError("Experiment E requires an empty Git index.")
    return {
        "head": head,
        "subject": subject,
        "branch": _git("branch", "--show-current").stdout.strip(),
        "staged_paths": staged,
    }


def _preregister() -> dict[str, Any]:
    programme = load_programme()
    first = write_preregistration(programme.programme_identity)
    specification = (EVIDENCE_DIR / "oracle_delay_specification.json").read_bytes()
    registry = (EVIDENCE_DIR / "oracle_delay_registry.csv").read_bytes()
    second = write_preregistration(programme.programme_identity)
    if (
        specification != (EVIDENCE_DIR / "oracle_delay_specification.json").read_bytes()
        or registry != (EVIDENCE_DIR / "oracle_delay_registry.csv").read_bytes()
        or first != second
    ):
        raise ValueError("Experiment E pre-registration is not deterministic.")
    return {
        **first,
        "deterministic_reconstruction": True,
        "isolated_reconstructions": 2,
    }


def _preflight() -> dict[str, Any]:
    programme = load_programme()
    return {
        "git": _git_boundary(),
        "scientific": preflight(programme.programme_identity),
        "programme_boundary": {
            "experiment_e_master_status": programme.experiments_by_identifier[
                "E_oracle_delay"
            ].execution_status,
            "oracle_freeze_supersedes_master_blocker": True,
            "h4_status": programme.h4_synthesis.execution_status,
        },
    }


def _benchmark(
    *, workers: int, smoke_seconds: float, execution: dict[str, Any]
) -> dict[str, Any]:
    audit = execution["checkpoint_audit"]
    wall_time = float(execution["elapsed_seconds"])
    return {
        "schema_version": 1,
        "measurement_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "execution_command": (
            "PYTHONPATH=src python workflows/experiments/final/oracle_delay.py "
            f"all --workers {workers}"
        ),
        "worker_count": workers,
        "smoke_wall_time_seconds": smoke_seconds,
        "full_wall_time_seconds": wall_time,
        "throughput_simulations_per_second": 0.0
        if wall_time == 0.0
        else 768 / wall_time,
        "timing_method": "in_memory_wall_clock",
        "completed_replications": execution["completed_replications"],
        "reused_replications": execution["reused_replications"],
        "resumed_replications": execution["resumed_replications"],
        "failed_replications": execution["failed_replications"],
        "rerun_replications": execution["rerun_replications"],
        "completed_simulations": 768,
        "checkpoint_count": audit["valid_count"],
        "missing_checkpoint_count": audit["missing_count"],
        "duplicate_checkpoint_count": audit["duplicate_count"],
        "orphan_checkpoint_count": audit["orphan_count"],
        "output_size_bytes": audit["checkpoint_bytes"],
        "free_storage_bytes": shutil.disk_usage(REPOSITORY_ROOT).free,
        "network_calls": 0,
        "experiments_a_b_c_d_simulations": 0,
        "calibration_runs": 0,
        "oracle_recalibration_runs": 0,
        "held_out_validation_runs": 0,
        "delay_selection_runs": 0,
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
    parser.add_argument("--benchmark-json", type=Path)
    return parser


def _load_benchmark(path: Path | None) -> dict[str, Any]:
    selected = (
        path if path is not None else EVIDENCE_DIR / "oracle_delay_benchmark.json"
    )
    return json.loads(selected.read_text(encoding="utf-8"))


def main() -> int:
    args = build_parser().parse_args()
    programme = load_programme()
    identity = programme.programme_identity
    if args.operation == "pre-register":
        result = _preregister()
    elif args.operation == "preflight":
        result = _preflight()
    elif args.operation == "run-smoke":
        result = {"preflight": _preflight(), "smoke": run_smoke()}
    elif args.operation in {"run", "resume"}:
        result = {
            "preflight": _preflight(),
            "execution": run_matrix(
                programme_identity=identity,
                workers=args.workers,
                resume=args.operation == "resume",
            ),
        }
    elif args.operation == "audit-checkpoints":
        result = audit_checkpoints(identity)
    elif args.operation == "reconstruct-evidence":
        result = write_evidence(identity, _load_benchmark(args.benchmark_json))
    elif args.operation == "validate-completed":
        result = validate_evidence(identity)
    else:
        registration = _preregister()
        gate = _preflight()
        smoke_started = time.perf_counter()
        smoke = run_smoke()
        smoke_seconds = time.perf_counter() - smoke_started
        execution = run_matrix(
            programme_identity=identity, workers=args.workers, resume=True
        )
        benchmark = _benchmark(
            workers=args.workers, smoke_seconds=smoke_seconds, execution=execution
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
