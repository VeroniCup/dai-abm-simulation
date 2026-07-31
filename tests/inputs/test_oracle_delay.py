"""Typed oracle-delay registry tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from dai_sim.inputs.oracle_delay import (
    load_oracle_delay_registry,
    registry_identity,
    resolve_oracle_delay_treatment,
)


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config/sensitivities/final_oracle_delay_registry.yaml"


def _write_registry(path: Path, payload: dict[str, object]) -> None:
    payload["registry_identity"] = registry_identity(payload)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def test_default_registry_has_exact_three_system_wide_treatments() -> None:
    registry = load_oracle_delay_registry()
    assert tuple(item.identifier for item in registry.treatments) == (
        "oracle_delay_low",
        "oracle_delay_central",
        "oracle_delay_high",
    )
    assert tuple(item.delay_steps for item in registry.treatments) == (0, 1, 2)
    assert registry.step_duration_hours == 1
    assert registry.runtime_adopted is False
    assert registry.source_classification == (
        "transparent_sensitivity_not_empirically_identified"
    )


def test_treatment_lookup_is_explicit() -> None:
    assert resolve_oracle_delay_treatment(
        "oracle_delay_central"
    ).delay_steps == 1
    with pytest.raises(KeyError, match="Unknown oracle-delay"):
        resolve_oracle_delay_treatment("oracle_delay_fourth")


def test_registry_rejects_duplicate_values_and_excessive_delay(
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    duplicate = deepcopy(payload)
    duplicate["treatments"]["oracle_delay_high"]["delay_steps"] = 1
    duplicate["treatments"]["oracle_delay_high"]["equivalent_hours"] = 1
    duplicate_path = tmp_path / "duplicate.yaml"
    _write_registry(duplicate_path, duplicate)
    with pytest.raises(ValueError, match="ordering"):
        load_oracle_delay_registry(duplicate_path)

    excessive = deepcopy(payload)
    excessive["treatments"]["oracle_delay_high"]["delay_steps"] = 768
    excessive["treatments"]["oracle_delay_high"]["equivalent_hours"] = 768
    excessive_path = tmp_path / "excessive.yaml"
    _write_registry(excessive_path, excessive)
    with pytest.raises(ValueError, match="horizon"):
        load_oracle_delay_registry(excessive_path)


def test_registry_rejects_unsupported_semantic_owner(tmp_path: Path) -> None:
    payload = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    payload["parameter_semantic_owner"] = "another.delay.mechanism"
    path = tmp_path / "wrong_owner.yaml"
    _write_registry(path, payload)
    with pytest.raises(ValueError, match="parameter semantics"):
        load_oracle_delay_registry(path)
