# Repository architecture

## Purpose

The repository implements an interpretable agent-based model of DAI stability
under collateral-price stress. It separates economic mechanics, empirical
inputs, calibration, experiment orchestration and reproducibility records.
The model is intentionally narrower than the full Maker protocol.

## Authoritative package

The installable Python package is `src/dai_sim/`:

| Package | Responsibility |
| --- | --- |
| `model/` | Vault, collateral, price, liquidation, confidence, DAI-market and simulation mechanics |
| `inputs/` | Configuration and empirical runtime-input adapters |
| `calibration/` | Statistical estimation, reviews and adoption decisions |
| `experiments/` | Scenario definitions, runners, summaries and plots |
| `common/` | Shared repository-path infrastructure |

Compatibility modules remain temporarily under flat `src/` paths. They
forward to `dai_sim` and are not authoritative implementations.

The main dependency direction is:

```text
experiments
    -> inputs
    -> model
calibration
    -> processed data and provenance
    -> candidate parameters
```

Economic model modules do not depend on acquisition workflows.

## Empirical domains

Empirical material is organised by Maker-facing domain:

```text
data/<domain>/{raw,processed,model_inputs,provenance}/
workflows/<domain>/
sql/<domain>/{templates,generated}/
```

The domains are `market`, `gas`, `vaults`, `liquidations` and `protocol`.
Aligned market–gas environment blocks are market-owned because their row
identity is defined by the joint sampling block. Liquidation transaction gas
is liquidation-owned because the observation unit is a liquidation
transaction.

## Configuration

Complete user-facing profiles are:

- `config/profiles/legacy.yaml`;
- `config/profiles/empirical.yaml`;
- `config/profiles/empirical_stress.yaml`; and
- `config/profiles/empirical_integrated_eth.yaml`, an additive, opt-in
  integration-validation profile which is never selected implicitly.

Partial overrides live under `config/sensitivities/`. The explicit dormant
persistent-confidence scenario registry also lives there; it is an
experiment-design owner and is not merged into a complete profile by default.
Its activation and provenance contract is documented in
[`confidence_scenarios.md`](../experiments/confidence_scenarios.md). Protocol
mappings and fixed protocol settings live under `config/protocol/`.
Established experiments remain defined in Python rather than in separate
experiment configuration files.

Compact integration-validation evidence is owned by
`data/provenance/validation/`; detailed validation runs remain ignored under
`outputs/diagnostics/validation/`.

## Workflows and SQL

Acquisition, processing, reconstruction, model-input construction,
calibration and validation entry points live under `workflows/`. Historical
diagnostic and repair tools are bounded under
`workflows/maintenance/archive/`.

Hand-maintained SQL lives in `sql/<domain>/templates/`. Executed historical or
deterministically generated SQL lives in `sql/<domain>/generated/`, with
historical instances under `generated/history/` where appropriate.

## Behavioural compatibility

The legacy ETH-only path remains the default. Multi-collateral inputs are
normalised into collateral-specific price mappings and long-format
collateral-level outputs, while established system-level result columns remain
available. Compatibility shims are temporary migration aids and must contain
no business logic.

## Further reading

- [Model mechanics](../model/README.md)
- [Repository guide](repository_guide.md)
- [Data acquisition](../data/acquisition.md)
- [Regression validation](../validation/regression.md)
- [Restructuring specification](../repository_restructuring_specification.md)
