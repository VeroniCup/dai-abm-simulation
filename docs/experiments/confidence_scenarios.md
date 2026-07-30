# Persistent-confidence scenario registry

## 1. Calibration closure

Empirical rescue of the dormant persistent-confidence formulation is closed.
The registered Sobol domain contains no empirically compatible vector, and the
objective-blind structural factorial finds interaction trade-offs rather than
a compatible structural cell. No candidate, factorial cell, parameter vector
or structural variant was selected.

Persistent confidence may therefore enter later experiments only as a
transparent, pre-specified scenario dimension. The registry described here is
an experimental design, not an estimate, posterior summary or model-selection
result. It does not reopen calibration.

## 2. Stage 1 and Stage 2

Stage 1 contains the empirically estimated ordinary below-peg and above-peg
effective responses and the accepted 24-hour moving-block residual process.
Those inputs remain fixed.

Stage 2 contains the dormant persistent-confidence state and its panic
amplification term. The four registered cases are:

1. `stage1_only`;
2. `confidence_resilient`;
3. `confidence_central`; and
4. `confidence_fragile`.

`stage1_only` keeps Stage 2 inactive and is the production default. The other
three cases are scenario assumptions for separately authorised experiments.

## 3. Authoritative coupled transform

The source domain is
[`parameter_bounds.json`](../../data/provenance/calibration/confidence/parameter_bounds.json),
identified by SHA-256
`6e1fcb4dcc3047b03bd24d290946fa532cab70412a867bc640fac8929fb4feda`.
The transform owner remains
[`simulated_moments.py`](../../src/dai_sim/calibration/simulated_moments.py).

For canonical coordinates \((u_d,u_r,u_C,u_P)\), the authoritative inverse
mapping is:

\[
\alpha_d=u_d,\qquad
\rho_r=u_r,\qquad
\alpha_r=\alpha_d\rho_r,\qquad
C_{\min}=u_C,\qquad
\kappa_P=2.75454u_P.
\]

Here \(\rho_r=\alpha_r/\alpha_d\) is conditional recovery strength relative
to the same scenario's deterioration adjustment. It is the second independent
canonical coordinate. The runtime mechanism continues to consume the derived
raw recovery adjustment \(\alpha_r\); its API is not renamed.

Retaining \(\rho_r\) preserves the registered search parameterisation and the
meaning of the original Sobol coordinates. It also avoids choosing new
raw-\(\alpha_r\) coordinates after observing calibration or factorial
evidence. The coupling between deterioration and recovery is consequently
visible rather than silently removed.

## 4. Fixed coordinates and runtime values

| Scenario | Enabled | \((u_d,u_r,u_C,u_P)\) | \(\alpha_d\) | \(\rho_r\) | \(\alpha_r\) | \(C_{\min}\) | \(\kappa_P\) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `stage1_only` | no | inactive | — | — | — | — | — |
| `confidence_resilient` | yes | \((0.25,0.75,0.75,0.25)\) | 0.25 | 0.75 | 0.1875 | 0.75 | 0.688635 |
| `confidence_central` | yes | \((0.50,0.50,0.50,0.50)\) | 0.50 | 0.50 | 0.25 | 0.50 | 1.37727 |
| `confidence_fragile` | yes | \((0.75,0.25,0.25,0.75)\) | 0.75 | 0.25 | 0.1875 | 0.25 | 2.065905 |

The values are reconstructed solely from the source domain, the unchanged
inverse transform and the fixed quartile coordinates. They do not use a Sobol
candidate identity, objective value, compatibility result, factorial cell,
interaction label, empirical-moment proximity or final-validation outcome.

## 5. Correct ordering interpretation

The independent dimensions have the registered ordering:

- deterioration: fragile \(>\) central \(>\) resilient;
- relative recovery: resilient \(>\) central \(>\) fragile;
- confidence floor: resilient \(>\) central \(>\) fragile; and
- panic amplification: fragile \(>\) central \(>\) resilient.

Raw recovery is derived, not independently quantiled. Its exact ordering is:

\[
\alpha_r^{central}=0.25
>
\alpha_r^{resilient}
=
\alpha_r^{fragile}
=0.1875.
\]

This is expected. From a common confidence state and the same open recovery
gate, central therefore recovers faster, while resilient and fragile recover
at the same raw hourly adjustment. No strict resilient-to-fragile raw recovery
ordering is claimed.

The labels describe the joint bundle. Resilient combines slower
deterioration, stronger recovery relative to deterioration, a higher floor and
weaker panic amplification. Fragile combines the reverse. They do not claim
that every raw parameter is strictly ordered.

## 6. Endpoint exclusion

The registry uses only 0.25, 0.50 and 0.75 in canonical space. Zero and one are
excluded because the original domain was deliberately broad, endpoint
combinations can create boundary artefacts, and this registry represents
interpretable behavioural regimes. Any severe endpoint sensitivity would
require its own pre-registration.

## 7. Structural formulation

Every active scenario retains:

- the production/default vault-state construction;
- the accepted 24-hour moving-block residual process;
- the full recovery gate;
- the unresolved-backlog condition;
- the active-bad-debt condition;
- the price-stability condition;
- the original equal-weight stress construction; and
- the accepted Stage 1 coefficients.

The P25 factorial vault state, zero residual intervention, backlog removal and
price-only recovery gate are not scenario options. They remain diagnostic
factorial treatments and are not production alternatives.

## 8. Configuration and activation

The sole tracked configuration owner is
[`confidence_scenarios.yaml`](../../config/sensitivities/confidence_scenarios.yaml).
Typed loading, exact Decimal derivation, validation and metadata are owned by
[`confidence_scenarios.py`](../../src/dai_sim/experiments/confidence_scenarios.py).

Experiment configuration accepts one `confidence_scenario` identifier:

- an absent field resolves to `stage1_only`;
- explicit `stage1_only` is byte-equivalent to the absent field;
- an active registered identifier enables the exact bundle;
- an unknown identifier is rejected; and
- any manual or partial Stage 2 override is rejected.

Direct low-level constructors remain available for model unit tests. No
profile, established experiment or production runner is changed, and
`confidence_central` is not an implicit default.

Every resolved run records the identifier, enabled flag, canonical
coordinates, derived runtime values, source-domain checksum, registry and
configuration checksums, structural formulation, Stage 1 and residual
checksums, `parameter_source: scenario_defined`, and
`runtime_adopted: false`.

## 9. Mechanism verification

The compact deterministic smoke joins the pure persistent-confidence update
with the coefficient-normalised market response. It uses a fixed stress
target, no residual innovation, a closed recovery gate during deterioration
and the full open gate during recovery.

It verifies:

- finite, bounded and deterministic confidence paths;
- resilient, central and fragile deterioration ordering;
- the expected common-state raw recovery ordering;
- resilient, central and fragile relative-recovery ordering;
- fragile, central and resilient panic ordering;
- derived-\(\alpha_r\) use; and
- exact equivalence of missing configuration and `stage1_only`.

It is a mechanism integration smoke, not a recovery experiment. It makes no
claim that the endogenous DAI-price path has a universal scenario ordering.

## 10. Provenance

Compact evidence is registered under
`data/provenance/experiments/confidence/`:

- `confidence_scenario_specification.json`;
- `confidence_scenario_registry.csv`;
- `confidence_scenario_reproducibility.json`; and
- `confidence_scenario_decision.json`.

The experiment-provenance manifest records their paths, sizes, checksums and
scenario-defined classification. Deterministic reconstruction writes
byte-identical JSON and CSV artefacts.

## 11. Intended use and prohibited interpretation

The separately authorised
[ETH-only recovery matrix](eth_recovery_matrix.md) compares all four cases
under the same four controlled recovery paths and paired common random
numbers. The same registry may then be used as one robustness dimension in a
separately authorised multi-collateral experiment.

No scenario represents truth. The central case is only the componentwise
midpoint of canonical coordinates; it is not an empirical mean, posterior
mean, calibrated estimate or preferred case. Resilient is not an estimated
best case, and fragile is not a statistically estimated worst case. The
registry is not ranked, none of its active scenarios is selected, and no
scenario is adopted at runtime.
