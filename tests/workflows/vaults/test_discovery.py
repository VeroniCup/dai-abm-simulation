from decimal import Decimal
from pathlib import Path
import sys

from tests.support import REPOSITORY_ROOT

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from workflows.maintenance.archive import discover_vault_events as vaults


def frob_row(index: int, dink: int, dart: int) -> dict[str, str]:
    return {
        "block_time_utc": f"2023-02-01 0{index}:00:00.000 UTC",
        "block_number": str(16600000 + index),
        "transaction_hash": "0x" + f"{index + 1:064x}",
        "transaction_index": str(index), "trace_position": f"0.{index}",
        "source_contract": vaults.CANONICAL_VAT,
        "top_level_sender": "0x" + "1" * 40,
        "top_level_recipient": "0x" + "2" * 40,
        "success": "true", "ilk": "ETH-A", "urn": "0x" + f"{index + 3:040x}",
        "collateral_source": "0x" + "4" * 40,
        "debt_destination": "0x" + "5" * 40,
        "dink_raw": str(dink), "dart_raw": str(dart),
        "collateral_delta_wad": str(Decimal(dink) / Decimal(10) ** 18),
        "normalised_debt_delta_wad": str(Decimal(dart) / Decimal(10) ** 18),
        "is_deposit": str(dink > 0).lower(),
        "is_withdrawal": str(dink < 0).lower(),
        "is_debt_draw": str(dart > 0).lower(),
        "is_debt_repayment": str(dart < 0).lower(),
    }


def test_sql_is_bounded_and_uses_authoritative_sources():
    report = vaults.preflight()
    assert report["validation_passed"]
    assert report["network_client_present"] is False
    frob_sql = vaults.DIAGNOSTICS["frob"]["sql"].read_text()
    assert "maker_ethereum.vat_call_frob" in frob_sql
    assert "maker_ethereum.cdp_manager_call_frob" not in frob_sql
    for kind in ("liquidation", "ownership"):
        sql = vaults.DIAGNOSTICS[kind]["sql"].read_text()
        assert "ethereum.transactions" in sql
        assert "t.index AS transaction_index" in sql
        assert "call_tx_index AS transaction_index" not in sql
    assert "maker_ethereum.cdp_manager_call_give" in vaults.DIAGNOSTICS["ownership"]["sql"].read_text()


def test_signed_frob_directions_and_wad_scaling():
    rows = [
        frob_row(0, 10**18, 0), frob_row(1, -(10**18), 0),
        frob_row(2, 0, 2 * 10**18), frob_row(3, 0, -(2 * 10**18)),
    ]
    report = vaults.validate_frob(rows)
    assert report["validation_passed"]
    assert report["direction_counts"] == {
        "deposit": 1, "withdrawal": 1, "draw": 1, "repayment": 1,
    }


def test_unavailable_transaction_index_is_not_fabricated():
    rows = [
        frob_row(0, 10**18, 0), frob_row(1, -(10**18), 0),
        frob_row(2, 0, 10**18), frob_row(3, 0, -(10**18)),
    ]
    for row in rows:
        row["transaction_index"] = ""
    report = vaults.validate_frob(rows)
    assert report["validation_passed"]
    assert report["unavailable_transaction_index_count"] == 4
    assert "ethereum.transactions.index" in report["production_ordering_requirement"]


def test_dune_double_scaling_allows_only_machine_precision():
    rows = [
        frob_row(0, 10**18, 0), frob_row(1, -(10**18), 0),
        frob_row(2, 0, 920500656677329966115),
        frob_row(3, 0, -(920500656677329966115)),
    ]
    rows[2]["normalised_debt_delta_wad"] = "920.50065667733"
    rows[3]["normalised_debt_delta_wad"] = "-920.50065667733"
    assert vaults.validate_frob(rows)["validation_passed"]
    rows[2]["normalised_debt_delta_wad"] = "920.6"
    assert not vaults.validate_frob(rows)["validation_passed"]


def test_duplicate_source_calls_are_rejected():
    row = frob_row(0, 10**18, 10**18)
    report = vaults.validate_frob([row, dict(row)])
    assert not report["validation_passed"]
    assert any("duplicates a source call" in failure for failure in report["failures"])


def test_bark_grab_reconciliation():
    row = {
        "block_time_utc": "2022-06-13 00:00:00.000 UTC",
        "block_number": "14956500", "transaction_index": "3",
        "bark_event_index": "7", "bark_call_trace_position": "0.1.2",
        "grab_trace_position": "0.1.2.3", "ilk": "ETH-A",
        "bark_call_success": "true", "grab_success": "true",
        "vat_contract": vaults.CANONICAL_VAT,
        "dog_contract": "0x" + "d" * 40,
        "clipper_contract": "0x" + "e" * 40,
        "bark_keeper": "0x" + "f" * 40,
        "transaction_hash": "0x" + "a" * 64,
        "urn": "0x" + "b" * 40,
        "bark_ink_raw": str(5 * 10**18), "bark_art_raw": str(7 * 10**18),
        "bark_due_raw": str(8 * 10**45),
        "grab_dink_raw": str(-5 * 10**18), "grab_dart_raw": str(-7 * 10**18),
        "bark_collateral_wad": "5", "bark_normalised_debt_wad": "7",
        "bark_due_dai": "8", "grab_collateral_delta_wad": "-5",
        "grab_normalised_debt_delta_wad": "-7",
        "collateral_reconciles": "true", "normalised_debt_reconciles": "true",
        "transaction_bark_count": "2", "transaction_grab_count": "2",
        "urn_link_count": "1",
    }
    assert vaults.validate_liquidation([row])["validation_passed"]


def test_owner_mapping_requires_direct_urn_creation_and_tracks_give():
    open_row = {
        "ilk": "ETH-A", "manager_contract": vaults.CANONICAL_MANAGER,
        "urn_creator": vaults.CANONICAL_MANAGER,
        "transaction_hash": "0x" + "c" * 64,
        "urn": "0x" + "d" * 40, "creation_is_direct_child": "true",
        "owner_reconciles": "true", "cdp_id": "123",
        "block_number": "16600000", "transaction_index": "1",
        "source_position": "0.1", "event_type": "open",
        "source_table": "open+event+trace", "call_success": "true",
        "original_manager_owner": "0x" + "1" * 40, "new_owner": "",
    }
    give_row = dict(open_row)
    give_row.update({
        "block_number": "16600001", "transaction_index": "2",
        "transaction_hash": "0x" + "e" * 64,
        "source_position": "0.2", "event_type": "give",
        "source_table": "maker_ethereum.cdp_manager_call_give",
        "new_owner": "0x" + "2" * 40,
    })
    report = vaults.validate_ownership([open_row, give_row])
    assert report["validation_passed"]
    assert report["ownership_transfer_observed"]
    assert report["owner_histories"]["123"][-1]["effective_owner"] == "0x" + "2" * 40
    open_row["creation_is_direct_child"] = "false"
    assert not vaults.validate_ownership([open_row, give_row])["validation_passed"]


def test_diagnostic_sql_rejects_decoded_call_transaction_ordering():
    sql = vaults.DIAGNOSTICS["ownership"]["sql"].read_text().replace(
        "t.index AS transaction_index", "call_tx_index AS transaction_index"
    )
    report = vaults.validate_sql("ownership", sql)
    assert not report["validation_passed"]
