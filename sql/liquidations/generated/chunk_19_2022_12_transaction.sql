-- Phase 1C production unique transaction bridge: 19_2022_12.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x757492ae12cbe977989c31c80b889adb39cb4d9231fa9b5dc8dbc3fdb56db4da),
        (0xfcacffec58ca8f7410674af4458016ac138a991294d78d77bcd7ab96e5793ebc)
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
WHERE t.block_date >= DATE '2022-12-01'
  AND t.block_date < DATE '2023-01-08'
  AND t.block_time >= TIMESTAMP '2022-12-01 00:00:00'
  AND t.block_time < TIMESTAMP '2023-01-08 00:00:00'
