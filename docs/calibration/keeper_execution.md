# System-wide keeper execution calibration

## Decision boundary

This study pre-registers and implements the first direct calibration of the
simulator's shared keeper execution controls:

- `LiquidationConfig.max_liquidations_per_step`; and
- `LiquidationConfig.risk_cost_rate`, used here as the existing proportional
  keeper hurdle interface.

The result is **candidate-only**. No legacy, empirical or empirical-stress
profile imports the registry, and no established experiment is changed. The
overall classification is
`shared_keeper_execution_registry_ready_with_partial_identification`.

## Runtime semantic audit

The present profit equation is:

\[
\begin{aligned}
D_{\mathrm{repaid}} &=
  D_{\mathrm{vault}}\times\texttt{max\_close\_factor},\\
R_{\mathrm{gross}} &=
  D_{\mathrm{repaid}}\times\texttt{liquidation\_penalty},\\
C_{\mathrm{risk}} &=
  D_{\mathrm{repaid}}\times\texttt{risk\_cost\_rate},\\
\Pi_{\mathrm{expected}} &=
  R_{\mathrm{gross}}-\texttt{gas\_cost}-C_{\mathrm{risk}}.
\end{aligned}
\]

A keeper executes only where expected profit is strictly positive. With the
empirical demand layer enabled, the operation order is unsafe inventory,
sampled demand, global expected-profit ordering, the shared attempt budget,
then the profitability outcome. The capacity field therefore counts protocol
liquidation opportunities per one-hour simulation step. It is not ETH-only,
per-ilk or per-collateral capacity.

## Evidence and comparability

The comparable collateral universe is the validated Liquidations 2.0 sample:
ETH-A/B/C and WBTC-A/B/C. The hourly evidence retains those exact ilks and also
constructs an explicitly labelled `SYSTEM_ALL` aggregate. Other Maker
collateral is excluded because no jointly validated local unsafe-inventory and
canonical liquidation mapping is available for this bounded design.

Two representative windows enter estimation:

- Terra/CeFi, 5 May–20 June 2022, which provides 1,104 start-of-hour system
  states, 138 positive-unsafe-inventory hours and 649 linked Bark–grab
  closures; and
- quiet-mature February 2024, which provides 696 hours with no unsafe
  inventory or liquidation closure.

The USDC/SVB interval and the withheld November 2022 final-validation interval
are excluded from threshold construction and estimation. Continuous
2021–2024 liquidation evidence informs comparability and transaction
economics, but positive closures are never substituted for missing unsafe
inventory.

## Pre-registered capacity design

High demand requires positive start-of-hour unsafe inventory. The primary
threshold is the nearest-rank 75th percentile of that positive inventory;
67th and 90th percentile definitions are robustness checks.

Execution stress requires at least two of:

- hourly median effective gas price at or above its calibration 90th
  percentile;
- maximum ETH/WBTC rolling 24-hour realised volatility at or above its
  calibration 90th percentile; and
- minimum ETH/WBTC 24-hour log return at or below its calibration 5th
  percentile.

The primary inventory threshold is 17 unsafe vaults. It identifies 36
high-demand hours, of which 35 have observed slack. The pooled nearest-rank
closure counts are 14 at p75, 26 at p90 and 45 at p95, with a maximum of 46.
Observation and day-block bootstraps are retained in the frontier evidence.
The primary p90 day-block interval is 14–45, so uncertainty is not narrow.

Level 1 frontier identification is not claimed. The two calendar blocks have
p90 closure counts of 45 and 26, a difference of 19 (42.2% of the larger
value), and the primary non-stress subset contains only seven hours. Capacity
is therefore `shared_capacity_partially_identified`, despite passing the
minimum demand and slack counts. Upper-tail counts do not show a repeated,
stable common saturation point and the 67th/75th/90th demand-threshold p90s
are 24/26/45.

Count remains the calibrated unit. As validation outputs, primary high-demand
completed debt has p90 4.77 million DAI and maximum 15.59 million DAI, while
completed collateral value has p90 USD 5.68 million and maximum USD
17.95 million. The execution-to-starting-inventory ratio is reported only as
an aggregate diagnostic because arrivals and profitability may also bind.

## Composition and candidate count range

Within the same 36 system high-demand hours, 19 are `mixed_collateral`, four
are `single_collateral_dominant`, and 13 have no closure. Their p90 closure
counts are 45, 5 and 0 respectively. The pre-registered material-difference
test requires at least ten observations in both the mixed and dominant groups.
Composition is therefore `composition_unresolved`, not silently treated as
stable and not used to create collateral-specific capacities.

The pre-registered insufficient-regime rule gives pooled p75/p90/p95 values of
14/26/45. The composition rule cannot be applied with only four dominant
hours, so the pooled range is retained:

| Candidate profile | Shared hourly count |
|---|---:|
| `shared_keeper_capacity_low` | 14 |
| `shared_keeper_capacity_central` | 26 |
| `shared_keeper_capacity_high` | 45 |

These are empirical sensitivity points under observed demand, not estimates
of a physical keeper-network maximum. The `direct_system_count` mapping is
used because the runtime demand pool and the capacity evidence share the same
reconstructed protocol population. Population scaling is not applied.

The Bark identity proxy records the decoded incentive recipient where present
and otherwise the Bark transaction sender. In the 36 primary high-demand
hours it has a median of one and p90 of two distinct addresses, with a
descriptive correlation of about 0.70 with closure count. This supports the
ecosystem interpretation but does not turn address count into capacity.

## Profit hurdle

The detailed calibration-only opportunity panel contains 1,289 successful
Take events. The primary system-wide sample contains 1,064 auctions with
exactly one Take, one auction in that transaction and no other liquidation
action. This prevents partial Takes from being counted as independent model
vault opportunities. For the current model's economics, the direct proxy is:

\[
\Pi_{\mathrm{direct}} =
  \texttt{Take.owe}\times\texttt{liquidation penalty}
  - \texttt{transaction gas cost USD}.
\]

This is a model-mapping proxy, not realised keeper profit. It omits acquisition
discounts or premiums, capital funding, inventory risk, bundling, private
order flow and off-chain operating costs.

The direct-profit proxy has median 2,974.84 DAI, p05 665.37 DAI and p25
1,639.21 DAI. Six successful observations have a negative ex-post direct-cost
proxy. None of the 733 failed Take calls supplies the complete economics of a
rejected opportunity, so the Level 1 requirement of at least 20 genuinely
negative or rejected choices is not met.

The hurdle is consequently `profit_hurdle_partially_identified`. The
direct-cost-only candidate stays at zero. Successful-execution direct-margin
quantiles define
non-negative lower-bound sensitivities:

| Candidate profile | `risk_cost_rate` |
|---|---:|
| `direct_cost_only` | 0 |
| `keeper_hurdle_low` | 0.105100900480 |
| `keeper_hurdle_high` | 0.124431757397 |

These rates are not rejection-threshold estimates. Their role is to test how
much proportional surplus the current reduced-form interface can remove
before otherwise profitable opportunities cease to execute.

## Configuration and smoke validation

The candidate registry is
[`config/sensitivities/keeper_execution.yaml`](../../config/sensitivities/keeper_execution.yaml).
Its typed resolver is explicitly opt-in and records profile IDs, capacity,
hurdle rate, classification, source checksum and `runtime_adopted: false`.

A compact mixed-collateral smoke activates each low, central and high profile
against ETH and BTC opportunities in one global ranking. Each profile respects
one combined cap, retains two capacity-limited records and reports
cross-collateral allocation. A separate hurdle probe distinguishes profitable
and unprofitable opportunities. Ordinary simulation code never imports the
candidate registry, so its absence preserves legacy behaviour exactly.

## Provenance and limitations

The compact evidence is under
`data/provenance/calibration/keeper/`. Detailed hourly diagnostics and the
immutable pre-registration snapshot are ignored under
`outputs/diagnostics/calibration/keeper_execution/<scientific-identity>/`.

Important limitations are:

- only two bounded unsafe-inventory windows are available, one with no unsafe
  demand;
- calendar stability fails and the non-stress high-demand sample is small;
- observed throughput is a lower bound on latent physical capacity;
- intra-hour unsafe arrivals can make closures exceed start inventory;
- the mixed-versus-dominant composition comparison is underpowered;
- the current profit equation assigns the protocol penalty as keeper gross
  reward and is not a full auction-profit model; and
- rejected opportunities are not observed with complete economics.

## Next experimental boundary

This study does not run an integrated simulation. A separately authorised
next step may construct one ETH-only empirical profile with 500 vaults,
empirical market, gas and liquidation-arrival inputs, the shared central
capacity, one registered hurdle profile, and the accepted Stage 1
response/confidence settings. That experiment must preserve the present
candidate-only provenance and must not reinterpret the count as
collateral-specific capacity.
