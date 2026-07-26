-- Phase 1C production unique transaction bridge: 16_2022_09.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x0a22d6f3e26f954e68ddebc0a32331f0f8474e52ea11c7c91dbc78f2196185bc),
        (0x1361950704955aa7cb859667e7e51a96f112265fb06a76b74d5a2de275b60302),
        (0x3294d9715883b7cc7d5098d25d5e7a014a1d368445a5a835b23642729cd8e2c7),
        (0x532f54f6be96cac7b3ce285ac8931fcef9ff5ef2e327acf1a9a4d0040e03545e),
        (0x60d9aa1de054884827dc5e7ae032dbe8e09e5da09f3145138d6d4cdf7c18367c),
        (0x779144d5449077954aac0dc265c5aeaf22f5e822b64668254ce3d9179282d1bc),
        (0x8c51741946b37f71e89ee43d7eb75b227aa8e6363b38e14d59d279a70b336b54),
        (0x93304dddae85b512c73286205d50edfc2f336707dd6d39c06399c06636bc82d8),
        (0xad0f92aedc1adb8fcd87039b8c5cf64505584113dd6aabef15af3a2cdd040745),
        (0xb279f7abb25319d66d07d39cb386aaee5b806b6182e761ef65351b3e824b6e1e),
        (0xb41e587b1c6302fcd3334125063f9afb5994d4da6163fc00874030f0fcfdbb15),
        (0xc9732c9733ce8487d47a4952d2ce43e8927c90fb6f60efd50d54e0321b70ce6e),
        (0xd4c612e5f01c649fb27de7b4ac3554cd7654d5eb47e6dd94bc43974038c5c135),
        (0xe83ebb39d81e173e8108110df10cf0de8d8dfc56ef79384be8ff0e52834f5158),
        (0xfedbdd95563358d3ed2167711983252583b1ba4508f396763169b5a28704666f)
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
WHERE t.block_date >= DATE '2022-09-01'
  AND t.block_date < DATE '2022-10-08'
  AND t.block_time >= TIMESTAMP '2022-09-01 00:00:00'
  AND t.block_time < TIMESTAMP '2022-10-08 00:00:00'
