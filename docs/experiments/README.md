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
- [ETH-only peg-recovery matrix](eth_recovery_matrix.md) — the pre-registered
  16-cell recovery-path × confidence-scenario experiment using paired common
  random numbers and censored sustained-recovery estimands.
- [Peg recovery](peg_recovery.md)
- [Multi-collateral portfolios and shocks](multi_collateral.md)

Established scenario definitions are Python configuration factories in
`scenarios.py`, with execution functions in `runner.py`. The new opt-in ETH
recovery matrix has a dedicated versioned YAML design and resumable workflow;
it does not change those established runners. All experiments use explicit
seeds, and the first five experiments retain frozen substantive regression
checksums.
