# Repository restructuring baseline

## Purpose

This is the Stage 1 pre-migration freeze for the behaviour-neutral,
Maker-facing repository restructuring. It records the committed repository,
the explicitly excluded working-tree change, the active environment, runtime
inputs, tests, deterministic simulations and Experiments 1–5 before any path
or package migration.

The restructuring specification, path map, and reference inventory were
retired after the migration closed. Their historical content remains available
through Git history. The complete machine-readable pre-migration freeze is
[`repository_restructuring_baseline_manifest.json`](repository_restructuring_baseline_manifest.json).

## Baseline status

**Stage 1 passed. Stage 2 is ready for separate authorisation and has not
started.** No project file was moved, renamed, split, merged or deleted. No
runtime pool, empirical dataset, SQL query or established output was rebuilt.

## Git checkpoint

- Branch: `feature/multi-collateral`
- Upstream: `origin/feature/multi-collateral`
- Fetch and push URL: `git@github.com:VeroniCup/dai-abm-simulation.git`
- HEAD: `c645139c39293800bf243c9ce915b4466cf2d5b5` — Document Maker-facing repository restructuring
- Parent: `ebb36668955065deb3781a61ea52ca2e1d5ae327` — Add empirical liquidation demand and capacity separation
- Ahead/behind: `0/0`
- Tracked files at HEAD: `272`
- Git: `git version 2.40.0`
- Untracked, non-ignored paths before Stage 1: none

The two most recent milestone commits are `c645139c39293800bf243c9ce915b4466cf2d5b5` (Document Maker-facing repository restructuring) and
`ebb36668955065deb3781a61ea52ca2e1d5ae327` (Add empirical liquidation demand and capacity separation).

## Protected working-tree exclusions

`data/DATA_ACQUISITION_PLAN.md` is the only pre-existing tracked modification.
It remains unstaged and byte-for-byte unchanged:

- working-tree SHA-256:
  `05587f17600f148d90cc26df4f281258d299188dad8dd53d2ab00f351863ee60`;
- committed HEAD SHA-256:
  `d1a38dd32bc8155257e3299e0eb562576e7b0c1c68c556fee607105df6e9db3c`;
- treatment: excluded from the committed-HEAD file inventory and required to
  survive every restructuring stage.

Its content is not reproduced here. Ignored raw and processed data,
provenance detail, generated diagnostics, outputs, `.DS_Store`, `.idea/`,
caches and environment files are likewise outside the committed-HEAD snapshot.

## Current visual tree

```text
.
├── config/                         # 31 tracked configuration/input files
│   └── empirical/data/             # 9 tracked compact runtime artefacts
├── data/                           # 15 tracked entry points/provenance files
│   ├── raw/                        # ignored payloads; tracked domain READMEs
│   ├── processed/                  # ignored datasets; tracked README
│   └── provenance/                 # selected tracked manifests
├── docs/                           # 17 tracked documents/design inventories
├── outputs/                        # generated and ignored
├── scripts/                        # 27 tracked workflow scripts
├── sql/                            # 117 tracked SQL files
│   ├── liquidations/generated/
│   └── vaults/generated/
├── src/                            # 28 tracked Python modules
│   └── estimation/                 # 8 of the 28 modules
└── tests/                          # 22 test modules and 5 fixtures
```

Current paths remain authoritative. The proposed target tree is intentionally
not repeated here; see the restructuring specification.

## Repository counts

| Area | Tracked files |
|---|---:|
| root | 10 |
| config | 31 |
| data | 15 |
| docs | 17 |
| scripts | 27 |
| sql | 117 |
| src | 28 |
| tests | 27 |

There are 28 source modules, including 8 estimation modules; 27 workflow
scripts; 117 SQL files; 31 configuration-area files (22 configurations plus 9
compact runtime artefacts); 22 test modules; 5 fixtures; and 28 tracked
Markdown files. The maximum tracked path depth is 7.

The design path map has 282 rows,
represents its 255/255 tracked snapshot and all 14/14 intended Tranche D files,
and has no unresolved, duplicate or malformed rows. The reference inventory
has 2261 rows and likewise
has no unresolved, duplicate or malformed rows. Both inventories pre-date
their own documentation commit and intentionally avoid self-reference.

## Environment summary

- Python: `3.13.9` (`CPython`)
- Platform family and architecture: `Darwin arm64`
- Key packages: NumPy `2.3.5`, pandas
  `2.3.3`, Matplotlib `3.10.6`,
  PyYAML `6.0.3`, SciPy `1.16.3`, pytest
  `8.4.2`, statsmodels `0.14.5`
- `environment.yml` SHA-256: `92c55be185f5b46924865479f96b1d374cf86a67b024a8c3d25ffc7fb589ede2`
- `requirements.txt` SHA-256: `c2c46b3b9d67c2bedd805eb5a53e27d4598ab8502466d4e96efa5baeaa34bc30`

All required imports and tests pass. The environment is operational but not an
exact match: `environment.yml` requests Python 3.11, while the active
interpreter is Python 3.13.9. Package records in the JSON contain names and
versions only; build paths and machine identifiers are excluded.

## Source and import baseline

All 28 source modules imported successfully with the currently supported
repository-root plus `src/` import path. The committed layout uses a mixture of
flat imports, `src.*` imports and explicit `sys.path` manipulation in scripts
and tests. Their exact locations and module hashes are recorded in the JSON.
No import was changed.

## Configuration baseline

The cumulative empirical chain is:

1. `config/empirical/phase2_empirical_baseline.yaml` (`ba5b835065c7749650c24ecba85a993fdfc6f8ac2aa0960ce27e54817d13ed3e`, mode `empirical_tranche_a`)
2. `config/empirical/phase2_empirical_distributional.yaml` (`3dc98addca67821c43fb94d292e846dc04eeafd491afa49b84e998d826ea0dea`, mode `empirical_tranche_b`)
3. `config/empirical/phase2_empirical_market_gas.yaml` (`b892981b30a85e3fe2aa91df4c0bd27ce873aac96851918c961aed1deb0acc83`, mode `empirical_tranche_c`)
4. `config/empirical/phase2_empirical_liquidation_arrivals.yaml` (`14f16732cca34021e69e9b729f7441bde212820411f6889cf95de80770d78edb`, mode `empirical_tranche_d`)

The most complete current empirical bundle is
`config/empirical/phase2_empirical_liquidation_arrivals.yaml`. All tracked
YAML/JSON configuration and manifest candidates, plus relevant CSV tables,
parsed successfully. Complete configurations, partial sensitivities, runtime
inputs and manifests remain distinguished in the JSON.

## Runtime-input checksums

| Input | Current path | Shape | SHA-256 | Gate |
|---|---|---:|---|---|
| vault_initialisation_pool | config/empirical/data/vault_initialisation_pools.csv | 7208 x 12 | `5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892` | pass |
| market_gas_hourly_pool | config/empirical/data/market_gas_hourly_pool.csv | 27024 x 16 | `b69276801bacf789f8ae91789983cc98a8a6d42d0a992940c0bcfa109ca25b7d` | pass |
| liquidation_gas_pool | config/empirical/data/liquidation_gas_pool.csv | 1287 x 11 | `37a5f49f4cc273b9d0d9526609be7f14b91b78939acf26e4dce00b66443e1594` | pass |
| liquidation_arrival_hourly_pool | config/empirical/data/liquidation_arrival_hourly_pool.csv | 1104 x 12 | `cc29435bb0434237aba438ee98bded77f086704c7400bb5016e2b58703258c8a` | pass |
| liquidation_sequence_pool | config/empirical/data/liquidation_sequence_pool.csv | 54 x 10 | `9fdd5f3b5fb97e2dd41d0201bad34909ad05e423ad6b52f65219f49f02a1c7ed` | pass |

The liquidation-gas pool contains 1,283 primary-eligible rows and retains four
zero observations. The liquidation-arrival manifest SHA-256 is
`a6123b4aefa2b2d4d41abb40cd924c89fa5e9194ddd331b493820af959de850f`. Every pinned checksum matched; no pool was
rebuilt.

## Data and provenance summary

Every tracked data entry point and provenance manifest is recorded with its
committed SHA-256, domain, role, path-reference flags and available Dune query
or execution identifiers. No tracked entry point contains an absolute local
path. Ignored raw/processed data are summarised by domain, file count, byte
size and extension in the JSON; their individual payloads were not hashed or
altered.

## SQL summary

There are 117 tracked SQL files: 20 hand-authored/templates and 97 generated
files. Each has a committed SHA-256 and domain classification in the JSON.
No Dune query was run. Deterministic regeneration has not yet been
demonstrated for the complete generated SQL corpus, so generated SQL remains a
Stage 7 validation risk.

## Test results

- `python -m compileall src scripts`: passed
- `pytest -q`: **322 passed**, 0 failed, 0 skipped, 0 warnings (5.44 seconds)
- Tranche B: **19 passed** (1.55 seconds)
- Tranche C: **17 passed** (1.43 seconds)
- Tranche D: **17 passed** (0.71 seconds)

## Deterministic smoke results

| Smoke | Seed | Horizon | Final DAI | Max abs peg deviation | Attempts | Successes | Substantive SHA-256 |
|---|---:|---:|---:|---:|---:|---:|---|
| legacy_baseline | 42 | 100 | 0.991190416881 | 0.0088095831186 | 4593 | 90 | `5f7bb2776d72c846ddfd1ceca791ec3f0f2e111ba445e6d12a178796a812fa64` |
| cumulative_empirical_market_gas | 42 | 200 | 0.862240084086 | 0.137759915914 | 0 | 0 | `078cf67155069c9eecc19416407a2254fd03d22d00cf4864b85638fc4adfd53b` |
| empirical_with_legacy_liquidation_demand | 42 | 200 | 0.862240084086 | 0.137759915914 | 0 | 0 | `078cf67155069c9eecc19416407a2254fd03d22d00cf4864b85638fc4adfd53b` |
| empirical_with_hurdle_liquidation_demand | 42 | 200 | 0.862240084086 | 0.137759915914 | 0 | 0 | `bbe69f0ba6813d3c0ed60f4b30ad5b2adc6e12572b4619560d87a62556befbc1` |
| multi_collateral_bounded | 42 | 48 | 1.00051635362 | 0.0015818105935 | 6477 | 290 | `a8913dff2a6955e5dce2424a0955608d930051dbd050f8aa0fa07b47bba93bf9` |

The cumulative empirical market/gas and the explicit legacy-demand sensitivity
have the same substantive output, as expected: both use legacy all-eligible
liquidation demand. The empirical hurdle run differs. Every smoke was run
twice and reproduced its checksum.

## Experiments 1–5 regression baseline

Canonicalisation sorts columns and rows, excludes timestamps/paths/runtime
metadata, and records numeric content to 10 significant digits. This is stable
across in-memory results and their established CSV serialisation.

| Experiment | Name | Scenarios | Combined shape | Substantive SHA-256 | Matches existing ignored tables |
|---:|---|---|---:|---|---|
| 1 | baseline_scenarios | extreme_panic, high_gas, low_gas, medium_gas | 400 x 62 | `30090453d67c4f9632b0212f9df5df178ee4f1aeb769a013056af2a6383a95da` | yes |
| 2 | oracle_delay | oracle_delay_0, oracle_delay_1, oracle_delay_10, oracle_delay_3, oracle_delay_5 | 500 x 63 | `f7c9494e3996b83d962193659472afcbc0d87d7ff5345ef221df7c065ae0c761` | yes |
| 3 | shock_severity | shock_20pct, shock_35pct, shock_43pct, shock_55pct, shock_70pct | 500 x 63 | `1f02073859d7dda416b73ae1470d76570cb9c9ab475ca054971d2a6ef5765c6d` | yes |
| 4 | confidence_sensitivity | baseline_confidence, extreme_confidence_breakdown, fragile_confidence, panic_sensitive, resilient_confidence | 500 x 63 | `73ccf5d20ddca457822ab5d7d10e63061acdd51ee341f562f2c1344dc235f237` | yes |
| 5 | peg_recovery | recovery_0pct, recovery_100pct, recovery_25pct, recovery_50pct, recovery_75pct | 500 x 66 | `b843906be4a59d31b4f7b7306b5c2038df77b49ba361bc24c24dd1f5384fe339` | yes |

Each experiment ran twice with identical checksums. The checksums also match
the existing ignored `combined_results.csv` and `summary.csv` tables. Existing
result and figure files were not regenerated or overwritten. Experiment 6 is
represented only by the bounded multi-collateral smoke above.

## Randomness risks

Simulation, vault initialisation, market blocks, gas sampling and liquidation
arrivals expose separate seed interfaces and use NumPy generators. Experiment
runners propagate the fixed simulation seed. Fixed-seed reproducibility passed.
`src/dai_market.py` retains an unseeded fallback generator when no RNG is
supplied; established simulation runners supply their seeded generator. This
is an import-migration risk, not a Stage 1 behavioural failure. Random streams
were not consolidated.

## Ignore-policy verification

Representative `.DS_Store`, `.idea/`, `.env`, raw data, processed data,
generated diagnostics, outputs, Python caches and pytest caches are ignored by
the current `.gitignore` rules. No raw or processed dataset, credential file or
generated output became trackable. `.gitignore` was not changed.

## Migration gates for Stage 2

All Stage 2 readiness gates pass:

- local and remote commits match;
- full and targeted tests pass;
- pinned runtime-input hashes match;
- Experiments 1–5 are repeatable and match established ignored outputs;
- legacy and empirical smokes are repeatable;
- the protected working-tree change is the only tracked exclusion;
- ignore policy works;
- the JSON parses and covers every file tracked at HEAD exactly once;
- report and manifest values agree.

Stage 2 still requires separate explicit authorisation.

## Known limitations

- The active Python minor version differs from `environment.yml`.
- Imports currently mix flat modules, `src.*` imports and `sys.path` edits.
- The DAI-market unseeded fallback remains an implicit RNG risk for unsupported
  callers that omit the RNG.
- Complete generated-SQL regeneration is not yet proven.
- The design inventories intentionally exclude self-referential design
  artefacts.
