# Raw gas data

This directory stores the 13 unmodified hourly Dune result chunks and the
locally assembled raw panel. Query and execution identifiers, checksums,
validation, acquisition state and credit records live under
`data/gas/provenance/`.

The assembled file is a local ordering and concatenation of validated chunks,
not a Dune-side transformation. Raw payloads and detailed acquisition metadata
are ignored by Git. No gas-to-USD conversion or parameter estimation belongs
here. See the [processing guide](../../../docs/data/processing.md).
