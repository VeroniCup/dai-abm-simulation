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
    """Raised when mechanism outputs do not use the canonical family tree."""


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
    """Return the legacy flat family root used by compatibility checks."""
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
    """Resolve the canonical family root and reject legacy-only state.

    Experiment execution never relocates output. A legacy-only tree requires
    explicit reconciliation so that a resume cannot split one scientific run
    across two authoritative directories.
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
