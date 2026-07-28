# Parameter adoption and model-interface plan

## Purpose and decision boundary

This plan is the auditable bridge between the Phase 2A–2C candidate evidence
and any later simulator implementation. It inventories the current
implementation, preserves every candidate and its provenance, assigns one
primary adoption class to every authoritative parameter subsection, and
defines the smallest staged changes that could support empirical calibration.

It is a plan only. No value is adopted, no configuration file is modified and
no simulator mechanics are changed.

## Authoritative inventory and count reconciliation

The authoritative inventory contains **56 numbered parameter subsections** in
`parameter_estimation_plan.md`. The earlier count of 55 missed the grouped,
multiline subsection 4.3.7 covering `shock_size`, `shock_sizes`,
`crypto_crash_size` and `stable_depeg_size`. The discrepancy is documentary:
no runtime field has been added or removed.

The audit also maps 70 implemented configuration and material runtime fields
to those subsections, including all 50 live annotated dataclass fields. These
include all annotated fields in:

- `SimulationConfig`;
- `CollateralConfig` and `CollateralPortfolioConfig`;
- `PriceProcessConfig`;
- `LiquidationConfig`;
- `ConfidenceConfig`;
- `DAIMarketConfig`; and
- the material `run_simulation` and vault-generator controls not held in a
  dataclass.

The implementation is authoritative for semantics. The main conflicts or
qualification points are:

- Phase 2A records `mu` and `sigma` as hourly return moments, while the legacy
  GBM exposes `dt=1/365`. They are not numerically interchangeable until the
  model-time convention is fixed or converted.
- `risk_cost_rate` is a proportional cost on debt repaid. It is not the
  empirically motivated minimum expected-profit participation threshold.
- Phase 2A's original status table predates Phase 1E-B and therefore records
  several vault parameters as blocked. Phase 2B and Phase 2C evidence is later,
  preserved separately and not written over the original records.
- The canonical multi-collateral path uses price mappings; `price_col` and
  `oracle_col` remain legacy DataFrame-adapter controls and are classified
  `superseded_or_unused`, not deleted.
- `max_close_factor` documentation and code agree: it is a per-vault debt-close
  fraction. It is not liquidation throughput or auction Take size.

## Candidate consolidation

The consolidated evidence contains **80 distinct records**:

| Source | Records |
|---|---:|
| Phase 2A reviewed candidates | 64 |
| Phase 2B vault candidates | 9 |
| Phase 2C liquidation/stress candidates | 7 |

The consolidation retains original values, distribution references, source
registry checksums, units, frequency, collateral, regime, uncertainty,
original status and later review status. Repeated parameters are deliberately
not collapsed. In particular:

- ETH, WBTC and USDC-proxy return evidence remains collateral-specific;
- effective protocol histories remain exact-ilk and effective-dated;
- the USDC/SVB and Terra/CeFi stress-share values remain moderate- and
  severe-stress evidence respectively;
- the Phase 2B and Phase 2C buffer records coexist;
- the full-vault close fraction and partial auction-execution fractions remain
  different candidates; and
- descriptive or validation-only evidence is not promoted to an adoptable
  scalar.

One traceable source-registry inconsistency is preserved rather than silently
repaired. The Phase 2C registry records a sample size of 581 for
`auction_duration`, while the durable auction identity
`(clipper_contract, auction_id)` and the Phase 2C report establish 649
auctions. The consolidation retains the registry value and flags it. The
duration sample size must not support adoption until a separately authorised
registry regeneration reconciles it; this does not affect the present
configuration-ready decisions.

## Adoption-class totals

Each of the 56 subsections has exactly one primary class:

| Primary adoption class | Count |
|---|---:|
| `configuration_ready` | 1 |
| `configuration_ready_with_sensitivity` | 11 |
| `protocol_constant_ready` | 4 |
| `requires_scalar_reduction` | 2 |
| `requires_distribution_interface` | 5 |
| `requires_regime_interface` | 1 |
| `requires_new_model_mechanism` | 1 |
| `literature_required` | 1 |
| `not_identifiable` | 11 |
| `scenario_only` | 18 |
| `superseded_or_unused` | 1 |

No parameter is marked adopted. The detailed row-level decision is in
`parameter_adoption_matrix.csv`.

## Configuration candidates requiring no mechanics change

The following candidates can be represented by existing mechanics after the
stated review gate. They should be placed in a **separate empirical
configuration**, leaving the current hand-set baseline intact.

| Parameter | Current | Review candidate | Qualification and expected effect |
|---|---:|---:|---|
| `n_vaults` | 100 | 500 | Computational scaling choice; require 100–1,000 convergence. More vaults improve distributional resolution and increase runtime. |
| ETH/BTC `target_debt_share` | ETH 1.0, BTC 0 | ETH 0.848394, BTC 0.151606 | Quiet-window composition, not an unconditional protocol weight. Adds BTC exposure and changes collateral attribution. |
| `min_collateral_ratio_buffer` | 0.05 | 0.492758 | Normal initialisation q05. Raises the generated lower collateralisation floor; stress states must not replace this candidate. |
| hourly `mu` | 0 in legacy GBM units | ETH 2.0684e-5; WBTC 2.8097e-5; USDC proxy -9.9612e-8 | Requires explicit hourly/GBM-time conversion. Directional comparison is otherwise meaningless. |
| hourly `sigma` | 0.80 in legacy GBM units | ETH 0.006083; WBTC 0.004743; USDC proxy 0.000667 | Requires the same time-unit decision and block sensitivity. |
| liquidation ratio | global 1.5 | exact-ilk value at baseline time | Historical replay uses effective history. Generic experiments must pre-register a timestamp rather than average ilks. |
| liquidation penalty | global 0.13 | exact-ilk value at baseline time | Same effective-time and exact-ilk requirement. |
| `max_close_factor` | 1.0 default; 0.3/0.5 in scenarios | 1.0 | Directly compatible only as the protocol-close fraction. Existing reduced-close scenarios remain explicit sensitivities. |
| `normal_lower_price` | 0.99 | 0.9992875 | Empirical DAI boundary, not an observed confidence level. Makes normal classification narrower. |
| `normal_upper_price` | 1.01 | 1.0030259 | Must be reviewed jointly with the other DAI thresholds. |
| `stress_lower_price` | 0.97 | 0.9967380 | Would make below-peg panic classification much more sensitive. |
| `max_normal_liquidatable_share` | 0.05 | 0 in the quiet evidence | Boundary estimate; requires nearby sensitivity and held-out validation. |

Exact start prices and `initial_dai_price` are interface-compatible, but the
Phase 2 registries do not provide a single generic start value. They must be
selected from the pre-registered baseline timestamp, not inferred silently.

`gas_cost` and `max_liquidations_per_step` are not included in this immediate
set because each requires a declared scalar reduction from a distribution.
`max_stress_liquidatable_share` requires a regime decision rather than a
single pooled number.

## Protocol constants: replay and generic experiments

Four authoritative subsections are protocol-constant ready: collateral
identity, liquidation ratio, liquidation penalty and the DAI peg price.

Historical replay must use the exact effective-dated setting for each ilk. It
must not average histories or carry a setting across a migration boundary.
Generic experiments should instead use:

1. a pre-registered baseline timestamp;
2. the exact values active for each included ilk at that timestamp;
3. an explicit mapping from exact ilks to ETH and BTC model collateral;
4. explicit scenario overrides; and
5. robustness ranges drawn from observed changes.

For the empirical generic baseline, the recommended timestamp-selection rule
is the opening hour of the validated quiet-mature window,
**2024-02-01 00:00:00 UTC**, because it is pre-specified by the representative
design and is not chosen to optimise simulation fit. A different date may be
used only if declared before results are examined.

Debt ceilings, dust, stability fees and auction-stopped histories remain
credible protocol evidence, but the present simplified ABM does not consume
all of them. They belong in historical provenance or a later replay adapter,
not in the core generic experiment by default.

## `max_close_factor` decision

The field should be retained. A future empirical configuration may adopt
`1.0` because:

- code and documentation define it as the maximum fraction of one vault's
  debt repaid in one simulated liquidation;
- all 649 exact Terra/CeFi Bark–grab links remove the complete unsafe urn
  position; and
- keeper throughput is separately controlled by
  `max_liquidations_per_step`.

The mapping remains an abstraction. `Vat.grab` closes the urn position, while
Clipper can subsequently use multiple partial Takes. If auction execution is
later represented, it should receive a separate optional configuration such
as `auction_execution`, never a silent reinterpretation of
`max_close_factor`.

A rename is not justified now because the implementation and documentation
already agree. Documentation may describe it as the *protocol close fraction*.
If a later refactor renames it, the old name should remain a deprecated alias
for at least one compatibility cycle, with conflicts rejected explicitly.

Adopting `1.0` would not change the class default, but would materially change
experiments configured at `0.5` or `0.3`: the maximum debt repaid per event
would double or increase by approximately 233%, respectively. A hypothetical
`0.25` scenario would quadruple its close cap. This affects keeper gross
reward, collateral removal, residual vault state and potentially bad debt.
Current experiments must therefore retain their declared scenario values
unless separately migrated.

## Vault-initialisation interface

### Option A: retain the global Gaussian moments

This is the compatibility baseline. It is small and transparent, but does not
represent the observed right tails, exact-ilk heterogeneity or joint
debt–leverage dependence. Clipping can create artificial mass at the minimum
ratio, and Gaussian debt draws can be implausible before safeguards.

### Option B: collateral-specific parametric distributions

Debt should use a positive distribution such as lognormal or a fitted
truncated family. Collateralisation is better represented as a non-negative
buffer above the applicable liquidation ratio, not as an unrestricted ratio.
A copula, rank-correlation target or conditional model would be needed to
preserve debt–buffer dependence. This option extrapolates more smoothly for
small samples, but introduces family-selection assumptions.

### Option C: empirical joint resampling

The primary recommendation is an optional empirical joint sampler that draws
`(debt_dai, collateral_ratio_buffer)` pairs from validated opening states. It
should:

- use collateral-family pools, retaining exact-ilk provenance;
- accept an explicit regime label;
- draw pairs jointly rather than independently;
- use deterministic seeded sampling;
- permit sampling with replacement;
- expose the source window and checksum;
- reject values outside economic support rather than silently clipping; and
- fall back when a collateral pool is below a pre-specified minimum size.

Option B is the simpler fallback. Option A remains the legacy default for
backward compatibility. No sampler is implemented by this plan.

## Multi-collateral initialisation

The minimum future schema should allow:

- portfolio debt shares by model collateral family;
- optional exact-ilk weights within a family;
- collateral-specific vault counts or a deterministic count-allocation rule;
- a debt distribution and buffer distribution per family;
- a joint empirical-pool reference per family;
- collateral-specific liquidation ratios, penalties and close-factor
  overrides; and
- an explicit fallback for STABLE when no corresponding vault evidence exists.

Exact-ilk empirical results should be retained in provenance, then mapped to
ETH and BTC only at the declared model boundary. The ETH-only path must remain
the default special case and reproduce current seeded results.

## Regime interface

The Phase 2A classifier provides a provisional normal/stress description. The
withheld FTX diagnostic supports persistence testing but must not enter
calibration. Phase 2B/2C further distinguishes moderate USDC/SVB stress from
severe Terra/CeFi liquidation pressure.

This evidence does **not** yet identify a calibrated exogenous three-state
Markov process. The current model already has endogenous normal, stress and
panic confidence states. The recommended minimum design is therefore:

- retain the endogenous confidence-state mechanics;
- use the Phase 2A two-state classifier for empirical stratification;
- allow named sampler/configuration overrides for `normal`,
  `moderate_stress` and `severe_stress`;
- do not tune thresholds to named events; and
- treat severe/panic overrides as scenario evidence until independently
  validated.

`max_stress_liquidatable_share` should preserve the USDC/SVB value
`0.000577546` and the Terra/CeFi q95 `0.001853` and maximum `0.028470`
under separate labels. A single pooled threshold is not recommended.

## Liquidation arrival and throughput

Four stages must remain distinct:

1. market and vault state make a vault liquidatable;
2. a Bark initiates liquidation;
3. `Vat.grab` transfers the unsafe urn position; and
4. one or more Takes execute the auction subject to keeper capacity.

The current ABM models stage 1 endogenously and combines stages 2–4 into one
keeper action. `max_liquidations_per_step` is deterministic execution capacity.

The recommended dissertation core retains endogenous unsafe-vault creation and
a separate deterministic capacity cap. The Tranche D implementation now adds
an opt-in hurdle demand overlay:

- probability of any Bark activity in an hour; and
- empirical positive Bark count conditional on activity.

It does not create a second liquidation state variable. Instead, it observes
the simulator's current liquidatable inventory, samples a bounded empirical
arrival count and then applies the separate keeper-throughput cap. The Phase
2C variance-to-mean ratio and zero mass reject a simple Poisson
representation, but do not require a Hawkes model.

Keeper participation should move towards an explicit minimum expected-profit
threshold. Evidence comes from Phase 1C clean and failed Take transactions,
liquidation-specific gas units and prices, Phase 1B network gas conditions,
and Phase 1A ETH/USD conversion. `risk_cost_rate` should remain only as a
legacy reduced-form control until that threshold is designed.

## Auction execution

The 649 Terra/CeFi auctions contain partial execution and 20 multi-Take
auctions despite full urn closure. A complete auction engine could model Take
fractions, elapsed completion time, incomplete auctions, gas and keeper
participation, but this would expand the dissertation substantially.

The preferred scope is:

- keep the one-stage liquidation in the core ABM;
- use observed Take fractions and duration as validation/sensitivity evidence;
- if required, add a simplified optional auction-friction extension with a
  completion delay and recovery fraction; and
- leave explicit multi-keeper bidding and per-Take gas accounting to future
  work.

## Market-process interface

The primary empirical design is aligned moving-block resampling of ETH, WBTC
and the stable proxy:

- 168 hours as the default block;
- 72–336 hours as the sensitivity range;
- one shared sequence of block indices to preserve cross-collateral
  dependence;
- deterministic seeds;
- explicit normal/moderate/severe source pools if regime conditioning is used;
  and
- no FTX observations in fitting.

The fallback is the current GBM using reviewed collateral-specific moments
after explicit hourly-to-GBM-unit conversion. Transparent shock paths remain
scenario experiments, not empirical return generators.

## Gas interface

The primary later design should keep three quantities separate:

1. transaction gas units;
2. gas price in gwei; and
3. total ETH/USD transaction cost.

Clean successful-Take gas units are the primary liquidation-specific evidence.
Hourly Phase 1B gas prices provide normal and stress network conditions, and
Phase 1A supplies ETH/USD. A scalar `gas_cost` remains useful as a compatibility
mode after a documented reduction and sensitivity analysis.

Four genuine zero-gas observations are missing/indeterminate for the primary
estimate, not free liquidations. They should be excluded in the primary
reduction and retained in a clearly labelled retain-all sensitivity.

## Confidence and behavioural backlog

The 15 fields previously classified `requires_model_calibration` are:

| Parameter | Continued role | Later treatment |
|---|---|---|
| `risk_cost_rate` | Legacy keeper uncertainty cost | Prefer explicit minimum-profit threshold; retain only for compatibility. |
| `bad_debt_panic_threshold` | Panic trigger | Simulation matching and sensitivity. |
| `normal_confidence` | Latent state level | Scenario normalisation or simulation matching; not directly observed. |
| `stress_confidence` | Latent state level | Simulation matching with regime-labelled targets. |
| `panic_confidence` | Latent state level | Severe-stress scenario/simulation matching. |
| `panic_selling_multiplier` | Behavioural pressure | Minimum-distance/SMM and ablation. |
| `price_adjustment_speed` | DAI response rate | Simulation matching to peg deviation and recovery persistence. |
| `arbitrage_strength` | Stabilising demand | Simulation matching; keep distinct from recovery-only strength. |
| `above_peg_supply_strength` | Above-peg supply response | Simulation matching and above-peg ablation. |
| `panic_strength` | Panic selling in DAI market | Joint calibration with confidence; avoid duplicate panic pressure. |
| `noise_std` | Residual DAI-price noise | Residual diagnostic after deterministic mechanisms are fixed. |
| `arbitrage_recovery_strength` | Optional recovery mechanism | Retain only if recovery extension is enabled; otherwise superseded/zero. |
| `policy_feedback_strength` | Optional recovery mechanism | Scenario or literature requirement unless independently identified. |
| `bad_debt_recovery_drag` | Recovery impairment | Simulation matching under bad-debt episodes. |
| `min_recovery_confidence` | Recovery activation floor | Scenario/simulation matching; test for redundancy with confidence state. |

None is directly identifiable from the acquired panels alone. Later estimation
should use simulation outputs matched to DAI deviation, recovery time, bad
debt, liquidation activity and confidence-regime persistence. Each mechanism
requires an ablation test to detect duplication. FTX is reserved for
validation.

## Illustrative future configuration

The following YAML is illustrative only and is **not** a modification to
current configuration:

```yaml
schema_version: 1
mode: empirical_generic
frequency: 1h
random_seed: 42

population:
  n_vaults: 500
  initialisation:
    strategy: empirical_joint       # legacy_gaussian | parametric | empirical_joint
    fallback: collateral_lognormal_buffer
    regime: normal
    pools:
      ETH:
        path: null
        checksum: null
      BTC:
        path: null
        checksum: null

collateral_allocation:
  debt_shares:
    ETH: 0.8483941127
    BTC: 0.1516058873
  exact_ilk_provenance: true

market:
  strategy: moving_block            # gbm remains supported
  block_hours: 168
  sensitivity_block_hours: [72, 168, 336]
  aligned_collaterals: [ETH, BTC, STABLE]
  regime_pool: normal

gas:
  strategy: scalar                  # empirical_distribution is future
  scalar_cost_usd: null
  empirical:
    gas_units_source: clean_successful_take
    gas_price_source: phase1b_hourly
    exclude_indeterminate_zero_gas: true

protocol:
  mode: generic_baseline            # effective_dated_replay for history
  baseline_timestamp_utc: "2024-02-01T00:00:00Z"
  collateral:
    ETH:
      liquidation_ratio: null
      liquidation_penalty: null
    BTC:
      liquidation_ratio: null
      liquidation_penalty: null

liquidation:
  protocol_close_fraction: 1.0      # maps to current max_close_factor
  capacity:
    strategy: scalar
    max_per_hour: null
  arrival:
    strategy: endogenous_only       # optional hurdle remains future
  keeper:
    minimum_expected_profit_usd: null
    legacy_risk_cost_rate: 0.0

confidence:
  evidence_regime: normal           # normal | moderate_stress | severe_stress
  normal_lower_price: 0.9992875
  normal_upper_price: 1.0030259
  stress_lower_price: 0.9967380
  liquidatable_share_overrides:
    normal: null
    moderate_stress: 0.000577546
    severe_stress_q95: 0.001852518

dai_market:
  peg_price_usd: 1.0
  behavioural_parameters: current_baseline
```

Every distribution block states its frequency, collateral scope, regime and
source. Nulls are deliberate adoption gates, not implied zeros.

## Implementation sequence

### Configuration-only empirical bundle

Fields: `max_close_factor`, represented protocol constants, initial prices,
target debt shares and reviewed scalar thresholds.

Modules: configuration loading, experiment construction and existing config
classes only. Tests must cover schema, units, exact-ilk mapping and unchanged
legacy outputs. Stop if a supposedly ready field requires mechanics changes.
Current defaults and Experiments 1–5 remain untouched unless the empirical
configuration is explicitly selected.

Implementation note: Tranche A is now implemented as an opt-in bundle under
`config/profiles/`, with its audit report in the
[historical implementation archive](../archive/tranche_reports/tranche_a_empirical_configuration_report.md).
The implementation adopts
only current-interface-compatible rows. Exact-ilk protocol constants, scalar
GBM moments with unresolved hourly conversion and generator-only collateral
buffer values remain excluded for later tranches.

### Distribution-aware vault initialisation

Add the optional empirical joint sampler and collateral-specific parametric
fallback. Update `vault.py`, `simulation.py`, `collateral.py` and a small
configuration adapter. Test economic support, tails, dependence, deterministic
seeds, small-pool fallback and exact ETH-only equivalence.

Implementation note: Tranche B is now implemented as an opt-in
distribution-aware initialisation path. The runtime pool and configuration are
under `config/profiles/`, while historical diagnostic outputs remain under the ignored
`outputs/diagnostics/input_construction/vaults/` directory, and the implementation
report is
[implementation report](../archive/tranche_reports/tranche_b_distributional_vault_initialisation_report.md).
The legacy
Gaussian initialiser remains the default, and Tranche A continues to use its
configuration-only behaviour unless the Tranche B bundle is explicitly
selected.

### Empirical market and gas sampling

Add aligned moving blocks and a regime-labelled gas sampler while retaining
GBM and scalar gas modes. Test block boundaries, correlations, seed
reproducibility, zero-gas handling and unit conversion.

Implementation note: Tranche C is now implemented as an opt-in empirical
environment-input layer. It adds aligned ETH/WBTC return blocks, compact
market/gas and liquidation-gas runtime pools, and explicit empirical gas input
modes while preserving legacy GBM and scalar gas defaults. The implementation
report is in the
[historical implementation archive](../archive/tranche_reports/tranche_c_empirical_market_and_gas_report.md).

### Liquidation demand and throughput

Implemented as an opt-in hurdle-count demand interface after Tranches B and C.
It tests the liquidatable/Bark/grab/Take distinctions, backlog, capacity and
profit accounting while preserving legacy defaults. The primary hurdle
probability is the Phase 2C conditional start-inventory-positive activity
estimate, and positive counts are sampled from the compact Terra/CeFi hourly
arrival pool. Sequence sensitivity is retained as a diagnostic artefact only;
no auction lifecycle or confidence mechanism is added.

### Confidence and behavioural calibration

Use minimum-distance or SMM after the observable interfaces are fixed. Test
ablation, sensitivity and withheld FTX validation. Never present latent
coefficients as direct empirical estimates.

The smallest completed tranches are **Tranche A**, implemented as a separate
empirical configuration with no change to legacy defaults, and **Tranche B**,
implemented as an opt-in distribution-aware vault initialisation interface.
**Tranche C** is also complete as an opt-in empirical market/gas input layer.
**Tranche D** is complete as an opt-in empirical liquidation-arrival and
keeper-throughput interface. Later behavioural interfaces remain separately
gated. The implementation report is
`tranche_d_liquidation_arrival_and_capacity_report.md`.

## Adoption-validation framework

Every tranche must include:

- unit tests and schema validation;
- deterministic seeds and reproducible artefacts;
- distributional support, quantile and dependence checks;
- economic invariants for debt, collateral, liquidation, keeper profit and bad
  debt;
- baseline regression tests for the current hand-set configuration and
  Experiments 1–5;
- representative-window validation not circularly used for the candidate;
- withheld FTX validation only;
- uncertainty and sensitivity analysis;
- mechanism ablations; and
- an explicit comparison with the current baseline.

An adoption stops if units or frequency are ambiguous, economic invariants
fail, the empirical configuration changes legacy mode, a candidate only fits
after using FTX, or a scalar reduction hides a material distributional result.

## Reproducibility outputs

Generated audit artefacts are under
`outputs/diagnostics/calibration/parameter_adoption/`:

- `parameter_adoption_matrix.csv`;
- `candidate_consolidation.csv`;
- `model_interface_gaps.csv`;
- `configuration_ready_candidates.csv`;
- `proposed_implementation_tranches.csv`;
- `adoption_validation_plan.csv`; and
- `adoption_review_metadata.json`.

These outputs are a decision record. They do not constitute parameter adoption.
