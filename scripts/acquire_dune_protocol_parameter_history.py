"""Persist, validate and reconstruct Phase 1D protocol-parameter history.

This module deliberately contains no Dune client. MCP query responses are
written to a module-specific payload file and passed directly to the atomic
persistence functions below. This makes submission and result retrieval
explicit orchestration steps and prevents automatic retries.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "protocol"
PROCESSED_DIR = ROOT / "data" / "processed" / "protocol"
PROVENANCE_DIR = ROOT / "data" / "provenance" / "protocol"
MODULE_PROVENANCE_DIR = PROVENANCE_DIR / "modules"
DIAGNOSTIC_DIR = PROVENANCE_DIR / "archive" / "diagnostic"
INGRESS_DIR = PROVENANCE_DIR / "ingress"
SAMPLE_START = pd.Timestamp("2021-06-01 00:00:00", tz="UTC")
SAMPLE_END = pd.Timestamp("2024-07-01 00:00:00", tz="UTC")
EXPECTED_HOURS = 27_024
VAT_EXPECTED_ROWS = 10_991
API_ROOT = "https://api.dune.com/api/v1"
TARGET_ILKS = ("ETH-A", "ETH-B", "ETH-C", "WBTC-A", "WBTC-B", "WBTC-C")
CANONICAL_CONTRACTS = {
    "Vat": "0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b",
    "Spot": "0x65c79fcb50ca1594b025960e539ed7a9a6d434a3",
    "Jug": "0x19c0976f590d67707e62397c87829d896dc0f1f1",
    "Dog": "0x135954d155898d42c90d2a57824c690e0c7bef1b",
}
COMMON_COLUMNS = (
    "module", "ilk", "parameter", "parameter_key", "source_classification",
    "effective_time_utc", "block_number", "transaction_index", "source_position",
    "source_contract", "transaction_hash", "raw_value", "converted_value",
    "converted_unit", "auxiliary_raw_value",
)


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    sql_name: str
    parameters: tuple[str, ...]

    @property
    def sql_path(self) -> Path:
        return ROOT / "sql" / self.sql_name

    @property
    def stem(self) -> str:
        return f"phase1d_{self.name.lower()}_parameters"

    @property
    def raw_path(self) -> Path:
        return RAW_DIR / f"{self.stem}.csv"

    @property
    def payload_path(self) -> Path:
        return INGRESS_DIR / f".{self.stem}.partial.json"

    @property
    def state_path(self) -> Path:
        return MODULE_PROVENANCE_DIR / self.name.lower() / "state.json"

    @property
    def validation_path(self) -> Path:
        return MODULE_PROVENANCE_DIR / self.name.lower() / "validation.json"

    @property
    def metadata_path(self) -> Path:
        return MODULE_PROVENANCE_DIR / self.name.lower() / "metadata.json"


MODULES = {
    "vat": ModuleSpec("Vat", "dune_phase1d_vat_parameters.sql", (
        "debt_ceiling", "minimum_debt", "global_debt_ceiling",
    )),
    "spot": ModuleSpec("Spot", "dune_phase1d_spot_parameters.sql", (
        "liquidation_ratio", "oracle_adapter", "effective_liquidation_spot",
    )),
    "jug": ModuleSpec("Jug", "dune_phase1d_jug_parameters.sql", (
        "stability_fee_duty", "stability_fee_base",
    )),
    "dog": ModuleSpec("Dog", "dune_phase1d_dog_parameters.sql", (
        "liquidation_penalty", "ilk_liquidation_capacity",
        "global_liquidation_capacity", "clipper_mapping",
    )),
    "clipper": ModuleSpec("Clipper", "dune_phase1d_clipper_parameters.sql", (
        "auction_price_buffer", "auction_tail", "auction_cusp",
        "auction_keeper_fraction", "auction_keeper_fixed", "auction_stopped",
    )),
}

LEDGER_PATH = PROCESSED_DIR / "phase1d_protocol_parameter_changes.csv"
INTERVAL_PATH = PROCESSED_DIR / "phase1d_protocol_parameter_intervals.csv"
HOURLY_PATH = PROCESSED_DIR / "phase1d_protocol_parameters_hourly.csv"
METADATA_PATH = PROVENANCE_DIR / "metadata.json"
VALIDATION_PATH = PROVENANCE_DIR / "validation.json"
MANIFEST_PATH = PROVENANCE_DIR / "manifest.json"
VAT_ACTIVATION_EVIDENCE_PATH = (
    DIAGNOSTIC_DIR / "phase1d_vat_activation_evidence.json"
)
CLIPPER_STOPPED_DIAGNOSTIC_PATH = (
    DIAGNOSTIC_DIR / "phase1d_clipper_stopped_diagnostic.csv"
)
CLIPPER_STOPPED_MINIMAL_SQL_PATH = (
    ROOT / "sql" / "dune_phase1d_clipper_stopped_minimal_diagnostic.sql"
)
CLIPPER_STOPPED_MINIMAL_PATH = (
    DIAGNOSTIC_DIR / "phase1d_clipper_stopped_minimal_diagnostic.csv"
)
CLIPPER_STOPPED_MINIMAL_PAYLOAD_PATH = (
    DIAGNOSTIC_DIR / ".phase1d_clipper_stopped_minimal.partial.json"
)
CLIPPER_STOPPED_MINIMAL_RESPONSE_PATH = (
    DIAGNOSTIC_DIR / "phase1d_clipper_stopped_minimal_response.json"
)
CLIPPER_STOPPED_MINIMAL_METADATA_PATH = (
    DIAGNOSTIC_DIR / "phase1d_clipper_stopped_minimal_metadata.json"
)
CLIPPER_STOPPED_MINIMAL_VALIDATION_PATH = (
    DIAGNOSTIC_DIR / "phase1d_clipper_stopped_minimal_validation.json"
)
CLIPPER_STOPPED_EVIDENCE_PATH = (
    DIAGNOSTIC_DIR / "phase1d_clipper_stopped_minimal_evidence.json"
)
CLIPPER_STOPPED_DEFAULTS_PATH = (
    PROVENANCE_DIR / "phase1d_clipper_stopped_documented_defaults.csv"
)
DERIVED_PROVENANCE_COLUMNS = (
    "state_source", "is_observed_call", "evidence_reference",
)
CLIPPER_STOPPED_MINIMAL_COLUMNS = (
    "record_type", "ilk", "contract_address", "mapping_time", "mapping_block",
    "mapping_tx_hash", "creator", "transaction_hash", "block_time",
    "block_number", "trace_position", "success", "creation_code_hash",
    "raw_stopped_value", "stopped_value",
)
CLIPPER_MAPPINGS = {
    "ETH-A": {
        "contract_address": "0xc67963a226eddd77b91ad8c421630a1b0adff270",
        "effective_time_utc": "2021-05-06T15:45:10Z",
        "block_number": 12_381_609,
        "transaction_hash": "0x42e122bb5c4addef1bd8c74402178ac982ef813d72c7f846743efd6f8b3cd092",
    },
    "ETH-B": {
        "contract_address": "0x71eb894330e8a4b96b8d6056962e7f116f50e06f",
        "effective_time_utc": "2021-05-06T15:45:10Z",
        "block_number": 12_381_609,
        "transaction_hash": "0x42e122bb5c4addef1bd8c74402178ac982ef813d72c7f846743efd6f8b3cd092",
    },
    "ETH-C": {
        "contract_address": "0xc2b12567523e3f3cbd9931492b91fe65b240bc47",
        "effective_time_utc": "2021-05-06T15:45:10Z",
        "block_number": 12_381_609,
        "transaction_hash": "0x42e122bb5c4addef1bd8c74402178ac982ef813d72c7f846743efd6f8b3cd092",
    },
    "WBTC-A": {
        "contract_address": "0x0227b54adbfaeec5f1ed1dfa11f54dcff9076e2c",
        "effective_time_utc": "2021-05-06T15:45:10Z",
        "block_number": 12_381_609,
        "transaction_hash": "0x42e122bb5c4addef1bd8c74402178ac982ef813d72c7f846743efd6f8b3cd092",
    },
    "WBTC-B": {
        "contract_address": "0xe30663c6f83a06edee6273d72274ae24f1084a22",
        "effective_time_utc": "2021-11-22T14:03:13Z",
        "block_number": 13_664_911,
        "transaction_hash": "0xd0bc8bb58931497ce575f3d1afda63890a226cef7fa08d80c98d78f70c74567d",
    },
    "WBTC-C": {
        "contract_address": "0x39f29773dcb94a32529d0612c6706c49622161d1",
        "effective_time_utc": "2021-11-29T14:00:07Z",
        "block_number": 13_709_002,
        "transaction_hash": "0xab810a967ba4a68862c4433ec4185fbe1a3ff121bf4b38535a2aab4a8e9908a4",
    },
}


class ProtocolProductionError(RuntimeError):
    """Raised when persistence or reconstruction fails a stop gate."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
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
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def write_dataframe_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial.csv")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    with temporary.open("rb+") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def validate_sql(spec: ModuleSpec, sql: str) -> dict[str, Any]:
    lower = sql.lower()
    failures: list[str] = []
    for fragment in (
        "2021-06-01 00:00:00", "2024-07-01 00:00:00",
        "pre_sample_initial_state", "in_sample_change",
        "call_block_date", "call_block_time", "order by",
    ):
        if fragment not in lower:
            failures.append(f"missing SQL fragment: {fragment}")
    for ilk in TARGET_ILKS:
        if f"'{ilk.lower()}'" not in lower:
            failures.append(f"missing exact ilk: {ilk}")
    for forbidden in ("select *", "prices.", "{{", "api_key"):
        if forbidden in lower:
            failures.append(f"forbidden SQL fragment: {forbidden}")
    if spec.name == "Clipper" and "maker_ethereum.dog_call_file" not in lower:
        failures.append("Clipper query must derive the effective contract universe from Dog")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "sql_sha256": sha256_text(sql),
    }


def initialise_module(spec: ModuleSpec) -> dict[str, Any]:
    if spec.raw_path.exists() or spec.payload_path.exists():
        raise ProtocolProductionError(f"Refusing to overwrite {spec.name} artefacts")
    sql = spec.sql_path.read_text(encoding="utf-8")
    report = validate_sql(spec, sql)
    if not report["validation_passed"]:
        raise ProtocolProductionError("; ".join(report["failures"]))
    state = {
        "module": spec.name,
        "state": "planned",
        "query_type": "private temporary production",
        "engine": "small",
        "sql_path": relative(spec.sql_path),
        "sql_sha256": report["sql_sha256"],
        "query_id": None,
        "query_url": None,
        "execution_id": None,
        "result_retrieval_count": 0,
        "raw_file_persisted": False,
        "validation_passed": False,
        "sample_start_utc": SAMPLE_START.isoformat(),
        "sample_end_exclusive_utc": SAMPLE_END.isoformat(),
    }
    write_json_atomic(spec.state_path, state)
    return state


def update_module_state(spec: ModuleSpec, state_name: str, **fields: Any) -> dict[str, Any]:
    if not spec.state_path.exists():
        raise ProtocolProductionError(f"{spec.name} state file does not exist")
    state = json.loads(spec.state_path.read_text(encoding="utf-8"))
    state.update(fields)
    state["state"] = state_name
    write_json_atomic(spec.state_path, state)
    return state


def _expected_pre_series(spec: ModuleSpec, frame: pd.DataFrame) -> set[tuple[str, str, str]]:
    if spec.name == "Vat":
        expected = {(ilk, parameter, "") for ilk in TARGET_ILKS for parameter in
                    ("debt_ceiling", "minimum_debt")} | {
                        ("GLOBAL", "global_debt_ceiling", "")}
        if VAT_ACTIVATION_EVIDENCE_PATH.exists():
            evidence = json.loads(VAT_ACTIVATION_EVIDENCE_PATH.read_text(encoding="utf-8"))
            if evidence.get("status") == "validated":
                parameter_map = {"line": "debt_ceiling", "dust": "minimum_debt"}
                for series, details in evidence.get("classifications", {}).items():
                    ilk, key = series.split(":", 1)
                    if details.get("classification") == "activated_during_sample":
                        expected.discard((ilk, parameter_map[key], ""))
        return expected
    if spec.name == "Spot":
        expected = {(ilk, parameter, "") for ilk in TARGET_ILKS for parameter in
                    ("liquidation_ratio", "oracle_adapter", "effective_liquidation_spot")}
        for ilk in _documented_activation_times():
            for parameter in ("liquidation_ratio", "oracle_adapter", "effective_liquidation_spot"):
                expected.discard((ilk, parameter, ""))
        return expected
    if spec.name == "Jug":
        expected = {(ilk, "stability_fee_duty", "") for ilk in TARGET_ILKS} | {
            ("GLOBAL", "stability_fee_base", "")}
        for ilk in _documented_activation_times():
            expected.discard((ilk, "stability_fee_duty", ""))
        return expected
    if spec.name == "Dog":
        expected = {(ilk, parameter, "") for ilk in TARGET_ILKS for parameter in
                    ("liquidation_penalty", "ilk_liquidation_capacity", "clipper_mapping")} | {
                        ("GLOBAL", "global_liquidation_capacity", "")}
        for ilk in _documented_activation_times():
            for parameter in ("liquidation_penalty", "ilk_liquidation_capacity", "clipper_mapping"):
                expected.discard((ilk, parameter, ""))
        return expected
    return {
        (str(row.ilk), str(row.parameter), str(row.source_contract).lower())
        for row in frame.itertuples(index=False)
        if pd.Timestamp(row.effective_time_utc) < SAMPLE_START
    }


def _documented_activation_times() -> dict[str, pd.Timestamp]:
    if not VAT_ACTIVATION_EVIDENCE_PATH.exists():
        return {}
    evidence = json.loads(VAT_ACTIVATION_EVIDENCE_PATH.read_text(encoding="utf-8"))
    if evidence.get("status") != "validated":
        return {}
    activations: dict[str, pd.Timestamp] = {}
    for series, details in evidence.get("classifications", {}).items():
        if details.get("classification") != "activated_during_sample":
            continue
        ilk, key = series.split(":", 1)
        if key != "line":
            continue
        activation = details.get("activation_setting") or {}
        activations[ilk] = pd.to_datetime(activation.get("timestamp"), utc=True)
    return activations


def validate_clipper_stopped_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Validate documented Clipper defaults without treating absence as zero."""
    failures: list[str] = []
    source = evidence.get("verified_source") or {}
    semantics = evidence.get("solidity_storage_semantics") or {}
    diagnostic = evidence.get("diagnostic") or {}
    if evidence.get("status") != "validated":
        failures.append("Clipper stopped evidence is not marked validated")
    if source.get("declaration") != "uint256 public stopped = 0;":
        failures.append("verified source does not explicitly initialise stopped to zero")
    if not source.get("exact_match_deployment_evidence"):
        failures.append("deployed-source exact-match evidence is absent")
    if source.get("constructor_assigns_stopped") is not False:
        failures.append("constructor non-override of stopped is not established")
    if not semantics.get("uint_default_is_zero") or not semantics.get("reference"):
        failures.append("Solidity zero-state semantics are not documented")
    explicit_call_count = diagnostic.get("explicit_stopped_call_count")
    non_zero_call_count = diagnostic.get("non_zero_stopped_call_count")
    if explicit_call_count is None:
        failures.append("explicit stopped-call count is not established")
    elif explicit_call_count != 0:
        failures.append("explicit stopped calls require observed-call reconstruction")
    if non_zero_call_count is None:
        failures.append("absence of earlier non-zero stopped calls is not established")
    elif non_zero_call_count != 0:
        failures.append("an earlier non-zero stopped call exists")
    if not diagnostic.get("all_six_addresses_included"):
        failures.append("the stopped-call scan did not establish all six addresses")
    if diagnostic.get("deployment_record_count") != len(TARGET_ILKS):
        failures.append("the diagnostic did not establish six deployment records")
    if diagnostic.get("scan_end_exclusive_utc") != SAMPLE_END.isoformat():
        failures.append("the stopped-call history does not end at the sample boundary")

    states = evidence.get("series") or []
    if len(states) != len(TARGET_ILKS):
        failures.append("documented default-state count is not six")
    by_ilk = {str(item.get("ilk")): item for item in states}
    if set(by_ilk) != set(TARGET_ILKS):
        failures.append("documented default-state ilks differ from the target population")
    for ilk in TARGET_ILKS:
        item = by_ilk.get(ilk) or {}
        mapping = CLIPPER_MAPPINGS[ilk]
        contract = str(item.get("contract_address") or "").lower()
        if contract != mapping["contract_address"]:
            failures.append(f"Clipper contract mismatch for {ilk}")
        if item.get("classification") != "explicit_zero_initial_state":
            failures.append(f"unsupported stopped classification for {ilk}")
            continue
        if str(item.get("initial_value")) != "0":
            failures.append(f"stopped initial value is not zero for {ilk}")
        if item.get("state_source") != "contract_default":
            failures.append(f"stopped state source is not contract_default for {ilk}")
        if item.get("is_observed_call") is not False:
            failures.append(f"documented default is incorrectly marked observed for {ilk}")
        deployment_time = pd.to_datetime(item.get("deployment_time_utc"), utc=True, errors="coerce")
        mapping_time = pd.to_datetime(mapping["effective_time_utc"], utc=True)
        effective_time = pd.to_datetime(item.get("effective_start_utc"), utc=True, errors="coerce")
        if pd.isna(deployment_time) or deployment_time > mapping_time:
            failures.append(f"invalid deployment boundary for {ilk}")
        if pd.isna(effective_time) or effective_time != mapping_time:
            failures.append(f"default does not begin at the Dog mapping boundary for {ilk}")
        if int(item.get("mapping_block_number") or -1) != mapping["block_number"]:
            failures.append(f"mapping block mismatch for {ilk}")
        if str(item.get("mapping_transaction_hash") or "").lower() != mapping["transaction_hash"]:
            failures.append(f"mapping transaction mismatch for {ilk}")
        for field in ("deployment_transaction_hash", "mapping_transaction_hash"):
            if not re.fullmatch(r"0x[0-9a-fA-F]{64}", str(item.get(field) or "")):
                failures.append(f"malformed {field} for {ilk}")
        if not item.get("verified_clipper_abi"):
            failures.append(f"deployed Clipper ABI evidence is absent for {ilk}")
        if not item.get("verified_source_exact_match"):
            failures.append(f"exact-match deployed source is absent for {ilk}")
        source_url = str(item.get("verified_source_url") or "").lower()
        if mapping["contract_address"] not in source_url:
            failures.append(f"verified-source URL does not bind the {ilk} contract")
        if not re.fullmatch(
            r"0x[0-9a-fA-F]{64}", str(item.get("creation_code_hash") or "")
        ):
            failures.append(f"creation code hash is absent or malformed for {ilk}")
        if item.get("constructor_assigns_stopped") is not False:
            failures.append(f"constructor stopped non-override is absent for {ilk}")
        if int(item.get("explicit_stopped_call_count") or 0) != 0:
            failures.append(f"explicit stopped calls require reconstruction for {ilk}")
        if item.get("earlier_non_zero_call_count") is None:
            failures.append(f"earlier non-zero call absence is not established for {ilk}")
        elif item.get("earlier_non_zero_call_count") != 0:
            failures.append(f"earlier non-zero stopped call found for {ilk}")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "documented_series_count": len(states),
        "documented_ilks": sorted(by_ilk),
        "explicit_stopped_call_count": diagnostic.get("explicit_stopped_call_count"),
        "non_zero_stopped_call_count": diagnostic.get("non_zero_stopped_call_count"),
    }


def validate_clipper_stopped_minimal_rows(
    rows: list[dict[str, Any]], columns: list[str]
) -> dict[str, Any]:
    """Validate the bounded creation/stopped-call diagnostic result."""
    failures: list[str] = []
    if tuple(columns) != CLIPPER_STOPPED_MINIMAL_COLUMNS:
        failures.append(f"unexpected columns: {columns}")
    frame = pd.DataFrame(rows)
    if frame.empty or not set(CLIPPER_STOPPED_MINIMAL_COLUMNS).issubset(frame.columns):
        return {
            "validation_passed": False,
            "failures": failures or ["diagnostic result is empty or malformed"],
            "row_count": len(rows),
            "column_count": len(columns),
        }
    frame["contract_address"] = frame["contract_address"].astype(str).str.lower()
    frame["transaction_hash"] = frame["transaction_hash"].astype(str).str.lower()
    frame["mapping_tx_hash"] = frame["mapping_tx_hash"].astype(str).str.lower()
    frame["block_time"] = pd.to_datetime(frame["block_time"], utc=True, errors="coerce")
    frame["mapping_time"] = pd.to_datetime(frame["mapping_time"], utc=True, errors="coerce")
    frame["block_number"] = pd.to_numeric(frame["block_number"], errors="coerce")
    frame["mapping_block"] = pd.to_numeric(frame["mapping_block"], errors="coerce")
    creations = frame[frame["record_type"] == "contract_creation"].copy()
    calls = frame[frame["record_type"] == "stopped_file_call"].copy()
    unexpected_types = sorted(
        set(frame["record_type"]) - {"contract_creation", "stopped_file_call"}
    )
    if unexpected_types:
        failures.append(f"unexpected record types: {unexpected_types}")
    if len(creations) != len(TARGET_ILKS):
        failures.append(f"creation record count is {len(creations)}, expected six")
    expected_addresses = {
        mapping["contract_address"] for mapping in CLIPPER_MAPPINGS.values()
    }
    if set(creations["contract_address"]) != expected_addresses:
        failures.append("creation addresses differ from the six Dog mappings")
    if creations["contract_address"].duplicated().any():
        failures.append("duplicate creation records exist")
    if set(creations["ilk"]) != set(TARGET_ILKS):
        failures.append("creation ilks differ from the target population")
    malformed_hashes = ~frame["transaction_hash"].str.fullmatch(r"0x[0-9a-f]{64}")
    if malformed_hashes.any():
        failures.append(f"malformed transaction hashes: {int(malformed_hashes.sum())}")
    unsuccessful_creations = creations["success"].astype(str).str.lower().ne("true")
    if unsuccessful_creations.any():
        failures.append("one or more contract creations were unsuccessful")
    if creations["block_time"].isna().any() or creations["block_number"].isna().any():
        failures.append("creation time or block is unavailable")
    if (creations["block_time"] > creations["mapping_time"]).any():
        failures.append("a contract creation occurs after its Dog mapping boundary")
    mapping_failures = 0
    for row in frame.itertuples(index=False):
        mapping = CLIPPER_MAPPINGS.get(str(row.ilk))
        if mapping is None or str(row.contract_address) != mapping["contract_address"]:
            mapping_failures += 1
            continue
        if int(row.mapping_block) != mapping["block_number"]:
            mapping_failures += 1
        if str(row.mapping_tx_hash) != mapping["transaction_hash"]:
            mapping_failures += 1
    if mapping_failures:
        failures.append(f"Dog mapping mismatches: {mapping_failures}")
    duplicate_calls = int(calls.duplicated(
        ["contract_address", "transaction_hash", "trace_position"], keep=False
    ).sum())
    if duplicate_calls:
        failures.append(f"duplicate stopped calls: {duplicate_calls}")
    invalid_values = 0
    for value in calls["stopped_value"]:
        try:
            if int(value) not in {0, 1, 2, 3}:
                invalid_values += 1
        except (TypeError, ValueError, OverflowError):
            invalid_values += 1
    if invalid_values:
        failures.append(f"invalid stopped values: {invalid_values}")
    ordering_columns = [
        "block_time", "block_number", "transaction_hash", "trace_position", "record_type"
    ]
    deterministic = frame.sort_values(
        ordering_columns, kind="stable", na_position="first"
    ).index.tolist() == frame.index.tolist()
    if not deterministic:
        failures.append("rows are not in deterministic diagnostic order")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(frame),
        "column_count": len(columns),
        "creation_record_count": len(creations),
        "explicit_stopped_call_count": len(calls),
        "successful_stopped_call_count": int(
            calls["success"].astype(str).str.lower().eq("true").sum()
        ),
        "non_zero_successful_stopped_call_count": int(
            (
                calls["success"].astype(str).str.lower().eq("true")
                & pd.to_numeric(calls["stopped_value"], errors="coerce").ne(0)
            ).sum()
        ),
        "duplicate_stopped_call_count": duplicate_calls,
        "deterministic_ordering": deterministic,
        "deployment_to_sample_end_filter_validated": True,
    }


def persist_clipper_stopped_minimal_payload() -> dict[str, Any]:
    """Promote the one authorised MCP response through an atomic CSV handoff."""
    if CLIPPER_STOPPED_MINIMAL_PATH.exists():
        raise ProtocolProductionError("minimal Clipper diagnostic CSV already exists")
    if not CLIPPER_STOPPED_MINIMAL_PAYLOAD_PATH.exists():
        raise ProtocolProductionError("minimal Clipper diagnostic payload is absent")
    payload = json.loads(
        CLIPPER_STOPPED_MINIMAL_PAYLOAD_PATH.read_text(encoding="utf-8")
    )
    structured = payload.get("structuredContent")
    if not isinstance(structured, dict):
        raise ProtocolProductionError("MCP payload lacks structured content")
    query = structured.get("query") or {}
    execution = structured.get("execution") or {}
    preview = structured.get("result_preview") or {}
    result_metadata = preview.get("resultMetadata") or {}
    data = preview.get("data") or {}
    rows = data.get("rows")
    columns = [
        str(item.get("name")) for item in result_metadata.get("columns", [])
        if isinstance(item, dict)
    ]
    if preview.get("state") != "COMPLETED":
        raise ProtocolProductionError(
            f"minimal Clipper diagnostic state is {preview.get('state')}"
        )
    if not isinstance(rows, list):
        raise ProtocolProductionError("minimal Clipper diagnostic rows are absent")
    if int(result_metadata.get("totalRowCount", -1)) != len(rows):
        raise ProtocolProductionError("minimal Clipper diagnostic result is incomplete")
    if tuple(columns) != CLIPPER_STOPPED_MINIMAL_COLUMNS:
        raise ProtocolProductionError("minimal Clipper diagnostic schema differs")
    descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{CLIPPER_STOPPED_MINIMAL_PATH.name}.", suffix=".partial",
        dir=CLIPPER_STOPPED_MINIMAL_PATH.parent,
    )
    partial = Path(partial_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=columns, extrasaction="raise", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        with partial.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            parsed_rows = list(reader)
            parsed_columns = list(reader.fieldnames or [])
        report = validate_clipper_stopped_minimal_rows(parsed_rows, parsed_columns)
        write_json_atomic(CLIPPER_STOPPED_MINIMAL_VALIDATION_PATH, report)
        if not report["validation_passed"]:
            raise ProtocolProductionError("; ".join(report["failures"]))
        os.replace(partial, CLIPPER_STOPPED_MINIMAL_PATH)
        _fsync_directory(CLIPPER_STOPPED_MINIMAL_PATH.parent)
    except Exception:
        if partial.exists():
            failure = partial.with_suffix(partial.suffix + ".failed")
            os.replace(partial, failure)
            _fsync_directory(failure.parent)
        raise
    checksum = sha256_file(CLIPPER_STOPPED_MINIMAL_PATH)
    size = CLIPPER_STOPPED_MINIMAL_PATH.stat().st_size
    metadata = {
        "phase": "1D",
        "operation": "minimal Clipper stopped replacement diagnostic",
        "query_id": query.get("query_id"),
        "query_url": query.get("url"),
        "execution_id": execution.get("execution_id"),
        "execution_state": preview.get("state"),
        "engine": execution.get("engine_used"),
        "sql_path": relative(CLIPPER_STOPPED_MINIMAL_SQL_PATH),
        "sql_sha256": sha256_file(CLIPPER_STOPPED_MINIMAL_SQL_PATH),
        "dimensions": [len(rows), len(columns)],
        "raw_path": relative(CLIPPER_STOPPED_MINIMAL_PATH),
        "raw_size_bytes": size,
        "raw_sha256": checksum,
        "result_retrieval_count": 1,
        "execution_cost_credits": result_metadata.get("executionCostCredits"),
        "persisted_at_utc": utc_now_iso(),
        "validation_path": relative(CLIPPER_STOPPED_MINIMAL_VALIDATION_PATH),
        "full_creation_scan_start": "2020-01-01T00:00:00Z",
        "full_stopped_call_scan_end_exclusive": SAMPLE_END.isoformat(),
    }
    write_json_atomic(CLIPPER_STOPPED_MINIMAL_METADATA_PATH, metadata)
    os.replace(
        CLIPPER_STOPPED_MINIMAL_PAYLOAD_PATH,
        CLIPPER_STOPPED_MINIMAL_RESPONSE_PATH,
    )
    _fsync_directory(CLIPPER_STOPPED_MINIMAL_RESPONSE_PATH.parent)
    return report | metadata


def _clipper_stopped_evidence() -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not CLIPPER_STOPPED_EVIDENCE_PATH.exists():
        return None, {
            "validation_passed": False,
            "failures": ["Clipper stopped evidence file is absent"],
        }
    evidence = json.loads(CLIPPER_STOPPED_EVIDENCE_PATH.read_text(encoding="utf-8"))
    return evidence, validate_clipper_stopped_evidence(evidence)


def _clipper_documented_default_rows() -> pd.DataFrame:
    evidence, report = _clipper_stopped_evidence()
    if evidence is None or not report["validation_passed"]:
        raise ProtocolProductionError("Clipper stopped defaults are not validated")
    evidence_reference = relative(CLIPPER_STOPPED_EVIDENCE_PATH)
    rows: list[dict[str, Any]] = []
    for item in evidence["series"]:
        effective_time = pd.to_datetime(item["effective_start_utc"], utc=True)
        rows.append({
            "module": "Clipper",
            "ilk": item["ilk"],
            "parameter": "auction_stopped",
            "parameter_key": "stopped",
            "source_classification": (
                "pre_sample_initial_state" if effective_time < SAMPLE_START
                else "in_sample_change"
            ),
            "effective_time_utc": effective_time,
            "block_number": item["mapping_block_number"],
            "transaction_index": pd.NA,
            "source_position": "contract_default_at_mapping",
            "source_contract": item["contract_address"],
            "transaction_hash": item["mapping_transaction_hash"],
            "raw_value": "0",
            "converted_value": 0.0,
            "converted_unit": "integer",
            "auxiliary_raw_value": None,
            "state_source": "contract_default",
            "is_observed_call": False,
            "evidence_reference": evidence_reference,
        })
    return pd.DataFrame(rows, columns=COMMON_COLUMNS + DERIVED_PROVENANCE_COLUMNS)


def _conversion(raw: str, parameter: str) -> float | None:
    if parameter in {"oracle_adapter", "clipper_mapping"}:
        return None
    numeric = Decimal(str(raw))
    if parameter in {
        "debt_ceiling", "minimum_debt", "global_debt_ceiling",
        "ilk_liquidation_capacity", "global_liquidation_capacity",
        "auction_keeper_fixed",
    }:
        return float(numeric / Decimal("1e45"))
    if parameter in {
        "liquidation_ratio", "effective_liquidation_spot",
        "stability_fee_duty", "stability_fee_base", "auction_price_buffer",
        "auction_cusp",
    }:
        return float(numeric / Decimal("1e27"))
    if parameter == "liquidation_penalty":
        return float(numeric / Decimal("1e18") - 1)
    if parameter == "auction_keeper_fraction":
        return float(numeric / Decimal("1e18"))
    if parameter in {"auction_tail", "auction_stopped"}:
        return float(numeric)
    raise ProtocolProductionError(f"Unsupported parameter conversion: {parameter}")


def validate_module_rows(
    spec: ModuleSpec, rows: list[dict[str, Any]], columns: list[str]
) -> dict[str, Any]:
    failures: list[str] = []
    if tuple(columns) != COMMON_COLUMNS:
        failures.append(f"unexpected columns: {columns}")
    if not rows:
        failures.append("result is empty")
    frame = pd.DataFrame(rows)
    if frame.empty or not set(COMMON_COLUMNS).issubset(frame.columns):
        return {"validation_passed": False, "failures": failures,
                "row_count": len(rows), "column_count": len(columns)}
    frame["effective_time_utc"] = pd.to_datetime(frame["effective_time_utc"], utc=True)
    frame["block_number"] = pd.to_numeric(frame["block_number"], errors="coerce")
    frame["transaction_index"] = pd.to_numeric(frame["transaction_index"], errors="coerce")
    allowed_ilks = set(TARGET_ILKS) | {"GLOBAL"}
    unexpected_ilks = sorted(set(frame["ilk"]) - allowed_ilks)
    if unexpected_ilks:
        failures.append(f"unexpected ilks: {unexpected_ilks}")
    observed_target_ilks = set(frame.loc[frame["ilk"] != "GLOBAL", "ilk"])
    if observed_target_ilks != set(TARGET_ILKS):
        failures.append(f"target ilk population mismatch: {sorted(observed_target_ilks)}")
    if set(frame["module"]) != {spec.name}:
        failures.append("unexpected module label")
    unexpected_parameters = sorted(set(frame["parameter"]) - set(spec.parameters))
    if unexpected_parameters:
        failures.append(f"unexpected parameters: {unexpected_parameters}")
    if spec.name == "Vat":
        expected_population = {
            (ilk, parameter) for ilk in TARGET_ILKS
            for parameter in ("debt_ceiling", "minimum_debt")
        } | {("GLOBAL", "global_debt_ceiling")}
    elif spec.name == "Spot":
        expected_population = {
            (ilk, parameter) for ilk in TARGET_ILKS for parameter in spec.parameters
        }
    elif spec.name == "Jug":
        expected_population = {
            (ilk, "stability_fee_duty") for ilk in TARGET_ILKS
        } | {("GLOBAL", "stability_fee_base")}
    elif spec.name == "Dog":
        expected_population = {
            (ilk, parameter) for ilk in TARGET_ILKS
            for parameter in (
                "liquidation_penalty", "ilk_liquidation_capacity", "clipper_mapping"
            )
        } | {("GLOBAL", "global_liquidation_capacity")}
    else:
        expected_population = {
            (ilk, parameter) for ilk in TARGET_ILKS for parameter in spec.parameters
        }
    observed_population = set(zip(frame["ilk"], frame["parameter"]))
    missing_parameter_population = sorted(expected_population - observed_population)
    documented_default_states: dict[str, Any] = {}
    clipper_evidence_report: dict[str, Any] | None = None
    if spec.name == "Clipper":
        evidence, clipper_evidence_report = _clipper_stopped_evidence()
        if clipper_evidence_report["validation_passed"] and evidence is not None:
            documented_ilks = {
                str(item["ilk"]) for item in evidence.get("series", [])
                if item.get("classification") == "explicit_zero_initial_state"
            }
            missing_parameter_population = [
                item for item in missing_parameter_population
                if not (item[1] == "auction_stopped" and item[0] in documented_ilks)
            ]
            documented_default_states = {
                f"{item['ilk']}:auction_stopped": {
                    "initial_value": "0",
                    "state_source": "contract_default",
                    "is_observed_call": False,
                    "effective_start_utc": item["effective_start_utc"],
                    "contract_address": item["contract_address"],
                    "evidence_reference": relative(CLIPPER_STOPPED_EVIDENCE_PATH),
                }
                for item in evidence.get("series", [])
            }
    if missing_parameter_population:
        failures.append(
            f"missing required parameter series: {missing_parameter_population}"
        )
    if not set(frame["source_classification"]).issubset(
        {"pre_sample_initial_state", "in_sample_change"}
    ):
        failures.append("unexpected source classification")
    pre = frame["source_classification"].eq("pre_sample_initial_state")
    if (frame.loc[pre, "effective_time_utc"] >= SAMPLE_START).any():
        failures.append("pre-sample rows are not strictly before the sample")
    if ((frame.loc[~pre, "effective_time_utc"] < SAMPLE_START) |
            (frame.loc[~pre, "effective_time_utc"] >= SAMPLE_END)).any():
        failures.append("in-sample rows fall outside the sample")
    malformed_contracts = ~frame["source_contract"].astype(str).str.match(r"^0x[0-9a-fA-F]{40}$")
    malformed_hashes = ~frame["transaction_hash"].astype(str).str.match(r"^0x[0-9a-fA-F]{64}$")
    if malformed_contracts.any():
        failures.append(f"malformed source contracts: {int(malformed_contracts.sum())}")
    if malformed_hashes.any():
        failures.append(f"malformed transaction hashes: {int(malformed_hashes.sum())}")
    canonical = CANONICAL_CONTRACTS.get(spec.name)
    if canonical is not None:
        unexpected_contracts = sorted(
            set(frame["source_contract"].astype(str).str.lower()) - {canonical}
        )
        if unexpected_contracts:
            failures.append(f"unexpected {spec.name} source contracts: {unexpected_contracts}")
    if spec.name == "Clipper":
        for ilk, mapping in CLIPPER_MAPPINGS.items():
            observed_contracts = set(
                frame.loc[frame["ilk"] == ilk, "source_contract"]
                .astype(str).str.lower()
            )
            if observed_contracts != {mapping["contract_address"]}:
                failures.append(
                    f"Clipper contract population mismatch for {ilk}: "
                    f"{sorted(observed_contracts)}"
                )
    key_expectations = {
        "debt_ceiling": "line", "minimum_debt": "dust",
        "global_debt_ceiling": "Line", "liquidation_ratio": "mat",
        "oracle_adapter": "pip", "effective_liquidation_spot": "poke",
        "stability_fee_duty": "duty", "stability_fee_base": "base",
        "liquidation_penalty": "chop", "ilk_liquidation_capacity": "hole",
        "global_liquidation_capacity": "Hole", "clipper_mapping": "clip",
        "auction_price_buffer": "buf", "auction_tail": "tail",
        "auction_cusp": "cusp", "auction_keeper_fraction": "chip",
        "auction_keeper_fixed": "tip", "auction_stopped": "stopped",
    }
    wrong_keys = frame[
        frame.apply(lambda row: key_expectations.get(row["parameter"]) != row["parameter_key"], axis=1)
    ]
    if not wrong_keys.empty:
        failures.append(f"parameter-key mismatches: {len(wrong_keys)}")
    source_key = ["source_contract", "transaction_hash", "source_position", "parameter", "ilk"]
    duplicate_count = int(frame.duplicated(source_key, keep=False).sum())
    if duplicate_count:
        failures.append(f"duplicate source calls: {duplicate_count}")
    ordering = frame.sort_values(
        ["effective_time_utc", "block_number", "transaction_index", "source_position"],
        kind="stable", na_position="first",
    ).index.tolist()
    if ordering != frame.index.tolist():
        failures.append("rows are not in deterministic chronological source order")
    conversion_failures = 0
    address_failures = 0
    for row in frame.itertuples(index=False):
        if row.parameter in {"oracle_adapter", "clipper_mapping"}:
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", str(row.raw_value)):
                address_failures += 1
            continue
        try:
            raw = Decimal(str(row.raw_value))
            converted = float(row.converted_value)
        except (ValueError, TypeError, ArithmeticError):
            conversion_failures += 1
            continue
        expected = _conversion(str(row.raw_value), str(row.parameter))
        if raw < 0 or expected is None or not math.isfinite(converted) or not math.isclose(
            converted, expected, rel_tol=1e-12, abs_tol=1e-12
        ):
            conversion_failures += 1
    if address_failures:
        failures.append(f"invalid address-valued settings: {address_failures}")
    if conversion_failures:
        failures.append(f"raw-to-converted unit failures: {conversion_failures}")
    expected_pre = _expected_pre_series(spec, frame)
    if spec.name == "Clipper":
        observed_pre = {
            (str(row.ilk), str(row.parameter), str(row.source_contract).lower())
            for row in frame.loc[pre].itertuples(index=False)
        }
    else:
        observed_pre = {
            (str(row.ilk), str(row.parameter), "")
            for row in frame.loc[pre].itertuples(index=False)
        }
    missing_pre = sorted(expected_pre - observed_pre)
    multiple_pre_count = int(frame.loc[pre].duplicated(
        ["ilk", "parameter"] + (["source_contract"] if spec.name == "Clipper" else []),
        keep=False,
    ).sum())
    if missing_pre:
        failures.append(f"missing pre-sample states: {missing_pre}")
    if multiple_pre_count:
        failures.append(f"multiple pre-sample states: {multiple_pre_count}")
    documented_activations: dict[str, Any] = {}
    if spec.name == "Vat" and VAT_ACTIVATION_EVIDENCE_PATH.exists():
        evidence = json.loads(VAT_ACTIVATION_EVIDENCE_PATH.read_text(encoding="utf-8"))
        if evidence.get("status") == "validated":
            parameter_map = {"line": "debt_ceiling", "dust": "minimum_debt"}
            for series, details in evidence.get("classifications", {}).items():
                if details.get("classification") != "activated_during_sample":
                    continue
                ilk, key = series.split(":", 1)
                parameter = parameter_map[key]
                series_rows = frame[
                    (frame["ilk"] == ilk) & (frame["parameter"] == parameter)
                ].sort_values(
                    ["effective_time_utc", "block_number", "transaction_index", "source_position"],
                    kind="stable", na_position="first",
                )
                activation = details.get("activation_setting") or {}
                expected_time = pd.to_datetime(activation.get("timestamp"), utc=True)
                expected_raw = str(activation.get("raw_value"))
                expected_block = int(activation.get("block_number"))
                expected_hash = str(activation.get("transaction_hash")).lower()
                expected_position = str(activation.get("call_position"))
                pre_rows = series_rows[
                    series_rows["source_classification"] == "pre_sample_initial_state"
                ]
                in_sample = series_rows[
                    series_rows["source_classification"] == "in_sample_change"
                ]
                boundary_valid = bool(
                    pre_rows.empty
                    and not in_sample.empty
                    and in_sample.iloc[0]["effective_time_utc"] == expected_time
                    and str(in_sample.iloc[0]["raw_value"]) == expected_raw
                    and int(in_sample.iloc[0]["block_number"]) == expected_block
                    and str(in_sample.iloc[0]["transaction_hash"]).lower() == expected_hash
                    and str(in_sample.iloc[0]["source_position"]) == expected_position
                )
                if not boundary_valid:
                    failures.append(f"documented activation boundary mismatch: {series}")
                documented_activations[series] = {
                    "activation_time_utc": expected_time.isoformat(),
                    "initial_raw_value": expected_raw,
                    "activation_block_number": expected_block,
                    "activation_transaction_hash": expected_hash,
                    "activation_source_position": expected_position,
                    "boundary_valid": boundary_valid,
                    "pre_activation_forward_fill_permitted": False,
                }
    if spec.name in {"Spot", "Jug", "Dog"}:
        for ilk, activation_time in _documented_activation_times().items():
            for parameter in spec.parameters:
                if parameter.startswith("global_") or parameter == "stability_fee_base":
                    continue
                series_rows = frame[
                    (frame["ilk"] == ilk) & (frame["parameter"] == parameter)
                ].sort_values(
                    ["effective_time_utc", "block_number", "transaction_index", "source_position"],
                    kind="stable", na_position="first",
                )
                pre_rows = series_rows[
                    series_rows["source_classification"] == "pre_sample_initial_state"
                ]
                in_sample = series_rows[
                    series_rows["source_classification"] == "in_sample_change"
                ]
                boundary_valid = bool(
                    pre_rows.empty and not in_sample.empty
                    and in_sample.iloc[0]["effective_time_utc"] >= activation_time
                )
                if not boundary_valid:
                    failures.append(f"documented ilk activation mismatch: {ilk}:{parameter}")
                documented_activations[f"{ilk}:{parameter}"] = {
                    "ilk_activation_time_utc": activation_time.isoformat(),
                    "first_parameter_time_utc": (
                        in_sample.iloc[0]["effective_time_utc"].isoformat()
                        if not in_sample.empty else None
                    ),
                    "boundary_valid": boundary_valid,
                    "pre_activation_forward_fill_permitted": False,
                }
    return {
        "validation_passed": not failures,
        "failures": failures,
        "module": spec.name,
        "row_count": len(frame),
        "column_count": len(columns),
        "observed_ilks": sorted(observed_target_ilks),
        "parameter_counts": {
            f"{ilk}:{parameter}": int(count)
            for (ilk, parameter), count in frame.groupby(["ilk", "parameter"]).size().items()
        },
        "pre_sample_state_count": int(pre.sum()),
        "missing_pre_sample_states": [list(item) for item in missing_pre],
        "duplicate_source_call_rows": duplicate_count,
        "unit_conversion_failure_count": conversion_failures,
        "missing_required_parameter_series": [
            list(item) for item in missing_parameter_population
        ],
        "documented_in_sample_activations": documented_activations,
        "documented_default_states": documented_default_states,
        "clipper_stopped_evidence_validation": clipper_evidence_report,
        "minimum_time_utc": frame["effective_time_utc"].min().isoformat(),
        "maximum_time_utc": frame["effective_time_utc"].max().isoformat(),
    }


def persist_module_payload(spec: ModuleSpec) -> dict[str, Any]:
    if spec.raw_path.exists():
        raise ProtocolProductionError(f"{spec.name} raw file already exists")
    if not spec.payload_path.exists():
        raise ProtocolProductionError(f"{spec.name} payload does not exist")
    state = json.loads(spec.state_path.read_text(encoding="utf-8"))
    payload = json.loads(spec.payload_path.read_text(encoding="utf-8"))
    if payload.get("state") != "COMPLETED":
        update_module_state(spec, "failed", error=payload.get("errorMessage"))
        raise ProtocolProductionError(f"{spec.name} execution did not complete")
    if payload.get("executionId") != state.get("execution_id"):
        raise ProtocolProductionError(f"{spec.name} execution ID mismatch")
    rows = payload.get("data", {}).get("rows")
    metadata = payload.get("resultMetadata") or {}
    if not isinstance(rows, list):
        raise ProtocolProductionError(f"{spec.name} payload has no row list")
    columns = [column["name"] for column in metadata.get("columns", [])]
    total = int(metadata.get("totalRowCount", -1))
    if len(rows) != total:
        raise ProtocolProductionError(
            f"{spec.name} incomplete retrieval: {len(rows)} of {total} rows"
        )
    report = validate_module_rows(spec, rows, columns)
    write_json_atomic(spec.validation_path, report)
    if not report["validation_passed"]:
        update_module_state(spec, "failed", result_retrieval_count=1,
                            validation_passed=False, validation_failures=report["failures"])
        raise ProtocolProductionError("; ".join(report["failures"]))
    frame = pd.DataFrame(rows, columns=columns)
    write_dataframe_atomic(frame, spec.raw_path)
    checksum = sha256_file(spec.raw_path)
    size = spec.raw_path.stat().st_size
    spec.payload_path.unlink()
    update_module_state(
        spec, "complete", result_retrieval_count=1, raw_file_persisted=True,
        validation_passed=True, row_count=len(frame), column_count=len(frame.columns),
        raw_path=relative(spec.raw_path), raw_size_bytes=size, raw_sha256=checksum,
        execution_cost_credits=metadata.get("executionCostCredits"),
    )
    return report | {"raw_sha256": checksum, "raw_size_bytes": size}


def _api_json(api_key: str, url: str) -> dict[str, Any]:
    request = Request(url, headers={"X-Dune-API-Key": api_key}, method="GET")
    try:
        with urlopen(request, timeout=180) as response:
            body = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000].replace(api_key, "[REDACTED]")
        raise ProtocolProductionError(f"Dune API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ProtocolProductionError(f"Dune API request failed: {exc.reason}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProtocolProductionError("Dune returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ProtocolProductionError("Dune returned a non-object JSON response")
    return payload


def _normalise_api_metadata(payload: dict[str, Any]) -> tuple[int, list[str]]:
    candidates = [
        payload.get("result_metadata"), payload.get("resultMetadata"),
        (payload.get("result") or {}).get("metadata") if isinstance(payload.get("result"), dict) else None,
    ]
    metadata = next((item for item in candidates if isinstance(item, dict)), {})
    total = metadata.get("total_row_count", metadata.get("totalRowCount", metadata.get("row_count")))
    columns = metadata.get("column_names", metadata.get("columns"))
    if isinstance(columns, list) and columns and isinstance(columns[0], dict):
        columns = [item.get("name") for item in columns]
    if total is None or not isinstance(columns, list) or not columns:
        raise ProtocolProductionError("Execution metadata lacks total row count or schema")
    return int(total), [str(column) for column in columns]


def vat_recovery_preflight() -> dict[str, Any]:
    spec = MODULES["vat"]
    if not spec.state_path.exists():
        raise ProtocolProductionError("Vat state file is absent")
    state = json.loads(spec.state_path.read_text(encoding="utf-8"))
    checks = {
        "final_csv_absent": not spec.raw_path.exists(),
        "temporary_payload_absent": not spec.payload_path.exists(),
        "query_id": state.get("query_id") == 8069558,
        "execution_id": state.get("execution_id") == "01KY4TZWPGZPS66ZFZQ5YYQKH9",
        "execution_completed": state.get("execution_state") == "COMPLETED",
        "sql_checksum": sha256_file(spec.sql_path) == "41dcb14a7d7e8b996f8b821815fb0df222acfb655b14510cd4a62254e4ba3b99",
        "failed_wrapper_state_preserved": (
            state.get("failure_stage") == "local_result_persistence"
            and state.get("retrieved_result_not_locally_persisted") is True
            and "apply_patch" in str(state.get("failure_error"))
        ),
    }
    partials = sorted(spec.raw_path.parent.glob(f".{spec.raw_path.name}.*.partial"))
    checks["complete_partial_absent"] = not partials
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "validation_passed": not failures, "failures": failures, "checks": checks,
        "query_id": state.get("query_id"), "execution_id": state.get("execution_id"),
        "existing_partial_files": [relative(path) for path in partials],
        "recovery_method": "one status metadata GET followed by one result JSON GET in the same local process; no query submission capability",
    }


def _write_validate_promote(
    spec: ModuleSpec,
    rows: list[dict[str, Any]],
    columns: list[str],
) -> tuple[dict[str, Any], str, int]:
    """Write and fsync the result before semantic validation and promotion."""
    if spec.raw_path.exists():
        raise ProtocolProductionError(f"Refusing to overwrite {spec.name} raw result")
    if tuple(columns) != COMMON_COLUMNS:
        raise ProtocolProductionError(f"{spec.name} schema differs from expected columns")
    spec.raw_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{spec.raw_path.name}.", suffix=".partial", dir=spec.raw_path.parent,
    )
    partial = Path(partial_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=columns, extrasaction="raise", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        with partial.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            parsed_rows = list(reader)
            parsed_columns = list(reader.fieldnames or [])
        if len(parsed_rows) != len(rows) or parsed_columns != columns:
            raise ProtocolProductionError(f"{spec.name} partial CSV failed structural validation")
        report = validate_module_rows(spec, parsed_rows, parsed_columns)
        write_json_atomic(spec.validation_path, report)
        if not report["validation_passed"]:
            raise ProtocolProductionError("; ".join(report["failures"]))
        os.replace(partial, spec.raw_path)
        _fsync_directory(spec.raw_path.parent)
    except Exception:
        if partial.exists():
            failure_partial = partial.with_suffix(partial.suffix + ".failed")
            os.replace(partial, failure_partial)
            _fsync_directory(failure_partial.parent)
            update_module_state(
                spec, "persistence_or_validation_failed",
                raw_file_persisted=False,
                validation_passed=False,
                failed_partial_path=relative(failure_partial),
                failed_partial_size_bytes=failure_partial.stat().st_size,
                failed_partial_sha256=sha256_file(failure_partial),
            )
        raise
    return report, sha256_file(spec.raw_path), spec.raw_path.stat().st_size


def _result_rows(
    response: dict[str, Any], expected_rows: int, expected_columns: list[str]
) -> list[dict[str, Any]]:
    if response.get("state") != "QUERY_STATE_COMPLETED":
        raise ProtocolProductionError(f"Result response state is {response.get('state')}")
    result_object = response.get("result")
    rows = result_object.get("rows") if isinstance(result_object, dict) else None
    if not isinstance(rows, list):
        raise ProtocolProductionError("Completed result response lacks rows")
    result_rows, result_columns = _normalise_api_metadata(response)
    if result_rows != expected_rows or result_columns != expected_columns:
        raise ProtocolProductionError("Status and result metadata differ")
    if len(rows) != expected_rows:
        raise ProtocolProductionError(f"Incomplete result: {len(rows)} of {expected_rows} rows")
    if response.get("next_offset") not in (None, "", 0):
        raise ProtocolProductionError(
            f"Result is paginated at offset {response.get('next_offset')}"
        )
    return rows


def recover_vat_result(api_key: str) -> dict[str, Any]:
    """Retrieve the authorised completed Vat execution once and persist atomically."""
    spec = MODULES["vat"]
    preflight = vat_recovery_preflight()
    if not preflight["validation_passed"]:
        raise ProtocolProductionError("Vat recovery preflight failed: " + ", ".join(preflight["failures"]))
    execution_id = "01KY4TZWPGZPS66ZFZQ5YYQKH9"
    prior_state = json.loads(spec.state_path.read_text(encoding="utf-8"))
    prior_retrievals = int(prior_state.get("total_result_retrieval_count", 2))
    status = _api_json(api_key, f"{API_ROOT}/execution/{execution_id}/status")
    if status.get("state") != "QUERY_STATE_COMPLETED":
        raise ProtocolProductionError(f"Vat execution is not completed: {status.get('state')}")
    expected_rows, expected_columns = _normalise_api_metadata(status)
    if expected_rows != VAT_EXPECTED_ROWS:
        raise ProtocolProductionError(
            f"Vat status reports {expected_rows} rows, expected {VAT_EXPECTED_ROWS}"
        )
    if tuple(expected_columns) != COMMON_COLUMNS:
        raise ProtocolProductionError(f"Vat status schema differs from expected columns: {expected_columns}")
    limit = max(expected_rows + 100, 1000)
    query = urlencode({"limit": limit, "offset": 0})
    result = _api_json(api_key, f"{API_ROOT}/execution/{execution_id}/results?{query}")
    rows = _result_rows(result, expected_rows, expected_columns)
    update_module_state(
        spec, "result_retrieved", recovery_result_retrieval_count=1,
        recovery_status_request_count=1,
    )
    persisted_report, checksum, size = _write_validate_promote(
        spec, rows, expected_columns
    )
    recovery_time = utc_now_iso()
    metadata = {
        "module": "Vat", "query_id": 8069558, "execution_id": execution_id,
        "query_type": "private temporary production", "engine": "small",
        "sql_path": relative(spec.sql_path), "sql_sha256": sha256_file(spec.sql_path),
        "retrieval_operation": "result-only recovery of existing completed execution",
        "status_request_count": 1, "recovery_result_retrieval_count": 1,
        "prior_result_retrieval_count": prior_retrievals,
        "total_result_retrieval_count": prior_retrievals + 1,
        "recovered_at_utc": recovery_time, "dimensions": [len(rows), len(expected_columns)],
        "raw_path": relative(spec.raw_path), "raw_size_bytes": size, "raw_sha256": checksum,
        "validation_path": relative(spec.validation_path),
        "prior_malformed_patch_failure_preserved": True,
    }
    write_json_atomic(spec.metadata_path, metadata)
    write_json_atomic(spec.validation_path, persisted_report)
    update_module_state(
        spec, "complete", recovery_operation="existing execution result-only retrieval",
        recovery_status_request_count=1, recovery_result_retrieval_count=1,
        total_result_retrieval_count=prior_retrievals + 1, raw_file_persisted=True,
        validation_passed=True, recovered_at_utc=recovery_time,
        row_count=len(rows), column_count=len(expected_columns), raw_path=relative(spec.raw_path),
        raw_size_bytes=size, raw_sha256=checksum, metadata_path=relative(spec.metadata_path),
        validation_path=relative(spec.validation_path),
    )
    return persisted_report | {
        "raw_path": relative(spec.raw_path), "raw_size_bytes": size,
        "raw_sha256": checksum, "status_request_count": 1,
        "recovery_result_retrieval_count": 1,
    }


def retrieve_module_result(
    api_key: str, spec: ModuleSpec, timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Poll one recorded execution and retrieve its complete result exactly once."""
    if spec.name == "Vat":
        raise ProtocolProductionError("Vat must use its explicit recovery command")
    if spec.raw_path.exists():
        raise ProtocolProductionError(f"{spec.name} raw result already exists")
    state = json.loads(spec.state_path.read_text(encoding="utf-8"))
    execution_id = str(state.get("execution_id") or "")
    if not execution_id:
        raise ProtocolProductionError(f"{spec.name} execution ID is not recorded")
    if sha256_file(spec.sql_path) != state.get("sql_sha256"):
        raise ProtocolProductionError(f"{spec.name} SQL checksum differs from recorded state")
    deadline = time.monotonic() + timeout_seconds
    status_count = 0
    while True:
        status = _api_json(api_key, f"{API_ROOT}/execution/{execution_id}/status")
        status_count += 1
        execution_state = status.get("state")
        update_module_state(
            spec, "polling", status_request_count=status_count,
            execution_state=execution_state,
        )
        if execution_state == "QUERY_STATE_COMPLETED":
            break
        if execution_state in {
            "QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_CANCELED",
            "QUERY_STATE_EXPIRED",
        }:
            update_module_state(spec, "failed", execution_error=status.get("error"))
            raise ProtocolProductionError(
                f"{spec.name} execution ended in {execution_state}: {status.get('error')}"
            )
        if time.monotonic() >= deadline:
            update_module_state(spec, "timed_out", status_request_count=status_count)
            raise ProtocolProductionError(f"{spec.name} status polling timed out")
        time.sleep(2)
    expected_rows, expected_columns = _normalise_api_metadata(status)
    if expected_rows > 32_000:
        raise ProtocolProductionError(
            f"{spec.name} has {expected_rows} rows, above the one-request limit"
        )
    if tuple(expected_columns) != COMMON_COLUMNS:
        raise ProtocolProductionError(f"{spec.name} status schema differs from expected columns")
    limit = max(1000, expected_rows + 100)
    query = urlencode({"limit": limit, "offset": 0})
    response = _api_json(api_key, f"{API_ROOT}/execution/{execution_id}/results?{query}")
    rows = _result_rows(response, expected_rows, expected_columns)
    update_module_state(
        spec, "result_retrieved", status_request_count=status_count,
        result_retrieval_count=1, expected_row_count=expected_rows,
        expected_column_count=len(expected_columns),
    )
    report, checksum, size = _write_validate_promote(spec, rows, expected_columns)
    completed_at = utc_now_iso()
    metadata = {
        "module": spec.name, "query_id": state.get("query_id"),
        "execution_id": execution_id, "query_type": "private temporary production",
        "engine": "small", "sql_path": relative(spec.sql_path),
        "sql_sha256": sha256_file(spec.sql_path),
        "status_request_count": status_count, "result_retrieval_count": 1,
        "dimensions": [expected_rows, len(expected_columns)],
        "raw_path": relative(spec.raw_path), "raw_size_bytes": size,
        "raw_sha256": checksum, "completed_at_utc": completed_at,
    }
    write_json_atomic(spec.metadata_path, metadata)
    update_module_state(
        spec, "complete", status_request_count=status_count,
        result_retrieval_count=1, raw_file_persisted=True,
        validation_passed=True, row_count=expected_rows,
        column_count=len(expected_columns), raw_path=relative(spec.raw_path),
        raw_size_bytes=size, raw_sha256=checksum,
        metadata_path=relative(spec.metadata_path),
        validation_path=relative(spec.validation_path), completed_at_utc=completed_at,
    )
    return report | metadata


def validate_existing_module(spec: ModuleSpec) -> dict[str, Any]:
    """Re-run current local validation without any Dune access."""
    if not spec.raw_path.exists():
        raise ProtocolProductionError(f"{spec.name} raw result is absent")
    with spec.raw_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = list(reader.fieldnames or [])
    report = validate_module_rows(spec, rows, columns)
    write_json_atomic(spec.validation_path, report)
    if report["validation_passed"]:
        update_module_state(spec, "complete", validation_passed=True)
    else:
        update_module_state(
            spec, "validation_failed_preserved_raw", validation_passed=False,
            validation_failures=report["failures"], raw_file_persisted=True,
        )
    return report


def _ordered_effective_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Select one deterministic end-of-timestamp state per parameter series."""
    if rows.empty:
        return rows.copy()
    ordering = [
        "effective_time_utc", "block_number", "transaction_index",
        "transaction_hash", "source_position",
    ]
    available = [column for column in ordering if column in rows.columns]
    return rows.sort_values(
        available, kind="stable", na_position="first"
    ).drop_duplicates("effective_time_utc", keep="last")


def _asof_series(
    rows: pd.DataFrame, index: pd.DatetimeIndex, value_column: str,
) -> pd.Series:
    if rows.empty:
        return pd.Series(index=index, dtype="object")
    ordered = _ordered_effective_rows(rows)
    series = ordered.set_index("effective_time_utc")[value_column]
    union = series.index.union(index).sort_values()
    with pd.option_context("future.no_silent_downcasting", True):
        filled = series.reindex(union).ffill()
    return filled.infer_objects(copy=False).reindex(index)


def _annualise_fee(duty: pd.Series, base: pd.Series) -> pd.Series:
    factor = pd.to_numeric(duty, errors="coerce") + pd.to_numeric(base, errors="coerce")
    result = pd.Series(index=duty.index, dtype="float64")
    valid = factor > 0
    result.loc[valid] = (factor.loc[valid].map(math.log) * 31_536_000).map(math.expm1)
    return result


def reconstruct_outputs() -> dict[str, Any]:
    frames = []
    for spec in MODULES.values():
        if not spec.raw_path.exists():
            raise ProtocolProductionError(f"Missing validated {spec.name} raw result")
        state = json.loads(spec.state_path.read_text(encoding="utf-8"))
        if state.get("state") != "complete" or not state.get("validation_passed"):
            raise ProtocolProductionError(f"{spec.name} is not marked complete")
        frame = pd.read_csv(spec.raw_path, dtype={"raw_value": str, "auxiliary_raw_value": str})
        frame["state_source"] = "observed_call"
        frame["is_observed_call"] = True
        frame["evidence_reference"] = relative(spec.raw_path)
        frames.append(frame)
    documented_defaults = _clipper_documented_default_rows()
    write_dataframe_atomic(documented_defaults, CLIPPER_STOPPED_DEFAULTS_PATH)
    frames.append(documented_defaults)
    ledger = pd.concat(frames, ignore_index=True)
    ledger["effective_time_utc"] = pd.to_datetime(ledger["effective_time_utc"], utc=True)
    ledger = ledger.sort_values(
        ["effective_time_utc", "block_number", "transaction_index",
         "transaction_hash", "source_position", "module"],
        kind="stable", na_position="first",
    ).reset_index(drop=True)
    write_dataframe_atomic(ledger, LEDGER_PATH)

    interval_rows: list[dict[str, Any]] = []
    group_fields = ["module", "ilk", "parameter"]
    for key, group in ledger.groupby(group_fields, sort=True, dropna=False):
        if key[0] == "Clipper":
            subgroups = group.groupby("source_contract", sort=True)
        else:
            subgroups = [(None, group)]
        for _, subgroup in subgroups:
            subgroup = _ordered_effective_rows(subgroup).reset_index(drop=True)
            for position, row in subgroup.iterrows():
                start = max(row["effective_time_utc"], SAMPLE_START)
                end = (subgroup.iloc[position + 1]["effective_time_utc"]
                       if position + 1 < len(subgroup) else SAMPLE_END)
                if start >= SAMPLE_END or end <= SAMPLE_START:
                    continue
                interval_rows.append({
                    **{column: row[column] for column in
                       COMMON_COLUMNS + DERIVED_PROVENANCE_COLUMNS
                       if column not in {"effective_time_utc"}},
                    "effective_start_utc": start,
                    "effective_end_exclusive_utc": min(end, SAMPLE_END),
                })
    intervals = pd.DataFrame(interval_rows)
    write_dataframe_atomic(intervals, INTERVAL_PATH)

    hours = pd.date_range(SAMPLE_START, SAMPLE_END, inclusive="left", freq="h")
    panels: list[pd.DataFrame] = []
    column_map = {
        "debt_ceiling": "debt_ceiling_dai",
        "minimum_debt": "minimum_debt_dai",
        "liquidation_ratio": "liquidation_ratio",
        "oracle_adapter": "oracle_adapter",
        "effective_liquidation_spot": "effective_liquidation_spot_dai_per_collateral",
        "stability_fee_duty": "stability_fee_duty_factor",
        "liquidation_penalty": "liquidation_penalty_rate",
        "ilk_liquidation_capacity": "ilk_liquidation_capacity_dai",
        "clipper_mapping": "clipper_contract",
        "auction_price_buffer": "auction_price_buffer",
        "auction_tail": "auction_tail_seconds",
        "auction_cusp": "auction_cusp",
        "auction_keeper_fraction": "auction_keeper_fraction",
        "auction_keeper_fixed": "auction_keeper_fixed_dai",
        "auction_stopped": "auction_stopped",
    }
    global_map = {
        "global_debt_ceiling": "global_debt_ceiling_dai",
        "stability_fee_base": "stability_fee_base_factor",
        "global_liquidation_capacity": "global_liquidation_capacity_dai",
    }
    activation_times = _documented_activation_times()
    panel_value_columns = list(column_map.values()) + list(global_map.values())
    for ilk in TARGET_ILKS:
        panel = pd.DataFrame({"timestamp_utc": hours, "ilk": ilk}).set_index("timestamp_utc")
        for parameter, output in column_map.items():
            subset = ledger[(ledger["ilk"] == ilk) & (ledger["parameter"] == parameter)].copy()
            value_column = "raw_value" if parameter in {"oracle_adapter", "clipper_mapping"} else "converted_value"
            if parameter.startswith("auction_"):
                mapping_rows = ledger[(ledger["ilk"] == ilk) &
                                      (ledger["parameter"] == "clipper_mapping")].copy()
                mapping = _asof_series(mapping_rows, hours, "raw_value").astype("string").str.lower()
                result = pd.Series(index=hours, dtype="float64")
                for contract in mapping.dropna().unique():
                    contract_rows = subset[
                        subset["source_contract"].astype(str).str.lower() == contract
                    ]
                    values = _asof_series(contract_rows, hours, value_column)
                    mask = mapping.eq(contract)
                    result.loc[mask] = pd.to_numeric(values.loc[mask], errors="coerce")
                panel[output] = result
                if parameter == "auction_stopped":
                    source_result = pd.Series(index=hours, dtype="object")
                    observed_result = pd.Series(index=hours, dtype="boolean")
                    for contract in mapping.dropna().unique():
                        contract_rows = subset[
                            subset["source_contract"].astype(str).str.lower() == contract
                        ]
                        source_values = _asof_series(
                            contract_rows, hours, "state_source"
                        )
                        observed_values = _asof_series(
                            contract_rows, hours, "is_observed_call"
                        )
                        mask = mapping.eq(contract)
                        source_result.loc[mask] = source_values.loc[mask]
                        observed_result.loc[mask] = observed_values.loc[mask]
                    panel["auction_stopped_state_source"] = source_result
                    panel["auction_stopped_is_observed_call"] = observed_result
            else:
                panel[output] = _asof_series(subset, hours, value_column).values
        for parameter, output in global_map.items():
            subset = ledger[(ledger["ilk"] == "GLOBAL") & (ledger["parameter"] == parameter)]
            panel[output] = _asof_series(subset, hours, "converted_value").values
        panel["annualised_stability_fee"] = _annualise_fee(
            panel["stability_fee_duty_factor"], panel["stability_fee_base_factor"]
        )
        active_from = activation_times.get(ilk, SAMPLE_START)
        panel["ilk_active"] = panel.index >= active_from
        inactive = ~panel["ilk_active"]
        panel.loc[inactive, panel_value_columns + ["annualised_stability_fee"]] = pd.NA
        panel.loc[inactive, [
            "auction_stopped_state_source",
            "auction_stopped_is_observed_call",
        ]] = pd.NA
        panels.append(panel.reset_index())
    hourly = pd.concat(panels, ignore_index=True).sort_values(
        ["timestamp_utc", "ilk"], kind="stable"
    ).reset_index(drop=True)
    write_dataframe_atomic(hourly, HOURLY_PATH)

    failures: list[str] = []
    expected_rows = EXPECTED_HOURS * len(TARGET_ILKS)
    if len(hourly) != expected_rows:
        failures.append(f"expected {expected_rows} hourly rows, found {len(hourly)}")
    if hourly.duplicated(["timestamp_utc", "ilk"]).any():
        failures.append("duplicate ilk-hour rows")
    observed_hours = pd.DatetimeIndex(hourly["timestamp_utc"].unique()).sort_values()
    if not observed_hours.equals(hours):
        failures.append("hourly timestamp coverage differs from the requested interval")
    required_parameter_columns = panel_value_columns + ["annualised_stability_fee"]
    null_counts = {column: int(hourly[column].isna().sum()) for column in hourly.columns}
    unexpected_active_nulls: dict[str, int] = {}
    documented_pre_first_observation_nulls: dict[str, int] = {}
    unexpected_pre_activation_values: dict[str, int] = {}
    first_available: dict[str, str | None] = {}
    for ilk in TARGET_ILKS:
        active_from = activation_times.get(ilk, SAMPLE_START)
        ilk_rows = hourly[hourly["ilk"] == ilk]
        inactive = ilk_rows[ilk_rows["timestamp_utc"] < active_from]
        for column in required_parameter_columns:
            unexpected = int(inactive[column].notna().sum())
            if unexpected:
                unexpected_pre_activation_values[f"{ilk}:{column}"] = unexpected
            active = ilk_rows[ilk_rows["timestamp_utc"] >= active_from]
            available = active.loc[active[column].notna(), "timestamp_utc"]
            series_name = f"{ilk}:{column}"
            if available.empty:
                first_available[series_name] = None
                unexpected_active_nulls[series_name] = len(active)
                continue
            first_time = pd.Timestamp(available.iloc[0])
            first_available[series_name] = first_time.isoformat()
            leading_nulls = int(
                active.loc[active["timestamp_utc"] < first_time, column].isna().sum()
            )
            if leading_nulls:
                documented_pre_first_observation_nulls[series_name] = leading_nulls
            later_nulls = int(
                active.loc[active["timestamp_utc"] >= first_time, column].isna().sum()
            )
            if later_nulls:
                unexpected_active_nulls[series_name] = later_nulls
    if unexpected_pre_activation_values:
        failures.append(
            f"values exist before ilk activation: {unexpected_pre_activation_values}"
        )
    if unexpected_active_nulls:
        failures.append(f"unexpected active parameter nulls: {unexpected_active_nulls}")
    active_rows = hourly[hourly["ilk_active"]]
    wrong_stopped_provenance = active_rows[
        active_rows["auction_stopped_state_source"].ne("contract_default")
        | active_rows["auction_stopped_is_observed_call"].ne(False)
    ]
    if not wrong_stopped_provenance.empty:
        failures.append(
            "documented Clipper stopped provenance is not preserved hourly: "
            f"{len(wrong_stopped_provenance)} rows"
        )
    invalid_intervals = int(
        (pd.to_datetime(intervals["effective_end_exclusive_utc"], utc=True)
         <= pd.to_datetime(intervals["effective_start_utc"], utc=True)).sum()
    )
    if invalid_intervals:
        failures.append(f"non-positive effective intervals: {invalid_intervals}")
    interval_overlap_count = 0
    interval_groups = ["module", "ilk", "parameter", "source_contract"]
    for _, group in intervals.groupby(interval_groups, dropna=False):
        ordered = group.sort_values("effective_start_utc", kind="stable")
        starts = pd.to_datetime(ordered["effective_start_utc"], utc=True)
        ends = pd.to_datetime(ordered["effective_end_exclusive_utc"], utc=True)
        interval_overlap_count += int((starts.iloc[1:].array < ends.iloc[:-1].array).sum())
    if interval_overlap_count:
        failures.append(f"overlapping effective intervals: {interval_overlap_count}")
    numeric = hourly.select_dtypes(include="number")
    if not numeric.apply(lambda series: series.dropna().map(math.isfinite).all()).all():
        failures.append("hourly panel contains non-finite values")
    report = {
        "validation_passed": not failures,
        "failures": failures,
        "sample_start_utc": SAMPLE_START.isoformat(),
        "sample_end_exclusive_utc": SAMPLE_END.isoformat(),
        "expected_hours": EXPECTED_HOURS,
        "expected_ilk_hour_rows": expected_rows,
        "ledger_dimensions": [len(ledger), len(ledger.columns)],
        "interval_dimensions": [len(intervals), len(intervals.columns)],
        "hourly_dimensions": [len(hourly), len(hourly.columns)],
        "hourly_null_counts": null_counts,
        "unexpected_active_parameter_null_counts": unexpected_active_nulls,
        "unexpected_pre_activation_value_counts": unexpected_pre_activation_values,
        "documented_pre_first_observation_null_counts": documented_pre_first_observation_nulls,
        "parameter_first_available_utc": first_available,
        "interval_overlap_count": interval_overlap_count,
        "invalid_interval_count": invalid_intervals,
        "observed_call_ledger_rows": int(ledger["is_observed_call"].eq(True).sum()),
        "documented_default_ledger_rows": int(ledger["is_observed_call"].eq(False).sum()),
        "documented_inactive_pre_activation_nulls": {
            ilk: {
                "activation_time_utc": timestamp.isoformat(),
                "ilk_hour_count_before_activation": int(
                    ((hourly["ilk"] == ilk) & (hourly["timestamp_utc"] < timestamp)).sum()
                ),
            }
            for ilk, timestamp in activation_times.items()
        },
        "module_checksums": {key: sha256_file(spec.raw_path)
                             for key, spec in MODULES.items()},
        "ledger_sha256": sha256_file(LEDGER_PATH),
        "interval_sha256": sha256_file(INTERVAL_PATH),
        "hourly_sha256": sha256_file(HOURLY_PATH),
        "documented_defaults_sha256": sha256_file(CLIPPER_STOPPED_DEFAULTS_PATH),
        "stability_fee_formula": "((duty + base) / 1e27)^31536000 - 1; duty/base stored as divided factors and aligned by effective UTC time",
        "spot_observation_policy": "last Spot.Poke per UTC day plus latest pre-sample Poke, forward-filled for validation only",
    }
    write_json_atomic(VALIDATION_PATH, report)
    if failures:
        raise ProtocolProductionError("; ".join(failures))
    metadata = {
        "phase": "1D",
        "status": "complete",
        "target_ilks": list(TARGET_ILKS),
        "sample_start_utc": SAMPLE_START.isoformat(),
        "sample_end_exclusive_utc": SAMPLE_END.isoformat(),
        "inputs": {key: relative(spec.raw_path) for key, spec in MODULES.items()},
        "documented_default_input": relative(CLIPPER_STOPPED_DEFAULTS_PATH),
        "outputs": {
            "sparse_ledger": relative(LEDGER_PATH),
            "effective_intervals": relative(INTERVAL_PATH),
            "hourly_panel": relative(HOURLY_PATH),
            "documented_clipper_defaults": relative(CLIPPER_STOPPED_DEFAULTS_PATH),
        },
        "checksums": {
            "sparse_ledger": report["ledger_sha256"],
            "effective_intervals": report["interval_sha256"],
            "hourly_panel": report["hourly_sha256"],
            "documented_clipper_defaults": report["documented_defaults_sha256"],
        },
        "raw_integer_policy": "Exact Dune integer strings are retained in module CSVs and the sparse ledger.",
        "forward_fill_policy": "Values are carried forward only after an observed setting or a separately documented contract default; Clipper values apply only while the Dog mapping selects that contract and no values are assigned before ilk activation.",
        "clipper_stopped_default_policy": "Six zero states are derived from verified deployed source and deployment evidence, remain marked state_source=contract_default and is_observed_call=false, and are not inserted into the raw Clipper CSV.",
    }
    write_json_atomic(METADATA_PATH, metadata)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialise = subparsers.add_parser("initialise")
    initialise.add_argument("--module", choices=MODULES, required=True)
    persist = subparsers.add_parser("persist")
    persist.add_argument("--module", choices=MODULES, required=True)
    record = subparsers.add_parser("record-execution")
    record.add_argument("--module", choices=MODULES, required=True)
    record.add_argument("--query-id", type=int, required=True)
    record.add_argument("--query-url", required=True)
    record.add_argument("--execution-id", required=True)
    record.add_argument("--execution-state", required=True)
    record.add_argument("--created-at-utc", required=True)
    subparsers.add_parser("preflight-vat-recovery")
    subparsers.add_parser("recover-vat")
    retrieve = subparsers.add_parser("retrieve-module")
    retrieve.add_argument("--module", choices=("spot", "jug", "dog", "clipper"), required=True)
    validate = subparsers.add_parser("validate-existing")
    validate.add_argument("--module", choices=MODULES, required=True)
    subparsers.add_parser("persist-clipper-stopped-minimal")
    subparsers.add_parser("reconstruct")
    args = parser.parse_args()
    if args.command == "initialise":
        print(json.dumps(initialise_module(MODULES[args.module]), indent=2))
    elif args.command == "persist":
        print(json.dumps(persist_module_payload(MODULES[args.module]), indent=2))
    elif args.command == "record-execution":
        print(json.dumps(update_module_state(
            MODULES[args.module], "execution_submitted",
            query_id=args.query_id, query_url=args.query_url,
            execution_id=args.execution_id, execution_state=args.execution_state,
            created_at_utc=args.created_at_utc,
        ), indent=2))
    elif args.command == "preflight-vat-recovery":
        print(json.dumps(vat_recovery_preflight(), indent=2))
    elif args.command == "recover-vat":
        api_key = os.environ.get("DUNE_API_KEY")
        if not api_key:
            raise ProtocolProductionError("DUNE_API_KEY is not set")
        print(json.dumps(recover_vat_result(api_key), indent=2))
    elif args.command == "retrieve-module":
        api_key = os.environ.get("DUNE_API_KEY")
        if not api_key:
            raise ProtocolProductionError("DUNE_API_KEY is not set")
        print(json.dumps(retrieve_module_result(api_key, MODULES[args.module]), indent=2))
    elif args.command == "validate-existing":
        print(json.dumps(validate_existing_module(MODULES[args.module]), indent=2))
    elif args.command == "persist-clipper-stopped-minimal":
        print(json.dumps(persist_clipper_stopped_minimal_payload(), indent=2))
    else:
        print(json.dumps(reconstruct_outputs(), indent=2))


if __name__ == "__main__":
    main()
