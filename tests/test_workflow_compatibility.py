"""Compatibility and CLI-parity gates for Stage 6 workflow wrappers."""

from __future__ import annotations

import importlib
from pathlib import Path
import re
import subprocess
import sys

import pytest

from test_workflow_migration import ROOT, WORKFLOW_MAPPING

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


CLI_WRAPPERS = (
    "acquire_dune_hourly_gas.py",
    "acquire_dune_market_prices.py",
    "acquire_dune_protocol_parameter_history.py",
    "acquire_dune_protocol_parameters.py",
    "acquire_dune_vaults.py",
    "acquire_phase1e_b_representative_vaults.py",
    "build_vault_initialisation_pools.py",
    "diagnose_dune_vat_activation.py",
    "discover_dune_vault_events.py",
    "process_dune_hourly_gas.py",
    "process_dune_market_prices.py",
    "repair_phase1e_b_quiet_rates.py",
    "retrieve_dune_execution_page.py",
    "run_parameter_adoption_review.py",
    "run_phase2a_candidate_review.py",
    "run_phase2a_parameter_estimation.py",
    "run_phase2b_vault_estimation.py",
    "run_phase2c_liquidation_estimation.py",
    "validate_dune_market_prices.py",
)


def _module_name(relative: str) -> str:
    return "workflows." + relative.removesuffix(".py").replace("/", ".")


def _wrapper_name(filename: str) -> str:
    return "scripts." + filename.removesuffix(".py")


@pytest.mark.parametrize("wrapper,target", WORKFLOW_MAPPING.items())
def test_wrapper_import_is_authoritative_module(
    wrapper: str,
    target: str,
) -> None:
    authoritative = importlib.import_module(_module_name(target))
    compatibility = importlib.import_module(_wrapper_name(wrapper))
    assert compatibility is authoritative


def test_corrected_wrapper_targets_are_exact() -> None:
    expected = {
        "acquire_dune_protocol_parameter_history.py": "workflows.protocol.acquire",
        "acquire_dune_protocol_parameters.py": (
            "workflows.maintenance.archive.debt_ceiling_diagnostic"
        ),
        "acquire_dune_vaults.py": "workflows.vaults.acquire",
        "acquire_phase1e_b_representative_vaults.py": (
            "workflows.vaults.acquire_representative"
        ),
    }
    for wrapper, module_name in expected.items():
        assert importlib.import_module(_wrapper_name(wrapper)) is importlib.import_module(
            module_name
        )


def test_wrappers_are_pure_aliases_without_path_mutation() -> None:
    for wrapper in WORKFLOW_MAPPING:
        path = ROOT / "scripts" / wrapper
        text = path.read_text(encoding="utf-8")
        assert "sys.path" not in text
        assert "import_module" in text
        assert "runpy.run_path" in text
        assert len(text.splitlines()) <= 25


def _normalise_help(text: str, wrapper: str, target: str) -> str:
    replacements = (
        str(ROOT / "scripts" / wrapper),
        str(ROOT / "workflows" / target),
        f"scripts/{wrapper}",
        f"workflows/{target}",
    )
    normalised = text
    for value in replacements:
        normalised = normalised.replace(value, "<COMMAND>")
    return re.sub(r"usage: [^\\s]+", "usage: <COMMAND>", normalised)


@pytest.mark.parametrize("wrapper", CLI_WRAPPERS)
def test_old_and_new_help_are_equivalent(wrapper: str) -> None:
    target = WORKFLOW_MAPPING[wrapper]
    commands = (
        [sys.executable, str(ROOT / "scripts" / wrapper), "--help"],
        [sys.executable, str(ROOT / "workflows" / target), "--help"],
    )
    results = [
        subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        for command in commands
    ]
    assert [result.returncode for result in results] == [0, 0]
    assert _normalise_help(results[0].stdout, wrapper, target) == _normalise_help(
        results[1].stdout,
        wrapper,
        target,
    )
    assert results[0].stderr == results[1].stderr == ""


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
