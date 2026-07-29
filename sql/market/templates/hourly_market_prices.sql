-- Full-range DAI and ETH market evidence for confidence calibration.
--
-- The two assets retain the exact Ethereum contract identities, price field,
-- source field and start-of-hour UTC convention used by the existing
-- prices.hour acquisition.  The final ordering makes result pagination
-- deterministic.

SELECT
    timestamp AS timestamp_utc,
    CASE contract_address
        WHEN 0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2 THEN 'ETH'
        WHEN 0x6b175474e89094c44da98b954eedeac495271d0f THEN 'DAI'
    END AS asset,
    CASE contract_address
        WHEN 0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2 THEN 'WETH'
        WHEN 0x6b175474e89094c44da98b954eedeac495271d0f THEN 'DAI'
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
      0x6b175474e89094c44da98b954eedeac495271d0f
  )
  AND timestamp >= TIMESTAMP '2019-12-31 00:00:00 UTC'
  AND timestamp < TIMESTAMP '2024-07-01 00:00:00 UTC'
ORDER BY timestamp_utc, asset
