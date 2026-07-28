"""Compatibility alias for :mod:`dai_sim.model.liquidation` until Stage 11."""

if __name__ == "__main__":
    import runpy as _runpy

    _runpy.run_module("dai_sim.model.liquidation", run_name="__main__")
else:
    from importlib import import_module as _import_module
    import sys as _sys

    _sys.modules[__name__] = _import_module("dai_sim.model.liquidation")
