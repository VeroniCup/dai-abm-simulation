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

Completed structural stages:

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
11. removal of temporary compatibility interfaces.

Stage 12 final review remains. The historical baseline remains unchanged under
`docs/repository_restructuring_baseline.md`.

## Regression status

The frozen smoke and Experiments 1–5 checksums are recorded in
[the regression guide](docs/validation/regression.md) and the
[Stage 1 baseline](docs/repository_restructuring_baseline.md).

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

The remaining empirical task is adoption and validation of defensible
parameter candidates, followed by calibrated counterfactual experiments.
Changes to auction execution, confidence mechanics, stable-depeg transmission
or keeper-capacity allocation require separate modelling decisions.
