"""Reconstruct the registered H4 recovery evidence synthesis."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from typing import Any

from dai_sim.experiments.final.recovery_behaviour_synthesis import (
    MATRIX_COLUMNS,
    SOURCE_COLUMNS,
    SYNTHESIS_PARENT_COMMIT,
    _csv_bytes,
    build_evidence_matrix,
    build_source_registry,
    classify_synthesis,
    validate_evidence,
    validate_source_registry,
    write_evidence,
)
from dai_sim.inputs.configuration import REPOSITORY_ROOT


OPERATIONS = (
    "inventory",
    "validate-sources",
    "build-matrix",
    "classify",
    "reconstruct",
    "all",
)


def _git(*arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def boundary() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    parent_subject = _git("show", "-s", "--format=%s", SYNTHESIS_PARENT_COMMIT)
    branch = _git("branch", "--show-current")
    if _git("merge-base", SYNTHESIS_PARENT_COMMIT, head) != SYNTHESIS_PARENT_COMMIT:
        raise ValueError("The current history does not descend from the H4 boundary.")
    if parent_subject != "Evaluate oracle delay effects":
        raise ValueError("The registered H4 synthesis parent subject changed.")
    if branch != "feature/multi-collateral":
        raise ValueError("The H4 synthesis is authorised on feature/multi-collateral.")
    return {
        "branch": branch,
        "head": head,
        "synthesis_parent_commit": SYNTHESIS_PARENT_COMMIT,
        "synthesis_parent_subject": parent_subject,
    }


def inventory() -> dict[str, Any]:
    rows = build_source_registry()
    validate_source_registry(rows)
    payload = _csv_bytes(rows, SOURCE_COLUMNS)
    return {
        "boundary": boundary(),
        "source_count": len(rows),
        "source_identifiers": [row["source_identifier"] for row in rows],
        "source_registry_sha256": hashlib.sha256(payload).hexdigest(),
    }


def validate_sources() -> dict[str, Any]:
    result = inventory()
    return {
        **result,
        "passed": True,
        "registered_decisions_primary": True,
        "statistical_pooling": False,
        "held_out_sources": 0,
        "usdc_svb_sources": 0,
    }


def build_matrix() -> dict[str, Any]:
    validate_sources()
    rows = build_evidence_matrix()
    payload = _csv_bytes(rows, MATRIX_COLUMNS)
    return {
        "finding_count": len(rows),
        "components": sorted({row["component"] for row in rows}),
        "matrix_sha256": hashlib.sha256(payload).hexdigest(),
        "written": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    return parser


def main() -> int:
    operation = build_parser().parse_args().operation
    if operation == "inventory":
        result = inventory()
    elif operation == "validate-sources":
        result = validate_sources()
    elif operation == "build-matrix":
        result = build_matrix()
    elif operation == "classify":
        validate_sources()
        result = classify_synthesis()
    elif operation == "reconstruct":
        validate_sources()
        result = write_evidence()
    else:
        result = {
            "inventory": inventory(),
            "source_validation": validate_sources(),
            "matrix": build_matrix(),
            "classification": classify_synthesis(),
            "reconstruction": write_evidence(),
            "validation": validate_evidence(),
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
