# Phase 2C liquidation and stress-tail parameter review

## Scope

Phase 2C uses the validated Terra/CeFi representative window, 5 May to
20 June 2022, to review liquidation-close semantics, auction execution,
liquidation clustering and the two Phase 2B stress-tail candidates. The work is
local and review-only. It does not acquire data, change simulator mechanics,
write configuration or adopt a candidate.

The run verifies the recorded checksums of the Terra/CeFi close-factor,
Bark–grab, stress-tail, event, snapshot, validation and auction files, together
with the Phase 1C actions and Phase 1A/1D panels. The reconstruction still has
649 exact Bark–grab links, no negative reconstructed states, no replay
mismatches and all six target ilks. Neither FTX nor bull-expansion evidence is
used.

## Semantic audit

`LiquidationConfig.max_close_factor` is the maximum fraction of one vault's
outstanding DAI debt repaid in one simulated liquidation. The same fraction is
used in keeper-profit assessment and execution. `Vault.partial_liquidate`
removes collateral worth the repaid debt plus the liquidation penalty, capped
by available collateral, and may close a position terminally when a partial
operation would worsen bad debt.

This is not a throughput control. `LiquidationConfig.max_liquidations_per_step`
separately caps the number of profitable vault liquidations performed in one
step after profit ranking.

Maker's `Vat.grab` is the closest empirical analogue to the close factor at the
protocol state-transition level. In every linked Terra/CeFi case it transfers
the full unsafe urn position: both `abs(grab.dart) / pre-grab art` and
`abs(grab.dink) / pre-grab ink` equal one. Clipper can nevertheless sell the
resulting auction lot through one or more Takes. The current simulator combines
the protocol transition and keeper execution into one stage; therefore a
full-vault grab is not evidence that every keeper Take processes the full
auction.

The three interpretations are consequently:

1. protocol close: the evidence supports a review candidate of `1.0`;
2. capacity: this is represented by `max_liquidations_per_step`, not by
   `max_close_factor`; and
3. auction execution: per-Take fractions are a distinct empirical
   distribution for which the current model has no field.

## Close-factor evidence

All 649 Bark–grab matches are usable. There are no zero denominators, excluded
observations or partial closures. The debt and collateral distributions both
have mean, median, minimum and maximum equal to `1.0`, with exactly zero
dispersion. This result remains exact by ilk, calendar day, one-hour-gap
liquidation sequence, debt-size quartile and pre-liquidation buffer quartile.
DAI debt removed is reconstructed as
`abs(grab.dart) × effective rate / 1e45`.

No numerical standard error is reported because the distribution is
degenerate. The uncertainty is structural: whether the single-stage simulator
should continue to represent the protocol close, or whether protocol
initiation and auction execution should later be split.

The review status for `max_close_factor = 1.0` is
`protocol_value_ready_for_review`. It is not adopted.

## Auction execution evidence

The 649 Terra/CeFi auctions contain 676 successful Take events. All auctions
have at least one Take and all have the provisional terminal classification
`target_cleared`; 20 auctions have more than one Take and the maximum is eight.
The median debt fraction settled by a Take is `1.0`, but the minimum is
`0.0002103`, confirming genuine partial execution. The median fraction of the
initial lot purchased per Take is `0.79449`.

Across auctions, median elapsed time from Bark to 25%, 50%, 75% and 100% of
the auction debt target is approximately 1,773, 1,775, 1,775 and 1,775
seconds, respectively. The observed completion range is 746–2,527 seconds.
Exact-ilk differences and every decoded remaining-state progression are kept
in `auction_execution_fractions.csv`.

These figures describe auction execution, not vault closure. They support a
distinct empirical Take-size or completion distribution only. Adding such a
distribution would require a new interface and explicit multi-stage auction
mechanics.

## Liquidation clustering

The 649 grabs form 54 sequences when a gap of more than one hour starts a new
sequence. The median sequence contains five grabs and five urns; the mean is
12.02 and the maximum is 84. The longest sequence lasts 7,194 seconds and is
also the largest, beginning at 05:00:12 UTC on 12 May 2022. The largest
debt-removal sequence removes approximately DAI 15.80 million and begins at
10:00:24 UTC on 13 June.

Across all 1,104 hours, mean grabs per hour are `0.5879`, the variance is
`12.3440`, the zero share is `0.9411` and the maximum is 46. A Poisson process
with the same mean would imply a zero share of only `0.5555`. The
variance-to-mean ratio is approximately `21.0`; the maximum daily total is
170. This is strong descriptive evidence of a quiet-state hurdle and clustered
positive counts.

A negative-binomial count can represent overdispersion but not the explicit
quiet hurdle. A self-exciting interpretation is plausible, but a Hawkes model
would add complexity unsupported by the present methodology. The transparent
review candidate is therefore a hurdle plus the empirical positive-count and
sequence distributions. This is blocked by the current model interface and
has not been implemented.

## Stress-tail liquidatable share

The denominator remains all active urns in the relevant collateral scope at
the start of each UTC hour. For the named Terra/CeFi window, the global mean is
`0.000410`, the median and q90 are zero, q95 is `0.001853`, q99 is
`0.009392`, and the maximum is `0.028470`. The Phase 2B USDC/SVB threshold
`0.000577546` is exceeded in 90 Terra/CeFi hours, across 27 episodes, with a
longest run of eight hours. The current configuration threshold `0.30` is
never approached.

The Phase 2A classifier identifies 215 Terra/CeFi stress hours. Within them,
the global q95 is `0.009503` and the mean is `0.001836`; the named-window
results and classifier-conditioned results remain separately labelled.

The largest exact-ilk maxima are:

| Ilk | Maximum |
|---|---:|
| ETH-A | 0.026731 |
| ETH-B | 0.068702 |
| ETH-C | 0.041451 |
| WBTC-A | 0.024948 |
| WBTC-B | 0.100000 |
| WBTC-C | 0.032258 |

Small-ilk maxima have small denominators and must not be pooled as if they had
the same precision as the system share.

The USDC/SVB candidate is much smaller because that representative interval
contains classifier stress but no realised Bark or grab, whereas Terra/CeFi
contains concentrated crypto-collateral liquidations. It should be retained
as moderate-stress evidence and combined with the Terra/CeFi q95 and maximum
as a labelled severity hierarchy. The scalar simulator interface cannot
preserve that hierarchy without selecting a declared scenario threshold.

## Collateral-ratio buffer review

The Phase 2B value `0.492758` is an absolute q05 buffer used as normal
initialisation evidence. Terra/CeFi does not invalidate that interpretation:
the Terra opening-state absolute q05 is `0.419827` (urn-cluster 95% interval
`0.390389–0.448869`) and the relative q05 is `0.281102`.

Stress-state evidence is quite different:

| State | Measure | Minimum | q01 | q05 | q10 | Median | At/below zero |
|---|---|---:|---:|---:|---:|---:|---:|
| Pre-liquidation | Absolute | -0.148340 | -0.126896 | -0.107397 | -0.083825 | -0.022669 | 72.73% |
| Pre-liquidation | Relative | -0.088531 | -0.084270 | -0.072271 | -0.056003 | -0.014855 | 72.73% |
| All post-event stress states | Absolute | -0.118976 | -0.037030 | 0.003526 | 0.031232 | 0.425187 | 4.48% |
| All post-event stress states | Relative | -0.073291 | -0.024258 | 0.002407 | 0.021592 | 0.288994 | 4.48% |

The output also reports ETH, WBTC and exact-ilk estimates, q05 urn-cluster
intervals and frequencies within five percentage points of liquidation. The
quiet/USDC Phase 2B candidate remains suitable for review as a normal
initialisation floor, not as a description of stress dynamics, and is not
replaced by the Terra minimum.

## Model-interface findings

| Quantity | Current representation | Review result |
|---|---|---|
| `max_close_factor` | scalar with optional collateral override | directly compatible at protocol-close level |
| `max_liquidations_per_step` | shared scalar count cap | empirical evidence needs a timestep-specific scalar reduction |
| stress liquidatable share | global scalar threshold | labelled severity hierarchy needs a declared scenario or new regime interface |
| initial ratio buffer | global absolute scalar floor | directly compatible for normal initialisation |
| auction execution fraction | absent | requires a new field and multi-stage execution |
| liquidation arrivals | absent | requires a distribution interface |
| auction duration | absent | descriptive only without auction mechanics |

Current defaults are `1.0` for `max_close_factor`, no throughput cap, `0.30`
for the stress liquidatable-share threshold and `0.05` for the minimum
initialisation buffer. Established experiments deliberately use close factors
of `0.3` or `0.5` and count caps of 2–20. Changing these later would alter
repayment, collateral removal, keeper profitability, backlog and bad debt, so
backward-compatible defaults and existing experiments require explicit review.
A semantic mismatch must not be treated as a numerical calibration failure.

## Candidate recommendations

- `max_close_factor = 1.0`: `protocol_value_ready_for_review`; adoption requires
  a decision to retain the one-stage protocol-close abstraction.
- `max_liquidations_per_step`: `provisional_distribution_choice`; retain the
  empirical hourly/sequence distribution and select scalars only for declared
  sensitivities.
- liquidation arrival process: `blocked_by_model_interface`; a transparent
  hurdle representation is preferred to Poisson.
- auction execution fraction: `blocked_by_model_interface`; retain separately
  from the protocol close.
- `max_stress_liquidatable_share`:
  `provisional_distribution_choice`; preserve moderate and severe labelled
  evidence rather than pooling.
- `min_collateral_ratio_buffer`: `ready_for_review` as normal initialisation
  evidence; Terra values are stress validation only.
- auction duration: `descriptive_only`.

No candidate is adopted.

## Statistical uncertainty and limitations

The run uses seed `20260726`, 400 day-block, urn-cluster and
liquidation-sequence bootstrap replications where applicable. Close-factor
dispersion remains exactly zero. The purposively selected Terra/CeFi window is
not an unconditional historical sample; exact-ilk tails with few active vaults
are noisy; decoded Take progression cannot identify omitted off-chain bidding
or a keeper's full decision process; and the current simulator has no explicit
auction lifecycle.

## Recommended next model-design decision

The minimum-change option is to retain `max_close_factor` as the protocol-close
fraction, review `1.0`, and leave `max_liquidations_per_step` as the separate
capacity control. If the dissertation needs auction timing or partial keeper
execution, add a distinct optional auction-execution distribution while
preserving the existing one-stage defaults and Experiments 1–5. No such change
is made in Phase 2C.

Reproducible review artefacts are under
`data/processed/estimation/phase2c_liquidations/`.

The consolidated adoption review retains `max_close_factor = 1.0` as the only
directly configuration-ready Phase 2C candidate, while auction execution,
clustered arrivals and regime-specific stress thresholds remain separately
gated interface decisions. No value has been adopted. See
`parameter_adoption_and_model_interface_plan.md`.
