# Data acquisition

## Design

The empirical design combines compact continuous panels with representative
high-volume vault windows:

- market, gas, liquidation and protocol series cover the full validated sample
  where hourly or sparse extraction is economical;
- vault mutation and state reconstruction uses purposively selected ordinary
  and stress windows;
- the FTX interval is withheld from primary calibration;
- completed exhaustive-method chunks are preserved as methodology validation,
  not treated as a failed acquisition.

The original continuous vault plan is preserved byte-for-byte in the
[historical acquisition plan](../archive/historical_plans/DATA_ACQUISITION_PLAN.md).

## Sources and ownership

| Domain | Primary source | Authoritative workflow | SQL |
| --- | --- | --- | --- |
| Market | Dune `prices.hour` | `workflows/market/acquire.py` | `sql/market/templates/hourly_prices.sql` and `sql/market/templates/hourly_market_prices.sql` |
| Gas | Dune `ethereum.transactions` and `ethereum.blocks` | `workflows/gas/acquire.py` | `sql/gas/templates/hourly_conditions.sql` |
| Protocol | Decoded Maker Vat, Spot, Jug, Dog and Clipper calls | `workflows/protocol/acquire.py` | `sql/protocol/templates/` |
| Vaults | Successful Vat frob, fork and grab; manager mapping and rate calls | `workflows/vaults/acquire.py` and `workflows/vaults/acquire_representative.py` | `sql/vaults/templates/` |
| Liquidations | Decoded Dog and Clipper events/calls plus unique Ethereum transactions | `workflows/liquidations/acquire.py` | `sql/liquidations/generated/history/` for preserved executed instances |

Raw results belong under `data/<domain>/raw/`. Domain acquisition state,
checksums, query and execution identifiers belong under
`data/<domain>/provenance/`.

## Market series

The operational market query retrieves WETH as model asset ETH, WBTC as the
BTC-collateral proxy, DAI and native USDC on Ethereum. WBTC remains WBTC in raw
data. Its interval is half-open from 1 June 2021 to 1 July 2024 UTC.

The confidence-calibration extension uses the same Dune `prices.hour`
methodology and exact WETH and DAI contracts over the half-open interval from
31 December 2019 to 1 July 2024. It deliberately excludes WBTC and USDC
because they are not inputs to the pre-registered Design C evidence gate. The
two-asset result is a separate calibration evidence panel; it does not replace
the established four-asset operational panel.

Preferred source: Dune. The full-range confidence extension selected the first
authorised route: an exact `prices.hour` extension with CoinPaprika as the
reported source throughout. No provider boundary was introduced. Any future
fallback requires its own provenance and explicit source/unit mapping; it is
not automatically substituted.

## Gas series

Network gas is aggregated hourly inside Dune. It retains effective gas-price
quantiles, base and priority fees, utilisation, transaction and block gas
totals, failure share and EIP-1559 context. The historical acquisition used
bounded Small-engine chunks with atomic state and persistence.

Google BigQuery Ethereum and Etherscan statistics are documented fallbacks.
The hourly table prices gas; liquidation transaction gas units are acquired
separately.

## Protocol parameters

Sparse setting histories reconstruct Vat, Spot, Jug, Dog and Clipper state
from the latest valid pre-sample value plus in-sample changes. Official Maker
source, ABI and governance records are corroborating sources where decoded
calls do not establish defaults or migrations.

## Vault windows

The selected windows are:

| Role | Half-open window | Status |
| --- | --- | --- |
| Early-system method comparison | 2020-02-01 to 2020-03-01 | preserved |
| Black Thursday method comparison | 2020-03-01 to 2020-04-01 | preserved |
| Bull market and WBTC expansion | 2021-11-15 to 2021-12-06 | planned evidence window |
| Terra/CeFi contagion | 2022-05-05 to 2022-06-20 | complete |
| FTX withheld validation | 2022-11-01 to 2022-11-21 | withheld |
| USDC/SVB depeg | 2023-03-06 to 2023-03-20 | complete |
| Quiet mature market | 2024-02-01 to 2024-03-01 | complete |

Each reconstructed window requires an authoritative opening state or validated
targeted pre-history, canonical signed Vat mutations, exact accumulated rates
and ownership mapping where available. The first in-window mutation is never
treated as an opening balance.

## Liquidations

The event architecture preserves Bark, Kick, Take, Redo, Yank and failed call
records and joins each unique transaction once. Event and transaction files
remain separate before local reconciliation. The acquisition does not export
unrelated transaction or log history.

## Persistence and resume behaviour

The acquisition workflows use explicit modes, one execution per authorised
query, stop-on-failure semantics and atomic local writes:

```text
identifiers persisted
→ execution completed
→ result retrieved
→ partial payload written and fsynced
→ structural validation
→ atomic rename
→ semantic validation
```

A completed local chunk is never silently re-executed. A completed Dune
execution without a persisted result requires explicit result-recovery
authorisation. Large deterministic results use validated pagination or bounded
subwindows.

## Prerequisites and external boundaries

Live Dune acquisition requires a private `DUNE_API_KEY`, appropriate account
quota and explicit authority to create or execute a query. Credentials are
read from the environment and are never printed or committed. Acquired raw and
processed payloads are ignored by Git.

Local processing and validation do not require external access. Reproducing
ignored raw data may nevertheless require Dune availability, account
permissions and credits; query and execution identifiers alone do not
guarantee permanent result retention.

## Fallback policy

Every fallback is a separate source with separate validation:

| Evidence | Primary | Backup |
| --- | --- | --- |
| ETH/WBTC | Dune | Binance or Kraken |
| DAI/USDC | Dune | DEX VWAP or Coinbase corroboration |
| Gas | Dune | BigQuery or Etherscan |
| Protocol settings | decoded calls | contract state and governance records |
| Vault mutations | decoded Vat calls | archive-node traces |
| Liquidations | decoded Maker events | filtered Ethereum logs |

No missing observation is silently filled from a backup source.
