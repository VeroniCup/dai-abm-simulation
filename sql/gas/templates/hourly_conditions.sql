WITH
transaction_hours AS (
    SELECT
        date_trunc('hour', block_time) AS timestamp_utc,
        count(*) AS transaction_count,
        avg(CAST(gas_price AS double)) / 1e9
            AS mean_effective_gas_price_gwei,
        approx_percentile(
            CAST(gas_price AS double) / 1e9,
            ARRAY[0.50, 0.75, 0.90, 0.95, 0.99]
        ) AS effective_gas_price_quantiles_gwei,
        approx_percentile(
            CASE
                WHEN block_number >= 12965000
                    THEN CAST(priority_fee_per_gas AS double) / 1e9
            END,
            0.50
        ) AS median_priority_fee_gwei,
        CAST(count_if(success = false) AS double)
            / NULLIF(count_if(success IS NOT NULL), 0)
            AS failed_transaction_share,
        count_if(success IS NULL) AS null_success_count,
        CAST(sum(gas_used) AS decimal(38, 0))
            AS transaction_total_gas_used
    FROM ethereum.transactions
    WHERE block_date >= DATE '{{START_DATE}}'
      AND block_date < DATE '{{END_DATE}}'
      AND block_time >= TIMESTAMP '{{START_DATE}} 00:00:00'
      AND block_time < TIMESTAMP '{{END_DATE}} 00:00:00'
    GROUP BY 1
),
block_hours AS (
    SELECT
        date_trunc('hour', time) AS timestamp_utc,
        count(*) AS block_count,
        approx_percentile(
            CASE
                WHEN number >= 12965000
                    THEN CAST(base_fee_per_gas AS double) / 1e9
            END,
            0.50
        ) AS median_base_fee_gwei,
        approx_percentile(
            CASE
                WHEN number >= 12965000
                    THEN CAST(base_fee_per_gas AS double) / 1e9
            END,
            0.95
        ) AS p95_base_fee_gwei,
        sum(CAST(gas_used AS double))
            / NULLIF(sum(CAST(gas_limit AS double)), 0)
            AS block_utilisation,
        sum(CAST(gas_used AS double))
            / NULLIF(
                sum(
                    CASE
                        WHEN number >= 12965000
                            THEN CAST(gas_limit AS double) / 2.0
                        ELSE CAST(gas_limit AS double)
                    END
                ),
                0
            ) AS target_normalised_block_utilisation,
        CAST(sum(gas_used) AS decimal(38, 0))
            AS block_total_gas_used,
        CAST(count_if(number >= 12965000) AS double)
            / NULLIF(count(*), 0) AS eip1559_block_share
    FROM ethereum.blocks
    WHERE date >= DATE '{{START_DATE}}'
      AND date < DATE '{{END_DATE}}'
      AND time >= TIMESTAMP '{{START_DATE}} 00:00:00'
      AND time < TIMESTAMP '{{END_DATE}} 00:00:00'
    GROUP BY 1
)
SELECT
    t.timestamp_utc,
    t.transaction_count,
    b.block_count,
    t.effective_gas_price_quantiles_gwei[1]
        AS median_effective_gas_price_gwei,
    t.mean_effective_gas_price_gwei,
    t.effective_gas_price_quantiles_gwei[2]
        AS p75_effective_gas_price_gwei,
    t.effective_gas_price_quantiles_gwei[3]
        AS p90_effective_gas_price_gwei,
    t.effective_gas_price_quantiles_gwei[4]
        AS p95_effective_gas_price_gwei,
    t.effective_gas_price_quantiles_gwei[5]
        AS p99_effective_gas_price_gwei,
    b.median_base_fee_gwei,
    b.p95_base_fee_gwei,
    t.median_priority_fee_gwei,
    b.block_utilisation,
    b.target_normalised_block_utilisation,
    t.transaction_total_gas_used,
    b.block_total_gas_used,
    CAST(t.transaction_total_gas_used AS double)
        - CAST(b.block_total_gas_used AS double)
        AS gas_used_reconciliation_difference,
    t.failed_transaction_share,
    t.null_success_count,
    b.eip1559_block_share
FROM transaction_hours t
INNER JOIN block_hours b
    ON t.timestamp_utc = b.timestamp_utc
