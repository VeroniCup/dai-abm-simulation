# Experiments

Experiments are separated by scientific role. Established historical runners
remain in [`src/dai_sim/experiments/`](../../src/dai_sim/experiments/);
controlled pre-final studies live in
[`experiments/mechanism/`](../../src/dai_sim/experiments/mechanism/), and
[`experiments/final/`](../../src/dai_sim/experiments/final/) is the sole
destination for the unimplemented final dissertation programme.

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
- [Constrained-liquidation ETH recovery](constrained_eth_recovery.md) — the
  completed 24-cell controlled recovery × system-wide capacity × confidence
  experiment using the validated integrated empirical ETH profile.
- [Experiment infrastructure maintenance](../validation/experiment_infrastructure_maintenance.md)
  — operational hardening of evidence reconstruction and concurrent profile
  initialisation with scientific evidence held immutable.
- [Peg recovery](peg_recovery.md)
- [Multi-collateral portfolios and shocks](multi_collateral.md)

The established multi-collateral runner above is a protected historical
stylised experiment
and remains operational for regression compatibility. Its five historical
portfolio names and five historical shock names are not the newly frozen
final design. The final, still unexecuted design has five portfolios and seven
shocks registered by the
[multi-collateral integration validation](../validation/multicollateral_integration.md).
No final portfolio or shock has been ranked or selected.

Established scenario definitions are protected Python configuration factories in
`scenarios.py`, with execution functions in `runner.py`. The new opt-in ETH
recovery matrix has a dedicated versioned YAML design and resumable workflow;
it does not change those established runners. Its source and workflow are under
`experiments/mechanism/`. All experiments use explicit
seeds, and the first five experiments retain frozen substantive regression
checksums.
