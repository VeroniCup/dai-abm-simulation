# Collateral prices and oracles

## Price representation

Canonical prices are collateral mappings such as:

```python
{"ETH": 2000.0, "BTC": 30000.0, "STABLE": 1.0}
```

`CollateralPricePaths` contains aligned market and oracle arrays for every
collateral class. Legacy scalar, array and DataFrame ETH inputs are normalised
into this representation.

Implementation:

- [`collateral_prices.py`](../../src/dai_sim/model/collateral_prices.py)
- [`simulation.py`](../../src/dai_sim/model/simulation.py)

## Synthetic paths

The model supports constant, geometric-Brownian-motion, deterministic shock
and shock-recovery paths. The established scenarios use fixed seeds and
explicit shock timing. These stylised path parameters are experiment controls
unless a calibration document explicitly classifies them as empirical.

The empirical input path samples aligned historical return blocks through
`dai_sim.inputs.market`, preserving cross-asset and gas-state dependence. It
is opt-in through the empirical profile.

## Oracle delay

The oracle path is a lagged version of the corresponding market path. A common
delay is currently applied to all collateral classes. Liquidation eligibility
uses oracle prices; collateral valuation and reported market effects retain
the relevant market-price context.

This is an intentionally simple oracle abstraction. It does not reproduce OSM
voting, medianisation, circuit breakers or collateral-specific feed
infrastructure.

## Stable collateral

The STABLE model class is a stylised aggregation. Empirical inputs preserve
exact Maker ilk and token provenance before mapping into STABLE. USDC prices
support stable-collateral market conditions, but the current model has no
direct stable-depeg transmission into confidence or DAI demand.
