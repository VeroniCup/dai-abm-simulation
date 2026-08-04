"""Tests for package discovery and repository-path infrastructure."""

from __future__ import annotations

import os
import ast
from pathlib import Path
import runpy
import subprocess
import sys
import tomllib
import yaml

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
    (path / "src/dai_sim").mkdir(parents=True)
    (path / "config").mkdir()
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


def test_find_repository_root_from_root_nested_directory_and_file(
    tmp_path: Path,
) -> None:
    assert find_repository_root(REPOSITORY_ROOT) == REPOSITORY_ROOT
    assert find_repository_root(REPOSITORY_ROOT / "src/dai_sim/common") == REPOSITORY_ROOT

    filtered = _make_sentinel_root(tmp_path / "filtered")
    nested = filtered / "src/dai_sim/nested"
    nested.mkdir()
    assert not (filtered / "AGENTS.md").exists()
    assert not (filtered / ".git").exists()
    assert not (filtered / "README.md").exists()
    assert find_repository_root(filtered) == filtered
    assert find_repository_root(nested) == filtered

    workflow_root = runpy.run_path(
        str(REPOSITORY_ROOT / "workflows/_bootstrap.py")
    )["_repository_root"]
    assert workflow_root(nested / "workflow.py") == filtered


def test_find_repository_root_from_relative_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(REPOSITORY_ROOT)
    assert find_repository_root("src/dai_sim") == REPOSITORY_ROOT


def test_find_repository_root_fails_outside_repository(tmp_path: Path) -> None:
    unrelated_parent = tmp_path / "unrelated-parent"
    unrelated_parent.mkdir()
    (unrelated_parent / "pyproject.toml").touch()
    (unrelated_parent / "AGENTS.md").touch()
    (unrelated_parent / "src").mkdir()
    nested = unrelated_parent / "unrelated-work"
    nested.mkdir()
    with pytest.raises(
        RepositoryRootNotFoundError,
        match=r"pyproject\.toml, src/dai_sim/ and config/",
    ):
        find_repository_root(nested)


def test_find_repository_root_rejects_nonexistent_start(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        find_repository_root(tmp_path / "missing")


@pytest.mark.parametrize("sentinel", ("pyproject.toml", "src/dai_sim", "config"))
def test_single_weak_sentinel_is_not_accepted(
    tmp_path: Path,
    sentinel: str,
) -> None:
    candidate = _make_sentinel_root(tmp_path / "candidate")
    marker = candidate / sentinel
    if marker.is_dir():
        marker.rmdir()
        if sentinel == "src/dai_sim":
            (candidate / "src").rmdir()
    else:
        marker.unlink()
    with pytest.raises(
        RepositoryRootNotFoundError,
        match=r"pyproject\.toml, src/dai_sim/ and config/",
    ):
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
    runtime_requirements = payload["project"]["dependencies"]
    assert runtime_requirements == [
        "matplotlib>=3.8",
        "numpy>=1.26",
        "pandas>=2.1",
        "PyYAML>=6.0",
        "scipy>=1.11",
    ]
    extras = payload["project"]["optional-dependencies"]
    assert extras == {
        "test": ["pytest>=8.0", "setuptools>=68"],
        "lint": ["ruff>=0.14"],
    }
    assert "dynamic" not in payload["project"]
    assert "dynamic" not in payload["tool"]["setuptools"]
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
        "dai_sim.experiments.final",
        "dai_sim.experiments.mechanism",
        "dai_sim.inputs",
        "dai_sim.model",
        "dai_sim.validation",
    ]

    requirements = (REPOSITORY_ROOT / "requirements.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    assert requirements == [
        "# Authoritative runtime and test dependencies are declared in pyproject.toml.",
        "-e .[test]",
    ]
    assert not any(
        marker in line
        for line in requirements
        for marker in ("@ file:", "file://", "/Users/", "/home/", "/opt/conda")
    )

    imported = {}
    for root_name in ("src", "workflows", "tests"):
        names = set()
        for path in (REPOSITORY_ROOT / root_name).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(item.name.split(".")[0] for item in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.add(node.module.split(".")[0])
        imported[root_name] = names
    runtime_imports = {"matplotlib", "numpy", "pandas", "scipy", "yaml"}
    test_only_imports = {"pytest", "setuptools"}
    assert runtime_imports <= imported["src"] | imported["workflows"]
    assert test_only_imports <= imported["tests"]
    declared_runtime_imports = {
        "yaml" if item.lower().startswith("pyyaml") else item.split(">=")[0].lower()
        for item in runtime_requirements
    }
    declared_test_imports = {
        item.split(">=")[0].lower() for item in extras["test"]
    }
    assert declared_runtime_imports == runtime_imports
    assert declared_test_imports == test_only_imports

    environment = yaml.safe_load(
        (REPOSITORY_ROOT / "environment.yml").read_text(encoding="utf-8")
    )
    environment_dependencies = set(environment["dependencies"])
    assert "python>=3.11,<3.14" in environment_dependencies
    normalised_environment = {item.lower() for item in environment_dependencies}
    assert {item.lower() for item in runtime_requirements} <= normalised_environment
    assert {item.lower() for item in extras["test"]} <= normalised_environment
    assert {item.lower() for item in extras["lint"]} <= normalised_environment
