# Raw liquidation data

This directory owns the decoded Maker liquidation action facts, bounded chunk
results and unique Ethereum transaction bridge. Raw event/call rows and
transaction rows remain separate before local reconciliation.

Generated payloads are ignored by Git. Query/execution identifiers, checksums,
legacy-gate evidence and validation live under
`data/liquidations/provenance/`. See
[liquidation calibration](../../../docs/calibration/liquidations.md).
