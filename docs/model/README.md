# Model mechanics

The active model documentation is organised by economic concern:

- [Collateral and vaults](vaults_and_collateral.md)
- [Collateral prices and oracles](prices_and_oracles.md)
- [Liquidations and keeper capacity](liquidations.md)
- [DAI market and confidence](dai_market_and_confidence.md)
- [Simulation ordering, outputs and metrics](simulation_and_outputs.md)

The authoritative implementation is under
[`src/dai_sim/model/`](../../src/dai_sim/model/). The model is a simplified
research abstraction: it represents the mechanisms required by the
dissertation, not the complete Maker contract or auction system.
