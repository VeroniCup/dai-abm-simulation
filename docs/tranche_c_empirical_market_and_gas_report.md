# Tranche C Empirical Market and Gas Report

## Scope

Tranche C adds an explicitly opt-in empirical environment-input layer for:

- aligned ETH and WBTC hourly return blocks;
- empirical network gas-price conditions;
- liquidation-specific gas-unit and total-cost pools;
- deterministic sidecar provenance and diagnostics.

It does not alter legacy defaults, Tranche A values, Tranche B vault
initialisation, liquidation equations, confidence transitions, price-response
equations, auction mechanics, agent decisions or simulation update order.

## Semantic audit

### Market inputs

The current legacy market process is
`price_process.generate_gbm_price_path`. It generates the complete price path
before simulation. The GBM equation applies log returns of the form:

`(mu - 0.5 * sigma^2) * dt + sigma * sqrt(dt) * epsilon`.

The exposed legacy `mu` and `sigma` are annualised GBM parameters and the
default `dt` is `1 / 365`. Phase 2A estimates are hourly log-return moments,
so they are not substituted into the legacy GBM fields. Tranche C instead uses
the validated hourly log-return representation directly.

The simulation timestep is one abstract step. In empirical Tranche C runs it is
treated as one hour because the supplied empirical price paths contain one row
per validated hourly return. ETH and BTC/WBTC paths are supplied as aligned
price arrays through the existing multi-collateral price-path interface.

Existing shock generators construct deterministic paths separately. The
primary Tranche C configuration sets `shock_overlay_enabled: false` to avoid
double-counting stress in sampled empirical blocks.

### Gas inputs

The current gas field is `LiquidationConfig.gas_cost`, a fixed USD/DAI scalar
subtracted from keeper expected profit. Existing low, medium, high and
extreme-gas scenarios alter this scalar and, separately, liquidation capacity.

The current simulator does not consume gas price, gas units or ETH-denominated
fees separately. Tranche C therefore generates an external per-step USD gas
cost path and passes it through an optional `gas_cost_path`. When omitted, the
legacy scalar path is unchanged.

The gas component formula is:

`gas_units * sampled_gas_price_gwei * 1e-9 * simulated_ETH_price_usd`.

This is an input construction formula only; it does not change the keeper
profit equation. Runtime component costs use the reconstructed simulated ETH
price consumed by the simulator at the same timestep. The historical ETH price
retained in the market/gas runtime pool is diagnostic provenance only and is
not used to determine runtime component gas costs.

## Runtime-pool construction

The deterministic builder is:

- `scripts/build_market_gas_runtime_pools.py`

It verifies Phase 1A–1C and Phase 2A source checksums, aligns hourly market
and gas rows, records FTX holdout exclusions, applies the primary zero-gas
rule and writes compact runtime artefacts.

### Market/gas hourly pool

- Path: `config/empirical/data/market_gas_hourly_pool.csv`
- Rows: 27,024
- SHA-256: `b69276801bacf789f8ae91789983cc98a8a6d42d0a992940c0bcfa109ca25b7d`

The pool contains timestamp, calibration label, regime label, ETH/WBTC hourly
log returns, ETH/WBTC prices for diagnostics, effective gas-price columns and
block-utilisation diagnostics. It does not contain DAI as an exogenous
simulation price path.

### Liquidation gas pool

- Path: `config/empirical/data/liquidation_gas_pool.csv`
- Rows: 1,287
- Primary eligible rows: 1,283
- Zero observations retained for sensitivity: 4
- SHA-256: `37a5f49f4cc273b9d0d9526609be7f14b91b78939acf26e4dce00b66443e1594`

The primary pool excludes four indeterminate zero gas-price/cost transactions.
The zero-inclusive sensitivity retains them explicitly.

## Market modes

Exactly two market modes are supported:

1. `legacy_gbm`;
2. `empirical_block_bootstrap`.

`legacy_gbm` remains the default. Unknown modes fail validation.

The empirical block process uses aligned moving blocks of ETH and WBTC hourly
log returns. It draws valid block starts with replacement, concatenates full
blocks, truncates only the final block to the requested horizon and constructs
prices sequentially from configured starting prices. Historical absolute price
levels are not spliced into the simulated path.

## Gas modes

Exactly three gas modes are supported:

1. `legacy_scalar`;
2. `empirical_components`;
3. `empirical_total_cost`.

`legacy_scalar` remains the default.

`empirical_components` is the primary Tranche C gas mode. It samples clean
successful-Take gas units and combines them with the sampled hourly network
gas price and the reconstructed simulated ETH price for the same simulation
timestep. The resulting USD cost is passed into the existing scalar gas-cost
input.

`empirical_total_cost` is a compatibility sensitivity mode. It samples the
observed total USD transaction-cost distribution directly and does not model
gas-price and ETH-price dependence separately.

## Block length and FTX withholding

The primary block length is 168 hours. Bounded sensitivities use 72 and 336
hours.

| Block length | Valid block starts | FTX overlaps |
| ---: | ---: | ---: |
| 72 | 26,401 | 0 |
| 168 | 26,209 | 0 |
| 336 | 25,873 | 0 |

The withheld FTX validation period is:

- 2022-11-01 00:00:00 UTC through 2022-11-20 23:00:00 UTC.

No runtime calibration block may overlap that period. The first source row is
also not an eligible block start because its hourly return is structurally
missing.

## Configurations

Primary:

- `config/empirical/phase2_empirical_market_gas.yaml`

Sensitivity files:

- `config/empirical/sensitivity/phase2_empirical_market_gas_block_72.yaml`
- `config/empirical/sensitivity/phase2_empirical_market_gas_block_336.yaml`
- `config/empirical/sensitivity/phase2_empirical_market_gas_high_gas_q90.yaml`
- `config/empirical/sensitivity/phase2_empirical_market_gas_zero_inclusive.yaml`
- `config/empirical/sensitivity/phase2_empirical_market_blocks_legacy_gas.yaml`

All configurations reproduce the Tranche B scalar and vault-initialisation
settings explicitly. Tranche A and Tranche B YAML files are unchanged.

## Diagnostics

Generated diagnostics are written under the ignored directory:

- `data/processed/estimation/tranche_c/`

The 500-step validation sample preserves strong ETH/WBTC dependence:

- source Pearson correlation: 0.840512;
- generated Pearson correlation: 0.860279;
- source Spearman correlation: 0.830803;
- generated Spearman correlation: 0.844185.

Market–gas diagnostics show positive association between absolute ETH returns
and median gas price:

- Pearson correlation between absolute ETH return and gas price: 0.147045;
- median gas during high-volatility ETH hours: 50.307587 gwei;
- median gas during other hours: 25.882116 gwei;
- stress-labelled share of high-volatility hours: 0.617470.

Gas-process diagnostics record the corrected primary component-gas sample
median at 23.663254 USD for the bounded 500-step diagnostic path. The previous
historical-price-linked value of 40.678889 USD is superseded. The direct
zero-inclusive total-cost sensitivity has a median of 67.560962 USD in the
same diagnostic draw. These are smoke diagnostics, not adopted parameter
estimates.

## Smoke validation

Six bounded smoke runs completed:

1. legacy GBM plus legacy scalar gas;
2. Tranche B empirical-joint initialisation with legacy GBM and legacy gas;
3. empirical market blocks with legacy scalar gas;
4. 168-hour empirical blocks with component gas;
5. 72-hour empirical blocks with component gas;
6. 336-hour empirical blocks with component gas.

All produced finite positive ETH prices, non-negative gas inputs and separated
output provenance.

## FTX validation

An existing FTX validation artefact is available and copied into the Tranche C
diagnostics with an explicit validation-only note. It is not used to build
runtime pools, select block length, tune gas inputs or estimate parameters.

## Legacy preservation

Legacy GBM and scalar gas remain the defaults:

- `MarketProcessConfig().mode == "legacy_gbm"`;
- `GasProcessConfig().mode == "legacy_scalar"`.

The optional `gas_cost_path` is inactive unless supplied. With a constant path
equal to the scalar configuration value, simulation output is identical to the
legacy scalar gas path.

## Limitations

The component gas mode maps clean successful-Take gas evidence to the current
simulator's single liquidation gas-cost scalar. It does not yet distinguish
Bark, failed attempts, auction settlement, all liquidation-related
transactions or multi-action transaction gas. These clean successful-Take
observations are therefore a compatibility proxy for the current scalar
interface, not direct estimates for every liquidation-related action.

Empirical market and gas inputs are hourly, so one Tranche C simulation step is
interpreted as one hour. Several behavioural, confidence and liquidation
capacity controls remain abstract per-step quantities pending later
frequency-aware calibration; Tranche C does not recalibrate those controls.

The empirical block process is a bootstrap, not a Markov regime model. Block
concatenation may move between empirical regimes at boundaries, but price
levels are reconstructed from returns to avoid artificial historical
price-level jumps.

## Recommended next tranche

The next tranche should remain separately authorised. Candidate directions are
liquidation-arrival/throughput interfaces or behavioural calibration. Tranche C
does not implement hurdle liquidations, auction execution or confidence
mechanics.
