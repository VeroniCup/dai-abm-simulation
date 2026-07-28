"""Semantic configuration profiles and explicit sensitivity overrides.

Legacy experiment factories remain untouched. Complete profiles are loaded
only when requested, while partial sensitivities are applied explicitly and in
caller-supplied order.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
import csv
import hashlib
import json

import yaml

from dai_sim.model.collateral import CollateralConfig, CollateralPortfolioConfig
from dai_sim.model.confidence import ConfidenceConfig
from dai_sim.model.liquidation import LiquidationConfig
from dai_sim.model.market import DAIMarketConfig
from dai_sim.model.simulation import SimulationConfig


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EMPIRICAL_CONFIG_PATH = (
    REPOSITORY_ROOT / "config" / "profiles" / "empirical.yaml"
)
DEFAULT_LEGACY_CONFIG_PATH = REPOSITORY_ROOT / "config" / "profiles" / "legacy.yaml"
DEFAULT_EMPIRICAL_STRESS_CONFIG_PATH = (
    REPOSITORY_ROOT / "config" / "profiles" / "empirical_stress.yaml"
)
DEFAULT_MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "data"
    / "protocol"
    / "provenance"
    / "parameter_adoption"
    / "manifest.json"
)
CALIBRATION_EVIDENCE_ROOT = (
    REPOSITORY_ROOT / "data" / "provenance" / "calibration"
)
PARAMETER_ADOPTION_EVIDENCE_ROOT = (
    CALIBRATION_EVIDENCE_ROOT / "parameter_adoption"
)

EXPECTED_ADOPTION_REVIEW_CHECKSUMS = {
    "data/provenance/calibration/parameter_adoption/parameter_adoption_matrix.csv": (
        "a78a3824c967de1cf794c4128115d67b461d7c207f94ea6b4a44acfc535b44ed"
    ),
    "data/provenance/calibration/parameter_adoption/configuration_ready_candidates.csv": (
        "71e60ba546d860c10d3de0a1e91b016117432f1510b0fd425b2b799219e0dd02"
    ),
    "data/provenance/calibration/parameter_adoption/candidate_consolidation.csv": (
        "c92986f5ac0975804b08c9d1a5fad69886be3fc07e5a8feae625971fc99ffd44"
    ),
    "data/provenance/calibration/parameter_adoption/model_interface_gaps.csv": (
        "8a8c83ab731396c36697e987154f79536d2228df2707ea46ac3cbf6d922c93a3"
    ),
    "data/provenance/calibration/parameter_adoption/proposed_implementation_tranches.csv": (
        "b13cc33e38513bbfeb22aa70cd704d4ba3a88b43f4e6e484a69bf58bef0239de"
    ),
}

CONFIGURATION_READY_CANDIDATES = (
    PARAMETER_ADOPTION_EVIDENCE_ROOT / "configuration_ready_candidates.csv"
)

SUPPORTED_BUNDLE_KEYS = {
    "bundle_name",
    "mode",
    "description",
    "source_manifest",
    "simulation",
    "collateral_portfolio",
    "liquidation",
    "confidence",
    "dai_market",
    "vault_initialisation",
    "market_process",
    "gas_process",
    "liquidation_demand",
    "provenance",
}
SUPPORTED_SIMULATION_KEYS = {
    "n_steps",
    "n_vaults",
    "initial_eth_price",
    "liquidation_ratio",
    "oracle_delay_steps",
    "debt_mean",
    "debt_std",
    "collateral_ratio_mean",
    "collateral_ratio_std",
    "random_seed",
}
SUPPORTED_PORTFOLIO_KEYS = {"name", "target_debt_shares", "compatibility_defaults"}
SUPPORTED_COMPATIBILITY_KEYS = {"initial_prices"}
SUPPORTED_LIQUIDATION_KEYS = {
    "liquidation_penalty",
    "gas_cost",
    "risk_cost_rate",
    "max_close_factor",
    "max_liquidations_per_step",
}
SUPPORTED_CONFIDENCE_KEYS = {
    "normal_lower_price",
    "normal_upper_price",
    "stress_lower_price",
    "max_normal_liquidatable_share",
    "max_stress_liquidatable_share",
    "bad_debt_panic_threshold",
    "normal_confidence",
    "stress_confidence",
    "panic_confidence",
    "panic_selling_multiplier",
}
SUPPORTED_DAI_MARKET_KEYS = {
    "peg_price",
    "price_adjustment_speed",
    "arbitrage_strength",
    "above_peg_supply_strength",
    "panic_strength",
    "noise_std",
    "min_price",
    "max_price",
    "enable_peg_recovery",
    "arbitrage_recovery_strength",
    "policy_feedback_strength",
    "bad_debt_recovery_drag",
    "min_recovery_confidence",
}
SEMANTIC_PROFILE_MODES = {"legacy", "empirical", "empirical_stress"}
SENSITIVITY_METADATA_KEYS = {
    "sensitivity_name",
    "description",
    "source_path",
    "source_sha256",
    "overrides",
}
OVERRIDABLE_PROFILE_KEYS = {
    "simulation",
    "collateral_portfolio",
    "liquidation",
    "confidence",
    "dai_market",
    "vault_initialisation",
    "market_process",
    "gas_process",
    "liquidation_demand",
}


@dataclass(frozen=True)
class EmpiricalConfigurationBundle:
    """Validated Tranche A configuration objects and provenance."""

    bundle_name: str
    config_path: Path
    config_sha256: str
    manifest_path: Path | None
    manifest_sha256: str | None
    simulation_config: SimulationConfig
    liquidation_config: LiquidationConfig
    confidence_config: ConfidenceConfig
    dai_market_config: DAIMarketConfig


def sha256_file(path: Path | str) -> str:
    """Return the SHA-256 digest for a local file."""
    resolved = Path(path)
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_adoption_review_checksums(
    expected: dict[str, str] | None = None,
) -> dict[str, str]:
    """Validate adoption-review artefacts before their rows are consumed."""
    checksums = expected or EXPECTED_ADOPTION_REVIEW_CHECKSUMS
    observed: dict[str, str] = {}
    for relative_path, expected_hash in checksums.items():
        path = REPOSITORY_ROOT / relative_path
        actual_hash = sha256_file(path)
        observed[relative_path] = actual_hash
        if actual_hash != expected_hash:
            raise ValueError(
                f"Checksum mismatch for {relative_path}: "
                f"expected {expected_hash}, observed {actual_hash}."
            )
    return observed


def read_configuration_ready_candidates(
    path: Path | str = CONFIGURATION_READY_CANDIDATES,
) -> list[dict[str, str]]:
    """Read the machine-readable configuration-ready candidate audit."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _reject_unknown_keys(
    mapping: dict[str, Any],
    allowed: set[str],
    context: str,
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise ValueError(f"Unknown {context} keys: {sorted(unknown)}.")


def _require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping.")
    return value


def _validate_probability(value: float, name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must lie in [0, 1].")


def _build_portfolio(raw: dict[str, Any]) -> CollateralPortfolioConfig:
    _reject_unknown_keys(raw, SUPPORTED_PORTFOLIO_KEYS, "collateral_portfolio")
    name = str(raw.get("name", "")).strip()
    shares = _require_mapping(raw.get("target_debt_shares"), "target_debt_shares")
    defaults = _require_mapping(
        raw.get("compatibility_defaults"),
        "compatibility_defaults",
    )
    _reject_unknown_keys(defaults, SUPPORTED_COMPATIBILITY_KEYS, "compatibility_defaults")
    initial_prices = _require_mapping(defaults.get("initial_prices"), "initial_prices")

    collateral_names = tuple(shares)
    if not collateral_names or not set(collateral_names).issubset({"ETH", "BTC"}):
        raise ValueError(
            "target_debt_shares must contain one or both of ETH and BTC."
        )
    if set(initial_prices) != set(shares):
        raise ValueError(
            "compatibility initial_prices must match target_debt_shares."
        )

    total_share = 0.0
    collaterals: list[CollateralConfig] = []
    for collateral_name in collateral_names:
        share = float(shares[collateral_name])
        price = float(initial_prices[collateral_name])
        _validate_probability(share, f"{collateral_name} target_debt_share")
        total_share += share
        collaterals.append(
            CollateralConfig(
                name=collateral_name,
                initial_price=price,
                liquidation_ratio=None,
                liquidation_penalty=None,
                target_debt_share=share,
                max_close_factor=None,
            )
        )

    if abs(total_share - 1.0) > 1e-9:
        raise ValueError(
            "Target debt shares must sum to 1.0; "
            f"received {total_share:.12f}."
        )

    return CollateralPortfolioConfig(name=name, collaterals=tuple(collaterals))


def _build_simulation_config(
    raw: dict[str, Any],
    portfolio: CollateralPortfolioConfig,
    base: SimulationConfig,
) -> SimulationConfig:
    _reject_unknown_keys(raw, SUPPORTED_SIMULATION_KEYS, "simulation")
    n_vaults = int(raw.get("n_vaults", base.n_vaults))
    if n_vaults <= 0:
        raise ValueError("n_vaults must be positive.")
    config = replace(
        base,
        n_steps=int(raw.get("n_steps", base.n_steps)),
        n_vaults=n_vaults,
        initial_eth_price=float(raw.get("initial_eth_price", base.initial_eth_price)),
        liquidation_ratio=float(raw.get("liquidation_ratio", base.liquidation_ratio)),
        oracle_delay_steps=int(raw.get("oracle_delay_steps", base.oracle_delay_steps)),
        debt_mean=float(raw.get("debt_mean", base.debt_mean)),
        debt_std=float(raw.get("debt_std", base.debt_std)),
        collateral_ratio_mean=float(
            raw.get("collateral_ratio_mean", base.collateral_ratio_mean)
        ),
        collateral_ratio_std=float(
            raw.get("collateral_ratio_std", base.collateral_ratio_std)
        ),
        random_seed=(
            None
            if raw.get("random_seed", base.random_seed) is None
            else int(raw.get("random_seed", base.random_seed))
        ),
        collateral_portfolio=portfolio,
    )
    config.validate()
    return config


def _build_liquidation_config(
    raw: dict[str, Any],
    base: LiquidationConfig,
) -> LiquidationConfig:
    _reject_unknown_keys(raw, SUPPORTED_LIQUIDATION_KEYS, "liquidation")
    max_liquidations = raw.get("max_liquidations_per_step")
    config = replace(
        base,
        liquidation_penalty=float(
            raw.get("liquidation_penalty", base.liquidation_penalty)
        ),
        gas_cost=float(raw.get("gas_cost", base.gas_cost)),
        risk_cost_rate=float(raw.get("risk_cost_rate", base.risk_cost_rate)),
        max_close_factor=float(raw.get("max_close_factor", base.max_close_factor)),
        max_liquidations_per_step=(
            base.max_liquidations_per_step
            if "max_liquidations_per_step" not in raw
            else (None if max_liquidations is None else int(max_liquidations))
        ),
    )
    config.validate()
    return config


def _build_confidence_config(
    raw: dict[str, Any],
    base: ConfidenceConfig,
) -> ConfidenceConfig:
    _reject_unknown_keys(raw, SUPPORTED_CONFIDENCE_KEYS, "confidence")
    config = replace(
        base,
        normal_lower_price=float(raw["normal_lower_price"]),
        normal_upper_price=float(raw["normal_upper_price"]),
        stress_lower_price=float(raw["stress_lower_price"]),
        max_normal_liquidatable_share=float(raw["max_normal_liquidatable_share"]),
        max_stress_liquidatable_share=float(
            raw.get(
                "max_stress_liquidatable_share",
                base.max_stress_liquidatable_share,
            )
        ),
        bad_debt_panic_threshold=float(
            raw.get("bad_debt_panic_threshold", base.bad_debt_panic_threshold)
        ),
        normal_confidence=float(raw.get("normal_confidence", base.normal_confidence)),
        stress_confidence=float(raw.get("stress_confidence", base.stress_confidence)),
        panic_confidence=float(raw.get("panic_confidence", base.panic_confidence)),
        panic_selling_multiplier=float(
            raw.get("panic_selling_multiplier", base.panic_selling_multiplier)
        ),
    )
    config.validate()
    return config


def _build_dai_market_config(
    raw: dict[str, Any] | None,
    base: DAIMarketConfig,
) -> DAIMarketConfig:
    if raw is None:
        base.validate()
        return base
    _reject_unknown_keys(raw, SUPPORTED_DAI_MARKET_KEYS, "dai_market")
    values = {
        key: raw.get(key, getattr(base, key))
        for key in SUPPORTED_DAI_MARKET_KEYS
    }
    config = replace(
        base,
        peg_price=float(values["peg_price"]),
        price_adjustment_speed=float(values["price_adjustment_speed"]),
        arbitrage_strength=float(values["arbitrage_strength"]),
        above_peg_supply_strength=float(values["above_peg_supply_strength"]),
        panic_strength=float(values["panic_strength"]),
        noise_std=float(values["noise_std"]),
        min_price=float(values["min_price"]),
        max_price=float(values["max_price"]),
        enable_peg_recovery=bool(values["enable_peg_recovery"]),
        arbitrage_recovery_strength=float(values["arbitrage_recovery_strength"]),
        policy_feedback_strength=float(values["policy_feedback_strength"]),
        bad_debt_recovery_drag=float(values["bad_debt_recovery_drag"]),
        min_recovery_confidence=float(values["min_recovery_confidence"]),
    )
    config.validate()
    return config


def _load_yaml_mapping(path: Path | str, context: str) -> dict[str, Any]:
    resolved = Path(path)
    with resolved.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{context} must be a mapping.")
    return payload


def _merge_override(base: Any, override: Any, path: tuple[str, ...] = ()) -> Any:
    """Merge an explicit override, rejecting mapping/list type conflicts."""
    location = ".".join(path) or "<root>"
    if isinstance(base, dict):
        if not isinstance(override, dict):
            raise ValueError(f"Type conflict at {location}: mapping required.")
        result = dict(base)
        for key, value in override.items():
            child_path = path + (str(key),)
            result[key] = (
                _merge_override(result[key], value, child_path)
                if key in result
                else value
            )
        return result
    if isinstance(override, dict):
        raise ValueError(f"Type conflict at {location}: scalar or list required.")
    if isinstance(base, list) != isinstance(override, list):
        if isinstance(base, list) or isinstance(override, list):
            raise ValueError(f"Type conflict at {location}: list shape differs.")
    return override


def apply_configuration_overrides(
    profile: dict[str, Any],
    sensitivities: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Apply validated partial sensitivities in explicit caller order."""
    if not isinstance(profile, dict):
        raise ValueError("Complete profile must be a mapping.")
    result = dict(profile)
    for index, sensitivity in enumerate(sensitivities):
        if not isinstance(sensitivity, dict):
            raise ValueError(f"Sensitivity {index} must be a mapping.")
        _reject_unknown_keys(
            sensitivity,
            SENSITIVITY_METADATA_KEYS,
            f"sensitivity {index}",
        )
        overrides = sensitivity.get("overrides")
        if not isinstance(overrides, dict) or not overrides:
            raise ValueError(f"Sensitivity {index} overrides must be a non-empty mapping.")
        unknown = set(overrides) - OVERRIDABLE_PROFILE_KEYS
        if unknown:
            raise ValueError(
                f"Sensitivity {index} contains unsupported override keys: "
                f"{sorted(unknown)}."
            )
        result = _merge_override(result, overrides)
    return result


def load_configuration_payload(
    profile_path: Path | str,
    sensitivity_paths: tuple[Path | str, ...] = (),
) -> dict[str, Any]:
    """Load one complete profile and explicit semantic sensitivity files."""
    profile = _load_yaml_mapping(profile_path, "Configuration profile")
    sensitivities: list[dict[str, Any]] = []
    for path in sensitivity_paths:
        sensitivity = _load_yaml_mapping(path, "Configuration sensitivity")
        source_path = sensitivity.get("source_path")
        source_sha256 = sensitivity.get("source_sha256")
        if not isinstance(source_path, str) or not isinstance(source_sha256, str):
            raise ValueError("Sensitivity source_path and source_sha256 are required.")
        if len(source_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in source_sha256
        ):
            raise ValueError("Sensitivity source_sha256 must be a lowercase SHA-256.")
        sensitivities.append(sensitivity)
    return apply_configuration_overrides(profile, sensitivities)


def load_empirical_configuration_bundle(
    path: Path | str = DEFAULT_EMPIRICAL_CONFIG_PATH,
    *,
    base_simulation_config: SimulationConfig | None = None,
    base_liquidation_config: LiquidationConfig | None = None,
    base_confidence_config: ConfidenceConfig | None = None,
    base_dai_market_config: DAIMarketConfig | None = None,
    verify_registry_checksums: bool = True,
) -> EmpiricalConfigurationBundle:
    """
    Load the explicit Tranche A empirical bundle.

    Missing simulator fields inherit supplied base objects or dataclass
    defaults. No default experiment path calls this function.
    """
    config_path = Path(path).resolve()
    if verify_registry_checksums:
        verify_adoption_review_checksums()

    raw = _load_yaml_mapping(config_path, "Empirical configuration")
    _reject_unknown_keys(raw, SUPPORTED_BUNDLE_KEYS, "bundle")

    bundle_name = str(raw.get("bundle_name", "")).strip()
    mode = str(raw.get("mode", "")).strip()
    if mode not in SEMANTIC_PROFILE_MODES:
        raise ValueError(f"Unsupported configuration profile mode: {mode}.")
    if not bundle_name:
        raise ValueError("Configuration bundle_name must not be empty.")

    source_manifest = raw.get("source_manifest")
    manifest_path = (
        None
        if source_manifest is None
        else REPOSITORY_ROOT / str(source_manifest)
    )
    portfolio = _build_portfolio(
        _require_mapping(raw.get("collateral_portfolio"), "collateral_portfolio")
    )
    simulation = _build_simulation_config(
        _require_mapping(raw.get("simulation"), "simulation"),
        portfolio=portfolio,
        base=base_simulation_config or SimulationConfig(),
    )
    liquidation = _build_liquidation_config(
        _require_mapping(raw.get("liquidation"), "liquidation"),
        base=base_liquidation_config or LiquidationConfig(),
    )
    confidence = _build_confidence_config(
        _require_mapping(raw.get("confidence"), "confidence"),
        base=base_confidence_config or ConfidenceConfig(),
    )
    dai_market = _build_dai_market_config(
        raw.get("dai_market"),
        base_dai_market_config or DAIMarketConfig(),
    )

    return EmpiricalConfigurationBundle(
        bundle_name=bundle_name,
        config_path=config_path,
        config_sha256=sha256_file(config_path),
        manifest_path=manifest_path,
        manifest_sha256=(
            None if manifest_path is None else sha256_file(manifest_path)
        ),
        simulation_config=simulation,
        liquidation_config=liquidation,
        confidence_config=confidence,
        dai_market_config=dai_market,
    )


def empirical_run_provenance(
    bundle: EmpiricalConfigurationBundle,
    *,
    seed: int | None,
    experiment_name: str,
) -> dict[str, Any]:
    """Return sidecar metadata for an explicitly selected empirical run."""
    return {
        "mode": "empirical_tranche_a",
        "configuration_bundle_name": bundle.bundle_name,
        "configuration_file": str(bundle.config_path.relative_to(REPOSITORY_ROOT)),
        "configuration_sha256": bundle.config_sha256,
        "candidate_manifest": (
            None
            if bundle.manifest_path is None
            else str(bundle.manifest_path.relative_to(REPOSITORY_ROOT))
        ),
        "candidate_manifest_sha256": bundle.manifest_sha256,
        "seed": seed,
        "experiment_name": experiment_name,
    }


def manifest_records(path: Path | str = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Read the compact Tranche A manifest."""
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("bundle_name") != "phase2_empirical_baseline":
        raise ValueError("Unexpected parameter-adoption manifest bundle name.")
    return payload
