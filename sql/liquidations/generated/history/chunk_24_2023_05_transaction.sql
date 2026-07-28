-- Phase 1C production unique transaction bridge: 24_2023_05.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x0cb9ebecf5ed8fe318753e171000165eb2798ca15ca7810e9f4f95d97ad92c7a),
        (0x2d3450935f0e14d0bbe48c33bc368702177368377136c50292ccbe5da89d2ee8),
        (0x8a45aa2a493123195a2a4291c923c774449280bbda757e67addf1f503ea6edfe),
        (0xf6daaaa58bb37cae8d875f9c470cbc24c922295a4ec966ad6d1009362e4a7cea)
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
WHERE t.block_date >= DATE '2023-05-01'
  AND t.block_date < DATE '2023-06-08'
  AND t.block_time >= TIMESTAMP '2023-05-01 00:00:00'
  AND t.block_time < TIMESTAMP '2023-06-08 00:00:00'
