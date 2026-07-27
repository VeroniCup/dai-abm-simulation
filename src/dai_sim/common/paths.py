"""Safe, side-effect-free repository path discovery and resolution."""

from __future__ import annotations

from pathlib import Path


_REPOSITORY_SENTINELS = ("pyproject.toml", "AGENTS.md", "src")


class RepositoryRootNotFoundError(RuntimeError):
    """Raised when no repository root exists above the requested start."""


def _normalise_existing_start(start: Path | str | None) -> Path:
    """Return an existing, resolved directory from which discovery can begin."""
    candidate = Path.cwd() if start is None else Path(start)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"Repository discovery start does not exist: {candidate}"
        ) from error

    return resolved.parent if resolved.is_file() else resolved


def _has_repository_sentinels(candidate: Path) -> bool:
    """Return whether a directory satisfies the conservative root contract."""
    return (
        (candidate / "pyproject.toml").is_file()
        and (candidate / "AGENTS.md").is_file()
        and (candidate / "src").is_dir()
    )


def find_repository_root(start: Path | str | None = None) -> Path:
    """Find the repository root at or above an explicit starting location.

    Parameters
    ----------
    start:
        Existing file or directory from which to search. Relative paths are
        resolved from the current working directory. If omitted, discovery
        starts from the current working directory.

    Returns
    -------
    pathlib.Path
        The fully resolved repository root.

    Raises
    ------
    FileNotFoundError
        If an explicit starting path does not exist.
    RepositoryRootNotFoundError
        If no ancestor satisfies the repository sentinel contract.
    """
    search_directory = _normalise_existing_start(start)

    for candidate in (search_directory, *search_directory.parents):
        if _has_repository_sentinels(candidate):
            return candidate

    raise RepositoryRootNotFoundError(
        "No repository root containing pyproject.toml, AGENTS.md and src/ "
        f"was found at or above: {search_directory}"
    )


def repository_path(
    *parts: str | Path,
    root: Path | str | None = None,
) -> Path:
    """Resolve a path within the repository without creating it.

    An absolute child path is accepted only when its resolved location remains
    within the discovered repository root. Relative traversal is similarly
    constrained after resolution.
    """
    repository_root = find_repository_root(root)
    target = repository_root

    for part in parts:
        child = Path(part)
        target = child if child.is_absolute() else target / child

    resolved_target = target.resolve(strict=False)
    try:
        resolved_target.relative_to(repository_root)
    except ValueError as error:
        raise ValueError(
            f"Resolved path escapes the repository root: {resolved_target}"
        ) from error

    return resolved_target
