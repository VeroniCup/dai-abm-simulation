# Repository guide

## Start here

The authoritative paths are:

| Need | Path |
| --- | --- |
| Economic model | `src/dai_sim/model/` |
| Empirical input adapters | `src/dai_sim/inputs/` |
| Calibration methods | `src/dai_sim/calibration/` |
| Experiment scenarios and runners | `src/dai_sim/experiments/` |
| Complete profiles | `config/profiles/` |
| Sensitivity overrides | `config/sensitivities/` |
| Domain data and provenance | `data/<domain>/` |
| Workflow entry points | `workflows/` |
| SQL templates and history | `sql/<domain>/` |
| Active documentation | `docs/overview/`, `docs/model/`, `docs/calibration/`, `docs/experiments/`, `docs/data/`, `docs/validation/` |
| Historical reports and plans | `docs/archive/` |

Run commands from the repository root.

## Installation

Python 3.11–3.13 is supported by `pyproject.toml`. The project can be installed
in an isolated environment with:

```bash
python -m pip install -e .
```

The package exposes Python modules rather than an installed console command.

## Running the model

The current supported interface is the Python API. For example:

```python
from dai_sim.experiments.runner import run_all_scenarios

results, summary = run_all_scenarios()
```

The runner writes detailed experiment results beneath `outputs/experiments/`
and summary tables beneath `outputs/tables/`; plotting utilities write beneath
`outputs/figures/`. Use explicitly chosen temporary paths when validating code
so established local outputs are not overwritten.

The semantic experiment functions are:

- `run_all_scenarios`;
- `run_oracle_delay_experiment`;
- `run_shock_severity_experiment`;
- `run_confidence_sensitivity_experiment`;
- `run_peg_recovery_experiment`;
- `run_multicollateral_experiment`.

There is no separate experiment workflow command or experiment YAML
configuration surface at this stage.

## Profiles

`config/profiles/legacy.yaml` preserves established defaults.
`config/profiles/empirical.yaml` opts into the complete empirical input
bundle. `config/profiles/empirical_stress.yaml` applies documented stress
selections without changing protocol constants silently.

Profiles are loaded through `dai_sim.inputs.configuration`; empirical market,
gas, vault and liquidation data are loaded from compact tracked pools under
the owning domain's `model_inputs/` directory.

## Empirical workflows

Use the semantic workflow paths, for example:

```bash
python workflows/market/acquire.py --help
python workflows/market/process.py --help
python workflows/gas/process.py --help
python workflows/vaults/build_inputs.py --help
python workflows/calibration/validate.py --help
```

Acquisition commands that contact Dune require explicit credentials and may
consume credits. Their documented `--help` interfaces and local validation
paths are safe; do not execute live acquisition without a bounded acquisition
authorisation. `workflows/liquidations/build_inputs.py` is a local builder but
does not expose an argparse help interface, so it is not listed as a help
command.

## Data boundaries

Raw and processed empirical payloads are generated locally and ignored by
Git. Compact runtime pools, selected manifests, SQL, workflows and checksum
records are tracked. Reproducing an ignored dataset requires the external
source, the relevant query or execution identifiers, and credentials where
the source requires them.

See [data acquisition](../data/acquisition.md),
[processing](../data/processing.md) and
[provenance](../data/provenance.md).

## Current and historical documentation

Active documentation describes the current repository. Phase- and
tranche-labelled reports under `docs/archive/` describe the repository at the
time of each empirical milestone; their paths and terminology may be
historical. The root entry points link to active semantic guidance.
