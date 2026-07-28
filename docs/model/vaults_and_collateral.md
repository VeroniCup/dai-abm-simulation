# Collateral and vault state

## Collateral portfolios

`CollateralConfig` describes one model collateral class and its initial price,
target debt share and optional risk overrides. `CollateralPortfolioConfig`
validates a collection of collateral classes. The implemented classes used by
the established experiment are ETH, BTC and STABLE.

Each vault holds exactly one collateral type. Portfolio allocation targets
system debt shares rather than equal vault counts. ETH-only is the default
special case and remains compatible with scalar ETH price inputs.

Implementation:

- [`collateral.py`](../../src/dai_sim/model/collateral.py)
- [`vault.py`](../../src/dai_sim/model/vault.py)

## Vault state

The canonical vault fields are:

- `vault_id`;
- `collateral_amount`;
- `collateral_type`;
- `debt_dai`;
- `liquidation_ratio`;
- active and liquidation state.

At price \(P_{c,t}\), collateral value and collateral ratio are:

\[
V_{i,t}=q_{i,t}P_{c,t},
\qquad
CR_{i,t}=\frac{V_{i,t}}{D_{i,t}}.
\]

A zero-debt vault has infinite collateral ratio. An active vault is
liquidatable when its collateral ratio is below its liquidation ratio.
Liquidatable status, liquidation execution and realised bad debt are separate
states.

## Initial populations

The legacy generator samples debt and collateral ratios from configured
parametric distributions and clips initial collateral ratios above the
liquidation boundary. The empirical path can instead draw joint vault
characteristics from the tracked representative-regime pool through
`dai_sim.inputs.vaults`. It is opt-in; legacy initialisation remains the
default.

Multi-collateral generation retains collateral-specific liquidation ratios
where supplied and preserves the shared defaults otherwise. Random seeds are
passed explicitly by the established runners.

## Limitations

Vault owners do not currently follow an endogenous behavioural policy for
repayment, borrowing or collateral management during the simulation. The
model does not reproduce every Maker collateral type or proxy ownership
relationship. Empirical CDP manager owners are identity proxies, not verified
beneficial owners.
