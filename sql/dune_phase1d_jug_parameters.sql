-- Phase 1D production: Jug duty by ilk and global base.
WITH
bounds AS (
    SELECT TIMESTAMP '2021-06-01 00:00:00' AS sample_start,
           TIMESTAMP '2024-07-01 00:00:00' AS sample_end
),
selected_ilks(ilk, ilk_raw) AS (
    VALUES
        ('ETH-A', 0x4554482d41000000000000000000000000000000000000000000000000000000),
        ('ETH-B', 0x4554482d42000000000000000000000000000000000000000000000000000000),
        ('ETH-C', 0x4554482d43000000000000000000000000000000000000000000000000000000),
        ('WBTC-A', 0x574254432d410000000000000000000000000000000000000000000000000000),
        ('WBTC-B', 0x574254432d420000000000000000000000000000000000000000000000000000),
        ('WBTC-C', 0x574254432d430000000000000000000000000000000000000000000000000000)
),
candidate_calls AS (
    SELECT 'Jug' AS module, i.ilk, 'stability_fee_duty' AS parameter,
           'duty' AS parameter_key, f.call_block_time AS effective_time_utc,
           f.call_block_number AS block_number, f.call_tx_index AS transaction_index,
           ARRAY_JOIN(TRANSFORM(f.call_trace_address, x -> CAST(x AS varchar)), '.') AS source_position,
           f.contract_address AS source_contract, f.call_tx_hash AS transaction_hash,
           f.data_uint256 AS raw_numeric
    FROM maker_ethereum.jug_call_file f
    JOIN selected_ilks i ON f.ilk = i.ilk_raw
    CROSS JOIN bounds b
    WHERE f.call_success = true
      AND f.what = 0x6475747900000000000000000000000000000000000000000000000000000000
      AND f.call_block_date >= DATE '2019-11-01'
      AND f.call_block_date < CAST(b.sample_end AS date)
      AND f.call_block_time < b.sample_end

    UNION ALL

    SELECT 'Jug', 'GLOBAL', 'stability_fee_base', 'base',
           f.call_block_time, f.call_block_number, f.call_tx_index,
           ARRAY_JOIN(TRANSFORM(f.call_trace_address, x -> CAST(x AS varchar)), '.'),
           f.contract_address, f.call_tx_hash, f.data_uint256
    FROM maker_ethereum.jug_call_file f CROSS JOIN bounds b
    WHERE f.call_success = true
      AND f.what = 0x6261736500000000000000000000000000000000000000000000000000000000
      AND f.call_block_date >= DATE '2019-11-01'
      AND f.call_block_date < CAST(b.sample_end AS date)
      AND f.call_block_time < b.sample_end
),
ranked AS (
    SELECT c.*,
        ROW_NUMBER() OVER (
            PARTITION BY ilk, parameter, (effective_time_utc < b.sample_start)
            ORDER BY effective_time_utc DESC, block_number DESC,
                     transaction_index DESC, source_position DESC
        ) AS period_rank,
        b.sample_start
    FROM candidate_calls c CROSS JOIN bounds b
),
selected AS (
    SELECT module, ilk, parameter, parameter_key, effective_time_utc,
           block_number, transaction_index, source_position, source_contract,
           transaction_hash, raw_numeric, sample_start
    FROM ranked
    WHERE effective_time_utc >= sample_start OR period_rank = 1
)
SELECT module, ilk, parameter, parameter_key,
    CASE WHEN effective_time_utc < sample_start
         THEN 'pre_sample_initial_state' ELSE 'in_sample_change' END AS source_classification,
    effective_time_utc, block_number, transaction_index, source_position,
    CONCAT('0x', TO_HEX(source_contract)) AS source_contract,
    CONCAT('0x', TO_HEX(transaction_hash)) AS transaction_hash,
    CAST(raw_numeric AS varchar) AS raw_value,
    CAST(raw_numeric AS double) / 1e27 AS converted_value,
    'RAY_factor' AS converted_unit,
    CAST(NULL AS varchar) AS auxiliary_raw_value
FROM selected
ORDER BY effective_time_utc, block_number, transaction_index, source_position
