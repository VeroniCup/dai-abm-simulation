"""Substantive gates for the constrained-liquidation ETH recovery study."""

from __future__ import annotations

from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from dai_sim.experiments.confidence_scenarios import EXPECTED_SCENARIO_ORDER
from dai_sim.experiments.constrained_eth_recovery import (
    CAPACITY_ORDER,
    CAPACITY_VALUES,
    EXPECTED_PATH_CHECKSUMS,
    EXPECTED_SHOCK_CHECKSUM,
    PROFILE_IDENTITY,
    PROFILE_SHA256,
    RECOVERY_PATH_ORDER,
    SEED_STREAMS,
    _demand_decision,
    _distribution,
    _overall_classification,
    _pair_vault_events,
    _support_classification,
    build_cell_registry,
    build_paths,
    capacity_contrasts,
    derive_seed,
    experiment_identity,
    load_design,
    preflight,
    recovery_contrasts,
    seed_record,
    seed_registry_checksum,
    specification_payload,
)
from dai_sim.experiments.eth_recovery import _recovery_metrics, path_checksum
from dai_sim.inputs.integrated_profile import (
    TOTAL_DEBT_DAI,
    VAULT_COUNT,
    resolve_integrated_empirical_eth_profile,
)


def _design():
    return load_design()


def test_integrated_profile_identity_and_experimental_boundary() -> None:
    profile = resolve_integrated_empirical_eth_profile()
    assert profile.identifier == "empirical_integrated_eth"
    assert profile.profile_identity == PROFILE_IDENTITY
    assert profile.profile_checksum == PROFILE_SHA256
    assert profile.runtime_adopted is False
    assert VAULT_COUNT == 500
    assert TOTAL_DEBT_DAI == 2_500_000.0
    assert profile.liquidation_demand.mode == "empirical_hurdle_count"
    assert profile.market.mode == "empirical_block_bootstrap"
    assert profile.bundle.base_bundle.simulation_config.oracle_delay_steps == 0


def test_design_owns_only_registered_treatments() -> None:
    design = _design()
    assert design.recovery_paths == RECOVERY_PATH_ORDER
    assert design.capacities == CAPACITY_ORDER
    assert design.confidence_scenarios == EXPECTED_SCENARIO_ORDER
    assert design.replications == 128
    assert design.total_hours == 768
    assert design.pre_shock_hours == 48
    assert design.post_shock_hours == 720


def test_cell_registry_is_exact_and_deterministically_ordered() -> None:
    cells = build_cell_registry(_design())
    assert len(cells) == 24
    assert len({cell.identifier for cell in cells}) == 24
    assert [cell.order for cell in cells] == list(range(1, 25))
    assert [cell.identifier for cell in cells[:4]] == [
        f"persistent_trough__capacity_14__{scenario}"
        for scenario in EXPECTED_SCENARIO_ORDER
    ]
    assert cells[-1].identifier == "full_week__capacity_45__confidence_fragile"


def test_every_cell_uses_direct_cost_only_and_shared_registered_capacity() -> None:
    design = _design()
    cells = build_cell_registry(design)
    assert {cell.capacity for cell in cells} == {14, 26, 45}
    assert {cell.capacity_profile for cell in cells} == set(CAPACITY_ORDER)
    payload = specification_payload(design)
    assert payload["capacity"]["hurdle_profile"] == "direct_cost_only"
    assert payload["capacity"]["risk_cost_rate"] == 0.0
    assert payload["capacity"]["semantics"] == "system_wide_shared_capacity"
    assert payload["capacity"]["selected_profile"] is None


def test_controlled_paths_preserve_registered_shock_and_checksums() -> None:
    paths = build_paths(_design())
    assert set(paths) == {"persistent_trough", "full_week"}
    assert {
        identifier: path_checksum(values)
        for identifier, values in paths.items()
    } == EXPECTED_PATH_CHECKSUMS
    assert EXPECTED_SHOCK_CHECKSUM == (
        "f7370b9f2faa6c2e97ca5dddf7b28d3ccfa109ee52f635d9ff43a8893f683ea5"
    )
    assert all(np.array_equal(values[:48], np.full(48, 2000.0)) for values in paths.values())
    assert {values[48] for values in paths.values()} == {1140.0}


def test_persistent_and_full_week_endpoints_are_exact() -> None:
    paths = build_paths(_design())
    assert np.all(paths["persistent_trough"][48:] == 1140.0)
    assert paths["full_week"][48 + 168] == pytest.approx(2000.0)
    assert np.allclose(paths["full_week"][48 + 168 :], 2000.0)
    assert (np.diff(paths["full_week"][48:]) >= -1e-12).all()
    assert paths["full_week"].max() == 2000.0


def test_seed_registry_is_treatment_invariant_and_stream_specific() -> None:
    record = seed_record(11)
    assert record == seed_record(11)
    seeds = [record[f"{stream}_seed"] for stream in SEED_STREAMS]
    assert len(set(seeds)) == len(SEED_STREAMS)
    assert record != seed_record(12)
    assert seed_registry_checksum(128) == seed_registry_checksum(128)
    with pytest.raises(ValueError, match="Unknown"):
        derive_seed(0, "treatment")


def test_demand_decision_uses_attempt_budget_as_authoritative_capacity_count() -> None:
    decision = _demand_decision(
        step=3,
        inventory=100,
        capacity=14,
        uniform=0.0,
        positive_count=82,
        hurdle_probability=1.0,
    )
    assert decision.sampled_demand == 82
    assert decision.bounded_demand == 82
    assert decision.attempt_budget == 14
    assert decision.demand_truncated_by_capacity == 68
    assert decision.attempt_budget <= decision.keeper_capacity


def test_demand_audit_rows_cannot_create_attempts_when_hurdle_is_inactive() -> None:
    decision = _demand_decision(
        step=2,
        inventory=40,
        capacity=14,
        uniform=0.9,
        positive_count=20,
        hurdle_probability=0.1,
    )
    assert decision.sampled_demand == 0
    assert decision.attempt_budget == 0
    assert decision.demand_inactive_unresolved == 40


def test_vault_pairing_reports_avoided_additional_debt_and_delay() -> None:
    persistent = {
        1: {
            "first_successful_closure_hour": 50,
            "initial_debt_dai": 100.0,
        },
        2: {
            "first_successful_closure_hour": None,
            "initial_debt_dai": 200.0,
        },
        3: {
            "first_successful_closure_hour": 60,
            "initial_debt_dai": 300.0,
        },
    }
    full = {
        1: {
            "first_successful_closure_hour": None,
            "initial_debt_dai": 100.0,
        },
        2: {
            "first_successful_closure_hour": 55,
            "initial_debt_dai": 200.0,
        },
        3: {
            "first_successful_closure_hour": 66,
            "initial_debt_dai": 300.0,
        },
    }
    row = _pair_vault_events(
        replication=0,
        capacity_profile=CAPACITY_ORDER[0],
        capacity=14,
        confidence_scenario="stage1_only",
        persistent=persistent,
        full=full,
    )
    assert row["paired_liquidations_avoided"] == 1
    assert row["paired_additional_liquidations"] == 1
    assert row["paired_avoided_debt_dai"] == 100.0
    assert row["paired_additional_debt_dai"] == 200.0
    assert row["closure_time_difference_mean"] == 6.0


def test_vault_pairing_rejects_mismatched_identifiers() -> None:
    with pytest.raises(ValueError, match="identifiers"):
        _pair_vault_events(
            replication=0,
            capacity_profile=CAPACITY_ORDER[0],
            capacity=14,
            confidence_scenario="stage1_only",
            persistent={1: {}},
            full={2: {}},
        )


def test_recovery_counter_resets_and_restricted_mean_is_censored() -> None:
    base = _design().recovery_design
    prices = np.full(720, 0.99)
    prices[1:11] = 1.0
    prices[12:36] = 1.0
    metrics = _recovery_metrics(prices, design=base)
    assert metrics["first_return_time"] == 1
    assert metrics["failed_recovery_attempts"] == 1
    assert metrics["sustained_recovery_time"] == 36
    censored = _recovery_metrics(np.full(720, 0.99), design=base)
    assert censored["restricted_mean_recovery_time"] == 720
    assert censored["right_censored"] == 1


def test_distribution_reports_paired_uncertainty_and_zero_mass() -> None:
    result = _distribution([0.0, 0.0, 2.0, 2.0])
    assert result["mean"] == 1.0
    assert result["median"] == 1.0
    assert result["positive_share"] == 0.5
    assert result["ci95_lower"] < result["mean"] < result["ci95_upper"]


def _contrast_frame() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    paired = []
    metrics = (
        "backlog_area_dai_hours",
        "maximum_unresolved_tab_dai",
        "cumulative_realised_bad_debt_dai",
        "below_peg_burden",
        "restricted_mean_recovery_time",
    )
    for path in RECOVERY_PATH_ORDER:
        for profile in CAPACITY_ORDER:
            capacity = CAPACITY_VALUES[profile]
            for scenario in EXPECTED_SCENARIO_ORDER:
                for replication in range(4):
                    row = {
                        "recovery_path": path,
                        "capacity_profile": profile,
                        "capacity": capacity,
                        "confidence_scenario": scenario,
                        "replication": replication,
                    }
                    for metric in metrics:
                        row[metric] = (
                            float(100 - capacity + replication)
                            - (10.0 if path == "full_week" else 0.0)
                        )
                    rows.append(row)
                if path == RECOVERY_PATH_ORDER[0]:
                    for replication in range(4):
                        paired.append(
                            {
                                "replication": replication,
                                "capacity_profile": profile,
                                "capacity": capacity,
                                "confidence_scenario": scenario,
                                "paired_liquidations_avoided": 1,
                                "paired_additional_liquidations": 0,
                                "paired_avoided_debt_dai": 1000.0,
                                "paired_additional_debt_dai": 0.0,
                                "closure_time_difference_mean": 2.0,
                            }
                        )
    frame = pd.DataFrame(rows)
    # The implementation supports every registered summary metric.
    from dai_sim.experiments.constrained_eth_recovery import SUMMARY_METRICS

    for metric in SUMMARY_METRICS:
        if metric not in frame:
            frame[metric] = 0.0
    return frame, pd.DataFrame(paired)


def test_recovery_contrasts_preserve_full_minus_persistent_sign() -> None:
    frame, paired = _contrast_frame()
    result = recovery_contrasts(frame, paired)
    row = result.loc[
        result["capacity"].eq(14)
        & result["confidence_scenario"].eq("stage1_only")
        & result["metric"].eq("backlog_area_dai_hours")
    ].iloc[0]
    assert row["mean"] == -10.0
    avoided = result.loc[
        result["capacity"].eq(14)
        & result["confidence_scenario"].eq("stage1_only")
        & result["metric"].eq("paired_avoided_debt_dai")
    ].iloc[0]
    assert avoided["mean"] == 1000.0


def test_capacity_contrasts_preserve_ordered_mathematical_sign() -> None:
    frame, _ = _contrast_frame()
    result = capacity_contrasts(frame)
    row = result.loc[
        result["recovery_path"].eq("full_week")
        & result["confidence_scenario"].eq("stage1_only")
        & result["capacity_contrast"].eq("45 - 14")
        & result["metric"].eq("backlog_area_dai_hours")
    ].iloc[0]
    assert row["mean"] == -31.0


def test_specification_is_result_blind_and_forbids_selection() -> None:
    payload = specification_payload(_design())
    assert payload["result_blind"] is True
    assert payload["substantive_simulations"] == 3072
    assert payload["confidence"]["primary"] == "stage1_only"
    assert payload["confidence"]["ranked"] is False
    assert payload["confidence"]["selected"] is None
    assert payload["final_validation_data_used"] is False
    assert payload["usdc_svb_used"] is False
    assert payload["multi_collateral_execution"] is False
    assert payload["runtime_adopted"] is False


def test_scientific_identity_is_deterministic_and_parent_bound() -> None:
    design = _design()
    assert experiment_identity(design) == experiment_identity(design)
    assert len(experiment_identity(design)) == 64
    assert specification_payload(design)["starting_code_parent"] == (
        "ffb6c65cd1d57e1aa49b1e5b4dc77da1c212fcef"
    )


def test_preflight_confirms_storage_profiles_and_protected_inputs() -> None:
    result = preflight(_design())
    assert result["cell_count"] == 24
    assert result["simulation_count"] == 3072
    assert result["minimum_free_storage_satisfied"] is True
    assert result["free_storage_bytes"] >= 10 * 1024**3
    assert result["runtime_adopted"] is False


def test_registered_materiality_thresholds_are_fixed_and_positive() -> None:
    materiality = _design().materiality
    assert materiality == {
        "paired_avoided_debt_dai": 1000.0,
        "backlog_area_dai_hours": 10000.0,
        "maximum_unresolved_tab_dai": 1000.0,
        "below_peg_burden": 0.01,
        "restricted_mean_recovery_time_hours": 24.0,
    }
    assert all(value > 0 for value in materiality.values())


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, "not_supported"),
        (1, "partially_supported"),
        (2, "supported"),
        (3, "supported"),
    ],
)
def test_hypothesis_support_count_branches(count: int, expected: str) -> None:
    assert _support_classification(count) == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"invalid": True}, "constrained_recovery_experiment_invalid"),
        ({"low_operational": False}, "constrained_recovery_not_operational"),
        (
            {"h5a": "partially_supported", "h5c": "present"},
            "recovery_effect_capacity_dependent",
        ),
        (
            {"h5a": "supported", "h5b": "not_supported"},
            "recovery_improves_solvency_not_peg",
        ),
        (
            {"h5a": "supported", "h5b": "supported"},
            "recovery_matters_under_constrained_execution",
        ),
        (
            {
                "h5a": "not_supported",
                "h5b": "not_supported",
                "capacity_mechanism": "capacity_effect_mixed",
            },
            "capacity_dominates_recovery",
        ),
        ({}, "no_clear_constrained_recovery_effect"),
    ],
)
def test_overall_classification_hierarchy(
    overrides: dict[str, object], expected: str
) -> None:
    arguments = {
        "invalid": False,
        "low_operational": True,
        "opportunity": True,
        "h5a": "not_supported",
        "h5b": "partially_supported",
        "h5c": "not_present",
        "capacity_mechanism": "no_clear_capacity_effect",
    }
    arguments.update(overrides)
    assert _overall_classification(**arguments) == expected


def test_configuration_cannot_silently_add_a_path(tmp_path) -> None:
    source = _design().config_path
    payload = source.read_text(encoding="utf-8").replace(
        "    - order: 2\n      identifier: full_week",
        "    - order: 2\n      identifier: partial_week\n      sha256: bad\n"
        "    - order: 3\n      identifier: full_week",
    )
    changed = tmp_path / "changed.yaml"
    changed.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="Recovery paths"):
        load_design(changed)


def test_configuration_cannot_activate_a_positive_hurdle(tmp_path) -> None:
    source = _design().config_path
    payload = source.read_text(encoding="utf-8").replace(
        "risk_cost_rate: 0.0", "risk_cost_rate: 0.01"
    )
    changed = tmp_path / "changed.yaml"
    changed.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="Keeper treatment"):
        load_design(changed)


def test_configuration_cannot_change_capacity(tmp_path) -> None:
    source = _design().config_path
    payload = source.read_text(encoding="utf-8").replace(
        "value: 14", "value: 15", 1
    )
    changed = tmp_path / "changed.yaml"
    changed.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="capacity"):
        load_design(changed)
