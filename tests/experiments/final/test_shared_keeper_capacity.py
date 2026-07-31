"""Focused tests for final Experiment D shared keeper capacity."""

from __future__ import annotations

from dataclasses import replace
import json

import pandas as pd
import pytest

from dai_sim.experiments.final import shared_keeper_capacity as d
from dai_sim.experiments.final.programme import load_programme
from dai_sim.model.liquidation import rank_liquidation_candidates
from dai_sim.model.vault import Vault


@pytest.fixture(scope="module")
def smoke_replication() -> dict[str, object]:
    """Reuse one real registered replication across integration assertions."""
    return d.simulate_replication(0)


def _contrast(
    mean: float,
    lower: float,
    upper: float,
    *,
    operationality: str = "operational",
) -> dict[str, object]:
    return {
        "mean": mean,
        "ci95_lower": lower,
        "ci95_upper": upper,
        "operationality": operationality,
        "classification": "no_capacity_effect",
    }


def test_registry_is_exact_frozen_nine_cell_matrix() -> None:
    cells = d.build_cell_registry()
    assert len(cells) == 9
    assert tuple(cell.identifier for cell in cells) == d.CELL_ORDER
    assert tuple(cell.master_row_checksum for cell in cells) == (
        d.EXPECTED_MASTER_CELL_CHECKSUMS
    )
    assert [cell.capacity for cell in cells] == [14, 26, 45] * 3
    assert {cell.replication_count for cell in cells} == {128}
    assert {cell.hurdle for cell in cells} == {"direct_cost_only"}
    assert {cell.confidence for cell in cells} == {"stage1_only"}
    assert {cell.oracle_delay for cell in cells} == {0}


def test_registry_contains_only_three_registered_anchors() -> None:
    cells = d.build_cell_registry()
    assert tuple(
        dict.fromkeys((cell.portfolio, cell.shock) for cell in cells)
    ) == d.ANCHOR_ORDER
    assert "eth_only" not in {cell.portfolio for cell in cells}
    assert "balanced_crypto" not in {cell.portfolio for cell in cells}


def test_dedicated_seed_registry_is_deterministic_and_separate() -> None:
    assert d.seed_record(0) == d.seed_record(0)
    assert d.seed_record(0) != d.seed_record(1)
    assert d.EXPERIMENT_NAMESPACE not in {
        "final-idiosyncratic-diversification-v1",
        "final-correlated-stress-v1",
        "final-stable-collateral-tradeoff-v1",
    }
    assert len(d.seed_registry_checksum()) == 64


def test_common_streams_are_deterministic() -> None:
    first = d._prepare_replication_streams(0)
    second = d._prepare_replication_streams(0)
    assert first["paired_stream_checksum"] == second["paired_stream_checksum"]
    assert first["stream_components"] == second["stream_components"]
    assert first["nested_audit"]["passed"] is True


def test_capacity_does_not_change_frozen_ranking() -> None:
    audit = d._ranking_preflight()
    assert audit == {
        "passed": True,
        "ranked_vault_ids": [1, 2, 3],
        "capacity_neutral": True,
        "collateral_quota": False,
        "random_tie_break": False,
    }


def test_ranking_uses_profit_debt_and_vault_id() -> None:
    vaults = [
        Vault(2, 2, 0.5, 1_000.0, collateral_type="ETH"),
        Vault(1, 1, 1.0, 2_000.0, collateral_type="ETH"),
        Vault(3, 3, 0.5, 1_000.0, collateral_type="ETH"),
    ]
    base = (
        d.resolve_integrated_empirical_eth_profile()
        .bundle.base_bundle.liquidation_config
    )
    ranked = rank_liquidation_candidates(
        vaults,
        prices={"ETH": 1_000.0, "BTC": 30_000.0, "STABLE": 1.0},
        config=replace(
            base,
            gas_cost=0.0,
            risk_cost_rate=0.0,
            max_close_factor=1.0,
            max_liquidations_per_step=14,
        ),
    )
    assert ranked["vault_id"].tolist() == [1, 2, 3]


@pytest.mark.parametrize(
    ("values", "valid", "expected"),
    [
        ([0.0, 1.0], True, "operational"),
        ([0.0, 0.0], True, "degenerate"),
        ([None, None], True, "not_operational"),
        ([0.0, 1.0], False, "invalid"),
    ],
)
def test_metric_operationality_branches(
    values: list[float | None],
    valid: bool,
    expected: str,
) -> None:
    assert (
        d.classify_metric_operationality(values, valid=valid) == expected
    )


@pytest.mark.parametrize(
    ("low_central", "central_high", "low_high", "operationality", "valid", "expected"),
    [
        (_contrast(1, 0.2, 1.8), _contrast(1, 0.2, 1.8), _contrast(2, 1, 3), "operational", True, "monotonic_relief"),
        (_contrast(0, -1, 1), _contrast(1, 0.2, 1.8), _contrast(1, 0.2, 1.8), "operational", True, "threshold_relief"),
        (_contrast(-1, -2, -0.2), _contrast(3, 2, 4), _contrast(2, 1, 3), "operational", True, "non_monotonic_relief"),
        (_contrast(0, -1, 1), _contrast(0, -1, 1), _contrast(0, -1, 1), "operational", True, "no_capacity_effect"),
        (_contrast(-1, -2, -0.2), _contrast(-1, -2, -0.2), _contrast(-2, -3, -1), "operational", True, "capacity_effect_adverse"),
        (_contrast(0, 0, 0), _contrast(0, 0, 0), _contrast(0, 0, 0), "degenerate", True, "not_operational"),
        (_contrast(0, 0, 0), _contrast(0, 0, 0), _contrast(0, 0, 0), "operational", False, "invalid"),
    ],
)
def test_monotonicity_branches(
    low_central: dict[str, object],
    central_high: dict[str, object],
    low_high: dict[str, object],
    operationality: str,
    valid: bool,
    expected: str,
) -> None:
    assert (
        d.classify_monotonicity(
            low_central,
            central_high,
            low_high,
            operationality=operationality,
            valid=valid,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("statuses", "valid", "expected"),
    [
        (["capacity_relief_supported"] * 3, True, "supported"),
        (["capacity_relief_supported", "capacity_relief_partial", "capacity_relief_partial"], True, "partially_supported"),
        (["capacity_relief_not_supported"] * 3, True, "not_supported"),
        (["capacity_not_binding"] * 3, True, "not_operational"),
        (["capacity_relief_supported"] * 3, False, "invalid"),
    ],
)
def test_d1_branches(
    statuses: list[str], valid: bool, expected: str
) -> None:
    payload = {
        str(index): {"classification": value}
        for index, value in enumerate(statuses)
    }
    assert d.classify_d1(payload, valid=valid) == expected


@pytest.mark.parametrize(
    ("mode", "valid", "expected"),
    [
        ("present", True, "shared_capacity_transmission_present"),
        ("mixed", True, "shared_capacity_transmission_mixed"),
        ("not_present", True, "shared_capacity_transmission_not_present"),
        ("not_binding", True, "shared_capacity_not_binding"),
        ("present", False, "shared_capacity_transmission_invalid"),
    ],
)
def test_d2_branches(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    valid: bool,
    expected: str,
) -> None:
    first_anchor = "__".join(d.ANCHOR_ORDER[0])

    def fake_lookup(
        _contrasts: pd.DataFrame,
        *,
        contrast_type: str,
        anchor: str,
        metric: str,
        family: str | None = None,
        **_kwargs: object,
    ) -> dict[str, object]:
        if metric == "capacity_rejected_opportunity_count":
            if mode == "not_binding":
                return _contrast(0.0, -1.0, 1.0)
            return _contrast(2.0, 1.0, 3.0)
        full_anchor = mode == "present" or (
            mode == "mixed" and anchor == first_anchor
        )
        if mode == "not_present":
            full_anchor = False
        if metric == "rejected_count":
            return _contrast(
                1.0 if full_anchor and family in {"ETH", "WBTC"} else 0.0,
                -1.0,
                2.0,
            )
        if metric == "cross_family_displacement_hours":
            return _contrast(0.0, -1.0, 1.0)
        if metric == "backlog_area":
            return _contrast(
                2.0 if full_anchor and family == "ETH" else 0.0,
                1.0 if full_anchor and family == "ETH" else -1.0,
                3.0 if full_anchor and family == "ETH" else 1.0,
            )
        raise AssertionError((contrast_type, anchor, metric, family))

    monkeypatch.setattr(d, "_contrast_lookup", fake_lookup)
    assert (
        d.classify_d2(pd.DataFrame(), valid=valid)["classification"]
        == expected
    )


@pytest.mark.parametrize(
    ("mode", "valid", "expected"),
    [
        ("present", True, "peg_friction_effect_present"),
        ("partial", True, "peg_friction_effect_partial"),
        ("unchanged", True, "peg_unchanged"),
        ("mixed", True, "peg_response_mixed"),
        ("not_operational", True, "peg_not_operational"),
        ("present", False, "peg_response_invalid"),
    ],
)
def test_d3_branches(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    valid: bool,
    expected: str,
) -> None:
    first_anchor = "__".join(d.ANCHOR_ORDER[0])

    def fake_lookup(
        _contrasts: pd.DataFrame,
        *,
        anchor: str,
        metric: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        if mode == "not_operational":
            return _contrast(
                0.0, 0.0, 0.0, operationality="degenerate"
            )
        if mode == "present":
            return _contrast(1.0, 0.5, 1.5)
        if mode == "partial" and anchor == first_anchor:
            return _contrast(1.0, 0.5, 1.5)
        if mode == "mixed" and metric == d.PEG_METRICS[0]:
            return _contrast(-1.0, -1.5, -0.5)
        return _contrast(0.0, -0.5, 0.5)

    monkeypatch.setattr(d, "_contrast_lookup", fake_lookup)
    assert (
        d.classify_d3(pd.DataFrame(), valid=valid)["classification"]
        == expected
    )


@pytest.mark.parametrize(
    ("d1", "d2", "d3", "valid", "expected"),
    [
        ("supported", "shared_capacity_transmission_present", "peg_friction_effect_present", True, "H1_shared_capacity_supported"),
        ("partially_supported", "shared_capacity_transmission_mixed", "peg_unchanged", True, "H1_shared_capacity_partially_supported"),
        ("partially_supported", "shared_capacity_transmission_not_present", "peg_friction_effect_partial", True, "H1_shared_capacity_backlog_effect_only"),
        ("not_supported", "shared_capacity_transmission_not_present", "peg_unchanged", True, "H1_no_clear_shared_capacity_effect"),
        ("not_operational", "shared_capacity_not_binding", "peg_not_operational", True, "H1_shared_capacity_not_operational"),
        ("supported", "shared_capacity_transmission_invalid", "peg_unchanged", True, "H1_shared_capacity_experiment_invalid"),
        ("supported", "shared_capacity_transmission_present", "peg_unchanged", False, "H1_shared_capacity_experiment_invalid"),
    ],
)
def test_overall_h1_branches(
    d1: str,
    d2: str,
    d3: str,
    valid: bool,
    expected: str,
) -> None:
    assert d.classify_overall_h1(d1, d2, d3, valid=valid) == expected


@pytest.mark.parametrize(
    ("d1", "d3", "valid", "expected"),
    [
        ("supported", "peg_friction_effect_present", True, "solvency_and_peg_improve_with_capacity"),
        ("supported", "peg_unchanged", True, "solvency_improves_peg_unchanged"),
        ("not_supported", "peg_friction_effect_partial", True, "peg_improves_solvency_unchanged"),
        ("supported", "peg_response_mixed", True, "solvency_and_peg_diverge"),
        ("not_supported", "peg_unchanged", True, "neither_materially_changes"),
        ("supported", "peg_unchanged", False, "relationship_invalid"),
    ],
)
def test_peg_solvency_branches(
    d1: str, d3: str, valid: bool, expected: str
) -> None:
    assert d.classify_peg_solvency(d1, d3, valid=valid) == expected


def test_direction_normalisation_reverses_higher_is_better_metrics() -> None:
    assert d.METRIC_DIRECTIONS["backlog_area_share"] == 1
    assert d.METRIC_DIRECTIONS["liquidation_completion_ratio"] == -1
    assert d.METRIC_DIRECTIONS["minimum_dai_price"] == -1


def test_zero_denominator_completion_and_rejection_are_not_applicable() -> None:
    assert d._distribution([])["mean"] != d._distribution([])["mean"]
    decision = d._demand_decision(
        step=0,
        inventory=0,
        uniform=0.0,
        positive_count=20,
        hurdle_probability=1.0,
        capacity=14,
    )
    assert decision.bounded_demand == 0
    assert decision.attempt_budget == 0


def test_specification_excludes_selection_and_held_out_data() -> None:
    payload = d.specification_payload(load_programme().programme_identity)
    assert payload["substantive_simulations"] == 1_152
    assert payload["capacity_selection_permitted"] is False
    assert payload["held_out_data_used"] is False
    assert payload["usdc_svb_used"] is False
    assert payload["experiment_e_executed"] is False
    assert payload["runtime_adopted"] is False


def test_experiment_d_output_path_is_semantic_final_namespace() -> None:
    identity = d.experiment_identity(load_programme().programme_identity)
    assert d._output_dir(load_programme().programme_identity) == (
        d.REPOSITORY_ROOT
        / "outputs/experiments/final/shared_keeper_capacity"
        / identity
    )
    assert "mechanism" not in d._output_dir(
        load_programme().programme_identity
    ).parts


def test_preregistered_evidence_names_are_exact() -> None:
    assert len(d.COMPACT_FILENAMES) == 8
    assert d.COMPACT_FILENAMES[0] == (
        "shared_keeper_capacity_specification.json"
    )
    assert d.COMPACT_FILENAMES[-1] == (
        "shared_keeper_capacity_benchmark.json"
    )


def test_master_programme_and_prior_identities_are_frozen() -> None:
    assert load_programme().programme_identity == d.MASTER_PROGRAMME_IDENTITY
    assert d.EXPERIMENT_A_IDENTITY == (
        "a9d7c3fa5dc5da9bcf61314a57501ea5a8be506e305eee6f45afaae3131600bb"
    )
    assert d.EXPERIMENT_B_IDENTITY == (
        "e02c035162f8178c96d2cae71d0a581ce813ab33526854bd5810e8e2810ead83"
    )
    assert d.EXPERIMENT_C_IDENTITY == (
        "cb6d00877c54011cc49714bdfe23fad83140fef001568ea9b43d355811c9129b"
    )


def test_registered_keeper_checksum_and_coordinates_are_frozen() -> None:
    assert d.KEEPER_REGISTRY_SHA256 == (
        "58c5754ed95dead1ad283a7961fb0588496804a94f58ddb0e196a57601ee1e1b"
    )
    assert d.CAPACITY_ORDER == (14, 26, 45)
    payload = json.loads(
        (
            d.REPOSITORY_ROOT
            / "data/provenance/calibration/keeper/"
            "keeper_execution_decision.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["capacity"]["classification"] == (
        "shared_capacity_partially_identified"
    )


def test_queue_records_preserve_rank_order() -> None:
    frame = pd.DataFrame(
        [
            {
                "candidate_rank": 1,
                "vault_id": 9,
                "collateral_type": "ETH",
                "debt_at_risk": 10.0,
                "expected_profit": 1.0,
            },
            {
                "candidate_rank": 2,
                "vault_id": 4,
                "collateral_type": "BTC",
                "debt_at_risk": 9.0,
                "expected_profit": 0.5,
            },
        ]
    )
    assert [row["vault_id"] for row in d._queue_records(frame)] == [9, 4]


def test_real_replication_preserves_capacity_only_pairing(
    smoke_replication: dict[str, object],
) -> None:
    rows = pd.DataFrame(smoke_replication["cell_rows"])
    assert len(rows) == 9
    assert rows["capacity"].tolist() == [14, 26, 45] * 3
    for _, anchor in rows.groupby("anchor", sort=False):
        for column in (
            "paired_stream_checksum",
            "state_checksum",
            "gas_unit_draw_checksum",
            "gas_component_checksum",
            "price_path_checksum",
        ):
            assert anchor[column].nunique() == 1


def test_real_replication_passes_queue_crn_and_ranking_audits(
    smoke_replication: dict[str, object],
) -> None:
    anchor_audits = smoke_replication["anchor_audits"]
    assert set(anchor_audits) == {
        "__".join(anchor) for anchor in d.ANCHOR_ORDER
    }
    for audit in anchor_audits.values():
        assert audit["common_random_numbers_valid"] is True
        assert audit["ranking_owner_invariant"] is True
        assert len(set(audit["capacity_neutral_owner_checksums"].values())) == 1


def test_real_replication_passes_accounting_and_capacity_gates(
    smoke_replication: dict[str, object],
) -> None:
    rows = pd.DataFrame(smoke_replication["cell_rows"])
    assert rows["accounting_valid"].all()
    assert rows["numerical_valid"].all()
    assert rows["shared_capacity_valid"].all()
    assert not rows["duplicate_attempt"].any()
    assert not rows["duplicate_closure"].any()
    assert (rows["maximum_capacity_utilisation"] <= 1.0).all()
    assert (rows["capacity_rejected_opportunity_count"] >= 0).all()


def test_completed_evidence_retains_scientific_boundaries() -> None:
    validation = d.validate_evidence(load_programme().programme_identity)
    assert validation["passed"] is True
    assert validation["experiments_a_b_c_unchanged"] is True
    assert validation["experiment_e_unexecuted"] is True
    assert validation["capacity_selected"] is False
    assert validation["runtime_adopted"] is False


def test_evidence_serialisation_rejects_unsupported_objects() -> None:
    with pytest.raises(TypeError):
        d._pretty_json({"unsupported": object()})
