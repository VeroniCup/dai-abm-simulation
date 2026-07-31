# Result-blind oracle-delay freeze

## Purpose and boundary

This note records the numerical freeze required before final Experiment E. It
was completed after Experiment D and before any Experiment E simulation. The
master programme remains content-addressed as
`084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260`;
its six E rows, two anchors, treatment identifiers and row checksums have not
changed. The external delay registry only resolves their previously empty
numerical coordinate.

No network source, held-out observation, USDC/SVB interval, prior final-
experiment result or hypothetical Experiment E outcome was used. The registry
is not imported by an ordinary runtime profile and does not select a preferred
delay.

## Implemented simulation semantics

The target is `SimulationConfig.oracle_delay_steps`, implemented by
`src/dai_sim/model/collateral_prices.py::_apply_oracle_delay`. It is a
non-negative integer measured in simulation steps. Final-programme paths are
hourly, so one step equals one hour.

The same fixed lag is applied independently to every available ETH, BTC and
STABLE market-price array. At step \(t\), the protocol-observed price is the
market price from \(t-d\). For the first \(d\) steps, where no earlier path
value exists, the first market price is repeated. No interpolation is used.
Market prices themselves remain contemporaneous, as do the gas input and DAI
price process. Protocol collateralisation summaries, liquidation eligibility
and keeper liquidation decisions use the delayed oracle prices. Market-based
stress and confidence summaries continue to use contemporaneous market
prices.

The parameter is therefore a simplified simulation price lag. It is not
automatically equivalent to any single real-world oracle property.

## Concepts kept distinct

The evidence review distinguished:

1. oracle update cadence;
2. oracle observation staleness;
3. publication latency;
4. a protocol-imposed delay;
5. the implemented simulation price lag; and
6. market-to-protocol price mismatch.

Only direct timestamp pairs could identify realised observation staleness.
Update intervals could at most partially identify it. A tracked protocol rule
could provide a bounded design coordinate only if its numerical value and
effective period were already present locally.

## Repository-resident source inventory

| Candidate | Local evidence | Observations relevant to its own object | Oracle-delay use |
| --- | --- | ---: | --- |
| Spot oracle-adapter history | Six effective `pip` mappings for ETH/WBTC ilks | 6 | Excluded: maps contracts but contains no observation timestamp, cadence or delay value |
| Hourly protocol panel | Forward-filled parameter and adapter state | 162,144 | Excluded: derived state, not oracle updates |
| Hourly market panel | Contemporaneous ETH/WBTC reference prices | 27,024 | Excluded: no oracle timestamp and held-out periods are present in the file |
| OSM `hop` schema metadata | A live getter schema identified during Phase 1D discovery | 0 numeric observations | Excluded: metadata alone supplies neither value nor effective period |
| Oracle parameter-source mapping | A partial acquisition design for `osm_call_hop` | 1 design row | Excluded: explicitly describes getter calls as opportunistic and does not reconstruct history |
| Integrated ETH validation profile | Transparent zero-delay setting | 0 empirical observations | Excluded: scenario baseline, not evidence |
| Historical oracle-experiment manifest | Protected legacy simulator outputs | 0 source observations | Excluded: result-generated data cannot choose E coordinates |

The canonical row-level inventory, file checksums, coverage, missingness,
duplicate diagnostics and exclusion reasons are in
`data/provenance/calibration/oracle_delay/oracle_delay_source_inventory.csv`.

## Sufficiency and evidence tier

The thresholds were frozen before deriving coordinates. Direct identification
would require at least 30 non-missing staleness observations, at least 10
positive observations and three calendar days. Interval-based partial
identification would require at least 20 valid update intervals over three
calendar days.

There are zero eligible direct staleness observations, zero eligible update
intervals and no locally tracked numerical delay rule with an effective
period. ETH, WBTC, STABLE and the pooled system-wide sample therefore all fail
Tiers 1–3. The scientific classification is:

`transparent_sensitivity_not_empirically_identified`.

## Result-blind coordinate derivation

The pre-registered Tier 4 rule is used:

| Treatment | Steps | Hours | Interpretation |
| --- | ---: | ---: | --- |
| `oracle_delay_low` | 0 | 0 | transparent no-delay baseline |
| `oracle_delay_central` | 1 | 1 | one-step mechanism sensitivity |
| `oracle_delay_high` | 2 | 2 | two-step mechanism sensitivity |

For any empirical tier, conversion would use deterministic ceiling to the
one-hour step and would require the high value to exceed the central value by
at least one step. Tier 4 fixes the integer coordinates directly, so no
rounding or cap was applied.

> The zero-, one- and two-step coordinates are result-blind mechanism
> sensitivities and are not estimates of historical Maker oracle latency.

The one common coordinate set is extrapolated across ETH, BTC and STABLE
because the existing model exposes one global delay. This is a model-aligned
sensitivity, not evidence of equal oracle behaviour across collateral
families.

## Experiment E readiness

The registry resolves exactly six cells:

- `empirical_crypto` under `joint_crypto_high_correlation`, crossed with
  delays 0, 1 and 2; and
- `stable_supported` under `joint_crypto_stable_stress`, crossed with delays
  0, 1 and 2.

Every cell retains 128 planned replications, shared keeper capacity 26,
`direct_cost_only` hurdle and `stage1_only` confidence. Total planned
simulation count remains 768. Future execution must pair identical initial
states, shocks, gas paths, liquidation arrivals, keeper gas-unit draws, DAI
residual blocks and non-delay randomness within each anchor. Only
`oracle_delay_steps` may vary.

The readiness classification is
`experiment_e_ready_with_transparent_delay_sensitivity`. Experiment E is ready
but unexecuted. No checkpoint or substantive output was created by this pass.

## Reproducibility and limitations

The canonical configuration is
`config/sensitivities/final_oracle_delay_registry.yaml`. Its identity binds the
parent commit, implemented semantic owner, one-hour step, source inventory,
empty eligible-source set, evidence tier, calibration boundary, derivation and
rounding rules, coordinates, held-out exclusions and `runtime_adopted: false`.

Compact provenance is held in
`data/provenance/calibration/oracle_delay/`. The workflow
`workflows/calibration/oracle_delay.py` supports local inventory, estimation,
freeze and validation modes but contains no experiment executor. Its
non-host-dependent artefacts reconstruct byte-identically.

The principal limitation is substantive: the local repository does not hold
the timestamp evidence required to estimate historical Maker oracle
staleness. The freeze therefore supports a transparent mechanism experiment,
not a claim about the empirical distribution of real oracle latency.
