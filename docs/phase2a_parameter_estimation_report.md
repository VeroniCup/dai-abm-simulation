# Phase 2A Parameter Estimation Report

## Scope

Phase 2A estimates only quantities identifiable from the completed Phase
1A--1D market, gas, liquidation and protocol datasets. It does not alter
simulator configuration or estimate vault-owner behaviour. The authoritative
plan contains 56 numbered parameter subsections, although the commissioning
brief referred to 55; all 56 were audited.

## Datasets and sample split

The continuous hourly coverage is 2021-06-01 00:00 UTC to 2024-07-01 00:00
UTC, exclusive. The FTX interval 2022-11-01 to 2022-11-21 is withheld from all
thresholds and candidate estimates and is used only for validation
diagnostics. All inputs passed manifest dimension and SHA-256 checks.

## Implemented estimators

- aligned empirical ETH, WBTC, USDC and DAI hourly return distributions;
- Pearson, Spearman and covariance matrices by two-state regime;
- moving-block-bootstrap uncertainty and a 168-hour candidate block;
- the documented two-of-six normal/stress classifier;
- gas-price, base-fee, priority-fee, utilisation and failure distributions;
- liquidation count overdispersion and Poisson/negative-binomial benchmarks;
- auction, throughput, keeper-transaction gas and USD-cost distributions; and
- exact-ilk, effective-dated Phase 1D protocol histories.

## Key candidate evidence

The calibration sample contains 24,055 normal hours
and 2,489 stress hours. Estimated stress entry,
exit and persistence probabilities are
0.044776,
0.432704 and
0.567296, respectively.

There are 1,287
clean successful-Take transactions in the calibration sample. Their
transaction-level USD gas-cost median is 72.4294; this remains a
candidate distribution and has not been written to `LiquidationConfig`.

## Three-state assessment

The provisional four-condition panic candidate accounts for
0.7685% of calibration hours across
145 runs. A three-state model is not
adopted because incremental held-out improvement has not been demonstrated.

## Parameter status

The audit statuses are:

- `blocked_pending_phase1e_b`: 10
- `literature_required`: 1
- `phase2a_estimable`: 11
- `protocol_constant`: 4
- `requires_model_calibration`: 15
- `scenario_only`: 15

Blocked or deferred parameters have no numerical placeholders.

## Uncertainty and diagnostics

Moving-block-bootstrap percentile intervals use a fixed seed and 200
replications. Count-model diagnostics retain the empirical distribution as the
primary representation where zero activity dominates. Protocol settings are
deterministic effective states rather than sampled averages.

The liquidation-volume calibration q90 is
0 DAI because
liquidation hours are sparse; the threshold is retained transparently rather
than adjusted after inspection. There are
4 successful
Take transactions with observed top-level gas price equal to zero. They remain
unchanged and require sensitivity review before a gas-cost candidate is
adopted.

Figures generated for review:

- `outputs/estimation/phase2a/regime_timeline.png`
- `outputs/estimation/phase2a/gas_by_regime.png`
- `outputs/estimation/phase2a/liquidation_activity.png`

## Outputs

- `data/processed/estimation/phase2a/diagnostics/calibration_validation_split.csv` (2 x 5, SHA-256 `e35852b25e09fe65347d341c4e6382d8973fa2b64b996f3af615a9d881d8a574`)
- `data/processed/estimation/phase2a/diagnostics/input_integrity.csv` (10 x 6, SHA-256 `a6bc68badbbd0a15803a13a184364b8fed149ef63f39ac5155c062062cbb53d2`)
- `data/processed/estimation/phase2a/diagnostics/regime_thresholds.csv` (6 x 4, SHA-256 `843049bcd1be163e3045c796d2b1a231eb59971f97db19284b56e6bdf29b0161`)
- `data/processed/estimation/phase2a/diagnostics/validation_gates.csv` (5 x 3, SHA-256 `a5a6726686b732302cdf81922fee021fb33eca1c3020c854e95ba14f229d16cd`)
- `data/processed/estimation/phase2a/gas/gas_distribution.csv` (42 x 17, SHA-256 `2c1548c9a7a9ed242479d028253ad1b960c8b29cd8bf59efa9b9e791579cde11`)
- `data/processed/estimation/phase2a/gas/gas_market_dependence.csv` (128 x 7, SHA-256 `c595c17eddcb00b98f05bd630e51ffbcc11f1e9045d0353e1e67ace9dac2aba2`)
- `data/processed/estimation/phase2a/gas/gas_sampling_index.csv` (27,024 x 6, SHA-256 `c722a29370672c26b10c90b951f2bac7510eee45d4e1902c6267e65417760524`)
- `data/processed/estimation/phase2a/liquidations/auction_distribution.csv` (234 x 18, SHA-256 `9d6bf9af08cae15991fa8f757f3262216bcf266c1592687cd1d83e54542a4823`)
- `data/processed/estimation/phase2a/liquidations/hourly_liquidation_summary.csv` (504 x 18, SHA-256 `d329c68b1e98d7bd33408fb3d6e5a2828e655e998aa65fd1076e209beef4e307`)
- `data/processed/estimation/phase2a/liquidations/liquidation_count_models.csv` (9 x 16, SHA-256 `caa38fffea0028c3566241dfead9f53a2feadff50094b0d7bd2c5c2a80ff02c2`)
- `data/processed/estimation/phase2a/liquidations/liquidation_transaction_gas.csv` (1,316 x 35, SHA-256 `137a17b8752bc90b0ac83b2f9593684781d598d340bb6be65afcab6b624c03a0`)
- `data/processed/estimation/phase2a/liquidations/liquidation_transaction_gas_summary.csv` (21 x 16, SHA-256 `7bc4026e7b35c24bf5c8cba688f3a6a24357b95e2e737e3d7d90dad5c26f9e5d`)
- `data/processed/estimation/phase2a/market/absolute_return_autocorrelation.csv` (243 x 5, SHA-256 `823e07a0f253f92dab07d02dcdd45dc4c022e9fc074bcabeb049a5277ef5fa30`)
- `data/processed/estimation/phase2a/market/dai_peg_distribution.csv` (8 x 16, SHA-256 `6eabeef59b75f098ae95dc4160db7bc658a691c5b189609bfe2bec7f8e824f9c`)
- `data/processed/estimation/phase2a/market/dependence_matrices.csv` (288 x 7, SHA-256 `4ecec5591d09bce133adf232bcac437edf0dcb7141945d5d38ea2cba10e72338`)
- `data/processed/estimation/phase2a/market/initial_prices.csv` (8 x 4, SHA-256 `63213ce64f21c4a5df71f5dd46b2ef4e1e852649e6b88e1f4cf0d5ddd2f4bd0f`)
- `data/processed/estimation/phase2a/market/return_block_index.csv` (26,210 x 6, SHA-256 `53ff7b1d5ad9153e4f988208ca68eaa9cfb09332c7feeb65be8207354490c151`)
- `data/processed/estimation/phase2a/market/return_bootstrap_uncertainty.csv` (16 x 9, SHA-256 `593ebfc59e74901edcb347d03e1108cccf7d21a67e86d87c0bc2d09429701f4b`)
- `data/processed/estimation/phase2a/market/return_distribution.csv` (24 x 19, SHA-256 `cd5e2b001f68340ff8f0ad3d5d49214a48f7ff25b963cb171f457f44b4420c26`)
- `data/processed/estimation/phase2a/parameter_status.csv` (56 x 10, SHA-256 `314275a1ccb79d1813fa1bbbed66c963af404b19b472cf23750efbecc98c329d`)
- `data/processed/estimation/phase2a/protocol/collateral_activation_periods.csv` (6 x 4, SHA-256 `653ccfb580f91ecde40f3d165df178e342db41f32370fc23841dd1b2ec37d2a2`)
- `data/processed/estimation/phase2a/protocol/protocol_change_counts.csv` (93 x 4, SHA-256 `71cfdef59b3d36d6e8111474d3ed7fcbbdd178ee0462f403f453e6ddd0238f21`)
- `data/processed/estimation/phase2a/protocol/protocol_parameter_summary.csv` (78 x 10, SHA-256 `793c3c8d60b3413970c06f507113f3ff9db531e24e8e765e4e6156c0540fffc3`)
- `data/processed/estimation/phase2a/regimes/hourly_regimes.csv` (27,024 x 12, SHA-256 `3e8bab94b22e2b3c35484b612f1fdf5df12a6f2cac5e006683aae42159913753`)
- `data/processed/estimation/phase2a/regimes/regime_durations.csv` (2,156 x 5, SHA-256 `b8a543395e1138848deb08039c9b6bce3a60c24954874f98dff40df2ff87f63f`)
- `data/processed/estimation/phase2a/regimes/regime_prevalence.csv` (2 x 3, SHA-256 `9d928ed1f2c7dcff4be241cf0d43a2773953f52856593b27dfbf30c13380c734`)
- `data/processed/estimation/phase2a/regimes/regime_transitions.csv` (4 x 4, SHA-256 `f42d753656e16073d5dee8af39a7e45347662021ed033160d3d501d9fdadf4e1`)
- `data/processed/estimation/phase2a/phase2a_candidate_parameters.json` (64 x 19, SHA-256 `fae0583fd2dc8a477df49d5954c80c486a209f8d3df963d779e5fe289fa5972d`)

## Limitations

Phase 2A cannot identify vault-size, leverage, owner intervention or
population-composition parameters without Phase 1E-B. Manager identities are
not beneficial-owner identities. Phase 1C bad debt is retained as a proxy.
Top-level transaction gas is not inner-call gas. Behavioural DAI, confidence,
panic and unobserved keeper-risk coefficients require later model calibration.

## Recommended next step

Review the candidate registry and threshold sensitivity, then acquire the
highest-information Phase 1E-B windows before estimating vault-population
parameters. Simulator YAML values and mechanics should remain unchanged until
that review is complete.
