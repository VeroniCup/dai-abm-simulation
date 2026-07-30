"""
Explicit Tranche C empirical environment-input configuration and generation.

This module stitches together the opt-in Tranche B vault initialiser, Tranche C
market blocks and Tranche C gas inputs. It does not alter simulator defaults.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import hashlib
import json

from .configuration import (
    REPOSITORY_ROOT,
    load_configuration_payload,
    sha256_file,
)
from .gas import (
    GasProcessConfig,
    GasProcessResult,
    component_gas_costs,
    legacy_scalar_gas,
    sample_total_gas_costs,
)
from .liquidations import (
    DEFAULT_LIQUIDATION_ARRIVAL_POOL_PATH,
    LiquidationDemandConfig,
    LiquidationDemandProcess,
)
from .market import (
    MarketBootstrapResult,
    MarketProcessConfig,
    generate_empirical_price_paths,
)
from .vaults import (
    TrancheBConfigurationBundle,
    load_tranche_b_configuration,
    initialise_vaults,
)


DEFAULT_TRANCHE_C_CONFIG_PATH = (
    REPOSITORY_ROOT / "config" / "profiles" / "empirical.yaml"
)
DEFAULT_TRANCHE_D_CONFIG_PATH = (
    REPOSITORY_ROOT / "config" / "profiles" / "empirical.yaml"
)
VALID_SEMANTIC_PROFILE_MODES = {"legacy", "empirical", "empirical_stress"}


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
class TrancheDConfigurationBundle:
    """Loaded opt-in Tranche D configuration."""

    bundle_name: str
    config_path: Path
    config_sha256: str
    tranche_c_bundle: TrancheCConfigurationBundle
    liquidation_demand: LiquidationDemandConfig


@dataclass(frozen=True)
class EnvironmentInputResult:
    """Generated external inputs and provenance for one Tranche C run."""

    price_paths: dict[str, Any]
    gas_cost_path: Any
    initial_vaults: Any
    market: MarketBootstrapResult | None
    gas: GasProcessResult
    liquidation_demand: LiquidationDemandProcess | None
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


def _parse_liquidation_demand(raw: dict[str, Any] | None) -> LiquidationDemandConfig:
    if raw is None:
        config = LiquidationDemandConfig()
        config.validate()
        return config
    allowed = {
        "mode",
        "pool_path",
        "pool_sha256",
        "seed",
        "hurdle_probability",
        "hurdle_estimator",
        "positive_count_mode",
        "sequence_mode",
        "inventory_conditioning",
        "count_truncation_policy",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown liquidation_demand keys: {sorted(unknown)}.")
    config = LiquidationDemandConfig(
        mode=str(raw.get("mode", "legacy_all_eligible")),
        pool_path=_root_path(raw.get("pool_path")),
        pool_sha256=raw.get("pool_sha256"),
        seed=None if raw.get("seed") is None else int(raw["seed"]),
        hurdle_probability=(
            None
            if raw.get("hurdle_probability") is None
            else float(raw["hurdle_probability"])
        ),
        hurdle_estimator=str(
            raw.get("hurdle_estimator", "conditional_start_inventory_positive")
        ),
        positive_count_mode=str(
            raw.get("positive_count_mode", "empirical_positive_hour_counts")
        ),
        sequence_mode=str(raw.get("sequence_mode", "none")),
        inventory_conditioning=str(
            raw.get("inventory_conditioning", "current_liquidatable_inventory_positive")
        ),
        count_truncation_policy=str(
            raw.get("count_truncation_policy", "truncate_to_inventory_then_capacity")
        ),
    )
    config.validate()
    return config


def load_tranche_c_configuration(
    path: Path | str = DEFAULT_TRANCHE_C_CONFIG_PATH,
    *,
    sensitivity_paths: tuple[Path | str, ...] = (),
) -> TrancheCConfigurationBundle:
    """Load and validate the explicit Tranche C configuration."""
    config_path = Path(path).resolve()
    raw = load_configuration_payload(config_path, sensitivity_paths)
    if not isinstance(raw, dict):
        raise ValueError("Tranche C configuration must be a mapping.")
    if raw.get("mode") not in VALID_SEMANTIC_PROFILE_MODES:
        raise ValueError("Tranche C mode must be a semantic profile mode.")

    tranche_b_bundle = load_tranche_b_configuration(
        config_path,
        sensitivity_paths=sensitivity_paths,
    )

    return TrancheCConfigurationBundle(
        bundle_name=str(raw["bundle_name"]),
        config_path=config_path,
        config_sha256=sha256_file(config_path),
        tranche_b_bundle=tranche_b_bundle,
        market_process=_parse_market(raw.get("market_process")),
        gas_process=_parse_gas(raw.get("gas_process")),
    )


def load_tranche_d_configuration(
    path: Path | str = DEFAULT_TRANCHE_D_CONFIG_PATH,
    *,
    sensitivity_paths: tuple[Path | str, ...] = (),
) -> TrancheDConfigurationBundle:
    """Load a complete profile with optional explicit ordered sensitivities."""
    config_path = Path(path).resolve()
    raw = load_configuration_payload(config_path, sensitivity_paths)
    if not isinstance(raw, dict):
        raise ValueError("Tranche D configuration must be a mapping.")
    if raw.get("mode") not in VALID_SEMANTIC_PROFILE_MODES:
        raise ValueError("Tranche D mode must be a semantic profile mode.")

    tranche_c_bundle = load_tranche_c_configuration(
        config_path,
        sensitivity_paths=sensitivity_paths,
    )

    return TrancheDConfigurationBundle(
        bundle_name=str(raw["bundle_name"]),
        config_path=config_path,
        config_sha256=sha256_file(config_path),
        tranche_c_bundle=tranche_c_bundle,
        liquidation_demand=_parse_liquidation_demand(raw.get("liquidation_demand")),
    )


def load_configuration_profile(
    path: Path | str = DEFAULT_TRANCHE_D_CONFIG_PATH,
    *,
    sensitivity_paths: tuple[Path | str, ...] = (),
) -> TrancheDConfigurationBundle:
    """Load and fully validate one semantic profile and explicit overrides."""
    return load_tranche_d_configuration(
        path,
        sensitivity_paths=sensitivity_paths,
    )


def _canonical_value(value: Any) -> Any:
    """Normalise loaded values for behaviour-only configuration comparison."""
    if isinstance(value, Path):
        return "<repository-relative-path>"
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def configuration_behaviour_payload(
    bundle: TrancheDConfigurationBundle,
) -> dict[str, Any]:
    """Return the complete loaded runtime configuration without path metadata."""
    tranche_c = bundle.tranche_c_bundle
    tranche_b = tranche_c.tranche_b_bundle
    base = tranche_b.base_bundle
    simulation = asdict(base.simulation_config)
    portfolio = simulation.get("collateral_portfolio")
    if isinstance(portfolio, dict):
        portfolio = dict(portfolio)
        portfolio.pop("name", None)
        simulation["collateral_portfolio"] = portfolio
    return _canonical_value(
        {
            "simulation": simulation,
            "liquidation": asdict(base.liquidation_config),
            "confidence": asdict(base.confidence_config),
            "dai_market": asdict(base.dai_market_config),
            "vault_initialisation": asdict(tranche_b.initialisation),
            "market_process": asdict(tranche_c.market_process),
            "gas_process": asdict(tranche_c.gas_process),
            "liquidation_demand": asdict(bundle.liquidation_demand),
        }
    )


def configuration_behaviour_sha256(
    bundle: TrancheDConfigurationBundle,
) -> str:
    """Hash the stable canonical representation of loaded runtime behaviour."""
    encoded = json.dumps(
        configuration_behaviour_payload(bundle),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generate_environment_inputs(
    bundle: TrancheCConfigurationBundle | TrancheDConfigurationBundle,
) -> EnvironmentInputResult:
    """Generate explicit Tranche C price, gas and initial-vault inputs."""
    tranche_c_bundle = bundle.tranche_c_bundle if isinstance(
        bundle,
        TrancheDConfigurationBundle,
    ) else bundle
    simulation_config = tranche_c_bundle.tranche_b_bundle.base_bundle.simulation_config
    vault_result = initialise_vaults(
        simulation_config,
        tranche_c_bundle.tranche_b_bundle.initialisation,
    )

    if tranche_c_bundle.market_process.mode == "legacy_gbm":
        raise ValueError("Tranche C environment generation requires empirical market blocks.")

    initial_prices = simulation_config.collateral_portfolio.initial_prices
    market_result = generate_empirical_price_paths(
        n_steps=simulation_config.n_steps,
        initial_prices=initial_prices,
        config=tranche_c_bundle.market_process,
    )

    if tranche_c_bundle.gas_process.mode == "legacy_scalar":
        gas_result = legacy_scalar_gas()
    elif tranche_c_bundle.gas_process.mode == "empirical_total_cost":
        gas_result = sample_total_gas_costs(
            n_steps=simulation_config.n_steps,
            config=tranche_c_bundle.gas_process,
        )
    elif tranche_c_bundle.gas_process.mode == "empirical_components":
        gas_result = component_gas_costs(
            sampled_market_gas_rows=market_result.sampled_rows,
            simulated_eth_prices=market_result.price_paths["ETH"],
            config=tranche_c_bundle.gas_process,
        )
    else:
        raise ValueError(f"Unknown gas process mode: {tranche_c_bundle.gas_process.mode}.")

    demand_process = None
    demand_provenance = {"liquidation_demand_mode": "legacy_all_eligible"}
    if isinstance(bundle, TrancheDConfigurationBundle):
        demand_process = LiquidationDemandProcess(bundle.liquidation_demand)
        demand_provenance = demand_process.provenance()

    provenance = {
        "configuration_path": str(bundle.config_path.relative_to(REPOSITORY_ROOT)),
        "configuration_sha256": bundle.config_sha256,
        "simulation_seed": simulation_config.random_seed,
        "tranche_b_vault_pool_checksum": vault_result.provenance.get("pool_checksum"),
        "vault_initialisation": vault_result.provenance,
        "market": market_result.provenance,
        "gas": gas_result.provenance,
        "liquidation_demand": demand_provenance,
        "legacy_or_empirical_mode": (
            "empirical_tranche_d"
            if isinstance(bundle, TrancheDConfigurationBundle)
            else "empirical_tranche_c"
        ),
    }
    return EnvironmentInputResult(
        price_paths=market_result.price_paths,
        gas_cost_path=gas_result.gas_cost_usd,
        initial_vaults=vault_result.vaults,
        market=market_result,
        gas=gas_result,
        liquidation_demand=demand_process,
        provenance=provenance,
    )


def write_environment_provenance(provenance: dict[str, Any], path: Path | str) -> None:
    """Write deterministic Tranche C sidecar provenance."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
