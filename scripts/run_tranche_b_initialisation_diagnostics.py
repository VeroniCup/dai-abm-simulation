"""
Run bounded Tranche B vault-initialisation diagnostics.

This script does not estimate parameters. It validates the opt-in
configuration, samples initial vault populations and runs very short smoke
simulations without touching legacy output directories.
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

from empirical_config import load_empirical_configuration_bundle, sha256_file  # noqa: E402
from experiments import create_base_simulation_config  # noqa: E402
from liquidation import LiquidationConfig  # noqa: E402
from confidence import ConfidenceConfig  # noqa: E402
from dai_market import DAIMarketConfig  # noqa: E402
from simulation import run_simulation_with_collateral_metrics  # noqa: E402
from vault import vaults_to_dataframe  # noqa: E402
from vault_initialisation import (  # noqa: E402
    DEFAULT_POOL_PATH,
    DEFAULT_TRANCHE_B_CONFIG_PATH,
    VaultInitialisationConfig,
    compare_sample_to_pool,
    initialise_vaults,
    load_pool,
    load_tranche_b_configuration,
)


OUTPUT_DIR = REPOSITORY_ROOT / "data" / "processed" / "estimation" / "tranche_b"
SMOKE_CONFIGS = {
    "legacy_gaussian": None,
    "tranche_a_configuration_only": REPOSITORY_ROOT / "config/empirical/phase2_empirical_baseline.yaml",
    "tranche_b_parametric_truncated": REPOSITORY_ROOT / "config/empirical/sensitivity/phase2_empirical_parametric_truncated.yaml",
    "tranche_b_empirical_joint": DEFAULT_TRANCHE_B_CONFIG_PATH,
}


def _summary(frame: pd.DataFrame, variable: str) -> dict[str, float]:
    values = pd.to_numeric(frame[variable], errors="coerce").dropna()
    return {
        "count": float(len(values)),
        "mean": float(values.mean()),
        "std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
        "median": float(values.median()),
        "q10": float(values.quantile(0.10)),
        "q25": float(values.quantile(0.25)),
        "q75": float(values.quantile(0.75)),
        "q90": float(values.quantile(0.90)),
        "q95": float(values.quantile(0.95)),
        "q99": float(values.quantile(0.99)),
        "maximum": float(values.max()),
    }


def _price_paths(config) -> dict[str, np.ndarray]:
    if config.collateral_portfolio is None:
        return {"ETH": np.full(config.n_steps, config.initial_eth_price)}
    prices = config.collateral_portfolio.initial_prices
    return {
        collateral_type: np.full(config.n_steps, price)
        for collateral_type, price in prices.items()
    }


def _initial_state_metrics(name: str, result, config) -> dict[str, object]:
    prices = (
        config.initial_eth_price
        if config.collateral_portfolio is None
        else config.collateral_portfolio.initial_prices
    )
    frame = vaults_to_dataframe(result.vaults, prices)
    total_debt = frame["debt_dai"].sum()
    by_family = frame.groupby("collateral_type")["debt_dai"].sum() / total_debt
    return {
        "run": name,
        "vaults": len(frame),
        "active_vaults": int(frame["is_active"].sum()),
        "liquidatable_vaults": int(frame["is_liquidatable"].sum()),
        "liquidatable_share": float(frame["is_liquidatable"].mean()),
        "eth_debt_share": float(by_family.get("ETH", 0.0)),
        "btc_debt_share": float(by_family.get("BTC", 0.0)),
        "debt_mean": float(frame["debt_dai"].mean()),
        "collateral_ratio_median": float(frame["collateral_ratio"].median()),
    }


def _run_smoke() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for name, path in SMOKE_CONFIGS.items():
        start = time.perf_counter()
        if name == "legacy_gaussian":
            config = replace(create_base_simulation_config(), n_steps=8)
            init = initialise_vaults(config, VaultInitialisationConfig())
            liquidation = LiquidationConfig()
            confidence = ConfidenceConfig()
            market = DAIMarketConfig()
        elif name == "tranche_a_configuration_only":
            bundle = load_empirical_configuration_bundle(path)
            config = replace(bundle.simulation_config, n_steps=8)
            init = initialise_vaults(config, VaultInitialisationConfig())
            liquidation = bundle.liquidation_config
            confidence = bundle.confidence_config
            market = bundle.dai_market_config
        else:
            bundle = load_tranche_b_configuration(path)
            config = replace(bundle.base_bundle.simulation_config, n_steps=8)
            init = initialise_vaults(config, bundle.initialisation)
            liquidation = bundle.base_bundle.liquidation_config
            confidence = bundle.base_bundle.confidence_config
            market = bundle.base_bundle.dai_market_config

        system, collateral = run_simulation_with_collateral_metrics(
            config=config,
            price_path=_price_paths(config),
            liquidation_config=liquidation,
            confidence_config=confidence,
            dai_market_config=market,
            initial_vaults=init.vaults,
        )
        elapsed = time.perf_counter() - start
        rows.append(
            {
                **_initial_state_metrics(name, init, config),
                "mode": init.provenance["initialisation_mode"],
                "system_rows": len(system),
                "collateral_rows": len(collateral),
                "runtime_seconds": elapsed,
                "status": "passed",
            }
        )
    return pd.DataFrame(rows)


def _distribution_outputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    init = initialise_vaults(bundle.base_bundle.simulation_config, bundle.initialisation)
    pool = load_pool(DEFAULT_POOL_PATH)
    normal_pool = pool.loc[pool["regime_label"].eq("normal")]

    validation_rows = []
    for variable in ("debt_dai", "collateral_ratio", "absolute_buffer"):
        validation_rows.append(
            {
                "mode": "empirical_joint",
                "variable": variable,
                **_summary(init.sampled_rows, variable),
            }
        )
    validation_rows.append(
        {
            "mode": "empirical_joint",
            "variable": "debt_buffer_pearson",
            "count": float(len(init.sampled_rows)),
            "mean": float(init.sampled_rows["debt_dai"].corr(init.sampled_rows["absolute_buffer"])),
            "std": np.nan,
            "median": np.nan,
            "q10": np.nan,
            "q25": np.nan,
            "q75": np.nan,
            "q90": np.nan,
            "q95": np.nan,
            "q99": np.nan,
            "maximum": np.nan,
        }
    )
    comparison = compare_sample_to_pool(init.sampled_rows, normal_pool)
    return pd.DataFrame(validation_rows), comparison


def _population_convergence() -> pd.DataFrame:
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    rows = []
    for n_vaults in (100, 500, 1000):
        start = time.perf_counter()
        config = replace(bundle.base_bundle.simulation_config, n_vaults=n_vaults)
        init = initialise_vaults(config, bundle.initialisation)
        elapsed = time.perf_counter() - start
        rows.append(
            {
                **_initial_state_metrics(f"empirical_joint_{n_vaults}", init, config),
                "n_vaults": n_vaults,
                "minimum_non_zero_share": 1 / n_vaults,
                "runtime_seconds": elapsed,
                "duplicate_empirical_row_draw_count": init.provenance[
                    "duplicate_empirical_row_draw_count"
                ],
            }
        )
    return pd.DataFrame(rows)


def _zero_threshold() -> pd.DataFrame:
    convergence = _population_convergence()
    return convergence.assign(
        normal_threshold=0.0,
        threshold_crossed=lambda frame: frame["liquidatable_share"] > 0.0,
    )[
        [
            "n_vaults",
            "liquidatable_vaults",
            "liquidatable_share",
            "minimum_non_zero_share",
            "normal_threshold",
            "threshold_crossed",
        ]
    ]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    smoke = _run_smoke()
    validation, comparison = _distribution_outputs()
    convergence = _population_convergence()
    zero_threshold = _zero_threshold()

    smoke.to_csv(OUTPUT_DIR / "tranche_b_smoke_results.csv", index=False, lineterminator="\n")
    validation.to_csv(OUTPUT_DIR / "sampling_validation.csv", index=False, lineterminator="\n")
    comparison.to_csv(OUTPUT_DIR / "distribution_comparison.csv", index=False, lineterminator="\n")
    convergence.to_csv(OUTPUT_DIR / "population_convergence.csv", index=False, lineterminator="\n")
    zero_threshold.to_csv(
        OUTPUT_DIR / "normal_liquidatable_threshold_diagnostic.csv",
        index=False,
        lineterminator="\n",
    )

    metadata = {
        "phase": "tranche_b_distributional_vault_initialisation",
        "status": "complete",
        "pool_path": "config/empirical/data/vault_initialisation_pools.csv",
        "pool_sha256": sha256_file(DEFAULT_POOL_PATH),
        "primary_configuration": "config/empirical/phase2_empirical_distributional.yaml",
        "primary_configuration_sha256": sha256_file(DEFAULT_TRANCHE_B_CONFIG_PATH),
        "outputs": {
            path.name: {
                "path": str(path.relative_to(REPOSITORY_ROOT)),
                "sha256": sha256_file(path),
                "rows": int(pd.read_csv(path).shape[0]),
            }
            for path in sorted(OUTPUT_DIR.glob("*.csv"))
        },
        "ftx_used_for_calibration": False,
        "legacy_defaults_changed": False,
        "tranche_a_values_changed": False,
        "notes": "Diagnostics are bounded smoke and initialisation checks only.",
    }
    (OUTPUT_DIR / "tranche_b_run_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
