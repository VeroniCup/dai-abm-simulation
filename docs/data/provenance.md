# Data provenance

## Ownership

`data/provenance/` is the cross-domain index. It contains the authoritative
data manifest and links into domain provenance. Each domain owns its query,
execution, acquisition, processing and validation records under
`data/<domain>/provenance/`.

The top-level [data entry point](../../data/README.md) provides concise
navigation. Domain raw-data READMEs describe the ignored local payloads.

## Required records

Durable provenance should identify:

- provider and source table or contract;
- exact SQL or template path and checksum;
- query and execution identifiers;
- query type and engine;
- requested and actual UTC coverage;
- row and column counts;
- file path, size and content checksum;
- acquisition or processing timestamp;
- validation status;
- units, transformations and source limitations;
- credit usage where applicable.

For chunked acquisition, the combined record links to every chunk identifier,
checksum and state. Failed or aborted attempts remain separate from successful
production costs.

## Tracked and ignored material

Tracked provenance includes the cross-domain manifest, compact runtime-input
manifests, selected source identifiers and checksums needed to identify ignored
data. Detailed result payloads, partial files, transient states, local
validation outputs and machine-specific paths remain ignored unless a durable
record is required for an irreproducible execution.

Credentials, `.env` files and Dune API keys never belong in provenance.

## Checksum classes

Four checksum classes are distinct:

1. content checksums remain stable when a file is moved unchanged;
2. path-sensitive metadata checksums change when embedded paths change;
3. generated-output checksums may include volatile metadata and need a
   substantive comparison;
4. regression checksums canonicalise model results and exclude path/runtime
   metadata.

Stage 5 established domain data-tree digests. Stage 7 established SQL content
and semantic-path digests. Historical SQL is preserved even where current
generators have evolved.

## Reverse lookup

A reader should be able to start with a model input or processed file and find:

```text
file checksum
→ domain provenance
→ source SQL/template
→ query and execution IDs
→ acquisition state and validation
```

The reverse path should also work from a query or execution identifier to the
local file that entered analysis. A query identifier does not imply that Dune
will retain the result indefinitely.

## Historical evidence

Chronological reports and plans are under
[`docs/archive/`](../../docs/archive/README.md). They preserve original paths,
costs, limitations and execution decisions. Active guides describe current
paths; archived code spans may refer to the repository layout that existed
when the work was performed.
