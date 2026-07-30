# Experiment infrastructure maintenance

## Purpose and classification

This maintenance pass repairs two operational defects exposed by the completed
constrained-liquidation ETH-recovery experiment. It is classified as
`operational_infrastructure`, not `scientific_model`. Treatment definitions,
metrics, parameters, seeds, profiles, checkpoints, results and production
defaults are unchanged.

The completed experiment remains owned by scientific-code identity
`17ace2ebe8a57e277c0bef0cedcc92956be02920991c597f20c6c8ceeb81ab08`
and experiment identity
`6cfbd19384fc95fe8b06de74704d0b2a76638722b100242e0bc87a9ee3e05acc`.
Operational maintenance does not create a new scientific identity.

Before maintenance, the identity helper rehashed the user-facing workflow
file and compared the live Git `HEAD` with the pre-registration parent. That
would incorrectly re-identify a completed experiment after any operational
workflow commit. The completed study now returns its registered scientific
owner explicitly, while preflight recomputes the treatment identity and
requires it to match the registered experiment identity. This freezes the
historical scientific owner without weakening treatment, profile, seed or
evidence checks.

## Reconstruction CLI defect

The public `reconstruct-evidence` branch supplied `design` positionally even
though the authoritative `write_evidence` API declares every argument
keyword-only. Python therefore raised `TypeError` before evidence construction.
The repair changes only the invocation boundary to `design=design`; the
authoritative function signature, payload construction, serialisation,
checksums, benchmark policy and manifest semantics are unchanged.

Regression coverage exercises the real CLI dispatch with a keyword-only test
double, rejects invalid operations clearly and checks that no simulation
dispatch is reached. The public command is also run twice in isolated
tracked-source copies containing the existing checkpoints. Non-host-dependent
artefacts must reproduce byte-for-byte; the existing host-dependent benchmark
is passed through under its registered policy.

## Concurrent profile-resolution defect

The semantic profile loaders previously stripped downstream sections, wrote
the remainder to a predictable sibling path ending in
`.base_for_validation.yaml`, loaded it and then unlinked it. Every process
resolving the same profile therefore owned the same mutable pathname. In the
pre-fix four-worker stress reproduction, 9 of 100 profile resolutions failed.
The observed traceback showed one worker deleting
`config/profiles/empirical_integrated_eth.base_for_validation.yaml` while
another worker attempted to hash it.

The temporary file was unnecessary. The base loader already accepts the full
validated semantic profile and ignores downstream sections after validating
their keys. Tranche B now validates the original immutable profile directly;
Tranches C and D pass the original profile and ordered sensitivities to the
next loader. No temporary profile is created, shared, replaced or deleted.

## Concurrency guarantees

The repaired path provides the following guarantees:

1. every worker reads the same tracked profile bytes;
2. no worker can observe a partially written validation profile;
3. no worker deletes profile state;
4. there is no temporary-resource collision or cleanup ownership ambiguity;
5. resolved configuration content is deterministic;
6. scientific seeds and cell identifiers are independent of process identity;
7. resolved owner paths remain repository-relative;
8. no hostname, process identifier or temporary path enters metadata; and
9. a failed resolution cannot corrupt shared profile state.

The regression stress uses 25 batches' worth of work, four spawned workers and
100 total integrated-plus-generic profile resolutions. Serial and parallel
payload and profile checksums must agree. A profile-only worker smoke verifies
that the registered cell order, seed registry and 128 checkpoints are
unchanged and that no scientific result is produced.

## Evidence preservation

Before the patch, all 162 protected tracked evidence, profile, sensitivity and
runtime-input files were hashed. The complete manifest-of-hashes SHA-256 was
`d2f0ff080b4383af33c0d56a39aa889a440678757faa52636ef423469ba32919`.
The ten constrained-recovery compact artefacts retain their registered
checksums, including specification SHA-256
`4016d213eed7cde1262af2cb7cc2318bcb27efd282f35669cdf8f8cb12d0ab70`.
The experiment manifest is not rewritten by this maintenance pass.

The corrected reconstruction command is validated only against isolated
comparison copies. Comparison files are not registered or committed.

## Checkpoint preservation

The registered checkpoint directory contains 128 JSON files totalling
11,991,680 bytes. Its ordered full-file manifest SHA-256 is
`eb4c768304e4004837538be338143a9ae7b99cfaae7964d331a44c25842f5f07`.
Tests and manual audits read these files but do not rewrite them. No checkpoint
is added, removed, duplicated or orphaned.

## Test design

Focused tests cover:

- the public keyword-only CLI boundary and invalid arguments;
- repeatable byte-level evidence reconstruction;
- the immutable registered experiment identity;
- absence of shared temporary profile materialisation;
- repeatable serial profile resolution;
- 100 resolutions across four spawned workers;
- repository-relative, process-independent resolved metadata; and
- preservation of cell identities, seeds and checkpoints during profile-only
  worker startup.

The full suite, compilation and diff checks remain cumulative gates. No
720-hour simulation, constrained-recovery replication, multi-collateral
simulation or final-validation simulation is run.

## Validation outcome

- The pre-fix public CLI failed with the expected keyword-only `TypeError`.
- The pre-fix four-worker reproduction completed 91 of 100 resolutions and
  failed nine with `FileNotFoundError` at the shared validation path.
- The corrected public CLI ran twice in an isolated tracked-source copy,
  used the existing 128 checkpoints, returned the registered experiment
  identity and reproduced all ten artefacts identically.
- The spawned four-worker regression passed repeatedly. Each execution
  performed 100 resolutions, followed by an intentional failed resolution
  and a successful recovery resolution from the same worker pool.
- The focused maintenance and configuration suite passed 116 tests.
- The complete suite passed 938 tests with no failure, skip or collection
  error, exceeding the committed 930-test baseline by eight tests.
- `python -m compileall src workflows tests` and `git diff --check` passed.
- All 162 protected tracked files, 128 checkpoints and 29 established
  Experiments 1–5 output files matched their pre-patch hashes.
- Repository disk usage increased by approximately 68 KiB from the baseline
  audit; no permanent diagnostic output or new checkpoint set was created.

## Environmental boundary

The ordinary sandbox denies the semaphore capability used by
`ProcessPoolExecutor` on this host. The process-level stress is therefore run
in the authorised supported execution context. This is an environmental
restriction distinct from the fixed profile-loader race. The spawned-worker
test passes where process primitives are available and skips only with the
precise semaphore-denial reason otherwise.

## Production boundary

The maintenance changes only previously failing valid infrastructure
operations. It does not alter the legacy, empirical, empirical-stress or
integrated profile bytes; production-default selection; keeper capacity;
confidence, oracle or liquidation settings; experiment definitions; or seed
registries.

## Next scientific stage

> Freeze final multi-collateral empirical inputs and validate the
> shared-capacity multi-collateral integration contract.

No multi-collateral or final-validation stage is marked complete here.
