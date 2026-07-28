-- Phase 1C production unique transaction bridge: 17_2022_10.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x9392a3280457aa8fe042df217c687e90996cee8d744de4dc3dae50ab1d22c072),
        (0xeaba2d3a0456030c4d97a653bb1f1e069aba67ae3cf4fbde9314a69f1a2a5d12),
        (0xf4848b64e4eb2e841db6b085f4729ba1a73f85ab2298ce84963f617997027059)
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
WHERE t.block_date >= DATE '2022-10-01'
  AND t.block_date < DATE '2022-11-08'
  AND t.block_time >= TIMESTAMP '2022-10-01 00:00:00'
  AND t.block_time < TIMESTAMP '2022-11-08 00:00:00'
