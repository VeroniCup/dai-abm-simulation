"""Deterministic construction of the manifest-filtered code submission.

This module owns packaging mechanics only.  It does not import or execute the
simulation, calibration, experiment, or validation layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Iterable, Sequence


LEGACY_CONTENT_MANIFEST_NAME = "SUBMISSION_CONTENT_MANIFEST.json"
CONTENT_MANIFEST_SUFFIX = ".content-manifest.json"
SCHEMA_VERSION = 1


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of *path* without modifying it."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic, newline-terminated JSON bytes."""
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def external_content_manifest_path(destination: Path) -> Path:
    """Return the default external content-manifest path for *destination*."""
    return destination.with_name(f"{destination.name}{CONTENT_MANIFEST_SUFFIX}")


def _load_content_manifest(path: Path) -> dict[str, Any]:
    inventory = json.loads(path.read_text(encoding="utf-8"))
    records = inventory["included_files"]
    if submission_bundle_identity(records) != inventory[
        "submission_bundle_identity"
    ]:
        raise ValueError("Submission content manifest identity differs.")
    return inventory


def locate_external_content_manifest(
    bundle_root: Path,
    explicit_path: Path | None = None,
) -> Path:
    """Locate one valid content manifest beside a Git-free payload root."""
    root = bundle_root.resolve()
    if explicit_path is not None:
        path = explicit_path.resolve()
        _load_content_manifest(path)
        return path

    default = external_content_manifest_path(root)
    candidates = [default] if default.is_file() else []
    candidates.extend(
        path
        for path in sorted(root.parent.glob(f"*{CONTENT_MANIFEST_SUFFIX}"))
        if path not in candidates
    )
    matches = []
    for path in candidates:
        try:
            inventory = _load_content_manifest(path)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
            continue
        records = inventory["included_files"]
        if all(
            (root / item["path"]).is_file()
            and not (root / item["path"]).is_symlink()
            and (root / item["path"]).stat().st_size == item["size_bytes"]
            and sha256_file(root / item["path"]) == item["sha256"]
            for item in records
        ):
            matches.append(path)
    if len(matches) != 1:
        raise FileNotFoundError(
            "Exactly one matching external content manifest is required; "
            f"found {len(matches)}."
        )
    return matches[0]


def load_external_content_manifest(
    bundle_root: Path,
    explicit_path: Path | None = None,
) -> dict[str, Any]:
    """Load the verified external manifest for a Git-free payload."""
    return _load_content_manifest(
        locate_external_content_manifest(bundle_root, explicit_path)
    )


def is_manifest_filtered_bundle(bundle_root: Path) -> bool:
    """Return whether *bundle_root* is a Git-free, externally bound payload."""
    root = bundle_root.resolve()
    if (root / ".git").exists():
        return False
    try:
        locate_external_content_manifest(root)
    except (FileNotFoundError, OSError, ValueError):
        return False
    return True


@dataclass(frozen=True)
class ManifestRule:
    """One normalised repository-relative include or exclude rule."""

    pattern: str
    line_number: int
    directory: bool
    glob: bool

    @property
    def literal(self) -> bool:
        """Return whether this rule names one literal path."""
        return not self.glob

    def matches(self, relative_path: str) -> bool:
        """Return whether this rule owns *relative_path*."""
        path = _normalise_relative(relative_path)
        target = self.pattern[:-1] if self.directory else self.pattern
        if not self.directory:
            if self.glob:
                return _match_posix_pattern(target, path)
            return path == target

        ancestors = _directory_ancestors(path)
        if self.glob:
            return any(_match_posix_pattern(target, item) for item in ancestors)
        return path == target or path.startswith(f"{target}/")


def _match_posix_pattern(pattern: str, value: str) -> bool:
    """Match an anchored POSIX path pattern without suffix matching.

    ``PurePath.match`` treats relative patterns as suffix patterns, so a rule
    such as ``sql/*/templates`` can otherwise select a nested
    ``other/sql/...`` path.  This matcher keeps ``*`` within one path segment
    and gives ``**`` its conventional recursive meaning.
    """
    pattern_parts = PurePosixPath(pattern).parts
    value_parts = PurePosixPath(value).parts

    def match_parts(
        remaining_pattern: tuple[str, ...],
        remaining_value: tuple[str, ...],
    ) -> bool:
        if not remaining_pattern:
            return not remaining_value
        head, *tail = remaining_pattern
        rest = tuple(tail)
        if head == "**":
            return match_parts(rest, remaining_value) or bool(
                remaining_value
            ) and match_parts(remaining_pattern, remaining_value[1:])
        return bool(remaining_value) and fnmatchcase(
            remaining_value[0], head
        ) and match_parts(rest, remaining_value[1:])

    return match_parts(pattern_parts, value_parts)


def _normalise_relative(value: str) -> str:
    text = value.replace("\\", "/").strip()
    if not text or text.startswith("/"):
        raise ValueError(f"Manifest path is empty or absolute: {value!r}.")
    path = PurePosixPath(text.rstrip("/"))
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Manifest path escapes or is not canonical: {value!r}.")
    return path.as_posix()


def _directory_ancestors(relative_path: str) -> tuple[str, ...]:
    parts = PurePosixPath(relative_path).parts
    return tuple("/".join(parts[:index]) for index in range(1, len(parts)))


def parse_manifest(path: Path) -> tuple[ManifestRule, ...]:
    """Parse comments, blank lines, literal paths, and POSIX-style globs."""
    rules: list[ManifestRule] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        directory = text.endswith("/")
        normalised = _normalise_relative(text)
        pattern = normalised + ("/" if directory else "")
        rules.append(
            ManifestRule(
                pattern=pattern,
                line_number=line_number,
                directory=directory,
                glob=any(character in pattern for character in "*?["),
            )
        )
    if not rules:
        raise ValueError(f"Manifest contains no active rules: {path}.")
    return tuple(rules)


def discover_repository_files(repository_root: Path) -> tuple[str, ...]:
    """Return tracked and authorised untracked, non-ignored files."""
    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        try:
            inventory = load_external_content_manifest(repository_root)
        except FileNotFoundError:
            raise subprocess.CalledProcessError(
                completed.returncode,
                completed.args,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        records = inventory["included_files"]
        return tuple(sorted(item["path"] for item in records))
    values = completed.stdout.decode("utf-8").split("\0")
    paths = []
    for value in values:
        if not value:
            continue
        relative = _normalise_relative(value)
        source = repository_root / relative
        if source.exists():
            paths.append(relative)
    return tuple(sorted(set(paths)))


def select_paths(
    candidate_paths: Iterable[str],
    include_rules: Sequence[ManifestRule],
    exclude_rules: Sequence[ManifestRule],
) -> tuple[str, ...]:
    """Select paths with explicit include precedence over every exclusion."""
    selected = []
    for relative in sorted({_normalise_relative(item) for item in candidate_paths}):
        if not any(rule.matches(relative) for rule in include_rules):
            continue
        # An include match is authoritative even when a parent exclusion also
        # matches.  Keeping this branch explicit documents that precedence.
        _ = any(rule.matches(relative) for rule in exclude_rules)
        selected.append(relative)
    return tuple(selected)


def _filesystem_matches(repository_root: Path, rule: ManifestRule) -> bool:
    target = rule.pattern[:-1] if rule.directory else rule.pattern
    if rule.literal:
        path = repository_root / target
        return path.is_dir() if rule.directory else path.is_file()
    return any(repository_root.glob(target))


def validate_manifest_rules(
    repository_root: Path,
    include_rules: Sequence[ManifestRule],
) -> tuple[str, ...]:
    """Reject missing literals and report unmatched include globs."""
    missing_literals = [
        rule.pattern
        for rule in include_rules
        if rule.literal and not _filesystem_matches(repository_root, rule)
    ]
    if missing_literals:
        raise FileNotFoundError(
            "Literal include paths are missing: " + ", ".join(missing_literals)
        )
    return tuple(
        rule.pattern
        for rule in include_rules
        if rule.glob and not _filesystem_matches(repository_root, rule)
    )


def _file_record(repository_root: Path, relative: str) -> dict[str, Any]:
    source = repository_root / relative
    if source.is_symlink():
        raise ValueError(f"Submission symlink is not permitted: {relative}.")
    resolved = source.resolve()
    try:
        resolved.relative_to(repository_root.resolve())
    except ValueError as exc:
        raise ValueError(f"Submission path escapes repository: {relative}.") from exc
    if not source.is_file():
        raise FileNotFoundError(f"Submission file is unavailable: {relative}.")
    mode = stat.S_IMODE(source.stat().st_mode)
    return {
        "path": relative,
        "size_bytes": source.stat().st_size,
        "sha256": sha256_file(source),
        "executable": bool(mode & 0o111),
    }


def submission_bundle_identity(files: Sequence[dict[str, Any]]) -> str:
    """Hash the ordered path, bytes, size, and executable-bit contract."""
    payload = [
        {
            "path": item["path"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
            "executable": item["executable"],
        }
        for item in files
    ]
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def build_inventory(
    *,
    repository_root: Path,
    include_manifest: Path,
    exclude_manifest: Path,
    builder_source: Path,
    candidate_paths: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return the deterministic payload inventory selected by both manifests."""
    root = repository_root.resolve()
    include_rules = parse_manifest(include_manifest)
    exclude_rules = parse_manifest(exclude_manifest)
    unmatched_globs = validate_manifest_rules(root, include_rules)
    candidates = (
        discover_repository_files(root)
        if candidate_paths is None
        else tuple(sorted({_normalise_relative(item) for item in candidate_paths}))
    )
    selected = select_paths(candidates, include_rules, exclude_rules)
    records = [_file_record(root, relative) for relative in selected]
    selected_set = set(selected)
    excluded_records = [
        _file_record(root, relative)
        for relative in candidates
        if relative not in selected_set
    ]
    identity = submission_bundle_identity(records)
    largest = sorted(
        records,
        key=lambda item: (-item["size_bytes"], item["path"]),
    )[:30]
    return {
        "schema_version": SCHEMA_VERSION,
        "classification": "manifest_filtered_code_submission_v2",
        "submission_bundle_identity": identity,
        "include_manifest_sha256": sha256_file(include_manifest),
        "exclude_manifest_sha256": sha256_file(exclude_manifest),
        "builder_source_sha256": sha256_file(builder_source),
        "included_files": records,
        "included_file_count": len(records),
        "included_total_bytes": sum(item["size_bytes"] for item in records),
        "excluded_file_count": len(excluded_records),
        "excluded_total_bytes": sum(
            item["size_bytes"] for item in excluded_records
        ),
        "largest_included_files": largest,
        "unmatched_include_globs": list(unmatched_globs),
        "symlink_count": 0,
        "absolute_path_count": 0,
        "content_manifest_location": "external_sidecar",
        "content_manifest_suffix": CONTENT_MANIFEST_SUFFIX,
    }


def build_bundle(
    repository_root: Path,
    destination: Path,
    inventory: dict[str, Any],
    *,
    content_manifest: Path | None = None,
) -> tuple[Path, Path]:
    """Atomically copy the payload and write its manifest outside the root."""
    root = repository_root.resolve()
    destination = destination.resolve()
    if destination == root or root in destination.parents:
        raise ValueError("Submission destination must be outside the repository.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if any(destination.iterdir()):
            raise FileExistsError(
                f"Submission destination contains unrelated content: {destination}."
            )
        destination.rmdir()
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.staging-",
            dir=destination.parent,
        )
    )
    try:
        for record in inventory["included_files"]:
            relative = record["path"]
            source = root / relative
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            os.chmod(target, stat.S_IMODE(source.stat().st_mode))
        os.replace(staging, destination)
        manifest_path = (
            external_content_manifest_path(destination)
            if content_manifest is None
            else content_manifest.resolve()
        )
        if manifest_path == destination or destination in manifest_path.parents:
            raise ValueError("Content manifest must remain outside the payload root.")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{manifest_path.name}.", dir=manifest_path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(canonical_json_bytes(inventory))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, manifest_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination, manifest_path


def build_record(
    inventory: dict[str, Any],
    content_manifest: Path,
) -> dict[str, Any]:
    """Return a build record binding the external manifest by name and hash."""
    return {
        **inventory,
        "external_content_manifest": content_manifest.name,
        "content_manifest_sha256": sha256_file(content_manifest),
    }


def verify_bundle(
    destination: Path,
    content_manifest: Path | None = None,
) -> dict[str, Any]:
    """Verify every copied byte, executable bit, and unexpected path."""
    root = destination.resolve()
    manifest_path = locate_external_content_manifest(root, content_manifest)
    inventory = _load_content_manifest(manifest_path)
    expected = {item["path"]: item for item in inventory["included_files"]}
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        additional = sorted(actual - set(expected))
        raise ValueError(
            f"Submission payload differs; missing={missing}, additional={additional}."
        )
    for relative, record in expected.items():
        path = root / relative
        if path.is_symlink():
            raise ValueError(f"Submission contains a symlink: {relative}.")
        if path.stat().st_size != record["size_bytes"]:
            raise ValueError(f"Submission size differs: {relative}.")
        if sha256_file(path) != record["sha256"]:
            raise ValueError(f"Submission checksum differs: {relative}.")
        executable = bool(stat.S_IMODE(path.stat().st_mode) & 0o111)
        if executable != record["executable"]:
            raise ValueError(f"Submission executable bit differs: {relative}.")
    if submission_bundle_identity(list(expected.values())) != inventory[
        "submission_bundle_identity"
    ]:
        raise ValueError("Submission bundle identity differs.")
    return {
        "status": "passed",
        "submission_bundle_identity": inventory["submission_bundle_identity"],
        "included_file_count": len(expected),
        "included_total_bytes": inventory["included_total_bytes"],
        "content_manifest_sha256": sha256_file(manifest_path),
        "content_manifest_name": manifest_path.name,
    }


def is_verified_bundle_member(bundle_root: Path, relative_path: str) -> bool:
    """Return whether a file is bound by a valid submission sidecar record.

    A code-submission archive deliberately contains no Git object database.
    This check supplies the equivalent read-only content boundary for legacy
    scientific evidence that requires proof of a committed source file.
    """
    root = bundle_root.resolve()
    try:
        inventory = load_external_content_manifest(root)
        records = inventory["included_files"]
        relative = _normalise_relative(relative_path)
        matches = [item for item in records if item["path"] == relative]
        if len(matches) != 1:
            return False
        record = matches[0]
        source = root / relative
        if not source.is_file() or source.is_symlink():
            return False
        executable = bool(stat.S_IMODE(source.stat().st_mode) & 0o111)
        return (
            source.stat().st_size == record["size_bytes"]
            and sha256_file(source) == record["sha256"]
            and executable == record["executable"]
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return False
