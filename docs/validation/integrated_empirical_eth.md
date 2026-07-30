# Integrated empirical ETH-only profile

## Purpose

`empirical_integrated_eth` is an opt-in integration and distributional-
validation harness. It assembles the accepted empirical owners in one
500-vault, 720-hour ETH-only simulation without recalibrating a parameter or
changing a production default. Its overall classification is
`integrated_empirical_eth_profile_ready_with_caveats`.

ETH-only describes the synthetic vault population, not the scope of keeper
capacity. The capacity remains the system-wide Maker count inferred from the
ETH-A/B/C and WBTC-A/B/C evidence.

## Profile components

The profile resolves:

- 500 ETH vaults from the empirical joint debt–collateral-ratio pool;
- exactly 2,500,000 DAI of normalised starting debt;
- aligned 168-hour ETH-return and network-gas blocks from calibration data;
- clean successful-Take gas-unit observations and component gas-cost
  construction;
- the hourly empirical liquidation-arrival hurdle and positive-count pool;
- `shared_keeper_capacity_central`, or 26 system-wide opportunities per hour;
- the `direct_cost_only` hurdle with `risk_cost_rate = 0`;
- the existing full-close liquidation abstraction;
- Stage 1 responses \(\kappa_-=0.199381\) and
  \(\kappa_+=0.105131\);
- accepted 24-hour Stage 1 residual blocks;
- `stage1_only` confidence, fixed at one with zero panic contribution; and
- zero oracle delay, labelled
  `transparent_baseline_not_calibrated`.

The sequence-arrival pool is checksum protected but is not activated
centrally. No persistent-confidence scenario, recovery mechanism, stable
collateral or multi-collateral allocation is active.

## Protected identities

| Owner | SHA-256 |
| --- | --- |
| Vault initialisation | `5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892` |
| Market–gas blocks | `b69276801bacf789f8ae91789983cc98a8a6d42d0a992940c0bcfa109ca25b7d` |
| Keeper gas | `37a5f49f4cc273b9d0d9526609be7f14b91b78939acf26e4dce00b66443e1594` |
| Hourly liquidation arrivals | `cc29435bb0434237aba438ee98bded77f086704c7400bb5016e2b58703258c8a` |
| Arrival-sequence sensitivity | `9fdd5f3b5fb97e2dd41d0201bad34909ad05e423ad6b52f65219f49f02a1c7ed` |
| Keeper configuration | `e1d590508bb3e95ec6bdc2a30c41580fe211831a673dd447e793a0053a7fa848` |
| Keeper registry | `58c5754ed95dead1ad283a7961fb0588496804a94f58ddb0e196a57601ee1e1b` |
| Stage 1 residual sequence | `3fa2319cee9e1749405c0dc477e0f11ef9c31dd83c371b619bd33eda23c37c30` |
| Stage 1 residual blocks | `6f55b51acfc1da23836b3d847153bd4f68e4a38fc33fd967e9d3b795737bf28c` |

The profile identity is
`ab68c32a145262bcef07716469d92be09e3d96506383ad16a07d0ba1bad2b34d`.
The result-blind pre-registration identity is
`85f466ab297094fe4385546cf7c27d3e9f76d8bfdd64e4282c603e844faa1bd7`,
and the scientific code identity is
`f88cdf57e23bca4e56bb768fc0bb6767978d0649419f4d16fbfa964701aa2f4e`.

## Validation design

The immutable specification was written before the successful validation
results. Component A resolves typed owners, checks units, checksums and
non-adoption boundaries. Component B uses 512 independent initialisations,
each with 500 vaults, plus separately seeded market–gas and arrival reference
draws. Component C runs 128 replications of 720 hourly steps. A distinct
240-hour controlled smoke proves that the shared capacity can bind.

The validation registry is separate from calibration registry B, recovery
seeds and final-validation seeds. The FTX withheld interval and USDC/SVB data
are excluded.

## Input-distribution results

All 15 vault moments are inside their source-derived 95% reference bands. The
mean initial debt is exactly 5,000 DAI per vault and total debt is exactly
2,500,000 DAI. The empirical debt–collateral-ratio rank correlation is
retained: the integrated mean is -0.562254 against a reference mean of
-0.562193. No initial vault is liquidatable.

All ten market–gas moments are inside their reference bands. Sampled rows
remain aligned, use 168-hour blocks, belong to the calibration pool and
exclude the FTX withheld period.

Six of seven liquidation-arrival moments are inside their bands. The
integrated mean maximum support is 45.9707 against a degenerate reference
bound of 46, so it is classified `below`. This is a finite-sample
maximum-statistic caveat; the sampler was not retuned. The arrival component
therefore has an inside share of 0.857143 and the overall input classification
is `integrated_empirical_eth_inputs_valid_with_caveats`.

## Dynamic-output results

All 128 replications are numerically valid. Across a 720-hour replication,
the mean values are:

| Metric | Mean |
| --- | ---: |
| Unsafe inventory, hourly | 0.1162 vaults |
| Liquidation arrivals | 60.2266 |
| Selected attempts | 17.8516 |
| Successful closures | 11.2109 |
| Debt repaid | 79,606.35 DAI |
| Maximum unresolved tab | 50,628.94 DAI |
| Maximum backlog duration | 8.1328 hours |
| Realised bad debt | 0 DAI |
| Keeper-profit proxy | 10,116.69 DAI |
| Minimum DAI price | 0.995762 |
| Mean absolute peg deviation | 0.000606 |

Debt-conservation errors are at floating-point rounding scale (maximum
absolute error \(4.08\times10^{-10}\)); collateral-conservation errors are
zero. States are finite and non-negative, and no vault is closed twice.

Historical comparison is deliberately limited. Hourly successful closures
and DAI mean absolute deviation are within their available training-reference
bands. Completed debt, gas-conditioned execution, keeper profit, backlog and
bad debt are marked `reference_not_operational` where the standardised
population or reduced-form mechanism lacks a like-for-like historical
denominator. The output classification is consequently
`integrated_outputs_partially_compatible`, not a claim of predictive fit.

## Shared-capacity validation

The cap is applied once per system hour after demand sampling and global
candidate ranking. It is not an ETH or per-collateral capacity. Across 815
positive-demand replication-hours (0.8843% of all hours), it binds in three
hours (0.3681% of demand hours). Weighted mean utilisation during demand hours
is 0.10783 of capacity, the cross-replication p90 of each replication's
demand-hour p90 is 0.19692, the maximum is one, the maximum selected attempt
count is 26, and the maximum rejected count is 16.

The bounded-demand accounting regression excludes unselected opportunities
from attempted counts. The integration harness therefore uses the
authoritative ranked `attempt_budget` for capacity accounting with no audit
record overcount; the zero overcount remains recorded as a regression-protected
diagnostic.

The controlled smoke uses a fixed ETH price of USD 200 and zero residuals.
It creates at most 437 unsafe vaults, selects at most 26 attempts, rejects 94
opportunities over seven binding hours, carries unresolved inventory forward,
closes no vault twice and retains a finite DAI price. It is a mechanism smoke,
not a recovery experiment.

## Classification and boundaries

- Input: `integrated_empirical_eth_inputs_valid_with_caveats`
- Dynamic output: `integrated_outputs_partially_compatible`
- Overall: `integrated_empirical_eth_profile_ready_with_caveats`
- Experiment ready: true
- Runtime adopted: false

The authorised
[constrained-liquidation recovery experiment](../experiments/constrained_eth_recovery.md)
is now complete. It passed all ownership and numerical gates and found a
capacity-dependent solvency channel without a primary Stage 1 peg effect.
This validates the profile's intended experimental use but does not change its
`runtime_adopted: false` status or authorise parameter tuning,
population-scale robustness, oracle calibration, final multi-collateral
execution or final validation.

The central integration treatment is capacity 26 with `direct_cost_only`.
Capacities 14 and 45, positive hurdle candidates, population sizes 250 and
1,000, and oracle delay remain later sensitivities. Zero oracle delay is a
transparent baseline rather than an estimate.

## Reproducibility

Compact evidence is registered under
`data/provenance/validation/integrated_empirical_eth/`; its eight entries are
checksum-addressed by `data/provenance/validation/manifest.json`. Detailed
diagnostics are ignored under
`outputs/diagnostics/validation/integrated_empirical_eth/<profile_identity>/`.
They occupy 290,413 bytes, below the 300 MB cap. The deterministic compact
payloads were constructed twice and matched byte-for-byte, excluding only
the explicitly host-dependent benchmark fields.

No parameter or confidence coefficient was estimated by this validation, no
multi-collateral experiment ran, no final-validation observation was used,
and no production profile or default was changed. The later constrained
recovery matrix used this profile without modifying it.

## Relation to the final multi-collateral profile

The
[final multi-collateral integration validation](multicollateral_integration.md)
uses this profile's protected 500-vault, 2.5 million DAI population convention,
its median system collateral-ratio target of 3.6089387701260205, Stage 1-only
confidence, zero-delay oracle baseline and central system-wide capacity 26.
It adds independently owned WBTC and explicitly counterfactual stable-proxy
families without changing this ETH-only profile or its evidence.

The new five-portfolio and seven-shock registries are future final-experiment
inputs. They do not retrospectively alter this validation, and their ordinary
dynamic results are integration diagnostics rather than a comparison with the
ETH-only results reported here.
