# Experiments

Experiments are separated by scientific role. Established historical runners
remain in [`src/dai_sim/experiments/`](../../src/dai_sim/experiments/);
controlled pre-final studies live in
[`experiments/mechanism/`](../../src/dai_sim/experiments/mechanism/), and
[`experiments/final/`](../../src/dai_sim/experiments/final/) is the sole
destination for the pre-registered
[final dissertation programme](final/README.md).

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
- [Final dissertation experiment programme](final/README.md) — the
  authoritative four research questions and four hypotheses, together with
  the registered Experiment A–E and H4-synthesis boundaries.
- [Experiment A — idiosyncratic diversification](final/idiosyncratic_diversification.md)
  — the completed eight-cell, 1,024-simulation isolated-shock experiment.
- [Experiment B — correlated stress](final/correlated_stress.md)
  — the completed eight-cell, 1,024-simulation registered joint-stress
  experiment, with its bundled-treatment limitation retained.
- [Experiment C — stable-collateral trade-off](final/stable_collateral_tradeoff.md)
  — the completed twelve-cell, 1,536-simulation counterfactual stable-proxy
  experiment.
- [Experiment D — shared keeper capacity](final/shared_keeper_capacity.md)
  — the completed nine-cell, 1,152-simulation global-capacity experiment.

Generated detailed experiment outputs use the semantic namespaces
`outputs/experiments/mechanism/` for controlled mechanism studies and
`outputs/experiments/final/` for the final programme. These ignored outputs
remain reproducible from their corresponding workflows.

The established multi-collateral runner above is a protected historical
stylised experiment
and remains operational for regression compatibility. Its five historical
portfolio names and five historical shock names are not the newly frozen
final design. The final design has five portfolios and seven shocks registered by the
[multi-collateral integration validation](../validation/multicollateral_integration.md).
No final portfolio, shock or capacity has been ranked or selected. Its core
programme contains 43 cells and 5,504 planned simulations. Experiments A–D
are complete. Experiment A supports idiosyncratic diversification; Experiment
B finds that the benefit weakens across the registered stress bundles without
reversing; Experiment C finds supported crypto buffering but no registered
stable-depeg severity or exposure gradient; and Experiment D finds one small
threshold backlog effect, mixed shared-capacity transmission and unchanged
peg outcomes, yielding `H1_no_clear_shared_capacity_effect`. The
result-independent oracle-delay freeze resolves Experiment E to transparent
zero-, one- and two-step sensitivities. Experiment E is ready but unexecuted,
and the H4 evidence synthesis is `pending_evidence_synthesis`.

Established scenario definitions are protected Python configuration factories in
`scenarios.py`, with execution functions in `runner.py`. The new opt-in ETH
recovery matrix has a dedicated versioned YAML design and resumable workflow;
it does not change those established runners. Its source and workflow are under
`experiments/mechanism/`. All experiments use explicit
seeds, and the first five experiments retain frozen substantive regression
checksums.
