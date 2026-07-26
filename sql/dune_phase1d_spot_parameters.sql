-- Phase 1D production: Spot settings plus daily last effective spot observation.
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
setting_candidates AS (
    SELECT
        'Spot' AS module, i.ilk,
        CASE f.what
            WHEN 0x6d61740000000000000000000000000000000000000000000000000000000000 THEN 'liquidation_ratio'
            WHEN 0x7069700000000000000000000000000000000000000000000000000000000000 THEN 'oracle_adapter'
        END AS parameter,
        CASE f.what
            WHEN 0x6d61740000000000000000000000000000000000000000000000000000000000 THEN 'mat'
            WHEN 0x7069700000000000000000000000000000000000000000000000000000000000 THEN 'pip'
        END AS parameter_key,
        f.call_block_time AS effective_time_utc, f.call_block_number AS block_number,
        f.call_tx_index AS transaction_index,
        ARRAY_JOIN(TRANSFORM(f.call_trace_address, x -> CAST(x AS varchar)), '.') AS source_position,
        f.contract_address AS source_contract, f.call_tx_hash AS transaction_hash,
        f.data AS raw_numeric, f.pip_ AS raw_address, CAST(NULL AS varbinary) AS auxiliary_raw
    FROM maker_ethereum.spot_call_file f
    JOIN selected_ilks i ON f.ilk = i.ilk_raw
    CROSS JOIN bounds b
    WHERE f.call_success = true
      AND f.what IN (
          0x6d61740000000000000000000000000000000000000000000000000000000000,
          0x7069700000000000000000000000000000000000000000000000000000000000
      )
      AND f.call_block_date >= DATE '2019-11-01'
      AND f.call_block_date < CAST(b.sample_end AS date)
      AND f.call_block_time < b.sample_end
),
ranked_settings AS (
    SELECT s.*,
        ROW_NUMBER() OVER (
            PARTITION BY ilk, parameter, (effective_time_utc < b.sample_start)
            ORDER BY effective_time_utc DESC, block_number DESC,
                     transaction_index DESC, source_position DESC
        ) AS period_rank,
        b.sample_start
    FROM setting_candidates s CROSS JOIN bounds b
),
selected_settings AS (
    SELECT module, ilk, parameter, parameter_key, effective_time_utc,
           block_number, transaction_index, source_position, source_contract,
           transaction_hash, raw_numeric, raw_address, auxiliary_raw, sample_start
    FROM ranked_settings
    WHERE effective_time_utc >= sample_start OR period_rank = 1
),
poke_candidates AS (
    SELECT
        'Spot' AS module, i.ilk, 'effective_liquidation_spot' AS parameter,
        'poke' AS parameter_key, p.evt_block_time AS effective_time_utc,
        p.evt_block_number AS block_number, p.evt_tx_index AS transaction_index,
        CAST(p.evt_index AS varchar) AS source_position,
        p.contract_address AS source_contract, p.evt_tx_hash AS transaction_hash,
        p.spot AS raw_numeric, CAST(NULL AS varbinary) AS raw_address,
        p.val AS auxiliary_raw,
        ROW_NUMBER() OVER (
            PARTITION BY i.ilk,
                CASE WHEN p.evt_block_time < b.sample_start
                     THEN DATE '1970-01-01' ELSE p.evt_block_date END
            ORDER BY p.evt_block_time DESC, p.evt_block_number DESC,
                     p.evt_tx_index DESC, p.evt_index DESC
        ) AS observation_rank,
        b.sample_start
    FROM maker_ethereum.spot_evt_poke p
    JOIN selected_ilks i ON p.ilk = i.ilk_raw
    CROSS JOIN bounds b
    WHERE p.evt_block_date >= DATE '2019-11-01'
      AND p.evt_block_date < CAST(b.sample_end AS date)
      AND p.evt_block_time < b.sample_end
),
selected_pokes AS (
    SELECT module, ilk, parameter, parameter_key, effective_time_utc,
           block_number, transaction_index, source_position, source_contract,
           transaction_hash, raw_numeric, raw_address, auxiliary_raw, sample_start
    FROM poke_candidates WHERE observation_rank = 1
),
combined AS (
    SELECT module, ilk, parameter, parameter_key, effective_time_utc,
           block_number, transaction_index, source_position, source_contract,
           transaction_hash, raw_numeric, raw_address, auxiliary_raw, sample_start
    FROM selected_settings
    UNION ALL
    SELECT module, ilk, parameter, parameter_key, effective_time_utc,
           block_number, transaction_index, source_position, source_contract,
           transaction_hash, raw_numeric, raw_address, auxiliary_raw, sample_start
    FROM selected_pokes
)
SELECT
    module, ilk, parameter, parameter_key,
    CASE WHEN effective_time_utc < sample_start
         THEN 'pre_sample_initial_state' ELSE 'in_sample_change' END AS source_classification,
    effective_time_utc, block_number, transaction_index, source_position,
    CONCAT('0x', TO_HEX(source_contract)) AS source_contract,
    CONCAT('0x', TO_HEX(transaction_hash)) AS transaction_hash,
    CASE WHEN raw_address IS NOT NULL THEN CONCAT('0x', TO_HEX(raw_address))
         ELSE CAST(raw_numeric AS varchar) END AS raw_value,
    CASE WHEN raw_numeric IS NOT NULL THEN CAST(raw_numeric AS double) / 1e27 END AS converted_value,
    CASE WHEN parameter = 'oracle_adapter' THEN 'address'
         WHEN parameter = 'liquidation_ratio' THEN 'ratio'
         ELSE 'DAI_per_collateral' END AS converted_unit,
    CASE WHEN auxiliary_raw IS NOT NULL THEN CONCAT('0x', TO_HEX(auxiliary_raw)) END AS auxiliary_raw_value
FROM combined
ORDER BY effective_time_utc, block_number, transaction_index, source_position
