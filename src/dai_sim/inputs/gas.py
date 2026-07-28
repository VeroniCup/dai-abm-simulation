"""
Opt-in empirical gas-input processes for Tranche C.

The simulator's legacy gas field is a scalar USD/DAI liquidation cost. This
module preserves that default and adds explicit empirical input generators
without changing keeper-profit equations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .configuration import REPOSITORY_ROOT, sha256_file


DEFAULT_LIQUIDATION_GAS_POOL_PATH = (
    REPOSITORY_ROOT / "config" / "empirical" / "data" / "liquidation_gas_pool.csv"
)
VALID_GAS_MODES = {"legacy_scalar", "empirical_components", "empirical_total_cost"}
VALID_ZERO_POLICIES = {"exclude_zero_primary", "include_zero_sensitivity"}
VALID_GAS_ALIGNMENT_MODES = {"shared_market_gas", "independent"}
VALID_NETWORK_GAS_COLUMNS = {
    "median_effective_gas_price_gwei",
    "p90_effective_gas_price_gwei",
    "p99_effective_gas_price_gwei",
}

LIQUIDATION_GAS_POOL_COLUMNS = {
    "gas_pool_row_id",
    "event_type",
    "sample_role",
    "regime_label",
    "is_primary_eligible",
    "is_zero_gas_observation",
    "gas_units",
    "effective_gas_price_gwei",
    "eth_price_usd",
    "transaction_gas_cost_eth",
    "transaction_gas_cost_usd",
}


def _provenance_path(path: Path) -> str:
    """Return a stable provenance path for repository and temporary artefacts."""
    try:
        return str(path.relative_to(REPOSITORY_ROOT))
    except ValueError:
        return str(path)


@dataclass(frozen=True)
class GasProcessConfig:
    """Configuration for one gas-input process."""

    mode: str = "legacy_scalar"
    pool_path: Path | None = None
    pool_sha256: str | None = None
    seed: int | None = None
    alignment_mode: str = "shared_market_gas"
    zero_observation_policy: str = "exclude_zero_primary"
    event_type: str = "clean_successful_take_transaction"
    cost_currency: str = "USD"
    network_gas_column: str = "median_effective_gas_price_gwei"

    def validate(self) -> None:
        """Validate gas-process controls."""
        if self.mode not in VALID_GAS_MODES:
            raise ValueError(f"Unknown gas process mode: {self.mode}.")
        if self.alignment_mode not in VALID_GAS_ALIGNMENT_MODES:
            raise ValueError(f"Unknown gas alignment mode: {self.alignment_mode}.")
        if self.zero_observation_policy not in VALID_ZERO_POLICIES:
            raise ValueError(
                f"Unknown gas zero-observation policy: {self.zero_observation_policy}."
            )
        if self.cost_currency != "USD":
            raise ValueError("Only USD gas costs are currently supported.")
        if self.network_gas_column not in VALID_NETWORK_GAS_COLUMNS:
            raise ValueError(f"Unknown network gas column: {self.network_gas_column}.")


@dataclass(frozen=True)
class GasProcessResult:
    """Generated gas-cost path and provenance."""

    gas_cost_usd: np.ndarray | None
    sampled_rows: pd.DataFrame | None
    provenance: dict[str, Any]


def load_liquidation_gas_pool(
    path: Path | str = DEFAULT_LIQUIDATION_GAS_POOL_PATH,
    expected_sha256: str | None = None,
) -> pd.DataFrame:
    """Load and validate the compact clean-Take gas pool."""
    pool_path = Path(path)
    if expected_sha256 is not None:
        observed = sha256_file(pool_path)
        if observed != expected_sha256:
            raise ValueError(
                f"Liquidation gas pool checksum mismatch: expected {expected_sha256}, "
                f"observed {observed}."
            )
    pool = pd.read_csv(pool_path)
    missing = LIQUIDATION_GAS_POOL_COLUMNS - set(pool.columns)
    if missing:
        raise ValueError(f"Liquidation gas pool missing columns: {sorted(missing)}.")
    for column in [
        "gas_units",
        "effective_gas_price_gwei",
        "eth_price_usd",
        "transaction_gas_cost_eth",
        "transaction_gas_cost_usd",
    ]:
        pool[column] = pd.to_numeric(pool[column], errors="coerce")
        if pool[column].isna().any() or not np.isfinite(pool[column]).all():
            raise ValueError(f"{column} must be finite.")
    if pool["gas_units"].le(0).any():
        raise ValueError("Liquidation gas pool contains non-positive gas units.")
    if pool["transaction_gas_cost_usd"].lt(0).any():
        raise ValueError("Liquidation gas pool contains negative USD costs.")
    return pool


def _eligible_gas_pool(pool: pd.DataFrame, config: GasProcessConfig) -> pd.DataFrame:
    eligible = pool.loc[pool["event_type"].eq(config.event_type)].copy()
    if config.zero_observation_policy == "exclude_zero_primary":
        eligible = eligible.loc[eligible["is_primary_eligible"].astype(bool)]
    if eligible.empty:
        raise ValueError("No eligible liquidation gas observations are available.")
    return eligible.reset_index(drop=True)


def sample_total_gas_costs(
    *,
    n_steps: int,
    config: GasProcessConfig,
) -> GasProcessResult:
    """Sample a scalar USD gas-cost path from clean liquidation transactions."""
    config.validate()
    if config.mode != "empirical_total_cost":
        raise ValueError("Total-cost sampling requires empirical_total_cost mode.")
    if n_steps <= 0:
        raise ValueError("n_steps must be positive.")
    pool_path = config.pool_path or DEFAULT_LIQUIDATION_GAS_POOL_PATH
    pool = load_liquidation_gas_pool(pool_path, config.pool_sha256)
    eligible = _eligible_gas_pool(pool, config)
    rng = np.random.default_rng(config.seed)
    draw_indexes = rng.choice(eligible.index.to_numpy(), size=n_steps, replace=True)
    sampled = eligible.loc[draw_indexes].copy().reset_index(drop=True)
    sampled.insert(0, "simulation_step", np.arange(n_steps, dtype=int))
    costs = sampled["transaction_gas_cost_usd"].to_numpy(dtype=float)
    if (costs < 0).any() or not np.isfinite(costs).all():
        raise ValueError("Sampled gas costs must be finite and non-negative.")
    provenance = {
        "gas_process_mode": config.mode,
        "gas_pool_path": _provenance_path(Path(pool_path)),
        "gas_pool_checksum": sha256_file(Path(pool_path)),
        "gas_seed": config.seed,
        "gas_alignment_mode": config.alignment_mode,
        "gas_event_type": config.event_type,
        "gas_zero_observation_policy": config.zero_observation_policy,
        "gas_cost_currency": config.cost_currency,
        "eligible_pool_size": int(len(eligible)),
        "zero_observations_in_source_pool": int(pool["is_zero_gas_observation"].sum()),
        "replacement_used": True,
    }
    return GasProcessResult(gas_cost_usd=costs, sampled_rows=sampled, provenance=provenance)


def component_gas_costs(
    *,
    sampled_market_gas_rows: pd.DataFrame,
    simulated_eth_prices: Sequence[float],
    config: GasProcessConfig,
) -> GasProcessResult:
    """
    Calculate component gas costs from gas units, network gas and simulated ETH.

    This is an input-generator compatibility layer. The existing simulator
    still consumes the resulting USD scalar per liquidation opportunity.
    """
    config.validate()
    if config.mode != "empirical_components":
        raise ValueError("Component gas sampling requires empirical_components mode.")
    pool_path = config.pool_path or DEFAULT_LIQUIDATION_GAS_POOL_PATH
    pool = load_liquidation_gas_pool(pool_path, config.pool_sha256)
    eligible = _eligible_gas_pool(pool, config)
    rng = np.random.default_rng(config.seed)
    n_steps = len(sampled_market_gas_rows)
    eth_price = np.asarray(simulated_eth_prices, dtype=float)
    if len(eth_price) != n_steps:
        raise ValueError(
            "simulated_eth_prices length must match sampled_market_gas_rows."
        )
    if not np.isfinite(eth_price).all() or (eth_price <= 0).any():
        raise ValueError("simulated_eth_prices must be finite and positive.")
    draw_indexes = rng.choice(eligible.index.to_numpy(), size=n_steps, replace=True)
    units = eligible.loc[draw_indexes, "gas_units"].to_numpy(dtype=float)
    gas_price = pd.to_numeric(
        sampled_market_gas_rows[config.network_gas_column],
        errors="coerce",
    ).to_numpy(dtype=float)
    if (units < 0).any() or not np.isfinite(units).all():
        raise ValueError("Sampled gas units must be finite and non-negative.")
    if (gas_price < 0).any() or not np.isfinite(gas_price).all():
        raise ValueError("Sampled gas prices must be finite and non-negative.")
    costs = units * gas_price * 1e-9 * eth_price
    if (costs < 0).any() or not np.isfinite(costs).all():
        raise ValueError("Component gas costs must be finite and non-negative.")
    sampled = eligible.loc[draw_indexes].copy().reset_index(drop=True)
    sampled.insert(0, "simulation_step", np.arange(n_steps, dtype=int))
    sampled["network_gas_price_gwei"] = gas_price
    sampled["runtime_eth_price_usd"] = eth_price
    sampled["component_transaction_gas_cost_usd"] = costs
    provenance = {
        "gas_process_mode": config.mode,
        "gas_pool_path": _provenance_path(Path(pool_path)),
        "gas_pool_checksum": sha256_file(Path(pool_path)),
        "gas_seed": config.seed,
        "gas_alignment_mode": config.alignment_mode,
        "gas_event_type": config.event_type,
        "gas_zero_observation_policy": config.zero_observation_policy,
        "network_gas_column": config.network_gas_column,
        "gas_cost_currency": config.cost_currency,
        "eligible_pool_size": int(len(eligible)),
        "zero_observations_in_source_pool": int(pool["is_zero_gas_observation"].sum()),
        "replacement_used": True,
        "eth_price_source": "reconstructed_simulated_eth_price_path",
        "timestep_price_convention": (
            "gas cost at simulation step t uses the simulated ETH price consumed "
            "by the simulator at step t"
        ),
        "formula": (
            "gas_units * sampled_gas_price_gwei * 1e-9 * "
            "simulated_eth_price_usd"
        ),
    }
    return GasProcessResult(gas_cost_usd=costs, sampled_rows=sampled, provenance=provenance)


def legacy_scalar_gas() -> GasProcessResult:
    """Return explicit provenance for the unchanged legacy scalar gas path."""
    return GasProcessResult(
        gas_cost_usd=None,
        sampled_rows=None,
        provenance={
            "gas_process_mode": "legacy_scalar",
            "legacy_default_preserved": True,
        },
    )
