"""Substantive tests for the pre-registered ETH recovery experiment."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import runpy

import numpy as np
import pandas as pd
import pytest

from dai_sim.inputs.confidence_scenarios import EXPECTED_SCENARIO_ORDER
from dai_sim.experiments.final import stable_collateral_tradeoff as experiment_c
from dai_sim.experiments.mechanism.eth_recovery import (
    CONFIDENCE_CONTRASTS,
    PATH_ORDER,
    PRIMARY_METRICS,
    RECOVERY_CONTRASTS,
    SUMMARY_METRICS,
    _recovery_metrics,
    build_cell_registry,
    build_eth_path,
    classify_experiment,
    derive_recovery_seed,
    experiment_identity,
    interaction_contrasts,
    load_recovery_design,
    paired_contrasts,
    path_checksum,
    replication_seed_record,
    seed_registry_checksum,
    smoothstep,
    validate_evidence,
)
from dai_sim.experiments.mechanism.output_paths import (
    MechanismOutputMigrationRequiredError,
    canonical_mechanism_output_root,
    resolve_mechanism_output_root,
)


def _design():
    return replace(
        load_recovery_design(),
        output_root=resolve_mechanism_output_root("eth_recovery"),
    )


def _paths():
    design = _design()
    return {
        definition.identifier: build_eth_path(design, definition)
        for definition in design.path_definitions
    }


def _synthetic_frame() -> pd.DataFrame:
    rows = []
    path_effect = {
        "persistent_trough": 4.0,
        "partial_week": 3.0,
        "full_week": 2.0,
        "rapid_full": 1.0,
    }
    for path_identifier in PATH_ORDER:
        for scenario_index, scenario in enumerate(EXPECTED_SCENARIO_ORDER):
            for replication in range(8):
                base = path_effect[path_identifier] + scenario_index * 0.1
                row = {
                    "recovery_path": path_identifier,
                    "confidence_scenario": scenario,
                    "replication": replication,
                    "numerical_valid": True,
                    "right_censored": 0,
                }
                for metric in SUMMARY_METRICS:
                    row[metric] = (
                        1.0 - base * 0.01
                        if metric in {
                            "final_dai_price",
                            "minimum_dai_price",
                            "confidence_at_horizon",
                            "minimum_confidence",
                        }
                        else float(base + replication * 0.001)
                    )
                for metric in (
                    "recovery_probability_48h",
                    "recovery_probability_168h",
                    "recovery_probability_336h",
                    "recovery_probability_720h",
                    "final_peg_band_status",
                ):
                    row[metric] = int(path_identifier != "persistent_trough")
                rows.append(row)
    return pd.DataFrame(rows)


def test_design_has_exact_authoritative_boundaries(tmp_path: Path) -> None:
    design = _design()
    assert design.baseline_path.name == "legacy.yaml"
    assert design.pre_shock_price == 2000.0
    assert design.trough_price == 1140.0
    assert design.shock_hour == 48
    assert design.post_shock_hours == 720
    assert design.total_hours == 768
    assert design.replications == 128
    assert design.output_root == (
        Path(__file__).resolve().parents[3]
        / "outputs/experiments/mechanism/eth_recovery"
    )
    paths = {
        definition.identifier: build_eth_path(design, definition)
        for definition in design.path_definitions
    }
    cells = build_cell_registry(design, paths)
    identity = experiment_identity(design, cells)
    assert identity == (
        "68afcef1166bb6b13813d0e481ce7bddff7605c0ac7326bf8b9d1400eacff20b"
    )
    assert experiment_identity(
        replace(design, output_root=tmp_path / "relocated"),
        cells,
    ) == identity

    for family in ("eth_recovery", "constrained_eth_recovery"):
        clean_root = tmp_path / f"clean-{family}"
        assert canonical_mechanism_output_root(
            family,
            repository_root=clean_root,
        ) == clean_root / "outputs/experiments/mechanism" / family
        old_only_root = tmp_path / f"old-only-{family}"
        legacy = old_only_root / "outputs/experiments" / family
        legacy.mkdir(parents=True)
        with pytest.raises(
            MechanismOutputMigrationRequiredError,
            match="automatic migration is disabled",
        ):
            resolve_mechanism_output_root(
                family,
                repository_root=old_only_root,
            )
        assert not (
            old_only_root / "outputs/experiments/mechanism" / family
        ).exists()

    assert experiment_c.OUTPUT_ROOT == (
        Path(__file__).resolve().parents[3]
        / "outputs/experiments/final/stable_collateral_tradeoff"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, 0.0), (0.25, 0.15625), (0.5, 0.5), (0.75, 0.84375), (1.0, 1.0)],
)
def test_cubic_smoothstep_is_exact(value: float, expected: float) -> None:
    assert smoothstep(value) == expected


def test_paths_have_identical_pre_shock_and_trough() -> None:
    design = _design()
    paths = _paths()
    assert all(
        np.array_equal(path[:48], np.full(48, 2000.0))
        for path in paths.values()
    )
    assert {path[48] for path in paths.values()} == {1140.0}


@pytest.mark.parametrize("identifier", PATH_ORDER)
def test_paths_are_monotone_finite_and_have_no_overshoot(identifier: str) -> None:
    path = _paths()[identifier]
    assert np.isfinite(path).all()
    assert (path > 0).all()
    assert (np.diff(path[48:]) >= -1e-12).all()
    assert path.max() <= 2000.0


def test_recovery_path_endpoints_are_exact() -> None:
    paths = _paths()
    expected_partial = np.exp(
        np.log(1140.0) + 0.5 * (np.log(2000.0) - np.log(1140.0))
    )
    assert np.all(paths["persistent_trough"][48:] == 1140.0)
    assert paths["partial_week"][48 + 168] == pytest.approx(expected_partial)
    assert paths["full_week"][48 + 168] == pytest.approx(2000.0)
    assert paths["rapid_full"][48 + 48] == pytest.approx(2000.0)


def test_path_checksums_are_deterministic_and_unique() -> None:
    first = {name: path_checksum(path) for name, path in _paths().items()}
    second = {name: path_checksum(path) for name, path in _paths().items()}
    assert first == second
    assert len(set(first.values())) == 4


def test_cell_registry_is_exact_and_path_first() -> None:
    design = _design()
    cells = build_cell_registry(design, _paths())
    assert len(cells) == 16
    assert [cell.order for cell in cells] == list(range(1, 17))
    assert [cell.identifier for cell in cells[:4]] == [
        f"persistent_trough__{scenario}" for scenario in EXPECTED_SCENARIO_ORDER
    ]
    assert cells[-1].identifier == "rapid_full__confidence_fragile"
    assert len({cell.identifier for cell in cells}) == 16


def test_seed_ownership_is_treatment_invariant_and_stream_specific() -> None:
    record = replication_seed_record(7)
    assert record == replication_seed_record(7)
    assert len(
        {
            record["vault_sampling_seed"],
            record["market_innovations_seed"],
            record["liquidation_randomness_seed"],
        }
    ) == 3
    assert record != replication_seed_record(8)


def test_seed_registry_is_deterministic() -> None:
    assert seed_registry_checksum(128) == seed_registry_checksum(128)
    assert seed_registry_checksum(128) != seed_registry_checksum(127)
    with pytest.raises(ValueError, match="Unknown"):
        derive_recovery_seed(0, "treatment")


def test_sustained_recovery_requires_24_hours_and_resets() -> None:
    design = _design()
    prices = np.full(720, 0.99)
    prices[1:11] = 1.0
    prices[12:36] = 1.0
    metrics = _recovery_metrics(prices, design=design)
    assert metrics["first_return_time"] == 1
    assert metrics["failed_recovery_attempts"] == 1
    assert metrics["sustained_recovery_time"] == 36
    assert metrics["recovery_probability_48h"] == 1


def test_no_exit_is_recovered_at_zero() -> None:
    metrics = _recovery_metrics(np.ones(720), design=_design())
    assert metrics["sustained_recovery_time"] == 0
    assert metrics["restricted_mean_recovery_time"] == 0
    assert metrics["right_censored"] == 0


def test_no_recovery_uses_720_hour_restriction() -> None:
    metrics = _recovery_metrics(np.full(720, 0.99), design=_design())
    assert metrics["restricted_mean_recovery_time"] == 720
    assert metrics["right_censored"] == 1
    assert metrics["recovery_probability_720h"] == 0


def test_primary_metric_registry_is_not_scalarised() -> None:
    assert PRIMARY_METRICS == (
        "below_peg_burden",
        "restricted_mean_recovery_time",
        "recovery_probability_168h",
        "recovery_probability_720h",
        "maximum_unresolved_tab_dai",
        "cumulative_realised_bad_debt_dai",
    )
    assert "score" not in " ".join(SUMMARY_METRICS)


def test_fixed_contrast_registries_use_stage1_reference() -> None:
    assert len(RECOVERY_CONTRASTS) == 5
    assert CONFIDENCE_CONTRASTS == (
        ("confidence_resilient", "stage1_only"),
        ("confidence_central", "stage1_only"),
        ("confidence_fragile", "stage1_only"),
    )


def test_paired_contrasts_are_replication_level_and_complete() -> None:
    contrasts = paired_contrasts(_synthetic_frame())
    expected = (
        4 * len(RECOVERY_CONTRASTS)
        + 4 * len(CONFIDENCE_CONTRASTS)
    ) * len(SUMMARY_METRICS)
    assert len(contrasts) == expected
    row = contrasts.loc[
        contrasts["contrast"].eq(
            "full_week - persistent_trough | stage1_only"
        )
        & contrasts["metric"].eq("below_peg_burden")
    ].iloc[0]
    assert row["paired_estimate"] == pytest.approx(-2.0)
    assert bool(row["support_flag"])


def test_binary_contrast_reports_discordant_pairs() -> None:
    contrasts = paired_contrasts(_synthetic_frame())
    row = contrasts.loc[
        contrasts["contrast"].eq(
            "full_week - persistent_trough | stage1_only"
        )
        & contrasts["metric"].eq("recovery_probability_720h")
    ].iloc[0]
    assert row["discordant_positive_count"] == 8
    assert row["discordant_negative_count"] == 0


def test_interactions_have_exact_active_path_metric_grid() -> None:
    interactions = interaction_contrasts(_synthetic_frame())
    assert len(interactions) == 3 * 3 * len(SUMMARY_METRICS)
    assert set(interactions["confidence_scenario"]) == set(
        EXPECTED_SCENARIO_ORDER[1:]
    )
    assert set(interactions["recovery_path"]) == set(PATH_ORDER[1:])
    assert not interactions.loc[
        interactions["difference_in_differences"].abs().lt(1e-12),
        "material_interaction_flag",
    ].any()


def test_classification_invalidates_crn_or_numerical_failure() -> None:
    frame = _synthetic_frame()
    contrasts = paired_contrasts(frame)
    interactions = interaction_contrasts(frame)
    assert (
        classify_experiment(
            contrasts, interactions, frame, crn_valid=False
        )["overall_classification"]
        == "eth_recovery_experiment_invalid"
    )
    frame.loc[
        frame["recovery_path"].eq("full_week")
        & frame["confidence_scenario"].eq("stage1_only"),
        "numerical_valid",
    ] = False
    assert (
        classify_experiment(contrasts, interactions, frame)[
            "overall_classification"
        ]
        == "eth_recovery_experiment_invalid"
    )


def test_classification_never_ranks_a_confidence_scenario() -> None:
    frame = _synthetic_frame()
    decision = classify_experiment(
        paired_contrasts(frame),
        interaction_contrasts(frame),
        frame,
    )
    assert "rank" not in " ".join(decision).lower()
    assert decision["H4a"] in {"supported", "not_supported"}
    assert decision["H4b"] in {"supported", "not_supported"}
    assert decision["H4c"] in {"present", "not_present"}


def _classification_contrasts(
    *,
    supporting_scenarios: int,
    opposite_solvency: bool = False,
) -> pd.DataFrame:
    rows = []
    for index, scenario in enumerate(EXPECTED_SCENARIO_ORDER):
        supported = index < supporting_scenarios
        for metric in ("below_peg_burden", "restricted_mean_recovery_time"):
            rows.append(
                {
                    "contrast_family": "recovery_path",
                    "contrast": f"full_week - persistent_trough | {scenario}",
                    "metric": metric,
                    "support_flag": supported,
                    "ci_lower": -2.0 if supported else -0.5,
                    "ci_upper": -1.0 if supported else 0.5,
                    "expected_direction_flag": supported,
                }
            )
            rows.append(
                {
                    "contrast_family": "recovery_path",
                    "contrast": f"rapid_full - full_week | {scenario}",
                    "metric": metric,
                    "support_flag": supported,
                    "ci_lower": -2.0 if supported else -0.5,
                    "ci_upper": -1.0 if supported else 0.5,
                    "expected_direction_flag": supported,
                }
            )
        for metric in (
            "maximum_unresolved_tab_dai",
            "cumulative_realised_bad_debt_dai",
        ):
            rows.append(
                {
                    "contrast_family": "recovery_path",
                    "contrast": f"full_week - persistent_trough | {scenario}",
                    "metric": metric,
                    "support_flag": False,
                    "ci_lower": 1.0 if opposite_solvency else -0.5,
                    "ci_upper": 2.0 if opposite_solvency else 0.5,
                    "expected_direction_flag": False,
                }
            )
    return pd.DataFrame(rows)


@pytest.mark.parametrize(
    ("supporting", "opposite_solvency", "interaction", "expected"),
    [
        (4, False, False, "collateral_recovery_robustly_improves_peg"),
        (2, False, True, "collateral_recovery_effect_confidence_dependent"),
        (4, True, False, "recovery_path_improves_price_but_not_solvency"),
        (0, False, False, "no_clear_recovery_path_effect"),
    ],
)
def test_every_valid_overall_classification_is_reachable(
    supporting: int,
    opposite_solvency: bool,
    interaction: bool,
    expected: str,
) -> None:
    interactions = pd.DataFrame(
        {
            "metric": ["below_peg_burden"],
            "material_interaction_flag": [interaction],
        }
    )
    result = classify_experiment(
        _classification_contrasts(
            supporting_scenarios=supporting,
            opposite_solvency=opposite_solvency,
        ),
        interactions,
        _synthetic_frame(),
    )
    assert result["overall_classification"] == expected


def test_h4_subclassifications_follow_registered_rules() -> None:
    result = classify_experiment(
        _classification_contrasts(supporting_scenarios=4),
        pd.DataFrame(
            {
                "metric": ["restricted_mean_recovery_time"],
                "material_interaction_flag": [True],
            }
        ),
        _synthetic_frame(),
    )
    assert result["H4a"] == "supported"
    assert result["H4b"] == "supported"
    assert result["H4c"] == "present"


def test_completed_evidence_has_exact_boundary_and_manifest_registration() -> None:
    result = validate_evidence()
    assert result["cell_count"] == 16
    assert result["metric_rows"] == 16 * len(SUMMARY_METRICS)
    assert result["manifest_records"] == 9
    assert result["runtime_adopted"] is False


def test_configuration_contains_no_forbidden_cross_or_fifth_treatment() -> None:
    text = _design().config_path.read_text(encoding="utf-8")
    assert text.count("identifier:") == 4
    for forbidden in ("USDC", "SVB", "registry_b", "multi_collateral"):
        assert forbidden not in text


def test_production_default_remains_stage1_only() -> None:
    confidence_registry = (
        Path(__file__).resolve().parents[3]
        / "config/sensitivities/confidence_scenarios.yaml"
    )
    payload = confidence_registry.read_text(encoding="utf-8")
    assert "identifier: stage1_only" in payload
    assert "enabled: false" in payload


def test_workflow_exposes_only_registered_recovery_operations() -> None:
    workflow = (
        Path(__file__).resolve().parents[3]
        / "workflows/experiments/mechanism/eth_recovery.py"
    ).read_text(encoding="utf-8")
    for operation in (
        "validate-inputs",
        "build-paths",
        "validate-registry",
        "run-smoke",
        "run-full",
        "resume",
        "aggregate",
        "validate-completed",
        "reconstruct-evidence",
    ):
        assert operation in workflow
    for forbidden in ("USDC", "SVB", "scenario-ranking", "registry-b"):
        assert forbidden not in workflow
    assert 'resolve_mechanism_output_root("eth_recovery")' in workflow


def test_reconstruction_preserves_existing_measured_benchmark(
    tmp_path: Path,
) -> None:
    workflow_path = (
        Path(__file__).resolve().parents[3]
        / "workflows/experiments/mechanism/eth_recovery.py"
    )
    resolve = runpy.run_path(str(workflow_path))["_resolve_benchmark"]
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    expected = {
        "worker_count": 4,
        "completed_simulations": 2048,
        "wall_time_seconds": 56.25,
        "output_size_bytes": 55_000_000,
        "host_dependent": True,
    }
    (evidence_dir / "eth_recovery_benchmark.json").write_text(
        json.dumps(expected),
        encoding="utf-8",
    )

    observed = resolve(
        operation="reconstruct-evidence",
        benchmark_json=None,
        evidence_dir=evidence_dir,
        workers=1,
    )

    assert observed == expected
