"""Structural gates for domain-owned workflow commands."""

from __future__ import annotations

import ast
from pathlib import Path

from dai_sim.common.archive_boundary import is_manifest_filtered_bundle

from tests.support import REPOSITORY_ROOT as ROOT

WORKFLOW_MAPPING = {
    "acquire_dune_hourly_gas.py": "gas/acquire.py",
    "acquire_dune_liquidations.py": "liquidations/acquire.py",
    "acquire_dune_market_prices.py": "market/acquire.py",
    "acquire_dune_protocol_parameter_history.py": "protocol/acquire.py",
    "acquire_dune_vaults.py": "vaults/acquire.py",
    "acquire_phase1e_b_representative_vaults.py": ("vaults/acquire_representative.py"),
    "build_liquidation_arrival_runtime_pools.py": "liquidations/build_inputs.py",
    "build_market_gas_runtime_pools.py": "market/build_inputs.py",
    "build_vault_initialisation_pools.py": "vaults/build_inputs.py",
    "process_dune_hourly_gas.py": "gas/process.py",
    "process_dune_market_prices.py": "market/process.py",
    "run_parameter_adoption_review.py": "calibration/adoption.py",
    "run_phase2a_candidate_review.py": "calibration/validate.py",
    "run_phase2a_parameter_estimation.py": ("calibration/market_gas_protocol.py"),
    "run_phase2b_vault_estimation.py": "calibration/vaults.py",
    "run_phase2c_liquidation_estimation.py": "calibration/liquidations.py",
    "run_tranche_b_initialisation_diagnostics.py": "inputs/validate_vaults.py",
    "run_tranche_c_environment_diagnostics.py": ("inputs/validate_environment.py"),
    "run_tranche_d_liquidation_diagnostics.py": ("inputs/validate_liquidations.py"),
    "validate_dune_market_prices.py": "market/validate.py",
}

POST_RESTRUCTURING_WORKFLOWS = {
    "calibration/keeper_execution.py",
    "calibration/oracle_delay.py",
    "experiments/mechanism/constrained_eth_recovery.py",
    "experiments/mechanism/eth_recovery.py",
    "experiments/final/correlated_stress.py",
    "experiments/final/idiosyncratic_diversification.py",
    "experiments/final/stable_collateral_tradeoff.py",
    "experiments/final/shared_keeper_capacity.py",
    "experiments/final/oracle_delay.py",
    "experiments/final/recovery_behaviour_synthesis.py",
    "experiments/final/selected_robustness.py",
    "inputs/validate_integrated_eth.py",
    "inputs/validate_multicollateral.py",
    "inputs/build_runtime_derivatives.py",
    "inputs/build_stage1_residual_source.py",
    "verification/verify_external_artifacts.py",
    "market/process_historical_evidence.py",
    "validation/final_validation.py",
}
EXPECTED_CATEGORIES = {
    "calibration",
    "experiments",
    "gas",
    "inputs",
    "liquidations",
    "market",
    "protocol",
    "validation",
    "vaults",
    "verification",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_exactly_20_unique_authoritative_workflows_exist() -> None:
    assert len(WORKFLOW_MAPPING) == 20
    assert len(set(WORKFLOW_MAPPING.values())) == 20
    assert not (ROOT / "scripts").exists()
    for target in WORKFLOW_MAPPING.values():
        assert (ROOT / "workflows" / target).is_file()
    actual = {
        path.relative_to(ROOT / "workflows").as_posix()
        for path in (ROOT / "workflows").rglob("*.py")
        if not path.name.startswith("_")
    }
    assert set(WORKFLOW_MAPPING.values()) | POST_RESTRUCTURING_WORKFLOWS == actual


def test_protocol_and_vault_workflow_responsibilities_remain_distinct() -> None:
    expected = {
        "protocol/acquire.py",
        "vaults/acquire.py",
        "vaults/acquire_representative.py",
    }
    assert expected <= set(WORKFLOW_MAPPING.values())


def test_only_real_populated_categories_exist() -> None:
    workflow_root = ROOT / "workflows"
    categories = {
        path.name
        for path in workflow_root.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    }
    assert categories == EXPECTED_CATEGORIES
    assert (workflow_root / "experiments/mechanism/eth_recovery.py").is_file()
    for category in categories:
        assert any((workflow_root / category).rglob("*.py"))


def test_development_packaging_is_outside_workflow_discovery() -> None:
    assert not (ROOT / "workflows/maintenance").exists()
    builder = ROOT / "tools/packaging/build_code_bundle.py"
    if is_manifest_filtered_bundle(ROOT):
        assert not builder.exists()
    else:
        assert builder.is_file()
    assert "tools" not in EXPECTED_CATEGORIES


def test_authoritative_workflows_use_no_old_wrappers_or_flat_shims() -> None:
    forbidden_imports = {
        "confidence",
        "dai_market",
        "empirical_config",
        "environment_inputs",
        "experiments",
        "gas_process",
        "liquidation",
        "liquidation_demand",
        "market_bootstrap",
        "price_process",
        "simulation",
        "vault",
        "vault_initialisation",
    }
    for relative in WORKFLOW_MAPPING.values():
        path = ROOT / "workflows" / relative
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ""}
            else:
                continue
            assert not any(
                name == "scripts" or name.startswith("scripts.") for name in names
            )
            assert not any(
                name == "src.estimation" or name.startswith("src.estimation.")
                for name in names
            )
            assert not names.intersection(forbidden_imports)


def test_authoritative_workflows_do_not_mutate_sys_path() -> None:
    for relative in WORKFLOW_MAPPING.values():
        path = ROOT / "workflows" / relative
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Attribute) or node.attr != "path":
                continue
            assert not (isinstance(node.value, ast.Name) and node.value.id == "sys"), (
                path
            )


def test_workflow_targets_retain_sql_and_output_references() -> None:
    combined = "\n".join(
        (ROOT / "workflows" / relative).read_text(encoding="utf-8")
        for relative in WORKFLOW_MAPPING.values()
    )
    assert "sql/" in combined or ' / "sql"' in combined
    assert "outputs/diagnostics" in combined
    assert "data/processed/estimation" not in combined
    assert "data/raw/" not in combined
    assert "data/processed/market/" not in combined


def test_workflows_are_not_installed_packages() -> None:
    from setuptools import find_namespace_packages

    assert set(find_namespace_packages(where="src", include=["dai_sim*"])) == {
        "dai_sim",
        "dai_sim.calibration",
        "dai_sim.common",
        "dai_sim.experiments",
        "dai_sim.experiments.final",
        "dai_sim.experiments.mechanism",
        "dai_sim.inputs",
        "dai_sim.model",
        "dai_sim.validation",
    }
    assert not (ROOT / "workflows/__init__.py").exists()
