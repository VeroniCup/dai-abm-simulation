"""Resumable deterministic execution of the pre-registered confidence SMM search.

The module is calibration-only.  It caches candidate-invariant conditional
event inputs, evaluates complete Sobol candidates in spawned worker processes,
and writes atomic ignored checkpoints.  It does not expose a production model
caller or adopt a fitted parameter vector.
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import socket
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence
import zipfile

import numpy as np
import pandas as pd

from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file
from dai_sim.inputs.liquidations import LiquidationDemandProcess
from dai_sim.model.confidence import (
    PersistentConfidenceConfig,
    PersistentConfidenceState,
    RecoveryGateInputs,
    update_persistent_confidence,
)
from dai_sim.model.liquidation import liquidate_vaults, summarise_liquidations
from dai_sim.model.market import coefficient_normalised_market_response

from .event_simulation import (
    CALIBRATION_MANIFEST,
    EXPECTED_RESIDUAL_BLOCK_SHA256,
    EXPECTED_RESIDUAL_SEQUENCE_SHA256,
    SPARSE_SCALING_EVIDENCE,
    ConditionalEventPath,
    ConditionalEventStep,
    ConditionalInitialState,
    _active_system,
    _event_metrics,
    _liquidation_demand_config,
    _payload_sha256,
    build_conditional_initial_state,
    default_event_config,
    liquidation_pressure_state,
    load_stage1_owners,
    material_active_bad_debt,
    material_bad_debt_tolerance,
    prepare_event_path,
)
from .market import (
    CONFIDENCE_EVIDENCE,
    CONFIDENCE_PANEL,
    sample_residual_blocks,
)
from .simulated_moments import (
    CORE_GROUPS,
    DEFAULT_REGISTRY_IDS,
    SIMULATED_CORE_MOMENT_ORDER,
    StructuralParameters,
    aggregate_simulated_core_moments,
    array_sha256,
    derive_seed,
    moment_objective,
    sobol_candidates,
    validate_structural_parameters,
)


EVENT_SIMULATION_SCHEMA = 1
SEARCH_EXECUTION_SCHEMA = 2
CACHE_SCHEMA = 1
CANDIDATE_SCHEMA = 2
REGISTRY_A = DEFAULT_REGISTRY_IDS[0]
SEARCH_EVENT_COUNT = 32
REPLICATION_COUNT = 32
CANDIDATE_COUNT = 256
EXPECTED_PACKAGE_COUNT = SEARCH_EVENT_COUNT * REPLICATION_COUNT
EXPECTED_SEARCH_SUBSET_SHA256 = (
    "96e63cf508a94ca31601662503c9463f9bd694078263c0ceb5fe1fe090c968f4"
)
EXPECTED_CANDIDATE_SHA256 = (
    "fc56a12f0066cd84a15f5df52254ccf4a678847168af45e7f235757b3b1adde5"
)
DEFAULT_SEARCH_ROOT = (
    REPOSITORY_ROOT
    / "outputs/diagnostics/calibration/confidence/smm_search"
)
TRACKED_SEARCH_FILES = (
    "sobol_search_specification.json",
    "sobol_search_cache_summary.json",
    "sobol_search_candidates.csv",
    "sobol_search_top16.json",
    "sobol_search_reproducibility.json",
    "sobol_search_benchmark.json",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    raise TypeError(f"Cannot serialise {type(value).__name__}.")


def canonical_json_bytes(payload: Any) -> bytes:
    """Return the canonical scientific JSON representation."""
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")


def payload_sha256(payload: Any) -> str:
    """Hash canonical JSON without relying on Python's randomised hash."""
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_bytes(path, canonical_json_bytes(payload))


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    _atomic_bytes(
        path,
        frame.to_csv(
            index=False,
            lineterminator="\n",
            float_format="%.17g",
        ).encode("utf-8"),
    )


def _array_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.lib.format.write_array(
        buffer,
        np.asarray(array),
        allow_pickle=False,
    )
    return buffer.getvalue()


def deterministic_npz_bytes(arrays: Mapping[str, np.ndarray]) -> bytes:
    """Create a byte-stable, pickle-free NPZ archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_STORED,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(arrays):
            info = zipfile.ZipInfo(f"{name}.npy", (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, _array_bytes(np.asarray(arrays[name])))
    return buffer.getvalue()


def _atomic_npz(path: Path, arrays: Mapping[str, np.ndarray]) -> None:
    _atomic_bytes(path, deterministic_npz_bytes(arrays))


def _load_npz(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as source:
        return {name: source[name] for name in source.files}


def _manifest_records() -> dict[str, dict[str, Any]]:
    manifest = json.loads(CALIBRATION_MANIFEST.read_text(encoding="utf-8"))
    return {record["path"]: record for record in manifest["artefacts"]}


def _registered_sha256(path: Path) -> str:
    relative = path.relative_to(REPOSITORY_ROOT).as_posix()
    record = _manifest_records().get(relative)
    if record is None:
        raise ValueError(f"Scientific input is not registered: {relative}.")
    observed = sha256_file(path)
    if observed != record["sha256"]:
        raise ValueError(f"Scientific input checksum differs: {relative}.")
    return observed


@dataclass(frozen=True)
class SearchIdentity:
    """Immutable scientific and implementation identity for one search."""

    search_id: str
    inputs: dict[str, str]
    event_subset_sha256: str
    candidate_sha256: str
    event_simulation_schema: int
    search_execution_schema: int
    replication_count: int
    registry_id: str
    event_count: int
    candidate_count: int


def build_search_identity(
    *,
    scientific_checksums: Mapping[str, str],
    event_subset_sha256: str,
    candidate_sha256: str,
    event_simulation_schema: int = EVENT_SIMULATION_SCHEMA,
    search_execution_schema: int = SEARCH_EXECUTION_SCHEMA,
    replication_count: int = REPLICATION_COUNT,
    registry_id: str = REGISTRY_A,
    event_count: int = SEARCH_EVENT_COUNT,
    candidate_count: int = CANDIDATE_COUNT,
) -> SearchIdentity:
    """Construct a content-addressed identity from scientific inputs only."""
    payload = {
        "scientific_checksums": dict(sorted(scientific_checksums.items())),
        "event_subset_sha256": event_subset_sha256,
        "candidate_sha256": candidate_sha256,
        "event_simulation_schema": event_simulation_schema,
        "search_execution_schema": search_execution_schema,
        "replication_count": replication_count,
        "registry_id": registry_id,
        "event_count": event_count,
        "candidate_count": candidate_count,
    }
    return SearchIdentity(
        search_id=payload_sha256(payload),
        inputs=dict(sorted(scientific_checksums.items())),
        event_subset_sha256=event_subset_sha256,
        candidate_sha256=candidate_sha256,
        event_simulation_schema=event_simulation_schema,
        search_execution_schema=search_execution_schema,
        replication_count=replication_count,
        registry_id=registry_id,
        event_count=event_count,
        candidate_count=candidate_count,
    )


def load_search_identity(
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> tuple[SearchIdentity, dict[str, Any]]:
    """Load and verify every fixed design owner."""
    evidence_dir = Path(evidence_dir).resolve()
    names = {
        "stage1_estimates": "stage1_market_estimates.json",
        "stage1_residual": "stage1_residual_summary.json",
        "empirical_moments": "empirical_moments.csv",
        "moment_weights": "moment_weights.csv",
        "parameter_bounds": "parameter_bounds.json",
        "event_catalogue": "event_catalogue.csv",
        "seed_registry": "seed_registry.json",
        "conditional_event_specification": "conditional_event_specification.json",
        "conditional_initial_state": "conditional_initial_state.json",
        "recovery_gate_specification": "recovery_gate_specification.json",
    }
    checksums = {
        key: _registered_sha256(evidence_dir / filename)
        for key, filename in names.items()
    }
    specification = json.loads(
        (evidence_dir / "simulated_moments_specification.json").read_text(
            encoding="utf-8"
        )
    )
    subset = specification["search_subset"]
    sobol = specification["sobol_design"]
    if subset["count"] != SEARCH_EVENT_COUNT:
        raise ValueError("The fixed search subset must contain exactly 32 events.")
    if subset["sha256"] != EXPECTED_SEARCH_SUBSET_SHA256:
        raise ValueError("The registered search-subset checksum differs.")
    if sobol["count"] != CANDIDATE_COUNT:
        raise ValueError("The fixed Sobol design must contain 256 candidates.")
    transformed, structural = sobol_candidates(seed=int(sobol["seed"]))
    structural_array = np.asarray(
        [
            (
                value.deterioration_adjustment,
                value.recovery_adjustment,
                value.confidence_floor,
                value.panic_response,
            )
            for value in structural
        ],
        dtype="<f8",
    )
    candidate_sha = array_sha256(structural_array)
    if (
        candidate_sha != EXPECTED_CANDIDATE_SHA256
        or candidate_sha != sobol["structural_candidate_sha256"]
    ):
        raise ValueError("The registered Sobol candidate checksum differs.")
    if len(set(subset["event_ids"])) != SEARCH_EVENT_COUNT:
        raise ValueError("The search subset contains duplicate events.")
    if any(not value.startswith("calibration__") for value in subset["event_ids"]):
        raise ValueError("A validation event entered the search subset.")
    identity = build_search_identity(
        scientific_checksums=checksums,
        event_subset_sha256=subset["sha256"],
        candidate_sha256=candidate_sha,
    )
    return identity, {
        "specification": specification,
        "event_ids": tuple(sorted(subset["event_ids"])),
        "transformed": transformed,
        "structural": tuple(structural),
    }


def search_directory(
    identity: SearchIdentity,
    root: Path = DEFAULT_SEARCH_ROOT,
) -> Path:
    return Path(root).resolve() / identity.search_id


def _package_stem(event_id: str, replication: int) -> str:
    event_digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:16]
    return f"{event_digest}_replication_{replication:02d}"


def _residual_sequence(
    *,
    path: ConditionalEventPath,
    source: Any,
    event_id: str,
    replication: int,
    registry_id: str,
) -> tuple[int, np.ndarray]:
    seed = derive_seed(
        registry_id=registry_id,
        event_id=event_id,
        replication=replication,
        stream_name="market_innovations",
    )
    generator = np.random.default_rng(seed)
    block_count = math.ceil(len(path.timestamps) / 24)
    values = sample_residual_blocks(
        source,
        block_count=block_count,
        rng=generator,
    )[: len(path.timestamps)]
    return seed, np.asarray(values, dtype="<f8")


def _liquidation_evolution(
    *,
    state: ConditionalInitialState,
    path: ConditionalEventPath,
    replication: int,
    registry_id: str,
    profile_path: Path,
) -> tuple[int, dict[str, np.ndarray]]:
    """Run the candidate-invariant liquidation mechanism for the full path."""
    from dai_sim.inputs.vaults import load_tranche_b_configuration

    bundle = load_tranche_b_configuration(profile_path)
    liquidation_config = bundle.base_bundle.liquidation_config
    seed = derive_seed(
        registry_id=registry_id,
        event_id=path.event.event_id,
        replication=replication,
        stream_name="liquidation_randomness",
    )
    demand = LiquidationDemandProcess(
        _liquidation_demand_config(profile_path, seed=seed)
    )
    vaults = state.to_vaults()
    length = len(path.timestamps)
    liquidatable = np.zeros(length, dtype="<i8")
    attempts = np.zeros(length, dtype="<i8")
    successful = np.zeros(length, dtype="<i8")
    failed = np.zeros(length, dtype="<i8")
    cleared = np.zeros(length, dtype="<f8")
    unresolved = np.zeros(length, dtype="<f8")
    active_bad_debt = np.zeros(length, dtype="<f8")
    trailing = np.zeros(length, dtype="<f8")
    pressure = np.zeros(length, dtype="<f8")
    pressure_gate = np.zeros(length, dtype="?")
    material_bad_debt_flag = np.zeros(length, dtype="?")
    cleared_history: deque[float] = deque(maxlen=24)
    config = _ACTIVE_CACHE_CONFIG
    bad_debt_tolerance = material_bad_debt_tolerance(
        state.total_debt_dai, config
    )
    for position, eth_price in enumerate(path.observed_eth_prices):
        count, _, _ = _active_system(vaults, eth_price)
        liquidatable[position] = count
        decision = demand.sample_step(
            step=position,
            liquidatable_inventory=count,
            keeper_capacity=liquidation_config.max_liquidations_per_step,
        )
        if count:
            frame = liquidate_vaults(
                vaults,
                eth_price,
                liquidation_config,
                bounded_demand=decision.bounded_demand,
                attempt_budget=decision.attempt_budget,
            )
            summary = summarise_liquidations(frame)
        else:
            summary = {
                "n_attempted": 0,
                "n_liquidated": 0,
                "n_unprofitable": 0,
                "debt_repaid": 0.0,
            }
        _, unresolved_value, bad_debt_value = _active_system(vaults, eth_price)
        cleared_value = float(summary["debt_repaid"])
        cleared_history.append(cleared_value)
        state_pressure = liquidation_pressure_state(
            unresolved_tab_dai=unresolved_value,
            hourly_cleared_tab_dai=cleared_value,
            cleared_history=tuple(cleared_history),
            tolerance=config.liquidation_pressure_tolerance,
        )
        attempts[position] = int(summary["n_attempted"])
        successful[position] = int(summary["n_liquidated"])
        failed[position] = int(summary["n_unprofitable"])
        cleared[position] = cleared_value
        unresolved[position] = unresolved_value
        active_bad_debt[position] = bad_debt_value
        trailing[position] = state_pressure.trailing_cleared_tab_dai
        pressure[position] = state_pressure.pressure
        pressure_gate[position] = state_pressure.gate_open
        material_bad_debt_flag[position] = material_active_bad_debt(
            bad_debt_value,
            tolerance=bad_debt_tolerance,
        )
    return seed, {
        "liquidatable_before": liquidatable,
        "liquidation_attempts": attempts,
        "successful_liquidations": successful,
        "failed_liquidation_attempts": failed,
        "cleared_tab_dai": cleared,
        "unresolved_tab_dai": unresolved,
        "active_bad_debt_dai": active_bad_debt,
        "trailing_cleared_tab_dai": trailing,
        "liquidation_pressure": pressure,
        "liquidation_gate_open": pressure_gate,
        "material_active_bad_debt": material_bad_debt_flag,
    }


_ACTIVE_CACHE_CONFIG: Any = None
_CACHE_BUILD_CONTEXT: dict[str, Any] | None = None


def _cache_worker_initialise(
    cache_dir_text: str,
    panel_path_text: str,
    evidence_dir_text: str,
) -> None:
    """Load immutable package-building owners once in a spawned process."""
    global _CACHE_BUILD_CONTEXT, _ACTIVE_CACHE_CONFIG
    from dai_sim.inputs.vaults import DEFAULT_TRANCHE_B_CONFIG_PATH

    _thread_cap()
    identity, design = load_search_identity(Path(evidence_dir_text))
    panel, events, stage1 = load_stage1_owners(
        Path(panel_path_text), Path(evidence_dir_text),
        require_historical_panel=True,
    )
    config = default_event_config(events)
    rows = {
        event_id: events.loc[events["event_id"].eq(event_id)].iloc[0]
        for event_id in design["event_ids"]
    }
    paths = {
        event_id: prepare_event_path(
            panel=panel,
            event_row=rows[event_id],
            config=config,
        )
        for event_id in design["event_ids"]
    }
    _ACTIVE_CACHE_CONFIG = config
    profile_path = (
        Path(cache_dir_text).parent
        / ".worker_profiles"
        / f"empirical_{os.getpid()}.yaml"
    )
    _atomic_bytes(profile_path, DEFAULT_TRANCHE_B_CONFIG_PATH.read_bytes())
    _CACHE_BUILD_CONTEXT = {
        "identity": identity,
        "cache_dir": Path(cache_dir_text),
        "rows": rows,
        "paths": paths,
        "stage1": stage1,
        "config": config,
        "profile_path": profile_path,
    }


def _cache_worker(task: tuple[str, int]) -> dict[str, Any]:
    if _CACHE_BUILD_CONTEXT is None:
        raise RuntimeError("Cache worker was not initialised.")
    event_id, replication = task
    return _build_package(
        identity=_CACHE_BUILD_CONTEXT["identity"],
        cache_dir=_CACHE_BUILD_CONTEXT["cache_dir"],
        event_row=_CACHE_BUILD_CONTEXT["rows"][event_id],
        path=_CACHE_BUILD_CONTEXT["paths"][event_id],
        replication=replication,
        stage1=_CACHE_BUILD_CONTEXT["stage1"],
        config=_CACHE_BUILD_CONTEXT["config"],
        profile_path=_CACHE_BUILD_CONTEXT["profile_path"],
    )


def _build_package_set(
    *,
    cache_dir: Path,
    panel_path: Path,
    evidence_dir: Path,
    event_ids: Sequence[str],
    workers: int,
) -> list[dict[str, Any]]:
    tasks = [
        (event_id, replication)
        for event_id in sorted(event_ids)
        for replication in range(REPLICATION_COUNT)
    ]
    profiles = cache_dir.parent / ".worker_profiles"
    try:
        if workers == 1:
            _cache_worker_initialise(
                str(cache_dir), str(panel_path), str(evidence_dir)
            )
            return [_cache_worker(task) for task in tasks]
        context = mp.get_context("spawn")
        with context.Pool(
            processes=workers,
            initializer=_cache_worker_initialise,
            initargs=(str(cache_dir), str(panel_path), str(evidence_dir)),
        ) as pool:
            return sorted(
                pool.imap_unordered(_cache_worker, tasks, chunksize=1),
                key=lambda item: (item["event_id"], item["replication"]),
            )
    finally:
        if profiles.exists():
            shutil.rmtree(profiles)


def _cache_arrays(
    *,
    state: ConditionalInitialState,
    path: ConditionalEventPath,
    residuals: np.ndarray,
    liquidation: Mapping[str, np.ndarray],
) -> dict[str, np.ndarray]:
    arrays = {
        "timestamps_ns": np.asarray(
            [value.value for value in path.timestamps], dtype="<i8"
        ),
        "eth_prices": np.asarray(path.observed_eth_prices, dtype="<f8"),
        "residual_innovations": np.asarray(residuals, dtype="<f8"),
        "debt_dai": np.asarray(state.debt_dai, dtype="<f8"),
        "collateral_ratios": np.asarray(
            state.collateral_ratios, dtype="<f8"
        ),
        "liquidation_ratios": np.asarray(
            state.liquidation_ratios, dtype="<f8"
        ),
    }
    arrays.update(
        {name: np.asarray(value) for name, value in liquidation.items()}
    )
    return arrays


def _cache_metadata(
    *,
    identity: SearchIdentity,
    state: ConditionalInitialState,
    path: ConditionalEventPath,
    event_row: pd.Series,
    market_seed: int,
    liquidation_seed: int,
    arrays_sha256: str,
    arrays_size: int,
) -> dict[str, Any]:
    eligibility = {
        name: bool(event_row[name])
        for name in sorted(event_row.index)
        if name.startswith("eligible_")
    }
    strata = {
        name: event_row[name]
        for name in (
            "calendar_year",
            "initial_peg_gap",
            "eth_recovery_24h",
            "maximum_six_hour_burden",
            "event_eth_downside",
            "recovery_completion_hours",
        )
        if name in event_row.index
    }
    return {
        "schema_version": CACHE_SCHEMA,
        "search_id": identity.search_id,
        "event_id": path.event.event_id,
        "replication": state.replication,
        "registry_id": state.registry_id,
        "partition": path.event.partition,
        "initial_state_checksum": state.state_checksum,
        "vault_seed": state.vault_seed,
        "market_seed": market_seed,
        "liquidation_seed": liquidation_seed,
        "starting_eth_price": state.starting_eth_price,
        "vault_count": state.vault_count,
        "total_debt_dai": state.total_debt_dai,
        "starting_dai_price": path.starting_dai_price,
        "onset_timestamp_utc": path.event.onset_timestamp_utc.isoformat(),
        "observed_event_duration_hours": (
            path.event.observed_event_duration_hours
        ),
        "initial_peg_gap": path.event.initial_peg_gap,
        "eth_recovery_24h": path.event.eth_recovery_24h,
        "onset_position": path.onset_position,
        "minimum_evaluation_end_position": (
            path.minimum_evaluation_end_position
        ),
        "maximum_end_position": path.maximum_end_position,
        "path_length": len(path.timestamps),
        "event_strata": strata,
        "event_moment_eligibility": eligibility,
        "source_evidence_checksums": identity.inputs,
        "residual_source_sha256": EXPECTED_RESIDUAL_SEQUENCE_SHA256,
        "residual_block_sha256": EXPECTED_RESIDUAL_BLOCK_SHA256,
        "arrays_sha256": arrays_sha256,
        "arrays_size_bytes": arrays_size,
    }


def _build_package(
    *,
    identity: SearchIdentity,
    cache_dir: Path,
    event_row: pd.Series,
    path: ConditionalEventPath,
    replication: int,
    stage1: Mapping[str, Any],
    config: Any,
    profile_path: Path,
) -> dict[str, Any]:
    global _ACTIVE_CACHE_CONFIG
    _ACTIVE_CACHE_CONFIG = config
    event_id = path.event.event_id
    state = build_conditional_initial_state(
        event_id=event_id,
        replication=replication,
        registry_id=identity.registry_id,
        initial_eth_price=path.observed_eth_prices[0],
        profile_path=profile_path,
    )
    market_seed, residuals = _residual_sequence(
        path=path,
        source=stage1["source"],
        event_id=event_id,
        replication=replication,
        registry_id=identity.registry_id,
    )
    liquidation_seed, liquidation = _liquidation_evolution(
        state=state,
        path=path,
        replication=replication,
        registry_id=identity.registry_id,
        profile_path=profile_path,
    )
    arrays = _cache_arrays(
        state=state,
        path=path,
        residuals=residuals,
        liquidation=liquidation,
    )
    npz_content = deterministic_npz_bytes(arrays)
    npz_sha = hashlib.sha256(npz_content).hexdigest()
    metadata = _cache_metadata(
        identity=identity,
        state=state,
        path=path,
        event_row=event_row,
        market_seed=market_seed,
        liquidation_seed=liquidation_seed,
        arrays_sha256=npz_sha,
        arrays_size=len(npz_content),
    )
    metadata_content = canonical_json_bytes(metadata)
    stem = _package_stem(event_id, replication)
    npz_path = cache_dir / f"{stem}.npz"
    metadata_path = cache_dir / f"{stem}.json"
    _atomic_bytes(npz_path, npz_content)
    _atomic_bytes(metadata_path, metadata_content)
    return {
        "event_id": event_id,
        "replication": replication,
        "registry_id": identity.registry_id,
        "metadata_filename": metadata_path.name,
        "arrays_filename": npz_path.name,
        "metadata_size_bytes": len(metadata_content),
        "arrays_size_bytes": len(npz_content),
        "metadata_sha256": hashlib.sha256(metadata_content).hexdigest(),
        "arrays_sha256": npz_sha,
        "state_checksum": state.state_checksum,
        "residual_checksum": hashlib.sha256(
            np.asarray(residuals, dtype="<f8").tobytes()
        ).hexdigest(),
        "schema_version": CACHE_SCHEMA,
    }


def _cache_root(entries: Sequence[Mapping[str, Any]]) -> str:
    scientific = [
        {
            key: entry[key]
            for key in (
                "event_id",
                "replication",
                "registry_id",
                "metadata_filename",
                "arrays_filename",
                "metadata_size_bytes",
                "arrays_size_bytes",
                "metadata_sha256",
                "arrays_sha256",
                "state_checksum",
                "residual_checksum",
                "schema_version",
            )
        }
        for entry in sorted(
            entries, key=lambda item: (item["event_id"], item["replication"])
        )
    ]
    return payload_sha256(scientific)


def validate_search_cache(
    run_dir: Path,
    *,
    expected_identity: SearchIdentity | None = None,
) -> dict[str, Any]:
    """Validate a complete immutable event-replication cache."""
    run_dir = Path(run_dir)
    manifest_path = run_dir / "cache_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Search cache manifest is missing.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if expected_identity and manifest["search_id"] != expected_identity.search_id:
        raise ValueError("Search cache belongs to another search ID.")
    entries = manifest["packages"]
    if len(entries) != EXPECTED_PACKAGE_COUNT:
        raise ValueError("Search cache must contain exactly 1,024 packages.")
    identities = [(item["event_id"], item["replication"]) for item in entries]
    if len(set(identities)) != len(identities):
        raise ValueError("Search cache contains duplicate package identities.")
    cache_dir = run_dir / "cache"
    invalid = []
    for entry in entries:
        if entry["registry_id"] != REGISTRY_A:
            invalid.append(f"{entry['event_id']}:registry")
            continue
        if not entry["event_id"].startswith("calibration__"):
            invalid.append(f"{entry['event_id']}:partition")
            continue
        metadata_path = cache_dir / entry["metadata_filename"]
        arrays_path = cache_dir / entry["arrays_filename"]
        if (
            not metadata_path.is_file()
            or not arrays_path.is_file()
            or sha256_file(metadata_path) != entry["metadata_sha256"]
            or sha256_file(arrays_path) != entry["arrays_sha256"]
        ):
            invalid.append(f"{entry['event_id']}:{entry['replication']}")
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            metadata["schema_version"] != CACHE_SCHEMA
            or metadata["search_id"] != manifest["search_id"]
            or metadata["path_length"] <= 0
            or metadata["partition"] != "calibration"
        ):
            invalid.append(f"{entry['event_id']}:{entry['replication']}:metadata")
            continue
        arrays = _load_npz(arrays_path)
        length = metadata["path_length"]
        if any(
            len(arrays[name]) != length
            for name in (
                "timestamps_ns",
                "eth_prices",
                "residual_innovations",
                "unresolved_tab_dai",
                "active_bad_debt_dai",
            )
        ):
            invalid.append(f"{entry['event_id']}:{entry['replication']}:path")
        if (
            len(arrays["debt_dai"]) != metadata["vault_count"]
            or np.any(arrays["debt_dai"] <= 0.0)
            or np.any(arrays["collateral_ratios"] <= arrays["liquidation_ratios"])
            or not np.isfinite(arrays["eth_prices"]).all()
            or np.any(arrays["eth_prices"] <= 0.0)
            or any(
                np.any(arrays[name] < 0)
                for name in (
                    "liquidatable_before",
                    "liquidation_attempts",
                    "successful_liquidations",
                    "failed_liquidation_attempts",
                    "cleared_tab_dai",
                    "unresolved_tab_dai",
                    "active_bad_debt_dai",
                )
            )
        ):
            invalid.append(f"{entry['event_id']}:{entry['replication']}:state")
    if invalid:
        raise ValueError(f"Invalid search-cache packages: {invalid[:5]}.")
    root = _cache_root(entries)
    if root != manifest["cache_root_sha256"]:
        raise ValueError("Search cache root checksum differs.")
    event_ids = {item["event_id"] for item in entries}
    return {
        "status": "passed",
        "package_count": len(entries),
        "event_count": len(event_ids),
        "replication_count": len({item["replication"] for item in entries}),
        "missing_packages": 0,
        "duplicate_identities": 0,
        "invalid_checksums": 0,
        "validation_events": 0,
        "registry_b_packages": 0,
        "structurally_invalid_vault_states": 0,
        "incomplete_eth_paths": 0,
        "incomplete_residual_sequences": 0,
        "cache_root_sha256": root,
        "aggregate_bytes": int(
            sum(
                item["metadata_size_bytes"] + item["arrays_size_bytes"]
                for item in entries
            )
        ),
    }


def prepare_search_cache(
    *,
    panel_path: Path = CONFIDENCE_PANEL,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    search_root: Path = DEFAULT_SEARCH_ROOT,
    deterministic_rebuild_check: bool = True,
    workers: int | None = None,
) -> dict[str, Any]:
    """Build and byte-reproduce all 1,024 candidate-invariant packages."""
    identity, design = load_search_identity(evidence_dir)
    run_dir = search_directory(identity, search_root)
    cache_dir = run_dir / "cache"
    started = time.perf_counter()
    panel_path = Path(panel_path).resolve()
    evidence_dir = Path(evidence_dir).resolve()
    panel, events, stage1 = load_stage1_owners(
        panel_path, evidence_dir, require_historical_panel=True
    )
    config = default_event_config(events)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_workers = workers or min(6, os.cpu_count() or 1)
    if cache_workers < 1 or cache_workers > 6:
        raise ValueError("Cache workers must be between one and six.")
    entries = _build_package_set(
        cache_dir=cache_dir,
        panel_path=panel_path,
        evidence_dir=evidence_dir,
        event_ids=design["event_ids"],
        workers=cache_workers,
    )
    manifest = {
        "schema_version": CACHE_SCHEMA,
        "search_id": identity.search_id,
        "package_count": len(entries),
        "cache_root_sha256": _cache_root(entries),
        "packages": entries,
    }
    _atomic_json(run_dir / "cache_manifest.json", manifest)
    first = validate_search_cache(run_dir, expected_identity=identity)
    deterministic = {
        "performed": deterministic_rebuild_check,
        "package_identities_equal": True,
        "package_checksums_equal": True,
        "root_checksum_equal": True,
    }
    if deterministic_rebuild_check:
        temporary_root = Path(
            tempfile.mkdtemp(prefix="smm-cache-rebuild-", dir=run_dir)
        )
        try:
            second_cache = temporary_root / "cache"
            second_entries = _build_package_set(
                cache_dir=second_cache,
                panel_path=panel_path,
                evidence_dir=evidence_dir,
                event_ids=design["event_ids"],
                workers=cache_workers,
            )
            deterministic = {
                "performed": True,
                "package_identities_equal": [
                    (item["event_id"], item["replication"])
                    for item in entries
                ]
                == [
                    (item["event_id"], item["replication"])
                    for item in second_entries
                ],
                "package_checksums_equal": [
                    (item["metadata_sha256"], item["arrays_sha256"])
                    for item in entries
                ]
                == [
                    (item["metadata_sha256"], item["arrays_sha256"])
                    for item in second_entries
                ],
                "root_checksum_equal": (
                    _cache_root(entries) == _cache_root(second_entries)
                ),
            }
            if not all(deterministic.values()):
                raise ValueError("Candidate-invariant cache is not byte deterministic.")
        finally:
            shutil.rmtree(temporary_root)
    context = {
        "schema_version": SEARCH_EXECUTION_SCHEMA,
        "search_id": identity.search_id,
        "identity": asdict(identity),
        "event_ids": list(design["event_ids"]),
        "config": asdict(config),
        "stage1": {
            "below_peg_response": stage1["below_peg_response"],
            "above_peg_response": stage1["above_peg_response"],
        },
        "scaling": json.loads(
            SPARSE_SCALING_EVIDENCE.read_text(encoding="utf-8")
        ),
        "ordinary_preservation": _ordinary_preservation(evidence_dir),
        "objective": _objective_inputs(evidence_dir),
        "candidate_checksum": identity.candidate_sha256,
    }
    _atomic_json(run_dir / "run_context.json", context)
    _atomic_json(
        run_dir / "cache_validation.json",
        {
            **first,
            "deterministic_rebuild": deterministic,
            "preparation_seconds": time.perf_counter() - started,
            "preparation_workers": cache_workers,
        },
    )
    return {
        **first,
        "search_id": identity.search_id,
        "run_dir": run_dir.as_posix(),
        "deterministic_rebuild": deterministic,
        "preparation_seconds": time.perf_counter() - started,
        "preparation_workers": cache_workers,
    }


def _ordinary_preservation(evidence_dir: Path) -> dict[str, float]:
    frame = pd.read_csv(Path(evidence_dir) / "empirical_moments.csv").set_index(
        "moment"
    )
    return {
        name: float(frame.loc[name, "empirical_value"])
        for name in ("ordinary_below_mean", "ordinary_above_mean")
    }


def _objective_inputs(evidence_dir: Path) -> dict[str, dict[str, Any]]:
    moments = pd.read_csv(Path(evidence_dir) / "empirical_moments.csv").set_index(
        "moment"
    )
    weights = pd.read_csv(Path(evidence_dir) / "moment_weights.csv").set_index(
        "moment"
    )
    return {
        "empirical": {
            name: float(moments.loc[name, "empirical_value"])
            for name in SIMULATED_CORE_MOMENT_ORDER
        },
        "scales": {
            name: float(moments.loc[name, "empirical_scale"])
            for name in SIMULATED_CORE_MOMENT_ORDER
        },
        "groups": {
            name: str(moments.loc[name, "group"])
            for name in SIMULATED_CORE_MOMENT_ORDER
        },
        "within_group_weights": {
            name: float(weights.loc[name, "within_group_weight"])
            for name in SIMULATED_CORE_MOMENT_ORDER
        },
    }


@dataclass(frozen=True)
class CachedPackage:
    metadata: dict[str, Any]
    arrays: dict[str, np.ndarray]
    path: ConditionalEventPath | None = None


@dataclass(frozen=True)
class WorkerContext:
    run_dir: Path
    search_id: str
    event_ids: tuple[str, ...]
    config: Any
    stage1: dict[str, float]
    scaling: dict[str, Any]
    ordinary_preservation: dict[str, float]
    objective: dict[str, dict[str, Any]]
    candidates: tuple[StructuralParameters, ...]
    transformed: np.ndarray
    packages: dict[tuple[str, int], CachedPackage]


_WORKER_CONTEXT: WorkerContext | None = None


def _thread_cap() -> None:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[name] = "1"


def _load_worker_context(run_dir: Path) -> WorkerContext:
    context = json.loads((run_dir / "run_context.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (run_dir / "cache_manifest.json").read_text(encoding="utf-8")
    )
    _, candidates = sobol_candidates()
    transformed, _ = sobol_candidates()
    from .event_simulation import ConditionalEventSimulationConfig

    raw_packages = {}
    for entry in manifest["packages"]:
        metadata = json.loads(
            (run_dir / "cache" / entry["metadata_filename"]).read_text(
                encoding="utf-8"
            )
        )
        arrays = _load_npz(run_dir / "cache" / entry["arrays_filename"])
        for array in arrays.values():
            array.setflags(write=False)
        raw_packages[(entry["event_id"], int(entry["replication"]))] = (
            CachedPackage(metadata=metadata, arrays=arrays)
        )
    event_paths = {
        event_id: _path_from_package(raw_packages[(event_id, 0)])
        for event_id in context["event_ids"]
    }
    packages = {
        identity: CachedPackage(
            metadata=package.metadata,
            arrays=package.arrays,
            path=event_paths[identity[0]],
        )
        for identity, package in raw_packages.items()
    }
    return WorkerContext(
        run_dir=run_dir,
        search_id=context["search_id"],
        event_ids=tuple(context["event_ids"]),
        config=ConditionalEventSimulationConfig(**context["config"]),
        stage1=context["stage1"],
        scaling=context["scaling"],
        ordinary_preservation=context["ordinary_preservation"],
        objective=context["objective"],
        candidates=tuple(candidates),
        transformed=np.asarray(transformed, dtype="<f8"),
        packages=packages,
    )


def _worker_initialise(run_dir_text: str) -> None:
    global _WORKER_CONTEXT
    _thread_cap()
    _WORKER_CONTEXT = _load_worker_context(Path(run_dir_text))


def _path_from_package(package: CachedPackage) -> ConditionalEventPath:
    from .event_simulation import ConditionalEventInput

    if package.path is not None:
        return package.path
    metadata = package.metadata
    arrays = package.arrays
    timestamps = tuple(
        pd.Timestamp(int(value), tz="UTC") for value in arrays["timestamps_ns"]
    )
    event = ConditionalEventInput(
        event_id=metadata["event_id"],
        partition=metadata["partition"],
        onset_timestamp_utc=pd.Timestamp(metadata["onset_timestamp_utc"]),
        observed_event_duration_hours=int(
            metadata["observed_event_duration_hours"]
        ),
        initial_peg_gap=float(metadata["initial_peg_gap"]),
        eth_recovery_24h=float(metadata["eth_recovery_24h"]),
    )
    return ConditionalEventPath(
        event=event,
        timestamps=timestamps,
        observed_eth_prices=tuple(float(value) for value in arrays["eth_prices"]),
        starting_dai_price=float(metadata["starting_dai_price"]),
        onset_position=int(metadata["onset_position"]),
        minimum_evaluation_end_position=int(
            metadata["minimum_evaluation_end_position"]
        ),
        maximum_end_position=int(metadata["maximum_end_position"]),
        observed_dai_values_after_start_used=False,
    )


def _evaluate_cached_event(
    context: WorkerContext,
    *,
    candidate: StructuralParameters,
    event_id: str,
    replication: int,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Evaluate confidence and market dynamics over one immutable package."""
    package = context.packages[(event_id, replication)]
    metadata = package.metadata
    arrays = package.arrays
    path = _path_from_package(package)
    config = context.config
    peg_scale = float(
        context.scaling["lagged_below_peg_gap"]["positive_q95"]
    )
    eth_scale = float(
        context.scaling["lagged_24h_eth_downside"]["positive_q95"]
    )
    confidence_config = PersistentConfidenceConfig(
        deterioration_adjustment=candidate.deterioration_adjustment,
        recovery_adjustment=candidate.recovery_adjustment,
        confidence_floor=candidate.confidence_floor,
        stability_hours=config.stability_hours,
    )
    confidence_state = PersistentConfidenceState.initial()
    dai_price = path.starting_dai_price
    gate_inputs = RecoveryGateInputs(
        price_inside_recovery_band=(
            config.recovery_band_lower
            <= dai_price
            <= config.recovery_band_upper
        ),
        liquidation_pressure_acceptable=True,
        severe_bad_debt_present=False,
    )
    eth_returns: deque[float] = deque(maxlen=24)
    previous_eth = float(arrays["eth_prices"][0])
    event_steps: list[ConditionalEventStep] = []
    recovery_success = False
    all_confidence_valid = True
    all_price_valid = True
    for position in range(len(arrays["timestamps_ns"])):
        eth_price = float(arrays["eth_prices"][position])
        if position:
            eth_returns.append(math.log(eth_price) - math.log(previous_eth))
        previous_eth = eth_price
        lagged_downside = (
            max(0.0, -sum(eth_returns)) if len(eth_returns) == 24 else 0.0
        )
        scaled_peg = min(1.0, max(1.0 - dai_price, 0.0) / peg_scale)
        scaled_eth = min(1.0, lagged_downside / eth_scale)
        confidence_update = update_persistent_confidence(
            confidence_state,
            confidence_config,
            scaled_peg_gap=scaled_peg,
            scaled_collateral_stress=scaled_eth,
            recovery_inputs=gate_inputs,
            peg_weight=config.peg_stress_weight,
            collateral_weight=config.collateral_stress_weight,
        )
        confidence_state = confidence_update.state
        innovation = float(arrays["residual_innovations"][position])
        market = coefficient_normalised_market_response(
            dai_price=dai_price,
            confidence=confidence_state.confidence,
            below_peg_response=context.stage1["below_peg_response"],
            above_peg_response=context.stage1["above_peg_response"],
            panic_response=candidate.panic_response,
            residual_innovation=innovation,
            min_price=config.dai_min_price,
            max_price=config.dai_max_price,
        )
        dai_before = dai_price
        dai_price = market.clipped_next_price
        gate_inputs = RecoveryGateInputs(
            price_inside_recovery_band=(
                config.recovery_band_lower
                <= dai_price
                <= config.recovery_band_upper
            ),
            liquidation_pressure_acceptable=bool(
                arrays["liquidation_gate_open"][position]
            ),
            severe_bad_debt_present=bool(
                arrays["material_active_bad_debt"][position]
            ),
        )
        all_confidence_valid &= (
            candidate.confidence_floor - 1e-12
            <= confidence_state.confidence
            <= 1.0 + 1e-12
        )
        all_price_valid &= (
            math.isfinite(dai_price)
            and config.dai_min_price <= dai_price <= config.dai_max_price
        )
        if position >= path.onset_position:
            event_steps.append(
                ConditionalEventStep(
                    timestamp_utc=path.timestamps[position],
                    relative_hour=position - path.onset_position,
                    observed_eth_price=eth_price,
                    dai_price_before=float(dai_before),
                    dai_price_after=float(dai_price),
                    scaled_lagged_peg_gap=float(scaled_peg),
                    scaled_lagged_eth_downside=float(scaled_eth),
                    confidence=float(confidence_state.confidence),
                    confidence_branch=confidence_update.branch,
                    recovery_counter=int(
                        confidence_state.consecutive_stable_hours
                    ),
                    recovery_gate_open=bool(
                        confidence_state.recovery_gate_open
                    ),
                    liquidatable_vaults_before=int(
                        arrays["liquidatable_before"][position]
                    ),
                    liquidation_attempts=int(
                        arrays["liquidation_attempts"][position]
                    ),
                    successful_liquidations=int(
                        arrays["successful_liquidations"][position]
                    ),
                    failed_liquidation_attempts=int(
                        arrays["failed_liquidation_attempts"][position]
                    ),
                    cleared_tab_dai=float(arrays["cleared_tab_dai"][position]),
                    unresolved_tab_dai=float(
                        arrays["unresolved_tab_dai"][position]
                    ),
                    trailing_cleared_tab_dai=float(
                        arrays["trailing_cleared_tab_dai"][position]
                    ),
                    liquidation_pressure=float(
                        arrays["liquidation_pressure"][position]
                    ),
                    liquidation_gate_open=bool(
                        arrays["liquidation_gate_open"][position]
                    ),
                    active_bad_debt_dai=float(
                        arrays["active_bad_debt_dai"][position]
                    ),
                    material_active_bad_debt=bool(
                        arrays["material_active_bad_debt"][position]
                    ),
                    residual_innovation=innovation,
                    panic_component=float(market.panic_component),
                    lower_bound_binding=market.lower_bound_binding,
                    upper_bound_binding=market.upper_bound_binding,
                )
            )
        if (
            position >= path.minimum_evaluation_end_position
            and position >= path.onset_position
            and confidence_state.recovery_gate_open
            and gate_inputs.price_inside_recovery_band
            and gate_inputs.liquidation_pressure_acceptable
            and not gate_inputs.severe_bad_debt_present
        ):
            recovery_success = True
            break
    if not event_steps:
        raise ValueError("Cached event evaluation produced no event-period steps.")
    metrics = _event_metrics(
        path=path,
        event_steps=event_steps,
        replication=replication,
        config=config,
        recovery_success=recovery_success,
    )
    result_payload = {
        "event_id": event_id,
        "replication": replication,
        "registry_id": REGISTRY_A,
        "structural_parameters": asdict(candidate),
        "metrics": asdict(metrics),
        "state_checksum": metadata["initial_state_checksum"],
        "market_seed": metadata["market_seed"],
        "liquidation_seed": metadata["liquidation_seed"],
    }
    result_checksum = _payload_sha256(result_payload)
    structural = {
        "confidence_within_bounds": bool(all_confidence_valid),
        "valid_price": bool(all_price_valid),
        "future_information_used": False,
        "valid_vault_state": True,
        "valid_liquidation_state": bool(
            np.all(arrays["unresolved_tab_dai"] >= 0.0)
            and np.all(arrays["cleared_tab_dai"] >= 0.0)
        ),
        "valid_bad_debt_state": bool(
            np.all(arrays["active_bad_debt_dai"] >= 0.0)
        ),
        "duplicated_panic_term": False,
        "event_result_present": True,
    }
    return asdict(metrics), result_checksum, structural


def _candidate_checksum(
    index: int,
    candidate: StructuralParameters,
    transformed: np.ndarray,
) -> str:
    return payload_sha256(
        {
            "candidate_index": index,
            "structural": asdict(candidate),
            "transformed": [float(value) for value in transformed],
        }
    )


def structural_event_flags_pass(flags: Mapping[str, bool]) -> bool:
    """Interpret positive and explicitly negative structural diagnostics."""
    return bool(
        flags["confidence_within_bounds"]
        and flags["valid_price"]
        and not flags["future_information_used"]
        and flags["valid_vault_state"]
        and flags["valid_liquidation_state"]
        and flags["valid_bad_debt_state"]
        and not flags["duplicated_panic_term"]
        and flags["event_result_present"]
    )


def _aggregate_candidate(
    context: WorkerContext,
    *,
    candidate_index: int,
    event_ids: Sequence[str],
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    started = time.perf_counter()
    candidate = context.candidates[candidate_index]
    validate_structural_parameters(candidate)
    records = []
    event_checksums = []
    structural_flags = []
    for event_id in sorted(event_ids):
        for replication in range(REPLICATION_COUNT):
            metrics, checksum, structural = _evaluate_cached_event(
                context,
                candidate=candidate,
                event_id=event_id,
                replication=replication,
            )
            records.append(metrics)
            event_checksums.append(
                {
                    "event_id": event_id,
                    "replication": replication,
                    "result_checksum": checksum,
                }
            )
            structural_flags.append(structural)
    records.sort(key=lambda item: (item["event_id"], item["replication"]))
    aggregate = aggregate_simulated_core_moments(
        records,
        ordinary_preservation=context.ordinary_preservation,
        expected_event_ids=sorted(event_ids),
    )
    objective = moment_objective(
        simulated=aggregate.moments,
        **context.objective,
    )
    replication_moments: dict[str, list[float]] = {
        name: [] for name in SIMULATED_CORE_MOMENT_ORDER
    }
    for replication in range(REPLICATION_COUNT):
        selected = [
            record for record in records if record["replication"] == replication
        ]
        value = aggregate_simulated_core_moments(
            selected,
            ordinary_preservation=context.ordinary_preservation,
            expected_event_ids=sorted(event_ids),
        )
        for name in SIMULATED_CORE_MOMENT_ORDER:
            replication_moments[name].append(value.moments[name])
    mcse = {
        name: float(
            np.std(replication_moments[name], ddof=1)
            / math.sqrt(REPLICATION_COUNT)
        )
        for name in SIMULATED_CORE_MOMENT_ORDER
    }
    mcse_pass_by_moment = {
        name: bool(mcse[name] <= 0.10 * context.objective["scales"][name])
        for name in SIMULATED_CORE_MOMENT_ORDER
    }
    bound_shares = [
        float(record["numerical_bound_binding_share"]) for record in records
    ]
    structural_validity = bool(
        all(structural_event_flags_pass(flags) for flags in structural_flags)
    )
    objective_validity = bool(
        math.isfinite(objective.total_objective)
        and all(math.isfinite(value) for value in objective.moment_contributions.values())
        and set(objective.group_contributions) == set(CORE_GROUPS)
    )
    deterministic = {
        "search_id": context.search_id,
        "schema_version": CANDIDATE_SCHEMA,
        "candidate_index": candidate_index,
        "structural_vector": asdict(candidate),
        "transformed_vector": [
            float(value) for value in context.transformed[candidate_index]
        ],
        "candidate_checksum": _candidate_checksum(
            candidate_index,
            candidate,
            context.transformed[candidate_index],
        ),
        "event_count": len(event_ids),
        "replication_count_per_event": REPLICATION_COUNT,
        "event_replication_count": len(records),
        "registry_id": REGISTRY_A,
        "event_result_checksums": event_checksums,
        "simulated_core_moments": aggregate.moments,
        "empirical_core_moments": context.objective["empirical"],
        "standardised_discrepancies": objective.standardised_discrepancies,
        "moment_contributions": objective.moment_contributions,
        "group_contributions": objective.group_contributions,
        "total_objective": objective.total_objective,
        "mcse_by_moment": mcse,
        "mcse_pass_by_moment": mcse_pass_by_moment,
        "mcse_pass": bool(all(mcse_pass_by_moment.values())),
        "numerical_bound_binding_share": float(np.mean(bound_shares)),
        "maximum_event_numerical_bound_binding_share": float(max(bound_shares)),
        "numerical_bound_pass": bool(max(bound_shares) <= 0.01),
        "right_censored_event_replications": (
            aggregate.right_censored_event_replications
        ),
        "structural_validity": structural_validity,
        "objective_validity": objective_validity,
        "acceptance_diagnostics": {
            "all_event_results_present": len(records)
            == len(event_ids) * REPLICATION_COUNT,
            "confidence_within_bounds": all(
                item["confidence_within_bounds"] for item in structural_flags
            ),
            "no_future_information": all(
                not item["future_information_used"] for item in structural_flags
            ),
            "valid_prices": all(item["valid_price"] for item in structural_flags),
            "valid_vault_states": all(
                item["valid_vault_state"] for item in structural_flags
            ),
            "valid_liquidation_states": all(
                item["valid_liquidation_state"] for item in structural_flags
            ),
            "valid_bad_debt_states": all(
                item["valid_bad_debt_state"] for item in structural_flags
            ),
            "no_duplicated_panic_term": all(
                not item["duplicated_panic_term"] for item in structural_flags
            ),
            "all_empirical_scales_positive": all(
                value > 0.0 for value in context.objective["scales"].values()
            ),
        },
        "implementation_schema": {
            "event_simulation": EVENT_SIMULATION_SCHEMA,
            "search_execution": SEARCH_EXECUTION_SCHEMA,
            "candidate_checkpoint": CANDIDATE_SCHEMA,
        },
    }
    deterministic["result_checksum"] = payload_sha256(deterministic)
    payload = {
        **deterministic,
        "execution_duration_seconds": time.perf_counter() - started,
    }
    arrays = {
        name: np.asarray(
            [
                (
                    int(record[name])
                    if name
                    in {
                        "replication",
                        "recovery_completion_hours",
                        "failed_recovery_attempts",
                    }
                    else float(record[name])
                )
                for record in records
            ]
        )
        for name in (
            "replication",
            "first_six_hour_burden",
            "maximum_downside_deviation",
            "recovery_completion_hours",
            "failed_recovery_attempts",
            "initial_peg_gap",
            "eth_recovery_24h",
            "numerical_bound_binding_share",
        )
    }
    arrays["event_index"] = np.asarray(
        [
            sorted(event_ids).index(record["event_id"])
            for record in records
        ],
        dtype="<i8",
    )
    arrays["right_censored"] = np.asarray(
        [record["right_censored"] for record in records], dtype="?"
    )
    return payload, arrays


def _worker_candidate(task: tuple[int, tuple[str, ...]]) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if _WORKER_CONTEXT is None:
        raise RuntimeError("Spawn worker was not initialised.")
    index, event_ids = task
    try:
        return _aggregate_candidate(
            _WORKER_CONTEXT,
            candidate_index=index,
            event_ids=event_ids,
        )
    except Exception as error:
        raise RuntimeError(
            f"Candidate {index:03d} failed deterministically: "
            f"{type(error).__name__}: {error}"
        ) from error


def _candidate_paths(run_dir: Path, index: int) -> tuple[Path, Path]:
    directory = run_dir / "candidates"
    return (
        directory / f"candidate_{index:03d}.json",
        directory / f"candidate_{index:03d}_metrics.npz",
    )


def _write_candidate_checkpoint(
    run_dir: Path,
    payload: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
) -> None:
    index = int(payload["candidate_index"])
    json_path, npz_path = _candidate_paths(run_dir, index)
    if json_path.exists() and npz_path.exists():
        try:
            validate_candidate_checkpoint(
                run_dir, index, expected_search_id=payload["search_id"]
            )
            return
        except ValueError:
            pass
    npz_content = deterministic_npz_bytes(arrays)
    checkpoint = dict(payload)
    checkpoint["metrics_payload_sha256"] = hashlib.sha256(npz_content).hexdigest()
    checkpoint["metrics_payload_size_bytes"] = len(npz_content)
    _atomic_bytes(npz_path, npz_content)
    _atomic_json(json_path, checkpoint)
    validate_candidate_checkpoint(
        run_dir, index, expected_search_id=payload["search_id"]
    )


def validate_candidate_checkpoint(
    run_dir: Path,
    index: int,
    *,
    expected_search_id: str,
) -> dict[str, Any]:
    json_path, npz_path = _candidate_paths(Path(run_dir), index)
    if not json_path.is_file() or not npz_path.is_file():
        raise ValueError(f"Candidate {index:03d} checkpoint is incomplete.")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if payload["search_id"] != expected_search_id:
        raise ValueError("Candidate checkpoint belongs to another search ID.")
    if payload["candidate_index"] != index:
        raise ValueError("Candidate checkpoint index differs.")
    if payload["schema_version"] != CANDIDATE_SCHEMA:
        raise ValueError("Candidate checkpoint schema differs.")
    if sha256_file(npz_path) != payload["metrics_payload_sha256"]:
        raise ValueError("Candidate metric payload checksum differs.")
    deterministic = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "execution_duration_seconds",
            "metrics_payload_sha256",
            "metrics_payload_size_bytes",
        }
    }
    result_checksum = deterministic.pop("result_checksum")
    if payload_sha256(deterministic) != result_checksum:
        raise ValueError("Candidate result checksum differs.")
    expected = int(payload["event_count"]) * int(
        payload["replication_count_per_event"]
    )
    if (
        expected != payload["event_replication_count"]
        or len(payload["event_result_checksums"]) != expected
    ):
        raise ValueError("Candidate checkpoint has incomplete event results.")
    identities = {
        (item["event_id"], item["replication"])
        for item in payload["event_result_checksums"]
    }
    if len(identities) != expected:
        raise ValueError("Candidate checkpoint contains duplicate event results.")
    arrays = _load_npz(npz_path)
    if any(len(value) != expected for value in arrays.values()):
        raise ValueError("Candidate metric arrays are incomplete.")
    return payload


@contextmanager
def search_lock(
    run_dir: Path,
    operation: str,
    *,
    recover_stale: bool = False,
) -> Iterable[dict[str, Any]]:
    """Prevent concurrent writers, with explicit stale-lock recovery."""
    lock_path = Path(run_dir) / "search.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        live = (
            lock.get("hostname") == socket.gethostname()
            and _process_exists(int(lock.get("process_id", -1)))
        )
        if live:
            raise RuntimeError(
                f"Search lock is owned by live process {lock['process_id']}."
            )
        if not recover_stale:
            raise RuntimeError("A stale search lock exists; explicit recovery is required.")
        lock_path.unlink()
    lock = {
        "search_id": Path(run_dir).name,
        "process_id": os.getpid(),
        "hostname": socket.gethostname(),
        "start_time_utc": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
    }
    descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(canonical_json_bytes(lock).decode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        yield lock
    finally:
        current = json.loads(lock_path.read_text(encoding="utf-8"))
        if current == lock:
            lock_path.unlink()


def _process_exists(process_id: int) -> bool:
    if process_id <= 0:
        return False
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _run_candidate_batch(
    run_dir: Path,
    candidate_indices: Sequence[int],
    event_ids: Sequence[str],
    *,
    workers: int,
    spawn: bool = True,
) -> list[tuple[dict[str, Any], dict[str, np.ndarray]]]:
    tasks = [(int(index), tuple(sorted(event_ids))) for index in candidate_indices]
    if workers == 1 and not spawn:
        _worker_initialise(str(run_dir))
        return [_worker_candidate(task) for task in tasks]
    context = mp.get_context("spawn")
    results = []
    with context.Pool(
        processes=workers,
        initializer=_worker_initialise,
        initargs=(str(run_dir),),
    ) as pool:
        for result in pool.imap_unordered(_worker_candidate, tasks, chunksize=1):
            results.append(result)
    return sorted(results, key=lambda item: item[0]["candidate_index"])


def benchmark_workers(
    run_dir: Path,
    *,
    supported_workers: Sequence[int] = (1, 2, 4, 6),
) -> dict[str, Any]:
    """Benchmark the fixed performance set and select by throughput only."""
    run_dir = Path(run_dir)
    context = json.loads((run_dir / "run_context.json").read_text(encoding="utf-8"))
    event_ids = tuple(
        sorted(
            context["event_ids"],
            key=lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest(),
        )[:4]
    )
    candidates = (0, 63, 127, 255)
    logical = os.cpu_count() or 1
    counts = [value for value in supported_workers if value <= logical]
    if not counts:
        counts = [1]
    records = []
    checksum_reference = None
    for workers in counts:
        started = time.perf_counter()
        results = _run_candidate_batch(
            run_dir, candidates, event_ids, workers=workers
        )
        wall = time.perf_counter() - started
        checksums = {
            item[0]["candidate_index"]: item[0]["result_checksum"]
            for item in results
        }
        if checksum_reference is None:
            checksum_reference = checksums
        elif checksums != checksum_reference:
            raise ValueError("Worker benchmark results differ by worker count.")
        runs = len(candidates) * len(event_ids) * REPLICATION_COUNT
        records.append(
            {
                "workers": workers,
                "wall_seconds": wall,
                "event_replication_runs": runs,
                "runs_per_second": runs / wall,
                "candidate_checksums": checksums,
            }
        )
    baseline = records[0]["runs_per_second"]
    for record in records:
        record["speed_up"] = record["runs_per_second"] / baseline
    maximum = max(record["runs_per_second"] for record in records)
    selected = min(
        record["workers"]
        for record in records
        if record["runs_per_second"] >= 0.95 * maximum
    )
    result = {
        "schema_version": 1,
        "available_logical_cpus": logical,
        "candidate_indices": list(candidates),
        "event_ids": list(event_ids),
        "replications": REPLICATION_COUNT,
        "tested": records,
        "selection_rule": (
            "smallest worker count within 5% of highest observed throughput"
        ),
        "selected_workers": selected,
        "zero_failures": True,
        "peak_memory": "not measured portably across spawned workers",
    }
    _atomic_json(run_dir / "worker_benchmark.json", result)
    return result


def validate_serial_parallel(
    run_dir: Path,
    *,
    workers: int,
) -> dict[str, Any]:
    """Require exact full-search candidate equality across schedules."""
    context = json.loads((Path(run_dir) / "run_context.json").read_text(encoding="utf-8"))
    indices = (0, 127, 255)
    event_ids = tuple(context["event_ids"])
    serial = _run_candidate_batch(
        Path(run_dir), indices, event_ids, workers=1, spawn=False
    )
    parallel = _run_candidate_batch(
        Path(run_dir), indices, event_ids, workers=workers
    )
    serial_payloads = {item[0]["candidate_index"]: item[0] for item in serial}
    parallel_payloads = {item[0]["candidate_index"]: item[0] for item in parallel}
    fields = (
        "result_checksum",
        "simulated_core_moments",
        "standardised_discrepancies",
        "total_objective",
        "event_result_checksums",
        "right_censored_event_replications",
        "maximum_event_numerical_bound_binding_share",
    )
    equal = all(
        serial_payloads[index][field] == parallel_payloads[index][field]
        for index in indices
        for field in fields
    )
    if not equal:
        raise ValueError("Serial and parallel candidate evaluation differ.")
    result = {
        "schema_version": 1,
        "candidate_indices": list(indices),
        "serial_workers": 1,
        "parallel_workers": workers,
        "exact_equality_fields": list(fields),
        "candidate_result_checksums": {
            str(index): serial_payloads[index]["result_checksum"]
            for index in indices
        },
        "status": "passed",
    }
    _atomic_json(Path(run_dir) / "serial_parallel_equivalence.json", result)
    return result


def run_sobol_search(
    run_dir: Path,
    *,
    workers: int,
    resume: bool,
    recover_stale_lock: bool = False,
) -> dict[str, Any]:
    """Evaluate or resume all 256 complete candidate tasks."""
    run_dir = Path(run_dir)
    identity = run_dir.name
    validate_search_cache(run_dir)
    checkpoint_state = classify_candidate_checkpoints(
        run_dir,
        expected_search_id=identity,
        candidate_count=CANDIDATE_COUNT,
    )
    completed = checkpoint_state["completed"]
    invalid = checkpoint_state["invalid"]
    if completed and not resume:
        raise ValueError("Completed candidates exist; use explicit resume.")
    pending = [index for index in range(CANDIDATE_COUNT) if index not in completed]
    started = time.perf_counter()
    with search_lock(
        run_dir,
        "resume_sobol_search" if resume else "run_sobol_search",
        recover_stale=recover_stale_lock,
    ):
        context = json.loads(
            (run_dir / "run_context.json").read_text(encoding="utf-8")
        )
        tasks = [
            (int(index), tuple(sorted(context["event_ids"])))
            for index in pending
        ]
        process_context = mp.get_context("spawn")
        with process_context.Pool(
            processes=workers,
            initializer=_worker_initialise,
            initargs=(str(run_dir),),
        ) as pool:
            for payload, arrays in pool.imap_unordered(
                _worker_candidate, tasks, chunksize=1
            ):
                _write_candidate_checkpoint(run_dir, payload, arrays)
        history_path = run_dir / "resume_history.json"
        history = (
            json.loads(history_path.read_text(encoding="utf-8"))
            if history_path.exists()
            else {"operations": []}
        )
        history["operations"].append(
            {
                "operation": "resume" if resume else "new",
                "completed_candidates_skipped": completed,
                "invalid_candidates_recomputed": invalid,
                "newly_evaluated_candidates": pending,
                "worker_count": workers,
                "wall_seconds": time.perf_counter() - started,
            }
        )
        _atomic_json(history_path, history)
    final = [
        validate_candidate_checkpoint(
            run_dir, index, expected_search_id=identity
        )
        for index in range(CANDIDATE_COUNT)
    ]
    return {
        "search_id": identity,
        "candidates_requested": CANDIDATE_COUNT,
        "candidates_completed": len(final),
        "candidate_failures": 0,
        "missing_candidate_indices": [],
        "duplicate_candidate_indices": [],
        "completed_candidates_skipped": len(completed),
        "invalid_candidates_recomputed": len(invalid),
        "newly_evaluated_candidates": len(pending),
        "workers": workers,
        "wall_seconds": time.perf_counter() - started,
    }


def classify_candidate_checkpoints(
    run_dir: Path,
    *,
    expected_search_id: str,
    candidate_count: int,
) -> dict[str, list[int]]:
    """Classify valid, invalid and absent tasks for deterministic resume."""
    completed = []
    invalid = []
    for index in range(candidate_count):
        try:
            validate_candidate_checkpoint(
                Path(run_dir), index, expected_search_id=expected_search_id
            )
            completed.append(index)
        except (ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
            if any(path.exists() for path in _candidate_paths(Path(run_dir), index)):
                invalid.append(index)
    pending = [
        index for index in range(candidate_count) if index not in completed
    ]
    return {
        "completed": completed,
        "invalid": invalid,
        "pending": pending,
    }


def rank_candidates(
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the fixed validity precedence and select a non-final top 16."""
    rows = [dict(value) for value in candidates]
    eligible = [
        value
        for value in rows
        if value["structural_validity"] and value["objective_validity"]
    ]
    ordered = sorted(
        eligible,
        key=lambda value: (
            not value["mcse_pass"],
            not value["numerical_bound_pass"],
            value["total_objective"],
            value["candidate_index"],
        ),
    )
    next_stage = [
        value
        for value in ordered
        if value["mcse_pass"] and value["numerical_bound_pass"]
    ]
    if len(next_stage) < 16:
        return ordered, []
    selected = next_stage[:16]
    return ordered, selected


def _candidate_row(
    payload: Mapping[str, Any],
    rank: int | None,
    selected: set[int],
) -> dict[str, Any]:
    vector = payload["structural_vector"]
    return {
        "candidate_index": payload["candidate_index"],
        **vector,
        "objective": payload["total_objective"],
        **{
            f"group_{name}_contribution": payload["group_contributions"][name]
            for name in CORE_GROUPS
        },
        "maximum_moment_contribution": max(
            payload["moment_contributions"].values()
        ),
        "mcse_pass": payload["mcse_pass"],
        "numerical_bound_pass": payload["numerical_bound_pass"],
        "structural_pass": payload["structural_validity"],
        "objective_pass": payload["objective_validity"],
        "right_censored_event_count": payload[
            "right_censored_event_replications"
        ],
        "rank": rank if rank is not None else "",
        "next_stage_eligibility": payload["candidate_index"] in selected,
        "result_checksum": payload["result_checksum"],
    }


def _manifest_register(paths: Sequence[Path]) -> None:
    manifest = json.loads(CALIBRATION_MANIFEST.read_text(encoding="utf-8"))
    records = {
        record["path"]: record for record in manifest["artefacts"]
    }
    for path in paths:
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        records[relative] = {
            "path": relative,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "semantic_name": path.stem,
            "context": "pre-registered confidence Sobol search; calibration-only",
            "classification": "snapshot",
            "producer": "dai_sim.calibration.simulated_moments_search",
            "schema": (
                "Compact calibration evidence; no cache, trajectory or "
                "replication payload."
            ),
            "source_inputs": sorted(identity for identity in (
                "data/provenance/calibration/confidence/"
                "simulated_moments_specification.json",
                "data/provenance/calibration/confidence/"
                "conditional_event_specification.json",
            )),
        }
    manifest["artefacts"] = [
        records[name] for name in sorted(records)
    ]
    _atomic_bytes(
        CALIBRATION_MANIFEST,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def summarise_sobol_search(
    run_dir: Path,
    *,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    register_manifest: bool = True,
) -> dict[str, Any]:
    """Reconstruct compact tracked evidence from complete checkpoints."""
    run_dir = Path(run_dir)
    identity, design = load_search_identity(evidence_dir)
    if run_dir.name != identity.search_id:
        raise ValueError("Run directory and current search identity differ.")
    cache = validate_search_cache(run_dir, expected_identity=identity)
    candidates = [
        validate_candidate_checkpoint(
            run_dir, index, expected_search_id=identity.search_id
        )
        for index in range(CANDIDATE_COUNT)
    ]
    ranked, selected = rank_candidates(candidates)
    rank_map = {
        value["candidate_index"]: rank
        for rank, value in enumerate(ranked, start=1)
    }
    selected_indices = {value["candidate_index"] for value in selected}
    candidate_frame = pd.DataFrame(
        [
            _candidate_row(
                value,
                rank_map.get(value["candidate_index"]),
                selected_indices,
            )
            for value in sorted(
                candidates, key=lambda item: item["candidate_index"]
            )
        ]
    )
    benchmark = json.loads(
        (run_dir / "worker_benchmark.json").read_text(encoding="utf-8")
    )
    equivalence = json.loads(
        (run_dir / "serial_parallel_equivalence.json").read_text(
            encoding="utf-8"
        )
    )
    history = json.loads(
        (run_dir / "resume_history.json").read_text(encoding="utf-8")
    )
    specification = {
        "schema_version": 1,
        "search_id": identity.search_id,
        "scientific_input_checksums": identity.inputs,
        "implementation_schema": {
            "event_simulation": EVENT_SIMULATION_SCHEMA,
            "search_execution": SEARCH_EXECUTION_SCHEMA,
        },
        "fixed_search_subset": {
            "count": SEARCH_EVENT_COUNT,
            "event_ids": list(design["event_ids"]),
            "sha256": identity.event_subset_sha256,
        },
        "fixed_sobol_checksum": identity.candidate_sha256,
        "candidate_count": CANDIDATE_COUNT,
        "event_count": SEARCH_EVENT_COUNT,
        "replications": REPLICATION_COUNT,
        "registry_id": REGISTRY_A,
        "moment_schema": list(SIMULATED_CORE_MOMENT_ORDER),
        "objective_schema": {
            "groups": list(CORE_GROUPS),
            "scales": "registered empirical scales",
        },
        "worker_selection_rule": benchmark["selection_rule"],
        "cache_identity": cache["cache_root_sha256"],
        "resume_rules": (
            "skip only checksum-valid, schema-valid complete candidates"
        ),
        "runtime_adopted": False,
    }
    cache_summary = {
        "schema_version": CACHE_SCHEMA,
        "search_id": identity.search_id,
        "event_replication_package_count": cache["package_count"],
        "cache_root_checksum": cache["cache_root_sha256"],
        "aggregate_byte_size": cache["aggregate_bytes"],
        "validation_status": cache["status"],
        "cache_payloads_embedded": False,
    }
    top16 = {
        "schema_version": 1,
        "search_id": identity.search_id,
        "selected_candidate_indices": [
            value["candidate_index"] for value in selected
        ],
        "candidates": [
            {
                "candidate_index": value["candidate_index"],
                "structural_vector": value["structural_vector"],
                "objective": value["total_objective"],
                "rank": rank_map[value["candidate_index"]],
                "result_checksum": value["result_checksum"],
            }
            for value in selected
        ],
        "selection_rule": (
            "structural and objective validity; MCSE and numerical-bound "
            "validity; objective ascending; candidate-index tie-break"
        ),
        "status": (
            "accepted_for_all_event_followup"
            if len(selected) == 16
            else "insufficient_valid_candidates"
        ),
        "runtime_adopted": False,
        "final_parameter_selection": False,
    }
    deterministic_summary = {
        "candidate_result_checksums": [
            value["result_checksum"]
            for value in sorted(
                candidates, key=lambda item: item["candidate_index"]
            )
        ],
        "ranking": [
            value["candidate_index"] for value in ranked
        ],
        "top16": top16["selected_candidate_indices"],
    }
    reproducibility = {
        "schema_version": 1,
        "search_id": identity.search_id,
        "serial_parallel_test_candidates": equivalence["candidate_indices"],
        "serial_parallel_result_checksums": equivalence[
            "candidate_result_checksums"
        ],
        "worker_benchmark_checksums": benchmark["tested"][0][
            "candidate_checksums"
        ],
        "selected_worker_count": benchmark["selected_workers"],
        "summary_reconstruction_checksum": payload_sha256(
            deterministic_summary
        ),
        "resume_validation": {
            "operation_count": len(history["operations"]),
            "completed_candidates_reused": sum(
                len(item["completed_candidates_skipped"])
                for item in history["operations"]
            ),
        },
        "candidate_completion_count": len(candidates),
        "search_wall_time_seconds": sum(
            item["wall_seconds"] for item in history["operations"]
        ),
        "registry_b_used": False,
        "final_validation_used": False,
        "runtime_adopted": False,
    }
    total_wall = sum(item["wall_seconds"] for item in history["operations"])
    benchmark_evidence = {
        "schema_version": 1,
        "search_id": identity.search_id,
        "cache_preparation_time_seconds": json.loads(
            (run_dir / "cache_validation.json").read_text(encoding="utf-8")
        )["preparation_seconds"],
        "worker_benchmark": benchmark,
        "selected_workers": benchmark["selected_workers"],
        "full_search_wall_time_seconds": total_wall,
        "candidates_per_hour": CANDIDATE_COUNT / total_wall * 3600,
        "event_replication_runs_per_second": (
            CANDIDATE_COUNT
            * SEARCH_EVENT_COUNT
            * REPLICATION_COUNT
            / total_wall
        ),
        "observed_peak_memory": benchmark["peak_memory"],
        "projected_unexecuted_workloads": {
            "top16_all_74_events_runs": 16 * 74 * REPLICATION_COUNT,
            "powell": "not estimated without an authorised evaluation budget",
            "finalist_64_replication_registry_b": (
                "not estimated without an authorised finalist count"
            ),
        },
        "runtime_adopted": False,
    }
    outputs = {
        "sobol_search_specification.json": specification,
        "sobol_search_cache_summary.json": cache_summary,
        "sobol_search_top16.json": top16,
        "sobol_search_reproducibility.json": reproducibility,
        "sobol_search_benchmark.json": benchmark_evidence,
    }
    evidence_dir = Path(evidence_dir)
    for name, payload in outputs.items():
        _atomic_json(evidence_dir / name, payload)
    _atomic_csv(evidence_dir / "sobol_search_candidates.csv", candidate_frame)
    _write_search_diagnostics(
        run_dir,
        candidates=candidates,
        candidate_frame=candidate_frame,
        selected=selected,
        history=history,
    )
    paths = [evidence_dir / name for name in TRACKED_SEARCH_FILES]
    if register_manifest:
        _manifest_register(paths)
    return {
        "search_id": identity.search_id,
        "candidate_count": len(candidates),
        "structurally_valid_candidates": sum(
            value["structural_validity"] for value in candidates
        ),
        "objective_valid_candidates": sum(
            value["objective_validity"] for value in candidates
        ),
        "mcse_valid_candidates": sum(value["mcse_pass"] for value in candidates),
        "numerical_bound_valid_candidates": sum(
            value["numerical_bound_pass"] for value in candidates
        ),
        "top16_count": len(selected),
        "top16_indices": top16["selected_candidate_indices"],
        "evidence_paths": [path.as_posix() for path in paths],
    }


def _write_search_diagnostics(
    run_dir: Path,
    *,
    candidates: Sequence[Mapping[str, Any]],
    candidate_frame: pd.DataFrame,
    selected: Sequence[Mapping[str, Any]],
    history: Mapping[str, Any],
) -> None:
    """Write generated tables without trajectories or tracked-path ownership."""
    diagnostics = Path(run_dir) / "diagnostics"
    _atomic_csv(diagnostics / "candidate_status.csv", candidate_frame)
    _atomic_csv(
        diagnostics / "candidate_objectives.csv",
        candidate_frame[
            [
                "candidate_index",
                "objective",
                "rank",
                "next_stage_eligibility",
            ]
        ],
    )
    _atomic_csv(
        diagnostics / "group_contributions.csv",
        pd.DataFrame(
            [
                {
                    "candidate_index": candidate["candidate_index"],
                    "group": group,
                    "contribution": candidate["group_contributions"][group],
                }
                for candidate in candidates
                for group in CORE_GROUPS
            ]
        ),
    )
    _atomic_csv(
        diagnostics / "moment_contributions.csv",
        pd.DataFrame(
            [
                {
                    "candidate_index": candidate["candidate_index"],
                    "moment": moment,
                    "contribution": candidate["moment_contributions"][moment],
                }
                for candidate in candidates
                for moment in SIMULATED_CORE_MOMENT_ORDER
            ]
        ),
    )
    _atomic_csv(
        diagnostics / "mcse.csv",
        pd.DataFrame(
            [
                {
                    "candidate_index": candidate["candidate_index"],
                    "moment": moment,
                    "mcse": candidate["mcse_by_moment"][moment],
                    "pass": candidate["mcse_pass_by_moment"][moment],
                }
                for candidate in candidates
                for moment in SIMULATED_CORE_MOMENT_ORDER
            ]
        ),
    )
    _atomic_csv(
        diagnostics / "right_censoring.csv",
        pd.DataFrame(
            [
                {
                    "candidate_index": candidate["candidate_index"],
                    "right_censored_event_replications": candidate[
                        "right_censored_event_replications"
                    ],
                }
                for candidate in candidates
            ]
        ),
    )
    _atomic_csv(
        diagnostics / "numerical_bounds.csv",
        pd.DataFrame(
            [
                {
                    "candidate_index": candidate["candidate_index"],
                    "mean_binding_share": candidate[
                        "numerical_bound_binding_share"
                    ],
                    "maximum_event_binding_share": candidate[
                        "maximum_event_numerical_bound_binding_share"
                    ],
                    "pass": candidate["numerical_bound_pass"],
                }
                for candidate in candidates
            ]
        ),
    )
    parameter_columns = [
        "candidate_index",
        "deterioration_adjustment",
        "recovery_adjustment",
        "confidence_floor",
        "panic_response",
        "objective",
    ]
    _atomic_csv(
        diagnostics / "parameter_objective_scatter.csv",
        candidate_frame[parameter_columns],
    )
    _atomic_csv(
        diagnostics / "top16_comparison.csv",
        candidate_frame.loc[
            candidate_frame["candidate_index"].isin(
                [value["candidate_index"] for value in selected]
            )
        ],
    )
    _atomic_json(diagnostics / "search_timing.json", {"operations": history["operations"]})
    _atomic_json(Path(run_dir) / "resume_history_snapshot.json", history)


def validate_completed_search(
    run_dir: Path,
    *,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> dict[str, Any]:
    """Audit the full fixed design and compact evidence."""
    identity, design = load_search_identity(evidence_dir)
    cache = validate_search_cache(run_dir, expected_identity=identity)
    candidates = [
        validate_candidate_checkpoint(
            Path(run_dir), index, expected_search_id=identity.search_id
        )
        for index in range(CANDIDATE_COUNT)
    ]
    for payload, expected, transformed in zip(
        candidates,
        design["structural"],
        design["transformed"],
        strict=True,
    ):
        index = payload["candidate_index"]
        if (
            payload["structural_vector"] != asdict(expected)
            or payload["transformed_vector"]
            != [float(value) for value in transformed]
            or payload["candidate_checksum"]
            != _candidate_checksum(index, expected, transformed)
        ):
            raise ValueError(
                f"Candidate {index:03d} differs from the registered Sobol vector."
            )
    if any(
        value["event_count"] != SEARCH_EVENT_COUNT
        or value["replication_count_per_event"] != REPLICATION_COUNT
        or value["registry_id"] != REGISTRY_A
        for value in candidates
    ):
        raise ValueError("A completed candidate differs from the fixed design.")
    if any(
        any(
            not item["event_id"].startswith("calibration__")
            for item in value["event_result_checksums"]
        )
        for value in candidates
    ):
        raise ValueError("Final validation entered the completed search.")
    tracked = []
    records = _manifest_records()
    for name in TRACKED_SEARCH_FILES:
        path = Path(evidence_dir) / name
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        if relative not in records or records[relative]["sha256"] != sha256_file(path):
            raise ValueError(f"Search evidence is not registered: {relative}.")
        tracked.append(relative)
    ranked, selected = rank_candidates(candidates)
    return {
        "status": "passed",
        "search_id": identity.search_id,
        "cache": cache,
        "candidate_checkpoints": len(candidates),
        "candidate_indices": [value["candidate_index"] for value in candidates],
        "missing_candidates": 0,
        "duplicate_candidates": 0,
        "structural_vectors_match": CANDIDATE_COUNT,
        "events_per_candidate": SEARCH_EVENT_COUNT,
        "replications_per_event": REPLICATION_COUNT,
        "final_validation_events": 0,
        "registry_b_evaluations": 0,
        "powell_evaluations": 0,
        "ranked_candidates": len(ranked),
        "top16_count": len(selected),
        "tracked_evidence": tracked,
        "runtime_adopted": False,
    }
