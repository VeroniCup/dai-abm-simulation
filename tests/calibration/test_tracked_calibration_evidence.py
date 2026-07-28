"""Tracked-only reproducibility checks for compact calibration evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess

from dai_sim.calibration import adoption
from dai_sim.inputs import configuration

from tests.support import REPOSITORY_ROOT


MANIFEST_PATH = (
    REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_ignored(relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative_path],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    return result.returncode == 0


def test_tracked_calibration_evidence_is_content_addressed() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert len(manifest["artefacts"]) == 13
    for record in manifest["artefacts"]:
        path = REPOSITORY_ROOT / record["path"]
        assert path.is_file(), record["semantic_name"]
        assert not _is_ignored(record["path"]), record["semantic_name"]
        assert path.stat().st_size == record["size_bytes"]
        assert _sha256(path) == record["sha256"]
        assert record["classification"] in {"snapshot", "runtime_input"}


def test_parameter_adoption_snapshot_has_canonical_schema() -> None:
    path = (
        REPOSITORY_ROOT
        / "data/provenance/calibration/parameter_adoption/"
        "parameter_adoption_matrix.csv"
    )
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 56
    assert len(rows[0]) == 31
    assert {row["parameter_subsection"] for row in rows} == {
        f"4.{section}.{parameter}"
        for section, count in ((1, 7), (2, 8), (3, 12), (4, 6), (5, 10), (6, 13))
        for parameter in range(1, count + 1)
    }
    assert {row["adopted"] for row in rows} == {"False"}


def test_candidate_registry_counts_and_statuses_are_preserved() -> None:
    root = REPOSITORY_ROOT / "data/provenance/calibration"
    market = json.loads(
        (root / "market_gas_protocol/candidate_parameters.json").read_text(
            encoding="utf-8"
        )
    )
    vaults = json.loads(
        (root / "vaults/candidate_parameters.json").read_text(
            encoding="utf-8"
        )
    )
    liquidations = json.loads(
        (root / "liquidations/candidate_parameters.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(market["candidates"]) == 64
    assert len(vaults["candidates"]) == 9
    assert len(liquidations["candidates"]) == 7
    assert liquidations["no_candidate_adopted"] is True


def test_canonical_consumers_use_tracked_evidence() -> None:
    assert configuration.CONFIGURATION_READY_CANDIDATES.is_file()
    assert all(
        relative.startswith("data/provenance/calibration/")
        for relative in configuration.EXPECTED_ADOPTION_REVIEW_CHECKSUMS
    )
    assert all(
        path.is_file()
        and path.is_relative_to(
            REPOSITORY_ROOT / "data/provenance/calibration"
        )
        for path in adoption.REGISTRIES.values()
    )
    assert adoption.PHASE2A_STATUS.is_file()


def test_ignored_diagnostic_copies_remain_optional() -> None:
    ignored = (
        "outputs/diagnostics/calibration/parameter_adoption/"
        "parameter_adoption_matrix.csv",
        "outputs/diagnostics/calibration/market_gas_protocol/"
        "phase2a_candidate_parameters.json",
    )
    assert all(_is_ignored(path) for path in ignored)
    automatic_consumers = (
        REPOSITORY_ROOT / "src/dai_sim/inputs/configuration.py",
        REPOSITORY_ROOT / "src/dai_sim/calibration/adoption.py",
    )
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in automatic_consumers
    )
    assert not any(path in text for path in ignored)


def test_large_empirical_sources_remain_ignored() -> None:
    ignored = (
        "data/market/processed/combined/hourly_market_gas_panel.csv",
        "data/vaults/processed/representative_regimes/"
        "quiet_mature_2024-02-01_2024-03-01/opening_vault_state.csv",
    )
    assert all(_is_ignored(path) for path in ignored)
