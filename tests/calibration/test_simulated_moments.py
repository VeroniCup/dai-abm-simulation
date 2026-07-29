"""Deterministic confidence simulated-moments infrastructure tests."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from dai_sim.calibration.market import (
    build_residual_block_source,
    fit_stage1_coefficients,
    sample_residual_blocks,
)
from dai_sim.calibration.simulated_moments import (
    PANIC_RESPONSE_UPPER_BOUND,
    StructuralParameters,
    boundary_model_descriptions,
    build_event_catalogue,
    derive_seed,
    moment_objective,
    select_search_events,
    sobol_candidates,
    structural_to_transformed,
    transformed_to_structural,
)


def _hourly(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "dai_price_usd": prices,
            "eth_log_return": np.zeros(len(prices)),
        },
        index=pd.date_range("2020-01-01", periods=len(prices), freq="h", tz="UTC"),
    )


def test_event_start_completion_first_return_and_identifier_are_semantic() -> None:
    prices = [1.0] * 24 + [0.994, 0.996, 0.994] + [1.0] * 24
    events = build_event_catalogue(_hourly(prices))
    assert len(events) == 1
    row = events.iloc[0]
    assert row["onset_timestamp_utc"] == pd.Timestamp("2020-01-02T00:00:00Z")
    assert row["first_return_timestamp_utc"] == pd.Timestamp(
        "2020-01-02T01:00:00Z"
    )
    assert row["stable_run_start_timestamp_utc"] == pd.Timestamp(
        "2020-01-02T03:00:00Z"
    )
    assert row["failed_recovery_attempts"] == 1
    assert row["event_id"] == "calibration__20200102T000000Z"


def test_joint_stage1_fit_has_no_intercept_and_non_negative_coefficients() -> None:
    sample = pd.DataFrame(
        {
            "below_peg_gap": [0.01, 0.02, 0.0, 0.0],
            "above_peg_gap": [0.0, 0.0, 0.01, 0.02],
            "next_hour_change": [0.002, 0.004, -0.001, -0.002],
        }
    )
    result = fit_stage1_coefficients(sample)
    assert result["below_peg_response"] == pytest.approx(0.2)
    assert result["above_peg_response"] == pytest.approx(0.1)


def test_residual_blocks_never_cross_ineligible_hour() -> None:
    index = pd.DatetimeIndex(
        list(pd.date_range("2020-01-01", periods=30, freq="h", tz="UTC"))
        + list(pd.date_range("2020-01-03", periods=30, freq="h", tz="UTC"))
    )
    sample = pd.DataFrame(
        {
            "next_hour_change": np.linspace(-0.01, 0.01, 60),
            "below_peg_gap": np.zeros(60),
            "above_peg_gap": np.zeros(60),
        },
        index=index,
    )
    source = build_residual_block_source(
        sample, below_peg_response=0.2, above_peg_response=0.1
    )
    assert source.run_lengths == (30, 30)
    assert len(source.block_indices) == 14
    for block in source.block_indices:
        times = [source.timestamps[position] for position in block]
        assert times[-1] - times[0] == pd.Timedelta(hours=23)
    first = sample_residual_blocks(
        source, block_count=2, rng=np.random.default_rng(9)
    )
    second = sample_residual_blocks(
        source, block_count=2, rng=np.random.default_rng(9)
    )
    np.testing.assert_array_equal(first, second)


def test_parameter_transform_round_trip_and_boundary_descriptions() -> None:
    parameters = StructuralParameters(0.8, 0.3, 0.2, 1.1)
    transformed = structural_to_transformed(parameters)
    recovered = transformed_to_structural(transformed)
    assert recovered.deterioration_adjustment == pytest.approx(
        parameters.deterioration_adjustment
    )
    assert recovered.recovery_adjustment == pytest.approx(
        parameters.recovery_adjustment
    )
    assert recovered.confidence_floor == pytest.approx(
        parameters.confidence_floor
    )
    assert recovered.panic_response == pytest.approx(parameters.panic_response)
    assert set(boundary_model_descriptions()) == {
        "panic_response_zero",
        "confidence_floor_zero",
        "equal_adjustment_rates",
        "instantaneous_deterioration_target",
    }
    with pytest.raises(ValueError, match="Boundary"):
        structural_to_transformed(StructuralParameters(1.0, 0.3, 0.2, 1.1))


def test_objective_is_order_invariant_and_group_balanced() -> None:
    names = [f"{group}{position}" for group in "ABCD" for position in (1, 2)]
    empirical = {name: 0.0 for name in names}
    simulated = {name: 1.0 for name in reversed(names)}
    scales = {name: 1.0 for name in names}
    groups = {name: name[0] for name in names}
    weights = {name: 1.0 for name in names}
    first = moment_objective(
        simulated=simulated,
        empirical=empirical,
        scales=scales,
        groups=groups,
        within_group_weights=weights,
    )
    second = moment_objective(
        simulated=dict(reversed(list(simulated.items()))),
        empirical=dict(reversed(list(empirical.items()))),
        scales=scales,
        groups=groups,
        within_group_weights=weights,
    )
    assert first == second
    assert first.total_objective == 1.0
    assert first.group_contributions == {group: 0.25 for group in "ABCD"}
    assert max(first.concentration_diagnostics["effective_total_weights"].values()) == 0.125


def test_cryptographic_seeds_own_event_replication_and_stream() -> None:
    base = derive_seed(
        registry_id="a",
        event_id="event",
        replication=0,
        stream_name="vault_sampling",
    )
    assert base == derive_seed(
        registry_id="a",
        event_id="event",
        replication=0,
        stream_name="vault_sampling",
    )
    variants = {
        derive_seed(
            registry_id=registry,
            event_id=event,
            replication=replication,
            stream_name=stream,
        )
        for registry, event, replication, stream in (
            ("b", "event", 0, "vault_sampling"),
            ("a", "other", 0, "vault_sampling"),
            ("a", "event", 1, "vault_sampling"),
            ("a", "event", 0, "market_innovations"),
        )
    }
    assert base not in variants
    assert len(variants) == 4


def test_search_subset_is_stable_under_row_reordering() -> None:
    rows = []
    for position in range(40):
        rows.append(
            {
                "event_id": f"calibration__2020{position:04d}",
                "partition": "calibration",
                "calendar_year": 2020 + position % 2,
                "maximum_six_hour_burden": position + 1.0,
                "event_eth_downside": (position * 7) % 41,
                "recovery_completion_hours": (position * 11) % 43 + 1,
            }
        )
    frame = pd.DataFrame(rows)
    selected = select_search_events(frame)
    reordered = select_search_events(frame.sample(frac=1.0, random_state=5))
    assert len(selected) == 32
    assert selected == reordered


def test_sobol_design_is_deterministic_and_inside_structural_bounds() -> None:
    transformed, candidates = sobol_candidates()
    again, repeated = sobol_candidates()
    np.testing.assert_array_equal(transformed, again)
    assert len(candidates) == 256
    assert candidates == repeated
    for candidate in candidates:
        assert 0 < candidate.recovery_adjustment <= candidate.deterioration_adjustment <= 1
        assert 0 <= candidate.confidence_floor < 1
        assert 0 <= candidate.panic_response <= PANIC_RESPONSE_UPPER_BOUND
    assert hashlib.sha256(np.asarray(transformed, dtype="<f8").tobytes()).hexdigest()
