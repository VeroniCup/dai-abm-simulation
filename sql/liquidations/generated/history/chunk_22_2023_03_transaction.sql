-- Phase 1C production unique transaction bridge: 22_2023_03.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x0a478e77321f49b57efd59e366ceab917d266ea2c37907be1ddf0d270777f9ac),
        (0x3f87579e33995d7c3822ee5a913e6fe8936a9bb7f87b1d7ee49788f5100bf421),
        (0x4556fd194c4170e259733fc360a328c4a4d0932adf860330a65206963b001624),
        (0x9e6888f93bae8cd799ff487b83b5f4a7993fca9937b1c4693d4385e1746cf242),
        (0xc51177894e518ad3eef671fa031ad789473bb1220cccd8df273f7bd959580e79)
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
WHERE t.block_date >= DATE '2023-03-01'
  AND t.block_date < DATE '2023-04-08'
  AND t.block_time >= TIMESTAMP '2023-03-01 00:00:00'
  AND t.block_time < TIMESTAMP '2023-04-08 00:00:00'
