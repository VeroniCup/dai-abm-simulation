"""Substantive tests for dormant conditional-event simulation."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dai_sim.calibration.event_simulation import (
    EXPECTED_RESIDUAL_BLOCK_SHA256,
    EXPECTED_RESIDUAL_SEQUENCE_SHA256,
    ConditionalEventInput,
    ConditionalEventPath,
    bad_debt_sensitivity_flags,
    build_conditional_initial_state,
    default_event_config,
    derive_common_maximum_horizon,
    initial_state_summary,
    liquidation_pressure_state,
    material_active_bad_debt,
    material_bad_debt_tolerance,
    prepare_event_path,
    simulate_conditional_event,
)
from dai_sim.calibration.market import ResidualBlockSource
from dai_sim.calibration.simulated_moments import (
    StructuralParameters,
    select_event_smoke_subset,
)


def _catalogue() -> pd.DataFrame:
    rows = []
    for position in range(74):
        rows.append(
            {
                "event_id": f"calibration__202001{position:04d}",
                "partition": "calibration",
                "event_duration_hours": 24 + position,
                "first_six_hour_burden": float(position // 2),
            }
        )
    rows.append(
        {
            "event_id": "final_stress_validation__20230311T000000Z",
            "partition": "final_stress_validation",
            "event_duration_hours": 52,
            "first_six_hour_burden": 1.0,
        }
    )
    return pd.DataFrame(rows)


def _short_config():
    config = default_event_config(_catalogue())
    return replace(config, maximum_event_horizon_hours=72)


def _short_path() -> ConditionalEventPath:
    timestamps = tuple(pd.date_range("2020-01-01", periods=72, freq="h", tz="UTC"))
    eth = tuple(np.r_[np.full(48, 200.0), np.linspace(200.0, 150.0, 24)])
    return ConditionalEventPath(
        event=ConditionalEventInput(
            event_id="calibration__synthetic",
            partition="calibration",
            onset_timestamp_utc=timestamps[48],
            observed_event_duration_hours=0,
            initial_peg_gap=0.006,
            eth_recovery_24h=-0.05,
        ),
        timestamps=timestamps,
        observed_eth_prices=eth,
        starting_dai_price=1.0,
        onset_position=48,
        minimum_evaluation_end_position=71,
        maximum_end_position=71,
        observed_dai_values_after_start_used=False,
    )


def _stage1_owner() -> dict[str, object]:
    values = np.r_[np.full(24, -0.0001), np.full(24, 0.0001)]
    return {
        "below_peg_response": 0.2,
        "above_peg_response": 0.1,
        "source": ResidualBlockSource(
            timestamps=tuple(
                pd.date_range("2019-01-01", periods=48, freq="h", tz="UTC")
            ),
            centred_residuals=values,
            block_indices=(tuple(range(24)), tuple(range(24, 48))),
            run_lengths=(48,),
            mean_before_centring=0.0,
        ),
        "residual_sequence_sha256": EXPECTED_RESIDUAL_SEQUENCE_SHA256,
        "block_specification_sha256": EXPECTED_RESIDUAL_BLOCK_SHA256,
    }


def test_initial_state_sampling_and_eth_conversion_are_deterministic() -> None:
    arguments = {
        "event_id": "calibration__state",
        "replication": 0,
        "registry_id": "confidence-smm-registry-a",
    }
    first = build_conditional_initial_state(initial_eth_price=200.0, **arguments)
    repeated = build_conditional_initial_state(initial_eth_price=200.0, **arguments)
    repriced = build_conditional_initial_state(initial_eth_price=100.0, **arguments)
    different = build_conditional_initial_state(
        initial_eth_price=200.0,
        **{**arguments, "replication": 1},
    )
    assert first == repeated
    assert first.state_checksum == repriced.state_checksum
    assert first.state_checksum != different.state_checksum
    assert first.total_debt_dai == pytest.approx(2_500_000.0)
    assert sum(first.debt_dai) == pytest.approx(first.total_debt_dai)
    assert all(
        ratio > threshold
        for ratio, threshold in zip(
            first.collateral_ratios, first.liquidation_ratios, strict=True
        )
    )
    first_vaults = first.to_vaults()
    repriced_vaults = repriced.to_vaults()
    assert repriced_vaults[0].collateral_amount == pytest.approx(
        2 * first_vaults[0].collateral_amount
    )
    summary = initial_state_summary(first)
    assert summary["initially_liquidatable_vault_count"] == 0
    assert summary["vault_count"] == 500


def test_liquidation_pressure_and_bad_debt_gates_use_economic_amounts() -> None:
    zero = liquidation_pressure_state(
        unresolved_tab_dai=0.0,
        hourly_cleared_tab_dai=0.0,
        cleared_history=(),
        tolerance=1e-9,
    )
    assert zero.pressure == 0.0
    assert zero.gate_open
    material = liquidation_pressure_state(
        unresolved_tab_dai=5.0,
        hourly_cleared_tab_dai=2.0,
        cleared_history=(3.0, 2.0),
        tolerance=1e-9,
    )
    assert material.pressure == pytest.approx(0.5)
    assert not material.gate_open
    dust = liquidation_pressure_state(
        unresolved_tab_dai=5e-10,
        hourly_cleared_tab_dai=0.0,
        cleared_history=(),
        tolerance=1e-9,
    )
    assert dust.gate_open and dust.pressure == 0.0
    config = _short_config()
    tolerance = material_bad_debt_tolerance(2_500_000.0, config)
    assert tolerance == pytest.approx(2.5e-6)
    assert not material_active_bad_debt(tolerance, tolerance=tolerance)
    assert material_active_bad_debt(tolerance * 2, tolerance=tolerance)
    assert bad_debt_sensitivity_flags(2_501.0, 2_500_000.0) == {
        "active_bad_debt_ratio_above_0_1pct": True,
        "active_bad_debt_ratio_above_1pct": False,
    }


def test_common_horizon_and_smoke_subset_exclude_validation_and_reorder() -> None:
    events = _catalogue()
    maximum = int(events.loc[events.partition.eq("calibration"), "event_duration_hours"].max())
    assert derive_common_maximum_horizon(events) == (
        48 + int(np.ceil((maximum + 24) / 24)) * 24
    )
    first = select_event_smoke_subset(events)
    second = select_event_smoke_subset(events.sample(frac=1.0, random_state=7))
    assert first == second
    assert len(first) == 4
    assert all(identifier.startswith("calibration__") for identifier in first)


def test_event_path_uses_exact_preroll_and_only_starting_observed_dai() -> None:
    config = _short_config()
    onset = pd.Timestamp("2020-01-04T00:00:00Z")
    index = pd.date_range(
        onset - pd.Timedelta(hours=48),
        periods=72,
        freq="h",
    )
    panel = pd.DataFrame(
        {
            "eth_price_usd": np.linspace(200.0, 180.0, len(index)),
            "dai_price_usd": np.linspace(1.0, 0.9, len(index)),
        },
        index=index,
    )
    row = pd.Series(
        {
            "event_id": "calibration__path",
            "partition": "calibration",
            "onset_timestamp_utc": onset,
            "event_duration_hours": 0,
            "initial_peg_gap": 0.006,
            "eth_recovery_24h": 0.0,
        }
    )
    path = prepare_event_path(panel=panel, event_row=row, config=config)
    assert path.onset_position == 48
    assert len(path.timestamps) == 72
    assert path.starting_dai_price == 1.0
    assert not path.observed_dai_values_after_start_used
    assert path.timestamps[48] == onset


def test_dormant_loop_is_deterministic_and_has_no_future_dai_owner() -> None:
    parameters = StructuralParameters(0.6, 0.3, 0.2, 0.5)
    kwargs = {
        "path": _short_path(),
        "config": _short_config(),
        "structural_parameters": parameters,
        "replication": 0,
        "registry_id": "confidence-smm-registry-a",
        "stage1_owners": _stage1_owner(),
    }
    first = simulate_conditional_event(**kwargs)
    second = simulate_conditional_event(**kwargs)
    assert first.diagnostics.result_checksum == second.diagnostics.result_checksum
    assert first.metrics == second.metrics
    assert not first.diagnostics.observed_future_dai_used
    assert first.diagnostics.simulated_hours == 72
    assert first.diagnostics.event_hours == 24
    assert all(0.0 <= step.confidence <= 1.0 for step in first.steps)
    assert all(step.unresolved_tab_dai >= 0.0 for step in first.steps)
    altered = simulate_conditional_event(**{**kwargs, "replication": 1})
    assert first.diagnostics.market_seed != altered.diagnostics.market_seed
    assert first.diagnostics.vault_seed != altered.diagnostics.vault_seed
    assert first.diagnostics.liquidation_seed != altered.diagnostics.liquidation_seed
    assert first.diagnostics.result_checksum != altered.diagnostics.result_checksum


def test_production_simulation_has_no_event_simulation_import() -> None:
    source = Path("src/dai_sim/model/simulation.py").read_text(encoding="utf-8")
    assert "calibration.event_simulation" not in source
    assert "PersistentConfidenceConfig" not in source
