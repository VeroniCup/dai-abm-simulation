# Components

## `src/dai_sim/model`

The model package contains the simulation's economic state and transition
functions. `simulation.py` coordinates hourly updates and produces system and
collateral-level records. Its `SimulationConfig` controls the horizon, vault
population, initial prices, liquidation threshold, oracle delay and random
seed.

`collateral.py` defines collateral families and portfolio composition.
`collateral_prices.py` constructs aligned market and oracle paths, including
constant, stochastic, shock and recovery paths. Oracle lag is applied to the
price used by the protocol without replacing the contemporaneous market price.

`vault.py` creates and updates one-collateral vault positions. It calculates
collateral value and collateralisation from the relevant collateral price.
`liquidation.py` identifies eligible positions, estimates keeper economics,
ranks candidates deterministically and applies execution constraints. It keeps
liquidation, unresolved backlog and bad debt as separate quantities.

`confidence.py` supplies optional confidence and panic states. `market.py`
updates the reduced-form DAI price from demand, supply, stress and recovery
terms. `metrics.py` contains reusable summaries. These modules are composed by
the simulation engine rather than called through separate services.

## `src/dai_sim/inputs`

The inputs package turns files into validated Python objects. Configuration
loaders combine a complete profile with explicitly requested sensitivity
overrides and reject unknown fields. Separate loaders handle market blocks,
gas, vault initialisation, liquidation arrivals, keeper settings, oracle delay
and multi-collateral registries.

Portable runtime resolution maps large historical sources to compact tracked
files. A loader checks the expected content hash before using a compact source.
When an optional full source is present, its recorded hash is checked as well;
there is no network or user-home fallback. This keeps ordinary package use
independent of the complete research-data workspace.

## `src/dai_sim/calibration`

The calibration package contains estimators, statistical summaries,
identification checks and compact evidence construction. It includes utilities
for market and gas blocks, vault distributions, liquidation behaviour, keeper
execution, oracle-delay evidence and confidence diagnostics.

These modules are research tools, not requirements for an ordinary simulation
using an existing profile. They read explicit inputs and write evidence through
their workflows. They do not silently alter a profile or make a candidate value
a runtime default.

## `src/dai_sim/experiments`

The experiment package contains established scenario factories and repeated
comparison code. `runner.py`, `scenarios.py`, `summaries.py` and `plots.py`
support the earlier ETH-only interfaces and the multi-collateral runner.

`experiments/mechanism/` contains focused recovery studies.
`experiments/final/` contains the registered portfolio, shared-capacity,
oracle-delay and robustness comparisons. Experiment modules use fixed cell and
seed registries, common random numbers where appropriate, deterministic
checkpoint keys and compact evidence writers.

Detailed result rows and checkpoints are generated under `outputs/` and are not
part of the portable archive. Compact CSV and JSON evidence needed to inspect
the registered calculations is tracked under `data/provenance/`.

## `src/dai_sim/validation`

The validation package checks frozen inputs and evaluates the model against
held-out market windows. It verifies profile consistency, collateral
composition, source boundaries, negative controls and output accounting.

Validation has no route for updating model parameters or configurations. The
code checks that evaluation data stay outside calibration and that reported
evidence can be reconstructed deterministically. Detailed validation output is
generated separately from experiment output.

## `src/dai_sim/common`

The common package contains small infrastructure shared across scientific
modules. `paths.py` finds the project root from stable layout markers and keeps
resolved paths inside it. `serialization.py` supplies deterministic conversion
and encoding helpers. `submission_bundle.py` validates the include and exclude
manifests, copies the selected files atomically and verifies their content
manifest.

Checkpoint and evidence helpers that are specific to one study remain beside
that study rather than accumulating in the common package.

## `workflows`

Workflows are executable entry points. They bootstrap the installed package and
then call the corresponding package functions. Market, gas, vault, liquidation
and protocol directories contain acquisition or processing commands. The
inputs directory builds and validates compact inputs. Calibration, experiment
and validation directories expose their respective operations.

Direct workflow execution uses the same stable repository-layout markers as
the installed package: `pyproject.toml`, `src/dai_sim/` and `config/`. It does
not depend on version-control metadata or a particular documentation file.

`workflows/verification/` contains the optional read-only command for checking
separately retained historical artefacts. It requires an explicit external
root and neither downloads nor modifies artefacts. Internal bundle-construction
tools are not part of the portable archive.

Most complex workflows provide `--help` and an explicit command such as
`preflight`, `run`, `resume` or `validate-completed`. Acquisition commands can
contact external services and should not be confused with local simulation
commands.

## `config`

`config/profiles/` contains complete profiles. The legacy profile preserves
the established default model; empirical profiles opt into compact empirical
inputs. `config/protocol/` records collateral definitions and protocol
parameters. `config/sensitivities/` contains partial overrides and controlled
treatment registries. `config/validation/` defines held-out windows.

`config/submission/` contains packaging manifests and the runtime input map.
These files determine archive membership and compact source resolution; they
do not change the model equations.

## `data`

Tracked model inputs include empirical market blocks, vault initialisation
pools, liquidation-arrival and keeper-gas pools, protocol registries and
held-out path derivatives. Tracked provenance includes source inventories,
checksums, compact decisions and reproducibility records.

Raw provider responses, complete processed panels and detailed checkpoints are
excluded because they are large and unnecessary for ordinary imports and
tests. They can be supplied separately for optional historical reconstruction.

## `tests`

Model tests cover collateral, vault, price, liquidation, confidence and market
behaviour. Input tests validate profiles, registries and compact sources.
Calibration, experiment and validation tests check their calculations and
evidence contracts. Workflow tests cover command handling, persistence and
resume behaviour. Integration tests protect package discovery, repository
paths, SQL content, documentation links, output separation and archive
portability.

Fixed seeds and temporary fixtures keep tests repeatable. The suite does not
depend on a local output cache or a network connection.

## `sql`

SQL files are grouped by the same empirical domains as the data. Templates are
the maintained query sources; generated files record bounded historical
queries. They are included so acquisition logic can be inspected even though
query execution and large results are outside the archive. The simulation
runtime does not issue SQL queries.
