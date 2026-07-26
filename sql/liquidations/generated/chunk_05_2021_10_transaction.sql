-- Phase 1C production unique transaction bridge: 05_2021_10.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x0324875833b87b2b8f9fee39d94f8bc96ee63008fe13e6eb52f1b5e060f338b8),
        (0x0350182df293e80b1dc0445b95834231be3dfc0aae11b918f51d75b843a679bc),
        (0x05e0e60f7c7553a6eb8a74cb89dd261fdbd4f4572758cf90d3161ce4ddcebdad),
        (0x0edd69b0dd0f0c0b7b78659134d811b1412a2c60da9bf288e9cf84331011990b),
        (0x1939bf649cec03d91a3cc196b504f43e7660829573bc9ef2fb3fc5bac6d4daf6),
        (0x529a99cae760ffb73b023d9fb7a21ebcaaa47777ed1fe4a0d3984221b2e97138),
        (0x62041e1757746c1486aff8cf48d66bbb80841d8fdf62edf1a4c6bf023441c301),
        (0x678c32acd1d95fb717e7a02ff8b2c2bfe4681422c08a5abb98d0ea88c67c6a83),
        (0x8eaefae348577c3cf05d365c4026c2e149d8c9da9b43c515150cadf9aa9663d5),
        (0x90bbb95be386de7e17542ec40be7053e94ccb7c901e12e22700a9a19feb8fe7c),
        (0xbe019712b8e22638f834501c4a83cca7bad58229cc2f7558c180c33510452f0c),
        (0xc1cf85731c410f64d81f7b6dec235796eb820b5c0a65e4b2223456538a88fae5),
        (0xc633c48f93c9fdcb2329203c22fd066a9e4cfa4f14980b4d040b905295fafec1),
        (0xd06b1fb013c504c5fd2f696c99949b6a98c71ab558fc88853526690458b9d4b8),
        (0xddb334604d85038eac225945206c28f7b72111832b3f04288e0f157c8b4514d9),
        (0xe8c42d3f79ac346099ca43046f5d6ac77f9263de7522d95f640769baec94afc7),
        (0xf0d8dbb89d89c7d03a750e071838afa8b1b836924888aef586ab46dafa8d213d)
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
WHERE t.block_date >= DATE '2021-10-01'
  AND t.block_date < DATE '2021-11-08'
  AND t.block_time >= TIMESTAMP '2021-10-01 00:00:00'
  AND t.block_time < TIMESTAMP '2021-11-08 00:00:00'
