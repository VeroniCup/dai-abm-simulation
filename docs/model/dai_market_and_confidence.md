# DAI market and confidence

## Confidence regimes

The confidence module maps DAI price, liquidatable-vault share and bad debt
into normal, stress or panic states. Each state has a configured confidence
level, and panic creates additional selling pressure.

Implementation:

- [`confidence.py`](../../src/dai_sim/model/confidence.py)
- [`market.py`](../../src/dai_sim/model/market.py)

The thresholds are transparent experimental parameters. Empirical gas and
market regimes do not automatically replace the model's confidence states.

## DAI price adjustment

The DAI market is a reduced-form price-adjustment mechanism. Below the peg,
arbitrage demand is scaled by the peg gap and confidence. Above the peg, supply
pressure is scaled by the above-peg strength. Panic selling adds supply
pressure. The net pressure, adjustment speed and noise term update the DAI
price inside configured bounds.

An optional recovery channel adds arbitrage and policy feedback below the peg,
discounted by confidence and active bad debt. The peg-recovery experiment
varies the collateral recovery path while retaining explicit DAI-market
recovery parameters.

## Interpretation

Confidence is a modelling state, not an observed Maker variable. Its parameters
require calibration or sensitivity treatment. DAI-price effects arise through
the explicit demand, supply, panic and recovery equations; they do not arise
directly from collateral labels.

The current model does not include a direct stable-collateral depeg coefficient,
endogenous governance response or order-book liquidity.
