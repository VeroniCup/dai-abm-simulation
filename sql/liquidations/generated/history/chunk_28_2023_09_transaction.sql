-- Phase 1C production unique transaction bridge: 28_2023_09.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x6374040316b6e49f2093ba8493f97b87e976023ec70552987a1e9d499b16a4fc),
        (0x7e7a2d4c5230497855c450f38d8d14a387ecfd075a7796a6d7824465f95512e8),
        (0xf64ca2f440630b4bc26cd28dcc804cf1bd4b52917587503241cd8ceaa009c604)
)
SELECT
    CONCAT('0x', TO_HEX(t.hash)) AS tx_hash,
    CONCAT('0x', TO_HEX(t."from")) AS transaction_sender,
    CONCAT('0x', TO_HEX(t."to")) AS transaction_recipient,
    t.success,
    t.gas_limit,
    t.gas_used,
    t.gas_price,
    t.max_fee_per_gas,
    t.max_priority_fee_per_gas,
    t.priority_fee_per_gas,
    t.block_time,
    t.block_number,
    t.block_date,
    t.index AS transaction_index
FROM ethereum.transactions t
JOIN selected_hashes h ON t.hash = h.tx_hash
WHERE t.block_date >= DATE '2023-09-01'
  AND t.block_date < DATE '2023-10-08'
  AND t.block_time >= TIMESTAMP '2023-09-01 00:00:00'
  AND t.block_time < TIMESTAMP '2023-10-08 00:00:00'
