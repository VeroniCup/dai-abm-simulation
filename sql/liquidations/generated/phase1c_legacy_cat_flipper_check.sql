-- Phase 1C bounded legacy liquidation activity check.
SELECT source, contract_address, minimum_block_time, maximum_block_time, activity_count
FROM (
    SELECT
        'maker_ethereum.cat_evt_bite' AS source,
        CONCAT('0x', TO_HEX(contract_address)) AS contract_address,
        MIN(evt_block_time) AS minimum_block_time,
        MAX(evt_block_time) AS maximum_block_time,
        COUNT(*) AS activity_count
    FROM maker_ethereum.cat_evt_bite
    WHERE evt_block_date >= DATE '2021-06-01' AND evt_block_date < DATE '2024-07-01'
      AND evt_block_time >= TIMESTAMP '2021-06-01 00:00:00'
      AND evt_block_time < TIMESTAMP '2024-07-01 00:00:00'
    GROUP BY 1, 2
    UNION ALL
    SELECT
        'maker_ethereum.flipper_evt_kick',
        CONCAT('0x', TO_HEX(contract_address)),
        MIN(evt_block_time), MAX(evt_block_time), COUNT(*)
    FROM maker_ethereum.flipper_evt_kick
    WHERE evt_block_date >= DATE '2021-06-01' AND evt_block_date < DATE '2024-07-01'
      AND evt_block_time >= TIMESTAMP '2021-06-01 00:00:00'
      AND evt_block_time < TIMESTAMP '2024-07-01 00:00:00'
    GROUP BY 1, 2
) legacy
WHERE activity_count > 0
