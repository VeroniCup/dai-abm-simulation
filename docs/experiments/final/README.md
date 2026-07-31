# Final dissertation experiment programme

## Purpose and boundary

This directory owns the pre-registered final dissertation experiment
programme. It is separate from the protected historical runners and the
completed ETH-only mechanism studies. The programme contains 43 core cells
and 5,504 planned simulations, each with 128 replications.
[Experiment A](idiosyncratic_diversification.md) is complete from its original
128 authoritative checkpoints and 1,024 simulations.
[Experiment B](correlated_stress.md) is also complete from 128 authoritative
checkpoints and 1,024 simulations.
[Experiment C](stable_collateral_tradeoff.md) is complete from 128
authoritative checkpoints and 1,536 simulations.
[Experiment D](shared_keeper_capacity.md) is complete from 128 authoritative
checkpoints and 1,152 simulations. Experiment E remains unexecuted and
blocked pending the result-independent oracle-delay freeze.

The H4 evidence synthesis is a reporting programme rather than another core
simulation matrix. It remains pending and contributes no additional cell or
simulation to the totals above.

## Dissertation research questions

### RQ1

> How do collateral-price shocks propagate through vault collateralisation,
> liquidation eligibility, keeper execution and DAI price adjustment in the
> ETH-only core model?

### RQ2

> How do gas costs, keeper participation, liquidation capacity and oracle
> delay affect liquidation completion, bad debt and DAI peg recovery?

### RQ3

> Which collateral-recovery and behavioural assumptions materially affect the
> speed and reliability of peg restoration after stress?

### RQ4

> Under what collateral compositions and shock structures does
> multi-collateral DAI become more resilient than an ETH-only system, and when
> does diversification instead transmit or concentrate risk?

## Dissertation hypotheses

### H1 — Liquidation frictions

> Stronger liquidation frictions are expected to increase unresolved debt,
> bad debt and the magnitude or duration of negative peg deviations.

### H2 — Oracle delay

> Oracle delay is expected to widen the mismatch between market conditions
> and protocol action, especially after rapid collateral-price shocks.

### H3 — Diversification and contagion

> Multi-collateral diversification is expected to reduce system losses under
> isolated collateral-specific shocks, but its benefits should diminish under
> correlated stress and may reverse when a collateral intended to provide
> stability experiences its own depeg or liquidity impairment.

### H4 — Recovery and behavioural stabilisation

> Recovery is expected to depend jointly on collateral-price rebound,
> liquidation resolution and behavioural stabilisation, with unresolved
> backlog limiting the effect of otherwise favourable recovery conditions.

These are the only four dissertation hypotheses. Historical labels such as
H4a–H4c and H5a–H5d belong to the completed mechanism studies that originally
defined them; they are not additional dissertation hypotheses.

## Registered programme

| Programme component | Core cells | Replications | Planned simulations | Status | Principal role |
| --- | ---: | ---: | ---: | --- | --- |
| Experiment A — idiosyncratic diversification | 8 | 128 | 1,024 | `completed` | RQ4 and H3 under isolated collateral-specific shocks |
| Experiment B — correlated stress | 8 | 128 | 1,024 | `completed` | RQ4 and H3 across the two registered joint-stress bundles |
| Experiment C — stable-collateral trade-off | 12 | 128 | 1,536 | `completed` | RQ4 and H3 under stable-proxy depeg and joint stress |
| Experiment D — shared keeper capacity | 9 | 128 | 1,152 | `completed` | RQ2 and H1, with cross-collateral implications for RQ4 |
| Experiment E — oracle delay | 6 | 128 | 768 | `preregistered_blocked_pending_oracle_delay_freeze` | RQ2 and H2 |
| H4 evidence synthesis | 0 | — | 0 | `pending_evidence_synthesis` | RQ3 and H4, using pre-registered evidence rather than a new core matrix |
| **Total** | **43** |  | **5,504** |  |  |

Experiment E has no numerical oracle-delay treatments yet. Its blocked status
must remain until those values are frozen through a result-independent
specification. No placeholder values may be inferred from earlier studies.

Experiment A reports A1 `supported`, A2
`exposure_gradient_consistent`, A3 `shock_localisation_valid` and overall
`H3_idiosyncratic_diversification_supported`. Its solvency–peg relationship
is `solvency_improves_peg_unchanged`. The compact evidence was reconstructed
from the original checkpoints without rerunning a simulation. A
post-execution NumPy-to-JSON repair, classified
`evidence_serialization_infrastructure`, changed only the serialisation
boundary and did not change any scientific calculation or decision.

Experiment B reports B1 `supported`, B2
`correlation_deterioration_present`, B3 `transmission_mixed` and overall
`H3_correlation_deterioration_supported`. Every diversified portfolio is
classified `weakens_but_remains`, with no reversal. The registered
peg–solvency relationship is `solvency_deteriorates_peg_unchanged`. B2 is a
comparison of frozen bundled treatments—not a pure correlation coefficient
intervention—because severity, recovery and gas ownership also differ. The
post-execution `evidence_row_ordering_infrastructure` repair changed compact
row order only; it did not change checkpoints, values or decisions.

Experiment C reports C1 `supported`, C2
`depeg_exposure_gradient_inconsistent`, C3 `contagion_mixed` and overall
`H3_stable_tradeoff_partially_supported`. Both stable-backed portfolios are
`protection_without_material_depeg_cost`; this does not rank or select them.
The stable family and its depeg paths remain counterfactual, and USDC/SVB was
not used. The registered peg–solvency relationship is
`solvency_improves_peg_unchanged`.

Experiment D reports D1 `not_supported`, D2
`shared_capacity_transmission_mixed`, D3 `peg_unchanged` and overall
`H1_no_clear_shared_capacity_effect`. Only the empirical-crypto anchor shows
a clear, small threshold backlog-area effect; the stable-supported effect is
uncertain and the stable-heavy treatments do not bind. The registered
peg–solvency relationship is `neither_materially_changes`. Capacities 14, 26
and 45 remain partially identified sensitivity coordinates: none is ranked,
selected or runtime adopted.

## Sequencing and no-retuning rule

The programme is hierarchical. Completion of Experiment D does not authorise
Experiment E, the H4 synthesis, robustness layers or held-out validation.
The next boundary is the result-independent oracle-delay freeze required
before Experiment E. Each later component must retain its registered design
and receive its own execution authorisation.

Model mechanisms, parameters, empirical input pools, portfolio definitions,
shock definitions, keeper settings, confidence scenarios and oracle-delay
values must not be retuned in response to final-programme results. Held-out
validation is evaluative only. A miss, null result or unfavourable contrast
must be reported rather than repaired by changing the frozen design.
