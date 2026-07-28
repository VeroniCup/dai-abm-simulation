# Empirical framework

The empirical design estimates distributions and conditional behaviour for an
interpretable multi-collateral DAI simulation. Continuous hourly market, gas
and liquidation panels are combined with representative vault windows and
effective-dated protocol settings. Named crises support stress coverage and
validation; they are not the sole basis for parameter tuning.

The complete research design, hypotheses, outcome measures, robustness policy
and identification safeguards are in
[the empirical research design](docs/overview/research_design.md).

## Data and calibration

- [Acquisition](docs/data/acquisition.md)
- [Processing](docs/data/processing.md)
- [Provenance](docs/data/provenance.md)
- [Market and gas calibration](docs/calibration/market_and_gas.md)
- [Representative vault calibration](docs/calibration/vaults.md)
- [Liquidation calibration](docs/calibration/liquidations.md)
- [Protocol reconstruction](docs/calibration/protocol.md)
- [Parameter estimation](docs/calibration/parameter_estimation.md)
- [Parameter adoption](docs/calibration/parameter_adoption.md)

## Identification safeguards

Calibration, validation and scenario construction remain separate. The design
uses time-window and probability-based estimators, preserves uncertainty,
withholds the FTX interval from primary calibration, and avoids tuning the
model to reproduce one crisis. Protocol constants, empirical estimates,
literature assumptions and experimental scenario values remain distinct.

The representative vault windows are purposive. Their event frequencies must
not be interpreted as unconditional arrival probabilities; continuous panels
provide the relevant exposure denominators. Manager ownership is an identity
proxy rather than verified beneficial ownership, and the WBTC market series is
a BTC-collateral proxy rather than native BTC.

## Validation

Validation covers data integrity, distributional and moment matching,
multi-seed stability, sensitivity to windows and thresholds, withheld-period
performance and fixed-seed regression checks. See
[regression and robustness](docs/validation/regression.md).
