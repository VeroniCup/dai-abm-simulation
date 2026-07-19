"""
price_process.py

Collateral price-path infrastructure for the DAI stability simulation.

This module retains the existing ETH price generators and provides a canonical
representation for aligned market and oracle price paths across collateral
types. Price generation remains transparent and controllable rather than trying
to reproduce complete crypto-asset market dynamics.

Main functions:
- generate_constant_price_path
- generate_shock_price_path
- generate_gbm_price_path
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
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


@dataclass(frozen=True)
class CollateralPricePaths:
    """
    Canonical aligned market and oracle price paths.

    Attributes
    ----------
    steps:
        One-dimensional integer simulation steps.
    market_prices:
        Market price arrays keyed by normalised collateral identifier.
    oracle_prices:
        Oracle price arrays keyed by the same collateral identifiers.

    Notes
    -----
    Every market and oracle path has exactly one value per simulation step.
    """

    steps: np.ndarray
    market_prices: dict[str, np.ndarray]
    oracle_prices: dict[str, np.ndarray]

    def __post_init__(self) -> None:
        steps = np.asarray(self.steps)
        if steps.ndim != 1:
            raise ValueError("steps must be one-dimensional.")
        if len(steps) == 0:
            raise ValueError("price paths must contain at least one step.")

        numeric_steps = steps.astype(float)
        if not np.isfinite(numeric_steps).all():
            raise ValueError("steps must contain only finite values.")
        if not np.equal(numeric_steps, np.floor(numeric_steps)).all():
            raise ValueError("steps must contain integer values.")

        integer_steps = numeric_steps.astype(int)
        if len(np.unique(integer_steps)) != len(integer_steps):
            raise ValueError("steps must not contain duplicates.")

        market_prices = _normalise_price_arrays(
            self.market_prices,
            expected_length=len(integer_steps),
            label="market",
        )
        oracle_prices = _normalise_price_arrays(
            self.oracle_prices,
            expected_length=len(integer_steps),
            label="oracle",
        )

        if set(market_prices) != set(oracle_prices):
            raise ValueError(
                "Market and oracle price paths must contain the same "
                "collateral types."
            )

        object.__setattr__(self, "steps", integer_steps)
        object.__setattr__(self, "market_prices", market_prices)
        object.__setattr__(self, "oracle_prices", oracle_prices)

    def __len__(self) -> int:
        """Return the number of aligned simulation steps."""
        return len(self.steps)

    def iter_price_maps(
        self,
    ) -> Iterator[tuple[int, dict[str, float], dict[str, float]]]:
        """Yield each step with its market and oracle price maps."""
        for index, step in enumerate(self.steps):
            market_at_step = {
                collateral_type: float(path[index])
                for collateral_type, path in self.market_prices.items()
            }
            oracle_at_step = {
                collateral_type: float(path[index])
                for collateral_type, path in self.oracle_prices.items()
            }

            yield int(step), market_at_step, oracle_at_step


PricePathValues = pd.DataFrame | pd.Series | np.ndarray | Sequence[float]
PricePathInput = (
    CollateralPricePaths
    | PricePathValues
    | Mapping[str, PricePathValues]
)


def _normalise_collateral_type(collateral_type: object) -> str:
    """Return a validated uppercase collateral identifier."""
    normalised_type = str(collateral_type).strip().upper()
    if not normalised_type:
        raise ValueError("Collateral price-path keys must not be empty.")
    return normalised_type


def _normalise_price_arrays(
    price_paths: Mapping[str, np.ndarray],
    expected_length: int,
    label: str,
) -> dict[str, np.ndarray]:
    """Validate and copy price arrays keyed by collateral type."""
    if not price_paths:
        raise ValueError(f"{label.capitalize()} price paths must not be empty.")

    normalised_paths: dict[str, np.ndarray] = {}

    for collateral_type, values in price_paths.items():
        normalised_type = _normalise_collateral_type(collateral_type)
        if normalised_type in normalised_paths:
            raise ValueError(
                f"Duplicate {label} price path for '{normalised_type}'."
            )

        path = np.asarray(values, dtype=float)
        if path.ndim != 1:
            raise ValueError(
                f"{label.capitalize()} price path for {normalised_type} "
                "must be one-dimensional."
            )
        if len(path) != expected_length:
            raise ValueError(
                f"{label.capitalize()} price path for {normalised_type} "
                f"has length {len(path)}; expected {expected_length}."
            )
        if not np.isfinite(path).all():
            raise ValueError(
                f"{label.capitalize()} price path for {normalised_type} "
                "must contain only finite values."
            )
        if (path <= 0).any():
            raise ValueError(
                f"{label.capitalize()} prices for {normalised_type} "
                "must be positive."
            )

        normalised_paths[normalised_type] = path.copy()

    return normalised_paths


def _extract_price_path_values(
    collateral_type: str,
    price_path: PricePathValues,
) -> tuple[np.ndarray | None, np.ndarray]:
    """Extract optional steps and prices from one external path value."""
    if isinstance(price_path, pd.DataFrame):
        steps = (
            price_path["step"].to_numpy()
            if "step" in price_path.columns
            else None
        )

        price_columns = (
            f"{collateral_type.lower()}_price",
            "price",
        )
        price_column = next(
            (column for column in price_columns if column in price_path.columns),
            None,
        )

        if price_column is None:
            raise ValueError(
                f"DataFrame price path for {collateral_type} must contain "
                f"'{price_columns[0]}' or 'price'."
            )

        values = price_path[price_column].to_numpy(dtype=float)
        return steps, values

    if isinstance(price_path, pd.Series):
        return None, price_path.to_numpy(dtype=float)

    if isinstance(price_path, (str, bytes)):
        raise TypeError("Price paths must be numeric sequences, not text.")

    values = np.asarray(price_path, dtype=float)
    return None, values


def _apply_oracle_delay(
    market_prices: np.ndarray,
    delay_steps: int,
) -> np.ndarray:
    """Apply the existing fixed-step oracle delay to one market price path."""
    if delay_steps < 0:
        raise ValueError("delay_steps cannot be negative.")

    delayed = market_prices.copy()
    if delay_steps == 0:
        return delayed

    delayed[:delay_steps] = market_prices[0]
    if delay_steps < len(market_prices):
        delayed[delay_steps:] = market_prices[:-delay_steps]

    return delayed


def normalise_collateral_price_paths(
    price_paths: PricePathInput,
    delay_steps: int = 0,
) -> CollateralPricePaths:
    """
    Convert supported external price paths into the canonical representation.

    Supported inputs are:

    - the legacy ETH DataFrame with ``step`` and ``eth_price`` columns;
    - a one-dimensional legacy ETH price sequence;
    - a mapping from collateral type to a DataFrame or numeric sequence;
    - an existing :class:`CollateralPricePaths` object.

    Oracle prices are derived independently for each collateral type using the
    same fixed delay. Existing ETH-only paths therefore retain their historical
    oracle behaviour.
    """
    if delay_steps < 0:
        raise ValueError("delay_steps cannot be negative.")

    if isinstance(price_paths, CollateralPricePaths):
        steps = price_paths.steps
        raw_market_prices: Mapping[str, np.ndarray] = price_paths.market_prices
    elif isinstance(price_paths, Mapping):
        if not price_paths:
            raise ValueError("Collateral price-path mapping must not be empty.")

        raw_market_prices_dict: dict[str, np.ndarray] = {}
        steps = None
        expected_length: int | None = None

        for collateral_type, price_path in price_paths.items():
            normalised_type = _normalise_collateral_type(collateral_type)
            if normalised_type in raw_market_prices_dict:
                raise ValueError(
                    f"Duplicate price path for '{normalised_type}'."
                )

            path_steps, values = _extract_price_path_values(
                normalised_type,
                price_path,
            )

            if values.ndim != 1:
                raise ValueError(
                    f"Price path for {normalised_type} must be one-dimensional."
                )

            if expected_length is None:
                expected_length = len(values)
            elif len(values) != expected_length:
                raise ValueError(
                    "All collateral price paths must have the same length."
                )

            if path_steps is not None:
                if steps is None:
                    steps = path_steps
                elif not np.array_equal(np.asarray(steps), path_steps):
                    raise ValueError(
                        "All collateral price paths must use identical steps."
                    )

            raw_market_prices_dict[normalised_type] = values

        if expected_length is None:
            raise ValueError("Collateral price paths must not be empty.")
        if steps is None:
            steps = np.arange(expected_length)

        raw_market_prices = raw_market_prices_dict
    else:
        steps, eth_prices = _extract_price_path_values("ETH", price_paths)
        if steps is None:
            steps = np.arange(len(eth_prices))
        raw_market_prices = {"ETH": eth_prices}

    normalised_market_prices = _normalise_price_arrays(
        raw_market_prices,
        expected_length=len(steps),
        label="market",
    )
    oracle_prices = {
        collateral_type: _apply_oracle_delay(path, delay_steps)
        for collateral_type, path in normalised_market_prices.items()
    }

    return CollateralPricePaths(
        steps=np.asarray(steps),
        market_prices=normalised_market_prices,
        oracle_prices=oracle_prices,
    )


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
    market_prices = delayed[price_col].to_numpy(dtype=float)
    delayed[oracle_col] = _apply_oracle_delay(market_prices, delay_steps)

    return delayed


if __name__ == "__main__":
    # Quick smoke test. Run:
    # python src/price_process.py
    config = PriceProcessConfig(n_steps=100, initial_price=2_000, random_seed=42)

    constant = generate_constant_price_path(config)
    shock = generate_shock_price_path(config, shock_time=30, shock_size=-0.43)
    gbm = generate_gbm_price_path(config)
    canonical = normalise_collateral_price_paths(
        {"ETH": shock},
        delay_steps=3,
    )

    print("Constant path:")
    print(constant.head())

    print("\nShock path around shock_time:")
    print(shock.iloc[27:34])

    print("\nGBM path:")
    print(gbm.head())

    print("\nCanonical ETH price maps around shock_time:")
    canonical_rows = list(canonical.iter_price_maps())
    print(canonical_rows[27:34])
