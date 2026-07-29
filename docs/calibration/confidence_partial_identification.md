# Persistent-confidence partial identification

## 1. Methodological pivot

The five-moment Stage 2 point objective is not operational at the registered
Monte Carlo precision budget. That finding rules out another ranked search; it
does not rule out asking which regions of the fixed parameter domain remain
compatible with broad empirical evidence. This pass therefore replaces point
estimation with a bounded, grid-based admissible-set analysis.

The result is a finite-grid approximation to a partially identified set. It is
not a formal asymptotic confidence region, a posterior distribution, a
shortlist of estimates or a claim that retained vectors are equally likely.

## 2. Point and partial identification

Point estimation would require an operational scalar objective capable of
ordering parameter vectors. Four of the five proposed Stage 2 moments fail the
fixed operationality gate, so that route remains closed.

Partial identification instead asks whether each candidate's simulated-moment
uncertainty is compatible with pre-registered empirical support regions.
Compatibility is assessed constraint by constraint. No discrepancies are
summed, and neither distance from a band centre nor historical candidate rank
affects retention.

## 3. Fixed parameter grid

The analysis uses the existing 256-point objective-blind Sobol design for

\[
(\alpha_d,\alpha_r,C_{\min},\kappa_P).
\]

Candidate indices 0–255, transformed coordinates, structural vectors,
parameter bounds and checksum
`fc56a12f0066cd84a15f5df52254ccf4a678847168af45e7f235757b3b1adde5`
remain unchanged. The grid is neither pruned nor refined, and candidate 62 has
no privileged role.

## 4. All-event simulation design

Every candidate is evaluated on all 74 calibration events with the first 64
registry-A replication identities. The fixed workload is therefore

\[
256\times74\times64=1,212,416
\]

event–candidate–replication evaluations. Candidate-invariant event packages
are reused from the validated all-event cache. Final-validation events,
registry B and the USDC/SVB episode remain excluded.

One atomic ignored checkpoint is retained per candidate. Checkpoints contain
event-level sufficient statistics and deterministic result checksums, not
trajectories or complete event-by-replication arrays.

## 5. Empirical support bands

For each of the five behavioural summaries, the empirical support band is

\[
B_j=[m_j^{data}-2s_j,m_j^{data}+2s_j].
\]

The multiplier is fixed before candidate evaluation. Bands are intersected
with natural support: burden lies in \([0,1]\), downside deviation and failed
attempts are non-negative, recovery completion lies in \([0,792]\), and the
initial-gap burden contrast lies in \([-1,1]\). Both raw and adjusted endpoints
are recorded.

The five constraints are:

1. first-six-hour burden;
2. maximum downside deviation;
3. sustained-recovery completion hours;
4. failed recovery attempts;
5. initial-gap Q4–Q1 maximum-six-hour-burden contrast.

The ordinary below- and above-peg moments remain hard Stage 1 preservation
checks with zero Stage 2 weight.

## 6. Simulation uncertainty intervals

The verified analytic hierarchical MCSE is used for every candidate and
moment. The fixed 90 per cent Monte Carlo interval is

\[
C_{cj}=
[\widehat m_{cj}-1.645\,MCSE_{cj},
 \widehat m_{cj}+1.645\,MCSE_{cj}],
\]

again intersected with natural support. The replication-index estimator is
retained only as a diagnostic cross-check for the existing objective-blind
16-candidate panel; it never replaces the analytic MCSE.

## 7. Inner and outer admissibility

A moment receives an inner pass when its complete Monte Carlo interval lies
inside the empirical band. It receives an outer pass when the two intervals
overlap. Disjoint intervals fail.

A candidate is inner-admissible when all five moments pass the inner rule and
all hard gates pass. It is outer-admissible when all five receive at least an
outer pass and all hard gates pass. Outer-only candidates are outer-admissible
but not inner-admissible. Any failed moment or hard gate rejects the vector.

Outer compatibility means only that the candidate is not clearly incompatible
at the registered simulation precision. It is not a probability statement.

## 8. Hard structural gates

Every candidate must preserve valid confidence, price, vault, liquidation and
bad-debt states; complete event results; causal information; and one-count
panic transmission. No more than one per cent of accepted simulated steps may
bind a numerical DAI-price bound. Both Stage 1 preservation constraints must
remain within two registered empirical scales.

Right censoring is reported but is not an extra hard gate. It already enters
the fixed 792-hour recovery-completion convention.

## 9. Parameter-set summaries

Inner, outer, outer-only and rejected grid sets are summarised separately.
Reported diagnostics include counts, fractions, structural-parameter
quantiles, prior-normalised widths, boundary occupancy, rank correlations,
pairwise feasible ranges, numerical-bound distributions, censoring
distributions and constraint-specific failure counts.

Contraction is measured in prior-normalised Sobol coordinates:

\[
\rho_k=1-(\max_{c\in A}z_{ck}-\min_{c\in A}z_{ck}).
\]

These quantities describe the retained finite grid. They do not imply that
every continuous vector inside the reported envelope is admissible.

## 10. Objective-blind representatives

At most 24 outer-admissible candidates form a future robustness set. Selection
includes each parameter's grid-supported extrema, the outer medoid, the inner
medoid where available, and transformed-space farthest points. Ties are
resolved by lower candidate index.

Objective values, moment-centre distances, old ranks and candidate 62 do not
enter selection. Representatives are authorised only as design points for
later mechanism and policy robustness experiments. They are not estimates.

## 11. Structural non-recovery diagnostics

For every set, the analysis reports recovery-completion censoring, recovery
probabilities by 48, 168 and 792 hours, failed-recovery attempts, maximum
unresolved tab and maximum active bad debt. These diagnostics describe the
mechanisms behind admissibility and rejection. They are not new constraints or
replacement recovery moments.

## 12. Finite-grid limitations

The design can miss compatible regions between Sobol points, and grid
envelopes may conceal non-convexity or disconnected sets. Sixty-four
replications leave non-negligible Monte Carlo uncertainty by design, which is
why inner and outer sets are distinguished. Empirical support bands are broad
compatibility regions, not sampling-confidence intervals.

The analysis does not assign likelihoods, posterior probabilities or
preference weights to retained vectors.

## 13. Final classification

The compact evidence records one pre-registered outcome:

- partial identification established;
- weak partial identification;
- sparse admissible set;
- model–evidence incompatibility; or
- invalid analysis.

The classification follows only the fixed candidate-count, contraction,
inner-set, outer-only-share and reproducibility rules. It cannot be revised by
inspecting attractive vectors.

## 14. Authorised robustness boundary

If partial identification is established, later work may run mechanism and
policy experiments over the fixed representative set and report conclusions
robust across all representatives, with inner-set results distinguished.
Weak identification authorises broad sensitivity only. A sparse set requires
a separately pre-registered denser objective-blind grid. Incompatibility
requires review of structural assumptions or empirical bands without relaxing
them retrospectively.

No outcome authorises point fitting, candidate ranking or runtime adoption.

## 15. Production and validation boundaries

Persistent confidence remains dormant. Stage 1 estimates, event mechanics,
recovery gates, residual blocks, parameter bounds, profiles, sensitivities,
experiments and runtime inputs are unchanged. Final validation remains
untouched; Powell, registry B and USDC/SVB are outside this pass.

## 16. Completed finite-grid result

All 256 candidates completed the fixed 1,212,416 event–candidate–replication
evaluations. The inner and outer sets are both empty: zero candidates are
inner-admissible, zero are outer-only and all 256 are rejected. The
pre-registered classification is therefore **model–evidence
incompatibility**.

The outer-failure counts are 241 for first-six-hour burden, 255 for maximum
downside deviation, 256 for recovery-completion hours, 247 for failed
recovery attempts and 256 for the initial-gap burden contrast. Structural and
Stage 1 preservation gates pass for every candidate; 203 candidates fail the
one-per-cent numerical-bound gate. Because no outer set exists, there is no
admissible parameter envelope, contraction claim or representative vector.
The empty representative set is the logically required result, not a failed
selection.

The authorised next boundary is to review structural model assumptions or the
empirical support-band design without retrospectively relaxing the fixed
bands. No parameter is selected and no robustness experiment is authorised
from an empty representative set.

## 17. Storage and reproducibility

The scientific identity hashes the fixed empirical values and scales, support
and interval rules, parameter grid, event catalogue, registry, replications,
conditional-event inputs, gates and implementation schema. Host timing,
output paths, candidate classifications and representative indices are
excluded.

Detailed checkpoints remain ignored under
`outputs/diagnostics/calibration/confidence/partial_identification/`. Compact
specification, constraints, candidate classifications, set summary,
representatives, reproducibility and benchmark evidence are registered under
`data/provenance/calibration/confidence/`. The candidate-invariant cache is
reused in place and must not be duplicated.
