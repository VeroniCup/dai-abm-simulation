"""Inventory, freeze and validate the result-blind oracle-delay registry."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import runpy
import tempfile
from tempfile import TemporaryDirectory
from typing import Any

import yaml


_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
REPOSITORY_ROOT = runpy.run_path(str(_WORKFLOW_BOOTSTRAP))[
    "bootstrap_runtime"
](__file__)

from dai_sim.calibration.oracle_delay import (  # noqa: E402
    CALIBRATION_END_EXCLUSIVE_UTC,
    CALIBRATION_START_UTC,
    DIRECT_MINIMUM_OBSERVATIONS,
    DIRECT_MINIMUM_POSITIVE,
    INTERVAL_MINIMUM_OBSERVATIONS,
    MINIMUM_CALENDAR_DAYS,
    ORACLE_DELAY_PARENT_COMMIT,
    PARAMETER_NAME,
    PARAMETER_SEMANTIC_OWNER,
    PROGRAMME_IDENTITY,
    SIMULATION_HORIZON_STEPS,
    SIMULATION_STEP_HOURS,
    canonical_json_bytes,
    code_identity,
    csv_bytes,
    derive_coordinates,
    eligible_source_checksum,
    inventory_checksum,
    sha256_bytes,
    sha256_file,
    source_inventory,
)
from dai_sim.inputs.oracle_delay import registry_identity  # noqa: E402
from dai_sim.validation.oracle_delay import (  # noqa: E402
    validate_experiment_e_readiness,
)


DEFAULT_EVIDENCE_DIR = (
    REPOSITORY_ROOT / "data/provenance/calibration/oracle_delay"
)
DEFAULT_REGISTRY_PATH = (
    REPOSITORY_ROOT / "config/sensitivities/final_oracle_delay_registry.yaml"
)
DEFAULT_MANIFEST_PATH = (
    REPOSITORY_ROOT / "data/provenance/calibration/manifest.json"
)

INVENTORY_COLUMNS = (
    "source_identifier",
    "path",
    "source_type",
    "concept_measured",
    "collateral_coverage",
    "time_coverage",
    "observation_count",
    "timestamp_timezone",
    "simulation_time_alignment",
    "calibration_status",
    "held_out",
    "missingness",
    "missing_timestamp_count",
    "duplicate_timestamp_count",
    "monotonic_non_decreasing",
    "distinct_calendar_days",
    "eligibility_decision",
    "exclusion_reason",
    "observation_filter",
    "file_sha256",
    "file_size_bytes",
)
ESTIMATE_COLUMNS = (
    "collateral_or_pool",
    "source_tier",
    "sample_size",
    "positive_sample_size",
    "missingness",
    "calendar_days",
    "median_hours",
    "p90_hours",
    "units",
    "raw_central_hours",
    "raw_high_hours",
    "converted_central_steps",
    "converted_high_steps",
    "eligibility",
    "classification",
)
REGISTRY_COLUMNS = (
    "treatment_id",
    "delay_steps",
    "equivalent_hours",
    "status",
    "derivation_owner",
    "source_tier",
    "deterministic_row_checksum",
)


def _atomic_write(path: Path, value: bytes) -> None:
    """Write, flush and atomically replace one deterministic artefact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


def _time_coverage(row: dict[str, Any]) -> str:
    minimum = str(row.get("minimum_timestamp_utc") or "")
    maximum = str(row.get("maximum_timestamp_utc") or "")
    if not minimum or not maximum:
        return "not_available"
    return f"{minimum} to {maximum}"


def _inventory_rows() -> list[dict[str, Any]]:
    rows = source_inventory(repository_root=REPOSITORY_ROOT)
    for row in rows:
        row["time_coverage"] = _time_coverage(row)
    return rows


def _specification() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "objective": (
            "Freeze three result-blind, system-wide oracle-delay treatments "
            "before Experiment E."
        ),
        "parent_commit": ORACLE_DELAY_PARENT_COMMIT,
        "programme_identity": PROGRAMME_IDENTITY,
        "target_parameter": {
            "name": PARAMETER_NAME,
            "semantic_owner": PARAMETER_SEMANTIC_OWNER,
            "unit": "simulation_steps",
            "integer_required": True,
            "step_duration_hours": int(SIMULATION_STEP_HOURS),
            "global_across_collateral_families": True,
            "delayed_object": "protocol-observed collateral price",
            "initial_boundary": (
                "first market price repeated for delay_steps observations"
            ),
        },
        "concept_distinctions": [
            "oracle_update_cadence",
            "oracle_observation_staleness",
            "publication_latency",
            "protocol_imposed_delay",
            "simulation_price_lag",
            "market_to_protocol_mismatch",
        ],
        "source_hierarchy": {
            "tier_1": "direct_event_level_staleness",
            "tier_2": "oracle_update_intervals",
            "tier_3": "tracked_documented_protocol_rule",
            "tier_4": "transparent_zero_one_two_step_sensitivity",
        },
        "sample_sufficiency": {
            "tier_1_minimum_observations": DIRECT_MINIMUM_OBSERVATIONS,
            "tier_1_minimum_positive_observations": DIRECT_MINIMUM_POSITIVE,
            "tier_2_minimum_intervals": INTERVAL_MINIMUM_OBSERVATIONS,
            "minimum_calendar_days": MINIMUM_CALENDAR_DAYS,
        },
        "quantiles": {
            "central": "q50 of positive direct staleness",
            "high": "q90 of positive direct staleness",
            "tier_2_central": "0.5 times q50 update interval",
            "tier_2_high": "q90 update interval",
        },
        "rounding": (
            "deterministic ceiling to one-hour integer simulation steps; "
            "central at least one; high at least central plus one"
        ),
        "fallback": {"low_steps": 0, "central_steps": 1, "high_steps": 2},
        "calibration_boundary": {
            "start_utc": CALIBRATION_START_UTC,
            "end_exclusive_utc": CALIBRATION_END_EXCLUSIVE_UTC,
        },
        "held_out_exclusion": ["ftx", "usdc_svb"],
        "usdc_svb_used": False,
        "experiment_e_execution": False,
        "runtime_adopted": False,
        "result_blind": True,
    }


def _estimate_rows(coordinates: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for family in ("ETH", "WBTC", "STABLE", "pooled_system_wide"):
        pooled = family == "pooled_system_wide"
        rows.append(
            {
                "collateral_or_pool": family,
                "source_tier": 4,
                "sample_size": 0,
                "positive_sample_size": 0,
                "missingness": "not_applicable_no_eligible_series",
                "calendar_days": 0,
                "median_hours": "",
                "p90_hours": "",
                "units": "hours",
                "raw_central_hours": "",
                "raw_high_hours": "",
                "converted_central_steps": (
                    coordinates.central_steps if pooled else ""
                ),
                "converted_high_steps": coordinates.high_steps if pooled else "",
                "eligibility": "fallback_applied" if pooled else "no_eligible_evidence",
                "classification": coordinates.source_classification,
            }
        )
    return rows


def _registry_rows(coordinates: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    statuses = (
        "transparent_no_delay_baseline",
        "transparent_one_step_sensitivity",
        "transparent_two_step_sensitivity",
    )
    for (identifier, steps), status in zip(
        coordinates.treatments(), statuses, strict=True
    ):
        row: dict[str, Any] = {
            "treatment_id": identifier,
            "delay_steps": steps,
            "equivalent_hours": steps * int(SIMULATION_STEP_HOURS),
            "status": status,
            "derivation_owner": "dai_sim.calibration.oracle_delay",
            "source_tier": coordinates.evidence_tier,
        }
        row["deterministic_row_checksum"] = sha256_bytes(
            json.dumps(
                row, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        )
        rows.append(row)
    return rows


def _config_payload(
    *,
    coordinates: Any,
    inventory_sha256: str,
    eligible_sha256: str,
    registry_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "registry_version": "1.0.0",
        "registry_identifier": "final_oracle_delay_registry",
        "registry_identity": "pending",
        "parent_commit": ORACLE_DELAY_PARENT_COMMIT,
        "source_classification": coordinates.source_classification,
        "readiness_classification": coordinates.readiness_classification,
        "parameter_name": PARAMETER_NAME,
        "parameter_semantic_owner": PARAMETER_SEMANTIC_OWNER,
        "unit": "simulation_steps",
        "simulation_step": {
            "duration_hours": int(SIMULATION_STEP_HOURS),
            "horizon_steps": SIMULATION_HORIZON_STEPS,
        },
        "scope": {
            "global": True,
            "collateral_families": ["ETH", "BTC", "STABLE"],
            "family_specific_coordinates": False,
        },
        "evidence": {
            "tier": coordinates.evidence_tier,
            "source_inventory_path": (
                "data/provenance/calibration/oracle_delay/"
                "oracle_delay_source_inventory.csv"
            ),
            "source_inventory_sha256": inventory_sha256,
            "eligible_source_sha256": eligible_sha256,
            "eligible_observation_count": 0,
            "calibration_boundary": {
                "start_utc": CALIBRATION_START_UTC,
                "end_exclusive_utc": CALIBRATION_END_EXCLUSIVE_UTC,
            },
            "held_out_exclusion": ["ftx", "usdc_svb"],
            "held_out_observations_used": 0,
        },
        "derivation": {
            "formula": coordinates.derivation_rule,
            "rounding_rule": (
                "deterministic_ceiling_to_integer_steps_with_unique_high"
            ),
            "low_rule": "transparent_no_delay_baseline",
        },
        "treatments": {},
        "runtime_adopted": False,
    }
    for row in registry_rows:
        payload["treatments"][row["treatment_id"]] = {
            "delay_steps": row["delay_steps"],
            "equivalent_hours": row["equivalent_hours"],
            "status": row["status"],
            "source_tier": row["source_tier"],
        }
    payload["registry_identity"] = registry_identity(payload)
    return payload


def build_freeze_payloads() -> tuple[dict[str, bytes], bytes]:
    """Build all non-host-dependent freeze artefacts in memory."""
    specification = _specification()
    inventory = _inventory_rows()
    inventory_bytes = csv_bytes(inventory, INVENTORY_COLUMNS)
    inventory_sha = sha256_bytes(inventory_bytes)
    eligible_sha = eligible_source_checksum(inventory)
    coordinates = derive_coordinates(4)
    estimates = _estimate_rows(coordinates)
    registry = _registry_rows(coordinates)
    config = _config_payload(
        coordinates=coordinates,
        inventory_sha256=inventory_sha,
        eligible_sha256=eligible_sha,
        registry_rows=registry,
    )
    config_bytes = yaml.safe_dump(
        config, sort_keys=False, allow_unicode=True
    ).encode("utf-8")
    with TemporaryDirectory(prefix="oracle-delay-registry-") as directory:
        temporary_registry = Path(directory) / "registry.yaml"
        temporary_registry.write_bytes(config_bytes)
        readiness = validate_experiment_e_readiness(
            registry_path=temporary_registry
        )
    decision = {
        "schema_version": 1,
        "evidence_classification": coordinates.source_classification,
        "numerical_coordinate_set": {
            "oracle_delay_low": 0,
            "oracle_delay_central": 1,
            "oracle_delay_high": 2,
            "unit": "simulation_steps",
            "equivalent_hours": [0, 1, 2],
        },
        "limitations": [
            "No repository-resident oracle observation timestamp series exists.",
            "No repository-resident oracle update interval series exists.",
            "The tracked OSM hop metadata contains no numeric effective value.",
            "The common system-wide delay extrapolates equally to ETH, BTC and the counterfactual stable family.",
        ],
        "extrapolation_boundary": (
            "One global fixed-step lag is applied to all collateral families; "
            "the values are not historical Maker latency estimates."
        ),
        "readiness_classification": coordinates.readiness_classification,
        "experiment_e_status": "ready_but_unexecuted",
        "delay_selected": False,
        "runtime_adopted": False,
        "experiment_e_simulations": 0,
        "readiness_validation": readiness,
    }
    reproducibility = {
        "schema_version": 1,
        "parent_commit": ORACLE_DELAY_PARENT_COMMIT,
        "programme_identity": PROGRAMME_IDENTITY,
        "source_checksums": {
            row["path"]: row["file_sha256"] for row in inventory
        },
        "source_inventory_content_sha256": inventory_checksum(inventory),
        "source_inventory_file_sha256": inventory_sha,
        "eligible_source_sha256": eligible_sha,
        "registry_identity": config["registry_identity"],
        "config_sha256": sha256_bytes(config_bytes),
        "code_identity": code_identity(repository_root=REPOSITORY_ROOT),
        "deterministic_reconstruction": True,
        "network_calls": 0,
        "experiment_e_simulations": 0,
        "experiments_a_to_d_simulations": 0,
        "held_out_observations": 0,
        "usdc_svb_observations": 0,
        "runtime_adopted": False,
        "delay_selected": False,
    }
    artefacts = {
        "oracle_delay_freeze_specification.json": canonical_json_bytes(
            specification
        ),
        "oracle_delay_source_inventory.csv": inventory_bytes,
        "oracle_delay_estimates.csv": csv_bytes(estimates, ESTIMATE_COLUMNS),
        "oracle_delay_registry.csv": csv_bytes(registry, REGISTRY_COLUMNS),
        "oracle_delay_decision.json": canonical_json_bytes(decision),
        "oracle_delay_reproducibility.json": canonical_json_bytes(
            reproducibility
        ),
    }
    return artefacts, config_bytes


def _manifest_record(
    path: Path, source_inputs: list[str]
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "classification": "snapshot",
        "context": (
            "Result-blind oracle-delay freeze; transparent mechanism "
            "sensitivity only and not runtime adopted."
        ),
        "path": path.relative_to(REPOSITORY_ROOT).as_posix(),
        "producer": "workflows.calibration.oracle_delay",
        "schema": "Compact deterministic oracle-delay calibration provenance.",
        "semantic_name": path.stem,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "source_inputs": source_inputs,
    }
    if path.suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        record["dimensions"] = [
            max(0, len(rows) - 1),
            0 if not rows else len(rows[0]),
        ]
    return record


def update_manifest(evidence_dir: Path, manifest_path: Path) -> None:
    """Replace only oracle-delay records in the calibration manifest."""
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    prefix = evidence_dir.relative_to(REPOSITORY_ROOT).as_posix() + "/"
    payload["artefacts"] = [
        record
        for record in payload["artefacts"]
        if not record["path"].startswith(prefix)
    ]
    source_inputs = [candidate["path"] for candidate in _inventory_rows()]
    payload["artefacts"].extend(
        _manifest_record(path, source_inputs)
        for path in sorted(evidence_dir.iterdir())
        if path.is_file()
    )
    payload["artefacts"] = sorted(
        payload["artefacts"], key=lambda record: record["path"]
    )
    _atomic_write(manifest_path, canonical_json_bytes(payload))


def freeze(
    *,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    manifest_path: Path | None = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Write the specification first, then derive and atomically freeze."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        evidence_dir / "oracle_delay_freeze_specification.json",
        canonical_json_bytes(_specification()),
    )
    artefacts, config_bytes = build_freeze_payloads()
    for name, value in artefacts.items():
        _atomic_write(evidence_dir / name, value)
    _atomic_write(registry_path, config_bytes)
    validation = validate_experiment_e_readiness(registry_path=registry_path)
    if manifest_path is not None:
        update_manifest(evidence_dir, manifest_path)
    return {
        "mode": "freeze",
        "evidence_classification": (
            "transparent_sensitivity_not_empirically_identified"
        ),
        "readiness_classification": validation["readiness_classification"],
        "registry_identity": yaml.safe_load(
            config_bytes.decode("utf-8")
        )["registry_identity"],
        "config_sha256": sha256_bytes(config_bytes),
        "artefact_checksums": {
            name: sha256_bytes(value) for name, value in artefacts.items()
        },
        "experiment_e_simulations": 0,
        "network_calls": 0,
        "runtime_adopted": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("inventory", "estimate", "freeze", "validate", "all"),
    )
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--registry-path", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument(
        "--skip-manifest", action="store_true", help="Used for isolated reconstruction."
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.mode == "inventory":
        result = {
            "mode": "inventory",
            "sources": len(_inventory_rows()),
            "eligible_sources": 0,
        }
    elif args.mode == "estimate":
        result = {
            "mode": "estimate",
            "classification": (
                "transparent_sensitivity_not_empirically_identified"
            ),
            "coordinates_steps": [0, 1, 2],
            "written": False,
        }
    elif args.mode == "validate":
        result = validate_experiment_e_readiness(
            registry_path=args.registry_path
        )
        result["mode"] = "validate"
    else:
        result = freeze(
            evidence_dir=args.evidence_dir,
            registry_path=args.registry_path,
            manifest_path=(None if args.skip_manifest else DEFAULT_MANIFEST_PATH),
        )
        result["mode"] = args.mode
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
