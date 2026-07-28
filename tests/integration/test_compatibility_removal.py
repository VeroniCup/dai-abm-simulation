"""Final-state gates for the Stage 11 compatibility removal."""

from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys

import pytest
from setuptools import find_namespace_packages

from tests.integration.test_source_package_migration import AUTHORITATIVE_MODULES
from tests.support import REPOSITORY_ROOT as ROOT


REMOVED_FLAT_MODULES = (
    "__init__.py",
    "collateral.py",
    "confidence.py",
    "dai_market.py",
    "empirical_config.py",
    "empirical_data.py",
    "empirical_sources.py",
    "environment_inputs.py",
    "experiments.py",
    "gas_process.py",
    "liquidation.py",
    "liquidation_demand.py",
    "market_bootstrap.py",
    "metrics.py",
    "plot_results.py",
    "price_process.py",
    "protocol_data.py",
    "simulation.py",
    "vault.py",
    "vault_initialisation.py",
)
REMOVED_ESTIMATION_MODULES = (
    "__init__.py",
    "adoption_review.py",
    "data_loading.py",
    "phase2a.py",
    "phase2a_review.py",
    "phase2b_vaults.py",
    "phase2c_liquidations.py",
    "statistics.py",
)
REMOVED_CONFIGURATIONS = (
    "config/empirical/phase2_empirical_baseline.yaml",
    "config/empirical/phase2_empirical_distributional.yaml",
    "config/empirical/phase2_empirical_market_gas.yaml",
    "config/empirical/phase2_empirical_liquidation_arrivals.yaml",
    "config/protocol.yaml",
    "config/collateral_mapping.csv",
)


def test_removed_source_paths_are_absent() -> None:
    assert all(not (ROOT / "src" / name).exists() for name in REMOVED_FLAT_MODULES)
    assert all(
        not (ROOT / "src/estimation" / name).exists()
        for name in REMOVED_ESTIMATION_MODULES
    )
    assert not (ROOT / "src/estimation").exists()


@pytest.mark.parametrize(
    "module_name",
    ("collateral", "src.simulation", "src.estimation.phase2a"),
)
def test_removed_imports_fail_outside_repository(
    module_name: str,
    tmp_path: Path,
) -> None:
    source_path = ROOT / "src"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib; "
                f"importlib.import_module({module_name!r})"
            ),
        ],
        cwd=tmp_path,
        env={"PYTHONPATH": f"{source_path}:{ROOT}"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "ModuleNotFoundError" in completed.stderr


def test_all_canonical_modules_import() -> None:
    assert [
        importlib.import_module(name).__name__ for name in AUTHORITATIVE_MODULES
    ] == list(AUTHORITATIVE_MODULES)


def test_externally_exercised_private_symbols_remain_canonical() -> None:
    validation = importlib.import_module("dai_sim.calibration.validation")
    assert all(
        hasattr(validation, name)
        for name in (
            "_block_length_sensitivity",
            "_candidate_review",
            "_phase1e_dependencies",
            "_review_decision",
        )
    )


def test_canonical_source_contains_no_compatibility_fallback() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "src/dai_sim").rglob("*.py"))
    )
    assert "config/empirical/" not in combined
    assert "src.estimation" not in combined
    assert "COMPATIBILITY_PROFILE_MODES" not in combined
    assert '"base_config" in raw' not in combined
    assert "_sys.modules[" not in combined


def test_removed_configuration_aliases_are_absent() -> None:
    assert all(not (ROOT / path).exists() for path in REMOVED_CONFIGURATIONS)
    assert not (ROOT / "config/empirical").exists()
    assert {path.name for path in (ROOT / "config/profiles").glob("*.yaml")} == {
        "empirical.yaml",
        "empirical_stress.yaml",
        "legacy.yaml",
    }
    assert len(list((ROOT / "config/sensitivities").glob("*/*.yaml"))) == 14


def test_distribution_contains_only_canonical_packages() -> None:
    assert set(find_namespace_packages(where="src", include=["dai_sim*"])) == {
        "dai_sim",
        "dai_sim.calibration",
        "dai_sim.common",
        "dai_sim.experiments",
        "dai_sim.inputs",
        "dai_sim.model",
    }
    assert not list((ROOT / "src").glob("*.py"))
