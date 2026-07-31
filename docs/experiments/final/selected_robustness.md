# Selected robustness layer

## Scientific role

This is the pre-registered evaluative robustness layer for the completed final
Experiments A–E and the H4 evidence synthesis. It does not recalibrate a
parameter, choose a treatment or amend an earlier decision. It asks whether
four inherited conclusions remain defensible under three outstanding
one-at-a-time dimensions: population size, empirical market-block length and
the registered positive keeper hurdle. Sustained-recovery duration is a
metric-definition sensitivity applied to the same simulated DAI paths.

The content-addressed robustness identity is recorded in the compact
specification under
`data/provenance/experiments/final/selected_robustness/`.

## Coverage audit

Capacity, oracle delay, confidence scenarios, recovery paths, portfolio
endpoints and shock definitions were already covered by the completed final
experiments. Repeating them here would turn a selected robustness layer into
an unregistered factorial search. They are therefore frozen rather than
rerun.

The remaining matrix contains four contrast families, two portfolio roles,
seven one-at-a-time settings and 64 paired replications: 56 cells and 3,584
substantive simulations. All cells retain 2.5 million DAI total debt, initial
system collateralisation of 3.6089387701260205, shared capacity 26, zero
oracle delay, Stage 1-only confidence and the 24-hour DAI residual-block
owner.

## Contrast families

| Identifier | Frozen shock | Reference | Treatment | Inherited conclusion |
| --- | --- | --- | --- | --- |
| R-A | `eth_idiosyncratic_severe` | `eth_only` | `stable_supported` | isolated-shock diversification |
| R-B | `joint_crypto_high_correlation` | `eth_only` | `stable_supported` | diversification weakens but does not reverse |
| R-C | `joint_crypto_stable_stress` | `empirical_crypto` | `stable_supported` | stable support buffers combined stress |
| R-D | `stable_depeg_severe` | `stable_supported` | `stable_heavy` | stable-exposure gradient remains inconsistent |

R-D is intentionally not forced into a directional “stable-heavy is better”
claim. Its inherited C2 result is retained unless heavier stable exposure
produces a clear adverse gradient in at least two registered primary metrics.
The stable-attributed and exposure-normalised liquidation measures are part of
that decision together with the three system measures.

## One-at-a-time settings

The baseline uses 500 vaults, a 168-hour empirical market block and direct
cost only. The six non-baseline settings replace exactly one coordinate:

- 250 or 1,000 vaults;
- 72- or 336-hour aligned ETH/WBTC market blocks; or
- `risk_cost_rate` 0.105100900480 or 0.124431757397, in the keeper registry's
  unit of fraction of debt repaid.

Population streams are nested by family and exact ilk. Total debt, debt-share
portfolios and initial system collateralisation remain fixed. Market blocks
share result-blind start uniforms, exclude the November 2022 FTX and March
2023 USDC/SVB holdouts and do not alter the 24-hour DAI residual-block
process. The positive hurdle coordinates are registered sensitivities, not
point estimates.

## Recovery-definition sensitivity

Each DAI path is assessed using 12, 24 and 48 consecutive hours inside
0.995–1.005. This recalculates RMST, recovery probability and censoring from
one path. It does not alter the DAI path, confidence state, liquidation
execution or the registered 24-hour primary definition.

## Decision rules and validity

Every portfolio difference is paired by replication. The evidence reports raw
and direction-normalised means, standard errors, 95% intervals, quantiles,
operationality, materiality and sign relative to the inherited conclusion.
No aggregate resilience score is constructed.

A contrast is robust when at least five of six non-baseline settings retain
the inherited result, the baseline reconstructs it and no setting supplies a
clear two-metric reversal. Four retained settings yield a qualified result;
fewer than four yield sensitivity dependence. Two clear two-metric reversals
produce `reversed_under_sensitivity`. Accounting, numerical, path, common-
random-number or held-out-boundary failure is invalid rather than an
unfavourable scientific outcome.

## Execution and results

The authoritative eight-worker execution completed all 3,584 simulations in
2,120.504 seconds (1.690 simulations per second). Its 64 valid checkpoints
occupy 15,487,097 bytes; the audit found no missing, duplicate or orphan
checkpoint. The content-addressed identity is
`59474cbc9e37d7df5d49fb5b9a0abbf4670ce300799f82ccb0ec21ed8a3aebbf`.

Every contrast reconstructed its inherited baseline direction, retained that
direction in all six non-baseline settings and had no clear two-metric
reversal:

| Family | Result | Retained settings | Interpretation |
| --- | --- | ---: | --- |
| R-A | `robust` | 6/6 | Isolated-shock diversification remains favourable. |
| R-B | `robust` | 6/6 | The registered correlated-stress result remains a weakened benefit without reversal. |
| R-C | `robust` | 6/6 | Stable support continues to buffer the combined registered stress. |
| R-D | `robust` | 6/6 | The inconsistent stable-exposure gradient remains the defensible conclusion. |

Population changes affected magnitudes, especially R-C at 250 vaults, but
did not reverse a registered conclusion. The direction-normalised advantages
across the three system metrics ranged from 0.0258–0.0659 for R-A and
0.0257–0.0659 for R-B at 250 vaults; 0.0154–0.0723 and
0.0154–0.0723 respectively at 1,000 vaults. For R-C they ranged from
0.00127–0.0111 at 250 and 0.00626–0.0562 at 1,000. R-D remained mixed at the
system-metric level, including one negative mean backlog contrast at 250
vaults, while neither stable-attributed liquidation metric activated. That
pattern is evidence for retaining the inherited null/inconsistent gradient,
not for selecting a population.

The 72- and 336-hour market blocks also changed magnitudes without changing
directions. R-A and R-B system-metric advantages ranged from 0.0174–0.0461
at 72 hours and 0.0124–0.0524 at 336 hours. R-C ranged from
0.00979–0.0229 and 0.0173–0.0752 respectively. The positive keeper hurdles
increased the backlog-area contrast most visibly: the high coordinate yielded
0.2036 for R-A/R-B and 0.1641 for R-C, while their liquidation and maximum-
unresolved-tab directions remained retained. These are sensitivity results,
not evidence for adopting a hurdle.

Changing only the sustained-recovery definition from 12 to 24 to 48 hours
increased the mean restricted recovery time across the registered paths from
60.609 to 62.484 to 66.234 hours. Recovery probability remained one and no
path was right-censored under any definition. The 24-hour definition remains
the registered primary metric.

The overall result is `core_conclusions_robust`. Detailed checkpoints remain
ignored under
`outputs/experiments/final/selected_robustness/<robustness_identity>/`;
exactly eight compact artefacts are retained in provenance.

No robustness result changes Experiments A–E, H1–H4, a runtime profile or a
production default.
