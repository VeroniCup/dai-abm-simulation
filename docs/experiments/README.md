# Experiments

The established experiments are implemented in
[`src/dai_sim/experiments/`](../../src/dai_sim/experiments/):

- [Baseline gas and panic scenarios](baseline.md)
- [Oracle delay](oracle_delay.md)
- [Shock severity](shock_severity.md)
- [Confidence sensitivity](confidence.md)
- [Persistent-confidence scenario registry](confidence_scenarios.md) —
  dormant, scenario-defined Stage 2 bundles for future explicitly authorised
  experiments; no bundle is calibrated, ranked or runtime adopted.
- [Peg recovery](peg_recovery.md)
- [Multi-collateral portfolios and shocks](multi_collateral.md)

Scenario definitions are Python configuration factories in `scenarios.py`;
execution functions are in `runner.py`. There is no separate experiment YAML
or experiment workflow CLI. All established runners use explicit
seeds, and the first five experiments have frozen substantive regression
checksums.
