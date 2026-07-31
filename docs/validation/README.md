# Validation

Active validation records:

Validation code is exposed through `src/dai_sim/validation/`. The integrated
ETH and multi-collateral implementations remain at their historical
`src/dai_sim/calibration/*_validation.py` paths solely because those paths and
their workflow bytes are inputs to registered scientific identities; the
semantic validation modules delegate without redefining behaviour.

- [Regression validation](regression.md) — protected smoke, experiment and
  runtime-input identities.
- [Repository restructuring](repository_restructuring.md) — tracked-clone
  architecture and reproducibility closure.
- [Experiment-infrastructure maintenance](experiment_infrastructure_maintenance.md)
  — invocation repair and concurrency-safe semantic profile resolution.
- [Integrated empirical ETH-only profile](integrated_empirical_eth.md) —
  result-blind input and dynamic integration validation for the opt-in
  500-vault empirical harness.
- [Final multi-collateral integration](multicollateral_integration.md) —
  frozen five-portfolio and seven-shock inputs, counterfactual stable-proxy
  boundary, and validation of one globally ranked shared keeper capacity.
- [Final held-out validation](final_validation.md) — the frozen-model November
  2022 FTX/generalisation and March 2023 USDC/SVB evaluation, classified
  `final_validation_mixed` with an explicit no-retuning declaration.
- [Confidence scenarios](../experiments/confidence_scenarios.md) — joint typed
  input-resolution and scenario-validation contract.

Detailed generated diagnostics remain ignored. Compact, checksum-addressed
validation evidence is retained under `data/provenance/validation/`.
