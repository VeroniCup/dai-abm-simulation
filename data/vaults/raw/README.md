# Raw vault data

Validated monthly methodology chunks and representative-regime acquisitions
live beneath this directory. They preserve successful Vat frob, fork and grab
calls, ownership mappings, liquidation annotations and accumulated-rate
evidence where applicable.

Raw rows are immutable and ignored by Git. Checksums, query and execution
identifiers, resume state and validation records live under
`data/vaults/provenance/`. SQL templates are under `sql/vaults/templates/`;
active acquisition entry points are `workflows/vaults/acquire.py` and
`workflows/vaults/acquire_representative.py`.

See the [representative vault methodology](../../../docs/calibration/vaults.md).
