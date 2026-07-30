# Confidence sensitivity

## Research question

How sensitive is DAI peg behaviour to confidence thresholds, confidence levels,
panic selling and arbitrage strength under the same collateral shock?

## Implemented scenarios

The scenarios are `resilient_confidence`, `baseline_confidence`,
`fragile_confidence`, `panic_sensitive` and
`extreme_confidence_breakdown`. They vary confidence and DAI-market
parameters while holding the 43% ETH shock and liquidation environment fixed.

## Invocation

```python
from dai_sim.experiments.runner import run_confidence_sensitivity_experiment

results, summary = run_confidence_sensitivity_experiment()
```

## Interpretation and limitations

Compare peg depth and duration, confidence-state occupancy and bad-debt
interaction. The scenarios are behavioural sensitivity sets, not direct
measurements of market beliefs.

These established Experiment 4 configurations are distinct from the dormant
[persistent-confidence scenario registry](confidence_scenarios.md). The new
registry preserves the Stage 1-only production default and may be used only by
a separately authorised experiment through explicit activation.
