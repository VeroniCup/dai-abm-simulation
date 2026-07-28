-- Phase 1C production unique transaction bridge: 35_2024_04.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x08824c0acbbd0cc5cd7d32c5750064cf0fbb0ff1ca2d82ac8179c1b57077c573),
        (0x1837f04da1c968366a6da98c9f88737140083378e7c61f79be9df10bd9700d93),
        (0x24265f71bbe0e0287b0ef8a1e6f3e0f18faeb479f356562ff54d526d3b77bea0),
        (0x2a7836dbfab3606ecfd36ccde88591d8de22034fcabec7d2fec22508b06ce52a),
        (0x5cfdc8b1758a494a3d44379ab06600327d3a46aa176ddd67133678655d6231be),
        (0x6308bf50c23e442e6b2c21d280ae9d5a21fd51f7ca2af07ffc65a6f71aad5cf4),
        (0x6ca78455f45593ec96d88d9f57f22c906892e4e58fc585ebf97e167652cab701),
        (0x86f0d738b1b45fa724a80315d488f3b751917a3892dfcf1fbbe8533a98349019),
        (0x8d549c523c4c0abd7c6df7125fe8d2ea2caf0be3ac47e58934167ce7a187ce0c),
        (0xa0e582a4f843165f3d414ffe7ade3e640d200275ae770ee3d695da9cad6c6293),
        (0xa1c3e8dffbff352a81e73f26e3eb1b633deda7ded1ba929b0871c4af208089ad),
        (0xa3deaeb72d2a09a20b52743551b81942662ab7b0ece7d8ff6099cbbbe15a6885),
        (0xb003d522e4439696aa10a1fbff5abee9bd4fb96ff338a4c5df3abaf5de086c21),
        (0xe571d77e2d4753d5be63fb22d8dd93eb2ce2539c2f7686ca303fa0252170e52d)
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
WHERE t.block_date >= DATE '2024-04-01'
  AND t.block_date < DATE '2024-05-08'
  AND t.block_time >= TIMESTAMP '2024-04-01 00:00:00'
  AND t.block_time < TIMESTAMP '2024-05-08 00:00:00'
