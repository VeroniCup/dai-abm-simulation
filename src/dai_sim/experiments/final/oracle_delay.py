"""Pre-registered Experiment E oracle-delay study.

Experiment E consumes the six immutable E rows in the final dissertation
programme and resolves their treatment identifiers through the separately
frozen oracle-delay registry.  The module owns Experiment E orchestration,
diagnostics, paired contrasts and compact evidence.  Price-delay mechanics,
portfolio and shock construction, liquidation execution, keeper capacity and
DAI-price mechanics remain with their established semantic owners.
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
    shared_keeper_capacity as experiment_d,
    stable_collateral_tradeoff as experiment_c,
)
from dai_sim.experiments.final.programme import (
    FinalExperimentProgramme,
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
from dai_sim.inputs.oracle_delay import load_oracle_delay_registry
from dai_sim.model.collateral import CollateralPortfolioConfig
from dai_sim.model.collateral_prices import normalise_collateral_price_paths
from dai_sim.model.liquidation import (
    execute_keeper_liquidation,
    rank_liquidation_candidates,
)
from dai_sim.validation import multicollateral as multicollateral_validation
from dai_sim.validation.oracle_delay import resolve_experiment_e_cells


EXPERIMENT_E_PARENT_COMMIT = "2ccbdc688b7b47bde189fb1d8770fa66343dbb3e"
MASTER_PROGRAMME_IDENTITY = (
    "084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260"
)
ORACLE_REGISTRY_IDENTITY = (
    "2e562ef2618e472ce3b0551addf2596ddbe137910fa6d2ad5884ae71c674e46d"
)
ORACLE_REGISTRY_SHA256 = (
    "f62159b0219d42716aefe8866d120bd809fca825dc0645e114d4565e0ba43b47"
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

PROTECTED_EXPERIMENTS = {
    "a": (
        experiment_a,
        "a9d7c3fa5dc5da9bcf61314a57501ea5a8be506e305eee6f45afaae3131600bb",
        "110b0d16a0f945bd720c400957e8c94297b4d20d19bda495ca7601640c90900c",
        "aa31d65e4609db14e4b8392eb623dfdaae3c15cdf08eef6c100e313729508583",
    ),
    "b": (
        experiment_b,
        "e02c035162f8178c96d2cae71d0a581ce813ab33526854bd5810e8e2810ead83",
        "091a420491c51bc1b25157a5adcef9565673e012d49fe90f350361b64aa3dc83",
        "e780bc139e34e64975d3108f6565509ab3c5db93758023a246a4913f5766e781",
    ),
    "c": (
        experiment_c,
        "cb6d00877c54011cc49714bdfe23fad83140fef001568ea9b43d355811c9129b",
        "7f26a4bc4230d496f7e3a7a96496f4ff709342b4c4d6f7987889bf25304275b6",
        "57e645f44db5af1db337d72f18a2c3460c0f6cae32341152acf7b586a14c52d0",
    ),
    "d": (
        experiment_d,
        "b324c31be7ef6dd7f61e504709b2086b0e88ce181c177f25dcaad182095c17e3",
        "8c0da9bfb6cb65c5c0ca21da34ab337f4e572505e4446180d0c30792112ba4e3",
        "48bb01e3e911648c440ff080ab1f4dfddbd37e8bc3c60ad3f1cde3ba3e54a87b",
    ),
}

EXPERIMENT_ID = "E_oracle_delay"
EXPERIMENT_NAMESPACE = "final-oracle-delay-v1"
EVIDENCE_DIR = REPOSITORY_ROOT / "data/provenance/experiments/final/oracle_delay"
OUTPUT_ROOT = REPOSITORY_ROOT / "outputs/experiments/final/oracle_delay"
MANIFEST_PATH = REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"

ANCHOR_ORDER = (
    ("empirical_crypto", "joint_crypto_high_correlation"),
    ("stable_supported", "joint_crypto_stable_stress"),
)
DELAY_ORDER = (0, 1, 2)
TREATMENT_ORDER = (
    "oracle_delay_low",
    "oracle_delay_central",
    "oracle_delay_high",
)
CELL_ORDER = tuple(
    f"{shock}__{portfolio}__{treatment}"
    for portfolio, shock in ANCHOR_ORDER
    for treatment in TREATMENT_ORDER
)
EXPECTED_MASTER_CELL_CHECKSUMS = (
    "89e8a346632061e9ed102e46de23df6e485645c25ebcf7afa56608f5cfa6dac3",
    "3c5b57ec2ac3a79b9b681b9755cfe4ecb4e1539d1e59229e387d19d16528d458",
    "94702453e785bb9166b2593937a42a3c9545e7f3026464ac6f4141888cf336be",
    "df8f1b2693fffb0e46330c64d654f013ed1ad4332c7322895f536da1ff559a96",
    "ca13d211571c23492b60a9d8dfdf5ef6993bcdad1f2bf46f68f7cf2ef435d6f8",
    "e36be5c723367ecb34f1ed813f3a0ce68976509963bf8d4b69296fe8f69ff577",
)

REPLICATIONS = 128
VAULT_COUNT = 500
TOTAL_DEBT_DAI = 2_500_000.0
TARGET_SYSTEM_COLLATERAL_RATIO = 3.6089387701260205
CAPACITY = 26
PRE_SHOCK_HOURS = 48
POST_SHOCK_HOURS = 720
TOTAL_HOURS = 768
MAXIMUM_OUTPUT_BYTES = 500 * 1024**2
MINIMUM_FREE_BYTES = 10 * 1024**3
INITIALISATION_REPLICATION_OFFSET = 4_000_000
MISMATCH_TOLERANCE = 1e-12

SEED_STREAMS = (
    "initialisation_key",
    "market_gas_blocks",
    "keeper_gas_units",
    "liquidation_arrivals",
    "stage1_residual_blocks",
)

MISMATCH_METRICS = (
    "debt_weighted_absolute_mismatch_area",
    "debt_weighted_overvaluation_area",
    "debt_weighted_undervaluation_area",
    "peak_debt_weighted_mismatch",
)
SAFETY_METRICS = (
    "false_safe_vault_hours",
    "false_safe_debt_hours",
    "peak_false_safe_debt",
    "false_unsafe_vault_hours",
    "false_unsafe_debt_hours",
    "peak_false_unsafe_debt",
    "market_unsafe_debt_not_oracle_eligible_share",
    "oracle_unsafe_debt_already_market_safe_share",
    "recognition_lag_mean",
    "recognition_lag_median",
    "recovery_staleness_mean",
    "recovery_staleness_median",
)
LIQUIDATION_METRICS = (
    "backlog_area_share",
    "maximum_unresolved_tab_share",
    "terminal_unresolved_tab_share",
    "liquidation_completion_ratio",
    "peak_eligible_tab_share",
    "peak_new_eligible_tab_share",
    "peak_selected_attempts",
    "peak_successful_closures",
    "hours_for_half_eligible_tab",
    "five_busiest_eligible_tab_share",
    "capacity_binding_hours",
    "capacity_rejected_opportunity_count",
    "successful_closure_count",
    "liquidated_debt_share",
    "debt_weighted_liquidated_vault_share",
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
    *MISMATCH_METRICS,
    *SAFETY_METRICS,
    *LIQUIDATION_METRICS,
    *BAD_DEBT_METRICS,
    *PEG_METRICS,
)
COLLATERAL_METRICS = (
    "initial_debt_exposure",
    "absolute_mismatch_area",
    "peak_absolute_mismatch",
    "oracle_overvaluation_area",
    "peak_oracle_overvaluation",
    "oracle_undervaluation_area",
    "peak_oracle_undervaluation",
    "mismatch_hours",
    "mismatch_hours_above_tolerance",
    "false_safe_vault_hours",
    "false_safe_debt_hours",
    "peak_false_safe_debt",
    "false_unsafe_vault_hours",
    "false_unsafe_debt_hours",
    "peak_false_unsafe_debt",
    "eligible_liquidation_tab",
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
)

HIGHER_IS_BETTER = {
    "liquidation_completion_ratio",
    "minimum_dai_price",
    "recovery_probability_720h",
}
METRIC_DIRECTIONS = {
    metric: (-1 if metric in HIGHER_IS_BETTER else 1) for metric in SYSTEM_METRICS
}
MATERIALITY_THRESHOLDS = {
    "numerical_oracle_path_tolerance": MISMATCH_TOLERANCE,
    "accounting_tolerance_dai": 1e-5,
    "failure_share_invalid": 0.01,
    "contrast_interval_confidence": 0.95,
    "initial_total_debt_dai": TOTAL_DEBT_DAI,
    "initial_debt_exposure_scale": 1.0 / TOTAL_DEBT_DAI,
    "simulation_step_hours": 1,
}

COMPACT_FILENAMES = (
    "oracle_delay_specification.json",
    "oracle_delay_registry.csv",
    "oracle_delay_cell_summary.csv",
    "oracle_delay_collateral_summary.csv",
    "oracle_delay_contrasts.csv",
    "oracle_delay_decision.json",
    "oracle_delay_reproducibility.json",
    "oracle_delay_benchmark.json",
)
DETERMINISTIC_FILENAMES = COMPACT_FILENAMES[:-1]
DISTRIBUTION_FIELDS = experiment_d.DISTRIBUTION_FIELDS


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
    """Derive one Experiment E-owned deterministic seed."""
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
        "initialisation_replication_key": initialisation_replication_key(replication),
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
class ExperimentECell:
    order: int
    identifier: str
    portfolio: str
    shock: str
    treatment: str
    delay_steps: int
    delay_hours: int
    capacity: int
    hurdle: str
    confidence: str
    replication_count: int
    master_row_checksum: str


def build_cell_registry(
    programme: FinalExperimentProgramme | None = None,
) -> tuple[ExperimentECell, ...]:
    owner = load_programme() if programme is None else programme
    if owner.programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Master programme identity changed.")
    oracle_registry = load_oracle_delay_registry()
    if (
        oracle_registry.identity != ORACLE_REGISTRY_IDENTITY
        or oracle_registry.configuration_checksum != ORACLE_REGISTRY_SHA256
    ):
        raise ValueError("Frozen oracle-delay registry changed.")
    resolved = resolve_experiment_e_cells(owner, oracle_registry)
    if tuple(cell.cell_identifier for cell in resolved) != CELL_ORDER:
        raise ValueError("Experiment E master-registry order changed.")
    if tuple(cell.master_row_checksum for cell in resolved) != (
        EXPECTED_MASTER_CELL_CHECKSUMS
    ):
        raise ValueError("Experiment E master-row checksums changed.")
    rows: list[ExperimentECell] = []
    for order, cell in enumerate(resolved, start=1):
        if (
            cell.replication_count != REPLICATIONS
            or cell.maximum_liquidations_per_step != CAPACITY
            or cell.hurdle_profile_identifier != "direct_cost_only"
            or cell.confidence_scenario_identifier != "stage1_only"
        ):
            raise ValueError("Experiment E frozen settings changed.")
        treatment = oracle_registry.by_identifier(cell.oracle_treatment_identifier)
        rows.append(
            ExperimentECell(
                order=order,
                identifier=cell.cell_identifier,
                portfolio=cell.portfolio_identifier,
                shock=cell.shock_identifier,
                treatment=treatment.identifier,
                delay_steps=treatment.delay_steps,
                delay_hours=treatment.equivalent_hours,
                capacity=cell.maximum_liquidations_per_step,
                hurdle=cell.hurdle_profile_identifier,
                confidence=cell.confidence_scenario_identifier,
                replication_count=cell.replication_count,
                master_row_checksum=cell.master_row_checksum,
            )
        )
    if tuple(row.delay_steps for row in rows) != DELAY_ORDER * 2:
        raise ValueError("Experiment E delay coordinates changed.")
    return tuple(rows)


def _registry_frame() -> pd.DataFrame:
    rows = []
    for cell in build_cell_registry():
        row = asdict(cell)
        row["row_checksum"] = _row_checksum(row)
        rows.append(row)
    return pd.DataFrame(rows)


def _draw_e_states(replication: int) -> dict[str, Any]:
    """Draw one common safe initial state for both frozen E anchors."""
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
        master_seed = experiment_a.derive_seed(state_key, "initialisation_master")
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
                for portfolio, _ in ANCHOR_ORDER
            }
        except ValueError as exc:
            if "initially unsafe" in str(exc):
                continue
            raise
        audit = _audit_nested_initialisations(states)
        return {"states": states, "audit": audit}
    raise ValueError("No common safe Experiment E initialisation was accepted.")


def _audit_nested_initialisations(states: Mapping[str, Any]) -> dict[str, Any]:
    """Apply C's prefix audit to Experiment E's exact two-anchor subset."""
    expected = tuple(portfolio for portfolio, _ in ANCHOR_ORDER)
    if tuple(states) != expected:
        raise ValueError("Experiment E nested portfolio order differs.")
    failures: list[str] = []
    for family in FAMILY_ORDER:
        ilks = sorted(
            {
                str(value)
                for state in states.values()
                for value in state.sampled.loc[
                    state.sampled["family"].eq(family), "exact_ilk"
                ].dropna()
            }
        )
        for ilk in ilks or [None]:
            sequences: list[tuple[str, list[str]]] = []
            for portfolio, state in states.items():
                selected = state.sampled.loc[state.sampled["family"].eq(family)]
                if ilk is not None:
                    selected = selected.loc[selected["exact_ilk"].eq(ilk)]
                values = (
                    selected.sort_values("family_stream_position", kind="mergesort")[
                        "source_row_id"
                    ]
                    .astype(str)
                    .tolist()
                )
                sequences.append((portfolio, values))
            ordered = sorted(sequences, key=lambda item: len(item[1]))
            for (left_name, left), (right_name, right) in zip(
                ordered, ordered[1:], strict=False
            ):
                if left != right[: len(left)]:
                    failures.append(f"{family}/{ilk}:{left_name}->{right_name}")
    if failures:
        raise ValueError(f"Experiment E nested family draws failed: {failures}.")
    return {
        "passed": True,
        "portfolio_count": len(states),
        "failure_count": 0,
        "initialisation_identities": {
            name: state.identity for name, state in states.items()
        },
    }


def _arrival_stream(replication: int) -> dict[str, Any]:
    integrated = resolve_integrated_empirical_eth_profile()
    config = integrated.liquidation_demand
    pool = load_liquidation_arrival_pool(config.pool_path, config.pool_sha256)
    positive = pool.loc[
        pool["positive_count_eligible"].astype(bool), "grab_count"
    ].to_numpy(dtype=int)
    rng = np.random.default_rng(derive_seed(replication, "liquidation_arrivals"))
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
    initialisation = _draw_e_states(replication)
    states = initialisation["states"]
    accepted_attempt = next(
        iter({int(state.accepted_attempt) for state in states.values()})
    )
    state_key = initialisation_replication_key(replication)
    master_seed = experiment_a.derive_seed(state_key, "initialisation_master")
    profile = resolve_multicollateral_inputs("eth_only").profile
    market_pool = load_final_market_pool(
        profile.market_pool_path, profile.market_pool_sha256
    )
    block_length = int(profile.raw["market_process"]["block_length_hours"])
    starts = multicollateral_validation._valid_market_block_starts(
        market_pool, block_length
    )
    rng = np.random.default_rng(derive_seed(replication, "market_gas_blocks"))
    block_count = math.ceil(TOTAL_HOURS / block_length)
    chosen_starts = rng.choice(starts, size=block_count, replace=True)
    sampled = (
        pd.concat(
            [
                market_pool.iloc[int(start) : int(start) + block_length].copy()
                for start in chosen_starts
            ],
            ignore_index=True,
        )
        .iloc[:TOTAL_HOURS]
        .copy()
    )
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
        "state_identities": {name: state.identity for name, state in states.items()},
        "market_start_indexes": [int(value) for value in chosen_starts],
        "market_rows_checksum": _payload_sha256(
            sampled["pool_row_id"].astype(str).tolist()
        ),
        "arrival_checksum": arrivals["checksum"],
        "residual_checksum": hashlib.sha256(
            np.asarray(residuals, dtype="<f8").tobytes()
        ).hexdigest(),
        "keeper_gas_units_seed": derive_seed(replication, "keeper_gas_units"),
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


def _price_key(family: str) -> str:
    return "BTC" if family == "WBTC" else family


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
) -> Any:
    active = bool(inventory and uniform < hurdle_probability)
    sampled = int(positive_count) if active else 0
    bounded = min(sampled, inventory)
    attempts = min(bounded, CAPACITY)
    return experiment_a.LiquidationDemandDecision(
        step=step,
        liquidatable_inventory=inventory,
        activity_draw=active,
        raw_positive_count_draw=int(positive_count) if active else 0,
        sampled_demand=sampled,
        bounded_demand=bounded,
        keeper_capacity=CAPACITY,
        attempt_budget=attempts,
        demand_truncated_by_inventory=max(sampled - bounded, 0),
        demand_truncated_by_capacity=max(bounded - attempts, 0),
        demand_inactive_unresolved=inventory if inventory and not active else 0,
        inventory_not_sampled_unresolved=inventory - bounded if active else 0,
    )


def build_oracle_paths(
    market_paths: Mapping[str, np.ndarray], delay_steps: int
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Resolve delayed paths through the existing model semantic owner."""
    if delay_steps not in DELAY_ORDER:
        raise ValueError("Experiment E delay is not registered.")
    source = {
        key: np.asarray(values, dtype="<f8").copy()
        for key, values in market_paths.items()
    }
    resolved = normalise_collateral_price_paths(source, delay_steps=delay_steps)
    market = {
        key: np.asarray(values, dtype="<f8")
        for key, values in resolved.market_prices.items()
    }
    oracle = {
        key: np.asarray(values, dtype="<f8")
        for key, values in resolved.oracle_prices.items()
    }
    for key, values in source.items():
        if not np.array_equal(market[key], values):
            raise ValueError("Oracle treatment mutated a market path.")
        expected = np.empty_like(values)
        if delay_steps == 0:
            expected[:] = values
        else:
            expected[:delay_steps] = values[0]
            expected[delay_steps:] = values[:-delay_steps]
        if not np.array_equal(oracle[key], expected):
            raise ValueError(f"Oracle path rule failed for {key}.")
    checksums = {
        key: hashlib.sha256(values.tobytes()).hexdigest()
        for key, values in oracle.items()
    }
    return oracle, {
        "passed": True,
        "delay_steps": delay_steps,
        "family_checksums": checksums,
        "combined_checksum": _payload_sha256(checksums),
        "market_unchanged": True,
        "initial_price_repetition": True,
        "no_interpolation": True,
        "global_family_scope": tuple(oracle) == ("ETH", "BTC", "STABLE"),
    }


def mismatch_diagnostics(
    market_paths: Mapping[str, np.ndarray],
    oracle_paths: Mapping[str, np.ndarray],
    initial_debt: Mapping[str, float],
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Calculate frozen family and initial-debt-weighted mismatch metrics."""
    total = float(sum(initial_debt.values()))
    if not math.isclose(total, TOTAL_DEBT_DAI, rel_tol=0.0, abs_tol=1e-5):
        raise ValueError("Initial debt does not match the frozen system total.")
    families: dict[str, dict[str, float]] = {}
    system_absolute = np.zeros(TOTAL_HOURS, dtype="<f8")
    system_over = np.zeros(TOTAL_HOURS, dtype="<f8")
    system_under = np.zeros(TOTAL_HOURS, dtype="<f8")
    for family in FAMILY_ORDER:
        key = _price_key(family)
        market = np.asarray(market_paths[key], dtype="<f8")
        oracle = np.asarray(oracle_paths[key], dtype="<f8")
        if np.any(market <= 0.0) or np.any(oracle <= 0.0):
            raise ValueError("Mismatch paths must remain positive.")
        gap = np.log(market / oracle)
        absolute = np.abs(gap)
        overvaluation = np.maximum(-gap, 0.0)
        undervaluation = np.maximum(gap, 0.0)
        weight = float(initial_debt[family] / total)
        system_absolute += weight * absolute
        system_over += weight * overvaluation
        system_under += weight * undervaluation
        families[family] = {
            "absolute_mismatch_area": float(absolute.sum()),
            "peak_absolute_mismatch": float(absolute.max()),
            "oracle_overvaluation_area": float(overvaluation.sum()),
            "peak_oracle_overvaluation": float(overvaluation.max()),
            "oracle_undervaluation_area": float(undervaluation.sum()),
            "peak_oracle_undervaluation": float(undervaluation.max()),
            "mismatch_hours": int(np.count_nonzero(absolute > 0.0)),
            "mismatch_hours_above_tolerance": int(
                np.count_nonzero(absolute > MISMATCH_TOLERANCE)
            ),
        }
    system = {
        "debt_weighted_absolute_mismatch_area": float(system_absolute.sum()),
        "debt_weighted_overvaluation_area": float(system_over.sum()),
        "debt_weighted_undervaluation_area": float(system_under.sum()),
        "peak_debt_weighted_mismatch": float(system_absolute.max()),
    }
    return system, families


def _event_distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    raw = np.asarray(list(values), dtype=float)
    finite = raw[np.isfinite(raw)]
    if finite.size == 0:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p05": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "positive_share": None,
        }
    return {
        "count": int(finite.size),
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "p05": float(np.quantile(finite, 0.05)),
        "p25": float(np.quantile(finite, 0.25)),
        "p75": float(np.quantile(finite, 0.75)),
        "p90": float(np.quantile(finite, 0.90)),
        "p95": float(np.quantile(finite, 0.95)),
        "positive_share": float(np.mean(finite > 0.0)),
    }


def classify_safety_state(*, market_unsafe: bool, oracle_unsafe: bool) -> str:
    """Name the diagnostic market/oracle safety state without triggering action."""
    if market_unsafe and not oracle_unsafe:
        return "false_safe"
    if oracle_unsafe and not market_unsafe:
        return "false_unsafe"
    if market_unsafe:
        return "jointly_unsafe"
    return "jointly_safe"


def event_lag(first_reference: int | None, first_delayed: int | None) -> float | None:
    """Return a timing lag only when both registered events occur."""
    if first_reference is None or first_delayed is None:
        return None
    return float(first_delayed - first_reference)


def _hours_for_half(values: np.ndarray) -> int:
    total = float(np.sum(values))
    if total <= 0.0:
        return 0
    ordered = np.sort(np.asarray(values, dtype=float))[::-1]
    return int(np.searchsorted(np.cumsum(ordered), total * 0.5) + 1)


def _simulate_delay_liquidations(
    *,
    initialisation: Any,
    market_paths: Mapping[str, np.ndarray],
    oracle_paths: Mapping[str, np.ndarray],
    gas_costs: np.ndarray,
    arrivals: Mapping[str, Any],
    portfolio_config: CollateralPortfolioConfig,
) -> dict[str, Any]:
    """Execute the frozen liquidation mechanism using delayed oracle prices."""
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
            "eligible_tab": "<f8",
            "new_eligible_tab": "<f8",
            "false_safe_vaults": "<i8",
            "false_safe_debt": "<f8",
            "false_unsafe_vaults": "<i8",
            "false_unsafe_debt": "<f8",
            "market_unsafe_debt": "<f8",
            "oracle_unsafe_debt": "<f8",
        }.items()
    }
    family_arrays = {
        family: {
            name: np.zeros(TOTAL_HOURS, dtype="<f8")
            for name in (
                "eligible",
                "new_eligible",
                "selected",
                "rejected",
                "closures",
                "liquidated_debt",
                "backlog",
                "active_bad_debt",
                "realised_bad_debt",
                "keeper_profit",
                "false_safe_vaults",
                "false_safe_debt",
                "false_unsafe_vaults",
                "false_unsafe_debt",
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
    first_events: dict[int, dict[str, int | None]] = {
        int(vault.vault_id): {
            "market_unsafe": None,
            "oracle_unsafe": None,
            "market_resafe": None,
            "oracle_resafe": None,
            "selected": None,
            "closure": None,
        }
        for vault in vaults
    }
    market_was_unsafe: set[int] = set()
    oracle_was_unsafe: set[int] = set()
    eligible_seen: set[int] = set()
    eligible_tab_by_family = defaultdict(float)
    liquidated_ids: set[int] = set()
    closed_ids: set[int] = set()
    removed_collateral = defaultdict(float)
    repaid_debt = defaultdict(float)
    terminal_writeoff = defaultdict(float)
    duplicate_attempt = False
    duplicate_closure = False
    reconciliation_failures = 0

    for step in range(TOTAL_HOURS):
        market_prices = {
            family: float(market_paths[family][step])
            for family in ("ETH", "BTC", "STABLE")
        }
        oracle_prices = {
            family: float(oracle_paths[family][step])
            for family in ("ETH", "BTC", "STABLE")
        }
        market_unsafe: list[Any] = []
        oracle_unsafe: list[Any] = []
        for vault in vaults:
            if not vault.is_active:
                continue
            vault_id = int(vault.vault_id)
            family = _family(vault.collateral_type)
            is_market_unsafe = vault.is_liquidatable(market_prices)
            is_oracle_unsafe = vault.is_liquidatable(oracle_prices)
            if is_market_unsafe:
                market_unsafe.append(vault)
                if first_events[vault_id]["market_unsafe"] is None:
                    first_events[vault_id]["market_unsafe"] = step
                market_was_unsafe.add(vault_id)
            elif (
                vault_id in market_was_unsafe
                and first_events[vault_id]["market_resafe"] is None
            ):
                first_events[vault_id]["market_resafe"] = step
            if is_oracle_unsafe:
                oracle_unsafe.append(vault)
                if first_events[vault_id]["oracle_unsafe"] is None:
                    first_events[vault_id]["oracle_unsafe"] = step
                oracle_was_unsafe.add(vault_id)
            elif (
                vault_id in oracle_was_unsafe
                and first_events[vault_id]["oracle_resafe"] is None
            ):
                first_events[vault_id]["oracle_resafe"] = step
            debt = float(vault.debt_dai)
            if is_market_unsafe:
                arrays["market_unsafe_debt"][step] += debt
            if is_oracle_unsafe:
                arrays["oracle_unsafe_debt"][step] += debt
            if is_market_unsafe and not is_oracle_unsafe:
                arrays["false_safe_vaults"][step] += 1
                arrays["false_safe_debt"][step] += debt
                family_arrays[family]["false_safe_vaults"][step] += 1
                family_arrays[family]["false_safe_debt"][step] += debt
            if is_oracle_unsafe and not is_market_unsafe:
                arrays["false_unsafe_vaults"][step] += 1
                arrays["false_unsafe_debt"][step] += debt
                family_arrays[family]["false_unsafe_vaults"][step] += 1
                family_arrays[family]["false_unsafe_debt"][step] += debt

        step_config = replace(
            base_liquidation,
            gas_cost=float(gas_costs[step]),
            risk_cost_rate=0.0,
            max_close_factor=1.0,
            max_liquidations_per_step=CAPACITY,
        )
        ranked = rank_liquidation_candidates(
            oracle_unsafe,
            prices=oracle_prices,
            config=step_config,
            portfolio=portfolio_config,
        )
        profitable = ranked.loc[ranked["expected_profit"].gt(0.0)].copy()
        new_by_family = Counter()
        for row in ranked.itertuples(index=False):
            vault_id = int(row.vault_id)
            if step >= PRE_SHOCK_HOURS and vault_id not in eligible_seen:
                eligible_seen.add(vault_id)
                debt = float(row.debt_at_risk)
                family = _family(str(row.collateral_type))
                eligible_tab_by_family[family] += debt
                new_by_family[family] += debt
        decision = _demand_decision(
            step=step,
            inventory=len(ranked),
            uniform=float(arrivals["uniforms"][step]),
            positive_count=int(arrivals["positive_counts"][step]),
            hurdle_probability=float(arrivals["hurdle_probability"]),
        )
        demand_selected = ranked.head(decision.bounded_demand)
        selected = ranked.head(decision.attempt_budget)
        rejected = demand_selected.iloc[decision.attempt_budget :]
        attempt_ids = selected["vault_id"].astype(int).tolist()
        duplicate_attempt = duplicate_attempt or len(attempt_ids) != len(
            set(attempt_ids)
        )
        selected_by_family = Counter(
            _family(value) for value in selected["collateral_type"]
        )
        rejected_by_family = Counter(
            _family(value) for value in rejected["collateral_type"]
        )
        eligible_by_family = Counter(
            {
                family: sum(
                    float(row.debt_at_risk)
                    for row in ranked.itertuples(index=False)
                    if _family(str(row.collateral_type)) == family
                )
                for family in FAMILY_ORDER
            }
        )
        executions: list[dict[str, Any]] = []
        for vault_id in attempt_ids:
            vault = vault_by_id[vault_id]
            if first_events[vault_id]["selected"] is None:
                first_events[vault_id]["selected"] = step
            before_collateral = float(vault.collateral_amount)
            before_debt = float(vault.debt_dai)
            result = execute_keeper_liquidation(
                vault,
                oracle_prices,
                step_config,
                portfolio=portfolio_config,
            )
            family = _family(vault.collateral_type)
            result["family"] = family
            result["collateral_removed"] = before_collateral - float(
                vault.collateral_amount
            )
            result["terminal_debt_writeoff"] = max(
                before_debt - float(vault.debt_dai) - float(result["debt_repaid"]),
                0.0,
            )
            if bool(result["fully_liquidated"]):
                if vault_id in closed_ids:
                    duplicate_closure = True
                closed_ids.add(vault_id)
                if first_events[vault_id]["closure"] is None:
                    first_events[vault_id]["closure"] = step
            if bool(result["liquidated"]) and step >= PRE_SHOCK_HOURS:
                liquidated_ids.add(vault_id)
            executions.append(result)
        execution = pd.DataFrame(executions)

        for family in FAMILY_ORDER:
            subset = (
                execution.loc[execution["family"].eq(family)]
                if not execution.empty
                else execution
            )
            successful = (
                subset.loc[subset["liquidated"].astype(bool)]
                if not subset.empty
                else subset
            )
            closures = (
                subset.loc[subset["fully_liquidated"].astype(bool)]
                if not subset.empty
                else subset
            )
            liquidated_debt = (
                float(successful["debt_repaid"].sum()) if not successful.empty else 0.0
            )
            realised_bad_debt = (
                float(closures["bad_debt"].sum()) if not closures.empty else 0.0
            )
            debt_writeoff = (
                float(closures["terminal_debt_writeoff"].sum())
                if not closures.empty
                else 0.0
            )
            collateral_removed = (
                float(successful["collateral_removed"].sum())
                if not successful.empty
                else 0.0
            )
            repaid_debt[family] += liquidated_debt
            terminal_writeoff[family] += debt_writeoff
            removed_collateral[family] += collateral_removed
            backlog = float(
                sum(
                    vault.debt_dai
                    for vault in vaults
                    if vault.is_active
                    and _family(vault.collateral_type) == family
                    and vault.is_liquidatable(oracle_prices)
                )
            )
            active_bad_debt = float(
                sum(
                    vault.bad_debt(oracle_prices)
                    for vault in vaults
                    if vault.is_active and _family(vault.collateral_type) == family
                )
            )
            values = family_arrays[family]
            values["eligible"][step] = eligible_by_family[family]
            values["new_eligible"][step] = new_by_family[family]
            values["selected"][step] = selected_by_family[family]
            values["rejected"][step] = rejected_by_family[family]
            values["closures"][step] = len(closures)
            values["liquidated_debt"][step] = liquidated_debt
            values["backlog"][step] = backlog
            values["active_bad_debt"][step] = active_bad_debt
            values["realised_bad_debt"][step] = realised_bad_debt
            values["keeper_profit"][step] = (
                float(successful["realised_keeper_profit"].sum())
                if not successful.empty
                else 0.0
            )

        arrays["liquidatable_before"][step] = len(ranked)
        arrays["profitability_filtered"][step] = len(profitable)
        arrays["sampled_arrivals"][step] = len(demand_selected)
        arrays["selected_attempts"][step] = len(selected)
        arrays["successful_liquidations"][step] = (
            sum(
                family_arrays[family]["liquidated_debt"][step] > 0
                for family in FAMILY_ORDER
            )
            if execution.empty
            else int(execution["liquidated"].astype(bool).sum())
        )
        arrays["successful_closures"][step] = sum(
            family_arrays[family]["closures"][step] for family in FAMILY_ORDER
        )
        arrays["failed_liquidation_attempts"][step] = (
            len(selected) - arrays["successful_liquidations"][step]
        )
        arrays["capacity_rejected_opportunities"][step] = len(rejected)
        arrays["eligible_tab"][step] = sum(
            family_arrays[family]["eligible"][step] for family in FAMILY_ORDER
        )
        arrays["new_eligible_tab"][step] = sum(new_by_family.values())
        for family_metric, system_metric in (
            ("backlog", "unresolved_tab_dai"),
            ("active_bad_debt", "active_bad_debt_dai"),
            ("realised_bad_debt", "realised_bad_debt_dai"),
            ("liquidated_debt", "cleared_tab_dai"),
            ("keeper_profit", "keeper_profit_dai"),
        ):
            arrays[system_metric][step] = sum(
                family_arrays[family][family_metric][step] for family in FAMILY_ORDER
            )
        arrays["terminal_debt_writeoff_dai"][step] = sum(
            float(row.get("terminal_debt_writeoff", 0.0)) for row in executions
        )
        arrays["liquidation_gate_open"][step] = (
            arrays["unresolved_tab_dai"][step] <= 1e-9
        )
        arrays["material_active_bad_debt"][step] = (
            arrays["active_bad_debt_dai"][step] > 1e-6
        )
        for family_metric, system_metric in (
            ("eligible", "eligible_tab"),
            ("new_eligible", "new_eligible_tab"),
            ("selected", "selected_attempts"),
            ("rejected", "capacity_rejected_opportunities"),
            ("closures", "successful_closures"),
            ("liquidated_debt", "cleared_tab_dai"),
            ("backlog", "unresolved_tab_dai"),
            ("active_bad_debt", "active_bad_debt_dai"),
            ("realised_bad_debt", "realised_bad_debt_dai"),
            ("keeper_profit", "keeper_profit_dai"),
            ("false_safe_vaults", "false_safe_vaults"),
            ("false_safe_debt", "false_safe_debt"),
            ("false_unsafe_vaults", "false_unsafe_vaults"),
            ("false_unsafe_debt", "false_unsafe_debt"),
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
                if vault.is_active and _family(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    final_collateral = {
        family: float(
            sum(
                vault.collateral_amount
                for vault in vaults
                if vault.is_active and _family(vault.collateral_type) == family
            )
        )
        for family in FAMILY_ORDER
    }
    debt_errors = {
        family: initial_debt[family]
        - final_debt[family]
        - repaid_debt[family]
        - terminal_writeoff[family]
        for family in FAMILY_ORDER
    }
    collateral_errors = {
        family: initial_collateral[family]
        - final_collateral[family]
        - removed_collateral[family]
        for family in FAMILY_ORDER
    }
    accounting_valid = bool(
        reconciliation_failures == 0
        and not duplicate_attempt
        and not duplicate_closure
        and all(abs(value) <= 1e-5 for value in debt_errors.values())
        and all(abs(value) <= 1e-5 for value in collateral_errors.values())
    )
    recognition_lags = []
    recovery_staleness = []
    for events in first_events.values():
        if events["market_unsafe"] is not None and events["oracle_unsafe"] is not None:
            recognition_lags.append(
                float(events["oracle_unsafe"] - events["market_unsafe"])
            )
        if events["market_resafe"] is not None and events["oracle_resafe"] is not None:
            recovery_staleness.append(
                float(events["oracle_resafe"] - events["market_resafe"])
            )
    recognition = _event_distribution(recognition_lags)
    recovery = _event_distribution(recovery_staleness)
    post = slice(PRE_SHOCK_HOURS, None)
    total_eligible = float(sum(eligible_tab_by_family.values()))
    cleared = float(arrays["cleared_tab_dai"][post].sum())
    new_tab = arrays["new_eligible_tab"][post]
    busy = np.sort(new_tab)[-5:]
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
            None if total_eligible == 0.0 else cleared / total_eligible
        ),
        "peak_eligible_tab_share": float(
            arrays["eligible_tab"][post].max() / TOTAL_DEBT_DAI
        ),
        "peak_new_eligible_tab_share": float(
            arrays["new_eligible_tab"][post].max() / TOTAL_DEBT_DAI
        ),
        "peak_selected_attempts": int(arrays["selected_attempts"][post].max()),
        "peak_successful_closures": int(arrays["successful_closures"][post].max()),
        "hours_for_half_eligible_tab": _hours_for_half(new_tab),
        "five_busiest_eligible_tab_share": (
            0.0 if total_eligible == 0.0 else float(busy.sum() / total_eligible)
        ),
        "capacity_binding_hours": int(
            np.count_nonzero(arrays["capacity_rejected_opportunities"][post] > 0)
        ),
        "capacity_rejected_opportunity_count": int(
            arrays["capacity_rejected_opportunities"][post].sum()
        ),
        "successful_closure_count": int(arrays["successful_closures"][post].sum()),
        "liquidated_debt_share": cleared / TOTAL_DEBT_DAI,
        "debt_weighted_liquidated_vault_share": float(
            sum(initial_debt_by_vault[vault_id] for vault_id in liquidated_ids)
            / TOTAL_DEBT_DAI
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
        "false_safe_vault_hours": int(arrays["false_safe_vaults"][post].sum()),
        "false_safe_debt_hours": float(arrays["false_safe_debt"][post].sum()),
        "peak_false_safe_debt": float(arrays["false_safe_debt"][post].max()),
        "false_unsafe_vault_hours": int(arrays["false_unsafe_vaults"][post].sum()),
        "false_unsafe_debt_hours": float(arrays["false_unsafe_debt"][post].sum()),
        "peak_false_unsafe_debt": float(arrays["false_unsafe_debt"][post].max()),
        "market_unsafe_debt_not_oracle_eligible_share": (
            0.0
            if arrays["market_unsafe_debt"][post].sum() == 0.0
            else float(
                arrays["false_safe_debt"][post].sum()
                / arrays["market_unsafe_debt"][post].sum()
            )
        ),
        "oracle_unsafe_debt_already_market_safe_share": (
            0.0
            if arrays["oracle_unsafe_debt"][post].sum() == 0.0
            else float(
                arrays["false_unsafe_debt"][post].sum()
                / arrays["oracle_unsafe_debt"][post].sum()
            )
        ),
        "recognition_lag_mean": recognition["mean"],
        "recognition_lag_median": recognition["median"],
        "recovery_staleness_mean": recovery["mean"],
        "recovery_staleness_median": recovery["median"],
        "recognition_lag_not_applicable_count": VAULT_COUNT - int(recognition["count"]),
        "recovery_staleness_not_applicable_count": VAULT_COUNT - int(recovery["count"]),
        "accounting_valid": accounting_valid,
        "reconciliation_failure_count": reconciliation_failures,
        "duplicate_attempt": duplicate_attempt,
        "duplicate_closure": duplicate_closure,
        "shared_capacity_valid": bool(np.all(arrays["selected_attempts"] <= CAPACITY)),
        "nonnegative_backlog_valid": bool(
            np.all(arrays["unresolved_tab_dai"] >= -1e-12)
        ),
        "numerical_valid": bool(
            all(np.isfinite(values).all() for values in arrays.values())
            and all(vault.debt_dai >= 0.0 for vault in vaults)
            and all(vault.collateral_amount >= 0.0 for vault in vaults)
        ),
    }
    collateral_rows: list[dict[str, Any]] = []
    for family in FAMILY_ORDER:
        values = family_arrays[family]
        collateral_rows.append(
            {
                "family": family,
                "initial_debt_exposure": initial_debt[family],
                "false_safe_vault_hours": int(values["false_safe_vaults"][post].sum()),
                "false_safe_debt_hours": float(values["false_safe_debt"][post].sum()),
                "peak_false_safe_debt": float(values["false_safe_debt"][post].max()),
                "false_unsafe_vault_hours": int(
                    values["false_unsafe_vaults"][post].sum()
                ),
                "false_unsafe_debt_hours": float(
                    values["false_unsafe_debt"][post].sum()
                ),
                "peak_false_unsafe_debt": float(
                    values["false_unsafe_debt"][post].max()
                ),
                "eligible_liquidation_tab": float(eligible_tab_by_family[family]),
                "selected_count": int(values["selected"][post].sum()),
                "rejected_count": int(values["rejected"][post].sum()),
                "successful_closure_count": int(values["closures"][post].sum()),
                "liquidated_debt": float(values["liquidated_debt"][post].sum()),
                "terminal_unresolved_tab": float(values["backlog"][-1]),
                "backlog_area": float(values["backlog"][post].sum()),
                "maximum_backlog": float(values["backlog"][post].max()),
                "terminal_active_bad_debt": float(values["active_bad_debt"][-1]),
                "realised_bad_debt": float(values["realised_bad_debt"][post].sum()),
                "keeper_profit_proxy": float(values["keeper_profit"][post].sum()),
            }
        )
    return {
        "arrays": arrays,
        "system_summary": system_summary,
        "collateral_rows": collateral_rows,
        "timing": {"recognition_lag": recognition, "recovery_staleness": recovery},
        "accounting": {
            "passed": accounting_valid,
            "debt_errors": debt_errors,
            "collateral_errors": collateral_errors,
            "reconciliation_failure_count": reconciliation_failures,
        },
    }


def simulate_replication(
    replication: int,
    programme_identity: str | None = None,
    *,
    enforce_registered_core: bool = True,
) -> dict[str, Any]:
    """Run the exact six E cells for one paired replication."""
    programme = load_programme()
    resolved_identity = (
        programme.programme_identity
        if programme_identity is None
        else programme_identity
    )
    if resolved_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Experiment E programme identity changed.")
    if enforce_registered_core:
        _assert_preregistered_identities(resolved_identity)
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
    cells = {cell.identifier: cell for cell in build_cell_registry(programme)}
    cell_rows: list[dict[str, Any]] = []
    collateral_rows: list[dict[str, Any]] = []
    anchor_audits: dict[str, Any] = {}
    timing_audits: dict[str, Any] = {}

    for portfolio, shock in ANCHOR_ORDER:
        market_paths, gas_rows, path_audit = experiment_c.build_treatment_paths(
            streams["sampled_market"], shock
        )
        if not path_audit["path_valid"]:
            raise ValueError(f"Experiment E {portfolio}/{shock} path is invalid.")
        gas = component_gas_costs(
            sampled_market_gas_rows=gas_rows,
            simulated_eth_prices=market_paths["ETH"],
            config=replace(
                resolve_integrated_empirical_eth_profile().gas,
                seed=derive_seed(replication, "keeper_gas_units"),
            ),
        )
        if gas.gas_cost_usd is None or gas.sampled_rows is None:
            raise ValueError("Experiment E gas path is missing.")
        gas_checksum = _payload_sha256(
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
        state = streams["states"][portfolio]
        initial_debt = {
            family: float(
                sum(
                    vault.debt_dai
                    for vault in state.vaults
                    if _family(vault.collateral_type) == family
                )
            )
            for family in FAMILY_ORDER
        }
        treatment_audits: dict[str, Any] = {}
        market_checksum = _payload_sha256(path_audit["full_price_checksums"])
        for delay, treatment in zip(DELAY_ORDER, TREATMENT_ORDER, strict=True):
            identifier = f"{shock}__{portfolio}__{treatment}"
            oracle_paths, oracle_audit = build_oracle_paths(market_paths, delay)
            mismatch_system, mismatch_families = mismatch_diagnostics(
                market_paths, oracle_paths, initial_debt
            )
            liquidation = _simulate_delay_liquidations(
                initialisation=state,
                market_paths=market_paths,
                oracle_paths=oracle_paths,
                gas_costs=np.asarray(gas.gas_cost_usd, dtype="<f8"),
                arrivals=streams["arrivals"],
                portfolio_config=experiment_a._portfolio_config(
                    portfolio, collateral_payload, portfolio_payload
                ),
            )
            market = experiment_a._simulate_market_scenario(
                design=recovery_design,
                definition=full_week,
                eth_prices=market_paths["ETH"],
                liquidation=liquidation["arrays"],
                innovations=streams["residuals"],
                scenario_identifier="stage1_only",
                stage1_owners=streams["stage1"],
                peg_scale=float(scaling["lagged_below_peg_gap"]["positive_q95"]),
                eth_scale=float(scaling["lagged_24h_eth_downside"]["positive_q95"]),
                initial_vault_count=VAULT_COUNT,
            )
            system = {
                **mismatch_system,
                **liquidation["system_summary"],
                **{key: market["summary"][key] for key in PEG_METRICS},
                "cell_order": cells[identifier].order,
                "cell_identifier": identifier,
                "anchor": anchor,
                "portfolio": portfolio,
                "shock": shock,
                "oracle_treatment": treatment,
                "oracle_delay_steps": delay,
                "oracle_delay_hours": delay,
                "capacity": CAPACITY,
                "replication": replication,
                "hurdle": "direct_cost_only",
                "risk_cost_rate": 0.0,
                "confidence": "stage1_only",
                "paired_stream_checksum": streams["paired_stream_checksum"],
                "state_checksum": state.identity,
                "market_path_checksum": market_checksum,
                "gas_component_checksum": gas_checksum,
                "arrival_checksum": streams["arrivals"]["checksum"],
                "residual_checksum": streams["stream_components"]["residual_checksum"],
                "oracle_path_checksum": oracle_audit["combined_checksum"],
                "path_valid": bool(path_audit["path_valid"] and oracle_audit["passed"]),
                "nested_initialisation_valid": streams["nested_audit"]["passed"],
            }
            system["numerical_valid"] = bool(
                system["numerical_valid"]
                and market["summary"]["numerical_valid"]
                and system["path_valid"]
            )
            cell_rows.append(system)
            for family_row in liquidation["collateral_rows"]:
                family = family_row["family"]
                collateral_rows.append(
                    {
                        "cell_order": cells[identifier].order,
                        "cell_identifier": identifier,
                        "anchor": anchor,
                        "portfolio": portfolio,
                        "shock": shock,
                        "oracle_treatment": treatment,
                        "oracle_delay_steps": delay,
                        "replication": replication,
                        "numerical_valid": system["numerical_valid"],
                        "accounting_valid": system["accounting_valid"],
                        "path_valid": system["path_valid"],
                        **mismatch_families[family],
                        **family_row,
                    }
                )
            treatment_audits[treatment] = oracle_audit
            timing_audits[identifier] = liquidation["timing"]
        owner = {
            "state": state.identity,
            "market": market_checksum,
            "gas": gas_checksum,
            "arrivals": streams["arrivals"]["checksum"],
            "residuals": streams["stream_components"]["residual_checksum"],
        }
        anchor_audits[anchor] = {
            "common_random_numbers_valid": True,
            "treatment_neutral_owner_checksum": _payload_sha256(owner),
            "treatment_neutral_owner_checksums": {
                treatment: _payload_sha256(owner) for treatment in TREATMENT_ORDER
            },
            "oracle_path_audits": treatment_audits,
            "only_delay_varies": True,
            "market_contemporaneous": True,
            "gas_contemporaneous": True,
            "dai_residuals_contemporaneous": True,
        }
    if [row["cell_identifier"] for row in cell_rows] != list(CELL_ORDER):
        raise ValueError("Experiment E cell order differs.")
    expected_collateral = [
        (cell, family) for cell in CELL_ORDER for family in FAMILY_ORDER
    ]
    if [
        (row["cell_identifier"], row["family"]) for row in collateral_rows
    ] != expected_collateral:
        raise ValueError("Experiment E collateral order differs.")
    result = {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "programme_identity": resolved_identity,
        "experiment_identity": experiment_identity(resolved_identity),
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
        "timing_audits": timing_audits,
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
        _draw_e_states,
        _audit_nested_initialisations,
        _arrival_stream,
        _prepare_replication_streams,
        build_oracle_paths,
        mismatch_diagnostics,
        _simulate_delay_liquidations,
        simulate_replication,
        experiment_c.build_treatment_paths,
        normalise_collateral_price_paths,
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
            "oracle_registry_identity": ORACLE_REGISTRY_IDENTITY,
            "cell_order": CELL_ORDER,
            "replications": REPLICATIONS,
            "system_metrics": SYSTEM_METRICS,
            "collateral_metrics": COLLATERAL_METRICS,
            "metric_directions": METRIC_DIRECTIONS,
            "materiality_thresholds": MATERIALITY_THRESHOLDS,
        }
    )


def _decision_rules() -> dict[str, Any]:
    return {
        "response_shape": (
            "monotonic_deterioration",
            "threshold_deterioration",
            "non_monotonic_deterioration",
            "no_delay_effect",
            "countervailing_delay_benefit",
            "not_operational",
            "invalid",
        ),
        "E1": (
            "supported",
            "partially_supported",
            "not_supported",
            "not_operational",
            "invalid",
        ),
        "E2_anchor": (
            "delay_friction_supported",
            "delay_friction_partial",
            "timing_shift_without_net_deterioration",
            "countervailing_delay_benefit",
            "no_downstream_delay_effect",
            "not_operational",
            "invalid",
        ),
        "E2": (
            "supported",
            "partially_supported",
            "timing_effect_only",
            "countervailing_effect",
            "not_supported",
            "not_operational",
            "invalid",
        ),
        "E3": (
            "peg_delay_effect_present",
            "peg_delay_effect_partial",
            "peg_unchanged",
            "peg_response_mixed",
            "peg_not_operational",
            "peg_response_invalid",
        ),
        "overall_h2": (
            "H2_oracle_delay_supported",
            "H2_oracle_delay_partially_supported",
            "H2_oracle_mismatch_effect_only",
            "H2_oracle_delay_countervailing_effect",
            "H2_no_clear_oracle_delay_effect",
            "H2_oracle_delay_not_operational",
            "H2_oracle_delay_experiment_invalid",
        ),
        "peg_solvency": (
            "solvency_and_peg_deteriorate_with_delay",
            "solvency_deteriorates_peg_unchanged",
            "peg_deteriorates_solvency_unchanged",
            "solvency_and_peg_diverge",
            "delay_changes_timing_not_terminal_outcomes",
            "neither_materially_changes",
            "relationship_mixed",
            "relationship_invalid",
        ),
    }


def specification_payload(programme_identity: str) -> dict[str, Any]:
    if programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Experiment E programme identity changed.")
    return {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "experiment_e_parent_commit": EXPERIMENT_E_PARENT_COMMIT,
        "programme_identity": programme_identity,
        "scientific_code_identity": scientific_code_identity(),
        "simulation_core_identity": simulation_core_identity(),
        "oracle_registry_identity": ORACLE_REGISTRY_IDENTITY,
        "oracle_registry_sha256": ORACLE_REGISTRY_SHA256,
        "scientific_classification": "transparent_sensitivity_not_empirically_identified",
        "profile": {
            "identifier": "empirical_integrated_multicollateral",
            "identity": PROFILE_IDENTITY,
            "sha256": PROFILE_SHA256,
            "vault_count": VAULT_COUNT,
            "total_debt_dai": TOTAL_DEBT_DAI,
            "target_system_collateral_ratio": TARGET_SYSTEM_COLLATERAL_RATIO,
            "runtime_adopted": False,
        },
        "registry_checksums": {
            "collateral": COLLATERAL_REGISTRY_SHA256,
            "portfolio": PORTFOLIO_REGISTRY_SHA256,
            "shock": SHOCK_REGISTRY_SHA256,
            "keeper": KEEPER_REGISTRY_SHA256,
            "confidence": CONFIDENCE_REGISTRY_SHA256,
            "oracle_delay": ORACLE_REGISTRY_SHA256,
        },
        "research_questions": ("RQ2",),
        "hypotheses": ("H2",),
        "anchors": [
            {"portfolio": portfolio, "shock": shock}
            for portfolio, shock in ANCHOR_ORDER
        ],
        "delays": [
            {"treatment": treatment, "steps": delay, "hours": delay}
            for treatment, delay in zip(TREATMENT_ORDER, DELAY_ORDER, strict=True)
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
            "rmst_cap_hours": 720,
        },
        "common_settings": {
            "capacity": CAPACITY,
            "hurdle": "direct_cost_only",
            "risk_cost_rate": 0.0,
            "confidence": "stage1_only",
            "max_close_factor": 1.0,
        },
        "stage1_owners": {
            "below_peg_response": EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
            "above_peg_response": EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
            "residual_sequence_sha256": EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
            "residual_block_sha256": EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
        },
        "oracle_semantics": {
            "owner": "dai_sim.model.collateral_prices._apply_oracle_delay",
            "global_family_scope": True,
            "initial_price_repetition": True,
            "interpolation": False,
            "market_gas_and_dai_remain_contemporaneous": True,
        },
        "mismatch_definitions": {
            "gap": "log(market_price/oracle_price)",
            "absolute_gap": "abs(gap)",
            "overvaluation_gap": "max(-gap,0)",
            "undervaluation_gap": "max(gap,0)",
            "system_weight": "frozen_initial_debt_share",
        },
        "timing_definitions": {
            "recognition_lag": "first_oracle_unsafe-first_market_unsafe",
            "recovery_staleness": "first_oracle_resafe-first_market_resafe",
            "never_both_states": "not_applicable",
        },
        "system_metrics": SYSTEM_METRICS,
        "collateral_metrics": COLLATERAL_METRICS,
        "metric_directions": METRIC_DIRECTIONS,
        "raw_contrasts": ("delay_1_minus_0", "delay_2_minus_1", "delay_2_minus_0"),
        "direction_normalised_deterioration": True,
        "operationality_classes": (
            "operational",
            "degenerate",
            "not_operational",
            "invalid",
        ),
        "materiality_thresholds": MATERIALITY_THRESHOLDS,
        "decision_rules": _decision_rules(),
        "delay_selection_permitted": False,
        "final_validation_data_used": False,
        "held_out_data_used": False,
        "usdc_svb_used": False,
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
    return None if not path.is_file() else json.loads(path.read_text(encoding="utf-8"))


def _assert_preregistered_identities(programme_identity: str) -> None:
    payload = _registered_specification()
    if payload is None:
        raise ValueError("Experiment E must be pre-registered before execution.")
    if (
        payload.get("programme_identity") != programme_identity
        or payload.get("scientific_code_identity") != scientific_code_identity()
        or payload.get("simulation_core_identity") != simulation_core_identity()
        or payload.get("experiment_identity") != experiment_identity(programme_identity)
    ):
        raise ValueError("Experiment E pre-registered identity changed.")


def write_preregistration(programme_identity: str) -> dict[str, Any]:
    payload = specification_payload(programme_identity)
    identity = experiment_identity(programme_identity)
    specification_bytes = _pretty_json({**payload, "experiment_identity": identity})
    registry_bytes = _csv_bytes(_registry_frame())
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    outputs = (
        (EVIDENCE_DIR / COMPACT_FILENAMES[0], specification_bytes),
        (EVIDENCE_DIR / COMPACT_FILENAMES[1], registry_bytes),
    )
    for path, content in outputs:
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f"Experiment E pre-registration differs: {path.name}.")
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
    snapshots: dict[str, Any] = {}
    for label, (
        module,
        identity,
        evidence_hash,
        checkpoint_hash,
    ) in PROTECTED_EXPERIMENTS.items():
        registered = json.loads(
            (module.EVIDENCE_DIR / module.COMPACT_FILENAMES[0]).read_text(
                encoding="utf-8"
            )
        )
        if registered.get("experiment_identity") != identity:
            raise ValueError(f"Protected Experiment {label.upper()} identity changed.")
        snapshots[f"{label}_evidence"] = _tree_snapshot(module.EVIDENCE_DIR)
        snapshots[f"{label}_checkpoints"] = _tree_snapshot(
            module.OUTPUT_ROOT, "replication_*.json"
        )
        if (
            snapshots[f"{label}_evidence"]["file_count"] != 8
            or snapshots[f"{label}_evidence"]["content_map_sha256"] != evidence_hash
            or snapshots[f"{label}_checkpoints"]["file_count"] != 128
            or snapshots[f"{label}_checkpoints"]["content_map_sha256"]
            != checkpoint_hash
        ):
            raise ValueError(f"Protected Experiment {label.upper()} changed.")
    return {"passed": True, **snapshots}


def _output_dir(programme_identity: str) -> Path:
    return OUTPUT_ROOT / experiment_identity(programme_identity)


def _checkpoint_path(output_dir: Path, replication: int) -> Path:
    return output_dir / "checkpoints" / f"replication_{replication:03d}.json"


def _valid_checkpoint(path: Path, *, replication: int, programme_identity: str) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if (
        payload.get("replication") != replication
        or payload.get("programme_identity") != programme_identity
        or payload.get("experiment_identity") != experiment_identity(programme_identity)
        or payload.get("scientific_code_identity") != scientific_code_identity()
        or payload.get("simulation_count") != len(CELL_ORDER)
        or [row.get("cell_identifier") for row in payload.get("cell_rows", [])]
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
            path, replication=replication, programme_identity=programme_identity
        ):
            valid.append(replication)
        elif path.exists():
            invalid.append(replication)
    expected_names = {
        f"replication_{replication:03d}.json" for replication in range(REPLICATIONS)
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
            "sha256": sha256_file(_checkpoint_path(output_dir, replication)),
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
        "complete": len(valid) == REPLICATIONS and not invalid and not orphans,
    }


def preflight(programme_identity: str) -> dict[str, Any]:
    _assert_preregistered_identities(programme_identity)
    profile_path = (
        REPOSITORY_ROOT / "config/profiles/empirical_integrated_multicollateral.yaml"
    )
    if sha256_file(profile_path) != PROFILE_SHA256:
        raise ValueError("Frozen integrated profile changed.")
    cells = build_cell_registry()
    if len(cells) != 6:
        raise ValueError("Experiment E must contain six cells.")
    streams = _prepare_replication_streams(0)
    path_audits: dict[str, Any] = {}
    for portfolio, shock in ANCHOR_ORDER:
        market_paths, _, audit = experiment_c.build_treatment_paths(
            streams["sampled_market"], shock
        )
        if not audit["path_valid"]:
            raise ValueError(f"Experiment E {shock} path is invalid.")
        delay_audits = {}
        for delay in DELAY_ORDER:
            _, delay_audits[str(delay)] = build_oracle_paths(market_paths, delay)
        path_audits[f"{portfolio}__{shock}"] = {
            "market": audit,
            "oracle": delay_audits,
        }
    free_bytes = shutil.disk_usage(REPOSITORY_ROOT).free
    if free_bytes < MINIMUM_FREE_BYTES:
        raise ValueError("Less than 10 GiB free before Experiment E.")
    return {
        "passed": True,
        "programme_identity": programme_identity,
        "experiment_identity": experiment_identity(programme_identity),
        "scientific_code_identity": scientific_code_identity(),
        "simulation_core_identity": simulation_core_identity(),
        "cell_count": len(cells),
        "replications": REPLICATIONS,
        "substantive_simulations": len(cells) * REPLICATIONS,
        "nested_initialisation": streams["nested_audit"],
        "path_audits": path_audits,
        "regression_audit": regression_audit(),
        "free_bytes": free_bytes,
        "output_cap_bytes": MAXIMUM_OUTPUT_BYTES,
        "experiments_a_b_c_d_simulations": 0,
        "held_out_data_used": False,
        "delay_selection_permitted": False,
        "runtime_adopted": False,
    }


def run_smoke(replication: int = 0) -> dict[str, Any]:
    result = simulate_replication(
        replication, MASTER_PROGRAMME_IDENTITY, enforce_registered_core=True
    )
    if not all(
        audit["common_random_numbers_valid"]
        and audit["only_delay_varies"]
        and all(item["passed"] for item in audit["oracle_path_audits"].values())
        for audit in result["anchor_audits"].values()
    ):
        raise ValueError("Experiment E smoke CRN or oracle-path audit failed.")
    if not all(
        row["numerical_valid"] and row["accounting_valid"] and row["path_valid"]
        for row in result["cell_rows"]
    ):
        raise ValueError("Experiment E smoke validity failed.")
    zero_rows = [row for row in result["cell_rows"] if row["oracle_delay_steps"] == 0]
    if any(
        abs(row["debt_weighted_absolute_mismatch_area"]) > MISMATCH_TOLERANCE
        for row in zero_rows
    ):
        raise ValueError("Experiment E zero-delay mismatch is not structural zero.")
    return {
        "passed": True,
        "replication": replication,
        "simulation_count": result["simulation_count"],
        "result_checksum": result["result_checksum"],
        "anchor_audits": result["anchor_audits"],
        "conclusions_inspected": False,
    }


def _worker_initialiser() -> None:
    multiprocessing.current_process().authkey = b"dai-sim-experiment-e"


def _run_one(replication: int, programme_identity: str) -> dict[str, Any]:
    started = time.perf_counter()
    result = simulate_replication(
        replication, programme_identity, enforce_registered_core=True
    )
    result["worker_elapsed_seconds"] = time.perf_counter() - started
    return result


def run_matrix(
    *, programme_identity: str, workers: int, resume: bool = False
) -> dict[str, Any]:
    _assert_preregistered_identities(programme_identity)
    output_dir = _output_dir(programme_identity)
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    before = audit_checkpoints(programme_identity)
    if before["invalid_count"] or before["orphan_count"]:
        raise ValueError("Experiment E checkpoint audit failed before execution.")
    if before["valid_count"] and not resume:
        raise ValueError("Valid Experiment E checkpoints exist; use resume.")
    pending = [
        replication
        for replication in range(REPLICATIONS)
        if replication not in before["valid_replications"]
    ]
    completed: list[int] = []
    failures: dict[int, str] = {}
    started = time.perf_counter()
    if pending:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_worker_initialiser,
        ) as executor:
            futures = {
                executor.submit(_run_one, replication, programme_identity): replication
                for replication in pending
            }
            for future in as_completed(futures):
                replication = futures[future]
                try:
                    result = future.result()
                    _atomic_json(_checkpoint_path(output_dir, replication), result)
                    if not _valid_checkpoint(
                        _checkpoint_path(output_dir, replication),
                        replication=replication,
                        programme_identity=programme_identity,
                    ):
                        raise ValueError(
                            "Persisted Experiment E checkpoint is invalid."
                        )
                    completed.append(replication)
                except (
                    Exception
                ) as exc:  # pragma: no cover - exercised by worker failure
                    failures[replication] = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    after = audit_checkpoints(programme_identity)
    if failures:
        raise RuntimeError(f"Experiment E worker failures: {failures}")
    if not after["complete"]:
        raise ValueError("Experiment E checkpoint matrix is incomplete.")
    if after["checkpoint_bytes"] > MAXIMUM_OUTPUT_BYTES:
        raise ValueError("Experiment E detailed output exceeds 500 MB.")
    return {
        "output_dir": _relative(output_dir),
        "workers": workers,
        "elapsed_seconds": elapsed,
        "completed_replications": len(completed),
        "reused_replications": before["valid_count"],
        "resumed_replications": before["valid_count"] if resume else 0,
        "failed_replications": 0,
        "rerun_replications": 0,
        "completed_simulations": len(CELL_ORDER) * REPLICATIONS,
        "checkpoint_audit": after,
    }


def load_results(programme_identity: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    audit = audit_checkpoints(programme_identity)
    if not audit["complete"]:
        raise ValueError("Experiment E checkpoints are incomplete.")
    cell_rows: list[dict[str, Any]] = []
    collateral_rows: list[dict[str, Any]] = []
    for replication in range(REPLICATIONS):
        payload = json.loads(
            _checkpoint_path(_output_dir(programme_identity), replication).read_text(
                encoding="utf-8"
            )
        )
        cell_rows.extend(payload["cell_rows"])
        collateral_rows.extend(payload["collateral_rows"])
    cells = (
        pd.DataFrame(cell_rows)
        .sort_values(["cell_order", "replication"])
        .reset_index(drop=True)
    )
    collateral = pd.DataFrame(collateral_rows)
    family_order = {family: index for index, family in enumerate(FAMILY_ORDER)}
    collateral["_family_order"] = collateral["family"].map(family_order)
    collateral = (
        collateral.sort_values(["cell_order", "_family_order", "replication"])
        .drop(columns="_family_order")
        .reset_index(drop=True)
    )
    if len(cells) != len(CELL_ORDER) * REPLICATIONS or len(collateral) != len(
        CELL_ORDER
    ) * REPLICATIONS * len(FAMILY_ORDER):
        raise ValueError("Experiment E reconstructed result dimensions differ.")
    return cells, collateral


def _distribution(values: Iterable[float]) -> dict[str, float]:
    return experiment_d._distribution(values)


def classify_metric_operationality(
    values: Iterable[float | None], *, valid: bool = True
) -> str:
    if not valid:
        return "invalid"
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce")
    finite = series[np.isfinite(series)]
    if finite.empty:
        return "not_operational"
    if float(finite.max() - finite.min()) <= MISMATCH_TOLERANCE:
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
            finite = pd.to_numeric(selected[metric], errors="coerce")
            finite = finite[np.isfinite(finite)]
            rows.append(
                {
                    "cell_order": cell.order,
                    "cell_identifier": cell.identifier,
                    "anchor": f"{cell.portfolio}__{cell.shock}",
                    "portfolio": cell.portfolio,
                    "shock": cell.shock,
                    "oracle_treatment": cell.treatment,
                    "oracle_delay_steps": cell.delay_steps,
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
            for metric_order, metric in enumerate(COLLATERAL_METRICS, start=1):
                finite = pd.to_numeric(selected[metric], errors="coerce")
                finite = finite[np.isfinite(finite)]
                rows.append(
                    {
                        "cell_order": cell.order,
                        "cell_identifier": cell.identifier,
                        "anchor": f"{cell.portfolio}__{cell.shock}",
                        "portfolio": cell.portfolio,
                        "shock": cell.shock,
                        "oracle_treatment": cell.treatment,
                        "oracle_delay_steps": cell.delay_steps,
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
    left_delay: int,
    right_delay: int,
    family: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    selected = frame.loc[frame["anchor"].eq(anchor)]
    if family is not None:
        selected = selected.loc[selected["family"].eq(family)]
    left = selected.loc[
        selected["oracle_delay_steps"].eq(left_delay), ["replication", metric]
    ].rename(columns={metric: "left"})
    right = selected.loc[
        selected["oracle_delay_steps"].eq(right_delay), ["replication", metric]
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
    order: int,
    contrast_type: str,
    anchor: str,
    family: str | None,
    metric: str,
    left_delay: int,
    right_delay: int,
    direction: int,
    values: np.ndarray,
    operationality: str,
) -> dict[str, Any]:
    return {
        "contrast_order": order,
        "contrast_type": contrast_type,
        "anchor": anchor,
        "family": family,
        "metric": metric,
        "left_delay": left_delay,
        "right_delay": right_delay,
        "contrast_label": f"delay_{right_delay}_minus_{left_delay}",
        "direction_multiplier": direction,
        "operationality": operationality,
        "count": int(len(values)),
        **_distribution(values),
        "discordant_positive": int(np.count_nonzero(values > 0.0)),
        "discordant_negative": int(np.count_nonzero(values < 0.0)),
    }


def classify_response_shape(
    zero_one: Mapping[str, Any],
    one_two: Mapping[str, Any],
    zero_two: Mapping[str, Any],
    *,
    operationality: str,
    valid: bool = True,
) -> str:
    if not valid or operationality == "invalid":
        return "invalid"
    if operationality != "operational":
        return "not_operational"
    if float(zero_two["ci95_upper"]) < 0.0:
        return "countervailing_delay_benefit"
    overall_adverse = float(zero_two["ci95_lower"]) > 0.0
    adjacent_benefit = (
        float(zero_one["ci95_upper"]) < 0.0 or float(one_two["ci95_upper"]) < 0.0
    )
    if overall_adverse and adjacent_benefit:
        return "non_monotonic_deterioration"
    adjacent_adverse = float(zero_one["mean"]) >= 0.0 and float(one_two["mean"]) >= 0.0
    adjacent_clear = (
        float(zero_one["ci95_lower"]) > 0.0 and float(one_two["ci95_lower"]) > 0.0
    )
    if overall_adverse and adjacent_adverse and adjacent_clear:
        return "monotonic_deterioration"
    if overall_adverse and not adjacent_benefit:
        return "threshold_deterioration"
    return "no_delay_effect"


def paired_contrasts(system: pd.DataFrame, collateral: pd.DataFrame) -> pd.DataFrame:
    operationality = metric_operationality(system)
    rows: list[dict[str, Any]] = []
    order = 0
    pairs = ((0, 1), (1, 2), (0, 2))
    for portfolio, shock in ANCHOR_ORDER:
        anchor = f"{portfolio}__{shock}"
        for metric in SYSTEM_METRICS:
            deterioration_records: dict[tuple[int, int], dict[str, Any]] = {}
            for left_delay, right_delay in pairs:
                left, right = _paired_values(
                    system,
                    anchor=anchor,
                    metric=metric,
                    left_delay=left_delay,
                    right_delay=right_delay,
                )
                raw = right - left
                deterioration = raw * METRIC_DIRECTIONS[metric]
                order += 1
                rows.append(
                    _contrast_record(
                        order=order,
                        contrast_type="raw_delay_contrast",
                        anchor=anchor,
                        family=None,
                        metric=metric,
                        left_delay=left_delay,
                        right_delay=right_delay,
                        direction=1,
                        values=raw,
                        operationality=operationality[metric],
                    )
                )
                order += 1
                record = _contrast_record(
                    order=order,
                    contrast_type="direction_normalised_deterioration",
                    anchor=anchor,
                    family=None,
                    metric=metric,
                    left_delay=left_delay,
                    right_delay=right_delay,
                    direction=METRIC_DIRECTIONS[metric],
                    values=deterioration,
                    operationality=operationality[metric],
                )
                rows.append(record)
                deterioration_records[(left_delay, right_delay)] = record
            order += 1
            rows.append(
                {
                    **deterioration_records[(0, 2)],
                    "contrast_order": order,
                    "contrast_type": "response_shape_classification",
                    "classification": classify_response_shape(
                        deterioration_records[(0, 1)],
                        deterioration_records[(1, 2)],
                        deterioration_records[(0, 2)],
                        operationality=operationality[metric],
                    ),
                }
            )
        for family in FAMILY_ORDER:
            for metric in COLLATERAL_METRICS:
                for left_delay, right_delay in pairs:
                    left, right = _paired_values(
                        collateral,
                        anchor=anchor,
                        family=family,
                        metric=metric,
                        left_delay=left_delay,
                        right_delay=right_delay,
                    )
                    order += 1
                    rows.append(
                        _contrast_record(
                            order=order,
                            contrast_type="collateral_delay_contrast",
                            anchor=anchor,
                            family=family,
                            metric=metric,
                            left_delay=left_delay,
                            right_delay=right_delay,
                            direction=1,
                            values=right - left,
                            operationality="operational"
                            if len(left)
                            else "not_operational",
                        )
                    )
    return (
        pd.DataFrame(rows)
        .sort_values("contrast_order", kind="mergesort")
        .reset_index(drop=True)
    )


def _contrast_lookup(
    contrasts: pd.DataFrame, *, anchor: str, metric: str
) -> dict[str, Any]:
    selected = contrasts.loc[
        contrasts["contrast_type"].eq("direction_normalised_deterioration")
        & contrasts["anchor"].eq(anchor)
        & contrasts["metric"].eq(metric)
        & contrasts["left_delay"].eq(0)
        & contrasts["right_delay"].eq(2)
        & contrasts["family"].isna()
    ]
    if len(selected) != 1:
        raise ValueError(f"Expected one Experiment E contrast for {anchor}/{metric}.")
    return selected.iloc[0].to_dict()


def _clear_adverse(record: Mapping[str, Any]) -> bool:
    return (
        str(record["operationality"]) == "operational"
        and float(record["ci95_lower"]) > 0.0
    )


def _clear_beneficial(record: Mapping[str, Any]) -> bool:
    return (
        str(record["operationality"]) == "operational"
        and float(record["ci95_upper"]) < 0.0
    )


def classify_e1(anchor_rules: Mapping[str, bool | None], *, valid: bool = True) -> str:
    if not valid:
        return "invalid"
    values = list(anchor_rules.values())
    if all(value is None for value in values):
        return "not_operational"
    supported = sum(value is True for value in values)
    if supported == len(values):
        return "supported"
    if supported == 1 or (
        supported == 0 and all(value is not False for value in values)
    ):
        return "partially_supported"
    return "not_supported"


def classify_e2_anchor(
    *,
    adverse_count: int,
    beneficial_count: int,
    timing_changed: bool,
    operational_count: int,
    valid: bool = True,
) -> str:
    if not valid:
        return "invalid"
    if operational_count == 0:
        return "not_operational"
    if beneficial_count:
        return "countervailing_delay_benefit"
    if adverse_count >= 2:
        return "delay_friction_supported"
    if adverse_count == 1:
        return "delay_friction_partial"
    if timing_changed:
        return "timing_shift_without_net_deterioration"
    return "no_downstream_delay_effect"


def classify_e2(anchor_statuses: Mapping[str, str], *, valid: bool = True) -> str:
    if not valid or "invalid" in anchor_statuses.values():
        return "invalid"
    values = list(anchor_statuses.values())
    if all(value == "not_operational" for value in values):
        return "not_operational"
    if any(value == "countervailing_delay_benefit" for value in values):
        return "countervailing_effect"
    if all(value == "delay_friction_supported" for value in values):
        return "supported"
    if any(value == "delay_friction_supported" for value in values) or all(
        value == "delay_friction_partial" for value in values
    ):
        return "partially_supported"
    if any(value == "timing_shift_without_net_deterioration" for value in values):
        return "timing_effect_only"
    return "not_supported"


def classify_e3(
    *,
    adverse_count: int,
    beneficial_count: int,
    operational_count: int,
    valid: bool = True,
) -> str:
    if not valid:
        return "peg_response_invalid"
    if operational_count == 0:
        return "peg_not_operational"
    if adverse_count >= 2 and beneficial_count == 0:
        return "peg_delay_effect_present"
    if adverse_count == 1 and beneficial_count == 0:
        return "peg_delay_effect_partial"
    if beneficial_count and adverse_count:
        return "peg_response_mixed"
    return "peg_unchanged"


def classify_overall_h2(e1: str, e2: str, e3: str, *, valid: bool = True) -> str:
    if not valid or "invalid" in (e1, e2) or e3 == "peg_response_invalid":
        return "H2_oracle_delay_experiment_invalid"
    if e1 == "not_operational" and e2 == "not_operational":
        return "H2_oracle_delay_not_operational"
    if (
        e1 == "supported"
        and e2 == "supported"
        and e3 in {"peg_delay_effect_present", "peg_delay_effect_partial"}
    ):
        return "H2_oracle_delay_supported"
    if e1 == "supported" and e2 == "countervailing_effect":
        return "H2_oracle_delay_countervailing_effect"
    if (
        e1 == "supported"
        and e2 == "not_supported"
        and e3 in {"peg_unchanged", "peg_not_operational"}
    ):
        return "H2_oracle_mismatch_effect_only"
    if e1 == "supported" and e2 in {
        "supported",
        "partially_supported",
        "timing_effect_only",
    }:
        return "H2_oracle_delay_partially_supported"
    return "H2_no_clear_oracle_delay_effect"


def _validity_audit(
    system: pd.DataFrame, collateral: pd.DataFrame, programme_identity: str
) -> dict[str, Any]:
    cell_failures = {}
    for cell in CELL_ORDER:
        selected = system.loc[system["cell_identifier"].eq(cell)]
        failures = int(
            (~selected["numerical_valid"].astype(bool)).sum()
            + (~selected["accounting_valid"].astype(bool)).sum()
            + (~selected["path_valid"].astype(bool)).sum()
        )
        cell_failures[cell] = failures
    checkpoint = audit_checkpoints(programme_identity)
    passed = bool(
        all(
            count / REPLICATIONS <= MATERIALITY_THRESHOLDS["failure_share_invalid"]
            for count in cell_failures.values()
        )
        and collateral["numerical_valid"].astype(bool).all()
        and checkpoint["complete"]
    )
    return {
        "passed": passed,
        "cell_failure_counts": cell_failures,
        "checkpoint_complete": checkpoint["complete"],
        "held_out_data_used": False,
        "usdc_svb_used": False,
        "delay_selected": False,
    }


def _find_contrast(
    contrasts: pd.DataFrame,
    *,
    anchor: str,
    metric: str,
    left: int,
    right: int,
) -> dict[str, Any]:
    selected = contrasts.loc[
        contrasts["contrast_type"].eq("direction_normalised_deterioration")
        & contrasts["anchor"].eq(anchor)
        & contrasts["metric"].eq(metric)
        & contrasts["left_delay"].eq(left)
        & contrasts["right_delay"].eq(right)
        & contrasts["family"].isna()
    ]
    if len(selected) != 1:
        raise ValueError(
            f"Missing Experiment E contrast {anchor}/{metric}/{left}/{right}."
        )
    return selected.iloc[0].to_dict()


def classify_peg_solvency(e2: str, e3: str, *, valid: bool = True) -> str:
    if not valid:
        return "relationship_invalid"
    solvency_worse = e2 in {"supported", "partially_supported"}
    timing_only = e2 == "timing_effect_only"
    peg_worse = e3 in {"peg_delay_effect_present", "peg_delay_effect_partial"}
    if solvency_worse and peg_worse:
        return "solvency_and_peg_deteriorate_with_delay"
    if solvency_worse and e3 in {"peg_unchanged", "peg_not_operational"}:
        return "solvency_deteriorates_peg_unchanged"
    if not solvency_worse and peg_worse:
        return "peg_deteriorates_solvency_unchanged"
    if timing_only and not peg_worse:
        return "delay_changes_timing_not_terminal_outcomes"
    if e2 == "not_supported" and e3 in {"peg_unchanged", "peg_not_operational"}:
        return "neither_materially_changes"
    if e2 == "countervailing_effect" and peg_worse:
        return "solvency_and_peg_diverge"
    return "relationship_mixed"


def classify_results(
    system: pd.DataFrame,
    collateral: pd.DataFrame,
    contrasts: pd.DataFrame,
    programme_identity: str,
) -> dict[str, Any]:
    validity = _validity_audit(system, collateral, programme_identity)
    operationality = metric_operationality(system)
    e1_rules: dict[str, bool | None] = {}
    e2_anchors: dict[str, str] = {}
    e3_anchors: dict[str, str] = {}
    for portfolio, shock in ANCHOR_ORDER:
        anchor = f"{portfolio}__{shock}"
        mismatch01 = _find_contrast(
            contrasts,
            anchor=anchor,
            metric="debt_weighted_absolute_mismatch_area",
            left=0,
            right=1,
        )
        mismatch12 = _find_contrast(
            contrasts,
            anchor=anchor,
            metric="debt_weighted_absolute_mismatch_area",
            left=1,
            right=2,
        )
        mismatch02 = _find_contrast(
            contrasts,
            anchor=anchor,
            metric="debt_weighted_absolute_mismatch_area",
            left=0,
            right=2,
        )
        recognition = _find_contrast(
            contrasts,
            anchor=anchor,
            metric="false_safe_debt_hours",
            left=0,
            right=2,
        )
        zero = system.loc[
            system["anchor"].eq(anchor) & system["oracle_delay_steps"].eq(0),
            "debt_weighted_absolute_mismatch_area",
        ]
        if mismatch02["operationality"] not in {"operational", "degenerate"}:
            e1_rules[anchor] = None
        else:
            e1_rules[anchor] = bool(
                float(mismatch01["mean"]) > 0.0
                and float(mismatch12["mean"]) > 0.0
                and float(mismatch02["ci95_lower"]) > 0.0
                and (float(recognition["mean"]) > 0.0 or _clear_adverse(recognition))
                and float(zero.abs().max()) <= MISMATCH_TOLERANCE
            )
        downstream_metrics = (
            "backlog_area_share",
            "maximum_unresolved_tab_share",
            "terminal_unresolved_tab_share",
            "liquidation_completion_ratio",
            "false_safe_debt_hours",
            "peak_eligible_tab_share",
            "five_busiest_eligible_tab_share",
            "capacity_rejected_opportunity_count",
            "liquidated_debt_share",
        )
        records = [
            _contrast_lookup(contrasts, anchor=anchor, metric=metric)
            for metric in downstream_metrics
        ]
        operational_records = [
            record for record in records if record["operationality"] == "operational"
        ]
        bad_debt_records = [
            _contrast_lookup(contrasts, anchor=anchor, metric=metric)
            for metric in BAD_DEBT_METRICS
            if operationality[metric] == "operational"
        ]
        e2_anchors[anchor] = classify_e2_anchor(
            adverse_count=sum(_clear_adverse(record) for record in operational_records),
            beneficial_count=sum(
                _clear_beneficial(record)
                for record in [*operational_records, *bad_debt_records]
            ),
            timing_changed=any(
                abs(float(record["mean"])) > MISMATCH_TOLERANCE
                for record in operational_records
                if record["metric"]
                in {
                    "false_safe_debt_hours",
                    "peak_eligible_tab_share",
                    "five_busiest_eligible_tab_share",
                }
            ),
            operational_count=len(operational_records),
            valid=validity["passed"],
        )
        peg_records = [
            _contrast_lookup(contrasts, anchor=anchor, metric=metric)
            for metric in PEG_METRICS
        ]
        peg_operational = [
            record
            for record in peg_records
            if record["operationality"] == "operational"
        ]
        e3_anchors[anchor] = classify_e3(
            adverse_count=sum(_clear_adverse(record) for record in peg_operational),
            beneficial_count=sum(
                _clear_beneficial(record) for record in peg_operational
            ),
            operational_count=len(peg_operational),
            valid=validity["passed"],
        )
    e1 = classify_e1(e1_rules, valid=validity["passed"])
    e2 = classify_e2(e2_anchors, valid=validity["passed"])
    if not validity["passed"] or any(
        value == "peg_response_invalid" for value in e3_anchors.values()
    ):
        e3 = "peg_response_invalid"
    elif all(value == "peg_not_operational" for value in e3_anchors.values()):
        e3 = "peg_not_operational"
    elif all(value == "peg_delay_effect_present" for value in e3_anchors.values()):
        e3 = "peg_delay_effect_present"
    elif any(
        value in {"peg_delay_effect_present", "peg_delay_effect_partial"}
        for value in e3_anchors.values()
    ):
        e3 = "peg_delay_effect_partial"
    elif any(value == "peg_response_mixed" for value in e3_anchors.values()):
        e3 = "peg_response_mixed"
    else:
        e3 = "peg_unchanged"
    overall = classify_overall_h2(e1, e2, e3, valid=validity["passed"])
    sensitivity: dict[str, str] = {}
    first_anchor = f"{ANCHOR_ORDER[0][0]}__{ANCHOR_ORDER[0][1]}"
    second_anchor = f"{ANCHOR_ORDER[1][0]}__{ANCHOR_ORDER[1][1]}"
    for metric in (*MISMATCH_METRICS, *LIQUIDATION_METRICS):
        first = abs(
            float(
                _contrast_lookup(contrasts, anchor=first_anchor, metric=metric)["mean"]
            )
        )
        second = abs(
            float(
                _contrast_lookup(contrasts, anchor=second_anchor, metric=metric)["mean"]
            )
        )
        tolerance = max(abs(first), abs(second), 1.0) * 1e-9
        if abs(first - second) <= tolerance:
            sensitivity[metric] = "similar_sensitivity"
        elif first > second:
            sensitivity[metric] = "crypto_anchor_more_sensitive"
        else:
            sensitivity[metric] = "crypto_stable_anchor_more_sensitive"
    sensitivity["overall"] = (
        next(iter(set(sensitivity.values())))
        if len(set(sensitivity.values())) == 1
        else "metric_specific"
    )
    return {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "experiment_identity": experiment_identity(programme_identity),
        "programme_identity": programme_identity,
        "metric_operationality": operationality,
        "path_validation": {
            "passed": validity["passed"],
            "delay_zero_structural_zero": True,
        },
        "anchor_e1_rules": e1_rules,
        "anchor_downstream_statuses": e2_anchors,
        "anchor_peg_statuses": e3_anchors,
        "E1": {"classification": e1},
        "E2": {"classification": e2},
        "E3": {"classification": e3},
        "cross_anchor_sensitivity": sensitivity,
        "overall_h2_classification": overall,
        "peg_solvency_relationship": classify_peg_solvency(
            e2, e3, valid=validity["passed"]
        ),
        "bad_debt_evaluation_boundary": {
            **{metric: operationality[metric] for metric in BAD_DEBT_METRICS},
            "interpretation": "Degenerate bad-debt outcomes are excluded under the retained close-factor-one boundary.",
        },
        "validity_audit": validity,
        "scientific_classification": "transparent_sensitivity_not_empirically_identified",
        "preferred_delay": None,
        "delay_selected": False,
        "next_authorised_stage": "pre_registered_h4_recovery_and_behavioural_stabilisation_synthesis",
        "runtime_adopted": False,
    }


def _load_checkpoints(programme_identity: str) -> list[dict[str, Any]]:
    return [
        json.loads(
            _checkpoint_path(_output_dir(programme_identity), replication).read_text(
                encoding="utf-8"
            )
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
        raise ValueError("Experiment E benchmark is incomplete.")
    if int(benchmark["completed_simulations"]) != len(CELL_ORDER) * REPLICATIONS:
        raise ValueError("Experiment E benchmark simulation count differs.")


def build_evidence_payloads(
    programme_identity: str, benchmark: Mapping[str, Any]
) -> dict[str, bytes]:
    _assert_preregistered_identities(programme_identity)
    _benchmark_validate(benchmark)
    system, collateral = load_results(programme_identity)
    cells = cell_summary(system)
    collateral_cells = collateral_summary(collateral)
    contrasts = paired_contrasts(system, collateral)
    decision = classify_results(system, collateral, contrasts, programme_identity)
    checkpoints = _load_checkpoints(programme_identity)
    crn_failures = [
        {"replication": payload["replication"], "anchor": anchor}
        for payload in checkpoints
        for anchor, audit in payload["anchor_audits"].items()
        if not (
            audit["common_random_numbers_valid"]
            and audit["only_delay_varies"]
            and len(set(audit["treatment_neutral_owner_checksums"].values())) == 1
        )
    ]
    oracle_failures = [
        {
            "replication": payload["replication"],
            "anchor": anchor,
            "treatment": treatment,
        }
        for payload in checkpoints
        for anchor, audit in payload["anchor_audits"].items()
        for treatment, path in audit["oracle_path_audits"].items()
        if not path["passed"]
    ]
    result_frames = {
        COMPACT_FILENAMES[2]: _csv_bytes(cells),
        COMPACT_FILENAMES[3]: _csv_bytes(collateral_cells),
        COMPACT_FILENAMES[4]: _csv_bytes(contrasts),
        COMPACT_FILENAMES[5]: _pretty_json(decision),
    }
    audit = audit_checkpoints(programme_identity)
    regression = regression_audit()
    reproducibility = {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "experiment_identity": experiment_identity(programme_identity),
        "programme_identity": programme_identity,
        "oracle_registry_identity": ORACLE_REGISTRY_IDENTITY,
        "scientific_code_identity": scientific_code_identity(),
        "simulation_core_identity": simulation_core_identity(),
        "seed_registry_sha256": seed_registry_checksum(),
        "crn_audit": {
            "passed": not crn_failures,
            "failure_count": len(crn_failures),
            "failures": crn_failures,
        },
        "oracle_path_audit": {
            "passed": not oracle_failures,
            "failure_count": len(oracle_failures),
            "failures": oracle_failures,
        },
        "checkpoint_audit": audit,
        "completed_simulations": len(CELL_ORDER) * REPLICATIONS,
        "result_checksums": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in result_frames.items()
        },
        "protected_regression_audit": regression,
        "experiments_a_b_c_d_unchanged": regression["passed"],
        "held_out_data_used": False,
        "usdc_svb_used": False,
        "delay_selected": False,
        "parameter_recalibration_runs": 0,
        "runtime_adopted": False,
        "deterministic_reconstruction": True,
    }
    specification = EVIDENCE_DIR / COMPACT_FILENAMES[0]
    registry = EVIDENCE_DIR / COMPACT_FILENAMES[1]
    if not specification.is_file() or not registry.is_file():
        raise ValueError("Experiment E pre-registration files are missing.")
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
            "classification": "pre_registered_final_oracle_delay_experiment",
            "path": _relative(path),
            "runtime_adopted": False,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in paths
    ]


def update_experiment_manifest(records: Sequence[Mapping[str, Any]]) -> None:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    owned_paths = {_relative(EVIDENCE_DIR / name) for name in COMPACT_FILENAMES}
    preserved = sorted(
        (row for row in payload["artefacts"] if str(row["path"]) not in owned_paths),
        key=lambda row: str(row["path"]),
    )
    if len(preserved) != 59:
        raise ValueError("Experiment E expected 59 preserved manifest artefacts.")
    if {str(row["path"]) for row in records} != owned_paths:
        raise ValueError("Experiment E manifest ownership differs.")
    combined = sorted(
        [*preserved, *map(dict, records)], key=lambda row: str(row["path"])
    )
    if len({str(row["path"]) for row in combined}) != len(combined):
        raise ValueError("Experiment manifest contains duplicate paths.")
    payload["artefacts"] = combined
    payload["artefact_count"] = len(combined)
    if payload["artefact_count"] != 67:
        raise ValueError("Experiment manifest must contain 67 artefacts.")
    _atomic_json(MANIFEST_PATH, payload)


def write_evidence(
    programme_identity: str, benchmark: Mapping[str, Any]
) -> dict[str, Any]:
    checkpoint_before = audit_checkpoints(programme_identity)
    if not checkpoint_before["complete"]:
        raise ValueError("Experiment E checkpoints are incomplete.")
    first = build_evidence_payloads(programme_identity, benchmark)
    second = build_evidence_payloads(programme_identity, benchmark)
    for name in DETERMINISTIC_FILENAMES:
        if first[name] != second[name]:
            raise ValueError(f"Experiment E evidence differs: {name}.")
    with (
        tempfile.TemporaryDirectory(
            prefix="experiment-e-evidence-first-"
        ) as first_name,
        tempfile.TemporaryDirectory(
            prefix="experiment-e-evidence-second-"
        ) as second_name,
    ):
        for directory, payloads in zip(
            (Path(first_name), Path(second_name)), (first, second), strict=True
        ):
            for name, payload in payloads.items():
                _atomic_bytes(directory / name, payload)
        for name in DETERMINISTIC_FILENAMES:
            if (Path(first_name) / name).read_bytes() != (
                Path(second_name) / name
            ).read_bytes():
                raise ValueError(
                    f"Isolated Experiment E reconstruction differs: {name}."
                )
    if audit_checkpoints(programme_identity) != checkpoint_before:
        raise ValueError("Experiment E evidence changed checkpoints.")
    for name, payload in first.items():
        path = EVIDENCE_DIR / name
        if (
            path.exists()
            and path.read_bytes() != payload
            and name in COMPACT_FILENAMES[:2]
        ):
            raise ValueError("Experiment E pre-registration changed.")
        _atomic_bytes(path, payload)
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    update_experiment_manifest(_manifest_records(paths))
    return {
        "experiment_identity": experiment_identity(programme_identity),
        "artefact_count": len(paths),
        "artefact_checksums": {path.name: sha256_file(path) for path in paths},
        "deterministic_reconstruction": True,
        "checkpoint_content_unchanged": True,
    }


def validate_evidence(programme_identity: str) -> dict[str, Any]:
    _assert_preregistered_identities(programme_identity)
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    if not all(path.is_file() for path in paths):
        raise ValueError("Experiment E compact evidence is incomplete.")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("artefact_count") != 67:
        raise ValueError("Experiment manifest count differs after Experiment E.")
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
        registry["identifier"].tolist() != list(CELL_ORDER)
        or len(cells) != len(CELL_ORDER) * len(SYSTEM_METRICS)
        or len(collateral)
        != len(CELL_ORDER) * len(FAMILY_ORDER) * len(COLLATERAL_METRICS)
        or contrasts.empty
        or decision["preferred_delay"] is not None
        or decision["runtime_adopted"]
        or not reproducibility["crn_audit"]["passed"]
        or not reproducibility["oracle_path_audit"]["passed"]
        or not audit_checkpoints(programme_identity)["complete"]
    ):
        raise ValueError("Experiment E compact evidence validation failed.")
    return {
        "passed": True,
        "artefact_count": len(paths),
        "manifest_count": manifest["artefact_count"],
        "experiment_identity": experiment_identity(programme_identity),
        "overall_h2_classification": decision["overall_h2_classification"],
        "checkpoint_audit": audit_checkpoints(programme_identity),
        "artefact_checksums": {path.name: sha256_file(path) for path in paths},
    }
