-- Phase 1D production: Clipper settings for all effective six-ilk Clippers.
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
clipper_universe AS (
    SELECT DISTINCT i.ilk, d.clip AS clipper_contract
    FROM maker_ethereum.dog_call_file d
    JOIN selected_ilks i ON d.ilk = i.ilk_raw
    CROSS JOIN bounds b
    WHERE d.call_success = true
      AND d.what = 0x636c697000000000000000000000000000000000000000000000000000000000
      AND d.clip IS NOT NULL
      AND d.call_block_date >= DATE '2021-01-01'
      AND d.call_block_date < CAST(b.sample_end AS date)
      AND d.call_block_time < b.sample_end
),
candidate_calls AS (
    SELECT 'Clipper' AS module, u.ilk,
        CASE c.what
            WHEN 0x6275660000000000000000000000000000000000000000000000000000000000 THEN 'auction_price_buffer'
            WHEN 0x7461696c00000000000000000000000000000000000000000000000000000000 THEN 'auction_tail'
            WHEN 0x6375737000000000000000000000000000000000000000000000000000000000 THEN 'auction_cusp'
            WHEN 0x6368697000000000000000000000000000000000000000000000000000000000 THEN 'auction_keeper_fraction'
            WHEN 0x7469700000000000000000000000000000000000000000000000000000000000 THEN 'auction_keeper_fixed'
            WHEN 0x73746f7070656400000000000000000000000000000000000000000000000000 THEN 'auction_stopped'
        END AS parameter,
        CASE c.what
            WHEN 0x6275660000000000000000000000000000000000000000000000000000000000 THEN 'buf'
            WHEN 0x7461696c00000000000000000000000000000000000000000000000000000000 THEN 'tail'
            WHEN 0x6375737000000000000000000000000000000000000000000000000000000000 THEN 'cusp'
            WHEN 0x6368697000000000000000000000000000000000000000000000000000000000 THEN 'chip'
            WHEN 0x7469700000000000000000000000000000000000000000000000000000000000 THEN 'tip'
            WHEN 0x73746f7070656400000000000000000000000000000000000000000000000000 THEN 'stopped'
        END AS parameter_key,
        c.call_block_time AS effective_time_utc, c.call_block_number AS block_number,
        c.call_tx_index AS transaction_index,
        ARRAY_JOIN(TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.') AS source_position,
        c.contract_address AS source_contract, c.call_tx_hash AS transaction_hash,
        c.data_uint256 AS raw_numeric
    FROM maker_ethereum.clipper_call_file c
    JOIN clipper_universe u ON c.contract_address = u.clipper_contract
    CROSS JOIN bounds b
    WHERE c.call_success = true
      AND c.what IN (
          0x6275660000000000000000000000000000000000000000000000000000000000,
          0x7461696c00000000000000000000000000000000000000000000000000000000,
          0x6375737000000000000000000000000000000000000000000000000000000000,
          0x6368697000000000000000000000000000000000000000000000000000000000,
          0x7469700000000000000000000000000000000000000000000000000000000000,
          0x73746f7070656400000000000000000000000000000000000000000000000000
      )
      AND c.call_block_date >= DATE '2021-01-01'
      AND c.call_block_date < CAST(b.sample_end AS date)
      AND c.call_block_time < b.sample_end
),
ranked AS (
    SELECT c.*,
        ROW_NUMBER() OVER (
            PARTITION BY ilk, source_contract, parameter,
                         (effective_time_utc < b.sample_start)
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
    CASE
        WHEN parameter IN ('auction_price_buffer', 'auction_cusp') THEN CAST(raw_numeric AS double) / 1e27
        WHEN parameter = 'auction_keeper_fraction' THEN CAST(raw_numeric AS double) / 1e18
        WHEN parameter = 'auction_keeper_fixed' THEN CAST(raw_numeric AS double) / 1e45
        WHEN parameter IN ('auction_tail', 'auction_stopped') THEN CAST(raw_numeric AS double)
    END AS converted_value,
    CASE
        WHEN parameter IN ('auction_price_buffer', 'auction_cusp') THEN 'ratio'
        WHEN parameter = 'auction_keeper_fraction' THEN 'proportion'
        WHEN parameter = 'auction_keeper_fixed' THEN 'DAI'
        WHEN parameter = 'auction_tail' THEN 'seconds'
        ELSE 'integer'
    END AS converted_unit,
    CAST(NULL AS varchar) AS auxiliary_raw_value
FROM selected
ORDER BY effective_time_utc, block_number, transaction_index, source_position
