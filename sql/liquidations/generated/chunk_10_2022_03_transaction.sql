-- Phase 1C production unique transaction bridge: 10_2022_03.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x0141a467b06624ab304490fcd8657e74a408a164542d30217216bfd047ba8e2f),
        (0x05de091b49f8f1db9afabccf3d69a5ab2b4ef342b2c21822832bbe9b731f8e33),
        (0x0f2da734cfdc502d36b58d69dbb9c2399b964e3224ad54f9d425b7cd34b2a745),
        (0x0fb5bfc074f17ce60d4b625a1a8aff742ab0beb12af315cec724a443436450fe),
        (0x90ac3b7e065ab0ebc908ac152f6fa2f0dcac1c36a751cced6552bdb96636a28b),
        (0xadd8cc0bd37fda05ada3e43d9d2c7b7ced42d3eb0daae017fa7b7c135cb805d3),
        (0xbd2326653599c1fb8cc68cce0a6062d843644bb5b1c295a0b6e6445a039ad743),
        (0xc76f4cc12064e8904f0d0de1fedb37b4fff59038050ee2b857055fc586ae053f),
        (0xd8e2fc689d230b77e831daee03f290d59eee98f0121f35f4f741a0fa2388a446)
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
WHERE t.block_date >= DATE '2022-03-01'
  AND t.block_date < DATE '2022-04-08'
  AND t.block_time >= TIMESTAMP '2022-03-01 00:00:00'
  AND t.block_time < TIMESTAMP '2022-04-08 00:00:00'
