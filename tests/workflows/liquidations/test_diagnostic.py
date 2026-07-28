"""Deterministic tests for the Phase 1C liquidation diagnostic handoff."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


from tests.support import REPOSITORY_ROOT as ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflows.maintenance.archive import liquidation_diagnostic as diagnostic


def base_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {column: None for column in diagnostic.REQUIRED_COLUMNS}
    row.update({
        "initiation_window_label": "nonzero_2022_06",
        "ilk": "ETH-A",
        "dog_contract": "0x" + "11" * 20,
        "clipper_contract": "0x" + "22" * 20,
        "auction_id": "7",
        "transaction_hash": "0x" + "33" * 32,
        "block_number": 1,
        "block_timestamp": "2022-06-13 00:00:00.000 UTC",
        "transaction_index": 0,
        "event_index": 1,
        "action_type": "bark",
        "source_table": "maker_ethereum.dog_evt_bark",
        "record_kind": "event",
        "event_to_call_linkage_flag": True,
        "bark_ink_raw": str(2 * 10**18),
        "bark_art_raw": str(100 * 10**18),
        "bark_due_raw": str(100 * 10**45),
        "collateral_wad_units": 2.0,
        "debt_or_payment_dai": 100.0,
        "top_level_transaction_success": True,
        "gas_limit": 500_000,
        "gas_used": 300_000,
        "effective_gas_price_wei": 20_000_000_000,
        "effective_gas_price_gwei": 20.0,
        "maker_liquidation_action_count_in_tx": 2,
        "distinct_auctions_in_tx": 1,
        "multi_auction_transaction": False,
        "auction_initiated_before_window": False,
        "action_in_principal_window": True,
        "action_in_bounded_horizon": True,
        "legacy_cat_bite_count": 0,
        "legacy_flipper_activity_count": 0,
    })
    row.update(changes)
    return row


def linked_rows() -> list[dict[str, object]]:
    bark = base_row()
    bark_call = base_row(
        source_table="maker_ethereum.dog_call_bark",
        record_kind="call",
        event_index=None,
        call_trace_address="0",
        decoded_call_success=True,
    )
    kick = base_row(
        action_type="kick",
        source_table="maker_ethereum.clipper_evt_kick",
        event_index=2,
        kick_tab_raw=str(113 * 10**45),
        kick_lot_raw=str(2 * 10**18),
        kick_top_raw=str(2_000 * 10**27),
        collateral_wad_units=2.0,
        debt_or_payment_dai=113.0,
        price_dai_per_collateral=2_000.0,
    )
    kick_call = base_row(
        action_type="kick",
        source_table="maker_ethereum.clipper_call_kick",
        record_kind="call",
        event_index=None,
        call_trace_address="0.1",
        decoded_call_success=True,
        collateral_wad_units=None,
        debt_or_payment_dai=None,
        price_dai_per_collateral=None,
    )
    return [bark, bark_call, kick, kick_call]


class TopicAndSqlTests(unittest.TestCase):
    def test_yank_topic_is_abi_derived_keccak_not_sha3(self) -> None:
        self.assertEqual(
            diagnostic.keccak256(b"").hex(),
            "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470",
        )
        self.assertEqual(diagnostic.verify_yank_topic(), diagnostic.YANK_TOPIC0)

    def test_sql_has_explicit_six_ilks_and_no_prefix_population_filter(self) -> None:
        sql = diagnostic.DEFAULT_SQL.read_text(encoding="utf-8")
        report = diagnostic.validate_sql(sql)
        self.assertTrue(report["validation_passed"], report["failures"])
        for ilk in diagnostic.EXPECTED_ILKS:
            self.assertEqual(sql.count(f"'{ilk}'"), 1)
        self.assertNotIn("starts_with(from_utf8", sql.lower())

    def test_kick_calls_uses_live_aliases_and_explicit_renames(self) -> None:
        sql = diagnostic.DEFAULT_SQL.read_text(encoding="utf-8")
        body = diagnostic._extract_cte_body(sql, "kick_calls")
        self.assertNotIn("c.window_label", body)
        self.assertNotIn("c.clipper_contract", body)
        self.assertIn("w.window_label AS initiation_window_label", body)
        self.assertIn("c.contract_address AS clipper_contract", body)

    def test_live_base_alias_references_and_union_alignment(self) -> None:
        audit = diagnostic.audit_sql_lineage(
            diagnostic.DEFAULT_SQL.read_text(encoding="utf-8")
        )
        self.assertTrue(audit["validation_passed"], audit["failures"])
        self.assertEqual(audit["raw_action_branch_count"], 9)
        self.assertEqual(audit["raw_action_branch_column_counts"], [43] * 9)

    def test_decoded_call_contracts_are_renamed_from_contract_address(self) -> None:
        sql = diagnostic.DEFAULT_SQL.read_text(encoding="utf-8")
        for cte in ("take_calls_extended", "redo_calls_extended", "kick_calls"):
            body = diagnostic._extract_cte_body(sql, cte)
            self.assertRegex(body, r"c\.contract_address AS clipper_contract")


class LinkageTests(unittest.TestCase):
    def test_auction_key_includes_clipper(self) -> None:
        left = base_row(clipper_contract="0x01", auction_id="7")
        right = base_row(clipper_contract="0x02", auction_id="7")
        self.assertNotEqual(diagnostic.auction_key(left), diagnostic.auction_key(right))

    def test_bark_kick_requires_same_transaction(self) -> None:
        rows = linked_rows()
        rows[2]["transaction_hash"] = "0x" + "44" * 32
        report = diagnostic.reconcile_bark_kick(rows)
        self.assertEqual(report, {"matched": 0, "unmatched": 1, "multiply_matched": 0})

    def test_orphan_take_is_detected(self) -> None:
        orphan = base_row(
            action_type="take_success",
            source_table="maker_ethereum.clipper_evt_take",
            auction_id="999",
        )
        self.assertEqual(diagnostic.detect_orphans(linked_rows() + [orphan])["take"], 1)

    def test_unlinked_successful_call_is_rejected(self) -> None:
        rows = linked_rows()
        rows[1]["event_to_call_linkage_flag"] = False
        report = diagnostic.validate_rows(rows, sorted(diagnostic.REQUIRED_COLUMNS))
        self.assertFalse(report["validation_passed"])
        self.assertEqual(report["unlinked_successful_call_count"], 1)


class EconomicStateTests(unittest.TestCase):
    def test_wad_ray_rad_scaling(self) -> None:
        self.assertEqual(diagnostic.scale_maker(str(3 * 10**18), diagnostic.WAD), 3)
        self.assertEqual(diagnostic.scale_maker(str(4 * 10**27), diagnostic.RAY), 4)
        self.assertEqual(diagnostic.scale_maker(str(5 * 10**45), diagnostic.RAD), 5)

    def test_partial_take_order_and_formula(self) -> None:
        rows = linked_rows()
        first = base_row(
            action_type="take_success",
            source_table="maker_ethereum.clipper_evt_take",
            transaction_hash="0x" + "55" * 32,
            block_number=2,
            event_index=3,
            take_remaining_tab_raw=str(50 * 10**45),
            take_remaining_lot_raw=str(1 * 10**18),
            take_owe_raw=str(50 * 10**45),
            take_price_raw=str(50 * 10**27),
        )
        second = base_row(
            action_type="take_success",
            source_table="maker_ethereum.clipper_evt_take",
            transaction_hash="0x" + "66" * 32,
            block_number=3,
            event_index=4,
            take_remaining_tab_raw="0",
            take_remaining_lot_raw="0",
            take_owe_raw=str(50 * 10**45),
            take_price_raw=str(50 * 10**27),
        )
        report = diagnostic.validate_partial_takes(rows + [first, second])
        self.assertEqual(report["auctions_with_multiple_takes"], 1)
        self.assertEqual(report["non_monotonic_take_count"], 0)
        self.assertEqual(report["maximum_absolute_discrepancy"], 0.0)

    def test_terminal_classification_checks_remaining_state(self) -> None:
        target = linked_rows() + [base_row(
            action_type="take_success",
            source_table="maker_ethereum.clipper_evt_take",
            take_remaining_tab_raw="0",
            take_remaining_lot_raw=str(10**18),
            block_number=2,
        )]
        classification = diagnostic.classify_terminals(target)
        self.assertEqual(next(iter(classification.values())), "target_cleared")


class GasAndLegacyTests(unittest.TestCase):
    def test_multi_auction_transaction_is_detected_without_gas_allocation(self) -> None:
        tx_hash = "0x" + "77" * 32
        rows = [
            base_row(transaction_hash=tx_hash, clipper_contract="0x01", auction_id="1"),
            base_row(transaction_hash=tx_hash, clipper_contract="0x02", auction_id="1"),
        ]
        report = diagnostic.detect_multi_auction_transactions(rows)
        self.assertEqual(report["multi_auction_transaction_count"], 1)

    def test_nonzero_legacy_count_fails_validation(self) -> None:
        rows = linked_rows()
        for row in rows:
            row["legacy_cat_bite_count"] = 1
        report = diagnostic.validate_rows(rows, sorted(diagnostic.REQUIRED_COLUMNS))
        self.assertFalse(report["validation_passed"])
        self.assertEqual(report["legacy_cat_bite_count"], 1)


class PersistenceTests(unittest.TestCase):
    def test_atomic_persistence_does_not_use_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sql = root / "diagnostic.sql"
            sql.write_text(diagnostic.DEFAULT_SQL.read_text(encoding="utf-8"), encoding="utf-8")
            state = root / "state.json"
            payload = root / ".payload.json"
            raw = root / "raw.csv"
            validation = root / "validation.json"
            diagnostic.initialise_state(state, sql)
            diagnostic.update_state(
                state,
                "execution_submitted",
                query_id=123,
                query_url="https://dune.com/queries/123",
                execution_id="execution-1",
            )
            rows = [dict(row) for _ in range(50) for row in linked_rows()]
            # Make event and call keys unique while retaining realistic volume.
            for index, row in enumerate(rows):
                row["transaction_hash"] = "0x" + f"{index:064x}"
                row["auction_id"] = str(index // 4)
                if row["record_kind"] == "event":
                    row["event_index"] = index
                else:
                    row["call_trace_address"] = str(index)
            # Restore Bark/Kick same-transaction linkage in every four-row group.
            for offset in range(0, len(rows), 4):
                shared = "0x" + f"{offset:064x}"
                for row in rows[offset : offset + 4]:
                    row["transaction_hash"] = shared
            columns = sorted(diagnostic.REQUIRED_COLUMNS)
            diagnostic.write_json_atomic(payload, {
                "executionId": "execution-1",
                "state": "COMPLETED",
                "resultMetadata": {
                    "totalRowCount": len(rows),
                    "columns": [{"name": column, "type": "varchar"} for column in columns],
                    "executionCostCredits": "0.1",
                },
                "data": {"rows": rows},
            })
            closed_stdin = io.StringIO()
            closed_stdin.close()
            with patch("sys.stdin", closed_stdin):
                final = diagnostic.persist_result(
                    payload_path=payload,
                    state_path=state,
                    raw_path=raw,
                    validation_path=validation,
                )
            self.assertEqual(final["state"], "complete")
            self.assertTrue(raw.exists())
            self.assertFalse(raw.with_name("." + raw.name + ".partial").exists())
            self.assertEqual(len(raw.read_text(encoding="utf-8").splitlines()), 201)

    def test_failure_preserves_ids_and_prevents_second_state_initialisation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sql = root / "diagnostic.sql"
            sql.write_text(diagnostic.DEFAULT_SQL.read_text(encoding="utf-8"), encoding="utf-8")
            state = root / "state.json"
            diagnostic.initialise_state(state, sql)
            diagnostic.update_state(state, "failed", query_id=42, execution_id="execution-42")
            with self.assertRaises(diagnostic.LiquidationDiagnosticError):
                diagnostic.initialise_state(state, sql)
            recovered = diagnostic.load_json(state)
            self.assertEqual(recovered["query_id"], 42)
            self.assertEqual(recovered["execution_id"], "execution-42")


if __name__ == "__main__":
    unittest.main()
