"""Content-addressed ownership for portable runtime sources.

Frozen scientific configurations retain their historical processed-source
paths and checksums. This module maps those provenance references to compact,
tracked runtime owners without changing the recorded scientific values. The
full processed sources are optional verification inputs and are never fetched.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Final, Mapping

import yaml


REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
RUNTIME_MAP_PATH: Final = REPOSITORY_ROOT / "config/submission/runtime_input_map.yaml"
CLASSIFICATION: Final = "portable_runtime_resolution_v2"
MIGRATION_PARENT_COMMIT: Final = "d0b59afe04321362836b9c616365df7e221c25d2"
EQUIVALENCE_CONTRACT_VERSION: Final = "full_vs_compact_exact_v1"


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of *path*."""
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_path(value: str, context: str) -> Path:
    if not value or Path(value).is_absolute():
        raise ValueError(f"{context} must be a repository-relative path.")
    path = (REPOSITORY_ROOT / value).resolve()
    try:
        path.relative_to(REPOSITORY_ROOT)
    except ValueError as exc:
        raise ValueError(f"{context} must remain inside the repository.") from exc
    return path


def _relative_source(value: Path | str) -> str:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (REPOSITORY_ROOT / path).resolve()
    try:
        return resolved.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("Historical source must remain inside the repository.") from exc


def _sha256_text(value: Any, context: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{context} must be an explicit SHA-256 value.")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{context} must be hexadecimal.") from exc
    return value


@dataclass(frozen=True)
class RuntimeSourceResolution:
    """One verified historical-to-portable runtime mapping."""

    historical_path: str
    historical_sha256: str
    role: str
    runtime_path: Path
    runtime_sha256: str
    runtime_owner_type: str
    optional_full_source_present: bool
    runtime_map_sha256: str


def load_runtime_map(path: Path = RUNTIME_MAP_PATH) -> Mapping[str, Any]:
    """Load and strictly validate the portable runtime map."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Runtime input map must be a YAML mapping.")
    if raw.get("schema_version") != 1:
        raise ValueError("Runtime input map schema version differs.")
    if raw.get("classification") != CLASSIFICATION:
        raise ValueError("Runtime input map classification differs.")
    if raw.get("network_fallback") is not False:
        raise ValueError("Runtime input map must prohibit network fallback.")
    sources = raw.get("sources")
    if not isinstance(sources, dict) or len(sources) != 3:
        raise ValueError("Runtime input map must contain exactly three sources.")
    for historical_path, entry in sources.items():
        _repository_path(str(historical_path), "historical source")
        if not isinstance(entry, dict):
            raise ValueError("Every runtime source entry must be a mapping.")
        _sha256_text(entry.get("historical_sha256"), "historical source checksum")
        if entry.get("role") not in {
            "provenance_only",
            "provenance_source_for_existing_runtime_pool",
            "compact_final_validation_paths",
        }:
            raise ValueError("Runtime source role differs.")
        if entry.get("optional_full_source_verification") is not True:
            raise ValueError("Full-source verification must remain enabled when available.")
        _validate_owner_definition(entry.get("primary_runtime_owner"), "primary")
        supporting = entry.get("supporting_runtime_owner")
        if supporting is not None:
            _validate_owner_definition(supporting, "supporting")
    return raw


def _validate_owner_definition(value: Any, context: str) -> Mapping[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} runtime owner must be a mapping.")
    required = {"path", "sha256", "owner_type"}
    if set(value) != required:
        raise ValueError(f"{context} runtime owner fields differ.")
    _repository_path(str(value["path"]), f"{context} runtime owner")
    _sha256_text(value["sha256"], f"{context} runtime owner checksum")
    if not isinstance(value["owner_type"], str) or not value["owner_type"]:
        raise ValueError(f"{context} runtime owner type must be explicit.")
    return value


def _validate_runtime_owner(value: Any, context: str) -> tuple[Path, str, str]:
    owner = _validate_owner_definition(value, context)
    path = _repository_path(owner["path"], f"{context} runtime owner")
    if not path.is_file():
        raise FileNotFoundError(f"Portable runtime owner is missing: {owner['path']}.")
    expected_sha = owner["sha256"]
    observed_sha = sha256_file(path)
    if observed_sha != expected_sha:
        raise ValueError(
            f"Portable runtime owner checksum differs for {owner['path']}: "
            f"expected {expected_sha}, observed {observed_sha}."
        )
    return path, expected_sha, owner["owner_type"]


def resolve_runtime_source(
    historical_path: Path | str,
    historical_sha256: str,
    *,
    map_path: Path = RUNTIME_MAP_PATH,
) -> RuntimeSourceResolution:
    """Resolve one frozen provenance source to a verified tracked owner."""
    relative = _relative_source(historical_path)
    expected_historical_sha = _sha256_text(
        historical_sha256, "historical source checksum"
    )
    mapping = load_runtime_map(map_path)
    sources = mapping["sources"]
    if relative not in sources:
        source = _repository_path(relative, "historical source")
        if not source.is_file():
            raise FileNotFoundError(f"Frozen source is missing: {relative}.")
        observed = sha256_file(source)
        if observed != expected_historical_sha:
            raise ValueError(
                f"Frozen source checksum differs for {relative}: "
                f"expected {expected_historical_sha}, observed {observed}."
            )
        return RuntimeSourceResolution(
            historical_path=relative,
            historical_sha256=expected_historical_sha,
            role="unmapped_frozen_source",
            runtime_path=source,
            runtime_sha256=observed,
            runtime_owner_type="historical_source",
            optional_full_source_present=True,
            runtime_map_sha256=sha256_file(map_path),
        )
    entry = sources[relative]
    registered_source_sha = _sha256_text(
        entry["historical_sha256"], "mapped historical source checksum"
    )
    if registered_source_sha != expected_historical_sha:
        raise ValueError(f"Historical checksum mapping differs for {relative}.")
    runtime_path, runtime_sha, owner_type = _validate_runtime_owner(
        entry["primary_runtime_owner"], "primary"
    )
    supporting = entry.get("supporting_runtime_owner")
    if supporting is not None:
        _validate_runtime_owner(supporting, "supporting")
    source = _repository_path(relative, "historical source")
    source_present = source.is_file()
    if source_present:
        observed_source_sha = sha256_file(source)
        if observed_source_sha != expected_historical_sha:
            raise ValueError(
                f"Optional provenance source checksum differs for {relative}: "
                f"expected {expected_historical_sha}, observed {observed_source_sha}."
            )
    return RuntimeSourceResolution(
        historical_path=relative,
        historical_sha256=expected_historical_sha,
        role=entry["role"],
        runtime_path=runtime_path,
        runtime_sha256=runtime_sha,
        runtime_owner_type=owner_type,
        optional_full_source_present=source_present,
        runtime_map_sha256=sha256_file(map_path),
    )


def portable_runtime_identity_payload() -> dict[str, Any]:
    """Return the result-independent portable runtime identity payload."""
    mapping = load_runtime_map()
    source_checksums = {
        path: entry["historical_sha256"]
        for path, entry in mapping["sources"].items()
    }
    resolver_paths = (
        "src/dai_sim/inputs/runtime_sources.py",
        "src/dai_sim/inputs/multicollateral.py",
        "src/dai_sim/validation/final_validation.py",
    )
    return {
        "schema_version": 1,
        "classification": CLASSIFICATION,
        "migration_parent_commit": MIGRATION_PARENT_COMMIT,
        "runtime_map_sha256": sha256_file(RUNTIME_MAP_PATH),
        "portable_resolver_sha256": {
            path: sha256_file(REPOSITORY_ROOT / path) for path in resolver_paths
        },
        "compact_validation_derivative_sha256": mapping["sources"][
            "data/market/processed/combined/hourly_market_gas_panel.csv"
        ]["primary_runtime_owner"]["sha256"],
        "existing_market_block_pool_sha256": mapping["sources"][
            "data/market/processed/dune_hourly_market_prices_processed.csv"
        ]["primary_runtime_owner"]["sha256"],
        "frozen_collateral_registry_sha256": mapping["sources"][
            "data/protocol/processed/hourly_protocol_parameters.csv"
        ]["primary_runtime_owner"]["sha256"],
        "historical_sources": source_checksums,
        "equivalence_contract_version": EQUIVALENCE_CONTRACT_VERSION,
        "clean_checkout_test_contract": {
            "processed_sources_required": 0,
            "network_calls": 0,
            "runtime_map_required": True,
            "content_addressed_owners_required": True,
        },
        "historical_scientific_identities_preserved": True,
        "historical_runtime_source_packaged": False,
        "scientific_value_changes": 0,
        "runtime_adopted_for_clean_checkout": True,
        "network_calls": 0,
    }


def portable_runtime_identity() -> str:
    """Return the content-addressed portable runtime identity."""
    payload = json.dumps(
        portable_runtime_identity_payload(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()
