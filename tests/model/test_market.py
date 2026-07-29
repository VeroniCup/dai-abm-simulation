"""Coefficient-normalised behavioural market interface tests."""

from __future__ import annotations

import pytest

from dai_sim.model.market import (
    coefficient_normalised_market_response,
)


def _response(**changes):
    values = {
        "dai_price": 0.98,
        "confidence": 0.5,
        "below_peg_response": 0.2,
        "above_peg_response": 0.1,
        "panic_response": 0.3,
        "residual_innovation": 0.001,
        "min_price": 0.5,
        "max_price": 1.5,
    }
    values.update(changes)
    return coefficient_normalised_market_response(**values)


def test_behavioural_components_count_panic_exactly_once() -> None:
    result = _response()
    assert result.below_peg_stabilising_component == pytest.approx(0.002)
    assert result.above_peg_supply_component == 0.0
    assert result.panic_component == pytest.approx(-0.003)
    assert result.unclipped_price_change == pytest.approx(0.0)
    assert result.unclipped_next_price == pytest.approx(0.98)


def test_above_peg_supply_is_negative_and_panic_is_zero() -> None:
    result = _response(dai_price=1.02)
    assert result.below_peg_stabilising_component == 0.0
    assert result.above_peg_supply_component == pytest.approx(-0.002)
    assert result.panic_component == 0.0


def test_clipping_reports_the_binding_bound() -> None:
    low = _response(residual_innovation=-1.0)
    high = _response(residual_innovation=1.0)
    assert low.lower_bound_binding and not low.upper_bound_binding
    assert low.clipped_next_price == 0.5
    assert high.upper_bound_binding and not high.lower_bound_binding
    assert high.clipped_next_price == 1.5


@pytest.mark.parametrize(
    "changes",
    [
        {"confidence": 1.1},
        {"panic_response": -0.1},
        {"dai_price": float("nan")},
        {"min_price": 2.0, "max_price": 1.0},
    ],
)
def test_behavioural_interface_rejects_invalid_inputs(changes) -> None:
    with pytest.raises(ValueError):
        _response(**changes)
