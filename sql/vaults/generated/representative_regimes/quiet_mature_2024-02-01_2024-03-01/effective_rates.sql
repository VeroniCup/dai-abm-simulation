-- Phase 1E exact Jug.drip stored rates and Vat.fold reconciliation.
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
      AND block_date < DATE '2024-03-01'
      AND block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND block_time < TIMESTAMP '2024-03-01 00:00:00 UTC'
),
rates AS (
    SELECT
        d.call_block_time AS effective_time_utc,
        d.call_block_number AS block_number,
        d.call_tx_hash AS transaction_hash_raw,
        ARRAY_JOIN(TRANSFORM(d.call_trace_address, x -> CAST(x AS varchar)), '.') AS trace_position,
        i.ilk,
        'drip' AS rate_record_type,
        CAST(d.output_rate AS varchar) AS raw_rate_ray,
        CAST(NULL AS varchar) AS raw_rate_delta,
        d.call_success,
        d.contract_address AS source_contract_raw,
        'maker_ethereum.jug_call_drip' AS source_table
    FROM maker_ethereum.jug_call_drip d
    INNER JOIN selected_ilks i ON i.ilk_raw = d.ilk
    WHERE d.call_block_date >= DATE '2019-11-01'
      AND d.call_block_date < DATE '2024-03-01'
      AND d.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND d.call_block_time < TIMESTAMP '2024-03-01 00:00:00 UTC'
      AND d.call_success = true

    UNION ALL

    SELECT
        f.call_block_time,
        f.call_block_number,
        f.call_tx_hash,
        ARRAY_JOIN(TRANSFORM(f.call_trace_address, x -> CAST(x AS varchar)), '.'),
        i.ilk,
        'fold',
        CAST(NULL AS varchar),
        CAST(f.rate AS varchar),
        f.call_success,
        f.contract_address,
        'maker_ethereum.vat_call_fold'
    FROM maker_ethereum.vat_call_fold f
    INNER JOIN selected_ilks i ON i.ilk_raw = f.i
    WHERE f.call_block_date >= DATE '2019-11-01'
      AND f.call_block_date < DATE '2024-03-01'
      AND f.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND f.call_block_time < TIMESTAMP '2024-03-01 00:00:00 UTC'
      AND f.call_success = true
)
SELECT
    r.effective_time_utc,
    r.block_number,
    CONCAT('0x', TO_HEX(r.transaction_hash_raw)) AS transaction_hash,
    t.transaction_index,
    r.trace_position,
    r.ilk,
    r.rate_record_type,
    r.raw_rate_ray,
    r.raw_rate_delta,
    r.call_success,
    CONCAT('0x', TO_HEX(r.source_contract_raw)) AS source_contract,
    r.source_table
FROM rates r
INNER JOIN transactions t
    ON t.hash = r.transaction_hash_raw
   AND t.block_number = r.block_number

ORDER BY r.block_number, t.transaction_index, r.trace_position,
         r.transaction_hash_raw, r.rate_record_type, r.ilk
