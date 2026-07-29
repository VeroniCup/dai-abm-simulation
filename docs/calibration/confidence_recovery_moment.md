# Confidence recovery-moment redesign

## 1. Purpose and boundary

This pass applies the pre-registered simplification hierarchy following the
Monte Carlo precision diagnosis. It tests two bounded conditional-recovery
estimands using all 74 calibration events and the objective-blind 16-candidate
panel. It does not rank candidates, estimate Stage 2 parameters, use final
validation evidence or alter production behaviour.

## 2. Failure of the old duration contrast

The old Group D contrast used eventual sustained-recovery duration. The
hierarchical MCSE estimator was correct, but the moment was not operationally
identifiable: structural non-recovery dominated its simulation variance and
longer horizons recovered only three of 15,603 censored runs. The old Sobol
search remains a valid audit under its original schema, not a search under a
replacement schema.

## 3. Structural non-recovery

Non-recovery is an economic outcome, not missing data. Candidate A represents
it as zero recovery probability. Candidate B assigns it the fixed restriction
horizon. Neither candidate uses the 792-hour censoring sentinel as an observed
duration.

Stored completion positions are converted to hours from each event's fixed
observed trough by subtracting the registered 48-hour pre-roll and the
catalogue's `hours_to_minimum`. This conversion requires no trajectory
regeneration.

## 4. Fixed replacement hierarchy

The hierarchy is:

1. select the 48-hour probability contrast only if all empirical, precision and
   sensitivity gates pass;
2. otherwise consider the 168-hour restricted-mean contrast under the same
   fixed classes of gate; and
3. if neither passes, classify the conditional recovery moment as unsupported.

Objective values cannot affect this hierarchy.

## 5. Candidate A: recovery within 48 hours

For fixed observed ETH-recovery quartiles \(Q_1\) and \(Q_4\),

\[
\Delta P_{48}
=
\frac{1}{|Q_4|}\sum_{e\in Q_4}\mathbf 1(T_e\leq48)
-
\frac{1}{|Q_1|}\sum_{e\in Q_1}\mathbf 1(T_e\leq48).
\]

The 48-hour horizon includes the 24 hours required to establish sustained
recovery and a further 24 hours for price return and gate opening. The
boundary lies near the centre of the observed calibration recovery
distribution and was fixed before simulation-fit comparison. The 72-hour and
168-hour versions are diagnostic only.

## 6. Candidate B: restricted mean to 168 hours

\[
\Delta RMST_{168}
=
\frac{1}{|Q_4|}\sum_{e\in Q_4}\min(T_e,168)
-
\frac{1}{|Q_1|}\sum_{e\in Q_1}\min(T_e,168).
\]

One week is economically interpretable, contains the 24-hour stability
requirement and remains well below the structurally uninformative 792-hour
horizon. Restrictions at 72 and 336 hours are diagnostic only.

## 7. Empirical feasibility

Both extreme quartiles contain 19 fixed events. Candidate A has an empirical
contrast of `0.1578947368421053` and scale `0.0823305695312817`. Q1 contains
16 recoveries and three non-recoveries within 48 hours; Q4 contains 19
recoveries and no non-recoveries. It therefore fails the immutable requirement
for at least four outcomes of each type in each stratum.

Candidate B has an empirical contrast of `-12.315789473684209` hours and scale
`7.464510486189091`. All 38 extreme-quartile events recover before 168 hours,
so it fails the immutable requirement for at least four observations at the
restriction in one stratum.

Scales use 2,000 fixed-stratum bootstrap resamples and the established
bootstrap-standard-deviation, IQR/1.349, consistent-MAD hierarchy. Quartile
membership is never reassigned.

## 8. Simulation precision

The existing all-event R=32/64/128/256 checkpoints provide every required
completion outcome. At R=256, analytic and replication-index MCSE agree within
15% for all 16 candidates for both estimands.

Candidate A passes the fixed MCSE gate for 16 of 16 candidates; its median and
90th-percentile projected requirements are 96 and 256 replications. Candidate
B passes for only eight of 16 candidates; its corresponding requirements are
384 and 1,024. It therefore also fails the minimum 12-of-16 precision gate and
the maximum 512-replication 90th-percentile gate.

## 9. Convergence and replication requirements

All 16 candidates show regular convergence for both estimands, with slopes
inside the pre-registered interval \([-0.65,-0.35]\). No persistent variance
floor is detected. Projections are reported only for these regular sequences
and do not authorise additional evaluation.

## 10. Parameter sensitivity

Both estimands vary materially across the objective-blind panel. Candidate A
ranges from `0.014597039473684213` to `0.408922697368421`; Candidate B ranges
from `-68.33470394736841` to `-2.453125` hours. Recovery adjustment has a clear
secondary rank relationship in both cases. These are identification
diagnostics, not fit results.

## 11. Replacement decision

The result is **conditional recovery moment unsupported**. Candidate A fails
its empirical gate. Candidate B is then considered and fails both its
empirical and simulation-precision gates. No replacement is selected.

## 12. Moment architecture

Because no candidate passes, the canonical SMM specification, empirical-moment
table and weight table remain byte-for-byte unchanged. The old duration
contrast remains an active historical row only because removing it requires a
separately pre-registered objective simplification and identification review;
it must not be used in a new search.

## 13. Evidence ownership

Compact evidence is owned by
`data/provenance/calibration/confidence/recovery_moment_*`. Generated bootstrap,
influence, MCSE and sensitivity tables remain ignored under
`outputs/diagnostics/calibration/confidence/recovery_moment_redesign/`.

## 14. Implication for a future search

A new Sobol search is not authorised. The next methodological boundary is to
pre-register an objective simplification, reconsider Group D weighting and
check whether the four-parameter vector remains identified after removal of
the unsupported channel.

## 15. Production and validation boundaries

No runtime profile, sensitivity, experiment definition, recovery gate,
parameter bound, Stage 1 estimate, residual representation or event
trajectory changes. Registry B, Powell optimisation and USDC/SVB final
validation are outside this pass.

The subsequent
[objective-simplification review](confidence_objective_identification.md)
excludes every conditional recovery moment but finds that four of five
remaining active moments fail the fixed operationality gate. The proposed
simplified objective therefore does not authorise a new search.
