-- Phase 1C production unique transaction bridge: 21_2023_02.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x2b306d1dac826293e12c5f4018c552bdfc0c823630384d97c7712267973c0b42),
        (0x6c3d4c9144691e022deb21670c2dbba83c5285b144b12aa2826dec1ceca554b0)
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
WHERE t.block_date >= DATE '2023-02-01'
  AND t.block_date < DATE '2023-03-08'
  AND t.block_time >= TIMESTAMP '2023-02-01 00:00:00'
  AND t.block_time < TIMESTAMP '2023-03-08 00:00:00'
