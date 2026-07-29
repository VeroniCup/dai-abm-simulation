# Conditional confidence event simulation

## 1. Purpose and dormant boundary

The conditional event simulator supplies the bridge between the accepted
Stage 1 market response and a later bounded Stage 2 simulated-moments
evaluation. It is owned by
`src/dai_sim/calibration/event_simulation.py`, is calibration-only and has no
production caller. No runtime profile enables persistent confidence.

This implementation validates interfaces and computational feasibility. The
separate [Sobol-search execution layer](confidence_sobol_search.md) reuses this
mechanism and its exact event metrics to rank the fixed candidate design. The
event simulator itself still does not select or runtime-adopt
\(\alpha_d\), \(\alpha_r\), \(C_{\min}\) or \(\kappa_P\).

## 2. Conditional experiment, not exact replay

Each experiment conditions on an observed hourly ETH path and the observed DAI
price at the beginning of a 48-hour pre-roll. All subsequent DAI prices,
confidence states, vault valuations and liquidation outcomes are simulated.
Observed future DAI prices remain targets only.

The design therefore does not reproduce the exact historical Maker vault
population, collateral composition, keeper participation or protocol state.
It tests whether one standardised mechanism can reproduce event-level
behaviour under historical collateral conditions.

## 3. Standardised initial-state ownership

The complete empirical profile owns the primary normalisation:

- 500 vaults;
- total initial debt of \(500\times5{,}000=2.5\) million DAI;
- an ETH-only mechanism core;
- joint debt-weight and collateral-ratio draws from the reviewed normal-regime
  ETH vault pool;
- sampled debt weights rescaled once to the fixed system-debt normalisation;
- collateral quantities derived from debt, sampled collateral ratio and the
  event pre-roll-start ETH price;
- no initially liquidatable vault;
- zero initial active and realised bad debt;
- zero initial unresolved and trailing cleared tab; and
- confidence one with stability counter zero.

The empirical profile also owns the liquidation penalty, close factor, fixed
attempt gas cost, unlimited configured keeper-capacity ceiling and zero oracle
delay. The existing short-horizon vault mechanics do not accrue a stability
fee; that absence is recorded rather than silently approximated.

## 4. Event-invariant and event-varying quantities

Vault count, total debt, sampling design, protocol and liquidation settings,
capacity rule, gas treatment, collateral mode, initial insolvency state and
initial confidence are invariant design quantities. The seed registry permits
the sampled vault realisation to vary by event and replication while retaining
the same distribution and total debt.

Only the starting observed DAI price, observed ETH path, evaluation horizon and
seed-owned realisation vary. Parameters are never tuned to an event.

## 5. Pre-roll and common horizon

Every eligible calibration event has an exact 48-hour ETH pre-roll. The common
maximum total horizon is

\[
48+\left\lceil
\frac{\max_e(\text{observed event duration}_e)+24}{24}
\right\rceil 24=792\text{ hours}.
\]

The maximum uses the 74 calibration events only; the final USDC/SVB event is
excluded. An event is evaluated through its observed duration plus 24 hours.
If simulated sustained recovery has not completed, it may continue to the
common maximum and is then right-censored.

## 6. Stage 1 and residual ownership

The event simulator reads registered Stage 1 evidence and refuses evidence
that is unaccepted, unregistered, checksum-mismatched or runtime-adopted. It
uses the stored point estimates at full precision rather than duplicating them
in source code.

The centred ordinary-hour residual sequence and eligible 24-hour moving blocks
are reconstructed from the ignored canonical panel. Their registered sequence
and block-specification checksums must reproduce before simulation. Complete
blocks are sampled with the market-innovation stream, concatenated in order and
truncated to the required path length.

## 7. Within-hour causal ordering

One hour proceeds as follows:

1. read the lagged simulated DAI state and observed ETH history;
2. scale the lagged below-peg gap and lagged 24-hour ETH downside;
3. update persistent confidence from the previous hour's recovery conditions;
4. apply the accepted coefficient-normalised response and current residual;
5. value vaults at the current observed ETH price;
6. sample existing liquidation demand and run existing liquidation logic;
7. reconcile cleared tab, unresolved tab and active bad debt;
8. set recovery inputs for the following hour; and
9. record conditional metrics.

No step reads future ETH, observed future DAI, future liquidation results or
future recovery status.

## 8. Liquidation-pressure gate

Unresolved tab \(U_t\) is the remaining DAI debt of active liquidatable vaults
after current-hour keeper action. Cleared tab is the existing liquidation
summary's `debt_repaid`; \(C_t^{24}\) is its trailing 24-hour sum. Diagnostic
pressure is

\[
L_t=\frac{U_t}{U_t+C_t^{24}+\epsilon}.
\]

The primary recovery rule is \(U_t=0\) within \(10^{-9}\) DAI. It does not
substitute the liquidatable-vault share and estimates no liquidation
coefficient.

## 9. Material-active-bad-debt gate

Any material active bad debt blocks recovery. Numerical materiality is

\[
\tau_B=\max(10^{-9},10^{-12}D_0)\ \text{DAI}.
\]

For the standard \(D_0=2.5\) million DAI state,
\(\tau_B=2.5\times10^{-6}\) DAI. Active bad-debt ratios above 0.1% and 1%
are diagnostics only; they do not select or modify the primary gate.

## 10. Conditional event metrics

The compact result records price minima and downside burdens, first return and
sustained recovery, failed recovery attempts, overshoot, confidence minima and
recovery, unresolved and cleared tab, active bad debt, numerical-bound
bindings and right-censoring. Full smoke trajectories remain ignored
diagnostics and are not tracked evidence.

SMM aggregation averages replications within event and then gives events equal
weight. It returns the fixed eight-moment schema but never invokes the
objective during this pass. Cumulative burden and burden after first return
remain diagnostic exclusions.

## 11. Deterministic probes and smoke subset

Interface probes are Sobol indices 0, 127 and 255 plus explicit
\(\kappa_P=0\) and \(C_{\min}=0\) boundary models. They are not estimates and
are not ranked.

The smoke subset contains one calibration event from each first-six-hour
burden quartile. Within a quartile, the event with the lowest SHA-256 content
hash is selected. The rule is stable under catalogue row reordering and cannot
select the final validation event.

## 12. Benchmark and workload implications

The bounded benchmark executes four events, one interior probe, two
replications and one registry: eight event-replication runs. Compact evidence
reports observed wall time, run-time distribution, traced peak memory and
linear extrapolations for pre-registered future workloads. Those workloads
were not executed and the optimisation design was not altered.

If later evaluation is expensive, acceptable engineering responses are
event-level parallelism and caching deterministic states, ETH paths, residual
blocks and vectorised metric inputs. Reducing statistical coverage based only
on this benchmark is not authorised.

## 13. Evidence and diagnostics

Compact evidence is tracked in
`data/provenance/calibration/confidence/` and registered in the calibration
manifest. It contains the conditional specification, standardised state,
recovery gates, smoke checksums and benchmark summary. Generated trajectories,
gate transitions and timing rows belong under
`outputs/diagnostics/calibration/confidence/event_simulation/` and remain
ignored.

## 14. Validation boundary

The final USDC/SVB event is parsed and its ETH path completeness is checked,
but it is not simulated. It does not choose the state, gates, probes,
benchmark or implementation acceptance.

## 15. Remaining work before SMM evaluation

A later, separately authorised pass may evaluate the fixed objective over a
bounded subset with common random numbers. It must preserve censoring,
equal-event weighting, validation partitions and the registered mechanism.
This implementation neither supplies Stage 2 defaults nor identifies a
preferred probe.

## 16. Production-integration boundary

Persistent confidence remains absent from
`src/dai_sim/model/simulation.py`. Production integration, runtime adoption,
parameter fitting, final validation and counterfactual experiments are all
separate decisions.
