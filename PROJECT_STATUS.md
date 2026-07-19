# Project Status

## Current branch

- Branch: `feature/multi-collateral`
- Multi-collateral implementation is complete through Experiment 06.
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

Before final robustness analysis:

1. diagnose stable-depeg thresholds;
2. inspect collateral-ratio and distance-to-liquidation distributions;
3. calculate exposure-normalised outcomes;
4. detect equivalent scenario paths and results;
5. select defensible empirical parameter ranges;
6. run multi-seed and shock-severity robustness checks.

## Research decisions reserved for the user

Codex must not decide these silently:

- final collateral parameter calibration;
- final shock magnitudes;
- whether stable depegs directly affect confidence or DAI demand;
- whether oracle delay should vary by collateral;
- changes to realised bad-debt accounting;
- changes to keeper-capacity measurement.