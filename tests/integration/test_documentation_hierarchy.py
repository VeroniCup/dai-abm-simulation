from __future__ import annotations

import hashlib
import re
from pathlib import Path


from tests.support import REPOSITORY_ROOT as ROOT
DOCS = ROOT / "docs"

ACTIVE_CATEGORIES = (
    "overview",
    "model",
    "calibration",
    "experiments",
    "data",
    "validation",
)
ROOT_DOCUMENTS = (
    "README.md",
    "PROJECT_STATUS.md",
    "AGENTS.md",
    "empirical.md",
    "parameters.md",
)
CHRONOLOGY = re.compile(
    r"(phase1|phase2|tranche_a|tranche_b|tranche_c|tranche_d|"
    r"attempt3|repair|final_v\\d+)",
    re.IGNORECASE,
)

CANONICAL_METHOD_DOCUMENTS = (
    "docs/calibration/parameter_adoption.md",
    "docs/calibration/parameter_estimation.md",
    "docs/calibration/vaults.md",
    "docs/calibration/liquidations.md",
    "docs/calibration/market_and_gas.md",
    "docs/data/acquisition.md",
)


def active_documents() -> list[Path]:
    roots = [ROOT / name for name in ROOT_DOCUMENTS]
    category_docs = [
        path
        for category in ACTIVE_CATEGORIES
        for path in (DOCS / category).rglob("*.md")
    ]
    return roots + category_docs


def test_every_populated_documentation_category_has_real_content() -> None:
    for category in ACTIVE_CATEGORIES:
        directory = DOCS / category
        files = [path for path in directory.rglob("*") if path.is_file()]
        assert directory.is_dir(), category
        assert files, category
        for path in files:
            assert path.stat().st_size > 0, path

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
    for name in ROOT_DOCUMENTS:
        path = ROOT / name
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8")
        assert "docs/" in text

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/overview/architecture.md" in readme
    assert "docs/model/README.md" in readme
    assert "docs/data/acquisition.md" in readme


def test_document_migration_ledger_covers_every_moved_source() -> None:
    for path in CANONICAL_METHOD_DOCUMENTS:
        assert (ROOT / path).is_file(), path

    obsolete_root_documents = (
        "docs/parameter_adoption_and_model_interface_plan.md",
        "docs/parameter_estimation_plan.md",
        "docs/phase1e_representative_calibration_strategy.md",
    )
    for path in obsolete_root_documents:
        assert not (ROOT / path).exists(), path


def test_acquisition_plan_is_preserved_byte_for_byte() -> None:
    archived = (
        DOCS / "archive" / "historical_plans" / "DATA_ACQUISITION_PLAN.md"
    )
    assert archived.is_file()
    assert not (ROOT / "data" / "DATA_ACQUISITION_PLAN.md").exists()
    digest = hashlib.sha256(archived.read_bytes()).hexdigest()
    assert digest == (
        "05587f17600f148d90cc26df4f281258d"
        "299188dad8dd53d2ab00f351863ee60"
    )

    acquisition = (DOCS / "data" / "acquisition.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "representative",
        "prices.hour",
        "ethereum.transactions",
        "WBTC",
        "stop-on-failure",
        "DUNE_API_KEY",
        "query and execution identifiers",
    ):
        assert phrase in acquisition


def test_no_placeholder_document_exists() -> None:
    for path in DOCS.rglob("*.md"):
        text = path.read_text(encoding="utf-8").lower()
        assert "coming soon" not in text, path
        assert "todo: write" not in text, path
