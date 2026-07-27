# Tranche A Empirical Configuration Report

## Scope

Tranche A creates a separate, opt-in empirical configuration bundle. It does
not change simulator mechanics, default configuration behaviour, sampling
logic, liquidation logic, confidence logic or the established Experiments 1-5.

The primary bundle is:

- `config/empirical/phase2_empirical_baseline.yaml`

The bounded population-and-debt-share sensitivity bundles are:

- `config/empirical/sensitivity/phase2_empirical_low_sensitivity.yaml`
- `config/empirical/sensitivity/phase2_empirical_high_sensitivity.yaml`

The candidate manifest is:

- `config/empirical/tranche_a_manifest.json`

## Candidate inclusion audit

The implementation used
`data/processed/estimation/adoption_review/configuration_ready_candidates.csv`
as the machine-readable source of truth after verifying the recorded
adoption-review checksums.

Seven conceptual candidates were included in the primary empirical
configuration, producing eight configuration-field assignments. The two
collateral-family debt-share fields are one conceptual `target_debt_share`
candidate represented by separate ETH and BTC assignments.

| Parameter | Field | Value | Source | Status |
| --- | --- | ---: | --- | --- |
| `n_vaults` | `SimulationConfig.n_vaults` | 500 | Phase 2B | `configuration_ready_with_sensitivity` |
| `target_debt_share` ETH | `CollateralConfig.target_debt_share` | 0.8483941126796408 | Phase 2B | `configuration_ready_with_sensitivity` |
| `target_debt_share` BTC | `CollateralConfig.target_debt_share` | 0.1516058873203592 | Phase 2B | `configuration_ready_with_sensitivity` |
| `max_close_factor` | `LiquidationConfig.max_close_factor` | 1.0 | Phase 2C | `configuration_ready` |
| `normal_lower_price` | `ConfidenceConfig.normal_lower_price` | 0.9992875 | Phase 2A | `configuration_ready_with_sensitivity` |
| `normal_upper_price` | `ConfidenceConfig.normal_upper_price` | 1.0030259166666666 | Phase 2A | `configuration_ready_with_sensitivity` |
| `stress_lower_price` | `ConfidenceConfig.stress_lower_price` | 0.9967380166666668 | Phase 2A | `configuration_ready_with_sensitivity` |
| `max_normal_liquidatable_share` | `ConfidenceConfig.max_normal_liquidatable_share` | 0.0 | Phase 2B | `configuration_ready_with_sensitivity` |

The ETH and BTC debt shares are represented at the implemented
collateral-family level. They do not imply exact-ilk allocation.

## Excluded candidates

Five configuration-ready rows were deliberately excluded from Tranche A:

| Parameter | Decision | Reason |
| --- | --- | --- |
| `min_collateral_ratio_buffer` | `exclude_missing_current_field` | The value maps to a vault-generator argument, not a stored top-level configuration field. Adopting it would require an interface change. |
| `mu` | `exclude_interface_mismatch` | Current GBM entry points use scalar ETH-style parameters and do not represent collateral-specific hourly moments without a new market-sampling interface. |
| `sigma` | `exclude_interface_mismatch` | Current GBM entry points use scalar ETH-style parameters and do not represent collateral-specific hourly volatility without a new market-sampling interface. |
| `liquidation_ratio` | `exclude_interface_mismatch` | The candidate requires exact-ilk timestamp selection; the Tranche A bundle represents ETH and BTC collateral families. |
| `liquidation_penalty` | `exclude_interface_mismatch` | The candidate requires exact-ilk timestamp selection; the Tranche A bundle represents ETH and BTC collateral families. |

The documented Phase 2C inconsistency is preserved: `auction_duration` has
sample size 581 in the preserved registry and 649 auctions under the durable
composite key. It is not adopted or repaired in this tranche.

## Configuration implementation

The loader is `src/empirical_config.py`. It validates the explicit bundle,
checks adoption-review checksums, rejects unknown fields and converts approved
values into the existing dataclasses:

- `SimulationConfig`
- `CollateralPortfolioConfig`
- `LiquidationConfig`
- `ConfidenceConfig`
- `DAIMarketConfig`

No default experiment function imports or calls the loader.

## Sensitivity configurations

The sensitivity files use a small low/high design. They are bounded
population-and-debt-share sensitivity bundles, not comprehensive sensitivity
bounds for every Tranche A candidate:

- `n_vaults`: 100 and 1,000, from the Phase 2B convergence range;
- BTC target debt share: 0.08485334085946024 and 0.2451900989821847;
- ETH target debt share: complementary values that keep shares summing to one.

Confidence thresholds retain central values because the candidate audit records
nearby sensitivity as required but does not provide complete numerical ranges
suitable for these bundles. Confidence-threshold sensitivity therefore remains
deferred rather than implicitly fixed by the low/high files.

`max_normal_liquidatable_share = 0` is also retained unchanged. Future
sensitivity must explicitly check its interaction with simulated population
size, because the smallest positive observed liquidatable share is
population-dependent: `1 / n_vaults`. For example, one initially liquidatable
vault implies shares of 0.01, 0.002 and 0.001 for 100, 500 and 1,000 simulated
vaults respectively.

## Legacy preservation

The following pre-existing configuration hashes were recorded before
implementation and remained unchanged:

| File | SHA-256 |
| --- | --- |
| `config/collateral_mapping.csv` | `203fac30fb9c9cff589827fa29ce108a475c9891a91d9b18bab56196ba214a06` |
| `config/empirical.yaml` | `4c41f36fe69c2bd42d5784e809e5fcb8ede5370af2bd7b8f109eaa6696db57fd` |
| `config/protocol.yaml` | `af322b9b7e7500cf609030abf28757f925a6a4f761c0e8eb0db8100dc345dfbd` |
| `src/experiments.py` | `20e5b9ce0f38dcfa10700dab0be11784d502550fb2424561aa40c5f636afdb2e` |

Protected user-owned files were not modified by this tranche.

## Smoke-test results

The empirical smoke test loads the primary bundle explicitly, runs a short
eight-step ETH/BTC simulation with a fixed seed and records sidecar
provenance. It is a configuration-loading check only; it is not empirical
validation of the model.

The smoke test confirms:

- the bundle loads;
- the simulation completes;
- ETH and BTC collateral types are present;
- active debt and collateral values remain non-negative;
- output provenance identifies `empirical_tranche_a`.

## Experiments 1-5 regression results

Experiments 1-5 were run in isolated temporary result directories before and
after implementation. Substantive outputs were byte-identical under the same
seeds and scenario definitions.

| Experiment | Rows | Summary rows | Output checksum |
| --- | ---: | ---: | --- |
| 01 baseline scenarios | 400 | 4 | `f955f5016b454d031553ae4a3fd5b6adcf4cd5bff6fa5950093a5f2bf2c620d9` |
| 02 oracle delay | 500 | 5 | `8af38b8571cfd47d73f012c3c860e2ac7cb78016152e500f68c933887325077c` |
| 03 shock severity | 500 | 5 | `a2d41a85fb3682407f43617024f420ea1fecf66f54c3a2020d4b5adfe4c84839` |
| 04 confidence sensitivity | 500 | 5 | `3295eab1b6585f6c6ead10734027dc76b8a01d99a626ebca447d4533aa93a666` |
| 05 peg recovery | 500 | 5 | `0ce90ea8552f7fd9c880adb05299b203789fea7ddd6de16115318f55a5722781` |

## Limitations

Tranche A is intentionally narrow. It does not implement empirical joint
resampling, moving-block returns, exact-ilk protocol replay, hurdle
liquidation arrivals, auction execution, behavioural calibration or
confidence-mechanism changes. The follow-on Tranche B report documents the
separate opt-in distribution-aware initialisation interface:
`docs/tranche_b_distributional_vault_initialisation_report.md`.

`max_close_factor = 1.0` is adopted only as the current simulator's
protocol-close fraction. It is not a Clipper Take fraction and it does not
settle the separate auction-execution mechanism question.

## Next recommended tranche

The next substantive implementation tranche is distribution-aware vault
initialisation. That tranche should add an optional empirical vault sampler
before adopting debt-distribution or collateral-ratio distribution candidates.
