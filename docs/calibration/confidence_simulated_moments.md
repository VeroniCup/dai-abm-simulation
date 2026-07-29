# Constrained simulated moments for confidence and peg recovery

## 1. Purpose and methodological boundary

This document specifies a constrained simulated-moments calibration for a
future persistent behavioural-confidence mechanism. The first bounded
infrastructure pass now connects the validated historical DAI and ETH evidence
to a reproducible Stage 1 estimate and a future Stage 2 design without fitting
Stage 2 parameters, adopting values or changing executable behaviour.

The design has three stages:

1. determine ordinary asymmetric DAI-market dynamics directly;
2. estimate a four-parameter behavioural state by simulated moments; and
3. test additional mechanisms only as declared sensitivities.

The current instantaneous confidence mechanism remains authoritative. Pure
persistent-confidence and coefficient-normalised market-response interfaces
exist for testing, but neither has a production caller. No profile is altered,
no Stage 2 parameter is selected and the predictive regression remains closed.

### 1.1 Implemented boundary

The bounded infrastructure now provides:

- a pure persistent-confidence transition with an explicit recovery gate;
- an unused pure coefficient-normalised DAI response;
- joint non-negative estimation of \(\kappa_-\) and \(\kappa_+\);
- a centred, run-bounded 24-hour empirical residual-block source;
- the deterministic 75-event catalogue;
- compact evidence for the eight fixed moments;
- cryptographically derived random-stream ownership; and
- structural transformations, the pure four-group objective, the
  pre-registered 32-event subset and 256 Sobol candidates.

This is infrastructure, not behavioural adoption. The workflow does not call
the simulator, evaluate an SMM objective over candidates, rank candidates or
fit \(\alpha_d,\alpha_r,C_{\min},\kappa_P\).

## 2. Why the predictive route is closed

The binary persistence design has no positive outcome. The continuous
predictive redesign supplies adequate origins only after extending the DAI/ETH
panel to 31 December 2019, but the largest December 2020–January 2021 episode
still contributes 56.55% of pooled six-hour burden against the fixed 25%
ceiling. The source extension and sparse predictor transformations are valid;
the failure is concentration in the observed outcome, not a source defect.

No threshold, horizon, origin grid, start date or dominance gate may now be
changed to obtain a predictive fit. The predictive stress-proxy regression is
permanently closed. Simulated moments instead give each complete event equal
weight and compare event-level severity and recovery summaries.

## 3. Fixed prior specifications

The following choices are not re-estimated:

- material downside begins below \(0.995\);
- sustained price recovery is 24 consecutive hours in
  \(0.995\leq p_t\leq1.005\);
- the confidence-recovery gate additionally requires ordinary-or-lower
  liquidation pressure and no severe bad-debt condition;
- collateral stress is
  \[
  R_t^-=\max\left(0,-\sum_{j=1}^{24}r^{ETH}_{t-j}\right);
  \]
- the six-hour burden is
  \[
  B_t^{(6)}
  =
  \frac{1}{6}\sum_{j=0}^{5}
  \min\left(1,\frac{\max(0,0.995-p_{t+j})}{0.005}\right);
  \]
- a sparse non-negative predictor is scaled by
  \[
  s(x_t)=\min\left(1,\frac{x_t}{Q^+_{0.95}(x)}\right);
  \]
- tab-based backlog-to-clearance pressure is a sensitivity and possible
  recovery gate, not a primary coefficient; and
- the confidence ceiling is one and the recovery duration is 24 hours.

The calibration evidence is the complete half-open interval
`2019-12-31 00:00 UTC` to `2024-07-01 00:00 UTC`, excluding quiet validation
from 1–21 November 2022 and final stress validation from 6–20 March 2023.
Terra/CeFi remains development evidence.

## 4. Staged calibration architecture

### 4.1 Stage 1: directly identified market dynamics

Before behavioural optimisation, estimate from ordinary and mild-deviation
hours:

- effective below-peg response \(\kappa_-\);
- effective above-peg response \(\kappa_+\); and
- the complete residual innovation distribution, including serial dependence
  relevant to event simulation.

Confidence is treated as approximately one in these observations. Stage 1
must use calendar-block uncertainty and must not separately estimate the
legacy products of adjustment speed, arbitrage strength or panic multipliers.
The three Stage 1 quantities are fixed when Stage 2 begins. The bounded
implementation estimates
\(\widehat\kappa_-=0.1993809753\) and
\(\widehat\kappa_+=0.1051311602\) from the 1,189 fixed daily observations.
Both calendar-month bootstrap sign and boundary gates pass. These are accepted
for future SMM, not runtime adopted.

### 4.2 Stage 2: constrained behavioural SMM

The only primary behavioural vector is

\[
\theta=(\alpha_d,\alpha_r,C_{\min},\kappa_P),
\]

where \(\alpha_d\) is deterioration adjustment, \(\alpha_r\) is recovery
adjustment, \(C_{\min}\) is the confidence floor and \(\kappa_P\) is the
consolidated panic response.

The future bounded state remains:

\[
C_t^\ast=1-\widehat S_t,
\]

\[
C_t =
\begin{cases}
\max[C_{\min},C_{t-1}+\alpha_d(C_t^\ast-C_{t-1})],
& C_t^\ast<C_{t-1},\\
C_{t-1},
& C_t^\ast\geq C_{t-1}\text{ and the recovery gate is closed},\\
\min[1,C_{t-1}+\alpha_r(1-C_{t-1})],
& \text{the recovery gate is open}.
\end{cases}
\]

No separate persistence coefficient, confidence ceiling or estimated
stability duration is added.

### 4.3 Stage 3: optional sensitivities

Liquidation pressure, bad-debt response, policy feedback, long-run scarring,
arbitrage capacity, participant heterogeneity and the current optional
recovery equation are excluded from the primary vector. They may be tested
only after Stage 2 is identified and validated.

## 5. Stress-state normalisation

The future observable input is

\[
\widehat S_t=
\operatorname{clip}_{[0,1]}
\left[
0.5s(g^-_{t-1})+0.5s(R^-_t)
\right],
\qquad
g^-_{t-1}=\max(1-p_{t-1},0).
\]

**Normalisation B, equal weights, is the primary specification.**

Normalisation A would introduce a fifth parameter whose share competes with
\(\alpha_d\) and \(\kappa_P\). Normalisation C would freeze weights from
conditional gradients, but the empirical relation is not sufficiently stable:
equal-weight onset-stress quartiles have mean first-six-hour burdens of
0.1284, 0.1636, 0.1105 and 0.1053, and onset stress has a correlation of
\(-0.091\) with first-six-hour burden. Those non-monotone gradients do not
support a data-derived weight ratio.

Equal weights are transparent, preserve both validated channels and add no
parameter. Pre-registered sensitivities use peg/ETH splits of 0.25/0.75 and
0.75/0.25. They may not select the primary estimate.

## 6. Behavioural price equation and ownership

The future price response is

\[
g_t^-=\max(1-p_t,0),\qquad g_t^+=\max(p_t-1,0),
\]

\[
\Delta p_t
=
\kappa_-C_tg_t^-
-\kappa_+g_t^+
-\kappa_P(1-C_t)g_t^-
+\varepsilon_t.
\]

Stage 1 owns \(\kappa_-\), \(\kappa_+\) and \(\varepsilon_t\). Stage 2 owns
\(\alpha_d,\alpha_r,C_{\min},\kappa_P\). There is no common adjustment-speed
parameter. Panic pressure enters once through
\(\kappa_P(1-C_t)g_t^-\).

## 7. Parameter bounds and transformations

| Parameter | Structural bound | Internal representation | Boundary evaluation |
| --- | --- | --- | --- |
| \(\alpha_d\) | \(0<\alpha_d\leq1\) | \(\alpha_d=\operatorname{logit}^{-1}(z_d)\) | Evaluate \(\alpha_d=1\) explicitly |
| \(\alpha_r\) | \(0<\alpha_r\leq\alpha_d\) | \(\alpha_r=\alpha_d\operatorname{logit}^{-1}(z_r)\) | Evaluate \(\alpha_d=\alpha_r\) explicitly |
| \(C_{\min}\) | \(0\leq C_{\min}<1\) | logit on the open interval | Evaluate \(C_{\min}=0\) explicitly |
| \(\kappa_P\) | \(0\leq\kappa_P\leq2.75454\) | bounded \(\log(\kappa_P)\) for the positive model | Evaluate \(\kappa_P=0\) explicitly |

The panic upper bound is determined before optimisation:

\[
\kappa_P^{\max}
=
\frac{\max_t\max(p_t-p_{t+1},0)}
{\max_t\max(1-p_t,0)}
=
\frac{0.08638833}{0.03136217}
=2.75454.
\]

Both quantities use calibration hours only. The ratio prevents the maximum
panic channel from producing a one-hour fall larger than the largest observed
calibration fall. It is a conservative empirical bound, not a tuned result.
The positive model uses a fixed numerical lower endpoint only to represent
\(\log(\kappa_P)\); zero is always a distinct nested model.

Empirical timing supports, but cannot by itself prove, the restriction
\(\alpha_d\geq\alpha_r\). Median time from onset to trough is one hour,
whereas median time from trough to completion of sustained recovery is 24
hours. Deterioration is no slower than recovery in 91.9% of calibration
events. The restriction is therefore not contradicted by the observed event
timing.

## 8. Event and ordinary-window construction

### 8.1 Event catalogue

An event begins at the first \(p_t<0.995\) after 24 prior hours at or above
0.995. It ends at completion of the first subsequent 24-hour run at or above
0.995. The catalogue retains the onset, completion, stable-run start,
pre-event conditioning hours, trough, first return, failed recovery runs,
burden path, ETH path and post-recovery overshoot.

The full panel contains 75 complete events:

- 74 calibration events;
- no quiet-validation event;
- one final USDC/SVB stress event; and
- no event crossing a partition boundary.

The 74 calibration events comprise 26 events beginning in 2020 and 48 in
2021. None begins after December 2021. This is genuine temporal concentration
and must be visible in uncertainty and validation; it is not repaired by
selecting later non-events.

Every event receives equal weight within an event moment. The long
December 2020–January 2021 event remains one event. Its exclusion is reported
only as an influence sensitivity.

### 8.2 Ordinary observations

Ordinary observations must:

- lie in \(0.995\leq p_t\leq1.005\);
- be outside an active material-downside event;
- have a complete lagged 24-hour ETH window;
- remain in calibration; and
- be selected without using future DAI corrections.

The primary rule is **daily at 00:00 UTC**. It gives 1,189 observations,
including 172 below-peg and 1,017 above-peg mild observations across five
calendar years. The six-hour grid gives 4,798 observations but repeats nearby
serial states four times per day. It remains a sampling sensitivity. The daily
rule is chosen for lower serial duplication, not for a more favourable slope.

## 9. Empirical candidate-moment feasibility

Temporary analysis uses the ignored canonical panel and 2,000 deterministic
event-resampling draws. `Scale` follows bootstrap standard deviation, then
IQR/1.349, then consistent MAD. `2020 / 2021` reports the annual equal-event
means. Quiet and final validation evidence is absent from every value below.

| Candidate event moment | Events | Mean | Median | IQR | Bootstrap SD | Scale | Largest event | 2020 / 2021 mean | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Minimum price | 74 | 0.991765 | 0.993450 | 0.003607 | 0.000531 | 0.000531 | 1.4% | 0.988271 / 0.993658 | pass |
| Maximum downside deviation | 74 | 0.003235 | 0.001550 | 0.003607 | 0.000544 | 0.000544 | 11.0% | 0.006729 / 0.001342 | pass |
| Maximum six-hour burden | 74 | 0.312551 | 0.202094 | 0.315477 | 0.035070 | 0.035070 | 4.3% | 0.545333 / 0.186461 | pass |
| Cumulative burden | 74 | 6.270821 | 0.519450 | 1.615992 | 3.728566 | 3.728566 | 56.5% | 16.3347 / 0.819549 | reject |
| Hours to minimum | 74 | 9.932432 | 1 | 10.75 | 2.168481 | 2.168481 | 11.0% | 16.1923 / 6.5417 | pass |
| First-six-hour burden | 74 | 0.126703 | 0.046382 | 0.114975 | 0.024571 | 0.024571 | 10.3% | 0.271365 / 0.048344 | pass |
| First-24-hour burden | 74 | 0.061691 | 0.021241 | 0.052900 | 0.011890 | 0.011890 | 8.6% | 0.138779 / 0.019935 | pass |
| Onset ETH downside | 74 | 0.012373 | 0 | 0.020234 | 0.002128 | 0.002128 | 6.9% | 0.011828 / 0.012668 | pass |
| Hours below 0.995 | 74 | 11.283784 | 3 | 3.75 | 5.404769 | 5.404769 | 48.9% | 26.0769 / 3.2708 | pass |
| Hours to first return | 74 | 1.918919 | 1 | 1 | 0.230480 | 0.230480 | 8.5% | 2.7308 / 1.4792 | pass |
| Hours to recovery completion | 74 | 48.959459 | 28.5 | 21.75 | 9.539428 | 9.539428 | 19.4% | 75.2692 / 34.7083 | pass |
| Recovery half-life | 74 | 1.986486 | 2 | 1 | 0.159901 | 0.159901 | 4.8% | 2.1154 / 1.9167 | pass |
| Burden after first return | 74 | 5.468958 | 0.011692 | 0.758183 | 3.550458 | 3.550458 | 62.6% | 14.5298 / 0.560999 | reject |
| Failed recovery attempts | 74 | 3.121622 | 0.5 | 2 | 1.298469 | 1.298469 | 39.8% | 6.8077 / 1.1250 | pass |
| Post-recovery overshoot | 74 | 0.009914 | 0.007528 | 0.004831 | 0.000749 | 0.000749 | 3.7% | 0.014870 / 0.007230 | pass |
| Not recovered within 168 hours | 74 | 0.027027 | 0 | 0 | 0.018944 | 0.018944 | 50.0% | 0.076923 / 0 | pass, secondary only |
| Initial peg gap | 74 | 0.006262 | 0.005745 | 0.001254 | 0.000162 | 0.000162 | 2.4% | 0.007013 / 0.005855 | pass |
| Event ETH downside | 74 | 0.015201 | 0 | 0.015393 | 0.003589 | 0.003589 | 11.5% | 0.008385 / 0.018894 | pass |
| Recovery hours from trough | 74 | 39.027027 | 24 | 4 | 8.553193 | 8.553193 | 22.1% | 59.0769 / 28.1667 | pass |

The two rejected pooled burden moments preserve the previous concentration
finding under the event construction. They are diagnostic only.

For ordinary daily observations, mean next-hour change is \(0.00035326\) below
the peg and \(-0.00009513\) above it. Calendar-month block-bootstrap scales are
\(0.00013559\) and \(0.00002883\); the largest calendar-month absolute
contributions are 15.4% and 6.8%.

Two conditional contrasts also pass:

- the top-minus-bottom initial-gap quartile contrast in maximum six-hour
  burden is 0.599066, with 19 events per stratum, bootstrap scale 0.071927 and
  maximum within-stratum event contribution 42.0%; and
- the top-minus-bottom 24-hour ETH-recovery quartile contrast in recovery
  hours from the trough is \(-12.3158\) hours, with 19 events per stratum,
  bootstrap scale 7.5325 hours and maximum contribution 21.8%.

Every selected core moment has at least 19 eligible events, a non-zero scale,
no event contribution above 50%, a deterministic definition and no validation
input.

## 10. Core, secondary and diagnostic moments

The primary objective contains exactly eight core moments:

| Group | Core moment | Data value | Scale | Principal role |
| --- | --- | ---: | ---: | --- |
| A | Ordinary mean next-hour change below peg | 0.00035326 USD | 0.00013559 | Preserve fixed \(\kappa_-\) dynamics |
| A | Ordinary mean next-hour change above peg | -0.00009513 USD | 0.00002883 | Preserve fixed \(\kappa_+\) dynamics |
| B | Equal-event mean first-six-hour burden | 0.126703 | 0.024571 | \(\alpha_d\) |
| B | Equal-event mean maximum downside deviation | 0.003235 USD | 0.000544 | \(C_{\min}\) |
| C | Equal-event mean hours to sustained-recovery completion | 48.9595 hours | 9.5394 | \(\alpha_r\) |
| C | Equal-event mean failed recovery attempts | 3.1216 | 1.2985 | Recovery persistence |
| D | Initial-gap Q4–Q1 contrast in maximum six-hour burden | 0.599066 | 0.071927 | \(\kappa_P\) |
| D | ETH-recovery Q4–Q1 contrast in recovery hours from trough | -12.3158 hours | 7.5325 | Conditional recovery |

Secondary validation moments are minimum price, maximum six-hour burden, hours
to minimum, first-24-hour burden, hours below 0.995, first return, recovery
half-life, overshoot and non-recovery within 168 hours. Onset stress, event ETH
downside, annual instability and ordinary six-hour-grid results are
diagnostics. Cumulative burden and burden after first return are excluded from
the objective because one event contributes more than 50%.

## 11. Parameter-to-moment identification matrix

| Core moment | \(\alpha_d\) | \(\alpha_r\) | \(C_{\min}\) | \(\kappa_P\) |
| --- | --- | --- | --- | --- |
| Ordinary below-peg change | weak | none | none | none |
| Ordinary above-peg change | none | none | none | none |
| First-six-hour burden | **primary** | none | secondary | secondary |
| Maximum downside deviation | secondary | weak | **primary** | secondary |
| Recovery-completion hours | weak | **primary** | secondary | secondary |
| Failed recovery attempts | weak | secondary | secondary | weak |
| Initial-gap burden contrast | secondary | none | secondary | **primary** |
| ETH-recovery duration contrast | weak | secondary | weak | weak |

Group A is a preservation group for quantities fixed in Stage 1 rather than a
source of independent Stage 2 identification. Every Stage 2 parameter has one
plausible primary moment and no parameter has more than three primary moments.
The future Jacobian must still confirm joint rank; this qualitative matrix does
not assert identification.

## 12. Moment normalisation and weighting

For moment \(j\), the scale \(s_j\) is selected in this order:

1. event-block bootstrap standard deviation;
2. IQR divided by 1.349; and
3. consistent MAD.

Ordinary moments use calendar-month blocks. An all-zero hierarchy rejects the
moment. The discrepancy is

\[
d_j(\theta)=
\frac{m_j^{sim}(\theta)-m_j^{data}}{s_j}.
\]

The primary objective is

\[
J(\theta)
=
\sum_{g=1}^4
0.25\frac{1}{|M_g|}
\sum_{j\in M_g}\widetilde w_jd_j(\theta)^2.
\]

Each group has two core moments, so initial effective weight is 12.5% per
moment and 25% per group. Inverse-variance adjustment is optional only after
calibration resampling, is capped at ten times the group median, and is
renormalised to mean one. A resulting moment above 20% total weight is
forbidden. A full inverse covariance matrix is not primary; shrinkage
covariance is a later sensitivity.

Future evidence records the empirical scale, raw, capped and final
within-group weight, group weight and effective total weight for every moment.

## 13. Historical replay limitation

The present evidence does not support exact historical replay for the 2020–21
calibration events. Required event inputs are classified as follows:

| Required state | Status |
| --- | --- |
| ETH price/return path | directly observed |
| Initial DAI price and pre-event peg path | directly observed |
| DAI event outcomes | directly observed |
| Exact historical vault state | unavailable for most calibration events |
| Initial vault distribution | sampled from reviewed representative evidence |
| Collateral composition | sampled or fixed to a documented model portfolio |
| Liquidation activity | observed only from June 2021; otherwise unavailable |
| Protocol settings | observed from June 2021; otherwise fixed to documented regime values |
| Gas conditions | observed from June 2021; otherwise sampled/fixed |
| Simulation horizon | observed event horizon plus fixed pre-roll and post-roll |

The primary design is therefore a **conditional event experiment**. It replays
the observed ETH path, starts from the observed DAI price, uses a standardised
pre-event vault and protocol state conditioned only on observable regime
information, and compares normalised burden and recovery moments. It does not
claim to reproduce a historical Maker state or an exact DAI path.

A 48-hour pre-roll initialises lags and permits the standardised system state
to settle. The event horizon runs through observed recovery completion plus a
fixed 24-hour post-roll, capped only by a pre-registered common maximum long
enough to include every core recovery outcome.

## 14. Event blocks and computational subset

All 74 calibration events remain in the final objective and uncertainty
analysis. The catalogue records episode identifier, dates, year, initial gap,
ETH downside, burden, recovery, evidence availability and moment eligibility.

For the initial global search only, computational load may be reduced to 32
events. Selection is deterministic and fixed before simulation by joint
strata of event-burden quartile, ETH-downside quartile, recovery-duration
quartile and year, with a content-hash tie-break. No event is selected using
fit quality. All candidates promoted from the search subset are evaluated on
all 74 events.

## 15. Simulation replications and seed policy

The primary objective uses:

- 32 fixed replications per event and parameter vector;
- a content-addressed seed registry;
- identical seeds across candidate vectors;
- independent event-specific streams; and
- separate streams for vault sampling, market innovations and any liquidation
  randomness.

At 32 replications, every core simulated moment must have Monte Carlo standard
error no greater than \(0.10s_j\). Finalists use 64 replications under two
independent common-random-number registries. At 64, the threshold is
\(0.075s_j\), the top-five ranking must have Spearman correlation at least
0.90 between registries, and the selected candidate must remain in the top two
under each registry. Replication count never depends on apparent candidate
difficulty.

## 16. Optimisation design

The bounded search is pre-registered:

1. evaluate 256 Sobol points (\(2^8\)) in the four-dimensional transformed
   space on the deterministic 32-event search subset with 32 replications;
2. re-evaluate the best 16 on all 74 calibration events;
3. refine the best four with bounded Powell search, at most 100 objective
   evaluations per start, using the fixed common-random-number registry;
4. re-evaluate the best five with 64 replications and two independent
   registries; and
5. evaluate explicit \(\kappa_P=0\), \(C_{\min}=0\) and
   \(\alpha_d=\alpha_r\) nested models.

The 256-point count is a power-of-two low-discrepancy design that gives 64
initial points per dimension while keeping the search near 0.8 million
event-replication runs under the planned subset and refinement caps. It is
fixed from dimension and workload, not preliminary fit. Gradients are not
used.

## 17. Identification diagnostics

The future implementation must report:

- one-dimensional objective profiles;
- all six pairwise objective surfaces;
- the scaled finite-difference moment Jacobian;
- singular values and condition number;
- correlations among near-optimal candidates;
- bound occupancy;
- moment sensitivity rankings;
- nested-model objective changes; and
- leave-one-event-out parameter ranges.

The retained four-parameter model requires numerical Jacobian rank four, a
smallest-to-largest singular-value ratio of at least \(10^{-3}\), and condition
number no greater than \(10^3\). A parameter is weakly identified if its
profile is flat within one objective unit, its near-optimal values span more
than 75% of its admissible range, it repeatedly reaches a bound, or
leave-one-event-out instability breaches Section 20. Weak parameters are
reported as ranges or scenario bands.

## 18. Empirical uncertainty

The future run uses 2,000 bootstrap replications:

- complete-event resampling for event and conditional moments; and
- calendar-month block resampling for ordinary moments.

Episodes remain intact. Hourly independent bootstrap is prohibited. Bootstrap
draws estimate scales and uncertainty only; they cannot change the selected
moments, bounds or normalisation.

## 19. Leave-one-event-out procedure

For each of the 74 calibration events:

1. omit the complete event;
2. repeat the bounded calibration on the remaining events, using warm starts
   only from the pre-registered global design;
3. simulate the omitted conditional event; and
4. report errors for minimum price, cumulative burden, hours below 0.995,
   first return and sustained recovery.

Report parameter dispersion, objective change, event prediction error,
influence and failure frequency. The December 2020–January 2021 episode is one
ordinary iteration. Its separate exclusion sensitivity cannot select the
primary estimate.

## 20. Blocked and final validation

Chronological checks are:

- early development: event starts before 1 February 2021 (28 events);
- later calibration check: event starts from 1 February 2021 onward
  (46 events);
- quiet generalisation: 1–21 November 2022; and
- untouched final stress: 6–20 March 2023.

The early/later split tests temporal instability in both directions. It is not
called final validation. Quiet validation tests false activation. USDC/SVB is
used once after the full specification, weights, bounds, optimiser and
candidate have been frozen. No parameter is changed afterwards.

Quiet metrics are average peg deviation, residual volatility, false stress
activation, false-depeg duration, unnecessary confidence deterioration and
price-bound activation.

Final stress metrics are minimum price, cumulative and maximum six-hour
burden, time to minimum, first return, sustained recovery, recovery success,
overshoot, simulated confidence minimum and recovery time, liquidation-gate
sensitivity and predictive-interval coverage.

## 21. Numerical acceptance criteria

### 21.1 Structural validity

Confidence must remain bounded; updates must use no future information; gate
resets must be exact; panic is counted once; legacy behaviour must remain
reproducible; and numerical price bounds may bind in no more than 1% of steps
in any accepted primary event experiment.

### 21.2 Moment fit and concentration

- every absolute core discrepancy must be at most \(2s_j\);
- each group root-mean-square standardised discrepancy must be at most one;
- \(J(\theta)\leq1\);
- no moment may have more than 20% ex-ante weight;
- no realised moment may contribute more than 35% of \(J\); and
- no realised group may contribute more than 45% of \(J\).

An accepted result must report failure rather than delete a conflicting
moment.

### 21.3 Identification and Monte Carlo validity

- scaled Jacobian rank four, condition number at most \(10^3\), and singular
  ratio at least \(10^{-3}\);
- 32- and 64-replication MCSE and ranking thresholds in Section 15;
- median leave-one-event-out parameter shift no more than 0.25 of its
  structural range and 90th-percentile shift no more than 0.50;
- fewer than 20% of leave-one-out estimates at any one bound; and
- every nested model evaluated and reported.

### 21.4 Validation validity

At least seven of the eight observable final-stress market/recovery metrics
must lie inside pre-registered 90% simulation intervals. Latent confidence
metrics are diagnostics and do not count towards coverage. In quiet
validation, false stress may occupy at most 5% of hours, no false depeg may
persist for 24 hours, and numerical bounds must never bind. These thresholds
are fixed before fitting and use empirical scales or the fixed recovery rule.

## 22. Rejection and simplification

If the four-parameter vector fails identification:

1. test \(\kappa_P=0\);
2. fix \(C_{\min}\) from an independently documented severe-stress
   lower-response bound;
3. impose \(\alpha_d=\alpha_r\) only as a restricted model;
4. reduce redundant moments; and
5. report ranges rather than add parameters.

Do not add heterogeneity, policy feedback or bad debt; reopen the predictive
route; change thresholds; tune named events; or add parameters in response to
weak identification.

## 23. Bad-debt classification

Bad debt is classified as **recovery-gate mechanism only**.

It is excluded from the primary SMM objective and stress state, and no
bad-debt coefficient is estimated. The empirical evidence is too sparse and
its accounting proxy is not sufficiently complete for a continuous response.
A separately supported severe condition may block recovery, as required by
the fixed gate. Until that severe condition is operationally defined, the gate
is an implementation blocker rather than an invitation to infer a threshold.

## 24. Policy and legacy-recovery classification

- `policy_feedback_strength` is a literature-informed experiment sensitivity,
  not a calibrated primary mechanism.
- `bad_debt_recovery_drag` remains only in the legacy recovery ablation.
- `arbitrage_recovery_strength` is not separately estimated because
  \(\kappa_-\) owns effective below-peg correction.
- `min_recovery_confidence` is replaced in the future mode by the fixed
  stability and system-pressure gate.
- the current optional recovery equation is retained only as a legacy
  ablation and is excluded from the new primary behavioural mode.

## 25. Evidence, outputs, code and tests

Compact, content-addressed evidence is now tracked under
`data/provenance/calibration/confidence/`:

- `stage1_market_estimates.json`;
- `stage1_residual_summary.json`;
- `simulated_moments_specification.json`;
- `empirical_moments.csv`;
- `moment_weights.csv`;
- `parameter_bounds.json`;
- `event_catalogue.csv`;
- `seed_registry.json`.

`identification_summary.json` and `simulated_moments_selection.json` are
deliberately absent because they require a completed SMM fit.

They must be registered in the calibration manifest and contain no hourly
trajectories. Diagnostics belong in
`outputs/diagnostics/calibration/confidence/`, tables in
`outputs/tables/calibration/confidence/`, and event trajectories in
`outputs/experiments/confidence/`.

The bounded implementation uses the existing semantic owners:

- `model/confidence.py`: bounded persistent state and recovery gate;
- `model/market.py`: effective response equation;
- `model/simulation.py`: unchanged legacy state timing;
- `model/metrics.py`: unchanged legacy outcomes;
- `calibration/market.py`: ordinary-market quantities and event construction;
- `calibration/validation.py`: blocked, influence and identification checks;
- `experiments/scenarios.py` and `summaries.py`: unchanged;
- `calibration/simulated_moments.py`: pure events, transformations, objective,
  seeds, subset and Sobol design; and
- `workflows/calibration/market_gas_protocol.py`: calibration entry point.

A substantive `src/dai_sim/calibration/simulated_moments.py` is appropriate
only if event simulation, objective evaluation, seed ownership and optimisation
would otherwise obscure `market.py`. Generic `smm.py`, `optimisation.py`,
`utils.py` and wrapper-only workflows are prohibited.

Current tests cover event construction, ordinary sampling, scales and weights,
state bounds and timing, seed determinism, objective reproducibility, boundary
models, blocked partitions, legacy regression checks and evidence-manifest
integrity. Jacobian and leave-one-event-out fit tests remain Stage 2 work.

## 26. Remaining blockers

Stage 2 fitting and runtime integration still require separate authorisation.
Before fitting or adoption:

- the severe bad-debt recovery-gate condition must be defined or the gate must
  remain explicitly unavailable;
- conditional event initial-state sampling must be specified without claiming
  exact replay;
- the exact legacy/new configuration interface must be approved;
- computational workload must be benchmarked; and
- the current simulator must gain persistent confidence only through a
  regression-protected implementation.

The moment set is feasible for an infrastructure pass, not evidence that the
four parameters are identified. No behavioural coefficient has been fitted or
adopted.
