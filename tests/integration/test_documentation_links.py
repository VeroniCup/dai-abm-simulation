from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest


from tests.support import REPOSITORY_ROOT as ROOT
USER_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs/repository_structure.md",
    ROOT / "docs/components.md",
    ROOT / "docs/running.md",
)
MARKDOWN_LINK = re.compile(
    r"(?<!!)\[[^\]]*\]\(([^)]+)\)|!\[[^\]]*\]\(([^)]+)\)"
)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def documentation_files() -> list[Path]:
    return list(USER_DOCUMENTS)


def active_documents() -> list[Path]:
    return documentation_files()


def github_slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[`*_~]", "", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return re.sub(r"\s+", "-", text)


def anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    result: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADING.match(line)
        if not match:
            continue
        base = github_slug(match.group(1))
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.add(base if count == 0 else f"{base}-{count}")
    return result


def local_links(path: Path) -> list[tuple[str, str | None]]:
    found = []
    for match in MARKDOWN_LINK.finditer(path.read_text(encoding="utf-8")):
        raw = (match.group(1) or match.group(2)).strip()
        if raw.startswith(("http://", "https://", "mailto:")):
            continue
        target, marker, anchor = raw.partition("#")
        found.append((unquote(target), anchor if marker else None))
    return found


def test_all_local_markdown_links_and_anchors_resolve() -> None:
    failures = []
    for source in active_documents():
        for target, anchor in local_links(source):
            destination = source if not target else (source.parent / target).resolve()
            if not destination.exists():
                failures.append(f"{source.relative_to(ROOT)} -> {target}")
                continue
            if anchor and destination.is_file() and destination.suffix == ".md":
                if anchor not in anchors(destination):
                    failures.append(f"{source.relative_to(ROOT)} -> {target}#{anchor}")
    assert failures == []


def test_no_machine_specific_documentation_links() -> None:
    for path in documentation_files():
        text = path.read_text(encoding="utf-8")
        assert "file:///" not in text, path
        assert "/Users/" not in text, path


def test_active_docs_do_not_present_obsolete_paths_as_authoritative() -> None:
    obsolete_literals = (
        "src/estimation/",
        "config/empirical/data/",
        "sql/dune_",
        "scripts/",
        "docs/phase1e_",
        "docs/phase2",
        "docs/tranche_",
    )
    flat_source = re.compile(r"`src/(?!dai_sim/)[a-z_]+\.py`")
    banned_user_phrases = re.compile(
        r"\b(Codex|prompt|assistant|current HEAD|working tree|marker-facing|"
        r"submission guide|current pass|portability migration phase|"
        r"readiness classification|scientific owner|semantic owner|"
        r"historical identity replacement|internal development|audit result)\b",
        re.IGNORECASE,
    )
    failures = []
    for path in active_documents():
        text = path.read_text(encoding="utf-8")
        for literal in obsolete_literals:
            if literal in text:
                failures.append(f"{path.relative_to(ROOT)}: {literal}")
        if flat_source.search(text):
            failures.append(f"{path.relative_to(ROOT)}: flat src module")
    for path in USER_DOCUMENTS:
        if banned_user_phrases.search(path.read_text(encoding="utf-8")):
            failures.append(f"{path.relative_to(ROOT)}: development-history prose")
    assert failures == []


@pytest.mark.parametrize(
    "script",
    (
        "workflows/market/acquire.py",
        "workflows/market/process.py",
        "workflows/market/validate.py",
        "workflows/gas/process.py",
        "workflows/vaults/build_inputs.py",
        "workflows/calibration/validate.py",
    ),
)
def test_documented_workflow_help_is_safe_and_current(script: str) -> None:
    completed = subprocess.run(
        [sys.executable, script, "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()


def test_active_shell_commands_reference_existing_paths() -> None:
    command = re.compile(r"^\s*python\s+([^\s\\]+)", re.MULTILINE)
    missing = []
    for path in active_documents():
        for target in command.findall(path.read_text(encoding="utf-8")):
            if target in {"-m", "-c"}:
                continue
            if not (ROOT / target).exists():
                missing.append(f"{path.relative_to(ROOT)}: {target}")
    assert missing == []

    user_text = "\n".join(path.read_text(encoding="utf-8") for path in USER_DOCUMENTS)
    assert "confidence was calibrated" not in user_text.lower()
    assert "historical maker oracle latency estimate" not in user_text.lower()
