# Code-submission clean-up

## Second portability boundary

The remaining clean-checkout dependencies have explicit owners: the Stage 1
residual process uses an exact compact derivative, oracle-delay tests use the
frozen seven-candidate inventory, and completed-study tests use tracked
reconstruction contracts rather than ignored checkpoint trees. Full historical
reconstruction remains available only when a user supplies the separately
retained artefact archive.

See the [submission reproducibility boundary](../data/submission_reproducibility_boundary.md).

## Submission boundary

The code-submission manifests under `config/submission/` separate the portable
scientific runtime from local acquisition, processed evidence and generated
output. The submission includes source code, configurations, tests, semantic
workflows, SQL templates, compact model inputs and durable provenance. It
excludes raw data, processed panels, generated outputs, caches and host
metadata.

The manifest-filtered archive includes the complete tracked SQL hierarchy
(15 templates and 103 generated historical queries), because those files are
small, checksum-protected reproducibility evidence. It includes the external
scientific-artefact verifier through exact-file precedence while leaving the
bundle builder and unrelated maintenance utilities in the development
repository. `FINAL.md` remains deleted: the final roadmap was retired after
completion and is not recreated for submission.

The three formerly mandatory processed runtime sources total approximately
92.1 MB and are excluded:

- the hourly protocol-parameter panel;
- the processed hourly market-price panel;
- the combined hourly market-and-gas panel.

Their historical paths and checksums remain recorded. Runtime ownership is
provided by the frozen collateral registry, the existing tracked market-block
pool and an exact 816-row held-out derivative. Full processed sources remain
optional provenance and rebuild inputs.

## Scientific boundary

Historical experiments used and validated the complete processed sources.
They are not re-described as compact-input executions. Pre-migration resolver
bytes and scientific identities remain frozen historical provenance. The
portable runtime has its own content-addressed identity and changes no
scientific value or decision.

## Reproducibility contract

A clean checkout must install offline with dependencies already present,
compile, pass the focused runtime tests and pass the complete test suite while
the processed directories and generated `outputs/` tree are absent. Runtime
resolution must perform zero network calls and must fail on missing or corrupt
compact owners. Detailed acquisition and reprocessing remain a separate,
documented workflow requiring locally supplied full sources.

The archive contains no generated reporting package, diagnostic payload,
processed source or historical checkpoint tree. Its root content-manifest
sidecar provides a deterministic checksum boundary where Git history is
deliberately unavailable.
