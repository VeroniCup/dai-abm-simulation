-- Phase 1C production action/call extraction: 07_2021_12.
-- Dune performs bounded filtering, Bark anchoring and raw selection. All
-- reconciliation, ordering, scaling and aggregation are performed locally.
WITH
windows(initiation_window_label, principal_start, principal_end, followup_end) AS (
    VALUES
        (
            '07_2021_12',
            TIMESTAMP '2021-12-01 00:00:00',
            TIMESTAMP '2022-01-01 00:00:00',
            TIMESTAMP '2022-01-08 00:00:00'
        )
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
barks AS (
    SELECT
        w.initiation_window_label,
        w.principal_start,
        w.principal_end,
        w.followup_end,
        i.ilk,
        b.contract_address AS dog_contract,
        b.clip AS clipper_contract,
        b.id AS auction_id,
        b.urn,
        b.evt_tx_hash AS bark_tx_hash,
        b.evt_block_time AS bark_block_time,
        b.evt_block_number AS bark_block_number,
        b.evt_tx_index AS bark_transaction_index,
        b.evt_index AS bark_event_index,
        b.evt_tx_from AS bark_event_sender,
        b.ink,
        b.art,
        b.due
    FROM maker_ethereum.dog_evt_bark b
    JOIN selected_ilks i ON b.ilk = i.ilk_raw
    JOIN windows w
      ON b.evt_block_time >= w.principal_start
     AND b.evt_block_time < w.principal_end
     AND b.evt_block_date >= CAST(w.principal_start AS date)
     AND b.evt_block_date < CAST(w.principal_end AS date)
),
auction_universe AS (
    SELECT DISTINCT
        initiation_window_label,
        principal_start,
        principal_end,
        followup_end,
        ilk,
        dog_contract,
        clipper_contract,
        auction_id,
        urn,
        bark_tx_hash,
        bark_block_time,
        bark_block_number,
        bark_transaction_index,
        bark_event_index,
        bark_event_sender,
        ink,
        art,
        due
    FROM barks
),
raw_actions AS (
    SELECT
        a.initiation_window_label,
        true AS action_in_principal_window,
        true AS action_in_bounded_horizon,
        'maker_ethereum.dog_evt_bark' AS source_table,
        'bark_event' AS record_type,
        CONCAT('0x', TO_HEX(a.dog_contract)) AS dog_contract,
        CONCAT('0x', TO_HEX(a.clipper_contract)) AS clipper_contract,
        CAST(a.auction_id AS varchar) AS auction_id,
        a.ilk,
        CONCAT('0x', TO_HEX(a.urn)) AS urn,
        CONCAT('0x', TO_HEX(a.bark_tx_hash)) AS tx_hash,
        a.bark_block_time AS block_time,
        a.bark_block_number AS block_number,
        a.bark_transaction_index AS transaction_index,
        a.bark_event_index AS event_index,
        CAST(NULL AS varchar) AS call_trace_address,
        CAST(NULL AS boolean) AS call_success,
        CONCAT('0x', TO_HEX(a.bark_event_sender)) AS event_sender,
        CAST(NULL AS varchar) AS call_sender,
        CAST(NULL AS varchar) AS call_recipient,
        CAST(NULL AS varchar) AS usr,
        CAST(NULL AS varchar) AS who,
        CAST(NULL AS varchar) AS kpr,
        CAST(a.ink AS varchar) AS ink_raw,
        CAST(a.art AS varchar) AS art_raw,
        CAST(a.due AS varchar) AS due_raw,
        CAST(NULL AS varchar) AS top_raw,
        CAST(NULL AS varchar) AS tab_raw,
        CAST(NULL AS varchar) AS lot_raw,
        CAST(NULL AS varchar) AS coin_raw,
        CAST(NULL AS varchar) AS price_raw,
        CAST(NULL AS varchar) AS owe_raw,
        CAST(NULL AS varchar) AS remaining_tab_raw,
        CAST(NULL AS varchar) AS remaining_lot_raw,
        CAST(NULL AS varchar) AS max_raw,
        CAST(NULL AS varchar) AS amt_raw
    FROM auction_universe a

    UNION ALL

    SELECT
        a.initiation_window_label, true, true,
        'maker_ethereum.dog_call_bark', 'bark_call',
        CONCAT('0x', TO_HEX(c.contract_address)),
        CONCAT('0x', TO_HEX(a.clipper_contract)), CAST(a.auction_id AS varchar), a.ilk,
        CONCAT('0x', TO_HEX(c.urn)), CONCAT('0x', TO_HEX(c.call_tx_hash)),
        c.call_block_time, c.call_block_number, c.call_tx_index, CAST(NULL AS bigint),
        ARRAY_JOIN(TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.'),
        c.call_success, CAST(NULL AS varchar), CONCAT('0x', TO_HEX(c.call_tx_from)),
        CONCAT('0x', TO_HEX(c.call_tx_to)), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CONCAT('0x', TO_HEX(c.kpr)),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar)
    FROM maker_ethereum.dog_call_bark c
    JOIN auction_universe a
      ON c.contract_address = a.dog_contract
     AND c.output_id = a.auction_id
     AND c.call_tx_hash = a.bark_tx_hash
     AND c.call_block_time >= a.principal_start
     AND c.call_block_time < a.principal_end
     AND c.call_block_date >= CAST(a.principal_start AS date)
     AND c.call_block_date < CAST(a.principal_end AS date)

    UNION ALL

    SELECT
        a.initiation_window_label, true, true,
        'maker_ethereum.clipper_evt_kick', 'kick_event',
        CONCAT('0x', TO_HEX(a.dog_contract)), CONCAT('0x', TO_HEX(k.contract_address)),
        CAST(k.id AS varchar), a.ilk, CONCAT('0x', TO_HEX(a.urn)),
        CONCAT('0x', TO_HEX(k.evt_tx_hash)), k.evt_block_time, k.evt_block_number,
        k.evt_tx_index, k.evt_index, CAST(NULL AS varchar), CAST(NULL AS boolean),
        CONCAT('0x', TO_HEX(k.evt_tx_from)), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CONCAT('0x', TO_HEX(k.usr)), CAST(NULL AS varchar), CONCAT('0x', TO_HEX(k.kpr)),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(k.top AS varchar), CAST(k.tab AS varchar), CAST(k.lot AS varchar),
        CAST(k.coin AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar)
    FROM maker_ethereum.clipper_evt_kick k
    JOIN auction_universe a
      ON k.contract_address = a.clipper_contract
     AND k.id = a.auction_id
     AND k.evt_tx_hash = a.bark_tx_hash
     AND k.evt_block_time >= a.principal_start
     AND k.evt_block_time < a.principal_end
     AND k.evt_block_date >= CAST(a.principal_start AS date)
     AND k.evt_block_date < CAST(a.principal_end AS date)

    UNION ALL

    SELECT
        a.initiation_window_label, true, true,
        'maker_ethereum.clipper_call_kick', 'kick_call',
        CONCAT('0x', TO_HEX(a.dog_contract)), CONCAT('0x', TO_HEX(c.contract_address)),
        CAST(c.output_id AS varchar), a.ilk, CONCAT('0x', TO_HEX(c.usr)),
        CONCAT('0x', TO_HEX(c.call_tx_hash)), c.call_block_time, c.call_block_number,
        c.call_tx_index, CAST(NULL AS bigint),
        ARRAY_JOIN(TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.'),
        c.call_success, CAST(NULL AS varchar), CONCAT('0x', TO_HEX(c.call_tx_from)),
        CONCAT('0x', TO_HEX(c.call_tx_to)), CONCAT('0x', TO_HEX(c.usr)),
        CAST(NULL AS varchar), CONCAT('0x', TO_HEX(c.kpr)),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(c.tab AS varchar), CAST(c.lot AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar)
    FROM maker_ethereum.clipper_call_kick c
    JOIN auction_universe a
      ON c.contract_address = a.clipper_contract
     AND c.output_id = a.auction_id
     AND c.call_tx_hash = a.bark_tx_hash
     AND c.call_block_time >= a.principal_start
     AND c.call_block_time < a.principal_end
     AND c.call_block_date >= CAST(a.principal_start AS date)
     AND c.call_block_date < CAST(a.principal_end AS date)

    UNION ALL

    SELECT
        a.initiation_window_label,
        t.evt_block_time < a.principal_end,
        true,
        'maker_ethereum.clipper_evt_take', 'take_event',
        CONCAT('0x', TO_HEX(a.dog_contract)), CONCAT('0x', TO_HEX(t.contract_address)),
        CAST(t.id AS varchar), a.ilk, CONCAT('0x', TO_HEX(a.urn)),
        CONCAT('0x', TO_HEX(t.evt_tx_hash)), t.evt_block_time, t.evt_block_number,
        t.evt_tx_index, t.evt_index, CAST(NULL AS varchar), CAST(NULL AS boolean),
        CONCAT('0x', TO_HEX(t.evt_tx_from)), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CONCAT('0x', TO_HEX(t.usr)), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(t.price AS varchar), CAST(t.owe AS varchar),
        CAST(t.tab AS varchar), CAST(t.lot AS varchar), CAST(t.max AS varchar), CAST(NULL AS varchar)
    FROM maker_ethereum.clipper_evt_take t
    JOIN auction_universe a
      ON t.contract_address = a.clipper_contract
     AND t.id = a.auction_id
     AND t.evt_block_time >= a.bark_block_time
     AND t.evt_block_time < a.followup_end
     AND t.evt_block_date >= CAST(a.principal_start AS date)
     AND t.evt_block_date < CAST(a.followup_end AS date)

    UNION ALL

    SELECT
        a.initiation_window_label,
        c.call_block_time < a.principal_end,
        true,
        'maker_ethereum.clipper_call_take',
        IF(c.call_success, 'take_call_success', 'take_call_failed'),
        CONCAT('0x', TO_HEX(a.dog_contract)), CONCAT('0x', TO_HEX(c.contract_address)),
        CAST(c.id AS varchar), a.ilk, CONCAT('0x', TO_HEX(a.urn)),
        CONCAT('0x', TO_HEX(c.call_tx_hash)), c.call_block_time, c.call_block_number,
        c.call_tx_index, CAST(NULL AS bigint),
        ARRAY_JOIN(TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.'),
        c.call_success, CAST(NULL AS varchar), CONCAT('0x', TO_HEX(c.call_tx_from)),
        CONCAT('0x', TO_HEX(c.call_tx_to)), CAST(NULL AS varchar),
        CONCAT('0x', TO_HEX(c.who)), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(c.max AS varchar), CAST(c.amt AS varchar)
    FROM maker_ethereum.clipper_call_take c
    JOIN auction_universe a
      ON c.contract_address = a.clipper_contract
     AND c.id = a.auction_id
     AND c.call_block_time >= a.bark_block_time
     AND c.call_block_time < a.followup_end
     AND c.call_block_date >= CAST(a.principal_start AS date)
     AND c.call_block_date < CAST(a.followup_end AS date)

    UNION ALL

    SELECT
        a.initiation_window_label,
        r.evt_block_time < a.principal_end,
        true,
        'maker_ethereum.clipper_evt_redo', 'redo_event',
        CONCAT('0x', TO_HEX(a.dog_contract)), CONCAT('0x', TO_HEX(r.contract_address)),
        CAST(r.id AS varchar), a.ilk, CONCAT('0x', TO_HEX(a.urn)),
        CONCAT('0x', TO_HEX(r.evt_tx_hash)), r.evt_block_time, r.evt_block_number,
        r.evt_tx_index, r.evt_index, CAST(NULL AS varchar), CAST(NULL AS boolean),
        CONCAT('0x', TO_HEX(r.evt_tx_from)), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CONCAT('0x', TO_HEX(r.usr)), CAST(NULL AS varchar), CONCAT('0x', TO_HEX(r.kpr)),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(r.top AS varchar), CAST(r.tab AS varchar), CAST(r.lot AS varchar),
        CAST(r.coin AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(r.tab AS varchar), CAST(r.lot AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar)
    FROM maker_ethereum.clipper_evt_redo r
    JOIN auction_universe a
      ON r.contract_address = a.clipper_contract
     AND r.id = a.auction_id
     AND r.evt_block_time >= a.bark_block_time
     AND r.evt_block_time < a.followup_end
     AND r.evt_block_date >= CAST(a.principal_start AS date)
     AND r.evt_block_date < CAST(a.followup_end AS date)

    UNION ALL

    SELECT
        a.initiation_window_label,
        c.call_block_time < a.principal_end,
        true,
        'maker_ethereum.clipper_call_redo',
        IF(c.call_success, 'redo_call_success', 'redo_call_failed'),
        CONCAT('0x', TO_HEX(a.dog_contract)), CONCAT('0x', TO_HEX(c.contract_address)),
        CAST(c.id AS varchar), a.ilk, CONCAT('0x', TO_HEX(a.urn)),
        CONCAT('0x', TO_HEX(c.call_tx_hash)), c.call_block_time, c.call_block_number,
        c.call_tx_index, CAST(NULL AS bigint),
        ARRAY_JOIN(TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.'),
        c.call_success, CAST(NULL AS varchar), CONCAT('0x', TO_HEX(c.call_tx_from)),
        CONCAT('0x', TO_HEX(c.call_tx_to)), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CONCAT('0x', TO_HEX(c.kpr)),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar)
    FROM maker_ethereum.clipper_call_redo c
    JOIN auction_universe a
      ON c.contract_address = a.clipper_contract
     AND c.id = a.auction_id
     AND c.call_block_time >= a.bark_block_time
     AND c.call_block_time < a.followup_end
     AND c.call_block_date >= CAST(a.principal_start AS date)
     AND c.call_block_date < CAST(a.followup_end AS date)

    UNION ALL

    SELECT
        a.initiation_window_label,
        l.block_time < a.principal_end,
        true,
        'ethereum.logs', 'yank_event',
        CONCAT('0x', TO_HEX(a.dog_contract)), CONCAT('0x', TO_HEX(l.contract_address)),
        CAST(BYTEARRAY_TO_UINT256(l.data) AS varchar), a.ilk, CONCAT('0x', TO_HEX(a.urn)),
        CONCAT('0x', TO_HEX(l.tx_hash)), l.block_time, l.block_number, l.tx_index,
        l.index, CAST(NULL AS varchar), CAST(NULL AS boolean),
        CONCAT('0x', TO_HEX(l.tx_from)), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar)
    FROM ethereum.logs l
    JOIN auction_universe a
      ON l.contract_address = a.clipper_contract
     AND BYTEARRAY_TO_UINT256(l.data) = a.auction_id
     AND l.block_time >= a.bark_block_time
     AND l.block_time < a.followup_end
     AND l.block_date >= CAST(a.principal_start AS date)
     AND l.block_date < CAST(a.followup_end AS date)
    WHERE l.topic0 = 0x2c5d2826eb5903b8fc201cf48094b858f42f61c7eaac9aaf43ebed490138144e
)
SELECT
    initiation_window_label,
    action_in_principal_window,
    action_in_bounded_horizon,
    source_table,
    record_type,
    dog_contract,
    clipper_contract,
    auction_id,
    ilk,
    urn,
    tx_hash,
    block_time,
    block_number,
    transaction_index,
    event_index,
    call_trace_address,
    call_success,
    event_sender,
    call_sender,
    call_recipient,
    usr,
    who,
    kpr,
    ink_raw,
    art_raw,
    due_raw,
    top_raw,
    tab_raw,
    lot_raw,
    coin_raw,
    price_raw,
    owe_raw,
    remaining_tab_raw,
    remaining_lot_raw,
    max_raw,
    amt_raw
FROM raw_actions
