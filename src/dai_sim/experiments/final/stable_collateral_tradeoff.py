"""Pre-registered Experiment C stable-collateral trade-off.

Experiment C consumes the twelve immutable C rows in the final dissertation
programme.  It composes the established portfolio, market, gas, liquidation,
confidence and evidence owners; this module owns only C treatment assignment,
stable-specific diagnostics, paired trade-off contrasts and resumable evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from functools import lru_cache
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

from dai_sim.common.serialization import to_json_compatible
from dai_sim.experiments.final import (
    correlated_stress as experiment_b,
    idiosyncratic_diversification as experiment_a,
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
from dai_sim.inputs.market import prices_from_log_returns
from dai_sim.inputs.multicollateral import (
    FAMILY_ORDER,
    load_final_market_pool,
    resolve_multicollateral_inputs,
)
from dai_sim.validation import multicollateral as multicollateral_validation


EXPERIMENT_C_PARENT_COMMIT = (
    "97364e62aee94b083b251ac89d361e3d7e235374"
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
EXPERIMENT_A_EVIDENCE_TREE_SHA256 = (
    "110b0d16a0f945bd720c400957e8c94297b4d20d19bda495ca7601640c90900c"
)
EXPERIMENT_B_EVIDENCE_TREE_SHA256 = (
    "091a420491c51bc1b25157a5adcef9565673e012d49fe90f350361b64aa3dc83"
)
EXPERIMENT_A_CHECKPOINT_TREE_SHA256 = (
    "aa31d65e4609db14e4b8392eb623dfdaae3c15cdf08eef6c100e313729508583"
)
EXPERIMENT_B_CHECKPOINT_TREE_SHA256 = (
    "e780bc139e34e64975d3108f6565509ab3c5db93758023a246a4913f5766e781"
)

EXPERIMENT_ID = "C_stable_collateral_tradeoff"
EXPERIMENT_NAMESPACE = "final-stable-collateral-tradeoff-v1"
EVIDENCE_DIR = (
    REPOSITORY_ROOT
    / "data/provenance/experiments/final/stable_collateral_tradeoff"
)
OUTPUT_ROOT = (
    REPOSITORY_ROOT
    / "outputs/experiments/final/stable_collateral_tradeoff"
)
MANIFEST_PATH = REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"
BASE_MANIFEST_ARTEFACTS_SHA256 = (
    "1604f25c9db9c5240855a08f037ac158f3c28dc0df1f51602eea648c660127f1"
)

PORTFOLIO_ORDER = (
    "empirical_crypto",
    "stable_supported",
    "stable_heavy",
)
SHOCK_ORDER = (
    "joint_crypto_high_correlation",
    "stable_depeg_moderate",
    "stable_depeg_severe",
    "joint_crypto_stable_stress",
)
CELL_ORDER = tuple(
    f"{shock}__{portfolio}"
    for shock in SHOCK_ORDER
    for portfolio in PORTFOLIO_ORDER
)
EXPECTED_MASTER_CELL_CHECKSUMS = (
    "bf183001addb9989f0a3796f4fa8f131f783ef609c0c78591d9f24ede66f2937",
    "bc8f45be78952c945db30625b33932156d529110697559b3c7610d5b55feec54",
    "b802087753fead6f0109a4564b4354a68a153eec39ee6cb411f3e8df9343533a",
    "83442939bae279b996ba2e34b2116bb380e0a1853cc0a70c397ff39bfe2ee8e2",
    "f2264540eb106b230057d6bcac8ae7611718564e7e3672460380425b28eb04b5",
    "4b18a718c467eb31c6a07a401acc7ded211dea6b27e77fe66364a2744d5620db",
    "9cdc18c53940850ee3a8b8cd0a76756a2e43887552a7ef16133d3ce4649b19bd",
    "1de2dd15f69265cb05a8ae0253ed149c3396d515212549458753c6fd6b0848db",
    "5a8c95986e14d40c90ff84b0f9540dfcc958119157f57f55d0e3c73a04fb12a5",
    "1bdd0c4fb989afc5229552143bd0cd9e59c62e315d552295b2b47373d411263c",
    "ed393f6672beaf42a8d6a25a294d0104abfe6a15229df1c980decf40f2516b47",
    "445d24581b655a83cce1ba9e76aa0c3233476fc39b061644a389e052de4d1700",
)

REPLICATIONS = 128
VAULT_COUNT = 500
TOTAL_DEBT_DAI = 2_500_000.0
TARGET_SYSTEM_COLLATERAL_RATIO = 3.6089387701260205
CAPACITY = 26
PRE_SHOCK_HOURS = 48
POST_SHOCK_HOURS = 720
TOTAL_HOURS = 768
REGISTERED_KERNEL_HOURS = 216
REGISTERED_KERNEL_ONSET = 24
KERNEL_EMBEDDING_START = PRE_SHOCK_HOURS - REGISTERED_KERNEL_ONSET
MAXIMUM_OUTPUT_BYTES = 750 * 1024**2
MINIMUM_FREE_BYTES = 10 * 1024**3
INITIALISATION_REPLICATION_OFFSET = 2_000_000

REGISTERED_SCIENTIFIC_CODE_IDENTITY = (
    "e9cccf942a84976d428669a0c2943150d155f087b1a1a4d2ac1583dc2619fa51"
)
REGISTERED_SIMULATION_CORE_IDENTITY = (
    "72ac0425d3033bdd2dea97e3522e3f97c4fbb45b66a10e125cacb0f92e0af6f7"
)
REGISTERED_EXPERIMENT_IDENTITY = (
    "cb6d00877c54011cc49714bdfe23fad83140fef001568ea9b43d355811c9129b"
)

SEED_STREAMS = (
    "initialisation_key",
    "market_gas_blocks",
    "keeper_gas_units",
    "liquidation_arrivals",
    "stage1_residual_blocks",
)
SYSTEM_METRICS = experiment_a.SYSTEM_METRICS
BINARY_METRICS = experiment_a.BINARY_METRICS
ZERO_HEAVY_METRICS = experiment_a.ZERO_HEAVY_METRICS
PRIMARY_SOLVENCY_METRICS = (
    "backlog_area_share",
    "liquidated_debt_share",
    "unresolved_tab_share",
    "realised_bad_debt_share",
)
PEG_METRICS = (
    "below_peg_burden",
    "mean_absolute_peg_deviation",
    "minimum_dai_price",
    "restricted_mean_recovery_time",
    "recovery_probability_720h",
)
SYSTEM_DIAGNOSTICS = (
    "positive_demand_hours",
    "binding_hours",
    "mean_capacity_utilisation",
    "maximum_capacity_utilisation",
    "maximum_simultaneously_unsafe_families",
    "maximum_backlog_duration",
    "hours_one_unsafe_family",
    "hours_at_least_two_unsafe_families",
    "hours_all_applicable_volatile_families_unsafe",
    "hours_eth_wbtc_simultaneously_unsafe",
    "share_hours_eth_wbtc_simultaneously_unsafe",
    "maximum_simultaneous_active_backlog_families",
    "stable_minimum_price",
    "stable_hours_below_0_99",
    "stable_hours_below_0_95",
    "stable_hours_below_0_90",
)
COLLATERAL_METRICS = (
    *experiment_b.COLLATERAL_METRICS,
    "stable_minimum_price",
    "stable_hours_below_0_99",
    "stable_hours_below_0_95",
    "stable_hours_below_0_90",
)
STABLE_ATTRIBUTED_GRADIENT_METRICS = (
    "unsafe_vault_count",
    "selected_attempts",
    "capacity_rejections",
    "successful_closures",
    "liquidated_debt",
    "backlog_area",
    "maximum_backlog",
    "active_bad_debt",
    "realised_bad_debt",
    "keeper_profit_proxy",
    "displaced_candidates",
)
STABLE_EXPOSURE_NORMALISED_GRADIENT_METRICS = (
    "exposure_normalised_liquidated_debt",
    "exposure_normalised_backlog",
    "exposure_normalised_bad_debt",
)
METRIC_DIRECTIONS = {
    metric: (-1 if metric != "recovery_probability_720h" else 1)
    for metric in SYSTEM_METRICS
}
MATERIALITY_THRESHOLDS = {
    "numerical_tolerance": 1e-10,
    "accounting_tolerance_dai": 1e-5,
    "stable_price_tolerance": 1e-12,
    "stable_unsafe_activity_threshold": 0.0,
    "contrast_interval_confidence": 0.95,
    "failure_share_invalid": 0.01,
}
COMPACT_FILENAMES = (
    "stable_collateral_tradeoff_specification.json",
    "stable_collateral_tradeoff_registry.csv",
    "stable_collateral_tradeoff_cell_summary.csv",
    "stable_collateral_tradeoff_collateral_summary.csv",
    "stable_collateral_tradeoff_contrasts.csv",
    "stable_collateral_tradeoff_decision.json",
    "stable_collateral_tradeoff_reproducibility.json",
    "stable_collateral_tradeoff_benchmark.json",
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
REGISTRY_COLUMNS = (
    "cell_order",
    "cell_identifier",
    "shock",
    "portfolio",
    "capacity",
    "hurdle",
    "confidence",
    "oracle_delay",
    "replication_count",
    "master_row_checksum",
    "row_checksum",
)
CELL_SUMMARY_COLUMNS = (
    "cell_order",
    "cell_identifier",
    "shock",
    "portfolio",
    "metric_order",
    "metric",
    "operationality",
    "direction",
    "count",
    *DISTRIBUTION_FIELDS,
)
COLLATERAL_SUMMARY_COLUMNS = (
    "cell_order",
    "cell_identifier",
    "shock",
    "portfolio",
    "family_order",
    "family",
    "metric_order",
    "metric",
    "count",
    *DISTRIBUTION_FIELDS,
)
CONTRAST_COLUMNS = (
    "contrast_order",
    "contrast_type",
    "shock",
    "portfolio",
    "reference_portfolio",
    "comparison_shock",
    "family",
    "metric",
    "direction_multiplier",
    "count",
    *DISTRIBUTION_FIELDS,
    "discordant_positive",
    "discordant_negative",
    "reversal",
)


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        to_json_compatible(payload),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _pretty_json(payload: Any) -> bytes:
    return (
        json.dumps(
            to_json_compatible(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _row_checksum(row: Mapping[str, Any]) -> str:
    return _payload_sha256(dict(row))


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")


def _atomic_bytes(path: Path, payload: bytes) -> None:
    experiment_a._atomic_bytes(path, payload)


def _atomic_json(path: Path, payload: Any) -> None:
    _atomic_bytes(path, _pretty_json(payload))


def _relative(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def derive_seed(replication: int, stream: str, substream: str = "") -> int:
    """Derive a C-owned deterministic seed independent of A, B and D/E."""
    if stream not in SEED_STREAMS:
        raise ValueError(f"Unregistered Experiment C seed stream: {stream}.")
    payload = (
        f"{EXPERIMENT_NAMESPACE}|{replication}|{stream}|{substream}"
    ).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def initialisation_replication_key(replication: int) -> int:
    return INITIALISATION_REPLICATION_OFFSET + int(replication)


def seed_record(replication: int) -> dict[str, Any]:
    return {
        "replication": int(replication),
        "namespace": EXPERIMENT_NAMESPACE,
        "initialisation_replication_key": initialisation_replication_key(
            replication
        ),
        "streams": {
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
class ExperimentCCell:
    """One immutable master-programme Experiment C cell."""

    order: int
    identifier: str
    shock: str
    portfolio: str
    capacity: int
    hurdle: str
    confidence: str
    oracle_delay: int
    replication_count: int
    master_row_checksum: str


def _validate_master_cell(cell: ProgrammeCell) -> None:
    expected = {
        "experiment_identifier": EXPERIMENT_ID,
        "research_questions": ("RQ4",),
        "hypotheses": ("H3",),
        "capacity_profile_identifier": "shared_keeper_capacity_central",
        "maximum_liquidations_per_step": CAPACITY,
        "confidence_scenario_identifier": "stage1_only",
        "hurdle_profile_identifier": "direct_cost_only",
        "risk_cost_rate": Decimal("0"),
        "oracle_treatment_identifier": "transparent_zero_delay_baseline",
        "oracle_delay_steps": 0,
        "replication_count": REPLICATIONS,
        "execution_status": "preregistered_not_executed",
    }
    for name, value in expected.items():
        if getattr(cell, name) != value:
            raise ValueError(f"Frozen Experiment C cell changed: {name}.")
    if (
        cell.portfolio_identifier not in PORTFOLIO_ORDER
        or cell.shock_identifier not in SHOCK_ORDER
    ):
        raise ValueError("Experiment C contains an unregistered treatment.")


def build_cell_registry(
    owner: FinalExperimentProgramme | None = None,
) -> tuple[ExperimentCCell, ...]:
    programme = load_programme() if owner is None else owner
    if programme.programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Master programme identity changed.")
    experiment = programme.experiments_by_identifier[EXPERIMENT_ID]
    if (
        experiment.order != 3
        or experiment.primary_research_question != "RQ4"
        or experiment.primary_hypothesis != "H3"
        or experiment.replication_count != REPLICATIONS
        or experiment.execution_status != "preregistered_not_executed"
        or experiment.dependency_status != "frozen_inputs_ready"
    ):
        raise ValueError("Frozen Experiment C metadata changed.")
    cells: list[ExperimentCCell] = []
    for source in experiment.cells:
        _validate_master_cell(source)
        cells.append(
            ExperimentCCell(
                order=source.cell_order,
                identifier=source.identifier,
                shock=source.shock_identifier,
                portfolio=source.portfolio_identifier,
                capacity=source.maximum_liquidations_per_step,
                hurdle=source.hurdle_profile_identifier,
                confidence=source.confidence_scenario_identifier,
                oracle_delay=int(source.oracle_delay_steps or 0),
                replication_count=source.replication_count,
                master_row_checksum=source.row_checksum,
            )
        )
    if tuple(cell.identifier for cell in cells) != CELL_ORDER:
        raise ValueError("Experiment C cell order differs.")
    if tuple(cell.master_row_checksum for cell in cells) != (
        EXPECTED_MASTER_CELL_CHECKSUMS
    ):
        raise ValueError("Experiment C master-row checksums differ.")
    return tuple(cells)


def _registry_frame() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for cell in build_cell_registry():
        row = {
            "cell_order": cell.order,
            "cell_identifier": cell.identifier,
            "shock": cell.shock,
            "portfolio": cell.portfolio,
            "capacity": cell.capacity,
            "hurdle": cell.hurdle,
            "confidence": cell.confidence,
            "oracle_delay": cell.oracle_delay,
            "replication_count": cell.replication_count,
            "master_row_checksum": cell.master_row_checksum,
        }
        row["row_checksum"] = _row_checksum(row)
        rows.append(row)
    return pd.DataFrame(rows, columns=REGISTRY_COLUMNS)


def _tree_snapshot(path: Path, pattern: str = "*") -> dict[str, Any]:
    files = sorted(item for item in path.rglob(pattern) if item.is_file())
    rows = [
        {
            "path": item.relative_to(path).as_posix(),
            "size": item.stat().st_size,
            "sha256": sha256_file(item),
        }
        for item in files
    ]
    return {
        "file_count": len(rows),
        "total_bytes": sum(row["size"] for row in rows),
        "content_map_sha256": _payload_sha256(rows),
    }


def regression_audit() -> dict[str, Any]:
    """Protect A/B evidence and checkpoints from Experiment C."""
    a_evidence = _tree_snapshot(experiment_a.EVIDENCE_DIR)
    b_evidence = _tree_snapshot(experiment_b.EVIDENCE_DIR)
    a_checkpoints = _tree_snapshot(experiment_a.OUTPUT_ROOT, "replication_*.json")
    b_checkpoints = _tree_snapshot(experiment_b.OUTPUT_ROOT, "replication_*.json")
    expected = {
        "a_evidence": (8, EXPERIMENT_A_EVIDENCE_TREE_SHA256),
        "b_evidence": (8, EXPERIMENT_B_EVIDENCE_TREE_SHA256),
        "a_checkpoints": (128, EXPERIMENT_A_CHECKPOINT_TREE_SHA256),
        "b_checkpoints": (128, EXPERIMENT_B_CHECKPOINT_TREE_SHA256),
    }
    actual = {
        "a_evidence": a_evidence,
        "b_evidence": b_evidence,
        "a_checkpoints": a_checkpoints,
        "b_checkpoints": b_checkpoints,
    }
    for name, (count, checksum) in expected.items():
        if (
            actual[name]["file_count"] != count
            or actual[name]["content_map_sha256"] != checksum
        ):
            raise ValueError(f"Experiment {name} regression boundary changed.")
    return {"passed": True, **actual}


def _draw_c_nested_states(replication: int) -> dict[str, Any]:
    """Draw the three C portfolios from common family-stream prefixes."""
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
                for portfolio in PORTFOLIO_ORDER
            }
        except ValueError as exc:
            if "initially unsafe" in str(exc):
                continue
            raise
        audit = audit_nested_initialisations(states)
        return {"states": states, "audit": audit}
    raise ValueError("No common safe C initialisation was accepted.")


def audit_nested_initialisations(states: Mapping[str, Any]) -> dict[str, Any]:
    if tuple(states) != PORTFOLIO_ORDER:
        raise ValueError("C nested portfolio order differs.")
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
        keys: list[str | None] = ilks or [None]
        for ilk in keys:
            sequences: list[tuple[str, list[str]]] = []
            for portfolio, state in states.items():
                selected = state.sampled.loc[state.sampled["family"].eq(family)]
                if ilk is not None:
                    selected = selected.loc[selected["exact_ilk"].eq(ilk)]
                values = selected.sort_values(
                    "family_stream_position", kind="mergesort"
                )["source_row_id"].astype(str).tolist()
                sequences.append((portfolio, values))
            ordered = sorted(sequences, key=lambda item: len(item[1]))
            for (left_name, left), (right_name, right) in zip(
                ordered, ordered[1:], strict=False
            ):
                if left != right[: len(left)]:
                    failures.append(
                        f"{family}/{ilk}:{left_name}->{right_name}"
                    )
    if failures:
        raise ValueError(f"C nested family draws failed: {failures}.")
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
    initialisation = _draw_c_nested_states(replication)
    states = initialisation["states"]
    accepted_attempt = next(
        iter({int(state.accepted_attempt) for state in states.values()})
    )
    state_key = initialisation_replication_key(replication)
    master_seed = experiment_a.derive_seed(
        state_key, "initialisation_master"
    )
    family_seeds = {
        family: experiment_a.derive_seed(
            state_key,
            f"vault_{family}",
            f"master:{master_seed}:attempt:{accepted_attempt}",
        )
        for family in FAMILY_ORDER
    }
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
        "initialisation_family_seeds": family_seeds,
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


def registered_shock_kernels(shock: str) -> dict[str, np.ndarray]:
    if shock not in SHOCK_ORDER:
        raise ValueError(f"Unexpected Experiment C shock: {shock}.")
    selected = experiment_b._registered_shock_frame().loc[
        lambda frame: frame["shock_identifier"].eq(shock)
    ]
    kernels: dict[str, np.ndarray] = {}
    for family in FAMILY_ORDER:
        row = selected.loc[selected["family"].eq(family)]
        if len(row) != 1:
            raise ValueError(f"Missing one frozen {shock}/{family} row.")
        values = row.iloc[0]
        if int(values["onset_hour"]) != REGISTERED_KERNEL_ONSET:
            raise ValueError("Frozen C shock onset changed.")
        kernel = multicollateral_validation._controlled_path(
            multiplier=float(values["price_multiplier_at_trough"]),
            onset=int(values["onset_hour"]),
            recovery=str(values["recovery_path"]),
            recovery_hours=max(int(values["duration_hours"]), 1),
            horizon=REGISTERED_KERNEL_HOURS,
        )
        checksum = hashlib.sha256(
            np.asarray(kernel, dtype="<f8").tobytes()
        ).hexdigest()
        if checksum != str(values["path_checksum"]):
            raise ValueError(f"Frozen {shock}/{family} path changed.")
        kernels[family] = kernel
    return kernels


def build_treatment_paths(
    sampled_market: pd.DataFrame,
    shock: str,
) -> tuple[dict[str, np.ndarray], pd.DataFrame, dict[str, Any]]:
    collateral, _, _ = experiment_a._design_payloads()
    initial = {
        family: float(
            multicollateral_validation._family_payload(collateral, family)[
                "initial_price_usd"
            ]
        )
        for family in FAMILY_ORDER
    }
    ordinary = prices_from_log_returns(
        sampled_market,
        initial_prices={"ETH": initial["ETH"], "BTC": initial["WBTC"]},
    )
    ordinary["STABLE"] = experiment_a._stable_prices(
        sampled_market, initial["STABLE"]
    )
    kernels = registered_shock_kernels(shock)
    multipliers = {
        family: experiment_a.embed_registered_kernel(kernels[family])
        for family in FAMILY_ORDER
    }
    paths = {
        "ETH": ordinary["ETH"] * multipliers["ETH"],
        "BTC": ordinary["BTC"] * multipliers["WBTC"],
        "STABLE": ordinary["STABLE"] * multipliers["STABLE"],
    }
    if any(
        not np.isfinite(values).all() or np.any(values <= 0.0)
        for values in paths.values()
    ):
        raise ValueError("Experiment C price path is invalid.")
    stable = np.asarray(paths["STABLE"], dtype="<f8")
    stable_multiplier = np.asarray(multipliers["STABLE"], dtype="<f8")
    crypto_only = shock == "joint_crypto_high_correlation"
    stable_only = shock in {"stable_depeg_moderate", "stable_depeg_severe"}
    joint = shock == "joint_crypto_stable_stress"
    expected_floor = {
        "joint_crypto_high_correlation": 1.0,
        "stable_depeg_moderate": 0.95,
        "stable_depeg_severe": 0.90,
        "joint_crypto_stable_stress": 0.90,
    }[shock]
    audit = {
        "shock": shock,
        "registered_kernel_checksums": {
            family: hashlib.sha256(
                np.asarray(kernels[family], dtype="<f8").tobytes()
            ).hexdigest()
            for family in FAMILY_ORDER
        },
        "embedded_multiplier_checksums": {
            family: hashlib.sha256(
                np.asarray(multipliers[family], dtype="<f8").tobytes()
            ).hexdigest()
            for family in FAMILY_ORDER
        },
        "full_price_checksums": {
            family: hashlib.sha256(
                np.asarray(
                    paths["BTC" if family == "WBTC" else family],
                    dtype="<f8",
                ).tobytes()
            ).hexdigest()
            for family in FAMILY_ORDER
        },
        "stable_multiplier_minimum": float(stable_multiplier.min()),
        "expected_stable_multiplier_floor": expected_floor,
        "stable_floor_valid": math.isclose(
            float(stable_multiplier.min()),
            expected_floor,
            rel_tol=0.0,
            abs_tol=1e-12,
        ),
        "stable_ordinary_valid": bool(
            not crypto_only
            or np.array_equal(
                stable_multiplier, np.ones(TOTAL_HOURS, dtype="<f8")
            )
        ),
        "stable_treatment_active": stable_only or joint,
        "crypto_treatment_active": crypto_only or joint,
        "stable_minimum_price": float(stable.min()),
        "stable_hours_below_0_99": int(np.count_nonzero(stable < 0.99)),
        "stable_hours_below_0_95": int(np.count_nonzero(stable < 0.95)),
        "stable_hours_below_0_90": int(np.count_nonzero(stable < 0.90)),
        "gas_owner": "ordinary_common_market_blocks",
        "gas_environment_checksum": _payload_sha256(
            sampled_market.loc[
                :, list(experiment_b.EMPIRICAL_GAS_COLUMNS)
            ].to_dict(orient="records")
        ),
        "price_isolation_valid": True,
        "final_validation_data_used": bool(
            not sampled_market["is_calibration"].astype(bool).all()
        ),
    }
    audit["path_valid"] = bool(
        audit["stable_floor_valid"]
        and audit["stable_ordinary_valid"]
        and not audit["final_validation_data_used"]
    )
    return paths, sampled_market.copy(), audit


def simulate_replication(
    replication: int,
    programme_identity: str | None = None,
    *,
    enforce_registered_core: bool = True,
) -> dict[str, Any]:
    if (
        enforce_registered_core
        and simulation_core_identity() != REGISTERED_SIMULATION_CORE_IDENTITY
    ):
        raise RuntimeError("Experiment C simulation-core identity changed.")
    programme = load_programme()
    programme_identity = (
        programme.programme_identity
        if programme_identity is None
        else programme_identity
    )
    if programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Experiment C programme identity changed.")
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
    path_audits: dict[str, Any] = {}
    gas_unit_checksums: set[str] = set()
    gas_component_checksums: dict[str, str] = {}

    for shock in SHOCK_ORDER:
        paths, gas_rows, path_audit = build_treatment_paths(
            streams["sampled_market"], shock
        )
        path_audits[shock] = path_audit
        gas = component_gas_costs(
            sampled_market_gas_rows=gas_rows,
            simulated_eth_prices=paths["ETH"],
            config=replace(
                resolve_integrated_empirical_eth_profile().gas,
                seed=derive_seed(replication, "keeper_gas_units"),
            ),
        )
        if gas.gas_cost_usd is None or gas.sampled_rows is None:
            raise ValueError("Experiment C gas path is missing.")
        unit_checksum = _payload_sha256(
            gas.sampled_rows[
                ["gas_pool_row_id", "gas_units"]
            ].to_dict(orient="records")
        )
        component_checksum = _payload_sha256(
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
        gas_unit_checksums.add(unit_checksum)
        gas_component_checksums[shock] = component_checksum
        for portfolio in PORTFOLIO_ORDER:
            identifier = f"{shock}__{portfolio}"
            liquidation = experiment_b._simulate_cell_liquidations(
                initialisation=streams["states"][portfolio],
                price_paths=paths,
                gas_costs=np.asarray(gas.gas_cost_usd, dtype="<f8"),
                arrivals=streams["arrivals"],
                portfolio_config=experiment_a._portfolio_config(
                    portfolio,
                    collateral_payload,
                    portfolio_payload,
                ),
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
                    for key in (
                        "below_peg_burden",
                        "mean_absolute_peg_deviation",
                        "minimum_dai_price",
                        "restricted_mean_recovery_time",
                        "recovery_probability_720h",
                        "right_censored",
                    )
                },
                "stable_minimum_price": path_audit["stable_minimum_price"],
                "stable_hours_below_0_99": path_audit[
                    "stable_hours_below_0_99"
                ],
                "stable_hours_below_0_95": path_audit[
                    "stable_hours_below_0_95"
                ],
                "stable_hours_below_0_90": path_audit[
                    "stable_hours_below_0_90"
                ],
                "cell_order": cells[identifier].order,
                "cell_identifier": identifier,
                "shock": shock,
                "portfolio": portfolio,
                "replication": replication,
                "capacity": CAPACITY,
                "hurdle": "direct_cost_only",
                "confidence": "stage1_only",
                "oracle_delay": 0,
                "paired_stream_checksum": streams[
                    "paired_stream_checksum"
                ],
                "state_checksum": streams["states"][portfolio].identity,
                "gas_unit_draw_checksum": unit_checksum,
                "gas_component_checksum": component_checksum,
                "price_path_checksum": _payload_sha256(
                    path_audit["full_price_checksums"]
                ),
                "path_valid": path_audit["path_valid"],
                "price_isolation_valid": path_audit[
                    "price_isolation_valid"
                ],
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
            for row in liquidation["collateral_rows"]:
                stable_specific = (
                    {
                        "stable_minimum_price": path_audit[
                            "stable_minimum_price"
                        ],
                        "stable_hours_below_0_99": path_audit[
                            "stable_hours_below_0_99"
                        ],
                        "stable_hours_below_0_95": path_audit[
                            "stable_hours_below_0_95"
                        ],
                        "stable_hours_below_0_90": path_audit[
                            "stable_hours_below_0_90"
                        ],
                    }
                    if row["family"] == "STABLE"
                    else {
                        "stable_minimum_price": None,
                        "stable_hours_below_0_99": None,
                        "stable_hours_below_0_95": None,
                        "stable_hours_below_0_90": None,
                    }
                )
                collateral_rows.append(
                    {
                        "cell_order": cells[identifier].order,
                        "cell_identifier": identifier,
                        "shock": shock,
                        "portfolio": portfolio,
                        "replication": replication,
                        "numerical_valid": system["numerical_valid"],
                        "accounting_valid": system["accounting_valid"],
                        "path_valid": system["path_valid"],
                        "price_isolation_valid": system[
                            "price_isolation_valid"
                        ],
                        "nested_initialisation_valid": system[
                            "nested_initialisation_valid"
                        ],
                        **row,
                        **stable_specific,
                    }
                )

    if len(gas_unit_checksums) != 1:
        raise ValueError("Experiment C common gas-unit streams drifted.")
    if (
        gas_component_checksums["stable_depeg_moderate"]
        != gas_component_checksums["stable_depeg_severe"]
        or gas_component_checksums["joint_crypto_high_correlation"]
        != gas_component_checksums["joint_crypto_stable_stress"]
    ):
        raise ValueError("Experiment C negative-control gas paths drifted.")
    if [row["cell_identifier"] for row in cell_rows] != list(CELL_ORDER):
        raise ValueError("Experiment C cell order differs.")
    expected_collateral = [
        (cell, family) for cell in CELL_ORDER for family in FAMILY_ORDER
    ]
    if [
        (row["cell_identifier"], row["family"])
        for row in collateral_rows
    ] != expected_collateral:
        raise ValueError("Experiment C collateral order differs.")
    negative_control_pairs = (
        ("stable_depeg_moderate", "stable_depeg_severe"),
        ("joint_crypto_high_correlation", "joint_crypto_stable_stress"),
    )
    row_map = {
        (row["shock"], row["portfolio"]): row for row in cell_rows
    }
    negative_control_failures: list[str] = []
    compare_fields = (*SYSTEM_METRICS, *SYSTEM_DIAGNOSTICS[:-4])
    for left, right in negative_control_pairs:
        left_row = row_map[(left, "empirical_crypto")]
        right_row = row_map[(right, "empirical_crypto")]
        for metric in compare_fields:
            if not math.isclose(
                float(left_row[metric]),
                float(right_row[metric]),
                rel_tol=0.0,
                abs_tol=MATERIALITY_THRESHOLDS["numerical_tolerance"],
            ):
                negative_control_failures.append(
                    f"{left}->{right}:{metric}"
                )
    for row in cell_rows:
        row["stable_negative_control_valid"] = not negative_control_failures
        row["numerical_valid"] = bool(
            row["numerical_valid"] and not negative_control_failures
        )
    for row in collateral_rows:
        row["stable_negative_control_valid"] = not negative_control_failures
        row["numerical_valid"] = bool(
            row["numerical_valid"] and not negative_control_failures
        )
    result = {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "programme_identity": programme_identity,
        "experiment_identity": experiment_identity(programme_identity),
        "replication": replication,
        "scientific_code_identity": REGISTERED_SCIENTIFIC_CODE_IDENTITY,
        "profile_identity": PROFILE_IDENTITY,
        "seed_registry_sha256": seed_registry_checksum(),
        "seed_ownership": streams["seed_ownership"],
        "paired_stream_checksum": streams["paired_stream_checksum"],
        "stream_components": streams["stream_components"],
        "nested_initialisation_audit": streams["nested_audit"],
        "path_audits": path_audits,
        "gas_unit_draw_checksum": next(iter(gas_unit_checksums)),
        "gas_component_checksums": gas_component_checksums,
        "stable_negative_control": {
            "passed": not negative_control_failures,
            "failure_count": len(negative_control_failures),
            "failures": negative_control_failures,
            "registered_non_vault_stable_channel": False,
        },
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


@lru_cache(maxsize=1)
def simulation_core_identity() -> str:
    functions = (
        derive_seed,
        initialisation_replication_key,
        seed_record,
        seed_registry_checksum,
        _draw_c_nested_states,
        audit_nested_initialisations,
        _arrival_stream,
        _prepare_replication_streams,
        registered_shock_kernels,
        build_treatment_paths,
        simulate_replication,
        experiment_b._simulate_cell_liquidations,
        experiment_a._normalise_nested_portfolio,
        experiment_a._simulate_market_scenario,
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


@lru_cache(maxsize=1)
def scientific_code_identity() -> str:
    return _payload_sha256(
        {
            "simulation_core_identity": simulation_core_identity(),
            "programme_identity": MASTER_PROGRAMME_IDENTITY,
            "cell_order": CELL_ORDER,
            "replications": REPLICATIONS,
            "primary_metrics": PRIMARY_SOLVENCY_METRICS,
            "metric_directions": METRIC_DIRECTIONS,
            "materiality_thresholds": MATERIALITY_THRESHOLDS,
            "negative_control_pairs": (
                ("stable_depeg_moderate", "stable_depeg_severe"),
                (
                    "joint_crypto_high_correlation",
                    "joint_crypto_stable_stress",
                ),
            ),
        }
    )


def _decision_rules() -> dict[str, Any]:
    return {
        "C1": {
            "supported": (
                "Both stable portfolios have at least two operational "
                "advantages with 95% intervals above zero and no adverse "
                "operational bad-debt effect."
            ),
            "partially_supported": "Exactly one portfolio satisfies the rule.",
            "not_supported": "Neither portfolio satisfies the rule.",
            "not_operational": "Fewer than two primary metrics are operational.",
            "invalid": "A registered validity gate fails.",
        },
        "C2": {
            "depeg_exposure_gradient_consistent": (
                "Negative controls pass; severity worsens at least one "
                "stable-sensitive metric for both portfolios; severe heavy "
                "exposure worsens at least two metrics."
            ),
            "depeg_exposure_gradient_partial": (
                "Negative controls pass but severity or exposure ordering is "
                "only partial."
            ),
            "depeg_exposure_gradient_not_present": (
                "Negative controls pass without a systematic gradient."
            ),
            "depeg_exposure_gradient_inconsistent": (
                "Registered directions are clearly and unexplainedly opposite."
            ),
            "not_operational": "No stable cell activates a stable-loss channel.",
            "invalid": "Price isolation, CRN or accounting fails.",
        },
        "C3": {
            "contagion_reversal_present": (
                "At least one portfolio has two adverse joint-stress "
                "advantages with intervals below zero and an active stable "
                "loss channel."
            ),
            "contagion_erosion_present": (
                "Both portfolios have two positive erosion metrics and at "
                "least one active stable-loss or displacement channel."
            ),
            "contagion_mixed": "Some erosion/transmission appears inconsistently.",
            "contagion_not_present": (
                "Advantages persist without material stable deterioration."
            ),
            "not_operational": "Stable shock does not activate stable losses.",
            "invalid": "A registered validity gate fails.",
        },
    }


def specification_payload(programme_identity: str) -> dict[str, Any]:
    if programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Experiment C programme identity changed.")
    cells = [asdict(cell) for cell in build_cell_registry()]
    return {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "experiment_c_parent_commit": EXPERIMENT_C_PARENT_COMMIT,
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
        "research_question": "RQ4",
        "hypothesis": "H3",
        "components": ("C1", "C2", "C3"),
        "cells": cells,
        "cell_order": CELL_ORDER,
        "portfolio_order": PORTFOLIO_ORDER,
        "shock_order": SHOCK_ORDER,
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
            "capacity": CAPACITY,
            "hurdle": "direct_cost_only",
            "risk_cost_rate": 0.0,
            "confidence": "stage1_only",
            "oracle_delay": 0,
        },
        "stage1_owners": {
            "below_peg_response": EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
            "above_peg_response": EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
            "residual_sequence_sha256": (
                EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256
            ),
            "residual_block_sha256": EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
        },
        "stable_owner": {
            "status": "counterfactual_stable_proxy",
            "liquidation_ratio": 1.10,
            "liquidation_penalty": 0.05,
            "ordinary_price": "clean_stable_proxy",
            "depeg_floors": {
                "moderate": 0.95,
                "severe": 0.90,
            },
            "scenario_defined": True,
            "usdc_svb_used": False,
        },
        "negative_control": {
            "portfolio": "empirical_crypto",
            "stable_exposure": 0.0,
            "pairs": (
                ("stable_depeg_moderate", "stable_depeg_severe"),
                (
                    "joint_crypto_high_correlation",
                    "joint_crypto_stable_stress",
                ),
            ),
            "registered_non_vault_stable_channel": False,
            "failure_classification": "invalid",
        },
        "system_metrics": SYSTEM_METRICS,
        "system_diagnostics": SYSTEM_DIAGNOSTICS,
        "collateral_metrics": COLLATERAL_METRICS,
        "primary_solvency_metrics": PRIMARY_SOLVENCY_METRICS,
        "metric_directions": METRIC_DIRECTIONS,
        "materiality_thresholds": MATERIALITY_THRESHOLDS,
        "contrast_types": (
            "raw_portfolio_contrast",
            "direction_normalised_advantage",
            "crypto_protection",
            "depeg_cost",
            "severity_increment",
            "exposure_gradient",
            "joint_stress_advantage",
            "tradeoff_erosion",
            "stable_to_crypto_contagion",
            "reversal_flag",
        ),
        "decision_rules": _decision_rules(),
        "portfolio_tradeoff_statuses": (
            "protection_with_reversal",
            "protection_with_material_erosion",
            "protection_with_limited_depeg_cost",
            "depeg_cost_without_crypto_protection",
            "protection_without_material_depeg_cost",
            "mixed",
            "not_operational",
            "invalid",
        ),
        "h3_hierarchy": (
            "H3_stable_contagion_reversal_supported",
            "H3_stable_tradeoff_supported",
            "H3_stable_tradeoff_partially_supported",
            "H3_stable_support_without_material_depeg_cost",
            "H3_stable_depeg_cost_without_crypto_protection",
            "H3_no_clear_stable_collateral_tradeoff",
            "H3_stable_tradeoff_experiment_not_operational",
            "H3_stable_tradeoff_experiment_invalid",
        ),
        "peg_solvency_hierarchy": (
            "solvency_and_peg_tradeoff",
            "solvency_improves_peg_unchanged",
            "depeg_costs_solvent_system_peg_unchanged",
            "peg_deteriorates_solvent_system_unchanged",
            "solvency_and_peg_deteriorate",
            "solvency_and_peg_diverge",
            "neither_materially_changes",
            "relationship_mixed",
            "relationship_invalid",
        ),
        "final_validation_data_used": False,
        "held_out_data_used": False,
        "usdc_svb_used": False,
        "portfolio_selection_permitted": False,
        "runtime_adopted": False,
    }


def experiment_identity(programme_identity: str) -> str:
    specification = specification_payload(programme_identity)
    excluded = {
        "schema_version",
        "experiment_id",
    }
    return _payload_sha256(
        {
            key: value
            for key, value in specification.items()
            if key not in excluded
        }
    )


def write_preregistration(programme_identity: str) -> dict[str, Any]:
    payload = specification_payload(programme_identity)
    identity = experiment_identity(programme_identity)
    if (
        scientific_code_identity() != REGISTERED_SCIENTIFIC_CODE_IDENTITY
        or simulation_core_identity()
        != REGISTERED_SIMULATION_CORE_IDENTITY
        or identity != REGISTERED_EXPERIMENT_IDENTITY
    ):
        raise ValueError("Experiment C registered identity differs.")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    specification_path = EVIDENCE_DIR / COMPACT_FILENAMES[0]
    registry_path = EVIDENCE_DIR / COMPACT_FILENAMES[1]
    specification_bytes = _pretty_json(
        {**payload, "experiment_identity": identity}
    )
    registry_bytes = _csv_bytes(_registry_frame())
    for path, content in (
        (specification_path, specification_bytes),
        (registry_path, registry_bytes),
    ):
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f"Pre-registration differs: {_relative(path)}.")
        _atomic_bytes(path, content)
    return {
        "experiment_identity": identity,
        "scientific_code_identity": scientific_code_identity(),
        "simulation_core_identity": simulation_core_identity(),
        "specification_sha256": sha256_file(specification_path),
        "registry_sha256": sha256_file(registry_path),
    }


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
        != REGISTERED_SCIENTIFIC_CODE_IDENTITY
        or payload.get("simulation_count") != len(CELL_ORDER)
        or [row.get("cell_identifier") for row in payload.get("cell_rows", [])]
        != list(CELL_ORDER)
        or len(payload.get("collateral_rows", []))
        != len(CELL_ORDER) * len(FAMILY_ORDER)
        or not payload.get("stable_negative_control", {}).get("passed", False)
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
    orphans = sorted(
        path.name
        for path in checkpoint_dir.glob("replication_*.json")
        if path.name
        not in {
            f"replication_{replication:03d}.json"
            for replication in range(REPLICATIONS)
        }
    )
    files = [
        _checkpoint_path(output_dir, replication) for replication in valid
    ]
    rows = [
        {
            "replication": replication,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for replication, path in zip(valid, files, strict=True)
    ]
    return {
        "valid_count": len(valid),
        "valid_replications": valid,
        "invalid_count": len(invalid),
        "invalid_replications": invalid,
        "missing_count": REPLICATIONS - len(valid) - len(invalid),
        "orphan_count": len(orphans),
        "orphans": orphans,
        "checkpoint_bytes": sum(row["size"] for row in rows),
        "checkpoint_content_map_sha256": _payload_sha256(rows),
        "complete": (
            len(valid) == REPLICATIONS
            and not invalid
            and not orphans
        ),
    }


def preflight(programme_identity: str) -> dict[str, Any]:
    if programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Experiment C programme identity differs.")
    if (
        scientific_code_identity() != REGISTERED_SCIENTIFIC_CODE_IDENTITY
        or simulation_core_identity()
        != REGISTERED_SIMULATION_CORE_IDENTITY
        or experiment_identity(programme_identity)
        != REGISTERED_EXPERIMENT_IDENTITY
    ):
        raise ValueError("Experiment C frozen identities differ.")
    if sha256_file(
        REPOSITORY_ROOT
        / "config/profiles/empirical_integrated_multicollateral.yaml"
    ) != PROFILE_SHA256:
        raise ValueError("Frozen integrated profile changed.")
    registry = build_cell_registry()
    if len(registry) != 12:
        raise ValueError("Experiment C must contain twelve cells.")
    paths: dict[str, Any] = {}
    smoke_streams = _prepare_replication_streams(0)
    for shock in SHOCK_ORDER:
        _, _, audit = build_treatment_paths(
            smoke_streams["sampled_market"], shock
        )
        if not audit["path_valid"]:
            raise ValueError(f"Experiment C {shock} path is invalid.")
        paths[shock] = audit
    free_bytes = shutil.disk_usage(REPOSITORY_ROOT).free
    if free_bytes < MINIMUM_FREE_BYTES:
        raise ValueError("Less than 10 GiB free before Experiment C.")
    regression = regression_audit()
    return {
        "passed": True,
        "programme_identity": programme_identity,
        "experiment_identity": experiment_identity(programme_identity),
        "scientific_code_identity": scientific_code_identity(),
        "simulation_core_identity": simulation_core_identity(),
        "cell_count": len(registry),
        "replications": REPLICATIONS,
        "substantive_simulations": len(registry) * REPLICATIONS,
        "nested_initialisation": smoke_streams["nested_audit"],
        "path_audits": paths,
        "regression_audit": regression,
        "free_bytes": free_bytes,
        "output_cap_bytes": MAXIMUM_OUTPUT_BYTES,
        "experiments_a_b_simulations": 0,
        "experiments_d_e_simulations": 0,
        "held_out_data_used": False,
        "runtime_adopted": False,
    }


def run_smoke(replication: int = 0) -> dict[str, Any]:
    result = simulate_replication(
        replication,
        MASTER_PROGRAMME_IDENTITY,
        enforce_registered_core=True,
    )
    return {
        "passed": True,
        "replication": replication,
        "simulation_count": result["simulation_count"],
        "stable_negative_control": result["stable_negative_control"],
        "all_numerical_valid": all(
            row["numerical_valid"] for row in result["cell_rows"]
        ),
        "all_accounting_valid": all(
            row["accounting_valid"] for row in result["cell_rows"]
        ),
        "path_valid": all(
            audit["path_valid"] for audit in result["path_audits"].values()
        ),
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
                    _atomic_json(
                        _checkpoint_path(output_dir, replication), result
                    )
                    if not _valid_checkpoint(
                        _checkpoint_path(output_dir, replication),
                        replication=replication,
                        programme_identity=programme_identity,
                    ):
                        raise ValueError(
                            "Persisted checkpoint did not validate."
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
        raise RuntimeError(f"Experiment C worker failure: {failures[0]}.")
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
        raise ValueError("Experiment C output exceeded 750 MB.")
    return execution


def load_results(programme_identity: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    audit = audit_checkpoints(programme_identity)
    if not audit["complete"]:
        raise ValueError("Experiment C checkpoints are incomplete.")
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
    collateral_frame = pd.DataFrame(collateral)
    family_order = {family: index for index, family in enumerate(FAMILY_ORDER)}
    collateral_frame["_family_order"] = collateral_frame["family"].map(
        family_order
    )
    collateral_frame = collateral_frame.sort_values(
        ["cell_order", "_family_order", "replication"], kind="mergesort"
    ).drop(columns="_family_order").reset_index(drop=True)
    if len(cell_frame) != len(CELL_ORDER) * REPLICATIONS:
        raise ValueError("Experiment C cell-result dimensions differ.")
    if len(collateral_frame) != len(CELL_ORDER) * len(FAMILY_ORDER) * REPLICATIONS:
        raise ValueError("Experiment C collateral dimensions differ.")
    return cell_frame, collateral_frame


def _distribution(values: Iterable[float]) -> dict[str, float]:
    distribution = experiment_a._distribution(values)
    return {
        field: float(distribution[field]) for field in DISTRIBUTION_FIELDS
    }


def _valid_rows(frame: pd.DataFrame) -> pd.Series:
    valid = pd.Series(True, index=frame.index, dtype=bool)
    for column in (
        "numerical_valid",
        "accounting_valid",
        "path_valid",
        "price_isolation_valid",
        "nested_initialisation_valid",
        "stable_negative_control_valid",
    ):
        if column in frame:
            valid &= frame[column].astype(bool)
    return valid


def classify_metric_operationality(
    frame: pd.DataFrame,
    metric: str,
    *,
    tolerance: float = 1e-12,
) -> str:
    if metric not in frame:
        return "not_operational"
    valid = _valid_rows(frame)
    if frame.empty or not valid.any():
        return "invalid"
    values = pd.to_numeric(frame.loc[valid, metric], errors="coerce")
    if values.empty or values.isna().all():
        return "not_operational"
    if values.isna().any() or not np.isfinite(values.to_numpy()).all():
        return "invalid"
    array = values.to_numpy(dtype=float)
    all_equal = float(array.max() - array.min()) <= tolerance
    every_cell_constant = all(
        float(group.max() - group.min()) <= tolerance
        for _, group in frame.loc[valid].groupby(
            "cell_identifier", sort=False
        )[metric]
    )
    return "degenerate" if all_equal or every_cell_constant else "operational"


def metric_operationality(frame: pd.DataFrame) -> dict[str, str]:
    return {
        metric: classify_metric_operationality(frame, metric)
        for metric in SYSTEM_METRICS
    }


def cell_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    statuses = metric_operationality(frame)
    ordered_metrics = (*SYSTEM_METRICS, *SYSTEM_DIAGNOSTICS)
    for key, group in frame.groupby(
        ["cell_order", "cell_identifier", "shock", "portfolio"],
        sort=False,
    ):
        cell_order, identifier, shock, portfolio = key
        for metric_order, metric in enumerate(ordered_metrics, start=1):
            values = pd.to_numeric(group[metric], errors="raise")
            rows.append(
                {
                    "cell_order": int(cell_order),
                    "cell_identifier": identifier,
                    "shock": shock,
                    "portfolio": portfolio,
                    "metric_order": metric_order,
                    "metric": metric,
                    "operationality": statuses.get(metric, "diagnostic"),
                    "direction": METRIC_DIRECTIONS.get(metric),
                    "count": len(values),
                    **_distribution(values),
                }
            )
    return pd.DataFrame(rows, columns=CELL_SUMMARY_COLUMNS)


def collateral_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    family_order = {family: index + 1 for index, family in enumerate(FAMILY_ORDER)}
    for key, group in frame.groupby(
        ["cell_order", "cell_identifier", "shock", "portfolio", "family"],
        sort=False,
    ):
        cell_order, identifier, shock, portfolio, family = key
        for metric_order, metric in enumerate(COLLATERAL_METRICS, start=1):
            values = pd.to_numeric(group[metric], errors="coerce").dropna()
            if values.empty:
                distribution = {field: None for field in DISTRIBUTION_FIELDS}
            else:
                distribution = _distribution(values)
            rows.append(
                {
                    "cell_order": int(cell_order),
                    "cell_identifier": identifier,
                    "shock": shock,
                    "portfolio": portfolio,
                    "family_order": family_order[family],
                    "family": family,
                    "metric_order": metric_order,
                    "metric": metric,
                    "count": len(values),
                    **distribution,
                }
            )
    result = pd.DataFrame(rows, columns=COLLATERAL_SUMMARY_COLUMNS)
    expected = [
        (cell, family)
        for cell in CELL_ORDER
        for family in FAMILY_ORDER
        for _ in COLLATERAL_METRICS
    ]
    actual = list(zip(result["cell_identifier"], result["family"], strict=True))
    if actual != expected:
        raise ValueError("Experiment C collateral evidence order differs.")
    return result


def _paired_system(
    frame: pd.DataFrame,
    *,
    left_shock: str,
    left_portfolio: str,
    right_shock: str,
    right_portfolio: str,
) -> pd.DataFrame:
    left = frame.loc[
        frame["shock"].eq(left_shock)
        & frame["portfolio"].eq(left_portfolio)
    ].copy()
    right = frame.loc[
        frame["shock"].eq(right_shock)
        & frame["portfolio"].eq(right_portfolio)
    ].copy()
    paired = left.merge(
        right,
        on="replication",
        how="inner",
        validate="one_to_one",
        suffixes=("_left", "_right"),
        sort=True,
    )
    if len(paired) != REPLICATIONS:
        raise ValueError("Experiment C paired system contrast is incomplete.")
    return paired


def _paired_collateral_sum(
    frame: pd.DataFrame,
    *,
    left_shock: str,
    right_shock: str,
    portfolio: str,
    metric: str,
    families: Sequence[str],
) -> tuple[pd.Series, pd.Series]:
    selected = frame.loc[
        frame["portfolio"].eq(portfolio)
        & frame["family"].isin(families)
    ]
    grouped = (
        selected.groupby(["shock", "replication"], sort=False)[metric]
        .sum()
        .rename("value")
        .reset_index()
    )
    left = grouped.loc[grouped["shock"].eq(left_shock)].set_index(
        "replication"
    )["value"]
    right = grouped.loc[grouped["shock"].eq(right_shock)].set_index(
        "replication"
    )["value"]
    left, right = left.align(right, join="inner")
    if len(left) != REPLICATIONS:
        raise ValueError("Experiment C collateral contrast is incomplete.")
    return left, right


def _paired_collateral_portfolios(
    frame: pd.DataFrame,
    *,
    shock: str,
    left_portfolio: str,
    right_portfolio: str,
    family: str,
    metric: str,
) -> tuple[pd.Series, pd.Series]:
    selected = frame.loc[
        frame["shock"].eq(shock) & frame["family"].eq(family)
    ]
    left = selected.loc[
        selected["portfolio"].eq(left_portfolio)
    ].set_index("replication")[metric]
    right = selected.loc[
        selected["portfolio"].eq(right_portfolio)
    ].set_index("replication")[metric]
    left, right = left.align(right, join="inner")
    if len(left) != REPLICATIONS:
        raise ValueError(
            "Experiment C paired collateral portfolio contrast is incomplete."
        )
    if left.isna().any() or right.isna().any():
        raise ValueError(
            "Experiment C paired collateral portfolio contrast is unavailable."
        )
    return left.astype(float), right.astype(float)


def _contrast_row(
    *,
    order: int,
    contrast_type: str,
    shock: str | None,
    portfolio: str | None,
    reference_portfolio: str | None,
    comparison_shock: str | None,
    family: str | None,
    metric: str,
    direction_multiplier: int,
    values: np.ndarray,
    left_values: pd.Series | None = None,
    right_values: pd.Series | None = None,
    reversal: bool | None = None,
) -> dict[str, Any]:
    distribution = _distribution(values)
    discordant_positive = None
    discordant_negative = None
    if metric in BINARY_METRICS and left_values is not None and right_values is not None:
        left = left_values.astype(int)
        right = right_values.astype(int)
        discordant_positive = int(((left == 1) & (right == 0)).sum())
        discordant_negative = int(((left == 0) & (right == 1)).sum())
    return {
        "contrast_order": order,
        "contrast_type": contrast_type,
        "shock": shock,
        "portfolio": portfolio,
        "reference_portfolio": reference_portfolio,
        "comparison_shock": comparison_shock,
        "family": family,
        "metric": metric,
        "direction_multiplier": direction_multiplier,
        "count": len(values),
        **distribution,
        "discordant_positive": discordant_positive,
        "discordant_negative": discordant_negative,
        "reversal": reversal,
    }


def paired_contrasts(
    frame: pd.DataFrame,
    collateral: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    order = 0

    def append(**kwargs: Any) -> None:
        nonlocal order
        order += 1
        rows.append(_contrast_row(order=order, **kwargs))

    raw_pairs = (
        ("stable_supported", "empirical_crypto"),
        ("stable_heavy", "empirical_crypto"),
        ("stable_heavy", "stable_supported"),
    )
    for shock in SHOCK_ORDER:
        for left_portfolio, right_portfolio in raw_pairs:
            paired = _paired_system(
                frame,
                left_shock=shock,
                left_portfolio=left_portfolio,
                right_shock=shock,
                right_portfolio=right_portfolio,
            )
            for metric in SYSTEM_METRICS:
                left = paired[f"{metric}_left"]
                right = paired[f"{metric}_right"]
                append(
                    contrast_type="raw_portfolio_contrast",
                    shock=shock,
                    portfolio=left_portfolio,
                    reference_portfolio=right_portfolio,
                    comparison_shock=None,
                    family=None,
                    metric=metric,
                    direction_multiplier=1,
                    values=(left - right).to_numpy(dtype=float),
                    left_values=left,
                    right_values=right,
                )

    advantage_arrays: dict[tuple[str, str, str], np.ndarray] = {}
    for shock in SHOCK_ORDER:
        for portfolio in PORTFOLIO_ORDER[1:]:
            paired = _paired_system(
                frame,
                left_shock=shock,
                left_portfolio="empirical_crypto",
                right_shock=shock,
                right_portfolio=portfolio,
            )
            for metric in SYSTEM_METRICS:
                direction = METRIC_DIRECTIONS[metric]
                values = (
                    direction
                    * (
                        paired[f"{metric}_right"].to_numpy(dtype=float)
                        - paired[f"{metric}_left"].to_numpy(dtype=float)
                    )
                )
                # direction=-1 yields empirical - stable for lower-is-better.
                advantage_arrays[(shock, portfolio, metric)] = values
                append(
                    contrast_type="direction_normalised_advantage",
                    shock=shock,
                    portfolio=portfolio,
                    reference_portfolio="empirical_crypto",
                    comparison_shock=None,
                    family=None,
                    metric=metric,
                    direction_multiplier=direction,
                    values=values,
                )

    for portfolio in PORTFOLIO_ORDER[1:]:
        for metric in SYSTEM_METRICS:
            protection = advantage_arrays[
                ("joint_crypto_high_correlation", portfolio, metric)
            ]
            append(
                contrast_type="crypto_protection",
                shock="joint_crypto_high_correlation",
                portfolio=portfolio,
                reference_portfolio="empirical_crypto",
                comparison_shock=None,
                family=None,
                metric=metric,
                direction_multiplier=METRIC_DIRECTIONS[metric],
                values=protection,
            )
            joint = advantage_arrays[
                ("joint_crypto_stable_stress", portfolio, metric)
            ]
            append(
                contrast_type="joint_stress_advantage",
                shock="joint_crypto_stable_stress",
                portfolio=portfolio,
                reference_portfolio="empirical_crypto",
                comparison_shock=None,
                family=None,
                metric=metric,
                direction_multiplier=METRIC_DIRECTIONS[metric],
                values=joint,
            )
            erosion = protection - joint
            append(
                contrast_type="tradeoff_erosion",
                shock="joint_crypto_stable_stress",
                portfolio=portfolio,
                reference_portfolio="empirical_crypto",
                comparison_shock="joint_crypto_high_correlation",
                family=None,
                metric=metric,
                direction_multiplier=1,
                values=erosion,
            )
            joint_distribution = _distribution(joint)
            reversal = bool(
                joint_distribution["mean"] < 0.0
                and joint_distribution["ci95_upper"] < 0.0
            )
            append(
                contrast_type="reversal_flag",
                shock="joint_crypto_stable_stress",
                portfolio=portfolio,
                reference_portfolio="empirical_crypto",
                comparison_shock=None,
                family=None,
                metric=metric,
                direction_multiplier=METRIC_DIRECTIONS[metric],
                values=joint,
                reversal=reversal,
            )

    for shock in ("stable_depeg_moderate", "stable_depeg_severe"):
        for portfolio in PORTFOLIO_ORDER[1:]:
            paired = _paired_system(
                frame,
                left_shock=shock,
                left_portfolio=portfolio,
                right_shock=shock,
                right_portfolio="empirical_crypto",
            )
            for metric in SYSTEM_METRICS:
                left = paired[f"{metric}_left"]
                right = paired[f"{metric}_right"]
                values = (
                    left.to_numpy(dtype=float)
                    - right.to_numpy(dtype=float)
                ) * (-METRIC_DIRECTIONS[metric])
                append(
                    contrast_type="depeg_cost",
                    shock=shock,
                    portfolio=portfolio,
                    reference_portfolio="empirical_crypto",
                    comparison_shock=None,
                    family=None,
                    metric=metric,
                    direction_multiplier=-METRIC_DIRECTIONS[metric],
                    values=values,
                    left_values=left,
                    right_values=right,
                )

    for portfolio in PORTFOLIO_ORDER[1:]:
        paired = _paired_system(
            frame,
            left_shock="stable_depeg_severe",
            left_portfolio=portfolio,
            right_shock="stable_depeg_moderate",
            right_portfolio=portfolio,
        )
        for metric in SYSTEM_METRICS:
            values = (
                paired[f"{metric}_left"].to_numpy(dtype=float)
                - paired[f"{metric}_right"].to_numpy(dtype=float)
            ) * (-METRIC_DIRECTIONS[metric])
            append(
                contrast_type="severity_increment",
                shock="stable_depeg_severe",
                portfolio=portfolio,
                reference_portfolio=portfolio,
                comparison_shock="stable_depeg_moderate",
                family=None,
                metric=metric,
                direction_multiplier=-METRIC_DIRECTIONS[metric],
                values=values,
            )

    for shock in ("stable_depeg_moderate", "stable_depeg_severe"):
        paired = _paired_system(
            frame,
            left_shock=shock,
            left_portfolio="stable_heavy",
            right_shock=shock,
            right_portfolio="stable_supported",
        )
        for metric in SYSTEM_METRICS:
            values = (
                paired[f"{metric}_left"].to_numpy(dtype=float)
                - paired[f"{metric}_right"].to_numpy(dtype=float)
            ) * (-METRIC_DIRECTIONS[metric])
            append(
                contrast_type="exposure_gradient",
                shock=shock,
                portfolio="stable_heavy",
                reference_portfolio="stable_supported",
                comparison_shock=None,
                family=None,
                metric=metric,
                direction_multiplier=-METRIC_DIRECTIONS[metric],
                values=values,
            )

        for metric in STABLE_ATTRIBUTED_GRADIENT_METRICS:
            left, right = _paired_collateral_portfolios(
                collateral,
                shock=shock,
                left_portfolio="stable_heavy",
                right_portfolio="stable_supported",
                family="STABLE",
                metric=metric,
            )
            append(
                contrast_type="exposure_gradient",
                shock=shock,
                portfolio="stable_heavy",
                reference_portfolio="stable_supported",
                comparison_shock=None,
                family="STABLE",
                metric=f"stable_attributed_{metric}",
                direction_multiplier=1,
                values=(left - right).to_numpy(dtype=float),
                left_values=left,
                right_values=right,
            )

        for metric in STABLE_EXPOSURE_NORMALISED_GRADIENT_METRICS:
            left, right = _paired_collateral_portfolios(
                collateral,
                shock=shock,
                left_portfolio="stable_heavy",
                right_portfolio="stable_supported",
                family="STABLE",
                metric=metric,
            )
            append(
                contrast_type="exposure_gradient",
                shock=shock,
                portfolio="stable_heavy",
                reference_portfolio="stable_supported",
                comparison_shock=None,
                family="STABLE",
                metric=f"stable_{metric}",
                direction_multiplier=1,
                values=(left - right).to_numpy(dtype=float),
                left_values=left,
                right_values=right,
            )

    crypto_metrics = (
        "selected_attempts",
        "capacity_rejections",
        "liquidated_debt",
        "backlog_area",
        "maximum_backlog",
        "keeper_profit_proxy",
    )
    for portfolio in PORTFOLIO_ORDER[1:]:
        for metric in crypto_metrics:
            joint, crypto = _paired_collateral_sum(
                collateral,
                left_shock="joint_crypto_stable_stress",
                right_shock="joint_crypto_high_correlation",
                portfolio=portfolio,
                metric=metric,
                families=("ETH", "WBTC"),
            )
            append(
                contrast_type="stable_to_crypto_contagion",
                shock="joint_crypto_stable_stress",
                portfolio=portfolio,
                reference_portfolio=portfolio,
                comparison_shock="joint_crypto_high_correlation",
                family="ETH+WBTC",
                metric=metric,
                direction_multiplier=1,
                values=(joint - crypto).to_numpy(dtype=float),
                left_values=joint,
                right_values=crypto,
            )

    return pd.DataFrame(rows, columns=CONTRAST_COLUMNS)


def _contrast_lookup(
    contrasts: pd.DataFrame,
    contrast_type: str,
    portfolio: str,
    metric: str,
    *,
    shock: str | None = None,
    family: str | None = None,
) -> Mapping[str, Any]:
    selected = contrasts.loc[
        contrasts["contrast_type"].eq(contrast_type)
        & contrasts["portfolio"].eq(portfolio)
        & contrasts["metric"].eq(metric)
    ]
    if shock is not None:
        selected = selected.loc[selected["shock"].eq(shock)]
    if family is None:
        selected = selected.loc[selected["family"].isna()]
    else:
        selected = selected.loc[selected["family"].eq(family)]
    if len(selected) != 1:
        raise ValueError(
            f"Expected one C contrast: {contrast_type}/{portfolio}/{metric}."
        )
    return selected.iloc[0].to_dict()


def classify_c1(
    contrasts: pd.DataFrame,
    operationality: Mapping[str, str],
    *,
    valid: bool,
) -> tuple[str, dict[str, Any]]:
    if not valid:
        return "invalid", {"reason": "validity_gate_failed"}
    operational = [
        metric
        for metric in PRIMARY_SOLVENCY_METRICS
        if operationality.get(metric) == "operational"
    ]
    if len(operational) < 2:
        return "not_operational", {"operational_metrics": operational}
    detail: dict[str, Any] = {}
    passes = 0
    for portfolio in PORTFOLIO_ORDER[1:]:
        beneficial = []
        adverse_bad_debt = []
        for metric in operational:
            row = _contrast_lookup(
                contrasts, "crypto_protection", portfolio, metric
            )
            if row["mean"] > 0.0 and row["ci95_lower"] > 0.0:
                beneficial.append(metric)
            if "bad_debt" in metric and row["ci95_upper"] < 0.0:
                adverse_bad_debt.append(metric)
        passed = len(beneficial) >= 2 and not adverse_bad_debt
        passes += int(passed)
        detail[portfolio] = {
            "passed": passed,
            "beneficial_metrics": beneficial,
            "adverse_bad_debt_metrics": adverse_bad_debt,
        }
    classification = (
        "supported"
        if passes == 2
        else "partially_supported"
        if passes == 1
        else "not_supported"
    )
    return classification, detail


def _stable_activity(
    collateral: pd.DataFrame,
    *,
    shock: str,
    portfolio: str,
) -> dict[str, float]:
    selected = collateral.loc[
        collateral["shock"].eq(shock)
        & collateral["portfolio"].eq(portfolio)
        & collateral["family"].eq("STABLE")
    ]
    return {
        metric: float(pd.to_numeric(selected[metric], errors="raise").mean())
        for metric in (
            "unsafe_vault_count",
            "selected_attempts",
            "capacity_rejections",
            "liquidated_debt",
            "backlog_area",
            "displaced_candidates",
        )
    }


def classify_c2(
    contrasts: pd.DataFrame,
    collateral: pd.DataFrame,
    operationality: Mapping[str, str],
    *,
    valid: bool,
    negative_control_passed: bool,
) -> tuple[str, dict[str, Any]]:
    if not valid or not negative_control_passed:
        return "invalid", {"negative_control_passed": negative_control_passed}
    operational = [
        metric
        for metric in PRIMARY_SOLVENCY_METRICS
        if operationality.get(metric) == "operational"
    ]
    activity = {
        portfolio: _stable_activity(
            collateral,
            shock="stable_depeg_severe",
            portfolio=portfolio,
        )
        for portfolio in PORTFOLIO_ORDER[1:]
    }
    if not any(
        values["unsafe_vault_count"] > 0.0
        or values["liquidated_debt"] > 0.0
        or values["backlog_area"] > 0.0
        for values in activity.values()
    ):
        return "not_operational", {"stable_activity": activity}
    severity: dict[str, list[str]] = {}
    for portfolio in PORTFOLIO_ORDER[1:]:
        severity[portfolio] = [
            metric
            for metric in operational
            if (
                (
                    row := _contrast_lookup(
                        contrasts,
                        "severity_increment",
                        portfolio,
                        metric,
                    )
                )["mean"]
                > 0.0
                and row["ci95_lower"] > 0.0
            )
        ]
    exposure = [
        metric
        for metric in operational
        if (
            (
                row := _contrast_lookup(
                    contrasts,
                    "exposure_gradient",
                    "stable_heavy",
                    metric,
                    shock="stable_depeg_severe",
                )
            )["mean"]
            > 0.0
            and row["ci95_lower"] > 0.0
        )
    ]
    opposite = [
        metric
        for metric in operational
        if (
            (
                row := _contrast_lookup(
                    contrasts,
                    "exposure_gradient",
                    "stable_heavy",
                    metric,
                    shock="stable_depeg_severe",
                )
            )["mean"]
            < 0.0
            and row["ci95_upper"] < 0.0
        )
    ]
    stable_attributed = [
        metric
        for metric in STABLE_ATTRIBUTED_GRADIENT_METRICS
        if (
            (
                row := _contrast_lookup(
                    contrasts,
                    "exposure_gradient",
                    "stable_heavy",
                    f"stable_attributed_{metric}",
                    shock="stable_depeg_severe",
                    family="STABLE",
                )
            )["mean"]
            > 0.0
            and row["ci95_lower"] > 0.0
        )
    ]
    stable_attributed_opposite = [
        metric
        for metric in STABLE_ATTRIBUTED_GRADIENT_METRICS
        if (
            (
                row := _contrast_lookup(
                    contrasts,
                    "exposure_gradient",
                    "stable_heavy",
                    f"stable_attributed_{metric}",
                    shock="stable_depeg_severe",
                    family="STABLE",
                )
            )["mean"]
            < 0.0
            and row["ci95_upper"] < 0.0
        )
    ]
    exposure_normalised = [
        metric
        for metric in STABLE_EXPOSURE_NORMALISED_GRADIENT_METRICS
        if (
            (
                row := _contrast_lookup(
                    contrasts,
                    "exposure_gradient",
                    "stable_heavy",
                    f"stable_{metric}",
                    shock="stable_depeg_severe",
                    family="STABLE",
                )
            )["mean"]
            > 0.0
            and row["ci95_lower"] > 0.0
        )
    ]
    exposure_normalised_opposite = [
        metric
        for metric in STABLE_EXPOSURE_NORMALISED_GRADIENT_METRICS
        if (
            (
                row := _contrast_lookup(
                    contrasts,
                    "exposure_gradient",
                    "stable_heavy",
                    f"stable_{metric}",
                    shock="stable_depeg_severe",
                    family="STABLE",
                )
            )["mean"]
            < 0.0
            and row["ci95_upper"] < 0.0
        )
    ]
    severity_pass = all(severity[portfolio] for portfolio in severity)
    exposure_evidence = [
        *exposure,
        *(f"stable_attributed_{metric}" for metric in stable_attributed),
    ]
    exposure_pass = len(exposure_evidence) >= 2
    opposite_explained = bool(
        opposite
        and (
            stable_attributed
            or stable_attributed_opposite
            or exposure_normalised
            or exposure_normalised_opposite
        )
    )
    if severity_pass and exposure_pass:
        classification = "depeg_exposure_gradient_consistent"
    elif opposite and not exposure_evidence and not opposite_explained:
        classification = "depeg_exposure_gradient_inconsistent"
    elif severity_pass or exposure_evidence:
        classification = "depeg_exposure_gradient_partial"
    else:
        classification = "depeg_exposure_gradient_not_present"
    return classification, {
        "stable_activity": activity,
        "severity_worsening_metrics": severity,
        "severe_exposure_gradient_metrics": exposure,
        "opposite_exposure_metrics": opposite,
        "stable_attributed_exposure_gradient_metrics": stable_attributed,
        "opposite_stable_attributed_metrics": stable_attributed_opposite,
        "exposure_normalised_gradient_metrics": exposure_normalised,
        "opposite_exposure_normalised_metrics": (
            exposure_normalised_opposite
        ),
        "opposite_system_gradient_explained": opposite_explained,
    }


def classify_c3(
    contrasts: pd.DataFrame,
    collateral: pd.DataFrame,
    operationality: Mapping[str, str],
    *,
    valid: bool,
) -> tuple[str, dict[str, Any]]:
    if not valid:
        return "invalid", {"reason": "validity_gate_failed"}
    operational = [
        metric
        for metric in PRIMARY_SOLVENCY_METRICS
        if operationality.get(metric) == "operational"
    ]
    detail: dict[str, Any] = {}
    any_active = False
    reversal_present = False
    erosion_passes = 0
    any_signal = False
    for portfolio in PORTFOLIO_ORDER[1:]:
        reversals = []
        erosion = []
        for metric in operational:
            joint = _contrast_lookup(
                contrasts, "joint_stress_advantage", portfolio, metric
            )
            eroded = _contrast_lookup(
                contrasts, "tradeoff_erosion", portfolio, metric
            )
            if joint["mean"] < 0.0 and joint["ci95_upper"] < 0.0:
                reversals.append(metric)
            if eroded["mean"] > 0.0 and eroded["ci95_lower"] > 0.0:
                erosion.append(metric)
        activity = _stable_activity(
            collateral,
            shock="joint_crypto_stable_stress",
            portfolio=portfolio,
        )
        active = any(
            activity[metric] > 0.0
            for metric in (
                "unsafe_vault_count",
                "liquidated_debt",
                "backlog_area",
                "displaced_candidates",
            )
        )
        contagion_rows = contrasts.loc[
            contrasts["contrast_type"].eq("stable_to_crypto_contagion")
            & contrasts["portfolio"].eq(portfolio)
        ]
        crypto_deterioration = contagion_rows.loc[
            (
                contagion_rows["metric"].isin(
                    ("capacity_rejections", "liquidated_debt", "backlog_area")
                )
            )
            & (contagion_rows["mean"] > 0.0)
        ]["metric"].tolist()
        any_active |= active
        reversal_present |= len(reversals) >= 2 and active
        erosion_passes += int(len(erosion) >= 2)
        any_signal |= bool(erosion or crypto_deterioration)
        detail[portfolio] = {
            "reversal_metrics": reversals,
            "erosion_metrics": erosion,
            "stable_activity": activity,
            "crypto_deterioration_metrics": crypto_deterioration,
            "active_stable_channel": active,
        }
    if not any_active:
        classification = "not_operational"
    elif reversal_present:
        classification = "contagion_reversal_present"
    elif erosion_passes == 2:
        classification = "contagion_erosion_present"
    elif any_signal:
        classification = "contagion_mixed"
    else:
        classification = "contagion_not_present"
    return classification, detail


def classify_portfolio_tradeoffs(
    contrasts: pd.DataFrame,
    c1_detail: Mapping[str, Any],
    c2: str,
    c3_detail: Mapping[str, Any],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for portfolio in PORTFOLIO_ORDER[1:]:
        protected = bool(c1_detail.get(portfolio, {}).get("passed", False))
        reversed_ = len(
            c3_detail.get(portfolio, {}).get("reversal_metrics", [])
        ) >= 2
        erosion = len(
            c3_detail.get(portfolio, {}).get("erosion_metrics", [])
        ) >= 2
        severe_cost = any(
            (
                row := _contrast_lookup(
                    contrasts,
                    "depeg_cost",
                    portfolio,
                    metric,
                    shock="stable_depeg_severe",
                )
            )["mean"]
            > 0.0
            and row["ci95_lower"] > 0.0
            for metric in PRIMARY_SOLVENCY_METRICS
        )
        if protected and reversed_:
            status = "protection_with_reversal"
        elif protected and erosion:
            status = "protection_with_material_erosion"
        elif protected and severe_cost:
            status = "protection_with_limited_depeg_cost"
        elif not protected and severe_cost:
            status = "depeg_cost_without_crypto_protection"
        elif protected:
            status = "protection_without_material_depeg_cost"
        elif c2 == "not_operational":
            status = "not_operational"
        else:
            status = "mixed"
        result[portfolio] = status
    return result


def classify_h3(c1: str, c2: str, c3: str, *, valid: bool) -> str:
    if not valid or "invalid" in {c1, c2, c3}:
        return "H3_stable_tradeoff_experiment_invalid"
    if "not_operational" in {c2, c3}:
        return "H3_stable_tradeoff_experiment_not_operational"
    if (
        c1 in {"supported", "partially_supported"}
        and c2
        in {
            "depeg_exposure_gradient_consistent",
            "depeg_exposure_gradient_partial",
        }
        and c3 == "contagion_reversal_present"
    ):
        return "H3_stable_contagion_reversal_supported"
    if (
        c1 == "supported"
        and c2 == "depeg_exposure_gradient_consistent"
        and c3 in {"contagion_erosion_present", "contagion_mixed"}
    ):
        return "H3_stable_tradeoff_supported"
    supportive = sum(
        (
            c1 in {"supported", "partially_supported"},
            c2
            in {
                "depeg_exposure_gradient_consistent",
                "depeg_exposure_gradient_partial",
            },
            c3
            in {
                "contagion_reversal_present",
                "contagion_erosion_present",
                "contagion_mixed",
            },
        )
    )
    if supportive >= 2:
        return "H3_stable_tradeoff_partially_supported"
    if (
        c1 == "supported"
        and c2 == "depeg_exposure_gradient_not_present"
        and c3 == "contagion_not_present"
    ):
        return "H3_stable_support_without_material_depeg_cost"
    if (
        c1 == "not_supported"
        and c2
        in {
            "depeg_exposure_gradient_consistent",
            "depeg_exposure_gradient_partial",
        }
    ):
        return "H3_stable_depeg_cost_without_crypto_protection"
    return "H3_no_clear_stable_collateral_tradeoff"


def classify_peg_solvency(
    frame: pd.DataFrame,
    c1: str,
    c2: str,
    c3: str,
    *,
    valid: bool,
) -> str:
    if not valid:
        return "relationship_invalid"
    peg_changed = any(
        float(frame.groupby("cell_identifier")[metric].mean().max())
        - float(frame.groupby("cell_identifier")[metric].mean().min())
        > 1e-10
        for metric in PEG_METRICS
    )
    solvency_signal = c1 in {"supported", "partially_supported"} or c3 in {
        "contagion_reversal_present",
        "contagion_erosion_present",
        "contagion_mixed",
    }
    depeg_cost = c2 in {
        "depeg_exposure_gradient_consistent",
        "depeg_exposure_gradient_partial",
    }
    if not peg_changed and depeg_cost:
        return "depeg_costs_solvent_system_peg_unchanged"
    if not peg_changed and c1 in {"supported", "partially_supported"}:
        return "solvency_improves_peg_unchanged"
    if peg_changed and solvency_signal:
        return "solvency_and_peg_tradeoff"
    if peg_changed:
        return "peg_deteriorates_solvent_system_unchanged"
    return "neither_materially_changes"


def _validity_audit(
    frame: pd.DataFrame,
    checkpoints: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    failure_counts = {
        "numerical_failures": int((~frame["numerical_valid"].astype(bool)).sum()),
        "accounting_failures": int(
            (~frame["accounting_valid"].astype(bool)).sum()
        ),
        "price_isolation_failures": int(
            (~frame["price_isolation_valid"].astype(bool)).sum()
        ),
        "crn_failures": int(
            frame.groupby(["portfolio", "replication"])[
                "state_checksum"
            ].nunique().gt(1).sum()
        ),
        "registry_resolution_failures": int(
            set(frame["cell_identifier"]) != set(CELL_ORDER)
        ),
        "stable_negative_control_failures": int(
            sum(
                not checkpoint["stable_negative_control"]["passed"]
                for checkpoint in checkpoints
            )
        ),
        "checkpoint_failures": 0,
    }
    failure_counts["passed"] = not any(failure_counts.values())
    failure_counts["maximum_cell_failure_share"] = float(
        frame.assign(failed=~_valid_rows(frame))
        .groupby("cell_identifier")["failed"]
        .mean()
        .max()
    )
    if failure_counts["maximum_cell_failure_share"] > 0.01:
        failure_counts["passed"] = False
    return failure_counts


def classify_results(
    frame: pd.DataFrame,
    collateral: pd.DataFrame,
    contrasts: pd.DataFrame,
    checkpoints: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    operationality = metric_operationality(frame)
    validity = _validity_audit(frame, checkpoints)
    negative_control_passed = (
        validity["stable_negative_control_failures"] == 0
    )
    c1, c1_detail = classify_c1(
        contrasts, operationality, valid=validity["passed"]
    )
    c2, c2_detail = classify_c2(
        contrasts,
        collateral,
        operationality,
        valid=validity["passed"],
        negative_control_passed=negative_control_passed,
    )
    c3, c3_detail = classify_c3(
        contrasts,
        collateral,
        operationality,
        valid=validity["passed"],
    )
    portfolio_status = classify_portfolio_tradeoffs(
        contrasts, c1_detail, c2, c3_detail
    )
    overall = classify_h3(c1, c2, c3, valid=validity["passed"])
    peg_solvency = classify_peg_solvency(
        frame, c1, c2, c3, valid=validity["passed"]
    )
    return {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "experiment_identity": REGISTERED_EXPERIMENT_IDENTITY,
        "metric_operationality": operationality,
        "validity_audit": validity,
        "stable_negative_control": {
            "passed": negative_control_passed,
            "registered_non_vault_stable_channel": False,
            "failure_count": validity[
                "stable_negative_control_failures"
            ],
        },
        "C1": {"classification": c1, "detail": c1_detail},
        "C2": {"classification": c2, "detail": c2_detail},
        "C3": {"classification": c3, "detail": c3_detail},
        "portfolio_tradeoff_statuses": portfolio_status,
        "overall_h3_classification": overall,
        "peg_solvency_relationship": peg_solvency,
        "portfolio_selected": False,
        "shock_selected": False,
        "stable_proxy_status": "counterfactual_stable_proxy",
        "usdc_svb_used": False,
        "held_out_data_used": False,
        "next_authorised_pass": "Experiment D only",
        "experiment_e_blocked": True,
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
        "schema_version",
        "measurement_timestamp_utc",
        "execution_command",
        "worker_count",
        "smoke_wall_time_seconds",
        "full_wall_time_seconds",
        "throughput_simulations_per_second",
        "timing_method",
        "checkpoint_write_span_seconds",
        "median_worker_replication_seconds",
        "original_timer_captured",
        "completed_replications",
        "reused_replications",
        "resumed_replications",
        "failed_replications",
        "rerun_replications",
        "completed_simulations",
        "checkpoint_count",
        "output_size_bytes",
        "free_storage_bytes",
        "network_calls",
        "calibration_runs",
        "experiment_a_simulations",
        "experiment_b_simulations",
        "experiments_d_e_simulations",
        "held_out_validation_runs",
    }
    if set(benchmark) != required:
        raise ValueError("Experiment C benchmark fields differ.")
    if (
        int(benchmark["completed_replications"])
        + int(benchmark["reused_replications"])
        != REPLICATIONS
        or int(benchmark["completed_simulations"])
        != REPLICATIONS * len(CELL_ORDER)
        or int(benchmark["checkpoint_count"]) != REPLICATIONS
        or int(benchmark["output_size_bytes"]) > MAXIMUM_OUTPUT_BYTES
        or int(benchmark["free_storage_bytes"]) < MINIMUM_FREE_BYTES
        or any(
            int(benchmark[field]) != 0
            for field in (
                "failed_replications",
                "rerun_replications",
                "network_calls",
                "calibration_runs",
                "experiment_a_simulations",
                "experiment_b_simulations",
                "experiments_d_e_simulations",
                "held_out_validation_runs",
            )
        )
        or str(REPOSITORY_ROOT) in json.dumps(benchmark, sort_keys=True)
    ):
        raise ValueError("Experiment C benchmark crosses a boundary.")


def build_evidence_payloads(
    programme_identity: str,
    benchmark: Mapping[str, Any],
) -> dict[str, bytes]:
    _benchmark_validate(benchmark)
    frame, collateral = load_results(programme_identity)
    checkpoints = _load_checkpoints(programme_identity)
    cells = cell_summary(frame)
    collateral_rows = collateral_summary(collateral)
    contrasts = paired_contrasts(frame, collateral)
    decision = classify_results(
        frame, collateral, contrasts, checkpoints
    )
    audit = audit_checkpoints(programme_identity)
    regression = regression_audit()
    deterministic_payloads: dict[str, bytes] = {
        COMPACT_FILENAMES[0]: _pretty_json(
            {
                **specification_payload(programme_identity),
                "experiment_identity": experiment_identity(
                    programme_identity
                ),
            }
        ),
        COMPACT_FILENAMES[1]: _csv_bytes(_registry_frame()),
        COMPACT_FILENAMES[2]: _csv_bytes(cells),
        COMPACT_FILENAMES[3]: _csv_bytes(collateral_rows),
        COMPACT_FILENAMES[4]: _csv_bytes(contrasts),
        COMPACT_FILENAMES[5]: _pretty_json(decision),
    }
    result_checksums = {
        f"replication_{replication:03d}": checkpoint["result_checksum"]
        for replication, checkpoint in enumerate(checkpoints)
    }
    reproducibility = {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "experiment_identity": experiment_identity(programme_identity),
        "scientific_code_identity": REGISTERED_SCIENTIFIC_CODE_IDENTITY,
        "simulation_core_identity": REGISTERED_SIMULATION_CORE_IDENTITY,
        "programme_identity": programme_identity,
        "profile_identity": PROFILE_IDENTITY,
        "seed_registry_sha256": seed_registry_checksum(),
        "shock_path_checksums": {
            shock: checkpoints[0]["path_audits"][shock][
                "registered_kernel_checksums"
            ]
            for shock in SHOCK_ORDER
        },
        "completed_simulations": REPLICATIONS * len(CELL_ORDER),
        "checkpoint_audit": audit,
        "result_checksums": result_checksums,
        "evidence_checksums": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in deterministic_payloads.items()
        },
        "crn_audit": {
            "paired_stream_count": len(
                {checkpoint["paired_stream_checksum"] for checkpoint in checkpoints}
            ),
            "expected_replication_count": REPLICATIONS,
            "all_negative_controls_passed": all(
                checkpoint["stable_negative_control"]["passed"]
                for checkpoint in checkpoints
            ),
        },
        "experiment_a_unchanged": regression["a_evidence"],
        "experiment_b_unchanged": regression["b_evidence"],
        "experiment_a_checkpoints_unchanged": regression["a_checkpoints"],
        "experiment_b_checkpoints_unchanged": regression["b_checkpoints"],
        "experiments_d_e_unexecuted": True,
        "held_out_data_used": False,
        "usdc_svb_used": False,
        "runtime_adopted": False,
        "post_execution_repairs": (
            {
                "classification": (
                    "checkpoint_host_timing_validation_boundary"
                ),
                "cause": (
                    "worker_elapsed_seconds was appended after the "
                    "scientific result checksum and was initially treated "
                    "as scientific payload by checkpoint validation"
                ),
                "simulation_reexecuted": False,
                "checkpoint_content_changed": False,
                "scientific_identity_changed": False,
                "decision_rules_changed": False,
                "all_128_payloads_recovered_locally": True,
            },
            {
                "classification": (
                    "pre_registered_exposure_gradient_reporting_completion"
                ),
                "cause": (
                    "the first compact contrast build reported the system "
                    "exposure gradient but omitted the pre-registered "
                    "stable-attributed and exposure-normalised gradient "
                    "rows"
                ),
                "simulation_reexecuted": False,
                "checkpoint_content_changed": False,
                "scientific_identity_changed": False,
                "pre_registered_rule_changed": False,
                "classification_changed": False,
                "all_required_gradient_levels_reported": True,
            },
            {
                "classification": (
                    "pre_registered_c3_branch_reachability_correction"
                ),
                "cause": (
                    "active stable loss was incorrectly sufficient by "
                    "itself for the mixed branch, making the registered "
                    "contagion_not_present branch unreachable"
                ),
                "simulation_reexecuted": False,
                "checkpoint_content_changed": False,
                "scientific_identity_changed": False,
                "pre_registered_rule_changed": False,
                "classification_changed": False,
            },
        ),
    }
    deterministic_payloads[COMPACT_FILENAMES[6]] = _pretty_json(
        reproducibility
    )
    return {
        **deterministic_payloads,
        COMPACT_FILENAMES[7]: _pretty_json(benchmark),
    }


def _manifest_records(paths: Iterable[Path]) -> list[dict[str, Any]]:
    return [
        {
            "classification": (
                "pre_registered_final_stable_collateral_tradeoff_experiment"
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
    if len(preserved) != 43:
        raise ValueError("Experiment C expected 43 preserved artefacts.")
    if _payload_sha256(preserved) != BASE_MANIFEST_ARTEFACTS_SHA256:
        raise ValueError("Experiment C preserved manifest rows changed.")
    if {str(row["path"]) for row in records} != owned_paths:
        raise ValueError("Experiment C manifest ownership differs.")
    combined = sorted(
        [*preserved, *map(dict, records)],
        key=lambda row: str(row["path"]),
    )
    if len({str(row["path"]) for row in combined}) != len(combined):
        raise ValueError("Experiment manifest contains duplicates.")
    payload["artefacts"] = combined
    payload["artefact_count"] = len(combined)
    if payload["artefact_count"] != 51:
        raise ValueError("Experiment manifest must contain 51 artefacts.")
    _atomic_json(MANIFEST_PATH, payload)


def write_evidence(
    programme_identity: str,
    benchmark: Mapping[str, Any],
) -> dict[str, Any]:
    checkpoint_before = audit_checkpoints(programme_identity)
    if not checkpoint_before["complete"]:
        raise ValueError("Experiment C checkpoints are incomplete.")
    first = build_evidence_payloads(programme_identity, benchmark)
    second = build_evidence_payloads(programme_identity, benchmark)
    for name in DETERMINISTIC_FILENAMES:
        if first[name] != second[name]:
            raise ValueError(f"Experiment C evidence is not deterministic: {name}.")
    with tempfile.TemporaryDirectory(
        prefix="experiment-c-evidence-first-"
    ) as first_name, tempfile.TemporaryDirectory(
        prefix="experiment-c-evidence-second-"
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
                raise ValueError(f"Isolated Experiment C evidence differs: {name}.")
    if audit_checkpoints(programme_identity) != checkpoint_before:
        raise ValueError("Experiment C evidence changed checkpoints.")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in first.items():
        path = EVIDENCE_DIR / name
        if path.exists() and path.read_bytes() != payload:
            if name in COMPACT_FILENAMES[:2]:
                raise ValueError("Pre-registration changed after execution.")
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
    if experiment_identity(programme_identity) != REGISTERED_EXPERIMENT_IDENTITY:
        raise ValueError("Experiment C identity differs.")
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    if not all(path.is_file() for path in paths):
        raise ValueError("Experiment C compact evidence is incomplete.")
    payload = json.loads(
        (EVIDENCE_DIR / COMPACT_FILENAMES[5]).read_text(encoding="utf-8")
    )
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    records = {
        str(row["path"]): row for row in manifest["artefacts"]
    }
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
    if (
        len(registry) != 12
        or registry["cell_identifier"].tolist() != list(CELL_ORDER)
        or payload["validity_audit"]["passed"] is not True
        or payload["stable_negative_control"]["passed"] is not True
        or payload["portfolio_selected"] is not False
        or payload["runtime_adopted"] is not False
        or manifest["artefact_count"] != 51
    ):
        raise ValueError("Experiment C evidence validation failed.")
    return {
        "passed": True,
        "experiment_identity": REGISTERED_EXPERIMENT_IDENTITY,
        "artefact_count": 8,
        "manifest_artefact_count": 51,
        "registry_rows": len(registry),
        "cell_summary_rows": len(cells),
        "collateral_summary_rows": len(collateral),
        "contrast_rows": len(contrasts),
        "decision": {
            "C1": payload["C1"]["classification"],
            "C2": payload["C2"]["classification"],
            "C3": payload["C3"]["classification"],
            "overall_h3_classification": payload[
                "overall_h3_classification"
            ],
            "peg_solvency_relationship": payload[
                "peg_solvency_relationship"
            ],
        },
        "experiments_a_b_unchanged": True,
        "experiments_d_e_unexecuted": True,
        "runtime_adopted": False,
    }
