# Pre-registered confidence Sobol search

## 1. Purpose and stage boundary

This pass evaluates the fixed Stage 2 search design for the dormant
persistent-confidence mechanism. It is a calibration experiment, not a
production integration. It ranks bounded candidates for a later all-event
follow-up but does not select a final parameter vector.

The execution excludes the 74-event top-16 follow-up, Powell refinement,
64-replication confirmation, registry B, Jacobian and profile diagnostics,
leave-one-event-out analysis and final USDC/SVB validation.

## 2. Fixed scientific design

The search contains 256 scrambled Sobol candidates, 32 content-selected
calibration events and 32 replications per event under registry A: 262,144
event–replication runs. The event subset, structural vectors, parameter
bounds, stress weights, moment definitions, empirical scales, four objective
groups and seeds are registered inputs and cannot respond to candidate fit.

The eight moments are the two ordinary Stage 1 preservation moments, two
downside-severity moments, two recovery moments and two cross-event contrasts.
Replications are averaged within event before events receive equal weight.

## 3. Content-addressed search identity

The search identifier is a SHA-256 of all registered scientific evidence
checksums, the event-subset and candidate checksums, implementation schemas,
counts and registry identifier. Wall time, process identifier, hostname,
output path and Python's randomised hash are excluded. A scientific or
implementation change therefore creates a new search rather than silently
sharing checkpoints.

## 4. Immutable candidate-invariant cache

Each event–replication package records the deterministic initial vault state,
observed ETH path, pre-roll, common horizon, starting DAI price, residual
innovations, all three stream seeds, empirical event strata and eligibility.
It also precomputes the exact candidate-invariant liquidation evolution using
the existing vault, liquidation-demand and liquidation mechanics.

This is valid because the four Stage 2 confidence parameters affect simulated
DAI confidence and price but do not enter vault valuation, keeper demand or
liquidation execution. A reference equivalence gate requires cached evaluation
to reproduce the established event simulator. Packages use canonical JSON and
pickle-free deterministic NPZ arrays under the ignored search directory.

The 1,024 packages are reconstructed twice. Package identities, bytes,
checksums and the aggregate root checksum must agree exactly.

## 5. Deterministic process parallelism

The parallel task is one complete candidate. A spawned worker loads immutable
cache metadata once, processes events by sorted event identifier and
replications numerically, and caps numerical-library threads at one. Candidate
results do not depend on worker completion order, and no worker reads live
data or writes tracked evidence.

The operational benchmark tests one, two, four and six workers where supported
on candidates 0, 63, 127 and 255, the first four fixed search events and all 32
replications. The smallest worker count within 5% of maximum observed
throughput is selected.

## 6. Atomic checkpoints and resume

Every candidate has a canonical JSON checkpoint and a compact pickle-free
metric array. A sibling temporary file is flushed and synchronised before
atomic replacement. A checkpoint is reusable only when its search identity,
candidate vector, schemas, payload checksums, 32 events, 32 replications and
result checksum validate.

Incomplete or invalid candidates are recomputed from the same inputs. Valid
candidates are never silently overwritten. A search lock records operational
ownership and rejects a second live writer; stale-lock recovery is explicit.
Resume history distinguishes skipped, invalid-recomputed and newly evaluated
candidates.

## 7. Serial–parallel equivalence

Candidates 0, 127 and 255 are evaluated serially and with the selected worker
count across the full 32-event design. Result checksums, simulated moments,
standardised discrepancies, objectives, event checksums, censoring and
numerical-bound diagnostics must be exactly equal. A floating tolerance is not
used to excuse schedule dependence.

## 8. Candidate validity

Structural validity requires complete results, bounded confidence, finite and
bounded DAI prices, valid cached vault/liquidation/bad-debt states, no future
DAI information and exactly one panic term. Objective validity requires all
eight finite moments, positive registered scales, four finite group
contributions and a finite total.

Monte Carlo validity requires each moment's replication MCSE to be no greater
than 10% of its registered empirical scale. Numerical validity requires the
maximum event–replication DAI-bound binding share not to exceed 1%. Replication
counts are never changed after observing a failure.

## 9. Ranking and non-final top 16

Structurally and objectively valid candidates are ordered by:

1. MCSE pass;
2. numerical-bound pass;
3. total objective;
4. candidate index.

Exactly 16 candidates are accepted for future all-event evaluation only if at
least 16 pass both additional gates. They are not final estimates, runtime
values or Powell starting points at this stage.

## 10. Evidence and runtime boundary

Ignored diagnostics contain caches, candidate checkpoints, contribution and
MCSE tables, worker timings and resume history. Compact tracked evidence
contains the search specification, cache summary, one-row-per-candidate table,
non-final top 16, reproducibility record and benchmark. Compact evidence is
reconstructed twice from checkpoints; deterministic content must be
byte-identical, while host timings remain explicitly operational.

No runtime profile, sensitivity, experiment factory, model input or production
simulation imports the search. Final validation remains untouched.

## 11. Limitations and next stage

The search uses a standardised ETH-only conditional experiment rather than an
exact historical Maker replay. Calibration events occur in 2020–21, so
temporal transport remains a validation risk. Passing the search authorises
only the pre-registered top-16 evaluation on all 74 calibration events. It
does not authorise Powell, registry B, final validation or runtime adoption.

## 12. Completed search result

The fixed search completed all 256 candidates and 262,144 event–replication
runs under registry A. The final search used four spawned workers, completed
in 364.25 seconds and reproduced serial results exactly for candidates 0, 127
and 255. All candidates passed structural and objective validity, and 53
passed the numerical-bound gate.

No candidate passed the fixed all-moment MCSE gate. In particular, the
ETH-recovery quartile duration contrast exceeded \(0.10s_j\) for every
candidate at the fixed 32 replications. The deterministic top-16 file
therefore records `insufficient_valid_candidates` and contains no selected
candidate. This is a valid scientific result, not an infrastructure failure.
The pass is classified **Sobol search completed but insufficient valid
candidates**.

No replication was added, no threshold was relaxed and no candidate was
retried in response to this result. The all-event stage, Powell, registry B,
final validation and runtime adoption remain blocked.
