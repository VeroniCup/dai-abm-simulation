# Experiment C — stable-collateral trade-off

## 1. Purpose

Experiment C is the third completed component of the pre-registered final
dissertation experiment programme. It addresses RQ4 and the stable-collateral
part of H3:

> Does a stable allocation protect the system from joint crypto stress, and
> when does impairment of that allocation create depeg or shared-capacity
> costs?

Experiments A and B remain unchanged. They established diversification
support under isolated shocks and support that weakens across the two
registered correlated-stress bundles. Experiment C tests the remaining
stable-proxy boundary. Its registered result is
`H3_stable_tradeoff_partially_supported`.

## 2. Stable-proxy boundary

The STABLE family is `counterfactual_stable_proxy`. It is not an empirically
reconstructed Maker USDC vault population. Its liquidation ratio is 1.10,
its liquidation penalty is 0.05 and its ordinary price is the clean stable
proxy. The 0.95 and 0.90 depeg floors are scenario-defined. USDC/SVB and
held-out validation data were not used.

The experiment therefore identifies behaviour within the frozen model and
scenario registry. It does not identify an optimal historical Maker
portfolio, and no portfolio or stable share is ranked or selected.

## 3. Frozen design

The twelve cells cross three portfolios:

- `empirical_crypto`: 84.8394% ETH and 15.1606% WBTC;
- `stable_supported`: 63.6296% ETH, 11.3704% WBTC and 25% STABLE; and
- `stable_heavy`: 42.4197% ETH, 7.5803% WBTC and 50% STABLE;

with four shocks:

- `joint_crypto_high_correlation`;
- `stable_depeg_moderate`, with a 0.95 floor and 72-hour recovery;
- `stable_depeg_severe`, with a 0.90 floor and 168-hour recovery; and
- `joint_crypto_stable_stress`, combining the frozen joint crypto and severe
  stable treatments.

Every cell uses 128 common-random-number replications, giving 1,536
substantive simulations. Fixed settings are 500 vaults, 2.5 million DAI of
initial debt, target system collateralisation 3.6089387701260205, shared
keeper capacity 26, `direct_cost_only`, Stage 1-only confidence, zero oracle
delay and a 768-hour horizon.

## 4. Common random numbers and isolation

Within a replication, the twelve cells share nested family vault draws,
initialisation keys, ordinary market blocks, gas-unit draws, liquidation
arrivals and Stage 1 residual blocks. The shock registry alone owns
treatment price paths. Portfolio initial states are identical across shocks,
and the ordered family streams are prefix-nested across portfolio sizes.

The zero-STABLE `empirical_crypto` portfolio provides the isolation control.
Moderate and severe stable-only shocks produce identical system outcomes for
this portfolio. Its joint crypto cell is also identical with and without the
stable shock component. There is no registered non-vault stable-price
channel. All 128 negative-control audits pass.

## 5. Execution and reproducibility

The registered command was:

```text
PYTHONPATH=src python workflows/experiments/final/stable_collateral_tradeoff.py all --workers 4
```

The ordinary sandbox stopped before worker creation because macOS semaphore
metadata was unavailable. After fresh permission for the same command, four
workers completed all 128 atomic checkpoints. The audit reports:

- completed simulations: 1,536;
- valid checkpoints: 128;
- missing, duplicate, invalid and orphan checkpoints: 0;
- failed and rerun replications: 0;
- detailed output: 11,487,194 bytes; and
- A, B, D and E simulations executed: 0.

The original orchestration stopped after checkpoint creation because host
timing appended after the scientific checksum was initially validated as
scientific payload. The validator boundary was corrected, all checkpoints
were recovered locally without rewriting or rerunning them, and evidence was
then reconstructed. The original timer was not preserved; the transparent
510.179-second benchmark combines the checkpoint-write span with one median
worker completion time. It implies approximately 3.011 simulations per
second.

The compact reporting pass also completed the already pre-registered
stable-attributed and exposure-normalised gradient rows, and corrected
reachability of the registered C3 `contagion_not_present` branch. Neither
repair changed a checkpoint, scientific identity, registered rule or
classification.

## 6. Metric operationality and validity

Operational primary solvency metrics are:

- backlog-area share;
- liquidated-debt share; and
- maximum unresolved-tab share.

Realised-bad-debt share, positive realised bad debt and terminal active bad
debt are degenerate under close-factor-one accounting. They remain reported
and do not determine C1–C3. All registered peg metrics are reported; recovery
probability is degenerate in this matrix.

There are zero numerical, accounting, CRN, price-isolation, registry,
negative-control and checkpoint failures. Family totals reconcile to system
totals under one shared capacity.

## 7. Mean system outcomes

Backlog area is a debt-normalised DAI-hour measure, not a point-in-time
percentage.

| Shock | Portfolio | Backlog-area share | Liquidated-debt share | Unresolved-tab share | Capacity rejections |
| --- | --- | ---: | ---: | ---: | ---: |
| Joint crypto | `empirical_crypto` | 0.078149 | 0.033649 | 0.016280 | 0.015625 |
| Joint crypto | `stable_supported` | 0.032773 | 0.010937 | 0.007932 | 0 |
| Joint crypto | `stable_heavy` | 0.005734 | 0.001819 | 0.001105 | 0 |
| Moderate depeg | `empirical_crypto` | 0.066980 | 0.030241 | 0.014216 | 0.023438 |
| Moderate depeg | `stable_supported` | 0.032527 | 0.008587 | 0.006257 | 0 |
| Moderate depeg | `stable_heavy` | 0.004888 | 0.001757 | 0.000957 | 0 |
| Severe depeg | `empirical_crypto` | 0.066980 | 0.030241 | 0.014216 | 0.023438 |
| Severe depeg | `stable_supported` | 0.032527 | 0.008587 | 0.006257 | 0 |
| Severe depeg | `stable_heavy` | 0.004888 | 0.001757 | 0.000957 | 0 |
| Joint crypto–stable | `empirical_crypto` | 0.078149 | 0.033649 | 0.016280 | 0.015625 |
| Joint crypto–stable | `stable_supported` | 0.032776 | 0.010953 | 0.007932 | 0 |
| Joint crypto–stable | `stable_heavy` | 0.005739 | 0.001834 | 0.001105 | 0 |

All twelve cells have the same mean below-peg burden (0.262733), mean
absolute peg deviation (0.000600), minimum DAI price (0.995929) and mean
restricted recovery time (61.9297 hours).

## 8. C1 — crypto-risk buffering

Under joint crypto stress, both stable-backed portfolios have positive
direction-normalised advantages with 95% intervals above zero on all three
operational solvency metrics.

| Portfolio | Backlog advantage (95% CI) | Liquidated-debt advantage (95% CI) | Unresolved-tab advantage (95% CI) |
| --- | ---: | ---: | ---: |
| `stable_supported` | 0.045376 [0.010150, 0.080602] | 0.022712 [0.012236, 0.033188] | 0.008348 [0.001140, 0.015556] |
| `stable_heavy` | 0.072415 [0.036192, 0.108637] | 0.031830 [0.019405, 0.044255] | 0.015175 [0.008540, 0.021810] |

No operational bad-debt metric has a clear adverse effect. C1 is
`supported`.

## 9. C2 — depeg cost and exposure gradient

The depeg treatments activate stable liquidation in only one replication of
128 for each stable-backed portfolio. Mean stable liquidated debt is 40.178
DAI for `stable_supported` and 39.493 DAI for `stable_heavy`; mean stable
backlog, capacity rejection and displacement are zero. The moderate and
severe treatments therefore have identical registered system outcomes and
zero severity increments on the operational metrics.

Greater stable exposure does not produce the registered adverse system
gradient under severe depeg. Heavy-minus-supported means are:

| Gradient level | Backlog | Liquidated debt | Unresolved tab |
| --- | ---: | ---: | ---: |
| Raw system share | -0.027638 [-0.049067, -0.006210] | -0.006830 [-0.011390, -0.002270] | -0.005300 [-0.009472, -0.001129] |
| STABLE-attributed raw amount | 0 | -0.685 [-2.026, 0.657] | 0 |
| STABLE exposure-normalised | 0 | -0.0000327 [-0.0000968, 0.0000314] | 0 |

The raw system gradient is clearly opposite to the registered adverse
direction, while stable-attributed and exposure-normalised evidence does not
provide a clear adverse gradient or a clear statistical explanation. No
stable-backed portfolio receives a direct depeg benefit: the system
differences reflect frozen portfolio composition and ordinary crypto
activity, not a beneficial stable-price channel.

C2 is `depeg_exposure_gradient_inconsistent`. This is a substantive null or
opposite result under the frozen high-collateralisation population, not a
reason to retune the stable floor, liquidation ratio or portfolio shares.

## 10. C3 — joint stress, erosion and contagion

The joint-stress advantages remain positive with 95% intervals above zero on
all three operational solvency metrics for both stable-backed portfolios.
No reversal flag is set.

Trade-off erosion is very small and its 95% intervals include zero. Mean
erosion in backlog-area share is 0.000003 for `stable_supported` and
0.000005 for `stable_heavy`; mean liquidated-debt erosion is 0.000016 for
both.

The stable channel is nevertheless active in one replication. Relative to
crypto-only joint stress, mean ETH+WBTC backlog area rises by 7.317 DAI-hours
for `stable_supported` and 11.265 DAI-hours for `stable_heavy`, but both
intervals include zero. ETH+WBTC liquidated debt, maximum backlog and
capacity rejections do not change. There is no stable/crypto candidate
displacement.

This is limited transmission rather than systematic erosion or reversal. C3
is `contagion_mixed`.

## 11. Portfolio trade-off statuses and H3

Both stable-backed portfolios are
`protection_without_material_depeg_cost`. These labels are descriptive; they
do not rank or select a portfolio.

C1 supports crypto buffering, C2 rejects the registered severity and
exposure-gradient pattern, and C3 finds limited mixed transmission without
material erosion. The registered overall classification is
`H3_stable_tradeoff_partially_supported`.

The peg–solvency relationship is
`solvency_improves_peg_unchanged`: stable-backed portfolios improve the
operational solvency measures under joint crypto stress, while the Stage 1
peg outcomes remain identical.

## 12. Limitations

- STABLE is counterfactual and has no direct DAI-demand or confidence channel.
- Stable vaults begin at the common high system collateralisation target, so
  the registered depegs activate very few stable liquidations.
- The moderate and severe treatments are scenario paths, not estimates from
  USDC/SVB.
- Shared capacity is rarely binding in these cells; Experiment C does not
  replace the registered capacity treatment in Experiment D.
- Degenerate bad-debt metrics limit interpretation to the operational
  backlog, liquidation and unresolved-tab measures.
- The result is conditional on the frozen portfolio compositions and does
  not imply historical Maker portfolio optimality.

## 13. Reproducibility and next boundary

Experiment C identity:
`cb6d00877c54011cc49714bdfe23fad83140fef001568ea9b43d355811c9129b`.
The specification, registry, summaries, contrasts, decision,
reproducibility record and host benchmark are registered in
`data/provenance/experiments/final/stable_collateral_tradeoff/`.

All non-host-dependent evidence reconstructs byte-identically from the 128
ignored checkpoints. Experiments A and B remain byte-identical. Experiments D
and E did not run, no parameter was recalibrated, and no runtime default
changed.

The next authorised scientific pass is Experiment D: shared keeper capacity.
Experiment E remains blocked pending a result-independent oracle-delay
freeze. H4 synthesis remains pending.
