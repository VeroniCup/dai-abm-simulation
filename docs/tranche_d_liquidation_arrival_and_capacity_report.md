# Tranche D Liquidation Arrival and Capacity Report

## Purpose

Tranche D adds a deliberately opt-in liquidation-demand layer between
endogenous unsafe-vault creation and keeper execution. It is designed to keep
three ideas separate:

- how many vaults are unsafe in the simulated state;
- how many liquidation opportunities arrive for processing in the current
  step; and
- how many of those opportunities keeper capacity and profitability allow the
  model to execute.

The tranche does not acquire new data, rerun parameter estimation, change the
keeper-profit equation, add an auction engine, alter confidence mechanics or
modify legacy defaults.

## Existing liquidation-flow audit

The legacy simulator already treats unsafe-vault creation endogenously. At each
step it computes liquidatable vaults from oracle prices and collateral ratios,
then evaluates keeper profitability for every liquidatable vault. Profitable
opportunities are ordered by expected profit, and
`max_liquidations_per_step`, where supplied, limits execution after that
ranking.

Two semantic points are important:

1. `max_close_factor` is a per-vault debt-close fraction. It controls how much
   of an individual vault can be repaid in one simplified liquidation.
2. `max_liquidations_per_step` is keeper throughput. It limits the number of
   liquidation opportunities that can be executed in one simulation step.

Tranche D preserves both meanings. It adds an optional demand draw before
capacity is applied, rather than reinterpreting close factor as throughput or
using historical Bark counts as a direct replacement for simulated unsafe-vault
inventory.

## Empirical evidence used

The compact Tranche D runtime pools are derived from the validated Phase 2C
Terra/CeFi liquidation artefacts:

- 649 exact Bark--grab matches;
- 649 successful full-position grabs;
- 54 liquidation sequences;
- 65 active liquidation hours within 1,104 observed hourly rows; and
- a maximum observed hourly grab count of 46.

The hourly arrival pool contains no transaction hashes, urns, owners, auction
identifiers or raw Dune payloads. It is a compact runtime abstraction of
liquidation intensity evidence.

## Hurdle estimator

The primary Tranche D hurdle probability is:

```text
P(activity | start-of-hour liquidatable inventory > 0)
  = 48 / 138
  = 0.34782608695652173
```

The unconditional activity probability is:

```text
65 / 1104 = 0.058876811594202896
```

The conditional estimator is preferred for the runtime process because the
simulator first observes its current unsafe-vault inventory. The limitation is
that the empirical denominator is a start-of-hour inventory proxy. Some
historical Bark/grab activity occurs in hours where the start-of-hour
liquidatable count is zero because vault state changes within the hour. The
estimator is therefore a transparent demand proxy, not a claim that every
keeper action is observed by the same state variable the simulator uses.

## Positive-count pool

Conditional on hurdle activation, Tranche D samples positive hourly grab
counts with replacement from the empirical positive-count pool:

| Statistic | Value |
|---|---:|
| Positive hours | 65 |
| Minimum | 1 |
| Median | 5 |
| Mean | 9.984615384615385 |
| Variance | 117.45288461538461 |
| Variance-to-mean ratio | 11.763385562534962 |
| 75th percentile | 17 |
| 90th percentile | 23.60000000000001 |
| 95th percentile | 27.799999999999983 |
| 99th percentile | 45.359999999999985 |
| Maximum | 46 |

The source hourly grab count is strongly overdispersed. The full 1,104-hour
source series has mean `0.5878623188405797`, variance
`12.344041119739138` and variance-to-mean ratio `20.99818396947921`, with
zero-hour share `0.9411231884057971`.

## Sequence sensitivity

The sequence pool preserves 54 observed liquidation clusters, with median
sequence size 5, mean sequence size `12.018518518518519`, maximum sequence
size 84 and maximum observed duration 7,194 seconds.

Tranche D does not implement `empirical_sequence_bootstrap` as a runtime mode.
The current simulator executes liquidations in a single stage and does not yet
maintain a liquidation-sequence state. The sequence file is retained for
diagnostics and a later separately authorised auction or clustered-arrival
interface.

## Runtime artefacts

| Artefact | Rows | SHA-256 |
|---|---:|---|
| `config/empirical/data/liquidation_arrival_hourly_pool.csv` | 1,104 | `cc29435bb0434237aba438ee98bded77f086704c7400bb5016e2b58703258c8a` |
| `config/empirical/data/liquidation_sequence_pool.csv` | 54 | `9fdd5f3b5fb97e2dd41d0201bad34909ad05e423ad6b52f65219f49f02a1c7ed` |
| `config/empirical/data/liquidation_arrival_pools_manifest.json` | 1 manifest | `a6123b4aefa2b2d4d41abb40cd924c89fa5e9194ddd331b493820af959de850f` |

The builder verifies Phase 2C source checksums before writing these compact
runtime artefacts.

## Configuration interface

The primary opt-in configuration is:

```text
config/empirical/phase2_empirical_liquidation_arrivals.yaml
```

It inherits the Tranche C empirical market and gas inputs and adds:

- `liquidation_demand.mode: empirical_hurdle_count`;
- `liquidation_demand.hurdle_probability: 0.34782608695652173`;
- `liquidation_demand.hurdle_estimator:
  conditional_start_inventory_positive`;
- `liquidation_demand.positive_count_mode:
  empirical_positive_hour_counts`;
- `liquidation_demand.sequence_mode: none`; and
- `liquidation_demand.count_truncation_policy:
  truncate_to_inventory_then_capacity`.

The default demand configuration remains `legacy_all_eligible`. Loading a
Tranche A, B or C bundle does not activate empirical liquidation demand.

Tranche D also adds sensitivity bundles for:

- lower and upper hurdle probability;
- lower and upper throughput capacity; and
- explicit legacy-demand behaviour under the Tranche D loader.

## Runtime demand and capacity logic

For the empirical mode, each step follows this order:

1. observe current simulated liquidatable inventory;
2. draw hurdle activity only if inventory is positive;
3. if active, sample a positive count from the empirical positive-count pool;
4. truncate sampled demand to available inventory;
5. truncate bounded demand to `max_liquidations_per_step`, if capacity is set;
6. pass only the resulting attempt budget to the existing keeper-profit and
   liquidation execution path.

Liquidation candidates continue to be ordered by existing expected keeper
profit, with vault identifier as a deterministic tie-breaker. Unprofitable
selected opportunities remain unprofitable; the demand layer does not bypass
profitability.

The empirical output columns are added only when empirical demand is active:

- sampled liquidation demand;
- bounded liquidation demand;
- attempt budget;
- activity draw;
- inventory truncation;
- capacity truncation; and
- unresolved inventory after the step.

Legacy result schemas remain unchanged.

## Diagnostic results

The Tranche D diagnostic script writes generated outputs under:

```text
data/processed/estimation/tranche_d/
```

These are local generated diagnostics, not new empirical acquisitions.

The capacity separation diagnostic confirms that attempts never exceed the
capacity cap and bounded demand never exceeds simulated inventory. With the
same sampled demand path and an artificially ample unsafe inventory:

| Capacity | Share capacity-truncated | Average unprocessed demand |
|---:|---:|---:|
| 5 | 0.16666666666666666 | 2.088768115942029 |
| 20 | 0.061594202898550724 | 0.49094202898550726 |

The generated hurdle-count path is intentionally not forced to reproduce the
source zero share exactly. With the configured seed and start-inventory
conditioning it produced zero-demand share `0.9583333333333334`, mean bounded
demand `0.20018115942028986`, variance-to-mean ratio
`10.338595004621644` and maximum bounded demand 24. This is expected from an
independent Bernoulli/count draw under current-inventory conditioning.

Six local smoke scenarios passed:

- legacy demand under the legacy environment;
- legacy demand under the Tranche C environment;
- empirical hurdle demand with high capacity;
- empirical hurdle demand with constrained capacity;
- unprofitable selected opportunities;
- no liquidatable inventory.

## Limitations

Tranche D does not model:

- auction lifecycle or partial Take execution;
- multiple keepers bidding within one auction;
- per-action gas attribution;
- a Hawkes or Markov liquidation-arrival process;
- behavioural owner response; or
- final parameter adoption.

The hurdle/count process is an empirical reduced-form demand interface designed
to expose arrival uncertainty and throughput separately. It is suitable for
opt-in simulation experiments and sensitivity analysis, but it should not be
presented as a complete structural model of Maker liquidation auctions.

## Reproducibility checks

The implementation preserves established Tranche A--C defaults and uses
deterministic seeds. The compact empirical pool checksum remains:

```text
5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892
```

No data acquisition, parameter estimation, simulator-parameter adoption or
commit is part of this tranche.
