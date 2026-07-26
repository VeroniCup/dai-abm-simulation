import csv
from decimal import Decimal
import json
from pathlib import Path

import pytest

from scripts import acquire_dune_protocol_parameters as protocol


def diagnostic_rows(row_count=protocol.EXPECTED_ROWS):
    values = [Decimal("2500000000") + Decimal(index) for index in range(row_count)]
    times = ["2021-05-20 12:00:00.000 UTC"] + [
        f"2021-06-{1 + (index // 24):02d} {index % 24:02d}:00:00.000 UTC"
        for index in range(1, row_count)
    ]
    rows = []
    for index, (value, timestamp) in enumerate(zip(values, times)):
        raw = value * Decimal(10) ** 45
        converted = float(str(raw)) / 1e45
        previous = (
            float(str(values[index - 1] * Decimal(10) ** 45)) / 1e45
            if index else None
        )
        rows.append({
            "ilk": "ETH-A", "parameter": "debt_ceiling",
            "parameter_key": "line",
            "source_classification": (
                "pre_sample_initial_state" if index == 0 else "in_sample_change"
            ),
            "effective_time_utc": timestamp,
            "call_block_number": str(12000000 + index), "call_tx_index": "2",
            "contract_address": protocol.CANONICAL_VAT,
            "transaction_hash": "0x" + f"{index + 1:064x}",
            "raw_value_rad": str(raw),
            "value_dai": str(converted),
            "previous_value_dai": "" if previous is None else str(previous),
            "change_dai": "" if previous is None else str(converted - previous),
        })
    return rows


def test_sql_preflight_rejects_broad_or_unbounded_queries():
    valid = protocol.validate_sql(protocol.SQL_PATH.read_text(encoding="utf-8"))
    assert valid["validation_passed"]
    invalid = protocol.validate_sql("SELECT * FROM maker_ethereum.vat_call_file")
    assert not invalid["validation_passed"]


def test_rad_scaling_and_pre_window_state():
    report = protocol.validate_rows(diagnostic_rows(), list(protocol.EXPECTED_COLUMNS))
    assert report["validation_passed"]
    assert report["pre_window_state_count"] == 1
    assert report["in_window_change_count"] == protocol.EXPECTED_ROWS - 1
    assert report["duplicate_governance_change_count"] == 0
    assert report["carry_forward_intervals"][0]["effective_start_utc"] == "2021-06-01T00:00:00Z"


def test_invalid_change_is_not_silently_accepted():
    rows = diagnostic_rows()
    rows[1]["change_dai"] = "2"
    report = protocol.validate_rows(rows, list(protocol.EXPECTED_COLUMNS))
    assert not report["validation_passed"]
    assert any("incorrect change" in failure for failure in report["failures"])


def test_atomic_payload_persistence(tmp_path, monkeypatch):
    diagnostic_dir = tmp_path / "diagnostic"
    monkeypatch.setattr(protocol, "DIAGNOSTIC_DIR", diagnostic_dir)
    monkeypatch.setattr(protocol, "STATE_PATH", diagnostic_dir / "state.json")
    monkeypatch.setattr(protocol, "PAYLOAD_PATH", diagnostic_dir / ".payload.json")
    monkeypatch.setattr(protocol, "RAW_PATH", diagnostic_dir / "raw.csv")
    monkeypatch.setattr(protocol, "VALIDATION_PATH", diagnostic_dir / "validation.json")
    monkeypatch.setattr(protocol, "METADATA_PATH", diagnostic_dir / "metadata.json")
    protocol.write_json_atomic(protocol.STATE_PATH, {
        "execution_id": "01TEST", "query_id": 1, "sql_sha256": "a" * 64,
        "query_type": "private temporary diagnostic", "engine": "small",
        "sql_path": "sql/diagnostic.sql", "query_url": "https://dune.com/queries/1",
        "supersedes_failed_query_id": 8069228,
        "supersedes_failed_execution_id": "01KY4S1MW60ZPG9DTKMV2TJCT1",
    })
    rows = diagnostic_rows()
    protocol.write_json_atomic(protocol.PAYLOAD_PATH, {
        "state": "COMPLETED", "executionId": "01TEST", "data": {"rows": rows},
        "resultMetadata": {
            "totalRowCount": len(rows),
            "executionCostCredits": "0.001",
            "columns": [{"name": name, "type": "varchar"} for name in protocol.EXPECTED_COLUMNS],
        },
    })
    report = protocol.persist_payload()
    assert report["validation_passed"]
    assert protocol.RAW_PATH.exists()
    assert not protocol.PAYLOAD_PATH.exists()
    with protocol.RAW_PATH.open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == protocol.EXPECTED_ROWS
    state = json.loads(protocol.STATE_PATH.read_text())
    assert state["state"] == "complete"
    assert state["result_retrieval_count"] == 1
