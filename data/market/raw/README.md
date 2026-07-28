# Raw market data

The source is Dune `prices.hour`, queried by
`sql/market/templates/hourly_prices.sql` for Ethereum WETH, WBTC, DAI and
USDC. WETH is labelled ETH; WBTC remains WBTC as the BTC-collateral price
proxy.

The validated production interval is half-open from 1 June 2021 to 1 July
2024 UTC. Untouched result CSVs stay here; checksums, query and execution
identifiers and validation records live under `data/market/provenance/`.
Generated payloads are ignored by Git.

Local validation does not alter the raw result:

```bash
python workflows/market/validate.py \
  data/market/raw/dune_prices_hourly_2021-06-01_2024-06-30.csv
```

Live acquisition requires `DUNE_API_KEY` in the environment. The workflow
never silently switches mode or automatically retries an execution. See the
[acquisition guide](../../../docs/data/acquisition.md).
