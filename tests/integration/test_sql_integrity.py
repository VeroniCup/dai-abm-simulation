"""Content-integrity tests for domain-owned SQL templates."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys


from tests.support import REPOSITORY_ROOT
BASELINE = REPOSITORY_ROOT / "docs/repository_restructuring_baseline_manifest.json"
PATH_MAP = REPOSITORY_ROOT / "docs/repository_restructuring_path_map.csv"


def _baseline() -> dict[str, object]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _sql_mapping() -> dict[str, str]:
    with PATH_MAP.open(encoding="utf-8", newline="") as handle:
        return {
            row["current_path"]: row["proposed_path"]
            for row in csv.DictReader(handle)
            if row["current_path"].startswith("sql/")
        }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sql_classification_and_content_match_stage_one_baseline() -> None:
    sql = _baseline()["sql"]
    assert isinstance(sql, dict)
    assert sql["total_count"] == 117
    assert sql["hand_authored_or_template_count"] == 20
    assert sql["generated_count"] == 97

    mapping = _sql_mapping()
    files = sql["files"]
    assert isinstance(files, list)
    assert len(files) == 117
    for record in files:
        assert isinstance(record, dict)
        target = REPOSITORY_ROOT / mapping[record["path"]]
        assert _sha256(target) == record["sha256"]


def test_sql_sizes_match_stage_one_tracked_inventory() -> None:
    payload = _baseline()
    mapping = _sql_mapping()
    tracked = {
        record["path"]: record
        for record in payload["tracked_files"]
        if record["path"].startswith("sql/")
    }
    assert len(tracked) == 117
    for source, target in mapping.items():
        path = REPOSITORY_ROOT / target
        assert path.stat().st_size == tracked[source]["size_bytes"]
        assert _sha256(path) == tracked[source]["sha256"]


def test_sql_imports_are_lazy_and_have_no_network_or_output_side_effects(
    tmp_path: Path,
) -> None:
    workflow_modules = [
        ".".join(path.relative_to(REPOSITORY_ROOT).with_suffix("").parts)
        for path in (REPOSITORY_ROOT / "workflows").rglob("*.py")
        if path.name not in {"__init__.py", "_bootstrap.py"}
    ]
    code = f"""
import importlib
import pathlib
import urllib.request

original = pathlib.Path.read_text
def guarded(self, *args, **kwargs):
    if self.suffix == ".sql":
        raise AssertionError(f"workflow import read SQL: {{self}}")
    return original(self, *args, **kwargs)
pathlib.Path.read_text = guarded
urllib.request.urlopen = lambda *args, **kwargs: (_ for _ in ()).throw(
    AssertionError("workflow import accessed the network")
)
for name in {workflow_modules!r}:
    importlib.import_module(name)
"""
    subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=tmp_path,
        env={
            "PYTHONPATH": str(REPOSITORY_ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=True,
    )
    assert list(tmp_path.iterdir()) == []


def test_active_metadata_uses_current_sql_paths() -> None:
    mapping = _sql_mapping()
    obsolete = {
        source for source, target in mapping.items() if source != target
    }
    active_paths = (
        REPOSITORY_ROOT / "data/provenance/data_manifest.csv",
        REPOSITORY_ROOT / "data/gas/provenance/dune_ethereum_hourly_gas_chunk_ledger.json",
        REPOSITORY_ROOT / "data/liquidations/provenance/manifest.json",
        REPOSITORY_ROOT / "data/protocol/provenance/manifest.json",
        REPOSITORY_ROOT / "data/vaults/provenance/discovery_manifest.json",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in active_paths)
    assert not any(path in combined for path in obsolete)
    assert "sql/market/templates/hourly_prices.sql" in combined
    assert "sql/gas/templates/hourly_conditions.sql" in combined
    assert "sql/liquidations/generated/history/chunk_01_2021_06_action.sql" in combined
    assert "sql/protocol/templates/vat_parameters.sql" in combined
    assert "sql/vaults/templates/vat_frob_diagnostic.sql" in combined
