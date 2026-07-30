# Project status

## Current implementation

The simplified DAI model supports:

- ETH, BTC and stable collateral classes with one collateral type per vault;
- collateral-specific market and oracle paths;
- heterogeneous vault populations and target debt-share portfolios;
- collateral-specific liquidation ratios, penalties and close factors;
- profitability-gated liquidations under shared keeper capacity;
- gas costs, bad debt, confidence regimes, panic pressure and peg recovery;
- system-level and long-format collateral-level results.

Experiments 1–5 remain established ETH-only baselines. The multi-collateral
portfolio and shock experiment is implemented in
`src/dai_sim/experiments/runner.py`.

## Empirical inputs and calibration

Continuous market, gas, liquidation and protocol evidence has been acquired
and validated. Vault evidence uses representative ordinary and stress windows
rather than an exhaustive historical mutation census. Quiet-mature, USDC/SVB
and Terra/CeFi windows are complete, and the earlier continuous-acquisition
chunks remain preserved as methodology validation.

The repository contains reviewed candidates for market, gas, protocol, vault
and liquidation inputs. The opt-in empirical profile now supports:

- joint representative vault initialisation;
- empirical market-return blocks;
- component gas inputs;
- empirical liquidation-arrival demand separated from keeper throughput.

Legacy initialisation, market, gas and liquidation-demand behaviour remain the
defaults. Candidate estimation does not itself adopt values or authorise new
mechanics.

Detailed current guidance:

- [Empirical framework](empirical.md)
- [Parameter methodology](parameters.md)
- [Calibration documentation](docs/calibration/README.md)
- [Historical empirical reports](docs/archive/README.md)

## Repository restructuring

The domain-first repository structure is now authoritative. Completed
structural stages:

1. pre-migration baseline;
2. package and path infrastructure;
3. semantic source package;
4. semantic profiles and runtime inputs;
5. domain-first data and provenance;
6. domain workflows;
7. domain SQL hierarchy;
8. documentation consolidation;
9. semantic test hierarchy;
10. semantic output hierarchy;
11. removal of temporary compatibility interfaces;
12. final review and closure.

The bounded post-Stage-11 semantic-output correction and tracked-clone
self-containment correction are also complete. Temporary compatibility
interfaces have been removed. The Stage 12 working and tracked-only checkouts
each passed the then-current 491-test suite. The pre-infrastructure working
suite contained 501 passing tests after the historical confidence-evidence
additions. The behavioural-confidence infrastructure raises the current suite
to 536 passing tests through substantive model, calibration, workflow and
evidence tests; runtime inputs, smoke checks and Experiments 1–5 retain their
frozen integrity evidence.

Repository restructuring is closed. The
[final restructuring review](docs/validation/repository_restructuring.md)
records the architecture, 13-commit migration sequence, reproducibility
boundary and remaining limitations. The historical baseline remains unchanged
under `docs/repository_restructuring_baseline.md`.

## Regression status

The frozen smoke and Experiments 1–5 checksums are recorded in
[the regression guide](docs/validation/regression.md) and the
[Stage 1 baseline](docs/repository_restructuring_baseline.md). The Stage 12
review reproduced all of them without changing executable behaviour.

## Known limitations

- The simulator is not a full Maker auction engine.
- Stable collateral has no direct confidence or DAI-demand transmission
  channel.
- One oracle delay applies to all collateral paths.
- Behavioural confidence parameters remain incompletely identified.
- Representative vault windows do not identify unconditional event
  probabilities.
- Current results use a limited seed design and are preliminary dissertation
  evidence rather than final conclusions.

## Next research work

The behavioural-confidence calibration planning pass has resolved four core
specification choices in the [confidence and behavioural calibration
plan](docs/calibration/confidence_and_behaviour.md): sustained price recovery
uses the \(\pm0.5\%\) band for 24 consecutive hours; primary collateral stress
is lagged 24-hour ETH downside; liquidation-system pressure is measured by the
lagged backlog-to-clearance ratio and retained as a sensitivity/recovery gate;
and the new behavioural DAI response uses directly estimated effective
coefficients after scale normalisation.

These are pre-registered estimation choices, not adopted behavioural values.
The [confidence estimation design](docs/calibration/confidence_estimation.md)
preserves the binary audit: it fixes material downside at \(p<0.995\), defines
the six-hour persistence outcome, selects the tab-based backlog-to-clearance
measure after its reconstruction gate passes, and records the planned binary
logistic protocol that proved infeasible.

The binary persistence design is complete and non-estimable: its fixed
calibration sample contains 27 origins across 24 episodes, zero positive
outcomes, and no tab-pressure variation. No coefficient was fitted.

The [confidence evidence
redesign](docs/calibration/confidence_evidence_redesign.md) retains the 0.995
material threshold and six-hour horizon, but uses a continuous future downside
burden on a deterministic 00:00/06:00/12:00/18:00 UTC grid. Design A supplies
4,167 calibration origins, but only 47 have positive burden, 9 reach burden
0.10, all burden occurs in 2021, and both market predictors have zero MAD.
Design B adds Terra/CeFi hours but no burden and fails the same gates.
USDC/SVB remains an adequate untouched downside evaluation.

Tab pressure continues to pass its reconstruction gate but is positive at only
one calibration origin, in one month and one independent backlog episode, with
zero coincident burden. It is therefore fixed as a sensitivity predictor and
possible confidence-recovery gate, not a primary estimator input.

The pre-registered [Design C historical market
extension](docs/calibration/confidence_historical_market_evidence.md) is now
acquired and adopted. It supplies 39,456 complete DAI/ETH hours from 31
December 2019 through 30 June 2024 using the same Dune `prices.hour` and
CoinPaprika methodology as the existing panel. Both sparse positive-Q95
predictor transformations pass their declared gates, and USDC/SVB remains
untouched validation evidence.

Design C is nevertheless not eligible for fitting. It has 321 non-zero
calibration origins and 74 contributing episodes, but one December 2020–
January 2021 episode contributes 56.55% of total burden against the fixed 25%
ceiling. The final evidence-extension stop rule therefore closes the
predictive stress-proxy regression route permanently. No coefficient was
fitted.

The [constrained simulated-moments
specification](docs/calibration/confidence_simulated_moments.md) and its first
bounded infrastructure pass are complete.
It fixes equal weights on scaled lagged peg-gap and ETH-downside stress,
separates direct estimation of \(\kappa_-\), \(\kappa_+\) and residual
innovations from the Stage 2 vector
\((\alpha_d,\alpha_r,C_{\min},\kappa_P)\), and selects eight core moments in
four equally weighted groups. All selected moments pass the declared
event-count, non-zero-scale and event-concentration feasibility gates. The
catalogue contains 74 calibration events, all beginning in 2020–21, plus one
untouched USDC/SVB final-stress event. This temporal concentration is retained
as an identification and validation risk.

The fixed ordinary sample reproduces 1,189 daily observations: 172 below the
peg and 1,017 above it. Joint bounded least squares gives candidate effective
responses \(\widehat\kappa_-=0.1993809753\) and
\(\widehat\kappa_+=0.1051311602\). Both coefficient gates and the run-bounded
24-hour residual-block gates pass, so Stage 1 is accepted as a fixed input to
the completed global search and any separately authorised continuation. The
pure persistent-confidence and coefficient-normalised market interfaces have
no production caller, and no runtime profile adopts them.

Bad debt is classified as a recovery-gate mechanism only. Policy feedback is
a literature-informed sensitivity, and the current optional recovery equation
is retained only as a legacy ablation. The SMM design includes explicit
bounds, common-random-number replication, Sobol search, nested boundary
models, Jacobian diagnostics, event bootstrap, leave-one-event-out checks and
quiet/final blocked validation. The transformations, objective, deterministic
seed registry, 32-event subset and 256-point Sobol design are implemented and
the fixed 262,144-run search is complete. All 256 candidates pass structural
and objective validity, 53 pass the numerical-bound gate, and none passes the
fixed all-moment MCSE gate at 32 replications. The deterministic top-16 rule
therefore selects no candidate. The pass is classified as **Sobol search
completed but insufficient valid candidates**; the all-event follow-up,
Powell, registry B, final validation, a final Stage 2 estimate and behavioural
runtime integration have not begun.

The subsequent [Monte Carlo precision and recovery-censoring
diagnosis](docs/calibration/confidence_precision_diagnosis.md) verifies that
the existing MCSE estimator is the correct conditional hierarchical
estimator. An objective-blind 16-candidate ladder has regular convergence and
improves materially when all 74 calibration events are used, but most
projected requirements exceed 2,048 replications. Only three of 15,603
792-hour censored runs recover when the same paths are extended. The registered
recovery moment is therefore **not operationally identifiable** under the
fixed design. No candidate is selected; a future pass must pre-register any
simplification or replacement before rerunning a search.

The pre-registered
[recovery-moment redesign](docs/calibration/confidence_recovery_moment.md)
tests a 48-hour recovery-probability contrast and a 168-hour restricted-mean
contrast using the fixed 74-event quartiles and objective-blind 16-candidate
ladder. Candidate A fails its empirical support gate; Candidate B fails its
empirical support and simulation-precision gates. The result is
**conditional recovery moment unsupported**. The canonical SMM evidence is
unchanged, no candidate is selected and no new search is authorised. The next
boundary is an objective-simplification and identification review.

The dormant [conditional event simulation](docs/calibration/confidence_event_simulation.md)
is also implemented. It uses a standardised 500-vault, 2.5 million DAI
ETH-core state, observed ETH paths, registered Stage 1 residual blocks and
explicit zero-backlog/material-active-bad-debt recovery gates. Four
content-hashed calibration smoke events and deterministic Sobol/boundary
interface probes validate the mechanism, and the bounded eight-run workload
benchmark is recorded. This is conditional rather than exact historical
replay. The fixed subset candidates have now been ranked but no valid top 16
exists, no Stage 2 parameter has been fitted or adopted, and the final
USDC/SVB event remains unsimulated.

The remaining empirical work is adoption and validation of defensible
parameter candidates, followed by calibrated counterfactual experiments.
Changes to auction execution, confidence mechanics, stable-depeg transmission
or keeper-capacity allocation require separate modelling decisions and
authorisation.

The subsequent [objective-simplification and numerical-identification
gate](docs/calibration/confidence_objective_identification.md) defines seven
reported moments, including two zero-weight Stage 1 preservation constraints,
and a proposed five-moment Stage 2 objective with weight 0.20 per active
moment. At 256 replications, active-moment MCSE pass counts are 10/16, 3/16,
8/16, 16/16 and 10/16. Four moments therefore fail the fixed operationality
gate. The result is **seven-moment specification not operational**. No
anchors, Jacobians, parameter profiles, restricted model, new search or
Stage 2 estimate were evaluated, and production behaviour remains unchanged.

The authorised methodological continuation is a
[finite-grid partial-identification analysis](docs/calibration/confidence_partial_identification.md).
It reuses the fixed 256-vector Sobol domain and all-event registry-A cache,
classifies vectors by inner and outer empirical compatibility, and constructs
objective-blind representatives solely for later robustness experiments. It
does not calculate a scalar objective, estimate or rank a Stage 2 vector, use
final-validation evidence, or alter production behaviour.

The completed 256-vector pass retains no inner or outer candidate and rejects
all 256 vectors. Its pre-registered classification is **model–evidence
incompatibility**. All structural and Stage 1 gates pass; the incompatibility
arises from the five empirical compatibility constraints, with 203 candidates
also failing the numerical-bound gate. No representative vector exists. The
next authorised boundary is a review of structural assumptions or empirical
support-band design, not point fitting, ranking or runtime adoption.

That review is implemented as the
[persistent-confidence structural incompatibility
diagnosis](docs/calibration/confidence_structural_incompatibility.md). It
decomposes the five fixed compatibility failures and runs an objective-blind
16-candidate panel of one-factor vault-state, capacity, residual, stress and
recovery-gate interventions using paired registry-A streams. Historical hourly
gas is recorded as unavailable for the pre-June-2021 event hours rather than
invented. The pass neither changes the empirical bands or parameter domain nor
selects a candidate, structural model or runtime configuration. The completed
diagnosis is **multiple structural families contribute**: the lower-SCR vault
state, zero-residual mechanism diagnostic and removal of the unresolved-backlog
gate each partially explain downside and recovery mismatches, but no variant
resolves a constraint.

The resulting [objective-blind structural
factorial](docs/calibration/confidence_structural_factorial.md) is complete.
Its fixed MCSE gate initially failed at 64 replications for three candidates;
an estimator-ownership audit found no formula error, and the pre-registered
uniform extension to 128 replications brought every moment–effect combination
to at least 15/16 agreement without changing the threshold. No cell has an
inner- or outer-compatible candidate and no empirical constraint is resolved.
The final classification is **factorial interactions reveal trade-offs**:
there are no synergistic interactions, while materially mixed and
antagonistic interactions remain. The calibration-rescue programme for the
present confidence formulation therefore ends. No candidate, cell, parameter
or structural model is selected, and production behaviour remains unchanged.

The transparent
[persistent-confidence scenario registry](docs/experiments/confidence_scenarios.md)
is pre-registered as the methodological continuation. It contains the
unchanged Stage 1-only default plus three explicitly activated quartile
bundles reconstructed from the original coupled Stage 2 transform. The second
canonical coordinate is relative recovery
\(\rho_r=\alpha_r/\alpha_d\); consequently raw recovery is 0.25 for the
central bundle and 0.1875 for both resilient and fragile bundles. No scenario
is calibrated, ranked, selected or adopted by a runtime profile.

The first separately authorised continuation is the
[ETH-only peg-recovery matrix](docs/experiments/eth_recovery_matrix.md). It
fixes the 2,000-to-1,140 severe shock, four smoothstep recovery paths, the four
registered confidence cases, 128 paired replications per cell and censored
24-hour sustained-recovery estimands. Detailed checkpoints remain ignored and
compact decision evidence is registered under
`data/provenance/experiments/recovery/`. This experiment does not reopen
calibration or alter the Stage 1-only production default. Multi-collateral
execution remains a separate future authorisation.

The complete 2,048-run matrix is valid and classified as **no clear recovery
path effect**. All registered ETH path contrasts are zero under the fixed
ordinary-capacity baseline because virtually all vaults liquidate at the
common trough and no unresolved tab or material bad debt remains for later
collateral recovery to resolve. The fixed confidence bundles produce large
peg-persistence differences, but no bundle is ranked, selected or adopted.
H4a and H4b are not supported and no material H4c interaction is present.
