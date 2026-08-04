"""Result-blind calibration boundary for the final oracle-delay registry.

The implemented simulation parameter is a global, integer lag applied to every
collateral market-price path.  This module inventories repository-resident
evidence and implements the pre-registered evidence hierarchy without
executing an experiment or changing a runtime profile.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import csv
import io
import json
from pathlib import Path
from typing import Any

import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ORACLE_DELAY_PARENT_COMMIT = "d2e4b846cb9d7592bbf457e5c2a991671585a8c6"
PROGRAMME_IDENTITY = (
    "084dd8495ec29717a94cc2d6d5427a78f377d82989abf2d119547fb1db376260"
)
PARAMETER_NAME = "SimulationConfig.oracle_delay_steps"
PARAMETER_SEMANTIC_OWNER = (
    "src/dai_sim/model/collateral_prices.py::_apply_oracle_delay"
)
SIMULATION_STEP_HOURS = Decimal("1")
SIMULATION_HORIZON_STEPS = 768
CALIBRATION_START_UTC = "2021-06-01T00:00:00Z"
CALIBRATION_END_EXCLUSIVE_UTC = "2024-07-01T00:00:00Z"
HELD_OUT_INTERVALS = (
    ("2022-11-01T00:00:00Z", "2022-11-21T00:00:00Z"),
    ("2023-03-06T00:00:00Z", "2023-03-20T00:00:00Z"),
)
DIRECT_MINIMUM_OBSERVATIONS = 30
DIRECT_MINIMUM_POSITIVE = 10
INTERVAL_MINIMUM_OBSERVATIONS = 20
MINIMUM_CALENDAR_DAYS = 3

SCIENTIFIC_CLASSIFICATIONS = {
    1: "oracle_delay_empirically_identified",
    2: "oracle_delay_partially_identified_from_update_intervals",
    3: "oracle_delay_partially_identified_from_documented_rule",
    4: "transparent_sensitivity_not_empirically_identified",
}
READINESS_CLASSIFICATIONS = {
    1: "experiment_e_ready_with_empirical_delay_registry",
    2: "experiment_e_ready_with_partial_delay_registry",
    3: "experiment_e_ready_with_partial_delay_registry",
    4: "experiment_e_ready_with_transparent_delay_sensitivity",
}
TREATMENT_IDS = (
    "oracle_delay_low",
    "oracle_delay_central",
    "oracle_delay_high",
)


@dataclass(frozen=True)
class DelayCoordinates:
    """One result-blind three-coordinate delay freeze."""

    evidence_tier: int
    source_classification: str
    readiness_classification: str
    low_steps: int
    central_steps: int
    high_steps: int
    raw_central_hours: Decimal | None
    raw_high_hours: Decimal | None
    derivation_rule: str

    def validate(self, *, horizon_steps: int = SIMULATION_HORIZON_STEPS) -> None:
        """Require the exact non-negative, unique, integer treatment contract."""
        if self.evidence_tier not in SCIENTIFIC_CLASSIFICATIONS:
            raise ValueError("Unsupported oracle-delay evidence tier.")
        if self.source_classification != SCIENTIFIC_CLASSIFICATIONS[
            self.evidence_tier
        ]:
            raise ValueError("Oracle-delay scientific classification differs.")
        if self.readiness_classification != READINESS_CLASSIFICATIONS[
            self.evidence_tier
        ]:
            raise ValueError("Oracle-delay readiness classification differs.")
        values = (self.low_steps, self.central_steps, self.high_steps)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("Oracle delays must be integer simulation steps.")
        if self.low_steps != 0:
            raise ValueError("The low oracle-delay treatment must equal zero.")
        if self.central_steps < 1:
            raise ValueError("The central oracle-delay treatment must be positive.")
        if self.high_steps <= self.central_steps:
            raise ValueError("The high oracle delay must exceed the central delay.")
        if self.high_steps >= horizon_steps:
            raise ValueError("Oracle delay exceeds the valid simulation lag buffer.")

    def treatments(self) -> tuple[tuple[str, int], ...]:
        """Return the exact ordered treatment identifiers and step values."""
        return tuple(
            zip(
                TREATMENT_IDS,
                (self.low_steps, self.central_steps, self.high_steps),
                strict=True,
            )
        )


@dataclass(frozen=True)
class SourceCandidate:
    """One repository-resident candidate oracle-delay evidence source."""

    source_identifier: str
    path: str
    source_type: str
    concept_measured: str
    collateral_coverage: str
    timestamp_column: str | None
    observation_filter: str
    calibration_status: str
    held_out: bool
    eligibility_decision: str
    exclusion_reason: str


SOURCE_CANDIDATES = (
    SourceCandidate(
        "spot_oracle_adapter_history",
        "data/protocol/raw/spot_parameter_history.csv",
        "decoded_protocol_configuration_calls",
        "oracle_adapter_mapping",
        "ETH;WBTC",
        "effective_time_utc",
        "parameter == oracle_adapter",
        "validated_protocol_history",
        False,
        "excluded_concept_mismatch",
        "Maps each ilk to an adapter but contains no observation timestamp, update interval or delay value.",
    ),
    SourceCandidate(
        "hourly_protocol_parameter_panel",
        "data/protocol/processed/hourly_protocol_parameters.csv",
        "derived_hourly_protocol_state",
        "forward_filled_oracle_adapter_and_liquidation_state",
        "ETH;WBTC",
        "timestamp_utc",
        "all rows",
        "validated_protocol_history",
        False,
        "excluded_concept_mismatch",
        "Contains effective adapter mappings rather than oracle observation or update timestamps.",
    ),
    SourceCandidate(
        "hourly_market_reference_panel",
        "data/market/processed/dune_hourly_market_prices_processed.csv",
        "processed_market_prices",
        "source_market_reference_time",
        "ETH;WBTC",
        "timestamp_utc",
        "all rows",
        "calibration_and_held_out_hours_mixed",
        True,
        "excluded_missing_oracle_timestamp",
        "Contains market reference prices only and includes held-out intervals; it cannot identify staleness alone.",
    ),
    SourceCandidate(
        "osm_hop_schema_metadata",
        "data/protocol/provenance/schema_discovery.json",
        "schema_metadata",
        "protocol_delay_getter_availability",
        "mapped OSM contracts",
        None,
        "maker_ethereum.osm_call_hop metadata entry",
        "discovery_only",
        False,
        "excluded_no_numeric_observation",
        "Documents an opportunistic hop getter but records no getter value or effective period.",
    ),
    SourceCandidate(
        "oracle_parameter_source_mapping",
        "data/protocol/provenance/parameter_source_mapping.csv",
        "acquisition_design_metadata",
        "documented_oracle_source_plan",
        "mapped OSM contracts",
        None,
        "parameter == oracle_delay_hop",
        "partial_source_design",
        False,
        "excluded_no_numeric_observation",
        "States that getter calls would be opportunistic and that full delay history was not reconstructed.",
    ),
    SourceCandidate(
        "integrated_eth_zero_delay_profile",
        "data/provenance/validation/integrated_empirical_eth/integrated_empirical_eth_profile.json",
        "validation_profile",
        "simulation_price_lag_baseline",
        "ETH",
        None,
        "oracle_delay_steps == 0",
        "transparent_runtime_baseline",
        False,
        "excluded_scenario_not_evidence",
        "The zero-delay baseline is an explicit uncalibrated design choice, not historical oracle evidence.",
    ),
    SourceCandidate(
        "historical_oracle_experiment_manifest",
        "docs/repository_restructuring_baseline_manifest.json",
        "historical_result_manifest",
        "result_generated_simulation_response",
        "legacy ETH-only simulation",
        None,
        "historical oracle_delay output inventory",
        "protected_historical_experiment",
        False,
        "excluded_result_generated",
        "Historical simulator outputs cannot identify treatment coordinates for Experiment E.",
    ),
)


def sha256_bytes(value: bytes) -> str:
    """Return a SHA-256 hexadecimal digest for bytes."""
    return sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    """Return a SHA-256 digest without loading the complete file."""
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    """Serialise compact scientific provenance deterministically."""
    return (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def csv_bytes(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> bytes:
    """Serialise records as deterministic UTF-8 CSV with LF endings."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return stream.getvalue().encode("utf-8")


def normalise_utc_timestamps(
    values: Iterable[object], *, source_timezone: str = "UTC"
) -> pd.DatetimeIndex:
    """Parse timestamps, localise naive values explicitly and return UTC."""
    parsed: list[pd.Timestamp] = []
    for value in values:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError):
            parsed.append(pd.NaT)
            continue
        if pd.isna(timestamp):
            parsed.append(pd.NaT)
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(source_timezone)
        parsed.append(timestamp.tz_convert("UTC"))
    return pd.DatetimeIndex(parsed)


def calibration_only_mask(values: Iterable[object]) -> pd.Series:
    """Return a mask that excludes both registered held-out intervals."""
    timestamps = normalise_utc_timestamps(values)
    mask = pd.Series(timestamps.notna())
    for start, end_exclusive in HELD_OUT_INTERVALS:
        mask &= ~(
            (timestamps >= pd.Timestamp(start))
            & (timestamps < pd.Timestamp(end_exclusive))
        )
    return mask


def timestamp_diagnostics(values: Iterable[object]) -> dict[str, Any]:
    """Summarise timestamp validity without silently repairing order."""
    timestamps = normalise_utc_timestamps(values)
    valid = timestamps.dropna()
    return {
        "observation_count": len(timestamps),
        "missing_timestamp_count": int(timestamps.isna().sum()),
        "duplicate_timestamp_count": int(valid.duplicated().sum()),
        "monotonic_non_decreasing": bool(valid.is_monotonic_increasing),
        "minimum_timestamp_utc": (
            "" if not len(valid) else valid.min().isoformat()
        ),
        "maximum_timestamp_utc": (
            "" if not len(valid) else valid.max().isoformat()
        ),
        "distinct_calendar_days": int(len(pd.Index(valid.date).unique())),
    }


def direct_staleness_hours(
    decision_times: Iterable[object],
    observation_times: Iterable[object],
) -> pd.Series:
    """Calculate non-negative observation staleness in hours."""
    decision = normalise_utc_timestamps(decision_times)
    observation = normalise_utc_timestamps(observation_times)
    if len(decision) != len(observation):
        raise ValueError("Decision and oracle timestamp counts must match.")
    result = pd.Series((decision - observation).total_seconds() / 3_600)
    if result.dropna().lt(0).any():
        raise ValueError("Future-dated oracle observations are ineligible.")
    return result


def update_interval_hours(update_times: Iterable[object]) -> pd.Series:
    """Return ordered update intervals in hours after exact deduplication."""
    timestamps = normalise_utc_timestamps(update_times).dropna()
    ordered = pd.DatetimeIndex(timestamps.unique()).sort_values()
    if len(ordered) < 2:
        return pd.Series(dtype=float)
    intervals = pd.Series(ordered[1:] - ordered[:-1]).dt.total_seconds() / 3_600
    if intervals.le(0).any():
        raise ValueError("Oracle update intervals must be positive.")
    return intervals


def direct_sample_sufficient(
    staleness_hours: Sequence[float], timestamps: Iterable[object]
) -> bool:
    """Apply the pre-registered direct-identification sufficiency gate."""
    values = pd.Series(staleness_hours, dtype=float).dropna()
    diagnostics = timestamp_diagnostics(timestamps)
    return bool(
        len(values) >= DIRECT_MINIMUM_OBSERVATIONS
        and values.gt(0).sum() >= DIRECT_MINIMUM_POSITIVE
        and diagnostics["distinct_calendar_days"] >= MINIMUM_CALENDAR_DAYS
        and diagnostics["monotonic_non_decreasing"]
    )


def interval_sample_sufficient(
    intervals_hours: Sequence[float], timestamps: Iterable[object]
) -> bool:
    """Apply the pre-registered update-interval sufficiency gate."""
    values = pd.Series(intervals_hours, dtype=float).dropna()
    diagnostics = timestamp_diagnostics(timestamps)
    return bool(
        len(values) >= INTERVAL_MINIMUM_OBSERVATIONS
        and diagnostics["distinct_calendar_days"] >= MINIMUM_CALENDAR_DAYS
        and diagnostics["monotonic_non_decreasing"]
    )


def hours_to_steps(hours: Decimal | float | int, step_hours: Decimal) -> int:
    """Convert non-negative hours with deterministic ceiling."""
    value = Decimal(str(hours))
    if value < 0 or step_hours <= 0:
        raise ValueError(
            "Delay must be non-negative and step duration must be positive."
        )
    return int((value / step_hours).to_integral_value(rounding=ROUND_CEILING))


def derive_coordinates(
    evidence_tier: int,
    *,
    positive_staleness_hours: Sequence[float] = (),
    update_intervals: Sequence[float] = (),
    documented_delay_hours: Decimal | float | int | None = None,
    step_hours: Decimal = SIMULATION_STEP_HOURS,
) -> DelayCoordinates:
    """Derive the three treatment coordinates from one authorised tier."""
    if evidence_tier == 1:
        positive = pd.Series(positive_staleness_hours, dtype=float).dropna()
        positive = positive[positive.gt(0)]
        if positive.empty:
            raise ValueError("Tier 1 requires positive staleness observations.")
        central_raw = Decimal(str(positive.quantile(0.50)))
        high_raw = Decimal(str(positive.quantile(0.90)))
        rule = "positive_staleness_q50_and_q90"
    elif evidence_tier == 2:
        intervals = pd.Series(update_intervals, dtype=float).dropna()
        if intervals.empty or intervals.le(0).any():
            raise ValueError("Tier 2 requires positive update intervals.")
        central_raw = Decimal("0.5") * Decimal(
            str(intervals.quantile(0.50))
        )
        high_raw = Decimal(str(intervals.quantile(0.90)))
        rule = "half_update_interval_q50_and_update_interval_q90"
    elif evidence_tier == 3:
        if documented_delay_hours is None:
            raise ValueError("Tier 3 requires a documented delay value.")
        central_raw = Decimal(str(documented_delay_hours))
        high_raw = Decimal("2") * central_raw
        if central_raw <= 0:
            raise ValueError("Documented delay must be positive.")
        rule = "documented_delay_and_twice_documented_delay"
    elif evidence_tier == 4:
        coordinates = DelayCoordinates(
            evidence_tier=4,
            source_classification=SCIENTIFIC_CLASSIFICATIONS[4],
            readiness_classification=READINESS_CLASSIFICATIONS[4],
            low_steps=0,
            central_steps=1,
            high_steps=2,
            raw_central_hours=None,
            raw_high_hours=None,
            derivation_rule="transparent_zero_one_two_step_fallback",
        )
        coordinates.validate()
        return coordinates
    else:
        raise ValueError("Unsupported oracle-delay evidence tier.")

    central_steps = max(1, hours_to_steps(central_raw, step_hours))
    high_steps = max(
        central_steps + 1,
        hours_to_steps(high_raw, step_hours),
    )
    coordinates = DelayCoordinates(
        evidence_tier=evidence_tier,
        source_classification=SCIENTIFIC_CLASSIFICATIONS[evidence_tier],
        readiness_classification=READINESS_CLASSIFICATIONS[evidence_tier],
        low_steps=0,
        central_steps=central_steps,
        high_steps=high_steps,
        raw_central_hours=central_raw,
        raw_high_hours=high_raw,
        derivation_rule=rule,
    )
    coordinates.validate()
    return coordinates


def _filtered_csv(candidate: SourceCandidate, path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    if candidate.source_identifier == "spot_oracle_adapter_history":
        frame = frame.loc[frame["parameter"].eq("oracle_adapter")]
    elif candidate.source_identifier == "oracle_parameter_source_mapping":
        frame = frame.loc[frame["parameter"].eq("oracle_delay_hop")]
    return frame


def source_inventory(
    *, repository_root: Path = REPOSITORY_ROOT
) -> list[dict[str, Any]]:
    """Inspect all pre-registered local candidates without using outcomes."""
    missing = [
        candidate for candidate in SOURCE_CANDIDATES
        if not (repository_root / candidate.path).is_file()
    ]
    if missing:
        if repository_root != REPOSITORY_ROOT:
            raise FileNotFoundError(
                f"Missing oracle-delay source: {repository_root / missing[0].path}"
            )
        frozen = (
            REPOSITORY_ROOT
            / "data/provenance/calibration/oracle_delay/"
            "oracle_delay_source_inventory.csv"
        )
        frame = pd.read_csv(frozen, keep_default_na=False)
        if len(frame) != 7 or frame["source_identifier"].duplicated().any():
            raise ValueError("Frozen oracle-delay source inventory differs.")
        return frame.to_dict(orient="records")
    rows: list[dict[str, Any]] = []
    for candidate in SOURCE_CANDIDATES:
        path = repository_root / candidate.path
        if not path.is_file():
            raise FileNotFoundError(f"Missing oracle-delay source: {path}")
        diagnostics: dict[str, Any] = {
            "observation_count": 0,
            "missing_timestamp_count": 0,
            "duplicate_timestamp_count": 0,
            "monotonic_non_decreasing": "not_applicable",
            "minimum_timestamp_utc": "",
            "maximum_timestamp_utc": "",
            "distinct_calendar_days": 0,
        }
        if path.suffix == ".csv":
            frame = _filtered_csv(candidate, path)
            diagnostics["observation_count"] = len(frame)
            if candidate.timestamp_column is not None:
                diagnostics.update(
                    timestamp_diagnostics(frame[candidate.timestamp_column])
                )
        rows.append(
            {
                **asdict(candidate),
                "file_sha256": sha256_file(path),
                "file_size_bytes": path.stat().st_size,
                "timestamp_timezone": (
                    "UTC" if candidate.timestamp_column else "not_applicable"
                ),
                "simulation_time_alignment": (
                    "hourly" if "hourly" in candidate.source_identifier else "none"
                ),
                "missingness": (
                    diagnostics["missing_timestamp_count"]
                    / diagnostics["observation_count"]
                    if candidate.timestamp_column is not None
                    and diagnostics["observation_count"]
                    else "not_applicable"
                ),
                **diagnostics,
            }
        )
    return rows


def inventory_checksum(rows: Sequence[Mapping[str, Any]]) -> str:
    """Hash the complete candidate inventory independently of CSV layout."""
    return sha256_bytes(
        json.dumps(
            list(rows), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    )


def eligible_source_checksum(rows: Sequence[Mapping[str, Any]]) -> str:
    """Hash the ordered eligible subset; the empty set is meaningful."""
    eligible = [
        dict(row)
        for row in rows
        if str(row["eligibility_decision"]).startswith("eligible")
    ]
    return sha256_bytes(
        json.dumps(eligible, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def code_identity(*, repository_root: Path = REPOSITORY_ROOT) -> str:
    """Bind the three semantic package owners without host metadata."""
    relative_paths = (
        "src/dai_sim/calibration/oracle_delay.py",
        "src/dai_sim/inputs/oracle_delay.py",
        "src/dai_sim/validation/oracle_delay.py",
    )
    payload = {
        path: sha256_file(repository_root / path) for path in relative_paths
    }
    return sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
