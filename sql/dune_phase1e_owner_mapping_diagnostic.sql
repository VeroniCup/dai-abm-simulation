-- Phase 1E diagnostic 3: CDP ID, UrnHandler, manager owner and bounded gives.
-- Openings are selected in one seven-day interval. Successful give calls for
-- those newly opened CDPs are followed for a bounded additional 28 days.
WITH opens AS (
    SELECT
        o.call_block_time AS block_time_utc,
        o.call_block_number AS block_number,
        o.call_tx_hash AS transaction_hash,
        o.call_trace_address AS open_trace_address,
        o.call_tx_from AS top_level_sender,
        o.contract_address AS manager_contract,
        o.ilk AS ilk_raw,
        o.usr AS requested_owner,
        o.output_0 AS cdp_id
    FROM maker_ethereum.cdp_manager_call_open o
    WHERE o.call_block_date >= DATE '2023-02-01'
      AND o.call_block_date < DATE '2023-02-08'
      AND o.call_block_time >= TIMESTAMP '2023-02-01 00:00:00 UTC'
      AND o.call_block_time < TIMESTAMP '2023-02-08 00:00:00 UTC'
      AND o.contract_address = 0x5ef30b9986345249bc32d8928b7ee64de9435e39
      AND o.call_success = true
      AND o.ilk = 0x4554482d41000000000000000000000000000000000000000000000000000000
),
new_cdps AS (
    SELECT
        n.evt_tx_hash AS transaction_hash,
        n.evt_index AS event_index,
        n.usr AS manager_caller,
        n.own AS recorded_owner,
        n.cdp AS cdp_id
    FROM maker_ethereum.cdp_manager_evt_newcdp n
    WHERE n.evt_block_date >= DATE '2023-02-01'
      AND n.evt_block_date < DATE '2023-02-08'
      AND n.evt_block_time >= TIMESTAMP '2023-02-01 00:00:00 UTC'
      AND n.evt_block_time < TIMESTAMP '2023-02-08 00:00:00 UTC'
      AND n.contract_address = 0x5ef30b9986345249bc32d8928b7ee64de9435e39
),
urn_creations AS (
    SELECT
        t.tx_hash AS transaction_hash,
        t.address AS urn_handler,
        t."from" AS creator,
        t.trace_address AS creation_trace_address,
        t.block_time AS creation_block_time,
        t.block_number AS creation_block_number
    FROM ethereum.traces t
    WHERE t.block_date >= DATE '2023-02-01'
      AND t.block_date < DATE '2023-02-08'
      AND t.block_time >= TIMESTAMP '2023-02-01 00:00:00 UTC'
      AND t.block_time < TIMESTAMP '2023-02-08 00:00:00 UTC'
      AND t.type = 'create'
      AND t.success = true
      AND t."from" = 0x5ef30b9986345249bc32d8928b7ee64de9435e39
),
open_mappings AS (
    SELECT
        o.block_time_utc,
        o.block_number,
        o.transaction_hash,
        o.open_trace_address,
        n.event_index,
        o.ilk_raw,
        o.cdp_id,
        c.urn_handler,
        o.requested_owner,
        n.recorded_owner,
        n.manager_caller,
        o.top_level_sender,
        o.manager_contract,
        c.creator,
        c.creation_block_time,
        c.creation_block_number,
        c.creation_trace_address
    FROM opens o
    INNER JOIN new_cdps n
        ON n.transaction_hash = o.transaction_hash
       AND n.cdp_id = o.cdp_id
    INNER JOIN urn_creations c
        ON c.transaction_hash = o.transaction_hash
       AND c.creation_trace_address = CONCAT(
           o.open_trace_address, ARRAY[CAST(0 AS bigint)]
       )
),
gives AS (
    SELECT
        g.call_block_time AS block_time_utc,
        g.call_block_number AS block_number,
        g.call_tx_hash AS transaction_hash,
        g.call_trace_address AS give_trace_address,
        g.call_tx_from AS top_level_sender,
        g.contract_address AS manager_contract,
        g.cdp AS cdp_id,
        g.dst AS new_owner,
        g.call_success
    FROM maker_ethereum.cdp_manager_call_give g
    INNER JOIN open_mappings m ON m.cdp_id = g.cdp
    WHERE g.call_block_date >= DATE '2023-02-01'
      AND g.call_block_date < DATE '2023-03-08'
      AND g.call_block_time >= TIMESTAMP '2023-02-01 00:00:00 UTC'
      AND g.call_block_time < TIMESTAMP '2023-03-08 00:00:00 UTC'
      AND g.contract_address = 0x5ef30b9986345249bc32d8928b7ee64de9435e39
      AND g.call_success = true
),
relevant_transactions AS (
    SELECT transaction_hash, block_number FROM open_mappings
    UNION
    SELECT transaction_hash, block_number FROM gives
),
tx AS (
    SELECT
        t.hash AS transaction_hash,
        t.block_number,
        t.index AS transaction_index
    FROM ethereum.transactions t
    INNER JOIN relevant_transactions r
        ON r.transaction_hash = t.hash
       AND r.block_number = t.block_number
    WHERE t.block_date >= DATE '2023-02-01'
      AND t.block_date < DATE '2023-03-08'
      AND t.block_time >= TIMESTAMP '2023-02-01 00:00:00 UTC'
      AND t.block_time < TIMESTAMP '2023-03-08 00:00:00 UTC'
),
records AS (
    SELECT
        m.block_time_utc,
        m.block_number,
        m.transaction_hash,
        tx.transaction_index,
        ARRAY_JOIN(TRANSFORM(m.open_trace_address, x -> CAST(x AS varchar)), '.') AS source_position,
        'open' AS event_type,
        'maker_ethereum.cdp_manager_call_open+cdp_manager_evt_newcdp+ethereum.traces' AS source_table,
        m.cdp_id,
        m.ilk_raw,
        m.urn_handler,
        m.requested_owner AS original_manager_owner,
        CAST(NULL AS varbinary) AS new_owner,
        m.recorded_owner AS event_recorded_owner,
        m.manager_caller,
        m.top_level_sender,
        m.manager_contract,
        true AS call_success,
        m.event_index,
        ARRAY_JOIN(TRANSFORM(m.creation_trace_address, x -> CAST(x AS varchar)), '.') AS creation_trace_position,
        m.creator AS urn_creator,
        m.creation_block_time,
        m.creation_block_number,
        m.creation_trace_address = CONCAT(
            m.open_trace_address, ARRAY[CAST(0 AS bigint)]
        ) AS creation_is_direct_child,
        m.requested_owner = m.recorded_owner AS owner_reconciles
    FROM open_mappings m
    INNER JOIN tx
        ON tx.transaction_hash = m.transaction_hash
       AND tx.block_number = m.block_number

    UNION ALL

    SELECT
        g.block_time_utc,
        g.block_number,
        g.transaction_hash,
        tx.transaction_index,
        ARRAY_JOIN(TRANSFORM(g.give_trace_address, x -> CAST(x AS varchar)), '.') AS source_position,
        'give' AS event_type,
        'maker_ethereum.cdp_manager_call_give' AS source_table,
        g.cdp_id,
        m.ilk_raw,
        m.urn_handler,
        m.requested_owner AS original_manager_owner,
        g.new_owner,
        m.recorded_owner AS event_recorded_owner,
        CAST(NULL AS varbinary) AS manager_caller,
        g.top_level_sender,
        g.manager_contract,
        g.call_success,
        CAST(NULL AS bigint) AS event_index,
        ARRAY_JOIN(TRANSFORM(m.creation_trace_address, x -> CAST(x AS varchar)), '.') AS creation_trace_position,
        m.creator AS urn_creator,
        m.creation_block_time,
        m.creation_block_number,
        true AS creation_is_direct_child,
        true AS owner_reconciles
    FROM gives g
    INNER JOIN open_mappings m ON m.cdp_id = g.cdp_id
    INNER JOIN tx
        ON tx.transaction_hash = g.transaction_hash
       AND tx.block_number = g.block_number
)
SELECT
    block_time_utc,
    block_number,
    CONCAT('0x', TO_HEX(transaction_hash)) AS transaction_hash,
    transaction_index,
    source_position,
    event_type,
    source_table,
    CAST(cdp_id AS varchar) AS cdp_id,
    'ETH-A' AS ilk,
    CONCAT('0x', TO_HEX(urn_handler)) AS urn,
    CONCAT('0x', TO_HEX(original_manager_owner)) AS original_manager_owner,
    CASE WHEN new_owner IS NULL THEN NULL ELSE CONCAT('0x', TO_HEX(new_owner)) END AS new_owner,
    CONCAT('0x', TO_HEX(event_recorded_owner)) AS event_recorded_owner,
    CASE WHEN manager_caller IS NULL THEN NULL ELSE CONCAT('0x', TO_HEX(manager_caller)) END AS manager_caller,
    CONCAT('0x', TO_HEX(top_level_sender)) AS top_level_sender,
    CONCAT('0x', TO_HEX(manager_contract)) AS manager_contract,
    call_success,
    event_index,
    creation_trace_position,
    CONCAT('0x', TO_HEX(urn_creator)) AS urn_creator,
    creation_block_time,
    creation_block_number,
    creation_is_direct_child,
    owner_reconciles
FROM records
ORDER BY block_number, transaction_index, source_position, transaction_hash,
         event_type
