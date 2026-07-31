# Experiment D — Shared keeper capacity

## 1. Purpose and scientific boundary

Experiment D is the fourth component of the frozen final dissertation
programme. It tests RQ2 and H1 by varying only one global hourly keeper
capacity, while retaining the same portfolio state, shock path, gas path,
liquidation arrivals and DAI residual blocks within each paired replication.
It also supplies secondary RQ4/H3 evidence on cross-collateral competition
for the shared execution queue.

The registered capacities are 14, 26 and 45 liquidation opportunities per
hour. They are low, central and high sensitivity coordinates under partial
identification; they are not three separately calibrated truths. Experiment D
does not select a production capacity, change a runtime default or recalibrate
any parameter.

The experiment identity is
`b324c31be7ef6dd7f61e504709b2086b0e88ce181c177f25dcaad182095c17e3`.
It inherits master programme identity
`084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260`.

## 2. Relationship to Experiments B and C

Experiments B and C contain central-capacity cells, but their seed ownership
and scientific contrasts differ. Experiment D therefore executed new
capacity-26 observations paired directly with capacities 14 and 45. It did
not reuse or rerun any Experiment A–C checkpoint. Their compact evidence and
all 384 prior checkpoints remain byte-identical.

The three registered anchors are:

1. `empirical_crypto` under `joint_crypto_high_correlation`;
2. `stable_supported` under `joint_crypto_stable_stress`; and
3. `stable_heavy` under `joint_crypto_stable_stress`.

Cross-anchor differences are descriptive and are not interpreted as capacity
effects.

## 3. Design, common random numbers and ranking

Each anchor crosses the three capacities in anchor-first order, producing
nine cells. Each cell has 128 paired replications over 48 pre-shock and 720
post-shock hours, for 1,152 substantive simulations.

Within an anchor and replication, all capacities share:

- the portfolio initial state and latent family draws;
- ordinary market blocks and the registered shock path;
- network gas conditions and keeper gas-unit draws;
- liquidation-arrival draws;
- Stage 1 market owners and residual blocks; and
- every other non-capacity random stream.

The common-random-number and nested-initialisation audits pass. The
capacity-neutral owner checksum is identical across the three treatments in
each anchor. Once a lower capacity binds, subsequent queue paths may differ
because unresolved vault states differ; this is a treatment-mediated outcome,
not a failure of pre-treatment randomisation.

The model uses one global queue ranked by:

1. expected keeper profit, descending;
2. debt at risk, descending; and
3. vault identifier, ascending.

There is no random tie-break, collateral quota, family priority or
per-collateral capacity. Results are conditional on this frozen ranking rule.

## 4. Execution and reproducibility

The registered command was:

```text
PYTHONPATH=src python workflows/experiments/final/shared_keeper_capacity.py all --workers 4
```

The ordinary sandbox stopped before worker creation because macOS semaphore
metadata was unavailable. Fresh permission for the identical four-worker
command was then used. The completed audit reports:

- completed simulations: 1,152;
- valid checkpoints: 128;
- missing, duplicate, invalid and orphan checkpoints: 0;
- failed and rerun replications: 0;
- wall time: 564.932 seconds;
- throughput: 2.039 simulations per second; and
- detailed checkpoint output: 9,161,135 bytes.

All eight compact artefacts passed two isolated deterministic
reconstructions. The experiment manifest contains 59 records: the 51
preserved records plus the eight Experiment D artefacts.

## 5. Metric operationality and validity

All primary completion metrics are operational:

- backlog-area share;
- maximum unresolved-tab share;
- terminal unresolved-tab share; and
- liquidation-completion ratio.

Capacity rejection, utilisation, liquidation, backlog and the continuous peg
metrics are also operational. Recovery probability by 720 hours is
degenerate because every replication recovers within the registered horizon.

Realised-bad-debt share, positive realised bad debt and terminal active bad
debt are degenerate under the retained close-factor-one accounting boundary.
They remain in evidence but do not determine D1–D3. Consequently, H1's
bad-debt component cannot be evaluated here. Zero realised bad debt is not
evidence that capacity could never affect insolvency risk under another
accounting or population boundary.

There are zero numerical, accounting, path, capacity and checkpoint failures.
Family values reconcile to system values, no candidate is selected twice in
an hourly queue, and no selected count exceeds the one system-wide capacity.

## 6. System outcomes

Backlog area is a debt-normalised DAI-hour measure rather than a
point-in-time percentage.

| Anchor | Capacity | Backlog area | Maximum unresolved tab | Completion ratio | Mean rejections | Binding hours |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Empirical crypto / high correlation | 14 | 0.080584 | 0.019651 | 0.895014 | 1.0625 | 0.1484 |
| Empirical crypto / high correlation | 26 | 0.080084 | 0.019651 | 0.895117 | 0.1406 | 0.0234 |
| Empirical crypto / high correlation | 45 | 0.080084 | 0.019651 | 0.895117 | 0 | 0 |
| Stable supported / combined stress | 14 | 0.024525 | 0.007654 | 0.851403 | 0.0781 | 0.0234 |
| Stable supported / combined stress | 26 | 0.024497 | 0.007654 | 0.851403 | 0 | 0 |
| Stable supported / combined stress | 45 | 0.024497 | 0.007654 | 0.851403 | 0 | 0 |
| Stable heavy / combined stress | 14 | 0.003013 | 0.001013 | 0.763128 | 0 | 0 |
| Stable heavy / combined stress | 26 | 0.003013 | 0.001013 | 0.763128 | 0 | 0 |
| Stable heavy / combined stress | 45 | 0.003013 | 0.001013 | 0.763128 | 0 | 0 |

The terminal unresolved-tab means are capacity-invariant within every
anchor. Mean liquidated-debt shares are 0.040216, 0.010241 and 0.001838 for
the empirical-crypto, stable-supported and stable-heavy anchors at capacity
45; moving to capacity 14 changes only the empirical-crypto value slightly,
to 0.040211.

## 7. Capacity utilisation

The low-capacity empirical-crypto cell has mean all-hour utilisation 0.002224,
mean positive-demand utilisation 0.110580, mean maximum utilisation 0.276786
and a positive-demand binding share of 0.006718. At capacity 45 these values
are 0.000711, 0.035332, 0.101910 and zero respectively.

The stable-supported low-capacity cell binds in only 0.001299 of
positive-demand hours on average. No stable-heavy cell binds. Low average
utilisation does not by itself establish irrelevance: rare empirical-crypto
peaks generate the one clearly positive backlog-area contrast.

## 8. Raw contrasts, capacity relief and monotonicity

Raw contrasts preserve `capacity 14 − capacity 26`, `26 − 45` and
`14 − 45`. Direction-normalised relief multiplies each metric by its
pre-registered direction so that a positive value always means improvement
from higher capacity.

For the empirical-crypto anchor, low-to-high relief is:

| Metric | Relief 14→45 | 95% interval | Classification |
| --- | ---: | ---: | --- |
| Backlog-area share | 0.0004996 | [0.0000046, 0.0009945] | `threshold_relief` |
| Maximum unresolved-tab share | 0.00000095 | [-0.00000047, 0.00000237] | `no_capacity_effect` |
| Terminal unresolved-tab share | 0 | [0, 0] | `no_capacity_effect` |
| Completion ratio | 0.0001033 | [-0.0000507, 0.0002573] | `no_capacity_effect` |
| Rejected opportunities | 1.0625 | [0.1838, 1.9412] | operational |

The capacity-14 to capacity-26 step owns the backlog relief; the 26-to-45
step is zero. This is a threshold pattern, not evidence for a smooth
production-capacity optimum.

For stable supported, low-to-high backlog relief is 0.0000277 with interval
[-0.0000215, 0.0000769], and the other three primary reliefs are zero. All
four stable-heavy reliefs are zero. Peg contrasts are exactly zero within
every anchor for below-peg burden, mean absolute peg deviation, minimum DAI
price, restricted recovery time and recovery probability.

## 9. Collateral decomposition and displacement

At empirical-crypto capacity 14 relative to 45, mean ETH rejections increase
by 1.0313 [0.1943, 1.8682] and WBTC rejections by 0.0313
[-0.0171, 0.0796]. Mean ETH backlog area increases by 1,189.60 DAI-hours
[30.17, 2,349.02], while the WBTC increase of 59.33 DAI-hours has an interval
crossing zero. ETH and WBTC both have observed rejected or displaced
candidates. Mean ETH cross-family displacement hours increase by 0.1172 and
WBTC by 0.0234.

The stable-supported low-capacity treatment has sparse ETH rejection and
displacement; its low-to-high ETH backlog contrast is 69.15 DAI-hours with an
interval crossing zero. The stable-heavy anchor has no rejection or
displacement contrast. STABLE does not consume or lose an identifiable
capacity slot in these paired low-to-high contrasts.

The data identify family-level selected, rejected and displaced activity, but
do not uniquely identify a pairwise
\(Displacement_{i\leftarrow j}\) matrix. No pairwise attribution is invented.

## 10. Registered decisions

Anchor-level relief statuses are:

- empirical crypto / high correlation: `capacity_relief_partial`;
- stable supported / combined stress: `capacity_relief_not_supported`; and
- stable heavy / combined stress: `capacity_relief_not_supported`.

D1 is `not_supported`. Only one of four primary metrics in one anchor has a
clear low-to-high relief, so the registered capacity-relief rule is not met.

D2 is `shared_capacity_transmission_mixed`. The empirical-crypto anchor meets
the full rule through increased total rejection, ETH/WBTC rejection or
displacement and clear ETH backlog transmission. Stable supported provides
only partial sparse transmission, while stable heavy provides none. This is
secondary H3 evidence and is conditional on the frozen global ranking.

D3 is `peg_unchanged`. All operational peg paths and contrasts are identical
across capacity within each anchor.

The overall classification is `H1_no_clear_shared_capacity_effect`.
The peg–solvency relationship is `neither_materially_changes`. Although a
small threshold backlog effect is present in the empirical-crypto anchor, it
does not satisfy the registered completion rule and does not reach the peg
mechanism. A backlog effect without a peg effect could provide only partial,
not full, H1 support; here the registered evidence is weaker still.

Cross-anchor sensitivity is metric-specific. The empirical-crypto anchor is
more sensitive on backlog area, maximum unresolved tab and completion ratio,
while terminal unresolved tab is similarly insensitive.

## 11. Limitations

- Capacity is partially identified and evaluated only at three registered
  sensitivity coordinates.
- Binding is rare and concentrated in the empirical-crypto anchor.
- The STABLE family is counterfactual and its combined-stress path is
  scenario-defined.
- Pairwise displacement is not uniquely identifiable from the queue data.
- Realised bad debt is degenerate under close-factor-one accounting.
- Stage 1 market dynamics do not transmit the small capacity-driven backlog
  differences into different DAI paths.
- The conclusions are conditional on 500 frozen high-collateralisation
  vaults, direct-cost-only participation, zero oracle delay and the frozen
  global ranking.

These limitations are reported rather than used to alter the registered
population, capacities, hurdle, ranking or accounting.

## 12. Reproducibility and next boundary

The specification checksum is
`10d7bd2062d6d52b03941c90558dded45954fb8ffbf1a501dc0dd05e4f2b28e0`,
the seed-registry checksum is
`74a6a4b46237bf1b1eecbda0aefef4e4dab6e72da508823dc18e190ce7d169ce`,
the scientific-code identity is
`6620759e268b79dbe71cf0e0a4a2848b6f6ac50272c9338276b3ea08300afae1`,
and the simulation-core identity is
`7c1fd91903663779bb30c5b98448b1eac9ab2d426e17e9f6f47fb5db30a5dba4`.

Compact evidence is registered in
`data/provenance/experiments/final/shared_keeper_capacity/`. Detailed
checkpoints remain ignored under the matching semantic output identity. No
held-out or USDC/SVB data were used, no parameter was recalibrated, no
capacity was ranked or selected, and no runtime profile changed.

Experiment E remains unexecuted and blocked. The next authorised scientific
stage is the result-blind oracle-delay freeze required before Experiment E.
H4 synthesis remains pending.
