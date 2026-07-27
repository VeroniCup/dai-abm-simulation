"""
Opt-in empirical market-return block bootstrap for Tranche C.

Legacy GBM remains the default market process. This module constructs external
ETH/WBTC price paths from compact hourly log-return pools only when explicitly
selected by a Tranche C configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib

import numpy as np
import pandas as pd

from empirical_config import REPOSITORY_ROOT, sha256_file


DEFAULT_MARKET_GAS_POOL_PATH = (
    REPOSITORY_ROOT / "config" / "empirical" / "data" / "market_gas_hourly_pool.csv"
)
VALID_MARKET_MODES = {"legacy_gbm", "empirical_block_bootstrap"}
VALID_MARKET_POOLS = {"all_calibration", "normal", "stress"}
VALID_ALIGNMENT_MODES = {"shared_market_gas", "market_only"}
VALID_RETURN_TYPES = {"log_return"}

MARKET_GAS_POOL_COLUMNS = {
    "pool_row_id",
    "source_row",
    "timestamp_utc",
    "calibration_pool_label",
    "regime_label",
    "is_calibration",
    "is_withheld_ftx",
    "return_observation_valid",
    "eth_price_usd",
    "wbtc_price_usd",
    "eth_log_return",
    "wbtc_log_return",
    "median_effective_gas_price_gwei",
    "p90_effective_gas_price_gwei",
    "p99_effective_gas_price_gwei",
    "target_normalised_block_utilisation",
}


@dataclass(frozen=True)
class MarketProcessConfig:
    """Configuration for opt-in market path generation."""

    mode: str = "legacy_gbm"
    pool_path: Path | None = None
    pool_sha256: str | None = None
    pool_label: str = "all_calibration"
    block_length_hours: int = 168
    seed: int | None = None
    return_type: str = "log_return"
    alignment_mode: str = "shared_market_gas"
    withheld_period_policy: str = "exclude_ftx"
    shock_overlay_enabled: bool = False

    def validate(self) -> None:
        """Validate market-process controls."""
        if self.mode not in VALID_MARKET_MODES:
            raise ValueError(f"Unknown market process mode: {self.mode}.")
        if self.pool_label not in VALID_MARKET_POOLS:
            raise ValueError(f"Unknown market pool label: {self.pool_label}.")
        if self.block_length_hours <= 0:
            raise ValueError("market block length must be positive.")
        if self.return_type not in VALID_RETURN_TYPES:
            raise ValueError(f"Unknown market return type: {self.return_type}.")
        if self.alignment_mode not in VALID_ALIGNMENT_MODES:
            raise ValueError(f"Unknown market alignment mode: {self.alignment_mode}.")
        if self.withheld_period_policy != "exclude_ftx":
            raise ValueError("Only exclude_ftx is currently supported.")


@dataclass(frozen=True)
class MarketBootstrapResult:
    """Generated empirical price paths and sidecar provenance."""

    price_paths: dict[str, np.ndarray]
    sampled_rows: pd.DataFrame
    provenance: dict[str, Any]


def load_market_gas_pool(
    path: Path | str = DEFAULT_MARKET_GAS_POOL_PATH,
    expected_sha256: str | None = None,
) -> pd.DataFrame:
    """Load and validate the compact Tranche C hourly market/gas pool."""
    pool_path = Path(path)
    if expected_sha256 is not None:
        observed = sha256_file(pool_path)
        if observed != expected_sha256:
            raise ValueError(
                f"Market/gas pool checksum mismatch: expected {expected_sha256}, "
                f"observed {observed}."
            )
    pool = pd.read_csv(pool_path)
    missing = MARKET_GAS_POOL_COLUMNS - set(pool.columns)
    if missing:
        raise ValueError(f"Market/gas pool missing columns: {sorted(missing)}.")
    pool["timestamp_utc"] = pd.to_datetime(pool["timestamp_utc"], utc=True)
    if pool["timestamp_utc"].duplicated().any():
        raise ValueError("Market/gas pool contains duplicate timestamps.")
    if not pool["timestamp_utc"].is_monotonic_increasing:
        raise ValueError("Market/gas pool must be chronologically sorted.")
    for column in [
        "eth_price_usd",
        "wbtc_price_usd",
        "median_effective_gas_price_gwei",
        "p90_effective_gas_price_gwei",
        "p99_effective_gas_price_gwei",
    ]:
        pool[column] = pd.to_numeric(pool[column], errors="coerce")
        if pool[column].le(0).any() or not np.isfinite(pool[column]).all():
            raise ValueError(f"{column} must be finite and positive.")
    return pool


def _pool_mask(pool: pd.DataFrame, pool_label: str) -> pd.Series:
    if pool_label == "all_calibration":
        return pool["is_calibration"].astype(bool)
    return pool["is_calibration"].astype(bool) & pool["regime_label"].eq(pool_label)


def valid_block_starts(
    pool: pd.DataFrame,
    *,
    block_length_hours: int,
    pool_label: str = "all_calibration",
) -> list[int]:
    """Return deterministic valid moving-block start indexes."""
    if block_length_hours <= 0:
        raise ValueError("block_length_hours must be positive.")
    timestamps = pool["timestamp_utc"]
    hourly_steps = timestamps.diff().dropna().eq(pd.Timedelta(hours=1))
    if not hourly_steps.all():
        raise ValueError("Market/gas pool contains a timestamp gap.")

    eligible = (
        _pool_mask(pool, pool_label)
        & pool["return_observation_valid"].astype(bool)
        & ~pool["is_withheld_ftx"].astype(bool)
    ).to_numpy(dtype=bool)
    regimes = pool["regime_label"].to_numpy()
    starts: list[int] = []
    max_start = len(pool) - block_length_hours
    for start in range(max_start + 1):
        stop = start + block_length_hours
        window = eligible[start:stop]
        if len(window) != block_length_hours or not window.all():
            continue
        if pool_label in {"normal", "stress"} and not (regimes[start:stop] == pool_label).all():
            continue
        starts.append(start)
    return starts


def sample_market_gas_blocks(
    pool: pd.DataFrame,
    *,
    horizon: int,
    block_length_hours: int,
    seed: int | None,
    pool_label: str = "all_calibration",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Sample aligned market/gas rows using a moving-block bootstrap."""
    if horizon <= 0:
        raise ValueError("horizon must be positive.")
    starts = valid_block_starts(
        pool,
        block_length_hours=block_length_hours,
        pool_label=pool_label,
    )
    if not starts:
        raise ValueError("No valid empirical block starts are available.")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(horizon / block_length_hours))
    chosen_starts = rng.choice(np.asarray(starts, dtype=int), size=n_blocks, replace=True)
    pieces = [
        pool.iloc[start : start + block_length_hours].copy()
        for start in chosen_starts
    ]
    sampled = pd.concat(pieces, ignore_index=True).iloc[:horizon].copy()
    sampled.insert(0, "simulation_step", np.arange(horizon, dtype=int))
    final_block_length = horizon - block_length_hours * (n_blocks - 1)
    provenance = {
        "block_length_hours": block_length_hours,
        "n_blocks": n_blocks,
        "sampled_start_indexes": [int(value) for value in chosen_starts],
        "replacement_used": True,
        "final_truncated_block_length": int(final_block_length),
        "available_block_start_count": len(starts),
        "pool_label": pool_label,
    }
    return sampled, provenance


def prices_from_log_returns(
    sampled_rows: pd.DataFrame,
    *,
    initial_prices: dict[str, float],
) -> dict[str, np.ndarray]:
    """Construct positive price paths by applying sampled log returns."""
    required = {"ETH", "BTC"}
    if set(initial_prices) & required != required:
        raise ValueError("Initial prices must include ETH and BTC.")
    paths: dict[str, np.ndarray] = {}
    for collateral_type, column in (
        ("ETH", "eth_log_return"),
        ("BTC", "wbtc_log_return"),
    ):
        returns = pd.to_numeric(sampled_rows[column], errors="coerce").to_numpy(dtype=float)
        if np.isnan(returns).any() or not np.isfinite(returns).all():
            raise ValueError(f"{column} contains missing or non-finite returns.")
        prices = np.empty(len(returns), dtype=float)
        prices[0] = float(initial_prices[collateral_type])
        for index in range(1, len(returns)):
            prices[index] = prices[index - 1] * np.exp(returns[index])
        if not np.isfinite(prices).all() or (prices <= 0).any():
            raise ValueError(f"Generated {collateral_type} price path is invalid.")
        paths[collateral_type] = prices
    return paths


def generate_empirical_price_paths(
    *,
    n_steps: int,
    initial_prices: dict[str, float],
    config: MarketProcessConfig,
) -> MarketBootstrapResult:
    """Generate opt-in empirical ETH/BTC price paths."""
    config.validate()
    if config.mode != "empirical_block_bootstrap":
        raise ValueError("Empirical price path generation requires empirical_block_bootstrap.")
    pool_path = config.pool_path or DEFAULT_MARKET_GAS_POOL_PATH
    pool = load_market_gas_pool(pool_path, config.pool_sha256)
    sampled, provenance = sample_market_gas_blocks(
        pool,
        horizon=n_steps,
        block_length_hours=config.block_length_hours,
        seed=config.seed,
        pool_label=config.pool_label,
    )
    price_paths = prices_from_log_returns(sampled, initial_prices=initial_prices)
    provenance.update(
        {
            "market_process_mode": config.mode,
            "market_pool_path": str(Path(pool_path).relative_to(REPOSITORY_ROOT)),
            "market_pool_checksum": sha256_file(Path(pool_path)),
            "market_return_type": config.return_type,
            "market_alignment_mode": config.alignment_mode,
            "withheld_period_policy": config.withheld_period_policy,
            "shock_overlay_enabled": config.shock_overlay_enabled,
        }
    )
    return MarketBootstrapResult(
        price_paths=price_paths,
        sampled_rows=sampled,
        provenance=provenance,
    )
