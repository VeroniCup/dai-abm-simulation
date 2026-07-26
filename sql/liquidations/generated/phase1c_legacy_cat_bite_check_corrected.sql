-- Phase 1C corrected bounded legacy Cat/Flipper gate.
-- No decoded Flipper Kick table is live. Cat Bite exposes flip and id, which
-- identify the destination Flipper and the auction created by the Bite.
WITH selected_ilks(ilk, ilk_raw) AS (
    VALUES
        ('ETH-A', 0x4554482d41000000000000000000000000000000000000000000000000000000),
        ('ETH-B', 0x4554482d42000000000000000000000000000000000000000000000000000000),
        ('ETH-C', 0x4554482d43000000000000000000000000000000000000000000000000000000),
        ('WBTC-A', 0x574254432d410000000000000000000000000000000000000000000000000000),
        ('WBTC-B', 0x574254432d420000000000000000000000000000000000000000000000000000),
        ('WBTC-C', 0x574254432d430000000000000000000000000000000000000000000000000000)
)
SELECT
    'cat_bite' AS event_type,
    i.ilk,
    DATE_TRUNC('month', b.evt_block_time) AS month_utc,
    CONCAT('0x', TO_HEX(b.contract_address)) AS cat_contract,
    CONCAT('0x', TO_HEX(b.flip)) AS flipper_contract,
    COUNT(*) AS activity_count,
    COUNT(DISTINCT b.evt_tx_hash) AS unique_transaction_count,
    COUNT(DISTINCT b.id) AS unique_auction_count,
    MIN(b.evt_block_time) AS minimum_block_time,
    MAX(b.evt_block_time) AS maximum_block_time
FROM maker_ethereum.cat_evt_bite b
JOIN selected_ilks i ON b.ilk = i.ilk_raw
WHERE b.evt_block_date >= DATE '2021-06-01'
  AND b.evt_block_date < DATE '2024-07-01'
  AND b.evt_block_time >= TIMESTAMP '2021-06-01 00:00:00'
  AND b.evt_block_time < TIMESTAMP '2024-07-01 00:00:00'
GROUP BY 1, 2, 3, 4, 5
