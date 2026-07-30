# Persistent-confidence structural incompatibility

## 1. Purpose and boundary

This pass diagnoses why the dormant persistent-confidence conditional event
experiment cannot reproduce the five registered empirical support bands over
the fixed behavioural domain. It follows the completed finite-grid
partial-identification result, which retained no inner- or outer-admissible
vector. The diagnosis changes one experiment assumption family at a time; it
does not estimate a parameter, rank a candidate, choose a structural model or
alter production behaviour.

The empirical bands, empirical scales, natural-support clipping and 90% Monte
Carlo interval rule remain exactly as registered. Registry A, all 74
calibration events, 64 replications and the objective-blind 16-candidate panel
are fixed. The USDC/SVB event remains untouched final-validation evidence.

## 2. Committed model–evidence incompatibility

The source partial-identification identity is
`39d01a3dfa07053dbe31c8189d88ab5f5fdfaa8003d3ddb28606179fd8413e6d`.
It contains 256 Sobol vectors and 1,212,416 event-replication evaluations. It
retains zero inner and zero outer candidates and rejects all 256. All
structural and Stage 1 preservation gates pass; 203 candidates additionally
fail the fixed numerical DAI-bound gate.

No candidate from that analysis is re-evaluated merely to reconstruct the
baseline. Candidate summaries provide the all-grid decomposition, and the
preserved 16-candidate, 64-replication ladder provides paired baseline
realisations for structural interventions.

## 3. Baseline mismatch directions

The fixed classification rules give:

- first-six-hour burden: mixed location mismatch (70 intervals below, 15
  overlapping and 171 above);
- maximum downside deviation: no systematic location mismatch under the
  90%/25% rules (51 below, one overlapping and 204 above);
- recovery-completion hours: systematically above the empirical band (all
  256 intervals);
- failed recovery attempts: systematically below (247 intervals below and
  nine overlapping);
- initial-gap Q4–Q1 burden contrast: systematically below (all 256 intervals).

These counts describe distinct failures and are not summed into a score.
Candidate-specific signed gaps retain their direction: negative is below the
band, zero is inside it and positive is above it.

## 4. Hard-gate decomposition

The numerical-bound failure count reproduces at 203. Structural failures and
Stage 1 preservation failures remain zero. The audit reports failures by each
parameter quartile, right-censoring quartile, active-bad-debt occurrence,
unresolved-backlog occurrence and moment mismatch direction. The fixed
concentration rule classifies the numerical failures as broadly distributed;
the DAI price bounds are not changed.

## 5. Parameter-boundary trends

For each of four transformed behavioural coordinates and five moments, the
audit compares the lowest and highest deciles, reports the difference in
empirical-scale units, calculates Spearman rank correlation and checks the
direction of adjacent-bin movement. A signal requires at least a half-scale
extreme-decile difference, 75% aligned adjacent-bin changes and movement
towards the empirical band.

The registered rule identifies a possible low-boundary signal for the panic
response: first-six-hour burden, maximum downside deviation and
recovery-completion hours move towards their bands at the low boundary without
the prohibited pattern of large worsening elsewhere. This is a diagnostic
domain-truncation signal, not authority to amend or extrapolate the parameter
domain.

## 6. Structural variant principles

Every intervention changes exactly one of six families:

1. initial vault state;
2. liquidation capacity;
3. gas treatment;
4. residual innovation process;
5. observable-stress weights;
6. recovery gates.

All other registered assumptions remain fixed. Variants are diagnostic
interventions, not candidate runtime profiles. No variants are combined and no
result is used to rank the panel.

## 7. Vault-state diagnosis

The reviewed representative-regime snapshots support two objective-blind
historical states. Eligible snapshots contain active indebted ETH vaults with
complete debt, collateral-ratio and liquidation-ratio ownership. The
calibration-period debt-weighted system-collateral-ratio percentile selects:

- the snapshot nearest the 25th percentile, with earliest-timestamp tie-break;
- the snapshot nearest the median, under the same rule.

For each event and replication, 500 vaults are sampled with the existing
registry-A vault stream. Sampled relative debt weights are retained and total
debt is normalised to 2.5 million DAI. Event-start collateral quantities are
derived only from the pre-roll ETH price. No collateral ratio is scaled
arbitrarily and no event outcome enters snapshot selection.

The lower-SCR (`p25`) state materially moves maximum downside deviation and
recovery-completion hours towards their empirical bands, but resolves neither
constraint. The median-SCR state has no material effect. The family therefore
has a **partial explanatory signal**: initial collateralisation helps explain
part of two mismatches, but not the five-constraint incompatibility.

## 8. Liquidation-capacity and gas diagnosis

The capacity interventions impose ceilings of 20, 10 and five successful
liquidations per hourly step. The fixed 100 DAI gas cost, profitability rule,
penalty, full close factor and demand stream remain unchanged. An uncapped
package is reused only when its attempt count proves the ceiling cannot bind;
otherwise the canonical calibration liquidation path is recomputed.

Historical hourly gas is not executed. The calibration catalogue begins in
January 2020, whereas validated hourly gas ownership begins in June 2021.
Complete causal event-hour gas ownership is therefore unavailable and no
pre-coverage path, interpolation or result-selected event average is invented.

Capacity ceilings of 20, 10 and five have no material effect on any registered
moment and resolve no constraint. The capacity family has **no explanatory
signal** under this conditional experiment. Gas remains **unavailable**, so
the diagnosis does not generalise the capacity result to historical gas costs.

## 9. Residual-process diagnosis

`residual_zero` removes innovations as a mechanism-only diagnostic.
`residual_iid_empirical` samples individual values from the accepted centred
Stage 1 residual sequence using the existing registry-A market stream. It
preserves the empirical marginal source and removes only serial block
preservation. The primary experiment continues to use 24-hour moving blocks;
Stage 1 is not refitted.

Zero innovations materially improve maximum downside deviation and
recovery-completion hours but resolve neither constraint. IID empirical
innovations meet no material-improvement rule; their median changes worsen
burden, downside and recovery by more than one empirical scale, but the variant
does not meet the pre-registered `tradeoff` class because it first resolves or
materially improves no constraint. The residual family has a **partial
explanatory signal**, attributable to the mechanism-only zero-residual
intervention rather than to an alternative empirical residual model.

## 10. Stress-construction diagnosis

The ETH-dominant intervention uses peg/ETH weights 0.25/0.75. The peg-dominant
intervention uses 0.75/0.25. Scaling functions, lag ownership and confidence
equations remain fixed. These registered sensitivities are not fitted
weights.

Neither weight sensitivity satisfies the material-effect rule or resolves a
constraint. Observable-stress construction therefore has **no explanatory
signal** within the two registered one-factor weight changes.

## 11. Recovery-gate diagnosis

Three pure ablations retain the fixed 24-hour stability duration and
0.995–1.005 recovery band:

- backlog-only ignores active bad debt;
- bad-debt-only ignores unresolved backlog;
- price-only ignores both liquidation-state blockers.

The underlying liquidation, backlog and bad-debt paths remain present for
diagnostics. An ignored gate condition is not recoded as an altered economic
state.

Ignoring active bad debt alone (`gate_backlog_only`) has no material effect.
Ignoring backlog while retaining the bad-debt gate
(`gate_bad_debt_only`) materially improves downside and recovery, and the
price-only result is identical under the registered summaries. Thus the
gate-family signal is owned by the unresolved-backlog blocker; additionally
removing the active-bad-debt blocker contributes no measured incremental
effect. Neither variant resolves a constraint, so the family has a **partial
explanatory signal**.

## 12. Paired common-random-number design

Each source-backed variant uses the same candidate, event, replication and
registry-A stream identities as its preserved baseline. For each
candidate–variant–moment combination, the evidence reports the paired shift,
analytic hierarchical paired MCSE, signal-to-noise ratio, empirical-scale
shift, baseline and variant signed gaps, outer-pass states, numerical gate
states, censoring change and liquidation-state occurrence changes.

Candidate-invariant structural paths are computed once per event and
replication and shared across the fixed panel. Atomic event shards and
variant-candidate checkpoints support safe resume without duplicating the
18,944-package all-event cache.

## 13. Material-effect and resolution rules

A moment has a material directional effect only when at least 12 of 16
candidates move towards its band, at least eight have a shift of at least
0.5 empirical scales with paired SNR of at least two, and the median absolute
gap falls by at least 0.5 scales.

A constraint is diagnostically resolved only when at least 12 candidates
outer-pass, structural and Stage 1 gates remain valid, and the numerical-valid
count declines by no more than four relative to the panel baseline. These
rules are applied mechanically and produce no aggregate multi-moment score.

## 14. Family-level findings

The fixed classifications are:

- vault state: `partial_explanatory_signal`;
- liquidation capacity: `no_explanatory_signal`;
- gas treatment: `unavailable`;
- residual process: `partial_explanatory_signal`;
- stress construction: `no_explanatory_signal`;
- recovery gates: `partial_explanatory_signal`.

The material effects in the three partial families all concern downside and
recovery. No variant resolves any of the five constraints, and no variant or
family is preferred or adopted.

## 15. Overall structural diagnosis

The overall classification is
`multiple_structural_families_contribute`. Lower historical
collateralisation, zero residual innovations and removal of the backlog gate
provide complementary partial signals, while none is sufficient. A separate
possible low-bound panic-response signal remains recorded, but the overall
hierarchy gives priority to the observed contribution of multiple structural
families. The machine-readable decision in
`data/provenance/calibration/confidence/structural_incompatibility_decision.json`
is authoritative.

## 16. Authorised next boundary

The authorised continuation was the separately pre-registered
[objective-blind structural factorial](confidence_structural_factorial.md).
It combined only the three partial-signal families and preserved every
one-factor result. The completed factorial found no compatible cell and no
resolved constraint, so the calibration-rescue programme for the present
confidence formulation now ends. Neither pass authorises runtime adoption.

## 17. Limitations

The historical vault snapshots cover three representative regimes rather than
the full 2020–21 event catalogue. They diagnose initial cross-sectional state
sensitivity but are not historical event replays. Hourly gas coverage is
incomplete for the catalogue. Structural variants remain conditional on the
observed ETH paths, one initial DAI observation, registered moment definitions
and the simplified vault and liquidation representation.

## 18. Production and final-validation boundaries

Persistent confidence remains dormant. No runtime profile, sensitivity or
experiment definition changes. No final-validation event is simulated. The
analysis does not change empirical bands, parameter bounds, Stage 1 evidence,
recovery definitions, numerical price bounds or production mechanics.

## 19. Storage and reproducibility

Compact evidence is tracked under
`data/provenance/calibration/confidence/`. Generated event shards,
variant-candidate checkpoints, co-failure tables and timing records remain
ignored under
`outputs/diagnostics/calibration/confidence/structural_incompatibility/`.
The run requires at least 10 GiB free, caps new ignored storage at 750 MiB,
stores no trajectories or pickle files and records all deterministic
checksums in the calibration manifest.
