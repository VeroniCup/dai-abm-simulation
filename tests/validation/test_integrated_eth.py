"""Substantive tests for the opt-in integrated empirical ETH profile."""

from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from dai_sim.calibration.event_simulation import load_stage1_owners
from dai_sim.validation.integrated_eth import (
    COMPACT_FILENAMES,
    DYNAMIC_REPLICATION_COUNT,
    EVIDENCE_DIR,
    INITIALISATION_COUNT,
    InputValidationResult,
    DynamicValidationResult,
    VALIDATION_MANIFEST,
    VALIDATION_SEMANTIC_OWNER,
    _dynamic_replication,
    _manifest_payload,
    _normalised_initial_state,
    _overall_classification,
    _reference_rows,
    controlled_binding_smoke,
    preregistration_payload,
    seed_registry_checksum,
    validate_compact_evidence,
)
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file
from dai_sim.inputs.integrated_profile import (
    DYNAMIC_HOURS,
    EXPECTED_INPUT_CHECKSUMS,
    EXPECTED_KEEPER_CONFIGURATION_SHA256,
    EXPECTED_KEEPER_REGISTRY_SHA256,
    EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
    EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
    EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
    EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
    PROFILE_IDENTIFIER,
    SHARED_KEEPER_CAPACITY,
    TOTAL_DEBT_DAI,
    VAULT_COUNT,
    resolve_integrated_empirical_eth_profile,
)
from dai_sim.inputs.liquidations import (
    LiquidationDemandProcess,
    load_liquidation_arrival_pool,
)
from dai_sim.inputs.market import load_market_gas_pool, sample_market_gas_blocks


EXPECTED_EXISTING_PROFILE_CHECKSUMS = {
    "config/profiles/legacy.yaml": (
        "6de53071749fc504865ef760488003ab4733b58e8a6ce692144ca8e74ab9284a"
    ),
    "config/profiles/empirical.yaml": (
        "31bcc1f038311e2de2355114adbcc599f257105fe5bef3a0181e7b0e95b8f6fc"
    ),
    "config/profiles/empirical_stress.yaml": (
        "9c6ca37a2e8502802ab433cc10bf6a0caec47434ad05ec9502cb2b95c61a443a"
    ),
}


def test_profile_resolves_exact_opt_in_semantics() -> None:
    profile = resolve_integrated_empirical_eth_profile()
    simulation = profile.bundle.base_bundle.simulation_config
    liquidation = profile.bundle.base_bundle.liquidation_config

    assert profile.identifier == PROFILE_IDENTIFIER
    assert simulation.n_vaults == VAULT_COUNT
    assert simulation.n_steps == DYNAMIC_HOURS
    assert simulation.collateral_portfolio is not None
    assert simulation.collateral_portfolio.collateral_names == ("ETH",)
    assert simulation.collateral_portfolio.target_debt_shares == {"ETH": 1.0}
    assert profile.bundle.initialisation.mode == "empirical_joint"
    assert profile.market.mode == "empirical_block_bootstrap"
    assert profile.gas.mode == "empirical_components"
    assert profile.liquidation_demand.mode == "empirical_hurdle_count"
    assert profile.liquidation_demand.sequence_mode == "none"
    assert liquidation.max_liquidations_per_step == SHARED_KEEPER_CAPACITY
    assert liquidation.max_close_factor == 1.0
    assert profile.keeper.capacity_profile_id == "shared_keeper_capacity_central"
    assert profile.keeper.hurdle_profile_id == "direct_cost_only"
    assert profile.keeper.risk_cost_rate == 0.0
    assert profile.confidence.scenario.identifier == "stage1_only"
    assert profile.confidence.persistent_config is None
    assert profile.confidence.panic_response == 0.0
    assert profile.oracle_status == "transparent_baseline_not_calibrated"
    assert profile.runtime_adopted is False


def test_all_protected_input_and_keeper_checksums() -> None:
    profile = resolve_integrated_empirical_eth_profile()
    assert profile.input_checksums == EXPECTED_INPUT_CHECKSUMS
    assert (
        sha256_file(REPOSITORY_ROOT / "config/sensitivities/keeper_execution.yaml")
        == EXPECTED_KEEPER_CONFIGURATION_SHA256
    )
    assert (
        sha256_file(
            REPOSITORY_ROOT
            / "data/provenance/calibration/keeper/keeper_execution_registry.csv"
        )
        == EXPECTED_KEEPER_REGISTRY_SHA256
    )


def test_vault_owner_is_joint_normalised_and_deterministic() -> None:
    profile = resolve_integrated_empirical_eth_profile()
    first_vaults, first_rows, first_checksum = _normalised_initial_state(
        profile, seed=1984
    )
    second_vaults, second_rows, second_checksum = _normalised_initial_state(
        profile, seed=1984
    )

    assert len(first_vaults) == VAULT_COUNT
    assert math.isclose(
        sum(vault.debt_dai for vault in first_vaults),
        TOTAL_DEBT_DAI,
        abs_tol=1e-6,
    )
    assert all(vault.collateral_type == "ETH" for vault in first_vaults)
    assert all(vault.debt_dai > 0 for vault in first_vaults)
    assert all(vault.collateral_amount > 0 for vault in first_vaults)
    assert first_checksum == second_checksum
    pd.testing.assert_frame_equal(first_rows, second_rows)
    assert [vault.debt_dai for vault in first_vaults] == [
        vault.debt_dai for vault in second_vaults
    ]
    assert first_rows[["debt_dai", "collateral_ratio"]].drop_duplicates().shape[0] > 1


def test_reference_band_classification_is_explicit() -> None:
    integrated = pd.DataFrame({"metric": [2.0, 2.1, 1.9]})
    reference = pd.DataFrame({"metric": [1.0, 2.0, 3.0, 2.0]})
    row = _reference_rows("test", integrated, reference, "a" * 64)[0]
    assert row["status"] == "inside"


def test_market_gas_owner_keeps_alignment_and_training_pool() -> None:
    profile = resolve_integrated_empirical_eth_profile()
    pool = load_market_gas_pool(profile.market.pool_path, profile.market.pool_sha256)
    first, first_provenance = sample_market_gas_blocks(
        pool,
        horizon=720,
        block_length_hours=profile.market.block_length_hours,
        seed=123,
        pool_label=profile.market.pool_label,
    )
    second, second_provenance = sample_market_gas_blocks(
        pool,
        horizon=720,
        block_length_hours=profile.market.block_length_hours,
        seed=123,
        pool_label=profile.market.pool_label,
    )
    assert len(first) == 720
    assert first["is_calibration"].astype(bool).all()
    assert not first["is_withheld_ftx"].astype(bool).any()
    assert first["timestamp_utc"].notna().all()
    assert first_provenance["block_length_hours"] == 168
    assert first_provenance == second_provenance
    pd.testing.assert_frame_equal(first, second)


def test_arrival_owner_samples_before_capacity_and_truncates_inventory() -> None:
    profile = resolve_integrated_empirical_eth_profile()
    process = LiquidationDemandProcess(
        replace(profile.liquidation_demand, seed=77)
    )
    decisions = [
        process.sample_step(
            step=step,
            liquidatable_inventory=3,
            keeper_capacity=2,
        )
        for step in range(200)
    ]
    assert any(decision.raw_positive_count_draw > 3 for decision in decisions)
    assert all(decision.bounded_demand <= 3 for decision in decisions)
    assert all(decision.attempt_budget <= 2 for decision in decisions)
    assert any(
        decision.raw_positive_count_draw != decision.attempt_budget
        for decision in decisions
    )


def test_shared_capacity_controlled_smoke_binds_once_system_wide() -> None:
    smoke = controlled_binding_smoke(resolve_integrated_empirical_eth_profile())
    assert smoke["passed"] is True
    assert smoke["maximum_unsafe_inventory"] > 26
    assert smoke["maximum_attempts"] == 26
    assert smoke["capacity_rejected_opportunities"] > 0
    assert smoke["unresolved_inventory_carried_forward"] is True
    assert smoke["duplicate_execution_detected"] is False
    assert smoke["substantive_recovery_experiment"] is False


def test_stage1_and_residual_owners_are_exact_and_stage1_only() -> None:
    _, _, stage1 = load_stage1_owners()
    profile = resolve_integrated_empirical_eth_profile()
    assert round(stage1["below_peg_response"], 6) == EXPECTED_STAGE1_BELOW_PEG_RESPONSE
    assert round(stage1["above_peg_response"], 6) == EXPECTED_STAGE1_ABOVE_PEG_RESPONSE
    assert stage1["residual_sequence_sha256"] == EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256
    assert stage1["block_specification_sha256"] == EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256
    assert profile.confidence.scenario.identifier == "stage1_only"
    assert profile.confidence.persistent_config is None
    assert profile.confidence.panic_response == 0.0


def test_one_integrated_replication_has_valid_accounting_and_metadata() -> None:
    profile = resolve_integrated_empirical_eth_profile()
    market_pool = load_market_gas_pool(
        profile.market.pool_path,
        profile.market.pool_sha256,
    )
    _, _, stage1 = load_stage1_owners()
    result = _dynamic_replication(
        profile,
        replication=0,
        stage1=stage1,
        market_pool=market_pool,
    )

    assert result["numerical_valid"] is True
    assert result["duplicate_closure_detected"] is False
    assert result["maximum_attempts_one_hour"] <= SHARED_KEEPER_CAPACITY
    assert result["maximum_unsafe_inventory"] >= 0
    assert result["maximum_unresolved_tab"] >= 0.0
    assert result["maximum_active_bad_debt"] >= 0.0
    assert abs(result["debt_conservation_error"]) <= 1e-5
    assert abs(result["collateral_conservation_error"]) <= 1e-5
    assert result["capacity_profile"] == "shared_keeper_capacity_central"
    assert result["hurdle_profile"] == "direct_cost_only"
    assert result["oracle_status"] == "transparent_baseline_not_calibrated"
    assert len(result["vault_checksum"]) == 64
    assert len(result["market_block_identity"]) == 64
    assert len(result["gas_block_identity"]) == 64
    assert len(result["arrival_identity"]) == 64


def test_preregistration_is_result_blind_and_uses_dedicated_seeds() -> None:
    payload = preregistration_payload(resolve_integrated_empirical_eth_profile())
    assert payload["result_fields_excluded"] is True
    assert payload["profile_classification_excluded"] is True
    assert payload["future_recovery_results_excluded"] is True
    assert payload["seed_registry"]["registry_id"].startswith(
        "integrated-empirical-eth-validation"
    )
    assert payload["seed_registry"]["calibration_registry_b_reused"] is False
    assert payload["seed_registry"]["final_validation_seeds_reused"] is False
    assert len(seed_registry_checksum()) == 64


def _classification_fixture(
    input_classification: str,
    output_classification: str,
    *,
    numerical_validity_count: int = DYNAMIC_REPLICATION_COUNT,
    smoke_passed: bool = True,
) -> tuple[InputValidationResult, DynamicValidationResult]:
    inputs = InputValidationResult(
        rows=pd.DataFrame(),
        vault_draws=pd.DataFrame(index=range(INITIALISATION_COUNT)),
        market_gas_draws=pd.DataFrame(),
        arrival_draws=pd.DataFrame(),
        component_inside_shares={},
        classification=input_classification,
        no_fallback=True,
    )
    dynamic = DynamicValidationResult(
        replications=pd.DataFrame(),
        summary=pd.DataFrame(),
        capacity_summary=pd.DataFrame(),
        smoke={"passed": smoke_passed},
        output_classification=output_classification,
        numerical_validity_count=numerical_validity_count,
    )
    return inputs, dynamic


@pytest.mark.parametrize(
    ("input_classification", "output_classification", "expected"),
    [
        (
            "integrated_empirical_eth_inputs_valid",
            "integrated_outputs_broadly_compatible",
            "integrated_empirical_eth_profile_ready",
        ),
        (
            "integrated_empirical_eth_inputs_valid",
            "integrated_outputs_partially_compatible",
            "integrated_empirical_eth_profile_ready_with_caveats",
        ),
        (
            "integrated_empirical_eth_inputs_blocked",
            "integrated_outputs_partially_compatible",
            "integrated_empirical_eth_profile_blocked",
        ),
        (
            "integrated_empirical_eth_inputs_invalid",
            "integrated_outputs_partially_compatible",
            "integrated_empirical_eth_profile_invalid",
        ),
    ],
)
def test_classification_hierarchy(
    input_classification: str,
    output_classification: str,
    expected: str,
) -> None:
    assert (
        _overall_classification(
            *_classification_fixture(input_classification, output_classification)
        )
        == expected
    )


def test_numerical_or_shared_capacity_failure_is_invalid() -> None:
    inputs, dynamic = _classification_fixture(
        "integrated_empirical_eth_inputs_valid",
        "integrated_outputs_partially_compatible",
        numerical_validity_count=DYNAMIC_REPLICATION_COUNT - 1,
    )
    assert _overall_classification(inputs, dynamic).endswith("_invalid")
    inputs, dynamic = _classification_fixture(
        "integrated_empirical_eth_inputs_valid",
        "integrated_outputs_partially_compatible",
        smoke_passed=False,
    )
    assert _overall_classification(inputs, dynamic).endswith("_invalid")


def test_existing_profiles_remain_byte_identical() -> None:
    for relative_path, expected in EXPECTED_EXISTING_PROFILE_CHECKSUMS.items():
        assert sha256_file(REPOSITORY_ROOT / relative_path) == expected


def test_compact_evidence_is_complete_and_non_adopted() -> None:
    assert all((EVIDENCE_DIR / name).exists() for name in COMPACT_FILENAMES)
    result = validate_compact_evidence()
    assert result["manifest_entry_count"] == len(COMPACT_FILENAMES)
    assert result["deterministic_reconstruction"] is True
    assert result["runtime_adopted"] is False

    decision = json.loads(
        (EVIDENCE_DIR / "integrated_empirical_eth_decision.json").read_text()
    )
    reproducibility = json.loads(
        (
            EVIDENCE_DIR / "integrated_empirical_eth_reproducibility.json"
        ).read_text()
    )
    assert decision["no_parameter_tuning"] is True
    assert decision["no_production_adoption"] is True
    assert reproducibility["final_validation_data_used"] is False
    assert reproducibility["usdc_svb_used"] is False
    assert reproducibility["recovery_matrix_run"] is False
    assert reproducibility["multi_collateral_execution"] is False

    dynamic = pd.read_csv(
        EVIDENCE_DIR / "integrated_empirical_eth_dynamic_summary.csv"
    )
    capacity = pd.read_csv(
        EVIDENCE_DIR / "integrated_empirical_eth_capacity_summary.csv"
    )
    assert float(dynamic.loc[
        dynamic["metric"].eq("cumulative_attempt_record_overcount"), "maximum"
    ].iloc[0]) == 0.0
    assert float(capacity.loc[
        capacity["metric"].eq("generic_audit_attempt_record_overcount"), "value"
    ].iloc[0]) == 0.0


def test_manifest_rerun_preserves_other_semantic_owners(tmp_path: Path) -> None:
    evidence_hashes_before = {
        name: sha256_file(EVIDENCE_DIR / name) for name in COMPACT_FILENAMES
    }
    manifest = json.loads(VALIDATION_MANIFEST.read_text(encoding="utf-8"))
    shared_entry_count = len(manifest["entries"])
    foreign_path = "PROJECT_STATUS.md"
    foreign_entry = {
        "path": foreign_path,
        "sha256": sha256_file(REPOSITORY_ROOT / foreign_path),
        "bytes": (REPOSITORY_ROOT / foreign_path).stat().st_size,
        "semantic_owner": "another_validation_owner",
        "runtime_input": False,
    }
    manifest["entries"].append(foreign_entry)
    manifest["entry_count"] = len(manifest["entries"])
    temporary_manifest = tmp_path / "manifest.json"
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    merged = _manifest_payload(
        EVIDENCE_DIR,
        manifest_path=temporary_manifest,
    )
    temporary_manifest.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rerun = _manifest_payload(
        EVIDENCE_DIR,
        manifest_path=temporary_manifest,
    )

    assert rerun == merged
    assert foreign_entry in merged["entries"]
    assert merged["entry_count"] == shared_entry_count + 1
    assert len({entry["path"] for entry in merged["entries"]}) == len(
        merged["entries"]
    )
    assert [
        entry["path"] for entry in merged["entries"]
    ] == sorted(entry["path"] for entry in merged["entries"])
    assert sum(
        entry["semantic_owner"] == VALIDATION_SEMANTIC_OWNER
        for entry in merged["entries"]
    ) == len(COMPACT_FILENAMES)
    assert {
        name: sha256_file(EVIDENCE_DIR / name) for name in COMPACT_FILENAMES
    } == evidence_hashes_before


def test_compact_validator_accepts_a_shared_manifest(tmp_path: Path) -> None:
    manifest = json.loads(VALIDATION_MANIFEST.read_text(encoding="utf-8"))
    shared_entry_count = len(manifest["entries"])
    foreign_path = "PROJECT_STATUS.md"
    manifest["entries"].append(
        {
            "path": foreign_path,
            "sha256": sha256_file(REPOSITORY_ROOT / foreign_path),
            "bytes": (REPOSITORY_ROOT / foreign_path).stat().st_size,
            "semantic_owner": "another_validation_owner",
            "runtime_input": False,
        }
    )
    manifest["entry_count"] = len(manifest["entries"])
    temporary_manifest = tmp_path / "manifest.json"
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = validate_compact_evidence(manifest_path=temporary_manifest)

    assert result["manifest_entry_count"] == len(COMPACT_FILENAMES)
    assert result["validation_manifest_total_entry_count"] == (
        shared_entry_count + 1
    )


def test_multicollateral_compact_evidence_is_explicitly_trackable() -> None:
    compact_names = (
        "multicollateral_integration_specification.json",
        "final_collateral_registry.csv",
        "final_protocol_parameters.csv",
        "final_portfolio_registry.csv",
        "final_shock_registry.csv",
        "multicollateral_initialisation_validation.csv",
        "multicollateral_shared_capacity_validation.csv",
        "multicollateral_dynamic_validation.csv",
        "multicollateral_integration_decision.json",
        "multicollateral_integration_reproducibility.json",
        "multicollateral_integration_benchmark.json",
    )
    for name in compact_names:
        path = f"data/provenance/validation/multicollateral_integration/{name}"
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=REPOSITORY_ROOT,
            check=False,
        )
        assert result.returncode != 0, path

    ignored_paths = (
        (
            "data/provenance/validation/multicollateral_integration/"
            "replication_level_diagnostics.csv"
        ),
        (
            "outputs/diagnostics/validation/multicollateral_integration/"
            "replication_level_diagnostics.csv"
        ),
    )
    for path in ignored_paths:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=REPOSITORY_ROOT,
            check=False,
        )
        assert result.returncode == 0, path
