"""Provide opt-in distribution-aware vault initialisation.

Legacy Gaussian initialisation remains the simulator default. Distributional
sampling is used only when selected explicitly by a semantic profile.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib
import json

import numpy as np
import pandas as pd

from dai_sim.model.collateral import CollateralPortfolioConfig
from dai_sim.model.simulation import SimulationConfig, create_initial_vaults
from dai_sim.model.vault import Vault, create_vault_from_target_cr, vaults_to_dataframe

from .configuration import (
    REPOSITORY_ROOT,
    build_empirical_configuration_bundle,
    load_configuration_payload,
    sha256_file,
    verify_adoption_review_checksums,
)


DEFAULT_POOL_PATH = (
    REPOSITORY_ROOT
    / "data"
    / "vaults"
    / "model_inputs"
    / "initialisation"
    / "pool.csv"
)
DEFAULT_POOL_MANIFEST = (
    REPOSITORY_ROOT
    / "data"
    / "vaults"
    / "model_inputs"
    / "initialisation"
    / "manifest.json"
)
DEFAULT_TRANCHE_B_CONFIG_PATH = (
    REPOSITORY_ROOT / "config" / "profiles" / "empirical.yaml"
)

VALID_MODES = {"legacy_gaussian", "parametric_truncated", "empirical_joint"}
VALID_REGIMES = {"normal", "moderate_stress", "severe_stress"}
POOL_COLUMNS = {
    "pool_row_id",
    "source_window",
    "regime_label",
    "state_label",
    "timestamp_utc",
    "ilk",
    "collateral_family",
    "debt_dai",
    "collateral_ratio",
    "liquidation_ratio",
    "absolute_buffer",
    "relative_buffer",
}


@dataclass(frozen=True)
class ParametricFamilyConfig:
    """Positive marginal fallback distributions for one collateral family."""

    debt_log_mean: float
    debt_log_std: float
    buffer_log_mean: float
    buffer_log_std: float
    liquidation_ratio: float
    minimum_debt: float
    maximum_debt: float
    minimum_buffer: float
    maximum_buffer: float


@dataclass(frozen=True)
class VaultInitialisationConfig:
    """Configuration for one opt-in vault initialisation mode."""

    mode: str = "legacy_gaussian"
    seed: int | None = None
    regime: str = "normal"
    pool_path: Path | None = None
    pool_sha256: str | None = None
    fallback: str = "parametric_truncated"
    by_ilk: bool = False
    minimum_exact_ilk_pool_size: int = 50
    allow_initial_liquidatable: bool = False
    sample_with_replacement: bool = True
    max_sampling_attempts: int = 10_000
    parametric: dict[str, ParametricFamilyConfig] | None = None

    def validate(self) -> None:
        """Validate initialisation controls."""
        if self.mode not in VALID_MODES:
            raise ValueError(f"Unknown vault initialisation mode: {self.mode}.")
        if self.regime not in VALID_REGIMES:
            raise ValueError(f"Unknown vault initialisation regime: {self.regime}.")
        if self.fallback not in {"parametric_truncated", "family_pool", "global_pool"}:
            raise ValueError(f"Unknown vault initialisation fallback: {self.fallback}.")
        if self.minimum_exact_ilk_pool_size <= 0:
            raise ValueError("minimum_exact_ilk_pool_size must be positive.")
        if self.max_sampling_attempts <= 0:
            raise ValueError("max_sampling_attempts must be positive.")


@dataclass(frozen=True)
class TrancheBConfigurationBundle:
    """Loaded empirical configuration and initialisation controls."""

    bundle_name: str
    config_path: Path
    config_sha256: str
    initialisation: VaultInitialisationConfig
    base_bundle: Any


@dataclass(frozen=True)
class InitialisationResult:
    """Generated vaults and diagnostics for one initialisation run."""

    vaults: list[Vault]
    sampled_rows: pd.DataFrame
    provenance: dict[str, Any]


def load_pool(path: Path | str, expected_sha256: str | None = None) -> pd.DataFrame:
    """Load and validate a compact empirical initialisation pool."""
    pool_path = Path(path)
    if expected_sha256 is not None:
        observed = sha256_file(pool_path)
        if observed != expected_sha256:
            raise ValueError(
                f"Pool checksum mismatch: expected {expected_sha256}, observed {observed}."
            )
    pool = pd.read_csv(pool_path)
    missing = POOL_COLUMNS - set(pool.columns)
    if missing:
        raise ValueError(f"Empirical vault pool missing columns: {sorted(missing)}.")
    for column in [
        "debt_dai",
        "collateral_ratio",
        "liquidation_ratio",
        "absolute_buffer",
        "relative_buffer",
    ]:
        pool[column] = pd.to_numeric(pool[column], errors="coerce")
    if pool["pool_row_id"].duplicated().any():
        raise ValueError("Empirical vault pool contains duplicate pool_row_id values.")
    if pool["debt_dai"].le(0).any():
        raise ValueError("Empirical vault pool contains non-positive debt.")
    if pool["absolute_buffer"].lt(0).any():
        raise ValueError("Empirical vault pool contains liquidatable initial rows.")
    if not set(pool["collateral_family"]).issubset({"ETH", "WBTC"}):
        raise ValueError("Empirical vault pool contains unsupported collateral families.")
    return pool.sort_values("pool_row_id", kind="mergesort").reset_index(drop=True)


def _require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping.")
    return value


def _parse_parametric(raw: dict[str, Any] | None) -> dict[str, ParametricFamilyConfig] | None:
    if raw is None:
        return None
    result: dict[str, ParametricFamilyConfig] = {}
    for family, values in raw.items():
        family_key = str(family).upper()
        mapping = _require_mapping(values, f"parametric.{family_key}")
        result[family_key] = ParametricFamilyConfig(
            debt_log_mean=float(mapping["debt_log_mean"]),
            debt_log_std=float(mapping["debt_log_std"]),
            buffer_log_mean=float(mapping["buffer_log_mean"]),
            buffer_log_std=float(mapping["buffer_log_std"]),
            liquidation_ratio=float(mapping["liquidation_ratio"]),
            minimum_debt=float(mapping["minimum_debt"]),
            maximum_debt=float(mapping["maximum_debt"]),
            minimum_buffer=float(mapping["minimum_buffer"]),
            maximum_buffer=float(mapping["maximum_buffer"]),
        )
    return result


def _parse_initialisation(raw: dict[str, Any] | None) -> VaultInitialisationConfig:
    if raw is None:
        config = VaultInitialisationConfig()
        config.validate()
        return config
    allowed = {
        "mode",
        "seed",
        "regime",
        "pool_path",
        "pool_sha256",
        "fallback",
        "by_ilk",
        "minimum_exact_ilk_pool_size",
        "allow_initial_liquidatable",
        "sample_with_replacement",
        "max_sampling_attempts",
        "parametric",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown vault_initialisation keys: {sorted(unknown)}.")
    config = VaultInitialisationConfig(
        mode=str(raw.get("mode", "legacy_gaussian")),
        seed=(
            None
            if raw.get("seed") is None
            else int(raw.get("seed"))
        ),
        regime=str(raw.get("regime", "normal")),
        pool_path=(
            None
            if raw.get("pool_path") is None
            else REPOSITORY_ROOT / str(raw.get("pool_path"))
        ),
        pool_sha256=raw.get("pool_sha256"),
        fallback=str(raw.get("fallback", "parametric_truncated")),
        by_ilk=bool(raw.get("by_ilk", False)),
        minimum_exact_ilk_pool_size=int(raw.get("minimum_exact_ilk_pool_size", 50)),
        allow_initial_liquidatable=bool(raw.get("allow_initial_liquidatable", False)),
        sample_with_replacement=bool(raw.get("sample_with_replacement", True)),
        max_sampling_attempts=int(raw.get("max_sampling_attempts", 10_000)),
        parametric=_parse_parametric(raw.get("parametric")),
    )
    config.validate()
    return config


def load_tranche_b_configuration(
    path: Path | str = DEFAULT_TRANCHE_B_CONFIG_PATH,
    *,
    sensitivity_paths: tuple[Path | str, ...] = (),
) -> TrancheBConfigurationBundle:
    """Load empirical vault-initialisation controls from a semantic profile."""
    verify_adoption_review_checksums()
    config_path = Path(path).resolve()
    raw = load_configuration_payload(config_path, sensitivity_paths)
    if not isinstance(raw, dict):
        raise ValueError("Tranche B configuration must be a mapping.")
    if raw.get("mode") not in {"legacy", "empirical", "empirical_stress"}:
        raise ValueError("Tranche B mode must be a semantic profile mode.")

    base_bundle = build_empirical_configuration_bundle(
        raw,
        config_path=config_path,
        verify_registry_checksums=False,
    )

    return TrancheBConfigurationBundle(
        bundle_name=str(raw["bundle_name"]),
        config_path=config_path,
        config_sha256=sha256_file(config_path),
        initialisation=_parse_initialisation(raw.get("vault_initialisation")),
        base_bundle=base_bundle,
    )


def _target_counts(
    n_vaults: int,
    portfolio: CollateralPortfolioConfig,
) -> dict[str, int]:
    names = tuple(portfolio.collateral_names)
    raw_counts = {
        name: n_vaults * portfolio.target_debt_shares[name]
        for name in names
    }
    counts = {name: int(np.floor(value)) for name, value in raw_counts.items()}
    remaining = n_vaults - sum(counts.values())
    ordered = sorted(
        names,
        key=lambda name: (-(raw_counts[name] - counts[name]), name),
    )
    for name in ordered[:remaining]:
        counts[name] += 1
    return counts


def _canonical_family(name: str) -> str:
    normalised = str(name).strip().upper()
    return "WBTC" if normalised == "BTC" else normalised


def _sample_empirical_joint(
    simulation_config: SimulationConfig,
    init_config: VaultInitialisationConfig,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, dict[str, int]]:
    pool_path = init_config.pool_path or DEFAULT_POOL_PATH
    pool = load_pool(pool_path, init_config.pool_sha256)
    regime_pool = pool.loc[pool["regime_label"].eq(init_config.regime)].copy()
    if regime_pool.empty:
        raise ValueError(f"No empirical pool rows for regime {init_config.regime}.")

    portfolio = simulation_config.collateral_portfolio
    if portfolio is None:
        raise ValueError("Empirical joint sampling requires a collateral portfolio.")
    counts = _target_counts(simulation_config.n_vaults, portfolio)
    selected: list[pd.DataFrame] = []
    fallback_counts = Counter()

    for collateral_name, count in counts.items():
        family = _canonical_family(collateral_name)
        family_pool = regime_pool.loc[regime_pool["collateral_family"].eq(family)]
        if family_pool.empty:
            if init_config.fallback == "global_pool":
                family_pool = regime_pool
                fallback_counts["global_pool"] += count
            else:
                raise ValueError(f"No empirical pool rows for family {family}.")

        if init_config.by_ilk:
            ilk_counts = _target_counts_by_pool_debt(count, family_pool)
            for ilk, ilk_count in ilk_counts.items():
                ilk_pool = family_pool.loc[family_pool["ilk"].eq(ilk)]
                if len(ilk_pool) >= init_config.minimum_exact_ilk_pool_size:
                    draw_pool = ilk_pool
                    fallback_counts["exact_ilk_pool"] += ilk_count
                else:
                    draw_pool = family_pool
                    fallback_counts["family_pool"] += ilk_count
                selected.append(_draw_rows(draw_pool, ilk_count, rng, init_config))
        else:
            fallback_counts["family_pool"] += count
            selected.append(_draw_rows(family_pool, count, rng, init_config))

    result = pd.concat(selected, ignore_index=True)
    result = result.sample(frac=1.0, random_state=rng).reset_index(drop=True)
    return result, dict(fallback_counts)


def _target_counts_by_pool_debt(count: int, pool: pd.DataFrame) -> dict[str, int]:
    debt = pool.groupby("ilk")["debt_dai"].sum()
    shares = (debt / debt.sum()).to_dict()
    raw_counts = {ilk: count * share for ilk, share in shares.items()}
    counts = {ilk: int(np.floor(value)) for ilk, value in raw_counts.items()}
    remaining = count - sum(counts.values())
    ordered = sorted(pool["ilk"].unique(), key=lambda ilk: (-(raw_counts[ilk] - counts[ilk]), ilk))
    for ilk in ordered[:remaining]:
        counts[ilk] += 1
    return {ilk: value for ilk, value in counts.items() if value > 0}


def _draw_rows(
    pool: pd.DataFrame,
    count: int,
    rng: np.random.Generator,
    init_config: VaultInitialisationConfig,
) -> pd.DataFrame:
    replace = init_config.sample_with_replacement or count > len(pool)
    if count > len(pool) and not replace:
        raise ValueError("Requested empirical sample exceeds pool size without replacement.")
    indices = rng.choice(pool.index.to_numpy(), size=count, replace=replace)
    return pool.loc[indices].copy()


def _sample_parametric(
    simulation_config: SimulationConfig,
    init_config: VaultInitialisationConfig,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, dict[str, int]]:
    if init_config.parametric is None:
        raise ValueError("parametric_truncated mode requires parametric settings.")
    portfolio = simulation_config.collateral_portfolio
    if portfolio is None:
        raise ValueError("Parametric sampling requires a collateral portfolio.")
    counts = _target_counts(simulation_config.n_vaults, portfolio)
    records: list[dict[str, Any]] = []
    for collateral_name, count in counts.items():
        family = _canonical_family(collateral_name)
        params = init_config.parametric.get(family)
        if params is None:
            raise ValueError(f"Missing parametric settings for family {family}.")
        attempts = 0
        accepted = 0
        while accepted < count:
            if attempts >= init_config.max_sampling_attempts:
                raise ValueError(
                    f"Could not generate {count} valid {family} parametric samples "
                    f"within {init_config.max_sampling_attempts} attempts."
                )
            attempts += 1
            debt = float(rng.lognormal(params.debt_log_mean, params.debt_log_std))
            buffer = float(rng.lognormal(params.buffer_log_mean, params.buffer_log_std))
            if not (
                params.minimum_debt <= debt <= params.maximum_debt
                and params.minimum_buffer <= buffer <= params.maximum_buffer
            ):
                continue
            liquidation_ratio = params.liquidation_ratio
            collateral_ratio = liquidation_ratio + buffer
            records.append(
                {
                    "pool_row_id": f"parametric_{family}_{accepted:06d}",
                    "source_window": "parametric_truncated",
                    "regime_label": init_config.regime,
                    "state_label": "synthetic",
                    "timestamp_utc": "",
                    "ilk": f"{family}-FAMILY",
                    "collateral_family": family,
                    "debt_dai": debt,
                    "collateral_ratio": collateral_ratio,
                    "liquidation_ratio": liquidation_ratio,
                    "absolute_buffer": buffer,
                    "relative_buffer": collateral_ratio / liquidation_ratio - 1.0,
                }
            )
            accepted += 1
    return pd.DataFrame(records), {"parametric_truncated": len(records)}


def _rows_to_vaults(
    rows: pd.DataFrame,
    simulation_config: SimulationConfig,
) -> list[Vault]:
    portfolio = simulation_config.collateral_portfolio
    if portfolio is None:
        raise ValueError("Distribution-aware sampling requires a collateral portfolio.")
    prices = portfolio.initial_prices
    vaults: list[Vault] = []
    for index, row in rows.reset_index(drop=True).iterrows():
        family = str(row["collateral_family"])
        collateral_type = "BTC" if family == "WBTC" else family
        price = prices[collateral_type]
        vaults.append(
            create_vault_from_target_cr(
                vault_id=index,
                owner_id=index,
                debt_dai=float(row["debt_dai"]),
                target_collateral_ratio=float(row["collateral_ratio"]),
                prices={collateral_type: price},
                liquidation_ratio=float(row["liquidation_ratio"]),
                collateral_type=collateral_type,
            )
        )
    return vaults


def initialise_vaults(
    simulation_config: SimulationConfig,
    init_config: VaultInitialisationConfig | None = None,
) -> InitialisationResult:
    """Initialise vaults using the selected legacy or empirical mode."""
    config = init_config or VaultInitialisationConfig()
    config.validate()

    if config.mode == "legacy_gaussian":
        vaults = create_initial_vaults(simulation_config)
        frame = vaults_to_dataframe(
            vaults,
            simulation_config.initial_eth_price
            if simulation_config.collateral_portfolio is None
            else simulation_config.collateral_portfolio.initial_prices,
        )
        return InitialisationResult(
            vaults=vaults,
            sampled_rows=frame,
            provenance={
                "mode": "legacy_gaussian",
                "initialisation_mode": "legacy_gaussian",
                "seed": simulation_config.random_seed,
                "requested_vault_count": simulation_config.n_vaults,
                "fallback_counts": {},
            },
        )

    rng = np.random.default_rng(
        config.seed if config.seed is not None else simulation_config.random_seed
    )
    if config.mode == "empirical_joint":
        sampled, fallback_counts = _sample_empirical_joint(simulation_config, config, rng)
    elif config.mode == "parametric_truncated":
        sampled, fallback_counts = _sample_parametric(simulation_config, config, rng)
    else:
        raise ValueError(f"Unknown vault initialisation mode: {config.mode}.")

    if not config.allow_initial_liquidatable and sampled["absolute_buffer"].lt(0).any():
        raise ValueError("Initial liquidatable vaults are not allowed by this config.")

    vaults = _rows_to_vaults(sampled, simulation_config)
    provenance = initialisation_provenance(
        vaults=vaults,
        sampled_rows=sampled,
        simulation_config=simulation_config,
        init_config=config,
        fallback_counts=fallback_counts,
    )
    return InitialisationResult(vaults=vaults, sampled_rows=sampled, provenance=provenance)


def _series_summary(series: pd.Series) -> dict[str, float]:
    values = pd.to_numeric(series, errors="coerce").dropna()
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


def initialisation_provenance(
    *,
    vaults: list[Vault],
    sampled_rows: pd.DataFrame,
    simulation_config: SimulationConfig,
    init_config: VaultInitialisationConfig,
    fallback_counts: dict[str, int],
) -> dict[str, Any]:
    """Return sidecar metadata for one vault-initialisation run."""
    pool_checksum = None
    pool_path = None
    if init_config.pool_path is not None:
        pool_path = str(init_config.pool_path.relative_to(REPOSITORY_ROOT))
        pool_checksum = sha256_file(init_config.pool_path)
    duplicate_draws = (
        int(sampled_rows["pool_row_id"].duplicated().sum())
        if "pool_row_id" in sampled_rows
        else 0
    )
    return {
        "initialisation_mode": init_config.mode,
        "empirical_pool_version": "tranche_b_v1" if pool_path else None,
        "pool_path": pool_path,
        "pool_checksum": pool_checksum,
        "seed": init_config.seed if init_config.seed is not None else simulation_config.random_seed,
        "requested_vault_count": simulation_config.n_vaults,
        "sampled_counts_by_family": sampled_rows["collateral_family"].value_counts().sort_index().to_dict(),
        "sampled_counts_by_ilk": sampled_rows["ilk"].value_counts().sort_index().to_dict(),
        "fallback_counts": fallback_counts,
        "replacement_used": duplicate_draws > 0,
        "duplicate_empirical_row_draw_count": duplicate_draws,
        "initial_debt_summary": _series_summary(sampled_rows["debt_dai"]),
        "initial_collateral_ratio_summary": _series_summary(sampled_rows["collateral_ratio"]),
        "initial_buffer_summary": _series_summary(sampled_rows["absolute_buffer"]),
        "initial_liquidatable_count": int((sampled_rows["absolute_buffer"] < 0).sum()),
        "initial_liquidatable_share": float((sampled_rows["absolute_buffer"] < 0).mean()),
    }


def write_initialisation_metadata(metadata: dict[str, Any], path: Path | str) -> None:
    """Write deterministic vault-initialisation metadata."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare_sample_to_pool(sampled: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
    """Return transparent marginal and dependence diagnostics."""
    records: list[dict[str, Any]] = []
    for variable in ("debt_dai", "collateral_ratio", "absolute_buffer"):
        for label, frame in (("sample", sampled), ("pool", pool)):
            summary = _series_summary(frame[variable])
            records.append({"dataset": label, "variable": variable, **summary})
    for label, frame in (("sample", sampled), ("pool", pool)):
        debt = pd.to_numeric(frame["debt_dai"], errors="coerce")
        buffer = pd.to_numeric(frame["absolute_buffer"], errors="coerce")
        records.append(
            {
                "dataset": label,
                "variable": "debt_buffer_dependence",
                "count": float(len(frame)),
                "mean": float(debt.corr(buffer, method="pearson")),
                "std": float(debt.corr(buffer, method="spearman")),
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
    return pd.DataFrame(records)
