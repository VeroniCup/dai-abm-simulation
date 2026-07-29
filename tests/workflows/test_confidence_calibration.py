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
