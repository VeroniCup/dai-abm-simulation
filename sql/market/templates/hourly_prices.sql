-- Production acquisition query for the dissertation market-price panel.
--
-- This file is intentionally not executed by repository code. Save it as a
-- private Dune query, then pass that saved query ID to the acquisition script.
-- The half-open interval contains 27,024 UTC hours per instrument.

SELECT
    timestamp AS timestamp_utc,
    CASE contract_address
        WHEN 0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2 THEN 'ETH'
        WHEN 0x2260fac5e5542a773aa44fbcfedf7c193bc2c599 THEN 'WBTC'
        WHEN 0x6b175474e89094c44da98b954eedeac495271d0f THEN 'DAI'
        WHEN 0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48 THEN 'USDC'
    END AS asset,
    CASE contract_address
        WHEN 0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2 THEN 'WETH'
        WHEN 0x2260fac5e5542a773aa44fbcfedf7c193bc2c599 THEN 'WBTC'
        WHEN 0x6b175474e89094c44da98b954eedeac495271d0f THEN 'DAI'
        WHEN 0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48 THEN 'USDC'
    END AS dune_instrument,
    price AS price_usd,
    blockchain,
    contract_address_varchar AS contract_address,
    source,
    volume AS volume_usd
FROM prices.hour
WHERE blockchain = 'ethereum'
  AND contract_address IN (
      0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2,
      0x2260fac5e5542a773aa44fbcfedf7c193bc2c599,
      0x6b175474e89094c44da98b954eedeac495271d0f,
      0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48
  )
  AND timestamp >= TIMESTAMP '2021-06-01 00:00:00 UTC'
  AND timestamp < TIMESTAMP '2024-07-01 00:00:00 UTC'
