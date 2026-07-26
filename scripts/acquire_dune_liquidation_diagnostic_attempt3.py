"""Low-complexity Phase 1C diagnostic persistence and local reconciliation.

Dune supplies two immutable raw facts: Maker action/call rows and one unique
transaction bridge.  All matching, scaling, lifecycle and gas diagnostics are
performed locally.  The module has no network, credential or stdin path.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import median
import tempfile
from typing import Any, Callable, Iterable

from scripts.acquire_dune_liquidation_diagnostic import (
    EXPECTED_ILKS,
    RAD,
    RAY,
    WAD,
    LiquidationDiagnosticError,
    _extract_cte_body,
    _select_expression_count,
    _split_top_level,
    decimal_value,
    provenance_path,
    sha256_file,
    utc_now_iso,
    write_json_atomic,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACTION_SQL = PROJECT_ROOT / "sql" / "dune_phase1c_liquidation_actions_diagnostic.sql"
DIAGNOSTIC_DIR = (
    PROJECT_ROOT / "data" / "provenance" / "liquidations" / "archive" / "diagnostic"
)
ACTION_RAW = DIAGNOSTIC_DIR / "phase1c_liquidation_actions_attempt3.csv"
TRANSACTION_RAW = DIAGNOSTIC_DIR / "phase1c_liquidation_transactions_attempt3.csv"
ACTION_STATE = DIAGNOSTIC_DIR / "phase1c_liquidation_actions_attempt3_state.json"
TRANSACTION_STATE = DIAGNOSTIC_DIR / "phase1c_liquidation_transactions_attempt3_state.json"
ACTION_PAYLOAD = DIAGNOSTIC_DIR / ".phase1c_liquidation_actions_attempt3.partial.json"
TRANSACTION_PAYLOAD = DIAGNOSTIC_DIR / ".phase1c_liquidation_transactions_attempt3.partial.json"
TRANSACTION_SQL = (
    PROJECT_ROOT
    / "sql"
    / "liquidations"
    / "generated"
    / "phase1c_liquidation_transactions_attempt3.sql"
)
ATTEMPT_METADATA = DIAGNOSTIC_DIR / "phase1c_liquidation_attempt3_metadata.json"
ATTEMPT_VALIDATION = DIAGNOSTIC_DIR / "phase1c_liquidation_attempt3_validation.json"
TRANSACTION_RECOVERY_STATE = (
    DIAGNOSTIC_DIR / "phase1c_liquidation_transactions_attempt3_recovery_state.json"
)
TRANSACTION_RECOVERY_PAYLOAD = (
    DIAGNOSTIC_DIR / ".phase1c_liquidation_transactions_attempt3_recovery.partial.json"
)
RECOVERY_METADATA = DIAGNOSTIC_DIR / "phase1c_liquidation_attempt3_recovery_metadata.json"
RECOVERY_VALIDATION = DIAGNOSTIC_DIR / "phase1c_liquidation_attempt3_recovery_validation.json"
RECOVERY_SUMMARY = DIAGNOSTIC_DIR / "phase1c_liquidation_attempt3_summary.json"
MARKET_PANEL = (
    PROJECT_ROOT / "data" / "processed" / "market"
    / "dune_hourly_market_prices_processed.csv"
)
GAS_PANEL = (
    PROJECT_ROOT / "data" / "processed" / "gas"
    / "dune_ethereum_hourly_gas_processed.csv"
)

AUTHORISED_RECOVERY_QUERY_ID = 8060494
AUTHORISED_RECOVERY_EXECUTION_ID = "01KY3CY8JG1H3XJN36T8JTK43J"
AUTHORISED_TRANSACTION_SQL_SHA256 = (
    "13c33f7abed316c9afa1fb45aa9c2f0e443ebadea6daf6de2db96e744364ab55"
)
EXPECTED_TRANSACTION_ROWS = 368
EXPECTED_TRANSACTION_COLUMNS = 14

ACTION_COLUMNS = (
    "initiation_window_label", "action_in_principal_window",
    "action_in_bounded_horizon", "source_table", "record_type",
    "dog_contract", "clipper_contract", "auction_id", "ilk", "urn",
    "tx_hash", "block_time", "block_number", "transaction_index",
    "event_index", "call_trace_address", "call_success", "event_sender",
    "call_sender", "call_recipient", "usr", "who", "kpr", "ink_raw",
    "art_raw", "due_raw", "top_raw", "tab_raw", "lot_raw", "coin_raw",
    "price_raw", "owe_raw", "remaining_tab_raw", "remaining_lot_raw",
    "max_raw", "amt_raw",
)
RECORD_TYPES = {
    "bark_event", "bark_call", "kick_event", "kick_call", "take_event",
    "take_call_success", "take_call_failed", "redo_event",
    "redo_call_success", "redo_call_failed", "yank_event",
}
TRANSACTION_COLUMNS = (
    "tx_hash", "transaction_sender", "transaction_recipient", "success",
    "gas_limit", "gas_used", "gas_price", "max_fee_per_gas",
    "max_priority_fee_per_gas", "priority_fee_per_gas", "block_time",
    "block_number", "block_date", "transaction_index",
)


def _truth(value: Any) -> bool:
    return str(value).lower() in {"true", "1"}


def auction_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row["clipper_contract"]).lower(), str(row["auction_id"]))


def action_order(row: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        int(row.get("block_number") or 0),
        int(row.get("transaction_index") or 0),
        int(row.get("event_index") or -1),
        str(row.get("call_trace_address") or ""),
    )


def validate_shallow_action_sql(sql: str) -> dict[str, Any]:
    failures: list[str] = []
    lower = sql.lower()
    for fragment in ("exists (", "ethereum.transactions", "group by", " over ("):
        if fragment in lower:
            failures.append(f"forbidden planner-heavy fragment: {fragment.strip()}")
    for ilk in EXPECTED_ILKS:
        if sql.count(f"'{ilk}'") != 1:
            failures.append(f"ilk {ilk} must appear exactly once")
    for bound in (
        "2023-02-01 00:00:00", "2023-02-03 00:00:00",
        "2023-02-10 00:00:00", "2022-06-13 00:00:00",
        "2022-06-15 00:00:00", "2022-06-22 00:00:00",
    ):
        if bound not in sql:
            failures.append(f"missing bound {bound}")
    topic = "0x2c5d2826eb5903b8fc201cf48094b858f42f61c7eaac9aaf43ebed490138144e"
    if sql.lower().count(topic) != 1:
        failures.append("Yank topic must appear exactly once")
    try:
        body = _extract_cte_body(sql, "raw_actions")
        branches = _split_top_level(body, "UNION ALL")
        counts = [_select_expression_count(branch) for branch in branches]
        if len(branches) != 9 or len(set(counts)) != 1:
            failures.append(f"unaligned action branches: {counts}")
    except LiquidationDiagnosticError as exc:
        branches, counts = [], []
        failures.append(str(exc))
    if lower.count("from raw_actions") != 1:
        failures.append("raw_actions must be referenced only by the final projection")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "cte_names": ["windows", "selected_ilks", "barks", "auction_universe", "raw_actions"],
        "union_branch_count": len(branches),
        "union_column_counts": counts,
        "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
    }


def initialise_query_state(path: Path, query_kind: str, sql_path: Path) -> dict[str, Any]:
    if path.exists():
        raise LiquidationDiagnosticError(f"Refusing to overwrite state: {path}.")
    sql = sql_path.read_text(encoding="utf-8")
    if query_kind == "actions":
        report = validate_shallow_action_sql(sql)
        if not report["validation_passed"]:
            raise LiquidationDiagnosticError("; ".join(report["failures"]))
    state = {
        "attempt": 3,
        "query_kind": query_kind,
        "query_type": "private temporary diagnostic",
        "engine": "small",
        "sql_path": provenance_path(sql_path),
        "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
        "state": "planned",
        "query_id": None,
        "execution_id": None,
        "result_retrieved": False,
        "retrieval_count": 0,
        "raw_file_persisted": False,
        "validation_passed": False,
        "created_at_utc": utc_now_iso(),
    }
    write_json_atomic(path, state)
    return state


def update_state(path: Path, status: str, **fields: Any) -> dict[str, Any]:
    state = json.loads(path.read_text(encoding="utf-8"))
    state.update(fields)
    state["state"] = status
    state["updated_at_utc"] = utc_now_iso()
    write_json_atomic(path, state)
    return state


def _fsync_directory(path: Path) -> None:
    """Fsync a containing directory where the platform permits it."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def require_action_complete_for_transaction(state_path: Path) -> dict[str, Any]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not (
        state.get("state") == "complete"
        and state.get("validation_passed")
        and state.get("raw_file_persisted")
    ):
        raise LiquidationDiagnosticError("Query 2 is forbidden unless Query 1 is complete and validated.")
    return state


def require_no_failed_transaction_attempt(state_path: Path) -> None:
    if not state_path.exists():
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("state") == "failed":
        raise LiquidationDiagnosticError("No further query is authorised after Query 2 failure.")


def _unwrap(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    if isinstance(payload.get("structuredContent"), dict):
        payload = payload["structuredContent"]
    if payload.get("state") != "COMPLETED":
        raise LiquidationDiagnosticError(f"Execution is not complete: {payload.get('state')!r}.")
    metadata = payload.get("resultMetadata", {})
    rows = payload.get("data", {}).get("rows")
    columns = [item["name"] for item in metadata.get("columns", [])]
    if not isinstance(rows, list) or not columns:
        raise LiquidationDiagnosticError("Completed payload lacks rows or columns.")
    if metadata.get("totalRowCount") != len(rows):
        raise LiquidationDiagnosticError("Result metadata and row count differ.")
    return payload, rows, columns


def persist_result(
    *, payload_path: Path, state_path: Path, raw_path: Path,
    validator: Callable[[list[dict[str, Any]], list[str]], dict[str, Any]],
    row_sort_key: Callable[[dict[str, Any]], Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fsync, validate and atomically promote one retrieved result."""
    state = json.loads(state_path.read_text(encoding="utf-8"))
    payload, rows, columns = _unwrap(json.loads(payload_path.read_text(encoding="utf-8")))
    if str(payload.get("executionId")) != str(state.get("execution_id")):
        raise LiquidationDiagnosticError("Payload execution differs from durable state.")
    if row_sort_key is not None:
        rows = sorted(rows, key=row_sort_key)
    update_state(
        state_path, "result_retrieved", result_retrieved=True, retrieval_count=1,
        result_retrieved_at_utc=utc_now_iso(),
        compute_credits=payload.get("resultMetadata", {}).get("executionCostCredits"),
    )
    if raw_path.exists():
        raise LiquidationDiagnosticError("Refusing to overwrite raw output.")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{raw_path.name}.", suffix=".partial", dir=raw_path.parent,
    )
    os.close(descriptor)
    partial = Path(partial_name)
    with partial.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    with partial.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        parsed = list(reader)
        if list(reader.fieldnames or []) != columns:
            raise LiquidationDiagnosticError("Persisted header differs from result metadata.")
    if len(parsed) != len(rows) or partial.stat().st_size == 0:
        raise LiquidationDiagnosticError("Partial CSV structural check failed.")
    report = validator(parsed, columns)
    if not report["validation_passed"]:
        raise LiquidationDiagnosticError("; ".join(report["failures"]))
    checksum = sha256_file(partial)
    os.replace(partial, raw_path)
    _fsync_directory(raw_path.parent)
    state = update_state(
        state_path, "complete", raw_file_persisted=True, validation_passed=True,
        raw_file_path=provenance_path(raw_path), raw_file_size_bytes=raw_path.stat().st_size,
        raw_file_sha256=checksum, row_count=len(parsed), column_count=len(columns),
        completed_at_utc=utc_now_iso(),
    )
    payload_path.unlink(missing_ok=True)
    return state, report


def initialise_transaction_recovery_state(path: Path) -> dict[str, Any]:
    """Create immutable recovery provenance without altering the stopped state."""
    if path.exists():
        raise LiquidationDiagnosticError(f"Refusing to overwrite recovery state: {path}.")
    stopped = json.loads(TRANSACTION_STATE.read_text(encoding="utf-8"))
    expected = {
        "query_id": AUTHORISED_RECOVERY_QUERY_ID,
        "execution_id": AUTHORISED_RECOVERY_EXECUTION_ID,
        "sql_sha256": AUTHORISED_TRANSACTION_SQL_SHA256,
        "result_row_count": EXPECTED_TRANSACTION_ROWS,
        "result_column_count": EXPECTED_TRANSACTION_COLUMNS,
        "execution_state": "COMPLETED",
        "state": "failed",
    }
    mismatches = {
        key: {"expected": value, "observed": stopped.get(key)}
        for key, value in expected.items() if stopped.get(key) != value
    }
    if mismatches:
        raise LiquidationDiagnosticError(f"Stopped-state mismatch: {mismatches}")
    state = {
        "operation": "result-only persistence recovery",
        "attempt": 3,
        "query_id": AUTHORISED_RECOVERY_QUERY_ID,
        "execution_id": AUTHORISED_RECOVERY_EXECUTION_ID,
        "sql_sha256": AUTHORISED_TRANSACTION_SQL_SHA256,
        "expected_rows": EXPECTED_TRANSACTION_ROWS,
        "expected_columns": EXPECTED_TRANSACTION_COLUMNS,
        "original_retrieval_count": 1,
        "recovery_retrieval_count": 0,
        "query_created": False,
        "execution_submitted": False,
        "raw_file_persisted": False,
        "validation_passed": False,
        "state": "recovery_planned",
        "created_at_utc": utc_now_iso(),
        "stopped_state_path": provenance_path(TRANSACTION_STATE),
        "stopped_state_sha256": sha256_file(TRANSACTION_STATE),
    }
    write_json_atomic(path, state)
    return state


def recovery_preflight() -> dict[str, Any]:
    """Validate that exactly the authorised completed execution can be recovered."""
    failures: list[str] = []
    stopped = json.loads(TRANSACTION_STATE.read_text(encoding="utf-8"))
    checks = {
        "authorised_execution_only": stopped.get("execution_id") == AUTHORISED_RECOVERY_EXECUTION_ID,
        "authorised_query_only": stopped.get("query_id") == AUTHORISED_RECOVERY_QUERY_ID,
        "sql_checksum": stopped.get("sql_sha256") == AUTHORISED_TRANSACTION_SQL_SHA256,
        "local_sql_checksum": (
            TRANSACTION_SQL.exists()
            and sha256_file(TRANSACTION_SQL) == AUTHORISED_TRANSACTION_SQL_SHA256
        ),
        "expected_rows": stopped.get("result_row_count") == EXPECTED_TRANSACTION_ROWS,
        "expected_columns": stopped.get("result_column_count") == EXPECTED_TRANSACTION_COLUMNS,
        "completed_execution": stopped.get("execution_state") == "COMPLETED",
        "final_csv_absent": not TRANSACTION_RAW.exists(),
        "recovery_payload_absent": not TRANSACTION_RECOVERY_PAYLOAD.exists(),
        "action_file_present": ACTION_RAW.exists(),
        "market_panel_present": MARKET_PANEL.exists(),
        "gas_panel_present": GAS_PANEL.exists(),
    }
    stale_partials = sorted(TRANSACTION_RAW.parent.glob(f".{TRANSACTION_RAW.name}.*.partial"))
    checks["complete_partial_absent"] = not stale_partials
    action_hashes: set[str] = set()
    if ACTION_RAW.exists():
        with ACTION_RAW.open("r", encoding="utf-8", newline="") as handle:
            action_hashes = {
                str(row["tx_hash"]).lower() for row in csv.DictReader(handle)
            }
    checks["expected_action_hash_count"] = len(action_hashes) == EXPECTED_TRANSACTION_ROWS
    for name, passed in checks.items():
        if not passed:
            failures.append(name)
    return {
        "validation_passed": not failures,
        "failures": failures,
        "checks": checks,
        "stale_partial_paths": [provenance_path(path) for path in stale_partials],
        "action_transaction_hash_count": len(action_hashes),
        "authorised_execution_id": AUTHORISED_RECOVERY_EXECUTION_ID,
        "retrieval_code_has_query_submission_path": False,
    }


def persist_recovery_response(
    response: dict[str, Any] | None,
    *,
    payload_path: Path = TRANSACTION_RECOVERY_PAYLOAD,
    state_path: Path = TRANSACTION_RECOVERY_STATE,
    raw_path: Path = TRANSACTION_RAW,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Immediately fsync a retrieval response and promote its deterministic CSV."""
    if response is None:
        raise LiquidationDiagnosticError("Retrieval returned no response; persistence is forbidden.")
    payload, rows, columns = _unwrap(response)
    if payload.get("executionId") != AUTHORISED_RECOVERY_EXECUTION_ID:
        raise LiquidationDiagnosticError("Recovery response is for an unauthorised execution.")
    if len(rows) != EXPECTED_TRANSACTION_ROWS or len(columns) != EXPECTED_TRANSACTION_COLUMNS:
        raise LiquidationDiagnosticError(
            f"Recovery result shape is {len(rows)} x {len(columns)}; expected "
            f"{EXPECTED_TRANSACTION_ROWS} x {EXPECTED_TRANSACTION_COLUMNS}."
        )
    if payload_path.exists():
        raise LiquidationDiagnosticError(f"Refusing to overwrite recovery payload: {payload_path}.")
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, ingress_name = tempfile.mkstemp(
        prefix=f".{payload_path.name}.", suffix=".ingress", dir=payload_path.parent,
    )
    ingress = Path(ingress_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(response, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(ingress, payload_path)
        _fsync_directory(payload_path.parent)
    except Exception:
        ingress.unlink(missing_ok=True)
        raise
    update_state(
        state_path, "recovery_result_received", recovery_retrieval_count=1,
        recovery_retrieval_at_utc=utc_now_iso(), result_shape=[len(rows), len(columns)],
    )
    return persist_result(
        payload_path=payload_path,
        state_path=state_path,
        raw_path=raw_path,
        validator=lambda parsed, names: validate_transaction_rows(
            parsed, names, expected_hashes=_read_action_hashes()
        ),
        row_sort_key=lambda row: str(row["tx_hash"]).lower(),
    )


def retrieve_then_persist(
    retrieve: Callable[[], dict[str, Any] | None],
    persist: Callable[[dict[str, Any]], Any],
) -> Any:
    """Control-flow guard: a successful retrieval must invoke persistence once."""
    response = retrieve()
    if response is None:
        raise LiquidationDiagnosticError("Retrieval response is None; persistence was not called.")
    return persist(response)


def recover_ingress_file(
    ingress_path: Path,
    *,
    state_path: Path = TRANSACTION_RECOVERY_STATE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pass a filesystem-ingressed MCP response immediately to persistence."""
    if not ingress_path.exists() or ingress_path.stat().st_size == 0:
        raise LiquidationDiagnosticError("Recovery ingress payload is absent or empty.")
    with ingress_path.open("r", encoding="utf-8") as handle:
        response = json.load(handle)
    update_state(
        state_path, "recovery_response_ingressed",
        physical_retrieval_call_count=1, logical_retrieval_count=1,
        ingress_path=provenance_path(ingress_path),
        ingress_sha256=sha256_file(ingress_path),
    )
    try:
        result = retrieve_then_persist(
            lambda: response,
            lambda value: persist_recovery_response(value, state_path=state_path),
        )
    except Exception as exc:
        update_state(
            state_path, "recovery_failed", raw_file_persisted=False,
            validation_passed=False, recovery_error=str(exc),
        )
        raise
    ingress_path.unlink()
    return result


def reconcile_bark_kick(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    rows = list(rows)
    barks = [row for row in rows if row["record_type"] == "bark_event"]
    kicks = [row for row in rows if row["record_type"] == "kick_event"]
    matches = [sum(
        auction_key(kick) == auction_key(bark) and kick["tx_hash"] == bark["tx_hash"]
        for kick in kicks
    ) for bark in barks]
    return {
        "matched": sum(value == 1 for value in matches),
        "unmatched": sum(value == 0 for value in matches),
        "multiply_matched": sum(value > 1 for value in matches),
    }


def reconcile_event_calls(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    pairs = {
        "bark": ("bark_event", "bark_call"),
        "kick": ("kick_event", "kick_call"),
        "take": ("take_event", "take_call_success"),
        "redo": ("redo_event", "redo_call_success"),
    }
    result: dict[str, Any] = {}
    for family, (event_type, call_type) in pairs.items():
        keys: dict[tuple[str, str, str], dict[str, int]] = {}
        for row in rows:
            if row["record_type"] not in {event_type, call_type}:
                continue
            key = (*auction_key(row), row["tx_hash"])
            counts = keys.setdefault(key, {"events": 0, "calls": 0})
            counts["events" if row["record_type"] == event_type else "calls"] += 1
        result[family] = {
            "matched_keys": sum(v == {"events": 1, "calls": 1} for v in keys.values()),
            "event_without_call": sum(v["events"] > 0 and v["calls"] == 0 for v in keys.values()),
            "call_without_event": sum(v["calls"] > 0 and v["events"] == 0 for v in keys.values()),
            "ambiguous_keys": sum(v["events"] > 1 or v["calls"] > 1 for v in keys.values()),
        }
    return result


def classify_terminals(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], str]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(auction_key(row), []).append(row)
    output: dict[tuple[str, str], str] = {}
    for key, actions in grouped.items():
        if any(row["record_type"] == "yank_event" for row in actions):
            output[key] = "cancelled"
            continue
        takes = sorted((row for row in actions if row["record_type"] == "take_event"), key=action_order)
        if not takes:
            output[key] = "open_or_unresolved"
            continue
        final = takes[-1]
        tab = decimal_value(final.get("remaining_tab_raw"))
        lot = decimal_value(final.get("remaining_lot_raw"))
        if tab == 0:
            output[key] = "target_cleared"
        elif lot == 0 and tab is not None and tab > 0:
            output[key] = "collateral_exhausted"
        else:
            output[key] = "open_or_unresolved"
    return output


def partial_take_checks(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(auction_key(row), []).append(row)
    comparisons: list[dict[str, float]] = []
    non_monotonic = 0
    redo_boundaries = 0
    multiple = 0
    for actions in grouped.values():
        ordered = sorted(actions, key=action_order)
        kick = next((row for row in ordered if row["record_type"] == "kick_event"), None)
        previous_lot = decimal_value(kick.get("lot_raw")) if kick else None
        previous_tab = decimal_value(kick.get("tab_raw")) if kick else None
        redone = False
        takes = [row for row in ordered if row["record_type"] == "take_event"]
        multiple += int(len(takes) > 1)
        for row in ordered:
            if row["record_type"] == "redo_event":
                redone = True
                redo_boundaries += 1
                redo_lot = decimal_value(row.get("remaining_lot_raw"))
                redo_tab = decimal_value(row.get("remaining_tab_raw"))
                if previous_lot is not None and redo_lot is not None and redo_lot != previous_lot:
                    non_monotonic += 1
                if previous_tab is not None and redo_tab is not None and redo_tab != previous_tab:
                    non_monotonic += 1
                continue
            if row["record_type"] != "take_event":
                continue
            lot = decimal_value(row.get("remaining_lot_raw"))
            tab = decimal_value(row.get("remaining_tab_raw"))
            if previous_lot is not None and lot is not None and lot > previous_lot:
                non_monotonic += 1
            if previous_tab is not None and tab is not None and tab > previous_tab:
                non_monotonic += 1
            if previous_lot is not None and lot is not None:
                delta = (previous_lot - lot) / WAD
                owe = decimal_value(row.get("owe_raw"))
                price = decimal_value(row.get("price_raw"))
                if owe is not None and price not in {None, 0}:
                    implied = (owe / RAD) / (price / RAY)
                    absolute = abs(delta - implied)
                    comparisons.append({
                        "absolute": float(absolute),
                        "relative": float(absolute / abs(implied)) if implied else 0.0,
                        "after_redo": float(redone),
                    })
            previous_lot, previous_tab, redone = lot, tab, False
    return {
        "auctions_with_multiple_takes": multiple,
        "redo_boundary_count": redo_boundaries,
        "non_monotonic_or_redo_state_violation_count": non_monotonic,
        "comparison_count": len(comparisons),
        "maximum_absolute_discrepancy": max((x["absolute"] for x in comparisons), default=0.0),
        "maximum_relative_discrepancy": max((x["relative"] for x in comparisons), default=0.0),
    }


def _scaled_ranges(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    specifications = {
        "ink_wad": ("ink_raw", WAD), "art_wad": ("art_raw", WAD),
        "due_dai": ("due_raw", RAD), "top_dai_per_collateral": ("top_raw", RAY),
        "tab_dai": ("tab_raw", RAD), "lot_wad": ("lot_raw", WAD),
        "coin_dai": ("coin_raw", RAD), "price_dai_per_collateral": ("price_raw", RAY),
        "owe_dai": ("owe_raw", RAD), "remaining_tab_dai": ("remaining_tab_raw", RAD),
        "remaining_lot_wad": ("remaining_lot_raw", WAD),
    }
    result: dict[str, Any] = {}
    rows = list(rows)
    for name, (column, divisor) in specifications.items():
        values = [decimal_value(row.get(column)) / divisor for row in rows if decimal_value(row.get(column)) is not None]
        result[name] = {
            "count": len(values),
            "minimum": float(min(values)) if values else None,
            "maximum": float(max(values)) if values else None,
        }
    return result


def validate_action_rows(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, Any]:
    failures: list[str] = []
    if tuple(columns) != ACTION_COLUMNS:
        failures.append("action output columns are not exact")
    unexpected_types = sorted({row["record_type"] for row in rows}.difference(RECORD_TYPES))
    unexpected_ilks = sorted({row["ilk"] for row in rows}.difference(EXPECTED_ILKS))
    if unexpected_types:
        failures.append(f"unexpected record types: {unexpected_types}")
    if unexpected_ilks:
        failures.append(f"unexpected ilks: {unexpected_ilks}")
    if any(not _truth(row["action_in_bounded_horizon"]) for row in rows):
        failures.append("an action lies outside the bounded horizon")
    duplicates = 0
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        identity = (
            row["source_table"], row["tx_hash"], row["event_index"],
            row["call_trace_address"], row["record_type"],
        )
        duplicates += int(identity in seen)
        seen.add(identity)
    if duplicates:
        failures.append(f"{duplicates} duplicate source rows")
    bark_kick = reconcile_bark_kick(rows)
    if bark_kick["unmatched"] or bark_kick["multiply_matched"]:
        failures.append(f"Bark-Kick mismatch: {bark_kick}")
    anchors = {auction_key(row) for row in rows if row["record_type"] == "bark_event"}
    orphan_count = sum(auction_key(row) not in anchors for row in rows)
    if orphan_count:
        failures.append(f"{orphan_count} orphan rows")
    terminals = classify_terminals(rows)
    terminal_counts: dict[str, int] = {}
    for classification in terminals.values():
        terminal_counts[classification] = terminal_counts.get(classification, 0) + 1
    partial = partial_take_checks(rows)
    if partial["non_monotonic_or_redo_state_violation_count"]:
        failures.append("partial-Take or Redo state validation failed")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["record_type"]] = counts.get(row["record_type"], 0) + 1
    return {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(rows), "column_count": len(columns),
        "record_counts": counts,
        "exact_ilks": sorted({row["ilk"] for row in rows}),
        "window_counts": {
            label: sum(row["initiation_window_label"] == label for row in rows)
            for label in sorted({row["initiation_window_label"] for row in rows})
        },
        "unique_auction_count": len(anchors), "duplicate_source_row_count": duplicates,
        "orphan_row_count": orphan_count, "bark_kick": bark_kick,
        "event_call_reconciliation": reconcile_event_calls(rows),
        "terminal_classifications": terminal_counts,
        "horizon_truncated_auction_count": terminal_counts.get("open_or_unresolved", 0),
        "partial_takes": partial, "scaled_unit_ranges": _scaled_ranges(rows),
        "unique_transaction_count": len({row["tx_hash"] for row in rows}),
    }


def build_transaction_sql(tx_hashes: Iterable[str]) -> str:
    hashes = sorted({str(value).lower() for value in tx_hashes})
    if not hashes or len(hashes) > 2_000:
        raise LiquidationDiagnosticError(f"Transaction VALUES list size is {len(hashes)}; expected 1..2000.")
    for value in hashes:
        if len(value) != 66 or not value.startswith("0x") or any(char not in "0123456789abcdef" for char in value[2:]):
            raise LiquidationDiagnosticError(f"Invalid transaction hash: {value!r}.")
    values = ",\n        ".join(f"({value})" for value in hashes)
    return f"""-- Phase 1C attempt-three unique transaction bridge only.
WITH selected_hashes(tx_hash) AS (
    VALUES
        {values}
)
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
FROM ethereum.transactions t
JOIN selected_hashes h ON t.hash = h.tx_hash
WHERE (
        t.block_date >= DATE '2023-02-01' AND t.block_date < DATE '2023-02-10'
    AND t.block_time >= TIMESTAMP '2023-02-01 00:00:00' AND t.block_time < TIMESTAMP '2023-02-10 00:00:00'
) OR (
        t.block_date >= DATE '2022-06-13' AND t.block_date < DATE '2022-06-22'
    AND t.block_time >= TIMESTAMP '2022-06-13 00:00:00' AND t.block_time < TIMESTAMP '2022-06-22 00:00:00'
)
"""


def write_transaction_sql(path: Path, tx_hashes: Iterable[str]) -> str:
    sql = build_transaction_sql(tx_hashes)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(sql)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return hashlib.sha256(sql.encode()).hexdigest()


def _read_action_hashes(path: Path = ACTION_RAW) -> set[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {str(row["tx_hash"]).lower() for row in csv.DictReader(handle)}


def _parse_utc(value: Any) -> datetime:
    text = str(value).strip().replace(" UTC", "+00:00").replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_transaction_rows(
    rows: list[dict[str, Any]],
    columns: list[str],
    *,
    expected_hashes: set[str] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    if tuple(columns) != TRANSACTION_COLUMNS:
        failures.append("transaction output columns are not exact")
    hashes = [str(row.get("tx_hash") or "").lower() for row in rows]
    duplicates = len(hashes) - len(set(hashes))
    if duplicates:
        failures.append(f"{duplicates} duplicate transaction hashes")
    malformed = sum(not re.fullmatch(r"0x[0-9a-f]{64}", value) for value in hashes)
    null_hashes = sum(not row.get("tx_hash") for row in rows)
    invalid_success = 0
    invalid_gas = 0
    invalid_timestamp = 0
    date_mismatch = 0
    non_finite = 0
    for row in rows:
        if str(row.get("success")).lower() not in {"true", "false", "1", "0"}:
            invalid_success += 1
        try:
            used = Decimal(str(row["gas_used"]))
            limit = Decimal(str(row["gas_limit"]))
            price = Decimal(str(row["gas_price"]))
            numeric = [used, limit, price]
            numeric.extend(
                Decimal(str(row[name])) for name in (
                    "max_fee_per_gas", "max_priority_fee_per_gas", "priority_fee_per_gas"
                ) if row.get(name) not in {None, ""}
            )
            non_finite += sum(not value.is_finite() for value in numeric)
            if used <= 0 or limit <= 0 or used > limit or price < 0:
                invalid_gas += 1
        except (ArithmeticError, KeyError, TypeError, ValueError):
            invalid_gas += 1
        try:
            timestamp = _parse_utc(row["block_time"])
            if timestamp.date().isoformat() != str(row["block_date"]):
                date_mismatch += 1
        except (KeyError, TypeError, ValueError):
            invalid_timestamp += 1
    observed = set(hashes)
    expected = {value.lower() for value in expected_hashes} if expected_hashes is not None else None
    action_minus_transactions = sorted(expected.difference(observed)) if expected is not None else []
    transactions_minus_actions = sorted(observed.difference(expected)) if expected is not None else []
    if expected is not None and len(rows) != len(expected):
        failures.append(f"row count {len(rows)} differs from expected {len(expected)}")
    for label, value in (
        ("null transaction hashes", null_hashes), ("malformed transaction hashes", malformed),
        ("invalid success values", invalid_success), ("invalid gas rows", invalid_gas),
        ("invalid timestamps", invalid_timestamp), ("block date mismatches", date_mismatch),
        ("non-finite numeric values", non_finite),
        ("action hashes missing from transactions", len(action_minus_transactions)),
        ("unexpected transaction hashes", len(transactions_minus_actions)),
    ):
        if value:
            failures.append(f"{value} {label}")
    return {
        "validation_passed": not failures, "failures": failures,
        "row_count": len(rows), "column_count": len(columns),
        "unique_transaction_count": len(set(hashes)), "duplicate_transaction_count": duplicates,
        "null_transaction_hash_count": null_hashes,
        "malformed_transaction_hash_count": malformed,
        "invalid_success_count": invalid_success,
        "invalid_gas_row_count": invalid_gas,
        "invalid_timestamp_count": invalid_timestamp,
        "block_date_mismatch_count": date_mismatch,
        "non_finite_numeric_count": non_finite,
        "action_minus_transaction_hashes": action_minus_transactions,
        "transaction_minus_action_hashes": transactions_minus_actions,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    position = (len(values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _distribution(values: Iterable[Any]) -> dict[str, float | int | None]:
    parsed = sorted(float(decimal_value(value)) for value in values if decimal_value(value) is not None)
    return {
        "count": len(parsed), "minimum": parsed[0] if parsed else None,
        "p25": _percentile(parsed, 0.25), "median": median(parsed) if parsed else None,
        "mean": sum(parsed) / len(parsed) if parsed else None,
        "p75": _percentile(parsed, 0.75), "p90": _percentile(parsed, 0.90),
        "p95": _percentile(parsed, 0.95), "p99": _percentile(parsed, 0.99),
        "maximum": parsed[-1] if parsed else None,
    }


def combined_diagnostics(
    actions: list[dict[str, Any]], transactions: list[dict[str, Any]]
) -> dict[str, Any]:
    tx_by_hash = {row["tx_hash"].lower(): row for row in transactions}
    action_hashes = {row["tx_hash"].lower() for row in actions}
    missing = sorted(action_hashes.difference(tx_by_hash))
    semantic_by_tx: dict[str, list[dict[str, Any]]] = {}
    for row in actions:
        if row["record_type"].endswith("_event") or row["record_type"].endswith("_failed"):
            semantic_by_tx.setdefault(row["tx_hash"].lower(), []).append(row)
    multi_action = sum(len(rows) > 1 for rows in semantic_by_tx.values())
    multi_auction = sum(len({auction_key(row) for row in rows}) > 1 for rows in semantic_by_tx.values())
    failed_calls = [row for row in actions if row["record_type"] in {"take_call_failed", "redo_call_failed"}]
    failed_top_success = sum(_truth(tx_by_hash.get(row["tx_hash"].lower(), {}).get("success")) for row in failed_calls)
    failed_top_failed = sum(not _truth(tx_by_hash.get(row["tx_hash"].lower(), {}).get("success")) for row in failed_calls if row["tx_hash"].lower() in tx_by_hash)
    gas_by_type: dict[str, Any] = {}
    for record_type in sorted({row["record_type"] for row in actions}):
        hashes = {row["tx_hash"].lower() for row in actions if row["record_type"] == record_type}
        gas_by_type[record_type] = {
            "gas_used": _distribution(tx_by_hash[h]["gas_used"] for h in hashes if h in tx_by_hash),
            "gas_price_wei": _distribution(tx_by_hash[h]["gas_price"] for h in hashes if h in tx_by_hash),
            "unique_transaction_count": len(hashes),
        }
    successful_take_hashes = {
        row["tx_hash"].lower() for row in actions if row["record_type"] == "take_event"
    }
    duplicated_narrow = sum(
        len({auction_key(row) for row in semantic_by_tx.get(tx_hash, [])}) > 1
        for tx_hash in successful_take_hashes
    )
    return {
        "validation_passed": not missing,
        "missing_transaction_hashes": missing,
        "unique_transaction_count": len(tx_by_hash),
        "multi_action_transaction_count": multi_action,
        "multi_auction_transaction_count": multi_auction,
        "failed_call_count": len(failed_calls),
        "failed_calls_with_successful_top_level_transaction": failed_top_success,
        "failed_calls_with_failed_top_level_transaction": failed_top_failed,
        "failed_call_gas_is_transaction_level_only": True,
        "gas_distributions_by_record_type": gas_by_type,
        "successful_take_transaction_count": len(successful_take_hashes),
        "successful_take_transactions_touching_multiple_auctions": duplicated_narrow,
        "narrow_take_gas_measurable_without_auction_duplication": duplicated_narrow == 0,
    }


def _read_csv(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def _semantic_actions_by_transaction(
    actions: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in actions:
        if row["record_type"].endswith("_event") or row["record_type"].endswith("_failed"):
            grouped.setdefault(row["tx_hash"].lower(), []).append(row)
    return grouped


def classify_successful_take_transactions(
    actions: list[dict[str, Any]],
) -> dict[str, str]:
    semantic = _semantic_actions_by_transaction(actions)
    take_hashes = {row["tx_hash"].lower() for row in actions if row["record_type"] == "take_event"}
    classifications: dict[str, str] = {}
    for tx_hash in take_hashes:
        relevant = semantic[tx_hash]
        takes = [row for row in relevant if row["record_type"] == "take_event"]
        take_auctions = {auction_key(row) for row in takes}
        all_auctions = {auction_key(row) for row in relevant}
        other = [row for row in relevant if row["record_type"] != "take_event"]
        if len(all_auctions) > 1:
            label = "multiple_auctions"
        elif len(takes) > 1 and len(take_auctions) == 1 and not other:
            label = "multiple_takes_same_auction"
        elif len(takes) == 1 and other:
            label = "other_liquidation_actions_same_tx"
        elif len(takes) == 1 and len(take_auctions) == 1:
            label = "clean_single_take_single_auction"
        else:
            label = "ambiguous"
        classifications[tx_hash] = label
    return classifications


def _transaction_group_distributions(
    hashes: Iterable[str], tx_by_hash: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    unique = sorted(set(hashes))
    rows = [tx_by_hash[value] for value in unique]
    return {
        "transaction_count": len(rows),
        "gas_used": _distribution(row["gas_used"] for row in rows),
        "effective_gas_price_gwei": _distribution(
            Decimal(row["gas_price"]) / Decimal(10**9) for row in rows
        ),
        "transaction_fee_eth": _distribution(
            Decimal(row["gas_used"]) * Decimal(row["gas_price"]) / Decimal(10**18)
            for row in rows
        ),
    }


def _load_hourly_lookup(path: Path, columns: tuple[str, ...]) -> dict[datetime, dict[str, float]]:
    output: dict[datetime, dict[str, float]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            timestamp = _parse_utc(row["timestamp_utc"]).replace(minute=0, second=0, microsecond=0)
            output[timestamp] = {column: float(row[column]) for column in columns}
    return output


def _ratio_summary(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "count": len(ordered), "median": _percentile(ordered, 0.50),
        "p75": _percentile(ordered, 0.75), "p90": _percentile(ordered, 0.90),
        "p95": _percentile(ordered, 0.95),
        "percentage_above_one": 100 * sum(value > 1 for value in ordered) / len(ordered),
    }


def complete_recovery_diagnostics(
    actions: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    *,
    market_path: Path = MARKET_PANEL,
    gas_path: Path = GAS_PANEL,
) -> dict[str, Any]:
    tx_by_hash = {row["tx_hash"].lower(): row for row in transactions}
    action_hashes = {row["tx_hash"].lower() for row in actions}
    semantic = _semantic_actions_by_transaction(actions)
    classifications = classify_successful_take_transactions(actions)
    class_counts: dict[str, int] = {}
    for label in classifications.values():
        class_counts[label] = class_counts.get(label, 0) + 1

    record_hashes = {
        name: {row["tx_hash"].lower() for row in actions if row["record_type"] == record_type}
        for name, record_type in {
            "bark": "bark_event", "kick": "kick_event",
            "successful_take": "take_event", "failed_take_call": "take_call_failed",
        }.items()
    }
    record_hashes["multi_action"] = {
        tx_hash for tx_hash, rows in semantic.items() if len(rows) > 1
    }
    record_hashes["multi_auction"] = {
        tx_hash for tx_hash, rows in semantic.items()
        if len({auction_key(row) for row in rows}) > 1
    }
    distributions = {
        name: _transaction_group_distributions(hashes, tx_by_hash)
        for name, hashes in record_hashes.items()
    }

    failed_rows = [row for row in actions if row["record_type"] == "take_call_failed"]
    failed_hashes = record_hashes["failed_take_call"]
    successful_action_hashes = {
        row["tx_hash"].lower() for row in actions
        if row["record_type"] in {"bark_event", "kick_event", "take_event", "redo_event"}
    }
    failed_counts_per_tx: dict[str, int] = {}
    for row in failed_rows:
        key = row["tx_hash"].lower()
        failed_counts_per_tx[key] = failed_counts_per_tx.get(key, 0) + 1

    market = _load_hourly_lookup(market_path, ("eth_price_usd",))
    gas = _load_hourly_lookup(
        gas_path,
        ("median_effective_gas_price_gwei", "p90_effective_gas_price_gwei",
         "p99_effective_gas_price_gwei"),
    )
    enriched: dict[str, dict[str, float]] = {}
    missing_market: list[str] = []
    missing_gas: list[str] = []
    for tx_hash, row in tx_by_hash.items():
        hour = _parse_utc(row["block_time"]).replace(minute=0, second=0, microsecond=0)
        if hour not in market:
            missing_market.append(tx_hash)
            continue
        if hour not in gas:
            missing_gas.append(tx_hash)
            continue
        used = float(row["gas_used"])
        price_wei = float(row["gas_price"])
        price_gwei = price_wei / 1e9
        fee_eth = used * price_wei * 1e-18
        enriched[tx_hash] = {
            "gas_used": used, "gas_price_gwei": price_gwei,
            "fee_eth": fee_eth, "fee_usd": fee_eth * market[hour]["eth_price_usd"],
            "actual_to_hourly_median_ratio": price_gwei / gas[hour]["median_effective_gas_price_gwei"],
            "actual_to_hourly_p90_ratio": price_gwei / gas[hour]["p90_effective_gas_price_gwei"],
            "actual_to_hourly_p99_ratio": price_gwei / gas[hour]["p99_effective_gas_price_gwei"],
        }

    successful_take_hashes = record_hashes["successful_take"]
    clean_hashes = {
        tx_hash for tx_hash, label in classifications.items()
        if label == "clean_single_take_single_auction"
    }
    cost_groups = {
        "clean_successful_take": clean_hashes,
        "all_successful_take": successful_take_hashes,
        "failed_take_call": failed_hashes,
        "bark": record_hashes["bark"],
    }
    cost_distributions: dict[str, Any] = {}
    for name, hashes in cost_groups.items():
        values = [enriched[value] for value in sorted(hashes) if value in enriched]
        cost_distributions[name] = {
            "transaction_count": len(values),
            "transaction_gas_cost_eth": _distribution(value["fee_eth"] for value in values),
            "transaction_gas_cost_usd": _distribution(value["fee_usd"] for value in values),
        }

    hourly_comparisons: dict[str, Any] = {}
    for name, hashes in {
        "successful_take": successful_take_hashes,
        "failed_take_call": failed_hashes,
    }.items():
        values = [enriched[value] for value in sorted(hashes) if value in enriched]
        hourly_comparisons[name] = {
            ratio: _ratio_summary([value[ratio] for value in values])
            for ratio in (
                "actual_to_hourly_median_ratio", "actual_to_hourly_p90_ratio",
                "actual_to_hourly_p99_ratio",
            )
        }

    take_gas = [float(tx_by_hash[value]["gas_used"]) for value in successful_take_hashes]
    bins = {
        "below_100k": sum(value < 100_000 for value in take_gas),
        "100k_to_below_300k": sum(100_000 <= value < 300_000 for value in take_gas),
        "300k_to_500k_inclusive": sum(300_000 <= value <= 500_000 for value in take_gas),
        "above_500k": sum(value > 500_000 for value in take_gas),
    }
    gas_unit_comparison = {
        key: {"count": count, "percentage": 100 * count / len(take_gas)}
        for key, count in bins.items()
    }

    joined_action_count = sum(row["tx_hash"].lower() in tx_by_hash for row in actions)
    transaction_times = [_parse_utc(row["block_time"]) for row in transactions]
    return {
        "validation_passed": (
            action_hashes == set(tx_by_hash) and joined_action_count == len(actions)
            and len(tx_by_hash) == len(transactions) and not missing_market and not missing_gas
        ),
        "action_minus_transaction_hashes": sorted(action_hashes.difference(tx_by_hash)),
        "transaction_minus_action_hashes": sorted(set(tx_by_hash).difference(action_hashes)),
        "joined_action_row_count": joined_action_count,
        "expected_joined_action_row_count": len(actions),
        "join_row_multiplication_count": 0 if len(tx_by_hash) == len(transactions) else None,
        "transaction_structure": {
            "unique_transaction_count": len(tx_by_hash),
            "multi_action_transaction_count": len(record_hashes["multi_action"]),
            "multi_auction_transaction_count": len(record_hashes["multi_auction"]),
            "maximum_semantic_actions_in_one_transaction": max(map(len, semantic.values())),
            "successful_take_transaction_count": len(successful_take_hashes),
            "successful_take_transactions_touching_multiple_auctions": sum(
                len({auction_key(row) for row in semantic[value]}) > 1
                for value in successful_take_hashes
            ),
        },
        "transaction_distributions": distributions,
        "failed_take_calls": {
            "failed_call_row_count": len(failed_rows),
            "distinct_transaction_count": len(failed_hashes),
            "top_level_successful_transaction_count": sum(
                _truth(tx_by_hash[value]["success"]) for value in failed_hashes
            ),
            "top_level_failed_transaction_count": sum(
                not _truth(tx_by_hash[value]["success"]) for value in failed_hashes
            ),
            "transactions_also_containing_successful_liquidation_action": len(
                failed_hashes.intersection(successful_action_hashes)
            ),
            "transactions_with_multiple_failed_calls": sum(
                count > 1 for count in failed_counts_per_tx.values()
            ),
            "top_level_transaction_gas_only": True,
        },
        "successful_take_classification": {
            "counts": class_counts,
            "direct_gas_unit_estimation_classes": ["clean_single_take_single_auction"],
            "sensitivity_or_exclusion_classes": [
                "multiple_takes_same_auction", "other_liquidation_actions_same_tx",
                "multiple_auctions", "ambiguous",
            ],
        },
        "gas_cost_distributions": cost_distributions,
        "hourly_gas_environment_comparison": hourly_comparisons,
        "successful_take_gas_unit_index_comparison": gas_unit_comparison,
        "missing_market_hour_hashes": missing_market,
        "missing_gas_hour_hashes": missing_gas,
        "actual_coverage": {
            "minimum_block_time_utc": min(transaction_times).isoformat(),
            "maximum_block_time_utc": max(transaction_times).isoformat(),
        },
        "gas_attribution_warning": (
            "Gas is deduplicated by transaction hash. Attached action-row gas is repeated "
            "top-level transaction information and is not inner-call gas."
        ),
    }
