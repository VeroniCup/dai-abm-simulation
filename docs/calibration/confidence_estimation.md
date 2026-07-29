# Confidence estimation design

## 1. Purpose and boundary

This document specifies the empirical estimation design for the observable
stress proxy proposed in the [confidence and behavioural calibration
plan](confidence_and_behaviour.md). The mechanism plan defines the future
confidence state and DAI response. This document defines the outcome label,
sample, predictors, liquidation reconstruction, estimator, diagnostics and
evidence ownership needed before any coefficient can be fitted.

This is a design and feasibility record. It does not estimate or adopt
behavioural coefficients, implement persistent confidence, change the current
market equation or authorise a runtime profile.

The binary persistence design is preserved here as an audit record. Its
one-class result means that the binary estimator is no longer the primary next
step. The separately pre-registered
[confidence evidence redesign](confidence_evidence_redesign.md) replaces the
primary target and origin sampling for future work without rewriting or
discarding this failed result.

The feasibility audit used the existing local hourly market panel and
Liquidations 2.0 action evidence without changing them. Temporary calculations
were kept outside the repository.

## 2. Canonical evidence and field lineage

The design uses these current empirical owners:

| Responsibility | Current evidence | Required fields and interpretation |
| --- | --- | --- |
| Hourly DAI outcome | `data/market/processed/dune_hourly_market_prices_processed.csv` | `timestamp_utc`, `dai_price_usd` |
| Hourly ETH stress | Same market panel | `eth_log_return`; the structurally missing first return is outside every eligible 24-hour lookback |
| Auction state transitions | `data/liquidations/processed/liquidation_actions_2021-06-01_2024-06-30.csv` | `kick_event.tab_raw/tab_dai`; `take_event.remaining_tab_raw/remaining_tab_dai` and `owe_raw/owe_dai` |
| Auction identity and terminal cross-check | `data/liquidations/processed/liquidation_auctions_2021-06-01_2024-06-30.csv` | `clipper_contract`, `auction_id`, `ilk`, `terminal_classification` |
| Published hourly cross-check | `data/liquidations/processed/liquidation_hourly_by_ilk_2021-06-01_2024-06-30.csv` | `debt_repaid_dai`, `successful_takes`, `auctions_completed`; its `unresolved_auctions` field is not the live intralifecycle backlog |
| Acquisition continuity | `data/liquidations/provenance/chunks/` | 37 validated monthly action/transaction chunk pairs |

The canonical auction key is `(clipper_contract, auction_id)`. The exact ilk is
carried on every state record and must be constant within that key. Successful
events are ordered by `block_number`, Ethereum `event_index`, transaction hash
and record type. The current Kick and Take event rows have no duplicate
ordering keys. Decoded call trace positions and the absent transaction-index
field are therefore not needed to order the emitted state events used here.

The feasibility input contains:

- 27,024 consecutive UTC market hours, with no duplicate or missing DAI/ETH
  prices;
- 1,157 unique Kick events and auctions;
- 1,317 successful Take events; and
- the six exact ilks `ETH-A/B/C` and `WBTC-A/B/C`.

## 3. Material below-peg outcome

The primary material downside threshold is fixed before fitting:

\[
p_t < 0.995.
\]

This is one-sided. It identifies material downside depeg, whereas
\(0.995\le p_t\le1.005\) is the separate symmetric sustained-recovery band.
An above-peg observation is not a continued below-peg observation.

The only threshold sensitivity is \(p_t<0.99\). It is reported as a
pre-registered sensitivity and must not be selected because it gives a more
favourable result.

## 4. Six-hour outcome and episodes

### 4.1 Primary outcome

The prediction origin is the start of hour \(t\). An origin is eligible only
when \(p_{t-1}<0.995\), and every predictor must be available by the end of
hour \(t-1\).

Define \(Y_t^{(6)}=1\) when:

1. at least four of \(p_t,\ldots,p_{t+5}\) are below 0.995; and
2. \(p_{t+5}<0.995\).

Otherwise \(Y_t^{(6)}=0\). Six hours is longer than a one-hour market
fluctuation, shorter than the 24-hour sustained-recovery condition, supports
non-overlapping observations and remains proportionate to an hourly
MSc-scale design.

The pre-registered horizon sensitivities are three and 12 hours. Each uses a
two-thirds occupancy requirement rounded upwards and requires the final
horizon hour to remain below the fixed threshold. Horizon choice must not be
revisited after validation.

### 4.2 Episode construction

A material below-peg episode starts at the first \(p_t<0.995\) hour following
at least 24 consecutive hours with \(p_s\ge0.995\). It ends at the hour that
completes the first subsequent run of 24 consecutive hours with
\(p_s\ge0.995\).

This one-sided episode definition groups downside prediction origins. It does
not replace the symmetric sustained-recovery metric used for simulation
reporting.

Within each episode:

1. take the first origin satisfying \(p_{t-1}<0.995\);
2. create a fixed six-hour origin grid from that first origin;
3. retain a scheduled origin only if it still satisfies the eligibility rule;
4. do not replace an ineligible scheduled slot with a later, selectively
   favourable origin; and
5. stop at the episode or data boundary.

Each retained origin receives a stable `episode_id`. Uncertainty and influence
diagnostics group by episode.

## 5. Predictors and timing

The primary feature vector is:

\[
X_t =
\left[
z(g^-_{t-1}),
z(R^-_t),
z(L_t)
\right],
\]

with:

\[
g^-_{t-1}=\max(1-p_{t-1},0),
\]

\[
R^-_t=\max\left(0,-\sum_{j=1}^{24}r^{ETH}_{t-j}\right),
\]

and:

\[
L_t =
\frac{U_{t-1}}{U_{t-1}+C^{24}_{t-1}+\epsilon}.
\]

\(U_{t-1}\) is unresolved remaining tab at the end of the prior hour and
\(C^{24}_{t-1}\) is tab cleared during hours \(t-24,\ldots,t-1\). Both are in
DAI. \(L_t=0\) only when both observed quantities are zero. No hour-\(t\)
liquidation, price or return information enters the predictors.

For every continuous predictor:

1. winsorise using calibration-sample first and 99th percentiles;
2. centre using the calibration-sample median;
3. scale using the calibration-sample median absolute deviation; and
4. freeze and reuse those values unchanged in validation and stress analysis.

Each expanding-window fold repeats these operations using only its training
portion. A zero median absolute deviation makes that predictor unidentified;
no substitute scale is introduced silently.

## 6. Sample partitions

All intervals are half-open:

| Partition | Interval |
| --- | --- |
| Full evidence | 1 June 2021 00:00 UTC to 1 July 2024 00:00 UTC |
| Validation | 1 November 2022 00:00 UTC to 21 November 2022 00:00 UTC |
| Terra/CeFi stress analysis | 5 May 2022 00:00 UTC to 20 June 2022 00:00 UTC |
| USDC/SVB stress analysis | 6 March 2023 00:00 UTC to 20 March 2023 00:00 UTC |
| Calibration | Full evidence excluding all three intervals above |

Calibration contains 25,104 hourly grid observations, validation 480, the
Terra/CeFi stress interval 1,104 and the USDC/SVB interval 336. Validation is
used once, without refitting, after labels, transformations, regularisation,
diagnostics and acceptance rules have been fixed. Stress intervals remain
descriptive and cannot add calibration outcomes.

For an eligible row, all 24 predictor-source hours and all six outcome hours
must belong to the same partition. This conservative rule prevents a single
row from crossing an exclusion boundary.

## 7. Missing-data rules

Construct the exact hourly UTC grid before episodes or predictors. Do not
interpolate DAI prices, ETH prices, remaining tab or cleared tab. An origin is
eligible only when:

- \(p_{t-1}\) and all six outcome prices exist;
- all 24 ETH return inputs exist;
- the selected liquidation measure is observed; and
- the complete predictor/outcome span is inside one partition.

Missing liquidation evidence is never zero. Zero pressure requires an observed
hour with zero unresolved tab and zero preceding 24-hour clearance.

The current market grid has no missing DAI or ETH prices and one expected
missing first-hour ETH return. No eligible origin uses that return. No
otherwise eligible origin was excluded for missing data or a partition
crossing. There were 112 scheduled episode-grid slots that failed the
\(p_{t-1}<0.995\) origin rule; these are ineligible observations, not missing
rows.

## 8. Liquidation reconstruction

For each canonical auction key:

1. initialise outstanding tab from the unique `kick_event`;
2. order successful `take_event` rows deterministically;
3. replace outstanding tab with each Take's reported remaining tab;
4. define cleared tab as the non-negative reduction from the preceding state;
5. retain the latest decoded state to each hour end;
6. resolve only at a successful Take with exact decoded
   `remaining_tab_raw == 0`, cross-checked against the auction summary; and
7. retain failed Takes only as diagnostics, never as clearance.

No Redo or Yank event occurs in the current six-ilk action fact. A future Redo
must not change tab unless its decoded semantics explicitly support that
change. No terminal event is inferred from elapsed time or a later failed call.

The temporary hourly reconstruction contains:

- `unresolved_tab_dai`;
- `cleared_tab_dai`;
- `cleared_tab_24h_dai`;
- `active_auction_count`;
- `completed_auction_count_24h`;
- tab- and count-based pressure; and
- overall and exact-ilk source-coverage indicators.

These products are feasibility calculations, not repository datasets.

## 9. Remaining-tab gate results

### 9.1 Source coverage

All 37 monthly source chunks are validated. End-of-hour unresolved states and
usable decoded remaining-tab states were:

| Ilk | Unresolved auction-hours | Usable states | Coverage |
| --- | ---: | ---: | ---: |
| ETH-A | 16 | 16 | 100% |
| ETH-B | 4 | 4 | 100% |
| ETH-C | 3 | 3 | 100% |
| WBTC-A | 14 | 14 | 100% |
| WBTC-B | 0 | 0 | Not applicable; all 14 auctions resolve within their initiation hour |
| WBTC-C | 1 | 1 | 100% |
| **Total** | **38** | **38** | **100%** |

The overall 95% and per-ilk 90% gates pass. WBTC-B does not create a false
100% unresolved-state claim: its denominator is zero, while all 14 Kick/Take
lifecycles have usable state fields. No date interval is absent because of an
extraction break.

### 9.2 Auction reconciliation

For all 1,157 auctions:

\[
\text{initial tab}
=
\text{cumulative state reduction}
+\text{final remaining tab}.
\]

All auctions pass the tolerance
\(\max(1\text{ DAI},0.001\times\text{initial tab})\). Median, 95th-percentile
and maximum absolute reconciliation errors are all 0 DAI, both overall and by
ilk and calendar quarter.

Raw RAD-to-DAI fields reconcile to their displayed scaled fields within the
source's decimal rendering tolerance: the maximum difference is
\(4.92\times10^{-21}\) DAI against a \(5\times10^{-21}\) DAI tolerance.

### 9.3 State and temporal validity

The reconstruction found:

- zero negative outstanding states;
- zero unexplained tab increases;
- zero duplicate event keys;
- zero ambiguous ordering keys;
- zero invalid or mixed-unit rows;
- zero Take auctions without an initial Kick; and
- zero negative cleared amounts.

All 1,317 successful Takes reconcile to the published hourly repayment series;
the maximum hourly floating representation difference is
\(3.73\times10^{-9}\) DAI, below the \(10^{-6}\) DAI comparison tolerance.
All 1,157 resolutions reconcile in total.

One explained hourly timing difference affects two adjacent aggregate buckets.
ETH-A auction 181 reaches exact zero tab at 20 June 2021 14:46:48 UTC. The
published panel uses its later 15:01:58 failed Take as `final_action_time`,
whereas the state reconstruction resolves at the supported zero-tab event.
This changes neither clearance nor the total completion count.

All source-coverage, reconciliation, state-validity and temporal gates pass.

## 10. Selected liquidation proxy

The tab-based backlog-to-clearance ratio is selected. It preserves the DAI
magnitude of outstanding work, passes every declared reconstruction gate and
uses only information available before the behavioural update.

The count analogue remains a rejected primary fallback:

\[
L_t^{\mathrm{count}} =
\frac{N_{t-1}^{\mathrm{unresolved}}}
{N_{t-1}^{\mathrm{unresolved}}
+N_{t-1}^{\mathrm{completed,24h}}+1}.
\]

It is retained for sensitivity analysis, not as an automatic runtime fallback.
The tab measure's selection does not imply that it has enough variation at the
eligible prediction origins.

## 11. Sample adequacy

Applying the fixed episode, origin and partition rules gives:

| Partition | Grid hours | Episodes with origins | Origins | Positive | Negative |
| --- | ---: | ---: | ---: | ---: | ---: |
| Calibration | 25,104 | 24 | 27 | 0 | 27 |
| Validation | 480 | 0 | 0 | 0 | 0 |
| Terra/CeFi stress | 1,104 | 0 | 0 | 0 | 0 |
| USDC/SVB stress | 336 | 1 | 12 | 11 | 1 |

The full sample contains 25 one-sided episodes. Episode lengths range from 25
to 95 hours, with a median of 26 hours; the 24 normal hours required to close
an episode are included in those durations. All calibration origins occur in
2021. The largest calibration episode supplies 3 of 27 origins (11.1%), below
the 25% dominance limit.

The calibration sample passes the minimum ten-episode and episode-dominance
gates, but fails both class gates:

- positives: 0, required at least 50; and
- negatives: 27, required at least 50.

At calibration origins the tab-pressure measure is zero throughout, so its
median absolute deviation is also zero. Peg gap and ETH downside have non-zero
scales, but the absence of a positive class prevents even the planned
two-predictor simplification from being fitted.

The pre-registered sensitivity checks do not remedy this shortfall:

| Threshold and horizon | Calibration origins | Positive | Negative |
| --- | ---: | ---: | ---: |
| \(p<0.995\), 3 hours | 38 | 1 | 37 |
| \(p<0.995\), 12 hours | 25 | 0 | 25 |
| \(p<0.99\), 6 hours | 1 | 0 | 1 |

Stress or validation origins cannot be imported to manufacture calibration
classes. The declared result is therefore **not estimable with the current
fixed sample**. No coefficient fit is authorised. A later pass requires a
separately pre-registered source or sampling redesign that preserves a genuine
withheld test; changing the threshold or horizon after seeing this result is
not permissible.

## 12. Primary estimator

If a future sample passes the gates, fit:

\[
\Pr(Y_t^{(6)}=1)
=
\operatorname{logit}^{-1}\left(
\beta_0+\beta_pz(g^-_{t-1})+\beta_rz(R^-_t)+\beta_lz(L_t)
\right).
\]

Use an unweighted L2-penalised logistic likelihood, no automatic class weights,
no interactions and no bad-debt predictor. Do not constrain signs
mechanically. The expected signs are:

\[
\beta_p\ge0,\qquad\beta_r\ge0,\qquad\beta_l\ge0.
\]

Pre-register penalty strengths
\(\lambda\in\{10^{-4},10^{-3},\ldots,10^4\}\). Select the lowest mean
expanding-window log loss; ties within numerical tolerance select the larger
\(\lambda\), giving the stronger regularisation. The November 2022 validation
interval is never used for selection.

A coefficient passes its sign-stability diagnostic only when it is positive in
at least 80% of valid episode-block bootstrap replications. Failure is reported
and followed by the planned ablation; it does not permit silent deletion.

## 13. Cross-validation and uncertainty

Use chronological expanding-window folds with complete episodes:

- order episodes by start time;
- place contiguous episode groups into five approximately equal validation
  blocks using origin counts without looking at labels;
- use all earlier blocks as the fold's training sample;
- never split one episode between training and fold validation;
- require both classes in every training fold; and
- fit winsorisation, median and MAD values on the fold training data only.

If fewer than three valid folds remain, fitting stops. Final uncertainty uses
episode-block bootstrap resampling; hourly rows are never treated as
independent draws.

The present sample cannot instantiate these folds because its calibration
outcome has one class.

## 14. Diagnostics and ablations

The future run must report:

- hourly coverage, missingness, duplicate timestamps and leakage checks;
- episode counts, lengths, class balance and origin influence;
- predictor distributions, winsorisation frequencies, correlations and
  condition number;
- log loss, Brier score, Brier skill against an intercept-only model, ROC-AUC
  and precision–recall AUC;
- calibration intercept, slope and a reliability table or plot;
- coefficient paths across the fixed penalty grid;
- episode-block intervals and sign frequencies;
- fold stability, probability autocorrelation and episode influence; and
- validation and stress extrapolation beyond calibration predictor ranges.

The fixed ablations are:

1. peg gap only;
2. peg gap plus ETH stress;
3. peg gap plus liquidation pressure; and
4. the full three-predictor model.

A predictor is supported only when its sign is stable, it improves rolling
calibration performance against the relevant nested model, the improvement is
not driven by one episode and probability calibration is not materially
damaged. Statistical significance alone is insufficient.

Validation applies the frozen model without refitting or intercept
recalibration and compares all primary metrics with intercept-only and
peg-gap-only baselines. Stress analysis reports probability paths, peak
persistence, episode duration, false recovery signals, predictor-range
extrapolation and the pre-registered threshold/horizon sensitivities. Stress
results do not select coefficients.

## 15. Acceptance criteria

Coefficient estimation may advance only when:

1. the outcome and episode labels reproduce exactly;
2. partitions are disjoint and no feature leaks;
3. the tab proxy continues to pass its declared gate;
4. calibration has at least 50 positive and 50 negative origins across at
   least ten episodes, with no episode above 25%;
5. every included predictor has a non-zero calibration MAD;
6. at least three chronological folds are valid;
7. the selected model improves rolling calibration over the intercept-only
   model;
8. peg gap has the expected stable sign and additional predictors pass their
   sign and ablation checks;
9. validation is applied once without refitting;
10. stress extrapolation is visible; and
11. specifications and transformations are frozen and content-addressable.

The current evidence passes items 1–3 but fails items 4–6. The estimator must
therefore allow a simpler supported model, but no model is fitted when the
outcome itself has only one calibration class.

## 16. Future evidence and output ownership

No evidence or output is created in this pass. A future authorised estimation
run should place compact, stable and content-addressed evidence under:

`data/provenance/calibration/confidence/`

with semantic artefacts such as:

- `estimation_specification.json`;
- `liquidation_pressure_coverage.json`;
- `estimation_sample_summary.json`;
- `stress_proxy_candidates.csv`;
- `stress_proxy_selection.json`; and
- `transformation_parameters.json`.

They enter the existing calibration evidence manifest only after review.

Generated diagnostics belong under:

`outputs/diagnostics/calibration/confidence/`

and dissertation-ready summaries under:

`outputs/tables/calibration/confidence/`

Both output locations remain ignored. Future implementation should extend
`src/dai_sim/calibration/market.py`,
`src/dai_sim/calibration/validation.py` and
`workflows/calibration/market_gas_protocol.py`; it must not add a wrapper-only
workflow or new top-level directory.

## 17. Remaining blockers

Before actual fitting:

- provide a separately pre-registered calibration design with enough genuine
  positive and negative outcomes while retaining meaningful withheld evidence;
- resolve zero variation in liquidation pressure at eligible calibration
  origins, or keep tab pressure as a sensitivity rather than an identified
  primary coefficient;
- ensure the revised design supports at least three chronological folds;
- decide the bad-debt severe-condition definition and optional policy/recovery
  mechanisms; and
- obtain separate authorisation for the exact estimation code and compact
  evidence files.

The evidence redesign retains the threshold and horizon but evaluates a
continuous future downside burden on a deterministic six-hour grid. Designs A
and B remain non-estimable, and no validated pre-June-2021 market extension is
currently available for Design C. After a future evidence sample passes those
gates, coefficient uncertainty, legacy/new-mode configuration review and
empirical-profile adoption remain separate decisions. Behavioural
implementation is still unauthorised.
