-- Phase 1C production unique transaction bridge: 30_2023_11.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x017cbf1bca11f7fc29eeb1886495907d752b47bfc7a380afde14e49e7f4fcdf3),
        (0xb7e4a925a025e4f31d3185d9268a6cea7bbc8df0d640e4b0f657d0c0d5ba8958),
        (0xeb360602a8c0111940fab4a7429898ff79a7aea58498952c648c0abbec9061ef)
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
WHERE t.block_date >= DATE '2023-11-01'
  AND t.block_date < DATE '2023-12-08'
  AND t.block_time >= TIMESTAMP '2023-11-01 00:00:00'
  AND t.block_time < TIMESTAMP '2023-12-08 00:00:00'
