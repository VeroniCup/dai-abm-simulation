# Runtime data ownership

## Purpose

The submitted runtime is deliberately smaller than the processed evidence used
to construct and validate it. Historical experiments and held-out validation
were executed against the complete processed sources, whose paths and SHA-256
values remain part of frozen scientific evidence. Current clean-checkout
resolution uses exact, content-addressed runtime owners instead. This migration
changes data ownership only; it changes no scientific value, window, portfolio,
shock, parameter or default.

The portable boundary is classified as `portable_runtime_resolution_v2` and is
defined by [the sidecar runtime map](../../config/submission/runtime_input_map.yaml).
It is distinct from, and does not replace, any historical experiment or
validation identity.

## Source-to-runtime map

| Historical processed source | Historical role | Portable runtime owner | Runtime treatment |
| --- | --- | --- | --- |
| `data/protocol/processed/hourly_protocol_parameters.csv` | Source of the frozen protocol registry | `config/protocol/final_collateral_registry.yaml` | Provenance-only at runtime; the full hourly source is optional verification and rebuild evidence. |
| `data/market/processed/dune_hourly_market_prices_processed.csv` | Source of the registered joint market blocks | `data/market/model_inputs/multicollateral_blocks/pool.csv` | The existing tracked pool is the runtime owner; the full panel is optional rebuild evidence. |
| `data/market/processed/combined/hourly_market_gas_panel.csv` | Source of the two held-out paths | `data/model_inputs/validation/final_validation_market_gas_paths.csv` | Exact 816-row derivative used by the frozen validation loader. |

All runtime owners are verified against explicit SHA-256 values before use. If
an original processed source is present, its historical checksum is also
verified. A missing original source is valid; a present but corrupted original
source is not. There is no network fallback and no user-home fallback.

## Held-out derivative

The final-validation derivative contains only the seven fields consumed by
the validation runtime: timestamp, ETH and WBTC log returns, DAI and USDC
prices, USDC log return, and median effective gas price. It preserves exactly:

- 480 hours from 1 November to 21 November 2022, exclusive at the upper bound;
- 336 hours from 6 March to 20 March 2023, exclusive at the upper bound.

The derivative is neither rounded nor interpolated. Local full-versus-compact
validation confirms identical CSV values, parsed values, missingness masks and
downstream arrays, with a maximum numeric difference of zero.

## Historical identity boundary

The pre-migration resolver bytes are preserved as non-importable `.txt`
snapshots under
`data/provenance/maintenance/runtime_portability/legacy_sources/`. Historical
scientific identities continue to describe the executions already completed.
The current resolver bytes instead belong to the separate portable-runtime
identity recorded in the portability decision. The snapshots are provenance
only and are never imported or executed.

## Rebuilding

`workflows/inputs/build_runtime_derivatives.py` deterministically rebuilds and
checks the compact owners when the three complete processed sources are
available locally. Full acquisition and reprocessing therefore require those
sources to be obtained separately. Ordinary frozen runtime resolution and
final-validation input loading do not.

## Stage 1 residual owner

The omitted full Stage 1 historical market panel remains the provenance source
for the accepted coefficients. Clean-checkout runtime use instead loads
`data/model_inputs/calibration/stage1_residual_source.csv`. This derivative
contains only timestamp, contiguous run ownership and exact hexadecimal float
values needed to reproduce the accepted centred residual sequence and its
24-hour blocks. It preserves 28,859 residuals and 25,017 blocks without
rounding or interpolation.

Calibration-only code that genuinely needs historical event rows requests the
full source explicitly and fails clearly when it is absent. Ordinary frozen
runtime use does not. The broader distinction is documented in the
[submission reproducibility boundary](submission_reproducibility_boundary.md).
