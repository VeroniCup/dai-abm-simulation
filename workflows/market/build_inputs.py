"""
Build compact Tranche C market and gas runtime pools.

This script performs deterministic runtime-pool construction only. It does
not acquire data and does not estimate new parameters.
"""

from __future__ import annotations

from pathlib import Path
import runpy

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
REPOSITORY_ROOT = runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)
import hashlib
import json

import numpy as np
import pandas as pd


MARKET_OUTPUT_DIR = (
    REPOSITORY_ROOT / "data" / "market" / "model_inputs" / "environment_blocks"
)
LIQUIDATION_OUTPUT_DIR = (
    REPOSITORY_ROOT / "data" / "liquidations" / "model_inputs" / "keeper_gas"
)
AUDIT_DIR = (
    REPOSITORY_ROOT
    / "outputs"
    / "diagnostics"
    / "input_construction"
    / "market_gas"
)

MARKET_GAS_OUTPUT = MARKET_OUTPUT_DIR / "pool.csv"
MARKET_GAS_MANIFEST = MARKET_OUTPUT_DIR / "manifest.json"
LIQUIDATION_GAS_OUTPUT = LIQUIDATION_OUTPUT_DIR / "pool.csv"
LIQUIDATION_GAS_MANIFEST = LIQUIDATION_OUTPUT_DIR / "manifest.json"

SOURCE_CHECKSUMS = {
    "data/market/processed/combined/hourly_market_gas_panel.csv": (
        "86ed2ac5a5d364cc57e8b41e137ef369a0fce7a393d386b4b38fc1ebd1be0545"
    ),
    "outputs/diagnostics/calibration/market_gas_protocol/gas/gas_sampling_index.csv": (
        "c722a29370672c26b10c90b951f2bac7510eee45d4e1902c6267e65417760524"
    ),
    "outputs/diagnostics/calibration/market_gas_protocol/diagnostics/calibration_validation_split.csv": (
        "e35852b25e09fe65347d341c4e6382d8973fa2b64b996f3af615a9d881d8a574"
    ),
    "outputs/diagnostics/calibration/market_gas_protocol/liquidations/liquidation_transaction_gas.csv": (
        "137a17b8752bc90b0ac83b2f9593684781d598d340bb6be65afcab6b624c03a0"
    ),
    "outputs/diagnostics/calibration/market_gas_protocol/review/gas_cost_sensitivity.csv": (
        "456a2c5e3308690456a69127235a0dc786edf01189eb355159788a9bdc65042d"
    ),
}

MARKET_GAS_COLUMNS = [
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
]

LIQUIDATION_GAS_COLUMNS = [
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
]


def sha256_file(path: Path) -> str:
    """Return the SHA-256 checksum for a local file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_source_checksums() -> dict[str, str]:
    """Verify all source artefact checksums."""
    observed: dict[str, str] = {}
    for relative_path, expected in SOURCE_CHECKSUMS.items():
        path = REPOSITORY_ROOT / relative_path
        checksum = sha256_file(path)
        if checksum != expected:
            raise ValueError(
                f"Checksum mismatch for {relative_path}: "
                f"expected {expected}, observed {checksum}."
            )
        observed[relative_path] = checksum
    return observed


def _to_utc_z(series: pd.Series) -> pd.Series:
    values = pd.to_datetime(series, utc=True)
    return values.dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_market_gas_pool() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the compact hourly market/gas runtime pool and audit."""
    panel = pd.read_csv(REPOSITORY_ROOT / "data/market/processed/combined/hourly_market_gas_panel.csv")
    gas_index = pd.read_csv(
        REPOSITORY_ROOT
        / "outputs/diagnostics/calibration/market_gas_protocol/"
        "gas/gas_sampling_index.csv"
    )
    split = pd.read_csv(
        REPOSITORY_ROOT
        / "outputs/diagnostics/calibration/market_gas_protocol/"
        "diagnostics/calibration_validation_split.csv"
    )

    panel["timestamp_utc"] = _to_utc_z(panel["timestamp_utc"])
    gas_index["timestamp_utc"] = _to_utc_z(gas_index["timestamp_utc"])
    merged = panel.merge(
        gas_index[
            [
                "source_row",
                "timestamp_utc",
                "is_calibration",
                "is_validation",
                "regime",
            ]
        ],
        on="timestamp_utc",
        how="inner",
        validate="one_to_one",
    )
    if len(merged) != len(panel):
        raise ValueError("Hourly market/gas panel did not align with the Phase 2A gas index.")

    split["start_utc"] = pd.to_datetime(split["start_utc"], utc=True)
    split["end_utc"] = pd.to_datetime(split["end_utc"], utc=True)
    withheld = split.loc[split["sample"].eq("withheld_validation_ftx")].iloc[0]
    timestamps = pd.to_datetime(merged["timestamp_utc"], utc=True)
    is_ftx = timestamps.between(
        withheld["start_utc"],
        withheld["end_utc"],
        inclusive="both",
    )

    market_gas = pd.DataFrame(
        {
            "pool_row_id": np.arange(len(merged), dtype=int),
            "source_row": merged["source_row"].astype(int),
            "timestamp_utc": merged["timestamp_utc"],
            "calibration_pool_label": np.where(is_ftx, "withheld_ftx", "all_calibration"),
            "regime_label": merged["regime"],
            "is_calibration": merged["is_calibration"].astype(bool) & ~is_ftx,
            "is_withheld_ftx": is_ftx.astype(bool),
            "return_observation_valid": (
                merged["eth_log_return"].notna()
                & merged["wbtc_log_return"].notna()
                & np.isfinite(merged["eth_log_return"])
                & np.isfinite(merged["wbtc_log_return"])
            ),
            "eth_price_usd": merged["eth_price_usd"],
            "wbtc_price_usd": merged["wbtc_price_usd"],
            "eth_log_return": merged["eth_log_return"],
            "wbtc_log_return": merged["wbtc_log_return"],
            "median_effective_gas_price_gwei": merged[
                "median_effective_gas_price_gwei"
            ],
            "p90_effective_gas_price_gwei": merged["p90_effective_gas_price_gwei"],
            "p99_effective_gas_price_gwei": merged["p99_effective_gas_price_gwei"],
            "target_normalised_block_utilisation": merged[
                "target_normalised_block_utilisation"
            ],
        }
    )[MARKET_GAS_COLUMNS]

    if market_gas["timestamp_utc"].duplicated().any():
        raise ValueError("Market/gas runtime pool contains duplicate timestamps.")
    if not market_gas["timestamp_utc"].is_monotonic_increasing:
        raise ValueError("Market/gas runtime pool is not chronologically ordered.")

    audit = pd.DataFrame(
        [
            {
                "artefact": "market_gas_hourly_pool",
                "source_rows": len(panel),
                "output_rows": len(market_gas),
                "calibration_rows": int(market_gas["is_calibration"].sum()),
                "ftx_withheld_rows": int(market_gas["is_withheld_ftx"].sum()),
                "invalid_return_rows": int((~market_gas["return_observation_valid"]).sum()),
                "first_timestamp_utc": market_gas["timestamp_utc"].min(),
                "last_timestamp_utc": market_gas["timestamp_utc"].max(),
            }
        ]
    )
    return market_gas, audit


def build_liquidation_gas_pool() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the compact clean-Take gas runtime pool and audit."""
    source = pd.read_csv(
        REPOSITORY_ROOT
        / "outputs/diagnostics/calibration/market_gas_protocol/"
        "liquidations/liquidation_transaction_gas.csv"
    )
    clean = source.loc[
        source["take_transaction_class"].eq("clean_single_take_single_auction")
        & source["is_calibration"].astype(bool)
    ].copy()
    clean = clean.sort_values(
        ["timestamp_utc", "block_number", "transaction_index", "gas_used"],
        kind="mergesort",
    ).reset_index(drop=True)
    zero_gas = (
        clean["effective_gas_price_gwei"].eq(0)
        | clean["transaction_gas_cost_usd"].eq(0)
    )

    pool = pd.DataFrame(
        {
            "gas_pool_row_id": np.arange(len(clean), dtype=int),
            "event_type": "clean_successful_take_transaction",
            "sample_role": np.where(zero_gas, "zero_inclusive_sensitivity", "primary"),
            "regime_label": clean["regime"],
            "is_primary_eligible": ~zero_gas,
            "is_zero_gas_observation": zero_gas,
            "gas_units": clean["gas_used"].astype(int),
            "effective_gas_price_gwei": clean["effective_gas_price_gwei"],
            "eth_price_usd": clean["eth_price_usd"],
            "transaction_gas_cost_eth": clean["transaction_gas_cost_eth"],
            "transaction_gas_cost_usd": clean["transaction_gas_cost_usd"],
        }
    )[LIQUIDATION_GAS_COLUMNS]

    if pool["gas_units"].le(0).any():
        raise ValueError("Liquidation gas pool contains non-positive gas units.")
    if pool["transaction_gas_cost_usd"].lt(0).any():
        raise ValueError("Liquidation gas pool contains negative USD costs.")

    audit = pd.DataFrame(
        [
            {
                "artefact": "liquidation_gas_pool",
                "source_rows": len(source),
                "clean_calibration_rows": len(clean),
                "primary_rows": int(pool["is_primary_eligible"].sum()),
                "zero_inclusive_rows": len(pool),
                "zero_gas_observations": int(pool["is_zero_gas_observation"].sum()),
                "primary_median_usd": float(
                    pool.loc[pool["is_primary_eligible"], "transaction_gas_cost_usd"].median()
                ),
                "zero_inclusive_median_usd": float(pool["transaction_gas_cost_usd"].median()),
            }
        ]
    )
    return pool, audit


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def write_outputs() -> None:
    """Build and write all Tranche C runtime pools and manifests."""
    MARKET_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LIQUIDATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    checksums = verify_source_checksums()

    market_gas, market_audit = build_market_gas_pool()
    liquidation_gas, liquidation_audit = build_liquidation_gas_pool()

    _write_csv(market_gas, MARKET_GAS_OUTPUT)
    _write_csv(liquidation_gas, LIQUIDATION_GAS_OUTPUT)
    _write_csv(market_audit, AUDIT_DIR / "market_gas_runtime_pool_audit.csv")
    _write_csv(liquidation_audit, AUDIT_DIR / "gas_pool_audit.csv")

    market_manifest = {
        "artefact": "market_gas_hourly_pool",
        "version": "tranche_c_v1",
        "output_path": str(MARKET_GAS_OUTPUT.relative_to(REPOSITORY_ROOT)),
        "output_sha256": sha256_file(MARKET_GAS_OUTPUT),
        "rows": int(len(market_gas)),
        "columns": MARKET_GAS_COLUMNS,
        "return_type": "hourly_log_return",
        "withheld_ftx_period": {
            "start_utc": "2022-11-01T00:00:00Z",
            "end_utc": "2022-11-20T23:00:00Z",
            "policy": "excluded_from_calibration_block_eligibility",
        },
        "source_checksums": checksums,
        "notes": (
            "Compact runtime pool for aligned ETH/WBTC hourly log returns and "
            "hourly network gas-price conditions. No DAI path is used as an "
            "exogenous simulation input."
        ),
    }
    LIQUIDATION_GAS_MANIFEST.write_text(
        json.dumps(
            {
                "artefact": "liquidation_gas_pool",
                "version": "tranche_c_v1",
                "output_path": str(LIQUIDATION_GAS_OUTPUT.relative_to(REPOSITORY_ROOT)),
                "output_sha256": sha256_file(LIQUIDATION_GAS_OUTPUT),
                "rows": int(len(liquidation_gas)),
                "columns": LIQUIDATION_GAS_COLUMNS,
                "primary_rows": int(liquidation_gas["is_primary_eligible"].sum()),
                "zero_inclusive_rows": int(len(liquidation_gas)),
                "zero_gas_observations": int(
                    liquidation_gas["is_zero_gas_observation"].sum()
                ),
                "event_type": "clean_successful_take_transaction",
                "source_checksums": checksums,
                "notes": (
                    "Primary pool excludes four observed zero gas-price/cost "
                    "transactions; zero-inclusive sensitivity retains them."
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    MARKET_GAS_MANIFEST.write_text(
        json.dumps(market_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_outputs()
