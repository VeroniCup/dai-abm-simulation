# Collateral-shock severity

## Research question

How do progressively larger ETH price falls affect liquidation pressure, bad
debt, keeper activity and DAI peg stability?

## Implemented scenarios

The default shock magnitudes are 20%, 35%, 43%, 55% and 70% falls at step 30.
The population, confidence, DAI-market and medium/high-friction liquidation
settings are fixed. The base horizon is 100 steps with seed 42.

## Invocation

```python
from dai_sim.experiments.runner import run_shock_severity_experiment

results, summary = run_shock_severity_experiment()
```

## Interpretation and limitations

The experiment traces nonlinear threshold effects as more vaults become
liquidatable and capacity binds. Shock values are scenario controls unless
separately adopted from empirical evidence.
