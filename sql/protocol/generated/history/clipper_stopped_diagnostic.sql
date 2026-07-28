-- Phase 1D diagnostic: Clipper deployment evidence and stopped history.
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
deployments AS (
    SELECT
        u.ilk,
        u.clipper_contract,
        u.mapping_time,
        u.mapping_block,
        u.mapping_tx_hash,
        c.block_time AS deployment_time,
        c.block_number AS deployment_block,
        c.tx_hash AS deployment_tx_hash,
        c."from" AS deployer,
        c.code AS creation_code
    FROM clipper_universe u
    LEFT JOIN ethereum.creation_traces c
      ON c.address = u.clipper_contract
     AND c.block_month >= DATE '2021-01-01'
     AND c.block_month < DATE '2022-01-01'
),
catalogue AS (
    SELECT
        address,
        MAX_BY(name, created_at) AS contract_name,
        MAX_BY(namespace, created_at) AS contract_namespace,
        MAX_BY(abi_id, created_at) AS abi_id,
        MAX_BY(code, created_at) AS catalogue_code
    FROM ethereum.contracts
    WHERE address IN (SELECT clipper_contract FROM clipper_universe)
    GROUP BY address
),
stopped_calls AS (
    SELECT
        c.contract_address,
        c.call_block_time AS evidence_time,
        c.call_block_number AS evidence_block,
        c.call_tx_hash AS evidence_tx_hash,
        ARRAY_JOIN(
            TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.'
        ) AS trace_position,
        c.data_uint256 AS raw_stopped
    FROM maker_ethereum.clipper_call_file c
    WHERE c.contract_address IN (SELECT clipper_contract FROM clipper_universe)
      AND c.call_success = true
      AND c.what = 0x73746f7070656400000000000000000000000000000000000000000000000000
      AND c.call_block_date >= DATE '2021-01-01'
      AND c.call_block_date < DATE '2024-07-01'
      AND c.call_block_time < TIMESTAMP '2024-07-01 00:00:00'
),
getter_candidates AS (
    SELECT
        t."to" AS contract_address,
        t.block_time AS evidence_time,
        t.block_number AS evidence_block,
        t.tx_hash AS evidence_tx_hash,
        ARRAY_JOIN(
            TRANSFORM(t.trace_address, x -> CAST(x AS varchar)), '.'
        ) AS trace_position,
        VARBINARY_TO_UINT256(t.output) AS raw_stopped,
        ROW_NUMBER() OVER (
            PARTITION BY t."to"
            ORDER BY t.block_time, t.block_number, t.tx_index, t.trace_address
        ) AS getter_rank
    FROM ethereum.traces t
    WHERE t."to" IN (SELECT clipper_contract FROM clipper_universe)
      AND t.success = true
      AND VARBINARY_SUBSTRING(t.input, 1, 4)
          = VARBINARY_SUBSTRING(KECCAK(TO_UTF8('stopped()')), 1, 4)
      AND LENGTH(t.output) > 0
      AND t.block_date >= DATE '2021-01-01'
      AND t.block_date < DATE '2024-07-01'
      AND t.block_time < TIMESTAMP '2024-07-01 00:00:00'
),
base AS (
    SELECT
        d.*,
        a.contract_name,
        a.contract_namespace,
        a.abi_id,
        a.catalogue_code
    FROM deployments d
    LEFT JOIN catalogue a ON a.address = d.clipper_contract
),
deployment_rows AS (
    SELECT
        b.ilk,
        CONCAT('0x', TO_HEX(b.clipper_contract)) AS contract_address,
        'deployment' AS record_type,
        b.deployment_time,
        b.deployment_block,
        CONCAT('0x', TO_HEX(b.deployment_tx_hash)) AS deployment_tx_hash,
        CONCAT('0x', TO_HEX(b.deployer)) AS deployer,
        CONCAT('0x', TO_HEX(KECCAK(b.creation_code))) AS creation_code_hash,
        CONCAT('0x', TO_HEX(KECCAK(b.catalogue_code))) AS catalogue_code_hash,
        b.contract_name,
        b.contract_namespace,
        b.abi_id,
        b.mapping_time,
        b.mapping_block,
        CONCAT('0x', TO_HEX(b.mapping_tx_hash)) AS mapping_tx_hash,
        b.deployment_time AS evidence_time,
        b.deployment_block AS evidence_block,
        CONCAT('0x', TO_HEX(b.deployment_tx_hash)) AS evidence_tx_hash,
        CAST(NULL AS varchar) AS trace_position,
        CAST(NULL AS varchar) AS raw_stopped
    FROM base b
),
call_rows AS (
    SELECT
        b.ilk,
        CONCAT('0x', TO_HEX(b.clipper_contract)) AS contract_address,
        'stopped_file_call' AS record_type,
        b.deployment_time,
        b.deployment_block,
        CONCAT('0x', TO_HEX(b.deployment_tx_hash)) AS deployment_tx_hash,
        CONCAT('0x', TO_HEX(b.deployer)) AS deployer,
        CONCAT('0x', TO_HEX(KECCAK(b.creation_code))) AS creation_code_hash,
        CONCAT('0x', TO_HEX(KECCAK(b.catalogue_code))) AS catalogue_code_hash,
        b.contract_name,
        b.contract_namespace,
        b.abi_id,
        b.mapping_time,
        b.mapping_block,
        CONCAT('0x', TO_HEX(b.mapping_tx_hash)) AS mapping_tx_hash,
        c.evidence_time,
        c.evidence_block,
        CONCAT('0x', TO_HEX(c.evidence_tx_hash)) AS evidence_tx_hash,
        c.trace_position,
        CAST(c.raw_stopped AS varchar) AS raw_stopped
    FROM base b
    JOIN stopped_calls c ON c.contract_address = b.clipper_contract
),
getter_rows AS (
    SELECT
        b.ilk,
        CONCAT('0x', TO_HEX(b.clipper_contract)) AS contract_address,
        'earliest_observed_getter' AS record_type,
        b.deployment_time,
        b.deployment_block,
        CONCAT('0x', TO_HEX(b.deployment_tx_hash)) AS deployment_tx_hash,
        CONCAT('0x', TO_HEX(b.deployer)) AS deployer,
        CONCAT('0x', TO_HEX(KECCAK(b.creation_code))) AS creation_code_hash,
        CONCAT('0x', TO_HEX(KECCAK(b.catalogue_code))) AS catalogue_code_hash,
        b.contract_name,
        b.contract_namespace,
        b.abi_id,
        b.mapping_time,
        b.mapping_block,
        CONCAT('0x', TO_HEX(b.mapping_tx_hash)) AS mapping_tx_hash,
        g.evidence_time,
        g.evidence_block,
        CONCAT('0x', TO_HEX(g.evidence_tx_hash)) AS evidence_tx_hash,
        g.trace_position,
        CAST(g.raw_stopped AS varchar) AS raw_stopped
    FROM base b
    JOIN getter_candidates g
      ON g.contract_address = b.clipper_contract
     AND g.getter_rank = 1
)
SELECT ilk, contract_address, record_type, deployment_time, deployment_block,
       deployment_tx_hash, deployer, creation_code_hash, catalogue_code_hash,
       contract_name, contract_namespace, abi_id, mapping_time, mapping_block,
       mapping_tx_hash, evidence_time, evidence_block, evidence_tx_hash,
       trace_position, raw_stopped
FROM deployment_rows
UNION ALL
SELECT ilk, contract_address, record_type, deployment_time, deployment_block,
       deployment_tx_hash, deployer, creation_code_hash, catalogue_code_hash,
       contract_name, contract_namespace, abi_id, mapping_time, mapping_block,
       mapping_tx_hash, evidence_time, evidence_block, evidence_tx_hash,
       trace_position, raw_stopped
FROM call_rows
UNION ALL
SELECT ilk, contract_address, record_type, deployment_time, deployment_block,
       deployment_tx_hash, deployer, creation_code_hash, catalogue_code_hash,
       contract_name, contract_namespace, abi_id, mapping_time, mapping_block,
       mapping_tx_hash, evidence_time, evidence_block, evidence_tx_hash,
       trace_position, raw_stopped
FROM getter_rows
ORDER BY ilk, record_type, evidence_time, evidence_block, trace_position
