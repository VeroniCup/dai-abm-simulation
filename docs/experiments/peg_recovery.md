# Peg recovery

## Research question

How does recovery of collateral value interact with confidence, active bad
debt and explicit DAI-market recovery channels?

## Implemented scenarios

The ETH shock is 43% at step 30. Recovery starts at step 40 and ends at step
90. Default recovery fractions are 0%, 25%, 50%, 75% and 100%. The experiment
uses the explicit recovery-enabled DAI-market configuration.

## Invocation

```python
from dai_sim.experiments.runner import run_peg_recovery_experiment

results, summary = run_peg_recovery_experiment()
```

## Interpretation and limitations

The experiment distinguishes collateral-price recovery from DAI-price
recovery. The recovery channel is reduced-form and does not model a specific
governance intervention or market-making strategy.
