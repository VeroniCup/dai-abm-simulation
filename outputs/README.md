# Generated outputs

The output hierarchy separates generated simulation and analytical artefacts
by responsibility:

- `experiments/<experiment>/` contains detailed simulation-run results;
- `figures/<experiment>/` contains experiment figures;
- `diagnostics/<domain-or-workflow>/` contains generated validation,
  calibration and workflow diagnostics;
- `tables/<study-or-experiment>/` contains compact derived summaries and
  comparison tables.

Ordinary contents beneath these four directories are reproducible local
artefacts and are ignored by Git. Empirical observations, processed analytical
panels, compact runtime model inputs and acquisition provenance remain under
`data/`; they are not outputs.

Run validation in a temporary directory when comparison with established
artefacts is required. Do not mix figures with detailed results or treat
generated diagnostics as empirical source evidence.
