# FINAL.md

# Final Empirical, Validation and Experiment Roadmap

## Purpose

This file is the end-stage control document for the DAI multi-collateral dissertation project.

It records:

- what has already been completed and must remain frozen;
- the empirical and validation work still required;
- the correct sequence of the remaining implementation and experiment passes;
- the decision boundaries for parameters that may not be fully identified;
- the minimum evidence required before moving to the next stage;
- items that can remain transparent limitations rather than becoming new mechanisms;
- the final code, evidence, validation and dissertation freeze procedure.

The file should be checked after every remaining pass and updated when a stage
has been completed and validated; its Git commit status is recorded
separately.

The project must not move directly from the completed unbounded-capacity ETH-recovery experiment to final multi-collateral simulations. Keeper execution must first be empirically constrained and then integrated into the principal empirical model.

## End-stage completion checklist

Completed in the current end-stage pass:

- keeper capacity frontier: completed with a partially identified shared range;
- keeper profit-hurdle decision: completed at the successful-execution evidence level;
- keeper scenario registry: completed as candidate-only, opt-in evidence.
- integrated empirical ETH-only profile: completed and experiment-ready with caveats;
- integrated input and dynamic distributional validation: completed.
- constrained-liquidation recovery experiment: completed and operational;
- qualitative comparison with the unbounded-capacity null: completed;
- final ETH/WBTC plus counterfactual-stable collateral set: frozen;
- final protocol, five-portfolio and seven-shock registries: frozen; and
- shared-capacity multi-collateral integration validation: completed with
  caveats; and
- project-structure visualisation, architecture audit and scientific package
  taxonomy: completed as
  `scientific_package_taxonomy_ready_with_protected_exceptions`; and
- final four-RQ/four-hypothesis experiment programme pre-registration:
  completed under programme identity
  `084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260`,
  with 43 core cells and 5,504 planned simulations; and
- final Experiment A, idiosyncratic diversification: completed from 128
  authoritative checkpoints and 1,024 simulations under experiment identity
  `a9d7c3fa5dc5da9bcf61314a57501ea5a8be506e305eee6f45afaae3131600bb`,
  without selecting a portfolio or shock; and
- final Experiment B, correlated stress: completed from 128 authoritative
  checkpoints and 1,024 simulations under experiment identity
  `e02c035162f8178c96d2cae71d0a581ce813ab33526854bd5810e8e2810ead83`,
  without selecting a portfolio or shock; and
- final Experiment C, stable-collateral trade-off: completed from 128
  authoritative checkpoints and 1,536 simulations under experiment identity
  `cb6d00877c54011cc49714bdfe23fad83140fef001568ea9b43d355811c9129b`,
  without selecting a portfolio or shock; and
- final Experiment D, shared keeper capacity: completed from 128 authoritative
  checkpoints and 1,152 simulations under experiment identity
  `b324c31be7ef6dd7f61e504709b2086b0e88ce181c177f25dcaad182095c17e3`,
  without selecting a capacity; and
- result-blind oracle-delay freeze: completed under registry identity
  `2e562ef2618e472ce3b0551addf2596ddbe137910fa6d2ad5884ae71c674e46d`
  as `transparent_sensitivity_not_empirically_identified`, resolving low,
  central and high to 0, 1 and 2 hourly steps without runtime adoption.
- final Experiment E, oracle delay: completed from 128 authoritative
  checkpoints and 768 simulations under experiment identity
  `67ec5a1e03492608c7f847861f7dbd506d2a526dbf4107298241b26c855eb0f8`,
  without selecting or runtime-adopting a delay.

Stages 1–5, final Experiments A–E and the result-independent oracle-delay
freeze are complete. The five-experiment core final programme is complete. No
portfolio, shock, capacity or oracle delay has been selected from validation
or experiment outcomes.

---

# 1. Final methodological position

The project is an empirically informed, mechanism-oriented agent-based simulation of DAI.

It is designed to evaluate how:

- collateral-price shocks;
- heterogeneous vault exposure;
- liquidation eligibility;
- keeper profitability;
- keeper throughput constraints;
- oracle timing;
- liquidation backlog;
- bad debt;
- DAI market response;
- persistent-confidence assumptions;
- collateral composition; and
- cross-collateral competition

jointly affect peg stability and system solvency.

The project is not intended to forecast the exact future DAI price or reproduce every historical MakerDAO auction.

The final empirical contribution should be framed as:

> Multi-collateralisation improves DAI resilience only when diversification remains effective under stress, collateral-specific risks are appropriately constrained, and liquidation capacity is sufficient. Otherwise, concentration risk may be replaced by correlation risk, stablecoin contagion and competition for keeper capacity.

---

# 2. Frozen completed work

## 2.1 Repository and reproducibility architecture

Completed:

- semantic source layout;
- versioned configurations;
- domain-specific empirical inputs;
- provenance manifests;
- deterministic seed registries;
- content-addressed scientific identities;
- atomic checkpoints;
- safe resume;
- regression tests;
- protected runtime-input checksums;
- protected smoke tests;
- protected Experiments 1–5.

Required final treatment:

- preserve all existing checksums;
- do not weaken tests;
- do not replace negative evidence;
- do not stage large ignored diagnostic outputs.

## 2.2 Market, gas, vault, protocol and liquidation evidence

Completed or substantially complete:

- hourly ETH, WBTC, DAI and gas panels;
- joint market and gas moving-block inputs;
- empirical gas-cost modes;
- empirical joint vault debt and collateral-ratio pools;
- protocol liquidation ratios and penalties;
- full protocol-level vault-closure abstraction;
- liquidation arrival hurdle;
- positive liquidation-count pool;
- liquidation-arrival sequence sensitivity;
- separation of unsafe inventory, arrivals, capacity, profitability and completed liquidations.

Important fixed distinction:

1. **Unsafe inventory** is the number of positions eligible for liquidation.
2. **Liquidation arrivals or demand** are the opportunities entering processing.
3. **Keeper capacity** limits how many opportunities can be attempted.
4. **Profitability or participation** determines which attempts are executable.
5. **Successful closure** resolves debt under the model’s full-close abstraction.

These objects must not be collapsed into one parameter.

## 2.3 Stage 1 DAI market response

Completed:

- ordinary below-peg response:
  \[
  \kappa_-=0.199381;
  \]
- ordinary above-peg response:
  \[
  \kappa_+=0.105131;
  \]
- accepted 24-hour moving-block DAI residual process;
- protected Stage 1 evidence.

Status:

- empirically estimated;
- active in the relevant empirical mechanism;
- must remain unchanged in final experiments.

## 2.4 Persistent-confidence calibration

Completed:

- point-estimation attempt;
- Monte Carlo precision diagnosis;
- alternative recovery-moment review;
- operationality review;
- partial identification;
- structural incompatibility decomposition;
- valid \(2^3\) structural factorial;
- uniform \(R=128\) MCSE reconciliation;
- final classification:
  `factorial_interactions_reveal_tradeoffs`.

Conclusion:

- no admissible persistent-confidence parameter vector;
- no admissible structural-factorial cell;
- no structural treatment selected;
- calibration rescue closed;
- persistent confidence remains dormant by default;
- persistent-confidence parameters may be used only as transparent scenarios.

Do not:

- reopen Sobol search;
- rerun partial identification;
- select cell `101`;
- adopt P25 vault state;
- adopt zero residuals;
- remove the backlog gate;
- run Powell;
- use final-validation data for selection.

## 2.5 Transparent confidence scenarios

Completed:

1. `stage1_only`;
2. `confidence_resilient`;
3. `confidence_central`;
4. `confidence_fragile`.

Authoritative transform:

\[
\alpha_d=u_d,
\qquad
\rho_r=u_r,
\qquad
\alpha_r=\alpha_d\rho_r,
\qquad
C_{\min}=u_C,
\qquad
\kappa_P=2.75454u_P.
\]

Status:

- fixed scenario-defined bundles;
- not estimates;
- not ranked;
- not selected;
- Stage 1-only remains the production default.

## 2.6 ETH-only recovery matrix

Completed:

- four ETH recovery paths;
- four confidence scenarios;
- 16 cells;
- 128 replications per cell;
- 2,048 simulations;
- common random numbers;
- zero numerical failures.

Final classification:

`no_clear_recovery_path_effect`

Mechanism interpretation:

- the severe ETH shock made almost all 100 legacy vaults liquidatable;
- full-close liquidations and ordinary unbounded keeper capacity resolved almost all positions immediately;
- unresolved tab and active bad debt were zero;
- later ETH recovery therefore had no remaining liquidation channel;
- confidence assumptions controlled DAI recovery in active scenarios.

This is a conditional null result.

Do not claim:

- ETH recovery never matters;
- collateral recovery is irrelevant under constrained capacity;
- confidence scenarios are ranked;
- Stage 1-only was selected because it performed better.

---

# 3. Remaining empirical work and decisions

## 3.1 Shared keeper throughput capacity — completed

Current model object:

- maximum number of liquidation opportunities processed per hour.

Current status:

- methodology and evidence calibration completed;
- one system-wide shared constraint is retained;
- capacity is partially identified from high-demand historical throughput;
- candidate values are 14, 26 and 45 opportunities per hour;
- no physical keeper-network maximum is claimed.

Original empirical requirement:

- estimate effective capacity from intervals with substantial liquidation demand;
- use central, lower and upper capacity values;
- recognise that observed completed liquidations are demand-constrained and therefore only partially identify maximum capacity.

This calibration is complete. The registered candidates remain
candidate-only and the shared range is evidence-constrained rather than a
physical keeper-network maximum.

## 3.2 Keeper participation or additional profit hurdle — resolved partial

Current profitability equation already includes direct liquidation economics and gas.

Resolved status:

- no defensible rejected-opportunity sample exists;
- the hurdle is partially identified from successful-execution margins only;
- `direct_cost_only` remains the central integration treatment.

Required final outcome:

- classification: `profit_hurdle_partially_identified`;
- lower sensitivity: `keeper_hurdle_low = 0.105100900480`;
- upper sensitivity: `keeper_hurdle_high = 0.124431757397`;
- positive values are not rejection-threshold estimates.

Do not confuse this with:

- liquidation-arrival probability;
- keeper capacity;
- gas cost;
- liquidation penalty.

## 3.3 Integrated empirical ETH-only profile — completed

The additive `empirical_integrated_eth` profile now combines 500
empirical-joint ETH vaults normalised to 2.5 million DAI, empirical market and
gas blocks, empirical hourly liquidation arrivals, system-wide capacity 26,
`direct_cost_only`, full-close liquidation, the accepted Stage 1 response and
residual blocks, Stage 1-only confidence, and a transparent zero-delay oracle
baseline.

The result-blind validation used 512 input initialisations and 128 independent
720-hour dynamic replications. All numerical and accounting gates passed. The
classification is `integrated_empirical_eth_profile_ready_with_caveats`
because one finite-sample arrival maximum statistic and several reduced-form
dynamic comparisons lack like-for-like historical references. The profile is
experiment-ready but `runtime_adopted: false`. See
[`docs/validation/integrated_empirical_eth.md`](docs/validation/integrated_empirical_eth.md).

## 3.4 Recovery under constrained execution — completed

The 24-cell constrained experiment used the validated
`empirical_integrated_eth` profile, empirical arrivals and gas,
`direct_cost_only`, capacities 14/26/45, two controlled ETH paths and four
fixed confidence scenarios. All 3,072 simulations completed without numerical
failure.

The result is `recovery_effect_capacity_dependent`. H5a is supported, H5b is
not supported, H5c is present and H5d is present. Full-week recovery avoids
closures and reduces backlog, with the largest rescue effect at capacity 14,
but primary Stage 1-only peg outcomes are unchanged. Higher capacity reduces
backlog while reducing the number of positions available for later recovery.

Capacity remains one system-wide constraint. Capacity 26 remains the existing
central candidate and 14/45 remain robustness cases; none was selected from
the result. No confidence scenario was ranked or selected. See
[`docs/experiments/constrained_eth_recovery.md`](docs/experiments/constrained_eth_recovery.md).

The separate technical maintenance pass is complete. The convenience
reconstruction CLI now uses the keyword-only interface correctly, and profile
resolution no longer creates a shared temporary validation file. Parallel
profile initialisation passed 100 resolutions across four spawned workers.
No result, evidence checksum, checkpoint, experiment identity, parameter or
production default changed, and no substantive simulation ran. The host
sandbox's process-semaphore restriction remains an environmental constraint
documented separately from the repaired race.

## 3.5 Oracle delay — result-blind freeze complete

The implemented global integer price lag is now frozen externally to the
unchanged master programme. The repository contains Spot adapter mappings,
hourly protocol state, market reference prices and OSM getter metadata, but no
eligible oracle observation timestamp series, update-interval series or
tracked effective numerical delay rule. No held-out data were used.

The evidence classification is
`transparent_sensitivity_not_empirically_identified`. The three registered
treatments are 0, 1 and 2 steps, equivalent to 0, 1 and 2 hours. Registry
identity is
`2e562ef2618e472ce3b0551addf2596ddbe137910fa6d2ad5884ae71c674e46d`.
These coordinates are result-blind mechanism sensitivities rather than
historical Maker latency estimates. The registry is not runtime adopted and
does not select a preferred delay.

Experiment E is complete under the same transparent-sensitivity boundary.
Its identity is
`67ec5a1e03492608c7f847861f7dbd506d2a526dbf4107298241b26c855eb0f8`.
E1 is `supported`, E2 is `partially_supported`, E3 is `peg_unchanged`, and
the overall classification is `H2_oracle_delay_partially_supported`.
Mismatch and recognition lag increase at both registered anchors; downstream
liquidation effects are partial and peg outcomes are unchanged. The
peg–solvency relationship is `solvency_deteriorates_peg_unchanged`.
Realised-bad-debt metrics remain degenerate under close-factor-one accounting.
No delay was selected, no held-out or USDC/SVB data were used, Experiments
A–D remain unchanged, and `runtime_adopted` remains false. See
[`docs/experiments/final/oracle_delay.md`](docs/experiments/final/oracle_delay.md).

## 3.6 Stable collateral process — frozen with a counterfactual boundary

The input freeze establishes:

- a generic stable collateral proxy;
- ordinary near-par variation from the local USDC series;
- fixed 0.95 and 0.90 depeg floors;
- 72-hour and 168-hour controlled smooth-recovery horizons;
- explicit `counterfactual_stable_proxy` status for its vault and protocol
  owners; and
- exclusion of March 2023 USDC/SVB from construction.

The March 2023 event did not determine the stable-depeg scenarios and remains
future final validation. There is still no direct stable-depeg confidence or
DAI-demand coefficient.

## 3.7 Empirical and controlled shock registry — frozen

The final result-blind registry contains:

- `eth_idiosyncratic_severe`;
- `wbtc_idiosyncratic_severe`;
- `joint_crypto_empirical_stress`;
- `joint_crypto_high_correlation`;
- `stable_depeg_moderate`;
- `stable_depeg_severe`; and
- `joint_crypto_stable_stress`.

Volatile severity uses nearest-rank q01 negative 24-hour returns or the
pre-registered joint downside-and-gas score. Stable severity uses transparent
fixed floors. The registry was frozen before any final outcome was inspected;
no shock was ranked or selected.

## 3.8 Population size — essential validation

Final empirical experiments should preferably use:

- 500 vaults as the central empirical population;
- one smaller sensitivity;
- one larger sensitivity.

Candidate sizes:

- 250;
- 500;
- 1,000.

The legacy 100-vault model remains a benchmark, not the preferred final empirical scale.

## 3.9 Collateral composition and protocol freeze — completed

The final input registry fixes:

- the family order ETH, WBTC and counterfactual STABLE;
- exact `ETH-A/B/C` and `WBTC-A/B/C` metadata;
- exact-ilk and mechanically debt-weighted family liquidation ratios;
- empirical ETH/WBTC debt shares of 0.8483941126796408 and
  0.1516058873203592;
- counterfactual stable debt coordinates of 0.25 and 0.50;
- five portfolios with exactly 500 vaults and 2.5 million DAI; and
- a common initial system collateral ratio of 3.6089387701260205.

Debt ceilings remain non-operational. `stable_supported` and `stable_heavy`
remain counterfactual, and the historical ETH/WBTC ratio is preserved within
their crypto shares.

## 3.10 Integrated distributional and out-of-sample validation — integration complete

The multi-collateral integration contract has passed 1,280 initialisations,
160 ordinary 168-hour simulations and six shared-capacity smokes. It validates
exact debt shares, common collateralisation, source isolation, numerical
states, one global ranking, one system cap, backlog carry-forward and
collateral-to-system reconciliation.

Population-scale validation, quiet held-out validation, held-out crypto-stress
validation and final USDC/SVB validation remain outstanding. The oracle-delay
freeze and Experiment E are complete. No retuning may follow final
validation.

The validation record is
[`docs/validation/multicollateral_integration.md`](docs/validation/multicollateral_integration.md).

---

# 4. Items that may remain limitations

## 4.1 Full auction lifecycle

May remain omitted:

- multiple Takes;
- strategic bids;
- auction duration;
- individual keeper identities;
- settlement stages;
- partial purchase microstructure.

Current model description:

- one-stage protocol-close abstraction;
- not a complete auction engine.

## 4.2 Dynamic Markov regime process

A separate Markov state model is optional because the block bootstrap already preserves:

- volatility clustering;
- serial dependence;
- cross-asset correlation;
- market–gas dependence.

## 4.3 Endogenous vault-owner intervention

Top-up and repayment behaviour may remain outside scope.

Document:

- owners do not rescue unsafe positions;
- this may overstate liquidation exposure;
- future work could estimate intervention probabilities.

## 4.4 Collateral-specific slippage and market depth

Do not add unless liquidation proceeds cannot be represented defensibly through existing protocol and keeper economics.

## 4.5 Time-varying portfolio composition

Use fixed portfolio weights for controlled counterfactual comparisons.

Time-varying composition may remain future work.

## 4.6 Direct stable-depeg confidence coefficient

Do not add automatically.

First test whether the stable-depeg collateral and liquidation channel produces a meaningful effect.

A direct perception or confidence channel requires a separate model-design decision.

---

# 5. Final stage sequence

## Stage 0 — Commit ETH-only recovery experiment

**Status:** completed.

Required final check:

- commit subject:
  `Evaluate ETH-only peg recovery`;
- scientific interpretation retained;
- detailed outputs ignored;
- production remains Stage 1-only.

## Stage 1 — Keeper execution calibration

**Status:** completed.

Stage 1 establishes one system-wide shared capacity in the unit of
protocol-level liquidation opportunities per one-hour simulation step. The
primary comparable universe is ETH-A/B/C and WBTC-A/B/C. Capacity is
`shared_capacity_partially_identified`, with candidates 14, 26 and 45.
Composition is `composition_unresolved` because the
single-collateral-dominant high-demand group contains only four hours. The
additional hurdle is `profit_hurdle_partially_identified`, based only on
successful-execution margins. The central integration treatment is capacity
26 with `direct_cost_only`; capacities 14 and 45 and hurdle values
0.105100900480 and 0.124431757397 are mandatory sensitivities. All profiles
remain candidate-only and `runtime_adopted: false`.

### Stage 1A — Data and semantic audit

Confirm:

- exact current capacity field;
- exact capacity unit;
- simulation frequency;
- liquidation demand owner;
- profitability owner;
- gas owner;
- candidate ordering;
- capacity truncation;
- successful-closure accounting.

Freeze the current unit:

> liquidation opportunities per hour.

Do not convert the production mechanism to debt-value capacity during this stage.

### Stage 1B — Effective capacity frontier

Use historical liquidation evidence to reconstruct hourly:

- start-of-hour unsafe inventory;
- sampled or observed liquidation arrivals;
- completed liquidations;
- completed debt;
- gas conditions;
- volatility;
- collateral type;
- active liquidator count where available.

Estimate capacity only in a result-blind high-demand subset.

Candidate approach:

1. define high-demand hours using unsafe inventory or arrivals;
2. inspect saturation evidence;
3. calculate conditional upper quantiles of completed count;
4. estimate lower, central and upper effective capacity;
5. scale to the chosen synthetic vault population through a pre-specified rule;
6. validate count and debt throughput.

If saturation is not identified:

- report a lower bound;
- retain a bounded sensitivity range;
- do not claim a physical maximum.

### Stage 1C — Profit hurdle

Audit observability of:

- gross liquidation opportunity;
- gas;
- expected collateral proceeds;
- successful execution;
- unexecuted profitable opportunities;
- keeper identity or participation count.

Classification hierarchy:

1. estimate the additional hurdle if both positive and negative participation observations are defensible;
2. otherwise partially identify the hurdle from successful-opportunity profit quantiles;
3. otherwise retain zero additional hurdle as the central deterministic mechanism and pre-register conservative sensitivities.

### Stage 1D — Keeper scenario registry

Expected output:

- `shared_keeper_capacity_low = 14`;
- `shared_keeper_capacity_central = 26`;
- `shared_keeper_capacity_high = 45`;
- central `direct_cost_only` treatment;
- `keeper_hurdle_low = 0.105100900480`;
- `keeper_hurdle_high = 0.124431757397`.

Do not rank or select profiles using final simulation outcomes.

### Stage 1 completion gate

Do not move to Stage 2 until:

- capacity unit is frozen;
- empirical mapping is documented;
- low/central/high values are registered;
- profit hurdle is resolved;
- evidence reconstructs deterministically;
- production default remains unchanged;
- full tests pass.

All Stage 1 completion-gate conditions are satisfied. The constraint is not
ETH-only, not per-ilk and not duplicated across collateral pools. It counts
opportunities rather than DAI debt or collateral value.

## Stage 2 — Integrated empirical ETH-only profile

**Status:** completed; experiment-ready with caveats and not runtime adopted.

This is an ETH-only integration validation harness, not an ETH recalibration
of the system-wide keeper capacity. No constrained-recovery or
multi-collateral matrix should run until this profile passes.

### Central profile

Combine:

- 500 empirical-joint vaults;
- empirical ETH market blocks;
- empirical gas;
- empirical liquidation arrivals;
- central keeper capacity;
- final keeper hurdle;
- full close;
- Stage 1 market response;
- empirical residual blocks;
- Stage 1-only confidence.

The central profile must use 500 empirical-joint vaults, empirical market and
gas blocks, empirical liquidation arrivals, shared central keeper capacity
26, `direct_cost_only`, the Stage 1 DAI response and Stage 1-only confidence.
Capacities 14 and 45, the two positive hurdle sensitivities, and 250/1,000
vault populations are mandatory sensitivities.

### Sensitivities

- low keeper capacity;
- high keeper capacity;
- lower/upper profit hurdle;
- 250 and 1,000 vaults;
- oracle-delay range.

### Validation

Compare simulated and empirical:

- vault debt distribution;
- collateral-ratio distribution;
- liquidation count distribution;
- completed debt;
- backlog;
- bad debt;
- keeper profit;
- DAI peg moments.

### Completion gate

Require:

- no silent legacy fallback;
- all empirical inputs identified in metadata;
- deterministic seed ownership;
- distributional validation evidence;
- no final-validation data.

All completion-gate conditions are satisfied. The 512 input initialisations
retain the empirical joint vault distribution, market–gas alignment and
hourly arrival owner without fallback. All 128 dynamic replications are
numerically valid, selected attempts never exceed the single system-wide cap
of 26, and the controlled smoke carries rejected backlog forward. The
transparent oracle remains uncalibrated. Population robustness is not part of
this completion gate and remains outstanding.

## Stage 3 — Constrained-liquidation recovery experiment

**Status:** complete; `recovery_effect_capacity_dependent`.

### Research question

> Does post-shock ETH recovery affect peg and solvency outcomes when liquidation demand and keeper throughput are empirically constrained?

### Core design

Recovery paths:

- `persistent_trough`;
- `full_week`.

Optional robustness:

- `rapid_full`;
- `partial_week`.

Keeper capacity:

- low;
- central;
- high.

Confidence:

- all four fixed scenarios, or a result-blind core-plus-robustness allocation.

Demand:

- empirical liquidation-arrival process.

Vaults:

- empirical central population.

### Primary outcomes

- below-peg burden;
- sustained-recovery RMST;
- maximum backlog;
- unresolved tab;
- bad debt;
- cumulative debt repaid;
- capacity saturation;
- recovery-gate closure.

### Main interpretation

Determine whether:

- ETH recovery rescues vaults before execution;
- constrained capacity allows collateral recovery to reduce backlog;
- bad debt prevents behavioural recovery;
- confidence effects interact with unresolved liquidation.

### Completion gate

Require:

- capacity constraints bind in at least some registered cells;
- no result-based path addition;
- no scenario ranking;
- clear comparison with the unbounded-capacity null result.

All completion conditions passed in the pre-registered 24-cell,
3,072-simulation matrix. Full-week recovery reduced liquidation debt and
backlog under every capacity, with larger rescue effects under lower capacity;
primary Stage 1 peg outcomes did not change. No capacity or confidence
scenario was selected.

## Stage 4 — Freeze final multi-collateral empirical inputs

**Status:** complete with counterfactual stable ownership.

### Final collateral set

Frozen:

- ETH;
- WBTC;
- one generic counterfactual stable proxy, using ordinary USDC prices without
  claiming an empirical stable-vault population.

The exact empirical ilks are `ETH-A/B/C` and `WBTC-A/B/C`. No additional
collateral is admitted.

### Freeze

- empirical ETH/WBTC portfolio shares;
- controlled balanced portfolio;
- moderate stable-supported portfolio;
- stable-heavy sensitivity;
- collateral-specific liquidation parameters;
- shared keeper capacity;
- price and gas blocks;
- stable depeg process;
- shock registry;
- principal and adverse recovery paths;
- vault-population scale.

The registry fixes five portfolios: `eth_only`, `empirical_crypto`,
`balanced_crypto`, `stable_supported` and `stable_heavy`. It fixes seven
shocks: `eth_idiosyncratic_severe`, `wbtc_idiosyncratic_severe`,
`joint_crypto_empirical_stress`, `joint_crypto_high_correlation`,
`stable_depeg_moderate`, `stable_depeg_severe` and
`joint_crypto_stable_stress`. Central scale is 500 vaults and 2.5 million DAI,
with common system collateralisation 3.6089387701260205.

### Required labels

- empirical;
- evidence-constrained;
- counterfactual;
- sensitivity.

Stable shares are labelled counterfactual. No portfolio or shock was selected
from model outcomes.

## Stage 5 — Multi-collateral integration validation

**Status:** complete; `final_multicollateral_inputs_ready_with_caveats`.

Verify:

- exact total initial debt across portfolios;
- exact debt shares;
- controlled initial collateral value;
- correct collateral-specific vault pools;
- correct liquidation thresholds;
- correct penalties;
- shared capacity applied globally;
- global profitability ordering;
- collateral-specific backlog;
- collateral-specific bad debt;
- exact system aggregation;
- isolated shock ownership;
- correlated path ownership;
- stable-depeg ownership;
- no equivalent scenario paths;
- unchanged ETH-only regression.

Completion gate:

- integration tests pass: yes;
- no silent per-collateral capacity duplication: yes;
- no double-counted debt: yes;
- no equivalent scenarios mislabelled as independent: yes.

All 1,280 initialisations and 160 ordinary dynamic replications passed. Under
simultaneous demand, 108 unsafe ETH/WBTC/STABLE opportunities competed for one
capacity of 26; the global ordering selected 9/9/8 and was invariant to input
permutation. The stable family remains counterfactual, so the validation is
ready with caveats rather than fully empirical.

## Stage 6 — Final multi-collateral experiments

**Status:** core programme complete. Experiments A–E and the result-independent
oracle-delay freeze are complete; H4 evidence synthesis remains pending.

Use a hierarchical design rather than one enormous full factorial.

### Experiment A — Idiosyncratic diversification

Portfolios:

- `eth_only`;
- `empirical_crypto`;
- `balanced_crypto`;
- `stable_supported`.

Shocks:

- `eth_idiosyncratic_severe`;
- `wbtc_idiosyncratic_severe`.

Core settings:

- central keeper capacity;
- Stage 1-only confidence;
- full-week recovery.

Question:

- does unaffected collateral reduce system losses?

Result:

- 128 original authoritative checkpoints and 1,024 simulations completed;
- no simulation was rerun during evidence reconstruction;
- A1 is `supported`;
- A2 is `exposure_gradient_consistent`;
- A3 is `shock_localisation_valid`;
- the overall classification is
  `H3_idiosyncratic_diversification_supported`; and
- the solvency–peg relationship is
  `solvency_improves_peg_unchanged`.

The post-execution NumPy JSON scalar repair is classified
`evidence_serialization_infrastructure`. It changed only evidence
serialisation, not scientific calculation, aggregation or decision logic.
No portfolio, shock or runtime configuration was ranked, selected or adopted.
See the [Experiment A report](docs/experiments/final/idiosyncratic_diversification.md).

### Experiment B — Stress correlation

Portfolios:

- same core portfolios.

Shocks:

- `joint_crypto_empirical_stress`;
- `joint_crypto_high_correlation`.

Question:

- do diversification benefits collapse as correlation rises?

Result:

- 128 authoritative checkpoints and 1,024 simulations completed;
- B1 is `supported`;
- B2 is `correlation_deterioration_present`;
- B3 is `transmission_mixed`;
- every diversified portfolio is `weakens_but_remains`;
- the overall classification is
  `H3_correlation_deterioration_supported`; and
- the peg–solvency relationship is
  `solvency_deteriorates_peg_unchanged`.

The result must not be described as a ceteris-paribus effect of increasing
correlation. The two frozen treatment bundles also differ in shock severity,
recovery and gas ownership; the empirical bundle has the larger realised
stress-window correlation and deeper drawdown, while the high-correlation
labelled bundle has more jointly negative hours. The decision applies to the
registered bundled-treatment contrast. No portfolio, shock or runtime
configuration was ranked, selected or adopted. See the
[Experiment B report](docs/experiments/final/correlated_stress.md).

### Experiment C — Stable-collateral trade-off

Portfolios:

- `empirical_crypto`;
- `stable_supported`;
- `stable_heavy`.

Shocks:

- `joint_crypto_high_correlation`;
- `stable_depeg_moderate`;
- `stable_depeg_severe`;
- `joint_crypto_stable_stress`.

Question:

- does stable collateral exchange crypto-price risk for depeg-contagion risk?

Result:

- 128 authoritative checkpoints and 1,536 simulations completed;
- the zero-STABLE negative control passed in all replications;
- C1 is `supported`;
- C2 is `depeg_exposure_gradient_inconsistent`;
- C3 is `contagion_mixed`;
- both stable-backed portfolios are
  `protection_without_material_depeg_cost`;
- the overall classification is
  `H3_stable_tradeoff_partially_supported`; and
- the peg–solvency relationship is
  `solvency_improves_peg_unchanged`.

The STABLE family is a counterfactual proxy, the depeg floors are
scenario-defined, and USDC/SVB was not used. No portfolio or shock was ranked
or selected. Experiments A and B remain unchanged. See the
[Experiment C report](docs/experiments/final/stable_collateral_tradeoff.md).

### Experiment D — Shared keeper capacity

Completed simultaneous-shock cells crossed with:

- low capacity: 14;
- central capacity: 26;
- high capacity: 45.

Question:

- does shared keeper capacity transmit stress across collateral pools?

Result:

- 128 authoritative checkpoints and 1,152 simulations completed;
- the empirical-crypto anchor has `capacity_relief_partial`;
- stable supported and stable heavy have
  `capacity_relief_not_supported`;
- D1 is `not_supported`;
- D2 is `shared_capacity_transmission_mixed`;
- D3 is `peg_unchanged`;
- the overall classification is
  `H1_no_clear_shared_capacity_effect`; and
- the peg–solvency relationship is
  `neither_materially_changes`.

The empirical-crypto low-capacity treatment produces a small threshold
backlog-area effect and clear rejection increase, but the other primary
completion metrics and all registered peg outcomes are unchanged. Realised
bad-debt metrics remain degenerate under close-factor-one accounting. The
capacity coordinates remain partially identified sensitivity values; no
capacity was ranked, selected or runtime adopted. The transmission result is
conditional on the frozen expected-profit, debt-at-risk and vault-ID ranking.
See the
[Experiment D report](docs/experiments/final/shared_keeper_capacity.md).

### Robustness layer

Apply only to selected core contrasts:

- four confidence scenarios;
- persistent trough versus full-week recovery;
- market block lengths;
- population sizes;
- oracle delays;
- empirical portfolio-share interval endpoints;
- keeper-hurdle range.

Do not choose robustness cells after inspecting favourable results.

## Stage 7 — Final validation

**Status:** pending.

### Stage 7A — Quiet held-out validation

Assess:

- false-positive stress;
- peg distribution;
- liquidation frequency;
- backlog;
- baseline recovery;
- numerical stability.

Do not retune.

### Stage 7B — Held-out crypto stress validation

Assess:

- direction of liquidation intensity;
- gas and keeper stress;
- collateral contribution;
- peg pressure;
- backlog and bad debt.

Do not claim exact historical replay where initial vault states are standardised.

### Stage 7C — Final USDC/SVB validation

Run once after all specifications are frozen.

Assess:

- stable collateral depeg transmission;
- stable-backed liquidation;
- cross-collateral effects;
- DAI peg direction and approximate magnitude;
- model limitations.

After this run:

- no parameter changes;
- no scenario changes;
- no mechanism additions;
- no result-based retuning.

## Stage 8 — Robustness, dissertation outputs and code freeze

**Status:** pending.

### Required robustness

- population size;
- block length;
- capacity bounds;
- keeper-hurdle bounds;
- confidence scenarios;
- oracle delay;
- recovery definition;
- portfolio shares;
- selected shock severities.

### Final artefacts

Produce:

- final experiment registry;
- final compact evidence;
- final tables;
- final figures;
- result narrative;
- limitations;
- validation summary;
- complete provenance manifest;
- final repository status.

### Final code freeze

After final validation and robustness:

1. freeze experiment identities;
2. rerun full suite;
3. regenerate evidence twice;
4. confirm checksums;
5. update `PROJECT_STATUS.md`;
6. update `MAIN.md`;
7. update this `FINAL.md`;
8. update README and code comments only from final working state;
9. archive obsolete diagnostics where appropriate;
10. stop model development.

---

# 6. Final required result metrics

## Peg

- minimum DAI price;
- maximum negative deviation;
- mean absolute deviation;
- below-peg burden;
- hours outside peg band;
- first return;
- sustained recovery;
- RMST;
- failed recovery attempts;
- censoring share.

## Liquidation

- unsafe inventory;
- arrivals;
- attempts;
- completed closures;
- capacity saturation;
- unprofitable attempts;
- debt repaid;
- unresolved tab;
- backlog duration.

## Solvency

- active bad debt;
- realised bad debt;
- collateral-specific bad debt;
- system collateral ratio;
- debt remaining.

## Keeper

- effective capacity;
- utilisation;
- profit;
- participation;
- rejected profitable opportunities;
- collateral allocation;
- crowding.

## Multi-collateral

- losses by collateral;
- liquidation contribution;
- bad-debt contribution;
- diversification gain;
- concentration;
- cross-collateral backlog;
- shared-capacity displacement;
- stable-depeg contribution.

---

# 7. Decision rules for unresolved parameters

For every unresolved parameter, use this hierarchy:

1. **Directly observed**
2. **Statistically estimated**
3. **Partially identified range**
4. **Mechanically derived**
5. **Transparent sensitivity**
6. **Documented limitation**

Never fill an unidentified parameter with pseudo-empirical precision.

Every final parameter must state:

- value or range;
- unit;
- source;
- estimation period;
- status;
- uncertainty;
- runtime adoption;
- validation boundary.

---

# 8. Final no-go list

Do not:

- reopen persistent-confidence calibration;
- rank confidence scenarios;
- select a factorial structural treatment;
- treat the unbounded recovery null as universal;
- run final multi-collateral experiments before keeper calibration;
- use the liquidation-arrival hurdle as keeper capacity;
- use completed historical liquidations as unconstrained physical capacity;
- add a full auction engine;
- add stETH without complete support;
- add owner intervention without a separate design;
- use USDC/SVB to select parameters;
- retune after held-out validation;
- add scenarios after inspecting results;
- change Stage 1 coefficients;
- change accepted residual blocks;
- overwrite Experiments 1–5;
- weaken regression tests;
- stage ignored detailed outputs;
- claim exact historical replay;
- claim predictive accuracy;
- claim multi-collateralisation is always safer.

---

# 9. Final progress checklist

## Completed

- [x] Repository restructuring and reproducibility
- [x] Market and gas inputs
- [x] Vault empirical pools
- [x] Protocol parameters
- [x] Liquidation-arrival process
- [x] Stage 1 DAI response
- [x] Persistent-confidence calibration closure
- [x] Structural-factorial reconciliation
- [x] Transparent confidence scenarios
- [x] ETH-only unbounded-capacity recovery experiment

## Immediate

- [x] Keeper capacity frontier
- [x] Keeper profit-hurdle decision
- [x] Keeper scenario registry

## Empirical integration

- [x] Integrated empirical ETH-only profile
- [x] Distributional validation
- [ ] Population-scale validation
- [x] Oracle-delay status freeze

## Recovery

- [x] Constrained-liquidation recovery experiment
- [x] Comparison with unbounded-capacity null
- [x] Reconstruction CLI maintenance
- [x] Concurrent profile-initialisation maintenance

## Multi-collateral inputs

- [x] Final collateral set
- [x] Final protocol parameter table
- [x] Portfolio composition registry
- [x] Stable collateral process, explicitly counterfactual
- [x] Empirical and controlled shock registry
- [x] Shared keeper allocation validation
- [x] Multi-collateral integration validation

## Pre-final maintenance

- [x] Project-structure visualisation and architecture audit
  - calibration, validation, input resolution and experiments are explicitly
    separated;
  - the ETH recovery studies are registered mechanism experiments;
  - `experiments/final/` is the sole destination for the next programme;
  - path-hashed validator implementations remain protected exceptions;
  - no duplicate active ownership was found;
  - no ignored diagnostic was removed; and
  - all scientific evidence remained unchanged.

## Final experiments

- [x] Idiosyncratic diversification
- [x] Stress correlation
- [ ] Stable-collateral trade-off
- [ ] Shared keeper capacity
- [ ] H4 evidence synthesis
- [ ] Selected robustness layer

## Validation

- [ ] Quiet held-out validation
- [ ] Held-out crypto stress validation
- [ ] Final USDC/SVB validation
- [ ] No-retuning confirmation

## Freeze

- [ ] Final robustness
- [ ] Final evidence reconstruction
- [ ] Final figures and tables
- [ ] `MAIN.md` updated
- [ ] `FINAL.md` updated
- [ ] `PROJECT_STATUS.md` closed
- [ ] README and comments refreshed
- [ ] Full suite and clean repository audit
- [ ] Model development stopped

---

# 10. Immediate next pass

The next scientific stage is:

> **Complete the pre-registered H4 recovery and behavioural-stabilisation
> evidence synthesis.**

The final experiment registry continues to use the frozen five portfolios and
seven shocks without result-based screening. Experiments A–E are complete.
Population, positive-hurdle and oracle-delay cases remain separate
robustness dimensions. The remaining final experiments, population robustness,
held-out validation, USDC/SVB validation and final code freeze remain
incomplete.
