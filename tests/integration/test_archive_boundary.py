"""Contracts for the deterministic manifest-filtered code submission."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import subprocess
from typing import Any

import pytest

from dai_sim.common import archive_boundary as bundle
from tests.integration.test_documentation_links import local_links
from tests.support import REPOSITORY_ROOT


INCLUDE = REPOSITORY_ROOT / "config/submission/code_submission_include.txt"
EXCLUDE = REPOSITORY_ROOT / "config/submission/code_submission_exclude.txt"
BUILDER = REPOSITORY_ROOT / "tools/packaging/build_code_bundle.py"


def _write(path: Path, text: str = "content\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _rules(tmp_path: Path, include: str, exclude: str = "ignored/\n"):
    include_path = tmp_path / "include.txt"
    exclude_path = tmp_path / "exclude.txt"
    _write(include_path, include)
    _write(exclude_path, exclude)
    return (
        bundle.parse_manifest(include_path),
        bundle.parse_manifest(exclude_path),
    )


def _normalise_inventory(inventory: dict[str, Any]) -> dict[str, object]:
    """Return the shared, minimal Git/archive inventory contract."""
    records = inventory.get("included_files")
    if not isinstance(records, list):
        raise ValueError("Inventory included_files must be a list.")

    normalised = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Inventory file records must be objects.")
        path = record.get("path")
        size = record.get("size_bytes")
        checksum = record.get("sha256")
        executable = record.get("executable")
        if (
            not isinstance(path, str)
            or not path
            or PurePosixPath(path).is_absolute()
            or any(part in {"", ".", ".."} for part in PurePosixPath(path).parts)
        ):
            raise ValueError(f"Inventory path is not canonical: {path!r}.")
        if path in seen:
            raise ValueError(f"Inventory path is duplicated: {path}.")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError(f"Inventory size is invalid: {path}.")
        if (
            not isinstance(checksum, str)
            or len(checksum) != 64
            or any(character not in "0123456789abcdef" for character in checksum)
        ):
            raise ValueError(f"Inventory checksum is invalid: {path}.")
        if not isinstance(executable, bool):
            raise ValueError(f"Inventory executable flag is invalid: {path}.")
        seen.add(path)
        normalised.append(
            {
                "path": path,
                "size_bytes": size,
                "sha256": checksum,
                "executable": executable,
            }
        )

    normalised.sort(key=lambda item: item["path"])
    count = inventory.get("included_file_count")
    total = inventory.get("included_total_bytes")
    identity = inventory.get("submission_bundle_identity")
    if count != len(normalised):
        raise ValueError("Inventory file count differs from its records.")
    if total != sum(item["size_bytes"] for item in normalised):
        raise ValueError("Inventory byte count differs from its records.")
    expected_identity = bundle.submission_bundle_identity(normalised)
    if identity != expected_identity:
        raise ValueError("Inventory identity differs from its records.")
    unmatched = inventory.get("unmatched_include_globs", [])
    if not isinstance(unmatched, list) or not all(
        isinstance(item, str) for item in unmatched
    ):
        raise ValueError("Inventory unmatched globs must be a list of strings.")
    return {
        "included_files": normalised,
        "included_file_count": len(normalised),
        "included_total_bytes": total,
        "submission_bundle_identity": identity,
        "unmatched_include_globs": unmatched,
    }


def _git_index_inventory(repository_root: Path) -> dict[str, object] | None:
    """Return the staged tracked-file inventory, or ``None`` outside Git."""
    probe = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return None
    listed = subprocess.run(
        ["git", "-C", str(repository_root), "ls-files", "--stage", "-z"],
        check=True,
        capture_output=True,
    )
    records = []
    for entry in listed.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, encoded_path = entry.split(b"\t", maxsplit=1)
        mode, object_id, stage = metadata.decode("ascii").split()
        if stage != "0":
            raise ValueError("Git index contains unresolved merge stages.")
        if mode not in {"100644", "100755"}:
            raise ValueError(
                "Git inventory supports regular files only; "
                f"found mode {mode}."
            )
        path = encoded_path.decode("utf-8")
        blob = subprocess.run(
            ["git", "-C", str(repository_root), "cat-file", "blob", object_id],
            check=True,
            capture_output=True,
        ).stdout
        records.append(
            {
                "path": path,
                "size_bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "executable": mode == "100755",
            }
        )
    records.sort(key=lambda item: item["path"])
    inventory = {
        "included_files": records,
        "included_file_count": len(records),
        "included_total_bytes": sum(item["size_bytes"] for item in records),
        "submission_bundle_identity": bundle.submission_bundle_identity(records),
        "unmatched_include_globs": [],
    }
    return _normalise_inventory(inventory)


def _repository_inventory(
    repository_root: Path = REPOSITORY_ROOT,
    external_manifest: Path | None = None,
) -> dict[str, object]:
    git_inventory = _git_index_inventory(repository_root)
    if git_inventory is not None:
        return git_inventory
    try:
        inventory = bundle.load_external_content_manifest(
            repository_root,
            external_manifest,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "Repository inventory requires either a valid Git worktree "
            "or one matching external content manifest."
        ) from exc
    return _normalise_inventory(inventory)


def _run_git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
    )


def _initialise_git_repository(repository: Path) -> None:
    repository.mkdir()
    _run_git(repository, "init", "--quiet")
    _run_git(repository, "config", "user.email", "test@example.invalid")
    _run_git(repository, "config", "user.name", "Archive Boundary Test")


def _write_external_manifest(
    repository: Path,
    inventory: dict[str, object],
) -> Path:
    manifest = bundle.external_content_manifest_path(repository)
    manifest.write_bytes(bundle.canonical_json_bytes(inventory))
    return manifest


def _assert_git_inventory_reads_candidate_index_without_external_manifest(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "git-candidate"
    _initialise_git_repository(repository)
    _write(repository / ".gitignore", "ignored.txt\n")
    _write(repository / "retained.txt", "staged bytes\n")
    _write(repository / "deleted.txt")
    _run_git(repository, "add", ".gitignore", "retained.txt", "deleted.txt")
    _write(repository / "retained.txt", "unstaged replacement\n")
    _run_git(repository, "rm", "--cached", "deleted.txt")
    _write(repository / "added.txt", "new staged file\n")
    _run_git(repository, "add", "added.txt")
    _write(repository / "untracked.txt")
    _write(repository / "ignored.txt")

    inventory = _repository_inventory(repository)
    records = {
        item["path"]: item for item in inventory["included_files"]
    }
    assert set(records) == {".gitignore", "added.txt", "retained.txt"}
    assert records["retained.txt"]["sha256"] == hashlib.sha256(
        b"staged bytes\n"
    ).hexdigest()
    assert not bundle.external_content_manifest_path(repository).exists()


def _assert_archive_inventory_uses_external_manifest(tmp_path: Path) -> None:
    repository = tmp_path / "archive-inventory"
    repository.mkdir()
    _write(repository / "payload.txt", "archive bytes\n")
    record = {
        "path": "payload.txt",
        "size_bytes": len(b"archive bytes\n"),
        "sha256": hashlib.sha256(b"archive bytes\n").hexdigest(),
        "executable": False,
    }
    inventory = {
        "included_files": [record],
        "included_file_count": 1,
        "included_total_bytes": record["size_bytes"],
        "submission_bundle_identity": bundle.submission_bundle_identity([record]),
        "unmatched_include_globs": [],
    }
    manifest = _write_external_manifest(repository, inventory)

    assert _repository_inventory(repository, manifest) == inventory


def _assert_git_and_manifest_inventories_normalise_identically(
    tmp_path: Path,
) -> None:
    git_repository = tmp_path / "git-equivalence"
    _initialise_git_repository(git_repository)
    _write(git_repository / "payload.txt", "shared bytes\n")
    _run_git(git_repository, "add", "payload.txt")
    git_inventory = _repository_inventory(git_repository)

    archive = tmp_path / "archive-equivalence"
    archive.mkdir()
    _write(archive / "payload.txt", "shared bytes\n")
    _write_external_manifest(archive, git_inventory)

    assert _repository_inventory(archive) == git_inventory


def _assert_repository_inventory_fails_without_git_or_manifest(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "unbound"
    repository.mkdir()
    _write(repository / "payload.txt")

    with pytest.raises(
        FileNotFoundError,
        match="valid Git worktree or one matching external content manifest",
    ):
        _repository_inventory(repository)


def test_manifest_parser_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "manifest.txt"
    _write(path, "# comment\n\nalpha.txt\nfolder/\n")
    rules = bundle.parse_manifest(path)
    assert [rule.pattern for rule in rules] == ["alpha.txt", "folder/"]


def test_exact_include_overrides_parent_exclusion(tmp_path: Path) -> None:
    include, exclude = _rules(
        tmp_path,
        "workflows/verification/verifier.py\n",
        "workflows/verification/\n",
    )
    assert bundle.select_paths(
        ("workflows/verification/verifier.py", "workflows/verification/other.py"),
        include,
        exclude,
    ) == ("workflows/verification/verifier.py",)


def test_directory_and_glob_rules_are_segment_aware(tmp_path: Path) -> None:
    include, exclude = _rules(tmp_path, "sql/*/templates/\n")
    selected = bundle.select_paths(
        (
            "sql/market/templates/query.sql",
            "sql/market/generated/query.sql",
            "other/sql/market/templates/query.sql",
        ),
        include,
        exclude,
    )
    assert selected == ("sql/market/templates/query.sql",)


def test_missing_literal_include_fails(tmp_path: Path) -> None:
    include_path = tmp_path / "include.txt"
    _write(include_path, "missing.txt\n")
    rules = bundle.parse_manifest(include_path)
    with pytest.raises(FileNotFoundError, match="missing.txt"):
        bundle.validate_manifest_rules(tmp_path, rules)


def test_unmatched_glob_is_reported(tmp_path: Path) -> None:
    include_path = tmp_path / "include.txt"
    _write(include_path, "sql/*/templates/\n")
    rules = bundle.parse_manifest(include_path)
    assert bundle.validate_manifest_rules(tmp_path, rules) == (
        "sql/*/templates/",
    )


def test_escaping_and_absolute_manifest_paths_are_rejected(tmp_path: Path) -> None:
    for value in ("../outside.txt\n", "/absolute.txt\n"):
        path = tmp_path / "manifest.txt"
        _write(path, value)
        with pytest.raises(ValueError, match="absolute|escapes"):
            bundle.parse_manifest(path)


def test_selected_symlink_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path / "real.txt")
    (tmp_path / "linked.txt").symlink_to(tmp_path / "real.txt")
    include_path = tmp_path / "include.txt"
    exclude_path = tmp_path / "exclude.txt"
    _write(include_path, "linked.txt\n")
    _write(exclude_path, "ignored/\n")
    with pytest.raises(ValueError, match="symlink"):
        bundle.build_inventory(
            repository_root=tmp_path,
            include_manifest=include_path,
            exclude_manifest=exclude_path,
            builder_source=Path(bundle.__file__),
            candidate_paths=("linked.txt",),
        )


def test_path_order_and_identity_are_deterministic(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "a\n")
    _write(tmp_path / "b.txt", "b\n")
    include_path = tmp_path / "include.txt"
    exclude_path = tmp_path / "exclude.txt"
    _write(include_path, "a.txt\nb.txt\n")
    _write(exclude_path, "ignored/\n")
    kwargs = {
        "repository_root": tmp_path,
        "include_manifest": include_path,
        "exclude_manifest": exclude_path,
        "builder_source": Path(bundle.__file__),
    }
    first = bundle.build_inventory(candidate_paths=("b.txt", "a.txt"), **kwargs)
    second = bundle.build_inventory(candidate_paths=("a.txt", "b.txt"), **kwargs)
    assert [item["path"] for item in first["included_files"]] == [
        "a.txt",
        "b.txt",
    ]
    assert first["submission_bundle_identity"] == second[
        "submission_bundle_identity"
    ]


def test_atomic_build_preserves_bytes_modes_and_verifies(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    destination = tmp_path / "submission"
    _write(repository / "script.py", "#!/usr/bin/env python\n")
    (repository / "script.py").chmod(0o755)
    include_path = repository / "include.txt"
    exclude_path = repository / "exclude.txt"
    _write(include_path, "script.py\n")
    _write(exclude_path, "ignored/\n")
    inventory = bundle.build_inventory(
        repository_root=repository,
        include_manifest=include_path,
        exclude_manifest=exclude_path,
        builder_source=Path(bundle.__file__),
        candidate_paths=("script.py",),
    )
    _, manifest_path = bundle.build_bundle(repository, destination, inventory)
    result = bundle.verify_bundle(destination)
    assert result["status"] == "passed"
    assert (destination / "script.py").read_bytes() == (
        repository / "script.py"
    ).read_bytes()
    assert (destination / "script.py").stat().st_mode & 0o111
    assert manifest_path.parent == destination.parent
    assert not (destination / bundle.LEGACY_CONTENT_MANIFEST_NAME).exists()


def test_final_md_is_intentionally_absent_from_submission() -> None:
    assert not (REPOSITORY_ROOT / "FINAL.md").exists()
    if INCLUDE.is_file():
        rules = bundle.parse_manifest(INCLUDE)
        assert all(rule.pattern != "FINAL.md" for rule in rules)
    else:
        assert "FINAL.md" not in {
            item["path"] for item in _repository_inventory()["included_files"]
        }

    record_path = (
        REPOSITORY_ROOT
        / "data/provenance/maintenance/submission_portability/"
        "historical_document_checksums.json"
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    expected = {
        "docs/archive/historical_plans/DATA_ACQUISITION_PLAN.md",
        "docs/repository_restructuring_baseline.md",
        "docs/repository_restructuring_baseline_manifest.json",
    }
    assert {item["path"] for item in record["documents"]} == expected
    assert all(
        item["submission_treatment"] == "excluded_historical_checksum_bound"
        for item in record["documents"]
    )


def test_repository_inventory_includes_complete_sql_and_verifier() -> None:
    inventory = _repository_inventory()
    paths = {item["path"] for item in inventory["included_files"]}
    sql_paths = {path for path in paths if path.endswith(".sql")}
    assert len(sql_paths) == 118
    assert "workflows/verification/verify_external_artifacts.py" in paths
    assert not any(path.startswith("workflows/maintenance/") for path in paths)
    assert not any(path.startswith("tools/") for path in paths)
    assert "config/runtime/runtime_input_map.yaml" in paths
    assert not any(path.startswith("config/submission/") for path in paths)
    assert not any(
        "submission" in path
        for path in paths
        if not path.startswith(
            "data/provenance/maintenance/submission_portability/"
        )
    )
    assert inventory["unmatched_include_globs"] == []


def test_repository_inventory_excludes_payloads_and_keeps_policy_readme() -> None:
    inventory = _repository_inventory()
    paths = {item["path"] for item in inventory["included_files"]}
    assert not any(path.startswith("outputs/") for path in paths)
    assert not any("/processed/" in path for path in paths)
    assert not any("checkpoints/" in path or "diagnostics/" in path for path in paths)

    required_markdown = {
        "README.md",
        "docs/repository_structure.md",
        "docs/components.md",
        "docs/running.md",
    }
    excluded = {
        "AGENTS.md",
        "PROJECT_STATUS.md",
        "empirical.md",
        "parameters.md",
        "outputs/README.md",
        "docs/archive/historical_plans/DATA_ACQUISITION_PLAN.md",
        "docs/repository_restructuring_baseline.md",
        "docs/repository_restructuring_baseline_manifest.json",
        "docs/overview/full_suite_failure_resolution.md",
        "docs/overview/submission_cleanup.md",
        "docs/overview/code_submission_readiness.md",
    }
    assert {path for path in paths if path.endswith(".md")} == required_markdown
    assert paths.isdisjoint(excluded)


def test_included_markdown_links_resolve_within_submission_payload() -> None:
    inventory = _repository_inventory()
    paths = {item["path"] for item in inventory["included_files"]}
    failures = []
    for relative in sorted(path for path in paths if path.endswith(".md")):
        source = REPOSITORY_ROOT / relative
        for target, _anchor in local_links(source):
            if not target:
                continue
            destination = (source.parent / target).resolve()
            try:
                target_relative = destination.relative_to(
                    REPOSITORY_ROOT
                ).as_posix()
            except ValueError:
                failures.append(f"{relative} -> {target}")
                continue
            if destination.is_dir():
                if not any(
                    path == target_relative or path.startswith(f"{target_relative}/")
                    for path in paths
                ):
                    failures.append(f"{relative} -> {target}")
            elif target_relative not in paths:
                failures.append(f"{relative} -> {target}")
    assert failures == []


def test_content_manifest_sidecar_is_not_self_hashed(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    destination = tmp_path / "submission"
    _write(repository / "payload.txt")
    include_path = repository / "include.txt"
    exclude_path = repository / "exclude.txt"
    _write(include_path, "payload.txt\n")
    _write(exclude_path, "ignored/\n")
    inventory = bundle.build_inventory(
        repository_root=repository,
        include_manifest=include_path,
        exclude_manifest=exclude_path,
        builder_source=Path(bundle.__file__),
        candidate_paths=("payload.txt",),
    )
    _, manifest_path = bundle.build_bundle(repository, destination, inventory)
    sidecar = json.loads(manifest_path.read_text(encoding="utf-8"))
    listed_paths = {item["path"] for item in sidecar["included_files"]}
    actual_paths = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert bundle.LEGACY_CONTENT_MANIFEST_NAME not in listed_paths
    assert listed_paths == actual_paths
    assert not (destination / bundle.LEGACY_CONTENT_MANIFEST_NAME).exists()
    record = bundle.build_record(inventory, manifest_path)
    assert record["external_content_manifest"] == manifest_path.name
    assert record["content_manifest_sha256"] == bundle.sha256_file(manifest_path)
    assert manifest_path.name not in {
        item["path"] for item in sidecar["included_files"]
    }


def test_content_manifest_supplies_verified_archive_membership(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    destination = tmp_path / "submission"
    _write(repository / "evidence.json", '{"decision":"preserved"}\n')
    include_path = repository / "include.txt"
    exclude_path = repository / "exclude.txt"
    _write(include_path, "evidence.json\n")
    _write(exclude_path, "ignored/\n")
    inventory = bundle.build_inventory(
        repository_root=repository,
        include_manifest=include_path,
        exclude_manifest=exclude_path,
        builder_source=Path(bundle.__file__),
        candidate_paths=("evidence.json",),
    )
    bundle.build_bundle(repository, destination, inventory)
    assert bundle.is_verified_bundle_member(destination, "evidence.json")
    (destination / "evidence.json").write_text("changed\n", encoding="utf-8")
    assert not bundle.is_verified_bundle_member(destination, "evidence.json")
    _assert_git_inventory_reads_candidate_index_without_external_manifest(tmp_path)
    _assert_archive_inventory_uses_external_manifest(tmp_path)
    _assert_git_and_manifest_inventories_normalise_identically(tmp_path)
    _assert_repository_inventory_fails_without_git_or_manifest(tmp_path)
