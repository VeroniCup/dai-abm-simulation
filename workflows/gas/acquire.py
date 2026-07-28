"""Persist, validate and combine MCP-managed Phase 1B Dune gas chunks.

Dune MCP is responsible for creating and executing each private temporary
query exactly once. This local command renders the immutable SQL template,
persists each MCP result through atomic filesystem operations, validates it,
maintains resumable per-chunk state and concatenates only a complete, valid
13-chunk acquisition. It never reads, prints or persists a Dune API key and
has no network path or standard-input result handoff.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import runpy

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
REPOSITORY_ROOT = runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)
import sys
from typing import Any, Iterable

import pandas as pd


PROJECT_ROOT = REPOSITORY_ROOT
DEFAULT_TEMPLATE = PROJECT_ROOT / "sql" / "gas" / "templates" / "hourly_conditions.sql"
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "gas" / "raw"
DEFAULT_CHUNK_DIR = DEFAULT_RAW_DIR / "chunks"
DEFAULT_PROVENANCE_DIR = PROJECT_ROOT / "data" / "gas" / "provenance"
DEFAULT_STATE_DIR = DEFAULT_PROVENANCE_DIR / "state"
DEFAULT_CHUNK_VALIDATION_DIR = DEFAULT_PROVENANCE_DIR / "chunks"
DEFAULT_LEDGER = DEFAULT_PROVENANCE_DIR / "dune_ethereum_hourly_gas_chunk_ledger.json"
DEFAULT_ABORTED_ATTEMPTS = (
    DEFAULT_PROVENANCE_DIR / "dune_ethereum_hourly_gas_aborted_attempts.json"
)
DEFAULT_COMBINED = (
    PROJECT_ROOT
    / "data"
    / "gas"
    / "processed"
    / "dune_ethereum_hourly_gas_assembled_2021-06-01_2024-06-30.csv"
)
DEFAULT_METADATA = DEFAULT_PROVENANCE_DIR / "dune_ethereum_hourly_gas_acquisition.json"
DEFAULT_VALIDATION = DEFAULT_PROVENANCE_DIR / "dune_ethereum_hourly_gas_validation.json"
FULL_START = pd.Timestamp("2021-06-01T00:00:00Z")
FULL_END = pd.Timestamp("2024-07-01T00:00:00Z")
LONDON_HOUR = pd.Timestamp("2021-08-05T12:00:00Z")
LONDON_BLOCK = 12_965_000
EXPECTED_TEMPLATE_SHA256 = (
    "2a392f66e427b5dd1dbd97c7d65d61c4c594a3bb5dde9d7fd5d819725b939ae7"
)

CHUNKS = (
    (1, "2021-06-01", "2021-07-01"),
    (2, "2021-07-01", "2021-10-01"),
    (3, "2021-10-01", "2022-01-01"),
    (4, "2022-01-01", "2022-04-01"),
    (5, "2022-04-01", "2022-07-01"),
    (6, "2022-07-01", "2022-10-01"),
    (7, "2022-10-01", "2023-01-01"),
    (8, "2023-01-01", "2023-04-01"),
    (9, "2023-04-01", "2023-07-01"),
    (10, "2023-07-01", "2023-10-01"),
    (11, "2023-10-01", "2024-01-01"),
    (12, "2024-01-01", "2024-04-01"),
    (13, "2024-04-01", "2024-07-01"),
)

EXPECTED_COLUMNS = (
    "timestamp_utc",
    "transaction_count",
    "block_count",
    "median_effective_gas_price_gwei",
    "mean_effective_gas_price_gwei",
    "p75_effective_gas_price_gwei",
    "p90_effective_gas_price_gwei",
    "p95_effective_gas_price_gwei",
    "p99_effective_gas_price_gwei",
    "median_base_fee_gwei",
    "p95_base_fee_gwei",
    "median_priority_fee_gwei",
    "block_utilisation",
    "target_normalised_block_utilisation",
    "transaction_total_gas_used",
    "block_total_gas_used",
    "gas_used_reconciliation_difference",
    "failed_transaction_share",
    "null_success_count",
    "eip1559_block_share",
)
PRICE_AND_FEE_COLUMNS = (
    "median_effective_gas_price_gwei",
    "mean_effective_gas_price_gwei",
    "p75_effective_gas_price_gwei",
    "p90_effective_gas_price_gwei",
    "p95_effective_gas_price_gwei",
    "p99_effective_gas_price_gwei",
    "median_base_fee_gwei",
    "p95_base_fee_gwei",
    "median_priority_fee_gwei",
)
PERCENTILE_COLUMNS = (
    "median_effective_gas_price_gwei",
    "p75_effective_gas_price_gwei",
    "p90_effective_gas_price_gwei",
    "p95_effective_gas_price_gwei",
    "p99_effective_gas_price_gwei",
)


class GasAcquisitionError(RuntimeError):
    """Raised when an acquisition invariant fails."""


def utc_now_iso() -> str:
    """Return the current UTC time in ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    """Return a SHA-256 digest for bytes."""
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """Return a SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write deterministic, atomic JSON metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def state_path(state_dir: Path, chunk_number: int) -> Path:
    """Return the durable state path for one bounded chunk."""
    return state_dir / f"chunk_{chunk_number:02d}.state.json"


def chunk_stem(chunk_number: int) -> str:
    """Return the stable filename stem for one chunk."""
    start, end = chunk_bounds(chunk_number)
    return f"chunk_{chunk_number:02d}_{start.date()}_{end.date()}"


def append_status(state: dict[str, Any], status: str, **fields: Any) -> None:
    """Advance a state record and retain an auditable status history."""
    timestamp = utc_now_iso()
    state["state"] = status
    state["updated_at_utc"] = timestamp
    state.setdefault("status_history", []).append(
        {"state": status, "timestamp_utc": timestamp}
    )
    state.update(fields)


def load_state(path: Path) -> dict[str, Any]:
    """Load a chunk state record or raise a clear acquisition error."""
    if not path.exists():
        raise GasAcquisitionError(f"Chunk state does not exist: {path}.")
    return json.loads(path.read_text(encoding="utf-8"))


def provenance_path(path: Path) -> str:
    """Return a repository-relative path where possible, else an absolute path."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def chunk_bounds(chunk_number: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return UTC bounds for one fixed chunk."""
    for number, start, end in CHUNKS:
        if number == chunk_number:
            return pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    raise GasAcquisitionError(f"Unknown chunk number: {chunk_number}.")


def validate_chunk_plan(
    chunks: Iterable[tuple[int, str, str]] = CHUNKS,
    expected_start: pd.Timestamp = FULL_START,
    expected_end: pd.Timestamp = FULL_END,
) -> dict[str, Any]:
    """Validate numbering, contiguity, exclusivity and complete coverage."""
    parsed = [
        (number, pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"))
        for number, start, end in chunks
    ]
    if [item[0] for item in parsed] != list(range(1, len(parsed) + 1)):
        raise GasAcquisitionError("Chunk numbers must be consecutive from one.")
    if not parsed or parsed[0][1] != expected_start or parsed[-1][2] != expected_end:
        raise GasAcquisitionError("Chunk plan does not match full requested coverage.")
    for previous, current in zip(parsed, parsed[1:]):
        if previous[2] != current[1]:
            raise GasAcquisitionError(
                f"Chunks {previous[0]:02d} and {current[0]:02d} are not contiguous."
            )
    for number, start, end in parsed:
        if start >= end:
            raise GasAcquisitionError(f"Chunk {number:02d} is empty or reversed.")
    hours = sum(int((end - start) / pd.Timedelta(hours=1)) for _, start, end in parsed)
    if hours != 27_024:
        raise GasAcquisitionError(f"Chunk plan contains {hours} hours, not 27024.")
    return {"chunk_count": len(parsed), "expected_hours": hours}


def render_sql(template_text: str, start: pd.Timestamp, end: pd.Timestamp) -> str:
    """Render only the two authorised interval tokens."""
    rendered = template_text.replace("{{START_DATE}}", start.date().isoformat())
    rendered = rendered.replace("{{END_DATE}}", end.date().isoformat())
    if "{{" in rendered or "}}" in rendered:
        raise GasAcquisitionError("Unresolved SQL template token remains.")
    if "SELECT *" in rendered.upper() or "ORDER BY" in rendered.upper():
        raise GasAcquisitionError("Rendered SQL contains a forbidden clause.")
    if rendered.count(start.date().isoformat()) != 4:
        raise GasAcquisitionError("Start bound was not rendered in four filters.")
    if rendered.count(end.date().isoformat()) != 4:
        raise GasAcquisitionError("End bound was not rendered in four filters.")
    return rendered


def render_chunk_sql(template_path: Path, chunk_number: int) -> tuple[str, str]:
    """Return one chunk's SQL and its checksum."""
    start, end = chunk_bounds(chunk_number)
    sql = render_sql(template_path.read_text(encoding="utf-8"), start, end)
    return sql, sha256_bytes(sql.encode("utf-8"))


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def validate_rows(
    rows: list[dict[str, Any]], start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, Any]:
    """Validate a chunk without altering its observations."""
    failures: list[str] = []
    warnings: list[str] = []
    frame = pd.DataFrame(rows).replace({"": None})
    actual_columns = list(frame.columns)
    if set(actual_columns) != set(EXPECTED_COLUMNS) or len(actual_columns) != 20:
        failures.append(f"unexpected columns: {actual_columns}")
        return {"validation_passed": False, "failures": failures, "warnings": warnings}

    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    expected = pd.date_range(start, end - pd.Timedelta(hours=1), freq="1h")
    invalid_timestamp_count = int(timestamps.isna().sum())
    duplicates = int(timestamps.duplicated(keep=False).sum())
    observed = pd.DatetimeIndex(timestamps.dropna().unique()).sort_values()
    missing = expected.difference(observed)
    out_of_range = int(((timestamps < start) | (timestamps >= end)).sum())
    if invalid_timestamp_count:
        failures.append(f"{invalid_timestamp_count} invalid timestamps")
    if duplicates:
        failures.append(f"{duplicates} rows participate in duplicate hours")
    if len(missing):
        failures.append(f"{len(missing)} missing hours")
    if out_of_range:
        failures.append(f"{out_of_range} out-of-range timestamps")
    if len(frame) != len(expected):
        failures.append(f"row count {len(frame)} != expected {len(expected)}")
    if len(observed) and (observed.min() != start or observed.max() != expected.max()):
        failures.append("actual timestamp boundaries do not match the chunk")

    transaction_count = _numeric(frame, "transaction_count")
    block_count = _numeric(frame, "block_count")
    if bool((transaction_count <= 0).any()) or bool(transaction_count.isna().any()):
        failures.append("transaction_count is not strictly positive")
    if bool((block_count <= 0).any()) or bool(block_count.isna().any()):
        failures.append("block_count is not strictly positive")

    negative_counts: dict[str, int] = {}
    null_counts: dict[str, int] = {}
    for column in PRICE_AND_FEE_COLUMNS:
        values = _numeric(frame, column)
        negative_counts[column] = int((values < 0).sum())
        null_counts[column] = int(values.isna().sum())
        if negative_counts[column]:
            failures.append(f"{column} has {negative_counts[column]} negative values")

    failed_share = _numeric(frame, "failed_transaction_share")
    failed_share_violations = int(
        (failed_share.isna() | (failed_share < 0) | (failed_share > 1)).sum()
    )
    if failed_share_violations:
        failures.append(f"{failed_share_violations} failed-share violations")

    null_success = _numeric(frame, "null_success_count")
    null_success_violations = int((null_success.isna() | (null_success < 0)).sum())
    if null_success_violations:
        failures.append(f"{null_success_violations} null-success violations")

    utilisation_violations = 0
    for column in ("block_utilisation", "target_normalised_block_utilisation"):
        values = _numeric(frame, column)
        utilisation_violations += int(
            (~values.map(lambda value: math.isfinite(value) if pd.notna(value) else False)
             | (values < 0)).sum()
        )
    if utilisation_violations:
        failures.append(f"{utilisation_violations} utilisation violations")

    eip_share = _numeric(frame, "eip1559_block_share")
    eip_range_violations = int(
        (eip_share.isna() | (eip_share < 0) | (eip_share > 1)).sum()
    )
    if eip_range_violations:
        failures.append(f"{eip_range_violations} EIP-1559 share violations")

    percentiles = frame.loc[:, PERCENTILE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    percentile_violations = int(
        (percentiles.isna().any(axis=1) | percentiles.diff(axis=1).iloc[:, 1:].lt(0).any(axis=1)).sum()
    )
    if percentile_violations:
        failures.append(f"{percentile_violations} percentile-ordering violations")

    transaction_gas = _numeric(frame, "transaction_total_gas_used")
    block_gas = _numeric(frame, "block_total_gas_used")
    difference = _numeric(frame, "gas_used_reconciliation_difference")
    reconciliation_violations = int(
        (transaction_gas.isna() | block_gas.isna() | difference.isna()
         | transaction_gas.ne(block_gas) | difference.ne(0)).sum()
    )
    if reconciliation_violations:
        failures.append(f"{reconciliation_violations} gas reconciliation violations")

    pre = timestamps < LONDON_HOUR
    mixed = timestamps == LONDON_HOUR
    post = timestamps > LONDON_HOUR
    pre_london_violations = int(
        (
            frame.loc[pre, ["median_base_fee_gwei", "p95_base_fee_gwei", "median_priority_fee_gwei"]]
            .notna().any(axis=1)
            | eip_share.loc[pre].ne(0)
        ).sum()
    )
    if pre_london_violations:
        failures.append(f"{pre_london_violations} pre-London semantic violations")
    post_share_violations = int(eip_share.loc[post].ne(1).sum())
    if post_share_violations:
        failures.append(f"{post_share_violations} post-London share violations")
    post_null_base = int(
        frame.loc[post, ["median_base_fee_gwei", "p95_base_fee_gwei"]]
        .isna().any(axis=1).sum()
    )
    post_null_priority = int(frame.loc[post, "median_priority_fee_gwei"].isna().sum())
    if post_null_base:
        warnings.append(f"{post_null_base} fully post-London hours have null base fees")
    if post_null_priority:
        warnings.append(f"{post_null_priority} fully post-London hours have null priority fees")

    report = {
        "validation_passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "expected_row_count": int(len(expected)),
        "minimum_timestamp_utc": observed.min().isoformat() if len(observed) else None,
        "maximum_timestamp_utc": observed.max().isoformat() if len(observed) else None,
        "duplicate_hour_row_count": duplicates,
        "missing_hour_count": int(len(missing)),
        "out_of_range_timestamp_count": out_of_range,
        "invalid_timestamp_count": invalid_timestamp_count,
        "negative_value_counts": negative_counts,
        "null_value_counts": null_counts,
        "null_success_count_total": int(null_success.fillna(0).sum()),
        "failed_transaction_share_minimum": float(failed_share.min()),
        "failed_transaction_share_maximum": float(failed_share.max()),
        "utilisation_violation_count": utilisation_violations,
        "eip1559_share_minimum": float(eip_share.min()),
        "eip1559_share_maximum": float(eip_share.max()),
        "percentile_ordering_violation_count": percentile_violations,
        "gas_reconciliation_violation_count": reconciliation_violations,
        "maximum_absolute_gas_reconciliation_difference": float(difference.abs().max()),
        "pre_london_hour_count": int(pre.sum()),
        "pre_london_violation_count": pre_london_violations,
        "mixed_london_hour_count": int(mixed.sum()),
        "mixed_london_eip1559_block_share": (
            float(eip_share.loc[mixed].iloc[0]) if bool(mixed.any()) else None
        ),
        "fully_post_london_hour_count": int(post.sum()),
        "post_london_share_violation_count": post_share_violations,
        "post_london_null_base_fee_hour_count": post_null_base,
        "post_london_null_priority_fee_hour_count": post_null_priority,
    }
    return report


def _payload_rows(payload_text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Decode either a direct Dune result or its MCP text wrapper."""
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise GasAcquisitionError("MCP result payload is not valid JSON.") from exc
    if "state" not in payload and isinstance(payload.get("structuredContent"), dict):
        payload = payload["structuredContent"]
    if "state" not in payload and isinstance(payload.get("content"), list):
        text_blocks = [
            item.get("text") for item in payload["content"]
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if len(text_blocks) != 1 or not isinstance(text_blocks[0], str):
            raise GasAcquisitionError("MCP wrapper contains no unique text result.")
        try:
            payload = json.loads(text_blocks[0])
        except json.JSONDecodeError as exc:
            raise GasAcquisitionError("MCP text result is not valid JSON.") from exc
    if payload.get("state") != "COMPLETED":
        raise GasAcquisitionError(f"Execution is not complete: {payload.get('state')!r}.")
    rows = payload.get("data", {}).get("rows")
    if not isinstance(rows, list):
        raise GasAcquisitionError("MCP result payload contains no row list.")
    return payload, rows


def initialise_chunk(
    chunk_number: int,
    state_dir: Path,
    template: Path,
    *,
    chunk_dir: Path | None = None,
    validation_dir: Path | None = None,
    replace_failed_chunk: bool = False,
) -> dict[str, Any]:
    """Create planned state, refusing implicit retries or replacements."""
    validate_chunk_plan()
    template_sha = sha256_file(template)
    if template_sha != EXPECTED_TEMPLATE_SHA256:
        raise GasAcquisitionError(
            f"SQL template checksum {template_sha} does not match the authorised checksum."
        )
    start, end = chunk_bounds(chunk_number)
    path = state_path(state_dir, chunk_number)
    if path.exists():
        existing = load_state(path)
        if existing.get("state") == "complete" and existing.get("validation_passed"):
            raise GasAcquisitionError(
                f"Chunk {chunk_number:02d} is complete and must never be re-executed."
            )
        if not replace_failed_chunk:
            raise GasAcquisitionError(
                f"Chunk {chunk_number:02d} has durable state {existing.get('state')!r}; "
                "replacement requires --replace-failed-chunk."
            )
        replacement_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = path.with_name(f"{path.stem}.replaced-{replacement_stamp}.json")
        os.replace(path, archive)
        raw_chunk_dir = chunk_dir if chunk_dir is not None else state_dir.parent
        chunk_validation_dir = (
            validation_dir if validation_dir is not None else raw_chunk_dir
        )
        stem = chunk_stem(chunk_number)
        replaceable_artifacts = (
            raw_chunk_dir / f"{stem}.csv",
            chunk_validation_dir / f"{stem}.validation.json",
            raw_chunk_dir / f".{stem}.partial.csv",
            raw_chunk_dir / f".chunk_{chunk_number:02d}.partial.json",
        )
        for artifact in replaceable_artifacts:
            if artifact.exists():
                archived_artifact = artifact.with_name(
                    f"{artifact.stem}.replaced-{replacement_stamp}{artifact.suffix}"
                )
                os.replace(artifact, archived_artifact)
    state: dict[str, Any] = {
        "chunk_number": chunk_number,
        "requested_start_utc": start.isoformat(),
        "requested_end_exclusive_utc": end.isoformat(),
        "expected_row_count": int((end - start) / pd.Timedelta(hours=1)),
        "engine": "small",
        "query_type": "private temporary bounded chunk",
        "sql_template_path": provenance_path(template),
        "sql_template_sha256": template_sha,
        "rendered_sql_sha256": render_chunk_sql(template, chunk_number)[1],
        "query_id": None,
        "query_url": None,
        "execution_id": None,
        "result_retrieved": False,
        "raw_file_persisted": False,
        "validation_passed": False,
        "replacement_explicitly_authorised": replace_failed_chunk,
    }
    append_status(state, "planned")
    write_json(path, state)
    return state


def update_chunk_state(
    state_dir: Path, chunk_number: int, status: str, **fields: Any
) -> dict[str, Any]:
    """Atomically update one chunk's durable state."""
    path = state_path(state_dir, chunk_number)
    state = load_state(path)
    append_status(state, status, **fields)
    write_json(path, state)
    return state


def record_aborted_attempt(path: Path) -> dict[str, Any]:
    """Record the explicitly excluded first chunk-01 attempt."""
    payload = {
        "attempts": [
            {
                "chunk_number": 1,
                "classification": "aborted acquisition attempt",
                "dune_execution_state": "completed",
                "result_retrieved": True,
                "raw_file_persisted": False,
                "query_id": None,
                "execution_id": None,
                "identifiers_available": False,
                "observed_credit_delta": 0.089,
                "included_in_final_dataset": False,
                "execution_reused": False,
                "note": (
                    "Result retrieval completed, but the stdin-dependent local handoff "
                    "failed before persistence. No raw data entered the final dataset."
                ),
            }
        ]
    }
    write_json(path, payload)
    return payload


def write_csv_partial(path: Path, rows: list[dict[str, Any]]) -> None:
    """Flush an unmodified row serialisation to a partial CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=EXPECTED_COLUMNS, lineterminator="\n", extrasaction="raise"
        )
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())


def parse_partial_csv(path: Path, expected_rows: int) -> list[dict[str, str]]:
    """Parse and structurally verify a flushed partial CSV before rename."""
    if not path.exists() or path.stat().st_size == 0:
        raise GasAcquisitionError("Partial raw CSV is absent or empty.")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise GasAcquisitionError("Partial raw CSV header is missing or not exact.")
    header = ",".join(EXPECTED_COLUMNS)
    if path.read_text(encoding="utf-8").splitlines().count(header) != 1:
        raise GasAcquisitionError("Partial raw CSV does not contain exactly one header.")
    if len(rows) != expected_rows:
        raise GasAcquisitionError(
            f"Partial raw CSV has {len(rows)} records; expected {expected_rows}."
        )
    return rows


def write_combined_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write timestamp-sorted rows deterministically without deduplication."""
    ordered = sorted(rows, key=lambda row: str(row["timestamp_utc"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPECTED_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(ordered)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _new_ledger(template: Path) -> dict[str, Any]:
    return {
        "query_type": "private temporary bounded chunks",
        "engine": "small",
        "source_tables": ["ethereum.transactions", "ethereum.blocks"],
        "sql_template_path": provenance_path(template),
        "sql_template_sha256": sha256_file(template),
        "london_activation_block": LONDON_BLOCK,
        "percentiles_are_approximate": True,
        "chunks": [],
    }


def sync_ledger(ledger_path: Path, template: Path, state: dict[str, Any]) -> None:
    """Atomically upsert a sanitised chunk record into the acquisition ledger."""
    ledger = (
        json.loads(ledger_path.read_text(encoding="utf-8"))
        if ledger_path.exists()
        else _new_ledger(template)
    )
    record = {
        key: state.get(key)
        for key in (
            "chunk_number", "requested_start_utc", "requested_end_exclusive_utc",
            "query_id", "query_url", "execution_id", "state", "engine",
            "creation_timestamp_utc", "execution_submitted_at_utc",
            "execution_completed_at_utc", "result_retrieved_at_utc",
            "raw_file_persisted_at_utc", "validated_at_utc", "duration_seconds",
            "compute_credits", "usage_before", "usage_after",
            "observed_credit_delta", "row_count", "column_count", "raw_file_path",
            "raw_file_size_bytes", "raw_file_sha256", "validation_path",
            "validation_passed", "rendered_sql_sha256", "result_retrieved",
            "raw_file_persisted",
        )
    }
    record["execution_count"] = 1 if state.get("execution_id") else 0
    record["retrieval_count"] = 1 if state.get("result_retrieved") else 0
    chunks = [
        item for item in ledger.get("chunks", [])
        if item.get("chunk_number") != state["chunk_number"]
    ]
    chunks.append(record)
    ledger["chunks"] = sorted(chunks, key=lambda item: item["chunk_number"])
    write_json(ledger_path, ledger)


def persist_chunk_payload(
    *,
    chunk_number: int,
    payload_file: Path,
    state_dir: Path,
    chunk_dir: Path,
    ledger_path: Path,
    template: Path,
    validation_dir: Path | None = None,
    duration_seconds: float | None = None,
    fail_after: str | None = None,
) -> dict[str, Any]:
    """Persist one retrieved result without stdin and validate it atomically."""
    state_file = state_path(state_dir, chunk_number)
    state = load_state(state_file)
    if state.get("state") not in {"execution_submitted", "execution_completed"}:
        raise GasAcquisitionError(
            f"Chunk {chunk_number:02d} cannot ingest from state {state.get('state')!r}."
        )
    start, end = chunk_bounds(chunk_number)
    try:
        payload_text = payload_file.read_text(encoding="utf-8")
        payload, rows = _payload_rows(payload_text)
        if str(payload.get("executionId")) != str(state.get("execution_id")):
            raise GasAcquisitionError("Payload execution ID does not match durable state.")
        metadata = payload.get("resultMetadata", {})
        if metadata.get("totalRowCount") != len(rows):
            raise GasAcquisitionError("Payload metadata row count does not match returned rows.")
        append_status(
            state,
            "result_retrieved",
            result_retrieved=True,
            result_retrieved_at_utc=utc_now_iso(),
            execution_completed_at_utc=utc_now_iso(),
            duration_seconds=duration_seconds,
            compute_credits=(
                float(metadata["executionCostCredits"])
                if metadata.get("executionCostCredits") is not None else None
            ),
        )
        write_json(state_file, state)
        if fail_after == "retrieval":
            raise GasAcquisitionError("Injected failure after retrieval.")

        chunk_dir.mkdir(parents=True, exist_ok=True)
        stem = chunk_stem(chunk_number)
        partial_csv = chunk_dir / f".{stem}.partial.csv"
        raw_path = chunk_dir / f"{stem}.csv"
        validation_path = (
            validation_dir if validation_dir is not None else chunk_dir
        ) / f"{stem}.validation.json"
        if raw_path.exists():
            raise GasAcquisitionError(f"Refusing to overwrite chunk {chunk_number:02d}.")
        if partial_csv.exists():
            raise GasAcquisitionError(f"Partial CSV already exists: {partial_csv}.")
        write_csv_partial(partial_csv, rows)
        parsed_rows = parse_partial_csv(partial_csv, state["expected_row_count"])
        structural = validate_rows(parsed_rows, start, end)
        if not structural["validation_passed"]:
            raise GasAcquisitionError(
                "Structural pre-validation failed: " + "; ".join(structural["failures"])
            )
        partial_sha = sha256_file(partial_csv)
        if fail_after == "before_rename":
            raise GasAcquisitionError("Injected failure before atomic rename.")
        os.replace(partial_csv, raw_path)
        append_status(
            state,
            "raw_file_persisted",
            raw_file_persisted=True,
            raw_file_persisted_at_utc=utc_now_iso(),
            raw_file_path=provenance_path(raw_path),
            raw_file_size_bytes=raw_path.stat().st_size,
            raw_file_sha256=partial_sha,
            row_count=len(parsed_rows),
            column_count=len(EXPECTED_COLUMNS),
        )
        write_json(state_file, state)
        if fail_after == "raw_persistence":
            raise GasAcquisitionError("Injected failure after raw persistence.")

        report = validate_rows(parsed_rows, start, end)
        report.update(
            {
                "chunk_number": chunk_number,
                "requested_start_utc": start.isoformat(),
                "requested_end_exclusive_utc": end.isoformat(),
                "raw_file_path": provenance_path(raw_path),
                "raw_file_size_bytes": raw_path.stat().st_size,
                "raw_file_sha256": sha256_file(raw_path),
            }
        )
        write_json(validation_path, report)
        if not report["validation_passed"]:
            raise GasAcquisitionError(
                f"Chunk {chunk_number:02d} validation failed: {'; '.join(report['failures'])}"
            )
        append_status(
            state,
            "complete",
            validation_passed=True,
            validated_at_utc=utc_now_iso(),
            validation_path=provenance_path(validation_path),
        )
        write_json(state_file, state)
        sync_ledger(ledger_path, template, state)
        payload_file.unlink(missing_ok=True)
        return state
    except Exception as exc:
        if state_file.exists():
            state = load_state(state_file)
            append_status(state, "failed", failure=str(exc))
            write_json(state_file, state)
            sync_ledger(ledger_path, template, state)
        raise


def finalise(args: argparse.Namespace) -> dict[str, Any]:
    """Concatenate all valid chunks deterministically and validate the result."""
    validate_chunk_plan()
    if not args.ledger.exists():
        raise GasAcquisitionError("Chunk ledger does not exist.")
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    records = sorted(ledger.get("chunks", []), key=lambda item: item["chunk_number"])
    if [item["chunk_number"] for item in records] != list(range(1, 14)):
        raise GasAcquisitionError("All 13 chunk ledger records are required before concatenation.")
    if not all(
        item.get("state") == "complete"
        and item.get("validation_passed")
        and item.get("raw_file_persisted")
        for item in records
    ):
        raise GasAcquisitionError("A chunk failed validation; partial data will not be concatenated.")
    if args.combined.exists():
        raise GasAcquisitionError(f"Refusing to overwrite combined panel: {args.combined}.")

    rows: list[dict[str, Any]] = []
    source_row_strings: dict[str, dict[str, str]] = {}
    previous_end: pd.Timestamp | None = None
    for record in records:
        start, end = chunk_bounds(record["chunk_number"])
        if previous_end is not None and previous_end != start:
            raise GasAcquisitionError("Chunk boundary continuity failed.")
        previous_end = end
        raw_path = PROJECT_ROOT / record["raw_file_path"]
        if sha256_file(raw_path) != record["raw_file_sha256"]:
            raise GasAcquisitionError(f"Chunk {record['chunk_number']:02d} checksum changed.")
        with raw_path.open("r", encoding="utf-8", newline="") as handle:
            chunk_rows = list(csv.DictReader(handle))
        for row in chunk_rows:
            key = str(row["timestamp_utc"])
            if key in source_row_strings:
                raise GasAcquisitionError(f"Duplicate timestamp before concatenation: {key}.")
            source_row_strings[key] = {
                column: "" if row.get(column) is None else str(row.get(column))
                for column in EXPECTED_COLUMNS
            }
            rows.append(row)
    report = validate_rows(rows, FULL_START, FULL_END)
    if not report["validation_passed"]:
        raise GasAcquisitionError(
            "Combined validation failed before writing: " + "; ".join(report["failures"])
        )

    write_combined_rows(args.combined, rows)

    with args.combined.open("r", encoding="utf-8", newline="") as handle:
        round_trip = list(csv.DictReader(handle))
    changed = sum(
        any(row[column] != source_row_strings[row["timestamp_utc"]][column]
            for column in EXPECTED_COLUMNS)
        for row in round_trip
    )
    if changed:
        raise GasAcquisitionError(f"Concatenation changed {changed} raw rows.")

    report.update(
        {
            "validation_timestamp_utc": utc_now_iso(),
            "combined_file_path": provenance_path(args.combined),
            "combined_file_size_bytes": args.combined.stat().st_size,
            "combined_sha256": sha256_file(args.combined),
            "raw_value_change_count": changed,
            "chunk_boundary_continuity_passed": True,
        }
    )
    write_json(args.validation, report)
    metadata = {
        "provider": "Dune",
        "source_tables": ["ethereum.transactions", "ethereum.blocks"],
        "query_type": "private temporary bounded chunks",
        "engine": "small",
        "sql_template_path": provenance_path(args.template),
        "sql_template_sha256": sha256_file(args.template),
        "requested_start_utc": FULL_START.isoformat(),
        "requested_end_exclusive_utc": FULL_END.isoformat(),
        "actual_minimum_timestamp_utc": report["minimum_timestamp_utc"],
        "actual_maximum_timestamp_utc": report["maximum_timestamp_utc"],
        "row_count": report["row_count"],
        "column_count": report["column_count"],
        "combined_file_path": report["combined_file_path"],
        "combined_file_size_bytes": report["combined_file_size_bytes"],
        "combined_sha256": report["combined_sha256"],
        "chunk_ledger_path": provenance_path(args.ledger),
        "chunk_query_ids": [item["query_id"] for item in records],
        "chunk_execution_ids": [item["execution_id"] for item in records],
        "chunk_checksums": [item["raw_file_sha256"] for item in records],
        "acquisition_completed_at_utc": utc_now_iso(),
        "aggregation_definitions": {
            "percentiles": "Dune approx_percentile at hourly frequency",
            "failed_transaction_share": "count false success / count non-null success",
            "raw_block_utilisation": "sum block gas used / sum block gas limit",
            "target_normalised_block_utilisation": "post-London gas used divided by half the gas limit; pre-London divided by the gas limit",
            "gas_reconciliation": "transaction gas-used sum minus block gas-used sum",
        },
        "london_activation_block": LONDON_BLOCK,
        "usage_before_first_chunk": records[0]["usage_before"],
        "usage_after_each_chunk": [item["usage_after"] for item in records],
        "final_usage": records[-1]["usage_after"],
        "successful_production_batch_credit_delta": (
            records[-1]["usage_after"] - records[0]["usage_before"]
        ),
        "execution_compute_credits_sum": sum(
            float(item["compute_credits"]) for item in records
        ),
        "usage_metering_note": (
            "Immediate usage readings may batch adjacent executions; use the first-to-final "
            "usage delta for the production batch and execution metadata for per-query compute."
        ),
        "total_executions": sum(item["execution_count"] for item in records),
        "total_retrievals": sum(item["retrieval_count"] for item in records),
        "combined_file_is_locally_assembled": True,
        "chunk_files_are_unmodified_result_rows_serialised_as_csv": True,
    }
    write_json(args.metadata, metadata)
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("temporary-quarterly",))
    parser.add_argument(
        "--action",
        required=True,
        choices=(
            "validate-plan", "render-chunk", "record-aborted-attempt",
            "initialise-chunk", "record-usage-before", "record-query", "record-execution",
            "persist-result", "record-usage-after", "mark-failed", "finalise",
        ),
    )
    parser.add_argument("--start", default="2021-06-01")
    parser.add_argument("--end-exclusive", default="2024-07-01")
    parser.add_argument("--chunk", type=int)
    parser.add_argument("--query-id", type=int)
    parser.add_argument("--query-url")
    parser.add_argument("--execution-id")
    parser.add_argument("--creation-timestamp-utc")
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument("--compute-credits", type=float)
    parser.add_argument("--usage-before", type=float)
    parser.add_argument("--usage-after", type=float)
    parser.add_argument("--payload-file", type=Path)
    parser.add_argument("--failure")
    parser.add_argument("--replace-failed-chunk", action="store_true")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    parser.add_argument(
        "--chunk-validation-dir",
        type=Path,
        default=DEFAULT_CHUNK_VALIDATION_DIR,
    )
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--aborted-attempts", type=Path, default=DEFAULT_ABORTED_ATTEMPTS)
    parser.add_argument("--combined", type=Path, default=DEFAULT_COMBINED)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--validation", type=Path, default=DEFAULT_VALIDATION)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if pd.Timestamp(args.start, tz="UTC") != FULL_START or pd.Timestamp(
        args.end_exclusive, tz="UTC"
    ) != FULL_END:
        raise SystemExit("Only the authorised full Phase 1B bounds are accepted.")
    try:
        if args.action == "validate-plan":
            result = validate_chunk_plan()
            result["sql_template_sha256"] = sha256_file(args.template)
        elif args.action == "render-chunk":
            if args.chunk is None:
                raise GasAcquisitionError("render-chunk requires --chunk.")
            sql, checksum = render_chunk_sql(args.template, args.chunk)
            result = {"chunk": args.chunk, "rendered_sql_sha256": checksum, "sql": sql}
        elif args.action == "record-aborted-attempt":
            result = record_aborted_attempt(args.aborted_attempts)
        elif args.action == "initialise-chunk":
            if args.chunk is None:
                raise GasAcquisitionError("initialise-chunk requires --chunk.")
            result = initialise_chunk(
                args.chunk,
                args.state_dir,
                args.template,
                chunk_dir=args.chunk_dir,
                validation_dir=args.chunk_validation_dir,
                replace_failed_chunk=args.replace_failed_chunk,
            )
        elif args.action == "record-usage-before":
            if args.chunk is None or args.usage_before is None:
                raise GasAcquisitionError("record-usage-before requires chunk and usage.")
            path = state_path(args.state_dir, args.chunk)
            result = load_state(path)
            if result.get("state") != "planned":
                raise GasAcquisitionError("Usage-before may only be recorded in planned state.")
            result["usage_before"] = args.usage_before
            result["updated_at_utc"] = utc_now_iso()
            write_json(path, result)
        elif args.action == "record-query":
            required = ("chunk", "query_id", "query_url", "creation_timestamp_utc", "usage_before")
            missing = [name for name in required if getattr(args, name) is None]
            if missing:
                raise GasAcquisitionError(f"record-query missing arguments: {missing}.")
            current = load_state(state_path(args.state_dir, args.chunk))
            if current.get("state") != "planned":
                raise GasAcquisitionError("Query may only be recorded from planned state.")
            result = update_chunk_state(
                args.state_dir,
                args.chunk,
                "query_created",
                query_id=args.query_id,
                query_url=args.query_url,
                creation_timestamp_utc=args.creation_timestamp_utc,
                usage_before=args.usage_before,
            )
        elif args.action == "record-execution":
            if args.chunk is None or args.execution_id is None:
                raise GasAcquisitionError("record-execution requires chunk and execution ID.")
            current = load_state(state_path(args.state_dir, args.chunk))
            if current.get("state") != "query_created":
                raise GasAcquisitionError("Execution may only be recorded from query_created state.")
            result = update_chunk_state(
                args.state_dir,
                args.chunk,
                "execution_submitted",
                execution_id=args.execution_id,
                execution_submitted_at_utc=utc_now_iso(),
            )
        elif args.action == "persist-result":
            if args.chunk is None or args.payload_file is None:
                raise GasAcquisitionError("persist-result requires chunk and payload file.")
            result = persist_chunk_payload(
                chunk_number=args.chunk,
                payload_file=args.payload_file,
                state_dir=args.state_dir,
                chunk_dir=args.chunk_dir,
                validation_dir=args.chunk_validation_dir,
                ledger_path=args.ledger,
                template=args.template,
                duration_seconds=args.duration_seconds,
            )
        elif args.action == "record-usage-after":
            if args.chunk is None or args.usage_after is None:
                raise GasAcquisitionError("record-usage-after requires chunk and usage.")
            current = load_state(state_path(args.state_dir, args.chunk))
            if current.get("state") != "complete":
                raise GasAcquisitionError("Usage-after may only be recorded for a complete chunk.")
            result = update_chunk_state(
                args.state_dir,
                args.chunk,
                "complete",
                usage_after=args.usage_after,
                observed_credit_delta=args.usage_after - float(current["usage_before"]),
            )
            sync_ledger(args.ledger, args.template, result)
        elif args.action == "mark-failed":
            if args.chunk is None or args.failure is None:
                raise GasAcquisitionError("mark-failed requires chunk and failure text.")
            result = update_chunk_state(
                args.state_dir, args.chunk, "failed", failure=args.failure
            )
            sync_ledger(args.ledger, args.template, result)
        else:
            result = finalise(args)
    except GasAcquisitionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
