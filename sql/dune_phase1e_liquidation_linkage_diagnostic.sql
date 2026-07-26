-- Phase 1E diagnostic 2: one known ETH-A Bark and its canonical Vat.grab.
-- The selected transaction contains several liquidations; the chosen urn is
-- isolated while transaction-level multiplicity is retained for diagnosis.
WITH bark_transaction AS (
    SELECT
        b.contract_address AS dog_contract,
        b.clip AS clipper_contract,
        b.id AS auction_id,
        b.ilk AS ilk_raw,
        b.urn,
        b.evt_tx_hash AS transaction_hash,
        b.evt_block_time AS block_time_utc,
        b.evt_block_number AS block_number,
        b.evt_index AS bark_event_index,
        b.ink AS bark_ink_raw,
        b.art AS bark_art_raw,
        b.due AS bark_due_raw
    FROM maker_ethereum.dog_evt_bark b
    WHERE b.evt_block_date = DATE '2022-06-13'
      AND b.evt_block_time >= TIMESTAMP '2022-06-13 00:00:00 UTC'
      AND b.evt_block_time < TIMESTAMP '2022-06-14 00:00:00 UTC'
      AND b.evt_tx_hash = 0x37cff1857347f2c8f2e574ae1f4f47748d990077b57f059b158a17a7a24e965d
      AND b.ilk = 0x4554482d41000000000000000000000000000000000000000000000000000000
),
grab_transaction AS (
    SELECT
        g.contract_address AS vat_contract,
        g.call_success AS grab_success,
        g.call_tx_hash AS transaction_hash,
        ARRAY_JOIN(
            TRANSFORM(g.call_trace_address, x -> CAST(x AS varchar)),
            '.'
        ) AS grab_trace_position,
        g.i AS ilk_raw,
        g.u AS urn,
        g.dink AS grab_dink_raw,
        g.dart AS grab_dart_raw
    FROM maker_ethereum.vat_call_grab g
    WHERE g.call_block_date = DATE '2022-06-13'
      AND g.call_block_time >= TIMESTAMP '2022-06-13 00:00:00 UTC'
      AND g.call_block_time < TIMESTAMP '2022-06-14 00:00:00 UTC'
      AND g.contract_address = 0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b
      AND g.call_success = true
      AND g.call_tx_hash = 0x37cff1857347f2c8f2e574ae1f4f47748d990077b57f059b158a17a7a24e965d
      AND g.i = 0x4554482d41000000000000000000000000000000000000000000000000000000
),
bark_call AS (
    SELECT
        c.call_tx_hash AS transaction_hash,
        c.output_id AS auction_id,
        c.urn,
        c.kpr,
        c.call_success AS bark_call_success,
        ARRAY_JOIN(
            TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)),
            '.'
        ) AS bark_call_trace_position
    FROM maker_ethereum.dog_call_bark c
    WHERE c.call_block_date = DATE '2022-06-13'
      AND c.call_block_time >= TIMESTAMP '2022-06-13 00:00:00 UTC'
      AND c.call_block_time < TIMESTAMP '2022-06-14 00:00:00 UTC'
      AND c.call_success = true
      AND c.call_tx_hash = 0x37cff1857347f2c8f2e574ae1f4f47748d990077b57f059b158a17a7a24e965d
      AND c.ilk = 0x4554482d41000000000000000000000000000000000000000000000000000000
),
tx AS (
    SELECT
        t.hash AS transaction_hash,
        t.block_number,
        t.index AS transaction_index
    FROM ethereum.transactions t
    WHERE t.block_date = DATE '2022-06-13'
      AND t.block_time >= TIMESTAMP '2022-06-13 00:00:00 UTC'
      AND t.block_time < TIMESTAMP '2022-06-14 00:00:00 UTC'
      AND t.hash = 0x37cff1857347f2c8f2e574ae1f4f47748d990077b57f059b158a17a7a24e965d
),
transaction_counts AS (
    SELECT
        (SELECT COUNT(*) FROM bark_transaction) AS transaction_bark_count,
        (SELECT COUNT(*) FROM grab_transaction) AS transaction_grab_count
)
SELECT
    b.block_time_utc,
    b.block_number,
    CONCAT('0x', TO_HEX(b.transaction_hash)) AS transaction_hash,
    t.transaction_index,
    b.bark_event_index,
    c.bark_call_trace_position,
    g.grab_trace_position,
    'ETH-A' AS ilk,
    CONCAT('0x', TO_HEX(b.urn)) AS urn,
    CONCAT('0x', TO_HEX(c.kpr)) AS bark_keeper,
    CAST(b.auction_id AS varchar) AS auction_id,
    CONCAT('0x', TO_HEX(b.dog_contract)) AS dog_contract,
    CONCAT('0x', TO_HEX(g.vat_contract)) AS vat_contract,
    CONCAT('0x', TO_HEX(b.clipper_contract)) AS clipper_contract,
    c.bark_call_success,
    g.grab_success,
    CAST(b.bark_ink_raw AS varchar) AS bark_ink_raw,
    CAST(b.bark_art_raw AS varchar) AS bark_art_raw,
    CAST(b.bark_due_raw AS varchar) AS bark_due_raw,
    CAST(g.grab_dink_raw AS varchar) AS grab_dink_raw,
    CAST(g.grab_dart_raw AS varchar) AS grab_dart_raw,
    CAST(b.bark_ink_raw AS double) / 1e18 AS bark_collateral_wad,
    CAST(b.bark_art_raw AS double) / 1e18 AS bark_normalised_debt_wad,
    CAST(b.bark_due_raw AS double) / 1e45 AS bark_due_dai,
    CAST(g.grab_dink_raw AS double) / 1e18 AS grab_collateral_delta_wad,
    CAST(g.grab_dart_raw AS double) / 1e18 AS grab_normalised_debt_delta_wad,
    g.grab_dink_raw = -CAST(b.bark_ink_raw AS int256) AS collateral_reconciles,
    g.grab_dart_raw = -CAST(b.bark_art_raw AS int256) AS normalised_debt_reconciles,
    counts.transaction_bark_count,
    counts.transaction_grab_count,
    COUNT(*) OVER (PARTITION BY b.transaction_hash, b.urn) AS urn_link_count
FROM bark_transaction b
INNER JOIN grab_transaction g
    ON g.transaction_hash = b.transaction_hash
   AND g.ilk_raw = b.ilk_raw
   AND g.urn = b.urn
INNER JOIN bark_call c
    ON c.transaction_hash = b.transaction_hash
   AND c.auction_id = b.auction_id
   AND c.urn = b.urn
INNER JOIN tx t
    ON t.transaction_hash = b.transaction_hash
   AND t.block_number = b.block_number
CROSS JOIN transaction_counts counts
WHERE b.urn = 0x976db3678daf80add81a38f68f3ce2df5cc70187
ORDER BY b.block_number, t.transaction_index, b.bark_event_index,
         g.grab_trace_position, b.transaction_hash
