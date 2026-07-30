# Empirical research design

## 1. Purpose of the empirical analysis

The empirical stage should establish that the simulation is not merely a stylised mechanism exercise. Its purpose is to connect the model to observed market and protocol behaviour, assess whether the model can reproduce economically meaningful patterns, and then use the validated model for counterfactual stress testing.

The project should therefore follow the sequence:

> **Historical data → parameter estimation → distributional validation → historical replay → counterfactual stress tests**

The objective is not to claim that the model predicts the exact future DAI price. A more defensible claim is that the simulation:

1. is calibrated using observable protocol and market data;
2. reproduces important distributional and directional features of DAI stress episodes;
3. identifies the mechanisms through which collateral composition, liquidation frictions and keeper capacity affect system resilience; and
4. supports policy-relevant counterfactual comparisons that cannot be observed directly in historical data.

A suitable description of the project is:

> **An empirically calibrated and historically validated agent-based stress-testing model of multi-collateral DAI.**

---

## 2. Core research question

The principal research question should be:

> **How do collateral composition, cross-asset dependence and liquidation frictions jointly affect DAI solvency and peg resilience under market stress?**

This question can be divided into five testable sub-questions.

1. Does multi-collateralisation reduce system-wide bad debt relative to an ETH-only system?
2. Does the diversification benefit weaken when ETH and BTC become more highly correlated during market stress?
3. Does stable collateral reduce crypto-market liquidation risk while introducing stablecoin-depeg contagion risk?
4. Do collateral-specific liquidation parameters improve resilience relative to uniform parameters?
5. Does shared keeper capacity create competition between collateral types during simultaneous liquidations?

---

## 3. Empirical philosophy: estimate distributions, not individual crisis outcomes

The model should not be calibrated by repeatedly changing parameters until it resembles one selected historical event. That would risk event-specific overfitting.

Instead, parameters should be obtained from historical time windows and probability distributions. Crisis events should play one of three roles:

1. **Observations within a stress distribution**
   A crisis contributes to the estimation of tail returns, high-gas conditions, liquidation delays and cross-asset dependence.

2. **Out-of-sample validation episodes**
   A crisis is excluded from calibration and later used to test whether the model reproduces the direction and approximate magnitude of observed stress.

3. **Conditional stress-test templates**
   A historical event defines the broad type of shock, but the precise magnitude and duration are sampled from an estimated conditional distribution.

This gives a clear separation between:

- **calibration**, which estimates model inputs from data;
- **validation**, which evaluates model outputs against withheld observations; and
- **counterfactual analysis**, which changes policy or portfolio settings while holding the estimated environment constant.

---

### 3.1 Representative vault-data methodology

The original Phase 1E design proposed a continuous reconstruction of every
target-ilk vault mutation from the historical activation period through June
2024. Source discovery, three diagnostics and five validated monthly chunks
have completed the methodological purpose of that design: authoritative state
mutations, liquidation annotations, ownership mappings, signed values,
deterministic trace ordering, pagination and resumability have all been
verified.

The dissertation will now use **representative empirical calibration windows**
for high-volume vault data. This is a methodological refinement rather than an
acquisition failure. The validated continuous-acquisition infrastructure and
all completed chunks remain preserved for reproducibility.

The representative design combines:

- ordinary and mature-market vault observations;
- bull-market and multi-collateral expansion;
- prolonged crypto stress;
- stablecoin-led contagion;
- an earlier-system stress comparison; and
- a withheld Liquidations 2.0 validation window.

Continuous hourly panels remain appropriate for compact market, gas and
liquidation-activity aggregates. They identify unconditional regime
probabilities and persistence. Purposefully selected vault windows instead
identify conditional debt, leverage, mutation and owner-response
distributions. Stress windows must therefore not be equally weighted as if
they were a random calendar sample.

The definitive windows, credit controls and parameter-evidence mapping are in
[`docs/calibration/vaults.md`](../calibration/vaults.md).
The subsequent derivation, estimation, uncertainty and validation procedure
for every implemented simulator input is specified in
`docs/calibration/parameter_estimation.md`.

---

## 4. Unit of analysis and simulation frequency

All empirical inputs must be aligned with the simulation time step.

If one simulation step represents one hour, the main empirical data should also be hourly where possible:

- collateral returns;
- DAI price;
- gas cost;
- oracle price updates;
- liquidation opportunities;
- liquidation completion;
- auction delay; and
- keeper activity.

Daily data may still be used for slower-moving variables such as:

- collateral portfolio weights;
- total debt;
- debt ceilings;
- vault population summaries; and
- protocol parameter changes.

Daily volatility should not be inserted directly into an hourly model. Any frequency conversion must be documented and should only be used when higher-frequency data are unavailable.

---

## 5. Empirical data structure

The empirical dataset should be organised into four linked panels.

### 5.1 Market-time panel

One row per time interval, containing:

- ETH market price and return;
- BTC or WBTC market price and return;
- stable collateral price and deviation from par;
- DAI market price and peg deviation;
- realised volatility by collateral;
- cross-asset correlation estimates;
- gas price or transaction-cost proxy;
- market volume or liquidity proxy; and
- market-state classification.

### 5.2 Protocol-time panel

One row per time interval and collateral type, containing:

- collateral value locked;
- outstanding DAI debt;
- collateral debt share;
- debt ceiling;
- liquidation ratio;
- liquidation penalty;
- maximum close factor;
- liquidation volume;
- bad debt;
- active vault count; and
- oracle price.

### 5.3 Vault-level panel

One row per vault observation, containing where available:

- collateral type;
- collateral amount;
- outstanding debt;
- collateral ratio;
- distance to liquidation;
- vault size;
- whether the position was liquidated;
- whether collateral or debt was adjusted before liquidation; and
- realised liquidation outcome.

### 5.4 Liquidation- or auction-level panel

One row per liquidation opportunity or auction, containing where available:

- collateral type;
- debt at risk;
- collateral value;
- expected liquidation discount;
- gas cost;
- auction start and completion time;
- realised debt repaid;
- collateral sold;
- keeper participation;
- number of bids or liquidators;
- liquidation failure;
- keeper profit; and
- realised bad debt.

Not every field must be available in the first empirical implementation. The minimum viable dataset should prioritise the variables that identify parameters already present in the model.

---

## 6. Definition of normal and stress regimes

A regime classification should be defined using a transparent statistical rule rather than named events.

A simple baseline rule may classify an interval as stressed when at least two of the following hold:

- ETH return is below its historical fifth percentile;
- BTC return is below its historical fifth percentile;
- realised crypto volatility is above its historical ninetieth percentile;
- gas cost is above its historical ninetieth percentile;
- DAI absolute peg deviation is above its historical ninetieth percentile;
- liquidation volume is above its historical ninetieth percentile.

The resulting state variable is:

\[
S_t \in \{\text{normal},\text{stress}\}.
\]

A three-state extension may use:

\[
S_t \in \{\text{normal},\text{stress},\text{panic}\}.
\]

However, the two-state design should be preferred initially unless a third regime produces a clearly identifiable empirical improvement.

For each regime, estimate:

- return distributions;
- covariance or correlation matrices;
- gas distributions;
- liquidation intensity;
- keeper capacity;
- auction delay; and
- stablecoin-depeg probability.

The transition probability from state \(i\) to state \(j\) is:

\[
\widehat p_{ij}
=
\frac{\#(S_{t-1}=i,S_t=j)}
{\#(S_{t-1}=i)}.
\]

This captures both the arrival and persistence of market stress.

---

## 7. Descriptive empirical analysis

Before calibrating the simulator, the dissertation should document the principal stylised facts in the data.

### 7.1 Collateral return behaviour

Report for each collateral:

- mean return;
- standard deviation;
- skewness;
- kurtosis;
- minimum return;
- first and fifth percentiles;
- maximum drawdown; and
- realised-volatility distribution.

The purpose is to show why a Gaussian process with one fixed volatility may be inadequate.

### 7.2 Cross-collateral dependence

Estimate dependence separately for:

- the full sample;
- normal periods; and
- stress periods.

At minimum, report Pearson and rank correlations. The key question is whether ETH and BTC dependence rises during stress.

A useful measure is the diversification deterioration:

\[
\Delta \rho_{ij}
=
\rho_{ij}^{\text{stress}}
-
\rho_{ij}^{\text{normal}}.
\]

### 7.3 DAI peg behaviour

Report:

- mean absolute peg deviation;
- maximum positive and negative deviations;
- duration outside selected bands such as \(0.99\)–\(1.01\);
- recovery time after major deviations;
- peg-deviation autocorrelation; and
- relation between DAI deviation, collateral returns, gas and liquidation activity.

The controlled [ETH recovery matrix](../experiments/eth_recovery_matrix.md)
implements the recovery-regime test with four pre-registered collateral paths,
four transparent confidence cases, paired random streams and censored
sustained-recovery estimands. Its result is conditional mechanism evidence,
not a confidence calibration or historical event replay.

### 7.4 Liquidation and keeper behaviour

Report:

- liquidation frequency;
- liquidation volume;
- collateral-specific liquidation share;
- debt repaid;
- failed or delayed liquidation share;
- bad-debt frequency;
- keeper-profit distribution;
- concentration of keeper activity; and
- clearing-time distribution.

### 7.5 Vault risk distribution

Report by collateral type:

- collateral-ratio distribution;
- distance-to-liquidation distribution;
- debt-size distribution;
- share of debt near the liquidation boundary; and
- concentration of debt among large vaults.

This is particularly important because the current stable-depeg scenario produces no liquidation. The empirical analysis must determine whether this follows from realistic collateral-ratio buffers or from an overly safe simulated vault distribution.

---

## 8. Calibration design

### 8.1 Directly observed protocol parameters

Protocol parameters should be taken from the relevant historical settings rather than estimated statistically. These include:

- liquidation ratio;
- liquidation penalty;
- maximum close factor;
- debt ceiling, if incorporated;
- oracle configuration, where modelled; and
- other collateral-specific risk settings.

Historical replay should use the settings that were active during the replay period.

### 8.2 Empirical-distribution parameters

Parameters describing heterogeneous populations should preferably be sampled from empirical distributions rather than represented by one mean value.

Examples include:

- initial vault collateral ratios;
- vault debt sizes;
- collateral amounts;
- liquidation sizes;
- gas costs;
- keeper profits; and
- auction delays.

Where variables are related, joint observations should be sampled together. Debt and collateral ratio, for example, should not be sampled independently if large vaults systematically use different leverage.

### 8.3 Market-path parameters

The preferred baseline for multi-asset market paths is a joint moving-block bootstrap.

For each historical interval, construct the vector:

\[
\mathbf x_t =
\left(
r_{\mathrm{ETH},t},
r_{\mathrm{BTC},t},
r_{\mathrm{STABLE},t},
g_t
\right).
\]

Sample continuous blocks of these vectors rather than sampling each series independently. This preserves:

- short-run volatility clustering;
- contemporaneous cross-asset dependence;
- co-movement between market stress and gas; and
- realistic sequences of returns.

A regime-dependent bootstrap should use separate block pools for normal and stress periods.

### 8.4 Probability parameters

Event probabilities should be estimated as observed frequencies or conditional probabilities.

Examples include:

- probability of moving from normal to stress;
- probability that stress persists;
- probability of stable collateral depegging during stress;
- probability that an eligible vault is liquidated within a given interval;
- probability of keeper participation conditional on expected profitability;
- probability of auction failure conditional on gas and volatility.

### 8.5 Behavioural parameters

Behavioural coefficients should only be estimated when a corresponding observable outcome exists.

Examples include:

- keeper participation estimated with a logit model;
- liquidation completion estimated with a binary-response or hazard model;
- vault top-up behaviour estimated from vault adjustments near the liquidation boundary; and
- DAI price adjustment estimated from the historical relation between peg deviation and subsequent price changes.

A behavioural parameter that cannot be identified from data should be treated as:

1. a fixed modelling assumption;
2. a sensitivity parameter; or
3. a proposed future extension.

It should not be described as empirically estimated.

---

## 9. Validation strategy

Validation should be performed at several levels.

### 9.1 Distributional validation

Compare simulated and empirical distributions for:

- collateral returns;
- realised volatility;
- cross-asset correlations;
- gas;
- vault collateral ratios;
- liquidation volumes;
- bad debt;
- keeper profit; and
- recovery time.

Suitable comparisons include:

- mean and standard deviation;
- quantiles;
- tail exceedance frequencies;
- empirical cumulative distribution functions;
- Kolmogorov–Smirnov distance;
- Wasserstein distance; and
- confidence-interval overlap.

The purpose is not to force every distribution to match perfectly, but to demonstrate that the model produces plausible magnitudes and tails.

### 9.2 Moment validation

Define a set of empirical moments that the model should reproduce:

\[
m^{\text{data}}
=
\begin{bmatrix}
\text{DAI peg-volatility}\\
\text{maximum depeg}\\
\text{liquidation frequency}\\
\text{bad-debt frequency}\\
\text{median clearing time}\\
\text{stress correlation}\\
\text{keeper participation}
\end{bmatrix}.
\]

Compare them with simulated moments:

\[
D(\theta)
=
\left(
m^{\text{sim}}(\theta)-m^{\text{data}}
\right)'
W
\left(
m^{\text{sim}}(\theta)-m^{\text{data}}
\right).
\]

This may be used as a diagnostic even if formal simulated method of moments estimation is not adopted.

### 9.3 Historical replay

Historical replay should input observed exogenous paths, such as collateral prices and gas, while keeping calibrated behavioural and protocol parameters fixed.

The model should then be judged on whether it reproduces:

- the direction of DAI peg pressure;
- the occurrence and ordering of liquidations;
- approximate liquidation intensity;
- the emergence or absence of bad debt;
- recovery timing; and
- collateral contributions to system stress.

The project should not require exact point-by-point replication.

### 9.4 Out-of-sample validation

At least one period or event should be excluded from parameter estimation.

Possible designs include:

- estimate on an earlier period and validate on a later period;
- estimate on normal periods and validate on identified stress periods;
- estimate using ETH and BTC shocks and validate on a stablecoin-depeg episode; or
- rolling-window estimation and validation.

Parameters must not be re-tuned after observing validation results.

---

## 10. Main experimental design

The existing Experiment 06 provides five portfolios and five shocks. These should be converted from purely stylised scenarios into empirically grounded experimental families.

### 10.1 Portfolio family

Current portfolios:

- `eth_only`;
- `crypto_diversified`;
- `balanced`;
- `stable_heavy`; and
- `btc_concentrated`.

For the empirical analysis, each portfolio should be interpreted in one of two ways:

1. a historically observed collateral composition; or
2. a controlled counterfactual composition with fixed total debt and collateral value.

The second interpretation is preferable for causal comparison because only portfolio weights change.

### 10.2 Shock family

Current shocks:

- `eth_specific_crash`;
- `btc_specific_crash`;
- `correlated_crypto_crash`;
- `stable_depeg`; and
- `systemic_shock`.

Each shock should be defined as a conditional distribution rather than one deterministic magnitude.

For example:

- `eth_specific_crash`: ETH return sampled from the ETH tail while BTC and STABLE are sampled from their conditional distributions;
- `btc_specific_crash`: equivalent treatment for BTC;
- `correlated_crypto_crash`: ETH and BTC jointly sampled from stress blocks;
- `stable_depeg`: stable collateral deviation sampled from the historical depeg distribution;
- `systemic_shock`: joint stress block including crypto returns, stable deviation and gas.

This directly addresses the current finding that `systemic_shock` and `correlated_crypto_crash` produce identical outcomes. An empirically meaningful systemic shock should include at least one additional binding channel beyond correlated crypto returns.

### 10.3 Severity family

For each shock, report results by empirical severity quantile, for example:

- moderate stress: fiftieth percentile of the conditional stress distribution;
- severe stress: seventy-fifth percentile;
- extreme stress: ninety-fifth percentile.

An alternative is to use conditional expected shortfall ranges.

### 10.4 Monte Carlo design

For each portfolio–shock–severity combination:

1. draw market and gas paths from the relevant empirical distribution;
2. draw vault populations from calibrated distributions;
3. run multiple random seeds;
4. retain identical random-number streams across policy comparisons where possible; and
5. report the distribution of outcomes rather than one path.

---

## 11. Primary outcome measures

### 11.1 Peg stability

- final DAI price;
- maximum negative peg deviation;
- maximum absolute peg deviation;
- mean absolute peg deviation;
- time outside the selected peg band;
- peg-recovery time;
- recovery half-life; and
- area under peg deviation:

\[
AUPD
=
\sum_t |P^{DAI}_t-1|.
\]

### 11.2 Solvency

- cumulative bad debt;
- peak bad debt;
- bad debt as a share of total debt;
- probability of positive bad debt;
- expected shortfall of bad debt;
- collateral shortfall; and
- share of simulations ending with unresolved debt.

### 11.3 Liquidation efficiency

- liquidatable debt;
- debt repaid;
- liquidation-completion ratio;
- liquidation delay;
- failed or unprofitable attempts;
- collateral sold;
- realised liquidation discount; and
- maximum liquidation backlog.

### 11.4 Keeper outcomes

- cumulative keeper profit;
- profit per unit of debt repaid;
- keeper-participation rate;
- capacity utilisation;
- missed profitable opportunities;
- concentration of liquidation activity; and
- collateral allocation of shared capacity.

### 11.5 Vault outcomes

- number and share of liquidated vaults;
- vault survival rate;
- owner collateral loss;
- debt-weighted liquidation rate;
- liquidation by initial distance to the boundary; and
- loss concentration among large vaults.

### 11.6 Multi-collateral decomposition

For each collateral type:

- debt exposure;
- liquidation volume;
- bad debt;
- keeper profit;
- collateral sold;
- contribution to maximum system stress; and
- exposure-normalised loss.

Exposure-normalised bad debt should be reported as:

\[
\text{NormalisedBadDebt}_i
=
\frac{\text{BadDebt}_i}
{\text{InitialDebtExposure}_i}.
\]

This is necessary because raw losses mechanically increase with collateral exposure.

---

## 12. Hypotheses

### H1: Idiosyncratic diversification

\[
\text{Multi-collateralisation reduces system loss under collateral-specific shocks.}
\]

### H2: Stress correlation

\[
\text{The diversification benefit falls as stress-period ETH–BTC dependence rises.}
\]

### H3: Stable-collateral trade-off

\[
\text{Stable collateral reduces crypto-driven liquidation risk but introduces depeg-contagion risk.}
\]

### H4: Risk-sensitive liquidation design

\[
\text{Collateral-specific liquidation parameters reduce bad debt relative to uniform parameters.}
\]

### H5: Shared keeper capacity

\[
\text{Shared keeper capacity amplifies losses when several collateral types become unsafe simultaneously.}
\]

### H6: Ordinary versus tail resilience

\[
\text{The portfolio that minimises average volatility need not minimise crisis bad debt or peg-recovery time.}
\]

---

## 13. Robustness analysis

The empirical conclusions should survive the following checks.

### 13.1 Alternative estimation windows

Re-estimate parameters using:

- shorter and longer windows;
- pre- and post-major protocol changes;
- normal-only windows;
- rolling windows; and
- windows excluding the largest crisis.

### 13.2 Alternative regime thresholds

Test stress definitions based on:

- fifth versus first return percentiles;
- ninetieth versus ninety-fifth volatility percentiles;
- one versus multiple stress indicators; and
- two-state versus three-state classification.

### 13.3 Alternative block lengths

For the bootstrap, test several block lengths to ensure results are not driven by one arbitrary choice.

### 13.4 Alternative vault distributions

Compare:

- empirical joint bootstrap;
- fitted parametric distributions;
- debt-weighted sampling; and
- stressed initial collateral-ratio distributions.

### 13.5 Parameter uncertainty

Draw estimated coefficients from their sampling distributions or evaluate confidence-interval bounds.

### 13.6 Multiple seeds

Report medians, interquartile ranges, fifth and ninety-fifth percentiles, and failure probabilities.

### 13.7 Equivalent-path detection

The current project status notes that `systemic_shock` and `correlated_crypto_crash` produce identical outcomes. The empirical pipeline should automatically test whether:

- scenario price paths are identical;
- oracle paths are identical;
- liquidation triggers are identical; and
- final result files differ only by scenario label.

Equivalent scenarios should be diagnosed rather than interpreted as independent evidence.

---

## 14. Identification and overfitting safeguards

The following rules should govern model development.

1. Every freely calibrated parameter must have a corresponding empirical variable or target moment.
2. Parameters without an identifiable empirical counterpart must be fixed or subjected to sensitivity analysis.
3. The same event must not be used simultaneously for unrestricted calibration and claimed validation.
4. Calibration should target several moments, not one final outcome.
5. Behavioural parameters should be kept parsimonious.
6. Validation results should be reported even when fit is imperfect.
7. Policy experiments should use parameters fixed before the counterfactual comparison.
8. New mechanisms should only be added when they address a demonstrated empirical failure of the existing model.

These safeguards are especially important in an agent-based model because different parameter combinations may produce similar aggregate outputs.

---

## 15. Recommended dissertation structure

### Chapter 4: Data and empirical calibration

1. Data sources and sample construction
2. Collateral and DAI price behaviour
3. Normal and stress regimes
4. Vault and liquidation distributions
5. Protocol parameters
6. Statistical estimation methods
7. Calibration results

### Chapter 5: Model validation

1. Distributional validation
2. Moment comparison
3. Historical replay
4. Out-of-sample validation
5. Validation limitations

### Chapter 6: Counterfactual experiments

1. Collateral composition
2. Idiosyncratic collateral shocks
3. Correlated crypto shocks
4. Stable-collateral depegs
5. Systemic shocks
6. Keeper-capacity constraints
7. Collateral-specific risk parameters

### Chapter 7: Policy implications

1. Diversification versus contagion
2. Collateral concentration limits
3. Risk-sensitive liquidation settings
4. Keeper-capacity resilience
5. Capital efficiency versus solvency

---

## 16. Recommended implementation sequence

The next empirical work should proceed in this order:

1. define the simulation frequency and empirical sample period;
2. obtain historical collateral, DAI and gas series;
3. construct normal and stress regimes;
4. estimate joint market and gas distributions;
5. obtain protocol parameters by collateral and date;
6. acquire representative vault snapshots and mutation windows, with an
   authoritative opening state for every level-based observation;
7. calibrate existing liquidation and keeper parameters;
8. diagnose why the current stable-depeg shock is non-binding;
9. replace deterministic shocks with conditional empirical distributions;
10. run multi-seed distributional validation;
11. reserve the designated FTX window, and at least one alternative window in
    robustness checks, for out-of-sample validation; and
12. conduct policy counterfactuals with calibrated parameters held fixed.

---

## 17. Intended empirical contribution

The empirical contribution should not be stated as simply showing that multi-collateral DAI is safer than ETH-only DAI.

A stronger and more defensible conclusion is:

> **Multi-collateralisation improves DAI resilience only when diversification remains effective under stress, collateral-specific risks are appropriately constrained, and liquidation capacity is sufficient. Otherwise, concentration risk may be replaced by correlation risk, stablecoin contagion and competition for keeper capacity.**
