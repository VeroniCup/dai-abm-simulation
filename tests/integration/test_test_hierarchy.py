"""Stage 9 semantic test-hierarchy and fixture-integrity gates."""

from __future__ import annotations

from hashlib import sha256

from tests.support import REPOSITORY_ROOT


TESTS_ROOT = REPOSITORY_ROOT / "tests"
APPROVED_CATEGORIES = {
    "calibration",
    "experiments",
    "inputs",
    "integration",
    "model",
    "validation",
    "workflows",
}
EXPECTED_MAPPING = {
    "tests/test_configuration_profiles.py": (
        "tests/inputs/test_configuration_profiles.py"
    ),
    "tests/test_documentation_hierarchy.py": (
        "tests/integration/test_documentation_hierarchy.py"
    ),
    "tests/test_documentation_journeys.py": (
        "tests/integration/test_documentation_journeys.py"
    ),
    "tests/test_documentation_links.py": (
        "tests/integration/test_documentation_links.py"
    ),
    "tests/test_domain_data_paths.py": ("tests/integration/test_domain_data_paths.py"),
    "tests/test_dune_gas_pipeline.py": "tests/workflows/gas/test_acquisition.py",
    "tests/test_dune_liquidation_diagnostic.py": (
        "tests/workflows/liquidations/test_diagnostic.py"
    ),
    "tests/test_dune_liquidation_diagnostic_attempt3.py": (
        "tests/workflows/liquidations/test_diagnostic_reconciliation.py"
    ),
    "tests/test_dune_liquidation_production.py": (
        "tests/workflows/liquidations/test_acquisition.py"
    ),
    "tests/test_dune_market_pipeline.py": (
        "tests/workflows/market/test_acquisition.py"
    ),
    "tests/test_dune_protocol_parameter_history.py": (
        "tests/workflows/protocol/test_history.py"
    ),
    "tests/test_dune_protocol_parameters.py": (
        "tests/workflows/protocol/test_acquisition.py"
    ),
    "tests/test_dune_vat_activation_diagnostic.py": (
        "tests/workflows/protocol/test_activation.py"
    ),
    "tests/test_dune_vault_discovery.py": ("tests/workflows/vaults/test_discovery.py"),
    "tests/test_dune_vault_production.py": (
        "tests/workflows/vaults/test_acquisition.py"
    ),
    "tests/test_empirical_tranche_a_config.py": ("tests/inputs/test_configuration.py"),
    "tests/test_model_input_paths.py": "tests/inputs/test_model_input_paths.py",
    "tests/test_package_and_paths.py": ("tests/integration/test_package_and_paths.py"),
    "tests/test_parameter_adoption_review.py": ("tests/calibration/test_adoption.py"),
    "tests/test_phase1e_b_representative_vaults.py": (
        "tests/workflows/vaults/test_representative_windows.py"
    ),
    "tests/test_phase2a_candidate_review.py": ("tests/calibration/test_validation.py"),
    "tests/test_phase2a_estimation.py": (
        "tests/calibration/test_market_gas_protocol.py"
    ),
    "tests/test_phase2b_vault_estimation.py": ("tests/calibration/test_vaults.py"),
    "tests/test_phase2c_liquidation_estimation.py": (
        "tests/calibration/test_liquidations.py"
    ),
    "tests/test_process_dune_hourly_gas.py": ("tests/workflows/gas/test_processing.py"),
    "tests/test_process_dune_market_prices.py": (
        "tests/workflows/market/test_processing.py"
    ),
    "tests/test_provenance_paths.py": ("tests/integration/test_provenance_paths.py"),
    "tests/test_source_package_migration.py": (
        "tests/integration/test_source_package_migration.py"
    ),
    "tests/test_sql_hierarchy.py": "tests/integration/test_sql_hierarchy.py",
    "tests/test_sql_integrity.py": "tests/integration/test_sql_integrity.py",
    "tests/test_tranche_b_vault_initialisation.py": "tests/inputs/test_vaults.py",
    "tests/test_tranche_c_environment_inputs.py": "tests/inputs/test_environment.py",
    "tests/test_tranche_d_liquidation_demand.py": ("tests/inputs/test_liquidations.py"),
    "tests/test_workflow_migration.py": "tests/workflows/test_migration.py",
}
STAGE9_MODULES = {
    "tests/integration/test_test_collection_integrity.py",
    "tests/integration/test_test_hierarchy.py",
}
STAGE10_MODULES = {
    "tests/integration/test_ignore_rules.py",
    "tests/integration/test_output_hierarchy.py",
}
STAGE11_MODULES = {
    "tests/integration/test_compatibility_removal.py",
    "tests/workflows/test_canonical_commands.py",
}
POST_STAGE11_CORRECTION_MODULES = {
    "tests/workflows/test_semantic_output_paths.py",
}
CLEAN_CLONE_CORRECTION_MODULES = {
    "tests/calibration/test_tracked_calibration_evidence.py",
}
POST_RESTRUCTURING_FEATURE_MODULES = {
    "tests/calibration/test_confidence_evidence.py",
    "tests/calibration/test_confidence_infrastructure_evidence.py",
    "tests/inputs/test_confidence_scenario_resolution.py",
    "tests/validation/test_confidence_scenarios.py",
    "tests/calibration/test_event_simulation.py",
    "tests/calibration/test_keeper_execution.py",
    "tests/calibration/test_partial_identification.py",
    "tests/calibration/test_simulated_moments.py",
    "tests/calibration/test_simulated_moments_search.py",
    "tests/calibration/test_simulated_moments_diagnostics.py",
    "tests/calibration/test_structural_factorial.py",
    "tests/calibration/test_structural_incompatibility.py",
    "tests/model/test_confidence.py",
    "tests/model/test_liquidation_ranking.py",
    "tests/model/test_market.py",
    "tests/workflows/test_confidence_calibration.py",
    "tests/experiments/mechanism/test_eth_recovery.py",
    "tests/experiments/mechanism/test_constrained_eth_recovery.py",
    "tests/experiments/final/test_correlated_stress.py",
    "tests/experiments/final/test_idiosyncratic_diversification.py",
    "tests/experiments/final/test_stable_collateral_tradeoff.py",
    "tests/experiments/final/test_shared_keeper_capacity.py",
    "tests/experiments/final/test_final_oracle_delay.py",
    "tests/experiments/final/test_programme.py",
    "tests/validation/test_integrated_eth.py",
    "tests/validation/test_multicollateral.py",
    "tests/inputs/test_multicollateral.py",
    "tests/calibration/test_oracle_delay.py",
    "tests/inputs/test_oracle_delay.py",
    "tests/validation/test_oracle_delay.py",
    "tests/workflows/test_oracle_delay.py",
}
EXPECTED_FIXTURES = {
    "tests/fixtures/market/empirical_market.csv": (
        "297ab396a003a48322dd624c276d3edac656b8d0ebc91ca29d2292cf3959cec2"
    ),
    "tests/fixtures/protocol/collateral_mapping_fixture.csv": (
        "3a98e44381facbeb90ef96e52699f23813c6a5b71f08e825ab9cee6eb0edbaad"
    ),
    "tests/fixtures/protocol/liquidation_fixture.csv": (
        "114f41325a672c68de9c66a4c27cbf3ea25378dbf8dbbbc1b7a47082232df67d"
    ),
    "tests/fixtures/protocol/protocol_fixture.csv": (
        "dc7c22d5cc981c189c7440e746d8f4d664c99c6c088ea9ab268c6abd312e19fb"
    ),
    "tests/fixtures/protocol/vault_fixture.csv": (
        "c5b627911d022ced8e784cc055afe7759b272787545265fc76f93c00f129cd00"
    ),
}


def _relative_test_modules() -> set[str]:
    return {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in TESTS_ROOT.rglob("test_*.py")
    }


def test_pre_migration_mapping_is_complete_and_one_to_one() -> None:
    assert len(EXPECTED_MAPPING) == 34
    assert len(set(EXPECTED_MAPPING.values())) == len(EXPECTED_MAPPING)
    assert (
        set(EXPECTED_MAPPING.values())
        | STAGE9_MODULES
        | STAGE10_MODULES
        | STAGE11_MODULES
        | POST_STAGE11_CORRECTION_MODULES
        | CLEAN_CLONE_CORRECTION_MODULES
        | POST_RESTRUCTURING_FEATURE_MODULES
        == _relative_test_modules()
    )
    assert all(not (REPOSITORY_ROOT / old).exists() for old in EXPECTED_MAPPING)
    assert all((REPOSITORY_ROOT / new).is_file() for new in EXPECTED_MAPPING.values())


def test_only_populated_semantic_categories_exist() -> None:
    populated = {
        path.name
        for path in TESTS_ROOT.iterdir()
        if path.is_dir() and path.name != "fixtures" and any(path.rglob("test_*.py"))
    }
    assert populated == APPROVED_CATEGORIES
    assert (TESTS_ROOT / "experiments/mechanism/test_eth_recovery.py").is_file()


def test_no_test_module_remains_at_suite_root() -> None:
    assert not list(TESTS_ROOT.glob("test_*.py"))
    assert (TESTS_ROOT / "conftest.py").is_file()
    assert (TESTS_ROOT / "support.py").is_file()


def test_no_placeholder_or_duplicate_test_module_exists() -> None:
    modules = sorted(TESTS_ROOT.rglob("test_*.py"))
    assert len(modules) == 73
    assert all(path.stat().st_size > 100 for path in modules)
    assert len({path.resolve() for path in modules}) == len(modules)


def test_static_fixture_paths_and_bytes_are_exact() -> None:
    actual = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (TESTS_ROOT / "fixtures").rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    }
    assert actual == set(EXPECTED_FIXTURES)
    for relative, expected in EXPECTED_FIXTURES.items():
        assert sha256((REPOSITORY_ROOT / relative).read_bytes()).hexdigest() == expected


def test_market_fixture_move_preserves_shape_and_old_path_is_absent() -> None:
    path = REPOSITORY_ROOT / "tests/fixtures/market/empirical_market.csv"
    lines = path.read_bytes().splitlines()
    assert len(lines) == 20
    assert lines[0].decode("utf-8").split(",") == [
        "timestamp",
        "eth_usd",
        "btc_usd",
        "stable_usd",
        "dai_usd",
        "gas_proxy",
        "liquidation_volume",
    ]
    assert not (
        REPOSITORY_ROOT / "tests/fixtures/empirical_market_fixture.csv"
    ).exists()


def test_stage11_final_state_coverage_is_explicit() -> None:
    required = {
        "tests/integration/test_compatibility_removal.py": (
            "REMOVED_FLAT_MODULES",
            "REMOVED_ESTIMATION_MODULES",
        ),
        "tests/workflows/test_canonical_commands.py": (
            "CLI_WORKFLOWS",
            "REMOVED_WRAPPERS",
        ),
    }
    for relative, terms in required.items():
        text = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        assert all(term in text for term in terms)
