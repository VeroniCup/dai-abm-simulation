-- Phase 1C production unique transaction bridge: 32_2024_01.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x0f9ff57afc9b0b2f99eed525e3d360ff1182552ec2c2d06319beba6b35e4a451),
        (0xc063cabbe59bc8d4ac7cd6da93b0adc1f6ae67e72b3e454e379cfb04b5f97076)
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
WHERE t.block_date >= DATE '2024-01-01'
  AND t.block_date < DATE '2024-02-08'
  AND t.block_time >= TIMESTAMP '2024-01-01 00:00:00'
  AND t.block_time < TIMESTAMP '2024-02-08 00:00:00'
