-- Phase 1D diagnostic: reconstruct the ETH-A realised Vat debt ceiling.
-- The principal window is exactly three months. The pre-window branch supplies
-- the state required for local carry-forward at 2021-06-01 00:00:00 UTC.
WITH
settings AS (
    SELECT
        TIMESTAMP '2021-06-01 00:00:00' AS window_start,
        TIMESTAMP '2021-09-01 00:00:00' AS window_end,
        0x4554482d41000000000000000000000000000000000000000000000000000000 AS ilk_raw,
        0x6c696e6500000000000000000000000000000000000000000000000000000000 AS what_raw
),
pre_window_ranked AS (
    SELECT
        f.contract_address,
        f.call_tx_hash,
        f.call_block_time,
        f.call_block_number,
        f.call_tx_index,
        ARRAY_JOIN(
            TRANSFORM(f.call_trace_address, x -> CAST(x AS varchar)),
            '.'
        ) AS trace_order_key,
        f.data,
        ROW_NUMBER() OVER (
            ORDER BY
                f.call_block_number DESC,
                f.call_tx_index DESC,
                ARRAY_JOIN(
                    TRANSFORM(f.call_trace_address, x -> CAST(x AS varchar)),
                    '.'
                ) DESC
        ) AS recency_rank
    FROM maker_ethereum.vat_call_file f
    CROSS JOIN settings s
    WHERE f.call_success = true
      AND f.ilk = s.ilk_raw
      AND f.what = s.what_raw
      AND f.call_block_date >= DATE '2019-11-01'
      AND f.call_block_date < CAST(s.window_start AS date)
      AND f.call_block_time < s.window_start
),
selected_changes AS (
    SELECT
        true AS is_pre_window_state,
        p.contract_address,
        p.call_tx_hash,
        p.call_block_time,
        p.call_block_number,
        p.call_tx_index,
        p.trace_order_key,
        p.data
    FROM pre_window_ranked p
    WHERE p.recency_rank = 1

    UNION ALL

    SELECT
        false AS is_pre_window_state,
        f.contract_address,
        f.call_tx_hash,
        f.call_block_time,
        f.call_block_number,
        f.call_tx_index,
        ARRAY_JOIN(
            TRANSFORM(f.call_trace_address, x -> CAST(x AS varchar)),
            '.'
        ) AS trace_order_key,
        f.data
    FROM maker_ethereum.vat_call_file f
    CROSS JOIN settings s
    WHERE f.call_success = true
      AND f.ilk = s.ilk_raw
      AND f.what = s.what_raw
      AND f.call_block_date >= CAST(s.window_start AS date)
      AND f.call_block_date < CAST(s.window_end AS date)
      AND f.call_block_time >= s.window_start
      AND f.call_block_time < s.window_end
),
scaled_changes AS (
    SELECT
        is_pre_window_state,
        call_block_time AS effective_time_utc,
        call_block_number,
        call_tx_index,
        trace_order_key,
        CONCAT('0x', TO_HEX(contract_address)) AS contract_address,
        CONCAT('0x', TO_HEX(call_tx_hash)) AS transaction_hash,
        CAST(data AS varchar) AS raw_value_rad,
        CAST(data AS double) / 1e45 AS value_dai
    FROM selected_changes
),
chronological AS (
    SELECT
        *,
        LAG(value_dai) OVER (
            ORDER BY effective_time_utc, call_block_number, call_tx_index, trace_order_key
        ) AS previous_value_dai
    FROM scaled_changes
)
SELECT
    'ETH-A' AS ilk,
    'debt_ceiling' AS parameter,
    'line' AS parameter_key,
    CASE
        WHEN is_pre_window_state THEN 'pre_sample_initial_state'
        ELSE 'in_sample_change'
    END AS source_classification,
    effective_time_utc,
    call_block_number,
    call_tx_index,
    contract_address,
    transaction_hash,
    raw_value_rad,
    value_dai,
    previous_value_dai,
    value_dai - previous_value_dai AS change_dai
FROM chronological
ORDER BY effective_time_utc, call_block_number, call_tx_index, trace_order_key
