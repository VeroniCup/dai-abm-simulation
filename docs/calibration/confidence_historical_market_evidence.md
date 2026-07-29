# Historical market evidence for confidence calibration

## 1. Purpose and stop rule

This record closes the pre-registered Design C market-evidence extension. It
acquires one consistent hourly DAI/ETH source from 31 December 2019 to 1 July
2024, compares it with the existing June 2021–June 2024 panel and applies the
fixed no-fit burden and predictor gates.

The extension is valid and adopted. Design C nevertheless fails its
pre-registered episode-dominance gate. No coefficient is fitted. Under the
declared final stop rule, the predictive stress-proxy regression route is now
closed and the next behavioural-calibration method is constrained simulated
moments using the continuous burden distribution and recovery moments.

## 2. Sparse-predictor transformation

For a non-negative predictor \(x_t\), the calibration-owned transformation is:

\[
s(x_t)=\min\left(1,\frac{x_t}{Q^+_{0.95}(x)}\right),
\]

where \(Q^+_{0.95}\) is the 95th percentile of strictly positive calibration
observations. A true zero remains zero, positive magnitude is retained and
values above the scale are capped at one. The result is not centred.

The scale is eligible only with at least 100 positive observations, 12
positive calendar months, two positive years, 20 distinct positive values and
a finite positive \(Q^+_{0.95}\). Quiet and final-stress validation evidence
does not determine the scale.

The transformation applies to the lagged below-peg gap and lagged 24-hour ETH
downside. Tab pressure remains a sensitivity predictor and possible recovery
gate; it is not transformed or admitted to the primary Design C model.

## 3. Source inventory

The existing operational market panel was traced to Dune `prices.hour`, query
8043702 and execution `01KY0815CKMZYWJJF7QZ2N1GSM`. It identifies ETH through
the Ethereum WETH contract and DAI through the canonical Ethereum DAI
contract. Its reported source is CoinPaprika throughout.

Metadata inspection confirmed:

- `prices.hour` retains `timestamp`, `blockchain`, `contract_address`,
  `price`, `volume`, `source` and `contract_address_varchar`;
- the table documents volume-weighted hourly pricing and carry-forward when no
  trade is observed;
- `prices_external.hour` is available as the next source-specific fallback;
  and
- the external CoinDesk credential was unavailable, but no fallback was
  required.

Coinbase was not used because the primary route passed.

## 4. Source-selection order

The declared order was:

1. exact extension of the existing source;
2. `prices_external.hour`;
3. the current hybrid `prices.hour`;
4. full-range CoinDesk aggregate evidence; and
5. source-adoption review.

The first route passed. No provider boundary was introduced and no later
source was inspected for a more favourable outcome.

## 5. Credentials and access

The existing `DUNE_API_KEY` environment convention was available. The key was
not printed, persisted or interpolated into SQL. No paid subscription or
external API purchase was made.

Dune usage increased from 1,042.408 to 1,260.942 credits, an observed delta of
218.534 credits including execution and result access. Dune did not expose a
separate compute/export split through the read-only query metadata used here.

## 6. Acquisition method

The private temporary query is:

- query: 8145897;
- execution: `01KYP8NPE5XH2KN926949AYKGT`;
- engine: Small;
- SQL: `sql/market/templates/hourly_market_prices.sql`;
- SQL SHA-256:
  `1bc8ff155372731c435ab330d10e16e262c5df29557ff84ffe4cd111dc7babfc`.

It executed once. The completed result was retrieved in three deterministic
pages of at most 32,000 rows. Page offsets advanced contiguously and the final
ordered result contained 78,912 rows. No query was retried.

## 7. Asset identity

| Model asset | Dune instrument | Blockchain | Contract |
| --- | --- | --- | --- |
| ETH | WETH | Ethereum | `0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2` |
| DAI | DAI | Ethereum | `0x6b175474e89094c44da98b954eedeac495271d0f` |

Both prices are USD-denominated `prices.hour.price` values. Symbols alone are
never used for identity.

## 8. Raw and processed schemas

The ignored raw file is long-format with:

`timestamp_utc`, `asset`, `dune_instrument`, `price_usd`, `blockchain`,
`contract_address`, `source`, `volume_usd`.

The ignored processed evidence has one row per hour with:

- timestamp;
- DAI and ETH prices;
- DAI and ETH sources;
- source volumes;
- source identifiers;
- quality flags; and
- the ETH hourly log return.

The repository does not interpolate, forward-fill, smooth, clip or winsorise
prices. The first ETH return remains structurally missing.

## 9. Hourly coverage

The half-open interval contains 39,456 hours, computed from its boundaries.
Each asset has exactly 39,456 observations. Validation found:

- zero missing asset-hours;
- zero duplicate asset-hours;
- zero invalid, naive or non-UTC timestamps;
- zero out-of-range rows;
- zero null, non-finite or non-positive prices;
- one Ethereum contract identity per asset; and
- CoinPaprika as the sole reported source, with zero source changes.

DAI ranges from 0.9051239167 to 1.1291393333 USD. ETH ranges from
105.0691666667 to 4,851.8675 USD.

## 10. Stale-run diagnostics

Neither DAI nor ETH has a run of six or more identical hourly prices. The
longest qualifying run is therefore zero hours. Source volume is unavailable
for all 78,912 rows, so volume cannot independently identify provider-side
carry-forward. The absence of long identical-price runs means no detected
stale run affects a burden label, an ETH downside calculation or a fixed
validation interval.

This is evidence against a material long stale run, not proof that no
individual provider-filled hour exists.

## 11. Overlap comparison

All 27,024 existing hours match on timestamp for both assets. Differences are
limited to CSV floating representation:

| Statistic | DAI | ETH |
| --- | ---: | ---: |
| Mean absolute difference | \(2.24\times10^{-16}\) | \(5.24\times10^{-13}\) |
| Median absolute difference | \(2.22\times10^{-16}\) | \(4.55\times10^{-13}\) |
| 99th percentile | \(7.77\times10^{-16}\) | \(2.27\times10^{-12}\) |
| Maximum | \(1.11\times10^{-15}\) | \(4.55\times10^{-12}\) |
| Maximum relative difference | \(1.11\times10^{-15}\) | \(1.26\times10^{-15}\) |
| Price correlation | 1.0 | 1.0 |

ETH log-return correlation is effectively one. DAI has zero disagreements for
the 0.995 threshold, 0.99 threshold and symmetric recovery band. There are
zero six-hour burden differences above \(10^{-12}\); the total numerical
burden difference is \(2.41\times10^{-12}\).

November 2022 and USDC/SVB have no price-label disagreement. Two Terra/CeFi
prices differ only in floating representation and do not change burden.

## 12. Source-adoption decision

The candidate is adopted as an **exact-source extension apart from documented
floating representation**. It uses the same table, contracts, price field,
source semantics, aggregation and UTC convention over the complete interval.

The established four-asset panel remains the operational market panel. The
new full-range DAI/ETH panel is the canonical confidence-calibration evidence,
because acquiring unrelated WBTC and USDC history would add export cost
without contributing to this design.

## 13. Design C partition

Calibration covers the complete interval excluding:

- quiet validation: 1–21 November 2022; and
- final downside-stress validation: 6–20 March 2023.

Terra/CeFi remains development evidence in calibration. USDC/SVB remains
untouched by scaling and model-design choices.

Origins remain fixed at 00:00, 06:00, 12:00 and 18:00 UTC. Predictor data use
only the preceding 24 hours and outcomes use the six hours from the origin.
The structurally missing first ETH return removes only the otherwise earliest
boundary origin.

## 14. Burden feasibility

For the primary midnight anchor:

| Quantity | Result |
| --- | ---: |
| Retained calibration origins | 6,427 |
| Non-zero burden | 321 |
| Burden at least 0.10 | 186 |
| Burden at least 0.25 | 121 |
| Burden at least 0.50 | 61 |
| Mean burden | 0.012034 |
| Positive-burden median | 0.148489 |
| Positive-burden IQR | 0.370769 |
| 90th / 95th / 99th percentile | 0 / 0 / 0.460515 |
| Total burden | 77.340128 |
| Contributing episodes | 74 |

Burden occurs in both 2020 (68.747133) and 2021 (8.592994). Later calibration
years contribute zero. Five burden gates pass, but the largest episode
contributes 56.55% of total burden against the fixed 25% ceiling.

That episode begins on 6 December 2020 at 02:00 UTC and closes after the
24-hour normal run on 4 January 2021 at 09:00 UTC. It contributes 43.733350
burden. Prices vary within the episode, no six-hour identical-price run is
present and source identity does not change. The dominance is therefore an
observed concentration, not a detected stale-run artefact.

All six origin anchors contain 74 contributing episodes and total burden
77.340128. Their non-zero counts range from 310 to 321. Every anchor fails the
same 25% dominance gate.

## 15. Predictor feasibility

Both primary predictors pass every sparse-scaling gate:

| Predictor | Positive count | Months | Years | Distinct positives | \(Q^+_{0.95}\) | Capped share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Lagged below-peg gap | 1,012 | 51 | 5 | 997 | 0.0083080667 | 0.7935% |
| Lagged 24-hour ETH downside | 3,062 | 54 | 5 | 3,062 | 0.0863260329 | 2.3961% |

The scaled-predictor correlation is 0.02396. Quiet validation has no peg-gap
value above its frozen scale and six ETH-downside observations above it. Final
stress validation has ten peg-gap and one ETH-downside observations above the
frozen scales. Those observations are capped at one without changing either
scale.

## 16. Final Design C decision

The exact classification is:

**Market extension acquired, but fitting still unsupported.**

The source is valid and both predictors are transformable. The sole failed
gate is episode dominance. It may not be weakened after observing Design C,
and a more favourable start date may not be searched. No fractional model,
coefficient, penalty or interaction has been fitted.

The predictive target-extension route is now closed. The authorised next
methodological boundary is the already declared constrained SMM fallback,
using the continuous burden distribution, deterioration and recovery moments,
blocked validation and leave-one-event-out checks.

## 17. Evidence and provenance ownership

Ignored payloads:

- `data/market/raw/dune_prices_hourly_dai_eth_2019-12-31_2024-06-30.csv`;
- `data/market/processed/dune_hourly_dai_eth_market_prices_processed.csv`;
- detailed market acquisition, harmonisation and validation JSON under
  `data/market/provenance/`.

Tracked compact evidence:

- `data/provenance/calibration/confidence/historical_market_coverage.json`;
- `historical_market_harmonisation.json`;
- `sparse_predictor_scaling.json`; and
- `design_c_feasibility.json`.

Their checksums are registered in
`data/provenance/calibration/manifest.json`. The general data manifest retains
both the original four-asset acquisition and this two-asset extension.

## 18. Remaining boundary

No further market acquisition, threshold redesign or regression fitting is
required for this predictive route. A separately authorised SMM pass must
still specify its moments, weighting, bounds, blocked validation and
leave-one-event-out diagnostics before estimating behavioural parameters or
changing simulator behaviour.
