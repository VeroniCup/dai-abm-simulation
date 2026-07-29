# Data processing

## Boundaries

Raw files are immutable acquisition artefacts. Processing is local,
deterministic with respect to observed values, and writes domain-owned
generated outputs. It does not call Dune, impute missing observations or alter
raw data.

The domain lifecycle is:

```text
raw → processed → model_inputs
          ↘ provenance
```

Raw and processed payloads are ignored by Git. Compact runtime model inputs
and their manifests are tracked because simulations depend on them.

## Market

`workflows/market/process.py` verifies the raw checksum and creates the hourly
wide market panel, log returns, DAI/USDC peg deviations and stablecoin-extreme
review under `data/market/processed/`.

`workflows/market/process_historical_evidence.py` validates and harmonises the
separate full-range DAI/ETH confidence-calibration extract, compares the
overlapping prices with the operational panel and evaluates the frozen Design
C scaling and burden gates. It creates no coefficients and does not alter
runtime market inputs.

Prices are not winsorised, clipped, smoothed, interpolated or forward-filled.
The first log return remains missing. Review flags do not classify values as
errors.

`workflows/market/build_inputs.py` creates the aligned environment block pool
under `data/market/model_inputs/environment_blocks/`.

## Gas and the combined environment

`workflows/gas/process.py` preserves the 20 raw gas variables, derives explicit
spreads, ratios, fee shares, logs and changes, and joins exact UTC hours to the
processed market panel. Gas-only products live under
`data/gas/processed/`; the aligned market–gas panel is market-owned under
`data/market/processed/combined/`.

Structural pre-London nulls remain null. Candidate gas regimes and standardised
gas-cost indices are descriptive and do not set simulator parameters.

## Vaults

Representative vault processing expands observed Vat fork calls locally into
balanced source and destination mutations while retaining the raw call. It
reconstructs exact integer ink and art state from an opening boundary, applies
the latest effective accumulated rate and joins collateral prices and protocol
settings.

`workflows/vaults/build_inputs.py` creates the tracked initialisation pool
under `data/vaults/model_inputs/initialisation/`. Window sampling preserves
regime and exact-ilk provenance.

## Liquidations

Liquidation processing reconciles actions and transactions by hash, deduplicates
gas at transaction level, classifies successful-Take transaction structure and
builds arrival and keeper-gas pools:

- `data/liquidations/model_inputs/arrival/`;
- `data/liquidations/model_inputs/keeper_gas/`.

Historical action rows are never used as independent transaction-gas
observations.

## Protocol

Protocol processing constructs sparse setting changes, effective-dated
intervals and hourly ilk state. Values are null before activation; observed
calls and documented contract defaults remain distinguishable.

## Generated diagnostics

Generated calibration and input-construction diagnostics live under
`outputs/diagnostics/`. They are reproducible outputs, not authoritative
empirical panels or compact runtime model inputs. New domain data must remain
under the owning `data/<domain>/` lifecycle.

## Determinism

Processing metadata records input and output dimensions, content checksums,
script checksums, transformations and validation status. Creation timestamps
may differ between runs; observed values and deterministic serialisation must
not. No processing command should overwrite a validated raw file.
