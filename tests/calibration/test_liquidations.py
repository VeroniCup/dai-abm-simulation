"""Focused synthetic tests for liquidation and stress-tail estimation."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


from tests.support import REPOSITORY_ROOT
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from dai_sim.calibration import liquidations as phase2c


def test_simulator_field_semantic_extraction() -> None:
    audit = phase2c.semantic_audit()
    field = audit.loc[
        audit["interpretation"].eq("current_simulator_field")
    ].iloc[0]
    assert "fraction of one vault" in field["observed_semantics"]
    assert not bool(field["is_throughput_control"])
    capacity = audit.loc[
        audit["interpretation"].eq("separate_capacity_control")
    ].iloc[0]
    assert bool(capacity["is_throughput_control"])


def test_full_vault_fraction_and_zero_denominator() -> None:
    assert phase2c.decimal_fraction(-10, 10) == Decimal("1")
    assert phase2c.decimal_fraction(-5, 10) == Decimal("0.5")
    assert phase2c.decimal_fraction(1, 0) is None


def test_all_one_distribution_has_no_artificial_variance() -> None:
    result = phase2c.close_factor_distribution(
        [Decimal("1"), Decimal("1"), Decimal("1")]
    )
    assert result["mean"] == 1.0
    assert result["standard_deviation"] == 0.0
    assert result["degenerate"]


def test_bark_grab_amount_reconciliation() -> None:
    bark_ink, bark_art = 25, 40
    grab_dink, grab_dart = -25, -40
    assert grab_dink == -bark_ink
    assert grab_dart == -bark_art
    assert phase2c.decimal_fraction(grab_dart, bark_art) == 1


def _auction_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    auctions = pd.DataFrame({
        "clipper_contract": ["0xabc"],
        "auction_id": [1],
        "ilk": ["ETH-A"],
        "bark_time_utc": ["2022-05-01T00:00:00Z"],
        "kick_tab_dai": [100.0],
        "kick_lot_wad": [10.0],
        "terminal_classification": ["target_cleared"],
    })
    actions = pd.DataFrame({
        "record_type": ["take_event", "take_event"],
        "clipper_contract": ["0xAbC", "0xAbC"],
        "auction_id": [1, 1],
        "block_time": [
            "2022-05-01T00:10:00Z",
            "2022-05-01T00:20:00Z",
        ],
        "block_number": [1, 2],
        "event_index": [2, 1],
        "tx_hash": ["0x1", "0x2"],
        "remaining_tab_dai": [60.0, 0.0],
        "remaining_lot_wad": [6.0, 1.0],
        "owe_dai": [40.0, 60.0],
    })
    return actions, auctions


def test_auction_partial_execution_fractions() -> None:
    actions, auctions = _auction_fixture()
    result = phase2c.auction_execution_fractions(actions, auctions)
    assert result["debt_fraction_of_initial_auction"].tolist() == [0.4, 0.6]
    assert result["cumulative_debt_fraction"].tolist() == [0.4, 1.0]
    assert result["collateral_fraction_of_initial_lot"].tolist() == [0.4, 0.5]
    assert result["time_to_100_seconds"].tolist() == [1200.0, 1200.0]


def test_sequence_construction_uses_strict_one_hour_gap() -> None:
    frame = pd.DataFrame({
        "timestamp_utc": [
            "2022-01-01T00:00:00Z",
            "2022-01-01T01:00:00Z",
            "2022-01-01T02:00:01Z",
        ]
    })
    result = phase2c.assign_sequences(frame)
    assert result.tolist() == [1, 1, 2]


def test_stress_share_denominator_is_explicit() -> None:
    active = 100
    liquidatable = 3
    share = liquidatable / active
    assert share == pytest.approx(0.03)
    assert share != liquidatable / 80


def test_absolute_and_relative_buffer() -> None:
    absolute, relative = phase2c.collateral_buffers(
        pd.Series([1.65]), pd.Series([1.5])
    )
    assert absolute.iloc[0] == pytest.approx(0.15)
    assert relative.iloc[0] == pytest.approx(0.10)


def test_regime_labels_are_not_pooled() -> None:
    review = pd.DataFrame({
        "conditioning": [
            "named_terra_cefi_window",
            "phase2a_classifier_stress",
        ],
        "maximum": [0.02, 0.01],
    })
    assert review.groupby("conditioning").size().to_dict() == {
        "named_terra_cefi_window": 1,
        "phase2a_classifier_stress": 1,
    }


def test_candidate_registry_schema_and_status() -> None:
    with pytest.raises(ValueError, match="lacks fields"):
        phase2c._candidate(parameter="max_close_factor")
    record = {field: "x" for field in phase2c.CANDIDATE_FIELDS}
    record["review status"] = "ready_for_review"
    assert tuple(phase2c._candidate(**record)) == phase2c.CANDIDATE_FIELDS
    record["review status"] = "adopted"
    with pytest.raises(ValueError, match="Invalid"):
        phase2c._candidate(**record)


def test_fixed_seed_bootstrap_is_reproducible() -> None:
    frame = pd.DataFrame({
        "day": ["a", "a", "b", "b"],
        "value": [0.0, 0.1, 0.2, 0.3],
    })
    first = phase2c.bootstrap_quantile(
        frame, "value", 0.95, seed=42, replications=100,
        cluster_column="day",
    )
    second = phase2c.bootstrap_quantile(
        frame, "value", 0.95, seed=42, replications=100,
        cluster_column="day",
    )
    assert first == second


def test_estimator_has_no_network_or_configuration_write_path() -> None:
    source = Path(phase2c.__file__).read_text(encoding="utf-8")
    assert "requests." not in source
    assert "urllib" not in source
    assert "config/empirical.yaml" not in source
    assert "yaml.safe_dump" not in source
    assert "max_close_factor =" not in source
