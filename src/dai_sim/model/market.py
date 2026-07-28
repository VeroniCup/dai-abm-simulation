"""
dai_market.py

Simplified DAI market price dynamics for the DAI stability simulation.

This module models DAI price as responding to excess demand/supply pressure.

The aim is not to reproduce the full real-world DAI market. Instead, this
module provides a transparent mechanism for stress testing:

- if DAI trades below $1 and confidence is high, stabilising arbitrage demand
  pushes the price upward;
- if DAI trades above $1, selling/minting pressure pushes the price downward;
- if confidence collapses, panic selling can dominate stabilising arbitrage.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DAIMarketConfig:
    """
    Configuration for simplified DAI market dynamics.

    Attributes
    ----------
    peg_price:
        Target DAI price, normally 1 USD.
    price_adjustment_speed:
        Controls how strongly DAI price reacts to net demand pressure.
    arbitrage_strength:
        Strength of stabilising arbitrage around the peg.
    above_peg_supply_strength:
        Strength of selling/minting pressure when DAI is above peg.
    panic_strength:
        Strength of additional selling pressure in panic.
    noise_std:
        Standard deviation of random market noise.
    min_price:
        Lower bound for simulated DAI price.
    max_price:
        Upper bound for simulated DAI price.
    """

    peg_price: float = 1.0
    price_adjustment_speed: float = 0.02
    arbitrage_strength: float = 1.0
    above_peg_supply_strength: float = 1.0
    panic_strength: float = 1.0
    noise_std: float = 0.0005
    min_price: float = 0.50
    max_price: float = 1.50

    # Peg recovery mechanism.
    enable_peg_recovery: bool = False
    arbitrage_recovery_strength: float = 0.0
    policy_feedback_strength: float = 0.0
    bad_debt_recovery_drag: float = 1.0
    min_recovery_confidence: float = 0.0

    def validate(self) -> None:
        """Validate DAI market configuration."""
        if self.peg_price <= 0:
            raise ValueError("peg_price must be positive.")
        if self.price_adjustment_speed < 0:
            raise ValueError("price_adjustment_speed cannot be negative.")
        if self.arbitrage_strength < 0:
            raise ValueError("arbitrage_strength cannot be negative.")
        if self.above_peg_supply_strength < 0:
            raise ValueError("above_peg_supply_strength cannot be negative.")
        if self.panic_strength < 0:
            raise ValueError("panic_strength cannot be negative.")
        if self.noise_std < 0:
            raise ValueError("noise_std cannot be negative.")
        if self.min_price <= 0:
            raise ValueError("min_price must be positive.")
        if self.max_price <= self.min_price:
            raise ValueError("max_price must be greater than min_price.")

        # Arbitrage
        if self.arbitrage_recovery_strength < 0:
            raise ValueError("arbitrage_recovery_strength cannot be negative.")
        if self.policy_feedback_strength < 0:
            raise ValueError("policy_feedback_strength cannot be negative.")
        if self.bad_debt_recovery_drag < 0:
            raise ValueError("bad_debt_recovery_drag cannot be negative.")
        if not 0 <= self.min_recovery_confidence <= 1:
            raise ValueError("min_recovery_confidence must be between 0 and 1.")


def calculate_dai_market_pressures(
    dai_price: float,
    confidence: float,
    panic_selling_pressure: float,
    market_config: DAIMarketConfig,
) -> dict:
    """
    Calculate simplified DAI demand and supply pressures.

    Parameters
    ----------
    dai_price:
        Current DAI price.
    confidence:
        Current confidence level in the peg.
    panic_selling_pressure:
        Additional panic selling pressure from confidence.py.
    market_config:
        DAIMarketConfig object.

    Returns
    -------
    dict
        Dictionary containing demand pressure, supply pressure, panic pressure,
        and net pressure.
    """
    market_config.validate()

    if dai_price <= 0:
        raise ValueError("dai_price must be positive.")
    if confidence < 0:
        raise ValueError("confidence cannot be negative.")
    if panic_selling_pressure < 0:
        raise ValueError("panic_selling_pressure cannot be negative.")

    peg_gap = market_config.peg_price - dai_price

    # Stabilising arbitrage:
    # If DAI < 1, buying pressure should be positive.
    # If DAI >= 1, this term becomes zero.
    demand_pressure = (
        market_config.arbitrage_strength
        * confidence
        * max(peg_gap, 0.0)
    )

    # Above-peg supply/minting:
    # If DAI > 1, supply pressure pushes price downward.
    # If DAI <= 1, this term becomes zero.
    above_peg_supply_pressure = (
        market_config.above_peg_supply_strength
        * max(-peg_gap, 0.0)
    )

    # Panic selling:
    # This is extra sell pressure when confidence breaks down.
    panic_pressure = market_config.panic_strength * panic_selling_pressure

    total_supply_pressure = above_peg_supply_pressure + panic_pressure

    net_pressure = demand_pressure - total_supply_pressure

    return {
        "demand_pressure": demand_pressure,
        "above_peg_supply_pressure": above_peg_supply_pressure,
        "panic_pressure": panic_pressure,
        "total_supply_pressure": total_supply_pressure,
        "net_pressure": net_pressure,
    }


def calculate_peg_recovery_pressure(
    dai_price: float,
    confidence: float,
    active_bad_debt: float,
    total_debt_active: float,
    market_config: DAIMarketConfig,
) -> dict:
    """
    Calculate additional peg-recovery pressure.

    This is a stylised recovery mechanism inspired by MakerDAO's target-rate
    feedback logic and arbitrage demand around the peg.

    If DAI trades below peg, recovery pressure increases. However, recovery is
    weakened when confidence is low or when active bad debt remains large.
    """
    if not market_config.enable_peg_recovery:
        return {
            "peg_gap": 0.0,
            "bad_debt_ratio": 0.0,
            "recovery_discount": 0.0,
            "arbitrage_recovery_pressure": 0.0,
            "policy_feedback_pressure": 0.0,
            "total_recovery_pressure": 0.0,
        }

    peg_gap = max(market_config.peg_price - dai_price, 0.0)

    if peg_gap <= 0:
        return {
            "peg_gap": 0.0,
            "bad_debt_ratio": 0.0,
            "recovery_discount": 0.0,
            "arbitrage_recovery_pressure": 0.0,
            "policy_feedback_pressure": 0.0,
            "total_recovery_pressure": 0.0,
        }

    if confidence < market_config.min_recovery_confidence:
        confidence_effect = 0.0
    else:
        confidence_effect = confidence

    if total_debt_active > 0:
        bad_debt_ratio = active_bad_debt / total_debt_active
    else:
        bad_debt_ratio = 0.0

    recovery_discount = confidence_effect / (
        1.0 + market_config.bad_debt_recovery_drag * bad_debt_ratio
    )

    arbitrage_recovery_pressure = (
        market_config.arbitrage_recovery_strength
        * peg_gap
        * recovery_discount
    )

    policy_feedback_pressure = (
        market_config.policy_feedback_strength
        * peg_gap
        * recovery_discount
    )

    total_recovery_pressure = arbitrage_recovery_pressure + policy_feedback_pressure

    return {
        "peg_gap": peg_gap,
        "bad_debt_ratio": bad_debt_ratio,
        "recovery_discount": recovery_discount,
        "arbitrage_recovery_pressure": arbitrage_recovery_pressure,
        "policy_feedback_pressure": policy_feedback_pressure,
        "total_recovery_pressure": total_recovery_pressure,
    }


def update_dai_price(
    dai_price: float,
    confidence: float,
    panic_selling_pressure: float,
    market_config: DAIMarketConfig,
    rng: np.random.Generator | None = None,
    active_bad_debt: float = 0.0,
    total_debt_active: float = 0.0,
) -> tuple[float, dict]:
    """
    Update DAI price by one step.

    Price update rule:
        P_{t+1} = P_t + eta * net_pressure + noise

    where net_pressure = demand pressure - supply pressure.

    Parameters
    ----------
    dai_price:
        Current DAI price.
    confidence:
        Current confidence level.
    panic_selling_pressure:
        Additional panic selling pressure.
    market_config:
        DAIMarketConfig object.
    rng:
        Optional NumPy random generator.

    Returns
    -------
    tuple[float, dict]
        New DAI price and pressure details.
    """
    market_config.validate()

    pressures = calculate_dai_market_pressures(
        dai_price=dai_price,
        confidence=confidence,
        panic_selling_pressure=panic_selling_pressure,
        market_config=market_config,
    )

    # Update DAI market pricing using demand, supply, panic and recovery pressures.
    recovery_pressures = calculate_peg_recovery_pressure(
        dai_price=dai_price,
        confidence=confidence,
        active_bad_debt=active_bad_debt,
        total_debt_active=total_debt_active,
        market_config=market_config,
    )

    net_pressure = (
        pressures["net_pressure"]
        + recovery_pressures["total_recovery_pressure"]
    )

    if rng is None:
        rng = np.random.default_rng()
    noise = rng.normal(0.0, market_config.noise_std)

    new_price = dai_price + market_config.price_adjustment_speed * net_pressure + noise

    new_price = float(
        np.clip(new_price, market_config.min_price, market_config.max_price)
    )

    pressures.update(recovery_pressures)
    pressures["net_pressure"] = net_pressure
    pressures["noise"] = noise

    return new_price, pressures


if __name__ == "__main__":
    # Quick smoke test: PYTHONPATH=src python -m dai_sim.model.market

    market_config = DAIMarketConfig()
    rng = np.random.default_rng(42)

    test_cases = [
        {
            "name": "below peg, high confidence",
            "dai_price": 0.98,
            "confidence": 1.0,
            "panic_selling_pressure": 0.0,
        },
        {
            "name": "below peg, low confidence",
            "dai_price": 0.98,
            "confidence": 0.1,
            "panic_selling_pressure": 0.0,
        },
        {
            "name": "above peg",
            "dai_price": 1.02,
            "confidence": 1.0,
            "panic_selling_pressure": 0.0,
        },
        {
            "name": "panic below peg",
            "dai_price": 0.94,
            "confidence": 0.1,
            "panic_selling_pressure": 0.12,
        },
    ]

    for case in test_cases:
        new_price, pressures = update_dai_price(
            dai_price=case["dai_price"],
            confidence=case["confidence"],
            panic_selling_pressure=case["panic_selling_pressure"],
            market_config=market_config,
            rng=rng,
        )

        print(f"\n{case['name']}")
        print(f"old price: {case['dai_price']}")
        print(f"new price: {new_price}")
        print(pressures)
