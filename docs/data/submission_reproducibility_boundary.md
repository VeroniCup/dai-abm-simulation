# Submission reproducibility boundary

## Purpose

The code submission separates historical scientific reconstruction from the
portable evidence needed to inspect, test and run the frozen model. Historical
experiments used complete processed sources and detailed checkpoints. Their
identities, decisions and compact evidence remain authoritative and unchanged,
but the large source and checkpoint trees are not bundled in the submission.

The second boundary is classified as `portable_submission_evidence_v1`. It is
distinct from the first portable-runtime identity and from every calibration,
experiment and validation identity.

## Submitted boundary

The submitted repository contains:

- exact frozen runtime inputs;
- an exact 28,859-row derivative of the accepted Stage 1 centred residual
  sequence and its 25,017 admissible 24-hour blocks;
- the frozen seven-candidate oracle-delay inventory, including every exclusion
  reason and the zero eligible observation and interval counts;
- compact calibration, experiment and validation evidence;
- ten historical reconstruction contracts recording identities, specifications,
  decisions, replication counts and historical checkpoint audits;
- deterministic temporary fixtures for checkpoint and resume code-path tests.

Ordinary tests validate scientific contracts from tracked compact evidence.
They do not rebuild a historical conclusion from omitted worker checkpoints or
raw source files.

The submission additionally carries all 118 tracked SQL files, the active
semantic documentation selected by the submission manifests and the external
historical-artefact verifier. Every submitted path is listed in a generated
content manifest with its byte count, SHA-256 checksum and executable status.
The exact non-scientific bundle identity is stored in the development
repository's portability record rather than inside the identity-bearing
payload, avoiding a self-referential checksum.

## Separately retained material

Full historical checkpoint reconstruction requires the separately retained
experiment and validation artefact archive. Raw oracle-source re-audit requires
the separately retained candidate files. The non-default workflow
`workflows/verification/verify_external_artifacts.py` accepts an
explicit external root and verifies it without mutation, download or network
fallback.

The code archive alone therefore does not claim to replay every historical
simulation. This is an explicit submission exclusion, not a replacement of a
scientific identity or a reduction in the frozen evidence standard.

Generated reporting assets, diagnostics, full processed datasets and detailed
checkpoint trees are also excluded. `FINAL.md` is intentionally absent because
the completed roadmap was retired. The archive does not claim to rerun every
historical experiment or reproduce every generated dissertation asset.

## Scientific neutrality

This migration changes data and test ownership only. It changes no coefficient,
residual, experiment result, validation classification, scenario, registry or
production default. Historical source checksums remain recorded so that an
optional full-source audit can be performed when those sources are supplied.
