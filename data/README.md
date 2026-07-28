# Empirical input data

`src/empirical_data.py` accepts one combined CSV or several CSV sources. The
source adapter is implemented in `src/empirical_sources.py`; canonical returns,
volatility and regimes remain in `src/empirical_data.py`. Each source is
declared under `input_files` in `config/empirical.yaml`. Paths are resolved
relative to the repository root.

Empirical data use a domain-first hierarchy under `data/market/`, `data/gas/`,
`data/vaults/`, `data/liquidations/` and `data/protocol/`. Each populated
domain owns the relevant lifecycle directories:

- `raw/` for read-only acquisition artefacts;
- `processed/` for reproducible analytical datasets;
- `model_inputs/` for compact tracked runtime inputs;
- `provenance/` for domain-owned manifests, validation and acquisition records.

Raw and processed payloads and detailed provenance are ignored by Git. Their
tracked READMEs, selected durable provenance entry points and compact
`model_inputs/` remain version controlled. The narrow `data/provenance/` root
contains only the cross-domain data manifest and provenance index.

The generated `data/processed/estimation/` diagnostics tree remains temporarily
in the old lifecycle-first hierarchy until Stage 10. No other empirical data
should be added to a lifecycle-first location.

## Dune hourly market-price acquisition

The production SQL is stored in `sql/dune_hourly_market_prices.sql`. It maps
Dune's WETH instrument to the raw-data asset label `ETH`; WBTC remains `WBTC`
and is documented as the BTC-collateral price proxy, not native BTC. The query
uses `prices.hour`, four Ethereum contract addresses and the half-open UTC
interval from 2021-06-01 to 2024-07-01. It deliberately has no `ORDER BY`.

Save that SQL as a private Dune query before acquisition. The repository script
executes the saved query by ID on the Small engine; it never creates or updates
a query and never prints the `DUNE_API_KEY`:

```bash
export DUNE_API_KEY='set-outside-version-control'
python workflows/market/acquire.py \
  --mode saved-query \
  --query-id QUERY_ID
```

The script polls one execution, stops without retrying on failure or timeout,
and fetches each CSV result page at most once. Raw output is written to
`data/market/raw/` without imputation, sorting or value transformation. It also
records the query ID, execution ID, UTC acquisition time, coverage, row count
and SHA-256 checksum in an execution sidecar and `data/provenance/data_manifest.csv`.
If polling times out, resume the same execution rather than paying for another:

```bash
python workflows/market/acquire.py \
  --mode saved-query \
  --query-id QUERY_ID \
  --resume-execution-id EXECUTION_ID
```

For a query and execution created explicitly as a private temporary Dune query,
use `--mode temporary-query` together with both returned identifiers. This mode
never submits another execution:

```bash
python workflows/market/acquire.py \
  --mode temporary-query \
  --query-id TEMPORARY_QUERY_ID \
  --execution-id EXECUTION_ID
```

Validate the untouched result locally with:

```bash
python workflows/market/validate.py \
  data/market/raw/dune_prices_hourly_2021-06-01_2024-06-30.csv \
  --report data/market/provenance/dune_prices_hourly_2021-06-01_2024-06-30.validation.json
```

Validation checks the requested UTC boundaries, identifiers, row counts,
duplicate and missing asset-hours, maximum consecutive gaps, prices, sources,
blockchain values and stablecoin price ranges. It reports problems but never
imputes or changes the raw CSV.

## Phase 1A processed hourly market panel

Construct the source-specific wide panel only after the raw checksum and
structural validation have passed:

```bash
python workflows/market/process.py \
  --input data/market/raw/dune_prices_hourly_2021-06-01_2024-06-30.csv
```

The command is deterministic apart from recorded creation timestamps and has
no network or Dune API path. It writes generated analytical CSVs under
`data/market/processed/` and their provenance sidecars under
`data/market/provenance/`:

- `dune_hourly_market_prices_processed.csv` — one row per UTC hour with the
  exact raw prices, hourly log returns, DAI and USDC peg measures and source
  provenance;
- `stablecoin_extreme_review.csv` — every DAI or USDC observation meeting the
  documented price, peg-deviation or centred rolling-median review criteria;
- `data/market/provenance/dune_hourly_market_prices_processing_metadata.json`
  — input/output checksums, dimensions, transformation definitions and
  descriptive review;
- `data/market/provenance/dune_hourly_market_prices_processed_validation.json`
  — formula, timestamp, provenance and exact raw-price reconciliation checks.

Log returns are `log(price_t) - log(price_t-1)`, with the first observation
left missing. Peg deviation is price minus one; absolute peg deviation is its
absolute value; and the below-peg indicator equals one only below one dollar.
The stablecoin review uses a centred time-based 24-hour rolling median with
`min_periods=1`, so boundary windows use the available observations.

No price is winsorised, clipped, smoothed, interpolated, forward-filled,
deduplicated, imputed or removed. Review flags identify observations for
source and economic assessment; they do not classify observations as errors.
The raw-file checksum is verified again after processing.

## Phase 1B Dune hourly Ethereum gas acquisition

The production template is `sql/dune_ethereum_hourly_gas.sql`. It aggregates
`ethereum.transactions` and `ethereum.blocks` to 20 hourly fields. Effective
gas-price percentiles use Dune's approximate percentile aggregation. The
template uses matching partition and timestamp filters and is rendered into 13
fixed, contiguous half-open chunks covering 2021-06-01 through 2024-07-01.

`workflows/gas/acquire.py` is the local persistence and validation
state machine used with Dune MCP. It has no network or API-key path. Query and
execution identifiers are atomically recorded under
`data/gas/provenance/state/` before result retrieval. Retrieved MCP results are
written to a filesystem `.partial.json`; the script serialises result rows to a
flushed `.partial.csv`, parses and structurally validates that file, and then
uses an atomic rename for the final chunk CSV. Retrieval, persistence and
validation are separate durable states. Completed chunks cannot be replaced,
and failed or incomplete chunks require explicit replacement authorisation.

The 13 original chunk CSVs remain under `data/gas/raw/chunks/`. After all chunks
passed, they were sorted and concatenated locally without deduplication or
value changes into:

```text
data/gas/processed/dune_ethereum_hourly_gas_assembled_2021-06-01_2024-06-30.csv
```

The combined panel contains 27,024 UTC hours and 20 columns. Its SHA-256 is
`694a901ba6cf2a60a95014398900ab77508a9ce8218cb05acd6424fa23637541`.
Chunk query/execution IDs, checksums, validation results, credit readings and
the excluded aborted attempt are recorded in the acquisition ledger, metadata,
validation and aborted-attempt files under `data/gas/provenance/`. The
manifest retains the combined provenance even though generated raw files are
excluded from Git.

The first chunk-01 attempt completed and was retrieved but failed before local
persistence. Its unavailable query and execution identifiers were not
fabricated, no result rows from it entered the dataset, and its 0.089-credit
usage is excluded from the successful production-batch cost of 4.379 credits.
The execution-level production compute sum was 4.381 credits; the small
difference reflects usage-meter timing and rounding. Phase 1B discovery and
benchmarking used 0.665 credits in aggregate, making cumulative Phase 1B usage
5.133 credits.

The hourly table supplies the price of gas, not liquidation-specific gas
usage. Keeper cost in USD must later combine a separately estimated gas-unit
distribution with the selected hourly effective gas price and the Phase 1A ETH
price: `gas_units × gas_price_gwei × 1e-9 × eth_price_usd`. No conversion,
regime construction or price/gas join is performed during raw acquisition.

## Phase 1B processed gas and joined market--gas panels

Run the entirely local processor only after the raw gas and Phase 1A market
checksums have passed:

```bash
python workflows/gas/process.py \
  --gas-input data/gas/processed/dune_ethereum_hourly_gas_assembled_2021-06-01_2024-06-30.csv \
  --market-input data/market/processed/dune_hourly_market_prices_processed.csv
```

The processor has no Dune, API or network path. It writes generated,
Git-ignored artefacts under `data/gas/processed/` and
`data/market/processed/combined/`:

- `dune_ethereum_hourly_gas_processed.csv` — 27,024 rows and 41 columns,
  preserving all 20 raw gas fields and adding explicit spreads, ratios, fee
  shares, logs, changes and two descriptive candidate-regime classifications;
- `hourly_market_gas_panel.csv` — an exact one-to-one UTC join with the Phase
  1A panel, containing 27,024 rows and 66 columns;
- `gas_extreme_review.csv` — the 3,939-hour union of the documented full-sample
  percentile and absolute log-change review triggers, with deterministic
  consecutive-run fields and market context;
- descriptive statistics under `data/gas/processed/`; processing metadata and
  separate processed-gas and joined-panel validation JSON files under
  `data/gas/provenance/`.

The validated checksums are:

- processed gas panel:
  `4be17a29f9fb17e966131f09c4c6a41fbcca305350eba912759f74e85f5a1008`;
- joined panel:
  `86ed2ac5a5d364cc57e8b41e137ef369a0fce7a393d386b4b38fc1ebd1be0545`;
- gas-extreme review:
  `be78c1688ba87764b51f8e6b685f55a8b5534992cfa81d94f01d8fb9620008c8`.

Pre-London base-fee and priority-fee shares remain structurally missing. The
mixed London activation hour retains its observed EIP-1559 block share, and
fully post-London shares are calculated only where their denominators are
valid. Effective gas price remains the cross-period measure.

The joined panel includes hypothetical USD indices for 100,000, 300,000 and
500,000 gas units at median, P90 and P99 effective gas prices. These variables
do not represent empirically estimated Maker liquidation transaction costs
because liquidation-specific gas units have not yet been acquired, and they
must not be used to set `LiquidationConfig.gas_cost`.

Candidate classification A uses full-sample median effective-gas-price P75 and
P95 thresholds. Classification B separately identifies broad median-price
elevation, upper-tail P99-to-median bidding pressure and high target-normalised
utilisation, with a compound state when at least two conditions hold. Both are
descriptive candidate regimes, not final chosen simulator states or calibrated
parameters. No row is filled, clipped, smoothed, deduplicated or removed.

## Source schema

Every source requires:

- one timestamp column parseable by pandas as a timezone-aware or naive
  datetime;
- an explicit source timezone used for naive timestamps; all timestamps are
  converted to UTC;
- one or more numeric variables mapped to the canonical names below.

Canonical input columns:

| Canonical name | Meaning | Validation |
| --- | --- | --- |
| `eth_market_price` | ETH price in a consistent quote currency | strictly positive |
| `btc_market_price` | BTC or WBTC price in the same quote currency | strictly positive |
| `stable_market_price` | Price of the stable collateral represented by `STABLE` | strictly positive |
| `dai_market_price` | DAI market price in the same quote currency | strictly positive |
| `gas_cost_proxy` | Gas price or transaction-cost proxy | non-negative |
| `liquidation_volume` | Liquidation volume per source interval | non-negative; optional |

The complete moving-block-bootstrap pool requires ETH, BTC and STABLE prices
and a gas-cost proxy. DAI price is required for the peg-stress condition.
Liquidation volume is optional; its condition is only estimated when supplied.

Column mappings point from canonical names to source column names. For example:

```yaml
input_files:
  - name: combined_market_data
    path: data/market/raw/combined_market_data.csv
    timestamp_column: observed_at
    source_timezone: UTC
    duplicate_aggregation: null
    resample_aggregation: null
    columns:
      eth_market_price:
        source_column: eth_usd
        source_unit: USD_per_ETH
        target_unit: USD_per_ETH
        unit_conversion: null
      gas_cost_proxy:
        source_column: gas_gwei
        source_unit: gwei
        target_unit: gwei
        unit_conversion: null
```

When source and target units differ, `unit_conversion` must be explicit:

```yaml
unit_conversion:
  operation: multiply
  factor: 0.01
```

Only positive multiplicative conversions are supported. The adapter does not
infer exchange rates, decimal scaling, gas usage or currency conversions.

Exact duplicate timestamps are rejected unless `duplicate_aggregation` is set
to `mean`, `first` or `last`. Observations that are not already on the configured
time grid require an explicit `resample_aggregation` using the same choices.
The pipeline does not forward-fill or interpolate observations. Missing grid
intervals are retained as explicit missing rows, and returns are therefore not
calculated across gaps.

## Data manifest

`data/provenance/data_manifest.csv` contains one provenance record for every configured
source and canonical model variable. Its fields are:

- `series_name`, `model_variable`, `source_name`, `source_reference`;
- `raw_filename`, `download_date`, `native_frequency`,
  `processed_frequency`;
- `currency_or_unit`, `timezone`, `sample_start`, `sample_end`;
- `transformation`, `licence_or_access_note`, `notes`.

Dune acquisitions additionally populate query and execution identifiers,
requested and actual coverage, SQL and raw-file checksums, row counts,
validation status, source behaviour and credit usage. Phase 1A and Phase 1B
processing add the processed, joined, review and descriptive-summary paths and
checksums, processing-script checksum,
creation timestamp, processed dimensions, transformation definition and
processed-validation status. These provenance fields do not change the
existing baseline-manifest requirements.

All fields except `notes` are required for a baseline run. The manifest template
contains no invented sources, dates or access claims.

## Running the pipeline

The default command runs software validation only:

```bash
python src/empirical_data.py
```

Its outputs are written to `outputs/empirical/synthetic_validation/` and are not
empirical findings. After real paths, dates, mappings, units and manifest records
have been supplied, request the baseline explicitly:

```bash
python src/empirical_data.py --mode baseline --config config/empirical.yaml
```

No synthetic data are substituted when baseline inputs are incomplete. Real
outputs are written to `outputs/empirical/baseline/`.

## Synthetic fixture

`tests/fixtures/empirical_market_fixture.csv` is deliberately synthetic and is
used only by the executable validation in `src/empirical_data.py`. Its dates,
prices, gas values and liquidation values are not empirical observations and
must not be cited as findings.

## Protocol, vault and liquidation sources

`src/protocol_data.py` standardises these sources independently of the market
and regime pipeline. Configure real inputs in `config/protocol.yaml` and supply
explicit effective-dated collateral mappings in
`config/collateral_mapping.csv`. The mapping template is intentionally empty:
source collateral identifiers are never inferred from their names.

Canonical protocol fields are `outstanding_debt`, `debt_ceiling`,
`liquidation_ratio`, `liquidation_penalty`, `stability_fee`, `oracle_price`,
`market_price`, `collateral_locked`, `vault_count`, and optional `dust_limit`,
`close_factor` and auction fields. Vault snapshots use `collateral_amount`,
`collateral_value`, `debt_dai`, `collateral_ratio` and
`liquidation_ratio`. Liquidation events use `debt_at_risk`, `debt_repaid`,
`collateral_sold`, `collateral_value`, `liquidation_penalty`,
`gas_cost_proxy`, `keeper_reward`, `auction_duration` and `bad_debt`.

Every numeric mapping needs explicit source and target units. No keeper reward,
gas cost, bad debt, debt, or collateral value is inferred when unavailable.
Vault and liquidation collateral values must target DAI before they can be
compared with DAI debt; the adapter does not assume that another quote currency
is equivalent to DAI.
The files under `tests/fixtures/protocol/` are synthetic software fixtures and
must not be reported as empirical findings.

When both vault collateral value and positive debt exist, the canonical
`collateral_ratio` is recomputed as collateral value divided by debt. A supplied
ratio is retained in `collateral_ratio_source` and must agree within the
configured tolerance. If recomputation is impossible, a supplied ratio is used
and labelled as such; otherwise the derived fields remain unavailable.

For a real run, each configured file needs a complete record in
`data/provenance/data_manifest.csv` whose `source_name` and `raw_filename` match the source
configuration. Run:

```bash
python src/protocol_data.py --mode baseline --config config/protocol.yaml
```

The default `python src/protocol_data.py` command runs only synthetic software
validation and writes to `outputs/empirical/synthetic_validation/protocol/`.
