"""Path-protected confidence-scenario import surface.

Typed scenario resolution now belongs to :mod:`dai_sim.inputs`, while
mechanism validation and evidence reconstruction belong to
:mod:`dai_sim.validation`. This historical import path remains because the
registered integrated-ETH scientific identity includes the unchanged
``integrated_profile`` source that imports it.
"""

from __future__ import annotations

from dai_sim.inputs import confidence_scenarios as _inputs
from dai_sim.validation import confidence_scenarios as _validation


def __getattr__(name: str) -> object:
    """Resolve historical imports without duplicating scenario ownership."""
    if hasattr(_inputs, name):
        return getattr(_inputs, name)
    return getattr(_validation, name)


def __dir__() -> list[str]:
    """Expose both semantic APIs through the registered historical path."""
    return sorted(set(globals()) | set(dir(_inputs)) | set(dir(_validation)))
