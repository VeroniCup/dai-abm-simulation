# Raw protocol data

Raw Vat, Spot, Jug, Dog and Clipper setting histories live here. Generated
change ledgers, intervals and hourly panels live under
`data/protocol/processed/`; query, execution, activation, default-state and
validation evidence lives under `data/protocol/provenance/`.

Protocol settings use the latest valid pre-sample state or a documented
activation boundary. They are not inferred from liquidation outcomes or
opportunistic getter calls. Historical diagnostic SQL is preserved under
`sql/protocol/generated/history/`; active module templates are under
`sql/protocol/templates/`.

See [protocol reconstruction](../../../docs/calibration/protocol.md).
