"""Semantic and final-programme validation for the oracle-delay freeze."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from dai_sim.experiments.final.programme import (
    FinalExperimentProgramme,
    load_programme,
)
from dai_sim.inputs.oracle_delay import (
    DEFAULT_REGISTRY_PATH,
    OracleDelayRegistry,
    load_oracle_delay_registry,
)
from dai_sim.model.collateral_prices import normalise_collateral_price_paths


EXPECTED_PROGRAMME_IDENTITY = (
    "084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260"
)
EXPECTED_ANCHORS = (
    ("empirical_crypto", "joint_crypto_high_correlation"),
    ("stable_supported", "joint_crypto_stable_stress"),
)
EXPECTED_READINESS = {
    "oracle_delay_empirically_identified": (
        "experiment_e_ready_with_empirical_delay_registry"
    ),
    "oracle_delay_partially_identified_from_update_intervals": (
        "experiment_e_ready_with_partial_delay_registry"
    ),
    "oracle_delay_partially_identified_from_documented_rule": (
        "experiment_e_ready_with_partial_delay_registry"
    ),
    "transparent_sensitivity_not_empirically_identified": (
        "experiment_e_ready_with_transparent_delay_sensitivity"
    ),
}


@dataclass(frozen=True)
class ResolvedExperimentECell:
    """One frozen master-programme cell with its external numeric delay."""

    cell_identifier: str
    portfolio_identifier: str
    shock_identifier: str
    oracle_treatment_identifier: str
    oracle_delay_steps: int
    replication_count: int
    maximum_liquidations_per_step: int
    confidence_scenario_identifier: str
    hurdle_profile_identifier: str
    master_row_checksum: str


def validate_parameter_semantics() -> dict[str, Any]:
    """Validate the implemented global lag without executing a simulation."""
    market = {
        "ETH": np.array([100.0, 80.0, 90.0]),
        "BTC": np.array([200.0, 150.0, 175.0]),
        "STABLE": np.array([1.0, 0.9, 0.95]),
    }
    paths = normalise_collateral_price_paths(market, delay_steps=1)
    if any(
        not np.array_equal(paths.market_prices[name], values)
        for name, values in market.items()
    ):
        raise ValueError("Oracle delay unexpectedly changed market prices.")
    for name, values in market.items():
        expected = np.array([values[0], values[0], values[1]])
        if not np.array_equal(paths.oracle_prices[name], expected):
            raise ValueError(f"Oracle delay semantics differ for {name}.")
    return {
        "parameter_name": "SimulationConfig.oracle_delay_steps",
        "unit": "integer simulation steps",
        "step_duration_hours": 1,
        "scope": "global across ETH, BTC and STABLE collateral families",
        "delayed_object": "protocol-observed collateral price path",
        "liquidation_eligibility": "uses delayed oracle prices",
        "initial_buffer": "repeat first market price for the first delay_steps",
        "market_prices_contemporaneous": True,
        "gas_prices_contemporaneous": True,
        "dai_price_process_contemporaneous": True,
        "interpolation": False,
        "passed": True,
    }


def resolve_experiment_e_cells(
    programme: FinalExperimentProgramme | None = None,
    registry: OracleDelayRegistry | None = None,
) -> tuple[ResolvedExperimentECell, ...]:
    """Resolve the six frozen E rows without changing the master programme."""
    owner = programme or load_programme()
    delay_registry = registry or load_oracle_delay_registry()
    if owner.programme_identity != EXPECTED_PROGRAMME_IDENTITY:
        raise ValueError("Master final-programme identity changed.")
    experiment = owner.experiments_by_identifier["E_oracle_delay"]
    if experiment.execution_status != (
        "preregistered_blocked_pending_oracle_delay_freeze"
    ):
        raise ValueError("Frozen Experiment E programme status changed.")
    if experiment.dependency_status != "oracle_delay_freeze_required":
        raise ValueError("Frozen Experiment E dependency marker changed.")
    resolved: list[ResolvedExperimentECell] = []
    for cell in experiment.cells:
        if cell.oracle_delay_steps is not None:
            raise ValueError("Master programme must retain unresolved E delays.")
        if cell.oracle_treatment_identifier is None:
            raise ValueError("Experiment E treatment identifier is absent.")
        treatment = delay_registry.by_identifier(
            cell.oracle_treatment_identifier
        )
        resolved.append(
            ResolvedExperimentECell(
                cell_identifier=cell.identifier,
                portfolio_identifier=cell.portfolio_identifier,
                shock_identifier=cell.shock_identifier,
                oracle_treatment_identifier=treatment.identifier,
                oracle_delay_steps=treatment.delay_steps,
                replication_count=cell.replication_count,
                maximum_liquidations_per_step=(
                    cell.maximum_liquidations_per_step
                ),
                confidence_scenario_identifier=(
                    cell.confidence_scenario_identifier
                ),
                hurdle_profile_identifier=cell.hurdle_profile_identifier,
                master_row_checksum=cell.row_checksum,
            )
        )
    return tuple(resolved)


def validate_experiment_e_readiness(
    *,
    programme: FinalExperimentProgramme | None = None,
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    """Validate external dependency resolution while leaving E unexecuted."""
    owner = programme or load_programme()
    registry = load_oracle_delay_registry(registry_path)
    semantic_contract = validate_parameter_semantics()
    cells = resolve_experiment_e_cells(owner, registry)
    anchors = tuple(
        dict.fromkeys(
            (cell.portfolio_identifier, cell.shock_identifier)
            for cell in cells
        )
    )
    if anchors != EXPECTED_ANCHORS:
        raise ValueError("Experiment E anchor set differs.")
    if len(cells) != 6 or sum(cell.replication_count for cell in cells) != 768:
        raise ValueError("Experiment E cell or simulation count differs.")
    if {cell.replication_count for cell in cells} != {128}:
        raise ValueError("Experiment E replication count differs.")
    if {cell.maximum_liquidations_per_step for cell in cells} != {26}:
        raise ValueError("Experiment E keeper capacity differs.")
    if {cell.hurdle_profile_identifier for cell in cells} != {
        "direct_cost_only"
    }:
        raise ValueError("Experiment E keeper hurdle differs.")
    if {cell.confidence_scenario_identifier for cell in cells} != {
        "stage1_only"
    }:
        raise ValueError("Experiment E confidence scenario differs.")
    for anchor in EXPECTED_ANCHORS:
        anchor_cells = [
            cell
            for cell in cells
            if (cell.portfolio_identifier, cell.shock_identifier) == anchor
        ]
        if [cell.oracle_delay_steps for cell in anchor_cells] != [0, 1, 2]:
            raise ValueError("Experiment E treatment ordering differs.")
    expected_readiness = EXPECTED_READINESS[registry.source_classification]
    if registry.readiness_classification != expected_readiness:
        raise ValueError("Experiment E readiness classification differs.")
    return {
        "programme_identity": owner.programme_identity,
        "programme_cells_unchanged": len(owner.cells) == 43,
        "programme_planned_simulations_unchanged": (
            owner.planned_core_simulations == 5_504
        ),
        "master_programme_e_status": (
            "preregistered_blocked_pending_oracle_delay_freeze"
        ),
        "external_dependency_status": "resolved",
        "readiness_classification": expected_readiness,
        "experiment_e_status": "ready_but_unexecuted",
        "resolved_cells": [asdict(cell) for cell in cells],
        "resolved_cell_count": len(cells),
        "replications_per_cell": 128,
        "planned_simulations": 768,
        "anchors": [list(anchor) for anchor in anchors],
        "common_random_number_contract": {
            "identical_initial_portfolio_state": True,
            "identical_shock_path": True,
            "identical_gas_path": True,
            "identical_liquidation_arrivals": True,
            "identical_keeper_gas_unit_draws": True,
            "identical_dai_residual_blocks": True,
            "identical_non_delay_randomness": True,
            "sole_treatment_difference": "oracle_delay_steps",
        },
        "semantic_contract": semantic_contract,
        "experiment_e_simulations": 0,
        "checkpoints_created": 0,
        "runtime_adopted": False,
        "passed": True,
    }
