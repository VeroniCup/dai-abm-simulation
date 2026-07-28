-- Phase 1E CdpManager open/NewCdp/UrnHandler mappings, conservatively from MCD launch.
WITH selected_ilks(ilk_raw, ilk) AS (
    VALUES
        (0x4554482d41000000000000000000000000000000000000000000000000000000, 'ETH-A'),
        (0x4554482d42000000000000000000000000000000000000000000000000000000, 'ETH-B'),
        (0x4554482d43000000000000000000000000000000000000000000000000000000, 'ETH-C'),
        (0x574254432d410000000000000000000000000000000000000000000000000000, 'WBTC-A'),
        (0x574254432d420000000000000000000000000000000000000000000000000000, 'WBTC-B'),
        (0x574254432d430000000000000000000000000000000000000000000000000000, 'WBTC-C')
),
opens AS (
    SELECT o.*, i.ilk
    FROM maker_ethereum.cdp_manager_call_open o
    INNER JOIN selected_ilks i ON i.ilk_raw = o.ilk
    WHERE o.call_block_date >= DATE '2019-11-01'
      AND o.call_block_date < DATE '2024-07-01'
      AND o.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND o.call_block_time < TIMESTAMP '2024-07-01 00:00:00 UTC'
      AND o.contract_address = 0x5ef30b9986345249bc32d8928b7ee64de9435e39
      AND o.call_success = true
),
new_cdps AS (
    SELECT *
    FROM maker_ethereum.cdp_manager_evt_newcdp
    WHERE evt_block_date >= DATE '2019-11-01'
      AND evt_block_date < DATE '2024-07-01'
      AND evt_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND evt_block_time < TIMESTAMP '2024-07-01 00:00:00 UTC'
      AND contract_address = 0x5ef30b9986345249bc32d8928b7ee64de9435e39
),
creates AS (
    SELECT *
    FROM ethereum.traces
    WHERE block_date >= DATE '2019-11-01'
      AND block_date < DATE '2024-07-01'
      AND block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND block_time < TIMESTAMP '2024-07-01 00:00:00 UTC'
      AND type = 'create'
      AND success = true
      AND "from" = 0x5ef30b9986345249bc32d8928b7ee64de9435e39
),
transactions AS (
    SELECT hash, block_number, index AS transaction_index
    FROM ethereum.transactions
    WHERE block_date >= DATE '2019-11-01'
      AND block_date < DATE '2024-07-01'
      AND block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND block_time < TIMESTAMP '2024-07-01 00:00:00 UTC'
)
SELECT
    o.call_block_time AS effective_time_utc,
    o.call_block_number AS block_number,
    CONCAT('0x', TO_HEX(o.call_tx_hash)) AS transaction_hash,
    t.transaction_index,
    ARRAY_JOIN(TRANSFORM(o.call_trace_address, x -> CAST(x AS varchar)), '.') AS open_trace_position,
    n.evt_index AS newcdp_log_index,
    ARRAY_JOIN(TRANSFORM(c.trace_address, x -> CAST(x AS varchar)), '.') AS creation_trace_position,
    o.ilk,
    CAST(o.output_0 AS varchar) AS cdp_id,
    CONCAT('0x', TO_HEX(c.address)) AS urn,
    CONCAT('0x', TO_HEX(o.usr)) AS initial_owner,
    CONCAT('0x', TO_HEX(n.own)) AS event_owner,
    CONCAT('0x', TO_HEX(n.usr)) AS manager_caller,
    CONCAT('0x', TO_HEX(o.call_tx_from)) AS top_level_sender,
    CONCAT('0x', TO_HEX(o.contract_address)) AS manager_contract,
    CONCAT('0x', TO_HEX(c."from")) AS urn_creator,
    o.call_success,
    c.trace_address = CONCAT(o.call_trace_address, ARRAY[CAST(0 AS bigint)]) AS creation_is_direct_child
FROM opens o
INNER JOIN new_cdps n
    ON n.evt_tx_hash = o.call_tx_hash
   AND n.cdp = o.output_0
INNER JOIN creates c
    ON c.tx_hash = o.call_tx_hash
   AND c.trace_address = CONCAT(o.call_trace_address, ARRAY[CAST(0 AS bigint)])
INNER JOIN transactions t
    ON t.hash = o.call_tx_hash
   AND t.block_number = o.call_block_number
