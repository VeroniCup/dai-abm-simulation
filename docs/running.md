# Running the code

Run commands from the repository root unless a command explicitly says
otherwise.

## Requirements

The package metadata supports Python 3.11, 3.12 and 3.13. Runtime dependencies
are NumPy, pandas, Matplotlib, PyYAML and SciPy. The test suite uses pytest. A standard
`venv` environment is sufficient; `environment.yml` is available as an
alternative for Conda users.

Once dependencies are installed, package imports, simulations and tests do not
require network access. Data-acquisition workflows are different: they may
contact an external service and may require credentials.

## Installation

Create and activate an isolated environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell use:

```powershell
.venv\Scripts\Activate.ps1
```

Install the project in editable mode and check its declared dependencies:

```bash
python -m pip install -e .[test]
python -m pip check
```

`pyproject.toml` is the authoritative dependency specification. The short
`requirements.txt` wrapper installs the same editable package and test extra
for tools that expect a requirements file.

Editable installation keeps imports pointed at the checked-out `src/` tree,
so a code change is visible without rebuilding a wheel. Run the commands from
the repository root: package path discovery deliberately requires
`pyproject.toml`, `src/dai_sim/` and `config/` to belong to the same archive.
The activation command must be repeated in each new shell.

For an offline archive where the dependencies and build tools are already
available to the active interpreter, use:

```bash
PIP_NO_INDEX=1 python -m pip install -e . --no-deps --no-build-isolation
```

A newly created isolated environment does not inherit packages from its base
interpreter. For an offline check that deliberately reuses an already
provisioned local environment, create it with
`python -m venv --system-site-packages .venv` before running the command above.
Otherwise, install the declared dependencies and `setuptools` from a local
wheelhouse first. Neither approach requires the archive to contact a package
index.

## Verify the installation

Compile the package, workflows and tests, then run the complete suite:

```bash
python -m compileall src workflows tests
pytest
```

The current expected result is 1,353 passed tests and one documented skip,
with no failures or collection errors. A later archive may report additional
passing tests when new software checks are added.

## Quick non-substantive check

The following command imports the installed package, loads the frozen
collateral registry and prints the three configured families. It does not run
a simulation or write output:

```bash
python -c "from dai_sim.inputs.multicollateral import load_final_collateral_registry; print([item.name for item in load_final_collateral_registry().families])"
```

Expected output:

```text
['ETH', 'WBTC', 'STABLE']
```

Profile files are under `config/profiles/`. `legacy.yaml` retains the
established defaults. The empirical profiles enable compact empirical inputs
or the integrated multi-collateral configuration. Sensitivity files are partial
overrides and should not be passed as complete profiles.

The registry check also verifies the normal content-addressed input path: the
loader resolves a tracked registry, validates it and returns typed objects.
It is therefore a useful installation check when running the full test suite
would be inconvenient, although it is not a replacement for those tests.

## Run a simulation

The simplest active simulation entry point is the model module itself:

```bash
python -m dai_sim.model.simulation
```

It constructs a fixed-seed ETH-only configuration with 100 vaults, applies a
deterministic shock over 100 hourly steps and prints rows around the shock and
the final state. It normally completes in seconds and does not save an
experiment dataset.

The module example is intentionally small. It demonstrates package imports,
vault initialisation, hourly state transitions and the result schema without
selecting an empirical profile. Repeated invocations use the same seed. For a
different horizon, population or price process, create a `SimulationConfig`
in a short Python program rather than editing the module example.

For programmatic use, import functions from `dai_sim.model.simulation`. The
main convenience functions cover constant prices, geometric Brownian motion,
an abrupt shock and a shock followed by recovery. Each accepts an explicit
`SimulationConfig`; liquidation and DAI-market settings are separate objects.

The established scenario runner is available through
`dai_sim.experiments.runner`, but its functions write detailed CSV files. Use
it only when generated output is intended.

## Run an experiment

Experiment workflows expose explicit operations and write resumable output.
Inspect the command surface before execution:

```bash
python workflows/experiments/final/idiosyncratic_diversification.py --help
```

A full invocation has the form:

```bash
python workflows/experiments/final/idiosyncratic_diversification.py run --workers 8
```

The worker count controls local parallelism. Final comparison matrices can be
computationally expensive and may run for many minutes. Their workflow also
provides preflight, smoke, resume, checkpoint-audit and evidence-reconstruction
operations. Do not delete or mix checkpoints between experiment identities.

Run `--help` before choosing an operation and use the preflight command where
the workflow provides one. A full `run` creates detailed, ignored output; it
is not needed to confirm that the package was installed successfully. Seed and
cell registries are owned by the workflow and should not be replaced with
ad-hoc command-line values.

Other registered experiment entry points are beside this file under
`workflows/experiments/final/`. Focused ETH recovery workflows are under
`workflows/experiments/mechanism/`.

## Outputs

Generated output is ignored by Git. The principal namespaces are:

```text
outputs/experiments/mechanism/   focused mechanism-study results
outputs/experiments/final/       registered comparison matrices
outputs/validation/              held-out evaluation output
outputs/diagnostics/             local checks and review material
outputs/figures/                 generated plots
outputs/tables/                  generated summaries
```

Compact evidence that accompanies the code is already tracked under
`data/provenance/`. Running an experiment should not overwrite that evidence
unless the relevant workflow and frozen configuration explicitly permit
reconstruction.

## Optional historical verification

The portable archive does not contain every full processed source or worker
checkpoint. If the separately retained historical artefact tree is available,
inspect the read-only verifier with:

```bash
python workflows/verification/verify_external_artifacts.py --help
```

The verifier requires an explicit external root. It checks recorded artefacts
without downloading replacements or modifying the supplied tree.

Historical verification is optional because the portable archive includes the
compact derivatives used by normal profiles. Supplying an external root does
not make that tree part of the package and does not copy its contents into the
repository.

## Troubleshooting

**Editable installation fails.** Confirm that the active interpreter is Python
3.11–3.13 and that build dependencies are available. Recreate the environment
if it contains an incompatible earlier installation.

**A dependency is missing.** Run `python -m pip check`, then install the
dependencies declared in `pyproject.toml`. Offline installation requires those
packages to be supplied locally in advance.

**The project root cannot be found.** Run the command from the archive root or
one of its subdirectories. A valid root contains `pyproject.toml`,
`src/dai_sim/` and `config/`.

**A reconstruction command requests a missing source.** Ordinary simulation
and tests use compact inputs. Full acquisition or historical reconstruction
requires the separately retained raw, processed or checkpoint files named by
the relevant provenance record.
