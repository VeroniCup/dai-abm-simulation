"""
Opt-in empirical configuration bundle loading for Phase 2 Tranche A.

This module deliberately leaves the legacy experiment factories untouched.
It validates a separate YAML bundle and converts only audited, compatible
configuration-ready candidates into existing simulator dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
import csv
import hashlib
import json

import yaml

from collateral import CollateralConfig, CollateralPortfolioConfig
from confidence import ConfidenceConfig
from dai_market import DAIMarketConfig
from liquidation import LiquidationConfig
from simulation import SimulationConfig


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EMPIRICAL_CONFIG_PATH = (
    REPOSITORY_ROOT / "config" / "empirical" / "phase2_empirical_baseline.yaml"
)
DEFAULT_MANIFEST_PATH = REPOSITORY_ROOT / "config" / "empirical" / "tranche_a_manifest.json"

EXPECTED_ADOPTION_REVIEW_CHECKSUMS = {
    "data/processed/estimation/adoption_review/parameter_adoption_matrix.csv": (
        "a78a3824c967de1cf794c4128115d67b461d7c207f94ea6b4a44acfc535b44ed"
    ),
    "data/processed/estimation/adoption_review/configuration_ready_candidates.csv": (
        "71e60ba546d860c10d3de0a1e91b016117432f1510b0fd425b2b799219e0dd02"
    ),
    "data/processed/estimation/adoption_review/candidate_consolidation.csv": (
        "c92986f5ac0975804b08c9d1a5fad69886be3fc07e5a8feae625971fc99ffd44"
    ),
    "data/processed/estimation/adoption_review/model_interface_gaps.csv": (
        "8a8c83ab731396c36697e987154f79536d2228df2707ea46ac3cbf6d922c93a3"
    ),
    "data/processed/estimation/adoption_review/proposed_implementation_tranches.csv": (
        "b13cc33e38513bbfeb22aa70cd704d4ba3a88b43f4e6e484a69bf58bef0239de"
    ),
}

CONFIGURATION_READY_CANDIDATES = (
    REPOSITORY_ROOT
    / "data"
    / "processed"
    / "estimation"
    / "adoption_review"
    / "configuration_ready_candidates.csv"
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
    "provenance",
}
SUPPORTED_SIMULATION_KEYS = {"n_vaults"}
SUPPORTED_PORTFOLIO_KEYS = {"name", "target_debt_shares", "compatibility_defaults"}
SUPPORTED_COMPATIBILITY_KEYS = {"initial_prices"}
SUPPORTED_LIQUIDATION_KEYS = {"max_close_factor"}
SUPPORTED_CONFIDENCE_KEYS = {
    "normal_lower_price",
    "normal_upper_price",
    "stress_lower_price",
    "max_normal_liquidatable_share",
}


@dataclass(frozen=True)
class EmpiricalConfigurationBundle:
    """Validated Tranche A configuration objects and provenance."""

    bundle_name: str
    config_path: Path
    config_sha256: str
    manifest_path: Path
    manifest_sha256: str
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

    if set(shares) != {"ETH", "BTC"}:
        raise ValueError("Tranche A target_debt_shares must contain ETH and BTC.")

    total_share = 0.0
    collaterals: list[CollateralConfig] = []
    for collateral_name in ("ETH", "BTC"):
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
            "Tranche A target debt shares must sum to 1.0; "
            f"received {total_share:.12f}."
        )

    return CollateralPortfolioConfig(name=name, collaterals=tuple(collaterals))


def _build_simulation_config(
    raw: dict[str, Any],
    portfolio: CollateralPortfolioConfig,
    base: SimulationConfig,
) -> SimulationConfig:
    _reject_unknown_keys(raw, SUPPORTED_SIMULATION_KEYS, "simulation")
    n_vaults = int(raw["n_vaults"])
    if n_vaults <= 0:
        raise ValueError("n_vaults must be positive.")
    config = replace(base, n_vaults=n_vaults, collateral_portfolio=portfolio)
    config.validate()
    return config


def _build_liquidation_config(
    raw: dict[str, Any],
    base: LiquidationConfig,
) -> LiquidationConfig:
    _reject_unknown_keys(raw, SUPPORTED_LIQUIDATION_KEYS, "liquidation")
    config = replace(base, max_close_factor=float(raw["max_close_factor"]))
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
    )
    config.validate()
    return config


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
    config_path = Path(path)
    if verify_registry_checksums:
        verify_adoption_review_checksums()

    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError("Empirical configuration must be a mapping.")
    _reject_unknown_keys(raw, SUPPORTED_BUNDLE_KEYS, "bundle")

    bundle_name = str(raw.get("bundle_name", "")).strip()
    if not bundle_name.startswith("phase2_empirical_"):
        raise ValueError("Tranche A bundle_name must start with phase2_empirical_.")
    if raw.get("mode") != "empirical_tranche_a":
        raise ValueError("Tranche A mode must be empirical_tranche_a.")

    manifest_path = REPOSITORY_ROOT / str(raw["source_manifest"])
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
    dai_market = base_dai_market_config or DAIMarketConfig()
    dai_market.validate()

    return EmpiricalConfigurationBundle(
        bundle_name=bundle_name,
        config_path=config_path,
        config_sha256=sha256_file(config_path),
        manifest_path=manifest_path,
        manifest_sha256=sha256_file(manifest_path),
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
        "candidate_manifest": str(bundle.manifest_path.relative_to(REPOSITORY_ROOT)),
        "candidate_manifest_sha256": bundle.manifest_sha256,
        "seed": seed,
        "experiment_name": experiment_name,
    }


def manifest_records(path: Path | str = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Read the compact Tranche A manifest."""
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("bundle_name") != "phase2_empirical_baseline":
        raise ValueError("Unexpected Tranche A manifest bundle name.")
    return payload
