# AGENTS.md

Before using "dynamic workflows", "ultra code" or any harness feature that immediately 
spawns a large swarm of subagents, always explain the tradeoffs and ask the user for explicit approval.

## Project purpose

This repository implements a simplified agent-based simulation of DAI stability
under market stress for an MSc Computational Finance dissertation.

The model studies interactions between:

* collateral price shocks;
* vault leverage and liquidation;
* oracle delay;
* keeper incentives and capacity;
* gas costs;
* bad debt;
* confidence and panic selling;
* DAI peg deviation and recovery;
* multi-collateral portfolio composition.

Prefer transparent, interpretable economic logic over unnecessary complexity.
Do not add MakerDAO protocol features merely for realism unless required by the
research design.

## Completed experiments

The repository contains:

1. baseline gas and panic scenarios;
2. oracle-delay sensitivity;
3. collateral-shock severity;
4. confidence sensitivity;
5. DAI peg recovery;
6. multi-collateral portfolio and shock analysis.

Experiments 1–5 are established ETH-only baselines and must remain operational
unless a change is explicitly requested.

## Architecture

Main source files:

- `src/collateral.py`
- `src/vault.py`
- `src/liquidation.py`
- `src/price_process.py`
- `src/simulation.py`
- `src/experiments.py`
- `src/metrics.py`
- `src/plot_results.py`
- `src/confidence.py`
- `src/dai_market.py`

Approximate dependency flow:

experiments.py
    -> simulation.py
        -> price_process.py
        -> vault.py
        -> liquidation.py
        -> confidence.py
        -> dai_market.py
    -> metrics.py
    -> plot_results.py

Inspect actual imports and call sites before editing.

## Multi-collateral model

The implemented design is:

* each vault holds exactly one collateral asset;
* ETH, BTC, and STABLE vaults may coexist;
* portfolios are defined by target system debt shares;
* ETH-only remains the default special case;
* market and oracle prices are collateral-specific;
* liquidation ratio, liquidation penalty, and maximum close factor may be
    collateral-specific;
* keeper opportunities share one global capacity constraint;
* system-level and collateral-level results are both produced.

Canonical vault fields include:

* collateral_amount
* collateral_type
* debt_dai
* liquidation_ratio

Do not reintroduce deprecated ETH-specific vault fields such as
collateral_eth.

## Core interfaces

Canonical collateral prices are represented as mappings such as:

    {
    "ETH": 2000.0,
    "BTC": 30000.0,
    "STABLE": 1.0,
    }

Canonical price paths use CollateralPricePaths with:

* aligned simulation steps;
* collateral-specific market-price arrays;
* collateral-specific oracle-price arrays.

Legacy ETH-only scalar, array, and DataFrame inputs remain supported through
normalisation adapters.

The existing system-level result schema must remain compatible with Experiments
1–5. Multi-collateral attribution should remain in long-format collateral-level
results rather than hard-coded asset columns.

## Output structure

Results and figures must remain separate.

    outputs/
    ├── results/
    │   ├── 01_baseline_scenarios/
    │   ├── 02_oracle_delay/
    │   ├── 03_shock_severity/
    │   ├── 04_confidence_sensitivity/
    │   ├── 05_peg_recovery/
    │   └── 06_multicollateral/
    └── figures/
        ├── 01_baseline_scenarios/
        ├── 02_oracle_delay/
        ├── 03_shock_severity/
        ├── 04_confidence_sensitivity/
        ├── 05_peg_recovery/
        └── 06_multicollateral/

Do not place figures inside outputs/results/.

CSV files should be written directly under each one without subdirectories.

## Economic invariants

Preserve these distinctions:

* liquidatable status is determined by collateral ratio relative to the
    liquidation ratio;
* liquidation and bad debt are not equivalent;
* keeper participation depends on expected profitability;
* gas costs, penalties, close factors, delays, capacity limits, and failed
    attempts must remain economically meaningful;
* DAI-price effects must arise through explicit model mechanisms rather than
    directly from collateral labels.

Do not change economic equations merely to make tests pass.

If a requested implementation requires a new modelling assumption, report the
decision explicitly rather than choosing silently.

## Working rules

* Work in small, coherent changes.
* Inspect all relevant call sites before changing public interfaces.
* Do not perform broad blind search-and-replace operations.
* Do not rewrite unrelated modules.
* Do not weaken validation or suppress errors to obtain a passing run.
* Preserve deterministic random seeds unless explicitly asked otherwise.
* Use British English in comments, documentation, labels, and user-facing text.
* Retain type hints and useful validation messages.
* Avoid unnecessary dependencies.
* Do not commit or stage changes unless explicitly requested.
* Do not overwrite established experiment outputs unless the task requires
    regeneration.

## Validation

Choose validation appropriate to the files changed. At minimum, normally run:

    Bash
    python -m compileall src
    git diff --check

For simulation changes, also run relevant smoke tests such as:

    Bash
    python src/collateral.py
    python src/vault.py
    python src/liquidation.py
    python src/simulation.py

Run python src/experiments.py only when the task requires experiment
regeneration or full integration validation.

For changes affecting backward compatibility, verify that equivalent ETH-only
representations and identical seeds produce equal results within the required
numerical tolerance.

## Target Repository Architecture

<!-- BEGIN APPROVED TARGET REPOSITORY ARCHITECTURE -->

### Target architecture status

The domain-first repository architecture is the approved target for the next
dedicated restructuring. It has not yet been implemented. Until an authorised
migration stage is completed, current paths remain authoritative.

The full implementation specification, file-level path map, compatibility
policy, and validation sequence are in
`docs/repository_restructuring_specification.md`.

### Domain-first organising principle

Organise empirical work first by:

* `market`;
* `gas`;
* `vaults`;
* `liquidations`;
* `protocol`.

Within each data domain, repeat the lifecycle:

* `raw/`;
* `processed/`;
* `model_inputs/`;
* `provenance/`.

The approved top-level and important second-level target is:

```text
src/dai_sim/
├── model/
├── inputs/
├── calibration/
├── experiments/
└── common/

config/
├── profiles/
├── experiments/
├── sensitivities/
└── protocol/

data/
├── market/{raw,processed,model_inputs,provenance}/
├── gas/{raw,processed,model_inputs,provenance}/
├── vaults/{raw,processed,model_inputs,provenance}/
├── liquidations/{raw,processed,model_inputs,provenance}/
├── protocol/{raw,processed,model_inputs,provenance}/
└── provenance/

workflows/
├── market/
├── gas/
├── vaults/
├── liquidations/
├── protocol/
├── inputs/
├── calibration/
├── experiments/
└── maintenance/

sql/<domain>/{templates,generated}/
docs/{overview,model,calibration,experiments,data,validation,archive}/
tests/{model,inputs,calibration,experiments,workflows,integration,fixtures}/
outputs/{experiments,diagnostics,figures,tables}/
```

### Mandatory future rules

* Active paths describe domain and purpose, not development chronology.
* Do not create new active files or directories named for phases, tranches,
  attempts, temporary repairs, or version suffixes such as `final_v3`.
* Phase and tranche labels belong only in `docs/archive/`, historically
  necessary provenance, and Git history.
* Use singular Python model modules where appropriate, such as `vault.py` and
  `liquidation.py`; use plural domain directories such as `vaults/` and
  `liquidations/`.
* Use the workflow verbs `acquire`, `process`, `reconstruct`, `build_inputs`,
  `calibrate`, `validate`, and `run` consistently.
* Expose user-facing configuration profiles named `legacy`, `empirical`, and
  `empirical_stress`; do not expose cumulative Tranche configurations.
* Place compact empirical runtime inputs under the owning domain's
  `model_inputs/` directory, not under `config/`.
* Place development-history reports and plans under `docs/archive/`.
* Preserve behavioural neutrality during restructuring. Structural moves must
  not be combined with model, parameter, or empirical-feature changes.
* Consult `docs/repository_restructuring_specification.md` before any structural
  change.

### Temporary transition rule

Until the approved migration is implemented:

* use current paths where required;
* do not create ad hoc hybrid folders;
* do not partially implement the target architecture outside an authorised
  migration stage;
* record new work using current paths only when necessary, and map it in the
  restructuring specification before migration.

<!-- END APPROVED TARGET REPOSITORY ARCHITECTURE -->
