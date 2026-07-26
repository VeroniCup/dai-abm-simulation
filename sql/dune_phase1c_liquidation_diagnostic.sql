-- Phase 1C bounded Maker Liquidations 2.0 diagnostic only.
-- Principal windows are half-open. Related auction actions are retained within
-- a seven-day pre/post context so that boundary truncation is visible.
WITH
windows(window_label, principal_start, principal_end, extended_start, extended_end) AS (
    VALUES
        (
            'ordinary_2023_02',
            TIMESTAMP '2023-02-01 00:00:00',
            TIMESTAMP '2023-02-03 00:00:00',
            TIMESTAMP '2023-01-25 00:00:00',
            TIMESTAMP '2023-02-10 00:00:00'
        ),
        (
            'nonzero_2022_06',
            TIMESTAMP '2022-06-13 00:00:00',
            TIMESTAMP '2022-06-15 00:00:00',
            TIMESTAMP '2022-06-06 00:00:00',
            TIMESTAMP '2022-06-22 00:00:00'
        )
),
ilk_filter(ilk, ilk_raw) AS (
    VALUES
        ('ETH-A', 0x4554482d41000000000000000000000000000000000000000000000000000000),
        ('ETH-B', 0x4554482d42000000000000000000000000000000000000000000000000000000),
        ('ETH-C', 0x4554482d43000000000000000000000000000000000000000000000000000000),
        ('WBTC-A', 0x574254432d410000000000000000000000000000000000000000000000000000),
        ('WBTC-B', 0x574254432d420000000000000000000000000000000000000000000000000000),
        ('WBTC-C', 0x574254432d430000000000000000000000000000000000000000000000000000)
),
clip_filter(clip) AS (
    VALUES
        (0xc67963a226eddd77b91ad8c421630a1b0adff270),
        (0x71eb894330e8a4b96b8d6056962e7f116f50e06f),
        (0xc2b12567523e3f3cbd9931492b91fe65b240bc47),
        (0x0227b54adbfaeec5f1ed1dfa11f54dcff9076e2c),
        (0xe30663c6f83a06edee6273d72274ae24f1084a22),
        (0x39f29773dcb94a32529d0612c6706c49622161d1)
),
bark_events_extended AS (
    SELECT
        w.window_label,
        w.principal_start,
        w.principal_end,
        w.extended_start,
        w.extended_end,
        f.ilk,
        b.contract_address AS dog_contract,
        b.clip AS clipper_contract,
        b.id AS auction_id,
        b.evt_tx_hash AS transaction_hash,
        b.evt_block_number AS block_number,
        b.evt_block_time AS block_timestamp,
        b.evt_tx_index AS transaction_index,
        b.evt_index AS event_index,
        b.urn,
        b.ink,
        b.art,
        b.due,
        b.evt_tx_from
    FROM maker_ethereum.dog_evt_bark b
    JOIN ilk_filter f ON b.ilk = f.ilk_raw
    JOIN windows w
      ON b.evt_block_time >= w.extended_start
     AND b.evt_block_time < w.extended_end
     AND b.evt_block_date >= CAST(w.extended_start AS date)
     AND b.evt_block_date < CAST(w.extended_end AS date)
),
kick_events_extended AS (
    SELECT
        w.window_label,
        k.contract_address AS clipper_contract,
        k.id AS auction_id,
        k.evt_tx_hash AS transaction_hash,
        k.evt_block_number AS block_number,
        k.evt_block_time AS block_timestamp,
        k.evt_tx_index AS transaction_index,
        k.evt_index AS event_index,
        k.top,
        k.tab,
        k.lot,
        k.usr,
        k.kpr,
        k.coin
    FROM maker_ethereum.clipper_evt_kick k
    JOIN clip_filter c ON k.contract_address = c.clip
    JOIN windows w
      ON k.evt_block_time >= w.extended_start
     AND k.evt_block_time < w.extended_end
     AND k.evt_block_date >= CAST(w.extended_start AS date)
     AND k.evt_block_date < CAST(w.extended_end AS date)
),
auction_context AS (
    SELECT
        b.*,
        k.top AS kick_top,
        k.tab AS kick_tab,
        k.lot AS kick_lot,
        k.usr AS kick_usr,
        k.kpr AS kick_keeper,
        k.coin AS kick_coin,
        k.event_index AS kick_event_index,
        COUNT(k.auction_id) OVER (
            PARTITION BY b.clipper_contract, b.auction_id, b.transaction_hash
        ) AS bark_kick_match_count
    FROM bark_events_extended b
    LEFT JOIN kick_events_extended k
      ON k.window_label = b.window_label
     AND k.clipper_contract = b.clipper_contract
     AND k.auction_id = b.auction_id
     AND k.transaction_hash = b.transaction_hash
),
take_events_extended AS (
    SELECT
        w.window_label,
        t.contract_address AS clipper_contract,
        t.id AS auction_id,
        t.evt_tx_hash AS transaction_hash,
        t.evt_block_number AS block_number,
        t.evt_block_time AS block_timestamp,
        t.evt_tx_index AS transaction_index,
        t.evt_index AS event_index,
        t.price,
        t.owe,
        t.tab,
        t.lot,
        t.usr,
        ROW_NUMBER() OVER (
            PARTITION BY t.contract_address, t.id, t.evt_tx_hash
            ORDER BY t.evt_index
        ) AS link_ordinal
    FROM maker_ethereum.clipper_evt_take t
    JOIN clip_filter c ON t.contract_address = c.clip
    JOIN windows w
      ON t.evt_block_time >= w.extended_start
     AND t.evt_block_time < w.extended_end
     AND t.evt_block_date >= CAST(w.extended_start AS date)
     AND t.evt_block_date < CAST(w.extended_end AS date)
),
take_calls_extended AS (
    SELECT
        w.window_label,
        c.contract_address AS clipper_contract,
        c.id AS auction_id,
        c.call_tx_hash AS transaction_hash,
        c.call_block_number AS block_number,
        c.call_block_time AS block_timestamp,
        c.call_tx_index AS transaction_index,
        ARRAY_JOIN(TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.') AS call_trace_address,
        c.call_tx_from AS call_sender,
        c.who,
        c.call_success,
        ROW_NUMBER() OVER (
            PARTITION BY c.contract_address, c.id, c.call_tx_hash, c.call_success
            ORDER BY c.call_trace_address, c.call_tx_index
        ) AS link_ordinal
    FROM maker_ethereum.clipper_call_take c
    JOIN clip_filter cf ON c.contract_address = cf.clip
    JOIN windows w
      ON c.call_block_time >= w.extended_start
     AND c.call_block_time < w.extended_end
     AND c.call_block_date >= CAST(w.extended_start AS date)
     AND c.call_block_date < CAST(w.extended_end AS date)
),
redo_events_extended AS (
    SELECT
        w.window_label,
        r.contract_address AS clipper_contract,
        r.id AS auction_id,
        r.evt_tx_hash AS transaction_hash,
        r.evt_block_number AS block_number,
        r.evt_block_time AS block_timestamp,
        r.evt_tx_index AS transaction_index,
        r.evt_index AS event_index,
        r.top,
        r.tab,
        r.lot,
        r.usr,
        r.kpr,
        r.coin,
        ROW_NUMBER() OVER (
            PARTITION BY r.contract_address, r.id, r.evt_tx_hash
            ORDER BY r.evt_index
        ) AS link_ordinal
    FROM maker_ethereum.clipper_evt_redo r
    JOIN clip_filter c ON r.contract_address = c.clip
    JOIN windows w
      ON r.evt_block_time >= w.extended_start
     AND r.evt_block_time < w.extended_end
     AND r.evt_block_date >= CAST(w.extended_start AS date)
     AND r.evt_block_date < CAST(w.extended_end AS date)
),
redo_calls_extended AS (
    SELECT
        w.window_label,
        c.contract_address AS clipper_contract,
        c.id AS auction_id,
        c.call_tx_hash AS transaction_hash,
        c.call_block_number AS block_number,
        c.call_block_time AS block_timestamp,
        c.call_tx_index AS transaction_index,
        ARRAY_JOIN(TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.') AS call_trace_address,
        c.call_tx_from AS call_sender,
        c.kpr,
        c.call_success,
        ROW_NUMBER() OVER (
            PARTITION BY c.contract_address, c.id, c.call_tx_hash, c.call_success
            ORDER BY c.call_trace_address, c.call_tx_index
        ) AS link_ordinal
    FROM maker_ethereum.clipper_call_redo c
    JOIN clip_filter cf ON c.contract_address = cf.clip
    JOIN windows w
      ON c.call_block_time >= w.extended_start
     AND c.call_block_time < w.extended_end
     AND c.call_block_date >= CAST(w.extended_start AS date)
     AND c.call_block_date < CAST(w.extended_end AS date)
),
yank_events_extended AS (
    SELECT
        w.window_label,
        l.contract_address AS clipper_contract,
        BYTEARRAY_TO_UINT256(l.data) AS auction_id,
        l.tx_hash AS transaction_hash,
        l.block_number,
        l.block_time AS block_timestamp,
        l.tx_index AS transaction_index,
        l.index AS event_index
    FROM ethereum.logs l
    JOIN clip_filter c ON l.contract_address = c.clip
    JOIN windows w
      ON l.block_time >= w.extended_start
     AND l.block_time < w.extended_end
     AND l.block_date >= CAST(w.extended_start AS date)
     AND l.block_date < CAST(w.extended_end AS date)
    WHERE l.topic0 = 0x2c5d2826eb5903b8fc201cf48094b858f42f61c7eaac9aaf43ebed490138144e
),
diagnostic_auction_keys AS (
    SELECT DISTINCT window_label, clipper_contract, auction_id
    FROM auction_context
    WHERE block_timestamp >= principal_start AND block_timestamp < principal_end
    UNION
    SELECT DISTINCT a.window_label, a.clipper_contract, a.auction_id
    FROM (
        SELECT window_label, clipper_contract, auction_id, block_timestamp FROM take_events_extended
        UNION ALL
        SELECT window_label, clipper_contract, auction_id, block_timestamp FROM redo_events_extended
        UNION ALL
        SELECT window_label, clipper_contract, auction_id, block_timestamp FROM yank_events_extended
    ) a
    JOIN windows w ON a.window_label = w.window_label
    WHERE a.block_timestamp >= w.principal_start AND a.block_timestamp < w.principal_end
),
selected_context AS (
    SELECT a.*
    FROM auction_context a
    JOIN diagnostic_auction_keys d
      ON d.window_label = a.window_label
     AND d.clipper_contract = a.clipper_contract
     AND d.auction_id = a.auction_id
),
bark_calls AS (
    SELECT
        w.window_label,
        f.ilk,
        c.contract_address AS dog_contract,
        a.clipper_contract,
        c.output_id AS auction_id,
        c.call_tx_hash AS transaction_hash,
        c.call_block_number AS block_number,
        c.call_block_time AS block_timestamp,
        c.call_tx_index AS transaction_index,
        ARRAY_JOIN(TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.') AS call_trace_address,
        c.urn,
        c.kpr,
        c.call_tx_from AS call_sender,
        c.call_success
    FROM maker_ethereum.dog_call_bark c
    JOIN ilk_filter f ON c.ilk = f.ilk_raw
    JOIN windows w
      ON c.call_block_time >= w.principal_start
     AND c.call_block_time < w.principal_end
     AND c.call_block_date >= CAST(w.principal_start AS date)
     AND c.call_block_date < CAST(w.principal_end AS date)
    LEFT JOIN selected_context a
      ON a.window_label = w.window_label
     AND a.transaction_hash = c.call_tx_hash
     AND a.auction_id = c.output_id
),
kick_calls AS (
    SELECT
        w.window_label AS initiation_window_label,
        a.ilk,
        a.dog_contract,
        c.contract_address AS clipper_contract,
        c.output_id AS auction_id,
        c.call_tx_hash AS transaction_hash,
        c.call_block_number AS block_number,
        c.call_block_time AS block_timestamp,
        c.call_tx_index AS transaction_index,
        ARRAY_JOIN(TRANSFORM(c.call_trace_address, x -> CAST(x AS varchar)), '.') AS call_trace_address,
        c.usr,
        c.kpr,
        c.call_tx_from AS call_sender,
        c.tab,
        c.lot,
        c.call_success
    FROM maker_ethereum.clipper_call_kick c
    JOIN clip_filter cf ON c.contract_address = cf.clip
    JOIN windows w
      ON c.call_block_time >= w.extended_start
     AND c.call_block_time < w.extended_end
     AND c.call_block_date >= CAST(w.extended_start AS date)
     AND c.call_block_date < CAST(w.extended_end AS date)
    JOIN selected_context a
      ON a.window_label = w.window_label
     AND a.clipper_contract = c.contract_address
     AND a.auction_id = c.output_id
     AND a.transaction_hash = c.call_tx_hash
),
raw_actions AS (
    SELECT
        a.window_label, a.ilk, a.dog_contract, a.clipper_contract, a.auction_id,
        a.transaction_hash, a.block_number, a.block_timestamp, a.transaction_index,
        a.event_index, CAST(NULL AS varchar) AS call_trace_address,
        'bark' AS action_type, 'maker_ethereum.dog_evt_bark' AS source_table,
        'event' AS record_kind, CAST(NULL AS boolean) AS decoded_call_success,
        a.urn AS vault_or_urn, CAST(NULL AS varbinary) AS bark_keeper,
        CAST(NULL AS varbinary) AS kick_keeper, CAST(NULL AS varbinary) AS call_sender,
        CAST(NULL AS varbinary) AS take_who, CAST(NULL AS varbinary) AS take_usr,
        CAST(NULL AS varbinary) AS redo_keeper,
        CAST(a.ink AS varchar) AS bark_ink_raw, CAST(a.art AS varchar) AS bark_art_raw,
        CAST(a.due AS varchar) AS bark_due_raw, CAST(NULL AS varchar) AS kick_top_raw,
        CAST(NULL AS varchar) AS kick_tab_raw, CAST(NULL AS varchar) AS kick_lot_raw,
        CAST(NULL AS varchar) AS kick_coin_raw, CAST(NULL AS varchar) AS take_price_raw,
        CAST(NULL AS varchar) AS take_owe_raw, CAST(NULL AS varchar) AS take_remaining_tab_raw,
        CAST(NULL AS varchar) AS take_remaining_lot_raw, CAST(NULL AS varchar) AS redo_top_raw,
        CAST(NULL AS varchar) AS redo_tab_raw, CAST(NULL AS varchar) AS redo_lot_raw,
        CAST(NULL AS varchar) AS redo_coin_raw,
        CAST(a.ink AS double) / 1e18 AS collateral_wad_units,
        CAST(a.due AS double) / 1e45 AS debt_or_payment_dai,
        CAST(NULL AS double) AS price_dai_per_collateral,
        a.block_timestamp < a.principal_start AS auction_initiated_before_window,
        a.block_timestamp >= a.principal_start AND a.block_timestamp < a.principal_end AS action_in_principal_window,
        1 AS link_ordinal
    FROM selected_context a

    UNION ALL

    SELECT
        b.window_label, b.ilk, b.dog_contract, b.clipper_contract, b.auction_id,
        b.transaction_hash, b.block_number, b.block_timestamp, b.transaction_index,
        CAST(NULL AS bigint), b.call_trace_address,
        'bark', 'maker_ethereum.dog_call_bark', 'call', b.call_success,
        b.urn, b.kpr, CAST(NULL AS varbinary), b.call_sender,
        CAST(NULL AS varbinary), CAST(NULL AS varbinary), CAST(NULL AS varbinary),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS double), CAST(NULL AS double), CAST(NULL AS double),
        COALESCE(b.block_timestamp < w.principal_start, false),
        b.block_timestamp >= w.principal_start AND b.block_timestamp < w.principal_end,
        1
    FROM bark_calls b JOIN windows w ON b.window_label = w.window_label

    UNION ALL

    SELECT
        a.window_label, a.ilk, a.dog_contract, a.clipper_contract, a.auction_id,
        a.transaction_hash, k.block_number, k.block_timestamp, k.transaction_index,
        k.event_index, CAST(NULL AS varchar), 'kick', 'maker_ethereum.clipper_evt_kick',
        'event', CAST(NULL AS boolean), a.urn, CAST(NULL AS varbinary), k.kpr,
        CAST(NULL AS varbinary), CAST(NULL AS varbinary), CAST(NULL AS varbinary),
        CAST(NULL AS varbinary), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(k.top AS varchar), CAST(k.tab AS varchar),
        CAST(k.lot AS varchar), CAST(k.coin AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(k.lot AS double) / 1e18,
        CAST(k.tab AS double) / 1e45, CAST(k.top AS double) / 1e27,
        a.block_timestamp < a.principal_start,
        k.block_timestamp >= a.principal_start AND k.block_timestamp < a.principal_end,
        1
    FROM selected_context a
    JOIN kick_events_extended k
      ON k.window_label = a.window_label
     AND k.clipper_contract = a.clipper_contract
     AND k.auction_id = a.auction_id
     AND k.transaction_hash = a.transaction_hash

    UNION ALL

    SELECT
        k.initiation_window_label, k.ilk, k.dog_contract, k.clipper_contract, k.auction_id,
        k.transaction_hash, k.block_number, k.block_timestamp, k.transaction_index,
        CAST(NULL AS bigint), k.call_trace_address, 'kick',
        'maker_ethereum.clipper_call_kick', 'call', k.call_success,
        k.usr, CAST(NULL AS varbinary), k.kpr, k.call_sender,
        CAST(NULL AS varbinary), CAST(NULL AS varbinary), CAST(NULL AS varbinary),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(k.tab AS varchar), CAST(k.lot AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS double), CAST(k.tab AS double) / 1e45, CAST(NULL AS double),
        k.block_timestamp < a.principal_start,
        k.block_timestamp >= a.principal_start AND k.block_timestamp < a.principal_end,
        1
    FROM kick_calls k
    JOIN selected_context a
      ON a.window_label = k.initiation_window_label
     AND a.clipper_contract = k.clipper_contract
     AND a.auction_id = k.auction_id

    UNION ALL

    SELECT
        a.window_label, a.ilk, a.dog_contract, a.clipper_contract, a.auction_id,
        t.transaction_hash, t.block_number, t.block_timestamp, t.transaction_index,
        t.event_index, CAST(NULL AS varchar), 'take_success',
        'maker_ethereum.clipper_evt_take', 'event', CAST(NULL AS boolean),
        a.urn, CAST(NULL AS varbinary), a.kick_keeper, CAST(NULL AS varbinary),
        CAST(NULL AS varbinary), t.usr, CAST(NULL AS varbinary),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(t.price AS varchar), CAST(t.owe AS varchar),
        CAST(t.tab AS varchar), CAST(t.lot AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(t.lot AS double) / 1e18, CAST(t.owe AS double) / 1e45,
        CAST(t.price AS double) / 1e27, a.block_timestamp < a.principal_start,
        t.block_timestamp >= a.principal_start AND t.block_timestamp < a.principal_end,
        t.link_ordinal
    FROM selected_context a
    JOIN take_events_extended t
      ON t.window_label = a.window_label
     AND t.clipper_contract = a.clipper_contract
     AND t.auction_id = a.auction_id

    UNION ALL

    SELECT
        a.window_label, a.ilk, a.dog_contract, a.clipper_contract, a.auction_id,
        c.transaction_hash, c.block_number, c.block_timestamp, c.transaction_index,
        CAST(NULL AS bigint), c.call_trace_address,
        IF(c.call_success, 'take_success', 'take_failed_call'),
        'maker_ethereum.clipper_call_take', 'call', c.call_success,
        a.urn, CAST(NULL AS varbinary), a.kick_keeper, c.call_sender,
        c.who, CAST(NULL AS varbinary), CAST(NULL AS varbinary),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS double), CAST(NULL AS double), CAST(NULL AS double),
        a.block_timestamp < a.principal_start,
        c.block_timestamp >= a.principal_start AND c.block_timestamp < a.principal_end,
        c.link_ordinal
    FROM selected_context a
    JOIN take_calls_extended c
      ON c.window_label = a.window_label
     AND c.clipper_contract = a.clipper_contract
     AND c.auction_id = a.auction_id

    UNION ALL

    SELECT
        a.window_label, a.ilk, a.dog_contract, a.clipper_contract, a.auction_id,
        r.transaction_hash, r.block_number, r.block_timestamp, r.transaction_index,
        r.event_index, CAST(NULL AS varchar), 'redo_success',
        'maker_ethereum.clipper_evt_redo', 'event', CAST(NULL AS boolean),
        a.urn, CAST(NULL AS varbinary), a.kick_keeper, CAST(NULL AS varbinary),
        CAST(NULL AS varbinary), r.usr, r.kpr,
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(r.top AS varchar),
        CAST(r.tab AS varchar), CAST(r.lot AS varchar), CAST(r.coin AS varchar),
        CAST(r.lot AS double) / 1e18, CAST(r.tab AS double) / 1e45,
        CAST(r.top AS double) / 1e27, a.block_timestamp < a.principal_start,
        r.block_timestamp >= a.principal_start AND r.block_timestamp < a.principal_end,
        r.link_ordinal
    FROM selected_context a
    JOIN redo_events_extended r
      ON r.window_label = a.window_label
     AND r.clipper_contract = a.clipper_contract
     AND r.auction_id = a.auction_id

    UNION ALL

    SELECT
        a.window_label, a.ilk, a.dog_contract, a.clipper_contract, a.auction_id,
        c.transaction_hash, c.block_number, c.block_timestamp, c.transaction_index,
        CAST(NULL AS bigint), c.call_trace_address,
        IF(c.call_success, 'redo_success', 'redo_failed_call'),
        'maker_ethereum.clipper_call_redo', 'call', c.call_success,
        a.urn, CAST(NULL AS varbinary), a.kick_keeper, c.call_sender,
        CAST(NULL AS varbinary), CAST(NULL AS varbinary), c.kpr,
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS double), CAST(NULL AS double), CAST(NULL AS double),
        a.block_timestamp < a.principal_start,
        c.block_timestamp >= a.principal_start AND c.block_timestamp < a.principal_end,
        c.link_ordinal
    FROM selected_context a
    JOIN redo_calls_extended c
      ON c.window_label = a.window_label
     AND c.clipper_contract = a.clipper_contract
     AND c.auction_id = a.auction_id

    UNION ALL

    SELECT
        a.window_label, a.ilk, a.dog_contract, a.clipper_contract, a.auction_id,
        y.transaction_hash, y.block_number, y.block_timestamp, y.transaction_index,
        y.event_index, CAST(NULL AS varchar), 'yank', 'ethereum.logs', 'event',
        CAST(NULL AS boolean), a.urn, CAST(NULL AS varbinary), a.kick_keeper,
        CAST(NULL AS varbinary), CAST(NULL AS varbinary), CAST(NULL AS varbinary),
        CAST(NULL AS varbinary), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS varchar), CAST(NULL AS varchar),
        CAST(NULL AS varchar), CAST(NULL AS double), CAST(NULL AS double),
        CAST(NULL AS double), a.block_timestamp < a.principal_start,
        y.block_timestamp >= a.principal_start AND y.block_timestamp < a.principal_end,
        1
    FROM selected_context a
    JOIN yank_events_extended y
      ON y.window_label = a.window_label
     AND y.clipper_contract = a.clipper_contract
     AND y.auction_id = a.auction_id
),
linked_actions AS (
    SELECT
        a.*,
        CASE
            WHEN a.record_kind = 'event' THEN EXISTS (
                SELECT 1 FROM raw_actions c
                WHERE c.record_kind = 'call'
                  AND c.decoded_call_success = true
                  AND c.action_type = a.action_type
                  AND c.transaction_hash = a.transaction_hash
                  AND COALESCE(c.clipper_contract, c.dog_contract) = COALESCE(a.clipper_contract, a.dog_contract)
                  AND c.auction_id = a.auction_id
                  AND c.link_ordinal = a.link_ordinal
            )
            WHEN a.record_kind = 'call' AND a.decoded_call_success THEN EXISTS (
                SELECT 1 FROM raw_actions e
                WHERE e.record_kind = 'event'
                  AND e.action_type = a.action_type
                  AND e.transaction_hash = a.transaction_hash
                  AND COALESCE(e.clipper_contract, e.dog_contract) = COALESCE(a.clipper_contract, a.dog_contract)
                  AND e.auction_id = a.auction_id
                  AND e.link_ordinal = a.link_ordinal
            )
            ELSE false
        END AS event_to_call_linkage_flag
    FROM raw_actions a
),
transaction_action_counts AS (
    SELECT
        transaction_hash,
        COUNT_IF(record_kind = 'event' OR (record_kind = 'call' AND decoded_call_success = false)) AS maker_liquidation_action_count_in_tx,
        COUNT(DISTINCT ROW(clipper_contract, auction_id)) FILTER (WHERE auction_id IS NOT NULL) AS distinct_auctions_in_tx
    FROM linked_actions
    GROUP BY transaction_hash
),
transactions AS (
    SELECT
        t.hash,
        t."from" AS transaction_sender,
        t."to" AS transaction_recipient,
        t.success,
        t.gas_limit,
        t.gas_used,
        t.gas_price,
        t.max_fee_per_gas,
        t.max_priority_fee_per_gas,
        t.priority_fee_per_gas,
        t.block_time
    FROM ethereum.transactions t
    WHERE (
            t.block_date >= DATE '2023-01-25' AND t.block_date < DATE '2023-02-10'
        AND t.block_time >= TIMESTAMP '2023-01-25 00:00:00' AND t.block_time < TIMESTAMP '2023-02-10 00:00:00'
    ) OR (
            t.block_date >= DATE '2022-06-06' AND t.block_date < DATE '2022-06-22'
        AND t.block_time >= TIMESTAMP '2022-06-06 00:00:00' AND t.block_time < TIMESTAMP '2022-06-22 00:00:00'
    )
),
legacy_counts AS (
    SELECT
        COUNT(*) AS legacy_cat_bite_count,
        COUNT_IF(b.flip IS NOT NULL) AS legacy_flipper_activity_count
    FROM maker_ethereum.cat_evt_bite b
    JOIN ilk_filter f ON b.ilk = f.ilk_raw
    WHERE (
            b.evt_block_date >= DATE '2023-02-01' AND b.evt_block_date < DATE '2023-02-03'
        AND b.evt_block_time >= TIMESTAMP '2023-02-01 00:00:00' AND b.evt_block_time < TIMESTAMP '2023-02-03 00:00:00'
    ) OR (
            b.evt_block_date >= DATE '2022-06-13' AND b.evt_block_date < DATE '2022-06-15'
        AND b.evt_block_time >= TIMESTAMP '2022-06-13 00:00:00' AND b.evt_block_time < TIMESTAMP '2022-06-15 00:00:00'
    )
)
SELECT
    a.window_label AS initiation_window_label,
    a.ilk,
    CONCAT('0x', TO_HEX(a.dog_contract)) AS dog_contract,
    CONCAT('0x', TO_HEX(a.clipper_contract)) AS clipper_contract,
    CAST(a.auction_id AS varchar) AS auction_id,
    CONCAT('0x', TO_HEX(a.transaction_hash)) AS transaction_hash,
    a.block_number,
    a.block_timestamp,
    a.transaction_index,
    a.event_index,
    a.call_trace_address,
    a.action_type,
    a.source_table,
    a.record_kind,
    a.decoded_call_success,
    a.event_to_call_linkage_flag,
    CONCAT('0x', TO_HEX(a.vault_or_urn)) AS vault_or_urn,
    CONCAT('0x', TO_HEX(a.bark_keeper)) AS bark_keeper,
    CONCAT('0x', TO_HEX(a.kick_keeper)) AS kick_keeper,
    CONCAT('0x', TO_HEX(t.transaction_sender)) AS transaction_sender,
    CONCAT('0x', TO_HEX(a.call_sender)) AS call_sender,
    CONCAT('0x', TO_HEX(a.take_who)) AS take_who,
    CONCAT('0x', TO_HEX(a.take_usr)) AS take_usr,
    CONCAT('0x', TO_HEX(a.redo_keeper)) AS redo_keeper,
    a.bark_ink_raw,
    a.bark_art_raw,
    a.bark_due_raw,
    a.kick_top_raw,
    a.kick_tab_raw,
    a.kick_lot_raw,
    a.kick_coin_raw,
    a.take_price_raw,
    a.take_owe_raw,
    a.take_remaining_tab_raw,
    a.take_remaining_lot_raw,
    a.redo_top_raw,
    a.redo_tab_raw,
    a.redo_lot_raw,
    a.redo_coin_raw,
    a.collateral_wad_units,
    a.debt_or_payment_dai,
    a.price_dai_per_collateral,
    CONCAT('0x', TO_HEX(t.transaction_recipient)) AS top_level_transaction_recipient,
    t.success AS top_level_transaction_success,
    t.gas_limit,
    t.gas_used,
    t.gas_price AS effective_gas_price_wei,
    CAST(t.gas_price AS double) / 1e9 AS effective_gas_price_gwei,
    t.max_fee_per_gas,
    t.max_priority_fee_per_gas,
    t.priority_fee_per_gas AS actual_priority_fee_per_gas,
    t.block_time AS transaction_block_timestamp,
    c.maker_liquidation_action_count_in_tx,
    c.distinct_auctions_in_tx,
    c.distinct_auctions_in_tx > 1 AS multi_auction_transaction,
    a.auction_initiated_before_window,
    a.action_in_principal_window,
    true AS action_in_bounded_horizon,
    l.legacy_cat_bite_count,
    l.legacy_flipper_activity_count
FROM linked_actions a
LEFT JOIN transactions t ON t.hash = a.transaction_hash
LEFT JOIN transaction_action_counts c ON c.transaction_hash = a.transaction_hash
CROSS JOIN legacy_counts l
