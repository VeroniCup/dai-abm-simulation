"""
Explicit Tranche C empirical environment-input configuration and generation.

This module stitches together the opt-in Tranche B vault initialiser, Tranche C
market blocks and Tranche C gas inputs. It does not alter simulator defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

import yaml

from empirical_config import REPOSITORY_ROOT, sha256_file
from gas_process import (
    GasProcessConfig,
    GasProcessResult,
    component_gas_costs,
    legacy_scalar_gas,
    sample_total_gas_costs,
)
from market_bootstrap import (
    MarketBootstrapResult,
    MarketProcessConfig,
    generate_empirical_price_paths,
)
from vault_initialisation import (
    TrancheBConfigurationBundle,
    load_tranche_b_configuration,
    initialise_vaults,
)


DEFAULT_TRANCHE_C_CONFIG_PATH = (
    REPOSITORY_ROOT / "config" / "empirical" / "phase2_empirical_market_gas.yaml"
)


@dataclass(frozen=True)
class TrancheCConfigurationBundle:
    """Loaded opt-in Tranche C configuration."""

    bundle_name: str
    config_path: Path
    config_sha256: str
    tranche_b_bundle: TrancheBConfigurationBundle
    market_process: MarketProcessConfig
    gas_process: GasProcessConfig


@dataclass(frozen=True)
class EnvironmentInputResult:
    """Generated external inputs and provenance for one Tranche C run."""

    price_paths: dict[str, Any]
    gas_cost_path: Any
    initial_vaults: Any
    market: MarketBootstrapResult | None
    gas: GasProcessResult
    provenance: dict[str, Any]


def _root_path(value: str | None) -> Path | None:
    if value is None:
        return None
    return REPOSITORY_ROOT / value


def _parse_market(raw: dict[str, Any] | None) -> MarketProcessConfig:
    if raw is None:
        config = MarketProcessConfig()
        config.validate()
        return config
    allowed = {
        "mode",
        "pool_path",
        "pool_sha256",
        "pool_label",
        "block_length_hours",
        "seed",
        "return_type",
        "alignment_mode",
        "withheld_period_policy",
        "shock_overlay_enabled",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown market_process keys: {sorted(unknown)}.")
    config = MarketProcessConfig(
        mode=str(raw.get("mode", "legacy_gbm")),
        pool_path=_root_path(raw.get("pool_path")),
        pool_sha256=raw.get("pool_sha256"),
        pool_label=str(raw.get("pool_label", "all_calibration")),
        block_length_hours=int(raw.get("block_length_hours", 168)),
        seed=None if raw.get("seed") is None else int(raw["seed"]),
        return_type=str(raw.get("return_type", "log_return")),
        alignment_mode=str(raw.get("alignment_mode", "shared_market_gas")),
        withheld_period_policy=str(raw.get("withheld_period_policy", "exclude_ftx")),
        shock_overlay_enabled=bool(raw.get("shock_overlay_enabled", False)),
    )
    config.validate()
    return config


def _parse_gas(raw: dict[str, Any] | None) -> GasProcessConfig:
    if raw is None:
        config = GasProcessConfig()
        config.validate()
        return config
    allowed = {
        "mode",
        "pool_path",
        "pool_sha256",
        "seed",
        "alignment_mode",
        "zero_observation_policy",
        "event_type",
        "cost_currency",
        "network_gas_column",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown gas_process keys: {sorted(unknown)}.")
    config = GasProcessConfig(
        mode=str(raw.get("mode", "legacy_scalar")),
        pool_path=_root_path(raw.get("pool_path")),
        pool_sha256=raw.get("pool_sha256"),
        seed=None if raw.get("seed") is None else int(raw["seed"]),
        alignment_mode=str(raw.get("alignment_mode", "shared_market_gas")),
        zero_observation_policy=str(raw.get("zero_observation_policy", "exclude_zero_primary")),
        event_type=str(raw.get("event_type", "clean_successful_take_transaction")),
        cost_currency=str(raw.get("cost_currency", "USD")),
        network_gas_column=str(raw.get("network_gas_column", "median_effective_gas_price_gwei")),
    )
    config.validate()
    return config


def load_tranche_c_configuration(
    path: Path | str = DEFAULT_TRANCHE_C_CONFIG_PATH,
) -> TrancheCConfigurationBundle:
    """Load and validate the explicit Tranche C configuration."""
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Tranche C configuration must be a mapping.")
    if raw.get("mode") != "empirical_tranche_c":
        raise ValueError("Tranche C mode must be empirical_tranche_c.")

    base_payload = dict(raw)
    base_payload["mode"] = "empirical_tranche_b"
    base_payload.pop("market_process", None)
    base_payload.pop("gas_process", None)
    temporary = config_path.with_suffix(".base_for_validation.yaml")
    try:
        temporary.write_text(yaml.safe_dump(base_payload, sort_keys=False), encoding="utf-8")
        tranche_b_bundle = load_tranche_b_configuration(temporary)
    finally:
        if temporary.exists():
            temporary.unlink()

    return TrancheCConfigurationBundle(
        bundle_name=str(raw["bundle_name"]),
        config_path=config_path,
        config_sha256=sha256_file(config_path),
        tranche_b_bundle=tranche_b_bundle,
        market_process=_parse_market(raw.get("market_process")),
        gas_process=_parse_gas(raw.get("gas_process")),
    )


def generate_environment_inputs(
    bundle: TrancheCConfigurationBundle,
) -> EnvironmentInputResult:
    """Generate explicit Tranche C price, gas and initial-vault inputs."""
    simulation_config = bundle.tranche_b_bundle.base_bundle.simulation_config
    vault_result = initialise_vaults(
        simulation_config,
        bundle.tranche_b_bundle.initialisation,
    )

    if bundle.market_process.mode == "legacy_gbm":
        raise ValueError("Tranche C environment generation requires empirical market blocks.")

    initial_prices = simulation_config.collateral_portfolio.initial_prices
    market_result = generate_empirical_price_paths(
        n_steps=simulation_config.n_steps,
        initial_prices=initial_prices,
        config=bundle.market_process,
    )

    if bundle.gas_process.mode == "legacy_scalar":
        gas_result = legacy_scalar_gas()
    elif bundle.gas_process.mode == "empirical_total_cost":
        gas_result = sample_total_gas_costs(
            n_steps=simulation_config.n_steps,
            config=bundle.gas_process,
        )
    elif bundle.gas_process.mode == "empirical_components":
        gas_result = component_gas_costs(
            sampled_market_gas_rows=market_result.sampled_rows,
            simulated_eth_prices=market_result.price_paths["ETH"],
            config=bundle.gas_process,
        )
    else:
        raise ValueError(f"Unknown gas process mode: {bundle.gas_process.mode}.")

    provenance = {
        "configuration_path": str(bundle.config_path.relative_to(REPOSITORY_ROOT)),
        "configuration_sha256": bundle.config_sha256,
        "simulation_seed": simulation_config.random_seed,
        "tranche_b_vault_pool_checksum": vault_result.provenance.get("pool_checksum"),
        "vault_initialisation": vault_result.provenance,
        "market": market_result.provenance,
        "gas": gas_result.provenance,
        "legacy_or_empirical_mode": "empirical_tranche_c",
    }
    return EnvironmentInputResult(
        price_paths=market_result.price_paths,
        gas_cost_path=gas_result.gas_cost_usd,
        initial_vaults=vault_result.vaults,
        market=market_result,
        gas=gas_result,
        provenance=provenance,
    )


def write_environment_provenance(provenance: dict[str, Any], path: Path | str) -> None:
    """Write deterministic Tranche C sidecar provenance."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
