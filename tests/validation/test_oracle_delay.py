"""Oracle-delay semantic and Experiment E readiness tests."""

from __future__ import annotations

from dai_sim.experiments.final.programme import load_programme
from dai_sim.inputs.oracle_delay import load_oracle_delay_registry
from dai_sim.validation.oracle_delay import (
    EXPECTED_PROGRAMME_IDENTITY,
    resolve_experiment_e_cells,
    validate_experiment_e_readiness,
    validate_parameter_semantics,
)


def test_parameter_semantics_match_existing_global_price_lag() -> None:
    semantics = validate_parameter_semantics()
    assert semantics["passed"] is True
    assert semantics["step_duration_hours"] == 1
    assert semantics["scope"] == (
        "global across ETH, BTC and STABLE collateral families"
    )
    assert semantics["delayed_object"] == "protocol-observed collateral price path"
    assert semantics["initial_buffer"] == (
        "repeat first market price for the first delay_steps"
    )
    assert semantics["market_prices_contemporaneous"] is True


def test_six_master_rows_resolve_without_changing_programme() -> None:
    programme = load_programme()
    registry = load_oracle_delay_registry()
    cells = resolve_experiment_e_cells(programme, registry)
    assert programme.programme_identity == EXPECTED_PROGRAMME_IDENTITY
    assert len(programme.cells) == 43
    assert programme.planned_core_simulations == 5_504
    assert len(cells) == 6
    assert {cell.replication_count for cell in cells} == {128}
    assert sum(cell.replication_count for cell in cells) == 768
    assert [cell.oracle_delay_steps for cell in cells] == [0, 1, 2, 0, 1, 2]
    assert all(cell.master_row_checksum for cell in cells)


def test_experiment_e_is_ready_but_unexecuted() -> None:
    readiness = validate_experiment_e_readiness()
    assert readiness["readiness_classification"] == (
        "experiment_e_ready_with_transparent_delay_sensitivity"
    )
    assert readiness["experiment_e_status"] == "ready_but_unexecuted"
    assert readiness["experiment_e_simulations"] == 0
    assert readiness["checkpoints_created"] == 0
    assert readiness["runtime_adopted"] is False
    assert readiness["common_random_number_contract"][
        "sole_treatment_difference"
    ] == "oracle_delay_steps"
