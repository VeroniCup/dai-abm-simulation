-- Phase 1C production unique transaction bridge: 09_2022_02.
WITH selected_hashes(tx_hash) AS (
    VALUES
        (0x0581f4c99a0a6c6c06e60c2b3fa6b83b12c2816475beb6aae818120ca2ebe346),
        (0x0bab58c7721cbb7262b3ce36c6602362409c6c91b0852c78fb7a8a2c28d8acce),
        (0x0fd0cbf4e9cdd3df57711b86ea7bcb39937b53dffb38cab9f12ad6268bd9f290),
        (0x1ab56ed248bfd22f020cfcdebae2b4b47f83bd2185af77e102232219e04e62a2),
        (0x254980828237e8399bdfc3ec83432b6e199bb7ce3fa89e66b305e194a9afaaad),
        (0x2a430067b4b001b194362a9afbdd57c4319007326f08096078d3e4c18304fe2b),
        (0x31adfc52ce8593de47a82cbe974396e7bcd36725d8c42e4359f273f547be3c3b),
        (0x33ab03edf87010ddb2460af25a7d0441b9315f50ab70fbf9ff3b70d62bf0b84a),
        (0x374f15a196ae71bf6aaccc30d76a390a11381b1524c6801360793b70b402637b),
        (0x4d68199e58f9ca22b06d5afa31695ab2e0a8838b10ec1ff39a4abadad6c3f3ac),
        (0x4deac6f06f39bc8700d947dfee86ec5f4a571f848f91742aabb0c70311f176f5),
        (0x4e8dcf58c78bfecdc7a9ecf6b878e5ca675faffba243494dd59e077b4e5497a3),
        (0x64ee1c9f0f954462d32d192cc423eece7d1beceefe287b1f23ac971cc3db5906),
        (0x6cd7c80dff7d4a95fa6e579bc9c8f03ce9bce5db5d70b41608a67085a6b416c2),
        (0x6ea833a63d377202312a49caea19e52faeea6c64622d5225a3b517f60bc69d81),
        (0x73a71b006186500efe6810bcbd24a2cfb47b040c994db8b3e121d2d21c96bbcd),
        (0x7e1be8decf7272c616d794046eb2ca7cb7676b65be8f420be090dcdf7ed8a484),
        (0x83fbf5652ffca4ca395c8858a07da72004f14e37f72ead8adebdb450f59492c0),
        (0x91674edfe676f77b54f85ccbcb3770d6a60171da777dbd01adc414e1693aaaf0),
        (0x96c26f03bc68a83845d2a7f31a690bd9bd2c1942b4565254b1ede8543048a19c),
        (0xba9e6fc8021e8b91a4a07a96d12a8637d1e14a38268fd52b7ce5ea12754853a4),
        (0xbb7dd830c732f06243a67c9ef0c69f56d7205dcdf002a7f2c235185ba68c5133),
        (0xc40004157012ffecbe77ec20099258cbc31a12bb520fe752814fa56eaf67bafe),
        (0xdb89060dee4b8fb78594b79fc9a6bda1d4fa8a72c863ea4c267c25dc55a0524b),
        (0xddc519e4bd1605ea6871b7b095e7ed06291465a8f7ae080e5af37ddeab485f7e),
        (0xfb7d322b01df5fd5873c92b3dc2448d7115b3df189664c58f3e3061d2209acd5),
        (0xfef98e7e7f98ed90902a59bf205f9e3be3c982adb0bdaf54c1b870df0f547aa7)
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
WHERE t.block_date >= DATE '2022-02-01'
  AND t.block_date < DATE '2022-03-08'
  AND t.block_time >= TIMESTAMP '2022-02-01 00:00:00'
  AND t.block_time < TIMESTAMP '2022-03-08 00:00:00'
