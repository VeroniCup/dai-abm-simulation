-- Phase 1C production unique transaction bridge: 25_2023_06.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0xa37f1487cd2bf82242c2a5d21d2f2bba840851fa7c29ec3d382789c47aa3b2ff),
        (0xa5377309c54ec15e43e66e2d079b7592397810ecf3f94473cbeff765a6c00faa),
        (0xb92b4cba7dded48e7bce36e5b1f398b24f8f528a03e232c0a5109957de2a5d6b)
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
WHERE t.block_date >= DATE '2023-06-01'
  AND t.block_date < DATE '2023-07-08'
  AND t.block_time >= TIMESTAMP '2023-06-01 00:00:00'
  AND t.block_time < TIMESTAMP '2023-07-08 00:00:00'
