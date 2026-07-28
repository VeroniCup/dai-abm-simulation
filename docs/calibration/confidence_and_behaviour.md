# Confidence and behavioural calibration

## 1. Purpose and decision boundary

This document defines the first post-restructuring calibration milestone for
confidence, DAI-market behaviour and peg recovery. It audits the implemented
mechanism, identifies what the existing empirical evidence can support, and
specifies a bounded future implementation. It does not estimate behavioural
parameters, adopt new values or authorise executable changes.

Confidence is a latent modelling state. It is not an observed Maker variable,
a wallet label or a survey measure. Historical DAI prices, collateral returns,
liquidation conditions and protocol outcomes can identify reduced-form
relationships and target moments, but they do not reveal confidence directly.
All future results must preserve that distinction.

The calibration principles are:

- estimate relationships from time windows and empirical distributions;
- separate calibration, validation and stress-testing periods;
- use probabilistic relationships only where the data identify heterogeneous
  behaviour;
- avoid tuning the model to reproduce one named event;
- normalise or remove coefficients that are not separately identified; and
- retain successful recovery, delayed recovery, partial recovery and persistent
  depeg as possible outcomes.

## 2. Current mechanism audit

### 2.1 State and timing

The current confidence state is a system-wide dictionary returned by
`get_confidence_state` in
[`confidence.py`](../../src/dai_sim/model/confidence.py). It contains:

- `regime`: `normal`, `stress` or `panic`;
- `confidence`: the configured scalar associated with that regime; and
- `panic_selling_pressure`: a below-peg pressure that is non-zero only in
  panic.

There is no stored confidence state carried from one simulation step to the
next and no `initial_confidence` input. At the start of each step,
[`simulation.py`](../../src/dai_sim/model/simulation.py) recomputes confidence
from the current DAI price, the market-price share of active vaults that is
liquidatable and active bad debt. The first-step value is therefore implied by
the initial DAI price and initial vault state.

The step order is:

1. summarise pre-liquidation vault state at oracle and market prices;
2. classify the pre-liquidation confidence regime;
3. calculate systemic stress and update DAI price;
4. attempt and execute liquidations;
5. summarise the post-liquidation vault state; and
6. classify and record post-liquidation confidence.

The post-liquidation confidence value is diagnostic only. Any liquidation
effects persist through the vault and bad-debt state used in the next fresh
classification; the confidence value itself is not carried forward.

### 2.2 Classification

The price classifier is:

- normal if DAI lies between `normal_lower_price` and
  `normal_upper_price`;
- stress if DAI lies between `stress_lower_price` and
  `normal_lower_price`, or is above the normal upper boundary; and
- panic if DAI is below `stress_lower_price` or non-positive.

The system classifier overrides this result:

- panic if the price state is panic, liquidatable share exceeds
  `max_stress_liquidatable_share`, or active bad debt exceeds
  `bad_debt_panic_threshold`;
- stress if the price state is stress or liquidatable share exceeds
  `max_normal_liquidatable_share`; and
- normal otherwise.

The regime maps immediately to `normal_confidence`, `stress_confidence` or
`panic_confidence`. There is no gradual deterioration, persistence, recovery
delay or scarring.

### 2.3 DAI demand, selling and recovery

[`market.py`](../../src/dai_sim/model/market.py) implements the following
reduced-form pressures. With peg price \(p^\ast\), DAI price \(p_t\),
confidence \(C_t\), and gap \(g_t=p^\ast-p_t\):

\[
D_t
=
\text{arbitrage\_strength}\ C_t\max(g_t,0),
\]

\[
S_t^{+}
=
\text{above\_peg\_supply\_strength}\max(-g_t,0),
\]

\[
S_t^{panic}
=
\text{panic\_strength}\times\text{combined panic pressure}.
\]

The model then applies:

\[
p_{t+1}
=
\operatorname{clip}\left(
p_t+\text{price\_adjustment\_speed}
(D_t-S_t^{+}-S_t^{panic}+R_t)+\varepsilon_t
\right).
\]

The simulation adds two sources to combined panic pressure:

\[
\text{panic\_selling\_multiplier}\max(1-p_t,0)
\mathbf{1}_{panic}
+0.005\,L_t
+0.5\,B_t,
\]

where \(L_t\) is liquidatable share and \(B_t\) is active bad debt divided by
active debt. The coefficients `0.005` and `0.5` are currently hard-coded in
`simulation.py`, are not configuration-owned, and are not documented as
empirical estimates.

The optional recovery term is disabled in the complete profiles. When enabled,
it adds arbitrage and policy feedback below the peg, scaled by confidence and
discounted by the active-bad-debt ratio. It has no stability-period gate and
does not change the confidence state itself.

### 2.4 Stress transmission

The implemented channels are:

- DAI peg deviation changes the regime directly;
- collateral prices affect confidence indirectly through liquidatable vaults
  and active bad debt;
- active bad debt can trigger panic and weakens optional recovery;
- liquidatable share can trigger stress or panic and also enters the hard-coded
  systemic selling pressure; and
- liquidation execution can improve the next classification by reducing
  unsafe inventory or can leave bad debt and unresolved positions.

The following are not direct confidence inputs:

- ETH, WBTC or stablecoin returns;
- realised or downside volatility;
- failed, unprofitable or capacity-limited liquidation counts;
- elapsed time since a depeg;
- repeated stress observations;
- keeper participation;
- gas cost; and
- collateral-price recovery itself.

Failed liquidation attempts matter only indirectly if unsafe vaults or bad debt
remain. Collateral-price recovery matters only if it changes liquidatable share
or bad debt. Confidence is homogeneous and system-wide; there is no
agent-specific belief or participation draw.

## 3. Current parameter traceability

The code defaults and established experiment factories remain the legacy
behavioural baseline. The complete empirical profiles adopt only the reviewed
DAI-price boundaries and quiet-window normal liquidatable-share boundary; the
remaining behavioural values are still scenario controls.

| Semantic role | Code field or coefficient | Current value | Configuration owner | Consumer | Current evidence and tests |
| --- | --- | --- | --- | --- | --- |
| Normal lower DAI boundary | `ConfidenceConfig.normal_lower_price` | `0.99` default/base; `0.9992875` empirical profiles | `config/profiles/{legacy,empirical,empirical_stress}.yaml`; experiment factory | `classify_price_regime` | Phase 1A fifth-percentile candidate for empirical profiles; configuration tests, source-schema test and frozen experiments |
| Normal upper DAI boundary | `ConfidenceConfig.normal_upper_price` | `1.01` default/base; `1.0030259166666666` empirical profiles | Same as above | `classify_price_regime` | Phase 1A ninety-fifth-percentile candidate; same test boundary |
| Panic-eligible lower DAI boundary | `ConfidenceConfig.stress_lower_price` | `0.97` default/base; `0.9967380166666668` empirical profiles | Same as above | `classify_price_regime` | Phase 1A first-percentile candidate; same test boundary |
| Normal liquidatable-share boundary | `ConfidenceConfig.max_normal_liquidatable_share` | `0.05` default/base; `0.0` empirical profiles | Same as above | `classify_system_regime` | Quiet-mature reconstructed-vault candidate; profile and integration tests |
| Panic liquidatable-share boundary | `ConfidenceConfig.max_stress_liquidatable_share` | `0.30` | Same as above | `classify_system_regime` | Moderate and severe stress candidates disagree; not adopted empirically |
| Absolute bad-debt panic boundary | `ConfidenceConfig.bad_debt_panic_threshold` | `1000.0` DAI | Same as above | `classify_system_regime` | Scenario control; scale-sensitive and not empirically identified |
| Normal confidence level | `ConfidenceConfig.normal_confidence` | `1.0` | Same as above | `confidence_level`, then DAI demand and recovery | Scale normalisation/scenario control; schema and regression coverage only |
| Stress confidence level | `ConfidenceConfig.stress_confidence` | `0.5` | Same as above | Same as above | Scenario control; not directly observed |
| Panic confidence level | `ConfidenceConfig.panic_confidence` | `0.1` | Same as above | Same as above | Scenario control; sparse-tail calibration remains |
| Panic gap multiplier | `ConfidenceConfig.panic_selling_multiplier` | `2.0` | Same as above | `panic_selling_pressure` | Scenario control; not separately identified from market panic strength |
| Target peg | `DAIMarketConfig.peg_price` | `1.0` USD | Same profiles and experiment factory | All DAI pressure functions | Protocol/design constant; configuration and regression tests |
| Price adjustment scale | `DAIMarketConfig.price_adjustment_speed` | `0.02` per step | Same as above | `update_dai_price` | Scenario control; only products with pressure coefficients are observed |
| Below-peg arbitrage strength | `DAIMarketConfig.arbitrage_strength` | `1.0` | Same as above | `calculate_dai_market_pressures` | Scenario control; no direct arbitrage-flow data |
| Above-peg supply strength | `DAIMarketConfig.above_peg_supply_strength` | `1.0` | Same as above | Same as above | Scenario control; no direct mint/sell-flow data |
| Panic market strength | `DAIMarketConfig.panic_strength` | `1.0` default/profiles; `0.5` base experiment factory | Same as above | Same as above | Scenario control; jointly confounded with panic gap multiplier |
| Residual price noise | `DAIMarketConfig.noise_std` | `0.0005` USD per step | Same as above | `update_dai_price` | Scenario assumption; estimable after deterministic terms |
| Numerical price floor | `DAIMarketConfig.min_price` | `0.50` | Same as above | `update_dai_price` | Experimental safeguard |
| Numerical price ceiling | `DAIMarketConfig.max_price` | `1.50` | Same as above | `update_dai_price` | Experimental safeguard |
| Recovery switch | `DAIMarketConfig.enable_peg_recovery` | `false` profiles; `true` recovery experiment | Same as above | `calculate_peg_recovery_pressure` | Experimental mechanism switch |
| Recovery-only arbitrage strength | `DAIMarketConfig.arbitrage_recovery_strength` | `0.0` profiles; `2.0` recovery experiment | Same as above | Same as above | Scenario value; potentially redundant with base arbitrage |
| Policy feedback strength | `DAIMarketConfig.policy_feedback_strength` | `0.0` profiles; `1.5` recovery experiment | Same as above | Same as above | Scenario value; no causal estimate |
| Bad-debt recovery drag | `DAIMarketConfig.bad_debt_recovery_drag` | `1.0` profiles; `5.0` recovery experiment | Same as above | Same as above | Scenario value; rare bad-debt evidence |
| Minimum recovery confidence | `DAIMarketConfig.min_recovery_confidence` | `0.0` profiles; `0.1` recovery experiment | Same as above | Same as above | Scenario value; depends on confidence-scale normalisation |
| Direct liquidatable-share selling | hard-coded `0.005` | `0.005` | No configuration owner | `simulation.py` systemic stress pressure | Fixed modelling assumption; regression coverage only |
| Direct bad-debt-ratio selling | hard-coded `0.5` | `0.5` | No configuration owner | Same as above | Fixed modelling assumption; regression coverage only |

The principal current tests are
[`test_configuration.py`](../../tests/inputs/test_configuration.py),
[`test_configuration_profiles.py`](../../tests/inputs/test_configuration_profiles.py),
[`test_source_package_migration.py`](../../tests/integration/test_source_package_migration.py)
and the frozen experiment checks described in
[`regression.md`](../validation/regression.md). There are no dedicated unit
tests for confidence persistence, recovery delay, parameter identifiability or
the two hard-coded systemic-pressure coefficients because those mechanisms do
not yet exist as explicit interfaces.

## 4. Available empirical variables

| Candidate variable | Availability | Defensible construction and limitation |
| --- | --- | --- |
| DAI absolute and signed peg deviation | Directly available | Hourly `dai_peg_deviation`, `dai_abs_peg_deviation` and price from the Phase 1A panel |
| DAI below-peg deviation | Directly available | `max(1-dai_price_usd, 0)`; `dai_below_peg` is also present |
| DAI return | Directly available | Hourly `dai_log_return` |
| Deviation duration and recovery duration | Constructible | Consecutive runs outside a pre-registered band; sustained recovery must require a fixed number of hours inside the band |
| Time since material depeg | Constructible | Hours since the last threshold crossing; threshold fixed before estimation |
| Repeated-stress indicator | Constructible | Number of material-depeg or stress episodes in a fixed trailing window |
| ETH and WBTC returns | Directly available | Hourly log returns; WBTC remains a wrapped BTC-collateral proxy |
| Realised and downside volatility | Constructible | Rolling return dispersion and negative semivariance using only past data |
| Gas and transaction-cost conditions | Directly available | Hourly median and tail gas prices, utilisation and standardised cost indices; liquidation transaction gas is separate |
| Liquidation count and volume | Directly available | Continuous hourly liquidation panel by exact ilk |
| Liquidation backlog | Directly available as a proxy | `unresolved_auctions` plus initiated/completed flow; it is not identical to simulated unsafe-vault inventory |
| Unsuccessful or delayed liquidation | Directly available as a proxy | Failed Take attempts, Redos, unresolved auctions and observed duration; failed inner-call gas remains unobserved |
| Bad debt | Constructible only as a proxy | Auction remaining-tab/bad-debt proxy and reconstructed states; sparse and not a complete accounting series |
| Liquidatable-vault share | Constructible in representative windows | Reconstructed collateral ratio versus effective liquidation ratio; not continuously observed over the full sample |
| Protocol changes | Directly available | Effective-dated Phase 1D parameter panel |
| DAI trading volume | Future acquisition | Not in the current tracked or ignored empirical panels |
| DAI market depth | Future acquisition | Not available; no order-book or DEX depth series is present |
| DAI supply change | Future acquisition | Not present as a continuous, validated supply series |
| Actual DAI arbitrage participation | Weakly observable/unsuitable now | Price correction is observed, but arbitrage identities, capacity and competing flows are not |
| Beneficial-owner confidence | Unsuitable | Manager owner is an identity proxy, not a beneficial-owner or belief measure |

The joined market–gas panel, continuous liquidation panel, effective protocol
panel and representative vault windows can be joined locally by UTC hour.
Production code must not depend on these ignored full panels. Any future
runtime input must be a compact, tracked, content-addressed artefact under its
owning domain, with canonical provenance.

## 5. Latent-confidence interpretation

The recommended interpretation is a bounded, system-wide reduced-form index:

- \(C_t=1\) is a normalisation for the strongest stabilising response in the
  model, not a statement of universal belief;
- lower \(C_t\) means the observed stress history predicts weaker below-peg
  correction and/or stronger selling pressure;
- the index has memory, so identical contemporaneous conditions may produce
  different responses after short and prolonged stress; and
- the index is validated through DAI-price and recovery moments, not against an
  unobserved confidence label.

A transparent proxy target can be estimated from lagged observables:

\[
\Pr(Y_{t+h}=1)
=
\operatorname{logit}^{-1}\left(
\beta_0+\beta_p g_t^-+\beta_r r_t^-+\beta_l L_t+\beta_b B_t
\right),
\]

where \(Y_{t+h}\) denotes continued material depeg over a fixed horizon,
\(g_t^-\) is below-peg deviation, \(r_t^-\) is downside collateral stress,
\(L_t\) is unresolved liquidation pressure and \(B_t\) is a defensible bad-debt
proxy. This probability is a stress proxy, not observed confidence.

Bad debt should enter the primary proxy only if its coverage and variation pass
the pre-registered data-quality gate. Otherwise it remains a sensitivity
channel. Gas may condition the liquidation-pressure measure, but should not be
added as an independent confidence coefficient without incremental predictive
evidence.

## 6. Candidate model designs

| Criterion | A. Bounded deterministic state | B. Probabilistic heterogeneous participation | C. Regime-dependent state process |
| --- | --- | --- | --- |
| Core rule | Smooth a transparent observable stress target and recover after stable conditions | Draw agent participation from a logistic probability using confidence, peg gap and costs | Estimate transitions among normal, stress, panic and recovery states |
| Empirical identifiability | Moderate with current hourly panels | Weak: no DAI arbitrage-flow, depth or participant data | Moderate for observed regimes, weak for rare panic transitions |
| New parameter burden | Low to moderate | High: probability, capacity and heterogeneity distribution | Moderate to high: transition matrix plus state-specific responses |
| Interpretability | High | Moderate | Moderate |
| Computational cost | Low | Moderate to high | Low |
| Current-model compatibility | High; replaces instantaneous lookup with one state update | Requires a new behavioural-agent or participation layer | Compatible with current labels but changes transition semantics |
| Overfitting risk | Manageable with normalisations and blocked validation | High | High in sparse extreme states |
| Recovery behaviour | Supports delayed, partial and failed recovery | Supports endogenous weak/strong participation but capacity is unobserved | Supports sticky regimes and recovery-state transitions |
| Dissertation explainability | Strong | Defensible only with new flow evidence | Defensible, but more elaborate than current evidence requires |
| Testing burden | State bounds, timing, memory, recovery and legacy mode | All of A plus probability, aggregation and seed-distribution tests | Transition, occupancy, rare-state and label-stability tests |

### Recommendation

Candidate A is the primary design. Candidate C is a sensitivity alternative
using the existing regime labels after the deterministic state has been
estimated. Candidate B should not be implemented until DAI volume, liquidity
or participant evidence can distinguish participation from generic price
reversion.

The primary design should remain system-wide. Agent heterogeneity is not
required for the first implementation because the available data identify
aggregate DAI correction, not individual arbitrage decisions.

## 7. Recommended minimum specification

### 7.1 State equation

Let \(\widehat S_t\in[0,1]\) be the pre-estimated observable stress proxy and
\(C_t^\ast=1-\widehat S_t\). Use asymmetric adjustment:

\[
C_t =
\begin{cases}
\max(C_{\min},\ C_{t-1}+\alpha_d(C_t^\ast-C_{t-1})),
& C_t^\ast<C_{t-1},\\
C_{t-1},
& C_t^\ast\ge C_{t-1}\ \text{and stability gate is closed},\\
\min(1,\ C_{t-1}+\alpha_r(1-C_{t-1})),
& \text{stability gate is open}.
\end{cases}
\]

The stability gate opens after \(k\) consecutive hours inside the calibrated
DAI band, with no severe unresolved-liquidation or bad-debt condition. A new
material depeg or severe liquidation condition closes the gate and resets its
counter. This permits persistence and recovery without forcing recovery.

The minimum new state parameters are:

- deterioration adjustment \(\alpha_d\);
- recovery adjustment \(\alpha_r\);
- recovery stability period \(k\); and
- confidence floor \(C_{\min}\).

Do not add a separate persistence coefficient: persistence is already implied
by \(\alpha_d\), \(\alpha_r\) and the gate. The ceiling remains the normalised
constant `1.0`. Long-lived scarring should be a sensitivity alternative to a
lower recovery target, not a fifth primary parameter unless held-out evidence
requires it.

### 7.2 Stress inputs

The primary stress proxy should use the smallest validated set:

- below-peg deviation;
- downside ETH/WBTC return or downside-volatility composite; and
- unresolved liquidation pressure normalised by exposure.

Bad-debt ratio is included only after coverage validation. Repeated-stress
history can be represented by the state equation rather than an additional
coefficient. Peg thresholds and liquidatable-share thresholds remain
observable classification rules rather than latent confidence values.

### 7.3 DAI response

Estimate effective response coefficients rather than attempting to identify
products of arbitrary scales:

\[
\kappa_- =
\text{price adjustment speed}\times\text{arbitrage strength},
\qquad
\kappa_+ =
\text{price adjustment speed}\times\text{above-peg supply strength}.
\]

Normalise `price_adjustment_speed` to one documented scale for behavioural
calibration, or expose \(\kappa_-\) and \(\kappa_+\) directly. Do not estimate
both components of either product.

Use one effective panic coefficient multiplying a documented panic signal.
The present `panic_selling_multiplier`, `panic_strength`, hard-coded
liquidatable-share coefficient and hard-coded bad-debt coefficient are not
separately identifiable. The future implementation must either consolidate
them or fix all but one by explicit normalisation.

Estimate residual noise after the deterministic response. Do not add an
arbitrage-capacity parameter or agent participation distribution in the
primary specification because current data do not identify either.

## 8. Parameter-estimation strategy

| Proposed quantity | Classification | Empirical target | Estimator | Uncertainty and validation |
| --- | --- | --- | --- | --- |
| Existing DAI regime thresholds | Direct empirical classification rules | DAI price quantiles and episode classification | Existing registered quantiles plus nearby-threshold grid | Year-block bootstrap and held-out episode performance |
| Liquidatable-share thresholds | Distributionally estimated rules | Reconstructed liquidatable share | Regime-specific quantiles with window-cluster bootstrap | Leave-one-stress-window-out; report moderate/severe alternatives |
| Stress-proxy coefficients | Statistically estimated | Probability of continued material depeg | Penalised logistic model with lagged, standardised predictors | Time-block bootstrap, coefficient signs, calibration curve and ablation |
| \(\alpha_d\) | Statistically/SMM estimated | Deterioration speed, depeg depth and cumulative deviation | Constrained minimum distance or SMM | Profile interval and blocked validation |
| \(\alpha_r\) | Statistically/SMM estimated | Recovery half-life and sustained recovery | Constrained minimum distance or SMM | Profile interval and leave-one-episode-out |
| Stability period \(k\) | Distributionally estimated discrete parameter | Stable hours preceding sustained recovery | Empirical duration distribution; small pre-registered grid | Sensitivity around selected quantile |
| Confidence floor \(C_{\min}\) | Calibrated behavioural parameter | Severe-depeg depth and weak arbitrage response | Profiled bounded SMM | Wide interval; stress test rather than false precision |
| Effective below-peg response \(\kappa_-\) | Statistically estimated then SMM-refined | One-step correction, duration and overshoot below peg | Asymmetric autoregression followed by SMM | Block bootstrap and withheld FTX interval |
| Effective above-peg response \(\kappa_+\) | Statistically estimated then SMM-refined | One-step correction and overshoot above peg | Same asymmetric model | Test restricted symmetric model first |
| Effective panic response | Calibrated behavioural parameter | Tail depth, area below peg and persistence | One normalised coefficient in constrained SMM | Leave-one-stress-window-out and ablation |
| Residual noise | Distributionally estimated | Residual hourly DAI innovation | Residual empirical distribution or regime-scaled standard deviation | Autocorrelation, tails and simulated coverage |
| Peg target | Protocol/design constant | USD target | No estimator | Formula and unit tests |
| Price bounds | Experimental scenario parameters | Numerical safeguard | No estimator | Binding-frequency sensitivity |
| Bad-debt response | Sensitivity unless data gate passes | Recovery conditional on defensible bad-debt ratio | Interaction in proxy/SMM only after coverage check | Report omission and wide bounds |
| Agent participation/capacity | Additional-data dependency | DAI arbitrage flow, volume and depth | Not estimated now | No implementation without new evidence |

All estimation uses lagged covariates to avoid contemporaneous look-ahead.
Predictors are standardised on the calibration sample only. Regularisation,
thresholds, lag lengths, recovery bands and moment weights are fixed before
examining validation results.

### 8.1 Complete behavioural parameter classification

The following matrix completes the traceability in Section 3. `C` denotes the
primary calibration sample defined in Section 9; `V` is the withheld FTX
validation interval; and `S` denotes the two stress-testing windows. Confidence
and response coefficients remain global in the primary design. Agent
heterogeneity is not required unless the row says otherwise.

| Parameter | Role, interpretation and unit | Empirical target and required variables | Estimation, window and validation | Uncertainty and heterogeneity | Owner → consumer | Proposed status |
| --- | --- | --- | --- | --- | --- | --- |
| `normal_lower_price` | Lower normal boundary; USD/DAI | Central lower DAI-price quantile; DAI price | Registered quantile on C; classify V; stress check S | Year-block interval; no heterogeneity | Profiles/factory → price classifier | Distributionally estimated |
| `normal_upper_price` | Upper normal boundary; USD/DAI | Central upper DAI-price quantile; DAI price | Registered quantile on C; asymmetric validation on V | Year-block interval; no heterogeneity | Profiles/factory → price classifier | Distributionally estimated |
| `stress_lower_price` | Panic-eligible tail boundary; USD/DAI | Lower-tail persistent depeg; DAI price and episode duration | Tail quantile/change-point on C; false-panic check V | Threshold grid and block interval; no heterogeneity | Profiles/factory → price classifier | Distributionally estimated |
| `max_normal_liquidatable_share` | Normal unsafe-vault boundary; share | Ordinary reconstructed liquidatable share | Quiet-window quantile with continuous liquidation context; validate outside window | Window-cluster interval; ilk results retained diagnostically | Profiles/factory → system classifier | Distributionally estimated |
| `max_stress_liquidatable_share` | Severe unsafe-vault boundary; share | Moderate/severe reconstructed liquidatable share | Labelled-window quantiles; leave-one-S-window-out | Wide day-block interval; global primary with exact-ilk diagnostics | Profiles/factory → system classifier | Distributionally estimated, unresolved severity choice |
| `bad_debt_panic_threshold` | Absolute panic trigger; DAI | Scaled active bad debt and DAI response | No defensible estimator in current absolute form | Strong scale uncertainty; no heterogeneity | Profiles/factory → system classifier | Unnecessary and removable or replace with normalised input |
| `normal_confidence` | Normal latent level; index | Scale normalisation | Fix at one, not estimate | None after normalisation; no heterogeneity | Profiles/factory → demand/recovery | Fixed modelling normalisation |
| `stress_confidence` | Stress latent level; index | Stress correction and persistence moments | Current discrete design: joint SMM on C, V validation | Profile interval; no heterogeneity | Profiles/factory → demand/recovery | Unnecessary if bounded continuous state is adopted |
| `panic_confidence` | Panic latent level; index | Severe depth and non-recovery moments | Current discrete design: bounded SMM using C, test S | Very wide tail interval; no heterogeneity | Profiles/factory → demand/recovery | Unnecessary if bounded continuous state is adopted |
| `panic_selling_multiplier` | Converts panic peg gap to pressure; multiplier | Tail depth and cumulative below-peg area | Not separately estimable from `panic_strength`; normalise jointly | Profile ridge expected; no heterogeneity | Profiles/factory → panic pressure | Unnecessary and removable after consolidation |
| `peg_price` | USD target; USD/DAI | Maker design target | No estimator; formula checks | None; no heterogeneity | Profiles/factory → all market equations | Directly observed protocol/design constant |
| `price_adjustment_speed` | Pressure-to-price scale; per step | DAI change conditional on all pressures | Fix scale or estimate only effective products on C; validate V | Identification normalisation; no heterogeneity | Profiles/factory → price update | Unnecessary as a separately estimated parameter |
| `arbitrage_strength` | Below-peg response; dimensionless | Below-peg one-step correction and duration | Estimate effective \(\kappa_-\) on C; validate V and S | Block-bootstrap/profile interval; aggregate only | Profiles/factory → demand pressure | Statistically estimated only as effective product |
| `above_peg_supply_strength` | Above-peg response; dimensionless | Above-peg one-step correction and overshoot | Estimate effective \(\kappa_+\) on C; validate V | Block-bootstrap interval; aggregate only | Profiles/factory → supply pressure | Statistically estimated only as effective product |
| `panic_strength` | Panic-pressure response; dimensionless | Extreme DAI depth, area and persistence | One consolidated coefficient by SMM on C; test S | Profile interval and ablation; no heterogeneity | Profiles/factory → panic supply | Statistically estimated after consolidation |
| `noise_std` | Residual DAI innovation scale; USD/step | Residual price changes | Fit after deterministic terms on C; check V residuals | Empirical residual/bootstrap interval; regime sensitivity only | Profiles/factory → price update | Distributionally estimated |
| `min_price` | Numerical floor; USD/DAI | Binding frequency only | No estimator; widen in S | Scenario range; no heterogeneity | Profiles/factory → clipping | Stress-test parameter |
| `max_price` | Numerical ceiling; USD/DAI | Binding frequency only | No estimator; widen in S | Scenario range; no heterogeneity | Profiles/factory → clipping | Stress-test parameter |
| `enable_peg_recovery` | Optional mechanism switch; Boolean | Nested-model recovery performance | Paired ablation on C and V | Model-selection uncertainty; no heterogeneity | Profiles/factory → recovery function | Stress-test parameter pending replacement decision |
| `arbitrage_recovery_strength` | Additional below-peg response; dimensionless | Incremental recovery beyond base arbitrage | Nested-model test on C; validate V | Expected collinearity; no heterogeneity | Profiles/factory → recovery function | Unnecessary unless incremental identification passes |
| `policy_feedback_strength` | Stylised policy response; dimensionless | Recovery aligned with effective protocol actions | Not causally identified; event evidence only | Literature/scenario range; no heterogeneity | Profiles/factory → recovery function | Literature-informed prior or stress-test parameter |
| `bad_debt_recovery_drag` | Recovery impairment; dimensionless | Recovery conditional on bad-debt ratio | Interaction SMM only if data gate passes | Wide profile interval; no heterogeneity | Profiles/factory → recovery discount | Stress-test parameter unless statistically identified |
| `min_recovery_confidence` | Recovery activation boundary; index | Recovery/non-recovery classification | Current design: profiled threshold; future design uses stability gate | Scale-dependent interval; no heterogeneity | Profiles/factory → recovery discount | Unnecessary under recommended stability gate |
| Hard-coded liquidatable-share coefficient | Direct selling response; pressure/share | DAI move conditional on unresolved pressure | Consolidate into stress proxy/panic coefficient | Not separately identifiable; no heterogeneity | No owner → simulation systemic pressure | Unnecessary and removable in current form |
| Hard-coded bad-debt-ratio coefficient | Direct selling response; pressure/ratio | DAI move conditional on defensible bad-debt ratio | Include only after data gate and consolidation | Sparse-tail uncertainty; no heterogeneity | No owner → simulation systemic pressure | Unnecessary in current form; sensitivity if supported |
| Stress-proxy peg coefficient \(\beta_p\) | Predictive stress loading; log-odds per standardised gap | Continued depeg; lagged below-peg gap | Penalised logistic model on C; calibration and sign checks V | Time-block bootstrap; system-wide | Future calibration candidate → confidence target | Statistically estimated |
| Stress-proxy collateral coefficient \(\beta_r\) | Predictive stress loading; log-odds per standardised downside measure | Continued depeg; lagged ETH/WBTC downside stress | Same model and windows as \(\beta_p\) | Time-block bootstrap; no agent heterogeneity | Future calibration candidate → confidence target | Statistically estimated |
| Stress-proxy liquidation coefficient \(\beta_l\) | Predictive stress loading; log-odds per standardised pressure | Continued depeg; unresolved auctions/exposure | Same model, ablation and V check | Coverage and block uncertainty; no agent heterogeneity | Future calibration candidate → confidence target | Statistically estimated |
| Stress-proxy bad-debt coefficient \(\beta_b\) | Optional predictive loading; log-odds per standardised ratio | Continued depeg; defensible bad-debt ratio | Estimate only after coverage gate; otherwise S-only | Sparse-event interval; no agent heterogeneity | Future calibration candidate → confidence target | Stress-test parameter unless data support estimation |
| Deterioration adjustment \(\alpha_d\) | Downward state adjustment; fraction per hour | Depeg onset speed, depth and cumulative deviation | Constrained SMM on C; validate V | Profile interval; no agent heterogeneity | Future confidence config → state update | Statistically estimated |
| Recovery adjustment \(\alpha_r\) | Upward state adjustment; fraction per hour | Recovery half-life and sustained recovery | Constrained SMM on C; validate V, test S | Profile/episode-bootstrap interval; no agent heterogeneity | Future confidence config → state update | Statistically estimated |
| Stability period \(k\) | Delay before recovery; hours | Stable hours preceding sustained recovery | Empirical duration quantile and small fixed grid on C | Discrete sensitivity interval; no agent heterogeneity | Future confidence config → state update | Distributionally estimated |
| Confidence floor \(C_{\min}\) | Lower bounded latent response; index | Severe depth and weak correction | Profiled bounded SMM on C; stress check S | Wide tail range; no agent heterogeneity | Future confidence config → state update | Statistically estimated with stress-test bounds |
| Effective below-peg response \(\kappa_-\) | Aggregate stabilising response; price change per gap per hour | Subsequent DAI correction; lagged negative gap and confidence | Asymmetric regression then SMM on C; validate V | Block-bootstrap/profile interval; aggregate only | Future market config → demand pressure | Statistically estimated |
| Effective above-peg response \(\kappa_+\) | Aggregate supply response; price change per gap per hour | Subsequent DAI correction; lagged positive gap | Asymmetric regression then SMM on C; validate V | Block-bootstrap/profile interval; aggregate only | Future market config → supply pressure | Statistically estimated |
| Effective panic response | Aggregate downside response; price change per panic signal per hour | Tail depth, duration and area | One-coefficient constrained SMM on C; test S | Wide profile interval; no agent heterogeneity | Future market config → panic supply | Statistically estimated with stress bounds |
| Arbitrage participation probability | Agent action probability | DAI participant/flow observations | No estimator with current data | Heterogeneity would be required | No current owner → Candidate B | Additional-data dependency; do not add |
| Arbitrage capacity | Bounded DAI buying capacity | DAI depth, volume and capital | No estimator with current data | Participant and liquidity heterogeneity required | No current owner → Candidate B | Additional-data dependency; do not add |

## 9. Calibration, validation and stress windows

The existing empirical policy withholds 1–21 November 2022 from primary
candidate estimation. The same half-open FTX interval remains the principal
out-of-sample validation window for behavioural calibration.

The proposed split is:

- **calibration**: the continuous hourly sample from 1 June 2021 to 1 July
  2024 excluding the withheld interval and the stress windows below; ordinary
  depeg episodes are selected by pre-registered thresholds rather than names;
  the quiet-mature vault window from 1 February to 1 March 2024 supplies an
  ordinary liquidation-state check;
- **validation**: 1–21 November 2022, used once after the specification,
  moments and parameter bounds have been fixed; and
- **stress testing**: the Terra/CeFi window from 5 May to 20 June 2022 and the
  USDC/SVB window from 6–20 March 2023, used for robustness and mechanism
  failure analysis rather than coefficient tuning.

Existing DAI threshold candidates were estimated from the broader
FTX-excluded sample and are not re-described as cleanly withheld from the two
stress windows. For new behavioural coefficients, those windows must be
excluded from fitting or handled through explicit leave-one-window-out
estimation. This limitation must be visible in reported results.

Time-series cross-validation uses contiguous blocks, not shuffled hours.
Bootstrap resampling uses day or episode blocks long enough to preserve serial
dependence. Named windows are descriptive labels and robustness sets, not
targets for manual path matching.

## 10. Peg-recovery outcomes and experiments

Recovery must be defined before simulation comparison. For peg band
\(\delta\) and required duration \(h\), sustained recovery occurs at the first
step \(t\) such that:

\[
|p_s-1|\le\delta
\quad\text{for every }s\in[t,t+h-1].
\]

Report at least:

- minimum DAI price;
- maximum absolute peg deviation;
- hours below pre-registered 0.99 and 0.995 thresholds;
- time to first return to the band;
- time to sustained recovery;
- sustained-recovery indicator by the horizon;
- recovery half-life and cumulative absolute deviation;
- post-recovery overshoot;
- minimum confidence and time for confidence to return to its recovery band;
- stress and panic occupancy;
- unresolved-liquidation level and duration;
- cumulative unresolved-liquidation pressure;
- active and realised bad debt;
- effective arbitrage demand;
- panic selling pressure; and
- fraction of steps at numerical price bounds.

Future semantic experiments retain their present ownership:

- `baseline`: compare legacy and behavioural specifications without changing
  the shock;
- `confidence`: vary estimated uncertainty bounds and ablate stress channels;
- `peg_recovery`: cross collateral recovery, confidence recovery and backlog
  clearance;
- `shock_severity`: test nonlinear deterioration without re-estimation; and
- `multi_collateral`: test common confidence under alternative portfolio
  composition and correlated shocks.

The recovery design must cross the following channels independently:

1. permanent, partial and full collateral-price recovery;
2. sticky versus recovering confidence;
3. weak versus stronger effective arbitrage response;
4. persistent versus cleared liquidation backlog; and
5. persistent versus resolved bad-debt proxy.

No scenario should set DAI price or confidence directly to its recovered value.

## 11. Exact future implementation map

Executable work requires a separate, bounded authorisation. The anticipated
semantic owners are:

| File | Why this is the owner | Bounded future change |
| --- | --- | --- |
| `src/dai_sim/model/confidence.py` | Confidence state and transitions | Add a state/config representation and pure bounded update function; retain a declared legacy instantaneous mode |
| `src/dai_sim/model/market.py` | DAI demand and supply equations | Consume effective response coefficients and remove or normalise duplicate panic/recovery products |
| `src/dai_sim/model/simulation.py` | Step ordering and state persistence | Carry confidence and stability counter between steps; pass backlog/bad-debt inputs without changing liquidation mechanics |
| `src/dai_sim/model/metrics.py` | General outcome definitions | Add sustained recovery, confidence recovery, cumulative pressure and bound-binding metrics |
| `src/dai_sim/calibration/market.py` | Existing market calibration owner | Construct episodes, fit proxy/asymmetric response models and write compact candidates |
| `src/dai_sim/calibration/validation.py` | Calibration validation owner | Add blocked-window, profile-likelihood, ablation and moment checks |
| `src/dai_sim/experiments/scenarios.py` | Semantic scenario factories | Add explicitly named behavioural specification and uncertainty variants while retaining legacy factories |
| `src/dai_sim/experiments/summaries.py` | Experiment reporting | Add the approved sustained-recovery and pressure metrics |
| `config/profiles/empirical.yaml` | Complete empirical runtime profile | Adopt values only after estimation and review; retain legacy mode as default elsewhere |
| `config/profiles/empirical_stress.yaml` | Complete operational stress profile | Use reviewed uncertainty/stress bounds, not arbitrary crisis matching |
| `config/sensitivities/market/` | Explicit partial behavioural overrides | Add only genuinely reusable confidence/recovery sensitivities with semantic names |
| `workflows/calibration/market_gas_protocol.py` | Existing market calibration entry point | Extend the existing workflow; do not add a wrapper-only workflow |
| `tests/model/` | Model-mechanism responsibility | Add confidence-transition, market-pressure, timing and recovery tests |
| `tests/calibration/` | Estimator responsibility | Add blocked split, estimator, uncertainty and evidence-integrity tests |
| `tests/experiments/` | Experiment responsibility | Add recovery-definition and semantic experiment tests |
| `tests/integration/` | Cross-layer compatibility | Preserve legacy initialisation and Experiments 1–5 checksums |

The currently absent `tests/model/` and `tests/experiments/` directories are
approved target responsibilities, not placeholders. They should be created
only together with substantive tests in the authorised implementation.

No new top-level directory, compatibility module, flat `src` module, workflow
wrapper, cumulative profile or chronology-labelled file is required.

## 12. Test plan

The implementation gate requires:

- confidence remains in its configured bounds;
- identical current stress produces more deterioration after repeated stress
  only through documented memory;
- a new severe observation resets the stability counter;
- recovery does not begin before the required stable period;
- unresolved liquidation or severe bad debt can keep the gate closed;
- recovery can be successful, delayed, partial or absent;
- no confidence or price update uses future empirical information;
- direct collateral-return and liquidation channels have the expected signs;
- below- and above-peg response formulas match their effective coefficients;
- panic pressure is counted once;
- price bounds report binding rather than silently censoring results;
- deterministic seeds reproduce state and price paths;
- legacy mode reproduces all frozen smoke and Experiments 1–5 checksums;
- empirical profiles load the reviewed fields without hidden inheritance;
- blocked calibration and validation windows are disjoint;
- compact runtime evidence matches its manifest checksum; and
- output summaries reconcile detailed results.

## 13. Data gaps and acquisition dependencies

No live acquisition is required to estimate price thresholds, asymmetric peg
correction, residual noise, depeg durations, collateral stress or continuous
liquidation-pressure proxies.

The following block stronger behavioural claims:

- no continuous DAI trading-volume or market-depth series;
- no direct identification of DAI arbitrage transactions or participants;
- no direct confidence observation;
- incomplete bad-debt accounting and few severe bad-debt episodes;
- representative rather than continuous liquidatable-vault shares;
- no beneficial-owner identity; and
- no causal identification of governance policy feedback.

These gaps mean arbitrage capacity, agent participation heterogeneity,
long-lived scarring and policy feedback remain sensitivity or future-data
questions. They do not block the recommended aggregate bounded-state design.

## 14. Risks, acceptance criteria and unresolved decisions

### Risks of overfitting

- fitting several multiplicative coefficients that produce the same DAI
  response;
- treating hourly observations within one episode as independent;
- using rare crises both to estimate and validate panic behaviour;
- allowing the stress proxy to reproduce the DAI outcome mechanically through
  contemporaneous peg deviation;
- adding bad debt, gas, volatility and liquidation variables without
  incremental predictive evidence;
- interpreting purposive vault windows as unconditional exposure; and
- retaining an optional recovery term that duplicates base arbitrage.

### Acceptance criteria for implementation

Implementation is ready for authorisation only when:

1. the outcome horizon, peg bands and sustained-recovery duration are fixed;
2. the calibration, validation and stress windows are materialised and
   non-overlapping for new coefficients;
3. liquidation-pressure and bad-debt proxies have explicit definitions and
   coverage reports;
4. effective rather than multiplicatively redundant DAI coefficients are
   selected;
5. the stress-proxy specification passes sign, stability and ablation checks;
6. every adopted parameter has a point estimate, uncertainty interval and
   provenance record;
7. the legacy behavioural mode and frozen regressions remain mandatory; and
8. the exact executable files and tests in Section 11 receive separate
   authorisation.

### Unresolved decisions

- Choose the material-depeg band and sustained-recovery duration before
  estimation.
- Decide whether the primary stress proxy uses ETH only or a debt-share-weighted
  ETH/WBTC downside measure.
- Define unresolved liquidation pressure using auctions, unsafe inventory or a
  documented combination.
- Decide whether bad debt passes the primary-data gate or remains sensitivity
  only.
- Choose which scale parameter is normalised in the DAI pressure equation.
- Decide whether the optional recovery equation is removed, retained only as an
  ablation, or re-expressed by the confidence recovery state.
- Decide whether the empirical profile opts into the new mechanism after
  validation while the legacy profile remains unchanged.

Until these decisions and estimates exist, coding a new confidence mechanism
would require guessed parameter values. This planning pass therefore stops
before executable implementation.
