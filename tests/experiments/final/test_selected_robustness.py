"""Focused tests for the registered selected robustness layer."""

from __future__ import annotations

import json
import numpy as np
import pytest

from dai_sim.experiments.final import selected_robustness as robustness


def test_registry_is_exact_56_cell_oat_matrix() -> None:
    cells = robustness.build_cell_registry()
    assert len(cells) == 56
    assert len({cell.identifier for cell in cells}) == 56
    assert {cell.contrast_family for cell in cells} == set(robustness.CONTRAST_ORDER)
    assert {cell.setting for cell in cells} == set(robustness.SETTING_ORDER)
    assert {cell.role for cell in cells} == {"reference", "treatment"}
    assert {cell.replication_count for cell in cells} == {64}
    assert len(cells) * robustness.REPLICATIONS == 3584


def test_registry_contains_only_remaining_dimensions() -> None:
    owner = robustness.load_registry()
    assert owner["no_full_factorial"] is True
    assert owner["forbidden_dimensions"] == [
        "capacity",
        "oracle_delay",
        "confidence_scenario",
        "recovery_path",
        "portfolio_endpoints",
        "shock_definitions",
    ]
    assert {cell.population for cell in robustness.build_cell_registry()} == {250, 500, 1000}
    assert {cell.market_block_hours for cell in robustness.build_cell_registry()} == {72, 168, 336}
    assert {cell.hurdle for cell in robustness.build_cell_registry()} == {
        "direct_cost_only",
        "keeper_hurdle_low",
        "keeper_hurdle_high",
    }
    assert owner["fixed_system"]["capacity"] == 26
    assert owner["fixed_system"]["oracle_delay_hours"] == 0
    assert owner["fixed_system"]["confidence"] == "stage1_only"
    assert owner["fixed_system"]["dai_residual_block_hours"] == 24


def test_keeper_hurdle_semantics_are_exact() -> None:
    owner = robustness.load_registry()["keeper_hurdles"]
    assert owner["direct_cost_only"] == {
        "risk_cost_rate": 0.0,
        "unit": "fraction_of_debt_repaid",
    }
    assert owner["keeper_hurdle_low"]["risk_cost_rate"] == pytest.approx(0.105100900480)
    assert owner["keeper_hurdle_high"]["risk_cost_rate"] == pytest.approx(0.124431757397)
    assert {value["unit"] for value in owner.values()} == {"fraction_of_debt_repaid"}


@pytest.fixture(scope="module")
def nested_states():  # type: ignore[no-untyped-def]
    return robustness.initialise_nested_populations(0)


def test_population_states_fix_scale_and_collateralisation(nested_states) -> None:  # type: ignore[no-untyped-def]
    _, portfolios, _ = robustness.experiment_a._design_payloads()
    for population, states in nested_states.items():
        for portfolio, state in states.items():
            assert len(state.vaults) == population
            assert sum(vault.debt_dai for vault in state.vaults) == pytest.approx(2_500_000.0)
            assert state.final_system_collateral_ratio == pytest.approx(3.6089387701260205)
            expected = robustness.multicollateral_validation._portfolio_payload(
                portfolios,
                portfolio,
            )["target_debt_shares"]
            observed = (
                state.sampled.groupby("family")["debt_dai"].sum()
                / state.sampled["debt_dai"].sum()
            ).to_dict()
            for family in robustness.FAMILY_ORDER:
                assert observed.get(family, 0.0) == pytest.approx(expected[family])


def test_population_draws_are_nested(nested_states) -> None:  # type: ignore[no-untyped-def]
    assert robustness.audit_population_nesting(nested_states) == {
        "passed": True,
        "failure_count": 0,
    }


def test_market_blocks_are_aligned_and_exclude_holdouts() -> None:
    blocks = robustness._sample_market_paths(0)
    assert tuple(blocks) == (72, 168, 336)
    for length, frame in blocks.items():
        assert len(frame) == 768
        assert len(frame.attrs["block_starts"]) == int(np.ceil(768 / length))
        timestamps = robustness.pd.to_datetime(frame["timestamp_utc"], utc=True)
        assert not ((timestamps >= robustness.FTX_START) & (timestamps < robustness.FTX_END)).any()
        assert not ((timestamps >= robustness.SVB_START) & (timestamps < robustness.SVB_END)).any()
        assert frame[["eth_log_return", "wbtc_log_return"]].notna().all().all()
    assert robustness.specification_payload()["market_blocks"][
        "dai_residual_block_hours"
    ] == 24


def test_recovery_sensitivity_reuses_one_path_and_keeps_24_primary() -> None:
    path = np.ones(720)
    path[:10] = 0.99
    first = robustness._recovery_sensitivity(path)
    second = robustness._recovery_sensitivity(path.copy())
    assert first == second
    assert [row["consecutive_hours"] for row in first] == [12, 24, 48]
    assert robustness.load_registry()["recovery_definition"]["primary_consecutive_hours"] == 24


@pytest.mark.parametrize(
    ("retained", "reversed", "operational", "valid", "expected"),
    [
        (5, 0, True, True, "robust"),
        (4, 0, True, True, "robust_with_qualification"),
        (3, 0, True, True, "sensitivity_dependent"),
        (5, 2, True, True, "reversed_under_sensitivity"),
        (5, 0, False, True, "not_operational"),
        (5, 0, True, False, "invalid"),
    ],
)
def test_contrast_classification_branches(
    retained: int,
    reversed: int,
    operational: bool,
    valid: bool,
    expected: str,
) -> None:
    assert robustness.classify_contrast_family(
        retained_settings=retained,
        clear_reversal_settings=reversed,
        operational=operational,
        valid=valid,
    ) == expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["robust"] * 4, "core_conclusions_robust"),
        (["robust", "robust_with_qualification"], "core_conclusions_robust_with_qualifications"),
        (["robust", "sensitivity_dependent"], "core_conclusions_sensitivity_dependent"),
        (["robust", "reversed_under_sensitivity"], "core_conclusions_not_robust"),
        (["robust", "invalid"], "robustness_invalid"),
    ],
)
def test_overall_classification_branches(values: list[str], expected: str) -> None:
    assert robustness.classify_overall(values) == expected


def test_r_d_preserves_inconsistent_gradient_without_two_clear_adverse_metrics() -> None:
    rows = []
    for setting in robustness.SETTING_ORDER:
        for metric in (*robustness.PRIMARY_METRICS, *robustness.R_D_METRICS):
            rows.append(
                {
                    "contrast_family": "R-D",
                    "setting": setting,
                    "metric": metric,
                    "operationality": "operational",
                    "sign_relative_to_core": "retained",
                    "ci95_upper": 0.0,
                }
            )
    frame = robustness.pd.DataFrame(rows)
    simulation_rows = robustness.pd.DataFrame(
        {
            "accounting_valid": [True],
            "numerical_valid": [True],
            "path_valid": [True],
            "held_out_data_used": [False],
        }
    )
    decision = robustness.decision_payload(frame, simulation_rows)
    assert decision["contrast_families"]["R-D"]["classification"] == "robust"
    assert decision["contrast_families"]["R-D"]["baseline_direction_reconstructed"] is True


def test_r_d_two_metric_adverse_gradient_is_a_clear_reversal() -> None:
    rows = []
    for setting in robustness.SETTING_ORDER:
        for position, metric in enumerate(
            (*robustness.PRIMARY_METRICS, *robustness.R_D_METRICS)
        ):
            rows.append(
                {
                    "contrast_family": "R-D",
                    "setting": setting,
                    "metric": metric,
                    "operationality": "operational",
                    "sign_relative_to_core": (
                        "reversed"
                        if setting in {"population_250", "population_1000"}
                        and position < 2
                        else "retained"
                    ),
                    "ci95_upper": -0.1,
                }
            )
    frame = robustness.pd.DataFrame(rows)
    simulation_rows = robustness.pd.DataFrame(
        {
            "accounting_valid": [True],
            "numerical_valid": [True],
            "path_valid": [True],
            "held_out_data_used": [False],
        }
    )
    decision = robustness.decision_payload(frame, simulation_rows)
    assert decision["contrast_families"]["R-D"]["classification"] == (
        "reversed_under_sensitivity"
    )


def test_seed_registry_is_deterministic_and_result_blind() -> None:
    assert robustness.seed_record(0) == robustness.seed_record(0)
    assert robustness.seed_record(0) != robustness.seed_record(1)
    assert len(robustness.seed_registry_checksum()) == 64
    assert robustness.specification_payload()["no_retuning"] is True
    assert robustness.specification_payload()["runtime_adopted"] is False
    assert robustness.load_registry()["forbidden_dimensions"] == [
        "capacity",
        "oracle_delay",
        "confidence_scenario",
        "recovery_path",
        "portfolio_endpoints",
        "shock_definitions",
    ]


def test_experiment_manifest_uses_canonical_artefact_schema() -> None:
    manifest = json.loads(robustness.MANIFEST_PATH.read_text(encoding="utf-8"))
    assert "artefacts" in manifest
    assert "entries" not in manifest
    assert manifest["artefact_count"] == len(manifest["artefacts"])
