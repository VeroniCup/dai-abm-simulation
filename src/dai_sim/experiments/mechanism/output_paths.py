"""Canonical output locations for mechanism experiments.

Scientific experiment identities deliberately exclude these operational paths.
Historical pre-registration configurations may therefore retain the locations
used when an experiment originally ran while current execution resolves through
this semantic owner.
"""

from __future__ import annotations

from pathlib import Path

from dai_sim.inputs.configuration import REPOSITORY_ROOT


MECHANISM_EXPERIMENT_OUTPUT_ROOT = (
    REPOSITORY_ROOT / "outputs/experiments/mechanism"
)
MECHANISM_EXPERIMENT_FAMILIES = frozenset(
    {
        "constrained_eth_recovery",
        "eth_recovery",
    }
)


class MechanismOutputMigrationRequiredError(RuntimeError):
    """Raised when only a superseded flat mechanism output tree exists."""


def canonical_mechanism_output_root(
    experiment_family: str,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> Path:
    """Return the canonical family root without touching the filesystem."""
    if experiment_family not in MECHANISM_EXPERIMENT_FAMILIES:
        raise ValueError(
            f"Unknown mechanism experiment family: {experiment_family!r}."
        )
    return (
        Path(repository_root)
        / "outputs"
        / "experiments"
        / "mechanism"
        / experiment_family
    )


def legacy_mechanism_output_root(
    experiment_family: str,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> Path:
    """Return the superseded flat family root for migration checks only."""
    if experiment_family not in MECHANISM_EXPERIMENT_FAMILIES:
        raise ValueError(
            f"Unknown mechanism experiment family: {experiment_family!r}."
        )
    return Path(repository_root) / "outputs" / "experiments" / experiment_family


def resolve_mechanism_output_root(
    experiment_family: str,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> Path:
    """Resolve a canonical family root and reject unmigrated old-only state.

    Ordinary experiment execution never relocates output.  An old-only tree
    requires an explicit, separately audited migration so that a resume cannot
    silently fork one scientific run across two authoritative directories.
    """
    canonical = canonical_mechanism_output_root(
        experiment_family,
        repository_root=repository_root,
    )
    legacy = legacy_mechanism_output_root(
        experiment_family,
        repository_root=repository_root,
    )
    if legacy.exists():
        if canonical.exists():
            raise MechanismOutputMigrationRequiredError(
                "Conflicting mechanism output trees exist at both "
                f"{legacy} and {canonical}; reconcile them explicitly before "
                "running or resuming the experiment."
            )
        raise MechanismOutputMigrationRequiredError(
            f"Mechanism output remains at the superseded path {legacy}. "
            f"Move it explicitly to {canonical} before running or resuming; "
            "automatic migration is disabled."
        )
    return canonical
