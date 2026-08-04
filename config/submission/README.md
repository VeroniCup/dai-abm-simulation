# Code-submission manifests

The include and exclude manifests define the portable dissertation code
submission. They operate on tracked files and authorised untracked,
non-ignored files in the current working tree.

Rules are interpreted as follows:

1. blank lines and lines beginning with `#` are ignored;
2. a rule ending in `/` owns the complete directory subtree;
3. glob rules use deterministic POSIX-style path matching;
4. any include match takes precedence over every exclude match;
5. symlinks are rejected;
6. every literal include path must exist;
7. unmatched include globs are reported;
8. repository-escaping and absolute paths are rejected;
9. copied file bytes and executable bits are preserved; and
10. payload paths and content-manifest records are ordered lexicographically.

`FINAL.md` is intentionally absent: the final roadmap was retired after
completion and its authorised deletion is preserved. The complete tracked SQL
hierarchy is included because generated historical queries form part of the
protected SQL integrity and reproducibility contract.

The maintenance tree is excluded by default. Exact include rules retain the
external scientific-artefact verifier, the historical maintenance workflows
required by the structural suite, and the retrieval owner. The bundle builder
itself remains a development-repository tool and is not part of the submitted
payload.

This development-only directory is excluded from the distributed archive. The
builder writes the ordered payload content manifest beside the archive rather
than inside it, so that sidecar does not participate in its own content
identity.
