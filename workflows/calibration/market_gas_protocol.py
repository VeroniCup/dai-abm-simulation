"""Run the bounded, entirely local Phase 2A estimation workflow."""

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
from dai_sim.calibration.market import (
    CONFIDENCE_DIAGNOSTICS,
    CONFIDENCE_EVIDENCE,
    CONFIDENCE_PANEL,
    DEFAULT_FIGURES,
    DEFAULT_OUTPUT,
    DEFAULT_REPORT,
    ConfidenceCalibrationConfig,
    Phase2AConfig,
    run_confidence_calibration_infrastructure,
    run_phase2a,
)
from dai_sim.calibration.event_simulation import (
    DEFAULT_EVENT_DIAGNOSTICS,
    PROBE_INDICES,
    run_event_simulation_evidence,
)
from dai_sim.calibration.simulated_moments_search import (
    DEFAULT_SEARCH_ROOT,
    benchmark_workers,
    load_search_identity,
    prepare_search_cache,
    run_sobol_search,
    search_directory,
    summarise_sobol_search,
    validate_completed_search,
    validate_search_cache,
    validate_serial_parallel,
)
from dai_sim.calibration.simulated_moments_diagnostics import (
    HORIZON_TWO,
    PRIMARY_HORIZON,
    audit_completed_search,
    diagnostic_directory,
    objective_blind_candidate_panel,
    prepare_diagnostic_cache,
    run_extended_horizon_diagnosis,
    run_replication_ladder,
    summarise_precision_diagnosis,
    validate_completed_diagnosis,
    validate_diagnostic_cache,
)


def build_parser() -> argparse.ArgumentParser:
    """Build explicit local-only execution arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Estimate Phase 2A empirical candidates from locally validated "
            "Phase 1A–1D inputs, or build the bounded confidence-calibration "
            "infrastructure. This command does not access the network."
        )
    )
    parser.add_argument(
        "operation",
        nargs="?",
        choices=(
            "phase2a",
            "confidence-infrastructure",
            "event-simulation",
            "smm-search",
            "smm-precision",
        ),
        default="phase2a",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--figure-dir", type=Path, default=DEFAULT_FIGURES)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seed", type=int, default=20_260_726)
    parser.add_argument("--bootstrap-replications", type=int, default=200)
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument(
        "--input",
        type=Path,
        help=(
            "Ignored canonical historical panel required only by "
            "confidence-infrastructure."
        ),
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=CONFIDENCE_EVIDENCE,
    )
    parser.add_argument(
        "--source-evidence-dir",
        type=Path,
        default=CONFIDENCE_EVIDENCE,
        help="Registered accepted Stage 1 and residual evidence.",
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        default=CONFIDENCE_DIAGNOSTICS,
    )
    parser.add_argument("--validation-only", action="store_true")
    parser.add_argument(
        "--event-action",
        choices=("validate", "initial-state", "gates", "smoke", "benchmark", "all"),
        default="all",
        help="Bounded dormant event-simulation operation; never an optimiser.",
    )
    parser.add_argument(
        "--registry-id",
        default="confidence-smm-registry-a",
        help="Deterministic seed-registry root for event-simulation operations.",
    )
    parser.add_argument(
        "--probe-indices",
        default="0,127,255",
        help="Exact comma-separated interface probes; only 0,127,255 are accepted.",
    )
    parser.add_argument(
        "--event-diagnostics-dir",
        type=Path,
        default=DEFAULT_EVENT_DIAGNOSTICS,
    )
    parser.add_argument(
        "--search-action",
        choices=(
            "prepare-cache",
            "validate-cache",
            "benchmark",
            "equivalence",
            "run",
            "resume",
            "summarise",
            "validate",
        ),
        default="validate",
        help="Explicit fixed-design Sobol-search operation.",
    )
    parser.add_argument(
        "--search-root",
        type=Path,
        default=DEFAULT_SEARCH_ROOT,
        help="Ignored root for immutable caches and candidate checkpoints.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="Explicit spawned worker count; omitted values use the benchmark.",
    )
    parser.add_argument(
        "--recover-stale-lock",
        action="store_true",
        help="Explicitly recover a verified stale search lock.",
    )
    parser.add_argument(
        "--precision-action",
        choices=(
            "audit",
            "panel",
            "prepare-cache",
            "validate-cache",
            "run-ladder",
            "resume-ladder",
            "prepare-extended-cache",
            "run-extended",
            "resume-extended",
            "summarise",
            "validate",
        ),
        default="validate",
        help=(
            "Explicit Monte Carlo precision operation; never selects, "
            "optimises or validates a final parameter vector."
        ),
    )
    parser.add_argument(
        "--precision-root",
        type=Path,
        help="Ignored root containing resumable precision-diagnosis state.",
    )
    return parser


def main() -> int:
    """Execute once and print only compact provenance, never input rows."""
    parser = build_parser()
    args = parser.parse_args()
    if args.operation == "smm-precision":
        run_dir = (
            args.precision_root.resolve()
            if args.precision_root is not None
            else diagnostic_directory(evidence_dir=args.evidence_dir.resolve())
        )
        workers = args.workers or 4
        if workers < 1 or workers > 6:
            parser.error("--workers must be between 1 and 6")
        if args.precision_action == "audit":
            result = audit_completed_search()
        elif args.precision_action == "panel":
            result = objective_blind_candidate_panel()
        elif args.precision_action == "prepare-cache":
            if args.input is None:
                parser.error("smm-precision prepare-cache requires --input")
            result = prepare_diagnostic_cache(
                run_dir=run_dir,
                panel_path=args.input.resolve(),
                evidence_dir=args.evidence_dir.resolve(),
                workers=workers,
                horizon=PRIMARY_HORIZON,
            )
        elif args.precision_action == "validate-cache":
            result = validate_diagnostic_cache(
                run_dir, horizon=PRIMARY_HORIZON
            )
        elif args.precision_action in {"run-ladder", "resume-ladder"}:
            result = run_replication_ladder(
                run_dir=run_dir,
                workers=workers,
                resume=args.precision_action == "resume-ladder",
            )
        elif args.precision_action == "prepare-extended-cache":
            if args.input is None:
                parser.error(
                    "smm-precision prepare-extended-cache requires --input"
                )
            result = prepare_diagnostic_cache(
                run_dir=run_dir,
                panel_path=args.input.resolve(),
                evidence_dir=args.evidence_dir.resolve(),
                workers=workers,
                horizon=HORIZON_TWO,
            )
        elif args.precision_action in {"run-extended", "resume-extended"}:
            result = run_extended_horizon_diagnosis(
                run_dir=run_dir,
                workers=workers,
                resume=args.precision_action == "resume-extended",
            )
        elif args.precision_action == "summarise":
            result = summarise_precision_diagnosis(
                run_dir=run_dir,
                evidence_dir=args.evidence_dir.resolve(),
                register_manifest=(
                    args.evidence_dir.resolve()
                    == CONFIDENCE_EVIDENCE.resolve()
                ),
            )
        else:
            result = validate_completed_diagnosis(
                run_dir=run_dir,
                evidence_dir=args.evidence_dir.resolve(),
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.operation == "smm-search":
        identity, _ = load_search_identity(args.evidence_dir.resolve())
        run_dir = search_directory(identity, args.search_root.resolve())
        if args.search_action == "prepare-cache":
            if args.input is None:
                parser.error("smm-search prepare-cache requires an explicit --input")
            result = prepare_search_cache(
                panel_path=args.input.resolve(),
                evidence_dir=args.evidence_dir.resolve(),
                search_root=args.search_root.resolve(),
                workers=args.workers,
            )
        elif args.search_action == "validate-cache":
            result = validate_search_cache(
                run_dir, expected_identity=identity
            )
        elif args.search_action == "benchmark":
            result = benchmark_workers(run_dir)
        else:
            benchmark_path = run_dir / "worker_benchmark.json"
            if args.workers is None:
                if not benchmark_path.is_file():
                    parser.error(
                        "Run the worker benchmark or supply explicit --workers"
                    )
                workers = int(
                    json.loads(benchmark_path.read_text(encoding="utf-8"))[
                        "selected_workers"
                    ]
                )
            else:
                workers = args.workers
            if workers < 1 or workers > 6:
                parser.error("--workers must be between 1 and 6")
            if args.search_action == "equivalence":
                result = validate_serial_parallel(run_dir, workers=workers)
            elif args.search_action in {"run", "resume"}:
                result = run_sobol_search(
                    run_dir,
                    workers=workers,
                    resume=args.search_action == "resume",
                    recover_stale_lock=args.recover_stale_lock,
                )
            elif args.search_action == "summarise":
                result = summarise_sobol_search(
                    run_dir,
                    evidence_dir=args.evidence_dir.resolve(),
                    register_manifest=(
                        args.evidence_dir.resolve()
                        == CONFIDENCE_EVIDENCE.resolve()
                    ),
                )
            else:
                result = validate_completed_search(
                    run_dir,
                    evidence_dir=args.evidence_dir.resolve(),
                )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.operation == "event-simulation":
        try:
            probe_indices = tuple(
                int(value.strip())
                for value in args.probe_indices.split(",")
                if value.strip()
            )
        except ValueError:
            parser.error("--probe-indices must contain comma-separated integers")
        if probe_indices != PROBE_INDICES:
            parser.error("--probe-indices must be exactly 0,127,255")
        action = "validate" if args.validation_only else args.event_action
        result = run_event_simulation_evidence(
            panel_path=(args.input or CONFIDENCE_PANEL).resolve(),
            source_evidence_dir=args.source_evidence_dir.resolve(),
            evidence_dir=args.evidence_dir.resolve(),
            diagnostics_dir=args.event_diagnostics_dir.resolve(),
            registry_id=args.registry_id,
            probe_indices=probe_indices,
            action=action,
            register_manifest=(
                args.evidence_dir.resolve() == CONFIDENCE_EVIDENCE.resolve()
            ),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.operation == "confidence-infrastructure":
        if args.input is None:
            parser.error(
                "confidence-infrastructure requires an explicit --input path"
            )
        result = run_confidence_calibration_infrastructure(
            ConfidenceCalibrationConfig(
                input_path=args.input.resolve(),
                evidence_dir=args.evidence_dir.resolve(),
                diagnostics_dir=args.diagnostics_dir.resolve(),
                random_seed=args.seed,
                bootstrap_replications=args.bootstrap_replications,
                validation_only=args.validation_only,
            )
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    config = Phase2AConfig(
        output_dir=args.output_dir.resolve(),
        figure_dir=args.figure_dir.resolve(),
        report_path=args.report_path.resolve(),
        random_seed=args.seed,
        bootstrap_replications=args.bootstrap_replications,
        write_figures=not args.no_figures,
        write_report=not args.no_report,
    )
    result = run_phase2a(config)
    print(
        json.dumps(
            {
                "metadata_path": result["metadata_path"],
                "registry_path": result["registry_path"],
                "parameter_count": result["parameter_count"],
                "candidate_count": result["candidate_count"],
                "output_count": len(result["outputs"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
