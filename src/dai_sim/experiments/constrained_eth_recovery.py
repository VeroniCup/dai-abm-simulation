"""Pre-registered constrained-liquidation ETH-recovery experiment.

The experiment composes the validated empirical ETH profile with the existing
controlled recovery paths, system-wide keeper candidates and confidence
scenario registry.  It owns experimental treatment assignment, common random
numbers, compact vault-event diagnostics and paired inference; it does not
replace model mechanics or runtime defaults.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any

import numpy as np
import pandas as pd
import yaml

from dai_sim.calibration.event_simulation import (
    SPARSE_SCALING_EVIDENCE,
    load_stage1_owners,
)
from dai_sim.calibration.integrated_eth_validation import (
    EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
    EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
    _normalised_initial_state,
)
from dai_sim.calibration.market import sample_residual_blocks
from dai_sim.experiments.confidence_scenarios import (
    EXPECTED_SCENARIO_ORDER,
    load_confidence_scenario_registry,
)
from dai_sim.experiments.eth_recovery import (
    EXPECTED_CONFIDENCE_CONFIG_SHA256,
    EXPECTED_CONFIDENCE_REGISTRY_SHA256,
    RecoveryDesign,
    RecoveryPathDefinition,
    _recovery_metrics,
    _simulate_market_scenario,
    build_eth_path,
    load_recovery_design,
    path_checksum,
    shock_checksum,
)
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file
from dai_sim.inputs.gas import component_gas_costs
from dai_sim.inputs.integrated_profile import (
    EXPECTED_INPUT_CHECKSUMS,
    EXPECTED_KEEPER_CONFIGURATION_SHA256,
    EXPECTED_KEEPER_REGISTRY_SHA256,
    EXPECTED_STAGE1_ABOVE_PEG_RESPONSE,
    EXPECTED_STAGE1_BELOW_PEG_RESPONSE,
    SHARED_KEEPER_CAPACITY,
    TOTAL_DEBT_DAI,
    VAULT_COUNT,
    IntegratedEmpiricalETHProfile,
    resolve_integrated_empirical_eth_profile,
)
from dai_sim.inputs.keeper_execution import resolve_keeper_execution_candidate
from dai_sim.inputs.liquidations import (
    LiquidationDemandDecision,
    load_liquidation_arrival_pool,
)
from dai_sim.inputs.market import load_market_gas_pool, sample_market_gas_blocks
from dai_sim.model.liquidation import liquidate_vaults, summarise_liquidations


DEFAULT_CONFIG_PATH = (
    REPOSITORY_ROOT / "config/sensitivities/constrained_eth_recovery.yaml"
)
DEFAULT_EVIDENCE_DIR = (
    REPOSITORY_ROOT / "data/provenance/experiments/constrained_recovery"
)
DEFAULT_MANIFEST_PATH = (
    REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"
)
STARTING_CODE_PARENT = "ffb6c65cd1d57e1aa49b1e5b4dc77da1c212fcef"
REGISTERED_SCIENTIFIC_CODE_IDENTITY = (
    "17ace2ebe8a57e277c0bef0cedcc92956be02920991c597f20c6c8ceeb81ab08"
)
REGISTERED_EXPERIMENT_IDENTITY = (
    "6cfbd19384fc95fe8b06de74704d0b2a76638722b100242e0bc87a9ee3e05acc"
)
PROFILE_IDENTITY = (
    "ab68c32a145262bcef07716469d92be09e3d96506383ad16a07d0ba1bad2b34d"
)
PROFILE_SHA256 = (
    "ea0e08f263210af3c3041843537f975ebd886fcf5130c617b0edb189218b3862"
)
RECOVERY_PATH_ORDER = ("persistent_trough", "full_week")
CAPACITY_ORDER = (
    "shared_keeper_capacity_low",
    "shared_keeper_capacity_central",
    "shared_keeper_capacity_high",
)
CAPACITY_VALUES = {
    "shared_keeper_capacity_low": 14,
    "shared_keeper_capacity_central": 26,
    "shared_keeper_capacity_high": 45,
}
EXPECTED_PATH_CHECKSUMS = {
    "persistent_trough": (
        "fbe1e92c038a60f662e59178e77d7fcbfa0571a76d6c90494f7ec8b05f5239f5"
    ),
    "full_week": (
        "f175c9111380499b2b7d71d32a4ac6f42cc3f8bc3d196c7fded95cb87a2c4d3b"
    ),
}
EXPECTED_SHOCK_CHECKSUM = (
    "f7370b9f2faa6c2e97ca5dddf7b28d3ccfa109ee52f635d9ff43a8893f683ea5"
)
SEED_STREAMS = (
    "vault_sampling",
    "market_gas_blocks",
    "keeper_gas_units",
    "liquidation_arrivals",
    "stage1_residual_blocks",
)
PRIMARY_CELL_METRICS = (
    "backlog_area_dai_hours",
    "maximum_unresolved_tab_dai",
    "cumulative_realised_bad_debt_dai",
    "below_peg_burden",
    "restricted_mean_recovery_time",
)
SUMMARY_METRICS = (
    *PRIMARY_CELL_METRICS,
    "unsafe_vault_count",
    "peak_unsafe_share",
    "newly_unsafe_count",
    "cumulative_arrival_count",
    "cumulative_attempts",
    "cumulative_successful_closures",
    "cumulative_capacity_rejected",
    "cumulative_unprofitable_attempts",
    "binding_hours",
    "positive_demand_hours",
    "mean_capacity_utilisation",
    "maximum_capacity_utilisation",
    "maximum_attempts_one_hour",
    "cumulative_debt_repaid_dai",
    "completed_liquidation_count",
    "unresolved_vault_count",
    "unresolved_tab_at_horizon_dai",
    "maximum_backlog_duration",
    "active_bad_debt_at_horizon_dai",
    "maximum_active_bad_debt_dai",
    "keeper_profit_dai",
    "recovered_before_execution_count",
    "recovered_before_closure_count",
    "minimum_dai_price",
    "maximum_negative_peg_deviation",
    "mean_absolute_peg_deviation",
    "hours_below_0995",
    "hours_above_1005",
    "first_return_time",
    "failed_recovery_attempts",
    "recovery_probability_168h",
    "recovery_probability_336h",
    "recovery_probability_720h",
    "final_dai_price",
    "final_peg_band_status",
    "minimum_confidence",
    "mean_confidence_loss",
    "confidence_at_horizon",
    "hours_at_confidence_floor",
    "hours_recovery_gate_closed",
    "first_recovery_gate_open",
    "recovery_gate_reopenings",
    "cumulative_panic_contribution",
    "maximum_panic_contribution",
)
RECOVERY_CONTRAST_METRICS = (
    *SUMMARY_METRICS,
    "paired_liquidations_avoided",
    "paired_additional_liquidations",
    "paired_avoided_debt_dai",
    "paired_additional_debt_dai",
    "closure_time_difference_mean",
)
CAPACITY_CONTRASTS = (
    ("shared_keeper_capacity_central", "shared_keeper_capacity_low"),
    ("shared_keeper_capacity_high", "shared_keeper_capacity_central"),
    ("shared_keeper_capacity_high", "shared_keeper_capacity_low"),
)
INTERACTION_CONTRASTS = (
    ("shared_keeper_capacity_low", "shared_keeper_capacity_high"),
    ("shared_keeper_capacity_central", "shared_keeper_capacity_high"),
    ("shared_keeper_capacity_low", "shared_keeper_capacity_central"),
)
EVIDENCE_FILENAMES = (
    "constrained_recovery_specification.json",
    "constrained_recovery_registry.csv",
    "constrained_recovery_cell_summary.csv",
    "constrained_recovery_vault_rescue.csv",
    "constrained_recovery_recovery_contrasts.csv",
    "constrained_recovery_capacity_contrasts.csv",
    "constrained_recovery_interactions.csv",
    "constrained_recovery_decision.json",
    "constrained_recovery_reproducibility.json",
    "constrained_recovery_benchmark.json",
)


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=lambda value: (
            value.item() if isinstance(value, np.generic) else value
        ),
    ).encode("utf-8")


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, payload: Any) -> None:
    _atomic_bytes(
        path,
        (
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8"),
    )


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    output = io.StringIO(newline="")
    frame.to_csv(output, index=False, lineterminator="\n", float_format="%.12g")
    return output.getvalue().encode("utf-8")


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()


@dataclass(frozen=True)
class ConstrainedRecoveryCell:
    """One path-by-capacity-by-confidence treatment cell."""

    order: int
    identifier: str
    recovery_path: str
    path_checksum: str
    capacity_profile: str
    capacity: int
    confidence_scenario: str
    scenario_checksum: str
    replication_count: int
    row_checksum: str


@dataclass(frozen=True)
class ConstrainedRecoveryDesign:
    """Validated result-blind experimental design."""

    config_path: Path
    config_sha256: str
    experiment_id: str
    profile_identity: str
    profile_sha256: str
    recovery_design: RecoveryDesign
    recovery_paths: tuple[str, ...]
    capacities: tuple[str, ...]
    confidence_scenarios: tuple[str, ...]
    replications: int
    total_hours: int
    pre_shock_hours: int
    post_shock_hours: int
    lower_band: float
    upper_band: float
    stability_hours: int
    recovery_cap_hours: int
    registry_id: str
    materiality: Mapping[str, float]
    output_root: Path
    evidence_dir: Path
    maximum_new_bytes: int
    minimum_free_bytes: int


def scientific_code_identity() -> str:
    """Return the immutable scientific owner of the completed experiment.

    Operational maintenance may repair invocation or configuration-loading
    infrastructure without re-identifying the registered scientific design.
    """
    return REGISTERED_SCIENTIFIC_CODE_IDENTITY


def load_design(
    path: Path | str = DEFAULT_CONFIG_PATH,
) -> ConstrainedRecoveryDesign:
    """Load and validate the sole constrained-recovery design owner."""
    config_path = Path(path).resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        raise ValueError("Unsupported constrained-recovery design schema.")
    if payload.get("experiment_id") != "constrained_eth_recovery_v1":
        raise ValueError("Unexpected constrained-recovery experiment identity.")
    profile = resolve_integrated_empirical_eth_profile()
    integrated = payload["integrated_profile"]
    if (
        profile.profile_identity != PROFILE_IDENTITY
        or profile.profile_checksum != PROFILE_SHA256
        or integrated["identity"] != PROFILE_IDENTITY
        or integrated["sha256"] != PROFILE_SHA256
    ):
        raise ValueError("Integrated empirical profile identity changed.")
    recovery = load_recovery_design(
        REPOSITORY_ROOT / payload["recovery_owner"]["configuration"]
    )
    if shock_checksum(recovery) != EXPECTED_SHOCK_CHECKSUM:
        raise ValueError("Canonical ETH shock checksum changed.")
    definitions = {item.identifier: item for item in recovery.path_definitions}
    recovery_paths = tuple(
        str(row["identifier"]) for row in payload["recovery_owner"]["paths"]
    )
    if recovery_paths != RECOVERY_PATH_ORDER:
        raise ValueError("Recovery paths must be persistent_trough then full_week.")
    for row in payload["recovery_owner"]["paths"]:
        identifier = str(row["identifier"])
        observed = path_checksum(build_eth_path(recovery, definitions[identifier]))
        if observed != EXPECTED_PATH_CHECKSUMS[identifier] or row["sha256"] != observed:
            raise ValueError(f"Recovery path checksum changed: {identifier}.")
    keeper = payload["keeper"]
    if (
        sha256_file(REPOSITORY_ROOT / keeper["registry"])
        != EXPECTED_KEEPER_CONFIGURATION_SHA256
        or keeper["registry_sha256"] != EXPECTED_KEEPER_CONFIGURATION_SHA256
        or keeper["evidence_registry_sha256"] != EXPECTED_KEEPER_REGISTRY_SHA256
        or keeper["hurdle_profile"] != "direct_cost_only"
        or float(keeper["risk_cost_rate"]) != 0.0
        or keeper["semantics"] != "system_wide_shared_capacity"
    ):
        raise ValueError("Keeper treatment changed.")
    capacities = tuple(str(row["profile"]) for row in keeper["capacities"])
    if capacities != CAPACITY_ORDER:
        raise ValueError("Keeper capacity order changed.")
    for row in keeper["capacities"]:
        candidate = resolve_keeper_execution_candidate(
            str(row["profile"]), "direct_cost_only"
        )
        expected = CAPACITY_VALUES[candidate.capacity_profile_id]
        if (
            int(row["value"]) != expected
            or candidate.maximum_liquidations_per_step != expected
            or candidate.risk_cost_rate != 0.0
        ):
            raise ValueError("Registered keeper capacity or hurdle changed.")
    confidence = payload["confidence"]
    if (
        sha256_file(REPOSITORY_ROOT / confidence["registry"])
        != EXPECTED_CONFIDENCE_CONFIG_SHA256
        or confidence["configuration_sha256"] != EXPECTED_CONFIDENCE_CONFIG_SHA256
        or confidence["evidence_registry_sha256"]
        != EXPECTED_CONFIDENCE_REGISTRY_SHA256
        or tuple(confidence["order"]) != EXPECTED_SCENARIO_ORDER
        or confidence["primary"] != "stage1_only"
    ):
        raise ValueError("Confidence registry or primary owner changed.")
    randomness = payload["randomness"]
    horizon = payload["horizon"]
    output = payload["output"]
    design = ConstrainedRecoveryDesign(
        config_path=config_path,
        config_sha256=sha256_file(config_path),
        experiment_id=str(payload["experiment_id"]),
        profile_identity=profile.profile_identity,
        profile_sha256=profile.profile_checksum,
        recovery_design=recovery,
        recovery_paths=recovery_paths,
        capacities=capacities,
        confidence_scenarios=tuple(confidence["order"]),
        replications=int(randomness["replications_per_cell"]),
        total_hours=int(horizon["total_hours"]),
        pre_shock_hours=int(horizon["pre_shock_hours"]),
        post_shock_hours=int(horizon["post_shock_hours"]),
        lower_band=float(horizon["recovery_band_lower"]),
        upper_band=float(horizon["recovery_band_upper"]),
        stability_hours=int(horizon["sustained_recovery_hours"]),
        recovery_cap_hours=int(horizon["restricted_mean_cap_hours"]),
        registry_id=str(randomness["registry_id"]),
        materiality={
            str(key): float(value)
            for key, value in payload["materiality"].items()
        },
        output_root=REPOSITORY_ROOT / output["root"],
        evidence_dir=REPOSITORY_ROOT / output["compact_evidence"],
        maximum_new_bytes=int(output["maximum_new_bytes"]),
        minimum_free_bytes=int(output["minimum_free_bytes"]),
    )
    if (
        design.replications != 128
        or design.pre_shock_hours != 48
        or design.post_shock_hours != 720
        or design.total_hours != 768
        or design.recovery_design.total_hours != design.total_hours
    ):
        raise ValueError("Replication or horizon design changed.")
    return design


def build_paths(
    design: ConstrainedRecoveryDesign,
) -> dict[str, np.ndarray]:
    definitions = {
        item.identifier: item
        for item in design.recovery_design.path_definitions
    }
    result = {
        identifier: build_eth_path(
            design.recovery_design, definitions[identifier]
        )
        for identifier in design.recovery_paths
    }
    for identifier, values in result.items():
        if path_checksum(values) != EXPECTED_PATH_CHECKSUMS[identifier]:
            raise ValueError(f"Controlled path changed: {identifier}.")
    return result


def _scenario_checksums() -> dict[str, str]:
    registry = load_confidence_scenario_registry()
    return {
        scenario.identifier: _payload_sha256(scenario.record())
        for scenario in registry.scenarios
    }


def build_cell_registry(
    design: ConstrainedRecoveryDesign,
    paths: Mapping[str, np.ndarray] | None = None,
) -> tuple[ConstrainedRecoveryCell, ...]:
    """Build the exact path-capacity-confidence ordered 24-cell registry."""
    path_values = dict(paths or build_paths(design))
    scenarios = _scenario_checksums()
    cells: list[ConstrainedRecoveryCell] = []
    for path_identifier in design.recovery_paths:
        for capacity_profile in design.capacities:
            capacity = CAPACITY_VALUES[capacity_profile]
            for confidence_scenario in design.confidence_scenarios:
                order = len(cells) + 1
                identifier = (
                    f"{path_identifier}__capacity_{capacity}__"
                    f"{confidence_scenario}"
                )
                base = {
                    "order": order,
                    "identifier": identifier,
                    "recovery_path": path_identifier,
                    "path_checksum": path_checksum(
                        path_values[path_identifier]
                    ),
                    "capacity_profile": capacity_profile,
                    "capacity": capacity,
                    "capacity_semantics": "system_wide_shared_capacity",
                    "hurdle_profile": "direct_cost_only",
                    "confidence_scenario": confidence_scenario,
                    "scenario_checksum": scenarios[confidence_scenario],
                    "integrated_profile_checksum": design.profile_sha256,
                    "replication_count": design.replications,
                }
                cells.append(
                    ConstrainedRecoveryCell(
                        order=order,
                        identifier=identifier,
                        recovery_path=path_identifier,
                        path_checksum=base["path_checksum"],
                        capacity_profile=capacity_profile,
                        capacity=capacity,
                        confidence_scenario=confidence_scenario,
                        scenario_checksum=base["scenario_checksum"],
                        replication_count=design.replications,
                        row_checksum=_payload_sha256(base),
                    )
                )
    if len(cells) != 24 or len({cell.identifier for cell in cells}) != 24:
        raise ValueError("Constrained-recovery registry must contain 24 cells.")
    return tuple(cells)


def derive_seed(replication: int, stream: str) -> int:
    """Derive a treatment-invariant seed from the dedicated registry."""
    if stream not in SEED_STREAMS:
        raise ValueError(f"Unknown constrained-recovery stream: {stream}.")
    if isinstance(replication, bool) or replication < 0:
        raise ValueError("replication must be a non-negative integer.")
    return int.from_bytes(
        hashlib.sha256(
            _canonical_json(
                {
                    "registry_id": "constrained_eth_recovery_v1",
                    "replication": int(replication),
                    "stream": stream,
                    "version": 1,
                }
            )
        ).digest()[:8],
        "big",
    )


def seed_record(replication: int) -> dict[str, Any]:
    record = {
        "replication": replication,
        **{
            f"{stream}_seed": derive_seed(replication, stream)
            for stream in SEED_STREAMS
        },
    }
    return {**record, "seed_record_checksum": _payload_sha256(record)}


def seed_registry_checksum(replications: int = 128) -> str:
    return _payload_sha256(
        [seed_record(replication) for replication in range(replications)]
    )


def experiment_identity(
    design: ConstrainedRecoveryDesign,
    cells: Sequence[ConstrainedRecoveryCell] | None = None,
) -> str:
    registry = tuple(cells or build_cell_registry(design))
    return _payload_sha256(
        {
            "schema_version": 1,
            "starting_code_parent": STARTING_CODE_PARENT,
            "scientific_code_identity": scientific_code_identity(),
            "design_sha256": design.config_sha256,
            "profile_identity": design.profile_identity,
            "profile_sha256": design.profile_sha256,
            "shock_sha256": EXPECTED_SHOCK_CHECKSUM,
            "path_checksums": EXPECTED_PATH_CHECKSUMS,
            "keeper_configuration_sha256": EXPECTED_KEEPER_CONFIGURATION_SHA256,
            "keeper_registry_sha256": EXPECTED_KEEPER_REGISTRY_SHA256,
            "confidence_configuration_sha256": EXPECTED_CONFIDENCE_CONFIG_SHA256,
            "confidence_registry_sha256": EXPECTED_CONFIDENCE_REGISTRY_SHA256,
            "cell_order": [cell.identifier for cell in registry],
            "replications": design.replications,
            "seed_registry_sha256": seed_registry_checksum(design.replications),
            "metrics": list(SUMMARY_METRICS),
            "materiality": dict(design.materiality),
        }
    )


def _source_checksums(profile: IntegratedEmpiricalETHProfile) -> dict[str, str]:
    return {
        **profile.input_checksums,
        "keeper_configuration": EXPECTED_KEEPER_CONFIGURATION_SHA256,
        "keeper_registry": EXPECTED_KEEPER_REGISTRY_SHA256,
        "confidence_configuration": EXPECTED_CONFIDENCE_CONFIG_SHA256,
        "confidence_registry": EXPECTED_CONFIDENCE_REGISTRY_SHA256,
        "stage1_residual_sequence": EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
        "stage1_residual_blocks": EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
    }


def specification_payload(
    design: ConstrainedRecoveryDesign,
) -> dict[str, Any]:
    """Construct the immutable result-blind scientific specification."""
    profile = resolve_integrated_empirical_eth_profile()
    cells = build_cell_registry(design)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "scientific_purpose": (
            "Test whether controlled ETH recovery rescues unsafe vaults under "
            "empirical liquidation arrivals and system-wide keeper constraints."
        ),
        "starting_code_parent": STARTING_CODE_PARENT,
        "scientific_code_identity": scientific_code_identity(),
        "experiment_identity": experiment_identity(design, cells),
        "integrated_profile": {
            "identifier": profile.identifier,
            "identity": profile.profile_identity,
            "sha256": profile.profile_checksum,
            "vault_count": VAULT_COUNT,
            "total_debt_dai": TOTAL_DEBT_DAI,
            "runtime_adopted": False,
        },
        "protected_inputs": _source_checksums(profile),
        "controlled_price_boundary": {
            "shock_sha256": EXPECTED_SHOCK_CHECKSUM,
            "path_checksums": EXPECTED_PATH_CHECKSUMS,
            "isolates_collateral_recovery": True,
            "preserves_unconditional_eth_gas_joint_distribution": False,
            "historical_replay": False,
        },
        "capacity": {
            "profiles": CAPACITY_VALUES,
            "semantics": "system_wide_shared_capacity",
            "hurdle_profile": "direct_cost_only",
            "risk_cost_rate": 0.0,
            "selected_profile": None,
        },
        "confidence": {
            "primary": "stage1_only",
            "robustness": list(EXPECTED_SCENARIO_ORDER[1:]),
            "ranked": False,
            "selected": None,
        },
        "cell_order": [cell.identifier for cell in cells],
        "replications_per_cell": design.replications,
        "substantive_simulations": len(cells) * design.replications,
        "seed_ownership": {
            "registry_id": design.registry_id,
            "streams": list(SEED_STREAMS),
            "common_random_numbers": True,
            "seed_registry_sha256": seed_registry_checksum(design.replications),
        },
        "horizon": {
            "pre_shock_hours": design.pre_shock_hours,
            "post_shock_hours": design.post_shock_hours,
            "total_hours": design.total_hours,
            "confirmation_tail": False,
        },
        "recovery_definition": {
            "band": [design.lower_band, design.upper_band],
            "consecutive_hours": design.stability_hours,
            "restricted_mean_cap_hours": design.recovery_cap_hours,
        },
        "rescue_definitions": {
            "recovered_before_execution": (
                "unsafe, open, then safe before first selected attempt"
            ),
            "recovered_before_closure": (
                "unsafe, open, then safe before successful closure"
            ),
            "paired_liquidation_avoided": (
                "closed under persistent_trough and open under full_week"
            ),
            "paired_additional_liquidation": (
                "closed under full_week and open under persistent_trough"
            ),
        },
        "primary_outcomes": [
            "paired_avoided_debt_dai",
            *PRIMARY_CELL_METRICS,
        ],
        "secondary_outcomes": list(SUMMARY_METRICS),
        "contrasts": {
            "recovery": "full_week - persistent_trough",
            "capacity": [
                "26 - 14",
                "45 - 26",
                "45 - 14",
            ],
            "interactions": [
                "recovery(14) - recovery(45)",
                "recovery(26) - recovery(45)",
                "recovery(14) - recovery(26)",
            ],
            "confidence": [
                f"{scenario} - stage1_only"
                for scenario in EXPECTED_SCENARIO_ORDER[1:]
            ],
        },
        "hypotheses": ["H5a", "H5b", "H5c", "H5d"],
        "materiality": dict(design.materiality),
        "capacity_operationality": {
            "low_replication_binding_share": 0.10,
            "low_positive_demand_binding_share": 0.01,
            "low_rejection_positive_replication_share": 0.25,
            "central_any_binding": True,
            "central_maximum_attempts": 26,
        },
        "classification_hierarchy": [
            "constrained_recovery_experiment_invalid",
            "constrained_recovery_not_operational",
            "recovery_effect_capacity_dependent",
            "recovery_improves_solvency_not_peg",
            "recovery_matters_under_constrained_execution",
            "capacity_dominates_recovery",
            "no_clear_constrained_recovery_effect",
        ],
        "result_blind": True,
        "final_validation_data_used": False,
        "usdc_svb_used": False,
        "multi_collateral_execution": False,
        "runtime_adopted": False,
    }
    payload["specification_identity"] = _payload_sha256(payload)
    return payload


def write_preregistration(
    design: ConstrainedRecoveryDesign | None = None,
) -> dict[str, Any]:
    """Write the immutable specification before substantive execution."""
    owner = design or load_design()
    payload = specification_payload(owner)
    path = owner.evidence_dir / "constrained_recovery_specification.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError("Existing constrained-recovery specification differs.")
    else:
        _atomic_json(path, payload)
    output_copy = (
        owner.output_root
        / payload["experiment_identity"]
        / "preregistration_snapshot.json"
    )
    if output_copy.exists():
        if json.loads(output_copy.read_text(encoding="utf-8")) != payload:
            raise ValueError("Detailed pre-registration snapshot differs.")
    else:
        _atomic_json(output_copy, payload)
    return {
        "experiment_identity": payload["experiment_identity"],
        "specification_identity": payload["specification_identity"],
        "path": _relative(path),
        "sha256": sha256_file(path),
        "result_blind": True,
    }


def _arrival_stream(
    profile: IntegratedEmpiricalETHProfile,
    *,
    replication: int,
    horizon: int,
) -> dict[str, Any]:
    pool = load_liquidation_arrival_pool(
        profile.liquidation_demand.pool_path,
        profile.liquidation_demand.pool_sha256,
    )
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
        "checksum": _payload_sha256(
            {
                "uniform_sha256": hashlib.sha256(
                    np.asarray(uniforms, dtype="<f8").tobytes()
                ).hexdigest(),
                "count_sha256": hashlib.sha256(
                    np.asarray(counts, dtype="<i8").tobytes()
                ).hexdigest(),
            }
        ),
    }


def _demand_decision(
    *,
    step: int,
    inventory: int,
    capacity: int,
    uniform: float,
    positive_count: int,
    hurdle_probability: float,
) -> LiquidationDemandDecision:
    """Apply the empirical hurdle/count rule to pre-sampled CRN draws."""
    if inventory == 0:
        active = False
        sampled = 0
    else:
        active = bool(uniform < hurdle_probability)
        sampled = int(positive_count) if active else 0
    bounded = min(sampled, inventory)
    attempts = min(bounded, capacity)
    return LiquidationDemandDecision(
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
        inventory_not_sampled_unresolved=(
            inventory - bounded if active else 0
        ),
    )


def _max_run(values: Sequence[bool]) -> int:
    maximum = current = 0
    for value in values:
        current = current + 1 if value else 0
        maximum = max(maximum, current)
    return maximum


def _simulate_liquidation_path(
    *,
    profile: IntegratedEmpiricalETHProfile,
    base_vaults: Sequence[Any],
    initial_debt_by_vault: Mapping[int, float],
    eth_prices: np.ndarray,
    gas_costs: np.ndarray,
    arrivals: Mapping[str, Any],
    capacity_profile: str,
    capacity: int,
    pre_shock_hours: int,
) -> dict[str, Any]:
    """Run canonical liquidation mechanics and compact vault-event tracking."""
    vaults = deepcopy(list(base_vaults))
    events = {
        int(vault.vault_id): {
            "first_unsafe_hour": None,
            "first_selected_attempt_hour": None,
            "first_successful_closure_hour": None,
            "first_return_to_safety_hour": None,
        }
        for vault in vaults
    }
    arrays = {
        key: np.zeros(len(eth_prices), dtype=dtype)
        for key, dtype in {
            "liquidatable_before": "<i8",
            "newly_unsafe": "<i8",
            "sampled_arrivals": "<i8",
            "selected_attempts": "<i8",
            "successful_liquidations": "<i8",
            "failed_liquidation_attempts": "<i8",
            "capacity_rejected_opportunities": "<i8",
            "unresolved_vault_count": "<i8",
            "unresolved_tab_dai": "<f8",
            "active_bad_debt_dai": "<f8",
            "realised_bad_debt_dai": "<f8",
            "cleared_tab_dai": "<f8",
            "keeper_profit_dai": "<f8",
            "liquidation_gate_open": "?",
            "material_active_bad_debt": "?",
        }.items()
    }
    initial_debt = float(sum(vault.debt_dai for vault in vaults))
    initial_collateral = float(sum(vault.collateral_amount for vault in vaults))
    total_removed_collateral = 0.0
    total_repaid = 0.0
    closed_ids: set[int] = set()
    binding_hours = 0
    positive_demand_hours = 0
    maximum_attempts = 0
    capacity_utilisation: list[float] = []
    for step, (eth_price, gas_cost) in enumerate(
        zip(eth_prices, gas_costs, strict=True)
    ):
        price = float(eth_price)
        newly_unsafe = 0
        for vault in vaults:
            event = events[int(vault.vault_id)]
            unsafe = vault.is_active and vault.is_liquidatable(price)
            if unsafe and event["first_unsafe_hour"] is None:
                event["first_unsafe_hour"] = step
                newly_unsafe += 1
            elif (
                vault.is_active
                and not unsafe
                and event["first_unsafe_hour"] is not None
                and event["first_return_to_safety_hour"] is None
                and step > int(event["first_unsafe_hour"])
            ):
                event["first_return_to_safety_hour"] = step
        liquidatable = [
            vault
            for vault in vaults
            if vault.is_active and vault.is_liquidatable(price)
        ]
        arrays["liquidatable_before"][step] = len(liquidatable)
        arrays["newly_unsafe"][step] = newly_unsafe
        decision = _demand_decision(
            step=step,
            inventory=len(liquidatable),
            capacity=capacity,
            uniform=float(arrivals["uniforms"][step]),
            positive_count=int(arrivals["positive_counts"][step]),
            hurdle_probability=float(
                profile.liquidation_demand.hurdle_probability
            ),
        )
        arrays["sampled_arrivals"][step] = decision.sampled_demand
        arrays["selected_attempts"][step] = decision.attempt_budget
        arrays["capacity_rejected_opportunities"][
            step
        ] = decision.demand_truncated_by_capacity
        if decision.bounded_demand > 0:
            positive_demand_hours += 1
            capacity_utilisation.append(decision.attempt_budget / capacity)
        if decision.demand_truncated_by_capacity > 0:
            binding_hours += 1
        maximum_attempts = max(maximum_attempts, decision.attempt_budget)
        collateral_before = float(
            sum(vault.collateral_amount for vault in vaults if vault.is_active)
        )
        if liquidatable:
            liquidation_frame = liquidate_vaults(
                vaults,
                price,
                replace(
                    profile.bundle.base_bundle.liquidation_config,
                    gas_cost=float(gas_cost),
                    risk_cost_rate=0.0,
                    max_close_factor=1.0,
                    max_liquidations_per_step=capacity,
                ),
                bounded_demand=decision.bounded_demand,
                attempt_budget=decision.attempt_budget,
            )
            summary = summarise_liquidations(liquidation_frame)
            attempted = liquidation_frame.loc[
                liquidation_frame["attempted"].astype(bool), "vault_id"
            ]
            for vault_id in attempted:
                event = events[int(vault_id)]
                if event["first_selected_attempt_hour"] is None:
                    event["first_selected_attempt_hour"] = step
            successful = liquidation_frame.loc[
                liquidation_frame["liquidated"].astype(bool), "vault_id"
            ]
            for vault_id in successful:
                event = events[int(vault_id)]
                if event["first_successful_closure_hour"] is not None:
                    raise ValueError("Vault closed more than once.")
                event["first_successful_closure_hour"] = step
                closed_ids.add(int(vault_id))
        else:
            summary = {
                "n_attempted": 0,
                "n_liquidated": 0,
                "debt_repaid": 0.0,
                "bad_debt_realised": 0.0,
                "keeper_profit": 0.0,
            }
        if int(summary["n_attempted"]) != decision.attempt_budget:
            raise ValueError("Audit attempts differ from authoritative attempt budget.")
        collateral_after = float(
            sum(vault.collateral_amount for vault in vaults if vault.is_active)
        )
        total_removed_collateral += collateral_before - collateral_after
        total_repaid += float(summary["debt_repaid"])
        arrays["successful_liquidations"][step] = int(summary["n_liquidated"])
        arrays["failed_liquidation_attempts"][step] = (
            decision.attempt_budget - int(summary["n_liquidated"])
        )
        arrays["realised_bad_debt_dai"][step] = float(
            summary["bad_debt_realised"]
        )
        arrays["cleared_tab_dai"][step] = float(summary["debt_repaid"])
        arrays["keeper_profit_dai"][step] = float(summary["keeper_profit"])
        active = [vault for vault in vaults if vault.is_active]
        unresolved_vaults = [
            vault for vault in active if vault.is_liquidatable(price)
        ]
        unresolved = float(sum(vault.debt_dai for vault in unresolved_vaults))
        active_bad_debt = float(sum(vault.bad_debt(price) for vault in active))
        arrays["unresolved_vault_count"][step] = len(unresolved_vaults)
        arrays["unresolved_tab_dai"][step] = unresolved
        arrays["active_bad_debt_dai"][step] = active_bad_debt
        arrays["liquidation_gate_open"][step] = unresolved <= 1e-9
        arrays["material_active_bad_debt"][step] = active_bad_debt > max(
            1e-9, 1e-12 * initial_debt
        )
    final_debt = float(sum(vault.debt_dai for vault in vaults if vault.is_active))
    final_collateral = float(
        sum(vault.collateral_amount for vault in vaults if vault.is_active)
    )
    debt_error = initial_debt - final_debt - total_repaid
    collateral_error = (
        initial_collateral - final_collateral - total_removed_collateral
    )
    if abs(debt_error) > 1e-5 or abs(collateral_error) > 1e-5:
        raise ValueError("Liquidation accounting failed.")
    if maximum_attempts > capacity:
        raise ValueError("System-wide keeper capacity was exceeded.")
    rescue = {}
    final_open = {int(vault.vault_id): bool(vault.is_active) for vault in vaults}
    for vault_id, event in events.items():
        unsafe = event["first_unsafe_hour"]
        returned = event["first_return_to_safety_hour"]
        attempted = event["first_selected_attempt_hour"]
        closed = event["first_successful_closure_hour"]
        rescue[vault_id] = {
            **event,
            "initial_debt_dai": float(initial_debt_by_vault[vault_id]),
            "final_open": final_open[vault_id],
            "recovered_before_execution": bool(
                unsafe is not None
                and returned is not None
                and (attempted is None or returned < attempted)
            ),
            "recovered_before_closure": bool(
                unsafe is not None
                and returned is not None
                and (closed is None or returned < closed)
            ),
        }
    if not 0 < pre_shock_hours < len(eth_prices):
        raise ValueError("pre_shock_hours must lie inside the experiment horizon.")
    post = slice(pre_shock_hours, None)
    post_unresolved = arrays["unresolved_tab_dai"][post]
    post_active_bad_debt = arrays["active_bad_debt_dai"][post]
    post_liquidatable = arrays["liquidatable_before"][post]
    post_attempts = arrays["selected_attempts"][post]
    post_rejected = arrays["capacity_rejected_opportunities"][post]
    post_arrivals = arrays["sampled_arrivals"][post]
    post_success = arrays["successful_liquidations"][post]
    post_failed = arrays["failed_liquidation_attempts"][post]
    post_repaid = arrays["cleared_tab_dai"][post]
    post_keeper_profit = arrays["keeper_profit_dai"][post]
    post_realised_bad_debt = arrays["realised_bad_debt_dai"][post]
    cell_summary = {
        "capacity_profile": capacity_profile,
        "capacity": capacity,
        "capacity_semantics": "system_wide_shared_capacity",
        "hurdle_profile": "direct_cost_only",
        "risk_cost_rate": 0.0,
        "unsafe_vault_count": int(
            sum(event["first_unsafe_hour"] is not None for event in rescue.values())
        ),
        "peak_unsafe_share": float(post_liquidatable.max() / VAULT_COUNT),
        "newly_unsafe_count": int(arrays["newly_unsafe"][post].sum()),
        "cumulative_arrival_count": int(post_arrivals.sum()),
        "cumulative_attempts": int(post_attempts.sum()),
        "cumulative_successful_closures": int(post_success.sum()),
        "cumulative_capacity_rejected": int(post_rejected.sum()),
        "cumulative_unprofitable_attempts": int(post_failed.sum()),
        "binding_hours": int(np.count_nonzero(post_rejected > 0)),
        "positive_demand_hours": int(
            np.count_nonzero(
                arrays["selected_attempts"][post]
                + arrays["capacity_rejected_opportunities"][post]
                > 0
            )
        ),
        "mean_capacity_utilisation": (
            float(np.mean(capacity_utilisation))
            if capacity_utilisation
            else 0.0
        ),
        "maximum_capacity_utilisation": (
            float(np.max(capacity_utilisation))
            if capacity_utilisation
            else 0.0
        ),
        "maximum_attempts_one_hour": int(post_attempts.max()),
        "cumulative_debt_repaid_dai": float(post_repaid.sum()),
        "completed_liquidation_count": int(post_success.sum()),
        "unresolved_vault_count": int(
            arrays["unresolved_vault_count"][-1]
        ),
        "backlog_area_dai_hours": float(post_unresolved.sum()),
        "maximum_unresolved_tab_dai": float(post_unresolved.max()),
        "unresolved_tab_at_horizon_dai": float(post_unresolved[-1]),
        "maximum_backlog_duration": _max_run(post_unresolved > 0),
        "cumulative_realised_bad_debt_dai": float(
            post_realised_bad_debt.sum()
        ),
        "active_bad_debt_at_horizon_dai": float(post_active_bad_debt[-1]),
        "maximum_active_bad_debt_dai": float(post_active_bad_debt.max()),
        "keeper_profit_dai": float(post_keeper_profit.sum()),
        "recovered_before_execution_count": int(
            sum(item["recovered_before_execution"] for item in rescue.values())
        ),
        "recovered_before_closure_count": int(
            sum(item["recovered_before_closure"] for item in rescue.values())
        ),
        "debt_conservation_error": debt_error,
        "collateral_conservation_error": collateral_error,
        "duplicate_closure_detected": False,
        "numerical_valid": bool(
            all(np.isfinite(values).all() for values in arrays.values())
            and final_debt >= -1e-9
            and final_collateral >= -1e-9
        ),
    }
    return {
        "arrays": arrays,
        "events": rescue,
        "summary": cell_summary,
        "closed_ids": sorted(closed_ids),
    }


def _prepare_replication_streams(
    design: ConstrainedRecoveryDesign,
    profile: IntegratedEmpiricalETHProfile,
    replication: int,
) -> dict[str, Any]:
    vaults, _, vault_checksum = _normalised_initial_state(
        profile,
        seed=derive_seed(replication, "vault_sampling"),
    )
    initial_debt_by_vault = {
        int(vault.vault_id): float(vault.debt_dai) for vault in vaults
    }
    market_pool = load_market_gas_pool(
        profile.market.pool_path, profile.market.pool_sha256
    )
    market, market_provenance = sample_market_gas_blocks(
        market_pool,
        horizon=design.total_hours,
        block_length_hours=profile.market.block_length_hours,
        seed=derive_seed(replication, "market_gas_blocks"),
        pool_label=profile.market.pool_label,
    )
    arrivals = _arrival_stream(
        profile, replication=replication, horizon=design.total_hours
    )
    _, _, stage1 = load_stage1_owners()
    residual_rng = np.random.default_rng(
        derive_seed(replication, "stage1_residual_blocks")
    )
    residuals = sample_residual_blocks(
        stage1["source"],
        block_count=math.ceil(design.total_hours / 24),
        rng=residual_rng,
    )[: design.total_hours]
    seed_ownership = seed_record(replication)
    stream_components = {
        "vault_checksum": vault_checksum,
        "market_start_indexes": market_provenance["sampled_start_indexes"],
        "keeper_gas_units_seed": derive_seed(
            replication, "keeper_gas_units"
        ),
        "arrival_checksum": arrivals["checksum"],
        "residual_checksum": hashlib.sha256(
            np.asarray(residuals, dtype="<f8").tobytes()
        ).hexdigest(),
    }
    return {
        "vaults": vaults,
        "initial_debt_by_vault": initial_debt_by_vault,
        "vault_checksum": vault_checksum,
        "market": market,
        "arrivals": arrivals,
        "stage1": stage1,
        "residuals": residuals,
        "seed_ownership": seed_ownership,
        "paired_stream_checksum": _payload_sha256(stream_components),
        "stream_components": stream_components,
    }


def _pair_vault_events(
    *,
    replication: int,
    capacity_profile: str,
    capacity: int,
    confidence_scenario: str,
    persistent: Mapping[int, Mapping[str, Any]],
    full: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    if set(persistent) != set(full):
        raise ValueError("Paired vault identifiers differ.")
    avoided: list[int] = []
    additional: list[int] = []
    differences: list[float] = []
    for vault_id in sorted(persistent):
        left = persistent[vault_id]
        right = full[vault_id]
        left_closed = left["first_successful_closure_hour"] is not None
        right_closed = right["first_successful_closure_hour"] is not None
        if left_closed and not right_closed:
            avoided.append(vault_id)
        elif right_closed and not left_closed:
            additional.append(vault_id)
        if left_closed and right_closed:
            differences.append(
                float(right["first_successful_closure_hour"])
                - float(left["first_successful_closure_hour"])
            )
    values = np.asarray(differences, dtype=float)
    return {
        "replication": replication,
        "capacity_profile": capacity_profile,
        "capacity": capacity,
        "confidence_scenario": confidence_scenario,
        "paired_liquidations_avoided": len(avoided),
        "paired_additional_liquidations": len(additional),
        "paired_avoided_debt_dai": float(
            sum(persistent[item]["initial_debt_dai"] for item in avoided)
        ),
        "paired_additional_debt_dai": float(
            sum(full[item]["initial_debt_dai"] for item in additional)
        ),
        "closure_time_difference_count": len(values),
        "closure_time_difference_mean": (
            float(values.mean()) if len(values) else 0.0
        ),
        "closure_time_difference_median": (
            float(np.median(values)) if len(values) else 0.0
        ),
        "closure_time_difference_p25": (
            float(np.quantile(values, 0.25)) if len(values) else 0.0
        ),
        "closure_time_difference_p75": (
            float(np.quantile(values, 0.75)) if len(values) else 0.0
        ),
        "closure_time_positive_share": (
            float(np.mean(values > 0)) if len(values) else 0.0
        ),
        "closure_time_negative_share": (
            float(np.mean(values < 0)) if len(values) else 0.0
        ),
    }


def simulate_replication(
    replication: int,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    """Run all 24 treatment cells for one CRN replication."""
    design = load_design(config_path)
    profile = resolve_integrated_empirical_eth_profile()
    paths = build_paths(design)
    streams = _prepare_replication_streams(design, profile, replication)
    scaling = json.loads(SPARSE_SCALING_EVIDENCE.read_text(encoding="utf-8"))
    liquidation_results: dict[tuple[str, str], dict[str, Any]] = {}
    gas_stream_checksums: set[str] = set()
    for path_identifier in design.recovery_paths:
        eth_prices = paths[path_identifier]
        gas = component_gas_costs(
            sampled_market_gas_rows=streams["market"],
            simulated_eth_prices=eth_prices,
            config=replace(
                profile.gas,
                seed=derive_seed(replication, "keeper_gas_units"),
            ),
        )
        if gas.gas_cost_usd is None or gas.sampled_rows is None:
            raise ValueError("Empirical component gas owner returned no path.")
        gas_stream_checksums.add(
            _payload_sha256(
                gas.sampled_rows["gas_pool_row_id"].astype(str).tolist()
            )
        )
        for capacity_profile in design.capacities:
            capacity = CAPACITY_VALUES[capacity_profile]
            liquidation_results[(path_identifier, capacity_profile)] = (
                _simulate_liquidation_path(
                    profile=profile,
                    base_vaults=streams["vaults"],
                    initial_debt_by_vault=streams["initial_debt_by_vault"],
                    eth_prices=eth_prices,
                    gas_costs=gas.gas_cost_usd,
                    arrivals=streams["arrivals"],
                    capacity_profile=capacity_profile,
                    capacity=capacity,
                    pre_shock_hours=design.pre_shock_hours,
                )
            )
    if len(gas_stream_checksums) != 1:
        raise ValueError("Gas-unit draws differ across controlled price paths.")
    definitions = {
        item.identifier: item
        for item in design.recovery_design.path_definitions
    }
    cell_rows: list[dict[str, Any]] = []
    rescue_rows: list[dict[str, Any]] = []
    cells = build_cell_registry(design, paths)
    by_identifier = {cell.identifier: cell for cell in cells}
    for path_identifier in design.recovery_paths:
        for capacity_profile in design.capacities:
            capacity = CAPACITY_VALUES[capacity_profile]
            liquidation = liquidation_results[
                (path_identifier, capacity_profile)
            ]
            for confidence_scenario in design.confidence_scenarios:
                cell_identifier = (
                    f"{path_identifier}__capacity_{capacity}__"
                    f"{confidence_scenario}"
                )
                market = _simulate_market_scenario(
                    design=design.recovery_design,
                    definition=definitions[path_identifier],
                    eth_prices=paths[path_identifier],
                    liquidation=liquidation["arrays"],
                    innovations=streams["residuals"],
                    scenario_identifier=confidence_scenario,
                    stage1_owners=streams["stage1"],
                    peg_scale=float(
                        scaling["lagged_below_peg_gap"]["positive_q95"]
                    ),
                    eth_scale=float(
                        scaling["lagged_24h_eth_downside"]["positive_q95"]
                    ),
                    initial_vault_count=VAULT_COUNT,
                )
                summary = {
                    **market["summary"],
                    **liquidation["summary"],
                    "cell_order": by_identifier[cell_identifier].order,
                    "cell_identifier": cell_identifier,
                    "replication": replication,
                    "paired_stream_checksum": streams[
                        "paired_stream_checksum"
                    ],
                    "state_checksum": streams["vault_checksum"],
                    "recovery_path": path_identifier,
                    "capacity_profile": capacity_profile,
                    "capacity": capacity,
                    "confidence_scenario": confidence_scenario,
                }
                summary["numerical_valid"] = bool(
                    summary["numerical_valid"]
                    and market["summary"]["numerical_valid"]
                )
                cell_rows.append(summary)
                rescue_rows.append(
                    {
                        "record_type": "within_cell",
                        "replication": replication,
                        "recovery_path": path_identifier,
                        "capacity_profile": capacity_profile,
                        "capacity": capacity,
                        "confidence_scenario": confidence_scenario,
                        "unsafe_vault_count": summary["unsafe_vault_count"],
                        "recovered_before_execution": summary[
                            "recovered_before_execution_count"
                        ],
                        "recovered_before_closure": summary[
                            "recovered_before_closure_count"
                        ],
                        "unresolved_open_vaults": summary[
                            "unresolved_vault_count"
                        ],
                    }
                )
    paired_rows = []
    for capacity_profile in design.capacities:
        capacity = CAPACITY_VALUES[capacity_profile]
        persistent = liquidation_results[
            ("persistent_trough", capacity_profile)
        ]["events"]
        full = liquidation_results[("full_week", capacity_profile)]["events"]
        for confidence_scenario in design.confidence_scenarios:
            paired_rows.append(
                _pair_vault_events(
                    replication=replication,
                    capacity_profile=capacity_profile,
                    capacity=capacity,
                    confidence_scenario=confidence_scenario,
                    persistent=persistent,
                    full=full,
                )
            )
    result = {
        "schema_version": 1,
        "replication": replication,
        "seed_ownership": streams["seed_ownership"],
        "paired_stream_checksum": streams["paired_stream_checksum"],
        "stream_components": streams["stream_components"],
        "cell_rows": cell_rows,
        "rescue_rows": rescue_rows,
        "paired_rows": paired_rows,
        "simulation_count": 24,
        "result_checksum": _payload_sha256(
            {
                "replication": replication,
                "paired_stream_checksum": streams["paired_stream_checksum"],
                "cell_rows": cell_rows,
                "rescue_rows": rescue_rows,
                "paired_rows": paired_rows,
            }
        ),
    }
    return result


def _checkpoint_path(output_dir: Path, replication: int) -> Path:
    return output_dir / "checkpoints" / f"replication_{replication:03d}.json"


def _valid_checkpoint(path: Path, replication: int) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected = _payload_sha256(
            {
                "replication": replication,
                "paired_stream_checksum": payload["paired_stream_checksum"],
                "cell_rows": payload["cell_rows"],
                "rescue_rows": payload["rescue_rows"],
                "paired_rows": payload["paired_rows"],
            }
        )
        return (
            payload["replication"] == replication
            and payload["simulation_count"] == 24
            and len(payload["cell_rows"]) == 24
            and payload["result_checksum"] == expected
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False


def preflight(
    design: ConstrainedRecoveryDesign | None = None,
) -> dict[str, Any]:
    """Validate identities, storage, cells, CRN seeds and output bounds."""
    owner = design or load_design()
    profile = resolve_integrated_empirical_eth_profile()
    paths = build_paths(owner)
    cells = build_cell_registry(owner, paths)
    if experiment_identity(owner, cells) != REGISTERED_EXPERIMENT_IDENTITY:
        raise ValueError("Registered scientific experiment identity differs.")
    if profile.runtime_adopted or profile.profile_identity != PROFILE_IDENTITY:
        raise ValueError("Integrated profile crossed its opt-in boundary.")
    if profile.input_checksums != EXPECTED_INPUT_CHECKSUMS:
        raise ValueError("Protected empirical inputs changed.")
    disk = shutil.disk_usage(REPOSITORY_ROOT)
    if disk.free < owner.minimum_free_bytes:
        raise RuntimeError("Fewer than 10 GiB remain.")
    existing = sum(
        path.stat().st_size
        for path in (REPOSITORY_ROOT / "outputs/experiments").rglob("*")
        if path.is_file()
    )
    projected = owner.replications * 2_000_000
    if projected > owner.maximum_new_bytes:
        raise RuntimeError("Projected detailed output exceeds 750 MB.")
    return {
        "starting_code_parent": STARTING_CODE_PARENT,
        "experiment_identity": experiment_identity(owner, cells),
        "profile_identity": profile.profile_identity,
        "profile_checksum": profile.profile_checksum,
        "cell_count": len(cells),
        "replications_per_cell": owner.replications,
        "simulation_count": len(cells) * owner.replications,
        "path_checksums": {
            name: path_checksum(values) for name, values in paths.items()
        },
        "seed_registry_checksum": seed_registry_checksum(owner.replications),
        "free_storage_bytes": disk.free,
        "existing_experiment_output_bytes": existing,
        "projected_new_output_bytes": projected,
        "minimum_free_storage_satisfied": True,
        "runtime_adopted": False,
    }


def run_smoke(
    design: ConstrainedRecoveryDesign | None = None,
    *,
    replication: int = 0,
) -> dict[str, Any]:
    """Run one result-blind 24-cell mechanism and CRN smoke."""
    owner = design or load_design()
    result = simulate_replication(replication, owner.config_path)
    rows = pd.DataFrame(result["cell_rows"])
    expected = [cell.identifier for cell in build_cell_registry(owner)]
    if rows.sort_values("cell_order")["cell_identifier"].tolist() != expected:
        raise ValueError("Smoke cell order differs from the registry.")
    if rows["paired_stream_checksum"].nunique() != 1:
        raise ValueError("Smoke CRN ownership differs across cells.")
    if rows["state_checksum"].nunique() != 1:
        raise ValueError("Smoke vault states differ across cells.")
    if set(rows["capacity"]) != {14, 26, 45}:
        raise ValueError("Smoke capacity resolution failed.")
    if not rows["hurdle_profile"].eq("direct_cost_only").all():
        raise ValueError("Smoke used an unauthorised keeper hurdle.")
    if not rows["numerical_valid"].all():
        raise ValueError("Smoke contains numerical failure.")
    return {
        "replication": replication,
        "cell_count": len(rows),
        "paired_stream_checksum": rows["paired_stream_checksum"].iloc[0],
        "state_checksum": rows["state_checksum"].iloc[0],
        "cell_order_valid": True,
        "crn_valid": True,
        "capacity_values": sorted(rows["capacity"].unique().tolist()),
        "direct_cost_only": True,
        "stage1_primary_present": bool(
            rows["confidence_scenario"].eq("stage1_only").any()
        ),
        "numerical_valid": True,
    }


def audit_checkpoints(
    design: ConstrainedRecoveryDesign | None = None,
) -> dict[str, Any]:
    owner = design or load_design()
    identity = experiment_identity(owner)
    output_dir = owner.output_root / identity
    expected = {
        _checkpoint_path(output_dir, replication)
        for replication in range(owner.replications)
    }
    observed = set((output_dir / "checkpoints").glob("replication_*.json"))
    valid = sum(
        _valid_checkpoint(path, replication)
        for replication, path in enumerate(sorted(expected))
    )
    return {
        "experiment_identity": identity,
        "expected_checkpoints": owner.replications,
        "observed_checkpoints": len(observed),
        "valid_checkpoints": valid,
        "missing_checkpoints": len(expected - observed),
        "orphan_checkpoints": len(observed - expected),
        "duplicate_checkpoints": 0,
        "passed": (
            observed == expected and valid == owner.replications
        ),
    }


def run_matrix(
    design: ConstrainedRecoveryDesign | None = None,
    *,
    workers: int = 4,
    resume: bool = True,
    max_replications: int | None = None,
) -> dict[str, Any]:
    """Execute or resume atomic replication checkpoints."""
    owner = design or load_design()
    identity = experiment_identity(owner)
    specification = owner.evidence_dir / "constrained_recovery_specification.json"
    if not specification.is_file():
        raise ValueError("Substantive execution requires pre-registration.")
    registered = json.loads(specification.read_text(encoding="utf-8"))
    if registered["experiment_identity"] != identity:
        raise ValueError("Pre-registration identity differs from current design.")
    replication_count = (
        owner.replications
        if max_replications is None
        else int(max_replications)
    )
    if not 1 <= replication_count <= owner.replications:
        raise ValueError("max_replications lies outside the registered design.")
    output_dir = owner.output_root / identity
    tasks = []
    reused = 0
    for replication in range(replication_count):
        checkpoint = _checkpoint_path(output_dir, replication)
        if resume and _valid_checkpoint(checkpoint, replication):
            reused += 1
        else:
            tasks.append(replication)
    started = time.perf_counter()
    completed = 0
    if workers == 1:
        for replication in tasks:
            result = simulate_replication(replication, owner.config_path)
            _atomic_json(_checkpoint_path(output_dir, replication), result)
            completed += 1
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    simulate_replication, replication, owner.config_path
                ): replication
                for replication in tasks
            }
            for future in as_completed(futures):
                replication = futures[future]
                result = future.result()
                _atomic_json(_checkpoint_path(output_dir, replication), result)
                completed += 1
    wall = time.perf_counter() - started
    output_size = sum(
        path.stat().st_size for path in output_dir.rglob("*") if path.is_file()
    )
    if output_size > owner.maximum_new_bytes:
        raise RuntimeError("Detailed output exceeds the registered 750 MB cap.")
    return {
        "experiment_identity": identity,
        "worker_count": workers,
        "completed_replications": completed,
        "reused_replications": reused,
        "resumed_replications": reused if resume else 0,
        "failed_replications": 0,
        "rerun_replications": 0,
        "checkpoint_count": completed + reused,
        "completed_simulations": (completed + reused) * 24,
        "wall_time_seconds": wall,
        "throughput_simulations_per_second": (
            0.0 if wall == 0.0 else completed * 24 / wall
        ),
        "output_size_bytes": output_size,
        "free_storage_bytes": shutil.disk_usage(REPOSITORY_ROOT).free,
        "complete": completed + reused == owner.replications,
    }


def load_results(
    design: ConstrainedRecoveryDesign | None = None,
    *,
    require_complete: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load checkpointed cell, within-cell rescue and paired-vault rows."""
    owner = design or load_design()
    output_dir = owner.output_root / experiment_identity(owner)
    cell_rows: list[dict[str, Any]] = []
    rescue_rows: list[dict[str, Any]] = []
    paired_rows: list[dict[str, Any]] = []
    for replication in range(owner.replications):
        checkpoint = _checkpoint_path(output_dir, replication)
        if not _valid_checkpoint(checkpoint, replication):
            if require_complete:
                raise ValueError(f"Missing valid checkpoint: {checkpoint}.")
            continue
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        cell_rows.extend(payload["cell_rows"])
        rescue_rows.extend(payload["rescue_rows"])
        paired_rows.extend(payload["paired_rows"])
    cells = pd.DataFrame(cell_rows)
    rescue = pd.DataFrame(rescue_rows)
    paired = pd.DataFrame(paired_rows)
    expected = owner.replications * 24
    if require_complete and len(cells) != expected:
        raise ValueError("Cell result count differs from 3,072.")
    if not cells.empty:
        for replication, group in cells.groupby("replication"):
            if (
                group["paired_stream_checksum"].nunique() != 1
                or group["state_checksum"].nunique() != 1
                or len(group) != 24
            ):
                raise ValueError(
                    f"CRN ownership failed for replication {replication}."
                )
        cells = cells.sort_values(
            ["cell_order", "replication"], kind="mergesort"
        ).reset_index(drop=True)
    return cells, rescue, paired


def _distribution(values: Iterable[float]) -> dict[str, float]:
    array = np.asarray(list(values), dtype=float)
    count = len(array)
    if count == 0:
        raise ValueError("Cannot summarise an empty distribution.")
    mean = float(array.mean())
    se = float(array.std(ddof=1) / math.sqrt(count)) if count > 1 else 0.0
    return {
        "mean": mean,
        "standard_error": se,
        "ci95_lower": mean - 1.96 * se,
        "ci95_upper": mean + 1.96 * se,
        "median": float(np.median(array)),
        "p05": float(np.quantile(array, 0.05)),
        "p25": float(np.quantile(array, 0.25)),
        "p75": float(np.quantile(array, 0.75)),
        "p90": float(np.quantile(array, 0.90)),
        "p95": float(np.quantile(array, 0.95)),
        "minimum": float(array.min()),
        "maximum": float(array.max()),
        "positive_share": float(np.mean(array > 0)),
    }


def cell_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_columns = [
        "cell_order",
        "cell_identifier",
        "recovery_path",
        "capacity_profile",
        "capacity",
        "confidence_scenario",
    ]
    for key, group in frame.groupby(group_columns, sort=False):
        failures = int((~group["numerical_valid"].astype(bool)).sum())
        for metric in SUMMARY_METRICS:
            rows.append(
                {
                    **dict(zip(group_columns, key, strict=True)),
                    "metric": metric,
                    "valid_replication_count": int(len(group) - failures),
                    **_distribution(group[metric]),
                    "censoring_count": (
                        int(group["right_censored"].sum())
                        if metric == "restricted_mean_recovery_time"
                        else 0
                    ),
                    "numerical_failure_count": failures,
                }
            )
    return pd.DataFrame(rows)


def _paired_contrast_rows(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    metrics: Sequence[str],
    metadata: Mapping[str, Any],
) -> list[dict[str, Any]]:
    paired = left.merge(
        right,
        on="replication",
        suffixes=("_left", "_right"),
        validate="one_to_one",
    )
    rows = []
    for metric in metrics:
        differences = (
            paired[f"{metric}_left"].to_numpy(dtype=float)
            - paired[f"{metric}_right"].to_numpy(dtype=float)
        )
        rows.append(
            {
                **metadata,
                "metric": metric,
                "paired_count": len(paired),
                **_distribution(differences),
                "discordant_positive_count": int(
                    np.count_nonzero(differences > 0)
                ),
                "discordant_negative_count": int(
                    np.count_nonzero(differences < 0)
                ),
            }
        )
    return rows


def recovery_contrasts(
    frame: pd.DataFrame,
    paired: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for capacity_profile in CAPACITY_ORDER:
        capacity = CAPACITY_VALUES[capacity_profile]
        for scenario in EXPECTED_SCENARIO_ORDER:
            left = frame.loc[
                frame["recovery_path"].eq("full_week")
                & frame["capacity_profile"].eq(capacity_profile)
                & frame["confidence_scenario"].eq(scenario)
            ]
            right = frame.loc[
                frame["recovery_path"].eq("persistent_trough")
                & frame["capacity_profile"].eq(capacity_profile)
                & frame["confidence_scenario"].eq(scenario)
            ]
            pair_group = paired.loc[
                paired["capacity_profile"].eq(capacity_profile)
                & paired["confidence_scenario"].eq(scenario)
            ]
            augmented_left = left.merge(
                pair_group,
                on=[
                    "replication",
                    "capacity_profile",
                    "capacity",
                    "confidence_scenario",
                ],
                how="left",
                validate="one_to_one",
            )
            for metric in (
                "paired_liquidations_avoided",
                "paired_additional_liquidations",
                "paired_avoided_debt_dai",
                "paired_additional_debt_dai",
                "closure_time_difference_mean",
            ):
                augmented_left[metric] = pair_group.set_index("replication").loc[
                    augmented_left["replication"], metric
                ].to_numpy()
                right = right.copy()
                right[metric] = 0.0
            rows.extend(
                _paired_contrast_rows(
                    augmented_left,
                    right,
                    metrics=RECOVERY_CONTRAST_METRICS,
                    metadata={
                        "capacity_profile": capacity_profile,
                        "capacity": capacity,
                        "confidence_scenario": scenario,
                        "contrast": "full_week - persistent_trough",
                    },
                )
            )
    return pd.DataFrame(rows)


def capacity_contrasts(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for path_identifier in RECOVERY_PATH_ORDER:
        for scenario in EXPECTED_SCENARIO_ORDER:
            for left_profile, right_profile in CAPACITY_CONTRASTS:
                left = frame.loc[
                    frame["recovery_path"].eq(path_identifier)
                    & frame["capacity_profile"].eq(left_profile)
                    & frame["confidence_scenario"].eq(scenario)
                ]
                right = frame.loc[
                    frame["recovery_path"].eq(path_identifier)
                    & frame["capacity_profile"].eq(right_profile)
                    & frame["confidence_scenario"].eq(scenario)
                ]
                rows.extend(
                    _paired_contrast_rows(
                        left,
                        right,
                        metrics=SUMMARY_METRICS,
                        metadata={
                            "recovery_path": path_identifier,
                            "confidence_scenario": scenario,
                            "capacity_contrast": (
                                f"{CAPACITY_VALUES[left_profile]} - "
                                f"{CAPACITY_VALUES[right_profile]}"
                            ),
                            "left_capacity_profile": left_profile,
                            "right_capacity_profile": right_profile,
                        },
                    )
                )
    return pd.DataFrame(rows)


def interaction_contrasts(
    recovery: pd.DataFrame,
    design: ConstrainedRecoveryDesign,
) -> pd.DataFrame:
    rows = []
    metric_thresholds = {
        "paired_avoided_debt_dai": design.materiality[
            "paired_avoided_debt_dai"
        ],
        "backlog_area_dai_hours": design.materiality[
            "backlog_area_dai_hours"
        ],
        "maximum_unresolved_tab_dai": design.materiality[
            "maximum_unresolved_tab_dai"
        ],
        "below_peg_burden": design.materiality["below_peg_burden"],
        "restricted_mean_recovery_time": design.materiality[
            "restricted_mean_recovery_time_hours"
        ],
    }
    cells, _, paired = load_results(design)
    for scenario in EXPECTED_SCENARIO_ORDER:
        for left_profile, right_profile in INTERACTION_CONTRASTS:
            left_capacity = CAPACITY_VALUES[left_profile]
            right_capacity = CAPACITY_VALUES[right_profile]
            for metric, threshold in metric_thresholds.items():
                if metric.startswith("paired_"):
                    source = paired
                    left = source.loc[
                        source["confidence_scenario"].eq(scenario)
                        & source["capacity_profile"].eq(left_profile),
                        ["replication", metric],
                    ]
                    right = source.loc[
                        source["confidence_scenario"].eq(scenario)
                        & source["capacity_profile"].eq(right_profile),
                        ["replication", metric],
                    ]
                else:
                    recovery_metric = recovery.loc[
                        recovery["confidence_scenario"].eq(scenario)
                        & recovery["metric"].eq(metric)
                    ]
                    # Reconstruct replication-level path differences.
                    left_full = cells.loc[
                        cells["recovery_path"].eq("full_week")
                        & cells["capacity_profile"].eq(left_profile)
                        & cells["confidence_scenario"].eq(scenario),
                        ["replication", metric],
                    ]
                    left_persistent = cells.loc[
                        cells["recovery_path"].eq("persistent_trough")
                        & cells["capacity_profile"].eq(left_profile)
                        & cells["confidence_scenario"].eq(scenario),
                        ["replication", metric],
                    ]
                    right_full = cells.loc[
                        cells["recovery_path"].eq("full_week")
                        & cells["capacity_profile"].eq(right_profile)
                        & cells["confidence_scenario"].eq(scenario),
                        ["replication", metric],
                    ]
                    right_persistent = cells.loc[
                        cells["recovery_path"].eq("persistent_trough")
                        & cells["capacity_profile"].eq(right_profile)
                        & cells["confidence_scenario"].eq(scenario),
                        ["replication", metric],
                    ]
                    left = left_full.merge(
                        left_persistent,
                        on="replication",
                        suffixes=("_full", "_persistent"),
                    )
                    left[metric] = (
                        left[f"{metric}_full"] - left[f"{metric}_persistent"]
                    )
                    left = left[["replication", metric]]
                    right = right_full.merge(
                        right_persistent,
                        on="replication",
                        suffixes=("_full", "_persistent"),
                    )
                    right[metric] = (
                        right[f"{metric}_full"] - right[f"{metric}_persistent"]
                    )
                    right = right[["replication", metric]]
                merged = left.merge(
                    right,
                    on="replication",
                    suffixes=("_left", "_right"),
                    validate="one_to_one",
                )
                differences = (
                    merged[f"{metric}_left"].to_numpy(dtype=float)
                    - merged[f"{metric}_right"].to_numpy(dtype=float)
                )
                distribution = _distribution(differences)
                rows.append(
                    {
                        "confidence_scenario": scenario,
                        "interaction_contrast": (
                            f"recovery({left_capacity}) - "
                            f"recovery({right_capacity})"
                        ),
                        "metric": metric,
                        **distribution,
                        "materiality_threshold": threshold,
                        "materiality_flag": abs(distribution["mean"]) >= threshold,
                        "interval_excludes_zero": (
                            distribution["ci95_lower"] > 0
                            or distribution["ci95_upper"] < 0
                        ),
                        "interpretation": (
                            "capacity-dependent recovery effect"
                            if abs(distribution["mean"]) >= threshold
                            else "below registered materiality"
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _contrast_row(
    frame: pd.DataFrame,
    *,
    capacity: int,
    scenario: str,
    metric: str,
) -> pd.Series:
    return frame.loc[
        frame["capacity"].eq(capacity)
        & frame["confidence_scenario"].eq(scenario)
        & frame["metric"].eq(metric)
    ].iloc[0]


def _support_classification(support_count: int) -> str:
    """Map the pre-registered three-capacity support count."""
    if support_count >= 2:
        return "supported"
    if support_count == 1:
        return "partially_supported"
    return "not_supported"


def _overall_classification(
    *,
    invalid: bool,
    low_operational: bool,
    opportunity: bool,
    h5a: str,
    h5b: str,
    h5c: str,
    capacity_mechanism: str,
) -> str:
    """Apply the immutable ordered classification hierarchy."""
    if invalid:
        return "constrained_recovery_experiment_invalid"
    if not low_operational or not opportunity:
        return "constrained_recovery_not_operational"
    if h5a in {"supported", "partially_supported"} and h5c == "present":
        return "recovery_effect_capacity_dependent"
    if h5a in {"supported", "partially_supported"} and h5b == "not_supported":
        return "recovery_improves_solvency_not_peg"
    if h5a == "supported" and h5b == "supported" and h5c != "present":
        return "recovery_matters_under_constrained_execution"
    if (
        h5a == "not_supported"
        and h5b == "not_supported"
        and capacity_mechanism != "no_clear_capacity_effect"
    ):
        return "capacity_dominates_recovery"
    return "no_clear_constrained_recovery_effect"


def classify_results(
    *,
    design: ConstrainedRecoveryDesign,
    cells: pd.DataFrame,
    paired: pd.DataFrame,
    recovery: pd.DataFrame,
    capacity: pd.DataFrame,
    interactions: pd.DataFrame,
) -> dict[str, Any]:
    """Apply the fixed operationality, H5 and overall hierarchy."""
    low = cells.loc[
        cells["capacity"].eq(14)
        & cells["confidence_scenario"].eq("stage1_only")
    ]
    low_binding_replication_share = float(
        np.mean(low["binding_hours"] > 0)
    )
    low_positive_demand_binding_share = float(
        low["binding_hours"].sum()
        / max(low["positive_demand_hours"].sum(), 1)
    )
    low_rejection_positive_share = float(
        np.mean(low["cumulative_capacity_rejected"] > 0)
    )
    low_operational = bool(
        low_binding_replication_share >= 0.10
        or low_positive_demand_binding_share >= 0.01
        or low_rejection_positive_share >= 0.25
    )
    central = cells.loc[
        cells["capacity"].eq(26)
        & cells["confidence_scenario"].eq("stage1_only")
    ]
    central_operational = bool(
        (central["binding_hours"] > 0).any()
        and (central["maximum_attempts_one_hour"] == 26).any()
    )
    opportunity = bool(cells["maximum_unresolved_tab_dai"].gt(0).any())
    h5a_support_count = 0
    for capacity_value in (14, 26, 45):
        avoided = _contrast_row(
            recovery,
            capacity=capacity_value,
            scenario="stage1_only",
            metric="paired_avoided_debt_dai",
        )
        backlog = _contrast_row(
            recovery,
            capacity=capacity_value,
            scenario="stage1_only",
            metric="backlog_area_dai_hours",
        )
        bad_debt = _contrast_row(
            recovery,
            capacity=capacity_value,
            scenario="stage1_only",
            metric="cumulative_realised_bad_debt_dai",
        )
        if (
            avoided["mean"] > 0
            and avoided["positive_share"] >= 0.25
            and backlog["ci95_lower"] <= 0
            and bad_debt["ci95_lower"] <= 0
        ):
            h5a_support_count += 1
    h5a = _support_classification(h5a_support_count)
    h5b_support_count = 0
    for capacity_value in (14, 26, 45):
        burden = _contrast_row(
            recovery,
            capacity=capacity_value,
            scenario="stage1_only",
            metric="below_peg_burden",
        )
        rmst = _contrast_row(
            recovery,
            capacity=capacity_value,
            scenario="stage1_only",
            metric="restricted_mean_recovery_time",
        )
        improvement = burden["ci95_upper"] < 0 or rmst["ci95_upper"] < 0
        opposite = burden["ci95_lower"] > 0 or rmst["ci95_lower"] > 0
        if improvement and not opposite:
            h5b_support_count += 1
    h5b = _support_classification(h5b_support_count)
    primary_interactions = interactions.loc[
        interactions["confidence_scenario"].eq("stage1_only")
    ]
    if primary_interactions["interval_excludes_zero"].any():
        h5c = "present"
    elif primary_interactions["materiality_flag"].any():
        h5c = "weak"
    else:
        h5c = "not_present"
    active_decoupling = 0
    for scenario in EXPECTED_SCENARIO_ORDER[1:]:
        scenario_rows = recovery.loc[
            recovery["confidence_scenario"].eq(scenario)
        ]
        avoided_improves = bool(
            scenario_rows.loc[
                scenario_rows["metric"].eq("paired_avoided_debt_dai"),
                "mean",
            ].gt(0).any()
        )
        lower_is_better_improves = bool(
            scenario_rows.loc[
                scenario_rows["metric"].isin(
                    [
                        "backlog_area_dai_hours",
                        "maximum_unresolved_tab_dai",
                        "cumulative_realised_bad_debt_dai",
                    ]
                ),
                "mean",
            ].lt(0).any()
        )
        solvency_improves = avoided_improves or lower_is_better_improves
        peg_improves = bool(
            (
                scenario_rows.loc[
                    scenario_rows["metric"].isin(
                        [
                            "below_peg_burden",
                            "restricted_mean_recovery_time",
                        ]
                    ),
                    "ci95_upper",
                ]
                < 0
            ).any()
        )
        confidence_active = bool(
            cells.loc[
                cells["confidence_scenario"].eq(scenario),
                ["hours_recovery_gate_closed", "cumulative_panic_contribution"],
            ].to_numpy(dtype=float).max()
            > 0
        )
        if solvency_improves and not peg_improves and confidence_active:
            active_decoupling += 1
    h5d = "present" if active_decoupling >= 2 else "not_present"
    high_low = capacity.loc[
        capacity["capacity_contrast"].eq("45 - 14")
        & capacity["metric"].isin(
            [
                "backlog_area_dai_hours",
                "maximum_unresolved_tab_dai",
            ]
        )
    ]
    clearly_lower = (
        high_low.assign(clear=high_low["ci95_upper"] < 0)
        .groupby(["recovery_path", "metric"])["clear"]
        .sum()
    )
    if (clearly_lower >= 3).any():
        capacity_mechanism = "higher_capacity_reduces_backlog"
    else:
        timing = capacity.loc[
            capacity["metric"].isin(
                [
                    "cumulative_attempts",
                    "completed_liquidation_count",
                    "backlog_area_dai_hours",
                ]
            ),
            "mean",
        ].abs().max()
        solvency = capacity.loc[
            capacity["metric"].isin(
                [
                    "cumulative_realised_bad_debt_dai",
                    "unresolved_tab_at_horizon_dai",
                ]
            ),
            "mean",
        ].abs().max()
        if timing > 0 and solvency <= 1e-9:
            capacity_mechanism = "capacity_changes_timing_not_solvency"
        elif timing > 0:
            capacity_mechanism = "capacity_effect_mixed"
        else:
            capacity_mechanism = "no_clear_capacity_effect"
    numerical_failure_by_cell = (
        cells.assign(failure=~cells["numerical_valid"].astype(bool))
        .groupby("cell_identifier")["failure"]
        .mean()
    )
    invalid = bool(
        numerical_failure_by_cell.gt(0.01).any()
        or cells["paired_stream_checksum"].isna().any()
        or cells["duplicate_closure_detected"].any()
    )
    overall = _overall_classification(
        invalid=invalid,
        low_operational=low_operational,
        opportunity=opportunity,
        h5a=h5a,
        h5b=h5b,
        h5c=h5c,
        capacity_mechanism=capacity_mechanism,
    )
    return {
        "capacity_operationality": {
            "low_capacity_operational": low_operational,
            "low_binding_replication_share": low_binding_replication_share,
            "low_positive_demand_binding_share": (
                low_positive_demand_binding_share
            ),
            "low_rejection_positive_replication_share": (
                low_rejection_positive_share
            ),
            "central_capacity_operational": central_operational,
            "meaningful_unresolved_inventory": opportunity,
        },
        "H5a": h5a,
        "H5b": h5b,
        "H5c": h5c,
        "H5d": h5d,
        "capacity_mechanism_classification": capacity_mechanism,
        "overall_classification": overall,
        "capacity_selected": None,
        "confidence_scenario_ranked": False,
        "confidence_scenario_selected": None,
        "runtime_adopted": False,
    }


def _registry_frame(
    design: ConstrainedRecoveryDesign,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "order": cell.order,
                "cell_identifier": cell.identifier,
                "recovery_path": cell.recovery_path,
                "path_checksum": cell.path_checksum,
                "capacity_profile": cell.capacity_profile,
                "capacity": cell.capacity,
                "capacity_semantics": "system_wide_shared_capacity",
                "hurdle_profile": "direct_cost_only",
                "confidence_scenario": cell.confidence_scenario,
                "scenario_checksum": cell.scenario_checksum,
                "integrated_profile_checksum": design.profile_sha256,
                "replication_count": cell.replication_count,
                "row_checksum": cell.row_checksum,
            }
            for cell in build_cell_registry(design)
        ]
    )


def _rescue_evidence(
    rescue: pd.DataFrame,
    paired: pd.DataFrame,
) -> pd.DataFrame:
    within_rows = []
    for key, group in rescue.groupby(
        [
            "recovery_path",
            "capacity_profile",
            "capacity",
            "confidence_scenario",
        ],
        sort=False,
    ):
        metadata = dict(
            zip(
                [
                    "recovery_path",
                    "capacity_profile",
                    "capacity",
                    "confidence_scenario",
                ],
                key,
                strict=True,
            )
        )
        for metric in (
            "unsafe_vault_count",
            "recovered_before_execution",
            "recovered_before_closure",
            "unresolved_open_vaults",
        ):
            within_rows.append(
                {
                    "record_type": "within_cell",
                    **metadata,
                    "metric": metric,
                    "replication_count": len(group),
                    **_distribution(group[metric]),
                }
            )
    paired_rows = []
    for key, group in paired.groupby(
        ["capacity_profile", "capacity", "confidence_scenario"], sort=False
    ):
        metadata = dict(
            zip(
                ["capacity_profile", "capacity", "confidence_scenario"],
                key,
                strict=True,
            )
        )
        for metric in (
            "paired_liquidations_avoided",
            "paired_additional_liquidations",
            "paired_avoided_debt_dai",
            "paired_additional_debt_dai",
            "closure_time_difference_mean",
        ):
            paired_rows.append(
                {
                    "record_type": "paired_recovery",
                    "recovery_path": "full_week - persistent_trough",
                    **metadata,
                    "metric": metric,
                    "replication_count": len(group),
                    **_distribution(group[metric]),
                }
            )
    return pd.DataFrame(within_rows + paired_rows)


def build_evidence_payloads(
    *,
    design: ConstrainedRecoveryDesign,
    benchmark: Mapping[str, Any],
) -> dict[str, bytes]:
    """Build deterministic compact evidence from complete checkpoints."""
    specification_path = (
        design.evidence_dir / "constrained_recovery_specification.json"
    )
    if not specification_path.is_file():
        raise ValueError("Missing immutable pre-registration.")
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    if specification != specification_payload(design):
        raise ValueError("Scientific specification changed after pre-registration.")
    cells, rescue, paired = load_results(design)
    summaries = cell_summary(cells)
    recovery = recovery_contrasts(cells, paired)
    capacity = capacity_contrasts(cells)
    interactions = interaction_contrasts(recovery, design)
    decision = classify_results(
        design=design,
        cells=cells,
        paired=paired,
        recovery=recovery,
        capacity=capacity,
        interactions=interactions,
    )
    decision.update(
        {
            "schema_version": 1,
            "qualitative_unbounded_comparison": (
                "The committed legacy unbounded experiment liquidated nearly "
                "all unsafe vaults immediately; this design tests the missing "
                "empirical-arrival and constrained-capacity waiting channel "
                "without a formal cross-experiment estimate."
            ),
            "unresolved_caveats": [
                "Controlled ETH paths break unconditional ETH-return/gas dependence.",
                "Shared keeper capacities are partially identified.",
                "Oracle delay and population robustness remain unresolved.",
            ],
            "authorised_next_boundary": (
                "freeze_multi_collateral_empirical_inputs_and_validate_shared_capacity_contract"
                if decision["overall_classification"]
                != "constrained_recovery_not_operational"
                else "constrained_recovery_design_review_without_tuning"
            ),
            "no_parameter_recalibration": True,
            "no_positive_hurdle": True,
            "no_capacity_selection": True,
            "no_confidence_selection": True,
        }
    )
    checkpoint = audit_checkpoints(design)
    reproducibility = {
        "schema_version": 1,
        "starting_code_parent": STARTING_CODE_PARENT,
        "scientific_code_identity": scientific_code_identity(),
        "experiment_identity": experiment_identity(design),
        "specification_sha256": sha256_file(specification_path),
        "integrated_profile_identity": design.profile_identity,
        "input_checksums": _source_checksums(
            resolve_integrated_empirical_eth_profile()
        ),
        "shock_sha256": EXPECTED_SHOCK_CHECKSUM,
        "path_checksums": EXPECTED_PATH_CHECKSUMS,
        "keeper_registry_sha256": EXPECTED_KEEPER_REGISTRY_SHA256,
        "confidence_registry_sha256": EXPECTED_CONFIDENCE_REGISTRY_SHA256,
        "seed_registry_sha256": seed_registry_checksum(design.replications),
        "crn_audit": {
            "passed": bool(
                cells.groupby("replication")["paired_stream_checksum"]
                .nunique()
                .eq(1)
                .all()
            ),
            "initial_vault_states_shared": bool(
                cells.groupby("replication")["state_checksum"]
                .nunique()
                .eq(1)
                .all()
            ),
            "replications": design.replications,
        },
        "checkpoint_audit": checkpoint,
        "completed_simulations": len(cells),
        "expected_simulations": 3072,
        "numerical_failures": int(
            (~cells["numerical_valid"].astype(bool)).sum()
        ),
        "result_checksums": {
            "cell_rows": _payload_sha256(cells.to_dict("records")),
            "paired_rows": _payload_sha256(paired.to_dict("records")),
        },
        "final_validation_data_used": False,
        "usdc_svb_used": False,
        "multi_collateral_execution": False,
        "parameter_calibration": False,
        "runtime_adopted": False,
    }
    benchmark_payload = {
        "schema_version": 1,
        **dict(benchmark),
        "host_dependent": True,
    }
    payloads = {
        "constrained_recovery_registry.csv": _csv_bytes(
            _registry_frame(design)
        ),
        "constrained_recovery_cell_summary.csv": _csv_bytes(summaries),
        "constrained_recovery_vault_rescue.csv": _csv_bytes(
            _rescue_evidence(rescue, paired)
        ),
        "constrained_recovery_recovery_contrasts.csv": _csv_bytes(recovery),
        "constrained_recovery_capacity_contrasts.csv": _csv_bytes(capacity),
        "constrained_recovery_interactions.csv": _csv_bytes(interactions),
        "constrained_recovery_decision.json": (
            json.dumps(decision, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
        "constrained_recovery_reproducibility.json": (
            json.dumps(reproducibility, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
        "constrained_recovery_benchmark.json": (
            json.dumps(benchmark_payload, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
    }
    return payloads


def write_evidence(
    *,
    design: ConstrainedRecoveryDesign | None = None,
    benchmark: Mapping[str, Any],
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Write compact evidence atomically and register it in the manifest."""
    owner = design or load_design()
    first = build_evidence_payloads(design=owner, benchmark=benchmark)
    second = build_evidence_payloads(design=owner, benchmark=benchmark)
    if first != second:
        raise ValueError("Non-host-dependent evidence is not deterministic.")
    for name, payload in first.items():
        _atomic_bytes(owner.evidence_dir / name, payload)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    retained = [
        record
        for record in manifest["artefacts"]
        if not str(record["path"]).startswith(
            "data/provenance/experiments/constrained_recovery/"
        )
    ]
    all_names = ("constrained_recovery_specification.json", *first.keys())
    records = []
    for name in all_names:
        path = owner.evidence_dir / name
        records.append(
            {
                "classification": (
                    "pre_registered_constrained_eth_recovery_experiment"
                ),
                "path": _relative(path),
                "runtime_adopted": False,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    updated = {
        **manifest,
        "artefact_count": len(retained) + len(records),
        "artefacts": sorted(retained + records, key=lambda row: row["path"]),
        "purpose": (
            "Content-addressed experimental evidence; no keeper capacity or "
            "confidence scenario is selected or adopted."
        ),
    }
    _atomic_json(manifest_path, updated)
    return {
        "experiment_identity": experiment_identity(owner),
        "artefact_count": len(records),
        "checksums": {
            name: sha256_file(owner.evidence_dir / name)
            for name in all_names
        },
        "manifest_sha256": sha256_file(manifest_path),
        "deterministic_reconstruction": True,
    }


def validate_evidence(
    design: ConstrainedRecoveryDesign | None = None,
) -> dict[str, Any]:
    """Validate compact schemas, registration and experimental boundaries."""
    owner = design or load_design()
    missing = [
        name for name in EVIDENCE_FILENAMES
        if not (owner.evidence_dir / name).is_file()
    ]
    if missing:
        raise ValueError(f"Missing constrained-recovery evidence: {missing}.")
    registry = pd.read_csv(
        owner.evidence_dir / "constrained_recovery_registry.csv"
    )
    summary = pd.read_csv(
        owner.evidence_dir / "constrained_recovery_cell_summary.csv"
    )
    decision = json.loads(
        (
            owner.evidence_dir / "constrained_recovery_decision.json"
        ).read_text(encoding="utf-8")
    )
    reproducibility = json.loads(
        (
            owner.evidence_dir / "constrained_recovery_reproducibility.json"
        ).read_text(encoding="utf-8")
    )
    if (
        len(registry) != 24
        or registry["cell_identifier"].nunique() != 24
        or set(registry["capacity"]) != {14, 26, 45}
        or not registry["hurdle_profile"].eq("direct_cost_only").all()
    ):
        raise ValueError("Constrained-recovery registry is incomplete.")
    if set(summary["valid_replication_count"]) != {128}:
        raise ValueError("Cell evidence lacks 128 valid replications.")
    if (
        reproducibility["completed_simulations"] != 3072
        or not reproducibility["crn_audit"]["passed"]
        or not reproducibility["checkpoint_audit"]["passed"]
        or reproducibility["numerical_failures"] != 0
        or reproducibility["final_validation_data_used"]
        or reproducibility["usdc_svb_used"]
        or reproducibility["multi_collateral_execution"]
        or reproducibility["runtime_adopted"]
        or decision["capacity_selected"] is not None
        or decision["confidence_scenario_selected"] is not None
    ):
        raise ValueError("Evidence crossed its registered boundary.")
    manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    records = {row["path"]: row for row in manifest["artefacts"]}
    for name in EVIDENCE_FILENAMES:
        path = owner.evidence_dir / name
        relative = _relative(path)
        if (
            relative not in records
            or records[relative]["sha256"] != sha256_file(path)
        ):
            raise ValueError(f"Unregistered constrained evidence: {relative}.")
    return {
        "experiment_identity": experiment_identity(owner),
        "cell_count": len(registry),
        "simulation_count": reproducibility["completed_simulations"],
        "overall_classification": decision["overall_classification"],
        "deterministic_reconstruction": True,
        "runtime_adopted": False,
    }
