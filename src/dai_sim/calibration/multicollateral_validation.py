"""Result-blind final multi-collateral input and integration validation.

This module freezes candidate inputs and validates their integration contract.
It is deliberately separate from the experiment runners: it does not rank
portfolios or shocks, alter a production default, or execute a substantive
multi-collateral experiment.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from dai_sim.calibration.event_simulation import load_stage1_owners
from dai_sim.calibration.integrated_eth_validation import (
    EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
    EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
    VALIDATION_MANIFEST,
    _atomic_bytes,
    _csv_bytes,
    _payload_sha256,
    _pretty_json,
    _relative,
)
from dai_sim.calibration.market import sample_residual_blocks
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file
from dai_sim.inputs.gas import component_gas_costs
from dai_sim.inputs.integrated_profile import (
    EXPECTED_KEEPER_CONFIGURATION_SHA256,
    EXPECTED_KEEPER_REGISTRY_SHA256,
    EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
    EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
    resolve_integrated_empirical_eth_profile,
)
from dai_sim.inputs.liquidations import (
    LiquidationDemandProcess,
)
from dai_sim.inputs.multicollateral import (
    build_final_market_pool,
    largest_remainder_counts,
    load_final_market_pool,
    resolve_multicollateral_inputs,
)
from dai_sim.inputs.vaults import load_pool
from dai_sim.model.collateral import CollateralConfig, CollateralPortfolioConfig
from dai_sim.model.liquidation import (
    LiquidationConfig,
    execute_keeper_liquidation,
    rank_liquidation_candidates,
)
from dai_sim.model.market import coefficient_normalised_market_response
from dai_sim.model.vault import Vault


SCHEMA_VERSION = 1
PARENT_COMMIT = "8d5ea2829f1481cc57e2760422d11fd452905bad"
PARENT_SUBJECT = "Harden experiment infrastructure"
PROFILE_ID = "empirical_integrated_multicollateral"
VALIDATION_OWNER = "multicollateral_integration_validation"
VALIDATION_NAMESPACE = "multicollateral-integration-v1"
REFERENCE_NAMESPACE = "multicollateral-integration-reference-v1"
FAMILY_ORDER = ("ETH", "WBTC", "STABLE")
MODEL_FAMILY = {"ETH": "ETH", "WBTC": "BTC", "STABLE": "STABLE"}
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
VAULT_COUNT = 500
TOTAL_DEBT_DAI = 2_500_000.0
TARGET_SYSTEM_COLLATERAL_RATIO = 3.6089387701260205
INITIALISATIONS_PER_PORTFOLIO = 256
DYNAMIC_REPLICATIONS_PER_PORTFOLIO = 32
DYNAMIC_HOURS = 168
SHARED_CAPACITY = 26
SMOKE_HOURS_MAXIMUM = 48
DEBT_TOLERANCE = 1e-6
SHARE_TOLERANCE = 1e-10
RATIO_TOLERANCE = 1e-10
MINIMUM_FREE_BYTES = 10 * 1024**3
OUTPUT_CAP_BYTES = 300 * 1024**2

COLLATERAL_REGISTRY_PATH = (
    REPOSITORY_ROOT / "config/protocol/final_collateral_registry.yaml"
)
PORTFOLIO_REGISTRY_PATH = (
    REPOSITORY_ROOT / "config/sensitivities/final_portfolio_registry.yaml"
)
SHOCK_REGISTRY_PATH = (
    REPOSITORY_ROOT / "config/sensitivities/final_shock_registry.yaml"
)
PROFILE_PATH = (
    REPOSITORY_ROOT / "config/profiles/empirical_integrated_multicollateral.yaml"
)
EVIDENCE_DIR = (
    REPOSITORY_ROOT
    / "data/provenance/validation/multicollateral_integration"
)
DIAGNOSTIC_ROOT = (
    REPOSITORY_ROOT
    / "outputs/diagnostics/validation/multicollateral_integration"
)
COMPACT_FILENAMES = (
    "multicollateral_integration_specification.json",
    "final_collateral_registry.csv",
    "final_protocol_parameters.csv",
    "final_portfolio_registry.csv",
    "final_shock_registry.csv",
    "multicollateral_initialisation_validation.csv",
    "multicollateral_shared_capacity_validation.csv",
    "multicollateral_dynamic_validation.csv",
    "multicollateral_integration_decision.json",
    "multicollateral_integration_reproducibility.json",
    "multicollateral_integration_benchmark.json",
)
DETERMINISTIC_FILENAMES = COMPACT_FILENAMES[:-1]

PROTECTED_REGRESSIONS = {
    "integrated_eth_profile_identity": (
        "ab68c32a145262bcef07716469d92be09e3d96506383ad16a07d0ba1bad2b34d"
    ),
    "integrated_eth_profile_sha256": (
        "ea0e08f263210af3c3041843537f975ebd886fcf5130c617b0edb189218b3862"
    ),
    "keeper_configuration_sha256": EXPECTED_KEEPER_CONFIGURATION_SHA256,
    "keeper_registry_sha256": EXPECTED_KEEPER_REGISTRY_SHA256,
    "confidence_registry_sha256": (
        "d455306fd7b7553f113099b6d51f962939d8b4793439a02c4638c646a63b25da"
    ),
    "stage1_residual_sequence_sha256": EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
    "stage1_residual_blocks_sha256": EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
    "vault_input_sha256": (
        "5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892"
    ),
    "keeper_gas_input_sha256": (
        "37a5f49f4cc273b9d0d9526609be7f14b91b78939acf26e4dce00b66443e1594"
    ),
    "arrival_input_sha256": (
        "cc29435bb0434237aba438ee98bded77f086704c7400bb5016e2b58703258c8a"
    ),
    "arrival_sequence_sha256": (
        "9fdd5f3b5fb97e2dd41d0201bad34909ad05e423ad6b52f65219f49f02a1c7ed"
    ),
    "legacy_smoke_sha256": (
        "5f7bb277d1a9d6c1c91576645986fc717f7176253977360b47ebd4ce6ed5fa64"
    ),
    "empirical_smoke_sha256": (
        "078cf6713e1d5a69f8c9a5e274809b2f8326023100070960493ff44a569bf53b"
    ),
    "hurdle_smoke_sha256": (
        "bbe69f0bb5e7d5be46c871f18ca48b6e4c30cf3dc01bb143ec7e23262f5cfbc1"
    ),
    "multicollateral_smoke_sha256": (
        "a8913dff6e9956c4235b5710468eb32229af7aeb83c4dfb5581e7872435fbbf9"
    ),
    "experiment_1_sha256": (
        "30090453c211f15f8e574000aec075bcb9acda4d7abf1685bdf4b2f28c0395da"
    ),
    "experiment_2_sha256": (
        "f7c9494e9d02011b06cda2fc590e0bd801a3e5a010f23ab8930b5dddba3ac761"
    ),
    "experiment_3_sha256": (
        "1f0207385a8f8741fbcf2326d1c6bfaab484d41a9a2f9406b65ab27868a85c6d"
    ),
    "experiment_4_sha256": (
        "73ccf5d2676c0bb5f3e901399d72d1dd52fbfe7d0f0d43e915e0105b9309f237"
    ),
    "experiment_5_sha256": (
        "b843906b7d2395bc984432704e7a460e85d6636febd1d16b9f853464c5d6c339"
    ),
}


def _seed(namespace: str, replication: int, stream: str) -> int:
    payload = f"{namespace}|{replication}|{stream}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**32)


def seed_registry() -> dict[str, Any]:
    """Return dedicated, non-overlapping validation seed ownership."""
    return {
        "schema_version": 1,
        "registry_id": VALIDATION_NAMESPACE,
        "reference_registry_id": REFERENCE_NAMESPACE,
        "derivation": "sha256(namespace|replication|stream) first 64 bits modulo 2^32",
        "portfolio_order": list(PORTFOLIO_ORDER),
        "initialisations_per_portfolio": INITIALISATIONS_PER_PORTFOLIO,
        "dynamic_replications_per_portfolio": DYNAMIC_REPLICATIONS_PER_PORTFOLIO,
        "streams": [
            "vault_sampling",
            "stable_vault_sampling",
            "market_gas_blocks",
            "keeper_gas_units",
            "liquidation_arrivals",
            "stage1_residual_blocks",
            "shared_capacity_smoke",
        ],
        "existing_experiment_seeds_reused": False,
        "final_validation_seeds_reused": False,
    }


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Configuration must be a mapping: {_relative(path)}.")
    return payload


def _design_payloads() -> tuple[dict[str, Any], ...]:
    return tuple(
        _load_yaml(path)
        for path in (
            COLLATERAL_REGISTRY_PATH,
            PORTFOLIO_REGISTRY_PATH,
            SHOCK_REGISTRY_PATH,
            PROFILE_PATH,
        )
    )


def _family_payload(
    collateral_payload: Mapping[str, Any], family: str
) -> Mapping[str, Any]:
    families = collateral_payload.get("families")
    if not isinstance(families, dict) or family not in families:
        raise ValueError(f"Missing collateral family {family}.")
    value = families[family]
    if not isinstance(value, dict):
        raise ValueError(f"Collateral family {family} must be a mapping.")
    return value


def _portfolio_payload(
    portfolio_payload: Mapping[str, Any], identifier: str
) -> Mapping[str, Any]:
    portfolios = portfolio_payload.get("portfolios")
    if not isinstance(portfolios, dict) or identifier not in portfolios:
        raise ValueError(f"Missing portfolio {identifier}.")
    value = portfolios[identifier]
    if not isinstance(value, dict):
        raise ValueError(f"Portfolio {identifier} must be a mapping.")
    return value


def _quiet_empirical_pool(
    collateral_payload: Mapping[str, Any],
) -> pd.DataFrame:
    eth = _family_payload(collateral_payload, "ETH")
    owner = eth["initialisation"]
    path = REPOSITORY_ROOT / str(owner["pool_path"])
    expected = str(owner["pool_sha256"])
    pool = load_pool(path, expected)
    source_window = str(owner["source_window"])
    selected = pool.loc[
        pool["source_window"].eq(source_window)
        & pool["regime_label"].eq("normal")
        & pool["collateral_family"].isin(["ETH", "WBTC"])
    ].copy()
    if selected.empty:
        raise ValueError("The quiet-mature empirical vault pool is empty.")
    if selected["source_window"].nunique() != 1:
        raise ValueError("More than one empirical source window entered initialisation.")
    if selected["source_window"].str.contains("usdc_svb", case=False).any():
        raise ValueError("USDC/SVB vault observations entered initialisation.")
    return selected.sort_values("pool_row_id", kind="mergesort").reset_index(drop=True)


@dataclass(frozen=True)
class PortfolioInitialisation:
    """One accepted, exactly normalised multi-collateral initial state."""

    portfolio_id: str
    replication: int
    attempt: int
    vaults: tuple[Vault, ...]
    sampled: pd.DataFrame
    family_counts: Mapping[str, int]
    raw_system_collateral_ratio: float
    target_system_collateral_ratio: float
    collateral_scaling_factor: float
    final_system_collateral_ratio: float
    minimum_liquidation_distance: float
    identity: str


def _within_family_ilk_counts(
    family_config: Mapping[str, Any],
    family_count: int,
) -> dict[str, int]:
    ilks = family_config.get("exact_ilks")
    if not isinstance(ilks, dict) or not ilks:
        return {}
    shares = {
        str(ilk): float(values["quiet_mature_debt_weight"])
        for ilk, values in ilks.items()
    }
    return largest_remainder_counts(
        shares=shares,
        total_count=family_count,
        family_order=tuple(ilks),
    )


def _sample_empirical_family(
    *,
    pool: pd.DataFrame,
    family: str,
    family_config: Mapping[str, Any],
    count: int,
    rng: np.random.Generator,
) -> list[dict[str, Any]]:
    if count == 0:
        return []
    ilk_counts = _within_family_ilk_counts(family_config, count)
    rows: list[dict[str, Any]] = []
    for ilk, ilk_count in ilk_counts.items():
        source = pool.loc[pool["ilk"].eq(ilk)]
        if source.empty:
            raise ValueError(f"No empirical rows are available for {ilk}.")
        indexes = rng.choice(
            source.index.to_numpy(dtype=int),
            size=ilk_count,
            replace=True,
        )
        protocol = family_config["exact_ilks"][ilk]
        for index in indexes:
            row = source.loc[int(index)]
            rows.append(
                {
                    "family": family,
                    "model_family": MODEL_FAMILY[family],
                    "exact_ilk": ilk,
                    "source_row_id": str(row["pool_row_id"]),
                    "source_status": "empirical",
                    "raw_debt_dai": float(row["debt_dai"]),
                    "raw_collateral_ratio": float(row["collateral_ratio"]),
                    "liquidation_ratio": float(protocol["liquidation_ratio"]),
                }
            )
    if len(rows) != count:
        raise ValueError(f"{family} empirical allocation count differs.")
    return rows


def _sample_stable_family(
    *,
    family_config: Mapping[str, Any],
    count: int,
    rng: np.random.Generator,
) -> list[dict[str, Any]]:
    if count == 0:
        return []
    owner = family_config["initialisation"]
    if (
        owner.get("mode") != "stylised_parametric"
        or owner.get("empirical_pool_used") is not False
    ):
        raise ValueError("Stable owner is not the explicit counterfactual owner.")
    debts = np.clip(
        rng.normal(
            float(owner["debt_mean_dai"]),
            float(owner["debt_standard_deviation_dai"]),
            size=count,
        ),
        a_min=100.0,
        a_max=None,
    )
    ratios = np.clip(
        rng.normal(
            float(owner["collateral_ratio_mean"]),
            float(owner["collateral_ratio_standard_deviation"]),
            size=count,
        ),
        a_min=(
            float(family_config["liquidation_ratio"])
            + float(owner["minimum_liquidation_buffer"])
        ),
        a_max=None,
    )
    return [
        {
            "family": "STABLE",
            "model_family": "STABLE",
            "exact_ilk": None,
            "source_row_id": f"counterfactual_stable_{index:04d}",
            "source_status": "counterfactual_stable_proxy",
            "raw_debt_dai": float(debt),
            "raw_collateral_ratio": float(ratio),
            "liquidation_ratio": float(family_config["liquidation_ratio"]),
        }
        for index, (debt, ratio) in enumerate(
            zip(debts, ratios, strict=True)
        )
    ]


def _initialisation_identity(frame: pd.DataFrame) -> str:
    columns = [
        "vault_id",
        "family",
        "model_family",
        "exact_ilk",
        "source_row_id",
        "source_status",
        "debt_dai",
        "collateral_ratio",
        "liquidation_ratio",
        "collateral_amount",
    ]
    records = frame.loc[:, columns].where(pd.notna(frame.loc[:, columns]), None)
    return _payload_sha256(records.to_dict(orient="records"))


def initialise_portfolio(
    portfolio_id: str,
    *,
    replication: int,
    collateral_payload: Mapping[str, Any] | None = None,
    portfolio_payload: Mapping[str, Any] | None = None,
    pool: pd.DataFrame | None = None,
    maximum_attempts: int = 100,
) -> PortfolioInitialisation:
    """Construct one result-blind portfolio with exact debt and common CR."""
    if portfolio_id not in PORTFOLIO_ORDER:
        raise ValueError(f"Unknown final portfolio: {portfolio_id}.")
    if collateral_payload is None or portfolio_payload is None:
        collateral_payload, portfolio_payload, _, _ = _design_payloads()
    selected_pool = pool if pool is not None else _quiet_empirical_pool(
        collateral_payload
    )
    portfolio = _portfolio_payload(portfolio_payload, portfolio_id)
    shares = {
        family: float(portfolio["target_debt_shares"][family])
        for family in FAMILY_ORDER
    }
    counts = largest_remainder_counts(
        shares=shares,
        total_count=VAULT_COUNT,
        family_order=FAMILY_ORDER,
    )
    expected_counts = {
        family: int(portfolio["expected_vault_counts"][family])
        for family in FAMILY_ORDER
    }
    if counts != expected_counts:
        raise ValueError(
            f"Largest-remainder allocation differs for {portfolio_id}: {counts}."
        )

    for attempt in range(maximum_attempts):
        empirical_rng = np.random.default_rng(
            _seed(
                VALIDATION_NAMESPACE,
                replication * maximum_attempts + attempt,
                f"vault_sampling:{portfolio_id}",
            )
        )
        stable_rng = np.random.default_rng(
            _seed(
                VALIDATION_NAMESPACE,
                replication * maximum_attempts + attempt,
                f"stable_vault_sampling:{portfolio_id}",
            )
        )
        rows = [
            *_sample_empirical_family(
                pool=selected_pool,
                family="ETH",
                family_config=_family_payload(collateral_payload, "ETH"),
                count=counts["ETH"],
                rng=empirical_rng,
            ),
            *_sample_empirical_family(
                pool=selected_pool,
                family="WBTC",
                family_config=_family_payload(collateral_payload, "WBTC"),
                count=counts["WBTC"],
                rng=empirical_rng,
            ),
            *_sample_stable_family(
                family_config=_family_payload(collateral_payload, "STABLE"),
                count=counts["STABLE"],
                rng=stable_rng,
            ),
        ]
        frame = pd.DataFrame(rows)
        if len(frame) != VAULT_COUNT or frame.empty:
            raise ValueError("Initialisation did not create exactly 500 vault rows.")
        frame.insert(0, "vault_id", np.arange(VAULT_COUNT, dtype=int))
        frame["debt_dai"] = 0.0
        for family in FAMILY_ORDER:
            mask = frame["family"].eq(family)
            if not mask.any():
                continue
            target = TOTAL_DEBT_DAI * shares[family]
            raw_total = float(frame.loc[mask, "raw_debt_dai"].sum())
            if raw_total <= 0.0:
                raise ValueError(f"{family} raw sampled debt is not positive.")
            frame.loc[mask, "debt_dai"] = (
                frame.loc[mask, "raw_debt_dai"] * target / raw_total
            )
        raw_ratio = float(
            np.sum(
                frame["debt_dai"].to_numpy(dtype=float)
                * frame["raw_collateral_ratio"].to_numpy(dtype=float)
            )
            / TOTAL_DEBT_DAI
        )
        if raw_ratio <= 0.0:
            raise ValueError("Raw system collateral ratio is not positive.")
        collateral_scale = TARGET_SYSTEM_COLLATERAL_RATIO / raw_ratio
        frame["collateral_ratio"] = (
            frame["raw_collateral_ratio"].astype(float) * collateral_scale
        )
        frame["initial_price_usd"] = frame["family"].map(
            {
                family: float(
                    _family_payload(collateral_payload, family)[
                        "initial_price_usd"
                    ]
                )
                for family in FAMILY_ORDER
            }
        )
        frame["collateral_amount"] = (
            frame["debt_dai"]
            * frame["collateral_ratio"]
            / frame["initial_price_usd"]
        )
        margins = (
            frame["collateral_ratio"] - frame["liquidation_ratio"]
        )
        if (margins <= 0.0).any():
            continue
        total_debt = float(frame["debt_dai"].sum())
        final_ratio = float(
            np.sum(frame["debt_dai"] * frame["collateral_ratio"]) / total_debt
        )
        vaults = tuple(
            Vault(
                vault_id=int(row.vault_id),
                owner_id=int(row.vault_id),
                collateral_amount=float(row.collateral_amount),
                debt_dai=float(row.debt_dai),
                liquidation_ratio=float(row.liquidation_ratio),
                collateral_type=str(row.model_family),
                exact_ilk=(
                    None if pd.isna(row.exact_ilk) else str(row.exact_ilk)
                ),
            )
            for row in frame.itertuples(index=False)
        )
        if len({vault.vault_id for vault in vaults}) != VAULT_COUNT:
            raise ValueError("Initialisation contains duplicate vault identifiers.")
        for family in FAMILY_ORDER:
            realised = float(frame.loc[frame["family"].eq(family), "debt_dai"].sum())
            expected = TOTAL_DEBT_DAI * shares[family]
            if not math.isclose(
                realised, expected, rel_tol=0.0, abs_tol=DEBT_TOLERANCE
            ):
                raise ValueError(f"{family} debt normalisation failed.")
        if not math.isclose(
            total_debt,
            TOTAL_DEBT_DAI,
            rel_tol=0.0,
            abs_tol=DEBT_TOLERANCE,
        ):
            raise ValueError("Initialisation total debt differs from 2.5m DAI.")
        if not math.isclose(
            final_ratio,
            TARGET_SYSTEM_COLLATERAL_RATIO,
            rel_tol=0.0,
            abs_tol=RATIO_TOLERANCE,
        ):
            raise ValueError("Initialisation system collateral ratio differs.")
        return PortfolioInitialisation(
            portfolio_id=portfolio_id,
            replication=replication,
            attempt=attempt,
            vaults=vaults,
            sampled=frame,
            family_counts=counts,
            raw_system_collateral_ratio=raw_ratio,
            target_system_collateral_ratio=TARGET_SYSTEM_COLLATERAL_RATIO,
            collateral_scaling_factor=collateral_scale,
            final_system_collateral_ratio=final_ratio,
            minimum_liquidation_distance=float(margins.min()),
            identity=_initialisation_identity(frame),
        )
    raise ValueError(
        f"No safe {portfolio_id} initialisation was accepted after "
        f"{maximum_attempts} deterministic attempts."
    )


def scientific_code_identity() -> str:
    """Hash the authoritative additive integration implementation."""
    paths = (
        REPOSITORY_ROOT / "src/dai_sim/inputs/multicollateral.py",
        REPOSITORY_ROOT / "src/dai_sim/calibration/multicollateral_validation.py",
        REPOSITORY_ROOT / "src/dai_sim/model/vault.py",
        REPOSITORY_ROOT / "src/dai_sim/model/liquidation.py",
        REPOSITORY_ROOT / "workflows/inputs/validate_multicollateral.py",
    )
    digest = hashlib.sha256()
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Missing scientific owner: {_relative(path)}.")
        digest.update(_relative(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def preregistration_payload() -> dict[str, Any]:
    """Return the immutable result-blind freeze and validation specification."""
    collateral, portfolios, shocks, profile = _design_payloads()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "final multi-collateral input freeze and integration validation",
        "multicollateral_integration_parent": PARENT_COMMIT,
        "parent_subject": PARENT_SUBJECT,
        "profile_identifier": PROFILE_ID,
        "scientific_code_identity": scientific_code_identity(),
        "configuration_checksums": {
            "collateral_registry": sha256_file(COLLATERAL_REGISTRY_PATH),
            "portfolio_registry": sha256_file(PORTFOLIO_REGISTRY_PATH),
            "shock_registry": sha256_file(SHOCK_REGISTRY_PATH),
            "profile": sha256_file(PROFILE_PATH),
        },
        "collateral_decision_hierarchy": {
            "required_volatile": ["ETH", "WBTC"],
            "stable_preference": "existing tracked generic stable proxy",
            "stable_admission_rule": "documented existing counterfactual owner only",
            "stable_owner_status": "counterfactual_stable_proxy",
            "family_order": list(FAMILY_ORDER),
        },
        "exact_ilks": {
            family: list(
                _family_payload(collateral, family).get("exact_ilks", {})
            )
            for family in ("ETH", "WBTC")
        },
        "population": {
            "vault_count": VAULT_COUNT,
            "total_debt_dai": TOTAL_DEBT_DAI,
            "count_allocation": "largest remainder; ties ETH, WBTC, STABLE",
            "debt_normalisation": (
                "one deterministic multiplicative scale per family"
            ),
            "collateral_ratio_normalisation": (
                "one portfolio-wide collateral-value scale"
            ),
            "common_system_collateral_ratio": TARGET_SYSTEM_COLLATERAL_RATIO,
            "target_statistic": (
                "median debt-weighted system collateral ratio from the "
                "protected 512 integrated ETH initialisations"
            ),
            "unsafe_initialisation_policy": (
                "reject and resample whole initialisation on deterministic substream"
            ),
        },
        "portfolio_order": list(PORTFOLIO_ORDER),
        "portfolio_rules": portfolios,
        "protocol_parameter_rules": {
            "exact_ilk_retained": True,
            "liquidation_ratio": "directly observed at 2024-02-01 boundary",
            "liquidation_penalty": "directly observed at 2024-02-01 boundary",
            "debt_ceiling": "retained for provenance; not operational in model",
            "result_based_choice": False,
        },
        "ordinary_price_owners": {
            "ETH_WBTC": "joint clean empirical 168-hour blocks",
            "stable": "clean local USDC returns as proxy ordinary path",
            "gas_alignment": "same sampled hourly rows",
            "market_pool_path": profile["market_process"]["pool_path"],
        },
        "exclusions": profile["final_validation_exclusions"],
        "volatile_tail_rule": {
            "horizon_hours": 24,
            "sample": "negative calibration-pool log returns only",
            "estimator": "nearest-rank",
            "registered_quantile": 0.01,
            "reported_quantiles": [0.05, 0.01],
            "minimum_primary": False,
        },
        "joint_stress_rule": {
            "score": (
                "-z(ETH 24h log return) - z(WBTC 24h log return) "
                "+ 0.5*z(24h median gas)"
            ),
            "lambda": 0.5,
            "selection_uses_model_outcomes": False,
        },
        "controlled_recovery": {
            "principal": "full_week",
            "adverse": "persistent_trough",
            "partial_week_core": False,
            "rapid_full_core": False,
        },
        "stable_depegs": {
            "moderate": {"floor_usd": 0.95, "recovery_hours": 72},
            "severe": {"floor_usd": 0.90, "recovery_hours": 168},
            "uses_usdc_svb": False,
            "status": "transparent_counterfactual",
        },
        "shock_order": list(SHOCK_ORDER),
        "shared_capacity_contract": {
            "capacity": SHARED_CAPACITY,
            "semantics": "one system-wide budget",
            "hurdle": "direct_cost_only",
            "risk_cost_rate": 0.0,
            "ranking": [
                "expected_profit_descending",
                "debt_at_risk_descending",
                "vault_id_ascending",
            ],
            "collateral_first_tie_break": False,
        },
        "validation_design": {
            "A": "registry and owner validation",
            "B": {
                "initialisations_per_portfolio": INITIALISATIONS_PER_PORTFOLIO,
                "portfolio_count": len(PORTFOLIO_ORDER),
                "total_initialisations": (
                    INITIALISATIONS_PER_PORTFOLIO * len(PORTFOLIO_ORDER)
                ),
            },
            "C": {
                "replications_per_portfolio": DYNAMIC_REPLICATIONS_PER_PORTFOLIO,
                "portfolio_count": len(PORTFOLIO_ORDER),
                "hours": DYNAMIC_HOURS,
                "total_replications": (
                    DYNAMIC_REPLICATIONS_PER_PORTFOLIO * len(PORTFOLIO_ORDER)
                ),
            },
            "D": {
                "smoke_count": 6,
                "maximum_hours_per_smoke": SMOKE_HOURS_MAXIMUM,
            },
        },
        "acceptance_rules": {
            "vault_count": VAULT_COUNT,
            "total_debt_tolerance": DEBT_TOLERANCE,
            "debt_share_tolerance": SHARE_TOLERANCE,
            "system_collateral_ratio_tolerance": RATIO_TOLERANCE,
            "initially_unsafe_allowed": 0,
            "capacity_may_not_exceed": SHARED_CAPACITY,
            "accounting_failures_allowed": 0,
            "price_leakage_allowed": False,
            "fallback_allowed": False,
        },
        "classifications": {
            "starting_core": "multicollateral_core_compatible_with_repairs",
            "collateral": [
                "final_collateral_universe_ready",
                "final_collateral_universe_ready_with_counterfactual_stable",
                "final_collateral_universe_crypto_ready_stable_blocked",
                "final_collateral_universe_invalid",
            ],
            "portfolio": [
                "final_portfolio_registry_ready",
                "final_portfolio_registry_ready_with_blocked_stable_cases",
                "final_portfolio_registry_invalid",
            ],
            "shock": [
                "final_shock_registry_ready",
                "final_shock_registry_ready_with_counterfactual_stable_depegs",
                "final_shock_registry_blocked",
                "final_shock_registry_invalid",
            ],
            "shared_capacity": [
                "shared_capacity_contract_valid",
                "shared_capacity_contract_valid_with_caveats",
                "shared_capacity_contract_blocked",
                "shared_capacity_contract_invalid",
            ],
            "overall": [
                "final_multicollateral_inputs_ready",
                "final_multicollateral_inputs_ready_with_caveats",
                "final_multicollateral_inputs_blocked",
                "final_multicollateral_inputs_invalid",
            ],
        },
        "seed_registry": seed_registry(),
        "protected_regressions": PROTECTED_REGRESSIONS,
        "result_fields_excluded": True,
        "portfolio_ranking": False,
        "shock_ranking_by_model_outcome": False,
        "substantive_final_experiment": False,
        "parameter_recalibration": False,
        "keeper_recalibration": False,
        "confidence_recalibration": False,
        "final_validation_data_used": False,
        "usdc_svb_used": False,
        "runtime_adopted": False,
    }
    payload["specification_identity"] = _payload_sha256(payload)
    return payload


def write_preregistration(
    evidence_dir: Path = EVIDENCE_DIR,
) -> dict[str, Any]:
    """Persist the specification before any tail or validation result."""
    payload = preregistration_payload()
    path = evidence_dir / COMPACT_FILENAMES[0]
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError(
                "Existing multi-collateral specification differs from current design."
            )
    else:
        _atomic_bytes(path, _pretty_json(payload))
    return payload


def _row_checksum(row: Mapping[str, Any]) -> str:
    return _payload_sha256(
        {key: value for key, value in row.items() if key != "row_checksum"}
    )


def collateral_registry_frame(
    collateral_payload: Mapping[str, Any],
) -> pd.DataFrame:
    """Flatten the typed collateral owner into auditable exact-ilk rows."""
    rows: list[dict[str, Any]] = []
    for order, family in enumerate(FAMILY_ORDER, start=1):
        owner = _family_payload(collateral_payload, family)
        ilks = owner.get("exact_ilks")
        entries: Iterable[tuple[str | None, Mapping[str, Any]]]
        if isinstance(ilks, dict) and ilks:
            entries = ((str(ilk), values) for ilk, values in ilks.items())
        else:
            entries = ((None, owner),)
        for exact_ilk, parameters in entries:
            initialisation = owner["initialisation"]
            provenance = owner["provenance"]
            row = {
                "registry_order": order,
                "family": family,
                "simulator_collateral_name": owner["simulator_collateral_name"],
                "token_or_proxy": owner["underlying_asset"],
                "exact_ilk": exact_ilk,
                "empirical_status": owner["evidence_status"],
                "vault_owner": initialisation["owner"],
                "vault_owner_status": initialisation["mode"],
                "price_owner": (
                    "joint_empirical_market_pool"
                    if family in {"ETH", "WBTC"}
                    else "clean_usdc_proxy_ordinary_path"
                ),
                "liquidation_ratio": float(parameters["liquidation_ratio"]),
                "liquidation_penalty_rate": float(
                    parameters["liquidation_penalty_rate"]
                ),
                "initial_price_usd": float(owner["initial_price_usd"]),
                "debt_ceiling_treatment": (
                    "not_operational"
                    if exact_ilk is not None
                    else "not_applicable"
                ),
                "stable_or_volatile": (
                    "stable" if family == "STABLE" else "volatile"
                ),
                "source_checksum": (
                    initialisation.get("pool_sha256")
                    or provenance.get("frozen_parent_owner_sha256")
                    or provenance.get("vault_owner_sha256")
                ),
                "inclusion_status": "included",
                "final_validation_boundary": (
                    "exclude FTX and USDC/SVB; no held-out validation"
                ),
                "limitation": (
                    provenance.get("caveat", "")
                    if family == "STABLE"
                    else "Exact ilks retained; no family averaging in vault state."
                ),
            }
            row["row_checksum"] = _row_checksum(row)
            rows.append(row)
    frame = pd.DataFrame(rows)
    expected_ilks = {
        "ETH-A",
        "ETH-B",
        "ETH-C",
        "WBTC-A",
        "WBTC-B",
        "WBTC-C",
    }
    if set(frame["exact_ilk"].dropna()) != expected_ilks:
        raise ValueError("Final exact-ilk population differs.")
    if frame["family"].drop_duplicates().tolist() != list(FAMILY_ORDER):
        raise ValueError("Final collateral family order differs.")
    return frame


def protocol_parameters_frame(
    collateral_payload: Mapping[str, Any],
) -> pd.DataFrame:
    """Return only protocol parameters that are active in the simulator."""
    rows: list[dict[str, Any]] = []
    for family in FAMILY_ORDER:
        owner = _family_payload(collateral_payload, family)
        ilks = owner.get("exact_ilks")
        entries: Iterable[tuple[str | None, Mapping[str, Any]]]
        if isinstance(ilks, dict) and ilks:
            entries = ((str(ilk), values) for ilk, values in ilks.items())
        else:
            entries = ((None, owner),)
        for exact_ilk, values in entries:
            source = owner["provenance"]
            source_checksum = (
                source.get("protocol_hourly_sha256")
                or source.get("frozen_parent_owner_sha256")
                or source.get("collateral_owner_sha256")
            )
            base = {
                "family": family,
                "exact_ilk": exact_ilk,
                "parameter_period": source.get(
                    "parameter_boundary_utc", "counterfactual owner"
                ),
                "source_checksum": source_checksum,
                "runtime_adopted": False,
            }
            for parameter, value, status in (
                (
                    "liquidation_ratio",
                    values["liquidation_ratio"],
                    (
                        "directly_observed"
                        if exact_ilk is not None
                        else "counterfactual"
                    ),
                ),
                (
                    "liquidation_penalty_rate",
                    values["liquidation_penalty_rate"],
                    (
                        "directly_observed"
                        if exact_ilk is not None
                        else "counterfactual"
                    ),
                ),
            ):
                row = {
                    **base,
                    "parameter": parameter,
                    "value": value,
                    "parameter_status": status,
                    "model_operational": True,
                }
                row["row_checksum"] = _row_checksum(row)
                rows.append(row)
    return pd.DataFrame(rows)


def portfolio_registry_frame(
    portfolio_payload: Mapping[str, Any],
) -> pd.DataFrame:
    """Flatten the five frozen candidate portfolios without ranking them."""
    rows: list[dict[str, Any]] = []
    portfolios = portfolio_payload["portfolios"]
    if list(portfolios) != list(PORTFOLIO_ORDER):
        raise ValueError("Final portfolio order differs.")
    for portfolio_order, identifier in enumerate(PORTFOLIO_ORDER, start=1):
        definition = _portfolio_payload(portfolio_payload, identifier)
        shares = {
            family: float(definition["target_debt_shares"][family])
            for family in FAMILY_ORDER
        }
        counts = largest_remainder_counts(
            shares=shares,
            total_count=VAULT_COUNT,
            family_order=FAMILY_ORDER,
        )
        if counts != {
            family: int(definition["expected_vault_counts"][family])
            for family in FAMILY_ORDER
        }:
            raise ValueError(f"{identifier} registered counts differ.")
        if not math.isclose(sum(shares.values()), 1.0, abs_tol=1e-12):
            raise ValueError(f"{identifier} shares do not sum to one.")
        for family_order, family in enumerate(FAMILY_ORDER, start=1):
            row = {
                "portfolio_order": portfolio_order,
                "portfolio": identifier,
                "family_order": family_order,
                "family": family,
                "target_debt_share": shares[family],
                "target_vault_count": counts[family],
                "empirical_status": (
                    "benchmark"
                    if identifier == "eth_only"
                    else (
                        "empirical_composition"
                        if identifier == "empirical_crypto"
                        else "transparent_counterfactual"
                    )
                ),
                "debt_normalisation_rule": (
                    "one multiplicative scale per family to exact target debt"
                ),
                "collateral_ratio_rule": (
                    f"portfolio-wide scale to {TARGET_SYSTEM_COLLATERAL_RATIO}"
                ),
                "portfolio_selected": False,
            }
            row["row_checksum"] = _row_checksum(row)
            rows.append(row)
    return pd.DataFrame(rows)


def _nearest_rank(values: Sequence[float], probability: float) -> float:
    array = np.sort(np.asarray(values, dtype=float))
    if len(array) == 0:
        raise ValueError("Nearest-rank estimator requires observations.")
    if not 0.0 < probability <= 1.0:
        raise ValueError("Nearest-rank probability must lie in (0, 1].")
    rank = max(1, math.ceil(probability * len(array)))
    return float(array[rank - 1])


def _rolling_market_candidates(pool: pd.DataFrame) -> pd.DataFrame:
    """Build contiguous 24-hour market and gas candidates after exclusions."""
    frame = pool.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    gaps = frame["timestamp_utc"].diff().ne(pd.Timedelta(hours=1))
    frame["_segment"] = gaps.cumsum()
    pieces: list[pd.DataFrame] = []
    for _, segment in frame.groupby("_segment", sort=False):
        segment = segment.copy()
        segment["eth_24h_log_return"] = (
            segment["eth_log_return"].rolling(24, min_periods=24).sum()
        )
        segment["wbtc_24h_log_return"] = (
            segment["wbtc_log_return"].rolling(24, min_periods=24).sum()
        )
        segment["gas_24h_mean"] = (
            segment["median_effective_gas_price_gwei"]
            .rolling(24, min_periods=24)
            .mean()
        )
        pieces.append(segment)
    candidates = pd.concat(pieces, ignore_index=True)
    candidates = candidates.dropna(
        subset=[
            "eth_24h_log_return",
            "wbtc_24h_log_return",
            "gas_24h_mean",
        ]
    ).reset_index(drop=True)
    if candidates.empty:
        raise ValueError("No contiguous 24-hour market candidates are available.")
    return candidates


def derive_market_tail_statistics(pool: pd.DataFrame) -> dict[str, Any]:
    """Derive pre-registered tail values without simulation outcomes."""
    candidates = _rolling_market_candidates(pool)
    result: dict[str, Any] = {}
    for family, column in (
        ("ETH", "eth_24h_log_return"),
        ("WBTC", "wbtc_24h_log_return"),
    ):
        negative = candidates.loc[candidates[column] < 0.0, column].to_numpy(
            dtype=float
        )
        if len(negative) == 0:
            raise ValueError(f"No negative 24-hour {family} returns are available.")
        result[family] = {
            "negative_observation_count": int(len(negative)),
            "q05_log_return": _nearest_rank(negative, 0.05),
            "q01_log_return": _nearest_rank(negative, 0.01),
            "minimum_log_return": float(np.min(negative)),
        }
        result[family]["registered_price_multiplier"] = float(
            math.exp(result[family]["q01_log_return"])
        )
        result[family]["registered_percentage_change"] = float(
            result[family]["registered_price_multiplier"] - 1.0
        )
    standardised: dict[str, np.ndarray] = {}
    for name, column, sign in (
        ("ETH", "eth_24h_log_return", -1.0),
        ("WBTC", "wbtc_24h_log_return", -1.0),
        ("gas", "gas_24h_mean", 1.0),
    ):
        values = candidates[column].to_numpy(dtype=float)
        standard_deviation = float(np.std(values, ddof=1))
        if standard_deviation <= 0.0:
            raise ValueError(f"Joint-stress {name} standard deviation is zero.")
        standardised[name] = sign * (values - float(np.mean(values))) / standard_deviation
    candidates["joint_stress_score"] = (
        standardised["ETH"] + standardised["WBTC"] + 0.5 * standardised["gas"]
    )
    selected_index = int(candidates["joint_stress_score"].idxmax())
    selected = candidates.loc[selected_index]
    result["joint_empirical"] = {
        "selection_timestamp_utc": pd.Timestamp(
            selected["timestamp_utc"]
        ).isoformat(),
        "score": float(selected["joint_stress_score"]),
        "lambda": 0.5,
        "eth_24h_log_return": float(selected["eth_24h_log_return"]),
        "wbtc_24h_log_return": float(selected["wbtc_24h_log_return"]),
        "gas_24h_mean_gwei": float(selected["gas_24h_mean"]),
        "eth_price_multiplier": float(
            math.exp(float(selected["eth_24h_log_return"]))
        ),
        "wbtc_price_multiplier": float(
            math.exp(float(selected["wbtc_24h_log_return"]))
        ),
        "selection_uses_model_outcomes": False,
    }
    return result


def _smoothstep(value: float) -> float:
    clipped = min(max(value, 0.0), 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def _controlled_path(
    *,
    multiplier: float,
    onset: int,
    recovery: str,
    recovery_hours: int,
    horizon: int = 216,
) -> np.ndarray:
    path = np.ones(horizon, dtype=float)
    if not 0.0 < multiplier <= 1.0:
        raise ValueError("Shock multiplier must lie in (0, 1].")
    path[onset] = multiplier
    if recovery == "persistent_trough":
        path[onset:] = multiplier
    elif recovery in {"full_week", "smooth_counterfactual"}:
        log_trough = math.log(multiplier)
        for hour in range(onset, horizon):
            progress = _smoothstep((hour - onset) / recovery_hours)
            path[hour] = math.exp(log_trough * (1.0 - progress))
    elif recovery == "ordinary":
        path[onset:] = multiplier
    else:
        raise ValueError(f"Unknown controlled recovery path: {recovery}.")
    return path


def shock_registry_frame(
    shock_payload: Mapping[str, Any],
    market_pool: pd.DataFrame,
) -> tuple[pd.DataFrame, Mapping[str, Any]]:
    """Resolve the seven pre-registered shocks from owner rules only."""
    tails = derive_market_tail_statistics(market_pool)
    onset = int(shock_payload["onset_hour"])
    shocks = shock_payload["shocks"]
    if list(shocks) != list(SHOCK_ORDER):
        raise ValueError("Final shock order differs.")
    rows: list[dict[str, Any]] = []
    for shock_order, shock_id in enumerate(SHOCK_ORDER, start=1):
        definition = shocks[shock_id]
        for family_order, family in enumerate(FAMILY_ORDER, start=1):
            rule = definition["rules"][family]
            source_rule = str(rule["rule"])
            recovery = definition.get(
                "principal_recovery_path_id",
                "smooth_counterfactual"
                if source_rule == "fixed_price_floor"
                else "ordinary",
            )
            duration = int(
                rule.get(
                    "duration_hours",
                    168 if recovery == "full_week" else 0,
                )
                or 0
            )
            if source_rule == "historical_24h_nearest_rank_q01":
                multiplier = float(tails[family]["registered_price_multiplier"])
                magnitude = float(tails[family]["registered_percentage_change"])
                status = "empirical_calibration_tail"
                path = _controlled_path(
                    multiplier=multiplier,
                    onset=onset,
                    recovery=recovery,
                    recovery_hours=max(duration, 1),
                )
            elif source_rule == "joint_empirical_stress_episode":
                key = "eth_price_multiplier" if family == "ETH" else "wbtc_price_multiplier"
                multiplier = float(tails["joint_empirical"][key])
                magnitude = multiplier - 1.0
                status = "empirical_calibration_episode"
                path = _controlled_path(
                    multiplier=multiplier,
                    onset=onset,
                    recovery=recovery,
                    recovery_hours=max(duration, 1),
                )
            elif source_rule == "fixed_price_floor":
                floor = float(rule["price_floor"])
                multiplier = floor
                magnitude = float(rule["magnitude"])
                status = "transparent_counterfactual"
                recovery = "smooth_counterfactual"
                path = _controlled_path(
                    multiplier=multiplier,
                    onset=onset,
                    recovery="smooth_counterfactual",
                    recovery_hours=duration,
                )
            elif source_rule == "none":
                multiplier = 1.0
                magnitude = 0.0
                status = "ordinary_unshocked"
                path = np.ones(216, dtype=float)
                recovery = "ordinary"
                duration = 0
            else:
                raise ValueError(
                    f"Unknown shock rule {source_rule} for {shock_id}/{family}."
                )
            row = {
                "shock_order": shock_order,
                "shock_identifier": shock_id,
                "family_order": family_order,
                "family": family,
                "onset_hour": onset,
                "shock_magnitude": magnitude,
                "price_multiplier_at_trough": multiplier,
                "source_rule": source_rule,
                "recovery_path": recovery,
                "duration_hours": duration,
                "empirical_status": status,
                "path_checksum": hashlib.sha256(
                    np.asarray(path, dtype="<f8").tobytes()
                ).hexdigest(),
                "selection_uses_model_outcomes": False,
                "usdc_svb_used": False,
                "final_validation_data_used": False,
            }
            row["row_checksum"] = _row_checksum(row)
            rows.append(row)
    frame = pd.DataFrame(rows)
    if len(frame) != len(SHOCK_ORDER) * len(FAMILY_ORDER):
        raise ValueError("Final shock registry does not have 21 rows.")
    if frame["shock_identifier"].drop_duplicates().tolist() != list(SHOCK_ORDER):
        raise ValueError("Final shock registry order differs.")
    price_isolation = {
        "eth_idiosyncratic": bool(
            frame.loc[
                frame["shock_identifier"].eq("eth_idiosyncratic_severe")
                & frame["family"].eq("ETH"),
                "price_multiplier_at_trough",
            ].iloc[0]
            < 1.0
            and frame.loc[
                frame["shock_identifier"].eq("eth_idiosyncratic_severe")
                & ~frame["family"].eq("ETH"),
                "price_multiplier_at_trough",
            ].eq(1.0).all()
        ),
        "wbtc_idiosyncratic": bool(
            frame.loc[
                frame["shock_identifier"].eq("wbtc_idiosyncratic_severe")
                & frame["family"].eq("WBTC"),
                "price_multiplier_at_trough",
            ].iloc[0]
            < 1.0
            and frame.loc[
                frame["shock_identifier"].eq("wbtc_idiosyncratic_severe")
                & ~frame["family"].eq("WBTC"),
                "price_multiplier_at_trough",
            ].eq(1.0).all()
        ),
        "stable_depeg": bool(
            frame.loc[
                frame["shock_identifier"].eq("stable_depeg_severe")
                & frame["family"].eq("STABLE"),
                "price_multiplier_at_trough",
            ].iloc[0]
            == 0.90
            and frame.loc[
                frame["shock_identifier"].eq("stable_depeg_severe")
                & ~frame["family"].eq("STABLE"),
                "price_multiplier_at_trough",
            ].eq(1.0).all()
        ),
        "joint_distinct_paths": bool(
            frame.loc[
                frame["shock_identifier"].eq("joint_crypto_high_correlation")
                & frame["family"].isin(["ETH", "WBTC"]),
                "path_checksum",
            ].nunique()
            == 2
        ),
    }
    if not all(price_isolation.values()):
        raise ValueError(f"Price-isolation validation failed: {price_isolation}.")
    return frame, {**tails, "price_isolation": price_isolation}


@dataclass(frozen=True)
class InitialisationValidation:
    """Compact and detailed results for Component B."""

    summary: pd.DataFrame
    replications: pd.DataFrame
    classification: str


def run_initialisation_validation(
    collateral_payload: Mapping[str, Any],
    portfolio_payload: Mapping[str, Any],
) -> InitialisationValidation:
    """Validate 256 independent initialisations for every portfolio."""
    pool = _quiet_empirical_pool(collateral_payload)
    pool_owner = pool.set_index("pool_row_id")[
        ["collateral_family", "ilk"]
    ].to_dict(orient="index")
    replication_rows: list[dict[str, Any]] = []
    for portfolio_index, portfolio_id in enumerate(PORTFOLIO_ORDER):
        definition = _portfolio_payload(portfolio_payload, portfolio_id)
        shares = {
            family: float(definition["target_debt_shares"][family])
            for family in FAMILY_ORDER
        }
        for replication in range(INITIALISATIONS_PER_PORTFOLIO):
            global_replication = (
                portfolio_index * INITIALISATIONS_PER_PORTFOLIO + replication
            )
            result = initialise_portfolio(
                portfolio_id,
                replication=global_replication,
                collateral_payload=collateral_payload,
                portfolio_payload=portfolio_payload,
                pool=pool,
            )
            frame = result.sampled
            source_leakage_count = 0
            for sampled_row in frame.loc[
                frame["source_status"].eq("empirical")
            ].itertuples(index=False):
                source = pool_owner.get(str(sampled_row.source_row_id))
                if (
                    source is None
                    or source["collateral_family"] != sampled_row.family
                    or source["ilk"] != sampled_row.exact_ilk
                ):
                    source_leakage_count += 1
            realised_shares = {
                family: float(
                    frame.loc[frame["family"].eq(family), "debt_dai"].sum()
                    / TOTAL_DEBT_DAI
                )
                for family in FAMILY_ORDER
            }
            record: dict[str, Any] = {
                "portfolio": portfolio_id,
                "replication": replication,
                "global_replication": global_replication,
                "identity": result.identity,
                "accepted_attempt": result.attempt,
                "vault_count": len(result.vaults),
                "total_debt_dai": float(frame["debt_dai"].sum()),
                "raw_system_collateral_ratio": (
                    result.raw_system_collateral_ratio
                ),
                "target_system_collateral_ratio": (
                    result.target_system_collateral_ratio
                ),
                "collateral_scaling_factor": (
                    result.collateral_scaling_factor
                ),
                "final_system_collateral_ratio": (
                    result.final_system_collateral_ratio
                ),
                "minimum_liquidation_distance": (
                    result.minimum_liquidation_distance
                ),
                "initially_unsafe_count": int(
                    np.count_nonzero(
                        frame["collateral_ratio"].to_numpy(dtype=float)
                        <= frame["liquidation_ratio"].to_numpy(dtype=float)
                    )
                ),
                "duplicate_vault_ids": (
                    len(result.vaults)
                    - len({vault.vault_id for vault in result.vaults})
                ),
                "empirical_source_window_count": int(
                    frame.loc[
                        frame["source_status"].eq("empirical"), "source_row_id"
                    ].notna().any()
                ),
                "stable_empirical_rows": int(
                    (
                        frame["family"].eq("STABLE")
                        & frame["source_status"].eq("empirical")
                    ).sum()
                ),
                "family_source_leakage_count": source_leakage_count,
            }
            for family in FAMILY_ORDER:
                family_frame = frame.loc[frame["family"].eq(family)]
                record[f"{family}_vault_count"] = int(len(family_frame))
                record[f"{family}_debt_share"] = realised_shares[family]
                record[f"{family}_debt_share_error"] = (
                    realised_shares[family] - shares[family]
                )
                record[f"{family}_mean_debt_dai"] = (
                    float(family_frame["debt_dai"].mean())
                    if len(family_frame)
                    else 0.0
                )
                record[f"{family}_mean_collateral_ratio"] = (
                    float(family_frame["collateral_ratio"].mean())
                    if len(family_frame)
                    else 0.0
                )
            replication_rows.append(record)
    replications = pd.DataFrame(replication_rows).sort_values(
        ["portfolio", "replication"], kind="mergesort"
    )
    summary_rows: list[dict[str, Any]] = []
    for portfolio_id in PORTFOLIO_ORDER:
        selected = replications.loc[replications["portfolio"].eq(portfolio_id)]
        replay = initialise_portfolio(
            portfolio_id,
            replication=(
                PORTFOLIO_ORDER.index(portfolio_id)
                * INITIALISATIONS_PER_PORTFOLIO
            ),
            collateral_payload=collateral_payload,
            portfolio_payload=portfolio_payload,
            pool=pool,
        )
        deterministic = bool(replay.identity == selected.iloc[0]["identity"])
        metric_values = {
            "initialisation_count": float(len(selected)),
            "vault_count_minimum": float(selected["vault_count"].min()),
            "vault_count_maximum": float(selected["vault_count"].max()),
            "maximum_total_debt_error_dai": float(
                np.max(np.abs(selected["total_debt_dai"] - TOTAL_DEBT_DAI))
            ),
            "maximum_debt_share_error": float(
                max(
                    np.max(np.abs(selected[f"{family}_debt_share_error"]))
                    for family in FAMILY_ORDER
                )
            ),
            "maximum_system_collateral_ratio_error": float(
                np.max(
                    np.abs(
                        selected["final_system_collateral_ratio"]
                        - TARGET_SYSTEM_COLLATERAL_RATIO
                    )
                )
            ),
            "minimum_liquidation_distance": float(
                selected["minimum_liquidation_distance"].min()
            ),
            "maximum_initially_unsafe_count": float(
                selected["initially_unsafe_count"].max()
            ),
            "maximum_duplicate_vault_ids": float(
                selected["duplicate_vault_ids"].max()
            ),
            "stable_empirical_row_count": float(
                selected["stable_empirical_rows"].sum()
            ),
            "maximum_family_source_leakage_count": float(
                selected["family_source_leakage_count"].max()
            ),
            "deterministic_replay": float(deterministic),
        }
        for family in FAMILY_ORDER:
            metric_values[f"{family}_target_vault_count"] = float(
                selected[f"{family}_vault_count"].iloc[0]
            )
            metric_values[f"{family}_mean_debt_dai"] = float(
                selected[f"{family}_mean_debt_dai"].mean()
            )
            metric_values[f"{family}_mean_collateral_ratio"] = float(
                selected[f"{family}_mean_collateral_ratio"].mean()
            )
        for metric, value in metric_values.items():
            summary_rows.append(
                {
                    "portfolio": portfolio_id,
                    "metric": metric,
                    "value": value,
                    "initialisation_count": len(selected),
                    "exact_debt": bool(
                        metric != "maximum_total_debt_error_dai"
                        or value <= DEBT_TOLERANCE
                    ),
                    "deterministic_status": deterministic,
                    "owner_status": (
                        "counterfactual_not_empirically_banded"
                        if metric.startswith("STABLE_")
                        else "family_specific_owner"
                    ),
                }
            )
    summary = pd.DataFrame(summary_rows)
    valid = bool(
        len(replications)
        == INITIALISATIONS_PER_PORTFOLIO * len(PORTFOLIO_ORDER)
        and replications["vault_count"].eq(VAULT_COUNT).all()
        and np.max(
            np.abs(replications["total_debt_dai"] - TOTAL_DEBT_DAI)
        )
        <= DEBT_TOLERANCE
        and max(
            np.max(np.abs(replications[f"{family}_debt_share_error"]))
            for family in FAMILY_ORDER
        )
        <= SHARE_TOLERANCE
        and np.max(
            np.abs(
                replications["final_system_collateral_ratio"]
                - TARGET_SYSTEM_COLLATERAL_RATIO
            )
        )
        <= RATIO_TOLERANCE
        and replications["initially_unsafe_count"].eq(0).all()
        and replications["duplicate_vault_ids"].eq(0).all()
        and replications["stable_empirical_rows"].eq(0).all()
        and replications["family_source_leakage_count"].eq(0).all()
    )
    return InitialisationValidation(
        summary=summary,
        replications=replications,
        classification=(
            "final_portfolio_registry_ready"
            if valid
            else "final_portfolio_registry_invalid"
        ),
    )


def _family_portfolio(
    collateral_payload: Mapping[str, Any],
    active_families: Sequence[str],
) -> CollateralPortfolioConfig:
    collaterals = []
    share = 1.0 / len(active_families)
    for family in active_families:
        owner = _family_payload(collateral_payload, family)
        collaterals.append(
            CollateralConfig(
                name=str(owner["simulator_collateral_name"]),
                initial_price=float(owner["initial_price_usd"]),
                liquidation_ratio=float(owner["liquidation_ratio"]),
                liquidation_penalty=float(owner["liquidation_penalty_rate"]),
                target_debt_share=share,
                max_close_factor=float(owner["max_close_factor"]),
            )
        )
    return CollateralPortfolioConfig(
        name="multicollateral_shared_capacity_smoke",
        collaterals=tuple(collaterals),
    )


def _smoke_vaults(
    active_families: Sequence[str],
    collateral_payload: Mapping[str, Any],
) -> list[Vault]:
    """Construct transparent unsafe candidates with interleaved profits."""
    vaults: list[Vault] = []
    vault_id = 0
    for level in range(36):
        for family_index, family in enumerate(active_families):
            owner = _family_payload(collateral_payload, family)
            penalty = float(owner["liquidation_penalty_rate"])
            target_profit = 10_000.0 - level * 10.0 - family_index
            debt = target_profit / penalty
            model_family = str(owner["simulator_collateral_name"])
            price = float(owner["initial_price_usd"])
            vaults.append(
                Vault(
                    vault_id=vault_id,
                    owner_id=vault_id,
                    collateral_amount=0.80 * debt / price,
                    debt_dai=debt,
                    liquidation_ratio=float(owner["liquidation_ratio"]),
                    collateral_type=model_family,
                    exact_ilk=(
                        next(iter(owner["exact_ilks"]))
                        if owner.get("exact_ilks")
                        else None
                    ),
                )
            )
            vault_id += 1
    return vaults


def _family_from_model(value: str) -> str:
    return "WBTC" if value == "BTC" else value


def _capacity_smoke(
    *,
    identifier: str,
    active_families: Sequence[str],
    collateral_payload: Mapping[str, Any],
    permuted: bool = False,
) -> tuple[dict[str, Any], pd.DataFrame]:
    vaults = _smoke_vaults(active_families, collateral_payload)
    ordered_vaults = list(reversed(vaults)) if permuted else list(vaults)
    prices = {
        str(_family_payload(collateral_payload, family)["simulator_collateral_name"]):
        float(_family_payload(collateral_payload, family)["initial_price_usd"])
        for family in active_families
    }
    portfolio = _family_portfolio(collateral_payload, active_families)
    config = LiquidationConfig(
        liquidation_penalty=0.13,
        gas_cost=0.0,
        risk_cost_rate=0.0,
        max_close_factor=1.0,
        max_liquidations_per_step=SHARED_CAPACITY,
    )
    ranked = rank_liquidation_candidates(
        ordered_vaults,
        prices=prices,
        config=config,
        portfolio=portfolio,
    )
    selected = ranked.head(SHARED_CAPACITY)
    selected_ids = tuple(int(value) for value in selected["vault_id"])
    selected_id_set = set(selected_ids)
    isolated_selected_ids: dict[str, set[int]] = {}
    for family in active_families:
        model_family = str(
            _family_payload(collateral_payload, family)[
                "simulator_collateral_name"
            ]
        )
        isolated_ranked = rank_liquidation_candidates(
            [
                vault
                for vault in ordered_vaults
                if vault.collateral_type == model_family
            ],
            prices=prices,
            config=config,
            portfolio=portfolio,
        )
        isolated_selected_ids[family] = set(
            isolated_ranked.head(SHARED_CAPACITY)["vault_id"].astype(int)
        )
    expected = (
        ranked.sort_values(
            ["expected_profit", "debt_at_risk", "vault_id"],
            ascending=[False, False, True],
            kind="mergesort",
        )
        .head(SHARED_CAPACITY)["vault_id"]
        .astype(int)
        .tolist()
    )
    if list(selected_ids) != expected:
        raise ValueError(f"Global ranking differs in smoke {identifier}.")
    vault_by_id = {vault.vault_id: vault for vault in vaults}
    execution_rows: list[dict[str, Any]] = []
    initial_debt = {
        family: float(
            sum(
                vault.debt_dai
                for vault in vaults
                if _family_from_model(vault.collateral_type) == family
            )
        )
        for family in active_families
    }
    initial_collateral = {
        family: float(
            sum(
                vault.collateral_amount
                for vault in vaults
                if _family_from_model(vault.collateral_type) == family
            )
        )
        for family in active_families
    }
    for vault_id in selected_ids:
        result = execute_keeper_liquidation(
            vault_by_id[vault_id],
            prices,
            config,
            portfolio=portfolio,
        )
        result["family"] = _family_from_model(
            vault_by_id[vault_id].collateral_type
        )
        execution_rows.append(result)
    execution = pd.DataFrame(execution_rows)
    candidates_by_family = Counter(
        _family_from_model(value) for value in ranked["collateral_type"]
    )
    selected_by_family = Counter(
        _family_from_model(value) for value in selected["collateral_type"]
    )
    successful_by_family = Counter(
        execution.loc[execution["liquidated"].astype(bool), "family"]
    )
    rejected_by_family = {
        family: candidates_by_family[family] - selected_by_family[family]
        for family in active_families
    }
    completed_debt_by_family = {
        family: float(
            execution.loc[
                execution["family"].eq(family), "debt_repaid"
            ].sum()
        )
        for family in active_families
    }
    keeper_profit_by_family = {
        family: float(
            execution.loc[
                execution["family"].eq(family), "realised_keeper_profit"
            ].sum()
        )
        for family in active_families
    }
    final_debt = {
        family: float(
            sum(
                vault.debt_dai
                for vault in vaults
                if _family_from_model(vault.collateral_type) == family
                and vault.is_active
            )
        )
        for family in active_families
    }
    final_collateral = {
        family: float(
            sum(
                vault.collateral_amount
                for vault in vaults
                if _family_from_model(vault.collateral_type) == family
                and vault.is_active
            )
        )
        for family in active_families
    }
    backlog_by_family = {
        family: float(
            sum(
                vault.debt_dai
                for vault in vaults
                if _family_from_model(vault.collateral_type) == family
                and vault.is_liquidatable(prices)
            )
        )
        for family in active_families
    }
    bad_debt_by_family = {
        family: float(
            sum(
                vault.bad_debt(prices)
                for vault in vaults
                if _family_from_model(vault.collateral_type) == family
                and vault.is_active
            )
        )
        for family in active_families
    }
    debt_errors = {
        family: initial_debt[family]
        - final_debt[family]
        - completed_debt_by_family[family]
        for family in active_families
    }
    collateral_removed = {
        family: initial_collateral[family] - final_collateral[family]
        for family in active_families
    }
    displacement = {
        family: len(isolated_selected_ids[family] - selected_id_set)
        for family in active_families
    }
    original_candidate_ids = set(ranked["vault_id"].astype(int))
    actual_unresolved_ids = {
        vault.vault_id
        for vault in vaults
        if vault.is_active and vault.is_liquidatable(prices)
    }
    fully_liquidated_ids = set(
        execution.loc[
            execution["fully_liquidated"].astype(bool), "vault_id"
        ].astype(int)
    )
    expected_unresolved_ids = original_candidate_ids - fully_liquidated_ids
    backlog_persistence_valid = actual_unresolved_ids == expected_unresolved_ids
    system_reconciles = bool(
        len(selected) == sum(selected_by_family.values())
        and int(execution["liquidated"].sum())
        == sum(successful_by_family.values())
        and math.isclose(
            float(execution["debt_repaid"].sum()),
            sum(completed_debt_by_family.values()),
            abs_tol=1e-8,
        )
        and math.isclose(
            float(execution["realised_keeper_profit"].sum()),
            sum(keeper_profit_by_family.values()),
            abs_tol=1e-8,
        )
        and all(abs(value) <= 1e-8 for value in debt_errors.values())
    )
    row: dict[str, Any] = {
        "smoke_identifier": identifier,
        "hours": 2,
        "active_collateral_families": "|".join(active_families),
        "unsafe_opportunities": int(len(ranked)),
        "sampled_arrivals": int(len(ranked)),
        "total_attempts": int(len(selected)),
        "capacity_value": SHARED_CAPACITY,
        "capacity_rejected_opportunities": int(
            len(ranked) - len(selected)
        ),
        "successful_closures": int(execution["liquidated"].sum()),
        "unprofitable_attempts": int((~execution["liquidated"]).sum()),
        "completed_debt_dai": float(execution["debt_repaid"].sum()),
        "backlog_tab_dai": sum(backlog_by_family.values()),
        "active_bad_debt_dai": sum(bad_debt_by_family.values()),
        "realised_bad_debt_dai": float(
            execution.loc[
                execution["liquidated"].astype(bool), "bad_debt"
            ].sum()
        ),
        "keeper_profit_dai": float(execution["realised_keeper_profit"].sum()),
        "ranking_validation": True,
        "permutation_validation": True,
        "accounting_validation": system_reconciles,
        "backlog_persistence_validation": backlog_persistence_valid,
        "selected_vault_ids_checksum": _payload_sha256(selected_ids),
        "duplicate_closure": bool(
            len(execution["vault_id"]) != execution["vault_id"].nunique()
        ),
    }
    for family in FAMILY_ORDER:
        row[f"{family}_unsafe"] = int(candidates_by_family[family])
        row[f"{family}_selected_attempts"] = int(selected_by_family[family])
        row[f"{family}_rejected"] = int(rejected_by_family.get(family, 0))
        row[f"{family}_successful"] = int(successful_by_family[family])
        row[f"{family}_completed_debt_dai"] = float(
            completed_debt_by_family.get(family, 0.0)
        )
        row[f"{family}_backlog_tab_dai"] = float(
            backlog_by_family.get(family, 0.0)
        )
        row[f"{family}_active_bad_debt_dai"] = float(
            bad_debt_by_family.get(family, 0.0)
        )
        row[f"{family}_keeper_profit_dai"] = float(
            keeper_profit_by_family.get(family, 0.0)
        )
        row[f"capacity_displacement_{family}_from_other_collateral"] = int(
            displacement.get(family, 0)
        )
        row[f"{family}_collateral_removed_units"] = float(
            collateral_removed.get(family, 0.0)
        )
    trace = ranked.copy()
    trace["selected"] = trace["vault_id"].isin(selected_ids)
    trace["smoke_identifier"] = identifier
    return row, trace


@dataclass(frozen=True)
class SharedCapacityValidation:
    """Compact Component D evidence and ignored candidate traces."""

    summary: pd.DataFrame
    traces: pd.DataFrame
    classification: str


def run_shared_capacity_validation(
    collateral_payload: Mapping[str, Any],
) -> SharedCapacityValidation:
    """Run the six transparent shared-capacity contract smokes."""
    definitions = (
        ("eth_only_unsafe", ("ETH",), False),
        ("wbtc_only_unsafe", ("WBTC",), False),
        ("stable_only_unsafe", ("STABLE",), False),
        ("eth_wbtc_simultaneous", ("ETH", "WBTC"), False),
        ("all_collateral_simultaneous", FAMILY_ORDER, False),
        ("permuted_all_collateral", FAMILY_ORDER, True),
    )
    rows: list[dict[str, Any]] = []
    traces: list[pd.DataFrame] = []
    for identifier, families, permuted in definitions:
        row, trace = _capacity_smoke(
            identifier=identifier,
            active_families=families,
            collateral_payload=collateral_payload,
            permuted=permuted,
        )
        rows.append(row)
        traces.append(trace)
    summary = pd.DataFrame(rows)
    original = summary.loc[
        summary["smoke_identifier"].eq("all_collateral_simultaneous")
    ].iloc[0]
    permuted = summary.loc[
        summary["smoke_identifier"].eq("permuted_all_collateral")
    ].iloc[0]
    permutation_valid = bool(
        original["selected_vault_ids_checksum"]
        == permuted["selected_vault_ids_checksum"]
    )
    summary.loc[
        summary["smoke_identifier"].isin(
            ["all_collateral_simultaneous", "permuted_all_collateral"]
        ),
        "permutation_validation",
    ] = permutation_valid
    simultaneous = summary.loc[
        summary["smoke_identifier"].isin(
            [
                "eth_wbtc_simultaneous",
                "all_collateral_simultaneous",
                "permuted_all_collateral",
            ]
        )
    ]
    spans_families = all(
        sum(int(row[f"{family}_selected_attempts"] > 0) for family in FAMILY_ORDER)
        >= 2
        for _, row in simultaneous.iterrows()
    )
    valid = bool(
        summary["hours"].le(SMOKE_HOURS_MAXIMUM).all()
        and summary["total_attempts"].le(SHARED_CAPACITY).all()
        and summary["ranking_validation"].all()
        and summary["accounting_validation"].all()
        and summary["backlog_persistence_validation"].all()
        and summary["permutation_validation"].all()
        and ~summary["duplicate_closure"].any()
        and simultaneous["capacity_rejected_opportunities"].gt(0).all()
        and spans_families
    )
    return SharedCapacityValidation(
        summary=summary,
        traces=pd.concat(traces, ignore_index=True),
        classification=(
            "shared_capacity_contract_valid"
            if valid
            else "shared_capacity_contract_invalid"
        ),
    )


def _valid_market_block_starts(
    pool: pd.DataFrame,
    block_length: int = DYNAMIC_HOURS,
) -> np.ndarray:
    timestamps = pd.to_datetime(pool["timestamp_utc"], utc=True)
    valid = pool["return_observation_valid"].astype(bool).to_numpy()
    segments = pool["calibration_segment_id"].to_numpy()
    starts: list[int] = []
    for start in range(0, len(pool) - block_length + 1):
        stop = start + block_length
        if not valid[start:stop].all():
            continue
        if segments[start] != segments[stop - 1]:
            continue
        expected_end = timestamps.iloc[start] + pd.Timedelta(
            hours=block_length - 1
        )
        if timestamps.iloc[stop - 1] != expected_end:
            continue
        starts.append(start)
    if not starts:
        raise ValueError("No valid 168-hour clean market blocks are available.")
    return np.asarray(starts, dtype=int)


def _sample_market_block(
    pool: pd.DataFrame,
    *,
    seed: int,
    valid_starts: np.ndarray | None = None,
) -> tuple[pd.DataFrame, int]:
    starts = (
        _valid_market_block_starts(pool)
        if valid_starts is None
        else valid_starts
    )
    rng = np.random.default_rng(seed)
    start = int(rng.choice(starts))
    sample = pool.iloc[start : start + DYNAMIC_HOURS].copy().reset_index(drop=True)
    sample.insert(0, "simulation_step", np.arange(DYNAMIC_HOURS, dtype=int))
    if len(sample) != DYNAMIC_HOURS:
        raise ValueError("Sampled market block is incomplete.")
    return sample, start


def _price_paths(
    sample: pd.DataFrame,
    initial_prices: Mapping[str, float],
) -> dict[str, np.ndarray]:
    paths: dict[str, np.ndarray] = {}
    for family, column in (
        ("ETH", "eth_log_return"),
        ("BTC", "wbtc_log_return"),
        ("STABLE", "usdc_log_return"),
    ):
        initial = float(initial_prices[family])
        returns = pd.to_numeric(sample[column], errors="raise").to_numpy(
            dtype=float
        )
        if not np.isfinite(returns).all():
            raise ValueError(f"{column} contains non-finite returns.")
        values = np.empty(DYNAMIC_HOURS, dtype=float)
        values[0] = initial
        for position in range(1, DYNAMIC_HOURS):
            values[position] = values[position - 1] * math.exp(returns[position])
        if not np.isfinite(values).all() or np.any(values <= 0.0):
            raise ValueError(f"{family} ordinary price path is invalid.")
        paths[family] = values
    return paths


def _price_isolation_valid(
    vaults: Sequence[Vault],
    price_map: Mapping[str, float],
) -> bool:
    """Verify that each vault reads only its own collateral-price owner."""
    for collateral_type in ("ETH", "BTC", "STABLE"):
        vault = next(
            (
                candidate
                for candidate in vaults
                if candidate.collateral_type == collateral_type
            ),
            None,
        )
        if vault is None:
            continue
        baseline = vault.collateral_value(dict(price_map))
        other_prices = dict(price_map)
        for other in other_prices:
            if other != collateral_type:
                other_prices[other] *= 1.25
        if not math.isclose(
            vault.collateral_value(other_prices),
            baseline,
            rel_tol=0.0,
            abs_tol=1e-10,
        ):
            return False
        own_price = dict(price_map)
        own_price[collateral_type] *= 1.01
        expected = baseline * 1.01
        if not math.isclose(
            vault.collateral_value(own_price),
            expected,
            rel_tol=1e-12,
            abs_tol=1e-10,
        ):
            return False
    return True


def _ordinary_owner_validation(sample: pd.DataFrame) -> bool:
    """Prove that Component C uses only the registered calibration owners."""
    timestamps = pd.to_datetime(sample["timestamp_utc"], utc=True)
    outside_ftx = ~(
        (timestamps >= pd.Timestamp("2022-11-01T00:00:00Z"))
        & (timestamps < pd.Timestamp("2022-11-21T00:00:00Z"))
    )
    outside_svb = ~(
        (timestamps >= pd.Timestamp("2023-03-06T00:00:00Z"))
        & (timestamps < pd.Timestamp("2023-03-20T00:00:00Z"))
    )
    required = {
        "eth_log_return",
        "wbtc_log_return",
        "usdc_log_return",
        "median_effective_gas_price_gwei",
        "p90_effective_gas_price_gwei",
        "p99_effective_gas_price_gwei",
    }
    return bool(
        required.issubset(sample.columns)
        and sample["is_calibration"].astype(bool).all()
        and sample["return_observation_valid"].astype(bool).all()
        and outside_ftx.all()
        and outside_svb.all()
        and sample.loc[:, sorted(required)].notna().all().all()
    )


def _dynamic_replication(
    *,
    portfolio_id: str,
    portfolio_index: int,
    replication: int,
    collateral_payload: Mapping[str, Any],
    portfolio_payload: Mapping[str, Any],
    vault_pool: pd.DataFrame,
    market_pool: pd.DataFrame,
    stage1: Mapping[str, Any],
    valid_market_starts: np.ndarray | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    global_replication = (
        portfolio_index * DYNAMIC_REPLICATIONS_PER_PORTFOLIO + replication
    )
    initial = initialise_portfolio(
        portfolio_id,
        replication=10_000 + global_replication,
        collateral_payload=collateral_payload,
        portfolio_payload=portfolio_payload,
        pool=vault_pool,
    )
    vaults = list(initial.vaults)
    sample, market_start = _sample_market_block(
        market_pool,
        seed=_seed(
            VALIDATION_NAMESPACE,
            global_replication,
            "market_gas_blocks",
        ),
        valid_starts=valid_market_starts,
    )
    initial_prices = {
        "ETH": float(_family_payload(collateral_payload, "ETH")["initial_price_usd"]),
        "BTC": float(
            _family_payload(collateral_payload, "WBTC")["initial_price_usd"]
        ),
        "STABLE": float(
            _family_payload(collateral_payload, "STABLE")["initial_price_usd"]
        ),
    }
    prices = _price_paths(sample, initial_prices)
    integrated = resolve_integrated_empirical_eth_profile()
    gas = component_gas_costs(
        sampled_market_gas_rows=sample,
        simulated_eth_prices=prices["ETH"],
        config=replace(
            integrated.gas,
            seed=_seed(
                VALIDATION_NAMESPACE,
                global_replication,
                "keeper_gas_units",
            ),
        ),
    )
    if gas.gas_cost_usd is None:
        raise ValueError("Component gas owner returned no USD cost path.")
    demand = LiquidationDemandProcess(
        replace(
            integrated.liquidation_demand,
            seed=_seed(
                VALIDATION_NAMESPACE,
                global_replication,
                "liquidation_arrivals",
            ),
        )
    )
    residual_rng = np.random.default_rng(
        _seed(
            VALIDATION_NAMESPACE,
            global_replication,
            "stage1_residual_blocks",
        )
    )
    residuals = sample_residual_blocks(
        stage1["source"],
        block_count=math.ceil(DYNAMIC_HOURS / 24),
        rng=residual_rng,
    )[:DYNAMIC_HOURS]
    gas_path_checksum = hashlib.sha256(
        np.asarray(gas.gas_cost_usd, dtype="<f8").tobytes()
    ).hexdigest()
    residual_path_checksum = hashlib.sha256(
        np.asarray(residuals, dtype="<f8").tobytes()
    ).hexdigest()

    active_families = tuple(
        family
        for family in FAMILY_ORDER
        if initial.family_counts[family] > 0
    )
    portfolio = _family_portfolio(collateral_payload, active_families)
    initial_debt = {
        family: float(
            sum(
                vault.debt_dai
                for vault in vaults
                if _family_from_model(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    initial_collateral = {
        family: float(
            sum(
                vault.collateral_amount
                for vault in vaults
                if _family_from_model(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    totals: dict[str, dict[str, float]] = {
        family: defaultdict(float) for family in FAMILY_ORDER
    }
    maximum_backlog = {family: 0.0 for family in FAMILY_ORDER}
    maximum_bad_debt = {family: 0.0 for family in FAMILY_ORDER}
    maximum_system_backlog = 0.0
    maximum_system_bad_debt = 0.0
    hourly_rows: list[dict[str, Any]] = []
    dai_price = 1.0
    dai_prices: list[float] = []
    maximum_attempts = 0
    binding_hours = 0
    reconciliation_failures = 0
    duplicate_attempt = False
    duplicate_closure = False
    fully_closed_ids: set[int] = set()
    state_invalid = False
    arrival_records: list[dict[str, Any]] = []
    vault_by_id = {vault.vault_id: vault for vault in vaults}
    owner_validation = _ordinary_owner_validation(sample)
    initial_price_map = {
        "ETH": float(prices["ETH"][0]),
        "BTC": float(prices["BTC"][0]),
        "STABLE": float(prices["STABLE"][0]),
    }
    price_isolation = _price_isolation_valid(vaults, initial_price_map)
    for step in range(DYNAMIC_HOURS):
        price_map = {
            "ETH": float(prices["ETH"][step]),
            "BTC": float(prices["BTC"][step]),
            "STABLE": float(prices["STABLE"][step]),
        }
        candidates = [
            vault
            for vault in vaults
            if vault.is_active and vault.is_liquidatable(price_map)
        ]
        step_config = LiquidationConfig(
            liquidation_penalty=0.13,
            gas_cost=float(gas.gas_cost_usd[step]),
            risk_cost_rate=0.0,
            max_close_factor=1.0,
            max_liquidations_per_step=SHARED_CAPACITY,
        )
        ranked = rank_liquidation_candidates(
            candidates,
            prices=price_map,
            config=step_config,
            portfolio=portfolio,
        )
        decision = demand.sample_step(
            step=step,
            liquidatable_inventory=len(candidates),
            keeper_capacity=SHARED_CAPACITY,
        )
        arrival_records.append(decision.as_record())
        demand_selected = ranked.head(decision.bounded_demand)
        attempt_selected = ranked.head(decision.attempt_budget)
        attempt_ids = attempt_selected["vault_id"].astype(int).tolist()
        duplicate_attempt = duplicate_attempt or (
            len(attempt_ids) != len(set(attempt_ids))
        )
        demand_by_family = Counter(
            _family_from_model(value)
            for value in demand_selected["collateral_type"]
        )
        attempt_by_family = Counter(
            _family_from_model(value)
            for value in attempt_selected["collateral_type"]
        )
        candidate_by_family = Counter(
            _family_from_model(value) for value in ranked["collateral_type"]
        )
        maximum_attempts = max(maximum_attempts, len(attempt_ids))
        binding_hours += int(decision.demand_truncated_by_capacity > 0)
        execution_rows: list[dict[str, Any]] = []
        for vault_id in attempt_ids:
            vault = vault_by_id[vault_id]
            collateral_before = vault.collateral_amount
            result = execute_keeper_liquidation(
                vault,
                price_map,
                step_config,
                portfolio=portfolio,
            )
            family = _family_from_model(vault.collateral_type)
            result["family"] = family
            result["collateral_removed_units"] = (
                collateral_before - vault.collateral_amount
            )
            if result["fully_liquidated"]:
                if vault_id in fully_closed_ids:
                    duplicate_closure = True
                fully_closed_ids.add(vault_id)
            execution_rows.append(result)
        execution = pd.DataFrame(execution_rows)
        successful_by_family: Counter[str] = Counter()
        step_family: dict[str, dict[str, float]] = {}
        for family in FAMILY_ORDER:
            family_execution = (
                execution.loc[execution["family"].eq(family)]
                if not execution.empty
                else execution
            )
            successful = (
                int(family_execution["liquidated"].sum())
                if not family_execution.empty
                else 0
            )
            successful_by_family[family] = successful
            totals[family]["unsafe_opportunities"] += candidate_by_family[family]
            totals[family]["sampled_arrivals"] += demand_by_family[family]
            totals[family]["selected_attempts"] += attempt_by_family[family]
            totals[family]["capacity_rejected"] += (
                demand_by_family[family] - attempt_by_family[family]
            )
            totals[family]["successful_closures"] += successful
            totals[family]["unprofitable_attempts"] += (
                attempt_by_family[family] - successful
            )
            successful_execution = (
                family_execution.loc[
                    family_execution["liquidated"].astype(bool)
                ]
                if not family_execution.empty
                else family_execution
            )
            completed_debt = (
                float(successful_execution["debt_repaid"].sum())
                if not successful_execution.empty
                else 0.0
            )
            realised_bad_debt = (
                float(successful_execution["bad_debt"].sum())
                if not successful_execution.empty
                else 0.0
            )
            keeper_profit = (
                float(successful_execution["realised_keeper_profit"].sum())
                if not successful_execution.empty
                else 0.0
            )
            collateral_removed = (
                float(successful_execution["collateral_removed_units"].sum())
                if not successful_execution.empty
                else 0.0
            )
            totals[family]["completed_debt_dai"] += completed_debt
            totals[family]["realised_bad_debt_dai"] += realised_bad_debt
            totals[family]["keeper_profit_dai"] += keeper_profit
            totals[family]["collateral_removed_units"] += collateral_removed
            backlog = float(
                sum(
                    vault.debt_dai
                    for vault in vaults
                    if _family_from_model(vault.collateral_type) == family
                    and vault.is_liquidatable(price_map)
                )
            )
            active_bad_debt = float(
                sum(
                    vault.bad_debt(price_map)
                    for vault in vaults
                    if _family_from_model(vault.collateral_type) == family
                    and vault.is_active
                )
            )
            maximum_backlog[family] = max(maximum_backlog[family], backlog)
            maximum_bad_debt[family] = max(
                maximum_bad_debt[family], active_bad_debt
            )
            step_family[family] = {
                "unsafe_opportunities": float(candidate_by_family[family]),
                "sampled_arrivals": float(demand_by_family[family]),
                "selected_attempts": float(attempt_by_family[family]),
                "capacity_rejected": float(
                    demand_by_family[family] - attempt_by_family[family]
                ),
                "successful_closures": float(successful),
                "unprofitable_attempts": float(
                    attempt_by_family[family] - successful
                ),
                "completed_debt_dai": completed_debt,
                "backlog_tab_dai": backlog,
                "active_bad_debt_dai": active_bad_debt,
                "realised_bad_debt_dai": realised_bad_debt,
                "keeper_profit_dai": keeper_profit,
                "collateral_removed_units": collateral_removed,
            }
            hourly_rows.append(
                {
                    "portfolio": portfolio_id,
                    "replication": replication,
                    "step": step,
                    "family": family,
                    "unsafe_opportunities": candidate_by_family[family],
                    "sampled_arrivals": demand_by_family[family],
                    "selected_attempts": attempt_by_family[family],
                    "capacity_rejected": (
                        demand_by_family[family] - attempt_by_family[family]
                    ),
                    "successful_closures": successful,
                    "unprofitable_attempts": (
                        attempt_by_family[family] - successful
                    ),
                    "completed_debt_dai": completed_debt,
                    "backlog_tab_dai": backlog,
                    "active_bad_debt_dai": active_bad_debt,
                    "realised_bad_debt_dai": realised_bad_debt,
                    "keeper_profit_dai": keeper_profit,
                    "collateral_removed_units": collateral_removed,
                }
            )
        successful_execution = (
            execution.loc[execution["liquidated"].astype(bool)]
            if not execution.empty
            else execution
        )
        system_step = {
            "unsafe_opportunities": float(len(ranked)),
            "sampled_arrivals": float(len(demand_selected)),
            "selected_attempts": float(len(attempt_selected)),
            "capacity_rejected": float(
                len(demand_selected) - len(attempt_selected)
            ),
            "successful_closures": float(
                len(successful_execution)
            ),
            "unprofitable_attempts": float(
                len(attempt_selected) - len(successful_execution)
            ),
            "completed_debt_dai": (
                float(successful_execution["debt_repaid"].sum())
                if not successful_execution.empty
                else 0.0
            ),
            "backlog_tab_dai": float(
                sum(values["backlog_tab_dai"] for values in step_family.values())
            ),
            "active_bad_debt_dai": float(
                sum(
                    values["active_bad_debt_dai"]
                    for values in step_family.values()
                )
            ),
            "realised_bad_debt_dai": (
                float(successful_execution["bad_debt"].sum())
                if not successful_execution.empty
                else 0.0
            ),
            "keeper_profit_dai": (
                float(successful_execution["realised_keeper_profit"].sum())
                if not successful_execution.empty
                else 0.0
            ),
            "collateral_removed_units": float(
                sum(
                    values["collateral_removed_units"]
                    for values in step_family.values()
                )
            ),
        }
        if decision.sampled_demand < decision.bounded_demand:
            state_invalid = True
        if (
            decision.sampled_demand - decision.bounded_demand
            != decision.demand_truncated_by_inventory
            or decision.bounded_demand - decision.attempt_budget
            != decision.demand_truncated_by_capacity
        ):
            state_invalid = True
        if any(
            not math.isfinite(value) or value < 0.0
            for value in system_step.values()
        ):
            state_invalid = True
        if not execution.empty:
            numerical_columns = (
                "expected_profit",
                "realised_keeper_profit",
                "bad_debt",
                "debt_repaid",
                "remaining_debt",
                "remaining_collateral_amount",
                "collateral_removed_units",
            )
            if not np.isfinite(
                execution.loc[:, numerical_columns].to_numpy(dtype=float)
            ).all():
                state_invalid = True
        if any(
            not math.isfinite(vault.debt_dai)
            or not math.isfinite(vault.collateral_amount)
            or vault.debt_dai < 0.0
            or vault.collateral_amount < 0.0
            for vault in vaults
        ):
            state_invalid = True
        for metric, system_value in system_step.items():
            family_value = sum(
                values[metric] for values in step_family.values()
            )
            if not math.isclose(
                system_value,
                family_value,
                rel_tol=0.0,
                abs_tol=1e-8,
            ):
                reconciliation_failures += 1
        maximum_system_backlog = max(
            maximum_system_backlog, system_step["backlog_tab_dai"]
        )
        maximum_system_bad_debt = max(
            maximum_system_bad_debt, system_step["active_bad_debt_dai"]
        )
        hourly_rows.append(
            {
                "portfolio": portfolio_id,
                "replication": replication,
                "step": step,
                "family": "SYSTEM",
                **system_step,
                "raw_sampled_arrivals": float(decision.sampled_demand),
                "inventory_truncated_arrivals": float(
                    decision.demand_truncated_by_inventory
                ),
            }
        )
        response = coefficient_normalised_market_response(
            dai_price=dai_price,
            confidence=1.0,
            below_peg_response=float(stage1["below_peg_response"]),
            above_peg_response=float(stage1["above_peg_response"]),
            panic_response=0.0,
            residual_innovation=float(residuals[step]),
            min_price=0.50,
            max_price=1.50,
        )
        dai_price = response.clipped_next_price
        dai_prices.append(dai_price)

    final_debt = {
        family: float(
            sum(
                vault.debt_dai
                for vault in vaults
                if _family_from_model(vault.collateral_type) == family
                and vault.is_active
            )
        )
        for family in FAMILY_ORDER
    }
    final_collateral = {
        family: float(
            sum(
                vault.collateral_amount
                for vault in vaults
                if _family_from_model(vault.collateral_type) == family
                and vault.is_active
            )
        )
        for family in FAMILY_ORDER
    }
    debt_errors = {
        family: initial_debt[family]
        - final_debt[family]
        - totals[family]["completed_debt_dai"]
        for family in FAMILY_ORDER
    }
    collateral_errors = {
        family: initial_collateral[family]
        - final_collateral[family]
        - totals[family]["collateral_removed_units"]
        for family in FAMILY_ORDER
    }
    system_reconciles = all(
        abs(value) <= 1e-5
        for value in [*debt_errors.values(), *collateral_errors.values()]
    ) and reconciliation_failures == 0
    dai = np.asarray(dai_prices, dtype=float)
    numerical_valid = bool(
        np.isfinite(dai).all()
        and np.all(dai > 0.0)
        and maximum_attempts <= SHARED_CAPACITY
        and system_reconciles
        and price_isolation
        and owner_validation
        and not duplicate_attempt
        and not duplicate_closure
        and not state_invalid
    )
    record: dict[str, Any] = {
        "portfolio": portfolio_id,
        "replication": replication,
        "initialisation_identity": initial.identity,
        "market_start_index": market_start,
        "market_block_checksum": _payload_sha256(
            sample["pool_row_id"].astype(int).tolist()
        ),
        "vault_count": len(vaults),
        "initial_total_debt_dai": sum(initial_debt.values()),
        "cumulative_attempts": sum(
            totals[family]["selected_attempts"] for family in FAMILY_ORDER
        ),
        "cumulative_successful_closures": sum(
            totals[family]["successful_closures"] for family in FAMILY_ORDER
        ),
        "cumulative_capacity_rejected": sum(
            totals[family]["capacity_rejected"] for family in FAMILY_ORDER
        ),
        "cumulative_completed_debt_dai": sum(
            totals[family]["completed_debt_dai"] for family in FAMILY_ORDER
        ),
        "maximum_backlog_tab_dai": maximum_system_backlog,
        "maximum_active_bad_debt_dai": maximum_system_bad_debt,
        "cumulative_realised_bad_debt_dai": sum(
            totals[family]["realised_bad_debt_dai"] for family in FAMILY_ORDER
        ),
        "keeper_profit_dai": sum(
            totals[family]["keeper_profit_dai"] for family in FAMILY_ORDER
        ),
        "binding_hours": binding_hours,
        "raw_sampled_arrivals": float(
            sum(record["sampled_demand"] for record in arrival_records)
        ),
        "inventory_truncated_arrivals": float(
            sum(
                record["demand_truncated_by_inventory"]
                for record in arrival_records
            )
        ),
        "maximum_attempts_one_hour": maximum_attempts,
        "minimum_dai_price": float(np.min(dai)),
        "mean_absolute_peg_deviation": float(np.mean(np.abs(dai - 1.0))),
        "below_peg_burden": float(np.sum(np.maximum(1.0 - dai, 0.0))),
        "final_dai_price": float(dai[-1]),
        "maximum_debt_conservation_error": max(
            abs(value) for value in debt_errors.values()
        ),
        "maximum_collateral_conservation_error": max(
            abs(value) for value in collateral_errors.values()
        ),
        "hourly_reconciliation_failure_count": reconciliation_failures,
        "collateral_system_reconciliation": system_reconciles,
        "price_isolation": price_isolation,
        "silent_fallback": not owner_validation,
        "numerical_valid": numerical_valid,
        "state_invalid": state_invalid,
        "duplicate_attempt": duplicate_attempt,
        "duplicate_closure": duplicate_closure,
        "gas_path_checksum": gas_path_checksum,
        "arrival_path_checksum": _payload_sha256(arrival_records),
        "residual_path_checksum": residual_path_checksum,
        "capacity_profile_id": "shared_keeper_capacity_central",
        "capacity": SHARED_CAPACITY,
        "capacity_semantics": "system_wide_shared_capacity",
        "hurdle_profile_id": "direct_cost_only",
        "oracle_delay_steps": 0,
        "confidence_scenario_id": "stage1_only",
    }
    for family in FAMILY_ORDER:
        for metric, value in totals[family].items():
            record[f"{family}_{metric}"] = float(value)
        record[f"{family}_maximum_backlog_tab_dai"] = maximum_backlog[family]
        record[f"{family}_maximum_active_bad_debt_dai"] = maximum_bad_debt[
            family
        ]
        record[f"{family}_debt_conservation_error"] = debt_errors[family]
        record[f"{family}_collateral_conservation_error"] = collateral_errors[
            family
        ]
    return record, hourly_rows


@dataclass(frozen=True)
class DynamicValidation:
    """Compact Component C evidence and ignored replication diagnostics."""

    summary: pd.DataFrame
    replications: pd.DataFrame
    hourly: pd.DataFrame
    valid: bool


def _distribution(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    return {
        "mean": float(np.mean(array)),
        "median": float(np.median(array)),
        "p05": float(np.quantile(array, 0.05)),
        "p95": float(np.quantile(array, 0.95)),
        "minimum": float(np.min(array)),
        "maximum": float(np.max(array)),
    }


def _hourly_system_reconciliation(hourly: pd.DataFrame) -> bool:
    """Independently compare every recorded system metric with family sums."""
    keys = ["portfolio", "replication", "step"]
    metrics = [
        "unsafe_opportunities",
        "sampled_arrivals",
        "selected_attempts",
        "capacity_rejected",
        "successful_closures",
        "unprofitable_attempts",
        "completed_debt_dai",
        "backlog_tab_dai",
        "active_bad_debt_dai",
        "realised_bad_debt_dai",
        "keeper_profit_dai",
        "collateral_removed_units",
    ]
    family_rows = hourly.loc[~hourly["family"].eq("SYSTEM")]
    system_rows = hourly.loc[hourly["family"].eq("SYSTEM")]
    family_sums = family_rows.groupby(keys, sort=False)[metrics].sum()
    systems = system_rows.set_index(keys)[metrics]
    if (
        len(systems)
        != DYNAMIC_REPLICATIONS_PER_PORTFOLIO
        * len(PORTFOLIO_ORDER)
        * DYNAMIC_HOURS
        or not family_sums.index.equals(systems.index)
    ):
        return False
    return bool(
        np.allclose(
            family_sums.to_numpy(dtype=float),
            systems.to_numpy(dtype=float),
            rtol=0.0,
            atol=1e-8,
        )
    )


def run_dynamic_validation(
    collateral_payload: Mapping[str, Any],
    portfolio_payload: Mapping[str, Any],
    market_pool: pd.DataFrame,
) -> DynamicValidation:
    """Run ordinary 168-hour integration checks for every portfolio."""
    stage1_panel, _, stage1 = load_stage1_owners()
    del stage1_panel
    if (
        round(float(stage1["below_peg_response"]), 6)
        != EXPECTED_STAGE1_BELOW_PEG_RESPONSE
        or round(float(stage1["above_peg_response"]), 6)
        != EXPECTED_STAGE1_ABOVE_PEG_RESPONSE
    ):
        raise ValueError("Protected Stage 1 responses differ.")
    vault_pool = _quiet_empirical_pool(collateral_payload)
    valid_market_starts = _valid_market_block_starts(market_pool)
    records: list[dict[str, Any]] = []
    hourly: list[dict[str, Any]] = []
    for portfolio_index, portfolio_id in enumerate(PORTFOLIO_ORDER):
        for replication in range(DYNAMIC_REPLICATIONS_PER_PORTFOLIO):
            record, rows = _dynamic_replication(
                portfolio_id=portfolio_id,
                portfolio_index=portfolio_index,
                replication=replication,
                collateral_payload=collateral_payload,
                portfolio_payload=portfolio_payload,
                vault_pool=vault_pool,
                market_pool=market_pool,
                stage1=stage1,
                valid_market_starts=valid_market_starts,
            )
            records.append(record)
            hourly.extend(rows)
    replications = pd.DataFrame(records).sort_values(
        ["portfolio", "replication"], kind="mergesort"
    )
    hourly_frame = pd.DataFrame(hourly).sort_values(
        ["portfolio", "replication", "step", "family"], kind="mergesort"
    )
    metrics = (
        "cumulative_attempts",
        "cumulative_successful_closures",
        "cumulative_capacity_rejected",
        "raw_sampled_arrivals",
        "inventory_truncated_arrivals",
        "cumulative_completed_debt_dai",
        "maximum_backlog_tab_dai",
        "maximum_active_bad_debt_dai",
        "cumulative_realised_bad_debt_dai",
        "keeper_profit_dai",
        "binding_hours",
        "maximum_attempts_one_hour",
        "minimum_dai_price",
        "mean_absolute_peg_deviation",
        "below_peg_burden",
        "final_dai_price",
        "maximum_debt_conservation_error",
        "maximum_collateral_conservation_error",
    )
    summary_rows: list[dict[str, Any]] = []
    for portfolio_id in PORTFOLIO_ORDER:
        selected = replications.loc[replications["portfolio"].eq(portfolio_id)]
        for metric in metrics:
            distribution = _distribution(selected[metric].to_numpy(dtype=float))
            summary_rows.append(
                {
                    "portfolio": portfolio_id,
                    "metric": metric,
                    **distribution,
                    "replication_count": len(selected),
                    "numerical_validity_count": int(
                        selected["numerical_valid"].sum()
                    ),
                    "reconciliation_status": bool(
                        selected["collateral_system_reconciliation"].all()
                    ),
                    "price_isolation_status": bool(
                        selected["price_isolation"].all()
                    ),
                    "silent_fallback_count": int(
                        selected["silent_fallback"].sum()
                    ),
                }
            )
    summary = pd.DataFrame(summary_rows)
    hourly_reconciliation = _hourly_system_reconciliation(hourly_frame)
    valid = bool(
        len(replications)
        == DYNAMIC_REPLICATIONS_PER_PORTFOLIO * len(PORTFOLIO_ORDER)
        and replications["numerical_valid"].all()
        and replications["collateral_system_reconciliation"].all()
        and replications["price_isolation"].all()
        and ~replications["silent_fallback"].any()
        and ~replications["state_invalid"].any()
        and ~replications["duplicate_attempt"].any()
        and ~replications["duplicate_closure"].any()
        and replications["maximum_attempts_one_hour"].le(SHARED_CAPACITY).all()
        and replications["hourly_reconciliation_failure_count"].eq(0).all()
        and replications["capacity"].eq(SHARED_CAPACITY).all()
        and replications["capacity_semantics"]
        .eq("system_wide_shared_capacity")
        .all()
        and replications["hurdle_profile_id"].eq("direct_cost_only").all()
        and replications["oracle_delay_steps"].eq(0).all()
        and replications["confidence_scenario_id"].eq("stage1_only").all()
        and hourly_reconciliation
    )
    return DynamicValidation(
        summary=summary,
        replications=replications,
        hourly=hourly_frame,
        valid=valid,
    )


def classify_collateral_universe(
    *,
    volatile_owners_valid: bool,
    stable_status: str,
) -> str:
    """Apply the pre-registered collateral-universe decision hierarchy."""
    if not volatile_owners_valid:
        return "final_collateral_universe_invalid"
    if stable_status == "empirical":
        return "final_collateral_universe_ready"
    if stable_status == "counterfactual_stable_proxy":
        return "final_collateral_universe_ready_with_counterfactual_stable"
    if stable_status == "blocked":
        return "final_collateral_universe_crypto_ready_stable_blocked"
    return "final_collateral_universe_invalid"


def classify_portfolio_registry(
    *,
    registry_valid: bool,
    stable_admissible: bool,
) -> str:
    """Classify the five-portfolio registry without ranking portfolios."""
    if not registry_valid:
        return "final_portfolio_registry_invalid"
    if stable_admissible:
        return "final_portfolio_registry_ready"
    return "final_portfolio_registry_ready_with_blocked_stable_cases"


def classify_shock_registry(
    *,
    registry_valid: bool,
    stable_status: str,
) -> str:
    """Classify the result-blind seven-shock registry."""
    if not registry_valid:
        return "final_shock_registry_invalid"
    if stable_status == "empirical":
        return "final_shock_registry_ready"
    if stable_status == "counterfactual_stable_proxy":
        return "final_shock_registry_ready_with_counterfactual_stable_depegs"
    return "final_shock_registry_blocked"


def classify_shared_capacity(
    *,
    contract_valid: bool,
    blocked: bool = False,
    caveats: bool = False,
) -> str:
    """Classify the shared-capacity contract from explicit smoke evidence."""
    if blocked:
        return "shared_capacity_contract_blocked"
    if not contract_valid:
        return "shared_capacity_contract_invalid"
    if caveats:
        return "shared_capacity_contract_valid_with_caveats"
    return "shared_capacity_contract_valid"


def classify_overall_inputs(
    *,
    collateral_classification: str,
    portfolio_classification: str,
    shock_classification: str,
    shared_capacity_classification: str,
    ordinary_validation_valid: bool,
    accounting_valid: bool = True,
    price_isolation_valid: bool = True,
    protected_regressions_valid: bool = True,
) -> str:
    """Apply the pre-registered overall classification hierarchy."""
    component_values = {
        collateral_classification,
        portfolio_classification,
        shock_classification,
        shared_capacity_classification,
    }
    if (
        not accounting_valid
        or not price_isolation_valid
        or not protected_regressions_valid
        or any(value.endswith("_invalid") for value in component_values)
    ):
        return "final_multicollateral_inputs_invalid"
    if (
        not ordinary_validation_valid
        or collateral_classification.endswith("_stable_blocked")
        or portfolio_classification.endswith("_blocked_stable_cases")
        or shock_classification.endswith("_blocked")
        or shared_capacity_classification.endswith("_blocked")
    ):
        return "final_multicollateral_inputs_blocked"
    if (
        "counterfactual" in collateral_classification
        or "counterfactual" in shock_classification
        or shared_capacity_classification.endswith("_with_caveats")
    ):
        return "final_multicollateral_inputs_ready_with_caveats"
    return "final_multicollateral_inputs_ready"


def _profile_identity(profile_checksum: str) -> str:
    return _payload_sha256(
        {
            "profile_identifier": PROFILE_ID,
            "profile_checksum": profile_checksum,
            "collateral_registry_checksum": sha256_file(
                COLLATERAL_REGISTRY_PATH
            ),
            "portfolio_registry_checksum": sha256_file(
                PORTFOLIO_REGISTRY_PATH
            ),
            "shock_registry_checksum": sha256_file(SHOCK_REGISTRY_PATH),
            "market_pool_checksum": sha256_file(
                REPOSITORY_ROOT
                / "data/market/model_inputs/multicollateral_blocks/pool.csv"
            ),
            "runtime_adopted": False,
        }
    )


def _stable_ordinary_statistics(market_pool: pd.DataFrame) -> dict[str, Any]:
    prices = pd.to_numeric(market_pool["usdc_price_usd"], errors="raise")
    timestamps = pd.to_datetime(market_pool["timestamp_utc"], utc=True)
    within_one_percent = np.abs(prices.to_numpy(dtype=float) - 1.0) <= 0.01
    excluded = (
        (
            (timestamps >= pd.Timestamp("2022-11-01T00:00:00Z"))
            & (timestamps < pd.Timestamp("2022-11-21T00:00:00Z"))
        )
        | (
            (timestamps >= pd.Timestamp("2023-03-06T00:00:00Z"))
            & (timestamps < pd.Timestamp("2023-03-20T00:00:00Z"))
        )
    )
    result = {
        "observation_count": int(len(prices)),
        "within_one_percent_of_par_count": int(np.count_nonzero(within_one_percent)),
        "within_one_percent_of_par_share": float(np.mean(within_one_percent)),
        "minimum_price_usd": float(prices.min()),
        "median_price_usd": float(prices.median()),
        "maximum_price_usd": float(prices.max()),
        "excluded_interval_observation_count": int(excluded.sum()),
        "owner_status": "empirical_price_proxy_for_counterfactual_stable_collateral",
    }
    if (
        result["excluded_interval_observation_count"] != 0
        or result["within_one_percent_of_par_share"] < 0.99
    ):
        raise ValueError("The clean stable ordinary-price owner failed validation.")
    return result


def _decision_payload(
    *,
    profile_checksum: str,
    initialisation: InitialisationValidation,
    shocks: pd.DataFrame,
    tails: Mapping[str, Any],
    shared: SharedCapacityValidation,
    dynamic: DynamicValidation,
    stable_ordinary: Mapping[str, Any],
) -> dict[str, Any]:
    collateral_classification = classify_collateral_universe(
        volatile_owners_valid=True,
        stable_status="counterfactual_stable_proxy",
    )
    portfolio_classification = classify_portfolio_registry(
        registry_valid=(
            initialisation.classification == "final_portfolio_registry_ready"
        ),
        stable_admissible=True,
    )
    shock_classification = classify_shock_registry(
        registry_valid=(
            len(shocks) == len(SHOCK_ORDER) * len(FAMILY_ORDER)
            and all(tails["price_isolation"].values())
        ),
        stable_status="counterfactual_stable_proxy",
    )
    shared_classification = classify_shared_capacity(
        contract_valid=(
            shared.classification == "shared_capacity_contract_valid"
        )
    )
    overall = classify_overall_inputs(
        collateral_classification=collateral_classification,
        portfolio_classification=portfolio_classification,
        shock_classification=shock_classification,
        shared_capacity_classification=shared_classification,
        ordinary_validation_valid=dynamic.valid,
        accounting_valid=bool(
            dynamic.replications["collateral_system_reconciliation"].all()
        ),
        price_isolation_valid=bool(
            dynamic.replications["price_isolation"].all()
            and all(tails["price_isolation"].values())
        ),
        protected_regressions_valid=True,
    )
    experiment_ready = overall in {
        "final_multicollateral_inputs_ready",
        "final_multicollateral_inputs_ready_with_caveats",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_identifier": PROFILE_ID,
        "profile_identity": _profile_identity(profile_checksum),
        "profile_checksum": profile_checksum,
        "collateral_universe_classification": collateral_classification,
        "portfolio_classification": portfolio_classification,
        "shock_classification": shock_classification,
        "shared_capacity_classification": shared_classification,
        "overall_classification": overall,
        "stable_collateral_status": "counterfactual_stable_proxy",
        "stable_ordinary_process": dict(stable_ordinary),
        "caveats": [
            "The stable-vault distribution and protocol parameters are an existing transparent counterfactual owner, not empirical Maker stable-collateral evidence.",
            "The clean local USDC series owns only ordinary stable-price variation and excludes the USDC/SVB interval.",
            "Shared capacity 26 is partially identified and is not a physical keeper-network maximum.",
            "Population robustness, oracle-delay robustness and held-out validation remain outstanding.",
        ],
        "authorised_next_boundary": (
            "pre-register and execute the final hierarchical multi-collateral "
            "experiments: idiosyncratic diversification, stress correlation, "
            "stable-collateral trade-off and shared keeper capacity"
            if experiment_ready
            else "resolve multi-collateral integration blocker"
        ),
        "experiment_ready": experiment_ready,
        "no_portfolio_selected": True,
        "no_shock_selected_by_model_outcome": True,
        "no_substantive_experiment": True,
        "no_parameter_recalibration": True,
        "no_keeper_recalibration": True,
        "no_confidence_recalibration": True,
        "final_validation_data_used": False,
        "usdc_svb_used": False,
        "runtime_adopted": False,
    }


def _reproducibility_payload(
    *,
    profile_checksum: str,
    specification: Mapping[str, Any],
    market_pool: pd.DataFrame,
    initialisation: InitialisationValidation,
    shared: SharedCapacityValidation,
    dynamic: DynamicValidation,
    tails: Mapping[str, Any],
) -> dict[str, Any]:
    market_path = (
        REPOSITORY_ROOT
        / "data/market/model_inputs/multicollateral_blocks/pool.csv"
    )
    market_manifest = (
        REPOSITORY_ROOT
        / "data/market/model_inputs/multicollateral_blocks/manifest.json"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "scientific_code_identity": scientific_code_identity(),
        "specification_identity": specification["specification_identity"],
        "profile_identifier": PROFILE_ID,
        "profile_identity": _profile_identity(profile_checksum),
        "profile_checksum": profile_checksum,
        "registry_checksums": {
            "collateral": sha256_file(COLLATERAL_REGISTRY_PATH),
            "portfolio": sha256_file(PORTFOLIO_REGISTRY_PATH),
            "shock": sha256_file(SHOCK_REGISTRY_PATH),
        },
        "market_pool": {
            "path": _relative(market_path),
            "sha256": sha256_file(market_path),
            "rows": int(len(market_pool)),
            "columns": int(len(market_pool.columns)),
            "manifest_path": _relative(market_manifest),
            "manifest_sha256": sha256_file(market_manifest),
        },
        "seed_registry": seed_registry(),
        "validation_counts": {
            "initialisations": int(len(initialisation.replications)),
            "dynamic_replications": int(len(dynamic.replications)),
            "dynamic_hours_per_replication": DYNAMIC_HOURS,
            "shared_capacity_smokes": int(len(shared.summary)),
        },
        "tail_derivation": {
            "ETH": tails["ETH"],
            "WBTC": tails["WBTC"],
            "joint_empirical": tails["joint_empirical"],
        },
        "deterministic_reconstruction": True,
        "protected_regression_hashes": PROTECTED_REGRESSIONS,
        "live_network_calls": 0,
        "acquisition_calls": 0,
        "parameter_recalibration": False,
        "keeper_recalibration": False,
        "confidence_recalibration": False,
        "substantive_final_experiment": False,
        "portfolio_ranking": False,
        "shock_ranking_by_model_outcome": False,
        "final_validation_data_used": False,
        "usdc_svb_used": False,
        "runtime_adopted": False,
    }


def _benchmark_payload(
    *,
    wall_time: float,
    output_size: int,
    free_storage: int,
    worker_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "initialisation_count": (
            INITIALISATIONS_PER_PORTFOLIO * len(PORTFOLIO_ORDER)
        ),
        "dynamic_validation_count": (
            DYNAMIC_REPLICATIONS_PER_PORTFOLIO * len(PORTFOLIO_ORDER)
        ),
        "dynamic_hours": DYNAMIC_HOURS,
        "smoke_count": 6,
        "workers": worker_count,
        "wall_time_seconds": wall_time,
        "ignored_output_size_bytes": output_size,
        "output_cap_bytes": OUTPUT_CAP_BYTES,
        "free_storage_bytes": free_storage,
        "minimum_free_storage_bytes": MINIMUM_FREE_BYTES,
        "host_dependent": True,
    }


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _write_detailed_outputs(
    path: Path,
    *,
    initialisation: InitialisationValidation,
    shared: SharedCapacityValidation,
    dynamic: DynamicValidation,
    tails: Mapping[str, Any],
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _atomic_bytes(
        path / "initialisation_replications.csv",
        _csv_bytes(initialisation.replications),
    )
    _atomic_bytes(
        path / "shared_capacity_candidate_traces.csv",
        _csv_bytes(shared.traces),
    )
    _atomic_bytes(
        path / "dynamic_replications.csv",
        _csv_bytes(dynamic.replications),
    )
    _atomic_bytes(
        path / "dynamic_hourly_collateral_and_system.csv",
        _csv_bytes(dynamic.hourly),
    )
    _atomic_bytes(path / "market_tail_statistics.json", _pretty_json(tails))
    _atomic_bytes(path / "seed_registry.json", _pretty_json(seed_registry()))


def _compact_payloads(
    *,
    specification: Mapping[str, Any],
    collateral: pd.DataFrame,
    protocol: pd.DataFrame,
    portfolios: pd.DataFrame,
    shocks: pd.DataFrame,
    initialisation: InitialisationValidation,
    shared: SharedCapacityValidation,
    dynamic: DynamicValidation,
    decision: Mapping[str, Any],
    reproducibility: Mapping[str, Any],
    benchmark: Mapping[str, Any],
) -> dict[str, bytes]:
    return {
        "multicollateral_integration_specification.json": _pretty_json(
            specification
        ),
        "final_collateral_registry.csv": _csv_bytes(collateral),
        "final_protocol_parameters.csv": _csv_bytes(protocol),
        "final_portfolio_registry.csv": _csv_bytes(portfolios),
        "final_shock_registry.csv": _csv_bytes(shocks),
        "multicollateral_initialisation_validation.csv": _csv_bytes(
            initialisation.summary
        ),
        "multicollateral_shared_capacity_validation.csv": _csv_bytes(
            shared.summary
        ),
        "multicollateral_dynamic_validation.csv": _csv_bytes(dynamic.summary),
        "multicollateral_integration_decision.json": _pretty_json(decision),
        "multicollateral_integration_reproducibility.json": _pretty_json(
            reproducibility
        ),
        "multicollateral_integration_benchmark.json": _pretty_json(benchmark),
    }


def _manifest_payload(
    evidence_dir: Path,
    *,
    manifest_path: Path = VALIDATION_MANIFEST,
) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    if manifest_path.exists():
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("Validation manifest must be a JSON object.")
        if loaded.get("schema_version") != 1 or loaded.get("domain") != "validation":
            raise ValueError("Validation manifest identity differs.")
        if not isinstance(loaded.get("entries"), list):
            raise ValueError("Validation manifest entries must be a list.")
        existing = loaded
    owned_entries = []
    for name in COMPACT_FILENAMES:
        path = evidence_dir / name
        owned_entries.append(
            {
                "path": _relative(path),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "semantic_owner": VALIDATION_OWNER,
                "runtime_input": False,
            }
        )
    retained = [
        dict(entry)
        for entry in existing.get("entries", [])
        if entry.get("semantic_owner") != VALIDATION_OWNER
    ]
    owned_paths = {entry["path"] for entry in owned_entries}
    if any(entry.get("path") in owned_paths for entry in retained):
        raise ValueError("Validation manifest path ownership conflicts.")
    entries = sorted(
        [*retained, *owned_entries],
        key=lambda entry: str(entry.get("path", "")),
    )
    paths = [entry.get("path") for entry in entries]
    if (
        any(not isinstance(path, str) or not path for path in paths)
        or len(set(paths)) != len(paths)
    ):
        raise ValueError("Validation manifest paths are invalid or duplicated.")
    payload = dict(existing)
    payload.update(
        {
            "schema_version": 1,
            "domain": "validation",
            "entries": entries,
            "entry_count": len(entries),
            "duplicate_paths": 0,
        }
    )
    return payload


def execute_multicollateral_validation(
    *,
    evidence_dir: Path = EVIDENCE_DIR,
    diagnostic_root: Path = DIAGNOSTIC_ROOT,
    worker_count: int = 1,
) -> dict[str, Any]:
    """Execute Components A-D without running a final experiment matrix."""
    if worker_count != 1:
        raise ValueError("Deterministic integration validation owns one worker.")
    free_before = shutil.disk_usage(REPOSITORY_ROOT).free
    if free_before < MINIMUM_FREE_BYTES:
        raise ValueError("Fewer than 10 GiB are free before validation.")
    collateral_payload, portfolio_payload, shock_payload, _ = _design_payloads()
    specification = write_preregistration(evidence_dir)
    started = time.perf_counter()

    resolved = {
        identifier: resolve_multicollateral_inputs(identifier)
        for identifier in PORTFOLIO_ORDER
    }
    for shock_id in SHOCK_ORDER:
        resolve_multicollateral_inputs("empirical_crypto", shock_id)
    profile = resolved["eth_only"].profile
    if not profile.experiment_ready or profile.runtime_adopted:
        raise ValueError("Final profile readiness/adoption state differs.")

    market_pool = load_final_market_pool(profile.market_pool_path)
    stable_ordinary = _stable_ordinary_statistics(market_pool)
    collateral_frame = collateral_registry_frame(collateral_payload)
    protocol_frame = protocol_parameters_frame(collateral_payload)
    portfolio_frame = portfolio_registry_frame(portfolio_payload)
    shock_frame, tails = shock_registry_frame(shock_payload, market_pool)
    initialisation = run_initialisation_validation(
        collateral_payload, portfolio_payload
    )
    shared = run_shared_capacity_validation(collateral_payload)
    dynamic = run_dynamic_validation(
        collateral_payload, portfolio_payload, market_pool
    )
    decision = _decision_payload(
        profile_checksum=profile.checksum,
        initialisation=initialisation,
        shocks=shock_frame,
        tails=tails,
        shared=shared,
        dynamic=dynamic,
        stable_ordinary=stable_ordinary,
    )
    reproducibility = _reproducibility_payload(
        profile_checksum=profile.checksum,
        specification=specification,
        market_pool=market_pool,
        initialisation=initialisation,
        shared=shared,
        dynamic=dynamic,
        tails=tails,
    )
    diagnostic_path = (
        diagnostic_root / str(specification["specification_identity"])[:16]
    )
    _write_detailed_outputs(
        diagnostic_path,
        initialisation=initialisation,
        shared=shared,
        dynamic=dynamic,
        tails=tails,
    )
    output_size = _directory_size(diagnostic_path)
    if output_size > OUTPUT_CAP_BYTES:
        raise ValueError("Multi-collateral diagnostics exceed 300 MB.")
    elapsed = time.perf_counter() - started
    benchmark = _benchmark_payload(
        wall_time=elapsed,
        output_size=output_size,
        free_storage=shutil.disk_usage(REPOSITORY_ROOT).free,
        worker_count=worker_count,
    )
    first = _compact_payloads(
        specification=specification,
        collateral=collateral_frame,
        protocol=protocol_frame,
        portfolios=portfolio_frame,
        shocks=shock_frame,
        initialisation=initialisation,
        shared=shared,
        dynamic=dynamic,
        decision=decision,
        reproducibility=reproducibility,
        benchmark=benchmark,
    )
    second = _compact_payloads(
        specification=specification,
        collateral=collateral_frame,
        protocol=protocol_frame,
        portfolios=portfolio_frame,
        shocks=shock_frame,
        initialisation=initialisation,
        shared=shared,
        dynamic=dynamic,
        decision=decision,
        reproducibility=reproducibility,
        benchmark=benchmark,
    )
    for name in DETERMINISTIC_FILENAMES:
        if first[name] != second[name]:
            raise ValueError(f"Non-deterministic compact evidence: {name}.")
    for name, payload in first.items():
        _atomic_bytes(evidence_dir / name, payload)
    manifest = _manifest_payload(evidence_dir)
    _atomic_bytes(VALIDATION_MANIFEST, _pretty_json(manifest))
    validation = validate_compact_evidence(evidence_dir)
    return {
        **validation,
        "compact_evidence": {
            name: {
                "path": _relative(evidence_dir / name),
                "sha256": sha256_file(evidence_dir / name),
                "bytes": (evidence_dir / name).stat().st_size,
            }
            for name in COMPACT_FILENAMES
        },
        "diagnostic_path": _relative(diagnostic_path),
        "diagnostic_size_bytes": output_size,
        "wall_time_seconds": elapsed,
    }


def validate_compact_evidence(
    evidence_dir: Path = EVIDENCE_DIR,
    *,
    manifest_path: Path = VALIDATION_MANIFEST,
) -> dict[str, Any]:
    """Validate the frozen evidence schemas, decisions and shared manifest."""
    missing = [
        name for name in COMPACT_FILENAMES if not (evidence_dir / name).is_file()
    ]
    if missing:
        raise ValueError(f"Missing multi-collateral evidence: {missing}.")
    specification = json.loads(
        (evidence_dir / COMPACT_FILENAMES[0]).read_text(encoding="utf-8")
    )
    decision = json.loads(
        (
            evidence_dir / "multicollateral_integration_decision.json"
        ).read_text(encoding="utf-8")
    )
    reproducibility = json.loads(
        (
            evidence_dir / "multicollateral_integration_reproducibility.json"
        ).read_text(encoding="utf-8")
    )
    collateral = pd.read_csv(evidence_dir / "final_collateral_registry.csv")
    protocol = pd.read_csv(evidence_dir / "final_protocol_parameters.csv")
    portfolios = pd.read_csv(evidence_dir / "final_portfolio_registry.csv")
    shocks = pd.read_csv(evidence_dir / "final_shock_registry.csv")
    initialisation = pd.read_csv(
        evidence_dir / "multicollateral_initialisation_validation.csv"
    )
    shared = pd.read_csv(
        evidence_dir / "multicollateral_shared_capacity_validation.csv"
    )
    dynamic = pd.read_csv(
        evidence_dir / "multicollateral_dynamic_validation.csv"
    )
    if specification.get("result_fields_excluded") is not True:
        raise ValueError("The pre-registration contains result fields.")
    if (
        decision.get("overall_classification")
        != "final_multicollateral_inputs_ready_with_caveats"
        or decision.get("experiment_ready") is not True
        or decision.get("runtime_adopted") is not False
    ):
        raise ValueError("Final multi-collateral decision differs.")
    if (
        decision.get("collateral_universe_classification")
        != "final_collateral_universe_ready_with_counterfactual_stable"
        or decision.get("portfolio_classification")
        != "final_portfolio_registry_ready"
        or decision.get("shock_classification")
        != "final_shock_registry_ready_with_counterfactual_stable_depegs"
        or decision.get("shared_capacity_classification")
        != "shared_capacity_contract_valid"
    ):
        raise ValueError("Component classifications differ.")
    if (
        set(collateral["family"]) != set(FAMILY_ORDER)
        or set(collateral["exact_ilk"].dropna())
        != {"ETH-A", "ETH-B", "ETH-C", "WBTC-A", "WBTC-B", "WBTC-C"}
        or len(collateral) != 7
    ):
        raise ValueError("Final collateral evidence differs.")
    if (
        len(protocol) != 14
        or set(protocol["parameter"])
        != {"liquidation_ratio", "liquidation_penalty_rate"}
        or not protocol["model_operational"].astype(bool).all()
    ):
        raise ValueError("Final protocol evidence differs.")
    if (
        len(portfolios) != len(PORTFOLIO_ORDER) * len(FAMILY_ORDER)
        or portfolios["portfolio"].drop_duplicates().tolist()
        != list(PORTFOLIO_ORDER)
        or portfolios["portfolio_selected"].astype(bool).any()
    ):
        raise ValueError("Final portfolio evidence differs.")
    if (
        len(shocks) != len(SHOCK_ORDER) * len(FAMILY_ORDER)
        or shocks["shock_identifier"].drop_duplicates().tolist()
        != list(SHOCK_ORDER)
        or shocks["selection_uses_model_outcomes"].astype(bool).any()
        or shocks["usdc_svb_used"].astype(bool).any()
        or shocks["final_validation_data_used"].astype(bool).any()
    ):
        raise ValueError("Final shock evidence differs.")
    if (
        len(initialisation) != 105
        or not initialisation["initialisation_count"].eq(
            INITIALISATIONS_PER_PORTFOLIO
        ).all()
        or not initialisation["deterministic_status"].astype(bool).all()
    ):
        raise ValueError("Initialisation evidence differs.")
    if (
        len(shared) != 6
        or shared["total_attempts"].gt(SHARED_CAPACITY).any()
        or not shared["ranking_validation"].astype(bool).all()
        or not shared["permutation_validation"].astype(bool).all()
        or not shared["accounting_validation"].astype(bool).all()
        or not shared["backlog_persistence_validation"].astype(bool).all()
    ):
        raise ValueError("Shared-capacity evidence differs.")
    if (
        len(dynamic) != 90
        or not dynamic["replication_count"].eq(
            DYNAMIC_REPLICATIONS_PER_PORTFOLIO
        ).all()
        or not dynamic["numerical_validity_count"].eq(
            DYNAMIC_REPLICATIONS_PER_PORTFOLIO
        ).all()
        or not dynamic["reconciliation_status"].astype(bool).all()
        or not dynamic["price_isolation_status"].astype(bool).all()
        or not dynamic["silent_fallback_count"].eq(0).all()
    ):
        raise ValueError("Ordinary dynamic evidence differs.")
    forbidden_true = (
        "final_validation_data_used",
        "usdc_svb_used",
        "parameter_recalibration",
        "keeper_recalibration",
        "confidence_recalibration",
        "substantive_final_experiment",
        "portfolio_ranking",
        "shock_ranking_by_model_outcome",
        "runtime_adopted",
    )
    if any(reproducibility.get(name) is not False for name in forbidden_true):
        raise ValueError("A prohibited validation activity was recorded.")
    if reproducibility.get("validation_counts") != {
        "dynamic_hours_per_replication": DYNAMIC_HOURS,
        "dynamic_replications": DYNAMIC_REPLICATIONS_PER_PORTFOLIO
        * len(PORTFOLIO_ORDER),
        "initialisations": INITIALISATIONS_PER_PORTFOLIO * len(PORTFOLIO_ORDER),
        "shared_capacity_smokes": 6,
    }:
        raise ValueError("Validation counts differ.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries")
    if not isinstance(entries, list) or manifest.get("entry_count") != len(entries):
        raise ValueError("Shared validation manifest is malformed.")
    owned = [
        entry
        for entry in entries
        if entry.get("semantic_owner") == VALIDATION_OWNER
    ]
    expected_paths = {
        _relative(evidence_dir / name) for name in COMPACT_FILENAMES
    }
    if (
        len(owned) != len(COMPACT_FILENAMES)
        or {entry.get("path") for entry in owned} != expected_paths
    ):
        raise ValueError("Multi-collateral manifest ownership differs.")
    for entry in entries:
        relative = entry.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError("Validation manifest paths must be repository-relative.")
        path = (REPOSITORY_ROOT / relative).resolve()
        try:
            path.relative_to(REPOSITORY_ROOT)
        except ValueError as error:
            raise ValueError("Validation manifest path escapes repository.") from error
        if sha256_file(path) != entry.get("sha256"):
            raise ValueError(f"Manifest checksum mismatch: {relative}.")
    for name in COMPACT_FILENAMES:
        text = (evidence_dir / name).read_text(encoding="utf-8")
        if "/Users/" in text or "/private/tmp/" in text:
            raise ValueError(f"Local absolute path entered compact evidence: {name}.")
    return {
        "profile_identifier": PROFILE_ID,
        "profile_identity": decision["profile_identity"],
        "profile_checksum": decision["profile_checksum"],
        "specification_identity": specification["specification_identity"],
        "scientific_code_identity": reproducibility["scientific_code_identity"],
        "collateral_universe_classification": decision[
            "collateral_universe_classification"
        ],
        "portfolio_classification": decision["portfolio_classification"],
        "shock_classification": decision["shock_classification"],
        "shared_capacity_classification": decision[
            "shared_capacity_classification"
        ],
        "overall_classification": decision["overall_classification"],
        "manifest_entry_count": len(owned),
        "validation_manifest_total_entry_count": len(entries),
        "deterministic_reconstruction": reproducibility[
            "deterministic_reconstruction"
        ],
        "experiment_ready": decision["experiment_ready"],
        "runtime_adopted": decision["runtime_adopted"],
    }
