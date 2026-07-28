# Liquidations and keeper capacity

## Eligibility and profitability

Vault eligibility is determined by the vault's collateral ratio relative to
its liquidation ratio. The keeper decision is separate. For an eligible vault,
the simplified expected profit is:

\[
\Pi_i =
D_i f_i p_i
- G
- D_i f_i r,
\]

where \(D_i\) is debt, \(f_i\) is the close factor, \(p_i\) is the liquidation
penalty or gross reward rate, \(G\) is gas cost and \(r\) is a proportional
risk-cost rate. The keeper acts only when expected profit is positive.

Implementation:

- [`liquidation.py`](../../src/dai_sim/model/liquidation.py)
- [`vault.py`](../../src/dai_sim/model/vault.py)

## Execution and bad debt

`Vault.partial_liquidate` repays up to the configured close-factor share and
removes collateral value including the penalty, subject to available
collateral. A partial action can leave an active residual vault. Bad debt is
measured from the remaining position; it is not synonymous with liquidation.

Collateral-specific penalty and close-factor values override shared
`LiquidationConfig` values when supplied by the portfolio.

## Capacity and demand

Profitable opportunities are ranked by expected profit. The shared
`max_liquidations_per_step` limit bounds executed actions across all collateral
types. Capacity-limited opportunities remain explicit failed attempts.

The empirical liquidation-arrival path can bound exogenous demand separately
from keeper capacity. It is implemented in
[`inputs/liquidations.py`](../../src/dai_sim/inputs/liquidations.py) and is
opt-in. Legacy all-eligible demand remains the default.

## What is not implemented

The simulator does not contain a Clipper auction engine, partial Take bidding,
auction resets, keeper competition or transaction-by-transaction settlement.
Historical Bark, Kick, Take and Redo evidence is used for calibration and
validation; it is not replayed as a contract-level auction lifecycle.

Keeper gas estimates use top-level transaction evidence only where
classification avoids duplicate attribution. They must not be interpreted as
inner-call gas.
