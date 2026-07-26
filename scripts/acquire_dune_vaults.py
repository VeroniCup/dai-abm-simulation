"""Local persistence and validation for Phase 1E production acquisition.

This module has no Dune client, credential handling or automatic retry path.
The orchestrator creates one private temporary query at a time and writes its
single completed result response to the corresponding ignored payload path.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "data" / "raw" / "vaults"
PROCESSED_ROOT = ROOT / "data" / "processed" / "vaults"
PROVENANCE_ROOT = ROOT / "data" / "provenance" / "vaults"
RAW_CHUNK_ROOT = RAW_ROOT / "chunks"
PROCESSED_CHUNK_ROOT = PROCESSED_ROOT / "chunks"
PROVENANCE_CHUNK_ROOT = PROVENANCE_ROOT / "chunks"
RAW_STREAM_ROOT = RAW_ROOT / "streams"
PROVENANCE_STREAM_ROOT = PROVENANCE_ROOT / "streams"
GENERATED_SQL_ROOT = ROOT / "sql" / "vaults" / "generated"
INGRESS_ROOT = PROVENANCE_ROOT / "ingress"
MANIFEST_PATH = PROVENANCE_ROOT / "manifest.json"
TEMPLATE_PATH = ROOT / "sql" / "dune_phase1e_vat_mutations_monthly.sql"
SCAN_START = pd.Timestamp("2019-11-01T00:00:00Z")
SAMPLE_START = pd.Timestamp("2021-06-01T00:00:00Z")
SAMPLE_END = pd.Timestamp("2024-07-01T00:00:00Z")
TARGET_ILKS = ("ETH-A", "ETH-B", "ETH-C", "WBTC-A", "WBTC-B", "WBTC-C")
CANONICAL_VAT = "0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b"
CANONICAL_MANAGER = "0x5ef30b9986345249bc32d8928b7ee64de9435e39"
CANONICAL_JUG = "0x19c0976f590d67707e62397c87829d896dc0f1f1"

MUTATION_COLUMNS = (
    "block_time_utc", "block_number", "transaction_hash", "transaction_index",
    "trace_position", "call_type", "ilk", "urn", "source_urn",
    "destination_urn", "dink_raw", "dart_raw", "call_success",
    "source_contract", "source_table",
)
OPEN_COLUMNS = (
    "effective_time_utc", "block_number", "transaction_hash",
    "transaction_index", "open_trace_position", "newcdp_log_index",
    "creation_trace_position", "ilk", "cdp_id", "urn", "initial_owner",
    "event_owner", "manager_caller", "top_level_sender", "manager_contract",
    "urn_creator", "call_success", "creation_is_direct_child",
)
GIVE_COLUMNS = (
    "effective_time_utc", "block_number", "transaction_hash",
    "transaction_index", "trace_position", "cdp_id", "new_owner",
    "top_level_sender", "manager_contract", "call_success",
)
RATE_COLUMNS = (
    "effective_time_utc", "block_number", "transaction_hash",
    "transaction_index", "trace_position", "ilk", "rate_record_type",
    "raw_rate_ray", "raw_rate_delta", "call_success", "source_contract",
    "source_table",
)
STREAM_SPECS = {
    "open": {
        "sql": ROOT / "sql" / "dune_phase1e_manager_open_mappings.sql",
        "columns": OPEN_COLUMNS,
    },
    "give": {
        "sql": ROOT / "sql" / "dune_phase1e_manager_gives.sql",
        "columns": GIVE_COLUMNS,
    },
    "rate": {
        "sql": ROOT / "sql" / "dune_phase1e_accumulated_rates.sql",
        "columns": RATE_COLUMNS,
    },
}


class VaultAcquisitionError(RuntimeError):
    """Raised when acquisition provenance or a raw result is invalid."""


@dataclass(frozen=True)
class MonthChunk:
    number: int
    start: pd.Timestamp
    end: pd.Timestamp

    @property
    def chunk_id(self) -> str:
        return f"{self.number:02d}_{self.start:%Y_%m}"


@dataclass(frozen=True)
class Subwindow:
    label: str
    parent_chunk_id: str
    start: pd.Timestamp
    end: pd.Timestamp


def month_plan() -> tuple[MonthChunk, ...]:
    starts = pd.date_range(SCAN_START, SAMPLE_END, freq="MS", inclusive="left")
    return tuple(
        MonthChunk(index, start, min(start + pd.offsets.MonthBegin(1), SAMPLE_END))
        for index, start in enumerate(starts, start=1)
    )


MONTHS = month_plan()
CHUNK_05_SUBWINDOWS = (
    Subwindow(
        "05A", "05_2020_03",
        pd.Timestamp("2020-03-01T00:00:00Z"),
        pd.Timestamp("2020-03-16T00:00:00Z"),
    ),
    Subwindow(
        "05B", "05_2020_03",
        pd.Timestamp("2020-03-16T00:00:00Z"),
        pd.Timestamp("2020-04-01T00:00:00Z"),
    ),
)
PAGE_LIMIT = 32_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def write_csv_atomic(path: Path, columns: Iterable[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def validate_plan(months: Iterable[MonthChunk] = MONTHS) -> dict[str, Any]:
    values = tuple(months)
    failures: list[str] = []
    if len(values) != 56:
        failures.append(f"expected 56 monthly chunks, found {len(values)}")
    if not values or values[0].start != SCAN_START or values[-1].end != SAMPLE_END:
        failures.append("monthly plan does not cover the conservative scan interval")
    for previous, current in zip(values, values[1:]):
        if previous.end != current.start:
            failures.append(f"gap or overlap between {previous.chunk_id} and {current.chunk_id}")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "chunk_count": len(values),
        "scan_start_utc": SCAN_START.isoformat(),
        "sample_end_exclusive_utc": SAMPLE_END.isoformat(),
    }


def render_month_sql(chunk: MonthChunk | Subwindow) -> str:
    sql = TEMPLATE_PATH.read_text(encoding="utf-8")
    values = {
        "{{START_DATE}}": chunk.start.strftime("%Y-%m-%d"),
        "{{END_DATE}}": chunk.end.strftime("%Y-%m-%d"),
        "{{START_TIMESTAMP}}": chunk.start.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "{{END_TIMESTAMP}}": chunk.end.strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    for marker, value in values.items():
        if sql.count(marker) == 0:
            raise VaultAcquisitionError(f"missing SQL marker {marker}")
        sql = sql.replace(marker, value)
    lower = sql.lower()
    for table in ("vat_call_frob", "vat_call_fork", "vat_call_grab", "ethereum.transactions"):
        if table not in lower:
            raise VaultAcquisitionError(f"monthly SQL lacks {table}")
    if "select *" in lower or "call_tx_index" in lower:
        raise VaultAcquisitionError("monthly SQL violates projection or ordering controls")
    required_order = (
        "order by\n    m.block_number,\n    t.transaction_index,\n"
        "    m.trace_address_raw,\n    m.transaction_hash_raw,\n"
        "    m.call_type,"
    )
    if required_order not in lower:
        raise VaultAcquisitionError("monthly SQL lacks deterministic numeric trace ordering")
    return sql


def month_paths(chunk: MonthChunk) -> dict[str, Path]:
    chunk_name = f"chunk_{chunk.chunk_id}"
    raw_base = RAW_CHUNK_ROOT / chunk_name
    processed_base = PROCESSED_CHUNK_ROOT / chunk_name
    provenance_base = PROVENANCE_CHUNK_ROOT / chunk_name
    return {
        "directory": raw_base,
        "sql": GENERATED_SQL_ROOT / chunk_name / "query.sql",
        "state": provenance_base / "state.json",
        "payload": INGRESS_ROOT / chunk_name / ".result.partial.json",
        "combined": (
            processed_base / "vat_mutations.csv"
            if chunk.chunk_id == "05_2020_03"
            else raw_base / "vat_mutations.csv"
        ),
        "frob": processed_base / "vat_frob.csv",
        "fork": processed_base / "vat_fork.csv",
        "grab": processed_base / "vat_grab.csv",
        "validation": provenance_base / "validation.json",
        "metadata": provenance_base / "metadata.json",
    }


def subwindow_paths(window: Subwindow) -> dict[str, Path]:
    parent = f"chunk_{window.parent_chunk_id}"
    raw_base = RAW_CHUNK_ROOT / parent / "subwindows" / window.label
    provenance_base = PROVENANCE_CHUNK_ROOT / parent / "subwindows" / window.label
    return {
        "directory": raw_base,
        "sql": GENERATED_SQL_ROOT / parent / "subwindows" / window.label / "query.sql",
        "state": provenance_base / "state.json",
        "payload": INGRESS_ROOT / parent / "subwindows" / window.label / ".result.partial.json",
        "raw": raw_base / "vat_mutations.csv",
        "validation": provenance_base / "validation.json",
        "metadata": provenance_base / "metadata.json",
    }


def stream_paths(kind: str) -> dict[str, Path]:
    raw_base = RAW_STREAM_ROOT / kind
    provenance_base = PROVENANCE_STREAM_ROOT / kind
    return {
        "directory": raw_base,
        "sql": GENERATED_SQL_ROOT / "streams" / kind / "query.sql",
        "state": provenance_base / "state.json",
        "payload": INGRESS_ROOT / "streams" / kind / ".result.partial.json",
        "raw": raw_base / f"{kind}.csv",
        "validation": provenance_base / "validation.json",
        "metadata": provenance_base / "metadata.json",
    }


def _write_sql(path: Path, sql: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(sql)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def _manifest() -> dict[str, Any]:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "phase": "1E production",
        "status": "in_progress",
        "provider": "Dune",
        "engine": "small",
        "query_type": "private temporary bounded production",
        "scan_start_utc": SCAN_START.isoformat(),
        "sample_start_utc": SAMPLE_START.isoformat(),
        "sample_end_exclusive_utc": SAMPLE_END.isoformat(),
        "target_ilks": list(TARGET_ILKS),
        "monthly_chunk_count": len(MONTHS),
        "months": {},
        "streams": {},
        "automatic_retry_count": 0,
    }


def sync_manifest(section: str, key: str, state: dict[str, Any]) -> None:
    manifest = _manifest()
    manifest.setdefault(section, {})
    manifest[section][key] = state
    manifest["updated_at_utc"] = utc_now()
    write_json_atomic(MANIFEST_PATH, manifest)


def initialise_month(chunk: MonthChunk) -> dict[str, Any]:
    paths = month_paths(chunk)
    if paths["state"].exists():
        state = json.loads(paths["state"].read_text(encoding="utf-8"))
        if state.get("state") == "complete" and state.get("validation_passed"):
            return {**state, "skipped_completed": True}
        raise VaultAcquisitionError(f"{chunk.chunk_id} has incomplete state; replacement is not authorised")
    sql = render_month_sql(chunk)
    _write_sql(paths["sql"], sql)
    state = {
        "chunk_id": chunk.chunk_id,
        "chunk_number": chunk.number,
        "start_utc": chunk.start.isoformat(),
        "end_exclusive_utc": chunk.end.isoformat(),
        "state": "planned",
        "engine": "small",
        "sql_path": relative(paths["sql"]),
        "sql_sha256": sha256_bytes(sql.encode()),
        "query_id": None,
        "execution_id": None,
        "retrieval_count": 0,
        "raw_file_persisted": False,
        "validation_passed": False,
        "created_at_utc": utc_now(),
    }
    write_json_atomic(paths["state"], state)
    sync_manifest("months", chunk.chunk_id, state)
    return state


def initialise_subwindow(window: Subwindow) -> dict[str, Any]:
    paths = subwindow_paths(window)
    if paths["state"].exists():
        state = json.loads(paths["state"].read_text(encoding="utf-8"))
        if state.get("state") == "complete" and state.get("validation_passed"):
            return {**state, "skipped_completed": True}
        raise VaultAcquisitionError(
            f"{window.label} has incomplete state; replacement is not authorised"
        )
    sql = render_month_sql(window)
    _write_sql(paths["sql"], sql)
    state = {
        "subwindow": window.label,
        "parent_chunk_id": window.parent_chunk_id,
        "start_utc": window.start.isoformat(),
        "end_exclusive_utc": window.end.isoformat(),
        "state": "planned",
        "engine": "small",
        "sql_path": relative(paths["sql"]),
        "sql_sha256": sha256_bytes(sql.encode()),
        "query_id": None,
        "execution_id": None,
        "retrieval_count": 0,
        "raw_file_persisted": False,
        "validation_passed": False,
        "created_at_utc": utc_now(),
    }
    write_json_atomic(paths["state"], state)
    sync_manifest("replacement_subwindows", window.label, state)
    return state


def initialise_stream(kind: str) -> dict[str, Any]:
    if kind not in STREAM_SPECS:
        raise VaultAcquisitionError(f"unknown stream {kind}")
    paths = stream_paths(kind)
    if paths["state"].exists():
        state = json.loads(paths["state"].read_text(encoding="utf-8"))
        if state.get("state") == "complete" and state.get("validation_passed"):
            return {**state, "skipped_completed": True}
        raise VaultAcquisitionError(f"{kind} has incomplete state; replacement is not authorised")
    sql = STREAM_SPECS[kind]["sql"].read_text(encoding="utf-8")
    _write_sql(paths["sql"], sql)
    state = {
        "stream": kind, "state": "planned", "engine": "small",
        "sql_path": relative(paths["sql"]), "sql_sha256": sha256_bytes(sql.encode()),
        "query_id": None, "execution_id": None, "retrieval_count": 0,
        "raw_file_persisted": False, "validation_passed": False,
        "created_at_utc": utc_now(),
    }
    write_json_atomic(paths["state"], state)
    sync_manifest("streams", kind, state)
    return state


def record_submission(paths: dict[str, Path], section: str, key: str,
                      query_id: int, execution_id: str, query_url: str,
                      execution_state: str, usage_before: float) -> dict[str, Any]:
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    if state.get("query_id") or state.get("execution_id"):
        raise VaultAcquisitionError("query identifiers already recorded")
    state.update({
        "state": "execution_submitted", "query_id": query_id,
        "query_url": query_url, "execution_id": execution_id,
        "execution_state": execution_state, "usage_before": usage_before,
        "submitted_at_utc": utc_now(),
    })
    write_json_atomic(paths["state"], state)
    sync_manifest(section, key, state)
    return state


def _extract(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    rows, columns, metadata, state = _normalise_result_payload(payload)
    if not isinstance(rows, list):
        raise VaultAcquisitionError("completed payload contains no rows array")
    if metadata.get("totalRowCount") != len(rows):
        raise VaultAcquisitionError("result is incomplete or paginated")
    if state != "COMPLETED":
        raise VaultAcquisitionError(f"execution is not completed: {state}")
    return rows, columns, metadata


def _normalise_result_payload(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]] | None, list[str], dict[str, Any], str]:
    """Normalise MCP and direct Dune result-endpoint envelopes."""
    if "result" in payload:
        result = payload.get("result") or {}
        raw_metadata = result.get("metadata") or {}
        columns = [
            str(item.get("name") if isinstance(item, dict) else item)
            for item in raw_metadata.get("column_names", [])
        ]
        metadata = {
            "columns": [{"name": name} for name in columns],
            "totalRowCount": raw_metadata.get("total_row_count"),
            "executionCostCredits": raw_metadata.get("execution_cost_credits"),
        }
        state = str(payload.get("state", "")).removeprefix("QUERY_STATE_")
        return result.get("rows"), columns, metadata, state
    metadata = payload.get("resultMetadata") or {}
    columns = [str(item["name"]) for item in metadata.get("columns", [])]
    return (
        payload.get("data", {}).get("rows"),
        columns,
        metadata,
        str(payload.get("state", "")).removeprefix("QUERY_STATE_"),
    )


def _truth(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1"}


def _address(value: Any) -> bool:
    return bool(re.fullmatch(r"0x[0-9A-Fa-f]{40}", str(value or "")))


def _hash(value: Any) -> bool:
    return bool(re.fullmatch(r"0x[0-9A-Fa-f]{64}", str(value or "")))


def trace_tuple(value: Any) -> tuple[int, ...]:
    """Parse a non-root dot-serialised trace position numerically."""
    if value is None:
        raise VaultAcquisitionError("trace position is SQL null")
    text = str(value).strip()
    if not text:
        raise VaultAcquisitionError("root trace requires the validated root parser")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", text):
        raise VaultAcquisitionError("malformed trace position")
    return tuple(int(part) for part in text.split("."))


def parsed_trace_position(row: dict[str, Any], field: str,
                          *, allow_serialised_root: bool) -> tuple[int, ...]:
    """Distinguish a present serialised root array from missing metadata.

    Dune's ARRAY_JOIN over the decoded, non-null ``array(bigint)`` call trace
    produces ``""`` for the valid top-level empty array.  Only SQL projections
    explicitly validated to have that provenance may opt into root handling.
    """
    if field not in row:
        raise VaultAcquisitionError("trace-position field is absent")
    value = row[field]
    if value is None:
        raise VaultAcquisitionError("trace position is SQL null")
    if value == "":
        if allow_serialised_root:
            return ()
        raise VaultAcquisitionError("serialised root is not authorised for this parser path")
    return trace_tuple(value)


def validate_mutations(rows: list[dict[str, Any]], chunk: MonthChunk) -> dict[str, Any]:
    failures: list[str] = []
    keys: set[tuple[str, str, str]] = set()
    counts = {"frob": 0, "fork": 0, "grab": 0}
    start, end = chunk.start.to_pydatetime(), chunk.end.to_pydatetime()
    ordering: list[tuple[Any, ...]] = []
    for index, row in enumerate(rows):
        call_type = str(row.get("call_type"))
        counts[call_type] = counts.get(call_type, 0) + 1
        if call_type not in {"frob", "fork", "grab"}:
            failures.append(f"row {index} has invalid call type")
        if row.get("ilk") not in TARGET_ILKS or not _truth(row.get("call_success")):
            failures.append(f"row {index} is not a successful target-ilk call")
        if str(row.get("source_contract", "")).lower() != CANONICAL_VAT:
            failures.append(f"row {index} has non-canonical Vat contract")
        if not _hash(row.get("transaction_hash")):
            failures.append(f"row {index} has invalid transaction hash")
        try:
            timestamp = pd.Timestamp(row["block_time_utc"]).to_pydatetime()
            position = parsed_trace_position(
                row, "trace_position", allow_serialised_root=True
            )
            tx_index = int(row["transaction_index"])
            int(str(row["dink_raw"])); int(str(row["dart_raw"]))
        except (ValueError, TypeError, InvalidOperation, VaultAcquisitionError) as error:
            failures.append(f"row {index} has invalid ordering or signed values: {error}")
            continue
        if not start <= timestamp < end:
            failures.append(f"row {index} falls outside its month")
        urn_identity = (
            str(row.get("urn") or "").lower(),
            str(row.get("source_urn") or "").lower(),
            str(row.get("destination_urn") or "").lower(),
        )
        key = (
            str(row["source_table"]), str(row["block_number"]),
            str(row["transaction_hash"]).lower(), repr(position),
            str(row["source_contract"]).lower(), str(row["ilk"]), *urn_identity,
        )
        if key in keys:
            failures.append(f"row {index} duplicates a source call")
        keys.add(key)
        if call_type == "fork":
            if row.get("urn") or not _address(row.get("source_urn")) or not _address(row.get("destination_urn")):
                failures.append(f"row {index} has malformed fork urn fields")
        elif not _address(row.get("urn")) or row.get("source_urn") or row.get("destination_urn"):
            failures.append(f"row {index} has malformed frob/grab urn fields")
        ordering.append((int(row["block_number"]), tx_index, position,
                         {"frob": 0, "fork": 1, "grab": 2}.get(call_type, 9),
                         str(row["transaction_hash"]).lower()))
    unresolved_ties = len(ordering) - len(set(ordering))
    if unresolved_ties:
        failures.append(f"{unresolved_ties} unresolved deterministic-order ties")
    return {
        "validation_passed": not failures, "failures": failures,
        "row_count": len(rows), "source_counts": counts,
        "duplicate_source_call_count": len(rows) - len(keys),
        "unresolved_ordering_tie_count": unresolved_ties,
        "valid_root_trace_count": sum(
            row.get("trace_position") == "" for row in rows
        ),
        "trace_policy": (
            "A present empty string produced by ARRAY_JOIN over the decoded "
            "non-null empty call_trace_address array is the numeric root tuple (); "
            "absent, null and malformed values remain invalid."
        ),
    }


def deterministic_mutation_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Return the exact local counterpart of the production SQL ordering."""
    return (
        int(row["block_number"]),
        int(row["transaction_index"]),
        parsed_trace_position(row, "trace_position", allow_serialised_root=True),
        str(row["transaction_hash"]).lower(),
        str(row["call_type"]),
        str(row["ilk"]),
        str(row.get("urn") or "").lower(),
        str(row.get("source_urn") or "").lower(),
        str(row.get("destination_urn") or "").lower(),
    )


def query_has_deterministic_order(sql: str) -> bool:
    normalised = re.sub(r"\s+", " ", sql.lower()).strip()
    required = (
        "order by m.block_number, t.transaction_index, m.trace_address_raw, "
        "m.transaction_hash_raw, m.call_type, m.ilk, m.urn_raw, "
        "m.source_urn_raw, m.destination_urn_raw"
    )
    return required in normalised


def page_plan(total_rows: int, page_limit: int = PAGE_LIMIT) -> tuple[tuple[int, int], ...]:
    if total_rows < 0 or page_limit <= 0:
        raise VaultAcquisitionError("invalid pagination dimensions")
    return tuple(
        (offset, min(page_limit, total_rows - offset))
        for offset in range(0, total_rows, page_limit)
    )


def page_path(chunk: MonthChunk, offset: int, row_count: int) -> Path:
    end = offset + row_count - 1
    return month_paths(chunk)["directory"] / f"page_{offset:05d}_{end:05d}.json"


def persisted_page_offsets(
    chunk: MonthChunk,
    total_rows: int,
    page_limit: int = PAGE_LIMIT,
) -> tuple[int, ...]:
    return tuple(
        offset
        for offset, row_count in page_plan(total_rows, page_limit)
        if page_path(chunk, offset, row_count).exists()
    )


def _extract_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    rows, columns, metadata, state = _normalise_result_payload(payload)
    if not isinstance(rows, list):
        raise VaultAcquisitionError("completed page contains no rows array")
    total = metadata.get("totalRowCount")
    if not isinstance(total, int) or total < len(rows):
        raise VaultAcquisitionError("page has invalid API-reported total")
    if state != "COMPLETED":
        raise VaultAcquisitionError(f"execution is not completed: {state}")
    return rows, columns, metadata


def validate_page_sequence(
    pages: list[tuple[int, dict[str, Any]]],
    *,
    expected_total: int,
    page_limit: int = PAGE_LIMIT,
    ordered_sql: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not ordered_sql:
        raise VaultAcquisitionError("refusing to paginate a result without deterministic ordering")
    expected_plan = page_plan(expected_total, page_limit)
    if tuple((offset, len(payload.get("data", {}).get("rows", [])))
             for offset, payload in pages) != expected_plan:
        raise VaultAcquisitionError("page offsets or row counts contain a gap or overlap")
    combined: list[dict[str, Any]] = []
    totals: set[int] = set()
    schemas: set[tuple[str, ...]] = set()
    page_details: list[dict[str, Any]] = []
    prior_final_key: tuple[Any, ...] | None = None
    for offset, payload in pages:
        rows, columns, metadata = _extract_page(payload)
        totals.add(int(metadata["totalRowCount"]))
        schemas.add(tuple(columns))
        if tuple(columns) != MUTATION_COLUMNS:
            raise VaultAcquisitionError("paginated result schema differs from mutation schema")
        keys = [deterministic_mutation_key(row) for row in rows]
        if any(left >= right for left, right in zip(keys, keys[1:])):
            raise VaultAcquisitionError("page is not strictly deterministically ordered")
        if prior_final_key is not None and keys and prior_final_key >= keys[0]:
            raise VaultAcquisitionError("page boundary overlaps or is not strictly ordered")
        if keys:
            prior_final_key = keys[-1]
        combined.extend(rows)
        page_details.append({
            "offset": offset,
            "limit": page_limit,
            "returned_rows": len(rows),
            "api_reported_total_rows": metadata["totalRowCount"],
        })
    if totals != {expected_total}:
        raise VaultAcquisitionError("API-reported total changed between page requests")
    if len(schemas) != 1 or len(combined) != expected_total:
        raise VaultAcquisitionError("paginated result is incomplete")
    stable_keys = [deterministic_mutation_key(row) for row in combined]
    if len(stable_keys) != len(set(stable_keys)):
        raise VaultAcquisitionError("duplicate stable source key across pages")
    return combined, {
        "page_count": len(pages),
        "page_limit": page_limit,
        "total_rows": expected_total,
        "pages": page_details,
    }


def validate_subwindow_coverage(windows: Iterable[Subwindow]) -> dict[str, Any]:
    values = tuple(windows)
    failures: list[str] = []
    if not values:
        failures.append("sub-window plan is empty")
    for previous, current in zip(values, values[1:]):
        if previous.end != current.start:
            failures.append(f"gap or overlap between {previous.label} and {current.label}")
    if values and (
        values[0].start != pd.Timestamp("2020-03-01T00:00:00Z")
        or values[-1].end != pd.Timestamp("2020-04-01T00:00:00Z")
    ):
        failures.append("replacement plan does not exactly cover March 2020")
    return {"validation_passed": not failures, "failures": failures}


def _validate_common(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> list[str]:
    failures: list[str] = []
    keys: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows):
        if not _truth(row.get("call_success")) or not _hash(row.get("transaction_hash")):
            failures.append(f"row {index} is unsuccessful or has malformed hash")
        try:
            int(row["block_number"]); int(row["transaction_index"])
            position_field = "open_trace_position" if "open_trace_position" in columns else "trace_position"
            parsed_trace_position(row, position_field, allow_serialised_root=True)
        except (ValueError, TypeError, VaultAcquisitionError):
            failures.append(f"row {index} has invalid deterministic ordering")
        key = (str(row.get("transaction_hash")).lower(), str(row.get("transaction_index")),
               str(row.get("open_trace_position") or row.get("trace_position")))
        if key in keys:
            failures.append(f"row {index} duplicates a source record")
        keys.add(key)
    return failures


def validate_stream(kind: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    columns = tuple(STREAM_SPECS[kind]["columns"])
    failures = _validate_common(rows, columns)
    if kind == "open":
        cdps: dict[str, str] = {}
        urns: dict[str, str] = {}
        for index, row in enumerate(rows):
            if row.get("ilk") not in TARGET_ILKS:
                failures.append(f"row {index} has unexpected ilk")
            if str(row.get("manager_contract", "")).lower() != CANONICAL_MANAGER:
                failures.append(f"row {index} has non-canonical manager")
            if not _address(row.get("urn")) or not _address(row.get("initial_owner")):
                failures.append(f"row {index} has malformed mapping address")
            if not _truth(row.get("creation_is_direct_child")) or row.get("initial_owner") != row.get("event_owner"):
                failures.append(f"row {index} fails open/NewCdp/creation reconciliation")
            cdp, urn = str(row.get("cdp_id")), str(row.get("urn")).lower()
            if cdp in cdps and cdps[cdp] != urn:
                failures.append(f"CDP {cdp} maps to more than one urn")
            if urn in urns and urns[urn] != cdp:
                failures.append(f"urn {urn} maps to more than one CDP")
            cdps[cdp], urns[urn] = urn, cdp
    elif kind == "give":
        for index, row in enumerate(rows):
            if str(row.get("manager_contract", "")).lower() != CANONICAL_MANAGER or not _address(row.get("new_owner")):
                failures.append(f"row {index} has invalid give mapping")
    else:
        for index, row in enumerate(rows):
            record_type = row.get("rate_record_type")
            if row.get("ilk") not in TARGET_ILKS or record_type not in {"drip", "fold"}:
                failures.append(f"row {index} has invalid rate identity")
            expected_contract = CANONICAL_JUG if record_type == "drip" else CANONICAL_VAT
            if str(row.get("source_contract", "")).lower() != expected_contract:
                failures.append(f"row {index} has invalid rate source contract")
            raw = row.get("raw_rate_ray") if record_type == "drip" else row.get("raw_rate_delta")
            try:
                value = int(str(raw))
                if record_type == "drip" and value <= 0:
                    failures.append(f"row {index} has non-positive stored rate")
            except ValueError:
                failures.append(f"row {index} has malformed rate integer")
    return {"validation_passed": not failures, "failures": failures, "row_count": len(rows)}


def _promote(paths: dict[str, Path], columns: tuple[str, ...], rows: list[dict[str, Any]],
             validation: dict[str, Any], metadata: dict[str, Any]) -> None:
    write_csv_atomic(paths["raw"], columns, rows)
    with paths["raw"].open(newline="", encoding="utf-8") as handle:
        parsed = list(csv.DictReader(handle))
    if len(parsed) != len(rows):
        raise VaultAcquisitionError("persisted CSV row count changed")
    write_json_atomic(paths["validation"], validation)
    metadata.update({
        "raw_path": relative(paths["raw"]), "row_count": len(rows),
        "column_count": len(columns), "file_size_bytes": paths["raw"].stat().st_size,
        "file_sha256": sha256_file(paths["raw"]),
    })
    write_json_atomic(paths["metadata"], metadata)


def _promote_mutation_rows(
    paths: dict[str, Path],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    write_csv_atomic(paths["combined"], MUTATION_COLUMNS, rows)
    outputs: dict[str, Any] = {}
    for call_type in ("frob", "fork", "grab"):
        selected = [row for row in rows if row["call_type"] == call_type]
        write_csv_atomic(paths[call_type], MUTATION_COLUMNS, selected)
        outputs[call_type] = {
            "path": relative(paths[call_type]),
            "rows": len(selected),
            "size_bytes": paths[call_type].stat().st_size,
            "sha256": sha256_file(paths[call_type]),
        }
    return {
        "combined_path": relative(paths["combined"]),
        "combined_rows": len(rows),
        "combined_size_bytes": paths["combined"].stat().st_size,
        "combined_sha256": sha256_file(paths["combined"]),
        "outputs": outputs,
    }


def persist_month(chunk: MonthChunk, usage_after: float, *, preserve_payload: bool = False,
                  recovery: bool = False) -> dict[str, Any]:
    paths = month_paths(chunk)
    payload = json.loads(paths["payload"].read_text(encoding="utf-8"))
    rows, columns, result_metadata = _extract(payload)
    if tuple(columns) != MUTATION_COLUMNS:
        raise VaultAcquisitionError(f"unexpected mutation columns: {columns}")
    validation = validate_mutations(rows, chunk)
    write_json_atomic(paths["validation"], validation)
    if not validation["validation_passed"]:
        raise VaultAcquisitionError("; ".join(validation["failures"]))
    promoted = _promote_mutation_rows(paths, rows)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    metadata = {
        "query_id": state["query_id"], "execution_id": state["execution_id"],
        "execution_state": payload["state"], "execution_cost_credits": result_metadata.get("executionCostCredits"),
        "usage_before": state["usage_before"], "usage_after": usage_after,
        "observed_credit_delta": usage_after - float(state["usage_before"]),
        **promoted,
    }
    write_json_atomic(paths["metadata"], metadata)
    state.update({
        "state": "complete", "execution_state": "COMPLETED", "retrieval_count": 1,
        "raw_file_persisted": True, "validation_passed": True,
        "row_count": len(rows), "usage_after": usage_after,
        "observed_credit_delta": metadata["observed_credit_delta"],
        "combined_sha256": metadata["combined_sha256"], "completed_at_utc": utc_now(),
    })
    if recovery:
        state.update({
            "local_recovery": True,
            "recovery_additional_dune_call_count": 0,
            "recovery_additional_dune_credits": 0.0,
            "recovery_trace_policy": validation["trace_policy"],
            "recovery_source_payload_preserved": preserve_payload,
        })
        metadata.update({
            "local_recovery": True,
            "recovery_additional_dune_call_count": 0,
            "recovery_additional_dune_credits": 0.0,
            "source_payload_preserved": preserve_payload,
        })
        write_json_atomic(paths["metadata"], metadata)
    write_json_atomic(paths["state"], state)
    sync_manifest("months", chunk.chunk_id, state)
    if not preserve_payload:
        paths["payload"].unlink()
    return {"state": state, "metadata": metadata, "validation": validation}


def persist_paginated_month(
    chunk: MonthChunk,
    usage_after: float,
    *,
    expected_total: int,
) -> dict[str, Any]:
    paths = month_paths(chunk)
    sql = paths["sql"].read_text(encoding="utf-8")
    plan = page_plan(expected_total)
    pages: list[tuple[int, dict[str, Any]]] = []
    page_provenance: list[dict[str, Any]] = []
    for offset, row_count in plan:
        path = page_path(chunk, offset, row_count)
        if not path.exists():
            raise VaultAcquisitionError(f"missing persisted page at offset {offset}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        pages.append((offset, payload))
        page_provenance.append({
            "path": relative(path),
            "offset": offset,
            "limit": PAGE_LIMIT,
            "returned_rows": row_count,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    rows, pagination = validate_page_sequence(
        pages,
        expected_total=expected_total,
        ordered_sql=query_has_deterministic_order(sql),
    )
    validation = validate_mutations(rows, chunk)
    write_json_atomic(paths["validation"], validation)
    if not validation["validation_passed"]:
        raise VaultAcquisitionError("; ".join(validation["failures"]))
    promoted = _promote_mutation_rows(paths, rows)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    metadata = {
        "query_id": state["query_id"],
        "execution_id": state["execution_id"],
        "execution_state": "COMPLETED",
        "usage_before": state["usage_before"],
        "usage_after": usage_after,
        "observed_credit_delta": usage_after - float(state["usage_before"]),
        "recovery_method": "deterministic_execution_result_pagination",
        "pagination": pagination,
        "page_files": page_provenance,
        **promoted,
    }
    write_json_atomic(paths["metadata"], metadata)
    state.update({
        "state": "complete",
        "execution_state": "COMPLETED",
        "retrieval_count": len(pages),
        "raw_file_persisted": True,
        "validation_passed": True,
        "row_count": len(rows),
        "usage_after": usage_after,
        "observed_credit_delta": metadata["observed_credit_delta"],
        "combined_sha256": metadata["combined_sha256"],
        "pagination": pagination,
        "completed_at_utc": utc_now(),
    })
    write_json_atomic(paths["state"], state)
    sync_manifest("months", chunk.chunk_id, state)
    return {"state": state, "metadata": metadata, "validation": validation}


def persist_subwindow(window: Subwindow, usage_after: float) -> dict[str, Any]:
    paths = subwindow_paths(window)
    payload = json.loads(paths["payload"].read_text(encoding="utf-8"))
    rows, columns, result_metadata = _extract(payload)
    if tuple(columns) != MUTATION_COLUMNS:
        raise VaultAcquisitionError(f"unexpected mutation columns: {columns}")
    validation_chunk = MonthChunk(5, window.start, window.end)
    validation = validate_mutations(rows, validation_chunk)
    write_json_atomic(paths["validation"], validation)
    if not validation["validation_passed"]:
        raise VaultAcquisitionError("; ".join(validation["failures"]))
    write_csv_atomic(paths["raw"], MUTATION_COLUMNS, rows)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    metadata = {
        "query_id": state["query_id"],
        "execution_id": state["execution_id"],
        "execution_state": payload["state"],
        "execution_cost_credits": result_metadata.get("executionCostCredits"),
        "usage_before": state["usage_before"],
        "usage_after": usage_after,
        "observed_credit_delta": usage_after - float(state["usage_before"]),
        "raw_path": relative(paths["raw"]),
        "result_retrieval": {
            "endpoint": "execution-specific result endpoint",
            "limit": PAGE_LIMIT,
            "offset": 0,
            "physical_request_count": 1,
            "api_reported_total_rows": result_metadata.get("totalRowCount"),
        },
        "row_count": len(rows),
        "column_count": len(MUTATION_COLUMNS),
        "file_size_bytes": paths["raw"].stat().st_size,
        "file_sha256": sha256_file(paths["raw"]),
    }
    write_json_atomic(paths["metadata"], metadata)
    state.update({
        "state": "complete",
        "execution_state": "COMPLETED",
        "retrieval_count": 1,
        "raw_file_persisted": True,
        "validation_passed": True,
        "row_count": len(rows),
        "usage_after": usage_after,
        "observed_credit_delta": metadata["observed_credit_delta"],
        "raw_sha256": metadata["file_sha256"],
        "result_retrieval": metadata["result_retrieval"],
        "completed_at_utc": utc_now(),
    })
    write_json_atomic(paths["state"], state)
    sync_manifest("replacement_subwindows", window.label, state)
    paths["payload"].unlink()
    return {"state": state, "metadata": metadata, "validation": validation}


def combine_chunk_05_replacement(expected_rows: int = 43_081) -> dict[str, Any]:
    coverage = validate_subwindow_coverage(CHUNK_05_SUBWINDOWS)
    if not coverage["validation_passed"]:
        raise VaultAcquisitionError("; ".join(coverage["failures"]))
    pages: list[list[dict[str, Any]]] = []
    provenance: list[dict[str, Any]] = []
    for window in CHUNK_05_SUBWINDOWS:
        paths = subwindow_paths(window)
        state = json.loads(paths["state"].read_text(encoding="utf-8"))
        if state.get("state") != "complete" or not state.get("validation_passed"):
            raise VaultAcquisitionError(f"sub-window {window.label} is incomplete")
        with paths["raw"].open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        pages.append(rows)
        provenance.append({
            "label": window.label,
            "start_utc": window.start.isoformat(),
            "end_exclusive_utc": window.end.isoformat(),
            "query_id": state["query_id"],
            "execution_id": state["execution_id"],
            "row_count": len(rows),
            "file_sha256": sha256_file(paths["raw"]),
            "observed_credit_delta": state["observed_credit_delta"],
            "result_retrieval": state.get("result_retrieval"),
        })
    if pages[0] and pages[1]:
        if deterministic_mutation_key(pages[0][-1]) >= deterministic_mutation_key(pages[1][0]):
            raise VaultAcquisitionError("sub-window boundary is not strictly ordered")
    rows = pages[0] + pages[1]
    if len(rows) != expected_rows:
        raise VaultAcquisitionError(
            f"replacement has {len(rows)} rows, expected {expected_rows}"
        )
    chunk = get_month("05_2020_03")
    validation = validate_mutations(rows, chunk)
    validation["subwindow_coverage"] = coverage
    if not validation["validation_passed"]:
        raise VaultAcquisitionError("; ".join(validation["failures"]))
    paths = month_paths(chunk)
    promoted = _promote_mutation_rows(paths, rows)
    write_json_atomic(paths["validation"], validation)
    original = json.loads(paths["state"].read_text(encoding="utf-8"))
    original_provenance = {
        "query_id": original.get("query_id"),
        "execution_id": original.get("execution_id"),
        "sql_sha256": original.get("sql_sha256"),
        "reported_result_rows": original.get("reported_result_rows", 43_081),
        "compute_credits": original.get("observed_credit_delta", 0.265),
        "retrieval_count": 1,
        "retrieved_rows": 32_000,
        "partial_payload_persisted": False,
        "failure_stage": "result_retrieval_pagination_gate",
        "failure_reason": (
            "The completed execution reports 43,081 rows, exceeding the "
            "execution-result endpoint's 32,000-row single-call maximum; "
            "the authorised retrieval was partial and was not persisted."
        ),
        "persistence_status": "superseded_unordered_result_not_used",
    }
    additional_observed_delta = sum(
        float(item["observed_credit_delta"]) for item in provenance
    )
    first_replacement_state = json.loads(
        subwindow_paths(CHUNK_05_SUBWINDOWS[0])["state"].read_text(
            encoding="utf-8"
        )
    )
    final_replacement_state = json.loads(
        subwindow_paths(CHUNK_05_SUBWINDOWS[-1])["state"].read_text(
            encoding="utf-8"
        )
    )
    metadata = {
        "recovery_method": "submonth_replacement",
        "existing_execution_pagination_safe": False,
        "existing_execution_pagination_rejection_reason": (
            "Original query 8077198 has no deterministic final ORDER BY; "
            "offset pages were not requested or combined in this recovery."
        ),
        "original_execution": original_provenance,
        "replacement_subwindows": provenance,
        "additional_query_count": 2,
        "additional_execution_count": 2,
        "retrieval_count": 2,
        "original_compute_credits": original_provenance["compute_credits"],
        "replacement_observed_credit_delta": additional_observed_delta,
        "replacement_compute_credits": None,
        "replacement_retrieval_credits": None,
        "credit_separation_note": (
            "Dune usage deltas include compute and result retrieval; the "
            "execution status endpoint did not expose them separately."
        ),
        "future_retrieval_policy": (
            "Results up to 32,000 rows use one atomic retrieval. Larger "
            "results require deterministic final SQL ordering and sequential "
            "32,000-row pages with total, schema, key and boundary validation; "
            "otherwise acquisition stops for an explicit sub-window plan."
        ),
        **promoted,
    }
    write_json_atomic(paths["metadata"], metadata)
    stale_original_fields = {
        "additional_compute_credits", "failure_reason", "failure_stage",
        "observed_credit_delta", "partial_payload_persisted",
        "reported_total_row_count", "requested_result_limit",
        "result_retrieved_partial", "usage_after", "usage_before",
    }
    state = {
        **{key: value for key, value in original.items()
           if key not in stale_original_fields},
        "state": "complete",
        "execution_state": "COMPLETED",
        "recovery_method": "submonth_replacement",
        "original_execution": original_provenance,
        "replacement_subwindows": provenance,
        "retrieval_count": 2,
        "raw_file_persisted": True,
        "validation_passed": True,
        "row_count": len(rows),
        "combined_sha256": promoted["combined_sha256"],
        "additional_query_count": 2,
        "additional_execution_count": 2,
        "existing_execution_pagination_safe": False,
        "replacement_observed_credit_delta": additional_observed_delta,
        "replacement_compute_credits": None,
        "replacement_retrieval_credits": None,
        "usage_before_replacement": first_replacement_state["usage_before"],
        "usage_after_replacement": final_replacement_state["usage_after"],
        "completed_at_utc": utc_now(),
    }
    write_json_atomic(paths["state"], state)
    sync_manifest("months", chunk.chunk_id, state)
    return {"state": state, "metadata": metadata, "validation": validation}


def recover_month(chunk: MonthChunk, expected_sha256: str, expected_size: int,
                  expected_rows: int) -> dict[str, Any]:
    paths = month_paths(chunk)
    if not paths["payload"].exists():
        raise VaultAcquisitionError("preserved recovery payload is absent")
    if paths["payload"].stat().st_size != expected_size:
        raise VaultAcquisitionError("preserved recovery payload size differs")
    observed_sha = sha256_file(paths["payload"])
    if observed_sha != expected_sha256:
        raise VaultAcquisitionError("preserved recovery payload checksum differs")
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    expected_provenance = {
        "query_id": 8076833,
        "execution_id": "01KY66A6KGCF1B6CZWS4QR2E8D",
        "sql_sha256": "7907375c9091d67d9e5e41afb5ffbe04e3d6beda07c198473d985d7c469ca30d",
    }
    for field, expected in expected_provenance.items():
        if state.get(field) != expected:
            raise VaultAcquisitionError(f"chunk-03 {field} provenance differs")
    payload = json.loads(paths["payload"].read_text(encoding="utf-8"))
    if payload.get("state") != "COMPLETED" or payload.get("resultMetadata", {}).get("totalRowCount") != expected_rows:
        raise VaultAcquisitionError("preserved recovery payload is incomplete")
    result = persist_month(
        chunk, float(state.get("usage_after", state["usage_before"])),
        preserve_payload=True, recovery=True,
    )
    if sha256_file(paths["payload"]) != expected_sha256:
        raise VaultAcquisitionError("recovery modified the preserved source payload")
    return result


def persist_stream(kind: str, usage_after: float) -> dict[str, Any]:
    paths = stream_paths(kind)
    payload = json.loads(paths["payload"].read_text(encoding="utf-8"))
    rows, columns, result_metadata = _extract(payload)
    expected = tuple(STREAM_SPECS[kind]["columns"])
    if tuple(columns) != expected:
        raise VaultAcquisitionError(f"unexpected {kind} columns: {columns}")
    validation = validate_stream(kind, rows)
    if not validation["validation_passed"]:
        write_json_atomic(paths["validation"], validation)
        raise VaultAcquisitionError("; ".join(validation["failures"]))
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    metadata = {
        "query_id": state["query_id"], "execution_id": state["execution_id"],
        "execution_state": payload["state"], "execution_cost_credits": result_metadata.get("executionCostCredits"),
        "usage_before": state["usage_before"], "usage_after": usage_after,
        "observed_credit_delta": usage_after - float(state["usage_before"]),
    }
    _promote(paths, expected, rows, validation, metadata)
    state.update({
        "state": "complete", "execution_state": "COMPLETED", "retrieval_count": 1,
        "raw_file_persisted": True, "validation_passed": True, "row_count": len(rows),
        "raw_sha256": metadata["file_sha256"], "usage_after": usage_after,
        "observed_credit_delta": metadata["observed_credit_delta"], "completed_at_utc": utc_now(),
    })
    write_json_atomic(paths["state"], state)
    sync_manifest("streams", kind, state)
    paths["payload"].unlink()
    return {"state": state, "metadata": metadata, "validation": validation}


def get_month(chunk_id: str) -> MonthChunk:
    for chunk in MONTHS:
        if chunk.chunk_id == chunk_id:
            return chunk
    raise VaultAcquisitionError(f"unknown chunk {chunk_id}")


def get_subwindow(label: str) -> Subwindow:
    for window in CHUNK_05_SUBWINDOWS:
        if window.label == label:
            return window
    raise VaultAcquisitionError(f"unknown replacement sub-window {label}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    init_month = sub.add_parser("init-month"); init_month.add_argument("--chunk", required=True)
    init_subwindow = sub.add_parser("init-subwindow")
    init_subwindow.add_argument("--subwindow", choices=("05A", "05B"), required=True)
    init_stream = sub.add_parser("init-stream"); init_stream.add_argument("--stream", choices=STREAM_SPECS, required=True)
    record_month = sub.add_parser("record-month")
    record_month.add_argument("--chunk", required=True); record_month.add_argument("--query-id", type=int, required=True)
    record_month.add_argument("--execution-id", required=True); record_month.add_argument("--query-url", required=True)
    record_month.add_argument("--execution-state", required=True); record_month.add_argument("--usage-before", type=float, required=True)
    record_stream = sub.add_parser("record-stream")
    record_stream.add_argument("--stream", choices=STREAM_SPECS, required=True); record_stream.add_argument("--query-id", type=int, required=True)
    record_stream.add_argument("--execution-id", required=True); record_stream.add_argument("--query-url", required=True)
    record_stream.add_argument("--execution-state", required=True); record_stream.add_argument("--usage-before", type=float, required=True)
    record_subwindow = sub.add_parser("record-subwindow")
    record_subwindow.add_argument("--subwindow", choices=("05A", "05B"), required=True)
    record_subwindow.add_argument("--query-id", type=int, required=True)
    record_subwindow.add_argument("--execution-id", required=True)
    record_subwindow.add_argument("--query-url", required=True)
    record_subwindow.add_argument("--execution-state", required=True)
    record_subwindow.add_argument("--usage-before", type=float, required=True)
    persist_month_parser = sub.add_parser("persist-month"); persist_month_parser.add_argument("--chunk", required=True); persist_month_parser.add_argument("--usage-after", type=float, required=True)
    persist_pages_parser = sub.add_parser("persist-month-pages")
    persist_pages_parser.add_argument("--chunk", required=True)
    persist_pages_parser.add_argument("--usage-after", type=float, required=True)
    persist_pages_parser.add_argument("--expected-total", type=int, required=True)
    persist_subwindow_parser = sub.add_parser("persist-subwindow")
    persist_subwindow_parser.add_argument("--subwindow", choices=("05A", "05B"), required=True)
    persist_subwindow_parser.add_argument("--usage-after", type=float, required=True)
    sub.add_parser("combine-chunk-05")
    recover_month_parser = sub.add_parser("recover-month")
    recover_month_parser.add_argument("--chunk", required=True)
    recover_month_parser.add_argument("--expected-sha256", required=True)
    recover_month_parser.add_argument("--expected-size", type=int, required=True)
    recover_month_parser.add_argument("--expected-rows", type=int, required=True)
    persist_stream_parser = sub.add_parser("persist-stream"); persist_stream_parser.add_argument("--stream", choices=STREAM_SPECS, required=True); persist_stream_parser.add_argument("--usage-after", type=float, required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        result = validate_plan()
        for chunk in MONTHS:
            render_month_sql(chunk)
    elif args.command == "init-month": result = initialise_month(get_month(args.chunk))
    elif args.command == "init-subwindow":
        result = initialise_subwindow(get_subwindow(args.subwindow))
    elif args.command == "init-stream": result = initialise_stream(args.stream)
    elif args.command == "record-month":
        chunk = get_month(args.chunk)
        result = record_submission(month_paths(chunk), "months", chunk.chunk_id, args.query_id, args.execution_id, args.query_url, args.execution_state, args.usage_before)
    elif args.command == "record-stream":
        result = record_submission(stream_paths(args.stream), "streams", args.stream, args.query_id, args.execution_id, args.query_url, args.execution_state, args.usage_before)
    elif args.command == "record-subwindow":
        window = get_subwindow(args.subwindow)
        result = record_submission(
            subwindow_paths(window), "replacement_subwindows", window.label,
            args.query_id, args.execution_id, args.query_url,
            args.execution_state, args.usage_before,
        )
    elif args.command == "persist-month": result = persist_month(get_month(args.chunk), args.usage_after)
    elif args.command == "persist-month-pages":
        result = persist_paginated_month(
            get_month(args.chunk), args.usage_after,
            expected_total=args.expected_total,
        )
    elif args.command == "persist-subwindow":
        result = persist_subwindow(
            get_subwindow(args.subwindow), args.usage_after
        )
    elif args.command == "combine-chunk-05":
        result = combine_chunk_05_replacement()
    elif args.command == "recover-month":
        result = recover_month(
            get_month(args.chunk), args.expected_sha256,
            args.expected_size, args.expected_rows,
        )
    else: result = persist_stream(args.stream, args.usage_after)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
