# Phase 1E-B USDC/SVB Acquisition Report

## Scope and outcome

The authorised stress window is the exact half-open interval
`[2023-03-06 00:00:00 UTC, 2023-03-20 00:00:00 UTC)`. It covers `ETH-A`,
`ETH-B`, `ETH-C`, `WBTC-A`, `WBTC-B` and `WBTC-C`. These are the exact
ETH/WBTC vault ilks approved by the representative-regime strategy. PSM and
stablecoin-backed accounting were not added: the purpose is to observe how the
approved vault population responded to a stablecoin-led disturbance, while
Phase 1A supplies the contemporaneous DAI and USDC evidence.

All bounded source streams passed validation. Exact local replay of 1,892
canonical Vat mutations reproduced all 3,456 independently observed closing
states, with no negative state, ordering ambiguity or mismatch. No relevant
`Dog.Bark` or `Vat.grab` occurred in the window. The absence is retained as an
observation and is not interpreted as proof that liquidation exposure was
generally absent.

## Source architecture

The implementation reuses the quiet-mature architecture:

- the boundary query exports authoritative opening and closing `ink`, `art`
  and accumulated-rate state by exact `(ilk, urn)`;
- successful canonical `Vat.frob`, `Vat.fork` and `Vat.grab` calls are the only
  economic mutations;
- transaction ordering uses `ethereum.transactions.index`, followed by numeric
  trace position and stable source keys;
- manager `open` and `give` records supply owner/proxy annotations, not
  beneficial-owner identities;
- `Dog.Bark` is an annotation and never a second liquidation delta; and
- rate Method B combines one exact pre-window accumulated rate per ilk with a
  bounded stream of paired in-window `Jug.drip` and direct-child `Vat.fold`
  calls.

Maker fixed-point integers are preserved through state updates. Accrued debt is
calculated using Python `Decimal` precision 80 as
`art_raw × rate_raw_ray / 1e45`.

## Queries, executions and cost

Every Dune query was private, temporary, executed exactly once on Small and
retrieved exactly once after completion. Bark annotations were extracted
locally from the validated Phase 1C action fact.

| Stream | Query | Execution | Rows × columns | Observed credit delta | Result |
|---|---:|---|---:|---:|---|
| Boundary states | [8114261](https://dune.com/queries/8114261) | `01KYF8VPQX313BHVF26YJ7HVXJ` | 3,456 × 15 | 23.399 | Passed |
| Vat mutations | [8114306](https://dune.com/queries/8114306) | `01KYF99ZAGP21DYD8RHD6F6YQ8` | 1,892 × 15 | 11.388 | Passed |
| Ownership history | [8114317](https://dune.com/queries/8114317) | `01KYF9CDRX9MR7J5HXTKXT6K15` | 4,341 × 14 | 49.906 | Passed |
| Bark annotations | Local Phase 1C extract | — | 0 × 13 | 0.000 | Passed, zero observations |
| Sparse effective rates | [8114330](https://dune.com/queries/8114330) | `01KYF9EZP5HH8D6RKPAMQ6TWHK` | 1,356 × 12 raw | 6.107 | Passed |

Usage increased from 926.545 to 1,017.345 credits: 90.800 credits in total,
below the 180-credit hard cap. The remaining quota is 1,482.655 credits, above
the required 1,350-credit reserve. Dune did not separately expose compute and
export charges for these executions, so the observed usage deltas are the
authoritative cost measure.

The four persisted Dune source streams contain 11,045 rows. This is about
121.64 source rows per observed credit, 8.221 credits per 1,000 source rows,
37.24 active opening vaults per credit and 20.84 canonical mutation rows per
credit.

## Checksums and persisted outputs

The principal immutable raw CSV checksums are:

| Stream | SHA-256 |
|---|---|
| Boundary states | `61d10a65d278efa6076a64200c8a41132ac36d2973b49069d6eb54571ed4f7aa` |
| Vat mutations | `638c5814cfe36bbe04ad817a51e3fec3e2bc9e036fb489bed5d895a7bdbf1761` |
| Ownership history | `13ba0443fc3631822b85da4952f9b71885a5e0242f0b51b422e7216156fc30ce` |
| Bark annotations | `ab80435807eac38ffba793f8fe2bdea30a89966c27770553b82dd05443ab8bcf` |
| Effective-rate changes | `eb364f6c9cac56d8a897198e04928e6906b8c739329ee9c8fcf2a3743f84d2eb` |

The principal processed checksums are:

| Output | Rows | SHA-256 |
|---|---:|---|
| Opening vault state | 3,456 | `35e34954d2916b4829798547bc7a62e249329777fe961719421567d24ce67bac` |
| Closing vault state | 3,456 | `4072c2cdf4a3b9ae5c26e7e9986c87c6b993f921c3a86a70a0e2301a8502df27` |
| Sparse effective rates | 1,362 | `bff9aca3be2c1cdb818b4c84456860b7b421ea5a4e1311c86b5046b93bf8489f` |
| Reconstructed vault events | 1,892 | `2decf135f26eda7b9c0f186e0e96090a22a0899c4e81d5c72aad3e47699be04e` |
| Reconstructed snapshots | 6,912 | `986478ce6d82d69962018c6f47042dcad517d5caf76fc916ed34355d76dc2151` |
| Behaviour summary | 6 | `19ba192c61cdec7ffd64fdc8931019d601aa1cbdb97625982401f12b85ed6306` |
| Quiet-versus-USDC/SVB comparison | 7 | `165e8fc8312ec28ec466894a870d9403ba852312296df4b563303d415ea801cc` |
| Parameter readiness | 10 | `c8782ca1d7ce17440dd7bc58faa6704f43f50a97edffc4ab183c907f35388d69` |

Page-level checksums, SQL checksums, retrieval bounds and execution state are
recorded under
`data/provenance/vaults/representative_regimes/usdc_svb_2023-03-06_2023-03-20/`.

## Vault evidence and replay validation

The boundary contains 3,381 active and 1,934 indebted opening vaults. The
closing boundary contains 3,311 active and 1,868 indebted vaults. Of the active
opening population, 3,287 vaults have a manager CDP mapping and 94 are direct or
otherwise unmapped. The ownership stream contains 3,362 `open` records and 979
ordered `give` transitions.

All 1,892 mutations are successful frobs; no fork or grab occurred. Exclusive
mutation classification gives 307 deposits, 383 withdrawals, 422 draws, 341
repayments, 436 combined adjustments and three no-state-change calls. The
non-exclusive economic indicators used in the behaviour comparison count 526
positive collateral deltas, 600 negative collateral deltas, 641 positive debt
deltas and 558 negative debt deltas.

The sparse rate output contains six opening-rate rows, 678 `Jug.drip` rows and
678 matching `Vat.fold` rows. Every fold delta reconciles, no duplicate or
ordering ambiguity remains, and every final accumulated rate matches the
independent closing boundary.

Replay validation reports:

- zero negative event states;
- zero duplicate or unresolved source-order keys;
- zero opening-to-closing `ink` or `art` mismatches;
- zero rate or accrued-debt mismatches;
- zero Bark/grab ambiguity, unmatched Bark or unmatched grab; and
- zero liquidation double-counting.

## Descriptive quiet-versus-stress evidence

The comparison is descriptive and does not establish causality. The
USDC/SVB window is fourteen days while quiet mature is twenty-nine days, so raw
flow counts should not be compared without exposure adjustment.

At opening, USDC/SVB contains 3,381 active and 1,934 indebted vaults versus
3,296 and 1,886 in quiet mature. Its pooled median debt is about 15,810 DAI
versus 20,158 DAI, and its pooled median collateral ratio is about 4.071 versus
4.456. Relative to quiet mature, USDC/SVB has more withdrawals and repayments
despite its shorter duration, but fewer draws and fewer distinct intervening
urns. No grab occurs in either window. The exact-ilk table retains material
heterogeneity: ETH-A has a lower median collateral ratio in USDC/SVB, while
ETH-B and WBTC-B have higher medians. These differences are retained by regime
and exact ilk rather than pooled into a single behavioural effect.

## Parameter evidence readiness

The ten Phase 1E-B-dependent parameters now have the following evidence status:

| Parameter | Quiet observations | USDC/SVB observations | Combined | Status |
|---|---:|---:|---:|---|
| `n_vaults` | 3,296 | 3,381 | 6,677 | `ready_for_estimation` |
| `target_debt_share` | 1,886 | 1,934 | 3,820 | `ready_for_estimation` |
| `debt_mean` | 1,886 | 1,934 | 3,820 | `ready_for_estimation` |
| `debt_std` | 1,886 | 1,934 | 3,820 | `ready_for_estimation` |
| `collateral_ratio_mean` | 1,886 | 1,934 | 3,820 | `ready_for_estimation` |
| `collateral_ratio_std` | 1,886 | 1,934 | 3,820 | `ready_for_estimation` |
| `min_collateral_ratio_buffer` | 1,886 | 1,934 | 3,820 | `ready_for_estimation` |
| `max_close_factor` | 0 | 0 | 0 | `insufficient_observations` |
| `max_normal_liquidatable_share` | 1,886 | 1,934 | 3,820 | `ready_for_estimation` |
| `max_stress_liquidatable_share` | 0 | 1,934 | 1,934 | `ready_for_estimation` |

These statuses authorise later estimation work; they do not adopt values.
`max_close_factor` still requires complementary Phase 1C liquidation evidence
and preferably a representative window containing linked grabs.

## Limitations and next windows

The exact six-ilk scope does not identify PSM accounting or stablecoin-backed
vault behaviour. Manager ownership is a proxy, and direct urns remain
legitimate unmapped observations. Purposeful windows do not identify
calendar-time event probabilities without continuous exposure denominators.
Neither quiet mature nor USDC/SVB contains a liquidation, so close-factor
evidence remains weak.

Bull expansion remains methodologically useful for WBTC-B/C adoption and
high-gas behaviour. Terra/CeFi remains useful for prolonged deleveraging,
liquidation clustering and persistence. Given the available quota, the next
authorisation should prioritise the window with the largest remaining
identification gain and retain the 1,350-credit reserve. No FTX calibration
window, mutation sample, market sample or liquidation sample was acquired or
used. The effective ownership table necessarily retains older `open` and
`give` records, including some with November 2022 timestamps, solely to
establish the owner/proxy state at the USDC/SVB boundary; these identity
records are not treated as FTX behavioural or validation evidence.
