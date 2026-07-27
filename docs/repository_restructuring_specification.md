# Maker-facing repository restructuring specification

## Status and scope

This document defines the approved target architecture for the next dedicated
repository restructuring. It is implementation-ready, but the architecture has
not yet been implemented. Current paths remain authoritative until their
migration stage is explicitly authorised and completed.

The restructuring is behaviour-neutral. It must not change economic equations,
parameter values, random seeds, empirical observations, data checksums, Dune
query semantics, or the established outputs of Experiments 1–5.

The complete file-level plan is in
[`repository_restructuring_path_map.csv`](repository_restructuring_path_map.csv).
The current import and path-reference surface is in
[`repository_restructuring_reference_inventory.csv`](repository_restructuring_reference_inventory.csv).

## Current-state summary

The design inventory contains:

- 255 files tracked in `HEAD`;
- 14 intended untracked Tranche D files;
- 10 important ignored path groups;
- 28 current or intended source modules, mapping to 31 proposed package
  modules after the approved splits;
- 27 current or intended workflow scripts;
- 117 tracked SQL files, including 97 generated SQL files;
- 13 tracked documents under `docs/`, one intended Tranche D report, and five
  durable root documents;
- 21 tracked test modules, one intended Tranche D test, and five tracked
  fixtures;
- a 2,261-row reference inventory covering Python imports, literal paths,
  dynamic path operations, Markdown links, and ignore rules.

The reference inventory is a migration-baseline snapshot. It includes the
authorised `AGENTS.md` addition but deliberately excludes the three
restructuring-design artefacts themselves; indexing the path map and reference
inventory would create self-referential rows without identifying a migration
consumer.

The repository is operational, but its public navigation reflects development
chronology. Phase- and tranche-labelled configurations, reports, scripts, SQL,
and tests obscure the five substantive Maker-facing domains. Runtime model
inputs also sit under `config/empirical/data/`, while raw, processed, and
provenance data are organised lifecycle-first. The target makes domain the
first navigation decision and lifecycle the repeated second decision.

## Approved design principles

1. **Domain first.** Market, gas, vaults, liquidations, and protocol are the
   primary empirical domains.
2. **Lifecycle consistency.** Every data domain repeats `raw/`, `processed/`,
   `model_inputs/`, and `provenance/`.
3. **Semantic active names.** Active names describe purpose. Development
   chronology is not an interface.
4. **Symmetry.** Equivalent domains use equivalent data, workflow, SQL, test,
   and documentation patterns.
5. **Archived history.** Phase, tranche, attempt, repair, and diagnostic-history
   labels may remain in Git history, provenance, and `docs/archive/`, not in
   active navigation.
6. **Behavioural neutrality.** Structural migration and behavioural changes
   are separate commits and separate reviews.
7. **No empty architecture theatre.** A target directory or module is created
   only when a current responsibility is migrated into it.

## Final target tree

```text
dai-abm-simulation/
├── README.md
├── PROJECT_STATUS.md
├── AGENTS.md
├── empirical.md
├── parameters.md
├── pyproject.toml
├── environment.yml
├── requirements.txt
├── src/
│   └── dai_sim/
│       ├── __init__.py
│       ├── model/
│       │   ├── __init__.py
│       │   ├── collateral.py
│       │   ├── vault.py
│       │   ├── liquidation.py
│       │   ├── market.py
│       │   ├── collateral_prices.py
│       │   ├── confidence.py
│       │   ├── simulation.py
│       │   └── metrics.py
│       ├── inputs/
│       │   ├── __init__.py
│       │   ├── configuration.py
│       │   ├── sources.py
│       │   ├── environment.py
│       │   ├── market.py
│       │   ├── gas.py
│       │   ├── vaults.py
│       │   ├── liquidations.py
│       │   └── protocol.py
│       ├── calibration/
│       │   ├── __init__.py
│       │   ├── data_loading.py
│       │   ├── statistics.py
│       │   ├── market.py
│       │   ├── gas.py
│       │   ├── vaults.py
│       │   ├── liquidations.py
│       │   ├── protocol.py
│       │   ├── adoption.py
│       │   └── validation.py
│       ├── experiments/
│       │   ├── __init__.py
│       │   ├── scenarios.py
│       │   ├── runner.py
│       │   ├── summaries.py
│       │   └── plots.py
│       └── common/
│           ├── __init__.py
│           ├── paths.py
│           ├── random.py
│           ├── validation.py
│           └── provenance.py
├── config/
│   ├── profiles/
│   │   ├── legacy.yaml
│   │   ├── empirical.yaml
│   │   └── empirical_stress.yaml
│   ├── experiments/
│   │   ├── baseline.yaml
│   │   ├── oracle_delay.yaml
│   │   ├── shock_severity.yaml
│   │   ├── confidence.yaml
│   │   ├── peg_recovery.yaml
│   │   └── multi_collateral.yaml
│   ├── sensitivities/
│   │   ├── market/
│   │   ├── gas/
│   │   ├── vaults/
│   │   └── liquidations/
│   └── protocol/
│       ├── collateral_types.csv
│       └── parameters.yaml
├── data/
│   ├── provenance/
│   │   ├── index.json
│   │   └── data_manifest.csv
│   ├── market/
│   │   ├── raw/
│   │   ├── processed/
│   │   ├── model_inputs/
│   │   └── provenance/
│   ├── gas/
│   │   ├── raw/
│   │   ├── processed/
│   │   ├── model_inputs/
│   │   └── provenance/
│   ├── vaults/
│   │   ├── raw/
│   │   ├── processed/
│   │   ├── model_inputs/
│   │   └── provenance/
│   ├── liquidations/
│   │   ├── raw/
│   │   ├── processed/
│   │   ├── model_inputs/
│   │   └── provenance/
│   └── protocol/
│       ├── raw/
│       ├── processed/
│       ├── model_inputs/
│       └── provenance/
├── workflows/
│   ├── market/
│   ├── gas/
│   ├── vaults/
│   ├── liquidations/
│   ├── protocol/
│   ├── inputs/
│   ├── calibration/
│   ├── experiments/
│   └── maintenance/
├── sql/
│   ├── market/{templates,generated}/
│   ├── gas/{templates,generated}/
│   ├── vaults/{templates,generated}/
│   ├── liquidations/{templates,generated}/
│   └── protocol/{templates,generated}/
├── docs/
│   ├── overview/
│   ├── model/
│   ├── calibration/
│   ├── experiments/
│   ├── data/
│   ├── validation/
│   └── archive/
│       ├── phase_reports/
│       ├── tranche_reports/
│       └── historical_plans/
├── tests/
│   ├── model/
│   ├── inputs/
│   ├── calibration/
│   ├── experiments/
│   ├── workflows/
│   ├── integration/
│   └── fixtures/
└── outputs/
    ├── experiments/
    ├── diagnostics/
    ├── figures/
    └── tables/
```

`pyproject.toml` is part of the final package design, but it is not created
during this documentation task. It belongs to the source-package migration
stage.

## Target-path review

The tree is a design boundary rather than a demand to create placeholders.
“Immediate” below means the path should be populated in the named migration
stage, not during this design task.

| Target path | Purpose and current sources | Immediate / package | Combination, collision, and runtime consequence |
|---|---|---|---|
| `src/dai_sim/` | Installable project namespace for all current `src/` modules. | Stage 2; `__init__.py` required. | Changes every internal import; requires temporary import compatibility and a package configuration. |
| `src/dai_sim/model/` | Economic model from collateral, vault, liquidation, DAI market, price process, confidence, simulation, and metrics. | Stage 3; `__init__.py` required. | `dai_market.py` and `price_process.py` receive distinct semantic names; public behaviour is unchanged. |
| `src/dai_sim/inputs/` | Configuration, source adaptation, environment composition, and domain runtime-input loaders. | Stage 3; `__init__.py` required. | Combines the present empirical input surface without merging domain responsibilities. |
| `src/dai_sim/calibration/` | Statistical estimation, reviews, and adoption decisions from `src/estimation/` and calibration parts of `empirical_data.py`. | Stage 3; `__init__.py` required. | `phase2a.py` is split by domain; split needs output-equivalence tests. |
| `src/dai_sim/experiments/` | Scenario definitions, execution, summaries, and plots from `experiments.py` and `plot_results.py`. | Stage 3; `__init__.py` required. | Splits a large module; established experiment entry points require temporary wrappers. |
| `src/dai_sim/common/` | Shared paths, validation, provenance, and possibly random helpers. | Only when a real shared responsibility is extracted; `__init__.py` required. | Must not become a generic dumping ground; no placeholder files. |
| `config/profiles/` | Complete user-facing legacy, empirical, and empirical-stress bundles. | Stage 4; no `__init__.py`. | Merges cumulative phase/tranche YAML only after value equivalence; changes loader paths, not values. |
| `config/experiments/` | Named scenario inputs for the six established experiments. | Stage 4 only for experiments with an actual external configuration; no `__init__.py`. | Do not extract code constants merely to fill the tree; extraction needs separate behavioural review. |
| `config/sensitivities/<domain>/` | Partial domain overrides replacing chronology-labelled sensitivity names. | Stage 4; no `__init__.py`. | Requires an explicit, tested override contract; sensitivities are not standalone profiles. |
| `config/protocol/` | Collateral-type mapping and fixed protocol-data configuration. | Stage 4; no `__init__.py`. | CSV-to-YAML conversion is not required; content format remains unchanged unless separately authorised. |
| `data/<domain>/raw/` | Authoritative acquired observations from current `data/raw/<domain>/`. | Stage 5; no `__init__.py`. | Large ignored files move domain by domain; manifests and content hashes gate each move. |
| `data/<domain>/processed/` | Reproducible transformed datasets from current `data/processed/<domain>/`. | Stage 5; no `__init__.py`. | Processing paths and path-sensitive metadata change; observed values must not. |
| `data/<domain>/model_inputs/` | Compact tracked runtime pools currently under `config/empirical/data/`. | Stage 4; no `__init__.py`. | Loader defaults and profile paths change atomically; content checksums must remain identical. |
| `data/<domain>/provenance/` | Domain manifests, metadata, validation, state, and checksum records. | Stage 5; no `__init__.py`. | Embedded paths make this higher-risk than a plain move; update and validate atomically. |
| `data/provenance/` | Cross-domain index and authoritative data manifest only. | Stage 5; no `__init__.py`. | Retains a narrow cross-domain exception; it must not absorb domain metadata. |
| `workflows/<domain>/` | Active acquisition, processing, reconstruction, input-building, and validation CLIs from `scripts/`. | Stage 6; no `__init__.py` initially. | Duplicate CLIs merge only after flag and failure-semantics comparison. |
| `workflows/calibration/` | Thin calibration entry points for `dai_sim.calibration`. | Stage 6; no `__init__.py` initially. | Business logic remains importable; CLIs do not become a second implementation. |
| `workflows/experiments/` | User-facing experiment runner. | Stage 6 when a real runner moves; no placeholder. | Must preserve Experiments 1–5 commands and output identity. |
| `workflows/maintenance/` | Generic result retrieval and archived one-off discovery/repair tools. | Stage 6; no `__init__.py`. | Historical scripts are not active APIs; preserve provenance and bounded safety controls. |
| `sql/<domain>/templates/` | Hand-maintained parameterised SQL. | Stage 7; no `__init__.py`. | Manifest SQL paths and checksums require controlled updates. |
| `sql/<domain>/generated/` | Deterministic instances and historical executed SQL. | Stage 7; no `__init__.py`. | May become ignored only after byte-identical regeneration is proven. |
| `docs/<purpose>/` | Active reader guides, model, calibration, data, experiment, and validation documents. | Stage 8; no `__init__.py`. | Consolidation must precede archival so no historical content is lost. |
| `docs/archive/` | Phase reports, tranche reports, and historical plans. | Stage 8; no `__init__.py`. | Historical labels are valid here; links and provenance references need updating. |
| `tests/<concern>/` | Semantic tests and fixtures replacing chronology-labelled test names. | Stage 9; packages not required unless relative fixtures later justify them. | Move after imports stabilise; test collection count must not fall. |
| `outputs/<kind>/` | Ignored experiments, diagnostics, figures, and tables. | Stage 10; no `__init__.py`. | Existing output hashes and results/figures separation must be preserved. |

### Package directories

`src/dai_sim/` and its five Python subpackages require `__init__.py` files.
Their creation is deferred until responsibilities move into them. `workflows/`
contains executable entry points rather than importable business logic and does
not require package initialisers unless later exposed as console-script modules.
Data, SQL, configuration, documentation, test, and output directories do not
require `__init__.py`.

### Direct moves, splits, and merges

| Current responsibility | Target | Action and consequence |
|---|---|---|
| `collateral.py`, `vault.py`, `liquidation.py`, `confidence.py`, `simulation.py`, `metrics.py` | `dai_sim.model` | Move with package-qualified imports; retain public behaviour. |
| `dai_market.py` | `dai_sim.model.market` | Rename; this is the endogenous DAI market. |
| `price_process.py` | `dai_sim.model.collateral_prices` | Rename to avoid colliding with the endogenous DAI market. |
| `empirical_config.py` | `dai_sim.inputs.configuration` | Rename; centralise profile parsing without changing values. |
| `empirical_sources.py` | `dai_sim.inputs.sources` | Move and rename; source adaptation remains cross-domain. |
| `environment_inputs.py` | `dai_sim.inputs.environment` | Move and rename; remains the composition boundary. |
| `market_bootstrap.py`, `gas_process.py`, `vault_initialisation.py`, `liquidation_demand.py`, `protocol_data.py` | corresponding `dai_sim.inputs` modules | Move and rename; class names need not change during structural migration. |
| `empirical_data.py` | `calibration/market.py` and `inputs/market.py` | Split estimation from loading/adaptation. Split only after characterisation tests. |
| `src/estimation/phase2a.py` | `calibration/market.py`, `gas.py`, and `protocol.py` | Split by output domain; common orchestration remains in a small runner. |
| `phase2b_vaults.py`, `phase2c_liquidations.py` | `calibration/vaults.py`, `liquidations.py` | Move and rename. |
| `phase2a_review.py` | `calibration/validation.py` | Rename; chronology disappears from the active API. |
| `adoption_review.py`, `data_loading.py`, `statistics.py` | semantic names under `calibration/` | Move without changing statistical behaviour. |
| `experiments.py` | `experiments/scenarios.py`, `runner.py`, `summaries.py` | Split the current large orchestration module. |
| `plot_results.py` | `experiments/plots.py` | Move and rename. |

The package contains 28 current or intended modules to migrate, producing 31
proposed package modules after the approved splits. No module is deleted before
the compatibility and regression stage.

### Common package

`common/paths.py`, `validation.py`, and `provenance.py` should be introduced
only by extracting genuinely shared code encountered during migration.
`common/random.py` is created only if seed handling is found in three or more
domains. This prevents a generic utility layer from becoming a dumping ground.

## Naming policy

### Active names

Active names state purpose and use lower-case snake case. They must not contain
`phase1`, `phase2`, `tranche_a`, `tranche_b`, `attempt2`, `final_v3`, or
`repair_latest`. Dates and chunk identifiers are permitted for generated
acquisition artefacts because they identify bounded coverage rather than
development chronology.

### Domain names

Use `market`, `gas`, `vaults`, `liquidations`, and `protocol` for domain
directories. Use singular Python model nouns (`vault.py`, `liquidation.py`,
`market.py`) and plural empirical collection modules where appropriate
(`inputs/vaults.py`, `inputs/liquidations.py`).

### Workflow verbs

Use only `acquire`, `process`, `reconstruct`, `build_inputs`, `calibrate`,
`validate`, and `run` as primary active workflow verbs. Discovery, repair, and
one-off recovery utilities move to `workflows/maintenance/archive/` after their
provenance value is recorded.

### Historical labels

Phase and tranche labels are retained only in `docs/archive/`, historical
provenance, deterministic historical SQL, and Git history. Newly generated
active paths must not use them.

## Configuration redesign

The user-facing surface consists of three complete profiles:

- `legacy.yaml`: current established defaults, synthetic/Gaussian vault
  initialisation, endogenous legacy price and gas behaviour, and the ETH-only
  compatibility path unless an experiment supplies a portfolio;
- `empirical.yaml`: the current cumulative Tranche A–D content—audited
  configuration candidates, empirical joint vault initialisation, aligned
  market-return blocks, component gas, and empirical liquidation-arrival
  demand;
- `empirical_stress.yaml`: the empirical profile with explicitly documented
  stress selections, such as stress pools or upper-tail regimes. It must not
  silently alter protocol constants.

Profiles should initially be complete, materialised YAML files. Runtime profile
inheritance must not be introduced in the structural migration because it would
change configuration semantics. A later, separately reviewed enhancement may
support composition with a documented deep-merge contract. Sensitivity files
are intentionally partial overrides and should be applied explicitly by the
runner. Duplicate cumulative YAML is eliminated only after equivalence tests
show that `empirical.yaml` reproduces the latest cumulative bundle.

### Sensitivity mapping

| Current semantic purpose | Final active path |
|---|---|
| 100- and 1,000-vault bounds | `config/sensitivities/vaults/population_100.yaml`, `population_1000.yaml` |
| legacy Gaussian and truncated parametric initialisation | `config/sensitivities/vaults/legacy_gaussian.yaml`, `parametric_truncated.yaml` |
| 72- and 336-hour market blocks | `config/sensitivities/market/block_72h.yaml`, `block_336h.yaml` |
| high-q90 and zero-inclusive gas | `config/sensitivities/gas/high_q90.yaml`, `zero_inclusive.yaml` |
| legacy scalar gas | `config/sensitivities/gas/legacy_scalar.yaml` |
| low/high liquidation hurdle | `config/sensitivities/liquidations/hurdle_low.yaml`, `hurdle_high.yaml` |
| low/high keeper capacity | `config/sensitivities/liquidations/capacity_low.yaml`, `capacity_high.yaml` |
| legacy all-eligible demand | `config/sensitivities/liquidations/legacy_demand.yaml` |

The four cumulative `phase2_empirical_*.yaml` files are superseded by the three
profiles after equality tests. They are archived for one migration stage and
then deleted after validation. The high/low Tranche A files are not duplicate
profiles; they become the two vault-population sensitivities. The Tranche A
manifest becomes parameter-adoption provenance rather than configuration.

## Data redesign

The domain-first mapping is mechanical:

```text
data/raw/<domain>/         -> data/<domain>/raw/
data/processed/<domain>/   -> data/<domain>/processed/
data/provenance/<domain>/  -> data/<domain>/provenance/
```

The cross-domain index and authoritative data manifest remain at
`data/provenance/`. They point into each domain but do not own domain records.

Compact runtime inputs move as complete dataset units:

- aligned market and gas block pool:
  `data/market/model_inputs/environment_blocks/{pool.csv,manifest.json}`;
- liquidation-specific gas pool:
  `data/liquidations/model_inputs/keeper_gas/{pool.csv,manifest.json}`;
- vault initialisation pool:
  `data/vaults/model_inputs/initialisation/{pool.csv,manifest.json}`;
- liquidation-arrival pools:
  `data/liquidations/model_inputs/arrival/{hourly_pool.csv,sequence_pool.csv,manifest.json}`.

The aligned market–gas processed panel and runtime block pool are market-owned
because market block sampling defines their row identity and alignment. Network
gas-only panels remain gas-owned. Liquidation transaction gas remains
liquidation-owned because its sampling unit is a liquidation transaction.
This is an explicit ownership rule, not a `shared/` exception.

Raw and processed datasets remain ignored by default. Compact model inputs that
are required at runtime remain tracked. Their associated manifests are tracked.

## Provenance rules

Each domain uses stable names:

- `manifest.json`: authoritative inventory and source identifiers;
- `metadata.json`: acquisition or transformation context;
- `validation.json`: validation result;
- `state.json`: resumable execution state;
- `checksums.json`: content-checksum registry where multiple artefacts exist.

Tracked provenance comprises the cross-domain index, the authoritative compact
manifests, query/execution identifiers needed for reproduction, and checksums
for ignored data. Detailed per-page payloads, transient states, validation
outputs, and local paths remain ignored. Historical failed attempts remain
under a domain `provenance/archive/` only where they document credit use,
failure handling, or an irreproducible execution. Existing provenance is not
renamed until its path-bearing fields can be updated atomically.

## Workflow redesign

All 27 current or intended scripts are mapped in the path map. The active
surface is:

| Domain | Active workflows |
|---|---|
| market | `acquire.py`, `process.py`, `build_inputs.py`, `validate.py` |
| gas | `acquire.py`, `process.py`, `validate.py` |
| vaults | `acquire.py`, `reconstruct.py`, `build_inputs.py`, `validate.py` |
| liquidations | `acquire.py`, `reconstruct.py`, `build_inputs.py`, `validate.py` |
| protocol | `acquire.py`, `process.py`, `validate.py` |
| calibration | `market_gas_protocol.py`, `vaults.py`, `liquidations.py`, `adoption.py`, `validate.py` |
| inputs | `validate_vaults.py`, `validate_environment.py`, `validate_liquidations.py` |
| maintenance | `retrieve_result.py` plus archived discovery, diagnostic, and repair tools |

Current duplicate acquisition entry points for protocol and vaults merge only
after their CLI flags are inventoried. Frequently used current commands receive
temporary wrappers with deprecation messages for one stage. One-off repair and
attempt-specific scripts are archived, not exposed as active commands.

## SQL redesign

The 117 tracked SQL files map to a domain and one of two roles:

- `templates/`: hand-maintained parameterised SQL used by an active workflow;
- `generated/`: deterministic query instances, ignored by default after the
  generator and checksum recording are validated.

The market and gas hourly queries become active templates. Phase 1D module
queries become protocol templates; diagnostic queries become historical
generated SQL. Phase 1E mutation, ownership, rate, and linkage SQL becomes vault
templates. The 77 liquidation generated files and 20 vault generated files
remain represented individually in the path map. Historical phase/attempt names
may remain inside a `generated/history/` provenance boundary, but newly
generated files use semantic dataset and coverage names.

Generated SQL may become ignored only after:

1. its generator is deterministic;
2. template and parameter checksums are recorded;
3. every query and execution identifier remains discoverable;
4. regeneration produces byte-identical SQL.

## Documentation redesign

The active documentation set is organised by reader purpose:

- `overview/`: architecture, repository guide, and research design;
- `model/`: mechanics by model concern;
- `calibration/`: market/gas, vault, liquidation, protocol, parameter
  estimation, and adoption;
- `experiments/`: one document per established experiment;
- `data/`: acquisition, processing, and provenance;
- `validation/`: regression, withheld-FTX validation, and robustness;
- `archive/`: phase reports, tranche reports, and historical plans.

The three active current documents—parameter adoption, parameter estimation,
and representative vault calibration—move into `docs/calibration/`. Phase
reports move to `docs/archive/phase_reports/`; Tranche A–D reports move to
`docs/archive/tranche_reports/`. `data/DATA_ACQUISITION_PLAN.md` eventually
moves unchanged into `docs/archive/historical_plans/`, but it is protected and
is not changed in this task. Its active conclusions must first be consolidated
into `docs/data/acquisition.md`.

`README.md`, `PROJECT_STATUS.md`, `AGENTS.md`, `empirical.md`, and
`parameters.md` remain durable root entry points. They become concise indexes
to the detailed documents rather than historical logs.

## Test redesign

The 22 current or intended test modules map semantically:

- Dune acquisition, diagnostics, production, and processing tests go under
  `tests/workflows/<domain>/`;
- configuration and runtime-input tests go under `tests/inputs/`;
- estimation and adoption tests go under `tests/calibration/`;
- existing model tests, when added, go under `tests/model/`;
- end-to-end profile and Experiments 1–5 equivalence tests go under
  `tests/integration/`;
- the five current fixtures remain under `tests/fixtures/`, grouped by domain.

Test filenames describe behaviour, not phases or tranches. Test moves occur
after package imports are stable so discovery failures are not conflated with
source-package failures. No historical-tooling test is removed until the
corresponding archived workflow has either a retained test or a recorded
retirement decision.

## Output redesign

Generated outputs use:

```text
outputs/experiments/<experiment>/
outputs/figures/<experiment>/
outputs/diagnostics/<domain-or-workflow>/
outputs/tables/<study-or-experiment>/
```

Experiment names are `baseline`, `oracle_delay`, `shock_severity`,
`confidence`, `peg_recovery`, and `multi_collateral`. Numeric prefixes are
removed from the active interface because names are already unique and order is
documented. Results and figures remain separate. Existing output checksums are
preserved until path migration and are compared before old paths are retired.

## Collision and ambiguity resolutions

| Collision | Resolution |
|---|---|
| `market.py` could mean endogenous DAI pricing or exogenous collateral prices | `model/market.py` is the DAI market; `model/collateral_prices.py` is the exogenous price process; `inputs/market.py` is empirical input construction. |
| `liquidation.py` could mean mechanics or empirical demand | `model/liquidation.py` contains mechanics; `inputs/liquidations.py` contains empirical arrival/cost inputs; `calibration/liquidations.py` estimates candidates. |
| Many `validate.py` files | Their parent domain is the namespace. Shared pure assertions alone may move to `common/validation.py`. |
| Protocol configuration versus protocol calibration | `config/protocol/` stores fixed configuration; `inputs/protocol.py` loads data; `calibration/protocol.py` estimates or reconstructs candidates. |
| Combined market/gas ownership | Market owns aligned environment blocks; gas owns network gas panels; liquidations own transaction-specific gas. |
| Two protocol and two vault acquisition scripts | Merge by domain after CLI-equivalence tests; do not silently drop flags. |
| `experiments.py` combines scenarios, execution, and summaries | Split into three semantic modules, with plotting separate. |
| `phase2a.py` spans three calibration domains | Split by produced parameter domain and retain a thin orchestration entry point. |

No semantic collision remains unresolved. Any implementation discovery that
invalidates these ownership rules is a stop condition requiring specification
amendment.

## Compatibility policy

The target is a clean active structure, not permanent aliases.

Temporary compatibility is allowed for:

- old flat-module imports while call sites migrate;
- frequently used script commands;
- old configuration entry points;
- durable external documentation links.

Every shim must have an owner, deprecation message, removal stage, and
characterisation test. Import shims are removed in stage 11 after all internal
imports and tests use `dai_sim`. Old script wrappers are removed after one
documented release or milestone. Configuration aliases are removed after
profile-equivalence tests. Data-path aliases are not created; manifests and
consumers migrate atomically.

## Checksum and manifest policy

Four checksum classes are treated differently:

1. **Content checksum:** unchanged by `git mv`; verify before and after every
   data or runtime-input move.
2. **Path-sensitive metadata checksum:** changes when embedded paths change;
   regenerate deterministically and record both old and new checksums.
3. **Generated-output checksum:** should remain unchanged for behaviour-neutral
   code migration; compare substantive outputs independently of metadata paths.
4. **Regression-output checksum:** Experiments 1–5 and empirical diagnostic
   baselines must remain unchanged unless separately authorised.

Path-bearing manifests, YAML, metadata JSON, Markdown, SQL registries, scripts,
 and tests are enumerated in the reference inventory. No old data path is
removed until the authoritative manifest resolves the new path, the content
hash matches, and a reverse lookup from query/execution identifier succeeds.

## Migration stages and commit sequence

Each stage is a dedicated reviewable commit on one restructuring branch.

| Stage | Scope and dependencies | Validation and stop condition |
|---|---|---|
| 1. Freeze checkpoint | Record HEAD, working-tree exclusions, profile hashes, pool hashes, and Experiments 1–5 checksums. | Stop if the baseline is not reproducible. |
| 2. Package/path infrastructure | Add `pyproject.toml`, `dai_sim` package skeleton only where populated, and central path tests. | Import smoke; no runtime consumer changes. |
| 3. Source package | Use `git mv`; migrate model, inputs, calibration, experiments; add temporary import shims. | `compileall`, full `pytest`, module smoke tests, ETH-only equivalence, experiment checksums. |
| 4. Configuration and model inputs | Materialise three profiles; move compact pools by domain; update loaders atomically. | YAML/JSON parse, profile equivalence, pool content hashes, legacy default remains default. |
| 5. Data and provenance | Move raw/processed/provenance domain by domain; update cross-domain manifest in the same commit per domain. | Content hashes, row counts, schema, path-sensitive metadata audit; stop on any missing reference. |
| 6. Workflows | Move and merge scripts; retain bounded wrappers where needed. | CLI help snapshots, mocked acquisition tests, stop-on-failure and no-retry tests. |
| 7. SQL | Move templates; validate deterministic generators; archive historical generated SQL. | SQL/template checksums, query identifiers, byte-identical regeneration. |
| 8. Documentation | Consolidate active guides; archive phase/tranche reports; update links. | Markdown link check and Maker-facing journey review. |
| 9. Tests | Move tests and fixtures to semantic suites; remove chronology from active names. | Test collection count does not fall; full suite passes. |
| 10. Outputs and ignore rules | Move experiment outputs and diagnostics; update `.gitignore`. | `git check-ignore`, output checksums, no large generated artefacts staged. |
| 11. Compatibility removal | Remove shims, obsolete cumulative configs, old wrappers, and old paths after validation. | Search finds no active old imports or paths; full regressions pass. |
| 12. Final review | Tree review, provenance audit, documentation review, and clean status. | Stop on behavioural difference, broken checksum, unresolved reference, or chronology-labelled active path. |

Structural moves, behaviour changes, parameter changes, and new empirical
features must never share a commit.

## Validation framework

Every migration stage must include:

- `python -m compileall src workflows`;
- the complete `pytest` suite;
- targeted smoke tests for changed public interfaces;
- legacy and empirical profile equivalence with fixed seeds;
- Experiments 1–5 substantive checksum comparison;
- compact runtime-pool checksum comparison;
- data dimensions, schemas, coverage, and content hashes;
- manifest and query/execution reverse lookup;
- `git diff --check`;
- `git status --short` and staged-size inspection;
- a search for obsolete active imports and paths;
- `git check-ignore` for raw data, processed data, diagnostics, `.env`, and
  `.DS_Store`.

Stop immediately on a changed economic result, missing provenance link,
content-hash mismatch, import ambiguity, unresolved deterministic ordering,
incomplete generated SQL regeneration, or accidental inclusion of ignored
datasets.

## Git-history policy

Use `git mv` wherever a one-to-one move exists. Make pure moves before content
edits when practical so Git can detect renames. Splits and merges should cite
the source files in the commit message and retain characterisation tests. Do
not combine structural changes with feature development. Historical reports
and generated SQL are archived rather than rewritten, preserving blame and
provenance.

## Obsolete-root review

| Path | Recommendation | Reason |
|---|---|---|
| `structure.txt` | Archive under `docs/archive/historical_plans/`, then delete the root copy after validation. | It is a stale tracked tree snapshot superseded by the repository guide. |
| `Icon` | Remove after confirming it is Finder metadata; keep ignored by `Icon?`/`Icon\r`. | It is local noise, not project content. |
| `notebooks/` | Do not create or retain an empty directory. Introduce only if a reproducible research notebook is approved. | Empty placeholder adds navigation without responsibility. |
| `.idea/` | Keep ignored and remove from local working copies at owner discretion; never track. | IDE-specific state is not reproducible project configuration. |

## Maker-facing reader journeys

1. **Where is the DAI simulation model?**
   `README.md` → `docs/overview/architecture.md` → `src/dai_sim/model/`.
2. **Where are liquidation mechanics implemented?**
   `docs/model/liquidations.md` → `src/dai_sim/model/liquidation.py`.
3. **Where do empirical liquidation inputs come from?**
   `docs/calibration/liquidations.md` →
   `data/liquidations/model_inputs/` → `src/dai_sim/inputs/liquidations.py`.
4. **How do I run the empirical profile?**
   `docs/overview/repository_guide.md` → `config/profiles/empirical.yaml` →
   `workflows/experiments/run.py`.
5. **How do I run the multi-collateral experiment?**
   `docs/experiments/multi_collateral.md` →
   `config/experiments/multi_collateral.yaml` →
   `src/dai_sim/experiments/runner.py`.
6. **Where are market and gas calibration methods documented?**
   `docs/calibration/market_and_gas.md` →
   `src/dai_sim/calibration/{market,gas}.py`.
7. **Where are the underlying data and provenance?**
   `docs/data/provenance.md` → `data/<domain>/{raw,processed,provenance}/`.
8. **Where are validation and robustness results?**
   `docs/validation/` → `outputs/diagnostics/` and `outputs/tables/`.

None of these journeys requires knowledge of Phase or Tranche chronology.

## Unresolved decisions

There are no blocking semantic collisions or unresolved file mappings in the
design inventory. Three implementation details remain deliberately staged
rather than pre-decided:

- whether profile composition is worth adding after complete-profile
  equivalence is established;
- whether any shared random/provenance helper merits extraction to `common/`;
- whether generated SQL should be ignored after deterministic regeneration is
  demonstrated.

These are implementation-stage decisions with explicit gates, not permission
to vary the approved domain-first architecture.
