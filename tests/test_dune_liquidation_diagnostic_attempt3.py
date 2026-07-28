"""Tests for the shallow Phase 1C attempt-three architecture."""

from __future__ import annotations

from pathlib import Path
import csv
import json
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflows.maintenance.archive import liquidation_diagnostic_attempt3 as attempt3
from workflows.maintenance.archive.liquidation_diagnostic import (
    LiquidationDiagnosticError,
    write_json_atomic,
)


def row(record_type: str, **updates: object) -> dict[str, object]:
    value = {column: None for column in attempt3.ACTION_COLUMNS}
    value.update({
        "initiation_window_label": "nonzero_2022_06",
        "action_in_principal_window": True,
        "action_in_bounded_horizon": True,
        "source_table": "test",
        "record_type": record_type,
        "dog_contract": "0x" + "11" * 20,
        "clipper_contract": "0x" + "22" * 20,
        "auction_id": "1",
        "ilk": "ETH-A",
        "urn": "0x" + "33" * 20,
        "tx_hash": "0x" + "44" * 32,
        "block_time": "2022-06-13 00:00:00.000 UTC",
        "block_number": "1",
        "transaction_index": "0",
        "event_index": "1" if record_type.endswith("_event") else None,
        "call_trace_address": None if record_type.endswith("_event") else "0",
        "call_success": None if record_type.endswith("_event") else True,
    })
    value.update(updates)
    return value


def basic_actions() -> list[dict[str, object]]:
    return [
        row("bark_event", ink_raw=str(2 * 10**18), art_raw=str(100 * 10**18), due_raw=str(100 * 10**45)),
        row("bark_call", event_index=None, call_trace_address="0", call_success=True),
        row("kick_event", event_index="2", top_raw=str(2_000 * 10**27), tab_raw=str(113 * 10**45), lot_raw=str(2 * 10**18)),
        row("kick_call", event_index=None, call_trace_address="0.1", call_success=True),
    ]


def test_shallow_sql_architecture_and_exact_scope() -> None:
    sql = attempt3.ACTION_SQL.read_text(encoding="utf-8")
    report = attempt3.validate_shallow_action_sql(sql)
    assert report["validation_passed"], report["failures"]
    assert report["union_branch_count"] == 9
    assert report["union_column_counts"] == [36] * 9
    assert "exists (" not in sql.lower()
    assert "ethereum.transactions" not in sql.lower()
    assert "group by" not in sql.lower()
    assert " over (" not in sql.lower()
    for ilk in attempt3.EXPECTED_ILKS:
        assert sql.count(f"'{ilk}'") == 1
    assert "2023-02-10 00:00:00" in sql
    assert "2022-06-22 00:00:00" in sql
    assert sql.lower().count("0x2c5d2826eb5903b8fc201cf48094b858f42f61c7eaac9aaf43ebed490138144e") == 1


def test_bark_kick_same_transaction_reconciliation() -> None:
    assert attempt3.reconcile_bark_kick(basic_actions()) == {
        "matched": 1, "unmatched": 0, "multiply_matched": 0,
    }
    actions = basic_actions()
    actions[2]["tx_hash"] = "0x" + "55" * 32
    assert attempt3.reconcile_bark_kick(actions)["unmatched"] == 1


def test_event_call_ambiguity_is_retained() -> None:
    actions = basic_actions()
    actions.append(dict(actions[3], call_trace_address="0.2"))
    report = attempt3.reconcile_event_calls(actions)
    assert report["kick"]["ambiguous_keys"] == 1


def test_terminal_classification_checks_remaining_state() -> None:
    actions = basic_actions() + [row(
        "take_event", tx_hash="0x" + "55" * 32, block_number="2",
        event_index="3", remaining_tab_raw="0", remaining_lot_raw=str(10**18),
    )]
    assert next(iter(attempt3.classify_terminals(actions).values())) == "target_cleared"
    actions.append(row("yank_event", tx_hash="0x" + "66" * 32, block_number="3", event_index="4"))
    assert next(iter(attempt3.classify_terminals(actions).values())) == "cancelled"


def test_partial_take_and_unit_scaling() -> None:
    actions = basic_actions() + [
        row("take_event", tx_hash="0x" + "55" * 32, block_number="2", event_index="3",
            remaining_tab_raw=str(50 * 10**45), remaining_lot_raw=str(10**18),
            owe_raw=str(50 * 10**45), price_raw=str(50 * 10**27)),
        row("take_event", tx_hash="0x" + "66" * 32, block_number="3", event_index="4",
            remaining_tab_raw="0", remaining_lot_raw="0",
            owe_raw=str(50 * 10**45), price_raw=str(50 * 10**27)),
    ]
    report = attempt3.partial_take_checks(actions)
    assert report["auctions_with_multiple_takes"] == 1
    assert report["non_monotonic_or_redo_state_violation_count"] == 0
    assert report["maximum_absolute_discrepancy"] == 0
    ranges = attempt3._scaled_ranges(actions)
    assert ranges["ink_wad"]["minimum"] == 2
    assert ranges["due_dai"]["maximum"] == 100


def test_transaction_sql_is_unique_bounded_and_unaggregated() -> None:
    hashes = ["0x" + "aa" * 32, "0x" + "bb" * 32, "0x" + "aa" * 32]
    sql = attempt3.build_transaction_sql(hashes)
    assert sql.count("(0x" + "aa" * 32 + ")") == 1
    assert "GROUP BY" not in sql.upper()
    assert "2023-02-10" in sql and "2022-06-22" in sql


def test_transaction_validation_detects_duplicates() -> None:
    columns = list(attempt3.TRANSACTION_COLUMNS)
    tx = {column: None for column in columns}
    tx["tx_hash"] = "0x" + "aa" * 32
    report = attempt3.validate_transaction_rows([tx, dict(tx)], columns)
    assert not report["validation_passed"]
    assert report["duplicate_transaction_count"] == 1


def test_gas_deduplication_and_multi_action_multi_auction() -> None:
    actions = basic_actions()
    actions.append(row(
        "take_event", clipper_contract="0x" + "99" * 20, auction_id="2",
        event_index="5",
    ))
    tx = {column: None for column in attempt3.TRANSACTION_COLUMNS}
    tx.update({"tx_hash": actions[0]["tx_hash"], "success": True, "gas_used": "300000", "gas_price": "20000000000"})
    report = attempt3.combined_diagnostics(actions, [tx])
    assert report["unique_transaction_count"] == 1
    assert report["multi_action_transaction_count"] == 1
    assert report["multi_auction_transaction_count"] == 1
    assert report["gas_distributions_by_record_type"]["bark_event"]["gas_used"]["count"] == 1


def test_stop_after_query_one_failure_and_query_two_failure() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        action_state = root / "action.json"
        transaction_state = root / "transaction.json"
        write_json_atomic(action_state, {"state": "failed", "validation_passed": False, "raw_file_persisted": False})
        with pytest.raises(LiquidationDiagnosticError):
            attempt3.require_action_complete_for_transaction(action_state)
        write_json_atomic(transaction_state, {"state": "failed"})
        with pytest.raises(LiquidationDiagnosticError):
            attempt3.require_no_failed_transaction_attempt(transaction_state)


def test_attempt_three_paths_are_separate_from_prior_attempts() -> None:
    names = {
        attempt3.ACTION_STATE.name, attempt3.TRANSACTION_STATE.name,
        attempt3.ACTION_PAYLOAD.name, attempt3.TRANSACTION_PAYLOAD.name,
    }
    assert len(names) == 4
    assert all("attempt3" in name for name in names)


def transaction_row(index: int) -> dict[str, object]:
    return {
        "tx_hash": "0x" + f"{index:064x}",
        "transaction_sender": "0x" + "11" * 20,
        "transaction_recipient": "0x" + "22" * 20,
        "success": index % 3 != 0,
        "gas_limit": 500_000,
        "gas_used": 100_000 + index,
        "gas_price": 20_000_000_000 + index,
        "max_fee_per_gas": 30_000_000_000,
        "max_priority_fee_per_gas": 2_000_000_000,
        "priority_fee_per_gas": 1_500_000_000,
        "block_time": "2022-06-13 00:00:00.000 UTC",
        "block_number": 14_950_000 + index,
        "block_date": "2022-06-13",
        "transaction_index": index,
    }


def test_retrieval_response_must_flow_to_persistence() -> None:
    response = {"state": "COMPLETED"}
    observed: list[dict[str, object]] = []

    result = attempt3.retrieve_then_persist(lambda: response, lambda value: observed.append(value) or "done")

    assert result == "done"
    assert observed == [response]
    with pytest.raises(LiquidationDiagnosticError, match="None"):
        attempt3.retrieve_then_persist(lambda: None, lambda value: observed.append(value))
    assert observed == [response]


def test_recovery_persists_realistic_result_without_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [transaction_row(index) for index in range(368)]
    hashes = {str(row["tx_hash"]).lower() for row in rows}
    payload = {
        "executionId": attempt3.AUTHORISED_RECOVERY_EXECUTION_ID,
        "state": "COMPLETED",
        "resultMetadata": {
            "columns": [{"name": column, "type": "varchar"} for column in attempt3.TRANSACTION_COLUMNS],
            "totalRowCount": 368,
            "executionCostCredits": "2.047",
        },
        "data": {"rows": list(reversed(rows))},
    }
    monkeypatch.setattr(attempt3, "_read_action_hashes", lambda: hashes)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "recovery.json"
        payload_path = root / ".recovery.partial.json"
        raw = root / "transactions.csv"
        write_json_atomic(state, {
            "execution_id": attempt3.AUTHORISED_RECOVERY_EXECUTION_ID,
            "state": "recovery_planned",
        })

        recovered_state, report = attempt3.persist_recovery_response(
            payload, payload_path=payload_path, state_path=state, raw_path=raw,
        )

        assert report["validation_passed"]
        assert recovered_state["raw_file_persisted"]
        assert not payload_path.exists()
        with raw.open(encoding="utf-8", newline="") as handle:
            persisted = list(csv.DictReader(handle))
        assert len(persisted) == 368
        assert persisted[0]["tx_hash"] == "0x" + f"{0:064x}"
        assert persisted[-1]["tx_hash"] == "0x" + f"{367:064x}"
        assert json.loads(state.read_text())["recovery_retrieval_count"] == 1


def test_transaction_validation_checks_completeness_and_fields() -> None:
    rows = [transaction_row(index) for index in range(3)]
    expected = {str(row["tx_hash"]).lower() for row in rows}
    report = attempt3.validate_transaction_rows(
        rows, list(attempt3.TRANSACTION_COLUMNS), expected_hashes=expected,
    )
    assert report["validation_passed"]
    assert report["action_minus_transaction_hashes"] == []
    assert report["transaction_minus_action_hashes"] == []
    rows[0]["gas_used"] = 600_000
    report = attempt3.validate_transaction_rows(
        rows, list(attempt3.TRANSACTION_COLUMNS), expected_hashes=expected,
    )
    assert not report["validation_passed"]
    assert report["invalid_gas_row_count"] == 1


def test_successful_take_transaction_classification() -> None:
    clean = row("take_event", tx_hash="0x" + "10" * 32)
    same = row("take_event", tx_hash="0x" + "20" * 32)
    same_second = dict(same, event_index="8")
    other = row("take_event", tx_hash="0x" + "30" * 32)
    failed = row("take_call_failed", tx_hash=other["tx_hash"], event_index=None)
    multi = row("take_event", tx_hash="0x" + "40" * 32)
    multi_second = dict(multi, clipper_contract="0x" + "99" * 20, auction_id="2")
    report = attempt3.classify_successful_take_transactions(
        [clean, same, same_second, other, failed, multi, multi_second]
    )
    assert report[str(clean["tx_hash"])] == "clean_single_take_single_auction"
    assert report[str(same["tx_hash"])] == "multiple_takes_same_auction"
    assert report[str(other["tx_hash"])] == "other_liquidation_actions_same_tx"
    assert report[str(multi["tx_hash"])] == "multiple_auctions"
