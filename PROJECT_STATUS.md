# Project status

## Current implementation

The simplified DAI model supports:

- ETH, BTC and stable collateral classes with one collateral type per vault;
- collateral-specific market and oracle paths;
- heterogeneous vault populations and target debt-share portfolios;
- collateral-specific liquidation ratios, penalties and close factors;
- profitability-gated liquidations under shared keeper capacity;
- gas costs, bad debt, confidence regimes, panic pressure and peg recovery;
- system-level and long-format collateral-level results.

Experiments 1–5 remain established ETH-only baselines. The multi-collateral
portfolio and shock experiment is implemented in
`src/dai_sim/experiments/runner.py`.

## Empirical inputs and calibration

Continuous market, gas, liquidation and protocol evidence has been acquired
and validated. Vault evidence uses representative ordinary and stress windows
rather than an exhaustive historical mutation census. Quiet-mature, USDC/SVB
and Terra/CeFi windows are complete, and the earlier continuous-acquisition
chunks remain preserved as methodology validation.

The repository contains reviewed candidates for market, gas, protocol, vault
and liquidation inputs. The opt-in empirical profile now supports:

- joint representative vault initialisation;
- empirical market-return blocks;
- component gas inputs;
- empirical liquidation-arrival demand separated from keeper throughput.

Legacy initialisation, market, gas and liquidation-demand behaviour remain the
defaults. Candidate estimation does not itself adopt values or authorise new
mechanics.

Detailed current guidance:

- [Empirical framework](empirical.md)
- [Parameter methodology](parameters.md)
- [Calibration documentation](docs/calibration/README.md)
- [Historical empirical reports](docs/archive/README.md)

## Repository restructuring

The domain-first repository structure is now authoritative. Completed
structural stages:

1. pre-migration baseline;
2. package and path infrastructure;
3. semantic source package;
4. semantic profiles and runtime inputs;
5. domain-first data and provenance;
6. domain workflows;
7. domain SQL hierarchy;
8. documentation consolidation;
9. semantic test hierarchy;
10. semantic output hierarchy;
11. removal of temporary compatibility interfaces;
12. final review and closure.

The bounded post-Stage-11 semantic-output correction and tracked-clone
self-containment correction are also complete. Temporary compatibility
interfaces have been removed. The Stage 12 working and tracked-only checkouts
each passed the then-current 491-test suite. The current working suite contains
501 passing tests after the historical confidence-evidence additions; runtime
inputs, smoke checks and Experiments 1–5 retain their frozen integrity
evidence.

Repository restructuring is closed. The
[final restructuring review](docs/validation/repository_restructuring.md)
records the architecture, 13-commit migration sequence, reproducibility
boundary and remaining limitations. The historical baseline remains unchanged
under `docs/repository_restructuring_baseline.md`.

## Regression status

The frozen smoke and Experiments 1–5 checksums are recorded in
[the regression guide](docs/validation/regression.md) and the
[Stage 1 baseline](docs/repository_restructuring_baseline.md). The Stage 12
review reproduced all of them without changing executable behaviour.

## Known limitations

- The simulator is not a full Maker auction engine.
- Stable collateral has no direct confidence or DAI-demand transmission
  channel.
- One oracle delay applies to all collateral paths.
- Behavioural confidence parameters remain incompletely identified.
- Representative vault windows do not identify unconditional event
  probabilities.
- Current results use a limited seed design and are preliminary dissertation
  evidence rather than final conclusions.

## Next research work

The behavioural-confidence calibration planning pass has resolved four core
specification choices in the [confidence and behavioural calibration
plan](docs/calibration/confidence_and_behaviour.md): sustained price recovery
uses the \(\pm0.5\%\) band for 24 consecutive hours; primary collateral stress
is lagged 24-hour ETH downside; liquidation-system pressure is measured by the
lagged backlog-to-clearance ratio and retained as a sensitivity/recovery gate;
and the new behavioural DAI response uses directly estimated effective
coefficients after scale normalisation.

These are pre-registered estimation choices, not adopted behavioural values.
The [confidence estimation design](docs/calibration/confidence_estimation.md)
preserves the binary audit: it fixes material downside at \(p<0.995\), defines
the six-hour persistence outcome, selects the tab-based backlog-to-clearance
measure after its reconstruction gate passes, and records the planned binary
logistic protocol that proved infeasible.

The binary persistence design is complete and non-estimable: its fixed
calibration sample contains 27 origins across 24 episodes, zero positive
outcomes, and no tab-pressure variation. No coefficient was fitted.

The [confidence evidence
redesign](docs/calibration/confidence_evidence_redesign.md) retains the 0.995
material threshold and six-hour horizon, but uses a continuous future downside
burden on a deterministic 00:00/06:00/12:00/18:00 UTC grid. Design A supplies
4,167 calibration origins, but only 47 have positive burden, 9 reach burden
0.10, all burden occurs in 2021, and both market predictors have zero MAD.
Design B adds Terra/CeFi hours but no burden and fails the same gates.
USDC/SVB remains an adequate untouched downside evaluation.

Tab pressure continues to pass its reconstruction gate but is positive at only
one calibration origin, in one month and one independent backlog episode, with
zero coincident burden. It is therefore fixed as a sensitivity predictor and
possible confidence-recovery gate, not a primary estimator input.

The pre-registered [Design C historical market
extension](docs/calibration/confidence_historical_market_evidence.md) is now
acquired and adopted. It supplies 39,456 complete DAI/ETH hours from 31
December 2019 through 30 June 2024 using the same Dune `prices.hour` and
CoinPaprika methodology as the existing panel. Both sparse positive-Q95
predictor transformations pass their declared gates, and USDC/SVB remains
untouched validation evidence.

Design C is nevertheless not eligible for fitting. It has 321 non-zero
calibration origins and 74 contributing episodes, but one December 2020–
January 2021 episode contributes 56.55% of total burden against the fixed 25%
ceiling. The final evidence-extension stop rule therefore closes the
predictive stress-proxy regression route. No coefficient was fitted.
Behavioural implementation remains unauthorised; the next methodological
boundary is a separately specified constrained simulated-moments calibration
with blocked and leave-one-event-out validation.

The remaining empirical work is adoption and validation of defensible
parameter candidates, followed by calibrated counterfactual experiments.
Changes to auction execution, confidence mechanics, stable-depeg transmission
or keeper-capacity allocation require separate modelling decisions and
authorisation.
