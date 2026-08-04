"""Shared persistence and reconciliation helpers for liquidation acquisition."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

from dai_sim.common.paths import find_repository_root


PROJECT_ROOT = find_repository_root(__file__)
WAD = Decimal(10) ** 18
RAY = Decimal(10) ** 27
RAD = Decimal(10) ** 45

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
TRANSACTION_COLUMNS = (
    "tx_hash", "transaction_sender", "transaction_recipient", "success",
    "gas_limit", "gas_used", "gas_price", "max_fee_per_gas",
    "max_priority_fee_per_gas", "priority_fee_per_gas", "block_time",
    "block_number", "block_date", "transaction_index",
)


class LiquidationDiagnosticError(RuntimeError):
    """Raised when an acquisition persistence or reconciliation invariant fails."""


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


def provenance_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def decimal_value(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise LiquidationDiagnosticError(
            f"Non-numeric Maker value: {value!r}."
        ) from exc


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


def _unwrap(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    if isinstance(payload.get("structuredContent"), dict):
        payload = payload["structuredContent"]
    if payload.get("state") != "COMPLETED":
        raise LiquidationDiagnosticError(
            f"Execution is not complete: {payload.get('state')!r}."
        )
    metadata = payload.get("resultMetadata", {})
    rows = payload.get("data", {}).get("rows")
    columns = [item["name"] for item in metadata.get("columns", [])]
    if not isinstance(rows, list) or not columns:
        raise LiquidationDiagnosticError("Completed payload lacks rows or columns.")
    if metadata.get("totalRowCount") != len(rows):
        raise LiquidationDiagnosticError("Result metadata and row count differ.")
    return payload, rows, columns


def reconcile_bark_kick(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    rows = list(rows)
    barks = [row for row in rows if row["record_type"] == "bark_event"]
    kicks = [row for row in rows if row["record_type"] == "kick_event"]
    matches = [
        sum(
            auction_key(kick) == auction_key(bark)
            and kick["tx_hash"] == bark["tx_hash"]
            for kick in kicks
        )
        for bark in barks
    ]
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
            counts[
                "events" if row["record_type"] == event_type else "calls"
            ] += 1
        result[family] = {
            "matched_keys": sum(
                value == {"events": 1, "calls": 1} for value in keys.values()
            ),
            "event_without_call": sum(
                value["events"] > 0 and value["calls"] == 0
                for value in keys.values()
            ),
            "call_without_event": sum(
                value["calls"] > 0 and value["events"] == 0
                for value in keys.values()
            ),
            "ambiguous_keys": sum(
                value["events"] > 1 or value["calls"] > 1
                for value in keys.values()
            ),
        }
    return result


def classify_terminals(
    rows: Iterable[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(auction_key(row), []).append(row)
    output: dict[tuple[str, str], str] = {}
    for key, actions in grouped.items():
        if any(row["record_type"] == "yank_event" for row in actions):
            output[key] = "cancelled"
            continue
        takes = sorted(
            (row for row in actions if row["record_type"] == "take_event"),
            key=action_order,
        )
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
        kick = next(
            (row for row in ordered if row["record_type"] == "kick_event"),
            None,
        )
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
                if (
                    previous_lot is not None
                    and redo_lot is not None
                    and redo_lot != previous_lot
                ):
                    non_monotonic += 1
                if (
                    previous_tab is not None
                    and redo_tab is not None
                    and redo_tab != previous_tab
                ):
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
                    comparisons.append(
                        {
                            "absolute": float(absolute),
                            "relative": (
                                float(absolute / abs(implied)) if implied else 0.0
                            ),
                            "after_redo": float(redone),
                        }
                    )
            previous_lot, previous_tab, redone = lot, tab, False
    return {
        "auctions_with_multiple_takes": multiple,
        "redo_boundary_count": redo_boundaries,
        "non_monotonic_or_redo_state_violation_count": non_monotonic,
        "comparison_count": len(comparisons),
    }


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
                Decimal(str(row[name]))
                for name in (
                    "max_fee_per_gas",
                    "max_priority_fee_per_gas",
                    "priority_fee_per_gas",
                )
                if row.get(name) not in {None, ""}
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
    expected = (
        {value.lower() for value in expected_hashes}
        if expected_hashes is not None
        else None
    )
    action_minus_transactions = (
        sorted(expected.difference(observed)) if expected is not None else []
    )
    transactions_minus_actions = (
        sorted(observed.difference(expected)) if expected is not None else []
    )
    if expected is not None and len(rows) != len(expected):
        failures.append(f"row count {len(rows)} differs from expected {len(expected)}")
    for label, value in (
        ("null transaction hashes", null_hashes),
        ("malformed transaction hashes", malformed),
        ("invalid success values", invalid_success),
        ("invalid gas rows", invalid_gas),
        ("invalid timestamps", invalid_timestamp),
        ("block date mismatches", date_mismatch),
        ("non-finite numeric values", non_finite),
        ("action hashes missing from transactions", len(action_minus_transactions)),
        ("unexpected transaction hashes", len(transactions_minus_actions)),
    ):
        if value:
            failures.append(f"{value} {label}")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(rows),
        "column_count": len(columns),
        "unique_transaction_count": len(set(hashes)),
        "duplicate_transaction_count": duplicates,
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


def _semantic_actions_by_transaction(
    actions: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in actions:
        if row["record_type"].endswith("_event") or row["record_type"].endswith(
            "_failed"
        ):
            grouped.setdefault(row["tx_hash"].lower(), []).append(row)
    return grouped


def classify_successful_take_transactions(
    actions: list[dict[str, Any]],
) -> dict[str, str]:
    semantic = _semantic_actions_by_transaction(actions)
    take_hashes = {
        row["tx_hash"].lower()
        for row in actions
        if row["record_type"] == "take_event"
    }
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
