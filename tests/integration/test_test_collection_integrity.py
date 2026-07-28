"""Stage 9 logical collection, marker and monkeypatch preservation gates."""

from __future__ import annotations

import ast
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from tests.integration.test_test_hierarchy import EXPECTED_MAPPING, STAGE9_MODULES
from tests.support import REPOSITORY_ROOT


EXPECTED_CASE_DIGEST = (
    "d6130220e85bca93f7463a36cf326b787183326ef68004c9bd371f7c72067d21"
)
EXPECTED_DECORATOR_DIGEST = (
    "d020744b4fd16b1c5b7df51e11ae4ee4693c531c433267d75697efa05aae8cfb"
)
EXPECTED_MONKEYPATCH_DIGEST = (
    "ab4dd01aafb3912a97c25c7d99dbab33876de72fb1d5d79ad3287143307e05b8"
)
EXPECTED_CASE_COUNTS = {
    "tests/calibration/test_adoption.py": 13,
    "tests/calibration/test_liquidations.py": 12,
    "tests/calibration/test_market_gas_protocol.py": 16,
    "tests/calibration/test_validation.py": 12,
    "tests/calibration/test_vaults.py": 16,
    "tests/inputs/test_configuration.py": 11,
    "tests/inputs/test_configuration_profiles.py": 16,
    "tests/inputs/test_environment.py": 17,
    "tests/inputs/test_liquidations.py": 17,
    "tests/inputs/test_model_input_paths.py": 6,
    "tests/inputs/test_vaults.py": 19,
    "tests/integration/test_documentation_hierarchy.py": 7,
    "tests/integration/test_documentation_journeys.py": 8,
    "tests/integration/test_documentation_links.py": 10,
    "tests/integration/test_domain_data_paths.py": 6,
    "tests/integration/test_package_and_paths.py": 16,
    "tests/integration/test_provenance_paths.py": 6,
    "tests/integration/test_source_compatibility.py": 6,
    "tests/integration/test_source_package_migration.py": 4,
    "tests/integration/test_sql_hierarchy.py": 6,
    "tests/integration/test_sql_integrity.py": 4,
    "tests/workflows/gas/test_acquisition.py": 19,
    "tests/workflows/gas/test_processing.py": 10,
    "tests/workflows/liquidations/test_acquisition.py": 17,
    "tests/workflows/liquidations/test_diagnostic.py": 16,
    "tests/workflows/liquidations/test_diagnostic_reconciliation.py": 14,
    "tests/workflows/market/test_acquisition.py": 7,
    "tests/workflows/market/test_processing.py": 4,
    "tests/workflows/protocol/test_acquisition.py": 4,
    "tests/workflows/protocol/test_activation.py": 7,
    "tests/workflows/protocol/test_history.py": 19,
    "tests/workflows/test_compatibility.py": 49,
    "tests/workflows/test_migration.py": 8,
    "tests/workflows/vaults/test_acquisition.py": 19,
    "tests/workflows/vaults/test_discovery.py": 8,
    "tests/workflows/vaults/test_representative_windows.py": 45,
}


def _collect_nodeids() -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return [line for line in result.stdout.splitlines() if "::" in line]


def _baseline_nodeids(nodeids: list[str]) -> list[str]:
    return sorted(
        nodeid
        for nodeid in nodeids
        if nodeid.split("::", 1)[0] not in STAGE9_MODULES
    )


def _digest_lines(lines: list[str]) -> str:
    return sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def _decorator_records() -> list[tuple[str, str, tuple[str, ...]]]:
    records = []
    for relative in sorted(EXPECTED_MAPPING.values()):
        tree = ast.parse((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("test_"):
                    continue
            elif isinstance(node, ast.ClassDef):
                if not node.name.startswith("Test"):
                    continue
            else:
                continue
            records.append(
                (
                    relative,
                    node.name,
                    tuple(ast.unparse(item) for item in node.decorator_list),
                )
            )
    return sorted(records)


def _monkeypatch_records() -> list[tuple[str, str, tuple[str, ...]]]:
    records = []
    for relative in sorted(EXPECTED_MAPPING.values()):
        tree = ast.parse((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call = ast.unparse(node.func)
            if "monkeypatch" not in call:
                continue
            records.append(
                (
                    relative,
                    call,
                    tuple(ast.unparse(argument) for argument in node.args),
                )
            )
    return sorted(records)


def _json_digest(value: object) -> str:
    serialised = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    return sha256(serialised.encode("utf-8")).hexdigest()


def test_all_474_pre_migration_logical_cases_are_preserved() -> None:
    baseline = _baseline_nodeids(_collect_nodeids())
    assert len(baseline) == 474
    assert len(set(baseline)) == len(baseline)
    assert _digest_lines(baseline) == EXPECTED_CASE_DIGEST


def test_pre_migration_case_counts_are_preserved_by_module() -> None:
    counts = Counter(
        nodeid.split("::", 1)[0] for nodeid in _baseline_nodeids(_collect_nodeids())
    )
    assert counts == Counter(EXPECTED_CASE_COUNTS)


def test_parametrisation_and_marker_decorators_are_preserved() -> None:
    records = _decorator_records()
    assert len(records) == 415
    assert _json_digest(records) == EXPECTED_DECORATOR_DIGEST


def test_monkeypatch_targets_and_arguments_are_preserved() -> None:
    records = _monkeypatch_records()
    assert len(records) == 51
    assert _json_digest(records) == EXPECTED_MONKEYPATCH_DIGEST


def test_existing_suite_defines_no_fixture_with_changed_scope() -> None:
    fixture_decorators = []
    for relative in sorted(EXPECTED_MAPPING.values()):
        tree = ast.parse((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fixture_decorators.extend(
                ast.unparse(item)
                for item in node.decorator_list
                if "fixture" in ast.unparse(item)
            )
    assert fixture_decorators == []


def test_stage9_cases_are_the_only_collection_additions() -> None:
    nodeids = _collect_nodeids()
    baseline = _baseline_nodeids(nodeids)
    additions = sorted(set(nodeids) - set(baseline))
    assert additions
    assert all(nodeid.split("::", 1)[0] in STAGE9_MODULES for nodeid in additions)
    assert len(nodeids) == 474 + len(additions)
