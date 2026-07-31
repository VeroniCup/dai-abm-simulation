# H4 recovery and behavioural-stabilisation evidence synthesis

## 1. Purpose

This report completes the registered evidence synthesis for the final
programme. It organises frozen findings; it is not a sixth experiment, a new
calibration, a meta-analysis or an out-of-sample validation.

## 2. RQ3 and H4

RQ3 asks which collateral-recovery and behavioural assumptions materially
affect the speed and reliability of peg restoration after stress. H4 expects
recovery to depend jointly on collateral rebound, liquidation resolution and
behavioural stabilisation, with unresolved backlog limiting favourable
recovery conditions.

## 3. Evidence-synthesis status

The scientific status is `registered_evidence_synthesis`. Component
experiments were independently pre-registered and their decisions are frozen.
The rules below organise known registered findings and cannot create new
cross-experiment causal contrasts. Evidential strength comes from consistency
and mechanism triangulation, not pooled statistical estimation.

## 4. Source hierarchy

Tier 1 registered decisions, immutable specifications, reproducibility records
and identities are authoritative. Tier 2 compact summaries quantify Tier 1
decisions but cannot change them. Tier 3 tracked reports supply terminology,
mechanism interpretation and limitations but cannot override a decision.
Ignored checkpoints, untracked notes, held-out observations, USDC/SVB and
external evidence are excluded.

## 5. Confidence-identification boundary

Point estimation, partial identification and the structural factorial are
complete. There is no admissible persistent-confidence vector or structural
factorial cell, calibration rescue is closed, and persistent confidence is
dormant by default. The structural conclusion remains
`factorial_interactions_reveal_tradeoffs`.

The registry contains exactly `stage1_only`, `confidence_resilient`,
`confidence_central` and `confidence_fragile`. The three active cases are
transparent assumptions, not estimates. They are not ranked or selected;
`confidence_central` is not an empirical central estimate, and Stage 1-only
remains the production default.

## 6. Unbounded conditional null

The unbounded ETH study completed 2,048 simulations across four recovery paths
and four confidence scenarios without a numerical failure. Its decision is
`no_clear_recovery_path_effect`, interpreted here as
`conditional_channel_absence`: the severe shock made almost all 100 legacy
vaults liquidatable, and full-close ordinary execution resolved nearly all
positions immediately. Unresolved tab and active bad debt then offered no
inventory for later collateral rebound to rescue. This does not show that
collateral recovery is universally irrelevant.

## 7. Constrained recovery result and historical source crosswalk

The constrained ETH study completed 3,072 simulations across 24 cells without
a numerical failure. Full-week recovery avoided mean liquidation debt of
7,213.87, 5,579.38 and 5,237.86 DAI at capacities 14, 26 and 45. Mean
backlog-area reductions were 203,360, 140,912 and 130,803 DAI-hours, with all
registered intervals excluding zero. Mean positions recovered before
execution were 27.65, 20.33 and 17.92.

The frozen internal decisions are H5a `supported`, H5b `not_supported`, H5c
`present` and H5d `present`; the capacity mechanism is
`higher_capacity_reduces_backlog`, and the overall source decision is
`recovery_effect_capacity_dependent`.

> These were internal component labels of the constrained-recovery experiment
> and are not additional dissertation hypotheses.

## 8. Capacity conditioning

Slower execution leaves more unresolved positions available for rebound to
rescue. Faster execution reduces backlog but closes that rescue window sooner.
Recovery and execution therefore interact. Experiment D does not reproduce a
general shared-capacity effect: its populations, shocks and treatment question
differ, several anchors do not bind, and its transmission result is mixed.

## 9. Behavioural scenario evidence

Stage 1-only below-peg-burden and restricted-mean-recovery-time contrasts are
exactly zero across the constrained recovery paths. The resilient scenario has
a negative below-peg-burden contrast at all three capacities, whereas the
central and fragile primary contrasts are zero. This demonstrates scenario
sensitivity without identifying, ranking or preferring a behavioural case.

## 10. Backlog-gate evidence

Unresolved positions are necessary for collateral rescue, execution speed
changes the rescue window, and collateral recovery reduces backlog. The
implemented behavioural route is also gated by unresolved tab, active bad debt
and price stability. The mechanism condition is therefore present. No
registered contrast cleanly isolates backlog or bad debt as the cause of a peg
recovery difference, so the causal peg effect remains unresolved.

## 11. Final A–E solvency–peg pattern

Experiment A records `solvency_improves_peg_unchanged`; B records
`solvency_deteriorates_peg_unchanged`; C records
`solvency_improves_peg_unchanged`; D records
`neither_materially_changes`; and E records
`solvency_deteriorates_peg_unchanged`. These decisions triangulate a separation
between operational solvency or timing changes and sustained peg recovery.
They are not counted as pooled observations.

## 12. S1 — recovery channel

`conditionally_operational`. Collateral rebound affects vault outcomes only
while unsafe positions remain unresolved. The unbounded null and constrained
rescue result are mechanistically compatible.

## 13. S2 — execution conditioning

`supported`, with generalisability `context_specific`. Rescue and backlog vary
materially across the constrained ETH capacities, while Experiment D supplies
weak or non-binding final multi-collateral capacity evidence.

## 14. S3 — behavioural stabilisation

`scenario_dependent_not_identified`. Active assumptions alter peg recovery in
registered recovery evidence, but effects differ and no behavioural vector is
empirically admissible.

## 15. S4 — backlog gate

`mechanism_present_peg_effect_unresolved`. The state gate is operational, but
its independent causal peg effect is not isolated.

## 16. S5 — solvency–peg decoupling

`strongly_supported`. The constrained study improves solvency without changing
Stage 1 peg outcomes, and at least three final experiments register material
operational changes with unchanged peg outcomes and no clear contradiction.

## 17. Overall H4 decision

`H4_recovery_conditionally_supported`. This is the unique outcome of the
registered hierarchy given S1–S5; it was not selected after reading formatted
conclusion text.

## 18. RQ3 answer

Collateral recovery can rescue unresolved vaults and reduce backlog, but the
channel disappears after liquidation closure. Execution capacity changes the
rescue window. Behavioural assumptions can alter peg recovery under transparent
scenarios, but are not empirically identified. Across the Stage 1-only final
programme, solvency and liquidation-timing changes generally remain distinct
from sustained DAI peg recovery.

## 19. Limitations

Source populations, shocks, seeds, confidence activation and treatment aims
differ. Persistent confidence is not identified; the backlog-to-peg effect is
not isolated; final bad-debt evidence is constrained by close-factor-one
accounting; and this synthesis makes no predictive-accuracy claim.

## 20. No-pooling boundary

No pooled mean, confidence interval, p-value, inverse-variance weight,
simulation-count weight or combined effect size is calculated. The method is
registered decision triangulation, mechanism compatibility and directional
claim mapping.

## 21. Reproducibility

The source registry contains 12 frozen source bundles. The synthesis identity
is `06f56e77ad56416483b2c010f0e63375b664baeff1830ec6306e37858c5920cb`
and its source-registry checksum is
`825640e51bbda151b73b2ec2ee43a07fe4bd08fd9b50337c49831f6045d5d98a`.
Six compact artefacts reconstruct byte-identically from tracked evidence.
Reconstruction executes zero simulations, reads zero checkpoints, makes zero
network calls and uses no held-out observations.

## 22. Next stage

Begin the pre-registered robustness layer and final validation sequence without
retuning the frozen model. Quiet, crypto-stress and USDC/SVB held-out
validation remain pending and evaluative only.
