"""Compatibility exports for simulation imports retained until Stage 11."""

if __name__ == "__main__":
    import runpy as _runpy

    _runpy.run_module("dai_sim.model.simulation", run_name="__main__")
else:
    from dai_sim.model.simulation import *  # noqa: F403
    from dai_sim.inputs.liquidations import LiquidationDemandProcess
