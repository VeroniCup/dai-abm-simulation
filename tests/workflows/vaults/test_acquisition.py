from pathlib import Path
import json
import sys

import pandas as pd

from tests.support import REPOSITORY_ROOT

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from workflows.vaults import acquire as vaults


def mutation_row(call_type="frob"):
    row = {
        "block_time_utc": "2021-06-01 00:01:00.000 UTC", "block_number": "12500000",
        "transaction_hash": "0x" + "1" * 64, "transaction_index": "2",
        "trace_position": "0.10.2", "call_type": call_type, "ilk": "ETH-A",
        "urn": "0x" + "2" * 40, "source_urn": "", "destination_urn": "",
        "dink_raw": str(10**18), "dart_raw": str(-(10**18)),
        "call_success": "true", "source_contract": vaults.CANONICAL_VAT,
        "source_table": f"maker_ethereum.vat_call_{call_type}",
    }
    if call_type == "fork":
        row.update({"urn": "", "source_urn": "0x" + "2" * 40,
                    "destination_urn": "0x" + "3" * 40})
    return row


def test_month_plan_is_contiguous_and_complete():
    report = vaults.validate_plan()
    assert report["validation_passed"]
    assert report["chunk_count"] == 56


def test_month_sql_changes_only_bounded_dates_and_uses_transaction_index():
    first, second = vaults.MONTHS[:2]
    sql = vaults.render_month_sql(first)
    assert first.start.strftime("%Y-%m-%d") in sql
    assert first.end.strftime("%Y-%m-%d") in sql
    assert "index AS transaction_index" in sql
    assert "call_tx_index" not in sql
    assert "SELECT *" not in sql.upper()
    assert "ORDER BY" in sql.upper()
    assert "m.trace_address_raw" in sql
    assert vaults.render_month_sql(first) != vaults.render_month_sql(second)


def test_numeric_trace_order_is_not_lexicographic():
    assert vaults.parsed_trace_position({"trace": ""}, "trace", allow_serialised_root=True) == ()
    assert () < (0,) < (1,) < (1, 0) < (2,)
    assert vaults.trace_tuple("0.2") < vaults.trace_tuple("0.10")


def test_root_trace_requires_present_validated_serialisation():
    for row in ({}, {"trace": None}, {"trace": "bad.position"}):
        try:
            vaults.parsed_trace_position(row, "trace", allow_serialised_root=True)
        except vaults.VaultAcquisitionError:
            pass
        else:
            raise AssertionError(f"invalid trace metadata was accepted: {row}")
    try:
        vaults.parsed_trace_position({"trace": ""}, "trace", allow_serialised_root=False)
    except vaults.VaultAcquisitionError:
        pass
    else:
        raise AssertionError("unvalidated blank trace was accepted as root")


def test_root_calls_in_different_transactions_are_deterministic():
    chunk = vaults.MonthChunk(1, pd.Timestamp("2021-06-01T00:00:00Z"), pd.Timestamp("2021-07-01T00:00:00Z"))
    first = mutation_row()
    first["trace_position"] = ""
    second = dict(first)
    second["transaction_hash"] = "0x" + "9" * 64
    second["transaction_index"] = "3"
    report = vaults.validate_mutations([first, second], chunk)
    assert report["validation_passed"]
    assert report["valid_root_trace_count"] == 2


def test_same_transaction_root_collision_fails():
    chunk = vaults.MonthChunk(1, pd.Timestamp("2021-06-01T00:00:00Z"), pd.Timestamp("2021-07-01T00:00:00Z"))
    first = mutation_row()
    first["trace_position"] = ""
    second = dict(first)
    second["urn"] = "0x" + "8" * 40
    report = vaults.validate_mutations([first, second], chunk)
    assert not report["validation_passed"]
    assert report["unresolved_ordering_tie_count"] == 1


def test_mutation_validation_accepts_signed_values_and_fork_fields():
    chunk = vaults.MonthChunk(1, pd.Timestamp("2021-06-01T00:00:00Z"), pd.Timestamp("2021-07-01T00:00:00Z"))
    rows = [mutation_row(), mutation_row("fork")]
    rows[1]["transaction_hash"] = "0x" + "4" * 64
    rows[1]["trace_position"] = "0.11"
    report = vaults.validate_mutations(rows, chunk)
    assert report["validation_passed"]
    assert report["source_counts"]["fork"] == 1


def test_duplicate_source_calls_and_unresolved_ties_fail():
    chunk = vaults.MonthChunk(1, pd.Timestamp("2021-06-01T00:00:00Z"), pd.Timestamp("2021-07-01T00:00:00Z"))
    row = mutation_row()
    report = vaults.validate_mutations([row, dict(row)], chunk)
    assert not report["validation_passed"]


def test_acquisition_module_has_no_network_or_secret_path():
    source = Path(vaults.__file__).read_text()
    for forbidden in ("DUNE_API_KEY", "requests.", "urllib", "executeQuery"):
        assert forbidden not in source


def test_incomplete_state_cannot_be_silently_resumed(tmp_path, monkeypatch):
    chunk = vaults.MONTHS[0]
    monkeypatch.setattr(vaults, "RAW_CHUNK_ROOT", tmp_path / "raw")
    monkeypatch.setattr(vaults, "PROCESSED_CHUNK_ROOT", tmp_path / "processed")
    monkeypatch.setattr(vaults, "PROVENANCE_CHUNK_ROOT", tmp_path / "provenance")
    monkeypatch.setattr(vaults, "GENERATED_SQL_ROOT", tmp_path / "sql")
    monkeypatch.setattr(vaults, "INGRESS_ROOT", tmp_path / "ingress")
    monkeypatch.setattr(vaults, "MANIFEST_PATH", tmp_path / "manifest.json")
    state = vaults.initialise_month(chunk)
    assert state["state"] == "planned"
    try:
        vaults.initialise_month(chunk)
    except vaults.VaultAcquisitionError as error:
        assert "replacement is not authorised" in str(error)
    else:
        raise AssertionError("incomplete chunk was silently resumed")


def _page_payload(rows, total):
    return {
        "state": "COMPLETED",
        "data": {"rows": rows},
        "resultMetadata": {
            "totalRowCount": total,
            "columns": [{"name": column} for column in vaults.MUTATION_COLUMNS],
        },
    }


def _ordered_rows(count):
    rows = []
    for index in range(count):
        row = mutation_row()
        row["block_number"] = str(12_500_000 + index)
        row["transaction_hash"] = f"0x{index + 1:064x}"
        row["trace_position"] = str(index)
        rows.append(row)
    return rows


def test_pagination_boundary_plans():
    assert vaults.page_plan(32_000) == ((0, 32_000),)
    assert vaults.page_plan(32_001) == ((0, 32_000), (32_000, 1))
    assert vaults.page_plan(43_081) == ((0, 32_000), (32_000, 11_081))


def test_paginated_rows_reject_gaps_overlaps_and_inconsistent_totals():
    rows = _ordered_rows(3)
    valid = [(0, _page_payload(rows[:2], 3)), (2, _page_payload(rows[2:], 3))]
    combined, metadata = vaults.validate_page_sequence(
        valid, expected_total=3, page_limit=2, ordered_sql=True
    )
    assert len(combined) == 3
    assert metadata["page_count"] == 2
    for bad in (
        [(0, valid[0][1]), (1, valid[1][1])],
        [(0, valid[0][1]), (3, valid[1][1])],
    ):
        try:
            vaults.validate_page_sequence(
                bad, expected_total=3, page_limit=2, ordered_sql=True
            )
        except vaults.VaultAcquisitionError:
            pass
        else:
            raise AssertionError("page gap or overlap was accepted")
    inconsistent = [
        (0, _page_payload(rows[:2], 3)),
        (2, _page_payload(rows[2:], 4)),
    ]
    try:
        vaults.validate_page_sequence(
            inconsistent, expected_total=3, page_limit=2, ordered_sql=True
        )
    except vaults.VaultAcquisitionError:
        pass
    else:
        raise AssertionError("inconsistent API totals were accepted")


def test_paginated_rows_reject_duplicate_or_invalid_boundary():
    rows = _ordered_rows(3)
    duplicate = dict(rows[1])
    duplicate_pages = [
        (0, _page_payload(rows[:2], 3)),
        (2, _page_payload([duplicate], 3)),
    ]
    reversed_pages = [
        (0, _page_payload(rows[1:], 3)),
        (2, _page_payload([rows[0]], 3)),
    ]
    for pages in (duplicate_pages, reversed_pages):
        try:
            vaults.validate_page_sequence(
                pages, expected_total=3, page_limit=2, ordered_sql=True
            )
        except vaults.VaultAcquisitionError:
            pass
        else:
            raise AssertionError("invalid deterministic page boundary was accepted")


def test_numeric_trace_order_across_page_boundary():
    rows = _ordered_rows(2)
    rows[0]["block_number"] = rows[1]["block_number"] = "12500000"
    rows[0]["transaction_index"] = rows[1]["transaction_index"] = "2"
    rows[0]["trace_position"] = "0.2"
    rows[1]["trace_position"] = "0.10"
    pages = [
        (0, _page_payload([rows[0]], 2)),
        (1, _page_payload([rows[1]], 2)),
    ]
    combined, _ = vaults.validate_page_sequence(
        pages, expected_total=2, page_limit=1, ordered_sql=True
    )
    assert [row["trace_position"] for row in combined] == ["0.2", "0.10"]


def test_unordered_results_are_never_paginated():
    rows = _ordered_rows(2)
    try:
        vaults.validate_page_sequence(
            [(0, _page_payload(rows, 2))],
            expected_total=2,
            page_limit=2,
            ordered_sql=False,
        )
    except vaults.VaultAcquisitionError as error:
        assert "deterministic ordering" in str(error)
    else:
        raise AssertionError("unordered result pagination was accepted")
    assert vaults.query_has_deterministic_order(
        vaults.render_month_sql(vaults.MONTHS[0])
    )


def test_persisted_first_page_is_resumable(tmp_path, monkeypatch):
    chunk = vaults.MONTHS[0]
    monkeypatch.setattr(vaults, "RAW_CHUNK_ROOT", tmp_path)
    first = vaults.page_path(chunk, 0, 2)
    first.parent.mkdir(parents=True)
    first.write_text(json.dumps(_page_payload(_ordered_rows(2), 3)))
    assert vaults.persisted_page_offsets(chunk, 3, page_limit=2) == (0,)


def test_subwindow_replacement_is_contiguous_and_exclusive():
    report = vaults.validate_subwindow_coverage(vaults.CHUNK_05_SUBWINDOWS)
    assert report["validation_passed"]
    broken = (
        vaults.CHUNK_05_SUBWINDOWS[0],
        vaults.Subwindow(
            "bad", "05_2020_03",
            pd.Timestamp("2020-03-17T00:00:00Z"),
            pd.Timestamp("2020-04-01T00:00:00Z"),
        ),
    )
    assert not vaults.validate_subwindow_coverage(broken)["validation_passed"]


def test_direct_result_envelope_is_normalised():
    rows = _ordered_rows(2)
    payload = {
        "state": "QUERY_STATE_COMPLETED",
        "result": {
            "rows": rows,
            "metadata": {
                "column_names": list(vaults.MUTATION_COLUMNS),
                "total_row_count": 2,
            },
        },
    }
    parsed, columns, metadata = vaults._extract(payload)
    assert parsed == rows
    assert tuple(columns) == vaults.MUTATION_COLUMNS
    assert metadata["totalRowCount"] == 2
