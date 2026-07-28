# Simulation ordering, outputs and metrics

## Step ordering

The simulation engine composes collateral paths, vault state, liquidation
decisions, confidence and the DAI market. At each step it:

1. resolves market and delayed oracle prices;
2. evaluates vault and system state;
3. identifies and ranks liquidation opportunities;
4. applies keeper profitability, demand and shared capacity constraints;
5. updates vaults and liquidation summaries;
6. derives confidence and panic pressure;
7. updates the DAI market price;
8. records system and collateral-level metrics.

The authoritative implementation is
[`simulation.py`](../../src/dai_sim/model/simulation.py). Metrics and experiment
summaries are in
[`metrics.py`](../../src/dai_sim/model/metrics.py) and
[`experiments/summaries.py`](../../src/dai_sim/experiments/summaries.py).

## Results

Established system-level columns remain compatible with the ETH-only
experiments. Multi-collateral attribution is represented in long-format
collateral-level results rather than adding one fixed column per asset.

Core outcomes include:

- DAI price and peg deviation;
- active debt and collateral value;
- system and vault collateral ratios;
- liquidatable and liquidated vault counts;
- attempted, profitable, successful and capacity-limited liquidations;
- debt repaid and collateral liquidated;
- active and realised bad debt;
- expected and realised keeper profit;
- confidence and panic state.

Generated detailed results live under `outputs/experiments/`, figures under
`outputs/figures/`, diagnostics under `outputs/diagnostics/`, and compact
reporting tables under `outputs/tables/`. Figures and summary tables must not
be mixed into detailed experiment directories.

## Determinism

The established runners pass fixed random seeds. Regression comparison removes
path and runtime metadata and canonicalises substantive tables before hashing.
See [regression validation](../validation/regression.md).
