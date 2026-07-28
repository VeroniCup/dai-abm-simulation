"""Local preflight, persistence and validation for Phase 1E diagnostics.

The module deliberately contains no Dune client and cannot create or execute a
query.  MCP result payloads are persisted to an ignored ingress JSON file and
then promoted to deterministic CSV through the atomic path implemented here.
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
import re
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_DIR = (
    ROOT / "data" / "vaults" / "provenance" / "archive" / "discovery"
)
CANONICAL_VAT = "0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b"
CANONICAL_MANAGER = "0x5ef30b9986345249bc32d8928b7ee64de9435e39"
TARGET_ILKS = ("ETH-A", "ETH-B", "ETH-C", "WBTC-A", "WBTC-B", "WBTC-C")

DIAGNOSTICS = {
    "frob": {
        "sql": ROOT / "sql" / "dune_phase1e_vat_frob_diagnostic.sql",
        "stem": "phase1e_vat_frob_diagnostic",
    },
    "liquidation": {
        "sql": ROOT / "sql" / "dune_phase1e_liquidation_linkage_diagnostic.sql",
        "stem": "phase1e_liquidation_linkage_diagnostic",
    },
    "ownership": {
        "sql": ROOT / "sql" / "dune_phase1e_owner_mapping_diagnostic.sql",
        "stem": "phase1e_owner_mapping_diagnostic",
    },
}

EXPECTED_COLUMNS = {
    "frob": (
        "block_time_utc", "block_number", "transaction_hash",
        "transaction_index", "trace_position", "source_contract",
        "top_level_sender", "top_level_recipient", "success", "ilk", "urn",
        "collateral_source", "debt_destination", "dink_raw", "dart_raw",
        "collateral_delta_wad", "normalised_debt_delta_wad", "is_deposit",
        "is_withdrawal", "is_debt_draw", "is_debt_repayment",
    ),
    "liquidation": (
        "block_time_utc", "block_number", "transaction_hash",
        "transaction_index", "bark_event_index", "bark_call_trace_position",
        "grab_trace_position", "ilk", "urn", "bark_keeper", "auction_id",
        "dog_contract", "vat_contract", "clipper_contract",
        "bark_call_success", "grab_success", "bark_ink_raw", "bark_art_raw",
        "bark_due_raw", "grab_dink_raw", "grab_dart_raw",
        "bark_collateral_wad", "bark_normalised_debt_wad", "bark_due_dai",
        "grab_collateral_delta_wad", "grab_normalised_debt_delta_wad",
        "collateral_reconciles", "normalised_debt_reconciles",
        "transaction_bark_count", "transaction_grab_count", "urn_link_count",
    ),
    "ownership": (
        "block_time_utc", "block_number", "transaction_hash",
        "transaction_index", "source_position", "event_type", "source_table",
        "cdp_id", "ilk", "urn", "original_manager_owner", "new_owner",
        "event_recorded_owner", "manager_caller", "top_level_sender",
        "manager_contract", "call_success", "event_index",
        "creation_trace_position", "urn_creator", "creation_block_time",
        "creation_block_number", "creation_is_direct_child", "owner_reconciles",
    ),
}


class VaultDiscoveryError(RuntimeError):
    """Raised when a diagnostic is unsafe, incomplete or invalid."""


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
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def paths(kind: str) -> dict[str, Path]:
    stem = DIAGNOSTICS[kind]["stem"]
    return {
        "payload": DISCOVERY_DIR / f".{stem}.partial.json",
        "csv": DISCOVERY_DIR / f"{stem}.csv",
        "state": DISCOVERY_DIR / f"{stem}_state.json",
        "metadata": DISCOVERY_DIR / f"{stem}_metadata.json",
        "validation": DISCOVERY_DIR / f"{stem}_validation.json",
    }


def validate_sql(kind: str, sql: str) -> dict[str, Any]:
    lower = sql.lower()
    failures: list[str] = []
    common = (
        "call_block_date" if kind != "liquidation" else "evt_block_date",
        "call_success = true" if kind != "liquidation" else "g.call_success = true",
        "order by",
    )
    for fragment in common:
        if fragment not in lower:
            failures.append(f"missing required fragment: {fragment}")
    for fragment in ("select *", "2021-06-01", "2024-07-01"):
        if fragment in lower:
            failures.append(f"diagnostic contains forbidden broad fragment: {fragment}")
    if kind == "frob":
        required = ("maker_ethereum.vat_call_frob", "f.dink", "f.dart", "2023-02-08")
    elif kind == "liquidation":
        required = (
            "maker_ethereum.dog_evt_bark", "maker_ethereum.dog_call_bark",
            "maker_ethereum.vat_call_grab", "ethereum.transactions",
            "t.index as transaction_index", "2022-06-14",
        )
    else:
        required = (
            "maker_ethereum.cdp_manager_call_open",
            "maker_ethereum.cdp_manager_evt_newcdp",
            "maker_ethereum.cdp_manager_call_give",
            "ethereum.traces",
            "ethereum.transactions",
            "t.index as transaction_index",
            "t.type = 'create'",
            "2023-02-08",
            "2023-03-08",
        )
    for fragment in required:
        if fragment.lower() not in lower:
            failures.append(f"missing required fragment: {fragment}")
    if kind in {"liquidation", "ownership"} and "call_tx_index as transaction_index" in lower:
        failures.append("decoded call_tx_index must not be used as transaction ordering")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
    }


def preflight() -> dict[str, Any]:
    reports = {}
    for kind, spec in DIAGNOSTICS.items():
        reports[kind] = validate_sql(kind, spec["sql"].read_text(encoding="utf-8"))
    return {
        "validation_passed": all(r["validation_passed"] for r in reports.values()),
        "diagnostics": reports,
        "network_client_present": False,
        "target_ilks": list(TARGET_ILKS),
    }


def initialise_state(kind: str) -> dict[str, Any]:
    report = validate_sql(kind, DIAGNOSTICS[kind]["sql"].read_text(encoding="utf-8"))
    if not report["validation_passed"]:
        raise VaultDiscoveryError("; ".join(report["failures"]))
    target = paths(kind)
    for key in ("payload", "csv", "state"):
        if target[key].exists():
            raise VaultDiscoveryError(f"Refusing to overwrite {relative(target[key])}")
    state = {
        "diagnostic": kind,
        "state": "planned",
        "query_type": "private temporary diagnostic",
        "engine": "small",
        "sql_path": relative(DIAGNOSTICS[kind]["sql"]),
        "sql_sha256": report["sql_sha256"],
        "query_id": None,
        "execution_id": None,
        "result_retrieval_count": 0,
        "raw_file_persisted": False,
        "validation_passed": False,
    }
    write_json_atomic(target["state"], state)
    return state


def update_state(kind: str, status: str, **fields: Any) -> dict[str, Any]:
    target = paths(kind)
    state = json.loads(target["state"].read_text(encoding="utf-8"))
    state.update(fields)
    state["state"] = status
    write_json_atomic(target["state"], state)
    return state


def refresh_planned_state(kind: str) -> dict[str, Any]:
    """Refresh a planned diagnostic after a local, pre-execution SQL edit."""
    target = paths(kind)
    state = json.loads(target["state"].read_text(encoding="utf-8"))
    if state.get("state") != "planned" or state.get("query_id") or state.get("execution_id"):
        raise VaultDiscoveryError("Only an unsubmitted planned diagnostic may be refreshed")
    report = validate_sql(kind, DIAGNOSTICS[kind]["sql"].read_text(encoding="utf-8"))
    if not report["validation_passed"]:
        raise VaultDiscoveryError("; ".join(report["failures"]))
    state["sql_sha256"] = report["sql_sha256"]
    write_json_atomic(target["state"], state)
    return state


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1"}


def valid_hash(value: Any) -> bool:
    return bool(re.fullmatch(r"0x[0-9A-Fa-f]{64}", str(value or "")))


def valid_address(value: Any) -> bool:
    return bool(re.fullmatch(r"0x[0-9A-Fa-f]{40}", str(value or "")))


def source_key(row: dict[str, Any], trace_field: str) -> tuple[str, ...]:
    return (
        str(row.get("block_number")), str(row.get("transaction_index")),
        str(row.get("transaction_hash")), str(row.get(trace_field)),
    )


def required_integer(row: dict[str, Any], field: str, index: int,
                     failures: list[str]) -> int:
    text = str(row.get(field) or "").strip()
    try:
        return int(text)
    except ValueError:
        failures.append(f"row {index} has unavailable or invalid {field}")
        return -1


def trace_order(value: Any) -> tuple[int, ...]:
    text = str(value or "").strip()
    if not text:
        raise ValueError("trace position is unavailable")
    return tuple(int(part) for part in text.split("."))


def scaled_matches(raw: Decimal, observed: Any, exponent: int) -> bool:
    expected = raw / Decimal(10) ** exponent
    value = Decimal(str(observed))
    tolerance = max(Decimal("1e-12"), abs(expected) * Decimal("1e-12"))
    return abs(value - expected) <= tolerance


def validate_frob(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    keys: set[tuple[str, ...]] = set()
    direction_counts = {"deposit": 0, "withdrawal": 0, "draw": 0, "repayment": 0}
    tx_counts: dict[str, int] = {}
    ordering = []
    unavailable_transaction_index_count = 0
    for index, row in enumerate(rows):
        if row.get("ilk") != "ETH-A" or not bool_value(row.get("success")):
            failures.append(f"row {index} is not a successful ETH-A call")
        if str(row.get("source_contract", "")).lower() != CANONICAL_VAT:
            failures.append(f"row {index} has a non-canonical Vat contract")
        if not valid_hash(row.get("transaction_hash")) or not valid_address(row.get("urn")):
            failures.append(f"row {index} has malformed identity fields")
        key = source_key(row, "trace_position")
        if key in keys:
            failures.append(f"row {index} duplicates a source call")
        keys.add(key)
        dink = Decimal(str(row["dink_raw"]))
        dart = Decimal(str(row["dart_raw"]))
        expected_dink = dink / Decimal(10) ** 18
        expected_dart = dart / Decimal(10) ** 18
        observed_dink = Decimal(str(row["collateral_delta_wad"]))
        observed_dart = Decimal(str(row["normalised_debt_delta_wad"]))
        dink_tolerance = max(Decimal("1e-12"), abs(expected_dink) * Decimal("1e-12"))
        dart_tolerance = max(Decimal("1e-12"), abs(expected_dart) * Decimal("1e-12"))
        if abs(observed_dink - expected_dink) > dink_tolerance:
            failures.append(f"row {index} fails dink WAD conversion")
        if abs(observed_dart - expected_dart) > dart_tolerance:
            failures.append(f"row {index} fails dart WAD conversion")
        direction_counts["deposit"] += int(dink > 0)
        direction_counts["withdrawal"] += int(dink < 0)
        direction_counts["draw"] += int(dart > 0)
        direction_counts["repayment"] += int(dart < 0)
        tx_hash = str(row["transaction_hash"]).lower()
        tx_counts[tx_hash] = tx_counts.get(tx_hash, 0) + 1
        transaction_index_text = str(row.get("transaction_index") or "").strip()
        unavailable_transaction_index_count += int(not transaction_index_text)
        transaction_index = int(transaction_index_text) if transaction_index_text else -1
        ordering.append((int(row["block_number"]), transaction_index, tx_hash, str(row["trace_position"])))
    if not rows:
        failures.append("diagnostic returned no Vat.frob rows")
    for direction, count in direction_counts.items():
        if count == 0:
            failures.append(f"diagnostic contains no {direction} example")
    if ordering != sorted(ordering):
        failures.append("rows are not deterministically ordered")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(rows),
        "duplicate_source_call_count": len(rows) - len(keys),
        "direction_counts": direction_counts,
        "transactions_with_multiple_vat_frobs": sum(v > 1 for v in tx_counts.values()),
        "maximum_vat_frobs_in_one_transaction": max(tx_counts.values(), default=0),
        "unavailable_transaction_index_count": unavailable_transaction_index_count,
        "production_ordering_requirement": (
            "Join ethereum.transactions.index by transaction hash because the live "
            "decoded call rows returned null call_tx_index despite the catalog's "
            "non-null declaration. Do not fabricate zero indices."
        ),
    }


def validate_liquidation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    bark_keys: set[tuple[str, str]] = set()
    grab_keys: set[tuple[str, str]] = set()
    ordering: list[tuple[Any, ...]] = []
    if len(rows) != 1:
        failures.append(f"expected one Bark–grab linkage row, found {len(rows)}")
    for index, row in enumerate(rows):
        if row.get("ilk") != "ETH-A":
            failures.append(f"row {index} has an unexpected ilk")
        if not bool_value(row.get("grab_success")) or not bool_value(row.get("bark_call_success")):
            failures.append(f"row {index} is not a successful Bark and grab linkage")
        if str(row.get("vat_contract", "")).lower() != CANONICAL_VAT:
            failures.append(f"row {index} has a non-canonical Vat contract")
        if (
            not valid_hash(row.get("transaction_hash"))
            or not valid_address(row.get("urn"))
            or not valid_address(row.get("bark_keeper"))
            or not valid_address(row.get("dog_contract"))
            or not valid_address(row.get("clipper_contract"))
        ):
            failures.append(f"row {index} has malformed identity fields")
        transaction_index = required_integer(row, "transaction_index", index, failures)
        event_index = required_integer(row, "bark_event_index", index, failures)
        try:
            bark_trace = trace_order(row.get("bark_call_trace_position"))
            grab_trace = trace_order(row.get("grab_trace_position"))
        except (TypeError, ValueError):
            failures.append(f"row {index} has an invalid call trace position")
            bark_trace = (-1,)
            grab_trace = (-1,)
        tx_hash = str(row.get("transaction_hash", "")).lower()
        bark_key = (tx_hash, str(row.get("bark_event_index")))
        grab_key = (tx_hash, str(row.get("grab_trace_position")))
        if bark_key in bark_keys:
            failures.append(f"row {index} duplicates a Bark source record")
        if grab_key in grab_keys:
            failures.append(f"row {index} duplicates a grab source record")
        bark_keys.add(bark_key)
        grab_keys.add(grab_key)
        ordering.append((int(row["block_number"]), transaction_index, event_index,
                         grab_trace, tx_hash))
        bark_ink = Decimal(str(row["bark_ink_raw"]))
        bark_art = Decimal(str(row["bark_art_raw"]))
        bark_due = Decimal(str(row["bark_due_raw"]))
        grab_dink = Decimal(str(row["grab_dink_raw"]))
        grab_dart = Decimal(str(row["grab_dart_raw"]))
        if bark_ink <= 0 or bark_art <= 0 or bark_due <= 0:
            failures.append(f"row {index} has non-positive Bark accounting values")
        if grab_dink != -bark_ink:
            failures.append("Bark ink does not reconcile to Vat.grab dink")
        if grab_dart != -bark_art:
            failures.append("Bark art does not reconcile to Vat.grab dart")
        if not bool_value(row.get("collateral_reconciles")) or not bool_value(row.get("normalised_debt_reconciles")):
            failures.append("Dune reconciliation flags are false")
        conversions = (
            (bark_ink, row.get("bark_collateral_wad"), 18, "Bark ink"),
            (bark_art, row.get("bark_normalised_debt_wad"), 18, "Bark art"),
            (bark_due, row.get("bark_due_dai"), 45, "Bark due"),
            (grab_dink, row.get("grab_collateral_delta_wad"), 18, "grab dink"),
            (grab_dart, row.get("grab_normalised_debt_delta_wad"), 18, "grab dart"),
        )
        for raw, observed, exponent, label in conversions:
            if not scaled_matches(raw, observed, exponent):
                failures.append(f"row {index} fails {label} conversion")
        if required_integer(row, "urn_link_count", index, failures) != 1:
            failures.append(f"row {index} is not a unique urn-level Bark–grab match")
        bark_count = required_integer(row, "transaction_bark_count", index, failures)
        grab_count = required_integer(row, "transaction_grab_count", index, failures)
        if bark_count < 1 or grab_count < 1 or bark_count != grab_count:
            failures.append(f"row {index} has unexplained transaction-level Bark/grab cardinality")
    if ordering != sorted(ordering):
        failures.append("rows are not deterministically ordered")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(rows),
        "unique_bark_source_count": len(bark_keys),
        "unique_grab_source_count": len(grab_keys),
        "bark_grab_match_count": int(len(rows) == 1 and not failures),
        "ordering_source": "ethereum.transactions.index, Bark log index and Vat.grab trace position",
        "state_mutation_conclusion": (
            "Vat.grab is the canonical collateral and normalised-debt state mutation; "
            "Dog.Bark is liquidation and auction annotation and must not add a second delta."
        ),
    }


def validate_ownership(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    source_keys: set[tuple[str, ...]] = set()
    ordering: list[tuple[Any, ...]] = []
    by_cdp: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        if row.get("ilk") != "ETH-A":
            failures.append(f"row {index} has an unexpected ilk")
        if str(row.get("manager_contract", "")).lower() != CANONICAL_MANAGER:
            failures.append(f"row {index} has a non-canonical manager")
        if str(row.get("urn_creator", "")).lower() != CANONICAL_MANAGER:
            failures.append(f"row {index} has an unexpected UrnHandler creator")
        if (
            not valid_hash(row.get("transaction_hash"))
            or not valid_address(row.get("urn"))
            or not valid_address(row.get("original_manager_owner"))
            or not bool_value(row.get("call_success"))
        ):
            failures.append(f"row {index} has malformed identity fields")
        if not bool_value(row.get("creation_is_direct_child")):
            failures.append(f"row {index} lacks direct-child creation linkage")
        if not bool_value(row.get("owner_reconciles")):
            failures.append(f"row {index} owner fields do not reconcile")
        event_type = str(row.get("event_type"))
        if event_type not in {"open", "give"}:
            failures.append(f"row {index} has an unexpected event type")
        if event_type == "give" and not valid_address(row.get("new_owner")):
            failures.append(f"row {index} has a malformed give destination")
        transaction_index = required_integer(row, "transaction_index", index, failures)
        try:
            position = trace_order(row.get("source_position"))
        except (TypeError, ValueError):
            failures.append(f"row {index} has an invalid source trace position")
            position = (-1,)
        tx_hash = str(row.get("transaction_hash", "")).lower()
        key = (str(row.get("source_table")), tx_hash,
               str(row.get("source_position")), event_type)
        if key in source_keys:
            failures.append(f"row {index} duplicates a source record")
        source_keys.add(key)
        cdp = str(row.get("cdp_id"))
        by_cdp.setdefault(cdp, []).append(row)
        ordering.append((int(row["block_number"]), transaction_index, position,
                         tx_hash, event_type))
    if not rows:
        failures.append("diagnostic returned no owner/CDP/urn mappings")
    if ordering != sorted(ordering):
        failures.append("rows are not deterministically ordered")
    urn_to_cdp: dict[str, str] = {}
    owner_histories: dict[str, list[dict[str, str]]] = {}
    open_count = 0
    give_count = 0
    for cdp, cdp_rows in by_cdp.items():
        opens = [row for row in cdp_rows if row.get("event_type") == "open"]
        gives = [row for row in cdp_rows if row.get("event_type") == "give"]
        open_count += len(opens)
        give_count += len(gives)
        if len(opens) != 1:
            failures.append(f"CDP {cdp} has {len(opens)} open mappings")
            continue
        anchor = opens[0]
        urn = str(anchor.get("urn", "")).lower()
        if urn in urn_to_cdp and urn_to_cdp[urn] != cdp:
            failures.append(f"urn {urn} maps to multiple CDP IDs")
        urn_to_cdp[urn] = cdp
        for row in cdp_rows:
            if str(row.get("urn", "")).lower() != urn:
                failures.append(f"CDP {cdp} has inconsistent urn linkage")
            if row.get("original_manager_owner") != anchor.get("original_manager_owner"):
                failures.append(f"CDP {cdp} has inconsistent original-owner linkage")
        current_owner = str(anchor.get("original_manager_owner", "")).lower()
        history = [{"event_type": "open", "effective_owner": current_owner}]
        ordered_gives = sorted(
            gives,
            key=lambda row: (
                int(row["block_number"]), int(row["transaction_index"]),
                trace_order(row["source_position"]),
                str(row["transaction_hash"]).lower(),
            ),
        )
        for row in ordered_gives:
            destination = str(row.get("new_owner", "")).lower()
            history.append({
                "event_type": "give", "previous_effective_owner": current_owner,
                "effective_owner": destination,
            })
            current_owner = destination
        owner_histories[cdp] = history
    return {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(rows),
        "unique_source_record_count": len(source_keys),
        "unique_cdp_count": len(by_cdp),
        "unique_urn_count": len(urn_to_cdp),
        "open_count": open_count,
        "give_count": give_count,
        "ownership_transfer_observed": give_count > 0,
        "owner_histories": owner_histories,
        "ordering_source": "ethereum.transactions.index and decoded call trace position",
        "owner_proxy_warning": (
            "The manager owner is commonly a DSProxy or integration contract; "
            "it is an owner-identity proxy, not a verified beneficial wallet owner."
        ),
        "direct_urn_warning": (
            "A direct Vat urn need not have a CdpManager CDP ID or manager-owner "
            "mapping and must remain nullable in the production identity layer."
        ),
    }


VALIDATORS: dict[str, Callable[[list[dict[str, Any]]], dict[str, Any]]] = {
    "frob": validate_frob,
    "liquidation": validate_liquidation,
    "ownership": validate_ownership,
}


def extract_rows(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    result = payload.get("result") if isinstance(payload.get("result"), dict) else None
    rows = None
    if data is not None:
        rows = data.get("rows")
    if rows is None and result is not None:
        rows = result.get("rows")
    if rows is None:
        rows = payload.get("rows")
    if not isinstance(rows, list):
        raise VaultDiscoveryError("MCP payload contains no result rows")
    metadata = payload.get("resultMetadata") or payload.get("result_metadata") or {}
    columns_meta = metadata.get("columns") if isinstance(metadata, dict) else None
    if isinstance(columns_meta, list):
        columns = [str(item.get("name")) for item in columns_meta]
    elif rows:
        columns = list(rows[0].keys())
    else:
        columns = []
    return rows, columns, metadata if isinstance(metadata, dict) else {}


def persist(kind: str) -> dict[str, Any]:
    target = paths(kind)
    payload = json.loads(target["payload"].read_text(encoding="utf-8"))
    rows, columns, result_metadata = extract_rows(payload)
    expected = list(EXPECTED_COLUMNS[kind])
    if columns != expected:
        raise VaultDiscoveryError(f"unexpected {kind} columns: {columns}")
    partial_csv = target["csv"].with_name(f".{target['csv'].name}.tmp")
    target["csv"].parent.mkdir(parents=True, exist_ok=True)
    try:
        with partial_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=expected, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        with partial_csv.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            parsed = list(reader)
            parsed_columns = list(reader.fieldnames or [])
        if parsed_columns != expected or len(parsed) != len(rows):
            raise VaultDiscoveryError("partial CSV failed structural validation")
        report = VALIDATORS[kind](parsed)
        report.update({"columns": expected, "column_count": len(expected)})
        write_json_atomic(target["validation"], report)
        if not report["validation_passed"]:
            raise VaultDiscoveryError("; ".join(report["failures"]))
        os.replace(partial_csv, target["csv"])
        fsync_directory(target["csv"].parent)
    except Exception:
        if partial_csv.exists():
            failed = partial_csv.with_suffix(partial_csv.suffix + ".failed")
            os.replace(partial_csv, failed)
            fsync_directory(failed.parent)
        raise
    state = json.loads(target["state"].read_text(encoding="utf-8"))
    metadata = {
        "diagnostic": kind,
        "query_id": state.get("query_id"),
        "query_url": state.get("query_url"),
        "execution_id": state.get("execution_id"),
        "execution_state": payload.get("state"),
        "engine": "small",
        "sql_path": state.get("sql_path"),
        "sql_sha256": state.get("sql_sha256"),
        "row_count": len(rows),
        "column_count": len(expected),
        "file_path": relative(target["csv"]),
        "file_size_bytes": target["csv"].stat().st_size,
        "file_sha256": sha256_file(target["csv"]),
        "result_metadata": result_metadata,
        "validation_status": "passed",
    }
    write_json_atomic(target["metadata"], metadata)
    update_state(
        kind, "complete", result_retrieval_count=1, raw_file_persisted=True,
        validation_passed=True, row_count=len(rows), column_count=len(expected),
        execution_state=payload.get("state"),
        raw_file_path=metadata["file_path"], raw_file_sha256=metadata["file_sha256"],
        raw_file_size_bytes=metadata["file_size_bytes"],
    )
    target["payload"].unlink()
    return {"metadata": metadata, "validation": report}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight")
    initialise = subparsers.add_parser("initialise")
    initialise.add_argument("--diagnostic", choices=DIAGNOSTICS, required=True)
    refresh = subparsers.add_parser("refresh")
    refresh.add_argument("--diagnostic", choices=DIAGNOSTICS, required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--diagnostic", choices=DIAGNOSTICS, required=True)
    record.add_argument("--query-id", type=int, required=True)
    record.add_argument("--query-url", required=True)
    record.add_argument("--execution-id", required=True)
    record.add_argument("--execution-state", required=True)
    persist_parser = subparsers.add_parser("persist")
    persist_parser.add_argument("--diagnostic", choices=DIAGNOSTICS, required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        result = preflight()
    elif args.command == "initialise":
        result = initialise_state(args.diagnostic)
    elif args.command == "refresh":
        result = refresh_planned_state(args.diagnostic)
    elif args.command == "record":
        result = update_state(
            args.diagnostic, "execution_submitted", query_id=args.query_id,
            query_url=args.query_url, execution_id=args.execution_id,
            execution_state=args.execution_state,
        )
    else:
        result = persist(args.diagnostic)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
