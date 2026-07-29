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
cross-domain `provenance/calibration/` tree includes compact, content-addressed
calibration evidence but never hourly payloads. Generated diagnostics belong
under `outputs/diagnostics/`, not in the domain data lifecycle.
