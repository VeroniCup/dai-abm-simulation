# Market and gas calibration

## Evidence

The continuous hourly sample covers 1 June 2021 through 30 June 2024:

- market panel:
  `data/market/processed/dune_hourly_market_prices_processed.csv`;
- network gas panel:
  `data/gas/processed/dune_ethereum_hourly_gas_processed.csv`;
- joined environment panel:
  `data/market/processed/combined/hourly_market_gas_panel.csv`;
- tracked runtime blocks:
  `data/market/model_inputs/environment_blocks/pool.csv`.

The raw market instruments are ETH through WETH, WBTC as the Maker
BTC-collateral proxy, DAI and USDC. WBTC is not relabelled as native BTC in raw
data. The simulation adapter maps it into the BTC model class while retaining
wrapper provenance.

## Derived variables

Market calibration uses hourly log returns, absolute returns, cross-asset
dependence, DAI and USDC peg deviations and aligned market–gas blocks. Gas
calibration retains median and upper-tail effective gas prices, base and
priority fees, utilisation, failed-transaction share and their changes.

Pre-London structural base-fee and priority-fee nulls remain null. Effective
gas price is the cross-period gas-price measure. Full-sample and annual
quantiles are descriptive; regime thresholds are validated against nearby
specifications.

## Estimation

The active calibration modules are:

- [`market.py`](../../src/dai_sim/calibration/market.py);
- [`gas.py`](../../src/dai_sim/calibration/gas.py);
- [`statistics.py`](../../src/dai_sim/calibration/statistics.py).

The runtime environment input uses aligned empirical blocks to preserve serial
and cross-domain dependence. The 168-hour block is the reviewed default
candidate; 72- and 336-hour blocks remain sensitivity choices. The FTX window
from 1–21 November 2022 is withheld from primary threshold and candidate
estimation.

## Gas-cost interpretation

The hourly network panel measures the price of gas, not liquidation-specific
gas units. A transaction cost is:

\[
\text{gas cost USD} =
\text{gas used}
\times \text{effective gas price in wei}
\times 10^{-18}
\times \text{ETH/USD}.
\]

Liquidation-specific gas observations are owned by the liquidation domain.
Standardised 100,000, 300,000 and 500,000 gas indices in the processed panel
are comparison indices, not estimates of Maker keeper costs.

## Runtime interface

Empirical blocks and component gas processes are opt-in through
`config/profiles/empirical.yaml`. Legacy geometric-Brownian-motion prices and
scalar gas remain available through `config/profiles/legacy.yaml`. Gas
sensitivity overrides live under `config/sensitivities/gas/`; market block
sensitivities live under `config/sensitivities/market/`.

## Limitations

Hourly aggregation removes transaction-level bidding heterogeneity. Dune
percentiles are approximate. WBTC introduces wrapper-specific risk, and the
sample does not alone identify behavioural confidence parameters or causal
links between gas, returns and liquidation activity.
