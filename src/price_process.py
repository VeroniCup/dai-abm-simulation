"""
price_process.py

ETH price process generators for the DAI stability simulation.

This module provides simple price paths used to stress-test the simulated
DAI system. We start with transparent and controllable processes rather than
trying to reproduce real ETH market dynamics.

Main functions:
- generate_constant_price_path
- generate_shock_price_path
- generate_gbm_price_path
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PriceProcessConfig:
    """
    Configuration for ETH price path generation.

    Attributes
    ----------
    n_steps:
        Number of time steps in the simulation.
    initial_price:
        Initial ETH price.
    random_seed:
        Optional seed for reproducibility.
    """

    n_steps: int = 200
    initial_price: float = 2_000.0
    random_seed: Optional[int] = 42

    def validate(self) -> None:
        """Validate basic configuration values."""
        if self.n_steps <= 0:
            raise ValueError("n_steps must be positive.")
        if self.initial_price <= 0:
            raise ValueError("initial_price must be positive.")


def generate_constant_price_path(
    config: PriceProcessConfig,
) -> pd.DataFrame:
    """
    Generate a constant ETH price path.

    This is useful for debugging. If ETH price never changes, then any
    liquidations or DAI depegging should come from other parts of the model,
    not from collateral shocks.

    Parameters
    ----------
    config:
        PriceProcessConfig object.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: step, eth_price, log_return.
    """
    config.validate()

    prices = np.full(config.n_steps, config.initial_price, dtype=float)
    log_returns = np.zeros(config.n_steps, dtype=float)

    return pd.DataFrame(
        {
            "step": np.arange(config.n_steps),
            "eth_price": prices,
            "log_return": log_returns,
        }
    )


def generate_gbm_price_path(
    config: PriceProcessConfig,
    mu: float = 0.0,
    sigma: float = 0.80,
    dt: float = 1 / 365,
    floor_price: float = 1e-8,
) -> pd.DataFrame:
    """
    Generate a Geometric Brownian Motion ETH price path.

    The process is:

        dS_t = mu * S_t * dt + sigma * S_t * dW_t

    Discretised as:

        S_{t+1} = S_t * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*epsilon_t)

    Parameters
    ----------
    config:
        PriceProcessConfig object.
    mu:
        Annualised drift.
    sigma:
        Annualised volatility.
    dt:
        Time step size. Default is 1/365, interpreted as daily steps.
    floor_price:
        Minimum allowed price to avoid numerical issues.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: step, eth_price, log_return.
    """
    config.validate()

    if sigma < 0:
        raise ValueError("sigma must be non-negative.")
    if dt <= 0:
        raise ValueError("dt must be positive.")
    if floor_price <= 0:
        raise ValueError("floor_price must be positive.")

    rng = np.random.default_rng(config.random_seed)

    prices = np.empty(config.n_steps, dtype=float)
    prices[0] = config.initial_price

    log_returns = np.zeros(config.n_steps, dtype=float)

    for t in range(1, config.n_steps):
        epsilon = rng.normal(0.0, 1.0)
        log_return = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * epsilon
        log_returns[t] = log_return
        prices[t] = max(prices[t - 1] * np.exp(log_return), floor_price)

    return pd.DataFrame(
        {
            "step": np.arange(config.n_steps),
            "eth_price": prices,
            "log_return": log_returns,
        }
    )


def generate_shock_price_path(
    config: PriceProcessConfig,
    shock_time: int = 50,
    shock_size: float = -0.43,
    pre_shock_drift: float = 0.0,
    post_shock_drift: float = 0.0,
) -> pd.DataFrame:
    """
    Generate a deterministic ETH price path with a one-time shock.

    Example:
    shock_size = -0.43 means ETH drops by 43% at shock_time.

    Parameters
    ----------
    config:
        PriceProcessConfig object.
    shock_time:
        Time step at which the shock occurs.
    shock_size:
        Percentage shock applied to price.
        Example: -0.43 means a 43% drop; 0.10 means a 10% rise.
    pre_shock_drift:
        Optional deterministic percentage drift applied before the shock
        at each time step.
    post_shock_drift:
        Optional deterministic percentage drift applied after the shock
        at each time step.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: step, eth_price, log_return.
    """
    config.validate()

    if not 0 <= shock_time < config.n_steps:
        raise ValueError("shock_time must be within [0, n_steps - 1].")
    if shock_size <= -1:
        raise ValueError("shock_size must be greater than -1.")
    if pre_shock_drift <= -1:
        raise ValueError("pre_shock_drift must be greater than -1.")
    if post_shock_drift <= -1:
        raise ValueError("post_shock_drift must be greater than -1.")

    prices = np.empty(config.n_steps, dtype=float)
    prices[0] = config.initial_price

    for t in range(1, config.n_steps):
        if t < shock_time:
            prices[t] = prices[t - 1] * (1.0 + pre_shock_drift)
        elif t == shock_time:
            prices[t] = prices[t - 1] * (1.0 + shock_size)
        else:
            prices[t] = prices[t - 1] * (1.0 + post_shock_drift)

    log_returns = np.zeros(config.n_steps, dtype=float)
    log_returns[1:] = np.diff(np.log(prices))

    return pd.DataFrame(
        {
            "step": np.arange(config.n_steps),
            "eth_price": prices,
            "log_return": log_returns,
        }
    )


def generate_shock_recovery_price_path(
    config: PriceProcessConfig,
    shock_time: int = 30,
    shock_size: float = -0.43,
    recovery_start: int = 40,
    recovery_end: int = 90,
    recovery_fraction: float = 0.5,
) -> pd.DataFrame:
    """
    Generate an ETH price path with a discrete shock followed by gradual recovery.

    The price first follows a constant path at the initial price. At shock_time,
    it falls by shock_size. From recovery_start to recovery_end, it gradually
    recovers a fraction of the lost value.

    Parameters
    ----------
    config:
        Price process configuration.
    shock_time:
        Step at which the ETH shock occurs.
    shock_size:
        Proportional shock. Example: -0.43 means a 43% fall.
    recovery_start:
        Step at which recovery begins.
    recovery_end:
        Step by which recovery is completed.
    recovery_fraction:
        Fraction of the lost value that is recovered.
        Example: 0.5 means ETH recovers 50% of the initial loss.

    Returns
    -------
    pd.DataFrame
        Price path with columns step, eth_price and log_return.
    """
    config.validate()

    if not 0 <= shock_time < config.n_steps:
        raise ValueError("shock_time must be within the simulation horizon.")
    if shock_size >= 0:
        raise ValueError("shock_size should be negative for a downward shock.")
    if recovery_start < shock_time:
        raise ValueError("recovery_start must be greater than or equal to shock_time.")
    if recovery_end <= recovery_start:
        raise ValueError("recovery_end must be greater than recovery_start.")
    if not 0.0 <= recovery_fraction <= 1.0:
        raise ValueError("recovery_fraction must be between 0 and 1.")

    steps = np.arange(config.n_steps)

    initial_price = config.initial_price
    shocked_price = initial_price * (1.0 + shock_size)
    lost_value = initial_price - shocked_price
    recovered_price = shocked_price + recovery_fraction * lost_value

    prices = np.full(config.n_steps, initial_price, dtype=float)

    for step in range(config.n_steps):
        if step < shock_time:
            prices[step] = initial_price
        elif step < recovery_start:
            prices[step] = shocked_price
        elif step <= recovery_end:
            recovery_progress = (step - recovery_start) / (recovery_end - recovery_start)
            prices[step] = shocked_price + recovery_progress * (
                recovered_price - shocked_price
            )
        else:
            prices[step] = recovered_price

    log_returns = np.zeros(config.n_steps)
    log_returns[1:] = np.diff(np.log(prices))

    return pd.DataFrame(
        {
            "step": steps,
            "eth_price": prices,
            "log_return": log_returns,
        }
    )


def add_shock_to_existing_path(
    price_path: pd.DataFrame,
    shock_time: int,
    shock_size: float,
    price_col: str = "eth_price",
) -> pd.DataFrame:
    """
    Apply a one-time percentage shock to an existing ETH price path.

    This is useful if we later use historical ETH prices or GBM paths and
    want to impose an additional stress event.

    Parameters
    ----------
    price_path:
        Existing DataFrame containing ETH prices.
    shock_time:
        Time step at which the shock occurs.
    shock_size:
        Percentage shock applied from shock_time onward.
        Example: -0.43 means prices from shock_time onward are multiplied by 0.57.
    price_col:
        Name of the price column.

    Returns
    -------
    pd.DataFrame
        New DataFrame with shocked ETH price path.
    """
    if price_col not in price_path.columns:
        raise ValueError(f"{price_col} not found in price_path.")
    if not 0 <= shock_time < len(price_path):
        raise ValueError("shock_time must be within the price_path length.")
    if shock_size <= -1:
        raise ValueError("shock_size must be greater than -1.")

    shocked = price_path.copy()
    shocked.loc[shock_time:, price_col] = shocked.loc[shock_time:, price_col] * (
        1.0 + shock_size
    )

    prices = shocked[price_col].to_numpy(dtype=float)
    log_returns = np.zeros(len(shocked), dtype=float)
    log_returns[1:] = np.diff(np.log(prices))
    shocked["log_return"] = log_returns

    return shocked


def add_oracle_price(
    price_path: pd.DataFrame,
    delay_steps: int = 0,
    price_col: str = "eth_price",
    oracle_col: str = "oracle_eth_price",
) -> pd.DataFrame:
    """
    Add a delayed oracle ETH price column to a price path.

    The market price represents the true ETH market price.
    The oracle price represents the price used by the simulated protocol
    for collateral ratio checks and liquidation triggers.

    If delay_steps = 0, oracle price equals market price.
    If delay_steps = 3, oracle price at step t equals market price from step t-3.

    Parameters
    ----------
    price_path:
        DataFrame containing an ETH market price column.
    delay_steps:
        Number of time steps by which the oracle price lags.
    price_col:
        Name of the market ETH price column.
    oracle_col:
        Name of the delayed oracle price column.

    Returns
    -------
    pd.DataFrame
        Price path with oracle price column added.
    """
    if delay_steps < 0:
        raise ValueError("delay_steps cannot be negative.")
    if price_col not in price_path.columns:
        raise ValueError(f"{price_col} not found in price_path.")

    delayed = price_path.copy()

    if delay_steps == 0:
        delayed[oracle_col] = delayed[price_col]
    else:
        delayed[oracle_col] = delayed[price_col].shift(delay_steps)
        delayed[oracle_col] = delayed[oracle_col].fillna(delayed[price_col].iloc[0])

    return delayed


if __name__ == "__main__":
    # Quick smoke test. Run:
    # python src/price_process.py
    config = PriceProcessConfig(n_steps=100, initial_price=2_000, random_seed=42)

    constant = generate_constant_price_path(config)
    shock = generate_shock_price_path(config, shock_time=30, shock_size=-0.43)
    gbm = generate_gbm_price_path(config)

    print("Constant path:")
    print(constant.head())

    print("\nShock path around shock_time:")
    print(shock.iloc[27:34])

    print("\nGBM path:")
    print(gbm.head())