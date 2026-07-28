"""Retrieve one immutable Dune execution-result page directly to disk.

The command performs exactly one HTTP request, never submits an execution and
never retries.  The API key is read only from the environment and is not
printed or persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
REPOSITORY_ROOT = runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)
import tempfile

import requests


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def retrieve_page(
    execution_id: str,
    output: Path,
    *,
    limit: int,
    offset: int,
    timeout: int = 240,
) -> dict[str, object]:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite existing result page: {output}")
    key = os.environ.get("DUNE_API_KEY")
    if not key:
        raise RuntimeError("DUNE_API_KEY is not set")
    if not 1 <= limit <= 32_000 or offset < 0:
        raise RuntimeError("invalid Dune result page bounds")
    response = requests.get(
        f"https://api.dune.com/api/v1/execution/{execution_id}/results",
        headers={"X-Dune-API-Key": key},
        params={"limit": limit, "offset": offset},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result") or {}
    rows = result.get("rows")
    metadata = result.get("metadata") or {}
    if not isinstance(rows, list):
        raise RuntimeError("Dune response contains no result rows")
    total = metadata.get("total_row_count")
    if not isinstance(total, int):
        raise RuntimeError("Dune response contains no total row count")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(name)
    encoded = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)
    _fsync_directory(output.parent)
    return {
        "execution_id": execution_id,
        "limit": limit,
        "offset": offset,
        "returned_rows": len(rows),
        "api_reported_total_rows": total,
        "path": str(output),
        "size_bytes": output.stat().st_size,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "physical_request_count": 1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--offset", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    print(json.dumps(retrieve_page(
        args.execution_id,
        args.output,
        limit=args.limit,
        offset=args.offset,
        timeout=args.timeout,
    ), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
