-- Phase 1E diagnostic 1: canonical ETH-A Vat.frob state changes.
-- The seven-day interval is deliberately bounded and partition-pruned.
WITH frobs AS (
    SELECT
        f.call_block_time AS block_time_utc,
        f.call_block_number AS block_number,
        f.call_tx_hash AS transaction_hash,
        f.call_tx_index AS transaction_index,
        ARRAY_JOIN(
            TRANSFORM(f.call_trace_address, x -> CAST(x AS varchar)),
            '.'
        ) AS trace_position,
        f.contract_address AS source_contract,
        f.call_tx_from AS top_level_sender,
        f.call_tx_to AS top_level_recipient,
        f.call_success AS success,
        f.i AS ilk_raw,
        f.u AS urn,
        f.v AS collateral_source,
        f.w AS debt_destination,
        f.dink AS dink_raw,
        f.dart AS dart_raw
    FROM maker_ethereum.vat_call_frob f
    WHERE f.call_block_date >= DATE '2023-02-01'
      AND f.call_block_date < DATE '2023-02-08'
      AND f.call_block_time >= TIMESTAMP '2023-02-01 00:00:00 UTC'
      AND f.call_block_time < TIMESTAMP '2023-02-08 00:00:00 UTC'
      AND f.contract_address = 0x35d1b3f3d7966a1dfe207aa4514c12a259a0492b
      AND f.call_success = true
      AND f.i = 0x4554482d41000000000000000000000000000000000000000000000000000000
)
SELECT
    block_time_utc,
    block_number,
    CONCAT('0x', TO_HEX(transaction_hash)) AS transaction_hash,
    transaction_index,
    trace_position,
    CONCAT('0x', TO_HEX(source_contract)) AS source_contract,
    CONCAT('0x', TO_HEX(top_level_sender)) AS top_level_sender,
    CONCAT('0x', TO_HEX(top_level_recipient)) AS top_level_recipient,
    success,
    'ETH-A' AS ilk,
    CONCAT('0x', TO_HEX(urn)) AS urn,
    CONCAT('0x', TO_HEX(collateral_source)) AS collateral_source,
    CONCAT('0x', TO_HEX(debt_destination)) AS debt_destination,
    CAST(dink_raw AS varchar) AS dink_raw,
    CAST(dart_raw AS varchar) AS dart_raw,
    CAST(dink_raw AS double) / 1e18 AS collateral_delta_wad,
    CAST(dart_raw AS double) / 1e18 AS normalised_debt_delta_wad,
    dink_raw > 0 AS is_deposit,
    dink_raw < 0 AS is_withdrawal,
    dart_raw > 0 AS is_debt_draw,
    dart_raw < 0 AS is_debt_repayment
FROM frobs
ORDER BY block_number, transaction_index, transaction_hash, trace_position
