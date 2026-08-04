# Code-submission readiness

## Current decision

The first runtime migration is evaluated under
`portable_runtime_resolution_v2`. The complete submission boundary is
`portable_submission_evidence_v1`, with identity
`e0e58222253204ee87f39a93b0d6edd650a64e47af81b2dd7521d2bd35d7a33b`.
Its readiness decision is recorded in
`data/provenance/maintenance/submission_portability/portability_decision.json`.

The decision may be `ready_with_submission_exclusions` only after all of the
following gates pass:

- exact full-versus-compact equality with zero scientific-value differences;
- successful ordinary and detached clean-checkout test suites;
- the unchanged first-boundary focused check and the expanded 82-test
  portability check;
- unchanged historical evidence and frozen identities;
- no reads from ignored processed sources in the clean checkout;
- no network or user-home fallback.

The final archive is selected by the two manifests under `config/submission/`
and built from the current working tree. The generated
`SUBMISSION_CONTENT_MANIFEST.json` binds every submitted path, byte count,
checksum and executable bit. Its content identity is recorded outside the
payload in the submission-bundle portability record: embedding the identity in
an included document would make that document, and therefore the identity,
self-referential.

The first portability-focused contract and exact-equivalence gate remain
unchanged. The second submission boundary adds the exact Stage 1 residual
derivative, frozen oracle-source inventory ownership and ten compact historical
reconstruction contracts. Ordinary tests use deterministic temporary fixtures
for checkpoint code paths and tracked compact evidence for scientific results.

The readiness classification is `ready_with_submission_exclusions`: full
historical checkpoint reconstruction and raw oracle-source re-audit remain
optional external operations and are not claimed from the code archive alone.
The earlier ordinary and detached portability suites each passed 1,392 tests
with the same single documented skip. After adding the manifest-filtered bundle
contracts, the exact archive passes 1,407 tests with that same skip. It reads no
ignored scientific source and performs no network or user-home fallback.

## Included runtime evidence

The portable archive includes the sidecar runtime map, the existing
multi-collateral market-block pool, the 816-row final-validation derivative,
the frozen collateral registry, the resolver, deterministic rebuild workflow,
tests and maintenance provenance. The exact include and exclude policies are
in `config/submission/code_submission_include.txt` and
`config/submission/code_submission_exclude.txt`.

The archive also includes all 118 tracked SQL files: 15 templates and 103
generated historical queries. Generated SQL remains modest in size and is
required by the checksum-and-size integrity suite. Explicit include precedence
retains the external scientific-artefact verifier despite the default exclusion
of maintenance workflows.

## Excluded material

Raw and processed acquisition data, complete processed panels and generated
outputs are excluded. The three migrated processed sources account for about
92.1 MB. Their exclusion does not prevent use of the frozen simulation inputs
or held-out validation paths, but full acquisition and derivative rebuilding
require the complete sources to be supplied separately.

Detailed experiment and validation checkpoints are also excluded. Their
historical counts, identities, content-map checksums where recorded, compact
evidence owners and decisions are preserved under
`data/provenance/maintenance/submission_portability/`.

Generated reporting packages, diagnostics, processed sources and detailed
checkpoints are absent. `FINAL.md` is also intentionally excluded because the
completed roadmap was retired during the authorised submission clean-up; it is
not recreated for packaging.

## Exact filtered-bundle validation

The final classification is issued only after the filtered payload installs
offline, passes `pip check`, compiles, and passes the complete suite plus the
SQL, documentation-link, diagnostic-independence and portability-focused
checks. Archive evidence owners that historically checked Git objects may use
the checksum-bound content manifest when `.git` is absent. This is a packaging
boundary only: it neither reconstructs nor changes scientific evidence.

The verified result is 1,407 passed, one documented skip and zero failures.
The SQL, documentation-link and diagnostic-independence selection passes 21
checks; the bundle and compact-runtime selection passes 32 checks.

## Identity interpretation

Historical identities remain authoritative for the completed experiments and
validation. The portable-runtime identity describes current clean-checkout
resolution and is intentionally different from those historical source-code
identities. It is not a replacement experiment identity and provides no basis
for changing a scientific classification, parameter or default.
