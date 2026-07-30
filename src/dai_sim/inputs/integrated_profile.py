"""Typed resolution for the opt-in integrated empirical ETH profile.

The profile is an integration harness.  It resolves existing empirical owners
and reviewed candidate registries without altering ordinary simulation
configuration loading or any production default.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from dai_sim.experiments.confidence_scenarios import (
    DEFAULT_REGISTRY_PATH as DEFAULT_CONFIDENCE_REGISTRY_PATH,
    ConfidenceScenarioActivation,
    resolve_confidence_scenario,
)

from .configuration import REPOSITORY_ROOT, load_configuration_payload, sha256_file
from .gas import GasProcessConfig
from .keeper_execution import (
    KeeperExecutionCandidate,
    resolve_keeper_execution_candidate,
)
from .liquidations import LiquidationDemandConfig
from .market import MarketProcessConfig
from .vaults import TrancheBConfigurationBundle, load_tranche_b_configuration


PROFILE_IDENTIFIER = "empirical_integrated_eth"
DEFAULT_PROFILE_PATH = (
    REPOSITORY_ROOT / "config/profiles/empirical_integrated_eth.yaml"
)
EXPECTED_INPUT_CHECKSUMS = {
    "vault_initialisation": (
        "5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892"
    ),
    "market_gas": (
        "b69276801bacf789f8ae91789983cc98a8a6d42d0a992940c0bcfa109ca25b7d"
    ),
    "keeper_gas": (
        "37a5f49f4cc273b9d0d9526609be7f14b91b78939acf26e4dce00b66443e1594"
    ),
    "liquidation_arrival": (
        "cc29435bb0434237aba438ee98bded77f086704c7400bb5016e2b58703258c8a"
    ),
    "liquidation_sequence_sensitivity": (
        "9fdd5f3b5fb97e2dd41d0201bad34909ad05e423ad6b52f65219f49f02a1c7ed"
    ),
}
EXPECTED_KEEPER_CONFIGURATION_SHA256 = (
    "e1d590508bb3e95ec6bdc2a30c41580fe211831a673dd447e793a0053a7fa848"
)
EXPECTED_KEEPER_REGISTRY_SHA256 = (
    "58c5754ed95dead1ad283a7961fb0588496804a94f58ddb0e196a57601ee1e1b"
)
EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256 = (
    "3fa2319cee9e1749405c0dc477e0f11ef9c31dd83c371b619bd33eda23c37c30"
)
EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256 = (
    "6f55b51acfc1da23836b3d847153bd4f68e4a38fc33fd967e9d3b795737bf28c"
)
EXPECTED_STAGE1_BELOW_PEG_RESPONSE = 0.199381
EXPECTED_STAGE1_ABOVE_PEG_RESPONSE = 0.105131
TOTAL_DEBT_DAI = 2_500_000.0
VAULT_COUNT = 500
DYNAMIC_HOURS = 720
SHARED_KEEPER_CAPACITY = 26


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPOSITORY_ROOT))


def _path(raw: Mapping[str, Any], key: str) -> Path:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be an explicit repository-relative path.")
    path = (REPOSITORY_ROOT / value).resolve()
    try:
        path.relative_to(REPOSITORY_ROOT)
    except ValueError as exc:
        raise ValueError(f"{key} must remain within the repository.") from exc
    return path


@dataclass(frozen=True)
class IntegratedEmpiricalETHProfile:
    """Fully resolved, candidate-only integrated ETH profile."""

    identifier: str
    profile_path: Path
    profile_checksum: str
    profile_identity: str
    bundle: TrancheBConfigurationBundle
    market: MarketProcessConfig
    gas: GasProcessConfig
    liquidation_demand: LiquidationDemandConfig
    keeper: KeeperExecutionCandidate
    confidence: ConfidenceScenarioActivation
    owner_paths: Mapping[str, str]
    input_checksums: Mapping[str, str]
    total_debt_dai: float
    oracle_status: str
    experiment_ready: bool
    runtime_adopted: bool

    def validate(self) -> None:
        """Enforce the fixed integration semantics and non-adoption boundary."""
        simulation = self.bundle.base_bundle.simulation_config
        liquidation = self.bundle.base_bundle.liquidation_config
        portfolio = simulation.collateral_portfolio
        if self.identifier != PROFILE_IDENTIFIER:
            raise ValueError("Unexpected integrated profile identifier.")
        if simulation.n_vaults != VAULT_COUNT:
            raise ValueError("Integrated profile must create exactly 500 vaults.")
        if simulation.n_steps != DYNAMIC_HOURS:
            raise ValueError("Integrated validation horizon must be 720 hours.")
        if portfolio is None or portfolio.collateral_names != ("ETH",):
            raise ValueError("Integrated profile must remain strictly ETH-only.")
        if portfolio.target_debt_shares != {"ETH": 1.0}:
            raise ValueError("Integrated profile must assign all debt to ETH.")
        if self.bundle.initialisation.mode != "empirical_joint":
            raise ValueError("Integrated vault owner must be empirical_joint.")
        if self.market.mode != "empirical_block_bootstrap":
            raise ValueError("Integrated market owner must be empirical.")
        if self.gas.mode != "empirical_components":
            raise ValueError("Integrated gas owner must use empirical components.")
        if self.liquidation_demand.mode != "empirical_hurdle_count":
            raise ValueError("Integrated arrival owner must be empirical hourly demand.")
        if self.liquidation_demand.sequence_mode != "none":
            raise ValueError("Sequence sensitivity must not be central.")
        if self.keeper.maximum_liquidations_per_step != SHARED_KEEPER_CAPACITY:
            raise ValueError("Shared keeper capacity must equal 26.")
        if self.keeper.system_wide_status != "shared_across_all_collateral_types":
            raise ValueError("Keeper capacity must remain shared system-wide.")
        if self.keeper.capacity_profile_id != "shared_keeper_capacity_central":
            raise ValueError("Unexpected central keeper-capacity candidate.")
        if self.keeper.hurdle_profile_id != "direct_cost_only":
            raise ValueError("Central keeper hurdle must be direct_cost_only.")
        if self.keeper.risk_cost_rate != 0.0 or liquidation.risk_cost_rate != 0.0:
            raise ValueError("Central keeper hurdle must remain zero.")
        if liquidation.max_liquidations_per_step != SHARED_KEEPER_CAPACITY:
            raise ValueError("Profile liquidation cap must resolve to 26.")
        if liquidation.max_close_factor != 1.0:
            raise ValueError("Integrated profile must retain full-close liquidation.")
        if simulation.oracle_delay_steps != 0:
            raise ValueError("Transparent oracle baseline must use zero delay.")
        if self.oracle_status != "transparent_baseline_not_calibrated":
            raise ValueError("Unexpected oracle status.")
        if self.confidence.scenario.identifier != "stage1_only":
            raise ValueError("Integrated profile must use stage1_only confidence.")
        if self.confidence.persistent_config is not None:
            raise ValueError("Persistent confidence must remain disabled.")
        if self.confidence.panic_response != 0.0:
            raise ValueError("Stage 1-only panic contribution must be zero.")
        if self.total_debt_dai != TOTAL_DEBT_DAI:
            raise ValueError("Integrated total debt must remain 2.5 million DAI.")
        if self.input_checksums != EXPECTED_INPUT_CHECKSUMS:
            raise ValueError("Protected integrated input checksums differ.")
        if self.runtime_adopted:
            raise ValueError("Integrated profile must remain opt-in.")


def resolve_integrated_empirical_eth_profile(
    path: Path | str = DEFAULT_PROFILE_PATH,
) -> IntegratedEmpiricalETHProfile:
    """Resolve and validate the additive integrated profile without fallback."""
    profile_path = Path(path).resolve()
    raw = load_configuration_payload(profile_path)
    if raw.get("bundle_name") != PROFILE_IDENTIFIER:
        raise ValueError("Integrated profile bundle_name is missing or incorrect.")
    if raw.get("mode") != "empirical":
        raise ValueError("Integrated profile must use the empirical semantic mode.")
    provenance = raw.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("Integrated profile provenance must be explicit.")
    if provenance.get("profile_identifier") != PROFILE_IDENTIFIER:
        raise ValueError("Integrated profile provenance identifier is incorrect.")

    bundle = load_tranche_b_configuration(profile_path)
    market_raw = raw.get("market_process")
    gas_raw = raw.get("gas_process")
    demand_raw = raw.get("liquidation_demand")
    if not all(isinstance(value, dict) for value in (market_raw, gas_raw, demand_raw)):
        raise ValueError("All empirical process owners must be explicit mappings.")

    market_path = _path(market_raw, "pool_path")
    gas_path = _path(gas_raw, "pool_path")
    demand_path = _path(demand_raw, "pool_path")
    vault_path = bundle.initialisation.pool_path
    if vault_path is None:
        raise ValueError("Integrated vault pool path must be explicit.")
    sequence_path = (
        REPOSITORY_ROOT
        / "data/liquidations/model_inputs/arrival/sequence_pool.csv"
    )
    observed = {
        "vault_initialisation": sha256_file(vault_path),
        "market_gas": sha256_file(market_path),
        "keeper_gas": sha256_file(gas_path),
        "liquidation_arrival": sha256_file(demand_path),
        "liquidation_sequence_sensitivity": sha256_file(sequence_path),
    }
    if observed != EXPECTED_INPUT_CHECKSUMS:
        raise ValueError(
            f"Protected input checksum failure: expected "
            f"{EXPECTED_INPUT_CHECKSUMS}, observed {observed}."
        )

    market = MarketProcessConfig(
        mode=str(market_raw["mode"]),
        pool_path=market_path,
        pool_sha256=str(market_raw["pool_sha256"]),
        pool_label=str(market_raw["pool_label"]),
        block_length_hours=int(market_raw["block_length_hours"]),
        seed=int(market_raw["seed"]),
        return_type=str(market_raw["return_type"]),
        alignment_mode=str(market_raw["alignment_mode"]),
        withheld_period_policy=str(market_raw["withheld_period_policy"]),
        shock_overlay_enabled=bool(market_raw["shock_overlay_enabled"]),
    )
    gas = GasProcessConfig(
        mode=str(gas_raw["mode"]),
        pool_path=gas_path,
        pool_sha256=str(gas_raw["pool_sha256"]),
        seed=int(gas_raw["seed"]),
        alignment_mode=str(gas_raw["alignment_mode"]),
        zero_observation_policy=str(gas_raw["zero_observation_policy"]),
        event_type=str(gas_raw["event_type"]),
        cost_currency=str(gas_raw["cost_currency"]),
        network_gas_column=str(gas_raw["network_gas_column"]),
    )
    demand = LiquidationDemandConfig(
        mode=str(demand_raw["mode"]),
        pool_path=demand_path,
        pool_sha256=str(demand_raw["pool_sha256"]),
        seed=int(demand_raw["seed"]),
        hurdle_probability=float(demand_raw["hurdle_probability"]),
        hurdle_estimator=str(demand_raw["hurdle_estimator"]),
        positive_count_mode=str(demand_raw["positive_count_mode"]),
        sequence_mode=str(demand_raw["sequence_mode"]),
        inventory_conditioning=str(demand_raw["inventory_conditioning"]),
        count_truncation_policy=str(demand_raw["count_truncation_policy"]),
    )
    market.validate()
    gas.validate()
    demand.validate()

    keeper = resolve_keeper_execution_candidate(
        "shared_keeper_capacity_central",
        "direct_cost_only",
    )
    if keeper.registry_checksum != EXPECTED_KEEPER_CONFIGURATION_SHA256:
        raise ValueError("Keeper configuration checksum differs.")
    registry_path = (
        REPOSITORY_ROOT
        / "data/provenance/calibration/keeper/keeper_execution_registry.csv"
    )
    if sha256_file(registry_path) != EXPECTED_KEEPER_REGISTRY_SHA256:
        raise ValueError("Keeper evidence registry checksum differs.")
    confidence = resolve_confidence_scenario("stage1_only")

    identity_payload = {
        "identifier": PROFILE_IDENTIFIER,
        "profile_checksum": sha256_file(profile_path),
        "input_checksums": observed,
        "keeper_configuration_checksum": keeper.registry_checksum,
        "keeper_evidence_registry_checksum": EXPECTED_KEEPER_REGISTRY_SHA256,
        "keeper_capacity_profile": keeper.capacity_profile_id,
        "keeper_hurdle_profile": keeper.hurdle_profile_id,
        "confidence_scenario": confidence.scenario.identifier,
        "stage1_below_peg_response": EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
        "stage1_above_peg_response": EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
        "residual_sequence_sha256": EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
        "residual_block_sha256": EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
        "vault_count": VAULT_COUNT,
        "total_debt_dai": TOTAL_DEBT_DAI,
        "dynamic_hours": DYNAMIC_HOURS,
        "oracle_status": provenance.get("oracle_status"),
        "runtime_adopted": bool(provenance.get("runtime_adopted")),
    }
    profile = IntegratedEmpiricalETHProfile(
        identifier=PROFILE_IDENTIFIER,
        profile_path=profile_path,
        profile_checksum=sha256_file(profile_path),
        profile_identity=_payload_sha256(identity_payload),
        bundle=bundle,
        market=market,
        gas=gas,
        liquidation_demand=demand,
        keeper=keeper,
        confidence=confidence,
        owner_paths={
            "profile": _relative(profile_path),
            "vault_initialisation": _relative(vault_path),
            "market_gas": _relative(market_path),
            "keeper_gas": _relative(gas_path),
            "liquidation_arrival": _relative(demand_path),
            "liquidation_sequence_sensitivity": _relative(sequence_path),
            "keeper_configuration": _relative(keeper.source_file),
            "keeper_evidence_registry": _relative(registry_path),
            "confidence_registry": _relative(DEFAULT_CONFIDENCE_REGISTRY_PATH),
        },
        input_checksums=observed,
        total_debt_dai=TOTAL_DEBT_DAI,
        oracle_status=str(provenance["oracle_status"]),
        experiment_ready=bool(provenance.get("experiment_ready", False)),
        runtime_adopted=bool(provenance["runtime_adopted"]),
    )
    profile.validate()
    return profile
