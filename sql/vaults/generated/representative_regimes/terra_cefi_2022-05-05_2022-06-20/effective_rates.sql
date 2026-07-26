-- Phase 1E-B Method B: bounded accumulated-rate changes only.
WITH
selected_ilks(ilk_raw, ilk) AS (
    VALUES
        (0x4554482d41000000000000000000000000000000000000000000000000000000, 'ETH-A'),
        (0x4554482d42000000000000000000000000000000000000000000000000000000, 'ETH-B'),
        (0x4554482d43000000000000000000000000000000000000000000000000000000, 'ETH-C'),
        (0x574254432d410000000000000000000000000000000000000000000000000000, 'WBTC-A'),
        (0x574254432d420000000000000000000000000000000000000000000000000000, 'WBTC-B'),
        (0x574254432d430000000000000000000000000000000000000000000000000000, 'WBTC-C')
),
window_drips AS (
    SELECT
        d.call_block_time AS effective_time_utc,
        d.call_block_number AS block_number,
        d.call_tx_hash AS transaction_hash_raw,
        d.call_trace_address AS trace_address_raw,
        i.ilk,
        'drip' AS rate_record_type,
        CAST(d.output_rate AS varchar) AS raw_rate_ray,
        CAST(NULL AS varchar) AS raw_rate_delta,
        d.call_success,
        d.contract_address AS source_contract_raw,
        'maker_ethereum.jug_call_drip' AS source_table
    FROM maker_ethereum.jug_call_drip d
    INNER JOIN selected_ilks i ON i.ilk_raw = d.ilk
    WHERE d.call_block_date >= DATE '2022-05-05'
      AND d.call_block_date < DATE '2022-06-20'
      AND d.call_block_time >= TIMESTAMP '2022-05-05 00:00:00 UTC'
      AND d.call_block_time < TIMESTAMP '2022-06-20 00:00:00 UTC'
      AND d.contract_address = 0x19c0976f590d67707e62397c87829d896dc0f1f1
      AND d.call_success = true
),
window_folds AS (
    SELECT
        f.call_block_time AS effective_time_utc,
        f.call_block_number AS block_number,
        f.call_tx_hash AS transaction_hash_raw,
        f.call_trace_address AS trace_address_raw,
        i.ilk,
        'fold' AS rate_record_type,
        CAST(NULL AS varchar) AS raw_rate_ray,
        CAST(f.rate AS varchar) AS raw_rate_delta,
        f.call_success,
        f.contract_address AS source_contract_raw,
        'maker_ethereum.vat_call_fold' AS source_table
    FROM maker_ethereum.vat_call_fold f
    INNER JOIN selected_ilks i ON i.ilk_raw = f.i
    WHERE f.call_block_date >= DATE '2022-05-05'
      AND f.call_block_date < DATE '2022-06-20'
      AND f.call_block_time >= TIMESTAMP '2022-05-05 00:00:00 UTC'
      AND f.call_block_time < TIMESTAMP '2022-06-20 00:00:00 UTC'
      AND f.contract_address = 0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b
      AND f.call_success = true
),
rate_records AS (
    SELECT effective_time_utc, block_number, transaction_hash_raw,
           trace_address_raw, ilk, rate_record_type, raw_rate_ray,
           raw_rate_delta, call_success, source_contract_raw, source_table
    FROM window_drips
    UNION ALL
    SELECT effective_time_utc, block_number, transaction_hash_raw,
           trace_address_raw, ilk, rate_record_type, raw_rate_ray,
           raw_rate_delta, call_success, source_contract_raw, source_table
    FROM window_folds
),
transactions AS (
    SELECT hash, block_number, index AS transaction_index
    FROM ethereum.transactions
    WHERE block_date >= DATE '2022-05-05'
      AND block_date < DATE '2022-06-20'
      AND block_time >= TIMESTAMP '2022-05-05 00:00:00 UTC'
      AND block_time < TIMESTAMP '2022-06-20 00:00:00 UTC'
)
SELECT
    r.effective_time_utc,
    r.block_number,
    CONCAT('0x', TO_HEX(r.transaction_hash_raw)) AS transaction_hash,
    t.transaction_index,
    ARRAY_JOIN(
        TRANSFORM(r.trace_address_raw, x -> CAST(x AS varchar)), '.'
    ) AS trace_position,
    r.ilk,
    r.rate_record_type,
    r.raw_rate_ray,
    r.raw_rate_delta,
    r.call_success,
    CONCAT('0x', TO_HEX(r.source_contract_raw)) AS source_contract,
    r.source_table
FROM rate_records r
INNER JOIN transactions t
    ON t.hash = r.transaction_hash_raw
   AND t.block_number = r.block_number
ORDER BY
    r.block_number,
    t.transaction_index,
    r.trace_address_raw,
    r.transaction_hash_raw,
    r.rate_record_type,
    r.ilk
