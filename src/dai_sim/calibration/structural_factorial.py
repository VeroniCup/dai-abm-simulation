"""Objective-blind structural factorial diagnosis for persistent confidence.

The module owns the fixed 2^3 diagnostic experiment over historical vault
state, residual isolation and the unresolved-backlog recovery gate.  It reuses
the committed baseline and single-factor event-replication streams, executes
only the four missing interaction cells, and never ranks or selects candidates,
cells, parameters or a production specification.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import time
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file
from dai_sim.inputs.liquidations import LiquidationDemandProcess
from dai_sim.inputs.vaults import (
    DEFAULT_TRANCHE_B_CONFIG_PATH,
    load_tranche_b_configuration,
)

from . import simulated_moments_search as search
from .event_simulation import (
    ConditionalEventSimulationConfig,
    _liquidation_demand_config,
    load_stage1_owners,
)
from .market import CONFIDENCE_EVIDENCE
from .partial_identification import (
    NATURAL_SUPPORTS,
    NUMERICAL_BOUND_LIMIT,
    construct_mc_interval,
)
from .simulated_moments import STAGE2_ACTIVE_MOMENTS
from .simulated_moments_diagnostics import (
    MEAN_MOMENTS,
    analytic_contrast_mcse,
    analytic_equal_event_mcse,
)
from . import structural_incompatibility as structural


SCHEMA_VERSION = 1
FACTOR_ORDER = (
    "A_vault_state",
    "B_residual_process",
    "C_backlog_gate",
)
CELL_ORDER = ("000", "100", "010", "001", "110", "101", "011", "111")
REUSED_CELLS = ("000", "100", "010", "001")
NEW_CELLS = ("110", "101", "011", "111")
EFFECT_ORDER = ("A", "B", "C", "AB", "AC", "BC", "ABC")
INTERACTION_CELLS = ("110", "101", "011", "111")
EVENT_COUNT = structural.EVENT_COUNT
REPLICATION_COUNT = structural.REPLICATION_COUNT
PANEL_INDICES = structural.PANEL_INDICES
PANEL_SHA256 = structural.PANEL_SHA256
REGISTRY_A = structural.REGISTRY_A
STRUCTURAL_DECISION_PATH = (
    CONFIDENCE_EVIDENCE / "structural_incompatibility_decision.json"
)
STRUCTURAL_REGISTRY_PATH = CONFIDENCE_EVIDENCE / "structural_variant_registry.json"
STRUCTURAL_REPRODUCIBILITY_PATH = (
    CONFIDENCE_EVIDENCE / "structural_incompatibility_reproducibility.json"
)
INITIAL_STATE_PATH = CONFIDENCE_EVIDENCE / "conditional_initial_state.json"
RESIDUAL_PATH = CONFIDENCE_EVIDENCE / "stage1_residual_summary.json"
RECOVERY_GATE_PATH = CONFIDENCE_EVIDENCE / "recovery_gate_specification.json"
EVENT_CATALOGUE_PATH = CONFIDENCE_EVIDENCE / "event_catalogue.csv"
SEED_REGISTRY_PATH = CONFIDENCE_EVIDENCE / "seed_registry.json"
STRUCTURAL_ROOT = structural.DEFAULT_ROOT
DEFAULT_PARENT = (
    REPOSITORY_ROOT
    / "outputs/diagnostics/calibration/confidence/structural_factorial"
)
MINIMUM_FREE_BYTES = 10 * 1024**3
MAX_NEW_STORAGE_BYTES = 500 * 1024**2
PROJECTED_STORAGE_BYTES = 160 * 1024**2
EXPECTED_REUSED_EVALUATIONS = (
    len(REUSED_CELLS) * len(PANEL_INDICES) * EVENT_COUNT * REPLICATION_COUNT
)
EXPECTED_NEW_EVALUATIONS = (
    len(NEW_CELLS) * len(PANEL_INDICES) * EVENT_COUNT * REPLICATION_COUNT
)
EXPECTED_TOTAL_EVALUATIONS = (
    len(CELL_ORDER) * len(PANEL_INDICES) * EVENT_COUNT * REPLICATION_COUNT
)
EXPECTED_NEW_CHECKPOINTS = len(NEW_CELLS) * len(PANEL_INDICES)
PRECISION_SCHEMA_VERSION = 1
PRECISION_PREFIXES_R64 = (16, 32, 48, 64)
PRECISION_FINAL_REPLICATION_COUNT = 128
PRECISION_ADDED_REPLICATIONS = tuple(range(64, 128))
PRECISION_EFFECTS = ("C", "BC")
PRECISION_MOMENT = "failed_recovery_attempts_mean"
PRECISION_RELATIVE_TOLERANCE = 0.15
PRECISION_MINIMUM_PASS_COUNT = 15
PRECISION_MAX_NEW_STORAGE_BYTES = 300 * 1024**2
PROJECTED_PRECISION_STORAGE_BYTES = 150 * 1024**2
EXPECTED_PRECISION_REUSED_EVALUATIONS = EXPECTED_TOTAL_EVALUATIONS
EXPECTED_PRECISION_NEW_EVALUATIONS = (
    len(CELL_ORDER)
    * len(PANEL_INDICES)
    * EVENT_COUNT
    * len(PRECISION_ADDED_REPLICATIONS)
)
EXPECTED_PRECISION_TOTAL_EVALUATIONS = (
    len(CELL_ORDER)
    * len(PANEL_INDICES)
    * EVENT_COUNT
    * PRECISION_FINAL_REPLICATION_COUNT
)
EXPECTED_PRECISION_CHECKPOINTS = len(CELL_ORDER) * len(PANEL_INDICES)
PRECISION_EVIDENCE_NAMES = (
    "structural_factorial_precision_specification.json",
    "structural_factorial_precision_audit.csv",
    "structural_factorial_precision_decision.json",
    "structural_factorial_precision_reproducibility.json",
    "structural_factorial_precision_benchmark.json",
)
EVIDENCE_NAMES = (
    "structural_factorial_specification.json",
    "structural_factorial_registry.json",
    "structural_factorial_cells.csv",
    "structural_factorial_effects.csv",
    "structural_factorial_interactions.csv",
    "structural_factorial_cell_summary.json",
    "structural_factorial_interaction_summary.json",
    "structural_factorial_decision.json",
    "structural_factorial_reproducibility.json",
    "structural_factorial_benchmark.json",
)
DETERMINISTIC_EVIDENCE_NAMES = EVIDENCE_NAMES[:-1]
METRIC_COLUMNS = (
    "first_six_hour_burden",
    "maximum_downside_deviation",
    "recovery_completion_hours",
    "failed_recovery_attempts",
    "initial_peg_gap",
    "numerical_bound_binding_share",
    "right_censored",
    "minimum_confidence",
    "maximum_unresolved_tab_dai",
    "maximum_active_bad_debt_dai",
)
FACTOR_VARIANTS = {
    "A_vault_state": "vault_historical_p25_scr",
    "B_residual_process": "residual_zero",
    "C_backlog_gate": "gate_bad_debt_only",
}
FACTOR_SUBSETS = {
    "A": (0,),
    "B": (1,),
    "C": (2,),
    "AB": (0, 1),
    "AC": (0, 2),
    "BC": (1, 2),
    "ABC": (0, 1, 2),
}
ADDITIVE_COMPONENTS = {
    "110": {"110": 1.0, "100": -1.0, "010": -1.0, "000": 1.0},
    "101": {"101": 1.0, "100": -1.0, "001": -1.0, "000": 1.0},
    "011": {"011": 1.0, "010": -1.0, "001": -1.0, "000": 1.0},
    "111": {
        "111": 1.0,
        "100": -1.0,
        "010": -1.0,
        "001": -1.0,
        "000": 2.0,
    },
}


@dataclass(frozen=True)
class FactorialCell:
    """One fixed cell in the objective-blind 2^3 design."""

    code: str
    vault_high: bool
    residual_high: bool
    backlog_high: bool
    reused: bool
    source_variant: str | None

    @property
    def binary(self) -> tuple[int, int, int]:
        return tuple(int(value) for value in (
            self.vault_high,
            self.residual_high,
            self.backlog_high,
        ))

    @property
    def signed(self) -> tuple[int, int, int]:
        return tuple(1 if value else -1 for value in self.binary)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    search._atomic_json(path, payload)


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    search._atomic_csv(path, frame)


def _canonical_json(payload: Any) -> bytes:
    return search.canonical_json_bytes(payload)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _variant_map() -> dict[str, dict[str, Any]]:
    return {
        item["variant_id"]: item
        for item in _json(STRUCTURAL_REGISTRY_PATH)["variants"]
    }


def build_factorial_cells() -> tuple[FactorialCell, ...]:
    """Return the exact deterministic eight-cell registry."""
    source = {
        "000": None,
        "100": FACTOR_VARIANTS["A_vault_state"],
        "010": FACTOR_VARIANTS["B_residual_process"],
        "001": FACTOR_VARIANTS["C_backlog_gate"],
    }
    cells = tuple(
        FactorialCell(
            code=code,
            vault_high=code[0] == "1",
            residual_high=code[1] == "1",
            backlog_high=code[2] == "1",
            reused=code in REUSED_CELLS,
            source_variant=source.get(code),
        )
        for code in CELL_ORDER
    )
    if tuple(cell.code for cell in cells) != CELL_ORDER:
        raise ValueError("Factorial cell order changed.")
    if sum(not cell.reused for cell in cells) != 4:
        raise ValueError("The factorial must contain exactly four missing cells.")
    return cells


def _factor_definitions() -> dict[str, Any]:
    initial = _json(INITIAL_STATE_PATH)
    variants = _variant_map()
    reproducibility = _json(STRUCTURAL_REPRODUCIBILITY_PATH)
    p25 = variants[FACTOR_VARIANTS["A_vault_state"]]
    return {
        "A_vault_state": {
            "low": {
                "label": "baseline_standardised_500_vault_state",
                "total_debt_dai": 2_500_000.0,
                "state_checksum": initial["state_summary"]["state_checksum"],
            },
            "high": {
                "label": "historical_p25_system_collateral_ratio_state",
                "total_debt_dai": 2_500_000.0,
                "source_timestamp": p25["settings"]["snapshot"]["timestamp_utc"],
                "source_path": p25["settings"]["snapshot"]["source_path"],
                "source_system_collateral_ratio": p25["settings"]["snapshot"][
                    "system_collateral_ratio"
                ],
                "state_audit_sha256": reproducibility["vault_state_audit"]["sha256"],
                "relative_debt_weights_preserved": True,
                "event_specific_selection": False,
                "arbitrary_collateral_ratio_scaling": False,
            },
        },
        "B_residual_process": {
            "low": {
                "label": "accepted_24_hour_moving_block_residuals",
                "residual_sequence_sha256": _json(RESIDUAL_PATH)[
                    "centred_residual_sequence_sha256"
                ],
                "block_specification_sha256": _json(RESIDUAL_PATH)[
                    "block_index_specification_sha256"
                ],
            },
            "high": {
                "label": "zero_residual_innovation",
                "mechanism_isolation_only": True,
                "empirical_residual_model": False,
            },
        },
        "C_backlog_gate": {
            "low": {
                "label": "full_registered_recovery_gate",
                "price_stability": True,
                "unresolved_backlog": True,
                "active_bad_debt": True,
            },
            "high": {
                "label": "backlog_removed_gate",
                "price_stability": True,
                "unresolved_backlog": False,
                "active_bad_debt": True,
                "source_variant": "gate_bad_debt_only",
            },
        },
    }


def _constraints(
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> pd.DataFrame:
    return structural._constraints(evidence_dir)


def build_factorial_identity(
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> tuple[str, dict[str, Any]]:
    """Build the result-blind content-addressed factorial design identity."""
    decision = _json(STRUCTURAL_DECISION_PATH)
    if decision["overall_classification"] != "multiple_structural_families_contribute":
        raise ValueError("The committed structural diagnosis is not the required source.")
    constraints = _constraints(evidence_dir)
    cells = build_factorial_cells()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_structural_decision_sha256": sha256_file(
            STRUCTURAL_DECISION_PATH
        ),
        "source_partial_identification_identity": structural.PARTIAL_IDENTIFICATION_ID,
        "candidate_panel": list(PANEL_INDICES),
        "candidate_panel_sha256": PANEL_SHA256,
        "event_catalogue_sha256": sha256_file(EVENT_CATALOGUE_PATH),
        "seed_registry_sha256": sha256_file(SEED_REGISTRY_PATH),
        "registry": REGISTRY_A,
        "replications": REPLICATION_COUNT,
        "factor_order": list(FACTOR_ORDER),
        "factor_definitions": _factor_definitions(),
        "cell_order": list(CELL_ORDER),
        "cell_coding": {
            cell.code: {
                "binary": list(cell.binary),
                "signed": list(cell.signed),
                "reused": cell.reused,
            }
            for cell in cells
        },
        "empirical_support_bands": [
            {
                "moment": moment,
                "lower": float(constraints.loc[moment, "adjusted_band_lower"]),
                "upper": float(constraints.loc[moment, "adjusted_band_upper"]),
                "scale": float(constraints.loc[moment, "empirical_scale"]),
            }
            for moment in STAGE2_ACTIVE_MOMENTS
        ],
        "mc_interval_rule": {
            "critical_value": 1.645,
            "natural_support_clipping": True,
            "inner_pass": "simulated mean lies inside the empirical band",
            "outer_pass": "90% Monte Carlo interval overlaps the empirical band",
        },
        "hard_gate_rules": {
            "structural_validity": True,
            "stage1_preservation": True,
            "numerical_bound_limit": NUMERICAL_BOUND_LIMIT,
        },
        "factorial_effect_schema": {
            "signed_coding": [-1, 1],
            "effects": list(EFFECT_ORDER),
            "effect_divisor": 4,
            "paired_event_replication_level": True,
        },
        "interaction_classification_schema": {
            "same_direction_candidates": 12,
            "large_precise_candidates": 8,
            "residual_scale_threshold": 0.5,
            "snr_threshold": 2.0,
            "median_gap_threshold": 0.5,
        },
        "implementation_schema": {
            "factorial": SCHEMA_VERSION,
            "event_simulation": structural.search.EVENT_SIMULATION_SCHEMA,
            "checkpoint": 1,
        },
        "result_fields_excluded": True,
        "selection_fields_excluded": True,
    }
    return search.payload_sha256(payload), payload


def factorial_directory(parent: Path = DEFAULT_PARENT) -> Path:
    identity, _ = build_factorial_identity()
    path = Path(parent).resolve()
    return path if path.name == identity else path / identity


def _cell_registry() -> dict[str, Any]:
    identity, design = build_factorial_identity()
    variants = _variant_map()
    structural_reproducibility = _json(STRUCTURAL_REPRODUCIBILITY_PATH)
    cells = []
    for cell in build_factorial_cells():
        changed = [
            FACTOR_ORDER[index]
            for index, value in enumerate(cell.binary)
            if value
        ]
        source_identity: str | None
        if cell.code == "000":
            source_identity = structural.PARTIAL_IDENTIFICATION_ID
        elif cell.reused:
            source_identity = structural_reproducibility["variant_identities"][
                cell.source_variant
            ]
        else:
            source_identity = None
        record = {
            "binary_code": cell.code,
            "binary_coding": list(cell.binary),
            "signed_coding": list(cell.signed),
            "vault_state_level": "high" if cell.vault_high else "low",
            "residual_process_level": "high" if cell.residual_high else "low",
            "backlog_gate_level": "high" if cell.backlog_high else "low",
            "status": "reused" if cell.reused else "newly_evaluated",
            "source_variant": cell.source_variant,
            "source_checkpoint_identity": source_identity,
            "changed_assumptions": changed,
            "fixed_assumptions": [
                name for name in FACTOR_ORDER if name not in changed
            ],
            "selected": False,
            "runtime_adopted": False,
        }
        record["cell_checksum"] = search.payload_sha256(record)
        cells.append(record)
    return {
        "schema_version": SCHEMA_VERSION,
        "factorial_identity": identity,
        "factor_order": list(FACTOR_ORDER),
        "cells": cells,
        "cell_count": 8,
        "reused_cell_count": 4,
        "new_cell_count": 4,
        "design_identity_inputs": design,
        "objective_used": False,
        "candidate_ranked": False,
        "cell_ranked": False,
        "cell_selected": False,
        "parameter_selected": False,
        "runtime_adopted": False,
    }


def _structural_shard_frame(variant_id: str) -> pd.DataFrame:
    """Load one preserved single-factor event-replication stream."""
    frames = []
    columns = (
        "candidate_index",
        "variant_id",
        "event_id",
        "replication",
        *METRIC_COLUMNS,
        "structural_pass",
    )
    for path in sorted((STRUCTURAL_ROOT / "shards").glob("event_shard_*.npz")):
        with np.load(path, allow_pickle=False) as arrays:
            mask = arrays["variant_id"] == variant_id
            frames.append(
                pd.DataFrame({column: arrays[column][mask] for column in columns})
            )
    if not frames:
        raise ValueError(f"Preserved structural stream is unavailable: {variant_id}.")
    frame = pd.concat(frames, ignore_index=True)
    return _validate_event_frame(frame, cell_id=None)


def _normalise_baseline(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.loc[
        :,
        [
            "candidate_index",
            "event_id",
            "replication",
            *METRIC_COLUMNS,
        ],
    ].copy()
    result["structural_pass"] = True
    return _validate_event_frame(result, cell_id=None)


def _validate_event_frame(
    frame: pd.DataFrame,
    *,
    cell_id: str | None,
) -> pd.DataFrame:
    required = {
        "candidate_index",
        "event_id",
        "replication",
        *METRIC_COLUMNS,
        "structural_pass",
    }
    missing = required - set(frame)
    if missing:
        raise ValueError(f"Factorial event frame lacks columns: {sorted(missing)}.")
    result = frame.loc[:, sorted(required)].copy()
    result["candidate_index"] = pd.to_numeric(
        result["candidate_index"], errors="raise"
    ).astype(int)
    result["replication"] = pd.to_numeric(
        result["replication"], errors="raise"
    ).astype(int)
    key = ["candidate_index", "event_id", "replication"]
    if result[key].duplicated().any():
        raise ValueError("Factorial event stream contains duplicate rows.")
    candidate_ids = set(result["candidate_index"])
    expected_rows = len(candidate_ids) * EVENT_COUNT * REPLICATION_COUNT
    if (
        len(result) != expected_rows
        or not candidate_ids
        or not candidate_ids.issubset(set(PANEL_INDICES))
        or result["event_id"].nunique() != EVENT_COUNT
        or set(result["replication"]) != set(range(REPLICATION_COUNT))
    ):
        label = cell_id or "reused"
        raise ValueError(f"Factorial event stream is incomplete for cell {label}.")
    numeric = [column for column in METRIC_COLUMNS if column != "right_censored"]
    if not np.isfinite(result[numeric].to_numpy(dtype=float)).all():
        raise ValueError("Factorial event stream contains non-finite metrics.")
    return result.sort_values(key, kind="mergesort").reset_index(drop=True)


def _reused_cell_frames() -> dict[str, pd.DataFrame]:
    frames = {
        "000": _normalise_baseline(structural._baseline_ladder()),
        "100": _structural_shard_frame(FACTOR_VARIANTS["A_vault_state"]),
        "010": _structural_shard_frame(FACTOR_VARIANTS["B_residual_process"]),
        "001": _structural_shard_frame(FACTOR_VARIANTS["C_backlog_gate"]),
    }
    results = pd.read_csv(
        CONFIDENCE_EVIDENCE / "structural_variant_results.csv"
    )
    for code, variant_id in (
        ("100", FACTOR_VARIANTS["A_vault_state"]),
        ("010", FACTOR_VARIANTS["B_residual_process"]),
        ("001", FACTOR_VARIANTS["C_backlog_gate"]),
    ):
        observed = _cell_moment_rows(frames[code], cell_id=code)
        expected = results.loc[results["variant_id"].eq(variant_id)]
        for _, row in observed.iterrows():
            match = expected.loc[
                expected["candidate_index"].eq(row["candidate_index"])
                & expected["moment"].eq(row["moment"])
            ]
            if len(match) != 1 or not math.isclose(
                float(row["simulated_mean"]),
                float(match["variant_moment"].iloc[0]),
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError(f"Reused factorial cell {code} does not reproduce.")
    baseline = _cell_moment_rows(frames["000"], cell_id="000")
    expected_baseline = results.loc[
        results["variant_id"].eq(FACTOR_VARIANTS["A_vault_state"])
    ]
    for _, row in baseline.iterrows():
        match = expected_baseline.loc[
            expected_baseline["candidate_index"].eq(row["candidate_index"])
            & expected_baseline["moment"].eq(row["moment"])
        ]
        if len(match) != 1 or not math.isclose(
            float(row["simulated_mean"]),
            float(match["baseline_moment"].iloc[0]),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("Reused factorial baseline does not reproduce.")
    return frames


def validate_factorial_inputs(
    *,
    parent: Path = DEFAULT_PARENT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> dict[str, Any]:
    """Validate fixed sources, reused streams and the storage boundary."""
    decision = _json(STRUCTURAL_DECISION_PATH)
    if (
        decision["overall_classification"]
        != "multiple_structural_families_contribute"
        or decision["parameter_selected"]
        or decision["structural_model_selected"]
        or decision["runtime_adopted"]
    ):
        raise ValueError("The source structural diagnosis is not eligible.")
    identity, _ = build_factorial_identity(evidence_dir)
    registry = _cell_registry()
    if [item["binary_code"] for item in registry["cells"]] != list(CELL_ORDER):
        raise ValueError("Factorial registry differs from the pre-registration.")
    reused = _reused_cell_frames()
    free = shutil.disk_usage(REPOSITORY_ROOT).free
    total_diagnostics = (
        sum(path.stat().st_size for path in (
            REPOSITORY_ROOT / "outputs/diagnostics"
        ).rglob("*") if path.is_file())
        if (REPOSITORY_ROOT / "outputs/diagnostics").exists()
        else 0
    )
    structural_size = sum(
        path.stat().st_size for path in STRUCTURAL_ROOT.rglob("*") if path.is_file()
    )
    root = factorial_directory(parent)
    existing_size = (
        sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        if root.exists()
        else 0
    )
    if free < MINIMUM_FREE_BYTES:
        raise ValueError("Fewer than 10 GiB are free.")
    if PROJECTED_STORAGE_BYTES > MAX_NEW_STORAGE_BYTES:
        raise ValueError("Projected factorial storage exceeds 500 MB.")
    if existing_size > MAX_NEW_STORAGE_BYTES:
        raise ValueError("Existing factorial diagnostics exceed 500 MB.")
    return {
        "status": "passed",
        "factorial_identity": identity,
        "panel_sha256": PANEL_SHA256,
        "reused_cells": list(reused),
        "reused_evaluations": EXPECTED_REUSED_EVALUATIONS,
        "new_evaluations": EXPECTED_NEW_EVALUATIONS,
        "total_evaluations": EXPECTED_TOTAL_EVALUATIONS,
        "free_bytes": free,
        "total_diagnostics_bytes": total_diagnostics,
        "structural_incompatibility_diagnostics_bytes": structural_size,
        "existing_factorial_diagnostics_bytes": existing_size,
        "projected_factorial_storage_bytes": PROJECTED_STORAGE_BYTES,
        "storage_cap_bytes": MAX_NEW_STORAGE_BYTES,
        "runtime_adopted": False,
    }


def _candidate_checksum(owner: Mapping[str, Any], index: int) -> str:
    return search._candidate_checksum(
        index,
        owner["candidates"][index],
        owner["transformed"][index],
    )


def _checkpoint_path(root: Path, cell_id: str, candidate_index: int) -> Path:
    return root / "cells" / cell_id / f"candidate_{candidate_index:03d}.npz"


def _shard_path(root: Path, shard_index: int) -> Path:
    return root / "shards" / f"factorial_event_shard_{shard_index:02d}.npz"


def _frame_checksum(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values(
        ["candidate_index", "event_id", "replication"], kind="mergesort"
    )
    records = []
    for row in ordered.to_dict("records"):
        records.append(
            {
                key: (
                    bool(value)
                    if isinstance(value, (bool, np.bool_))
                    else int(value)
                    if isinstance(value, (int, np.integer))
                    else float(value)
                    if isinstance(value, (float, np.floating))
                    else str(value)
                )
                for key, value in row.items()
            }
        )
    return search.payload_sha256(records)


def _frame_to_arrays(
    frame: pd.DataFrame,
    *,
    metadata: Mapping[str, Any],
) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    for column in frame.columns:
        values = frame[column].to_numpy()
        if values.dtype == object:
            values = values.astype(str)
        arrays[column] = values
    for key, value in metadata.items():
        arrays[f"_meta_{key}"] = np.asarray([str(value)])
    return arrays


def _arrays_to_frame(
    arrays: Mapping[str, np.ndarray],
) -> tuple[pd.DataFrame, dict[str, str]]:
    metadata = {
        key.removeprefix("_meta_"): str(value[0])
        for key, value in arrays.items()
        if key.startswith("_meta_")
    }
    frame = pd.DataFrame(
        {key: value for key, value in arrays.items() if not key.startswith("_meta_")}
    )
    return frame, metadata


_WORKER_OWNER: dict[str, Any] | None = None


def _worker_initialise(
    root_text: str,
    factorial_id: str,
    base_liquidation_config: Any,
    demand_config: Any,
) -> None:
    global _WORKER_OWNER
    search._thread_cap()
    owner = structural._load_cache_owner()
    context = owner["context"]
    owner["config"] = ConditionalEventSimulationConfig(**context["config"])
    eligible, _ = structural._snapshot_catalogue()
    owner["eligible_snapshots"] = eligible
    _, _, stage1 = load_stage1_owners()
    owner["stage1"] = stage1
    owner["residual_values"] = np.asarray(
        stage1["source"].centred_residuals, dtype="<f8"
    )
    owner["base_liquidation_config"] = base_liquidation_config
    owner["demand_template"] = LiquidationDemandProcess(demand_config)
    owner["root"] = Path(root_text)
    owner["factorial_id"] = factorial_id
    owner["registry"] = _cell_registry()
    owner["variant_map"] = _variant_map()
    _WORKER_OWNER = owner


def _apply_cell_package(
    package: search.CachedPackage,
    cell: FactorialCell,
    owner: Mapping[str, Any],
    *,
    precomputed_p25: tuple[
        search.CachedPackage, ConditionalEventSimulationConfig
    ] | None = None,
) -> tuple[search.CachedPackage, ConditionalEventSimulationConfig]:
    result = package
    config = owner["config"]
    if cell.vault_high:
        if precomputed_p25 is None:
            result, config = structural._variant_package(
                result,
                owner["variant_map"][FACTOR_VARIANTS["A_vault_state"]],
                config=config,
                eligible_snapshots=owner["eligible_snapshots"],
                residual_values=owner["residual_values"],
                base_liquidation_config=owner["base_liquidation_config"],
                demand_template=owner["demand_template"],
            )
        else:
            result, config = precomputed_p25
    if cell.residual_high:
        arrays = dict(result.arrays)
        arrays["residual_innovations"] = np.zeros_like(
            arrays["residual_innovations"], dtype="<f8"
        )
        result = search.CachedPackage(
            metadata=dict(result.metadata),
            arrays=arrays,
            path=result.path,
        )
    if cell.backlog_high:
        arrays = dict(result.arrays)
        arrays["liquidation_gate_open"] = np.ones_like(
            arrays["liquidation_gate_open"], dtype="?"
        )
        result = search.CachedPackage(
            metadata=dict(result.metadata),
            arrays=arrays,
            path=result.path,
        )
    return result, config


def _event_shard(
    task: tuple[int, tuple[str, ...]],
) -> dict[str, Any]:
    if _WORKER_OWNER is None:
        raise RuntimeError("Factorial worker is not initialised.")
    shard_index, event_ids = task
    owner = _WORKER_OWNER
    path = _shard_path(owner["root"], shard_index)
    expected = (
        len(event_ids)
        * REPLICATION_COUNT
        * len(NEW_CELLS)
        * len(PANEL_INDICES)
    )
    if path.is_file():
        arrays = search._load_npz(path)
        frame, metadata = _arrays_to_frame(arrays)
        if (
            len(frame) != expected
            or metadata.get("factorial_id") != owner["factorial_id"]
            or metadata.get("schema_version") != str(SCHEMA_VERSION)
            or metadata.get("result_checksum") != _frame_checksum(frame)
        ):
            raise ValueError(f"Stale or incomplete factorial shard: {path}.")
        return {
            "shard_index": shard_index,
            "evaluations": 0,
            "resumed": True,
        }
    cells = {cell.code: cell for cell in build_factorial_cells()}
    records: list[dict[str, Any]] = []
    for event_id in sorted(event_ids):
        for replication in range(REPLICATION_COUNT):
            package = structural._package(owner, event_id, replication)
            p25_package = _apply_cell_package(
                package,
                cells["100"],
                owner,
            )
            for cell_id in NEW_CELLS:
                cell_package, config = _apply_cell_package(
                    package,
                    cells[cell_id],
                    owner,
                    precomputed_p25=(
                        p25_package if cells[cell_id].vault_high else None
                    ),
                )
                context = search.WorkerContext(
                    run_dir=owner["root"],
                    search_id=owner["factorial_id"],
                    event_ids=(event_id,),
                    config=config,
                    stage1=owner["context"]["stage1"],
                    scaling=owner["context"]["scaling"],
                    ordinary_preservation=owner["context"]["ordinary_preservation"],
                    objective={},
                    candidates=owner["candidates"],
                    transformed=owner["transformed"],
                    packages={(event_id, replication): cell_package},
                )
                for index in PANEL_INDICES:
                    metrics, _, flags = search._evaluate_cached_event(
                        context,
                        candidate=owner["candidates"][index],
                        event_id=event_id,
                        replication=replication,
                    )
                    records.append(
                        {
                            "cell_id": cell_id,
                            "candidate_index": index,
                            **metrics,
                            "structural_pass": search.structural_event_flags_pass(
                                flags
                            ),
                        }
                    )
    frame = pd.DataFrame(records).sort_values(
        ["cell_id", "candidate_index", "event_id", "replication"],
        kind="mergesort",
    )
    frame = frame.loc[
        :,
        [
            "cell_id",
            "candidate_index",
            "event_id",
            "replication",
            *METRIC_COLUMNS,
            "structural_pass",
        ],
    ]
    checksum = _frame_checksum(frame)
    search._atomic_npz(
        path,
        _frame_to_arrays(
            frame,
            metadata={
                "schema_version": SCHEMA_VERSION,
                "factorial_id": owner["factorial_id"],
                "result_checksum": checksum,
            },
        ),
    )
    return {
        "shard_index": shard_index,
        "evaluations": len(frame),
        "resumed": False,
    }


def _validate_checkpoint(
    path: Path,
    *,
    factorial_id: str,
    cell_record: Mapping[str, Any],
    candidate_index: int,
    candidate_checksum: str,
) -> pd.DataFrame:
    arrays = search._load_npz(path)
    frame, metadata = _arrays_to_frame(arrays)
    expected = {
        "schema_version": str(SCHEMA_VERSION),
        "factorial_id": factorial_id,
        "cell_id": cell_record["binary_code"],
        "cell_checksum": cell_record["cell_checksum"],
        "candidate_index": str(candidate_index),
        "candidate_checksum": candidate_checksum,
        "event_count": str(EVENT_COUNT),
        "replication_count": str(REPLICATION_COUNT),
        "registry": REGISTRY_A,
    }
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError(f"Factorial checkpoint identity differs: {path}.")
    if metadata.get("result_checksum") != _frame_checksum(frame):
        raise ValueError(f"Factorial checkpoint checksum differs: {path}.")
    validated = _validate_event_frame(frame, cell_id=cell_record["binary_code"])
    return validated.loc[
        validated["candidate_index"].eq(candidate_index)
    ].reset_index(drop=True)


def _write_checkpoints_from_shards(
    *,
    root: Path,
    shard_count: int,
) -> int:
    owner = structural._load_cache_owner()
    registry = _cell_registry()
    cell_records = {
        item["binary_code"]: item for item in registry["cells"]
    }
    frames = []
    for shard_index in range(shard_count):
        frame, metadata = _arrays_to_frame(
            search._load_npz(_shard_path(root, shard_index))
        )
        if metadata.get("factorial_id") != registry["factorial_identity"]:
            raise ValueError("Factorial shard identity differs.")
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    written = 0
    for cell_id in NEW_CELLS:
        for index in PANEL_INDICES:
            path = _checkpoint_path(root, cell_id, index)
            candidate_checksum = _candidate_checksum(owner, index)
            if path.is_file():
                _validate_checkpoint(
                    path,
                    factorial_id=registry["factorial_identity"],
                    cell_record=cell_records[cell_id],
                    candidate_index=index,
                    candidate_checksum=candidate_checksum,
                )
                continue
            frame = combined.loc[
                combined["cell_id"].eq(cell_id)
                & combined["candidate_index"].eq(index)
            ].drop(columns=["cell_id"])
            if len(frame) != EVENT_COUNT * REPLICATION_COUNT:
                raise ValueError("Factorial candidate checkpoint rows are incomplete.")
            checksum = _frame_checksum(frame)
            search._atomic_npz(
                path,
                _frame_to_arrays(
                    frame,
                    metadata={
                        "schema_version": SCHEMA_VERSION,
                        "factorial_id": registry["factorial_identity"],
                        "cell_id": cell_id,
                        "cell_checksum": cell_records[cell_id]["cell_checksum"],
                        "candidate_index": index,
                        "candidate_checksum": candidate_checksum,
                        "event_count": EVENT_COUNT,
                        "replication_count": REPLICATION_COUNT,
                        "registry": REGISTRY_A,
                        "result_checksum": checksum,
                    },
                ),
            )
            written += 1
    return written


def run_missing_cells(
    *,
    parent: Path = DEFAULT_PARENT,
    workers: int = 4,
    resume: bool = False,
) -> dict[str, Any]:
    """Execute or resume exactly the four missing interaction cells."""
    if workers < 1 or workers > 6:
        raise ValueError("workers must be between one and six.")
    validation = validate_factorial_inputs(parent=parent)
    identity = validation["factorial_identity"]
    root = factorial_directory(parent)
    root.mkdir(parents=True, exist_ok=True)
    existing = list((root / "cells").glob("*/*.npz")) if (root / "cells").exists() else []
    shards = list((root / "shards").glob("*.npz")) if (root / "shards").exists() else []
    if (existing or shards) and not resume:
        raise ValueError("Factorial diagnostics exist; use explicit resume.")
    event_ids = tuple(sorted(structural._load_cache_owner()["context"]["event_ids"]))
    event_shards = tuple(
        tuple(event_ids[offset::workers])
        for offset in range(workers)
        if event_ids[offset::workers]
    )
    tasks = tuple(enumerate(event_shards))
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    base_liquidation_config = bundle.base_bundle.liquidation_config
    demand_config = _liquidation_demand_config(
        DEFAULT_TRANCHE_B_CONFIG_PATH,
        seed=0,
    )
    started = time.perf_counter()
    context = mp.get_context("spawn")
    with context.Pool(
        processes=len(tasks),
        initializer=_worker_initialise,
        initargs=(
            str(root),
            identity,
            base_liquidation_config,
            demand_config,
        ),
    ) as pool:
        results = pool.map(_event_shard, tasks)
    written = _write_checkpoints_from_shards(
        root=root,
        shard_count=len(tasks),
    )
    elapsed = time.perf_counter() - started
    checkpoint_count = len(list((root / "cells").glob("*/*.npz")))
    if checkpoint_count != EXPECTED_NEW_CHECKPOINTS:
        raise ValueError("Factorial checkpoints are incomplete.")
    history_path = root / "run_history.json"
    history = (
        _json(history_path)
        if history_path.is_file()
        else {"schema_version": SCHEMA_VERSION, "runs": []}
    )
    history["runs"].append(
        {
            "action": "resume" if resume else "run",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "workers": workers,
            "duration_seconds": elapsed,
            "new_evaluations": sum(item["evaluations"] for item in results),
            "represented_new_evaluations": EXPECTED_NEW_EVALUATIONS,
            "checkpoint_count": checkpoint_count,
            "checkpoints_written": written,
            "event_shard_count": len(tasks),
        }
    )
    _atomic_json(history_path, history)
    size = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    if size > MAX_NEW_STORAGE_BYTES:
        raise ValueError("Factorial diagnostics exceed the 500 MB cap.")
    return {
        **validation,
        "status": "completed",
        "workers": workers,
        "duration_seconds": elapsed,
        "new_evaluations_this_run": sum(item["evaluations"] for item in results),
        "represented_new_evaluations": EXPECTED_NEW_EVALUATIONS,
        "reused_evaluations": EXPECTED_REUSED_EVALUATIONS,
        "total_represented_evaluations": EXPECTED_TOTAL_EVALUATIONS,
        "checkpoint_count": checkpoint_count,
        "checkpoints_written": written,
        "ignored_output_size_bytes": size,
        "runtime_adopted": False,
    }


def _new_cell_frames(root: Path) -> dict[str, pd.DataFrame]:
    registry = _cell_registry()
    cell_records = {item["binary_code"]: item for item in registry["cells"]}
    owner = structural._load_cache_owner()
    result = {}
    for cell_id in NEW_CELLS:
        frames = []
        for index in PANEL_INDICES:
            frames.append(
                _validate_checkpoint(
                    _checkpoint_path(root, cell_id, index),
                    factorial_id=registry["factorial_identity"],
                    cell_record=cell_records[cell_id],
                    candidate_index=index,
                    candidate_checksum=_candidate_checksum(owner, index),
                )
            )
        result[cell_id] = _validate_event_frame(
            pd.concat(frames, ignore_index=True),
            cell_id=cell_id,
        )
    return result


def load_all_cells(
    *,
    parent: Path = DEFAULT_PARENT,
) -> dict[str, pd.DataFrame]:
    """Load and validate all reused and newly evaluated factorial cells."""
    frames = {**_reused_cell_frames(), **_new_cell_frames(factorial_directory(parent))}
    if tuple(frames) != CELL_ORDER:
        frames = {code: frames[code] for code in CELL_ORDER}
    return frames


def _moment_estimate(frame: pd.DataFrame, moment: str) -> Any:
    if moment in MEAN_MOMENTS:
        return analytic_equal_event_mcse(frame, outcome=MEAN_MOMENTS[moment])
    return analytic_contrast_mcse(
        frame,
        outcome="first_six_hour_burden",
        stratifier="initial_peg_gap",
    )


def _moment_source(moment: str) -> str:
    return MEAN_MOMENTS.get(moment, "first_six_hour_burden")


def _numerical_bound_share(frame: pd.DataFrame) -> float:
    durations = frame["recovery_completion_hours"].astype(float) + 1.0
    return float(
        (
            frame["numerical_bound_binding_share"].astype(float) * durations
        ).sum()
        / durations.sum()
    )


def _candidate_parameters() -> Mapping[int, Any]:
    return {
        index: candidate
        for index, candidate in enumerate(
            structural._load_cache_owner()["candidates"]
        )
        if index in PANEL_INDICES
    }


def _cell_moment_rows(
    frame: pd.DataFrame,
    *,
    cell_id: str,
    constraints: pd.DataFrame | None = None,
) -> pd.DataFrame:
    constraints = _constraints() if constraints is None else constraints
    candidates = _candidate_parameters()
    rows = []
    for index in PANEL_INDICES:
        candidate_frame = frame.loc[frame["candidate_index"].eq(index)]
        numerical_share = _numerical_bound_share(candidate_frame)
        diagnostics = {
            "censoring_share": float(candidate_frame["right_censored"].mean()),
            "numerical_bound_share": numerical_share,
            "numerical_bound_pass": numerical_share <= NUMERICAL_BOUND_LIMIT,
            "active_bad_debt_occurrence": bool(
                candidate_frame["maximum_active_bad_debt_dai"].gt(0.0).any()
            ),
            "unresolved_backlog_occurrence": bool(
                candidate_frame["maximum_unresolved_tab_dai"].gt(0.0).any()
            ),
            "maximum_active_bad_debt_dai": float(
                candidate_frame["maximum_active_bad_debt_dai"].max()
            ),
            "maximum_unresolved_tab_dai": float(
                candidate_frame["maximum_unresolved_tab_dai"].max()
            ),
            "structural_validity": bool(
                candidate_frame["structural_pass"].astype(bool).all()
            ),
            "stage1_preservation": True,
            "confidence_floor_binding_share": float(
                np.isclose(
                    candidate_frame["minimum_confidence"].astype(float),
                    candidates[index].confidence_floor,
                    rtol=0.0,
                    atol=1e-12,
                ).mean()
            ),
            "recovery_probability_48h": float(
                (
                    ~candidate_frame["right_censored"].astype(bool)
                    & candidate_frame["recovery_completion_hours"].le(48)
                ).mean()
            ),
            "recovery_probability_168h": float(
                (
                    ~candidate_frame["right_censored"].astype(bool)
                    & candidate_frame["recovery_completion_hours"].le(168)
                ).mean()
            ),
            "recovery_probability_792h": float(
                (~candidate_frame["right_censored"].astype(bool)).mean()
            ),
            "failed_recovery_attempts_diagnostic": float(
                candidate_frame["failed_recovery_attempts"].mean()
            ),
            "result_checksum": _frame_checksum(candidate_frame),
        }
        for moment in STAGE2_ACTIVE_MOMENTS:
            estimate = _moment_estimate(candidate_frame, moment)
            band = constraints.loc[moment]
            lower = float(band["adjusted_band_lower"])
            upper = float(band["adjusted_band_upper"])
            scale = float(band["empirical_scale"])
            mcse = float(estimate.diagnostic_mcse)
            interval = construct_mc_interval(
                estimate=estimate.point_estimate,
                mcse=mcse,
                natural_support=NATURAL_SUPPORTS[moment],
            )
            gap = structural.signed_band_gap(
                estimate.point_estimate, lower, upper
            )
            rows.append(
                {
                    "cell_id": cell_id,
                    "candidate_index": index,
                    "moment": moment,
                    "simulated_mean": estimate.point_estimate,
                    "hierarchical_mcse": mcse,
                    "analytic_mcse": estimate.analytic_mcse,
                    "replication_index_mcse": estimate.replication_index_mcse,
                    "mcse_relative_disagreement": estimate.relative_disagreement,
                    "mcse_agreement_pass": estimate.agreement_pass,
                    "mc_interval_lower": interval.adjusted_lower,
                    "mc_interval_upper": interval.adjusted_upper,
                    "empirical_band_lower": lower,
                    "empirical_band_upper": upper,
                    "empirical_scale": scale,
                    "signed_band_gap": gap,
                    "absolute_band_gap": abs(gap),
                    "normalised_band_gap": gap / scale,
                    "inner_pass": lower <= estimate.point_estimate <= upper,
                    "outer_pass": (
                        interval.adjusted_upper >= lower
                        and interval.adjusted_lower <= upper
                    ),
                    **diagnostics,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["cell_id", "candidate_index", "moment"], kind="mergesort"
    ).reset_index(drop=True)


def construct_cell_evidence(
    cells: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    constraints = _constraints()
    return pd.concat(
        [
            _cell_moment_rows(cells[code], cell_id=code, constraints=constraints)
            for code in CELL_ORDER
        ],
        ignore_index=True,
    )


def _linear_combination_frame(
    cells: Mapping[str, pd.DataFrame],
    *,
    candidate_index: int,
    source: str,
    weights: Mapping[str, float],
) -> pd.DataFrame:
    base: pd.DataFrame | None = None
    for code, weight in weights.items():
        frame = cells[code].loc[
            cells[code]["candidate_index"].eq(candidate_index),
            ["event_id", "replication", "initial_peg_gap", source],
        ].copy()
        frame = frame.rename(columns={source: code})
        if base is None:
            base = frame
        else:
            base = base.merge(
                frame.drop(columns=["initial_peg_gap"]),
                on=["event_id", "replication"],
                validate="one_to_one",
            )
    if base is None:
        raise ValueError("A factorial contrast needs at least one cell.")
    base["contrast"] = sum(weight * base[code] for code, weight in weights.items())
    return base


def _effect_weights(effect: str) -> dict[str, float]:
    subset = FACTOR_SUBSETS[effect]
    cells = {item.code: item for item in build_factorial_cells()}
    return {
        code: float(np.prod([cells[code].signed[index] for index in subset]) / 4.0)
        for code in CELL_ORDER
    }


def _estimate_contrast(
    frame: pd.DataFrame,
    *,
    moment: str,
    prefix: int | None = None,
) -> Any:
    source = frame if prefix is None else frame.loc[frame["replication"].lt(prefix)]
    if moment in MEAN_MOMENTS:
        return analytic_equal_event_mcse(source, outcome="contrast")
    return analytic_contrast_mcse(
        source,
        outcome="contrast",
        stratifier="initial_peg_gap",
    )


def construct_factorial_effects(
    cells: Mapping[str, pd.DataFrame],
    *,
    enforce_agreement: bool = True,
) -> pd.DataFrame:
    rows = []
    for index in PANEL_INDICES:
        for moment in STAGE2_ACTIVE_MOMENTS:
            source = _moment_source(moment)
            for effect in EFFECT_ORDER:
                frame = _linear_combination_frame(
                    cells,
                    candidate_index=index,
                    source=source,
                    weights=_effect_weights(effect),
                )
                estimate = _estimate_contrast(frame, moment=moment)
                prefix = _estimate_contrast(frame, moment=moment, prefix=32)
                mcse = float(estimate.diagnostic_mcse)
                value = float(estimate.point_estimate)
                rows.append(
                    {
                        "candidate_index": index,
                        "moment": moment,
                        "effect": effect,
                        "effect_estimate": value,
                        "paired_mcse": mcse,
                        "analytic_mcse": estimate.analytic_mcse,
                        "replication_index_mcse": estimate.replication_index_mcse,
                        "relative_disagreement": estimate.relative_disagreement,
                        "agreement_pass": estimate.agreement_pass,
                        "snr": (
                            math.inf
                            if mcse == 0.0 and value != 0.0
                            else 0.0
                            if mcse == 0.0
                            else abs(value) / mcse
                        ),
                        "sign": int(np.sign(value)),
                        "prefix_32_estimate": prefix.point_estimate,
                        "prefix_32_sign": int(np.sign(prefix.point_estimate)),
                        "prefix_sign_stable": (
                            int(np.sign(prefix.point_estimate))
                            == int(np.sign(value))
                        ),
                        "dominant_event": estimate.dominant_event,
                        "dominant_event_share": estimate.dominant_event_share,
                        "effective_event_count": estimate.effective_event_count,
                    }
                )
    result = pd.DataFrame(rows).sort_values(
        ["candidate_index", "moment", "effect"], kind="mergesort"
    ).reset_index(drop=True)
    agreement = result.groupby(["moment", "effect"], sort=True)[
        "agreement_pass"
    ].sum()
    if enforce_agreement and (agreement < PRECISION_MINIMUM_PASS_COUNT).any():
        failed = agreement.loc[
            agreement < PRECISION_MINIMUM_PASS_COUNT
        ].to_dict()
        raise ValueError(f"Factorial paired MCSE cross-check failed: {failed}.")
    return result


def _precision_design_inputs() -> dict[str, Any]:
    """Return the fixed, result-blind precision-validation specification."""
    return {
        "schema_version": PRECISION_SCHEMA_VERSION,
        "source_factorial_identity": build_factorial_identity()[0],
        "original_replications": REPLICATION_COUNT,
        "extended_replications": PRECISION_FINAL_REPLICATION_COUNT,
        "nested_prefixes": list(PRECISION_PREFIXES_R64),
        "added_replications_zero_based": list(PRECISION_ADDED_REPLICATIONS),
        "moment": PRECISION_MOMENT,
        "effects": list(PRECISION_EFFECTS),
        "relative_tolerance": PRECISION_RELATIVE_TOLERANCE,
        "minimum_candidate_pass_count": PRECISION_MINIMUM_PASS_COUNT,
        "candidate_panel": list(PANEL_INDICES),
        "candidate_panel_sha256": PANEL_SHA256,
        "cells": list(CELL_ORDER),
        "events": EVENT_COUNT,
        "registry": REGISTRY_A,
        "factorial_effect_formula": (
            "one quarter times the sum over all eight cells of the signed "
            "factor-product multiplied by the cell event-replication value"
        ),
        "analytic_estimator": {
            "construction": (
                "construct the paired factorial effect within each "
                "event-replication, estimate each event variance with ddof=1, "
                "divide by R, and sum equal-event contributions divided by E^2"
            ),
            "zero_variance_events": "retain with zero contribution",
            "non_finite_observations": "reject",
        },
        "replication_index_estimator": {
            "construction": (
                "construct the paired factorial effect within each "
                "event-replication, average equally across events at each "
                "replication index, and use sd(ddof=1)/sqrt(R)"
            ),
            "replication_identity": (
                "the exact registry-A replication index shared across cells; "
                "event streams remain independently event-keyed"
            ),
            "non_finite_observations": "reject",
        },
        "audit_classification_rules": {
            "formula_or_ownership_mismatch": (
                "the static ownership audit finds different cell coefficients, "
                "event weights, replication identities, divisors or order of "
                "paired construction"
            ),
            "variance_floor_or_degeneracy": (
                "the final analytic and replication-index MCSE are both at "
                "most 1e-12, or all event-level effect variances are zero"
            ),
            "finite_replication_instability": (
                "the ownership audit passes, both estimators are finite with "
                "non-degenerate variance, but the final 15% gate fails"
            ),
            "audit_unresolved": (
                "a non-finite or otherwise unclassified disagreement remains"
            ),
            "gate_pass": "the final relative disagreement is at most 15%",
        },
        "extension_rule": (
            "extend uniformly to R=128 only if both estimators target the same "
            "estimand and any R=64 moment-effect gate remains below 15/16"
        ),
        "candidate_specific_extension": False,
        "cell_specific_extension": False,
        "threshold_relaxed": False,
        "objective_used": False,
        "runtime_adopted": False,
    }


def build_precision_identity() -> tuple[str, dict[str, Any]]:
    """Return the content-addressed precision identity and its fixed inputs."""
    payload = _precision_design_inputs()
    return search.payload_sha256(payload), payload


def precision_directory(parent: Path = DEFAULT_PARENT) -> Path:
    """Return the ignored directory for the fixed R=128 precision extension."""
    precision_id, _ = build_precision_identity()
    return factorial_directory(parent) / "precision_r128" / precision_id


def _estimator_ownership_audit() -> dict[str, Any]:
    """Record the common estimand and covariance ownership before results."""
    weights = {
        effect: _effect_weights(effect)
        for effect in PRECISION_EFFECTS
    }
    expected_scale = 0.25
    coefficient_pass = all(
        set(values) == set(CELL_ORDER)
        and all(abs(abs(value) - expected_scale) <= 1e-15 for value in values.values())
        for values in weights.values()
    )
    return {
        "schema_version": PRECISION_SCHEMA_VERSION,
        "candidate_ownership": "one fixed objective-blind candidate at a time",
        "cell_ownership": "all eight registered factorial cells",
        "factor_effect_coding": weights,
        "paired_replication_identity": (
            "registry-A event and replication identities are matched before "
            "the eight cell values are combined"
        ),
        "event_weighting": "equal event weight after paired effect construction",
        "within_event_covariance": (
            "retained because the signed eight-cell effect is constructed "
            "before the event-level variance is estimated"
        ),
        "across_event_aggregation": {
            "analytic": (
                "sum of event-specific conditional Monte Carlo variances; "
                "event random streams are independently keyed by event_id"
            ),
            "replication_index": (
                "variance of the equal-event mean over common replication "
                "indices; finite samples include sampled cross-event covariance"
            ),
        },
        "divisor_and_degrees_of_freedom": (
            "both use sample variance with ddof=1 and divide by the number "
            "of replications through sd/sqrt(R)"
        ),
        "zero_variance_events": "retained with zero analytic contribution",
        "non_finite_observations": "rejected by the shared metric validator",
        "replication_prefix_ownership": (
            "exact nested zero-based prefixes 0:16, 0:32, 0:48 and 0:64"
        ),
        "signed_effect_scaling": "standard 2^3 high-minus-low scale of 1/4",
        "cell_coefficient_check": coefficient_pass,
        "same_estimand": coefficient_pass,
        "formula_error": False,
        "status": "passed" if coefficient_pass else "failed",
    }


def _comparison_candidates() -> tuple[int, int, int]:
    """Select fixed comparison candidates without using MCSE outcomes."""
    lower = min(PANEL_INDICES)
    median_by_order = PANEL_INDICES[(len(PANEL_INDICES) - 1) // 2]
    upper = max(PANEL_INDICES)
    return lower, median_by_order, upper


def _contrast_diagnostics(
    frame: pd.DataFrame,
    estimate: Any,
) -> dict[str, Any]:
    event_variances = (
        frame.groupby("event_id", sort=True)["contrast"]
        .var(ddof=1)
        .fillna(0.0)
    )
    replication_values = (
        frame.groupby("replication", sort=True)["contrast"].mean()
    )
    values = event_variances.to_numpy(dtype=float)
    return {
        "effect_estimate": float(estimate.point_estimate),
        "analytic_mcse": float(estimate.analytic_mcse),
        "replication_index_mcse": float(estimate.replication_index_mcse),
        "absolute_difference": abs(
            float(estimate.analytic_mcse)
            - float(estimate.replication_index_mcse)
        ),
        "relative_disagreement": float(estimate.relative_disagreement),
        "agreement_pass": bool(estimate.agreement_pass),
        "event_count": int(frame["event_id"].nunique()),
        "replication_count": int(frame["replication"].nunique()),
        "non_zero_event_replication_observations": int(
            np.count_nonzero(frame["contrast"].to_numpy(dtype=float))
        ),
        "event_variance_minimum": float(values.min()),
        "event_variance_p25": float(np.quantile(values, 0.25)),
        "event_variance_median": float(np.median(values)),
        "event_variance_p75": float(np.quantile(values, 0.75)),
        "event_variance_maximum": float(values.max()),
        "replication_level_effect_variance": float(
            replication_values.var(ddof=1)
        ),
        "dominant_event": estimate.dominant_event,
        "dominant_event_share": float(estimate.dominant_event_share),
        "zero_variance_event_count": int(event_variances.eq(0.0).sum()),
    }


def _convergence_slope(prefixes: Sequence[int], values: Sequence[float]) -> float:
    x = np.asarray(prefixes, dtype=float)
    y = np.asarray(values, dtype=float)
    positive = np.isfinite(y) & (y > 0.0)
    if np.count_nonzero(positive) < 2:
        return math.nan
    return float(np.polyfit(np.log(x[positive]), np.log(y[positive]), 1)[0])


def _audit_classification(
    final: Mapping[str, Any],
    *,
    ownership_passed: bool,
) -> str:
    if not ownership_passed:
        return "formula_or_ownership_mismatch"
    if final["agreement_pass"]:
        return "gate_pass"
    values = (
        float(final["analytic_mcse"]),
        float(final["replication_index_mcse"]),
    )
    if not all(math.isfinite(value) for value in values):
        return "audit_unresolved"
    if (
        max(values) <= 1e-12
        or int(final["zero_variance_event_count"]) == EVENT_COUNT
    ):
        return "variance_floor_or_degeneracy"
    return "finite_replication_instability"


def construct_precision_audit(
    cells: Mapping[str, pd.DataFrame],
    *,
    prefixes: Sequence[int] = PRECISION_PREFIXES_R64,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Construct the fixed nested-prefix audit from already simulated cells."""
    prefixes = tuple(int(value) for value in prefixes)
    if not prefixes or tuple(sorted(set(prefixes))) != prefixes:
        raise ValueError("Precision prefixes must be unique and increasing.")
    maximum = max(prefixes)
    expected_replications = set(range(maximum))
    for code in CELL_ORDER:
        observed = set(int(value) for value in cells[code]["replication"].unique())
        if not expected_replications.issubset(observed):
            raise ValueError(f"Cell {code} lacks the requested precision prefix.")
    ownership = _estimator_ownership_audit()
    rows: list[dict[str, Any]] = []
    series: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for prefix in prefixes:
        for candidate_index in PANEL_INDICES:
            for effect in PRECISION_EFFECTS:
                frame = _linear_combination_frame(
                    cells,
                    candidate_index=candidate_index,
                    source=_moment_source(PRECISION_MOMENT),
                    weights=_effect_weights(effect),
                )
                frame = frame.loc[frame["replication"].lt(prefix)].copy()
                estimate = _estimate_contrast(
                    frame,
                    moment=PRECISION_MOMENT,
                )
                row = {
                    "replication_prefix": prefix,
                    "candidate_index": candidate_index,
                    "moment": PRECISION_MOMENT,
                    "effect": effect,
                    **_contrast_diagnostics(frame, estimate),
                }
                rows.append(row)
                series[(candidate_index, effect)].append(row)
    result = pd.DataFrame(rows)
    for key, records in series.items():
        final = records[-1]
        classification = _audit_classification(
            final,
            ownership_passed=bool(ownership["same_estimand"]),
        )
        analytic_slope = _convergence_slope(
            prefixes,
            [float(item["analytic_mcse"]) for item in records],
        )
        index_slope = _convergence_slope(
            prefixes,
            [float(item["replication_index_mcse"]) for item in records],
        )
        ratios = [
            (
                float(item["replication_index_mcse"])
                / float(item["analytic_mcse"])
                if float(item["analytic_mcse"]) > 0.0
                else math.nan
            )
            for item in records
        ]
        finite_ratios = [value for value in ratios if math.isfinite(value)]
        ratio_range = (
            max(finite_ratios) - min(finite_ratios)
            if finite_ratios
            else math.nan
        )
        mask = (
            result["candidate_index"].eq(key[0])
            & result["effect"].eq(key[1])
        )
        result.loc[mask, "analytic_convergence_slope"] = analytic_slope
        result.loc[mask, "replication_index_convergence_slope"] = index_slope
        result.loc[mask, "estimator_ratio_range"] = ratio_range
        result.loc[mask, "audit_classification"] = classification
    result["estimator_ratio"] = np.where(
        result["analytic_mcse"].gt(0.0),
        result["replication_index_mcse"] / result["analytic_mcse"],
        np.nan,
    )
    result = result.sort_values(
        ["replication_prefix", "candidate_index", "effect"],
        kind="mergesort",
    ).reset_index(drop=True)
    final_rows = result.loc[result["replication_prefix"].eq(maximum)]
    pass_counts = {
        effect: int(
            final_rows.loc[final_rows["effect"].eq(effect), "agreement_pass"].sum()
        )
        for effect in PRECISION_EFFECTS
    }
    failing = {
        effect: [
            int(value)
            for value in final_rows.loc[
                final_rows["effect"].eq(effect)
                & ~final_rows["agreement_pass"].astype(bool),
                "candidate_index",
            ]
        ]
        for effect in PRECISION_EFFECTS
    }
    return result, {
        "ownership": ownership,
        "prefixes": list(prefixes),
        "final_replication_count": maximum,
        "pass_counts": pass_counts,
        "failing_candidates": failing,
        "gate_pass": all(
            count >= PRECISION_MINIMUM_PASS_COUNT
            for count in pass_counts.values()
        ),
    }


def validate_r64_precision_inputs(
    *,
    parent: Path = DEFAULT_PARENT,
) -> dict[str, Any]:
    """Validate all preserved R=64 checkpoints and four event shards."""
    factorial_validation = validate_factorial_inputs(parent=parent)
    root = factorial_directory(parent)
    cells = load_all_cells(parent=parent)
    if any(len(frame) != len(PANEL_INDICES) * EVENT_COUNT * REPLICATION_COUNT for frame in cells.values()):
        raise ValueError("A preserved R=64 cell has an unexpected row count.")
    shard_paths = sorted((root / "shards").glob("factorial_event_shard_*.npz"))
    if len(shard_paths) != 4:
        raise ValueError("The four preserved factorial event shards are incomplete.")
    shard_rows = 0
    for path in shard_paths:
        frame, metadata = _arrays_to_frame(search._load_npz(path))
        if (
            metadata.get("factorial_id") != factorial_validation["factorial_identity"]
            or metadata.get("schema_version") != str(SCHEMA_VERSION)
            or metadata.get("result_checksum") != _frame_checksum(frame)
        ):
            raise ValueError(f"Preserved factorial shard validation failed: {path}.")
        shard_rows += len(frame)
    if shard_rows != EXPECTED_NEW_EVALUATIONS:
        raise ValueError("Preserved factorial event-shard rows are incomplete.")
    free = shutil.disk_usage(root).free
    if free < MINIMUM_FREE_BYTES:
        raise ValueError("Fewer than 10 GiB remain free.")
    if PROJECTED_PRECISION_STORAGE_BYTES > PRECISION_MAX_NEW_STORAGE_BYTES:
        raise ValueError("Projected precision storage exceeds 300 MB.")
    return {
        **factorial_validation,
        "status": "passed",
        "r64_cell_count": len(cells),
        "r64_event_shard_count": len(shard_paths),
        "r64_checkpoint_count": len(list((root / "cells").glob("*/*.npz"))),
        "r64_rows": sum(len(frame) for frame in cells.values()),
        "precision_identity": build_precision_identity()[0],
        "projected_precision_storage_bytes": PROJECTED_PRECISION_STORAGE_BYTES,
        "precision_storage_cap_bytes": PRECISION_MAX_NEW_STORAGE_BYTES,
        "free_bytes": free,
    }


def audit_r64_precision(
    *,
    parent: Path = DEFAULT_PARENT,
) -> dict[str, Any]:
    """Persist the result-blind estimator audit and R=64 prefix diagnosis."""
    validation = validate_r64_precision_inputs(parent=parent)
    root = precision_directory(parent)
    root.mkdir(parents=True, exist_ok=True)
    cells = load_all_cells(parent=parent)
    audit, summary = construct_precision_audit(cells)
    comparison = set(_comparison_candidates())
    affected = {42, 94, 134}
    direct = audit.loc[
        audit["replication_prefix"].eq(REPLICATION_COUNT)
        & audit["candidate_index"].isin(sorted(comparison | affected))
    ].copy()
    _atomic_json(root / "precision_identity.json", {
        "precision_identity": build_precision_identity()[0],
        "design_inputs": build_precision_identity()[1],
    })
    _atomic_json(root / "estimator_ownership_audit.json", summary["ownership"])
    _atomic_csv(root / "r64_prefix_audit.csv", audit)
    _atomic_csv(root / "r64_direct_reconstruction.csv", direct)
    _atomic_json(
        root / "r64_audit_decision.json",
        {
            "schema_version": PRECISION_SCHEMA_VERSION,
            "precision_identity": build_precision_identity()[0],
            "comparison_candidates": list(_comparison_candidates()),
            "affected_candidates": [42, 94, 134],
            "pass_counts": summary["pass_counts"],
            "failing_candidates": summary["failing_candidates"],
            "gate_pass": summary["gate_pass"],
            "formula_error": not summary["ownership"]["same_estimand"],
            "extension_required": (
                summary["ownership"]["same_estimand"]
                and not summary["gate_pass"]
            ),
            "threshold_relaxed": False,
            "runtime_adopted": False,
        },
    )
    return {
        **validation,
        "precision_identity": build_precision_identity()[0],
        "ownership_status": summary["ownership"]["status"],
        "formula_error": not summary["ownership"]["same_estimand"],
        "pass_counts": summary["pass_counts"],
        "failing_candidates": summary["failing_candidates"],
        "audit_classifications": sorted(
            set(audit["audit_classification"].astype(str))
        ),
        "extension_required": (
            summary["ownership"]["same_estimand"] and not summary["gate_pass"]
        ),
        "diagnostic_paths": [
            str(root / "estimator_ownership_audit.json"),
            str(root / "r64_prefix_audit.csv"),
            str(root / "r64_direct_reconstruction.csv"),
            str(root / "r64_audit_decision.json"),
        ],
    }


def _precision_shard_path(root: Path, shard_index: int) -> Path:
    return root / "added_shards" / f"precision_event_shard_{shard_index:02d}.npz"


def _precision_checkpoint_path(
    root: Path,
    cell_id: str,
    candidate_index: int,
) -> Path:
    return (
        root
        / "checkpoints"
        / cell_id
        / f"candidate_{candidate_index:03d}.json"
    )


def _precision_frame_checksum(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values(
        ["cell_id", "candidate_index", "event_id", "replication"],
        kind="mergesort",
    )
    records = []
    for row in ordered.to_dict("records"):
        records.append(
            {
                key: (
                    bool(value)
                    if isinstance(value, (bool, np.bool_))
                    else int(value)
                    if isinstance(value, (int, np.integer))
                    else float(value)
                    if isinstance(value, (float, np.floating))
                    else str(value)
                )
                for key, value in row.items()
            }
        )
    return search.payload_sha256(records)


def _precision_worker_initialise(
    root_text: str,
    factorial_id: str,
    precision_id: str,
    base_liquidation_config: Any,
    demand_config: Any,
) -> None:
    """Initialise an extension worker without a shared configuration file."""
    _worker_initialise(
        root_text,
        factorial_id,
        base_liquidation_config,
        demand_config,
    )
    if _WORKER_OWNER is None:
        raise RuntimeError("Precision worker initialisation failed.")
    profiles = Path(root_text) / ".worker_profiles"
    profile_path = profiles / f"empirical_{os.getpid()}.yaml"
    search._atomic_bytes(
        profile_path,
        DEFAULT_TRANCHE_B_CONFIG_PATH.read_bytes(),
    )
    _WORKER_OWNER["precision_identity"] = precision_id
    _WORKER_OWNER["profile_path"] = profile_path
    search._ACTIVE_CACHE_CONFIG = _WORKER_OWNER["config"]


def _extension_base_package(
    owner: Mapping[str, Any],
    *,
    event_id: str,
    replication: int,
) -> search.CachedPackage:
    """Construct one continued registry-A package entirely in worker memory."""
    template = structural._package(owner, event_id, 0)
    path = template.path
    state = search.build_conditional_initial_state(
        event_id=event_id,
        replication=replication,
        registry_id=REGISTRY_A,
        initial_eth_price=float(path.observed_eth_prices[0]),
        profile_path=owner["profile_path"],
    )
    market_seed, residuals = search._residual_sequence(
        path=path,
        source=owner["stage1"]["source"],
        event_id=event_id,
        replication=replication,
        registry_id=REGISTRY_A,
    )
    liquidation_seed, liquidation = search._liquidation_evolution(
        state=state,
        path=path,
        replication=replication,
        registry_id=REGISTRY_A,
        profile_path=owner["profile_path"],
    )
    arrays = search._cache_arrays(
        state=state,
        path=path,
        residuals=residuals,
        liquidation=liquidation,
    )
    metadata = dict(template.metadata)
    metadata.update(
        {
            "replication": replication,
            "registry_id": REGISTRY_A,
            "initial_state_checksum": state.state_checksum,
            "vault_seed": state.vault_seed,
            "market_seed": market_seed,
            "liquidation_seed": liquidation_seed,
        }
    )
    return search.CachedPackage(
        metadata=metadata,
        arrays=arrays,
        path=path,
    )


def _precision_event_shard(
    task: tuple[int, tuple[str, ...]],
) -> dict[str, Any]:
    """Evaluate all eight cells for the exact added replication suffix."""
    if _WORKER_OWNER is None:
        raise RuntimeError("Precision worker is not initialised.")
    shard_index, event_ids = task
    owner = _WORKER_OWNER
    path = _precision_shard_path(owner["root"], shard_index)
    expected = (
        len(event_ids)
        * len(PRECISION_ADDED_REPLICATIONS)
        * len(CELL_ORDER)
        * len(PANEL_INDICES)
    )
    if path.is_file():
        frame, metadata = _arrays_to_frame(search._load_npz(path))
        if (
            len(frame) != expected
            or metadata.get("factorial_id") != owner["factorial_id"]
            or metadata.get("precision_identity") != owner["precision_identity"]
            or metadata.get("schema_version") != str(PRECISION_SCHEMA_VERSION)
            or metadata.get("result_checksum") != _precision_frame_checksum(frame)
        ):
            raise ValueError(f"Stale or incomplete precision shard: {path}.")
        return {
            "shard_index": shard_index,
            "evaluations": 0,
            "represented_evaluations": len(frame),
            "resumed": True,
        }
    cells = {cell.code: cell for cell in build_factorial_cells()}
    records: list[dict[str, Any]] = []
    for event_id in sorted(event_ids):
        for replication in PRECISION_ADDED_REPLICATIONS:
            package = _extension_base_package(
                owner,
                event_id=event_id,
                replication=replication,
            )
            p25_package = _apply_cell_package(
                package,
                cells["100"],
                owner,
            )
            for cell_id in CELL_ORDER:
                cell = cells[cell_id]
                cell_package, config = _apply_cell_package(
                    package,
                    cell,
                    owner,
                    precomputed_p25=(
                        p25_package if cell.vault_high else None
                    ),
                )
                context = search.WorkerContext(
                    run_dir=owner["root"],
                    search_id=owner["factorial_id"],
                    event_ids=(event_id,),
                    config=config,
                    stage1=owner["context"]["stage1"],
                    scaling=owner["context"]["scaling"],
                    ordinary_preservation=owner["context"]["ordinary_preservation"],
                    objective={},
                    candidates=owner["candidates"],
                    transformed=owner["transformed"],
                    packages={(event_id, replication): cell_package},
                )
                for candidate_index in PANEL_INDICES:
                    metrics, _, flags = search._evaluate_cached_event(
                        context,
                        candidate=owner["candidates"][candidate_index],
                        event_id=event_id,
                        replication=replication,
                    )
                    records.append(
                        {
                            "cell_id": cell_id,
                            "candidate_index": candidate_index,
                            **metrics,
                            "structural_pass": search.structural_event_flags_pass(
                                flags
                            ),
                        }
                    )
    frame = pd.DataFrame(records).sort_values(
        ["cell_id", "candidate_index", "event_id", "replication"],
        kind="mergesort",
    )
    frame = frame.loc[
        :,
        [
            "cell_id",
            "candidate_index",
            "event_id",
            "replication",
            *METRIC_COLUMNS,
            "structural_pass",
        ],
    ]
    if len(frame) != expected:
        raise ValueError("Precision shard evaluation count differs.")
    checksum = _precision_frame_checksum(frame)
    search._atomic_npz(
        path,
        _frame_to_arrays(
            frame,
            metadata={
                "schema_version": PRECISION_SCHEMA_VERSION,
                "factorial_id": owner["factorial_id"],
                "precision_identity": owner["precision_identity"],
                "replication_start": min(PRECISION_ADDED_REPLICATIONS),
                "replication_end_exclusive": max(PRECISION_ADDED_REPLICATIONS) + 1,
                "result_checksum": checksum,
            },
        ),
    )
    return {
        "shard_index": shard_index,
        "evaluations": len(frame),
        "represented_evaluations": len(frame),
        "resumed": False,
        "result_checksum": checksum,
    }


def _load_precision_added_frames(
    root: Path,
) -> dict[str, pd.DataFrame]:
    identity = build_precision_identity()[0]
    factorial_id = build_factorial_identity()[0]
    paths = sorted((root / "added_shards").glob("precision_event_shard_*.npz"))
    if not paths:
        raise ValueError("No precision-extension shards are available.")
    frames = []
    for path in paths:
        frame, metadata = _arrays_to_frame(search._load_npz(path))
        if (
            metadata.get("factorial_id") != factorial_id
            or metadata.get("precision_identity") != identity
            or metadata.get("result_checksum") != _precision_frame_checksum(frame)
        ):
            raise ValueError(f"Precision-extension shard validation failed: {path}.")
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    if len(combined) != EXPECTED_PRECISION_NEW_EVALUATIONS:
        raise ValueError("Precision-extension rows are incomplete.")
    if combined[
        ["cell_id", "candidate_index", "event_id", "replication"]
    ].duplicated().any():
        raise ValueError("Precision-extension shards contain duplicate rows.")
    expected_replications = set(PRECISION_ADDED_REPLICATIONS)
    if set(int(value) for value in combined["replication"].unique()) != expected_replications:
        raise ValueError("Precision-extension replication ownership differs.")
    return {
        code: combined.loc[combined["cell_id"].eq(code)]
        .drop(columns=["cell_id"])
        .sort_values(
            ["candidate_index", "event_id", "replication"],
            kind="mergesort",
        )
        .reset_index(drop=True)
        for code in CELL_ORDER
    }


def _write_precision_checkpoints(
    *,
    root: Path,
    parent: Path,
) -> int:
    original = load_all_cells(parent=parent)
    added = _load_precision_added_frames(root)
    precision_id = build_precision_identity()[0]
    factorial_id = build_factorial_identity()[0]
    written = 0
    for cell_id in CELL_ORDER:
        for candidate_index in PANEL_INDICES:
            path = _precision_checkpoint_path(
                root,
                cell_id,
                candidate_index,
            )
            original_frame = original[cell_id].loc[
                original[cell_id]["candidate_index"].eq(candidate_index)
            ].reset_index(drop=True)
            added_frame = added[cell_id].loc[
                added[cell_id]["candidate_index"].eq(candidate_index)
            ].reset_index(drop=True)
            combined = pd.concat(
                [original_frame, added_frame],
                ignore_index=True,
            )
            if (
                len(original_frame) != EVENT_COUNT * REPLICATION_COUNT
                or len(added_frame)
                != EVENT_COUNT * len(PRECISION_ADDED_REPLICATIONS)
                or len(combined)
                != EVENT_COUNT * PRECISION_FINAL_REPLICATION_COUNT
            ):
                raise ValueError("Precision checkpoint rows are incomplete.")
            original_checksum = _frame_checksum(original_frame)
            added_checksum = _frame_checksum(added_frame)
            combined_checksum = _frame_checksum(combined)
            prefix_checksum = _frame_checksum(
                combined.loc[combined["replication"].lt(REPLICATION_COUNT)]
            )
            payload = {
                "schema_version": PRECISION_SCHEMA_VERSION,
                "factorial_identity": factorial_id,
                "precision_validation_identity": precision_id,
                "cell_id": cell_id,
                "candidate_index": candidate_index,
                "original_replication_count": REPLICATION_COUNT,
                "added_replication_count": len(PRECISION_ADDED_REPLICATIONS),
                "combined_replication_count": PRECISION_FINAL_REPLICATION_COUNT,
                "event_count": EVENT_COUNT,
                "registry": REGISTRY_A,
                "original_64_replication_checksum": original_checksum,
                "added_64_replication_checksum": added_checksum,
                "combined_128_replication_checksum": combined_checksum,
                "exact_prefix_checksum": prefix_checksum,
                "exact_prefix_valid": prefix_checksum == original_checksum,
                "added_data_storage": "shared_atomic_event_shards",
                "runtime_adopted": False,
            }
            if not payload["exact_prefix_valid"]:
                raise ValueError("The R=64 precision prefix changed.")
            if path.is_file():
                if _json(path) != payload:
                    raise ValueError(f"Precision checkpoint identity differs: {path}.")
            else:
                _atomic_json(path, payload)
                written += 1
    return written


def load_r128_cells(
    *,
    parent: Path = DEFAULT_PARENT,
) -> dict[str, pd.DataFrame]:
    """Load the immutable R=64 prefixes plus the shared R=128 suffix."""
    root = precision_directory(parent)
    original = load_all_cells(parent=parent)
    added = _load_precision_added_frames(root)
    checkpoints = list((root / "checkpoints").glob("*/*.json"))
    if len(checkpoints) != EXPECTED_PRECISION_CHECKPOINTS:
        raise ValueError("Precision checkpoint metadata are incomplete.")
    result: dict[str, pd.DataFrame] = {}
    expected_replications = set(range(PRECISION_FINAL_REPLICATION_COUNT))
    for cell_id in CELL_ORDER:
        frame = pd.concat(
            [original[cell_id], added[cell_id]],
            ignore_index=True,
        ).sort_values(
            ["candidate_index", "event_id", "replication"],
            kind="mergesort",
        ).reset_index(drop=True)
        expected_rows = (
            len(PANEL_INDICES) * EVENT_COUNT * PRECISION_FINAL_REPLICATION_COUNT
        )
        if len(frame) != expected_rows:
            raise ValueError(f"R=128 cell {cell_id} is incomplete.")
        for candidate_index in PANEL_INDICES:
            subset = frame.loc[frame["candidate_index"].eq(candidate_index)]
            if (
                subset["event_id"].nunique() != EVENT_COUNT
                or set(int(value) for value in subset["replication"].unique())
                != expected_replications
                or subset[
                    ["event_id", "replication"]
                ].duplicated().any()
            ):
                raise ValueError(
                    f"R=128 cell {cell_id} candidate {candidate_index} differs."
                )
            checkpoint = _json(
                _precision_checkpoint_path(root, cell_id, candidate_index)
            )
            if checkpoint["combined_128_replication_checksum"] != _frame_checksum(
                subset.reset_index(drop=True)
            ):
                raise ValueError("R=128 combined checkpoint checksum differs.")
        result[cell_id] = frame
    return result


def run_precision_extension(
    *,
    parent: Path = DEFAULT_PARENT,
    workers: int = 4,
    resume: bool = False,
) -> dict[str, Any]:
    """Run or resume the uniform, pre-registered R=128 continuation."""
    if workers < 1 or workers > 6:
        raise ValueError("workers must be between one and six.")
    audit = audit_r64_precision(parent=parent)
    if audit["formula_error"]:
        raise ValueError("A formula error must be resolved before simulation.")
    if not audit["extension_required"]:
        raise ValueError("The fixed R=64 gate does not require an extension.")
    root = precision_directory(parent)
    existing = list((root / "added_shards").glob("*.npz"))
    checkpoints = list((root / "checkpoints").glob("*/*.json"))
    if (existing or checkpoints) and not resume:
        raise ValueError("Precision diagnostics exist; use explicit resume.")
    event_ids = tuple(sorted(structural._load_cache_owner()["context"]["event_ids"]))
    event_shards = tuple(
        tuple(event_ids[offset::workers])
        for offset in range(workers)
        if event_ids[offset::workers]
    )
    tasks = tuple(enumerate(event_shards))
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    base_liquidation_config = bundle.base_bundle.liquidation_config
    demand_config = _liquidation_demand_config(
        DEFAULT_TRANCHE_B_CONFIG_PATH,
        seed=0,
    )
    started = time.perf_counter()
    profiles = root / ".worker_profiles"
    try:
        context = mp.get_context("spawn")
        with context.Pool(
            processes=len(tasks),
            initializer=_precision_worker_initialise,
            initargs=(
                str(root),
                build_factorial_identity()[0],
                build_precision_identity()[0],
                base_liquidation_config,
                demand_config,
            ),
        ) as pool:
            results = pool.map(_precision_event_shard, tasks)
    finally:
        if profiles.exists():
            shutil.rmtree(profiles)
    written = _write_precision_checkpoints(root=root, parent=parent)
    elapsed = time.perf_counter() - started
    checkpoint_count = len(list((root / "checkpoints").glob("*/*.json")))
    if checkpoint_count != EXPECTED_PRECISION_CHECKPOINTS:
        raise ValueError("Precision checkpoints are incomplete.")
    history_path = root / "run_history.json"
    history = (
        _json(history_path)
        if history_path.is_file()
        else {"schema_version": PRECISION_SCHEMA_VERSION, "runs": []}
    )
    history["runs"].append(
        {
            "action": "resume" if resume else "extend",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "workers": workers,
            "duration_seconds": elapsed,
            "new_evaluations": sum(int(item["evaluations"]) for item in results),
            "represented_new_evaluations": EXPECTED_PRECISION_NEW_EVALUATIONS,
            "checkpoint_count": checkpoint_count,
            "checkpoints_written": written,
            "event_shard_count": len(tasks),
        }
    )
    _atomic_json(history_path, history)
    size = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    if size > PRECISION_MAX_NEW_STORAGE_BYTES:
        raise ValueError("Precision diagnostics exceed the 300 MB cap.")
    load_r128_cells(parent=parent)
    return {
        "status": "completed",
        "factorial_identity": build_factorial_identity()[0],
        "precision_identity": build_precision_identity()[0],
        "workers": workers,
        "duration_seconds": elapsed,
        "reused_evaluations": EXPECTED_PRECISION_REUSED_EVALUATIONS,
        "new_evaluations": EXPECTED_PRECISION_NEW_EVALUATIONS,
        "new_evaluations_this_run": sum(
            int(item["evaluations"]) for item in results
        ),
        "total_represented_evaluations": EXPECTED_PRECISION_TOTAL_EVALUATIONS,
        "checkpoint_count": checkpoint_count,
        "checkpoints_written": written,
        "event_shard_count": len(tasks),
        "ignored_output_size_bytes": size,
        "storage_cap_bytes": PRECISION_MAX_NEW_STORAGE_BYTES,
        "runtime_adopted": False,
    }


def construct_interactions(
    cells: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    constraints = _constraints()
    rows = []
    for cell_id in INTERACTION_CELLS:
        residual_weights = ADDITIVE_COMPONENTS[cell_id]
        actual_weights = {cell_id: 1.0}
        additive_weights = dict(residual_weights)
        additive_weights[cell_id] -= 1.0
        additive_weights = {
            code: -weight
            for code, weight in additive_weights.items()
            if weight != 0.0
        }
        for index in PANEL_INDICES:
            for moment in STAGE2_ACTIVE_MOMENTS:
                source = _moment_source(moment)
                residual_frame = _linear_combination_frame(
                    cells,
                    candidate_index=index,
                    source=source,
                    weights=residual_weights,
                )
                actual_frame = _linear_combination_frame(
                    cells,
                    candidate_index=index,
                    source=source,
                    weights=actual_weights,
                )
                additive_frame = _linear_combination_frame(
                    cells,
                    candidate_index=index,
                    source=source,
                    weights=additive_weights,
                )
                residual = _estimate_contrast(residual_frame, moment=moment)
                actual = _estimate_contrast(actual_frame, moment=moment)
                additive = _estimate_contrast(additive_frame, moment=moment)
                band = constraints.loc[moment]
                lower = float(band["adjusted_band_lower"])
                upper = float(band["adjusted_band_upper"])
                scale = float(band["empirical_scale"])
                additive_gap = structural.signed_band_gap(
                    additive.point_estimate, lower, upper
                )
                actual_gap = structural.signed_band_gap(
                    actual.point_estimate, lower, upper
                )
                reduction = abs(additive_gap) - abs(actual_gap)
                direction = (
                    "towards_band"
                    if reduction > 0.0
                    else "away_from_band"
                    if reduction < 0.0
                    else "unchanged"
                )
                mcse = float(residual.diagnostic_mcse)
                rows.append(
                    {
                        "interaction_cell": cell_id,
                        "candidate_index": index,
                        "moment": moment,
                        "additive_prediction": additive.point_estimate,
                        "actual_result": actual.point_estimate,
                        "interaction_residual": residual.point_estimate,
                        "paired_mcse": mcse,
                        "analytic_mcse": residual.analytic_mcse,
                        "replication_index_mcse": residual.replication_index_mcse,
                        "mcse_agreement_pass": residual.agreement_pass,
                        "snr": (
                            math.inf
                            if mcse == 0.0 and residual.point_estimate != 0.0
                            else 0.0
                            if mcse == 0.0
                            else abs(residual.point_estimate) / mcse
                        ),
                        "empirical_scale": scale,
                        "additive_band_gap": additive_gap,
                        "actual_band_gap": actual_gap,
                        "band_gap_reduction": reduction,
                        "band_gap_reduction_scales": reduction / scale,
                        "direction": direction,
                        "large_residual": abs(residual.point_estimate) >= 0.5 * scale,
                        "precise_residual": (
                            mcse == 0.0
                            and residual.point_estimate != 0.0
                        )
                        or (
                            mcse > 0.0
                            and abs(residual.point_estimate) / mcse >= 2.0
                        ),
                        "large_and_precise": (
                            abs(residual.point_estimate) >= 0.5 * scale
                            and (
                                (
                                    mcse == 0.0
                                    and residual.point_estimate != 0.0
                                )
                                or (
                                    mcse > 0.0
                                    and abs(residual.point_estimate) / mcse >= 2.0
                                )
                            )
                        ),
                    }
                )
    return pd.DataFrame(rows).sort_values(
        ["interaction_cell", "candidate_index", "moment"], kind="mergesort"
    ).reset_index(drop=True)


def classify_interaction(group: pd.DataFrame) -> dict[str, Any]:
    """Apply the fixed directional, magnitude, precision and scale rules."""
    if (
        group["candidate_index"].nunique() != 16
        or not group["mcse_agreement_pass"].astype(bool).all()
    ):
        return {
            "classification": "interaction_invalid",
            "towards_count": 0,
            "away_count": 0,
            "large_precise_count": 0,
            "median_absolute_gap_difference_scales": math.nan,
        }
    towards = int(group["direction"].eq("towards_band").sum())
    away = int(group["direction"].eq("away_from_band").sum())
    large_precise = int(group["large_and_precise"].astype(bool).sum())
    median_gap = float(group["band_gap_reduction_scales"].abs().median())
    magnitude_material = large_precise >= 8 and median_gap >= 0.5
    if magnitude_material and towards >= 12:
        classification = "synergistic_towards_band"
    elif magnitude_material and away >= 12:
        classification = "antagonistic_away_from_band"
    elif magnitude_material:
        classification = "material_mixed_interaction"
    else:
        classification = "approximately_additive"
    return {
        "classification": classification,
        "towards_count": towards,
        "away_count": away,
        "large_precise_count": large_precise,
        "median_absolute_gap_difference_scales": median_gap,
    }


def _cell_baseline_effects(
    cells: Mapping[str, pd.DataFrame],
    *,
    cell_id: str,
) -> pd.DataFrame:
    constraints = _constraints()
    rows = []
    for index in PANEL_INDICES:
        for moment in STAGE2_ACTIVE_MOMENTS:
            source = _moment_source(moment)
            frame = _linear_combination_frame(
                cells,
                candidate_index=index,
                source=source,
                weights={cell_id: 1.0, "000": -1.0},
            )
            paired = _estimate_contrast(frame, moment=moment)
            actual = _moment_estimate(
                cells[cell_id].loc[
                    cells[cell_id]["candidate_index"].eq(index)
                ],
                moment,
            )
            baseline = _moment_estimate(
                cells["000"].loc[cells["000"]["candidate_index"].eq(index)],
                moment,
            )
            band = constraints.loc[moment]
            lower = float(band["adjusted_band_lower"])
            upper = float(band["adjusted_band_upper"])
            scale = float(band["empirical_scale"])
            actual_gap = structural.signed_band_gap(
                actual.point_estimate, lower, upper
            )
            baseline_gap = structural.signed_band_gap(
                baseline.point_estimate, lower, upper
            )
            mcse = float(paired.diagnostic_mcse)
            rows.append(
                {
                    "cell_id": cell_id,
                    "candidate_index": index,
                    "moment": moment,
                    "paired_shift": paired.point_estimate,
                    "paired_mcse": mcse,
                    "snr": (
                        math.inf
                        if mcse == 0.0 and paired.point_estimate != 0.0
                        else 0.0
                        if mcse == 0.0
                        else abs(paired.point_estimate) / mcse
                    ),
                    "shift_scales": paired.point_estimate / scale,
                    "baseline_gap_scales": baseline_gap / scale,
                    "actual_gap_scales": actual_gap / scale,
                    "gap_reduction_scales": (
                        abs(baseline_gap) - abs(actual_gap)
                    )
                    / scale,
                    "towards_band": abs(actual_gap) < abs(baseline_gap),
                    "away_from_band": abs(actual_gap) > abs(baseline_gap),
                }
            )
    return pd.DataFrame(rows)


def _material_improvement(group: pd.DataFrame) -> bool:
    return bool(
        group["towards_band"].astype(bool).sum() >= 12
        and (
            group["shift_scales"].abs().ge(0.5)
            & group["snr"].ge(2.0)
        ).sum()
        >= 8
        and group["gap_reduction_scales"].median() >= 0.5
    )


def _material_worsening(group: pd.DataFrame) -> bool:
    return bool(
        (
            group["away_from_band"].astype(bool)
            & (
                group["actual_gap_scales"].abs()
                - group["baseline_gap_scales"].abs()
            ).ge(1.0)
            & group["snr"].ge(2.0)
        ).sum()
        >= 12
    )


def _cell_summary(
    cells: Mapping[str, pd.DataFrame],
    cell_evidence: pd.DataFrame,
    interactions: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline_valid = int(
        cell_evidence.loc[
            cell_evidence["cell_id"].eq("000")
            & cell_evidence["moment"].eq(STAGE2_ACTIVE_MOMENTS[0]),
            "numerical_bound_pass",
        ].sum()
    )
    interaction_classes = {}
    for (cell_id, moment), group in interactions.groupby(
        ["interaction_cell", "moment"], sort=True
    ):
        interaction_classes[(cell_id, moment)] = classify_interaction(group)
    summaries: dict[str, Any] = {}
    mechanism_rows = []
    for cell_id in CELL_ORDER:
        evidence = cell_evidence.loc[cell_evidence["cell_id"].eq(cell_id)]
        by_candidate = evidence.groupby("candidate_index", sort=True)
        inner = by_candidate.apply(
            lambda group: bool(
                group["inner_pass"].astype(bool).all()
                and group["structural_validity"].astype(bool).all()
                and group["stage1_preservation"].astype(bool).all()
                and group["numerical_bound_pass"].astype(bool).all()
            ),
            include_groups=False,
        )
        outer = by_candidate.apply(
            lambda group: bool(
                group["outer_pass"].astype(bool).all()
                and group["structural_validity"].astype(bool).all()
                and group["stage1_preservation"].astype(bool).all()
                and group["numerical_bound_pass"].astype(bool).all()
            ),
            include_groups=False,
        )
        numerical_valid = int(
            evidence.loc[
                evidence["moment"].eq(STAGE2_ACTIVE_MOMENTS[0]),
                "numerical_bound_pass",
            ].sum()
        )
        structural_failures = int(
            (~evidence["structural_validity"].astype(bool)).sum()
        )
        stage1_failures = int(
            (~evidence["stage1_preservation"].astype(bool)).sum()
        )
        resolved = []
        per_moment = {}
        for moment, group in evidence.groupby("moment", sort=True):
            inner_count = int(group["inner_pass"].astype(bool).sum())
            outer_count = int(group["outer_pass"].astype(bool).sum())
            resolution = bool(
                outer_count >= 12
                and structural_failures == 0
                and stage1_failures == 0
                and numerical_valid >= baseline_valid - 4
            )
            if resolution:
                resolved.append(moment)
            per_moment[moment] = {
                "inner_pass_count": inner_count,
                "outer_pass_count": outer_count,
                "resolved": resolution,
            }
        baseline_effects = _cell_baseline_effects(cells, cell_id=cell_id)
        improved = [
            moment
            for moment, group in baseline_effects.groupby("moment", sort=True)
            if _material_improvement(group)
        ]
        worsened = [
            moment
            for moment, group in baseline_effects.groupby("moment", sort=True)
            if _material_worsening(group)
        ]
        tradeoff = bool((resolved or improved) and worsened)
        material_interaction_moments = [
            moment
            for moment in STAGE2_ACTIVE_MOMENTS
            if (cell_id, moment) in interaction_classes
            and interaction_classes[(cell_id, moment)]["classification"]
            in {
                "synergistic_towards_band",
                "antagonistic_away_from_band",
                "material_mixed_interaction",
            }
        ]
        if structural_failures or stage1_failures:
            classification = "structurally_invalid"
        elif int(outer.sum()) >= 12 and numerical_valid >= 12:
            classification = "panel_wide_compatibility"
        elif 1 <= int(outer.sum()) <= 11:
            classification = "limited_panel_compatibility"
        elif len(resolved) >= 3:
            classification = "constraint_improvement_without_full_compatibility"
        elif 1 <= len(resolved) <= 2:
            classification = "partial_constraint_improvement"
        elif len(material_interaction_moments) >= 2:
            classification = "partial_constraint_improvement"
        else:
            classification = "no_compatibility_improvement"
        first = evidence.loc[
            evidence["moment"].eq(STAGE2_ACTIVE_MOMENTS[0])
        ].sort_values("candidate_index")
        mechanism = {
            "censoring_share_mean": float(first["censoring_share"].mean()),
            "recovery_probability_48h_mean": float(
                first["recovery_probability_48h"].mean()
            ),
            "recovery_probability_168h_mean": float(
                first["recovery_probability_168h"].mean()
            ),
            "recovery_probability_792h_mean": float(
                first["recovery_probability_792h"].mean()
            ),
            "failed_recovery_attempts_mean": float(
                first["failed_recovery_attempts_diagnostic"].mean()
            ),
            "numerical_bound_share_mean": float(
                first["numerical_bound_share"].mean()
            ),
            "confidence_floor_binding_share_mean": float(
                first["confidence_floor_binding_share"].mean()
            ),
            "unresolved_backlog_occurrence_count": int(
                first["unresolved_backlog_occurrence"].astype(bool).sum()
            ),
            "maximum_unresolved_tab_dai": float(
                first["maximum_unresolved_tab_dai"].max()
            ),
            "active_bad_debt_occurrence_count": int(
                first["active_bad_debt_occurrence"].astype(bool).sum()
            ),
            "maximum_active_bad_debt_dai": float(
                first["maximum_active_bad_debt_dai"].max()
            ),
        }
        mechanism_rows.append({"cell_id": cell_id, **mechanism})
        summaries[cell_id] = {
            "inner_compatible_count": int(inner.sum()),
            "outer_compatible_count": int(outer.sum()),
            "outer_only_count": int((outer & ~inner).sum()),
            "rejected_count": int((~outer).sum()),
            "numerical_bound_valid_count": numerical_valid,
            "structural_failure_count": structural_failures,
            "stage1_preservation_failure_count": stage1_failures,
            "per_moment": per_moment,
            "resolved_moments": resolved,
            "materially_improved_moments": improved,
            "tradeoff": {
                "registered": tradeoff,
                "improved_moments": sorted(set(resolved) | set(improved)),
                "worsened_moments": worsened,
            },
            "panel_compatibility_classification": classification,
            "mechanism_diagnostics": mechanism,
            "selected": False,
            "runtime_adopted": False,
        }
    return summaries, {
        "schema_version": SCHEMA_VERSION,
        "rows": mechanism_rows,
        "empirical_constraint": False,
    }


def _interaction_summary(
    interactions: pd.DataFrame,
) -> dict[str, Any]:
    records = []
    for (cell_id, moment), group in interactions.groupby(
        ["interaction_cell", "moment"], sort=True
    ):
        records.append(
            {
                "interaction_cell": cell_id,
                "interaction_order": 3 if cell_id == "111" else 2,
                "moment": moment,
                **classify_interaction(group),
            }
        )
    classes = defaultdict(list)
    for record in records:
        classes[record["classification"]].append(
            {
                "interaction_cell": record["interaction_cell"],
                "moment": record["moment"],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "classifications": records,
        "synergistic_interactions": classes["synergistic_towards_band"],
        "antagonistic_interactions": classes["antagonistic_away_from_band"],
        "mixed_interactions": classes["material_mixed_interaction"],
        "approximately_additive_interactions": classes["approximately_additive"],
        "invalid_interactions": classes["interaction_invalid"],
        "mechanism_interpretation": (
            "Interaction directions use empirical-band gaps; mechanism metrics "
            "remain diagnostic and are not empirical constraints."
        ),
        "cell_ranked": False,
        "runtime_adopted": False,
    }


def _overall_decision(
    cell_summary: Mapping[str, Any],
    interaction_summary: Mapping[str, Any],
) -> dict[str, Any]:
    new = {code: cell_summary[code] for code in NEW_CELLS}
    panel = [
        code for code in NEW_CELLS
        if new[code]["panel_compatibility_classification"]
        == "panel_wide_compatibility"
        and not new[code]["tradeoff"]["registered"]
    ]
    limited = [
        code for code in NEW_CELLS
        if (
            new[code]["panel_compatibility_classification"]
            == "limited_panel_compatibility"
            or (
                len(new[code]["resolved_moments"]) >= 3
                and not new[code]["tradeoff"]["registered"]
            )
        )
    ]
    combined_improvers = [
        code for code in NEW_CELLS
        if len(
            set(new[code]["resolved_moments"])
            | set(new[code]["materially_improved_moments"])
        )
        >= 2
    ]
    important_interactions = [
        item
        for item in interaction_summary["classifications"]
        if item["classification"] != "approximately_additive"
    ]
    if panel:
        classification = "factorial_panel_compatibility_signal"
        boundary = (
            "Undertake a substantive structural-justification review and define "
            "a versioned revised conditional-event experiment from independently "
            "defensible assumptions before rerunning the 256-vector grid."
        )
    elif limited:
        classification = "factorial_limited_compatibility_signal"
        boundary = (
            "Inspect compatible candidate-cell mechanisms and independently "
            "justify any revised structural formulation; do not search again yet."
        )
    elif combined_improvers and (
        all(new[code]["tradeoff"]["registered"] for code in combined_improvers)
        or not panel
    ):
        classification = "factorial_interactions_reveal_tradeoffs"
        boundary = (
            "End empirical calibration rescue for the present confidence "
            "formulation, retain confidence parameters as transparent scenario "
            "dimensions, and document the structural trade-offs."
        )
    elif (
        not any(
            cell_summary[code]["outer_compatible_count"]
            for code in NEW_CELLS
        )
        and max(len(cell_summary[code]["resolved_moments"]) for code in NEW_CELLS)
        < 3
        and not important_interactions
    ):
        classification = "factorial_effects_approximately_additive_and_insufficient"
        boundary = (
            "End empirical Stage 2 calibration for the present formulation and "
            "use transparent pre-specified behavioural scenarios."
        )
    else:
        classification = "factorial_interactions_reveal_tradeoffs"
        boundary = (
            "End empirical calibration rescue for the present confidence "
            "formulation and document the unresolved non-additive trade-offs."
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "final_classification": classification,
        "cells_by_panel_classification": {
            category: [
                code for code in CELL_ORDER
                if cell_summary[code]["panel_compatibility_classification"]
                == category
            ]
            for category in (
                "panel_wide_compatibility",
                "limited_panel_compatibility",
                "constraint_improvement_without_full_compatibility",
                "partial_constraint_improvement",
                "no_compatibility_improvement",
                "structurally_invalid",
            )
        },
        "unresolved_constraints": [
            moment
            for moment in STAGE2_ACTIVE_MOMENTS
            if not any(
                moment in cell_summary[code]["resolved_moments"]
                for code in CELL_ORDER
            )
        ],
        "interaction_findings": {
            "synergistic_count": len(
                interaction_summary["synergistic_interactions"]
            ),
            "antagonistic_count": len(
                interaction_summary["antagonistic_interactions"]
            ),
            "mixed_count": len(interaction_summary["mixed_interactions"]),
            "approximately_additive_count": len(
                interaction_summary["approximately_additive_interactions"]
            ),
        },
        "tradeoff_cells": [
            code for code in CELL_ORDER
            if cell_summary[code]["tradeoff"]["registered"]
        ],
        "authorised_next_boundary": boundary,
        "selected_cell": None,
        "selected_parameter": None,
        "structural_model_selected": False,
        "candidate_ranked": False,
        "cell_ranked": False,
        "runtime_adopted": False,
    }


def _register_manifest(
    evidence_dir: Path,
    *,
    names: Sequence[str] = EVIDENCE_NAMES,
) -> None:
    manifest_path = REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
    manifest = _json(manifest_path)
    artefacts = {item["path"]: item for item in manifest["artefacts"]}
    for name in names:
        path = evidence_dir / name
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        artefacts[relative] = {
            "path": relative,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "producer": "dai_sim.calibration.structural_factorial",
            "classification": "snapshot",
            "semantic_name": path.stem,
            "schema": "Compact objective-blind structural-factorial evidence.",
            "context": (
                "Fixed 2^3 diagnostic; no candidate, cell, parameter or "
                "structural model is ranked or selected."
            ),
            "runtime_adopted": False,
        }
    manifest["artefacts"] = [artefacts[key] for key in sorted(artefacts)]
    search._atomic_bytes(
        manifest_path,
        (
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False)
            + "\n"
        ).encode("utf-8"),
    )


def summarise_factorial(
    *,
    parent: Path = DEFAULT_PARENT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    register_manifest: bool = True,
    cells_override: Mapping[str, pd.DataFrame] | None = None,
    replication_count: int = REPLICATION_COUNT,
    precision_identity: str | None = None,
) -> dict[str, Any]:
    """Construct compact evidence from the eight complete factorial cells."""
    validation = validate_factorial_inputs(parent=parent, evidence_dir=evidence_dir)
    root = factorial_directory(parent)
    cells = (
        load_all_cells(parent=parent)
        if cells_override is None
        else {code: cells_override[code] for code in CELL_ORDER}
    )
    registry = _cell_registry()
    cell_evidence = construct_cell_evidence(cells)
    effects = construct_factorial_effects(cells)
    interactions = construct_interactions(cells)
    interaction_summary = _interaction_summary(interactions)
    cell_summary, mechanism = _cell_summary(cells, cell_evidence, interactions)
    decision = _overall_decision(cell_summary, interaction_summary)
    specification = {
        "schema_version": SCHEMA_VERSION,
        "factorial_identity": registry["factorial_identity"],
        "factors": _factor_definitions(),
        "factor_order": list(FACTOR_ORDER),
        "cells": list(CELL_ORDER),
        "reused_cells": list(REUSED_CELLS),
        "new_cells": list(NEW_CELLS),
        "candidate_panel": list(PANEL_INDICES),
        "candidate_panel_sha256": PANEL_SHA256,
        "events": EVENT_COUNT,
        "replications": replication_count,
        "precision_validation_identity": precision_identity,
        "registry": REGISTRY_A,
        "empirical_bands": registry["design_identity_inputs"][
            "empirical_support_bands"
        ],
        "compatibility_rules": {
            "inner": "all five means inside bands plus all hard gates",
            "outer": "all five 90% MC intervals overlap bands plus all hard gates",
            "constraint_resolution": (
                "12/16 outer passes, zero structural and Stage 1 failures, "
                "and at most four fewer numerical-valid candidates than cell 000"
            ),
        },
        "interaction_rules": registry["design_identity_inputs"][
            "interaction_classification_schema"
        ],
        "outcome_hierarchy": [
            "factorial_panel_compatibility_signal",
            "factorial_limited_compatibility_signal",
            "factorial_interactions_reveal_tradeoffs",
            "factorial_effects_approximately_additive_and_insufficient",
            "factorial_diagnosis_invalid",
        ],
        "scalar_objective": None,
        "candidate_ranked": False,
        "cell_ranked": False,
        "cell_selected": False,
        "parameter_selected": False,
        "runtime_adopted": False,
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(evidence_dir / EVIDENCE_NAMES[0], specification)
    _atomic_json(evidence_dir / EVIDENCE_NAMES[1], registry)
    _atomic_csv(evidence_dir / EVIDENCE_NAMES[2], cell_evidence)
    _atomic_csv(evidence_dir / EVIDENCE_NAMES[3], effects)
    _atomic_csv(evidence_dir / EVIDENCE_NAMES[4], interactions)
    _atomic_json(
        evidence_dir / EVIDENCE_NAMES[5],
        {
            "schema_version": SCHEMA_VERSION,
            "cells": cell_summary,
            "cell_order": list(CELL_ORDER),
            "ranked": False,
            "runtime_adopted": False,
        },
    )
    _atomic_json(evidence_dir / EVIDENCE_NAMES[6], interaction_summary)
    _atomic_json(evidence_dir / EVIDENCE_NAMES[7], decision)
    diagnostic_mechanism = root / "mechanism_diagnostics.json"
    _atomic_json(diagnostic_mechanism, mechanism)
    checkpoint_paths = sorted((root / "cells").glob("*/*.npz"))
    deterministic_paths = [evidence_dir / name for name in EVIDENCE_NAMES[:8]]
    reproducibility = {
        "schema_version": SCHEMA_VERSION,
        "factorial_identity": registry["factorial_identity"],
        "source_structural_diagnosis_identity": sha256_file(
            STRUCTURAL_DECISION_PATH
        ),
        "panel_sha256": PANEL_SHA256,
        "reused_cell_identities": {
            item["binary_code"]: item["source_checkpoint_identity"]
            for item in registry["cells"]
            if item["status"] == "reused"
        },
        "new_cell_identities": {
            item["binary_code"]: item["cell_checksum"]
            for item in registry["cells"]
            if item["status"] == "newly_evaluated"
        },
        "paired_stream_ownership": (
            "registry-A event, replication, market, vault and liquidation stream "
            "identities are shared across all cells except the declared factor."
        ),
        "new_checkpoint_count": len(checkpoint_paths),
        "new_checkpoint_checksums": {
            path.relative_to(root).as_posix(): sha256_file(path)
            for path in checkpoint_paths
        },
        "reused_evaluations": (
            EXPECTED_REUSED_EVALUATIONS
            if replication_count == REPLICATION_COUNT
            else EXPECTED_PRECISION_REUSED_EVALUATIONS
        ),
        "new_evaluations": (
            EXPECTED_NEW_EVALUATIONS
            if replication_count == REPLICATION_COUNT
            else EXPECTED_PRECISION_NEW_EVALUATIONS
        ),
        "total_represented_evaluations": (
            EXPECTED_TOTAL_EVALUATIONS
            if replication_count == REPLICATION_COUNT
            else EXPECTED_PRECISION_TOTAL_EVALUATIONS
        ),
        "precision_validation_identity": precision_identity,
        "deterministic_evidence_checksums": {
            path.name: sha256_file(path) for path in deterministic_paths
        },
        "objective_ranking_used": False,
        "candidate_ranking_used": False,
        "cell_ranking_used": False,
        "final_validation_data_used": False,
        "registry_b_used": False,
        "usdc_svb_simulations": 0,
        "selected_cell": None,
        "selected_parameter": None,
        "runtime_adopted": False,
    }
    _atomic_json(evidence_dir / EVIDENCE_NAMES[8], reproducibility)
    history = _json(root / "run_history.json")
    wall_time = sum(float(item["duration_seconds"]) for item in history["runs"])
    if precision_identity is not None:
        precision_history = _json(
            precision_directory(parent) / "run_history.json"
        )
        wall_time += sum(
            float(item["duration_seconds"])
            for item in precision_history["runs"]
        )
    ignored_size = sum(
        path.stat().st_size for path in root.rglob("*") if path.is_file()
    )
    largest = max(
        (path.stat().st_size for path in checkpoint_paths),
        default=0,
    )
    benchmark = {
        "schema_version": SCHEMA_VERSION,
        "reused_evaluations": reproducibility["reused_evaluations"],
        "new_evaluations": reproducibility["new_evaluations"],
        "total_represented_evaluations": reproducibility[
            "total_represented_evaluations"
        ],
        "worker_count": max(
            int(item["workers"])
            for item in (
                history["runs"]
                + (
                    precision_history["runs"]
                    if precision_identity is not None
                    else []
                )
            )
        ),
        "wall_time_seconds": wall_time,
        "throughput_new_evaluations_per_second": (
            reproducibility["new_evaluations"] / wall_time
        ),
        "peak_memory_bytes": None,
        "ignored_output_size_bytes": ignored_size,
        "largest_checkpoint_bytes": largest,
        "host_dependent": True,
        "projected_full_grid_structural_rerun": (
            "not authorised; requires an independently justified revised design"
        ),
    }
    _atomic_json(evidence_dir / EVIDENCE_NAMES[9], benchmark)
    if register_manifest:
        _register_manifest(evidence_dir)
    return {
        **validation,
        "status": "completed",
        "final_classification": decision["final_classification"],
        "factorial_identity": registry["factorial_identity"],
        "replications": replication_count,
        "reused_evaluations": reproducibility["reused_evaluations"],
        "new_evaluations": reproducibility["new_evaluations"],
        "total_represented_evaluations": reproducibility[
            "total_represented_evaluations"
        ],
        "cell_classifications": {
            code: cell_summary[code]["panel_compatibility_classification"]
            for code in CELL_ORDER
        },
        "compact_evidence": {
            name: sha256_file(evidence_dir / name) for name in EVIDENCE_NAMES
        },
        "runtime_adopted": False,
    }


def construct_registered_precision_audit(
    cells: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Recalculate every registered moment-effect gate at all fixed prefixes."""
    prefixes = (*PRECISION_PREFIXES_R64, PRECISION_FINAL_REPLICATION_COUNT)
    frames = []
    for prefix in prefixes:
        prefix_cells = {
            code: frame.loc[frame["replication"].lt(prefix)].copy()
            for code, frame in cells.items()
        }
        effects = construct_factorial_effects(
            prefix_cells,
            enforce_agreement=False,
        )
        effects.insert(0, "replication_prefix", prefix)
        frames.append(effects)
    result = pd.concat(frames, ignore_index=True)
    for (candidate_index, moment, effect), group in result.groupby(
        ["candidate_index", "moment", "effect"],
        sort=True,
    ):
        ordered = group.sort_values("replication_prefix", kind="mergesort")
        final = ordered.iloc[-1]
        classification = _audit_classification(
            {
                "agreement_pass": bool(final["agreement_pass"]),
                "analytic_mcse": float(final["analytic_mcse"]),
                "replication_index_mcse": float(
                    final["replication_index_mcse"]
                ),
                "zero_variance_event_count": 0,
            },
            ownership_passed=True,
        )
        analytic_slope = _convergence_slope(
            ordered["replication_prefix"],
            ordered["analytic_mcse"],
        )
        index_slope = _convergence_slope(
            ordered["replication_prefix"],
            ordered["replication_index_mcse"],
        )
        mask = (
            result["candidate_index"].eq(candidate_index)
            & result["moment"].eq(moment)
            & result["effect"].eq(effect)
        )
        result.loc[mask, "analytic_convergence_slope"] = analytic_slope
        result.loc[
            mask,
            "replication_index_convergence_slope",
        ] = index_slope
        result.loc[mask, "audit_classification"] = classification
        result.loc[mask, "event_count"] = EVENT_COUNT
        result.loc[mask, "replication_count"] = result.loc[
            mask,
            "replication_prefix",
        ]
    result = result.sort_values(
        ["replication_prefix", "candidate_index", "moment", "effect"],
        kind="mergesort",
    ).reset_index(drop=True)
    final_rows = result.loc[
        result["replication_prefix"].eq(PRECISION_FINAL_REPLICATION_COUNT)
    ]
    counts = (
        final_rows.groupby(["moment", "effect"], sort=True)["agreement_pass"]
        .sum()
        .astype(int)
    )
    failures = {
        f"{moment}|{effect}": int(count)
        for (moment, effect), count in counts.items()
        if count < PRECISION_MINIMUM_PASS_COUNT
    }
    candidate_failures = {
        f"{moment}|{effect}": [
            int(value)
            for value in group.loc[
                ~group["agreement_pass"].astype(bool),
                "candidate_index",
            ]
        ]
        for (moment, effect), group in final_rows.groupby(
            ["moment", "effect"],
            sort=True,
        )
        if not group["agreement_pass"].astype(bool).all()
    }
    return result, {
        "final_pass_counts": {
            f"{moment}|{effect}": int(count)
            for (moment, effect), count in counts.items()
        },
        "final_failing_combinations": failures,
        "final_candidate_failures": candidate_failures,
        "gate_pass": not failures,
    }


def summarise_precision_reconciliation(
    *,
    parent: Path = DEFAULT_PARENT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    register_manifest: bool = True,
) -> dict[str, Any]:
    """Create precision evidence and, only after a pass, factorial evidence."""
    cells = load_r128_cells(parent=parent)
    audit, gate = construct_registered_precision_audit(cells)
    precision_id, design = build_precision_identity()
    root = precision_directory(parent)
    specification = {
        **design,
        "precision_validation_identity": precision_id,
        "estimator_ownership_audit": _estimator_ownership_audit(),
        "original_r64_pass_counts": _json(root / "r64_audit_decision.json")[
            "pass_counts"
        ],
        "audit_classifications": sorted(
            set(audit["audit_classification"].astype(str))
        ),
        "uniform_extension_executed": True,
        "no_threshold_relaxation": True,
    }
    decision = {
        "schema_version": PRECISION_SCHEMA_VERSION,
        "factorial_identity": build_factorial_identity()[0],
        "precision_validation_identity": precision_id,
        "formula_correction": None,
        "formula_error_existed": False,
        "extension_required": True,
        "extension_executed": True,
        "original_replication_count": REPLICATION_COUNT,
        "final_replication_count": PRECISION_FINAL_REPLICATION_COUNT,
        **gate,
        "validity_status": (
            "passed" if gate["gate_pass"] else "factorial_diagnosis_invalid"
        ),
        "authorised_next_boundary": (
            "Continue the original objective-blind factorial analysis."
            if gate["gate_pass"]
            else (
                "Do not produce substantive interaction conclusions; end the "
                "calibration-rescue programme or separately review estimator design."
            )
        ),
        "selected_candidate": None,
        "selected_cell": None,
        "selected_parameter": None,
        "runtime_adopted": False,
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(evidence_dir / PRECISION_EVIDENCE_NAMES[0], specification)
    _atomic_csv(evidence_dir / PRECISION_EVIDENCE_NAMES[1], audit)
    _atomic_json(evidence_dir / PRECISION_EVIDENCE_NAMES[2], decision)
    checkpoint_paths = sorted((root / "checkpoints").glob("*/*.json"))
    original_paths = sorted(
        (factorial_directory(parent) / "cells").glob("*/*.npz")
    )
    deterministic_paths = [
        evidence_dir / name for name in PRECISION_EVIDENCE_NAMES[:3]
    ]
    reproducibility = {
        "schema_version": PRECISION_SCHEMA_VERSION,
        "factorial_identity": build_factorial_identity()[0],
        "precision_validation_identity": precision_id,
        "original_checkpoint_identities": {
            path.relative_to(factorial_directory(parent)).as_posix(): sha256_file(path)
            for path in original_paths
        },
        "extension_checkpoint_identities": {
            path.relative_to(root).as_posix(): sha256_file(path)
            for path in checkpoint_paths
        },
        "prefix_checksums": {
            f"{payload['cell_id']}|{payload['candidate_index']}": {
                "original": payload["original_64_replication_checksum"],
                "prefix": payload["exact_prefix_checksum"],
                "prefix_valid": payload["exact_prefix_valid"],
                "added": payload["added_64_replication_checksum"],
                "combined": payload["combined_128_replication_checksum"],
            }
            for payload in (_json(path) for path in checkpoint_paths)
        },
        "seed_ownership": (
            "registry A; exact event-keyed continuation at zero-based "
            "replication indices 64 through 127"
        ),
        "reused_evaluations": EXPECTED_PRECISION_REUSED_EVALUATIONS,
        "new_evaluations": EXPECTED_PRECISION_NEW_EVALUATIONS,
        "total_represented_evaluations": EXPECTED_PRECISION_TOTAL_EVALUATIONS,
        "deterministic_result_checksums": {
            path.name: sha256_file(path) for path in deterministic_paths
        },
        "objective_ranking_used": False,
        "final_validation_data_used": False,
        "registry_b_used": False,
        "runtime_adopted": False,
    }
    _atomic_json(evidence_dir / PRECISION_EVIDENCE_NAMES[3], reproducibility)
    history = _json(root / "run_history.json")
    runtime = sum(float(item["duration_seconds"]) for item in history["runs"])
    storage = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    benchmark = {
        "schema_version": PRECISION_SCHEMA_VERSION,
        "reused_evaluations": EXPECTED_PRECISION_REUSED_EVALUATIONS,
        "new_evaluations": EXPECTED_PRECISION_NEW_EVALUATIONS,
        "total_represented_evaluations": EXPECTED_PRECISION_TOTAL_EVALUATIONS,
        "runtime_seconds": runtime,
        "throughput_new_evaluations_per_second": (
            EXPECTED_PRECISION_NEW_EVALUATIONS / runtime
        ),
        "storage_bytes": storage,
        "storage_cap_bytes": PRECISION_MAX_NEW_STORAGE_BYTES,
        "host_dependent": True,
        "runtime_adopted": False,
    }
    _atomic_json(evidence_dir / PRECISION_EVIDENCE_NAMES[4], benchmark)
    factorial_result = None
    if gate["gate_pass"]:
        factorial_result = summarise_factorial(
            parent=parent,
            evidence_dir=evidence_dir,
            register_manifest=False,
            cells_override=cells,
            replication_count=PRECISION_FINAL_REPLICATION_COUNT,
            precision_identity=precision_id,
        )
    if register_manifest:
        _register_manifest(evidence_dir, names=PRECISION_EVIDENCE_NAMES)
        if gate["gate_pass"]:
            _register_manifest(evidence_dir, names=EVIDENCE_NAMES)
    return {
        "status": "completed",
        "factorial_identity": build_factorial_identity()[0],
        "precision_identity": precision_id,
        **gate,
        "factorial_result": factorial_result,
        "compact_precision_evidence": {
            name: sha256_file(evidence_dir / name)
            for name in PRECISION_EVIDENCE_NAMES
        },
        "runtime_adopted": False,
    }


def validate_completed_precision_reconciliation(
    *,
    parent: Path = DEFAULT_PARENT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> dict[str, Any]:
    """Validate the precision gate, prefix identities and permitted evidence."""
    manifest = {
        item["path"]: item
        for item in _json(
            REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
        )["artefacts"]
    }
    invalid = []
    for name in PRECISION_EVIDENCE_NAMES:
        path = evidence_dir / name
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        if (
            not path.is_file()
            or relative not in manifest
            or manifest[relative]["sha256"] != sha256_file(path)
        ):
            invalid.append(relative)
    if invalid:
        raise ValueError(f"Precision evidence is invalid: {invalid}.")
    specification = _json(evidence_dir / PRECISION_EVIDENCE_NAMES[0])
    audit = pd.read_csv(evidence_dir / PRECISION_EVIDENCE_NAMES[1])
    decision = _json(evidence_dir / PRECISION_EVIDENCE_NAMES[2])
    reproducibility = _json(evidence_dir / PRECISION_EVIDENCE_NAMES[3])
    expected_rows = (
        5
        * len(PANEL_INDICES)
        * len(STAGE2_ACTIVE_MOMENTS)
        * len(EFFECT_ORDER)
    )
    if (
        specification["precision_validation_identity"]
        != build_precision_identity()[0]
        or len(audit) != expected_rows
        or not decision["gate_pass"]
        or decision["validity_status"] != "passed"
        or len(reproducibility["extension_checkpoint_identities"])
        != EXPECTED_PRECISION_CHECKPOINTS
        or not all(
            item["prefix_valid"]
            for item in reproducibility["prefix_checksums"].values()
        )
    ):
        raise ValueError("Completed precision reconciliation differs.")
    factorial = validate_completed_factorial(
        parent=parent,
        evidence_dir=evidence_dir,
    )
    return {
        "status": "passed",
        "factorial_identity": build_factorial_identity()[0],
        "precision_identity": build_precision_identity()[0],
        "precision_audit_rows": len(audit),
        "final_pass_counts": decision["final_pass_counts"],
        "final_candidate_failures": decision["final_candidate_failures"],
        "checkpoint_count": EXPECTED_PRECISION_CHECKPOINTS,
        "reused_evaluations": EXPECTED_PRECISION_REUSED_EVALUATIONS,
        "new_evaluations": EXPECTED_PRECISION_NEW_EVALUATIONS,
        "total_represented_evaluations": EXPECTED_PRECISION_TOTAL_EVALUATIONS,
        "factorial_final_classification": factorial["final_classification"],
        "runtime_adopted": False,
    }


def validate_completed_factorial(
    *,
    parent: Path = DEFAULT_PARENT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> dict[str, Any]:
    """Validate complete evidence, cell coverage and all non-selection gates."""
    identity, _ = build_factorial_identity(evidence_dir)
    root = factorial_directory(parent)
    manifest = {
        item["path"]: item
        for item in _json(
            REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
        )["artefacts"]
    }
    invalid = []
    for name in EVIDENCE_NAMES:
        path = evidence_dir / name
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        if (
            not path.is_file()
            or relative not in manifest
            or manifest[relative]["sha256"] != sha256_file(path)
        ):
            invalid.append(relative)
    if invalid:
        raise ValueError(f"Factorial evidence is invalid: {invalid}.")
    specification = _json(evidence_dir / EVIDENCE_NAMES[0])
    registry = _json(evidence_dir / EVIDENCE_NAMES[1])
    cells = pd.read_csv(
        evidence_dir / EVIDENCE_NAMES[2],
        dtype={"cell_id": str},
    )
    cells["cell_id"] = cells["cell_id"].str.zfill(3)
    effects = pd.read_csv(evidence_dir / EVIDENCE_NAMES[3])
    interactions = pd.read_csv(evidence_dir / EVIDENCE_NAMES[4])
    decision = _json(evidence_dir / EVIDENCE_NAMES[7])
    reproducibility = _json(evidence_dir / EVIDENCE_NAMES[8])
    if specification["factorial_identity"] != identity:
        raise ValueError("Factorial evidence identity differs.")
    if (
        len(cells) != 8 * 16 * len(STAGE2_ACTIVE_MOMENTS)
        or set(cells["cell_id"]) != set(CELL_ORDER)
        or len(effects) != 16 * len(STAGE2_ACTIVE_MOMENTS) * 7
        or len(interactions) != 4 * 16 * len(STAGE2_ACTIVE_MOMENTS)
        or len(list((root / "cells").glob("*/*.npz"))) != 64
    ):
        raise ValueError("Factorial evidence dimensions differ.")
    forbidden = (
        specification["scalar_objective"] is not None
        or specification["candidate_ranked"]
        or specification["cell_ranked"]
        or specification["cell_selected"]
        or specification["parameter_selected"]
        or decision["selected_cell"] is not None
        or decision["selected_parameter"] is not None
        or reproducibility["objective_ranking_used"]
        or reproducibility["candidate_ranking_used"]
        or reproducibility["cell_ranking_used"]
        or reproducibility["final_validation_data_used"]
        or reproducibility["registry_b_used"]
        or reproducibility["usdc_svb_simulations"] != 0
    )
    if forbidden:
        raise ValueError("Selection, ranking, objective or validation data entered.")
    if any(
        payload.get("runtime_adopted")
        for payload in (specification, registry, decision, reproducibility)
    ):
        raise ValueError("Factorial diagnostics cannot be runtime adopted.")
    size = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    if size > MAX_NEW_STORAGE_BYTES:
        raise ValueError("Factorial diagnostics exceed the 500 MB cap.")
    extended = (
        specification["replications"] == PRECISION_FINAL_REPLICATION_COUNT
    )
    return {
        "status": "passed",
        "factorial_identity": identity,
        "final_classification": decision["final_classification"],
        "cell_rows": len(cells),
        "effect_rows": len(effects),
        "interaction_rows": len(interactions),
        "checkpoint_count": 64,
        "reused_evaluations": (
            EXPECTED_PRECISION_REUSED_EVALUATIONS
            if extended
            else EXPECTED_REUSED_EVALUATIONS
        ),
        "new_evaluations": (
            EXPECTED_PRECISION_NEW_EVALUATIONS
            if extended
            else EXPECTED_NEW_EVALUATIONS
        ),
        "total_represented_evaluations": (
            EXPECTED_PRECISION_TOTAL_EVALUATIONS
            if extended
            else EXPECTED_TOTAL_EVALUATIONS
        ),
        "ignored_output_size_bytes": size,
        "cell_selected": False,
        "parameter_selected": False,
        "runtime_adopted": False,
    }


def run_factorial_review(
    *,
    action: str,
    parent: Path = DEFAULT_PARENT,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    workers: int = 4,
) -> dict[str, Any]:
    """Dispatch explicit local-only structural-factorial operations."""
    if action == "validate-inputs":
        return validate_factorial_inputs(parent=parent, evidence_dir=evidence_dir)
    if action == "validate-reused-cells":
        frames = _reused_cell_frames()
        return {
            "status": "passed",
            "cells": list(frames),
            "rows": {code: len(frame) for code, frame in frames.items()},
            "reused_evaluations": EXPECTED_REUSED_EVALUATIONS,
        }
    if action == "build-registry":
        return _cell_registry()
    if action == "run-missing-cells":
        return run_missing_cells(parent=parent, workers=workers, resume=False)
    if action == "resume":
        return run_missing_cells(parent=parent, workers=workers, resume=True)
    if action in {
        "calculate-effects",
        "calculate-additive-predictions",
        "classify-interactions",
        "classify-cells",
        "summarise-mechanisms",
        "reconstruct-evidence",
        "summarise",
    }:
        return summarise_factorial(
            parent=parent,
            evidence_dir=evidence_dir,
        )
    if action == "validate":
        return validate_completed_factorial(
            parent=parent,
            evidence_dir=evidence_dir,
        )
    if action == "precision-validate-inputs":
        return validate_r64_precision_inputs(parent=parent)
    if action == "precision-audit-r64":
        return audit_r64_precision(parent=parent)
    if action == "precision-extend":
        return run_precision_extension(
            parent=parent,
            workers=workers,
            resume=False,
        )
    if action == "precision-resume":
        return run_precision_extension(
            parent=parent,
            workers=workers,
            resume=True,
        )
    if action == "precision-summarise":
        return summarise_precision_reconciliation(
            parent=parent,
            evidence_dir=evidence_dir,
        )
    if action == "precision-validate":
        return validate_completed_precision_reconciliation(
            parent=parent,
            evidence_dir=evidence_dir,
        )
    raise ValueError(f"Unsupported structural-factorial action: {action}.")
