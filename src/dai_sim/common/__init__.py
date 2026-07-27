"""Shared infrastructure with an established cross-domain responsibility."""

from .paths import (
    RepositoryRootNotFoundError,
    find_repository_root,
    repository_path,
)

__all__ = [
    "RepositoryRootNotFoundError",
    "find_repository_root",
    "repository_path",
]
