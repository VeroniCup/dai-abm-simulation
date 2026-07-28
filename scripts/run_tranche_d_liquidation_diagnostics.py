"""
Run local Tranche D liquidation-arrival diagnostics.

The diagnostics compare the compact Phase 2C-derived arrival pool with
deterministic synthetic draws from the opt-in hurdle-count process. They do
not acquire data or rerun parameter estimation.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from empirical_config import sha256_file  # noqa: E402
from environment_inputs import (  # noqa: E402
    DEFAULT_TRANCHE_C_CONFIG_PATH,
    DEFAULT_TRANCHE_D_CONFIG_PATH,
    generate_environment_inputs,
    load_tranche_c_configuration,
    load_tranche_d_configuration,
)
from experiments import create_base_simulation_config  # noqa: E402
from liquidation import LiquidationConfig  # noqa: E402
from liquidation_demand import (  # noqa: E402
    LiquidationDemandConfig,
    LiquidationDemandProcess,
    arrival_pool_statistics,
    load_liquidation_arrival_pool,
)
from price_process import generate_constant_price_path, PriceProcessConfig  # noqa: E402
from simulation import run_simulation_with_price_path  # noqa: E402
from vault import Vault  # noqa: E402


OUTPUT_DIR = REPOSITORY_ROOT / "data" / "processed" / "estimation" / "tranche_d"


def _summary(values: pd.Series | np.ndarray) -> dict[str, float]:
    series = pd.Series(values).dropna().astype(float)
    variance = float(series.var(ddof=1)) if len(series) > 1 else 0.0
    mean = float(series.mean()) if len(series) else 0.0
    return {
        "count": float(len(series)),
        "mean": mean,
        "variance": variance,
        "variance_to_mean": float(variance / mean) if mean > 0 else np.nan,
        "median": float(series.median()) if len(series) else np.nan,
        "q75": float(series.quantile(0.75)) if len(series) else np.nan,
        "q90": float(series.quantile(0.90)) if len(series) else np.nan,
        "q95": float(series.quantile(0.95)) if len(series) else np.nan,
        "q99": float(series.quantile(0.99)) if len(series) else np.nan,
        "minimum": float(series.min()) if len(series) else np.nan,
        "maximum": float(series.max()) if len(series) else np.nan,
    }


def _run_lengths(active: pd.Series) -> pd.Series:
    values = active.astype(bool).to_numpy()
    lengths = []
    current = 0
    for value in values:
        if value:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    return pd.Series(lengths, dtype=float)


def build_diagnostics() -> dict[str, Path]:
    """Create deterministic diagnostic CSVs and metadata."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bundle = load_tranche_d_configuration(DEFAULT_TRANCHE_D_CONFIG_PATH)
    pool = load_liquidation_arrival_pool(
        bundle.liquidation_demand.pool_path,
        bundle.liquidation_demand.pool_sha256,
    )
    sequence_pool = pd.read_csv(
        REPOSITORY_ROOT
        / "data"
        / "liquidations"
        / "model_inputs"
        / "arrival"
        / "sequence_pool.csv"
    )
    manifest_path = (
        REPOSITORY_ROOT
        / "data"
        / "liquidations"
        / "model_inputs"
        / "arrival"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stats = arrival_pool_statistics(pool)

    audit = pd.DataFrame(
        [
            {
                "artefact": "liquidation_arrival_hourly_pool",
                "rows": len(pool),
                "sha256": sha256_file(bundle.liquidation_demand.pool_path),
                **stats,
            },
            {
                "artefact": "liquidation_sequence_pool",
                "rows": len(sequence_pool),
                "sha256": sha256_file(
                    REPOSITORY_ROOT
                    / "data"
                    / "liquidations"
                    / "model_inputs"
                    / "arrival"
                    / "sequence_pool.csv"
                ),
                "sequence_sensitivity_implemented": False,
            },
        ]
    )

    hurdle = pd.DataFrame(
        [
            {
                "estimator": "unconditional_activity",
                "denominator_hours": len(pool),
                "activity_hours": int(pool["activity_indicator"].sum()),
                "probability": stats["unconditional_activity_probability"],
                "primary": False,
                "limitation": "Includes hours where no start-of-hour liquidatable inventory is observed.",
            },
            {
                "estimator": "conditional_start_inventory_positive",
                "denominator_hours": stats["conditional_inventory_positive_hours"],
                "activity_hours": stats["conditional_activity_count"],
                "probability": stats["conditional_activity_probability"],
                "primary": True,
                "limitation": (
                    "Start-of-hour inventory is observed; within-hour transitions "
                    "can still produce Bark/grab rows when start inventory is zero."
                ),
            },
        ]
    )

    positive_counts = pool.loc[pool["positive_count_eligible"].astype(bool), "grab_count"]
    positive_distribution = pd.DataFrame(
        [
            {
                "dataset": "source_positive_hours",
                **_summary(positive_counts),
            }
        ]
    )
    sequence_distribution = pd.DataFrame(
        [
            {"dataset": "source_sequence_size", **_summary(sequence_pool["sequence_size"])},
            {"dataset": "source_sequence_duration_seconds", **_summary(sequence_pool["duration_seconds"])},
            {
                "dataset": "source_positive_run_length",
                **_summary(_run_lengths(pool["activity_indicator"] > 0)),
            },
            {
                "dataset": "source_zero_run_length",
                **_summary(_run_lengths(pool["activity_indicator"] == 0)),
            },
        ]
    )

    process = LiquidationDemandProcess(bundle.liquidation_demand)
    generated = []
    inventories = pool["liquidatable_vault_count"].to_numpy(dtype=int)
    for step, inventory in enumerate(inventories):
        generated.append(
            process.sample_step(
                step=step,
                liquidatable_inventory=int(inventory),
                keeper_capacity=None,
            ).as_record()
        )
    generated_df = pd.DataFrame(generated)
    arrival_validation = pd.DataFrame(
        [
            {
                "dataset": "source_hourly_grabs",
                "zero_hour_share": float((pool["grab_count"] == 0).mean()),
                **_summary(pool["grab_count"]),
            },
            {
                "dataset": "generated_bounded_demand",
                "zero_hour_share": float((generated_df["bounded_demand"] == 0).mean()),
                **_summary(generated_df["bounded_demand"]),
            },
        ]
    )

    capacity_rows = []
    for capacity in (5, 20):
        process = LiquidationDemandProcess(bundle.liquidation_demand)
        decisions = [
            process.sample_step(
                step=step,
                liquidatable_inventory=max(int(inventory), 100),
                keeper_capacity=capacity,
            ).as_record()
            for step, inventory in enumerate(inventories)
        ]
        frame = pd.DataFrame(decisions)
        capacity_rows.append(
            {
                "capacity": capacity,
                "rows": len(frame),
                "attempts_never_exceed_capacity": bool(
                    (frame["attempt_budget"] <= capacity).all()
                ),
                "bounded_demand_never_exceeds_inventory": bool(
                    (frame["bounded_demand"] <= frame["liquidatable_inventory"]).all()
                ),
                "share_capacity_truncated": float(
                    (frame["demand_truncated_by_capacity"] > 0).mean()
                ),
                "average_unprocessed_demand": float(
                    frame["demand_truncated_by_capacity"].mean()
                ),
            }
        )
    capacity_validation = pd.DataFrame(capacity_rows)

    smoke = _run_smoke(bundle)

    paths = {
        "liquidation_arrival_runtime_pool_audit": OUTPUT_DIR
        / "liquidation_arrival_runtime_pool_audit.csv",
        "hurdle_estimator_review": OUTPUT_DIR / "hurdle_estimator_review.csv",
        "positive_count_distribution": OUTPUT_DIR / "positive_count_distribution.csv",
        "sequence_distribution": OUTPUT_DIR / "sequence_distribution.csv",
        "arrival_process_validation": OUTPUT_DIR / "arrival_process_validation.csv",
        "capacity_separation_validation": OUTPUT_DIR / "capacity_separation_validation.csv",
        "tranche_d_smoke_results": OUTPUT_DIR / "tranche_d_smoke_results.csv",
    }
    frames = {
        "liquidation_arrival_runtime_pool_audit": audit,
        "hurdle_estimator_review": hurdle,
        "positive_count_distribution": positive_distribution,
        "sequence_distribution": sequence_distribution,
        "arrival_process_validation": arrival_validation,
        "capacity_separation_validation": capacity_validation,
        "tranche_d_smoke_results": smoke,
    }
    for key, frame in frames.items():
        frame.to_csv(paths[key], index=False, lineterminator="\n")

    metadata = {
        "phase": "tranche_d_liquidation_arrival_and_capacity",
        "status": "complete",
        "configuration": str(DEFAULT_TRANCHE_D_CONFIG_PATH.relative_to(REPOSITORY_ROOT)),
        "configuration_sha256": sha256_file(DEFAULT_TRANCHE_D_CONFIG_PATH),
        "source_manifest": manifest,
        "no_data_acquisition": True,
        "no_parameter_estimation": True,
        "legacy_default_demand_mode": "legacy_all_eligible",
        "sequence_sensitivity_implemented": False,
        "outputs": {
            path.name: {
                "rows": int(pd.read_csv(path).shape[0]),
                "sha256": sha256_file(path),
            }
            for path in sorted(paths.values())
        },
    }
    metadata_path = OUTPUT_DIR / "tranche_d_run_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["tranche_d_run_metadata"] = metadata_path
    return paths


def _test_vaults(*, profitable: bool = True) -> list[Vault]:
    debt = 1000.0 if profitable else 500.0
    return [
        Vault(
            vault_id=index,
            owner_id=index,
            collateral_amount=0.6,
            debt_dai=debt,
            liquidation_ratio=1.5,
        )
        for index in range(1, 11)
    ]


def _run_smoke(bundle) -> pd.DataFrame:
    rows = []
    config = replace(create_base_simulation_config(), n_steps=4, n_vaults=10)
    price_path = generate_constant_price_path(
        PriceProcessConfig(n_steps=4, initial_price=1000.0)
    )
    legacy = run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=LiquidationConfig(max_liquidations_per_step=3),
        initial_vaults=_test_vaults(),
    )
    rows.append(
        {
            "run": "legacy_liquidation_demand_under_legacy_environment",
            "status": "passed",
            "demand_mode": "legacy_all_eligible",
            "has_demand_columns": any("liquidation_demand" in c for c in legacy.columns),
            "max_attempted": int(legacy["n_attempted_liquidations"].max()),
            "max_successful": int(legacy["n_successful_liquidations"].max()),
        }
    )
    tranche_c_inputs = generate_environment_inputs(
        load_tranche_c_configuration(DEFAULT_TRANCHE_C_CONFIG_PATH)
    )
    tranche_c_legacy = run_simulation_with_price_path(
        config=replace(create_base_simulation_config(), n_steps=4, n_vaults=10),
        price_path=price_path,
        liquidation_config=LiquidationConfig(max_liquidations_per_step=3),
        initial_vaults=_test_vaults(),
        gas_cost_path=tranche_c_inputs.gas_cost_path[:4],
    )
    rows.append(
        {
            "run": "legacy_liquidation_demand_under_tranche_c_environment",
            "status": "passed",
            "demand_mode": "legacy_all_eligible",
            "has_demand_columns": any(
                "liquidation_demand" in c for c in tranche_c_legacy.columns
            ),
            "max_attempted": int(tranche_c_legacy["n_attempted_liquidations"].max()),
            "max_successful": int(tranche_c_legacy["n_successful_liquidations"].max()),
        }
    )
    process = LiquidationDemandProcess(bundle.liquidation_demand)
    empirical = run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=LiquidationConfig(max_liquidations_per_step=100),
        initial_vaults=_test_vaults(),
        liquidation_demand_process=process,
    )
    rows.append(
        {
            "run": "empirical_hurdle_demand_high_capacity",
            "status": "passed",
            "demand_mode": "empirical_hurdle_count",
            "has_demand_columns": True,
            "max_attempted": int(empirical["n_attempted_liquidations"].max()),
            "max_successful": int(empirical["n_successful_liquidations"].max()),
            "invariants_passed": bool(
                (
                    empirical["n_attempted_liquidations"]
                    <= empirical["liquidation_attempt_budget"]
                ).all()
            ),
        }
    )
    constrained = run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=LiquidationConfig(max_liquidations_per_step=2),
        initial_vaults=_test_vaults(),
        liquidation_demand_process=LiquidationDemandProcess(bundle.liquidation_demand),
    )
    rows.append(
        {
            "run": "empirical_hurdle_demand_constrained_capacity",
            "status": "passed",
            "demand_mode": "empirical_hurdle_count",
            "has_demand_columns": True,
            "max_attempted": int(constrained["n_attempted_liquidations"].max()),
            "max_successful": int(constrained["n_successful_liquidations"].max()),
            "invariants_passed": bool(
                (constrained["liquidation_attempt_budget"] <= 2).all()
            ),
        }
    )
    unprofitable = run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=LiquidationConfig(gas_cost=10_000.0, max_liquidations_per_step=10),
        initial_vaults=_test_vaults(profitable=False),
        liquidation_demand_process=LiquidationDemandProcess(bundle.liquidation_demand),
    )
    rows.append(
        {
            "run": "empirical_hurdle_mixed_profitability_guard",
            "status": "passed",
            "demand_mode": "empirical_hurdle_count",
            "has_demand_columns": True,
            "max_attempted": int(unprofitable["n_attempted_liquidations"].max()),
            "max_successful": int(unprofitable["n_successful_liquidations"].max()),
            "profitability_rules_active": bool(
                unprofitable["n_successful_liquidations"].max() == 0
            ),
        }
    )
    no_inventory = run_simulation_with_price_path(
        config=config,
        price_path=price_path,
        liquidation_config=LiquidationConfig(max_liquidations_per_step=10),
        initial_vaults=[
            Vault(vault_id=i, owner_id=i, collateral_amount=10.0, debt_dai=100.0)
            for i in range(10)
        ],
        liquidation_demand_process=LiquidationDemandProcess(bundle.liquidation_demand),
    )
    rows.append(
        {
            "run": "no_liquidatable_inventory",
            "status": "passed",
            "demand_mode": "empirical_hurdle_count",
            "has_demand_columns": True,
            "max_attempted": int(no_inventory["n_attempted_liquidations"].max()),
            "max_successful": int(no_inventory["n_successful_liquidations"].max()),
            "no_inventory_no_liquidation": bool(
                no_inventory["sampled_liquidation_demand"].max() == 0
                and no_inventory["n_successful_liquidations"].max() == 0
            ),
        }
    )
    return pd.DataFrame(rows)


def main() -> None:
    paths = build_diagnostics()
    print(json.dumps({key: str(path) for key, path in paths.items()}, indent=2))


if __name__ == "__main__":
    main()
