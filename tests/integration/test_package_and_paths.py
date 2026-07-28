"""Tests for the Stage 2 package and repository-path infrastructure."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest
from setuptools import find_packages


from tests.support import REPOSITORY_ROOT
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import dai_sim  # noqa: E402
from dai_sim.common.paths import (  # noqa: E402
    RepositoryRootNotFoundError,
    find_repository_root,
    repository_path,
)


def _make_sentinel_root(path: Path) -> Path:
    """Create the minimum repository sentinel structure for an isolated test."""
    path.mkdir()
    (path / "pyproject.toml").touch()
    (path / "AGENTS.md").touch()
    (path / "src").mkdir()
    return path


def test_package_import_is_deliberately_empty() -> None:
    assert dai_sim.__doc__
    assert not any(
        hasattr(dai_sim, name)
        for name in ("collateral", "liquidation", "simulation", "vault")
    )


def test_import_outside_repository_has_no_filesystem_side_effect(
    tmp_path: Path,
) -> None:
    environment = {
        **os.environ,
        "PYTHONPATH": str(SRC_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    code = (
        "import sys; "
        "import dai_sim; "
        "import dai_sim.common.paths; "
        "assert not {'collateral', 'liquidation', 'simulation', 'vault'} "
        "& set(sys.modules)"
    )
    subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=tmp_path,
        env=environment,
        check=True,
    )
    assert list(tmp_path.iterdir()) == []


def test_find_repository_root_from_root_nested_directory_and_file() -> None:
    assert find_repository_root(REPOSITORY_ROOT) == REPOSITORY_ROOT
    assert find_repository_root(REPOSITORY_ROOT / "src/dai_sim/common") == REPOSITORY_ROOT
    assert find_repository_root(REPOSITORY_ROOT / "AGENTS.md") == REPOSITORY_ROOT


def test_find_repository_root_from_relative_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(REPOSITORY_ROOT)
    assert find_repository_root("src/dai_sim") == REPOSITORY_ROOT


def test_find_repository_root_fails_outside_repository(tmp_path: Path) -> None:
    with pytest.raises(RepositoryRootNotFoundError, match="No repository root"):
        find_repository_root(tmp_path)


def test_find_repository_root_rejects_nonexistent_start(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        find_repository_root(tmp_path / "missing")


@pytest.mark.parametrize("sentinel", ("pyproject.toml", "AGENTS.md", "src"))
def test_single_weak_sentinel_is_not_accepted(
    tmp_path: Path,
    sentinel: str,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    marker = candidate / sentinel
    marker.mkdir() if sentinel == "src" else marker.touch()
    with pytest.raises(RepositoryRootNotFoundError):
        find_repository_root(candidate)


def test_repository_path_resolves_normal_nested_and_missing_paths() -> None:
    assert repository_path("src") == (REPOSITORY_ROOT / "src").resolve()
    assert repository_path("src", "dai_sim", "future.py") == (
        REPOSITORY_ROOT / "src/dai_sim/future.py"
    ).resolve()
    assert not (REPOSITORY_ROOT / "src/dai_sim/future.py").exists()


def test_repository_path_uses_explicit_root(tmp_path: Path) -> None:
    root = _make_sentinel_root(tmp_path / "repository")
    assert repository_path("data", "future.csv", root=root) == (
        root / "data/future.csv"
    ).resolve()


def test_repository_path_rejects_relative_escape(tmp_path: Path) -> None:
    root = _make_sentinel_root(tmp_path / "repository")
    with pytest.raises(ValueError, match="escapes"):
        repository_path("..", "outside.csv", root=root)


def test_repository_path_rejects_outside_absolute_path(tmp_path: Path) -> None:
    root = _make_sentinel_root(tmp_path / "repository")
    with pytest.raises(ValueError, match="escapes"):
        repository_path(tmp_path / "outside.csv", root=root)


def test_repository_path_accepts_verified_inside_absolute_path(
    tmp_path: Path,
) -> None:
    root = _make_sentinel_root(tmp_path / "repository")
    inside = root / "future.csv"
    assert repository_path(inside, root=root) == inside.resolve()


def test_repository_path_does_not_create_or_change_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _make_sentinel_root(tmp_path / "repository")
    working_directory = tmp_path / "working"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)
    target = repository_path("new", "nested", "file.csv", root=root)
    assert Path.cwd() == working_directory
    assert target == (root / "new/nested/file.csv").resolve()
    assert not (root / "new").exists()


def test_pyproject_metadata_and_discovery_are_bounded() -> None:
    payload = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert payload["project"]["name"] == "dai-abm-simulation"
    assert payload["project"]["version"] == "0.1.0a0"
    assert payload["project"]["requires-python"] == ">=3.11,<3.14"
    assert payload["project"]["dynamic"] == ["dependencies"]
    assert payload["build-system"]["build-backend"] == "setuptools.build_meta"
    assert payload["tool"]["setuptools"]["package-dir"] == {"": "src"}
    discovery = payload["tool"]["setuptools"]["packages"]["find"]
    assert discovery == {"where": ["src"], "include": ["dai_sim*"]}
    assert "scripts" not in payload["project"]
    assert "pytest" not in payload.get("tool", {})
    assert sorted(find_packages(where=SRC_ROOT, include=["dai_sim*"])) == [
        "dai_sim",
        "dai_sim.calibration",
        "dai_sim.common",
        "dai_sim.experiments",
        "dai_sim.inputs",
        "dai_sim.model",
    ]
