"""Portable runtime-source ownership and historical-boundary tests."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import shutil

import pandas as pd
import pytest

from dai_sim.inputs import runtime_sources
from dai_sim.inputs.stage1 import load_portable_stage1_residual_source
from dai_sim.inputs.submission_portability import (
    MAINTENANCE_HISTORY_PATH,
    canonical_sha256,
    load_reconstruction_contracts,
    validate_portability_bundle,
)
from dai_sim.inputs.multicollateral import (
    load_final_collateral_registry,
    load_integrated_multicollateral_profile,
)
from dai_sim.validation import final_validation
from tests.support import REPOSITORY_ROOT
from workflows.verification.verify_external_artifacts import (
    verify_external_artifacts,
)


LEGACY_ROOT = (
    REPOSITORY_ROOT
    / "data/provenance/maintenance/runtime_portability/legacy_sources"
)
PROCESSED_SOURCES = {
    "data/protocol/processed/hourly_protocol_parameters.csv": (
        "8190f1aa9f63a6ebd41ef5eb38ee33b64523631161199e37224ce859cb71f195"
    ),
    "data/market/processed/dune_hourly_market_prices_processed.csv": (
        "43f8a23aff2ec995a4e1ad5e8fc66f4b5223e8dcc9c8a36bd272d733ae1d4e25"
    ),
    "data/market/processed/combined/hourly_market_gas_panel.csv": (
        "86ed2ac5a5d364cc57e8b41e137ef369a0fce7a393d386b4b38fc1ebd1be0545"
    ),
}


def _portable_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    mapping = runtime_sources.load_runtime_map()
    map_path = tmp_path / "config/submission/runtime_input_map.yaml"
    map_path.parent.mkdir(parents=True)
    shutil.copy2(runtime_sources.RUNTIME_MAP_PATH, map_path)
    for entry in mapping["sources"].values():
        for key in ("primary_runtime_owner", "supporting_runtime_owner"):
            owner = entry.get(key)
            if owner is None:
                continue
            source = REPOSITORY_ROOT / owner["path"]
            destination = tmp_path / owner["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    monkeypatch.setattr(runtime_sources, "REPOSITORY_ROOT", tmp_path)
    return map_path


def test_legacy_source_snapshots_are_exact_and_non_importable() -> None:
    expected = {
        "multicollateral.py.txt": (
            "4e215ff709d00b02fdddaad05e8e3738efe0be5a0b5dd022cfa93039323ef7a9"
        ),
        "final_validation.py.txt": (
            "4cb99d79d7d768629eb1f51861f055e246385b1035e5714dff64632a088bbb30"
        ),
    }
    for name, checksum in expected.items():
        path = LEGACY_ROOT / name
        assert path.suffix == ".txt"
        assert runtime_sources.sha256_file(path) == checksum


def test_runtime_map_resolves_three_verified_owners() -> None:
    mapping = runtime_sources.load_runtime_map()
    assert tuple(mapping["sources"]) == tuple(PROCESSED_SOURCES)
    resolved = {
        source: runtime_sources.resolve_runtime_source(source, checksum)
        for source, checksum in PROCESSED_SOURCES.items()
    }
    assert resolved[
        "data/protocol/processed/hourly_protocol_parameters.csv"
    ].runtime_owner_type == "frozen_collateral_registry"
    assert resolved[
        "data/market/processed/dune_hourly_market_prices_processed.csv"
    ].runtime_owner_type == "existing_multicollateral_market_block_pool"
    assert resolved[
        "data/market/processed/combined/hourly_market_gas_panel.csv"
    ].runtime_owner_type == "exact_held_out_market_gas_derivative"


def test_frozen_runtime_objects_resolve_from_portable_owners() -> None:
    collateral = load_final_collateral_registry()
    profile = load_integrated_multicollateral_profile()
    ftx = final_validation._historical_window("ftx")
    svb = final_validation._historical_window("usdc_svb")
    assert collateral.family_order == ("ETH", "WBTC", "STABLE")
    assert profile.identifier == "empirical_integrated_multicollateral"
    assert len(ftx) == 480
    assert len(svb) == 336
    assert tuple(ftx.columns) == (
        "timestamp_utc",
        "eth_log_return",
        "wbtc_log_return",
        "dai_price_usd",
        "usdc_price_usd",
        "usdc_log_return",
        "median_effective_gas_price_gwei",
    )


def test_processed_sources_are_optional_for_runtime_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    map_path = _portable_tree(tmp_path, monkeypatch)
    for source, checksum in PROCESSED_SOURCES.items():
        resolution = runtime_sources.resolve_runtime_source(
            source, checksum, map_path=map_path
        )
        assert resolution.optional_full_source_present is False
        assert resolution.runtime_path.is_file()


def test_corrupt_compact_derivative_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    map_path = _portable_tree(tmp_path, monkeypatch)
    derivative = (
        tmp_path
        / "data/model_inputs/validation/final_validation_market_gas_paths.csv"
    )
    derivative.write_bytes(derivative.read_bytes() + b"corrupt\n")
    source = "data/market/processed/combined/hourly_market_gas_panel.csv"
    with pytest.raises(ValueError, match="runtime owner checksum differs"):
        runtime_sources.resolve_runtime_source(
            source, PROCESSED_SOURCES[source], map_path=map_path
        )


def test_corrupt_runtime_map_fails(tmp_path: Path) -> None:
    path = tmp_path / "runtime_input_map.yaml"
    text = runtime_sources.RUNTIME_MAP_PATH.read_text(encoding="utf-8")
    path.write_text(
        text.replace("portable_runtime_resolution_v2", "unregistered"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="classification differs"):
        runtime_sources.load_runtime_map(path)


def test_corrupt_optional_full_source_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    map_path = _portable_tree(tmp_path, monkeypatch)
    source = "data/market/processed/combined/hourly_market_gas_panel.csv"
    full = tmp_path / source
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text("not the registered source\n", encoding="utf-8")
    with pytest.raises(ValueError, match="provenance source checksum differs"):
        runtime_sources.resolve_runtime_source(
            source, PROCESSED_SOURCES[source], map_path=map_path
        )


def test_full_and_compact_values_are_exact_when_source_is_available() -> None:
    source = REPOSITORY_ROOT / (
        "data/market/processed/combined/hourly_market_gas_panel.csv"
    )
    derivative = REPOSITORY_ROOT / (
        "data/model_inputs/validation/final_validation_market_gas_paths.csv"
    )
    if not source.is_file():
        assert runtime_sources.sha256_file(derivative) == (
            "e2f6d8206b0dd040ddbf4ee302b75c575ffcec412c920db6ddd2c1f04cda1ade"
        )
        return
    from workflows.inputs.build_runtime_derivatives import validate_equivalence

    report = validate_equivalence(source, derivative)
    assert report["scientific_value_differences"] == 0
    assert report["maximum_numeric_difference"] == 0.0


def test_portable_identity_is_distinct_from_historical_identities() -> None:
    identity = runtime_sources.portable_runtime_identity()
    assert len(identity) == 64
    assert identity not in {
        "a9d7c3fa5dc5da9bcf61314a57501ea5a8be506e305eee6f45afaae3131600bb",
        "1bc40998534dd3842a229c701743494147d24832d956622411afba7863d3c295",
        "a5e281a810892454539f0528c30536696d01c664bbd6cceda17584b88d5f3ed2",
    }
    payload = runtime_sources.portable_runtime_identity_payload()
    assert payload["historical_scientific_identities_preserved"] is True
    assert payload["scientific_value_changes"] == 0
    assert payload["network_calls"] == 0


def test_runtime_map_has_no_network_fallback() -> None:
    mapping = runtime_sources.load_runtime_map()
    assert mapping["network_fallback"] is False
    source = Path(runtime_sources.__file__).read_text(encoding="utf-8")
    assert "requests" not in source
    assert "urlopen" not in source


def test_runtime_derivative_schema_and_order_are_exact() -> None:
    path = (
        REPOSITORY_ROOT
        / "data/model_inputs/validation/final_validation_market_gas_paths.csv"
    )
    frame = pd.read_csv(path)
    assert len(frame) == 816
    assert frame["timestamp_utc"].is_monotonic_increasing
    assert not frame["timestamp_utc"].duplicated().any()


def test_stage1_portable_derivative_preserves_exact_registered_process() -> None:
    source, manifest = load_portable_stage1_residual_source()
    assert len(source.centred_residuals) == 28_859
    assert len(source.block_indices) == 25_017
    assert manifest["centred_residual_sequence_sha256"] == (
        "3fa2319cee9e1749405c0dc477e0f11ef9c31dd83c371b619bd33eda23c37c30"
    )
    assert manifest["block_index_specification_sha256"] == (
        "6f55b51acfc1da23836b3d847153bd4f68e4a38fc33fd967e9d3b795737bf28c"
    )
    assert float.fromhex(manifest["below_peg_response_float64_hex"]) == pytest.approx(
        0.19938097532295382
    )
    assert float.fromhex(manifest["above_peg_response_float64_hex"]) == pytest.approx(
        0.10513116022712267
    )


def test_historical_reconstruction_contracts_preserve_ten_studies() -> None:
    registry = load_reconstruction_contracts()
    studies = {item["study_identifier"]: item for item in registry["studies"]}
    assert set(studies) == {
        "unbounded_eth_recovery",
        "constrained_eth_recovery",
        "experiment_a",
        "experiment_b",
        "experiment_c",
        "experiment_d",
        "experiment_e",
        "selected_robustness",
        "final_validation",
        "h4_synthesis",
    }
    assert studies["experiment_a"]["scientific_identity"] == (
        "a9d7c3fa5dc5da9bcf61314a57501ea5a8be506e305eee6f45afaae3131600bb"
    )
    assert studies["final_validation"]["scientific_identity"] == (
        "a5e281a810892454539f0528c30536696d01c664bbd6cceda17584b88d5f3ed2"
    )
    assert all(
        item["reconstruction_status"] == "external_artifacts_optional"
        for item in studies.values()
    )


def test_second_portability_bundle_is_scientifically_non_operational() -> None:
    result = validate_portability_bundle()
    assert result["status"] == "passed"
    assert result["study_count"] == 10
    assert result["readiness"] == "ready_with_submission_exclusions"
    assert result["portable_submission_identity"] != (
        "bbb89292dcec748261ec8cf8ca512f707316336eecb4b81252d80f0deba52f34"
    )


def test_maintenance_relocation_preserves_historical_verifier_provenance() -> None:
    record = json.loads(MAINTENANCE_HISTORY_PATH.read_text(encoding="utf-8"))
    verifier = next(
        item
        for item in record["relocations"]
        if item["classification"] == "user_verification"
    )
    assert verifier["historical_path"] == (
        "workflows/maintenance/verify_external_scientific_artifacts.py"
    )
    assert verifier["current_path"] == (
        "workflows/verification/verify_external_artifacts.py"
    )
    assert verifier["historical_sha256"] == record[
        "historical_test_support_sources"
    ]["external_verifier"]["sha256"]
    assert verifier["current_sha256"] == runtime_sources.sha256_file(
        REPOSITORY_ROOT / verifier["current_path"]
    )
    assert verifier["historical_sha256"] != verifier["current_sha256"]
    assert not (REPOSITORY_ROOT / "workflows/maintenance").exists()


def test_external_verifier_uses_a_temporary_real_schema_fixture(tmp_path: Path) -> None:
    checkpoint_root = tmp_path / "archive/checkpoints"
    checkpoint_root.mkdir(parents=True)
    for replication in range(2):
        payload = {
            "schema_version": 1,
            "experiment_identity": "fixture-identity",
            "replication": replication,
            "complete": True,
        }
        (checkpoint_root / f"replication_{replication:03d}.json").write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    content = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(checkpoint_root.glob("replication_*.json"))
    }
    compact = {
        "path": (
            "data/provenance/experiments/final/idiosyncratic_diversification/"
            "idiosyncratic_diversification_specification.json"
        ),
        "sha256": (
            "e6da0af839c53ddffb6eeaea596174d26499afeb55ca0d1910be49c679cd740d"
        ),
    }
    study = {
        "study_identifier": "fixture",
        "scientific_identity": "fixture-identity",
        "specification": compact,
        "seed_registry_sha256": "fixture",
        "expected_cell_count": 1,
        "expected_replication_count": 2,
        "historical_checkpoint_count": 2,
        "checkpoint_content_manifest": {
            "status": "recorded_content_map",
            "algorithm": "filename_sha256_map",
            "sha256": canonical_sha256(content),
        },
        "compact_evidence": [compact, compact, compact],
        "decision": compact,
        "simulation_core_identity": "fixture-core",
        "external_checkpoint_root": "archive/checkpoints",
        "reconstruction_status": "external_artifacts_optional",
        "ordinary_submission_test_owner": "temporary_fixture",
    }
    contract = {
        "schema_version": 1,
        "classification": "portable_submission_evidence_v1",
        "registry_content_sha256": "",
        "studies": [study],
    }
    identity_payload = dict(contract)
    identity_payload.pop("registry_content_sha256")
    contract["registry_content_sha256"] = canonical_sha256(identity_payload)
    contract_path = tmp_path / "contracts.json"
    contract_path.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = verify_external_artifacts(
        tmp_path,
        contracts_path=contract_path,
    )
    assert result["status"] == "passed"
    assert result["studies"] == [
        {
            "study_identifier": "fixture",
            "checkpoint_count": 2,
            "content_verification": "recorded_content_map",
        }
    ]


def test_external_verifier_rejects_an_incomplete_archive(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="artefact root is absent"):
        verify_external_artifacts(tmp_path / "absent")


def test_external_verifier_has_no_network_or_home_fallback() -> None:
    source = (
        REPOSITORY_ROOT
        / "workflows/verification/verify_external_artifacts.py"
    ).read_text(encoding="utf-8")
    for blocked in ("requests", "urlopen", "/Users/", "Path.home"):
        assert blocked not in source
