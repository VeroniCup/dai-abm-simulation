# Raw protocol data

Place unmodified protocol-time observations, such as liquidation volume, here.
Protocol inputs are optional for the first market panel but must be documented
in the data manifest when configured. Raw files are ignored by Git.

Phase 1D raw module observations are stored directly in `data/protocol/raw/`.
Discovery records, parameter-source mappings, diagnostic state and validation,
and production manifests are stored under `data/protocol/provenance/`. Derived
change ledgers, intervals and hourly panels are under
`data/protocol/processed/`. These generated artefacts remain ignored;
the durable diagnostic SQL is
`sql/protocol/generated/history/eth_a_debt_ceiling_diagnostic.sql` and the local validation
implementation is `workflows/maintenance/archive/debt_ceiling_diagnostic.py`.

The Phase 1D diagnostic does not constitute production acquisition and does not
change any simulator parameter. Protocol settings are reconstructed as
effective-dated change records with an explicit pre-sample initial state; they
must not be inferred from liquidation outcomes.
