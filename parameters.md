# Parameter Acquisition Plan for the Multi-Collateral DAI Simulation

## 1. Scope

This document maps the parameters currently identifiable from `PROJECT_STATUS.md` and the established model architecture to defensible empirical acquisition methods.

The present model is already sufficiently complex for the dissertation's empirical stage. It contains:

- multi-asset market and oracle price paths;
- ETH, BTC and STABLE collateral;
- heterogeneous vault populations;
- portfolio allocation by target debt share;
- collateral-specific liquidation ratios;
- collateral-specific liquidation penalties;
- collateral-specific maximum close factors;
- shared keeper capacity;
- DAI price and confidence dynamics;
- five portfolio configurations;
- five shock configurations; and
- system- and collateral-level output tables.

Accordingly, the core empirical programme should calibrate the existing model rather than add a large number of new mechanisms.

Any proposed additions are placed in **Section 8: Parameters requiring discussion before implementation**. They should not be added silently.

The reproducible Phase 2 procedure that connects these acquisition methods to
every implemented simulator field is maintained in
`docs/parameter_estimation_plan.md`. It defines parameter
provenance, estimators, uncertainty and validation without assigning values.

---

## 2. Classification of parameter-acquisition methods

Each parameter should be assigned to one of the following classes.

### Class A — Direct protocol observation

The parameter is explicitly set by the protocol or governance process and should be read directly for the relevant collateral and historical date.

Examples:

- liquidation ratio;
- liquidation penalty;
- debt ceiling; and
- auction settings.

### Class B — Direct empirical measurement

The parameter is calculated directly from observed data without fitting a structural model.

Examples:

- collateral portfolio weights;
- historical gas quantiles;
- observed liquidation volume;
- empirical vault debt distribution; and
- observed oracle delay.

### Class C — Statistical estimation

The parameter is inferred from a time series, cross-sectional distribution or probability model.

Examples:

- return volatility;
- stress-transition probability;
- keeper-participation probability;
- price-recovery coefficient; and
- liquidation-delay distribution.

### Class D — Calibrated behavioural parameter

The parameter is not directly observable but has a clear empirical output or target moment. It may be estimated by minimum-distance calibration, simulated method of moments or a simple transparent grid search.

Examples:

- DAI demand-response strength;
- confidence sensitivity; and
- panic-selling response.

### Class E — Fixed modelling assumption or sensitivity parameter

The parameter is not empirically identifiable with the available data. It should be fixed transparently and varied in robustness tests.

It must not be described as empirically estimated.

---

### 2.1 Revised Phase 1E evidence design

Phase 1E no longer seeks an exhaustive 2019–2024 vault census. Phase 1E-A has
completed methodology validation; Phase 1E-B will estimate vault behaviour from
representative ordinary and stressed windows. All existing diagnostics, chunks,
checksums and acquisition controls remain valid.

Parameter provenance must distinguish four dissertation-facing evidence
classes:

| Parameter group | Primary evidence |
|---|---|
| Return, gas, peg and market-regime distributions | Empirical estimation from continuous Phase 1A and Phase 1B panels |
| Liquidation arrival, auction outcomes and keeper gas | Empirical estimation from Phase 1C |
| Liquidation ratios, penalties, debt limits, dust and auction settings | Protocol constants from Phase 1D |
| Vault size, leverage, borrowing, repayment and owner intervention | Empirical estimation from Phase 1E-B representative snapshots and mutation windows |
| Simulated vault count, controlled portfolio shares, shock onset and random seed | Scenario assumptions |
| Confidence, panic and unobserved keeper-cost components | Empirical-moment calibration, literature bounds and scenario sensitivity, with the source labelled explicitly |

Purposefully selected Phase 1E-B windows estimate conditional behaviour. They
must not be used alone to estimate unconditional crisis arrival rates. The
complete mapping, selected windows and expected credits are maintained in
`docs/phase1e_representative_calibration_strategy.md`.

---

## 3. Market and price-process parameters

### 3.1 Initial market price by collateral

**Likely model object**

- initial ETH price;
- initial BTC price;
- initial STABLE price.

**Preferred method**

Class B: direct empirical measurement.

For a historical replay, use the observed market price at the first simulation timestamp.

For stochastic Monte Carlo experiments, use either:

- the market price at the start of the estimation or evaluation period; or
- a normalised starting value, such as 1.0, when outcomes are scale-invariant.

**Recommended rule**

Use observed initial prices for historical replay and clearly labelled normalised prices for generic stress tests.

**Overfitting risk**

Low. The initial price should not be adjusted to improve simulated outcomes.

---

### 3.2 Market return distribution by collateral

**Likely model object**

- price drift;
- volatility;
- random price innovation;
- collateral-specific price path.

**Preferred method**

Class C: joint empirical moving-block bootstrap.

Construct aligned return vectors:

\[
\mathbf r_t =
\left(
r_{\mathrm{ETH},t},
r_{\mathrm{BTC},t},
r_{\mathrm{STABLE},t}
\right).
\]

Sample continuous blocks from the historical data, preserving contemporaneous dependence and volatility clustering.

A parametric alternative is a multivariate volatility model, but the bootstrap should be the baseline because it is more transparent and preserves empirical tails.

**Outputs to store**

- normal-regime return blocks;
- stress-regime return blocks;
- selected block length;
- unconditional and conditional quantiles;
- normal and stress covariance matrices.

**Robustness**

Test alternative sample windows and block lengths.

---

### 3.3 Drift or expected return

**Likely model object**

- collateral price-process drift.

**Preferred method**

Class C: historical mean or median return over the estimation window.

However, for short stress-test horizons, expected return is usually small relative to volatility and may be set to zero.

**Recommended rule**

Use zero drift in short-horizon stress tests unless the empirical horizon makes drift economically material. Estimate drift only for longer simulations.

**Overfitting risk**

Moderate because short-sample mean returns are unstable.

---

### 3.4 Volatility by collateral

**Likely model object**

- ETH volatility;
- BTC volatility;
- STABLE volatility;
- stochastic price noise.

**Preferred method**

Class C: directly estimate at the simulation frequency.

Possible measures:

- standard deviation of log returns;
- realised volatility;
- exponentially weighted volatility; or
- regime-specific volatility.

**Recommended rule**

Use separate normal- and stress-regime distributions rather than one full-sample value.

**Do not**

Insert daily volatility directly into an hourly model without a documented conversion.

---

### 3.5 Cross-collateral dependence

**Likely model object**

- correlation between ETH, BTC and STABLE paths;
- joint shock dependence.

**Preferred method**

Class C: estimate joint dependence from aligned returns.

At minimum calculate:

- full-sample correlation;
- normal-regime correlation;
- stress-regime correlation; and
- rank correlation.

**Recommended implementation**

Prefer joint block sampling over manually imposing a correlation matrix. The estimated matrices remain useful for reporting and diagnostic validation.

**Key empirical test**

\[
\Delta \rho_{\mathrm{ETH,BTC}}
=
\rho^{\mathrm{stress}}_{\mathrm{ETH,BTC}}
-
\rho^{\mathrm{normal}}_{\mathrm{ETH,BTC}}.
\]

---

### 3.6 Shock-arrival probability

**Likely model object**

- probability of an ETH-specific crash;
- probability of a BTC-specific crash;
- probability of a correlated crypto crash;
- probability of a stable depeg;
- probability of a systemic shock.

**Preferred method**

Class C: historical exceedance frequency or regime-transition model.

First define each shock independently of named events. For example:

\[
I^{ETH}_t
=
\mathbb I
\left(
r^{ETH}_t < q^{ETH}_{0.05}
\right).
\]

Then estimate:

\[
\widehat p_{ETH}
=
\frac{\sum_t I^{ETH}_t}{T}.
\]

For regime-based simulation, estimate transition probabilities between normal and stress states.

**Important distinction**

The unconditional probability of a rare event and the conditional distribution used in a forced stress test are different objects.

---

### 3.7 Shock magnitude

**Current status**

Shock magnitudes are currently stylised and not empirically calibrated.

**Preferred method**

Class C: sample from the conditional empirical tail distribution.

For an ETH-specific crash:

\[
r^{ETH}_t
\mid
r^{ETH}_t < q^{ETH}_{\alpha}.
\]

For a correlated crypto crash, jointly sample ETH and BTC from historical stress blocks.

For a stable depeg, sample the stable-price deviation and recovery path from historical depeg intervals.

**Recommended reporting**

Use empirical severity quantiles rather than one arbitrary value:

- median conditional stress;
- seventy-fifth percentile;
- ninety-fifth percentile.

**Do not**

Select one crisis return and treat it as the general crash parameter.

---

### 3.8 Shock timing

**Likely model object**

- `shock_step`;
- onset time.

**Preferred method**

Depends on experiment type.

- Historical replay: Class B, use the observed timestamp.
- Unconditional Monte Carlo: Class C, draw arrival from estimated hazard or transition probability.
- Conditional stress test: Class E, set a common onset step for comparability.

**Recommended rule**

A fixed shock step is acceptable in controlled counterfactual experiments because it is an experimental design choice, not a claimed empirical estimate.

---

### 3.9 Shock duration and recovery

**Likely model object**

- permanent price jump;
- temporary depeg;
- post-shock recovery rate;
- recovery horizon.

**Preferred method**

Class C: estimate from post-shock price dynamics.

For a deviation \(d_t=P_t-P^*\), estimate:

\[
d_t = \rho d_{t-1}+\varepsilon_t.
\]

The implied half-life is:

\[
HL =
\frac{\ln(0.5)}
{\ln|\rho|}.
\]

Alternatively, draw complete historical stress blocks, which allows duration and recovery to remain endogenous to the sampled path.

**Recommended baseline**

Use block paths. Use an estimated recovery coefficient only when the simulator requires a parametric process.

---

### 3.10 Stable-collateral price noise

**Likely model object**

- STABLE ordinary volatility.

**Preferred method**

Class C: estimate from non-depeg intervals only.

The stable process should distinguish:

1. ordinary small deviations around par; and
2. rare depeg episodes.

A mixture representation is:

\[
r_t^{STABLE}
\sim
(1-p_D)F_{\mathrm{ordinary}}
+
p_DF_{\mathrm{depeg}}.
\]

**Reason**

Using a single full-sample volatility may underestimate depeg tails while overstating ordinary noise.

---

### 3.11 Market price versus oracle price

**Likely model object**

- market path by collateral;
- oracle path by collateral.

**Preferred method**

Class B or C.

If historical oracle data are available, measure the timestamp difference and price discrepancy directly.

Otherwise estimate:

- update interval;
- median delay;
- upper-tail delay;
- probability of stale price during stress.

**Current model limitation**

One oracle delay applies to all collateral paths.

**Baseline recommendation**

Retain the shared delay initially, estimate it from observed oracle behaviour, and test low, central and high empirical quantiles.

Collateral-specific oracle delays are discussed separately in Section 8.

---

## 4. Vault-population parameters

### 4.1 Number of vaults

**Likely model object**

- total simulated vault count;
- count by collateral type.

**Preferred method**

Class E for computational scale, with empirical weighting.

The absolute simulated count need not equal the full on-chain population if each simulated vault represents a weighted group.

**Recommended rule**

Choose a computationally manageable count, then preserve:

- collateral debt shares;
- debt-size distribution;
- collateral-ratio distribution; and
- concentration measures.

**Validation**

Check that increasing the simulated vault count does not materially change aggregate results.

---

### 4.2 Collateral-type allocation

**Current status**

ETH, BTC and STABLE coexist. Portfolio allocation uses target debt shares.

**Preferred method**

- Historical baseline: Class B, use observed debt shares by collateral.
- Counterfactual portfolios: Class E, use controlled target shares.

**Current portfolio labels**

- `eth_only`;
- `crypto_diversified`;
- `balanced`;
- `stable_heavy`;
- `btc_concentrated`.

**Recommended rule**

Maintain the current five portfolios, but document whether each is:

- historically observed;
- approximately historically inspired; or
- purely counterfactual.

Hold total initial system debt and collateral value constant across controlled portfolio comparisons.

---

### 4.3 Initial vault debt

**Likely model object**

- `debt_dai`;
- total system debt;
- vault-level debt distribution.

**Preferred method**

Class B or C: empirical joint distribution by collateral type and
representative regime.

Use a debt-weighted or vault-weighted empirical sample depending on the question.

Because debt distributions are usually skewed, avoid a simple normal distribution.

Cross-sectional snapshots must include inactive vaults where possible. A
mutation-only sample would over-represent owners who adjust positions.

**Recommended implementation**

Jointly sample:

\[
(\text{collateral type},\text{debt},\text{collateral ratio}).
\]

**Scaling**

If the simulated system is smaller than the observed system, apply a documented scale factor while preserving relative distributions.

---

### 4.4 Initial collateral amount

**Likely model object**

- `collateral_amount`.

**Preferred method**

Derive from sampled debt, sampled collateral ratio and initial market price:

\[
CollateralAmount_{v,0}
=
\frac{CR_{v,0}\times Debt_{v,0}}
{Price_{i,0}}.
\]

This is preferable to sampling collateral amount independently because it maintains internal accounting consistency.

---

### 4.5 Initial collateral ratio

**Likely model object**

- vault collateral ratio;
- distance to liquidation.

**Preferred method**

Class B or C: empirical distribution by collateral type and representative
regime, using an authoritative opening snapshot or validated level observation.

Prefer joint bootstrap with vault debt. If only summary data are available, fit a positive skewed distribution to the distance above the liquidation ratio:

\[
Buffer_{v,0}
=
CR_{v,0}-LR_i > 0.
\]

**Current research need**

Diagnose whether the STABLE vault collateral-ratio distribution is so conservative that realistic depegs cannot trigger liquidation.

**Recommended outputs**

- debt-weighted median collateral ratio;
- lower quantiles;
- share of debt within 5%, 10% and 20% of the liquidation boundary.

---

### 4.6 Target debt shares

**Current model object**

- target debt share by collateral in each portfolio.

**Preferred method**

Class B for historical calibration and Class E for counterfactuals.

**Recommended controls**

Across portfolios, keep fixed:

- total system debt;
- total initial collateral value;
- vault count or weighted vault mass;
- common market starting date; and
- common random seeds.

This isolates the effect of composition.

---

### 4.7 Vault heterogeneity and random seed

**Likely model object**

- random generator seed;
- distributional sampling parameters.

**Preferred method**

The seed is Class E and has no empirical value.

**Recommended rule**

Use many seeds and report outcome distributions. For paired policy comparisons, use common random numbers so that each policy faces the same sampled market and vault conditions.

---

## 5. Collateral-specific risk and liquidation parameters

### 5.1 Liquidation ratio

**Current model object**

- collateral-specific liquidation ratio.

**Preferred method**

Class A: direct protocol observation by collateral and date.

**Historical replay**

Use the ratio in force during the replay period.

**Counterfactual analysis**

Vary around the observed baseline to examine the solvency–capital-efficiency trade-off.

**Do not**

Estimate the liquidation ratio from historical liquidations; it is a governance setting, not a behavioural parameter.

---

### 5.2 Liquidation penalty

**Current model object**

- collateral-specific liquidation penalty.

**Preferred method**

Class A: direct protocol observation by collateral and date.

**Counterfactual analysis**

Use observed values as the baseline and test a limited empirical or governance-relevant range.

**Validation target**

Check whether the model produces plausible owner losses and keeper incentives under the observed penalty.

---

### 5.3 Maximum close factor

**Current model object**

- collateral-specific maximum close factor.

**Preferred method**

Class A if it corresponds directly to a protocol setting.

If the implemented close factor is a modelling simplification rather than a direct Maker parameter, classify it as Class E and document the mapping.

**Sensitivity**

Test whether bad debt and liquidation backlog are sensitive to partial versus near-complete liquidation.

---

### 5.4 Liquidation eligibility

**Likely model object**

A vault becomes liquidatable when:

\[
CR_{v,t}<LR_i.
\]

**Preferred method**

The rule itself is Class A or a direct protocol mapping.

No statistical calibration is required.

**Validation**

Test that the implementation reproduces known boundary behaviour and uses the correct market or oracle price.

---

### 5.5 Liquidation discount or collateral-sale price

**Likely model object**

- price discount;
- liquidation proceeds;
- collateral recovered.

**Preferred method**

Class B or C: empirical distribution conditional on collateral type, gas, volatility and liquidation size.

A simple regression may be:

\[
Discount_j
=
\alpha_i
+\beta_1 Gas_j
+\beta_2 Volatility_j
+\beta_3 Size_j
+\varepsilon_j.
\]

If the current implementation derives discount mechanically from the penalty and price, retain that structure and validate the implied discount distribution rather than adding a new parameter immediately.

---

### 5.6 Liquidation delay

**Likely model object**

- delay before liquidation;
- auction or execution delay.

**Preferred method**

Class B or C: empirical time from eligibility or auction start to completion.

Estimate separately by collateral and regime where sufficient data exist.

**Simple baseline**

Use a conditional empirical distribution:

\[
D_j
\sim
F_D(
d\mid
S_t,\text{collateral type}
).
\]

**Current model implication**

If delay is already represented indirectly through keeper capacity, avoid adding a second delay mechanism unless data show that capacity alone cannot reproduce observed timing.

---

### 5.7 Realised bad-debt accounting

**Current status**

Changes to realised bad-debt accounting are reserved for user discussion.

**Preferred method**

First classify the current accounting identity rather than introducing a new parameter.

Validate that:

\[
\text{Debt at liquidation}
=
\text{Debt repaid}
+
\text{Realised bad debt}
\]

subject to any fees or recovered collateral explicitly included in the model.

**Recommendation**

Do not change the accounting rule during parameter calibration. Treat any change as a model-design decision requiring separate discussion.

---

## 6. Keeper parameters

### 6.1 Shared keeper capacity

**Current model object**

- one shared capacity across collateral types.

**Preferred method**

Class B or C.

Potential empirical proxies:

- maximum liquidation count completed per interval;
- maximum DAI debt cleared per interval;
- high quantiles of completed liquidation value during high-demand periods; and
- number of active liquidator addresses.

Observed completed volume is demand-constrained, so it is not a direct measure of maximum capacity.

**Recommended baseline**

Estimate effective capacity from intervals with substantial liquidation demand, and use:

- central estimate;
- lower stress quantile; and
- upper quantile.

**Current research reservation**

Any change to how keeper capacity is measured should be discussed before implementation.

---

### 6.2 Keeper capacity unit

**Likely modelling choice**

Capacity may be measured as:

- number of vaults per step;
- debt value per step; or
- collateral value per step.

**Preferred method**

Class E unless the existing implementation has a direct empirical unit.

**Recommended rule**

Debt value per step is generally more comparable across heterogeneous vault sizes. However, changing the existing unit would alter the mechanism and should be discussed first.

---

### 6.3 Keeper participation or profitability threshold

**Likely model object**

- minimum profitable liquidation;
- probability of execution;
- unprofitable attempt count.

**Preferred method**

If the current model uses a deterministic profitability rule, obtain the inputs directly:

- liquidation reward or discount;
- gas cost;
- debt size; and
- collateral value.

Then participation follows mechanically from:

\[
ExpectedProfit
=
ExpectedRevenue
-
GasCost
-
OtherExecutionCosts.
\]

If a probabilistic participation layer already exists, estimate it using a logit model:

\[
P(Participate_j=1)
=
\Lambda(
\beta_0
+\beta_1 ExpectedProfit_j
-\beta_2 Volatility_j
+\beta_3 Liquidity_j
).
\]

**Recommendation**

Do not add a new stochastic participation coefficient unless the deterministic model fails validation.

---

### 6.4 Gas cost

**Likely model object**

- gas cost per liquidation;
- low-, medium- and high-gas scenarios.

**Preferred method**

Class B or C.

Estimate gas distributions at the simulation frequency and condition them on market regime:

\[
G_t\sim F_G(g\mid S_t).
\]

If transaction gas usage is known, convert gas price into a currency cost consistently.

**Recommended replacement for stylised scenarios**

Use empirical quantiles such as:

- low: twenty-fifth percentile;
- central: median;
- high: ninetieth percentile;
- extreme: ninety-ninth percentile.

These labels should be derived from the estimation window rather than selected manually.

---

### 6.5 Keeper profit

**Likely model object**

- realised keeper profit;
- cumulative keeper profit.

**Preferred method**

Keeper profit is primarily an output, not a free input.

Validate the distribution against observed liquidation proceeds and execution costs.

If the model includes an exogenous profit margin, classify it as Class D or E and justify it separately.

---

### 6.6 Unprofitable liquidation attempts

**Current output**

The wider project already reports unprofitable attempts.

**Preferred method**

This is an output to validate, not a parameter.

Empirical comparison may use the share of opportunities for which expected proceeds do not cover gas and execution costs.

---

## 7. DAI market and confidence parameters

These parameters are part of the established project architecture, although `PROJECT_STATUS.md` focuses mainly on the multi-collateral extension.

### 7.1 Initial DAI price

**Preferred method**

Class B: observed DAI market price at the first timestamp for historical replay.

Use 1.0 for normalised counterfactual experiments.

---

### 7.2 Baseline DAI price noise

**Likely model object**

- market noise in the DAI price-update equation.

**Preferred method**

Class C: estimate from DAI returns during normal periods after accounting for predictable peg correction.

A simple model is:

\[
\Delta p_t^{DAI}
=
\alpha
+\phi(p_{t-1}^{DAI}-1)
+\varepsilon_t.
\]

Use the residual distribution for baseline noise.

**Recommended rule**

Estimate normal- and stress-regime residual distributions if sufficient data exist.

---

### 7.3 Peg-reversion or arbitrage strength

**Likely model object**

- demand response below the peg;
- selling response above the peg;
- peg-correction coefficient.

**Preferred method**

Class C or D.

Estimate:

\[
\Delta d_t
=
\alpha+\phi d_{t-1}+\varepsilon_t,
\qquad
d_t=P_t^{DAI}-1.
\]

The coefficient \(\phi\) provides an empirical starting point for peg reversion.

If the simulated mechanism is nonlinear, calibrate its coefficient to match:

- DAI recovery half-life;
- mean absolute deviation; and
- duration outside the peg band.

**Overfitting safeguard**

Do not calibrate only to one event's final DAI price.

---

### 7.4 Above-peg and below-peg asymmetry

**Likely model object**

- separate demand or price-pressure coefficients above and below one dollar.

**Preferred method**

Class C: threshold regression.

Estimate separately:

\[
\Delta d_t
=
\phi_-d_{t-1}\mathbb I(d_{t-1}<0)
+
\phi_+d_{t-1}\mathbb I(d_{t-1}>0)
+\varepsilon_t.
\]

Retain separate coefficients only if the data support meaningful asymmetry. Otherwise simplify to one peg-reversion parameter.

---

### 7.5 Confidence level or regime

**Likely model object**

- normal, stress and panic confidence states;
- numerical confidence values.

**Preferred method**

The state may be Class C, but the numerical scale is usually Class D or E.

Two defensible approaches are available.

#### Proxy-index approach

Construct a confidence proxy from observable variables such as:

- absolute DAI peg deviation;
- DAI volatility;
- bad-debt ratio;
- liquidation backlog; and
- crypto-market stress.

Estimate how the proxy changes with system conditions.

#### Regime approach

Estimate normal and stress states using threshold rules or a hidden-state model. Map each state to a model confidence value by matching DAI response moments.

**Recommendation**

Retain the current state structure initially. Do not add a more complex latent-state model unless the empirical results justify it.

---

### 7.6 Confidence sensitivity to bad debt

**Likely model object**

- effect of bad debt on confidence or panic pressure.

**Preferred method**

Class D: calibrate to the relationship between observed DAI deviation and protocol-stress proxies.

Possible target moments:

- DAI response following increases in liquidation shortfall;
- maximum depeg;
- recovery half-life; and
- persistence of below-peg pressure.

**Limitation**

Bad debt is rare, so the coefficient may be weakly identified. Report a range and sensitivity results rather than false precision.

---

### 7.7 Confidence sensitivity to collateral shocks

**Likely model object**

- confidence decline after ETH or broader market shocks.

**Preferred method**

Class C or D.

Estimate DAI price or flow response to:

- ETH and BTC returns;
- realised volatility;
- stablecoin deviations; and
- liquidation activity.

Avoid separate coefficients for every collateral unless the data contain enough independent episodes to identify them.

---

### 7.8 Confidence recovery

**Likely model object**

- recovery from panic or stress towards normal confidence.

**Preferred method**

Class C or D.

Estimate an autoregressive recovery coefficient or calibrate to observed DAI recovery duration.

Use:

\[
C_t-\bar C
=
\rho_C(C_{t-1}-\bar C)+\varepsilon_t.
\]

The implied recovery half-life should be reported.

---

### 7.9 Panic-selling pressure

**Likely model object**

- coefficient linking confidence, bad debt or depeg to selling pressure.

**Preferred method**

Class D.

Calibrate to several moments jointly:

- maximum negative depeg;
- area under peg deviation;
- recovery time;
- DAI volatility during stress; and
- asymmetry between negative and positive deviations.

**Recommended treatment**

Use a parsimonious single coefficient or one normal/stress pair. Avoid collateral-specific panic coefficients unless empirically necessary.

---

### 7.10 Direct stable-depeg transmission to DAI demand or confidence

**Current status**

This channel does not yet exist and is explicitly reserved for user discussion.

**Classification**

Proposed new parameter; see Section 8.

It must not be introduced as part of routine calibration.

---

## 8. Parameters requiring discussion before implementation

The present model is complex enough for the main empirical analysis. The following additions may be economically useful, but each changes the mechanism and should be agreed before coding.

### 8.1 Direct stable-collateral contagion coefficient

**Motivation**

The current stable-depeg scenario produces no liquidation or bad debt, and the stable component is not materially binding in `systemic_shock`.

A stable depeg may affect DAI even without immediately liquidating stable-backed vaults by changing:

- confidence in DAI backing;
- demand for DAI;
- redemption behaviour; or
- perceived collateral quality.

**Possible parameter**

\[
\gamma_{stable}
=
\text{effect of stable-collateral depeg on DAI demand or confidence}.
\]

**Possible empirical acquisition**

Class C or D: estimate DAI response to stable collateral price deviations, controlling for crypto returns and market stress.

**Decision required**

Whether this transmission belongs within the intended model scope or should remain a limitation.

---

### 8.2 Collateral-specific oracle delay

**Motivation**

The current model applies one oracle delay to every collateral.

Different collateral markets and oracle feeds may exhibit different update timing or staleness.

**Possible parameters**

\[
Delay_{\mathrm{ETH}},
\quad
Delay_{\mathrm{BTC}},
\quad
Delay_{\mathrm{STABLE}}.
\]

**Possible empirical acquisition**

Class B: observed oracle update intervals and market–oracle divergence by collateral.

**Decision required**

Whether the empirical gain justifies three separate delay processes.

---

### 8.3 Endogenous keeper-capacity allocation rule

**Motivation**

Shared capacity exists, but a keeper may prioritise collateral with the highest expected profit, lowest inventory risk or greatest liquidity.

**Possible parameter**

A collateral-priority score:

\[
Score_{i,t}
=
\beta_1 ExpectedProfit_{i,t}
-\beta_2 Risk_{i,t}
+\beta_3 Liquidity_{i,t}.
\]

**Possible empirical acquisition**

Class C or D from observed liquidation ordering and keeper participation.

**Decision required**

Whether shared capacity should remain first-come-first-served or become economically allocated.

---

### 8.4 Collateral-specific market liquidity or slippage

**Motivation**

ETH, BTC and stable collateral may generate different liquidation proceeds for the same notional size.

**Possible parameters**

- market depth;
- price-impact coefficient; and
- slippage distribution.

**Possible empirical acquisition**

Class C from order-book or decentralised-exchange data.

**Decision required**

This may add substantial data and modelling complexity. It should only be added if liquidation discount cannot otherwise be validated.

---

### 8.5 Vault-owner intervention probability

**Motivation**

Vault owners may add collateral or repay debt before liquidation.

**Possible parameter**

\[
P(\text{intervene})
=
\Lambda(
\beta_0
+\beta_1 DistanceToLiquidation
+\beta_2 DebtSize
+\beta_3 Volatility
).
\]

**Possible empirical acquisition**

Class C from vault-level transaction histories.

**Decision required**

Whether owner behaviour is central to the dissertation or outside the intended liquidation-focused scope.

---

### 8.6 Time-varying collateral portfolio composition

**Motivation**

Current Experiment 06 compares fixed portfolio compositions.

In reality, collateral shares change over time.

**Possible process**

Portfolio weights evolve from observed historical transitions or an estimated Markov process.

**Decision required**

For controlled counterfactual experiments, fixed weights are preferable. Time-varying weights should be considered only for historical system replay.

---

## 9. Parameters that should remain outputs rather than inputs

The following should not be calibrated as free inputs unless the code explicitly requires a structural parameter behind them:

- final DAI price;
- maximum peg deviation;
- cumulative bad debt;
- debt repaid;
- liquidation volume;
- number of liquidated vaults;
- keeper profit;
- unprofitable attempts;
- recovery time;
- system collateral ratio;
- share liquidatable;
- exposure-normalised loss; and
- collateral contribution to system stress.

These are validation targets and policy outcomes.

---

## 10. Proposed parameter file architecture

The estimation pipeline should produce a versioned parameter file rather than hard-coded constants.

A possible structure is:

```yaml
metadata:
  estimation_start: "YYYY-MM-DD"
  estimation_end: "YYYY-MM-DD"
  simulation_frequency: "1h"
  regime_definition: "two_state_threshold"
  parameter_version: "v1"

market:
  block_length: 24
  normal_return_blocks_file: "..."
  stress_return_blocks_file: "..."
  regime_transition_matrix:
    normal_to_normal: null
    normal_to_stress: null
    stress_to_normal: null
    stress_to_stress: null
  gas_quantiles:
    p25: null
    p50: null
    p90: null
    p99: null

collateral:
  ETH:
    initial_price: null
    liquidation_ratio: null
    liquidation_penalty: null
    maximum_close_factor: null
    oracle_delay_steps: null
  BTC:
    initial_price: null
    liquidation_ratio: null
    liquidation_penalty: null
    maximum_close_factor: null
    oracle_delay_steps: null
  STABLE:
    initial_price: null
    liquidation_ratio: null
    liquidation_penalty: null
    maximum_close_factor: null
    oracle_delay_steps: null
    depeg_arrival_probability: null
    depeg_persistence: null

vault_population:
  joint_distribution_file: "..."
  simulated_vault_count: null
  total_initial_debt: null

keepers:
  shared_capacity_central: null
  shared_capacity_low: null
  shared_capacity_high: null
  capacity_unit: "existing_model_unit"

dai_market:
  initial_price: 1.0
  peg_reversion: null
  above_peg_response: null
  below_peg_response: null
  residual_noise_scale: null

confidence:
  normal_level: null
  stress_level: null
  panic_level: null
  bad_debt_sensitivity: null
  market_stress_sensitivity: null
  recovery_coefficient: null
  panic_selling_strength: null
```

Fields that remain modelling assumptions should be labelled explicitly rather than filled with pseudo-empirical precision.

---

## 11. Minimum viable empirical calibration

The first defensible empirical version does not require every parameter in this document.

The minimum set is:

1. observed collateral-specific liquidation ratios;
2. observed collateral-specific liquidation penalties;
3. documented maximum close factors;
4. historical collateral debt shares;
5. joint ETH–BTC–STABLE return blocks;
6. normal and stress regime definitions;
7. stress-transition probabilities;
8. empirical shock-severity distributions;
9. vault debt and collateral-ratio distributions;
10. gas distributions by regime;
11. empirically defensible shared keeper-capacity ranges;
12. DAI peg-reversion and residual-noise estimates;
13. confidence parameters calibrated to several aggregate moments;
14. multi-seed output distributions; and
15. at least one out-of-sample validation period.

This is sufficient to turn Experiment 06 into an empirically grounded dissertation experiment without adding a new class of agents or a full additional market mechanism.

---

## 12. Immediate parameter-research priorities

Based on the current project status, the next work should prioritise:

1. **Phase 1E-B representative vault windows**
   Acquire a quiet mature baseline, stablecoin-depeg, bull/activation and
   prolonged crypto-stress samples while reserving the FTX window for
   validation. This identifies collateral-ratio, distance-to-liquidation and
   owner-response distributions without claiming a complete vault census.

2. **Joint market and gas stress distributions**
   This replaces deterministic shock magnitudes and separates correlated crypto stress from a genuinely systemic shock.

3. **Historical collateral weights and protocol risk settings**
   This establishes realistic baselines for the five portfolios.

4. **Shared keeper-capacity measurement**
   This is central to simultaneous multi-collateral liquidation.

5. **DAI peg-response and confidence calibration**
   These determine whether collateral stress transmits to market-price outcomes.

6. **Exposure-normalised outcome measures**
   These prevent large collateral categories from appearing riskier merely because they contain more debt.

Only after these steps should the project decide whether a direct stable-depeg confidence or DAI-demand channel is necessary.
