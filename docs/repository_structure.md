# Repository structure

The portable archive is organised around an installable Python package,
explicit configuration, compact data inputs and reproducible command-line
workflows. Scientific source files and generated output are kept separate.

## Archive tree

```text
dai-abm-simulation/
├── README.md
├── pyproject.toml
├── requirements.txt
├── environment.yml
├── src/
│   └── dai_sim/
│       ├── model/
│       ├── inputs/
│       ├── calibration/
│       ├── experiments/
│       │   ├── mechanism/
│       │   └── final/
│       ├── validation/
│       └── common/
├── config/
│   ├── profiles/
│   ├── protocol/
│   ├── sensitivities/
│   ├── validation/
│   └── runtime/
├── data/
│   ├── market/model_inputs/
│   ├── gas/provenance/
│   ├── vaults/model_inputs/
│   ├── liquidations/model_inputs/
│   ├── protocol/provenance/
│   ├── model_inputs/
│   └── provenance/
├── workflows/
│   ├── market/
│   ├── gas/
│   ├── vaults/
│   ├── liquidations/
│   ├── protocol/
│   ├── inputs/
│   ├── calibration/
│   ├── experiments/
│   ├── validation/
│   └── verification/
├── sql/
│   └── <domain>/{templates,generated}/
├── tests/
│   ├── model/
│   ├── inputs/
│   ├── calibration/
│   ├── experiments/
│   ├── validation/
│   ├── workflows/
│   └── integration/
└── docs/
    ├── repository_structure.md
    ├── components.md
    └── running.md
```

The tree shows the material included in the archive rather than every raw,
processed or generated file used during the research.

## Source code

`src/dai_sim/` is the only installed package. `model/` contains economic state
and transition logic. `inputs/` loads profiles, registries and compact runtime
files. `calibration/` contains estimation and evidence-building utilities,
while `experiments/` and `validation/` contain repeated comparisons and
evaluation code. `common/` provides small shared facilities such as path
resolution and deterministic serialisation.

The `src/` layout prevents repository files from being imported accidentally
when the package has not been installed. Package discovery is bounded to the
`dai_sim` namespace by `pyproject.toml`.

## Configuration

`config/` holds text-based configuration rather than generated data.
`profiles/` contains complete runnable configurations, including the legacy
and empirical profiles. `protocol/` records collateral and protocol settings.
`sensitivities/` contains controlled overrides and treatment registries, and
`validation/` contains held-out window definitions. `runtime/` contains the
neutral compact-runtime source map used by the installed package.

Configuration files are validated when loaded. A sensitivity file is not a
complete profile, and an experimental setting is not automatically a default.
Archive-construction policy remains development-only and is not distributed.

## Compact model inputs and provenance

`data/` is organised by economic domain: market, gas, vaults, liquidations and
protocol. The archive retains compact files needed by the runtime under
`model_inputs/`, together with checksums and transformation records under
`provenance/`. Cross-domain calibration, experiment and validation evidence is
stored under `data/provenance/`.

Large raw acquisitions and full processed panels are not included. They are
retained separately where a complete historical reconstruction is required.
The compact files are sufficient for package loading, ordinary simulations and
the test suite.

## Workflows

`workflows/` contains executable Python entry points grouped by task. Domain
directories cover data acquisition and processing. `inputs/` validates or
builds runtime inputs, `calibration/` exposes estimation utilities,
`experiments/` runs mechanism and registered comparison matrices, and
`validation/` contains held-out evaluation entry points.

The archive also includes a narrow read-only historical artefact verifier under
`workflows/verification/`. Internal packaging tools are kept outside the
archive. Workflows import the installed package; they do not duplicate the
model equations.

## SQL

`sql/` follows the same market, gas, vault, liquidation and protocol domains.
Files under `templates/` are maintained query designs. Files under
`generated/` preserve the exact bounded queries used for historical
acquisition. SQL is included for inspection and reproducibility, but executing
it may require an external data service and credentials.

## Tests

`tests/` mirrors the software responsibilities. Unit tests cover model and
input behaviour. Experiment, calibration and validation tests protect their
contracts and compact evidence. Workflow tests check command boundaries and
safe resume behaviour. Integration tests cover package discovery, repository
paths, SQL, documentation, provenance and the filtered archive itself.

Temporary test data is created under test-controlled directories. Ordinary
tests do not need ignored result folders, full processed data or historical
worker checkpoints.

## Documentation

The archive includes only this structure guide, the component guide, the
running guide and the root README. Detailed research notes and historical
project records remain outside the portable documentation set. Numerical
evidence remains available in compact CSV and JSON files rather than being
repeated in software documentation.

## Generated outputs

Generated files are written to explicit namespaces in a development checkout:

```text
outputs/
├── experiments/
│   ├── mechanism/
│   └── final/
├── validation/
├── diagnostics/
├── figures/
└── tables/
```

Mechanism studies and registered comparison matrices therefore do not mix
their detailed rows. Validation output has a separate root, and presentation
files remain separate from experiment results. The whole `outputs/` tree is
generated, ignored by Git and excluded from the code archive.
