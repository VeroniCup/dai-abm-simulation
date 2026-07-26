-- Phase 1E successful CdpManager ownership changes.
WITH transactions AS (
    SELECT hash, block_number, index AS transaction_index
    FROM ethereum.transactions
    WHERE block_date >= DATE '2019-11-01'
      AND block_date < DATE '2024-07-01'
      AND block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
      AND block_time < TIMESTAMP '2024-07-01 00:00:00 UTC'
)
SELECT
    g.call_block_time AS effective_time_utc,
    g.call_block_number AS block_number,
    CONCAT('0x', TO_HEX(g.call_tx_hash)) AS transaction_hash,
    t.transaction_index,
    ARRAY_JOIN(TRANSFORM(g.call_trace_address, x -> CAST(x AS varchar)), '.') AS trace_position,
    CAST(g.cdp AS varchar) AS cdp_id,
    CONCAT('0x', TO_HEX(g.dst)) AS new_owner,
    CONCAT('0x', TO_HEX(g.call_tx_from)) AS top_level_sender,
    CONCAT('0x', TO_HEX(g.contract_address)) AS manager_contract,
    g.call_success
FROM maker_ethereum.cdp_manager_call_give g
INNER JOIN transactions t
    ON t.hash = g.call_tx_hash
   AND t.block_number = g.call_block_number
WHERE g.call_block_date >= DATE '2019-11-01'
  AND g.call_block_date < DATE '2024-07-01'
  AND g.call_block_time >= TIMESTAMP '2019-11-01 00:00:00 UTC'
  AND g.call_block_time < TIMESTAMP '2024-07-01 00:00:00 UTC'
  AND g.contract_address = 0x5ef30b9986345249bc32d8928b7ee64de9435e39
  AND g.call_success = true
