# Full-suite failure resolution

## Purpose and boundary

This maintenance pass resolves the 30 inherited test failures observed at
commit `70510e2d695f381c9479967170a5aaf6c7e58fa8` without reconstructing ignored
diagnostics or changing scientific evidence. The original run reported 1,344
passes, one documented skip and 30 failures. Its binary dirty-tree baseline is
preserved under the ignored `outputs/maintenance/failure_resolution_baseline/`
directory; the baseline patch has SHA-256
`713b4dbec0b1929c574d6e020223c4082f905366ed4da43f119161b5bcb51598`.

No calibration, simulation, held-out validation, parameter adoption or
production configuration was run or changed. Tests now recover scientific
contracts from tracked compact evidence, frozen inputs and deterministic
temporary test data.

## Original failure inventory

| Root cause | Original failing tests | Resolution | Scientific impact |
| --- | ---: | --- | --- |
| Missing checksum-bound documentation metadata | 6 | Restore three exact small files and retire obsolete chronology/archive expectations | None |
| Missing generated diagnostics or run context | 11 | Validate registered compact artefacts; create the resume shard in a temporary test directory | None |
| Factorial evidence dimension exception | 1 | Replace a historical worker-directory count with a semantic compact-evidence contract | None |
| Active documentation hierarchy and links | 3 | Validate only declared active categories and repair active semantic links | None |
| Obsolete SQL migration-map dependency | 9 | Validate the current content-addressed SQL inventory and the Stage 1 content multiset | None |

The exact original node identifiers were:

1. `tests/calibration/test_adoption.py::test_generated_outputs_are_deterministic`
2. `tests/calibration/test_keeper_execution.py::test_preregistration_is_result_blind_and_excludes_validation`
3. `tests/calibration/test_keeper_execution.py::test_preregistration_snapshot_is_immutable`
4. `tests/calibration/test_keeper_execution.py::test_scientific_identity_changes_with_design_not_results`
5. `tests/calibration/test_keeper_execution.py::test_full_panel_reconciles_system_and_excludes_usdc_svb`
6. `tests/calibration/test_keeper_execution.py::test_capacity_hierarchy_and_composition_are_reported`
7. `tests/calibration/test_keeper_execution.py::test_profit_hurdle_uses_clean_calibration_opportunities_only`
8. `tests/calibration/test_oracle_delay.py::test_repository_source_inventory_supports_only_tier_four`
9. `tests/calibration/test_simulated_moments_diagnostics.py::test_completed_estimator_audit_preserves_negative_eligibility`
10. `tests/calibration/test_structural_factorial.py::test_reused_cells_reproduce_committed_streams`
11. `tests/calibration/test_structural_factorial.py::test_factorial_input_validation_passes`
12. `tests/calibration/test_structural_factorial.py::test_completed_precision_and_factorial_evidence_validate`
13. `tests/calibration/test_structural_incompatibility.py::test_input_validation_reuses_exact_completed_baseline`
14. `tests/calibration/test_structural_incompatibility.py::test_partial_event_shard_requires_explicit_resume`
15. `tests/integration/test_documentation_hierarchy.py::test_every_populated_documentation_category_has_real_content`
16. `tests/integration/test_documentation_hierarchy.py::test_phase_and_tranche_reports_are_archived`
17. `tests/integration/test_documentation_hierarchy.py::test_document_migration_ledger_covers_every_moved_source`
18. `tests/integration/test_documentation_hierarchy.py::test_acquisition_plan_is_preserved_byte_for_byte`
19. `tests/integration/test_documentation_journeys.py::test_regression_journey`
20. `tests/integration/test_documentation_links.py::test_all_local_markdown_links_and_anchors_resolve`
21. `tests/integration/test_sql_hierarchy.py::test_sql_inventory_maps_once_to_unique_targets`
22. `tests/integration/test_sql_hierarchy.py::test_template_and_generated_storage_matches_approved_map`
23. `tests/integration/test_sql_hierarchy.py::test_obsolete_sql_paths_are_absent`
24. `tests/integration/test_sql_hierarchy.py::test_workflows_and_wrappers_have_no_obsolete_sql_literals`
25. `tests/integration/test_sql_integrity.py::test_sql_classification_and_content_match_stage_one_baseline`
26. `tests/integration/test_sql_integrity.py::test_sql_sizes_match_stage_one_tracked_inventory`
27. `tests/integration/test_sql_integrity.py::test_active_metadata_uses_current_sql_paths`
28. `tests/workflows/test_oracle_delay.py::test_non_host_dependent_payloads_reconstruct_byte_identically`
29. `tests/workflows/test_oracle_delay.py::test_isolated_freeze_is_atomic_and_non_operational`
30. `tests/workflows/test_oracle_delay.py::test_payload_construction_does_not_use_network`

## Factorial evidence audit

The audit covered the structural-factorial specification, registry, cell,
effect and interaction tables, decision, reproducibility record, precision
specification and audit, and the linked partial-identification evidence. The
full row-and-schema inventory is retained in the ignored
`factorial_dimension_audit.tsv` baseline artefact.

| Evidence | Rows | Columns | Registered dimensions |
| --- | ---: | ---: | --- |
| Factorial cells | 640 | 34 | 16 candidates × 8 cells × 5 moments |
| Factorial effects | 560 | 17 | 16 candidates × 7 effects × 5 moments |
| Factorial interactions | 320 | 20 | 16 candidates × 4 interaction cells × 5 moments |
| Precision audit | 2,800 | 23 | 16 candidates × 7 effects × 5 moments × 5 prefixes |

All artefacts agree on 74 events, three factors, eight factorial cells, five
moments and 128 registered replications. Shared candidate, moment, cell,
effect, stream and source identities reconcile exactly. The mismatch is
therefore classified `missing_runtime_context_only`: the old validation path
counted 64 ignored worker directories, although the tracked reproducibility
record already contains the 64 checkpoint identities.

The replacement validator checks each design against its own specification
and checks all shared semantic identifiers directly. It does not require raw
matrices with scientifically different roles to have the same shape. The
factorial identity remains
`4558b97de3c092b8cec70b9117407333527f517559b7126fa0428c5e9059ad00`,
the precision identity remains
`107c5698528ad433371a7d7f49ffde533691c30c032b92edf47b1cf5611cac52`,
and the registered conclusion remains
`factorial_interactions_reveal_tradeoffs`. No cell or persistent-confidence
parameter is selected.

## Diagnostic independence

| Former dependency | Former purpose | Tracked replacement | SHA-256 or validation boundary | Row-level coverage |
| --- | --- | --- | --- | --- |
| Vault liquidatable-share hourly diagnostic | Keeper source boundary and composition | Keeper specification, decision, registry and hourly panel summary | Registry `58c5754ed95dead1ad283a7961fb0588496804a94f58ddb0e196a57601ee1e1b`; summary `d9fc66be7350683ed5249e0eaeeed6eba3e47fe47f64851251bc21f27221f30b` | Compact hourly aggregates retained |
| Liquidation transaction-gas diagnostic | Positive-hurdle evidence | Keeper specification, decision, reproducibility and profit-hurdle table | Specification `5b0ac9d1372dd1306f8dea9490f5acc3ab80e9044f89de059f069acf2789ba7a`; decision `5a2ee0ac6b46a13bfa74c171fd2d399742813b1f3b406fea2b2f922887e4a289` | Registered clean-source summaries retained |
| Search cache manifest | Negative simulated-moments eligibility | Monte Carlo estimator audit | `4ca2992ffc789de6ed33ffb159d876358c60e0532e6db7ab5789544ee1be4009` | Candidate eligibility counts retained |
| Factorial precision `run_context.json` | Completed stream and shape metadata | Factorial specification and reproducibility record | `a6c7c809a7d9e1a7c5ad3c82f63cdee90936fd5a1eadbf725b0bbc86a82369da`; `ba1bc543cb935caca81fb27134cc665eca40be2414c7968fa9853d336b3b3988` | All compact cell, effect, interaction and precision rows checked |
| Partial-identification `run_context.json` | Baseline ownership and resume state | Partial-identification specification and reproducibility record | `347e47bc4c36bf7804320f823abf728096256fab1bc2706fefd0f2a66552f82c`; `3a8533aecc0bb5eb67aca1c00607d58e4f603902a767925b1983917badb452da` | Historical result is validated compactly; resume behaviour uses a deterministic temporary shard |

`tests/evidence_contracts.py` owns the non-operational semantic validators.
`tests/integration/test_diagnostic_independence.py` denies reads under
`outputs/diagnostics/` while validating keeper, estimator, factorial,
partial-identification and oracle-delay source contracts.

## Retained metadata and documentation hierarchy

Three small files were recoverable byte for byte from Git and remain necessary:

| File | Reason retained | SHA-256 |
| --- | --- | --- |
| `docs/archive/historical_plans/DATA_ACQUISITION_PLAN.md` | Checksum-bound acquisition source and active historical target | `05587f17600f148d90cc26df4f281258d299188dad8dd53d2ab00f351863ee60` |
| `docs/repository_restructuring_baseline_manifest.json` | Frozen oracle-delay source-inventory candidate and Stage 1 SQL content record | `cae567cee25a93779fc838df4ac0a238bb407d308437a4f27c1fb521bd5e92b1` |
| `docs/repository_restructuring_baseline.md` | Active regression and project-status target | `18e26b3f604b10aebf23c6034115ff5a699d3a4274d99b28b94709ac0f8ab8fe` |

The chronology report corpus and migration-ledger assertions were development
history rather than current scientific invariants. Active documentation now
requires only the overview, model, calibration, experiments, data and
validation categories. Active links resolve to semantic owners; an archive is
not required to be populated merely to preserve an earlier migration layout.
The acquisition plan is the one retained historical exception.

## SQL hierarchy

The deleted restructuring path map is classified as obsolete maintenance
scaffolding and is not restored. Current SQL validation uses Option B: a
deterministic content-addressed inventory of the live domain hierarchy.

The current inventory contains 118 files across `gas`, `liquidations`,
`market`, `protocol` and `vaults`: 15 templates and 103 generated historical
queries. Its path-and-content inventory SHA-256 is
`74789454e55f5d2f68e16cd8422b8ba797a47388712ac1c9b535010e49a5e554`.
The 117 files inherited from the Stage 1 baseline are additionally validated
as a checksum-and-size multiset, preserving exact content through semantic
path migration. The one post-restructuring market template is registered
separately. Tests also require canonical workflow defaults, valid SQL literals,
no top-level SQL files and no legacy top-level Dune SQL path prefix.

## Tests changed and invariants retained

- `tests/calibration/test_structural_factorial.py`: semantic factorial and
  completed-stream validation.
- `tests/calibration/test_structural_incompatibility.py`: compact baseline
  validation and temporary-shard resume guard.
- `tests/calibration/test_simulated_moments_diagnostics.py`: registered
  negative-eligibility audit.
- `tests/calibration/test_keeper_execution.py`: registered source boundary,
  identity, hierarchy, composition and hurdle evidence.
- `tests/integration/test_documentation_hierarchy.py`: current semantic
  taxonomy and canonical method owners.
- `tests/integration/test_documentation_links.py`: all active links and anchors.
- `tests/integration/test_sql_hierarchy.py`: deterministic current inventory,
  semantic placement and workflow path resolution.
- `tests/integration/test_sql_integrity.py`: exact Stage 1 content preservation
  independent of the retired migration map.
- `tests/integration/test_diagnostic_independence.py`: explicit ignored-output
  denial across the repaired scientific contracts.
- `tests/integration/test_test_collection_integrity.py` and
  `tests/integration/test_test_hierarchy.py`: register that single new test as
  an exact post-restructuring addition while preserving the 420-case historical
  collection and decorator digests.

No inherited failure was skipped or marked as an expected failure. Retired
development-history assertions were replaced with active structural
invariants; substantive scientific coverage was not reduced.

## Final validation status

The focused factorial, confidence, keeper, oracle-delay, documentation, SQL
and adoption suites pass. The ordinary full suite and a second full suite with
`outputs/diagnostics/` absent each collected 1,376 cases and completed with
1,375 passes, one pre-existing documented skip and no failures. The additional
case is the diagnostic-independence regression test; the historical 420-case
collection digest and all existing logical cases remain unchanged.

Compilation of `src`, `workflows` and `tests` succeeds. Scoped Ruff and
`git diff --check` pass. A before-and-after comparison covers 249 registered
scientific evidence, model-input and configuration files, with zero changed or
missing files. The security scan found no credential, authenticated URL,
machine-specific path or temporary-host-path addition in the maintenance
changes.
