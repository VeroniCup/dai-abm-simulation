"""Structural gates for the Stage 6 workflow migration."""

from __future__ import annotations

import ast
from pathlib import Path


from tests.support import REPOSITORY_ROOT as ROOT

WORKFLOW_MAPPING = {
    "acquire_dune_hourly_gas.py": "gas/acquire.py",
    "acquire_dune_liquidation_diagnostic.py": (
        "maintenance/archive/liquidation_diagnostic.py"
    ),
    "acquire_dune_liquidation_diagnostic_attempt3.py": (
        "maintenance/archive/liquidation_diagnostic_attempt3.py"
    ),
    "acquire_dune_liquidations.py": "liquidations/acquire.py",
    "acquire_dune_market_prices.py": "market/acquire.py",
    "acquire_dune_protocol_parameter_history.py": "protocol/acquire.py",
    "acquire_dune_protocol_parameters.py": (
        "maintenance/archive/debt_ceiling_diagnostic.py"
    ),
    "acquire_dune_vaults.py": "vaults/acquire.py",
    "acquire_phase1e_b_representative_vaults.py": (
        "vaults/acquire_representative.py"
    ),
    "build_liquidation_arrival_runtime_pools.py": "liquidations/build_inputs.py",
    "build_market_gas_runtime_pools.py": "market/build_inputs.py",
    "build_vault_initialisation_pools.py": "vaults/build_inputs.py",
    "diagnose_dune_vat_activation.py": (
        "maintenance/archive/diagnose_vat_activation.py"
    ),
    "discover_dune_vault_events.py": (
        "maintenance/archive/discover_vault_events.py"
    ),
    "process_dune_hourly_gas.py": "gas/process.py",
    "process_dune_market_prices.py": "market/process.py",
    "repair_phase1e_b_quiet_rates.py": (
        "maintenance/archive/repair_quiet_rates.py"
    ),
    "retrieve_dune_execution_page.py": "maintenance/retrieve_result.py",
    "run_parameter_adoption_review.py": "calibration/adoption.py",
    "run_phase2a_candidate_review.py": "calibration/validate.py",
    "run_phase2a_parameter_estimation.py": (
        "calibration/market_gas_protocol.py"
    ),
    "run_phase2b_vault_estimation.py": "calibration/vaults.py",
    "run_phase2c_liquidation_estimation.py": "calibration/liquidations.py",
    "run_tranche_b_initialisation_diagnostics.py": "inputs/validate_vaults.py",
    "run_tranche_c_environment_diagnostics.py": (
        "inputs/validate_environment.py"
    ),
    "run_tranche_d_liquidation_diagnostics.py": (
        "inputs/validate_liquidations.py"
    ),
    "validate_dune_market_prices.py": "market/validate.py",
}

EXPECTED_CATEGORIES = {
    "calibration",
    "gas",
    "inputs",
    "liquidations",
    "maintenance",
    "market",
    "protocol",
    "vaults",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_exactly_27_unique_authoritative_workflows_exist() -> None:
    assert len(WORKFLOW_MAPPING) == 27
    assert len(set(WORKFLOW_MAPPING.values())) == 27
    assert not (ROOT / "scripts").exists()
    for target in WORKFLOW_MAPPING.values():
        assert (ROOT / "workflows" / target).is_file()


def test_protocol_and_vault_workflow_responsibilities_remain_distinct() -> None:
    expected = {
        "protocol/acquire.py",
        "maintenance/archive/debt_ceiling_diagnostic.py",
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
    assert not (workflow_root / "experiments").exists()
    for category in categories:
        assert any((workflow_root / category).rglob("*.py"))


def test_archived_debt_ceiling_diagnostic_is_a_real_implementation() -> None:
    path = ROOT / "workflows/maintenance/archive/debt_ceiling_diagnostic.py"
    tree = _tree(path)
    functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert {"main", "validate_rows", "write_json_atomic"} <= functions
    assert len(path.read_text(encoding="utf-8").splitlines()) > 400


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
            assert not any(name == "scripts" or name.startswith("scripts.") for name in names)
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
            assert not (
                isinstance(node.value, ast.Name) and node.value.id == "sys"
            ), path


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
        "dai_sim.inputs",
        "dai_sim.model",
    }
    assert not (ROOT / "workflows/__init__.py").exists()
