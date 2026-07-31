"""Deterministic oracle-delay freeze workflow tests."""

from __future__ import annotations

import json
from pathlib import Path
import socket

import yaml

from workflows.calibration.oracle_delay import (
    build_freeze_payloads,
    freeze,
)


def test_non_host_dependent_payloads_reconstruct_byte_identically() -> None:
    first_artefacts, first_config = build_freeze_payloads()
    second_artefacts, second_config = build_freeze_payloads()
    assert first_artefacts == second_artefacts
    assert first_config == second_config


def test_isolated_freeze_is_atomic_and_non_operational(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    registry = tmp_path / "registry.yaml"
    result = freeze(
        evidence_dir=evidence,
        registry_path=registry,
        manifest_path=None,
    )
    assert result["experiment_e_simulations"] == 0
    assert result["network_calls"] == 0
    assert result["runtime_adopted"] is False
    assert {path.name for path in evidence.iterdir()} == {
        "oracle_delay_freeze_specification.json",
        "oracle_delay_source_inventory.csv",
        "oracle_delay_estimates.csv",
        "oracle_delay_registry.csv",
        "oracle_delay_decision.json",
        "oracle_delay_reproducibility.json",
    }
    payload = yaml.safe_load(registry.read_text(encoding="utf-8"))
    assert payload["runtime_adopted"] is False
    decision = json.loads(
        (evidence / "oracle_delay_decision.json").read_text(encoding="utf-8")
    )
    assert decision["delay_selected"] is False
    assert decision["experiment_e_status"] == "ready_but_unexecuted"


def test_payload_construction_does_not_use_network(
    monkeypatch: object,
) -> None:
    def blocked(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", blocked)  # type: ignore[attr-defined]
    artefacts, _ = build_freeze_payloads()
    reproducibility = json.loads(
        artefacts["oracle_delay_reproducibility.json"]
    )
    assert reproducibility["network_calls"] == 0
    assert reproducibility["held_out_observations"] == 0
