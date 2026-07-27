# Phase 2 Parameter Estimation Plan

## 1. Purpose

This document provides the methodological bridge between empirical data
acquisition and calibration of the agent-based model (ABM). It defines how
each implemented simulator parameter should be sourced, transformed,
estimated, validated and passed into the model without assigning a value in
advance.

The governing sequence is:

> **Verified empirical inputs → derived calibration variables → transparent
> estimators → parameter uncertainty → withheld validation → simulator
> configuration**

This sequence is consistent with the
[empirical framework](../empirical.md), the
[parameter acquisition plan](../parameters.md) and the
[representative Phase 1E strategy](phase1e_representative_calibration_strategy.md).
It does not replace those documents. It turns their data and source decisions
into a reproducible Phase 2 estimation procedure.

The plan covers every implemented configuration field and every economically
material public control used by the current simulation. Fields that are aliases
for the same mechanism are discussed together, but remain separately
identified in the traceability table. Object names, column labels and other
routing fields are included as structural inputs; they are not presented as
economic estimates.

This document deliberately does not:

- estimate or recommend numerical parameter values;
- change the simulator's equations;
- introduce unimplemented MakerDAO mechanisms;
- treat purposively selected stress windows as a random historical sample; or
- describe a protocol setting, literature assumption or experimental choice
  as an empirical estimate.

### Phase 2A implementation record

The bounded Phase 2A tranche has implemented the parts of this plan that are
identifiable from validated Phase 1A--1D data. Its generated candidate bundle
is under `data/processed/estimation/phase2a/`, and its concise technical record
is the [Phase 2A parameter-estimation report](phase2a_parameter_estimation_report.md).
No candidate has been written into simulator configuration.

Phase 2A does not supersede the Phase 1E-B dependency recorded below.
Quiet-mature and USDC/SVB evidence is now acquired and validated; nine
Phase 1E-B-dependent parameter candidates have subsequently been estimated in
Phase 2B and remain subject to review.
The completed Terra/CeFi window contributes 649 exact Bark–grab links and
pre-grab states. Phase 2C has now used them to produce a protocol-level
`max_close_factor = 1.0` review candidate; the value remains unadopted.

The separate Tranche A empirical configuration bundle now documents the first
configuration-only adoption step in
[the Tranche A empirical configuration report](tranche_a_empirical_configuration_report.md).
It is opt-in only and does not change the methodological classification below.

The subsequent Tranche B implementation introduces the optional
distribution-aware vault-initialisation interface described in
[the Tranche B distribution-aware initialisation report](tranche_b_distributional_vault_initialisation_report.md).
It provides a runtime bridge for paired empirical debt and collateral-ratio
evidence, while preserving the distinction between candidate estimation and
parameter adoption.

Tranche C extends that bridge to empirical market and gas inputs. The opt-in
implementation is documented in
[the Tranche C empirical market and gas report](tranche_c_empirical_market_and_gas_report.md).
It consumes validated hourly return and gas artefacts without re-estimating
parameters or changing the equations that consume prices and gas costs.

Tranche D adds the corresponding opt-in bridge for liquidation-arrival demand
and keeper-throughput separation. It uses the Phase 2C Terra/CeFi
Bark--grab/hourly evidence to sample a hurdle-count demand process before the
existing keeper-profit and capacity rules are applied. The implementation is
documented in
[the Tranche D liquidation-arrival and capacity report](tranche_d_liquidation_arrival_and_capacity_report.md).

The first Phase 1E-B tranche is documented in the
[tranche 1 acquisition report](phase1e_b_tranche1_acquisition_report.md).
Its quiet-mature reconstruction is complete after the bounded Method B rate
repair. The separately authorised
[USDC/SVB window](phase1e_b_usdc_svb_acquisition_report.md) also passes exact
opening-to-closing replay. These results establish estimation readiness; they
do not themselves estimate or adopt any simulator value.

### Phase 2B implementation record

The bounded Phase 2B tranche has now estimated the nine authorised
vault-population candidates supported by the quiet-mature and USDC/SVB
reconstructions. The generated registry and diagnostics are under
`data/processed/estimation/phase2b_vaults/`, and the methods and results are
documented in the
[Phase 2B vault-parameter report](phase2b_vault_parameter_estimation_report.md).
No estimate has been adopted. Raw debt and collateral-ratio moments remain
provisional distribution choices because the current global Gaussian
interfaces do not preserve the observed heavy tails or exact-ilk
heterogeneity. `n_vaults` remains a provisional computational scaling choice.

`max_close_factor` is supported by 649 exact Terra/CeFi Bark–grab links. All
observations are full closures. Phase 2C reports this degeneracy and
distinguishes empirical Maker Liquidations 2.0 semantics from partial-close
scenario design. Bull expansion remains a secondary leverage and
collateral-composition sensitivity. The withheld FTX interval was not used for
fitting.

---

## 2. Parameter classification

Every value supplied to the simulator must carry one primary provenance class.
Hybrid evidence may be recorded in the notes, but the final parameter record
must not obscure its principal basis.

### 2.1 Protocol constants

Protocol constants are governance or contract settings observed directly for a
particular ilk and effective time. They are not estimated statistically.
Examples include the liquidation ratio and liquidation penalty.

Protocol constants may vary over time. A historical replay must use the value
effective at the replay timestamp. A generic experiment must state the
effective date, time-weighting rule or collateral-family aggregation used to
reduce an effective-dated series to one simulator input.

### 2.2 Empirically estimated parameters

Empirically estimated parameters are obtained from observed market, gas,
liquidation or representative vault data. They include directly measured
statistics, fitted distribution parameters and behavioural coefficients
identified by matching observable moments.

Each estimate must retain:

- the source artefact and checksum;
- the calibration interval or representative windows;
- the observation unit and frequency;
- the transformation formula;
- the estimator;
- uncertainty or resampling information; and
- the reason that the estimator is compatible with the simulator field.

### 2.3 Literature-derived parameters

Literature-derived parameters are used only where the existing data do not
identify a mechanism sufficiently. Examples may include bounds on unobserved
keeper inventory risk or oracle-operation delays where exact update evidence
is unavailable.

The record must cite the source, explain the translation into model units and
identify the parameter as literature-derived. Literature values should be
subject to sensitivity analysis rather than treated as exact observations.

### 2.4 Experimental scenario parameters

Experimental scenario parameters define the research design rather than an
unknown historical quantity. They include the simulation horizon, shock
timing, random seed, counterfactual portfolio composition and mechanism
switches.

An empirical distribution may inform a scenario range, but the selected
scenario remains an experimental choice. Baseline, stress and robustness
values must therefore be labelled as scenario settings.

### 2.5 Structural and routing inputs

Structural inputs identify model objects or route data, for example collateral
names, portfolio names and price-column labels. They are validated against the
model schema and empirical mapping, but they are not calibrated.

### 2.6 Classification rule for ambiguous cases

When more than one evidence type contributes, apply the following rule:

1. a directly effective protocol setting takes precedence for a protocol
   mechanism;
2. a measurable historical distribution takes precedence for an observable
   behavioural outcome;
3. literature constrains an unobserved component but does not convert it into
   an empirical estimate;
4. an investigator-selected point within an empirical or literature range is
   an experimental scenario value; and
5. a coefficient fitted only to make one crisis replay look plausible is not a
   validated estimate.

---

## 3. Calibration workflow

### 3.1 Freeze the estimation target

Before estimation, record the code revision, time-step definition, parameter
schema and model equation that consumes each parameter. A parameter must not be
estimated against one equation and then used in a materially different
equation without re-estimation.

The current empirical frequency is hourly. Any daily, event-level or
transaction-level statistic must be converted explicitly to the hourly model
frequency where required.

### 3.2 Verify input provenance

Only data that pass the corresponding Phase 1 validation may enter estimation:

- Phase 1A supplies aligned ETH, WBTC, DAI and USDC prices, returns and peg
  deviations;
- Phase 1B supplies hourly effective gas-price, base-fee, priority-fee,
  utilisation and failed-transaction measures;
- Phase 1C supplies liquidation, auction, keeper-transaction and
  liquidation-specific gas evidence;
- Phase 1D supplies effective-dated protocol settings and contract mappings;
  and
- Phase 1E-B will supply representative vault states and economic mutations,
  using the acquisition method validated in Phase 1E-A.

The estimation run must fail if an expected checksum, schema, time boundary,
unit conversion or validation status does not match the registered provenance.

### 3.3 Construct derived variables

Derived variables must be created in a deterministic processing stage, not
inside an optimiser. Important examples are:

\[
r_{a,t} = \log P_{a,t} - \log P_{a,t-1},
\]

\[
\text{collateral ratio}_{i,t}
=
\frac{\text{collateral amount}_{i,t}P_{a,t}}
     {\text{accrued DAI debt}_{i,t}},
\]

\[
\text{gas cost USD}_{j}
=
\text{gas used}_{j}
\times
\text{effective gas price}_{j,\mathrm{wei}}
\times 10^{-18}
\times
P_{\mathrm{ETH},h(j)},
\]

and

\[
\text{liquidatable share}_{t}
=
\frac{\#\{i:\mathrm{CR}_{i,t}<\mathrm{LR}_{i,t}\}}
     {\#\{i:\text{active at }t\}}.
\]

Every derived field must have an explicit formula, unit, missing-value rule and
source-field mapping.

### 3.4 Separate estimation, validation and scenario periods

Continuous Phase 1A–1C series may be partitioned chronologically into
calibration and validation periods. Phase 1E-B windows are purposively selected
and therefore estimate conditional vault behaviour. They must not, on their
own, determine unconditional crisis probabilities.

At least one representative stress window must remain withheld from parameter
fitting. Where data are sparse, use rolling-origin or leave-one-window-out
validation rather than reusing every observation for both estimation and
assessment.

### 3.5 Estimate observable parameters first

Estimation should proceed in blocks:

1. protocol constants and effective-date mappings;
2. market return, dependence and gas distributions;
3. vault size, leverage and behavioural-transition distributions;
4. liquidation cost, timing and capacity;
5. confidence and DAI-price behavioural coefficients; and
6. joint refinement subject to the uncertainty from the earlier blocks.

This order limits compensation between weakly identified parameters. For
example, `panic_strength` should not be allowed to absorb an incorrect gas-cost
or keeper-capacity specification.

### 3.6 Preserve uncertainty

A single point estimate is insufficient for stochastic stress testing. Each
empirical or literature-derived parameter should have an uncertainty object,
such as:

- a bootstrap distribution;
- a confidence interval;
- posterior or profile-likelihood bounds;
- regime-specific empirical quantiles; or
- a documented sensitivity set.

Simulation runs should propagate parameter uncertainty separately from process
noise and scenario variation.

### 3.7 Export a machine-readable calibration bundle

Phase 2 should produce a versioned bundle containing, for every parameter:

- implemented field name;
- provenance class;
- source paths and checksums;
- transformation version;
- estimator and settings;
- fitted value or distribution;
- uncertainty;
- units and frequency;
- calibration and validation windows;
- acceptance-test results; and
- the simulator configuration path that consumes it.

The bundle should be generated, not hand-edited, once estimation begins.

---

## 4. Parameter-by-parameter estimation plan

### 4.1 Simulation design and structural inputs

#### 4.1.1 `n_steps`

**Purpose.** Defines the number of hourly state transitions in one simulation
run.

**Empirical source.** The required replay or stress-test interval; no empirical
estimation dataset is needed.

**Derived variable.** Number of timestamps after aligning the chosen start,
exclusive end and hourly frequency.

**Statistical estimator.** None. This is an experimental scenario parameter.

**Simulation implementation.** `SimulationConfig.n_steps` and
`PriceProcessConfig.n_steps` must agree with the supplied price-path length.

**Validation method.** Confirm exact timestamp count, aligned collateral paths
and no early truncation or implicit padding.

**Notes.** Longer horizons are robustness designs, not better estimates.

#### 4.1.2 `n_vaults`

**Purpose.** Sets the size of the synthetic vault population.

**Empirical source.** Phase 1E-B active-vault counts and debt concentration
within representative windows.

**Derived variable.** Observed active-vault count, debt-weight distribution and
sampling weight required to represent system debt.

**Statistical estimator.** Experimental choice informed by convergence tests;
not a direct historical count unless each simulated vault represents one
observed vault.

**Simulation implementation.** `SimulationConfig.n_vaults`.

**Validation method.** Repeat simulations at increasing population sizes and
verify stability of debt shares, liquidation rates, bad debt and peg outcomes.

**Notes.** If computational scaling requires representative weights, the
weighting rule must be documented rather than silently changing vault size.

#### 4.1.3 `random_seed`

**Purpose.** Makes stochastic vault sampling, price generation and DAI-price
noise reproducible.

**Empirical source.** None.

**Derived variable.** A registered sequence of seed identifiers for baseline
and robustness runs.

**Statistical estimator.** None. This is an experimental scenario parameter.

**Simulation implementation.** `SimulationConfig.random_seed`,
`PriceProcessConfig.random_seed`, the vault generators and
`build_multicollateral_price_paths`.

**Validation method.** Identical inputs and seeds must reproduce identical
outputs; reported conclusions must also be stable across a pre-registered
multi-seed set.

**Notes.** A favourable seed must never be selected after inspecting outcomes.

#### 4.1.4 `execute_liquidations`

**Purpose.** Switches the keeper-liquidation mechanism on or off.

**Empirical source.** None.

**Derived variable.** Boolean mechanism state.

**Statistical estimator.** None. This is an experimental scenario parameter.

**Simulation implementation.** Runtime argument to the public simulation
wrappers.

**Validation method.** With identical paths and initial states, compare the
enabled run with a disabled counterfactual and verify that only the intended
liquidation-mediated outcomes change.

**Notes.** The disabled setting is a mechanism experiment, not a historical
claim that liquidations did not operate.

#### 4.1.5 `collateral_portfolio`, `collaterals` and portfolio `name`

**Purpose.** Defines which one-asset vault classes coexist and labels the
portfolio experiment.

**Empirical source.** Phase 1D exact-ilk mappings and Phase 1E-B collateral
scope; experiment definitions for counterfactual portfolios.

**Derived variable.** Ordered set of model collateral classes and their exact
ilk-to-model mapping.

**Statistical estimator.** None for membership and names. Portfolio membership
is structural; counterfactual composition is experimental.

**Simulation implementation.** `SimulationConfig.collateral_portfolio` and
`CollateralPortfolioConfig.collaterals`/`name`.

**Validation method.** Require unique normalised collateral names, shares
summing to one and a complete mapping to prices and risk parameters.

**Notes.** Model classes such as BTC may combine several exact Maker ilks only
through an explicit, effective-dated aggregation rule.

#### 4.1.6 collateral `name` and vault `collateral_type`

**Purpose.** Routes prices, protocol settings and results to the correct
collateral class.

**Empirical source.** Phase 1D exact ilk and contract mappings.

**Derived variable.** Exact-ilk-to-model-class lookup retaining wrapper
provenance, for example WBTC mapped to the BTC model class.

**Statistical estimator.** None. These are structural routing inputs.

**Simulation implementation.** `CollateralConfig.name` and the
`collateral_type` argument/field used by vault generation.

**Validation method.** Reject unmapped labels, duplicate class identifiers and
price paths that do not cover every portfolio class.

**Notes.** The raw instrument must remain WBTC in empirical provenance even
where the simulator class is BTC.

#### 4.1.7 `price_col` and `oracle_col`

**Purpose.** Select source columns when adapting legacy price-path data.

**Empirical source.** The validated processed-panel schema.

**Derived variable.** Column-name mapping only.

**Statistical estimator.** None. These are routing inputs.

**Simulation implementation.** `add_shock_to_existing_path` and
`add_oracle_price`.

**Validation method.** Confirm the selected columns exist, contain finite
positive prices and have the intended economic meaning.

**Notes.** Column labels must not appear in the calibration bundle as numerical
parameters.

### 4.2 Initial prices, portfolio composition and vault population

#### 4.2.1 `initial_eth_price` and collateral `initial_price`

**Purpose.** Sets the initial unit price used to construct vault collateral and
price paths.

**Empirical source.** Phase 1A hourly ETH, WBTC and stablecoin prices.

**Derived variable.** Price at the exact replay start or a declared normalised
starting index for scale-free experiments.

**Statistical estimator.** Direct observation for replay; none for a normalised
scenario.

**Simulation implementation.** `SimulationConfig.initial_eth_price`,
`PriceProcessConfig.initial_price` and `CollateralConfig.initial_price`.

**Validation method.** Match the replay timestamp exactly and verify that vault
collateral values reproduce the intended initial collateral ratios.

**Notes.** A normalised price is an experimental convention and must not be
described as an observed USD price.

#### 4.2.2 `initial_dai_price`

**Purpose.** Initializes the simulated DAI market state.

**Empirical source.** Phase 1A DAI/USD series.

**Derived variable.** DAI price at the replay start or the protocol peg for a
generic counterfactual.

**Statistical estimator.** Direct observation for replay; protocol/scenario
value for generic experiments.

**Simulation implementation.** Runtime argument to the public simulation
wrappers.

**Validation method.** Confirm that the first reported price and first
price-change calculation use the chosen initial state without a one-step
shift.

**Notes.** Starting every historical stress replay exactly at par would discard
observed pre-existing peg pressure.

#### 4.2.3 `target_debt_share`

**Purpose.** Allocates sampled system debt across collateral classes.

**Empirical source.** Phase 1E-B representative vault states, reconciled where
possible with protocol debt aggregates and Phase 1D activation boundaries.

**Derived variable.** Active DAI debt by model collateral class divided by
total active debt at a defined snapshot or window summary.

**Statistical estimator.** Direct empirical share for the observed baseline;
pre-specified weights for counterfactual portfolios.

**Simulation implementation.** `CollateralConfig.target_debt_share`.

**Validation method.** Compare realised simulated shares with targets and test
alternative snapshot/averaging rules.

**Notes.** Observed composition and experimental portfolios must be stored as
different configurations.

#### 4.2.4 `debt_mean`

**Purpose.** Controls the centre of the initial vault-debt distribution used by
the existing Gaussian generator.

**Empirical source.** Phase 1E-B representative vault snapshots after exact
rate conversion of normalised debt.

**Derived variable.** Active DAI debt per urn, by collateral and regime, with
zero-debt and inactive vaults classified explicitly.

**Statistical estimator.** Mean of the estimation population if the current
Gaussian generator is retained; bootstrap uncertainty and debt-weighted
diagnostics should accompany it.

**Simulation implementation.** `SimulationConfig.debt_mean` and the vault
generators.

**Validation method.** Compare simulated and empirical mean, median, upper
quantiles, concentration and total debt.

**Notes.** Vault debt is likely skewed. Matching only the mean is a documented
model limitation; empirical resampling would require a later authorised code
change.

#### 4.2.5 `debt_std`

**Purpose.** Controls dispersion of initial vault debt in the existing
generator.

**Empirical source.** The same Phase 1E-B active-vault debt samples used for
`debt_mean`.

**Derived variable.** Cross-sectional standard deviation of DAI debt within
the defined collateral/regime population.

**Statistical estimator.** Sample standard deviation with vault-level
bootstrap uncertainty.

**Simulation implementation.** `SimulationConfig.debt_std` and the vault
generators.

**Validation method.** Compare simulated dispersion, quantiles, tail share and
Gini or concentration measures against the empirical distribution.

**Notes.** The generator clips low debt. Validation must therefore assess the
realised, not merely requested, standard deviation.

#### 4.2.6 `collateral_ratio_mean`

**Purpose.** Sets the centre of initial vault leverage.

**Empirical source.** Phase 1E-B vault collateral, exact accrued debt, Phase 1A
collateral price and Phase 1D effective liquidation settings.

**Derived variable.** Vault collateral value divided by accrued DAI debt at
representative snapshots.

**Statistical estimator.** Sample mean within collateral and regime, with
window-clustered bootstrap uncertainty.

**Simulation implementation.** `SimulationConfig.collateral_ratio_mean` and
the vault generators.

**Validation method.** Compare full distributions, liquidation-distance
quantiles and debt-weighted collateralisation, not just the mean.

**Notes.** Pooling purposive stress and quiet windows without weights would
distort the unconditional population.

#### 4.2.7 `collateral_ratio_std`

**Purpose.** Controls cross-vault leverage heterogeneity.

**Empirical source.** The same representative vault snapshots used for the
collateral-ratio mean.

**Derived variable.** Cross-sectional dispersion of collateral ratios after
excluding debt-zero ratios that are economically undefined.

**Statistical estimator.** Sample standard deviation with window-clustered
bootstrap uncertainty.

**Simulation implementation.** `SimulationConfig.collateral_ratio_std` and the
vault generators.

**Validation method.** Compare lower-tail liquidation distance, interquartile
range and debt-weighted dispersion.

**Notes.** A Gaussian mean and standard deviation do not preserve the observed
dependence between vault debt and leverage; joint-distribution diagnostics are
mandatory.

#### 4.2.8 `min_collateral_ratio_buffer`

**Purpose.** Prevents newly generated vaults from starting below their
liquidation ratio.

**Empirical source.** Phase 1E-B distance-to-liquidation distribution can
inform a plausible range, but the clipping rule itself is a modelling
safeguard.

**Derived variable.** Lower-tail distance
\(\mathrm{CR}_{i}-\mathrm{LR}_{i}\) among active non-liquidating vaults.

**Statistical estimator.** None for the baseline rule; choose as an
experimental scenario parameter and test against empirical lower quantiles.

**Simulation implementation.** Public vault-generator argument.

**Validation method.** Report the share of draws altered by clipping and
compare the realised lower tail with observed vault states.

**Notes.** Heavy clipping indicates misspecification of the proposed
collateral-ratio distribution.

### 4.3 Collateral price paths and shock controls

#### 4.3.1 `price_path`

**Purpose.** Supplies the exogenous market-price sequence for each collateral.

**Empirical source.** Phase 1A aligned hourly prices and returns.

**Derived variable.** Historical replay path, aligned moving-block bootstrap or
declared deterministic shock path.

**Statistical estimator.** Empirical moving-block bootstrap is preferred for
stochastic calibration because it preserves cross-asset dependence and
volatility clustering.

**Simulation implementation.** Runtime input to
`run_simulation_with_price_path` in the canonical collateral mapping.

**Validation method.** Compare marginal return quantiles, drawdowns,
autocorrelation, cross-asset dependence and regime durations with the source
data.

**Notes.** This path input should be preferred over a Gaussian process for the
main empirical experiments.

#### 4.3.2 `mu`

**Purpose.** Sets drift in the optional geometric Brownian motion benchmark.

**Empirical source.** Phase 1A log returns at the intended frequency.

**Derived variable.** Mean log return converted consistently to the units
implied by `dt`.

**Statistical estimator.** Sample mean or maximum-likelihood drift, with
uncertainty reported; zero-drift is an experimental benchmark.

**Simulation implementation.** `generate_gbm_price_path` and
`run_gbm_simulation`.

**Validation method.** Check frequency scaling and compare generated long-run
return distributions with empirical observations.

**Notes.** Drift is weakly estimated over short crypto samples and should not
drive stress conclusions.

#### 4.3.3 `sigma`

**Purpose.** Sets volatility in the optional geometric Brownian motion
benchmark.

**Empirical source.** Phase 1A hourly log returns.

**Derived variable.** Standard deviation of log returns, annualised or
de-annualised consistently with `dt`.

**Statistical estimator.** Realised standard deviation, preferably reported by
regime and year with bootstrap uncertainty.

**Simulation implementation.** `generate_gbm_price_path` and
`run_gbm_simulation`.

**Validation method.** Compare generated volatility and return quantiles with
the empirical sample; document GBM tail underfit.

**Notes.** Regime-conditioned empirical blocks are preferable where volatility
is non-stationary.

#### 4.3.4 `dt`

**Purpose.** Converts drift and volatility rates to one price-process step.

**Empirical source.** The simulation frequency definition.

**Derived variable.** Fraction of the estimation unit represented by one
hourly step.

**Statistical estimator.** None. This is a structural experimental parameter.

**Simulation implementation.** `generate_gbm_price_path` and
`run_gbm_simulation`.

**Validation method.** Dimensional checks must reproduce the intended
annualised or hourly variance.

**Notes.** An inconsistent `dt` can create an apparently calibrated but
incorrect volatility.

#### 4.3.5 `floor_price`

**Purpose.** Prevents non-positive numerical prices in the GBM generator.

**Empirical source.** None.

**Derived variable.** Numerical lower bound.

**Statistical estimator.** None. This is a modelling safeguard/scenario
parameter.

**Simulation implementation.** `generate_gbm_price_path`.

**Validation method.** Confirm the floor is never binding in ordinary runs and
report every binding observation in stress tests.

**Notes.** It must not be estimated from the minimum historical price or used
to suppress economically meaningful losses.

#### 4.3.6 `shock_time`

**Purpose.** Locates a deterministic shock within the simulation.

**Empirical source.** Historical event timestamps for replay or the experiment
design for generic stress.

**Derived variable.** Integer offset from the simulation start.

**Statistical estimator.** None. This is an experimental scenario parameter.

**Simulation implementation.** Shock generators, simulation wrappers and
multi-collateral path construction.

**Validation method.** Verify the pre-shock path is unchanged and the shock is
applied exactly once at the registered step.

**Notes.** Shock timing should not be adjusted after observing model outcomes.

#### 4.3.7 `shock_size`, `shock_sizes`, `crypto_crash_size` and
`stable_depeg_size`

**Purpose.** Defines the one-step loss by collateral in deterministic stress
experiments.

**Empirical source.** Phase 1A hourly returns, rolling drawdowns and
joint-return blocks.

**Derived variable.** Collateral-specific tail return or drawdown conditional
on a clearly defined horizon and regime.

**Statistical estimator.** Empirical conditional quantiles or block-bootstrap
draws; selected fixed severities remain experimental scenario parameters.

**Simulation implementation.** Price shock functions and
`MultiCollateralShockScenario.shock_sizes`, including the convenience
`crypto_crash_size` and `stable_depeg_size` arguments.

**Validation method.** Compare severity, duration and cross-asset co-movement
with held-out stress blocks.

**Notes.** The same percentage shock must not be imposed on ETH, BTC and stable
collateral merely for convenience unless it is explicitly a controlled
counterfactual.

#### 4.3.8 `pre_shock_drift` and `post_shock_drift`

**Purpose.** Controls deterministic price movement before and after a shock.

**Empirical source.** Phase 1A local return windows around candidate stress
blocks.

**Derived variable.** Mean return over pre-defined pre- and post-shock
intervals.

**Statistical estimator.** Window mean with block-bootstrap uncertainty, or
zero as an experimental isolation of the shock.

**Simulation implementation.** `generate_shock_price_path`.

**Validation method.** Confirm cumulative pre/post movement and avoid
double-counting recovery through both drift and a recovery function.

**Notes.** These controls are not needed when replaying or resampling observed
paths.

#### 4.3.9 `recovery_start`

**Purpose.** Marks the first step of deterministic collateral-price recovery.

**Empirical source.** Phase 1A stress drawdown and recovery episodes.

**Derived variable.** Hours from the shock to a pre-defined recovery criterion.

**Statistical estimator.** Empirical duration distribution; a chosen duration
is an experimental scenario setting.

**Simulation implementation.** Shock-recovery generator and wrapper.

**Validation method.** Check ordering relative to shock and recovery end, and
compare with held-out episode durations.

**Notes.** The recovery criterion must be fixed before measuring durations.

#### 4.3.10 `recovery_end`

**Purpose.** Marks the final step of deterministic recovery.

**Empirical source.** The same Phase 1A recovery episodes.

**Derived variable.** Hours from shock to the chosen terminal recovery
criterion.

**Statistical estimator.** Empirical duration quantiles; selected value remains
an experimental scenario parameter.

**Simulation implementation.** Shock-recovery generator and wrapper.

**Validation method.** Require `recovery_end > recovery_start` and compare the
resulting slope and duration with observed episodes.

**Notes.** Censored episodes that do not recover within the observation window
must not be treated as completed recoveries.

#### 4.3.11 `recovery_fraction`

**Purpose.** Sets the fraction of the shock loss reversed by the recovery end.

**Empirical source.** Phase 1A stress and recovery blocks.

**Derived variable.** Recovered price distance divided by the initial shock
distance at a fixed horizon.

**Statistical estimator.** Empirical conditional distribution by asset and
regime; chosen quantile is an experimental scenario setting.

**Simulation implementation.** Shock-recovery generator and wrapper.

**Validation method.** Verify endpoint arithmetic and compare recovery
fractions with withheld episodes.

**Notes.** Values must not imply a full return to the prior level unless the
scenario intends that outcome.

#### 4.3.12 `oracle_delay_steps` and `delay_steps`

**Purpose.** Creates the information delay between market and oracle prices.

**Empirical source.** Exact oracle update timestamps where acquired, Phase 1D
oracle mappings and verified protocol/literature evidence.

**Derived variable.** Hours between a market-price observation and the oracle
value effective for liquidation eligibility.

**Statistical estimator.** Empirical delay distribution where identifiable;
otherwise a literature/protocol-bounded scenario set.

**Simulation implementation.** `SimulationConfig.oracle_delay_steps` and
`add_oracle_price(delay_steps=...)`.

**Validation method.** Historical replay of oracle-versus-market divergence,
liquidatable-share timing and liquidation onset.

**Notes.** The current simulator applies one delay across collateral types.
Collateral-specific delays require a separately authorised extension.

### 4.4 Liquidation and keeper parameters

#### 4.4.1 `liquidation_ratio`

**Purpose.** Determines when a vault becomes eligible for liquidation.

**Empirical source.** Phase 1D effective-dated Spot liquidation-ratio history,
mapped from exact ilks.

**Derived variable.** Raw `mat` converted from RAY and mapped to the relevant
model collateral and timestamp.

**Statistical estimator.** None. This is a protocol constant.

**Simulation implementation.** Global `SimulationConfig.liquidation_ratio`,
vault generation and optional `CollateralConfig.liquidation_ratio` override.

**Validation method.** Recompute historical eligibility for selected Phase 1E
vault states and compare with observed liquidation boundaries.

**Notes.** Collateral overrides should be used where exact ilks differ. Any
family-level aggregation must state whether it is debt-weighted, time-weighted
or scenario-specific.

#### 4.4.2 `liquidation_penalty`

**Purpose.** Sets the gross penalty/reward component in the simplified keeper
profit equation.

**Empirical source.** Phase 1D Dog `chop` history by exact ilk.

**Derived variable.** `chop / 1e18 - 1`, effective at the simulation timestamp.

**Statistical estimator.** None. This is a protocol constant.

**Simulation implementation.** Global `LiquidationConfig.liquidation_penalty`
with optional `CollateralConfig.liquidation_penalty` override.

**Validation method.** Compare configured values with the effective protocol
ledger and Phase 1C auction economics.

**Notes.** The model treats the penalty as keeper gross reward; that
simplification must be assessed because realised auction proceeds do not
necessarily accrue identically.

#### 4.4.3 `gas_cost`

**Purpose.** Subtracts the cost of attempting a liquidation from expected
keeper profit.

**Empirical source.** Phase 1C classified successful Take transactions, joined
to Phase 1A ETH/USD; Phase 1B supplies the surrounding network gas regime.

**Derived variable.**
\[
\text{gas used}\times\text{effective gas price}_{\mathrm{wei}}
\times10^{-18}\times\mathrm{ETH/USD}.
\]

**Statistical estimator.** Primary distribution from clean
single-Take/single-auction transactions; regime-conditional median or
quantiles may be selected for corresponding scenarios.

**Simulation implementation.** `LiquidationConfig.gas_cost`, denominated in
USD/DAI terms.

**Validation method.** Compare selected cost distributions with held-out
liquidation transactions and with Phase 1B hourly median, P90 and P99 gas
conditions.

**Notes.** Standardised 100k/300k/500k indices are diagnostics, not substitutes
for liquidation-specific gas observations.

#### 4.4.4 `risk_cost_rate`

**Purpose.** Represents proportional auction, inventory, slippage and
operational risk omitted from direct gas cost.

**Empirical source.** Phase 1C auction discounts, durations, resets and
transaction classifications, supplemented by keeper-market literature where
off-chain costs are unobserved.

**Derived variable.** Residual cost relative to repaid debt after separately
accounting for observed gas and directly measurable auction economics.

**Statistical estimator.** Transparent bounded calibration or minimum-distance
fit to keeper-participation and auction-outcome moments; literature-informed
sensitivity where residual components remain unidentified.

**Simulation implementation.** `LiquidationConfig.risk_cost_rate`.

**Validation method.** Out-of-sample keeper participation, delay and auction
completion; profile sensitivity must show whether conclusions depend on this
parameter.

**Notes.** An accounting residual is not automatically keeper profit or risk
cost. Omitted components must be listed.

#### 4.4.5 `max_close_factor`

**Purpose.** Caps the share of one vault's debt repaid in one simulated
liquidation.

**Empirical source.** Phase 1C auction outcomes and Phase 1E-B pre/post
liquidation vault states.

**Derived variable.** Debt repaid by a liquidation episode divided by debt at
risk, with multi-take auctions linked before calculation.

**Statistical estimator.** Empirical distribution or collateral/regime
quantile if the simplified mechanism is retained.

**Simulation implementation.** Global
`LiquidationConfig.max_close_factor` with optional
`CollateralConfig.max_close_factor` override.

**Validation method.** Compare simulated partial/full liquidation shares,
residual debt and repeat-liquidation frequency with observed episodes.

**Notes.** Maker Liquidations 2.0 is not literally a fixed close-factor system.
This is a model analogue and must not be labelled as a direct protocol
constant.

#### 4.4.6 `max_liquidations_per_step`

**Purpose.** Represents shared keeper-processing capacity per hourly step.

**Empirical source.** Phase 1C hourly auction initiation, successful take,
completion and unique-participant counts, conditioned on Phase 1B gas regime.

**Derived variable.** Number of liquidation opportunities successfully
processed per hour, together with backlog and clustering measures.

**Statistical estimator.** Regime-conditional empirical distribution or
capacity quantile; a fixed cap is a reduced-form approximation.

**Simulation implementation.** `LiquidationConfig.max_liquidations_per_step`.

**Validation method.** Compare completion counts, capacity-limited attempts,
backlog duration and collateral competition with held-out stress windows.

**Notes.** Capacity is global in the current model. Collateral-specific
capacity would change the economic mechanism and is outside this estimation
task.

The Tranche D interface separates this throughput cap from empirical
liquidation-arrival demand. In the opt-in hurdle-count mode,
`max_liquidations_per_step` limits attempted opportunities after demand has
already been truncated to simulated unsafe-vault inventory; in legacy mode,
all eligible liquidatable vaults continue to be considered by the existing
liquidation routine.

### 4.5 Confidence-regime parameters

#### 4.5.1 `normal_lower_price`

**Purpose.** Sets the lower DAI-price boundary of the normal regime.

**Empirical source.** Phase 1A DAI peg-deviation distribution.

**Derived variable.** Lower boundary of the central normal-price region.

**Statistical estimator.** Pre-registered empirical quantile or threshold
selected by classification performance against stress outcomes.

**Simulation implementation.** `ConfidenceConfig.normal_lower_price`.

**Validation method.** Regime frequency, stability across years and prediction
of held-out liquidation/peg-stress moments.

**Notes.** A selected quantile becomes an empirical classification rule, not a
protocol constant.

#### 4.5.2 `normal_upper_price`

**Purpose.** Sets the upper DAI-price boundary of the normal regime.

**Empirical source.** Phase 1A positive peg-deviation distribution.

**Derived variable.** Upper boundary of the central normal-price region.

**Statistical estimator.** Empirical upper quantile or threshold selected
symmetrically/asymmetrically according to validated classification performance.

**Simulation implementation.** `ConfidenceConfig.normal_upper_price`.

**Validation method.** Asymmetric above/below-peg classification checks and
year-by-year regime frequencies.

**Notes.** The boundary need not be symmetric around one if the data reject
symmetry.

#### 4.5.3 `stress_lower_price`

**Purpose.** Defines the DAI-price boundary below which panic is eligible.

**Empirical source.** Phase 1A lower-tail DAI deviations and Phase 1C
liquidation stress.

**Derived variable.** Lower-tail price threshold associated with materially
different stress outcomes.

**Statistical estimator.** Tail quantile or change-point/classification
threshold estimated on calibration periods.

**Simulation implementation.** `ConfidenceConfig.stress_lower_price`.

**Validation method.** Held-out detection of persistent depeg periods, false
panic frequency and sensitivity to nearby thresholds.

**Notes.** It must remain below `normal_lower_price` by construction.

#### 4.5.4 `max_normal_liquidatable_share`

**Purpose.** Separates ordinary from stressed vault-system pressure.

**Empirical source.** Phase 1E-B reconstructed representative vault states,
with Phase 1C hourly liquidation activity.

**Derived variable.** Share of active vaults below their effective liquidation
ratio at each observed hour.

**Statistical estimator.** Upper quantile of ordinary-window observations or
threshold selected to distinguish ordinary and stress conditions.

**Simulation implementation.**
`ConfidenceConfig.max_normal_liquidatable_share`.

**Validation method.** Out-of-window regime classification and observed
liquidation-arrival differences.

**Notes.** Representative stress windows cannot determine the unconditional
frequency without appropriate continuous-data weighting.

#### 4.5.5 `max_stress_liquidatable_share`

**Purpose.** Marks vault pressure sufficiently severe to contribute to panic.

**Empirical source.** The same vault-state and liquidation panels as the normal
threshold.

**Derived variable.** Upper-tail liquidatable share during stress windows.

**Statistical estimator.** Stress-tail quantile or classification threshold
estimated without using the withheld validation window.

**Simulation implementation.**
`ConfidenceConfig.max_stress_liquidatable_share`.

**Validation method.** Panic recall, false positives, bad-debt outcomes and
threshold sensitivity.

**Notes.** Must not be below `max_normal_liquidatable_share`.

#### 4.5.6 `bad_debt_panic_threshold`

**Purpose.** Allows active bad debt to trigger panic.

**Empirical source.** Phase 1C unrecovered-debt evidence and Phase 1E-B system
debt/reconstruction where defensible.

**Derived variable.** Active bad debt in DAI and, for validation, bad debt as a
share of active system debt.

**Statistical estimator.** Behavioural calibration to peg and confidence
moments; absolute threshold chosen consistently with simulated system scale.

**Simulation implementation.**
`ConfidenceConfig.bad_debt_panic_threshold`.

**Validation method.** Scale tests across `n_vaults`, total debt and portfolio
composition, plus held-out depeg behaviour.

**Notes.** The implemented threshold is absolute. A normalised empirical
threshold cannot be inserted without an explicit conversion to the simulated
system scale.

#### 4.5.7 `normal_confidence`

**Purpose.** Sets the latent stabilising-confidence level in the normal regime.

**Empirical source.** Not directly observed; Phase 1A DAI mean reversion and
Phase 1C/1E system stress provide target moments.

**Derived variable.** Normal-regime DAI adjustment and volatility moments.

**Statistical estimator.** Minimum-distance or simulated method of moments
(SMM), with a normalisation where needed for identification.

**Simulation implementation.** `ConfidenceConfig.normal_confidence`.

**Validation method.** Held-out normal-period peg dispersion and recovery
dynamics.

**Notes.** This is a calibrated behavioural parameter, not survey-measured
confidence.

#### 4.5.8 `stress_confidence`

**Purpose.** Reduces stabilising behaviour during stress.

**Empirical source.** Phase 1A stress-window DAI dynamics and Phase 1C
liquidation conditions.

**Derived variable.** Stress-regime persistence, peg deviation and recovery
moments relative to normal periods.

**Statistical estimator.** Joint SMM or minimum-distance calibration subject
to the confidence ordering restriction.

**Simulation implementation.** `ConfidenceConfig.stress_confidence`.

**Validation method.** Withheld stress-window peg path and regime duration,
with profile sensitivity.

**Notes.** It is jointly identified with DAI-market strength parameters and
must not be estimated in isolation without checking compensation.

#### 4.5.9 `panic_confidence`

**Purpose.** Sets stabilising confidence in the most severe regime.

**Empirical source.** Severe DAI depeg observations and corresponding
liquidation/bad-debt conditions.

**Derived variable.** Extreme-regime peg depth, persistence and recovery
moments.

**Statistical estimator.** Constrained SMM or bounded calibration, supplemented
by literature/sensitivity because extreme observations are sparse.

**Simulation implementation.** `ConfidenceConfig.panic_confidence`.

**Validation method.** Leave-one-event-out validation and wide uncertainty
reporting.

**Notes.** Sparse crises do not support a falsely precise estimate.

#### 4.5.10 `panic_selling_multiplier`

**Purpose.** Amplifies selling pressure when confidence enters panic.

**Empirical source.** Phase 1A DAI downside moves and recovery, conditional on
Phase 1C liquidation pressure and bad-debt evidence.

**Derived variable.** Incremental downside price pressure during panic after
controlling for ordinary peg gap and modelled system stress.

**Statistical estimator.** Constrained behavioural calibration to panic-depth
and duration moments.

**Simulation implementation.**
`ConfidenceConfig.panic_selling_multiplier`.

**Validation method.** Withheld-event depth, duration and recovery plus
sensitivity to the confidence parameters.

**Notes.** The parameter captures a reduced-form channel and should not be
interpreted as observed sell volume.

### 4.6 DAI-market parameters

#### 4.6.1 `peg_price`

**Purpose.** Defines the target price around which DAI demand and supply
pressures operate.

**Empirical source.** Maker's monetary design and DAI's USD target.

**Derived variable.** Target USD price.

**Statistical estimator.** None. This is a protocol/design constant.

**Simulation implementation.** `DAIMarketConfig.peg_price`.

**Validation method.** Unit tests and confirmation that all peg-gap formulas
use the same target.

**Notes.** Observed mean market price is not a replacement for the target.

#### 4.6.2 `price_adjustment_speed`

**Purpose.** Converts net demand pressure into a one-step DAI-price change.

**Empirical source.** Phase 1A hourly DAI prices and empirical stress
covariates from Phases 1B–1E.

**Derived variable.** Hourly DAI price change and model-implied net pressure.

**Statistical estimator.** SMM or minimum-distance fit to autocorrelation,
variance and impulse-response moments.

**Simulation implementation.** `DAIMarketConfig.price_adjustment_speed`.

**Validation method.** Held-out one-step changes, peg-deviation distribution
and recovery half-life.

**Notes.** This parameter is scale-dependent on the pressure equations and
must be estimated jointly or under explicit normalisations.

#### 4.6.3 `arbitrage_strength`

**Purpose.** Controls stabilising demand when DAI trades below peg.

**Empirical source.** Phase 1A below-peg episodes and recovery paths.

**Derived variable.** Subsequent DAI price correction conditional on lagged
negative peg gap and confidence regime.

**Statistical estimator.** Constrained regression for initial evidence,
followed by SMM in the full nonlinear model.

**Simulation implementation.** `DAIMarketConfig.arbitrage_strength`.

**Validation method.** Below-peg recovery speed and overshoot in held-out
episodes.

**Notes.** It is not direct on-chain arbitrage volume and must be labelled as a
reduced-form coefficient.

#### 4.6.4 `above_peg_supply_strength`

**Purpose.** Controls selling or minting pressure when DAI trades above peg.

**Empirical source.** Phase 1A above-peg episodes; protocol/vault activity may
provide supporting evidence where Phase 1E-B overlaps.

**Derived variable.** Subsequent DAI correction conditional on a positive peg
gap.

**Statistical estimator.** Asymmetric constrained regression followed by SMM.

**Simulation implementation.**
`DAIMarketConfig.above_peg_supply_strength`.

**Validation method.** Above-peg recovery speed, overshoot and asymmetry
relative to below-peg episodes.

**Notes.** It should not be forced equal to `arbitrage_strength` unless an
explicit restricted model is being tested.

#### 4.6.5 `panic_strength`

**Purpose.** Converts panic-selling pressure into DAI supply pressure.

**Empirical source.** Phase 1A severe depegs joined to Phase 1C liquidation and
Phase 1E-B system-stress measures.

**Derived variable.** Incremental downside DAI movement associated with the
model's panic-pressure proxy.

**Statistical estimator.** Joint constrained SMM with confidence and panic
parameters.

**Simulation implementation.** `DAIMarketConfig.panic_strength`.

**Validation method.** Withheld severe-event depth/duration and parameter
profile diagnostics.

**Notes.** Joint identification with `panic_selling_multiplier` must be tested;
one coefficient may require normalisation.

#### 4.6.6 `noise_std`

**Purpose.** Adds unexplained stochastic variation to the DAI price.

**Empirical source.** Phase 1A hourly DAI changes.

**Derived variable.** Residual price innovation after fitting deterministic
peg, confidence and system-stress components.

**Statistical estimator.** Residual standard deviation, with heteroskedasticity
and regime stability checks.

**Simulation implementation.** `DAIMarketConfig.noise_std`.

**Validation method.** Residual distribution, autocorrelation, normality/tail
diagnostics and simulated peg-volatility coverage.

**Notes.** It should be estimated after deterministic coefficients; otherwise
it absorbs model misspecification.

#### 4.6.7 `min_price`

**Purpose.** Provides a lower numerical bound for simulated DAI price.

**Empirical source.** None required; historical support can inform sensitivity.

**Derived variable.** Numerical lower bound.

**Statistical estimator.** None. This is an experimental safeguard.

**Simulation implementation.** `DAIMarketConfig.min_price`.

**Validation method.** Report how often it binds and repeat key experiments
with wider bounds.

**Notes.** It must not censor stress outcomes without explicit disclosure.

#### 4.6.8 `max_price`

**Purpose.** Provides an upper numerical bound for simulated DAI price.

**Empirical source.** None required; historical support can inform sensitivity.

**Derived variable.** Numerical upper bound.

**Statistical estimator.** None. This is an experimental safeguard.

**Simulation implementation.** `DAIMarketConfig.max_price`.

**Validation method.** Report binding frequency and test wider bounds.

**Notes.** Bounds should not be chosen to make the simulated distribution
match the historical range mechanically.

#### 4.6.9 `enable_peg_recovery`

**Purpose.** Switches the additional peg-recovery mechanism on or off.

**Empirical source.** None.

**Derived variable.** Boolean mechanism state.

**Statistical estimator.** None. This is an experimental scenario parameter.

**Simulation implementation.** `DAIMarketConfig.enable_peg_recovery`.

**Validation method.** Paired mechanism comparison under identical paths,
vaults and seeds.

**Notes.** The switch tests a model mechanism; it is not a time-varying
historical observation.

#### 4.6.10 `arbitrage_recovery_strength`

**Purpose.** Adds explicit mean-reverting recovery pressure below peg.

**Empirical source.** Phase 1A below-peg recovery episodes.

**Derived variable.** Incremental recovery conditional on peg gap and
confidence after accounting for the base arbitrage term.

**Statistical estimator.** Constrained SMM or nested-model comparison.

**Simulation implementation.**
`DAIMarketConfig.arbitrage_recovery_strength`.

**Validation method.** Held-out recovery half-life, cumulative deviation and
overshoot; compare against the simpler model.

**Notes.** If the coefficient cannot be separately identified from
`arbitrage_strength`, retain the simpler mechanism or report a sensitivity
range.

#### 4.6.11 `policy_feedback_strength`

**Purpose.** Represents additional stabilising policy feedback in the recovery
mechanism.

**Empirical source.** Phase 1A recovery paths aligned with Phase 1D protocol
changes where timing supports such a link.

**Derived variable.** Residual recovery associated with documented effective
policy changes and confidence.

**Statistical estimator.** Event-time or local-projection evidence followed by
bounded SMM; literature bounds if policy effects are not separately
identifiable.

**Simulation implementation.**
`DAIMarketConfig.policy_feedback_strength`.

**Validation method.** Withheld recovery periods and comparison with a zero
feedback restriction.

**Notes.** Do not infer causality from contemporaneous governance changes
alone.

#### 4.6.12 `bad_debt_recovery_drag`

**Purpose.** Weakens peg recovery when active bad debt is high.

**Empirical source.** Phase 1C bad-debt proxies, Phase 1E-B system debt and
Phase 1A DAI recovery.

**Derived variable.** Recovery response conditional on bad debt as a share of
active system debt.

**Statistical estimator.** Constrained SMM with literature/sensitivity bounds
when bad-debt episodes are sparse.

**Simulation implementation.**
`DAIMarketConfig.bad_debt_recovery_drag`.

**Validation method.** Leave-one-event-out recovery and interaction moments.

**Notes.** Ensure the empirical bad-debt denominator maps to the simulator's
implemented ratio.

#### 4.6.13 `min_recovery_confidence`

**Purpose.** Sets the minimum confidence needed for explicit recovery pressure.

**Empirical source.** Confidence is latent; Phase 1A recovery/non-recovery
episodes provide target classification moments.

**Derived variable.** Boundary in the calibrated confidence scale separating
effective from ineffective recovery.

**Statistical estimator.** Profiled threshold within joint behavioural
calibration.

**Simulation implementation.**
`DAIMarketConfig.min_recovery_confidence`.

**Validation method.** Held-out recovery classification, threshold stability
and sensitivity to confidence-scale normalisation.

**Notes.** It cannot be estimated independently before the confidence scale is
identified.

---

## 5. Statistical estimation methods

### 5.1 Direct effective-state extraction

Phase 1D protocol settings should be joined by exact effective time, ilk and
contract mapping. The estimator is a deterministic as-of join:

\[
\theta_{i,t}
=
\theta_{i,k}
\quad\text{for}\quad
t_k \leq t < t_{k+1}.
\]

No interpolation is permitted. Values remain null before validated activation.
When several exact ilks map to one simulator class, retain each exact series
and document the aggregation or scenario-selection rule.

### 5.2 Empirical distributions and quantiles

Observable gas costs, vault sizes, leverage, liquidation fractions and delays
should first be represented as empirical distributions. Report counts, missing
coverage, quantiles, mean, standard deviation, tail concentration and
regime/collateral stratification.

Quantiles must use a registered convention. Transaction-level distributions
must deduplicate by transaction hash before measuring top-level gas.

### 5.3 Clustered and block bootstrap

Ordinary independent bootstrapping is inappropriate where observations share
an auction, vault, transaction or time block. Use:

- moving-block bootstrap for hourly market and gas series;
- auction-level bootstrap for linked liquidation actions;
- vault-level bootstrap for cross-sectional snapshots; and
- window-clustered bootstrap for representative Phase 1E-B comparisons.

The bootstrap unit and number of replications must be recorded in the
calibration metadata.

### 5.4 Regime-conditioned estimation

Estimate ordinary, stress and extreme distributions using regime definitions
fixed before fitting the simulator. Phase 1B candidate gas regimes may support
exploration but should not become final states solely because they generate a
desirable simulation.

Report both pooled and regime-conditioned estimates. Test temporal stability
across years and the pre-/post-London fee-market distinction where relevant.

### 5.5 Joint market-path estimation

The primary price-process method should resample aligned ETH, WBTC and stable
collateral return blocks. This retains empirical cross-asset dependence,
volatility clustering and tail co-movement.

GBM estimates are benchmark inputs only. They should not replace empirical
paths in the main calibration unless diagnostics demonstrate adequate
distributional fit.

### 5.6 Threshold estimation

Confidence thresholds may be estimated by:

- pre-registered empirical quantiles;
- change-point analysis; or
- classification thresholds chosen on calibration periods to distinguish
  economically defined normal, stress and panic outcomes.

Thresholds must obey the simulator's ordering constraints. Classification
performance must be evaluated on held-out periods, and results must be
reported over a nearby threshold grid.

### 5.7 Minimum-distance calibration and SMM

Latent behavioural parameters should be fitted only after observable inputs
are fixed. Let \(\mathbf m^{\mathrm{data}}\) be empirical moments and
\(\mathbf m^{\mathrm{sim}}(\theta)\) the mean simulated moments across registered
seeds. Estimate:

\[
\hat{\theta}
=
\arg\min_{\theta\in\Theta}
\left[
\mathbf m^{\mathrm{sim}}(\theta)-\mathbf m^{\mathrm{data}}
\right]^\top
W
\left[
\mathbf m^{\mathrm{sim}}(\theta)-\mathbf m^{\mathrm{data}}
\right].
\]

Candidate moments include:

- DAI peg-deviation quantiles;
- DAI return variance and autocorrelation;
- below- and above-peg recovery half-life;
- stress and panic duration;
- liquidation completion and capacity-limited shares;
- bad debt relative to active debt; and
- keeper-participation or clean-Take outcomes.

Use transparent parameter bounds, a fixed weighting matrix and multiple
starting points. Report weak identification, flat objective regions and
parameter correlations rather than choosing one arbitrary optimum.

### 5.8 Partial identification and sensitivity sets

Where several parameter combinations reproduce the same moments, retain an
admissible parameter set. Dissertation conclusions should be repeated across
that set. This is particularly important for:

- confidence levels and panic amplification;
- DAI adjustment and arbitrage strengths;
- unobserved keeper risk cost; and
- bad-debt effects on recovery.

### 5.9 Multiple testing and specification choices

Pre-register the primary estimator, moments and validation windows. Alternative
window weights, block lengths, threshold rules and aggregation mappings are
robustness specifications. Do not select among them solely by the final
counterfactual result.

---

## 6. Validation methodology

### 6.1 Data and transformation validation

Before estimation:

- verify all registered checksums and validation statuses;
- confirm UTC timestamps and exact frequency;
- validate raw units and transformations;
- enforce exact ilk and contract mappings;
- distinguish observed rows from documented defaults or locally derived rows;
- prevent transaction-level gas duplication; and
- retain missingness and inactive-period semantics.

### 6.2 Parameter-level validation

Each parameter record must pass:

1. **unit validation** — simulator and source units agree;
2. **support validation** — estimates satisfy model constraints;
3. **provenance validation** — source and transformation are reproducible;
4. **stability validation** — estimates are compared across time and
   representative windows;
5. **uncertainty validation** — intervals or sensitivity sets are retained;
   and
6. **implementation validation** — the value reaches the intended field and
   equation.

### 6.3 Distributional validation

The calibrated model should reproduce distributions rather than one chosen
path. Compare empirical and simulated:

- collateral-return and drawdown distributions;
- cross-asset dependence;
- vault debt and collateral-ratio distributions;
- liquidatable shares;
- liquidation size, timing and completion;
- keeper gas costs;
- DAI peg deviations and recovery;
- bad debt; and
- collateral-level and system-level concentration.

Use graphical checks together with absolute errors, relative errors,
Kolmogorov–Smirnov or Wasserstein distances where appropriate. Statistical
tests must not be used mechanically on very large samples without economic
effect sizes.

### 6.4 Withheld historical validation

At least one stress window and ordinary period must be excluded from fitting.
Run historical replay using only information available before or outside the
withheld window. Evaluate direction, timing, order of magnitude and
distributional coverage rather than demanding exact path replication.

### 6.5 Mechanism validation

Use paired simulations with identical initial states, paths and seeds to
isolate:

- liquidation enabled versus disabled;
- low versus high gas cost;
- unconstrained versus constrained keeper capacity;
- current versus delayed oracle prices;
- peg-recovery mechanism enabled versus disabled; and
- single- versus multi-collateral portfolios.

The sign of each mechanism's effect should be economically coherent before
using the model for policy conclusions.

### 6.6 Multi-seed and convergence validation

Report Monte Carlo uncertainty across a registered seed set. Increase the
number of vaults and simulation replications until key summary statistics are
stable within a pre-defined tolerance. Numerical convergence is distinct from
empirical validity; both are required.

### 6.7 Sensitivity and uncertainty propagation

Vary:

- empirical estimates across bootstrap draws;
- literature inputs across cited ranges;
- behavioural parameters across profile or admissible sets; and
- experimental parameters across pre-registered scenarios.

Report which dissertation conclusions remain invariant and which depend on a
narrow assumption.

### 6.8 Acceptance criteria

Before calibrated counterfactual experiments begin:

- every implemented parameter must appear in the calibration bundle;
- no value may have an unknown provenance class;
- protocol values must match their effective dates;
- empirically estimated values must pass held-out or resampling validation;
- literature and scenario values must have sensitivity cases;
- the model must pass mechanism and numerical convergence checks; and
- remaining material mismatches must be documented as limitations rather than
  hidden through re-tuning.

---

## 7. Complete traceability table

The table lists exact implemented names. Where several names are aliases for
one mechanism, they point to the same subsection.

| Implemented parameter or input | Primary class | Empirical evidence or basis | Derived variable / estimator | Simulator use | Primary validation |
|---|---|---|---|---|---|
| `SimulationConfig.n_steps` | Experimental scenario | Selected hourly horizon | Exact timestamp count; no estimator | Simulation loop length | Path-length and boundary checks |
| `PriceProcessConfig.n_steps` | Experimental scenario | Selected hourly horizon | Same as simulation `n_steps` | Generated path length | Equality with simulation length |
| `SimulationConfig.n_vaults` | Experimental scenario | Phase 1E-B active-vault population and concentration | Convergence-informed population size | Synthetic vault count | Multi-size convergence |
| `SimulationConfig.initial_eth_price` | Empirical/scenario | Phase 1A ETH/USD | Start-time observation or normalised scenario | Legacy ETH initial value | Start-state reconciliation |
| `PriceProcessConfig.initial_price` | Empirical/scenario | Phase 1A collateral prices | Start-time observation | Price generator | First-price equality |
| `CollateralConfig.initial_price` | Empirical/scenario | Phase 1A collateral prices | Start-time observation | Collateral-specific initial value | Initial vault-value check |
| `initial_dai_price` | Empirical/scenario | Phase 1A DAI/USD or peg | Start-time observation or generic peg | Initial DAI market state | First-step alignment |
| `SimulationConfig.liquidation_ratio` | Protocol constant | Phase 1D Spot | `mat / 1e27` | Global fallback and vault threshold | Effective-date and eligibility replay |
| `CollateralConfig.liquidation_ratio` | Protocol constant | Phase 1D Spot by ilk | Effective ratio mapped to class | Collateral override | Exact-ilk mapping |
| `SimulationConfig.oracle_delay_steps` | Empirical/literature/scenario | Oracle updates, Phase 1D mappings, literature | Delay hours/distribution | Market-to-oracle lag | Oracle divergence replay |
| `add_oracle_price.delay_steps` | Empirical/literature/scenario | Same as above | Same delay mapping | Legacy path adapter | Equality with configured delay |
| `SimulationConfig.debt_mean` | Empirical estimate | Phase 1E-B vault states | Mean accrued DAI debt | Gaussian vault generator | Distribution and tail fit |
| `SimulationConfig.debt_std` | Empirical estimate | Phase 1E-B vault states | SD of accrued DAI debt | Gaussian vault generator | Realised dispersion and clipping |
| `SimulationConfig.collateral_ratio_mean` | Empirical estimate | Phase 1A/1D/1E-B | Mean vault collateral ratio | Gaussian vault generator | Distribution and liquidation distance |
| `SimulationConfig.collateral_ratio_std` | Empirical estimate | Phase 1A/1D/1E-B | SD of vault collateral ratio | Gaussian vault generator | Lower-tail and dispersion fit |
| `min_collateral_ratio_buffer` | Experimental scenario | Phase 1E-B lower-tail diagnostic | Chosen clipping buffer | Vault generator safeguard | Clipping-rate report |
| `SimulationConfig.random_seed` | Experimental scenario | Reproducibility design | Registered seed | Simulation RNG | Exact rerun and multi-seed checks |
| `PriceProcessConfig.random_seed` | Experimental scenario | Reproducibility design | Registered seed | Price RNG | Exact rerun |
| vault-generator `random_seed` | Experimental scenario | Reproducibility design | Registered seed | Vault sampling RNG | Exact population rerun |
| `SimulationConfig.collateral_portfolio` | Structural/scenario | Exact-ilk mapping and experiment design | Portfolio object | Multi-collateral configuration | Complete path/parameter coverage |
| `CollateralPortfolioConfig.name` | Structural | Experiment registry | Identifier only | Output/configuration label | Uniqueness |
| `CollateralPortfolioConfig.collaterals` | Structural | Phase 1D/1E scope | Ordered collateral set | Portfolio members | Unique names and complete mappings |
| `CollateralConfig.name` | Structural | Exact-ilk-to-model map | Model collateral label | Price/risk routing | Mapping validation |
| vault `collateral_type` argument | Structural | Exact-ilk-to-model map | Model collateral label | Vault assignment | Mapping validation |
| `CollateralConfig.target_debt_share` | Empirical/scenario | Phase 1E-B debt composition | Debt share by class or counterfactual weight | Portfolio allocation | Realised-share error |
| `LiquidationConfig.liquidation_penalty` | Protocol constant | Phase 1D Dog | `chop / 1e18 - 1` | Global keeper reward fallback | Effective-date check |
| `CollateralConfig.liquidation_penalty` | Protocol constant | Phase 1D Dog by ilk | Effective penalty mapped to class | Collateral override | Exact-ilk mapping |
| `LiquidationConfig.gas_cost` | Empirical estimate | Phase 1C transactions + Phase 1A ETH/USD | Actual gas-cost USD distribution | Keeper-profit cost | Held-out transaction costs |
| `LiquidationConfig.risk_cost_rate` | Empirical/literature | Phase 1C auction residuals and literature | Bounded SMM/residual cost rate | Proportional keeper cost | Participation/outcome fit and sensitivity |
| `LiquidationConfig.max_close_factor` | Empirical model analogue | Phase 1C/1E-B liquidation episodes | Debt-repaid fraction distribution | Global repayment cap | Partial/full liquidation fit |
| `CollateralConfig.max_close_factor` | Empirical model analogue | Phase 1C/1E-B by collateral | Collateral-specific repayment fraction | Collateral override | Collateral-level fit |
| `LiquidationConfig.max_liquidations_per_step` | Empirical estimate | Phase 1C hourly activity | Regime-conditioned throughput/capacity | Shared keeper cap | Backlog and completion fit |
| `ConfidenceConfig.normal_lower_price` | Empirical estimate | Phase 1A DAI/USD | Lower central quantile/classification threshold | Normal-regime boundary | Held-out regime performance |
| `ConfidenceConfig.normal_upper_price` | Empirical estimate | Phase 1A DAI/USD | Upper central quantile/classification threshold | Normal-regime boundary | Above-peg performance |
| `ConfidenceConfig.stress_lower_price` | Empirical estimate | Phase 1A/1C stress | Tail/change-point threshold | Panic price boundary | Held-out depeg detection |
| `ConfidenceConfig.max_normal_liquidatable_share` | Empirical estimate | Phase 1C/1E-B | Ordinary upper quantile/threshold | Normal pressure boundary | Held-out classification |
| `ConfidenceConfig.max_stress_liquidatable_share` | Empirical estimate | Phase 1C/1E-B | Stress upper quantile/threshold | Panic pressure boundary | Held-out classification |
| `ConfidenceConfig.bad_debt_panic_threshold` | Behavioural/scenario | Phase 1C/1E-B | Scale-consistent calibrated threshold | Bad-debt panic trigger | Scale and held-out tests |
| `ConfidenceConfig.normal_confidence` | Behavioural estimate | Phase 1A normal periods | Constrained SMM level | Normal confidence state | Peg dispersion/recovery |
| `ConfidenceConfig.stress_confidence` | Behavioural estimate | Phase 1A/1C stress | Constrained SMM level | Stress confidence state | Withheld stress moments |
| `ConfidenceConfig.panic_confidence` | Behavioural/literature | Sparse severe depegs | Bounded SMM/sensitivity | Panic confidence state | Leave-one-event-out |
| `ConfidenceConfig.panic_selling_multiplier` | Behavioural estimate | Phase 1A/1C severe stress | Constrained SMM | Panic selling pressure | Depth/duration validation |
| `DAIMarketConfig.peg_price` | Protocol/design constant | DAI USD target | No estimator | Peg-gap target | Formula consistency |
| `DAIMarketConfig.price_adjustment_speed` | Behavioural estimate | Phase 1A joined empirical panel | SMM to dynamics | Net-pressure response | Return, variance and half-life |
| `DAIMarketConfig.arbitrage_strength` | Behavioural estimate | Phase 1A below-peg episodes | Regression then SMM | Below-peg demand | Held-out recovery |
| `DAIMarketConfig.above_peg_supply_strength` | Behavioural estimate | Phase 1A above-peg episodes | Asymmetric regression then SMM | Above-peg supply | Held-out correction |
| `DAIMarketConfig.panic_strength` | Behavioural estimate | Phase 1A/1C/1E-B | Joint constrained SMM | Panic supply pressure | Severe-event replay |
| `DAIMarketConfig.noise_std` | Empirical estimate | Phase 1A DAI changes | Residual SD | Random DAI innovation | Residual and volatility checks |
| `DAIMarketConfig.min_price` | Experimental safeguard | Numerical design | Fixed sensitivity bound | Lower clip | Binding-frequency test |
| `DAIMarketConfig.max_price` | Experimental safeguard | Numerical design | Fixed sensitivity bound | Upper clip | Binding-frequency test |
| `DAIMarketConfig.enable_peg_recovery` | Experimental scenario | Mechanism design | Boolean | Recovery switch | Paired mechanism test |
| `DAIMarketConfig.arbitrage_recovery_strength` | Behavioural estimate | Phase 1A recoveries | Nested SMM | Additional recovery pressure | Half-life and overshoot |
| `DAIMarketConfig.policy_feedback_strength` | Behavioural/literature | Phase 1A + Phase 1D policy timing | Event evidence and bounded SMM | Policy recovery pressure | Withheld recovery and zero restriction |
| `DAIMarketConfig.bad_debt_recovery_drag` | Behavioural estimate | Phase 1A/1C/1E-B | Constrained SMM | Bad-debt recovery discount | Interaction moments |
| `DAIMarketConfig.min_recovery_confidence` | Behavioural estimate | Phase 1A recovery classification | Profiled threshold | Recovery eligibility | Held-out classification |
| runtime `execute_liquidations` | Experimental scenario | Mechanism design | Boolean | Enables keeper action | Paired mechanism test |
| runtime `price_path` | Empirical/scenario | Phase 1A | Replay, joint block bootstrap or deterministic path | Exogenous collateral prices | Return/dependence/drawdown fit |
| GBM `mu` | Empirical benchmark | Phase 1A returns | Frequency-consistent mean log return | GBM drift | Generated return fit |
| GBM `sigma` | Empirical benchmark | Phase 1A returns | Frequency-consistent volatility | GBM volatility | Generated variance/tails |
| GBM `dt` | Structural scenario | Time-step definition | Unit conversion | GBM increment | Dimensional validation |
| GBM `floor_price` | Experimental safeguard | Numerical design | Fixed lower bound | Positive-price floor | Binding-frequency test |
| shock `shock_time` | Experimental scenario | Replay timestamp or design | Step offset | Shock onset | Exact application step |
| shock `shock_size` | Empirical/scenario | Phase 1A tails | Conditional quantile or selected stress | Single-asset shock | Severity and drawdown fit |
| `MultiCollateralShockScenario.shock_sizes` | Empirical/scenario | Phase 1A joint tails | Collateral shock mapping | Multi-asset shock | Cross-asset stress fit |
| `crypto_crash_size` | Experimental scenario informed by data | Phase 1A ETH/WBTC tails | Selected conditional severity | Scenario factory | Tail-rank report |
| `stable_depeg_size` | Experimental scenario informed by data | Phase 1A stablecoin tails | Selected conditional severity | Scenario factory | Tail-rank report |
| `pre_shock_drift` | Empirical/scenario | Phase 1A event windows | Pre-window mean or zero restriction | Deterministic price path | Cumulative-return check |
| `post_shock_drift` | Empirical/scenario | Phase 1A event windows | Post-window mean or zero restriction | Deterministic price path | No double-counted recovery |
| `recovery_start` | Empirical/scenario | Phase 1A recovery episodes | Delay to recovery criterion | Recovery path | Duration validation |
| `recovery_end` | Empirical/scenario | Phase 1A recovery episodes | Delay to terminal criterion | Recovery path | Ordering and duration |
| `recovery_fraction` | Empirical/scenario | Phase 1A recovery episodes | Fraction of shock reversed | Recovery endpoint | Endpoint/replay validation |
| adapter `price_col` | Structural | Processed schema | Column mapping | Legacy path adapter | Schema and meaning |
| adapter `oracle_col` | Structural | Processed schema | Column mapping | Legacy oracle adapter | Schema and meaning |

---

## 8. Multi-collateral extension considerations

### 8.1 Preserve exact-ilk provenance

ETH-A, ETH-B, ETH-C, WBTC-A, WBTC-B and WBTC-C must remain distinct in the
empirical layers. Mapping them to ETH and BTC model classes is a documented
model reduction. The calibration bundle must retain:

- exact ilk;
- model collateral class;
- effective activation period;
- wrapper or token provenance;
- source contract;
- aggregation weight; and
- the protocol setting selected for each experiment.

### 8.2 Separate observed composition from counterfactual composition

An empirically observed `target_debt_share` configuration provides the baseline.
Balanced, stable-heavy, BTC-concentrated and other portfolios are
counterfactual experimental scenarios. They should reuse the same estimated
behavioural environment unless the research question explicitly conditions
behaviour on composition.

### 8.3 Estimate dependence jointly

Collateral returns must not be sampled independently. Joint moving blocks
should preserve:

- ordinary ETH–WBTC correlation;
- correlation increases during stress;
- stablecoin depeg dependence;
- volatility clustering; and
- the timing of gas and liquidation pressure where panels overlap.

Counterfactual dependence structures may be imposed as experimental scenarios,
but must be compared with empirical ranges.

### 8.4 Collateral-specific vault distributions

Vault debt and collateralisation should be estimated by exact ilk first and
then mapped to model collateral classes. Pooling is permitted only after
testing whether distributions are sufficiently similar or applying explicit
weights. Small-sample ilks should retain wider uncertainty rather than being
silently assigned ETH estimates.

### 8.5 Collateral-specific protocol settings

Use collateral overrides for liquidation ratios and penalties when the
implemented interface supports them. `max_close_factor` is a reduced-form
liquidation analogue, not a directly observed Maker setting. Parameters that
remain global in the code, including keeper capacity and oracle delay, should
be acknowledged as shared-mechanism restrictions.

### 8.6 Shared keeper capacity and transaction costs

Phase 1C should identify whether simultaneous collateral liquidations compete
for the same transaction and keeper capacity. The primary gas-cost estimate
must use clean successful-Take transactions without duplicated top-level gas.
Other transaction classes should remain available for sensitivity analysis.

### 8.7 Stable collateral

Stable collateral introduces a qualitatively different risk channel. Its
price-path and depeg severity can be estimated from Phase 1A, but vault
behaviour and protocol settings require a corresponding empirical collateral
scope. Where the target Phase 1E-B extraction covers only ETH and WBTC ilks,
STABLE vault parameters remain literature-derived or experimental and must be
labelled accordingly.

### 8.8 Validation by collateral and at system level

Every calibrated experiment should report:

- collateral-level debt and vault counts;
- liquidatable and liquidated positions;
- keeper attempts and capacity limitations;
- collateral sold and debt repaid;
- bad debt;
- DAI peg outcomes; and
- system totals reconciled to the sum of collateral-level results.

A model that matches system totals while misallocating losses between
collateral types has not passed multi-collateral validation.

### 8.9 Current interface limitations

Phase 2 estimation must work with the implemented model unless a later change
is separately authorised. The principal limitations to carry into calibration
are:

- Gaussian marginal vault sampling rather than empirical joint resampling;
- one oracle delay for all collateral;
- one shared keeper-capacity cap;
- a fixed scalar gas cost within a run;
- a close-factor abstraction for auction liquidation;
- latent confidence rather than an observed agent-level belief measure; and
- no direct stable-collateral confidence channel.

These limitations should be tested through sensitivity and reported in the
dissertation. They must not be hidden by selecting convenient parameter values.

---

## 9. Phase 2 reproducibility checklist

Phase 2 is ready to begin only when:

- the representative Phase 1E-B acquisition has passed its validation gates;
- all source paths and checksums are registered;
- exact time and collateral mappings are frozen;
- each implemented parameter has one primary provenance class;
- estimation and withheld-validation windows are fixed;
- transformation code and tests are in place;
- uncertainty and resampling methods are pre-specified;
- a machine-readable calibration-bundle schema exists; and
- no numerical value is inserted into the simulator without a traceable
  parameter record.

The final Phase 2 hand-off should permit an independent researcher to start
from the validated empirical artefacts, reproduce every transformation and
estimate, instantiate the same simulator configuration and rerun the stated
validation tests.

The Terra/CeFi boundary, mutation, ownership and sparse-rate streams have
passed. Exact replay reconciles the closing boundary, and the 649 linked grabs
make close-factor estimation methodologically ready for Phase 2C. The updated
parameter-readiness status is documented in
`phase1e_b_terra_cefi_acquisition_report.md`.

Phase 2C has now completed that review without adopting parameters. The
simulator field is confirmed as a per-vault debt-close fraction, for which the
649 full-position grabs support a protocol-level candidate of `1.0`.
Per-Take auction execution, clustered arrivals and keeper throughput remain
separate quantities with different interface requirements. The stress-share
review preserves USDC/SVB and Terra/CeFi as labelled moderate and severe
evidence rather than pooling them. Full methods and model-interface
recommendations are in
`phase2c_liquidation_parameter_estimation_report.md`.

Tranche D has since implemented the liquidation-arrival part of that interface
as an opt-in hurdle-count process. It preserves `max_close_factor` as a
per-vault close fraction and treats keeper throughput as the distinct
`max_liquidations_per_step` cap. Sequence and auction-execution evidence
remain diagnostic only. See
`tranche_d_liquidation_arrival_and_capacity_report.md`.

The subsequent adoption audit reconciles 56 authoritative parameter
subsections and consolidates all 80 Phase 2A–2C candidate records without
adopting them. It separates configuration-only candidates from distribution,
regime, liquidation and behavioural interface work. The staged decision
framework is in `parameter_adoption_and_model_interface_plan.md`.
