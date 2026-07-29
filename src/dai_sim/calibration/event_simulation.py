"""Dormant conditional-event simulation for behavioural calibration.

This module owns a deliberately calibration-only experiment.  It conditions
on observed ETH prices and one observed starting DAI price, but it does not
claim to replay the historical Maker system.  Production simulation entry
points do not import or call this module.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import tempfile
import time
import tracemalloc
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from dai_sim.inputs.configuration import (
    REPOSITORY_ROOT,
    load_configuration_payload,
    sha256_file,
)
from dai_sim.inputs.liquidations import (
    LiquidationDemandConfig,
    LiquidationDemandProcess,
)
from dai_sim.inputs.vaults import (
    DEFAULT_TRANCHE_B_CONFIG_PATH,
    initialise_vaults,
    load_tranche_b_configuration,
)
from dai_sim.model.collateral import (
    CollateralConfig,
    CollateralPortfolioConfig,
)
from dai_sim.model.confidence import (
    PersistentConfidenceConfig,
    PersistentConfidenceState,
    RecoveryGateInputs,
    update_persistent_confidence,
)
from dai_sim.model.liquidation import liquidate_vaults, summarise_liquidations
from dai_sim.model.market import coefficient_normalised_market_response
from dai_sim.model.simulation import SimulationConfig
from dai_sim.model.vault import Vault

from .market import (
    CONFIDENCE_EVIDENCE,
    CONFIDENCE_PANEL,
    CONFIDENCE_PANEL_SHA256,
    build_residual_block_source,
    load_confidence_panel,
    ordinary_confidence_sample,
    sample_residual_blocks,
)
from .simulated_moments import (
    DEFAULT_REGISTRY_IDS,
    StructuralParameters,
    aggregate_simulated_core_moments,
    build_event_catalogue,
    derive_seed,
    select_event_smoke_subset,
    sobol_candidates,
    validate_structural_parameters,
)


DEFAULT_EVENT_DIAGNOSTICS = (
    REPOSITORY_ROOT
    / "outputs/diagnostics/calibration/confidence/event_simulation"
)
CALIBRATION_MANIFEST = (
    REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
)
SPARSE_SCALING_EVIDENCE = (
    CONFIDENCE_EVIDENCE / "sparse_predictor_scaling.json"
)
EXPECTED_RESIDUAL_SEQUENCE_SHA256 = (
    "3fa2319cee9e1749405c0dc477e0f11ef9c31dd83c371b619bd33eda23c37c30"
)
EXPECTED_RESIDUAL_BLOCK_SHA256 = (
    "6f55b51acfc1da23836b3d847153bd4f68e4a38fc33fd967e9d3b795737bf28c"
)
PROBE_INDICES = (0, 127, 255)
EXPECTED_STAGE1_STATUS = "accepted_for_future_smm"
PRIMARY_COLLATERAL_MODE = "ETH-only mechanism core"


@dataclass(frozen=True)
class ConditionalEventSimulationConfig:
    """Immutable controls for the conditional calibration experiment."""

    pre_roll_hours: int
    post_recovery_hours: int
    maximum_event_horizon_hours: int
    stability_hours: int
    recovery_band_lower: float
    recovery_band_upper: float
    material_downside_threshold: float
    peg_stress_weight: float
    collateral_stress_weight: float
    stage1_evidence_reference: str
    residual_evidence_reference: str
    initial_state_reference: str
    liquidation_pressure_tolerance: float
    bad_debt_absolute_tolerance: float
    bad_debt_relative_tolerance: float
    dai_min_price: float
    dai_max_price: float
    step_hours: int
    primary_collateral_mode: str
    calibration_only: bool
    runtime_adopted: bool

    def validate(self) -> None:
        """Validate fixed design controls without supplying Stage 2 values."""
        if self.pre_roll_hours != 48:
            raise ValueError("The conditional pre-roll must be exactly 48 hours.")
        if self.post_recovery_hours != 24:
            raise ValueError("The post-recovery allowance must be 24 hours.")
        if self.stability_hours != 24:
            raise ValueError("The recovery stability duration must be 24 hours.")
        if self.step_hours != 1:
            raise ValueError("The conditional model step must be one hour.")
        if not math.isclose(self.recovery_band_lower, 0.995):
            raise ValueError("The lower recovery bound must be 0.995.")
        if not math.isclose(self.recovery_band_upper, 1.005):
            raise ValueError("The upper recovery bound must be 1.005.")
        if not math.isclose(self.material_downside_threshold, 0.995):
            raise ValueError("Material downside must be defined by p < 0.995.")
        if not math.isclose(
            self.peg_stress_weight + self.collateral_stress_weight,
            1.0,
            abs_tol=1e-12,
        ):
            raise ValueError("Stress weights must sum to one.")
        if self.maximum_event_horizon_hours <= self.pre_roll_hours:
            raise ValueError("The common horizon must exceed the pre-roll.")
        if self.liquidation_pressure_tolerance < 0.0:
            raise ValueError("Liquidation-pressure tolerance cannot be negative.")
        if (
            self.bad_debt_absolute_tolerance < 0.0
            or self.bad_debt_relative_tolerance < 0.0
        ):
            raise ValueError("Bad-debt tolerances cannot be negative.")
        if not 0.0 < self.dai_min_price < self.dai_max_price:
            raise ValueError("Require 0 < DAI minimum < DAI maximum.")
        if self.primary_collateral_mode != PRIMARY_COLLATERAL_MODE:
            raise ValueError("The primary experiment must remain ETH-only.")
        if not self.calibration_only or self.runtime_adopted:
            raise ValueError("The event simulator must remain dormant and calibration-only.")


@dataclass(frozen=True)
class ConditionalEventInput:
    """Catalogue-owned event metadata used to prepare a conditional path."""

    event_id: str
    partition: str
    onset_timestamp_utc: pd.Timestamp
    observed_event_duration_hours: int
    initial_peg_gap: float
    eth_recovery_24h: float


@dataclass(frozen=True)
class ConditionalInitialState:
    """Compact canonical initial vault realisation for one replication."""

    event_id: str
    replication: int
    registry_id: str
    vault_seed: int
    starting_eth_price: float
    vault_count: int
    total_debt_dai: float
    debt_dai: tuple[float, ...]
    collateral_ratios: tuple[float, ...]
    liquidation_ratios: tuple[float, ...]
    initial_active_bad_debt_dai: float
    initial_realised_bad_debt_dai: float
    initial_unresolved_tab_dai: float
    initial_trailing_cleared_tab_dai: float
    initial_confidence: float
    initial_stability_counter: int
    collateral_mode: str
    state_checksum: str

    def to_vaults(self) -> list[Vault]:
        """Materialise mutable Vault objects at the event's starting ETH price."""
        return [
            Vault(
                vault_id=index,
                owner_id=index,
                collateral_amount=(
                    debt * collateral_ratio / self.starting_eth_price
                ),
                debt_dai=debt,
                liquidation_ratio=liquidation_ratio,
                collateral_type="ETH",
            )
            for index, (debt, collateral_ratio, liquidation_ratio) in enumerate(
                zip(
                    self.debt_dai,
                    self.collateral_ratios,
                    self.liquidation_ratios,
                    strict=True,
                )
            )
        ]


@dataclass(frozen=True)
class ConditionalEventPath:
    """Observed ETH path and non-future DAI initial condition."""

    event: ConditionalEventInput
    timestamps: tuple[pd.Timestamp, ...]
    observed_eth_prices: tuple[float, ...]
    starting_dai_price: float
    onset_position: int
    minimum_evaluation_end_position: int
    maximum_end_position: int
    observed_dai_values_after_start_used: bool


@dataclass(frozen=True)
class ConditionalEventStep:
    """One auditable step from the calibration-only causal loop."""

    timestamp_utc: pd.Timestamp
    relative_hour: int
    observed_eth_price: float
    dai_price_before: float
    dai_price_after: float
    scaled_lagged_peg_gap: float
    scaled_lagged_eth_downside: float
    confidence: float
    confidence_branch: str
    recovery_counter: int
    recovery_gate_open: bool
    liquidatable_vaults_before: int
    liquidation_attempts: int
    successful_liquidations: int
    failed_liquidation_attempts: int
    cleared_tab_dai: float
    unresolved_tab_dai: float
    trailing_cleared_tab_dai: float
    liquidation_pressure: float
    liquidation_gate_open: bool
    active_bad_debt_dai: float
    material_active_bad_debt: bool
    residual_innovation: float
    panic_component: float
    lower_bound_binding: bool
    upper_bound_binding: bool


@dataclass(frozen=True)
class ConditionalEventMetrics:
    """Event-level metrics exposed to simulated-moment aggregation."""

    event_id: str
    replication: int
    starting_dai_price: float
    initial_peg_gap: float
    eth_recovery_24h: float
    minimum_dai_price: float
    maximum_downside_deviation: float
    maximum_six_hour_burden: float
    first_six_hour_burden: float
    first_24_hour_burden: float
    cumulative_downside_burden: float
    burden_after_first_return: float
    hours_below_0995: int
    hours_to_minimum: int
    hours_to_first_return: int | None
    recovery_completion_hours: int
    recovery_success: bool
    failed_recovery_attempts: int
    post_recovery_overshoot: float
    minimum_confidence: float
    confidence_recovery_time: int | None
    maximum_unresolved_tab_dai: float
    cumulative_cleared_tab_dai: float
    maximum_active_bad_debt_dai: float
    numerical_bound_binding_share: float
    right_censored: bool


@dataclass(frozen=True)
class ConditionalEventDiagnostics:
    """Compact diagnostics that do not expose a production runner."""

    state_checksum: str
    result_checksum: str
    seed_registry_id: str
    vault_seed: int
    market_seed: int
    liquidation_seed: int
    simulated_hours: int
    event_hours: int
    panic_component_nonzero_hours: int
    liquidation_backlog_reconciled: bool
    bad_debt_tolerance_dai: float
    residual_sequence_checksum_verified: bool
    residual_block_checksum_verified: bool
    observed_future_dai_used: bool


@dataclass(frozen=True)
class ConditionalEventResult:
    """One deterministic conditional-event result."""

    event_id: str
    replication: int
    structural_parameters: StructuralParameters
    registry_id: str
    metrics: ConditionalEventMetrics
    diagnostics: ConditionalEventDiagnostics
    steps: tuple[ConditionalEventStep, ...]


@dataclass(frozen=True)
class LiquidationPressureState:
    """Calibration-owned tab-pressure adapter output."""

    unresolved_tab_dai: float
    hourly_cleared_tab_dai: float
    trailing_cleared_tab_dai: float
    pressure: float
    gate_open: bool


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda value: (
            value.isoformat()
            if isinstance(value, pd.Timestamp)
            else value.item()
            if isinstance(value, np.generic)
            else value
        ),
    ).encode("utf-8")


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
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
    _atomic_text(
        path,
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=lambda value: (
                value.isoformat()
                if isinstance(value, pd.Timestamp)
                else value.item()
                if isinstance(value, np.generic)
                else value
            ),
        )
        + "\n",
    )


def derive_common_maximum_horizon(events: pd.DataFrame) -> int:
    """Derive the fixed total horizon from calibration events only."""
    selected = events.loc[events["partition"].eq("calibration")]
    if len(selected) != 74:
        raise ValueError("The common horizon requires exactly 74 calibration events.")
    maximum = int(selected["event_duration_hours"].max())
    return 48 + math.ceil((maximum + 24) / 24) * 24


def default_event_config(events: pd.DataFrame) -> ConditionalEventSimulationConfig:
    """Build the fixed design without inventing Stage 2 defaults."""
    config = ConditionalEventSimulationConfig(
        pre_roll_hours=48,
        post_recovery_hours=24,
        maximum_event_horizon_hours=derive_common_maximum_horizon(events),
        stability_hours=24,
        recovery_band_lower=0.995,
        recovery_band_upper=1.005,
        material_downside_threshold=0.995,
        peg_stress_weight=0.5,
        collateral_stress_weight=0.5,
        stage1_evidence_reference=(
            "data/provenance/calibration/confidence/stage1_market_estimates.json"
        ),
        residual_evidence_reference=(
            "data/provenance/calibration/confidence/stage1_residual_summary.json"
        ),
        initial_state_reference=(
            "data/provenance/calibration/confidence/conditional_initial_state.json"
        ),
        liquidation_pressure_tolerance=1e-9,
        bad_debt_absolute_tolerance=1e-9,
        bad_debt_relative_tolerance=1e-12,
        dai_min_price=0.50,
        dai_max_price=1.50,
        step_hours=1,
        primary_collateral_mode=PRIMARY_COLLATERAL_MODE,
        calibration_only=True,
        runtime_adopted=False,
    )
    config.validate()
    return config


def _manifest_records(manifest_path: Path = CALIBRATION_MANIFEST) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return {record["path"]: record for record in payload["artefacts"]}


def _load_registered_json(path: Path) -> dict[str, Any]:
    relative = path.relative_to(REPOSITORY_ROOT).as_posix()
    record = _manifest_records().get(relative)
    if record is None:
        raise ValueError(f"Calibration evidence is not registered: {relative}.")
    observed = sha256_file(path)
    if observed != record["sha256"]:
        raise ValueError(f"Calibration evidence checksum mismatch: {relative}.")
    return json.loads(path.read_text(encoding="utf-8"))


def load_stage1_owners(
    panel_path: Path = CONFIDENCE_PANEL,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Verify Stage 1, reconstruct residual blocks and return their owners."""
    stage1 = _load_registered_json(evidence_dir / "stage1_market_estimates.json")
    residual_evidence = _load_registered_json(
        evidence_dir / "stage1_residual_summary.json"
    )
    if stage1.get("status") != EXPECTED_STAGE1_STATUS:
        raise ValueError("Stage 1 is not accepted for future SMM.")
    if residual_evidence.get("status") != EXPECTED_STAGE1_STATUS:
        raise ValueError("The residual source is not accepted for future SMM.")
    if stage1.get("runtime_adopted") or residual_evidence.get("runtime_adopted"):
        raise ValueError("Calibration-only Stage 1 evidence is unexpectedly adopted.")
    if stage1.get("input_sha256") != CONFIDENCE_PANEL_SHA256:
        raise ValueError("Stage 1 does not own the canonical market panel.")
    panel = load_confidence_panel(panel_path)
    events = build_event_catalogue(panel)
    hourly = ordinary_confidence_sample(
        panel,
        events,
        daily=False,
        require_lagged_eth=False,
    )
    below = float(stage1["below_peg_response"]["point_estimate"])
    above = float(stage1["above_peg_response"]["point_estimate"])
    source = build_residual_block_source(
        hourly,
        below_peg_response=below,
        above_peg_response=above,
    )
    residual_values_hash = hashlib.sha256(
        np.asarray(source.centred_residuals, dtype="<f8").tobytes()
    ).hexdigest()
    block_hash = hashlib.sha256(
        json.dumps(source.block_indices, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if residual_values_hash != EXPECTED_RESIDUAL_SEQUENCE_SHA256:
        raise ValueError("Reconstructed residual sequence checksum differs.")
    if block_hash != EXPECTED_RESIDUAL_BLOCK_SHA256:
        raise ValueError("Reconstructed residual block checksum differs.")
    if (
        residual_evidence["centred_residual_sequence_sha256"] != residual_values_hash
        or residual_evidence["block_index_specification_sha256"] != block_hash
    ):
        raise ValueError("Residual evidence does not match its reconstruction.")
    return panel, events, {
        "below_peg_response": below,
        "above_peg_response": above,
        "source": source,
        "residual_sequence_sha256": residual_values_hash,
        "block_specification_sha256": block_hash,
        "stage1": stage1,
    }


def _eth_only_portfolio(initial_eth_price: float) -> CollateralPortfolioConfig:
    return CollateralPortfolioConfig(
        name="conditional_event_eth_core",
        collaterals=(
            CollateralConfig(
                name="ETH",
                initial_price=float(initial_eth_price),
                liquidation_ratio=None,
                liquidation_penalty=None,
                target_debt_share=1.0,
            ),
        ),
    )


def build_conditional_initial_state(
    *,
    event_id: str,
    replication: int,
    registry_id: str,
    initial_eth_price: float,
    profile_path: Path = DEFAULT_TRANCHE_B_CONFIG_PATH,
) -> ConditionalInitialState:
    """Sample the reviewed ETH vault distribution under fixed normalisation."""
    if initial_eth_price <= 0.0:
        raise ValueError("initial_eth_price must be positive.")
    bundle = load_tranche_b_configuration(profile_path)
    seed = derive_seed(
        registry_id=registry_id,
        event_id=event_id,
        replication=replication,
        stream_name="vault_sampling",
    )
    simulation = replace(
        bundle.base_bundle.simulation_config,
        initial_eth_price=float(initial_eth_price),
        collateral_portfolio=_eth_only_portfolio(initial_eth_price),
        random_seed=seed,
    )
    initialisation = replace(bundle.initialisation, seed=seed)
    generated = initialise_vaults(simulation, initialisation)
    if len(generated.vaults) != simulation.n_vaults:
        raise ValueError("Initialiser did not reproduce the configured vault count.")
    raw_total = sum(vault.debt_dai for vault in generated.vaults)
    target_total = float(simulation.n_vaults * simulation.debt_mean)
    if raw_total <= 0.0:
        raise ValueError("Sampled vault debt must be positive.")
    normalisation = target_total / raw_total
    debts = tuple(float(vault.debt_dai * normalisation) for vault in generated.vaults)
    ratios = tuple(
        float(vault.collateral_ratio(initial_eth_price))
        for vault in generated.vaults
    )
    liquidation_ratios = tuple(
        float(vault.liquidation_ratio) for vault in generated.vaults
    )
    if any(
        debt <= 0.0 or ratio <= liquidation_ratio
        for debt, ratio, liquidation_ratio in zip(
            debts, ratios, liquidation_ratios, strict=True
        )
    ):
        raise ValueError("Conditional initial state contains an invalid vault.")
    payload = {
        "collateral_mode": PRIMARY_COLLATERAL_MODE,
        "debt_dai": debts,
        "collateral_ratios": ratios,
        "liquidation_ratios": liquidation_ratios,
        "normalised_total_debt_dai": target_total,
        "vault_count": simulation.n_vaults,
    }
    return ConditionalInitialState(
        event_id=event_id,
        replication=replication,
        registry_id=registry_id,
        vault_seed=seed,
        starting_eth_price=float(initial_eth_price),
        vault_count=simulation.n_vaults,
        total_debt_dai=target_total,
        debt_dai=debts,
        collateral_ratios=ratios,
        liquidation_ratios=liquidation_ratios,
        initial_active_bad_debt_dai=0.0,
        initial_realised_bad_debt_dai=0.0,
        initial_unresolved_tab_dai=0.0,
        initial_trailing_cleared_tab_dai=0.0,
        initial_confidence=1.0,
        initial_stability_counter=0,
        collateral_mode=PRIMARY_COLLATERAL_MODE,
        state_checksum=_payload_sha256(payload),
    )


def initial_state_summary(state: ConditionalInitialState) -> dict[str, Any]:
    """Return compact, non-row-level diagnostics for one state realisation."""
    debts = np.asarray(state.debt_dai, dtype=float)
    ratios = np.asarray(state.collateral_ratios, dtype=float)
    liquidation_ratios = np.asarray(state.liquidation_ratios, dtype=float)
    weights = debts / debts.sum()
    collateral_value = float(np.sum(debts * ratios))
    return {
        "vault_count": state.vault_count,
        "total_debt_dai": float(debts.sum()),
        "total_collateral_value_usd": collateral_value,
        "system_collateral_ratio": collateral_value / debts.sum(),
        "collateral_ratio": {
            "minimum": float(ratios.min()),
            "median": float(np.median(ratios)),
            "maximum": float(ratios.max()),
        },
        "liquidation_ratio": {
            "minimum": float(liquidation_ratios.min()),
            "median": float(np.median(liquidation_ratios)),
            "maximum": float(liquidation_ratios.max()),
        },
        "debt_weight": {
            "minimum": float(weights.min()),
            "median": float(np.median(weights)),
            "maximum": float(weights.max()),
            "herfindahl_index": float(np.sum(weights**2)),
        },
        "initially_liquidatable_vault_count": int(
            np.count_nonzero(ratios < liquidation_ratios)
        ),
        "state_checksum": state.state_checksum,
    }


def prepare_event_path(
    *,
    panel: pd.DataFrame,
    event_row: pd.Series,
    config: ConditionalEventSimulationConfig,
) -> ConditionalEventPath:
    """Prepare complete observed ETH ownership without future DAI inputs."""
    if str(event_row["partition"]) != "calibration":
        raise ValueError("Only calibration events may enter the event simulator.")
    onset = pd.Timestamp(event_row["onset_timestamp_utc"])
    if onset.tzinfo is None:
        onset = onset.tz_localize("UTC")
    else:
        onset = onset.tz_convert("UTC")
    start = onset - pd.Timedelta(hours=config.pre_roll_hours)
    post_onset_hours = config.maximum_event_horizon_hours - config.pre_roll_hours
    end = onset + pd.Timedelta(hours=post_onset_hours - 1)
    expected = pd.date_range(start, end, freq="h")
    selected = panel.reindex(expected)
    if len(selected) != config.maximum_event_horizon_hours:
        raise ValueError("Conditional path length does not equal the common horizon.")
    if selected["eth_price_usd"].isna().any():
        raise ValueError("An event lacks its complete observed ETH path or pre-roll.")
    observed_duration = int(event_row["event_duration_hours"])
    minimum_end = min(
        config.maximum_event_horizon_hours - 1,
        config.pre_roll_hours + observed_duration + config.post_recovery_hours,
    )
    event = ConditionalEventInput(
        event_id=str(event_row["event_id"]),
        partition="calibration",
        onset_timestamp_utc=onset,
        observed_event_duration_hours=observed_duration,
        initial_peg_gap=float(event_row["initial_peg_gap"]),
        eth_recovery_24h=float(event_row["eth_recovery_24h"]),
    )
    return ConditionalEventPath(
        event=event,
        timestamps=tuple(expected),
        observed_eth_prices=tuple(
            selected["eth_price_usd"].to_numpy(dtype=float)
        ),
        starting_dai_price=float(selected["dai_price_usd"].iloc[0]),
        onset_position=config.pre_roll_hours,
        minimum_evaluation_end_position=minimum_end,
        maximum_end_position=config.maximum_event_horizon_hours - 1,
        observed_dai_values_after_start_used=False,
    )


def liquidation_pressure_state(
    *,
    unresolved_tab_dai: float,
    hourly_cleared_tab_dai: float,
    cleared_history: Sequence[float],
    tolerance: float,
    epsilon: float = 1e-12,
) -> LiquidationPressureState:
    """Adapt liquidation tab outputs to the pre-registered recovery gate."""
    values = (
        unresolved_tab_dai,
        hourly_cleared_tab_dai,
        tolerance,
        epsilon,
    )
    if not all(math.isfinite(value) and value >= 0.0 for value in values):
        raise ValueError("Liquidation tab values and tolerances must be non-negative.")
    trailing = float(sum(cleared_history))
    if unresolved_tab_dai <= tolerance:
        pressure = 0.0
    else:
        pressure = unresolved_tab_dai / (
            unresolved_tab_dai + trailing + epsilon
        )
    return LiquidationPressureState(
        unresolved_tab_dai=float(unresolved_tab_dai),
        hourly_cleared_tab_dai=float(hourly_cleared_tab_dai),
        trailing_cleared_tab_dai=trailing,
        pressure=float(pressure),
        gate_open=bool(unresolved_tab_dai <= tolerance),
    )


def material_bad_debt_tolerance(
    initial_debt_dai: float,
    config: ConditionalEventSimulationConfig,
) -> float:
    """Return numerical dust tolerance, not an estimated severity threshold."""
    if initial_debt_dai <= 0.0:
        raise ValueError("Initial debt must be positive.")
    return max(
        config.bad_debt_absolute_tolerance,
        config.bad_debt_relative_tolerance * initial_debt_dai,
    )


def material_active_bad_debt(
    active_bad_debt_dai: float,
    *,
    tolerance: float,
) -> bool:
    """Return whether economically material active bad debt blocks recovery."""
    if (
        not math.isfinite(active_bad_debt_dai)
        or active_bad_debt_dai < 0.0
        or tolerance < 0.0
    ):
        raise ValueError("Bad debt and its tolerance must be finite and non-negative.")
    return bool(active_bad_debt_dai > tolerance)


def bad_debt_sensitivity_flags(
    active_bad_debt_dai: float,
    initial_debt_dai: float,
) -> dict[str, bool]:
    """Return diagnostic-only 0.1% and 1% active-debt flags."""
    if initial_debt_dai <= 0.0:
        raise ValueError("Initial debt must be positive.")
    ratio = active_bad_debt_dai / initial_debt_dai
    return {
        "active_bad_debt_ratio_above_0_1pct": bool(ratio > 0.001),
        "active_bad_debt_ratio_above_1pct": bool(ratio > 0.01),
    }


def _liquidation_demand_config(
    profile_path: Path,
    *,
    seed: int,
) -> LiquidationDemandConfig:
    payload = load_configuration_payload(profile_path, ())
    raw = payload["liquidation_demand"]
    pool_path = (
        None
        if raw.get("pool_path") is None
        else REPOSITORY_ROOT / str(raw["pool_path"])
    )
    return LiquidationDemandConfig(
        mode=str(raw["mode"]),
        pool_path=pool_path,
        pool_sha256=raw.get("pool_sha256"),
        seed=seed,
        hurdle_probability=(
            None
            if raw.get("hurdle_probability") is None
            else float(raw["hurdle_probability"])
        ),
        hurdle_estimator=str(raw["hurdle_estimator"]),
        positive_count_mode=str(raw["positive_count_mode"]),
        sequence_mode=str(raw["sequence_mode"]),
        inventory_conditioning=str(raw["inventory_conditioning"]),
        count_truncation_policy=str(raw["count_truncation_policy"]),
    )


def _active_system(vaults: Sequence[Vault], eth_price: float) -> tuple[int, float, float]:
    active = [vault for vault in vaults if vault.is_active]
    liquidatable = [vault for vault in active if vault.is_liquidatable(eth_price)]
    unresolved = float(sum(vault.debt_dai for vault in liquidatable))
    bad_debt = float(sum(vault.bad_debt(eth_price) for vault in active))
    return len(liquidatable), unresolved, bad_debt


def _event_metrics(
    *,
    path: ConditionalEventPath,
    event_steps: Sequence[ConditionalEventStep],
    replication: int,
    config: ConditionalEventSimulationConfig,
    recovery_success: bool,
) -> ConditionalEventMetrics:
    prices = np.asarray([step.dai_price_after for step in event_steps], dtype=float)
    confidences = np.asarray([step.confidence for step in event_steps], dtype=float)
    severity = np.minimum(
        1.0,
        np.maximum(0.0, config.material_downside_threshold - prices) / 0.005,
    )
    minimum_position = int(np.argmin(prices))
    return_positions = np.flatnonzero(prices >= config.material_downside_threshold)
    first_return = int(return_positions[0]) if len(return_positions) else None
    rolling = pd.Series(severity).rolling(6, min_periods=1).mean()
    recovery_attempts = 0
    current = 0
    for price in prices:
        if config.recovery_band_lower <= price <= config.recovery_band_upper:
            current += 1
        elif current:
            if current < config.stability_hours:
                recovery_attempts += 1
            current = 0
    completion = len(event_steps) - 1
    recovery_position = len(event_steps) - 1 if recovery_success else None
    confidence_recovery = next(
        (
            index
            for index, value in enumerate(confidences)
            if index > int(np.argmin(confidences))
            and value >= 1.0 - 1e-12
        ),
        None,
    )
    overshoot = (
        float(np.maximum(prices[recovery_position + 1 :] - 1.0, 0.0).max())
        if recovery_position is not None and recovery_position + 1 < len(prices)
        else 0.0
    )
    bound_count = sum(
        step.lower_bound_binding or step.upper_bound_binding for step in event_steps
    )
    burden_after = (
        float(severity[first_return:].sum())
        if first_return is not None
        else float(severity.sum())
    )
    return ConditionalEventMetrics(
        event_id=path.event.event_id,
        replication=replication,
        starting_dai_price=path.starting_dai_price,
        initial_peg_gap=path.event.initial_peg_gap,
        eth_recovery_24h=path.event.eth_recovery_24h,
        minimum_dai_price=float(prices[minimum_position]),
        maximum_downside_deviation=float(
            max(0.0, config.material_downside_threshold - prices[minimum_position])
        ),
        maximum_six_hour_burden=float(rolling.max()),
        first_six_hour_burden=float(severity[:6].mean()),
        first_24_hour_burden=float(severity[:24].mean()),
        cumulative_downside_burden=float(severity.sum()),
        burden_after_first_return=burden_after,
        hours_below_0995=int(np.count_nonzero(prices < 0.995)),
        hours_to_minimum=minimum_position,
        hours_to_first_return=first_return,
        recovery_completion_hours=(
            int(recovery_position)
            if recovery_position is not None
            else completion
        ),
        recovery_success=recovery_success,
        failed_recovery_attempts=recovery_attempts,
        post_recovery_overshoot=overshoot,
        minimum_confidence=float(confidences.min()),
        confidence_recovery_time=confidence_recovery,
        maximum_unresolved_tab_dai=float(
            max(step.unresolved_tab_dai for step in event_steps)
        ),
        cumulative_cleared_tab_dai=float(
            sum(step.cleared_tab_dai for step in event_steps)
        ),
        maximum_active_bad_debt_dai=float(
            max(step.active_bad_debt_dai for step in event_steps)
        ),
        numerical_bound_binding_share=float(bound_count / len(event_steps)),
        right_censored=not recovery_success,
    )


def simulate_conditional_event(
    *,
    path: ConditionalEventPath,
    config: ConditionalEventSimulationConfig,
    structural_parameters: StructuralParameters,
    replication: int,
    registry_id: str,
    stage1_owners: Mapping[str, Any],
    profile_path: Path = DEFAULT_TRANCHE_B_CONFIG_PATH,
) -> ConditionalEventResult:
    """Run one dormant, causal conditional-event experiment."""
    config.validate()
    validate_structural_parameters(structural_parameters)
    if path.observed_dai_values_after_start_used:
        raise ValueError("Observed future DAI must not enter the event simulator.")
    initial = build_conditional_initial_state(
        event_id=path.event.event_id,
        replication=replication,
        registry_id=registry_id,
        initial_eth_price=path.observed_eth_prices[0],
        profile_path=profile_path,
    )
    vaults = initial.to_vaults()
    bundle = load_tranche_b_configuration(profile_path)
    liquidation_config = bundle.base_bundle.liquidation_config
    market_seed = derive_seed(
        registry_id=registry_id,
        event_id=path.event.event_id,
        replication=replication,
        stream_name="market_innovations",
    )
    liquidation_seed = derive_seed(
        registry_id=registry_id,
        event_id=path.event.event_id,
        replication=replication,
        stream_name="liquidation_randomness",
    )
    demand = LiquidationDemandProcess(
        _liquidation_demand_config(profile_path, seed=liquidation_seed)
    )
    rng = np.random.default_rng(market_seed)
    block_count = math.ceil(len(path.timestamps) / 24)
    innovations = sample_residual_blocks(
        stage1_owners["source"],
        block_count=block_count,
        rng=rng,
    )[: len(path.timestamps)]
    scaling = _load_registered_json(SPARSE_SCALING_EVIDENCE)
    peg_scale = float(scaling["lagged_below_peg_gap"]["positive_q95"])
    eth_scale = float(scaling["lagged_24h_eth_downside"]["positive_q95"])
    confidence_config = PersistentConfidenceConfig(
        deterioration_adjustment=structural_parameters.deterioration_adjustment,
        recovery_adjustment=structural_parameters.recovery_adjustment,
        confidence_floor=structural_parameters.confidence_floor,
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
    cleared_history: deque[float] = deque(maxlen=24)
    eth_returns: deque[float] = deque(maxlen=24)
    steps: list[ConditionalEventStep] = []
    recovery_success = False
    bad_debt_tolerance = material_bad_debt_tolerance(
        initial.total_debt_dai, config
    )
    previous_eth = path.observed_eth_prices[0]
    for position, (timestamp, eth_price, innovation) in enumerate(
        zip(
            path.timestamps,
            path.observed_eth_prices,
            innovations,
            strict=True,
        )
    ):
        if position:
            eth_returns.append(math.log(eth_price) - math.log(previous_eth))
        previous_eth = eth_price
        lagged_downside = max(0.0, -sum(eth_returns)) if len(eth_returns) == 24 else 0.0
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
        market = coefficient_normalised_market_response(
            dai_price=dai_price,
            confidence=confidence_state.confidence,
            below_peg_response=float(stage1_owners["below_peg_response"]),
            above_peg_response=float(stage1_owners["above_peg_response"]),
            panic_response=structural_parameters.panic_response,
            residual_innovation=float(innovation),
            min_price=config.dai_min_price,
            max_price=config.dai_max_price,
        )
        dai_before = dai_price
        dai_price = market.clipped_next_price
        liquidatable_before, _, _ = _active_system(vaults, eth_price)
        decision = demand.sample_step(
            step=position,
            liquidatable_inventory=liquidatable_before,
            keeper_capacity=liquidation_config.max_liquidations_per_step,
        )
        if liquidatable_before:
            liquidation_frame = liquidate_vaults(
                vaults,
                eth_price,
                liquidation_config,
                bounded_demand=decision.bounded_demand,
                attempt_budget=decision.attempt_budget,
            )
            liquidation_summary = summarise_liquidations(liquidation_frame)
        else:
            liquidation_summary = {
                "n_attempted": 0,
                "n_liquidated": 0,
                "n_unprofitable": 0,
                "debt_repaid": 0.0,
            }
        _, unresolved, active_bad_debt = _active_system(vaults, eth_price)
        cleared = float(liquidation_summary["debt_repaid"])
        cleared_history.append(cleared)
        pressure = liquidation_pressure_state(
            unresolved_tab_dai=unresolved,
            hourly_cleared_tab_dai=cleared,
            cleared_history=tuple(cleared_history),
            tolerance=config.liquidation_pressure_tolerance,
        )
        material_bad_debt = material_active_bad_debt(
            active_bad_debt, tolerance=bad_debt_tolerance
        )
        gate_inputs = RecoveryGateInputs(
            price_inside_recovery_band=(
                config.recovery_band_lower
                <= dai_price
                <= config.recovery_band_upper
            ),
            liquidation_pressure_acceptable=pressure.gate_open,
            severe_bad_debt_present=material_bad_debt,
        )
        steps.append(
            ConditionalEventStep(
                timestamp_utc=timestamp,
                relative_hour=position - path.onset_position,
                observed_eth_price=float(eth_price),
                dai_price_before=float(dai_before),
                dai_price_after=float(dai_price),
                scaled_lagged_peg_gap=float(scaled_peg),
                scaled_lagged_eth_downside=float(scaled_eth),
                confidence=float(confidence_state.confidence),
                confidence_branch=confidence_update.branch,
                recovery_counter=int(confidence_state.consecutive_stable_hours),
                recovery_gate_open=bool(confidence_state.recovery_gate_open),
                liquidatable_vaults_before=liquidatable_before,
                liquidation_attempts=int(liquidation_summary["n_attempted"]),
                successful_liquidations=int(liquidation_summary["n_liquidated"]),
                failed_liquidation_attempts=int(
                    liquidation_summary["n_unprofitable"]
                ),
                cleared_tab_dai=cleared,
                unresolved_tab_dai=unresolved,
                trailing_cleared_tab_dai=pressure.trailing_cleared_tab_dai,
                liquidation_pressure=pressure.pressure,
                liquidation_gate_open=pressure.gate_open,
                active_bad_debt_dai=active_bad_debt,
                material_active_bad_debt=material_bad_debt,
                residual_innovation=float(innovation),
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
            and pressure.gate_open
            and not material_bad_debt
        ):
            recovery_success = True
            break

    event_steps = tuple(steps[path.onset_position :])
    if not event_steps:
        raise ValueError("No event-period steps were simulated.")
    metrics = _event_metrics(
        path=path,
        event_steps=event_steps,
        replication=replication,
        config=config,
        recovery_success=recovery_success,
    )
    result_payload = {
        "event_id": path.event.event_id,
        "replication": replication,
        "registry_id": registry_id,
        "structural_parameters": asdict(structural_parameters),
        "metrics": asdict(metrics),
        "state_checksum": initial.state_checksum,
        "market_seed": market_seed,
        "liquidation_seed": liquidation_seed,
    }
    result_checksum = _payload_sha256(result_payload)
    diagnostics = ConditionalEventDiagnostics(
        state_checksum=initial.state_checksum,
        result_checksum=result_checksum,
        seed_registry_id=registry_id,
        vault_seed=initial.vault_seed,
        market_seed=market_seed,
        liquidation_seed=liquidation_seed,
        simulated_hours=len(steps),
        event_hours=len(event_steps),
        panic_component_nonzero_hours=sum(
            abs(step.panic_component) > 0.0 for step in steps
        ),
        liquidation_backlog_reconciled=all(
            step.unresolved_tab_dai >= 0.0
            and step.cleared_tab_dai >= 0.0
            for step in steps
        ),
        bad_debt_tolerance_dai=bad_debt_tolerance,
        residual_sequence_checksum_verified=(
            stage1_owners["residual_sequence_sha256"]
            == EXPECTED_RESIDUAL_SEQUENCE_SHA256
        ),
        residual_block_checksum_verified=(
            stage1_owners["block_specification_sha256"]
            == EXPECTED_RESIDUAL_BLOCK_SHA256
        ),
        observed_future_dai_used=False,
    )
    return ConditionalEventResult(
        event_id=path.event.event_id,
        replication=replication,
        structural_parameters=structural_parameters,
        registry_id=registry_id,
        metrics=metrics,
        diagnostics=diagnostics,
        steps=tuple(steps),
    )


def deterministic_probe_vectors(
    *,
    probe_indices: Sequence[int] = PROBE_INDICES,
    seed: int = 20_260_729,
) -> list[dict[str, Any]]:
    """Return three Sobol and two explicit boundary interface probes."""
    _, candidates = sobol_candidates(seed=seed)
    specification = _load_registered_json(
        CONFIDENCE_EVIDENCE / "simulated_moments_specification.json"
    )
    expected = specification["sobol_design"]["structural_candidate_sha256"]
    probes: list[dict[str, Any]] = []
    for index in probe_indices:
        if index not in PROBE_INDICES:
            raise ValueError("Only pre-registered probe indices 0, 127 and 255 are allowed.")
        probes.append(
            {
                "probe_id": f"sobol_{index}",
                "candidate_index": int(index),
                "structural_parameters": candidates[index],
                "source_sobol_checksum": expected,
                "boundary_status": "interior",
            }
        )
    base = candidates[127]
    probes.extend(
        [
            {
                "probe_id": "boundary_panic_response_zero",
                "candidate_index": None,
                "structural_parameters": replace(base, panic_response=0.0),
                "source_sobol_checksum": expected,
                "boundary_status": "kappa_P=0",
            },
            {
                "probe_id": "boundary_confidence_floor_zero",
                "candidate_index": None,
                "structural_parameters": replace(base, confidence_floor=0.0),
                "source_sobol_checksum": expected,
                "boundary_status": "C_min=0",
            },
        ]
    )
    return probes


def validate_final_event_input(
    panel: pd.DataFrame,
    events: pd.DataFrame,
    config: ConditionalEventSimulationConfig,
) -> dict[str, Any]:
    """Validate final-event parsing and ETH path completeness without simulation."""
    selected = events.loc[events["partition"].eq("final_stress_validation")]
    if len(selected) != 1:
        raise ValueError("Exactly one final-stress event must remain untouched.")
    row = selected.iloc[0]
    onset = pd.Timestamp(row["onset_timestamp_utc"])
    start = onset - pd.Timedelta(hours=config.pre_roll_hours)
    end = onset + pd.Timedelta(
        hours=config.maximum_event_horizon_hours - config.pre_roll_hours - 1
    )
    expected = pd.date_range(start, end, freq="h")
    values = panel.reindex(expected)["eth_price_usd"]
    return {
        "event_id": str(row["event_id"]),
        "parsed": True,
        "eth_path_complete": bool(values.notna().all()),
        "simulated": False,
        "used_for_design": False,
    }


def _event_row(events: pd.DataFrame, event_id: str) -> pd.Series:
    selected = events.loc[events["event_id"].eq(event_id)]
    if len(selected) != 1:
        raise ValueError(f"Event identifier is not unique: {event_id}.")
    return selected.iloc[0]


def _diagnostic_step_frame(result: ConditionalEventResult) -> pd.DataFrame:
    return pd.DataFrame([asdict(step) for step in result.steps])


def _write_diagnostics(
    directory: Path,
    results: Sequence[ConditionalEventResult],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    metric_rows = [
        {
            **asdict(result.metrics),
            "structural_vector_sha256": _payload_sha256(
                asdict(result.structural_parameters)
            ),
        }
        for result in results
    ]
    _atomic_text(
        directory / "event_metrics.csv",
        pd.DataFrame(metric_rows).to_csv(index=False, lineterminator="\n"),
    )
    for result in results:
        structural_digest = _payload_sha256(
            asdict(result.structural_parameters)
        )
        _atomic_text(
            directory
            / (
                f"{result.event_id}__r{result.replication:02d}"
                f"__p{structural_digest[:12]}__trajectory.csv"
            ),
            _diagnostic_step_frame(result).to_csv(index=False, lineterminator="\n"),
        )


def _manifest_record(path: Path, *, semantic_name: str, context: str) -> dict[str, Any]:
    return {
        "semantic_name": semantic_name,
        "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
        "producer": "dai_sim.calibration.event_simulation",
        "source_inputs": [
            "data/market/processed/dune_hourly_dai_eth_market_prices_processed.csv",
            "data/provenance/calibration/confidence/event_catalogue.csv",
        ],
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "schema": "Compact JSON calibration evidence; no hourly trajectory.",
        "context": context,
        "classification": "snapshot",
    }


def register_event_evidence(
    evidence_dir: Path,
    manifest_path: Path = CALIBRATION_MANIFEST,
) -> None:
    """Register the five compact event evidence artefacts deterministically."""
    names = {
        "conditional_event_specification.json": (
            "confidence_conditional_event_specification",
            "Conditional, non-exact historical experiment; not runtime adopted.",
        ),
        "conditional_initial_state.json": (
            "confidence_conditional_initial_state",
            "Compact standardised ETH-core state normalisation and checksum.",
        ),
        "recovery_gate_specification.json": (
            "confidence_recovery_gate_specification",
            "Zero-backlog and material-active-bad-debt recovery gates.",
        ),
        "event_simulation_smoke.json": (
            "confidence_event_simulation_smoke",
            "Interface probes only; no Stage 2 ranking, selection or fit.",
        ),
        "event_simulation_benchmark.json": (
            "confidence_event_simulation_benchmark",
            "Bounded observed timing and linear workload extrapolations only.",
        ),
    }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = {
        f"data/provenance/calibration/confidence/{name}"
        for name in names
    }
    manifest["artefacts"] = [
        record for record in manifest["artefacts"] if record["path"] not in paths
    ]
    for name, (semantic, context) in names.items():
        manifest["artefacts"].append(
            _manifest_record(
                evidence_dir / name,
                semantic_name=semantic,
                context=context,
            )
        )
    _atomic_json(manifest_path, manifest)


def _workload_estimates(
    *,
    seconds_per_run: float,
) -> list[dict[str, Any]]:
    specifications = [
        ("sobol_search", 32 * 32 * 256),
        ("bounded_candidate_follow_up", 74 * 32 * 16),
        ("four_powell_refinements_at_cap", 4 * 256),
        ("finalists_two_registries", 74 * 64 * 5 * 2),
    ]
    return [
        {
            "workload": name,
            "event_replication_runs": count,
            "linear_seconds": count * seconds_per_run,
            "executed": False,
        }
        for name, count in specifications
    ]


def run_event_simulation_evidence(
    *,
    panel_path: Path = CONFIDENCE_PANEL,
    source_evidence_dir: Path = CONFIDENCE_EVIDENCE,
    evidence_dir: Path = CONFIDENCE_EVIDENCE,
    diagnostics_dir: Path = DEFAULT_EVENT_DIAGNOSTICS,
    registry_id: str = DEFAULT_REGISTRY_IDS[0],
    probe_indices: Sequence[int] = PROBE_INDICES,
    action: str = "all",
    register_manifest: bool = True,
) -> dict[str, Any]:
    """Run bounded validation, smoke and benchmark operations only."""
    if action not in {"validate", "initial-state", "gates", "smoke", "benchmark", "all"}:
        raise ValueError(f"Unsupported event-simulation action: {action}.")
    panel, events, stage1 = load_stage1_owners(panel_path, source_evidence_dir)
    config = default_event_config(events)
    smoke_ids = select_event_smoke_subset(events)
    validation_boundary = validate_final_event_input(panel, events, config)
    paths = {
        event_id: prepare_event_path(
            panel=panel,
            event_row=_event_row(events, event_id),
            config=config,
        )
        for event_id in smoke_ids
    }
    reference_state = build_conditional_initial_state(
        event_id=smoke_ids[0],
        replication=0,
        registry_id=registry_id,
        initial_eth_price=paths[smoke_ids[0]].observed_eth_prices[0],
    )
    state_summary = initial_state_summary(reference_state)
    bundle = load_tranche_b_configuration(DEFAULT_TRANCHE_B_CONFIG_PATH)
    profile = load_configuration_payload(DEFAULT_TRANCHE_B_CONFIG_PATH, ())
    state_evidence = {
        "schema_version": 1,
        "status": "validated_standardised_conditional_state",
        "runtime_adopted": False,
        "interpretation": "Standardised ETH-core calibration state, not historical Maker state.",
        "configuration_owner": "config/profiles/empirical.yaml",
        "configuration_sha256": sha256_file(DEFAULT_TRANCHE_B_CONFIG_PATH),
        "vault_evidence_owner": "data/vaults/model_inputs/initialisation/pool.csv",
        "vault_evidence_sha256": bundle.initialisation.pool_sha256,
        "normalisation": {
            "vault_count": bundle.base_bundle.simulation_config.n_vaults,
            "total_debt_rule": "n_vaults multiplied by configured debt_mean",
            "total_debt_dai": (
                bundle.base_bundle.simulation_config.n_vaults
                * bundle.base_bundle.simulation_config.debt_mean
            ),
            "debt_weights": "reviewed normal-regime ETH empirical joint sample",
            "collateral_ratios": "reviewed normal-regime ETH empirical joint sample",
            "collateral_amount": "debt * collateral_ratio / event pre-roll-start ETH price",
        },
        "state_summary": state_summary,
        "protocol_and_liquidation": {
            "liquidation_penalty": bundle.base_bundle.liquidation_config.liquidation_penalty,
            "max_close_factor": bundle.base_bundle.liquidation_config.max_close_factor,
            "keeper_capacity": bundle.base_bundle.liquidation_config.max_liquidations_per_step,
            "gas_treatment": (
                f"fixed {bundle.base_bundle.liquidation_config.gas_cost} DAI "
                "per attempted liquidation from the empirical profile liquidation section"
            ),
            "stability_fee_treatment": "not accrued by the established short-horizon Vault mechanics",
            "oracle_market_relationship": "equal; empirical profile oracle_delay_steps = 0",
        },
        "initial_conditions": {
            "active_bad_debt_dai": 0.0,
            "realised_bad_debt_dai": 0.0,
            "unresolved_tab_dai": 0.0,
            "trailing_24h_cleared_tab_dai": 0.0,
            "confidence": 1.0,
            "stability_counter": 0,
        },
        "event_invariant_fields": [
            "vault_count",
            "total_initial_debt",
            "sampling distribution",
            "protocol and liquidation settings",
            "keeper capacity rule",
            "gas treatment",
            "ETH-only collateral mode",
            "initial bad debt and backlog",
            "initial confidence",
        ],
        "event_varying_fields": [
            "observed starting DAI price",
            "observed ETH path",
            "evaluation horizon",
            "seed-registry-owned vault realisation",
        ],
        "complete_vault_rows_tracked": False,
    }
    gate_evidence = {
        "schema_version": 1,
        "status": "operational",
        "runtime_adopted": False,
        "recovery_band": [config.recovery_band_lower, config.recovery_band_upper],
        "stability_hours": config.stability_hours,
        "liquidation_pressure": {
            "formula": "U / (U + C24 + epsilon)",
            "unresolved_tab_owner": "remaining debt of active liquidatable vaults after current-hour action",
            "cleared_tab_owner": "Liquidation summary debt_repaid",
            "primary_rule": "U equals zero within tolerance",
            "tolerance_dai": config.liquidation_pressure_tolerance,
            "liquidatable_share_substituted": False,
        },
        "material_active_bad_debt": {
            "primary_rule": "active bad debt greater than numerical tolerance blocks recovery",
            "tolerance_formula": "max(1e-9, 1e-12 * initial system debt) DAI",
            "reference_tolerance_dai": material_bad_debt_tolerance(
                reference_state.total_debt_dai, config
            ),
            "diagnostic_sensitivities": [0.001, 0.01],
            "sensitivities_used_by_primary_gate": False,
        },
        "fitted_recovery_gate_coefficient": None,
    }
    specification = {
        "schema_version": 1,
        "status": "implemented_conditional_non_exact_replay",
        "runtime_adopted": False,
        "calibration_only": True,
        "interpretation": (
            "Observed ETH conditional experiment with one observed DAI initial "
            "condition; not an exact historical Maker replay."
        ),
        "event_path_ownership": {
            "eth": "observed canonical hourly path",
            "dai": "observed at pre-roll start only; simulated thereafter",
        },
        "pre_roll_hours": config.pre_roll_hours,
        "post_recovery_hours": config.post_recovery_hours,
        "common_maximum_horizon_hours": config.maximum_event_horizon_hours,
        "longest_calibration_event_hours": int(
            events.loc[
                events["partition"].eq("calibration"),
                "event_duration_hours",
            ].max()
        ),
        "stage1_evidence_reference": config.stage1_evidence_reference,
        "residual_evidence_reference": config.residual_evidence_reference,
        "initial_state_reference": config.initial_state_reference,
        "residual_sequence_sha256": stage1["residual_sequence_sha256"],
        "residual_block_specification_sha256": stage1["block_specification_sha256"],
        "primary_collateral_mode": config.primary_collateral_mode,
        "within_hour_ordering": [
            "read lagged DAI and observed ETH history",
            "scale lagged peg gap and 24-hour ETH downside",
            "update persistent confidence from prior-hour gates",
            "apply accepted Stage 1 response and current residual innovation",
            "value vaults at current observed ETH",
            "sample existing liquidation demand and run existing liquidation logic",
            "reconcile cleared tab, unresolved tab and active bad debt",
            "set recovery inputs for the next hour",
            "record conditional metrics",
        ],
        "stage2_parameter_defaults": None,
        "final_validation_boundary": validation_boundary,
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(evidence_dir / "conditional_event_specification.json", specification)
    _atomic_json(evidence_dir / "conditional_initial_state.json", state_evidence)
    _atomic_json(evidence_dir / "recovery_gate_specification.json", gate_evidence)
    if action in {"validate", "initial-state", "gates"}:
        return {
            "action": action,
            "config": asdict(config),
            "smoke_event_ids": smoke_ids,
            "validation_boundary": validation_boundary,
            "state_checksum": reference_state.state_checksum,
        }

    probes = deterministic_probe_vectors(probe_indices=probe_indices)
    smoke_results: list[ConditionalEventResult] = []
    for event_id in smoke_ids:
        for probe in probes:
            smoke_results.append(
                simulate_conditional_event(
                    path=paths[event_id],
                    config=config,
                    structural_parameters=probe["structural_parameters"],
                    replication=0,
                    registry_id=registry_id,
                    stage1_owners=stage1,
                )
            )
    seed_difference = [
        simulate_conditional_event(
            path=paths[smoke_ids[0]],
            config=config,
            structural_parameters=probes[1]["structural_parameters"],
            replication=replication,
            registry_id=registry_id,
            stage1_owners=stage1,
        )
        for replication in (0, 1)
    ]
    if (
        seed_difference[0].diagnostics.result_checksum
        == seed_difference[1].diagnostics.result_checksum
    ):
        raise ValueError("Distinct replications did not change the event result.")
    probe_lookup = {
        _payload_sha256(asdict(probe["structural_parameters"])): probe["probe_id"]
        for probe in probes
    }
    smoke_evidence = {
        "schema_version": 1,
        "status": "passed",
        "runtime_adopted": False,
        "purpose": "Interface smoke only; no fit comparison.",
        "event_ids": smoke_ids,
        "event_selection": "one lowest-content-hash event per first-six-hour-burden quartile",
        "probe_vectors": [
            {
                "probe_id": probe["probe_id"],
                "candidate_index": probe["candidate_index"],
                "structural_vector": asdict(probe["structural_parameters"]),
                "source_sobol_checksum": probe["source_sobol_checksum"],
                "boundary_status": probe["boundary_status"],
            }
            for probe in probes
        ],
        "replication_ids": [0],
        "seed_difference_replication_ids": [0, 1],
        "results": [
            {
                "event_id": result.event_id,
                "replication": result.replication,
                "probe_id": probe_lookup[
                    _payload_sha256(asdict(result.structural_parameters))
                ],
                "result_checksum": result.diagnostics.result_checksum,
                "recovery_success": result.metrics.recovery_success,
                "right_censored": result.metrics.right_censored,
                "event_hours": result.diagnostics.event_hours,
            }
            for result in smoke_results
        ],
        "structural_validity": True,
        "candidate_ranking_performed": False,
        "stage2_fit_performed": False,
        "final_validation_event_simulated": False,
        "full_trajectories_tracked": False,
    }
    empirical_moments_path = (
        CONFIDENCE_EVIDENCE / "empirical_moments.csv"
    )
    empirical_record = _manifest_records().get(
        empirical_moments_path.relative_to(REPOSITORY_ROOT).as_posix()
    )
    if (
        empirical_record is None
        or sha256_file(empirical_moments_path) != empirical_record["sha256"]
    ):
        raise ValueError("Registered empirical moment evidence does not reproduce.")
    empirical_moments = pd.read_csv(empirical_moments_path).set_index("moment")
    ordinary_preservation = {
        name: float(empirical_moments.loc[name, "empirical_value"])
        for name in ("ordinary_below_mean", "ordinary_above_mean")
    }
    smoke_evidence["simulated_moments_by_probe"] = {}
    for probe in probes:
        selected_results = [
            result
            for result in smoke_results
            if result.structural_parameters == probe["structural_parameters"]
        ]
        aggregated = aggregate_simulated_core_moments(
            selected_results,
            ordinary_preservation=ordinary_preservation,
            expected_event_ids=smoke_ids,
        )
        smoke_evidence["simulated_moments_by_probe"][probe["probe_id"]] = {
            "moments": aggregated.moments,
            "event_count": aggregated.event_count,
            "right_censored_event_replications": (
                aggregated.right_censored_event_replications
            ),
            "equal_event_weighting": aggregated.equal_event_weighting,
            "objective_evaluated": aggregated.objective_evaluated,
            "diagnostic_moments_excluded": list(
                aggregated.diagnostic_moments_excluded
            ),
        }
    _atomic_json(evidence_dir / "event_simulation_smoke.json", smoke_evidence)
    _write_diagnostics(diagnostics_dir, smoke_results)
    if action == "smoke":
        return {
            "action": action,
            "smoke_event_ids": smoke_ids,
            "result_checksums": [
                result.diagnostics.result_checksum for result in smoke_results
            ],
        }

    benchmark_probe = probes[1]["structural_parameters"]
    timings: list[float] = []
    benchmark_results: list[ConditionalEventResult] = []
    tracemalloc.start()
    benchmark_start = time.perf_counter()
    for event_id in smoke_ids:
        for replication in (0, 1):
            started = time.perf_counter()
            benchmark_results.append(
                simulate_conditional_event(
                    path=paths[event_id],
                    config=config,
                    structural_parameters=benchmark_probe,
                    replication=replication,
                    registry_id=registry_id,
                    stage1_owners=stage1,
                )
            )
            timings.append(time.perf_counter() - started)
    wall = time.perf_counter() - benchmark_start
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    seconds_per_run = wall / len(benchmark_results)
    benchmark_evidence = {
        "schema_version": 1,
        "status": "bounded_benchmark_complete",
        "runtime_adopted": False,
        "benchmark_workload": {
            "events": 4,
            "replications": 2,
            "probe_id": "sobol_127",
            "registry_id": registry_id,
            "event_replication_runs": 8,
        },
        "observed": {
            "wall_clock_seconds": wall,
            "median_run_seconds": float(np.median(timings)),
            "maximum_run_seconds": float(np.max(timings)),
            "peak_traced_memory_bytes": int(peak_memory),
            "compact_result_payload_bytes": len(
                _canonical_json(
                    [
                        {
                            "metrics": asdict(result.metrics),
                            "diagnostics": asdict(result.diagnostics),
                        }
                        for result in benchmark_results
                    ]
                )
            ),
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "not reported",
        },
        "linear_extrapolations": _workload_estimates(
            seconds_per_run=seconds_per_run
        ),
        "extrapolated_workloads_executed": False,
        "optimisation_design_changed": False,
        "implementation_optimisations_if_needed": [
            "event-level parallelism",
            "cached deterministic initial states",
            "cached ETH paths",
            "cached residual blocks",
            "vectorised metric calculation",
        ],
    }
    _atomic_json(
        evidence_dir / "event_simulation_benchmark.json", benchmark_evidence
    )
    if register_manifest and evidence_dir.resolve() == CONFIDENCE_EVIDENCE.resolve():
        register_event_evidence(evidence_dir)
    return {
        "action": action,
        "common_horizon_hours": config.maximum_event_horizon_hours,
        "smoke_event_ids": smoke_ids,
        "smoke_result_checksums": [
            result.diagnostics.result_checksum for result in smoke_results
        ],
        "benchmark_runs": len(benchmark_results),
        "benchmark_wall_seconds": wall,
        "evidence_files": [
            "conditional_event_specification.json",
            "conditional_initial_state.json",
            "recovery_gate_specification.json",
            "event_simulation_smoke.json",
            "event_simulation_benchmark.json",
        ],
        "final_validation_simulated": False,
        "candidate_ranking_performed": False,
        "stage2_fit_performed": False,
    }
