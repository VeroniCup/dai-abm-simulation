# Liquidation calibration

## Evidence

The liquidation domain contains:

- a continuous Liquidations 2.0 action fact and unique transaction bridge;
- auction summaries and hourly aggregates;
- actual successful-Take and failed-call transaction gas;
- tracked keeper-gas and liquidation-arrival runtime pools;
- provenance linking Dune query and execution identifiers to ignored data.

The principal ilks are ETH-A/B/C and WBTC-A/B/C. Auction identity is always
`(clipper_contract, auction_id)`; auction ID alone is not globally unique.

## Event semantics

Dog Bark annotates liquidation initiation. Clipper Kick, Take, Redo and
exceptional Yank actions describe auction activity. Successful and failed
decoded calls remain distinct. A liquidation can have multiple transactions,
Takes, participants and resets.

Top-level transaction gas is deduplicated by transaction hash before
transaction-level distributions or totals are calculated. It is never
allocated once per action. Failed inner-call gas is not observable from the
top-level transaction alone.

## Estimators

Liquidation arrival is estimated as a hurdle process:

1. probability of a positive liquidation count;
2. conditional distribution of positive severity.

The continuous hourly panel supplies exposure denominators and clustering
evidence. Representative vault windows supply collateral-state context but do
not define unconditional arrival probabilities.

Keeper gas estimation uses the clean successful-Take class as the primary
sample: one successful Take, one auction and no other liquidation action in the
transaction. Multiple Takes, other actions, multiple auctions and ambiguous
transactions are retained for sensitivity analysis.

The active implementation is:

- [`liquidations.py`](../../src/dai_sim/calibration/liquidations.py);
- [`inputs/liquidations.py`](../../src/dai_sim/inputs/liquidations.py);
- `workflows/calibration/liquidations.py`;
- `workflows/liquidations/build_inputs.py`.

## Model mapping

The model separates:

- liquidation demand;
- keeper profitability;
- close factor;
- shared per-step capacity;
- gas cost;
- auction evidence.

Historical full-urn Bark–grab closure supports review of the simulator's
per-vault close fraction but is not keeper throughput. Clipper Take fractions
are auction execution evidence and are not substituted for the close factor.
The model contains no auction engine.

## Validation and limitations

Validate action-to-transaction coverage, Bark–Kick and Bark–grab linkage,
event/call ambiguity, transaction-gas deduplication, terminal classification,
unit scaling and collateral-specific distributions. Retain Redo, Yank,
unresolved and ambiguous cases.

Keeper profitability is a proxy because capital costs, private order flow,
bundling and off-chain operational costs are not fully observed. Sparse events
create wide uncertainty for conditional tails and collateral-specific
estimates.

## System-wide execution calibration

The subsequent
[system-wide keeper execution study](keeper_execution.md) uses reconstructed
start-of-hour unsafe inventory rather than positive closures as its demand
denominator. It confirms that `max_liquidations_per_step` is one global hourly
count after cross-collateral ranking. Calendar instability, wide bootstrap
uncertainty and an underpowered mixed-versus-dominant composition comparison
leave the candidate range partially identified.

Clean successful-Take economics likewise support only revealed lower-bound
sensitivities for `risk_cost_rate`; failed decoded calls do not identify
rejected economic opportunities. The resulting registry is candidate-only and
is not imported by any established runtime profile.
