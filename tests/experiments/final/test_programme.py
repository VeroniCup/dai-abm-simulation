from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from dai_sim.experiments.final.programme import (
    EXPERIMENT_ORDER,
    build_programme_registry,
    load_final_experiment_programme,
    load_programme,
    programme_identity,
    specification_payload,
    write_programme_preregistration,
)


ROOT = Path(__file__).resolve().parents[3]
PROGRAMME_PATH = (
    ROOT / "config/sensitivities/final_experiment_programme.yaml"
)


EXPECTED_RESEARCH_QUESTIONS = {
    "RQ1": (
        "How do collateral-price shocks propagate through vault "
        "collateralisation, liquidation eligibility, keeper execution and "
        "DAI price adjustment in the ETH-only core model?"
    ),
    "RQ2": (
        "How do gas costs, keeper participation, liquidation capacity and "
        "oracle delay affect liquidation completion, bad debt and DAI peg "
        "recovery?"
    ),
    "RQ3": (
        "Which collateral-recovery and behavioural assumptions materially "
        "affect the speed and reliability of peg restoration after stress?"
    ),
    "RQ4": (
        "Under what collateral compositions and shock structures does "
        "multi-collateral DAI become more resilient than an ETH-only system, "
        "and when does diversification instead transmit or concentrate risk?"
    ),
}
EXPECTED_HYPOTHESES = {
    "H1": (
        "Liquidation frictions",
        "Stronger liquidation frictions are expected to increase unresolved "
        "debt, bad debt and the magnitude or duration of negative peg "
        "deviations.",
    ),
    "H2": (
        "Oracle delay",
        "Oracle delay is expected to widen the mismatch between market "
        "conditions and protocol action, especially after rapid "
        "collateral-price shocks.",
    ),
    "H3": (
        "Diversification and contagion",
        "Multi-collateral diversification is expected to reduce system losses "
        "under isolated collateral-specific shocks, but its benefits should "
        "diminish under correlated stress and may reverse when a collateral "
        "intended to provide stability experiences its own depeg or liquidity "
        "impairment.",
    ),
    "H4": (
        "Recovery and behavioural stabilisation",
        "Recovery is expected to depend jointly on collateral-price rebound, "
        "liquidation resolution and behavioural stabilisation, with unresolved "
        "backlog limiting the effect of otherwise favourable recovery "
        "conditions.",
    ),
}


def test_programme_owns_exactly_four_questions_and_four_hypotheses() -> None:
    programme = load_final_experiment_programme()
    assert {
        item.identifier: item.text for item in programme.research_questions
    } == EXPECTED_RESEARCH_QUESTIONS
    assert {
        item.identifier: (item.title, item.statement)
        for item in programme.hypotheses
    } == EXPECTED_HYPOTHESES
    assert "H5" not in PROGRAMME_PATH.read_text(encoding="utf-8")
    assert "H6" not in PROGRAMME_PATH.read_text(encoding="utf-8")


def test_experiment_and_synthesis_statuses_are_exact() -> None:
    programme = load_final_experiment_programme()
    assert tuple(item.identifier for item in programme.experiments) == (
        EXPERIMENT_ORDER
    )
    assert tuple(item.execution_status for item in programme.experiments) == (
        "authorised_current_pass",
        "preregistered_not_executed",
        "preregistered_not_executed",
        "preregistered_not_executed",
        "preregistered_blocked_pending_oracle_delay_freeze",
    )
    assert programme.h4_synthesis.identifier == (
        "H4_recovery_and_behaviour_synthesis"
    )
    assert programme.h4_synthesis.research_questions == ("RQ3",)
    assert programme.h4_synthesis.hypotheses == ("H4",)
    assert programme.h4_synthesis.execution_status == (
        "pending_evidence_synthesis"
    )


def test_programme_expands_exactly_43_cells_and_5504_simulations() -> None:
    programme = load_final_experiment_programme()
    assert tuple(len(item.cells) for item in programme.experiments) == (
        8,
        8,
        12,
        9,
        6,
    )
    assert programme.planned_core_cells == len(programme.cells) == 43
    assert programme.planned_core_simulations == sum(
        cell.replication_count for cell in programme.cells
    ) == 5504
    assert programme.authorised_current_pass_simulations == sum(
        cell.replication_count for cell in programme.experiments[0].cells
    ) == 1024
    assert len(
        {
            (cell.experiment_identifier, cell.identifier)
            for cell in programme.cells
        }
    ) == 43
    assert len({cell.row_checksum for cell in programme.cells}) == 43


def test_experiment_ownership_contains_only_approved_hypotheses() -> None:
    programme = load_final_experiment_programme()
    experiments = programme.experiments_by_identifier
    assert experiments["A_idiosyncratic_diversification"].hypotheses == ("H3",)
    assert experiments["B_correlated_stress"].hypotheses == ("H3",)
    assert experiments["C_stable_collateral_tradeoff"].hypotheses == ("H3",)
    assert experiments["D_shared_keeper_capacity"].hypotheses == ("H1", "H3")
    assert experiments["E_oracle_delay"].hypotheses == ("H2",)
    assert {
        hypothesis
        for cell in programme.cells
        for hypothesis in cell.hypotheses
    } == {"H1", "H2", "H3"}


def test_experiment_e_has_identifiers_but_no_numeric_oracle_delays() -> None:
    programme = load_final_experiment_programme()
    experiment_e = programme.experiments_by_identifier["E_oracle_delay"]
    assert {
        cell.oracle_treatment_identifier for cell in experiment_e.cells
    } == {
        "oracle_delay_low",
        "oracle_delay_central",
        "oracle_delay_high",
    }
    assert all(cell.oracle_delay_steps is None for cell in experiment_e.cells)

    raw = yaml.safe_load(PROGRAMME_PATH.read_text(encoding="utf-8"))
    oracle_treatments = raw["experiments"]["E_oracle_delay"]["oracle_treatments"]
    assert all(set(item) == {"identifier"} for item in oracle_treatments)


def test_programme_identity_is_deterministic_and_result_blind(
    tmp_path: Path,
) -> None:
    first = load_final_experiment_programme()
    second = load_final_experiment_programme()
    assert first.programme_identity == second.programme_identity
    assert programme_identity(first) == first.programme_identity
    assert len(first.programme_identity) == 64

    raw = yaml.safe_load(PROGRAMME_PATH.read_text(encoding="utf-8"))
    invalid = deepcopy(raw)
    invalid["results"] = {"preferred_portfolio": "eth_only"}
    invalid_path = tmp_path / "programme_with_results.yaml"
    invalid_path.write_text(
        yaml.safe_dump(invalid, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="forbidden result field"):
        load_final_experiment_programme(invalid_path)

    altered = deepcopy(raw)
    altered["experiments"]["A_idiosyncratic_diversification"][
        "portfolios"
    ][-1] = "stable_heavy"
    altered_path = tmp_path / "altered_treatment_matrix.yaml"
    altered_path.write_text(
        yaml.safe_dump(altered, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="treatment matrix differs"):
        load_programme(altered_path)


def test_frozen_owner_and_non_adoption_boundaries_are_explicit() -> None:
    programme = load_final_experiment_programme()
    assert programme.runtime_adopted is False
    assert programme.parent_commit == (
        "0fabe5192b7942969fd01b602fc1031b6dcf8f62"
    )
    assert programme.package_boundary == "src/dai_sim/experiments/final/"
    assert programme.frozen_inputs["integrated_profile"]["identity"] == (
        "d0241808701d0472532c1f7c502ab6637afd60a50082b94bed9ff66f7ec2d53e"
    )
    assert programme.final_validation_boundary == {
        "final_validation_data_used": False,
        "excluded_intervals": ["ftx", "usdc_svb"],
        "outcome_based_portfolio_selection": False,
        "outcome_based_shock_selection": False,
        "retuning_permitted": False,
    }


def test_stable_programme_apis_are_deterministic_and_result_blind() -> None:
    programme = load_programme()
    assert programme == load_final_experiment_programme()
    registry = build_programme_registry(programme)
    assert len(registry) == 43
    assert tuple(row["programme_order"] for row in registry) == tuple(
        cell.programme_order for cell in programme.cells
    )
    assert all(
        row["row_checksum"] == cell.row_checksum
        for row, cell in zip(registry, programme.cells, strict=True)
    )
    experiment_e = [
        row
        for row in registry
        if row["experiment_identifier"] == "E_oracle_delay"
    ]
    assert len(experiment_e) == 6
    assert all(row["oracle_delay_steps"] is None for row in experiment_e)

    specification = specification_payload(programme)
    assert specification["programme_identity"] == programme_identity(programme)
    assert specification["result_blind"] is True
    assert specification["runtime_adopted"] is False
    assert specification["programme_totals"] == {
        "planned_core_cells": 43,
        "planned_core_simulations": 5504,
        "authorised_current_pass_simulations": 1024,
    }


def test_preregistration_writer_is_atomic_and_immutable(
    tmp_path: Path,
) -> None:
    programme = load_programme()
    first = write_programme_preregistration(
        programme,
        output_dir=tmp_path,
    )
    second = write_programme_preregistration(
        programme,
        output_dir=tmp_path,
    )
    assert first == second
    assert first["registry_rows"] == 43
    assert {
        path.name for path in tmp_path.iterdir()
    } == {
        "final_programme_decision.json",
        "final_programme_registry.csv",
        "final_programme_reproducibility.json",
        "final_programme_specification.json",
    }
    registry_lines = (
        tmp_path / "final_programme_registry.csv"
    ).read_text(encoding="utf-8").splitlines()
    assert len(registry_lines) == 44

    decision_path = tmp_path / "final_programme_decision.json"
    decision_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Existing pre-registration differs"):
        write_programme_preregistration(
            programme,
            output_dir=tmp_path,
        )
