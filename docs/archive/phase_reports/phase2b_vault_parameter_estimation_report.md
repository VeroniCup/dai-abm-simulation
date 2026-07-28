# Phase 2B Vault Parameter Estimation Report

## Scope

Phase 2B estimates nine review-only vault-population candidates from two
validated representative regimes:

- quiet mature: `[2024-02-01 00:00 UTC, 2024-03-01 00:00 UTC)`;
- USDC/SVB: `[2023-03-06 00:00 UTC, 2023-03-20 00:00 UTC)`.

The windows are purposive conditional samples. Their contrasts are descriptive,
not causal, and they are not weighted as though they formed a random continuous
history. The withheld FTX interval is absent. No candidate has been written to
configuration, no simulator interface has changed, and `max_close_factor` has
not been estimated.

## Datasets and integrity gates

The estimator uses the opening and closing vault states, reconstructed economic
mutations and effective accumulated-rate streams for both windows. It joins
these locally to the Phase 1A hourly ETH/WBTC prices, the Phase 1D
effective-dated liquidation ratios and the frozen Phase 2A hourly regime
classifier.

All eleven authoritative inputs passed SHA-256, schema, boundary and population
checks. The two reconstructions had already passed exact opening-to-closing
replay. Boundary keys were unique, the population contained exactly ETH-A,
ETH-B, ETH-C, WBTC-A, WBTC-B and WBTC-C, and no FTX timestamp entered any
calculation. The hourly reconstruction uses numeric trace ordering and accepts
a missing serialised trace only for the validated synthetic opening-rate record
or an observed top-level `Jug.drip`.

## Implemented semantics

The implementation audit established the following meanings before estimation.

- `SimulationConfig.n_vaults` is one synthetic population size. It is neither
  an observed collateral-specific count nor an instruction to reproduce the
  entire Maker population.
- `CollateralConfig.target_debt_share` is the share of total sampled system
  debt assigned to each model collateral class. It is not the share of active
  vaults that have debt.
- `debt_mean` and `debt_std` are global raw-level Gaussian inputs in the current
  vault generator.
- `collateral_ratio_mean` and `collateral_ratio_std` are global raw-level
  Gaussian inputs. The generator clips the lower tail at the collateral's
  liquidation ratio plus a separate absolute buffer.
- `min_collateral_ratio_buffer` is an absolute dimensionless difference,
  `collateral ratio - liquidation ratio`.
- both confidence thresholds use the share of liquidatable vaults divided by
  all active vaults. Active-indebted and valid-ratio denominators are retained
  as sensitivity diagnostics.

## Population and statistical methods

Debt, collateral-ratio and buffer distributions use active indebted vaults:
the urn must be active, have strictly positive exact reconstructed debt and,
where needed, a valid collateral value, rate and effective liquidation ratio.
Debt is calculated from integer Maker state before conversion. Collateral ratio
is reported as a dimensionless multiple:

\[
\mathrm{CR}_{i,t}
=
\frac{\mathrm{collateral}_{i,t}\times\mathrm{price}_{t}}
{\mathrm{art}_{i,t}\times\mathrm{rate}_{i,t}/10^{45}}.
\]

Cross-sectional uncertainty uses a fixed seed of `20260726` and 400 percentile
bootstrap replications. Each boundary contains one row per urn, so the urn is
the resampling unit. Owner-proxy clustering is a sensitivity only: mapped
manager owners form clusters and unmapped positions remain urn-specific.
Manager ownership is not interpreted as beneficial ownership. Hourly q95
liquidatable-share uncertainty uses a 24-hour moving-block bootstrap, which
preserves short local runs and avoids treating consecutive hours as
independent.

Raw distributions remain primary. The output also records medians, lower and
upper quantiles, log moments and q99-winsorised sensitivities. Large positions
are not removed.

## Candidate results

The values below are candidates for review, not adopted calibration values.

### `n_vaults`

Observed active counts range from 3,258 to 3,381 across the four boundaries;
active indebted counts range from 1,852 to 1,934. The candidate is **500
synthetic vaults**, with 100, 250, 500 and 1,000 retained for convergence
sensitivity. Relative to the 3,296 quiet-opening active vaults, 500 represents a
6.592-to-one population scaling factor. Its status is
`provisional_scaling_choice`: adoption requires a simulation-size convergence
test.

### `target_debt_share`

The quiet-opening six-ilk debt composition gives **ETH 0.848394** and
**BTC 0.151606**. Urn-bootstrap 95% intervals are `[0.732409, 0.911942]` and
`[0.084853, 0.245190]`, respectively. Exact-ilk quiet-opening shares are:

| Ilk | Debt share |
|---|---:|
| ETH-A | 0.267412 |
| ETH-B | 0.091074 |
| ETH-C | 0.489909 |
| WBTC-A | 0.058209 |
| WBTC-B | 0.033180 |
| WBTC-C | 0.060217 |

The USDC/SVB opening family shares are ETH 0.874199 and WBTC 0.125801.
Opening, closing and exact-ilk alternatives remain in the generated table.
The candidate is `ready_for_review`, but it represents an observed
six-ilk baseline rather than a counterfactual portfolio. There is no STABLE
share estimate in this evidence.

### `debt_mean` and `debt_std`

Among 1,886 quiet-opening active indebted vaults, the raw mean is
**468,757.70 DAI** with an urn-bootstrap 95% interval of
`[304,867.27, 673,545.90]`. The raw sample standard deviation is
**4,401,408.32 DAI**, with interval `[2,070,966.79, 6,481,807.44]`.
The median is only 20,158.22 DAI, q95 is 931,352.50 DAI and the maximum is
140,372,200 DAI. Skewness is 21.65 and the coefficient of variation is 9.39.
The q99-winsorised mean and standard deviation are 212,692.82 and 730,049.09
DAI.

The corresponding USDC/SVB opening raw mean and standard deviation are
357,026.48 and 2,758,663 DAI. Quiet-opening ETH and WBTC means are 482,344.53
and 404,928.34 DAI; their medians are 15,674.60 and 52,962.46 DAI.
Exact-ilk differences are material. Both global candidates are therefore
`provisional_distribution_choice`.

The empirical evidence favours exact-ilk empirical resampling, or at least
log-scale collateral-specific distributions, over a global raw Gaussian.
The current interface accepts only global raw moments. Until a separately
authorised interface change, the raw moments are reproducible scalar
diagnostics rather than a recommendation to ignore the tail mismatch.

### `collateral_ratio_mean` and `collateral_ratio_std`

The quiet-opening raw mean is **15.160135** and its 95% bootstrap interval is
`[11.858675, 19.562662]`. The raw standard deviation is **91.158713**, with
interval `[20.676341, 144.281632]`. The median is 4.455997, q95 is 41.613288
and the maximum is 3,108.182798. Skewness is 27.72. Q99 winsorisation reduces
the mean and standard deviation to 11.536019 and 16.668528.

The quiet-opening ETH mean is 17.496662, compared with 4.183401 for WBTC.
USDC/SVB opening means are 13.384840 for ETH and 3.328778 for WBTC. Exact-ilk
means range from 2.623307 for WBTC-B to 24.261425 for ETH-A. Because ilks have
different liquidation ratios, the buffer estimates below provide the
threshold-normalised lower-tail comparison.

Both candidates are `provisional_distribution_choice`. The current global
Gaussian interface loses the observed upper tail, exact-ilk heterogeneity and
dependence between debt and leverage. A later interface review should consider
empirical joint resampling; Phase 2B does not implement it.

### `min_collateral_ratio_buffer`

The candidate is the quiet-opening q05 absolute buffer,
**0.492758**, with bootstrap interval `[0.422145, 0.531862]`. The sample
minimum is 0.065407, q01 is 0.190712 and q10 is 0.684886. The corresponding
relative q05, `CR/LR - 1`, is 0.315962. No quiet-opening estimation row has a
zero or negative buffer.

Exact-ilk q05 absolute buffers range from 0.178243 for ETH-B to 0.651905 for
ETH-A. The lower-tail evidence therefore varies materially across ilks. The
candidate matches the simulator's absolute units, avoids choosing the literal
minimum and remains `provisional_distribution_choice`: the buffer is a
generator safeguard rather than a protocol threshold.

### `max_normal_liquidatable_share`

The candidate is the quiet-window q95 hourly liquidatable share,
**0.000000**, with a moving-block-bootstrap interval `[0, 0]`. None of the
696 quiet-window hours contains an economically liquidatable vault under the
effective Phase 1D threshold. The same result holds for the 685 hours that the
frozen Phase 2A classifier labels normal and for the alternative indebted and
valid-ratio denominators.

This is `ready_for_review`, not evidence that liquidation vulnerability is
impossible in ordinary markets. It is a conditional result for this window and
must be sensitivity-tested against other ordinary periods before adoption.

### `max_stress_liquidatable_share`

The primary candidate is the q95 among the 42 USDC/SVB hours classified as
stress: **0.000577546**, with moving-block-bootstrap interval
`[0, 0.000888626]`. The conditioned q99 is 0.001063803 and the maximum is
0.001185536. Four of the 42 stress-classified hours contain at least one
liquidatable position. Across all 336 named-window hours, q95 remains zero and
the maximum remains 0.001185536. The maximum sensitivity using active indebted
vaults is 0.002074.

This candidate remains `ready_for_review`, and its source USDC/SVB window has
no Bark or grab. The subsequently completed Terra/CeFi reconstruction now
supplies the missing descriptive stress-tail comparison. Calculated
liquidatable state, liquidation initiation and realised Vat state mutation
remain distinct, so no threshold is adopted here.

## Distribution and cross-window diagnostics

Debt and collateral ratio are extremely right-skewed in both windows. The raw
quiet-opening means are respectively 23.8% and 23.1% above their USDC/SVB
opening counterparts, but these are cross-window descriptions rather than
causal stress effects. Active population counts differ by only 2.6% at the
opening boundaries. The quiet closing boundary has fewer indebted vaults but
higher collateral-ratio moments than its opening boundary, illustrating why
opening and closing rows are reported separately.

At quiet opening, 588 of 1,886 positive-debt positions lie below the
effective protocol dust value recorded in the joined state. They are not
dropped: a small historical residual balance can remain positive without
being a newly creatable debt position. This reinforces the need to report
medians and empirical tails instead of silently trimming the population.

Owner-proxy concentration is low in the mapped records: the largest mapped
owner proxy represents about 0.22% of active vaults. The quiet-opening
owner-proxy-or-urn clustered intervals are `[292,271.03, 681,436.87]` for mean
debt and `[11.697964, 19.981546]` for mean collateral ratio. They do not alter
the qualitative heavy-tail conclusion. Owner is retained only as a dependence
diagnostic.

## Current-configuration comparison

| Parameter | Current reference | Candidate | Diagnostic result |
|---|---:|---:|---|
| `n_vaults` | 100 | 500 | Current value is within the 100--1,000 convergence range |
| ETH `target_debt_share` | 0.60 | 0.848394 | Outside bootstrap interval |
| BTC `target_debt_share` | 0.40 | 0.151606 | Outside bootstrap interval |
| `debt_mean` | 5,000 | 468,757.70 | Outside interval |
| `debt_std` | 1,000 | 4,401,408.32 | Outside interval |
| `collateral_ratio_mean` | 2.00 | 15.160135 | Outside interval |
| `collateral_ratio_std` | 0.25 | 91.158713 | Outside interval |
| absolute buffer | 0.05 | 0.492758 | Outside interval |
| normal liquidatable share | 0.05 | 0 | Different frequency interpretation; outside interval |
| stress liquidatable share | 0.30 | 0.000577546 | Different frequency interpretation; outside interval |

This comparison is diagnostic. A difference does not by itself imply that the
model is erroneous: several existing values are deliberately stylised, the
vault generator has restrictive Gaussian interfaces, and the confidence fields
act as reduced-form thresholds rather than direct historical frequencies.

## Candidate status and interface review

Three candidates are `ready_for_review`: debt composition, normal liquidatable
share and stress liquidatable share. Five distributional candidates are
`provisional_distribution_choice`, and `n_vaults` is
`provisional_scaling_choice`. None is adopted.

The existing simulator directly accepts a single `n_vaults`, global debt and
collateral-ratio moments, one global buffer argument, collateral-specific debt
shares and global normal/stress confidence thresholds. It does not accept an
empirical joint debt/leverage sampler, exact-ilk distributions, time-varying
vault populations or regime-specific initial-state distributions. The minimum
future interface change would be an optional empirical or collateral-specific
vault sampler that preserves the existing Gaussian default. Such a change is
not part of this phase.

## `max_close_factor` follow-up

The original two-window run correctly left `max_close_factor` as
`insufficient_evidence` and created no candidate record. The subsequently
completed Terra/CeFi reconstruction supplies 649 exact pre-grab observations,
all of which are full debt and collateral closures. A separate Phase 2C review
is now methodologically justified; this Phase 2B output remains immutable.

## Limitations and next evidence

- Two representative windows cannot identify unconditional vault-state
  frequencies or a universal historical maximum.
- The USDC/SVB window captures stress in the Phase 2A classifier but contains
  no realised Bark or grab.
- The current scalar Gaussian interfaces poorly represent the observed debt
  and collateral-ratio tails.
- ETH and WBTC are covered; this evidence does not estimate a STABLE
  collateral vault distribution.
- Manager owner is an identity proxy, not a beneficial owner.
- Bull-expansion acquisition remains optional for leverage, borrowing and
  collateral-composition sensitivity; it is no longer needed to unblock
  liquidation-tail evidence.

The next review should decide whether to retain scalars as deliberate
reduced-form inputs or separately authorise an empirical sampler. It should not
write these candidates into YAML until the convergence, distribution and
stress-tail sensitivities have been reviewed.

## Reproducibility outputs

The machine-readable candidate registry and all supporting tables are under
`data/processed/estimation/phase2b_vaults/`. The principal artefacts are:

- `phase2b_parameter_candidates.json`;
- `phase2b_parameter_status.csv`;
- `vault_count_estimates.csv`;
- `target_debt_share_estimates.csv`;
- `debt_distribution_estimates.csv`;
- `collateral_ratio_estimates.csv`;
- `collateral_ratio_buffer_estimates.csv`;
- `liquidatable_share_estimates.csv`;
- `cross_regime_comparison.csv`;
- `estimation_diagnostics.csv`; and
- `phase2b_run_metadata.json`.

The run metadata records every input and output checksum, the processing-script
checksum, fixed seed, resampling settings and explicit assertions that network
access, configuration writes, FTX use and `max_close_factor` estimation were
all absent.

## Terra/CeFi follow-up status

The bounded Terra/CeFi run is complete. Its exact state replay reconciles all
5,111 closing boundary rows and links 649 Barks to 649 canonical grabs without
ambiguity. This report's existing candidates remain unchanged, but
`max_close_factor` is now methodologically ready for separate Phase 2C
estimation and review. See
`phase1e_b_terra_cefi_acquisition_report.md`.

## Phase 2C review outcome

The separate Phase 2C review is complete. It confirms that
`max_close_factor` is the share of one vault's debt repaid in one simulated
liquidation, while `max_liquidations_per_step` is the distinct keeper-capacity
control. All 649 Terra/CeFi grabs support `1.0` only as a protocol-close
candidate; per-Take auction fractions are retained separately and no candidate
has been adopted. The Phase 2B USDC/SVB stress threshold remains labelled
moderate-stress evidence rather than being overwritten by Terra/CeFi.
See `phase2c_liquidation_parameter_estimation_report.md`.

The consolidated adoption review now places the Phase 2B vault moments in a
distribution-aware initialisation tranche, while target debt shares and the
normal buffer remain configuration candidates with sensitivity gates. No
Phase 2B value has been adopted. See
`parameter_adoption_and_model_interface_plan.md`.
