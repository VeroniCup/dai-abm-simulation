-- Phase 1C production unique transaction bridge: 26_2023_07.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x4d07f2fe3f2e15caad94e8937ae5c7f6d4fca65b40fff73d3fd3aaebccc6cbb4),
        (0x8c644b24673dee437f626325e4d2689d6eaa7ea3554d2175276c83d48a8d5f23)
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
WHERE t.block_date >= DATE '2023-07-01'
  AND t.block_date < DATE '2023-08-08'
  AND t.block_time >= TIMESTAMP '2023-07-01 00:00:00'
  AND t.block_time < TIMESTAMP '2023-08-08 00:00:00'
