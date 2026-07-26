# Phase 1E-B Tranche 1 Acquisition Report

## Scope and outcome

Tranche 1 authorised two exact half-open representative windows:

- quiet mature: `[2024-02-01 00:00:00 UTC, 2024-03-01 00:00:00 UTC)`;
- USDC/SVB: `[2023-03-06 00:00:00 UTC, 2023-03-20 00:00:00 UTC)`.

The quiet-mature boundary, canonical mutations, ownership and repaired
effective-rate stream are acquired, persisted and validated. Exact local
replay reproduces the independently observed closing boundary with no state
mismatch. USDC/SVB was deliberately outside this tranche's rate-repair
authorisation. It was subsequently acquired and validated under a separate
authorisation; see
[`phase1e_b_usdc_svb_acquisition_report.md`](phase1e_b_usdc_svb_acquisition_report.md).

The original effective-rate query completed but reported 419,830 rows because
it selected every historical `Jug.drip` and `Vat.fold` record. Exporting that
result was projected to cost approximately 2,729 credits, so it remains
unretrieved and is classified as `superseded_oversized_rate_export`.

## Source architecture

The acquired state evidence follows the validated Phase 1E architecture:

- successful canonical `Vat.frob`, `Vat.fork` and `Vat.grab` calls are the
  only economic mutations;
- `Vat.slip` and manager wrappers are excluded from state deltas;
- forks are designed for exact local source/destination expansion;
- transaction ordering comes from `ethereum.transactions.index`;
- trace addresses retain numeric ordering and the validated explicit root
  parser;
- `Dog.Bark` is a local Phase 1C annotation, not a second mutation;
- manager ownership remains an owner/proxy identity and may be null.

The opening-state query scans canonical mutations from 1 November 2019 but
exports only authoritative start and end balances by `(ilk, urn)`. It
conditionally aggregates pre-window and in-window deltas, expands `Vat.fork`
inside the aggregation and attaches exact latest pre-boundary and end-boundary
`Jug.drip.output_rate` values. This avoids exporting a continuous five-year
mutation history merely to construct the boundary state.

## Queries and observed cost

| Stream | Query | Execution | Rows | Compute credits | Observed delta | Result |
|---|---:|---|---:|---:|---:|---|
| Quiet boundary states | 8113626 | `01KYF3W8NPH17NCXBVGBKYQ9AF` | 3,410 × 15 | 0.418 | 22.418 | Persisted and passed |
| Quiet Vat mutations | 8113709 | `01KYF4FGV4D03ME7KJVQGFRWZH` | 2,074 × 15 | 0.850 | 12.850 | Persisted and passed |
| Quiet ownership history | 8113717 | `01KYF4HECB51VBA6MT7ENW36FM` | 4,266 × 14 | 36.779 | 63.779 | Persisted and passed |
| Quiet effective rates | 8113737 | `01KYF4M8P8RD4TZYB7V5NX3KAT` | 419,830 × 12 reported | 11.734 | 11.734 | Not retrieved; cost stop |
| Sparse rate repair | 8113965 | `01KYF6F87HFW5EADJJ0BZM2VMN` | 2,282 × 12 raw | 0.390 | 11.390 | Persisted and passed |

The repair SQL SHA-256 is
`e4bc8bd56800b9e06a016f4e2215413a2520e4b9227c5f6f1e9e5606a740e9e7`;
the raw CSV SHA-256 is
`246219a74981c5e060ec4b65cacfe1dc7b6b2580d82c0520c8fdf2adbd5b67b1`.

Every query was private, temporary and executed once on Small. There were no
diagnostic or sub-window queries and no automatic retries. Each of the three
initial persisted results and the sparse repair used one page. One initial
local retrieval attempt failed at
the sandbox DNS boundary before reaching Dune; the authorised external request
then succeeded and is the only physical Dune request recorded for that page.

Usage increased from 804.374 to 926.545 credits: 122.171 credits for the
tranche, including the superseded execution. The repair itself consumed
11.390 observed credits. The remaining quota is 1,573.455 credits.

## Persisted stream validation

The boundary result contains 3,410 unique `(ilk, urn)` records across all six
target ilks. There are no negative opening or end balances, missing positive
rates for indebted states, duplicate keys or future-rate joins.

The opening boundary contains 3,296 active vaults and 1,886 indebted vaults:

| Ilk | Active opening vaults | Indebted opening vaults |
|---|---:|---:|
| ETH-A | 2,025 | 1,029 |
| ETH-B | 190 | 137 |
| ETH-C | 472 | 389 |
| WBTC-A | 404 | 162 |
| WBTC-B | 70 | 55 |
| WBTC-C | 135 | 114 |

The mutation stream contains 2,074 successful canonical frobs affecting 617
urns: 700 deposits, 357 withdrawals, 1,108 draws and 264 repayments. No fork
or grab occurred. There are no duplicate source calls, malformed trace
positions or unresolved ordering ties.

The ownership result contains 3,320 unique CDP–urn mappings and 946 successful
ordered `give` transitions. Of the 3,296 active opening urns, 3,206 have a
manager mapping and 90 are direct or otherwise unmapped. The 3,310 distinct
owner/proxy addresses are not interpreted as beneficial owners.

The existing validated Phase 1C action fact contains no quiet-window Bark
event, consistent with the zero observed grabs. Bark/grab linkage therefore
has no non-zero quiet-mature case to validate.

## Effective-rate repair and replay

Method B was used. Phase 1D raw and processed files were audited first. They
contain exact `Jug.file` duty and base settings, but not the accumulated Vat
rate emitted by `Jug.drip`; the hourly Phase 1D panel therefore cannot establish
same-block rate ordering. The validated boundary result supplied one exact
latest pre-window accumulated rate per ilk. Query 8113965 then retrieved only
bounded in-window `Jug.drip.output_rate` and direct-child `Vat.fold.rate`
calls.

The raw repair contains 1,141 drip and 1,141 fold rows. All direct-child
fold deltas reconcile exactly to their paired resulting rates, including
legitimate repeated same-transaction calls. Adding six local opening rows
produces a 2,288 × 15 sparse stream with SHA-256
`d521bf46623f3e2c014e53f24bc2717216b7891ccc697a24f8cf61e707b08115`.
All six final accumulated rates match the independently acquired boundary
rates.

Replay begins with 3,410 recorded urn states, of which 3,296 are active and
1,886 indebted. It applies 2,074 canonical mutations and ends with 3,258
active and 1,852 indebted states. There are 82 inactive-to-active and 120
active-to-zero transition proxies. There are no negative event states,
ordering ties, Bark/grab inconsistencies or opening-to-closing state
mismatches.

## Information value

The four persisted source streams contain 12,032 records. Including the
superseded execution, the tranche supplied approximately:

- 98.49 persisted records per observed credit;
- 10.154 credits per 1,000 persisted records;
- 26.98 active opening vaults per observed credit; and
- 16.98 canonical mutation rows per observed credit.

This window adds a mature Liquidations 2.0 cross-section and ordinary
behavioural flow evidence that is distinct from the five 2019–2020
methodology-validation months. It adds little liquidation or close-factor
information because no grab occurred.

The parameter-readiness table is
`data/provenance/vaults/representative_regimes/tranche_01_parameter_evidence_readiness.csv`.
`max_normal_liquidatable_share` is ready for the later estimation stage from
the quiet-window evidence. Seven other level or behaviour parameters are
partially identified pending cross-window evidence, `max_close_factor` has
insufficient quiet-window liquidations, and `max_stress_liquidatable_share`
remains blocked by the unstarted stress window. No final value was estimated.

## Limitations and next authorisation

Quiet-mature architecture is now ready to be reused for USDC/SVB. Scaling the
bounded streams to fourteen days and allowing for a similar boundary and
ownership cross-section gives a revised conservative cost range of 90–140
credits. The high end would leave approximately 1,433 credits at current
usage, above the requested 1,400-credit repair reserve.

The separately authorised USDC/SVB window is now complete. Bull expansion
remains useful for WBTC-B/C adoption and high-gas behaviour; Terra/CeFi remains
useful for prolonged crypto-stress deleveraging and liquidation behaviour.
FTX remains withheld and was neither acquired nor used for calibration.
