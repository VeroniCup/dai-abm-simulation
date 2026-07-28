# Raw Dune market data

The Phase 1A source is `prices.hour`, queried by
`sql/dune_hourly_market_prices.sql` for Ethereum WETH, WBTC, DAI and USDC. WETH
is labelled `ETH`, while WBTC remains `WBTC` as the BTC-collateral price proxy.

The private temporary production query covered the half-open UTC interval from
2021-06-01 00:00:00 to 2024-07-01 00:00:00. Its untouched CSV is kept here,
while the execution sidecar and validation report are under
`data/market/provenance/`; generated artefacts are ignored by Git. They can be
identified and integrity-checked using the temporary query ID,
execution ID, SQL checksum and raw-file checksum committed in
`data/provenance/data_manifest.csv`.

Run the local validation without modifying the raw result:

```bash
python workflows/market/validate.py \
  data/market/raw/dune_prices_hourly_2021-06-01_2024-06-30.csv
```

The acquisition script supports explicit saved-query and temporary-query
modes. It never silently switches modes or automatically retries an execution.
`DUNE_API_KEY` must be supplied through the environment and must not be stored
in this repository.
