-- Phase 1C production unique transaction bridge: 36_2024_05.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x177ab2ed26746ba7636815088fe2a815913e6fc2adb7af93f1d9bdbeda56a21a),
        (0x3d7ddc753eb09b1fb45a925ecadee08568202e28046c80519b96494f5a82ca38),
        (0x4ebf038556a51f5d7e34efc565dace02e0a56490bc30320f10def55239453573),
        (0x83f19de518d121b63c0325a9edd14b67550939204a8e46a39379c9d1499dadcd),
        (0xc70be732ee3291f2ed63e06f037b212c9708d45998b0befb7a520434a5a6d88c),
        (0xcafd2a7b284a6009d49244b46a74b73af6dd20d713724a0e4bc9762718ece6b9)
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
WHERE t.block_date >= DATE '2024-05-01'
  AND t.block_date < DATE '2024-06-08'
  AND t.block_time >= TIMESTAMP '2024-05-01 00:00:00'
  AND t.block_time < TIMESTAMP '2024-06-08 00:00:00'
