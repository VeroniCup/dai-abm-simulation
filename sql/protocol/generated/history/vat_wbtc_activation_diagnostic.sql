-- Phase 1D bounded diagnostic: WBTC-B/C Vat onboarding and first settings.
WITH
selected_ilks(ilk, ilk_raw) AS (
    VALUES
        ('WBTC-B', 0x574254432d420000000000000000000000000000000000000000000000000000),
        ('WBTC-C', 0x574254432d430000000000000000000000000000000000000000000000000000)
),
initialisations AS (
    SELECT
        i.ilk,
        'init' AS call_type,
        'init' AS parameter_key,
        CAST(NULL AS varchar) AS raw_value,
        CAST(NULL AS double) AS converted_value_dai,
        c.call_block_time AS block_time,
        c.call_block_number AS block_number,
        c.call_tx_index AS transaction_index,
        ARRAY_JOIN(TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.') AS call_position,
        CONCAT('0x', TO_HEX(c.call_tx_hash)) AS transaction_hash,
        CONCAT('0x', TO_HEX(c.contract_address)) AS vat_contract
    FROM maker_ethereum.vat_call_init c
    JOIN selected_ilks i ON c.ilk = i.ilk_raw
    WHERE c.call_success = true
      AND c.contract_address = 0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b
      AND c.call_block_date >= DATE '2019-11-01'
      AND c.call_block_date < DATE '2024-07-01'
      AND c.call_block_time >= TIMESTAMP '2019-11-01 00:00:00'
      AND c.call_block_time < TIMESTAMP '2024-07-01 00:00:00'
),
settings AS (
    SELECT
        i.ilk,
        'file' AS call_type,
        CASE c.what
            WHEN 0x6c696e6500000000000000000000000000000000000000000000000000000000 THEN 'line'
            WHEN 0x6475737400000000000000000000000000000000000000000000000000000000 THEN 'dust'
        END AS parameter_key,
        CAST(c.data AS varchar) AS raw_value,
        CAST(c.data AS double) / 1e45 AS converted_value_dai,
        c.call_block_time AS block_time,
        c.call_block_number AS block_number,
        c.call_tx_index AS transaction_index,
        ARRAY_JOIN(TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.') AS call_position,
        CONCAT('0x', TO_HEX(c.call_tx_hash)) AS transaction_hash,
        CONCAT('0x', TO_HEX(c.contract_address)) AS vat_contract
    FROM maker_ethereum.vat_call_file c
    JOIN selected_ilks i ON c.ilk = i.ilk_raw
    WHERE c.call_success = true
      AND c.contract_address = 0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b
      AND c.what IN (
          0x6c696e6500000000000000000000000000000000000000000000000000000000,
          0x6475737400000000000000000000000000000000000000000000000000000000
      )
      AND c.call_block_date >= DATE '2019-11-01'
      AND c.call_block_date < DATE '2024-07-01'
      AND c.call_block_time >= TIMESTAMP '2019-11-01 00:00:00'
      AND c.call_block_time < TIMESTAMP '2024-07-01 00:00:00'
)
SELECT ilk, call_type, parameter_key, raw_value, converted_value_dai,
       block_time, block_number, transaction_index, call_position,
       transaction_hash, vat_contract
FROM initialisations
UNION ALL
SELECT ilk, call_type, parameter_key, raw_value, converted_value_dai,
       block_time, block_number, transaction_index, call_position,
       transaction_hash, vat_contract
FROM settings
ORDER BY block_time, block_number, transaction_index, call_position, call_type
