"""Pre-registered ETH-only peg-recovery experiment.

This module composes existing vault, liquidation, persistent-confidence and
coefficient-normalised DAI-market owners.  It is an opt-in experiment harness:
no production profile or established experiment imports it.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
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
from typing import Any

import numpy as np
import pandas as pd
import yaml

from dai_sim.calibration.event_simulation import (
    ConditionalEventInput,
    ConditionalEventPath,
    ConditionalEventSimulationConfig,
    SPARSE_SCALING_EVIDENCE,
    build_conditional_initial_state,
    load_stage1_owners,
    material_bad_debt_tolerance,
    simulate_candidate_invariant_liquidation_path,
)
from dai_sim.calibration.market import sample_residual_blocks
from dai_sim.experiments.confidence_scenarios import (
    EXPECTED_SCENARIO_ORDER,
    load_confidence_scenario_registry,
    resolve_confidence_scenario,
)
from dai_sim.inputs.configuration import (
    DEFAULT_LEGACY_CONFIG_PATH,
    REPOSITORY_ROOT,
    load_empirical_configuration_bundle,
    sha256_file,
)
from dai_sim.model.confidence import (
    PersistentConfidenceState,
    RecoveryGateInputs,
    update_persistent_confidence,
)
from dai_sim.model.market import coefficient_normalised_market_response


DEFAULT_CONFIG_PATH = (
    REPOSITORY_ROOT / "config/sensitivities/eth_recovery_matrix.yaml"
)
DEFAULT_EVIDENCE_DIR = (
    REPOSITORY_ROOT / "data/provenance/experiments/recovery"
)
DEFAULT_MANIFEST_PATH = (
    REPOSITORY_ROOT / "data/provenance/experiments/manifest.json"
)
EXPECTED_BASELINE_SHA256 = (
    "6de53071749fc504865ef760488003ab4733b58e8a6ce692144ca8e74ab9284a"
)
EXPECTED_CONFIDENCE_CONFIG_SHA256 = (
    "86c33147f167d708e4a18191e50c39bec5056a680b13e682551317ba9b916e85"
)
EXPECTED_CONFIDENCE_REGISTRY_SHA256 = (
    "d455306fd7b7553f113099b6d51f962939d8b4793439a02c4638c646a63b25da"
)
# Frozen by the result-blind v1 pre-registration before the 2,048-run matrix.
# Post-execution serializers and evidence validators may be repaired without
# silently relabelling the scientific treatment implementation.
PRE_REGISTERED_CODE_IDENTITY = (
    "bcae5ed6a4ea0ee1a8990f468fdec96e49dc14757aef1329365a52d4716cbbbe"
)
PATH_ORDER = (
    "persistent_trough",
    "partial_week",
    "full_week",
    "rapid_full",
)
PRIMARY_METRICS = (
    "below_peg_burden",
    "restricted_mean_recovery_time",
    "recovery_probability_168h",
    "recovery_probability_720h",
    "maximum_unresolved_tab_dai",
    "cumulative_realised_bad_debt_dai",
)
SUMMARY_METRICS = (
    *PRIMARY_METRICS,
    "recovery_probability_48h",
    "recovery_probability_336h",
    "minimum_dai_price",
    "maximum_negative_peg_deviation",
    "mean_absolute_peg_deviation",
    "hours_below_0995",
    "hours_above_1005",
    "first_return_time",
    "failed_recovery_attempts",
    "final_dai_price",
    "final_peg_band_status",
    "peak_liquidatable_vaults",
    "peak_share_liquidatable",
    "cumulative_debt_repaid_dai",
    "completed_liquidation_count",
    "unprofitable_attempt_count",
    "capacity_rejected_opportunities",
    "unresolved_tab_at_horizon_dai",
    "active_bad_debt_at_horizon_dai",
    "maximum_active_bad_debt_dai",
    "keeper_profit_dai",
    "minimum_confidence",
    "mean_confidence_loss",
    "hours_at_confidence_floor",
    "hours_recovery_gate_closed",
    "first_recovery_gate_open",
    "recovery_gate_reopenings",
    "cumulative_panic_contribution",
    "maximum_panic_contribution",
    "confidence_at_horizon",
)
RECOVERY_CONTRASTS = (
    ("partial_week", "persistent_trough"),
    ("full_week", "persistent_trough"),
    ("rapid_full", "persistent_trough"),
    ("full_week", "partial_week"),
    ("rapid_full", "full_week"),
)
CONFIDENCE_CONTRASTS = tuple(
    (scenario, "stage1_only") for scenario in EXPECTED_SCENARIO_ORDER[1:]
)
BINARY_METRICS = {
    "recovery_probability_48h",
    "recovery_probability_168h",
    "recovery_probability_336h",
    "recovery_probability_720h",
    "final_peg_band_status",
}
LOWER_IS_BETTER = {
    "below_peg_burden",
    "restricted_mean_recovery_time",
    "maximum_unresolved_tab_dai",
    "cumulative_realised_bad_debt_dai",
}
EVIDENCE_FILENAMES = (
    "eth_recovery_specification.json",
    "eth_recovery_paths.csv",
    "eth_recovery_registry.csv",
    "eth_recovery_cell_summary.csv",
    "eth_recovery_contrasts.csv",
    "eth_recovery_interactions.csv",
    "eth_recovery_decision.json",
    "eth_recovery_reproducibility.json",
    "eth_recovery_benchmark.json",
)


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=lambda value: (
            value.item() if isinstance(value, np.generic) else value
        ),
    ).encode("utf-8")


def _sha256_payload(payload: Any) -> str:
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
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
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
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8"),
    )


def _csv_bytes(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column) for column in columns})
    return output.getvalue().encode("utf-8")


@dataclass(frozen=True)
class RecoveryPathDefinition:
    """One deterministic post-trough ETH treatment."""

    order: int
    identifier: str
    recovery_fraction: float
    recovery_duration_hours: int

    def validate(self) -> None:
        if self.identifier not in PATH_ORDER:
            raise ValueError(f"Unknown recovery path: {self.identifier}.")
        if not 0.0 <= self.recovery_fraction <= 1.0:
            raise ValueError("Recovery fraction must lie in [0, 1].")
        if self.identifier == "persistent_trough":
            if self.recovery_fraction != 0.0 or self.recovery_duration_hours != 0:
                raise ValueError("persistent_trough must have f=0 and T=0.")
        elif self.recovery_duration_hours <= 0:
            raise ValueError("Recovering paths require a positive duration.")


@dataclass(frozen=True)
class RecoveryCell:
    """One path-by-confidence treatment cell."""

    order: int
    identifier: str
    recovery_path: str
    confidence_scenario: str
    path_checksum: str
    scenario_checksum: str
    replication_count: int
    cell_checksum: str


@dataclass(frozen=True)
class RecoveryDesign:
    """Validated owner of the full pre-registered experiment design."""

    config_path: Path
    config_sha256: str
    registry_id: str
    baseline_path: Path
    baseline_sha256: str
    pre_shock_price: float
    trough_price: float
    shock_hour: int
    pre_shock_hours: int
    post_shock_hours: int
    total_hours: int
    replications: int
    path_definitions: tuple[RecoveryPathDefinition, ...]
    confidence_scenarios: tuple[str, ...]
    lower_band: float
    upper_band: float
    stability_hours: int
    recovery_cap_hours: int
    output_root: Path
    evidence_dir: Path
    minimum_free_bytes: int
    maximum_new_bytes: int


def load_recovery_design(
    path: Path | str = DEFAULT_CONFIG_PATH,
) -> RecoveryDesign:
    """Load the sole YAML owner and verify all frozen dependencies."""
    config_path = Path(path).resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        raise ValueError("Unsupported ETH recovery design schema.")
    if payload.get("experiment_id") != "eth_recovery_matrix_v1":
        raise ValueError("Unexpected ETH recovery registry identity.")
    baseline = payload["baseline"]
    shock = payload["shock"]
    horizon = payload["horizon"]
    randomness = payload["randomness"]
    recovery = payload["recovery_definition"]
    output = payload["output"]
    confidence = payload["confidence"]
    baseline_path = REPOSITORY_ROOT / str(baseline["profile"])
    baseline_hash = sha256_file(baseline_path)
    if (
        baseline_hash != EXPECTED_BASELINE_SHA256
        or baseline["expected_sha256"] != EXPECTED_BASELINE_SHA256
    ):
        raise ValueError("Canonical legacy ETH-only baseline checksum changed.")
    registry = load_confidence_scenario_registry(
        REPOSITORY_ROOT / str(confidence["registry"])
    )
    if registry.configuration_sha256 != EXPECTED_CONFIDENCE_CONFIG_SHA256:
        raise ValueError("Confidence configuration checksum changed.")
    registry_evidence = (
        REPOSITORY_ROOT
        / "data/provenance/experiments/confidence/confidence_scenario_registry.csv"
    )
    if sha256_file(registry_evidence) != EXPECTED_CONFIDENCE_REGISTRY_SHA256:
        raise ValueError("Confidence scenario registry evidence changed.")
    if tuple(confidence["order"]) != EXPECTED_SCENARIO_ORDER:
        raise ValueError("Confidence scenario order changed.")
    paths = tuple(
        RecoveryPathDefinition(
            order=int(row["order"]),
            identifier=str(row["identifier"]),
            recovery_fraction=float(row["recovery_fraction"]),
            recovery_duration_hours=int(row["recovery_duration_hours"]),
        )
        for row in payload["recovery_paths"]
    )
    for path_definition in paths:
        path_definition.validate()
    if tuple(item.identifier for item in paths) != PATH_ORDER:
        raise ValueError("Recovery path order changed.")
    design = RecoveryDesign(
        config_path=config_path,
        config_sha256=sha256_file(config_path),
        registry_id=str(payload["experiment_id"]),
        baseline_path=baseline_path,
        baseline_sha256=baseline_hash,
        pre_shock_price=float(shock["pre_shock_price_usd"]),
        trough_price=float(shock["trough_price_usd"]),
        shock_hour=int(shock["onset_hour"]),
        pre_shock_hours=int(horizon["pre_shock_hours"]),
        post_shock_hours=int(horizon["post_shock_hours"]),
        total_hours=int(horizon["total_hours"]),
        replications=int(randomness["replications_per_cell"]),
        path_definitions=paths,
        confidence_scenarios=tuple(confidence["order"]),
        lower_band=float(recovery["lower_bound"]),
        upper_band=float(recovery["upper_bound"]),
        stability_hours=int(recovery["consecutive_hours"]),
        recovery_cap_hours=int(recovery["restricted_mean_cap_hours"]),
        output_root=REPOSITORY_ROOT / str(output["root"]),
        evidence_dir=REPOSITORY_ROOT / str(output["compact_evidence"]),
        minimum_free_bytes=int(output["minimum_free_bytes"]),
        maximum_new_bytes=int(output["maximum_new_bytes"]),
    )
    if (
        design.shock_hour != 48
        or design.pre_shock_hours != 48
        or design.post_shock_hours != 720
        or design.total_hours != 768
        or design.replications != 128
    ):
        raise ValueError("The pre-registered horizon or replication design changed.")
    if not math.isclose(
        design.trough_price / design.pre_shock_price - 1.0,
        -0.43,
        abs_tol=1e-12,
    ):
        raise ValueError("Canonical shock is not the frozen 43% decline.")
    if (
        design.lower_band != 0.995
        or design.upper_band != 1.005
        or design.stability_hours != 24
        or design.recovery_cap_hours != 720
    ):
        raise ValueError("Registered sustained-recovery semantics changed.")
    return design


def smoothstep(value: float) -> float:
    """Return the cubic smoothstep on the closed unit interval."""
    if not 0.0 <= value <= 1.0:
        raise ValueError("smoothstep input must lie in [0, 1].")
    return 3.0 * value**2 - 2.0 * value**3


def build_eth_path(
    design: RecoveryDesign,
    definition: RecoveryPathDefinition,
) -> np.ndarray:
    """Build one exact deterministic log-price recovery path."""
    definition.validate()
    values = np.full(design.total_hours, design.pre_shock_price, dtype="<f8")
    log_trough = math.log(design.trough_price)
    log_loss = math.log(design.pre_shock_price) - log_trough
    for position in range(design.shock_hour, design.total_hours):
        tau = position - design.shock_hour
        if definition.recovery_fraction == 0.0:
            fraction = 0.0
        else:
            x_value = min(tau / definition.recovery_duration_hours, 1.0)
            fraction = definition.recovery_fraction * smoothstep(x_value)
        values[position] = math.exp(log_trough + fraction * log_loss)
    values[design.shock_hour] = design.trough_price
    if definition.recovery_fraction == 0.0:
        values[design.shock_hour :] = design.trough_price
    if definition.recovery_duration_hours:
        values[
            design.shock_hour + definition.recovery_duration_hours :
        ] = math.exp(
            log_trough + definition.recovery_fraction * log_loss
        )
    validate_eth_path(design, definition, values)
    return values


def path_checksum(values: np.ndarray) -> str:
    """Hash canonical little-endian path bytes."""
    return hashlib.sha256(np.asarray(values, dtype="<f8").tobytes()).hexdigest()


def validate_eth_path(
    design: RecoveryDesign,
    definition: RecoveryPathDefinition,
    values: np.ndarray,
) -> None:
    """Validate the common shock and the declared recovery treatment."""
    if values.shape != (design.total_hours,):
        raise ValueError("ETH path has the wrong horizon.")
    if not np.isfinite(values).all() or np.any(values <= 0.0):
        raise ValueError("ETH path contains invalid prices.")
    if not np.all(values[: design.shock_hour] == design.pre_shock_price):
        raise ValueError("ETH paths must have identical pre-shock values.")
    if not math.isclose(
        values[design.shock_hour],
        design.trough_price,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("ETH path does not share the canonical trough.")
    post = values[design.shock_hour :]
    if np.any(np.diff(post) < -1e-12):
        raise ValueError("Post-trough ETH recovery must be monotone.")
    if post.max() > design.pre_shock_price + 1e-10:
        raise ValueError("ETH recovery path overshoots its pre-shock price.")
    expected_terminal = math.exp(
        math.log(design.trough_price)
        + definition.recovery_fraction
        * (math.log(design.pre_shock_price) - math.log(design.trough_price))
    )
    if not math.isclose(post[-1], expected_terminal, abs_tol=1e-10):
        raise ValueError("ETH path terminal recovery fraction changed.")
    if definition.recovery_duration_hours:
        endpoint = values[design.shock_hour + definition.recovery_duration_hours]
        if not math.isclose(endpoint, expected_terminal, abs_tol=1e-10):
            raise ValueError("ETH path did not reach its terminal price on time.")
        if not np.allclose(
            values[design.shock_hour + definition.recovery_duration_hours :],
            expected_terminal,
            atol=1e-10,
            rtol=0.0,
        ):
            raise ValueError("ETH path does not remain at its terminal value.")


def derive_recovery_seed(replication: int, stream_name: str) -> int:
    """Derive one treatment-invariant 64-bit seed for a replication."""
    if stream_name not in {
        "vault_sampling",
        "market_innovations",
        "liquidation_randomness",
    }:
        raise ValueError(f"Unknown ETH recovery random stream: {stream_name}.")
    if isinstance(replication, bool) or replication < 0:
        raise ValueError("replication must be a non-negative integer.")
    return int.from_bytes(
        hashlib.sha256(
            _canonical_json(
                {
                    "registry_id": "eth_recovery_matrix_v1",
                    "replication": int(replication),
                    "stream_name": stream_name,
                    "version": 1,
                }
            )
        ).digest()[:8],
        "big",
    )


def replication_seed_record(replication: int) -> dict[str, Any]:
    """Return treatment-invariant seed ownership and its checksum."""
    record = {
        "replication": replication,
        "vault_sampling_seed": derive_recovery_seed(replication, "vault_sampling"),
        "market_innovations_seed": derive_recovery_seed(
            replication, "market_innovations"
        ),
        "liquidation_randomness_seed": derive_recovery_seed(
            replication, "liquidation_randomness"
        ),
    }
    return {**record, "paired_stream_checksum": _sha256_payload(record)}


def seed_registry_checksum(replications: int) -> str:
    return _sha256_payload(
        [replication_seed_record(index) for index in range(replications)]
    )


def build_cell_registry(
    design: RecoveryDesign,
    paths: Mapping[str, np.ndarray],
) -> tuple[RecoveryCell, ...]:
    """Construct the exact recovery-path-first 16-cell registry."""
    registry = load_confidence_scenario_registry()
    scenario_rows = {
        scenario.identifier: scenario.record() for scenario in registry.scenarios
    }
    cells: list[RecoveryCell] = []
    for path_identifier in PATH_ORDER:
        path_hash = path_checksum(paths[path_identifier])
        for scenario_identifier in EXPECTED_SCENARIO_ORDER:
            base = {
                "order": len(cells) + 1,
                "recovery_path": path_identifier,
                "confidence_scenario": scenario_identifier,
                "baseline_sha256": design.baseline_sha256,
                "path_sha256": path_hash,
                "scenario_sha256": _sha256_payload(
                    scenario_rows[scenario_identifier]
                ),
                "replication_count": design.replications,
            }
            identifier = f"{path_identifier}__{scenario_identifier}"
            cells.append(
                RecoveryCell(
                    order=base["order"],
                    identifier=identifier,
                    recovery_path=path_identifier,
                    confidence_scenario=scenario_identifier,
                    path_checksum=path_hash,
                    scenario_checksum=base["scenario_sha256"],
                    replication_count=design.replications,
                    cell_checksum=_sha256_payload(
                        {**base, "identifier": identifier}
                    ),
                )
            )
    if len(cells) != 16 or len({cell.identifier for cell in cells}) != 16:
        raise ValueError("ETH recovery matrix must contain exactly 16 unique cells.")
    return tuple(cells)


def shock_checksum(design: RecoveryDesign) -> str:
    return _sha256_payload(
        {
            "source": "frozen_eth_only_shock",
            "pre_shock_price_usd": design.pre_shock_price,
            "onset_hour": design.shock_hour,
            "trough_hour": design.shock_hour,
            "trough_price_usd": design.trough_price,
            "arithmetic_loss_fraction": -0.43,
            "log_loss": math.log(design.trough_price)
            - math.log(design.pre_shock_price),
            "construction": "instantaneous",
        }
    )


def experiment_identity(
    design: RecoveryDesign,
    cells: Sequence[RecoveryCell],
) -> str:
    """Return the content-addressed scientific identity, excluding results."""
    return _sha256_payload(
        {
            "implementation_schema": 1,
            "code_identity": _code_identity(),
            "baseline_sha256": design.baseline_sha256,
            "shock_sha256": shock_checksum(design),
            "path_definitions": [asdict(item) for item in design.path_definitions],
            "confidence_registry_sha256": EXPECTED_CONFIDENCE_REGISTRY_SHA256,
            "confidence_configuration_sha256": EXPECTED_CONFIDENCE_CONFIG_SHA256,
            "cell_order": [cell.identifier for cell in cells],
            "replications": design.replications,
            "seed_registry_sha256": seed_registry_checksum(design.replications),
            "horizon": {
                "pre_shock_hours": design.pre_shock_hours,
                "post_shock_hours": design.post_shock_hours,
                "total_hours": design.total_hours,
            },
            "sustained_recovery": {
                "band": [design.lower_band, design.upper_band],
                "consecutive_hours": design.stability_hours,
                "rmst_cap_hours": design.recovery_cap_hours,
            },
            "metrics": list(SUMMARY_METRICS),
            "recovery_contrasts": list(RECOVERY_CONTRASTS),
            "confidence_contrasts": list(CONFIDENCE_CONTRASTS),
            "interaction_definition": "difference_in_differences",
            "classification_rules": ["H4a", "H4b", "H4c", "overall"],
        }
    )


def _code_identity() -> str:
    """Return the v1 scientific implementation identity frozen pre-execution."""
    return PRE_REGISTERED_CODE_IDENTITY


def _experiment_event_config(design: RecoveryDesign) -> ConditionalEventSimulationConfig:
    config = ConditionalEventSimulationConfig(
        pre_roll_hours=design.pre_shock_hours,
        post_recovery_hours=24,
        maximum_event_horizon_hours=design.total_hours,
        stability_hours=design.stability_hours,
        recovery_band_lower=design.lower_band,
        recovery_band_upper=design.upper_band,
        material_downside_threshold=0.995,
        peg_stress_weight=0.5,
        collateral_stress_weight=0.5,
        stage1_evidence_reference=(
            "data/provenance/calibration/confidence/stage1_market_estimates.json"
        ),
        residual_evidence_reference=(
            "data/provenance/calibration/confidence/stage1_residual_summary.json"
        ),
        initial_state_reference="config/profiles/legacy.yaml",
        liquidation_pressure_tolerance=1e-9,
        bad_debt_absolute_tolerance=1e-9,
        bad_debt_relative_tolerance=1e-12,
        dai_min_price=0.50,
        dai_max_price=1.50,
        step_hours=1,
        primary_collateral_mode="ETH-only mechanism core",
        calibration_only=True,
        runtime_adopted=False,
    )
    config.validate()
    return config


def _conditional_path(
    design: RecoveryDesign,
    definition: RecoveryPathDefinition,
    values: np.ndarray,
) -> ConditionalEventPath:
    timestamps = pd.date_range(
        "2000-01-01T00:00:00Z",
        periods=design.total_hours,
        freq="h",
    )
    event = ConditionalEventInput(
        event_id=design.registry_id,
        partition="calibration",
        onset_timestamp_utc=timestamps[design.shock_hour],
        observed_event_duration_hours=design.post_shock_hours,
        initial_peg_gap=0.0,
        eth_recovery_24h=float(
            values[min(design.shock_hour + 24, len(values) - 1)]
            / values[design.shock_hour]
            - 1.0
        ),
    )
    return ConditionalEventPath(
        event=event,
        timestamps=tuple(timestamps),
        observed_eth_prices=tuple(float(value) for value in values),
        starting_dai_price=1.0,
        onset_position=design.shock_hour,
        minimum_evaluation_end_position=design.total_hours - 1,
        maximum_end_position=design.total_hours - 1,
        observed_dai_values_after_start_used=False,
    )


def _recovery_metrics(
    prices: np.ndarray,
    *,
    design: RecoveryDesign,
) -> dict[str, float | int]:
    """Compute registered peg recovery with censoring retained."""
    if prices.shape != (design.post_shock_hours,):
        raise ValueError("Post-shock DAI path has the wrong length.")
    inside = (prices >= design.lower_band) & (prices <= design.upper_band)
    outside_positions = np.flatnonzero(~inside)
    first_return: int | None = None
    failed_attempts = 0
    sustained: int | None = None
    if len(outside_positions):
        first_exit = int(outside_positions[0])
        counter = 0
        for position in range(first_exit + 1, len(prices)):
            if inside[position]:
                if first_return is None:
                    first_return = position
                counter += 1
                if counter == design.stability_hours:
                    sustained = position + 1
                    break
            else:
                if 0 < counter < design.stability_hours:
                    failed_attempts += 1
                counter = 0
    else:
        sustained = 0
        first_return = 0
    restricted = (
        design.recovery_cap_hours
        if sustained is None
        else min(sustained, design.recovery_cap_hours)
    )
    return {
        "first_return_time": (
            design.recovery_cap_hours if first_return is None else first_return
        ),
        "sustained_recovery_time": (
            design.recovery_cap_hours if sustained is None else sustained
        ),
        "restricted_mean_recovery_time": restricted,
        "failed_recovery_attempts": failed_attempts,
        "right_censored": int(sustained is None),
        **{
            f"recovery_probability_{horizon}h": int(
                sustained is not None and sustained <= horizon
            )
            for horizon in (48, 168, 336, 720)
        },
    }


def _simulate_market_scenario(
    *,
    design: RecoveryDesign,
    definition: RecoveryPathDefinition,
    eth_prices: np.ndarray,
    liquidation: Mapping[str, np.ndarray],
    innovations: np.ndarray,
    scenario_identifier: str,
    stage1_owners: Mapping[str, Any],
    peg_scale: float,
    eth_scale: float,
    initial_vault_count: int,
) -> dict[str, Any]:
    activation = resolve_confidence_scenario(scenario_identifier)
    confidence_state = PersistentConfidenceState.initial()
    confidence_values = np.ones(design.total_hours, dtype="<f8")
    dai_values = np.ones(design.total_hours, dtype="<f8")
    panic_values = np.zeros(design.total_hours, dtype="<f8")
    gate_values = np.zeros(design.total_hours, dtype="?")
    floor_values = np.zeros(design.total_hours, dtype="?")
    dai_price = 1.0
    eth_returns: deque[float] = deque(maxlen=24)
    previous_eth = float(eth_prices[0])
    gate_inputs = RecoveryGateInputs(True, True, False)
    for position, (eth_price, innovation) in enumerate(
        zip(eth_prices, innovations, strict=True)
    ):
        if position:
            eth_returns.append(math.log(eth_price) - math.log(previous_eth))
        previous_eth = float(eth_price)
        lagged_downside = (
            max(0.0, -sum(eth_returns)) if len(eth_returns) == 24 else 0.0
        )
        scaled_peg = min(1.0, max(1.0 - dai_price, 0.0) / peg_scale)
        scaled_eth = min(1.0, lagged_downside / eth_scale)
        if activation.persistent_config is not None:
            update = update_persistent_confidence(
                confidence_state,
                activation.persistent_config,
                scaled_peg_gap=scaled_peg,
                scaled_collateral_stress=scaled_eth,
                recovery_inputs=gate_inputs,
                peg_weight=0.5,
                collateral_weight=0.5,
            )
            confidence_state = update.state
            confidence = confidence_state.confidence
            gate_values[position] = confidence_state.recovery_gate_open
            floor_values[position] = math.isclose(
                confidence,
                activation.persistent_config.confidence_floor,
                abs_tol=1e-12,
            )
        else:
            confidence = 1.0
        market = coefficient_normalised_market_response(
            dai_price=dai_price,
            confidence=confidence,
            below_peg_response=float(stage1_owners["below_peg_response"]),
            above_peg_response=float(stage1_owners["above_peg_response"]),
            panic_response=activation.panic_response,
            residual_innovation=float(innovation),
            min_price=0.50,
            max_price=1.50,
        )
        dai_price = market.clipped_next_price
        dai_values[position] = dai_price
        confidence_values[position] = confidence
        panic_values[position] = market.panic_component
        gate_inputs = RecoveryGateInputs(
            price_inside_recovery_band=(
                design.lower_band <= dai_price <= design.upper_band
            ),
            liquidation_pressure_acceptable=bool(
                liquidation["liquidation_gate_open"][position]
            ),
            severe_bad_debt_present=bool(
                liquidation["material_active_bad_debt"][position]
            ),
        )
    post = dai_values[design.shock_hour :]
    post_confidence = confidence_values[design.shock_hour :]
    post_gate = gate_values[design.shock_hour :]
    post_floor = floor_values[design.shock_hour :]
    post_panic = panic_values[design.shock_hour :]
    recovery = _recovery_metrics(post, design=design)
    gate_open_positions = np.flatnonzero(post_gate)
    reopenings = int(
        np.count_nonzero((~post_gate[:-1]) & post_gate[1:])
    )
    summary: dict[str, Any] = {
        "recovery_path": definition.identifier,
        "confidence_scenario": scenario_identifier,
        "confidence_active": activation.persistent_config is not None,
        "below_peg_burden": float(np.maximum(1.0 - post, 0.0).sum()),
        "minimum_dai_price": float(post.min()),
        "maximum_negative_peg_deviation": float(
            np.maximum(1.0 - post, 0.0).max()
        ),
        "mean_absolute_peg_deviation": float(np.abs(post - 1.0).mean()),
        "hours_below_0995": int(np.count_nonzero(post < 0.995)),
        "hours_above_1005": int(np.count_nonzero(post > 1.005)),
        "final_dai_price": float(post[-1]),
        "final_peg_band_status": int(
            design.lower_band <= post[-1] <= design.upper_band
        ),
        "maximum_unresolved_tab_dai": float(
            liquidation["unresolved_tab_dai"][design.shock_hour :].max()
        ),
        "cumulative_realised_bad_debt_dai": float(
            liquidation["realised_bad_debt_dai"].sum()
        ),
        "peak_liquidatable_vaults": int(
            liquidation["liquidatable_before"][design.shock_hour :].max()
        ),
        "peak_share_liquidatable": float(
            liquidation["liquidatable_before"][design.shock_hour :].max()
            / initial_vault_count
        ),
        "cumulative_debt_repaid_dai": float(
            liquidation["cleared_tab_dai"].sum()
        ),
        "completed_liquidation_count": int(
            liquidation["successful_liquidations"].sum()
        ),
        "unprofitable_attempt_count": int(
            liquidation["failed_liquidation_attempts"].sum()
        ),
        "capacity_rejected_opportunities": int(
            liquidation["capacity_rejected_opportunities"].sum()
        ),
        "unresolved_tab_at_horizon_dai": float(
            liquidation["unresolved_tab_dai"][-1]
        ),
        "active_bad_debt_at_horizon_dai": float(
            liquidation["active_bad_debt_dai"][-1]
        ),
        "maximum_active_bad_debt_dai": float(
            liquidation["active_bad_debt_dai"].max()
        ),
        "keeper_profit_dai": float(liquidation["keeper_profit_dai"].sum()),
        "minimum_confidence": float(post_confidence.min()),
        "mean_confidence_loss": float(np.mean(1.0 - post_confidence)),
        "hours_at_confidence_floor": int(np.count_nonzero(post_floor)),
        "hours_recovery_gate_closed": (
            int(np.count_nonzero(~post_gate))
            if activation.persistent_config is not None
            else 0
        ),
        "first_recovery_gate_open": (
            int(gate_open_positions[0])
            if len(gate_open_positions)
            else design.recovery_cap_hours
        ),
        "recovery_gate_reopenings": (
            reopenings if activation.persistent_config is not None else 0
        ),
        "cumulative_panic_contribution": float(np.abs(post_panic).sum()),
        "maximum_panic_contribution": float(np.abs(post_panic).max()),
        "confidence_at_horizon": float(post_confidence[-1]),
        "numerical_valid": True,
    }
    summary.update(recovery)
    numeric_values = [
        value
        for value in summary.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    if (
        not all(math.isfinite(float(value)) for value in numeric_values)
        or np.any(post <= 0.0)
        or np.any(liquidation["unresolved_tab_dai"] < 0.0)
        or np.any(liquidation["active_bad_debt_dai"] < 0.0)
    ):
        summary["numerical_valid"] = False
    return {
        "summary": summary,
        "dai_price_path": [float(value) for value in post],
        "confidence_path": [float(value) for value in post_confidence],
    }


def simulate_path_replication(
    *,
    path_identifier: str,
    replication: int,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    """Run four confidence cells sharing one path, state and random streams."""
    design = load_recovery_design(config_path)
    definition = next(
        item for item in design.path_definitions if item.identifier == path_identifier
    )
    eth_prices = build_eth_path(design, definition)
    config = _experiment_event_config(design)
    expected_vault_seed = derive_recovery_seed(replication, "vault_sampling")
    from dataclasses import replace
    from dai_sim.model.simulation import create_initial_vaults

    bundle = load_empirical_configuration_bundle(
        design.baseline_path,
        verify_registry_checksums=False,
    )
    simulation = replace(
        bundle.simulation_config,
        n_steps=design.total_hours,
        initial_eth_price=design.pre_shock_price,
        random_seed=expected_vault_seed,
    )
    generated_vaults = create_initial_vaults(simulation)
    debts = tuple(float(vault.debt_dai) for vault in generated_vaults)
    ratios = tuple(
        float(vault.collateral_ratio(design.pre_shock_price))
        for vault in generated_vaults
    )
    liquidation_ratios = tuple(
        float(vault.liquidation_ratio) for vault in generated_vaults
    )
    from dai_sim.calibration.event_simulation import ConditionalInitialState

    state_payload = {
        "collateral_mode": "ETH-only mechanism core",
        "debt_dai": debts,
        "collateral_ratios": ratios,
        "liquidation_ratios": liquidation_ratios,
        "vault_count": len(debts),
    }
    state = ConditionalInitialState(
        event_id=design.registry_id,
        replication=replication,
        registry_id=design.registry_id,
        vault_seed=expected_vault_seed,
        starting_eth_price=design.pre_shock_price,
        vault_count=len(debts),
        total_debt_dai=float(sum(debts)),
        debt_dai=debts,
        collateral_ratios=ratios,
        liquidation_ratios=liquidation_ratios,
        initial_active_bad_debt_dai=0.0,
        initial_realised_bad_debt_dai=0.0,
        initial_unresolved_tab_dai=0.0,
        initial_trailing_cleared_tab_dai=0.0,
        initial_confidence=1.0,
        initial_stability_counter=0,
        collateral_mode="ETH-only mechanism core",
        state_checksum=_sha256_payload(state_payload),
    )
    conditional_path = _conditional_path(design, definition, eth_prices)
    base_bundle = load_empirical_configuration_bundle(
        design.baseline_path,
        verify_registry_checksums=False,
    )
    liquidation = simulate_candidate_invariant_liquidation_path(
        state=state,
        path=conditional_path,
        replication=replication,
        registry_id=design.registry_id,
        config=config,
        maximum_liquidations_per_step=(
            base_bundle.liquidation_config.max_liquidations_per_step
        ),
        profile_path=design.baseline_path,
        base_liquidation_config=base_bundle.liquidation_config,
        liquidation_seed=derive_recovery_seed(
            replication, "liquidation_randomness"
        ),
    )
    _, _, stage1_owners = load_stage1_owners()
    residual_seed = derive_recovery_seed(replication, "market_innovations")
    rng = np.random.default_rng(residual_seed)
    innovations = sample_residual_blocks(
        stage1_owners["source"],
        block_count=math.ceil(design.total_hours / 24),
        rng=rng,
    )[: design.total_hours]
    scaling = json.loads(SPARSE_SCALING_EVIDENCE.read_text(encoding="utf-8"))
    scenarios = {
        scenario: _simulate_market_scenario(
            design=design,
            definition=definition,
            eth_prices=eth_prices,
            liquidation=liquidation,
            innovations=innovations,
            scenario_identifier=scenario,
            stage1_owners=stage1_owners,
            peg_scale=float(scaling["lagged_below_peg_gap"]["positive_q95"]),
            eth_scale=float(scaling["lagged_24h_eth_downside"]["positive_q95"]),
            initial_vault_count=state.vault_count,
        )
        for scenario in EXPECTED_SCENARIO_ORDER
    }
    seeds = replication_seed_record(replication)
    return {
        "schema_version": 1,
        "path_identifier": path_identifier,
        "replication": replication,
        "state_checksum": state.state_checksum,
        "seed_ownership": seeds,
        "path_checksum": path_checksum(eth_prices),
        "scenarios": scenarios,
        "result_checksum": _sha256_payload(
            {
                "path_identifier": path_identifier,
                "replication": replication,
                "state_checksum": state.state_checksum,
                "seed_ownership": seeds,
                "scenarios": scenarios,
            }
        ),
    }


def _checkpoint_path(output_dir: Path, path_identifier: str, replication: int) -> Path:
    return output_dir / "checkpoints" / path_identifier / f"replication_{replication:03d}.json"


def _valid_checkpoint(
    path: Path,
    *,
    path_identifier: str,
    replication: int,
) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return (
        payload.get("path_identifier") == path_identifier
        and payload.get("replication") == replication
        and len(payload.get("scenarios", {})) == len(EXPECTED_SCENARIO_ORDER)
        and set(payload.get("scenarios", {})) == set(EXPECTED_SCENARIO_ORDER)
        and all(
            payload["scenarios"][scenario]["summary"]["numerical_valid"]
            for scenario in EXPECTED_SCENARIO_ORDER
        )
    )


def run_smoke(
    design: RecoveryDesign | None = None,
) -> dict[str, Any]:
    """Run one deterministic replication across all sixteen cells."""
    owner = design or load_recovery_design()
    results = [
        simulate_path_replication(
            path_identifier=path_identifier,
            replication=0,
            config_path=owner.config_path,
        )
        for path_identifier in PATH_ORDER
    ]
    stream_checksums = {
        result["seed_ownership"]["paired_stream_checksum"] for result in results
    }
    state_checksums = {result["state_checksum"] for result in results}
    if len(stream_checksums) != 1 or len(state_checksums) != 1:
        raise ValueError("Smoke cells do not share non-treatment randomness.")
    explicit = resolve_confidence_scenario("stage1_only")
    implicit = resolve_confidence_scenario()
    if explicit != implicit:
        raise ValueError("Implicit and explicit stage1_only differ.")
    return {
        "cell_count": sum(len(result["scenarios"]) for result in results),
        "replication": 0,
        "crn_valid": True,
        "state_checksum": next(iter(state_checksums)),
        "paired_stream_checksum": next(iter(stream_checksums)),
        "stage1_default_equivalent": True,
        "result_checksum": _sha256_payload(results),
    }


def preflight(
    design: RecoveryDesign | None = None,
    *,
    run_smoke_test: bool = True,
) -> dict[str, Any]:
    """Validate design, storage, registry and optionally the 16-cell smoke."""
    owner = design or load_recovery_design()
    paths = {
        definition.identifier: build_eth_path(owner, definition)
        for definition in owner.path_definitions
    }
    cells = build_cell_registry(owner, paths)
    identity = experiment_identity(owner, cells)
    disk = shutil.disk_usage(REPOSITORY_ROOT)
    if disk.free < owner.minimum_free_bytes:
        raise RuntimeError("Fewer than 10 GiB remain before recovery execution.")
    existing_size = sum(
        path.stat().st_size
        for path in (REPOSITORY_ROOT / "outputs/experiments").rglob("*")
        if path.is_file()
    )
    projected = owner.replications * len(PATH_ORDER) * 120_000
    if projected > owner.maximum_new_bytes:
        raise RuntimeError("Projected recovery output exceeds 500 MB.")
    result = {
        "experiment_identity": identity,
        "path_count": len(paths),
        "cell_count": len(cells),
        "replications_per_cell": owner.replications,
        "simulation_count": len(cells) * owner.replications,
        "free_disk_bytes": disk.free,
        "existing_experiment_output_bytes": existing_size,
        "projected_output_bytes": projected,
        "path_checksums": {
            identifier: path_checksum(values) for identifier, values in paths.items()
        },
        "crn_registry_sha256": seed_registry_checksum(owner.replications),
        "smoke": run_smoke(owner) if run_smoke_test else None,
    }
    return result


def write_preregistration_snapshot(
    design: RecoveryDesign | None = None,
) -> dict[str, Any]:
    """Freeze the result-blind design beneath its content-addressed output."""
    owner = design or load_recovery_design()
    paths = {
        definition.identifier: build_eth_path(owner, definition)
        for definition in owner.path_definitions
    }
    cells = build_cell_registry(owner, paths)
    identity = experiment_identity(owner, cells)
    payload = {
        "schema_version": 1,
        "experiment_identity": identity,
        "design_configuration_sha256": owner.config_sha256,
        "baseline_sha256": owner.baseline_sha256,
        "shock_sha256": shock_checksum(owner),
        "path_checksums": {
            identifier: path_checksum(values) for identifier, values in paths.items()
        },
        "confidence_registry_sha256": EXPECTED_CONFIDENCE_REGISTRY_SHA256,
        "confidence_configuration_sha256": EXPECTED_CONFIDENCE_CONFIG_SHA256,
        "cell_order": [cell.identifier for cell in cells],
        "replications_per_cell": owner.replications,
        "seed_registry_sha256": seed_registry_checksum(owner.replications),
        "primary_metrics": list(PRIMARY_METRICS),
        "recovery_contrasts": list(RECOVERY_CONTRASTS),
        "confidence_contrasts": list(CONFIDENCE_CONTRASTS),
        "interaction": "paired difference-in-differences",
        "classification_hierarchy": ["H4a", "H4b", "H4c", "overall"],
        "result_blind": True,
        "runtime_adopted": False,
    }
    destination = (
        owner.output_root / identity / "preregistration_snapshot.json"
    )
    _atomic_json(destination, payload)
    return {
        "experiment_identity": identity,
        "path": destination.as_posix(),
        "sha256": sha256_file(destination),
        "result_blind": True,
    }


def run_matrix(
    *,
    design: RecoveryDesign | None = None,
    workers: int = 4,
    resume: bool = True,
    max_replications: int | None = None,
) -> dict[str, Any]:
    """Execute or resume all path-replication checkpoints."""
    owner = design or load_recovery_design()
    paths = {
        definition.identifier: build_eth_path(owner, definition)
        for definition in owner.path_definitions
    }
    cells = build_cell_registry(owner, paths)
    identity = experiment_identity(owner, cells)
    output_dir = owner.output_root / identity
    output_dir.mkdir(parents=True, exist_ok=True)
    replications = (
        owner.replications if max_replications is None else max_replications
    )
    if not 1 <= replications <= owner.replications:
        raise ValueError("max_replications must lie within the registered design.")
    tasks: list[tuple[str, int]] = []
    reused = 0
    for path_identifier in PATH_ORDER:
        for replication in range(replications):
            checkpoint = _checkpoint_path(output_dir, path_identifier, replication)
            if resume and _valid_checkpoint(
                checkpoint,
                path_identifier=path_identifier,
                replication=replication,
            ):
                reused += 1
            else:
                tasks.append((path_identifier, replication))
    started = time.perf_counter()
    completed = 0
    if workers == 1:
        for path_identifier, replication in tasks:
            result = simulate_path_replication(
                path_identifier=path_identifier,
                replication=replication,
                config_path=owner.config_path,
            )
            _atomic_json(
                _checkpoint_path(output_dir, path_identifier, replication),
                result,
            )
            completed += 1
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(
                    simulate_path_replication,
                    path_identifier=path_identifier,
                    replication=replication,
                    config_path=owner.config_path,
                ): (path_identifier, replication)
                for path_identifier, replication in tasks
            }
            for future in as_completed(future_map):
                path_identifier, replication = future_map[future]
                result = future.result()
                _atomic_json(
                    _checkpoint_path(output_dir, path_identifier, replication),
                    result,
                )
                completed += 1
    wall = time.perf_counter() - started
    output_size = sum(
        path.stat().st_size for path in output_dir.rglob("*") if path.is_file()
    )
    if output_size > owner.maximum_new_bytes:
        raise RuntimeError("Recovery output exceeded the registered 500 MB cap.")
    return {
        "experiment_identity": identity,
        "output_dir": output_dir.as_posix(),
        "workers": workers,
        "completed_path_replications": completed,
        "reused_path_replications": reused,
        "completed_simulations": (completed + reused) * 4,
        "wall_time_seconds": wall,
        "throughput_simulations_per_second": (
            0.0 if wall == 0.0 else completed * 4 / wall
        ),
        "output_size_bytes": output_size,
        "free_disk_bytes": shutil.disk_usage(REPOSITORY_ROOT).free,
        "complete": completed + reused == len(PATH_ORDER) * owner.replications,
    }


def load_run_summaries(
    design: RecoveryDesign,
    experiment_id: str,
    *,
    require_complete: bool = True,
) -> tuple[pd.DataFrame, dict[tuple[str, str], dict[str, np.ndarray]]]:
    """Load compact checkpoints into paired summaries and mean-path accumulators."""
    output_dir = design.output_root / experiment_id
    rows: list[dict[str, Any]] = []
    paths: dict[tuple[str, str], dict[str, list[np.ndarray]]] = {}
    for path_identifier in PATH_ORDER:
        for replication in range(design.replications):
            checkpoint = _checkpoint_path(output_dir, path_identifier, replication)
            if not _valid_checkpoint(
                checkpoint,
                path_identifier=path_identifier,
                replication=replication,
            ):
                if require_complete:
                    raise ValueError(f"Missing valid checkpoint: {checkpoint}.")
                continue
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            for scenario in EXPECTED_SCENARIO_ORDER:
                result = payload["scenarios"][scenario]
                rows.append(
                    {
                        "cell_identifier": f"{path_identifier}__{scenario}",
                        "replication": replication,
                        "state_checksum": payload["state_checksum"],
                        "paired_stream_checksum": payload["seed_ownership"][
                            "paired_stream_checksum"
                        ],
                        **result["summary"],
                    }
                )
                key = (path_identifier, scenario)
                paths.setdefault(key, {"dai": [], "confidence": []})
                paths[key]["dai"].append(
                    np.asarray(result["dai_price_path"], dtype=float)
                )
                paths[key]["confidence"].append(
                    np.asarray(result["confidence_path"], dtype=float)
                )
    frame = pd.DataFrame(rows).sort_values(
        ["recovery_path", "confidence_scenario", "replication"],
        key=lambda series: (
            series.map({value: index for index, value in enumerate(PATH_ORDER)})
            if series.name == "recovery_path"
            else series.map(
                {
                    value: index
                    for index, value in enumerate(EXPECTED_SCENARIO_ORDER)
                }
            )
            if series.name == "confidence_scenario"
            else series
        ),
        kind="mergesort",
    )
    expected = len(PATH_ORDER) * len(EXPECTED_SCENARIO_ORDER) * design.replications
    if require_complete and len(frame) != expected:
        raise ValueError("Completed run count differs from 2,048.")
    for replication, group in frame.groupby("replication"):
        if group["paired_stream_checksum"].nunique() != 1:
            raise ValueError(f"CRN stream ownership differs in replication {replication}.")
        if group["state_checksum"].nunique() != 1:
            raise ValueError(f"Initial states differ in replication {replication}.")
    means = {
        key: {
            label: np.mean(np.stack(values), axis=0)
            for label, values in grouped.items()
        }
        for key, grouped in paths.items()
    }
    return frame.reset_index(drop=True), means


def _distribution(values: np.ndarray) -> dict[str, float]:
    values = np.asarray(values, dtype=float)
    count = len(values)
    standard_error = (
        float(np.std(values, ddof=1) / math.sqrt(count)) if count > 1 else 0.0
    )
    estimate = float(np.mean(values))
    return {
        "mean": estimate,
        "standard_error": standard_error,
        "ci_lower": estimate - 1.96 * standard_error,
        "ci_upper": estimate + 1.96 * standard_error,
        "median": float(np.median(values)),
        "q25": float(np.quantile(values, 0.25)),
        "q75": float(np.quantile(values, 0.75)),
        "q05": float(np.quantile(values, 0.05)),
        "q95": float(np.quantile(values, 0.95)),
    }


def cell_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Return one deterministic row per cell and registered metric."""
    rows: list[dict[str, Any]] = []
    for path_identifier in PATH_ORDER:
        for scenario in EXPECTED_SCENARIO_ORDER:
            group = frame.loc[
                frame["recovery_path"].eq(path_identifier)
                & frame["confidence_scenario"].eq(scenario)
            ]
            for metric in SUMMARY_METRICS:
                distribution = _distribution(group[metric].to_numpy(dtype=float))
                rows.append(
                    {
                        "cell_identifier": f"{path_identifier}__{scenario}",
                        "recovery_path": path_identifier,
                        "confidence_scenario": scenario,
                        "metric": metric,
                        "replication_count": len(group),
                        **distribution,
                        "censoring_share": (
                            float(group["right_censored"].mean())
                            if metric == "restricted_mean_recovery_time"
                            else 0.0
                        ),
                        "numerical_valid_count": int(
                            group["numerical_valid"].sum()
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _paired_row(
    differences: np.ndarray,
    *,
    contrast_family: str,
    contrast: str,
    metric: str,
) -> dict[str, Any]:
    distribution = _distribution(differences)
    expected_direction = (
        "negative" if metric in LOWER_IS_BETTER else "positive"
    )
    expected = (
        distribution["mean"] < 0.0
        if expected_direction == "negative"
        else distribution["mean"] > 0.0
    )
    excludes_zero = (
        distribution["ci_upper"] < 0.0 or distribution["ci_lower"] > 0.0
    )
    row: dict[str, Any] = {
        "contrast_family": contrast_family,
        "contrast": contrast,
        "metric": metric,
        "paired_estimate": distribution["mean"],
        "standard_error": distribution["standard_error"],
        "ci_lower": distribution["ci_lower"],
        "ci_upper": distribution["ci_upper"],
        "median_paired_difference": distribution["median"],
        "q25_paired_difference": distribution["q25"],
        "q75_paired_difference": distribution["q75"],
        "expected_direction": expected_direction,
        "expected_direction_flag": bool(expected),
        "support_flag": bool(expected and excludes_zero),
    }
    if metric in BINARY_METRICS:
        row["discordant_positive_count"] = int(np.count_nonzero(differences == 1))
        row["discordant_negative_count"] = int(np.count_nonzero(differences == -1))
    else:
        row["discordant_positive_count"] = 0
        row["discordant_negative_count"] = 0
    return row


def paired_contrasts(frame: pd.DataFrame) -> pd.DataFrame:
    """Calculate all pre-registered path and stage1-reference contrasts."""
    indexed = frame.set_index(
        ["recovery_path", "confidence_scenario", "replication"]
    ).sort_index()
    rows: list[dict[str, Any]] = []
    for scenario in EXPECTED_SCENARIO_ORDER:
        for treatment, reference in RECOVERY_CONTRASTS:
            for metric in SUMMARY_METRICS:
                differences = (
                    indexed.loc[(treatment, scenario), metric]
                    - indexed.loc[(reference, scenario), metric]
                ).to_numpy(dtype=float)
                rows.append(
                    _paired_row(
                        differences,
                        contrast_family="recovery_path",
                        contrast=f"{treatment} - {reference} | {scenario}",
                        metric=metric,
                    )
                )
    for path_identifier in PATH_ORDER:
        for treatment, reference in CONFIDENCE_CONTRASTS:
            for metric in SUMMARY_METRICS:
                differences = (
                    indexed.loc[(path_identifier, treatment), metric]
                    - indexed.loc[(path_identifier, reference), metric]
                ).to_numpy(dtype=float)
                rows.append(
                    _paired_row(
                        differences,
                        contrast_family="confidence",
                        contrast=f"{treatment} - {reference} | {path_identifier}",
                        metric=metric,
                    )
                )
    return pd.DataFrame(rows)


def interaction_contrasts(frame: pd.DataFrame) -> pd.DataFrame:
    """Calculate active-scenario difference-in-differences without ranking."""
    indexed = frame.set_index(
        ["recovery_path", "confidence_scenario", "replication"]
    ).sort_index()
    rows: list[dict[str, Any]] = []
    for scenario in EXPECTED_SCENARIO_ORDER[1:]:
        for path_identifier in PATH_ORDER[1:]:
            for metric in SUMMARY_METRICS:
                scenario_path = indexed.loc[(path_identifier, scenario), metric]
                stage1_path = indexed.loc[
                    (path_identifier, "stage1_only"), metric
                ]
                scenario_persistent = indexed.loc[
                    ("persistent_trough", scenario), metric
                ]
                stage1_persistent = indexed.loc[
                    ("persistent_trough", "stage1_only"), metric
                ]
                values = (
                    scenario_path
                    - stage1_path
                    - scenario_persistent
                    + stage1_persistent
                ).to_numpy(dtype=float)
                distribution = _distribution(values)
                rows.append(
                    {
                        "confidence_scenario": scenario,
                        "recovery_path": path_identifier,
                        "metric": metric,
                        "difference_in_differences": distribution["mean"],
                        "standard_error": distribution["standard_error"],
                        "ci_lower": distribution["ci_lower"],
                        "ci_upper": distribution["ci_upper"],
                        "median": distribution["median"],
                        "q25": distribution["q25"],
                        "q75": distribution["q75"],
                        "direction": (
                            "negative"
                            if distribution["mean"] < 0.0
                            else "positive"
                            if distribution["mean"] > 0.0
                            else "zero"
                        ),
                        "material_interaction_flag": bool(
                            abs(distribution["mean"]) > 1e-12
                            and (
                                distribution["ci_upper"] < 0.0
                                or distribution["ci_lower"] > 0.0
                            )
                        ),
                        "mechanism_diagnostics": (
                            "paired CRN difference-in-differences"
                        ),
                    }
                )
    return pd.DataFrame(rows)


def classify_experiment(
    contrasts: pd.DataFrame,
    interactions: pd.DataFrame,
    frame: pd.DataFrame,
    *,
    crn_valid: bool = True,
    scenario_valid: bool = True,
) -> dict[str, Any]:
    """Apply the fixed H4 and overall decision hierarchy."""
    failure_shares = (
        1.0
        - frame.groupby(["recovery_path", "confidence_scenario"])[
            "numerical_valid"
        ].mean()
    )
    invalid = (
        not crn_valid
        or not scenario_valid
        or (failure_shares > 0.01).any()
        or len(frame) == 0
    )
    if invalid:
        return {
            "H4a": "invalid",
            "H4b": "invalid",
            "H4c": "invalid",
            "overall_classification": "eth_recovery_experiment_invalid",
        }
    recovery = contrasts.loc[contrasts["contrast_family"].eq("recovery_path")]
    h4a_support_count = 0
    h4a_opposite = False
    for scenario in EXPECTED_SCENARIO_ORDER:
        selected = recovery.loc[
            recovery["contrast"].eq(
                f"full_week - persistent_trough | {scenario}"
            )
            & recovery["metric"].isin(
                ["below_peg_burden", "restricted_mean_recovery_time"]
            )
        ]
        if len(selected) == 2 and selected["support_flag"].all():
            h4a_support_count += 1
        h4a_opposite |= bool(
            (
                (selected["ci_lower"] > 0.0)
                & selected["metric"].isin(
                    ["below_peg_burden", "restricted_mean_recovery_time"]
                )
            ).any()
        )
    h4a = h4a_support_count >= 3 and not h4a_opposite
    h4b_expected = 0
    h4b_opposite = False
    for scenario in EXPECTED_SCENARIO_ORDER:
        selected = recovery.loc[
            recovery["contrast"].eq(f"rapid_full - full_week | {scenario}")
            & recovery["metric"].isin(
                ["below_peg_burden", "restricted_mean_recovery_time"]
            )
        ]
        if (selected["expected_direction_flag"]).any():
            h4b_expected += 1
        h4b_opposite |= bool((selected["ci_lower"] > 0.0).all())
    h4b = h4b_expected >= 3 and not h4b_opposite
    h4c = bool(
        interactions.loc[
            interactions["metric"].isin(
                [
                    "below_peg_burden",
                    "restricted_mean_recovery_time",
                    "recovery_probability_720h",
                ]
            ),
            "material_interaction_flag",
        ].any()
    )
    solvency = recovery.loc[
        recovery["contrast"].str.startswith("full_week - persistent_trough")
        & recovery["metric"].isin(
            [
                "maximum_unresolved_tab_dai",
                "cumulative_realised_bad_debt_dai",
            ]
        )
    ]
    major_opposite_solvency = bool((solvency["ci_lower"] > 0.0).any())
    path_conclusion_reversed = h4a_support_count < 3 and h4c
    if h4a and not major_opposite_solvency and not path_conclusion_reversed:
        overall = "collateral_recovery_robustly_improves_peg"
    elif h4a_support_count > 0 and (h4c or h4a_support_count < 3):
        overall = "collateral_recovery_effect_confidence_dependent"
    elif h4a_support_count > 0 and major_opposite_solvency:
        overall = "recovery_path_improves_price_but_not_solvency"
    else:
        overall = "no_clear_recovery_path_effect"
    return {
        "H4a": "supported" if h4a else "not_supported",
        "H4a_supporting_scenarios": h4a_support_count,
        "H4b": "supported" if h4b else "not_supported",
        "H4b_expected_direction_scenarios": h4b_expected,
        "H4c": "present" if h4c else "not_present",
        "overall_classification": overall,
        "major_opposite_solvency_effect": major_opposite_solvency,
    }


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            key: (
                value.item()
                if isinstance(value, np.generic)
                else bool(value)
                if isinstance(value, np.bool_)
                else value
            )
            for key, value in row.items()
        }
        for row in frame.to_dict(orient="records")
    ]


def build_evidence_payloads(
    *,
    design: RecoveryDesign,
    experiment_id: str,
    benchmark: Mapping[str, Any],
) -> dict[str, bytes]:
    """Construct deterministic compact evidence from completed checkpoints."""
    paths = {
        definition.identifier: build_eth_path(design, definition)
        for definition in design.path_definitions
    }
    cells = build_cell_registry(design, paths)
    expected_identity = experiment_identity(design, cells)
    if experiment_id != expected_identity:
        raise ValueError("Experiment identity does not match the design.")
    frame, mean_paths = load_run_summaries(design, experiment_id)
    summaries = cell_summary(frame)
    contrasts = paired_contrasts(frame)
    interactions = interaction_contrasts(frame)
    decision = classify_experiment(contrasts, interactions, frame)
    path_rows = [
        {
            "order": definition.order,
            "path_identifier": definition.identifier,
            "pre_shock_price_usd": design.pre_shock_price,
            "trough_price_usd": design.trough_price,
            "recovery_fraction": definition.recovery_fraction,
            "recovery_duration_hours": definition.recovery_duration_hours,
            "terminal_price_usd": float(paths[definition.identifier][-1]),
            "path_sha256": path_checksum(paths[definition.identifier]),
        }
        for definition in design.path_definitions
    ]
    registry_rows = [
        {
            "cell_order": cell.order,
            "cell_identifier": cell.identifier,
            "recovery_path": cell.recovery_path,
            "confidence_scenario": cell.confidence_scenario,
            "baseline_sha256": design.baseline_sha256,
            "path_sha256": cell.path_checksum,
            "scenario_sha256": cell.scenario_checksum,
            "replication_count": cell.replication_count,
            "cell_sha256": cell.cell_checksum,
        }
        for cell in cells
    ]
    specification = {
        "schema_version": 1,
        "purpose": (
            "Evaluate joint post-shock ETH recovery and transparent "
            "persistent-confidence assumptions in the ETH-only mechanism."
        ),
        "experiment_identity": experiment_id,
        "baseline": {
            "path": design.baseline_path.relative_to(REPOSITORY_ROOT).as_posix(),
            "sha256": design.baseline_sha256,
            "vault_state": "production_default",
        },
        "shock": {
            "sha256": shock_checksum(design),
            "pre_shock_price_usd": design.pre_shock_price,
            "trough_price_usd": design.trough_price,
            "onset_hour": design.shock_hour,
            "arithmetic_loss_fraction": -0.43,
            "log_loss": math.log(design.trough_price)
            - math.log(design.pre_shock_price),
            "instantaneous": True,
        },
        "path_definitions": path_rows,
        "confidence_registry_sha256": EXPECTED_CONFIDENCE_REGISTRY_SHA256,
        "confidence_configuration_sha256": EXPECTED_CONFIDENCE_CONFIG_SHA256,
        "cell_order": [cell.identifier for cell in cells],
        "replications_per_cell": design.replications,
        "seed_ownership": {
            "registry_id": design.registry_id,
            "seed_registry_sha256": seed_registry_checksum(design.replications),
            "common_random_numbers": True,
        },
        "horizon": {
            "pre_shock_hours": design.pre_shock_hours,
            "post_shock_hours": design.post_shock_hours,
            "total_hours": design.total_hours,
        },
        "recovery_definition": {
            "band": [design.lower_band, design.upper_band],
            "consecutive_hours": design.stability_hours,
            "restricted_mean_cap_hours": design.recovery_cap_hours,
        },
        "primary_outcomes": list(PRIMARY_METRICS),
        "contrast_definitions": {
            "recovery_path": list(RECOVERY_CONTRASTS),
            "confidence": list(CONFIDENCE_CONTRASTS),
            "interaction": "paired difference-in-differences",
        },
        "classification_hierarchy": ["H4a", "H4b", "H4c", "overall"],
        "final_validation_excluded": True,
        "usdc_svb_used": False,
        "multi_collateral_executed": False,
        "scenario_ranked": False,
        "scenario_selected": None,
        "runtime_adopted": False,
    }
    numerical_failures = (
        frame.assign(failed=~frame["numerical_valid"])
        .groupby(["recovery_path", "confidence_scenario"])["failed"]
        .sum()
        .to_dict()
    )
    result_checksums = {
        f"{path_identifier}__{scenario}__mean_dai": hashlib.sha256(
            np.asarray(mean_paths[(path_identifier, scenario)]["dai"], dtype="<f8").tobytes()
        ).hexdigest()
        for path_identifier in PATH_ORDER
        for scenario in EXPECTED_SCENARIO_ORDER
    }
    reproducibility = {
        "schema_version": 1,
        "code_identity": _code_identity(),
        "experiment_identity": experiment_id,
        "baseline_sha256": design.baseline_sha256,
        "shock_sha256": shock_checksum(design),
        "path_checksums": {
            row["path_identifier"]: row["path_sha256"] for row in path_rows
        },
        "confidence_registry_sha256": EXPECTED_CONFIDENCE_REGISTRY_SHA256,
        "seed_registry_sha256": seed_registry_checksum(design.replications),
        "crn_validation": {
            "passed": True,
            "replications": design.replications,
            "non_treatment_streams_shared": True,
            "initial_states_shared": True,
        },
        "completed_runs": len(frame),
        "expected_runs": 2048,
        "numerical_failure_counts": {
            f"{key[0]}__{key[1]}": int(value)
            for key, value in numerical_failures.items()
        },
        "result_checksums": result_checksums,
        "final_validation_data_used": False,
        "multi_collateral_execution": False,
        "scenario_selection": None,
        "runtime_adopted": False,
    }
    decision = {
        "schema_version": 1,
        **decision,
        "main_unresolved_mechanisms": (
            "Separate gas, keeper-capacity and oracle-delay crosses remain outside "
            "this controlled experiment."
        ),
        "backlog_or_bad_debt_limited_recovery": bool(
            (
                (frame["maximum_unresolved_tab_dai"] > 1e-9)
                | (frame["maximum_active_bad_debt_dai"] > 1e-9)
            ).any()
        ),
        "confidence_scenario_ranked": False,
        "confidence_scenario_selected": None,
        "next_authorised_boundary": {
            "principal_multicollateral_path": "full_week",
            "adverse_sensitivity": "persistent_trough",
            "optional_robustness": ["rapid_full", "partial_week"],
            "confidence_dimension": "all four fixed scenarios; no selected case",
        },
        "runtime_adopted": False,
    }
    benchmark_payload = {
        "schema_version": 1,
        **dict(benchmark),
        "host_dependent": True,
    }
    cell_columns = list(summaries.columns)
    contrast_columns = list(contrasts.columns)
    interaction_columns = list(interactions.columns)
    return {
        "eth_recovery_specification.json": (
            json.dumps(specification, indent=2, sort_keys=True) + "\n"
        ).encode(),
        "eth_recovery_paths.csv": _csv_bytes(
            path_rows,
            (
                "order",
                "path_identifier",
                "pre_shock_price_usd",
                "trough_price_usd",
                "recovery_fraction",
                "recovery_duration_hours",
                "terminal_price_usd",
                "path_sha256",
            ),
        ),
        "eth_recovery_registry.csv": _csv_bytes(
            registry_rows,
            (
                "cell_order",
                "cell_identifier",
                "recovery_path",
                "confidence_scenario",
                "baseline_sha256",
                "path_sha256",
                "scenario_sha256",
                "replication_count",
                "cell_sha256",
            ),
        ),
        "eth_recovery_cell_summary.csv": _csv_bytes(
            _records(summaries), cell_columns
        ),
        "eth_recovery_contrasts.csv": _csv_bytes(
            _records(contrasts), contrast_columns
        ),
        "eth_recovery_interactions.csv": _csv_bytes(
            _records(interactions), interaction_columns
        ),
        "eth_recovery_decision.json": (
            json.dumps(decision, indent=2, sort_keys=True) + "\n"
        ).encode(),
        "eth_recovery_reproducibility.json": (
            json.dumps(reproducibility, indent=2, sort_keys=True) + "\n"
        ).encode(),
        "eth_recovery_benchmark.json": (
            json.dumps(benchmark_payload, indent=2, sort_keys=True) + "\n"
        ).encode(),
    }


def write_evidence(
    *,
    design: RecoveryDesign,
    experiment_id: str,
    benchmark: Mapping[str, Any],
    evidence_dir: Path | None = None,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Atomically write and register all compact recovery artefacts."""
    output = evidence_dir or design.evidence_dir
    payloads = build_evidence_payloads(
        design=design,
        experiment_id=experiment_id,
        benchmark=benchmark,
    )
    for name, payload in payloads.items():
        _atomic_bytes(output / name, payload)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    retained = [
        record
        for record in manifest["artefacts"]
        if not str(record["path"]).startswith(
            "data/provenance/experiments/recovery/"
        )
    ]
    records = [
        {
            "classification": "pre_registered_eth_recovery_experiment",
            "path": (output / name).relative_to(REPOSITORY_ROOT).as_posix(),
            "runtime_adopted": False,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }
        for name, payload in sorted(payloads.items())
    ]
    updated = {
        **manifest,
        "artefact_count": len(retained) + len(records),
        "artefacts": sorted(retained + records, key=lambda row: row["path"]),
        "purpose": (
            "Content-addressed experimental-design and ETH recovery evidence; "
            "no confidence scenario is selected or adopted."
        ),
    }
    _atomic_json(manifest_path, updated)
    return {
        "experiment_identity": experiment_id,
        "evidence_dir": output.as_posix(),
        "artefact_count": len(records),
        "checksums": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in sorted(payloads.items())
        },
    }


def validate_evidence(
    *,
    design: RecoveryDesign | None = None,
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate complete compact evidence and its interpretation boundary."""
    owner = design or load_recovery_design()
    directory = evidence_dir or owner.evidence_dir
    missing = [name for name in EVIDENCE_FILENAMES if not (directory / name).is_file()]
    if missing:
        raise ValueError(f"Missing ETH recovery evidence: {missing}.")
    specification = json.loads(
        (directory / "eth_recovery_specification.json").read_text()
    )
    decision = json.loads((directory / "eth_recovery_decision.json").read_text())
    registry = pd.read_csv(directory / "eth_recovery_registry.csv")
    summary = pd.read_csv(directory / "eth_recovery_cell_summary.csv")
    if len(registry) != 16 or registry["cell_identifier"].nunique() != 16:
        raise ValueError("Evidence does not contain exactly 16 cells.")
    if set(summary["replication_count"]) != {128}:
        raise ValueError("Evidence does not contain 128 replications per cell.")
    if specification["scenario_ranked"] or specification["scenario_selected"] is not None:
        raise ValueError("Recovery evidence ranks or selects a confidence scenario.")
    if (
        not specification["final_validation_excluded"]
        or specification["usdc_svb_used"]
        or specification["multi_collateral_executed"]
        or specification["runtime_adopted"]
        or decision["runtime_adopted"]
    ):
        raise ValueError("Recovery evidence crossed its authorised boundary.")
    manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    records = {record["path"]: record for record in manifest["artefacts"]}
    for name in EVIDENCE_FILENAMES:
        path = directory / name
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        if relative not in records or records[relative]["sha256"] != sha256_file(path):
            raise ValueError(f"Recovery evidence is not registered: {relative}.")
    return {
        "experiment_identity": specification["experiment_identity"],
        "cell_count": len(registry),
        "metric_rows": len(summary),
        "manifest_records": len(EVIDENCE_FILENAMES),
        "overall_classification": decision["overall_classification"],
        "runtime_adopted": False,
    }
