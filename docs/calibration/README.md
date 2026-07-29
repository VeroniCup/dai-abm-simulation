# Calibration

Active calibration guidance is organised by evidence and decision:

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
- [Representative vaults](vaults.md)
- [Liquidations](liquidations.md)
- [Protocol parameters](protocol.md)

Candidate estimation and adoption are separate. A statistically estimated
value is not an adopted configuration value until its semantics, provenance,
uncertainty and model interface have been reviewed. Chronological estimation
and implementation reports are preserved in the
[documentation archive](../archive/README.md).
