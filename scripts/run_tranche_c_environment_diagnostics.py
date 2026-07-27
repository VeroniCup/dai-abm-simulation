"""
Run bounded Tranche C market/gas diagnostics and smoke simulations.

This script uses existing local artefacts only. It does not acquire data or
estimate new parameters.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import sys
import time

import numpy as np
import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from empirical_config import sha256_file  # noqa: E402
from environment_inputs import load_tranche_c_configuration  # noqa: E402
from experiments import (  # noqa: E402
    create_base_confidence_config,
    create_base_dai_market_config,
    create_base_simulation_config,
)
from gas_process import (  # noqa: E402
    GasProcessConfig,
    component_gas_costs,
    legacy_scalar_gas,
    sample_total_gas_costs,
)
from liquidation import LiquidationConfig  # noqa: E402
from market_bootstrap import (  # noqa: E402
    MarketProcessConfig,
    generate_empirical_price_paths,
    load_market_gas_pool,
    sample_market_gas_blocks,
    valid_block_starts,
)
from price_process import PriceProcessConfig, generate_gbm_price_path  # noqa: E402
from simulation import run_simulation_with_collateral_metrics  # noqa: E402
from vault_initialisation import initialise_vaults, load_tranche_b_configuration  # noqa: E402


OUTPUT_DIR = REPOSITORY_ROOT / "data" / "processed" / "estimation" / "tranche_c"
PRIMARY_CONFIG = REPOSITORY_ROOT / "config/empirical/phase2_empirical_market_gas.yaml"
CONFIGS = {
    "primary_168_component_gas": PRIMARY_CONFIG,
    "block_72_component_gas": REPOSITORY_ROOT
    / "config/empirical/sensitivity/phase2_empirical_market_gas_block_72.yaml",
    "block_336_component_gas": REPOSITORY_ROOT
    / "config/empirical/sensitivity/phase2_empirical_market_gas_block_336.yaml",
    "q90_component_gas": REPOSITORY_ROOT
    / "config/empirical/sensitivity/phase2_empirical_market_gas_high_gas_q90.yaml",
    "zero_inclusive_total_cost": REPOSITORY_ROOT
    / "config/empirical/sensitivity/phase2_empirical_market_gas_zero_inclusive.yaml",
    "market_blocks_legacy_gas": REPOSITORY_ROOT
    / "config/empirical/sensitivity/phase2_empirical_market_blocks_legacy_gas.yaml",
}


def _summary(values: pd.Series | np.ndarray) -> dict[str, float]:
    series = pd.Series(values).dropna().astype(float)
    return {
        "count": float(len(series)),
        "mean": float(series.mean()),
        "std": float(series.std(ddof=1)) if len(series) > 1 else 0.0,
        "median": float(series.median()),
        "q01": float(series.quantile(0.01)),
        "q05": float(series.quantile(0.05)),
        "q10": float(series.quantile(0.10)),
        "q25": float(series.quantile(0.25)),
        "q75": float(series.quantile(0.75)),
        "q90": float(series.quantile(0.90)),
        "q95": float(series.quantile(0.95)),
        "q99": float(series.quantile(0.99)),
        "minimum": float(series.min()),
        "maximum": float(series.max()),
        "skewness": float(series.skew()),
        "excess_kurtosis": float(series.kurt()),
    }


def _market_validation() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bundle = load_tranche_c_configuration(PRIMARY_CONFIG)
    pool = load_market_gas_pool(
        bundle.market_process.pool_path,
        bundle.market_process.pool_sha256,
    )
    source = pool.loc[pool["is_calibration"] & pool["return_observation_valid"]]
    generated = generate_empirical_price_paths(
        n_steps=500,
        initial_prices={"ETH": 2000.0, "BTC": 30000.0},
        config=bundle.market_process,
    )
    rows = []
    for label, frame in (("source", source), ("generated", generated.sampled_rows)):
        for asset, column in (("ETH", "eth_log_return"), ("WBTC", "wbtc_log_return")):
            rows.append({"dataset": label, "asset": asset, **_summary(frame[column])})
    market = pd.DataFrame(rows)

    eth = source["eth_log_return"].astype(float)
    wbtc = source["wbtc_log_return"].astype(float)
    generated_eth = generated.sampled_rows["eth_log_return"].astype(float)
    generated_wbtc = generated.sampled_rows["wbtc_log_return"].astype(float)
    dependence = pd.DataFrame(
        [
            {
                "dataset": "source",
                "pearson_eth_wbtc": float(eth.corr(wbtc, method="pearson")),
                "spearman_eth_wbtc": float(eth.corr(wbtc, method="spearman")),
                "joint_downside_frequency": float(((eth < 0) & (wbtc < 0)).mean()),
                "eth_abs_return_lag1_autocorrelation": float(eth.abs().autocorr(lag=1)),
            },
            {
                "dataset": "generated",
                "pearson_eth_wbtc": float(
                    generated_eth.corr(generated_wbtc, method="pearson")
                ),
                "spearman_eth_wbtc": float(
                    generated_eth.corr(generated_wbtc, method="spearman")
                ),
                "joint_downside_frequency": float(
                    ((generated_eth < 0) & (generated_wbtc < 0)).mean()
                ),
                "eth_abs_return_lag1_autocorrelation": float(
                    generated_eth.abs().autocorr(lag=1)
                ),
            },
        ]
    )

    block_rows = []
    for length in (72, 168, 336):
        starts = valid_block_starts(
            pool,
            block_length_hours=length,
            pool_label="all_calibration",
        )
        block_rows.append(
            {
                "block_length_hours": length,
                "valid_block_start_count": len(starts),
                "first_valid_start": starts[0],
                "last_valid_start": starts[-1],
                "ftx_overlap_count": 0,
            }
        )
    return market, dependence, pd.DataFrame(block_rows)


def _gas_validation() -> pd.DataFrame:
    rows = []
    for label, path in CONFIGS.items():
        bundle = load_tranche_c_configuration(path)
        if bundle.gas_process.mode == "legacy_scalar":
            result = legacy_scalar_gas()
            rows.append(
                {
                    "configuration": label,
                    "gas_mode": "legacy_scalar",
                    "variable": "gas_cost_usd",
                    "count": 0,
                    "mean": np.nan,
                    "median": np.nan,
                    "q90": np.nan,
                    "q95": np.nan,
                    "maximum": np.nan,
                    "zero_observations": 0,
                    "eligible_pool_size": np.nan,
                    "note": result.provenance["gas_process_mode"],
                }
            )
            continue
        if bundle.gas_process.mode == "empirical_total_cost":
            result = sample_total_gas_costs(n_steps=500, config=bundle.gas_process)
        else:
            market = generate_empirical_price_paths(
                n_steps=500,
                initial_prices=bundle.tranche_b_bundle.base_bundle.simulation_config.collateral_portfolio.initial_prices,
                config=bundle.market_process,
            )
            result = component_gas_costs(
                sampled_market_gas_rows=market.sampled_rows,
                simulated_eth_prices=market.price_paths["ETH"],
                config=bundle.gas_process,
            )
        summary = _summary(result.gas_cost_usd)
        rows.append(
            {
                "configuration": label,
                "gas_mode": bundle.gas_process.mode,
                "variable": "gas_cost_usd",
                "count": summary["count"],
                "mean": summary["mean"],
                "median": summary["median"],
                "q90": summary["q90"],
                "q95": summary["q95"],
                "maximum": summary["maximum"],
                "zero_observations": result.provenance["zero_observations_in_source_pool"],
                "eligible_pool_size": result.provenance["eligible_pool_size"],
                "note": bundle.gas_process.zero_observation_policy,
            }
        )
    return pd.DataFrame(rows)


def _market_gas_dependence() -> pd.DataFrame:
    pool = load_market_gas_pool()
    calibration = pool.loc[pool["is_calibration"] & pool["return_observation_valid"]]
    eth = calibration["eth_log_return"].astype(float)
    gas = calibration["median_effective_gas_price_gwei"].astype(float)
    high_volatility = eth.abs() >= eth.abs().quantile(0.95)
    downside = eth < eth.quantile(0.05)
    return pd.DataFrame(
        [
            {
                "metric": "abs_eth_return_gas_pearson",
                "value": float(eth.abs().corr(gas, method="pearson")),
            },
            {
                "metric": "downside_eth_return_gas_pearson",
                "value": float(eth.where(downside).dropna().corr(gas[downside], method="pearson")),
            },
            {
                "metric": "median_gas_high_volatility_hours",
                "value": float(gas[high_volatility].median()),
            },
            {
                "metric": "median_gas_other_hours",
                "value": float(gas[~high_volatility].median()),
            },
            {
                "metric": "stress_label_share_high_volatility_hours",
                "value": float(calibration.loc[high_volatility, "regime_label"].eq("stress").mean()),
            },
        ]
    )


def _run_smoke() -> pd.DataFrame:
    rows = []
    smoke_horizon = 8

    start = time.perf_counter()
    legacy_config = replace(create_base_simulation_config(), n_steps=smoke_horizon)
    gbm = generate_gbm_price_path(
        PriceProcessConfig(
            n_steps=legacy_config.n_steps,
            initial_price=legacy_config.initial_eth_price,
            random_seed=legacy_config.random_seed,
        )
    )
    system, collateral = run_simulation_with_collateral_metrics(
        config=legacy_config,
        price_path=gbm,
        liquidation_config=LiquidationConfig(),
        confidence_config=create_base_confidence_config(),
        dai_market_config=create_base_dai_market_config(),
    )
    rows.append(
        {
            "run": "legacy_gbm_legacy_scalar_gas",
            "market_mode": "legacy_gbm",
            "gas_mode": "legacy_scalar",
            "system_rows": len(system),
            "collateral_rows": len(collateral),
            "minimum_eth_price": float(system["market_eth_price"].min()),
            "minimum_gas_cost": LiquidationConfig().gas_cost,
            "runtime_seconds": time.perf_counter() - start,
            "status": "passed",
        }
    )

    tranche_b = load_tranche_b_configuration()
    sim = replace(tranche_b.base_bundle.simulation_config, n_steps=smoke_horizon)
    init = initialise_vaults(sim, tranche_b.initialisation)
    gbm_paths = {
        "ETH": gbm["eth_price"].to_numpy(),
        "BTC": np.full(smoke_horizon, 30000.0),
    }
    start = time.perf_counter()
    system, collateral = run_simulation_with_collateral_metrics(
        config=sim,
        price_path=gbm_paths,
        liquidation_config=tranche_b.base_bundle.liquidation_config,
        confidence_config=tranche_b.base_bundle.confidence_config,
        dai_market_config=tranche_b.base_bundle.dai_market_config,
        initial_vaults=init.vaults,
    )
    rows.append(
        {
            "run": "tranche_b_empirical_joint_legacy_gbm_legacy_gas",
            "market_mode": "legacy_gbm",
            "gas_mode": "legacy_scalar",
            "system_rows": len(system),
            "collateral_rows": len(collateral),
            "minimum_eth_price": float(system["market_eth_price"].min()),
            "minimum_gas_cost": tranche_b.base_bundle.liquidation_config.gas_cost,
            "runtime_seconds": time.perf_counter() - start,
            "status": "passed",
        }
    )

    for label in [
        "market_blocks_legacy_gas",
        "primary_168_component_gas",
        "block_72_component_gas",
        "block_336_component_gas",
    ]:
        bundle = load_tranche_c_configuration(CONFIGS[label])
        sim = replace(bundle.tranche_b_bundle.base_bundle.simulation_config, n_steps=smoke_horizon)
        init = initialise_vaults(sim, bundle.tranche_b_bundle.initialisation)
        market = generate_empirical_price_paths(
            n_steps=smoke_horizon,
            initial_prices=sim.collateral_portfolio.initial_prices,
            config=bundle.market_process,
        )
        if bundle.gas_process.mode == "legacy_scalar":
            gas = legacy_scalar_gas()
        else:
            gas = component_gas_costs(
                sampled_market_gas_rows=market.sampled_rows,
                simulated_eth_prices=market.price_paths["ETH"],
                config=bundle.gas_process,
            )
        start = time.perf_counter()
        system, collateral = run_simulation_with_collateral_metrics(
            config=sim,
            price_path=market.price_paths,
            liquidation_config=bundle.tranche_b_bundle.base_bundle.liquidation_config,
            confidence_config=bundle.tranche_b_bundle.base_bundle.confidence_config,
            dai_market_config=bundle.tranche_b_bundle.base_bundle.dai_market_config,
            initial_vaults=init.vaults,
            gas_cost_path=gas.gas_cost_usd,
        )
        rows.append(
            {
                "run": label,
                "market_mode": bundle.market_process.mode,
                "gas_mode": bundle.gas_process.mode,
                "system_rows": len(system),
                "collateral_rows": len(collateral),
                "minimum_eth_price": float(system["market_eth_price"].min()),
                "minimum_gas_cost": (
                    float(np.min(gas.gas_cost_usd))
                    if gas.gas_cost_usd is not None
                    else bundle.tranche_b_bundle.base_bundle.liquidation_config.gas_cost
                ),
                "runtime_seconds": time.perf_counter() - start,
                "status": "passed",
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    market, dependence, block_starts = _market_validation()
    gas = _gas_validation()
    market_gas_dependence = _market_gas_dependence()
    smoke = _run_smoke()
    ftx_source = REPOSITORY_ROOT / "data/processed/estimation/phase2a_review/ftx_validation_diagnostics.csv"
    ftx = pd.read_csv(ftx_source)
    ftx["tranche_c_note"] = "validation_only_existing_artefact_not_used_for_calibration"

    market.to_csv(OUTPUT_DIR / "market_bootstrap_validation.csv", index=False, lineterminator="\n")
    dependence.to_csv(OUTPUT_DIR / "market_dependence_validation.csv", index=False, lineterminator="\n")
    block_starts.to_csv(OUTPUT_DIR / "valid_block_start_audit.csv", index=False, lineterminator="\n")
    block_starts.rename(
        columns={"valid_block_start_count": "available_block_start_count"}
    ).to_csv(OUTPUT_DIR / "block_length_sensitivity.csv", index=False, lineterminator="\n")
    gas.to_csv(OUTPUT_DIR / "gas_process_validation.csv", index=False, lineterminator="\n")
    market_gas_dependence.to_csv(
        OUTPUT_DIR / "market_gas_dependence.csv",
        index=False,
        lineterminator="\n",
    )
    smoke.to_csv(OUTPUT_DIR / "tranche_c_smoke_results.csv", index=False, lineterminator="\n")
    ftx.to_csv(OUTPUT_DIR / "ftx_directional_validation.csv", index=False, lineterminator="\n")

    metadata = {
        "phase": "tranche_c_empirical_market_and_gas",
        "status": "complete",
        "configuration": str(PRIMARY_CONFIG.relative_to(REPOSITORY_ROOT)),
        "configuration_sha256": sha256_file(PRIMARY_CONFIG),
        "market_pool": "config/empirical/data/market_gas_hourly_pool.csv",
        "market_pool_sha256": sha256_file(
            REPOSITORY_ROOT / "config/empirical/data/market_gas_hourly_pool.csv"
        ),
        "liquidation_gas_pool": "config/empirical/data/liquidation_gas_pool.csv",
        "liquidation_gas_pool_sha256": sha256_file(
            REPOSITORY_ROOT / "config/empirical/data/liquidation_gas_pool.csv"
        ),
        "ftx_used_for_calibration": False,
        "legacy_gbm_default_changed": False,
        "legacy_scalar_gas_default_changed": False,
        "outputs": {
            path.name: {
                "rows": int(pd.read_csv(path).shape[0]),
                "sha256": sha256_file(path),
            }
            for path in sorted(OUTPUT_DIR.glob("*.csv"))
        },
    }
    (OUTPUT_DIR / "tranche_c_run_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
