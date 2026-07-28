"""Acquire one explicit Dune execution and preserve its CSV result as raw data.

Saved-query mode submits one existing query ID. Temporary-query mode accepts a
query and execution already created by the caller and cannot submit another.
Both modes download each result page at most once and stop without retrying.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
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
import shutil
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from workflows.market.validate import validate_prices


API_ROOT = "https://api.dune.com/api/v1"
DEFAULT_OUTPUT = Path(
    "data/market/raw/dune_prices_hourly_2021-06-01_2024-06-30.csv"
)
DEFAULT_MANIFEST = Path("data/provenance/data_manifest.csv")
DEFAULT_PROVENANCE_DIRECTORY = Path("data/market/provenance")
DEFAULT_SQL_FILE = Path("sql/dune_hourly_market_prices.sql")
REQUESTED_START = "2021-06-01 00:00:00 UTC"
REQUESTED_END = "2024-07-01 00:00:00 UTC"
TERMINAL_FAILURE_STATES = {
    "QUERY_STATE_FAILED",
    "QUERY_STATE_CANCELED",
    "QUERY_STATE_CANCELLED",
    "QUERY_STATE_EXPIRED",
    "QUERY_STATE_COMPLETED_PARTIAL",
}
MANIFEST_EXTRA_COLUMNS = (
    "provider",
    "dune_table",
    "query_type",
    "query_id",
    "temporary_query_id",
    "execution_id",
    "sql_file_path",
    "sql_sha256",
    "acquisition_timestamp_utc",
    "requested_start_utc",
    "requested_end_utc",
    "actual_minimum_timestamp_utc",
    "actual_maximum_timestamp_utc",
    "raw_file_path",
    "raw_file_size_bytes",
    "sha256",
    "row_count",
    "validation_status",
    "source_distribution",
    "missing_hour_notes",
    "source_change_notes",
    "credit_delta",
)
SERIES = (
    (
        "dune_hourly_eth_usd",
        "eth_market_price",
        "USD_per_ETH",
        "ETH is represented by the Dune WETH instrument.",
    ),
    (
        "dune_hourly_wbtc_usd",
        "btc_market_price",
        "USD_per_WBTC",
        "WBTC is the BTC-collateral price proxy; it is not native BTC.",
    ),
    (
        "dune_hourly_dai_usd",
        "dai_market_price",
        "USD_per_DAI",
        "DAI price from the Ethereum DAI contract.",
    ),
    (
        "dune_hourly_usdc_usd",
        "stable_market_price",
        "USD_per_USDC",
        "USDC is the model's stable-collateral price series.",
    ),
)


class DuneAcquisitionError(RuntimeError):
    """Raised for a terminal acquisition problem."""


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


def _request(
    api_key: str,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> tuple[bytes, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"X-Dune-API-Key": api_key}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=120) as response:
            return response.read(), response.headers
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        detail = detail.replace(api_key, "[REDACTED]")
        raise DuneAcquisitionError(
            f"Dune API returned HTTP {exc.code}: {detail}"
        ) from exc
    except URLError as exc:
        raise DuneAcquisitionError(f"Dune API request failed: {exc.reason}") from exc


def _request_json(
    api_key: str,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body, _ = _request(api_key, method, url, payload)
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DuneAcquisitionError("Dune returned invalid JSON.") from exc
    if not isinstance(result, dict):
        raise DuneAcquisitionError("Dune returned an unexpected JSON structure.")
    return result


def execute_saved_query(api_key: str, query_id: int) -> str:
    """Submit a saved query once on the Small engine."""
    result = _request_json(
        api_key,
        "POST",
        f"{API_ROOT}/query/{query_id}/execute",
        {"performance": "small"},
    )
    execution_id = result.get("execution_id")
    if not execution_id:
        raise DuneAcquisitionError(
            "Dune did not return an execution_id for the saved query."
        )
    return str(execution_id)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write metadata atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def poll_execution(
    api_key: str,
    execution_id: str,
    timeout_seconds: int,
    poll_seconds: float,
    state_path: Path,
    state_record: dict[str, Any],
) -> None:
    """Poll one execution without submitting a replacement execution."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        status = _request_json(
            api_key,
            "GET",
            f"{API_ROOT}/execution/{execution_id}/status",
        )
        state = str(status.get("state", "UNKNOWN"))
        state_record["state"] = state
        state_record["last_checked_at_utc"] = utc_now().isoformat()
        write_json(state_path, state_record)
        print(f"Dune execution {execution_id}: {state}")
        if state == "QUERY_STATE_COMPLETED":
            return
        if state in TERMINAL_FAILURE_STATES:
            error = status.get("error") or status.get("error_metadata") or state
            raise DuneAcquisitionError(f"Execution stopped in {state}: {error}")
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Polling timed out. The script did not retry or replace execution "
                f"{execution_id}; resume it with --resume-execution-id."
            )
        time.sleep(poll_seconds)


def _next_offset(headers: Any) -> int | None:
    value = headers.get("X-Dune-Next-Offset")
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise DuneAcquisitionError(
            f"Invalid X-Dune-Next-Offset header: {value!r}."
        ) from exc


def download_csv_once_per_page(
    api_key: str,
    execution_id: str,
    output_path: Path,
    page_size: int,
) -> int:
    """Download unique CSV pages and combine them without changing row values."""
    parts_directory = output_path.with_suffix(output_path.suffix + ".parts")
    download_state_path = parts_directory / "download_state.json"
    parts_directory.mkdir(parents=True, exist_ok=True)

    if download_state_path.exists():
        state = json.loads(download_state_path.read_text(encoding="utf-8"))
        if state.get("execution_id") != execution_id:
            raise DuneAcquisitionError(
                "Existing download state belongs to a different execution."
            )
        offset = state.get("next_offset")
        visited_offsets = {int(value) for value in state.get("visited_offsets", [])}
    else:
        offset = 0
        visited_offsets: set[int] = set()

    while offset is not None:
        if offset in visited_offsets:
            raise DuneAcquisitionError(
                f"Refusing a duplicate export request for result offset {offset}."
            )
        query = urlencode({"limit": page_size, "offset": offset})
        body, headers = _request(
            api_key,
            "GET",
            f"{API_ROOT}/execution/{execution_id}/results/csv?{query}",
        )
        part_path = parts_directory / f"offset_{offset:012d}.csv"
        if part_path.exists():
            raise DuneAcquisitionError(f"Result page already exists: {part_path}.")
        part_path.write_bytes(body)
        visited_offsets.add(offset)
        offset = _next_offset(headers)
        write_json(
            download_state_path,
            {
                "execution_id": execution_id,
                "next_offset": offset,
                "visited_offsets": sorted(visited_offsets),
            },
        )

    part_paths = [
        parts_directory / f"offset_{value:012d}.csv"
        for value in sorted(visited_offsets)
    ]
    if not part_paths:
        raise DuneAcquisitionError("Dune returned no CSV result pages.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial_output = output_path.with_suffix(output_path.suffix + ".partial")
    first_header: bytes | None = None
    with partial_output.open("wb") as destination:
        for part_path in part_paths:
            content = part_path.read_bytes()
            header, separator, remainder = content.partition(b"\n")
            if not separator:
                raise DuneAcquisitionError(f"CSV page has no header: {part_path}.")
            normalised_header = header.rstrip(b"\r")
            if first_header is None:
                first_header = normalised_header
                destination.write(content)
            else:
                if normalised_header != first_header:
                    raise DuneAcquisitionError(
                        f"CSV header changed between result pages: {part_path}."
                    )
                destination.write(remainder)
    partial_output.replace(output_path)
    shutil.rmtree(parts_directory)
    return len(part_paths)


def inspect_csv(path: Path) -> dict[str, Any]:
    """Calculate raw-file coverage metadata without changing the file."""
    row_count = 0
    minimum_timestamp: str | None = None
    maximum_timestamp: str | None = None
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "timestamp_utc" not in reader.fieldnames:
            raise DuneAcquisitionError(
                "Downloaded CSV does not contain timestamp_utc."
            )
        for row in reader:
            timestamp = str(row["timestamp_utc"])
            minimum_timestamp = (
                timestamp if minimum_timestamp is None else min(minimum_timestamp, timestamp)
            )
            maximum_timestamp = (
                timestamp if maximum_timestamp is None else max(maximum_timestamp, timestamp)
            )
            row_count += 1
    return {
        "row_count": row_count,
        "minimum_timestamp_utc": minimum_timestamp,
        "maximum_timestamp_utc": maximum_timestamp,
    }


def sha256_file(path: Path) -> str:
    """Return the SHA-256 checksum of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_manifest_records(
    manifest_path: Path,
    output_path: Path,
    query_id: int,
    execution_id: str,
    query_type: str,
    sql_file_path: Path,
    sql_checksum: str,
    acquired_at: datetime,
    checksum: str,
    coverage: dict[str, Any],
    validation_report: dict[str, Any],
) -> None:
    """Append four provenance records after a successful acquisition."""
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        existing = list(reader)
    missing_extra = set(MANIFEST_EXTRA_COLUMNS) - set(fieldnames)
    if missing_extra:
        raise DuneAcquisitionError(
            f"Manifest is missing acquisition columns: {sorted(missing_extra)}."
        )
    if any(row.get("execution_id") == execution_id for row in existing):
        raise DuneAcquisitionError(
            f"Manifest already contains execution {execution_id}."
        )

    source_distribution = {
        asset: values["source_distribution"]
        for asset, values in validation_report["by_asset"].items()
    }
    missing_hour_notes = "; ".join(
        f"{asset}:{values['missing_hour_count']}"
        for asset, values in validation_report["by_asset"].items()
    )
    source_change_notes = "; ".join(
        f"{asset}:{values['source_change_count']}"
        for asset, values in validation_report["by_asset"].items()
    )
    common = {
        "source_name": "dune_prices_hour",
        "source_reference": f"https://dune.com/queries/{query_id}",
        "raw_filename": output_path.name,
        "download_date": acquired_at.date().isoformat(),
        "native_frequency": "1h",
        "processed_frequency": "1h",
        "timezone": "UTC",
        "sample_start": str(coverage["minimum_timestamp_utc"]),
        "sample_end": str(coverage["maximum_timestamp_utc"]),
        "transformation": "None; raw Dune result retained unchanged.",
        "licence_or_access_note": "Dune API; access subject to Dune terms.",
        "provider": "Dune",
        "dune_table": "prices.hour",
        "query_type": query_type,
        "query_id": str(query_id),
        "temporary_query_id": str(query_id) if query_type == "private temporary" else "",
        "execution_id": execution_id,
        "sql_file_path": str(sql_file_path),
        "sql_sha256": sql_checksum,
        "acquisition_timestamp_utc": acquired_at.isoformat(),
        "requested_start_utc": REQUESTED_START,
        "requested_end_utc": REQUESTED_END,
        "actual_minimum_timestamp_utc": str(coverage["minimum_timestamp_utc"]),
        "actual_maximum_timestamp_utc": str(coverage["maximum_timestamp_utc"]),
        "raw_file_path": str(output_path),
        "raw_file_size_bytes": str(output_path.stat().st_size),
        "sha256": checksum,
        "row_count": str(coverage["row_count"]),
        "validation_status": (
            "passed" if validation_report["validation_passed"] else "failed"
        ),
        "source_distribution": json.dumps(source_distribution, sort_keys=True),
        "missing_hour_notes": missing_hour_notes,
        "source_change_notes": source_change_notes,
        "credit_delta": "",
    }
    with manifest_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        for series_name, model_variable, unit, notes in SERIES:
            row = {column: "" for column in fieldnames}
            row.update(common)
            row.update(
                {
                    "series_name": series_name,
                    "model_variable": model_variable,
                    "currency_or_unit": unit,
                    "notes": notes,
                }
            )
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("saved-query", "temporary-query"),
        help="Select the execution source explicitly; modes never fall back.",
    )
    parser.add_argument("--query-id", required=True, type=int)
    parser.add_argument(
        "--execution-id",
        help="Existing execution ID; required only for temporary-query mode.",
    )
    parser.add_argument(
        "--resume-execution-id",
        help="Resume saved-query mode without submitting a replacement execution.",
    )
    parser.add_argument("--creation-timestamp-utc")
    parser.add_argument("--sql-file", type=Path, default=DEFAULT_SQL_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--validation-report", type=Path)
    parser.add_argument(
        "--provenance-directory",
        type=Path,
        default=DEFAULT_PROVENANCE_DIRECTORY,
    )
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--page-size", type=int, default=50_000)
    return parser.parse_args()


def main() -> int:
    """Execute the acquisition workflow."""
    args = parse_args()
    if args.timeout_seconds <= 0 or args.poll_seconds <= 0 or args.page_size <= 0:
        raise SystemExit("Timeout, polling interval and page size must be positive.")
    api_key = os.environ.get("DUNE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DUNE_API_KEY is not set in the environment.")
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite existing raw data: {args.output}")
    if not args.manifest.exists():
        raise SystemExit(f"Data manifest does not exist: {args.manifest}")
    if not args.sql_file.exists():
        raise SystemExit(f"Production SQL file does not exist: {args.sql_file}")
    if args.mode == "temporary-query":
        if not args.execution_id:
            raise SystemExit(
                "temporary-query mode requires --execution-id from the creating call."
            )
        if args.resume_execution_id:
            raise SystemExit(
                "temporary-query mode does not accept --resume-execution-id."
            )
    elif args.execution_id:
        raise SystemExit("saved-query mode does not accept --execution-id.")

    sql_checksum = sha256_file(args.sql_file)
    print(f"Local SQL SHA-256: {sql_checksum}")

    state_path = args.provenance_directory / (
        args.output.stem + ".execution.json"
    )
    if (
        state_path.exists()
        and args.mode == "saved-query"
        and not args.resume_execution_id
    ):
        raise SystemExit(
            f"Execution state already exists at {state_path}; resume its execution "
            "instead of submitting a replacement."
        )

    submitted_at = utc_now()
    if args.mode == "temporary-query":
        execution_id = str(args.execution_id)
        query_type = "private temporary"
    else:
        execution_id = args.resume_execution_id or execute_saved_query(
            api_key, args.query_id
        )
        query_type = "saved"
    state_record = {
        "query_id": args.query_id,
        "execution_id": execution_id,
        "query_type": query_type,
        "engine": "small",
        "sql_file_path": str(args.sql_file),
        "sql_sha256": sql_checksum,
        "creation_timestamp_utc": args.creation_timestamp_utc,
        "submitted_or_resumed_at_utc": submitted_at.isoformat(),
        "state": (
            "ACCEPTED_EXISTING_EXECUTION"
            if args.mode == "temporary-query"
            else ("SUBMITTED" if not args.resume_execution_id else "RESUMED")
        ),
    }
    write_json(state_path, state_record)

    try:
        poll_execution(
            api_key,
            execution_id,
            args.timeout_seconds,
            args.poll_seconds,
            state_path,
            state_record,
        )
        page_count = download_csv_once_per_page(
            api_key, execution_id, args.output, args.page_size
        )
        acquired_at = utc_now()
        coverage = inspect_csv(args.output)
        checksum = sha256_file(args.output)
        validation_report, validation_failures = validate_prices(args.output)
        validation_report_path = (
            args.validation_report
            or args.provenance_directory / (
                args.output.stem + ".validation.json"
            )
        )
        write_json(validation_report_path, validation_report)
        state_record.update(
            {
                "state": "ACQUIRED",
                "acquisition_timestamp_utc": acquired_at.isoformat(),
                "requested_start_utc": REQUESTED_START,
                "requested_end_utc": REQUESTED_END,
                "retrieval_page_count": page_count,
                "sha256": checksum,
                "validation_report": str(validation_report_path),
                "validation_status": (
                    "passed" if not validation_failures else "failed"
                ),
                **coverage,
            }
        )
        write_json(state_path, state_record)
        append_manifest_records(
            args.manifest,
            args.output,
            args.query_id,
            execution_id,
            query_type,
            args.sql_file,
            sql_checksum,
            acquired_at,
            checksum,
            coverage,
            validation_report,
        )
    except (DuneAcquisitionError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Saved raw Dune result to {args.output}")
    print(f"Execution ID: {execution_id}")
    print(f"Rows: {coverage['row_count']}; SHA-256: {checksum}")
    if validation_failures:
        print(
            "Raw acquisition was preserved, but validation failed: "
            + "; ".join(validation_failures),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
