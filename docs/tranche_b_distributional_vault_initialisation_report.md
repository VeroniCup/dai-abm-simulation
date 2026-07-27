# Tranche B Distribution-Aware Vault Initialisation Report

## Scope

Tranche B adds an opt-in vault-initialisation interface. It does not alter
legacy default behaviour, Tranche A scalar configuration values, liquidation
mechanics, confidence mechanics, market-price mechanics, gas mechanics, auction
logic or agent decision rules.

The default simulator path remains the original Gaussian vault generator. The
new interface is used only when a caller explicitly supplies a Tranche B
configuration and passes the generated initial vaults into the simulation.

## Tranche A corrections

The Tranche A audit wording has been corrected to distinguish seven conceptual
candidates from eight configuration-field assignments. ETH and BTC
`target_debt_share` fields are one conceptual candidate represented by two
family-level assignments.

The low/high sensitivity YAML files are now described as bounded
population-and-debt-share sensitivity bundles. They are not comprehensive
sensitivity bounds for every Tranche A candidate. Confidence-threshold
sensitivity remains deferred because the candidate audit did not provide
complete numerical ranges for those fields.

The configured `max_normal_liquidatable_share = 0` value is unchanged. A future
sensitivity check must account for the fact that the smallest positive observed
share is `1 / n_vaults`.

## Empirical pool construction

The compact runtime pool is:

- `config/empirical/data/vault_initialisation_pools.csv`
- SHA-256: `5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892`

It was generated deterministically by:

- `scripts/build_vault_initialisation_pools.py`

The script verifies the validated Phase 1E-B opening-state checksums, keeps
active indebted vaults, requires valid debt, collateral ratio and liquidation
ratio fields, then calculates:

- absolute buffer = `collateral_ratio - liquidation_ratio`;
- relative buffer = `collateral_ratio / liquidation_ratio - 1`.

The pool deliberately excludes transaction hashes, owner addresses, raw event
history and other unnecessary identifiers. Opening states are used as the
primary source to avoid pseudo-replication from repeated hourly snapshots.

| Regime source | Source rows | Included rows | Main exclusions |
| --- | ---: | ---: | --- |
| quiet mature 2024-02-01 to 2024-03-01 | 3,410 | 1,886 | inactive or zero-debt vaults |
| USDC/SVB 2023-03-06 to 2023-03-20 | 3,456 | 1,934 | inactive or zero-debt vaults |
| Terra/CeFi 2022-05-05 to 2022-06-20 | 5,111 | 3,388 | inactive or zero-debt vaults |

The resulting pool contains 7,208 rows across normal, moderate-stress and
severe-stress regime labels.

## Configuration schema

The primary Tranche B configuration is:

- `config/empirical/phase2_empirical_distributional.yaml`

Fallback smoke configurations are:

- `config/empirical/sensitivity/phase2_empirical_parametric_truncated.yaml`
- `config/empirical/sensitivity/phase2_empirical_legacy_gaussian.yaml`

The new `vault_initialisation` block supports:

- `mode`;
- `seed`;
- `regime`;
- `pool_path`;
- `pool_sha256`;
- `fallback`;
- `by_ilk`;
- `minimum_exact_ilk_pool_size`;
- `allow_initial_liquidatable`;
- `sample_with_replacement`;
- `max_sampling_attempts`;
- collateral-family parametric fallback settings.

Unknown modes and unknown initialisation fields fail validation.

## Initialisation modes

Exactly three modes are supported:

1. `legacy_gaussian`;
2. `parametric_truncated`;
3. `empirical_joint`.

`legacy_gaussian` is the default and delegates to the existing
`create_initial_vaults` path.

`parametric_truncated` samples positive lognormal debt and positive absolute
buffer values by collateral family, with bounded rejection sampling. The
collateral ratio is calculated as `liquidation_ratio + absolute_buffer`.
Independent marginals are treated as a fallback only; they are not claimed to
preserve empirical joint dependence.

`empirical_joint` is the primary Tranche B design. It resamples paired debt,
collateral-ratio, buffer, family and ilk observations from the compact pool.
Debt and collateral ratio are never independently shuffled. Exact-ilk pools are
used where sufficient, with fallback to the family pool and explicit fallback
counts in provenance.

## Distribution validation

Generated diagnostics are written under the ignored directory:

- `data/processed/estimation/tranche_b/`

The bounded empirical-joint smoke sample has 500 vaults, no initially
liquidatable vaults, and preserves paired pool rows. Its sampled debt and
collateral-ratio distributions remain right-skewed, matching the qualitative
Phase 2B finding that the legacy global Gaussian interface is too narrow for
vault initialisation.

For the normal-regime empirical-joint sample:

- median debt: 28,178.929908 DAI;
- q95 debt: 1,494,986.284642 DAI;
- maximum debt: 54,531,740.622187 DAI;
- median collateral ratio: 4.011597;
- q95 collateral ratio: 34.053078;
- maximum collateral ratio: 935.934364.

The sampled debt-buffer Pearson correlation is -0.021901 and the Spearman
correlation recorded in `distribution_comparison.csv` is -0.505779. These are
finite-sample diagnostics, not new parameter estimates.

## Population convergence

The bounded convergence diagnostic uses 100, 500 and 1,000 vaults with fixed
seeds. All runs complete and produce zero initially liquidatable vaults under
the normal empirical pool.

| Vaults | Minimum positive share | Initial liquidatable share | Duplicate empirical-row draws |
| ---: | ---: | ---: | ---: |
| 100 | 0.010 | 0.000 | 5 |
| 500 | 0.002 | 0.000 | 84 |
| 1,000 | 0.001 | 0.000 | 292 |

This confirms that 500 remains computationally manageable for smoke testing,
but it also shows why population-size sensitivity is necessary whenever a
threshold is exactly zero.

## Zero liquidatable-threshold interaction

The diagnostic file
`normal_liquidatable_threshold_diagnostic.csv` records the interaction between
`max_normal_liquidatable_share = 0` and the simulated population sizes 100,
500 and 1,000. The threshold is not changed. The result is a validation note
for future sensitivity work.

## Legacy preservation

The Tranche B implementation adds:

- `src/vault_initialisation.py`;
- `scripts/build_vault_initialisation_pools.py`;
- `scripts/run_tranche_b_initialisation_diagnostics.py`;
- an optional `initial_vaults` argument in simulation entry points.

When `initial_vaults` is not supplied, simulation still calls the original
vault initialiser. Experiments 1-5 and Tranche A remain on the legacy path.

Bounded smoke runs were completed for:

1. legacy Gaussian;
2. Tranche A configuration-only;
3. Tranche B parametric truncated;
4. Tranche B empirical joint.

All smoke runs completed with separated outputs and provenance.

## Limitations

The empirical pool is based on representative opening states, not a continuous
historical census. Stress regimes are not dynamically switched during a
simulation. The parametric fallback does not preserve observed joint
dependence. The finite 500-vault sample can produce debt-share dispersion
because the empirical debt distribution is heavy-tailed; this is a diagnostic
feature rather than an estimator.

Tranche B does not adopt new liquidation-arrival, price-process, gas, auction
or behavioural parameters.

## Recommended next tranche

The next implementation tranche should add empirical market and gas sampling
or another explicitly authorised interface from the adoption roadmap. Parameter
estimation, regime switching and simulator-mechanics changes remain separate
gates.
