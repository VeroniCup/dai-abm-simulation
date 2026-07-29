"""Tracked compact evidence gates for confidence SMM infrastructure."""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from tests.support import REPOSITORY_ROOT


ROOT = REPOSITORY_ROOT / "data/provenance/calibration/confidence"
REQUIRED = {
    "stage1_market_estimates.json",
    "stage1_residual_summary.json",
    "simulated_moments_specification.json",
    "empirical_moments.csv",
    "moment_weights.csv",
    "parameter_bounds.json",
    "event_catalogue.csv",
    "seed_registry.json",
    "conditional_event_specification.json",
    "conditional_initial_state.json",
    "recovery_gate_specification.json",
    "event_simulation_smoke.json",
    "event_simulation_benchmark.json",
}


def test_required_compact_evidence_is_registered_and_content_addressed() -> None:
    manifest = json.loads(
        (
            REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
        ).read_text(encoding="utf-8")
    )
    records = {
        record["path"].split("/")[-1]: record
        for record in manifest["artefacts"]
        if "/confidence/" in record["path"]
    }
    assert REQUIRED <= set(records)
    for name in REQUIRED:
        path = ROOT / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == records[name]["sha256"]
        assert path.stat().st_size == records[name]["size_bytes"]


def test_event_and_moment_evidence_reproduces_fixed_counts() -> None:
    events = pd.read_csv(ROOT / "event_catalogue.csv")
    moments = pd.read_csv(ROOT / "empirical_moments.csv")
    assert events.shape == (75, 34)
    assert events["partition"].value_counts().to_dict() == {
        "calibration": 74,
        "final_stress_validation": 1,
    }
    assert moments.shape == (8, 13)
    assert moments["group"].value_counts().sort_index().to_dict() == {
        group: 2 for group in "ABCD"
    }
    assert moments["initial_total_weight"].eq(0.125).all()


def test_stage1_is_future_smm_only_and_all_gates_pass() -> None:
    stage1 = json.loads(
        (ROOT / "stage1_market_estimates.json").read_text(encoding="utf-8")
    )
    residual = json.loads(
        (ROOT / "stage1_residual_summary.json").read_text(encoding="utf-8")
    )
    assert stage1["status"] == "accepted_for_future_smm"
    assert residual["status"] == "accepted_for_future_smm"
    assert all(stage1["gates"].values())
    assert all(residual["gates"].values())
    assert not stage1["runtime_adopted"]
    assert not residual["runtime_adopted"]


def test_stage2_has_no_estimate_or_runtime_adoption() -> None:
    bounds = json.loads(
        (ROOT / "parameter_bounds.json").read_text(encoding="utf-8")
    )
    specification = json.loads(
        (ROOT / "simulated_moments_specification.json").read_text(
            encoding="utf-8"
        )
    )
    assert specification["stage2_estimates"] is None
    assert not specification["runtime_adopted"]
    assert not bounds["runtime_adopted"]
    assert all(
        record["estimate"] is None
        for record in bounds["parameters"].values()
    )


def test_compact_evidence_contains_no_hourly_payload_or_absolute_path() -> None:
    assert sum((ROOT / name).stat().st_size for name in REQUIRED) < 100_000
    for name in REQUIRED:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "/Users/" not in text
    assert not (ROOT / "identification_summary.json").exists()
    assert not (ROOT / "simulated_moments_selection.json").exists()


def test_seed_registry_vectors_reproduce() -> None:
    from dai_sim.calibration.simulated_moments import derive_seed

    registry = json.loads(
        (ROOT / "seed_registry.json").read_text(encoding="utf-8")
    )
    for vector in registry["verification_vectors"]:
        assert vector["seed"] == derive_seed(
            registry_id=vector["registry_id"],
            event_id=vector["event_id"],
            replication=vector["replication"],
            stream_name=vector["stream_name"],
        )


def test_conditional_event_evidence_is_dormant_compact_and_non_ranked() -> None:
    specification = json.loads(
        (ROOT / "conditional_event_specification.json").read_text(encoding="utf-8")
    )
    initial = json.loads(
        (ROOT / "conditional_initial_state.json").read_text(encoding="utf-8")
    )
    gates = json.loads(
        (ROOT / "recovery_gate_specification.json").read_text(encoding="utf-8")
    )
    smoke = json.loads(
        (ROOT / "event_simulation_smoke.json").read_text(encoding="utf-8")
    )
    benchmark = json.loads(
        (ROOT / "event_simulation_benchmark.json").read_text(encoding="utf-8")
    )
    assert specification["common_maximum_horizon_hours"] == 792
    assert specification["stage2_parameter_defaults"] is None
    assert initial["normalisation"]["vault_count"] == 500
    assert initial["normalisation"]["total_debt_dai"] == 2_500_000
    assert gates["fitted_recovery_gate_coefficient"] is None
    assert gates["liquidation_pressure"]["liquidatable_share_substituted"] is False
    assert len(smoke["event_ids"]) == 4
    assert len(smoke["probe_vectors"]) == 5
    assert not smoke["candidate_ranking_performed"]
    assert not smoke["stage2_fit_performed"]
    assert not smoke["final_validation_event_simulated"]
    assert not smoke["full_trajectories_tracked"]
    assert set(smoke["simulated_moments_by_probe"]) == {
        probe["probe_id"] for probe in smoke["probe_vectors"]
    }
    for result in smoke["simulated_moments_by_probe"].values():
        assert len(result["moments"]) == 8
        assert result["event_count"] == 4
        assert result["equal_event_weighting"]
        assert not result["objective_evaluated"]
    assert benchmark["benchmark_workload"]["event_replication_runs"] == 8
    assert not benchmark["extrapolated_workloads_executed"]
    assert all(
        not payload["runtime_adopted"]
        for payload in (specification, initial, gates, smoke, benchmark)
    )


def test_conditional_event_evidence_validator_passes_registered_checksums() -> None:
    from dai_sim.calibration.validation import validate_conditional_event_evidence

    result = validate_conditional_event_evidence(
        ROOT,
        REPOSITORY_ROOT / "data/provenance/calibration/manifest.json",
    )
    assert result["status"] == "passed"
    assert len(result["checked"]) == 5
    assert not result["runtime_adopted"]
    assert not result["stage2_fit_performed"]
