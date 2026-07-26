-- Phase 1E-B authoritative boundary states for USDC/SVB depeg.
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
mutations AS (
    SELECT f.call_block_time AS block_time_utc, i.ilk, f.u AS urn,
           f.dink AS dink_raw, f.dart AS dart_raw
    FROM maker_ethereum.vat_call_frob f
    JOIN selected_ilks i ON i.ilk_raw = f.i
    WHERE f.call_block_date >= DATE '2019-11-01'
      AND f.call_block_date < DATE '2023-03-20'
      AND f.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND f.call_block_time < TIMESTAMP '2023-03-20 00:00:00 UTC'
      AND f.contract_address = 0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b
      AND f.call_success = true
    UNION ALL
    SELECT f.call_block_time, i.ilk, f.src, -f.dink, -f.dart
    FROM maker_ethereum.vat_call_fork f
    JOIN selected_ilks i ON i.ilk_raw = f.ilk
    WHERE f.call_block_date >= DATE '2019-11-01'
      AND f.call_block_date < DATE '2023-03-20'
      AND f.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND f.call_block_time < TIMESTAMP '2023-03-20 00:00:00 UTC'
      AND f.contract_address = 0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b
      AND f.call_success = true
    UNION ALL
    SELECT f.call_block_time, i.ilk, f.dst, f.dink, f.dart
    FROM maker_ethereum.vat_call_fork f
    JOIN selected_ilks i ON i.ilk_raw = f.ilk
    WHERE f.call_block_date >= DATE '2019-11-01'
      AND f.call_block_date < DATE '2023-03-20'
      AND f.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND f.call_block_time < TIMESTAMP '2023-03-20 00:00:00 UTC'
      AND f.contract_address = 0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b
      AND f.call_success = true
    UNION ALL
    SELECT g.call_block_time, i.ilk, g.u, g.dink, g.dart
    FROM maker_ethereum.vat_call_grab g
    JOIN selected_ilks i ON i.ilk_raw = g.i
    WHERE g.call_block_date >= DATE '2019-11-01'
      AND g.call_block_date < DATE '2023-03-20'
      AND g.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND g.call_block_time < TIMESTAMP '2023-03-20 00:00:00 UTC'
      AND g.contract_address = 0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b
      AND g.call_success = true
),
balances AS (
    SELECT ilk, urn,
           SUM(CASE WHEN block_time_utc < TIMESTAMP '2023-03-06 00:00:00 UTC'
                    THEN dink_raw ELSE CAST(0 AS int256) END) AS opening_ink_raw,
           SUM(CASE WHEN block_time_utc < TIMESTAMP '2023-03-06 00:00:00 UTC'
                    THEN dart_raw ELSE CAST(0 AS int256) END) AS opening_art_raw,
           SUM(dink_raw) AS end_ink_raw,
           SUM(dart_raw) AS end_art_raw,
           COUNT_IF(block_time_utc < TIMESTAMP '2023-03-06 00:00:00 UTC')
               AS pre_window_mutation_count,
           COUNT_IF(block_time_utc >= TIMESTAMP '2023-03-06 00:00:00 UTC')
               AS window_mutation_count,
           MAX(CASE WHEN block_time_utc < TIMESTAMP '2023-03-06 00:00:00 UTC'
                    THEN block_time_utc END) AS last_pre_window_mutation_time_utc,
           MAX(CASE WHEN block_time_utc >= TIMESTAMP '2023-03-06 00:00:00 UTC'
                    THEN block_time_utc END) AS last_window_mutation_time_utc
    FROM mutations
    GROUP BY ilk, urn
),
rate_observations AS (
    SELECT d.call_block_time AS effective_time_utc, i.ilk, d.output_rate,
           d.call_block_number, d.call_trace_address, d.call_tx_hash
    FROM maker_ethereum.jug_call_drip d
    JOIN selected_ilks i ON i.ilk_raw = d.ilk
    WHERE d.call_block_date >= DATE '2019-11-01'
      AND d.call_block_date < DATE '2023-03-20'
      AND d.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND d.call_block_time < TIMESTAMP '2023-03-20 00:00:00 UTC'
      AND d.contract_address = 0x19c0976f590d67707e62397c87829d896dc0f1f1
      AND d.call_success = true
),
opening_rates AS (
    SELECT ilk, output_rate, effective_time_utc
    FROM (
        SELECT ilk, output_rate, effective_time_utc,
               ROW_NUMBER() OVER (
            PARTITION BY ilk
            ORDER BY call_block_number DESC, call_trace_address DESC,
                     call_tx_hash DESC
        ) AS rank
        FROM rate_observations
        WHERE effective_time_utc < TIMESTAMP '2023-03-06 00:00:00 UTC'
    )
    WHERE rank = 1
),
end_rates AS (
    SELECT ilk, output_rate, effective_time_utc
    FROM (
        SELECT ilk, output_rate, effective_time_utc,
               ROW_NUMBER() OVER (
            PARTITION BY ilk
            ORDER BY call_block_number DESC, call_trace_address DESC,
                     call_tx_hash DESC
        ) AS rank
        FROM rate_observations
    )
    WHERE rank = 1
)
SELECT
    b.ilk,
    CONCAT('0x', TO_HEX(b.urn)) AS urn,
    CAST(b.opening_ink_raw AS varchar) AS opening_ink_raw,
    CAST(b.opening_art_raw AS varchar) AS opening_art_raw,
    CAST(b.end_ink_raw AS varchar) AS end_ink_raw,
    CAST(b.end_art_raw AS varchar) AS end_art_raw,
    b.pre_window_mutation_count,
    b.window_mutation_count,
    b.last_pre_window_mutation_time_utc,
    b.last_window_mutation_time_utc,
    CAST(o.output_rate AS varchar) AS opening_rate_raw_ray,
    o.effective_time_utc AS opening_rate_effective_time_utc,
    CAST(e.output_rate AS varchar) AS end_rate_raw_ray,
    e.effective_time_utc AS end_rate_effective_time_utc,
    '0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b' AS canonical_vat_contract
FROM balances b
LEFT JOIN opening_rates o ON o.ilk = b.ilk
LEFT JOIN end_rates e ON e.ilk = b.ilk
WHERE b.opening_ink_raw <> 0 OR b.opening_art_raw <> 0
   OR b.end_ink_raw <> 0 OR b.end_art_raw <> 0
   OR b.window_mutation_count > 0
ORDER BY b.ilk, b.urn
