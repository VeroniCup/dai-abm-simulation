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
`src/dai_sim/experiments/runner.py`; it is the historical stylised runner, not
the newly frozen final empirical-input design.

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

The pre-registered
[system-wide keeper execution calibration](docs/calibration/keeper_execution.md)
is complete. The shared hourly capacity and the current proportional
profit-hurdle interface are both partially identified; the pre-registered
mixed-versus-dominant composition comparison is underpowered and therefore
unresolved. A candidate-only registry and typed opt-in resolver exist, but no
ordinary runtime profile imports them and no established experiment has
changed. The dedicated integrated validation profile resolves them only when
selected explicitly.

The additive
[integrated empirical ETH-only profile](docs/validation/integrated_empirical_eth.md)
is also complete. Its 512 input initialisations and 128 independent
720-hour dynamic replications passed all ownership, numerical, accounting and
shared-capacity gates. The result is
`integrated_empirical_eth_profile_ready_with_caveats`: all vault and
market–gas moments passed, while the liquidation-arrival maximum-support
statistic and limited like-for-like output references remain explicit
caveats. The profile uses system-wide capacity 26, `direct_cost_only`,
Stage 1-only confidence and a transparent zero-delay oracle baseline. It is
experiment-ready but not runtime adopted.

The pre-registered
[constrained-liquidation ETH recovery experiment](docs/experiments/constrained_eth_recovery.md)
is complete: 24 cells × 128 replications produced 3,072 valid simulations
with common random numbers and no numerical failures. Low and central
system-wide capacities were operational. Full-week recovery avoided mean
liquidation debt of 7,214, 5,579 and 5,238 DAI at capacities 14, 26 and 45,
and lowered backlog area at every capacity. Primary Stage 1-only peg outcomes
did not change. H5a is supported, H5b is not supported, H5c and H5d are
present, and the overall classification is
`recovery_effect_capacity_dependent`. No capacity or confidence scenario was
selected and no runtime default changed.

The
[final multi-collateral input freeze and integration
validation](docs/validation/multicollateral_integration.md) is complete. The
final collateral universe is ETH and WBTC with empirical owners plus an
explicitly counterfactual stable proxy. Its registry fixes five portfolios,
seven result-blind shocks, 500 vaults, 2.5 million DAI and common initial
system collateralisation of 3.6089387701260205. All 1,280 initialisations, 160
ordinary 168-hour replications and six shared-capacity smokes passed. The
central system-wide cap remains 26, and simultaneous three-family demand
selected 26 opportunities in total rather than 26 per family. The overall
classification is `final_multicollateral_inputs_ready_with_caveats`.
The profile is experiment-ready, opt-in and not runtime adopted. No portfolio
or shock was ranked or selected.

The first final-programme study,
[Experiment A — idiosyncratic diversification](docs/experiments/final/idiosyncratic_diversification.md),
is complete from its original 128 authoritative checkpoints and 1,024
simulations; no replication was rerun during evidence reconstruction. A
post-execution NumPy JSON scalar correction is classified
`evidence_serialization_infrastructure` and changed neither the scientific
calculations nor the registered decisions. A1 is `supported`, A2 is
`exposure_gradient_consistent`, A3 is `shock_localisation_valid`, and the
overall result is `H3_idiosyncratic_diversification_supported`. Solvency
improves for the qualifying diversified portfolios while the registered peg
outcomes remain unchanged. No portfolio, shock or runtime configuration was
ranked, selected or adopted.

The second final-programme study,
[Experiment B — correlated stress](docs/experiments/final/correlated_stress.md),
is complete from 128 authoritative checkpoints and 1,024 simulations under
experiment identity
`e02c035162f8178c96d2cae71d0a581ce813ab33526854bd5810e8e2810ead83`.
B1 is `supported`, B2 is `correlation_deterioration_present`, B3 is
`transmission_mixed`, and the overall result is
`H3_correlation_deterioration_supported`. All three diversified portfolios
are descriptively `weakens_but_remains`; none reverses. The registered
peg–solvency relationship is `solvency_deteriorates_peg_unchanged`. B2
compares two frozen bundles whose severity, recovery and gas ownership also
differ, so it is not a ceteris-paribus causal correlation estimate. Experiment
A remains unchanged, no portfolio or shock was selected, and no runtime
configuration was adopted.

The third final-programme study,
[Experiment C — stable-collateral trade-off](docs/experiments/final/stable_collateral_tradeoff.md),
is complete from 128 authoritative checkpoints and 1,536 simulations under
experiment identity
`cb6d00877c54011cc49714bdfe23fad83140fef001568ea9b43d355811c9129b`.
C1 is `supported`, C2 is `depeg_exposure_gradient_inconsistent`, C3 is
`contagion_mixed`, and the overall result is
`H3_stable_tradeoff_partially_supported`. Both stable-backed portfolios are
descriptively `protection_without_material_depeg_cost`, without ranking or
selection. The registered peg–solvency relationship is
`solvency_improves_peg_unchanged`. STABLE remains a counterfactual proxy; its
depeg paths are scenario-defined, and no USDC/SVB or held-out evidence was
used. Experiments A and B remain unchanged and no runtime default was
adopted.

The fourth final-programme study,
[Experiment D — shared keeper capacity](docs/experiments/final/shared_keeper_capacity.md),
is complete from 128 authoritative checkpoints and 1,152 simulations under
experiment identity
`b324c31be7ef6dd7f61e504709b2086b0e88ce181c177f25dcaad182095c17e3`.
D1 is `not_supported`, D2 is `shared_capacity_transmission_mixed`, D3 is
`peg_unchanged`, and the overall result is
`H1_no_clear_shared_capacity_effect`. The empirical-crypto anchor has a
small threshold backlog-area effect; the stable-supported effect is
uncertain, and stable-heavy capacity does not bind. The registered
peg–solvency relationship is `neither_materially_changes`. Realised bad-debt
metrics remain degenerate under close-factor-one accounting. Capacities 14,
26 and 45 remain partially identified sensitivity coordinates: no capacity
was ranked, selected or runtime adopted. Experiments A–C remain unchanged,
and Experiment E did not rerun them.

The result-blind
[oracle-delay freeze](docs/calibration/oracle_delay.md) is complete under
registry identity
`2e562ef2618e472ce3b0551addf2596ddbe137910fa6d2ad5884ae71c674e46d`.
The repository contains no eligible oracle observation or update-interval
series and no tracked effective numerical delay rule, so the freeze is
classified `transparent_sensitivity_not_empirically_identified`. The existing
Experiment E identifiers resolve externally to 0, 1 and 2 hourly simulation
steps. These are result-blind mechanism sensitivities, not estimates of
historical Maker oracle latency. The readiness classification is
`experiment_e_ready_with_transparent_delay_sensitivity`.

The fifth final-programme study,
[Experiment E — oracle delay](docs/experiments/final/oracle_delay.md), is
complete from 128 authoritative checkpoints and 768 simulations under
experiment identity
`67ec5a1e03492608c7f847861f7dbd506d2a526dbf4107298241b26c855eb0f8`.
E1 is `supported`, E2 is `partially_supported`, E3 is `peg_unchanged`, and
the overall result is `H2_oracle_delay_partially_supported`. Mismatch and
recognition lag grow at both anchors, while downstream liquidation effects
are modest and peg outcomes are unchanged. The peg–solvency relationship is
`solvency_deteriorates_peg_unchanged`; bad-debt metrics remain degenerate
under close-factor-one accounting. No delay was selected, no held-out or
USDC/SVB data were used, and the production zero-delay default remains
unchanged. Experiments A–D remain byte-identical.

The registered
[H4 recovery and behavioural-stabilisation evidence synthesis](docs/experiments/final/recovery_behaviour_synthesis.md)
is complete under synthesis identity
`06f56e77ad56416483b2c010f0e63375b664baeff1830ec6306e37858c5920cb`.
Its decisions are S1 `conditionally_operational`, S2 `supported` with the
`context_specific` qualifier, S3 `scenario_dependent_not_identified`, S4
`mechanism_present_peg_effect_unresolved` and S5 `strongly_supported`, giving
`H4_recovery_conditionally_supported`. Collateral rebound can rescue vaults
only while positions remain unresolved; execution conditions alter that
window; and registered solvency or timing changes repeatedly coexist with
unchanged peg outcomes. No simulation or checkpoint was used, no confidence
scenario was ranked or selected, no held-out or USDC/SVB evidence entered,
and production remains Stage 1-only.

The pre-registered
[selected robustness layer](docs/experiments/final/selected_robustness.md) is
complete under robustness identity
`59474cbc9e37d7df5d49fb5b9a0abbf4670ce300799f82ccb0ec21ed8a3aebbf`.
Its 56 cells and 64 paired replications per cell produced 3,584 valid
simulations. R-A, R-B, R-C and R-D are each `robust`; all six non-baseline
settings retained the inherited conclusion and no clear two-metric reversal
occurred. The overall classification is `core_conclusions_robust`. Population,
market-block, positive-hurdle and metric-only recovery sensitivities qualify
generalisability without selecting or adopting a treatment.

The frozen-model
[final held-out validation](docs/validation/final_validation.md) is complete
under freeze identity
`1bc40998534dd3842a229c701743494147d24832d956622411afba7863d3c295` and
validation identity
`a5e281a810892454539f0528c30536696d01c664bbd6cceda17584b88d5f3ed2`.
No distinct quiet window was separately registered, so November 2022 is
counted once as the generalisation/FTX holdout. Its 128 simulations are
`ftx_validation_directionally_consistent`. The final 256-simulation USDC/SVB
stage passed its zero-STABLE negative control but is
`usdc_svb_stable_channel_underactive`. The technically valid overall result
is `final_validation_mixed`. The no-retuning record confirms zero model,
parameter, scenario, metric-rule or production-adoption changes.

The separate
[experiment-infrastructure maintenance](docs/validation/experiment_infrastructure_maintenance.md)
is complete. The convenience reconstruction CLI now respects the keyword-only
API, and semantic profile resolution no longer materialises a shared
temporary file during parallel worker startup. One hundred profile
resolutions across four spawned workers completed deterministically. No
experiment result, compact-evidence checksum, checkpoint, profile, seed,
parameter or production default changed, and no substantive simulation ran.

The pre-final
[project-structure visualisation](docs/overview/project_structure.md) and
[architecture audit](docs/overview/project_structure_audit.md) are complete.
The follow-up
[scientific package taxonomy](docs/overview/scientific_package_taxonomy.md)
separates calibration, validation, scenario resolution, controlled mechanism
experiments and the reserved final programme. The two ETH recovery studies,
their workflows and tests now sit under `experiments/mechanism/`; confidence
scenario responsibilities are split between `inputs/` and `validation/`; and
`experiments/final/` is the one destination for the next implementation pass.
Path-hashed validator implementations remain documented historical
exceptions. The exact classification is
`scientific_package_taxonomy_ready_with_protected_exceptions`. No provenance,
runtime input, profile, registry, parameter, scientific identity, output or
production default changed.

Detailed current guidance:

- [Empirical framework](empirical.md)
- [Parameter methodology](parameters.md)
- [Calibration documentation](docs/calibration/README.md)
- [Historical acquisition plan](docs/archive/historical_plans/DATA_ACQUISITION_PLAN.md)

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
additions. The current multi-collateral integration pass collects 997 tests
and completes with 996 passing and one documented skip; runtime inputs, smoke
checks and Experiments 1–5 retain their frozen integrity evidence.

Repository restructuring is closed. The current architecture and
reproducibility boundary are recorded in the
[repository guide](docs/overview/repository_guide.md) and
[regression guide](docs/validation/regression.md). The historical baseline
remains unchanged under `docs/repository_restructuring_baseline.md`.

## Regression status

The frozen smoke and Experiments 1–5 checksums are recorded in
[the regression guide](docs/validation/regression.md) and the
[Stage 1 baseline](docs/repository_restructuring_baseline.md). The Stage 12
review reproduced all of them without changing executable behaviour.

## Known limitations

- The simulator is not a full Maker auction engine.
- Stable collateral has no direct confidence or DAI-demand transmission
  channel, and its final vault and protocol owners are counterfactual.
- One oracle delay applies to all collateral paths.
- Behavioural confidence parameters remain incompletely identified.
- Representative vault windows do not identify unconditional event
  probabilities.
- Current results use a limited seed design and are preliminary dissertation
  evidence rather than final conclusions.

## Next research work

Experiments A–E, the result-independent oracle-delay freeze, the registered H4
synthesis, selected robustness and final held-out validation are complete.
The five-experiment core programme plus RQ3/H4 evidence integration is
complete. The next stage is to produce the final dissertation tables, figures,
result registry and validation summary, then perform the final repository and
code freeze.
The stable-impairment component of H3 is complete with partial support, while
Experiment D provides mixed secondary shared-capacity transmission evidence.
Population-scale robustness and held-out final validation, including
USDC/SVB, are now complete. The five portfolios and
seven shocks are frozen inputs, not result-based selections. Keeper candidates
and both integrated profiles remain opt-in evidence rather than adopted
defaults.

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
