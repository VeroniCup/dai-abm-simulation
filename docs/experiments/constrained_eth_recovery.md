# Constrained-liquidation ETH recovery

## 1. Purpose

This pre-registered ETH-only mechanism experiment tests whether collateral
recovery can rescue unsafe vaults when empirical liquidation arrivals and
system-wide keeper throughput delay execution. It addresses the channel that
the earlier unbounded-capacity recovery experiment could not exercise:

\[
\text{unsafe vault}\rightarrow\text{waits for arrival and capacity}
\rightarrow\text{may recover before execution}.
\]

The experiment is complete and is classified
`recovery_effect_capacity_dependent`.

The H5a–H5d labels retained below are this completed study's historical
mechanism labels. They pre-date the final four-hypothesis dissertation
framework. They are not a fifth dissertation hypothesis and must not be
treated as additional hypotheses.

## 2. Relation to the earlier null

The committed unbounded experiment used 100 legacy vaults, fixed gas and
ordinary unbounded keeper execution. It liquidated nearly all unsafe vaults
at the common shock, leaving no unresolved position for a later ETH recovery
to rescue. Its `no_clear_recovery_path_effect` result is therefore a
conditional mechanism null.

The present experiment is not a formal treatment comparison with that study:
the vault population, total debt, gas owner, arrival owner and profile
semantics differ. It asks instead whether the missing waiting channel becomes
operational under the integrated empirical execution environment.

## 3. Integrated empirical base

Every cell resolves the fixed `empirical_integrated_eth` profile:

- identity
  `ab68c32a145262bcef07716469d92be09e3d96506383ad16a07d0ba1bad2b34d`;
- 500 empirical-joint ETH vaults;
- exactly 2,500,000 DAI initial debt;
- empirical market–gas blocks and component keeper gas;
- empirical hourly liquidation arrivals;
- full-close liquidation;
- accepted Stage 1 DAI response and residual blocks;
- zero oracle delay; and
- no WBTC or stable-collateral vaults.

The profile remains opt-in and `runtime_adopted: false`.

## 4. Controlled-price boundary

Only the ETH price path is replaced by a controlled treatment. Empirical gas
rows, gas-unit draws, arrival draws, residual blocks and vault samples remain
common within each replication. This isolates collateral recovery under
empirical execution conditions, but the overlaid price path no longer
preserves the unconditional empirical ETH-return–gas relationship. The study
is a controlled mechanism experiment, not a historical replay.

## 5. Shock and recovery paths

Both paths share a 48-hour pre-shock price of USD 2,000 and the instantaneous
canonical shock to USD 1,140 at hour 48, a 43% arithmetic loss. The shock
checksum is
`f7370b9f2faa6c2e97ca5dddf7b28d3ccfa109ee52f635d9ff43a8893f683ea5`.

The only path treatments are:

| Path | Definition | SHA-256 |
|---|---|---|
| `persistent_trough` | stays at USD 1,140 | `fbe1e92c038a60f662e59178e77d7fcbfa0571a76d6c90494f7ec8b05f5239f5` |
| `full_week` | smoothstep log recovery to USD 2,000 over 168 hours, then held | `f175c9111380499b2b7d71d32a4ac6f42cc3f8bc3d196c7fded95cb87a2c4d3b` |

No alternative path or post-trough ETH noise enters.

## 6. Empirical arrivals, gas and keeper hurdle

Liquidation demand uses the protected empirical hurdle/count input and the
inactive sequence sensitivity remains inactive. Keeper gas uses the same
empirical block rows and gas-unit draws across treatments. The hurdle is
exactly `direct_cost_only`, so `risk_cost_rate = 0`. No positive keeper
hurdle is tested or selected.

## 7. System-wide capacities

The ordered keeper treatments are 14, 26 and 45 opportunities per hour:

| Profile | Capacity |
|---|---:|
| `shared_keeper_capacity_low` | 14 |
| `shared_keeper_capacity_central` | 26 |
| `shared_keeper_capacity_high` | 45 |

Each is one `system_wide_shared_capacity`, even though this experiment is
ETH-only. The result does not select a capacity: 26 remains the existing
central integration candidate, while 14 and 45 remain registered robustness
cases.

## 8. Confidence roles

The four fixed scenarios are ordered:

1. `stage1_only`;
2. `confidence_resilient`;
3. `confidence_central`;
4. `confidence_fragile`.

`stage1_only` owns the primary historical mechanism H5a–H5c conclusions. The
active scenarios are transparent robustness assumptions used for the
historical mechanism H5d label and mechanism sensitivity.
They are neither ranked nor fitted.

## 9. Matrix, replications and common random numbers

The path-first Cartesian product contains exactly \(2\times3\times4=24\)
cells. Every cell has 128 replications, giving 3,072 simulations. Within a
replication all cells share the exact 500-vault state, vault identifiers,
gas rows, gas-unit draws, arrival stream, DAI residual stream and every other
non-treatment stochastic input.

The seed registry checksum is
`fcd4b17789da5684bbbcbc3f3fcbf7825328bf593c0cf06bb4b40ffd75948b5c`.
All 128 paired-stream audits passed.

## 10. Horizon and recovery

The common horizon is 768 hours: 48 pre-shock hours and 720 post-shock
evaluation hours. Sustained peg recovery requires 24 consecutive hours in
\([0.995,1.005]\); a band exit resets the counter. Restricted mean recovery
time is capped at 720 post-shock hours.

Solvency recovery and peg recovery remain distinct. A safe vault can avoid
liquidation without changing the Stage 1 DAI path.

## 11. Vault-level rescue definitions

Compact event tracking records the first unsafe hour, first selected attempt,
first successful closure, first return to safety, and final open status.

`recovered_before_execution` requires an unsafe, still-open vault to return
to safety before its first selected attempt. `recovered_before_closure`
requires it to return to safety while still open before successful closure.
For paired path outcomes, a liquidation is avoided where the vault closes
under `persistent_trough` but remains open under `full_week`; the reverse
case is recorded separately.

## 12. Primary and secondary outcomes

Primary outcomes are paired avoided liquidation debt, backlog area,
maximum unresolved tab, realised bad debt, below-peg burden and restricted
mean sustained-recovery time. Secondary measures cover unsafe inventory,
arrivals, attempts, rejection, profitability, closures, unresolved debt,
bad debt, rescue timing, DAI extrema, recovery probabilities, and the
registered confidence diagnostics. No scalar score is formed.

## 13. Contrasts and uncertainty

Recovery contrasts are `full_week - persistent_trough` within each capacity
and confidence scenario. Capacity contrasts are 26−14, 45−26 and 45−14
within each path and scenario. The three registered recovery–capacity
interactions compare the recovery contrast at 14, 26 and 45. Active
confidence cases are interpreted only against `stage1_only`.

Continuous paired outcomes report means, standard errors, 95% intervals,
medians and quantiles. Binary and zero-heavy outcomes additionally retain
discordance or positive shares. Signs remain mathematical: negative values
are improvements only for lower-is-better outcomes.

## 14. Operationality and numerical validity

Low capacity is operational:

- 99.61% of Stage 1-only path–replication rows contain a binding hour;
- 13.98% of positive-demand hours bind; and
- 99.61% of rows have a positive rejected-opportunity count.

Central capacity also binds and reaches 26 attempts in at least one
replication. All 3,072 simulations are finite and accounting-valid. There are
zero numerical failures, CRN failures, duplicate closures, missing
checkpoints, duplicate checkpoints or orphan checkpoints.

## 15. Primary Stage 1-only results

Full-week recovery rescues positions at every capacity:

| Capacity | Avoided liquidations, mean | Avoided debt, mean DAI | 95% interval, DAI |
|---:|---:|---:|---:|
| 14 | 31.95 | 7,213.87 | [6,225.45, 8,202.28] |
| 26 | 26.01 | 5,579.38 | [4,734.65, 6,424.10] |
| 45 | 24.28 | 5,237.86 | [4,391.62, 6,084.10] |

The reverse count is zero at capacities 26 and 45. At capacity 14 its mean is
0.0156, arising in 0.78% of replications.

Mean backlog area falls by 203,360, 140,912 and 130,803 DAI-hours at
capacities 14, 26 and 45 respectively; every paired 95% interval excludes
zero. Maximum unresolved tab is set at the common shock and is unchanged by
the subsequent recovery. Realised bad debt is numerical rounding dust in
both paths.

## 16. Rescue timing

Within `full_week`, the mean recovered-before-execution counts are 27.65,
20.33 and 17.92 at capacities 14, 26 and 45. Mean
recovered-before-closure counts are 32.09, 26.12 and 24.39. The declining
counts show the expected mechanism: faster execution leaves fewer positions
available for later collateral recovery.

Among vaults closed in both paths, mean closure-time differences
(`full_week - persistent_trough`) are −1.48, −1.00 and −0.82 hours. This
conditional timing statistic does not make later closure intrinsically
beneficial; avoided debt and backlog are interpreted separately.

## 17. Capacity effects and interactions

Capacity 45 versus 14 lowers mean backlog area by 462,735 DAI-hours under the
persistent path and 390,178 DAI-hours under full-week recovery. It also
reduces binding hours and raises the maximum selected attempts, while bad
debt and Stage 1 peg outcomes remain unchanged. The registered capacity
classification is `higher_capacity_reduces_backlog`.

The Stage 1-only low-versus-high recovery interaction is 1,976.00 DAI of
paired avoided debt, with a 95% interval [1,634.87, 2,317.14]. The
corresponding backlog interaction is −72,557 DAI-hours, with interval
[−85,585, −59,529]. Recovery therefore matters more when execution is
slower, while maximum initial backlog and peg outcomes have zero interaction.

## 18. Peg and confidence results

Under `stage1_only`, recovery-path contrasts are exactly zero for below-peg
burden and restricted mean peg-recovery time at all capacities. The ETH
recovery changes vault resolution but the Stage 1 DAI equation has no direct
collateral-path term.

The active confidence scenarios remain robustness cases. Resilient confidence
produces a negative below-peg-burden recovery contrast at all capacities,
whereas central and fragile produce zero primary peg contrast in this matrix.
The result is conditional on fixed scenario mechanics and is not a scenario
ranking or empirical fit.

## 19. Pre-registered decisions

- Historical mechanism H5a, recovery rescues unresolved positions:
  **supported**.
- Historical mechanism H5b, recovery improves primary peg outcomes:
  **not supported**.
- Historical mechanism H5c, the recovery effect depends on capacity:
  **present**.
- Historical mechanism H5d, solvency–peg decoupling under persistent
  confidence:
  **present**.
- Capacity mechanism: **`higher_capacity_reduces_backlog`**.
- Overall: **`recovery_effect_capacity_dependent`**.

The substantive interpretation is that empirical arrivals and bounded
capacity create a genuine waiting channel. Full-week ETH recovery avoids some
closures and lowers backlog, especially at low capacity, but primary Stage 1
peg dynamics remain unchanged. Solvency improvement and peg improvement are
therefore not equivalent.

## 20. Limitations

The controlled ETH path breaks unconditional return–gas dependence and is not
a historical replay. Shared capacity is partially identified. The experiment
uses one 500-vault ETH population scale, full-close liquidations and zero
oracle delay. It neither estimates owner intervention nor validates a physical
keeper-network maximum. Active confidence results are scenario-conditional.

## 21. Production and validation boundaries

No parameter, confidence coefficient, keeper candidate or production default
was changed. The arrival-sequence sensitivity stayed inactive. No USDC/SVB,
withheld final-validation period, WBTC/stable vault, multi-collateral
simulation or oracle-delay calibration entered. `runtime_adopted` remains
false.

## 22. Reproducibility

The immutable specification SHA-256 is
`4016d213eed7cde1262af2cb7cc2318bcb27efd282f35669cdf8f8cb12d0ab70`;
the experiment identity is
`6cfbd19384fc95fe8b06de74704d0b2a76638722b100242e0bc87a9ee3e05acc`.
The scientific owner is
[`constrained_eth_recovery.py`](../../src/dai_sim/experiments/mechanism/constrained_eth_recovery.py),
the configuration is
[`constrained_eth_recovery.yaml`](../../config/sensitivities/constrained_eth_recovery.yaml),
and the workflow is
[`workflows/experiments/mechanism/constrained_eth_recovery.py`](../../workflows/experiments/mechanism/constrained_eth_recovery.py).

The compact evidence is content-addressed under
`data/provenance/experiments/constrained_recovery/`. Detailed atomic
checkpoints remain ignored under
`outputs/experiments/constrained_eth_recovery/<experiment-identity>/`. The
safe execution used one worker after a four-worker host attempt exposed an
existing temporary profile-loader race before any checkpoint was written.
The completed run used 12,000,298 bytes and retained more than 237 GB free.

The subsequent
[experiment-infrastructure maintenance](../validation/experiment_infrastructure_maintenance.md)
corrected the convenience workflow's keyword-only invocation and removed the
unnecessary shared temporary profile used during worker initialisation.
Four-worker profile resolution now passes without changing the registered
scientific identity, any compact evidence byte or any checkpoint. The
completed scientific run remains the unchanged serial execution described
above; maintenance did not rerun it.

## 23. Comparison boundary

The earlier null and present result are qualitatively consistent: recovery
cannot rescue positions after immediate closure, but it can do so when
empirical arrivals and capacity preserve unresolved inventory. No formal
cross-study effect estimate is reported.

## 24. Next boundary

The operational maintenance boundary and the subsequent
[final multi-collateral input freeze and integration
validation](../validation/multicollateral_integration.md) are complete. That
validation retained the same one-system capacity contract under simultaneous
ETH, WBTC and counterfactual stable-proxy demand. The next scientific boundary
is:

> Pre-register and execute the final hierarchical multi-collateral
> experiments: idiosyncratic diversification, stress correlation,
> stable-collateral trade-off and shared keeper capacity.

Oracle-delay closure, population robustness, final multi-collateral
experiments and held-out final validation remain incomplete. The constrained
ETH evidence remains a historical single-collateral result and is not a
portfolio ranking.
