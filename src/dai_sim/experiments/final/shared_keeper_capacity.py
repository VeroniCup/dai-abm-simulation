"""Pre-registered Experiment D shared-keeper-capacity study.

Experiment D consumes the nine immutable D rows in the final dissertation
programme.  It composes the established portfolio, shock, market, keeper,
confidence and evidence owners.  This module owns only the capacity treatment,
capacity diagnostics, paired contrasts and Experiment D evidence.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import inspect
import json
import math
import multiprocessing
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any

import numpy as np
import pandas as pd

from dai_sim.experiments.final import (
    correlated_stress as experiment_b,
    idiosyncratic_diversification as experiment_a,
    stable_collateral_tradeoff as experiment_c,
)
from dai_sim.experiments.final.programme import (
    FinalExperimentProgramme,
    ProgrammeCell,
    load_programme,
)
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file
from dai_sim.inputs.gas import component_gas_costs
from dai_sim.inputs.integrated_profile import (
    EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
    EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
    EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
    EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
    resolve_integrated_empirical_eth_profile,
)
from dai_sim.inputs.liquidations import load_liquidation_arrival_pool
from dai_sim.inputs.multicollateral import (
    FAMILY_ORDER,
    load_final_market_pool,
    resolve_multicollateral_inputs,
)
from dai_sim.model.collateral import CollateralPortfolioConfig
from dai_sim.model.liquidation import (
    execute_keeper_liquidation,
    rank_liquidation_candidates,
)
from dai_sim.validation import multicollateral as multicollateral_validation


EXPERIMENT_D_PARENT_COMMIT = (
    "df498045a9e331d7570fef9a4fcc1e783c9f2fee"
)
MASTER_PROGRAMME_IDENTITY = (
    "084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260"
)
EXPERIMENT_A_IDENTITY = (
    "a9d7c3fa5dc5da9bcf61314a57501ea5a8be506e305eee6f45afaae3131600bb"
)
EXPERIMENT_B_IDENTITY = (
    "e02c035162f8178c96d2cae71d0a581ce813ab33526854bd5810e8e2810ead83"
)
EXPERIMENT_C_IDENTITY = (
    "cb6d00877c54011cc49714bdfe23fad83140fef001568ea9b43d355811c9129b"
)
PROFILE_IDENTITY = "d0241808701d0472532c1f7c502ab6637afd60a50082b94bed9ff66f7ec2d53e"
PROFILE_SHA256 = "a2da654cdc9fc053c50f13aacb18e63ce7854bf47d6ad1519352467f6c7986fc"
COLLATERAL_REGISTRY_SHA256 = (
    "75268fed6b3db5a80a822a80b8629291491cd73ce62b4c3e6cf3975060b4eb6d"
)
PORTFOLIO_REGISTRY_SHA256 = (
    "76aa03afa352d86be76fbc7e0153981589f50798c52aed7dfad897061b7960b1"
)
SHOCK_REGISTRY_SHA256 = (
    "a98df90e3e743fc22d9f92c38d53cf46a893928d3fe48eda9e609a20aa108581"
)
KEEPER_REGISTRY_SHA256 = (
    "58c5754ed95dead1ad283a7961fb0588496804a94f58ddb0e196a57601ee1e1b"
)
CONFIDENCE_REGISTRY_SHA256 = (
    "d455306fd7b7553f113099b6d51f962939d8b4793439a02c4638c646a63b25da"
)
EXPERIMENT_A_EVIDENCE_SHA256 = (
    "110b0d16a0f945bd720c400957e8c94297b4d20d19bda495ca7601640c90900c"
)
EXPERIMENT_B_EVIDENCE_SHA256 = (
    "091a420491c51bc1b25157a5adcef9565673e012d49fe90f350361b64aa3dc83"
)
EXPERIMENT_C_EVIDENCE_SHA256 = (
    "7f26a4bc4230d496f7e3a7a96496f4ff709342b4c4d6f7987889bf25304275b6"
)
EXPERIMENT_A_CHECKPOINT_SHA256 = (
    "aa31d65e4609db14e4b8392eb623dfdaae3c15cdf08eef6c100e313729508583"
)
EXPERIMENT_B_CHECKPOINT_SHA256 = (
    "e780bc139e34e64975d3108f6565509ab3c5db93758023a246a4913f5766e781"
)
EXPERIMENT_C_CHECKPOINT_SHA256 = (
    "57e645f44db5af1db337d72f18a2c3460c0f6cae32341152acf7b586a14c52d0"
)

EXPERIMENT_ID = "D_shared_keeper_capacity"
EXPERIMENT_NAMESPACE = "final-shared-keeper-capacity-v1"
EVIDENCE_DIR = (
    REPOSITORY_ROOT
    / "data/provenance/experiments/final/shared_keeper_capacity"
)
OUTPUT_ROOT = REPOSITORY_ROOT / "outputs/experiments/final/shared_keeper_capacity"
MANIFEST_PATH = REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"
BASE_MANIFEST_ARTEFACTS_SHA256 = (
    "45d2c9414c5a3c24458ca04719de15f4171eaaa05067d880908d4cf7c40a6fcf"
)

ANCHOR_ORDER = (
    ("empirical_crypto", "joint_crypto_high_correlation"),
    ("stable_supported", "joint_crypto_stable_stress"),
    ("stable_heavy", "joint_crypto_stable_stress"),
)
CAPACITY_ORDER = (14, 26, 45)
CAPACITY_PROFILES = {
    14: "shared_keeper_capacity_low",
    26: "shared_keeper_capacity_central",
    45: "shared_keeper_capacity_high",
}
CELL_ORDER = tuple(
    f"{shock}__{portfolio}__{CAPACITY_PROFILES[capacity]}"
    for portfolio, shock in ANCHOR_ORDER
    for capacity in CAPACITY_ORDER
)
EXPECTED_MASTER_CELL_CHECKSUMS = (
    "d96ecba966fc94b8bb2584a63af3c7ba95f654629f5c6c2af703a36c2b0bb870",
    "764da77417a403dab31c2389e0648440d3d805e2ee08023fde2a162934087734",
    "b1ba98d03359d1adce0187211462ae6caaf29c9667c9f1ca6bf6c15d2e191c0f",
    "cfbeeb8252b5ea953f3808d2db52a7ea2f0b995971c72b872d5c69f7cfba2602",
    "daf856fcd2180197a22a31b406a893390084316612092ae0606debfcb4e010c7",
    "e7ab6e7e6ca7be2c3467d4764d797be209ffd531c2256a13a11aeb2f906fc2c9",
    "cea91dab3be14741ba3dfb2f273a81fb916a9a3a7076d4521b613bbb161bf2e5",
    "9d409ee598738144ebab8465709d5bae3b427f272fbef841d7d4a4d8cec86bbd",
    "e1fa955384d99d03c001157864810efece3b09113c37d29834bce6cd0bfa76a2",
)

REPLICATIONS = 128
VAULT_COUNT = 500
TOTAL_DEBT_DAI = 2_500_000.0
TARGET_SYSTEM_COLLATERAL_RATIO = 3.6089387701260205
PRE_SHOCK_HOURS = 48
POST_SHOCK_HOURS = 720
TOTAL_HOURS = 768
MAXIMUM_OUTPUT_BYTES = 750 * 1024**2
MINIMUM_FREE_BYTES = 10 * 1024**3
INITIALISATION_REPLICATION_OFFSET = 3_000_000

SEED_STREAMS = (
    "initialisation_key",
    "market_gas_blocks",
    "keeper_gas_units",
    "liquidation_arrivals",
    "stage1_residual_blocks",
)
PRIMARY_COMPLETION_METRICS = (
    "backlog_area_share",
    "maximum_unresolved_tab_share",
    "terminal_unresolved_tab_share",
    "liquidation_completion_ratio",
)
SECONDARY_EXECUTION_METRICS = (
    "capacity_rejected_opportunity_count",
    "capacity_rejection_share",
    "successful_closure_count",
    "liquidated_debt_share",
    "debt_weighted_liquidated_vault_share",
    "hours_with_positive_unresolved_backlog",
    "capacity_binding_hours",
    "mean_capacity_utilisation",
    "maximum_capacity_utilisation",
    "mean_positive_demand_utilisation",
    "positive_demand_binding_share",
    "all_hour_binding_share",
    "unused_capacity_positive_demand_hours",
)
BAD_DEBT_METRICS = (
    "realised_bad_debt_share",
    "positive_realised_bad_debt",
    "terminal_active_bad_debt_share",
)
PEG_METRICS = (
    "below_peg_burden",
    "mean_absolute_peg_deviation",
    "minimum_dai_price",
    "restricted_mean_recovery_time",
    "recovery_probability_720h",
)
SYSTEM_METRICS = (
    *PRIMARY_COMPLETION_METRICS,
    *SECONDARY_EXECUTION_METRICS,
    *BAD_DEBT_METRICS,
    *PEG_METRICS,
)
COLLATERAL_METRICS = (
    "initial_debt_exposure",
    "eligible_liquidation_tab",
    "candidate_count",
    "profitability_filtered_count",
    "selected_count",
    "rejected_count",
    "successful_closure_count",
    "liquidated_debt",
    "terminal_unresolved_tab",
    "backlog_area",
    "maximum_backlog",
    "terminal_active_bad_debt",
    "realised_bad_debt",
    "keeper_profit_proxy",
    "share_system_capacity_consumed",
    "share_system_rejections",
    "contribution_to_system_backlog",
    "exposure_normalised_backlog",
    "exposure_normalised_unresolved_tab",
    "displaced_candidates",
    "cross_family_displacement_hours",
)
HIGHER_IS_BETTER = {
    "liquidation_completion_ratio",
    "successful_closure_count",
    "liquidated_debt_share",
    "debt_weighted_liquidated_vault_share",
    "minimum_dai_price",
    "recovery_probability_720h",
}
METRIC_DIRECTIONS = {
    metric: (-1 if metric in HIGHER_IS_BETTER else 1)
    for metric in SYSTEM_METRICS
}
MATERIALITY_THRESHOLDS = {
    "numerical_tolerance": 1e-10,
    "accounting_tolerance_dai": 1e-5,
    "failure_share_invalid": 0.01,
    "contrast_interval_confidence": 0.95,
    "backlog_share_scale": 1.0 / TOTAL_DEBT_DAI,
    "positive_demand_hour_scale": 1.0 / POST_SHOCK_HOURS,
    "capacity_coordinate_scale": 1.0 / max(CAPACITY_ORDER),
}
COMPACT_FILENAMES = (
    "shared_keeper_capacity_specification.json",
    "shared_keeper_capacity_registry.csv",
    "shared_keeper_capacity_cell_summary.csv",
    "shared_keeper_capacity_collateral_summary.csv",
    "shared_keeper_capacity_contrasts.csv",
    "shared_keeper_capacity_decision.json",
    "shared_keeper_capacity_reproducibility.json",
    "shared_keeper_capacity_benchmark.json",
)
DETERMINISTIC_FILENAMES = COMPACT_FILENAMES[:-1]
DISTRIBUTION_FIELDS = (
    "mean",
    "standard_error",
    "ci95_lower",
    "ci95_upper",
    "median",
    "p05",
    "p25",
    "p75",
    "p90",
    "p95",
    "positive_share",
)


def _payload_sha256(payload: Any) -> str:
    return experiment_c._payload_sha256(payload)


def _pretty_json(payload: Any) -> bytes:
    return experiment_c._pretty_json(payload)


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return experiment_c._csv_bytes(frame)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    experiment_c._atomic_bytes(path, payload)


def _atomic_json(path: Path, payload: Any) -> None:
    experiment_c._atomic_json(path, payload)


def _relative(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def _row_checksum(row: Mapping[str, Any]) -> str:
    return _payload_sha256(dict(row))


def derive_seed(replication: int, stream: str, substream: str = "") -> int:
    digest = hashlib.sha256(
        f"{EXPERIMENT_NAMESPACE}|{replication}|{stream}|{substream}".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def initialisation_replication_key(replication: int) -> int:
    return INITIALISATION_REPLICATION_OFFSET + replication


def seed_record(replication: int) -> dict[str, Any]:
    return {
        "replication": replication,
        "namespace": EXPERIMENT_NAMESPACE,
        "initialisation_replication_key": initialisation_replication_key(
            replication
        ),
        **{
            stream: derive_seed(replication, stream)
            for stream in SEED_STREAMS
            if stream != "initialisation_key"
        },
    }


def seed_registry_checksum(replications: int = REPLICATIONS) -> str:
    return _payload_sha256(
        [seed_record(replication) for replication in range(replications)]
    )


@dataclass(frozen=True)
class ExperimentDCell:
    order: int
    identifier: str
    portfolio: str
    shock: str
    capacity_profile: str
    capacity: int
    hurdle: str
    confidence: str
    oracle_delay: int
    replication_count: int
    master_row_checksum: str


def _validate_master_cell(cell: ProgrammeCell) -> None:
    if (
        cell.experiment_identifier != EXPERIMENT_ID
        or cell.confidence_scenario_identifier != "stage1_only"
        or cell.hurdle_profile_identifier != "direct_cost_only"
        or float(cell.risk_cost_rate) != 0.0
        or cell.oracle_treatment_identifier
        != "transparent_zero_delay_baseline"
        or cell.oracle_delay_steps != 0
        or cell.replication_count != REPLICATIONS
    ):
        raise ValueError("Experiment D master row changed.")
    if cell.maximum_liquidations_per_step not in CAPACITY_ORDER:
        raise ValueError("Experiment D capacity coordinate changed.")
    if (
        cell.capacity_profile_identifier
        != CAPACITY_PROFILES[cell.maximum_liquidations_per_step]
    ):
        raise ValueError("Experiment D capacity profile changed.")


def build_cell_registry(
    programme: FinalExperimentProgramme | None = None,
) -> tuple[ExperimentDCell, ...]:
    owner = load_programme() if programme is None else programme
    if owner.programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Master programme identity changed.")
    experiment = owner.experiments_by_identifier[EXPERIMENT_ID]
    observed = tuple(cell.identifier for cell in experiment.cells)
    checksums = tuple(cell.row_checksum for cell in experiment.cells)
    if observed != CELL_ORDER:
        raise ValueError(
            f"Experiment D master order differs: observed={observed!r}."
        )
    if checksums != EXPECTED_MASTER_CELL_CHECKSUMS:
        raise ValueError("Experiment D master row checksum changed.")
    rows: list[ExperimentDCell] = []
    for cell in experiment.cells:
        _validate_master_cell(cell)
        rows.append(
            ExperimentDCell(
                order=cell.cell_order,
                identifier=cell.identifier,
                portfolio=cell.portfolio_identifier,
                shock=cell.shock_identifier,
                capacity_profile=cell.capacity_profile_identifier,
                capacity=int(cell.maximum_liquidations_per_step),
                hurdle=cell.hurdle_profile_identifier,
                confidence=cell.confidence_scenario_identifier,
                oracle_delay=int(cell.oracle_delay_steps),
                replication_count=cell.replication_count,
                master_row_checksum=cell.row_checksum,
            )
        )
    return tuple(rows)


def _registry_frame() -> pd.DataFrame:
    rows = []
    for cell in build_cell_registry():
        row = asdict(cell)
        row["row_checksum"] = _row_checksum(row)
        rows.append(row)
    return pd.DataFrame(rows)


def _draw_d_states(replication: int) -> dict[str, Any]:
    state_key = initialisation_replication_key(replication)
    collateral, portfolios, pool = experiment_a._design_payloads()
    for attempt in range(100):
        empirical, _ = experiment_a._draw_nested_family_streams(
            replication=state_key,
            attempt=attempt,
            collateral_payload=collateral,
            portfolio_payload=portfolios,
            pool=pool,
        )
        master_seed = experiment_a.derive_seed(
            state_key, "initialisation_master"
        )
        stable_rng = np.random.default_rng(
            experiment_a.derive_seed(
                state_key,
                "vault_STABLE",
                f"master:{master_seed}:attempt:{attempt}",
            )
        )
        stable = multicollateral_validation._sample_stable_family(
            family_config=multicollateral_validation._family_payload(
                collateral, "STABLE"
            ),
            count=250,
            rng=stable_rng,
        )
        for position, row in enumerate(stable):
            row["family_stream_position"] = position
        try:
            states = {
                portfolio: experiment_a._normalise_nested_portfolio(
                    portfolio=portfolio,
                    replication=state_key,
                    attempt=attempt,
                    empirical=empirical,
                    stable=stable,
                    collateral_payload=collateral,
                    portfolio_payload=portfolios,
                )
                for portfolio in (
                    "empirical_crypto",
                    "stable_supported",
                    "stable_heavy",
                )
            }
        except ValueError as exc:
            if "initially unsafe" in str(exc):
                continue
            raise
        audit = experiment_c.audit_nested_initialisations(states)
        return {"states": states, "audit": audit}
    raise ValueError("No common safe Experiment D initialisation was accepted.")


def _arrival_stream(replication: int) -> dict[str, Any]:
    integrated = resolve_integrated_empirical_eth_profile()
    config = integrated.liquidation_demand
    pool = load_liquidation_arrival_pool(config.pool_path, config.pool_sha256)
    positive = pool.loc[
        pool["positive_count_eligible"].astype(bool), "grab_count"
    ].to_numpy(dtype=int)
    rng = np.random.default_rng(
        derive_seed(replication, "liquidation_arrivals")
    )
    uniforms = rng.random(TOTAL_HOURS)
    counts = rng.choice(positive, size=TOTAL_HOURS, replace=True)
    return {
        "uniforms": uniforms,
        "positive_counts": counts,
        "hurdle_probability": float(config.hurdle_probability),
        "checksum": _payload_sha256(
            {
                "uniforms": hashlib.sha256(
                    np.asarray(uniforms, dtype="<f8").tobytes()
                ).hexdigest(),
                "counts": hashlib.sha256(
                    np.asarray(counts, dtype="<i8").tobytes()
                ).hexdigest(),
            }
        ),
    }


def _prepare_replication_streams(replication: int) -> dict[str, Any]:
    initialisation = _draw_d_states(replication)
    states = initialisation["states"]
    accepted_attempt = next(
        iter({int(state.accepted_attempt) for state in states.values()})
    )
    state_key = initialisation_replication_key(replication)
    master_seed = experiment_a.derive_seed(
        state_key, "initialisation_master"
    )
    profile = resolve_multicollateral_inputs("eth_only").profile
    market_pool = load_final_market_pool(
        profile.market_pool_path, profile.market_pool_sha256
    )
    block_length = int(profile.raw["market_process"]["block_length_hours"])
    starts = multicollateral_validation._valid_market_block_starts(
        market_pool, block_length
    )
    rng = np.random.default_rng(
        derive_seed(replication, "market_gas_blocks")
    )
    block_count = math.ceil(TOTAL_HOURS / block_length)
    chosen_starts = rng.choice(starts, size=block_count, replace=True)
    sampled = pd.concat(
        [
            market_pool.iloc[
                int(start) : int(start) + block_length
            ].copy()
            for start in chosen_starts
        ],
        ignore_index=True,
    ).iloc[:TOTAL_HOURS].copy()
    sampled.insert(0, "simulation_step", np.arange(TOTAL_HOURS, dtype=int))
    arrivals = _arrival_stream(replication)
    _, _, stage1 = experiment_a.load_stage1_owners()
    residual_rng = np.random.default_rng(
        derive_seed(replication, "stage1_residual_blocks")
    )
    residuals = experiment_a.sample_residual_blocks(
        stage1["source"],
        block_count=math.ceil(TOTAL_HOURS / 24),
        rng=residual_rng,
    )[:TOTAL_HOURS]
    components = {
        "initialisation_replication_key": state_key,
        "initialisation_master_seed": master_seed,
        "initialisation_accepted_attempt": accepted_attempt,
        "state_identities": {
            name: state.identity for name, state in states.items()
        },
        "market_start_indexes": [int(value) for value in chosen_starts],
        "market_rows_checksum": _payload_sha256(
            sampled["pool_row_id"].astype(str).tolist()
        ),
        "arrival_checksum": arrivals["checksum"],
        "residual_checksum": hashlib.sha256(
            np.asarray(residuals, dtype="<f8").tobytes()
        ).hexdigest(),
        "keeper_gas_units_seed": derive_seed(
            replication, "keeper_gas_units"
        ),
    }
    return {
        "states": states,
        "nested_audit": initialisation["audit"],
        "sampled_market": sampled,
        "arrivals": arrivals,
        "stage1": stage1,
        "residuals": residuals,
        "seed_ownership": seed_record(replication),
        "stream_components": components,
        "paired_stream_checksum": _payload_sha256(components),
    }


def _family(value: str) -> str:
    return "WBTC" if value == "BTC" else value


def _max_run(values: Sequence[bool]) -> int:
    maximum = current = 0
    for value in values:
        current = current + 1 if value else 0
        maximum = max(maximum, current)
    return maximum


def _demand_decision(
    *,
    step: int,
    inventory: int,
    uniform: float,
    positive_count: int,
    hurdle_probability: float,
    capacity: int,
) -> Any:
    active = bool(inventory and uniform < hurdle_probability)
    sampled = int(positive_count) if active else 0
    bounded = min(sampled, inventory)
    attempts = min(bounded, capacity)
    return experiment_a.LiquidationDemandDecision(
        step=step,
        liquidatable_inventory=inventory,
        activity_draw=active,
        raw_positive_count_draw=int(positive_count) if active else 0,
        sampled_demand=sampled,
        bounded_demand=bounded,
        keeper_capacity=capacity,
        attempt_budget=attempts,
        demand_truncated_by_inventory=max(sampled - bounded, 0),
        demand_truncated_by_capacity=max(bounded - attempts, 0),
        demand_inactive_unresolved=inventory if inventory and not active else 0,
        inventory_not_sampled_unresolved=inventory - bounded if active else 0,
    )


def _queue_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    columns = (
        "candidate_rank",
        "vault_id",
        "collateral_type",
        "debt_at_risk",
        "expected_profit",
    )
    return frame.loc[:, columns].to_dict(orient="records")


def _simulate_capacity_liquidations(
    *,
    initialisation: Any,
    price_paths: Mapping[str, np.ndarray],
    gas_costs: np.ndarray,
    arrivals: Mapping[str, Any],
    portfolio_config: CollateralPortfolioConfig,
    capacity: int,
) -> dict[str, Any]:
    """Apply the canonical ranking and keeper execution under one capacity."""
    if capacity not in CAPACITY_ORDER:
        raise ValueError("Experiment D capacity is not registered.")
    vaults = deepcopy(list(initialisation.vaults))
    vault_by_id = {int(vault.vault_id): vault for vault in vaults}
    if len(vault_by_id) != len(vaults):
        raise ValueError("Initial vault identifiers are not unique.")
    integrated = resolve_integrated_empirical_eth_profile()
    base_liquidation = integrated.bundle.base_bundle.liquidation_config
    arrays = {
        name: np.zeros(TOTAL_HOURS, dtype=dtype)
        for name, dtype in {
            "liquidatable_before": "<i8",
            "profitability_filtered": "<i8",
            "sampled_arrivals": "<i8",
            "selected_attempts": "<i8",
            "successful_liquidations": "<i8",
            "successful_closures": "<i8",
            "failed_liquidation_attempts": "<i8",
            "capacity_rejected_opportunities": "<i8",
            "unresolved_tab_dai": "<f8",
            "active_bad_debt_dai": "<f8",
            "realised_bad_debt_dai": "<f8",
            "terminal_debt_writeoff_dai": "<f8",
            "cleared_tab_dai": "<f8",
            "keeper_profit_dai": "<f8",
            "liquidation_gate_open": "?",
            "material_active_bad_debt": "?",
        }.items()
    }
    family_arrays = {
        family: {
            name: np.zeros(TOTAL_HOURS, dtype="<f8")
            for name in (
                "candidates",
                "profitable",
                "selected",
                "rejected",
                "successful",
                "closures",
                "liquidated_debt",
                "backlog",
                "active_bad_debt",
                "realised_bad_debt",
                "terminal_debt_writeoff",
                "keeper_profit",
                "displaced",
                "cross_family_displacement",
            )
        }
        for family in FAMILY_ORDER
    }
    initial_debt = {
        family: float(
            sum(
                vault.debt_dai
                for vault in vaults
                if _family(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    initial_collateral = {
        family: float(
            sum(
                vault.collateral_amount
                for vault in vaults
                if _family(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    initial_debt_by_vault = {
        int(vault.vault_id): float(vault.debt_dai) for vault in vaults
    }
    eligible_seen: set[int] = set()
    eligible_tab = defaultdict(float)
    closed_ids: set[int] = set()
    liquidated_ids: set[int] = set()
    removed_collateral = defaultdict(float)
    repaid_debt = defaultdict(float)
    terminal_debt_writeoff = defaultdict(float)
    duplicate_attempt = False
    duplicate_closure = False
    reconciliation_failures = 0
    queue_audit_rows: list[dict[str, Any]] = []
    pairwise_identifiable = False

    for step in range(TOTAL_HOURS):
        prices = {
            "ETH": float(price_paths["ETH"][step]),
            "BTC": float(price_paths["BTC"][step]),
            "STABLE": float(price_paths["STABLE"][step]),
        }
        candidates = [
            vault
            for vault in vaults
            if vault.is_active and vault.is_liquidatable(prices)
        ]
        step_config = replace(
            base_liquidation,
            gas_cost=float(gas_costs[step]),
            risk_cost_rate=0.0,
            max_close_factor=1.0,
            max_liquidations_per_step=capacity,
        )
        ranked = rank_liquidation_candidates(
            candidates,
            prices=prices,
            config=step_config,
            portfolio=portfolio_config,
        )
        profitable = ranked.loc[ranked["expected_profit"].gt(0.0)].copy()
        for row in ranked.itertuples(index=False):
            vault_id = int(row.vault_id)
            if step >= PRE_SHOCK_HOURS and vault_id not in eligible_seen:
                eligible_seen.add(vault_id)
                eligible_tab[_family(str(row.collateral_type))] += float(
                    row.debt_at_risk
                )
        decision = _demand_decision(
            step=step,
            inventory=len(ranked),
            uniform=float(arrivals["uniforms"][step]),
            positive_count=int(arrivals["positive_counts"][step]),
            hurdle_probability=float(arrivals["hurdle_probability"]),
            capacity=capacity,
        )
        demand_selected = ranked.head(decision.bounded_demand)
        attempt_selected = ranked.head(decision.attempt_budget)
        rejected = demand_selected.iloc[decision.attempt_budget :]
        attempt_ids = attempt_selected["vault_id"].astype(int).tolist()
        duplicate_attempt = duplicate_attempt or len(attempt_ids) != len(
            set(attempt_ids)
        )
        candidate_by_family = Counter(
            _family(value) for value in ranked["collateral_type"]
        )
        profitable_by_family = Counter(
            _family(value) for value in profitable["collateral_type"]
        )
        selected_by_family = Counter(
            _family(value) for value in attempt_selected["collateral_type"]
        )
        rejected_by_family = Counter(
            _family(value) for value in rejected["collateral_type"]
        )
        selected_families = {
            family for family, count in selected_by_family.items() if count
        }
        rejected_families = {
            family for family, count in rejected_by_family.items() if count
        }
        selected_set = set(attempt_ids)
        displaced_by_family: dict[str, int] = {}
        for family in FAMILY_ORDER:
            isolated = (
                demand_selected.loc[
                    demand_selected["collateral_type"].map(_family).eq(family),
                    "vault_id",
                ]
                .head(capacity)
                .astype(int)
            )
            displaced_by_family[family] = (
                len(set(isolated) - selected_set)
                if decision.demand_truncated_by_capacity > 0
                else 0
            )
        queue_audit_rows.append(
            {
                "step": step,
                "eligible": _payload_sha256(_queue_records(ranked)),
                "profitable": _payload_sha256(_queue_records(profitable)),
                "ranked": _payload_sha256(_queue_records(ranked)),
                "selected": _payload_sha256(
                    _queue_records(attempt_selected)
                ),
                "rejected": _payload_sha256(_queue_records(rejected)),
                "candidate_count": len(ranked),
                "profitable_count": len(profitable),
                "selected_count": len(attempt_selected),
                "rejected_count": len(rejected),
            }
        )

        executions: list[dict[str, Any]] = []
        for vault_id in attempt_ids:
            vault = vault_by_id[vault_id]
            before_collateral = float(vault.collateral_amount)
            before_debt = float(vault.debt_dai)
            result = execute_keeper_liquidation(
                vault,
                prices,
                step_config,
                portfolio=portfolio_config,
            )
            result["family"] = _family(vault.collateral_type)
            result["collateral_removed"] = (
                before_collateral - float(vault.collateral_amount)
            )
            result["terminal_debt_writeoff"] = max(
                before_debt
                - float(vault.debt_dai)
                - float(result["debt_repaid"]),
                0.0,
            )
            if bool(result["fully_liquidated"]):
                if vault_id in closed_ids:
                    duplicate_closure = True
                closed_ids.add(vault_id)
            if bool(result["liquidated"]) and step >= PRE_SHOCK_HOURS:
                liquidated_ids.add(vault_id)
            executions.append(result)
        execution = pd.DataFrame(executions)
        for family in FAMILY_ORDER:
            selected = (
                execution.loc[execution["family"].eq(family)]
                if not execution.empty
                else execution
            )
            successful = (
                selected.loc[selected["liquidated"].astype(bool)]
                if not selected.empty
                else selected
            )
            closures = (
                selected.loc[selected["fully_liquidated"].astype(bool)]
                if not selected.empty
                else selected
            )
            liquidated_debt = (
                float(successful["debt_repaid"].sum())
                if not successful.empty
                else 0.0
            )
            realised_bad_debt = (
                float(closures["bad_debt"].sum())
                if not closures.empty
                else 0.0
            )
            debt_writeoff = (
                float(closures["terminal_debt_writeoff"].sum())
                if not closures.empty
                else 0.0
            )
            keeper_profit = (
                float(successful["realised_keeper_profit"].sum())
                if not successful.empty
                else 0.0
            )
            collateral_removed = (
                float(successful["collateral_removed"].sum())
                if not successful.empty
                else 0.0
            )
            repaid_debt[family] += liquidated_debt
            terminal_debt_writeoff[family] += debt_writeoff
            removed_collateral[family] += collateral_removed
            backlog = float(
                sum(
                    vault.debt_dai
                    for vault in vaults
                    if vault.is_active
                    and _family(vault.collateral_type) == family
                    and vault.is_liquidatable(prices)
                )
            )
            active_bad_debt = float(
                sum(
                    vault.bad_debt(prices)
                    for vault in vaults
                    if vault.is_active
                    and _family(vault.collateral_type) == family
                )
            )
            values = family_arrays[family]
            values["candidates"][step] = candidate_by_family[family]
            values["profitable"][step] = profitable_by_family[family]
            values["selected"][step] = selected_by_family[family]
            values["rejected"][step] = rejected_by_family[family]
            values["successful"][step] = len(successful)
            values["closures"][step] = len(closures)
            values["liquidated_debt"][step] = liquidated_debt
            values["backlog"][step] = backlog
            values["active_bad_debt"][step] = active_bad_debt
            values["realised_bad_debt"][step] = realised_bad_debt
            values["terminal_debt_writeoff"][step] = debt_writeoff
            values["keeper_profit"][step] = keeper_profit
            values["displaced"][step] = displaced_by_family[family]
            values["cross_family_displacement"][step] = bool(
                family in rejected_families
                and any(other != family for other in selected_families)
            )

        arrays["liquidatable_before"][step] = len(ranked)
        arrays["profitability_filtered"][step] = len(profitable)
        arrays["sampled_arrivals"][step] = len(demand_selected)
        arrays["selected_attempts"][step] = len(attempt_selected)
        arrays["successful_liquidations"][step] = sum(
            family_arrays[family]["successful"][step]
            for family in FAMILY_ORDER
        )
        arrays["successful_closures"][step] = sum(
            family_arrays[family]["closures"][step]
            for family in FAMILY_ORDER
        )
        arrays["failed_liquidation_attempts"][step] = (
            len(attempt_selected)
            - arrays["successful_liquidations"][step]
        )
        arrays["capacity_rejected_opportunities"][step] = len(rejected)
        arrays["unresolved_tab_dai"][step] = sum(
            family_arrays[family]["backlog"][step] for family in FAMILY_ORDER
        )
        arrays["active_bad_debt_dai"][step] = sum(
            family_arrays[family]["active_bad_debt"][step]
            for family in FAMILY_ORDER
        )
        arrays["realised_bad_debt_dai"][step] = sum(
            family_arrays[family]["realised_bad_debt"][step]
            for family in FAMILY_ORDER
        )
        arrays["terminal_debt_writeoff_dai"][step] = sum(
            family_arrays[family]["terminal_debt_writeoff"][step]
            for family in FAMILY_ORDER
        )
        arrays["cleared_tab_dai"][step] = sum(
            family_arrays[family]["liquidated_debt"][step]
            for family in FAMILY_ORDER
        )
        arrays["keeper_profit_dai"][step] = sum(
            family_arrays[family]["keeper_profit"][step]
            for family in FAMILY_ORDER
        )
        arrays["liquidation_gate_open"][step] = (
            arrays["unresolved_tab_dai"][step] <= 1e-9
        )
        arrays["material_active_bad_debt"][step] = (
            arrays["active_bad_debt_dai"][step] > 1e-6
        )
        for family_metric, system_metric in (
            ("candidates", "liquidatable_before"),
            ("profitable", "profitability_filtered"),
            ("selected", "selected_attempts"),
            ("rejected", "capacity_rejected_opportunities"),
            ("successful", "successful_liquidations"),
            ("closures", "successful_closures"),
            ("liquidated_debt", "cleared_tab_dai"),
            ("backlog", "unresolved_tab_dai"),
            ("active_bad_debt", "active_bad_debt_dai"),
            ("realised_bad_debt", "realised_bad_debt_dai"),
            ("terminal_debt_writeoff", "terminal_debt_writeoff_dai"),
            ("keeper_profit", "keeper_profit_dai"),
        ):
            if not math.isclose(
                float(arrays[system_metric][step]),
                sum(
                    float(family_arrays[family][family_metric][step])
                    for family in FAMILY_ORDER
                ),
                rel_tol=0.0,
                abs_tol=1e-8,
            ):
                reconciliation_failures += 1

    final_debt = {
        family: float(
            sum(
                vault.debt_dai
                for vault in vaults
                if vault.is_active
                and _family(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    final_collateral = {
        family: float(
            sum(
                vault.collateral_amount
                for vault in vaults
                if vault.is_active
                and _family(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    debt_errors = {
        family: (
            initial_debt[family]
            - final_debt[family]
            - repaid_debt[family]
            - terminal_debt_writeoff[family]
        )
        for family in FAMILY_ORDER
    }
    collateral_errors = {
        family: (
            initial_collateral[family]
            - final_collateral[family]
            - removed_collateral[family]
        )
        for family in FAMILY_ORDER
    }
    accounting_valid = bool(
        reconciliation_failures == 0
        and not duplicate_attempt
        and not duplicate_closure
        and all(abs(value) <= 1e-5 for value in debt_errors.values())
        and all(abs(value) <= 1e-5 for value in collateral_errors.values())
    )
    post = slice(PRE_SHOCK_HOURS, None)
    positive_demand = arrays["sampled_arrivals"][post] > 0
    binding = arrays["capacity_rejected_opportunities"][post] > 0
    selected_post = arrays["selected_attempts"][post]
    total_eligible_tab = float(sum(eligible_tab.values()))
    cleared_tab = float(arrays["cleared_tab_dai"][post].sum())
    system_summary = {
        "initial_total_debt_dai": TOTAL_DEBT_DAI,
        "backlog_area_share": float(
            arrays["unresolved_tab_dai"][post].sum() / TOTAL_DEBT_DAI
        ),
        "maximum_unresolved_tab_share": float(
            arrays["unresolved_tab_dai"][post].max() / TOTAL_DEBT_DAI
        ),
        "terminal_unresolved_tab_share": float(
            arrays["unresolved_tab_dai"][-1] / TOTAL_DEBT_DAI
        ),
        "liquidation_completion_ratio": (
            None if total_eligible_tab == 0.0 else cleared_tab / total_eligible_tab
        ),
        "capacity_rejected_opportunity_count": int(
            arrays["capacity_rejected_opportunities"][post].sum()
        ),
        "capacity_rejection_share": (
            None
            if arrays["sampled_arrivals"][post].sum() == 0
            else float(
                arrays["capacity_rejected_opportunities"][post].sum()
                / arrays["sampled_arrivals"][post].sum()
            )
        ),
        "successful_closure_count": int(
            arrays["successful_closures"][post].sum()
        ),
        "liquidated_debt_share": cleared_tab / TOTAL_DEBT_DAI,
        "debt_weighted_liquidated_vault_share": float(
            sum(initial_debt_by_vault[vault_id] for vault_id in liquidated_ids)
            / TOTAL_DEBT_DAI
        ),
        "hours_with_positive_unresolved_backlog": int(
            np.count_nonzero(arrays["unresolved_tab_dai"][post] > 1e-9)
        ),
        "capacity_binding_hours": int(np.count_nonzero(binding)),
        "mean_capacity_utilisation": float(np.mean(selected_post / capacity)),
        "maximum_capacity_utilisation": float(np.max(selected_post / capacity)),
        "mean_positive_demand_utilisation": (
            0.0
            if not np.any(positive_demand)
            else float(np.mean(selected_post[positive_demand] / capacity))
        ),
        "positive_demand_binding_share": (
            0.0
            if not np.any(positive_demand)
            else float(np.mean(binding[positive_demand]))
        ),
        "all_hour_binding_share": float(np.mean(binding)),
        "unused_capacity_positive_demand_hours": int(
            np.sum(capacity - selected_post[positive_demand])
        ),
        "realised_bad_debt_share": float(
            arrays["realised_bad_debt_dai"][post].sum() / TOTAL_DEBT_DAI
        ),
        "positive_realised_bad_debt": int(
            arrays["realised_bad_debt_dai"][post].sum() > 1e-9
        ),
        "terminal_active_bad_debt_share": float(
            arrays["active_bad_debt_dai"][-1] / TOTAL_DEBT_DAI
        ),
        "eligible_liquidation_tab": total_eligible_tab,
        "positive_demand_hours": int(np.count_nonzero(positive_demand)),
        "maximum_backlog_duration": _max_run(
            arrays["unresolved_tab_dai"][post] > 1e-9
        ),
        "accounting_valid": accounting_valid,
        "reconciliation_failure_count": reconciliation_failures,
        "duplicate_attempt": duplicate_attempt,
        "duplicate_closure": duplicate_closure,
        "shared_capacity_valid": bool(
            np.all(arrays["selected_attempts"] <= capacity)
        ),
        "nonnegative_backlog_valid": bool(
            np.all(arrays["unresolved_tab_dai"] >= -1e-12)
        ),
        "numerical_valid": bool(
            all(np.isfinite(values).all() for values in arrays.values())
            and all(vault.debt_dai >= 0.0 for vault in vaults)
            and all(vault.collateral_amount >= 0.0 for vault in vaults)
        ),
    }
    system_backlog = float(
        sum(
            family_arrays[family]["backlog"][post].sum()
            for family in FAMILY_ORDER
        )
    )
    total_selected = float(arrays["selected_attempts"][post].sum())
    total_rejected = float(
        arrays["capacity_rejected_opportunities"][post].sum()
    )
    collateral_rows: list[dict[str, Any]] = []
    for family in FAMILY_ORDER:
        exposure = initial_debt[family]
        values = family_arrays[family]
        backlog = float(values["backlog"][post].sum())
        terminal = float(values["backlog"][-1])
        collateral_rows.append(
            {
                "family": family,
                "initial_debt_exposure": exposure,
                "eligible_liquidation_tab": float(eligible_tab[family]),
                "candidate_count": int(values["candidates"][post].sum()),
                "profitability_filtered_count": int(
                    values["profitable"][post].sum()
                ),
                "selected_count": int(values["selected"][post].sum()),
                "rejected_count": int(values["rejected"][post].sum()),
                "successful_closure_count": int(
                    values["closures"][post].sum()
                ),
                "liquidated_debt": float(
                    values["liquidated_debt"][post].sum()
                ),
                "terminal_unresolved_tab": terminal,
                "backlog_area": backlog,
                "maximum_backlog": float(values["backlog"][post].max()),
                "terminal_active_bad_debt": float(
                    values["active_bad_debt"][-1]
                ),
                "realised_bad_debt": float(
                    values["realised_bad_debt"][post].sum()
                ),
                "keeper_profit_proxy": float(
                    values["keeper_profit"][post].sum()
                ),
                "share_system_capacity_consumed": (
                    None
                    if total_selected == 0.0
                    else float(values["selected"][post].sum() / total_selected)
                ),
                "share_system_rejections": (
                    None
                    if total_rejected == 0.0
                    else float(values["rejected"][post].sum() / total_rejected)
                ),
                "contribution_to_system_backlog": (
                    None if system_backlog == 0.0 else backlog / system_backlog
                ),
                "exposure_normalised_backlog": (
                    None if exposure == 0.0 else backlog / exposure
                ),
                "exposure_normalised_unresolved_tab": (
                    None if exposure == 0.0 else terminal / exposure
                ),
                "displaced_candidates": int(
                    values["displaced"][post].sum()
                ),
                "cross_family_displacement_hours": int(
                    values["cross_family_displacement"][post].sum()
                ),
            }
        )
    return {
        "arrays": arrays,
        "system_summary": system_summary,
        "collateral_rows": collateral_rows,
        "accounting": {
            "passed": accounting_valid,
            "debt_errors": debt_errors,
            "collateral_errors": collateral_errors,
            "reconciliation_failure_count": reconciliation_failures,
        },
        "queue_audit": {
            "ranking_owner": (
                "expected_profit_desc_debt_at_risk_desc_vault_id_asc"
            ),
            "pairwise_displacement_identifiable": pairwise_identifiable,
            "eligible_path_checksum": _payload_sha256(
                [row["eligible"] for row in queue_audit_rows]
            ),
            "profitability_filtered_path_checksum": _payload_sha256(
                [row["profitable"] for row in queue_audit_rows]
            ),
            "ranked_path_checksum": _payload_sha256(
                [row["ranked"] for row in queue_audit_rows]
            ),
            "selected_path_checksum": _payload_sha256(
                [row["selected"] for row in queue_audit_rows]
            ),
            "rejected_path_checksum": _payload_sha256(
                [row["rejected"] for row in queue_audit_rows]
            ),
            "queue_count_path_checksum": _payload_sha256(
                [
                    {
                        key: row[key]
                        for key in (
                            "step",
                            "candidate_count",
                            "profitable_count",
                            "selected_count",
                            "rejected_count",
                        )
                    }
                    for row in queue_audit_rows
                ]
            ),
        },
    }


def simulate_replication(
    replication: int,
    programme_identity: str | None = None,
    *,
    enforce_registered_core: bool = True,
) -> dict[str, Any]:
    programme = load_programme()
    resolved_programme_identity = (
        programme.programme_identity
        if programme_identity is None
        else programme_identity
    )
    if resolved_programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Experiment D programme identity changed.")
    if enforce_registered_core:
        _assert_preregistered_identities(resolved_programme_identity)
    streams = _prepare_replication_streams(replication)
    collateral_payload, portfolio_payload, _ = experiment_a._design_payloads()
    recovery_design = experiment_a.load_recovery_design()
    full_week = next(
        item
        for item in recovery_design.path_definitions
        if item.identifier == "full_week"
    )
    scaling = json.loads(
        experiment_a.SPARSE_SCALING_EVIDENCE.read_text(encoding="utf-8")
    )
    cells = {
        cell.identifier: cell for cell in build_cell_registry(programme)
    }
    cell_rows: list[dict[str, Any]] = []
    collateral_rows: list[dict[str, Any]] = []
    queue_audits: dict[str, Any] = {}
    anchor_audits: dict[str, Any] = {}

    for portfolio, shock in ANCHOR_ORDER:
        paths, gas_rows, path_audit = experiment_c.build_treatment_paths(
            streams["sampled_market"], shock
        )
        if not path_audit["path_valid"]:
            raise ValueError(f"Experiment D {portfolio}/{shock} path is invalid.")
        gas = component_gas_costs(
            sampled_market_gas_rows=gas_rows,
            simulated_eth_prices=paths["ETH"],
            config=replace(
                resolve_integrated_empirical_eth_profile().gas,
                seed=derive_seed(replication, "keeper_gas_units"),
            ),
        )
        if gas.gas_cost_usd is None or gas.sampled_rows is None:
            raise ValueError("Experiment D gas path is missing.")
        gas_unit_checksum = _payload_sha256(
            gas.sampled_rows[
                ["gas_pool_row_id", "gas_units"]
            ].to_dict(orient="records")
        )
        gas_component_checksum = _payload_sha256(
            gas.sampled_rows[
                [
                    "gas_pool_row_id",
                    "gas_units",
                    "network_gas_price_gwei",
                    "runtime_eth_price_usd",
                    "component_transaction_gas_cost_usd",
                ]
            ].to_dict(orient="records")
        )
        anchor = f"{portfolio}__{shock}"
        anchor_queue_audits: dict[int, Any] = {}
        for capacity in CAPACITY_ORDER:
            identifier = (
                f"{shock}__{portfolio}__{CAPACITY_PROFILES[capacity]}"
            )
            liquidation = _simulate_capacity_liquidations(
                initialisation=streams["states"][portfolio],
                price_paths=paths,
                gas_costs=np.asarray(gas.gas_cost_usd, dtype="<f8"),
                arrivals=streams["arrivals"],
                portfolio_config=experiment_a._portfolio_config(
                    portfolio,
                    collateral_payload,
                    portfolio_payload,
                ),
                capacity=capacity,
            )
            market = experiment_a._simulate_market_scenario(
                design=recovery_design,
                definition=full_week,
                eth_prices=paths["ETH"],
                liquidation=liquidation["arrays"],
                innovations=streams["residuals"],
                scenario_identifier="stage1_only",
                stage1_owners=streams["stage1"],
                peg_scale=float(
                    scaling["lagged_below_peg_gap"]["positive_q95"]
                ),
                eth_scale=float(
                    scaling["lagged_24h_eth_downside"]["positive_q95"]
                ),
                initial_vault_count=VAULT_COUNT,
            )
            system = {
                **liquidation["system_summary"],
                **{
                    key: market["summary"][key]
                    for key in PEG_METRICS
                },
                "cell_order": cells[identifier].order,
                "cell_identifier": identifier,
                "anchor": anchor,
                "portfolio": portfolio,
                "shock": shock,
                "capacity_profile": CAPACITY_PROFILES[capacity],
                "capacity": capacity,
                "replication": replication,
                "hurdle": "direct_cost_only",
                "risk_cost_rate": 0.0,
                "confidence": "stage1_only",
                "oracle_delay": 0,
                "paired_stream_checksum": streams[
                    "paired_stream_checksum"
                ],
                "state_checksum": streams["states"][portfolio].identity,
                "gas_unit_draw_checksum": gas_unit_checksum,
                "gas_component_checksum": gas_component_checksum,
                "price_path_checksum": _payload_sha256(
                    path_audit["full_price_checksums"]
                ),
                "path_valid": path_audit["path_valid"],
                "nested_initialisation_valid": streams[
                    "nested_audit"
                ]["passed"],
            }
            system["numerical_valid"] = bool(
                system["numerical_valid"]
                and market["summary"]["numerical_valid"]
                and system["path_valid"]
            )
            cell_rows.append(system)
            for family_row in liquidation["collateral_rows"]:
                collateral_rows.append(
                    {
                        "cell_order": cells[identifier].order,
                        "cell_identifier": identifier,
                        "anchor": anchor,
                        "portfolio": portfolio,
                        "shock": shock,
                        "capacity_profile": CAPACITY_PROFILES[capacity],
                        "capacity": capacity,
                        "replication": replication,
                        "numerical_valid": system["numerical_valid"],
                        "accounting_valid": system["accounting_valid"],
                        "path_valid": system["path_valid"],
                        **family_row,
                    }
                )
            anchor_queue_audits[capacity] = liquidation["queue_audit"]
            queue_audits[identifier] = liquidation["queue_audit"]
        owner_payload = {
            "state_checksum": streams["states"][portfolio].identity,
            "price_path_checksum": _payload_sha256(
                path_audit["full_price_checksums"]
            ),
            "gas_component_checksum": gas_component_checksum,
            "arrival_checksum": streams["arrivals"]["checksum"],
            "ranking_owner": (
                "expected_profit_desc_debt_at_risk_desc_vault_id_asc"
            ),
        }
        anchor_audits[anchor] = {
            "common_random_numbers_valid": True,
            "capacity_neutral_owner_checksum": _payload_sha256(owner_payload),
            "capacity_neutral_owner_checksums": {
                str(capacity): _payload_sha256(owner_payload)
                for capacity in CAPACITY_ORDER
            },
            "ranking_owner_invariant": len(
                {
                    audit["ranking_owner"]
                    for audit in anchor_queue_audits.values()
                }
            )
            == 1,
            "dynamic_queue_paths": {
                str(capacity): anchor_queue_audits[capacity][
                    "ranked_path_checksum"
                ]
                for capacity in CAPACITY_ORDER
            },
            "dynamic_queue_difference_interpretation": (
                "post_binding_state_mediation_is_an_outcome_not_a_crn_failure"
            ),
            "pairwise_displacement_identifiable": False,
        }

    if [row["cell_identifier"] for row in cell_rows] != list(CELL_ORDER):
        raise ValueError("Experiment D cell order differs.")
    expected_collateral = [
        (cell, family) for cell in CELL_ORDER for family in FAMILY_ORDER
    ]
    if [
        (row["cell_identifier"], row["family"])
        for row in collateral_rows
    ] != expected_collateral:
        raise ValueError("Experiment D collateral order differs.")
    result = {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "programme_identity": resolved_programme_identity,
        "experiment_identity": experiment_identity(
            resolved_programme_identity
        ),
        "replication": replication,
        "scientific_code_identity": scientific_code_identity(),
        "simulation_core_identity": simulation_core_identity(),
        "profile_identity": PROFILE_IDENTITY,
        "seed_registry_sha256": seed_registry_checksum(),
        "seed_ownership": streams["seed_ownership"],
        "paired_stream_checksum": streams["paired_stream_checksum"],
        "stream_components": streams["stream_components"],
        "nested_initialisation_audit": streams["nested_audit"],
        "anchor_audits": anchor_audits,
        "queue_audits": queue_audits,
        "cell_rows": cell_rows,
        "collateral_rows": collateral_rows,
        "simulation_count": len(cell_rows),
    }
    result["result_checksum"] = _payload_sha256(
        {
            key: value
            for key, value in result.items()
            if key not in {"schema_version", "experiment_id"}
        }
    )
    return result


def simulation_core_identity() -> str:
    functions = (
        derive_seed,
        initialisation_replication_key,
        seed_record,
        seed_registry_checksum,
        _draw_d_states,
        _arrival_stream,
        _prepare_replication_streams,
        _demand_decision,
        _queue_records,
        _simulate_capacity_liquidations,
        simulate_replication,
        experiment_c.build_treatment_paths,
        experiment_a._normalise_nested_portfolio,
        experiment_a._simulate_market_scenario,
        rank_liquidation_candidates,
        execute_keeper_liquidation,
        component_gas_costs,
    )
    return _payload_sha256(
        [
            {
                "module": function.__module__,
                "qualname": function.__qualname__,
                "source": inspect.getsource(function),
            }
            for function in functions
        ]
    )


def scientific_code_identity() -> str:
    return _payload_sha256(
        {
            "simulation_core_identity": simulation_core_identity(),
            "programme_identity": MASTER_PROGRAMME_IDENTITY,
            "cell_order": CELL_ORDER,
            "replications": REPLICATIONS,
            "primary_completion_metrics": PRIMARY_COMPLETION_METRICS,
            "metric_directions": METRIC_DIRECTIONS,
            "materiality_thresholds": MATERIALITY_THRESHOLDS,
            "ranking": (
                "expected_profit_desc",
                "debt_at_risk_desc",
                "vault_id_asc",
            ),
        }
    )


def _decision_rules() -> dict[str, Any]:
    return {
        "monotonicity": {
            "monotonic_relief": (
                "Both adjacent relief estimates are non-negative, the "
                "low-to-high interval excludes zero beneficially, and neither "
                "adjacent interval is clearly adverse."
            ),
            "threshold_relief": (
                "Low-to-high relief is clear, one adjacent interval crosses "
                "zero, and neither adjacent interval is clearly adverse."
            ),
            "non_monotonic_relief": (
                "Low-to-high relief is beneficial but one adjacent interval "
                "is clearly adverse."
            ),
            "no_capacity_effect": (
                "The low-to-high interval includes zero without a systematic "
                "adjacent pattern."
            ),
            "capacity_effect_adverse": (
                "The low-to-high interval is clearly adverse."
            ),
            "not_operational": "The metric is unavailable or degenerate.",
            "invalid": "A registered validity gate fails.",
        },
        "anchor_relief": {
            "required_clear_primary_metrics": 2,
            "required_monotonic_or_threshold_metrics": 2,
            "adverse_primary_metrics_permitted": 0,
            "rejections_must_not_increase_with_capacity": True,
        },
        "D1": (
            "supported",
            "partially_supported",
            "not_supported",
            "not_operational",
            "invalid",
        ),
        "D2": (
            "shared_capacity_transmission_present",
            "shared_capacity_transmission_mixed",
            "shared_capacity_transmission_not_present",
            "shared_capacity_not_binding",
            "shared_capacity_transmission_invalid",
        ),
        "D3": (
            "peg_friction_effect_present",
            "peg_friction_effect_partial",
            "peg_unchanged",
            "peg_response_mixed",
            "peg_not_operational",
            "peg_response_invalid",
        ),
        "overall_h1": (
            "H1_shared_capacity_supported",
            "H1_shared_capacity_partially_supported",
            "H1_shared_capacity_backlog_effect_only",
            "H1_no_clear_shared_capacity_effect",
            "H1_shared_capacity_not_operational",
            "H1_shared_capacity_experiment_invalid",
        ),
        "peg_solvency": (
            "solvency_and_peg_improve_with_capacity",
            "solvency_improves_peg_unchanged",
            "peg_improves_solvency_unchanged",
            "solvency_and_peg_diverge",
            "neither_materially_changes",
            "relationship_mixed",
            "relationship_invalid",
        ),
    }


def specification_payload(programme_identity: str) -> dict[str, Any]:
    if programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Experiment D programme identity changed.")
    return {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "experiment_d_parent_commit": EXPERIMENT_D_PARENT_COMMIT,
        "programme_identity": programme_identity,
        "scientific_code_identity": scientific_code_identity(),
        "simulation_core_identity": simulation_core_identity(),
        "profile": {
            "identifier": "empirical_integrated_multicollateral",
            "identity": PROFILE_IDENTITY,
            "sha256": PROFILE_SHA256,
            "vault_count": VAULT_COUNT,
            "total_debt_dai": TOTAL_DEBT_DAI,
            "target_system_collateral_ratio": (
                TARGET_SYSTEM_COLLATERAL_RATIO
            ),
            "runtime_adopted": False,
        },
        "registry_checksums": {
            "collateral": COLLATERAL_REGISTRY_SHA256,
            "portfolio": PORTFOLIO_REGISTRY_SHA256,
            "shock": SHOCK_REGISTRY_SHA256,
            "keeper": KEEPER_REGISTRY_SHA256,
            "confidence": CONFIDENCE_REGISTRY_SHA256,
        },
        "research_questions": ("RQ2", "RQ4"),
        "hypotheses": ("H1", "H3"),
        "primary_role": "RQ2_H1",
        "secondary_role": "RQ4_H3",
        "anchors": [
            {"portfolio": portfolio, "shock": shock}
            for portfolio, shock in ANCHOR_ORDER
        ],
        "capacities": [
            {
                "profile": CAPACITY_PROFILES[capacity],
                "value": capacity,
                "units": "liquidation_opportunities_per_hour",
                "identification": "partial",
            }
            for capacity in CAPACITY_ORDER
        ],
        "cells": [asdict(cell) for cell in build_cell_registry()],
        "cell_order": CELL_ORDER,
        "family_order": FAMILY_ORDER,
        "replications": REPLICATIONS,
        "substantive_simulations": len(CELL_ORDER) * REPLICATIONS,
        "seed_namespace": EXPERIMENT_NAMESPACE,
        "seed_registry_sha256": seed_registry_checksum(),
        "seed_streams": SEED_STREAMS,
        "horizon": {
            "pre_shock_hours": PRE_SHOCK_HOURS,
            "post_shock_hours": POST_SHOCK_HOURS,
            "total_hours": TOTAL_HOURS,
            "recovery_window_hours": 24,
            "recovery_band": (0.995, 1.005),
            "rmst_cap_hours": 720,
        },
        "common_settings": {
            "hurdle": "direct_cost_only",
            "risk_cost_rate": 0.0,
            "confidence": "stage1_only",
            "oracle_delay": 0,
            "max_close_factor": 1.0,
        },
        "stage1_owners": {
            "below_peg_response": EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
            "above_peg_response": EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
            "residual_sequence_sha256": (
                EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256
            ),
            "residual_block_sha256": EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
        },
        "queue_owner": {
            "scope": "one_global_system_queue",
            "ranking": (
                "expected_profit_desc",
                "debt_at_risk_desc",
                "vault_id_asc",
            ),
            "collateral_quotas": False,
            "random_tie_breaking": False,
            "pairwise_displacement_identifiable": False,
            "dynamic_queue_note": (
                "post-binding queue differences are treatment-mediated state "
                "outcomes; capacity-neutral inputs and ranking are paired"
            ),
        },
        "primary_completion_metrics": PRIMARY_COMPLETION_METRICS,
        "secondary_execution_metrics": SECONDARY_EXECUTION_METRICS,
        "bad_debt_metrics": BAD_DEBT_METRICS,
        "peg_metrics": PEG_METRICS,
        "collateral_metrics": COLLATERAL_METRICS,
        "metric_directions": METRIC_DIRECTIONS,
        "raw_contrasts": (
            "capacity_14_minus_26",
            "capacity_26_minus_45",
            "capacity_14_minus_45",
        ),
        "direction_normalised_relief": True,
        "materiality_thresholds": MATERIALITY_THRESHOLDS,
        "operationality_classes": (
            "operational",
            "degenerate",
            "not_operational",
            "invalid",
        ),
        "decision_rules": _decision_rules(),
        "capacity_selection_permitted": False,
        "final_validation_data_used": False,
        "held_out_data_used": False,
        "usdc_svb_used": False,
        "experiment_e_executed": False,
        "runtime_adopted": False,
    }


def experiment_identity(programme_identity: str) -> str:
    payload = specification_payload(programme_identity)
    return _payload_sha256(
        {
            key: value
            for key, value in payload.items()
            if key not in {"schema_version", "experiment_id"}
        }
    )


def _registered_specification() -> dict[str, Any] | None:
    path = EVIDENCE_DIR / COMPACT_FILENAMES[0]
    return (
        None
        if not path.is_file()
        else json.loads(path.read_text(encoding="utf-8"))
    )


def _assert_preregistered_identities(programme_identity: str) -> None:
    payload = _registered_specification()
    if payload is None:
        raise ValueError("Experiment D must be pre-registered before execution.")
    if (
        payload.get("programme_identity") != programme_identity
        or payload.get("scientific_code_identity")
        != scientific_code_identity()
        or payload.get("simulation_core_identity")
        != simulation_core_identity()
        or payload.get("experiment_identity")
        != experiment_identity(programme_identity)
    ):
        raise ValueError("Experiment D pre-registered identity changed.")


def write_preregistration(programme_identity: str) -> dict[str, Any]:
    payload = specification_payload(programme_identity)
    identity = experiment_identity(programme_identity)
    specification_bytes = _pretty_json(
        {**payload, "experiment_identity": identity}
    )
    registry_bytes = _csv_bytes(_registry_frame())
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    outputs = (
        (EVIDENCE_DIR / COMPACT_FILENAMES[0], specification_bytes),
        (EVIDENCE_DIR / COMPACT_FILENAMES[1], registry_bytes),
    )
    for path, content in outputs:
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f"Experiment D pre-registration differs: {path.name}.")
        _atomic_bytes(path, content)
    return {
        "experiment_identity": identity,
        "scientific_code_identity": scientific_code_identity(),
        "simulation_core_identity": simulation_core_identity(),
        "specification_sha256": sha256_file(outputs[0][0]),
        "registry_sha256": sha256_file(outputs[1][0]),
        "seed_registry_sha256": seed_registry_checksum(),
    }


def _tree_snapshot(path: Path, pattern: str = "*") -> dict[str, Any]:
    rows = [
        {
            "path": item.relative_to(path).as_posix(),
            "size": item.stat().st_size,
            "sha256": sha256_file(item),
        }
        for item in sorted(path.rglob(pattern))
        if item.is_file()
    ]
    return {
        "file_count": len(rows),
        "total_bytes": sum(row["size"] for row in rows),
        "content_map_sha256": _payload_sha256(rows),
    }


def regression_audit() -> dict[str, Any]:
    snapshots = {
        "a_evidence": experiment_c._tree_snapshot(
            experiment_a.EVIDENCE_DIR
        ),
        "b_evidence": experiment_c._tree_snapshot(
            experiment_b.EVIDENCE_DIR
        ),
        "c_evidence": experiment_c._tree_snapshot(
            experiment_c.EVIDENCE_DIR
        ),
        "a_checkpoints": experiment_c._tree_snapshot(
            experiment_a.OUTPUT_ROOT,
            "replication_*.json",
        ),
        "b_checkpoints": experiment_c._tree_snapshot(
            experiment_b.OUTPUT_ROOT,
            "replication_*.json",
        ),
        "c_checkpoints": experiment_c._tree_snapshot(
            experiment_c.OUTPUT_ROOT,
            "replication_*.json",
        ),
    }
    expected = {
        "a_evidence": (8, EXPERIMENT_A_EVIDENCE_SHA256),
        "b_evidence": (8, EXPERIMENT_B_EVIDENCE_SHA256),
        "c_evidence": (8, EXPERIMENT_C_EVIDENCE_SHA256),
        "a_checkpoints": (128, EXPERIMENT_A_CHECKPOINT_SHA256),
        "b_checkpoints": (128, EXPERIMENT_B_CHECKPOINT_SHA256),
        "c_checkpoints": (128, EXPERIMENT_C_CHECKPOINT_SHA256),
    }
    for key, (count, checksum) in expected.items():
        if (
            snapshots[key]["file_count"] != count
            or snapshots[key]["content_map_sha256"] != checksum
        ):
            raise ValueError(f"Protected {key} changed before Experiment D.")
    return {"passed": True, **snapshots}


def _output_dir(programme_identity: str) -> Path:
    return OUTPUT_ROOT / experiment_identity(programme_identity)


def _checkpoint_path(output_dir: Path, replication: int) -> Path:
    return output_dir / "checkpoints" / f"replication_{replication:03d}.json"


def _valid_checkpoint(
    path: Path,
    *,
    replication: int,
    programme_identity: str,
) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if (
        payload.get("replication") != replication
        or payload.get("programme_identity") != programme_identity
        or payload.get("experiment_identity")
        != experiment_identity(programme_identity)
        or payload.get("scientific_code_identity")
        != scientific_code_identity()
        or payload.get("simulation_count") != len(CELL_ORDER)
        or [
            row.get("cell_identifier")
            for row in payload.get("cell_rows", [])
        ]
        != list(CELL_ORDER)
        or len(payload.get("collateral_rows", []))
        != len(CELL_ORDER) * len(FAMILY_ORDER)
    ):
        return False
    expected = _payload_sha256(
        {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "schema_version",
                "experiment_id",
                "result_checksum",
                "worker_elapsed_seconds",
            }
        }
    )
    return payload.get("result_checksum") == expected


def audit_checkpoints(programme_identity: str) -> dict[str, Any]:
    output_dir = _output_dir(programme_identity)
    checkpoint_dir = output_dir / "checkpoints"
    valid: list[int] = []
    invalid: list[int] = []
    for replication in range(REPLICATIONS):
        path = _checkpoint_path(output_dir, replication)
        if _valid_checkpoint(
            path,
            replication=replication,
            programme_identity=programme_identity,
        ):
            valid.append(replication)
        elif path.exists():
            invalid.append(replication)
    expected_names = {
        f"replication_{replication:03d}.json"
        for replication in range(REPLICATIONS)
    }
    orphans = sorted(
        path.name
        for path in checkpoint_dir.glob("replication_*.json")
        if path.name not in expected_names
    )
    rows = [
        {
            "replication": replication,
            "size": _checkpoint_path(output_dir, replication).stat().st_size,
            "sha256": sha256_file(
                _checkpoint_path(output_dir, replication)
            ),
        }
        for replication in valid
    ]
    return {
        "valid_count": len(valid),
        "valid_replications": valid,
        "invalid_count": len(invalid),
        "invalid_replications": invalid,
        "missing_count": REPLICATIONS - len(valid) - len(invalid),
        "duplicate_count": 0,
        "orphan_count": len(orphans),
        "orphans": orphans,
        "checkpoint_bytes": sum(row["size"] for row in rows),
        "checkpoint_content_map_sha256": _payload_sha256(rows),
        "complete": (
            len(valid) == REPLICATIONS and not invalid and not orphans
        ),
    }


def _ranking_preflight() -> dict[str, Any]:
    from dai_sim.model.vault import Vault

    vaults = [
        Vault(
            vault_id=3,
            owner_id=3,
            collateral_amount=0.5,
            debt_dai=1000.0,
            liquidation_ratio=1.5,
            collateral_type="ETH",
        ),
        Vault(
            vault_id=2,
            owner_id=2,
            collateral_amount=0.5,
            debt_dai=1000.0,
            liquidation_ratio=1.5,
            collateral_type="ETH",
        ),
        Vault(
            vault_id=1,
            owner_id=1,
            collateral_amount=1.0,
            debt_dai=2000.0,
            liquidation_ratio=1.5,
            collateral_type="ETH",
        ),
    ]
    base = resolve_integrated_empirical_eth_profile().bundle.base_bundle
    ranked_by_capacity: dict[int, list[int]] = {}
    for capacity in CAPACITY_ORDER:
        config = replace(
            base.liquidation_config,
            gas_cost=0.0,
            risk_cost_rate=0.0,
            max_close_factor=1.0,
            max_liquidations_per_step=capacity,
        )
        ranked = rank_liquidation_candidates(
            vaults,
            prices={"ETH": 1000.0, "BTC": 30_000.0, "STABLE": 1.0},
            config=config,
        )
        ranked_by_capacity[capacity] = (
            ranked["vault_id"].astype(int).tolist()
        )
    if len({tuple(value) for value in ranked_by_capacity.values()}) != 1:
        raise ValueError("Capacity changed the pre-truncation ranking.")
    if ranked_by_capacity[14] != [1, 2, 3]:
        raise ValueError("Frozen ranking tie-break order changed.")
    return {
        "passed": True,
        "ranked_vault_ids": ranked_by_capacity[14],
        "capacity_neutral": True,
        "collateral_quota": False,
        "random_tie_break": False,
    }


def preflight(programme_identity: str) -> dict[str, Any]:
    _assert_preregistered_identities(programme_identity)
    profile_path = (
        REPOSITORY_ROOT
        / "config/profiles/empirical_integrated_multicollateral.yaml"
    )
    if sha256_file(profile_path) != PROFILE_SHA256:
        raise ValueError("Frozen integrated profile changed.")
    registry = build_cell_registry()
    if len(registry) != 9:
        raise ValueError("Experiment D must contain nine cells.")
    streams = _prepare_replication_streams(0)
    path_audits: dict[str, Any] = {}
    for _, shock in ANCHOR_ORDER:
        if shock in path_audits:
            continue
        _, _, audit = experiment_c.build_treatment_paths(
            streams["sampled_market"], shock
        )
        if not audit["path_valid"]:
            raise ValueError(f"Experiment D {shock} path is invalid.")
        path_audits[shock] = audit
    free_bytes = shutil.disk_usage(REPOSITORY_ROOT).free
    if free_bytes < MINIMUM_FREE_BYTES:
        raise ValueError("Less than 10 GiB free before Experiment D.")
    return {
        "passed": True,
        "programme_identity": programme_identity,
        "experiment_identity": experiment_identity(programme_identity),
        "scientific_code_identity": scientific_code_identity(),
        "simulation_core_identity": simulation_core_identity(),
        "cell_count": len(registry),
        "replications": REPLICATIONS,
        "substantive_simulations": len(registry) * REPLICATIONS,
        "nested_initialisation": streams["nested_audit"],
        "path_audits": path_audits,
        "ranking_audit": _ranking_preflight(),
        "regression_audit": regression_audit(),
        "free_bytes": free_bytes,
        "output_cap_bytes": MAXIMUM_OUTPUT_BYTES,
        "experiments_a_b_c_simulations": 0,
        "experiment_e_simulations": 0,
        "held_out_data_used": False,
        "capacity_selection_permitted": False,
        "runtime_adopted": False,
    }


def run_smoke(replication: int = 0) -> dict[str, Any]:
    result = simulate_replication(
        replication,
        MASTER_PROGRAMME_IDENTITY,
        enforce_registered_core=True,
    )
    common_streams = {
        row["anchor"]: row["paired_stream_checksum"]
        for row in result["cell_rows"]
    }
    if len(common_streams) != len(ANCHOR_ORDER):
        raise ValueError("Experiment D smoke anchor pairing failed.")
    if not all(
        audit["common_random_numbers_valid"]
        and audit["ranking_owner_invariant"]
        for audit in result["anchor_audits"].values()
    ):
        raise ValueError("Experiment D smoke CRN audit failed.")
    numerical_valid = all(
        row["numerical_valid"] for row in result["cell_rows"]
    )
    accounting_valid = all(
        row["accounting_valid"] for row in result["cell_rows"]
    )
    if not numerical_valid:
        raise ValueError("Experiment D smoke numerical audit failed.")
    if not accounting_valid:
        raise ValueError("Experiment D smoke accounting audit failed.")
    return {
        "passed": True,
        "replication": replication,
        "simulation_count": result["simulation_count"],
        "capacities": sorted(
            {row["capacity"] for row in result["cell_rows"]}
        ),
        "all_numerical_valid": numerical_valid,
        "all_accounting_valid": accounting_valid,
        "crn_valid": True,
        "ranking_valid": True,
        "hurdle": "direct_cost_only",
        "confidence": "stage1_only",
        "oracle_delay": 0,
    }


def _worker_initialiser() -> None:
    multiprocessing.current_process().daemon = False


def _run_one(replication: int, programme_identity: str) -> dict[str, Any]:
    started = time.perf_counter()
    result = simulate_replication(replication, programme_identity)
    result["worker_elapsed_seconds"] = time.perf_counter() - started
    return result


def run_matrix(
    programme_identity: str,
    *,
    workers: int = 4,
    resume: bool = True,
    max_replications: int | None = None,
) -> dict[str, Any]:
    _assert_preregistered_identities(programme_identity)
    if workers <= 0:
        raise ValueError("Worker count must be positive.")
    output_dir = _output_dir(programme_identity)
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    target = list(range(REPLICATIONS))
    if max_replications is not None:
        target = target[:max_replications]
    reused: list[int] = []
    pending: list[int] = []
    for replication in target:
        path = _checkpoint_path(output_dir, replication)
        if resume and _valid_checkpoint(
            path,
            replication=replication,
            programme_identity=programme_identity,
        ):
            reused.append(replication)
        else:
            pending.append(replication)
    started = time.perf_counter()
    completed: list[int] = []
    failures: list[dict[str, Any]] = []
    if pending:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_worker_initialiser,
        ) as executor:
            futures = {
                executor.submit(_run_one, replication, programme_identity): (
                    replication
                )
                for replication in pending
            }
            for future in as_completed(futures):
                replication = futures[future]
                try:
                    result = future.result()
                    path = _checkpoint_path(output_dir, replication)
                    _atomic_json(path, result)
                    if not _valid_checkpoint(
                        path,
                        replication=replication,
                        programme_identity=programme_identity,
                    ):
                        raise ValueError(
                            "Persisted Experiment D checkpoint did not validate."
                        )
                    completed.append(replication)
                except Exception as exc:
                    failures.append(
                        {
                            "replication": replication,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
    elapsed = time.perf_counter() - started
    if failures:
        _atomic_json(
            output_dir / "execution_failure.json",
            {
                "experiment_identity": experiment_identity(
                    programme_identity
                ),
                "failures": failures,
            },
        )
        raise RuntimeError(f"Experiment D worker failure: {failures[0]}.")
    audit = audit_checkpoints(programme_identity)
    execution = {
        "command_role": "substantive_matrix",
        "workers": workers,
        "requested_replications": len(target),
        "completed_replications": len(completed),
        "reused_replications": len(reused),
        "resumed_replications": len(reused),
        "failed_replications": 0,
        "rerun_replications": 0,
        "completed_simulations": len(completed) * len(CELL_ORDER),
        "reused_simulations": len(reused) * len(CELL_ORDER),
        "elapsed_seconds": elapsed,
        "throughput_simulations_per_second": (
            0.0
            if elapsed == 0.0
            else len(completed) * len(CELL_ORDER) / elapsed
        ),
        "checkpoint_audit": audit,
        "complete": audit["complete"],
    }
    _atomic_json(output_dir / "execution.json", execution)
    if audit["checkpoint_bytes"] > MAXIMUM_OUTPUT_BYTES:
        raise ValueError("Experiment D output exceeded 750 MB.")
    return execution


def load_results(programme_identity: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    audit = audit_checkpoints(programme_identity)
    if not audit["complete"]:
        raise ValueError("Experiment D checkpoints are incomplete.")
    cells: list[dict[str, Any]] = []
    collateral: list[dict[str, Any]] = []
    for replication in range(REPLICATIONS):
        payload = json.loads(
            _checkpoint_path(
                _output_dir(programme_identity), replication
            ).read_text(encoding="utf-8")
        )
        cells.extend(payload["cell_rows"])
        collateral.extend(payload["collateral_rows"])
    cell_frame = pd.DataFrame(cells).sort_values(
        ["cell_order", "replication"], kind="mergesort"
    ).reset_index(drop=True)
    family_order = {family: index for index, family in enumerate(FAMILY_ORDER)}
    collateral_frame = pd.DataFrame(collateral)
    collateral_frame["_family_order"] = collateral_frame["family"].map(
        family_order
    )
    collateral_frame = collateral_frame.sort_values(
        ["cell_order", "_family_order", "replication"], kind="mergesort"
    ).drop(columns="_family_order").reset_index(drop=True)
    if len(cell_frame) != len(CELL_ORDER) * REPLICATIONS:
        raise ValueError("Experiment D cell-result dimensions differ.")
    if len(collateral_frame) != (
        len(CELL_ORDER) * len(FAMILY_ORDER) * REPLICATIONS
    ):
        raise ValueError("Experiment D collateral dimensions differ.")
    return cell_frame, collateral_frame


def _distribution(values: Iterable[float]) -> dict[str, float]:
    raw = np.asarray(list(values), dtype=float)
    finite = raw[np.isfinite(raw)]
    if finite.size == 0:
        return {field: math.nan for field in DISTRIBUTION_FIELDS}
    standard_error = (
        0.0
        if finite.size < 2
        else float(np.std(finite, ddof=1) / math.sqrt(finite.size))
    )
    return {
        "mean": float(np.mean(finite)),
        "standard_error": standard_error,
        "ci95_lower": float(np.mean(finite) - 1.96 * standard_error),
        "ci95_upper": float(np.mean(finite) + 1.96 * standard_error),
        "median": float(np.median(finite)),
        "p05": float(np.quantile(finite, 0.05)),
        "p25": float(np.quantile(finite, 0.25)),
        "p75": float(np.quantile(finite, 0.75)),
        "p90": float(np.quantile(finite, 0.90)),
        "p95": float(np.quantile(finite, 0.95)),
        "positive_share": float(np.mean(finite > 0.0)),
    }


def classify_metric_operationality(
    values: Iterable[float | None],
    *,
    valid: bool = True,
) -> str:
    if not valid:
        return "invalid"
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce")
    finite = series[np.isfinite(series)]
    if finite.empty:
        return "not_operational"
    if float(finite.max() - finite.min()) <= MATERIALITY_THRESHOLDS[
        "numerical_tolerance"
    ]:
        return "degenerate"
    return "operational"


def metric_operationality(frame: pd.DataFrame) -> dict[str, str]:
    valid = bool(
        frame["numerical_valid"].astype(bool).all()
        and frame["accounting_valid"].astype(bool).all()
        and frame["path_valid"].astype(bool).all()
    )
    return {
        metric: classify_metric_operationality(frame[metric], valid=valid)
        for metric in SYSTEM_METRICS
    }


def cell_summary(frame: pd.DataFrame) -> pd.DataFrame:
    operationality = metric_operationality(frame)
    rows: list[dict[str, Any]] = []
    for cell in build_cell_registry():
        selected = frame.loc[frame["cell_identifier"].eq(cell.identifier)]
        for metric_order, metric in enumerate(SYSTEM_METRICS, start=1):
            values = pd.to_numeric(selected[metric], errors="coerce")
            finite = values[np.isfinite(values)]
            rows.append(
                {
                    "cell_order": cell.order,
                    "cell_identifier": cell.identifier,
                    "anchor": (
                        f"{cell.portfolio}__{cell.shock}"
                    ),
                    "portfolio": cell.portfolio,
                    "shock": cell.shock,
                    "capacity": cell.capacity,
                    "metric_order": metric_order,
                    "metric": metric,
                    "operationality": operationality[metric],
                    "direction_multiplier": METRIC_DIRECTIONS[metric],
                    "count": int(len(finite)),
                    **_distribution(finite),
                }
            )
    return pd.DataFrame(rows)


def collateral_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for cell in build_cell_registry():
        cell_rows = frame.loc[frame["cell_identifier"].eq(cell.identifier)]
        for family_order, family in enumerate(FAMILY_ORDER, start=1):
            selected = cell_rows.loc[cell_rows["family"].eq(family)]
            for metric_order, metric in enumerate(
                COLLATERAL_METRICS, start=1
            ):
                values = pd.to_numeric(selected[metric], errors="coerce")
                finite = values[np.isfinite(values)]
                rows.append(
                    {
                        "cell_order": cell.order,
                        "cell_identifier": cell.identifier,
                        "anchor": f"{cell.portfolio}__{cell.shock}",
                        "portfolio": cell.portfolio,
                        "shock": cell.shock,
                        "capacity": cell.capacity,
                        "family_order": family_order,
                        "family": family,
                        "metric_order": metric_order,
                        "metric": metric,
                        "count": int(len(finite)),
                        **_distribution(finite),
                    }
                )
    return pd.DataFrame(rows)


def _paired_values(
    frame: pd.DataFrame,
    *,
    anchor: str,
    metric: str,
    left_capacity: int,
    right_capacity: int,
    family: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    selected = frame.loc[frame["anchor"].eq(anchor)]
    if family is not None:
        selected = selected.loc[selected["family"].eq(family)]
    left = selected.loc[
        selected["capacity"].eq(left_capacity),
        ["replication", metric],
    ].rename(columns={metric: "left"})
    right = selected.loc[
        selected["capacity"].eq(right_capacity),
        ["replication", metric],
    ].rename(columns={metric: "right"})
    paired = left.merge(
        right, on="replication", how="inner", validate="one_to_one"
    ).sort_values("replication", kind="mergesort")
    left_values = pd.to_numeric(paired["left"], errors="coerce").to_numpy()
    right_values = pd.to_numeric(paired["right"], errors="coerce").to_numpy()
    finite = np.isfinite(left_values) & np.isfinite(right_values)
    return left_values[finite], right_values[finite]


def _contrast_record(
    *,
    contrast_order: int,
    contrast_type: str,
    anchor: str,
    family: str | None,
    metric: str,
    left_capacity: int,
    right_capacity: int,
    direction_multiplier: int,
    values: np.ndarray,
    operationality: str,
) -> dict[str, Any]:
    distribution = _distribution(values)
    return {
        "contrast_order": contrast_order,
        "contrast_type": contrast_type,
        "anchor": anchor,
        "family": family,
        "metric": metric,
        "left_capacity": left_capacity,
        "right_capacity": right_capacity,
        "contrast_label": f"capacity_{left_capacity}_minus_{right_capacity}",
        "direction_multiplier": direction_multiplier,
        "operationality": operationality,
        "count": int(len(values)),
        **distribution,
        "discordant_positive": int(np.count_nonzero(values > 0.0)),
        "discordant_negative": int(np.count_nonzero(values < 0.0)),
    }


def classify_monotonicity(
    low_central: Mapping[str, Any],
    central_high: Mapping[str, Any],
    low_high: Mapping[str, Any],
    *,
    operationality: str,
    valid: bool = True,
) -> str:
    if not valid or operationality == "invalid":
        return "invalid"
    if operationality != "operational":
        return "not_operational"
    if float(low_high["ci95_upper"]) < 0.0:
        return "capacity_effect_adverse"
    low_high_clear = float(low_high["ci95_lower"]) > 0.0
    adjacent_adverse = (
        float(low_central["ci95_upper"]) < 0.0
        or float(central_high["ci95_upper"]) < 0.0
    )
    if low_high_clear and adjacent_adverse:
        return "non_monotonic_relief"
    adjacent_nonnegative = (
        float(low_central["mean"]) >= 0.0
        and float(central_high["mean"]) >= 0.0
    )
    adjacent_crosses = (
        float(low_central["ci95_lower"]) <= 0.0
        <= float(low_central["ci95_upper"])
        or float(central_high["ci95_lower"]) <= 0.0
        <= float(central_high["ci95_upper"])
    )
    if low_high_clear and adjacent_nonnegative and not adjacent_crosses:
        return "monotonic_relief"
    if low_high_clear and not adjacent_adverse:
        return "threshold_relief"
    return "no_capacity_effect"


def paired_contrasts(
    system: pd.DataFrame,
    collateral: pd.DataFrame,
) -> pd.DataFrame:
    operationality = metric_operationality(system)
    rows: list[dict[str, Any]] = []
    order = 0
    pairs = ((14, 26), (26, 45), (14, 45))
    for portfolio, shock in ANCHOR_ORDER:
        anchor = f"{portfolio}__{shock}"
        for metric in SYSTEM_METRICS:
            direction = METRIC_DIRECTIONS[metric]
            raw_records: dict[tuple[int, int], dict[str, Any]] = {}
            relief_records: dict[tuple[int, int], dict[str, Any]] = {}
            for left_capacity, right_capacity in pairs:
                left, right = _paired_values(
                    system,
                    anchor=anchor,
                    metric=metric,
                    left_capacity=left_capacity,
                    right_capacity=right_capacity,
                )
                raw = left - right
                relief = raw * direction
                order += 1
                raw_record = _contrast_record(
                    contrast_order=order,
                    contrast_type="raw_capacity_contrast",
                    anchor=anchor,
                    family=None,
                    metric=metric,
                    left_capacity=left_capacity,
                    right_capacity=right_capacity,
                    direction_multiplier=1,
                    values=raw,
                    operationality=operationality[metric],
                )
                rows.append(raw_record)
                raw_records[(left_capacity, right_capacity)] = raw_record
                order += 1
                relief_record = _contrast_record(
                    contrast_order=order,
                    contrast_type="direction_normalised_capacity_relief",
                    anchor=anchor,
                    family=None,
                    metric=metric,
                    left_capacity=left_capacity,
                    right_capacity=right_capacity,
                    direction_multiplier=direction,
                    values=relief,
                    operationality=operationality[metric],
                )
                rows.append(relief_record)
                relief_records[(left_capacity, right_capacity)] = relief_record
            classification = classify_monotonicity(
                relief_records[(14, 26)],
                relief_records[(26, 45)],
                relief_records[(14, 45)],
                operationality=operationality[metric],
            )
            order += 1
            rows.append(
                {
                    **relief_records[(14, 45)],
                    "contrast_order": order,
                    "contrast_type": "monotonicity_classification",
                    "classification": classification,
                }
            )
        for family in FAMILY_ORDER:
            for metric in COLLATERAL_METRICS:
                for left_capacity, right_capacity in pairs:
                    left, right = _paired_values(
                        collateral,
                        anchor=anchor,
                        family=family,
                        metric=metric,
                        left_capacity=left_capacity,
                        right_capacity=right_capacity,
                    )
                    order += 1
                    rows.append(
                        _contrast_record(
                            contrast_order=order,
                            contrast_type="collateral_capacity_contrast",
                            anchor=anchor,
                            family=family,
                            metric=metric,
                            left_capacity=left_capacity,
                            right_capacity=right_capacity,
                            direction_multiplier=1,
                            values=left - right,
                            operationality=(
                                "not_operational"
                                if len(left) == 0
                                else "operational"
                            ),
                        )
                    )
    return pd.DataFrame(rows).sort_values(
        "contrast_order", kind="mergesort"
    ).reset_index(drop=True)


def _contrast_lookup(
    contrasts: pd.DataFrame,
    *,
    contrast_type: str,
    anchor: str,
    metric: str,
    left_capacity: int = 14,
    right_capacity: int = 45,
    family: str | None = None,
) -> dict[str, Any]:
    selected = contrasts.loc[
        contrasts["contrast_type"].eq(contrast_type)
        & contrasts["anchor"].eq(anchor)
        & contrasts["metric"].eq(metric)
        & contrasts["left_capacity"].eq(left_capacity)
        & contrasts["right_capacity"].eq(right_capacity)
    ]
    if family is None:
        selected = selected.loc[selected["family"].isna()]
    else:
        selected = selected.loc[selected["family"].eq(family)]
    if len(selected) != 1:
        raise ValueError(
            f"Expected one contrast for {contrast_type}/{anchor}/{family}/{metric}."
        )
    return selected.iloc[0].to_dict()


def classify_anchor_relief(
    contrasts: pd.DataFrame,
    *,
    anchor: str,
    valid: bool = True,
) -> dict[str, Any]:
    if not valid:
        return {
            "classification": "capacity_relief_invalid",
            "clear_primary_count": 0,
            "monotonic_or_threshold_count": 0,
            "adverse_primary_count": 0,
        }
    clear = 0
    monotonic = 0
    adverse = 0
    details: dict[str, Any] = {}
    operational_count = 0
    for metric in PRIMARY_COMPLETION_METRICS:
        relief = _contrast_lookup(
            contrasts,
            contrast_type="direction_normalised_capacity_relief",
            anchor=anchor,
            metric=metric,
        )
        classification = _contrast_lookup(
            contrasts,
            contrast_type="monotonicity_classification",
            anchor=anchor,
            metric=metric,
        )["classification"]
        operational = relief["operationality"] == "operational"
        operational_count += int(operational)
        clearly_beneficial = (
            operational and float(relief["ci95_lower"]) > 0.0
        )
        clearly_adverse = operational and float(relief["ci95_upper"]) < 0.0
        clear += int(clearly_beneficial)
        adverse += int(clearly_adverse)
        monotonic += int(
            classification in {"monotonic_relief", "threshold_relief"}
        )
        details[metric] = {
            "operationality": relief["operationality"],
            "low_to_high_mean_relief": relief["mean"],
            "ci95_lower": relief["ci95_lower"],
            "ci95_upper": relief["ci95_upper"],
            "monotonicity": classification,
        }
    rejection = _contrast_lookup(
        contrasts,
        contrast_type="raw_capacity_contrast",
        anchor=anchor,
        metric="capacity_rejected_opportunity_count",
    )
    rejection_nonincreasing = float(rejection["mean"]) >= 0.0
    if operational_count == 0:
        status = "capacity_not_binding"
    elif clear >= 2 and monotonic >= 2 and adverse == 0 and rejection_nonincreasing:
        status = "capacity_relief_supported"
    elif (
        (clear > 0 or monotonic > 0)
        and adverse == 0
        and rejection_nonincreasing
    ):
        status = "capacity_relief_partial"
    elif (
        float(rejection["mean"]) == 0.0
        and all(
            details[metric]["monotonicity"] == "not_operational"
            for metric in PRIMARY_COMPLETION_METRICS
        )
    ):
        status = "capacity_not_binding"
    else:
        status = "capacity_relief_not_supported"
    return {
        "classification": status,
        "clear_primary_count": clear,
        "monotonic_or_threshold_count": monotonic,
        "adverse_primary_count": adverse,
        "operational_primary_count": operational_count,
        "capacity_rejections_nonincreasing": rejection_nonincreasing,
        "primary_metrics": details,
    }


def classify_d1(
    anchor_statuses: Mapping[str, Mapping[str, Any]],
    *,
    valid: bool = True,
) -> str:
    if not valid:
        return "invalid"
    values = [item["classification"] for item in anchor_statuses.values()]
    if all(value == "capacity_not_binding" for value in values):
        return "not_operational"
    supported = sum(value == "capacity_relief_supported" for value in values)
    adverse = any(value == "capacity_relief_not_supported" for value in values)
    if supported == 3:
        return "supported"
    if supported in {1, 2} and not adverse:
        return "partially_supported"
    return "not_supported"


def classify_d2(
    contrasts: pd.DataFrame,
    *,
    valid: bool = True,
) -> dict[str, Any]:
    if not valid:
        return {
            "classification": "shared_capacity_transmission_invalid",
            "anchors": {},
        }
    details: dict[str, Any] = {}
    full_count = partial_count = binding_count = 0
    for portfolio, shock in ANCHOR_ORDER:
        anchor = f"{portfolio}__{shock}"
        rejection = _contrast_lookup(
            contrasts,
            contrast_type="raw_capacity_contrast",
            anchor=anchor,
            metric="capacity_rejected_opportunity_count",
        )
        rejection_clear = float(rejection["ci95_lower"]) > 0.0
        binding_count += int(float(rejection["mean"]) > 0.0)
        rejecting_families: list[str] = []
        displaced_families: list[str] = []
        backlog_families: list[str] = []
        for family in FAMILY_ORDER:
            rejected = _contrast_lookup(
                contrasts,
                contrast_type="collateral_capacity_contrast",
                anchor=anchor,
                family=family,
                metric="rejected_count",
            )
            displaced = _contrast_lookup(
                contrasts,
                contrast_type="collateral_capacity_contrast",
                anchor=anchor,
                family=family,
                metric="cross_family_displacement_hours",
            )
            backlog = _contrast_lookup(
                contrasts,
                contrast_type="collateral_capacity_contrast",
                anchor=anchor,
                family=family,
                metric="backlog_area",
            )
            if float(rejected["mean"]) > 0.0:
                rejecting_families.append(family)
            if float(displaced["mean"]) > 0.0:
                displaced_families.append(family)
            if float(backlog["ci95_lower"]) > 0.0:
                backlog_families.append(family)
        cross_family = (
            len(rejecting_families) >= 2 or bool(displaced_families)
        )
        full = rejection_clear and cross_family and bool(backlog_families)
        partial = (
            float(rejection["mean"]) > 0.0
            and (cross_family or bool(backlog_families))
        )
        full_count += int(full)
        partial_count += int(partial)
        details[anchor] = {
            "clear_total_rejection_increase": rejection_clear,
            "rejecting_families": rejecting_families,
            "displaced_families": displaced_families,
            "clear_backlog_families": backlog_families,
            "full_rule": full,
            "partial_rule": partial,
            "pairwise_attribution": "not_identifiable",
        }
    if binding_count == 0:
        classification = "shared_capacity_not_binding"
    elif full_count >= 2:
        classification = "shared_capacity_transmission_present"
    elif full_count == 1 or partial_count >= 2:
        classification = "shared_capacity_transmission_mixed"
    else:
        classification = "shared_capacity_transmission_not_present"
    return {"classification": classification, "anchors": details}


def classify_d3(
    contrasts: pd.DataFrame,
    *,
    valid: bool = True,
) -> dict[str, Any]:
    if not valid:
        return {"classification": "peg_response_invalid", "anchors": {}}
    details: dict[str, Any] = {}
    affected = 0
    systematic_metrics = 0
    operational_total = 0
    metric_anchor_counts = Counter()
    for portfolio, shock in ANCHOR_ORDER:
        anchor = f"{portfolio}__{shock}"
        clear = 0
        operational = 0
        adverse = 0
        metrics: dict[str, Any] = {}
        for metric in PEG_METRICS:
            row = _contrast_lookup(
                contrasts,
                contrast_type="direction_normalised_capacity_relief",
                anchor=anchor,
                metric=metric,
            )
            is_operational = row["operationality"] == "operational"
            operational += int(is_operational)
            operational_total += int(is_operational)
            beneficial = is_operational and float(row["ci95_lower"]) > 0.0
            clearly_adverse = (
                is_operational and float(row["ci95_upper"]) < 0.0
            )
            clear += int(beneficial)
            adverse += int(clearly_adverse)
            metric_anchor_counts[metric] += int(beneficial)
            metrics[metric] = {
                "operationality": row["operationality"],
                "mean_relief": row["mean"],
                "ci95_lower": row["ci95_lower"],
                "ci95_upper": row["ci95_upper"],
            }
        affected += int(clear >= 2)
        details[anchor] = {
            "clear_worsening_at_low_capacity_count": clear,
            "clear_adverse_count": adverse,
            "operational_count": operational,
            "peg_friction_rule": clear >= 2,
            "metrics": metrics,
        }
    systematic_metrics = sum(value >= 2 for value in metric_anchor_counts.values())
    if operational_total == 0:
        classification = "peg_not_operational"
    elif affected >= 2:
        classification = "peg_friction_effect_present"
    elif affected == 1 or systematic_metrics >= 1:
        classification = "peg_friction_effect_partial"
    elif any(
        detail["clear_adverse_count"] > 0 for detail in details.values()
    ):
        classification = "peg_response_mixed"
    else:
        classification = "peg_unchanged"
    return {"classification": classification, "anchors": details}


def classify_overall_h1(
    d1: str,
    d2: str,
    d3: str,
    *,
    valid: bool = True,
) -> str:
    if not valid or any("invalid" in value for value in (d1, d2, d3)):
        return "H1_shared_capacity_experiment_invalid"
    if d1 == "not_operational":
        return "H1_shared_capacity_not_operational"
    if (
        d1 == "supported"
        and d3
        in {"peg_friction_effect_present", "peg_friction_effect_partial"}
    ):
        return "H1_shared_capacity_supported"
    if d1 in {"supported", "partially_supported"} and d3 in {
        "peg_unchanged",
        "peg_not_operational",
        "peg_response_mixed",
    }:
        return "H1_shared_capacity_partially_supported"
    if d1 == "partially_supported":
        return "H1_shared_capacity_backlog_effect_only"
    return "H1_no_clear_shared_capacity_effect"


def classify_peg_solvency(
    d1: str,
    d3: str,
    *,
    valid: bool = True,
) -> str:
    if not valid:
        return "relationship_invalid"
    solvency = d1 in {"supported", "partially_supported"}
    peg = d3 in {
        "peg_friction_effect_present",
        "peg_friction_effect_partial",
    }
    if solvency and peg:
        return "solvency_and_peg_improve_with_capacity"
    if solvency and d3 in {"peg_unchanged", "peg_not_operational"}:
        return "solvency_improves_peg_unchanged"
    if peg and not solvency:
        return "peg_improves_solvency_unchanged"
    if d3 == "peg_response_mixed":
        return "solvency_and_peg_diverge"
    if not solvency and not peg:
        return "neither_materially_changes"
    return "relationship_mixed"


def _validity_audit(
    system: pd.DataFrame,
    collateral: pd.DataFrame,
    programme_identity: str,
) -> dict[str, Any]:
    checkpoint = audit_checkpoints(programme_identity)
    numerical_failures = int(
        (~system["numerical_valid"].astype(bool)).sum()
    )
    accounting_failures = int(
        (~system["accounting_valid"].astype(bool)).sum()
    )
    path_failures = int((~system["path_valid"].astype(bool)).sum())
    capacity_failures = int(
        (~system["shared_capacity_valid"].astype(bool)).sum()
    )
    expected_cells = len(CELL_ORDER) * REPLICATIONS
    passed = bool(
        len(system) == expected_cells
        and len(collateral)
        == expected_cells * len(FAMILY_ORDER)
        and numerical_failures / expected_cells <= 0.01
        and accounting_failures == 0
        and path_failures == 0
        and capacity_failures == 0
        and checkpoint["complete"]
    )
    return {
        "passed": passed,
        "system_rows": len(system),
        "collateral_rows": len(collateral),
        "numerical_failure_count": numerical_failures,
        "accounting_failure_count": accounting_failures,
        "path_failure_count": path_failures,
        "capacity_failure_count": capacity_failures,
        "checkpoint_complete": checkpoint["complete"],
        "held_out_data_used": False,
        "usdc_svb_used": False,
        "capacity_selected": False,
    }


def classify_results(
    system: pd.DataFrame,
    collateral: pd.DataFrame,
    contrasts: pd.DataFrame,
    programme_identity: str,
) -> dict[str, Any]:
    validity = _validity_audit(system, collateral, programme_identity)
    anchors = {
        f"{portfolio}__{shock}": classify_anchor_relief(
            contrasts,
            anchor=f"{portfolio}__{shock}",
            valid=validity["passed"],
        )
        for portfolio, shock in ANCHOR_ORDER
    }
    d1 = classify_d1(anchors, valid=validity["passed"])
    d2_payload = classify_d2(contrasts, valid=validity["passed"])
    d3_payload = classify_d3(contrasts, valid=validity["passed"])
    d2 = d2_payload["classification"]
    d3 = d3_payload["classification"]
    overall = classify_overall_h1(
        d1, d2, d3, valid=validity["passed"]
    )
    relationship = classify_peg_solvency(
        d1, d3, valid=validity["passed"]
    )
    operationality = metric_operationality(system)
    bad_debt_boundary = {
        metric: operationality[metric] for metric in BAD_DEBT_METRICS
    }
    bad_debt_boundary["interpretation"] = (
        "H1 bad-debt component excluded where degenerate under the retained "
        "close-factor-one accounting boundary."
    )
    sensitivity: dict[str, str] = {}
    for metric in PRIMARY_COMPLETION_METRICS:
        values = {}
        for portfolio, shock in ANCHOR_ORDER:
            anchor = f"{portfolio}__{shock}"
            values[anchor] = float(
                _contrast_lookup(
                    contrasts,
                    contrast_type="direction_normalised_capacity_relief",
                    anchor=anchor,
                    metric=metric,
                )["mean"]
            )
        if max(values.values()) - min(values.values()) <= 1e-12:
            sensitivity[metric] = "similar_sensitivity"
        else:
            winner = max(values, key=values.get)
            sensitivity[metric] = {
                "empirical_crypto__joint_crypto_high_correlation": (
                    "crypto_anchor_more_sensitive"
                ),
                "stable_supported__joint_crypto_stable_stress": (
                    "stable_supported_more_sensitive"
                ),
                "stable_heavy__joint_crypto_stable_stress": (
                    "stable_heavy_more_sensitive"
                ),
            }[winner]
    if len(set(sensitivity.values())) > 1:
        sensitivity["overall"] = "metric_specific"
    else:
        sensitivity["overall"] = next(iter(sensitivity.values()))
    return {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "experiment_identity": experiment_identity(programme_identity),
        "programme_identity": programme_identity,
        "metric_operationality": operationality,
        "anchor_relief_statuses": anchors,
        "D1": {"classification": d1},
        "D2": d2_payload,
        "D3": d3_payload,
        "cross_anchor_sensitivity": sensitivity,
        "overall_h1_classification": overall,
        "peg_solvency_relationship": relationship,
        "bad_debt_evaluation_boundary": bad_debt_boundary,
        "validity_audit": validity,
        "capacity_selected": False,
        "preferred_capacity": None,
        "next_authorised_stage": (
            "result_blind_oracle_delay_freeze_before_experiment_e"
        ),
        "experiment_e_executed": False,
        "runtime_adopted": False,
    }


def _load_checkpoints(programme_identity: str) -> list[dict[str, Any]]:
    return [
        json.loads(
            _checkpoint_path(
                _output_dir(programme_identity), replication
            ).read_text(encoding="utf-8")
        )
        for replication in range(REPLICATIONS)
    ]


def _benchmark_validate(benchmark: Mapping[str, Any]) -> None:
    required = {
        "execution_command",
        "worker_count",
        "full_wall_time_seconds",
        "throughput_simulations_per_second",
        "completed_replications",
        "reused_replications",
        "resumed_replications",
        "failed_replications",
        "rerun_replications",
        "completed_simulations",
        "checkpoint_count",
        "output_size_bytes",
        "free_storage_bytes",
    }
    if required - set(benchmark):
        raise ValueError("Experiment D benchmark is incomplete.")
    if int(benchmark["completed_simulations"]) != 1152:
        raise ValueError("Experiment D benchmark simulation count differs.")


def build_evidence_payloads(
    programme_identity: str,
    benchmark: Mapping[str, Any],
) -> dict[str, bytes]:
    _assert_preregistered_identities(programme_identity)
    _benchmark_validate(benchmark)
    system, collateral = load_results(programme_identity)
    cells = cell_summary(system)
    collateral_cells = collateral_summary(collateral)
    contrasts = paired_contrasts(system, collateral)
    decision = classify_results(
        system, collateral, contrasts, programme_identity
    )
    checkpoints = _load_checkpoints(programme_identity)
    anchor_crn_failures = [
        {
            "replication": payload["replication"],
            "anchor": anchor,
        }
        for payload in checkpoints
        for anchor, audit in payload["anchor_audits"].items()
        if not (
            audit["common_random_numbers_valid"]
            and audit["ranking_owner_invariant"]
            and len(
                set(audit["capacity_neutral_owner_checksums"].values())
            )
            == 1
        )
    ]
    queue_audit = {
        "ranking_owner": (
            "expected_profit_desc_debt_at_risk_desc_vault_id_asc"
        ),
        "capacity_neutral_input_failures": len(anchor_crn_failures),
        "capacity_neutral_inputs_paired": not anchor_crn_failures,
        "dynamic_queue_interpretation": (
            "queue paths may diverge only through prior capacity-mediated "
            "state changes; the capacity-neutral inputs and ranking owner "
            "remain identical within each anchor and replication"
        ),
        "pairwise_displacement_identifiable": False,
        "selected_and_rejected_checksums_recorded": True,
    }
    audit = audit_checkpoints(programme_identity)
    regression = regression_audit()
    result_frames = {
        COMPACT_FILENAMES[2]: _csv_bytes(cells),
        COMPACT_FILENAMES[3]: _csv_bytes(collateral_cells),
        COMPACT_FILENAMES[4]: _csv_bytes(contrasts),
        COMPACT_FILENAMES[5]: _pretty_json(decision),
    }
    reproducibility = {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "experiment_identity": experiment_identity(programme_identity),
        "programme_identity": programme_identity,
        "scientific_code_identity": scientific_code_identity(),
        "simulation_core_identity": simulation_core_identity(),
        "seed_registry_sha256": seed_registry_checksum(),
        "crn_audit": {
            "passed": not anchor_crn_failures,
            "failure_count": len(anchor_crn_failures),
            "failures": anchor_crn_failures,
            "paired_anchor_replications": len(ANCHOR_ORDER) * REPLICATIONS,
        },
        "queue_audit": queue_audit,
        "checkpoint_audit": audit,
        "simulation_counts": {
            "experiment_d": len(CELL_ORDER) * REPLICATIONS,
            "experiment_a": 0,
            "experiment_b": 0,
            "experiment_c": 0,
            "experiment_e": 0,
        },
        "result_checksums": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in result_frames.items()
        },
        "protected_regression_audit": regression,
        "experiments_a_b_c_unchanged": regression["passed"],
        "experiment_e_unexecuted": True,
        "held_out_data_used": False,
        "usdc_svb_used": False,
        "capacity_selected": False,
        "parameter_recalibration_runs": 0,
        "runtime_adopted": False,
        "deterministic_reconstruction": True,
    }
    specification = EVIDENCE_DIR / COMPACT_FILENAMES[0]
    registry = EVIDENCE_DIR / COMPACT_FILENAMES[1]
    if not specification.is_file() or not registry.is_file():
        raise ValueError("Experiment D pre-registration files are missing.")
    return {
        COMPACT_FILENAMES[0]: specification.read_bytes(),
        COMPACT_FILENAMES[1]: registry.read_bytes(),
        **result_frames,
        COMPACT_FILENAMES[6]: _pretty_json(reproducibility),
        COMPACT_FILENAMES[7]: _pretty_json(dict(benchmark)),
    }


def _manifest_records(paths: Iterable[Path]) -> list[dict[str, Any]]:
    return [
        {
            "classification": (
                "pre_registered_final_shared_keeper_capacity_experiment"
            ),
            "path": _relative(path),
            "runtime_adopted": False,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in paths
    ]


def update_experiment_manifest(records: Sequence[Mapping[str, Any]]) -> None:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    owned_paths = {
        _relative(EVIDENCE_DIR / name) for name in COMPACT_FILENAMES
    }
    preserved = sorted(
        (
            row
            for row in payload["artefacts"]
            if str(row["path"]) not in owned_paths
        ),
        key=lambda row: str(row["path"]),
    )
    if len(preserved) != 51:
        raise ValueError("Experiment D expected 51 preserved artefacts.")
    if _payload_sha256(preserved) != BASE_MANIFEST_ARTEFACTS_SHA256:
        raise ValueError("Experiment D preserved manifest rows changed.")
    if {str(row["path"]) for row in records} != owned_paths:
        raise ValueError("Experiment D manifest ownership differs.")
    combined = sorted(
        [*preserved, *map(dict, records)],
        key=lambda row: str(row["path"]),
    )
    if len({str(row["path"]) for row in combined}) != len(combined):
        raise ValueError("Experiment manifest contains duplicate paths.")
    payload["artefacts"] = combined
    payload["artefact_count"] = len(combined)
    if payload["artefact_count"] != 59:
        raise ValueError("Experiment manifest must contain 59 artefacts.")
    _atomic_json(MANIFEST_PATH, payload)


def write_evidence(
    programme_identity: str,
    benchmark: Mapping[str, Any],
) -> dict[str, Any]:
    checkpoint_before = audit_checkpoints(programme_identity)
    if not checkpoint_before["complete"]:
        raise ValueError("Experiment D checkpoints are incomplete.")
    first = build_evidence_payloads(programme_identity, benchmark)
    second = build_evidence_payloads(programme_identity, benchmark)
    for name in DETERMINISTIC_FILENAMES:
        if first[name] != second[name]:
            raise ValueError(f"Experiment D evidence differs: {name}.")
    with tempfile.TemporaryDirectory(
        prefix="experiment-d-evidence-first-"
    ) as first_name, tempfile.TemporaryDirectory(
        prefix="experiment-d-evidence-second-"
    ) as second_name:
        for directory, payloads in zip(
            (Path(first_name), Path(second_name)),
            (first, second),
            strict=True,
        ):
            for name, payload in payloads.items():
                _atomic_bytes(directory / name, payload)
        for name in DETERMINISTIC_FILENAMES:
            if (Path(first_name) / name).read_bytes() != (
                Path(second_name) / name
            ).read_bytes():
                raise ValueError(
                    f"Isolated Experiment D reconstruction differs: {name}."
                )
    if audit_checkpoints(programme_identity) != checkpoint_before:
        raise ValueError("Experiment D evidence changed checkpoints.")
    for name, payload in first.items():
        path = EVIDENCE_DIR / name
        if path.exists() and path.read_bytes() != payload:
            if name in COMPACT_FILENAMES[:2]:
                raise ValueError("Experiment D pre-registration changed.")
        _atomic_bytes(path, payload)
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    update_experiment_manifest(_manifest_records(paths))
    return {
        "experiment_identity": experiment_identity(programme_identity),
        "artefact_count": len(paths),
        "artefact_checksums": {
            path.name: sha256_file(path) for path in paths
        },
        "deterministic_reconstruction": True,
        "checkpoint_content_unchanged": True,
    }


def validate_evidence(programme_identity: str) -> dict[str, Any]:
    _assert_preregistered_identities(programme_identity)
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    if not all(path.is_file() for path in paths):
        raise ValueError("Experiment D compact evidence is incomplete.")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    records = {str(row["path"]): row for row in manifest["artefacts"]}
    for path in paths:
        record = records.get(_relative(path))
        if (
            record is None
            or record["sha256"] != sha256_file(path)
            or int(record["size_bytes"]) != path.stat().st_size
        ):
            raise ValueError(f"Manifest mismatch for {_relative(path)}.")
    registry = pd.read_csv(EVIDENCE_DIR / COMPACT_FILENAMES[1])
    cells = pd.read_csv(EVIDENCE_DIR / COMPACT_FILENAMES[2])
    collateral = pd.read_csv(EVIDENCE_DIR / COMPACT_FILENAMES[3])
    contrasts = pd.read_csv(EVIDENCE_DIR / COMPACT_FILENAMES[4])
    decision = json.loads(
        (EVIDENCE_DIR / COMPACT_FILENAMES[5]).read_text(encoding="utf-8")
    )
    reproducibility = json.loads(
        (EVIDENCE_DIR / COMPACT_FILENAMES[6]).read_text(encoding="utf-8")
    )
    if (
        len(registry) != 9
        or registry["identifier"].tolist() != list(CELL_ORDER)
        or decision["validity_audit"]["passed"] is not True
        or decision["capacity_selected"] is not False
        or decision["experiment_e_executed"] is not False
        or decision["runtime_adopted"] is not False
        or reproducibility["crn_audit"]["passed"] is not True
        or manifest["artefact_count"] != 59
    ):
        raise ValueError("Experiment D evidence validation failed.")
    return {
        "passed": True,
        "experiment_identity": experiment_identity(programme_identity),
        "artefact_count": 8,
        "manifest_artefact_count": 59,
        "registry_rows": len(registry),
        "cell_summary_rows": len(cells),
        "collateral_summary_rows": len(collateral),
        "contrast_rows": len(contrasts),
        "decision": {
            "D1": decision["D1"]["classification"],
            "D2": decision["D2"]["classification"],
            "D3": decision["D3"]["classification"],
            "overall_h1_classification": decision[
                "overall_h1_classification"
            ],
            "peg_solvency_relationship": decision[
                "peg_solvency_relationship"
            ],
        },
        "experiments_a_b_c_unchanged": True,
        "experiment_e_unexecuted": True,
        "capacity_selected": False,
        "runtime_adopted": False,
    }
