# Parameter methodology

Simulator inputs are classified before adoption:

- direct protocol observations;
- direct empirical measurements;
- statistical estimates;
- calibrated behavioural parameters;
- fixed modelling assumptions or experimental sensitivities.

This distinction prevents a protocol constant, empirical candidate or
scenario control from being presented as the same kind of evidence.

## Authoritative guides

- [Parameter sources and acquisition classes](docs/calibration/parameter_sources.md)
- [Parameter-by-parameter estimation plan](docs/calibration/parameter_estimation.md)
- [Adoption and model-interface decisions](docs/calibration/parameter_adoption.md)
- [Representative vault evidence](docs/calibration/vaults.md)
- [Protocol reconstruction](docs/calibration/protocol.md)
- [Market and gas calibration](docs/calibration/market_and_gas.md)
- [Liquidation calibration](docs/calibration/liquidations.md)

No candidate becomes an adopted simulator value merely because it has been
estimated. Adoption requires semantic compatibility with the current model,
provenance, uncertainty and validation evidence, and explicit review of any
mechanics change.

## Parameters requiring later decisions

Outstanding modelling choices include direct stable-collateral contagion,
collateral-specific oracle delays, endogenous keeper-capacity allocation,
collateral-specific slippage, vault-owner intervention and time-varying
portfolio composition. These remain sensitivity or future-interface questions;
they are not silently inferred from the current datasets.
