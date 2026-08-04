"""Shared, test-only access to authoritative repository-path discovery."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from dai_sim.common.paths import find_repository_root


REPOSITORY_ROOT = find_repository_root(__file__)


def _gitignore_rule_matches(
    pattern: str,
    relative_path: str,
    *,
    directory_descendants: bool,
) -> bool:
    """Apply the repository's simple, rooted ignore rules without Git."""
    pattern = pattern.lstrip("/")
    path = PurePosixPath(relative_path).as_posix()
    ancestors = [
        "/".join(PurePosixPath(path).parts[:index])
        for index in range(1, len(PurePosixPath(path).parts) + 1)
    ]
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return any(fnmatchcase(candidate, prefix) for candidate in ancestors)
    if pattern.endswith("/"):
        prefix = pattern.rstrip("/")
        if not directory_descendants:
            return fnmatchcase(path, prefix)
        return any(fnmatchcase(candidate, prefix) for candidate in ancestors)
    if "/" not in pattern:
        return any(fnmatchcase(part, pattern) for part in PurePosixPath(path).parts)
    return any(fnmatchcase(candidate, pattern) for candidate in ancestors)


def is_ignored(relative_path: str) -> bool:
    """Return Git-ignore policy deterministically, including in Git-free bundles."""
    ignored = False
    for raw in (REPOSITORY_ROOT / ".gitignore").read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pattern = line[1:] if negated else line
        if _gitignore_rule_matches(
            pattern,
            relative_path,
            directory_descendants=not negated,
        ):
            ignored = not negated
    return ignored
