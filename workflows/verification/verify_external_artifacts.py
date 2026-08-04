"""Verify an optional external archive of historical scientific checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
from typing import Any

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)

from dai_sim.inputs.submission_portability import (  # noqa: E402
    CONTRACTS_PATH,
    canonical_sha256,
    load_reconstruction_contracts,
)


def _snapshot(paths: list[Path], root: Path, algorithm: str) -> str:
    if algorithm == "filename_sha256_map":
        payload = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        }
        return canonical_sha256(payload)
    if algorithm == "relative_path_size_sha256_rows":
        payload = [
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in paths
        ]
        return canonical_sha256(payload)
    raise ValueError(f"Unsupported checkpoint manifest algorithm: {algorithm}.")


def verify_external_artifacts(
    artifact_root: Path,
    *,
    contracts_path: Path | None = None,
) -> dict[str, Any]:
    """Verify supplied checkpoints without mutating the archive."""
    root = artifact_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"External artefact root is absent: {root}.")
    contracts = load_reconstruction_contracts(
        contracts_path if contracts_path is not None else CONTRACTS_PATH,
        expected_study_count=None if contracts_path is not None else 10,
    )
    results: list[dict[str, Any]] = []
    for study in contracts["studies"]:
        expected_count = int(study["historical_checkpoint_count"])
        relative = Path(study["external_checkpoint_root"])
        checkpoint_root = root / relative
        paths = sorted(checkpoint_root.rglob("replication_*.json"))
        if len(paths) != expected_count:
            raise ValueError(
                f"Checkpoint count differs for {study['study_identifier']}: "
                f"{len(paths)} != {expected_count}."
            )
        manifest = study["checkpoint_content_manifest"]
        if manifest["status"] == "recorded_content_map":
            observed = _snapshot(paths, checkpoint_root, manifest["algorithm"])
            if observed != manifest["sha256"]:
                raise ValueError(
                    f"Checkpoint content differs for {study['study_identifier']}."
                )
        results.append(
            {
                "study_identifier": study["study_identifier"],
                "checkpoint_count": len(paths),
                "content_verification": manifest["status"],
            }
        )
    return {"status": "passed", "artifact_root": root.as_posix(), "studies": results}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--contracts", type=Path)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    result = verify_external_artifacts(
        arguments.artifact_root,
        contracts_path=arguments.contracts,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
