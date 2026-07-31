# Experiment B — correlated stress

## 1. Purpose

Experiment B is the second completed component of the pre-registered final
dissertation experiment programme. It addresses RQ4 and the correlated-stress
part of H3:

> Do the diversification benefits observed under isolated shocks persist,
> weaken or reverse when ETH and WBTC are stressed together?

Experiment A remains unchanged and supplies the separate isolated-shock
benchmark. Experiment B does not compare formally with Experiment A because
the registered shock families and treatment designs differ.

The registered Experiment B result is
`H3_correlation_deterioration_supported`. This classification concerns the
relative diversification advantage across the two frozen treatment bundles;
it is not a pure causal estimate of a correlation coefficient.

## 2. Frozen design

The eight-cell design crosses four portfolios:

- `eth_only`;
- `empirical_crypto`;
- `balanced_crypto`; and
- `stable_supported`;

with two shocks:

- `joint_crypto_empirical_stress`; and
- `joint_crypto_high_correlation`.

Each cell has 128 replications, giving 1,024 substantive simulations. The
common settings are 500 vaults, 2.5 million DAI of initial debt, target system
collateralisation of 3.6089387701260205, system-wide keeper capacity 26,
`direct_cost_only`, `risk_cost_rate = 0`, Stage 1-only confidence, zero oracle
delay and the registered full-week recovery path. The horizon is 768 hours:
48 pre-shock hours and 720 post-shock hours.

No stable depeg, capacity sensitivity, positive keeper hurdle, persistent
confidence, oracle-delay treatment, held-out interval or USDC/SVB observation
enters the design.

## 3. Registered stress treatments and path diagnostics

The empirical treatment uses the selected block ending
12 May 2022 06:00 UTC. Its exact 24-hour gas sequence is embedded at
simulation hours 48–71; ordinary sampled gas is retained outside that
interval. The high-correlation treatment uses the frozen smooth ETH and WBTC
kernels with a common onset and ordinary sampled gas. The stable multiplier
remains ordinary in both treatments.

Across the 128 paired path realisations, the principal mean diagnostics are:

| Diagnostic | Empirical joint stress | Registered high-correlation treatment |
| --- | ---: | ---: |
| Minimum 24-hour ETH log return | -0.272717 | -0.160552 |
| Minimum 24-hour WBTC log return | -0.166071 | -0.124467 |
| ETH–WBTC return correlation over the registered stress window | 0.978962 | 0.960282 |
| Hours with both treatment returns negative | 44.4688 | 53.6797 |
| Maximum simultaneous drawdown | 0.357871 | 0.211247 |
| Mean gas price in the owned stress component, gwei | 180.335 | 49.0867 |

Both treatments pass their registered path definitions, stable-path
isolation and final-validation exclusion. The empirical source block has
ETH–WBTC return correlation 0.971634 and 16 joint-negative hours.

The labels must be interpreted with care. The registered high-correlation
treatment has more joint-negative treatment hours, but the realised
full-window Pearson correlation is not higher than in the empirical bundle,
and the empirical bundle has larger absolute drawdowns and owns stressed gas.
The frozen kernels also differ in severity and recovery. Experiment B
therefore identifies deterioration across two registered bundled treatments,
not an otherwise identical intervention that varies correlation alone.

## 4. Common random numbers and execution

Within each replication all eight cells share:

- the master initialisation key and nested collateral-family draws;
- portfolio state across the two shock treatments;
- ordinary market-block draws;
- liquidation-arrival draws;
- Stage 1 residual blocks; and
- keeper gas-unit draws.

The empirical stress block alone owns its registered gas-price replacement.
Gas-unit randomness remains common, while gas-component and gas-environment
checksums deliberately differ between the two treatments.

The registered four-worker command completed all 128 atomic checkpoints.
Every checkpoint contains the eight cells in frozen shock-first order. The
audit reports:

- valid checkpoints: 128;
- missing, duplicate and orphan checkpoints: 0;
- completed substantive simulations: 1,024;
- failed or rerun replications: 0;
- detailed output size: 7,680,899 bytes; and
- Experiment A simulations executed: 0.

The persisted checkpoint write span was 399.982 seconds. Because the first
compact-evidence build failed after the matrix had completed, the original
in-memory timer was not emitted. The benchmark records a transparent
412.800-second reconstruction from that span plus one median four-worker
completion cycle, corresponding to approximately 2.481 simulations per
second. This timing qualification is operational and does not affect any
scientific result.

## 5. Operational metrics

The operational primary solvency metrics are:

- backlog-area share;
- liquidated-debt share; and
- maximum unresolved-tab share.

Realised-bad-debt share, positive realised bad debt and terminal active
bad-debt share are degenerate under the canonical close-factor-one
accounting boundary. They remain reported but do not determine B1 or B2.
All five registered peg metrics and the remaining liquidation metrics are
operational.

## 6. Mean system outcomes

The three operational solvency outcomes below retain their registered
definitions. Backlog area is a debt-normalised DAI-hour measure rather than a
point-in-time percentage.

| Shock | Portfolio | Backlog-area share | Liquidated-debt share | Maximum unresolved-tab share | Mean capacity rejections |
| --- | --- | ---: | ---: | ---: | ---: |
| Empirical | `eth_only` | 0.191977 | 0.077898 | 0.052169 | 0.4766 |
| Empirical | `empirical_crypto` | 0.120178 | 0.055617 | 0.037358 | 0.1953 |
| Empirical | `balanced_crypto` | 0.039977 | 0.014911 | 0.010061 | 0.0703 |
| Empirical | `stable_supported` | 0.028256 | 0.011548 | 0.008350 | 0 |
| High correlation | `eth_only` | 0.090323 | 0.046003 | 0.029212 | 0.0156 |
| High correlation | `empirical_crypto` | 0.071594 | 0.035213 | 0.019641 | 0.0156 |
| High correlation | `balanced_crypto` | 0.023400 | 0.010369 | 0.004519 | 0 |
| High correlation | `stable_supported` | 0.022532 | 0.006195 | 0.006816 | 0 |

Absolute losses are generally larger in the empirical bundle. B2 does not
compare those absolute levels directly: it asks whether each diversified
portfolio's paired advantage over `eth_only` becomes smaller in the second
registered bundle.

All eight cells have the same mean registered peg outcomes:

- below-peg burden: 0.259221;
- mean absolute peg deviation: 0.000597776;
- minimum DAI price: 0.995900;
- restricted mean recovery time: 82.4453 hours; and
- recovery probability by 720 hours: 0.984375.

## 7. Portfolio contrasts and diversification advantage

The compact evidence retains all 168 raw paired portfolio contrasts with
their mathematical signs. It also contains 84 direction-normalised
advantages and 42 paired deterioration interactions.

Under empirical joint stress, all three diversified portfolios have positive
advantages with 95% intervals above zero on backlog area, liquidated debt and
maximum unresolved tab. Mean advantages over `eth_only` are:

| Portfolio | Backlog area | Liquidated debt | Unresolved tab |
| --- | ---: | ---: | ---: |
| `empirical_crypto` | 0.071799 | 0.022280 | 0.014811 |
| `balanced_crypto` | 0.152000 | 0.062987 | 0.042107 |
| `stable_supported` | 0.163721 | 0.066350 | 0.043819 |

Under the registered high-correlation treatment, the corresponding means are:

| Portfolio | Backlog area | Liquidated debt | Unresolved tab |
| --- | ---: | ---: | ---: |
| `empirical_crypto` | 0.018729 | 0.010790 | 0.009571 |
| `balanced_crypto` | 0.066923 | 0.035634 | 0.024694 |
| `stable_supported` | 0.067791 | 0.039808 | 0.022396 |

The `empirical_crypto` backlog-area interval includes zero in the second
treatment; its liquidated-debt and unresolved-tab intervals remain
beneficial. No high-correlation reversal flag is set.

## 8. Correlation-deterioration interactions

The interaction is empirical-bundle advantage minus high-correlation-bundle
advantage. A positive value means the relative diversification benefit is
smaller in the high-correlation treatment.

| Portfolio | Backlog-area interaction (95% CI) | Liquidated-debt interaction (95% CI) | Unresolved-tab interaction (95% CI) |
| --- | ---: | ---: | ---: |
| `empirical_crypto` | 0.053070 [0.019723, 0.086417] | 0.011490 [0.004152, 0.018829] | 0.005239 [-0.002750, 0.013228] |
| `balanced_crypto` | 0.085076 [0.047277, 0.122876] | 0.027353 [0.018233, 0.036473] | 0.017414 [0.006471, 0.028356] |
| `stable_supported` | 0.095930 [0.058164, 0.133696] | 0.026541 [0.017177, 0.035906] | 0.021423 [0.011425, 0.031420] |

Every portfolio satisfies the registered B2 rule: at least two operational
metrics deteriorate clearly and no material opposite result reverses the
interpretation. None satisfies the stronger reversal rule.

## 9. Collateral transmission and shared capacity

ETH and WBTC both contribute unsafe or liquidation activity in all three
mixed-collateral portfolios under the high-correlation treatment. Both
families contribute positive backlog area. Mean high-correlation backlog
contributions are:

- `empirical_crypto`: ETH 89.6%, WBTC 10.4%;
- `balanced_crypto`: ETH 58.2%, WBTC 41.8%; and
- `stable_supported`: ETH 88.3%, WBTC 11.7%.

Shared capacity is operational but rarely binding. Positive displacement
appears for `empirical_crypto` only, with a mean of 0.015625 displaced ETH
candidates per replication. No portfolio has a higher mean simultaneous
ETH–WBTC unsafe-hour share in the high-correlation bundle; the paired changes
are negative for all three portfolios.

Consequently, every mixed portfolio satisfies at least two of the four
registered transmission conditions, but none satisfies all four. B3 is
`transmission_mixed`, not `transmission_intensifies`.

## 10. Registered decisions

### B1 — diversification under empirical joint stress

All three diversified portfolios satisfy the beneficial rule on all three
operational solvency metrics. B1 is `supported`.

### B2 — deterioration across the registered stress bundles

All three diversified portfolios satisfy the deterioration rule, and no
portfolio has a two-metric reversal. B2 is
`correlation_deterioration_present`.

### B3 — cross-collateral stress transmission

All three mixed portfolios show ETH and WBTC activity and positive backlog in
at least two families. Displacement and simultaneous-unsafe intensification
are not systematic. B3 is `transmission_mixed`.

### Portfolio persistence

`empirical_crypto`, `balanced_crypto` and `stable_supported` are each
classified `weakens_but_remains`. This is descriptive and does not rank or
select them.

### Overall H3 and peg relationship

The registered overall result is
`H3_correlation_deterioration_supported`. The registered peg–solvency
relationship is `solvency_deteriorates_peg_unchanged`.

This completes only the correlated-crypto component of H3. The
stable-collateral impairment and contagion component belongs to Experiment C
and remains unexecuted.

## 11. Compact-evidence ordering maintenance

After all 128 checkpoints completed, the first compact-evidence build stopped
because raw collateral rows had been loaded in lexical family order
(`ETH`, `STABLE`, `WBTC`) while the frozen evidence schema requires registry
order (`ETH`, `WBTC`, `STABLE`).

The repair is classified `evidence_row_ordering_infrastructure`. It orders
compact summary rows by the frozen cell, family and metric registries before
schema validation. It changes no simulation, checkpoint, summary value,
contrast, decision rule or registered identity. Replay is guarded by a
separate content-addressed simulation-core identity, so the evidence-only
maintenance cannot disable deterministic reconstruction from a clean clone
and any later change to replay-critical code is still rejected.

The registered scientific-code identity is
`98d7203a607a2cb38698b4b3e3b730af89ccc2742f739202a219d8c59d1f27de`.
The replay-compatible simulation-core identity is
`82e9c612de87bc93717fb0197b87eb01f23846737ce2cd96337e1f8fcfa55bdd`.
The operational source identity containing the evidence-only repair is
recorded separately in the reproducibility artefact.

## 12. Limitations

- B2 is a bundled-treatment comparison, not a pure correlation intervention.
- The empirical bundle owns a stressed gas block; the other treatment uses
  ordinary sampled gas.
- The treatment kernels differ in severity and recovery, and realised Pearson
  correlation is not ordered by the treatment labels.
- Realised bad debt is degenerate under the retained close-factor-one
  accounting boundary.
- STABLE is a counterfactual stable proxy, not empirical Maker USDC vaults.
- Shared-capacity displacement is sparse at capacity 26.
- Oracle delay remains zero and persistent confidence remains inactive.
- No portfolio or shock is ranked or selected.

## 13. Reproducibility and next boundary

Experiment identity:
`e02c035162f8178c96d2cae71d0a581ce813ab33526854bd5810e8e2810ead83`.

Seed-registry checksum:
`b6561e43f3d3682c4a117bc83ae8badfd88eaeea9a7dfccd7917a5e0e73ac950`.

The compact-evidence checksums are:

| Artefact | SHA-256 |
| --- | --- |
| Benchmark | `5338cc6cb8f51644ec7b57c394b1a7261aad1c33066af190a04c8ce6d28aa25b` |
| Cell summary | `b1975e29da3278cba665bf922b7d7746e8cb941b8d82a428c3ba262dd5832c76` |
| Collateral summary | `ed4397574529662ec641f09e3565b66a68f8195a9fcec5a47dc013b048038e7c` |
| Contrasts | `09eeebd447d6bfcb713bc3e5a6974b275529b74b8b48c17184da691f2562ab4a` |
| Decision | `dc669354d036060ce9477fdca4a863877af3a88ead73a9130d804c1a66b3add6` |
| Registry | `6c8b9984300b159c427aae350bca12756e50a50ddbe61e2597353b29949bc89b` |
| Reproducibility | `94f07e9f18b724ab9dd595c9fc8684d0f76cf29007045b4f7d8fc4d03d8fb5de` |
| Specification | `89f38e38b26426800c14f5b31a32e25aff783cf5951692adc4af0f92e870c680` |

All eight compact artefacts reconstruct byte-identically in isolated
directories, and the experiment manifest contains 43 artefacts. Experiment A
evidence and all 128 A checkpoints remain byte-identical. Experiments C–E
were not executed; no calibration, held-out validation, portfolio ranking or
runtime adoption occurred.

The next authorised scientific stage is:

> Execute Experiment C: stable-collateral trade-off using the frozen master
> programme.
