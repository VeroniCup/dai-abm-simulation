from __future__ import annotations

import hashlib
import json
import re
import subprocess

from dai_sim.common.archive_boundary import load_external_content_manifest
from pathlib import Path


from tests.support import REPOSITORY_ROOT as ROOT
DOCS = ROOT / "docs"

SOFTWARE_GUIDES = (
    "docs/repository_structure.md",
    "docs/components.md",
    "docs/running.md",
)
USER_DOCUMENTS = ("README.md", *SOFTWARE_GUIDES)
CHRONOLOGY = re.compile(
    r"(phase1|phase2|tranche_a|tranche_b|tranche_c|tranche_d|"
    r"attempt3|repair|final_v\\d+)",
    re.IGNORECASE,
)
HISTORICAL_RECORD = (
    ROOT
    / "data/provenance/maintenance/submission_portability/"
    "historical_document_checksums.json"
)


def active_documents() -> list[Path]:
    return [ROOT / name for name in USER_DOCUMENTS]


def repository_inventory_paths() -> set[str]:
    """Return the candidate tracked paths in Git or the archive manifest."""
    probe = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0 and probe.stdout.strip() == "true":
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--stage", "-z"],
            check=True,
            capture_output=True,
        )
        paths = set()
        for entry in listed.stdout.split(b"\0"):
            if not entry:
                continue
            metadata, encoded_path = entry.split(b"\t", maxsplit=1)
            _mode, _object_id, stage = metadata.decode("ascii").split()
            if stage != "0":
                raise ValueError("Git index contains unresolved merge stages.")
            paths.add(encoded_path.decode("utf-8"))
        return paths

    inventory = load_external_content_manifest(ROOT)
    return {item["path"] for item in inventory["included_files"]}


def test_every_populated_documentation_category_has_real_content() -> None:
    for relative in USER_DOCUMENTS:
        path = ROOT / relative
        assert path.is_file(), relative
        assert path.stat().st_size > 0, relative


def test_active_document_names_and_headings_are_semantic() -> None:
    for path in active_documents():
        relative = path.relative_to(ROOT).as_posix()
        assert not CHRONOLOGY.search(path.name), relative
        headings = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("#")
        ]
        assert not any(CHRONOLOGY.search(line) for line in headings), relative


def test_phase_and_tranche_reports_are_archived() -> None:
    active = [
        path.relative_to(ROOT).as_posix()
        for path in DOCS.rglob("*.md")
        if "archive" not in path.parts and CHRONOLOGY.search(path.name)
    ]
    assert active == []


def test_root_entry_points_exist_and_link_to_semantic_detail() -> None:
    readme = ROOT / "README.md"
    assert readme.is_file()
    text = readme.read_text(encoding="utf-8")
    for relative in SOFTWARE_GUIDES:
        assert relative in text


def test_document_migration_ledger_covers_every_moved_source() -> None:
    for relative in USER_DOCUMENTS:
        assert (ROOT / relative).is_file(), relative

    internal_roots = ("AGENTS.md", "PROJECT_STATUS.md", "empirical.md", "parameters.md")
    paths = repository_inventory_paths()
    assert not set(internal_roots).intersection(paths)
    assert {path for path in paths if path.endswith(".md")} == set(USER_DOCUMENTS)
    assert "outputs/README.md" not in paths
    assert not any(path.startswith("config/submission/") for path in paths)
    assert not any(path.startswith("tools/packaging/") for path in paths)


def test_acquisition_plan_is_preserved_byte_for_byte() -> None:
    archived = DOCS / "archive/historical_plans/DATA_ACQUISITION_PLAN.md"
    expected = "05587f17600f148d90cc26df4f281258d299188dad8dd53d2ab00f351863ee60"
    if archived.is_file():
        assert hashlib.sha256(archived.read_bytes()).hexdigest() == expected

    record = json.loads(HISTORICAL_RECORD.read_text(encoding="utf-8"))
    entries = {item["path"]: item for item in record["documents"]}
    item = entries["docs/archive/historical_plans/DATA_ACQUISITION_PLAN.md"]
    assert item["sha256"] == expected
    assert item["submission_treatment"] == "excluded_historical_checksum_bound"


def test_no_placeholder_document_exists() -> None:
    for path in active_documents():
        text = path.read_text(encoding="utf-8").lower()
        assert "coming soon" not in text, path
        assert "todo: write" not in text, path
        assert "in progress" not in text, path
