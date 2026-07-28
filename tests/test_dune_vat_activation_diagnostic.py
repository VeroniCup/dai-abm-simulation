from decimal import Decimal
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from workflows.maintenance.archive import diagnose_vat_activation as activation


def _row(ilk, call_type, key, time, position, raw=None):
    return {
        "ilk": ilk,
        "call_type": call_type,
        "parameter_key": key,
        "raw_value": "" if raw is None else str(raw),
        "converted_value_dai": "" if raw is None else str(float(Decimal(raw) / Decimal("1e45"))),
        "block_time": time,
        "block_number": str(12000000 + position),
        "transaction_index": "",
        "call_position": str(position),
        "transaction_hash": "0x" + f"{position:064x}",
        "vat_contract": activation.CANONICAL_VAT,
    }


def activation_rows():
    rows = []
    position = 0
    for ilk, init_time, setting_time in (
        ("WBTC-B", "2020-11-01T00:00:00+00:00", "2021-08-01T00:00:00+00:00"),
        ("WBTC-C", "2021-10-01T00:00:00+00:00", "2021-10-01T00:01:00+00:00"),
    ):
        position += 1
        rows.append(_row(ilk, "init", "init", init_time, position))
        for key, value in (("line", Decimal("1000000") * Decimal("1e45")),
                           ("dust", Decimal("5000") * Decimal("1e45"))):
            position += 1
            rows.append(_row(ilk, "file", key, setting_time, position, value))
    return sorted(rows, key=lambda row: (
        row["block_time"], int(row["block_number"]), row["transaction_hash"].lower(),
        row["call_position"], row["call_type"], row["parameter_key"],
    ))


def test_activation_sql_is_bounded_and_exact():
    report = activation.validate_sql(activation.SQL_PATH.read_text(encoding="utf-8"))
    assert report["validation_passed"], report["failures"]


def test_explicit_init_and_first_settings_support_in_sample_activation():
    report = activation.validate_rows(activation_rows(), list(activation.EXPECTED_COLUMNS))
    assert report["validation_passed"], report["failures"]
    assert all(
        item["classification"] == "activated_during_sample"
        for item in report["classifications"].values()
    )
    assert report["transaction_index_availability"]["unavailable_count"] == len(
        activation_rows()
    )
    assert report["unresolved_ordering_tie_count"] == 0


def test_pre_sample_setting_is_not_relaxed():
    rows = activation_rows()
    rows[1]["block_time"] = "2021-05-01T00:00:00+00:00"
    rows.sort(key=lambda row: (
        row["block_time"], int(row["block_number"]), row["transaction_hash"].lower(),
        row["call_position"], row["call_type"], row["parameter_key"],
    ))
    report = activation.validate_rows(rows, list(activation.EXPECTED_COLUMNS))
    assert report["classifications"]["WBTC-B:line"]["classification"] == "active_before_sample_start"


def test_invalid_rad_conversion_fails():
    rows = activation_rows()
    rows[1]["converted_value_dai"] = "123"
    report = activation.validate_rows(rows, list(activation.EXPECTED_COLUMNS))
    assert not report["validation_passed"]
    assert report["unit_conversion_failure_count"] == 1


def test_unresolved_fallback_ordering_tie_fails():
    rows = activation_rows()
    rows.append(dict(rows[-1]))
    report = activation.validate_rows(rows, list(activation.EXPECTED_COLUMNS))
    assert not report["validation_passed"]
    assert report["unresolved_ordering_tie_count"] == 1


def test_direct_result_retrieval_persists_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr(activation, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(activation, "RAW_PATH", tmp_path / "raw.csv")
    monkeypatch.setattr(activation, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(activation, "METADATA_PATH", tmp_path / "metadata.json")
    monkeypatch.setattr(activation, "VALIDATION_PATH", tmp_path / "validation.json")
    monkeypatch.setattr(activation, "EVIDENCE_PATH", tmp_path / "evidence.json")
    activation.write_json_atomic(activation.STATE_PATH, {
        "query_id": 1, "execution_id": "01TEST", "state": "execution_submitted",
    })
    rows = activation_rows()
    metadata = {"total_row_count": len(rows), "column_names": list(activation.EXPECTED_COLUMNS)}
    calls = []

    def fake_api(_key, url):
        calls.append(url)
        if url.endswith("/status"):
            return {"state": "QUERY_STATE_COMPLETED", "result_metadata": metadata}
        return {"state": "QUERY_STATE_COMPLETED", "next_offset": None,
                "result": {"rows": rows, "metadata": metadata}}

    monkeypatch.setattr(activation, "_api_json", fake_api)
    report = activation.retrieve_and_persist("not-logged")
    assert report["validation_passed"]
    assert len(calls) == 2
    assert activation.RAW_PATH.exists()
    assert not list(tmp_path.glob("*.partial"))
    state = json.loads(activation.STATE_PATH.read_text(encoding="utf-8"))
    assert state["result_retrieval_count"] == 1
    assert state["raw_file_persisted"]


def test_diagnostic_client_has_no_submission_endpoint():
    source = activation.Path(activation.__file__).read_text(encoding="utf-8").lower()
    assert "/execute" not in source
    assert "createquery" not in source
    assert "updatequery" not in source
    assert "print(api_key" not in source
