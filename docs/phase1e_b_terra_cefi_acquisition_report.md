# Phase 1E-B Terra/CeFi acquisition report

## Scope and status

The representative Terra/CeFi window is `[2022-05-05 00:00 UTC,
2022-06-20 00:00 UTC)`: 1,104 hours for `ETH-A`, `ETH-B`, `ETH-C`,
`WBTC-A`, `WBTC-B` and `WBTC-C`. Boundary state, canonical Vat mutations,
manager ownership, sparse accumulated rates, local liquidation linkage and
exact replay are complete and validated. Bull expansion and the withheld FTX
window were neither acquired nor used.

The method treats successful `Vat.frob`, `Vat.fork` and `Vat.grab` calls as
economic state mutations. `Dog.Bark` is an annotation only. State is updated
with exact integers and DAI debt is calculated as
`art_raw * rate_raw_ray / 1e45`; market and protocol quantities use the
validated Phase 1A and Phase 1D panels.

## Dune streams and cost

| Stream | Query | Execution | Rows | SHA-256 | Credits |
|---|---:|---|---:|---|---:|
| Boundary | 8114864 | `01KYFDJ837CX994C5M7X86NQTK` | 5,111 | `5e23c678b77490e4c9e9c06024a1aaf37d9ac2aebfe362b32b1a70bb6475b79a` | 0.393 |
| Vat mutations | 8114886 | `01KYFDPTRNR88V6GFBY26EF3QW` | 17,593 | `8539ec1e99e9697efd111258082634161be728869ff8bbe91e37327fc27a1802` | 0.665 |
| Ownership | 8115091 | `01KYFFDRSK307GPERBXT1T8NZA` | 6,565 | `705517367da48f4936bff982f5ac647fe81a12565264fa7f3a873d03247a8132` | 23.685 |
| Effective-rate calls | 8115144 | `01KYFFXT027TNG0TGY1Q1PFDZW` | 4,080 | `1e28f84b434d7f1d1f615a9894cd650312c7f8a2fce3229fdf4253f9b1a84c8a` | 0.320 |

The continuation began at 1,018.403 credits and ended at 1,042.408, an
observed delta of 24.005 credits. The complete Terra/CeFi window delta from
the boundary-stream start is 25.063 credits. The remaining quota is 1,457.592
credits, above the 1,250-credit continuation reserve. Each successful result
was retrieved once. A local orchestration parsing mistake made an additional
ownership creation call before the retained identifiers were persisted; no
further ownership execution was submitted. Query 8115091 is the sole
ownership result used in any dataset.

## Ownership and accumulated rates

The ownership result contains 4,996 opens and 1,569 successful give
transitions for 4,996 unique CDPs. At the opening boundary, 4,572 of 4,686
active vaults have a CDP and manager-owner proxy; 114 remain direct or
unmapped. There are 4,123 distinct opening owner proxies, 372 proxies with
more than one active vault, and a maximum observed cluster of 19 vaults.
Manager owner remains an identity proxy, not a claim about beneficial
ownership.

The raw rate stream contains 2,040 `Jug.drip` calls and 2,040 linked
`Vat.fold` calls. The processed sparse ledger adds one exact opening rate for
each ilk, giving 4,086 rows. All fold/drip pairs reconcile, ordering is
deterministic, and each final rate equals the independent closing boundary.
The six opening rates are:

| Ilk | Opening accumulated rate (ray) |
|---|---:|
| ETH-A | 1069652967009124532844035873 |
| ETH-B | 1098484215262774951551595450 |
| ETH-C | 1013277262539863758640457825 |
| WBTC-A | 1063857864561035079008522351 |
| WBTC-B | 1025846798548900666911934574 |
| WBTC-C | 1004623744598269310769340454 |

The respective closing rates are 1072653797742910240755054924,
1103949327517849615454220202, 1013920041257980397908796830,
1067173659831928137885851586, 1031073013488047921957353494 and
1005582435898778633578122454.

## Replay and liquidation evidence

The raw mutation stream comprises 16,941 frobs, three forks and 649 grabs.
Local fork expansion yields 17,596 economic rows. Exact replay has zero
negative state, zero ordering ambiguity and zero opening-to-closing mismatch
across all 5,111 ilk–urn rows.

All 649 local Phase 1C Barks match exactly one grab by transaction, ilk, urn
and signed amounts. There are no unmatched Barks, unmatched grabs, ambiguous
links or amount discrepancies. The link file records the treatment explicitly
so Bark cannot be counted as another state delta.

All 649 usable liquidations remove 100% of the pre-grab normalised debt and
100% of the pre-grab locked collateral. Consequently, the debt close fraction
has mean, standard deviation, minimum, q10, q25, median, q75, q90, q95, q99
and maximum of 1, 0, 1, 1, 1, 1, 1, 1, 1, 1 and 1. Counts by ilk are 400,
25, 121, 89, 6 and 8 in target-ilk order. This is a degenerate but directly
simulator-aligned empirical distribution; no value is adopted in this phase.

The 649 grabs form 54 one-hour-gap descriptive sequences. The largest
contains 84 grabs affecting 84 urns; the longest observed sequence lasts
7,194 seconds. These clusters are descriptive and do not establish causality.

## Stress-tail and cross-regime evidence

The hourly stress-tail file has 7,728 rows: one system row and six ilk rows
for each of 1,104 hours. The maximum calculated system liquidatable share is
0.02847, with 128 liquidatable vaults and approximately 31.264 million DAI of
debt at risk at the maximum. Barks occur in 65 distinct system hours.
Calculated liquidatable state, Bark initiation, grab execution and auction
records remain separate. Mutation activity, entry/exit proxies and ownership
concentration are retained in the event ledger and behaviour summary; sequence
clustering is retained in the separate sequence file.

The seven-row cross-regime comparison reports each exact ilk and the aggregate
for quiet-mature, USDC/SVB and Terra/CeFi. Counts are also duration-normalised.
The windows are purposively selected and unequal in duration, so the comparison
is descriptive and supports no causal interpretation.

## Parameter readiness

The ten-row readiness table now includes Terra/CeFi evidence. Nine existing
Phase 2B candidates remain `ready_for_review`; their values are unchanged.
`max_close_factor` advances to `ready_for_estimation` with 649 exact linked
observations. Phase 2C estimation is therefore methodologically justified,
subject to explicit review of the observed all-full-closure distribution and
the mismatch between Maker Liquidations 2.0 semantics and any intended
partial-close simulation experiment.

Bull expansion is not required to unblock `max_close_factor`. It remains
useful only as a later leverage and collateral-composition sensitivity window.

## Limitations

- The six ilks cover ETH and WBTC vaults, not all Maker collateral.
- Manager ownership is a proxy and direct urns legitimately remain nullable.
- Purposive windows do not identify causal effects or unconditional history.
- Every observed grab is a full closure, so partial-close behaviour is not
  empirically identified by this window.
- The stress-tail state is hourly; within-hour ordering remains available in
  the event ledger rather than the hourly table.
- No candidate has been adopted and no simulator mechanics or configuration
  have changed.
