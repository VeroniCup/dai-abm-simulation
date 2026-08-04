"""Build and verify the exact manifest-filtered code bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import sys

_WORKFLOW_BOOTSTRAP = next(
    parent / "workflows" / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "workflows" / "_bootstrap.py").is_file()
)
runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)

from dai_sim.common.submission_bundle import (  # noqa: E402
    build_bundle,
    build_inventory,
    canonical_json_bytes,
    verify_bundle,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("inventory", "validate", "build", "verify", "all")
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--include-manifest", type=Path, required=True)
    parser.add_argument("--exclude-manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--record", type=Path)
    return parser


def _write_record(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    """Run one deterministic submission-bundle operation."""
    args = _parser().parse_args(argv)
    root = args.repository_root.resolve()
    builder_source = Path(__file__).resolve()
    inventory = build_inventory(
        repository_root=root,
        include_manifest=args.include_manifest.resolve(),
        exclude_manifest=args.exclude_manifest.resolve(),
        builder_source=builder_source,
    )
    if args.record is not None:
        _write_record(args.record.resolve(), inventory)

    if args.command == "inventory":
        print(json.dumps(inventory, indent=2, sort_keys=True))
        return 0
    if args.command == "validate":
        print(
            json.dumps(
                {
                    "status": "passed",
                    "submission_bundle_identity": inventory[
                        "submission_bundle_identity"
                    ],
                    "included_file_count": inventory["included_file_count"],
                    "included_total_bytes": inventory["included_total_bytes"],
                    "unmatched_include_globs": inventory[
                        "unmatched_include_globs"
                    ],
                },
                sort_keys=True,
            )
        )
        return 0
    if args.destination is None:
        raise ValueError(f"{args.command} requires --destination.")
    destination = args.destination.resolve()
    if args.command == "verify":
        print(json.dumps(verify_bundle(destination), sort_keys=True))
        return 0
    if args.command in {"build", "all"}:
        build_bundle(root, destination, inventory)
    if args.command == "all":
        print(json.dumps(verify_bundle(destination), sort_keys=True))
    else:
        print(destination)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"submission bundle error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
