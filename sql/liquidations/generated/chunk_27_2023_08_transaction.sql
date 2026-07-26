-- Phase 1C production unique transaction bridge: 27_2023_08.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x0f2145d3801f6f82e1fa94f38b0d78a0184bebeefe6c216718c6e1054aaa99ce),
        (0x144fd06da2aaeb3bb7d07ca9f25296fe6b6617bd0872acf422dfb87860b26067),
        (0x4124cdf3299833f5ec1af8834fbb04e4be797a4c69696ab439c949ba9b4053f4),
        (0x469034fa16ae8dd3e173031729107eda47dc953c5b0e36431d3ee8504d1b301a),
        (0x47a055c2df88508f18668983600bbeb1b57dd59995c091c632e51beebe969c00),
        (0x489e65ec041d82150ce8ca940f2e7ce8e2a90d08fc39380684d14842ff1a4b79),
        (0x6fd273e857e323de0d74b2eaaf6b63d534e88d94d182f5da5500328d2a6819c7),
        (0x707fdb1e226f98dcbc1a6e5a7fd968185348d5733113aabb539132ad02f9562d),
        (0x83d0ca2a17ba688700ea068ba2553df0b9a5ef22ab6c16b5c9c75ebdcd10df32),
        (0x9c7707b5159b8a2a77d03f2ea3d2b0f7f9d5f364ff87d8f27df70f705c48c253),
        (0xa03a448785435d91ed008757b6092369a8fcf9ef1be7fd6069c8cb99d551a27f),
        (0xb040c236c1d376bcd32d485629b898ab65bda43880529c82629783d669420385),
        (0xb7dadc6652a47115106a620908625aceb5b1ef6d1876e019c917f477e8ac8eb9),
        (0xed0ab38a6c8192999def755fb8eef12dea6b3eda38271210cbe8574e7e463eb2),
        (0xf6313cb322d8ddfd69f9cc45cd80b49d40c13feaf6fb411eb918697b4aa9c62f),
        (0xfb36e60c3a55cce2937e248a34a02de991df60eb1be11b277821f6f3151b0001)
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
WHERE t.block_date >= DATE '2023-08-01'
  AND t.block_date < DATE '2023-09-08'
  AND t.block_time >= TIMESTAMP '2023-08-01 00:00:00'
  AND t.block_time < TIMESTAMP '2023-09-08 00:00:00'
