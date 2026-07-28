-- Phase 1C production unique transaction bridge: 11_2022_04.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x0317fbf676794d044ef69a334f09ce481d688994e147b1361a10150a9492df3e),
        (0x0affcfed4db6f7d8422dab05aed65f018c8884ce6f896800ba64848a87de6981),
        (0x469762aa18e678c7bb8b0aaef2b84e0ee33094d1f2a1dc4b61dec016e984574b),
        (0x4f230446bd30d6eb412e3da57cadb57f656645ec0140a17acdf582bb3af9a7c7),
        (0x50fac62b516004c9df1ef6acbbccc98156f5472e8ca7e23f89c8033c4937e339),
        (0x5223675573eab64600775682e297119dbb9aa8055d2f1e4d323053e3b1f65694),
        (0x688fab9686f1bebd8b8772bee721fc8816bd489738604c34e76a442e97629f2d),
        (0x6c5e94c75086d9c17c89c339b8bb14aaa0a7fc955a1325ac2aad0bfa771d04be),
        (0x6ebd5d61885d3210efbb10b093b8aecd2dac726f19f0aa27aecd41a18b4bc44c),
        (0x7084f884da9f6e1ad840ff2329145feb815c1fc6d9001cd39c95e4f2813559dd),
        (0x7c1863d7ac368b2b7933a2697f45e91e1a1dc9db2d252900f56f8c40e0caa767),
        (0x96ca3509f516def0fe6cfc959edb0b8ca481ed9e02fb017c9777f650c7170e5f),
        (0x9878c515a1d7e6adef9ecce27312a8b584ddddc2744db9cd777a3a101dd10a0e),
        (0x991097b5a77e9b3f56a695bb3c784302574470487d23bdc4cea808b712bd1938),
        (0xa9c659a6c0b9ea6e09aec358bff5810f2de1a106ff22a5d6b5e1f684039e3af1),
        (0xc3cdb51d0c0f85dda24f05b829dbf74d7632495db56a8bc27cdd0ddd196e04ad),
        (0xc4d6b5184ac073517469af3ad5845167a2b39f2fd6d8bb897bd26a7ceac5ceab),
        (0xcc11d6838c24a6a9b9a5999513c48c2a23c0654307232f8f663219e787f428f5),
        (0xce0533fda3c324b47f455634f83e4744fa5aab08bcd7f3eead6c1a13588fa6bc),
        (0xd76b704aa689f87176bbde9fdb90728f86dd0d4c2639ceb224ca0af56317e6a3),
        (0xdb3229af946209cf4bdbea5e9064089c43ca2ec9c0fab2823ec121b901bf28a8),
        (0xe7bacdc317afbaaa5bf55576aa1b320ce36c2c224e3ea65cf962cbe5670202e6),
        (0xef34cf9fc0abd8ade4140c9bac3b11d1504c8183bb9bb7d3a98daa0a00eb875a),
        (0xf4e17d9c08d4f2b124d7d4dc3a50046a9260f7427d3da155b392f36d2975945a),
        (0xfc942882cebbd4c2534e8241dbc56fe0edf11247f52319a06d5fb7075b813840)
)
SELECT
    CONCAT('0x', TO_HEX(t.hash)) AS tx_hash,
    CONCAT('0x', TO_HEX(t."from")) AS transaction_sender,
    CONCAT('0x', TO_HEX(t."to")) AS transaction_recipient,
    t.success,
    t.gas_limit,
    t.gas_used,
    t.gas_price,
    t.max_fee_per_gas,
    t.max_priority_fee_per_gas,
    t.priority_fee_per_gas,
    t.block_time,
    t.block_number,
    t.block_date,
    t.index AS transaction_index
FROM ethereum.transactions t
JOIN selected_hashes h ON t.hash = h.tx_hash
WHERE t.block_date >= DATE '2022-04-01'
  AND t.block_date < DATE '2022-05-08'
  AND t.block_time >= TIMESTAMP '2022-04-01 00:00:00'
  AND t.block_time < TIMESTAMP '2022-05-08 00:00:00'
