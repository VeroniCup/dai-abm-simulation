# Final held-out validation

## Scientific role

Final validation is an evaluative frozen-model comparison, not calibration
and not an exact replay of historical Maker auctions. Historical ETH, WBTC,
USDC and network-gas paths drive the simulation. Observed DAI is used only as
a comparison target. Standardised vault states, omitted owner intervention
and abstracted auction microstructure remain explicit limitations.

The validation freeze binds the scientific source, robustness decision,
Stage 1 coefficients and residual process, keeper and oracle registries,
historical source checksum, portfolios, metrics, decision hierarchy and the
no-retuning declaration before any held-out simulation.

## Window audit

The historical source covers 2021-06-01 to 2024-07-01 hourly and has SHA-256
`86ed2ac5a5d364cc57e8b41e137ef369a0fce7a393d386b4b38fc1ebd1be0545`.

| Stage | Half-open interval | Status |
| --- | --- | --- |
| Quiet | none | `quiet_validation_not_separately_registered` |
| November 2022 generalisation/FTX | 2022-11-01 00:00 to 2022-11-21 00:00 UTC | one canonical held-out observation |
| USDC/SVB | 2023-03-06 00:00 to 2023-03-20 00:00 UTC | held out and executed last |

Historical notes used the November interval for both quiet/generalisation and
FTX. It is counted once, not presented as two independent observations. No
distinct, result-blind quiet window satisfying the registration rules exists,
so no quiet simulation is invented.

## Frozen simulations

The FTX stage uses `empirical_crypto` for 128 vault-population replications.
The USDC/SVB stage uses `empirical_crypto` as a zero-STABLE negative control
and `stable_supported` as the primary stable-exposure portfolio, 128
replications each. Every stage retains 500 vaults, 2.5 million DAI, shared
capacity 26, direct-cost-only execution, Stage 1-only confidence, zero oracle
delay and no synthetic shock overlay.

USDC returns determine the STABLE validation path only. In the negative
control there is no STABLE debt exposure, liquidation or backlog, and there
is no registered non-vault stablecoin transmission route. Full transaction
gas is represented through the frozen component-gas interface using the
historical hourly network price.

## Comparisons and decision boundary

Observed diagnostics include collateral drawdowns and dependence, stablecoin
floor, DAI minimum and deviation burden, gas conditions and observed recovery
duration. Simulated distributions include unsafe inventory, eligible tab,
liquidation completion, backlog, unresolved debt, bad debt, capacity use,
keeper rejection, DAI deviations and censored recovery.

Comparable DAI metrics are labelled broadly compatible, overstated or
understated. Maker-state outcomes without a like-for-like historical target
are labelled structurally unavailable rather than assigned a fabricated
observed value. No numerical fit score is used.

`final_validation_supportive_with_limitations` requires both available
operational stages to be directionally or partially consistent and no
opposite mechanism. Mixed over- and under-statement remains
`final_validation_mixed`; systematic opposition is not supportive. Technical
invalidity is reserved for data, leakage, identity, accounting, negative-
control or deterministic-reconstruction failure.

## Irreversible order and no retuning

The quiet blocked decision is frozen first, followed by the November FTX
summary and then USDC/SVB. A later window is not inspected through the
simulation workflow before the prior stage's compact evidence exists.

The tracked declaration states that validation findings are evaluative:
unfavourable results are retained as limitations and do not trigger model
retuning. Model, parameter, scenario, metric-rule and production-adoption
change counts must all remain zero.

## Results and reproducibility

The freeze identity is
`1bc40998534dd3842a229c701743494147d24832d956622411afba7863d3c295` and
the validation identity is
`a5e281a810892454539f0528c30536696d01c664bbd6cceda17584b88d5f3ed2`.
No distinct quiet stage was executed: it remains
`quiet_validation_not_separately_registered` with zero simulations and is a
registration limitation rather than a technical failure.

### November 2022 generalisation/FTX holdout

The 480-hour path recorded ETH and WBTC window log returns of -0.3143 and
-0.2349, hourly return correlation of 0.9264, a DAI minimum of 0.99623 and
median/p95 gas prices of 14.98/41.34 gwei. Across 128 simulations, mean unsafe
vault share was 0.0300, completed liquidations 24.34, liquidated-debt share
0.0853, backlog-area share 0.2099 and maximum unresolved-tab share 0.0646.
Mean simulated minimum DAI price was 0.99640, recovery probability was one
and mean restricted recovery time was 25.08 hours. The result is
`ftx_validation_directionally_consistent`: collateral stress and liquidation
pressure activate in the expected direction, while exact magnitude remains
non-comparable to historical Maker because vault states are standardised,
owner intervention is omitted and auction microstructure is abstracted.

### March 2023 USDC/SVB holdout

The final 336-hour path recorded a USDC minimum of 0.90199, DAI minimum of
0.90512, DAI mean absolute deviation of 0.00720 and observed recovery duration
of 216 hours. The zero-STABLE `empirical_crypto` negative control passed. In
128 `stable_supported` simulations, the mean initial STABLE debt exposure was
625,000 DAI, but stable-attributed liquidated debt and stable backlog were both
zero. Mean unsafe share was 0.000094, completed liquidations 0.086,
liquidated-debt share 0.000032 and backlog-area share 0.000067. Mean simulated
minimum DAI price was 0.99657 and recovery probability 0.9844. The model
therefore under-activates the stable-vault channel relative to the observed
event, consistent with its high standardised initial collateralisation and
absence of an additional non-vault stablecoin transmission mechanism. The
classification is `usdc_svb_stable_channel_underactive`.

### Overall decision

The technically valid evidence is `final_validation_mixed`: the FTX stage is
directionally consistent, while the USDC/SVB stage materially understates the
stablecoin channel. This limitation is retained rather than repaired. The
no-retuning declaration records zero model, parameter, scenario, metric-rule
and production-adoption changes and states that validation findings are
evaluative.

The FTX stage completed 128 simulations in 46.794 seconds. USDC/SVB completed
256 simulations; its uninterrupted orchestration took 72.108 seconds and a
post-execution evidence aggregator then required an evidence-only resume from
all 128 existing checkpoints. No substantive simulation was retried. Both
checkpoint audits found no missing, duplicate or orphan records. Rebuilding
all non-host-dependent artefacts twice produced byte-identical files.
Detailed checkpoints remain ignored under
`outputs/validation/final/<validation_identity>/`; exactly 11 compact
artefacts are retained under `data/provenance/validation/final/` and
registered in the validation manifest.
