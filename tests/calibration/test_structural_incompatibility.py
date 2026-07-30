"""Tests for the objective-blind structural incompatibility diagnosis."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from dai_sim.calibration import structural_incompatibility as structural
from dai_sim.calibration import simulated_moments_search as search


def test_signed_band_gap_preserves_direction() -> None:
    assert structural.signed_band_gap(0.5, 1.0, 2.0) == -0.5
    assert structural.signed_band_gap(1.5, 1.0, 2.0) == 0.0
    assert structural.signed_band_gap(2.5, 1.0, 2.0) == 0.5


def test_interval_location_is_mutually_exclusive() -> None:
    assert structural.interval_location(0.0, 0.9, 1.0, 2.0) == "below"
    assert structural.interval_location(0.0, 1.0, 1.0, 2.0) == "overlap"
    assert structural.interval_location(2.1, 3.0, 1.0, 2.0) == "above"


@pytest.mark.parametrize(
    ("below", "above", "inside", "inner", "hard", "expected"),
    [
        (90, 0, 0, 0, 0, "systematically_below_band"),
        (0, 90, 0, 0, 0, "systematically_above_band"),
        (25, 25, 0, 0, 0, "mixed_location_mismatch"),
        (0, 0, 25, 0, 0, "overlap_prevented_mainly_by_mc_uncertainty"),
        (0, 0, 0, 0, 25, "hard_gate_dominated"),
        (10, 10, 10, 10, 0, "no_systematic_location_mismatch"),
    ],
)
def test_baseline_mismatch_rules_are_fixed(
    below: int,
    above: int,
    inside: int,
    inner: int,
    hard: int,
    expected: str,
) -> None:
    assert (
        structural.classify_baseline_mismatch(
            candidate_count=100,
            intervals_below=below,
            intervals_above=above,
            means_inside=inside,
            inner_passes=inner,
            otherwise_outer_hard_gate_failures=hard,
        )
        == expected
    )


def test_completed_baseline_decomposition_has_five_ordered_constraints() -> None:
    frame, cofailure = structural.decompose_baseline_mismatch(
        structural._candidates(), structural._constraints()
    )
    assert tuple(frame["moment"]) == structural.STAGE2_ACTIVE_MOMENTS
    assert len(cofailure) == 20
    assert frame.loc[
        frame["moment"].eq("recovery_completion_hours_mean"),
        "baseline_mismatch_classification",
    ].item() == "systematically_above_band"
    assert not any("score" in column for column in frame)


def test_parameter_trends_are_deterministic_and_never_extrapolate() -> None:
    first = structural.parameter_boundary_trends(
        structural._candidates(), structural._constraints()
    )
    second = structural.parameter_boundary_trends(
        structural._candidates().sample(frac=1.0, random_state=8),
        structural._constraints(),
    )
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 20
    assert first["extrapolated_parameter_value"].isna().all()
    assert first["adjacent_bin_monotonic_share"].between(0.0, 1.0).all()


def test_domain_signal_uses_three_moments_and_one_worsening_limit() -> None:
    rows = []
    for index, moment in enumerate(structural.STAGE2_ACTIVE_MOMENTS):
        rows.append(
            {
                "parameter": "panic_response",
                "moment": moment,
                "boundary_signal": index < 3,
                "movement_towards_band_boundary": "low" if index < 3 else "neither",
                "low_boundary_gap_scales": 1.0,
                "high_boundary_gap_scales": 2.0,
            }
        )
    result = structural.parameter_domain_signal(pd.DataFrame(rows))
    assert result["possible"]
    assert result["signals"][0]["boundary"] == "low"


def test_variant_registry_is_one_factor_objective_blind_and_source_owned() -> None:
    registry = structural.build_variant_registry()
    assert registry["variant_count"] == 13
    assert registry["executable_variant_count"] == 12
    assert not registry["objective_used"]
    assert not registry["variant_selected"]
    assert all(item["one_factor_audit"] for item in registry["variants"])
    assert all(item["fit_field"] is None for item in registry["variants"])
    assert all(len(item["unchanged_assumptions"]) == 5 for item in registry["variants"])
    assert all(
        Path(item["evidence_owner"]).exists()
        for item in registry["variants"]
        if item["source_status"] == "available"
    )


def test_historical_gas_is_explicitly_unavailable_before_coverage() -> None:
    registry = structural.build_variant_registry()
    gas = next(
        item for item in registry["variants"]
        if item["variant_id"] == "historical_hourly_gas"
    )
    assert gas["source_status"] == "source_unavailable"
    assert not gas["settings"]["causal_complete"]


def test_vault_snapshot_selection_uses_earliest_timestamp_tie_break() -> None:
    summaries = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(
                ["2022-01-02T00:00:00Z", "2022-01-01T00:00:00Z"], utc=True
            ),
            "source_path": ["b", "a"],
            "state_label": ["opening", "opening"],
            "system_collateral_ratio": [2.0, 2.0],
            "eligible_vault_count": [10, 10],
            "total_debt_dai": [100.0, 100.0],
        }
    )
    result = structural.select_snapshot_percentile(summaries, 0.5)
    assert result["timestamp_utc"].startswith("2022-01-01")


def test_selected_snapshot_distribution_reports_liquidatability() -> None:
    timestamp = pd.Timestamp("2022-01-01T00:00:00Z")
    eligible = pd.DataFrame(
        {
            "timestamp_utc": [timestamp, timestamp],
            "_source_path": ["source.csv", "source.csv"],
            "state_label": ["opening", "opening"],
            "debt_dai": [100.0, 300.0],
            "collateral_ratio": [1.2, 2.0],
            "liquidation_ratio": [1.45, 1.45],
        }
    )
    summary = structural._selected_snapshot_distribution(
        eligible,
        {
            "timestamp_utc": timestamp.isoformat(),
            "source_path": "source.csv",
            "state_label": "opening",
        },
    )
    assert summary["source_initially_liquidatable_count"] == 1
    assert summary["debt_dai"]["p50"] == pytest.approx(200.0)


def test_capacity_and_stress_registry_values_are_exact() -> None:
    registry = structural.build_variant_registry()["variants"]
    capacities = {
        item["settings"]["maximum_liquidations_per_step"]
        for item in registry
        if item["family"] == "liquidation_capacity"
    }
    assert capacities == {5, 10, 20}
    stresses = [
        item["settings"] for item in registry
        if item["family"] == "stress_construction"
    ]
    assert stresses == [
        {"peg_weight": 0.25, "collateral_weight": 0.75},
        {"peg_weight": 0.75, "collateral_weight": 0.25},
    ]
    assert all(sum(item.values()) == 1.0 for item in stresses)


def test_residual_and_gate_variants_do_not_change_baseline_registration() -> None:
    registry = structural.build_variant_registry()["variants"]
    residuals = {
        item["variant_id"]: item["settings"]["mode"]
        for item in registry if item["family"] == "residual_process"
    }
    assert residuals == {
        "residual_zero": "zero",
        "residual_iid_empirical": "iid_empirical",
    }
    gates = {
        item["variant_id"]: item["settings"]
        for item in registry if item["family"] == "recovery_gates"
    }
    assert gates["gate_backlog_only"] == {"backlog": True, "bad_debt": False}
    assert gates["gate_bad_debt_only"] == {"backlog": False, "bad_debt": True}
    assert gates["gate_price_only"] == {"backlog": False, "bad_debt": False}


def _synthetic_package() -> search.CachedPackage:
    return search.CachedPackage(
        metadata={
            "event_id": "calibration__synthetic",
            "replication": 3,
            "market_seed": 90210,
            "vault_seed": 123,
        },
        arrays={
            "residual_innovations": np.asarray([0.1, -0.2, 0.3], dtype="<f8"),
            "liquidation_attempts": np.asarray([1, 3, 5], dtype="<i8"),
            "liquidation_gate_open": np.asarray([True, False, True], dtype="?"),
            "material_active_bad_debt": np.asarray([False, True, True], dtype="?"),
            "active_bad_debt_dai": np.asarray([0.0, 4.0, 2.0], dtype="<f8"),
            "unresolved_tab_dai": np.asarray([0.0, 8.0, 1.0], dtype="<f8"),
        },
    )


def _registered_variant(variant_id: str) -> dict[str, object]:
    return next(
        item
        for item in structural.build_variant_registry()["variants"]
        if item["variant_id"] == variant_id
    )


def test_residual_variants_are_deterministic_and_preserve_empirical_support() -> None:
    package = _synthetic_package()
    residual_source = np.asarray([-0.4, -0.1, 0.2, 0.7], dtype="<f8")
    common = {
        "config": object(),
        "eligible_snapshots": pd.DataFrame(),
        "residual_values": residual_source,
    }
    zero, _ = structural._variant_package(
        package, _registered_variant("residual_zero"), **common
    )
    first, _ = structural._variant_package(
        package, _registered_variant("residual_iid_empirical"), **common
    )
    second, _ = structural._variant_package(
        package, _registered_variant("residual_iid_empirical"), **common
    )
    assert np.array_equal(zero.arrays["residual_innovations"], np.zeros(3))
    assert np.array_equal(
        first.arrays["residual_innovations"],
        second.arrays["residual_innovations"],
    )
    assert set(first.arrays["residual_innovations"]).issubset(set(residual_source))
    assert np.array_equal(
        package.arrays["residual_innovations"],
        np.asarray([0.1, -0.2, 0.3]),
    )


def test_gate_ablation_retains_underlying_backlog_and_bad_debt_state() -> None:
    package = _synthetic_package()
    common = {
        "config": object(),
        "eligible_snapshots": pd.DataFrame(),
        "residual_values": np.asarray([], dtype="<f8"),
    }
    price_only, _ = structural._variant_package(
        package, _registered_variant("gate_price_only"), **common
    )
    assert price_only.arrays["liquidation_gate_open"].all()
    assert not price_only.arrays["material_active_bad_debt"].any()
    assert np.array_equal(
        price_only.arrays["active_bad_debt_dai"],
        package.arrays["active_bad_debt_dai"],
    )
    assert np.array_equal(
        price_only.arrays["unresolved_tab_dai"],
        package.arrays["unresolved_tab_dai"],
    )


def test_non_binding_capacity_reuses_the_canonical_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _synthetic_package()

    def fail_if_called(**_: object) -> None:
        raise AssertionError("A non-binding capacity must reuse the baseline path.")

    monkeypatch.setattr(
        structural, "simulate_candidate_invariant_liquidation_path", fail_if_called
    )
    result, _ = structural._variant_package(
        package,
        _registered_variant("capacity_5"),
        config=object(),
        eligible_snapshots=pd.DataFrame(),
        residual_values=np.asarray([], dtype="<f8"),
    )
    assert result.arrays["liquidation_attempts"] is package.arrays[
        "liquidation_attempts"
    ]


def test_historical_state_is_deterministic_and_debt_normalised() -> None:
    package = search.CachedPackage(
        metadata={
            "event_id": "calibration__synthetic",
            "replication": 1,
            "market_seed": 2,
            "vault_seed": 3,
        },
        arrays={"eth_prices": np.asarray([1_500.0], dtype="<f8")},
    )
    timestamp = pd.Timestamp("2022-01-01T00:00:00Z")
    eligible = pd.DataFrame(
        {
            "timestamp_utc": [timestamp, timestamp],
            "_source_path": ["source.csv", "source.csv"],
            "state_label": ["opening", "opening"],
            "ilk": ["ETH-A", "ETH-A"],
            "urn": ["0x01", "0x02"],
            "debt_dai": [100.0, 300.0],
            "collateral_ratio": [2.0, 4.0],
            "liquidation_ratio": [1.45, 1.45],
        }
    )
    snapshot = {
        "timestamp_utc": timestamp.isoformat(),
        "source_path": "source.csv",
        "state_label": "opening",
    }
    first = structural._historical_state(package, snapshot, eligible)
    second = structural._historical_state(package, snapshot, eligible)
    assert first == second
    assert first.vault_count == 500
    assert sum(first.debt_dai) == pytest.approx(2_500_000.0)
    assert set(first.collateral_ratios).issubset({2.0, 4.0})


def _effect_frame(
    *,
    towards: int,
    large_precise: int,
    median_reduction: float,
    outer_passes: int = 0,
) -> pd.DataFrame:
    rows = []
    for index in range(16):
        rows.append(
            {
                "candidate_index": index,
                "movement_towards_band": index < towards,
                "shift_scales": 0.6 if index < large_precise else 0.1,
                "paired_snr": 3.0 if index < large_precise else 1.0,
                "absolute_band_gap_reduction_scales": median_reduction,
                "variant_outer_pass": index < outer_passes,
                "baseline_numerical_bound_pass": True,
                "variant_numerical_bound_pass": True,
                "structural_pass": True,
                "stage1_preservation_pass": True,
            }
        )
    return pd.DataFrame(rows)


def test_material_directional_effect_requires_every_threshold() -> None:
    assert structural.material_directional_effect(
        _effect_frame(towards=12, large_precise=8, median_reduction=0.5)
    )
    assert not structural.material_directional_effect(
        _effect_frame(towards=11, large_precise=8, median_reduction=0.5)
    )
    assert not structural.material_directional_effect(
        _effect_frame(towards=12, large_precise=7, median_reduction=0.5)
    )
    assert not structural.material_directional_effect(
        _effect_frame(towards=12, large_precise=8, median_reduction=0.49)
    )


def test_constraint_resolution_requires_twelve_outer_passes_and_hard_gates() -> None:
    assert structural.constraint_resolved(
        _effect_frame(
            towards=12, large_precise=8, median_reduction=0.5, outer_passes=12
        )
    )
    assert not structural.constraint_resolved(
        _effect_frame(
            towards=12, large_precise=8, median_reduction=0.5, outer_passes=11
        )
    )


def _variant_classification_frame(
    *,
    material_moments: int = 0,
    resolved_moments: int = 0,
    tradeoff: bool = False,
    structurally_valid: bool = True,
) -> pd.DataFrame:
    frames = []
    for position, moment in enumerate(structural.STAGE2_ACTIVE_MOMENTS):
        material = position < material_moments
        resolved = position < resolved_moments
        frame = _effect_frame(
            towards=12 if material else 0,
            large_precise=8 if material else 0,
            median_reduction=0.5 if material else 0.0,
            outer_passes=12 if resolved else 0,
        )
        frame["moment"] = moment
        frame["baseline_signed_gap"] = 2.0
        frame["variant_signed_gap"] = 1.0 if material else 2.0
        frame["baseline_gap_scales"] = 2.0
        frame["variant_gap_scales"] = 1.0 if material else 2.0
        if tradeoff and position == len(structural.STAGE2_ACTIVE_MOMENTS) - 1:
            frame["movement_towards_band"] = False
            frame["variant_signed_gap"] = 3.0
            frame["variant_gap_scales"] = 3.0
        if not structurally_valid:
            frame["structural_pass"] = False
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "no_material_effect"),
        ({"material_moments": 1}, "directionally_helpful_but_insufficient"),
        (
            {"material_moments": 1, "resolved_moments": 1},
            "single_constraint_resolution",
        ),
        (
            {"material_moments": 2, "resolved_moments": 2},
            "multi_constraint_resolution",
        ),
        ({"material_moments": 1, "tradeoff": True}, "tradeoff"),
        ({"structurally_valid": False}, "structurally_invalid"),
    ],
)
def test_variant_classification_is_fixed_and_mutually_exclusive(
    kwargs: dict[str, object], expected: str
) -> None:
    assert (
        structural.classify_variant(_variant_classification_frame(**kwargs))[
            "classification"
        ]
        == expected
    )


@pytest.mark.parametrize(
    ("summaries", "expected"),
    [
        ([{"classification": "source_unavailable"}], "unavailable"),
        (
            [{"classification": "tradeoff", "resolved": [], "material": []}],
            "tradeoff_family",
        ),
        (
            [{
                "classification": "multi_constraint_resolution",
                "resolved": ["a", "b", "c"],
                "material": ["a", "b", "c", "d"],
            }],
            "strong_explanatory_signal",
        ),
        (
            [{
                "classification": "single_constraint_resolution",
                "resolved": ["a"],
                "material": ["a"],
            }],
            "partial_explanatory_signal",
        ),
        (
            [{
                "classification": "no_material_effect",
                "resolved": [],
                "material": [],
            }],
            "no_explanatory_signal",
        ),
    ],
)
def test_family_classification_uses_only_registered_thresholds(
    summaries: list[dict[str, object]], expected: str
) -> None:
    assert structural.classify_family(summaries) == expected


@pytest.mark.parametrize(
    ("classes", "domain", "expected"),
    [
        (
            {
                "a": "strong_explanatory_signal",
                "b": "no_explanatory_signal",
            },
            {"possible": False},
            "single_structural_family_dominant",
        ),
        (
            {
                "a": "partial_explanatory_signal",
                "b": "partial_explanatory_signal",
            },
            {"possible": False},
            "multiple_structural_families_contribute",
        ),
        (
            {"a": "no_explanatory_signal"},
            {"possible": True},
            "parameter_domain_truncation_possible",
        ),
        (
            {"a": "no_explanatory_signal"},
            {"possible": False},
            "conditional_event_design_mismatch_unresolved",
        ),
    ],
)
def test_overall_classification_hierarchy(
    classes: dict[str, str],
    domain: dict[str, bool],
    expected: str,
) -> None:
    assert structural.overall_classification(classes, domain)[0] == expected


def test_input_validation_reuses_exact_completed_baseline() -> None:
    result = structural.validate_inputs()
    assert result["status"] == "passed"
    assert result["baseline_rows_reused"] == 75_776
    assert result["all_event_cache_root_sha256"] == structural.ALL_EVENT_CACHE_SHA256
    assert result["panel_sha256"] == structural.PANEL_SHA256


def test_workflow_help_is_import_safe_without_ignored_result_data() -> None:
    workflow = Path("workflows/calibration/market_gas_protocol.py")
    result = subprocess.run(
        [sys.executable, str(workflow), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "structural-diagnosis" in result.stdout
    assert "run-panel" in result.stdout
    for blocked in ("ranking", "powell", "registry-b"):
        assert blocked not in result.stdout.lower()


def test_partial_event_shard_requires_explicit_resume(tmp_path: Path) -> None:
    shard_directory = tmp_path / "shards"
    shard_directory.mkdir()
    (shard_directory / "event_shard_00.npz").touch()
    with pytest.raises(ValueError, match="explicit resume"):
        structural.run_structural_panel(root=tmp_path, workers=1, resume=False)


def test_registry_serialisation_contains_no_selected_model_or_candidate() -> None:
    payload = json.dumps(structural.build_variant_registry(), sort_keys=True)
    assert '"selected": true' not in payload.lower()
    assert '"runtime_adopted": true' not in payload.lower()
    assert "best_variant" not in payload


def test_completed_compact_evidence_is_registered_and_non_selective() -> None:
    validation = structural.validate_completed_diagnosis()
    assert validation == {
        "status": "passed",
        "overall_classification": "multiple_structural_families_contribute",
        "variant_count": 13,
        "executed_variant_count": 12,
        "result_rows": 960,
        "parameter_selected": False,
        "structural_model_selected": False,
        "runtime_adopted": False,
    }
    evidence = structural.CONFIDENCE_EVIDENCE
    results = pd.read_csv(evidence / "structural_variant_results.csv")
    assert len(results) == 12 * 16 * 5
    assert not any(
        blocked in column.lower()
        for column in results
        for blocked in ("objective", "rank", "selected")
    )
    decision = json.loads(
        (evidence / "structural_incompatibility_decision.json").read_text()
    )
    assert decision["unresolved_constraints"] == sorted(
        structural.STAGE2_ACTIVE_MOMENTS
    )
    assert not decision["parameter_selected"]
    assert not decision["structural_model_selected"]
    assert not decision["runtime_adopted"]


def test_reproducibility_checksums_cover_deterministic_evidence() -> None:
    evidence = structural.CONFIDENCE_EVIDENCE
    payload = json.loads(
        (
            evidence / "structural_incompatibility_reproducibility.json"
        ).read_text()
    )
    for name, expected in payload["deterministic_evidence_checksums"].items():
        assert structural.sha256_file(evidence / name) == expected
    assert payload["panel_sha256"] == structural.PANEL_SHA256
    assert payload["fixed_sobol_sha256"] == structural.SOBOL_SHA256
    assert not payload["objective_ranking_used"]
    assert not payload["final_validation_data_used"]
