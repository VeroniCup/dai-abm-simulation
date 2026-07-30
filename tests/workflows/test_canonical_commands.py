"""Canonical workflow command gates after Stage 11 wrapper removal."""

from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys

import pytest

from tests.support import REPOSITORY_ROOT as ROOT
from tests.workflows.test_migration import WORKFLOW_MAPPING


REMOVED_WRAPPERS = tuple(WORKFLOW_MAPPING)
CLI_WORKFLOWS = (
    "gas/acquire.py",
    "market/acquire.py",
    "protocol/acquire.py",
    "maintenance/archive/debt_ceiling_diagnostic.py",
    "vaults/acquire.py",
    "vaults/acquire_representative.py",
    "vaults/build_inputs.py",
    "maintenance/archive/diagnose_vat_activation.py",
    "maintenance/archive/discover_vault_events.py",
    "gas/process.py",
    "inputs/validate_multicollateral.py",
    "market/process.py",
    "maintenance/archive/repair_quiet_rates.py",
    "maintenance/retrieve_result.py",
    "calibration/adoption.py",
    "calibration/validate.py",
    "calibration/market_gas_protocol.py",
    "calibration/vaults.py",
    "calibration/liquidations.py",
    "market/validate.py",
)


def _module_name(relative: str) -> str:
    return "workflows." + relative.removesuffix(".py").replace("/", ".")


def test_removed_wrapper_paths_are_absent_and_workflows_import() -> None:
    assert not (ROOT / "scripts").exists()
    assert all(
        not (ROOT / "scripts" / wrapper).exists()
        for wrapper in REMOVED_WRAPPERS
    )
    assert [
        importlib.import_module(_module_name(relative)).__name__
        for relative in WORKFLOW_MAPPING.values()
    ] == [
        _module_name(relative) for relative in WORKFLOW_MAPPING.values()
    ]


@pytest.mark.parametrize("relative", CLI_WORKFLOWS)
def test_canonical_workflow_help(relative: str) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "workflows" / relative), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
    assert result.stderr == ""

def test_direct_workflow_help_is_working_directory_independent(
    tmp_path: Path,
) -> None:
    target = ROOT / "workflows/market/acquire.py"
    result = subprocess.run(
        [sys.executable, str(target), "--help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "--mode" in result.stdout
    assert result.stderr == ""
