"""Focused deterministic tests for representative-vault estimation."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


from tests.support import REPOSITORY_ROOT
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from dai_sim.calibration import vaults as phase2b


def state_fixture() -> pd.DataFrame:
    """Return a tiny multi-ilk state fixture without empirical input files."""
    return pd.DataFrame({
        "ilk": ["ETH-A", "ETH-A", "WBTC-A", "WBTC-B"],
        "urn": ["u1", "u2", "u3", "u4"],
        "owner_or_proxy": ["o1", "o1", "o2", None],
        "active": [True, True, True, False],
        "debt_dai": [100.0, 0.0, 200.0, 300.0],
        "collateral_value_usd": [140.0, 10.0, 300.0, 300.0],
        "collateral_ratio": [1.4, np.nan, 1.5, 1.0],
        "liquidation_ratio": [1.45, 1.45, 1.6, 1.6],
    })


def test_authoritative_parameter_list_is_exact() -> None:
    assert phase2b.PARAMETERS == (
        "n_vaults",
        "target_debt_share",
        "debt_mean",
        "debt_std",
        "collateral_ratio_mean",
        "collateral_ratio_std",
        "min_collateral_ratio_buffer",
        "max_normal_liquidatable_share",
        "max_stress_liquidatable_share",
    )
    assert phase2b.MAX_CLOSE_FACTOR not in phase2b.PARAMETERS


def test_debt_calculation_uses_wad_ray_scaling() -> None:
    assert phase2b.debt_from_raw(2 * 10**18, 3 * 10**27) == 6.0
    with pytest.raises(ValueError):
        phase2b.debt_from_raw(-1, 10**27)


def test_active_indebted_filter_excludes_zero_and_inactive() -> None:
    result = phase2b.active_indebted(state_fixture())
    assert result["urn"].tolist() == ["u1", "u3"]


def test_collateral_ratio_calculation() -> None:
    result = phase2b.collateral_ratio(
        pd.Series([150.0, 1.0]), pd.Series([100.0, 0.0])
    )
    assert result.iloc[0] == pytest.approx(1.5)
    assert pd.isna(result.iloc[1])


def test_absolute_and_relative_buffers() -> None:
    absolute, relative = phase2b.collateral_ratio_buffers(
        pd.Series([1.65]), pd.Series([1.5])
    )
    assert absolute.iloc[0] == pytest.approx(0.15)
    assert relative.iloc[0] == pytest.approx(0.10)


def test_liquidatable_classification_requires_active_positive_debt() -> None:
    frame = state_fixture()
    result = phase2b.classify_liquidatable(
        frame["active"],
        frame["debt_dai"],
        frame["collateral_ratio"],
        frame["liquidation_ratio"],
    )
    assert result.tolist() == [True, False, True, False]


def test_denominator_sensitivity_uses_all_active_as_primary() -> None:
    result = phase2b.liquidatable_denominators(state_fixture())
    assert result["liquidatable_count"] == 2
    assert result["active_count"] == 3
    assert result["active_indebted_count"] == 2
    assert result["share_all_active"] == pytest.approx(2 / 3)
    assert result["share_active_indebted"] == 1.0


def test_regime_labels_and_windows_exclude_ftx() -> None:
    roles = {window.key: window.role for window in phase2b.WINDOWS}
    assert roles == {"quiet_mature": "normal", "usdc_svb": "stress"}
    assert all(
        window.end_exclusive <= phase2b.FTX_START
        or window.start >= phase2b.FTX_END_EXCLUSIVE
        for window in phase2b.WINDOWS
    )


def test_collateral_stratification_preserves_exact_ilks() -> None:
    scopes = {
        name: len(frame)
        for name, frame in phase2b._scopes(state_fixture())
    }
    assert scopes["ALL"] == 4
    assert scopes["ETH"] == 2
    assert scopes["WBTC"] == 2
    assert scopes["ETH-A"] == 2
    assert scopes["WBTC-B"] == 1


def test_clustered_bootstrap_is_reproducible() -> None:
    frame = pd.DataFrame({
        "urn": ["a", "a", "b", "b"],
        "value": [1.0, 2.0, 10.0, 20.0],
    })
    first = phase2b.clustered_bootstrap_reproducible(
        frame,
        "value",
        "urn",
        seed=42,
        replications=100,
    )
    second = phase2b.clustered_bootstrap_reproducible(
        frame,
        "value",
        "urn",
        seed=42,
        replications=100,
    )
    assert first == second


def test_same_urn_rows_are_resampled_as_one_cluster() -> None:
    frame = pd.DataFrame({
        "urn": ["a", "a", "b", "b"],
        "value": [0.0, 0.0, 100.0, 100.0],
    })
    lower, upper = phase2b.clustered_bootstrap_reproducible(
        frame,
        "value",
        "urn",
        seed=7,
        replications=200,
    )
    assert lower == 0.0
    assert upper == 100.0


def test_numeric_trace_ordering_is_not_lexicographic() -> None:
    traces = ["10", "2", "1.3", "1.10", ""]
    assert sorted(traces, key=phase2b.numeric_trace_tuple) == [
        "",
        "1.3",
        "1.10",
        "2",
        "10",
    ]
    with pytest.raises(ValueError):
        phase2b.numeric_trace_tuple("1.bad")


def test_effective_rate_null_trace_requires_validated_root_source() -> None:
    opening = pd.Series({
        "trace_position": np.nan,
        "source_type": "opening_rate",
        "opening_state_flag": True,
        "observed_call_flag": True,
    })
    drip = pd.Series({
        "trace_position": np.nan,
        "source_type": "drip",
        "opening_state_flag": False,
        "observed_call_flag": True,
    })
    invalid = pd.Series({
        "trace_position": np.nan,
        "source_type": "fold",
        "opening_state_flag": False,
        "observed_call_flag": True,
    })
    assert phase2b._effective_rate_trace_tuple(opening) == ()
    assert phase2b._effective_rate_trace_tuple(drip) == ()
    with pytest.raises(ValueError, match="unavailable trace position"):
        phase2b._effective_rate_trace_tuple(invalid)


def test_candidate_registry_schema_rejects_missing_fields() -> None:
    with pytest.raises(ValueError, match="candidate lacks"):
        phase2b._candidate(parameter_name="debt_mean")
    record = {
        field: "value" for field in phase2b.CANDIDATE_FIELDS
    }
    assert tuple(phase2b._candidate(**record)) == phase2b.CANDIDATE_FIELDS


def test_max_close_factor_status_has_no_candidate() -> None:
    status = phase2b._candidate_status([])
    row = status.loc[status["parameter"].eq("max_close_factor")].iloc[0]
    assert row["status"] == "insufficient_evidence"
    assert bool(row["has_candidate"]) is False


def test_estimator_has_no_configuration_or_network_write_path() -> None:
    source = Path(phase2b.__file__).read_text(encoding="utf-8")
    assert "requests." not in source
    assert "urllib" not in source
    assert "config/empirical.yaml" not in source
    assert "yaml.safe_dump" not in source
