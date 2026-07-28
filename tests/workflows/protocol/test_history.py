from decimal import Decimal
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

from tests.support import REPOSITORY_ROOT
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from workflows.protocol import acquire as history


def _rows(spec, parameters, ilks=history.TARGET_ILKS):
    rows = []
    position = 0
    for ilk in ilks:
        for parameter in parameters:
            position += 1
            raw = {
                "oracle_adapter": "0x" + "11" * 20,
                "clipper_mapping": "0x" + "22" * 20,
            }.get(parameter, str(Decimal("2") * Decimal("1e27")))
            converted = history._conversion(raw, parameter)
            parameter_key = {
                "debt_ceiling": "line", "minimum_debt": "dust",
                "global_debt_ceiling": "Line",
                "stability_fee_duty": "duty", "stability_fee_base": "base",
                "auction_price_buffer": "buf", "auction_tail": "tail",
                "auction_cusp": "cusp", "auction_keeper_fraction": "chip",
                "auction_keeper_fixed": "tip", "auction_stopped": "stopped",
            }.get(parameter, parameter)
            source_contract = history.CANONICAL_CONTRACTS.get(
                spec.name, "0x" + "33" * 20
            )
            if spec.name == "Clipper":
                source_contract = history.CLIPPER_MAPPINGS[ilk]["contract_address"]
            rows.append({
                "module": spec.name, "ilk": ilk, "parameter": parameter,
                "parameter_key": parameter_key,
                "source_classification": "pre_sample_initial_state",
                "effective_time_utc": "2021-05-20 00:00:00.000 UTC",
                "block_number": 12000000 + position, "transaction_index": 1,
                "source_position": str(position),
                "source_contract": source_contract,
                "transaction_hash": "0x" + f"{position:064x}",
                "raw_value": raw, "converted_value": converted,
                "converted_unit": "test", "auxiliary_raw_value": None,
            })
    return rows


def test_all_production_sql_passes_preflight():
    for spec in history.MODULES.values():
        report = history.validate_sql(spec, spec.sql_path.read_text(encoding="utf-8"))
        assert report["validation_passed"], report["failures"]


def test_clipper_stopped_diagnostic_is_bounded_and_explicit():
    sql = (
        history.ROOT
        / "sql"
        / "protocol"
        / "generated"
        / "history"
        / "clipper_stopped_diagnostic.sql"
    ).read_text(encoding="utf-8").lower()
    assert sql.count("0xc67963a226eddd77b91ad8c421630a1b0adff270") == 1
    for mapping in history.CLIPPER_MAPPINGS.values():
        assert mapping["contract_address"] in sql
    assert "ethereum.creation_traces" in sql
    assert "maker_ethereum.clipper_call_file" in sql
    assert "ethereum.traces" in sql
    assert "stopped()" in sql
    assert "2024-07-01" in sql
    assert "select *" not in sql


def test_clipper_stopped_minimal_diagnostic_is_shallow_and_exact():
    sql = history.CLIPPER_STOPPED_MINIMAL_SQL_PATH.read_text(
        encoding="utf-8"
    ).lower()
    for mapping in history.CLIPPER_MAPPINGS.values():
        assert sql.count(mapping["contract_address"]) == 1
    assert "ethereum.traces" in sql
    assert "maker_ethereum.clipper_call_file" in sql
    assert "stopped()" not in sql
    assert "getter" not in sql
    assert "ethereum.creation_traces" not in sql
    assert "2024-07-01" in sql
    assert "select *" not in sql
    assert sql.count("union all") == 1


def test_clipper_stopped_minimal_validation_requires_six_creations():
    rows = []
    for position, (ilk, mapping) in enumerate(history.CLIPPER_MAPPINGS.items()):
        mapping_time = pd.Timestamp(mapping["effective_time_utc"])
        rows.append({
            "record_type": "contract_creation",
            "ilk": ilk,
            "contract_address": mapping["contract_address"],
            "mapping_time": mapping_time.isoformat(),
            "mapping_block": mapping["block_number"],
            "mapping_tx_hash": mapping["transaction_hash"],
            "creator": "0x" + "11" * 20,
            "transaction_hash": "0x" + f"{position + 1:064x}",
            "block_time": (mapping_time - pd.Timedelta(days=1)).isoformat(),
            "block_number": mapping["block_number"] - 1,
            "trace_position": "0",
            "success": True,
            "creation_code_hash": "0x" + "22" * 32,
            "raw_stopped_value": None,
            "stopped_value": None,
        })
    rows.sort(key=lambda row: (
        row["block_time"], row["block_number"], row["transaction_hash"],
        row["trace_position"], row["record_type"],
    ))
    report = history.validate_clipper_stopped_minimal_rows(
        rows, list(history.CLIPPER_STOPPED_MINIMAL_COLUMNS)
    )
    assert report["validation_passed"], report["failures"]
    assert report["creation_record_count"] == 6
    assert report["explicit_stopped_call_count"] == 0


def test_missing_clipper_stopped_rows_cannot_imply_zero():
    rows = []
    report = history.validate_clipper_stopped_minimal_rows(
        rows, list(history.CLIPPER_STOPPED_MINIMAL_COLUMNS)
    )
    assert not report["validation_passed"]


def test_minimal_clipper_payload_is_passed_to_atomic_persistence(
    tmp_path, monkeypatch
):
    diagnostic_dir = tmp_path / "diagnostic"
    diagnostic_dir.mkdir()
    payload_path = diagnostic_dir / ".minimal.partial.json"
    response_path = diagnostic_dir / "minimal_response.json"
    csv_path = diagnostic_dir / "minimal.csv"
    metadata_path = diagnostic_dir / "minimal_metadata.json"
    validation_path = diagnostic_dir / "minimal_validation.json"
    monkeypatch.setattr(history, "CLIPPER_STOPPED_MINIMAL_PAYLOAD_PATH", payload_path)
    monkeypatch.setattr(history, "CLIPPER_STOPPED_MINIMAL_RESPONSE_PATH", response_path)
    monkeypatch.setattr(history, "CLIPPER_STOPPED_MINIMAL_PATH", csv_path)
    monkeypatch.setattr(history, "CLIPPER_STOPPED_MINIMAL_METADATA_PATH", metadata_path)
    monkeypatch.setattr(history, "CLIPPER_STOPPED_MINIMAL_VALIDATION_PATH", validation_path)
    rows = []
    for position, (ilk, mapping) in enumerate(history.CLIPPER_MAPPINGS.items()):
        mapping_time = pd.Timestamp(mapping["effective_time_utc"])
        rows.append({
            "record_type": "contract_creation", "ilk": ilk,
            "contract_address": mapping["contract_address"],
            "mapping_time": mapping_time.isoformat(),
            "mapping_block": mapping["block_number"],
            "mapping_tx_hash": mapping["transaction_hash"],
            "creator": "0x" + "11" * 20,
            "transaction_hash": "0x" + f"{position + 1:064x}",
            "block_time": (mapping_time - pd.Timedelta(days=1)).isoformat(),
            "block_number": mapping["block_number"] - 1,
            "trace_position": "0", "success": True,
            "creation_code_hash": "0x" + "22" * 32,
            "raw_stopped_value": None, "stopped_value": None,
        })
    rows.sort(key=lambda row: (
        row["block_time"], row["block_number"], row["transaction_hash"],
        row["trace_position"], row["record_type"],
    ))
    history.write_json_atomic(payload_path, {
        "structuredContent": {
            "query": {"query_id": 1, "url": "https://dune.com/queries/1"},
            "execution": {"execution_id": "01TEST", "engine_used": "small"},
            "result_preview": {
                "state": "COMPLETED", "data": {"rows": rows},
                "resultMetadata": {
                    "totalRowCount": 6, "executionCostCredits": "0.001",
                    "columns": [
                        {"name": name, "type": "varchar"}
                        for name in history.CLIPPER_STOPPED_MINIMAL_COLUMNS
                    ],
                },
            },
        },
    })
    report = history.persist_clipper_stopped_minimal_payload()
    assert report["validation_passed"]
    assert csv_path.exists()
    assert response_path.exists()
    assert not payload_path.exists()


def test_unit_conversions():
    assert history._conversion(str(Decimal("150") * Decimal("1e25")), "liquidation_ratio") == 1.5
    assert history._conversion(str(Decimal("113") * Decimal("1e16")), "liquidation_penalty") == 0.13
    assert history._conversion(str(Decimal("5000") * Decimal("1e45")), "minimum_debt") == 5000
    assert history._conversion(str(Decimal("110") * Decimal("1e25")), "auction_price_buffer") == 1.1
    assert history._conversion(str(Decimal("1") * Decimal("1e16")), "auction_keeper_fraction") == 0.01


def test_module_validation_rejects_missing_pre_sample_state():
    spec = history.MODULES["jug"]
    rows = _rows(spec, ("stability_fee_duty",))
    report = history.validate_module_rows(spec, rows, list(history.COMMON_COLUMNS))
    assert not report["validation_passed"]
    assert any("missing pre-sample" in failure for failure in report["failures"])


def test_clipper_validation_rejects_missing_stopped_series(tmp_path, monkeypatch):
    monkeypatch.setattr(
        history, "CLIPPER_STOPPED_EVIDENCE_PATH", tmp_path / "absent.json"
    )
    spec = history.MODULES["clipper"]
    rows = _rows(spec, tuple(
        parameter for parameter in spec.parameters if parameter != "auction_stopped"
    ))
    report = history.validate_module_rows(spec, rows, list(history.COMMON_COLUMNS))
    assert not report["validation_passed"]
    assert report["missing_required_parameter_series"] == [
        [ilk, "auction_stopped"] for ilk in history.TARGET_ILKS
    ]


def _clipper_evidence():
    series = []
    for ilk, mapping in history.CLIPPER_MAPPINGS.items():
        effective = pd.Timestamp(mapping["effective_time_utc"])
        series.append({
            "ilk": ilk,
            "contract_address": mapping["contract_address"],
            "classification": "explicit_zero_initial_state",
            "initial_value": "0",
            "state_source": "contract_default",
            "is_observed_call": False,
            "deployment_time_utc": (effective - pd.Timedelta(days=1)).isoformat(),
            "deployment_block_number": mapping["block_number"] - 1,
            "deployment_transaction_hash": "0x" + "44" * 32,
            "mapping_time_utc": effective.isoformat(),
            "mapping_block_number": mapping["block_number"],
            "mapping_transaction_hash": mapping["transaction_hash"],
            "effective_start_utc": effective.isoformat(),
            "verified_clipper_abi": True,
            "verified_source_exact_match": True,
            "verified_source_url": (
                f"https://etherscan.io/address/{mapping['contract_address']}#code"
            ),
            "creation_code_hash": "0x" + "55" * 32,
            "constructor_assigns_stopped": False,
            "explicit_stopped_call_count": 0,
            "earlier_non_zero_call_count": 0,
        })
    return {
        "status": "validated",
        "verified_source": {
            "declaration": "uint256 public stopped = 0;",
            "exact_match_deployment_evidence": True,
            "constructor_assigns_stopped": False,
        },
        "solidity_storage_semantics": {
            "uint_default_is_zero": True,
            "reference": "https://docs.soliditylang.org/",
        },
        "diagnostic": {
            "explicit_stopped_call_count": 0,
            "non_zero_stopped_call_count": 0,
            "all_six_addresses_included": True,
            "deployment_record_count": 6,
            "scan_end_exclusive_utc": history.SAMPLE_END.isoformat(),
        },
        "series": series,
    }


def test_clipper_validation_accepts_separate_verified_defaults(tmp_path, monkeypatch):
    evidence_path = tmp_path / "clipper_stopped_evidence.json"
    history.write_json_atomic(evidence_path, _clipper_evidence())
    monkeypatch.setattr(history, "CLIPPER_STOPPED_EVIDENCE_PATH", evidence_path)
    spec = history.MODULES["clipper"]
    rows = _rows(spec, tuple(
        parameter for parameter in spec.parameters if parameter != "auction_stopped"
    ))
    report = history.validate_module_rows(spec, rows, list(history.COMMON_COLUMNS))
    assert report["validation_passed"], report["failures"]
    assert len(report["documented_default_states"]) == 6
    defaults = history._clipper_documented_default_rows()
    assert len(defaults) == 6
    assert defaults["state_source"].eq("contract_default").all()
    assert defaults["is_observed_call"].eq(False).all()
    assert defaults["raw_value"].eq("0").all()


def test_clipper_defaults_cannot_start_before_mapping(tmp_path, monkeypatch):
    evidence = _clipper_evidence()
    evidence["series"][0]["effective_start_utc"] = "2021-01-01T00:00:00Z"
    evidence_path = tmp_path / "clipper_stopped_evidence.json"
    history.write_json_atomic(evidence_path, evidence)
    monkeypatch.setattr(history, "CLIPPER_STOPPED_EVIDENCE_PATH", evidence_path)
    report = history.validate_clipper_stopped_evidence(evidence)
    assert not report["validation_passed"]
    assert any("Dog mapping boundary" in failure for failure in report["failures"])


def test_atomic_module_persistence(tmp_path, monkeypatch):
    original = history.MODULES["vat"]
    spec = history.ModuleSpec(original.name, original.sql_name, original.parameters)
    monkeypatch.setattr(history, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(history, "MODULE_PROVENANCE_DIR", tmp_path / "modules")
    monkeypatch.setattr(history, "INGRESS_DIR", tmp_path / "ingress")
    monkeypatch.setattr(
        history, "VAT_ACTIVATION_EVIDENCE_PATH", tmp_path / "no_activation_evidence.json"
    )
    rows = _rows(spec, ("debt_ceiling", "minimum_debt"))
    rows.extend(_rows(spec, ("global_debt_ceiling",), ("GLOBAL",)))
    rows.sort(key=lambda row: (row["effective_time_utc"], row["block_number"]))
    history.write_json_atomic(spec.state_path, {
        "execution_id": "01TEST", "query_id": 1, "state": "execution_completed",
    })
    history.write_json_atomic(spec.payload_path, {
        "state": "COMPLETED", "executionId": "01TEST", "data": {"rows": rows},
        "resultMetadata": {
            "totalRowCount": len(rows),
            "executionCostCredits": "0.001",
            "columns": [{"name": name, "type": "varchar"}
                        for name in history.COMMON_COLUMNS],
        },
    })
    report = history.persist_module_payload(spec)
    assert report["validation_passed"]
    assert spec.raw_path.exists()
    assert not spec.payload_path.exists()
    state = json.loads(spec.state_path.read_text(encoding="utf-8"))
    assert state["state"] == "complete"
    assert state["result_retrieval_count"] == 1


def test_asof_reconstruction_does_not_fill_before_first_observation():
    rows = pd.DataFrame({
        "effective_time_utc": pd.to_datetime(["2021-06-01 02:00:00"], utc=True),
        "block_number": [1], "transaction_index": [1], "source_position": ["0"],
        "converted_value": [1.5],
    })
    hours = pd.date_range("2021-06-01", periods=4, freq="h", tz="UTC")
    result = history._asof_series(rows, hours, "converted_value")
    assert result.iloc[:2].isna().all()
    assert result.iloc[2:].tolist() == [1.5, 1.5]


def test_effective_rows_collapse_same_timestamp_deterministically():
    rows = pd.DataFrame({
        "effective_time_utc": pd.to_datetime([
            "2021-06-01 02:00:00", "2021-06-01 02:00:00",
            "2021-06-01 03:00:00",
        ], utc=True),
        "block_number": [1, 1, 2],
        "transaction_index": [pd.NA, pd.NA, pd.NA],
        "transaction_hash": ["0x01", "0x02", "0x03"],
        "source_position": ["3", "3", "3"],
        "converted_value": [1.0, 2.0, 3.0],
    })
    ordered = history._ordered_effective_rows(rows)
    assert ordered["converted_value"].tolist() == [2.0, 3.0]
    assert ordered["effective_time_utc"].is_unique


def test_documented_stopped_defaults_keep_provenance():
    defaults = history._clipper_stopped_evidence()
    assert defaults[1]["validation_passed"]
    rows = history._clipper_documented_default_rows()
    assert rows["state_source"].eq("contract_default").all()
    assert rows["is_observed_call"].eq(False).all()
    assert rows["evidence_reference"].str.endswith(
        "phase1d_clipper_stopped_minimal_evidence.json"
    ).all()


def test_annualisation_aligns_duty_and_base_effective_values():
    duty = pd.Series([1.000000001, 1.000000002])
    base = pd.Series([0.0, 0.0])
    result = history._annualise_fee(duty, base)
    assert result.iloc[1] > result.iloc[0] > 0


def test_recovery_client_cannot_submit_or_print_api_key():
    source = history.Path(history.__file__).read_text(encoding="utf-8").lower()
    assert "query/" not in source
    assert "/execute" not in source
    assert "executequery" not in source
    assert "print(api_key" not in source


def test_vat_recovery_passes_response_directly_to_atomic_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(history, "MODULE_PROVENANCE_DIR", tmp_path / "modules")
    monkeypatch.setattr(history, "INGRESS_DIR", tmp_path / "ingress")
    monkeypatch.setattr(
        history, "VAT_ACTIVATION_EVIDENCE_PATH", tmp_path / "no_activation_evidence.json"
    )
    monkeypatch.setattr(history, "VAT_EXPECTED_ROWS", 13)
    spec = history.MODULES["vat"]
    rows = _rows(spec, ("debt_ceiling", "minimum_debt"))
    rows.extend(_rows(spec, ("global_debt_ceiling",), ("GLOBAL",)))
    rows.sort(key=lambda row: (row["effective_time_utc"], row["block_number"]))
    history.write_json_atomic(spec.state_path, {
        "query_id": 8069558,
        "execution_id": "01KY4TZWPGZPS66ZFZQ5YYQKH9",
        "execution_state": "COMPLETED",
        "failure_stage": "local_result_persistence",
        "failure_error": "apply_patch wrapper malformed",
        "retrieved_result_not_locally_persisted": True,
    })
    metadata = {
        "total_row_count": len(rows),
        "column_names": list(history.COMMON_COLUMNS),
    }
    calls = []

    def fake_api(_key, url):
        calls.append(url)
        if url.endswith("/status"):
            return {"state": "QUERY_STATE_COMPLETED", "result_metadata": metadata}
        return {
            "state": "QUERY_STATE_COMPLETED",
            "next_offset": None,
            "result": {"rows": rows, "metadata": metadata},
        }

    monkeypatch.setattr(history, "_api_json", fake_api)
    report = history.recover_vat_result("secret-not-logged")
    assert report["validation_passed"]
    assert len(calls) == 2
    assert calls[0].endswith("/status")
    assert "/results?" in calls[1]
    assert spec.raw_path.exists()
    assert not list(tmp_path.glob("*.partial"))
    state = json.loads(spec.state_path.read_text(encoding="utf-8"))
    assert state["state"] == "complete"
    assert state["recovery_result_retrieval_count"] == 1


def test_documented_in_sample_vat_activation_replaces_pre_sample_requirement(
    tmp_path, monkeypatch,
):
    evidence_path = tmp_path / "activation.json"
    monkeypatch.setattr(history, "VAT_ACTIVATION_EVIDENCE_PATH", evidence_path)
    spec = history.MODULES["vat"]
    pre_sample_ilks = ("ETH-A", "ETH-B", "ETH-C", "WBTC-A")
    rows = _rows(spec, ("debt_ceiling", "minimum_debt"), pre_sample_ilks)
    rows.extend(_rows(spec, ("global_debt_ceiling",), ("GLOBAL",)))
    classifications = {}
    position = 100
    for ilk, timestamp in (
        ("WBTC-B", "2021-11-22 14:03:13.000 UTC"),
        ("WBTC-C", "2021-11-29 14:00:07.000 UTC"),
    ):
        for key, parameter, raw in (
            ("line", "debt_ceiling", str(Decimal("30000000") * Decimal("1e45"))),
            ("dust", "minimum_debt", str(Decimal("30000") * Decimal("1e45"))),
        ):
            position += 1
            rows.append({
                "module": "Vat", "ilk": ilk, "parameter": parameter,
                "parameter_key": key, "source_classification": "in_sample_change",
                "effective_time_utc": timestamp, "block_number": 13664911 + position,
                "transaction_index": 1, "source_position": str(position),
                "source_contract": history.CANONICAL_CONTRACTS["Vat"],
                "transaction_hash": "0x" + f"{position:064x}",
                "raw_value": raw, "converted_value": history._conversion(raw, parameter),
                "converted_unit": "DAI", "auxiliary_raw_value": None,
            })
            classifications[f"{ilk}:{key}"] = {
                "classification": "activated_during_sample",
                "activation_setting": {
                    "timestamp": timestamp, "raw_value": raw,
                    "block_number": 13664911 + position,
                    "transaction_hash": "0x" + f"{position:064x}",
                    "call_position": str(position),
                },
            }
    history.write_json_atomic(evidence_path, {
        "status": "validated", "classifications": classifications,
    })
    rows.sort(key=lambda row: (
        row["effective_time_utc"], row["block_number"], row["transaction_index"],
        row["source_position"],
    ))
    report = history.validate_module_rows(spec, rows, list(history.COMMON_COLUMNS))
    assert report["validation_passed"], report["failures"]
    assert len(report["documented_in_sample_activations"]) == 4
    assert all(
        item["boundary_valid"] and not item["pre_activation_forward_fill_permitted"]
        for item in report["documented_in_sample_activations"].values()
    )
