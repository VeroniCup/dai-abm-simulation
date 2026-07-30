"""Focused checks for Stage 5 provenance ownership and active paths."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import subprocess


from tests.support import REPOSITORY_ROOT
DATA_ROOT = REPOSITORY_ROOT / "data"

OLD_ACTIVE_PREFIXES = (
    "data/raw/market",
    "data/raw/gas",
    "data/raw/vaults",
    "data/raw/liquidations",
    "data/raw/protocol",
    "data/processed/market",
    "data/processed/gas",
    "data/processed/vaults",
    "data/processed/liquidations",
    "data/processed/protocol",
    "data/processed/combined",
    "data/provenance/market",
    "data/provenance/gas",
    "data/provenance/vaults",
    "data/provenance/liquidations",
    "data/provenance/protocol",
    "data/provenance/manifests",
)

DURABLE_PROVENANCE = (
    "data/provenance/data_manifest.csv",
    "data/provenance/index.json",
    "data/provenance/calibration/manifest.json",
    "data/provenance/experiments/manifest.json",
    (
        "data/provenance/experiments/confidence/"
        "confidence_scenario_specification.json"
    ),
    (
        "data/provenance/experiments/confidence/"
        "confidence_scenario_registry.csv"
    ),
    (
        "data/provenance/experiments/confidence/"
        "confidence_scenario_reproducibility.json"
    ),
    (
        "data/provenance/experiments/confidence/"
        "confidence_scenario_decision.json"
    ),
    "data/gas/provenance/dune_ethereum_hourly_gas_chunk_ledger.json",
    "data/liquidations/provenance/manifest.json",
    "data/protocol/provenance/manifest.json",
    "data/protocol/provenance/clipper_stopped_default_states.csv",
    "data/protocol/provenance/parameter_adoption/manifest.json",
    "data/vaults/provenance/discovery_manifest.json",
    "data/vaults/provenance/manifest.json",
)


def _is_ignored(relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative_path],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    return result.returncode == 0


def test_root_provenance_contains_only_cross_domain_entry_points() -> None:
    entries = {
        path.name
        for path in (DATA_ROOT / "provenance").iterdir()
        if path.name != ".DS_Store"
    }
    assert entries == {
        "calibration",
        "experiments",
        "data_manifest.csv",
        "index.json",
    }


def test_provenance_index_uses_resolvable_domain_first_paths() -> None:
    payload = json.loads(
        (DATA_ROOT / "provenance/index.json").read_text(encoding="utf-8")
    )
    assert len(payload["categories"]) == 5
    for category in payload["categories"]:
        manifest = REPOSITORY_ROOT / category["authoritative_manifest"]
        assert manifest.is_file(), (category["category"], manifest)
        for key in ("raw_source_location", "processed_output_location"):
            relative = category[key]
            assert relative.startswith("data/")
            assert _is_ignored(f"{relative.rstrip('/')}/generated.csv")


def test_cross_domain_manifest_active_paths_resolve() -> None:
    manifest = DATA_ROOT / "provenance/data_manifest.csv"
    with manifest.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 7
    for row in rows:
        for key, value in row.items():
            if not value:
                continue
            if key.endswith("_path") or key in {
                "sql_file_path",
                "processing_script_path",
            }:
                path = REPOSITORY_ROOT / value
                if path.exists():
                    continue
                assert value.startswith("data/"), (key, value)
                assert _is_ignored(value), (key, value)


def test_active_provenance_has_no_old_domain_paths() -> None:
    for domain in ("market", "gas", "vaults", "liquidations", "protocol"):
        provenance = DATA_ROOT / domain / "provenance"
        for path in provenance.rglob("*"):
            if not path.is_file() or "archive" in path.relative_to(provenance).parts:
                continue
            if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8")
            assert not any(prefix in text for prefix in OLD_ACTIVE_PREFIXES), path


def test_durable_provenance_is_trackable_and_has_no_absolute_local_paths() -> None:
    local_path = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\)")
    for relative in DURABLE_PROVENANCE:
        path = REPOSITORY_ROOT / relative
        assert path.is_file()
        assert not _is_ignored(relative)
        assert local_path.search(path.read_text(encoding="utf-8")) is None


def test_detailed_provenance_remains_ignored() -> None:
    assert _is_ignored("data/gas/provenance/state/chunk_99.state.json")
    assert _is_ignored(
        "data/liquidations/provenance/chunks/chunk_99/validation.json"
    )
    assert _is_ignored("data/protocol/provenance/modules/vat/state.json")
    assert _is_ignored("data/vaults/provenance/chunks/chunk_99/state.json")
