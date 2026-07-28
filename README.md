# DAI ABM simulation

This repository contains an interpretable agent-based simulation of DAI
stability under market stress. It studies collateral shocks, vault leverage,
oracle delay, liquidation frictions, keeper incentives and capacity, gas
costs, bad debt, confidence and DAI peg recovery. ETH, BTC and stable
collateral classes can coexist, while the established ETH-only model remains
the default compatibility path.

The model is a dissertation research framework, not a full implementation of
MakerDAO and not financial advice.

## Repository map

- [Repository guide](docs/overview/repository_guide.md)
- [Architecture](docs/overview/architecture.md)
- [Model mechanics](docs/model/README.md)
- [Empirical research design](empirical.md)
- [Parameter methodology](parameters.md)
- [Calibration documentation](docs/calibration/README.md)
- [Experiment documentation](docs/experiments/README.md)
- [Data acquisition and provenance](docs/data/acquisition.md)
- [Validation and regression baselines](docs/validation/regression.md)
- [Current project status](PROJECT_STATUS.md)

The authoritative Python package is `src/dai_sim/`. User-facing profiles are
under `config/profiles/`; domain workflows are under `workflows/`; empirical
data are owned by `data/market/`, `data/gas/`, `data/vaults/`,
`data/liquidations/` and `data/protocol/`; SQL is organised under the same
domains.

## Installation

From the repository root, using Python 3.11–3.13:

```bash
python -m pip install -e .
```

## Running

The supported simulation interface is the Python API:

```python
from dai_sim.experiments.runner import run_all_scenarios

results, summary = run_all_scenarios()
```

Established scenarios and experiment-specific functions are documented in
[the experiment guide](docs/experiments/README.md). The repository does not
currently provide an installed console command or a separate experiment
workflow directory.

## Profiles and empirical inputs

`config/profiles/legacy.yaml` preserves established defaults.
`config/profiles/empirical.yaml` enables the complete opt-in empirical bundle,
and `config/profiles/empirical_stress.yaml` selects documented stress inputs.
Raw and processed data are generated locally and ignored by Git; compact
runtime pools and durable provenance are tracked.

Live acquisition may require a Dune API key and consumes external credits.
Local processing, model-input validation and simulation do not require Dune.
See the [data guide](docs/data/acquisition.md) for reproducibility boundaries.
