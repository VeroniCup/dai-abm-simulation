"""Focused checks for the Stage 5 domain-first data hierarchy."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess


from tests.support import REPOSITORY_ROOT
DATA_ROOT = REPOSITORY_ROOT / "data"

EXPECTED_LIFECYCLES = {
    "market": {"raw", "processed", "model_inputs", "provenance"},
    "gas": {"raw", "processed", "provenance"},
    "vaults": {"raw", "processed", "model_inputs", "provenance"},
    "liquidations": {"raw", "processed", "model_inputs", "provenance"},
    "protocol": {"raw", "processed", "provenance"},
}

OLD_DOMAIN_PATHS = {
    *(DATA_ROOT / "raw" / domain for domain in EXPECTED_LIFECYCLES),
    *(
        DATA_ROOT / "processed" / domain
        for domain in (*EXPECTED_LIFECYCLES, "combined")
    ),
    *(DATA_ROOT / "provenance" / domain for domain in EXPECTED_LIFECYCLES),
    DATA_ROOT / "provenance" / "manifests",
}

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


def _tree_digest(root: Path, lifecycle: str) -> str:
    """Hash lifecycle, relative path, byte size and file digest deterministically."""
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        record = (
            f"{lifecycle}\t{relative}\t{len(payload)}\t"
            f"{hashlib.sha256(payload).hexdigest()}\n"
        )
        digest.update(record.encode("utf-8"))
    return digest.hexdigest()


def _is_ignored(relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative_path],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    return result.returncode == 0


def test_domain_lifecycle_directories_are_populated_without_placeholders() -> None:
    for domain, expected in EXPECTED_LIFECYCLES.items():
        domain_root = DATA_ROOT / domain
        assert domain_root.is_dir()
        for lifecycle in expected:
            lifecycle_path = domain_root / lifecycle
            assert lifecycle_path == DATA_ROOT / domain / lifecycle
            assert not (lifecycle_path / ".gitkeep").exists()
            if lifecycle in {"raw", "processed"}:
                assert _is_ignored(
                    f"data/{domain}/{lifecycle}/generated.csv"
                )
            elif lifecycle == "provenance":
                assert _is_ignored(
                    f"data/{domain}/provenance/state/generated.json"
                )
            else:
                assert lifecycle_path.is_dir()
                assert any(
                    candidate.is_file()
                    for candidate in lifecycle_path.rglob("*")
                )


def test_old_active_domain_paths_are_absent() -> None:
    assert not [path for path in OLD_DOMAIN_PATHS if path.exists()]
    temporary_entries = {
        path.name
        for path in (DATA_ROOT / "processed").iterdir()
        if path.name != ".DS_Store"
    }
    assert temporary_entries == {"README.md"}


def test_combined_market_gas_panel_is_market_owned() -> None:
    canonical = "data/market/processed/combined/hourly_market_gas_panel.csv"
    market_manifest = (
        DATA_ROOT / "market/model_inputs/environment_blocks/manifest.json"
    ).read_text(encoding="utf-8")
    assert canonical in market_manifest
    assert _is_ignored(canonical)
    assert not (DATA_ROOT / "processed/combined").exists()


def test_tree_digest_is_prefix_independent_and_detects_content_change(
    tmp_path: Path,
) -> None:
    old = tmp_path / "old-prefix"
    new = tmp_path / "new-prefix"
    for root in (old, new):
        (root / "nested").mkdir(parents=True)
        (root / "alpha.csv").write_bytes(b"header\nvalue\n")
        (root / "nested/beta.json").write_bytes(b'{"valid": true}\n')

    assert _tree_digest(old, "raw") == _tree_digest(new, "raw")
    (new / "nested/beta.json").write_bytes(b'{"valid": false}\n')
    assert _tree_digest(old, "raw") != _tree_digest(new, "raw")


def test_domain_ignore_policy_preserves_model_inputs_and_documentation() -> None:
    for domain in EXPECTED_LIFECYCLES:
        assert _is_ignored(f"data/{domain}/raw/generated.csv")
        assert _is_ignored(f"data/{domain}/processed/generated.csv")
    assert _is_ignored("data/vaults/provenance/state/generated.json")
    assert _is_ignored(
        "outputs/diagnostics/calibration/generated.json"
    )

    assert not _is_ignored("data/market/raw/README.md")
    assert not _is_ignored("data/market/model_inputs/environment_blocks/pool.csv")
    assert not _is_ignored(
        "data/liquidations/model_inputs/keeper_gas/pool.csv"
    )


def test_authoritative_code_and_scripts_have_no_old_data_path_fallback() -> None:
    split_lifecycle_path = re.compile(
        r'/\s*["\']data["\']\s*/\s*'
        r'["\'](?:raw|processed|provenance)["\']\s*/\s*'
        r'["\'](?:market|gas|vaults|liquidations|protocol)["\']'
    )
    paths = [
        *sorted((REPOSITORY_ROOT / "src").rglob("*.py")),
        *sorted((REPOSITORY_ROOT / "workflows").rglob("*.py")),
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert not any(prefix in text for prefix in OLD_ACTIVE_PREFIXES), path
        assert split_lifecycle_path.search(text) is None, path
