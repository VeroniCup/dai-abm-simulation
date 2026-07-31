"""Operate the pre-registered final programme and Experiment A only."""

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

from dai_sim.experiments.final.idiosyncratic_diversification import (
    EVIDENCE_DIR,
    STARTING_CODE_PARENT,
    audit_checkpoints,
    preflight,
    run_matrix,
    run_smoke,
    validate_evidence,
    write_evidence,
    write_preregistration,
)
from dai_sim.experiments.final.programme import (
    DEFAULT_PREREGISTRATION_DIR,
    load_programme,
    update_programme_manifest,
    write_programme_preregistration,
)


def _head() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _preregister() -> dict[str, Any]:
    owner = load_programme()
    if _head() != STARTING_CODE_PARENT:
        raise ValueError("The final-programme parent commit differs.")
    first_master = write_programme_preregistration(owner)
    second_master = write_programme_preregistration(owner)
    if first_master != second_master:
        raise ValueError("Master pre-registration reconstruction differs.")
    manifest = update_programme_manifest(owner)
    first_a = write_preregistration(owner.programme_identity)
    second_a = write_preregistration(owner.programme_identity)
    if first_a != second_a:
        raise ValueError("Experiment A pre-registration reconstruction differs.")
    return {
        "programme": first_master,
        "experiment_a": first_a,
        "manifest": manifest,
        "deterministic_reconstruction": True,
    }


def _preflight() -> dict[str, Any]:
    owner = load_programme()
    required_preregistrations = (
        DEFAULT_PREREGISTRATION_DIR / "final_programme_specification.json",
        DEFAULT_PREREGISTRATION_DIR / "final_programme_registry.csv",
        DEFAULT_PREREGISTRATION_DIR / "final_programme_decision.json",
        DEFAULT_PREREGISTRATION_DIR / "final_programme_reproducibility.json",
        EVIDENCE_DIR / "idiosyncratic_diversification_specification.json",
        EVIDENCE_DIR / "idiosyncratic_diversification_registry.csv",
    )
    missing = [
        str(path)
        for path in required_preregistrations
        if not path.is_file()
    ]
    if missing:
        raise ValueError(
            "Result-blind pre-registration must precede execution preflight: "
            f"{missing}."
        )
    master_specification = json.loads(
        required_preregistrations[0].read_text(encoding="utf-8")
    )
    experiment_specification = json.loads(
        required_preregistrations[4].read_text(encoding="utf-8")
    )
    if (
        master_specification["programme_identity"] != owner.programme_identity
        or experiment_specification["programme_identity"]
        != owner.programme_identity
    ):
        raise ValueError("Pre-registration identities differ from current code.")
    executable = [
        experiment.identifier
        for experiment in owner.experiments
        if experiment.execution_status == "authorised_current_pass"
    ]
    if executable != ["A_idiosyncratic_diversification"]:
        raise ValueError("Exactly Experiment A must be executable.")
    if owner.experiments_by_identifier[
        "E_oracle_delay"
    ].dependency_status != "oracle_delay_freeze_required":
        raise ValueError("Experiment E is not blocked on its delay freeze.")
    result = preflight(owner.programme_identity)
    return {
        **result,
        "master_cell_count": owner.planned_core_cells,
        "master_simulation_count": owner.planned_core_simulations,
        "executable_experiments": executable,
        "experiments_b_to_d_executed": False,
        "experiment_e_executed": False,
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
        "experiments_b_to_e_simulations": 0,
        "held_out_validation_runs": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-register the final programme and operate only its authorised "
            "idiosyncratic-diversification experiment."
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
    existing = EVIDENCE_DIR / "idiosyncratic_diversification_benchmark.json"
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
        result = {
            "preflight": _preflight(),
            "smoke": run_smoke(),
        }
    elif args.operation in {"run", "resume"}:
        gate = _preflight()
        smoke = run_smoke()
        result = run_matrix(
            identity,
            workers=args.workers,
            resume=args.operation == "resume",
            max_replications=args.max_replications,
        )
        result = {
            "preflight": gate,
            "smoke": smoke,
            "execution": result,
        }
    elif args.operation == "audit-checkpoints":
        result = audit_checkpoints(identity)
    elif args.operation == "reconstruct-evidence":
        result = write_evidence(identity, _load_benchmark(args.benchmark_json))
    elif args.operation == "validate-completed":
        result = validate_evidence(identity)
    else:
        if args.max_replications is not None:
            raise ValueError("The complete operation cannot truncate replications.")
        registration = _preregister()
        gate = _preflight()
        smoke_started = time.perf_counter()
        smoke = run_smoke()
        smoke_seconds = time.perf_counter() - smoke_started
        execution = run_matrix(identity, workers=args.workers, resume=True)
        if not execution["complete"]:
            raise ValueError("Experiment A execution did not complete.")
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
