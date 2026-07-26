from decimal import Decimal
import csv
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import acquire_phase1e_b_representative_vaults as representative
from scripts import repair_phase1e_b_quiet_rates as rate_repair


def _synthetic_mutation_row(
    index: int,
    *,
    call_type: str = "frob",
    trace_position: str = "",
) -> dict[str, object]:
    values: dict[str, object] = {
        "block_time_utc": f"2022-05-05 00:00:0{index}.000 UTC",
        "block_number": 100 + index,
        "transaction_hash": "0x" + f"{index + 1:064x}",
        "transaction_index": index,
        "trace_position": trace_position,
        "call_type": call_type,
        "ilk": "ETH-A",
        "urn": "0x" + f"{index + 1:040x}",
        "source_urn": None,
        "destination_urn": None,
        "dink_raw": str(10 if index % 2 == 0 else -10),
        "dart_raw": "0",
        "call_success": True,
        "source_contract": representative.CANONICAL_VAT,
        "source_table": f"maker_ethereum.vat_call_{call_type}",
    }
    if call_type == "fork":
        values["urn"] = None
        values["source_urn"] = "0x" + "a" * 40
        values["destination_urn"] = "0x" + "b" * 40
    return {
        column: values[column]
        for column in representative.MUTATION_COLUMNS
    }


def _write_typed_page(
    path: Path,
    rows: list[dict[str, object]],
    *,
    total: int | None = None,
    columns: tuple[str, ...] | None = None,
) -> None:
    columns = columns or representative.MUTATION_COLUMNS
    payload = {
        "executionId": "01KYFDPTRNR88V6GFBY26EF3QW",
        "state": "COMPLETED",
        "resultMetadata": {
            "columns": [
                {"name": column, "type": "varchar"} for column in columns
            ],
            "totalRowCount": len(rows) if total is None else total,
            "executionCostCredits": "0.666",
        },
        "data": {"rows": rows},
    }
    path.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _patch_recovery_paths(monkeypatch, tmp_path: Path) -> dict[str, Path]:
    raw = tmp_path / "raw" / "vat_mutations.csv"
    provenance = tmp_path / "provenance"
    paths = {
        "sql": tmp_path / "query.sql",
        "state": provenance / "vat_mutations.state.json",
        "metadata": provenance / "vat_mutations.metadata.json",
        "validation": provenance / "vat_mutations.validation.json",
        "raw": raw,
        "pages": raw.parent / "pages",
    }
    paths["state"].parent.mkdir(parents=True)
    paths["state"].write_text(
        json.dumps({
            "state": "halted_after_result_retrieval_before_persistence",
            "query_id": 8114886,
            "execution_id": "01KYFDPTRNR88V6GFBY26EF3QW",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        representative, "stream_paths", lambda _window, _stream: paths
    )
    monkeypatch.setattr(
        representative,
        "window_paths",
        lambda _window: {
            "provenance": provenance,
            "raw": tmp_path / "raw",
            "processed": tmp_path / "processed",
            "sql": tmp_path / "sql",
        },
    )
    monkeypatch.setattr(representative, "relative", lambda path: str(path))
    return paths


def test_authorised_window_boundaries_are_exact():
    quiet = representative.WINDOWS["quiet_mature"]
    svb = representative.WINDOWS["usdc_svb"]
    assert quiet.start == pd.Timestamp("2024-02-01T00:00:00Z")
    assert quiet.end == pd.Timestamp("2024-03-01T00:00:00Z")
    assert svb.start == pd.Timestamp("2023-03-06T00:00:00Z")
    assert svb.end == pd.Timestamp("2023-03-20T00:00:00Z")
    terra = representative.WINDOWS["terra_cefi"]
    assert terra.start == pd.Timestamp("2022-05-05T00:00:00Z")
    assert terra.end == pd.Timestamp("2022-06-20T00:00:00Z")
    assert (terra.end - terra.start) == pd.Timedelta(days=46)


def test_boundary_sql_uses_authoritative_replay_without_future_leakage():
    window = representative.WINDOWS["quiet_mature"]
    sql = representative.render_boundary_sql(window)
    assert "vat_call_frob" in sql
    assert "vat_call_fork" in sql
    assert "vat_call_grab" in sql
    assert "vat_call_slip" not in sql
    assert "vat_call_urns" not in sql
    assert "2024-02-01 00:00:00 UTC" in sql
    assert "2024-03-01 00:00:00 UTC" in sql
    assert "ORDER BY b.ilk, b.urn" in sql
    assert "SELECT *" not in sql.upper()


def test_window_mutation_sql_has_numeric_deterministic_order():
    sql = representative.render_mutation_sql(
        representative.WINDOWS["usdc_svb"]
    )
    assert "m.trace_address_raw" in sql
    assert "ORDER BY" in sql
    assert "call_tx_index" not in sql
    assert "ethereum.transactions" in sql


def test_rate_sql_is_latest_pre_window_plus_bounded_window_only():
    window = representative.WINDOWS["quiet_mature"]
    sql = representative.render_rate_sql(window)
    assert "pre_window_rank = 1" in sql
    assert "window_drips" in sql
    assert "window_folds" in sql
    assert "2024-02-01 00:00:00 UTC" in sql
    assert "2024-03-01 00:00:00 UTC" in sql
    assert "ORDER BY" in sql


def test_method_b_rate_sql_is_strictly_bounded_and_sparse():
    sql = representative.render_in_window_rate_sql(
        representative.WINDOWS["quiet_mature"]
    )
    assert "historical_drips" not in sql
    assert "2024-02-01 00:00:00 UTC" in sql
    assert "2024-03-01 00:00:00 UTC" in sql
    assert "SELECT *" not in sql.upper()
    assert "ethereum.transactions" in sql
    assert "vat_call_frob" not in sql
    assert "ORDER BY" in sql


def test_usdc_svb_effective_rate_stream_reuses_bounded_method_b():
    window = representative.WINDOWS["usdc_svb"]
    sql = representative.render_sql(window, "effective_rates")
    assert "historical_drips" not in sql
    assert "2023-03-06 00:00:00 UTC" in sql
    assert "2023-03-20 00:00:00 UTC" in sql
    assert "SELECT *" not in sql.upper()


def test_stablecoin_stress_window_preserves_approved_six_ilk_scope():
    assert representative.TARGET_ILKS == (
        "ETH-A", "ETH-B", "ETH-C", "WBTC-A", "WBTC-B", "WBTC-C"
    )
    assert not any(
        "USDC" in ilk or "PSM" in ilk for ilk in representative.TARGET_ILKS
    )


def test_ownership_is_bounded_and_nullable_downstream():
    sql = representative.render_ownership_sql(
        representative.WINDOWS["quiet_mature"],
        ["0x" + "1" * 40],
    )
    assert "selected_urns" in sql
    assert "cdp_manager_call_open" in sql
    assert "cdp_manager_call_give" in sql
    assert "ethereum.traces" in sql
    assert "ORDER BY" in sql
    assert representative._ownership_at([], "0x" + "1" * 40,
                                        pd.Timestamp("2024-02-01T00:00:00Z")) == ("", "")


def test_page_boundaries_cover_32001_without_overlap():
    assert representative.page_plan(32_000) == ((0, 32_000),)
    assert representative.page_plan(32_001) == (
        (0, 32_000), (32_000, 1)
    )


def test_typed_dune_page_is_normalised_without_rewriting_rows():
    payload = {
        "state": "COMPLETED",
        "data": {"rows": [{"ilk": "ETH-A", "value": "1"}]},
        "resultMetadata": {
            "columns": [
                {"name": "ilk", "type": "varchar"},
                {"name": "value", "type": "varchar"},
            ],
            "totalRowCount": 1,
        },
    }
    rows, columns, total = representative._normalise_page(payload)
    assert rows == payload["data"]["rows"]
    assert columns == ["ilk", "value"]
    assert total == 1


def test_typed_result_rows_are_consumed_incrementally(tmp_path):
    path = tmp_path / "page.json"
    rows = [
        _synthetic_mutation_row(0),
        _synthetic_mutation_row(1, trace_position="1.10"),
    ]
    _write_typed_page(path, rows)
    header = representative.typed_result_file_metadata(path)
    assert header["resultMetadata"]["totalRowCount"] == 2
    assert list(representative.iter_typed_result_rows(
        path, read_size=37
    )) == rows


def test_recovery_writes_one_header_flushes_and_promotes_atomically(
    monkeypatch, tmp_path,
):
    paths = _patch_recovery_paths(monkeypatch, tmp_path)
    page = tmp_path / "page.json"
    rows = [_synthetic_mutation_row(index) for index in range(3)]
    _write_typed_page(page, rows)
    result = representative.persist_recovered_typed_mutations(
        window=representative.WINDOWS["terra_cefi"],
        page_path=page,
        usage_before=Decimal("10"),
        usage_after=Decimal("10"),
        local_flush_rows=2,
    )
    assert result["validation"]["persisted_row_count"] == 3
    assert result["validation"]["header_occurrence_count"] == 1
    assert paths["raw"].exists()
    assert not (
        paths["raw"].parent / ".mutation_result.recovery.rows.tmp"
    ).exists()
    with paths["raw"].open(newline="", encoding="utf-8") as handle:
        parsed = list(csv.DictReader(handle))
    assert len(parsed) == 3
    assert tuple(parsed[0]) == representative.MUTATION_COLUMNS


def test_incomplete_recovery_is_not_promoted(monkeypatch, tmp_path):
    paths = _patch_recovery_paths(monkeypatch, tmp_path)
    page = tmp_path / "page.json"
    _write_typed_page(
        page, [_synthetic_mutation_row(index) for index in range(3)]
    )
    with pytest.raises(
        representative.RepresentativeAcquisitionError,
        match="injected incomplete-stream failure",
    ):
        representative.persist_recovered_typed_mutations(
            window=representative.WINDOWS["terra_cefi"],
            page_path=page,
            usage_before=Decimal("10"),
            usage_after=Decimal("10"),
            local_flush_rows=1,
            fail_after_rows=2,
        )
    assert not paths["raw"].exists()
    assert (
        paths["raw"].parent
        / ".mutation_result.recovery.rows.tmp.invalid"
    ).exists()


def test_recovery_rejects_schema_and_api_total_mismatch(
    monkeypatch, tmp_path,
):
    paths = _patch_recovery_paths(monkeypatch, tmp_path)
    page = tmp_path / "wrong_schema.json"
    rows = [_synthetic_mutation_row(0)]
    _write_typed_page(
        page, rows, columns=representative.MUTATION_COLUMNS[:-1]
    )
    with pytest.raises(
        representative.RepresentativeAcquisitionError,
        match="schema or API total",
    ):
        representative.persist_recovered_typed_mutations(
            window=representative.WINDOWS["terra_cefi"],
            page_path=page,
            usage_before=Decimal("10"),
            usage_after=Decimal("10"),
        )
    assert not paths["raw"].exists()

    page = tmp_path / "wrong_total.json"
    _write_typed_page(page, rows, total=2)
    with pytest.raises(
        representative.RepresentativeAcquisitionError,
        match="API reported 2",
    ):
        representative.persist_recovered_typed_mutations(
            window=representative.WINDOWS["terra_cefi"],
            page_path=page,
            usage_before=Decimal("10"),
            usage_after=Decimal("10"),
        )
    assert not paths["raw"].exists()


def test_recovery_rejects_duplicate_source_key(monkeypatch, tmp_path):
    paths = _patch_recovery_paths(monkeypatch, tmp_path)
    page = tmp_path / "duplicate.json"
    row = _synthetic_mutation_row(0)
    _write_typed_page(page, [row, dict(row)])
    with pytest.raises(
        representative.RepresentativeAcquisitionError,
        match="duplicates a source call",
    ):
        representative.persist_recovered_typed_mutations(
            window=representative.WINDOWS["terra_cefi"],
            page_path=page,
            usage_before=Decimal("10"),
            usage_after=Decimal("10"),
        )
    assert not paths["raw"].exists()


def test_result_request_guard_prevents_retry():
    guard = representative.ResultRequestGuard()
    guard.mark_request()
    assert guard.requests_used == 1
    with pytest.raises(
        representative.RepresentativeAcquisitionError,
        match="exhausted",
    ):
        guard.mark_request()


def test_credit_cap_and_reserve_are_both_enforced():
    good = representative.enforce_credit_gate(
        starting_usage=Decimal("800"),
        current_usage=Decimal("900"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("200"),
    )
    assert good["passed"]
    cap = representative.enforce_credit_gate(
        starting_usage=Decimal("800"),
        current_usage=Decimal("1300"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("101"),
    )
    assert not cap["passed"]
    reserve = representative.enforce_credit_gate(
        starting_usage=Decimal("800"),
        current_usage=Decimal("1500"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("201"),
    )
    assert not reserve["passed"]


def test_rate_repair_credit_cap_and_1400_reserve_are_enforced():
    assert representative.enforce_rate_repair_credit_gate(
        current_usage=Decimal("915"),
        quota=Decimal("2500"),
        projected_cost=Decimal("30"),
    )["passed"]
    assert not representative.enforce_rate_repair_credit_gate(
        current_usage=Decimal("915"),
        quota=Decimal("2500"),
        projected_cost=Decimal("101"),
    )["passed"]
    assert not representative.enforce_rate_repair_credit_gate(
        current_usage=Decimal("1050"),
        quota=Decimal("2500"),
        projected_cost=Decimal("51"),
    )["passed"]


def test_usdc_svb_180_credit_cap_and_1350_reserve_are_enforced():
    assert representative.enforce_usdc_svb_credit_gate(
        starting_usage=Decimal("926.545"),
        current_usage=Decimal("926.545"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("132"),
    )["passed"]
    assert not representative.enforce_usdc_svb_credit_gate(
        starting_usage=Decimal("926.545"),
        current_usage=Decimal("926.545"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("181"),
    )["passed"]


def test_terra_cefi_300_credit_cap_1100_reserve_and_query_stop():
    assert representative.enforce_terra_cefi_credit_gate(
        starting_usage=Decimal("1017.345"),
        current_usage=Decimal("1017.345"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("240"),
    )["passed"]
    assert not representative.enforce_terra_cefi_credit_gate(
        starting_usage=Decimal("1017.345"),
        current_usage=Decimal("1017.345"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("301"),
    )["passed"]
    assert not representative.enforce_terra_cefi_credit_gate(
        starting_usage=Decimal("1017.345"),
        current_usage=Decimal("1290"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("111"),
    )["passed"]
    assert not representative.enforce_terra_cefi_credit_gate(
        starting_usage=Decimal("1017.345"),
        current_usage=Decimal("1017.345"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("20"),
        last_query_observed_cost=Decimal("101"),
        last_query_estimated_cost=Decimal("60"),
    )["passed"]
    assert not representative.enforce_terra_cefi_credit_gate(
        starting_usage=Decimal("1017.345"),
        current_usage=Decimal("1017.345"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("20"),
        last_query_observed_cost=Decimal("21"),
        last_query_estimated_cost=Decimal("10"),
    )["passed"]


def test_terra_continuation_180_credit_cap_1250_reserve_and_stream_limits():
    assert representative.enforce_terra_continuation_credit_gate(
        starting_usage=Decimal("1018.403"),
        current_usage=Decimal("1018.403"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("105"),
    )["passed"]
    assert not representative.enforce_terra_continuation_credit_gate(
        starting_usage=Decimal("1018.403"),
        current_usage=Decimal("1018.403"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("181"),
    )["passed"]
    assert not representative.enforce_terra_continuation_credit_gate(
        starting_usage=Decimal("1018.403"),
        current_usage=Decimal("1200"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("51"),
    )["passed"]
    assert not representative.enforce_terra_continuation_credit_gate(
        starting_usage=Decimal("1018.403"),
        current_usage=Decimal("1018.403"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("0"),
        stream="ownership_history",
        last_query_observed_cost=Decimal("101"),
        last_query_estimated_cost=Decimal("60"),
    )["passed"]
    assert not representative.enforce_terra_continuation_credit_gate(
        starting_usage=Decimal("1018.403"),
        current_usage=Decimal("1018.403"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("0"),
        stream="effective_rates",
        last_query_observed_cost=Decimal("51"),
        last_query_estimated_cost=Decimal("30"),
    )["passed"]
    assert not representative.enforce_terra_continuation_credit_gate(
        starting_usage=Decimal("1018.403"),
        current_usage=Decimal("1018.403"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("0"),
        stream="effective_rates",
        last_query_observed_cost=Decimal("21"),
        last_query_estimated_cost=Decimal("10"),
    )["passed"]


def test_terra_ownership_uses_authorised_raw_directory():
    paths = representative.stream_paths(
        representative.WINDOWS["terra_cefi"], "ownership_history"
    )
    assert paths["raw"].parent.name == "ownership"
    assert paths["pages"].parent.name == "ownership"


def test_terra_active_ilk_gate_checks_both_boundaries():
    window = representative.WINDOWS["terra_cefi"]
    rows = []
    for timestamp in (
        window.start, window.end - pd.Timedelta(hours=1)
    ):
        for ilk in representative.TARGET_ILKS:
            rows.append({
                "timestamp_utc": timestamp,
                "ilk": ilk,
                "ilk_active": True,
            })
    valid = representative.validate_active_ilks(window, pd.DataFrame(rows))
    assert valid["validation_passed"]
    rows[-1]["ilk_active"] = False
    invalid = representative.validate_active_ilks(
        window, pd.DataFrame(rows)
    )
    assert not invalid["validation_passed"]
    assert not representative.enforce_usdc_svb_credit_gate(
        starting_usage=Decimal("926.545"),
        current_usage=Decimal("1060"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("91"),
    )["passed"]
    assert not representative.enforce_usdc_svb_credit_gate(
        starting_usage=Decimal("926.545"),
        current_usage=Decimal("926.545"),
        quota=Decimal("2500"),
        projected_remaining_cost=Decimal("20"),
        last_query_observed_cost=Decimal("21"),
        last_query_estimated_cost=Decimal("10"),
    )["passed"]


def test_boundary_validation_rejects_negative_or_future_state():
    window = representative.WINDOWS["quiet_mature"]
    row = {
        "ilk": "ETH-A", "urn": "0x" + "2" * 40,
        "opening_ink_raw": "-1", "opening_art_raw": "0",
        "end_ink_raw": "0", "end_art_raw": "0",
        "pre_window_mutation_count": "1", "window_mutation_count": "1",
        "last_pre_window_mutation_time_utc": "2024-01-01T00:00:00Z",
        "last_window_mutation_time_utc": "2024-02-02T00:00:00Z",
        "opening_rate_raw_ray": str(10**27),
        "opening_rate_effective_time_utc": "2024-01-01T00:00:00Z",
        "end_rate_raw_ray": str(10**27),
        "end_rate_effective_time_utc": "2024-02-15T00:00:00Z",
        "canonical_vat_contract": representative.CANONICAL_VAT,
    }
    assert not representative.validate_boundary_rows([row], window)[
        "validation_passed"
    ]


def test_exact_debt_calculation_uses_art_times_rate():
    art_raw = 5 * 10**18
    rate_raw = 2 * 10**27
    debt = Decimal(art_raw) * Decimal(rate_raw) / Decimal(10**45)
    assert debt == Decimal("10")


def _boundary_rows():
    rows = []
    for index, ilk in enumerate(representative.TARGET_ILKS):
        opening = 10**27 + index
        rows.append({
            "ilk": ilk,
            "opening_rate_raw_ray": str(opening),
            "opening_rate_effective_time_utc": "2024-01-31T12:00:00Z",
            "end_rate_raw_ray": str(
                opening + 10 if ilk == "ETH-A" else opening
            ),
        })
    return rows


def _rate_call(
    *,
    ilk="ETH-A",
    record_type="drip",
    rate=str(10**27 + 10),
    delta="10",
    trace="0",
):
    return {
        "effective_time_utc": "2024-02-02T12:00:00Z",
        "block_number": "100",
        "transaction_hash": "0x" + "a" * 64,
        "transaction_index": "2",
        "trace_position": trace,
        "ilk": ilk,
        "rate_record_type": record_type,
        "raw_rate_ray": rate if record_type == "drip" else "",
        "raw_rate_delta": delta if record_type == "fold" else "",
        "call_success": "true",
        "source_contract": (
            representative.CANONICAL_JUG
            if record_type == "drip" else representative.CANONICAL_VAT
        ),
        "source_table": (
            "maker_ethereum.jug_call_drip"
            if record_type == "drip" else "maker_ethereum.vat_call_fold"
        ),
    }


def test_sparse_rate_builder_selects_one_opening_row_per_ilk_and_reconciles_fold():
    calls = [
        _rate_call(record_type="drip", trace="0"),
        _rate_call(record_type="fold", trace="0.0"),
    ]
    sparse, validation = representative.build_sparse_effective_rates(
        _boundary_rows(), calls, representative.WINDOWS["quiet_mature"]
    )
    assert validation["validation_passed"]
    assert validation["opening_row_count"] == 6
    assert validation["drip_count"] == 1
    assert validation["fold_count"] == 1
    assert validation["fold_drip_reconciliation_failure_count"] == 0
    assert len(sparse) == 8


def test_sparse_rate_builder_accepts_zero_in_window_changes():
    boundary = _boundary_rows()
    boundary[0]["end_rate_raw_ray"] = boundary[0]["opening_rate_raw_ray"]
    sparse, validation = representative.build_sparse_effective_rates(
        boundary, [], representative.WINDOWS["quiet_mature"]
    )
    assert validation["validation_passed"]
    assert validation["opening_row_count"] == 6
    assert validation["drip_count"] == 0
    assert validation["fold_count"] == 0
    assert len(sparse) == 6


def test_sparse_rate_builder_orders_repeated_same_block_drip_fold_pairs():
    first_rate = 10**27 + 10
    second_rate = 10**27 + 25
    calls = [
        _rate_call(
            record_type="drip", rate=str(first_rate), trace="0"
        ),
        _rate_call(
            record_type="fold", delta="10", trace="0.0"
        ),
        _rate_call(
            record_type="drip", rate=str(second_rate), trace="1"
        ),
        _rate_call(
            record_type="fold", delta="15", trace="1.0"
        ),
    ]
    boundary = _boundary_rows()
    boundary[0]["end_rate_raw_ray"] = str(second_rate)
    sparse, validation = representative.build_sparse_effective_rates(
        boundary, calls, representative.WINDOWS["quiet_mature"]
    )
    assert validation["validation_passed"]
    eth_drips = [
        row for row in sparse
        if row["ilk"] == "ETH-A" and row["source_type"] == "drip"
    ]
    assert [row["trace_position"] for row in eth_drips] == ["0", "1"]
    assert [row["resulting_rate_raw_ray"] for row in eth_drips] == [
        str(first_rate), str(second_rate)
    ]


def test_sparse_rate_builder_rejects_duplicate_source_calls():
    call = _rate_call(record_type="drip", trace="0")
    _, validation = representative.build_sparse_effective_rates(
        _boundary_rows(), [call, dict(call)],
        representative.WINDOWS["quiet_mature"],
    )
    assert not validation["validation_passed"]


def test_sparse_rate_builder_rejects_future_or_duplicate_opening_identity():
    rows = _boundary_rows()
    rows.append({
        **rows[0],
        "opening_rate_raw_ray": str(10**27 + 99),
    })
    _, validation = representative.build_sparse_effective_rates(
        rows, [], representative.WINDOWS["quiet_mature"]
    )
    assert not validation["validation_passed"]


def test_frob_and_fork_expand_to_balanced_urn_level_mutations():
    common = {
        "block_time_utc": "2024-02-02T12:00:00Z",
        "block_number": "100",
        "transaction_hash": "0x" + "a" * 64,
        "transaction_index": "2",
        "ilk": "ETH-A",
        "call_success": "true",
        "source_contract": representative.CANONICAL_VAT,
        "source_table": "maker_ethereum.vat_call_frob",
    }
    mutations = [
        {
            **common,
            "trace_position": "0",
            "call_type": "frob",
            "urn": "0x" + "1" * 40,
            "source_urn": "",
            "destination_urn": "",
            "dink_raw": "5",
            "dart_raw": "7",
        },
        {
            **common,
            "trace_position": "1",
            "call_type": "fork",
            "urn": "",
            "source_urn": "0x" + "1" * 40,
            "destination_urn": "0x" + "2" * 40,
            "dink_raw": "3",
            "dart_raw": "4",
            "source_table": "maker_ethereum.vat_call_fork",
        },
    ]
    expanded = representative.expand_economic_mutations(mutations)
    assert len(expanded) == 3
    assert expanded[0]["observed_or_derived"] == "observed_call"
    fork_rows = expanded[1:]
    assert [row["fork_side"] for row in fork_rows] == [
        "source", "destination"
    ]
    assert sum(row["economic_dink_raw"] for row in fork_rows) == 0
    assert sum(row["economic_dart_raw"] for row in fork_rows) == 0


def test_combined_frob_adjustment_is_not_forced_into_one_sign_class():
    assert representative.classify_economic_mutation({
        "call_type": "frob",
        "economic_dink_raw": 10,
        "economic_dart_raw": -5,
        "fork_side": "",
    }) == "combined_adjustment"


def test_bark_grab_linkage_uses_exact_signed_amounts():
    tx_hash = "0x" + "a" * 64
    urn = "0x" + "1" * 40
    bark = {
        "transaction_hash": tx_hash,
        "ilk": "ETH-A",
        "urn": urn,
        "auction_id": "7",
        "ink_raw": "10",
        "art_raw": "5",
    }
    grab = {
        "transaction_hash": tx_hash,
        "ilk": "ETH-A",
        "urn": urn,
        "call_type": "grab",
        "dink_raw": "-10",
        "dart_raw": "-5",
    }
    report = representative.validate_bark_grab_rows([bark], [grab])
    assert report["validation_passed"]
    assert report["matched_bark_count"] == 1
    assert report["matched_grab_count"] == 1
    assert "Vat.grab is the mutation" in report["economic_treatment"]


def test_grab_close_fractions_use_pre_grab_state_and_exact_debt_semantics():
    metrics = representative.liquidation_close_fraction_metrics(
        pre_ink_raw=100,
        pre_art_raw=80,
        dink_raw=-25,
        dart_raw=-40,
        rate_raw_ray=10**27,
    )
    assert metrics["post_grab_ink_raw"] == 75
    assert metrics["post_grab_art_raw"] == 40
    assert Decimal(metrics["debt_close_fraction"]) == Decimal("0.5")
    assert Decimal(metrics["collateral_close_fraction"]) == Decimal("0.25")
    assert not metrics["full_debt_closure"]
    assert not metrics["full_collateral_removal"]


def test_grab_full_closure_classification_is_separate_by_state_dimension():
    debt_only = representative.liquidation_close_fraction_metrics(
        pre_ink_raw=100,
        pre_art_raw=80,
        dink_raw=-50,
        dart_raw=-80,
        rate_raw_ray=10**27,
    )
    assert debt_only["full_debt_closure"]
    assert not debt_only["full_collateral_removal"]
    both = representative.liquidation_close_fraction_metrics(
        pre_ink_raw=100,
        pre_art_raw=80,
        dink_raw=-100,
        dart_raw=-80,
        rate_raw_ray=10**27,
    )
    assert both["full_debt_closure"]
    assert both["full_collateral_removal"]


def test_liquidation_sequences_are_deterministic_and_gap_bounded():
    base = {
        "block_number": "1",
        "transaction_index": "0",
        "trace_position": "",
        "transaction_hash": "0x" + "a" * 64,
        "urn": "0x" + "1" * 40,
        "auction_id": "1",
        "ilk": "ETH-A",
        "debt_reduction_dai": "10",
        "full_debt_closure": False,
    }
    rows = [
        {**base, "timestamp_utc": "2022-05-05T00:00:00Z"},
        {
            **base,
            "block_number": "2",
            "transaction_hash": "0x" + "b" * 64,
            "auction_id": "2",
            "timestamp_utc": "2022-05-05T01:00:00Z",
        },
        {
            **base,
            "block_number": "3",
            "transaction_hash": "0x" + "c" * 64,
            "auction_id": "3",
            "timestamp_utc": "2022-05-05T02:01:00Z",
        },
    ]
    first = representative.cluster_liquidation_sequences(rows)
    second = representative.cluster_liquidation_sequences(list(reversed(rows)))
    assert first == second
    assert [row["grab_count"] for row in first] == [2, 1]


def test_stress_tail_diagnostic_uses_hourly_state_and_preserves_candidate(
    monkeypatch,
):
    window = representative.RepresentativeWindow(
        "fixture", "Fixture",
        pd.Timestamp("2022-05-05T00:00:00Z"),
        pd.Timestamp("2022-05-05T01:00:00Z"),
        0, 0, Decimal(0), Decimal(0),
    )
    boundary = [{
        "ilk": "ETH-A",
        "urn": "0x" + "1" * 40,
        "opening_ink_raw": str(10**18),
        "opening_art_raw": str(10**21),
    }]
    rates = [{
        "ilk": "ETH-A",
        "effective_time_utc": "2022-05-04T23:00:00Z",
        "block_number": "",
        "transaction_index": "",
        "trace_position": "",
        "transaction_hash": "",
        "source_type": "opening_rate",
        "resulting_rate_raw_ray": str(10**27),
    }]
    market = pd.DataFrame(
        {"eth_price_usd": [1000], "wbtc_price_usd": [30000]},
        index=pd.DatetimeIndex([window.start]),
    )
    protocol_rows = [
        {
            "timestamp_utc": window.start,
            "ilk": ilk,
            "liquidation_ratio": 1.5,
        }
        for ilk in representative.TARGET_ILKS
    ]
    protocol = pd.DataFrame(protocol_rows).set_index(
        ["timestamp_utc", "ilk"]
    )
    monkeypatch.setattr(
        representative,
        "phase2b_stress_share_candidate",
        lambda: Decimal("0.25"),
    )
    rows = representative.build_stress_tail_diagnostics(
        window=window,
        boundary=boundary,
        expanded_mutations=[],
        rates=rates,
        barks=[],
        market=market,
        protocol=protocol,
    )
    system = next(row for row in rows if row["collateral_scope"] == "ALL")
    assert len(rows) == 7
    assert system["active_vaults"] == 1
    assert system["liquidatable_vaults"] == 1
    assert Decimal(system["liquidatable_share_all_active"]) == 1
    assert system["above_phase2b_stress_candidate"]


def test_terra_mutation_sql_is_bounded_and_deterministically_ordered():
    sql = representative.render_mutation_sql(
        representative.WINDOWS["terra_cefi"]
    )
    assert "2022-05-05 00:00:00 UTC" in sql
    assert "2022-06-20 00:00:00 UTC" in sql
    assert "ORDER BY" in sql
    assert "trace_address_raw" in sql
    assert "vat_call_slip" not in sql
    assert "SELECT *" not in sql.upper()


def test_rate_lookup_uses_numeric_same_block_order_without_future_leakage():
    rates = [
        {
            "ilk": "ETH-A",
            "effective_time_utc": "2024-01-31T12:00:00Z",
            "block_number": "",
            "transaction_index": "",
            "trace_position": "",
            "transaction_hash": "",
            "source_type": "opening_rate",
            "resulting_rate_raw_ray": str(10**27),
        },
        {
            "ilk": "ETH-A",
            "effective_time_utc": "2024-02-02T12:00:00Z",
            "block_number": "100",
            "transaction_index": "2",
            "trace_position": "1.10",
            "transaction_hash": "0x" + "a" * 64,
            "source_type": "drip",
            "resulting_rate_raw_ray": str(10**27 + 10),
        },
    ]
    before = representative._rate_at(
        rates,
        "ETH-A",
        pd.Timestamp("2024-02-02T12:00:00Z"),
        block_number=100,
        transaction_index=2,
        trace_position=(1, 2),
    )
    after = representative._rate_at(
        rates,
        "ETH-A",
        pd.Timestamp("2024-02-02T12:00:00Z"),
        block_number=100,
        transaction_index=2,
        trace_position=(1, 11),
    )
    assert before == 10**27
    assert after == 10**27 + 10


def test_local_rate_audit_distinguishes_duty_from_accumulated_rate():
    audit = rate_repair.source_audit()
    assert audit["selected_method"].startswith("B_")
    assert not audit["local_method_a_exact"]
    assert "Jug.drip.output_rate" in audit["method_a_blocker"]
    hourly = next(
        item for item in audit["candidate_sources"]
        if item["path"].endswith("phase1d_protocol_parameters_hourly.csv")
    )
    assert not hourly["exact_replay_suitability"]


def test_parameter_readiness_schema_is_stable():
    path = (
        representative.PROVENANCE_ROOT
        / "tranche_01_parameter_evidence_readiness.csv"
    )
    rows = representative.load_csv(path)
    assert len(rows) == 10
    assert {
        "parameter", "required_variable",
        "quiet_mature_observation_count", "usdc_svb_observation_count",
        "total_usable_observations", "collateral_coverage",
        "opening_state_reconstruction_succeeded", "ownership_required",
        "proposed_estimator", "uncertainty_method",
        "minimum_sample_threshold", "status", "notes",
    }.issubset(rows[0])


def test_inactive_collateral_is_not_synthesised():
    rows = [{
        "ilk": "WBTC-C", "urn": "0x" + "3" * 40,
        "opening_ink_raw": "0", "opening_art_raw": "0",
        "end_ink_raw": "0", "end_art_raw": "0",
        "pre_window_mutation_count": "0", "window_mutation_count": "0",
        "last_pre_window_mutation_time_utc": None,
        "last_window_mutation_time_utc": None,
        "opening_rate_raw_ray": str(10**27),
        "opening_rate_effective_time_utc": "2021-11-29T14:00:07Z",
        "end_rate_raw_ray": str(10**27),
        "end_rate_effective_time_utc": "2021-11-29T14:00:07Z",
        "canonical_vat_contract": representative.CANONICAL_VAT,
    }]
    # Dune's final WHERE excludes such entirely inactive rows.
    sql = representative.render_boundary_sql(
        representative.WINDOWS["quiet_mature"]
    )
    assert "OR b.window_mutation_count > 0" in sql
    assert rows[0]["opening_ink_raw"] == "0"


def test_ownership_transition_selects_latest_effective_proxy():
    urn = "0x" + "3" * 40
    rows = [
        {
            "record_type": "open",
            "effective_time_utc": "2023-03-01T00:00:00Z",
            "block_number": "100",
            "transaction_index": "1",
            "trace_position": "0",
            "transaction_hash": "0x" + "a" * 64,
            "urn": urn,
            "cdp_id": "9",
            "owner_or_proxy": "0x" + "4" * 40,
        },
        {
            "record_type": "give",
            "effective_time_utc": "2023-03-10T00:00:00Z",
            "block_number": "200",
            "transaction_index": "2",
            "trace_position": "1",
            "transaction_hash": "0x" + "b" * 64,
            "urn": urn,
            "cdp_id": "9",
            "owner_or_proxy": "0x" + "5" * 40,
        },
    ]
    before = representative._ownership_at(
        rows, urn, pd.Timestamp("2023-03-09T00:00:00Z")
    )
    after = representative._ownership_at(
        rows, urn, pd.Timestamp("2023-03-11T00:00:00Z")
    )
    assert before == ("9", "0x" + "4" * 40)
    assert after == ("9", "0x" + "5" * 40)


def test_bark_link_rule_uses_grab_as_only_mutation():
    source = Path(representative.__file__).read_text(encoding="utf-8")
    assert "Bark is the economic mutation" not in source
    assert '"bark_treatment": "annotation only; Vat.grab is the economic mutation"' in source


def test_new_paths_do_not_reintroduce_legacy_layout():
    window = representative.WINDOWS["quiet_mature"]
    paths = representative.window_paths(window)
    for path in paths.values():
        text = str(path)
        assert "/production/" not in text
        assert "/phase1e/" not in text
        assert "/diagnostic/" not in text
