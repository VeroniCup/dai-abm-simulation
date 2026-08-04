"""Contracts for the deterministic manifest-filtered code submission."""

from __future__ import annotations

import json
from pathlib import Path

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


def _repository_inventory() -> dict[str, object]:
    if not INCLUDE.is_file() or not EXCLUDE.is_file():
        return bundle.load_external_content_manifest(REPOSITORY_ROOT)
    builder_source = BUILDER if BUILDER.is_file() else Path(bundle.__file__)
    return bundle.build_inventory(
        repository_root=REPOSITORY_ROOT,
        include_manifest=INCLUDE,
        exclude_manifest=EXCLUDE,
        builder_source=builder_source,
    )


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
