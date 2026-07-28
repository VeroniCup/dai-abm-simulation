-- Phase 1D minimal replacement diagnostic: Clipper creation and stopped calls.
WITH
clipper_universe (
    ilk, clipper_contract, mapping_time, mapping_block, mapping_tx_hash
) AS (
    VALUES
        ('ETH-A', 0xc67963a226eddd77b91ad8c421630a1b0adff270,
         TIMESTAMP '2021-05-06 15:45:10', BIGINT '12381609',
         0x42e122bb5c4addef1bd8c74402178ac982ef813d72c7f846743efd6f8b3cd092),
        ('ETH-B', 0x71eb894330e8a4b96b8d6056962e7f116f50e06f,
         TIMESTAMP '2021-05-06 15:45:10', BIGINT '12381609',
         0x42e122bb5c4addef1bd8c74402178ac982ef813d72c7f846743efd6f8b3cd092),
        ('ETH-C', 0xc2b12567523e3f3cbd9931492b91fe65b240bc47,
         TIMESTAMP '2021-05-06 15:45:10', BIGINT '12381609',
         0x42e122bb5c4addef1bd8c74402178ac982ef813d72c7f846743efd6f8b3cd092),
        ('WBTC-A', 0x0227b54adbfaeec5f1ed1dfa11f54dcff9076e2c,
         TIMESTAMP '2021-05-06 15:45:10', BIGINT '12381609',
         0x42e122bb5c4addef1bd8c74402178ac982ef813d72c7f846743efd6f8b3cd092),
        ('WBTC-B', 0xe30663c6f83a06edee6273d72274ae24f1084a22,
         TIMESTAMP '2021-11-22 14:03:13', BIGINT '13664911',
         0xd0bc8bb58931497ce575f3d1afda63890a226cef7fa08d80c98d78f70c74567d),
        ('WBTC-C', 0x39f29773dcb94a32529d0612c6706c49622161d1,
         TIMESTAMP '2021-11-29 14:00:07', BIGINT '13709002',
         0xab810a967ba4a68862c4433ec4185fbe1a3ff121bf4b38535a2aab4a8e9908a4)
),
creation_rows AS (
    SELECT
        'contract_creation' AS record_type,
        u.ilk,
        CONCAT('0x', TO_HEX(u.clipper_contract)) AS contract_address,
        u.mapping_time,
        u.mapping_block,
        CONCAT('0x', TO_HEX(u.mapping_tx_hash)) AS mapping_tx_hash,
        CONCAT('0x', TO_HEX(t."from")) AS creator,
        CONCAT('0x', TO_HEX(t.tx_hash)) AS transaction_hash,
        t.block_time,
        t.block_number,
        ARRAY_JOIN(
            TRANSFORM(t.trace_address, x -> CAST(x AS varchar)), '.'
        ) AS trace_position,
        t.success,
        CONCAT('0x', TO_HEX(KECCAK(t.code))) AS creation_code_hash,
        CAST(NULL AS varchar) AS raw_stopped_value,
        CAST(NULL AS bigint) AS stopped_value
    FROM clipper_universe u
    JOIN ethereum.traces t
      ON t.address = u.clipper_contract
     AND t.type IN ('create', 'create2')
    WHERE t.block_date >= DATE '2020-01-01'
      AND t.block_date < DATE '2022-01-01'
),
stopped_call_rows AS (
    SELECT
        'stopped_file_call' AS record_type,
        u.ilk,
        CONCAT('0x', TO_HEX(u.clipper_contract)) AS contract_address,
        u.mapping_time,
        u.mapping_block,
        CONCAT('0x', TO_HEX(u.mapping_tx_hash)) AS mapping_tx_hash,
        CAST(NULL AS varchar) AS creator,
        CONCAT('0x', TO_HEX(c.call_tx_hash)) AS transaction_hash,
        c.call_block_time AS block_time,
        c.call_block_number AS block_number,
        ARRAY_JOIN(
            TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.'
        ) AS trace_position,
        c.call_success AS success,
        CAST(NULL AS varchar) AS creation_code_hash,
        CAST(c.data_uint256 AS varchar) AS raw_stopped_value,
        TRY_CAST(c.data_uint256 AS bigint) AS stopped_value
    FROM clipper_universe u
    JOIN maker_ethereum.clipper_call_file c
      ON c.contract_address = u.clipper_contract
    WHERE c.what = 0x73746f7070656400000000000000000000000000000000000000000000000000
      AND c.call_block_date >= DATE '2020-01-01'
      AND c.call_block_date < DATE '2024-07-01'
      AND c.call_block_time < TIMESTAMP '2024-07-01 00:00:00'
)
SELECT
    record_type, ilk, contract_address, mapping_time, mapping_block,
    mapping_tx_hash, creator, transaction_hash, block_time, block_number,
    trace_position, success, creation_code_hash, raw_stopped_value,
    stopped_value
FROM creation_rows
UNION ALL
SELECT
    record_type, ilk, contract_address, mapping_time, mapping_block,
    mapping_tx_hash, creator, transaction_hash, block_time, block_number,
    trace_position, success, creation_code_hash, raw_stopped_value,
    stopped_value
FROM stopped_call_rows
ORDER BY block_time, block_number, transaction_hash, trace_position, record_type
