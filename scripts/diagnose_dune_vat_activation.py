"""Acquire and validate the bounded WBTC-B/C Vat activation diagnostic.

The command has GET-only Dune access: status polling and one result request. It
cannot create, modify or execute a query.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "sql" / "dune_phase1d_vat_wbtc_activation_diagnostic.sql"
OUTPUT_DIR = (
    ROOT / "data" / "provenance" / "protocol" / "archive" / "diagnostic"
)
RAW_PATH = OUTPUT_DIR / "phase1d_vat_wbtc_activation_diagnostic.csv"
STATE_PATH = OUTPUT_DIR / "phase1d_vat_wbtc_activation_diagnostic_state.json"
METADATA_PATH = OUTPUT_DIR / "phase1d_vat_wbtc_activation_diagnostic_metadata.json"
VALIDATION_PATH = OUTPUT_DIR / "phase1d_vat_wbtc_activation_diagnostic_validation.json"
EVIDENCE_PATH = OUTPUT_DIR / "phase1d_vat_activation_evidence.json"
PRESERVED_FAILED_PATH = (
    OUTPUT_DIR / ".phase1d_vat_wbtc_activation_diagnostic.csv.md4nufka.partial.failed"
)
PRESERVED_FAILED_SHA256 = "5576298ce05e1960520a233c4e5716235a7da7e9c5094ec8d3deeaaf1b0c3036"
API_ROOT = "https://api.dune.com/api/v1"
SAMPLE_START = "2021-06-01T00:00:00+00:00"
SAMPLE_END = "2024-07-01T00:00:00+00:00"
TARGET_ILKS = ("WBTC-B", "WBTC-C")
CANONICAL_VAT = "0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b"
EXPECTED_COLUMNS = (
    "ilk", "call_type", "parameter_key", "raw_value", "converted_value_dai",
    "block_time", "block_number", "transaction_index", "call_position",
    "transaction_hash", "vat_contract",
)


class ActivationDiagnosticError(RuntimeError):
    """Raised when activation evidence or persistence is unsafe."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _fsync_directory(path: Path) -> None:
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
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def validate_sql(sql: str) -> dict[str, Any]:
    lower = sql.lower()
    failures = []
    for fragment in (
        "maker_ethereum.vat_call_init", "maker_ethereum.vat_call_file",
        "'wbtc-b'", "'wbtc-c'", "'line'", "'dust'",
        CANONICAL_VAT, "date '2019-11-01'", "date '2024-07-01'",
        "call_block_date", "call_block_time", "order by",
    ):
        if fragment not in lower:
            failures.append(f"missing SQL fragment: {fragment}")
    for forbidden in ("eth-a", "eth-b", "eth-c", "wbtc-a", "select *", "ethereum.transactions"):
        if forbidden in lower:
            failures.append(f"forbidden SQL fragment: {forbidden}")
    return {
        "validation_passed": not failures, "failures": failures,
        "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
    }


def initialise_state() -> dict[str, Any]:
    if RAW_PATH.exists() or STATE_PATH.exists():
        raise ActivationDiagnosticError("Refusing to overwrite an existing activation diagnostic")
    report = validate_sql(SQL_PATH.read_text(encoding="utf-8"))
    if not report["validation_passed"]:
        raise ActivationDiagnosticError("; ".join(report["failures"]))
    state = {
        "state": "planned", "query_type": "private temporary diagnostic",
        "engine": "small", "sql_path": relative(SQL_PATH),
        "sql_sha256": report["sql_sha256"], "query_id": None,
        "query_url": None, "execution_id": None, "status_request_count": 0,
        "result_retrieval_count": 0, "raw_file_persisted": False,
        "validation_passed": False, "target_ilks": list(TARGET_ILKS),
    }
    write_json_atomic(STATE_PATH, state)
    return state


def update_state(state_name: str, **fields: Any) -> dict[str, Any]:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state.update(fields)
    state["state"] = state_name
    state["updated_at_utc"] = utc_now_iso()
    write_json_atomic(STATE_PATH, state)
    return state


def record_execution(query_id: int, query_url: str, execution_id: str, state: str) -> dict[str, Any]:
    return update_state(
        "execution_submitted", query_id=query_id, query_url=query_url,
        execution_id=execution_id, execution_state=state,
        submitted_at_utc=utc_now_iso(),
    )


def _api_json(api_key: str, url: str) -> dict[str, Any]:
    request = Request(url, headers={"X-Dune-API-Key": api_key}, method="GET")
    try:
        with urlopen(request, timeout=180) as response:
            body = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000].replace(api_key, "[REDACTED]")
        raise ActivationDiagnosticError(f"Dune API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ActivationDiagnosticError(f"Dune API request failed: {exc.reason}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ActivationDiagnosticError("Dune returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ActivationDiagnosticError("Dune returned a non-object JSON response")
    return payload


def _metadata(payload: dict[str, Any]) -> tuple[int, list[str]]:
    candidates = [payload.get("result_metadata"),
                  (payload.get("result") or {}).get("metadata")
                  if isinstance(payload.get("result"), dict) else None]
    metadata = next((item for item in candidates if isinstance(item, dict)), {})
    total = metadata.get("total_row_count", metadata.get("row_count"))
    columns = metadata.get("column_names", metadata.get("columns"))
    if isinstance(columns, list) and columns and isinstance(columns[0], dict):
        columns = [item.get("name") for item in columns]
    if total is None or not isinstance(columns, list) or not columns:
        raise ActivationDiagnosticError("Execution metadata lacks row count or schema")
    return int(total), [str(column) for column in columns]


def validate_rows(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, Any]:
    failures: list[str] = []
    if tuple(columns) != EXPECTED_COLUMNS:
        failures.append(f"unexpected columns: {columns}")
    if not rows:
        failures.append("activation diagnostic is empty")
    source_keys = set()
    order = []
    tie_keys = []
    conversions_failed = 0
    blank_transaction_indices = 0
    events: dict[str, dict[str, list[dict[str, Any]]]] = {
        ilk: {"init": [], "line": [], "dust": []} for ilk in TARGET_ILKS
    }
    for index, row in enumerate(rows):
        ilk = str(row.get("ilk"))
        call_type = str(row.get("call_type"))
        key = str(row.get("parameter_key"))
        if ilk not in TARGET_ILKS:
            failures.append(f"row {index} has unexpected ilk {ilk}")
            continue
        if (call_type, key) not in {("init", "init"), ("file", "line"), ("file", "dust")}:
            failures.append(f"row {index} has unexpected call/key {call_type}/{key}")
        if str(row.get("vat_contract", "")).lower() != CANONICAL_VAT:
            failures.append(f"row {index} has non-canonical Vat contract")
        if not re.fullmatch(r"0x[0-9a-fA-F]{64}", str(row.get("transaction_hash", ""))):
            failures.append(f"row {index} has malformed transaction hash")
        source_key = (str(row.get("transaction_hash")), str(row.get("call_position")), call_type, key)
        if source_key in source_keys:
            failures.append(f"row {index} duplicates a source call")
        source_keys.add(source_key)
        timestamp = datetime.fromisoformat(str(row["block_time"]).replace(" UTC", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        transaction_index = str(row.get("transaction_index") or "").strip()
        if not transaction_index:
            blank_transaction_indices += 1
        elif not transaction_index.isdigit():
            failures.append(f"row {index} has a malformed available transaction index")
        deterministic_key = (
            timestamp, int(row["block_number"]), str(row["transaction_hash"]).lower(),
            str(row["call_position"]), call_type, key,
        )
        order.append(deterministic_key)
        tie_keys.append(deterministic_key)
        entry = dict(row)
        entry["timestamp"] = timestamp.isoformat()
        events[ilk][key].append(entry)
        if key in {"line", "dust"}:
            try:
                raw = Decimal(str(row["raw_value"]))
                converted = float(row["converted_value_dai"])
                expected = float(raw / Decimal("1e45"))
                if raw < 0 or not math.isfinite(converted) or not math.isclose(
                    converted, expected, rel_tol=1e-12, abs_tol=1e-12
                ):
                    conversions_failed += 1
            except (ValueError, TypeError, ArithmeticError):
                conversions_failed += 1
    if order != sorted(order):
        failures.append("rows are not in deterministic chronological order")
    unresolved_tie_count = len(tie_keys) - len(set(tie_keys))
    if unresolved_tie_count:
        failures.append(f"unresolved deterministic-ordering ties: {unresolved_tie_count}")
    if conversions_failed:
        failures.append(f"RAD conversion failures: {conversions_failed}")
    classifications: dict[str, Any] = {}
    sample_start = datetime.fromisoformat(SAMPLE_START)
    for ilk in TARGET_ILKS:
        init_calls = events[ilk]["init"]
        if not init_calls:
            failures.append(f"{ilk} has no explicit Vat.init call")
        earliest_init = init_calls[0] if init_calls else None
        for key in ("line", "dust"):
            calls = events[ilk][key]
            pre = [row for row in calls if datetime.fromisoformat(row["timestamp"]) < sample_start]
            if pre:
                classification = "active_before_sample_start"
                activation = pre[-1]
            elif calls and earliest_init:
                first = calls[0]
                first_time = datetime.fromisoformat(first["timestamp"])
                init_time = datetime.fromisoformat(earliest_init["timestamp"])
                if first_time >= sample_start and init_time <= first_time:
                    classification = "activated_during_sample"
                    activation = first
                else:
                    classification = "indeterminate"
                    activation = first
                    failures.append(f"{ilk} {key} lacks conclusive in-sample activation evidence")
            else:
                classification = "indeterminate"
                activation = None
                failures.append(f"{ilk} {key} has no setting call")
            classifications[f"{ilk}:{key}"] = {
                "classification": classification,
                "earliest_init": earliest_init,
                "earliest_setting": calls[0] if calls else None,
                "latest_pre_sample_setting": pre[-1] if pre else None,
                "activation_setting": activation,
                "initial_value_explicit_zero": (
                    str(activation.get("raw_value")) == "0" if activation else None
                ),
                "first_in_sample_zero_setting": next((
                    row for row in calls
                    if datetime.fromisoformat(row["timestamp"]) >= sample_start
                    and Decimal(str(row["raw_value"])) == 0
                ), None),
                "first_in_sample_non_zero_setting": next((
                    row for row in calls
                    if datetime.fromisoformat(row["timestamp"]) >= sample_start
                    and Decimal(str(row["raw_value"])) > 0
                ), None),
            }
    return {
        "validation_passed": not failures, "failures": failures,
        "row_count": len(rows), "column_count": len(columns),
        "duplicate_source_call_count": len(rows) - len(source_keys),
        "unit_conversion_failure_count": conversions_failed,
        "transaction_index_availability": {
            "available_count": len(rows) - blank_transaction_indices,
            "unavailable_count": blank_transaction_indices,
            "fabricated_default_used": False,
        },
        "deterministic_order_fields": [
            "block_time", "block_number", "transaction_hash",
            "call_position", "call_type", "parameter_key",
        ],
        "unresolved_ordering_tie_count": unresolved_tie_count,
        "classifications": classifications,
    }


def recover_preserved_diagnostic() -> dict[str, Any]:
    """Validate and atomically promote the checksum-pinned local failed partial."""
    if not PRESERVED_FAILED_PATH.exists():
        raise ActivationDiagnosticError("Preserved failed partial is absent")
    observed_checksum = sha256_file(PRESERVED_FAILED_PATH)
    if observed_checksum != PRESERVED_FAILED_SHA256:
        raise ActivationDiagnosticError(
            f"Preserved diagnostic checksum mismatch: {observed_checksum}"
        )
    if RAW_PATH.exists():
        raise ActivationDiagnosticError("Final diagnostic CSV already exists")
    with PRESERVED_FAILED_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = list(reader.fieldnames or [])
    if len(rows) != 325 or len(columns) != 11:
        raise ActivationDiagnosticError(
            f"Preserved diagnostic is {len(rows)} x {len(columns)}, expected 325 x 11"
        )
    report = validate_rows(rows, columns)
    if not report["validation_passed"]:
        write_json_atomic(VALIDATION_PATH, report)
        raise ActivationDiagnosticError("; ".join(report["failures"]))
    def ordering_key(row: dict[str, Any]) -> tuple[Any, ...]:
        timestamp = datetime.fromisoformat(str(row["block_time"]).replace(" UTC", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return (
            timestamp, int(row["block_number"]), str(row["transaction_hash"]).lower(),
            str(row["call_position"]), str(row["call_type"]),
            str(row["parameter_key"]),
        )
    ordered_rows = sorted(rows, key=ordering_key)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{RAW_PATH.name}.", suffix=".corrected.partial", dir=RAW_PATH.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=columns, extrasaction="raise", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(ordered_rows)
            handle.flush()
            os.fsync(handle.fileno())
        with temporary.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            persisted_rows = list(reader)
            persisted_columns = list(reader.fieldnames or [])
        persisted_report = validate_rows(persisted_rows, persisted_columns)
        if not persisted_report["validation_passed"]:
            raise ActivationDiagnosticError(
                "Corrected diagnostic failed semantic validation: "
                + "; ".join(persisted_report["failures"])
            )
        os.replace(temporary, RAW_PATH)
        _fsync_directory(RAW_PATH.parent)
    except Exception:
        if temporary.exists():
            os.replace(temporary, temporary.with_suffix(temporary.suffix + ".failed"))
            _fsync_directory(temporary.parent)
        raise
    final_checksum = sha256_file(RAW_PATH)
    evidence = {
        "status": "validated",
        "sample_start_utc": SAMPLE_START,
        "sample_end_exclusive_utc": SAMPLE_END,
        "source": "canonical Vat init and file calls",
        "preserved_failed_partial": relative(PRESERVED_FAILED_PATH),
        "preserved_failed_partial_sha256": observed_checksum,
        "classifications": persisted_report["classifications"],
        "ordering": {
            "fields": persisted_report["deterministic_order_fields"],
            "unresolved_tie_count": persisted_report["unresolved_ordering_tie_count"],
            "transaction_index_unavailable_count": 325,
            "transaction_index_default_fabricated": False,
        },
    }
    write_json_atomic(EVIDENCE_PATH, evidence)
    write_json_atomic(VALIDATION_PATH, persisted_report)
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state.update({
        "state": "complete_local_recovery",
        "local_recovery_only": True,
        "additional_dune_calls": 0,
        "prior_failure_preserved": True,
        "preserved_failed_partial_path": relative(PRESERVED_FAILED_PATH),
        "preserved_failed_partial_sha256": observed_checksum,
        "raw_file_persisted": True,
        "validation_passed": True,
        "row_count": len(persisted_rows),
        "column_count": len(persisted_columns),
        "raw_path": relative(RAW_PATH),
        "raw_size_bytes": RAW_PATH.stat().st_size,
        "raw_sha256": final_checksum,
        "evidence_path": relative(EVIDENCE_PATH),
        "local_recovered_at_utc": utc_now_iso(),
    })
    write_json_atomic(STATE_PATH, state)
    metadata = {
        "query_id": 8075457,
        "execution_id": "01KY5WM6WTQYVVZ5Q5W9BXBSY2",
        "sql_path": relative(SQL_PATH),
        "sql_sha256": "54887f35d662aa9087d182afff6b709394e5cd7679b06bc1e56d93a2ad18b1fb",
        "recovery_source": relative(PRESERVED_FAILED_PATH),
        "recovery_source_sha256": observed_checksum,
        "dimensions": [len(persisted_rows), len(persisted_columns)],
        "raw_path": relative(RAW_PATH),
        "raw_size_bytes": RAW_PATH.stat().st_size,
        "raw_sha256": final_checksum,
        "dune_calls_during_local_recovery": 0,
        "recovered_at_utc": utc_now_iso(),
    }
    write_json_atomic(METADATA_PATH, metadata)
    return persisted_report | metadata


def retrieve_and_persist(api_key: str, timeout_seconds: int = 180) -> dict[str, Any]:
    if RAW_PATH.exists():
        raise ActivationDiagnosticError("Final activation CSV already exists")
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    execution_id = str(state.get("execution_id") or "")
    if not execution_id:
        raise ActivationDiagnosticError("Execution ID is not recorded")
    deadline = time.monotonic() + timeout_seconds
    status_count = 0
    while True:
        status = _api_json(api_key, f"{API_ROOT}/execution/{execution_id}/status")
        status_count += 1
        execution_state = status.get("state")
        update_state("polling", status_request_count=status_count, execution_state=execution_state)
        if execution_state == "QUERY_STATE_COMPLETED":
            break
        if execution_state in {"QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_CANCELED", "QUERY_STATE_EXPIRED"}:
            raise ActivationDiagnosticError(f"Execution ended in {execution_state}: {status.get('error')}")
        if time.monotonic() >= deadline:
            raise ActivationDiagnosticError("Status polling timed out; no retry was made")
        time.sleep(2)
    expected_rows, expected_columns = _metadata(status)
    if tuple(expected_columns) != EXPECTED_COLUMNS:
        raise ActivationDiagnosticError(f"Status schema mismatch: {expected_columns}")
    limit = max(1000, expected_rows + 100)
    query = urlencode({"limit": limit, "offset": 0})
    response = _api_json(api_key, f"{API_ROOT}/execution/{execution_id}/results?{query}")
    result = response.get("result")
    rows = result.get("rows") if isinstance(result, dict) else None
    result_rows, result_columns = _metadata(response)
    if not isinstance(rows, list) or len(rows) != expected_rows:
        raise ActivationDiagnosticError("Result retrieval is incomplete")
    if result_rows != expected_rows or result_columns != expected_columns:
        raise ActivationDiagnosticError("Status and result metadata differ")
    if response.get("next_offset") not in (None, "", 0):
        raise ActivationDiagnosticError("Result is paginated; no further request was made")
    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True)
    descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{RAW_PATH.name}.", suffix=".partial", dir=OUTPUT_DIR,
    )
    partial = Path(partial_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=expected_columns,
                                    extrasaction="raise", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        with partial.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            parsed = list(reader)
            parsed_columns = list(reader.fieldnames or [])
        report = validate_rows(parsed, parsed_columns)
        write_json_atomic(VALIDATION_PATH, report)
        if not report["validation_passed"]:
            raise ActivationDiagnosticError("; ".join(report["failures"]))
        os.replace(partial, RAW_PATH)
        _fsync_directory(RAW_PATH.parent)
    except Exception:
        if partial.exists():
            os.replace(partial, partial.with_suffix(".partial.failed"))
            _fsync_directory(partial.parent)
        update_state("failed", result_retrieval_count=1, raw_file_persisted=False)
        raise
    checksum = sha256_file(RAW_PATH)
    evidence = {
        "status": "validated", "sample_start_utc": SAMPLE_START,
        "sample_end_exclusive_utc": SAMPLE_END,
        "source": "canonical Vat init and file calls",
        "classifications": report["classifications"],
    }
    write_json_atomic(EVIDENCE_PATH, evidence)
    metadata = {
        "query_id": state["query_id"], "execution_id": execution_id,
        "sql_path": relative(SQL_PATH), "sql_sha256": sha256_file(SQL_PATH),
        "dimensions": [len(rows), len(expected_columns)],
        "raw_path": relative(RAW_PATH), "raw_size_bytes": RAW_PATH.stat().st_size,
        "raw_sha256": checksum, "status_request_count": status_count,
        "result_retrieval_count": 1, "retrieved_at_utc": utc_now_iso(),
    }
    write_json_atomic(METADATA_PATH, metadata)
    update_state(
        "complete", execution_state="COMPLETED", status_request_count=status_count,
        result_retrieval_count=1, raw_file_persisted=True,
        validation_passed=True, row_count=len(rows), column_count=len(expected_columns),
        raw_path=relative(RAW_PATH), raw_size_bytes=RAW_PATH.stat().st_size,
        raw_sha256=checksum, evidence_path=relative(EVIDENCE_PATH),
    )
    return report | metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("initialise")
    record = subparsers.add_parser("record-execution")
    record.add_argument("--query-id", type=int, required=True)
    record.add_argument("--query-url", required=True)
    record.add_argument("--execution-id", required=True)
    record.add_argument("--execution-state", required=True)
    subparsers.add_parser("retrieve")
    subparsers.add_parser("recover-local")
    args = parser.parse_args()
    if args.command == "initialise":
        print(json.dumps(initialise_state(), indent=2))
    elif args.command == "record-execution":
        print(json.dumps(record_execution(
            args.query_id, args.query_url, args.execution_id, args.execution_state,
        ), indent=2))
    elif args.command == "retrieve":
        api_key = os.environ.get("DUNE_API_KEY")
        if not api_key:
            raise ActivationDiagnosticError("DUNE_API_KEY is not set")
        print(json.dumps(retrieve_and_persist(api_key), indent=2))
    else:
        print(json.dumps(recover_preserved_diagnostic(), indent=2))


if __name__ == "__main__":
    main()
