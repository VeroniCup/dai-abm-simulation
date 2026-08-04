"""Local-only system-wide keeper execution calibration.

This module estimates candidate keeper-capacity and profit-hurdle ranges from
validated local evidence.  It is intentionally separate from runtime profile
loading: generated candidates are review inputs, not adopted parameters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yaml

from dai_sim.model.liquidation import LiquidationConfig, liquidate_vaults
from dai_sim.model.vault import Vault

from .data_loading import PROJECT_ROOT, sha256_file


TARGET_ILKS = ("ETH-A", "ETH-B", "ETH-C", "WBTC-A", "WBTC-B", "WBTC-C")
SYSTEM_SCOPE = "SYSTEM_ALL"
TERRA_START = pd.Timestamp("2022-05-05T00:00:00Z")
TERRA_END = pd.Timestamp("2022-06-20T00:00:00Z")
QUIET_START = pd.Timestamp("2024-02-01T00:00:00Z")
QUIET_END = pd.Timestamp("2024-03-01T00:00:00Z")
USDC_SVB_START = pd.Timestamp("2023-03-06T00:00:00Z")
USDC_SVB_END = pd.Timestamp("2023-03-20T00:00:00Z")
FINAL_VALIDATION_START = pd.Timestamp("2022-11-01T00:00:00Z")
FINAL_VALIDATION_END = pd.Timestamp("2022-11-21T00:00:00Z")

DEFAULT_EVIDENCE_DIR = (
    PROJECT_ROOT / "data/provenance/calibration/keeper"
)
DEFAULT_DIAGNOSTIC_ROOT = (
    PROJECT_ROOT / "outputs/diagnostics/calibration/keeper_execution"
)
DEFAULT_REGISTRY_PATH = (
    PROJECT_ROOT / "config/sensitivities/keeper_execution.yaml"
)
CALIBRATION_MANIFEST = (
    PROJECT_ROOT / "data/provenance/calibration/manifest.json"
)

LIQUIDATION_HOURLY = (
    PROJECT_ROOT
    / "data/liquidations/processed/"
    "liquidation_hourly_by_ilk_2021-06-01_2024-06-30.csv"
)
LIQUIDATION_ACTIONS = (
    PROJECT_ROOT
    / "data/liquidations/processed/"
    "liquidation_actions_2021-06-01_2024-06-30.csv"
)
LIQUIDATION_GAS = (
    PROJECT_ROOT
    / "outputs/diagnostics/calibration/market_gas_protocol/"
    "liquidations/liquidation_transaction_gas.csv"
)
PROTOCOL_HOURLY = (
    PROJECT_ROOT / "data/protocol/processed/hourly_protocol_parameters.csv"
)
MARKET_GAS_HOURLY = (
    PROJECT_ROOT / "data/market/processed/combined/hourly_market_gas_panel.csv"
)
TERRA_STRESS = (
    PROJECT_ROOT
    / "data/vaults/processed/representative_regimes/"
    "terra_cefi_2022-05-05_2022-06-20/stress_tail_diagnostics.csv"
)
LIQUIDATABLE_SHARE = (
    PROJECT_ROOT
    / "outputs/diagnostics/calibration/vaults/liquidatable_share/"
    "hourly_liquidatable_share.csv"
)
MODEL_LIQUIDATION_SOURCE = (
    PROJECT_ROOT / "src/dai_sim/model/liquidation.py"
)
KEEPER_CALIBRATION_SOURCE = Path(__file__)
KEEPER_RESOLVER_SOURCE = (
    PROJECT_ROOT / "src/dai_sim/inputs/keeper_execution.py"
)
KEEPER_WORKFLOW_SOURCE = (
    PROJECT_ROOT / "workflows/calibration/keeper_execution.py"
)

COMPACT_ARTEFACTS = (
    "keeper_execution_specification.json",
    "keeper_collateral_comparability.csv",
    "keeper_hourly_panel_summary.csv",
    "keeper_capacity_frontier.csv",
    "keeper_profit_hurdle.csv",
    "keeper_execution_registry.csv",
    "keeper_execution_decision.json",
    "keeper_execution_reproducibility.json",
    "keeper_execution_benchmark.json",
)

CAPACITY_CLASSIFICATIONS = {
    "shared_effective_capacity_frontier_identified",
    "shared_capacity_partially_identified",
    "shared_capacity_not_identified_use_sensitivity",
    "shared_keeper_capacity_calibration_invalid",
}
COMPOSITION_CLASSIFICATIONS = {
    "composition_stable",
    "composition_sensitive_shared_capacity",
    "composition_unresolved",
}
HURDLE_CLASSIFICATIONS = {
    "profit_hurdle_estimated",
    "profit_hurdle_partially_identified",
    "profit_hurdle_not_identified",
    "profit_hurdle_calibration_invalid",
}


@dataclass(frozen=True)
class KeeperExecutionDesign:
    """Immutable pre-registered controls for the bounded calibration."""

    specification_version: int = 1
    random_seed: int = 20_260_730
    bootstrap_replications: int = 2_000
    simulation_step_hours: int = 1
    primary_high_demand_quantile: float = 0.75
    robustness_high_demand_quantiles: tuple[float, ...] = (0.67, 0.90)
    high_gas_quantile: float = 0.90
    high_volatility_quantile: float = 0.90
    downside_quantile: float = 0.05
    minimum_high_demand_hours_level1: int = 20
    minimum_slack_hours_level1: int = 10
    minimum_regime_hours: int = 10
    minimum_positive_profit_observations_level1: int = 50
    minimum_negative_profit_observations_level1: int = 20
    capacity_level2_minimum_hours: int = 10
    capacity_level2_minimum_slack_hours: int = 5
    calendar_instability_absolute: int = 2
    calendar_instability_relative: float = 0.25
    composition_instability_absolute: int = 2
    composition_instability_relative: float = 0.25
    minimum_composition_group_hours: int = 10
    minimum_repeated_upper_count: int = 3
    frontier_threshold_robustness_absolute: int = 2
    frontier_threshold_robustness_relative: float = 0.25
    maximum_bootstrap_interval_absolute: int = 2
    maximum_bootstrap_interval_relative: float = 0.25
    maximum_compact_file_bytes: int = 25 * 1024 * 1024
    maximum_diagnostic_bytes: int = 250 * 1024 * 1024
    maximum_total_output_bytes: int = 10 * 1024 * 1024 * 1024


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json(path: Path, payload: Any) -> None:
    _atomic_text(
        path,
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    _atomic_text(
        path,
        frame.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )


def _source_paths() -> dict[str, Path]:
    return {
        "liquidation_hourly": LIQUIDATION_HOURLY,
        "liquidation_actions": LIQUIDATION_ACTIONS,
        "liquidation_transaction_gas": LIQUIDATION_GAS,
        "protocol_hourly": PROTOCOL_HOURLY,
        "market_gas_hourly": MARKET_GAS_HOURLY,
        "terra_unsafe_inventory": TERRA_STRESS,
        "representative_liquidatable_share": LIQUIDATABLE_SHARE,
        "liquidation_model_source": MODEL_LIQUIDATION_SOURCE,
        "keeper_calibration_source": KEEPER_CALIBRATION_SOURCE,
        "keeper_resolver_source": KEEPER_RESOLVER_SOURCE,
        "keeper_workflow_source": KEEPER_WORKFLOW_SOURCE,
    }


def source_checksums() -> dict[str, str]:
    """Return checksums for every source entering the scientific identity."""
    paths = _source_paths()
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Keeper-execution inputs are missing: {sorted(missing)}"
        )
    return {name: sha256_file(path) for name, path in paths.items()}


def audit_runtime_semantics() -> dict[str, Any]:
    """Verify the present profit equation and global capacity ordering."""
    source = MODEL_LIQUIDATION_SOURCE.read_text(encoding="utf-8")
    required = {
        "debt_repaid": "debt_repaid = vault.debt_dai * max_close_factor",
        "gross_reward": "gross_reward = debt_repaid * liquidation_penalty",
        "risk_cost": "risk_cost = debt_repaid * config.risk_cost_rate",
        "profit": "return gross_reward - config.gas_cost - risk_cost",
        "profit_gate": '"is_profitable": expected_profit > 0',
        "global_sort": '["expected_profit", "vault_id"]',
        "global_head": "liquidatable_df.head(attempt_budget)",
        "legacy_unbounded_default": (
            "max_liquidations_per_step: int | None = None"
        ),
    }
    missing = [
        semantic for semantic, fragment in required.items() if fragment not in source
    ]
    if missing:
        raise ValueError(
            f"Keeper runtime semantic audit failed for: {sorted(missing)}"
        )
    return {
        "verified": True,
        "equation": (
            "expected_profit = debt_repaid * liquidation_penalty "
            "- gas_cost - debt_repaid * risk_cost_rate"
        ),
        "execution_rule": "expected_profit > 0",
        "capacity_scope": "global shared count after cross-collateral ranking",
        "capacity_unit": "liquidation opportunities per simulation step",
        "simulation_step_hours": 1,
        "legacy_capacity_default": "unbounded_none",
        "hidden_capacity_field_found": False,
        "operation_order": [
            "liquidatable inventory",
            "empirical demand selection when enabled",
            "global expected-profit ranking",
            "shared capacity attempt budget",
            "profitability outcome",
        ],
    }


def preregistration_payload(
    design: KeeperExecutionDesign = KeeperExecutionDesign(),
) -> dict[str, Any]:
    """Return the result-blind, immutable calibration specification."""
    design_payload = json.loads(json.dumps(asdict(design)))
    payload = {
        "study": "system_wide_keeper_execution_calibration",
        "status": "pre_registered_before_estimation",
        "design": design_payload,
        "scope": {
            "target_ilks": list(TARGET_ILKS),
            "capacity_scope": "one system-wide shared hourly count cap",
            "capacity_unit": (
                "protocol-level liquidation opportunities per one-hour "
                "simulation step"
            ),
            "eligible_windows": {
                "terra_cefi": [TERRA_START.isoformat(), TERRA_END.isoformat()],
                "quiet_mature": [QUIET_START.isoformat(), QUIET_END.isoformat()],
            },
            "excluded_estimation_windows": {
                "usdc_svb": [
                    USDC_SVB_START.isoformat(),
                    USDC_SVB_END.isoformat(),
                ],
                "withheld_final_validation": [
                    FINAL_VALIDATION_START.isoformat(),
                    FINAL_VALIDATION_END.isoformat(),
                ],
            },
        },
        "high_demand_definition": {
            "denominator": "positive start-of-hour unsafe system inventory",
            "primary_quantile": design.primary_high_demand_quantile,
            "robustness_quantiles": list(
                design.robustness_high_demand_quantiles
            ),
            "quantile_rule": "nearest_rank",
            "prohibition": (
                "positive observed closures are not a substitute denominator"
            ),
        },
        "execution_stress_definition": {
            "high_gas": "median effective gas price >= calibration q90",
            "high_volatility": (
                "maximum ETH/WBTC realised hourly-return volatility over "
                "24 hours >= calibration q90"
            ),
            "crypto_downside": (
                "minimum ETH/WBTC 24-hour log return <= calibration q05"
            ),
            "stress_rule": "at least two of the three conditions",
        },
        "capacity_identification_hierarchy": {
            "shared_effective_capacity_frontier_identified": {
                "minimum_high_demand_hours": (
                    design.minimum_high_demand_hours_level1
                ),
                "minimum_slack_hours": design.minimum_slack_hours_level1,
                "requires": [
                    "episode_block_bootstrap",
                    "observation_bootstrap",
                    "demand_threshold_robustness",
                    "calendar_block_stability",
                    "stable_upper_count_clustering",
                    "narrow_bootstrap_uncertainty",
                    "no_material_composition_instability",
                ],
            },
            "shared_capacity_partially_identified": {
                "minimum_high_demand_hours": (
                    design.capacity_level2_minimum_hours
                ),
                "minimum_slack_hours": (
                    design.capacity_level2_minimum_slack_hours
                ),
            },
            "shared_capacity_not_identified_use_sensitivity": (
                "retains count scale without claiming a frontier"
            ),
        },
        "capacity_profile_rule": {
            "adequate_regime_samples": (
                "low=stress p90, central=pooled p90, "
                "high=non-stress p95"
            ),
            "inadequate_regime_samples": (
                "low=pooled p75, central=pooled p90, high=pooled p95"
            ),
            "composition_widening": (
                "if mixed and single-collateral-dominant p90s differ by at "
                "least two and 25 per cent with at least ten hours each, "
                "lower low to the smaller composition p90 "
                "and raise high to the largest robustness p95"
            ),
            "composition_groups": {
                "single_collateral_dominant": (
                    "positive closures and largest collateral closure share "
                    "at or above 0.90"
                ),
                "mixed_collateral": (
                    "positive closures and largest collateral closure share "
                    "below 0.90"
                ),
                "no_closure": "zero observed protocol closures",
            },
            "level1_stability_rules": {
                "stable_upper_clustering": (
                    "at least three repetitions of a common upper-quartile "
                    "completed count"
                ),
                "threshold_robustness": (
                    "p90 range below both two opportunities and 25 per cent"
                ),
                "bootstrap_narrowness": (
                    "primary day-block p90 interval width no greater than "
                    "both two opportunities and 25 per cent of the estimate"
                ),
            },
            "integer_rule": "nearest_rank empirical integer quantiles",
            "physical_maximum_claim": False,
        },
        "population_scaling_hierarchy": {
            "direct_system_count": "direct system-capacity count",
            "level_b": (
                "population-scaled only when source and target vault "
                "denominators are both valid"
            ),
            "level_c": (
                "raw primary count plus later 250/500/1000-vault sensitivities"
            ),
        },
        "profit_hurdle_hierarchy": {
            "level1": {
                "minimum_positive": (
                    design.minimum_positive_profit_observations_level1
                ),
                "minimum_genuinely_negative_or_rejected": (
                    design.minimum_negative_profit_observations_level1
                ),
            },
            "successful_only_level2": {
                "direct_cost_only_hurdle": 0.0,
                "keeper_hurdle_low": (
                    "nearest-rank p05 successful direct-profit margin"
                ),
                "keeper_hurdle_high": (
                    "nearest-rank p25 successful direct-profit margin"
                ),
                "interpretation": (
                    "non-negative lower-bound sensitivities, not rejection "
                    "threshold estimates"
                ),
            },
            "level3": (
                "zero central and low, with one separately sourced "
                "conservative scenario only"
            ),
        },
        "profit_equation": {
            "simulator": (
                "debt_repaid = vault.debt_dai * max_close_factor; "
                "gross_reward = debt_repaid * liquidation_penalty; "
                "risk_cost = debt_repaid * risk_cost_rate; "
                "expected_profit = gross_reward - gas_cost - risk_cost; "
                "execute iff expected_profit > 0"
            ),
            "historical_direct_proxy": (
                "direct_profit = Take.owe_dai * effective liquidation penalty "
                "- clean top-level transaction gas cost USD"
            ),
            "negative_evidence_rule": (
                "a failed decoded call is not a rejected economic opportunity; "
                "Level 1 requires observable full economics for a rejected or "
                "genuinely negative decision"
            ),
        },
        "runtime_semantic_audit": audit_runtime_semantics(),
        "output_classifications": {
            "capacity": sorted(CAPACITY_CLASSIFICATIONS),
            "composition": sorted(COMPOSITION_CLASSIFICATIONS),
            "hurdle": sorted(HURDLE_CLASSIFICATIONS),
            "overall": [
                "shared_keeper_execution_registry_ready",
                "shared_keeper_execution_registry_ready_with_partial_identification",
                "shared_keeper_execution_registry_ready_with_sensitivity_only_hurdle",
                "shared_keeper_execution_calibration_blocked",
                "shared_keeper_execution_calibration_invalid",
            ],
        },
        "source_checksums": source_checksums(),
        "no_runtime_adoption": True,
        "no_final_validation_use": True,
    }
    return payload


def scientific_identity(payload: dict[str, Any]) -> str:
    """Return a stable result-blind identity for the specification."""
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def write_preregistration(
    diagnostic_root: Path = DEFAULT_DIAGNOSTIC_ROOT,
    design: KeeperExecutionDesign = KeeperExecutionDesign(),
) -> Path:
    """Write or verify the immutable result-blind specification snapshot."""
    payload = preregistration_payload(design)
    identity = scientific_identity(payload)
    path = diagnostic_root / identity / "preregistration_snapshot.json"
    canonical = json.dumps(
        payload, indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != canonical:
            raise ValueError("Existing keeper pre-registration is not immutable.")
    else:
        _atomic_text(path, canonical)
    return path


def nearest_rank(values: Iterable[float | int], probability: float) -> float:
    """Return the deterministic nearest-rank empirical quantile."""
    array = np.sort(np.asarray(list(values), dtype=float))
    if len(array) == 0:
        raise ValueError("Cannot calculate a quantile from an empty sample.")
    if not 0 <= probability <= 1:
        raise ValueError("Quantile probability must lie in [0, 1].")
    rank = max(1, math.ceil(probability * len(array)))
    return float(array[rank - 1])


def _collateral_family(ilk: str) -> str:
    if ilk.startswith("ETH-"):
        return "ETH"
    if ilk.startswith("WBTC-"):
        return "WBTC"
    return "OTHER"


def collateral_comparability() -> pd.DataFrame:
    """Return the explicit collateral inclusion and comparability audit."""
    if not LIQUIDATION_ACTIONS.is_file():
        frozen = (
            PROJECT_ROOT
            / "data/provenance/calibration/keeper/"
            "keeper_collateral_comparability.csv"
        )
        if not frozen.is_file():
            raise FileNotFoundError(
                "Neither the historical liquidation actions nor their frozen "
                "collateral-comparability evidence is available."
            )
        return pd.read_csv(frozen, low_memory=False)
    actions = pd.read_csv(
        LIQUIDATION_ACTIONS,
        usecols=["record_type", "ilk", "block_time"],
        low_memory=False,
    )
    barks = actions[
        actions["record_type"].eq("bark_event")
        & actions["ilk"].isin(TARGET_ILKS)
    ].copy()
    barks["block_time"] = pd.to_datetime(barks["block_time"], utc=True)
    action_checksum = sha256_file(LIQUIDATION_ACTIONS)
    rows = [
        {
            "collateral_identifier": ilk,
            "collateral_family": _collateral_family(ilk),
            "event_mechanism": "Liquidations 2.0 Dog.Bark plus Vat.grab",
            "protocol_version": "Maker Liquidations 2.0",
            "sample_start_utc": barks.loc[
                barks["ilk"].eq(ilk), "block_time"
            ].min().isoformat(),
            "sample_end_utc": barks.loc[
                barks["ilk"].eq(ilk), "block_time"
            ].max().isoformat(),
            "event_count": int(barks["ilk"].eq(ilk).sum()),
            "opportunity_mapping": (
                "one exact Bark-grab auction initiation maps to one "
                "protocol-level model opportunity; Takes are diagnostics"
            ),
            "debt_available": True,
            "collateral_value_available": True,
            "gas_available": True,
            "unsafe_inventory_available": True,
            "comparability_classification": "primary_comparable",
            "inclusion_status": "primary_capacity_sample",
            "exclusion_reason": "",
            "source_checksum": action_checksum,
        }
        for ilk in TARGET_ILKS
    ]
    rows.append(
        {
            "collateral_identifier": "OTHER_MAKER_COLLATERAL",
            "collateral_family": "OTHER",
            "event_mechanism": "not jointly validated",
            "protocol_version": "unverified in bounded local evidence",
            "sample_start_utc": "",
            "sample_end_utc": "",
            "event_count": 0,
            "opportunity_mapping": "unavailable",
            "debt_available": False,
            "collateral_value_available": False,
            "gas_available": False,
            "unsafe_inventory_available": False,
            "comparability_classification": "not_comparable",
            "inclusion_status": "excluded",
            "exclusion_reason": (
                "No jointly validated local unsafe-inventory and canonical "
                "Liquidations 2.0 mapping in the bounded calibration windows."
            ),
            "source_checksum": action_checksum,
        }
    )
    return pd.DataFrame(rows)


def _calibration_thresholds(market: pd.DataFrame) -> dict[str, float]:
    timestamps = pd.to_datetime(market["timestamp_utc"], utc=True)
    eligible = ~(
        timestamps.between(
            FINAL_VALIDATION_START,
            FINAL_VALIDATION_END,
            inclusive="left",
        )
        | timestamps.between(
            USDC_SVB_START,
            USDC_SVB_END,
            inclusive="left",
        )
    )
    work = market.loc[eligible].copy()
    work["eth_return_24h"] = (
        np.log(work["eth_price_usd"]).diff(24)
    )
    work["wbtc_return_24h"] = (
        np.log(work["wbtc_price_usd"]).diff(24)
    )
    work["eth_realised_volatility_24h"] = work[
        "eth_log_return"
    ].rolling(24, min_periods=24).std(ddof=0)
    work["wbtc_realised_volatility_24h"] = work[
        "wbtc_log_return"
    ].rolling(24, min_periods=24).std(ddof=0)
    work["crypto_realised_volatility_max_24h"] = work[
        ["eth_realised_volatility_24h", "wbtc_realised_volatility_24h"]
    ].max(axis=1)
    work["crypto_return_min_24h"] = work[
        ["eth_return_24h", "wbtc_return_24h"]
    ].min(axis=1)
    return {
        "high_gas_q90_gwei": nearest_rank(
            work["median_effective_gas_price_gwei"].dropna(), 0.90
        ),
        "high_volatility_q90": nearest_rank(
            work["crypto_realised_volatility_max_24h"].dropna(), 0.90
        ),
        "crypto_downside_q05": nearest_rank(
            work["crypto_return_min_24h"].dropna(), 0.05
        ),
        "threshold_sample_hours": int(len(work)),
    }


def _liquidator_and_gas_hourly() -> pd.DataFrame:
    """Return event-owned liquidator counts and transaction-level gas summaries."""
    actions = pd.read_csv(
        LIQUIDATION_ACTIONS,
        usecols=[
            "record_type",
            "ilk",
            "clipper_contract",
            "auction_id",
            "tx_hash",
            "block_time",
            "event_index",
            "kpr",
            "event_sender",
        ],
        low_memory=False,
    )
    barks = actions[
        actions["record_type"].eq("bark_event")
        & actions["ilk"].isin(TARGET_ILKS)
    ].copy()
    barks["timestamp_utc"] = pd.to_datetime(
        barks["block_time"], utc=True
    ).dt.floor("h")
    barks["tx_hash_normalised"] = barks["tx_hash"].str.lower()
    barks["liquidator_identity_proxy"] = barks["kpr"].fillna(
        barks["event_sender"]
    )
    if barks.duplicated(
        ["clipper_contract", "auction_id", "tx_hash_normalised", "event_index"]
    ).any():
        raise ValueError("Bark source ownership contains duplicate event keys.")
    liquidators = (
        barks.groupby(["timestamp_utc", "ilk"], as_index=False)[
            "liquidator_identity_proxy"
        ]
        .nunique(dropna=True)
        .rename(
            columns={
                "liquidator_identity_proxy": "unique_liquidator_count"
            }
        )
    )
    gas = pd.read_csv(
        LIQUIDATION_GAS,
        usecols=["tx_hash", "transaction_gas_cost_usd"],
    )
    gas["tx_hash_normalised"] = gas["tx_hash"].str.lower()
    if gas["tx_hash_normalised"].duplicated().any():
        raise ValueError("Transaction gas source is not unique by transaction hash.")
    event_gas = barks[
        ["timestamp_utc", "ilk", "tx_hash_normalised"]
    ].drop_duplicates().merge(
        gas[["tx_hash_normalised", "transaction_gas_cost_usd"]],
        on="tx_hash_normalised",
        how="left",
        validate="many_to_one",
    )
    gas_hourly = (
        event_gas.groupby(["timestamp_utc", "ilk"])[
            "transaction_gas_cost_usd"
        ]
        .agg(
            median_gas_cost_dai="median",
            p90_gas_cost_dai=lambda values: nearest_rank(
                values.dropna(), 0.90
            )
            if values.notna().any()
            else np.nan,
        )
        .reset_index()
    )
    return liquidators.merge(
        gas_hourly,
        on=["timestamp_utc", "ilk"],
        how="outer",
        validate="one_to_one",
    )


def build_hourly_panel() -> tuple[pd.DataFrame, dict[str, float]]:
    """Build the collateral-hour and system-hour calibration panel."""
    liquidation = pd.read_csv(LIQUIDATION_HOURLY)
    liquidation["timestamp_utc"] = pd.to_datetime(
        liquidation["timestamp_utc"], utc=True
    )
    liquidation = liquidation[
        liquidation["ilk"].isin(TARGET_ILKS)
    ].copy()

    terra = pd.read_csv(TERRA_STRESS)
    terra["timestamp_utc"] = pd.to_datetime(terra["timestamp_utc"], utc=True)
    terra = terra[terra["collateral_scope"].isin(TARGET_ILKS)].copy()
    terra = terra.rename(
        columns={
            "collateral_scope": "ilk",
            "liquidatable_vaults": "start_unsafe_inventory",
        }
    )
    terra["source_window"] = "terra_cefi"
    terra["inventory_source"] = "exact_reconstructed_start_of_hour_state"

    quiet = pd.read_csv(LIQUIDATABLE_SHARE)
    quiet["timestamp_utc"] = pd.to_datetime(quiet["timestamp_utc"], utc=True)
    quiet = quiet[
        quiet["window"].eq("quiet_mature")
        & quiet["collateral_scope"].isin(TARGET_ILKS)
    ].copy()
    quiet = quiet.rename(
        columns={
            "collateral_scope": "ilk",
            "liquidatable_vaults": "start_unsafe_inventory",
        }
    )
    quiet["source_window"] = "quiet_mature"
    quiet["inventory_source"] = "exact_reconstructed_start_of_hour_state"

    inventory_columns = [
        "timestamp_utc",
        "ilk",
        "start_unsafe_inventory",
        "source_window",
        "inventory_source",
    ]
    inventory = pd.concat(
        [terra[inventory_columns], quiet[inventory_columns]],
        ignore_index=True,
    )
    if inventory.duplicated(["timestamp_utc", "ilk"]).any():
        raise ValueError("Representative inventory contains duplicate ilk-hours.")

    raw_columns = [
        "timestamp_utc",
        "ilk",
        "auctions_initiated",
        "auctions_completed",
        "collateral_liquidated_wad",
        "debt_targeted_dai",
        "debt_repaid_dai",
        "successful_takes",
        "failed_take_attempts",
        "unique_keepers",
        "unresolved_auctions",
        "gas_used_unambiguous",
        "gas_cost_usd_unambiguous",
    ]
    panel = inventory.merge(
        liquidation[raw_columns],
        on=["timestamp_utc", "ilk"],
        how="left",
        validate="one_to_one",
    )
    if panel[raw_columns[2:]].isna().any().any():
        raise ValueError("Representative panel has unmatched liquidation hours.")

    liquidator_gas = _liquidator_and_gas_hourly()
    panel = panel.merge(
        liquidator_gas,
        on=["timestamp_utc", "ilk"],
        how="left",
        validate="one_to_one",
    )
    panel["unique_liquidator_count"] = (
        panel["unique_liquidator_count"].fillna(0).astype(int)
    )

    market = pd.read_csv(MARKET_GAS_HOURLY)
    market["timestamp_utc"] = pd.to_datetime(market["timestamp_utc"], utc=True)
    market_columns = [
        "timestamp_utc",
        "eth_price_usd",
        "wbtc_price_usd",
        "eth_log_return",
        "wbtc_log_return",
        "dai_peg_deviation",
        "median_effective_gas_price_gwei",
        "p90_effective_gas_price_gwei",
        "p99_effective_gas_price_gwei",
        "target_normalised_block_utilisation",
        "failed_transaction_share",
    ]
    panel = panel.merge(
        market[market_columns],
        on="timestamp_utc",
        how="left",
        validate="many_to_one",
    )
    if panel[market_columns[1:]].isna().any().any():
        raise ValueError("Representative panel has unmatched market/gas hours.")

    protocol = pd.read_csv(
        PROTOCOL_HOURLY,
        usecols=["timestamp_utc", "ilk", "liquidation_ratio", "ilk_active"],
    )
    protocol["timestamp_utc"] = pd.to_datetime(
        protocol["timestamp_utc"], utc=True
    )
    panel = panel.merge(
        protocol,
        on=["timestamp_utc", "ilk"],
        how="left",
        validate="one_to_one",
    )
    if panel[["liquidation_ratio", "ilk_active"]].isna().any().any():
        raise ValueError("Representative panel has unmatched protocol hours.")

    panel["collateral_family"] = panel["ilk"].map(_collateral_family)
    panel["is_system_aggregate"] = False
    panel["successful_protocol_closures"] = panel["auctions_initiated"].astype(
        int
    )
    panel["observed_liquidation_arrivals"] = panel[
        "auctions_initiated"
    ].astype(int)
    panel["observed_protocol_closures"] = panel[
        "auctions_initiated"
    ].astype(int)
    panel["observed_successful_takes"] = panel["successful_takes"].astype(int)
    panel["completed_debt_dai"] = panel["debt_targeted_dai"]
    panel["collateral_price_usd"] = np.where(
        panel["collateral_family"].eq("ETH"),
        panel["eth_price_usd"],
        panel["wbtc_price_usd"],
    )
    panel["completed_collateral_value_usd"] = (
        panel["collateral_liquidated_wad"] * panel["collateral_price_usd"]
    )
    panel["newly_unsafe_inventory"] = np.nan
    panel["newly_unsafe_inventory_quality"] = (
        "unavailable_from_start_of_hour_snapshot"
    )
    panel["unresolved_end_lower_bound"] = (
        panel["start_unsafe_inventory"]
        - panel["successful_protocol_closures"]
    ).clip(lower=0)
    panel["closures_exceed_start_inventory"] = (
        panel["successful_protocol_closures"]
        > panel["start_unsafe_inventory"]
    )

    summed_columns = [
        "start_unsafe_inventory",
        "auctions_initiated",
        "auctions_completed",
        "collateral_liquidated_wad",
        "debt_targeted_dai",
        "debt_repaid_dai",
        "successful_takes",
        "failed_take_attempts",
        "unique_keepers",
        "unresolved_auctions",
        "gas_used_unambiguous",
        "gas_cost_usd_unambiguous",
        "successful_protocol_closures",
        "observed_liquidation_arrivals",
        "observed_protocol_closures",
        "observed_successful_takes",
        "completed_debt_dai",
        "completed_collateral_value_usd",
        "unresolved_end_lower_bound",
    ]
    system = (
        panel.groupby(["source_window", "timestamp_utc"], as_index=False)[
            summed_columns
        ]
        .sum()
    )
    system = system.merge(
        market[market_columns],
        on="timestamp_utc",
        how="left",
        validate="many_to_one",
    )
    system["ilk"] = SYSTEM_SCOPE
    system["inventory_source"] = (
        "sum_of_six_exact_ilk_start_of_hour_states"
    )
    system["collateral_family"] = "SYSTEM"
    system["is_system_aggregate"] = True
    system["liquidation_ratio"] = np.nan
    system["ilk_active"] = True
    system["newly_unsafe_inventory"] = np.nan
    system["newly_unsafe_inventory_quality"] = (
        "unavailable_from_start_of_hour_snapshot"
    )
    system["closures_exceed_start_inventory"] = (
        system["successful_protocol_closures"]
        > system["start_unsafe_inventory"]
    )

    terra_all = pd.read_csv(TERRA_STRESS)
    terra_all["timestamp_utc"] = pd.to_datetime(
        terra_all["timestamp_utc"], utc=True
    )
    terra_all = terra_all[
        terra_all["collateral_scope"].eq("ALL")
    ].set_index("timestamp_utc")
    observed = system[
        system["source_window"].eq("terra_cefi")
    ].set_index("timestamp_utc")
    if not observed["start_unsafe_inventory"].equals(
        terra_all["liquidatable_vaults"].astype(int)
    ):
        raise ValueError("System unsafe inventory does not equal exact-ilk sum.")
    if not observed["successful_protocol_closures"].equals(
        terra_all["grab_executions"].astype(int)
    ):
        raise ValueError("System protocol closures do not reconcile to grabs.")

    exact_liquidators = pd.read_csv(
        LIQUIDATION_ACTIONS,
        usecols=[
            "record_type",
            "ilk",
            "block_time",
            "kpr",
            "event_sender",
        ],
        low_memory=False,
    )
    exact_liquidators = exact_liquidators[
        exact_liquidators["record_type"].eq("bark_event")
        & exact_liquidators["ilk"].isin(TARGET_ILKS)
    ].copy()
    exact_liquidators["timestamp_utc"] = pd.to_datetime(
        exact_liquidators["block_time"], utc=True
    ).dt.floor("h")
    exact_liquidators["liquidator_identity_proxy"] = exact_liquidators[
        "kpr"
    ].fillna(exact_liquidators["event_sender"])
    system_liquidators = (
        exact_liquidators.groupby("timestamp_utc", as_index=False)[
            "liquidator_identity_proxy"
        ]
        .nunique(dropna=True)
        .rename(
            columns={
                "liquidator_identity_proxy": "unique_liquidator_count"
            }
        )
    )
    system = system.merge(
        system_liquidators,
        on="timestamp_utc",
        how="left",
        validate="many_to_one",
    )
    system["unique_liquidator_count"] = (
        system["unique_liquidator_count"].fillna(0).astype(int)
    )
    exact_gas = panel[
        ["source_window", "timestamp_utc", "median_gas_cost_dai", "p90_gas_cost_dai"]
    ]
    system_gas = (
        exact_gas.groupby(["source_window", "timestamp_utc"], as_index=False)
        .agg(
            median_gas_cost_dai=("median_gas_cost_dai", "median"),
            p90_gas_cost_dai=("p90_gas_cost_dai", "max"),
        )
    )
    system = system.merge(
        system_gas,
        on=["source_window", "timestamp_utc"],
        how="left",
        validate="one_to_one",
    )

    closure_pivot = panel.pivot(
        index=["source_window", "timestamp_utc"],
        columns="ilk",
        values="successful_protocol_closures",
    ).fillna(0)
    closure_total = closure_pivot.sum(axis=1)
    largest = closure_pivot.max(axis=1)
    debt_pivot = panel.pivot(
        index=["source_window", "timestamp_utc"],
        columns="ilk",
        values="completed_debt_dai",
    ).fillna(0)
    debt_total = debt_pivot.sum(axis=1)
    debt_shares = debt_pivot.div(debt_total.replace(0, np.nan), axis=0)
    eth_columns = [name for name in closure_pivot if name.startswith("ETH-")]
    wbtc_columns = [name for name in closure_pivot if name.startswith("WBTC-")]
    composition = pd.DataFrame(
        {
            "source_window": closure_pivot.index.get_level_values(0),
            "timestamp_utc": closure_pivot.index.get_level_values(1),
            "positive_closure_collateral_count": closure_pivot.gt(0).sum(axis=1),
            "largest_collateral_closure_share": _safe_divide(
                largest, closure_total
            ).fillna(0),
            "eth_closure_share": _safe_divide(
                closure_pivot[eth_columns].sum(axis=1), closure_total
            ).fillna(0),
            "wbtc_closure_share": _safe_divide(
                closure_pivot[wbtc_columns].sum(axis=1), closure_total
            ).fillna(0),
            "debt_weighted_collateral_concentration": (
                debt_shares.pow(2).sum(axis=1).fillna(0)
            ),
        }
    ).reset_index(drop=True)
    composition["crypto_closure_share"] = (
        composition["eth_closure_share"]
        + composition["wbtc_closure_share"]
    )
    composition["stable_collateral_closure_share"] = 0.0
    composition["eth_dominant"] = (
        composition["eth_closure_share"]
        > composition["wbtc_closure_share"]
    )
    composition["non_eth_dominant"] = (
        composition["wbtc_closure_share"]
        > composition["eth_closure_share"]
    )
    composition["composition_group"] = "no_closure"
    composition.loc[
        closure_total.to_numpy() > 0,
        "composition_group",
    ] = "single_collateral_dominant"
    composition.loc[
        (closure_total.to_numpy() > 0)
        & (composition["largest_collateral_closure_share"].to_numpy() < 0.90),
        "composition_group",
    ] = "mixed_collateral"
    active = (
        panel.groupby(["source_window", "timestamp_utc"])["ilk_active"]
        .sum()
        .rename("active_collateral_type_count")
        .reset_index()
    )
    system = system.merge(
        composition,
        on=["source_window", "timestamp_utc"],
        how="left",
        validate="one_to_one",
    ).merge(
        active,
        on=["source_window", "timestamp_utc"],
        how="left",
        validate="one_to_one",
    )

    panel = pd.concat([panel, system], ignore_index=True, sort=False)
    panel = panel.sort_values(
        ["source_window", "timestamp_utc", "is_system_aggregate", "ilk"],
        kind="stable",
    ).reset_index(drop=True)
    thresholds = _calibration_thresholds(market)
    market_ordered = market.sort_values("timestamp_utc").copy()
    market_ordered["eth_return_24h"] = np.log(
        market_ordered["eth_price_usd"]
    ).diff(24)
    market_ordered["wbtc_return_24h"] = np.log(
        market_ordered["wbtc_price_usd"]
    ).diff(24)
    market_ordered["eth_realised_volatility_24h"] = market_ordered[
        "eth_log_return"
    ].rolling(24, min_periods=24).std(ddof=0)
    market_ordered["wbtc_realised_volatility_24h"] = market_ordered[
        "wbtc_log_return"
    ].rolling(24, min_periods=24).std(ddof=0)
    derived_market = market_ordered[
        [
            "timestamp_utc",
            "eth_return_24h",
            "wbtc_return_24h",
            "eth_realised_volatility_24h",
            "wbtc_realised_volatility_24h",
        ]
    ]
    panel = panel.merge(
        derived_market,
        on="timestamp_utc",
        how="left",
        validate="many_to_one",
    )
    panel["market_return_24h"] = np.where(
        panel["collateral_family"].eq("ETH"),
        panel["eth_return_24h"],
        np.where(
            panel["collateral_family"].eq("WBTC"),
            panel["wbtc_return_24h"],
            panel[["eth_return_24h", "wbtc_return_24h"]].min(axis=1),
        ),
    )
    panel["realised_volatility_24h"] = np.where(
        panel["collateral_family"].eq("ETH"),
        panel["eth_realised_volatility_24h"],
        np.where(
            panel["collateral_family"].eq("WBTC"),
            panel["wbtc_realised_volatility_24h"],
            panel[
                [
                    "eth_realised_volatility_24h",
                    "wbtc_realised_volatility_24h",
                ]
            ].max(axis=1),
        ),
    )
    panel["high_gas"] = (
        panel["median_effective_gas_price_gwei"]
        >= thresholds["high_gas_q90_gwei"]
    )
    panel["high_crypto_volatility"] = (
        panel["realised_volatility_24h"]
        >= thresholds["high_volatility_q90"]
    )
    panel["crypto_downside"] = (
        panel["market_return_24h"]
        <= thresholds["crypto_downside_q05"]
    )
    panel["execution_stress_condition_count"] = panel[
        ["high_gas", "high_crypto_volatility", "crypto_downside"]
    ].sum(axis=1)
    panel["execution_stress"] = (
        panel["execution_stress_condition_count"] >= 2
    )
    panel["gas_stress"] = panel["high_gas"]
    panel["market_stress"] = (
        panel["high_crypto_volatility"] | panel["crypto_downside"]
    )
    panel["gas_cost_quality"] = np.where(
        panel["median_gas_cost_dai"].notna(),
        "observed_transaction_level",
        "unavailable_for_bark_transaction_in_take_gas_source",
    )
    panel["data_quality_flags"] = (
        "exact_hourly_join;newly_unsafe_unavailable;"
        + panel["gas_cost_quality"]
    )
    panel["next_hour_start_unsafe_inventory"] = panel.groupby(
        ["source_window", "ilk"], sort=False
    )["start_unsafe_inventory"].shift(-1)
    panel["next_hour_carryover_proxy"] = np.minimum(
        panel["unresolved_end_lower_bound"],
        panel["next_hour_start_unsafe_inventory"],
    )
    panel["capacity_unit"] = (
        "protocol_liquidation_opportunities_per_one_hour_step"
    )
    panel["estimation_eligible"] = True
    return panel, thresholds


def _episode_ids(frame: pd.DataFrame) -> pd.Series:
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    starts = timestamps.diff().dt.total_seconds().fillna(np.inf).ne(3600)
    return starts.cumsum().astype(int)


def _bootstrap_interval(
    frame: pd.DataFrame,
    probability: float,
    *,
    seed: int,
    replications: int,
    cluster: bool,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    values = frame["successful_protocol_closures"].to_numpy(dtype=int)
    estimates: list[float] = []
    if cluster:
        blocks = [
            group["successful_protocol_closures"].to_numpy(dtype=int)
            for _, group in frame.groupby("bootstrap_block_id", sort=True)
        ]
        for _ in range(replications):
            selections = rng.integers(0, len(blocks), size=len(blocks))
            sample = np.concatenate([blocks[index] for index in selections])
            estimates.append(nearest_rank(sample, probability))
    else:
        for _ in range(replications):
            sample = rng.choice(values, size=len(values), replace=True)
            estimates.append(nearest_rank(sample, probability))
    return nearest_rank(estimates, 0.025), nearest_rank(estimates, 0.975)


def _distribution_summary(values: pd.Series) -> dict[str, Any]:
    """Return deterministic descriptive statistics for a numeric series."""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"count": 0}
    mean = float(clean.mean())
    variance = float(clean.var(ddof=0))
    return {
        "count": int(len(clean)),
        "minimum": float(clean.min()),
        "p25": nearest_rank(clean, 0.25),
        "median": nearest_rank(clean, 0.50),
        "p75": nearest_rank(clean, 0.75),
        "p90": nearest_rank(clean, 0.90),
        "p95": nearest_rank(clean, 0.95),
        "maximum": float(clean.max()),
        "mean": mean,
        "standard_deviation": float(clean.std(ddof=0)),
        "index_of_dispersion": variance / mean if mean > 0 else None,
        "zero_share": float(clean.eq(0).mean()),
    }


def _safe_correlation(left: pd.Series, right: pd.Series) -> float | None:
    valid = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(valid) < 3 or valid["left"].nunique() < 2 or valid["right"].nunique() < 2:
        return None
    value = float(valid["left"].corr(valid["right"]))
    return value if math.isfinite(value) else None


def _active_liquidator_evidence(primary: pd.DataFrame) -> dict[str, Any]:
    """Summarise Bark incentive-recipient evidence without treating it as capacity."""
    counts = primary["unique_liquidator_count"]
    positive = primary[primary["successful_protocol_closures"] > 0]
    total_events = int(positive["successful_protocol_closures"].sum())
    concentration = (
        float(
            positive["successful_protocol_closures"].max() / total_events
        )
        if total_events
        else None
    )
    return {
        "identity_semantics": (
            "distinct Bark kpr where decoded, otherwise Bark event transaction "
            "sender, per hour; a protocol liquidator identity proxy rather "
            "than all Take participants"
        ),
        "distribution": _distribution_summary(counts),
        "positive_closure_hour_distribution": _distribution_summary(
            positive["unique_liquidator_count"]
        ),
        "largest_hour_closure_concentration": concentration,
        "correlation_with_closures": _safe_correlation(
            counts, primary["successful_protocol_closures"]
        ),
        "correlation_with_median_gas_cost": _safe_correlation(
            counts, primary["median_gas_cost_dai"]
        ),
        "correlation_with_network_median_gas_price": _safe_correlation(
            counts, primary["median_effective_gas_price_gwei"]
        ),
        "correlation_with_volatility": _safe_correlation(
            counts, primary["realised_volatility_24h"]
        ),
        "mixed_hour_mean": (
            float(
                primary.loc[
                    primary["composition_group"].eq("mixed_collateral"),
                    "unique_liquidator_count",
                ].mean()
            )
            if primary["composition_group"].eq("mixed_collateral").any()
            else None
        ),
        "supporting_evidence_only": True,
    }


def estimate_capacity(
    panel: pd.DataFrame,
    design: KeeperExecutionDesign,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Estimate and classify the shared system-wide capacity frontier."""
    system = panel[panel["ilk"].eq(SYSTEM_SCOPE)].copy()
    positive_inventory = system[
        system["start_unsafe_inventory"] > 0
    ]["start_unsafe_inventory"]
    if positive_inventory.empty:
        return pd.DataFrame(), {
            "classification": (
                "shared_capacity_not_identified_use_sensitivity"
            ),
            "reason": "no_positive_start_unsafe_inventory",
        }

    demand_definitions = (
        ("primary_q75", design.primary_high_demand_quantile),
        ("robustness_q67", design.robustness_high_demand_quantiles[0]),
        ("robustness_q90", design.robustness_high_demand_quantiles[1]),
    )
    rows: list[dict[str, Any]] = []
    primary: pd.DataFrame | None = None
    threshold_p90: dict[str, int] = {}
    for definition, demand_quantile in demand_definitions:
        threshold = int(nearest_rank(positive_inventory, demand_quantile))
        high = system[
            system["start_unsafe_inventory"] >= threshold
        ].copy()
        high["high_demand_episode_id"] = _episode_ids(high)
        high["bootstrap_block_id"] = high["timestamp_utc"].dt.strftime(
            "%Y-%m-%d"
        )
        if definition == "primary_q75":
            primary = high.copy()
        subsets = {
            "pooled": high,
            "execution_stress": high[high["execution_stress"]],
            "non_stress": high[~high["execution_stress"]],
        }
        for subset_name, subset in subsets.items():
            if subset.empty:
                continue
            estimates: dict[str, Any] = {}
            for label, probability in (
                ("p75", 0.75),
                ("p90", 0.90),
                ("p95", 0.95),
            ):
                observation_low, observation_high = _bootstrap_interval(
                    subset,
                    probability,
                    seed=design.random_seed
                    + int(demand_quantile * 100)
                    + int(probability * 100),
                    replications=design.bootstrap_replications,
                    cluster=False,
                )
                cluster_low, cluster_high = _bootstrap_interval(
                    subset,
                    probability,
                    seed=design.random_seed
                    + 1_000
                    + int(demand_quantile * 100)
                    + int(probability * 100),
                    replications=design.bootstrap_replications,
                    cluster=True,
                )
                value = int(
                    nearest_rank(
                        subset["successful_protocol_closures"], probability
                    )
                )
                estimates[label] = value
                estimates[f"{label}_observation_bootstrap_low"] = (
                    observation_low
                )
                estimates[f"{label}_observation_bootstrap_high"] = (
                    observation_high
                )
                estimates[f"{label}_day_block_bootstrap_low"] = cluster_low
                estimates[f"{label}_day_block_bootstrap_high"] = cluster_high
            if subset_name == "pooled":
                threshold_p90[definition] = estimates["p90"]
            upper_counts = (
                subset.loc[
                    subset["successful_protocol_closures"]
                    >= estimates["p75"],
                    "successful_protocol_closures",
                ]
                .value_counts()
                .sort_index()
            )
            rows.append(
                {
                    "row_type": "frontier",
                    "system_or_diagnostic_scope": "SYSTEM_ALL",
                    "demand_definition": definition,
                    "inventory_threshold": threshold,
                    "regime": subset_name,
                    "composition_group": "all_compositions",
                    "sample_count": int(len(subset)),
                    "demand_slack_hours": int(
                        (
                            subset["successful_protocol_closures"]
                            < subset["start_unsafe_inventory"]
                        ).sum()
                    ),
                    **estimates,
                    "maximum": int(
                        subset["successful_protocol_closures"].max()
                    ),
                    "upper_value_frequencies": json.dumps(
                        {
                            str(int(key)): int(value)
                            for key, value in upper_counts.items()
                        },
                        sort_keys=True,
                    ),
                    "saturation_diagnostic": (
                        "supporting_only_not_physical_capacity"
                    ),
                    "composition_diagnostic": "pooled",
                    "stability_diagnostic": "reported_in_decision",
                    "classification": "pending_hierarchy",
                    "mapped_count": estimates["p90"],
                }
            )
        high["calendar_block"] = high["timestamp_utc"].dt.strftime("%Y-%m")
        for calendar_block, block in high.groupby("calendar_block"):
            rows.append(
                {
                    "row_type": "calendar_block_p90",
                    "system_or_diagnostic_scope": "SYSTEM_ALL",
                    "demand_definition": definition,
                    "inventory_threshold": threshold,
                    "regime": "pooled",
                    "composition_group": "all_compositions",
                    "sample_count": len(block),
                    "demand_slack_hours": int(
                        (
                            block["successful_protocol_closures"]
                            < block["start_unsafe_inventory"]
                        ).sum()
                    ),
                    "p75": int(
                        nearest_rank(
                            block["successful_protocol_closures"], 0.75
                        )
                    ),
                    "p90": int(
                        nearest_rank(
                            block["successful_protocol_closures"], 0.90
                        )
                    ),
                    "p95": int(
                        nearest_rank(
                            block["successful_protocol_closures"], 0.95
                        )
                    ),
                    "maximum": int(
                        block["successful_protocol_closures"].max()
                    ),
                    "upper_value_frequencies": "",
                    "saturation_diagnostic": "",
                    "composition_diagnostic": "",
                    "stability_diagnostic": calendar_block,
                    "classification": "diagnostic",
                    "mapped_count": np.nan,
                }
            )

    assert primary is not None
    composition_estimates: dict[str, dict[str, Any]] = {}
    for composition_group, group in primary.groupby(
        "composition_group", sort=True
    ):
        if group.empty:
            continue
        estimates = {
            label: int(
                nearest_rank(
                    group["successful_protocol_closures"], probability
                )
            )
            for label, probability in (
                ("p75", 0.75),
                ("p90", 0.90),
                ("p95", 0.95),
            )
        }
        composition_estimates[composition_group] = {
            "hours": int(len(group)),
            **estimates,
            "completed_debt_dai_p90": nearest_rank(
                group["completed_debt_dai"], 0.90
            ),
            "median_gas_cost_dai": (
                float(group["median_gas_cost_dai"].median())
                if group["median_gas_cost_dai"].notna().any()
                else None
            ),
            "active_liquidator_p90": int(
                nearest_rank(group["unique_liquidator_count"], 0.90)
            ),
        }
        rows.append(
            {
                "row_type": "composition",
                "system_or_diagnostic_scope": "SYSTEM_ALL",
                "demand_definition": "primary_q75",
                "inventory_threshold": int(
                    nearest_rank(
                        positive_inventory,
                        design.primary_high_demand_quantile,
                    )
                ),
                "regime": "pooled",
                "composition_group": composition_group,
                "sample_count": len(group),
                "demand_slack_hours": int(
                    (
                        group["successful_protocol_closures"]
                        < group["start_unsafe_inventory"]
                    ).sum()
                ),
                **estimates,
                "maximum": int(
                    group["successful_protocol_closures"].max()
                ),
                "upper_value_frequencies": "",
                "saturation_diagnostic": "",
                "composition_diagnostic": "primary_group",
                "stability_diagnostic": "",
                "classification": "diagnostic",
                "mapped_count": estimates["p90"],
            }
        )

    primary_slack = int(
        (
            primary["successful_protocol_closures"]
            < primary["start_unsafe_inventory"]
        ).sum()
    )
    calendar_values = [
        int(
            nearest_rank(
                group["successful_protocol_closures"],
                0.90,
            )
        )
        for _, group in primary.assign(
            calendar_block=primary["timestamp_utc"].dt.strftime("%Y-%m")
        ).groupby("calendar_block")
    ]
    calendar_difference = (
        max(calendar_values) - min(calendar_values)
        if len(calendar_values) >= 2
        else math.inf
    )
    calendar_relative = (
        calendar_difference / max(calendar_values)
        if calendar_values and max(calendar_values) > 0
        else math.inf
    )
    calendar_unstable = (
        calendar_difference >= design.calendar_instability_absolute
        and calendar_relative >= design.calendar_instability_relative
    )
    mixed = composition_estimates.get("mixed_collateral")
    dominant = composition_estimates.get("single_collateral_dominant")
    composition_sample_adequate = bool(
        mixed
        and dominant
        and mixed["hours"] >= design.minimum_composition_group_hours
        and dominant["hours"] >= design.minimum_composition_group_hours
    )
    composition_difference = (
        abs(mixed["p90"] - dominant["p90"])
        if mixed and dominant
        else math.inf
    )
    composition_relative = (
        composition_difference / max(mixed["p90"], dominant["p90"])
        if mixed and dominant and max(mixed["p90"], dominant["p90"]) > 0
        else math.inf
    )
    composition_sensitive = (
        composition_sample_adequate
        and composition_difference
        >= design.composition_instability_absolute
        and composition_relative
        >= design.composition_instability_relative
    )
    if not composition_sample_adequate:
        composition_classification = "composition_unresolved"
    elif composition_sensitive:
        composition_classification = (
            "composition_sensitive_shared_capacity"
        )
    else:
        composition_classification = "composition_stable"

    pooled_counts = primary["successful_protocol_closures"]
    pooled_p75 = int(nearest_rank(pooled_counts, 0.75))
    pooled_p90 = int(nearest_rank(pooled_counts, 0.90))
    pooled_p95 = int(nearest_rank(pooled_counts, 0.95))
    upper_frequencies = pooled_counts[
        pooled_counts >= pooled_p75
    ].value_counts()
    repeated_upper_count = (
        int(upper_frequencies.max()) if not upper_frequencies.empty else 0
    )
    stable_upper_clustering = (
        repeated_upper_count >= design.minimum_repeated_upper_count
    )
    threshold_range = max(threshold_p90.values()) - min(
        threshold_p90.values()
    )
    threshold_relative = threshold_range / max(threshold_p90.values())
    threshold_robust = (
        threshold_range < design.frontier_threshold_robustness_absolute
        and threshold_relative
        < design.frontier_threshold_robustness_relative
    )
    primary_row = next(
        row
        for row in rows
        if row["row_type"] == "frontier"
        and row["demand_definition"] == "primary_q75"
        and row["regime"] == "pooled"
    )
    bootstrap_width = (
        primary_row["p90_day_block_bootstrap_high"]
        - primary_row["p90_day_block_bootstrap_low"]
    )
    bootstrap_relative = bootstrap_width / max(pooled_p90, 1)
    bootstrap_narrow = (
        bootstrap_width <= design.maximum_bootstrap_interval_absolute
        and bootstrap_relative
        <= design.maximum_bootstrap_interval_relative
    )
    stress_hours = int(primary["execution_stress"].sum())
    non_stress_hours = int((~primary["execution_stress"]).sum())
    regime_adequate = min(stress_hours, non_stress_hours) >= (
        design.minimum_regime_hours
    )
    if (
        len(primary) >= design.minimum_high_demand_hours_level1
        and primary_slack >= design.minimum_slack_hours_level1
        and not calendar_unstable
        and stable_upper_clustering
        and threshold_robust
        and bootstrap_narrow
        and composition_classification == "composition_stable"
    ):
        classification = "shared_effective_capacity_frontier_identified"
    elif (
        len(primary) >= design.capacity_level2_minimum_hours
        and primary_slack >= design.capacity_level2_minimum_slack_hours
        and composition_classification
        != "composition_sensitive_shared_capacity"
    ):
        classification = "shared_capacity_partially_identified"
    else:
        classification = (
            "shared_capacity_not_identified_use_sensitivity"
        )

    if regime_adequate:
        low = int(
            nearest_rank(
                primary.loc[
                    primary["execution_stress"],
                    "successful_protocol_closures",
                ],
                0.90,
            )
        )
        central = pooled_p90
        high = int(
            nearest_rank(
                primary.loc[
                    ~primary["execution_stress"],
                    "successful_protocol_closures",
                ],
                0.95,
            )
        )
        profile_basis = "regime_specific"
    else:
        low = pooled_p75
        central = pooled_p90
        high = pooled_p95
        profile_basis = "pooled_insufficient_regime_samples"
    pre_widening = {"low": low, "central": central, "high": high}
    if composition_sensitive:
        low = min(low, mixed["p90"], dominant["p90"])
        robustness_high = max(
            row["p95"]
            for row in rows
            if row["row_type"] == "frontier"
            and row["regime"] == "pooled"
        )
        high = max(high, int(robustness_high))
    if not 0 < low <= central <= high:
        raise ValueError("Keeper capacity profiles are not ordered positive integers.")

    decision = {
        "classification": classification,
        "capacity_scale": "direct_system_count",
        "primary_inventory_threshold": int(
            nearest_rank(
                positive_inventory, design.primary_high_demand_quantile
            )
        ),
        "positive_inventory_hours": int(len(positive_inventory)),
        "high_demand_hours": int(len(primary)),
        "slack_hours": primary_slack,
        "stress_hours": stress_hours,
        "non_stress_hours": non_stress_hours,
        "regime_samples_adequate": regime_adequate,
        "calendar_block_count": len(calendar_values),
        "calendar_block_p90_values": calendar_values,
        "calendar_instability_absolute": calendar_difference,
        "calendar_instability_relative": calendar_relative,
        "calendar_stable": not calendar_unstable,
        "stable_upper_clustering": stable_upper_clustering,
        "repeated_upper_value_max_frequency": repeated_upper_count,
        "threshold_p90_values": threshold_p90,
        "threshold_robust": threshold_robust,
        "threshold_p90_range": threshold_range,
        "threshold_p90_relative_range": threshold_relative,
        "primary_p90_day_block_bootstrap_width": bootstrap_width,
        "primary_p90_day_block_bootstrap_relative_width": bootstrap_relative,
        "bootstrap_uncertainty_narrow": bootstrap_narrow,
        "composition_classification": composition_classification,
        "composition_estimates": composition_estimates,
        "composition_difference": (
            composition_difference
            if math.isfinite(composition_difference)
            else None
        ),
        "composition_relative_difference": (
            composition_relative
            if math.isfinite(composition_relative)
            else None
        ),
        "profile_basis": profile_basis,
        "pre_composition_widening": pre_widening,
        "profiles": {"low": low, "central": central, "high": high},
        "completed_count_distribution": _distribution_summary(pooled_counts),
        "completed_debt_distribution": _distribution_summary(
            primary["completed_debt_dai"]
        ),
        "completed_collateral_value_distribution": _distribution_summary(
            primary["completed_collateral_value_usd"]
        ),
        "aggregate_inventory_utilisation": {
            **_distribution_summary(
                _safe_divide(
                    primary["successful_protocol_closures"],
                    primary["start_unsafe_inventory"].clip(lower=1),
                )
            ),
            "interpretation": (
                "aggregate execution-to-starting-unsafe-inventory ratio; "
                "arrivals and profitability may also bind"
            ),
        },
        "demand_categories": {
            "category_a_demand_insufficient_hours": int(
                (
                    system["start_unsafe_inventory"]
                    < int(
                        nearest_rank(
                            positive_inventory,
                            design.primary_high_demand_quantile,
                        )
                    )
                ).sum()
            ),
            "category_b_plausibly_high_demand_hours": int(len(primary)),
            "category_c_demand_slack_hours": primary_slack,
            "category_d_saturation_supported": bool(
                stable_upper_clustering
                and threshold_robust
                and bootstrap_narrow
            ),
        },
        "active_liquidator_evidence": _active_liquidator_evidence(primary),
        "physical_maximum_claim": False,
        "interpretation": (
            "Observed upper-tail execution sensitivities under identified "
            "unsafe demand; not a physical keeper-network maximum."
        ),
    }
    for row in rows:
        if row["row_type"] == "frontier":
            row["classification"] = classification
    return pd.DataFrame(rows), decision


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    result = numerator / denominator.replace(0, np.nan)
    return result.replace([np.inf, -np.inf], np.nan)


def build_profit_opportunities() -> pd.DataFrame:
    """Build one row per successful model-mappable Take opportunity."""
    actions = pd.read_csv(LIQUIDATION_ACTIONS, low_memory=False)
    actions = actions[actions["record_type"].eq("take_event")].copy()
    actions["tx_hash_normalised"] = actions["tx_hash"].str.lower()
    actions["auction_take_event_count"] = actions.groupby(
        ["clipper_contract", "auction_id"]
    )["record_type"].transform("size")
    gas = pd.read_csv(LIQUIDATION_GAS)
    gas["tx_hash_normalised"] = gas["tx_hash"].str.lower()
    protocol = pd.read_csv(PROTOCOL_HOURLY, low_memory=False)
    protocol["timestamp_hour"] = pd.to_datetime(
        protocol["timestamp_utc"], utc=True
    )

    selected_action = [
        "chunk_id",
        "clipper_contract",
        "auction_id",
        "ilk",
        "urn",
        "tx_hash",
        "tx_hash_normalised",
        "block_time",
        "block_number",
        "transaction_index",
        "event_index",
        "who",
        "usr",
        "owe_dai",
        "price_dai_per_collateral",
        "remaining_tab_dai",
        "remaining_lot_wad",
        "auction_take_event_count",
    ]
    selected_gas = [
        "tx_hash_normalised",
        "take_transaction_class",
        "semantic_action_count",
        "take_event_count",
        "other_event_count",
        "unique_auctions",
        "success",
        "gas_used",
        "effective_gas_price_gwei",
        "transaction_gas_cost_eth",
        "transaction_gas_cost_usd",
        "is_calibration",
        "is_validation",
        "regime",
    ]
    frame = actions[selected_action].merge(
        gas[selected_gas],
        on="tx_hash_normalised",
        how="left",
        validate="many_to_one",
    )
    frame["timestamp_hour"] = pd.to_datetime(
        frame["block_time"], utc=True
    ).dt.floor("h")
    frame = frame.merge(
        protocol[
            ["timestamp_hour", "ilk", "liquidation_penalty_rate"]
        ],
        on=["timestamp_hour", "ilk"],
        how="left",
        validate="many_to_one",
    )
    market = pd.read_csv(
        MARKET_GAS_HOURLY,
        usecols=[
            "timestamp_utc",
            "eth_price_usd",
            "wbtc_price_usd",
            "eth_log_return",
            "wbtc_log_return",
            "target_normalised_block_utilisation",
        ],
    )
    market["timestamp_hour"] = pd.to_datetime(
        market["timestamp_utc"], utc=True
    )
    market["eth_realised_volatility_24h"] = market[
        "eth_log_return"
    ].rolling(24, min_periods=24).std(ddof=0)
    market["wbtc_realised_volatility_24h"] = market[
        "wbtc_log_return"
    ].rolling(24, min_periods=24).std(ddof=0)
    frame = frame.merge(
        market[
            [
                "timestamp_hour",
                "eth_price_usd",
                "wbtc_price_usd",
                "eth_realised_volatility_24h",
                "wbtc_realised_volatility_24h",
                "target_normalised_block_utilisation",
            ]
        ],
        on="timestamp_hour",
        how="left",
        validate="many_to_one",
    )
    frame["debt_repaid_dai"] = pd.to_numeric(
        frame["owe_dai"], errors="coerce"
    )
    frame["gross_reward_dai"] = (
        frame["debt_repaid_dai"] * frame["liquidation_penalty_rate"]
    )
    frame["collateral_bought_wad"] = _safe_divide(
        frame["debt_repaid_dai"], frame["price_dai_per_collateral"]
    )
    frame["collateral_market_price_usd"] = np.where(
        frame["ilk"].str.startswith("ETH-"),
        frame["eth_price_usd"],
        frame["wbtc_price_usd"],
    )
    frame["realised_volatility_24h"] = np.where(
        frame["ilk"].str.startswith("ETH-"),
        frame["eth_realised_volatility_24h"],
        frame["wbtc_realised_volatility_24h"],
    )
    frame["liquidity_proxy"] = np.nan
    frame["liquidity_proxy_quality"] = "unavailable_in_local_evidence"
    frame["direct_profit_dai"] = (
        frame["gross_reward_dai"] - frame["transaction_gas_cost_usd"]
    )
    frame["direct_profit_margin"] = _safe_divide(
        frame["direct_profit_dai"], frame["debt_repaid_dai"]
    )
    frame["gas_share_of_gross_reward"] = _safe_divide(
        frame["transaction_gas_cost_usd"], frame["gross_reward_dai"]
    )
    frame["debt_to_gas_cost_turnover"] = _safe_divide(
        frame["debt_repaid_dai"], frame["transaction_gas_cost_usd"]
    )
    frame["zero_gas_cost_observation"] = frame[
        "transaction_gas_cost_usd"
    ].eq(0)
    frame["model_mappable"] = (
        frame["take_transaction_class"].eq(
            "clean_single_take_single_auction"
        )
        & frame["auction_take_event_count"].eq(1)
        & frame["success"].eq(True)
        & frame["debt_repaid_dai"].gt(0)
        & frame["transaction_gas_cost_usd"].notna()
        & frame["liquidation_penalty_rate"].notna()
    )
    timestamps = frame["timestamp_hour"]
    frame["excluded_usdc_svb"] = timestamps.between(
        USDC_SVB_START, USDC_SVB_END, inclusive="left"
    )
    frame["estimation_eligible"] = (
        frame["model_mappable"]
        & frame["is_calibration"].eq(True)
        & frame["is_validation"].eq(False)
        & ~frame["excluded_usdc_svb"]
    )
    frame["genuinely_negative_or_rejected_evidence"] = False
    frame["economic_interpretation"] = (
        "current_model_direct_cost_proxy_not_realised_keeper_profit"
    )
    frame = frame[
        frame["is_calibration"].eq(True)
        & frame["is_validation"].eq(False)
        & ~frame["excluded_usdc_svb"]
    ].copy()
    frame = frame.sort_values(
        [
            "timestamp_hour",
            "block_number",
            "transaction_index",
            "event_index",
            "tx_hash_normalised",
        ],
        kind="stable",
    ).reset_index(drop=True)
    if frame.duplicated(
        ["clipper_contract", "auction_id", "tx_hash_normalised", "event_index"]
    ).any():
        raise ValueError("Profit-opportunity source keys are not unique.")
    return frame


def _summary_quantiles(values: pd.Series) -> dict[str, float]:
    return {
        name: nearest_rank(values, probability)
        for name, probability in (
            ("minimum", 0.0),
            ("p05", 0.05),
            ("p10", 0.10),
            ("p25", 0.25),
            ("median", 0.50),
        )
    }


def estimate_profit_hurdle(
    opportunities: pd.DataFrame,
    design: KeeperExecutionDesign,
) -> dict[str, Any]:
    """Classify the hurdle evidence and derive candidate-only sensitivities."""
    eligible = opportunities[opportunities["estimation_eligible"]].copy()
    positive_count = int((eligible["direct_profit_dai"] > 0).sum())
    proxy_negative_count = int((eligible["direct_profit_dai"] <= 0).sum())
    genuine_negative_count = int(
        eligible["genuinely_negative_or_rejected_evidence"].sum()
    )
    if (
        positive_count
        >= design.minimum_positive_profit_observations_level1
        and genuine_negative_count
        >= design.minimum_negative_profit_observations_level1
    ):
        classification = "profit_hurdle_estimated"
    elif len(eligible) >= design.minimum_positive_profit_observations_level1:
        classification = "profit_hurdle_partially_identified"
    elif len(eligible) > 0:
        classification = "profit_hurdle_not_identified"
    else:
        classification = "profit_hurdle_calibration_invalid"
    direct_profit = _summary_quantiles(eligible["direct_profit_dai"])
    direct_margin = _summary_quantiles(eligible["direct_profit_margin"])
    gas_share = _summary_quantiles(eligible["gas_share_of_gross_reward"])
    turnover = _summary_quantiles(
        eligible["debt_to_gas_cost_turnover"].dropna()
    )
    profiles = {
        "direct_cost_only": 0.0,
        "keeper_hurdle_low": max(0.0, direct_margin["p05"]),
        "keeper_hurdle_high": max(0.0, direct_margin["p25"]),
    }
    return {
        "classification": classification,
        "eligible_successful_opportunities": int(len(eligible)),
        "positive_direct_profit_proxy_count": positive_count,
        "negative_direct_profit_proxy_count": proxy_negative_count,
        "genuinely_negative_or_rejected_evidence_count": genuine_negative_count,
        "failed_take_call_count_not_negative_choice_evidence": 733,
        "direct_profit_dai": direct_profit,
        "direct_profit_margin": direct_margin,
        "gas_share_of_gross_reward": gas_share,
        "debt_to_gas_cost_turnover": turnover,
        "risk_cost_rate_profiles": profiles,
        "mapping": (
            "risk_cost_rate is the only present proportional keeper hurdle; "
            "p05 and p25 direct-margin profiles are revealed lower-bound "
            "sensitivities, not estimated rejection thresholds."
        ),
        "direct_cost_only_hurdle": 0.0,
        "threshold_non_negative_explanation": (
            "The observations are successful executions. A negative realised "
            "direct-cost proxy does not reveal a pre-trade rejection threshold, "
            "so candidate hurdle support is constrained to non-negative rates."
        ),
    }


def profit_hurdle_summary(
    opportunities: pd.DataFrame,
    hurdle: dict[str, Any],
) -> pd.DataFrame:
    """Return compact system and collateral diagnostic hurdle summaries."""
    eligible = opportunities[opportunities["estimation_eligible"]].copy()
    eligible["collateral_family"] = eligible["ilk"].map(_collateral_family)
    scopes: list[tuple[str, pd.DataFrame]] = [("SYSTEM_ALL", eligible)]
    scopes.extend(
        (f"FAMILY_{family}", group)
        for family, group in eligible.groupby("collateral_family", sort=True)
    )
    scopes.extend(
        (ilk, group) for ilk, group in eligible.groupby("ilk", sort=True)
    )
    rows: list[dict[str, Any]] = []
    for scope, group in scopes:
        profit = _summary_quantiles(group["direct_profit_dai"])
        margin = _summary_quantiles(group["direct_profit_margin"])
        system = scope == "SYSTEM_ALL"
        rows.append(
            {
                "scope": scope,
                "identification_level": (
                    "level_2_successful_execution_only"
                    if system
                    else "collateral_diagnostic_successful_only"
                ),
                "observation_count": int(len(group)),
                "positive_participation_count": int(
                    (group["direct_profit_dai"] > 0).sum()
                ),
                "negative_participation_count": 0,
                "nonpositive_profit_proxy_count": int(
                    (group["direct_profit_dai"] <= 0).sum()
                ),
                **{
                    f"direct_profit_{name}": value
                    for name, value in profit.items()
                },
                **{
                    f"direct_margin_{name}": value
                    for name, value in margin.items()
                },
                "model_coefficients": "",
                "direct_cost_only": (
                    hurdle["risk_cost_rate_profiles"]["direct_cost_only"]
                    if system
                    else np.nan
                ),
                "keeper_hurdle_low": (
                    hurdle["risk_cost_rate_profiles"]["keeper_hurdle_low"]
                    if system
                    else np.nan
                ),
                "keeper_hurdle_high": (
                    hurdle["risk_cost_rate_profiles"]["keeper_hurdle_high"]
                    if system
                    else np.nan
                ),
                "uncertainty": (
                    "successful executions bound acceptance only; no "
                    "defensible rejected executable opportunities"
                ),
                "classification": (
                    hurdle["classification"] if system else "diagnostic_only"
                ),
            }
        )
    return pd.DataFrame(rows)


def hourly_panel_summary(panel: pd.DataFrame) -> pd.DataFrame:
    """Return compact coverage and execution summaries by window and scope."""
    rows: list[dict[str, Any]] = []
    source_checksum = sha256_file(TERRA_STRESS) + ":" + sha256_file(
        LIQUIDATION_HOURLY
    )

    def add_row(
        sample_identifier: str,
        scope: str,
        group: pd.DataFrame,
    ) -> None:
        closure = _distribution_summary(
            group["successful_protocol_closures"]
        )
        debt = _distribution_summary(group["completed_debt_dai"])
        liquidators = _distribution_summary(
            group["unique_liquidator_count"]
        )
        positive_inventory = group[group["start_unsafe_inventory"] > 0]
        threshold = (
            nearest_rank(
                positive_inventory["start_unsafe_inventory"], 0.75
            )
            if not positive_inventory.empty
            else None
        )
        high = (
            group[group["start_unsafe_inventory"] >= threshold]
            if threshold is not None
            else group.iloc[0:0]
        )
        rows.append(
            {
                "sample_identifier": sample_identifier,
                "collateral_scope": scope,
                "observation_count": int(len(group)),
                "positive_inventory_hours": int(len(positive_inventory)),
                "high_demand_hours": int(len(high)),
                "demand_slack_hours": int(
                    (
                        high["successful_protocol_closures"]
                        < high["start_unsafe_inventory"]
                    ).sum()
                ),
                **{
                    f"closure_{name}": value
                    for name, value in closure.items()
                },
                **{
                    f"debt_throughput_{name}": value
                    for name, value in debt.items()
                },
                **{
                    f"active_liquidator_{name}": value
                    for name, value in liquidators.items()
                },
                "missing_newly_unsafe_share": float(
                    group["newly_unsafe_inventory"].isna().mean()
                ),
                "missing_gas_cost_share": float(
                    group["median_gas_cost_dai"].isna().mean()
                ),
                "source_checksum": source_checksum,
            }
        )

    for (window, ilk), group in panel.groupby(
        ["source_window", "ilk"], sort=True
    ):
        add_row(
            f"window={window};scope={ilk}",
            ilk,
            group,
        )
    system = panel[panel["is_system_aggregate"]]
    positive = system[system["start_unsafe_inventory"] > 0]
    threshold = nearest_rank(positive["start_unsafe_inventory"], 0.75)
    high = system[system["start_unsafe_inventory"] >= threshold]
    for group_name, group in high.groupby("composition_group", sort=True):
        add_row(f"primary_high_demand;composition={group_name}", SYSTEM_SCOPE, group)
    for stress, group in high.groupby("execution_stress", sort=True):
        add_row(
            f"primary_high_demand;execution_stress={str(bool(stress)).lower()}",
            SYSTEM_SCOPE,
            group,
        )
    return pd.DataFrame(rows)


def _overall_classification(
    capacity: str, hurdle: str
) -> str:
    if (
        capacity == "shared_keeper_capacity_calibration_invalid"
        or hurdle == "profit_hurdle_calibration_invalid"
    ):
        return "shared_keeper_execution_calibration_invalid"
    if capacity == "shared_capacity_not_identified_use_sensitivity":
        return "shared_keeper_execution_calibration_blocked"
    if hurdle == "profit_hurdle_not_identified":
        return (
            "shared_keeper_execution_registry_ready_with_sensitivity_only_hurdle"
        )
    if (
        capacity == "shared_capacity_partially_identified"
        or hurdle == "profit_hurdle_partially_identified"
    ):
        return (
            "shared_keeper_execution_registry_ready_with_partial_identification"
        )
    return "shared_keeper_execution_registry_ready"


def _registry_rows(
    capacity: dict[str, Any],
    hurdle: dict[str, Any],
    *,
    source_checksum: str,
    profitability_equation_checksum: str,
) -> pd.DataFrame:
    pairings = (
        ("low", "keeper_hurdle_low"),
        ("central", "direct_cost_only"),
        ("high", "keeper_hurdle_high"),
    )
    rows: list[dict[str, Any]] = []
    for order, (label, hurdle_id) in enumerate(pairings, start=1):
        row = {
            "order": order,
            "identifier": f"shared_keeper_capacity_{label}",
            "shared_capacity_value": int(capacity["profiles"][label]),
            "capacity_unit": "protocol opportunities per one-hour step",
            "capacity_status": capacity["classification"],
            "composition_status": capacity["composition_classification"],
            "population_mapping": capacity["capacity_scale"],
            "hurdle_identifier": hurdle_id,
            "hurdle_value": float(
                hurdle["risk_cost_rate_profiles"][hurdle_id]
            ),
            "hurdle_unit": "fraction of debt repaid",
            "hurdle_status": hurdle["classification"],
            "intended_use": (
                "opt-in bounded integration and sensitivity validation"
            ),
            "system_wide_status": "shared_across_all_collateral_types",
            "included_collateral_types": "|".join(TARGET_ILKS),
            "source_sample": "terra_cefi|quiet_mature",
            "source_checksum": source_checksum,
            "direct_gas_treatment": "transaction_gas_cost_usd_subtracted",
            "profitability_equation_checksum": (
                profitability_equation_checksum
            ),
            "parameter_source": "empirical_candidate_registry",
            "runtime_adopted": False,
        }
        row["deterministic_row_checksum"] = hashlib.sha256(
            json.dumps(
                row, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        ).hexdigest()
        rows.append(row)
    return pd.DataFrame(rows)


def _write_candidate_config(
    path: Path,
    capacity: dict[str, Any],
    hurdle: dict[str, Any],
    evidence_checksums: dict[str, str],
) -> None:
    payload = {
        "schema_version": 1,
        "candidate_bundle": "system_wide_keeper_execution",
        "runtime_adopted": False,
        "capacity_identification_classification": capacity["classification"],
        "composition_status": capacity["composition_classification"],
        "population_mapping_status": capacity["capacity_scale"],
        "hurdle_identification_status": hurdle["classification"],
        "system_wide_status": "shared_across_all_collateral_types",
        "included_collateral_types": list(TARGET_ILKS),
        "source_sample": ["terra_cefi", "quiet_mature"],
        "capacity_unit": "protocol opportunities per one-hour step",
        "shared_capacity_profiles": {
            f"shared_keeper_capacity_{name}": {
                "maximum_liquidations_per_step": int(value),
                "shared_across_collateral": True,
                "physical_maximum_claim": False,
            }
            for name, value in capacity["profiles"].items()
        },
        "profit_hurdle_profiles": {
            "direct_cost_only": {
                "risk_cost_rate": float(
                    hurdle["risk_cost_rate_profiles"]["direct_cost_only"]
                ),
                "interpretation": "current direct-cost-only model",
            },
            "keeper_hurdle_low": {
                "risk_cost_rate": float(
                    hurdle["risk_cost_rate_profiles"]["keeper_hurdle_low"]
                ),
                "interpretation": (
                    "successful-execution p05 revealed lower-bound sensitivity"
                ),
            },
            "keeper_hurdle_high": {
                "risk_cost_rate": float(
                    hurdle["risk_cost_rate_profiles"]["keeper_hurdle_high"]
                ),
                "interpretation": (
                    "successful-execution p25 conservative sensitivity"
                ),
            },
        },
        "source_evidence_checksums": evidence_checksums,
        "direct_gas_treatment": "transaction_gas_cost_usd_subtracted",
        "profitability_equation_checksum": sha256_file(
            MODEL_LIQUIDATION_SOURCE
        ),
        "parameter_source": "empirical_candidate_registry",
        "activation": "explicit opt-in resolver only",
    }
    _atomic_text(
        path,
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
    )


def mixed_collateral_smoke(
    capacity: int, risk_cost_rate: float
) -> dict[str, Any]:
    """Exercise global ordering, capacity and hurdle semantics without adoption."""
    prices = {"ETH": 10.0, "BTC": 10.0}
    vaults = [
        Vault(
            index,
            index,
            1.0,
            1_000.0 - index,
            1.5,
            "ETH" if index % 2 else "BTC",
        )
        for index in range(1, capacity + 3)
    ]
    config = LiquidationConfig(
        liquidation_penalty=0.13,
        gas_cost=1.0,
        risk_cost_rate=risk_cost_rate,
        max_close_factor=1.0,
        max_liquidations_per_step=capacity,
    )
    result = liquidate_vaults(
        vaults,
        prices,
        config,
        bounded_demand=len(vaults),
        attempt_budget=capacity,
    )
    executed = result[result["liquidated"]]
    limited = result[result["reason"].eq("capacity_limited")]
    allocation = {
        str(collateral): int(count)
        for collateral, count in executed["collateral_type"]
        .value_counts()
        .sort_index()
        .items()
    }

    hurdle_vaults = [
        Vault(11, 11, 1.0, 100.0, 1.5, "ETH"),
        Vault(12, 12, 1.0, 1_000.0, 1.5, "BTC"),
    ]
    hurdle_prices = {"ETH": 100.0, "BTC": 100.0}
    hurdle_result = liquidate_vaults(
        hurdle_vaults,
        hurdle_prices,
        LiquidationConfig(
            liquidation_penalty=0.13,
            gas_cost=5.0,
            risk_cost_rate=0.10,
            max_close_factor=1.0,
            max_liquidations_per_step=None,
        ),
    )
    return {
        "capacity_used_for_smoke": capacity,
        "executed_vault_ids": executed["vault_id"].astype(int).tolist(),
        "executed_collateral_types": executed["collateral_type"].tolist(),
        "capacity_limited_vault_ids": limited["vault_id"].astype(int).tolist(),
        "global_executed_count": int(len(executed)),
        "global_capacity_respected": int(len(executed)) <= capacity,
        "capacity_not_duplicated_by_collateral": int(len(executed)) == capacity,
        "collateral_allocation": allocation,
        "cross_collateral_ranking_observed": (
            len(set(executed["collateral_type"])) == 2
        ),
        "hurdle_reasons": {
            str(int(row.vault_id)): row.reason
            for row in hurdle_result.itertuples()
        },
        "unresolved_opportunities_preserved": int(len(limited)),
        "legacy_absent_registry_boundary": (
            "ordinary simulation code never imports or resolves the candidate registry"
        ),
    }


def _manifest_record(path: Path, source_inputs: list[str]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "classification": "snapshot",
        "context": (
            "Compact pre-registered keeper-execution calibration evidence; "
            "candidate-only and not runtime adopted."
        ),
        "path": _relative(path),
        "producer": "dai_sim.calibration.keeper_execution",
        "schema": (
            "Deterministic compact keeper capacity/profit-hurdle evidence."
        ),
        "semantic_name": f"keeper_execution_{path.stem}",
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "source_inputs": source_inputs,
    }
    if path.suffix == ".csv":
        frame = pd.read_csv(path)
        record["dimensions"] = [len(frame), len(frame.columns)]
    return record


def update_calibration_manifest(evidence_dir: Path) -> None:
    """Replace the keeper records in the tracked calibration manifest."""
    payload = json.loads(CALIBRATION_MANIFEST.read_text(encoding="utf-8"))
    prefix = _relative(evidence_dir) + "/"
    payload["artefacts"] = [
        record
        for record in payload["artefacts"]
        if not record["path"].startswith(prefix)
    ]
    source_inputs = sorted(_relative(path) for path in _source_paths().values())
    payload["artefacts"].extend(
        _manifest_record(evidence_dir / name, source_inputs)
        for name in COMPACT_ARTEFACTS
    )
    payload["artefacts"] = sorted(
        payload["artefacts"], key=lambda record: record["path"]
    )
    _write_json(CALIBRATION_MANIFEST, payload)


def _validate_output_budgets(
    evidence_dir: Path, diagnostic_dir: Path, design: KeeperExecutionDesign
) -> dict[str, int]:
    evidence_sizes = {
        path.name: path.stat().st_size
        for path in evidence_dir.iterdir()
        if path.is_file()
    }
    oversized = {
        name: size
        for name, size in evidence_sizes.items()
        if size > design.maximum_compact_file_bytes
    }
    if oversized:
        raise ValueError(f"Compact evidence files exceed 25 MiB: {oversized}")
    diagnostic_bytes = sum(
        path.stat().st_size
        for path in diagnostic_dir.rglob("*")
        if path.is_file()
    )
    total_bytes = sum(evidence_sizes.values()) + diagnostic_bytes
    if diagnostic_bytes > design.maximum_diagnostic_bytes:
        raise ValueError("Detailed keeper diagnostics exceed 250 MiB.")
    if total_bytes > design.maximum_total_output_bytes:
        raise ValueError("Keeper calibration outputs exceed 10 GiB.")
    return {
        "compact_bytes": sum(evidence_sizes.values()),
        "diagnostic_bytes": diagnostic_bytes,
        "total_bytes": total_bytes,
    }


def run_keeper_execution_calibration(
    *,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    diagnostic_root: Path = DEFAULT_DIAGNOSTIC_ROOT,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    design: KeeperExecutionDesign = KeeperExecutionDesign(),
) -> dict[str, Any]:
    """Run the pre-registered, local-only keeper execution calibration."""
    prereg_path = write_preregistration(diagnostic_root, design)
    specification = preregistration_payload(design)
    identity = scientific_identity(specification)
    diagnostic_dir = diagnostic_root / identity
    if json.loads(prereg_path.read_text(encoding="utf-8")) != specification:
        raise ValueError("Pre-registration checksum gate failed.")

    panel, thresholds = build_hourly_panel()
    frontier, capacity = estimate_capacity(panel, design)
    opportunities = build_profit_opportunities()
    hurdle = estimate_profit_hurdle(opportunities, design)
    overall = _overall_classification(
        capacity["classification"], hurdle["classification"]
    )
    if overall in {
        "shared_keeper_execution_calibration_blocked",
        "shared_keeper_execution_calibration_invalid",
    }:
        raise ValueError(
            f"Keeper execution calibration cannot produce a registry: {overall}"
        )

    evidence_dir.mkdir(parents=True, exist_ok=True)
    specification_path = (
        evidence_dir / "keeper_execution_specification.json"
    )
    _write_json(specification_path, specification)
    _write_csv(
        evidence_dir / "keeper_collateral_comparability.csv",
        collateral_comparability(),
    )
    _write_csv(
        evidence_dir / "keeper_hourly_panel_summary.csv",
        hourly_panel_summary(panel),
    )
    _write_csv(
        evidence_dir / "keeper_capacity_frontier.csv",
        frontier,
    )
    profit_columns = [
        "timestamp_hour",
        "clipper_contract",
        "auction_id",
        "ilk",
        "urn",
        "tx_hash_normalised",
        "block_number",
        "transaction_index",
        "event_index",
        "who",
        "usr",
        "take_transaction_class",
        "auction_take_event_count",
        "semantic_action_count",
        "unique_auctions",
        "gas_used",
        "effective_gas_price_gwei",
        "transaction_gas_cost_eth",
        "transaction_gas_cost_usd",
        "debt_repaid_dai",
        "collateral_bought_wad",
        "collateral_market_price_usd",
        "price_dai_per_collateral",
        "liquidation_penalty_rate",
        "gross_reward_dai",
        "direct_profit_dai",
        "direct_profit_margin",
        "gas_share_of_gross_reward",
        "debt_to_gas_cost_turnover",
        "realised_volatility_24h",
        "target_normalised_block_utilisation",
        "liquidity_proxy",
        "liquidity_proxy_quality",
        "zero_gas_cost_observation",
        "model_mappable",
        "is_calibration",
        "is_validation",
        "excluded_usdc_svb",
        "estimation_eligible",
        "genuinely_negative_or_rejected_evidence",
        "economic_interpretation",
    ]
    _write_csv(
        diagnostic_dir / "keeper_profit_opportunities.csv",
        opportunities[profit_columns],
    )
    _write_csv(
        evidence_dir / "keeper_profit_hurdle.csv",
        profit_hurdle_summary(opportunities, hurdle),
    )
    registry = _registry_rows(
        capacity,
        hurdle,
        source_checksum=sha256_file(specification_path),
        profitability_equation_checksum=sha256_file(
            MODEL_LIQUIDATION_SOURCE
        ),
    )
    _write_csv(
        evidence_dir / "keeper_execution_registry.csv",
        registry,
    )
    decision = {
        "study": "system_wide_keeper_execution_calibration",
        "capacity": capacity,
        "profit_hurdle": hurdle,
        "composition_classification": capacity[
            "composition_classification"
        ],
        "overall_classification": overall,
        "candidate_registry_written": True,
        "runtime_adopted": False,
        "default_profiles_changed": False,
        "final_validation_used": False,
        "usdc_svb_used_for_estimation": False,
        "no_physical_maximum_claim": True,
        "no_collateral_specific_independent_caps": True,
        "liquidation_demand_used_as_capacity": False,
        "eth_only_validation_boundary": (
            "apply the same system-wide count registry as an explicit "
            "validation harness; do not recalibrate it to ETH"
        ),
        "multi_collateral_shared_capacity_boundary": (
            "all collateral opportunities enter one global ranking and "
            "their combined selected count must not exceed the resolved cap"
        ),
        "final_experiment_run": False,
        "next_boundary": (
            "An integrated ETH-only empirical profile may be run separately "
            "with 500 vaults, empirical market/gas/arrival inputs, the central "
            "system cap, the registered hurdle and accepted Stage 1 response/"
            "confidence settings. It is not run here."
        ),
    }
    _write_json(
        evidence_dir / "keeper_execution_decision.json",
        decision,
    )
    smoke = {
        label: mixed_collateral_smoke(
            value,
            hurdle["risk_cost_rate_profiles"]["direct_cost_only"],
        )
        for label, value in capacity["profiles"].items()
    }
    _write_csv(diagnostic_dir / "keeper_hourly_panel.csv", panel)
    _write_csv(
        diagnostic_dir / "keeper_system_hourly_panel.csv",
        panel[panel["is_system_aggregate"]].copy(),
    )
    _write_csv(
        diagnostic_dir / "keeper_collateral_hourly_panel.csv",
        panel[~panel["is_system_aggregate"]].copy(),
    )
    _write_json(diagnostic_dir / "mixed_collateral_smoke.json", smoke)
    _write_json(
        diagnostic_dir / "saturation_diagnostics.json",
        {
            key: capacity[key]
            for key in (
                "stable_upper_clustering",
                "repeated_upper_value_max_frequency",
                "threshold_p90_values",
                "threshold_robust",
                "primary_p90_day_block_bootstrap_width",
                "bootstrap_uncertainty_narrow",
                "demand_categories",
            )
        },
    )

    preliminary_checksums = {
        name: sha256_file(evidence_dir / name)
        for name in COMPACT_ARTEFACTS[:7]
    }
    _write_candidate_config(
        registry_path, capacity, hurdle, preliminary_checksums
    )
    current_output_bytes = sum(
        path.stat().st_size
        for path in evidence_dir.iterdir()
        if path.is_file()
        and path.name
        not in {
            "keeper_execution_benchmark.json",
            "keeper_execution_reproducibility.json",
        }
    )
    benchmark = {
        "scientific_identity": identity,
        "workload": {
            "hourly_panel_rows": int(len(panel)),
            "frontier_rows": int(len(frontier)),
            "profit_opportunity_rows": int(len(opportunities)),
            "bootstrap_replications_per_interval": (
                design.bootstrap_replications
            ),
            "bootstrap_interval_count": int(
                frontier["row_type"].eq("frontier").sum() * 6
            ),
        },
        "input_size_bytes": int(
            sum(path.stat().st_size for path in _source_paths().values())
        ),
        "runtime_seconds": None,
        "peak_memory_bytes": None,
        "ignored_diagnostic_size_bytes": int(
            sum(
                path.stat().st_size
                for path in diagnostic_dir.rglob("*")
                if path.is_file()
            )
        ),
        "output_size_bytes_excluding_benchmark_and_reproducibility": int(
            current_output_bytes
        ),
        "host_dependent_status": (
            "runtime and memory excluded from deterministic compact evidence"
        ),
        "execution_mode": "local_deterministic_single_process",
        "network_access": False,
        "live_acquisition_calls": 0,
        "simulation_experiment_run": False,
        "figures_generated": 0,
    }
    _write_json(
        evidence_dir / "keeper_execution_benchmark.json",
        benchmark,
    )
    reproducibility = {
        "scientific_identity": identity,
        "preregistration_path": _relative(prereg_path),
        "preregistration_sha256": sha256_file(prereg_path),
        "source_checksums": source_checksums(),
        "panel_identity": sha256_file(
            diagnostic_dir / "keeper_hourly_panel.csv"
        ),
        "aggregation_checksum": sha256_file(
            diagnostic_dir / "keeper_system_hourly_panel.csv"
        ),
        "included_collateral_types": list(TARGET_ILKS),
        "excluded_collateral_types": ["OTHER_MAKER_COLLATERAL"],
        "quantile_convention": "integer nearest-rank",
        "bootstrap_seed_identity": hashlib.sha256(
            f"{design.random_seed}:{design.bootstrap_replications}:day".encode(
                "utf-8"
            )
        ).hexdigest(),
        "evidence_checksums_excluding_reproducibility": {
            name: sha256_file(evidence_dir / name)
            for name in COMPACT_ARTEFACTS
            if name != "keeper_execution_reproducibility.json"
        },
        "registry_config_path": _relative(registry_path),
        "registry_config_sha256": sha256_file(registry_path),
        "random_seed": design.random_seed,
        "bootstrap_replications": design.bootstrap_replications,
        "deterministic_serialisation": True,
        "runtime_adopted": False,
        "network_access": False,
        "live_acquisition_calls": 0,
        "final_validation_used": False,
        "usdc_svb_used_for_estimation": False,
        "detailed_outputs_ignored": True,
    }
    _write_json(
        evidence_dir / "keeper_execution_reproducibility.json",
        reproducibility,
    )
    # The benchmark precedes reproducibility in the compact tuple, but its
    # creation does not depend on any result checksum and is deterministic.
    update_calibration_manifest(evidence_dir)
    budgets = _validate_output_budgets(
        evidence_dir, diagnostic_dir, design
    )
    return {
        "scientific_identity": identity,
        "preregistration_path": _relative(prereg_path),
        "evidence_dir": _relative(evidence_dir),
        "diagnostic_dir": _relative(diagnostic_dir),
        "registry_path": _relative(registry_path),
        "capacity_classification": capacity["classification"],
        "composition_classification": capacity[
            "composition_classification"
        ],
        "hurdle_classification": hurdle["classification"],
        "overall_classification": overall,
        "capacity_profiles": capacity["profiles"],
        "hurdle_profiles": hurdle["risk_cost_rate_profiles"],
        "thresholds": thresholds,
        "panel_rows": len(panel),
        "profit_opportunity_rows": len(opportunities),
        "smoke": smoke,
        "output_budgets": budgets,
    }
