"""Pure persistent-confidence interface tests."""

from __future__ import annotations

import pytest

from dai_sim.model.confidence import (
    PersistentConfidenceConfig,
    PersistentConfidenceState,
    RecoveryGateInputs,
    observable_stress,
    update_persistent_confidence,
)


def _config(**changes: float | int) -> PersistentConfidenceConfig:
    values = {
        "deterioration_adjustment": 0.5,
        "recovery_adjustment": 0.25,
        "confidence_floor": 0.2,
        "stability_hours": 3,
    }
    values.update(changes)
    return PersistentConfidenceConfig(**values)


def _gate(
    *,
    price: bool = True,
    liquidation: bool = True,
    severe: bool = False,
) -> RecoveryGateInputs:
    return RecoveryGateInputs(price, liquidation, severe)


@pytest.mark.parametrize(
    "changes",
    [
        {"recovery_adjustment": 0.0},
        {"recovery_adjustment": 0.6},
        {"deterioration_adjustment": 1.1},
        {"confidence_floor": 1.0},
        {"stability_hours": 0},
    ],
)
def test_persistent_configuration_rejects_invalid_structure(changes) -> None:
    with pytest.raises(ValueError):
        _config(**changes).validate()


def test_observable_stress_validates_weights_and_clips_roundoff() -> None:
    assert observable_stress(1.0, 1.0) == 1.0
    assert observable_stress(0.2, 0.4) == pytest.approx(0.3)
    with pytest.raises(ValueError, match="sum to one"):
        observable_stress(0.2, 0.4, peg_weight=0.6, collateral_weight=0.5)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        observable_stress(-0.1, 0.4)


def test_initial_state_and_deterioration_are_deterministic_and_floored() -> None:
    state = PersistentConfidenceState.initial()
    assert state == PersistentConfidenceState(1.0, 0, False)
    update = update_persistent_confidence(
        state,
        _config(confidence_floor=0.8, deterioration_adjustment=1.0),
        scaled_peg_gap=1.0,
        scaled_collateral_stress=1.0,
        recovery_inputs=_gate(price=False),
    )
    assert update.branch == "deterioration"
    assert update.target_stress == 1.0
    assert update.state.confidence == 0.8
    assert update == update_persistent_confidence(
        state,
        _config(confidence_floor=0.8, deterioration_adjustment=1.0),
        scaled_peg_gap=1.0,
        scaled_collateral_stress=1.0,
        recovery_inputs=_gate(price=False),
    )


def test_recovery_gate_opens_on_exact_hour_and_recovery_is_delayed() -> None:
    state = PersistentConfidenceState(0.4, 0, False)
    for expected in (1, 2):
        update = update_persistent_confidence(
            state,
            _config(),
            scaled_peg_gap=0.0,
            scaled_collateral_stress=0.0,
            recovery_inputs=_gate(),
        )
        assert update.branch == "hold"
        assert update.updated_stable_counter == expected
        assert not update.recovery_gate_open
        state = update.state
    update = update_persistent_confidence(
        state,
        _config(),
        scaled_peg_gap=0.0,
        scaled_collateral_stress=0.0,
        recovery_inputs=_gate(),
    )
    assert update.branch == "recovery"
    assert update.updated_stable_counter == 3
    assert update.recovery_gate_open
    assert update.state.confidence == pytest.approx(0.55)


def test_non_qualifying_and_severe_hours_reset_recovery_memory() -> None:
    state = PersistentConfidenceState(0.4, 2, False)
    for gate in (_gate(liquidation=False), _gate(severe=True)):
        update = update_persistent_confidence(
            state,
            _config(),
            scaled_peg_gap=0.0,
            scaled_collateral_stress=0.0,
            recovery_inputs=gate,
        )
        assert update.branch == "hold"
        assert update.updated_stable_counter == 0
        assert not update.recovery_gate_open


def test_recovery_never_exceeds_confidence_ceiling() -> None:
    update = update_persistent_confidence(
        PersistentConfidenceState(1.0, 3, True),
        _config(),
        scaled_peg_gap=0.0,
        scaled_collateral_stress=0.0,
        recovery_inputs=_gate(),
    )
    assert update.state.confidence == 1.0
