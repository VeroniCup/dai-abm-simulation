# Final multi-collateral input freeze and integration validation

## 1. Purpose

This validation freezes the empirical and counterfactual inputs needed for the
final multi-collateral experiment design. It tests input ownership,
initialisation, ordinary dynamics, shared keeper allocation and accounting
without running or ranking any final experiment. The validated profile is
opt-in and experiment-ready; `runtime_adopted` remains false.

The overall result is
`final_multicollateral_inputs_ready_with_caveats`. ETH and WBTC have empirical
market and vault owners. The stable family is an explicitly labelled
`counterfactual_stable_proxy`, so the result is not a claim that all three
families are empirically identified.

## 2. Relation to constrained ETH recovery

The preceding constrained ETH-recovery experiment established that a
system-wide keeper cap can preserve unresolved inventory and make collateral
recovery operationally relevant. It used a single ETH collateral family and
did not test competition across collateral pools.

This pass carries the same central capacity of 26 opportunities per hour,
`direct_cost_only` hurdle, zero `risk_cost_rate`, Stage 1-only confidence and
zero-delay transparent oracle baseline into an opt-in multi-collateral
integration profile. It validates the cross-collateral contract but does not
extend the earlier ETH result into a diversification conclusion.

## 3. Existing multi-collateral implementation audit

The starting implementation is classified
`multicollateral_core_compatible_with_repairs`. It already represented one
collateral family per vault, accepted collateral-specific market and oracle
prices, allowed family-specific liquidation settings, produced system and
long-format collateral outputs, and applied a shared liquidation-capacity
field.

The repairs required for the final contract were structural rather than
economic: exact Maker ilks had to remain attached to vaults, the final
empirical/counterfactual owners had to be frozen, and candidate inspection had
to expose one deterministic global ranking. The established ETH-only runtime
path and Experiments 1–5 remain unchanged.

## 4. Final collateral universe

The final family order is fixed as:

1. `ETH`;
2. `WBTC` (normalised to the simulator collateral name `BTC`);
3. `STABLE`.

The exact empirical Maker ilks are `ETH-A`, `ETH-B`, `ETH-C`, `WBTC-A`,
`WBTC-B` and `WBTC-C`. No LP, staked-ETH, PSM, direct-deposit or other Maker
collateral enters this registry. The stable family is a stylised collateral
proxy rather than an additional empirically reconstructed Maker ilk.

## 5. Empirical versus counterfactual ownership

ETH and WBTC use the quiet-mature February 2024 joint vault pool and the
aligned empirical market–gas block pool. Exact-ilk sampling is debt-weighted
within each volatile family.

The stable proxy is deliberately split by evidence type. Its ordinary price
process uses the locally processed USDC price series as evidence for ordinary
near-par variation, but its vault distribution and protocol bundle are
stylised. Its evidence status is therefore
`counterfactual_stable_proxy`, not empirical USDC collateral. No silent
fallback from a missing empirical stable-vault pool is allowed.

## 6. Exact-ilk treatment

Exact ilks are sampled and retained on volatile-collateral vaults. ETH uses
quiet-mature within-family debt weights of 0.3151974147207501 for `ETH-A`,
0.10734831825178935 for `ETH-B` and 0.5774542670274606 for `ETH-C`. WBTC uses
0.3839463868669127 for `WBTC-A`, 0.218859649828156 for `WBTC-B` and
0.3971939633049313 for `WBTC-C`.

Each volatile vault carries its exact ilk and exact liquidation ratio. The
liquidation penalty is also exact, although it is 0.13 for all six included
ilks. Mechanically debt-weighted family settings remain compatibility and
provenance values rather than silently replacing those vault-level ratios.

## 7. Protocol parameters

The model-active frozen settings are:

| Family or ilk | Liquidation ratio | Penalty rate | Maximum close factor | Status |
|---|---:|---:|---:|---|
| `ETH-A` | 1.45 | 0.13 | 1.0 | empirical protocol setting |
| `ETH-B` | 1.30 | 0.13 | 1.0 | empirical protocol setting |
| `ETH-C` | 1.70 | 0.13 | 1.0 | empirical protocol setting |
| `WBTC-A` | 1.45 | 0.13 | 1.0 | empirical protocol setting |
| `WBTC-B` | 1.30 | 0.13 | 1.0 | empirical protocol setting |
| `WBTC-C` | 1.75 | 0.13 | 1.0 | empirical protocol setting |
| STABLE family | 1.10 | 0.05 | 1.0 | counterfactual family bundle |

Debt ceilings and minimum debts remain provenance fields and are not made
operational by this pass. No parameter was selected from simulation results or
recalibrated.

## 8. Population and debt normalisation

Every central portfolio has exactly 500 vaults and exactly 2,500,000 DAI of
initial debt. Vault counts are assigned by the largest-remainder rule in the
fixed family order `ETH`, `WBTC`, `STABLE`. Sampled family debts are then
scaled multiplicatively to their exact registered debt totals.

The transformation preserves within-family relative debt heterogeneity. It
does not infer a historical system population size and does not change the
standardised 500-vault interpretation used by the integrated ETH profile.
Population sizes 250 and 1,000 remain future robustness cases.

## 9. Common initial collateralisation

All five portfolios use the common initial system collateral-ratio target
3.6089387701260205. This is the median debt-weighted system collateral ratio
from the protected 512 integrated-ETH initialisations. After family debt
normalisation, one portfolio-wide collateral scaling establishes that common
target.

Unsafe initialisations are rejected and deterministically resampled. Scaling
does not permit any vault to start below its applicable liquidation ratio plus
the declared safety buffer. This makes portfolio comparisons start from
comparable system collateralisation rather than allowing composition to alter
the initial risk level mechanically.

## 10. Five portfolio definitions

The final registry contains exactly five portfolios:

| Portfolio | ETH debt share/count | WBTC debt share/count | STABLE debt share/count |
|---|---:|---:|---:|
| `eth_only` | 1.0 / 500 | 0.0 / 0 | 0.0 / 0 |
| `empirical_crypto` | 0.8483941126796408 / 424 | 0.1516058873203592 / 76 | 0.0 / 0 |
| `balanced_crypto` | 0.5 / 250 | 0.5 / 250 | 0.0 / 0 |
| `stable_supported` | 0.6362955845097307 / 318 | 0.11370441549026941 / 57 | 0.25 / 125 |
| `stable_heavy` | 0.4241970563398204 / 212 | 0.0758029436601796 / 38 | 0.5 / 250 |

The 25% and 50% stable coordinates are counterfactual design points. Within
the remaining crypto share they preserve the empirical ETH/WBTC ratio. The
portfolios are registered treatments, not an ordering from best to worst.

## 11. Ordinary price owners

ETH and WBTC returns are sampled jointly from a frozen 26,208-row,
22-column aligned market–gas pool in 168-hour blocks. This preserves their
observed contemporaneous relationship and the gas environment. The pool is
derived from the existing processed market panel and environment-block input;
it is not a newly acquired dataset.

The stable ordinary series is the aligned USDC price and log return. Across
the frozen pool, 99.9084249084% of stable-price observations lie within 1% of
par. The pool excludes the USDC/SVB interval and the FTX hold-out interval.
This ordinary-price owner does not turn the stable vault population or
protocol settings into empirical estimates.

## 12. Seven shock definitions

The final registry fixes seven result-blind shock identifiers:

1. `eth_idiosyncratic_severe`: ETH nearest-rank q01 negative 24-hour log
   return, with WBTC and STABLE left on ordinary paths;
2. `wbtc_idiosyncratic_severe`: the corresponding WBTC q01 tail;
3. `joint_crypto_empirical_stress`: the observed hour maximising standardised
   ETH downside plus standardised WBTC downside plus 0.5 times standardised
   gas;
4. `joint_crypto_high_correlation`: simultaneous ETH and WBTC q01 tails;
5. `stable_depeg_moderate`: a fixed STABLE trough of 0.95 followed by smooth
   recovery over 72 hours;
6. `stable_depeg_severe`: a fixed STABLE trough of 0.90 followed by smooth
   recovery over 168 hours;
7. `joint_crypto_stable_stress`: simultaneous ETH/WBTC q01 tails and the
   0.90 STABLE trough with the 168-hour smooth recovery.

Shock onset is hour 24. Volatile shocks use the registered `full_week`
principal recovery and `persistent_trough` adverse sensitivity. The selected
empirical joint-stress timestamp and all path checksums are recorded in the
compact registry.

The result-blind volatile-tail audit gives ETH q05/q01/minimum 24-hour log
returns of -0.07771029477038699, -0.12483514310239592 and
-0.24992659983947993. The corresponding WBTC values are
-0.062162287516442295, -0.09859374041712803 and
-0.19663909902391202.

The registered q01 multipliers are 0.8826424002789204 for ETH and
0.9061107494334123 for WBTC. The maximum result-blind joint-stress score occurs
at 2022-05-12 06:00 UTC and supplies 24-hour multipliers
0.7788579492718739 for ETH and 0.8632706805976554 for WBTC. The timestamp is
selected by the pre-registered market-and-gas score, not by model outcomes.

## 13. Stable-depeg boundary

The 0.95 and 0.90 stable floors are controlled counterfactuals. They are not
estimated from the excluded USDC/SVB period, are not historical replays and
do not validate a specific stable collateral. The ordinary USDC series is
used only as a near-par process owner outside the final-validation exclusions.

The simulator still has no separately estimated stable-depeg confidence,
liquidity or contagion channel. Stable-collateral conclusions must therefore
be reported as conditional on this transparent price-path treatment.

## 14. Shared keeper contract

One system-wide hourly attempt budget applies across all active collateral
families. The central value is 26; 14 and 45 remain low and high robustness
points. The central participation hurdle is `direct_cost_only` with
`risk_cost_rate = 0`. These are the previously calibrated, partially
identified keeper candidates; this pass does not recalibrate them.

Capacity is not copied per collateral, per ilk or per auction pool. Unattempted
unsafe opportunities remain in collateral-specific backlog and can carry
forward. The sum of attempts across collateral families can never exceed the
single system cap.

## 15. Global ranking

Unsafe opportunities enter one global deterministic ranking. The ordering is:

1. expected keeper profit, descending;
2. full debt at risk, descending;
3. vault identifier, ascending.

The first 26 opportunities form the attempted set. The order is independent
of input-list permutation, and no family receives a reserved quota. Exact ilks
remain metadata and do not alter the system-wide selection rule.

## 16. Collateral accounting

Each collateral family retains its own unsafe inventory, attempts, successful
closures, backlog, debt repaid, bad debt and keeper-profit attribution. System
quantities are the exact sum of the corresponding family quantities.

The validation checks debt and collateral conservation, uniqueness of closure,
finite states, non-negative state variables and price isolation. A WBTC or
stable path cannot mutate an ETH vault balance, and transaction opportunities
are not duplicated when reported at both collateral and system levels.

## 17. Validation design

The input freeze uses four components:

- Component A: registry, owner, checksum, label and exclusion validation;
- Component B: 256 deterministic initialisations for each of five portfolios,
  for 1,280 total;
- Component C: 32 independent ordinary 168-hour simulations for each
  portfolio, for 160 total;
- Component D: six transparent shared-capacity smokes of no more than
  48 hours.

The design validates ownership, numerical behaviour and the allocation
contract. It does not apply the seven final shocks as a comparative experiment
and does not estimate treatment effects. Seeds, acceptance gates and
classification rules are fixed in the pre-result specification.

## 18. Initialisation results

All 1,280 initialisations passed. Every population had 500 vaults, exact
registered family counts and 2,500,000 DAI total debt. The maximum absolute
debt error was \(9.313225746154785\times10^{-10}\) DAI, the unsafe-vault count
was zero throughout and the maximum accepted resampling attempt was three.

All family debt shares and the common system collateral-ratio target passed
their tolerances. No empirical ETH/WBTC row entered the stable population, and
no stable proxy observation entered an empirical volatile-family pool. The
classification is `final_portfolio_registry_ready`.

## 19. Ordinary dynamic results

All 160 ordinary 168-hour replications were numerically and structurally
valid. There were no fallback-path uses, invalid states, reconciliation
failures or duplicate closures.

| Portfolio | Replications | Total attempts | Successful closures | Maximum attempts in one hour |
|---|---:|---:|---:|---:|
| `eth_only` | 32 | 110 | 70 | 11 |
| `empirical_crypto` | 32 | 104 | 58 | 12 |
| `balanced_crypto` | 32 | 17 | 16 | 10 |
| `stable_supported` | 32 | 40 | 18 | 5 |
| `stable_heavy` | 32 | 15 | 7 | 4 |

These figures are ordinary integration diagnostics, not portfolio performance
estimates. They must not be used to rank or select a portfolio.

## 20. Shared-capacity smoke results

Each isolated-family smoke presented 36 unsafe opportunities: 26 were
attempted and 10 were rejected by the common cap. In simultaneous ETH/WBTC
demand, 72 opportunities competed for the same cap; 13 ETH and 13 WBTC
opportunities were selected and 46 were rejected.

With all three families active, 108 unsafe opportunities competed for 26
places. The selected set contained 9 ETH, 9 WBTC and 8 STABLE opportunities,
leaving 82 unattempted. Relative to each family's isolated 26 selections,
cross-collateral competition displaced 17 ETH, 17 WBTC and 18 STABLE
opportunities. The selected set was invariant to input permutation, backlog
carried forward correctly and all collateral/system accounting reconciled.

## 21. Classifications

The registered classifications are:

| Decision | Classification |
|---|---|
| Starting implementation | `multicollateral_core_compatible_with_repairs` |
| Collateral universe | `final_collateral_universe_ready_with_counterfactual_stable` |
| Portfolio registry | `final_portfolio_registry_ready` |
| Shock registry | `final_shock_registry_ready_with_counterfactual_stable_depegs` |
| Shared capacity | `shared_capacity_contract_valid` |
| Overall | `final_multicollateral_inputs_ready_with_caveats` |
| Stable family | `counterfactual_stable_proxy` |

The overall classification authorises pre-registration of the final
hierarchical multi-collateral experiments. It does not authorise selecting a
portfolio, shock or collateral treatment from these validation results.

## 22. Caveats

Stable vault sizes, collateral ratios and protocol settings are
counterfactual. The stable price owner is based on ordinary USDC observations,
but no USDC/SVB event is used and no empirical Maker USDC vault population is
claimed. The shared keeper-capacity range remains partially identified and is
not a physical network maximum.

The common population scale is standardised rather than historical. Exact-ilk
parameters are retained, while the current simulator applies mechanically
aggregated family settings. Oracle delay remains a zero transparent baseline,
and the pass does not resolve population-scale, oracle-delay or held-out
validation questions.

## 23. Next experiment boundary

The next authorised scientific pass is to pre-register and execute a
hierarchical final multi-collateral registry containing:

- Experiment A: idiosyncratic diversification;
- Experiment B: stress correlation;
- Experiment C: stable-collateral trade-off;
- Experiment D: shared keeper capacity.

The five portfolios and seven shocks are fixed input coordinates. Their
validation metrics do not supply a result-based screening or ranking rule.
Population robustness, oracle-delay robustness and held-out validation remain
separate later boundaries.

## 24. Production boundary

The `empirical_integrated_multicollateral` profile is experiment-ready but
opt-in. It is not selected by any production default. The legacy, empirical,
empirical-stress and integrated ETH profiles remain unchanged.

No substantive final multi-collateral experiment, final-validation simulation,
USDC/SVB validation, parameter recalibration, keeper recalibration or
confidence calibration occurred. The central shared cap remains 26 and
Stage 1-only confidence remains the final-profile baseline.

## 25. Reproducibility

The parent commit is `8d5ea2829f1481cc57e2760422d11fd452905bad`
(`Harden experiment infrastructure`). Registries, the opt-in profile, the
26,208-row market pool, deterministic seed registry, specification, validation
summaries, decision and reproducibility record are checksum-addressed.

The configuration SHA-256 checksums are
`75268fed6b3db5a80a822a80b8629291491cd73ce62b4c3e6cf3975060b4eb6d`
for the collateral registry,
`76aa03afa352d86be76fbc7e0153981589f50798c52aed7dfad897061b7960b1`
for the portfolio registry and
`a98df90e3e743fc22d9f92c38d53cf46a893928d3fe48eda9e609a20aa108581`
for the shock registry. The market pool checksum is
`e97570b94b2140f9a6dc6436b386ba0ea9e91d9de73b755cc38d8e971d91ed2e`.
The opt-in profile checksum is
`a2da654cdc9fc053c50f13aacb18e63ce7854bf47d6ad1519352467f6c7986fc`,
and its resolved identity is
`d0241808701d0472532c1f7c502ab6637afd60a50082b94bed9ff66f7ec2d53e`.
The immutable specification identity is
`2fa5fe41e6c510d9a3a4a69e5c72067ba99e131bbd044e37bc966d21d10895d9`;
the scientific-code identity is
`4e514cad4deac4cd32cd7e2c4c3d9fec83f52688d80ade9a7760262a08712632`.
Compact evidence checksums are recorded in the validation provenance manifest
rather than duplicated here. The shared manifest contains 11 entries owned by
this validation and 19 entries in total.

Non-host-dependent compact artefacts are reconstructed byte-identically.
Detailed diagnostics remain ignored, repository paths remain relative, and
the evidence records zero acquisition calls, live-network calls, final
experiments and final-validation simulations.
