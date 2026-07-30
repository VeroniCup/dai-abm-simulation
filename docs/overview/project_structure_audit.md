# Project structure audit

## Audit result

**Classification: `scientific_package_taxonomy_ready_with_protected_exceptions`.**

Calibration, validation, typed inputs, mechanism experiments and the future
final programme now have explicit package boundaries. No final experiment has
been implemented. The exceptions are path-hashed historical implementations,
not ambiguous active owners.

## Findings and actions

| Area | Finding | Action | Risk controlled |
| --- | --- | --- | --- |
| `src/dai_sim/calibration/` | Estimation and identification are coherent; two frozen-profile validators were semantically misplaced | Added semantic validation interfaces, retained path-hashed implementations | Scientific identities remain reconstructable |
| `src/dai_sim/validation/` | No explicit package previously existed | Added confidence, integrated ETH and multi-collateral validation interfaces | New callers have semantic validation interfaces; protected implementations and workflows remain path-bound |
| Confidence scenarios | Registry resolution and evidence validation shared one experiment module | Split active responsibilities between `inputs/` and `validation/` | One YAML value owner remains |
| ETH recovery studies | Controlled treatment matrices were mixed with root historical runners | Moved source, workflows and tests to `experiments/mechanism/` | Registered identities and evidence unchanged |
| Final experiments | Destination was implicit | Added only `experiments/final/__init__.py` | Following pass has one destination |
| Established Experiments 1–6 | Public imports, frozen outputs and historical docs depend on root modules | Retained `runner`, `scenarios`, `summaries` and `plots` | Experiments 1–5 remain operational |
| Tests | Scenario validation sat under calibration; validators sat under integration | Split/moved to `inputs/`, `validation/` and `experiments/mechanism/` | Collection count and substantive cases preserved |
| Workflows | Recovery entry points lacked the mechanism boundary | Moved both beneath `workflows/experiments/mechanism/` | CLI operations unchanged |
| Input validation workflows | Five commands consistently validate resolved inputs | Kept under `workflows/inputs/` | Two workflow files remain identity inputs |
| Shared recovery metric | Both registered recovery studies share one implementation | Retained under the ETH mechanism study | No equation or scientific identity changed |
| Documentation | Scientific roles were previously collapsed into “validation and experiments” | Added taxonomy, corrected diagrams, links and ownership tables | Final placement is explicit |

## Path-safety decisions

- **Safe moves:** both recovery implementations, their workflows and their
  tests. Their scientific identity functions return frozen registered
  identities rather than hashing the current module path.
- **Safe split:** confidence scenario resolution versus scenario validation.
  Existing compact payloads do not record the old Python source path.
- **Protected paths:** both validator implementations and both input-validation
  workflows. Their relative paths and bytes are scientific-code identity
  inputs.
- **Required historical import:** `experiments/confidence_scenarios.py`.
  The unchanged integrated-profile source imports this path and is itself an
  identity input.
- **Unsafe in this pass:** extracting recovery equations or rewriting the
  validator evidence identities. Either would require a separately
  pre-registered evidence-version migration.

## Single-owner result

The confidence YAML remains the sole scenario-value owner. The input module
resolves it; the validation module checks it; mechanism experiments consume
it. The historical import surface delegates and stores no values.

The two validation façades delegate to one implementation each. No copied
calculation, registry or serializer was added. Calibration modules continue to
own only estimation and identification, apart from the two documented frozen
implementation paths.

The final experiment destination is exclusively
`src/dai_sim/experiments/final/`. The existing stylised multi-collateral
runner remains historical and is not a competing final programme.

## Full audit reference

The file-by-file experiment audit, calibration-module classification,
workflow convention, test taxonomy, recovery-metric decision and protected
identity details are in
[scientific package taxonomy](scientific_package_taxonomy.md).

## Storage and archive result

Moves and splits add only small source and documentation files. Raw data,
processed data, compact runtime pools, provenance, checkpoints and generated
outputs were not changed. No archive or deletion decision was made. Existing
ignored diagnostic storage remains a separate housekeeping question.

## Gate for the next pass

The next pass may implement the pre-registered hierarchical multi-collateral
programme under `dai_sim.experiments.final`, mirrored by a final workflow and
tests when real code exists. It must import typed inputs and existing model
mechanisms, must not screen frozen portfolios or shocks using validation
outcomes, and must not reuse the historical root runner as a second final
owner.
