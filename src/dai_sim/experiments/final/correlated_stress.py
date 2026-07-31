"""Pre-registered Experiment B correlated-stress implementation.

This module consumes the immutable Experiment B rows from the final programme.
It reuses the frozen Experiment A initialisation, liquidation, recovery and
evidence conventions without changing Experiment A or any production default.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
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
from dai_sim.model.collateral import CollateralPortfolioConfig
from dai_sim.model.liquidation import (
    execute_keeper_liquidation,
    rank_liquidation_candidates,
)
from dai_sim.validation import multicollateral as multicollateral_validation


EXPERIMENT_B_PARENT_COMMIT = (
    "e19f57eb9b56f5dadd4a2f036dd487b36f31a4c0"
)
REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY = (
    "98d7203a607a2cb38698b4b3e3b730af89ccc2742f739202a219d8c59d1f27de"
)
REGISTERED_SIMULATION_CORE_IDENTITY = (
    "82e9c612de87bc93717fb0197b87eb01f23846737ce2cd96337e1f8fcfa55bdd"
)
REGISTERED_EXPERIMENT_IDENTITY = (
    "e02c035162f8178c96d2cae71d0a581ce813ab33526854bd5810e8e2810ead83"
)
EVIDENCE_ORDERING_REPAIR_CLASSIFICATION = (
    "evidence_row_ordering_infrastructure"
)
MASTER_PROGRAMME_IDENTITY = (
    "084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260"
)
EXPERIMENT_A_IDENTITY = (
    "a9d7c3fa5dc5da9bcf61314a57501ea5a8be506e305eee6f45afaae3131600bb"
)
EXPERIMENT_A_OPERATIONAL_CODE_IDENTITY = (
    "7cce1942e79f29aa584c1720cceaedcff003666d29dfd63d2deec299634dba0b"
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
SHOCK_EVIDENCE_SHA256 = (
    "5b5167f93f138cc08ba345f8af687d509da8c620dadbb537befcd4be22f8a750"
)
JOINT_STRESS_PROVENANCE_PATH = (
    REPOSITORY_ROOT
    / "data/provenance/validation/multicollateral_integration/"
    "multicollateral_integration_reproducibility.json"
)
JOINT_STRESS_PROVENANCE_SHA256 = (
    "e57258a9bc81f8d602a6bd7a9dbc306695a8c7bdbace84d5ba26b6b821c361f6"
)

EXPERIMENT_ID = "B_correlated_stress"
EXPERIMENT_NAMESPACE = "final-correlated-stress-v1"
EVIDENCE_DIR = (
    REPOSITORY_ROOT
    / "data/provenance/experiments/final/correlated_stress"
)
MANIFEST_PATH = REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"
BASE_MANIFEST_ARTIFACTS_SHA256 = (
    "901898c4d4fc3b0527c93c01c896e83a0af7e3972dbcec02ef8a67ef1bb3a676"
)
OUTPUT_ROOT = REPOSITORY_ROOT / "outputs/experiments/final/correlated_stress"

PORTFOLIO_ORDER = (
    "eth_only",
    "empirical_crypto",
    "balanced_crypto",
    "stable_supported",
)
SHOCK_ORDER = (
    "joint_crypto_empirical_stress",
    "joint_crypto_high_correlation",
)
CELL_ORDER = tuple(
    f"{shock}__{portfolio}"
    for shock in SHOCK_ORDER
    for portfolio in PORTFOLIO_ORDER
)
EXPECTED_MASTER_CELL_CHECKSUMS = (
    "fac35e79f80b7261a19bf7d5d91e2dd706b64d457e6daa29bb7129f38f219cb1",
    "885504b2138bccb402533e8cfe669e01af684a9e03aa10681a716a3a30f38ec6",
    "83f75da92625591a5067888d7e6353d70562572c435559e70803a6229a7987e4",
    "ac8e03c1cd788cd3b21be4ba05038b151f1dd8d12b45c06b64924d44b1699ba1",
    "d64702632587cc169dca55c7f93995f6f680cce982f33f66e99abe05133852e8",
    "00c6661013ee808c3d4083302976983c25dc9a6d6c7cd138a264dcd8f21c7a5d",
    "02a010d81c08377c94abfed711c85e4f20ebd428640112223b7ffde9d7530200",
    "a89f79d02cb8fbcfc819baf894ce12d88dbe937b8ca68bcceb237ee4714d4db0",
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
MAXIMUM_OUTPUT_BYTES = 500 * 1024**2
MINIMUM_FREE_BYTES = 10 * 1024**3

EMPIRICAL_BLOCK_END_UTC = pd.Timestamp("2022-05-12T06:00:00Z")
EMPIRICAL_BLOCK_HOURS = 24
EMPIRICAL_SOURCE_BLOCK_SHA256 = (
    "71440ef5afbc1797989fd716a9efd9a7ea72de3e6638c0359707f048c1c493bc"
)
EMPIRICAL_MEDIAN_GAS_PATH_SHA256 = (
    "13b0c22c442833b7d72ca08f30c49364f0f193f8d3756d496656c3fa534ebce1"
)
EMPIRICAL_GAS_EMBED_START = PRE_SHOCK_HOURS
EMPIRICAL_GAS_COLUMNS = (
    "median_effective_gas_price_gwei",
    "p90_effective_gas_price_gwei",
    "p99_effective_gas_price_gwei",
    "target_normalised_block_utilisation",
)
INITIALISATION_REPLICATION_OFFSET = 1_000_000

SEED_STREAMS = (
    "initialisation_master",
    "market_gas_blocks",
    "keeper_gas_units",
    "liquidation_arrivals",
    "stage1_residual_blocks",
)
SYSTEM_METRICS = experiment_a.SYSTEM_METRICS
SYSTEM_DIAGNOSTICS = (
    *experiment_a.SYSTEM_DIAGNOSTICS,
    "hours_one_unsafe_family",
    "hours_at_least_two_unsafe_families",
    "hours_all_applicable_volatile_families_unsafe",
    "hours_eth_wbtc_simultaneously_unsafe",
    "share_hours_eth_wbtc_simultaneously_unsafe",
    "maximum_simultaneous_active_backlog_families",
)
BINARY_METRICS = experiment_a.BINARY_METRICS
ZERO_HEAVY_METRICS = experiment_a.ZERO_HEAVY_METRICS
COLLATERAL_METRICS = (
    *experiment_a.COLLATERAL_METRICS,
    "simultaneous_unsafe_hours",
    "maximum_backlog",
)
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
OUTCOME_DEFINITIONS = {
    "realised_bad_debt_share": (
        "sum post-shock realised bad debt / initial system debt"
    ),
    "positive_realised_bad_debt": (
        "indicator(sum post-shock realised bad debt > 1e-9)"
    ),
    "active_bad_debt_share": (
        "terminal active bad debt / initial system debt"
    ),
    "unresolved_tab_share": (
        "maximum post-shock unresolved liquidation tab / initial system debt"
    ),
    "backlog_area_share": (
        "sum hourly post-shock unresolved tab / initial system debt"
    ),
    "liquidated_debt_share": (
        "sum post-shock keeper-repaid debt / initial system debt"
    ),
    "debt_weighted_liquidated_vault_share": (
        "initial debt of unique post-shock liquidated vaults / initial debt"
    ),
    "successful_closure_count": (
        "sum post-shock fully liquidated vault closures"
    ),
    "capacity_rejected_opportunities": (
        "sum post-shock demand selected minus shared-capacity attempts"
    ),
    "below_peg_burden": "owned sustained-recovery market summary",
    "mean_absolute_peg_deviation": "owned sustained-recovery market summary",
    "minimum_dai_price": "owned sustained-recovery market summary",
    "restricted_mean_recovery_time": (
        "owned 720-hour capped sustained-recovery RMST"
    ),
    "recovery_probability_720h": (
        "owned sustained-recovery indicator by 720 post-shock hours"
    ),
}
DIAGNOSTIC_DEFINITIONS = {
    "positive_demand_hours": "post-shock hours with sampled arrivals > 0",
    "binding_hours": (
        "post-shock hours with at least one capacity-rejected opportunity"
    ),
    "mean_capacity_utilisation": (
        "mean post-shock selected attempts / shared capacity 26"
    ),
    "maximum_capacity_utilisation": (
        "maximum post-shock selected attempts / shared capacity 26"
    ),
    "maximum_simultaneously_unsafe_families": (
        "maximum number of candidate families before execution"
    ),
    "maximum_backlog_duration": (
        "longest post-shock run of positive system unresolved tab"
    ),
    "hours_one_unsafe_family": (
        "post-shock hours with exactly one unsafe family"
    ),
    "hours_at_least_two_unsafe_families": (
        "post-shock hours with at least two unsafe families"
    ),
    "hours_all_applicable_volatile_families_unsafe": (
        "post-shock hours where every positive-exposure ETH/WBTC family "
        "is unsafe; ETH-only therefore has one applicable family"
    ),
    "hours_eth_wbtc_simultaneously_unsafe": (
        "post-shock hours where both ETH and WBTC are unsafe"
    ),
    "share_hours_eth_wbtc_simultaneously_unsafe": (
        "simultaneous ETH/WBTC unsafe hours / fixed 720-hour window"
    ),
    "maximum_simultaneous_active_backlog_families": (
        "maximum families with post-execution backlog above 1e-9 DAI"
    ),
}
METRIC_DIRECTIONS = {
    **{metric: -1 for metric in SYSTEM_METRICS},
    "minimum_dai_price": 1,
    "recovery_probability_720h": 1,
}
RAW_PORTFOLIO_CONTRASTS = (
    ("empirical_crypto", "eth_only"),
    ("balanced_crypto", "eth_only"),
    ("stable_supported", "eth_only"),
    ("balanced_crypto", "empirical_crypto"),
    ("stable_supported", "empirical_crypto"),
    ("stable_supported", "balanced_crypto"),
)
DIVERSIFIED_PORTFOLIOS = PORTFOLIO_ORDER[1:]

# Frozen before substantive execution. Debt thresholds reuse the constrained
# recovery study and are expressed as shares of the fixed 2.5m DAI system.
MATERIALITY_THRESHOLDS = {
    "realised_bad_debt_share": 1_000.0 / TOTAL_DEBT_DAI,
    "active_bad_debt_share": 1_000.0 / TOTAL_DEBT_DAI,
    "unresolved_tab_share": 1_000.0 / TOTAL_DEBT_DAI,
    "backlog_area_share": 10_000.0 / TOTAL_DEBT_DAI,
    "liquidated_debt_share": 1_000.0 / TOTAL_DEBT_DAI,
    "below_peg_burden": 0.01,
    "mean_absolute_peg_deviation": 0.0001,
    "minimum_dai_price": 0.0001,
    "restricted_mean_recovery_time": 24.0,
    "recovery_probability_720h": 0.01,
}
IDENTIFICATION_LIMITATION = (
    "B2 compares the two frozen registered joint-stress bundles. The smooth "
    "ETH and WBTC multiplier kernels co-move closely and differ in severity "
    "and recovery as registered, while the empirical treatment also owns its "
    "selected gas block. B2 therefore identifies deterioration across the "
    "registered bundles, not a pure causal correlation coefficient."
)

COMPACT_FILENAMES = (
    "correlated_stress_specification.json",
    "correlated_stress_registry.csv",
    "correlated_stress_cell_summary.csv",
    "correlated_stress_collateral_summary.csv",
    "correlated_stress_contrasts.csv",
    "correlated_stress_decision.json",
    "correlated_stress_reproducibility.json",
    "correlated_stress_benchmark.json",
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
    "minimum",
    "maximum",
    "positive_share",
)
OPERATIONALITY_STATUSES = {
    "operational",
    "degenerate",
    "not_operational",
    "invalid",
}
REGISTRY_COLUMNS = (
    "order",
    "identifier",
    "shock",
    "portfolio",
    "capacity",
    "hurdle",
    "confidence",
    "oracle_delay",
    "replication_count",
    "master_row_checksum",
)
CELL_SUMMARY_COLUMNS = (
    "cell_order",
    "cell_identifier",
    "shock",
    "portfolio",
    "metric",
    "operationality",
    "valid_replication_count",
    *DISTRIBUTION_FIELDS,
    "censoring_count",
    "numerical_failure_count",
)
COLLATERAL_SUMMARY_COLUMNS = (
    "cell_order",
    "cell_identifier",
    "shock",
    "portfolio",
    "family",
    "metric",
    "applicable_replication_count",
    "not_applicable_replication_count",
    "invalid_replication_count",
    *DISTRIBUTION_FIELDS,
)
CONTRAST_COLUMNS = (
    "contrast_type",
    "shock",
    "portfolio",
    "left_portfolio",
    "right_portfolio",
    "contrast",
    "metric",
    "direction_multiplier",
    "operationality",
    "reversal_flag",
    "pair_count",
    *DISTRIBUTION_FIELDS,
    "paired_probability_difference",
    "discordant_left_one_right_zero",
    "discordant_left_zero_right_one",
    "empirical_discordant_left_one_right_zero",
    "empirical_discordant_left_zero_right_one",
    "high_correlation_discordant_left_one_right_zero",
    "high_correlation_discordant_left_zero_right_one",
)

EXPERIMENT_A_EVIDENCE_CHECKSUMS = {
    "idiosyncratic_diversification_specification.json": (
        "e6da0af839c53ddffb6eeaea596174d26499afeb55ca0d1910be49c679cd740d"
    ),
    "idiosyncratic_diversification_registry.csv": (
        "59eb120b572a09c8cd863f180f735b227d21cbe0b5664c4d94a696ed51ad6840"
    ),
    "idiosyncratic_diversification_cell_summary.csv": (
        "db7de25363c4d93b7b5876f0fcfd36d8f87c9ee61505d78db967c9bfc9539350"
    ),
    "idiosyncratic_diversification_collateral_summary.csv": (
        "e45144f1d580cef241dd8a261b71bef4e53fb4b3914a1ad1c46c5da30631aea8"
    ),
    "idiosyncratic_diversification_contrasts.csv": (
        "26a048115e555f0c846858eeac019197356ac5e36d20667f187edd6046cb845b"
    ),
    "idiosyncratic_diversification_decision.json": (
        "cf720d855adc62c5270042f9d2cb85338ef14d7d80a2aa8cb70f7d0dc7b9f614"
    ),
    "idiosyncratic_diversification_reproducibility.json": (
        "d04a955c843b831ae95e9b4a9326b1cb65211041a12121b3e74b98922f562fe7"
    ),
    "idiosyncratic_diversification_benchmark.json": (
        "27820f78457d641e847efcee028377394dacf695ed6bb1597f0647b4a1679faa"
    ),
}
EXPERIMENT_A_CHECKPOINT_COUNT = 128
EXPERIMENT_A_CHECKPOINT_BYTES = 5_690_327
EXPERIMENT_A_CHECKPOINT_CONTENT_MAP_SHA256 = (
    "8604a23f49dcbdfc6e7e86de70beaf7960e1dd89903d1a1ecd60d6fd5a348c66"
)


def _frozen_experiment_a_checkpoint_snapshot() -> dict[str, Any]:
    return {
        "checkpoint_count": EXPERIMENT_A_CHECKPOINT_COUNT,
        "content_map_sha256": (
            EXPERIMENT_A_CHECKPOINT_CONTENT_MAP_SHA256
        ),
        "total_bytes": EXPERIMENT_A_CHECKPOINT_BYTES,
    }


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        to_json_compatible(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _row_checksum(row: Mapping[str, Any]) -> str:
    return _payload_sha256(dict(row))


def _pretty_json(payload: Any) -> bytes:
    return (
        json.dumps(
            to_json_compatible(payload),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_bytes(path: Path, payload: bytes) -> None:
    experiment_a._atomic_bytes(path, payload)


def _atomic_json(path: Path, payload: Any) -> None:
    _atomic_bytes(path, _pretty_json(payload))


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return experiment_a._csv_bytes(frame)


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()


def derive_seed(replication: int, stream: str, substream: str = "") -> int:
    """Derive one treatment-invariant 64-bit Experiment B seed."""
    if stream not in SEED_STREAMS:
        raise ValueError(f"Unknown Experiment B seed stream: {stream}.")
    if isinstance(replication, bool) or replication < 0:
        raise ValueError("replication must be a non-negative integer.")
    return int.from_bytes(
        hashlib.sha256(
            _canonical_json(
                {
                    "registry_id": EXPERIMENT_NAMESPACE,
                    "replication": int(replication),
                    "stream": stream,
                    "substream": str(substream),
                    "version": 1,
                }
            )
        ).digest()[:8],
        "big",
    )


def initialisation_replication_key(replication: int) -> int:
    """Map B replications into a disjoint Experiment A draw-key range."""
    if isinstance(replication, bool) or not 0 <= replication < REPLICATIONS:
        raise ValueError("Experiment B replication lies outside [0, 127].")
    return INITIALISATION_REPLICATION_OFFSET + int(replication)


def seed_record(replication: int) -> dict[str, Any]:
    key = initialisation_replication_key(replication)
    record = {
        "replication": replication,
        "registry_id": EXPERIMENT_NAMESPACE,
        "initialisation_replication_key": key,
        "initialisation_master_seed": experiment_a.derive_seed(
            key, "initialisation_master"
        ),
        "initialisation_family_seed_rule": (
            "Experiment A derive_seed(initialisation_replication_key, "
            "'vault_<family>', "
            "'master:<master_seed>:attempt:<accepted_attempt>')"
        ),
        **{
            f"{stream}_seed": derive_seed(replication, stream)
            for stream in SEED_STREAMS
            if stream != "initialisation_master"
        },
    }
    return {**record, "seed_record_checksum": _payload_sha256(record)}


def seed_registry_checksum(replications: int = REPLICATIONS) -> str:
    return _payload_sha256(
        [seed_record(replication) for replication in range(replications)]
    )


@dataclass(frozen=True)
class ExperimentBCell:
    """One immutable master-programme Experiment B cell."""

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
            raise ValueError(f"Frozen Experiment B cell field changed: {name}.")
    if (
        cell.portfolio_identifier not in PORTFOLIO_ORDER
        or cell.shock_identifier not in SHOCK_ORDER
    ):
        raise ValueError("Experiment B contains an unregistered treatment.")


def build_cell_registry(
    owner: FinalExperimentProgramme | None = None,
) -> tuple[ExperimentBCell, ...]:
    """Derive the exact eight-cell B registry from the frozen programme."""
    programme = load_programme() if owner is None else owner
    if programme.programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Master programme identity changed.")
    experiment = programme.experiments_by_identifier[EXPERIMENT_ID]
    if (
        experiment.order != 2
        or experiment.primary_research_question != "RQ4"
        or experiment.primary_hypothesis != "H3"
        or experiment.replication_count != REPLICATIONS
        or experiment.execution_status != "preregistered_not_executed"
        or experiment.dependency_status != "frozen_inputs_ready"
    ):
        raise ValueError("Frozen Experiment B programme metadata changed.")
    cells: list[ExperimentBCell] = []
    for source in experiment.cells:
        _validate_master_cell(source)
        cells.append(
            ExperimentBCell(
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
        raise ValueError("Experiment B cell order differs.")
    if tuple(cell.master_row_checksum for cell in cells) != (
        EXPECTED_MASTER_CELL_CHECKSUMS
    ):
        raise ValueError("Experiment B master-row checksum differs.")
    return tuple(cells)


def _market_pool() -> pd.DataFrame:
    profile = resolve_multicollateral_inputs("eth_only").profile
    return load_final_market_pool(
        profile.market_pool_path, profile.market_pool_sha256
    )


def _empirical_source_block(
    market_pool: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return the selected 24-hour source block ending at the frozen timestamp."""
    pool = _market_pool() if market_pool is None else market_pool.copy()
    timestamps = pd.to_datetime(pool["timestamp_utc"], utc=True)
    matches = np.flatnonzero(
        timestamps.eq(EMPIRICAL_BLOCK_END_UTC).to_numpy()
    )
    if len(matches) != 1:
        raise ValueError("Frozen empirical block endpoint is not unique.")
    stop = int(matches[0]) + 1
    start = stop - EMPIRICAL_BLOCK_HOURS
    if start < 0:
        raise ValueError("Frozen empirical block is incomplete.")
    block = pool.iloc[start:stop].copy().reset_index(drop=True)
    block_timestamps = pd.to_datetime(block["timestamp_utc"], utc=True)
    expected = pd.date_range(
        end=EMPIRICAL_BLOCK_END_UTC,
        periods=EMPIRICAL_BLOCK_HOURS,
        freq="h",
    )
    if not block_timestamps.equals(pd.Series(expected)):
        raise ValueError("Frozen empirical block is not hourly contiguous.")
    if not block["is_calibration"].astype(bool).all():
        raise ValueError("Frozen empirical block entered final validation.")
    if not block["return_observation_valid"].astype(bool).all():
        raise ValueError("Frozen empirical block contains invalid returns.")
    return block


def empirical_source_block_checksum(
    market_pool: pd.DataFrame | None = None,
) -> str:
    block = _empirical_source_block(market_pool)
    columns = (
        "pool_row_id",
        "timestamp_utc",
        "eth_log_return",
        "wbtc_log_return",
        *EMPIRICAL_GAS_COLUMNS,
    )
    records = block.loc[:, columns].copy()
    records["timestamp_utc"] = pd.to_datetime(
        records["timestamp_utc"], utc=True
    ).map(pd.Timestamp.isoformat)
    checksum = _payload_sha256(records.to_dict(orient="records"))
    if checksum != EMPIRICAL_SOURCE_BLOCK_SHA256:
        raise ValueError("Frozen empirical source-block identity changed.")
    return checksum


def _registered_shock_frame() -> pd.DataFrame:
    evidence = experiment_a._shock_evidence()
    _, _, shock_payload, _ = multicollateral_validation._design_payloads()
    resolved, _ = multicollateral_validation.shock_registry_frame(
        shock_payload, _market_pool()
    )
    if multicollateral_validation._csv_bytes(resolved) != (
        experiment_a.SHOCK_EVIDENCE_PATH.read_bytes()
    ):
        raise ValueError("Frozen shock registry does not reconstruct exactly.")
    if not resolved["row_checksum"].equals(evidence["row_checksum"]):
        raise ValueError("Frozen shock row checksums differ.")
    return resolved


def registered_shock_kernels(shock: str) -> dict[str, np.ndarray]:
    """Reconstruct exact B multiplier kernels from the frozen registry."""
    if shock not in SHOCK_ORDER:
        raise ValueError(f"Unexpected Experiment B shock: {shock}.")
    selected = _registered_shock_frame().loc[
        lambda frame: frame["shock_identifier"].eq(shock)
    ]
    kernels: dict[str, np.ndarray] = {}
    for family in FAMILY_ORDER:
        row = selected.loc[selected["family"].eq(family)]
        if len(row) != 1:
            raise ValueError(f"Missing one frozen {shock}/{family} row.")
        values = row.iloc[0]
        if int(values["onset_hour"]) != REGISTERED_KERNEL_ONSET:
            raise ValueError("Frozen shock-kernel onset changed.")
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
            raise ValueError(f"Frozen {shock}/{family} kernel checksum differs.")
        kernels[family] = kernel
    return kernels


def _embedded_multipliers(shock: str) -> dict[str, np.ndarray]:
    return {
        family: experiment_a.embed_registered_kernel(kernel)
        for family, kernel in registered_shock_kernels(shock).items()
    }


def _rolling_minimum_24h_log_return(values: np.ndarray) -> float:
    log_returns = np.diff(np.log(np.asarray(values, dtype=float)), prepend=0.0)
    rolling = pd.Series(log_returns).rolling(24, min_periods=24).sum()
    return float(rolling.min())


def _resolved_rolling_minimum_24h_log_return(
    values: np.ndarray,
) -> float:
    prices = np.asarray(values, dtype=float)
    log_returns = np.diff(np.log(prices), prepend=np.log(prices[0]))
    rolling = pd.Series(log_returns).rolling(24, min_periods=24).sum()
    return float(rolling.min())


def _path_diagnostics(
    shock: str,
    multipliers: Mapping[str, np.ndarray],
    gas_rows: pd.DataFrame,
    empirical_block: pd.DataFrame,
) -> dict[str, Any]:
    eth = np.asarray(multipliers["ETH"], dtype="<f8")
    wbtc = np.asarray(multipliers["WBTC"], dtype="<f8")
    stable = np.asarray(multipliers["STABLE"], dtype="<f8")
    eth_returns = np.diff(np.log(eth), prepend=0.0)
    wbtc_returns = np.diff(np.log(wbtc), prepend=0.0)
    stress = slice(PRE_SHOCK_HOURS, PRE_SHOCK_HOURS + 169)
    treatment_correlation = float(
        np.corrcoef(eth_returns[stress], wbtc_returns[stress])[0, 1]
    )
    source_eth = pd.to_numeric(
        empirical_block["eth_log_return"], errors="raise"
    ).to_numpy(dtype=float)
    source_wbtc = pd.to_numeric(
        empirical_block["wbtc_log_return"], errors="raise"
    ).to_numpy(dtype=float)
    source_correlation = float(np.corrcoef(source_eth, source_wbtc)[0, 1])
    source_joint_negative = int(
        np.count_nonzero((source_eth < 0.0) & (source_wbtc < 0.0))
    )
    selected_gas = pd.to_numeric(
        gas_rows.iloc[
            EMPIRICAL_GAS_EMBED_START : (
                EMPIRICAL_GAS_EMBED_START + EMPIRICAL_BLOCK_HOURS
            )
        ]["median_effective_gas_price_gwei"],
        errors="raise",
    ).to_numpy(dtype=float)
    if not np.array_equal(stable, np.ones(TOTAL_HOURS, dtype="<f8")):
        raise ValueError("Stable multiplier path is not ordinary.")
    if not np.isfinite(treatment_correlation):
        raise ValueError("Treatment correlation diagnostic is not finite.")
    combined_path_checksum = _payload_sha256(
        {
            "shock": shock,
            "embedded_multiplier_checksums": {
                family: hashlib.sha256(
                    np.asarray(multipliers[family], dtype="<f8").tobytes()
                ).hexdigest()
                for family in FAMILY_ORDER
            },
            "gas_owner": (
                "selected_empirical_24h_block"
                if shock == "joint_crypto_empirical_stress"
                else "ordinary_common_market_blocks"
            ),
            "empirical_source_block_sha256": (
                empirical_source_block_checksum()
                if shock == "joint_crypto_empirical_stress"
                else None
            ),
        }
    )
    return {
        "shock": shock,
        "registered_kernel_onset_hour": REGISTERED_KERNEL_ONSET,
        "kernel_embedding_start_hour": KERNEL_EMBEDDING_START,
        "experiment_shock_hour": PRE_SHOCK_HOURS,
        "registered_kernel_checksums": {
            family: hashlib.sha256(
                np.asarray(registered_shock_kernels(shock)[family], dtype="<f8")
                .tobytes()
            ).hexdigest()
            for family in FAMILY_ORDER
        },
        "embedded_multiplier_checksums": {
            family: hashlib.sha256(
                np.asarray(multipliers[family], dtype="<f8").tobytes()
            ).hexdigest()
            for family in FAMILY_ORDER
        },
        "path_checksum": combined_path_checksum,
        "treatment_kernel_eth_24h_minimum_log_return": (
            _rolling_minimum_24h_log_return(eth)
        ),
        "treatment_kernel_wbtc_24h_minimum_log_return": (
            _rolling_minimum_24h_log_return(wbtc)
        ),
        "treatment_kernel_eth_wbtc_return_correlation_stress_window": (
            treatment_correlation
        ),
        "selected_source_block_eth_wbtc_return_correlation": source_correlation,
        "selected_source_block_joint_negative_hours": source_joint_negative,
        "treatment_kernel_hours_both_negative_returns": int(
            np.count_nonzero(
                (eth_returns[stress] < 0.0)
                & (wbtc_returns[stress] < 0.0)
            )
        ),
        "treatment_kernel_hours_both_below_registered_stress_thresholds": int(
            np.count_nonzero(
                (eth[stress] <= np.min(eth) + 1e-15)
                & (wbtc[stress] <= np.min(wbtc) + 1e-15)
            )
        ),
        "treatment_kernel_maximum_simultaneous_drawdown": float(
            np.max((1.0 - eth[stress]) + (1.0 - wbtc[stress]))
        ),
        "gas_owner": (
            "selected_empirical_24h_block"
            if shock == "joint_crypto_empirical_stress"
            else "ordinary_common_market_blocks"
        ),
        "gas_stress_summary": {
            "count": len(selected_gas),
            "mean_gwei": float(np.mean(selected_gas)),
            "median_gwei": float(np.median(selected_gas)),
            "p95_gwei": float(np.quantile(selected_gas, 0.95)),
            "maximum_gwei": float(np.max(selected_gas)),
            "path_sha256": hashlib.sha256(
                np.asarray(selected_gas, dtype="<f8").tobytes()
            ).hexdigest(),
        },
        "empirical_source_block_sha256": (
            empirical_source_block_checksum()
            if shock == "joint_crypto_empirical_stress"
            else None
        ),
        "empirical_source_block_start_utc": (
            pd.Timestamp(
                empirical_block.iloc[0]["timestamp_utc"]
            ).isoformat()
            if shock == "joint_crypto_empirical_stress"
            else None
        ),
        "empirical_source_block_end_utc": (
            pd.Timestamp(
                empirical_block.iloc[-1]["timestamp_utc"]
            ).isoformat()
            if shock == "joint_crypto_empirical_stress"
            else None
        ),
        "stable_ordinary_multiplier_valid": True,
        "registered_joint_treatment_definition_valid": True,
        "price_isolation_valid": bool(
            set(multipliers) == set(FAMILY_ORDER)
            and np.array_equal(
                stable, np.ones(TOTAL_HOURS, dtype="<f8")
            )
        ),
        "final_validation_data_used": bool(
            not gas_rows["is_calibration"].astype(bool).all()
            if "is_calibration" in gas_rows
            else True
        ),
    }


def build_treatment_paths(
    sampled_market: pd.DataFrame,
    shock: str,
) -> tuple[dict[str, np.ndarray], pd.DataFrame, dict[str, Any]]:
    """Build one frozen price treatment and its explicit gas owner."""
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
    multipliers = _embedded_multipliers(shock)
    paths = {
        "ETH": ordinary["ETH"] * multipliers["ETH"],
        "BTC": ordinary["BTC"] * multipliers["WBTC"],
        "STABLE": ordinary["STABLE"] * multipliers["STABLE"],
    }
    for values in paths.values():
        if not np.isfinite(values).all() or np.any(values <= 0.0):
            raise ValueError("Experiment B price path is invalid.")
    gas_rows = sampled_market.copy()
    source_block = _empirical_source_block()
    if shock == "joint_crypto_empirical_stress":
        source = source_block.loc[:, EMPIRICAL_GAS_COLUMNS].reset_index(drop=True)
        start = EMPIRICAL_GAS_EMBED_START
        stop = start + EMPIRICAL_BLOCK_HOURS
        gas_rows.loc[
            gas_rows.index[start:stop], list(EMPIRICAL_GAS_COLUMNS)
        ] = source.to_numpy()
    audit = _path_diagnostics(shock, multipliers, gas_rows, source_block)
    eth_returns = np.diff(
        np.log(np.asarray(paths["ETH"], dtype=float)),
        prepend=np.log(float(paths["ETH"][0])),
    )
    wbtc_returns = np.diff(
        np.log(np.asarray(paths["BTC"], dtype=float)),
        prepend=np.log(float(paths["BTC"][0])),
    )
    stress = slice(PRE_SHOCK_HOURS, PRE_SHOCK_HOURS + 169)
    audit.update(
        {
            "eth_24h_minimum_log_return": (
                _resolved_rolling_minimum_24h_log_return(paths["ETH"])
            ),
            "wbtc_24h_minimum_log_return": (
                _resolved_rolling_minimum_24h_log_return(paths["BTC"])
            ),
            "eth_wbtc_return_correlation_stress_window": float(
                np.corrcoef(
                    eth_returns[stress], wbtc_returns[stress]
                )[0, 1]
            ),
            "hours_both_negative_treatment_returns": int(
                np.count_nonzero(
                    (eth_returns[stress] < 0.0)
                    & (wbtc_returns[stress] < 0.0)
                )
            ),
            "hours_both_below_registered_stress_thresholds": audit[
                "treatment_kernel_hours_both_below_registered_stress_thresholds"
            ],
            "maximum_simultaneous_drawdown": audit[
                "treatment_kernel_maximum_simultaneous_drawdown"
            ],
            "resolved_path_diagnostics": True,
        }
    )
    if not np.isfinite(
        audit["eth_wbtc_return_correlation_stress_window"]
    ):
        raise ValueError("Resolved Experiment B path correlation is invalid.")
    audit["full_price_checksums"] = {
        family: hashlib.sha256(
            np.asarray(
                paths["BTC" if family == "WBTC" else family], dtype="<f8"
            ).tobytes()
        ).hexdigest()
        for family in FAMILY_ORDER
    }
    audit["gas_environment_checksum"] = _payload_sha256(
        gas_rows.loc[:, EMPIRICAL_GAS_COLUMNS].to_dict(orient="records")
    )
    return paths, gas_rows, audit


def _arrival_stream(*, replication: int, horizon: int) -> dict[str, Any]:
    integrated = resolve_integrated_empirical_eth_profile()
    config = integrated.liquidation_demand
    pool = load_liquidation_arrival_pool(config.pool_path, config.pool_sha256)
    positive = pool.loc[
        pool["positive_count_eligible"].astype(bool), "grab_count"
    ].to_numpy(dtype=int)
    rng = np.random.default_rng(
        derive_seed(replication, "liquidation_arrivals")
    )
    uniforms = rng.random(horizon)
    counts = rng.choice(positive, size=horizon, replace=True)
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


def _demand_decision(
    *,
    step: int,
    inventory: int,
    uniform: float,
    positive_count: int,
    hurdle_probability: float,
) -> Any:
    if inventory == 0:
        active = False
        sampled = 0
    else:
        active = bool(uniform < hurdle_probability)
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


def _family(value: str) -> str:
    return "WBTC" if value == "BTC" else value


def _max_run(values: Sequence[bool]) -> int:
    maximum = current = 0
    for value in values:
        current = current + 1 if value else 0
        maximum = max(maximum, current)
    return maximum


def _prepare_replication_streams(replication: int) -> dict[str, Any]:
    state_key = initialisation_replication_key(replication)
    states = experiment_a.initialise_nested_portfolios(state_key)
    accepted_attempts = {
        int(state.accepted_attempt) for state in states.values()
    }
    if len(accepted_attempts) != 1:
        raise ValueError("Portfolio initialisation attempts differ.")
    accepted_attempt = next(iter(accepted_attempts))
    master_seed = experiment_a.derive_seed(
        state_key, "initialisation_master"
    )
    actual_family_seeds = {
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
    arrivals = _arrival_stream(replication=replication, horizon=TOTAL_HOURS)
    _, _, stage1 = experiment_a.load_stage1_owners()
    residual_rng = np.random.default_rng(
        derive_seed(replication, "stage1_residual_blocks")
    )
    residuals = experiment_a.sample_residual_blocks(
        stage1["source"],
        block_count=math.ceil(TOTAL_HOURS / 24),
        rng=residual_rng,
    )[:TOTAL_HOURS]
    market_provenance = {
        "block_length_hours": block_length,
        "n_blocks": block_count,
        "sampled_start_indexes": [int(value) for value in chosen_starts],
        "replacement_used": True,
        "final_truncated_block_length": int(
            TOTAL_HOURS - block_length * (block_count - 1)
        ),
        "available_block_start_count": len(starts),
        "pool_label": "all_calibration",
        "segment_bounded": True,
    }
    components = {
        "initialisation_replication_key": state_key,
        "initialisation_master_seed": master_seed,
        "initialisation_accepted_attempt": accepted_attempt,
        "initialisation_family_seeds": actual_family_seeds,
        "state_identities": {
            name: state.identity for name, state in states.items()
        },
        "market_start_indexes": market_provenance[
            "sampled_start_indexes"
        ],
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
        "sampled_market": sampled,
        "market_provenance": market_provenance,
        "arrivals": arrivals,
        "stage1": stage1,
        "residuals": residuals,
        "seed_ownership": seed_record(replication),
        "actual_initialisation_seed_ownership": {
            "accepted_attempt": accepted_attempt,
            "family_seeds": actual_family_seeds,
            "checksum": _payload_sha256(
                {
                    "accepted_attempt": accepted_attempt,
                    "family_seeds": actual_family_seeds,
                }
            ),
        },
        "stream_components": components,
        "paired_stream_checksum": _payload_sha256(components),
    }


def _simulate_cell_liquidations(
    *,
    initialisation: Any,
    price_paths: Mapping[str, np.ndarray],
    gas_costs: np.ndarray,
    arrivals: Mapping[str, Any],
    portfolio_config: CollateralPortfolioConfig,
) -> dict[str, Any]:
    """Compose canonical keeper mechanics and B transmission diagnostics."""
    vaults = deepcopy(list(initialisation.vaults))
    vault_by_id = {int(vault.vault_id): vault for vault in vaults}
    if len(vault_by_id) != len(vaults):
        raise ValueError("Initial vault identifiers are not unique.")
    integrated = resolve_integrated_empirical_eth_profile()
    base_liquidation = integrated.bundle.base_bundle.liquidation_config
    array_names = {
        "liquidatable_before": "<i8",
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
    }
    arrays = {
        name: np.zeros(TOTAL_HOURS, dtype=dtype)
        for name, dtype in array_names.items()
    }
    family_arrays = {
        family: {
            name: np.zeros(TOTAL_HOURS, dtype="<f8")
            for name in (
                "unsafe",
                "arrivals",
                "attempts",
                "capacity_rejections",
                "successful",
                "closures",
                "liquidated_debt",
                "backlog",
                "active_bad_debt",
                "realised_bad_debt",
                "terminal_debt_writeoff",
                "keeper_profit",
                "displaced_candidates",
                "simultaneous_unsafe",
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
    unsafe_ever = {family: set() for family in FAMILY_ORDER}
    applicable_volatile = {
        family for family in ("ETH", "WBTC") if initial_debt[family] > 0.0
    }
    closed_ids: set[int] = set()
    liquidated_initial_debt_ids: set[int] = set()
    removed_collateral = defaultdict(float)
    repaid_debt = defaultdict(float)
    terminal_debt_writeoff = defaultdict(float)
    unsafe_family_counts = np.zeros(TOTAL_HOURS, dtype="<i8")
    simultaneous_eth_wbtc = np.zeros(TOTAL_HOURS, dtype=bool)
    all_applicable_volatile_unsafe = np.zeros(TOTAL_HOURS, dtype=bool)
    active_backlog_family_counts = np.zeros(TOTAL_HOURS, dtype="<i8")
    duplicate_attempt = False
    duplicate_closure = False
    reconciliation_failures = 0

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
        unsafe_families = {
            _family(vault.collateral_type) for vault in candidates
        }
        unsafe_family_counts[step] = len(unsafe_families)
        simultaneous_eth_wbtc[step] = {
            "ETH",
            "WBTC",
        }.issubset(unsafe_families)
        all_applicable_volatile_unsafe[step] = bool(
            applicable_volatile
            and applicable_volatile.issubset(unsafe_families)
        )
        if step >= PRE_SHOCK_HOURS:
            for vault in candidates:
                unsafe_ever[_family(vault.collateral_type)].add(
                    int(vault.vault_id)
                )
        step_config = replace(
            base_liquidation,
            gas_cost=float(gas_costs[step]),
            risk_cost_rate=0.0,
            max_close_factor=1.0,
            max_liquidations_per_step=CAPACITY,
        )
        ranked = rank_liquidation_candidates(
            candidates,
            prices=prices,
            config=step_config,
            portfolio=portfolio_config,
        )
        decision = _demand_decision(
            step=step,
            inventory=len(candidates),
            uniform=float(arrivals["uniforms"][step]),
            positive_count=int(arrivals["positive_counts"][step]),
            hurdle_probability=float(arrivals["hurdle_probability"]),
        )
        demand_selected = ranked.head(decision.bounded_demand)
        attempt_selected = ranked.head(decision.attempt_budget)
        attempt_ids = attempt_selected["vault_id"].astype(int).tolist()
        duplicate_attempt = duplicate_attempt or len(attempt_ids) != len(
            set(attempt_ids)
        )
        demand_by_family = Counter(
            _family(value) for value in demand_selected["collateral_type"]
        )
        attempt_by_family = Counter(
            _family(value) for value in attempt_selected["collateral_type"]
        )
        candidate_by_family = Counter(
            _family(value) for value in ranked["collateral_type"]
        )
        selected_set = set(attempt_ids)
        displaced_by_family: dict[str, int] = {}
        for family in FAMILY_ORDER:
            if decision.demand_truncated_by_capacity <= 0:
                displaced_by_family[family] = 0
                continue
            isolated = (
                ranked.loc[
                    ranked["collateral_type"].map(_family).eq(family),
                    "vault_id",
                ]
                .head(CAPACITY)
                .astype(int)
            )
            displaced_by_family[family] = len(
                set(isolated) - selected_set
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
            family = _family(vault.collateral_type)
            result["family"] = family
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
                liquidated_initial_debt_ids.add(vault_id)
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
            values["unsafe"][step] = candidate_by_family[family]
            values["arrivals"][step] = demand_by_family[family]
            values["attempts"][step] = attempt_by_family[family]
            values["capacity_rejections"][step] = (
                demand_by_family[family] - attempt_by_family[family]
            )
            values["successful"][step] = len(successful)
            values["closures"][step] = len(closures)
            values["liquidated_debt"][step] = liquidated_debt
            values["backlog"][step] = backlog
            values["active_bad_debt"][step] = active_bad_debt
            values["realised_bad_debt"][step] = realised_bad_debt
            values["terminal_debt_writeoff"][step] = debt_writeoff
            values["keeper_profit"][step] = keeper_profit
            values["displaced_candidates"][step] = (
                displaced_by_family[family]
            )
            values["simultaneous_unsafe"][step] = (
                family in unsafe_families and len(unsafe_families) >= 2
            )

        active_backlog_family_counts[step] = sum(
            family_arrays[family]["backlog"][step] > 1e-9
            for family in FAMILY_ORDER
        )
        arrays["liquidatable_before"][step] = len(candidates)
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
            len(attempt_selected) - arrays["successful_liquidations"][step]
        )
        arrays["capacity_rejected_opportunities"][step] = (
            len(demand_selected) - len(attempt_selected)
        )
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
            ("unsafe", "liquidatable_before"),
            ("arrivals", "sampled_arrivals"),
            ("attempts", "selected_attempts"),
            ("capacity_rejections", "capacity_rejected_opportunities"),
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
    system_summary = {
        "initial_total_debt_dai": TOTAL_DEBT_DAI,
        "realised_bad_debt_share": float(
            arrays["realised_bad_debt_dai"][post].sum() / TOTAL_DEBT_DAI
        ),
        "positive_realised_bad_debt": int(
            arrays["realised_bad_debt_dai"][post].sum() > 1e-9
        ),
        "active_bad_debt_share": float(
            arrays["active_bad_debt_dai"][-1] / TOTAL_DEBT_DAI
        ),
        "unresolved_tab_share": float(
            arrays["unresolved_tab_dai"][post].max() / TOTAL_DEBT_DAI
        ),
        "backlog_area_share": float(
            arrays["unresolved_tab_dai"][post].sum() / TOTAL_DEBT_DAI
        ),
        "liquidated_debt_share": float(
            arrays["cleared_tab_dai"][post].sum() / TOTAL_DEBT_DAI
        ),
        "debt_weighted_liquidated_vault_share": float(
            sum(
                initial_debt_by_vault[vault_id]
                for vault_id in liquidated_initial_debt_ids
            )
            / TOTAL_DEBT_DAI
        ),
        "successful_closure_count": int(
            arrays["successful_closures"][post].sum()
        ),
        "capacity_rejected_opportunities": int(
            arrays["capacity_rejected_opportunities"][post].sum()
        ),
        "positive_demand_hours": int(
            np.count_nonzero(arrays["sampled_arrivals"][post] > 0)
        ),
        "binding_hours": int(
            np.count_nonzero(
                arrays["capacity_rejected_opportunities"][post] > 0
            )
        ),
        "mean_capacity_utilisation": float(
            np.mean(arrays["selected_attempts"][post] / CAPACITY)
        ),
        "maximum_capacity_utilisation": float(
            np.max(arrays["selected_attempts"][post] / CAPACITY)
        ),
        "maximum_simultaneously_unsafe_families": int(
            unsafe_family_counts[post].max()
        ),
        "maximum_backlog_duration": _max_run(
            arrays["unresolved_tab_dai"][post] > 0
        ),
        "hours_one_unsafe_family": int(
            np.count_nonzero(unsafe_family_counts[post] == 1)
        ),
        "hours_at_least_two_unsafe_families": int(
            np.count_nonzero(unsafe_family_counts[post] >= 2)
        ),
        "hours_all_applicable_volatile_families_unsafe": int(
            np.count_nonzero(all_applicable_volatile_unsafe[post])
        ),
        "hours_eth_wbtc_simultaneously_unsafe": int(
            np.count_nonzero(simultaneous_eth_wbtc[post])
        ),
        "share_hours_eth_wbtc_simultaneously_unsafe": float(
            np.mean(simultaneous_eth_wbtc[post])
        ),
        "maximum_simultaneous_active_backlog_families": int(
            active_backlog_family_counts[post].max()
        ),
        "accounting_valid": accounting_valid,
        "reconciliation_failure_count": reconciliation_failures,
        "duplicate_attempt": duplicate_attempt,
        "duplicate_closure": duplicate_closure,
        "unique_vault_identifiers": len(vault_by_id) == len(vaults),
        "shared_capacity_valid": bool(
            np.all(arrays["selected_attempts"] <= CAPACITY)
        ),
        "nonnegative_backlog_valid": bool(
            np.all(arrays["unresolved_tab_dai"] >= -1e-12)
        ),
        "nonnegative_bad_debt_valid": bool(
            np.all(arrays["active_bad_debt_dai"] >= -1e-12)
            and np.all(arrays["realised_bad_debt_dai"] >= -1e-12)
        ),
        "nonnegative_vault_balances_valid": bool(
            all(vault.debt_dai >= 0.0 for vault in vaults)
            and all(vault.collateral_amount >= 0.0 for vault in vaults)
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
    system_bad_debt = float(
        sum(
            family_arrays[family]["realised_bad_debt"][post].sum()
            for family in FAMILY_ORDER
        )
    )
    collateral_rows: list[dict[str, Any]] = []
    for family in FAMILY_ORDER:
        exposure = initial_debt[family]
        values = family_arrays[family]
        liquidated = float(values["liquidated_debt"][post].sum())
        backlog = float(values["backlog"][post].sum())
        bad_debt = float(values["realised_bad_debt"][post].sum())
        collateral_rows.append(
            {
                "family": family,
                "initial_debt_exposure": exposure,
                "unsafe_vault_count": len(unsafe_ever[family]),
                "simultaneous_unsafe_hours": int(
                    values["simultaneous_unsafe"][post].sum()
                ),
                "liquidation_arrivals": int(values["arrivals"][post].sum()),
                "selected_attempts": int(values["attempts"][post].sum()),
                "capacity_rejections": int(
                    values["capacity_rejections"][post].sum()
                ),
                "successful_closures": int(values["closures"][post].sum()),
                "liquidated_debt": liquidated,
                "backlog_area": backlog,
                "maximum_backlog": float(values["backlog"][post].max()),
                "active_bad_debt": float(values["active_bad_debt"][-1]),
                "realised_bad_debt": bad_debt,
                "keeper_profit_proxy": float(
                    values["keeper_profit"][post].sum()
                ),
                "exposure_normalised_liquidated_debt": (
                    None if exposure == 0.0 else liquidated / exposure
                ),
                "exposure_normalised_backlog": (
                    None if exposure == 0.0 else backlog / exposure
                ),
                "exposure_normalised_bad_debt": (
                    None if exposure == 0.0 else bad_debt / exposure
                ),
                "contribution_to_system_backlog": (
                    None
                    if system_backlog == 0.0
                    else backlog / system_backlog
                ),
                "contribution_to_system_bad_debt": (
                    None
                    if system_bad_debt == 0.0
                    else bad_debt / system_bad_debt
                ),
                "displaced_candidates": int(
                    values["displaced_candidates"][post].sum()
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
    }


def simulate_replication(
    replication: int,
    programme_identity: str | None = None,
) -> dict[str, Any]:
    """Run the exact eight Experiment B cells for one CRN replication."""
    if simulation_core_identity() != REGISTERED_SIMULATION_CORE_IDENTITY:
        raise RuntimeError(
            "Experiment B simulation-core identity differs from the "
            "registered replay-compatible implementation."
        )
    programme = load_programme()
    if programme_identity is None:
        programme_identity = programme.programme_identity
    if programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Experiment B programme identity differs.")
    streams = _prepare_replication_streams(replication)
    nested_audit = experiment_a.audit_nested_initialisations(
        streams["states"]
    )
    collateral_payload, portfolio_payload, _ = (
        experiment_a._design_payloads()
    )
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
    path_audits: dict[str, Any] = {}
    gas_unit_draw_checksums: set[str] = set()
    gas_component_checksums: dict[str, str] = {}

    for shock in SHOCK_ORDER:
        price_paths, gas_rows, path_audit = build_treatment_paths(
            streams["sampled_market"], shock
        )
        path_audit["joint_treatment_path_valid"] = bool(
            path_audit["price_isolation_valid"]
            and path_audit["stable_ordinary_multiplier_valid"]
            and path_audit[
                "registered_joint_treatment_definition_valid"
            ]
            and path_audit["resolved_path_diagnostics"]
            and not path_audit["final_validation_data_used"]
        )
        path_audits[shock] = path_audit
        integrated = resolve_integrated_empirical_eth_profile()
        gas = component_gas_costs(
            sampled_market_gas_rows=gas_rows,
            simulated_eth_prices=price_paths["ETH"],
            config=replace(
                integrated.gas,
                seed=derive_seed(replication, "keeper_gas_units"),
            ),
        )
        if gas.gas_cost_usd is None or gas.sampled_rows is None:
            raise ValueError("Component gas process did not return a path.")
        unit_rows = gas.sampled_rows[
            ["gas_pool_row_id", "gas_units"]
        ].to_dict(orient="records")
        unit_checksum = _payload_sha256(unit_rows)
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
        gas_unit_draw_checksums.add(unit_checksum)
        gas_component_checksums[shock] = component_checksum

        for portfolio in PORTFOLIO_ORDER:
            identifier = f"{shock}__{portfolio}"
            liquidation = _simulate_cell_liquidations(
                initialisation=streams["states"][portfolio],
                price_paths=price_paths,
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
                eth_prices=price_paths["ETH"],
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
                "gas_environment_checksum": path_audit[
                    "gas_environment_checksum"
                ],
                "gas_owner": path_audit["gas_owner"],
                "price_path_checksum": _payload_sha256(
                    path_audit["full_price_checksums"]
                ),
                "joint_treatment_path_valid": path_audit[
                    "joint_treatment_path_valid"
                ],
                "price_isolation_valid": path_audit[
                    "price_isolation_valid"
                ],
                "nested_initialisation_valid": nested_audit["passed"],
            }
            system["numerical_valid"] = bool(
                system["numerical_valid"]
                and market["summary"]["numerical_valid"]
            )
            system["finite_collateral_prices_valid"] = bool(
                all(
                    np.isfinite(np.asarray(values, dtype=float)).all()
                    and np.all(np.asarray(values, dtype=float) > 0.0)
                    for values in price_paths.values()
                )
            )
            system["finite_dai_price_valid"] = bool(
                market["summary"]["numerical_valid"]
            )
            required_metadata = (
                "cell_identifier",
                "shock",
                "portfolio",
                "replication",
                "paired_stream_checksum",
                "state_checksum",
                "gas_unit_draw_checksum",
                "gas_component_checksum",
                "price_path_checksum",
            )
            system["complete_metadata_valid"] = all(
                system.get(field) not in {None, ""}
                for field in required_metadata
            )
            system["numerical_valid"] = bool(
                system["numerical_valid"]
                and system["finite_collateral_prices_valid"]
                and system["finite_dai_price_valid"]
                and system["nonnegative_backlog_valid"]
                and system["nonnegative_bad_debt_valid"]
                and system["nonnegative_vault_balances_valid"]
                and system["unique_vault_identifiers"]
                and system["shared_capacity_valid"]
                and system["complete_metadata_valid"]
            )
            cell_rows.append(system)
            for row in liquidation["collateral_rows"]:
                collateral_rows.append(
                    {
                        "cell_order": cells[identifier].order,
                        "cell_identifier": identifier,
                        "shock": shock,
                        "portfolio": portfolio,
                        "replication": replication,
                        "numerical_valid": system["numerical_valid"],
                        "accounting_valid": system["accounting_valid"],
                        "joint_treatment_path_valid": system[
                            "joint_treatment_path_valid"
                        ],
                        "price_isolation_valid": system[
                            "price_isolation_valid"
                        ],
                        "nested_initialisation_valid": system[
                            "nested_initialisation_valid"
                        ],
                        **row,
                    }
                )

    if len(gas_unit_draw_checksums) != 1:
        raise ValueError("Keeper gas-unit draws drifted across B shocks.")
    if [row["cell_identifier"] for row in cell_rows] != list(CELL_ORDER):
        raise ValueError("Experiment B simulation cell order differs.")
    expected_collateral_keys = [
        (cell, family) for cell in CELL_ORDER for family in FAMILY_ORDER
    ]
    if [
        (row["cell_identifier"], row["family"])
        for row in collateral_rows
    ] != expected_collateral_keys:
        raise ValueError("Experiment B collateral-row order differs.")
    result = {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "programme_identity": programme_identity,
        "experiment_identity": experiment_identity(programme_identity),
        "replication": replication,
        "scientific_code_identity": (
            REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
        ),
        "profile_identity": PROFILE_IDENTITY,
        "seed_registry_sha256": seed_registry_checksum(),
        "seed_ownership": streams["seed_ownership"],
        "actual_initialisation_seed_ownership": streams[
            "actual_initialisation_seed_ownership"
        ],
        "paired_stream_checksum": streams["paired_stream_checksum"],
        "stream_components": streams["stream_components"],
        "nested_initialisation_audit": nested_audit,
        "path_audits": path_audits,
        "gas_unit_draw_checksum": next(iter(gas_unit_draw_checksums)),
        "gas_component_checksums": gas_component_checksums,
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
    """Hash replay-critical B functions and their external code owners."""
    functions = (
        derive_seed,
        initialisation_replication_key,
        seed_record,
        seed_registry_checksum,
        _validate_master_cell,
        build_cell_registry,
        _market_pool,
        _empirical_source_block,
        empirical_source_block_checksum,
        _registered_shock_frame,
        registered_shock_kernels,
        _embedded_multipliers,
        _rolling_minimum_24h_log_return,
        _resolved_rolling_minimum_24h_log_return,
        _path_diagnostics,
        build_treatment_paths,
        _arrival_stream,
        _demand_decision,
        _family,
        _max_run,
        _prepare_replication_streams,
        _simulate_cell_liquidations,
        simulate_replication,
    )
    external_paths = (
        REPOSITORY_ROOT / "src/dai_sim/experiments/final/programme.py",
        REPOSITORY_ROOT
        / "src/dai_sim/experiments/final/idiosyncratic_diversification.py",
        REPOSITORY_ROOT / "src/dai_sim/common/serialization.py",
        REPOSITORY_ROOT / "src/dai_sim/calibration/event_simulation.py",
        REPOSITORY_ROOT / "src/dai_sim/calibration/market.py",
        REPOSITORY_ROOT
        / "src/dai_sim/calibration/multicollateral_validation.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/configuration.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/gas.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/integrated_profile.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/liquidations.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/market.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/multicollateral.py",
        REPOSITORY_ROOT / "src/dai_sim/model/collateral.py",
        REPOSITORY_ROOT / "src/dai_sim/model/confidence.py",
        REPOSITORY_ROOT / "src/dai_sim/model/liquidation.py",
        REPOSITORY_ROOT / "src/dai_sim/model/market.py",
        REPOSITORY_ROOT / "src/dai_sim/model/vault.py",
        REPOSITORY_ROOT
        / "src/dai_sim/experiments/mechanism/eth_recovery.py",
        REPOSITORY_ROOT / "src/dai_sim/validation/multicollateral.py",
    )
    digest = hashlib.sha256()
    for function in functions:
        digest.update(function.__name__.encode("utf-8"))
        digest.update(b"\0")
        digest.update(inspect.getsource(function).encode("utf-8"))
        digest.update(b"\0")
    for path in external_paths:
        if not path.is_file():
            raise ValueError(
                f"Missing Experiment B simulation owner: {path}."
            )
        digest.update(_relative(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@lru_cache(maxsize=1)
def scientific_code_identity() -> str:
    """Hash current B code, including post-execution evidence infrastructure."""
    paths = (
        REPOSITORY_ROOT / "src/dai_sim/experiments/final/programme.py",
        REPOSITORY_ROOT
        / "src/dai_sim/experiments/final/correlated_stress.py",
        REPOSITORY_ROOT
        / "src/dai_sim/experiments/final/idiosyncratic_diversification.py",
        REPOSITORY_ROOT / "src/dai_sim/common/serialization.py",
        REPOSITORY_ROOT / "src/dai_sim/calibration/event_simulation.py",
        REPOSITORY_ROOT / "src/dai_sim/calibration/market.py",
        REPOSITORY_ROOT
        / "src/dai_sim/calibration/multicollateral_validation.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/configuration.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/gas.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/integrated_profile.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/liquidations.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/market.py",
        REPOSITORY_ROOT / "src/dai_sim/inputs/multicollateral.py",
        REPOSITORY_ROOT / "src/dai_sim/model/collateral.py",
        REPOSITORY_ROOT / "src/dai_sim/model/confidence.py",
        REPOSITORY_ROOT / "src/dai_sim/model/liquidation.py",
        REPOSITORY_ROOT / "src/dai_sim/model/market.py",
        REPOSITORY_ROOT / "src/dai_sim/model/vault.py",
        REPOSITORY_ROOT
        / "src/dai_sim/experiments/mechanism/eth_recovery.py",
        REPOSITORY_ROOT / "src/dai_sim/validation/multicollateral.py",
        REPOSITORY_ROOT
        / "workflows/experiments/final/correlated_stress.py",
    )
    digest = hashlib.sha256()
    for path in paths:
        if not path.is_file():
            raise ValueError(
                f"Missing Experiment B scientific owner: {path}."
            )
        digest.update(_relative(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _registered_path_identities() -> dict[str, Any]:
    source = _empirical_source_block()
    gas_values = pd.to_numeric(
        source["median_effective_gas_price_gwei"], errors="raise"
    ).to_numpy(dtype="<f8")
    gas_checksum = hashlib.sha256(gas_values.tobytes()).hexdigest()
    if gas_checksum != EMPIRICAL_MEDIAN_GAS_PATH_SHA256:
        raise ValueError("Frozen empirical median-gas path changed.")
    return {
        shock: {
            "kernel_checksums": {
                family: hashlib.sha256(
                    np.asarray(kernel, dtype="<f8").tobytes()
                ).hexdigest()
                for family, kernel in registered_shock_kernels(shock).items()
            },
            "gas_owner": (
                "selected_empirical_24h_block"
                if shock == "joint_crypto_empirical_stress"
                else "ordinary_common_market_blocks"
            ),
            "empirical_source_block_sha256": (
                empirical_source_block_checksum()
                if shock == "joint_crypto_empirical_stress"
                else None
            ),
            "empirical_median_gas_path_sha256": (
                gas_checksum
                if shock == "joint_crypto_empirical_stress"
                else None
            ),
        }
        for shock in SHOCK_ORDER
    }


def _joint_stress_selection() -> dict[str, Any]:
    if sha256_file(JOINT_STRESS_PROVENANCE_PATH) != (
        JOINT_STRESS_PROVENANCE_SHA256
    ):
        raise ValueError("Joint-stress selection provenance changed.")
    payload = json.loads(
        JOINT_STRESS_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    selected = dict(payload["tail_derivation"]["joint_empirical"])
    expected = {
        "selection_timestamp_utc": "2022-05-12T06:00:00+00:00",
        "lambda": 0.5,
        "score": 13.650920252292819,
        "eth_price_multiplier": 0.7788579492718739,
        "wbtc_price_multiplier": 0.8632706805976554,
        "gas_24h_mean_gwei": 180.334618793675,
        "selection_uses_model_outcomes": False,
    }
    for field, value in expected.items():
        if selected[field] != value:
            raise ValueError(
                f"Joint empirical stress selection changed: {field}."
            )
    return {
        **selected,
        "selection_rule": (
            "maximum standardised ETH downside + standardised WBTC "
            "downside + 0.5 * standardised gas"
        ),
        "provenance_sha256": JOINT_STRESS_PROVENANCE_SHA256,
        "final_validation_data_used": False,
    }


def _decision_rule_payload() -> dict[str, Any]:
    return {
        "operationality": {
            "tolerance": 1e-12,
            "statuses": [
                "operational",
                "degenerate",
                "not_operational",
                "invalid",
            ],
            "degenerate_rule": (
                "all registered cell values equal within tolerance or every "
                "replication has the same value"
            ),
            "bad_debt_exclusion": (
                "degenerate bad-debt outcomes cannot determine B1 or B2"
            ),
        },
        "B1": {
            "beneficial_rule": (
                "at least two operational primary solvency advantages have "
                "positive means and 95% intervals above zero, with no "
                "clearly adverse operational bad-debt metric"
            ),
            "classifications": [
                "supported",
                "partially_supported",
                "not_supported",
                "not_operational",
                "invalid",
            ],
            "branch_map": {
                "invalid": "any experiment validity gate fails",
                "not_operational": (
                    "fewer than two primary solvency metrics operational"
                ),
                "supported": (
                    "at least two diversified portfolios satisfy the "
                    "beneficial rule"
                ),
                "partially_supported": (
                    "exactly one diversified portfolio satisfies"
                ),
                "not_supported": "no diversified portfolio satisfies",
            },
        },
        "B2": {
            "deterioration_rule": (
                "at least two operational primary solvency deterioration "
                "interactions have positive means and 95% intervals above "
                "zero, with no material opposite result"
            ),
            "reversal_precedence": True,
            "classifications": [
                "correlation_deterioration_present",
                "correlation_deterioration_partial",
                "correlation_deterioration_not_present",
                "correlation_reversal_present",
                "not_operational",
                "invalid",
            ],
            "material_opposite_rule": (
                "interaction mean is negative by at least the frozen "
                "metric threshold and its 95% interval is below zero"
            ),
            "branch_map": {
                "invalid": "any experiment validity gate fails",
                "not_operational": (
                    "fewer than two primary solvency metrics operational"
                ),
                "correlation_reversal_present": (
                    "at least two portfolios have at least two adverse "
                    "high-correlation advantages; takes precedence"
                ),
                "correlation_deterioration_present": (
                    "at least two portfolios satisfy deterioration rule"
                ),
                "correlation_deterioration_partial": (
                    "exactly one satisfies, or at least two portfolios have "
                    "one clearly deteriorating metric"
                ),
                "correlation_deterioration_not_present": (
                    "no systematic deterioration pattern"
                ),
            },
        },
        "B3": {
            "conditions": [
                "ETH and WBTC both show positive unsafe or liquidation activity",
                "at least two families have positive backlog area",
                "at least one collateral has positive shared-capacity displacement",
                (
                    "high-correlation simultaneous ETH/WBTC unsafe-hour share "
                    "exceeds empirical-joint-stress share"
                ),
            ],
            "classifications": [
                "transmission_intensifies",
                "transmission_mixed",
                "transmission_not_present",
                "transmission_not_operational",
                "transmission_invalid",
            ],
            "branch_map": {
                "transmission_invalid": (
                    "collateral attribution, path or accounting fails"
                ),
                "transmission_not_operational": (
                    "shared capacity never binds and displacement is absent"
                ),
                "transmission_intensifies": (
                    "at least two portfolios satisfy all four conditions"
                ),
                "transmission_mixed": (
                    "at least two portfolios satisfy at least two conditions"
                ),
                "transmission_not_present": (
                    "no systematic cross-collateral intensification"
                ),
            },
        },
        "persistence_precedence": [
            "not_operational if fewer than two operational metrics",
            "reversed if at least two metrics clearly adverse",
            (
                "weakens_but_remains if at least two remain beneficial and "
                "at least two deteriorate"
            ),
            "persists if at least two remain beneficial",
            "neutralised if no metric is clearly beneficial or adverse",
            "mixed otherwise",
        ],
        "overall_h3_precedence": [
            "H3_correlated_stress_experiment_invalid",
            "H3_correlation_reverses_diversification",
            "H3_correlation_deterioration_supported",
            "H3_correlation_deterioration_partially_supported",
            "H3_diversification_robust_to_high_correlation",
            "H3_no_clear_correlated_stress_effect",
        ],
        "overall_h3_branch_map": {
            "H3_correlated_stress_experiment_invalid": (
                "any registered validity gate fails"
            ),
            "H3_correlation_reverses_diversification": (
                "B2 reversal present and B3 valid"
            ),
            "H3_correlation_deterioration_supported": (
                "B1 supported or partial, B2 deterioration present, and "
                "B3 intensifies or is mixed"
            ),
            "H3_correlation_deterioration_partially_supported": (
                "B2 partial, or B3 mixed with at least one B2 "
                "deteriorating metric"
            ),
            "H3_diversification_robust_to_high_correlation": (
                "B1 supported, B2 not present, at least two persistence "
                "classifications, and B3 valid"
            ),
            "H3_no_clear_correlated_stress_effect": (
                "remaining valid, B3-valid states without clear persistence "
                "or reversal"
            ),
        },
        "peg_solvency_classifications": [
            "solvency_and_peg_deteriorate_with_correlation",
            "solvency_deteriorates_peg_unchanged",
            "peg_deteriorates_solvency_unchanged",
            "solvency_and_peg_diverge",
            "neither_materially_changes",
            "relationship_mixed",
            "relationship_invalid",
        ],
        "peg_solvency_aggregation": {
            "group_state": (
                "deteriorates or improves when at least two portfolio-metric "
                "interactions are material and their 95% intervals exclude "
                "zero; both directions gives mixed; otherwise unchanged"
            ),
            "mapping": {
                "deteriorates+deteriorates": (
                    "solvency_and_peg_deteriorate_with_correlation"
                ),
                "deteriorates+unchanged": (
                    "solvency_deteriorates_peg_unchanged"
                ),
                "unchanged+deteriorates": (
                    "peg_deteriorates_solvency_unchanged"
                ),
                "unchanged+unchanged": "neither_materially_changes",
                "opposite_directions": "solvency_and_peg_diverge",
                "any_mixed_or_unmapped": "relationship_mixed",
                "invalid": "relationship_invalid",
            },
        },
    }


@lru_cache(maxsize=1)
def experiment_identity(programme_identity: str) -> str:
    """Return the historically registered, result-blind B identity."""
    if programme_identity != MASTER_PROGRAMME_IDENTITY:
        raise ValueError("Experiment B master programme identity differs.")
    identity = _payload_sha256(
        {
            "schema_version": 1,
            "parent_commit": EXPERIMENT_B_PARENT_COMMIT,
            "programme_identity": programme_identity,
            "scientific_code_identity": (
                REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
            ),
            "experiment_a_identity": EXPERIMENT_A_IDENTITY,
            "profile_identity": PROFILE_IDENTITY,
            "profile_sha256": PROFILE_SHA256,
            "registry_checksums": {
                "collateral": COLLATERAL_REGISTRY_SHA256,
                "portfolio": PORTFOLIO_REGISTRY_SHA256,
                "shock": SHOCK_REGISTRY_SHA256,
                "keeper": KEEPER_REGISTRY_SHA256,
                "confidence": CONFIDENCE_REGISTRY_SHA256,
                "shock_evidence": SHOCK_EVIDENCE_SHA256,
            },
            "stage1": {
                "below_peg_response": EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
                "above_peg_response": EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
                "residual_sequence": (
                    EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256
                ),
                "residual_blocks": EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
            },
            "cells": [asdict(cell) for cell in build_cell_registry()],
            "replications_per_cell": REPLICATIONS,
            "seed_registry_sha256": seed_registry_checksum(),
            "shock_path_identities": _registered_path_identities(),
            "joint_empirical_stress_selection": _joint_stress_selection(),
            "system_metrics": list(SYSTEM_METRICS),
            "outcome_definitions": OUTCOME_DEFINITIONS,
            "system_diagnostics": list(SYSTEM_DIAGNOSTICS),
            "diagnostic_definitions": DIAGNOSTIC_DEFINITIONS,
            "collateral_metrics": list(COLLATERAL_METRICS),
            "raw_portfolio_contrasts": [
                list(pair) for pair in RAW_PORTFOLIO_CONTRASTS
            ],
            "metric_directions": METRIC_DIRECTIONS,
            "materiality_thresholds": MATERIALITY_THRESHOLDS,
            "decision_rules": _decision_rule_payload(),
            "identification_limitation": IDENTIFICATION_LIMITATION,
            "horizon": {
                "pre_shock_hours": PRE_SHOCK_HOURS,
                "post_shock_hours": POST_SHOCK_HOURS,
                "total_hours": TOTAL_HOURS,
                "registered_kernel_onset_hour": REGISTERED_KERNEL_ONSET,
                "kernel_embedding_start_hour": KERNEL_EMBEDDING_START,
                "empirical_gas_embed_start": EMPIRICAL_GAS_EMBED_START,
                "empirical_gas_embed_hours": EMPIRICAL_BLOCK_HOURS,
            },
            "final_validation_data_used": False,
        }
    )
    if identity != REGISTERED_EXPERIMENT_IDENTITY:
        raise ValueError("Registered Experiment B identity reconstruction differs.")
    return identity


def specification_payload(programme_identity: str) -> dict[str, Any]:
    """Build the immutable, result-blind Experiment B specification."""
    cells = build_cell_registry()
    path_identities = _registered_path_identities()
    return {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "purpose": (
            "Test whether multi-collateral diversification persists, "
            "deteriorates or reverses under registered joint crypto stress."
        ),
        "parent_commit": EXPERIMENT_B_PARENT_COMMIT,
        "programme_identity": programme_identity,
        "scientific_code_identity": (
            REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
        ),
        "experiment_identity": experiment_identity(programme_identity),
        "experiment_a_regression_identity": EXPERIMENT_A_IDENTITY,
        "experiment_a_checkpoint_snapshot": (
            _frozen_experiment_a_checkpoint_snapshot()
        ),
        "research_question": "RQ4",
        "hypothesis": "H3",
        "analytical_components": {
            "B1": "diversification under empirical joint stress",
            "B2": "diversification deterioration under high correlation",
            "B3": "cross-collateral stress transmission",
        },
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
            "shock_evidence": SHOCK_EVIDENCE_SHA256,
        },
        "cell_order": [cell.identifier for cell in cells],
        "cells": [asdict(cell) for cell in cells],
        "replications_per_cell": REPLICATIONS,
        "substantive_simulations": len(cells) * REPLICATIONS,
        "seed_ownership": {
            "registry_id": EXPERIMENT_NAMESPACE,
            "streams": list(SEED_STREAMS),
            "nested_family_draws": True,
            "initialisation_replication_offset": (
                INITIALISATION_REPLICATION_OFFSET
            ),
            "common_random_numbers": True,
            "treatment_owned_gas_difference": True,
            "seed_registry_sha256": seed_registry_checksum(),
            "replication_registry": [
                seed_record(replication)
                for replication in range(REPLICATIONS)
            ],
        },
        "treatments": {
            "portfolios": list(PORTFOLIO_ORDER),
            "shocks": list(SHOCK_ORDER),
            "capacity": CAPACITY,
            "capacity_semantics": "one system-wide shared capacity",
            "hurdle": "direct_cost_only",
            "risk_cost_rate": 0.0,
            "confidence": "stage1_only",
            "oracle_delay": 0,
            "recovery": "full_week",
        },
        "shock_path_identities": path_identities,
        "joint_empirical_stress_selection": _joint_stress_selection(),
        "co_stress_diagnostics": {
            "return_window_hours": 24,
            "stress_window": (
                "registered onset through the 168-hour recovery interval"
            ),
            "below_stress_threshold_rule": (
                "family multiplier at or below its registered trough "
                "multiplier"
            ),
            "maximum_simultaneous_drawdown": (
                "(1 - ETH multiplier) + (1 - WBTC multiplier)"
            ),
            "no_post_construction_correlation_threshold": True,
        },
        "identification_scope": {
            "B2_estimand": "registered bundled-treatment deterioration",
            "pure_correlation_effect_identified": False,
            "limitation": IDENTIFICATION_LIMITATION,
        },
        "empirical_gas_translation": {
            "selection_endpoint_utc": EMPIRICAL_BLOCK_END_UTC.isoformat(),
            "source_hours": EMPIRICAL_BLOCK_HOURS,
            "source_block_sha256": empirical_source_block_checksum(),
            "embedding_start_hour": EMPIRICAL_GAS_EMBED_START,
            "translation_rule": (
                "preserve the exact selected 24-hour historical gas sequence "
                "at experiment hours 48-71 and retain the common ordinary "
                "sampled gas environment outside that interval"
            ),
            "result_blind": True,
            "final_validation_data_used": False,
        },
        "horizon": {
            "pre_shock_hours": PRE_SHOCK_HOURS,
            "post_shock_hours": POST_SHOCK_HOURS,
            "total_hours": TOTAL_HOURS,
            "registered_kernel_hours": REGISTERED_KERNEL_HOURS,
            "registered_kernel_onset_hour": REGISTERED_KERNEL_ONSET,
            "kernel_embedding_start_hour": KERNEL_EMBEDDING_START,
            "price_translation_rule": (
                "prepend 24 ordinary hours, retain each registered 216-hour "
                "multiplier kernel byte-for-byte, then retain its terminal "
                "multiplier through the common horizon"
            ),
        },
        "recovery_definition": {
            "band": [0.995, 1.005],
            "consecutive_hours": 24,
            "restricted_mean_cap_hours": POST_SHOCK_HOURS,
            "owner": "dai_sim.experiments.mechanism.eth_recovery",
        },
        "primary_outcomes": list(SYSTEM_METRICS),
        "outcome_definitions": OUTCOME_DEFINITIONS,
        "operational_primary_solvency_metrics": list(
            PRIMARY_SOLVENCY_METRICS
        ),
        "capacity_diagnostics": list(SYSTEM_DIAGNOSTICS),
        "diagnostic_definitions": DIAGNOSTIC_DEFINITIONS,
        "collateral_decomposition": list(COLLATERAL_METRICS),
        "raw_portfolio_contrasts": [
            f"{left} - {right}" for left, right in RAW_PORTFOLIO_CONTRASTS
        ],
        "direction_normalisation": {
            "metric_directions": METRIC_DIRECTIONS,
            "advantage": (
                "direction_multiplier * (portfolio - eth_only), where -1 "
                "denotes lower-is-better and +1 higher-is-better"
            ),
        },
        "deterioration_interaction": (
            "advantage_empirical_joint_stress - "
            "advantage_high_correlation"
        ),
        "materiality_thresholds": MATERIALITY_THRESHOLDS,
        "decision_rules": _decision_rule_payload(),
        "uncertainty": {
            "continuous": [
                "mean",
                "standard_error",
                "ci95_lower",
                "ci95_upper",
                "median",
                "p05",
                "p25",
                "p75",
                "p95",
            ],
            "binary": [
                "paired_probability_difference",
                "standard_error",
                "ci95_lower",
                "ci95_upper",
                "discordant_pair_counts",
            ],
            "binary_interaction_rule": (
                "interaction paired_probability_difference is the paired "
                "difference-in-differences; generic discordant counts are "
                "not applicable, while empirical and high-correlation "
                "source-pair discordant counts are retained separately"
            ),
            "zero_heavy": [
                "mean",
                "positive_share",
                "median",
                "p75",
                "p90",
                "p95",
            ],
        },
        "evidence_schemas": {
            "registry": {
                "format": "one row per registered cell",
                "columns": list(REGISTRY_COLUMNS),
                "unique_key": ["identifier"],
                "expected_rows": len(CELL_ORDER),
            },
            "cell_summary": {
                "format": "long",
                "columns": list(CELL_SUMMARY_COLUMNS),
                "unique_key": ["cell_identifier", "metric"],
                "expected_rows": len(CELL_ORDER)
                * (len(SYSTEM_METRICS) + len(SYSTEM_DIAGNOSTICS)),
            },
            "collateral_summary": {
                "format": "long",
                "columns": list(COLLATERAL_SUMMARY_COLUMNS),
                "unique_key": [
                    "cell_identifier",
                    "family",
                    "metric",
                ],
                "expected_rows": len(CELL_ORDER)
                * len(FAMILY_ORDER)
                * len(COLLATERAL_METRICS),
            },
            "contrasts": {
                "format": "long",
                "columns": list(CONTRAST_COLUMNS),
                "row_types": {
                    "raw_portfolio_contrast": 168,
                    "direction_normalised_advantage": 84,
                    "correlation_deterioration_interaction": 42,
                },
                "unique_keys": {
                    "raw_portfolio_contrast": [
                        "shock",
                        "left_portfolio",
                        "right_portfolio",
                        "metric",
                    ],
                    "direction_normalised_advantage": [
                        "shock",
                        "portfolio",
                        "metric",
                    ],
                    "correlation_deterioration_interaction": [
                        "portfolio",
                        "metric",
                    ],
                },
                "expected_rows": (
                    len(SHOCK_ORDER)
                    * len(RAW_PORTFOLIO_CONTRASTS)
                    * len(SYSTEM_METRICS)
                    + len(SHOCK_ORDER)
                    * len(DIVERSIFIED_PORTFOLIOS)
                    * len(SYSTEM_METRICS)
                    + len(DIVERSIFIED_PORTFOLIOS)
                    * len(SYSTEM_METRICS)
                ),
                "retain_non_operational_rows": True,
            },
        },
        "execution_plan": {
            "checkpoint_granularity": (
                "one replication containing all eight cells"
            ),
            "checkpoint_count": REPLICATIONS,
            "output_cap_bytes": MAXIMUM_OUTPUT_BYTES,
            "minimum_free_bytes": MINIMUM_FREE_BYTES,
            "resume": True,
        },
        "final_validation_data_used": False,
        "held_out_data_used": False,
        "usdc_svb_used": False,
        "portfolio_ranked": False,
        "portfolio_selected": None,
        "shock_ranked": False,
        "shock_selected": None,
        "runtime_adopted": False,
    }


def _registry_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(cell) for cell in build_cell_registry()])


def _assert_preregistration_matches(programme_identity: str) -> None:
    expected = {
        COMPACT_FILENAMES[0]: _pretty_json(
            specification_payload(programme_identity)
        ),
        COMPACT_FILENAMES[1]: _csv_bytes(_registry_frame()),
    }
    for name, payload in expected.items():
        path = EVIDENCE_DIR / name
        if not path.is_file() or path.read_bytes() != payload:
            raise ValueError(
                f"Experiment B pre-registration bytes differ: {name}."
            )


def write_preregistration(programme_identity: str) -> dict[str, Any]:
    """Write immutable specification and cell registry before simulation."""
    specification = specification_payload(programme_identity)
    registry = _registry_frame()
    payloads = {
        COMPACT_FILENAMES[0]: _pretty_json(specification),
        COMPACT_FILENAMES[1]: _csv_bytes(registry),
    }
    for name, payload in payloads.items():
        path = EVIDENCE_DIR / name
        if path.is_file():
            if path.read_bytes() != payload:
                raise ValueError(
                    f"Experiment B pre-registration would change: {name}."
                )
            continue
        _atomic_bytes(path, payload)
    return {
        "experiment_identity": specification["experiment_identity"],
        "scientific_code_identity": specification[
            "scientific_code_identity"
        ],
        "specification_sha256": sha256_file(
            EVIDENCE_DIR / COMPACT_FILENAMES[0]
        ),
        "registry_sha256": sha256_file(
            EVIDENCE_DIR / COMPACT_FILENAMES[1]
        ),
        "seed_registry_sha256": seed_registry_checksum(),
        "cell_count": len(registry),
        "deterministic": True,
    }


def _checkpoint_path(output_dir: Path, replication: int) -> Path:
    return output_dir / "checkpoints" / f"replication_{replication:03d}.json"


def _result_checksum(payload: Mapping[str, Any]) -> str:
    return _payload_sha256(
        {
            key: value
            for key, value in payload.items()
            if key not in {"schema_version", "experiment_id", "result_checksum"}
        }
    )


def _valid_checkpoint(
    path: Path,
    replication: int,
    expected_programme_identity: str,
) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cells = payload["cell_rows"]
        collateral = payload["collateral_rows"]
        expected_collateral = [
            (cell, family)
            for cell in CELL_ORDER
            for family in FAMILY_ORDER
        ]
        cell_frame = pd.DataFrame(cells)
        collateral_frame = pd.DataFrame(collateral)
        valid_cell_flags = all(
            cell_frame[column].astype(bool).all()
            for column in (
                "numerical_valid",
                "accounting_valid",
                "joint_treatment_path_valid",
                "price_isolation_valid",
                "nested_initialisation_valid",
                "finite_collateral_prices_valid",
                "finite_dai_price_valid",
                "nonnegative_backlog_valid",
                "nonnegative_bad_debt_valid",
                "nonnegative_vault_balances_valid",
                "unique_vault_identifiers",
                "shared_capacity_valid",
                "complete_metadata_valid",
            )
        )
        crn_valid = bool(
            cell_frame["paired_stream_checksum"].nunique() == 1
            and cell_frame["gas_unit_draw_checksum"].nunique() == 1
            and cell_frame.groupby("portfolio")["state_checksum"]
            .nunique()
            .eq(1)
            .all()
            and cell_frame.groupby("shock")["price_path_checksum"]
            .nunique()
            .eq(1)
            .all()
            and cell_frame.groupby("shock")["gas_component_checksum"]
            .nunique()
            .eq(1)
            .all()
            and cell_frame.groupby("shock")["gas_environment_checksum"]
            .nunique()
            .eq(1)
            .all()
            and cell_frame.groupby("shock")["gas_owner"]
            .nunique()
            .eq(1)
            .all()
            and cell_frame.groupby("shock")["gas_component_checksum"]
            .first()
            .nunique()
            == len(SHOCK_ORDER)
            and cell_frame.groupby("shock")["gas_environment_checksum"]
            .first()
            .nunique()
            == len(SHOCK_ORDER)
        )
        components = payload["stream_components"]
        actual_initialisation = payload[
            "actual_initialisation_seed_ownership"
        ]
        initialisation_valid = bool(
            actual_initialisation["accepted_attempt"]
            == components["initialisation_accepted_attempt"]
            and actual_initialisation["family_seeds"]
            == components["initialisation_family_seeds"]
            and actual_initialisation["checksum"]
            == _payload_sha256(
                {
                    "accepted_attempt": components[
                        "initialisation_accepted_attempt"
                    ],
                    "family_seeds": components[
                        "initialisation_family_seeds"
                    ],
                }
            )
            and payload["paired_stream_checksum"]
            == _payload_sha256(components)
        )
        gas_component_map = (
            cell_frame.groupby("shock", sort=False)[
                "gas_component_checksum"
            ]
            .first()
            .to_dict()
        )
        gas_owner_map = (
            cell_frame.groupby("shock", sort=False)["gas_owner"]
            .first()
            .to_dict()
        )
        return bool(
            payload["schema_version"] == 1
            and payload["experiment_id"] == EXPERIMENT_ID
            and payload["programme_identity"] == expected_programme_identity
            and payload["experiment_identity"]
            == experiment_identity(expected_programme_identity)
            and payload["replication"] == replication
            and payload["scientific_code_identity"]
            == REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
            and payload["profile_identity"] == PROFILE_IDENTITY
            and payload["seed_registry_sha256"] == seed_registry_checksum()
            and payload["seed_ownership"] == seed_record(replication)
            and initialisation_valid
            and payload["simulation_count"] == len(CELL_ORDER)
            and len(cells) == len(CELL_ORDER)
            and len(collateral) == len(expected_collateral)
            and [row["cell_identifier"] for row in cells] == list(CELL_ORDER)
            and cell_frame["replication"].eq(replication).all()
            and [
                (row["cell_identifier"], row["family"])
                for row in collateral
            ]
            == expected_collateral
            and collateral_frame["replication"].eq(replication).all()
            and payload["nested_initialisation_audit"]["passed"]
            and valid_cell_flags
            and crn_valid
            and payload["paired_stream_checksum"]
            == cell_frame["paired_stream_checksum"].iloc[0]
            and payload["gas_unit_draw_checksum"]
            == cell_frame["gas_unit_draw_checksum"].iloc[0]
            and payload["gas_component_checksums"]
            == gas_component_map
            and gas_owner_map
            == {
                "joint_crypto_empirical_stress": (
                    "selected_empirical_24h_block"
                ),
                "joint_crypto_high_correlation": (
                    "ordinary_common_market_blocks"
                ),
            }
            and tuple(payload["path_audits"]) == SHOCK_ORDER
            and all(
                payload["path_audits"][shock][
                    "joint_treatment_path_valid"
                ]
                and payload["path_audits"][shock][
                    "registered_joint_treatment_definition_valid"
                ]
                and payload["path_audits"][shock][
                    "resolved_path_diagnostics"
                ]
                and not payload["path_audits"][shock][
                    "final_validation_data_used"
                ]
                for shock in SHOCK_ORDER
            )
            and payload["result_checksum"] == _result_checksum(payload)
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        json.JSONDecodeError,
    ):
        return False


def _output_dir(programme_identity: str) -> Path:
    return OUTPUT_ROOT / experiment_identity(programme_identity)


def _record_execution_failure(
    output_dir: Path,
    *,
    replication: int,
    workers: int,
    error: BaseException,
) -> Path:
    """Persist one ignored failure record without retrying the replication."""
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%S%fZ")
    path = (
        output_dir
        / "failure_records"
        / f"failure_{stamp}_replication_{replication:03d}.json"
    )
    _atomic_json(
        path,
        {
            "schema_version": 1,
            "experiment_id": EXPERIMENT_ID,
            "replication": replication,
            "worker_count": workers,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "automatic_retry_attempted": False,
            "recorded_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        },
    )
    return path


def audit_checkpoints(programme_identity: str) -> dict[str, Any]:
    output_dir = _output_dir(programme_identity)
    expected = {
        _checkpoint_path(output_dir, replication)
        for replication in range(REPLICATIONS)
    }
    observed = set((output_dir / "checkpoints").glob("replication_*.json"))
    observed_replications: list[int] = []
    for path in sorted(observed):
        try:
            observed_replications.append(
                int(json.loads(path.read_text(encoding="utf-8"))["replication"])
            )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ):
            continue
    duplicates = len(observed_replications) - len(
        set(observed_replications)
    )
    valid = sum(
        _valid_checkpoint(path, replication, programme_identity)
        for replication in range(REPLICATIONS)
        if (
            path := _checkpoint_path(output_dir, replication)
        ).is_file()
    )
    return {
        "experiment_identity": experiment_identity(programme_identity),
        "expected_checkpoints": REPLICATIONS,
        "observed_checkpoints": len(observed),
        "valid_checkpoints": valid,
        "missing_checkpoints": len(expected - observed),
        "orphan_checkpoints": len(observed - expected),
        "duplicate_checkpoints": duplicates,
        "passed": bool(
            observed == expected
            and valid == REPLICATIONS
            and duplicates == 0
        ),
    }


def checkpoint_content_snapshot(
    programme_identity: str,
) -> dict[str, Any]:
    root = _output_dir(programme_identity) / "checkpoints"
    paths = sorted(root.glob("replication_*.json"))
    content = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    return {
        "checkpoint_count": len(paths),
        "content_map_sha256": _payload_sha256(content),
        "total_bytes": sum(path.stat().st_size for path in paths),
    }


def _experiment_a_checkpoint_snapshot() -> dict[str, Any]:
    root = (
        experiment_a.OUTPUT_ROOT
        / EXPERIMENT_A_IDENTITY
        / "checkpoints"
    )
    paths = sorted(root.glob("replication_*.json"))
    content = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    return {
        "checkpoint_count": len(paths),
        "content_map_sha256": _payload_sha256(content),
        "total_bytes": sum(path.stat().st_size for path in paths),
    }


def experiment_a_regression_audit(
    expected_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify the immutable Experiment A evidence and checkpoint boundary."""
    if experiment_a.experiment_identity(MASTER_PROGRAMME_IDENTITY) != (
        EXPERIMENT_A_IDENTITY
    ):
        raise ValueError("Experiment A identity differs.")
    if experiment_a.scientific_code_identity() != (
        EXPERIMENT_A_OPERATIONAL_CODE_IDENTITY
    ):
        raise ValueError("Experiment A operational source changed.")
    evidence_checksums = {
        name: sha256_file(experiment_a.EVIDENCE_DIR / name)
        for name in EXPERIMENT_A_EVIDENCE_CHECKSUMS
    }
    if evidence_checksums != EXPERIMENT_A_EVIDENCE_CHECKSUMS:
        raise ValueError("Experiment A compact evidence changed.")
    decision = json.loads(
        (
            experiment_a.EVIDENCE_DIR
            / "idiosyncratic_diversification_decision.json"
        ).read_text(encoding="utf-8")
    )
    decisions = {
        key: decision[key]
        for key in (
            "A1",
            "A2",
            "A3",
            "overall_h3_classification",
            "peg_solvency_relationship",
        )
    }
    expected_decisions = {
        "A1": "supported",
        "A2": "exposure_gradient_consistent",
        "A3": "shock_localisation_valid",
        "overall_h3_classification": (
            "H3_idiosyncratic_diversification_supported"
        ),
        "peg_solvency_relationship": "solvency_improves_peg_unchanged",
    }
    if decisions != expected_decisions:
        raise ValueError("Experiment A decisions changed.")
    snapshot = _experiment_a_checkpoint_snapshot()
    frozen_snapshot = _frozen_experiment_a_checkpoint_snapshot()
    local_checkpoint_count = int(snapshot["checkpoint_count"])
    if local_checkpoint_count not in {0, EXPERIMENT_A_CHECKPOINT_COUNT}:
        raise ValueError("Experiment A checkpoint set is partial.")
    if local_checkpoint_count and snapshot != frozen_snapshot:
        raise ValueError("Experiment A checkpoint bytes changed.")
    if expected_snapshot is not None:
        for field in (
            "checkpoint_count",
            "content_map_sha256",
            "total_bytes",
        ):
            if frozen_snapshot[field] != expected_snapshot[field]:
                raise ValueError(
                    f"Experiment A checkpoint snapshot changed: {field}."
                )
    return {
        "identity": EXPERIMENT_A_IDENTITY,
        "operational_code_identity": (
            EXPERIMENT_A_OPERATIONAL_CODE_IDENTITY
        ),
        "evidence_checksums": evidence_checksums,
        "decisions": decisions,
        "checkpoint_snapshot": frozen_snapshot,
        "unchanged": True,
        "simulations_executed": 0,
    }


def preflight(programme_identity: str) -> dict[str, Any]:
    """Validate every frozen owner and the result-blind B execution design."""
    programme = load_programme()
    if (
        programme_identity != MASTER_PROGRAMME_IDENTITY
        or programme.programme_identity != MASTER_PROGRAMME_IDENTITY
        or programme.planned_core_cells != 43
        or programme.planned_core_simulations != 5504
    ):
        raise ValueError("Frozen master programme differs.")
    preregistration_path = EVIDENCE_DIR / COMPACT_FILENAMES[0]
    if not preregistration_path.is_file():
        raise ValueError("Experiment B execution requires pre-registration.")
    preregistration = json.loads(
        preregistration_path.read_text(encoding="utf-8")
    )
    if preregistration["experiment_identity"] != experiment_identity(
        programme_identity
    ):
        raise ValueError("Experiment B pre-registration identity differs.")
    _assert_preregistration_matches(programme_identity)
    a_regression = experiment_a_regression_audit(
        preregistration.get("experiment_a_checkpoint_snapshot")
    )
    integrated_owner = resolve_integrated_empirical_eth_profile()
    if (
        integrated_owner.bundle.base_bundle.liquidation_config
        .max_liquidations_per_step
        != CAPACITY
        or multicollateral_validation._profile_identity(PROFILE_SHA256)
        != PROFILE_IDENTITY
    ):
        raise ValueError("Frozen integrated profile owner differs.")
    for portfolio in PORTFOLIO_ORDER:
        for shock in SHOCK_ORDER:
            resolved = resolve_multicollateral_inputs(portfolio, shock)
            if (
                resolved.profile.identifier
                != "empirical_integrated_multicollateral"
                or resolved.profile.checksum != PROFILE_SHA256
                or resolved.profile.runtime_adopted
            ):
                raise ValueError("Integrated multi-collateral profile differs.")
    cells = build_cell_registry(programme)
    records = [
        seed_record(replication) for replication in range(REPLICATIONS)
    ]
    seed_values: list[int] = []
    for record in records:
        seed_values.extend(
            [
                int(record["initialisation_master_seed"]),
                *[
                    int(record[f"{stream}_seed"])
                    for stream in SEED_STREAMS
                    if stream != "initialisation_master"
                ],
            ]
        )
    if len(seed_values) != len(set(seed_values)):
        raise ValueError("Experiment B seed registry contains a collision.")
    nested_records: list[dict[str, Any]] = []
    actual_family_seed_values: list[int] = []
    for replication in range(REPLICATIONS):
        key = initialisation_replication_key(replication)
        states = experiment_a.initialise_nested_portfolios(key)
        audit = experiment_a.audit_nested_initialisations(states)
        accepted_attempts = {
            int(state.accepted_attempt) for state in states.values()
        }
        if not audit["passed"] or len(accepted_attempts) != 1:
            raise ValueError(
                "Experiment B nested initialisation failed for "
                f"replication {replication}."
            )
        accepted_attempt = next(iter(accepted_attempts))
        master_seed = int(records[replication]["initialisation_master_seed"])
        family_seeds = {
            family: experiment_a.derive_seed(
                key,
                f"vault_{family}",
                f"master:{master_seed}:attempt:{accepted_attempt}",
            )
            for family in FAMILY_ORDER
        }
        actual_family_seed_values.extend(family_seeds.values())
        nested_records.append(
            {
                "replication": replication,
                "accepted_attempt": accepted_attempt,
                "family_seeds": family_seeds,
                "state_identities": {
                    portfolio: state.identity
                    for portfolio, state in states.items()
                },
            }
        )
    seed_values.extend(actual_family_seed_values)
    if len(seed_values) != len(set(seed_values)):
        raise ValueError(
            "Experiment B realised initialisation seed contains a collision."
        )
    nested = {
        "passed": True,
        "replication_count": len(nested_records),
        "portfolio_count_per_replication": len(PORTFOLIO_ORDER),
        "failure_count": 0,
        "realised_initialisation_registry_sha256": _payload_sha256(
            nested_records
        ),
        "realised_family_seed_count": len(actual_family_seed_values),
    }
    streams = _prepare_replication_streams(0)
    path_checks: dict[str, Any] = {}
    for shock in SHOCK_ORDER:
        _, _, audit = build_treatment_paths(
            streams["sampled_market"], shock
        )
        expected_gas_owner = (
            "selected_empirical_24h_block"
            if shock == "joint_crypto_empirical_stress"
            else "ordinary_common_market_blocks"
        )
        expected_source_checksum = (
            empirical_source_block_checksum()
            if shock == "joint_crypto_empirical_stress"
            else None
        )
        joint_valid = bool(
            audit["price_isolation_valid"]
            and audit["stable_ordinary_multiplier_valid"]
            and audit["registered_joint_treatment_definition_valid"]
            and audit["resolved_path_diagnostics"]
            and not audit["final_validation_data_used"]
        )
        audit["joint_treatment_path_valid"] = joint_valid
        if not (
            joint_valid
            and audit["gas_owner"] == expected_gas_owner
            and audit["empirical_source_block_sha256"]
            == expected_source_checksum
            and int(audit["gas_stress_summary"]["count"])
            == EMPIRICAL_BLOCK_HOURS
        ):
            raise ValueError("Experiment B shock-path ownership failed.")
        path_checks[shock] = audit
    statuses = {
        item.identifier: {
            "execution_status": item.execution_status,
            "dependency_status": item.dependency_status,
        }
        for item in programme.experiments
    }
    if (
        statuses["B_correlated_stress"]["execution_status"]
        != "preregistered_not_executed"
        or statuses["C_stable_collateral_tradeoff"]["execution_status"]
        != "preregistered_not_executed"
        or statuses["D_shared_keeper_capacity"]["execution_status"]
        != "preregistered_not_executed"
        or statuses["E_oracle_delay"]["execution_status"]
        != "preregistered_blocked_pending_oracle_delay_freeze"
    ):
        raise ValueError("Experiments B-E frozen statuses differ.")
    final_output_root = OUTPUT_ROOT.parent
    unexpected_final_outputs = (
        sorted(
            _relative(path)
            for path in final_output_root.iterdir()
            if path.is_dir()
            and path.name
            not in {
                "idiosyncratic_diversification",
                "correlated_stress",
            }
        )
        if final_output_root.is_dir()
        else []
    )
    if unexpected_final_outputs:
        raise ValueError(
            "A future final experiment output already exists: "
            f"{unexpected_final_outputs}."
        )
    free = shutil.disk_usage(REPOSITORY_ROOT).free
    projected = REPLICATIONS * 250_000
    if free < MINIMUM_FREE_BYTES:
        raise RuntimeError("Fewer than 10 GiB remain.")
    if projected > MAXIMUM_OUTPUT_BYTES:
        raise RuntimeError("Projected Experiment B output exceeds 500 MB.")
    return {
        "parent_commit": EXPERIMENT_B_PARENT_COMMIT,
        "programme_identity": programme_identity,
        "experiment_identity": experiment_identity(programme_identity),
        "scientific_code_identity": scientific_code_identity(),
        "cell_count": len(cells),
        "replications_per_cell": REPLICATIONS,
        "simulation_count": len(cells) * REPLICATIONS,
        "replication_identity_count": len(records),
        "seed_value_count": len(seed_values),
        "seed_collision_count": 0,
        "seed_registry_sha256": seed_registry_checksum(),
        "nested_initialisation_audit": nested,
        "initial_states_reused_across_shocks": True,
        "non_treatment_streams_reused_across_cells": True,
        "path_audits": path_checks,
        "experiment_a_regression": a_regression,
        "experiment_statuses": statuses,
        "unexpected_final_experiment_outputs": unexpected_final_outputs,
        "free_storage_bytes": free,
        "projected_new_output_bytes": projected,
        "minimum_free_storage_satisfied": True,
        "runtime_adopted": False,
    }


def run_smoke(replication: int = 0) -> dict[str, Any]:
    """Run one all-cell smoke check without exposing scientific outcomes."""
    result = simulate_replication(replication)
    cells = pd.DataFrame(result["cell_rows"]).sort_values("cell_order")
    if cells["cell_identifier"].tolist() != list(CELL_ORDER):
        raise ValueError("Experiment B smoke cell order differs.")
    if cells["paired_stream_checksum"].nunique() != 1:
        raise ValueError("Experiment B smoke CRN ownership differs.")
    if (
        cells.groupby(["portfolio", "replication"])["state_checksum"]
        .nunique()
        .ne(1)
        .any()
    ):
        raise ValueError("Experiment B initial state changed across shocks.")
    if cells["gas_unit_draw_checksum"].nunique() != 1:
        raise ValueError("Experiment B gas-unit CRN ownership differs.")
    gas_component_count = (
        cells.groupby("shock")["gas_component_checksum"]
        .first()
        .nunique()
    )
    if gas_component_count != len(SHOCK_ORDER):
        raise ValueError("Experiment B treatment-owned gas did not differ.")
    gas_environment_count = (
        cells.groupby("shock")["gas_environment_checksum"]
        .first()
        .nunique()
    )
    if gas_environment_count != len(SHOCK_ORDER):
        raise ValueError(
            "Experiment B empirical gas environment was not preserved."
        )
    if not cells["joint_treatment_path_valid"].all():
        raise ValueError("Experiment B joint path validation failed.")
    if not cells["accounting_valid"].all():
        raise ValueError("Experiment B smoke accounting failed.")
    if not cells["numerical_valid"].all():
        raise ValueError("Experiment B smoke numerical validation failed.")
    return {
        "replication": replication,
        "cell_count": len(cells),
        "paired_stream_checksum": cells["paired_stream_checksum"].iloc[0],
        "nested_initialisation_valid": result[
            "nested_initialisation_audit"
        ]["passed"],
        "cell_order_valid": True,
        "initial_states_reused_across_shocks": True,
        "common_gas_unit_draws": True,
        "treatment_owned_gas_distinction": (
            gas_component_count == len(SHOCK_ORDER)
            and gas_environment_count == len(SHOCK_ORDER)
        ),
        "joint_treatment_path_valid": True,
        "accounting_valid": True,
        "numerical_valid": True,
        "capacity": CAPACITY,
        "direct_cost_only": True,
        "stage1_only": True,
        "outcomes_inspected": False,
    }


def _worker_initialiser() -> None:
    experiment_a._worker_initialiser()


def run_matrix(
    programme_identity: str,
    *,
    workers: int = 4,
    resume: bool = True,
    max_replications: int | None = None,
) -> dict[str, Any]:
    """Execute or resume atomic one-replication/eight-cell checkpoints."""
    if not 1 <= workers <= 8:
        raise ValueError("workers must lie in [1, 8].")
    specification_path = EVIDENCE_DIR / COMPACT_FILENAMES[0]
    if not specification_path.is_file():
        raise ValueError("Substantive B execution requires pre-registration.")
    registered = json.loads(
        specification_path.read_text(encoding="utf-8")
    )
    identity = experiment_identity(programme_identity)
    if registered["experiment_identity"] != identity:
        raise ValueError("Experiment B pre-registration identity differs.")
    _assert_preregistration_matches(programme_identity)
    count = REPLICATIONS if max_replications is None else int(
        max_replications
    )
    if not 1 <= count <= REPLICATIONS:
        raise ValueError("max_replications lies outside the B design.")
    output_dir = _output_dir(programme_identity)
    tasks: list[int] = []
    reused = 0
    for replication in range(count):
        checkpoint = _checkpoint_path(output_dir, replication)
        if _valid_checkpoint(checkpoint, replication, programme_identity):
            if not resume:
                raise ValueError("Refusing to overwrite a valid checkpoint.")
            reused += 1
        elif checkpoint.exists():
            raise ValueError(
                f"Invalid checkpoint requires review: {checkpoint}."
            )
        else:
            tasks.append(replication)
    started = time.perf_counter()
    completed = 0
    if workers == 1:
        _worker_initialiser()
        for replication in tasks:
            try:
                result = simulate_replication(
                    replication, programme_identity
                )
            except Exception as error:
                _record_execution_failure(
                    output_dir,
                    replication=replication,
                    workers=workers,
                    error=error,
                )
                raise
            checkpoint = _checkpoint_path(output_dir, replication)
            _atomic_json(checkpoint, result)
            if not _valid_checkpoint(
                checkpoint, replication, programme_identity
            ):
                error = RuntimeError(
                    "A newly written Experiment B checkpoint is invalid."
                )
                _record_execution_failure(
                    output_dir,
                    replication=replication,
                    workers=workers,
                    error=error,
                )
                raise error
            completed += 1
    else:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_worker_initialiser,
        ) as executor:
            futures = {
                executor.submit(
                    simulate_replication,
                    replication,
                    programme_identity,
                ): replication
                for replication in tasks
            }
            for future in as_completed(futures):
                replication = futures[future]
                try:
                    result = future.result()
                except Exception as error:
                    for pending in futures:
                        pending.cancel()
                    _record_execution_failure(
                        output_dir,
                        replication=replication,
                        workers=workers,
                        error=error,
                    )
                    raise
                if int(result["replication"]) != replication:
                    error = RuntimeError(
                        "An Experiment B worker returned the wrong "
                        "replication."
                    )
                    for pending in futures:
                        pending.cancel()
                    _record_execution_failure(
                        output_dir,
                        replication=replication,
                        workers=workers,
                        error=error,
                    )
                    raise error
                checkpoint = _checkpoint_path(output_dir, replication)
                _atomic_json(checkpoint, result)
                if not _valid_checkpoint(
                    checkpoint, replication, programme_identity
                ):
                    error = RuntimeError(
                        "A newly written Experiment B checkpoint is invalid."
                    )
                    for pending in futures:
                        pending.cancel()
                    _record_execution_failure(
                        output_dir,
                        replication=replication,
                        workers=workers,
                        error=error,
                    )
                    raise error
                completed += 1
    wall = time.perf_counter() - started
    output_size = sum(
        path.stat().st_size
        for path in output_dir.rglob("*")
        if path.is_file()
    )
    if output_size > MAXIMUM_OUTPUT_BYTES:
        raise RuntimeError("Experiment B output exceeds 500 MB.")
    checkpoint_audit = audit_checkpoints(programme_identity)
    complete = completed + reused == REPLICATIONS
    if complete and not checkpoint_audit["passed"]:
        raise RuntimeError("Completed Experiment B checkpoint audit failed.")
    return {
        "experiment_identity": identity,
        "worker_count": workers,
        "completed_replications": completed,
        "reused_replications": reused,
        "resumed_replications": reused if resume and reused > 0 else 0,
        "failed_replications": 0,
        "rerun_replications": 0,
        "checkpoint_count": checkpoint_audit["valid_checkpoints"],
        "checkpoint_audit": checkpoint_audit,
        "completed_simulations": (completed + reused) * len(CELL_ORDER),
        "wall_time_seconds": wall,
        "throughput_simulations_per_second": (
            0.0
            if wall == 0.0
            else completed * len(CELL_ORDER) / wall
        ),
        "output_size_bytes": output_size,
        "free_storage_bytes": shutil.disk_usage(REPOSITORY_ROOT).free,
        "complete": complete,
    }


def load_results(
    programme_identity: str,
    *,
    require_complete: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load valid B checkpoints in stable cell/replication order."""
    output_dir = _output_dir(programme_identity)
    cell_rows: list[dict[str, Any]] = []
    collateral_rows: list[dict[str, Any]] = []
    for replication in range(REPLICATIONS):
        path = _checkpoint_path(output_dir, replication)
        if not _valid_checkpoint(path, replication, programme_identity):
            if require_complete:
                raise ValueError(f"Missing valid checkpoint: {path}.")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        cell_rows.extend(payload["cell_rows"])
        collateral_rows.extend(payload["collateral_rows"])
    cells = pd.DataFrame(cell_rows)
    collateral = pd.DataFrame(collateral_rows)
    if require_complete and (
        len(cells) != REPLICATIONS * len(CELL_ORDER)
        or len(collateral)
        != REPLICATIONS * len(CELL_ORDER) * len(FAMILY_ORDER)
    ):
        raise ValueError("Experiment B result dimensions differ.")
    if not cells.empty:
        for replication, group in cells.groupby("replication"):
            if (
                len(group) != len(CELL_ORDER)
                or group["paired_stream_checksum"].nunique() != 1
                or group["gas_unit_draw_checksum"].nunique() != 1
            ):
                raise ValueError(
                    f"Experiment B CRN failed for replication {replication}."
                )
        cells = cells.sort_values(
            ["cell_order", "replication"], kind="mergesort"
        ).reset_index(drop=True)
        collateral = collateral.sort_values(
            ["cell_order", "family", "replication"],
            kind="mergesort",
        ).reset_index(drop=True)
    return cells, collateral


def _distribution(values: Iterable[float]) -> dict[str, float]:
    return experiment_a._distribution(values)


def _valid_rows(frame: pd.DataFrame) -> pd.Series:
    valid = pd.Series(True, index=frame.index, dtype=bool)
    for column in (
        "numerical_valid",
        "accounting_valid",
        "joint_treatment_path_valid",
        "price_isolation_valid",
        "nested_initialisation_valid",
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
    """Classify one pre-registered metric without replacing it."""
    if metric not in frame:
        return "not_operational"
    if frame.empty or not _valid_rows(frame).any():
        return "invalid"
    values = pd.to_numeric(frame.loc[_valid_rows(frame), metric], errors="coerce")
    if values.empty or values.isna().all():
        return "not_operational"
    if values.isna().any() or not np.isfinite(values.to_numpy()).all():
        return "invalid"
    array = values.to_numpy(dtype=float)
    all_equal = float(array.max() - array.min()) <= tolerance
    every_cell_constant = all(
        float(group.max() - group.min()) <= tolerance
        for _, group in frame.loc[_valid_rows(frame)].groupby(
            "cell_identifier", sort=False
        )[metric]
    )
    if all_equal or every_cell_constant:
        return "degenerate"
    return "operational"


def metric_operationality(frame: pd.DataFrame) -> dict[str, str]:
    return {
        metric: classify_metric_operationality(frame, metric)
        for metric in SYSTEM_METRICS
    }


def cell_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    operationality = metric_operationality(frame)
    for key, group in frame.groupby(
        ["cell_order", "cell_identifier", "shock", "portfolio"],
        sort=False,
    ):
        valid_mask = _valid_rows(group)
        valid_group = group.loc[valid_mask]
        if valid_group.empty:
            raise ValueError("An Experiment B cell has no valid replications.")
        for metric in (*SYSTEM_METRICS, *SYSTEM_DIAGNOSTICS):
            rows.append(
                {
                    **dict(
                        zip(
                            (
                                "cell_order",
                                "cell_identifier",
                                "shock",
                                "portfolio",
                            ),
                            key,
                            strict=True,
                        )
                    ),
                    "metric": metric,
                    "operationality": operationality.get(
                        metric, "diagnostic"
                    ),
                    "valid_replication_count": int(len(valid_group)),
                    **_distribution(valid_group[metric]),
                    "censoring_count": (
                        int(valid_group["right_censored"].sum())
                        if metric == "restricted_mean_recovery_time"
                        else 0
                    ),
                    "numerical_failure_count": int((~valid_mask).sum()),
                }
            )
    result = pd.DataFrame(rows)
    expected = len(CELL_ORDER) * (
        len(SYSTEM_METRICS) + len(SYSTEM_DIAGNOSTICS)
    )
    if len(result) != expected:
        raise ValueError("Experiment B cell-summary dimensions differ.")
    return result


def collateral_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_columns = [
        "cell_order",
        "cell_identifier",
        "shock",
        "portfolio",
        "family",
    ]
    for key, group in frame.groupby(group_columns, sort=False):
        valid_group = group.loc[_valid_rows(group)]
        for metric in COLLATERAL_METRICS:
            values = pd.to_numeric(valid_group[metric], errors="coerce")
            applicable = values.notna()
            row = {
                **dict(zip(group_columns, key, strict=True)),
                "metric": metric,
                "applicable_replication_count": int(applicable.sum()),
                "not_applicable_replication_count": int(
                    len(valid_group) - applicable.sum()
                ),
                "invalid_replication_count": int(
                    len(group) - len(valid_group)
                ),
            }
            if applicable.any():
                row.update(_distribution(values[applicable]))
            else:
                row.update(
                    {
                        name: None
                        for name in (
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
                            "minimum",
                            "maximum",
                            "positive_share",
                        )
                    }
                )
            rows.append(row)
    result = pd.DataFrame(rows)
    expected = (
        len(CELL_ORDER) * len(FAMILY_ORDER) * len(COLLATERAL_METRICS)
    )
    if len(result) != expected:
        raise ValueError("Experiment B collateral-summary dimensions differ.")
    result["_cell_order"] = result["cell_identifier"].map(
        {identifier: index for index, identifier in enumerate(CELL_ORDER)}
    )
    result["_family_order"] = result["family"].map(
        {family: index for index, family in enumerate(FAMILY_ORDER)}
    )
    result["_metric_order"] = result["metric"].map(
        {metric: index for index, metric in enumerate(COLLATERAL_METRICS)}
    )
    if result[
        ["_cell_order", "_family_order", "_metric_order"]
    ].isna().any().any():
        raise ValueError("Experiment B collateral-summary key is unregistered.")
    result = (
        result.sort_values(
            ["_cell_order", "_family_order", "_metric_order"],
            kind="mergesort",
        )
        .drop(columns=["_cell_order", "_family_order", "_metric_order"])
        .reset_index(drop=True)
    )
    return result


def _paired_frames(
    frame: pd.DataFrame,
    *,
    shock: str,
    left: str,
    right: str,
) -> pd.DataFrame:
    selected = frame.loc[frame["shock"].eq(shock)]
    paired = selected.loc[selected["portfolio"].eq(left)].merge(
        selected.loc[selected["portfolio"].eq(right)],
        on="replication",
        suffixes=("_left", "_right"),
        validate="one_to_one",
    )
    valid = pd.Series(True, index=paired.index, dtype=bool)
    for column in (
        "numerical_valid",
        "accounting_valid",
        "joint_treatment_path_valid",
        "price_isolation_valid",
        "nested_initialisation_valid",
    ):
        valid &= paired[f"{column}_left"].astype(bool)
        valid &= paired[f"{column}_right"].astype(bool)
    paired = paired.loc[valid]
    if len(paired) != REPLICATIONS:
        raise ValueError("An Experiment B contrast lost valid pairs.")
    return paired


def _uncertainty_row(
    differences: np.ndarray,
    *,
    metric: str,
    left_values: pd.Series | None = None,
    right_values: pd.Series | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "pair_count": len(differences),
        **_distribution(differences),
    }
    row["paired_probability_difference"] = (
        float(np.mean(differences))
        if metric in BINARY_METRICS
        else None
    )
    if metric in BINARY_METRICS:
        if left_values is None or right_values is None:
            row["discordant_left_one_right_zero"] = None
            row["discordant_left_zero_right_one"] = None
        else:
            left_binary = left_values.astype(int)
            right_binary = right_values.astype(int)
            row["discordant_left_one_right_zero"] = int(
                ((left_binary == 1) & (right_binary == 0)).sum()
            )
            row["discordant_left_zero_right_one"] = int(
                ((left_binary == 0) & (right_binary == 1)).sum()
            )
    else:
        row["discordant_left_one_right_zero"] = None
        row["discordant_left_zero_right_one"] = None
    return row


def paired_contrasts(frame: pd.DataFrame) -> pd.DataFrame:
    """Build raw, advantage and deterioration rows with paired uncertainty."""
    statuses = metric_operationality(frame)
    rows: list[dict[str, Any]] = []
    advantage_arrays: dict[tuple[str, str, str], pd.Series] = {}
    advantage_discordance: dict[
        tuple[str, str, str], tuple[int, int]
    ] = {}

    for shock in SHOCK_ORDER:
        for left, right in RAW_PORTFOLIO_CONTRASTS:
            paired = _paired_frames(
                frame, shock=shock, left=left, right=right
            )
            for metric in SYSTEM_METRICS:
                left_values = paired[f"{metric}_left"]
                right_values = paired[f"{metric}_right"]
                differences = (
                    left_values.to_numpy(dtype=float)
                    - right_values.to_numpy(dtype=float)
                )
                rows.append(
                    {
                        "contrast_type": "raw_portfolio_contrast",
                        "shock": shock,
                        "portfolio": left,
                        "left_portfolio": left,
                        "right_portfolio": right,
                        "contrast": f"{left} - {right}",
                        "metric": metric,
                        "direction_multiplier": 1,
                        "operationality": statuses[metric],
                        "reversal_flag": None,
                        **_uncertainty_row(
                            differences,
                            metric=metric,
                            left_values=left_values,
                            right_values=right_values,
                        ),
                    }
                )
        for portfolio in DIVERSIFIED_PORTFOLIOS:
            paired = _paired_frames(
                frame,
                shock=shock,
                left=portfolio,
                right="eth_only",
            )
            for metric in SYSTEM_METRICS:
                multiplier = METRIC_DIRECTIONS[metric]
                raw = (
                    paired[f"{metric}_left"].to_numpy(dtype=float)
                    - paired[f"{metric}_right"].to_numpy(dtype=float)
                )
                advantages = multiplier * raw
                advantage_arrays[(shock, portfolio, metric)] = pd.Series(
                    advantages,
                    index=paired["replication"].astype(int).to_numpy(),
                ).sort_index()
                if metric in BINARY_METRICS:
                    left_binary = paired[f"{metric}_left"].astype(int)
                    right_binary = paired[f"{metric}_right"].astype(int)
                    advantage_discordance[(shock, portfolio, metric)] = (
                        int(
                            (
                                (left_binary == 1)
                                & (right_binary == 0)
                            ).sum()
                        ),
                        int(
                            (
                                (left_binary == 0)
                                & (right_binary == 1)
                            ).sum()
                        ),
                    )
                rows.append(
                    {
                        "contrast_type": (
                            "direction_normalised_advantage"
                        ),
                        "shock": shock,
                        "portfolio": portfolio,
                        "left_portfolio": portfolio,
                        "right_portfolio": "eth_only",
                        "contrast": (
                            f"advantage({portfolio}, {shock})"
                        ),
                        "metric": metric,
                        "direction_multiplier": multiplier,
                        "operationality": statuses[metric],
                        "reversal_flag": None,
                        **_uncertainty_row(
                            advantages,
                            metric=metric,
                            left_values=paired[f"{metric}_left"],
                            right_values=paired[f"{metric}_right"],
                        ),
                    }
                )

    for portfolio in DIVERSIFIED_PORTFOLIOS:
        for metric in SYSTEM_METRICS:
            empirical = advantage_arrays[
                (
                    "joint_crypto_empirical_stress",
                    portfolio,
                    metric,
                )
            ]
            high = advantage_arrays[
                (
                    "joint_crypto_high_correlation",
                    portfolio,
                    metric,
                )
            ]
            paired_advantages = pd.concat(
                {
                    "empirical": empirical,
                    "high_correlation": high,
                },
                axis=1,
                join="inner",
            )
            if (
                len(paired_advantages) != REPLICATIONS
                or not paired_advantages.index.is_unique
            ):
                raise ValueError(
                    "Experiment B deterioration interaction lost CRN pairs."
                )
            differences = (
                paired_advantages["empirical"]
                - paired_advantages["high_correlation"]
            ).to_numpy(dtype=float)
            high_distribution = _distribution(
                paired_advantages["high_correlation"]
            )
            empirical_discordance = advantage_discordance.get(
                (
                    "joint_crypto_empirical_stress",
                    portfolio,
                    metric,
                ),
                (None, None),
            )
            high_discordance = advantage_discordance.get(
                (
                    "joint_crypto_high_correlation",
                    portfolio,
                    metric,
                ),
                (None, None),
            )
            rows.append(
                {
                    "contrast_type": (
                        "correlation_deterioration_interaction"
                    ),
                    "shock": "empirical_minus_high_correlation",
                    "portfolio": portfolio,
                    "left_portfolio": (
                        "joint_crypto_empirical_stress_advantage"
                    ),
                    "right_portfolio": (
                        "joint_crypto_high_correlation_advantage"
                    ),
                    "contrast": (
                        "advantage_empirical - advantage_high_correlation"
                    ),
                    "metric": metric,
                    "direction_multiplier": METRIC_DIRECTIONS[metric],
                    "operationality": statuses[metric],
                    "reversal_flag": bool(
                        high_distribution["mean"] < 0.0
                        and high_distribution["ci95_upper"] < 0.0
                    ),
                    "empirical_discordant_left_one_right_zero": (
                        empirical_discordance[0]
                    ),
                    "empirical_discordant_left_zero_right_one": (
                        empirical_discordance[1]
                    ),
                    "high_correlation_discordant_left_one_right_zero": (
                        high_discordance[0]
                    ),
                    "high_correlation_discordant_left_zero_right_one": (
                        high_discordance[1]
                    ),
                    **_uncertainty_row(
                        differences,
                        metric=metric,
                    ),
                }
            )
    result = pd.DataFrame(rows)
    if len(result) != 294:
        raise ValueError("Experiment B contrast dimensions differ.")
    return result


def _contrast_row(
    contrasts: pd.DataFrame,
    *,
    contrast_type: str,
    portfolio: str,
    metric: str,
    shock: str | None = None,
) -> pd.Series:
    selected = contrasts.loc[
        contrasts["contrast_type"].eq(contrast_type)
        & contrasts["portfolio"].eq(portfolio)
        & contrasts["metric"].eq(metric)
    ]
    if shock is not None:
        selected = selected.loc[selected["shock"].eq(shock)]
    if len(selected) != 1:
        raise ValueError("Expected one Experiment B contrast row.")
    return selected.iloc[0]


def classify_b1(
    contrasts: pd.DataFrame,
    operationality: Mapping[str, str],
    *,
    valid: bool,
) -> tuple[str, dict[str, Any]]:
    if not valid:
        return "invalid", {}
    metrics = [
        metric
        for metric in PRIMARY_SOLVENCY_METRICS
        if operationality.get(metric) == "operational"
    ]
    if len(metrics) < 2:
        return "not_operational", {"operational_metrics": metrics}
    details: dict[str, Any] = {}
    qualifying = 0
    for portfolio in DIVERSIFIED_PORTFOLIOS:
        beneficial: list[str] = []
        adverse_bad_debt: list[str] = []
        for metric in metrics:
            row = _contrast_row(
                contrasts,
                contrast_type="direction_normalised_advantage",
                shock="joint_crypto_empirical_stress",
                portfolio=portfolio,
                metric=metric,
            )
            if row["mean"] > 0.0 and row["ci95_lower"] > 0.0:
                beneficial.append(metric)
            if (
                metric == "realised_bad_debt_share"
                and row["mean"] < 0.0
                and row["ci95_upper"] < 0.0
            ):
                adverse_bad_debt.append(metric)
        satisfied = len(beneficial) >= 2 and not adverse_bad_debt
        qualifying += int(satisfied)
        details[portfolio] = {
            "beneficial_metrics": beneficial,
            "adverse_bad_debt_metrics": adverse_bad_debt,
            "beneficial_rule_satisfied": satisfied,
        }
    classification = (
        "supported"
        if qualifying >= 2
        else "partially_supported" if qualifying == 1 else "not_supported"
    )
    return classification, {
        "operational_metrics": metrics,
        "qualifying_portfolio_count": qualifying,
        "portfolio_results": details,
    }


def classify_b2(
    contrasts: pd.DataFrame,
    operationality: Mapping[str, str],
    *,
    valid: bool,
) -> tuple[str, dict[str, Any]]:
    if not valid:
        return "invalid", {}
    metrics = [
        metric
        for metric in PRIMARY_SOLVENCY_METRICS
        if operationality.get(metric) == "operational"
    ]
    if len(metrics) < 2:
        return "not_operational", {"operational_metrics": metrics}
    details: dict[str, Any] = {}
    deterioration_portfolios = 0
    one_metric_portfolios = 0
    reversal_portfolios = 0
    for portfolio in DIVERSIFIED_PORTFOLIOS:
        deterioration: list[str] = []
        opposite: list[str] = []
        reversals: list[str] = []
        for metric in metrics:
            interaction = _contrast_row(
                contrasts,
                contrast_type="correlation_deterioration_interaction",
                portfolio=portfolio,
                metric=metric,
            )
            if (
                interaction["mean"] > 0.0
                and interaction["ci95_lower"] > 0.0
            ):
                deterioration.append(metric)
            if (
                interaction["mean"] < 0.0
                and interaction["ci95_upper"] < 0.0
                and abs(float(interaction["mean"]))
                >= MATERIALITY_THRESHOLDS[metric]
            ):
                opposite.append(metric)
            high = _contrast_row(
                contrasts,
                contrast_type="direction_normalised_advantage",
                shock="joint_crypto_high_correlation",
                portfolio=portfolio,
                metric=metric,
            )
            if high["mean"] < 0.0 and high["ci95_upper"] < 0.0:
                reversals.append(metric)
        qualifies = len(deterioration) >= 2 and not opposite
        deterioration_portfolios += int(qualifies)
        one_metric_portfolios += int(len(deterioration) >= 1)
        reversal_portfolios += int(len(reversals) >= 2)
        details[portfolio] = {
            "deteriorating_metrics": deterioration,
            "material_opposite_metrics": opposite,
            "reversal_metrics": reversals,
            "deterioration_rule_satisfied": qualifies,
        }
    if reversal_portfolios >= 2:
        classification = "correlation_reversal_present"
    elif deterioration_portfolios >= 2:
        classification = "correlation_deterioration_present"
    elif deterioration_portfolios == 1 or one_metric_portfolios >= 2:
        classification = "correlation_deterioration_partial"
    else:
        classification = "correlation_deterioration_not_present"
    return classification, {
        "operational_metrics": metrics,
        "deterioration_portfolio_count": deterioration_portfolios,
        "portfolios_with_at_least_one_deteriorating_metric": (
            one_metric_portfolios
        ),
        "reversal_portfolio_count": reversal_portfolios,
        "portfolio_results": details,
    }


def classify_b3(
    cells: pd.DataFrame,
    collateral: pd.DataFrame,
    *,
    valid: bool,
) -> tuple[str, dict[str, Any]]:
    if not valid:
        return "transmission_invalid", {}
    high_cells = cells.loc[
        cells["shock"].eq("joint_crypto_high_correlation")
    ]
    high_collateral = collateral.loc[
        collateral["shock"].eq("joint_crypto_high_correlation")
    ]
    capacity_operational = bool(
        (high_cells["binding_hours"] > 0).any()
        or (high_collateral["displaced_candidates"] > 0).any()
    )
    if not capacity_operational:
        return "transmission_not_operational", {
            "shared_capacity_operational": False
        }
    results: dict[str, Any] = {}
    complete = 0
    at_least_two = 0
    for portfolio in DIVERSIFIED_PORTFOLIOS:
        selected = high_collateral.loc[
            high_collateral["portfolio"].eq(portfolio)
        ]
        family_means = selected.groupby("family", sort=False).mean(
            numeric_only=True
        )
        eth_activity = bool(
            family_means.loc["ETH", "unsafe_vault_count"] > 0.0
            or family_means.loc["ETH", "liquidated_debt"] > 0.0
        )
        wbtc_activity = bool(
            family_means.loc["WBTC", "unsafe_vault_count"] > 0.0
            or family_means.loc["WBTC", "liquidated_debt"] > 0.0
        )
        two_family_backlog = (
            int((family_means["backlog_area"] > 0.0).sum()) >= 2
        )
        displacement = bool(
            (family_means["displaced_candidates"] > 0.0).any()
        )
        simultaneous = cells.loc[
            cells["portfolio"].eq(portfolio),
            [
                "replication",
                "shock",
                "share_hours_eth_wbtc_simultaneously_unsafe",
            ],
        ]
        pivot = simultaneous.pivot(
            index="replication",
            columns="shock",
            values="share_hours_eth_wbtc_simultaneously_unsafe",
        )
        paired_change = (
            pivot["joint_crypto_high_correlation"]
            - pivot["joint_crypto_empirical_stress"]
        )
        simultaneous_increase = bool(paired_change.mean() > 0.0)
        conditions = {
            "eth_and_wbtc_activity": eth_activity and wbtc_activity,
            "at_least_two_backlog_families": two_family_backlog,
            "positive_displacement": displacement,
            "simultaneous_unsafe_share_increases": simultaneous_increase,
        }
        count = sum(conditions.values())
        complete += int(count == 4)
        at_least_two += int(count >= 2)
        results[portfolio] = {
            "conditions": conditions,
            "condition_count": count,
            "mean_simultaneous_unsafe_share_change": float(
                paired_change.mean()
            ),
            "paired_simultaneous_unsafe_share_change": _distribution(
                paired_change
            ),
        }
    classification = (
        "transmission_intensifies"
        if complete >= 2
        else "transmission_mixed"
        if at_least_two >= 2
        else "transmission_not_present"
    )
    return classification, {
        "shared_capacity_operational": True,
        "complete_rule_portfolio_count": complete,
        "at_least_two_conditions_portfolio_count": at_least_two,
        "portfolio_results": results,
    }


def classify_persistence(
    contrasts: pd.DataFrame,
    operationality: Mapping[str, str],
) -> dict[str, Any]:
    metrics = [
        metric
        for metric in PRIMARY_SOLVENCY_METRICS
        if operationality.get(metric) == "operational"
    ]
    results: dict[str, Any] = {}
    for portfolio in DIVERSIFIED_PORTFOLIOS:
        if len(metrics) < 2:
            results[portfolio] = {
                "classification": "not_operational",
                "operational_metrics": metrics,
            }
            continue
        beneficial: list[str] = []
        adverse: list[str] = []
        deteriorating: list[str] = []
        for metric in metrics:
            high = _contrast_row(
                contrasts,
                contrast_type="direction_normalised_advantage",
                shock="joint_crypto_high_correlation",
                portfolio=portfolio,
                metric=metric,
            )
            interaction = _contrast_row(
                contrasts,
                contrast_type="correlation_deterioration_interaction",
                portfolio=portfolio,
                metric=metric,
            )
            if high["mean"] > 0.0 and high["ci95_lower"] > 0.0:
                beneficial.append(metric)
            if high["mean"] < 0.0 and high["ci95_upper"] < 0.0:
                adverse.append(metric)
            if (
                interaction["mean"] > 0.0
                and interaction["ci95_lower"] > 0.0
            ):
                deteriorating.append(metric)
        if len(adverse) >= 2:
            classification = "reversed"
        elif len(beneficial) >= 2 and len(deteriorating) >= 2:
            classification = "weakens_but_remains"
        elif len(beneficial) >= 2:
            classification = "persists"
        elif not beneficial and not adverse:
            classification = "neutralised"
        else:
            classification = "mixed"
        results[portfolio] = {
            "classification": classification,
            "beneficial_metrics": beneficial,
            "adverse_metrics": adverse,
            "deteriorating_metrics": deteriorating,
            "operational_metrics": metrics,
        }
    return results


def _group_deterioration_state(
    contrasts: pd.DataFrame,
    metrics: Sequence[str],
    operationality: Mapping[str, str],
) -> dict[str, Any]:
    deteriorating: list[dict[str, str]] = []
    improving: list[dict[str, str]] = []
    for portfolio in DIVERSIFIED_PORTFOLIOS:
        for metric in metrics:
            if operationality.get(metric) != "operational":
                continue
            row = _contrast_row(
                contrasts,
                contrast_type="correlation_deterioration_interaction",
                portfolio=portfolio,
                metric=metric,
            )
            threshold = MATERIALITY_THRESHOLDS[metric]
            if (
                row["mean"] >= threshold
                and row["ci95_lower"] > 0.0
            ):
                deteriorating.append(
                    {"portfolio": portfolio, "metric": metric}
                )
            if (
                row["mean"] <= -threshold
                and row["ci95_upper"] < 0.0
            ):
                improving.append(
                    {"portfolio": portfolio, "metric": metric}
                )
    if len(deteriorating) >= 2 and len(improving) >= 2:
        state = "mixed"
    elif len(deteriorating) >= 2:
        state = "deteriorates"
    elif len(improving) >= 2:
        state = "improves"
    else:
        state = "unchanged"
    return {
        "state": state,
        "material_deteriorating_rows": deteriorating,
        "material_improving_rows": improving,
    }


def classify_peg_solvency(
    contrasts: pd.DataFrame,
    operationality: Mapping[str, str],
    *,
    valid: bool,
) -> tuple[str, dict[str, Any]]:
    if not valid:
        return "relationship_invalid", {}
    solvency = _group_deterioration_state(
        contrasts,
        PRIMARY_SOLVENCY_METRICS,
        operationality,
    )
    peg = _group_deterioration_state(
        contrasts,
        PEG_METRICS,
        operationality,
    )
    pair = (solvency["state"], peg["state"])
    if pair == ("deteriorates", "deteriorates"):
        classification = "solvency_and_peg_deteriorate_with_correlation"
    elif pair == ("deteriorates", "unchanged"):
        classification = "solvency_deteriorates_peg_unchanged"
    elif pair == ("unchanged", "deteriorates"):
        classification = "peg_deteriorates_solvency_unchanged"
    elif pair == ("unchanged", "unchanged"):
        classification = "neither_materially_changes"
    elif "mixed" in pair:
        classification = "relationship_mixed"
    elif (
        ("deteriorates" in pair and "improves" in pair)
        or pair == ("improves", "deteriorates")
    ):
        classification = "solvency_and_peg_diverge"
    else:
        classification = "relationship_mixed"
    return classification, {"solvency": solvency, "peg": peg}


def _validity_audit(
    cells: pd.DataFrame,
    *,
    registry_valid: bool = True,
    checkpoint_valid: bool = True,
    final_validation_data_used: bool = False,
) -> dict[str, Any]:
    numerical_failures = int(
        (~cells["numerical_valid"].astype(bool)).sum()
    )
    accounting_failures = int(
        (~cells["accounting_valid"].astype(bool)).sum()
    )
    path_failures = int(
        (~cells["joint_treatment_path_valid"].astype(bool)).sum()
    )
    isolation_failures = int(
        (~cells["price_isolation_valid"].astype(bool)).sum()
    )
    nested_failures = int(
        (~cells["nested_initialisation_valid"].astype(bool)).sum()
    )
    crn_failures = int(
        cells.groupby("replication")["paired_stream_checksum"]
        .nunique()
        .ne(1)
        .sum()
    )
    gas_unit_failures = int(
        cells.groupby("replication")["gas_unit_draw_checksum"]
        .nunique()
        .ne(1)
        .sum()
    )
    gas_by_shock = (
        cells.groupby(["replication", "shock"], sort=False)
        .first()
        .reset_index()
    )
    gas_component_failures = int(
        gas_by_shock.groupby("replication")["gas_component_checksum"]
        .nunique()
        .ne(len(SHOCK_ORDER))
        .sum()
    )
    gas_environment_failures = int(
        gas_by_shock.groupby("replication")["gas_environment_checksum"]
        .nunique()
        .ne(len(SHOCK_ORDER))
        .sum()
    )
    expected_gas_owners = {
        "joint_crypto_empirical_stress": "selected_empirical_24h_block",
        "joint_crypto_high_correlation": "ordinary_common_market_blocks",
    }
    gas_owner_failures = int(
        (
            gas_by_shock["gas_owner"]
            != gas_by_shock["shock"].map(expected_gas_owners)
        ).sum()
    )
    state_failures = int(
        cells.groupby(["replication", "portfolio"])["state_checksum"]
        .nunique()
        .ne(1)
        .sum()
    )
    path_order_failures = int(
        cells.groupby(["replication", "shock"])["price_path_checksum"]
        .nunique()
        .ne(1)
        .sum()
    )
    invariant_failures = int(
        (
            ~cells[
                [
                    "finite_collateral_prices_valid",
                    "finite_dai_price_valid",
                    "nonnegative_backlog_valid",
                    "nonnegative_bad_debt_valid",
                    "nonnegative_vault_balances_valid",
                    "unique_vault_identifiers",
                    "shared_capacity_valid",
                    "complete_metadata_valid",
                ]
            ]
            .astype(bool)
            .all(axis=1)
        ).sum()
    )
    cell_failure_shares = (
        cells.assign(failed=~_valid_rows(cells))
        .groupby("cell_identifier")["failed"]
        .mean()
    )
    experiment_valid = bool(
        numerical_failures == 0
        and accounting_failures == 0
        and path_failures == 0
        and isolation_failures == 0
        and nested_failures == 0
        and crn_failures == 0
        and gas_unit_failures == 0
        and gas_component_failures == 0
        and gas_environment_failures == 0
        and gas_owner_failures == 0
        and state_failures == 0
        and path_order_failures == 0
        and invariant_failures == 0
        and float(cell_failure_shares.max()) == 0.0
        and registry_valid
        and checkpoint_valid
        and not final_validation_data_used
    )
    return {
        "numerical_failure_count": numerical_failures,
        "accounting_failure_count": accounting_failures,
        "joint_path_failure_count": path_failures,
        "price_ownership_failure_count": isolation_failures,
        "nested_initialisation_failure_count": nested_failures,
        "crn_failure_count": crn_failures,
        "gas_unit_crn_failure_count": gas_unit_failures,
        "treatment_gas_component_failure_count": gas_component_failures,
        "treatment_gas_environment_failure_count": (
            gas_environment_failures
        ),
        "treatment_gas_owner_failure_count": gas_owner_failures,
        "state_reuse_failure_count": state_failures,
        "path_order_failure_count": path_order_failures,
        "simulation_invariant_failure_count": invariant_failures,
        "maximum_cell_failure_share": float(cell_failure_shares.max()),
        "registry_resolution_failure_count": int(not registry_valid),
        "checkpoint_ownership_failure_count": int(not checkpoint_valid),
        "final_validation_data_used": final_validation_data_used,
        "experiment_valid": experiment_valid,
    }


def classify_results(
    cells: pd.DataFrame,
    collateral: pd.DataFrame,
    contrasts: pd.DataFrame,
    *,
    registry_valid: bool = True,
    checkpoint_valid: bool = True,
    final_validation_data_used: bool = False,
) -> dict[str, Any]:
    validity = _validity_audit(
        cells,
        registry_valid=registry_valid,
        checkpoint_valid=checkpoint_valid,
        final_validation_data_used=final_validation_data_used,
    )
    valid = bool(validity["experiment_valid"])
    operationality = metric_operationality(cells)
    b1, b1_detail = classify_b1(
        contrasts, operationality, valid=valid
    )
    b2, b2_detail = classify_b2(
        contrasts, operationality, valid=valid
    )
    b3, b3_detail = classify_b3(
        cells, collateral, valid=valid
    )
    persistence = (
        classify_persistence(contrasts, operationality)
        if valid
        else {
            portfolio: {
                "classification": "not_operational",
                "experiment_invalid": True,
            }
            for portfolio in DIVERSIFIED_PORTFOLIOS
        }
    )
    persistent_count = sum(
        row["classification"] == "persists"
        for row in persistence.values()
    )
    b3_valid = b3 != "transmission_invalid"
    if not valid:
        overall = "H3_correlated_stress_experiment_invalid"
    elif b2 == "correlation_reversal_present" and b3_valid:
        overall = "H3_correlation_reverses_diversification"
    elif (
        b1 in {"supported", "partially_supported"}
        and b2 == "correlation_deterioration_present"
        and b3 in {"transmission_intensifies", "transmission_mixed"}
    ):
        overall = "H3_correlation_deterioration_supported"
    elif (
        b2 == "correlation_deterioration_partial"
        or (
            b3 == "transmission_mixed"
            and b2_detail.get(
                "portfolios_with_at_least_one_deteriorating_metric", 0
            )
            > 0
        )
    ):
        overall = "H3_correlation_deterioration_partially_supported"
    elif (
        b1 == "supported"
        and b2 == "correlation_deterioration_not_present"
        and persistent_count >= 2
        and b3_valid
    ):
        overall = "H3_diversification_robust_to_high_correlation"
    elif (
        b3_valid
        and b2 == "correlation_deterioration_not_present"
    ):
        overall = "H3_no_clear_correlated_stress_effect"
    else:
        raise ValueError(
            "Experiment B decision state is outside the registered hierarchy."
        )
    relationship, relationship_detail = classify_peg_solvency(
        contrasts, operationality, valid=valid
    )
    return {
        "metric_operationality": operationality,
        "B1": b1,
        "B1_detail": b1_detail,
        "B2": b2,
        "B2_detail": b2_detail,
        "B3": b3,
        "B3_detail": b3_detail,
        "high_correlation_persistence": persistence,
        "overall_h3_classification": overall,
        "peg_solvency_relationship": relationship,
        "peg_solvency_detail": relationship_detail,
        "validity_audit": validity,
        "experiment_valid": valid,
    }


def _path_audit_summary(programme_identity: str) -> dict[str, Any]:
    records: dict[str, list[dict[str, Any]]] = {
        shock: [] for shock in SHOCK_ORDER
    }
    output_dir = _output_dir(programme_identity)
    for replication in range(REPLICATIONS):
        payload = json.loads(
            _checkpoint_path(output_dir, replication).read_text(
                encoding="utf-8"
            )
        )
        for shock in SHOCK_ORDER:
            records[shock].append(payload["path_audits"][shock])
    result: dict[str, Any] = {}
    scalar_fields = (
        "eth_24h_minimum_log_return",
        "wbtc_24h_minimum_log_return",
        "eth_wbtc_return_correlation_stress_window",
        "selected_source_block_eth_wbtc_return_correlation",
        "selected_source_block_joint_negative_hours",
        "hours_both_negative_treatment_returns",
        "hours_both_below_registered_stress_thresholds",
        "maximum_simultaneous_drawdown",
    )
    for shock, rows in records.items():
        result[shock] = {
            "replication_count": len(rows),
            "registered_kernel_checksums": rows[0][
                "registered_kernel_checksums"
            ],
            "gas_owner": rows[0]["gas_owner"],
            "empirical_source_block_sha256": rows[0][
                "empirical_source_block_sha256"
            ],
            "joint_treatment_path_valid": all(
                row["joint_treatment_path_valid"] for row in rows
            ),
            "stable_ordinary_multiplier_valid": all(
                row["stable_ordinary_multiplier_valid"] for row in rows
            ),
            "path_checksum_count": len(
                {row["path_checksum"] for row in rows}
            ),
            "full_price_checksum_count": len(
                {
                    _payload_sha256(row["full_price_checksums"])
                    for row in rows
                }
            ),
            "gas_environment_checksum_count": len(
                {row["gas_environment_checksum"] for row in rows}
            ),
            "diagnostics": {
                field: _distribution(row[field] for row in rows)
                for field in scalar_fields
            },
            "gas_stress_summary": {
                field: _distribution(
                    row["gas_stress_summary"][field] for row in rows
                )
                for field in (
                    "mean_gwei",
                    "median_gwei",
                    "p95_gwei",
                    "maximum_gwei",
                )
            },
        }
    return result


def _require_exact_columns(
    frame: pd.DataFrame,
    expected: Sequence[str],
    *,
    label: str,
) -> None:
    if tuple(frame.columns) != tuple(expected):
        raise ValueError(
            f"Experiment B {label} columns differ: "
            f"{tuple(frame.columns)}."
        )


def _finite_numeric_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    *,
    allow_null: bool = False,
) -> bool:
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        if not allow_null and values.isna().any():
            return False
        observed = values.dropna().to_numpy(dtype=float)
        if not np.isfinite(observed).all():
            return False
    return True


def _validate_summary_and_contrast_frames(
    registry: pd.DataFrame,
    cells: pd.DataFrame,
    collateral: pd.DataFrame,
    contrasts: pd.DataFrame,
) -> dict[str, int]:
    _require_exact_columns(registry, REGISTRY_COLUMNS, label="registry")
    _require_exact_columns(cells, CELL_SUMMARY_COLUMNS, label="cell-summary")
    _require_exact_columns(
        collateral, COLLATERAL_SUMMARY_COLUMNS, label="collateral-summary"
    )
    _require_exact_columns(
        contrasts, CONTRAST_COLUMNS, label="contrast"
    )
    expected_registry = _registry_frame()
    if not registry.equals(expected_registry):
        raise ValueError("Experiment B compact registry differs.")

    summary_metrics = (*SYSTEM_METRICS, *SYSTEM_DIAGNOSTICS)
    expected_cell_keys = [
        (identifier, metric)
        for identifier in CELL_ORDER
        for metric in summary_metrics
    ]
    actual_cell_keys = list(
        cells.loc[:, ["cell_identifier", "metric"]].itertuples(
            index=False, name=None
        )
    )
    if actual_cell_keys != expected_cell_keys:
        raise ValueError("Experiment B cell-summary keys or order differ.")
    if (
        not cells["valid_replication_count"].eq(REPLICATIONS).all()
        or not cells["numerical_failure_count"].eq(0).all()
        or not cells["operationality"].isin(
            {*OPERATIONALITY_STATUSES, "diagnostic"}
        ).all()
        or not _finite_numeric_columns(
            cells,
            (
                "valid_replication_count",
                *DISTRIBUTION_FIELDS,
                "censoring_count",
                "numerical_failure_count",
            ),
        )
    ):
        raise ValueError("Experiment B cell-summary values are invalid.")

    expected_collateral_keys = [
        (identifier, family, metric)
        for identifier in CELL_ORDER
        for family in FAMILY_ORDER
        for metric in COLLATERAL_METRICS
    ]
    actual_collateral_keys = list(
        collateral.loc[
            :, ["cell_identifier", "family", "metric"]
        ].itertuples(index=False, name=None)
    )
    if actual_collateral_keys != expected_collateral_keys:
        raise ValueError(
            "Experiment B collateral-summary keys or order differ."
        )
    count_columns = (
        "applicable_replication_count",
        "not_applicable_replication_count",
        "invalid_replication_count",
    )
    if (
        not collateral["invalid_replication_count"].eq(0).all()
        or not (
            collateral["applicable_replication_count"]
            + collateral["not_applicable_replication_count"]
        ).eq(REPLICATIONS).all()
        or not _finite_numeric_columns(
            collateral, count_columns
        )
        or not _finite_numeric_columns(
            collateral, DISTRIBUTION_FIELDS, allow_null=True
        )
    ):
        raise ValueError(
            "Experiment B collateral-summary values are invalid."
        )
    applicable = collateral["applicable_replication_count"].gt(0)
    if (
        collateral.loc[applicable, list(DISTRIBUTION_FIELDS)].isna().any().any()
        or collateral.loc[
            ~applicable, list(DISTRIBUTION_FIELDS)
        ].notna().any().any()
    ):
        raise ValueError(
            "Experiment B collateral applicability is inconsistent."
        )

    expected_raw = {
        (shock, left, right, metric)
        for shock in SHOCK_ORDER
        for left, right in RAW_PORTFOLIO_CONTRASTS
        for metric in SYSTEM_METRICS
    }
    expected_advantage = {
        (shock, portfolio, metric)
        for shock in SHOCK_ORDER
        for portfolio in DIVERSIFIED_PORTFOLIOS
        for metric in SYSTEM_METRICS
    }
    expected_interactions = {
        (portfolio, metric)
        for portfolio in DIVERSIFIED_PORTFOLIOS
        for metric in SYSTEM_METRICS
    }
    raw = contrasts.loc[
        contrasts["contrast_type"].eq("raw_portfolio_contrast")
    ]
    advantage = contrasts.loc[
        contrasts["contrast_type"].eq(
            "direction_normalised_advantage"
        )
    ]
    interactions = contrasts.loc[
        contrasts["contrast_type"].eq(
            "correlation_deterioration_interaction"
        )
    ]
    raw_keys = set(
        raw.loc[
            :, ["shock", "left_portfolio", "right_portfolio", "metric"]
        ].itertuples(index=False, name=None)
    )
    advantage_keys = set(
        advantage.loc[:, ["shock", "portfolio", "metric"]].itertuples(
            index=False, name=None
        )
    )
    interaction_keys = set(
        interactions.loc[:, ["portfolio", "metric"]].itertuples(
            index=False, name=None
        )
    )
    if (
        len(raw) != 168
        or len(advantage) != 84
        or len(interactions) != 42
        or raw_keys != expected_raw
        or advantage_keys != expected_advantage
        or interaction_keys != expected_interactions
        or interactions["shock"].ne(
            "empirical_minus_high_correlation"
        ).any()
        or not contrasts["pair_count"].eq(REPLICATIONS).all()
        or not contrasts["operationality"].isin(
            OPERATIONALITY_STATUSES
        ).all()
        or not contrasts["direction_multiplier"].isin({-1, 1}).all()
        or not _finite_numeric_columns(
            contrasts,
            ("pair_count", *DISTRIBUTION_FIELDS),
        )
    ):
        raise ValueError(
            "Experiment B contrast keys, counts or values are invalid."
        )
    if (
        interactions["reversal_flag"].isna().any()
        or contrasts.loc[
            ~contrasts.index.isin(interactions.index), "reversal_flag"
        ].notna().any()
    ):
        raise ValueError("Experiment B reversal flags are inconsistent.")
    for frame in (raw, advantage):
        binary = frame["metric"].isin(BINARY_METRICS)
        if (
            frame.loc[
                binary, "paired_probability_difference"
            ].isna().any()
            or frame.loc[
                binary,
                [
                    "discordant_left_one_right_zero",
                    "discordant_left_zero_right_one",
                ],
            ].isna().any().any()
            or frame.loc[
                ~binary, "paired_probability_difference"
            ].notna().any()
        ):
            raise ValueError(
                "Experiment B paired binary uncertainty is incomplete."
            )
    return {
        "registry_rows": len(registry),
        "cell_summary_rows": len(cells),
        "collateral_summary_rows": len(collateral),
        "raw_contrast_rows": len(raw),
        "advantage_rows": len(advantage),
        "interaction_rows": len(interactions),
        "contrast_rows": len(contrasts),
    }


def _validate_decision_payload(decision: Mapping[str, Any]) -> None:
    allowed = _decision_rule_payload()
    persistence = decision["high_correlation_persistence"]
    if (
        decision["B1"] not in allowed["B1"]["classifications"]
        or decision["B2"] not in allowed["B2"]["classifications"]
        or decision["B3"] not in allowed["B3"]["classifications"]
        or decision["overall_h3_classification"]
        not in allowed["overall_h3_branch_map"]
        or decision["peg_solvency_relationship"]
        not in allowed["peg_solvency_classifications"]
        or set(persistence) != set(DIVERSIFIED_PORTFOLIOS)
        or any(
            row["classification"]
            not in {
                "persists",
                "weakens_but_remains",
                "neutralised",
                "reversed",
                "mixed",
                "not_operational",
            }
            for row in persistence.values()
        )
        or set(decision["metric_operationality"]) != set(SYSTEM_METRICS)
        or any(
            status not in OPERATIONALITY_STATUSES
            for status in decision["metric_operationality"].values()
        )
        or decision["experiment_valid"] is not True
        or decision["validity_audit"]["experiment_valid"] is not True
        or decision["identification_limitation"]
        != IDENTIFICATION_LIMITATION
        or decision["portfolio_ranked"] is not False
        or decision["portfolio_selected"] is not None
        or decision["shock_ranked"] is not False
        or decision["shock_selected"] is not None
        or decision["stable_collateral_component_complete"] is not False
        or decision["next_authorised_pass"]
        != "C_stable_collateral_tradeoff"
        or decision["runtime_adopted"] is not False
    ):
        raise ValueError("Experiment B decision payload is invalid.")


def build_evidence_payloads(
    programme_identity: str,
    benchmark: Mapping[str, Any],
) -> dict[str, bytes]:
    _assert_preregistration_matches(programme_identity)
    cells, collateral = load_results(programme_identity)
    cell_evidence = cell_summary(cells)
    collateral_evidence = collateral_summary(collateral)
    contrasts = paired_contrasts(cells)
    checkpoint = audit_checkpoints(programme_identity)
    if not checkpoint["passed"]:
        raise ValueError("Experiment B checkpoint audit failed.")
    decision_core = classify_results(
        cells,
        collateral,
        contrasts,
        registry_valid=True,
        checkpoint_valid=bool(checkpoint["passed"]),
        final_validation_data_used=False,
    )
    decision = {
        "schema_version": 1,
        "experiment_identity": experiment_identity(programme_identity),
        **decision_core,
        "identification_limitation": IDENTIFICATION_LIMITATION,
        "portfolio_ranked": False,
        "portfolio_selected": None,
        "shock_ranked": False,
        "shock_selected": None,
        "stable_collateral_component_complete": False,
        "next_authorised_pass": (
            "C_stable_collateral_tradeoff"
            if decision_core["experiment_valid"]
            else None
        ),
        "runtime_adopted": False,
    }
    _validate_summary_and_contrast_frames(
        _registry_frame(),
        cell_evidence,
        collateral_evidence,
        contrasts,
    )
    _validate_decision_payload(decision)
    specification = json.loads(
        (EVIDENCE_DIR / COMPACT_FILENAMES[0]).read_text(encoding="utf-8")
    )
    a_regression = experiment_a_regression_audit(
        specification["experiment_a_checkpoint_snapshot"]
    )
    output_dir = _output_dir(programme_identity)
    result_checksums = {
        "cell_rows_csv": hashlib.sha256(_csv_bytes(cells)).hexdigest(),
        "collateral_rows_csv": hashlib.sha256(
            _csv_bytes(collateral)
        ).hexdigest(),
    }
    reproducibility = {
        "schema_version": 1,
        "experiment_identity": experiment_identity(programme_identity),
        "programme_identity": programme_identity,
        "scientific_code_identity": (
            REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
        ),
        "simulation_core_identity": simulation_core_identity(),
        "registered_simulation_core_identity": (
            REGISTERED_SIMULATION_CORE_IDENTITY
        ),
        "post_execution_operational_code_identity": (
            scientific_code_identity()
        ),
        "post_execution_maintenance": {
            "classification": EVIDENCE_ORDERING_REPAIR_CLASSIFICATION,
            "trigger": (
                "compact collateral-summary rows arrived in lexical family "
                "order after all checkpoints completed"
            ),
            "simulation_calculations_changed": False,
            "checkpoint_content_changed": False,
            "summary_values_changed": False,
            "decision_rules_changed": False,
            "registered_identity_preserved": True,
            "deterministic_replay_preserved": True,
            "repair": (
                "order compact collateral-summary rows by the frozen cell, "
                "family and metric registries before schema validation; "
                "bind future replay to the unchanged simulation core rather "
                "than evidence-only source bytes"
            ),
        },
        "parent_commit": EXPERIMENT_B_PARENT_COMMIT,
        "seed_registry_sha256": seed_registry_checksum(),
        "shock_path_identities": _registered_path_identities(),
        "identification_limitation": IDENTIFICATION_LIMITATION,
        "path_diagnostics": _path_audit_summary(programme_identity),
        "crn_audit": {
            "replication_count": REPLICATIONS,
            "paired_stream_failures": int(
                cells.groupby("replication")["paired_stream_checksum"]
                .nunique()
                .ne(1)
                .sum()
            ),
            "gas_unit_draw_failures": int(
                cells.groupby("replication")["gas_unit_draw_checksum"]
                .nunique()
                .ne(1)
                .sum()
            ),
            "state_reuse_failures": int(
                cells.groupby(["replication", "portfolio"])[
                    "state_checksum"
                ]
                .nunique()
                .ne(1)
                .sum()
            ),
            "treatment_gas_component_failures": int(
                cells.groupby(["replication", "shock"])[
                    "gas_component_checksum"
                ]
                .first()
                .groupby("replication")
                .nunique()
                .ne(len(SHOCK_ORDER))
                .sum()
            ),
            "treatment_gas_environment_failures": int(
                cells.groupby(["replication", "shock"])[
                    "gas_environment_checksum"
                ]
                .first()
                .groupby("replication")
                .nunique()
                .ne(len(SHOCK_ORDER))
                .sum()
            ),
            "treatment_gas_owner_failures": int(
                (
                    cells.groupby(["replication", "shock"])[
                        "gas_owner"
                    ]
                    .first()
                    .reset_index()
                    .assign(
                        expected=lambda frame: frame["shock"].map(
                            {
                                "joint_crypto_empirical_stress": (
                                    "selected_empirical_24h_block"
                                ),
                                "joint_crypto_high_correlation": (
                                    "ordinary_common_market_blocks"
                                ),
                            }
                        )
                    )
                    .eval("gas_owner != expected")
                    .sum()
                )
            ),
            "nested_family_draws": True,
            "treatment_owned_gas_difference": True,
        },
        "checkpoint_audit": checkpoint,
        "checkpoint_content_snapshot": checkpoint_content_snapshot(
            programme_identity
        ),
        "simulation_count": len(cells),
        "result_checksums": result_checksums,
        "detailed_output_path": _relative(output_dir),
        "detailed_output_size_bytes": sum(
            path.stat().st_size
            for path in output_dir.rglob("*")
            if path.is_file()
        ),
        "experiment_a_regression": a_regression,
        "experiment_a_simulations_executed": 0,
        "experiments_c_to_e_executed": False,
        "experiments_c_to_e_simulations": 0,
        "final_validation_data_used": False,
        "held_out_data_used": False,
        "usdc_svb_used": False,
        "portfolio_ranked": False,
        "runtime_adopted": False,
    }
    payloads = {
        COMPACT_FILENAMES[0]: (
            EVIDENCE_DIR / COMPACT_FILENAMES[0]
        ).read_bytes(),
        COMPACT_FILENAMES[1]: (
            EVIDENCE_DIR / COMPACT_FILENAMES[1]
        ).read_bytes(),
        COMPACT_FILENAMES[2]: _csv_bytes(cell_evidence),
        COMPACT_FILENAMES[3]: _csv_bytes(collateral_evidence),
        COMPACT_FILENAMES[4]: _csv_bytes(contrasts),
        COMPACT_FILENAMES[5]: _pretty_json(decision),
        COMPACT_FILENAMES[6]: _pretty_json(reproducibility),
        COMPACT_FILENAMES[7]: _pretty_json(dict(benchmark)),
    }
    if tuple(payloads) != COMPACT_FILENAMES:
        raise ValueError("Experiment B evidence filenames differ.")
    return payloads


def _manifest_records(
    paths: Iterable[Path],
    classification: str,
) -> list[dict[str, Any]]:
    return [
        {
            "classification": classification,
            "path": _relative(path),
            "runtime_adopted": False,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in paths
    ]


def update_experiment_manifest(
    owned_records: Sequence[Mapping[str, Any]],
) -> None:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    owned_paths = {str(row["path"]) for row in owned_records}
    expected_owned_paths = {
        _relative(EVIDENCE_DIR / name) for name in COMPACT_FILENAMES
    }
    if owned_paths != expected_owned_paths or len(owned_records) != len(
        COMPACT_FILENAMES
    ):
        raise ValueError("Experiment B manifest ownership differs.")
    preserved = [
        row
        for row in payload["artefacts"]
        if str(row["path"]) not in owned_paths
    ]
    preserved = sorted(preserved, key=lambda row: str(row["path"]))
    if _payload_sha256(preserved) != BASE_MANIFEST_ARTIFACTS_SHA256:
        raise ValueError("Experiment B preserved manifest rows changed.")
    combined = [*preserved, *map(dict, owned_records)]
    paths = [str(row["path"]) for row in combined]
    if len(paths) != len(set(paths)):
        raise ValueError("Experiment manifest contains duplicate paths.")
    if len(preserved) != 35:
        raise ValueError("Experiment B expected 35 preserved manifest rows.")
    payload["artefacts"] = sorted(combined, key=lambda row: str(row["path"]))
    payload["artefact_count"] = len(payload["artefacts"])
    if payload["artefact_count"] != 43:
        raise ValueError("Experiment manifest must contain 43 artefacts.")
    _atomic_json(MANIFEST_PATH, payload)


def _validate_benchmark_payload(
    benchmark: Mapping[str, Any],
) -> None:
    required = {
        "schema_version",
        "measurement_timestamp_utc",
        "execution_command",
        "worker_count",
        "smoke_wall_time_seconds",
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
        "network_calls",
        "calibration_runs",
        "experiment_a_simulations",
        "experiments_c_to_e_simulations",
        "held_out_validation_runs",
    }
    if set(benchmark) != required:
        raise ValueError(
            "Experiment B benchmark fields differ: "
            f"{sorted(set(benchmark) ^ required)}."
        )
    workers = int(benchmark["worker_count"])
    expected_command = (
        "PYTHONPATH=src python "
        "workflows/experiments/final/correlated_stress.py "
        f"all --workers {workers}"
    )
    completed = int(benchmark["completed_replications"])
    reused = int(benchmark["reused_replications"])
    if (
        benchmark["schema_version"] != 1
        or workers < 1
        or str(benchmark["execution_command"]) != expected_command
        or completed + reused != REPLICATIONS
        or int(benchmark["resumed_replications"]) != reused
        or int(benchmark["completed_simulations"])
        != REPLICATIONS * len(CELL_ORDER)
        or int(benchmark["checkpoint_count"]) != REPLICATIONS
        or any(
            int(benchmark[field]) != 0
            for field in (
                "failed_replications",
                "rerun_replications",
                "network_calls",
                "calibration_runs",
                "experiment_a_simulations",
                "experiments_c_to_e_simulations",
                "held_out_validation_runs",
            )
        )
        or float(benchmark["smoke_wall_time_seconds"]) < 0.0
        or float(benchmark["full_wall_time_seconds"]) < 0.0
        or float(benchmark["throughput_simulations_per_second"]) < 0.0
        or int(benchmark["output_size_bytes"]) > MAXIMUM_OUTPUT_BYTES
        or int(benchmark["free_storage_bytes"]) < MINIMUM_FREE_BYTES
        or str(REPOSITORY_ROOT) in json.dumps(benchmark, sort_keys=True)
    ):
        raise ValueError("Experiment B benchmark crosses a frozen boundary.")
    timestamp = pd.Timestamp(benchmark["measurement_timestamp_utc"])
    if timestamp.tzinfo is None:
        raise ValueError("Experiment B benchmark timestamp is not UTC-aware.")


def _is_reproducibility_maintenance_only(
    previous: bytes,
    replacement: bytes,
) -> bool:
    """Allow only replay/evidence maintenance metadata to be refreshed."""
    try:
        old = json.loads(previous)
        new = json.loads(replacement)
    except (TypeError, json.JSONDecodeError):
        return False
    mutable_fields = {
        "post_execution_operational_code_identity",
        "post_execution_maintenance",
        "simulation_core_identity",
        "registered_simulation_core_identity",
    }
    old_scientific = {
        key: value for key, value in old.items() if key not in mutable_fields
    }
    new_scientific = {
        key: value for key, value in new.items() if key not in mutable_fields
    }
    maintenance = new.get("post_execution_maintenance", {})
    return bool(
        old_scientific == new_scientific
        and new.get("simulation_core_identity")
        == REGISTERED_SIMULATION_CORE_IDENTITY
        and new.get("registered_simulation_core_identity")
        == REGISTERED_SIMULATION_CORE_IDENTITY
        and maintenance.get("classification")
        == EVIDENCE_ORDERING_REPAIR_CLASSIFICATION
        and maintenance.get("simulation_calculations_changed") is False
        and maintenance.get("checkpoint_content_changed") is False
        and maintenance.get("summary_values_changed") is False
        and maintenance.get("decision_rules_changed") is False
        and maintenance.get("registered_identity_preserved") is True
        and maintenance.get("deterministic_replay_preserved") is True
    )


def write_evidence(
    programme_identity: str,
    benchmark: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconstruct twice, then promote exactly eight compact artefacts."""
    _validate_benchmark_payload(benchmark)
    checkpoint_before = checkpoint_content_snapshot(programme_identity)
    if checkpoint_before["checkpoint_count"] != REPLICATIONS:
        raise ValueError("Experiment B checkpoint snapshot is incomplete.")
    first = build_evidence_payloads(programme_identity, benchmark)
    second = build_evidence_payloads(programme_identity, benchmark)
    checkpoint_after_reconstruction = checkpoint_content_snapshot(
        programme_identity
    )
    if checkpoint_after_reconstruction != checkpoint_before:
        raise ValueError(
            "Experiment B evidence reconstruction changed checkpoints."
        )
    for name in DETERMINISTIC_FILENAMES:
        if first[name] != second[name]:
            raise ValueError(f"Non-deterministic Experiment B evidence: {name}.")
    isolated_checksums: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(
        prefix="experiment-b-evidence-first-"
    ) as first_name, tempfile.TemporaryDirectory(
        prefix="experiment-b-evidence-second-"
    ) as second_name:
        directories = (Path(first_name), Path(second_name))
        for directory, payloads in zip(
            directories, (first, second), strict=True
        ):
            for name, payload in payloads.items():
                _atomic_bytes(directory / name, payload)
            if {
                path.name for path in directory.iterdir() if path.is_file()
            } != set(COMPACT_FILENAMES):
                raise ValueError(
                    "Isolated Experiment B evidence is incomplete."
                )
        for name in DETERMINISTIC_FILENAMES:
            left = (directories[0] / name).read_bytes()
            right = (directories[1] / name).read_bytes()
            if left != right:
                raise ValueError(
                    f"Isolated Experiment B evidence differs: {name}."
                )
            isolated_checksums.append(
                {
                    "filename": name,
                    "sha256": hashlib.sha256(left).hexdigest(),
                }
            )
    for name, payload in first.items():
        path = EVIDENCE_DIR / name
        if path.is_file():
            if path.read_bytes() != payload:
                if not (
                    name == "correlated_stress_reproducibility.json"
                    and _is_reproducibility_maintenance_only(
                        path.read_bytes(), payload
                    )
                ):
                    raise ValueError(
                        f"Existing Experiment B evidence differs: {name}."
                    )
                _atomic_bytes(path, payload)
            continue
        _atomic_bytes(path, payload)
    if checkpoint_content_snapshot(programme_identity) != checkpoint_before:
        raise ValueError("Experiment B evidence promotion changed checkpoints.")
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    update_experiment_manifest(
        _manifest_records(
            paths,
            "pre_registered_final_correlated_stress_experiment",
        )
    )
    return {
        "experiment_identity": experiment_identity(programme_identity),
        "artefact_count": len(paths),
        "artefact_checksums": {
            path.name: sha256_file(path) for path in paths
        },
        "deterministic_reconstruction": True,
        "isolated_comparison_directories": 2,
        "isolated_comparison_checksums": isolated_checksums,
        "checkpoint_content_snapshot": checkpoint_before,
        "pre_execution_artefacts_rewritten": False,
    }


def validate_evidence(programme_identity: str) -> dict[str, Any]:
    _assert_preregistration_matches(programme_identity)
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f"Missing Experiment B evidence: {missing}.")
    specification = json.loads(paths[0].read_text(encoding="utf-8"))
    registry = pd.read_csv(paths[1])
    cells = pd.read_csv(paths[2])
    collateral = pd.read_csv(paths[3])
    contrasts = pd.read_csv(paths[4])
    decision = json.loads(paths[5].read_text(encoding="utf-8"))
    reproducibility = json.loads(paths[6].read_text(encoding="utf-8"))
    benchmark = json.loads(paths[7].read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    dimensions = _validate_summary_and_contrast_frames(
        registry, cells, collateral, contrasts
    )
    _validate_decision_payload(decision)

    _validate_benchmark_payload(benchmark)
    reconstructed = build_evidence_payloads(
        programme_identity, benchmark
    )
    if any(
        path.read_bytes() != reconstructed[path.name] for path in paths
    ):
        raise ValueError(
            "Experiment B persisted evidence differs from reconstruction."
        )

    expected_identity = experiment_identity(programme_identity)
    path_diagnostics = reproducibility["path_diagnostics"]
    checkpoint = reproducibility["checkpoint_audit"]
    crn = reproducibility["crn_audit"]
    if (
        reproducibility["programme_identity"] != programme_identity
        or reproducibility["scientific_code_identity"]
        != REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
        or reproducibility["simulation_core_identity"]
        != simulation_core_identity()
        or reproducibility["registered_simulation_core_identity"]
        != REGISTERED_SIMULATION_CORE_IDENTITY
        or reproducibility["simulation_core_identity"]
        != reproducibility["registered_simulation_core_identity"]
        or reproducibility["post_execution_operational_code_identity"]
        != scientific_code_identity()
        or reproducibility["post_execution_maintenance"]["classification"]
        != EVIDENCE_ORDERING_REPAIR_CLASSIFICATION
        or reproducibility["post_execution_maintenance"][
            "simulation_calculations_changed"
        ]
        is not False
        or reproducibility["post_execution_maintenance"][
            "checkpoint_content_changed"
        ]
        is not False
        or reproducibility["post_execution_maintenance"][
            "summary_values_changed"
        ]
        is not False
        or reproducibility["post_execution_maintenance"][
            "decision_rules_changed"
        ]
        is not False
        or reproducibility["post_execution_maintenance"][
            "registered_identity_preserved"
        ]
        is not True
        or reproducibility["post_execution_maintenance"][
            "deterministic_replay_preserved"
        ]
        is not True
        or reproducibility["parent_commit"] != EXPERIMENT_B_PARENT_COMMIT
        or reproducibility["seed_registry_sha256"]
        != seed_registry_checksum()
        or reproducibility["shock_path_identities"]
        != _registered_path_identities()
        or reproducibility["identification_limitation"]
        != IDENTIFICATION_LIMITATION
        or set(path_diagnostics) != set(SHOCK_ORDER)
        or any(
            path_diagnostics[shock]["replication_count"] != REPLICATIONS
            or path_diagnostics[shock][
                "joint_treatment_path_valid"
            ] is not True
            or path_diagnostics[shock][
                "stable_ordinary_multiplier_valid"
            ] is not True
            for shock in SHOCK_ORDER
        )
        or any(
            int(crn[field]) != 0
            for field in (
                "paired_stream_failures",
                "gas_unit_draw_failures",
                "state_reuse_failures",
                "treatment_gas_component_failures",
                "treatment_gas_environment_failures",
                "treatment_gas_owner_failures",
            )
        )
        or crn["nested_family_draws"] is not True
        or crn["treatment_owned_gas_difference"] is not True
        or checkpoint["passed"] is not True
        or int(checkpoint["valid_checkpoints"]) != REPLICATIONS
        or reproducibility["checkpoint_content_snapshot"]
        != checkpoint_content_snapshot(programme_identity)
        or int(reproducibility["simulation_count"])
        != REPLICATIONS * len(CELL_ORDER)
        or reproducibility["experiment_a_regression"]["unchanged"] is not True
        or reproducibility["experiment_a_simulations_executed"] != 0
        or reproducibility["experiments_c_to_e_executed"] is not False
        or reproducibility["experiments_c_to_e_simulations"] != 0
        or reproducibility["final_validation_data_used"] is not False
        or reproducibility["held_out_data_used"] is not False
        or reproducibility["usdc_svb_used"] is not False
        or reproducibility["portfolio_ranked"] is not False
        or reproducibility["runtime_adopted"] is not False
        or int(reproducibility["detailed_output_size_bytes"])
        > MAXIMUM_OUTPUT_BYTES
        or str(REPOSITORY_ROOT)
        in json.dumps(reproducibility, sort_keys=True)
    ):
        raise ValueError("Experiment B reproducibility evidence is invalid.")

    owned_manifest = [
        row
        for row in manifest["artefacts"]
        if str(row["path"]).startswith(
            "data/provenance/experiments/final/correlated_stress/"
        )
    ]
    expected_owned_paths = {
        _relative(path): path for path in paths
    }
    observed_owned_paths = {
        str(row["path"]): row for row in owned_manifest
    }
    preserved_manifest = sorted(
        (
            row
            for row in manifest["artefacts"]
            if str(row["path"]) not in observed_owned_paths
        ),
        key=lambda row: str(row["path"]),
    )
    manifest_valid = bool(
        manifest["schema_version"] == 1
        and manifest["purpose"]
        == (
            "Content-addressed experimental evidence; no keeper capacity "
            "or confidence scenario is selected or adopted."
        )
        and manifest["artefact_count"] == 43
        and len(manifest["artefacts"]) == 43
        and len(
            {str(row["path"]) for row in manifest["artefacts"]}
        )
        == 43
        and _payload_sha256(preserved_manifest)
        == BASE_MANIFEST_ARTIFACTS_SHA256
        and set(observed_owned_paths) == set(expected_owned_paths)
        and all(
            row["classification"]
            == "pre_registered_final_correlated_stress_experiment"
            and row["runtime_adopted"] is False
            and row["sha256"] == sha256_file(expected_owned_paths[path])
            and int(row["size_bytes"])
            == expected_owned_paths[path].stat().st_size
            for path, row in observed_owned_paths.items()
        )
    )
    valid = bool(
        specification["experiment_identity"] == expected_identity
        and decision["experiment_identity"] == expected_identity
        and reproducibility["experiment_identity"] == expected_identity
        and manifest_valid
        and audit_checkpoints(programme_identity)["passed"]
    )
    if not valid:
        raise ValueError("Experiment B compact evidence validation failed.")
    return {
        "experiment_identity": experiment_identity(programme_identity),
        "artefact_count": len(paths),
        "manifest_artefact_count": manifest["artefact_count"],
        "schemas_valid": True,
        **dimensions,
        "decision": {
            key: decision[key]
            for key in (
                "B1",
                "B2",
                "B3",
                "overall_h3_classification",
                "peg_solvency_relationship",
            )
        },
        "experiment_a_unchanged": True,
        "experiments_c_to_e_unexecuted": True,
        "runtime_adopted": False,
        "passed": True,
    }
