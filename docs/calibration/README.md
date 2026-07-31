# Calibration

Active calibration guidance is organised by evidence and decision:

`src/dai_sim/calibration/` owns estimation, identification and adoption
decisions. Frozen-profile and cross-layer validation belongs to
`src/dai_sim/validation/`; two path-hashed historical validator
implementations remain under `calibration/` as documented exceptions rather
than calibration activities.

- [Parameter sources](parameter_sources.md) — acquisition classes and the
  complete parameter inventory.
- [Parameter estimation](parameter_estimation.md) — reproducible estimators
  and validation methods for each simulator input.
- [Parameter adoption](parameter_adoption.md) — semantic compatibility and
  model-interface decisions.
- [Market and gas](market_and_gas.md)
- [Confidence and behaviour](confidence_and_behaviour.md) — mechanism design
  for latent confidence, DAI response and sustained recovery.
- [Confidence estimation](confidence_estimation.md) — binary persistence
  design, liquidation reconstruction and non-estimable feasibility result.
- [Confidence evidence redesign](confidence_evidence_redesign.md) —
  continuous downside burden, deterministic origin grid, evidence-partition
  gates and the pre-registered historical extension.
- [Historical confidence market evidence](confidence_historical_market_evidence.md)
  — the adopted 2019–2024 DAI/ETH extension, sparse scaling gates and final
  no-fit Design C decision.
- [Constrained confidence simulated moments](confidence_simulated_moments.md)
  — staged direct/SMM ownership, equal-event moments, bounds, weighting,
  deterministic search infrastructure, identification and blocked validation.
  Stage 1 is accepted for future SMM; Stage 2 remains unfitted and no
  behavioural mechanism is runtime adopted.
- [Conditional confidence event simulation](confidence_event_simulation.md)
  — dormant standardised state, observed-ETH paths, recovery gates, interface
  probes and bounded workload evidence; no Stage 2 fit or runtime integration.
- [Pre-registered confidence Sobol search](confidence_sobol_search.md)
  — immutable candidate-invariant cache, spawned candidate evaluation, atomic
  resume and deterministic ranking. The 256-candidate search is complete, but
  the fixed MCSE gate permits no top-16 all-event follow-up.
- [Confidence precision diagnosis](confidence_precision_diagnosis.md) —
  hierarchical MCSE audit, objective-blind replication ladder and
  recovery-censoring continuation. The recovery moment is not operationally
  identifiable under the registered design; no candidate is selected.
- [Confidence recovery-moment redesign](confidence_recovery_moment.md) —
  fixed 48-hour probability and 168-hour restricted-mean alternatives,
  checkpoint-only precision evidence and the unsupported conditional-channel
  decision. No replacement, search or runtime adoption follows.
- [Confidence objective simplification and identification](confidence_objective_identification.md)
  — seven reported moments, a proposed equally weighted five-moment Stage 2
  objective and its operationality gate. Four active moments fail the fixed
  R=256 MCSE count, so no numerical identification or new search follows.
- [Persistent-confidence partial identification](confidence_partial_identification.md)
  — fixed-grid empirical compatibility bands, inner and outer admissibility,
  and objective-blind representatives for robustness analysis. Retained
  vectors are not estimates and no persistent-confidence value is adopted.
- [Persistent-confidence structural incompatibility](confidence_structural_incompatibility.md)
  — baseline mismatch directions and a fixed, one-factor, paired structural
  panel. Diagnostic interventions are not ranked, selected or runtime adopted.
- [Persistent-confidence structural factorial](confidence_structural_factorial.md)
  — objective-blind interactions among the three partial-signal families,
  including the uniform MCSE precision extension. No compatible cell is found;
  calibration rescue for the present formulation ends without selection.
- [Persistent-confidence scenarios](../experiments/confidence_scenarios.md) —
  four pre-registered experimental bundles reconstructed from the unchanged
  coupled domain transform. They are scenario-defined, not calibrated,
  ranked, selected or runtime adopted.
- [Representative vaults](vaults.md)
- [Liquidations](liquidations.md)
- [System-wide keeper execution](keeper_execution.md) — pre-registered shared
  hourly capacity and proportional profit-hurdle candidates. Both are
  partially identified and remain opt-in, non-adopted sensitivities.
- [Result-blind oracle-delay freeze](oracle_delay.md) — the implemented global
  price-lag semantics, local evidence audit and transparent zero-, one- and
  two-step Experiment E registry. The coordinates are not historical latency
  estimates and remain non-adopted.
- [Integrated empirical ETH-only validation](../validation/integrated_empirical_eth.md)
  — the opt-in 500-vault assembly of the accepted empirical owners. It is
  experiment-ready with caveats and remains non-adopted.
- [Protocol parameters](protocol.md)

Candidate estimation and adoption are separate. A statistically estimated
value is not an adopted configuration value until its semantics, provenance,
uncertainty and model interface have been reviewed. Chronological estimation
and implementation reports are preserved in the
[documentation archive](../archive/README.md).
