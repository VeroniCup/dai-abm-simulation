# Confidence evidence redesign

## 1. Purpose and boundary

This document records the pre-registered evidence redesign that followed the
non-estimable binary persistence design in
[confidence estimation](confidence_estimation.md). It changes the empirical
target and sampling unit before estimation. It does not weaken the material
depeg definition, relabel observations, import withheld observations into the
failed design or fit a behavioural coefficient.

The feasibility analysis used the existing ignored hourly market and
Liquidations 2.0 panels. It did not alter those inputs or create repository
evidence. Behavioural implementation remains unauthorised.

## 2. Reason for redesign

The fixed binary design produced:

| Quantity | Result |
| --- | ---: |
| Calibration hours | 25,104 |
| Calibration episodes with origins | 24 |
| Calibration origins | 27 |
| Positive six-hour persistence outcomes | 0 |
| Negative six-hour persistence outcomes | 27 |
| Validation origins | 0 |
| Calibration tab-pressure MAD at eligible origins | 0 |

The three-hour, 12-hour and lower-threshold sensitivities were also
inadequate. No coefficient was fitted. The difficulty was created by
episode-conditioned origin selection and a rare binary continuation outcome,
not by a defect in the market or liquidation evidence.

The redesign therefore:

- retains \(p<0.995\) as the material downside definition;
- retains the six-hour prediction horizon;
- replaces the binary primary target with a bounded continuous burden;
- replaces episode-conditioned origins with a deterministic UTC grid;
- retains validation and stress partitions as withheld evidence; and
- tests feasibility without fitting or comparing models.

The earlier binary result remains an audit record. Negative observations are
not relabelled, and stress observations are not retroactively inserted into
that failed design.

## 3. Primary continuous target

At an origin \(t\), define the six-hour future downside burden:

\[
B_t^{(6)}
=
\frac{1}{6}
\sum_{j=0}^{5}
\min\left[
1,
\frac{\max(0,0.995-p_{t+j})}{0.005}
\right].
\]

The target lies in \([0,1]\). It is zero when all six future prices are at or
above 0.995. An hour at 0.99 or below contributes one, while intermediate
downside observations contribute proportionally. The average therefore
combines duration and depth without requiring the origin itself to be below
the threshold.

The future observable stress target is:

\[
\widehat S_t = E[B_t^{(6)}\mid X_t].
\]

This conditional mean is a bounded predictor of future downside burden. It is
not directly observed confidence.

## 4. Diagnostic outcomes

Two additional outcomes are retained for diagnosis, not target selection.

Any downside onset is:

\[
O_t^{(6)}=\mathbf 1(B_t^{(6)}>0).
\]

The existing severe persistence label \(Y_t^{(6)}\) remains descriptive. It
equals one when at least four of \(p_t,\ldots,p_{t+5}\) are below 0.995 and
\(p_{t+5}<0.995\). It cannot return as the primary outcome unless a future
evidence extension independently passes its original adequacy gates.

Maximum downside severity is:

\[
M_t^{(6)}
=
\max_{j=0,\ldots,5}
\min\left[
1,
\frac{\max(0,0.995-p_{t+j})}{0.005}
\right].
\]

This reveals whether average burden hides a brief severe deviation. Validation
performance must not be used to choose among these outcomes.

## 5. Deterministic origin grid

Primary origins are fixed at 00:00, 06:00, 12:00 and 18:00 UTC for every
complete calendar day in a partition. Each origin owns the six future hours
from \(t\) through \(t+5\), so outcome windows do not overlap.

An origin is retained only when:

- the preceding 24 predictor hours and all six outcome hours lie in the same
  partition;
- all DAI prices and ETH returns required by the row are observed;
- the lagged liquidation state is observed; and
- no partition or sample boundary is crossed.

Predictors use information only through \(t-1\). Origins are fixed without
examining prices, outcomes or events. Missing or boundary-ineligible origins
are not replaced.

The five alternative grids beginning at 01:00 through 05:00 UTC are
pre-registered anchor sensitivities. They are not pooled, and the midnight
anchor remains primary because it has no data-boundary defect.

## 6. Predictors and timing

The lagged predictors remain:

\[
g^-_{t-1}=\max(1-p_{t-1},0),
\]

\[
R_t^-=
\max\left(
0,
-\sum_{j=1}^{24}r^{ETH}_{t-j}
\right),
\]

and:

\[
L_t=
\frac{U_{t-1}}
{U_{t-1}+C^{24}_{t-1}+\epsilon}.
\]

\(U_{t-1}\) is unresolved remaining tab at the end of hour \(t-1\), and
\(C^{24}_{t-1}\) is tab cleared in hours \(t-24,\ldots,t-1\). No hour-\(t\)
state enters a predictor.

The analysis also constructs, without automatically admitting them to the
model:

- above-peg gap;
- absolute peg gap;
- an indicator for positive tab pressure;
- unresolved tab in DAI;
- 24-hour cleared tab in DAI;
- count-based liquidation pressure; and
- hours since the latest material downside observation.

The market input contains 27,024 consecutive UTC hours from 1 June 2021
through 30 June 2024. It has no missing or duplicate timestamps and no missing
DAI or ETH prices. The single structurally missing first ETH return is outside
all retained lookbacks.

## 7. Transformation and tab-pressure gate

### 7.1 Market predictors

Peg gap and ETH downside retain calibration-owned first/99th-percentile
winsorisation, median centring and MAD scaling. These transformations must be
re-estimated inside each future training fold.

On both current calibration designs, the winsorised median and MAD of each
market predictor are zero:

| Design | Predictor | 1st percentile | 99th percentile | Median | MAD |
| --- | --- | ---: | ---: | ---: | ---: |
| A | Lagged peg gap | 0 | 0.002685 | 0 | 0 |
| A | ETH downside | 0 | 0.094142 | 0 | 0 |
| B | Lagged peg gap | 0 | 0.002615 | 0 | 0 |
| B | ETH downside | 0 | 0.102782 | 0 | 0 |

The declared transformation rule therefore blocks estimation on both current
samples. A substitute scale is not introduced after seeing this result.

### 7.2 Tab pressure

The tab reconstruction remains valid, but its variation on Design A's primary
grid is:

| Quantity | Result |
| --- | ---: |
| Calibration origins | 4,167 |
| Origins with \(L_t>0\) | 1 |
| Positive share | 0.024% |
| Calendar months represented | 1 |
| Independent backlog episodes represented | 1 |
| Active auctions represented at the positive origin | 20 |
| Positive \(L_t\), minimum/median/maximum | 0.146618 / 0.146618 / 0.146618 |
| Positive-value IQR | 0 |
| Burden at \(L_t>0\) | 0 |
| Share of total burden at \(L_t>0\) | 0% |

It fails all five pre-registered eligibility gates: 100 positive origins, 12
months, ten independent backlog episodes, ten per cent of burden and non-zero
positive IQR. The log-transform parameter \(\eta\) is therefore not defined.

Tab pressure is classified as **sensitivity predictor**. Its valid
reconstruction is retained, and it may additionally close a future confidence
recovery gate, but it is excluded from the primary stress estimator. The count
analogue is positive at the same single origin and also coincides with no
burden. It remains a separate sensitivity, not a silent substitute.

## 8. Evidence designs

### 8.1 Design A: strict existing split

Calibration is 1 June 2021 to 1 July 2024 excluding Terra/CeFi, November 2022
and USDC/SVB. November 2022 remains quiet/generalisation validation, while
Terra/CeFi and USDC/SVB remain stress evaluations.

### 8.2 Design B: development-stress calibration

Design B adds Terra/CeFi to calibration, retains November 2022 as quiet
validation and preserves USDC/SVB as final downside-stress validation.
USDC/SVB is not admitted to calibration.

### 8.3 Design C: longer historical market evidence

Design C extends only the DAI and ETH market evidence. Its primary design uses
peg gap and ETH downside over the longer sample. Liquidation pressure remains
unavailable before its validated Liquidations 2.0 coverage and is retained
only on the supported subperiod.

At the time of this redesign, no suitable pre-June-2021 panel existed locally.
The later [historical market evidence
pass](confidence_historical_market_evidence.md) acquired the fixed extension,
applied the gates without fitting and found that Design C fails the 25%
episode-dominance ceiling.

## 9. Partition-selection rule

The first passing design in the order A, B, C is eligible. A later design is
not chosen for apparently better performance:

1. Design A has priority.
2. Design B is considered only because A fails.
3. Design C is considered only because A and B fail or because an existing
   validated extension materially improves episode independence.

Neither A nor B passes the burden or predictor-scale gates. Design C was
therefore the **pre-registered next evidence design**. Its subsequent
acquisition is valid, but the largest episode contributes 56.55% of total
calibration burden. No design is selected for coefficient fitting.

## 10. Feasibility results

### 10.1 Primary midnight anchor

| Design and partition | Origins | \(B>0\) | \(B\ge0.10\) | \(B\ge0.25\) | \(B\ge0.50\) | Total burden |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A calibration | 4,167 | 47 | 9 | 1 | 0 | 2.608081 |
| A November validation | 76 | 0 | 0 | 0 | 0 | 0 |
| A Terra/CeFi stress | 180 | 0 | 0 | 0 | 0 | 0 |
| A USDC/SVB stress | 52 | 12 | 12 | 11 | 10 | 9.863547 |
| B calibration | 4,355 | 47 | 9 | 1 | 0 | 2.608081 |
| B November validation | 76 | 0 | 0 | 0 | 0 | 0 |
| B USDC/SVB validation | 52 | 12 | 12 | 11 | 10 | 9.863547 |

Design A calibration has mean burden 0.000626, median zero, 90th and 95th
percentiles zero and 99th percentile 0.004102. Its 47 positive origins span 24
one-sided episodes. Positive-burden IQR is 0.060471 and lag-one
six-hour-grid autocorrelation is 0.204. The largest episode contributes 19.66%
of total burden.

Design B calibration has mean burden 0.000599, median zero, 90th and 95th
percentiles zero and 99th percentile 0.003798. Adding Terra/CeFi contributes
188 retained origins but no burden, so the target counts, episode count and
total burden are unchanged.

All calibration burden occurs in 2021. Calendar years 2022, 2023 and 2024
contribute zero calibration burden under both designs. Both designs therefore
fail:

- at least 100 non-zero origins: 47 observed;
- at least 50 origins with burden at least 0.10: 9 observed; and
- non-zero burden in at least two years: one year observed.

They pass the 20-episode, 25% dominance and positive-burden-IQR gates. Passing
those partial gates does not override the failures.

### 10.2 Calibration burden by one-sided episode

| Episode | Start UTC | End UTC | Total burden |
| --- | --- | --- | ---: |
| E001 | 5 Jun 2021 11:00 | 6 Jun 2021 21:00 | 0.021283 |
| E002 | 7 Jun 2021 17:00 | 8 Jun 2021 18:00 | 0.098539 |
| E003 | 13 Jun 2021 04:00 | 14 Jun 2021 06:00 | 0.122933 |
| E004 | 16 Jun 2021 11:00 | 19 Jun 2021 18:00 | 0.395433 |
| E005 | 24 Jun 2021 02:00 | 25 Jun 2021 02:00 | 0.015900 |
| E006 | 25 Jun 2021 07:00 | 26 Jun 2021 15:00 | 0.067819 |
| E007 | 2 Jul 2021 03:00 | 3 Jul 2021 10:00 | 0.085539 |
| E008 | 5 Jul 2021 02:00 | 6 Jul 2021 07:00 | 0.132864 |
| E009 | 7 Jul 2021 22:00 | 10 Jul 2021 01:00 | 0.136553 |
| E010 | 10 Jul 2021 10:00 | 11 Jul 2021 17:00 | 0.254367 |
| E011 | 12 Jul 2021 10:00 | 15 Jul 2021 01:00 | 0.512700 |
| E012 | 15 Jul 2021 05:00 | 16 Jul 2021 06:00 | 0.036939 |
| E013 | 16 Jul 2021 09:00 | 17 Jul 2021 09:00 | 0.007908 |
| E014 | 19 Jul 2021 12:00 | 21 Jul 2021 03:00 | 0.233711 |
| E015 | 25 Jul 2021 14:00 | 26 Jul 2021 14:00 | 0.003714 |
| E016 | 8 Aug 2021 14:00 | 9 Aug 2021 14:00 | 0.008261 |
| E017 | 12 Aug 2021 14:00 | 13 Aug 2021 14:00 | 0.002625 |
| E018 | 27 Aug 2021 00:00 | 28 Aug 2021 00:00 | 0.015231 |
| E019 | 20 Sep 2021 03:00 | 21 Sep 2021 03:00 | 0.016036 |
| E020 | 26 Sep 2021 07:00 | 27 Sep 2021 07:00 | 0.013681 |
| E021 | 15 Oct 2021 09:00 | 16 Oct 2021 10:00 | 0.291722 |
| E022 | 28 Oct 2021 22:00 | 29 Oct 2021 22:00 | 0.010450 |
| E023 | 22 Nov 2021 03:00 | 23 Nov 2021 04:00 | 0.110925 |
| E024 | 10 Dec 2021 18:00 | 11 Dec 2021 18:00 | 0.012947 |

Episode ends include the 24-hour normal run that closes the one-sided episode.
Burden is attributed only from future hours below the material threshold.

### 10.3 Origin-anchor sensitivity

| Anchor | Calibration origins | \(B>0\) | \(B\ge0.10\) | \(B\ge0.25\) | Episodes | Total burden |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00 | 4,167 | 47 | 9 | 1 | 24 | 2.608081 |
| 01 | 4,164 | 42 | 10 | 1 | 24 | 2.608081 |
| 02 | 4,164 | 44 | 10 | 1 | 24 | 2.608081 |
| 03 | 4,164 | 45 | 8 | 1 | 24 | 2.608081 |
| 04 | 4,164 | 46 | 8 | 0 | 24 | 2.608081 |
| 05 | 4,164 | 46 | 6 | 1 | 24 | 2.608081 |

Each anchor partitions the same complete hours, so total burden and episode
contributions are invariant. Non-zero counts range from 42 to 47 and no anchor
passes the declared gates. The primary midnight anchor has no special boundary
failure and is retained.

## 11. Validation adequacy

The USDC/SVB interval passes the untouched downside-evaluation gate:

- 52 retained grid origins;
- 12 non-zero-burden origins; and
- 11 origins with burden at least 0.25.

Its mean burden is 0.189684, its total burden is 9.863547 and its lag-one grid
autocorrelation is 0.897. It remains wholly withheld from coefficient and
penalty selection.

November 2022 supplies 76 quiet/generalisation origins but no burden.
Terra/CeFi supplies 180 origins but no DAI downside burden under this target.
Neither can be the sole downside validation interval. Their zero results are
informative about mechanism generalisation, but do not satisfy the downside
validation gate.

The evidence can preserve a genuine withheld downside event. The present
failure is inadequate calibration variation, not the absence of a possible
validation set.

## 12. Pre-registered estimator class (not activated)

Had Design C passed every gate, the primary estimator would have been an
unweighted, L2-regularised fractional logistic mean model:

\[
E[B_t^{(6)}\mid X_t]
=
\operatorname{logit}^{-1}
\left(\beta_0+\beta^\top X_t\right).
\]

Fractional outcomes at zero and one are permitted. The primary model has no
automatic class weights, interactions, bad-debt predictor or
episode-conditioned sampling.

Because tab pressure fails its variation gate, the planned primary feature set
is lagged peg gap and ETH downside. Tab and count pressure remain separate
sensitivities on their supported subperiod. This feature set remains subject
to non-zero training-fold scale gates.

Had the gates passed, the baselines would have been:

1. unconditional mean burden;
2. lagged peg gap only;
3. lagged peg gap plus ETH downside; and
4. lagged peg gap plus eligible liquidation pressure, only if a later sample
   independently passes the pressure gate.

A hurdle sensitivity separately models \(B_t^{(6)}>0\) and positive burden.
It advances only if the fractional model has materially poor zero calibration,
both onset classes are adequate, and rolling calibration improves without
episode dominance.

## 13. Pre-registered cross-validation and uncertainty

Under the unactivated predictive design, origins would have been grouped into
contiguous calendar blocks. Expanding-window folds would have preserved
chronology and kept complete one-sided episodes within one fold. A six-hour
purge would have separated training and fold validation. Transformations would
have been owned by each training fold, with at least three valid folds
required.

Uncertainty uses the larger of one-sided episode blocks and seven-day blocks.
Grid origins are not treated as independent hourly draws. The future
estimation report must include:

- target zero share, severity, year and episode contributions;
- predictor coverage, transformations, correlation and extrapolation;
- mean squared error, mean absolute error and bounded-target squared error;
- fractional deviance or log score;
- calibration intercept, slope and reliability by predicted-burden decile;
- predicted versus observed total burden and non-zero frequency;
- episode burden error and coefficient stability;
- block-bootstrap intervals; and
- no-refit quiet and downside-stress validation.

Validation cannot select the penalty, target, anchor or evidence partition.

## 14. Liquidation-pressure role

The exact classification is **sensitivity predictor**. The reconstruction
continues to pass source-coverage, unit, state, temporal and auction
reconciliation gates. Sparse alignment with deterministic origins prevents a
primary coefficient, but does not make the state invalid.

Operationally, tab pressure may also gate confidence recovery because backlog
clearance remains economically meaningful. This secondary operational use
does not convert it into a fitted primary predictor.

## 15. Historical-evidence inventory

| Candidate | State | Coverage and frequency | Compatibility and provenance |
| --- | --- | --- | --- |
| `data/market/raw/dune_prices_hourly_2021-06-01_2024-06-30.csv` | Ignored | Four-asset hourly long panel; 1 Jun 2021–30 Jun 2024; no missing or duplicate asset-hours | Authoritative Dune `prices.hour` evidence and checksums; no earlier observations |
| `data/market/processed/dune_hourly_market_prices_processed.csv` | Ignored | 27,024-row hourly wide panel over the same period | Exact compatible DAI/USD and ETH/USD fields; complete provenance; no extension |
| `data/market/raw/dune_prices_hourly_dai_eth_2019-12-31_2024-06-30.csv` | Ignored | 78,912-row full-range long DAI/ETH extract | Adopted exact-source extension; query 8145897 and execution `01KYP8NPE5XH2KN926949AYKGT` |
| `data/market/processed/dune_hourly_dai_eth_market_prices_processed.csv` | Ignored | 39,456 complete hourly DAI/ETH rows | Canonical confidence-calibration panel; no missing hours, interpolation or provider boundary |
| `data/market/processed/combined/hourly_market_gas_panel.csv` | Ignored | 27,024-row hourly join over the same period | Compatible, but inherits the same market boundary |
| `data/market/model_inputs/environment_blocks/pool.csv` | Tracked | 27,024 hourly runtime rows over the same period | Derived input; has ETH fields but no DAI price and adds no earlier evidence |
| `data/market/processed/stablecoin_extreme_review.csv` | Ignored | 113 flagged observations within the current period | Non-exhaustive review, not a continuous sample |
| `outputs/diagnostics/calibration/market_gas_protocol/market/dai_peg_distribution.csv` | Ignored | Aggregate summaries of the current panel | No hourly observations and no earlier evidence |
| `tests/fixtures/market/empirical_market.csv` | Tracked | 19 small hourly fixture rows beginning in 2000 | Synthetic test evidence with a known gap; not empirical or provenance-backed |
| `data/provenance/calibration/confidence/` | Tracked compact evidence | Coverage, harmonisation, sparse scaling and Design C decision | Content-addressed in the calibration evidence manifest |

DAI prices are USD per DAI and ETH prices are USD per the WETH instrument in
the Dune `prices.hour` acquisitions. The full-range panel now supplies the
previously missing evidence without using vault mutations or another provider.
USDC/SVB remains wholly withheld. Design C fails its dominance gate, so the
sample is not expanded or shifted opportunistically.

## 16. Future evidence ownership

The historical acquisition creates compact, content-addressed records under:

`data/provenance/calibration/confidence/`

with coverage, harmonisation, sparse-scaling and final Design C evidence. Their
checksums are registered in `data/provenance/calibration/manifest.json`.

Generated diagnostics belong under
`outputs/diagnostics/calibration/confidence/`, and dissertation tables under
`outputs/tables/calibration/confidence/`. Those outputs remain ignored.

Future estimator code, if separately authorised, extends the existing
calibration owners in `src/dai_sim/calibration/market.py`,
`src/dai_sim/calibration/validation.py` and
`workflows/calibration/market_gas_protocol.py`. No wrapper-only workflow or
new top-level directory is required.

## 17. Remaining blockers

Coefficient fitting remains blocked because Designs A and B fail their burden
and transformation gates, tab pressure fails every sparse-variation gate and
Design C fails the fixed episode-dominance gate. Its primary market predictors
do pass the replacement positive-Q95 scaling gates, but that partial success
cannot override target concentration.

The final evidence-extension stop rule closes this predictive route. The next
bounded method is constrained simulated moments using continuous deterioration
and recovery evidence, subject to a separately authorised specification.

No coefficient has been fitted, no runtime parameter has been adopted and no
behavioural implementation is authorised.
