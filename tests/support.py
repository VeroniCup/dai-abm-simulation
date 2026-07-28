"""Shared, test-only access to authoritative repository-path discovery."""

from __future__ import annotations

from dai_sim.common.paths import find_repository_root


REPOSITORY_ROOT = find_repository_root(__file__)
