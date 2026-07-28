# Protocol-parameter reconstruction

## Scope

Protocol histories cover ETH-A/B/C and WBTC-A/B/C from 1 June 2021 through
30 June 2024, with the latest valid pre-sample state or a documented
in-sample activation boundary.

## Sources and units

The reconstructed modules are:

| Module | Parameters |
| --- | --- |
| Vat | ilk debt ceiling `line`, global ceiling `Line`, minimum debt `dust` |
| Spot | liquidation ratio `mat`, oracle adapter `pip`, effective spot |
| Jug | ilk stability-fee `duty`, global `base` |
| Dog | liquidation penalty `chop`, ilk/global capacity, Clipper mapping |
| Clipper | `buf`, `tail`, `cusp`, `chip`, `tip`, `stopped` |

Raw integer strings are retained. Conversions use WAD \(10^{18}\), RAY
\(10^{27}\) and RAD \(10^{45}\). The annualised stability fee combines
simultaneously effective duty and base:

\[
\left(\frac{\text{duty}+\text{base}}{10^{27}}\right)^{31{,}536{,}000}-1.
\]

Observed calls and documented contract-default states remain distinguishable.
No value is forward-filled before the ilk, contract or mapping becomes active.

## Activation and migration

WBTC-B and WBTC-C activate inside the sample; their Vat line and dust remain
null before their validated activation boundaries. Spot oracle and Dog
Clipper mappings are effective-dated. Clipper `stopped` default states require
verified source/default semantics and deployment/mapping evidence; a missing
call is not assumed to mean zero without that provenance.

## Model use

Protocol constants support historical replay and define collateral-specific
risk inputs. They are not estimates of behaviour. Timestamp selection must
choose the setting effective at the simulation or replay boundary.

The active implementation is:

- [`protocol.py`](../../src/dai_sim/calibration/protocol.py);
- [`inputs/protocol.py`](../../src/dai_sim/inputs/protocol.py);
- `workflows/protocol/acquire.py`;
- `config/protocol/parameters.yaml`;
- `config/protocol/collateral_types.csv`.

## Limitations

Caller-triggered getters are not continuous state histories. Debt and
utilisation cannot be inferred from parameter-setting calls. Historical
contract defaults require explicit source and deployment evidence, and
protocol constants should not be pooled across ilks or effective periods.
