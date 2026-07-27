"""
Opt-in liquidation-demand processes for empirical Tranche D.

The default mode preserves the existing simulator behaviour: every unsafe
vault is considered by the legacy liquidation routine. The empirical mode adds
a bounded demand layer before keeper capacity and profitability are applied.
It does not change keeper-profit equations or vault accounting.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib

import numpy as np
import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    """Return the SHA-256 checksum of a local file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


DEFAULT_LIQUIDATION_ARRIVAL_POOL_PATH = (
    REPOSITORY_ROOT / "config" / "empirical" / "data" / "liquidation_arrival_hourly_pool.csv"
)

VALID_LIQUIDATION_DEMAND_MODES = {"legacy_all_eligible", "empirical_hurdle_count"}
VALID_HURDLE_ESTIMATORS = {
    "conditional_start_inventory_positive",
    "unconditional_activity",
}
VALID_POSITIVE_COUNT_MODES = {"empirical_positive_hour_counts"}
VALID_COUNT_TRUNCATION_POLICIES = {"truncate_to_inventory_then_capacity"}

LIQUIDATION_ARRIVAL_POOL_COLUMNS = {
    "arrival_pool_row_id",
    "relative_hour",
    "timestamp_utc",
    "source_window",
    "empirical_regime_label",
    "liquidatable_vault_count",
    "liquidatable_share",
    "bark_count",
    "grab_count",
    "activity_indicator",
    "positive_count_eligible",
    "sequence_id",
}


@dataclass(frozen=True)
class LiquidationDemandConfig:
    """Configuration for the optional liquidation-demand layer."""

    mode: str = "legacy_all_eligible"
    pool_path: Path | None = None
    pool_sha256: str | None = None
    seed: int | None = None
    hurdle_probability: float | None = None
    hurdle_estimator: str = "conditional_start_inventory_positive"
    positive_count_mode: str = "empirical_positive_hour_counts"
    sequence_mode: str = "none"
    inventory_conditioning: str = "current_liquidatable_inventory_positive"
    count_truncation_policy: str = "truncate_to_inventory_then_capacity"

    def validate(self) -> None:
        """Validate demand-mode controls."""
        if self.mode not in VALID_LIQUIDATION_DEMAND_MODES:
            raise ValueError(f"Unknown liquidation demand mode: {self.mode}.")
        if self.hurdle_estimator not in VALID_HURDLE_ESTIMATORS:
            raise ValueError(f"Unknown hurdle estimator: {self.hurdle_estimator}.")
        if self.positive_count_mode not in VALID_POSITIVE_COUNT_MODES:
            raise ValueError(f"Unknown positive-count mode: {self.positive_count_mode}.")
        if self.sequence_mode != "none":
            raise ValueError("Only sequence_mode='none' is implemented in Tranche D.")
        if self.count_truncation_policy not in VALID_COUNT_TRUNCATION_POLICIES:
            raise ValueError(
                f"Unknown count truncation policy: {self.count_truncation_policy}."
            )
        if self.hurdle_probability is not None:
            if not 0 <= self.hurdle_probability <= 1:
                raise ValueError("hurdle_probability must lie in [0, 1].")


@dataclass(frozen=True)
class LiquidationDemandDecision:
    """One timestep's demand, capacity and attempt-budget decision."""

    step: int
    liquidatable_inventory: int
    activity_draw: bool
    raw_positive_count_draw: int
    sampled_demand: int
    bounded_demand: int
    keeper_capacity: int | None
    attempt_budget: int
    demand_truncated_by_inventory: int
    demand_truncated_by_capacity: int
    demand_inactive_unresolved: int
    inventory_not_sampled_unresolved: int
    end_of_step_unresolved_inventory: int | None = None

    def as_record(self) -> dict[str, Any]:
        """Return a deterministic diagnostics record."""
        return {
            "step": self.step,
            "liquidatable_inventory": self.liquidatable_inventory,
            "activity_draw": self.activity_draw,
            "raw_positive_count_draw": self.raw_positive_count_draw,
            "sampled_demand": self.sampled_demand,
            "bounded_demand": self.bounded_demand,
            "keeper_capacity": self.keeper_capacity,
            "attempt_budget": self.attempt_budget,
            "demand_truncated_by_inventory": self.demand_truncated_by_inventory,
            "demand_truncated_by_capacity": self.demand_truncated_by_capacity,
            "demand_inactive_unresolved": self.demand_inactive_unresolved,
            "inventory_not_sampled_unresolved": self.inventory_not_sampled_unresolved,
            "end_of_step_unresolved_inventory": self.end_of_step_unresolved_inventory,
        }


def load_liquidation_arrival_pool(
    path: Path | str = DEFAULT_LIQUIDATION_ARRIVAL_POOL_PATH,
    expected_sha256: str | None = None,
) -> pd.DataFrame:
    """Load and validate the compact liquidation-arrival runtime pool."""
    pool_path = Path(path)
    if expected_sha256 is not None:
        observed = sha256_file(pool_path)
        if observed != expected_sha256:
            raise ValueError(
                "Liquidation arrival pool checksum mismatch: "
                f"expected {expected_sha256}, observed {observed}."
            )
    pool = pd.read_csv(pool_path)
    missing = LIQUIDATION_ARRIVAL_POOL_COLUMNS - set(pool.columns)
    if missing:
        raise ValueError(
            f"Liquidation arrival pool missing columns: {sorted(missing)}."
        )
    pool["timestamp_utc"] = pd.to_datetime(pool["timestamp_utc"], utc=True)
    if pool["timestamp_utc"].duplicated().any():
        raise ValueError("Liquidation arrival pool contains duplicate timestamps.")
    if not pool["timestamp_utc"].is_monotonic_increasing:
        raise ValueError("Liquidation arrival pool must be chronologically sorted.")
    for column in [
        "liquidatable_vault_count",
        "bark_count",
        "grab_count",
        "activity_indicator",
        "positive_count_eligible",
    ]:
        values = pd.to_numeric(pool[column], errors="coerce")
        if values.isna().any() or (values < 0).any():
            raise ValueError(f"{column} must be non-negative and finite.")
        pool[column] = values.astype(int)
    pool["liquidatable_share"] = pd.to_numeric(
        pool["liquidatable_share"],
        errors="coerce",
    )
    if pool["liquidatable_share"].isna().any() or (pool["liquidatable_share"] < 0).any():
        raise ValueError("liquidatable_share must be non-negative and finite.")
    return pool


def arrival_pool_statistics(pool: pd.DataFrame) -> dict[str, Any]:
    """Return source statistics used for provenance and diagnostics."""
    positive = pool.loc[pool["positive_count_eligible"].astype(bool), "grab_count"]
    conditional_denominator = pool["liquidatable_vault_count"] > 0
    conditional_activity = (
        conditional_denominator & pool["activity_indicator"].astype(bool)
    )
    if conditional_denominator.sum() == 0:
        conditional_probability = None
    else:
        conditional_probability = float(
            conditional_activity.sum() / conditional_denominator.sum()
        )
    return {
        "row_count": int(len(pool)),
        "activity_count": int(pool["activity_indicator"].sum()),
        "zero_hour_share": float(1.0 - pool["activity_indicator"].mean()),
        "unconditional_activity_probability": float(pool["activity_indicator"].mean()),
        "conditional_inventory_positive_hours": int(conditional_denominator.sum()),
        "conditional_activity_count": int(conditional_activity.sum()),
        "conditional_activity_probability": conditional_probability,
        "positive_count_pool_size": int(len(positive)),
        "positive_count_minimum": int(positive.min()) if len(positive) else None,
        "positive_count_maximum": int(positive.max()) if len(positive) else None,
        "positive_count_mean": float(positive.mean()) if len(positive) else None,
        "positive_count_median": float(positive.median()) if len(positive) else None,
        "source_maximum_liquidatable_share": float(pool["liquidatable_share"].max()),
    }


class LiquidationDemandProcess:
    """Stateful RNG-backed liquidation-demand sampler."""

    def __init__(self, config: LiquidationDemandConfig):
        config.validate()
        self.config = config
        self.rng = np.random.default_rng(config.seed)
        self.pool: pd.DataFrame | None = None
        self.positive_counts: np.ndarray = np.asarray([], dtype=int)
        self.statistics: dict[str, Any] = {}
        if config.mode == "empirical_hurdle_count":
            pool_path = config.pool_path or DEFAULT_LIQUIDATION_ARRIVAL_POOL_PATH
            self.pool = load_liquidation_arrival_pool(pool_path, config.pool_sha256)
            self.statistics = arrival_pool_statistics(self.pool)
            self.positive_counts = self.pool.loc[
                self.pool["positive_count_eligible"].astype(bool),
                "grab_count",
            ].to_numpy(dtype=int)
            if len(self.positive_counts) == 0:
                raise ValueError("No positive liquidation counts are available.")
            if config.hurdle_probability is None:
                probability_key = (
                    "conditional_activity_probability"
                    if config.hurdle_estimator == "conditional_start_inventory_positive"
                    else "unconditional_activity_probability"
                )
                probability = self.statistics[probability_key]
                if probability is None:
                    raise ValueError("Selected hurdle probability is unavailable.")
                self.hurdle_probability = float(probability)
            else:
                self.hurdle_probability = float(config.hurdle_probability)
        else:
            self.hurdle_probability = 1.0

    def sample_step(
        self,
        *,
        step: int,
        liquidatable_inventory: int,
        keeper_capacity: int | None,
    ) -> LiquidationDemandDecision:
        """Draw one demand decision for the current unsafe inventory."""
        if liquidatable_inventory < 0:
            raise ValueError("liquidatable_inventory cannot be negative.")
        if keeper_capacity is not None and keeper_capacity <= 0:
            raise ValueError("keeper_capacity must be positive or None.")

        if self.config.mode == "legacy_all_eligible":
            bounded = int(liquidatable_inventory)
            attempt_budget = (
                bounded
                if keeper_capacity is None
                else min(bounded, int(keeper_capacity))
            )
            return LiquidationDemandDecision(
                step=step,
                liquidatable_inventory=int(liquidatable_inventory),
                activity_draw=liquidatable_inventory > 0,
                raw_positive_count_draw=int(liquidatable_inventory),
                sampled_demand=int(liquidatable_inventory),
                bounded_demand=bounded,
                keeper_capacity=keeper_capacity,
                attempt_budget=attempt_budget,
                demand_truncated_by_inventory=0,
                demand_truncated_by_capacity=bounded - attempt_budget,
                demand_inactive_unresolved=0,
                inventory_not_sampled_unresolved=0,
            )

        if liquidatable_inventory == 0:
            return LiquidationDemandDecision(
                step=step,
                liquidatable_inventory=0,
                activity_draw=False,
                raw_positive_count_draw=0,
                sampled_demand=0,
                bounded_demand=0,
                keeper_capacity=keeper_capacity,
                attempt_budget=0,
                demand_truncated_by_inventory=0,
                demand_truncated_by_capacity=0,
                demand_inactive_unresolved=0,
                inventory_not_sampled_unresolved=0,
            )

        active = bool(self.rng.random() < self.hurdle_probability)
        raw_count = (
            int(self.rng.choice(self.positive_counts, replace=True))
            if active
            else 0
        )
        sampled = raw_count if active else 0
        bounded = min(sampled, int(liquidatable_inventory))
        capacity = (
            bounded
            if keeper_capacity is None
            else min(bounded, int(keeper_capacity))
        )
        inactive_unresolved = int(liquidatable_inventory) if not active else 0
        not_sampled_unresolved = (
            0 if not active else int(liquidatable_inventory) - bounded
        )
        return LiquidationDemandDecision(
            step=step,
            liquidatable_inventory=int(liquidatable_inventory),
            activity_draw=active,
            raw_positive_count_draw=raw_count,
            sampled_demand=sampled,
            bounded_demand=bounded,
            keeper_capacity=keeper_capacity,
            attempt_budget=capacity,
            demand_truncated_by_inventory=max(sampled - bounded, 0),
            demand_truncated_by_capacity=max(bounded - capacity, 0),
            demand_inactive_unresolved=inactive_unresolved,
            inventory_not_sampled_unresolved=not_sampled_unresolved,
        )

    def provenance(self) -> dict[str, Any]:
        """Return deterministic demand-process provenance."""
        pool_path = self.config.pool_path or DEFAULT_LIQUIDATION_ARRIVAL_POOL_PATH
        result = {
            "liquidation_demand_mode": self.config.mode,
            "liquidation_arrival_seed": self.config.seed,
            "hurdle_estimator": self.config.hurdle_estimator,
            "hurdle_probability": self.hurdle_probability,
            "positive_count_mode": self.config.positive_count_mode,
            "sequence_mode": self.config.sequence_mode,
            "inventory_conditioning": self.config.inventory_conditioning,
            "count_truncation_policy": self.config.count_truncation_policy,
            "hourly_timestep_interpretation": True,
        }
        if self.config.mode == "empirical_hurdle_count":
            result.update(
                {
                    "liquidation_arrival_pool_path": str(
                        Path(pool_path).relative_to(REPOSITORY_ROOT)
                    ),
                    "liquidation_arrival_pool_sha256": sha256_file(Path(pool_path)),
                    **self.statistics,
                }
            )
        return result
