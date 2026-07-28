"""Import-safe bootstrap for directly executed repository workflows."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import ModuleType


def _repository_root(script_path: str | Path) -> Path:
    """Locate the repository without relying on a fixed parent depth."""
    resolved = Path(script_path).resolve()
    for candidate in resolved.parents:
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "AGENTS.md").is_file()
            and (candidate / "src" / "dai_sim").is_dir()
        ):
            return candidate
    raise RuntimeError(f"Cannot locate repository root above {resolved}")


def _load_dai_sim(repository_root: Path) -> None:
    """Load the source package without mutating ``sys.path``."""
    if "dai_sim" in sys.modules:
        return
    package_root = repository_root / "src" / "dai_sim"
    specification = spec_from_file_location(
        "dai_sim",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("Cannot construct the dai_sim package specification")
    module = module_from_spec(specification)
    sys.modules["dai_sim"] = module
    specification.loader.exec_module(module)


def _register_workflows_namespace(repository_root: Path) -> None:
    """Register the repository workflow namespace for direct execution."""
    if "workflows" in sys.modules:
        return
    module = ModuleType("workflows")
    module.__package__ = "workflows"
    module.__path__ = [str(repository_root / "workflows")]  # type: ignore[attr-defined]
    sys.modules["workflows"] = module


def bootstrap_runtime(script_path: str | Path) -> Path:
    """Prepare direct workflow execution and return the repository root."""
    repository_root = _repository_root(script_path)
    _load_dai_sim(repository_root)
    _register_workflows_namespace(repository_root)
    return repository_root
