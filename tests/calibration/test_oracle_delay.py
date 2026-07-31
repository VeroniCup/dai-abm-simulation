"""Focused result-blind oracle-delay calibration tests."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from dai_sim.calibration.oracle_delay import (
    calibration_only_mask,
    derive_coordinates,
    direct_sample_sufficient,
    direct_staleness_hours,
    hours_to_steps,
    interval_sample_sufficient,
    normalise_utc_timestamps,
    source_inventory,
    timestamp_diagnostics,
    update_interval_hours,
)


def test_timestamp_parsing_normalises_timezone_and_reports_missingness() -> None:
    values = [
        "2024-01-01 00:00:00",
        "2024-01-01T01:00:00+01:00",
        "not-a-timestamp",
        None,
    ]
    parsed = normalise_utc_timestamps(values)
    assert parsed[0] == pd.Timestamp("2024-01-01T00:00:00Z")
    assert parsed[1] == pd.Timestamp("2024-01-01T00:00:00Z")
    diagnostics = timestamp_diagnostics(values)
    assert diagnostics["missing_timestamp_count"] == 2
    assert diagnostics["duplicate_timestamp_count"] == 1
    assert diagnostics["monotonic_non_decreasing"] is True


def test_direct_staleness_preserves_zero_and_positive_hours() -> None:
    staleness = direct_staleness_hours(
        ["2024-01-01T02:00:00Z", "2024-01-01T03:00:00Z"],
        ["2024-01-01T02:00:00Z", "2024-01-01T01:00:00Z"],
    )
    assert staleness.tolist() == [0.0, 2.0]
    with pytest.raises(ValueError, match="Future-dated"):
        direct_staleness_hours(
            ["2024-01-01T00:00:00Z"],
            ["2024-01-01T01:00:00Z"],
        )


def test_direct_and_interval_sample_sufficiency_are_pre_registered() -> None:
    timestamps = pd.date_range("2024-01-01", periods=30, freq="3h", tz="UTC")
    sufficient = [0.0] * 20 + [1.0] * 10
    assert direct_sample_sufficient(sufficient, timestamps)
    assert not direct_sample_sufficient(sufficient[:-1], timestamps[:-1])
    intervals = update_interval_hours(timestamps[:21])
    assert len(intervals) == 20
    assert interval_sample_sufficient(intervals, timestamps[:21])
    assert not interval_sample_sufficient(intervals[:-1], timestamps[:20])


def test_update_intervals_deduplicate_before_differencing() -> None:
    intervals = update_interval_hours(
        [
            "2024-01-01T00:00:00Z",
            "2024-01-01T00:00:00Z",
            "2024-01-01T02:00:00Z",
            "2024-01-01T05:00:00Z",
        ]
    )
    assert intervals.tolist() == [2.0, 3.0]


def test_all_four_coordinate_derivations_are_deterministic() -> None:
    direct = derive_coordinates(
        1, positive_staleness_hours=[0.5, 1.0, 1.5, 2.0]
    )
    assert (direct.low_steps, direct.central_steps, direct.high_steps) == (
        0,
        2,
        3,
    )
    intervals = derive_coordinates(2, update_intervals=[2.0, 4.0, 6.0])
    assert (intervals.low_steps, intervals.central_steps, intervals.high_steps) == (
        0,
        2,
        6,
    )
    documented = derive_coordinates(3, documented_delay_hours=Decimal("1.25"))
    assert (
        documented.low_steps,
        documented.central_steps,
        documented.high_steps,
    ) == (0, 2, 3)
    fallback = derive_coordinates(4)
    assert (
        fallback.low_steps,
        fallback.central_steps,
        fallback.high_steps,
    ) == (0, 1, 2)
    assert fallback.source_classification == (
        "transparent_sensitivity_not_empirically_identified"
    )


def test_deterministic_ceiling_and_invalid_delays() -> None:
    assert hours_to_steps(Decimal("1.0001"), Decimal("1")) == 2
    with pytest.raises(ValueError, match="lag buffer"):
        derive_coordinates(3, documented_delay_hours=500)
    with pytest.raises(ValueError, match="positive"):
        derive_coordinates(3, documented_delay_hours=0)


def test_held_out_intervals_are_excluded() -> None:
    mask = calibration_only_mask(
        [
            "2022-10-31T23:00:00Z",
            "2022-11-01T00:00:00Z",
            "2023-03-10T00:00:00Z",
            "2023-03-20T00:00:00Z",
        ]
    )
    assert mask.tolist() == [True, False, False, True]


def test_repository_source_inventory_supports_only_tier_four() -> None:
    rows = source_inventory()
    assert len(rows) == 7
    assert all(
        not str(row["eligibility_decision"]).startswith("eligible")
        for row in rows
    )
    by_identifier = {row["source_identifier"]: row for row in rows}
    assert by_identifier["osm_hop_schema_metadata"]["observation_count"] == 0
    assert by_identifier["hourly_market_reference_panel"]["held_out"] is True
    assert by_identifier["historical_oracle_experiment_manifest"][
        "eligibility_decision"
    ] == "excluded_result_generated"
