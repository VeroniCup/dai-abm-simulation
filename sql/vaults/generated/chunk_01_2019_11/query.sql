-- Phase 1E monthly canonical Vat mutations.
-- Only the two bounded timestamps below vary between executions.
WITH selected_ilks(ilk_raw, ilk) AS (
    VALUES
        (0x4554482d41000000000000000000000000000000000000000000000000000000, 'ETH-A'),
        (0x4554482d42000000000000000000000000000000000000000000000000000000, 'ETH-B'),
        (0x4554482d43000000000000000000000000000000000000000000000000000000, 'ETH-C'),
        (0x574254432d410000000000000000000000000000000000000000000000000000, 'WBTC-A'),
        (0x574254432d420000000000000000000000000000000000000000000000000000, 'WBTC-B'),
        (0x574254432d430000000000000000000000000000000000000000000000000000, 'WBTC-C')
),
transactions AS (
    SELECT hash, block_number, index AS transaction_index
    FROM ethereum.transactions
    WHERE block_date >= DATE '2019-11-01'
      AND block_date < DATE '2019-12-01'
      AND block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND block_time < TIMESTAMP '2019-12-01 00:00:00 UTC'
),
mutations AS (
    SELECT
        f.call_block_time AS block_time_utc,
        f.call_block_number AS block_number,
        f.call_tx_hash AS transaction_hash_raw,
        ARRAY_JOIN(TRANSFORM(f.call_trace_address, x -> CAST(x AS varchar)), '.') AS trace_position,
        'frob' AS call_type,
        i.ilk,
        f.u AS urn_raw,
        CAST(NULL AS varbinary) AS source_urn_raw,
        CAST(NULL AS varbinary) AS destination_urn_raw,
        f.dink AS dink_raw,
        f.dart AS dart_raw,
        f.call_success,
        f.contract_address AS source_contract_raw,
        'maker_ethereum.vat_call_frob' AS source_table
    FROM maker_ethereum.vat_call_frob f
    INNER JOIN selected_ilks i ON i.ilk_raw = f.i
    WHERE f.call_block_date >= DATE '2019-11-01'
      AND f.call_block_date < DATE '2019-12-01'
      AND f.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND f.call_block_time < TIMESTAMP '2019-12-01 00:00:00 UTC'
      AND f.call_success = true

    UNION ALL

    SELECT
        f.call_block_time,
        f.call_block_number,
        f.call_tx_hash,
        ARRAY_JOIN(TRANSFORM(f.call_trace_address, x -> CAST(x AS varchar)), '.'),
        'fork',
        i.ilk,
        CAST(NULL AS varbinary),
        f.src,
        f.dst,
        f.dink,
        f.dart,
        f.call_success,
        f.contract_address,
        'maker_ethereum.vat_call_fork'
    FROM maker_ethereum.vat_call_fork f
    INNER JOIN selected_ilks i ON i.ilk_raw = f.ilk
    WHERE f.call_block_date >= DATE '2019-11-01'
      AND f.call_block_date < DATE '2019-12-01'
      AND f.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND f.call_block_time < TIMESTAMP '2019-12-01 00:00:00 UTC'
      AND f.call_success = true

    UNION ALL

    SELECT
        g.call_block_time,
        g.call_block_number,
        g.call_tx_hash,
        ARRAY_JOIN(TRANSFORM(g.call_trace_address, x -> CAST(x AS varchar)), '.'),
        'grab',
        i.ilk,
        g.u,
        CAST(NULL AS varbinary),
        CAST(NULL AS varbinary),
        g.dink,
        g.dart,
        g.call_success,
        g.contract_address,
        'maker_ethereum.vat_call_grab'
    FROM maker_ethereum.vat_call_grab g
    INNER JOIN selected_ilks i ON i.ilk_raw = g.i
    WHERE g.call_block_date >= DATE '2019-11-01'
      AND g.call_block_date < DATE '2019-12-01'
      AND g.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND g.call_block_time < TIMESTAMP '2019-12-01 00:00:00 UTC'
      AND g.call_success = true
)
SELECT
    m.block_time_utc,
    m.block_number,
    CONCAT('0x', TO_HEX(m.transaction_hash_raw)) AS transaction_hash,
    t.transaction_index,
    m.trace_position,
    m.call_type,
    m.ilk,
    CASE WHEN m.urn_raw IS NULL THEN NULL ELSE CONCAT('0x', TO_HEX(m.urn_raw)) END AS urn,
    CASE WHEN m.source_urn_raw IS NULL THEN NULL ELSE CONCAT('0x', TO_HEX(m.source_urn_raw)) END AS source_urn,
    CASE WHEN m.destination_urn_raw IS NULL THEN NULL ELSE CONCAT('0x', TO_HEX(m.destination_urn_raw)) END AS destination_urn,
    CAST(m.dink_raw AS varchar) AS dink_raw,
    CAST(m.dart_raw AS varchar) AS dart_raw,
    m.call_success,
    CONCAT('0x', TO_HEX(m.source_contract_raw)) AS source_contract,
    m.source_table
FROM mutations m
INNER JOIN transactions t
    ON t.hash = m.transaction_hash_raw
   AND t.block_number = m.block_number
