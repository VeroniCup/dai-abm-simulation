"""Local persistence and validation for the Phase 1D Dune diagnostic.

This module deliberately has no Dune client or network code. The one authorised
MCP result is written to a payload file and then passed directly to the atomic
persistence path below.
"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
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
import re
from typing import Any


ROOT = REPOSITORY_ROOT
SQL_PATH = ROOT / "sql" / "dune_phase1d_eth_a_debt_ceiling_diagnostic.sql"
DIAGNOSTIC_DIR = (
    ROOT / "data" / "protocol" / "provenance" / "archive" / "diagnostic"
)
STATE_PATH = DIAGNOSTIC_DIR / "phase1d_eth_a_debt_ceiling_attempt2_state.json"
PAYLOAD_PATH = DIAGNOSTIC_DIR / ".phase1d_eth_a_debt_ceiling_attempt2.partial.json"
RAW_PATH = DIAGNOSTIC_DIR / "phase1d_eth_a_debt_ceiling_diagnostic.csv"
VALIDATION_PATH = DIAGNOSTIC_DIR / "phase1d_eth_a_debt_ceiling_attempt2_validation.json"
METADATA_PATH = DIAGNOSTIC_DIR / "phase1d_eth_a_debt_ceiling_attempt2_metadata.json"

EXPECTED_COLUMNS = (
    "ilk", "parameter", "parameter_key", "source_classification",
    "effective_time_utc", "call_block_number", "call_tx_index",
    "contract_address", "transaction_hash", "raw_value_rad", "value_dai",
    "previous_value_dai", "change_dai",
)
ETH_A_RAW = "0x4554482d41000000000000000000000000000000000000000000000000000000"
LINE_RAW = "0x6c696e6500000000000000000000000000000000000000000000000000000000"
EXPECTED_ROWS = 174
CANONICAL_VAT = "0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b"


class ProtocolDiagnosticError(RuntimeError):
    """Raised when the bounded diagnostic is structurally unsafe or invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provenance_path(path: Path) -> str:
    """Use repository-relative paths in production and explicit test paths elsewhere."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def validate_sql(sql: str) -> dict[str, Any]:
    lower = sql.lower()
    failures: list[str] = []
    required = (
        "maker_ethereum.vat_call_file",
        ETH_A_RAW,
        LINE_RAW,
        "2021-06-01 00:00:00",
        "2021-09-01 00:00:00",
        "pre_sample_initial_state",
        "in_sample_change",
        "array_join(",
        "transform(f.call_trace_address, x -> cast(x as varchar))",
        "cast(data as double) / 1e45",
    )
    for fragment in required:
        if fragment.lower() not in lower:
            failures.append(f"missing required SQL fragment: {fragment}")
    for forbidden in (
        "select *", "ethereum.transactions", "prices.",
        "cast(call_trace_address as varchar)",
    ):
        if forbidden in lower:
            failures.append(f"forbidden SQL fragment: {forbidden}")
    if lower.count("maker_ethereum.vat_call_file") != 2:
        failures.append("diagnostic must read Vat.file only in the initial-state and window branches")
    if lower.count("call_block_date") < 4:
        failures.append("both branches require partition-date bounds")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
    }


def initialise_state() -> dict[str, Any]:
    if STATE_PATH.exists() or RAW_PATH.exists() or PAYLOAD_PATH.exists():
        raise ProtocolDiagnosticError("Refusing to overwrite an existing Phase 1D diagnostic artefact.")
    report = validate_sql(SQL_PATH.read_text(encoding="utf-8"))
    if not report["validation_passed"]:
        raise ProtocolDiagnosticError("; ".join(report["failures"]))
    state = {
        "attempt": 2,
        "supersedes_failed_query_id": 8069228,
        "supersedes_failed_execution_id": "01KY4S1MW60ZPG9DTKMV2TJCT1",
        "state": "planned",
        "query_type": "private temporary diagnostic",
        "engine": "small",
        "sql_path": str(SQL_PATH.relative_to(ROOT)),
        "sql_sha256": report["sql_sha256"],
        "query_id": None,
        "execution_id": None,
        "result_retrieval_count": 0,
        "raw_file_persisted": False,
        "validation_passed": False,
        "expected_ilk": "ETH-A",
        "parameter": "debt_ceiling",
        "principal_start_utc": "2021-06-01T00:00:00Z",
        "principal_end_exclusive_utc": "2021-09-01T00:00:00Z",
    }
    write_json_atomic(STATE_PATH, state)
    return state


def update_state(status: str, **fields: Any) -> dict[str, Any]:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state.update(fields)
    state["state"] = status
    write_json_atomic(STATE_PATH, state)
    return state


def validate_rows(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, Any]:
    failures: list[str] = []
    if tuple(columns) != EXPECTED_COLUMNS:
        failures.append(f"unexpected columns: {columns}")
    if len(rows) != EXPECTED_ROWS:
        failures.append(f"expected {EXPECTED_ROWS} rows, found {len(rows)}")
    times: list[str] = []
    block_order: list[tuple[str, int, int, str]] = []
    pre_count = 0
    in_window_count = 0
    previous_value: Decimal | None = None
    source_keys: set[tuple[str, str, str, str]] = set()
    carry_forward_intervals: list[dict[str, Any]] = []
    converted_values: list[Decimal] = []
    exact_double_conversion_count = 0
    for index, row in enumerate(rows):
        if (
            row.get("ilk") != "ETH-A"
            or row.get("parameter") != "debt_ceiling"
            or row.get("parameter_key") != "line"
        ):
            failures.append(f"row {index} has an unexpected ilk, parameter or key")
        timestamp = str(row.get("effective_time_utc") or "")
        times.append(timestamp)
        classification = str(row.get("source_classification") or "")
        if classification not in {"pre_sample_initial_state", "in_sample_change"}:
            failures.append(f"row {index} has an invalid source classification")
        is_pre = classification == "pre_sample_initial_state"
        pre_count += int(is_pre)
        in_window_count += int(classification == "in_sample_change")
        if is_pre and timestamp >= "2021-06-01":
            failures.append("pre-window state is not before the principal window")
        if not is_pre and not ("2021-06-01" <= timestamp < "2021-09-01"):
            failures.append(f"in-window row outside diagnostic bounds: {timestamp}")
        raw = Decimal(str(row["raw_value_rad"]))
        value = Decimal(str(row["value_dai"]))
        converted_values.append(value)
        if raw < 0 or value < 0:
            failures.append(f"row {index} has a negative debt ceiling")
        expected = raw / (Decimal(10) ** 45)
        tolerance = max(Decimal("1e-9"), abs(expected) * Decimal("1e-12"))
        if abs(value - expected) > tolerance:
            failures.append(f"row {index} fails RAD-to-DAI conversion")
        if float(str(row["value_dai"])) == float(str(row["raw_value_rad"])) / 1e45:
            exact_double_conversion_count += 1
        else:
            failures.append(f"row {index} differs from Dune's exact double raw/1e45 expression")
        if previous_value is None:
            if str(row.get("previous_value_dai") or "").strip() not in {"", "None", "null"}:
                failures.append("first row must have no previous value")
        else:
            previous = Decimal(str(row["previous_value_dai"]))
            change = Decimal(str(row["change_dai"]))
            if abs(previous - previous_value) > tolerance:
                failures.append(f"row {index} has an incorrect previous value")
            if abs(change - (value - previous_value)) > tolerance:
                failures.append(f"row {index} has an incorrect change")
        previous_value = value
        if not re.fullmatch(r"0x[0-9A-Fa-f]{40}", str(row.get("contract_address") or "")):
            failures.append(f"row {index} has a malformed contract address")
        elif str(row["contract_address"]).lower() != CANONICAL_VAT:
            failures.append(f"row {index} has a non-canonical Vat contract")
        if not re.fullmatch(r"0x[0-9A-Fa-f]{64}", str(row.get("transaction_hash") or "")):
            failures.append(f"row {index} has a malformed transaction hash")
        source_key = (
            str(row.get("call_block_number")), str(row.get("call_tx_index")),
            str(row.get("transaction_hash")), str(row.get("raw_value_rad")),
        )
        if source_key in source_keys:
            failures.append(f"row {index} duplicates a governance change")
        source_keys.add(source_key)
        block_order.append((
            timestamp,
            int(row["call_block_number"]),
            int(row["call_tx_index"]) if str(row.get("call_tx_index") or "").strip() else -1,
            str(row["transaction_hash"]),
        ))
        for field in ("value_dai", "previous_value_dai", "change_dai"):
            value_text = str(row.get(field) or "")
            if value_text and not math.isfinite(float(value_text)):
                failures.append(f"row {index} has non-finite {field}")
    if pre_count != 1:
        failures.append(f"expected exactly one pre-window state, found {pre_count}")
    if in_window_count != EXPECTED_ROWS - 1:
        failures.append(
            f"expected {EXPECTED_ROWS - 1} in-window changes, found {in_window_count}"
        )
    if times != sorted(times) or len(times) != len(set(times)):
        failures.append("parameter changes are not strictly chronological")
    if block_order != sorted(block_order):
        failures.append("timestamp, block and transaction ordering is not deterministic")
    if rows:
        for index, row in enumerate(rows):
            carry_forward_intervals.append({
                "effective_start_utc": (
                    "2021-06-01T00:00:00Z" if index == 0
                    else str(row["effective_time_utc"])
                ),
                "effective_end_exclusive_utc": (
                    str(rows[index + 1]["effective_time_utc"])
                    if index + 1 < len(rows) else "2021-09-01T00:00:00Z"
                ),
                "debt_ceiling_dai": str(row["value_dai"]),
                "source_classification": str(row["source_classification"]),
            })
    if carry_forward_intervals:
        if carry_forward_intervals[0]["effective_start_utc"] != "2021-06-01T00:00:00Z":
            failures.append("carry-forward intervals do not start at the window boundary")
        if carry_forward_intervals[-1]["effective_end_exclusive_utc"] != "2021-09-01T00:00:00Z":
            failures.append("carry-forward intervals do not end at the window boundary")
        for index in range(len(carry_forward_intervals) - 1):
            if (
                carry_forward_intervals[index]["effective_end_exclusive_utc"]
                != carry_forward_intervals[index + 1]["effective_start_utc"]
            ):
                failures.append(f"carry-forward gap or overlap after interval {index}")
    in_window_rows = [
        row for row in rows if row.get("source_classification") == "in_sample_change"
    ]
    tied_order_groups = len(block_order) - len(
        {(block, tx_index) for _, block, tx_index, _ in block_order}
    )
    return {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(rows),
        "column_count": len(columns),
        "pre_window_state_count": pre_count,
        "in_window_change_count": len(rows) - pre_count,
        "validated_in_window_change_count": in_window_count,
        "minimum_timestamp_utc": min(times) if times else None,
        "maximum_timestamp_utc": max(times) if times else None,
        "unit_conversion": "debt_ceiling_dai = raw_value_rad / 1e45",
        "carry_forward_method": "latest setting at or before each requested timestamp",
        "carry_forward_intervals": carry_forward_intervals,
        "duplicate_governance_change_count": len(rows) - len(source_keys),
        "canonical_vat_contract": CANONICAL_VAT,
        "canonical_vat_contract_match_count": sum(
            str(row.get("contract_address") or "").lower() == CANONICAL_VAT
            for row in rows
        ),
        "exact_double_conversion_match_count": exact_double_conversion_count,
        "distinct_setting_count": len({str(row.get("raw_value_rad")) for row in rows}),
        "minimum_debt_ceiling_dai": str(min(converted_values)) if converted_values else None,
        "maximum_debt_ceiling_dai": str(max(converted_values)) if converted_values else None,
        "first_debt_ceiling_dai": str(converted_values[0]) if converted_values else None,
        "final_debt_ceiling_dai": str(converted_values[-1]) if converted_values else None,
        "pre_sample_value_dai": str(rows[0]["value_dai"]) if rows else None,
        "first_in_window_value_dai": (
            str(in_window_rows[0]["value_dai"]) if in_window_rows else None
        ),
        "final_in_window_value_dai": (
            str(in_window_rows[-1]["value_dai"]) if in_window_rows else None
        ),
        "equal_block_transaction_position_count": tied_order_groups,
        "deterministic_tie_ordering_method": (
            "serialised call trace address in Dune SQL; omitted from economic output"
        ),
        "forward_fill_interval_count": len(carry_forward_intervals),
        "forward_fill_coverage_complete": bool(carry_forward_intervals) and not any(
            "carry-forward" in failure for failure in failures
        ),
        "no_other_ilks_or_parameter_selectors": not any(
            "unexpected ilk" in failure for failure in failures
        ),
        "pre_sample_selection_rule": (
            "latest successful ETH-A Vat.file line call before 2021-06-01, "
            "ordered by block, transaction and serialised trace address"
        ),
        "pre_sample_latest_validated_from_sql_logic": pre_count == 1,
    }


def _unwrap(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    if isinstance(payload.get("structuredContent"), dict):
        payload = payload["structuredContent"]
    if payload.get("state") != "COMPLETED":
        raise ProtocolDiagnosticError(f"Execution is not complete: {payload.get('state')}")
    metadata = payload.get("resultMetadata") or {}
    rows = (payload.get("data") or {}).get("rows")
    columns = [item["name"] for item in metadata.get("columns", [])]
    if not isinstance(rows, list) or int(metadata.get("totalRowCount", -1)) != len(rows):
        raise ProtocolDiagnosticError("Dune payload row metadata is absent or inconsistent.")
    return rows, columns, metadata


def persist_payload() -> dict[str, Any]:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    rows, columns, result_metadata = _unwrap(payload)
    execution_id = payload.get("executionId") or payload.get("structuredContent", {}).get("executionId")
    if str(execution_id) != str(state.get("execution_id")):
        raise ProtocolDiagnosticError("Payload execution ID differs from the durable state.")
    report = validate_rows(rows, columns)
    if not report["validation_passed"]:
        raise ProtocolDiagnosticError("; ".join(report["failures"]))
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = RAW_PATH.with_name(f".{RAW_PATH.name}.partial")
    if RAW_PATH.exists() or temporary.exists():
        raise ProtocolDiagnosticError("Refusing to overwrite a raw or partial diagnostic file.")
    with temporary.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    with temporary.open("r", encoding="utf-8", newline="") as handle:
        persisted = list(csv.DictReader(handle))
    second_report = validate_rows(persisted, columns)
    if not second_report["validation_passed"] or len(persisted) != len(rows):
        raise ProtocolDiagnosticError("Persisted CSV failed structural validation.")
    checksum = sha256_file(temporary)
    os.replace(temporary, RAW_PATH)
    try:
        descriptor = os.open(RAW_PATH.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass
    report.update({
        "raw_path": provenance_path(RAW_PATH),
        "raw_sha256": checksum,
        "raw_size_bytes": RAW_PATH.stat().st_size,
        "sql_sha256": state["sql_sha256"],
        "query_id": state["query_id"],
        "execution_id": state["execution_id"],
        "execution_cost_credits": result_metadata.get("executionCostCredits"),
    })
    write_json_atomic(VALIDATION_PATH, report)
    metadata = {
        "phase": "1D",
        "attempt": 2,
        "status": "complete",
        "query_type": state["query_type"],
        "engine": state["engine"],
        "query_id": state["query_id"],
        "query_url": state.get("query_url"),
        "execution_id": state["execution_id"],
        "sql_path": state["sql_path"],
        "sql_sha256": state["sql_sha256"],
        "raw_path": provenance_path(RAW_PATH),
        "raw_sha256": checksum,
        "raw_size_bytes": RAW_PATH.stat().st_size,
        "row_count": len(rows),
        "column_count": len(columns),
        "execution_cost_credits": result_metadata.get("executionCostCredits"),
        "result_retrieval_count": 1,
        "supersedes_failed_query_id": state["supersedes_failed_query_id"],
        "supersedes_failed_execution_id": state["supersedes_failed_execution_id"],
    }
    write_json_atomic(METADATA_PATH, metadata)
    update_state(
        "complete", result_retrieval_count=1, raw_file_persisted=True,
        validation_passed=True, row_count=len(rows), column_count=len(columns),
        raw_path=provenance_path(RAW_PATH), raw_sha256=checksum,
        raw_size_bytes=RAW_PATH.stat().st_size,
        execution_cost_credits=result_metadata.get("executionCostCredits"),
        validation_path=provenance_path(VALIDATION_PATH),
        metadata_path=provenance_path(METADATA_PATH),
    )
    PAYLOAD_PATH.unlink()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "initialise", "persist"))
    args = parser.parse_args()
    if args.command == "preflight":
        print(json.dumps(validate_sql(SQL_PATH.read_text(encoding="utf-8")), indent=2))
    elif args.command == "initialise":
        print(json.dumps(initialise_state(), indent=2))
    else:
        print(json.dumps(persist_payload(), indent=2))


if __name__ == "__main__":
    main()
