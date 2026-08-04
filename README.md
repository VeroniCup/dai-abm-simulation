# DAI agent-based simulation

## Project overview

This repository contains a Python simulation of DAI stability under market
stress. It models collateralised vaults, market and oracle prices, liquidation
eligibility, keeper execution, bad debt and a reduced-form DAI price response
at an hourly frequency. The software accompanies an MSc Computational Finance
dissertation and is intended for transparent mechanism analysis rather than
financial forecasting or operational use.

The established model is ETH-only. The multi-collateral extension adds WBTC
and a counterfactual stable-collateral proxy, while preserving one collateral
family per vault and one shared keeper queue. The stable proxy is a controlled
simulation component; it is not an empirical population of Maker USDC vaults.

## Key capabilities

- Hourly simulation of vault collateralisation, liquidation and DAI price
  adjustment.
- Legacy ETH-only and opt-in multi-collateral configurations.
- Empirical market blocks and controlled shock-and-recovery price paths.
- Collateral-specific prices, oracle lag, liquidation ratios and penalties.
- Keeper profitability checks, deterministic ranking and shared capacity
  constraints.
- Optional recovery and confidence scenarios without changing default
  behaviour.
- Repeated seeded comparisons with deterministic configuration and evidence
  checks.
- Compact runtime inputs and machine-readable provenance for portable testing.

The package keeps the simulation engine, empirical input adapters and workflow
entry points separate. This makes it possible to inspect a model mechanism in
isolation, select a complete configuration explicitly and direct generated
results to a known output namespace. Legacy interfaces remain available for
the established ETH-only examples, while newer profiles use the same core
accounting through typed multi-collateral inputs.

## Quick start

Python 3.11–3.13 is supported. Create an isolated environment and install the
package from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip check
```

On Windows PowerShell, activate the environment with
`.venv\Scripts\Activate.ps1`.

Run the complete test suite:

```bash
python -m compileall src workflows tests
pytest
```

The test suite covers model mechanics, input validation, experiment contracts,
portable runtime sources, SQL integrity and package structure.

## Run the model

The smallest built-in simulation example uses a fixed seed, 100 vaults and a
100-hour ETH shock path. It prints selected rows and does not write an
experiment dataset:

```bash
python -m dai_sim.model.simulation
```

Profiles and registered inputs can be checked without running a simulation:

```bash
python -c "from dai_sim.inputs.multicollateral import load_final_collateral_registry; print([item.name for item in load_final_collateral_registry().families])"
```

For profile selection, experiment workflows, output locations and optional
historical checks, see [Running the code](docs/running.md).

## Documentation

- [Repository structure](docs/repository_structure.md) describes the portable
  archive and generated-output layout.
- [Components](docs/components.md) explains the responsibility of each package
  and supporting directory.
- [Running the code](docs/running.md) provides installation, verification and
  execution commands.

The code documentation deliberately concentrates on software organisation and
operation. Scientific design, registered decisions and numerical evidence are
retained in machine-readable files under `data/provenance/` and are discussed
in the dissertation.

## Repository at a glance

```text
src/dai_sim/   Python package
config/        profiles, protocol settings and sensitivity registries
data/          compact model inputs and provenance
workflows/     executable entry points
sql/           query templates and retained historical queries
tests/         unit, integration and scientific-contract tests
docs/          software documentation
```

Generated results are written under `outputs/` in a development checkout and
are ignored by Git. Source code, compact inputs and compact evidence remain
separate from these generated files.

## Reproducibility boundary

The portable archive includes the compact runtime inputs and evidence needed
for ordinary installation, imports and tests. Full processed datasets,
historical worker checkpoints, diagnostics and generated figures are not
included. Once dependencies are installed, ordinary use requires no network
access. Separately retained historical artefacts can be checked with the
read-only verifier described in the [running guide](docs/running.md), but they
are not required by the normal test suite.

## Academic use

This repository accompanies an academic dissertation. Its outputs are research
artefacts rather than financial advice.
