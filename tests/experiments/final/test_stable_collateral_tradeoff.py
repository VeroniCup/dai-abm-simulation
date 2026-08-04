"""Regression gates for final Experiment C stable-collateral trade-offs."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dai_sim.experiments.final import (
    stable_collateral_tradeoff as experiment_c,
)
from dai_sim.experiments.final.programme import load_programme


def _compact_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load registered summaries without replaying a scientific replication."""
    cells = pd.read_csv(
        experiment_c.EVIDENCE_DIR / "stable_collateral_tradeoff_cell_summary.csv"
    )
    collateral = pd.read_csv(
        experiment_c.EVIDENCE_DIR
        / "stable_collateral_tradeoff_collateral_summary.csv"
    )
    return cells, collateral


def _reproducibility() -> dict[str, object]:
    return json.loads(
        (
            experiment_c.EVIDENCE_DIR
            / "stable_collateral_tradeoff_reproducibility.json"
        ).read_text(encoding="utf-8")
    )


def test_registry_has_exact_shock_first_cells() -> None:
    cells = experiment_c.build_cell_registry()
    assert len(cells) == 12
    assert tuple(cell.identifier for cell in cells) == experiment_c.CELL_ORDER
    assert tuple(cell.shock for cell in cells) == tuple(
        shock
        for shock in experiment_c.SHOCK_ORDER
        for _ in experiment_c.PORTFOLIO_ORDER
    )


def test_registry_has_exact_portfolios_and_shocks() -> None:
    cells = experiment_c.build_cell_registry()
    assert {cell.portfolio for cell in cells} == {
        "empirical_crypto",
        "stable_supported",
        "stable_heavy",
    }
    assert {cell.shock for cell in cells} == set(experiment_c.SHOCK_ORDER)
    assert "eth_only" not in {cell.portfolio for cell in cells}
    assert "balanced_crypto" not in {cell.portfolio for cell in cells}


def test_registry_preserves_common_settings() -> None:
    cells = experiment_c.build_cell_registry()
    assert {cell.capacity for cell in cells} == {26}
    assert {cell.hurdle for cell in cells} == {"direct_cost_only"}
    assert {cell.confidence for cell in cells} == {"stage1_only"}
    assert {cell.oracle_delay for cell in cells} == {0}
    assert {cell.replication_count for cell in cells} == {128}


def test_programme_boundary_is_frozen() -> None:
    programme = load_programme()
    assert programme.programme_identity == experiment_c.MASTER_PROGRAMME_IDENTITY
    assert len(programme.experiments_by_identifier[experiment_c.EXPERIMENT_ID].cells) == 12
    assert sum(
        len(experiment.cells) * experiment.replication_count
        for experiment in programme.experiments
    ) == 5_504


def test_seed_registry_is_c_owned_and_deterministic() -> None:
    first = experiment_c.seed_record(12)
    second = experiment_c.seed_record(12)
    assert first == second
    assert first["namespace"] == "final-stable-collateral-tradeoff-v1"
    assert experiment_c.seed_record(13) != first
    assert experiment_c.seed_registry_checksum() == (
        experiment_c.seed_registry_checksum()
    )


def test_unregistered_seed_stream_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unregistered Experiment C"):
        experiment_c.derive_seed(0, "experiment_d")


def test_nested_initialisations_cover_stable_heavy_prefix() -> None:
    payload = experiment_c._draw_c_nested_states(0)
    states = payload["states"]
    assert payload["audit"]["passed"] is True
    assert tuple(states) == experiment_c.PORTFOLIO_ORDER
    assert len(states["stable_heavy"].sampled.query("family == 'STABLE'")) == 250
    assert len(states["stable_supported"].sampled.query("family == 'STABLE'")) == 125
    assert len(states["empirical_crypto"].sampled.query("family == 'STABLE'")) == 0


def test_nested_audit_rejects_wrong_portfolio_order() -> None:
    payload = experiment_c._draw_c_nested_states(0)
    states = payload["states"]
    reordered = {
        "stable_supported": states["stable_supported"],
        "empirical_crypto": states["empirical_crypto"],
        "stable_heavy": states["stable_heavy"],
    }
    with pytest.raises(ValueError, match="portfolio order"):
        experiment_c.audit_nested_initialisations(reordered)


@pytest.mark.parametrize(
    ("shock", "floor"),
    (
        ("joint_crypto_high_correlation", 1.0),
        ("stable_depeg_moderate", 0.95),
        ("stable_depeg_severe", 0.90),
        ("joint_crypto_stable_stress", 0.90),
    ),
)
def test_registered_stable_floors(shock: str, floor: float) -> None:
    streams = experiment_c._prepare_replication_streams(0)
    _, _, audit = experiment_c.build_treatment_paths(
        streams["sampled_market"], shock
    )
    assert audit["stable_multiplier_minimum"] == pytest.approx(floor)
    assert audit["stable_floor_valid"] is True
    assert audit["path_valid"] is True


def test_joint_stress_reuses_crypto_and_severe_stable_kernels() -> None:
    high = experiment_c.registered_shock_kernels(
        "joint_crypto_high_correlation"
    )
    severe = experiment_c.registered_shock_kernels("stable_depeg_severe")
    joint = experiment_c.registered_shock_kernels(
        "joint_crypto_stable_stress"
    )
    assert np.array_equal(joint["ETH"], high["ETH"])
    assert np.array_equal(joint["WBTC"], high["WBTC"])
    assert np.array_equal(joint["STABLE"], severe["STABLE"])


def test_stable_only_shocks_leave_crypto_kernels_ordinary() -> None:
    for shock in ("stable_depeg_moderate", "stable_depeg_severe"):
        kernels = experiment_c.registered_shock_kernels(shock)
        assert np.array_equal(kernels["ETH"], np.ones(216))
        assert np.array_equal(kernels["WBTC"], np.ones(216))


def test_registered_evidence_completes_all_cells() -> None:
    cells, _ = _compact_frames()
    assert cells["cell_identifier"].drop_duplicates().tolist() == list(
        experiment_c.CELL_ORDER
    )
    assert cells["count"].eq(128).all()


def test_registered_negative_control_passes() -> None:
    assert _reproducibility()["crn_audit"]["all_negative_controls_passed"] is True


def test_registered_validity_passes() -> None:
    audit = _reproducibility()["checkpoint_audit"]
    assert audit["complete"] is True
    assert audit["valid_count"] == 128
    assert audit["invalid_count"] == 0


def test_registered_common_random_numbers_hold() -> None:
    audit = _reproducibility()["crn_audit"]
    assert audit["paired_stream_count"] == 128
    assert audit["expected_replication_count"] == 128


def test_registered_semantic_collateral_order() -> None:
    _, rows = _compact_frames()
    observed = rows[["cell_identifier", "family"]].drop_duplicates()
    expected = [
        (cell, family)
        for cell in experiment_c.CELL_ORDER
        for family in ("ETH", "WBTC", "STABLE")
    ]
    assert list(observed.itertuples(index=False, name=None)) == expected


def test_registered_zero_exposure_is_not_normalised_to_zero() -> None:
    _, rows = _compact_frames()
    stable = rows.loc[
        rows["portfolio"].eq("empirical_crypto")
        & rows["family"].eq("STABLE")
    ]
    exposure = stable.loc[stable["metric"].eq("initial_debt_exposure"), "mean"]
    assert exposure.eq(0.0).all()
    normalised = stable.loc[stable["metric"].isin({
        "exposure_normalised_backlog",
        "exposure_normalised_liquidated_debt",
    }), "mean"]
    assert normalised.isna().all()


def test_stable_diagnostics_are_only_attached_to_stable_rows() -> None:
    _, rows = _compact_frames()
    diagnostic = rows.loc[rows["metric"].eq("stable_minimum_price")]
    assert diagnostic.loc[
        diagnostic["family"].eq("STABLE"), "mean"
    ].notna().all()
    assert diagnostic.loc[
        ~diagnostic["family"].eq("STABLE"), "mean"
    ].isna().all()


@pytest.mark.parametrize(
    ("c1", "c2", "c3", "expected"),
    (
        (
            "supported",
            "depeg_exposure_gradient_consistent",
            "contagion_reversal_present",
            "H3_stable_contagion_reversal_supported",
        ),
        (
            "supported",
            "depeg_exposure_gradient_consistent",
            "contagion_erosion_present",
            "H3_stable_tradeoff_supported",
        ),
        (
            "partially_supported",
            "depeg_exposure_gradient_partial",
            "contagion_not_present",
            "H3_stable_tradeoff_partially_supported",
        ),
        (
            "supported",
            "depeg_exposure_gradient_not_present",
            "contagion_not_present",
            "H3_stable_support_without_material_depeg_cost",
        ),
        (
            "not_supported",
            "depeg_exposure_gradient_consistent",
            "contagion_not_present",
            "H3_stable_depeg_cost_without_crypto_protection",
        ),
        (
            "not_supported",
            "depeg_exposure_gradient_not_present",
            "contagion_not_present",
            "H3_no_clear_stable_collateral_tradeoff",
        ),
        (
            "supported",
            "not_operational",
            "not_operational",
            "H3_stable_tradeoff_experiment_not_operational",
        ),
    ),
)
def test_h3_classification_branches(
    c1: str, c2: str, c3: str, expected: str
) -> None:
    assert experiment_c.classify_h3(c1, c2, c3, valid=True) == expected


def test_h3_invalid_branch() -> None:
    assert experiment_c.classify_h3(
        "supported",
        "depeg_exposure_gradient_consistent",
        "contagion_erosion_present",
        valid=False,
    ) == "H3_stable_tradeoff_experiment_invalid"


def test_operationality_statuses() -> None:
    frame = pd.DataFrame(
        {
            "cell_identifier": ["a", "a", "b", "b"],
            "numerical_valid": [True] * 4,
            "accounting_valid": [True] * 4,
            "path_valid": [True] * 4,
            "price_isolation_valid": [True] * 4,
            "nested_initialisation_valid": [True] * 4,
            "stable_negative_control_valid": [True] * 4,
            "variable": [0.0, 1.0, 2.0, 3.0],
            "constant": [0.0] * 4,
        }
    )
    assert experiment_c.classify_metric_operationality(frame, "variable") == "operational"
    assert experiment_c.classify_metric_operationality(frame, "constant") == "degenerate"
    assert experiment_c.classify_metric_operationality(frame, "missing") == "not_operational"
    invalid = frame.assign(numerical_valid=False)
    assert experiment_c.classify_metric_operationality(invalid, "variable") == "invalid"


def test_raw_contrast_sign_is_left_minus_right() -> None:
    values = np.array([3.0, 4.0]) - np.array([1.0, 2.0])
    row = experiment_c._contrast_row(
        order=1,
        contrast_type="raw_portfolio_contrast",
        shock="shock",
        portfolio="stable_heavy",
        reference_portfolio="stable_supported",
        comparison_shock=None,
        family=None,
        metric="backlog_area_share",
        direction_multiplier=1,
        values=values,
    )
    assert row["mean"] == pytest.approx(2.0)


def test_lower_is_better_advantage_sign() -> None:
    assert experiment_c.METRIC_DIRECTIONS["backlog_area_share"] == -1
    empirical = np.array([0.2, 0.3])
    stable = np.array([0.1, 0.2])
    advantage = -1 * (stable - empirical)
    assert advantage.tolist() == pytest.approx([0.1, 0.1])


def test_recovery_probability_direction_is_positive() -> None:
    assert experiment_c.METRIC_DIRECTIONS["recovery_probability_720h"] == 1


def test_completed_contrasts_report_all_exposure_gradient_levels() -> None:
    contrasts = pd.read_csv(
        experiment_c.EVIDENCE_DIR
        / "stable_collateral_tradeoff_contrasts.csv"
    )
    gradients = contrasts.loc[
        contrasts["contrast_type"].eq("exposure_gradient")
    ]
    assert gradients["family"].isna().any()
    stable_metrics = set(
        gradients.loc[gradients["family"].eq("STABLE"), "metric"]
    )
    assert "stable_attributed_liquidated_debt" in stable_metrics
    assert "stable_exposure_normalised_liquidated_debt" in stable_metrics


@pytest.mark.parametrize(
    ("valid", "operational_count", "passing", "expected"),
    (
        (True, 2, {"stable_supported", "stable_heavy"}, "supported"),
        (True, 2, {"stable_supported"}, "partially_supported"),
        (True, 2, set(), "not_supported"),
        (True, 1, set(), "not_operational"),
        (False, 2, set(), "invalid"),
    ),
)
def test_c1_classifier_branches(
    monkeypatch: pytest.MonkeyPatch,
    valid: bool,
    operational_count: int,
    passing: set[str],
    expected: str,
) -> None:
    operationality = {
        metric: (
            "operational"
            if index < operational_count
            else "degenerate"
        )
        for index, metric in enumerate(experiment_c.PRIMARY_SOLVENCY_METRICS)
    }

    def lookup(
        contrasts: pd.DataFrame,
        contrast_type: str,
        portfolio: str,
        metric: str,
        **kwargs: object,
    ) -> dict[str, float]:
        del contrasts, contrast_type, metric, kwargs
        passed = portfolio in passing
        return {
            "mean": 1.0 if passed else 0.0,
            "ci95_lower": 0.5 if passed else -0.5,
            "ci95_upper": 1.5 if passed else 0.5,
        }

    monkeypatch.setattr(experiment_c, "_contrast_lookup", lookup)
    classification, _ = experiment_c.classify_c1(
        pd.DataFrame(), operationality, valid=valid
    )
    assert classification == expected


@pytest.mark.parametrize(
    ("mode", "valid", "negative_control", "active", "expected"),
    (
        (
            "consistent",
            True,
            True,
            True,
            "depeg_exposure_gradient_consistent",
        ),
        (
            "partial",
            True,
            True,
            True,
            "depeg_exposure_gradient_partial",
        ),
        (
            "not_present",
            True,
            True,
            True,
            "depeg_exposure_gradient_not_present",
        ),
        (
            "inconsistent",
            True,
            True,
            True,
            "depeg_exposure_gradient_inconsistent",
        ),
        (
            "explained_opposite",
            True,
            True,
            True,
            "depeg_exposure_gradient_not_present",
        ),
        ("not_operational", True, True, False, "not_operational"),
        ("invalid", False, True, True, "invalid"),
    ),
)
def test_c2_classifier_branches(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    valid: bool,
    negative_control: bool,
    active: bool,
    expected: str,
) -> None:
    operationality = {
        metric: (
            "operational"
            if metric in {"backlog_area_share", "liquidated_debt_share"}
            else "degenerate"
        )
        for metric in experiment_c.PRIMARY_SOLVENCY_METRICS
    }

    def activity(
        collateral: pd.DataFrame,
        *,
        shock: str,
        portfolio: str,
    ) -> dict[str, float]:
        del collateral, shock, portfolio
        value = 1.0 if active else 0.0
        return {
            "unsafe_vault_count": value,
            "selected_attempts": value,
            "capacity_rejections": 0.0,
            "liquidated_debt": value,
            "backlog_area": 0.0,
            "displaced_candidates": 0.0,
        }

    def lookup(
        contrasts: pd.DataFrame,
        contrast_type: str,
        portfolio: str,
        metric: str,
        **kwargs: object,
    ) -> dict[str, float]:
        del contrasts, portfolio, kwargs
        positive = False
        negative = False
        if contrast_type == "severity_increment":
            positive = mode in {"consistent", "partial"}
        elif metric in {
            "backlog_area_share",
            "liquidated_debt_share",
        }:
            positive = mode == "consistent"
            negative = mode in {"inconsistent", "explained_opposite"}
        elif (
            mode == "explained_opposite"
            and metric == "stable_exposure_normalised_liquidated_debt"
        ):
            negative = True
        return {
            "mean": 1.0 if positive else -1.0 if negative else 0.0,
            "ci95_lower": 0.5 if positive else -1.5 if negative else -0.5,
            "ci95_upper": 1.5 if positive else -0.5 if negative else 0.5,
        }

    monkeypatch.setattr(experiment_c, "_stable_activity", activity)
    monkeypatch.setattr(experiment_c, "_contrast_lookup", lookup)
    classification, _ = experiment_c.classify_c2(
        pd.DataFrame(),
        pd.DataFrame(),
        operationality,
        valid=valid,
        negative_control_passed=negative_control,
    )
    assert classification == expected


@pytest.mark.parametrize(
    ("mode", "valid", "active", "expected"),
    (
        ("reversal", True, True, "contagion_reversal_present"),
        ("erosion", True, True, "contagion_erosion_present"),
        ("mixed", True, True, "contagion_mixed"),
        ("not_present", True, True, "contagion_not_present"),
        ("not_operational", True, False, "not_operational"),
        ("invalid", False, True, "invalid"),
    ),
)
def test_c3_classifier_branches(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    valid: bool,
    active: bool,
    expected: str,
) -> None:
    operationality = {
        metric: (
            "operational"
            if metric in {"backlog_area_share", "liquidated_debt_share"}
            else "degenerate"
        )
        for metric in experiment_c.PRIMARY_SOLVENCY_METRICS
    }

    def activity(
        collateral: pd.DataFrame,
        *,
        shock: str,
        portfolio: str,
    ) -> dict[str, float]:
        del collateral, shock, portfolio
        value = 1.0 if active else 0.0
        return {
            "unsafe_vault_count": value,
            "selected_attempts": value,
            "capacity_rejections": 0.0,
            "liquidated_debt": value,
            "backlog_area": 0.0,
            "displaced_candidates": 0.0,
        }

    def lookup(
        contrasts: pd.DataFrame,
        contrast_type: str,
        portfolio: str,
        metric: str,
        **kwargs: object,
    ) -> dict[str, float]:
        del contrasts, portfolio, metric, kwargs
        negative = mode == "reversal" and (
            contrast_type == "joint_stress_advantage"
        )
        positive = mode == "erosion" and (
            contrast_type == "tradeoff_erosion"
        )
        return {
            "mean": 1.0 if positive else -1.0 if negative else 0.0,
            "ci95_lower": 0.5 if positive else -1.5 if negative else -0.5,
            "ci95_upper": 1.5 if positive else -0.5 if negative else 0.5,
        }

    contagion_mean = 1.0 if mode == "mixed" else 0.0
    contrasts = pd.DataFrame(
        {
            "contrast_type": ["stable_to_crypto_contagion"] * 2,
            "portfolio": ["stable_supported", "stable_heavy"],
            "metric": ["backlog_area", "backlog_area"],
            "mean": [contagion_mean, contagion_mean],
        }
    )
    monkeypatch.setattr(experiment_c, "_stable_activity", activity)
    monkeypatch.setattr(experiment_c, "_contrast_lookup", lookup)
    classification, _ = experiment_c.classify_c3(
        contrasts,
        pd.DataFrame(),
        operationality,
        valid=valid,
    )
    assert classification == expected


def test_specification_excludes_results_and_selection() -> None:
    payload = experiment_c.specification_payload(
        experiment_c.MASTER_PROGRAMME_IDENTITY
    )
    encoded = json.dumps(payload, sort_keys=True)
    assert "preferred_portfolio" not in encoded
    assert "preferred_shock" not in encoded
    assert "results" not in payload
    assert payload["portfolio_selection_permitted"] is False
    assert payload["runtime_adopted"] is False


def test_specification_records_counterfactual_stable_boundary() -> None:
    payload = experiment_c.specification_payload(
        experiment_c.MASTER_PROGRAMME_IDENTITY
    )
    stable = payload["stable_owner"]
    assert stable["status"] == "counterfactual_stable_proxy"
    assert stable["scenario_defined"] is True
    assert stable["usdc_svb_used"] is False


def test_specification_records_stage1_owners() -> None:
    owners = experiment_c.specification_payload(
        experiment_c.MASTER_PROGRAMME_IDENTITY
    )["stage1_owners"]
    assert owners["below_peg_response"] == pytest.approx(0.199381)
    assert owners["above_peg_response"] == pytest.approx(0.105131)
    assert owners["residual_sequence_sha256"] == (
        "3fa2319cee9e1749405c0dc477e0f11ef9c31dd83c371b619bd33eda23c37c30"
    )
    assert owners["residual_block_sha256"] == (
        "6f55b51acfc1da23836b3d847153bd4f68e4a38fc33fd967e9d3b795737bf28c"
    )


def test_registry_serialisation_is_deterministic() -> None:
    assert experiment_c._csv_bytes(experiment_c._registry_frame()) == (
        experiment_c._csv_bytes(experiment_c._registry_frame())
    )


def test_json_serialisation_rejects_unsupported_values() -> None:
    with pytest.raises(TypeError):
        experiment_c._canonical_json({"bad": object()})


def test_collateral_evidence_uses_semantic_family_order() -> None:
    _, summary = _compact_frames()
    first = summary.loc[
        summary["cell_identifier"].eq(experiment_c.CELL_ORDER[0])
    ]["family"].drop_duplicates().tolist()
    assert first == ["ETH", "WBTC", "STABLE"]


def test_regression_audit_preserves_a_and_b() -> None:
    audit = experiment_c.regression_audit()
    assert audit["passed"] is True
    assert audit["a_evidence"]["file_count"] == 8
    assert audit["b_evidence"]["file_count"] == 8
    assert audit["a_checkpoints"]["file_count"] == 128
    assert audit["b_checkpoints"]["file_count"] == 128


def test_later_experiment_identifiers_are_absent_from_cells() -> None:
    encoded = json.dumps(
        [cell.identifier for cell in experiment_c.build_cell_registry()]
    )
    assert "capacity_14" not in encoded
    assert "capacity_45" not in encoded
    assert "oracle_delay" not in encoded
    assert "persistent_confidence" not in encoded


def test_usdc_svb_and_heldout_are_excluded() -> None:
    payload = experiment_c.specification_payload(
        experiment_c.MASTER_PROGRAMME_IDENTITY
    )
    assert payload["usdc_svb_used"] is False
    assert payload["held_out_data_used"] is False
    assert payload["final_validation_data_used"] is False


def test_checkpoint_validator_rejects_missing_file(tmp_path: Path) -> None:
    assert experiment_c._valid_checkpoint(
        tmp_path / "missing.json",
        replication=0,
        programme_identity=experiment_c.MASTER_PROGRAMME_IDENTITY,
    ) is False


def test_master_cell_mutation_is_rejected() -> None:
    programme = load_programme()
    source = programme.experiments_by_identifier[
        experiment_c.EXPERIMENT_ID
    ].cells[0]
    with pytest.raises(ValueError, match="maximum_liquidations"):
        experiment_c._validate_master_cell(
            replace(source, maximum_liquidations_per_step=14)
        )
