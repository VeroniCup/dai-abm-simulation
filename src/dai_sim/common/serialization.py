"""Deterministic JSON-boundary normalisation for scientific evidence.

This module changes representation only.  It does not round, stringify or
otherwise alter scientific values before serialisation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np


def to_json_compatible(value: Any) -> Any:
    """Return a recursively JSON-compatible representation of ``value``.

    Unsupported objects are deliberately returned unchanged so that the JSON
    encoder raises a clear ``TypeError`` rather than silently stringifying
    them.
    """
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return to_json_compatible(value.tolist())
    if isinstance(value, Mapping):
        return {
            str(key): to_json_compatible(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [to_json_compatible(item) for item in value]
    return value
