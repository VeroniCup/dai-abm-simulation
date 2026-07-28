"""Phase 1C bounded Maker Liquidations 2.0 production acquisition.

The module has no network or credential path. Dune MCP creates and executes one
private temporary query at a time; this module renders the validated SQL,
records identifiers, atomically persists returned rows, validates every chunk,
and only combines a complete 37-month acquisition.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
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
import re
import tempfile
from typing import Any, Callable, Iterable

import pandas as pd

from workflows.maintenance.archive.liquidation_diagnostic import (
    RAD, RAY, WAD, LiquidationDiagnosticError, provenance_path, sha256_file,
    utc_now_iso, write_json_atomic,
)
from workflows.maintenance.archive.liquidation_diagnostic_attempt3 import (
    ACTION_COLUMNS, TRANSACTION_COLUMNS, _fsync_directory, _parse_utc, _truth,
    _unwrap, auction_key, classify_successful_take_transactions,
    classify_terminals, partial_take_checks, reconcile_bark_kick, reconcile_event_calls,
    validate_transaction_rows,
)


PROJECT_ROOT = REPOSITORY_ROOT
DIAGNOSTIC_SQL = (
    PROJECT_ROOT
    / "sql"
    / "liquidations"
    / "generated"
    / "history"
    / "liquidation_actions_diagnostic.sql"
)
RAW_ROOT = PROJECT_ROOT / "data" / "liquidations" / "raw"
PROCESSED_ROOT = PROJECT_ROOT / "data" / "liquidations" / "processed"
PROVENANCE_ROOT = PROJECT_ROOT / "data" / "liquidations" / "provenance"
CHUNK_ROOT = RAW_ROOT / "chunks"
CHUNK_VALIDATION_ROOT = PROVENANCE_ROOT / "chunks"
STATE_ROOT = PROVENANCE_ROOT / "state"
SQL_ROOT = PROJECT_ROOT / "sql" / "liquidations" / "generated" / "history"
INGRESS_ROOT = PROVENANCE_ROOT / "ingress"
MANIFEST = PROVENANCE_ROOT / "manifest.json"
ACTION_COMBINED = PROCESSED_ROOT / "phase1c_liquidation_actions_2021-06-01_2024-06-30.csv"
TRANSACTION_COMBINED = PROCESSED_ROOT / "phase1c_liquidation_transactions_2021-06-01_2024-06-30.csv"
AUCTION_SUMMARY = PROCESSED_ROOT / "phase1c_liquidation_auctions_2021-06-01_2024-06-30.csv"
HOURLY_PANEL = PROCESSED_ROOT / "phase1c_liquidation_hourly_by_ilk_2021-06-01_2024-06-30.csv"
FINAL_VALIDATION = PROVENANCE_ROOT / "validation.json"
LEGACY_STATE = PROVENANCE_ROOT / "archive" / "legacy" / "phase1c_legacy_check_state.json"
LEGACY_RAW = PROVENANCE_ROOT / "archive" / "legacy" / "phase1c_legacy_check.csv"
LEGACY_CORRECTED_STATE = PROVENANCE_ROOT / "legacy" / "phase1c_legacy_check_corrected_state.json"
LEGACY_CORRECTED_RAW = PROVENANCE_ROOT / "legacy" / "phase1c_legacy_check_corrected.csv"
LEGACY_CORRECTED_SQL = SQL_ROOT / "legacy_cat_bite_check_corrected.sql"
FINAL_METADATA = PROVENANCE_ROOT / "metadata.json"
CHUNK_18_RECOVERY_STATE = STATE_ROOT / "chunk_18_2022_11_transaction.recovery.state.json"
CHUNK_18_RECOVERY_PAYLOAD = PROVENANCE_ROOT / "archive" / "chunk_18" / ".chunk_18_2022_11_transaction.recovery.partial.json"
CHUNK_18_REPLACEMENT_STATE = STATE_ROOT / "chunk_18_2022_11_transaction.replacement.state.json"
CHUNK_18_REPLACEMENT_PAYLOAD = PROVENANCE_ROOT / "archive" / "chunk_18" / ".chunk_18_2022_11_transaction.replacement.partial.json"
CHUNK_18_COMPLETED_RECOVERY_STATE = (
    STATE_ROOT / "chunk_18_2022_11_transaction.completed_result_recovery.state.json"
)
MARKET_PANEL = PROJECT_ROOT / "data" / "market" / "processed" / "dune_hourly_market_prices_processed.csv"
GAS_PANEL = PROJECT_ROOT / "data" / "gas" / "processed" / "dune_ethereum_hourly_gas_processed.csv"

FULL_START = pd.Timestamp("2021-06-01T00:00:00Z")
FULL_END = pd.Timestamp("2024-07-01T00:00:00Z")
FOLLOWUP_DAYS = 7
EXPECTED_ILKS = ("ETH-A", "ETH-B", "ETH-C", "WBTC-A", "WBTC-B", "WBTC-C")
YANK_TOPIC = "0x2c5d2826eb5903b8fc201cf48094b858f42f61c7eaac9aaf43ebed490138144e"
AUTHORISED_CHUNK_18_QUERY_ID = 8061091
AUTHORISED_CHUNK_18_EXECUTION_ID = "01KY3G6JYY6FN17K9SBT2QV2PF"
AUTHORISED_CHUNK_18_SQL_SHA256 = (
    "4f538ac04c25158e02b602cf72765ab170d9c1c03fbd5b806ebc33b292360595"
)
EXPECTED_CHUNK_18_ACTION_ROWS = 171


class ProductionAcquisitionError(RuntimeError):
    """Raised when a production acquisition invariant fails."""


@dataclass(frozen=True)
class ChunkSpec:
    number: int
    chunk_id: str
    start: pd.Timestamp
    end: pd.Timestamp
    followup_end: pd.Timestamp


def monthly_chunks() -> tuple[ChunkSpec, ...]:
    starts = pd.date_range(FULL_START, FULL_END, freq="MS", inclusive="left")
    chunks: list[ChunkSpec] = []
    for number, start in enumerate(starts, start=1):
        end = min(start + pd.offsets.MonthBegin(1), FULL_END)
        chunks.append(ChunkSpec(
            number=number,
            chunk_id=f"{number:02d}_{start:%Y_%m}",
            start=start,
            end=end,
            followup_end=end + pd.Timedelta(days=FOLLOWUP_DAYS),
        ))
    return tuple(chunks)


CHUNKS = monthly_chunks()


def validate_chunk_plan(chunks: Iterable[ChunkSpec] = CHUNKS) -> dict[str, Any]:
    values = tuple(chunks)
    failures: list[str] = []
    if len(values) != 37:
        failures.append(f"expected 37 monthly chunks, found {len(values)}")
    if not values or values[0].start != FULL_START or values[-1].end != FULL_END:
        failures.append("chunk boundaries do not cover the requested sample")
    if [chunk.number for chunk in values] != list(range(1, len(values) + 1)):
        failures.append("chunk numbers are not consecutive")
    for previous, current in zip(values, values[1:]):
        if previous.end != current.start:
            failures.append(f"non-contiguous chunks {previous.chunk_id}/{current.chunk_id}")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "chunk_count": len(values),
        "requested_start_utc": FULL_START.isoformat(),
        "requested_end_exclusive_utc": FULL_END.isoformat(),
    }


def _timestamp_literal(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def render_action_sql(chunk: ChunkSpec, template_path: Path = DIAGNOSTIC_SQL) -> str:
    template = template_path.read_text(encoding="utf-8")
    replacement = f"""windows(initiation_window_label, principal_start, principal_end, followup_end) AS (
    VALUES
        (
            '{chunk.chunk_id}',
            TIMESTAMP '{_timestamp_literal(chunk.start)}',
            TIMESTAMP '{_timestamp_literal(chunk.end)}',
            TIMESTAMP '{_timestamp_literal(chunk.followup_end)}'
        )
)"""
    rendered, count = re.subn(
        r"windows\(initiation_window_label, principal_start, principal_end, followup_end\) AS \(.*?\n\),\nselected_ilks",
        replacement + ",\nselected_ilks",
        template,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ProductionAcquisitionError("Could not replace diagnostic windows CTE.")
    rendered = rendered.replace(
        "-- Phase 1C attempt-three action/call extraction only.",
        f"-- Phase 1C production action/call extraction: {chunk.chunk_id}.",
    )
    forbidden = ("ethereum.transactions", "group by", "exists (")
    if any(fragment in rendered.lower() for fragment in forbidden):
        raise ProductionAcquisitionError("Rendered action SQL contains planner-heavy logic.")
    if rendered.lower().count(YANK_TOPIC) != 1:
        raise ProductionAcquisitionError("Rendered action SQL lost the verified Yank topic.")
    for ilk in EXPECTED_ILKS:
        if rendered.count(f"'{ilk}'") != 1:
            raise ProductionAcquisitionError(f"Rendered SQL does not preserve exact ilk {ilk}.")
    return rendered


def build_transaction_sql(hashes: Iterable[str], chunk: ChunkSpec) -> str:
    values = sorted({str(value).lower() for value in hashes})
    for value in values:
        if not re.fullmatch(r"0x[0-9a-f]{64}", value):
            raise ProductionAcquisitionError(f"Malformed transaction hash {value!r}.")
    if len(values) > 6_500:
        raise ProductionAcquisitionError(
            f"Chunk {chunk.chunk_id} has {len(values)} hashes; a single query risks the SQL size limit."
        )
    if values:
        values_sql = ",\n        ".join(f"({value})" for value in values)
        hashes_cte = f"selected_hashes(tx_hash) AS (\n    VALUES\n        {values_sql}\n)"
        from_sql = "FROM ethereum.transactions t\nJOIN selected_hashes h ON t.hash = h.tx_hash"
        where_sql = f"""WHERE t.block_date >= DATE '{chunk.start.date()}'
  AND t.block_date < DATE '{chunk.followup_end.date()}'
  AND t.block_time >= TIMESTAMP '{_timestamp_literal(chunk.start)}'
  AND t.block_time < TIMESTAMP '{_timestamp_literal(chunk.followup_end)}'"""
    else:
        hashes_cte = "selected_hashes(tx_hash) AS (SELECT CAST(NULL AS varbinary) WHERE false)"
        from_sql = "FROM ethereum.transactions t\nJOIN selected_hashes h ON t.hash = h.tx_hash"
        where_sql = "WHERE false"
    return f"""-- Phase 1C production unique transaction bridge: {chunk.chunk_id}.
WITH {hashes_cte}
SELECT
    CONCAT('0x', TO_HEX(t.hash)) AS tx_hash,
    CONCAT('0x', TO_HEX(t.\"from\")) AS transaction_sender,
    CONCAT('0x', TO_HEX(t.\"to\")) AS transaction_recipient,
    t.success,
    t.gas_limit,
    t.gas_used,
    t.gas_price,
    t.max_fee_per_gas,
    t.max_priority_fee_per_gas,
    t.priority_fee_per_gas,
    t.block_time,
    t.block_number,
    t.block_date,
    t.index AS transaction_index
{from_sql}
{where_sql}
"""


def sql_sha256(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def chunk_paths(chunk: ChunkSpec, kind: str) -> dict[str, Path]:
    stem = f"chunk_{chunk.chunk_id}_{kind}"
    raw_directory = CHUNK_ROOT / f"chunk_{chunk.chunk_id}"
    validation_directory = CHUNK_VALIDATION_ROOT / f"chunk_{chunk.chunk_id}"
    return {
        "sql": SQL_ROOT / f"{stem}.sql",
        "state": STATE_ROOT / f"{stem}.state.json",
        "raw": raw_directory / f"{stem}.csv",
        "validation": validation_directory / f"{stem}.validation.json",
        "payload": INGRESS_ROOT / f".{stem}.partial.json",
    }


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def initialise_query(chunk: ChunkSpec, kind: str, sql: str) -> dict[str, Any]:
    paths = chunk_paths(chunk, kind)
    if paths["state"].exists():
        state = json.loads(paths["state"].read_text(encoding="utf-8"))
        if state.get("state") == "complete" and state.get("validation_passed"):
            return state
        raise ProductionAcquisitionError(
            f"{chunk.chunk_id} {kind} has incomplete state {state.get('state')!r}; no retry is authorised."
        )
    for name in ("raw", "payload"):
        if paths[name].exists():
            raise ProductionAcquisitionError(f"Unexpected pre-existing {name}: {paths[name]}")
    _write_text_atomic(paths["sql"], sql)
    state = {
        "chunk_number": chunk.number,
        "chunk_id": chunk.chunk_id,
        "kind": kind,
        "state": "planned",
        "requested_start_utc": chunk.start.isoformat(),
        "requested_end_exclusive_utc": chunk.end.isoformat(),
        "followup_end_exclusive_utc": chunk.followup_end.isoformat(),
        "query_type": "private temporary bounded monthly production",
        "engine": "small",
        "sql_path": provenance_path(paths["sql"]),
        "sql_sha256": sql_sha256(sql),
        "query_id": None,
        "execution_id": None,
        "result_retrieved": False,
        "retrieval_count": 0,
        "raw_file_persisted": False,
        "validation_passed": False,
        "created_at_utc": utc_now_iso(),
    }
    write_json_atomic(paths["state"], state)
    sync_manifest(state)
    return state


def update_query_state(chunk: ChunkSpec, kind: str, status: str, **fields: Any) -> dict[str, Any]:
    path = chunk_paths(chunk, kind)["state"]
    state = json.loads(path.read_text(encoding="utf-8"))
    state.update(fields)
    state["state"] = status
    state["updated_at_utc"] = utc_now_iso()
    write_json_atomic(path, state)
    sync_manifest(state)
    return state


def sync_manifest(state: dict[str, Any]) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {
        "phase": "1C",
        "status": "in_progress",
        "architecture": "monthly shallow action query plus unique transaction bridge",
        "engine": "small",
        "requested_start_utc": FULL_START.isoformat(),
        "requested_end_exclusive_utc": FULL_END.isoformat(),
        "exact_ilks": list(EXPECTED_ILKS),
        "auction_key": ["clipper_contract", "auction_id"],
        "source_tables": [
            "maker_ethereum.dog_evt_bark", "maker_ethereum.dog_call_bark",
            "maker_ethereum.clipper_evt_kick", "maker_ethereum.clipper_call_kick",
            "maker_ethereum.clipper_evt_take", "maker_ethereum.clipper_call_take",
            "maker_ethereum.clipper_evt_redo", "maker_ethereum.clipper_call_redo",
            "ethereum.logs", "ethereum.transactions",
        ],
        "queries": [],
    }
    key = (state["chunk_id"], state["kind"])
    manifest["queries"] = [
        item for item in manifest["queries"]
        if (item["chunk_id"], item["kind"]) != key
    ] + [state]
    manifest["queries"].sort(key=lambda item: (item["chunk_number"], item["kind"]))
    manifest["updated_at_utc"] = utc_now_iso()
    write_json_atomic(MANIFEST, manifest)


def validate_action_chunk(
    rows: list[dict[str, Any]], columns: list[str], chunk: ChunkSpec,
) -> dict[str, Any]:
    failures: list[str] = []
    if tuple(columns) != ACTION_COLUMNS:
        failures.append("action schema differs from the validated 36-column schema")
    unexpected_ilks = sorted({row["ilk"] for row in rows}.difference(EXPECTED_ILKS))
    if unexpected_ilks:
        failures.append(f"unexpected ilks: {unexpected_ilks}")
    if any(row["initiation_window_label"] != chunk.chunk_id for row in rows):
        failures.append("incorrect initiation chunk label")
    identities: set[tuple[Any, ...]] = set()
    duplicates = 0
    for row in rows:
        identity = (
            row["source_table"], row["record_type"], row["tx_hash"],
            row["event_index"], row["call_trace_address"], row["clipper_contract"],
            row["auction_id"],
        )
        duplicates += int(identity in identities)
        identities.add(identity)
        timestamp = _parse_utc(row["block_time"])
        if timestamp < chunk.start.to_pydatetime() or timestamp >= chunk.followup_end.to_pydatetime():
            failures.append("action timestamp outside principal/follow-up bounds")
            break
    if duplicates:
        failures.append(f"{duplicates} duplicate source rows")
    bark_kick = reconcile_bark_kick(rows)
    if bark_kick["unmatched"] or bark_kick["multiply_matched"]:
        failures.append(f"Bark-Kick linkage failed: {bark_kick}")
    partial = partial_take_checks(rows)
    if partial["non_monotonic_or_redo_state_violation_count"]:
        failures.append("Take state is non-monotonic outside a valid Redo boundary")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(rows),
        "column_count": len(columns),
        "duplicate_source_row_count": duplicates,
        "exact_ilks_observed": sorted({row["ilk"] for row in rows}),
        "unique_auction_count": len({auction_key(row) for row in rows if row["record_type"] == "bark_event"}),
        "unique_transaction_count": len({row["tx_hash"].lower() for row in rows}),
        "bark_kick": bark_kick,
        "event_call_reconciliation": reconcile_event_calls(rows),
        "partial_take_validation": partial,
    }


def persist_payload(chunk: ChunkSpec, kind: str, ingress: Path) -> dict[str, Any]:
    paths = chunk_paths(chunk, kind)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    response = json.loads(ingress.read_text(encoding="utf-8"))
    payload, rows, columns = _unwrap(response)
    if str(payload.get("executionId")) != str(state.get("execution_id")):
        raise ProductionAcquisitionError("Execution ID differs from durable state.")
    if paths["raw"].exists() or paths["payload"].exists():
        raise ProductionAcquisitionError("Refusing to overwrite persisted or partial result.")
    _write_text_atomic(paths["payload"], json.dumps(response, indent=2, sort_keys=True) + "\n")
    if kind == "action":
        report = validate_action_chunk(rows, columns, chunk)
        order_key: Callable[[dict[str, Any]], Any] = lambda row: (
            _parse_utc(row["block_time"]), int(row.get("transaction_index") or 0),
            int(row.get("event_index") or -1), str(row.get("call_trace_address") or ""),
            row["record_type"],
        )
    else:
        action_rows, _ = read_csv(chunk_paths(chunk, "action")["raw"])
        expected_hashes = {row["tx_hash"].lower() for row in action_rows}
        report = validate_transaction_rows(rows, columns, expected_hashes=expected_hashes)
        order_key = lambda row: row["tx_hash"].lower()
    if not report["validation_passed"]:
        update_query_state(chunk, kind, "failed", failure=report["failures"], result_retrieved=True)
        raise ProductionAcquisitionError("; ".join(report["failures"]))
    paths["raw"].parent.mkdir(parents=True, exist_ok=True)
    descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{paths['raw'].name}.", suffix=".partial", dir=paths["raw"].parent,
    )
    os.close(descriptor)
    partial = Path(partial_name)
    with partial.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        writer.writerows(sorted(rows, key=order_key))
        handle.flush()
        os.fsync(handle.fileno())
    parsed, parsed_columns = read_csv(partial)
    if len(parsed) != len(rows) or parsed_columns != columns:
        raise ProductionAcquisitionError("Partial CSV structural validation failed.")
    checksum = sha256_file(partial)
    os.replace(partial, paths["raw"])
    _fsync_directory(paths["raw"].parent)
    report.update({
        "chunk_id": chunk.chunk_id,
        "kind": kind,
        "raw_file_path": provenance_path(paths["raw"]),
        "raw_file_sha256": checksum,
        "raw_file_size_bytes": paths["raw"].stat().st_size,
    })
    write_json_atomic(paths["validation"], report)
    metadata = payload.get("resultMetadata", {})
    state = update_query_state(
        chunk, kind, "complete", result_retrieved=True, retrieval_count=1,
        raw_file_persisted=True, validation_passed=True,
        row_count=len(parsed), column_count=len(columns),
        raw_file_path=provenance_path(paths["raw"]),
        raw_file_sha256=checksum, raw_file_size_bytes=paths["raw"].stat().st_size,
        validation_path=provenance_path(paths["validation"]),
        compute_credits=float(metadata.get("executionCostCredits") or 0),
        completed_at_utc=utc_now_iso(),
    )
    paths["payload"].unlink(missing_ok=True)
    ingress.unlink(missing_ok=True)
    return state


def read_csv(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def chunk_18_recovery_preflight() -> dict[str, Any]:
    """Prove that a result-only recovery cannot submit another execution."""
    chunk = CHUNKS[17]
    action_paths = chunk_paths(chunk, "action")
    transaction_paths = chunk_paths(chunk, "transaction")
    action_rows, action_columns = read_csv(action_paths["raw"])
    expected_hashes = {str(row["tx_hash"]).lower() for row in action_rows}
    state = json.loads(transaction_paths["state"].read_text(encoding="utf-8"))
    sql_text = transaction_paths["sql"].read_text(encoding="utf-8")
    failed_payload = Path(PROJECT_ROOT, state.get("failed_payload_path", ""))
    partial_csvs = sorted(CHUNK_ROOT.glob(f".{transaction_paths['raw'].name}.*.partial"))
    checks = {
        "chunk_18_action_schema": tuple(action_columns) == ACTION_COLUMNS,
        "chunk_18_action_rows": len(action_rows) == EXPECTED_CHUNK_18_ACTION_ROWS,
        "chunk_18_action_validation": validate_action_chunk(
            action_rows, action_columns, chunk,
        )["validation_passed"],
        "transaction_csv_absent": not transaction_paths["raw"].exists(),
        "complete_partial_csv_absent": not partial_csvs,
        "query_id": state.get("query_id") == AUTHORISED_CHUNK_18_QUERY_ID,
        "execution_id": state.get("execution_id") == AUTHORISED_CHUNK_18_EXECUTION_ID,
        "state_sql_checksum": state.get("sql_sha256") == AUTHORISED_CHUNK_18_SQL_SHA256,
        "local_sql_checksum": sql_sha256(sql_text) == AUTHORISED_CHUNK_18_SQL_SHA256,
        "failed_payload_preserved": failed_payload.exists(),
        "bounded_block_date_filter": (
            "t.block_date >= DATE '2022-11-01'" in sql_text
            and "t.block_date < DATE '2022-12-08'" in sql_text
        ),
        "bounded_timestamp_filter": (
            "t.block_time >= TIMESTAMP '2022-11-01 00:00:00'" in sql_text
            and "t.block_time < TIMESTAMP '2022-12-08 00:00:00'" in sql_text
        ),
        "no_ordering_or_aggregation": (
            "ORDER BY" not in sql_text.upper() and "GROUP BY" not in sql_text.upper()
        ),
        "literal_hashes_are_deduplicated": all(
            sql_text.lower().count(f"({value})") == 1 for value in expected_hashes
        ),
        "recovery_state_absent": not CHUNK_18_RECOVERY_STATE.exists(),
        "recovery_payload_absent": not CHUNK_18_RECOVERY_PAYLOAD.exists(),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "validation_passed": not failures,
        "failures": failures,
        "checks": checks,
        "action_row_count": len(action_rows),
        "expected_unique_transaction_hash_count": len(expected_hashes),
        "sql_size_bytes": len(sql_text.encode("utf-8")),
        "sql_literal_hash_count": sum(
            1 for line in sql_text.splitlines()
            if re.fullmatch(r"\s*\(0x[0-9a-f]{64}\),?\s*", line.lower())
        ),
        "sql_sha256": sql_sha256(sql_text),
        "partial_csv_paths": [provenance_path(path) for path in partial_csvs],
        "query_submission_capability": False,
    }


def initialise_chunk_18_recovery(preflight: dict[str, Any]) -> dict[str, Any]:
    """Create separate recovery provenance without erasing the timed-out attempt."""
    if not preflight.get("validation_passed"):
        raise ProductionAcquisitionError(f"Recovery preflight failed: {preflight['failures']}")
    if CHUNK_18_RECOVERY_STATE.exists():
        raise ProductionAcquisitionError("Refusing to overwrite the chunk-18 recovery state.")
    state = {
        "operation": "status-check and result-only recovery of existing execution",
        "query_id": AUTHORISED_CHUNK_18_QUERY_ID,
        "execution_id": AUTHORISED_CHUNK_18_EXECUTION_ID,
        "chunk_id": CHUNKS[17].chunk_id,
        "requested_start_utc": CHUNKS[17].start.isoformat(),
        "requested_end_exclusive_utc": CHUNKS[17].end.isoformat(),
        "sql_sha256": AUTHORISED_CHUNK_18_SQL_SHA256,
        "expected_rows": preflight["expected_unique_transaction_hash_count"],
        "expected_columns": len(TRANSACTION_COLUMNS),
        "status_request_count": 0,
        "result_request_count": 0,
        "query_created": False,
        "execution_submitted": False,
        "raw_file_persisted": False,
        "validation_passed": False,
        "original_timeout_state_path": provenance_path(
            chunk_paths(CHUNKS[17], "transaction")["state"]
        ),
        "original_timeout_payload_path": json.loads(
            chunk_paths(CHUNKS[17], "transaction")["state"].read_text(encoding="utf-8")
        ).get("failed_payload_path"),
        "preflight": preflight,
        "state": "recovery_planned",
        "created_at_utc": utc_now_iso(),
    }
    write_json_atomic(CHUNK_18_RECOVERY_STATE, state)
    return state


def update_chunk_18_recovery(status: str, **fields: Any) -> dict[str, Any]:
    state = json.loads(CHUNK_18_RECOVERY_STATE.read_text(encoding="utf-8"))
    state.update(fields)
    state["state"] = status
    state["updated_at_utc"] = utc_now_iso()
    write_json_atomic(CHUNK_18_RECOVERY_STATE, state)
    return state


def retrieve_then_persist(
    retrieve: Callable[[], dict[str, Any] | None],
    persist: Callable[[dict[str, Any]], Any],
) -> Any:
    """Ensure a returned response is immediately handed to persistence once."""
    response = retrieve()
    if response is None:
        raise ProductionAcquisitionError(
            "Result response is None; the persistence function was not called."
        )
    return persist(response)


def persist_chunk_18_recovery_response(
    response: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Immediately fsync and persist the one authorised existing result response."""
    if response is None:
        raise ProductionAcquisitionError("Result response is None; persistence is forbidden.")
    payload, rows, columns = _unwrap(response)
    recovery = json.loads(CHUNK_18_RECOVERY_STATE.read_text(encoding="utf-8"))
    if payload.get("executionId") != AUTHORISED_CHUNK_18_EXECUTION_ID:
        raise ProductionAcquisitionError("Recovery response is for an unauthorised execution.")
    if len(rows) != recovery["expected_rows"] or tuple(columns) != TRANSACTION_COLUMNS:
        raise ProductionAcquisitionError(
            f"Recovery shape is {len(rows)} x {len(columns)}; expected "
            f"{recovery['expected_rows']} x {len(TRANSACTION_COLUMNS)}."
        )
    descriptor, ingress_name = tempfile.mkstemp(
        prefix=f".{CHUNK_18_RECOVERY_PAYLOAD.name}.", suffix=".ingress",
        dir=CHUNK_18_RECOVERY_PAYLOAD.parent,
    )
    ingress = Path(ingress_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(response, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(ingress, CHUNK_18_RECOVERY_PAYLOAD)
        _fsync_directory(CHUNK_18_RECOVERY_PAYLOAD.parent)
    except Exception:
        ingress.unlink(missing_ok=True)
        raise
    update_chunk_18_recovery(
        "result_received", result_request_count=1,
        result_received_at_utc=utc_now_iso(),
        response_shape=[len(rows), len(columns)],
        response_payload_sha256=sha256_file(CHUNK_18_RECOVERY_PAYLOAD),
    )
    transaction_paths = chunk_paths(CHUNKS[17], "transaction")
    try:
        state = persist_payload(
            CHUNKS[17], "transaction", CHUNK_18_RECOVERY_PAYLOAD,
        )
    except Exception as exc:
        update_chunk_18_recovery(
            "persistence_failed", persistence_error=str(exc),
            raw_file_persisted=False, validation_passed=False,
        )
        raise
    validation = json.loads(transaction_paths["validation"].read_text(encoding="utf-8"))
    action_rows, _ = read_csv(chunk_paths(CHUNKS[17], "action")["raw"])
    transaction_rows, _ = read_csv(transaction_paths["raw"])
    tx_hashes = {row["tx_hash"].lower() for row in transaction_rows}
    joined_count = sum(row["tx_hash"].lower() in tx_hashes for row in action_rows)
    validation["action_transaction_join"] = {
        "action_row_count": len(action_rows),
        "joined_row_count": joined_count,
        "join_multiplication_count": joined_count - len(action_rows),
        "all_actions_matched_exactly_once": joined_count == len(action_rows),
    }
    validation["validation_passed"] = bool(
        validation["validation_passed"]
        and joined_count == len(action_rows)
    )
    write_json_atomic(transaction_paths["validation"], validation)
    update_query_state(
        CHUNKS[17], "transaction", "complete",
        recovery_operation="existing execution result recovery",
        recovery_status_request_count=1,
        recovery_result_request_count=1,
        original_mcp_timeout_preserved=True,
        validation_passed=validation["validation_passed"],
    )
    recovery = update_chunk_18_recovery(
        "complete", raw_file_persisted=True,
        validation_passed=validation["validation_passed"],
        raw_file_path=state["raw_file_path"],
        raw_file_sha256=state["raw_file_sha256"],
        raw_file_size_bytes=state["raw_file_size_bytes"],
        row_count=state["row_count"], column_count=state["column_count"],
        completed_at_utc=utc_now_iso(),
    )
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["status"] = "paused_after_chunk_18_recovery"
    manifest["next_chunk_not_started"] = CHUNKS[18].chunk_id
    manifest["updated_at_utc"] = utc_now_iso()
    write_json_atomic(MANIFEST, manifest)
    return recovery, validation


def chunk_18_replacement_preflight() -> dict[str, Any]:
    """Validate one authorised rerun while preserving both earlier failure records."""
    chunk = CHUNKS[17]
    action_paths = chunk_paths(chunk, "action")
    transaction_paths = chunk_paths(chunk, "transaction")
    action_rows, action_columns = read_csv(action_paths["raw"])
    hashes = {str(row["tx_hash"]).lower() for row in action_rows}
    original = json.loads(transaction_paths["state"].read_text(encoding="utf-8"))
    recovery = json.loads(CHUNK_18_RECOVERY_STATE.read_text(encoding="utf-8"))
    sql_text = transaction_paths["sql"].read_text(encoding="utf-8")
    checks = {
        "action_rows": len(action_rows) == EXPECTED_CHUNK_18_ACTION_ROWS,
        "action_schema": tuple(action_columns) == ACTION_COLUMNS,
        "action_valid": validate_action_chunk(action_rows, action_columns, chunk)["validation_passed"],
        "expected_hashes": len(hashes) == 44,
        "transaction_csv_absent": not transaction_paths["raw"].exists(),
        "replacement_state_absent": not CHUNK_18_REPLACEMENT_STATE.exists(),
        "replacement_payload_absent": not CHUNK_18_REPLACEMENT_PAYLOAD.exists(),
        "query_id_unchanged": original.get("query_id") == AUTHORISED_CHUNK_18_QUERY_ID,
        "failed_execution_preserved": original.get("execution_id") == AUTHORISED_CHUNK_18_EXECUTION_ID,
        "sql_checksum": sql_sha256(sql_text) == AUTHORISED_CHUNK_18_SQL_SHA256,
        "original_timeout_payload_preserved": Path(
            PROJECT_ROOT, original.get("failed_payload_path", "")
        ).exists(),
        "failed_status_recovery_preserved": (
            recovery.get("dune_execution_state") == "FAILED"
            and recovery.get("execution_id") == AUTHORISED_CHUNK_18_EXECUTION_ID
        ),
    }
    failures = [name for name, value in checks.items() if not value]
    return {
        "validation_passed": not failures,
        "failures": failures,
        "checks": checks,
        "action_row_count": len(action_rows),
        "expected_unique_transaction_hash_count": len(hashes),
        "sql_sha256": sql_sha256(sql_text),
        "sql_size_bytes": len(sql_text.encode("utf-8")),
        "query_submission_capability": False,
    }


def initialise_chunk_18_replacement(preflight: dict[str, Any]) -> dict[str, Any]:
    if not preflight.get("validation_passed"):
        raise ProductionAcquisitionError(f"Replacement preflight failed: {preflight['failures']}")
    if CHUNK_18_REPLACEMENT_STATE.exists():
        raise ProductionAcquisitionError("Refusing to overwrite chunk-18 replacement provenance.")
    state = {
        "operation": "one authorised replacement execution of existing query",
        "chunk_id": CHUNKS[17].chunk_id,
        "query_id": AUTHORISED_CHUNK_18_QUERY_ID,
        "previous_failed_execution_id": AUTHORISED_CHUNK_18_EXECUTION_ID,
        "replacement_execution_id": None,
        "sql_sha256": AUTHORISED_CHUNK_18_SQL_SHA256,
        "expected_rows": preflight["expected_unique_transaction_hash_count"],
        "expected_columns": len(TRANSACTION_COLUMNS),
        "engine": "small",
        "execution_submission_count": 0,
        "result_retrieval_count": 0,
        "raw_file_persisted": False,
        "validation_passed": False,
        "preflight": preflight,
        "state": "replacement_planned",
        "created_at_utc": utc_now_iso(),
    }
    write_json_atomic(CHUNK_18_REPLACEMENT_STATE, state)
    return state


def update_chunk_18_replacement(status: str, **fields: Any) -> dict[str, Any]:
    state = json.loads(CHUNK_18_REPLACEMENT_STATE.read_text(encoding="utf-8"))
    state.update(fields)
    state["state"] = status
    state["updated_at_utc"] = utc_now_iso()
    write_json_atomic(CHUNK_18_REPLACEMENT_STATE, state)
    return state


def persist_chunk_18_replacement_response(
    response: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Persist the successful replacement without overwriting failure provenance."""
    if response is None:
        raise ProductionAcquisitionError("Replacement result response is None.")
    payload, rows, columns = _unwrap(response)
    replacement = json.loads(CHUNK_18_REPLACEMENT_STATE.read_text(encoding="utf-8"))
    execution_id = replacement.get("replacement_execution_id")
    if payload.get("executionId") != execution_id:
        raise ProductionAcquisitionError("Replacement response execution ID differs from state.")
    if len(rows) != replacement["expected_rows"] or tuple(columns) != TRANSACTION_COLUMNS:
        raise ProductionAcquisitionError(
            f"Replacement shape is {len(rows)} x {len(columns)}; expected "
            f"{replacement['expected_rows']} x {len(TRANSACTION_COLUMNS)}."
        )
    if CHUNK_18_REPLACEMENT_PAYLOAD.exists():
        raise ProductionAcquisitionError("Refusing to overwrite replacement payload.")
    _write_text_atomic(
        CHUNK_18_REPLACEMENT_PAYLOAD,
        json.dumps(response, indent=2, sort_keys=True) + "\n",
    )
    chunk = CHUNKS[17]
    paths = chunk_paths(chunk, "transaction")
    expected_hashes = {
        row["tx_hash"].lower() for row in read_csv(chunk_paths(chunk, "action")["raw"])[0]
    }
    report = validate_transaction_rows(rows, columns, expected_hashes=expected_hashes)
    if not report["validation_passed"]:
        update_chunk_18_replacement(
            "validation_failed", result_retrieval_count=1,
            failure=report["failures"], raw_file_persisted=False,
        )
        raise ProductionAcquisitionError("; ".join(report["failures"]))
    descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{paths['raw'].name}.", suffix=".partial", dir=paths["raw"].parent,
    )
    os.close(descriptor)
    partial = Path(partial_name)
    with partial.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row["tx_hash"].lower()))
        handle.flush()
        os.fsync(handle.fileno())
    parsed, parsed_columns = read_csv(partial)
    if len(parsed) != len(rows) or parsed_columns != columns or partial.stat().st_size == 0:
        raise ProductionAcquisitionError("Replacement partial CSV structural validation failed.")
    checksum = sha256_file(partial)
    os.replace(partial, paths["raw"])
    _fsync_directory(paths["raw"].parent)
    action_rows, _ = read_csv(chunk_paths(chunk, "action")["raw"])
    transaction_hashes = {row["tx_hash"].lower() for row in parsed}
    joined_count = sum(row["tx_hash"].lower() in transaction_hashes for row in action_rows)
    report.update({
        "chunk_id": chunk.chunk_id,
        "kind": "transaction",
        "raw_file_path": provenance_path(paths["raw"]),
        "raw_file_sha256": checksum,
        "raw_file_size_bytes": paths["raw"].stat().st_size,
        "action_transaction_join": {
            "action_row_count": len(action_rows),
            "joined_row_count": joined_count,
            "join_multiplication_count": joined_count - len(action_rows),
            "all_actions_matched_exactly_once": joined_count == len(action_rows),
        },
    })
    report["validation_passed"] = bool(
        report["validation_passed"] and joined_count == len(action_rows)
    )
    if not report["validation_passed"]:
        raise ProductionAcquisitionError("Replacement action linkage validation failed.")
    write_json_atomic(paths["validation"], report)
    metadata = payload.get("resultMetadata", {})
    replacement = update_chunk_18_replacement(
        "complete", result_retrieval_count=1, raw_file_persisted=True,
        validation_passed=True, row_count=len(parsed), column_count=len(columns),
        raw_file_path=provenance_path(paths["raw"]), raw_file_sha256=checksum,
        raw_file_size_bytes=paths["raw"].stat().st_size,
        compute_credits=float(metadata.get("executionCostCredits") or 0),
        completed_at_utc=utc_now_iso(),
    )
    update_query_state(
        chunk, "transaction", "complete",
        replacement_execution_id=execution_id,
        successful_execution_id=execution_id,
        original_failed_execution_id=AUTHORISED_CHUNK_18_EXECUTION_ID,
        replacement_state_path=provenance_path(CHUNK_18_REPLACEMENT_STATE),
        result_retrieved=True, retrieval_count=1, raw_file_persisted=True,
        validation_passed=True, row_count=len(parsed), column_count=len(columns),
        raw_file_path=provenance_path(paths["raw"]), raw_file_sha256=checksum,
        raw_file_size_bytes=paths["raw"].stat().st_size,
        validation_path=provenance_path(paths["validation"]),
        compute_credits=float(metadata.get("executionCostCredits") or 0),
        completed_at_utc=utc_now_iso(),
    )
    CHUNK_18_REPLACEMENT_PAYLOAD.unlink(missing_ok=True)
    return replacement, report


def chunk_18_completed_result_recovery_preflight() -> dict[str, Any]:
    """Gate one result-only retrieval of the completed replacement execution."""
    chunk = CHUNKS[17]
    action_rows, action_columns = read_csv(chunk_paths(chunk, "action")["raw"])
    expected_hashes = {row["tx_hash"].lower() for row in action_rows}
    replacement = json.loads(CHUNK_18_REPLACEMENT_STATE.read_text(encoding="utf-8"))
    transaction_paths = chunk_paths(chunk, "transaction")
    partials = sorted(CHUNK_ROOT.glob(f".{transaction_paths['raw'].name}.*.partial"))
    checks = {
        "action_rows": len(action_rows) == EXPECTED_CHUNK_18_ACTION_ROWS,
        "action_schema": tuple(action_columns) == ACTION_COLUMNS,
        "action_valid": validate_action_chunk(action_rows, action_columns, chunk)["validation_passed"],
        "expected_hashes": len(expected_hashes) == 44,
        "transaction_csv_absent": not transaction_paths["raw"].exists(),
        "complete_partial_absent": not partials,
        "replacement_payload_absent": not CHUNK_18_REPLACEMENT_PAYLOAD.exists(),
        "recovery_state_absent": not CHUNK_18_COMPLETED_RECOVERY_STATE.exists(),
        "query_id": replacement.get("query_id") == AUTHORISED_CHUNK_18_QUERY_ID,
        "execution_id": (
            replacement.get("replacement_execution_id") == "01KY3HNWXKZR3EN9CRE350HZFZ"
        ),
        "execution_completed": replacement.get("execution_final_state") == "COMPLETED",
        "expected_shape": (
            replacement.get("result_metadata_rows") == 44
            and replacement.get("result_metadata_columns") == len(TRANSACTION_COLUMNS)
        ),
        "sql_checksum": replacement.get("sql_sha256") == AUTHORISED_CHUNK_18_SQL_SHA256,
        "previous_result_not_persisted": not replacement.get("raw_file_persisted"),
    }
    failures = [name for name, value in checks.items() if not value]
    return {
        "validation_passed": not failures,
        "failures": failures,
        "checks": checks,
        "action_row_count": len(action_rows),
        "expected_unique_transaction_hash_count": len(expected_hashes),
        "expected_result_shape": [44, len(TRANSACTION_COLUMNS)],
        "authorised_execution_id": "01KY3HNWXKZR3EN9CRE350HZFZ",
        "result_retrieval_only": True,
        "query_creation_or_execution_capability": False,
        "status_request_required": False,
        "partial_paths": [provenance_path(path) for path in partials],
    }


def initialise_chunk_18_completed_result_recovery(
    preflight: dict[str, Any],
) -> dict[str, Any]:
    if not preflight.get("validation_passed"):
        raise ProductionAcquisitionError(f"Completed-result recovery failed: {preflight['failures']}")
    if CHUNK_18_COMPLETED_RECOVERY_STATE.exists():
        raise ProductionAcquisitionError("Refusing to overwrite completed-result recovery state.")
    state = {
        "operation": "one result-only retrieval of completed replacement execution",
        "query_id": AUTHORISED_CHUNK_18_QUERY_ID,
        "execution_id": "01KY3HNWXKZR3EN9CRE350HZFZ",
        "expected_rows": 44,
        "expected_columns": len(TRANSACTION_COLUMNS),
        "sql_sha256": AUTHORISED_CHUNK_18_SQL_SHA256,
        "result_retrieval_count": 0,
        "status_request_count": 0,
        "query_created": False,
        "query_modified": False,
        "execution_submitted": False,
        "raw_file_persisted": False,
        "validation_passed": False,
        "preflight": preflight,
        "state": "recovery_planned",
        "created_at_utc": utc_now_iso(),
    }
    write_json_atomic(CHUNK_18_COMPLETED_RECOVERY_STATE, state)
    return state


def update_chunk_18_completed_result_recovery(
    status: str, **fields: Any,
) -> dict[str, Any]:
    state = json.loads(CHUNK_18_COMPLETED_RECOVERY_STATE.read_text(encoding="utf-8"))
    state.update(fields)
    state["state"] = status
    state["updated_at_utc"] = utc_now_iso()
    write_json_atomic(CHUNK_18_COMPLETED_RECOVERY_STATE, state)
    return state


def persist_chunk_18_completed_result_recovery(
    response: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pass the authorised result response directly to atomic persistence."""
    if response is None:
        raise ProductionAcquisitionError("Completed-result recovery response is None.")
    try:
        replacement, validation = persist_chunk_18_replacement_response(response)
    except Exception as exc:
        update_chunk_18_completed_result_recovery(
            "persistence_failed", result_retrieval_count=1,
            persistence_error=str(exc), raw_file_persisted=False,
            validation_passed=False,
        )
        raise
    recovery = update_chunk_18_completed_result_recovery(
        "complete", result_retrieval_count=1, raw_file_persisted=True,
        validation_passed=True, raw_file_path=replacement["raw_file_path"],
        raw_file_sha256=replacement["raw_file_sha256"],
        raw_file_size_bytes=replacement["raw_file_size_bytes"],
        row_count=replacement["row_count"], column_count=replacement["column_count"],
        completed_at_utc=utc_now_iso(),
    )
    return recovery, validation


def prepare_action_chunk(chunk_number: int) -> dict[str, Any]:
    chunk = CHUNKS[chunk_number - 1]
    return initialise_query(chunk, "action", render_action_sql(chunk))


def prepare_transaction_chunk(chunk_number: int) -> dict[str, Any]:
    chunk = CHUNKS[chunk_number - 1]
    action_state = json.loads(chunk_paths(chunk, "action")["state"].read_text(encoding="utf-8"))
    if action_state.get("state") != "complete" or not action_state.get("validation_passed"):
        raise ProductionAcquisitionError("Transaction query requires a completed action chunk.")
    action_rows, _ = read_csv(chunk_paths(chunk, "action")["raw"])
    return initialise_query(
        chunk, "transaction",
        build_transaction_sql((row["tx_hash"] for row in action_rows), chunk),
    )


def pending_query() -> dict[str, Any] | None:
    """Return the only safe next query, or None when all chunks are complete."""
    validate_chunk_plan()
    for chunk in CHUNKS:
        action = chunk_paths(chunk, "action")["state"]
        transaction = chunk_paths(chunk, "transaction")["state"]
        if not action.exists():
            return {"chunk": chunk, "kind": "action"}
        action_state = json.loads(action.read_text(encoding="utf-8"))
        if action_state.get("state") != "complete":
            raise ProductionAcquisitionError(f"Stop: {chunk.chunk_id} action is not complete.")
        if not transaction.exists():
            return {"chunk": chunk, "kind": "transaction"}
        transaction_state = json.loads(transaction.read_text(encoding="utf-8"))
        if transaction_state.get("state") != "complete":
            raise ProductionAcquisitionError(f"Stop: {chunk.chunk_id} transaction is not complete.")
    return None


def legacy_sql() -> str:
    """Return one bounded count-only legacy Cat/Flipper check."""
    return """-- Phase 1C bounded legacy liquidation activity check.
SELECT source, contract_address, minimum_block_time, maximum_block_time, activity_count
FROM (
    SELECT
        'maker_ethereum.cat_evt_bite' AS source,
        CONCAT('0x', TO_HEX(contract_address)) AS contract_address,
        MIN(evt_block_time) AS minimum_block_time,
        MAX(evt_block_time) AS maximum_block_time,
        COUNT(*) AS activity_count
    FROM maker_ethereum.cat_evt_bite
    WHERE evt_block_date >= DATE '2021-06-01' AND evt_block_date < DATE '2024-07-01'
      AND evt_block_time >= TIMESTAMP '2021-06-01 00:00:00'
      AND evt_block_time < TIMESTAMP '2024-07-01 00:00:00'
    GROUP BY 1, 2
    UNION ALL
    SELECT
        'maker_ethereum.flipper_evt_kick',
        CONCAT('0x', TO_HEX(contract_address)),
        MIN(evt_block_time), MAX(evt_block_time), COUNT(*)
    FROM maker_ethereum.flipper_evt_kick
    WHERE evt_block_date >= DATE '2021-06-01' AND evt_block_date < DATE '2024-07-01'
      AND evt_block_time >= TIMESTAMP '2021-06-01 00:00:00'
      AND evt_block_time < TIMESTAMP '2024-07-01 00:00:00'
    GROUP BY 1, 2
) legacy
WHERE activity_count > 0
"""


def prepare_legacy_check() -> dict[str, Any]:
    """Initialise the one bounded count-only legacy check."""
    if LEGACY_STATE.exists() or LEGACY_RAW.exists():
        raise ProductionAcquisitionError("Refusing to overwrite legacy-check artefacts.")
    sql = legacy_sql()
    sql_path = SQL_ROOT / "legacy_cat_flipper_check.sql"
    _write_text_atomic(sql_path, sql)
    state = {
        "operation": "bounded count-only Cat/Flipper production-sample check",
        "query_type": "private temporary bounded legacy check",
        "engine": "small",
        "sql_path": provenance_path(sql_path),
        "sql_sha256": sql_sha256(sql),
        "query_id": None, "execution_id": None,
        "result_retrieval_count": 0, "raw_file_persisted": False,
        "validation_passed": False, "state": "planned",
        "created_at_utc": utc_now_iso(),
    }
    write_json_atomic(LEGACY_STATE, state)
    return state


def update_legacy_state(status: str, **fields: Any) -> dict[str, Any]:
    state = json.loads(LEGACY_STATE.read_text(encoding="utf-8"))
    state.update(fields)
    state["state"] = status
    state["updated_at_utc"] = utc_now_iso()
    write_json_atomic(LEGACY_STATE, state)
    return state


def persist_legacy_response(response: dict[str, Any] | None) -> dict[str, Any]:
    """Atomically persist and validate the bounded legacy count result."""
    if response is None:
        raise ProductionAcquisitionError("Legacy result response is None.")
    payload, rows, columns = _unwrap(response)
    expected = (
        "source", "contract_address", "minimum_block_time",
        "maximum_block_time", "activity_count",
    )
    if tuple(columns) != expected:
        raise ProductionAcquisitionError(f"Unexpected legacy schema: {columns}")
    state = json.loads(LEGACY_STATE.read_text(encoding="utf-8"))
    if payload.get("executionId") != state.get("execution_id"):
        raise ProductionAcquisitionError("Legacy response execution differs from state.")
    _write_csv_atomic(
        LEGACY_RAW, list(columns),
        sorted(rows, key=lambda row: (row["source"], row["contract_address"])),
    )
    parsed, parsed_columns = read_csv(LEGACY_RAW)
    if len(parsed) != len(rows) or parsed_columns != columns:
        raise ProductionAcquisitionError("Legacy CSV structural validation failed.")
    activity_count = sum(int(row["activity_count"]) for row in parsed)
    metadata = payload.get("resultMetadata", {})
    return update_legacy_state(
        "complete", result_retrieval_count=1, raw_file_persisted=True,
        validation_passed=True, row_count=len(parsed), column_count=len(columns),
        legacy_activity_count=activity_count,
        legacy_activity_zero=activity_count == 0,
        raw_file_path=provenance_path(LEGACY_RAW),
        raw_file_sha256=sha256_file(LEGACY_RAW),
        raw_file_size_bytes=LEGACY_RAW.stat().st_size,
        compute_credits=float(metadata.get("executionCostCredits") or 0),
        completed_at_utc=utc_now_iso(),
    )


def corrected_legacy_sql() -> str:
    """Return the metadata-verified Cat Bite gate for the six exact ilks."""
    return """-- Phase 1C corrected bounded legacy Cat/Flipper gate.
-- No decoded Flipper Kick table is live. Cat Bite exposes flip and id, which
-- identify the destination Flipper and the auction created by the Bite.
WITH selected_ilks(ilk, ilk_raw) AS (
    VALUES
        ('ETH-A', 0x4554482d41000000000000000000000000000000000000000000000000000000),
        ('ETH-B', 0x4554482d42000000000000000000000000000000000000000000000000000000),
        ('ETH-C', 0x4554482d43000000000000000000000000000000000000000000000000000000),
        ('WBTC-A', 0x574254432d410000000000000000000000000000000000000000000000000000),
        ('WBTC-B', 0x574254432d420000000000000000000000000000000000000000000000000000),
        ('WBTC-C', 0x574254432d430000000000000000000000000000000000000000000000000000)
)
SELECT
    'cat_bite' AS event_type,
    i.ilk,
    DATE_TRUNC('month', b.evt_block_time) AS month_utc,
    CONCAT('0x', TO_HEX(b.contract_address)) AS cat_contract,
    CONCAT('0x', TO_HEX(b.flip)) AS flipper_contract,
    COUNT(*) AS activity_count,
    COUNT(DISTINCT b.evt_tx_hash) AS unique_transaction_count,
    COUNT(DISTINCT b.id) AS unique_auction_count,
    MIN(b.evt_block_time) AS minimum_block_time,
    MAX(b.evt_block_time) AS maximum_block_time
FROM maker_ethereum.cat_evt_bite b
JOIN selected_ilks i ON b.ilk = i.ilk_raw
WHERE b.evt_block_date >= DATE '2021-06-01'
  AND b.evt_block_date < DATE '2024-07-01'
  AND b.evt_block_time >= TIMESTAMP '2021-06-01 00:00:00'
  AND b.evt_block_time < TIMESTAMP '2024-07-01 00:00:00'
GROUP BY 1, 2, 3, 4, 5
"""


def prepare_corrected_legacy_check() -> dict[str, Any]:
    if LEGACY_CORRECTED_STATE.exists() or LEGACY_CORRECTED_RAW.exists():
        raise ProductionAcquisitionError("Refusing to overwrite corrected legacy artefacts.")
    sql = corrected_legacy_sql()
    _write_text_atomic(LEGACY_CORRECTED_SQL, sql)
    state = {
        "operation": "corrected metadata-verified Cat Bite legacy gate",
        "query_type": "private temporary bounded count-only legacy check",
        "engine": "small",
        "sql_path": provenance_path(LEGACY_CORRECTED_SQL),
        "sql_sha256": sql_sha256(sql),
        "query_id": None, "execution_id": None,
        "result_retrieval_count": 0, "raw_file_persisted": False,
        "validation_passed": False, "legacy_gate_passed": False,
        "state": "planned", "created_at_utc": utc_now_iso(),
        "live_table": "maker_ethereum.cat_evt_bite",
        "flipper_table_available": False,
        "flipper_linkage": "Cat Bite flip and id fields",
    }
    write_json_atomic(LEGACY_CORRECTED_STATE, state)
    return state


def update_corrected_legacy_state(status: str, **fields: Any) -> dict[str, Any]:
    state = json.loads(LEGACY_CORRECTED_STATE.read_text(encoding="utf-8"))
    state.update(fields)
    state["state"] = status
    state["updated_at_utc"] = utc_now_iso()
    write_json_atomic(LEGACY_CORRECTED_STATE, state)
    return state


def persist_corrected_legacy_response(response: dict[str, Any] | None) -> dict[str, Any]:
    if response is None:
        raise ProductionAcquisitionError("Corrected legacy result response is None.")
    payload, rows, columns = _unwrap(response)
    expected = (
        "event_type", "ilk", "month_utc", "cat_contract", "flipper_contract",
        "activity_count", "unique_transaction_count", "unique_auction_count",
        "minimum_block_time", "maximum_block_time",
    )
    if tuple(columns) != expected:
        raise ProductionAcquisitionError(f"Unexpected corrected legacy schema: {columns}")
    state = json.loads(LEGACY_CORRECTED_STATE.read_text(encoding="utf-8"))
    if payload.get("executionId") != state.get("execution_id"):
        raise ProductionAcquisitionError("Corrected legacy execution differs from state.")
    unexpected_ilks = sorted({row["ilk"] for row in rows}.difference(EXPECTED_ILKS))
    if unexpected_ilks:
        raise ProductionAcquisitionError(f"Unexpected legacy ilks: {unexpected_ilks}")
    _write_csv_atomic(
        LEGACY_CORRECTED_RAW, list(columns),
        sorted(rows, key=lambda row: (
            row["month_utc"], row["ilk"], row["cat_contract"], row["flipper_contract"],
        )),
    )
    parsed, parsed_columns = read_csv(LEGACY_CORRECTED_RAW)
    if len(parsed) != len(rows) or parsed_columns != columns:
        raise ProductionAcquisitionError("Corrected legacy CSV structural validation failed.")
    activity_count = sum(int(row["activity_count"]) for row in parsed)
    metadata = payload.get("resultMetadata", {})
    return update_corrected_legacy_state(
        "complete", result_retrieval_count=1, raw_file_persisted=True,
        validation_passed=True, legacy_gate_passed=activity_count == 0,
        legacy_activity_count=activity_count,
        result_group_count=len(parsed), row_count=len(parsed), column_count=len(columns),
        raw_file_path=provenance_path(LEGACY_CORRECTED_RAW),
        raw_file_sha256=sha256_file(LEGACY_CORRECTED_RAW),
        raw_file_size_bytes=LEGACY_CORRECTED_RAW.stat().st_size,
        compute_credits=float(metadata.get("executionCostCredits") or 0),
        completed_at_utc=utc_now_iso(),
    )


SCALED_COLUMNS = (
    "ink_wad", "art_wad", "due_dai", "top_dai_per_collateral",
    "tab_dai", "lot_wad", "coin_dai", "price_dai_per_collateral",
    "owe_dai", "remaining_tab_dai", "remaining_lot_wad",
)


def _scaled(value: Any, divisor: Decimal) -> str | None:
    if value in {None, ""}:
        return None
    return format(Decimal(str(value)) / divisor, "f")


def scale_action_row(row: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    scaled = dict(row)
    scaled["chunk_id"] = chunk_id
    for output, source, divisor in (
        ("ink_wad", "ink_raw", WAD), ("art_wad", "art_raw", WAD),
        ("due_dai", "due_raw", RAD), ("top_dai_per_collateral", "top_raw", RAY),
        ("tab_dai", "tab_raw", RAD), ("lot_wad", "lot_raw", WAD),
        ("coin_dai", "coin_raw", RAD),
        ("price_dai_per_collateral", "price_raw", RAY),
        ("owe_dai", "owe_raw", RAD),
        ("remaining_tab_dai", "remaining_tab_raw", RAD),
        ("remaining_lot_wad", "remaining_lot_raw", WAD),
    ):
        scaled[output] = _scaled(row.get(source), divisor)
    return scaled


def _write_csv_atomic(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    temporary = Path(temporary_name)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _require_complete_chunks() -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for chunk in CHUNKS:
        for kind in ("action", "transaction"):
            path = chunk_paths(chunk, kind)["state"]
            if not path.exists():
                raise ProductionAcquisitionError(f"Missing {chunk.chunk_id} {kind} state.")
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("state") != "complete" or not state.get("validation_passed"):
                raise ProductionAcquisitionError(f"Incomplete {chunk.chunk_id} {kind} state.")
            states.append(state)
    return states


def combine_raw_chunks() -> dict[str, Any]:
    states = _require_complete_chunks()
    if any(path.exists() for path in (ACTION_COMBINED, TRANSACTION_COMBINED)):
        raise ProductionAcquisitionError("Refusing to overwrite combined production facts.")
    actions: list[dict[str, Any]] = []
    transactions_by_hash: dict[str, dict[str, Any]] = {}
    transaction_chunks: dict[str, set[str]] = {}
    cross_chunk_duplicates = 0
    for chunk in CHUNKS:
        action_rows, action_columns = read_csv(chunk_paths(chunk, "action")["raw"])
        if tuple(action_columns) != ACTION_COLUMNS:
            raise ProductionAcquisitionError(f"Action schema drift in {chunk.chunk_id}.")
        actions.extend(scale_action_row(row, chunk.chunk_id) for row in action_rows)
        tx_rows, tx_columns = read_csv(chunk_paths(chunk, "transaction")["raw"])
        if tuple(tx_columns) != TRANSACTION_COLUMNS:
            raise ProductionAcquisitionError(f"Transaction schema drift in {chunk.chunk_id}.")
        for row in tx_rows:
            key = row["tx_hash"].lower()
            transaction_chunks.setdefault(key, set()).add(chunk.chunk_id)
            if key in transactions_by_hash:
                comparable = dict(row)
                existing = dict(transactions_by_hash[key])
                existing.pop("chunk_ids", None)
                if comparable != existing:
                    raise ProductionAcquisitionError(f"Conflicting transaction {key} across chunks.")
                cross_chunk_duplicates += 1
            else:
                transactions_by_hash[key] = dict(row)
    action_keys: set[tuple[Any, ...]] = set()
    duplicate_actions = 0
    for row in actions:
        key = (
            row["source_table"], row["record_type"], row["tx_hash"], row["event_index"],
            row["call_trace_address"], row["clipper_contract"], row["auction_id"],
        )
        duplicate_actions += int(key in action_keys)
        action_keys.add(key)
    if duplicate_actions:
        raise ProductionAcquisitionError(f"{duplicate_actions} duplicate action rows across chunks.")
    expected_hashes = {row["tx_hash"].lower() for row in actions}
    observed_hashes = set(transactions_by_hash)
    if expected_hashes != observed_hashes:
        raise ProductionAcquisitionError(
            f"Combined transaction mismatch: A-T={len(expected_hashes-observed_hashes)}, "
            f"T-A={len(observed_hashes-expected_hashes)}."
        )
    action_ordered = sorted(actions, key=lambda row: (
        _parse_utc(row["block_time"]), int(row.get("transaction_index") or 0),
        int(row.get("event_index") or -1), str(row.get("call_trace_address") or ""),
    ))
    transaction_rows: list[dict[str, Any]] = []
    for key in sorted(transactions_by_hash):
        row = transactions_by_hash[key]
        row["chunk_ids"] = ";".join(sorted(transaction_chunks[key]))
        transaction_rows.append(row)
    _write_csv_atomic(
        ACTION_COMBINED, ["chunk_id", *ACTION_COLUMNS, *SCALED_COLUMNS], action_ordered,
    )
    _write_csv_atomic(
        TRANSACTION_COMBINED, ["chunk_ids", *TRANSACTION_COLUMNS], transaction_rows,
    )
    return {
        "query_state_count": len(states),
        "action_row_count": len(action_ordered),
        "transaction_row_count": len(transaction_rows),
        "cross_chunk_identical_transaction_duplicate_count": cross_chunk_duplicates,
        "action_sha256": sha256_file(ACTION_COMBINED),
        "transaction_sha256": sha256_file(TRANSACTION_COMBINED),
    }


def validate_existing_combined_facts() -> dict[str, Any]:
    """Validate deterministic combined facts after an interrupted finalisation."""
    if not ACTION_COMBINED.exists() or not TRANSACTION_COMBINED.exists():
        raise ProductionAcquisitionError("Both combined facts are required for recovery.")
    actions, action_columns = read_csv(ACTION_COMBINED)
    transactions, transaction_columns = read_csv(TRANSACTION_COMBINED)
    if tuple(action_columns) != ("chunk_id", *ACTION_COLUMNS, *SCALED_COLUMNS):
        raise ProductionAcquisitionError("Existing combined action schema is invalid.")
    if tuple(transaction_columns) != ("chunk_ids", *TRANSACTION_COLUMNS):
        raise ProductionAcquisitionError("Existing combined transaction schema is invalid.")
    action_keys = [(
        row["source_table"], row["record_type"], row["tx_hash"], row["event_index"],
        row["call_trace_address"], row["clipper_contract"], row["auction_id"],
    ) for row in actions]
    if len(action_keys) != len(set(action_keys)):
        raise ProductionAcquisitionError("Existing combined actions contain duplicates.")
    transaction_hashes = [row["tx_hash"].lower() for row in transactions]
    if len(transaction_hashes) != len(set(transaction_hashes)):
        raise ProductionAcquisitionError("Existing combined transactions contain duplicates.")
    action_hashes = {row["tx_hash"].lower() for row in actions}
    if action_hashes != set(transaction_hashes):
        raise ProductionAcquisitionError("Existing combined action/transaction linkage is incomplete.")
    chunk_transaction_rows = sum(
        len(read_csv(chunk_paths(chunk, "transaction")["raw"])[0]) for chunk in CHUNKS
    )
    return {
        "query_state_count": len(_require_complete_chunks()),
        "action_row_count": len(actions),
        "transaction_row_count": len(transactions),
        "cross_chunk_identical_transaction_duplicate_count": (
            chunk_transaction_rows - len(transactions)
        ),
        "action_sha256": sha256_file(ACTION_COMBINED),
        "transaction_sha256": sha256_file(TRANSACTION_COMBINED),
        "recovered_after_interrupted_metadata_serialisation": True,
    }


def _dec(row: dict[str, Any], column: str, divisor: Decimal | None = None) -> Decimal:
    value = row.get(column)
    if value in {None, ""}:
        return Decimal(0)
    parsed = Decimal(str(value))
    return parsed / divisor if divisor else parsed


def build_auction_summary(
    actions: list[dict[str, Any]], transactions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tx_by_hash = {row["tx_hash"].lower(): row for row in transactions}
    semantic: dict[str, list[dict[str, Any]]] = {}
    auction_actions: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in actions:
        auction_actions.setdefault(auction_key(row), []).append(row)
        if row["record_type"].endswith("_event") or row["record_type"].endswith("_failed"):
            semantic.setdefault(row["tx_hash"].lower(), []).append(row)
    terminal = classify_terminals(actions)
    take_classes = classify_successful_take_transactions(actions)
    output: list[dict[str, Any]] = []
    ambiguous_count = 0
    for key in sorted(auction_actions):
        rows = sorted(auction_actions[key], key=lambda row: (
            _parse_utc(row["block_time"]), int(row.get("transaction_index") or 0),
            int(row.get("event_index") or -1), str(row.get("call_trace_address") or ""),
        ))
        bark = next(row for row in rows if row["record_type"] == "bark_event")
        kicks = [row for row in rows if row["record_type"] == "kick_event"]
        takes = [row for row in rows if row["record_type"] == "take_event"]
        failed = [row for row in rows if row["record_type"] == "take_call_failed"]
        redos = [row for row in rows if row["record_type"] == "redo_event"]
        yanks = [row for row in rows if row["record_type"] == "yank_event"]
        tx_hashes = {row["tx_hash"].lower() for row in rows}
        unique_tx_hashes = {
            value for value in tx_hashes
            if len({auction_key(action) for action in semantic.get(value, [])}) == 1
        }
        shared_hashes = tx_hashes.difference(unique_tx_hashes)
        ambiguous = len(kicks) != 1 or any(
            details["ambiguous_keys"] for details in reconcile_event_calls(rows).values()
        )
        ambiguous_count += int(ambiguous)
        final_take = takes[-1] if takes else None
        first_time = _parse_utc(bark["block_time"])
        final_time = max(_parse_utc(row["block_time"]) for row in rows)
        initial_lot = _dec(kicks[0], "lot_raw", WAD) if kicks else Decimal(0)
        remaining_lot = _dec(final_take, "remaining_lot_raw", WAD) if final_take else initial_lot
        remaining_tab = _dec(final_take, "remaining_tab_raw", RAD) if final_take else (
            _dec(kicks[0], "tab_raw", RAD) if kicks else Decimal(0)
        )
        output.append({
            "chunk_id": bark["chunk_id"], "clipper_contract": key[0],
            "auction_id": key[1], "ilk": bark["ilk"], "urn": bark["urn"],
            "bark_tx_hash": bark["tx_hash"], "bark_time_utc": bark["block_time"],
            "kick_count": len(kicks), "take_count": len(takes),
            "failed_take_attempt_count": len(failed), "redo_count": len(redos),
            "yank_count": len(yanks), "first_action_time_utc": first_time.isoformat(),
            "final_action_time_utc": final_time.isoformat(),
            "observed_duration_seconds": (final_time - first_time).total_seconds(),
            "bark_ink_wad": str(_dec(bark, "ink_raw", WAD)),
            "bark_art_wad": str(_dec(bark, "art_raw", WAD)),
            "bark_due_dai": str(_dec(bark, "due_raw", RAD)),
            "kick_top_dai_per_collateral": str(_dec(kicks[0], "top_raw", RAY)) if kicks else None,
            "kick_tab_dai": str(_dec(kicks[0], "tab_raw", RAD)) if kicks else None,
            "kick_lot_wad": str(initial_lot) if kicks else None,
            "collateral_sold_wad": str(initial_lot - remaining_lot),
            "dai_paid": str(sum((_dec(row, "owe_raw", RAD) for row in takes), Decimal(0))),
            "remaining_lot_wad": str(remaining_lot), "remaining_tab_dai": str(remaining_tab),
            "keeper_incentives_dai": str(sum((_dec(row, "coin_raw", RAD) for row in kicks + redos), Decimal(0))),
            "terminal_classification": terminal[key],
            "unique_transaction_count": len(tx_hashes),
            "gas_used_unique_to_auction": sum(int(tx_by_hash[value]["gas_used"]) for value in unique_tx_hashes),
            "shared_multi_auction_transaction_count": len(shared_hashes),
            "gas_attribution_ambiguous": bool(shared_hashes),
            "event_call_ambiguity": ambiguous,
            "successful_take_classes": ";".join(sorted({take_classes[row["tx_hash"].lower()] for row in takes})),
        })
    return output, {
        "auction_count": len(output),
        "ambiguous_auction_count": ambiguous_count,
        "terminal_classifications": {
            str(key): int(value) for key, value in
            pd.Series([row["terminal_classification"] for row in output]).value_counts().items()
        },
    }


def build_hourly_panel(
    actions: list[dict[str, Any]], transactions: list[dict[str, Any]],
    auctions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    market = pd.read_csv(MARKET_PANEL, usecols=["timestamp_utc", "eth_price_usd"])
    gas = pd.read_csv(GAS_PANEL, usecols=[
        "timestamp_utc", "median_effective_gas_price_gwei",
        "p90_effective_gas_price_gwei", "p99_effective_gas_price_gwei",
    ])
    market["timestamp_utc"] = pd.to_datetime(market["timestamp_utc"], utc=True)
    gas["timestamp_utc"] = pd.to_datetime(gas["timestamp_utc"], utc=True)
    hourly_inputs = market.merge(gas, on="timestamp_utc", how="inner", validate="one_to_one")
    if len(hourly_inputs) != 27_024:
        raise ProductionAcquisitionError("Phase 1A/1B hourly inputs are incomplete.")
    price_by_hour = hourly_inputs.set_index("timestamp_utc").to_dict("index")
    auction_by_key = {(row["clipper_contract"], row["auction_id"]): row for row in auctions}
    tx_by_hash = {row["tx_hash"].lower(): row for row in transactions}
    semantic = _semantic_by_tx(actions)
    aggregates: dict[tuple[pd.Timestamp, str], dict[str, Any]] = {}

    def bucket(hour: pd.Timestamp, ilk: str) -> dict[str, Any]:
        return aggregates.setdefault((hour, ilk), {
            "auctions_initiated": 0, "auctions_completed": 0,
            "collateral_liquidated_wad": Decimal(0), "debt_targeted_dai": Decimal(0),
            "debt_repaid_dai": Decimal(0), "successful_takes": 0,
            "failed_take_attempts": 0, "redos": 0, "yanks": 0,
            "keepers": set(), "transaction_hashes": set(),
            "shared_multi_ilk_transaction_hashes": set(), "unresolved_auctions": 0,
            "bad_debt_proxy_dai": Decimal(0),
        })

    for row in actions:
        if not (row["record_type"].endswith("_event") or row["record_type"].endswith("_failed")):
            continue
        hour = pd.Timestamp(_parse_utc(row["block_time"])).floor("h")
        item = bucket(hour, row["ilk"])
        tx_hash = row["tx_hash"].lower()
        tx_ilks = {action["ilk"] for action in semantic[tx_hash]}
        if len(tx_ilks) == 1:
            item["transaction_hashes"].add(tx_hash)
        else:
            item["shared_multi_ilk_transaction_hashes"].add(tx_hash)
        if row["record_type"] == "bark_event":
            item["auctions_initiated"] += 1
            item["debt_targeted_dai"] += _dec(row, "due_raw", RAD)
        elif row["record_type"] == "take_event":
            item["successful_takes"] += 1
            item["debt_repaid_dai"] += _dec(row, "owe_raw", RAD)
        elif row["record_type"] == "take_call_failed":
            item["failed_take_attempts"] += 1
        elif row["record_type"] == "redo_event":
            item["redos"] += 1
        elif row["record_type"] == "yank_event":
            item["yanks"] += 1
        if row.get("who"):
            item["keepers"].add(row["who"].lower())

    for row in auctions:
        start_hour = pd.Timestamp(_parse_utc(row["bark_time_utc"])).floor("h")
        start_item = bucket(start_hour, row["ilk"])
        start_item["collateral_liquidated_wad"] += Decimal(row["collateral_sold_wad"])
        if row["terminal_classification"] == "open_or_unresolved":
            start_item["unresolved_auctions"] += 1
        else:
            completion_hour = pd.Timestamp(_parse_utc(row["final_action_time_utc"])).floor("h")
            bucket(completion_hour, row["ilk"])["auctions_completed"] += 1
        if row["terminal_classification"] == "collateral_exhausted":
            start_item["bad_debt_proxy_dai"] += Decimal(row["remaining_tab_dai"])

    output: list[dict[str, Any]] = []
    for timestamp in pd.date_range(FULL_START, FULL_END, freq="h", inclusive="left"):
        environment = price_by_hour[timestamp]
        for ilk in EXPECTED_ILKS:
            item = bucket(timestamp, ilk)
            tx_rows = [tx_by_hash[value] for value in sorted(item["transaction_hashes"])]
            prices = sorted(float(row["gas_price"]) / 1e9 for row in tx_rows)
            gas_used = sum(int(row["gas_used"]) for row in tx_rows)
            cost_eth = sum(int(row["gas_used"]) * int(row["gas_price"]) * 1e-18 for row in tx_rows)
            output.append({
                "timestamp_utc": timestamp.isoformat(), "ilk": ilk,
                "auctions_initiated": item["auctions_initiated"],
                "auctions_completed": item["auctions_completed"],
                "collateral_liquidated_wad": str(item["collateral_liquidated_wad"]),
                "debt_targeted_dai": str(item["debt_targeted_dai"]),
                "debt_repaid_dai": str(item["debt_repaid_dai"]),
                "successful_takes": item["successful_takes"],
                "failed_take_attempts": item["failed_take_attempts"],
                "redos": item["redos"], "yanks": item["yanks"],
                "unique_keepers": len(item["keepers"]),
                "unique_transactions_with_unambiguous_ilk": len(tx_rows),
                "shared_multi_ilk_transaction_count_unallocated": len(item["shared_multi_ilk_transaction_hashes"]),
                "gas_used_unambiguous": gas_used,
                "gas_cost_eth_unambiguous": cost_eth,
                "gas_cost_usd_unambiguous": cost_eth * environment["eth_price_usd"],
                "median_transaction_gas_price_gwei": pd.Series(prices).median() if prices else None,
                "p90_transaction_gas_price_gwei": pd.Series(prices).quantile(.90) if prices else None,
                "p99_transaction_gas_price_gwei": pd.Series(prices).quantile(.99) if prices else None,
                "unresolved_auctions": item["unresolved_auctions"],
                "bad_debt_proxy_dai": str(item["bad_debt_proxy_dai"]),
                "eth_price_usd": environment["eth_price_usd"],
                "hourly_median_effective_gas_price_gwei": environment["median_effective_gas_price_gwei"],
                "hourly_p90_effective_gas_price_gwei": environment["p90_effective_gas_price_gwei"],
                "hourly_p99_effective_gas_price_gwei": environment["p99_effective_gas_price_gwei"],
            })
    return output, {
        "row_count": len(output), "expected_row_count": 27_024 * 6,
        "phase1a_phase1b_joined_hour_count": len(hourly_inputs),
        "missing_phase1a_phase1b_hours": 27_024 - len(hourly_inputs),
    }


def _semantic_by_tx(actions: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for row in actions:
        if row["record_type"].endswith("_event") or row["record_type"].endswith("_failed"):
            output.setdefault(row["tx_hash"].lower(), []).append(row)
    return output


def finalise_production() -> dict[str, Any]:
    legacy = json.loads(LEGACY_CORRECTED_STATE.read_text(encoding="utf-8"))
    if not (
        legacy.get("state") == "complete"
        and legacy.get("validation_passed")
        and legacy.get("legacy_gate_passed")
        and legacy.get("legacy_activity_count") == 0
    ):
        raise ProductionAcquisitionError("The corrected zero-activity legacy gate has not passed.")
    combined = (
        validate_existing_combined_facts()
        if ACTION_COMBINED.exists() or TRANSACTION_COMBINED.exists()
        else combine_raw_chunks()
    )
    actions, action_columns = read_csv(ACTION_COMBINED)
    transactions, transaction_columns = read_csv(TRANSACTION_COMBINED)
    transaction_report = validate_transaction_rows(
        transactions,
        transaction_columns[1:],
        expected_hashes={row["tx_hash"].lower() for row in actions},
    )
    # The validator receives only canonical transaction fields; chunk_ids is provenance.
    if not transaction_report["validation_passed"]:
        raise ProductionAcquisitionError(str(transaction_report["failures"]))
    auctions, auction_report = build_auction_summary(actions, transactions)
    hourly, hourly_report = build_hourly_panel(actions, transactions, auctions)
    if hourly_report["row_count"] != hourly_report["expected_row_count"]:
        raise ProductionAcquisitionError("Hourly production panel is incomplete.")
    _write_csv_atomic(AUCTION_SUMMARY, list(auctions[0]) if auctions else [], auctions)
    _write_csv_atomic(HOURLY_PANEL, list(hourly[0]) if hourly else [], hourly)
    record_counts = {
        str(key): int(value) for key, value in
        pd.Series([row["record_type"] for row in actions]).value_counts().items()
    }
    ilk_counts = {
        str(key): int(value) for key, value in
        pd.Series([row["ilk"] for row in actions if row["record_type"] == "bark_event"]).value_counts().items()
    }
    take_classes = classify_successful_take_transactions(actions)
    class_counts = {
        str(key): int(value) for key, value in
        pd.Series(list(take_classes.values())).value_counts().items()
    }
    transaction_cost_eth = [
        int(row["gas_used"]) * int(row["gas_price"]) * 1e-18 for row in transactions
    ]
    zero_cost_count = sum(value == 0 for value in transaction_cost_eth)
    near_zero_cost_count = sum(0 < value <= 1e-8 for value in transaction_cost_eth)
    reconciliation = reconcile_event_calls(actions)
    validation = {
        "validation_passed": True,
        "combined": combined,
        "transaction_bridge": transaction_report,
        "auction_summary": auction_report,
        "hourly_panel": hourly_report,
        "record_counts": record_counts,
        "bark_counts_by_ilk": ilk_counts,
        "successful_take_transaction_classes": class_counts,
        "event_call_reconciliation": reconciliation,
        "redo_event_count": record_counts.get("redo_event", 0),
        "yank_event_count": record_counts.get("yank_event", 0),
        "gas_cost_review": {
            "definition": "unique transaction gas_used * gas_price * 1e-18 ETH",
            "zero_cost_transaction_count": zero_cost_count,
            "near_zero_positive_cost_transaction_count_le_1e_8_eth": near_zero_cost_count,
            "requires_review": bool(zero_cost_count or near_zero_cost_count),
        },
        "legacy_gate": {
            "activity_count": 0,
            "state_path": provenance_path(LEGACY_CORRECTED_STATE),
            "raw_path": provenance_path(LEGACY_CORRECTED_RAW),
            "raw_sha256": sha256_file(LEGACY_CORRECTED_RAW),
        },
        "output_files": {
            provenance_path(path): {
                "size_bytes": path.stat().st_size, "sha256": sha256_file(path),
            } for path in (ACTION_COMBINED, TRANSACTION_COMBINED, AUCTION_SUMMARY, HOURLY_PANEL)
        },
    }
    write_json_atomic(FINAL_VALIDATION, validation)
    metadata = {
        "phase": "1C",
        "created_at_utc": utc_now_iso(),
        "coverage_start_utc": FULL_START.isoformat(),
        "coverage_end_exclusive_utc": FULL_END.isoformat(),
        "exact_ilks": list(EXPECTED_ILKS),
        "auction_key": ["clipper_contract", "auction_id"],
        "chunk_count": len(CHUNKS),
        "input_manifest_path": provenance_path(MANIFEST),
        "legacy_gate_state_path": provenance_path(LEGACY_CORRECTED_STATE),
        "dimensions": {
            "actions": combined["action_row_count"],
            "transactions": combined["transaction_row_count"],
            "auctions": auction_report["auction_count"],
            "hourly_ilk_rows": hourly_report["row_count"],
        },
        "output_files": validation["output_files"],
        "validation_path": provenance_path(FINAL_VALIDATION),
    }
    write_json_atomic(FINAL_METADATA, metadata)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest.update({
        "status": "complete", "completed_at_utc": utc_now_iso(),
        "combined_outputs": validation["output_files"],
        "final_validation_path": provenance_path(FINAL_VALIDATION),
        "final_validation_sha256": sha256_file(FINAL_VALIDATION),
        "final_metadata_path": provenance_path(FINAL_METADATA),
        "final_metadata_sha256": sha256_file(FINAL_METADATA),
        "legacy_gate_passed": True,
        "legacy_activity_count": 0,
    })
    write_json_atomic(MANIFEST, manifest)
    return validation
