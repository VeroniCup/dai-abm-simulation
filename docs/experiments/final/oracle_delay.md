# Experiment E — Oracle delay

## 1. Purpose and scientific boundary

Experiment E is the fifth and final core component of the frozen dissertation
programme. It tests RQ2 and H2 by varying only the number of hourly steps by
which protocol-observed collateral prices lag contemporaneous market prices.
It evaluates mechanism sensitivity, not historical oracle performance.

> The treatments are transparent 0-, 1- and 2-hour simulation sensitivities and are not estimates of historical Maker oracle latency.

No delay is preferred or selected, the production zero-delay default remains
unchanged, and no parameter was recalibrated. The experiment identity is
`67ec5a1e03492608c7f847861f7dbd506d2a526dbf4107298241b26c855eb0f8`;
the frozen master programme identity remains
`084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260`.

## 2. Design and anchors

The two registered anchors are:

1. `empirical_crypto` under `joint_crypto_high_correlation`; and
2. `stable_supported` under `joint_crypto_stable_stress`.

Each anchor crosses `oracle_delay_low`, `oracle_delay_central` and
`oracle_delay_high`, resolved by registry identity
`2e562ef2618e472ce3b0551addf2596ddbe137910fa6d2ad5884ae71c674e46d`
to 0, 1 and 2 hourly steps. Six cells with 128 paired replications produce 768
substantive simulations. Every cell retains 500 vaults, 2.5 million DAI of
initial debt, target system collateralisation 3.6089387701260205, global
capacity 26, direct-cost-only participation and Stage 1-only confidence.

The experiment contains no gradual-shock control. It therefore establishes
delay effects under the two registered rapid shocks, not whether rapid shocks
are more delay-sensitive than gradual ones.

## 3. Delay semantics and common random numbers

The existing `collateral_prices._apply_oracle_delay` owner supplies the price
transformation. At delay (d), protocol price at hour (t) is market price at
(t-d); the initial market price is repeated for the first (d) hours. ETH,
WBTC and STABLE are shifted independently, with no interpolation or
cross-family leakage.

Within each anchor and replication, all treatments share the same vault
state, market and shock paths, gas path, gas-unit draws, liquidation arrivals,
DAI residual blocks, ranking rule and all other non-delay randomness. Market,
gas and DAI inputs remain contemporaneous. The oracle path alone differs.
All common-random-number and path audits pass.

## 4. Oracle-path and mismatch validation

Delay 0 equals the market path exactly and produces structural-zero mismatch.
The one- and two-step transformations pass initial-price repetition, family
scope, path immutability and deterministic-checksum gates.

The principal gap is

\[
Gap_{k,t}=\log(P^{market}_{k,t}/P^{oracle}_{k,t}),
\]

with absolute, oracle-overvaluation and oracle-undervaluation areas. System
metrics use frozen initial debt shares rather than treatment-dependent debt.
Mean debt-weighted absolute mismatch areas are:

| Anchor | 0 hours | 1 hour | 2 hours |
| --- | ---: | ---: | ---: |
| Empirical crypto / joint stress | 0 | 2.9354 | 4.7450 |
| Stable supported / combined stress | 0 | 2.2995 | 3.7209 |

Both adjacent increases and both zero-to-two paired intervals are adverse.
The direct mismatch mechanism is operational in both anchors.

## 5. False-safe, false-unsafe and timing diagnostics

`false_safe` means market unsafe but oracle safe; `false_unsafe` means market
safe but oracle unsafe. These states are diagnostic only: liquidation is
always triggered from oracle prices.

Mean false-safe debt-hours increase from zero to 81,883 and 163,531 in the
empirical-crypto anchor, and from zero to 17,455 and 32,194 in the
stable-supported anchor, at one and two hours respectively. Mean recognition
lag is exactly 0, 1 and 2 hours in the corresponding treatments. Mean
recovery staleness is likewise 0, 1 and 2 hours where both re-safety events
exist. Vaults lacking both relevant events remain not applicable rather than
receiving a fabricated zero.

False-unsafe vault-hours, debt-hours and peaks are retained in compact
evidence alongside family decompositions. Neither diagnostic substitutes a
market-price trigger into the scientific mechanism.

## 6. Liquidation timing, clustering and completion

The experiment records hourly eligible and newly eligible tab, selected
attempts, closures, rejections, concentration, binding, backlog and terminal
state. Capacity remains one global 26-opportunity queue.

In empirical crypto, mean backlog-area share is 0.06597, 0.05393 and 0.06901
at delays 0, 1 and 2. Mean maximum unresolved-tab share is 0.01629, 0.01483
and 0.01745; completion ratios are 0.8491, 0.8580 and 0.8531. The response is
countervailing across adjacent steps rather than smoothly adverse.

In stable supported, mean backlog-area share is 0.01014, 0.00824 and 0.01359;
maximum unresolved-tab share is 0.00441, 0.00389 and 0.00496; completion
ratios are 0.7703, 0.7670 and 0.7655. Capacity rejection remains a structural
zero in both anchors at the frozen capacity. Terminal unresolved tab is also
zero. The pre-registered downstream classifier therefore records
`delay_friction_partial` for both anchors, not full delay friction.

## 7. Solvency and bad-debt boundary

Liquidated-debt share and debt-weighted liquidated-vault share are retained
with family attribution. Delay changes eligibility timing and some completion
outcomes, but it does not generate a simple monotonic response across every
measure.

Realised-bad-debt share, positive realised bad debt and terminal active bad
debt are degenerate under the retained close-factor-one accounting boundary.
They are reported but excluded from E2 and overall support rules. This is an
accounting limitation, not evidence that oracle delay could never affect bad
debt under another population or close-factor design.

## 8. Peg outcomes

Below-peg burden, mean absolute peg deviation, minimum DAI price, restricted
mean sustained-recovery time and recovery probability are unchanged across
delays within each anchor. Mean below-peg burden is 0.26574, mean absolute
deviation is 0.000603, mean minimum price is 0.995842, and mean RMST is 74.76
hours. Recovery probability by 720 hours is a degenerate one.

E3 is consequently `peg_unchanged`. The Stage 1 market owner does not transmit
these small timing changes into different DAI paths under this design.

## 9. Registered decisions

- E1: `supported`;
- E2: `partially_supported`;
- E3: `peg_unchanged`;
- overall H2: `H2_oracle_delay_partially_supported`; and
- peg–solvency relationship: `solvency_deteriorates_peg_unchanged`.

E1 is supported because mismatch and recognition lag increase at both
anchors. E2 is partial because downstream effects exist but are modest,
metric-specific and sometimes countervailing between adjacent delays. E3 is
unchanged. Cross-anchor sensitivity is `metric_specific`; this is descriptive
and does not rank the two portfolios.

## 10. Execution and reproducibility

The ordinary sandbox stopped before worker creation because macOS semaphore
metadata was unavailable. Fresh narrow permission was used for:

```text
PYTHONPATH=src python workflows/experiments/final/oracle_delay.py run --workers 4
```

The audit records 768 completed simulations, 128 valid checkpoints, zero
failed or rerun replications, and zero missing, duplicate, invalid or orphan
checkpoints. Wall time was 486.349 seconds, throughput was 1.579 simulations
per second, and detailed ignored output occupies 7,565,237 bytes.

All non-host-dependent compact evidence was reconstructed twice in isolated
directories and was byte-identical. The experiment manifest now contains 67
records: 59 preserved records plus eight Experiment E artefacts. Experiments
A–D evidence and all 512 prior checkpoints remain byte-identical.

## 11. Limitations

- The three delays are transparent mechanism sensitivities, not empirical
  latency estimates.
- Only rapid registered shocks are evaluated.
- The stable family and combined stable stress remain counterfactual.
- Capacity does not bind, limiting queue-transmission evidence.
- Bad debt is degenerate under close-factor-one accounting.
- The high initial collateralisation and 500-vault population condition the
  magnitude of liquidation effects.
- No held-out or USDC/SVB evidence is used.
- Results do not justify selecting or runtime-adopting a delay.

## 12. Next boundary

The five-experiment core final programme is complete. The next authorised
scientific stage is the pre-registered H4 recovery and behavioural-
stabilisation evidence synthesis. Robustness, held-out validation, USDC/SVB
validation and code freeze remain pending.

Compact evidence is registered under
`data/provenance/experiments/final/oracle_delay/`. The specification checksum
is `acce1aafeabcc8ccfd63b4ca353e9839c1cc11373043432a47c31389eb8f0537`,
the seed-registry checksum is
`9f528c38a9a684df28174e6028242b159af04efafbf2fb919590c199af2a8eb2`,
the scientific-code identity is
`f70bda49fefe011e3fd64203674ac1b3f3c466704a5763a11d5bdf29e4f7bdea`,
and the simulation-core identity is
`6ee0a73fab7e4fd195664448a489c4f0cda16c07c68a67d862a7c36997ec3030`.
