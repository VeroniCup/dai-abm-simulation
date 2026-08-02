"""Focused tests for bounded parameter-candidate review."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


from tests.support import REPOSITORY_ROOT
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from dai_sim.calibration.data_loading import validate_protocol_intervals  # noqa: E402
from dai_sim.calibration.validation import (  # noqa: E402
    REVIEW_FIELDS,
    REVIEW_STATUSES,
    _block_length_sensitivity,
    _candidate_review,
    _phase1e_dependencies,
    _review_decision,
    aggregate_activity,
    classify_regime_specification,
    gas_cost_sensitivity,
    hurdle_summary,
    validate_reviewed_registry,
)
from dai_sim.calibration.statistics import estimate_regime_thresholds  # noqa: E402


def _candidate(
    *,
    field: str = "PriceProcessConfig.mu",
    value: float | None = 0.01,
    reference: str = "",
    provenance: str = "empirical_estimation",
) -> dict[str, object]:
    return {
        "simulator_field": field,
        "estimate_name": "test_candidate",
        "estimate_value": value,
        "distribution_reference": reference,
        "units": "per_hour",
        "simulation_frequency": "hourly",
        "collateral_scope": "ETH",
        "regime_scope": "calibration",
        "estimator": "test estimator",
        "input_dataset": "test dataset",
        "input_columns": "value",
        "estimation_window": "calibration excluding FTX",
        "sample_size": 10,
        "uncertainty_measure": {"method": "test"},
        "validation_status": "candidate_validated_for_review",
        "provenance_classification": provenance,
        "implementation_status": "estimated_not_adopted",
        "notes": "",
        "review_required_before_adoption": True,
    }


def _regime_input(rows: int = 100) -> pd.DataFrame:
    values = np.linspace(0.0, 1.0, rows)
    return pd.DataFrame(
        {
            "eth_log_return": -values,
            "wbtc_log_return": -values / 2,
            "realised_crypto_volatility": values,
            "median_effective_gas_price_gwei": values * 100,
            "dai_abs_peg_deviation": values / 100,
            "liquidation_volume_dai": np.where(values > 0.95, 1_000.0, 0.0),
        }
    )


def test_reviewed_registry_preserves_original_candidate_values() -> None:
    original = {"candidates": [_candidate()]}
    frame, reviewed = _candidate_review(original)
    validate_reviewed_registry(original, reviewed)
    assert reviewed["reviewed_candidates"][0]["estimate_value"] == 0.01
    assert frame.loc[0, "original_estimate_value"] == 0.01


def test_candidate_review_status_schema() -> None:
    original = {"candidates": [_candidate()]}
    _, reviewed = _candidate_review(original)
    result = reviewed["reviewed_candidates"][0]
    assert REVIEW_FIELDS.issubset(result)
    assert result["review_status"] in REVIEW_STATUSES
    changed = {**reviewed}
    changed["reviewed_candidates"] = [
        {**result, "estimate_value": 999.0}
    ]
    with pytest.raises(ValueError, match="changed original field"):
        validate_reviewed_registry(original, changed)


def test_gas_cost_sensitivity_exclusion_and_missing_are_distinct() -> None:
    frame = pd.DataFrame(
        {
            "gas_price": [0, 10, 20, 30],
            "transaction_gas_cost_usd": [0.0, 1.0, 2.0, 3.0],
            "regime": ["normal", "normal", "stress", "stress"],
        }
    )
    result = gas_cost_sensitivity(frame, seed=11, replications=50)
    retained = result.query(
        "variant == 'retain_observed_zero' and regime == 'all'"
    ).iloc[0]
    excluded = result.query(
        "variant == 'exclude_zero_transactions' and regime == 'all'"
    ).iloc[0]
    missing = result.query(
        "variant == 'zero_as_missing_no_imputation' and regime == 'all'"
    ).iloc[0]
    assert retained["effective_observations"] == 4
    assert excluded["source_rows"] == 3
    assert missing["source_rows"] == 4
    assert missing["effective_observations"] == 3
    assert excluded["median_usd"] == missing["median_usd"]


def test_gas_cost_bootstrap_is_deterministic() -> None:
    frame = pd.DataFrame(
        {
            "gas_price": [10, 20, 30],
            "transaction_gas_cost_usd": [1.0, 2.0, 3.0],
            "regime": ["normal", "stress", "stress"],
        }
    )
    first = gas_cost_sensitivity(frame, seed=7, replications=40)
    second = gas_cost_sensitivity(frame, seed=7, replications=40)
    pd.testing.assert_frame_equal(first, second)


def test_hurdle_decomposition_keeps_arrival_and_severity_separate() -> None:
    result = hurdle_summary(pd.Series([0.0, 0.0, 10.0, 30.0]))
    assert result["activity_probability"] == 0.5
    assert result["unconditional_q90"] == pytest.approx(24.0)
    assert result["conditional_median"] == 20.0


def test_alternative_aggregation_frequencies() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range(
                "2024-01-01", periods=24, freq="h", tz="UTC"
            ),
            "volume": np.ones(24),
        }
    )
    assert len(aggregate_activity(frame, frequency_hours=1, value_column="volume")) == 24
    assert len(aggregate_activity(frame, frequency_hours=6, value_column="volume")) == 4
    daily = aggregate_activity(frame, frequency_hours=24, value_column="volume")
    assert daily.loc[0, "volume"] == 24


def test_regime_sensitivity_does_not_mutate_thresholds() -> None:
    conditions = pd.DataFrame(
        {
            "a": [False, True, True],
            "b": [False, False, True],
            "c": [False, False, True],
        }
    )
    baseline = classify_regime_specification(
        conditions, minimum_conditions=2
    )
    strict = classify_regime_specification(
        conditions, minimum_conditions=3
    )
    removed = classify_regime_specification(
        conditions, minimum_conditions=2, removed_condition="c"
    )
    assert baseline.tolist() == ["normal", "normal", "stress"]
    assert strict.tolist() == ["normal", "normal", "stress"]
    assert removed.tolist() == ["normal", "normal", "stress"]
    assert list(conditions.columns) == ["a", "b", "c"]


def test_ftx_extreme_is_excluded_from_threshold_estimation() -> None:
    calibration = _regime_input()
    expected = estimate_regime_thresholds(calibration)
    ftx = _regime_input(1)
    ftx.loc[:, :] = 1e12
    combined = pd.concat([calibration, ftx], ignore_index=True)
    actual = estimate_regime_thresholds(combined.iloc[:-1])
    assert actual == expected
    assert estimate_regime_thresholds(combined) != expected


def test_block_length_comparison_is_fixed_seed_reproducible() -> None:
    timestamps = pd.date_range(
        "2022-09-15", periods=2_500, freq="h", tz="UTC"
    )
    rng = np.random.default_rng(9)
    hourly = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "eth_log_return": rng.normal(0, 0.01, len(timestamps)),
            "wbtc_log_return": rng.normal(0, 0.008, len(timestamps)),
        }
    )
    hourly["is_calibration"] = ~(
        (hourly["timestamp_utc"] >= pd.Timestamp("2022-11-01", tz="UTC"))
        & (hourly["timestamp_utc"] < pd.Timestamp("2022-11-21", tz="UTC"))
    )
    states = pd.Series(
        np.where(np.arange(len(hourly)) % 20 < 3, "stress", "normal")
    )
    first = _block_length_sensitivity(
        hourly, states, seed=3, replications=2
    )
    second = _block_length_sensitivity(
        hourly, states, seed=3, replications=2
    )
    pd.testing.assert_frame_equal(first, second)
    assert first["block_length_hours"].tolist() == [24, 72, 168, 336]


def test_protocol_interval_consistency() -> None:
    frame = pd.DataFrame(
        {
            "module": ["Vat", "Vat"],
            "ilk": ["ETH-A", "ETH-A"],
            "parameter": ["line", "line"],
            "effective_start_utc": [
                "2024-01-01T00:00:00Z",
                "2024-01-02T00:00:00Z",
            ],
            "effective_end_exclusive_utc": [
                "2024-01-02T00:00:00Z",
                "2024-01-03T00:00:00Z",
            ],
            "converted_value": [1.0, 2.0],
        }
    )
    assert len(validate_protocol_intervals(frame)) == 2
    frame.loc[1, "effective_start_utc"] = "2024-01-01T12:00:00Z"
    with pytest.raises(ValueError, match="overlaps"):
        validate_protocol_intervals(frame)


def test_model_compatibility_classification() -> None:
    protocol = _candidate(
        field="CollateralConfig.liquidation_ratio",
        value=None,
        reference="protocol.csv",
        provenance="protocol_constant",
    )
    ready = _review_decision(protocol)
    assert ready["review_status"] == "ready_for_later_adoption"
    unsupported = _candidate(
        field="protocol.debt_ceiling",
        value=None,
        reference="protocol.csv",
        provenance="protocol_constant",
    )
    assert (
        _review_decision(unsupported)["review_status"]
        == "blocked_by_model_mapping"
    )


def test_phase1e_dependency_schema_has_all_ten_fields() -> None:
    fields = [
        "n_vaults",
        "target_debt_share",
        "debt_mean",
        "debt_std",
        "collateral_ratio_mean",
        "collateral_ratio_std",
        "min_collateral_ratio_buffer",
        "max_close_factor",
        "max_normal_liquidatable_share",
        "max_stress_liquidatable_share",
    ]
    status = pd.DataFrame(
        {
            "parameter_subsection": [f"test {field}" for field in fields],
            "simulator_field": fields,
            "current_status": ["blocked_pending_phase1e_b"] * len(fields),
        }
    )
    result = _phase1e_dependencies(status)
    assert len(result) == 10
    assert result["opening_state_reconstruction_required"].all()
    assert result["minimum_sufficient_observations"].str.len().gt(0).all()
