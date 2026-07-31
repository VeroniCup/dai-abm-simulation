"""Focused gates for the pre-registered final Experiment E oracle-delay study."""

from __future__ import annotations

import numpy as np
import pytest

from dai_sim.experiments.final import oracle_delay as experiment
from dai_sim.experiments.final.programme import load_programme


def _record(mean: float, lower: float, upper: float) -> dict[str, float]:
    return {"mean": mean, "ci95_lower": lower, "ci95_upper": upper}


def test_registry_consumes_exact_six_frozen_master_rows() -> None:
    cells = experiment.build_cell_registry(load_programme())
    assert len(cells) == 6
    assert tuple(cell.identifier for cell in cells) == experiment.CELL_ORDER
    assert tuple(cell.delay_steps for cell in cells) == (0, 1, 2, 0, 1, 2)
    assert {cell.capacity for cell in cells} == {26}
    assert {cell.hurdle for cell in cells} == {"direct_cost_only"}
    assert {cell.confidence for cell in cells} == {"stage1_only"}
    assert {cell.replication_count for cell in cells} == {128}


def test_specification_keeps_transparent_sensitivity_dormant() -> None:
    payload = experiment.specification_payload(experiment.MASTER_PROGRAMME_IDENTITY)
    assert (
        payload["scientific_classification"]
        == "transparent_sensitivity_not_empirically_identified"
    )
    assert payload["runtime_adopted"] is False
    assert payload["delay_selection_permitted"] is False
    assert payload["substantive_simulations"] == 768


@pytest.mark.parametrize("delay", (0, 1, 2))
def test_oracle_paths_apply_exact_global_shift(delay: int) -> None:
    paths = {
        "ETH": np.arange(1.0, 769.0),
        "BTC": np.arange(1001.0, 1769.0),
        "STABLE": np.linspace(1.0, 1.1, 768),
    }
    oracle, audit = experiment.build_oracle_paths(paths, delay)
    for family, market in paths.items():
        if delay == 0:
            expected = market
        else:
            expected = np.concatenate((np.repeat(market[0], delay), market[:-delay]))
        np.testing.assert_array_equal(oracle[family], expected)
        np.testing.assert_array_equal(paths[family], market)
    assert audit["passed"]
    assert audit["initial_price_repetition"]
    assert audit["no_interpolation"]
    assert audit["global_family_scope"]


def test_oracle_paths_do_not_leak_across_families_and_are_deterministic() -> None:
    paths = {
        "ETH": np.full(768, 2.0),
        "BTC": np.full(768, 3.0),
        "STABLE": np.full(768, 4.0),
    }
    first, first_audit = experiment.build_oracle_paths(paths, 2)
    second, second_audit = experiment.build_oracle_paths(paths, 2)
    assert first_audit["combined_checksum"] == second_audit["combined_checksum"]
    assert set(np.unique(first["ETH"])) == {2.0}
    assert set(np.unique(first["BTC"])) == {3.0}
    assert set(np.unique(first["STABLE"])) == {4.0}


def test_mismatch_gap_signs_and_frozen_debt_weighting() -> None:
    market = {
        "ETH": np.full(768, 1.0),
        "BTC": np.full(768, 2.0),
        "STABLE": np.full(768, 1.0),
    }
    oracle = {
        "ETH": np.full(768, 2.0),
        "BTC": np.full(768, 1.0),
        "STABLE": np.full(768, 1.0),
    }
    debt = {"ETH": 1_250_000.0, "WBTC": 1_250_000.0, "STABLE": 0.0}
    system, families = experiment.mismatch_diagnostics(market, oracle, debt)
    assert families["ETH"]["oracle_overvaluation_area"] == pytest.approx(
        768 * np.log(2.0)
    )
    assert families["WBTC"]["oracle_undervaluation_area"] == pytest.approx(
        768 * np.log(2.0)
    )
    assert system["debt_weighted_absolute_mismatch_area"] == pytest.approx(
        768 * np.log(2.0)
    )


def test_zero_delay_mismatch_is_structural_zero() -> None:
    market = {family: np.linspace(1.0, 2.0, 768) for family in ("ETH", "BTC", "STABLE")}
    system, families = experiment.mismatch_diagnostics(
        market,
        market,
        {"ETH": 1_000_000.0, "WBTC": 1_000_000.0, "STABLE": 500_000.0},
    )
    assert all(value == 0.0 for value in system.values())
    assert all(row["mismatch_hours_above_tolerance"] == 0 for row in families.values())


@pytest.mark.parametrize(
    ("market", "oracle", "expected"),
    (
        (True, False, "false_safe"),
        (False, True, "false_unsafe"),
        (True, True, "jointly_unsafe"),
        (False, False, "jointly_safe"),
    ),
)
def test_safety_state_is_diagnostic_only(
    market: bool, oracle: bool, expected: str
) -> None:
    assert (
        experiment.classify_safety_state(market_unsafe=market, oracle_unsafe=oracle)
        == expected
    )


def test_event_lag_preserves_not_applicable_cases() -> None:
    assert experiment.event_lag(10, 12) == 2.0
    assert experiment.event_lag(None, 12) is None
    assert experiment.event_lag(10, None) is None


@pytest.mark.parametrize(
    ("records", "expected"),
    (
        (
            ((1.0, 0.2, 1.8), (1.0, 0.2, 1.8), (2.0, 1.0, 3.0)),
            "monotonic_deterioration",
        ),
        (
            ((0.0, -0.2, 0.2), (2.0, 1.0, 3.0), (2.0, 1.0, 3.0)),
            "threshold_deterioration",
        ),
        (
            ((-1.0, -2.0, -0.2), (3.0, 2.0, 4.0), (2.0, 1.0, 3.0)),
            "non_monotonic_deterioration",
        ),
        (((0.0, -1.0, 1.0), (0.0, -1.0, 1.0), (0.0, -1.0, 1.0)), "no_delay_effect"),
        (
            ((-1.0, -2.0, -0.2), (-1.0, -2.0, -0.2), (-2.0, -3.0, -1.0)),
            "countervailing_delay_benefit",
        ),
    ),
)
def test_response_shape_branches(
    records: tuple[tuple[float, float, float], ...], expected: str
) -> None:
    first, second, total = (_record(*values) for values in records)
    assert (
        experiment.classify_response_shape(
            first, second, total, operationality="operational"
        )
        == expected
    )


def test_response_shape_not_operational_and_invalid() -> None:
    record = _record(0.0, -1.0, 1.0)
    assert (
        experiment.classify_response_shape(
            record, record, record, operationality="degenerate"
        )
        == "not_operational"
    )
    assert (
        experiment.classify_response_shape(
            record, record, record, operationality="operational", valid=False
        )
        == "invalid"
    )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    (
        ((True, True), "supported"),
        ((True, False), "partially_supported"),
        ((False, False), "not_supported"),
        ((None, None), "not_operational"),
    ),
)
def test_e1_hierarchy(statuses: tuple[bool | None, bool | None], expected: str) -> None:
    assert experiment.classify_e1({"a": statuses[0], "b": statuses[1]}) == expected


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    (
        (
            {
                "adverse_count": 2,
                "beneficial_count": 0,
                "timing_changed": True,
                "operational_count": 4,
            },
            "delay_friction_supported",
        ),
        (
            {
                "adverse_count": 1,
                "beneficial_count": 0,
                "timing_changed": True,
                "operational_count": 4,
            },
            "delay_friction_partial",
        ),
        (
            {
                "adverse_count": 0,
                "beneficial_count": 0,
                "timing_changed": True,
                "operational_count": 4,
            },
            "timing_shift_without_net_deterioration",
        ),
        (
            {
                "adverse_count": 0,
                "beneficial_count": 1,
                "timing_changed": True,
                "operational_count": 4,
            },
            "countervailing_delay_benefit",
        ),
        (
            {
                "adverse_count": 0,
                "beneficial_count": 0,
                "timing_changed": False,
                "operational_count": 4,
            },
            "no_downstream_delay_effect",
        ),
        (
            {
                "adverse_count": 0,
                "beneficial_count": 0,
                "timing_changed": False,
                "operational_count": 0,
            },
            "not_operational",
        ),
    ),
)
def test_e2_anchor_hierarchy(kwargs: dict[str, object], expected: str) -> None:
    assert experiment.classify_e2_anchor(**kwargs) == expected


@pytest.mark.parametrize(
    ("e1", "e2", "e3", "expected"),
    (
        (
            "supported",
            "supported",
            "peg_delay_effect_present",
            "H2_oracle_delay_supported",
        ),
        (
            "supported",
            "partially_supported",
            "peg_unchanged",
            "H2_oracle_delay_partially_supported",
        ),
        (
            "supported",
            "not_supported",
            "peg_unchanged",
            "H2_oracle_mismatch_effect_only",
        ),
        (
            "supported",
            "countervailing_effect",
            "peg_unchanged",
            "H2_oracle_delay_countervailing_effect",
        ),
        (
            "not_supported",
            "not_supported",
            "peg_unchanged",
            "H2_no_clear_oracle_delay_effect",
        ),
        (
            "not_operational",
            "not_operational",
            "peg_not_operational",
            "H2_oracle_delay_not_operational",
        ),
    ),
)
def test_overall_h2_hierarchy(e1: str, e2: str, e3: str, expected: str) -> None:
    assert experiment.classify_overall_h2(e1, e2, e3) == expected


def test_invalid_overall_h2_has_priority() -> None:
    assert (
        experiment.classify_overall_h2(
            "supported", "supported", "peg_delay_effect_present", valid=False
        )
        == "H2_oracle_delay_experiment_invalid"
    )


def test_output_path_uses_final_oracle_delay_taxonomy() -> None:
    relative = experiment.OUTPUT_ROOT.relative_to(experiment.REPOSITORY_ROOT).as_posix()
    assert relative == "outputs/experiments/final/oracle_delay"


def test_compact_evidence_contract_is_exactly_eight_files() -> None:
    assert len(experiment.COMPACT_FILENAMES) == 8
    assert experiment.COMPACT_FILENAMES[0] == "oracle_delay_specification.json"
    assert experiment.COMPACT_FILENAMES[-1] == "oracle_delay_benchmark.json"
