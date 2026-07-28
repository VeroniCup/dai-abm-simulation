"""Persist and validate the bounded Phase 1C Dune liquidation diagnostic.

Dune MCP owns query creation, execution and the single result retrieval.  This
module owns deterministic SQL checks, durable identifiers, atomic filesystem
persistence and local diagnostic validation.  It has no network or stdin path.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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
from typing import Any, Iterable


PROJECT_ROOT = REPOSITORY_ROOT
DEFAULT_SQL = (
    PROJECT_ROOT
    / "sql"
    / "liquidations"
    / "generated"
    / "history"
    / "liquidation_diagnostic.sql"
)
DEFAULT_DIR = (
    PROJECT_ROOT / "data" / "liquidations" / "provenance" / "archive" / "diagnostic"
)
ORIGINAL_FAILED_STATE = DEFAULT_DIR / "phase1c_liquidation_diagnostic_metadata.json"
ORIGINAL_FAILED_PAYLOAD = DEFAULT_DIR / ".phase1c_liquidation_diagnostic.partial.json"
DEFAULT_STATE = DEFAULT_DIR / "phase1c_liquidation_diagnostic_replacement_metadata.json"
DEFAULT_PAYLOAD = DEFAULT_DIR / ".phase1c_liquidation_diagnostic_replacement.partial.json"
DEFAULT_RAW = DEFAULT_DIR / "phase1c_liquidation_actions_diagnostic.csv"
DEFAULT_VALIDATION = (
    DEFAULT_DIR / "phase1c_liquidation_diagnostic_validation.json"
)

EXPECTED_ILKS = ("ETH-A", "ETH-B", "ETH-C", "WBTC-A", "WBTC-B", "WBTC-C")
EXPECTED_ACTION_TYPES = {
    "bark",
    "kick",
    "take_success",
    "take_failed_call",
    "redo_success",
    "redo_failed_call",
    "yank",
}
WAD = Decimal(10) ** 18
RAY = Decimal(10) ** 27
RAD = Decimal(10) ** 45

# ABI-derived locally with the Keccak implementation below and checked against
# the empty-string Ethereum Keccak-256 vector in the test suite.
YANK_SIGNATURE = "Yank(uint256)"
YANK_TOPIC0 = "0x2c5d2826eb5903b8fc201cf48094b858f42f61c7eaac9aaf43ebed490138144e"

REQUIRED_COLUMNS = {
    "initiation_window_label",
    "ilk",
    "dog_contract",
    "clipper_contract",
    "auction_id",
    "transaction_hash",
    "block_number",
    "block_timestamp",
    "transaction_index",
    "event_index",
    "call_trace_address",
    "action_type",
    "source_table",
    "record_kind",
    "decoded_call_success",
    "event_to_call_linkage_flag",
    "vault_or_urn",
    "bark_keeper",
    "kick_keeper",
    "transaction_sender",
    "call_sender",
    "take_who",
    "take_usr",
    "redo_keeper",
    "bark_ink_raw",
    "bark_art_raw",
    "bark_due_raw",
    "kick_top_raw",
    "kick_tab_raw",
    "kick_lot_raw",
    "kick_coin_raw",
    "take_price_raw",
    "take_owe_raw",
    "take_remaining_tab_raw",
    "take_remaining_lot_raw",
    "redo_top_raw",
    "redo_tab_raw",
    "redo_lot_raw",
    "redo_coin_raw",
    "collateral_wad_units",
    "debt_or_payment_dai",
    "price_dai_per_collateral",
    "top_level_transaction_recipient",
    "top_level_transaction_success",
    "gas_limit",
    "gas_used",
    "effective_gas_price_wei",
    "effective_gas_price_gwei",
    "max_fee_per_gas",
    "max_priority_fee_per_gas",
    "actual_priority_fee_per_gas",
    "transaction_block_timestamp",
    "maker_liquidation_action_count_in_tx",
    "distinct_auctions_in_tx",
    "multi_auction_transaction",
    "auction_initiated_before_window",
    "action_in_principal_window",
    "action_in_bounded_horizon",
    "legacy_cat_bite_count",
    "legacy_flipper_activity_count",
}

LIVE_SCHEMA_COLUMNS = {
    "maker_ethereum.dog_evt_bark": {
        "contract_address", "evt_tx_hash", "evt_tx_from", "evt_tx_to",
        "evt_tx_index", "evt_index", "evt_block_time", "evt_block_number",
        "evt_block_date", "art", "clip", "due", "id", "ilk", "ink", "urn",
    },
    "maker_ethereum.dog_call_bark": {
        "contract_address", "call_success", "call_tx_hash", "call_tx_from",
        "call_tx_to", "call_tx_index", "call_trace_address", "call_block_time",
        "call_block_number", "call_block_date", "ilk", "kpr", "output_id", "urn",
    },
    "maker_ethereum.clipper_evt_kick": {
        "contract_address", "evt_tx_hash", "evt_tx_from", "evt_tx_to",
        "evt_tx_index", "evt_index", "evt_block_time", "evt_block_number",
        "evt_block_date", "coin", "id", "kpr", "lot", "tab", "top", "usr",
    },
    "maker_ethereum.clipper_call_kick": {
        "contract_address", "call_success", "call_tx_hash", "call_tx_from",
        "call_tx_to", "call_tx_index", "call_trace_address", "call_block_time",
        "call_block_number", "call_block_date", "kpr", "lot", "output_id", "tab", "usr",
    },
    "maker_ethereum.clipper_evt_take": {
        "contract_address", "evt_tx_hash", "evt_tx_from", "evt_tx_to",
        "evt_tx_index", "evt_index", "evt_block_time", "evt_block_number",
        "evt_block_date", "id", "lot", "max", "owe", "price", "tab", "usr",
    },
    "maker_ethereum.clipper_call_take": {
        "contract_address", "call_success", "call_tx_hash", "call_tx_from",
        "call_tx_to", "call_tx_index", "call_trace_address", "call_block_time",
        "call_block_number", "call_block_date", "amt", "data", "id", "max", "who",
    },
    "maker_ethereum.clipper_evt_redo": {
        "contract_address", "evt_tx_hash", "evt_tx_from", "evt_tx_to",
        "evt_tx_index", "evt_index", "evt_block_time", "evt_block_number",
        "evt_block_date", "coin", "id", "kpr", "lot", "tab", "top", "usr",
    },
    "maker_ethereum.clipper_call_redo": {
        "contract_address", "call_success", "call_tx_hash", "call_tx_from",
        "call_tx_to", "call_tx_index", "call_trace_address", "call_block_time",
        "call_block_number", "call_block_date", "id", "kpr",
    },
    "ethereum.transactions": {
        "hash", "from", "to", "success", "gas_limit", "gas_used", "gas_price",
        "max_fee_per_gas", "max_priority_fee_per_gas", "priority_fee_per_gas",
        "block_time", "block_date",
    },
}

BASE_CTE_AUDIT = {
    "bark_events_extended": ("b", "maker_ethereum.dog_evt_bark"),
    "kick_events_extended": ("k", "maker_ethereum.clipper_evt_kick"),
    "take_events_extended": ("t", "maker_ethereum.clipper_evt_take"),
    "take_calls_extended": ("c", "maker_ethereum.clipper_call_take"),
    "redo_events_extended": ("r", "maker_ethereum.clipper_evt_redo"),
    "redo_calls_extended": ("c", "maker_ethereum.clipper_call_redo"),
    "bark_calls": ("c", "maker_ethereum.dog_call_bark"),
    "kick_calls": ("c", "maker_ethereum.clipper_call_kick"),
    "transactions": ("t", "ethereum.transactions"),
}

COLUMN_LINEAGE_CHECKLIST = (
    {"output": "initiation_window_label", "source": "windows", "alias": "w", "column": "window_label", "renamed": True, "downstream": "auction_context, selected_context, actions"},
    {"output": "dog_contract", "source": "maker_ethereum.dog_evt_bark", "alias": "b", "column": "contract_address", "renamed": True, "downstream": "auction_context, actions"},
    {"output": "clipper_contract", "source": "maker_ethereum.dog_evt_bark", "alias": "b", "column": "clip", "renamed": True, "downstream": "auction key, actions"},
    {"output": "clipper_contract", "source": "maker_ethereum.clipper_evt_kick", "alias": "k", "column": "contract_address", "renamed": True, "downstream": "Bark-Kick linkage"},
    {"output": "clipper_contract", "source": "maker_ethereum.clipper_call_kick", "alias": "c", "column": "contract_address", "renamed": True, "downstream": "kick call actions"},
    {"output": "auction_id", "source": "maker_ethereum.dog_evt_bark", "alias": "b", "column": "id", "renamed": True, "downstream": "durable auction key"},
    {"output": "transaction_hash", "source": "decoded events", "alias": "b/k/t/r", "column": "evt_tx_hash", "renamed": True, "downstream": "event linkage and transactions"},
    {"output": "transaction_hash", "source": "decoded calls", "alias": "c", "column": "call_tx_hash", "renamed": True, "downstream": "call linkage and transactions"},
    {"output": "block_timestamp", "source": "decoded events", "alias": "b/k/t/r", "column": "evt_block_time", "renamed": True, "downstream": "window flags and ordering"},
    {"output": "event_index", "source": "decoded events", "alias": "b/k/t/r", "column": "evt_index", "renamed": True, "downstream": "event ordering"},
    {"output": "call_trace_address", "source": "decoded calls", "alias": "c", "column": "call_trace_address", "renamed": False, "downstream": "call ordering"},
    {"output": "decoded_call_success", "source": "decoded calls", "alias": "c", "column": "call_success", "renamed": True, "downstream": "failed-call separation"},
    {"output": "ilk", "source": "ilk_filter", "alias": "f", "column": "ilk", "renamed": False, "downstream": "all diagnostic actions"},
    {"output": "raw/scaled economics", "source": "Bark/Kick/Take/Redo", "alias": "a/k/t/r", "column": "ink/art/due/top/tab/lot/coin/price/owe", "renamed": True, "downstream": "diagnostic validation"},
)


class LiquidationDiagnosticError(RuntimeError):
    """Raised when an authorised diagnostic invariant fails."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def provenance_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _extract_cte_body(sql: str, cte_name: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(cte_name)}\s+AS\s*\(", sql)
    if not match:
        raise LiquidationDiagnosticError(f"CTE {cte_name!r} is absent.")
    start = match.end()
    depth = 1
    quote: str | None = None
    index = start
    while index < len(sql):
        char = sql[index]
        if quote:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return sql[start:index]
        index += 1
    raise LiquidationDiagnosticError(f"CTE {cte_name!r} has unbalanced parentheses.")


def _split_top_level(text: str, delimiter: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    start = 0
    index = 0
    upper = text.upper()
    token = delimiter.upper()
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and upper.startswith(token, index):
            parts.append(text[start:index].strip())
            index += len(token)
            start = index
            continue
        index += 1
    parts.append(text[start:].strip())
    return parts


def _select_expression_count(branch: str) -> int:
    select_match = re.search(r"(?is)\bSELECT\b", branch)
    if not select_match:
        raise LiquidationDiagnosticError("UNION branch has no SELECT.")
    tail = branch[select_match.end():]
    from_parts = _split_top_level(tail, "FROM")
    if len(from_parts) < 2:
        raise LiquidationDiagnosticError("UNION branch has no top-level FROM.")
    expressions = _split_top_level(from_parts[0], ",")
    return len(expressions)


def audit_sql_lineage(sql: str) -> dict[str, Any]:
    """Perform targeted static checks for the Phase 1C query's live lineage."""
    failures: list[str] = []
    references: dict[str, list[str]] = {}
    for cte_name, (alias, table) in BASE_CTE_AUDIT.items():
        try:
            body = _extract_cte_body(sql, cte_name)
        except LiquidationDiagnosticError as exc:
            failures.append(str(exc))
            continue
        used = sorted(set(re.findall(rf"\b{re.escape(alias)}\.([A-Za-z_][A-Za-z0-9_]*)", body)))
        references[cte_name] = used
        unknown = sorted(set(used).difference(LIVE_SCHEMA_COLUMNS[table]))
        if unknown:
            failures.append(f"{cte_name} uses non-live {alias} columns: {unknown}")

    try:
        kick_body = _extract_cte_body(sql, "kick_calls")
        if re.search(r"\bc\.window_label\b", kick_body):
            failures.append("kick_calls incorrectly uses c.window_label")
        if re.search(r"\bc\.clipper_contract\b", kick_body):
            failures.append("kick_calls incorrectly uses c.clipper_contract")
        if not re.search(r"\bw\.window_label\s+AS\s+initiation_window_label\b", kick_body, re.I):
            failures.append("kick_calls does not derive initiation_window_label from windows alias w")
        if not re.search(r"\bc\.contract_address\s+AS\s+clipper_contract\b", kick_body, re.I):
            failures.append("kick_calls does not rename live contract_address to clipper_contract")
    except LiquidationDiagnosticError as exc:
        failures.append(str(exc))

    try:
        raw_actions = _extract_cte_body(sql, "raw_actions")
        branches = _split_top_level(raw_actions, "UNION ALL")
        counts = [_select_expression_count(branch) for branch in branches]
        if len(branches) != 9:
            failures.append(f"raw_actions has {len(branches)} UNION branches, expected 9")
        if len(set(counts)) != 1:
            failures.append(f"raw_actions UNION column counts differ: {counts}")
    except LiquidationDiagnosticError as exc:
        branches = []
        counts = []
        failures.append(str(exc))

    decoded_alias_errors = sorted(set(re.findall(
        r"\b[bc ktr]\.clipper_contract\b".replace(" ", ""), sql
    )))
    # The concrete source-table errors are checked per CTE above; retain the
    # count for the audit report without treating valid upstream aliases as bad.
    return {
        "validation_passed": not failures,
        "failures": failures,
        "base_cte_live_column_references": references,
        "raw_action_branch_count": len(branches),
        "raw_action_branch_column_counts": counts,
        "lineage_checklist": list(COLUMN_LINEAGE_CHECKLIST),
        "clipper_contract_reference_count": len(decoded_alias_errors),
    }


def validate_sql(sql: str) -> dict[str, Any]:
    """Validate the immutable scope before a query is sent to Dune."""
    failures: list[str] = []
    upper = sql.upper()
    for ilk in EXPECTED_ILKS:
        if sql.count(f"'{ilk}'") != 1:
            failures.append(f"ilk {ilk} must appear exactly once")
    for forbidden in ("SELECT *",):
        if forbidden in upper:
            failures.append(f"forbidden SQL fragment: {forbidden}")
    required_bounds = (
        "2023-02-01 00:00:00",
        "2023-02-03 00:00:00",
        "2022-06-13 00:00:00",
        "2022-06-15 00:00:00",
    )
    for bound in required_bounds:
        if bound not in sql:
            failures.append(f"missing requested bound {bound}")
    if YANK_TOPIC0.lower() not in sql.lower():
        failures.append("verified Yank topic is absent")
    for table in (
        "maker_ethereum.dog_evt_bark",
        "maker_ethereum.dog_call_bark",
        "maker_ethereum.clipper_evt_kick",
        "maker_ethereum.clipper_call_kick",
        "maker_ethereum.clipper_evt_take",
        "maker_ethereum.clipper_call_take",
        "maker_ethereum.clipper_evt_redo",
        "maker_ethereum.clipper_call_redo",
        "ethereum.transactions",
        "ethereum.logs",
        "maker_ethereum.cat_evt_bite",
    ):
        if table not in sql:
            failures.append(f"missing required source {table}")
    if "ethereum.traces" in sql:
        failures.append("ethereum.traces is not authorised for this diagnostic")
    lineage = audit_sql_lineage(sql)
    failures.extend(lineage["failures"])
    return {
        "validation_passed": not failures,
        "failures": failures,
        "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "lineage": lineage,
    }


# Keccak-f[1600] constants.  Ethereum uses Keccak padding (0x01), not the
# standardised SHA3 padding (0x06).
_ROTATION = (
    0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43, 25, 39,
    41, 45, 15, 21, 8, 18, 2, 61, 56, 14,
)
_ROUND_CONSTANTS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)
_MASK64 = (1 << 64) - 1


def _rotate_left(value: int, shift: int) -> int:
    if shift == 0:
        return value & _MASK64
    return ((value << shift) | (value >> (64 - shift))) & _MASK64


def _keccak_f1600(state: list[int]) -> None:
    for round_constant in _ROUND_CONSTANTS:
        c = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotate_left(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= d[x]
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                destination_x = y
                destination_y = (2 * x + 3 * y) % 5
                b[destination_x + 5 * destination_y] = _rotate_left(
                    state[x + 5 * y], _ROTATION[x + 5 * y]
                )
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = b[x + 5 * y] ^ (
                    (~b[(x + 1) % 5 + 5 * y]) & b[(x + 2) % 5 + 5 * y]
                )
        state[0] ^= round_constant


def keccak256(payload: bytes) -> bytes:
    rate = 136
    padded = bytearray(payload)
    padded.append(0x01)
    while len(padded) % rate != rate - 1:
        padded.append(0)
    padded.append(0x80)
    state = [0] * 25
    for offset in range(0, len(padded), rate):
        block = padded[offset : offset + rate]
        for index in range(rate // 8):
            state[index] ^= int.from_bytes(block[8 * index : 8 * index + 8], "little")
        _keccak_f1600(state)
    return b"".join(value.to_bytes(8, "little") for value in state)[:32]


def verify_yank_topic() -> str:
    empty_vector = keccak256(b"").hex()
    if empty_vector != "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470":
        raise LiquidationDiagnosticError("Local Keccak implementation failed its known vector.")
    derived = "0x" + keccak256(YANK_SIGNATURE.encode("ascii")).hex()
    if derived.lower() != YANK_TOPIC0.lower():
        raise LiquidationDiagnosticError(
            f"Yank topic constant {YANK_TOPIC0} differs from ABI-derived {derived}."
        )
    return derived


def decimal_value(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise LiquidationDiagnosticError(f"Non-numeric Maker value: {value!r}.") from exc


def scale_maker(value: Any, unit: Decimal) -> Decimal | None:
    parsed = decimal_value(value)
    return None if parsed is None else parsed / unit


def auction_key(row: dict[str, Any]) -> tuple[str, str] | None:
    clip = str(row.get("clipper_contract") or "").lower()
    auction_id = str(row.get("auction_id") or "")
    return (clip, auction_id) if clip and auction_id else None


def detect_orphans(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    rows = list(rows)
    auctions = {
        auction_key(row)
        for row in rows
        if row.get("action_type") in {"bark", "kick"} and row.get("record_kind") == "event"
    }
    result = {"take": 0, "redo": 0, "yank": 0}
    for row in rows:
        action = str(row.get("action_type") or "")
        family = "take" if action.startswith("take_") else "redo" if action.startswith("redo_") else action
        if family in result and auction_key(row) not in auctions:
            result[family] += 1
    return result


def reconcile_bark_kick(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    rows = list(rows)
    barks = [r for r in rows if r.get("action_type") == "bark" and r.get("record_kind") == "event"]
    kicks = [r for r in rows if r.get("action_type") == "kick" and r.get("record_kind") == "event"]
    counts: list[int] = []
    for bark in barks:
        counts.append(sum(
            1 for kick in kicks
            if auction_key(kick) == auction_key(bark)
            and kick.get("transaction_hash") == bark.get("transaction_hash")
        ))
    return {
        "matched": sum(count == 1 for count in counts),
        "unmatched": sum(count == 0 for count in counts),
        "multiply_matched": sum(count > 1 for count in counts),
    }


def classify_terminals(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], str]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = auction_key(row)
        if key is not None:
            grouped.setdefault(key, []).append(row)
    classifications: dict[tuple[str, str], str] = {}
    for key, actions in grouped.items():
        if any(action.get("action_type") == "yank" for action in actions):
            classifications[key] = "cancelled"
            continue
        takes = [
            action for action in actions
            if action.get("action_type") == "take_success"
            and action.get("record_kind") == "event"
        ]
        takes.sort(key=lambda row: (
            int(row.get("block_number") or 0),
            int(row.get("transaction_index") or 0),
            int(row.get("event_index") or 0),
        ))
        if not takes:
            classifications[key] = "open_or_unresolved"
            continue
        final = takes[-1]
        tab = decimal_value(final.get("take_remaining_tab_raw"))
        lot = decimal_value(final.get("take_remaining_lot_raw"))
        if tab == 0:
            classifications[key] = "target_cleared"
        elif lot == 0 and tab is not None and tab > 0:
            classifications[key] = "collateral_exhausted"
        else:
            classifications[key] = "open_or_unresolved"
    return classifications


def validate_partial_takes(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("action_type") == "take_success" and row.get("record_kind") == "event":
            key = auction_key(row)
            if key is not None:
                grouped.setdefault(key, []).append(row)
    violations = 0
    discrepancies: list[dict[str, Any]] = []
    multiple = 0
    for key, takes in grouped.items():
        takes.sort(key=lambda row: (
            int(row.get("block_number") or 0),
            int(row.get("transaction_index") or 0),
            int(row.get("event_index") or 0),
        ))
        if len(takes) > 1:
            multiple += 1
        for previous, current in zip(takes, takes[1:]):
            previous_tab = decimal_value(previous.get("take_remaining_tab_raw"))
            current_tab = decimal_value(current.get("take_remaining_tab_raw"))
            previous_lot = decimal_value(previous.get("take_remaining_lot_raw"))
            current_lot = decimal_value(current.get("take_remaining_lot_raw"))
            if None in (previous_tab, current_tab, previous_lot, current_lot):
                continue
            if current_tab > previous_tab or current_lot > previous_lot:
                violations += 1
            price = scale_maker(current.get("take_price_raw"), RAY)
            owe = scale_maker(current.get("take_owe_raw"), RAD)
            lot_delta = (previous_lot - current_lot) / WAD
            if price and owe is not None:
                formula = owe / price
                absolute = abs(lot_delta - formula)
                relative = absolute / abs(formula) if formula else None
                discrepancies.append({
                    "clipper_contract": key[0],
                    "auction_id": key[1],
                    "transaction_hash": current.get("transaction_hash"),
                    "absolute_discrepancy": float(absolute),
                    "relative_discrepancy": float(relative) if relative is not None else None,
                })
    return {
        "auctions_with_multiple_takes": multiple,
        "non_monotonic_take_count": violations,
        "comparison_count": len(discrepancies),
        "maximum_absolute_discrepancy": max((d["absolute_discrepancy"] for d in discrepancies), default=0.0),
        "maximum_relative_discrepancy": max((d["relative_discrepancy"] or 0.0 for d in discrepancies), default=0.0),
        "discrepancies": discrepancies,
    }


def detect_multi_auction_transactions(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    by_tx: dict[str, set[tuple[str, str]]] = {}
    for row in rows:
        tx_hash = str(row.get("transaction_hash") or "")
        key = auction_key(row)
        if tx_hash and key is not None:
            by_tx.setdefault(tx_hash, set()).add(key)
    multi = {tx: keys for tx, keys in by_tx.items() if len(keys) > 1}
    return {
        "unique_transaction_count": len(by_tx),
        "multi_auction_transaction_count": len(multi),
        "multi_auction_transaction_hashes": sorted(multi),
    }


def _summary_stats(values: Iterable[Any]) -> dict[str, float | int | None]:
    parsed = sorted(float(value) for item in values if (value := decimal_value(item)) is not None)
    if not parsed:
        return {"count": 0, "minimum": None, "median": None, "maximum": None}
    middle = len(parsed) // 2
    median = parsed[middle] if len(parsed) % 2 else (parsed[middle - 1] + parsed[middle]) / 2
    return {"count": len(parsed), "minimum": parsed[0], "median": median, "maximum": parsed[-1]}


def validate_rows(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, Any]:
    failures: list[str] = []
    missing_columns = sorted(REQUIRED_COLUMNS.difference(columns))
    if missing_columns:
        failures.append(f"missing required columns: {missing_columns}")
    unexpected_ilks = sorted({str(r.get("ilk")) for r in rows if r.get("ilk") not in EXPECTED_ILKS})
    if unexpected_ilks:
        failures.append(f"unexpected ilks: {unexpected_ilks}")
    unexpected_actions = sorted({str(r.get("action_type")) for r in rows if r.get("action_type") not in EXPECTED_ACTION_TYPES})
    if unexpected_actions:
        failures.append(f"unexpected action types: {unexpected_actions}")

    event_keys: set[tuple[Any, ...]] = set()
    call_keys: set[tuple[Any, ...]] = set()
    duplicate_events = 0
    duplicate_calls = 0
    for row in rows:
        if row.get("record_kind") == "event":
            key = (row.get("source_table"), row.get("clipper_contract") or row.get("dog_contract"), row.get("transaction_hash"), row.get("event_index"))
            duplicate_events += int(key in event_keys)
            event_keys.add(key)
        elif row.get("record_kind") == "call":
            key = (row.get("source_table"), row.get("clipper_contract") or row.get("dog_contract"), row.get("transaction_hash"), row.get("call_trace_address"))
            duplicate_calls += int(key in call_keys)
            call_keys.add(key)
    if duplicate_events:
        failures.append(f"{duplicate_events} duplicate decoded event rows")
    if duplicate_calls:
        failures.append(f"{duplicate_calls} duplicate decoded call rows")

    unlinked_successful_events = sum(
        1 for row in rows
        if row.get("record_kind") == "event"
        and row.get("action_type") != "yank"
        and str(row.get("event_to_call_linkage_flag")).lower() not in {"true", "1"}
    )
    unlinked_successful_calls = sum(
        1 for row in rows
        if row.get("record_kind") == "call"
        and str(row.get("decoded_call_success")).lower() in {"true", "1"}
        and str(row.get("event_to_call_linkage_flag")).lower() not in {"true", "1"}
    )
    if unlinked_successful_events or unlinked_successful_calls:
        failures.append(
            "successful event/call reconciliation failed: "
            f"events={unlinked_successful_events}, calls={unlinked_successful_calls}"
        )

    bark_kick = reconcile_bark_kick(rows)
    if bark_kick["unmatched"] or bark_kick["multiply_matched"]:
        failures.append(f"Bark-Kick linkage failed: {bark_kick}")
    orphans = detect_orphans(rows)
    if any(orphans.values()):
        failures.append(f"orphan actions found: {orphans}")

    raw_scale_checks = {
        "bark_ink_wad": _summary_stats(scale_maker(r.get("bark_ink_raw"), WAD) for r in rows),
        "bark_art_wad": _summary_stats(scale_maker(r.get("bark_art_raw"), WAD) for r in rows),
        "bark_due_dai": _summary_stats(scale_maker(r.get("bark_due_raw"), RAD) for r in rows),
        "kick_tab_dai": _summary_stats(scale_maker(r.get("kick_tab_raw"), RAD) for r in rows),
        "kick_lot_wad": _summary_stats(scale_maker(r.get("kick_lot_raw"), WAD) for r in rows),
        "kick_top_ray": _summary_stats(scale_maker(r.get("kick_top_raw"), RAY) for r in rows),
        "take_owe_dai": _summary_stats(scale_maker(r.get("take_owe_raw"), RAD) for r in rows),
        "take_price_ray": _summary_stats(scale_maker(r.get("take_price_raw"), RAY) for r in rows),
        "redo_coin_dai": _summary_stats(scale_maker(r.get("redo_coin_raw"), RAD) for r in rows),
    }
    scaling_violations = 0
    for row in rows:
        expected: tuple[Decimal | None, Decimal | None, Decimal | None]
        action = str(row.get("action_type") or "")
        kind = str(row.get("record_kind") or "")
        if action == "bark" and kind == "event":
            expected = (
                scale_maker(row.get("bark_ink_raw"), WAD),
                scale_maker(row.get("bark_due_raw"), RAD),
                None,
            )
        elif action == "kick" and kind in {"event", "call"}:
            expected = (
                scale_maker(row.get("kick_lot_raw"), WAD),
                scale_maker(row.get("kick_tab_raw"), RAD),
                scale_maker(row.get("kick_top_raw"), RAY),
            )
        elif action == "take_success" and kind == "event":
            expected = (
                scale_maker(row.get("take_remaining_lot_raw"), WAD),
                scale_maker(row.get("take_owe_raw"), RAD),
                scale_maker(row.get("take_price_raw"), RAY),
            )
        elif action == "redo_success" and kind == "event":
            expected = (
                scale_maker(row.get("redo_lot_raw"), WAD),
                scale_maker(row.get("redo_tab_raw"), RAD),
                scale_maker(row.get("redo_top_raw"), RAY),
            )
        else:
            continue
        observed = (
            decimal_value(row.get("collateral_wad_units")),
            decimal_value(row.get("debt_or_payment_dai")),
            decimal_value(row.get("price_dai_per_collateral")),
        )
        for expected_value, observed_value in zip(expected, observed):
            if expected_value is None and observed_value is None:
                continue
            if expected_value is None or observed_value is None:
                scaling_violations += 1
                continue
            tolerance = max(abs(expected_value) * Decimal("1e-12"), Decimal("1e-12"))
            scaling_violations += int(abs(expected_value - observed_value) > tolerance)
    if scaling_violations:
        failures.append(f"{scaling_violations} raw-to-scaled Maker unit mismatches")
    partial = validate_partial_takes(rows)
    if partial["non_monotonic_take_count"]:
        failures.append("remaining Take tab or lot increased")
    terminals = classify_terminals(rows)
    terminal_counts: dict[str, int] = {}
    for value in terminals.values():
        terminal_counts[value] = terminal_counts.get(value, 0) + 1

    action_counts: dict[str, int] = {}
    ilk_counts: dict[str, int] = {}
    window_counts: dict[str, int] = {}
    for row in rows:
        action = str(row.get("action_type"))
        action_counts[action] = action_counts.get(action, 0) + 1
        ilk = str(row.get("ilk"))
        ilk_counts[ilk] = ilk_counts.get(ilk, 0) + 1
        window = str(row.get("initiation_window_label"))
        window_counts[window] = window_counts.get(window, 0) + 1

    legacy_cat = max((int(r.get("legacy_cat_bite_count") or 0) for r in rows), default=0)
    legacy_flip = max((int(r.get("legacy_flipper_activity_count") or 0) for r in rows), default=0)
    if legacy_cat or legacy_flip:
        failures.append(f"legacy activity is non-zero: cat={legacy_cat}, flipper={legacy_flip}")

    gas_by_action = {
        action: {
            "gas_used": _summary_stats(r.get("gas_used") for r in rows if r.get("action_type") == action),
            "effective_gas_price_gwei": _summary_stats(r.get("effective_gas_price_gwei") for r in rows if r.get("action_type") == action),
        }
        for action in sorted(action_counts)
    }
    batching = detect_multi_auction_transactions(rows)
    return {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(rows),
        "column_count": len(columns),
        "action_counts": action_counts,
        "counts_by_ilk": ilk_counts,
        "counts_by_window": window_counts,
        "unique_auction_count": len({auction_key(r) for r in rows if auction_key(r) is not None}),
        "duplicate_event_count": duplicate_events,
        "duplicate_call_count": duplicate_calls,
        "unlinked_successful_event_count": unlinked_successful_events,
        "unlinked_successful_call_count": unlinked_successful_calls,
        "bark_kick_linkage": bark_kick,
        "orphan_counts": orphans,
        "partial_take_checks": partial,
        "terminal_classification_counts": terminal_counts,
        "multi_auction_transactions": batching,
        "gas_distributions_by_action": gas_by_action,
        "unit_scale_ranges": raw_scale_checks,
        "unit_scaling_violation_count": scaling_violations,
        "legacy_cat_bite_count": legacy_cat,
        "legacy_flipper_activity_count": legacy_flip,
    }


def initialise_state(state_path: Path, sql_path: Path) -> dict[str, Any]:
    if state_path.exists():
        raise LiquidationDiagnosticError(f"Refusing to replace existing state: {state_path}.")
    sql = sql_path.read_text(encoding="utf-8")
    sql_report = validate_sql(sql)
    if not sql_report["validation_passed"]:
        raise LiquidationDiagnosticError("; ".join(sql_report["failures"]))
    payload = {
        "state": "planned",
        "query_type": "private temporary diagnostic",
        "engine": "small",
        "sql_path": provenance_path(sql_path),
        "sql_sha256": sql_report["sql_sha256"],
        "query_id": None,
        "query_url": None,
        "execution_id": None,
        "result_retrieved": False,
        "raw_file_persisted": False,
        "validation_passed": False,
        "retrieval_count": 0,
        "created_at_utc": utc_now_iso(),
    }
    write_json_atomic(state_path, payload)
    return payload


def update_state(state_path: Path, state: str, **fields: Any) -> dict[str, Any]:
    payload = load_json(state_path)
    payload.update(fields)
    payload["state"] = state
    payload["updated_at_utc"] = utc_now_iso()
    write_json_atomic(state_path, payload)
    return payload


def _unwrap_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    if "structuredContent" in payload and isinstance(payload["structuredContent"], dict):
        payload = payload["structuredContent"]
    if payload.get("state") != "COMPLETED":
        raise LiquidationDiagnosticError(f"Execution is not complete: {payload.get('state')!r}.")
    rows = payload.get("data", {}).get("rows")
    metadata = payload.get("resultMetadata", {})
    columns = [item["name"] for item in metadata.get("columns", [])]
    if not isinstance(rows, list) or not columns:
        raise LiquidationDiagnosticError("Result payload has no rows or column metadata.")
    if metadata.get("totalRowCount") != len(rows):
        raise LiquidationDiagnosticError("Retrieved row count differs from result metadata.")
    return payload, rows, columns


def persist_result(
    *,
    payload_path: Path = DEFAULT_PAYLOAD,
    state_path: Path = DEFAULT_STATE,
    raw_path: Path = DEFAULT_RAW,
    validation_path: Path = DEFAULT_VALIDATION,
) -> dict[str, Any]:
    """Persist one already-retrieved MCP result without stdin or a TTY."""
    state = load_json(state_path)
    try:
        payload, rows, columns = _unwrap_payload(load_json(payload_path))
        if str(payload.get("executionId")) != str(state.get("execution_id")):
            raise LiquidationDiagnosticError("Execution ID differs from durable state.")
        update_state(
            state_path,
            "result_retrieved",
            result_retrieved=True,
            retrieval_count=1,
            result_retrieved_at_utc=utc_now_iso(),
            execution_cost_credits=payload.get("resultMetadata", {}).get("executionCostCredits"),
        )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = raw_path.with_name("." + raw_path.name + ".partial")
        if raw_path.exists() or temporary.exists():
            raise LiquidationDiagnosticError("Refusing to overwrite a raw or partial diagnostic file.")
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        with temporary.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            parsed_rows = list(reader)
            if list(reader.fieldnames or []) != columns:
                raise LiquidationDiagnosticError("Persisted header differs from Dune metadata.")
        if len(parsed_rows) != len(rows) or temporary.stat().st_size == 0:
            raise LiquidationDiagnosticError("Partial CSV failed structural validation.")
        report = validate_rows(parsed_rows, columns)
        if not report["validation_passed"]:
            raise LiquidationDiagnosticError("; ".join(report["failures"]))
        checksum = sha256_file(temporary)
        os.replace(temporary, raw_path)
        update_state(
            state_path,
            "raw_file_persisted",
            raw_file_persisted=True,
            raw_file_path=provenance_path(raw_path),
            raw_file_sha256=checksum,
            raw_file_size_bytes=raw_path.stat().st_size,
            row_count=len(rows),
            column_count=len(columns),
        )
        report.update({
            "raw_file_path": provenance_path(raw_path),
            "raw_file_sha256": checksum,
            "raw_file_size_bytes": raw_path.stat().st_size,
            "sql_sha256": state["sql_sha256"],
            "query_id": state["query_id"],
            "execution_id": state["execution_id"],
            "created_at_utc": utc_now_iso(),
        })
        write_json_atomic(validation_path, report)
        final = update_state(
            state_path,
            "complete",
            validation_passed=True,
            validation_path=provenance_path(validation_path),
            completed_at_utc=utc_now_iso(),
        )
        payload_path.unlink(missing_ok=True)
        return final
    except Exception as exc:
        if state_path.exists():
            update_state(state_path, "failed", failure=str(exc))
        raise
