# Empirical data

Empirical data are organised by domain:

- `market/`;
- `gas/`;
- `vaults/`;
- `liquidations/`;
- `protocol/`.

Each populated domain owns `raw/`, `processed/`, `model_inputs/` and
`provenance/` responsibilities. The narrow `provenance/` root contains the
cross-domain index and authoritative data manifest.

Current guidance:

- [Acquisition](../docs/data/acquisition.md)
- [Processing](../docs/data/processing.md)
- [Provenance](../docs/data/provenance.md)

Raw and processed payloads are generated locally and ignored by Git. Compact
runtime model inputs and selected provenance records are tracked. The
`processed/estimation/` diagnostics tree remains temporarily in its historical
location until the output restructuring stage; it is not a destination for new
domain data.
