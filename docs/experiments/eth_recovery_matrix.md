# ETH-only peg-recovery matrix

## 1. Research purpose

This pre-registered experiment tests the recovery-regime hypothesis: DAI peg
recovery depends jointly on post-shock collateral recovery, liquidation
resolution and behavioural stabilisation. It is the first substantive use of
the transparent persistent-confidence scenarios after closure of their
calibration programme. The scenarios remain assumptions, not estimates.

## 2. Production baseline and fixed boundaries

The controlled experiment uses the established ETH-only `legacy` profile. It
therefore fixes 100 production-default Gaussian vaults, expected total initial
debt of 500,000 DAI, a 150% liquidation ratio, 13% liquidation penalty,
100 DAI transaction gas cost, zero risk-cost rate, full close factor,
unbounded ordinary keeper capacity and zero oracle delay. The DAI price begins
at one dollar. The profile is identified by SHA-256
`6de53071749fc504865ef760488003ab4733b58e8a6ce692144ca8e74ab9284a`.

The experiment changes neither the legacy runtime nor Experiments 1–5. Its DAI
equation uses the accepted Stage 1 below-peg and above-peg effective
coefficients and the accepted 24-hour moving-block residual process. Active
confidence scenarios additionally use the full 24-hour recovery gate, with
price stability, unresolved-backlog and active-bad-debt conditions retained.
Gas, keeper capacity and oracle delay are fixed rather than crossed.

## 3. Canonical shock and horizon

The frozen severe ETH shock is instantaneous at hour 48:

\[
P^{ETH}: 2000\longrightarrow1140,
\]

a 43% arithmetic loss. The first 48 hours are pre-shock and the 720 hours from
the shock hour through hour 767 form the post-shock evaluation period. The
total hourly horizon is therefore 768 observations, including the 24-hour
sustained-recovery confirmation inside the evaluation horizon.

## 4. Recovery paths

For hours \(\tau\) since the common trough, the deterministic treatment uses

\[
h(x)=3x^2-2x^3,\qquad
\log P_\tau=\log P_L+f\,h(\min(\tau/T,1))
(\log P_0-\log P_L).
\]

The four paths are ordered by treatment, not by an empirical forecasting
claim:

| Path | \(f\) | \(T\) | Interpretation |
| --- | ---: | ---: | --- |
| `persistent_trough` | 0 | 0 | ETH stays at 1,140 within the horizon |
| `partial_week` | 0.50 | 168 h | half the log loss recovered in seven days |
| `full_week` | 1 | 168 h | full recovery in seven days |
| `rapid_full` | 1 | 48 h | full recovery in two days |

Every path has the same pre-shock values, onset and trough; recovery is
monotone, finite and non-overshooting, and no post-trough ETH noise is added.

## 5. Confidence scenarios and matrix

The confidence dimension uses the committed registry in this exact order:

1. `stage1_only`;
2. `confidence_resilient`;
3. `confidence_central`;
4. `confidence_fragile`.

`stage1_only` is the reference and production default. The other bundles are
opt-in categorical scenarios with their unchanged registered parameters. In
particular, central has a larger raw recovery adjustment than resilient and
fragile, so labels do not impose a DAI-outcome ranking.

The path-first Cartesian product contains exactly 16 cells. There is no
no-shock substantive cell and no gas, keeper, oracle, structural-factorial or
multi-collateral cross.

## 6. Replications and common random numbers

Each cell has 128 pre-registered replications, for 2,048 runs. Registry
`eth_recovery_matrix_v1` derives separate vault, residual-block and liquidation
stream seeds from the replication identity. All 16 cells in a replication
share these seeds and the realised initial vault state. Only the deterministic
ETH path and registered confidence activation differ.

Detailed checkpoints are atomically written below the ignored
`outputs/experiments/eth_recovery/<experiment-identity>/` hierarchy. A valid
checkpoint is reused on resume; invalid or absent checkpoints are rerun.

## 7. Sustained recovery and censoring

DAI is inside the peg band when
\(0.995\leq P_t^{DAI}\leq1.005\). Sustained recovery requires 24 consecutive
inside-band hourly observations, and leaving the band resets the counter. If
the post-shock path never exits the band, recovery time is zero. Otherwise the
clock begins with the first post-shock exit and records first return, failed
attempts and completion of the 24-hour run.

Recovery probabilities are reported by 48, 168, 336 and 720 hours. Restricted
mean recovery time is capped at 720 hours, with every unrecovered replication
contributing the cap. Conditional recovery times among recovered runs cannot
replace these estimands.

## 8. Outcomes

The six primary outcomes are reported separately:

1. cumulative below-peg burden in DAI-price-hours;
2. restricted mean sustained-recovery time;
3. recovery probability by 168 hours;
4. recovery probability by 720 hours;
5. maximum unresolved liquidation tab; and
6. cumulative realised bad debt.

Secondary outcomes cover DAI extrema and duration, liquidation inventory,
repayment, attempts, capacity rejection, keeper profit, active bad debt and
the registered confidence-mechanism diagnostics. `stage1_only` records
inactive confidence and zero panic amplification.

## 9. Paired contrasts and interactions

Five path contrasts are computed within every confidence scenario:
`partial_week - persistent_trough`, `full_week - persistent_trough`,
`rapid_full - persistent_trough`, `full_week - partial_week`, and
`rapid_full - full_week`.

Within each path, the three active scenarios are compared only with
`stage1_only`. For every active scenario and non-persistent path, the
difference-in-differences subtracts the corresponding scenario effect under
`persistent_trough`. Continuous contrasts report paired means, standard
errors, 95% intervals, medians and interquartile ranges. Binary contrasts also
report discordant pairs. No scalar score, p-value selection or “best
scenario” contrast is used.

## 10. Pre-registered interpretation

H4a requires `full_week` to reduce both below-peg burden and restricted
recovery time relative to `persistent_trough`, with expected-direction paired
intervals excluding zero in at least three of four confidence scenarios and
no clear opposite result. H4b asks whether `rapid_full` improves either
primary peg measure over `full_week` in at least three scenarios without a
clear opposite effect. H4c is present when at least one registered interaction
interval excludes zero for burden, restricted recovery time or 720-hour
recovery probability.

The overall classification is one of:

- `collateral_recovery_robustly_improves_peg`;
- `collateral_recovery_effect_confidence_dependent`;
- `recovery_path_improves_price_but_not_solvency`;
- `no_clear_recovery_path_effect`; or
- `eth_recovery_experiment_invalid`.

Numerical failure above 1% in any cell, incomplete runs, seed failure, path
failure or scenario mismatch makes the experiment invalid.

## 11. Results and mechanism interpretation

The machine-readable cell summaries, paired contrasts, interactions and
decision are owned by `data/provenance/experiments/recovery/`. They retain
censoring and report backlog and bad-debt outcomes independently of peg
outcomes. The completed result and its interpretation are therefore read from
those registered artefacts rather than selected visually or copied into
runtime configuration.

All 2,048 runs completed with no numerical failure. The fixed experiment is
classified as **`no_clear_recovery_path_effect`**: H4a and H4b are not
supported and H4c is not present. Within every confidence scenario, all five
path contrasts are exactly zero for the primary outcomes. Under the ordinary
unbounded-capacity baseline, 99.625 vaults are liquidatable and successfully
liquidated on average at the common shock; mean debt repayment is
496,354.14 DAI. The unresolved tab is consequently zero after keeper action,
active bad debt is zero, and realised bad debt is numerical dust of about
\(8.25\times10^{-13}\) DAI. Later ETH recovery cannot change already completed
liquidations.

The confidence bundles nevertheless have large conditional peg effects, which
must not be interpreted as a ranking or estimate. Across all four recovery
paths, mean below-peg burden is 0.258 DAI-price-hours for `stage1_only`,
132.155 for resilient, 349.137 for central and 356.971 for fragile. Restricted
mean recovery times are 70.20, 463.93, 714.59 and 714.59 hours respectively;
720-hour recovery probabilities are 0.9922, 0.3750, 0.0078 and 0.0078.
These scenario differences are descriptive consequences of fixed assumptions.

Mechanistically, the severe common shock saturates collateral stress before
the smooth recovery paths separate, while the DAI peg gap then sustains
confidence loss. Mean post-shock recovery-gate closure is 354 hours for
resilient, 704 for central and 716 for fragile. Backlog and bad debt do not
limit recovery in this baseline; confidence-state persistence does. This
finding is conditional on immediate ordinary-capacity liquidation and does
not replace the separate keeper-capacity, gas or oracle experiments.

## 12. Limitations and next boundary

The ETH paths are transparent counterfactual treatments rather than forecasts.
The experiment is conditional on one severe shock, the simplified auction
mechanism and ordinary baseline gas, keeper and oracle conditions. It does not
identify a true confidence bundle, governance response or historical replay.

Irrespective of the result, later multi-collateral work uses `full_week` as
the design reference because it transparently returns ETH to its pre-shock
level over seven days; `persistent_trough` is the adverse sensitivity.
`rapid_full` and `partial_week` remain optional robustness paths. This rule
does not select the cell with the best DAI outcome. All four confidence
scenarios remain a robustness dimension unless a separate reduction is
pre-registered.

No final-validation data, USDC/SVB event, registry B, confidence calibration
search or multi-collateral simulation enters this experiment. None of its
scenario values is runtime adopted.

The subsequent
[constrained-liquidation experiment](constrained_eth_recovery.md) has now
tested the missing waiting channel with empirical arrivals and shared
capacities 14, 26 and 45. Its capacity-dependent rescue result does not revise
this experiment's conditional unbounded-capacity null.

## 13. Reproducibility

The YAML owner is
[`eth_recovery_matrix.yaml`](../../config/sensitivities/eth_recovery_matrix.yaml),
the implementation is
[`eth_recovery.py`](../../src/dai_sim/experiments/mechanism/eth_recovery.py), and the
workflow is
[`workflows/experiments/mechanism/eth_recovery.py`](../../workflows/experiments/mechanism/eth_recovery.py).
The scientific identity hashes the code owners, baseline, shock, paths,
confidence registry, seed registry, matrix, estimands, contrasts and decision
rules while excluding results, output paths, host metadata and rankings.
