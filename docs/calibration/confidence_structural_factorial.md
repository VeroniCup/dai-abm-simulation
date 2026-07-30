# Persistent-confidence structural factorial

## 1. Purpose and boundary

This pass tests whether three structural families that produced partial
one-factor signals interact in the dormant persistent-confidence conditional
event experiment. It is a pre-registered, objective-blind \(2^3\) diagnostic,
not a parameter search or a model-selection exercise. Empirical bands,
parameter bounds, events, candidate identities and production behaviour remain
unchanged.

## 2. Prior multiple-family diagnosis

The preceding structural diagnosis classified the evidence as
`multiple_structural_families_contribute`. A lower historical
system-collateral-ratio state, zero residual innovations and removal of the
unresolved-backlog recovery blocker each partly moved downside and recovery
summaries towards their empirical bands. No isolated intervention resolved a
complete empirical constraint.

## 3. Three-factor rationale

The factorial retains only those three families. Liquidation capacity and
observable-stress weights had no explanatory signal, while complete
event-hour historical gas ownership was unavailable. Excluding them avoids an
unregistered fourth factor and keeps the experiment interpretable.

## 4. Factor levels

Factor A compares the baseline standardised 500-vault state with the committed
historical P25 system-collateral-ratio state. Factor B compares accepted
24-hour moving-block residual innovations with a zero-residual mechanism
diagnostic. Factor C compares the full recovery gate with removal of the
unresolved-backlog condition while retaining the active-bad-debt condition.

Each high level changes only its registered assumption family. Zero residuals
are not an alternative empirical residual model, and backlog removal is not an
altered liquidation state.

## 5. Eight-cell design

Cells use the fixed order `000`, `100`, `010`, `001`, `110`, `101`, `011`,
`111`. Binary positions correspond to A, B and C. Standard signed coordinates
of \(-1,+1\) define main effects and interactions with the registered
high-minus-low coefficient of one quarter.

The content-addressed factorial identity is
`4558b97de3c092b8cec70b9117407333527f517559b7126fa0428c5e9059ad00`.

## 6. Reuse of four existing cells

Cells `000`, `100`, `010` and `001` reproduce the committed baseline and three
single-factor streams. Their 303,104 event-replication evaluations are reused
exactly. They are not rerun to simplify implementation or checkpoint
ownership.

## 7. Four new interaction cells

Cells `110`, `101`, `011` and `111` add the four missing combinations. At the
initial 64 replications they contribute 303,104 evaluations and 64 atomic
cell-candidate checkpoints. No existing cell is duplicated.

## 8. Objective-blind panel and common-random-number ownership

Every cell uses the same ordered panel of 16 candidates, all 74 calibration
events and registry A. Candidate, event and replication identities are paired
before cell contrasts are formed. The USDC/SVB final-validation event, registry
B and previous objective values or ranks do not enter.

## 9. MCSE reconciliation

At 64 replications, the analytic hierarchical and replication-index MCSE
estimators passed the fixed 15% agreement rule for only 13 of 16 candidates
for the failed-recovery-attempts C and BC effects. The affected candidates
were 42, 94 and 134.

An ownership audit found no formula error. Both estimators construct the
paired eight-cell factorial effect before uncertainty estimation, use equal
event weights and sample variances with one degree-of-freedom correction, and
target the same conditional Monte Carlo estimand. Exact nested prefixes showed
changing disagreement rather than a fixed ownership discrepancy.

The separately content-addressed precision identity is
`107c5698528ad433371a7d7f49ffde533691c30c032b92edf47b1cf5611cac52`.
A pre-registered uniform extension added replications 65–128 for all eight
cells, all 16 candidates and all 74 events. It reused 606,208 evaluations and
added exactly 606,208; no original checkpoint was overwritten.

At 128 replications every registered moment-effect combination passes the
unchanged requirement of at least 15 of 16 candidates within 15%. C and BC
for failed recovery attempts pass exactly 15 of 16; candidate 42 remains the
single candidate-level disagreement. The gate concerns the registered
combination count and is therefore valid without waiving that observation.

## 10. Cell compatibility

No cell contains an inner-compatible or outer-compatible candidate. All five
empirical constraints remain unresolved in every cell. Cell `101` meets the
fixed `partial_constraint_improvement` classification; the other seven cells
meet `no_compatibility_improvement`. This is not a ranking and does not make
cell `101` an admissible structural model.

## 11. Factorial main effects

Main effects A, B and C and interactions AB, AC, BC and ABC are calculated
separately for every candidate and moment. Effects are formed at the paired
event-replication level. The evidence retains analytic and replication-index
MCSEs, the larger agreed estimator, signal-to-noise ratios, 32-replication
prefix signs and dominant-event shares. Effects are never aggregated across
moments.

## 12. Two-factor interactions

The AB cells (`110`) and BC cells (`011`) show materially mixed interactions
for maximum downside deviation. The AC cell (`101`) shows antagonistic
interactions for maximum downside deviation and recovery-completion duration.
Other two-factor moment interactions are approximately additive under the
registered magnitude, precision and candidate-count rules.

## 13. Three-factor interaction

Cell `111` has a materially mixed three-factor interaction for maximum
downside deviation. Its interactions for burden, recovery duration, failed
recovery attempts and the initial-gap burden contrast are approximately
additive. It does not create an admissible candidate.

## 14. Additive predictions

Each two-factor cell is compared with the sum of its two single-factor shifts
relative to baseline. Cell `111` is compared with
\(m_{100}+m_{010}+m_{001}-2m_{000}\). Actual and additive values retain signed
empirical-band gaps, their difference and paired uncertainty. Movement is
defined from distance to the empirical band, never from the raw effect sign.

## 15. Synergy and antagonism rules

A material interaction requires a common band-gap direction for at least 12
of 16 candidates, at least eight residuals of one-half empirical scale with
paired signal-to-noise ratio of at least two, and a median absolute band-gap
difference of at least one-half scale.

The completed experiment contains no synergistic interaction, two
antagonistic interactions, three materially mixed interactions and 15
approximately additive interactions. These labels follow the fixed rules and
are not comparative scores.

## 16. Trade-offs

No cell passes the separate registered cell-level trade-off rule. Nevertheless,
combined interventions remain incompatible and introduce material mixed or
antagonistic effects in the moments they were intended to improve. The final
hierarchy therefore records structural interaction trade-offs rather than
claiming compatibility from smaller raw values.

## 17. Mechanism diagnostics

Generated diagnostics retain recovery censoring, recovery probability at 48,
168 and 792 hours, failed attempts, numerical-bound share, confidence-floor
binding, unresolved backlog, maximum unresolved tab, active bad debt and
maximum active bad debt. These explain paths but are not additional empirical
constraints.

## 18. Final classification

The fixed overall classification is
`factorial_interactions_reveal_tradeoffs`. There is no compatible cell, all
five constraints remain unresolved, and the interaction evidence contains
material adverse or mixed behaviour rather than a coherent multi-constraint
resolution.

No cell, candidate, parameter or structural model is selected. Persistent
confidence remains dormant and `runtime_adopted` remains false.

## 19. Authorised next boundary

The empirical calibration-rescue programme for the present confidence
formulation ends. Confidence parameters may remain transparent, pre-specified
scenario dimensions. That boundary is now implemented by the
[persistent-confidence scenario registry](../experiments/confidence_scenarios.md),
which reconstructs fixed quartile bundles from the original coupled transform.
It does not select a factorial cell or use interaction results to determine
scenario values. A future structural formulation would require independent
economic justification and a new versioned design; this factorial result does
not authorise direct adoption or another behavioural search.

## 20. Limitations of the panel

The panel contains 16 objective-blind points from the fixed 256-vector domain,
not a representative probability sample of behavioural parameters. The
experiment is conditional on the registered event catalogue, observed ETH
paths, simplified vault and liquidation representation, support bands and
natural bounds. Zero residuals and gate ablation are mechanism diagnostics,
not empirically estimated production alternatives.

## 21. Production, storage and reproducibility

Production profiles, sensitivities, experiment definitions and simulator
mechanics are unchanged. The extension uses 128 compact metadata checkpoints
and four shared suffix shards beneath the ignored factorial identity
directory; the original 64-replication checkpoints remain intact. No full
trajectories, pickle files or duplicated all-event cache are stored.

Compact factorial and precision evidence is registered under
`data/provenance/calibration/confidence/`. Detailed shards, prefix
reconstructions, mechanism diagnostics and timing records remain ignored under
`outputs/diagnostics/calibration/confidence/structural_factorial/`.
