# Oracle-delay sensitivity

## Research question

How does lag between market and liquidation-oracle prices affect hidden
undercollateralisation, liquidation timing and DAI stability?

## Implemented scenarios

`run_oracle_delay_experiment()` uses delays of 0, 1, 3, 5 and 10 simulation
steps by default. The common ETH shock is 43% at step 30. Liquidation and
market settings are held fixed.

## Invocation

```python
from dai_sim.experiments.runner import run_oracle_delay_experiment

results, summary = run_oracle_delay_experiment()
```

## Interpretation and limitations

The main comparison is the duration and magnitude of divergence between market
risk and oracle-recognised risk. One delay currently applies to every
collateral type; the experiment does not reproduce feed-specific update rules.
