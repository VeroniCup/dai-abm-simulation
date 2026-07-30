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

The file should be checked after every remaining pass and updated only when a stage has been committed and validated.

The project must not move directly from the completed unbounded-capacity ETH-recovery experiment to final multi-collateral simulations. Keeper execution must first be empirically constrained and then integrated into the principal empirical model.

## End-stage completion checklist

Completed in the current end-stage pass:

- keeper capacity frontier: completed with a partially identified shared range;
- keeper profit-hurdle decision: completed at the successful-execution evidence level;
- keeper scenario registry: completed as candidate-only, opt-in evidence.
- integrated empirical ETH-only profile: completed and experiment-ready with caveats;
- integrated input and dynamic distributional validation: completed.

Stages 1 and 2 are complete. The next stage is the separately pre-registered
constrained-liquidation recovery experiment; no multi-collateral matrix should
run before that bounded comparison is reviewed.

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

## 3.4 Recovery under constrained execution — essential

The completed recovery experiment used unbounded capacity.

A second, narrower recovery experiment must test whether ETH recovery matters where:

- arrivals are empirical;
- keeper capacity is bounded;
- unresolved vaults persist;
- backlog can interact with the full recovery gate;
- bad debt may remain active.

This is required before interpreting recovery in the multi-collateral model.

## 3.5 Oracle delay — required closure, not necessarily new estimation

Mechanics exist, but the final status of the parameter must be frozen.

Required audit:

- determine whether adequate historical oracle timestamps exist;
- estimate low, central and high delay where supported;
- otherwise classify oracle delay as a transparent sensitivity;
- do not call an arbitrary delay calibrated.

A major new acquisition project is not required unless existing data are insufficient for even a sensitivity rationale.

## 3.6 Stable collateral process — essential before final multi-collateral experiments

The project must freeze:

- exact stable proxy, likely USDC;
- ordinary near-par noise;
- controlled depeg magnitudes;
- depeg persistence or recovery paths;
- status of stable-backed portfolios as counterfactual;
- final-validation boundary for March 2023 USDC/SVB.

The March 2023 event must not determine the stable-depeg scenario if it remains final validation.

## 3.7 Empirical shock registry — essential

The fixed \(2000\rightarrow1140\) ETH shock is suitable for a mechanism experiment but should not be the only final stress definition.

Required final shock families:

- isolated ETH shock;
- isolated WBTC shock;
- empirical joint crypto stress;
- high-correlation crypto stress;
- stablecoin depeg;
- joint crypto and stable stress;
- optional sequential shock.

Severity levels should be fixed from empirical tail definitions or transparent counterfactual rules before final outcomes are inspected.

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

## 3.9 Collateral composition and protocol freeze — essential

Before final multi-collateral execution, freeze:

- collateral types;
- exact collateral-family mapping;
- liquidation ratios;
- liquidation penalties;
- debt ceilings where used;
- empirical ETH/WBTC debt shares;
- counterfactual stable shares;
- total initial debt;
- total initial collateral value or exposure-normalisation rule.

The historical ETH/WBTC share does not identify a stable-collateral share.

Stable-supported and stable-heavy portfolios must be labelled counterfactual unless additional evidence is introduced.

## 3.10 Integrated distributional and out-of-sample validation — essential

The final empirical profile must complete:

- distributional validation;
- moment comparison;
- quiet-period validation;
- held-out crypto-stress validation;
- final USDC/SVB validation.

No retuning may follow final validation.

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

**Status:** pending.

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

## Stage 4 — Freeze final multi-collateral empirical inputs

**Status:** pending.

### Recommended collateral set

Prefer:

- ETH;
- WBTC;
- USDC or one generic stable proxy.

Do not add stETH unless complete market, vault and protocol evidence already exists and implementation cost is modest.

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

### Required labels

- empirical;
- evidence-constrained;
- counterfactual;
- sensitivity.

Do not call stable shares empirical without supporting debt-composition evidence.

## Stage 5 — Multi-collateral integration validation

**Status:** pending.

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

- integration tests pass;
- no silent per-collateral capacity duplication;
- no double-counted debt;
- no equivalent scenarios mislabelled as independent.

## Stage 6 — Final multi-collateral experiments

**Status:** pending.

Use a hierarchical design rather than one enormous full factorial.

### Experiment A — Idiosyncratic diversification

Portfolios:

- ETH-only;
- empirical ETH/WBTC;
- balanced crypto;
- stable-supported.

Shocks:

- ETH-specific;
- WBTC-specific.

Core settings:

- central keeper capacity;
- Stage 1-only confidence;
- full-week recovery.

Question:

- does unaffected collateral reduce system losses?

### Experiment B — Stress correlation

Portfolios:

- same core portfolios.

Shocks:

- empirical joint crypto stress;
- high-correlation stress;
- systemic crypto stress.

Question:

- do diversification benefits collapse as correlation rises?

### Experiment C — Stable-collateral trade-off

Portfolios:

- crypto-only;
- moderate stable-supported;
- stable-heavy counterfactual.

Shocks:

- crypto stress;
- stable depeg;
- joint crypto and stable stress.

Question:

- does stable collateral exchange crypto-price risk for depeg-contagion risk?

### Experiment D — Shared keeper capacity

Selected simultaneous-shock cells crossed with:

- low capacity;
- central capacity;
- high capacity.

Question:

- does shared keeper capacity transmit stress across collateral pools?

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
- [ ] Oracle-delay status freeze

## Recovery

- [ ] Constrained-liquidation recovery experiment
- [ ] Comparison with unbounded-capacity null

## Multi-collateral inputs

- [ ] Final collateral set
- [ ] Final protocol parameter table
- [ ] Portfolio composition registry
- [ ] Stable collateral process
- [ ] Empirical shock registry
- [ ] Shared keeper allocation validation

## Final experiments

- [ ] Idiosyncratic diversification
- [ ] Stress correlation
- [ ] Stable-collateral trade-off
- [ ] Shared keeper capacity
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

The next authorised pass is:

> **Pre-register and run the bounded constrained-liquidation recovery experiment using the validated `empirical_integrated_eth` profile, without tuning the profile, changing production defaults, using final-validation data or running a multi-collateral matrix.**

The central integration treatment remains system-wide capacity 26 with
`direct_cost_only`. Population, positive-hurdle and oracle-delay cases remain
separate robustness dimensions.
