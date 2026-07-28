# Representative vault calibration

## Motivation

Phase 1E originally proposed reconstructing every target-ilk Vat mutation from
late 2019 to June 2024. Discovery, diagnostics and five production months have
now established that the source tables, signed values, liquidation linkage,
ownership mapping, numeric trace ordering, atomic persistence and pagination
controls are technically sound. They also show that exporting a complete
15-column mutation history has a low information-to-credit ratio for the
dissertation's calibration questions.

The revised objective is therefore to estimate behaviour from deliberately
selected market and protocol regimes. This is a methodological refinement, not
an acquisition failure. All validated discovery and production artefacts remain
authoritative evidence that the extraction method works.

## Methodological justification

The simulator requires distributions and conditional behaviours, not an exact
reproduction of every historical vault. Representative windows are defensible
when they:

- cover ordinary activity and several economically different stress mechanisms;
- preserve exact on-chain ordering and accounting inside each window;
- retain target-ilk and protocol-version distinctions;
- estimate conditional distributions within regimes;
- reserve at least one window for validation; and
- report sensitivity to the choice and weighting of windows.

Purposive windows must not be treated as a random sample of calendar time.
Unconditional arrival probabilities and regime persistence will continue to be
estimated from the continuous Phase 1A market panel, Phase 1B gas panel and
Phase 1C liquidation-count series. Phase 1E-B will estimate conditional vault
sizes, leverage, mutation behaviour and owner responses. Window observations
will be weighted by their actual exposure time or by an explicitly reported
target regime mixture; stress windows will not receive equal calendar weight by
default.

The pre-Liquidations-2.0 evidence is retained for method validation and owner
behaviour comparisons. It will not be pooled uncritically with Liquidations 2.0
auction outcomes.

### Quiet-mature implementation note

The first authorised tranche is recorded in
[quiet-mature acquisition report](../archive/phase_reports/phase1e_b_tranche1_acquisition_report.md).
Quiet-mature boundary, mutation and ownership evidence passed, and its
historically unbounded rate result was replaced by the bounded Method B
extraction. The same architecture subsequently completed the USDC/SVB window
with exact replay and a 90.800-credit observed delta. The detailed records are
the [quiet-mature report](../archive/phase_reports/phase1e_b_tranche1_acquisition_report.md) and the
[USDC/SVB acquisition report](../archive/phase_reports/phase1e_b_usdc_svb_acquisition_report.md).

## Representative calibration windows

The market evidence below was calculated locally from the validated market and
gas panels. Row and credit ranges are retained as historical planning estimates
for comparison with realised acquisition records. Quiet mature, USDC/SVB and
Terra/CeFi have authoritative realised dimensions and costs in their linked
acquisition reports. Credit forecasts used the observed March 2020 rate of
approximately 0.0060 credits per exported 15-column mutation row; execution
overhead and pricing changes remain uncertain.

| Role | Half-open window | Empirical motivation and model use | Expected mutation rows | Expected incremental credits |
|---|---|---|---:|---:|
| Method validation: early stable system | 2020-02-01 to 2020-03-01 | Pre-shock comparison immediately before Black Thursday. Supports parser, accounting and ordinary mutation-rate validation under the earlier liquidation architecture. | 30,906 validated | 0 |
| Method validation: Black Thursday | 2020-03-01 to 2020-04-01 | Extreme collateral stress, deleveraging and liquidation-linked state changes. Used as a legacy stress comparison, not as a Liquidations 2.0 auction calibration sample. | 43,081 validated | 0 |
| Bull market and multi-collateral expansion | 2021-11-15 to 2021-12-06 | Covers elevated crypto prices and gas plus the validated WBTC-B and WBTC-C activation boundaries on 22 and 29 November. Helps identify borrowing, collateral addition, leverage and cross-ilk adoption behaviour. Median hourly gas was about 118 gwei in this window. | 10,500–21,000 | 63–127 |
| Terra and CeFi contagion | 2022-05-05 to 2022-06-20 | Prolonged risk reduction rather than a single crash hour. The local market panel records an ETH hourly return as low as approximately -6.2%, and stablecoin deviations above 2% occurred. Helps estimate repayment, withdrawal, top-up, liquidation clustering and persistence conditional on extended stress. | 23,000–46,000 | 139–277 |
| FTX stress, withheld validation | 2022-11-01 to 2022-11-21 | A sharp crypto-specific shock with an ETH hourly return near -7.8% but materially lower gas than late 2021. Held out from primary vault-behaviour estimation to test whether parameters learned elsewhere reproduce deleveraging and liquidation direction. | 10,000–20,000 | 60–121 |
| USDC/SVB depeg | 2023-03-06 to 2023-03-20 | Distinguishes stablecoin contagion from a pure crypto crash. The validated panel records maximum absolute DAI and USDC deviations of about 9.5% and 9.8%. Helps assess whether ETH/WBTC vault owners change debt or collateral during a stablecoin-led disturbance. | 7,000–14,000 | 42–85 |
| Quiet mature market | 2024-02-01 to 2024-03-01 | Recent low-volatility baseline after protocol maturation. The 99th percentile absolute ETH hourly return was about 1.4%, and DAI/USDC deviations remained below about 0.23%. Establishes ordinary borrowing, repayment and owner-intervention baselines. | 7,250–14,500 | 44–88 |

The table's original five-window forecast was approximately 57,750–115,500
mutation rows and 348–698 credits, with a 15% operational allowance of roughly
400–803 credits. These figures are planning provenance, not current acquisition
status. Realised dimensions and costs supersede them wherever a linked
acquisition report exists.

## Calibration mapping

The four evidence classes used here are:

- **empirical estimation**: estimated from validated observations;
- **protocol constants**: read from effective-dated governance or contract
  settings;
- **literature**: used only when the mechanism is supported but not identified
  by the available on-chain data; and
- **scenario assumptions**: controlled experimental choices or sensitivity
  parameters.

| Model quantity | Primary evidence class | Evidence and treatment |
|---|---|---|
| Initial ETH, WBTC, stable and DAI prices | Empirical estimation | Phase 1A price at the simulation or replay start. |
| Return, volatility and cross-asset dependence | Empirical estimation | Continuous Phase 1A panel; regime-conditioned block sampling. |
| Gas regimes and gas-price distributions | Empirical estimation | Continuous Phase 1B panel. |
| Shock arrival and persistence | Empirical estimation | Continuous market/gas regime series, not the purposive vault windows. |
| Shock magnitude and recovery | Empirical estimation | Conditional tails and continuous historical blocks; scenario quantiles reported. |
| Shock onset in controlled experiments | Scenario assumptions | Common onset step used for comparability. |
| Liquidation ratio and penalty | Protocol constants | Effective-dated Phase 1D settings by exact ilk. |
| Debt ceilings, dust and auction settings | Protocol constants | Effective-dated Phase 1D settings; used where represented by the model. |
| Maximum close factor | Protocol constants or scenario assumptions | Use a documented protocol analogue where one exists; otherwise retain the explicit stylised model setting. |
| Oracle delay | Empirical estimation or protocol constants | Estimate observed delay where available and anchor permissible behaviour to oracle configuration. |
| Simulated vault count | Scenario assumptions | Computational scale; attach empirical weights and test scale robustness. |
| Collateral composition | Empirical estimation for baseline; scenario assumptions for counterfactuals | Observed debt shares define the historical baseline; five portfolio designs remain controlled experiments. |
| Vault debt, collateral ratio and leverage | Empirical estimation | Representative cross-sectional snapshots, stratified by exact ilk and regime; sample debt and ratio jointly. |
| Collateral amount | Empirical estimation and accounting identity | Derived consistently from sampled debt, collateral ratio and price. |
| Borrowing, repayment, deposit and withdrawal behaviour | Empirical estimation | Signed `frob` and expanded `fork` mutations within representative windows, conditional on regime, ilk and observable pre-action state. |
| Vault-owner intervention near liquidation | Empirical estimation where identifiable | Top-up and repayment hazards; otherwise retain as a sensitivity extension rather than a fitted coefficient. |
| Owner heterogeneity | Empirical estimation with limitations | Manager owner/proxy, CDP and urn mapping. Direct urns remain unmapped; manager owner is not claimed to be the beneficial owner. |
| Liquidation frequency and clustering | Empirical estimation | Phase 1C event and hourly panels, normalised by vault or debt exposure where available. |
| Liquidation timing, size and auction outcomes | Empirical estimation | Phase 1C auction facts and summaries, conditioned on collateral and gas regime. |
| Keeper gas units and transaction cost | Empirical estimation | Clean successful-Take transactions joined to actual gas price and ETH/USD; other transaction classes used for sensitivity. |
| Keeper participation and capacity | Empirical estimation | Unique keeper participation, clean transaction classes, completion rates and high-demand throughput from Phase 1C. |
| Keeper profitability threshold | Empirical estimation plus literature/sensitivity | On-chain proceeds and gas support a proxy; omitted inventory, capital and hedging costs require literature bounds and sensitivity analysis. |
| DAI peg reversion and residual noise | Empirical estimation | Continuous Phase 1A DAI series, conditioned on market and liquidation regimes. |
| Confidence sensitivity and panic selling | Scenario assumptions calibrated to empirical moments | Minimum-distance calibration against several peg, liquidation and bad-debt moments; not described as directly observed. |
| Stable-depeg transmission to confidence or demand | Scenario assumptions unless identified | Add only if the existing model fails validation; use literature and sensitivity bounds. |
| Random seed | Scenario assumptions | No empirical interpretation; use common random numbers and multiple seeds. |

## Acquisition roadmap and realised order

The original priority order below is retained to explain the information-per-
credit design. Completion status is recorded in the current project status and
the archived acquisition reports.

1. **Reuse February and March 2020** — no new Dune work; document the
   pre-Liquidations-2.0 limitation.
2. **USDC/SVB depeg** — short, distinctive, and directly relevant to stablecoin
   contagion.
3. **Quiet mature market** — supplies the ordinary behavioural baseline needed
   to interpret all stress windows.
4. **Bull market and WBTC-B/C activation** — identifies multi-collateral
   adoption and leverage under high gas.
5. **FTX window** — acquire and lock as a withheld validation set.
6. **Terra/CeFi window** — acquire last because it is longest and costliest,
   while providing the strongest evidence on persistent stress.

For every new window:

1. render an exact half-open bounded query from the validated template;
2. record usage and persist query/execution identifiers before retrieval;
3. inspect the reported row count before exporting;
4. apply the deterministic 32,000-row pagination policy;
5. persist pages and final files atomically;
6. validate source keys, numeric trace ordering, signed values, contract and
   ilk scope;
7. update the representative-window ledger; and
8. stop on the first execution, retrieval, persistence, validation or credit
   failure.

Validated windows are resumable and are never re-executed. A partial window is
not admitted to calibration. A row-count forecast above the window's credit
ceiling triggers an explicit scope review rather than an automatic narrower
query.

## State and sampling workflow

Mutation windows alone cannot provide an unbiased cross-section of all vaults:
vaults that do not transact would be absent. Phase 1E-B therefore separates:

- **cross-sectional vault snapshots**, including an inactive-vault sample, for
  debt, collateral-ratio, leverage and concentration distributions;
- **window mutation ledgers** for borrowing, repayment, collateral adjustment
  and intervention hazards;
- **Phase 1C liquidation records** for auction and keeper behaviour; and
- **Phase 1D effective settings** for protocol constants and debt conversion.

An opening balance is never inferred from the first mutation in a window.
Before state reconstruction, each window must obtain a validated authoritative
opening snapshot or a targeted pre-window history for the affected urns. If
neither is available, the window remains suitable for signed-flow analysis but
not level-based collateral-ratio estimation.

## Validation workflow

Each window must pass:

- exact UTC boundaries and exact six-ilk scope;
- canonical successful `frob`, `fork` and `grab` calls only;
- unique source keys and deterministic numeric trace ordering;
- exact signed integer preservation and balanced local `fork` expansion;
- Bark–grab reconciliation without double-counting;
- complete transaction-order linkage;
- no materially negative reconstructed balances;
- authoritative opening-state evidence for every level-based observation;
- effective protocol-parameter and accumulated-rate joins;
- explicit mapped and unmapped owner populations; and
- cross-window schema equality.

Pooled calibration must additionally report window weights, effective sample
sizes, regime coverage, sensitivity to excluding each window and performance on
the withheld FTX window.

## Expected datasets

Phase 1E-B should produce:

- an immutable raw mutation file and validation report per representative
  window;
- representative opening snapshots or targeted opening-state records;
- a canonical event ledger retaining window and regime labels;
- post-event vault states where opening evidence is sufficient;
- cross-sectional calibration samples by exact ilk and regime;
- owner-intervention and borrowing/repayment summaries;
- a window-level calibration manifest containing queries, executions,
  checksums, dimensions, credits and inclusion decisions; and
- a separate withheld validation dataset.

It will not produce or claim a complete 2019–2024 vault census.

## Dissertation justification

The design supports a narrower and more credible empirical claim: the model is
calibrated to observed conditional behaviour across economically distinct
regimes and validated on data not used for fitting. This matches the
dissertation's purpose—mechanism-based stress testing—more closely than an
expensive historical census whose additional quiet-period mutations contribute
little identification.

The original exhaustive design remains documented because it motivated the
source discovery, ordering rules and accounting tests. Its validated
infrastructure establishes reproducibility; the representative design improves
statistical focus and cost proportionality.

## Limitations

- Purposeful windows do not identify calendar-time event probabilities without
  continuous exposure denominators.
- Window selection may affect behavioural estimates; leave-one-window-out and
  alternative-window checks are required.
- The 2020 windows use an earlier liquidation architecture and cannot directly
  identify Liquidations 2.0 keeper behaviour.
- Mutation-active vaults are not a representative cross-section of all vaults;
  snapshots or explicit sampling weights are required.
- Manager ownership is only an identity proxy.
- Exact beneficial ownership, off-chain keeper costs and hedging costs remain
  partly unobserved.
- Credit forecasts depend on Dune pricing and realised result dimensions.

## Terra/CeFi execution note

The 5 May–20 June 2022 Terra/CeFi window is complete. Its 5,111 boundary rows,
17,593 raw Vat mutations, 6,565 ownership records and 4,086-row sparse rate
ledger pass validation. Exact replay reconciles the closing boundary and all
649 Phase 1C Barks link unambiguously to canonical grabs. This operational
history does not revise the representative-window methodology. Details are in
the
[Terra/CeFi acquisition report](../archive/phase_reports/phase1e_b_terra_cefi_acquisition_report.md).
