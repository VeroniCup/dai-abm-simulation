-- Phase 1C production unique transaction bridge: 34_2024_03.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x01c4e90a4c080a3d496030a8038f2c50d92de569ebc31866e28a575e37cb3da5),
        (0x3ccd1137b8548a8a15afc1eed9f2f460016199ca470104c28baf32ac29ba6ae4)
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
WHERE t.block_date >= DATE '2024-03-01'
  AND t.block_date < DATE '2024-04-08'
  AND t.block_time >= TIMESTAMP '2024-03-01 00:00:00'
  AND t.block_time < TIMESTAMP '2024-04-08 00:00:00'
