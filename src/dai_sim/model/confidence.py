"""
confidence.py

State-dependent confidence and panic-regime logic for the DAI simulation.

This module turns the idea of "belief in the peg" into a dynamic state variable.

Instead of assuming a fixed belief parameter, we classify the market into regimes:
- normal: DAI is close to the peg and the vault system looks healthy;
- stress: DAI deviates from the peg or liquidation pressure rises;
- panic: DAI is far below the peg, many vaults are liquidatable, or bad debt appears.

This is inspired by stablecoin panic-regime modelling, but adapted to DAI.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ConfidenceConfig:
    """
    Configuration for confidence-regime classification.

    Attributes
    ----------
    normal_lower_price:
        Lower DAI price bound for normal regime.
    normal_upper_price:
        Upper DAI price bound for normal regime.
    stress_lower_price:
        Lower DAI price bound before panic is triggered.
    max_normal_liquidatable_share:
        If share of active vaults liquidatable is below this value, the vault
        system can still be considered normal from a liquidation-pressure view.
    max_stress_liquidatable_share:
        If share of active vaults liquidatable exceeds this value, panic may occur.
    bad_debt_panic_threshold:
        If active bad debt exceeds this amount, panic may occur.
    normal_confidence:
        Confidence level in normal regime.
    stress_confidence:
        Confidence level in stress regime.
    panic_confidence:
        Confidence level in panic regime.
    panic_selling_multiplier:
        Additional selling pressure multiplier in panic regime.
    """

    normal_lower_price: float = 0.99
    normal_upper_price: float = 1.01
    stress_lower_price: float = 0.97

    max_normal_liquidatable_share: float = 0.05
    max_stress_liquidatable_share: float = 0.30
    bad_debt_panic_threshold: float = 1_000.0

    normal_confidence: float = 1.0
    stress_confidence: float = 0.5
    panic_confidence: float = 0.1

    panic_selling_multiplier: float = 2.0

    def validate(self) -> None:
        """Validate confidence configuration."""
        if not 0 < self.stress_lower_price < self.normal_lower_price < 1:
            raise ValueError(
                "Require 0 < stress_lower_price < normal_lower_price < 1."
            )
        if self.normal_upper_price <= 1:
            raise ValueError("normal_upper_price should be greater than 1.")
        if not 0 <= self.max_normal_liquidatable_share <= 1:
            raise ValueError("max_normal_liquidatable_share must be in [0, 1].")
        if not 0 <= self.max_stress_liquidatable_share <= 1:
            raise ValueError("max_stress_liquidatable_share must be in [0, 1].")
        if self.max_normal_liquidatable_share > self.max_stress_liquidatable_share:
            raise ValueError(
                "max_normal_liquidatable_share should not exceed "
                "max_stress_liquidatable_share."
            )
        if self.bad_debt_panic_threshold < 0:
            raise ValueError("bad_debt_panic_threshold cannot be negative.")
        if self.normal_confidence < 0:
            raise ValueError("normal_confidence cannot be negative.")
        if self.stress_confidence < 0:
            raise ValueError("stress_confidence cannot be negative.")
        if self.panic_confidence < 0:
            raise ValueError("panic_confidence cannot be negative.")
        if self.panic_selling_multiplier < 0:
            raise ValueError("panic_selling_multiplier cannot be negative.")


@dataclass(frozen=True)
class PersistentConfidenceConfig:
    """Explicit, non-runtime parameters for the persistent-confidence model."""

    deterioration_adjustment: float
    recovery_adjustment: float
    confidence_floor: float
    stability_hours: int

    def validate(self) -> None:
        """Validate the structural restrictions of the proposed mechanism."""
        values = (
            self.deterioration_adjustment,
            self.recovery_adjustment,
            self.confidence_floor,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Persistent-confidence parameters must be finite.")
        if not (
            0.0
            < self.recovery_adjustment
            <= self.deterioration_adjustment
            <= 1.0
        ):
            raise ValueError(
                "Require 0 < recovery_adjustment <= "
                "deterioration_adjustment <= 1."
            )
        if not 0.0 <= self.confidence_floor < 1.0:
            raise ValueError("confidence_floor must be in [0, 1).")
        if isinstance(self.stability_hours, bool) or self.stability_hours < 1:
            raise ValueError("stability_hours must be an integer of at least 1.")
        if int(self.stability_hours) != self.stability_hours:
            raise ValueError("stability_hours must be an integer of at least 1.")


@dataclass(frozen=True)
class PersistentConfidenceState:
    """Persistent confidence and its recovery-gate memory."""

    confidence: float
    consecutive_stable_hours: int
    recovery_gate_open: bool

    @classmethod
    def initial(cls) -> "PersistentConfidenceState":
        """Return the pre-registered state without using future evidence."""
        return cls(
            confidence=1.0,
            consecutive_stable_hours=0,
            recovery_gate_open=False,
        )

    def validate(self) -> None:
        """Validate a state supplied to the pure transition function."""
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be finite and in [0, 1].")
        if (
            isinstance(self.consecutive_stable_hours, bool)
            or self.consecutive_stable_hours < 0
            or int(self.consecutive_stable_hours)
            != self.consecutive_stable_hours
        ):
            raise ValueError(
                "consecutive_stable_hours must be a non-negative integer."
            )


@dataclass(frozen=True)
class RecoveryGateInputs:
    """Required observable conditions controlling confidence recovery."""

    price_inside_recovery_band: bool
    liquidation_pressure_acceptable: bool
    severe_bad_debt_present: bool


@dataclass(frozen=True)
class PersistentConfidenceUpdate:
    """A new immutable state plus auditable transition diagnostics."""

    state: PersistentConfidenceState
    target_stress: float
    target_confidence: float
    branch: str
    updated_stable_counter: int
    recovery_gate_open: bool


def observable_stress(
    scaled_peg_gap: float,
    scaled_collateral_stress: float,
    *,
    peg_weight: float = 0.5,
    collateral_weight: float = 0.5,
) -> float:
    """Combine already-scaled observable stress inputs without rescaling them."""
    values = (
        scaled_peg_gap,
        scaled_collateral_stress,
        peg_weight,
        collateral_weight,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Stress inputs and weights must be finite.")
    if not 0.0 <= scaled_peg_gap <= 1.0:
        raise ValueError("scaled_peg_gap must be in [0, 1].")
    if not 0.0 <= scaled_collateral_stress <= 1.0:
        raise ValueError("scaled_collateral_stress must be in [0, 1].")
    if peg_weight < 0.0 or collateral_weight < 0.0:
        raise ValueError("Stress weights must be non-negative.")
    if not math.isclose(
        peg_weight + collateral_weight,
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("Stress weights must sum to one.")
    return min(
        1.0,
        max(
            0.0,
            peg_weight * scaled_peg_gap
            + collateral_weight * scaled_collateral_stress,
        ),
    )


def update_persistent_confidence(
    state: PersistentConfidenceState,
    config: PersistentConfidenceConfig,
    *,
    scaled_peg_gap: float,
    scaled_collateral_stress: float,
    recovery_inputs: RecoveryGateInputs,
    peg_weight: float = 0.5,
    collateral_weight: float = 0.5,
) -> PersistentConfidenceUpdate:
    """Apply one pure persistent-confidence transition.

    This interface is intentionally not called by the production simulation.
    """
    state.validate()
    config.validate()
    stress = observable_stress(
        scaled_peg_gap,
        scaled_collateral_stress,
        peg_weight=peg_weight,
        collateral_weight=collateral_weight,
    )
    target = 1.0 - stress
    qualifying = (
        recovery_inputs.price_inside_recovery_band
        and recovery_inputs.liquidation_pressure_acceptable
        and not recovery_inputs.severe_bad_debt_present
    )
    if qualifying:
        stable_hours = state.consecutive_stable_hours + 1
        gate_open = stable_hours >= config.stability_hours
    else:
        stable_hours = 0
        gate_open = False

    if target < state.confidence:
        confidence = max(
            config.confidence_floor,
            state.confidence
            + config.deterioration_adjustment * (target - state.confidence),
        )
        branch = "deterioration"
    elif gate_open:
        confidence = min(
            1.0,
            state.confidence
            + config.recovery_adjustment * (1.0 - state.confidence),
        )
        branch = "recovery"
    else:
        confidence = state.confidence
        branch = "hold"

    updated = PersistentConfidenceState(
        confidence=confidence,
        consecutive_stable_hours=stable_hours,
        recovery_gate_open=gate_open,
    )
    return PersistentConfidenceUpdate(
        state=updated,
        target_stress=stress,
        target_confidence=target,
        branch=branch,
        updated_stable_counter=stable_hours,
        recovery_gate_open=gate_open,
    )


def classify_price_regime(
    dai_price: float,
    config: ConfidenceConfig,
) -> str:
    """
    Classify regime based only on DAI price.

    Parameters
    ----------
    dai_price:
        Current DAI market price.
    config:
        ConfidenceConfig object.

    Returns
    -------
    str
        One of: normal, stress, panic.
    """
    config.validate()

    if dai_price <= 0:
        return "panic"

    if config.normal_lower_price <= dai_price <= config.normal_upper_price:
        return "normal"

    if config.stress_lower_price <= dai_price < config.normal_lower_price:
        return "stress"

    if config.normal_upper_price < dai_price:
        # Above-peg DAI is a deviation, but less dangerous than below-peg panic.
        return "stress"

    return "panic"


def classify_system_regime(
    dai_price: float,
    share_liquidatable: float,
    active_bad_debt: float,
    config: ConfidenceConfig,
) -> str:
    """
    Classify overall system regime using DAI price and vault-system stress.

    Panic is triggered if:
    - DAI price falls below stress_lower_price;
    - share of liquidatable vaults is very high;
    - active bad debt exceeds the panic threshold.

    Stress is triggered if:
    - DAI price leaves the normal range;
    - share of liquidatable vaults exceeds the normal threshold.

    Parameters
    ----------
    dai_price:
        Current DAI market price.
    share_liquidatable:
        Share of active vaults currently liquidatable.
    active_bad_debt:
        Active bad debt in the system.
    config:
        ConfidenceConfig object.

    Returns
    -------
    str
        One of: normal, stress, panic.
    """
    config.validate()

    if not 0 <= share_liquidatable <= 1:
        raise ValueError("share_liquidatable must be in [0, 1].")
    if active_bad_debt < 0:
        raise ValueError("active_bad_debt cannot be negative.")

    price_regime = classify_price_regime(dai_price, config)

    if (
        price_regime == "panic"
        or share_liquidatable > config.max_stress_liquidatable_share
        or active_bad_debt > config.bad_debt_panic_threshold
    ):
        return "panic"

    if (
        price_regime == "stress"
        or share_liquidatable > config.max_normal_liquidatable_share
    ):
        return "stress"

    return "normal"


def confidence_level(
    regime: str,
    config: ConfidenceConfig,
) -> float:
    """
    Map regime to confidence level.

    Parameters
    ----------
    regime:
        normal, stress, or panic.
    config:
        ConfidenceConfig object.

    Returns
    -------
    float
        Confidence level.
    """
    config.validate()

    if regime == "normal":
        return config.normal_confidence
    if regime == "stress":
        return config.stress_confidence
    if regime == "panic":
        return config.panic_confidence

    raise ValueError(f"Unknown regime: {regime}")


def panic_selling_pressure(
    regime: str,
    dai_price: float,
    config: ConfidenceConfig,
) -> float:
    """
    Calculate additional selling pressure in panic.

    The further DAI falls below 1, the stronger the panic selling pressure.

    Parameters
    ----------
    regime:
        normal, stress, or panic.
    dai_price:
        Current DAI price.
    config:
        ConfidenceConfig object.

    Returns
    -------
    float
        Additional selling pressure.
    """
    config.validate()

    if regime != "panic":
        return 0.0

    peg_gap = max(1.0 - dai_price, 0.0)
    return config.panic_selling_multiplier * peg_gap


def get_confidence_state(
    dai_price: float,
    share_liquidatable: float,
    active_bad_debt: float,
    config: ConfidenceConfig,
) -> dict:
    """
    Return full confidence state.

    Parameters
    ----------
    dai_price:
        Current DAI market price.
    share_liquidatable:
        Share of active vaults currently liquidatable.
    active_bad_debt:
        Active bad debt in the system.
    config:
        ConfidenceConfig object.

    Returns
    -------
    dict
        Confidence state containing regime, confidence level, and panic pressure.
    """
    regime = classify_system_regime(
        dai_price=dai_price,
        share_liquidatable=share_liquidatable,
        active_bad_debt=active_bad_debt,
        config=config,
    )

    return {
        "regime": regime,
        "confidence": confidence_level(regime, config),
        "panic_selling_pressure": panic_selling_pressure(
            regime=regime,
            dai_price=dai_price,
            config=config,
        ),
    }


if __name__ == "__main__":
    # Quick smoke test: PYTHONPATH=src python -m dai_sim.model.confidence

    config = ConfidenceConfig()

    test_cases = [
        {
            "name": "normal price, healthy vaults",
            "dai_price": 1.00,
            "share_liquidatable": 0.00,
            "active_bad_debt": 0.0,
        },
        {
            "name": "slightly below peg",
            "dai_price": 0.985,
            "share_liquidatable": 0.00,
            "active_bad_debt": 0.0,
        },
        {
            "name": "large liquidation pressure",
            "dai_price": 1.00,
            "share_liquidatable": 0.50,
            "active_bad_debt": 0.0,
        },
        {
            "name": "bad debt appears",
            "dai_price": 0.995,
            "share_liquidatable": 0.10,
            "active_bad_debt": 2_000.0,
        },
        {
            "name": "DAI depeg panic",
            "dai_price": 0.94,
            "share_liquidatable": 0.10,
            "active_bad_debt": 0.0,
        },
    ]

    for case in test_cases:
        state = get_confidence_state(
            dai_price=case["dai_price"],
            share_liquidatable=case["share_liquidatable"],
            active_bad_debt=case["active_bad_debt"],
            config=config,
        )

        print(f"\n{case['name']}")
        print(state)
