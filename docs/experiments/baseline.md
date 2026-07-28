# Baseline gas and panic scenarios

## Research question

How do liquidation gas costs, keeper capacity and confidence breakdown change
DAI peg stability and bad debt after a common ETH shock?

## Implemented scenarios

`create_scenario_configs()` defines `low_gas`, `medium_gas`, `high_gas` and
`extreme_panic`. They vary gas cost, maximum liquidations per step and, for the
panic case, risk cost, close factor, confidence and DAI-market response. The
default shock is a 43% ETH fall at step 30.

The base population has 100 vaults, a 100-step horizon and seed 42. These are
established scenario definitions, not newly estimated empirical values.

## Invocation

```python
from dai_sim.experiments.runner import run_all_scenarios

results, summary = run_all_scenarios()
```

The function writes detailed scenario and combined CSVs under
`outputs/experiments/baseline/` and summary CSVs under
`outputs/tables/baseline/`.

## Interpretation and limitations

Compare peg deviation, active and realised bad debt, liquidation outcomes and
keeper profit across scenarios. The experiment changes several frictions in
the extreme-panic case, so its difference is a compound stress comparison,
not a single-parameter causal estimate.
