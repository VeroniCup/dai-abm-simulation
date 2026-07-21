# Raw gas data

Phase 1B stores the 13 unmodified Dune result-row CSVs under `chunks/` and the
locally sorted, concatenated raw panel at
`dune_ethereum_hourly_gas_2021-06-01_2024-06-30.csv`. State, checksums, query and
execution identifiers, validation and credit metadata are stored alongside the
ignored data. The combined panel is not a Dune-side transformation.

Raw data files and their acquisition metadata are ignored by Git; this
documentation file and the repository manifest retain the durable provenance.
No gas-to-USD conversion or parameter estimation belongs in this directory.
