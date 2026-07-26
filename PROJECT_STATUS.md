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

**Status: Planned**

Continuous reconstruction of every mutation through June 2024 has been
intentionally superseded. The remaining vault-data task is to acquire
representative ordinary, bull-market, crypto-stress, stablecoin-depeg and quiet
mature windows, with one stress window withheld for validation.

This is a methodological change rather than an incomplete or failed
acquisition. The revised design estimates conditional vault behaviour at a
substantially higher information-to-credit ratio while continuous Phase 1A,
Phase 1B and Phase 1C panels continue to identify market regimes, gas
conditions and liquidation arrival frequencies.

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

* Phase 1E-B — representative vault calibration acquisition;
* Milestone 10 — regime-conditioned estimation and bootstrap paths, following
  `docs/parameter_estimation_plan.md`;
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
