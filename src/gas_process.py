"""Compatibility alias for :mod:`dai_sim.inputs.gas` until Stage 11."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module("dai_sim.inputs.gas")
