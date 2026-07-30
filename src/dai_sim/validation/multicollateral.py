"""Semantic validation interface for the frozen multi-collateral contract.

The implementation remains at its registered historical path because its
scientific identity includes that path and the input-validation workflow
bytes. New code should import this semantic interface.
"""

from __future__ import annotations

from dai_sim.calibration import multicollateral_validation as _implementation


def __getattr__(name: str) -> object:
    """Delegate symbols to the path-protected historical implementation."""
    return getattr(_implementation, name)


def __dir__() -> list[str]:
    """Expose the implementation API through the semantic validation module."""
    return sorted(set(globals()) | set(dir(_implementation)))
