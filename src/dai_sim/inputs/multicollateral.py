"""Typed, dormant final multi-collateral empirical inputs.

The registries in this module freeze evidence owners and counterfactual choices
without adopting them in the ordinary runtime.  Resolution is deterministic:
family and registry order are explicit, vault counts use largest remainders,
and every frozen local source is checksum-validated before use.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from dai_sim.inputs.runtime_sources import resolve_runtime_source


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FAMILY_ORDER = ("ETH", "WBTC", "STABLE")
PORTFOLIO_ORDER = (
    "eth_only",
    "empirical_crypto",
    "balanced_crypto",
    "stable_supported",
    "stable_heavy",
)
SHOCK_ORDER = (
    "eth_idiosyncratic_severe",
    "wbtc_idiosyncratic_severe",
    "joint_crypto_empirical_stress",
    "joint_crypto_high_correlation",
    "stable_depeg_moderate",
    "stable_depeg_severe",
    "joint_crypto_stable_stress",
)
PROFILE_IDENTIFIER = "empirical_integrated_multicollateral"

DEFAULT_COLLATERAL_REGISTRY_PATH = (
    REPOSITORY_ROOT / "config/protocol/final_collateral_registry.yaml"
)
DEFAULT_PORTFOLIO_REGISTRY_PATH = (
    REPOSITORY_ROOT / "config/sensitivities/final_portfolio_registry.yaml"
)
DEFAULT_SHOCK_REGISTRY_PATH = (
    REPOSITORY_ROOT / "config/sensitivities/final_shock_registry.yaml"
)
DEFAULT_PROFILE_PATH = (
    REPOSITORY_ROOT / "config/profiles/empirical_integrated_multicollateral.yaml"
)
DEFAULT_ENVIRONMENT_POOL_PATH = (
    REPOSITORY_ROOT / "data/market/model_inputs/environment_blocks/pool.csv"
)
DEFAULT_MARKET_PANEL_PATH = (
    REPOSITORY_ROOT
    / "data/market/processed/dune_hourly_market_prices_processed.csv"
)
DEFAULT_FINAL_MARKET_POOL_PATH = (
    REPOSITORY_ROOT / "data/market/model_inputs/multicollateral_blocks/pool.csv"
)
DEFAULT_FINAL_MARKET_MANIFEST_PATH = (
    REPOSITORY_ROOT / "data/market/model_inputs/multicollateral_blocks/manifest.json"
)

EXPECTED_ENVIRONMENT_POOL_SHA256 = (
    "b69276801bacf789f8ae91789983cc98a8a6d42d0a992940c0bcfa109ca25b7d"
)
EXPECTED_MARKET_PANEL_SHA256 = (
    "43f8a23aff2ec995a4e1ad5e8fc66f4b5223e8dcc9c8a36bd272d733ae1d4e25"
)
FTX_START = pd.Timestamp("2022-11-01T00:00:00Z")
FTX_END = pd.Timestamp("2022-11-21T00:00:00Z")
SVB_START = pd.Timestamp("2023-03-06T00:00:00Z")
SVB_END = pd.Timestamp("2023-03-20T00:00:00Z")


def _sha256_file(path: Path | str) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_path(value: Any, context: str, *, must_exist: bool = True) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a repository-relative path.")
    path = (REPOSITORY_ROOT / value).resolve()
    try:
        path.relative_to(REPOSITORY_ROOT)
    except ValueError as exc:
        raise ValueError(f"{context} must remain inside the repository.") from exc
    if must_exist and not path.is_file():
        raise ValueError(f"{context} does not exist: {value}.")
    return path


def _load_yaml(path: Path | str) -> tuple[Path, dict[str, Any]]:
    resolved = Path(path).resolve()
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{resolved} must contain a YAML mapping.")
    return resolved, payload


def _decimal(value: Any, context: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{context} must be numeric.")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{context} must be numeric.") from exc
    if not result.is_finite():
        raise ValueError(f"{context} must be finite.")
    return result


def _optional_decimal(value: Any, context: str) -> Decimal | None:
    return None if value is None else _decimal(value, context)


def _ordered_mapping(
    raw: Any,
    expected_order: Sequence[str],
    context: str,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{context} must be a mapping.")
    if tuple(raw) != tuple(expected_order):
        raise ValueError(
            f"{context} order must be exactly {tuple(expected_order)}; "
            f"received {tuple(raw)}."
        )
    return raw


def _validate_frozen_file(path_value: Any, checksum_value: Any, context: str) -> Path:
    if not isinstance(checksum_value, str) or len(checksum_value) != 64:
        raise ValueError(f"{context} SHA-256 must be explicit.")
    try:
        resolution = resolve_runtime_source(path_value, checksum_value)
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(f"{context} checksum mismatch: {exc}") from exc
    return resolution.runtime_path


@dataclass(frozen=True)
class ExactIlkParameters:
    """One exact Maker ilk retained beneath a simulator collateral family."""

    identifier: str
    quiet_mature_debt_weight: Decimal
    pool_rows: int
    liquidation_ratio: Decimal
    liquidation_penalty_rate: Decimal
    debt_ceiling_dai: Decimal
    minimum_debt_dai: Decimal


@dataclass(frozen=True)
class CollateralFamilyInput:
    """Frozen input ownership and risk settings for one simulator family."""

    name: str
    evidence_status: str
    simulator_collateral_name: str
    underlying_asset: str
    initial_price_usd: Decimal
    liquidation_ratio: Decimal
    liquidation_penalty_rate: Decimal
    max_close_factor: Decimal
    quiet_mature_family_debt_share: Decimal | None
    initialisation: Mapping[str, Any]
    exact_ilks: tuple[ExactIlkParameters, ...]
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class FinalCollateralRegistry:
    """Validated final collateral-family registry."""

    path: Path
    checksum: str
    identifier: str
    runtime_adopted: bool
    family_order: tuple[str, ...]
    families: tuple[CollateralFamilyInput, ...]

    @property
    def by_family(self) -> dict[str, CollateralFamilyInput]:
        return {family.name: family for family in self.families}


@dataclass(frozen=True)
class PortfolioInput:
    """One exact final portfolio composition."""

    identifier: str
    description: str
    status: str
    target_debt_shares: Mapping[str, Decimal]
    expected_vault_counts: Mapping[str, int]


@dataclass(frozen=True)
class FinalPortfolioRegistry:
    """Validated five-portfolio registry."""

    path: Path
    checksum: str
    identifier: str
    runtime_adopted: bool
    family_order: tuple[str, ...]
    total_vaults: int
    total_debt_dai: Decimal
    common_system_target_collateral_ratio: Decimal
    reference_seed_registry_checksum: str
    portfolios: tuple[PortfolioInput, ...]

    @property
    def by_identifier(self) -> dict[str, PortfolioInput]:
        return {portfolio.identifier: portfolio for portfolio in self.portfolios}


@dataclass(frozen=True)
class ShockCollateralRule:
    """One family-specific component of a registered shock."""

    family: str
    rule: str
    magnitude: Decimal | None
    status: str | None
    price_floor: Decimal | None
    duration_hours: int | None


@dataclass(frozen=True)
class ShockInput:
    """One pre-registered final shock definition."""

    identifier: str
    description: str
    rules: tuple[ShockCollateralRule, ...]
    principal_recovery_path_id: str | None
    adverse_recovery_path_id: str | None


@dataclass(frozen=True)
class FinalShockRegistry:
    """Validated seven-shock registry and result-blind derivation rules."""

    path: Path
    checksum: str
    identifier: str
    runtime_adopted: bool
    family_order: tuple[str, ...]
    onset_hour: int
    exclusions: Mapping[str, Mapping[str, str]]
    tail_quantile: Decimal
    joint_lambda: Decimal
    shocks: tuple[ShockInput, ...]

    @property
    def by_identifier(self) -> dict[str, ShockInput]:
        return {shock.identifier: shock for shock in self.shocks}


@dataclass(frozen=True)
class IntegratedMulticollateralProfile:
    """Dormant profile joining the final registries and frozen input owners."""

    path: Path
    checksum: str
    identifier: str
    mode: str
    experiment_ready: bool
    runtime_adopted: bool
    registry_paths: Mapping[str, Path]
    registry_checksums: Mapping[str, str]
    total_vaults: int
    total_debt_dai: Decimal
    common_system_target_collateral_ratio: Decimal
    reference_seed_registry_checksum: str
    maximum_liquidations_per_step: int
    keeper_capacity_semantics: str
    keeper_hurdle_profile_id: str
    confidence_scenario_id: str
    confidence_registry_identity: str
    oracle_delay_steps: int
    market_pool_path: Path
    market_pool_sha256: str | None
    market_manifest_path: Path
    market_manifest_sha256: str | None
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class ResolvedMulticollateralInputs:
    """Fully validated deterministic selection from the dormant registries."""

    profile: IntegratedMulticollateralProfile
    collateral_registry: FinalCollateralRegistry
    portfolio_registry: FinalPortfolioRegistry
    shock_registry: FinalShockRegistry
    portfolio: PortfolioInput
    shock: ShockInput | None
    vault_counts: Mapping[str, int]
    target_family_debt_dai: Mapping[str, Decimal]


def _parse_exact_ilks(raw: Any, family_name: str) -> tuple[ExactIlkParameters, ...]:
    if not isinstance(raw, dict):
        raise ValueError(f"{family_name} exact_ilks must be a mapping.")
    ilks: list[ExactIlkParameters] = []
    for identifier, values in raw.items():
        if not isinstance(values, dict):
            raise ValueError(f"{identifier} settings must be a mapping.")
        ilks.append(
            ExactIlkParameters(
                identifier=str(identifier),
                quiet_mature_debt_weight=_decimal(
                    values["quiet_mature_debt_weight"],
                    f"{identifier} quiet-mature weight",
                ),
                pool_rows=int(values["pool_rows"]),
                liquidation_ratio=_decimal(
                    values["liquidation_ratio"], f"{identifier} liquidation ratio"
                ),
                liquidation_penalty_rate=_decimal(
                    values["liquidation_penalty_rate"],
                    f"{identifier} liquidation penalty",
                ),
                debt_ceiling_dai=_decimal(
                    values["debt_ceiling_dai"], f"{identifier} debt ceiling"
                ),
                minimum_debt_dai=_decimal(
                    values["minimum_debt_dai"], f"{identifier} minimum debt"
                ),
            )
        )
    if ilks:
        weight = sum((ilk.quiet_mature_debt_weight for ilk in ilks), Decimal(0))
        if abs(weight - Decimal(1)) > Decimal("1e-15"):
            raise ValueError(f"{family_name} exact-ilk weights must sum to one.")
    return tuple(ilks)


def load_final_collateral_registry(
    path: Path | str = DEFAULT_COLLATERAL_REGISTRY_PATH,
) -> FinalCollateralRegistry:
    """Load and validate empirical family owners and the explicit stable proxy."""
    resolved, raw = _load_yaml(path)
    family_order = tuple(raw.get("family_order", ()))
    if family_order != FAMILY_ORDER:
        raise ValueError(f"Collateral family order must be exactly {FAMILY_ORDER}.")
    family_payload = _ordered_mapping(raw.get("families"), FAMILY_ORDER, "families")
    families: list[CollateralFamilyInput] = []
    for name, values in family_payload.items():
        if not isinstance(values, dict):
            raise ValueError(f"{name} family definition must be a mapping.")
        initialisation = values.get("initialisation")
        provenance = values.get("provenance")
        if not isinstance(initialisation, dict) or not isinstance(provenance, dict):
            raise ValueError(f"{name} ownership and provenance must be explicit.")
        family = CollateralFamilyInput(
            name=name,
            evidence_status=str(values["evidence_status"]),
            simulator_collateral_name=str(values["simulator_collateral_name"]),
            underlying_asset=str(values["underlying_asset"]),
            initial_price_usd=_decimal(values["initial_price_usd"], f"{name} price"),
            liquidation_ratio=_decimal(
                values["liquidation_ratio"], f"{name} liquidation ratio"
            ),
            liquidation_penalty_rate=_decimal(
                values["liquidation_penalty_rate"], f"{name} liquidation penalty"
            ),
            max_close_factor=_decimal(
                values["max_close_factor"], f"{name} close factor"
            ),
            quiet_mature_family_debt_share=_optional_decimal(
                values.get("quiet_mature_family_debt_share"),
                f"{name} quiet-mature share",
            ),
            initialisation=dict(initialisation),
            exact_ilks=_parse_exact_ilks(values.get("exact_ilks"), name),
            provenance=dict(provenance),
        )
        expected_simulator_name = "BTC" if name == "WBTC" else name
        if family.simulator_collateral_name != expected_simulator_name:
            raise ValueError(
                f"{name} simulator collateral name must be "
                f"{expected_simulator_name}."
            )
        if family.initial_price_usd <= 0 or family.liquidation_ratio <= 1:
            raise ValueError(f"{name} price and liquidation ratio must be positive.")
        if not Decimal(0) <= family.liquidation_penalty_rate:
            raise ValueError(f"{name} liquidation penalty must be non-negative.")
        if not Decimal(0) < family.max_close_factor <= Decimal(1):
            raise ValueError(f"{name} close factor must lie in (0, 1].")
        if name in {"ETH", "WBTC"}:
            if family.evidence_status != "empirical" or not family.exact_ilks:
                raise ValueError(f"{name} must retain its empirical exact-ilk owner.")
            _validate_frozen_file(
                initialisation["pool_path"],
                initialisation["pool_sha256"],
                f"{name} vault pool",
            )
            _validate_frozen_file(
                provenance["protocol_hourly_path"],
                provenance["protocol_hourly_sha256"],
                f"{name} protocol panel",
            )
            _validate_frozen_file(
                provenance["candidate_path"],
                provenance["candidate_sha256"],
                f"{name} candidate evidence",
            )
        else:
            if family.evidence_status != "counterfactual_stable_proxy":
                raise ValueError("STABLE must be labelled counterfactual_stable_proxy.")
            if family.exact_ilks:
                raise ValueError("STABLE must not claim an empirical exact ilk.")
            if initialisation.get("mode") != "stylised_parametric":
                raise ValueError("STABLE must retain its stylised parameter owner.")
            if initialisation.get("empirical_pool_used") is not False:
                raise ValueError("STABLE must not use the ETH/WBTC empirical pool.")
            # These hashes freeze the starting-parent implementation identity.
            # Additive model work may coexist in the working tree, so the
            # current source bytes are not misrepresented as that identity.
            for owner in ("collateral_owner", "vault_owner"):
                _repository_path(provenance[f"{owner}_path"], f"STABLE {owner}")
                digest = provenance.get(f"{owner}_sha256")
                if not isinstance(digest, str) or len(digest) != 64:
                    raise ValueError(f"STABLE {owner} identity must be a SHA-256.")
        families.append(family)
    return FinalCollateralRegistry(
        path=resolved,
        checksum=_sha256_file(resolved),
        identifier=str(raw["registry_id"]),
        runtime_adopted=bool(raw["runtime_adopted"]),
        family_order=family_order,
        families=tuple(families),
    )


def largest_remainder_counts(
    shares: Mapping[str, Decimal | float | str],
    total_count: int,
    family_order: Sequence[str] = FAMILY_ORDER,
) -> dict[str, int]:
    """Allocate integer counts deterministically by Hamilton's method."""
    order = tuple(family_order)
    if tuple(shares) != order:
        raise ValueError(f"Shares must be supplied in family order {order}.")
    if total_count < 0:
        raise ValueError("total_count must be non-negative.")
    decimals = {name: _decimal(shares[name], f"{name} share") for name in order}
    if any(value < 0 for value in decimals.values()):
        raise ValueError("Shares must be non-negative.")
    if abs(sum(decimals.values(), Decimal(0)) - Decimal(1)) > Decimal("1e-15"):
        raise ValueError("Shares must sum to one.")
    quotas = {name: decimals[name] * total_count for name in order}
    counts = {
        name: int(quotas[name].to_integral_value(rounding=ROUND_FLOOR))
        for name in order
    }
    remaining = total_count - sum(counts.values())
    ranking = sorted(
        order,
        key=lambda name: (
            -(quotas[name] - Decimal(counts[name])),
            order.index(name),
        ),
    )
    for name in ranking[:remaining]:
        counts[name] += 1
    return counts


def load_final_portfolio_registry(
    path: Path | str = DEFAULT_PORTFOLIO_REGISTRY_PATH,
) -> FinalPortfolioRegistry:
    """Load the exact five registered portfolio compositions."""
    resolved, raw = _load_yaml(path)
    family_order = tuple(raw.get("family_order", ()))
    if family_order != FAMILY_ORDER:
        raise ValueError(f"Portfolio family order must be exactly {FAMILY_ORDER}.")
    total_vaults = int(raw["total_vaults"])
    portfolio_payload = _ordered_mapping(
        raw.get("portfolios"), PORTFOLIO_ORDER, "portfolios"
    )
    portfolios: list[PortfolioInput] = []
    for identifier, values in portfolio_payload.items():
        shares_raw = _ordered_mapping(
            values.get("target_debt_shares"),
            FAMILY_ORDER,
            f"{identifier} target_debt_shares",
        )
        counts_raw = _ordered_mapping(
            values.get("expected_vault_counts"),
            FAMILY_ORDER,
            f"{identifier} expected_vault_counts",
        )
        shares = {
            name: _decimal(shares_raw[name], f"{identifier} {name} share")
            for name in FAMILY_ORDER
        }
        counts = {name: int(counts_raw[name]) for name in FAMILY_ORDER}
        if largest_remainder_counts(shares, total_vaults, FAMILY_ORDER) != counts:
            raise ValueError(
                f"{identifier} expected counts do not follow largest remainders."
            )
        portfolios.append(
            PortfolioInput(
                identifier=identifier,
                description=str(values["description"]),
                status=str(values["status"]),
                target_debt_shares=shares,
                expected_vault_counts=counts,
            )
        )
    ratio_rule = raw.get("collateral_ratio_rule")
    if not isinstance(ratio_rule, dict):
        raise ValueError("collateral_ratio_rule must be explicit.")
    return FinalPortfolioRegistry(
        path=resolved,
        checksum=_sha256_file(resolved),
        identifier=str(raw["registry_id"]),
        runtime_adopted=bool(raw["runtime_adopted"]),
        family_order=family_order,
        total_vaults=total_vaults,
        total_debt_dai=_decimal(raw["total_debt_dai"], "total debt"),
        common_system_target_collateral_ratio=_decimal(
            ratio_rule["common_system_target"], "common collateral ratio"
        ),
        reference_seed_registry_checksum=str(
            ratio_rule["reference_seed_registry_checksum"]
        ),
        portfolios=tuple(portfolios),
    )


def load_final_shock_registry(
    path: Path | str = DEFAULT_SHOCK_REGISTRY_PATH,
) -> FinalShockRegistry:
    """Load the exact seven result-blind shock definitions."""
    resolved, raw = _load_yaml(path)
    family_order = tuple(raw.get("family_order", ()))
    if family_order != FAMILY_ORDER:
        raise ValueError(f"Shock family order must be exactly {FAMILY_ORDER}.")
    shock_payload = _ordered_mapping(raw.get("shocks"), SHOCK_ORDER, "shocks")
    shocks: list[ShockInput] = []
    for identifier, values in shock_payload.items():
        rule_payload = _ordered_mapping(
            values.get("rules"), FAMILY_ORDER, f"{identifier} rules"
        )
        rules: list[ShockCollateralRule] = []
        for family, rule in rule_payload.items():
            if not isinstance(rule, dict):
                raise ValueError(f"{identifier}/{family} rule must be a mapping.")
            magnitude = _optional_decimal(
                rule.get("magnitude"), f"{identifier}/{family} magnitude"
            )
            if magnitude is None and rule.get("status") != "pending_result_blind_derivation":
                raise ValueError(
                    f"{identifier}/{family} null magnitude must remain pending."
                )
            rules.append(
                ShockCollateralRule(
                    family=family,
                    rule=str(rule["rule"]),
                    magnitude=magnitude,
                    status=None if rule.get("status") is None else str(rule["status"]),
                    price_floor=_optional_decimal(
                        rule.get("price_floor"),
                        f"{identifier}/{family} price floor",
                    ),
                    duration_hours=(
                        None
                        if rule.get("duration_hours") is None
                        else int(rule["duration_hours"])
                    ),
                )
            )
        shocks.append(
            ShockInput(
                identifier=identifier,
                description=str(values["description"]),
                rules=tuple(rules),
                principal_recovery_path_id=(
                    None
                    if values.get("principal_recovery_path_id") is None
                    else str(values["principal_recovery_path_id"])
                ),
                adverse_recovery_path_id=(
                    None
                    if values.get("adverse_recovery_path_id") is None
                    else str(values["adverse_recovery_path_id"])
                ),
            )
        )
    exclusions = raw.get("exclusions")
    tail = raw.get("volatile_tail_rule")
    joint = raw.get("joint_empirical_stress_rule")
    if not all(isinstance(value, dict) for value in (exclusions, tail, joint)):
        raise ValueError("Shock exclusions and derivation rules must be mappings.")
    expected_exclusions = {
        "ftx": {
            "start_utc": "2022-11-01T00:00:00Z",
            "end_exclusive_utc": "2022-11-21T00:00:00Z",
        },
        "usdc_svb": {
            "start_utc": "2023-03-06T00:00:00Z",
            "end_exclusive_utc": "2023-03-20T00:00:00Z",
        },
    }
    if exclusions != expected_exclusions:
        raise ValueError("Final-validation exclusions differ from pre-registration.")
    if int(raw["onset_hour"]) != 24:
        raise ValueError("All final shocks must begin at hour 24.")
    if str(tail["estimator"]) != "nearest_rank" or int(tail["horizon_hours"]) != 24:
        raise ValueError("Tail rule must be the registered 24-hour nearest rank.")
    if _decimal(tail["quantile"], "tail quantile") != Decimal("0.01"):
        raise ValueError("Tail quantile must equal q01.")
    if _decimal(joint["gas_weight_lambda"], "joint gas lambda") != Decimal("0.5"):
        raise ValueError("Joint stress lambda must equal 0.5.")
    if str(joint["score"]) != (
        "standardised_ETH_downside + standardised_WBTC_downside + "
        "0.5 * standardised_gas"
    ):
        raise ValueError("Joint empirical stress score differs.")
    moderate = shocks[4].rules[2]
    severe = shocks[5].rules[2]
    joint_stable = shocks[6].rules[2]
    if (
        moderate.price_floor != Decimal("0.95")
        or moderate.duration_hours != 72
        or severe.price_floor != Decimal("0.90")
        or severe.duration_hours != 168
        or joint_stable.price_floor != Decimal("0.90")
        or joint_stable.duration_hours != 168
    ):
        raise ValueError("Stable-depeg floors or durations differ.")
    recovery = raw.get("volatile_recovery_paths")
    if not isinstance(recovery, dict):
        raise ValueError("Volatile recovery ownership must be explicit.")
    if (
        recovery.get("principal") != "full_week"
        or recovery.get("adverse") != "persistent_trough"
    ):
        raise ValueError("Volatile principal/adverse recovery paths differ.")
    _validate_frozen_file(
        recovery["source_path"],
        recovery["source_sha256"],
        "volatile recovery owner",
    )
    for shock in (*shocks[:4], shocks[6]):
        if (
            shock.principal_recovery_path_id != "full_week"
            or shock.adverse_recovery_path_id != "persistent_trough"
        ):
            raise ValueError(
                f"{shock.identifier} must retain principal and adverse recoveries."
            )
    return FinalShockRegistry(
        path=resolved,
        checksum=_sha256_file(resolved),
        identifier=str(raw["registry_id"]),
        runtime_adopted=bool(raw["runtime_adopted"]),
        family_order=family_order,
        onset_hour=int(raw["onset_hour"]),
        exclusions=dict(exclusions),
        tail_quantile=Decimal("0.01"),
        joint_lambda=Decimal("0.5"),
        shocks=tuple(shocks),
    )


def load_integrated_multicollateral_profile(
    path: Path | str = DEFAULT_PROFILE_PATH,
) -> IntegratedMulticollateralProfile:
    """Load the dormant final profile and checksum every frozen owner."""
    resolved, raw = _load_yaml(path)
    if raw.get("profile_identifier") != PROFILE_IDENTIFIER:
        raise ValueError("Unexpected final multi-collateral profile identifier.")
    if raw.get("mode") != "empirical":
        raise ValueError("Final multi-collateral profile must use empirical mode.")
    registry_paths_raw = raw.get("registry_paths")
    registry_checksums = raw.get("registry_checksums")
    if not isinstance(registry_paths_raw, dict) or not isinstance(
        registry_checksums, dict
    ):
        raise ValueError("Registry paths and checksums must be explicit.")
    if tuple(registry_paths_raw) != ("collateral", "portfolio", "shock"):
        raise ValueError("Registry path order must be collateral, portfolio, shock.")
    paths = {
        owner: _validate_frozen_file(
            registry_paths_raw[owner],
            registry_checksums.get(owner),
            f"{owner} registry",
        )
        for owner in registry_paths_raw
    }
    population = raw.get("population")
    keeper = raw.get("keeper")
    confidence = raw.get("confidence")
    oracle = raw.get("oracle")
    market = raw.get("market_process")
    others = raw.get("other_empirical_owners")
    if not all(
        isinstance(value, dict)
        for value in (population, keeper, confidence, oracle, market, others)
    ):
        raise ValueError("All final empirical owners must be explicit mappings.")
    frozen_pairs = (
        ("vault pool", population["vault_pool_path"], population["vault_pool_sha256"]),
        (
            "vault pool manifest",
            population["vault_pool_manifest_path"],
            population["vault_pool_manifest_sha256"],
        ),
        (
            "keeper configuration",
            keeper["configuration_path"],
            keeper["configuration_sha256"],
        ),
        (
            "keeper evidence",
            keeper["evidence_registry_path"],
            keeper["evidence_registry_sha256"],
        ),
        (
            "confidence registry",
            confidence["registry_path"],
            confidence["registry_file_sha256"],
        ),
        (
            "source environment pool",
            market["source_environment_pool_path"],
            market["source_environment_pool_sha256"],
        ),
        (
            "source market panel",
            market["source_market_panel_path"],
            market["source_market_panel_sha256"],
        ),
        (
            "keeper gas pool",
            others["keeper_gas_pool_path"],
            others["keeper_gas_pool_sha256"],
        ),
        (
            "liquidation arrival pool",
            others["liquidation_arrival_pool_path"],
            others["liquidation_arrival_pool_sha256"],
        ),
    )
    for context, owner_path, owner_checksum in frozen_pairs:
        _validate_frozen_file(owner_path, owner_checksum, context)
    market_pool_path = _repository_path(
        market["pool_path"], "final market pool", must_exist=False
    )
    market_manifest_path = _repository_path(
        market["manifest_path"], "final market manifest", must_exist=False
    )
    pool_checksum = market.get("pool_sha256")
    manifest_checksum = market.get("manifest_sha256")
    if pool_checksum is not None:
        _validate_frozen_file(market["pool_path"], pool_checksum, "final market pool")
    if manifest_checksum is not None:
        _validate_frozen_file(
            market["manifest_path"], manifest_checksum, "final market manifest"
        )
    profile = IntegratedMulticollateralProfile(
        path=resolved,
        checksum=_sha256_file(resolved),
        identifier=PROFILE_IDENTIFIER,
        mode="empirical",
        experiment_ready=bool(raw["experiment_ready"]),
        runtime_adopted=bool(raw["runtime_adopted"]),
        registry_paths=paths,
        registry_checksums=dict(registry_checksums),
        total_vaults=int(population["total_vaults"]),
        total_debt_dai=_decimal(population["total_debt_dai"], "profile total debt"),
        common_system_target_collateral_ratio=_decimal(
            population["common_system_target_collateral_ratio"],
            "profile common collateral ratio",
        ),
        reference_seed_registry_checksum=str(
            population["reference_seed_registry_checksum"]
        ),
        maximum_liquidations_per_step=int(
            keeper["maximum_liquidations_per_step"]
        ),
        keeper_capacity_semantics=str(keeper["capacity_semantics"]),
        keeper_hurdle_profile_id=str(keeper["hurdle_profile_id"]),
        confidence_scenario_id=str(confidence["scenario_id"]),
        confidence_registry_identity=str(
            confidence["registry_identity_sha256"]
        ),
        oracle_delay_steps=int(oracle["delay_steps"]),
        market_pool_path=market_pool_path,
        market_pool_sha256=pool_checksum,
        market_manifest_path=market_manifest_path,
        market_manifest_sha256=manifest_checksum,
        raw=raw,
    )
    if profile.runtime_adopted:
        raise ValueError("Final multi-collateral input profile must remain non-adopted.")
    if (
        profile.total_vaults != 500
        or profile.total_debt_dai != Decimal("2500000.0")
        or profile.common_system_target_collateral_ratio
        != Decimal("3.6089387701260205")
    ):
        raise ValueError("Fixed population semantics differ from pre-registration.")
    if (
        profile.maximum_liquidations_per_step != 26
        or profile.keeper_capacity_semantics != "system_wide_shared_capacity"
        or profile.keeper_hurdle_profile_id != "direct_cost_only"
    ):
        raise ValueError("Shared keeper capacity semantics differ.")
    if profile.confidence_scenario_id != "stage1_only":
        raise ValueError("Final profile must retain Stage 1 confidence only.")
    if profile.confidence_registry_identity != (
        "d455306fd7b7553f113099b6d51f962939d8b4793439a02c4638c646a63b25da"
    ):
        raise ValueError("Protected confidence-registry identity differs.")
    if profile.oracle_delay_steps != 0:
        raise ValueError("Final profile must retain transparent zero-delay oracle.")
    return profile


def resolve_multicollateral_inputs(
    portfolio_id: str,
    shock_id: str | None = None,
    profile_path: Path | str = DEFAULT_PROFILE_PATH,
) -> ResolvedMulticollateralInputs:
    """Resolve one deterministic portfolio/shock selection without adoption."""
    profile = load_integrated_multicollateral_profile(profile_path)
    collateral = load_final_collateral_registry(profile.registry_paths["collateral"])
    portfolios = load_final_portfolio_registry(profile.registry_paths["portfolio"])
    shocks = load_final_shock_registry(profile.registry_paths["shock"])
    if any(
        registry.runtime_adopted for registry in (collateral, portfolios, shocks)
    ):
        raise ValueError("Final input registries must remain non-adopted.")
    try:
        portfolio = portfolios.by_identifier[portfolio_id]
    except KeyError as exc:
        raise ValueError(f"Unknown final portfolio: {portfolio_id}.") from exc
    shock: ShockInput | None = None
    if shock_id is not None:
        try:
            shock = shocks.by_identifier[shock_id]
        except KeyError as exc:
            raise ValueError(f"Unknown final shock: {shock_id}.") from exc
    counts = largest_remainder_counts(
        portfolio.target_debt_shares,
        profile.total_vaults,
        FAMILY_ORDER,
    )
    if counts != portfolio.expected_vault_counts:
        raise ValueError("Resolved vault counts differ from the frozen portfolio.")
    targets = {
        family: profile.total_debt_dai * portfolio.target_debt_shares[family]
        for family in FAMILY_ORDER
    }
    return ResolvedMulticollateralInputs(
        profile=profile,
        collateral_registry=collateral,
        portfolio_registry=portfolios,
        shock_registry=shocks,
        portfolio=portfolio,
        shock=shock,
        vault_counts=counts,
        target_family_debt_dai=targets,
    )


FINAL_MARKET_COLUMNS = (
    "pool_row_id",
    "source_pool_row_id",
    "source_row",
    "timestamp_utc",
    "calibration_pool_label",
    "regime_label",
    "is_calibration",
    "return_observation_valid",
    "calibration_segment_id",
    "eth_price_usd",
    "wbtc_price_usd",
    "usdc_price_usd",
    "eth_log_return",
    "wbtc_log_return",
    "usdc_log_return",
    "eth_24h_log_return",
    "wbtc_24h_log_return",
    "usdc_24h_log_return",
    "median_effective_gas_price_gwei",
    "p90_effective_gas_price_gwei",
    "p99_effective_gas_price_gwei",
    "target_normalised_block_utilisation",
)


def build_final_market_pool(
    environment_pool_path: Path | str = DEFAULT_ENVIRONMENT_POOL_PATH,
    phase1a_panel_path: Path | str = DEFAULT_MARKET_PANEL_PATH,
) -> pd.DataFrame:
    """Build the deterministic result-blind multi-collateral market pool locally."""
    environment_path = Path(environment_pool_path)
    market_path = Path(phase1a_panel_path)
    if _sha256_file(environment_path) != EXPECTED_ENVIRONMENT_POOL_SHA256:
        raise ValueError("Source environment-pool checksum differs.")
    if _sha256_file(market_path) != EXPECTED_MARKET_PANEL_SHA256:
        raise ValueError("Source Phase 1A market-panel checksum differs.")
    environment = pd.read_csv(environment_path)
    market = pd.read_csv(
        market_path,
        usecols=("timestamp_utc", "usdc_price_usd", "usdc_log_return"),
    )
    environment["timestamp_utc"] = pd.to_datetime(
        environment["timestamp_utc"], utc=True, errors="raise"
    )
    market["timestamp_utc"] = pd.to_datetime(
        market["timestamp_utc"], utc=True, errors="raise"
    )
    if environment["timestamp_utc"].duplicated().any() or market[
        "timestamp_utc"
    ].duplicated().any():
        raise ValueError("Source market timestamps must be unique.")
    pool = environment.merge(
        market,
        on="timestamp_utc",
        how="left",
        validate="one_to_one",
    )
    if pool[["usdc_price_usd"]].isna().any().any():
        raise ValueError("USDC price coverage is incomplete.")
    excluded = (
        ((pool["timestamp_utc"] >= FTX_START) & (pool["timestamp_utc"] < FTX_END))
        | ((pool["timestamp_utc"] >= SVB_START) & (pool["timestamp_utc"] < SVB_END))
    )
    pool = pool.loc[~excluded].copy()
    pool = pool.sort_values("timestamp_utc", kind="stable").reset_index(drop=True)
    pool["source_pool_row_id"] = pool["pool_row_id"]
    pool["pool_row_id"] = np.arange(len(pool), dtype=np.int64)
    starts = pool["timestamp_utc"].diff().ne(pd.Timedelta(hours=1))
    pool["calibration_segment_id"] = starts.cumsum().astype(np.int64) - 1
    for column in ("eth_log_return", "wbtc_log_return", "usdc_log_return"):
        pool.loc[starts, column] = np.nan
    pool["return_observation_valid"] = (
        pool[["eth_log_return", "wbtc_log_return", "usdc_log_return"]]
        .notna()
        .all(axis=1)
    )
    for family, column in (
        ("eth", "eth_log_return"),
        ("wbtc", "wbtc_log_return"),
        ("usdc", "usdc_log_return"),
    ):
        pool[f"{family}_24h_log_return"] = pool.groupby(
            "calibration_segment_id", sort=False
        )[column].transform(
            lambda values: values.rolling(window=24, min_periods=24).sum()
        )
    pool["timestamp_utc"] = pool["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    result = pool.loc[:, FINAL_MARKET_COLUMNS].copy()
    _validate_final_market_frame(result)
    return result


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    buffer = StringIO()
    frame.to_csv(
        buffer,
        index=False,
        lineterminator="\n",
        float_format="%.12g",
    )
    return buffer.getvalue().encode("utf-8")


def build_final_market_pool_manifest(
    pool: pd.DataFrame,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Build, and optionally atomically persist, compact pool provenance."""
    _validate_final_market_frame(pool)
    payload = {
        "artefact": "final_multicollateral_market_gas_pool",
        "version": 1,
        "runtime_adopted": False,
        "rows": int(len(pool)),
        "columns": list(pool.columns),
        "output_path": str(
            DEFAULT_FINAL_MARKET_POOL_PATH.relative_to(REPOSITORY_ROOT)
        ),
        "output_sha256": sha256(_csv_bytes(pool)).hexdigest(),
        "source_checksums": {
            str(DEFAULT_ENVIRONMENT_POOL_PATH.relative_to(REPOSITORY_ROOT)): (
                EXPECTED_ENVIRONMENT_POOL_SHA256
            ),
            str(DEFAULT_MARKET_PANEL_PATH.relative_to(REPOSITORY_ROOT)): (
                EXPECTED_MARKET_PANEL_SHA256
            ),
        },
        "excluded_intervals": {
            "ftx": {
                "start_utc": FTX_START.isoformat().replace("+00:00", "Z"),
                "end_exclusive_utc": FTX_END.isoformat().replace("+00:00", "Z"),
            },
            "usdc_svb": {
                "start_utc": SVB_START.isoformat().replace("+00:00", "Z"),
                "end_exclusive_utc": SVB_END.isoformat().replace("+00:00", "Z"),
            },
        },
        "tail_derivation": {
            "horizon_hours": 24,
            "estimator": "nearest_rank",
            "quantile": 0.01,
            "computed_within_contiguous_segments": True,
        },
    }
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    return payload


def _validate_final_market_frame(frame: pd.DataFrame) -> None:
    if tuple(frame.columns) != FINAL_MARKET_COLUMNS:
        raise ValueError("Final multi-collateral market-pool schema differs.")
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("Final market-pool timestamps must be unique and ordered.")
    excluded = (
        ((timestamps >= FTX_START) & (timestamps < FTX_END))
        | ((timestamps >= SVB_START) & (timestamps < SVB_END))
    )
    if excluded.any():
        raise ValueError("Final-validation intervals must not enter the pool.")
    if frame["pool_row_id"].tolist() != list(range(len(frame))):
        raise ValueError("Final pool row identifiers must be contiguous.")
    numeric = (
        "eth_price_usd",
        "wbtc_price_usd",
        "usdc_price_usd",
        "median_effective_gas_price_gwei",
        "p90_effective_gas_price_gwei",
        "p99_effective_gas_price_gwei",
        "target_normalised_block_utilisation",
    )
    values = frame.loc[:, numeric].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("Final market-pool level variables must be finite.")
    if (values[["eth_price_usd", "wbtc_price_usd", "usdc_price_usd"]] <= 0).any().any():
        raise ValueError("Final market-pool prices must be positive.")


def load_final_market_pool(
    path: Path | str = DEFAULT_FINAL_MARKET_POOL_PATH,
    expected_sha256: str | None = None,
) -> pd.DataFrame:
    """Load and validate a frozen final market pool, optionally by checksum."""
    resolved = Path(path)
    if expected_sha256 is not None:
        observed = _sha256_file(resolved)
        if observed != expected_sha256:
            raise ValueError(
                f"Final market-pool checksum mismatch: expected {expected_sha256}, "
                f"observed {observed}."
            )
    frame = pd.read_csv(resolved)
    _validate_final_market_frame(frame)
    return frame
