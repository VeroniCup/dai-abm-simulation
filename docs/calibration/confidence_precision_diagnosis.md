# Confidence Monte Carlo precision and recovery diagnosis

## 1. Purpose and fixed boundary

This diagnostic explains why the completed confidence Sobol search produced no
eligible top-16 population. It evaluates Monte Carlo precision and
recovery-time censoring only. It does not select or rank candidates, change the
registered objective, fit Stage 2 parameters, run final validation or adopt
runtime behaviour.

The core recovery moment, empirical scale, \(0.10s_j\) MCSE threshold,
four-dimensional parameter bounds, event catalogue, registry A and 792-hour
primary horizon remain exactly as registered.

## 2. Committed Sobol failure

The authoritative 256-candidate search is reproduced from search identifier
`5f3dc71ae6bbcadff06aa639a774960511a8a0e8f1a0ed316ce418c32a55795d`.
All 256 candidates are structurally and objectively valid, 53 pass the
numerical-bound gate, and none passes every MCSE gate. Consequently, the
committed top-16 population remains empty.

## 3. MCSE estimand

The estimand is simulation uncertainty conditional on the fixed empirical
event catalogue and fixed quartile membership. Cross-event empirical
heterogeneity is not Monte Carlo noise. Events receive equal weight and
replications are independent conditional simulation streams within each
event.

## 4. Analytic hierarchical estimator

For an equal-event mean with event \(e\), \(R\) replications, within-event
sample variance \(s_e^2\), and \(E\) fixed events, the analytic variance is

\[
\widehat{\operatorname{Var}}_{\mathrm{MC}}(\bar m)
=\frac{1}{E^2}\sum_{e=1}^{E}\frac{s_e^2}{R}.
\]

For the registered Q4-minus-Q1 recovery contrast, the two disjoint quartile
terms are

\[
\sum_{e\in Q4}\frac{s_e^2/R}{|Q4|^2}
+
\sum_{e\in Q1}\frac{s_e^2/R}{|Q1|^2}.
\]

The MCSE is the square root of the applicable variance. These formulae retain
fixed event weights and do not count between-event variation as simulation
error.

## 5. Replication-index cross-check

The existing implementation forms the equal-event moment independently for
each replication index and reports
\(\operatorname{sd}(m_r)/\sqrt{R}\). This is a valid cross-check under common
event weights. A 15% relative agreement tolerance is diagnostic rather than
an eligibility rule. At 256 replications, all 16 panel candidates pass this
agreement check for the recovery contrast.

## 6. Audit of the previous estimator

The previous estimator is classified as `correct_hierarchical_mcse`. Its
stored values reproduce exactly, it targets the same conditional Monte Carlo
uncertainty, and it does not add empirical event heterogeneity. The analytic
audit therefore requires no correction and does not change the original
zero-candidate eligibility result. All prior evidence is preserved.

## 7. Objective-blind candidate panel

The fixed 16-member panel is

`0, 94, 171, 42, 193, 100, 116, 127, 36, 252, 222, 97, 134, 103, 203, 126`.

Starting with Sobol index zero, each next member maximises its minimum
Euclidean distance from the existing panel in transformed Sobol space, with a
lower-index tie-break. Objective values, validity outcomes and final
validation information are absent from construction. The panel checksum is
`7ca9475da16b6e2a971d8adfe8bda6714c0841191e596e45d51bbcf2a26108f9`.

Adjacent members define eight fixed pairs for comparative-precision
diagnostics only.

## 8. Thirty-two versus 74 events

The diagnostic uses the original 32-event subset and the full 74-event
calibration catalogue. For the ETH-recovery Q4-minus-Q1 duration contrast, the
median diagnostic MCSE at \(R=256\) falls from 4.320791 hours with 32 events to
2.983049 hours with 74 events. The 74-event design therefore improves
precision materially, but only four of 16 panel candidates pass the unchanged
0.75325-hour threshold.

## 9. Replication ladder

The cumulative ladder uses \(R=32,64,128,256\), always reusing the same stream
prefixes. Recovery-contrast results are:

| Events | R | Passes / 16 | Minimum MCSE | Median MCSE | Maximum MCSE |
|---|---:|---:|---:|---:|---:|
| 32 | 32 | 0 | 2.507147 | 11.811530 | 22.302846 |
| 32 | 64 | 0 | 1.704088 | 8.400280 | 15.762358 |
| 32 | 128 | 0 | 1.179100 | 6.307638 | 11.228244 |
| 32 | 256 | 0 | 0.814564 | 4.320791 | 7.932082 |
| 74 | 32 | 0 | 1.270982 | 7.988968 | 16.093181 |
| 74 | 64 | 0 | 0.882787 | 5.815355 | 10.705956 |
| 74 | 128 | 3 | 0.643386 | 4.235654 | 8.058469 |
| 74 | 256 | 4 | 0.447909 | 2.983049 | 5.397933 |

The first 32 replications reproduce 16,384 established overlapping
candidate–event results exactly.

## 10. Convergence rates

All 16 recovery-contrast series show regular convergence under both event
sets. For 74 events, fitted log–log slopes range from -0.554649 to -0.421479,
with median -0.497414, close to the \(R^{-1/2}\) reference. The problem is not
irregular numerical convergence: the variance level is too high relative to
the fixed threshold.

## 11. Required-replication projections

At 74 events, projected power-of-two requirements are: three candidates at
128, one at 256, one at 1,024, three at 4,096, three at 8,192 and five above
8,192 replications. The operational 90th percentile is recorded as 16,384
under the conservative capped representation. Projections are descriptive and
unexecuted; they do not authorise a larger search.

## 12. Censoring at 792 hours

The extended subset contains eight objective-blind candidates, all 74 events
and 64 replications. At the primary horizon, 15,603 of 37,888
candidate–event–replication runs are right-censored. ETH-recovery Q1 and Q4
censoring rates are 0.479338 and 0.354646 respectively, an absolute imbalance
of 0.124692. The imbalance is material under the registered diagnostic rule.
The unchanged core metric records censored recovery duration as 743 hours
because the 792-step package includes the registered pre-event positioning;
the diagnostic reports this numeric sentinel rather than relabelling it.

## 13. Extended-horizon diagnosis

The 792-hour prefix is exactly equal to the primary run for all 37,888
extended-subset results and all recorded metrics. Continuing the same
candidate, event, replication and stream identities to 1,584 and 2,376 hours
produces only three additional recoveries; all three occur by 1,584 hours.
Only 0.0192% of H0-censored runs therefore recover under either extension.
No future observed DAI prices are used.

## 14. Survival-aware diagnostics

These summaries are diagnostic only. At Q1, restricted mean recovery time is
429.0773 hours at 792 and 808.7130 hours at 1,584; corresponding Q4 values are
314.6129 and 595.4928 hours. Recovery probabilities by 792 hours are 0.520662
for Q1 and 0.645354 for Q4, and do not increase by 1,584 hours. The
Q4-minus-Q1 restricted-mean contrasts are -114.4644 and -213.2202 hours.
Neither this representation nor any recovery curve replaces the registered
core moment.

## 15. Paired candidate-difference precision

Eight adjacent objective-blind pairs use identical event, replication and
stream identities. Paired recovery-contrast MCSE ranges from 2.164086 to
5.257117 hours; the corresponding unpaired calculation ranges from 2.143208
to 7.208817 hours. Pairing reduces the estimate in five of eight pairs, though
not uniformly.

Common random numbers can improve comparative precision, but they do not
satisfy the absolute MCSE gate. No pair is ranked, and paired precision cannot
replace the fixed absolute criterion without a future pre-registered
amendment.

## 16. Numerical-bound and recovery-gate interactions

Across the 16 candidates, descriptive correlations between recovery MCSE and
candidate-level diagnostics are 0.3863 for price-bound binding share, -0.0495
for confidence-floor binding share, 0.4157 for right censoring, 0.3820 for a
positive unresolved backlog and 0.5846 for material active bad debt.
Corresponding level correlations are 0.4156 for mean maximum unresolved tab
and 0.5096 for mean maximum active bad debt. Deterministic median-split
cross-tabs and grouped summaries are retained in ignored diagnostics.

These associations do not establish causation and do not justify narrowing
parameter bounds.

## 17. Computational implications

The primary candidate-invariant cache contains 18,944 packages
(1,827,757,470 bytes); the extended cache contains 4,736 packages
(1,192,133,664 bytes). Both were built once and reused across candidates.
The 303,104 primary event–replication evaluations took 379.06 seconds with
four workers, approximately 799.62 evaluations per second. Extended
H0/H1/H2 evaluation took 241.45 seconds. Cache construction took 3,424.06 and
2,227.62 seconds respectively. Peak memory was not measured portably.

The benchmark evidence projects, but does not execute, full 256-candidate
workloads at 64–1,024 replications for both 32 and 74 events. Host timing does
not alter the statistical design.

## 18. Final diagnosis

The pass is classified **recovery moment not operationally identifiable**.
The MCSE estimator is valid and convergence is regular, but most candidates
require more than 2,048 replications and censoring is predominantly structural
non-recovery. The precision-feasibility band is
`operationally_impractical_under_current_moment`.

## 19. Authorised next methodological boundary

The next permissible pass is a separately pre-registered simplification or
replacement of the recovery moment. It must explain the estimand and treatment
of structural non-recovery before any new search. This diagnosis does not
silently substitute a moment, change the horizon or authorise more
replications.

## 20. Production and validation boundaries

No candidate is selected or preferred. Powell, registry B and USDC/SVB final
validation are not run. The 0.10 threshold, empirical scales, event evidence,
core moments and model equations are unchanged. Persistent confidence remains
dormant; no runtime profile, sensitivity or experiment adopts a Stage 2 value.

Compact evidence is registered under
`data/provenance/calibration/confidence/`; generated checkpoints, interaction
tables and timing detail remain ignored under
`outputs/diagnostics/calibration/confidence/monte_carlo_precision/`.
