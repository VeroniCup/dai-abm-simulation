"""Regression checks for tests that consume compact tracked evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dai_sim.calibration.oracle_delay import source_inventory
from tests.evidence_contracts import (
    validate_keeper_execution_compact_evidence,
    validate_monte_carlo_estimator_audit,
    validate_partial_identification_compact_evidence,
    validate_structural_factorial_compact_evidence,
)


def test_scientific_contracts_do_not_read_ignored_diagnostics(
    monkeypatch: Any,
) -> None:
    """Keep scientific contract tests independent of local run directories."""
    original_open = Path.open

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        normalised = path.as_posix()
        if "outputs/diagnostics" in normalised:
            raise AssertionError(f"ignored diagnostic read attempted: {normalised}")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    factorial = validate_structural_factorial_compact_evidence()
    keeper = validate_keeper_execution_compact_evidence()
    estimator = validate_monte_carlo_estimator_audit()
    partial = validate_partial_identification_compact_evidence()
    oracle_sources = source_inventory()

    assert factorial["status"] == "passed"
    assert keeper["status"] == "passed"
    assert estimator["existing_estimator_classification"] == (
        "correct_hierarchical_mcse"
    )
    assert partial["status"] == "passed"
    assert oracle_sources
