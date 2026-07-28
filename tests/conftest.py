"""Suite-wide import and repository-path support."""

from __future__ import annotations

from pathlib import Path
import sys

_TESTS_ROOT = Path(__file__).resolve().parent
_SOURCE_ROOT = _TESTS_ROOT.parent / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from dai_sim.common.paths import find_repository_root


REPOSITORY_ROOT = find_repository_root(__file__)
