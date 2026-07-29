# Confidence objective simplification and identification gate

## 1. Purpose and boundary

This pass pre-registers a seven-moment reporting specification and a
five-moment Stage 2 objective for the dormant persistent-confidence mechanism.
It asks whether the active moment set is operational enough to justify a
numerical identification exercise for
\((\alpha_d,\alpha_r,C_{\min},\kappa_P)\). It does not fit, rank or adopt a
parameter vector.

## 2. Unsupported conditional recovery channel

The historical ETH-conditioned recovery-duration contrast is operationally
unidentified. The pre-registered 48-hour probability replacement has a Q4
historical ceiling, while the 168-hour restricted mean has no binding
historical cap and insufficient simulation precision. All three conditional
recovery candidates are therefore excluded from the prospective objective.
The historical eight-moment specification remains immutable as an audit
object and must not be searched again.

## 3. Seven-moment reporting architecture

The reporting specification retains:

1. ordinary below-peg mean next-hour change;
2. ordinary above-peg mean next-hour change;
3. first-six-hour burden;
4. maximum downside deviation;
5. sustained-recovery completion hours;
6. failed recovery attempts;
7. initial-gap Q4-minus-Q1 maximum-six-hour-burden contrast.

The first two moments preserve the accepted Stage 1 response. The remaining
five are the proposed Stage 2 objective.

## 4. Five active Stage 2 moments

The active moments measure two deterioration outcomes, two unconditional
recovery outcomes and one initial-gap conditional burden contrast. No
ETH-conditioned recovery moment, probability replacement or restricted-mean
replacement is active.

## 5. Stage 1 preservation constraints

The ordinary below- and above-peg changes retain zero Stage 2 weight. Each
must reproduce its accepted Stage 1 value within two empirical scales. A
failure is implementation drift rather than Stage 2 misfit, so its discrepancy
does not enter the objective.

## 6. Weighting rationale

Each active moment receives weight 0.20. The active weights sum to one,
preserving equal original per-moment importance after removing the two fixed
Stage 1 moments and the unsupported recovery contrast. Deterioration and
recovery each receive 40 per cent, while conditional burden receives 20 per
cent. No moment exceeds the established concentration limit.

For standardised discrepancies
\(d_j=(m_j^{sim}-m_j^{data})/s_j\), the prospective loss is

\[
J_5=\sum_{j=1}^{5}0.20d_j^2.
\]

The pure implementation returns total loss, moment contributions, group
subtotals and preservation-constraint status. It was not used to rank any
candidate.

## 7. Active-moment operationality

The audit reuses all 74 calibration events, registry A, the objective-blind
16-candidate panel and the completed 256-replication ladder. An active moment
requires a finite positive scale, non-zero simulated variation, at least 12 of
16 candidates passing \(\mathrm{MCSE}\le0.10s_j\), regular convergence for at
least 75 per cent of candidates and no deterministic calculation failure.

| Active moment | MCSE passes | Regular convergence | Operational |
| --- | ---: | ---: | --- |
| First-six-hour burden | 10/16 | 14/16 | No |
| Maximum downside deviation | 3/16 | 15/16 | No |
| Sustained-recovery completion hours | 8/16 | 16/16 | No |
| Failed recovery attempts | 16/16 | 16/16 | Yes |
| Initial-gap burden contrast | 10/16 | 15/16 | No |

All moments have finite empirical support and non-zero panel variation.
Nevertheless, four fail the fixed precision count. The operationality gate
therefore fails.

Sustained-recovery completion retains the existing unconditional treatment:
non-recoveries enter at the 792-hour administrative horizon. The median
candidate censoring share is approximately 0.616. Its 8/16 precision result
shows that structural non-recovery continues to make this unconditional
moment unstable.

## 8. Objective-blind anchors

The pre-registered design would select five Sobol anchors whose unit
coordinates all lie in \([0.15,0.85]\): centre-nearest first, followed by
iterative farthest-point selection with lower candidate-index tie-breaking.
Because the operationality gate failed, no anchors were selected. Candidate
62 and objective values played no role.

## 9. Finite-difference design

The prospective design uses transformed coordinates, central differences at
\(h=0.05\), and a central-anchor check at \(h=0.025\). It specifies all 74
events, registry A, 128 replications for five-anchor derivatives and an exact
256-replication prefix extension at the central anchor. No derivative was
evaluated.

## 10. Paired derivative uncertainty

The implemented primitives estimate paired central derivatives, derivative
MCSE, signal-to-noise ratios, signs and complete Jacobians under common random
numbers. A local signal requires SNR at least two. These routines were tested
on synthetic inputs only; the empirical operationality failure blocked their
application to simulator results.

## 11. Local Jacobians

The fixed local gates require rank four, condition number no greater than
\(10^3\), singular-value ratio at least \(10^{-3}\), absolute column cosine no
greater than 0.995 and signal for every parameter. No local Jacobian was
constructed.

## 12. Stacked global Jacobian

The prospective stacked matrix scales five local Jacobians by
\(1/\sqrt{5}\). It would apply the same rank, conditioning and cosine gates,
plus signal at three of five anchors for every parameter. No stacked matrix or
singular value was calculated.

## 13. Parameter profiles

The fixed profile grid is \(0.10,0.30,0.50,0.70,0.90\), varying one
transformed coordinate at a time with paired common random numbers. A
parameter would be non-flat if an active moment moved by at least half an
empirical scale and endpoint MCSE were no more than one quarter of that move.
No profile was evaluated.

## 14. Full-model identification

The full four-parameter model cannot be classified as identified because all
five active moments must first be operational. Rank, conditioning,
step-size-stability and parameter-flatness gates remain unevaluated rather
than being treated as failures.

## 15. Restricted-model hierarchy

The fixed hierarchy remains:

1. test \(\kappa_P=0\) only if panic response causes the decisive failure;
2. require independent identification if \(C_{\min}\) is unsupported;
3. test \(\alpha_d=\alpha_r\) only for decisive deterioration/recovery
   collinearity while the other parameters remain supported;
4. otherwise classify identification as unresolved.

The active-moment failure occurs before parameter-specific evidence exists, so
no restricted model was evaluated.

## 16. Prospective objective identity

The proposed reporting schema, active moments, scales, weights, preservation
constraints and protected source checksums produce prospective objective
identity
`6438dd1e723b95716365a177e341d23fe5f0cce1b30df0b862b339edef749971`.
This is a content address for the rejected prospective design, not a new
search identity.

## 17. Computational and storage implications

The audit reused 18,944 candidate-invariant cache packages and the registered
303,104-row replication ladder. It produced no new simulator evaluations and
no ignored identification payload. The existing multi-gigabyte cache was not
copied. More than 10 GB remained free throughout.

After the decision is committed, the ignored
`outputs/diagnostics/calibration/confidence/objective_identification/`
directory is safe to remove if it exists; this pass creates no required
content there. The authoritative Monte Carlo cache remains useful for audit
reproduction and was not deleted.

## 18. Final decision

The final classification is
`seven_moment_specification_not_operational`. Only failed recovery attempts
passes the complete active-moment operationality gate. No objective
comparison, anchor selection, Jacobian, profile, restricted model, parameter
fit or runtime adoption follows.

## 19. Authorised next boundary

Any continuation requires a separately pre-registered review of active-moment
precision or evidence design. A new Sobol search is not authorised under this
five-moment proposal, and the historical eight-moment objective must not be
searched again.

## 20. Production and validation boundaries

Persistent confidence remains dormant. Runtime profiles, sensitivities,
experiments, model inputs, vault mechanics, liquidation mechanics and price
processes are unchanged. Registry B, Powell optimisation, final validation and
the USDC/SVB event remain outside this pass.
