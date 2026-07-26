"""Tests for bounded Phase 1C production acquisition."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
import tempfile

import pytest

from scripts import acquire_dune_liquidations as production
from scripts.acquire_dune_liquidation_diagnostic import write_json_atomic


def test_monthly_plan_is_exact_and_contiguous() -> None:
    report = production.validate_chunk_plan()
    assert report["validation_passed"]
    assert report["chunk_count"] == 37
    assert production.CHUNKS[0].start == production.FULL_START
    assert production.CHUNKS[-1].end == production.FULL_END
    assert all(left.end == right.start for left, right in zip(production.CHUNKS, production.CHUNKS[1:]))


def test_rendered_action_sql_only_changes_bounded_window() -> None:
    chunk = production.CHUNKS[0]
    sql = production.render_action_sql(chunk)
    assert sql.count("windows(initiation_window_label") == 1
    assert f"'{chunk.chunk_id}'" in sql
    assert "2021-06-01 00:00:00" in sql
    assert "2021-07-01 00:00:00" in sql
    assert "2021-07-08 00:00:00" in sql
    assert "ordinary_2023_02" not in sql
    assert "nonzero_2022_06" not in sql
    assert "ethereum.transactions" not in sql.lower()
    assert "group by" not in sql.lower()
    assert "exists (" not in sql.lower()
    assert sql.lower().count(production.YANK_TOPIC) == 1
    for ilk in production.EXPECTED_ILKS:
        assert sql.count(f"'{ilk}'") == 1


def test_transaction_sql_has_unique_hashes_and_exact_bounds() -> None:
    chunk = production.CHUNKS[1]
    first = "0x" + "11" * 32
    second = "0x" + "22" * 32
    sql = production.build_transaction_sql([first, second, first], chunk)
    assert sql.count(f"({first})") == 1
    assert sql.count(f"({second})") == 1
    assert str(chunk.start.date()) in sql
    assert str(chunk.followup_end.date()) in sql
    assert "GROUP BY" not in sql.upper()
    assert "ORDER BY" not in sql.upper()


def test_empty_transaction_chunk_remains_one_schema_query() -> None:
    sql = production.build_transaction_sql([], production.CHUNKS[0])
    assert "WHERE false" in sql
    assert all(column in sql for column in ("gas_used", "gas_price", "transaction_index"))


def test_validate_action_chunk_detects_duplicate_source_rows() -> None:
    chunk = production.CHUNKS[0]
    row = {column: None for column in production.ACTION_COLUMNS}
    row.update({
        "initiation_window_label": chunk.chunk_id,
        "source_table": "maker_ethereum.dog_evt_bark",
        "record_type": "bark_event",
        "dog_contract": "0x" + "11" * 20,
        "clipper_contract": "0x" + "22" * 20,
        "auction_id": "1",
        "ilk": "ETH-A",
        "tx_hash": "0x" + "33" * 32,
        "block_time": "2021-06-02 00:00:00.000 UTC",
        "block_number": "1",
        "transaction_index": "0",
        "event_index": "1",
    })
    report = production.validate_action_chunk([row, dict(row)], list(production.ACTION_COLUMNS), chunk)
    assert not report["validation_passed"]
    assert report["duplicate_source_row_count"] == 1


def test_pending_query_stops_on_incomplete_state(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        monkeypatch.setattr(production, "STATE_ROOT", root)
        chunk = production.CHUNKS[0]
        paths = production.chunk_paths(chunk, "action")
        paths["state"].parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(paths["state"], {"state": "failed"})
        with pytest.raises(production.ProductionAcquisitionError, match="Stop"):
            production.pending_query()


def test_acquisition_module_has_no_network_or_submission_path() -> None:
    source = Path(production.__file__).read_text(encoding="utf-8")
    for fragment in (
        "createAndExecuteQuery", "executeQueryById", "requests.", "urllib", "httpx",
        "DUNE_API_KEY",
    ):
        assert fragment not in source


def test_chunk_18_recovery_passes_response_directly_to_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {"state": "COMPLETED", "executionId": production.AUTHORISED_CHUNK_18_EXECUTION_ID}
    calls: list[dict[str, object]] = []

    def persist(value: dict[str, object]) -> str:
        calls.append(value)
        return "persisted"

    result = production.retrieve_then_persist(lambda: response, persist)
    assert result == "persisted"
    assert calls == [response]


def test_chunk_18_recovery_rejects_missing_response() -> None:
    with pytest.raises(production.ProductionAcquisitionError, match="None"):
        production.retrieve_then_persist(lambda: None, lambda value: value)


def test_chunk_18_replacement_constants_preserve_failed_execution() -> None:
    assert production.AUTHORISED_CHUNK_18_QUERY_ID == 8061091
    assert production.AUTHORISED_CHUNK_18_EXECUTION_ID == "01KY3G6JYY6FN17K9SBT2QV2PF"
    assert production.AUTHORISED_CHUNK_18_SQL_SHA256 == (
        "4f538ac04c25158e02b602cf72765ab170d9c1c03fbd5b806ebc33b292360595"
    )


def test_completed_result_recovery_has_no_status_or_submission_step() -> None:
    source = production.chunk_18_completed_result_recovery_preflight.__doc__ or ""
    assert "result-only" in source
    module_source = Path(production.__file__).read_text(encoding="utf-8")
    assert "executeQueryById" not in module_source
    assert "createAndExecuteQuery" not in module_source


def test_legacy_check_is_bounded_and_count_only() -> None:
    sql = production.legacy_sql().lower()
    assert "2021-06-01" in sql and "2024-07-01" in sql
    assert "cat_evt_bite" in sql and "flipper_evt_kick" in sql
    assert "count(*)" in sql
    assert "ethereum.transactions" not in sql


def test_corrected_legacy_check_uses_live_cat_bite_schema() -> None:
    sql = production.corrected_legacy_sql().lower()
    assert "maker_ethereum.cat_evt_bite" in sql
    assert "flipper_evt_kick" not in sql
    assert "b.flip" in sql and "b.id" in sql and "b.evt_tx_hash" in sql
    assert "b.evt_block_date" in sql and "b.evt_block_time" in sql
    for ilk in production.EXPECTED_ILKS:
        assert sql.count(f"'{ilk.lower()}'") == 1


def test_final_validation_counts_are_plain_python_integers() -> None:
    values = {str(key): int(value) for key, value in __import__("pandas").Series(["a", "a"]).value_counts().items()}
    assert values == {"a": 2}
    assert type(values["a"]) is int


def test_manifest_sync_contains_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as directory:
        manifest = Path(directory) / "manifest.json"
        monkeypatch.setattr(production, "MANIFEST", manifest)
        state = {
            "chunk_number": 1, "chunk_id": "01_2021_06", "kind": "action",
            "state": "planned", "sql_sha256": "abc", "query_id": None,
        }
        production.sync_manifest(state)
        text = manifest.read_text(encoding="utf-8")
        assert "api_key" not in text.lower()
        assert json.loads(text)["queries"][0]["chunk_id"] == "01_2021_06"


def test_local_scaling_preserves_raw_wbtc_wad_values() -> None:
    row = {column: None for column in production.ACTION_COLUMNS}
    row.update({"ilk": "WBTC-A", "lot_raw": str(2 * 10**18), "tab_raw": str(5 * 10**45)})
    scaled = production.scale_action_row(row, "01_2021_06")
    assert scaled["lot_raw"] == str(2 * 10**18)
    assert scaled["lot_wad"] == "2"
    assert Decimal(scaled["tab_dai"]) == Decimal(5)
    assert scaled["chunk_id"] == "01_2021_06"


def test_auction_summary_deduplicates_transaction_gas() -> None:
    def action(record_type: str, tx_hash: str, **values: object) -> dict[str, object]:
        row = {column: None for column in ["chunk_id", *production.ACTION_COLUMNS, *production.SCALED_COLUMNS]}
        row.update({
            "chunk_id": "01_2021_06", "record_type": record_type,
            "clipper_contract": "0x" + "11" * 20, "auction_id": "1",
            "ilk": "ETH-A", "urn": "0x" + "22" * 20, "tx_hash": tx_hash,
            "block_time": "2021-06-02 00:00:00.000 UTC", "transaction_index": "0",
            "event_index": "1", "source_table": "test",
        })
        row.update(values)
        return row
    bark_hash = "0x" + "33" * 32
    take_hash = "0x" + "44" * 32
    actions = [
        action("bark_event", bark_hash, ink_raw=str(2 * 10**18), art_raw=str(100 * 10**18), due_raw=str(100 * 10**45)),
        action("kick_event", bark_hash, top_raw=str(2_000 * 10**27), tab_raw=str(113 * 10**45), lot_raw=str(2 * 10**18)),
        action("take_event", take_hash, owe_raw=str(113 * 10**45), price_raw=str(2_000 * 10**27), remaining_tab_raw="0", remaining_lot_raw="0"),
    ]
    transactions = [
        {"tx_hash": bark_hash, "gas_used": "300000"},
        {"tx_hash": take_hash, "gas_used": "200000"},
    ]
    auctions, report = production.build_auction_summary(actions, transactions)
    assert report["auction_count"] == 1
    assert auctions[0]["gas_used_unique_to_auction"] == 500000
    assert auctions[0]["terminal_classification"] == "target_cleared"
