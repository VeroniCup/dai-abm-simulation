-- Phase 1C production unique transaction bridge: 03_2021_08.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x02ede72d930d87cc4c7bbbad9c0a2cd156a0bbc533c246363d4138c673437790),
        (0x0566785ba38e841276feb4017c08e18e771ed9b861244bc12f69a043955d411b),
        (0x2a9610c6525ab6e6fb6bee05e876bf1282f7e60d7df8607f36298e593ab73f37),
        (0x2c1bdb26e1c1714989b05d8dbab5a9bb8ee3f088704ff734ddf37b7409882a8f),
        (0x55dbac7c70e61c71a45554e2a02d1c8cda586102d7a884e133f9c97da34498ab),
        (0x5e9cd95b07d78031c3dbb3ffd78b7c41680f46a3e0da11a7f8e154d233a37013),
        (0x68efbffe509ff78056ebe4ed62e72dd131d0b7c7804a6a6584c7972876bbd568),
        (0x70240c051299ce2f71cc96b1eff958f4c0a92129c0e6944305ea91f1ceabb1ea),
        (0x754761dfba9d63d9803df93495b16b343b727cac3009f6f0dc627af224829fb6),
        (0x91d081aeedec6330ca9ea0dd4f6a1eddd2055926c6ec40ab67d4847f6eafa49f),
        (0x9558655f2aec8611ea996b699401ea03ebce670769df6ae52453d7252505f4be),
        (0xa565ef87706973e3e9aa880937c623125c24bace9dcf340a6fcb97c261270519),
        (0xa96339204c82406b67177de4b936bb2a1ff473b9323fec07cbd2d9b6e248172e),
        (0xc627f970a6ccf78988e1261aa5a7e1c8ae7ed3497de629966c22f6427eb6a606),
        (0xdbea2a976b8f155e0bdd558ef626b11560d0d26530023d3529861a38b937d054),
        (0xe76d3fd3b8159dcd190d1bc3be37b68f4951c42890bec0baf9e0c4a20ab784d2),
        (0xf1605fa8067e0bc2e2f3cd3ed0379381779d0fd3bad521c334ed2f9e4d7022e6)
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
WHERE t.block_date >= DATE '2021-08-01'
  AND t.block_date < DATE '2021-09-08'
  AND t.block_time >= TIMESTAMP '2021-08-01 00:00:00'
  AND t.block_time < TIMESTAMP '2021-09-08 00:00:00'
