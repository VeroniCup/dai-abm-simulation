"""Test-collection, marker and monkeypatch preservation gates."""

from __future__ import annotations

import ast
from collections import Counter
from hashlib import sha256
import json
import subprocess
import sys

from tests.integration.test_test_hierarchy import (
    CLEAN_CLONE_CORRECTION_MODULES,
    EXPECTED_MAPPING,
    POST_RESTRUCTURING_FEATURE_MODULES,
    POST_STAGE11_CORRECTION_MODULES,
    STAGE11_MODULES,
    STAGE9_MODULES,
    STAGE10_MODULES,
)
from tests.support import REPOSITORY_ROOT


EXPECTED_CASE_DIGEST = (
    "2054b2891c179229b3c08794af04dfd0d56edfec8c277ec0d17da1ed7cad42e4"
)
EXPECTED_DECORATOR_DIGEST = (
    "f4c54d66e12bc9ceb1b27d3367971f9af1adc956f1f3fb42e194ed41e9029411"
)
EXPECTED_MONKEYPATCH_DIGEST = (
    "d4041fbf5d7ae996d9b2786db57b61921a7cd2d44288e49f407167dd1f24d187"
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
    "tests/inputs/test_liquidations.py": 18,
    "tests/inputs/test_model_input_paths.py": 6,
    "tests/inputs/test_vaults.py": 19,
    "tests/integration/test_documentation_hierarchy.py": 7,
    "tests/integration/test_documentation_journeys.py": 8,
    "tests/integration/test_documentation_links.py": 10,
    "tests/integration/test_domain_data_paths.py": 6,
    "tests/integration/test_package_and_paths.py": 16,
    "tests/integration/test_provenance_paths.py": 6,
    "tests/integration/test_source_package_migration.py": 4,
    "tests/integration/test_sql_hierarchy.py": 6,
    "tests/integration/test_sql_integrity.py": 4,
    "tests/workflows/gas/test_acquisition.py": 19,
    "tests/workflows/gas/test_processing.py": 10,
    "tests/workflows/liquidations/test_acquisition.py": 17,
    "tests/workflows/market/test_acquisition.py": 7,
    "tests/workflows/market/test_processing.py": 4,
    "tests/workflows/protocol/test_history.py": 19,
    "tests/workflows/test_migration.py": 8,
    "tests/workflows/vaults/test_acquisition.py": 18,
    "tests/workflows/vaults/test_representative_windows.py": 44,
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
        if nodeid.split("::", 1)[0]
        not in (
            STAGE9_MODULES
            | STAGE10_MODULES
            | STAGE11_MODULES
            | POST_STAGE11_CORRECTION_MODULES
            | CLEAN_CLONE_CORRECTION_MODULES
            | POST_RESTRUCTURING_FEATURE_MODULES
        )
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


def test_all_369_retained_pre_migration_logical_cases_are_preserved() -> None:
    baseline = _baseline_nodeids(_collect_nodeids())
    assert len(baseline) == 369
    assert len(set(baseline)) == len(baseline)
    assert _digest_lines(baseline) == EXPECTED_CASE_DIGEST


def test_pre_migration_case_counts_are_preserved_by_module() -> None:
    counts = Counter(
        nodeid.split("::", 1)[0] for nodeid in _baseline_nodeids(_collect_nodeids())
    )
    assert counts == Counter(EXPECTED_CASE_COUNTS)


def test_parametrisation_and_marker_decorators_are_preserved() -> None:
    records = _decorator_records()
    assert len(records) == 354
    assert _json_digest(records) == EXPECTED_DECORATOR_DIGEST


def test_monkeypatch_targets_and_arguments_are_preserved() -> None:
    records = _monkeypatch_records()
    assert len(records) == 34
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


def test_restructuring_cases_are_the_only_collection_additions() -> None:
    nodeids = _collect_nodeids()
    baseline = _baseline_nodeids(nodeids)
    additions = sorted(set(nodeids) - set(baseline))
    assert additions
    assert all(
        nodeid.split("::", 1)[0]
        in (
            STAGE9_MODULES
            | STAGE10_MODULES
            | STAGE11_MODULES
            | POST_STAGE11_CORRECTION_MODULES
            | CLEAN_CLONE_CORRECTION_MODULES
            | POST_RESTRUCTURING_FEATURE_MODULES
        )
        for nodeid in additions
    )
    counts = Counter(nodeid.split("::", 1)[0] for nodeid in additions)
    assert counts == {
        "tests/integration/test_ignore_rules.py": 6,
        "tests/integration/test_archive_boundary.py": 15,
        "tests/integration/test_output_hierarchy.py": 12,
        "tests/integration/test_test_collection_integrity.py": 6,
        "tests/integration/test_test_hierarchy.py": 7,
        "tests/integration/test_compatibility_removal.py": 9,
        "tests/integration/test_diagnostic_independence.py": 1,
        "tests/inputs/test_multicollateral.py": 9,
        "tests/inputs/test_runtime_sources.py": 18,
        "tests/workflows/test_canonical_commands.py": 18,
        "tests/workflows/test_semantic_output_paths.py": 5,
        "tests/calibration/test_tracked_calibration_evidence.py": 10,
        "tests/calibration/test_confidence_evidence.py": 10,
        "tests/calibration/test_confidence_infrastructure_evidence.py": 11,
        "tests/inputs/test_confidence_scenario_resolution.py": 28,
        "tests/calibration/test_event_simulation.py": 6,
        "tests/calibration/test_keeper_execution.py": 13,
        "tests/calibration/test_partial_identification.py": 24,
        "tests/calibration/test_simulated_moments.py": 17,
        "tests/calibration/test_simulated_moments_search.py": 21,
        "tests/calibration/test_simulated_moments_diagnostics.py": 38,
        "tests/calibration/test_structural_factorial.py": 70,
        "tests/calibration/test_structural_incompatibility.py": 44,
        "tests/model/test_confidence.py": 10,
        "tests/model/test_liquidation_ranking.py": 6,
        "tests/model/test_market.py": 7,
        "tests/workflows/test_confidence_calibration.py": 40,
        "tests/experiments/mechanism/test_eth_recovery.py": 36,
        "tests/experiments/mechanism/test_constrained_eth_recovery.py": 41,
        "tests/experiments/final/test_correlated_stress.py": 65,
        "tests/experiments/final/test_idiosyncratic_diversification.py": 39,
        "tests/experiments/final/test_stable_collateral_tradeoff.py": 63,
        "tests/experiments/final/test_shared_keeper_capacity.py": 59,
        "tests/experiments/final/test_final_oracle_delay.py": 38,
        "tests/experiments/final/test_balance_sheet_animation.py": 10,
        "tests/experiments/final/test_oracle_delay_animation.py": 11,
        "tests/experiments/final/test_programme.py": 9,
        "tests/experiments/final/test_recovery_behaviour_synthesis.py": 40,
        "tests/experiments/final/test_selected_robustness.py": 22,
        "tests/validation/test_confidence_scenarios.py": 9,
        "tests/validation/test_final_validation.py": 25,
        "tests/validation/test_integrated_eth.py": 20,
        "tests/validation/test_multicollateral.py": 40,
        "tests/calibration/test_oracle_delay.py": 8,
        "tests/inputs/test_oracle_delay.py": 4,
        "tests/validation/test_oracle_delay.py": 3,
        "tests/workflows/test_oracle_delay.py": 3,
    }
    assert len(nodeids) == 369 + len(additions)
