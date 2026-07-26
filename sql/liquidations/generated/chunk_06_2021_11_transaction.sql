-- Phase 1C production unique transaction bridge: 06_2021_11.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x0295beacc561536891e418a078f761eb844baaf941337fb08771df23a34a6ede),
        (0x109bfb89c86923c6ff02f372efb0241abe0739acbfe7a9c03f9221f6e141c57d),
        (0x1250b1ec83e2975e304a72f6e78ffef38785850cbc962d2e328d11bde56dec91),
        (0x20a8017988e6df07fed36c435c2db647d87780f6a1bf3806947b52ff9c4b8adc),
        (0x2268a3707b61a147b4ae7547273621ddfa82f0a04637d5b35cfab656f7c964ec),
        (0x696ecf27c044a56c3ec4b9bc44d75ad3638acb1e278a92d5de2e6cd560a41b65),
        (0x7899662d0e450d8456818047410808f0545d3ca0e43f183aa87e2807a720a70e),
        (0x83ba6b033804ddf9baf59f30dfb75232bb52adba3ca323c9029f04f5fec1db79),
        (0x84e08974c31b77e7655771d450c1169be51ec742f8de8c3fd9b8954555e4b755),
        (0x85902eff81f109df4c9cc9fe18fdd74847ffb2d900ae852dcf4f7f2b83952ea2),
        (0x866db3fc3dec169c8862e805c768d61940bcbdc7fbc5d0bce0efe1bf058fcbd8),
        (0x9848464d86bf65bb91b02231c49abb1d7c1bf345f8acc0c913898ded73127880),
        (0xa13e69728b365af9df051bafa30c5e76ccf59915b78c30b036a31c5e73878d03),
        (0xa4a41e9d1a26bec66cf5b4d486195c71c88ac1bb59c2a5143e33f436cb21720c),
        (0xadc536c0f84a79eb47632e60b3325a905c6574c2d67376d4c55a0e008a1a7305),
        (0xb014eac31704bde50d89e73d2b234871a6ad83a133372efeb54e36464ac97e8c),
        (0xbbbd88b46f4431b985c8ee2bae6067d307a5673b28de35ca6ba75df8f9790034),
        (0xbfc2013a88988d298dec88ebb683fa556cdfaad4d80be786fbb23c7fe94cf8b3),
        (0xc1e85eba4b8b7d111e9d085e9e08916499b0abfd077e6a3d4b7e0d4efc1cb9b4),
        (0xcf842ce414dfa1e58e851a121f5851a894e2a4d480a3203dceb5e046a2ab3d49),
        (0xd9a414889a1852fe5681d766f83abce899837bced9f235decf8ebcc83a172e72),
        (0xe60641acb9c4a3d1eeb12aff1d07f5970d27411c273bf95dfde640e249dcd4f6),
        (0xe6d4544921c6a3ec3a4f44ba5394077e316bf2747bc47582e6a0844298a25b3c),
        (0xec53d67426b1c552815fa7d2419a0c2b9add7dd8aa449aea7fd7565efb51f683),
        (0xf48f2c9bfc63f057b4cc9079104df3382050e740c5dbe95219091eb134eaf2b5)
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
WHERE t.block_date >= DATE '2021-11-01'
  AND t.block_date < DATE '2021-12-08'
  AND t.block_time >= TIMESTAMP '2021-11-01 00:00:00'
  AND t.block_time < TIMESTAMP '2021-12-08 00:00:00'
