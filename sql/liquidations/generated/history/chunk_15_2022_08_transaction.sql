-- Phase 1C production unique transaction bridge: 15_2022_08.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x05db7e29b189481ebd274c458bf953169f604421465e0f724701d7b4d12d0e51),
        (0x0b4cf83dd202306e6ec64f2c01e4f9739c5476a5a65c21bec561600d5fcac154),
        (0x5c47c3e336e7bc1b668a13702fa59e3ddef86d64a3cab44af5efeef61218bce4),
        (0x648838f45cf79531870ef2b92b334c682bf95585ce53c19108dce199b9113374),
        (0x77eaf65d53af45d4d37460e93188b55942f3ffc29538ccef6ec5e052e0029672),
        (0xd5e459bf836993ff76d21279a73cb462950d417274bbe1506697ea125de1def2),
        (0xd8cb2b70baf8c759898d4961d1a8b5fcfd728205622d551ddc55a16543ed463a),
        (0xf36a81e5a49f292dcb13c6904c98c90c85ce3bd9c319108f8b06d8f5062540ec)
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
WHERE t.block_date >= DATE '2022-08-01'
  AND t.block_date < DATE '2022-09-08'
  AND t.block_time >= TIMESTAMP '2022-08-01 00:00:00'
  AND t.block_time < TIMESTAMP '2022-09-08 00:00:00'
