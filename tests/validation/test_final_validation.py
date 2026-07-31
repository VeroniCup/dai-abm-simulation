"""Focused tests for frozen-model final held-out validation."""

from __future__ import annotations

import inspect

import pytest

from dai_sim.validation import final_validation as validation


def test_window_inventory_prevents_ftx_double_counting() -> None:
    inventory = validation.window_inventory()
    assert inventory["identifier"].tolist() == [
        "quiet",
        "november_2022_generalisation_ftx_holdout",
        "usdc_svb",
    ]
    quiet = inventory.iloc[0]
    assert quiet["decision"] == "quiet_validation_not_separately_registered"
    assert quiet["start_utc"] is None
    assert len(inventory.loc[inventory["identifier"].str.contains("november_2022")]) == 1


def test_exact_held_out_windows_and_stage_order() -> None:
    assert validation._window_bounds("ftx") == (
        validation.pd.Timestamp("2022-11-01T00:00:00Z"),
        validation.pd.Timestamp("2022-11-21T00:00:00Z"),
    )
    assert validation._window_bounds("usdc_svb") == (
        validation.pd.Timestamp("2023-03-06T00:00:00Z"),
        validation.pd.Timestamp("2023-03-20T00:00:00Z"),
    )
    assert validation.STAGE_ORDER == ("quiet", "ftx", "usdc_svb")
    ftx_start, ftx_end = validation._window_bounds("ftx")
    usdc_start, usdc_end = validation._window_bounds("usdc_svb")
    assert ftx_end <= usdc_start or usdc_end <= ftx_start


def test_historical_paths_have_exact_complete_coverage() -> None:
    assert len(validation._historical_window("ftx")) == 480
    assert len(validation._historical_window("usdc_svb")) == 336
    assert validation.load_registry()["historical_source"]["sha256"] == (
        "86ed2ac5a5d364cc57e8b41e137ef369a0fce7a393d386b4b38fc1ebd1be0545"
    )


def test_observed_dai_is_target_only_and_no_overlay_exists() -> None:
    owner = validation.load_registry()["simulation"]
    assert owner["observed_dai_role"] == "comparison_target_only"
    assert owner["synthetic_shock_overlay"] is False
    source = inspect.getsource(validation.simulate_replication)
    assert "dai_price_usd" not in source
    assert "calibrate" not in source
    assert validation.load_registry()["simulation"]["keeper_hurdle"] == (
        "direct_cost_only"
    )
    assert validation.load_registry()["simulation"]["oracle_delay_hours"] == 0


def test_usdc_negative_control_portfolio_has_no_stable_exposure() -> None:
    states = validation.experiment_a.initialise_nested_portfolios(7_100_000)
    empirical = states["empirical_crypto"].sampled
    assert not empirical["family"].eq("STABLE").any()
    assert states["stable_supported"].sampled["family"].eq("STABLE").any()


@pytest.mark.parametrize(
    ("ftx", "usdc", "valid", "stages", "expected"),
    [
        ("ftx_validation_directionally_consistent", "usdc_svb_validation_partially_consistent", True, 2, "final_validation_supportive_with_limitations"),
        ("ftx_validation_directionally_consistent", "usdc_svb_stable_channel_underactive", True, 2, "final_validation_mixed"),
        ("ftx_validation_directionally_consistent", "usdc_svb_mixed", True, 2, "final_validation_mixed"),
        ("ftx_validation_overstates_stress", "usdc_svb_understates_contagion", True, 2, "final_validation_not_supportive"),
        ("ftx_validation_directionally_consistent", "usdc_svb_mixed", True, 1, "final_validation_not_fully_operational"),
        ("ftx_validation_directionally_consistent", "usdc_svb_mixed", False, 2, "final_validation_invalid"),
    ],
)
def test_final_decision_branches(
    ftx: str,
    usdc: str,
    valid: bool,
    stages: int,
    expected: str,
) -> None:
    assert validation.classify_final(
        ftx,
        usdc,
        valid=valid,
        operational_stages=stages,
    ) == expected


def test_workflow_has_no_calibration_or_update_operation() -> None:
    owner = validation.load_registry()
    assert owner["workflow_operations"] == [
        "inventory",
        "freeze",
        "quiet",
        "ftx",
        "usdc-svb",
        "reconstruct",
        "all",
    ]
    assert owner["forbidden_operations"] == [
        "calibrate",
        "update_parameters",
        "add_scenario",
        "retune",
    ]
    assert "update_parameter" not in dir(validation)
    assert "calibrate" not in dir(validation)


def test_usdc_stage_is_gated_by_frozen_ftx_evidence(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(validation, "EVIDENCE_DIR", tmp_path)
    (tmp_path / validation.COMPACT_FILENAMES[2]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="FTX evidence must be frozen"):
        validation._stage_gate("usdc_svb")


def test_validation_compact_schema_is_exact() -> None:
    assert validation.COMPACT_FILENAMES == (
        "final_validation_specification.json",
        "final_validation_window_inventory.csv",
        "final_validation_freeze.json",
        "final_validation_quiet_summary.json",
        "final_validation_ftx_summary.json",
        "final_validation_usdc_svb_summary.json",
        "final_validation_metric_comparison.csv",
        "final_validation_decision.json",
        "no_retuning_decision.json",
        "final_validation_reproducibility.json",
        "final_validation_benchmark.json",
    )


def test_stable_attribution_is_collected_without_entering_comparison_metrics() -> None:
    simulated = validation.load_registry()["metrics"]["simulated"]
    assert "stable_liquidated_debt" not in simulated
    source = inspect.getsource(validation.simulate_replication)
    assert '"stable_initial_debt_exposure"' in source
    assert '"stable_liquidated_debt"' in source
    assert '"stable_backlog_area"' in source


def test_validation_registry_freezes_no_retuning_declaration() -> None:
    assert validation.load_registry()["no_retuning_declaration"] == (
        "Validation findings are evaluative. Unfavourable results are retained "
        "as limitations and do not trigger model retuning."
    )


def _distribution(mean: float) -> dict[str, float]:
    return {"mean": mean}


@pytest.mark.parametrize(
    ("unsafe", "eligible", "completed", "backlog", "expected"),
    [
        (0.0, 0.0, 0.0, 0.0, "ftx_validation_understates_stress"),
        (0.1, 1.0, 0.0, 0.0, "ftx_validation_partially_consistent"),
        (0.1, 1.0, 1.0, 0.0, "ftx_validation_directionally_consistent"),
        (0.1, 1.0, 0.0, 0.1, "ftx_validation_directionally_consistent"),
    ],
)
def test_ftx_classification_is_result_blind_and_predefined(
    unsafe: float,
    eligible: float,
    completed: float,
    backlog: float,
    expected: str,
) -> None:
    observed = {"eth_window_log_return": -0.1, "wbtc_window_log_return": -0.1}
    simulated = {
        "unsafe_vault_share": _distribution(unsafe),
        "eligible_liquidation_tab": _distribution(eligible),
        "completed_liquidations": _distribution(completed),
        "backlog_area_share": _distribution(backlog),
    }
    assert validation.classify_ftx_validation(
        observed=observed,
        simulated=simulated,
    ) == expected


@pytest.mark.parametrize(
    ("control", "exposure", "liquidated", "backlog", "expected"),
    [
        (False, 1.0, 1.0, 0.0, "usdc_svb_invalid"),
        (True, 0.0, 0.0, 0.0, "usdc_svb_not_operational"),
        (True, 1.0, 0.0, 0.0, "usdc_svb_stable_channel_underactive"),
        (True, 1.0, 0.0, 0.1, "usdc_svb_validation_partially_consistent"),
        (True, 1.0, 0.1, 0.0, "usdc_svb_validation_directionally_consistent"),
    ],
)
def test_usdc_classification_preserves_underactive_channel(
    control: bool,
    exposure: float,
    liquidated: float,
    backlog: float,
    expected: str,
) -> None:
    primary = {
        "stable_initial_debt_exposure": _distribution(exposure),
        "stable_liquidated_debt": _distribution(liquidated),
        "stable_backlog_area": _distribution(backlog),
    }
    assert validation.classify_usdc_svb_validation(
        negative_control_passed=control,
        stable_supported=primary,
    ) == expected
