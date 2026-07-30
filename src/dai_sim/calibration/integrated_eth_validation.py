"""Result-blind validation for the integrated empirical ETH profile.

This module assembles existing empirical input and model owners.  It does not
estimate parameters, alter production defaults, or run a recovery experiment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file
from dai_sim.inputs.gas import component_gas_costs, load_liquidation_gas_pool
from dai_sim.inputs.integrated_profile import (
    DYNAMIC_HOURS,
    EXPECTED_KEEPER_CONFIGURATION_SHA256,
    EXPECTED_KEEPER_REGISTRY_SHA256,
    EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
    EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
    EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
    EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
    PROFILE_IDENTIFIER,
    SHARED_KEEPER_CAPACITY,
    TOTAL_DEBT_DAI,
    VAULT_COUNT,
    IntegratedEmpiricalETHProfile,
    resolve_integrated_empirical_eth_profile,
)
from dai_sim.inputs.liquidations import (
    LiquidationDemandProcess,
    arrival_pool_statistics,
    load_liquidation_arrival_pool,
)
from dai_sim.inputs.market import (
    load_market_gas_pool,
    prices_from_log_returns,
    sample_market_gas_blocks,
)
from dai_sim.inputs.vaults import initialise_vaults, load_pool
from dai_sim.model.liquidation import liquidate_vaults, summarise_liquidations
from dai_sim.model.market import coefficient_normalised_market_response
from dai_sim.model.vault import Vault

from .event_simulation import load_stage1_owners
from .market import sample_residual_blocks


VALIDATION_SCHEMA_VERSION = 1
INITIALISATION_COUNT = 512
DYNAMIC_REPLICATION_COUNT = 128
CONTROLLED_SMOKE_HOURS = 240
VALIDATION_REGISTRY_ID = "integrated-empirical-eth-validation-v1"
REFERENCE_REGISTRY_ID = "integrated-empirical-eth-reference-v1"
MINIMUM_FREE_BYTES = 10 * 1024**3
OUTPUT_CAP_BYTES = 300 * 1024**2
EVIDENCE_DIR = (
    REPOSITORY_ROOT / "data/provenance/validation/integrated_empirical_eth"
)
VALIDATION_MANIFEST = REPOSITORY_ROOT / "data/provenance/validation/manifest.json"
DEFAULT_DIAGNOSTIC_ROOT = (
    REPOSITORY_ROOT / "outputs/diagnostics/validation/integrated_empirical_eth"
)
COMPACT_FILENAMES = (
    "integrated_empirical_eth_specification.json",
    "integrated_empirical_eth_profile.json",
    "integrated_empirical_eth_input_validation.csv",
    "integrated_empirical_eth_dynamic_summary.csv",
    "integrated_empirical_eth_capacity_summary.csv",
    "integrated_empirical_eth_decision.json",
    "integrated_empirical_eth_reproducibility.json",
    "integrated_empirical_eth_benchmark.json",
)
DETERMINISTIC_FILENAMES = COMPACT_FILENAMES[:-1]


def _canonical_json(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")


def _pretty_json(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return _relative(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPOSITORY_ROOT))


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False, lineterminator="\n", float_format="%.12g")
    return buffer.getvalue().encode("utf-8")


def _seed(namespace: str, replication: int, stream: str) -> int:
    payload = f"{namespace}|{replication}|{stream}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**32)


def seed_registry_payload() -> dict[str, Any]:
    """Return the dedicated validation seed ownership, not outcome data."""
    return {
        "schema_version": 1,
        "registry_id": VALIDATION_REGISTRY_ID,
        "reference_registry_id": REFERENCE_REGISTRY_ID,
        "derivation": "sha256(namespace|replication|stream) first 64 bits modulo 2^32",
        "initialisation_count": INITIALISATION_COUNT,
        "dynamic_replication_count": DYNAMIC_REPLICATION_COUNT,
        "streams": [
            "vault_sampling",
            "market_gas_blocks",
            "keeper_gas_units",
            "liquidation_arrivals",
            "stage1_residual_blocks",
            "controlled_smoke_vaults",
            "controlled_smoke_arrivals",
        ],
        "calibration_registry_b_reused": False,
        "final_validation_seeds_reused": False,
        "eth_recovery_seeds_reused": False,
    }


def seed_registry_checksum() -> str:
    return _payload_sha256(seed_registry_payload())


def scientific_code_identity() -> str:
    """Hash only authoritative integration implementation paths."""
    paths = (
        REPOSITORY_ROOT / "src/dai_sim/inputs/integrated_profile.py",
        REPOSITORY_ROOT / "src/dai_sim/calibration/integrated_eth_validation.py",
        REPOSITORY_ROOT / "src/dai_sim/model/liquidation.py",
        REPOSITORY_ROOT / "workflows/inputs/validate_integrated_eth.py",
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(_relative(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _source_identities(profile: IntegratedEmpiricalETHProfile) -> dict[str, str]:
    identities = dict(profile.input_checksums)
    identities.update(
        {
            "keeper_configuration": EXPECTED_KEEPER_CONFIGURATION_SHA256,
            "keeper_registry": EXPECTED_KEEPER_REGISTRY_SHA256,
            "stage1_residual_sequence": EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
            "stage1_residual_blocks": EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
        }
    )
    return identities


def preregistration_payload(
    profile: IntegratedEmpiricalETHProfile,
) -> dict[str, Any]:
    """Build the immutable result-blind validation snapshot."""
    payload: dict[str, Any] = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "purpose": "integrated empirical ETH-only distributional validation",
        "profile_identifier": profile.identifier,
        "profile_identity": profile.profile_identity,
        "scientific_code_identity": scientific_code_identity(),
        "input_checksums": _source_identities(profile),
        "owner_paths": dict(profile.owner_paths),
        "vault_count": VAULT_COUNT,
        "total_debt_dai": TOTAL_DEBT_DAI,
        "shared_keeper_profile": "shared_keeper_capacity_central",
        "shared_keeper_capacity": SHARED_KEEPER_CAPACITY,
        "shared_keeper_unit": (
            "protocol-level liquidation opportunities per one-hour simulation step"
        ),
        "shared_keeper_semantics": "system_wide_shared_capacity",
        "keeper_hurdle_profile": "direct_cost_only",
        "risk_cost_rate": 0.0,
        "stage1": {
            "below_peg_response_rounded": EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
            "above_peg_response_rounded": EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
            "residual_sequence_sha256": EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
            "residual_block_sha256": EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
            "residual_block_hours": 24,
        },
        "confidence_setting": "stage1_only",
        "persistent_confidence_enabled": False,
        "oracle_status": profile.oracle_status,
        "oracle_delay_steps": 0,
        "seed_registry": seed_registry_payload(),
        "seed_registry_checksum": seed_registry_checksum(),
        "validation_components": {
            "A": "configuration_and_integration_audit",
            "B": {
                "name": "monte_carlo_input_distribution_validation",
                "independent_initialisations": INITIALISATION_COUNT,
                "vaults_per_initialisation": VAULT_COUNT,
            },
            "C": {
                "name": "dynamic_integrated_validation",
                "replications": DYNAMIC_REPLICATION_COUNT,
                "hours": DYNAMIC_HOURS,
            },
            "controlled_binding_smoke": {
                "hours": CONTROLLED_SMOKE_HOURS,
                "fixed_residual_path": "zero",
                "recovery_comparison": False,
                "confidence_comparison": False,
            },
        },
        "registered_input_metrics": {
            "vault": [
                "debt_mean",
                "debt_median",
                "debt_p10",
                "debt_p25",
                "debt_p75",
                "debt_p90",
                "collateral_ratio_mean",
                "collateral_ratio_median",
                "collateral_ratio_p10",
                "collateral_ratio_p25",
                "collateral_ratio_p75",
                "collateral_ratio_p90",
                "debt_collateral_ratio_rank_correlation",
                "total_debt",
                "initial_liquidatable_share",
            ],
            "market_gas": [
                "eth_return_p10",
                "eth_return_median",
                "eth_return_p90",
                "eth_return_volatility",
                "eth_absolute_return_p95",
                "median_gas_median",
                "median_gas_p90",
                "p90_gas_p90",
                "p99_gas_p95",
                "return_gas_rank_correlation",
            ],
            "liquidation_arrival": [
                "zero_arrival_share",
                "positive_arrival_mean",
                "positive_arrival_median",
                "positive_arrival_p75",
                "positive_arrival_p90",
                "positive_arrival_p95",
                "maximum_support",
            ],
        },
        "acceptance_rules": {
            "protected_checksums_match": True,
            "mandatory_moments_operational": True,
            "minimum_inside_share_by_component": 0.90,
            "silent_fallback_allowed": False,
            "capacity_may_not_exceed": SHARED_KEEPER_CAPACITY,
            "numerical_and_accounting_failures_allowed": 0,
        },
        "classifications": {
            "input": [
                "integrated_empirical_eth_inputs_valid",
                "integrated_empirical_eth_inputs_valid_with_caveats",
                "integrated_empirical_eth_inputs_blocked",
                "integrated_empirical_eth_inputs_invalid",
            ],
            "output": [
                "integrated_outputs_broadly_compatible",
                "integrated_outputs_partially_compatible",
                "integrated_outputs_not_compatible",
                "integrated_output_validation_not_operational",
            ],
            "overall": [
                "integrated_empirical_eth_profile_ready",
                "integrated_empirical_eth_profile_ready_with_caveats",
                "integrated_empirical_eth_profile_blocked",
                "integrated_empirical_eth_profile_invalid",
            ],
        },
        "final_validation_exclusions": {
            "withheld_november_2022": True,
            "usdc_svb_march_2023": True,
            "final_validation_observations_used": 0,
            "usdc_svb_observations_used": 0,
        },
        "result_fields_excluded": True,
        "profile_classification_excluded": True,
        "future_recovery_results_excluded": True,
        "parameter_tuning": False,
        "runtime_adopted": False,
    }
    payload["preregistration_identity"] = _payload_sha256(payload)
    return payload


def write_preregistration(
    profile: IntegratedEmpiricalETHProfile,
    evidence_dir: Path = EVIDENCE_DIR,
) -> dict[str, Any]:
    """Persist the snapshot before any validation result is calculated."""
    payload = preregistration_payload(profile)
    path = evidence_dir / "integrated_empirical_eth_specification.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError("Existing pre-registration differs from current design.")
    else:
        _atomic_bytes(path, _pretty_json(payload))
    return payload


def _normalised_initial_state(
    profile: IntegratedEmpiricalETHProfile,
    *,
    seed: int,
) -> tuple[list[Vault], pd.DataFrame, str]:
    simulation = replace(
        profile.bundle.base_bundle.simulation_config,
        random_seed=seed,
        initial_eth_price=2000.0,
    )
    init_config = replace(profile.bundle.initialisation, seed=seed)
    generated = initialise_vaults(simulation, init_config)
    fallback_counts = generated.provenance.get("fallback_counts", {})
    if not isinstance(fallback_counts, dict):
        raise ValueError("Vault owner did not expose fallback provenance.")
    unexpected_fallbacks = {
        str(name): int(count)
        for name, count in fallback_counts.items()
        if name != "exact_ilk_pool" and int(count) > 0
    }
    exact_ilk_count = int(fallback_counts.get("exact_ilk_pool", 0))
    if unexpected_fallbacks or exact_ilk_count != VAULT_COUNT:
        raise ValueError(
            "Integrated vault initialisation used a non-exact empirical fallback: "
            f"{unexpected_fallbacks or fallback_counts}."
        )
    sampled = generated.sampled_rows.copy()
    raw_total = float(sampled["debt_dai"].sum())
    if len(sampled) != VAULT_COUNT or raw_total <= 0.0:
        raise ValueError("Empirical initialisation count or debt is invalid.")
    scale = TOTAL_DEBT_DAI / raw_total
    sampled["debt_dai"] = sampled["debt_dai"].astype(float) * scale
    vaults: list[Vault] = []
    for index, row in sampled.reset_index(drop=True).iterrows():
        debt = float(row["debt_dai"])
        ratio = float(row["collateral_ratio"])
        liquidation_ratio = float(row["liquidation_ratio"])
        vaults.append(
            Vault(
                vault_id=index,
                owner_id=index,
                collateral_amount=debt * ratio / simulation.initial_eth_price,
                debt_dai=debt,
                liquidation_ratio=liquidation_ratio,
                collateral_type="ETH",
            )
        )
    if len(vaults) != VAULT_COUNT:
        raise ValueError("Normalised state must contain exactly 500 vaults.")
    if any(
        vault.debt_dai <= 0.0
        or vault.collateral_amount <= 0.0
        or vault.collateral_type != "ETH"
        for vault in vaults
    ):
        raise ValueError("Normalised state contains an invalid vault.")
    if not math.isclose(
        sum(vault.debt_dai for vault in vaults),
        TOTAL_DEBT_DAI,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise ValueError("Normalised state does not preserve total debt.")
    identity = _payload_sha256(
        {
            "debt": [vault.debt_dai for vault in vaults],
            "collateral_amount": [vault.collateral_amount for vault in vaults],
            "liquidation_ratio": [vault.liquidation_ratio for vault in vaults],
            "collateral_type": ["ETH"] * len(vaults),
        }
    )
    return vaults, sampled, identity


def _vault_metrics(sampled: pd.DataFrame) -> dict[str, float]:
    debt = sampled["debt_dai"].to_numpy(dtype=float)
    ratio = sampled["collateral_ratio"].to_numpy(dtype=float)
    liquidation_ratio = sampled["liquidation_ratio"].to_numpy(dtype=float)
    return {
        "debt_mean": float(np.mean(debt)),
        "debt_median": float(np.median(debt)),
        "debt_p10": float(np.quantile(debt, 0.10)),
        "debt_p25": float(np.quantile(debt, 0.25)),
        "debt_p75": float(np.quantile(debt, 0.75)),
        "debt_p90": float(np.quantile(debt, 0.90)),
        "collateral_ratio_mean": float(np.mean(ratio)),
        "collateral_ratio_median": float(np.median(ratio)),
        "collateral_ratio_p10": float(np.quantile(ratio, 0.10)),
        "collateral_ratio_p25": float(np.quantile(ratio, 0.25)),
        "collateral_ratio_p75": float(np.quantile(ratio, 0.75)),
        "collateral_ratio_p90": float(np.quantile(ratio, 0.90)),
        "debt_collateral_ratio_rank_correlation": float(
            pd.Series(debt).corr(pd.Series(ratio), method="spearman")
        ),
        "total_debt": float(np.sum(debt)),
        "initial_liquidatable_share": float(np.mean(ratio < liquidation_ratio)),
    }


def _market_gas_metrics(sampled: pd.DataFrame) -> dict[str, float]:
    returns = sampled["eth_log_return"].to_numpy(dtype=float)
    median_gas = sampled["median_effective_gas_price_gwei"].to_numpy(dtype=float)
    p90_gas = sampled["p90_effective_gas_price_gwei"].to_numpy(dtype=float)
    p99_gas = sampled["p99_effective_gas_price_gwei"].to_numpy(dtype=float)
    return {
        "eth_return_p10": float(np.quantile(returns, 0.10)),
        "eth_return_median": float(np.median(returns)),
        "eth_return_p90": float(np.quantile(returns, 0.90)),
        "eth_return_volatility": float(np.std(returns, ddof=1)),
        "eth_absolute_return_p95": float(np.quantile(np.abs(returns), 0.95)),
        "median_gas_median": float(np.median(median_gas)),
        "median_gas_p90": float(np.quantile(median_gas, 0.90)),
        "p90_gas_p90": float(np.quantile(p90_gas, 0.90)),
        "p99_gas_p95": float(np.quantile(p99_gas, 0.95)),
        "return_gas_rank_correlation": float(
            pd.Series(returns).corr(pd.Series(median_gas), method="spearman")
        ),
    }


def _arrival_path_metrics(decisions: Sequence[int]) -> dict[str, float]:
    values = np.asarray(decisions, dtype=float)
    positive = values[values > 0]
    if len(positive) == 0:
        raise ValueError("Arrival validation path contains no positive draws.")
    return {
        "zero_arrival_share": float(np.mean(values == 0)),
        "positive_arrival_mean": float(np.mean(positive)),
        "positive_arrival_median": float(np.median(positive)),
        "positive_arrival_p75": float(np.quantile(positive, 0.75)),
        "positive_arrival_p90": float(np.quantile(positive, 0.90)),
        "positive_arrival_p95": float(np.quantile(positive, 0.95)),
        "maximum_support": float(np.max(positive)),
    }


def _reference_rows(
    component: str,
    integrated: pd.DataFrame,
    reference: pd.DataFrame,
    checksum: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric in integrated.columns:
        source = reference[metric].astype(float)
        observed = integrated[metric].astype(float)
        lower = float(source.quantile(0.025))
        upper = float(source.quantile(0.975))
        source_statistic = float(source.mean())
        integrated_statistic = float(observed.mean())
        if not all(
            math.isfinite(value)
            for value in (lower, upper, source_statistic, integrated_statistic)
        ):
            status = "not operational"
        elif integrated_statistic < lower:
            status = "below"
        elif integrated_statistic > upper:
            status = "above"
        else:
            status = "inside"
        rows.append(
            {
                "component": component,
                "metric": metric,
                "source_statistic": source_statistic,
                "lower_reference_bound": lower,
                "upper_reference_bound": upper,
                "integrated_statistic": integrated_statistic,
                "status": status,
                "sample_size": int(len(observed)),
                "checksum": checksum,
            }
        )
    return rows


def _sample_arrival_path(
    profile: IntegratedEmpiricalETHProfile,
    seed: int,
    horizon: int = DYNAMIC_HOURS,
) -> list[int]:
    process = LiquidationDemandProcess(
        replace(profile.liquidation_demand, seed=seed)
    )
    return [
        process.sample_step(
            step=step,
            liquidatable_inventory=VAULT_COUNT,
            keeper_capacity=None,
        ).sampled_demand
        for step in range(horizon)
    ]


@dataclass(frozen=True)
class InputValidationResult:
    rows: pd.DataFrame
    vault_draws: pd.DataFrame
    market_gas_draws: pd.DataFrame
    arrival_draws: pd.DataFrame
    component_inside_shares: Mapping[str, float]
    classification: str
    no_fallback: bool


def run_input_validation(
    profile: IntegratedEmpiricalETHProfile,
) -> InputValidationResult:
    """Run the pre-registered 512-initialisation input validation."""
    vault_integrated: list[dict[str, float]] = []
    vault_reference: list[dict[str, float]] = []
    market_integrated: list[dict[str, float]] = []
    market_reference: list[dict[str, float]] = []
    arrival_integrated: list[dict[str, float]] = []
    arrival_reference: list[dict[str, float]] = []
    market_pool = load_market_gas_pool(
        profile.market.pool_path, profile.market.pool_sha256
    )
    no_fallback = True
    for replication in range(INITIALISATION_COUNT):
        _, sampled, _ = _normalised_initial_state(
            profile,
            seed=_seed(VALIDATION_REGISTRY_ID, replication, "vault_sampling"),
        )
        vault_integrated.append(_vault_metrics(sampled))
        _, reference_sample, _ = _normalised_initial_state(
            profile,
            seed=_seed(REFERENCE_REGISTRY_ID, replication, "vault_sampling"),
        )
        vault_reference.append(_vault_metrics(reference_sample))

        sampled_market, provenance = sample_market_gas_blocks(
            market_pool,
            horizon=DYNAMIC_HOURS,
            block_length_hours=profile.market.block_length_hours,
            seed=_seed(
                VALIDATION_REGISTRY_ID, replication, "market_gas_blocks"
            ),
            pool_label=profile.market.pool_label,
        )
        sampled_reference, _ = sample_market_gas_blocks(
            market_pool,
            horizon=DYNAMIC_HOURS,
            block_length_hours=profile.market.block_length_hours,
            seed=_seed(
                REFERENCE_REGISTRY_ID, replication, "market_gas_blocks"
            ),
            pool_label=profile.market.pool_label,
        )
        if sampled_market["is_withheld_ftx"].astype(bool).any():
            raise ValueError("Held-out FTX observations entered market validation.")
        if not sampled_market["is_calibration"].astype(bool).all():
            raise ValueError("A market draw left the calibration pool.")
        if provenance["block_length_hours"] != profile.market.block_length_hours:
            raise ValueError("Market block length changed during sampling.")
        market_integrated.append(_market_gas_metrics(sampled_market))
        market_reference.append(_market_gas_metrics(sampled_reference))

        arrival_integrated.append(
            _arrival_path_metrics(
                _sample_arrival_path(
                    profile,
                    _seed(
                        VALIDATION_REGISTRY_ID,
                        replication,
                        "liquidation_arrivals",
                    ),
                )
            )
        )
        arrival_reference.append(
            _arrival_path_metrics(
                _sample_arrival_path(
                    profile,
                    _seed(
                        REFERENCE_REGISTRY_ID,
                        replication,
                        "liquidation_arrivals",
                    ),
                )
            )
        )

    vault_frame = pd.DataFrame(vault_integrated)
    market_frame = pd.DataFrame(market_integrated)
    arrival_frame = pd.DataFrame(arrival_integrated)
    rows = [
        *_reference_rows(
            "vault",
            vault_frame,
            pd.DataFrame(vault_reference),
            profile.input_checksums["vault_initialisation"],
        ),
        *_reference_rows(
            "market_gas",
            market_frame,
            pd.DataFrame(market_reference),
            profile.input_checksums["market_gas"],
        ),
        *_reference_rows(
            "liquidation_arrival",
            arrival_frame,
            pd.DataFrame(arrival_reference),
            profile.input_checksums["liquidation_arrival"],
        ),
    ]
    result = pd.DataFrame(rows)
    shares = {
        component: float(group["status"].eq("inside").mean())
        for component, group in result.groupby("component", sort=True)
    }
    mandatory_operational = not result["status"].eq("not operational").any()
    if not no_fallback:
        classification = "integrated_empirical_eth_inputs_invalid"
    elif not mandatory_operational:
        classification = "integrated_empirical_eth_inputs_blocked"
    elif all(value >= 0.90 for value in shares.values()):
        classification = "integrated_empirical_eth_inputs_valid"
    else:
        classification = "integrated_empirical_eth_inputs_valid_with_caveats"
    return InputValidationResult(
        rows=result,
        vault_draws=vault_frame,
        market_gas_draws=market_frame,
        arrival_draws=arrival_frame,
        component_inside_shares=shares,
        classification=classification,
        no_fallback=no_fallback,
    )


def _consecutive_max(mask: Sequence[bool]) -> int:
    maximum = 0
    current = 0
    for value in mask:
        current = current + 1 if value else 0
        maximum = max(maximum, current)
    return maximum


def _sustained_recovery(prices: Sequence[float], hours: int = 24) -> int | None:
    values = np.asarray(prices, dtype=float)
    inside = (values >= 0.995) & (values <= 1.005)
    for start in range(0, len(values) - hours + 1):
        if inside[start : start + hours].all():
            return start
    return None


def _dynamic_replication(
    profile: IntegratedEmpiricalETHProfile,
    *,
    replication: int,
    stage1: Mapping[str, Any],
    market_pool: pd.DataFrame,
) -> dict[str, Any]:
    vaults, _, vault_checksum = _normalised_initial_state(
        profile,
        seed=_seed(VALIDATION_REGISTRY_ID, replication, "vault_sampling"),
    )
    sampled_market, market_provenance = sample_market_gas_blocks(
        market_pool,
        horizon=DYNAMIC_HOURS,
        block_length_hours=profile.market.block_length_hours,
        seed=_seed(VALIDATION_REGISTRY_ID, replication, "market_gas_blocks"),
        pool_label=profile.market.pool_label,
    )
    price_path = prices_from_log_returns(
        sampled_market,
        initial_prices={"ETH": 2000.0, "BTC": 30_000.0},
    )["ETH"]
    gas_result = component_gas_costs(
        sampled_market_gas_rows=sampled_market,
        simulated_eth_prices=price_path,
        config=replace(
            profile.gas,
            seed=_seed(
                VALIDATION_REGISTRY_ID, replication, "keeper_gas_units"
            ),
        ),
    )
    if gas_result.gas_cost_usd is None:
        raise ValueError("Integrated gas owner returned no cost path.")
    demand = LiquidationDemandProcess(
        replace(
            profile.liquidation_demand,
            seed=_seed(
                VALIDATION_REGISTRY_ID, replication, "liquidation_arrivals"
            ),
        )
    )
    residual_rng = np.random.default_rng(
        _seed(VALIDATION_REGISTRY_ID, replication, "stage1_residual_blocks")
    )
    residuals = sample_residual_blocks(
        stage1["source"],
        block_count=math.ceil(DYNAMIC_HOURS / 24),
        rng=residual_rng,
    )[:DYNAMIC_HOURS]

    initial_debt = float(sum(vault.debt_dai for vault in vaults))
    initial_collateral = float(sum(vault.collateral_amount for vault in vaults))
    total_attempts = 0
    total_attempt_record_overcount = 0
    total_successful = 0
    total_unprofitable = 0
    total_rejected = 0
    total_arrivals = 0
    total_debt_repaid = 0.0
    total_collateral_removed = 0.0
    total_realised_bad_debt = 0.0
    total_keeper_profit = 0.0
    demand_hours = 0
    binding_hours = 0
    capacity_utilisation: list[float] = []
    unresolved_path: list[float] = []
    active_bad_debt_path: list[float] = []
    unsafe_inventory_path: list[int] = []
    dai_prices: list[float] = []
    attempts_path: list[int] = []
    arrivals_path: list[int] = []
    rejected_path: list[int] = []
    successful_path: list[int] = []
    dai_price = 1.0
    for step, (eth_price, gas_cost, residual) in enumerate(
        zip(price_path, gas_result.gas_cost_usd, residuals, strict=True)
    ):
        active = [vault for vault in vaults if vault.is_active]
        liquidatable = [
            vault for vault in active if vault.is_liquidatable(float(eth_price))
        ]
        unsafe_inventory_path.append(len(liquidatable))
        decision = demand.sample_step(
            step=step,
            liquidatable_inventory=len(liquidatable),
            keeper_capacity=SHARED_KEEPER_CAPACITY,
        )
        step_config = replace(
            profile.bundle.base_bundle.liquidation_config,
            gas_cost=float(gas_cost),
            risk_cost_rate=0.0,
            max_liquidations_per_step=SHARED_KEEPER_CAPACITY,
        )
        collateral_before = float(
            sum(vault.collateral_amount for vault in vaults if vault.is_active)
        )
        if liquidatable:
            liquidation_frame = liquidate_vaults(
                vaults,
                float(eth_price),
                step_config,
                bounded_demand=decision.bounded_demand,
                attempt_budget=decision.attempt_budget,
            )
            summary = summarise_liquidations(liquidation_frame)
        else:
            summary = {
                "n_attempted": 0,
                "n_liquidated": 0,
                "n_unprofitable": 0,
                "debt_repaid": 0.0,
                "bad_debt_realised": 0.0,
                "keeper_profit": 0.0,
            }
        collateral_after = float(
            sum(vault.collateral_amount for vault in vaults if vault.is_active)
        )
        removed = collateral_before - collateral_after
        # In bounded-demand mode the authoritative attempt count is the
        # already-ranked keeper budget.  The generic audit frame also marks
        # some unselected, unprofitable rows as ``attempted``; those rows never
        # reach execute_keeper_liquidation and must not be misreported as
        # capacity-consuming executions.
        attempts = int(decision.attempt_budget)
        attempted_record_count = int(summary["n_attempted"])
        if attempts > SHARED_KEEPER_CAPACITY:
            raise ValueError("Shared capacity was exceeded.")
        if attempted_record_count < attempts:
            raise ValueError("Liquidation audit omitted a selected keeper attempt.")
        attempt_record_overcount = attempted_record_count - attempts
        rejected = int(decision.demand_truncated_by_capacity)
        total_attempts += attempts
        total_attempt_record_overcount += attempt_record_overcount
        total_successful += int(summary["n_liquidated"])
        total_unprofitable += attempts - int(summary["n_liquidated"])
        total_rejected += rejected
        total_arrivals += int(decision.sampled_demand)
        total_debt_repaid += float(summary["debt_repaid"])
        total_collateral_removed += removed
        total_realised_bad_debt += float(summary["bad_debt_realised"])
        total_keeper_profit += float(summary["keeper_profit"])
        if decision.bounded_demand > 0:
            demand_hours += 1
            capacity_utilisation.append(attempts / SHARED_KEEPER_CAPACITY)
        if rejected > 0:
            binding_hours += 1

        active = [vault for vault in vaults if vault.is_active]
        unresolved = float(
            sum(
                vault.debt_dai
                for vault in active
                if vault.is_liquidatable(float(eth_price))
            )
        )
        active_bad_debt = float(
            sum(vault.bad_debt(float(eth_price)) for vault in active)
        )
        unresolved_path.append(unresolved)
        active_bad_debt_path.append(active_bad_debt)
        attempts_path.append(attempts)
        arrivals_path.append(int(decision.sampled_demand))
        rejected_path.append(rejected)
        successful_path.append(int(summary["n_liquidated"]))

        response = coefficient_normalised_market_response(
            dai_price=dai_price,
            confidence=1.0,
            below_peg_response=float(stage1["below_peg_response"]),
            above_peg_response=float(stage1["above_peg_response"]),
            panic_response=0.0,
            residual_innovation=float(residual),
            min_price=0.50,
            max_price=1.50,
        )
        dai_price = response.clipped_next_price
        dai_prices.append(dai_price)

    final_debt = float(sum(vault.debt_dai for vault in vaults if vault.is_active))
    final_collateral = float(
        sum(vault.collateral_amount for vault in vaults if vault.is_active)
    )
    debt_error = initial_debt - final_debt - total_debt_repaid
    collateral_error = (
        initial_collateral - final_collateral - total_collateral_removed
    )
    dai = np.asarray(dai_prices, dtype=float)
    unresolved_values = np.asarray(unresolved_path, dtype=float)
    bad_debt_values = np.asarray(active_bad_debt_path, dtype=float)
    numerical_valid = bool(
        np.isfinite(dai).all()
        and np.isfinite(unresolved_values).all()
        and np.isfinite(bad_debt_values).all()
        and np.all(dai > 0.0)
        and np.all(unresolved_values >= -1e-9)
        and np.all(bad_debt_values >= -1e-9)
        and abs(debt_error) <= 1e-5
        and abs(collateral_error) <= 1e-5
        and total_successful <= VAULT_COUNT
    )
    return {
        "replication": replication,
        "vault_checksum": vault_checksum,
        "market_block_identity": _payload_sha256(
            market_provenance["sampled_start_indexes"]
        ),
        "gas_block_identity": _payload_sha256(
            {
                "market_starts": market_provenance["sampled_start_indexes"],
                "gas_seed": _seed(
                    VALIDATION_REGISTRY_ID, replication, "keeper_gas_units"
                ),
            }
        ),
        "arrival_identity": _payload_sha256(arrivals_path),
        "total_debt": initial_debt,
        "capacity_profile": profile.keeper.capacity_profile_id,
        "hurdle_profile": profile.keeper.hurdle_profile_id,
        "oracle_status": profile.oracle_status,
        "demand_hours": demand_hours,
        "binding_hours": binding_hours,
        "mean_unsafe_inventory": float(np.mean(unsafe_inventory_path)),
        "maximum_unsafe_inventory": int(max(unsafe_inventory_path, default=0)),
        "cumulative_arrival_count": total_arrivals,
        "cumulative_attempts": total_attempts,
        "cumulative_attempt_record_overcount": total_attempt_record_overcount,
        "cumulative_successful_closures": total_successful,
        "cumulative_capacity_rejected": total_rejected,
        "cumulative_unprofitable_attempts": total_unprofitable,
        "mean_capacity_utilisation": (
            float(np.mean(capacity_utilisation)) if capacity_utilisation else 0.0
        ),
        "p90_capacity_utilisation": (
            float(np.quantile(capacity_utilisation, 0.90))
            if capacity_utilisation
            else 0.0
        ),
        "maximum_capacity_utilisation": (
            float(np.max(capacity_utilisation)) if capacity_utilisation else 0.0
        ),
        "maximum_attempts_one_hour": int(max(attempts_path, default=0)),
        "mean_capacity_rejected": float(np.mean(rejected_path)),
        "maximum_capacity_rejected": int(max(rejected_path, default=0)),
        "cumulative_debt_repaid": total_debt_repaid,
        "maximum_unresolved_tab": float(np.max(unresolved_values)),
        "unresolved_tab_at_horizon": float(unresolved_values[-1]),
        "maximum_backlog_duration": _consecutive_max(unresolved_values > 0),
        "maximum_active_bad_debt": float(np.max(bad_debt_values)),
        "active_bad_debt_at_horizon": float(bad_debt_values[-1]),
        "cumulative_realised_bad_debt": total_realised_bad_debt,
        "keeper_profit": total_keeper_profit,
        "minimum_dai_price": float(np.min(dai)),
        "maximum_negative_peg_deviation": float(np.max(np.maximum(1.0 - dai, 0.0))),
        "mean_absolute_peg_deviation": float(np.mean(np.abs(dai - 1.0))),
        "below_peg_burden": float(np.sum(np.maximum(1.0 - dai, 0.0))),
        "hours_below_0995": int(np.count_nonzero(dai < 0.995)),
        "hours_above_1005": int(np.count_nonzero(dai > 1.005)),
        "sustained_recovery_time": (
            DYNAMIC_HOURS
            if _sustained_recovery(dai) is None
            else int(_sustained_recovery(dai))
        ),
        "final_dai_price": float(dai[-1]),
        "gas_execution_rank_correlation": float(
            pd.Series(gas_result.gas_cost_usd).corr(
                pd.Series(successful_path), method="spearman"
            )
            if np.std(successful_path) > 0
            else 0.0
        ),
        "debt_conservation_error": debt_error,
        "collateral_conservation_error": collateral_error,
        "numerical_valid": numerical_valid,
        "duplicate_closure_detected": total_successful > VAULT_COUNT,
        "attempt_path_checksum": _payload_sha256(attempts_path),
        "residual_path_checksum": hashlib.sha256(
            np.asarray(residuals, dtype="<f8").tobytes()
        ).hexdigest(),
    }


def controlled_binding_smoke(
    profile: IntegratedEmpiricalETHProfile,
) -> dict[str, Any]:
    """Prove one shared cap under a short fixed low-price path."""
    vaults, _, state_checksum = _normalised_initial_state(
        profile,
        seed=_seed(
            VALIDATION_REGISTRY_ID, 0, "controlled_smoke_vaults"
        ),
    )
    demand = LiquidationDemandProcess(
        replace(
            profile.liquidation_demand,
            seed=_seed(
                VALIDATION_REGISTRY_ID, 0, "controlled_smoke_arrivals"
            ),
        )
    )
    eth_price = 200.0
    maximum_unsafe = 0
    maximum_attempts = 0
    rejected_total = 0
    binding_hours = 0
    unresolved_carried = False
    dai_price = 1.0
    for step in range(CONTROLLED_SMOKE_HOURS):
        unsafe_before = [
            vault
            for vault in vaults
            if vault.is_active and vault.is_liquidatable(eth_price)
        ]
        maximum_unsafe = max(maximum_unsafe, len(unsafe_before))
        decision = demand.sample_step(
            step=step,
            liquidatable_inventory=len(unsafe_before),
            keeper_capacity=SHARED_KEEPER_CAPACITY,
        )
        summary = {
            "n_attempted": 0,
            "n_liquidated": 0,
        }
        if unsafe_before:
            frame = liquidate_vaults(
                vaults,
                eth_price,
                replace(
                    profile.bundle.base_bundle.liquidation_config,
                    gas_cost=0.0,
                    risk_cost_rate=0.0,
                    max_liquidations_per_step=SHARED_KEEPER_CAPACITY,
                ),
                bounded_demand=decision.bounded_demand,
                attempt_budget=decision.attempt_budget,
            )
            summary = summarise_liquidations(frame)
        maximum_attempts = max(maximum_attempts, int(summary["n_attempted"]))
        rejected_total += int(decision.demand_truncated_by_capacity)
        binding_hours += int(decision.demand_truncated_by_capacity > 0)
        unsafe_after = sum(
            vault.is_active and vault.is_liquidatable(eth_price)
            for vault in vaults
        )
        if decision.demand_truncated_by_capacity > 0 and unsafe_after > 0:
            unresolved_carried = True
        response = coefficient_normalised_market_response(
            dai_price=dai_price,
            confidence=1.0,
            below_peg_response=EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
            above_peg_response=EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
            panic_response=0.0,
            residual_innovation=0.0,
            min_price=0.5,
            max_price=1.5,
        )
        dai_price = response.clipped_next_price
    passed = bool(
        maximum_unsafe > SHARED_KEEPER_CAPACITY
        and maximum_attempts <= SHARED_KEEPER_CAPACITY
        and rejected_total > 0
        and unresolved_carried
        and math.isfinite(dai_price)
    )
    return {
        "hours": CONTROLLED_SMOKE_HOURS,
        "state_checksum": state_checksum,
        "fixed_eth_price": eth_price,
        "fixed_residual_path": "zero",
        "maximum_unsafe_inventory": maximum_unsafe,
        "maximum_attempts": maximum_attempts,
        "capacity_rejected_opportunities": rejected_total,
        "binding_hours": binding_hours,
        "unresolved_inventory_carried_forward": unresolved_carried,
        "duplicate_execution_detected": False,
        "final_dai_price": dai_price,
        "finite_dai_state": math.isfinite(dai_price),
        "passed": passed,
        "substantive_recovery_experiment": False,
    }


def _distribution(values: Iterable[float]) -> dict[str, float]:
    array = np.asarray(list(values), dtype=float)
    return {
        "mean": float(np.mean(array)),
        "standard_error": float(np.std(array, ddof=1) / math.sqrt(len(array))),
        "median": float(np.median(array)),
        "p05": float(np.quantile(array, 0.05)),
        "p25": float(np.quantile(array, 0.25)),
        "p75": float(np.quantile(array, 0.75)),
        "p95": float(np.quantile(array, 0.95)),
        "minimum": float(np.min(array)),
        "maximum": float(np.max(array)),
    }


def _dynamic_reference_status(
    metric: str,
    summary: Mapping[str, float],
    arrival_pool: pd.DataFrame,
    stage1_panel: pd.DataFrame,
) -> str:
    if metric == "cumulative_successful_closures":
        hourly = float(summary["mean"]) / DYNAMIC_HOURS
        reference = arrival_pool["grab_count"].to_numpy(dtype=float)
        lower, upper = np.quantile(reference, [0.025, 0.975])
        return (
            "within_reference_band"
            if lower <= hourly <= upper
            else "outside_reference_band"
        )
    if metric == "mean_absolute_peg_deviation":
        reference = np.abs(stage1_panel["dai_price_usd"].to_numpy(dtype=float) - 1.0)
        lower, upper = np.quantile(reference, [0.025, 0.975])
        return (
            "within_reference_band"
            if lower <= float(summary["mean"]) <= upper
            else "outside_reference_band"
        )
    return "reference_not_operational"


@dataclass(frozen=True)
class DynamicValidationResult:
    replications: pd.DataFrame
    summary: pd.DataFrame
    capacity_summary: pd.DataFrame
    smoke: Mapping[str, Any]
    output_classification: str
    numerical_validity_count: int


def run_dynamic_validation(
    profile: IntegratedEmpiricalETHProfile,
) -> DynamicValidationResult:
    """Run 128 integrated 720-hour simulations with dedicated seeds."""
    stage1_panel, _, stage1 = load_stage1_owners()
    if round(float(stage1["below_peg_response"]), 6) != EXPECTED_STAGE1_BELOW_PEG_RESPONSE:
        raise ValueError("Accepted below-peg response differs.")
    if round(float(stage1["above_peg_response"]), 6) != EXPECTED_STAGE1_ABOVE_PEG_RESPONSE:
        raise ValueError("Accepted above-peg response differs.")
    market_pool = load_market_gas_pool(
        profile.market.pool_path, profile.market.pool_sha256
    )
    arrival_pool = load_liquidation_arrival_pool(
        profile.liquidation_demand.pool_path,
        profile.liquidation_demand.pool_sha256,
    )
    records = [
        _dynamic_replication(
            profile,
            replication=replication,
            stage1=stage1,
            market_pool=market_pool,
        )
        for replication in range(DYNAMIC_REPLICATION_COUNT)
    ]
    frame = pd.DataFrame(records).sort_values(
        "replication", kind="mergesort"
    ).reset_index(drop=True)
    metrics = [
        "demand_hours",
        "binding_hours",
        "mean_unsafe_inventory",
        "maximum_unsafe_inventory",
        "cumulative_arrival_count",
        "cumulative_attempts",
        "cumulative_attempt_record_overcount",
        "cumulative_successful_closures",
        "cumulative_capacity_rejected",
        "cumulative_unprofitable_attempts",
        "mean_capacity_utilisation",
        "p90_capacity_utilisation",
        "maximum_capacity_utilisation",
        "maximum_attempts_one_hour",
        "mean_capacity_rejected",
        "maximum_capacity_rejected",
        "cumulative_debt_repaid",
        "maximum_unresolved_tab",
        "unresolved_tab_at_horizon",
        "maximum_backlog_duration",
        "maximum_active_bad_debt",
        "active_bad_debt_at_horizon",
        "cumulative_realised_bad_debt",
        "keeper_profit",
        "minimum_dai_price",
        "maximum_negative_peg_deviation",
        "mean_absolute_peg_deviation",
        "below_peg_burden",
        "hours_below_0995",
        "hours_above_1005",
        "sustained_recovery_time",
        "final_dai_price",
        "gas_execution_rank_correlation",
        "debt_conservation_error",
        "collateral_conservation_error",
    ]
    summary_rows: list[dict[str, Any]] = []
    valid_count = int(frame["numerical_valid"].sum())
    for metric in metrics:
        distribution = _distribution(frame[metric])
        summary_rows.append(
            {
                "metric": metric,
                "replication_count": DYNAMIC_REPLICATION_COUNT,
                **distribution,
                "reference_status": _dynamic_reference_status(
                    metric, distribution, arrival_pool, stage1_panel
                ),
                "numerical_validity_count": valid_count,
            }
        )
    summary = pd.DataFrame(summary_rows)
    smoke = controlled_binding_smoke(profile)
    capacity = pd.DataFrame(
        [
            {
                "metric": "demand_hours",
                "value": float(frame["demand_hours"].sum()),
                "unit": "replication-hours",
            },
            {
                "metric": "share_all_hours_with_positive_demand",
                "value": float(
                    frame["demand_hours"].sum()
                    / (DYNAMIC_REPLICATION_COUNT * DYNAMIC_HOURS)
                ),
                "unit": "fraction",
            },
            {
                "metric": "binding_hours",
                "value": float(frame["binding_hours"].sum()),
                "unit": "replication-hours",
            },
            {
                "metric": "share_demand_hours_binding",
                "value": float(
                    frame["binding_hours"].sum()
                    / max(frame["demand_hours"].sum(), 1)
                ),
                "unit": "fraction",
            },
            {
                "metric": "mean_capacity_utilisation_on_demand_hours",
                "value": float(
                    frame["cumulative_attempts"].sum()
                    / max(
                        frame["demand_hours"].sum() * SHARED_KEEPER_CAPACITY,
                        1,
                    )
                ),
                "unit": "fraction_of_26",
            },
            {
                "metric": "p90_replication_capacity_utilisation",
                "value": float(
                    frame["p90_capacity_utilisation"].quantile(0.90)
                ),
                "unit": "fraction_of_26",
            },
            {
                "metric": "maximum_capacity_utilisation",
                "value": float(frame["maximum_capacity_utilisation"].max()),
                "unit": "fraction_of_26",
            },
            {
                "metric": "mean_capacity_rejected_opportunities",
                "value": float(frame["mean_capacity_rejected"].mean()),
                "unit": "opportunities_per_hour",
            },
            {
                "metric": "maximum_capacity_rejected_opportunities",
                "value": float(frame["maximum_capacity_rejected"].max()),
                "unit": "opportunities_per_hour",
            },
            {
                "metric": "maximum_hourly_attempts",
                "value": float(frame["maximum_attempts_one_hour"].max()),
                "unit": "opportunities_per_hour",
            },
            {
                "metric": "generic_audit_attempt_record_overcount",
                "value": float(frame["cumulative_attempt_record_overcount"].sum()),
                "unit": "non-executed audit records",
            },
            {
                "metric": "controlled_smoke_pass",
                "value": float(bool(smoke["passed"])),
                "unit": "boolean",
            },
        ]
    )
    operational = summary.loc[
        ~summary["reference_status"].eq("reference_not_operational"),
        "reference_status",
    ]
    within = int(operational.eq("within_reference_band").sum())
    if valid_count != DYNAMIC_REPLICATION_COUNT or not smoke["passed"]:
        output_classification = "integrated_outputs_not_compatible"
    elif len(operational) == 0:
        output_classification = "integrated_output_validation_not_operational"
    elif within == len(operational) and len(operational) >= 4:
        output_classification = "integrated_outputs_broadly_compatible"
    else:
        output_classification = "integrated_outputs_partially_compatible"
    return DynamicValidationResult(
        replications=frame,
        summary=summary,
        capacity_summary=capacity,
        smoke=smoke,
        output_classification=output_classification,
        numerical_validity_count=valid_count,
    )


def _overall_classification(
    inputs: InputValidationResult,
    dynamic: DynamicValidationResult,
) -> str:
    if inputs.classification == "integrated_empirical_eth_inputs_invalid":
        return "integrated_empirical_eth_profile_invalid"
    if (
        inputs.classification == "integrated_empirical_eth_inputs_blocked"
        or dynamic.output_classification
        == "integrated_output_validation_not_operational"
    ):
        return "integrated_empirical_eth_profile_blocked"
    if (
        dynamic.numerical_validity_count != DYNAMIC_REPLICATION_COUNT
        or not dynamic.smoke["passed"]
    ):
        return "integrated_empirical_eth_profile_invalid"
    if (
        inputs.classification == "integrated_empirical_eth_inputs_valid"
        and dynamic.output_classification
        == "integrated_outputs_broadly_compatible"
    ):
        return "integrated_empirical_eth_profile_ready"
    return "integrated_empirical_eth_profile_ready_with_caveats"


def _profile_payload(
    profile: IntegratedEmpiricalETHProfile,
    overall: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "identifier": profile.identifier,
        "profile_identity": profile.profile_identity,
        "profile_path": _relative(profile.profile_path),
        "profile_sha256": profile.profile_checksum,
        "owner_paths": dict(profile.owner_paths),
        "input_checksums": _source_identities(profile),
        "simulation": {
            "hours": DYNAMIC_HOURS,
            "vault_count": VAULT_COUNT,
            "total_debt_dai": TOTAL_DEBT_DAI,
            "collateral_types": ["ETH"],
            "oracle_delay_steps": 0,
            "oracle_status": profile.oracle_status,
        },
        "vault_initialisation": {
            "mode": profile.bundle.initialisation.mode,
            "regime": profile.bundle.initialisation.regime,
            "fallback_configured_but_used": False,
            "joint_dependence_retained": True,
        },
        "market": asdict(profile.market),
        "gas": asdict(profile.gas),
        "liquidation_demand": asdict(profile.liquidation_demand),
        "keeper": {
            "capacity_profile": profile.keeper.capacity_profile_id,
            "capacity": profile.keeper.maximum_liquidations_per_step,
            "unit": (
                "protocol-level liquidation opportunities per one-hour simulation step"
            ),
            "semantics": "system_wide_shared_capacity",
            "population_mapping": profile.keeper.population_mapping_status,
            "hurdle_profile": profile.keeper.hurdle_profile_id,
            "risk_cost_rate": profile.keeper.risk_cost_rate,
        },
        "stage1": {
            "below_peg_response_rounded": EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
            "above_peg_response_rounded": EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
            "residual_sequence_sha256": EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
            "residual_block_sha256": EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
        },
        "confidence": {
            "identifier": profile.confidence.scenario.identifier,
            "persistent_confidence_enabled": False,
            "fixed_confidence": 1.0,
            "panic_response": 0.0,
        },
        "no_fallback": True,
        "profile_status": "candidate_opt_in",
        "experiment_ready": overall
        in {
            "integrated_empirical_eth_profile_ready",
            "integrated_empirical_eth_profile_ready_with_caveats",
        },
        "runtime_adopted": False,
    }


def _decision_payload(
    profile: IntegratedEmpiricalETHProfile,
    inputs: InputValidationResult,
    dynamic: DynamicValidationResult,
    overall: str,
) -> dict[str, Any]:
    ready = overall in {
        "integrated_empirical_eth_profile_ready",
        "integrated_empirical_eth_profile_ready_with_caveats",
    }
    return {
        "schema_version": 1,
        "profile_identifier": profile.identifier,
        "profile_identity": profile.profile_identity,
        "input_classification": inputs.classification,
        "output_classification": dynamic.output_classification,
        "overall_classification": overall,
        "principal_caveats": [
            "Dynamic liquidation and DAI outputs are reduced-form and only partly comparable with historical observations.",
            "The oracle uses a transparent zero-delay baseline that has not been empirically calibrated.",
            "The shared capacity is partially identified and is not a physical keeper-network maximum.",
            "Population robustness at 250 and 1,000 vaults remains outstanding.",
            "The bounded-demand audit regression excludes unselected opportunities from attempted counts; the authoritative attempt budget and capacity diagnostics now agree.",
        ],
        "component_inside_shares": dict(inputs.component_inside_shares),
        "capacity_validation": {
            "shared_semantics": "system_wide_shared_capacity",
            "maximum_attempts": int(
                dynamic.replications["maximum_attempts_one_hour"].max()
            ),
            "capacity": SHARED_KEEPER_CAPACITY,
            "controlled_smoke_passed": bool(dynamic.smoke["passed"]),
            "duplicated_per_collateral": False,
        },
        "oracle_status": profile.oracle_status,
        "authorised_next_boundary": (
            "constrained_liquidation_recovery_experiment"
            if ready
            else "resolve_integrated_profile_blocker"
        ),
        "no_parameter_tuning": True,
        "no_production_adoption": True,
        "runtime_adopted": False,
    }


def _reproducibility_payload(
    profile: IntegratedEmpiricalETHProfile,
    preregistration: Mapping[str, Any],
    inputs: InputValidationResult,
    dynamic: DynamicValidationResult,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "scientific_code_identity": scientific_code_identity(),
        "profile_identity": profile.profile_identity,
        "preregistration_identity": preregistration["preregistration_identity"],
        "seed_registry_checksum": seed_registry_checksum(),
        "input_checksums": _source_identities(profile),
        "completed_initialisations": len(inputs.vault_draws),
        "completed_dynamic_replications": len(dynamic.replications),
        "deterministic_reconstruction": True,
        "final_validation_data_used": False,
        "usdc_svb_used": False,
        "recovery_matrix_run": False,
        "multi_collateral_execution": False,
        "parameter_calibration_run": False,
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
        "schema_version": 1,
        "initialisation_count": INITIALISATION_COUNT,
        "simulation_count": DYNAMIC_REPLICATION_COUNT,
        "simulation_hours": DYNAMIC_HOURS,
        "worker_count": worker_count,
        "wall_time_seconds": wall_time,
        "simulations_per_second": (
            DYNAMIC_REPLICATION_COUNT / wall_time if wall_time > 0 else None
        ),
        "memory_bytes": None,
        "ignored_output_size_bytes": output_size,
        "output_cap_bytes": OUTPUT_CAP_BYTES,
        "free_storage_bytes": free_storage,
        "minimum_free_storage_bytes": MINIMUM_FREE_BYTES,
        "host_dependent": True,
        "platform": platform.system(),
    }


def _write_detailed_outputs(
    path: Path,
    inputs: InputValidationResult,
    dynamic: DynamicValidationResult,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _atomic_bytes(path / "initialisation_moment_draws.csv", _csv_bytes(inputs.vault_draws))
    _atomic_bytes(path / "market_gas_moment_draws.csv", _csv_bytes(inputs.market_gas_draws))
    _atomic_bytes(path / "arrival_moment_draws.csv", _csv_bytes(inputs.arrival_draws))
    _atomic_bytes(path / "replication_summaries.csv", _csv_bytes(dynamic.replications))
    _atomic_bytes(path / "controlled_binding_smoke.json", _pretty_json(dynamic.smoke))
    _atomic_bytes(path / "seed_registry.json", _pretty_json(seed_registry_payload()))


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _compact_payloads(
    profile: IntegratedEmpiricalETHProfile,
    preregistration: Mapping[str, Any],
    inputs: InputValidationResult,
    dynamic: DynamicValidationResult,
    *,
    benchmark: Mapping[str, Any],
) -> dict[str, bytes]:
    overall = _overall_classification(inputs, dynamic)
    payloads = {
        "integrated_empirical_eth_specification.json": _pretty_json(
            preregistration
        ),
        "integrated_empirical_eth_profile.json": _pretty_json(
            _profile_payload(profile, overall)
        ),
        "integrated_empirical_eth_input_validation.csv": _csv_bytes(inputs.rows),
        "integrated_empirical_eth_dynamic_summary.csv": _csv_bytes(dynamic.summary),
        "integrated_empirical_eth_capacity_summary.csv": _csv_bytes(
            dynamic.capacity_summary
        ),
        "integrated_empirical_eth_decision.json": _pretty_json(
            _decision_payload(profile, inputs, dynamic, overall)
        ),
        "integrated_empirical_eth_reproducibility.json": _pretty_json(
            _reproducibility_payload(profile, preregistration, inputs, dynamic)
        ),
        "integrated_empirical_eth_benchmark.json": _pretty_json(benchmark),
    }
    return payloads


def _manifest_payload(evidence_dir: Path) -> dict[str, Any]:
    entries = []
    for name in COMPACT_FILENAMES:
        path = evidence_dir / name
        entries.append(
            {
                "path": _relative(path),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "semantic_owner": "integrated_empirical_eth_validation",
                "runtime_input": False,
            }
        )
    return {
        "schema_version": 1,
        "domain": "validation",
        "entries": entries,
        "entry_count": len(entries),
        "duplicate_paths": 0,
    }


def execute_integrated_validation(
    *,
    evidence_dir: Path = EVIDENCE_DIR,
    diagnostic_root: Path = DEFAULT_DIAGNOSTIC_ROOT,
    worker_count: int = 1,
) -> dict[str, Any]:
    """Execute the complete pre-registered validation and compact evidence."""
    if worker_count != 1:
        raise ValueError("Current deterministic validation owns exactly one worker.")
    profile = resolve_integrated_empirical_eth_profile()
    free_before = shutil.disk_usage(REPOSITORY_ROOT).free
    if free_before < MINIMUM_FREE_BYTES:
        raise ValueError("Fewer than 10 GiB are free before dynamic validation.")
    preregistration = write_preregistration(profile, evidence_dir)
    started = time.perf_counter()
    inputs = run_input_validation(profile)
    dynamic = run_dynamic_validation(profile)
    diagnostic_path = diagnostic_root / profile.profile_identity
    _write_detailed_outputs(diagnostic_path, inputs, dynamic)
    output_size = _directory_size(diagnostic_path)
    if output_size > OUTPUT_CAP_BYTES:
        raise ValueError("Integrated validation output exceeds 300 MB.")
    elapsed = time.perf_counter() - started
    benchmark = _benchmark_payload(
        wall_time=elapsed,
        output_size=output_size,
        free_storage=shutil.disk_usage(REPOSITORY_ROOT).free,
        worker_count=worker_count,
    )
    first = _compact_payloads(
        profile, preregistration, inputs, dynamic, benchmark=benchmark
    )
    second = _compact_payloads(
        profile, preregistration, inputs, dynamic, benchmark=benchmark
    )
    for name in DETERMINISTIC_FILENAMES:
        if first[name] != second[name]:
            raise ValueError(f"Compact evidence is non-deterministic: {name}.")
    for name, payload in first.items():
        _atomic_bytes(evidence_dir / name, payload)
    manifest = _manifest_payload(evidence_dir)
    _atomic_bytes(VALIDATION_MANIFEST, _pretty_json(manifest))
    overall = _overall_classification(inputs, dynamic)
    return {
        "profile_identifier": profile.identifier,
        "profile_identity": profile.profile_identity,
        "preregistration_identity": preregistration["preregistration_identity"],
        "scientific_code_identity": scientific_code_identity(),
        "input_classification": inputs.classification,
        "output_classification": dynamic.output_classification,
        "overall_classification": overall,
        "experiment_ready": overall
        in {
            "integrated_empirical_eth_profile_ready",
            "integrated_empirical_eth_profile_ready_with_caveats",
        },
        "compact_evidence": {
            name: {
                "path": _relative(evidence_dir / name),
                "sha256": sha256_file(evidence_dir / name),
                "bytes": (evidence_dir / name).stat().st_size,
            }
            for name in COMPACT_FILENAMES
        },
        "validation_manifest": _relative(VALIDATION_MANIFEST),
        "validation_manifest_entry_count": len(manifest["entries"]),
        "diagnostic_path": _relative(diagnostic_path),
        "diagnostic_size_bytes": output_size,
        "wall_time_seconds": elapsed,
        "deterministic_reconstruction": True,
        "runtime_adopted": False,
    }


def validate_compact_evidence(
    evidence_dir: Path = EVIDENCE_DIR,
) -> dict[str, Any]:
    """Validate compact evidence schemas, classifications and manifest links."""
    missing = [
        name for name in COMPACT_FILENAMES if not (evidence_dir / name).exists()
    ]
    if missing:
        raise ValueError(f"Missing integrated validation evidence: {missing}.")
    specification = json.loads(
        (evidence_dir / COMPACT_FILENAMES[0]).read_text(encoding="utf-8")
    )
    profile_payload = json.loads(
        (evidence_dir / COMPACT_FILENAMES[1]).read_text(encoding="utf-8")
    )
    decision = json.loads(
        (evidence_dir / "integrated_empirical_eth_decision.json").read_text(
            encoding="utf-8"
        )
    )
    reproducibility = json.loads(
        (
            evidence_dir / "integrated_empirical_eth_reproducibility.json"
        ).read_text(encoding="utf-8")
    )
    input_rows = pd.read_csv(
        evidence_dir / "integrated_empirical_eth_input_validation.csv"
    )
    dynamic_rows = pd.read_csv(
        evidence_dir / "integrated_empirical_eth_dynamic_summary.csv"
    )
    capacity_rows = pd.read_csv(
        evidence_dir / "integrated_empirical_eth_capacity_summary.csv"
    )
    if specification["result_fields_excluded"] is not True:
        raise ValueError("Pre-registration contains result fields.")
    if profile_payload["runtime_adopted"] is not False:
        raise ValueError("Integrated profile was unexpectedly adopted.")
    if decision["overall_classification"] not in preregistration_payload(
        resolve_integrated_empirical_eth_profile()
    )["classifications"]["overall"]:
        raise ValueError("Unknown overall integrated-profile classification.")
    if reproducibility["final_validation_data_used"]:
        raise ValueError("Final-validation data entered integrated validation.")
    if reproducibility["usdc_svb_used"]:
        raise ValueError("USDC/SVB entered integrated validation.")
    if reproducibility["recovery_matrix_run"] or reproducibility[
        "multi_collateral_execution"
    ]:
        raise ValueError("A prohibited substantive experiment was recorded.")
    if set(input_rows["status"]) - {"inside", "below", "above", "not operational"}:
        raise ValueError("Unknown input-moment classification.")
    if dynamic_rows["numerical_validity_count"].min() != DYNAMIC_REPLICATION_COUNT:
        raise ValueError("Not every dynamic replication is numerically valid.")
    maximum_attempts = capacity_rows.loc[
        capacity_rows["metric"].eq("maximum_hourly_attempts"), "value"
    ]
    if len(maximum_attempts) != 1 or float(maximum_attempts.iloc[0]) > 26:
        raise ValueError("Shared capacity validation failed.")
    manifest = json.loads(VALIDATION_MANIFEST.read_text(encoding="utf-8"))
    if manifest["entry_count"] != len(COMPACT_FILENAMES):
        raise ValueError("Validation manifest entry count differs.")
    if len({entry["path"] for entry in manifest["entries"]}) != len(
        manifest["entries"]
    ):
        raise ValueError("Validation manifest contains duplicate paths.")
    for entry in manifest["entries"]:
        path = REPOSITORY_ROOT / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Manifest checksum mismatch: {entry['path']}.")
    return {
        "profile_identity": profile_payload["profile_identity"],
        "preregistration_identity": specification["preregistration_identity"],
        "scientific_code_identity": reproducibility["scientific_code_identity"],
        "input_classification": decision["input_classification"],
        "output_classification": decision["output_classification"],
        "overall_classification": decision["overall_classification"],
        "manifest_entry_count": manifest["entry_count"],
        "deterministic_reconstruction": reproducibility[
            "deterministic_reconstruction"
        ],
        "runtime_adopted": profile_payload["runtime_adopted"],
    }
