# Project Status

## Current branch

- Branch: `feature/multi-collateral`
- Multi-collateral implementation is complete through Experiment 06.
- Empirical infrastructure is complete through Milestone 9 software validation;
  market, gas, liquidation and protocol evidence has been acquired, while vault
  calibration awaits the planned representative-window sample.
- Changes remain uncommitted unless stated otherwise.

## Completed implementation milestones

### Milestone 1 — Vault and liquidation migration

- Canonical fields: `collateral_amount`, `collateral_type`.
- Scalar and mapped collateral prices supported.
- ETH-only outputs preserved.

### Milestone 2 — Multi-asset price infrastructure

- Canonical `CollateralPricePaths`.
- Market and oracle paths per collateral.
- Legacy ETH path inputs remain supported.

### Milestone 3 — Heterogeneous vault populations

- ETH, BTC, and STABLE may coexist.
- Portfolio allocation uses target debt shares.
- Long-format collateral-level results added.

### Milestone 4 — Collateral-specific risk parameters

- Liquidation ratio.
- Liquidation penalty.
- Maximum close factor.
- Shared keeper capacity retained.

### Milestone 5 — Experiment 06

Portfolios:

- `eth_only`
- `crypto_diversified`
- `balanced`
- `stable_heavy`
- `btc_concentrated`

Shocks:

- `eth_specific_crash`
- `btc_specific_crash`
- `correlated_crypto_crash`
- `stable_depeg`
- `systemic_shock`

### Milestones 7–8 — Market empirical infrastructure

- Configuration-driven UTC source adaptation and explicit unit conversion.
- Aligned market-time panels, calibration/validation samples and stress regimes.
- Transition matrices, empirical pools, overlap reports and descriptive summaries.
- Synthetic validation outputs are separated from real baseline outputs.

### Milestone 9 — Protocol, vault and liquidation empirical panels

- Effective-dated, explicit mapping from source collateral identifiers to ETH,
  BTC and STABLE model classes.
- Long-format protocol-time, vault-snapshot and liquidation-event panels.
- Separate quality reports and descriptive collateral, vault and liquidation
  summaries.
- Real baseline execution remains disabled until source files, mappings and
  complete manifest records are supplied.

## Empirical acquisition status

### Phase 1E-A — Methodology validation

**Status: Complete**

- Authoritative Vat mutation, liquidation-annotation and ownership sources were
  identified and validated.
- Signed mutation values, numeric trace ordering, root traces, deterministic
  source keys, pagination, atomic persistence and resumability were tested.
- Five monthly Vat-mutation chunks from November 2019 through March 2020 were
  validated and retained with their provenance and checksums.
- The work establishes that the acquisition and reconstruction method is
  technically reproducible.

### Phase 1E-B — Representative calibration acquisition

**Status: Quiet-mature, USDC/SVB and Terra/CeFi windows complete**

Continuous reconstruction of every mutation through June 2024 has been
intentionally superseded. The remaining vault-data task is to acquire
representative ordinary, bull-market, crypto-stress, stablecoin-depeg and quiet
mature windows, with one stress window withheld for validation.

The first bounded tranche completed the quiet-mature window. The second
authorised acquisition completed the USDC/SVB window
`[2023-03-06, 2023-03-20)`. Both have authoritative boundary states, canonical
mutations, targeted manager ownership history, sparse accumulated-rate streams
and exact independently reconciled replay. The USDC/SVB acquisition used four
Small executions plus a local Bark extract, consumed 90.800 observed credits
and left 1,482.655 credits. It contains no Bark or grab, so close-factor
identification still relies on complementary liquidation evidence. See
`docs/phase1e_b_tranche1_acquisition_report.md` and
`docs/phase1e_b_usdc_svb_acquisition_report.md`.

The Terra/CeFi window `[2022-05-05, 2022-06-20)` is also complete. Exact
replay reconciles all 5,111 boundary rows; all 649 Barks match canonical grabs
without ambiguity; and 649 simulator-aligned debt close fractions are now
available for Phase 2C review. No parameter has been adopted. See
`docs/phase1e_b_terra_cefi_acquisition_report.md`.

This is a methodological change rather than an incomplete or failed
acquisition. The revised design estimates conditional vault behaviour at a
substantially higher information-to-credit ratio while continuous Phase 1A,
Phase 1B and Phase 1C panels continue to identify market regimes, gas
conditions and liquidation arrival frequencies.

### Phase 2A — Bounded Phase 1A--1D parameter estimation

**Status: Complete**

- All 56 numbered parameter-plan subsections were audited against the current
  simulator interface; the earlier working brief referred to 55.
- Hourly market returns, the two-state market regime, gas conditions,
  liquidation activity, clean Take-transaction costs and effective-dated
  protocol settings were estimated or extracted from validated Phase 1A--1D
  artefacts.
- The FTX interval from 1 November to 21 November 2022 was withheld from every
  calibration threshold and candidate estimate.
- Generated estimates, diagnostics and the 64-entry candidate registry are
  under `data/processed/estimation/phase2a/`; the working report is
  `docs/phase2a_parameter_estimation_report.md`.
- No candidate value has been adopted in simulator configuration. The nine
  vault parameters supported by the completed Phase 1E-B windows have now
  advanced to the separate Phase 2B candidate-estimation review.

### Phase 2A-R — Candidate hardening review

**Status: Complete**

- All 64 candidates were reviewed without changing the original registry:
  12 are ready for later timestamp-selected adoption, 14 require sensitivity
  review, 12 are descriptive only and 26 are blocked by current model mapping.
- Four pre-London successful-Take transactions retain an explicit zero source
  gas price but lack a defensible alternative fee field. The primary later
  estimator should exclude them or mark them missing without imputation, with
  retain-all reported as sensitivity.
- Sparse liquidation activity is represented as an arrival probability plus
  conditional positive severity. Implementing an exogenous hurdle mechanism
  would require separate authorisation because current liquidations are
  endogenous to vault state.
- The two-state classifier detects the withheld FTX disturbance without using
  its label for fitting, but remains provisional under nearby specifications.
- The 168-hour empirical block remains the default candidate, with 72--336
  hours retained as a sensitivity range.
- Review outputs are under `data/processed/estimation/phase2a_review/`; the
  technical report is `docs/phase2a_candidate_review.md`.

### Phase 2B — Representative vault-parameter estimation

**Status: Candidate estimation complete; adoption review pending**

- Nine authorised vault-population candidates were estimated from the
  validated quiet-mature and USDC/SVB windows without using the withheld FTX
  interval or changing simulator configuration.
- Debt and collateral-ratio evidence is strongly right-skewed, so the current
  global Gaussian inputs remain provisional distribution choices rather than
  adopted values.
- Debt composition and the normal/stress liquidatable-share thresholds are
  ready for review; the simulation population remains a provisional scaling
  choice.
- Terra/CeFi supplies 649 exactly linked full-closure grabs, so
  `max_close_factor` is methodologically ready for Phase 2C estimation and
  review. The existing Phase 2B registry remains unchanged.
- Bull expansion remains useful for leverage and composition sensitivity, but
  is no longer required to resolve the close-factor evidence blocker.
- Reproducible outputs are under
  `data/processed/estimation/phase2b_vaults/`; see
  `docs/phase2b_vault_parameter_estimation_report.md`.

### Phase 2C — Liquidation and stress-tail review

**Status: Candidate review complete; model-design decision pending**

- The simulator's `max_close_factor` is a per-vault debt-close fraction, not
  keeper throughput. All 649 exact Terra/CeFi Bark–grab matches close the full
  unsafe urn position, supporting `1.0` as a protocol-level review candidate.
- Clipper Take fractions, liquidation sequences and throughput remain distinct
  empirical quantities. Auction execution and a hurdle arrival process would
  require new optional interfaces and have not been implemented.
- The Phase 2B USDC/SVB stress-share value is retained as moderate-stress
  evidence; Terra/CeFi adds a severe-window q95 and maximum without pooling the
  regimes.
- No candidate has been adopted and no simulator configuration or mechanics
  have changed. See
  `docs/phase2c_liquidation_parameter_estimation_report.md`.

### Parameter-adoption and model-interface review

**Status: Tranches A, B and C complete**

- All 56 authoritative parameter subsections and 70 material implemented
  configuration/runtime fields (including all 50 live dataclass fields) are
  mapped to one primary adoption class.
- The review preserves 80 Phase 2A–2C candidate records without pooling
  conflicting regimes, collaterals or semantic stages.
- The separate configuration-only empirical bundle has been implemented as an
  explicit opt-in path. It retains all legacy defaults and established
  experiments.
- Distribution-aware vault initialisation has also been implemented as a
  separate opt-in Tranche B path using compact representative-regime sampling
  pools. It does not change the legacy default generator or Tranche A
  configuration-only behaviour.
- Empirical market-return block bootstrapping and empirical gas-input
  generation have been implemented as a separate opt-in Tranche C path. Legacy
  GBM and scalar gas remain the defaults.
- Regime switching, liquidation-arrival and behavioural changes remain later,
  separately gated tranches. See
  `docs/parameter_adoption_and_model_interface_plan.md` and
  `docs/tranche_a_empirical_configuration_report.md` and
  `docs/tranche_b_distributional_vault_initialisation_report.md` and
  `docs/tranche_c_empirical_market_and_gas_report.md`.

## Current outputs

Results:

`outputs/results/06_multicollateral/`

Figures:

`outputs/figures/06_multicollateral/`

Experiment 06 produces:

- `system_results.csv`
- `collateral_results.csv`
- `system_summary.csv`
- `collateral_summary.csv`

## Preliminary findings

- Balanced and stable-heavy portfolios reduce systemic bad debt relative to
  ETH-only.
- Diversification between ETH and BTC provides limited protection under
  correlated crypto shocks.
- Stable-heavy currently appears most resilient.
- The current stable-depeg scenario generates no liquidation or bad debt.
- `systemic_shock` currently produces the same outcomes as
  `correlated_crypto_crash`, indicating that the STABLE component is not
  materially binding under the present assumptions.

These are preliminary stylised findings and are not yet final dissertation
conclusions.

## Known limitations

- Shock magnitudes are not yet empirically calibrated.
- Results currently rely on a limited seed configuration.
- Stable collateral has no direct confidence or DAI-demand transmission channel.
- One oracle delay applies to all collateral paths.
- Stable-depeg resilience may reflect the current collateral-ratio distribution
  rather than a generally robust economic conclusion.
- Existing ETH-specific system columns are retained for backward compatibility.

## Next research stage

Research question: **How do collateral composition, cross-asset dependence
and liquidation frictions jointly affect DAI
solvency and peg resilience under market stress?**

Sequence:

* next empirical-interface tranche, subject to explicit authorisation and the
  gates in `docs/parameter_adoption_and_model_interface_plan.md`;
* Milestone 11 — model calibration and withheld-window validation;
* Milestone 12 — empirically calibrated counterfactual experiments.

## Research decisions reserved for the user

Codex must not decide these silently:

- final collateral parameter calibration;
- final shock magnitudes;
- whether stable depegs directly affect confidence or DAI demand;
- whether oracle delay should vary by collateral;
- changes to realised bad-debt accounting;
- changes to keeper-capacity measurement.
