"""Pre-register or execute the local keeper-execution calibration."""

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

from dai_sim.calibration.keeper_execution import (  # noqa: E402
    DEFAULT_DIAGNOSTIC_ROOT,
    DEFAULT_EVIDENCE_DIR,
    DEFAULT_REGISTRY_PATH,
    KeeperExecutionDesign,
    run_keeper_execution_calibration,
    scientific_identity,
    preregistration_payload,
    write_preregistration,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("pre-register", "execute"),
        help="Write the result-blind snapshot or run the registered design.",
    )
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument(
        "--diagnostic-root", type=Path, default=DEFAULT_DIAGNOSTIC_ROOT
    )
    parser.add_argument("--registry-path", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--seed", type=int, default=20_260_730)
    parser.add_argument("--bootstrap-replications", type=int, default=2_000)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    design = KeeperExecutionDesign(
        random_seed=args.seed,
        bootstrap_replications=args.bootstrap_replications,
    )
    if args.mode == "pre-register":
        path = write_preregistration(args.diagnostic_root, design)
        payload = preregistration_payload(design)
        result = {
            "mode": "pre-register",
            "scientific_identity": scientific_identity(payload),
            "path": str(path),
            "estimates_calculated": False,
        }
    else:
        result = run_keeper_execution_calibration(
            evidence_dir=args.evidence_dir,
            diagnostic_root=args.diagnostic_root,
            registry_path=args.registry_path,
            design=design,
        )
        result["mode"] = "execute"
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
