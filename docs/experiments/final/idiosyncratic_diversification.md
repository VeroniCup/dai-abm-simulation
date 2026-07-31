# Experiment A — idiosyncratic diversification

## 1. Purpose

Experiment A is the first completed component of the pre-registered final
dissertation experiment programme. It addresses RQ4 and the isolated-shock
part of H3:

> Does unaffected collateral reduce system losses when a severe shock is
> confined to ETH or WBTC?

The experiment estimates diversification and exposure effects without
ranking or selecting a portfolio or shock. Its overall classification is
`H3_idiosyncratic_diversification_supported`.

## 2. Registered design

The eight-cell design crosses four portfolios:

- `eth_only`;
- `empirical_crypto`;
- `balanced_crypto`; and
- `stable_supported`;

with two shocks:

- `eth_idiosyncratic_severe`; and
- `wbtc_idiosyncratic_severe`.

Each cell has 128 replications, giving 1,024 substantive simulations. The
common settings are system-wide keeper capacity 26, `direct_cost_only`,
`risk_cost_rate = 0`, Stage 1-only confidence, zero oracle delay and
`full_week` collateral recovery. The total horizon is 768 hours, comprising
48 pre-shock hours and 720 post-shock hours.

The experiment uses paired common random numbers, nested collateral-family
draws and a fixed portfolio state within each replication across the two
shock treatments. Final-validation data, including USDC/SVB, are excluded.

## 3. Evidence and execution integrity

All 128 authoritative replication checkpoints completed and passed the
checkpoint, numerical, accounting, common-random-number, nested-draw,
price-isolation and path-order audits. They contain all eight cells and
therefore the complete 1,024 simulations. No simulation failed.

The compact cell, collateral and contrast evidence was reconstructed from
those original checkpoints. The reconstruction did not resume, repeat or
replace a replication. In particular:

- simulations rerun for evidence repair: 0;
- calibration runs: 0;
- Experiment B–E simulations: 0; and
- held-out validation runs: 0.

The experiment identity remains
`a9d7c3fa5dc5da9bcf61314a57501ea5a8be506e305eee6f45afaae3131600bb`,
under programme identity
`084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260`.

## 4. Evidence serialisation boundary

The first evidence write reached a JSON serialisation boundary because three
computed A1 counts were NumPy integer scalars rather than native Python
integers. This occurred after all simulations and scientific aggregation had
completed.

The repair is classified `evidence_serialization_infrastructure`. It
normalises NumPy scalar and array containers only at the JSON boundary. It
does not change a model equation, random stream, checkpoint, aggregation,
contrast, decision rule or scientific result. Evidence was rebuilt twice in
isolated temporary directories before promotion, while the result-blind
pre-registration artefacts and all original checkpoints were preserved.

The registered execution source identity
`759748068fec4d45c257a649189b37234d7dd6d23e7ccf4273067bd4c2d1c00a`
owns the completed scientific matrix. The post-execution operational identity
`7cce1942e79f29aa584c1720cceaedcff003666d29dfd63d2deec299634dba0b`
includes the JSON-boundary repair. The registered Experiment A identity
remains unchanged; no new scientific experiment identity was created.

This is an operational evidence-writing correction, not a scientific
limitation and not an additional experiment execution.

## 5. Registered analytical components

### A1 — ETH-shock diversification

Each diversified portfolio is compared with `eth_only` under
`eth_idiosyncratic_severe`. The registered beneficial rule requires at least
two of the paired 95% intervals for realised bad-debt share, backlog-area
share and liquidated-debt share to lie below zero, with no clearly adverse
realised-bad-debt interval.

`balanced_crypto` and `stable_supported` each satisfy that rule.
`empirical_crypto` does not. Because at least two diversified portfolios
satisfy it, A1 is `supported`.

### A2 — WBTC exposure gradient

The WBTC exposure order is:

1. `eth_only`;
2. `stable_supported`;
3. `empirical_crypto`;
4. `balanced_crypto`.

The ETH-only negative control has zero direct WBTC loss. Raw liquidated debt
and backlog are informative and non-decreasing with WBTC exposure. Realised
bad debt is constant and therefore uninformative under the current canonical
full-close accounting semantics. Exposure-normalised measures are retained
and interpreted separately rather than used to conceal the raw exposure
gradient.

A2 is `exposure_gradient_consistent`.

### A3 — shock localisation

The ETH shock affects only the ETH collateral path directly, and the WBTC
shock affects only the WBTC collateral path directly. The stable path remains
ordinary under both treatments. There is no price leakage or path-order
effect, and both collateral-level and system-level accounting reconcile. All
registered nested-draw checks also pass. A3 is
`shock_localisation_valid`.

## 6. Solvency and peg results

The registered relationship is `solvency_improves_peg_unchanged`.
`balanced_crypto` and `stable_supported` have beneficial solvency evidence
under the ETH-specific shock, while all five registered peg measures are
unchanged for every diversified portfolio relative to `eth_only`.

This separation is economically interpretable. In the current Stage 1-only
DAI mechanism, the isolated collateral path can alter liquidation and backlog
outcomes without introducing a direct collateral-composition term into the
DAI-price equation. The result does not imply that collateral composition
could never affect the peg under a different, separately specified
behavioural channel.

## 7. Interpretation

The joint registered conclusions are:

- A1: `supported`;
- A2: `exposure_gradient_consistent`;
- A3: `shock_localisation_valid`; and
- overall H3:
  `H3_idiosyncratic_diversification_supported`.

The support is deliberately narrow: multi-collateral composition can reduce
system losses under isolated collateral-specific shocks, and WBTC losses
increase consistently with WBTC exposure. It does not establish resilience
under correlated crypto stress or stable-proxy impairment.

## 8. Limitations

- STABLE is a counterfactual stable proxy rather than an empirical Maker USDC
  vault family.
- Oracle delay remains the transparent zero-delay baseline pending its
  separate freeze.
- Isolated-shock evidence cannot establish correlated-stress resilience.
- Under the canonical close-factor-one owner, terminal debt may be recorded
  as keeper-repaid, leaving realised bad debt structurally zero. This
  registered measurement boundary was retained without post-result retuning.
- The result does not rank portfolios or shocks and does not select a runtime
  configuration.

## 9. Programme decision

Experiment A is complete. No portfolio, shock or runtime profile has been
selected or adopted. Experiment B, correlated stress, is the next authorised
pass but has not been executed. Experiments B–E all remain unexecuted; the
separate restrictions on Experiments C–E, including the blocked oracle-delay
freeze for Experiment E, remain in force.
