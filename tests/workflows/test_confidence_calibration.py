"""Local-only confidence calibration workflow command tests."""

from __future__ import annotations

import subprocess
import sys

import pytest

from workflows.calibration import market_gas_protocol


def test_help_does_not_require_the_ignored_panel() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "workflows/calibration/market_gas_protocol.py",
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "confidence-infrastructure" in result.stdout
    assert "event-simulation" in result.stdout
    assert "smm-search" in result.stdout
    assert "smm-precision" in result.stdout
    assert "recovery-redesign" in result.stdout
    assert "objective-identification" in result.stdout
    assert "partial-identification" in result.stdout


def test_confidence_operation_requires_explicit_input(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["market_gas_protocol.py", "confidence-infrastructure"],
    )
    with pytest.raises(SystemExit) as error:
        market_gas_protocol.main()
    assert error.value.code == 2


def test_validation_only_passes_explicit_local_configuration(
    monkeypatch, tmp_path
) -> None:
    observed = {}

    def fake_run(config):
        observed["config"] = config
        return {"validation_only": True}

    monkeypatch.setattr(
        market_gas_protocol,
        "run_confidence_calibration_infrastructure",
        fake_run,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_gas_protocol.py",
            "confidence-infrastructure",
            "--input",
            str(tmp_path / "input.csv"),
            "--validation-only",
        ],
    )
    assert market_gas_protocol.main() == 0
    assert observed["config"].validation_only
    assert observed["config"].input_path == (tmp_path / "input.csv").resolve()


def test_workflow_has_no_live_acquisition_import() -> None:
    source = market_gas_protocol.Path(
        market_gas_protocol.__file__
    ).read_text(encoding="utf-8")
    assert "requests" not in source
    assert "dune" not in source.lower()
    assert "dai_sim.model.simulation" not in source


def test_partial_identification_forwards_bounded_grid_controls(
    monkeypatch, tmp_path
) -> None:
    observed = {}

    def fake_run(**kwargs):
        observed.update(kwargs)
        return {"status": "passed"}

    monkeypatch.setattr(
        market_gas_protocol, "run_partial_identification_review", fake_run
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_gas_protocol.py",
            "partial-identification",
            "--partial-identification-action",
            "resume-grid",
            "--partial-identification-root",
            str(tmp_path / "partial"),
            "--precision-root",
            str(tmp_path / "cache"),
            "--workers",
            "3",
            "--recover-stale-lock",
        ],
    )
    assert market_gas_protocol.main() == 0
    assert observed["action"] == "resume-grid"
    assert observed["workers"] == 3
    assert observed["recover_stale_lock"]
    assert observed["root"] == (tmp_path / "partial").resolve()
    assert observed["cache_dir"] == (tmp_path / "cache").resolve()


def test_partial_identification_constructs_the_five_registered_bands() -> None:
    result = market_gas_protocol.run_partial_identification_review(
        action="construct-bands"
    )
    assert result["status"] == "passed"
    assert result["constraint_count"] == 5
    assert all(
        row["classification_rule"].startswith("inner iff")
        for row in result["constraints"]
    )


@pytest.mark.parametrize(
    "unsupported",
    ("--objective", "--rank", "--top-16", "--powell", "--registry-b"),
)
def test_partial_identification_rejects_optimisation_flags(unsupported) -> None:
    parser = market_gas_protocol.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["partial-identification", unsupported])


@pytest.mark.parametrize("event_action", ["validate", "smoke", "benchmark"])
def test_event_simulation_operations_forward_explicit_bounded_controls(
    monkeypatch, tmp_path, event_action
) -> None:
    observed = {}

    def fake_run(**kwargs):
        observed.update(kwargs)
        return {"action": kwargs["action"]}

    monkeypatch.setattr(
        market_gas_protocol,
        "run_event_simulation_evidence",
        fake_run,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_gas_protocol.py",
            "event-simulation",
            "--input",
            str(tmp_path / "panel.csv"),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--event-diagnostics-dir",
            str(tmp_path / "diagnostics"),
            "--event-action",
            event_action,
            "--probe-indices",
            "0,127,255",
        ],
    )
    assert market_gas_protocol.main() == 0
    assert observed["action"] == event_action
    assert observed["probe_indices"] == (0, 127, 255)
    assert observed["panel_path"] == (tmp_path / "panel.csv").resolve()
    assert observed["source_evidence_dir"] == (
        market_gas_protocol.CONFIDENCE_EVIDENCE.resolve()
    )
    assert not observed["register_manifest"]


def test_event_workflow_rejects_non_preregistered_probe_or_optimisation_flag(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_gas_protocol.py",
            "event-simulation",
            "--probe-indices",
            "1,2,3",
        ],
    )
    with pytest.raises(SystemExit) as error:
        market_gas_protocol.main()
    assert error.value.code == 2
    parser = market_gas_protocol.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["event-simulation", "--optimise"])


def test_search_cache_preparation_requires_explicit_ignored_panel(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["market_gas_protocol.py", "smm-search", "--search-action", "prepare-cache"],
    )
    with pytest.raises(SystemExit) as error:
        market_gas_protocol.main()
    assert error.value.code == 2


def test_search_validation_does_not_require_ignored_panel(
    monkeypatch, tmp_path
) -> None:
    observed = {}
    identity = type("Identity", (), {"search_id": "fixed-search"})()
    monkeypatch.setattr(
        market_gas_protocol,
        "load_search_identity",
        lambda _: (identity, {}),
    )
    monkeypatch.setattr(
        market_gas_protocol,
        "validate_search_cache",
        lambda run_dir, expected_identity: observed.update(
            run_dir=run_dir, identity=expected_identity
        )
        or {"status": "passed"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_gas_protocol.py",
            "smm-search",
            "--search-action",
            "validate-cache",
            "--search-root",
            str(tmp_path),
        ],
    )
    assert market_gas_protocol.main() == 0
    assert observed["run_dir"] == (tmp_path / "fixed-search").resolve()


def test_search_resume_forwards_explicit_workers_and_lock_policy(
    monkeypatch, tmp_path
) -> None:
    observed = {}
    identity = type("Identity", (), {"search_id": "fixed-search"})()
    monkeypatch.setattr(
        market_gas_protocol,
        "load_search_identity",
        lambda _: (identity, {}),
    )
    monkeypatch.setattr(
        market_gas_protocol,
        "run_sobol_search",
        lambda run_dir, **kwargs: observed.update(run_dir=run_dir, **kwargs)
        or {"status": "passed"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_gas_protocol.py",
            "smm-search",
            "--search-action",
            "resume",
            "--search-root",
            str(tmp_path),
            "--workers",
            "4",
            "--recover-stale-lock",
        ],
    )
    assert market_gas_protocol.main() == 0
    assert observed["workers"] == 4
    assert observed["resume"]
    assert observed["recover_stale_lock"]


@pytest.mark.parametrize(
    "unsupported",
    ["--powell", "--registry-b", "--final-validation"],
)
def test_search_workflow_rejects_unauthorised_operations(unsupported) -> None:
    parser = market_gas_protocol.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["smm-search", unsupported])


def test_precision_audit_is_local_and_objective_blind(monkeypatch, tmp_path) -> None:
    observed = {}
    monkeypatch.setattr(
        market_gas_protocol,
        "audit_completed_search",
        lambda: observed.update(called=True) or {"candidate_selected": False},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_gas_protocol.py",
            "smm-precision",
            "--precision-action",
            "audit",
            "--precision-root",
            str(tmp_path),
        ],
    )
    assert market_gas_protocol.main() == 0
    assert observed == {"called": True}


def test_precision_resume_forwards_only_fixed_workers(monkeypatch, tmp_path) -> None:
    observed = {}
    monkeypatch.setattr(
        market_gas_protocol,
        "run_replication_ladder",
        lambda **kwargs: observed.update(kwargs) or {"status": "passed"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_gas_protocol.py",
            "smm-precision",
            "--precision-action",
            "resume-ladder",
            "--precision-root",
            str(tmp_path),
            "--workers",
            "3",
        ],
    )
    assert market_gas_protocol.main() == 0
    assert observed["run_dir"] == tmp_path.resolve()
    assert observed["workers"] == 3
    assert observed["resume"]


def test_precision_summary_does_not_select_or_adopt(monkeypatch, tmp_path) -> None:
    observed = {}
    monkeypatch.setattr(
        market_gas_protocol,
        "summarise_precision_diagnosis",
        lambda **kwargs: observed.update(kwargs)
        or {"candidate_selected": False, "runtime_adopted": False},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_gas_protocol.py",
            "smm-precision",
            "--precision-action",
            "summarise",
            "--precision-root",
            str(tmp_path / "run"),
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ],
    )
    assert market_gas_protocol.main() == 0
    assert observed["run_dir"] == (tmp_path / "run").resolve()
    assert observed["evidence_dir"] == (tmp_path / "evidence").resolve()
    assert not observed["register_manifest"]


@pytest.mark.parametrize(
    "unsupported",
    ["--powell", "--registry-b", "--final-validation", "--optimise"],
)
def test_precision_workflow_rejects_optimisation_and_validation_flags(
    unsupported,
) -> None:
    parser = market_gas_protocol.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["smm-precision", unsupported])


def test_recovery_redesign_forwards_only_local_checkpoint_controls(
    monkeypatch, tmp_path
) -> None:
    observed = {}
    monkeypatch.setattr(
        market_gas_protocol,
        "run_recovery_moment_redesign",
        lambda **kwargs: observed.update(kwargs)
        or {"status": "conditional_recovery_moment_unsupported"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_gas_protocol.py",
            "recovery-redesign",
            "--recovery-action",
            "resume",
            "--precision-root",
            str(tmp_path / "checkpoints"),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--recovery-diagnostics-dir",
            str(tmp_path / "diagnostics"),
        ],
    )
    assert market_gas_protocol.main() == 0
    assert observed["action"] == "resume"
    assert observed["run_dir"] == (tmp_path / "checkpoints").resolve()
    assert observed["diagnostics_dir"] == (tmp_path / "diagnostics").resolve()
    assert not observed["register_manifest"]


@pytest.mark.parametrize(
    "unsupported",
    ["--powell", "--registry-b", "--final-validation", "--optimise", "--search-action"],
)
def test_recovery_redesign_rejects_search_and_optimisation_operations(
    unsupported,
) -> None:
    parser = market_gas_protocol.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["recovery-redesign", unsupported])


def test_objective_identification_forwards_only_local_gated_controls(
    monkeypatch, tmp_path
) -> None:
    observed = {}
    monkeypatch.setattr(
        market_gas_protocol,
        "run_objective_identification_review",
        lambda **kwargs: observed.update(kwargs)
        or {"status": "seven_moment_specification_not_operational"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_gas_protocol.py",
            "objective-identification",
            "--identification-action",
            "resume-jacobian-evaluation",
            "--precision-root",
            str(tmp_path / "checkpoints"),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--identification-diagnostics-dir",
            str(tmp_path / "diagnostics"),
        ],
    )
    assert market_gas_protocol.main() == 0
    assert observed["action"] == "resume-jacobian-evaluation"
    assert observed["run_dir"] == (tmp_path / "checkpoints").resolve()
    assert observed["diagnostics_dir"] == (tmp_path / "diagnostics").resolve()
    assert not observed["register_manifest"]


@pytest.mark.parametrize(
    "unsupported",
    [
        "--powell",
        "--registry-b",
        "--final-validation",
        "--search-action",
        "--optimise",
    ],
)
def test_objective_identification_rejects_search_and_adoption_operations(
    unsupported,
) -> None:
    parser = market_gas_protocol.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["objective-identification", unsupported])
