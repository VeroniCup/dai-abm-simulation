# Multi-collateral portfolios and shocks

## Research question

How do collateral composition, cross-asset shock structure and shared keeper
capacity affect system solvency and DAI peg resilience?

## Implemented portfolios and shocks

The five portfolios are `eth_only`, `crypto_diversified`, `balanced`,
`stable_heavy` and `btc_concentrated`. Target system debt shares define their
composition.

The five shocks are `eth_specific_crash`, `btc_specific_crash`,
`correlated_crypto_crash`, `stable_depeg` and `systemic_shock`. Default crypto
falls are 43% and the stable depeg is 20%. They are stylised scenario
magnitudes.

## Invocation

```python
from dai_sim.experiments.runner import run_multicollateral_experiment

system, collateral, system_summary, collateral_summary = (
    run_multicollateral_experiment()
)
```

Scenario definitions are in
[`scenarios.py`](../../src/dai_sim/experiments/scenarios.py); the runner is
[`runner.py`](../../src/dai_sim/experiments/runner.py). There is no separate
experiment configuration file.

## Outputs and limitations

The experiment returns system-level and long-format collateral-level results
and summaries. Current stable-depeg effects are limited by the absence of a
direct stable-collateral confidence or DAI-demand channel. Correlated crypto
and systemic scenarios can therefore become equivalent under some current
assumptions; this is a model finding to diagnose, not evidence that stable
collateral is universally protective.
