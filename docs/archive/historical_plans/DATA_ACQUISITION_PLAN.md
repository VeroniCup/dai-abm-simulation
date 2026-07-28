# DATA_ACQUISITION_PLAN.md

# Data Acquisition Plan

Before using "dynamic workflows", "ultra code" or any harness feature that immediately
spawns a large swarm of subagents, always explain the tradeoffs and ask the user for explicit approval.

## Purpose

This document defines the data acquisition strategy for the empirical calibration of the DAI multi-collateral simulation.

The guiding principles are:

- prefer free and reproducible data sources;
- obtain data at hourly resolution where practical;
- maintain complete provenance for every dataset;
- preserve raw data unchanged;
- always prepare backup sources in case the preferred source becomes unavailable.

This document complements `empirical.md` and `parameters.md` and should be updated whenever new data sources are introduced.

---

# Revised Phase 1E methodology

The original plan proposed continuous vault-mutation acquisition from the
earliest relevant ilk activation through June 2024. That design was useful for
discovering authoritative sources and proving reconstruction correctness, but
validated acquisition costs show that it is not the best empirical design for
the dissertation.

Phase 1E is now divided into:

- **Phase 1E-A — Methodology validation: Complete.** Discovery, diagnostics,
  parser repairs, deterministic ordering, pagination, resumability and chunks
  01–05 are preserved as validated evidence.
- **Phase 1E-B — Representative calibration acquisition: Planned.** Acquire
  purposively selected ordinary and stressed windows that identify simulator
  parameters and behavioural assumptions.

The continuous plan is retained in provenance as the original design; it is no
longer the intended production methodology. Continuous market, gas and
liquidation-count panels remain appropriate because they are compact hourly
aggregates. The representative-window change applies to high-volume vault
mutation and state reconstruction.

The detailed window design, parameter mapping and credit roadmap are recorded
in `docs/phase1e_representative_calibration_strategy.md`.

---

# Overall workflow

```text
Acquire raw data
        ↓
Validate completeness
        ↓
Standardise format
        ↓
Run empirical pipeline
        ↓
Estimate empirical distributions
        ↓
Calibrate simulator
        ↓
Historical validation
        ↓
Counterfactual experiments
```

---

# Directory structure

Raw datasets should be placed under:

```text
data/
├── raw/
│   ├── market/
│   ├── gas/
│   ├── protocol/
│   ├── vaults/
│   └── liquidations/
│
├── processed/
│
├── data_manifest.csv
└── README.md
```

Raw files must never be modified.

All transformations should occur through the empirical pipeline.

---

# Priority levels

The required datasets are divided into three groups.

## Tier A — Market data (highest priority)

These are required before any empirical calibration can begin.

Required variables:

- ETH price
- BTC (or WBTC) price
- USDC price (proxy for STABLE collateral)
- DAI price
- Ethereum gas-cost proxy

Target frequency:

> Hourly (UTC)

Expected confidence:

★★★★★

---

# Tier B — Protocol state

Required for protocol calibration.

Includes:

- collateral debt
- collateral locked
- debt ceilings
- liquidation ratios
- liquidation penalties
- stability fees
- vault counts

Target frequency:

Daily is sufficient.

Risk parameters usually change only after governance actions and therefore do not require hourly observations.

Expected confidence:

★★★★☆

---

# Tier C — Vaults and liquidations

Required for behavioural calibration.

Includes:

- vault snapshots
- collateral-ratio distributions
- debt distributions
- liquidation events
- auction outcomes
- bad debt
- keeper activity

Expected confidence:

★★★☆☆

Vault evidence will be collected from representative regimes rather than as a
continuous census. Liquidation events already acquired in Phase 1C retain their
event-level scope.

This remains the most demanding identification problem because mutation-active
vaults are not an unbiased cross-section of all vaults.

---

# Data source hierarchy

## 1. Market prices

### Variables

- ETH/USD
- WBTC/USD as the BTC-collateral price proxy
- USDC/USD
- DAI/USD

### Preferred source

Dune

Table:

```
prices.hour
```

Advantages:

- hourly UTC timestamps
- standardised schema
- one source for all assets
- compatible with empirical pipeline

---

### Backup 1

Binance public historical data

Use:

- ETHUSDT
- BTCUSDT

Hourly OHLC.

---

### Backup 2

Kraken historical OHLC

Use USD trading pairs where available.

---

### Backup 3

Coinbase candles

Useful for validation or filling small gaps.

---

### Notes

The Dune market-price acquisition uses:

```
ETH      ← ETH/USD
BTC      ← WBTC/USD, retained as WBTC in raw data
STABLE   ← USDC/USD
DAI      ← DAI/USD
```

WBTC/USD is used because the Maker collateral instrument is WBTC. The raw
dataset must label it `WBTC`, not native BTC. Later model-standardisation code
may map that series to the simulator's `BTC` collateral category while
retaining the WBTC provenance and wrapper-risk limitation.

---

# 2. Gas-cost series

Required variable:

```
gas_cost_proxy
```

Primary source:

Dune canonical `ethereum.transactions` and `ethereum.blocks`, aggregated inside
Dune to hourly UTC frequency. Acquisition uses 13 bounded private temporary
queries on the Small engine, with matching partition and timestamp filters.

The acquired fields are transaction and block counts; median, mean, P75, P90,
P95 and P99 effective gas prices; median and P95 base fees; median priority
fee; raw and target-normalised block utilisation; transaction and block gas
totals and their reconciliation difference; failed-transaction share;
null-success count; and EIP-1559 block share. Percentiles are approximate Dune
aggregations.

Future improvement:

Estimate actual liquidation transaction costs by combining:

```
gas_used
×
effective_gas_price
×
ETH/USD
```

---

Backup sources:

- Google BigQuery Ethereum public datasets
- Etherscan historical gas statistics

---

# 3. Protocol state

Required variables

- outstanding debt
- debt ceiling
- collateral locked
- vault count
- liquidation ratio
- liquidation penalty
- stability fee
- dust
- auction parameters (if available)

Preferred source

Dune Maker protocol tables.

---

Backup

Ethereum contract state.

---

Verification

Official Maker governance spell archive.

---

# 4. Vault snapshots

Preferred strategy

Representative cross-sectional snapshots aligned with the Phase 1E-B
calibration windows. The sample must include inactive vaults where possible so
that mutation-active vaults do not determine the entire leverage distribution.

Window mutation ledgers should be combined with an authoritative opening
snapshot or a targeted pre-window history for affected urns. The first mutation
in a window must not be treated as an opening balance.

For every vault:

- collateral type
- collateral amount
- debt
- collateral ratio
- liquidation ratio
- distance to liquidation

Target collateral types

ETH:

- ETH-A
- ETH-B
- ETH-C

BTC:

- WBTC-A
- WBTC-B
- WBTC-C

---

# Important modelling note

The simulation contains a stylised

```
STABLE
```

collateral class.

Real MakerDAO contains multiple stable collateral types.

In particular,

```
PSM-USDC-A
```

behaves differently from ordinary vaults.

Therefore the empirical pipeline should preserve:

```
source_collateral_type
```

and

```
model_collateral_type
```

separately.

The aggregation into

```
STABLE
```

occurs only during calibration.

---

# 5. Liquidation events

Preferred source

Dune decoded Maker liquidation events.

Target events

- Bark
- Kick
- Take
- Redo

Important variables

- timestamp
- vault
- collateral
- debt
- collateral sold
- auction duration
- gas
- keeper
- bad debt

Backup

BigQuery Ethereum logs.

---

# Calibration and validation periods

Continuous Phase 1A and Phase 1B panels retain their validated coverage from
June 2021 through June 2024. Phase 1E-B uses the following representative vault
windows:

| Role | Half-open window |
|---|---|
| Existing early-system method comparison | 2020-02-01 to 2020-03-01 |
| Existing Black Thursday method comparison | 2020-03-01 to 2020-04-01 |
| Bull market and WBTC-B/C activation | 2021-11-15 to 2021-12-06 |
| Terra and CeFi contagion | 2022-05-05 to 2022-06-20 |
| FTX withheld validation | 2022-11-01 to 2022-11-21 |
| USDC/SVB depeg | 2023-03-06 to 2023-03-20 |
| Quiet mature market | 2024-02-01 to 2024-03-01 |

The 2020 observations validate accounting and provide legacy behavioural
comparisons; they are not pooled as Liquidations 2.0 auction evidence. The FTX
window is withheld from primary behavioural estimation.

Purposive window frequencies must not be interpreted as unconditional event
probabilities. Those probabilities use continuous exposure denominators from
the market, gas and liquidation panels.

---

# Data provenance

Every dataset must have a corresponding record in

```
data_manifest.csv
```

including:

- series name
- model variable
- source
- source reference
- download date
- file name
- frequency
- timezone
- currency/unit
- sample coverage
- transformation
- licence
- notes

No dataset should enter the empirical pipeline without complete provenance.

---

# Fallback strategy

| Dataset | Primary | Backup | Final fallback |
|----------|----------|---------|----------------|
| ETH | Dune | Binance | Kraken |
| BTC | Dune | Binance | Kraken |
| DAI | Dune | DEX VWAP | Coinbase |
| USDC | Dune | DEX VWAP | Coinbase |
| Gas | Dune | BigQuery | Etherscan |
| Protocol state | Dune | Contract state | Governance archive |
| Risk parameters | Governance archive | Contract state | Manual reconstruction |
| Vault snapshots | Dune | Archive node | Representative-window sampling |
| Liquidations | Dune | BigQuery logs | Manual decoding |

Every required dataset has at least one backup source.

---

# Acquisition order

## Phase 1 — Market panel

Acquire:

- ETH
- BTC
- USDC
- DAI
- Gas

Populate

```
data/raw/market/
```

and

```
data/raw/gas/
```

Run:

```
python src/empirical_data.py --mode baseline
```

---

## Phase 2 — Protocol panel

Acquire:

- collateral debt
- collateral locked
- governance parameters

Produce:

```
protocol_time_panel.csv
```

---

## Phase 3 — Vault panel

Acquire the Phase 1E-B representative windows in information-per-credit order.
For each window, acquire:

- a representative opening snapshot or validated targeted opening history;
- canonical signed Vat mutations;
- ownership mappings where available; and
- effective protocol and accumulated-rate joins.

Estimate:

- debt distribution
- collateral-ratio distribution
- leverage distribution

Produce:

```
representative_vault_calibration_panel.csv
```

---

## Phase 4 — Liquidations

Acquire:

- Bark
- Kick
- Take
- Redo

Join transaction gas.

Produce:

```
liquidation_event_panel.csv
```

---

# Current status

✅ Empirical pipeline implemented.

✅ Data validation pipeline implemented.

✅ Synthetic validation completed.

✅ Phase 1A market data acquired and processed.

✅ Phase 1B gas data acquired and processed.

✅ Phase 1C Liquidations 2.0 data acquired and validated.

✅ Phase 1D protocol-parameter history acquired and validated.

✅ Phase 1E-A methodology validation complete.

⬜ Phase 1E-B representative calibration windows planned.

⬜ Empirical calibration not yet started.

---

# Notes

The objective of this acquisition stage is **not** to maximise the quantity of data collected, but to ensure that every empirical input used for calibration is:

- reproducible;
- well documented;
- historically accurate;
- consistent across all datasets;
- traceable to an original source.

A smaller, higher-quality dataset is preferable to a larger dataset with uncertain provenance or inconsistent definitions.

The representative-window strategy applies this principle explicitly. It
preserves the original continuous design and completed chunks for
reproducibility, while directing remaining credits to observations that
identify ordinary behaviour, prolonged crypto stress, stablecoin contagion and
out-of-sample performance.
