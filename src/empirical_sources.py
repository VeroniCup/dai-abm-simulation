"""Configuration-driven adapters for raw empirical CSV sources.

This module standardises provider-specific timestamps, column names, units and
frequencies before data enter the canonical transformations in
``empirical_data.py``. It contains no return, volatility or regime logic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd


CANONICAL_INPUT_COLUMNS = (
    "eth_market_price",
    "btc_market_price",
    "stable_market_price",
    "dai_market_price",
    "gas_cost_proxy",
    "liquidation_volume",
)
REQUIRED_BASELINE_COLUMNS = (
    "eth_market_price",
    "btc_market_price",
    "stable_market_price",
    "dai_market_price",
    "gas_cost_proxy",
)
PRICE_COLUMNS = (
    "eth_market_price",
    "btc_market_price",
    "stable_market_price",
    "dai_market_price",
)
NON_NEGATIVE_COLUMNS = (
    "gas_cost_proxy",
    "liquidation_volume",
)
AGGREGATION_RULES = {"mean", "first", "last"}
INVALID_UNIT_LABELS = {"", "n/a", "na", "none", "unknown", "unspecified"}
MANIFEST_COLUMNS = (
    "series_name",
    "model_variable",
    "source_name",
    "source_reference",
    "raw_filename",
    "download_date",
    "native_frequency",
    "processed_frequency",
    "currency_or_unit",
    "timezone",
    "sample_start",
    "sample_end",
    "transformation",
    "licence_or_access_note",
    "notes",
)
REQUIRED_MANIFEST_VALUE_COLUMNS = tuple(
    column for column in MANIFEST_COLUMNS if column != "notes"
)


def validate_fixed_frequency(frequency: str) -> str:
    """Return a validated fixed pandas frequency string."""
    try:
        offset = pd.tseries.frequencies.to_offset(frequency)
        nanos = offset.nanos
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "simulation_frequency must be a fixed pandas frequency such as "
            "'1h'."
        ) from exc
    if nanos <= 0:
        raise ValueError("simulation_frequency must be positive.")
    return offset.freqstr


@dataclass(frozen=True)
class ExplicitUnitConversion:
    """An explicit multiplicative conversion between documented units."""

    operation: str
    factor: float

    def __post_init__(self) -> None:
        operation = str(self.operation).strip().lower()
        factor = float(self.factor)
        if operation != "multiply":
            raise ValueError(
                "Only explicit multiplicative unit conversions are supported."
            )
        if not np.isfinite(factor) or factor <= 0:
            raise ValueError("Unit-conversion factors must be finite and positive.")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "factor", factor)

    def apply(self, values: pd.Series) -> pd.Series:
        """Apply the documented conversion."""
        return values * self.factor


@dataclass(frozen=True)
class EmpiricalFieldConfig:
    """Mapping and unit metadata for one canonical empirical variable."""

    source_column: str
    source_unit: str
    target_unit: str
    conversion: ExplicitUnitConversion | None = None

    def __post_init__(self) -> None:
        source_column = str(self.source_column).strip()
        source_unit = str(self.source_unit).strip()
        target_unit = str(self.target_unit).strip()
        if not source_column:
            raise ValueError("Mapped source columns must not be empty.")
        for label, unit in (
            ("source_unit", source_unit),
            ("target_unit", target_unit),
        ):
            if unit.lower() in INVALID_UNIT_LABELS:
                raise ValueError(f"{label} must be an explicit, valid unit.")
        if source_unit != target_unit and self.conversion is None:
            raise ValueError(
                "Source and target units differ, but no explicit conversion "
                f"was configured: '{source_unit}' to '{target_unit}'."
            )
        object.__setattr__(self, "source_column", source_column)
        object.__setattr__(self, "source_unit", source_unit)
        object.__setattr__(self, "target_unit", target_unit)

    @property
    def conversion_factor(self) -> float:
        """Return one when no explicit conversion is required."""
        if self.conversion is None:
            return 1.0
        return self.conversion.factor


@dataclass(frozen=True)
class EmpiricalSourceConfig:
    """Configuration for one user-supplied raw CSV source."""

    name: str
    path: Path
    timestamp_column: str
    source_timezone: str
    fields: dict[str, EmpiricalFieldConfig]
    duplicate_aggregation: str | None = None
    resample_aggregation: str | None = None

    def __post_init__(self) -> None:
        source_name = str(self.name).strip()
        timestamp_column = str(self.timestamp_column).strip()
        source_timezone = str(self.source_timezone).strip()
        if not source_name:
            raise ValueError("Empirical source names must not be empty.")
        if not timestamp_column:
            raise ValueError(
                f"timestamp_column must be supplied for source '{source_name}'."
            )
        if not source_timezone:
            raise ValueError(
                f"source_timezone must be supplied for source '{source_name}'."
            )
        try:
            pd.Timestamp("2000-01-01").tz_localize(source_timezone)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid source_timezone '{source_timezone}' for "
                f"'{source_name}'."
            ) from exc
        if not self.fields:
            raise ValueError(
                f"At least one field mapping is required for '{source_name}'."
            )

        unknown_columns = set(self.fields) - set(CANONICAL_INPUT_COLUMNS)
        if unknown_columns:
            raise ValueError(
                f"Unknown canonical columns for '{source_name}': "
                f"{sorted(unknown_columns)}."
            )
        source_columns = [field.source_column for field in self.fields.values()]
        if len(source_columns) != len(set(source_columns)):
            raise ValueError(
                f"Source columns must map uniquely for '{source_name}'."
            )
        for label, rule in (
            ("duplicate_aggregation", self.duplicate_aggregation),
            ("resample_aggregation", self.resample_aggregation),
        ):
            if rule is not None and rule not in AGGREGATION_RULES:
                raise ValueError(
                    f"{label} for '{source_name}' must be one of "
                    f"{sorted(AGGREGATION_RULES)} or null."
                )

        object.__setattr__(self, "name", source_name)
        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "timestamp_column", timestamp_column)
        object.__setattr__(self, "source_timezone", source_timezone)
        object.__setattr__(self, "fields", dict(self.fields))

    @property
    def column_mapping(self) -> dict[str, str]:
        """Return canonical-to-source column names for compatibility."""
        return {
            canonical: field.source_column
            for canonical, field in self.fields.items()
        }


def explicit_unit_conversion_from_mapping(
    mapping: Mapping[str, Any] | None,
) -> ExplicitUnitConversion | None:
    """Parse an optional explicit conversion mapping."""
    if mapping is None:
        return None
    if not isinstance(mapping, Mapping):
        raise ValueError("unit_conversion must be a mapping or null.")
    if mapping.get("operation") is None or mapping.get("factor") is None:
        raise ValueError(
            "unit_conversion requires both operation and factor."
        )
    return ExplicitUnitConversion(
        operation=str(mapping["operation"]),
        factor=float(mapping["factor"]),
    )


def empirical_source_from_mapping(
    source_mapping: Mapping[str, Any],
    base_dir: Path,
) -> EmpiricalSourceConfig:
    """Construct one validated adapter configuration from decoded YAML."""
    name = source_mapping.get("name")
    path_value = source_mapping.get("path")
    timestamp_column = source_mapping.get("timestamp_column")
    source_timezone = source_mapping.get("source_timezone")
    if path_value is None or str(path_value).strip() == "":
        raise ValueError(f"Input path must be supplied for source '{name}'.")
    if timestamp_column is None or str(timestamp_column).strip() == "":
        raise ValueError(
            f"timestamp_column must be supplied for source '{name}'."
        )
    if source_timezone is None or str(source_timezone).strip() == "":
        raise ValueError(
            f"source_timezone must be supplied for source '{name}'."
        )

    path = Path(str(path_value))
    if not path.is_absolute():
        path = base_dir / path
    raw_columns = source_mapping.get("columns")
    if not isinstance(raw_columns, Mapping):
        raise ValueError(f"columns must be a mapping for source '{name}'.")

    fields = {}
    for canonical, field_mapping in raw_columns.items():
        if field_mapping is None:
            continue
        if not isinstance(field_mapping, Mapping):
            raise ValueError(
                f"Column '{canonical}' for source '{name}' must use the "
                "documented field mapping."
            )
        source_column = field_mapping.get("source_column")
        source_unit = field_mapping.get("source_unit")
        target_unit = field_mapping.get("target_unit")
        if source_column is None or source_unit is None or target_unit is None:
            raise ValueError(
                f"Column '{canonical}' for source '{name}' requires "
                "source_column, source_unit and target_unit."
            )
        fields[str(canonical)] = EmpiricalFieldConfig(
            source_column=str(source_column),
            source_unit=str(source_unit),
            target_unit=str(target_unit),
            conversion=explicit_unit_conversion_from_mapping(
                field_mapping.get("unit_conversion")
            ),
        )

    return EmpiricalSourceConfig(
        name=str(name) if name is not None else "",
        path=path,
        timestamp_column=str(timestamp_column),
        source_timezone=str(source_timezone),
        fields=fields,
        duplicate_aggregation=source_mapping.get("duplicate_aggregation"),
        resample_aggregation=source_mapping.get("resample_aggregation"),
    )


def parse_timestamps_to_utc(
    values: pd.Series,
    source: Any,
) -> pd.DatetimeIndex:
    """Parse source timestamps and convert every observation to UTC.

    ``source`` must expose ``name`` and ``source_timezone`` attributes. This
    deliberately small interface allows market, protocol, vault and
    liquidation adapters to share identical timezone handling.
    """
    parsed = []
    invalid = 0
    for value in values:
        try:
            timestamp = pd.Timestamp(value)
            if pd.isna(timestamp):
                raise ValueError
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize(source.source_timezone)
            timestamp = timestamp.tz_convert("UTC")
        except (TypeError, ValueError):
            invalid += 1
            parsed.append(pd.NaT)
        else:
            parsed.append(timestamp)
    if invalid:
        raise ValueError(
            f"Source '{source.name}' contains {invalid} invalid or ambiguous "
            "timestamps."
        )
    return pd.DatetimeIndex(parsed, name="timestamp")


def _quality_record(
    category: str,
    metric: str,
    value: object,
    source: str,
    field: str = "",
    notes: str = "",
) -> dict[str, object]:
    """Build one adapter data-quality record."""
    return {
        "category": category,
        "source": source,
        "field": field,
        "metric": metric,
        "value": value,
        "notes": notes,
    }


def adapt_source_frame(
    raw: pd.DataFrame,
    source: EmpiricalSourceConfig,
    simulation_frequency: str,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Standardise one raw frame without mutating it or filling observations."""
    frequency = validate_fixed_frequency(simulation_frequency)
    required_columns = {
        source.timestamp_column,
        *source.column_mapping.values(),
    }
    missing_columns = required_columns - set(raw.columns)
    if missing_columns:
        raise ValueError(
            f"Source '{source.name}' is missing columns: "
            f"{sorted(missing_columns)}."
        )

    timestamps = parse_timestamps_to_utc(
        raw[source.timestamp_column],
        source,
    )
    frame = pd.DataFrame(index=timestamps)
    conversion_notes = []
    for canonical, field in source.fields.items():
        original = raw[field.source_column]
        numeric = pd.to_numeric(original, errors="coerce")
        invalid_numeric = original.notna() & numeric.isna()
        if invalid_numeric.any():
            raise ValueError(
                f"Source '{source.name}' contains non-numeric values in "
                f"'{field.source_column}'."
            )
        finite_values = numeric.dropna().to_numpy(dtype=float)
        if not np.isfinite(finite_values).all():
            raise ValueError(
                f"Source '{source.name}' contains non-finite values in "
                f"'{field.source_column}'."
            )
        converted = numeric.astype(float)
        if field.conversion is not None:
            converted = field.conversion.apply(converted)
            conversion_notes.append(
                f"{canonical}: multiplied by {field.conversion.factor:g} "
                f"({field.source_unit} to {field.target_unit})"
            )
        else:
            conversion_notes.append(
                f"{canonical}: no conversion ({field.source_unit})"
            )
        frame[canonical] = converted.to_numpy(dtype=float)

    for column in PRICE_COLUMNS:
        if column in frame and (frame[column].dropna() <= 0).any():
            raise ValueError(
                f"Source '{source.name}' contains non-positive values in "
                f"'{column}'."
            )
    for column in NON_NEGATIVE_COLUMNS:
        if column in frame and (frame[column].dropna() < 0).any():
            raise ValueError(
                f"Source '{source.name}' contains negative values in "
                f"'{column}'."
            )

    duplicated_observations = int(frame.index.duplicated(keep=False).sum())
    duplicate_rows_removed = int(frame.index.duplicated(keep="first").sum())
    if duplicated_observations and source.duplicate_aggregation is None:
        raise ValueError(
            f"Source '{source.name}' contains duplicated timestamps; set an "
            "explicit duplicate_aggregation rule to aggregate them."
        )
    if duplicated_observations:
        frame = frame.groupby(level="timestamp").agg(
            source.duplicate_aggregation
        )

    frame = frame.sort_index()
    if frame.empty:
        raise ValueError(f"Source '{source.name}' contains no observations.")

    resample_rows_aggregated = 0
    if source.resample_aggregation is None:
        aligned_index = frame.index.floor(frequency)
        if not frame.index.equals(aligned_index):
            raise ValueError(
                f"Source '{source.name}' contains timestamps off the "
                f"{frequency} grid; set an explicit resample_aggregation rule."
            )
    else:
        occupied_bins = int(frame.index.floor(frequency).nunique())
        resample_rows_aggregated = int(len(frame) - occupied_bins)
        frame = frame.resample(frequency).agg(source.resample_aggregation)

    expected_index = pd.date_range(
        start=frame.index.min(),
        end=frame.index.max(),
        freq=frequency,
        tz="UTC",
    )
    missing_expected = expected_index.difference(frame.index).union(
        frame.index[frame.isna().all(axis=1)]
    )
    rows_removed = duplicate_rows_removed + resample_rows_aggregated
    notes = [
        f"naive timestamps interpreted as {source.source_timezone}",
        "timestamps converted to UTC",
        f"aligned to {frequency}",
        "no forward filling or interpolation",
        *conversion_notes,
    ]
    if source.duplicate_aggregation is not None:
        notes.append(
            "duplicate timestamps aggregated with "
            f"{source.duplicate_aggregation}"
        )
    if source.resample_aggregation is not None:
        notes.append(
            f"observations resampled with {source.resample_aggregation}"
        )

    quality = [
        _quality_record(
            "source",
            "source_row_count",
            int(len(raw)),
            source=source.name,
        ),
        _quality_record(
            "source",
            "processed_source_rows",
            int(len(frame)),
            source=source.name,
        ),
        _quality_record(
            "source",
            "coverage_start",
            frame.index.min().isoformat(),
            source=source.name,
        ),
        _quality_record(
            "source",
            "coverage_end",
            frame.index.max().isoformat(),
            source=source.name,
        ),
        _quality_record(
            "duplicates",
            "duplicated_timestamp_observations",
            duplicated_observations,
            source=source.name,
        ),
        _quality_record(
            "duplicates",
            "duplicate_rows_aggregated",
            duplicate_rows_removed,
            source=source.name,
        ),
        _quality_record(
            "alignment",
            "missing_expected_intervals",
            int(len(missing_expected)),
            source=source.name,
        ),
        _quality_record(
            "rows",
            "rows_removed",
            rows_removed,
            source=source.name,
            notes=(
                "Rows are removed only by explicitly configured duplicate or "
                "resampling aggregation."
            ),
        ),
        _quality_record(
            "transformation",
            "transformation_notes",
            "; ".join(notes),
            source=source.name,
        ),
    ]
    return frame, quality


def _safe_source_filename(source_name: str) -> str:
    """Return a filesystem-safe deterministic source label."""
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", source_name).strip("_")
    if not safe_name:
        raise ValueError("Source name cannot be converted to a safe filename.")
    return safe_name.lower()


def load_and_align_sources(
    sources: Sequence[EmpiricalSourceConfig],
    simulation_frequency: str,
    standardised_output_dir: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load, adapt and align configured sources on a complete UTC time grid."""
    frequency = validate_fixed_frequency(simulation_frequency)
    source_frames = []
    quality_records: list[dict[str, object]] = []
    mapped_columns: set[str] = set()

    for source in sources:
        if not source.path.exists():
            raise FileNotFoundError(
                "Configured empirical input file does not exist for "
                f"source '{source.name}': {source.path}."
            )
        raw = pd.read_csv(source.path)
        frame, source_quality = adapt_source_frame(raw, source, frequency)
        overlapping_columns = mapped_columns & set(frame.columns)
        if overlapping_columns:
            raise ValueError(
                "Canonical empirical columns may only be supplied once; "
                f"duplicates: {sorted(overlapping_columns)}."
            )
        mapped_columns.update(frame.columns)
        source_frames.append(frame)
        quality_records.extend(source_quality)

        if standardised_output_dir is not None:
            output_dir = Path(standardised_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = f"standardised_{_safe_source_filename(source.name)}.csv"
            frame.reset_index().to_csv(output_dir / filename, index=False)

    combined = pd.concat(source_frames, axis=1, join="outer").sort_index()
    expected_index = pd.date_range(
        start=combined.index.min(),
        end=combined.index.max(),
        freq=frequency,
        tz="UTC",
    )
    missing_expected = expected_index.difference(combined.index).union(
        combined.index[combined.isna().all(axis=1)]
    )
    combined = combined.reindex(expected_index)
    combined.index.name = "timestamp"
    quality_records.extend(
        [
            _quality_record(
                "alignment",
                "missing_expected_intervals",
                int(len(missing_expected)),
                source="combined",
                notes="Intervals absent from every source before reindexing.",
            ),
            _quality_record(
                "transformation",
                "transformation_notes",
                (
                    "Outer alignment on the configured grid; missing intervals "
                    "retained; no forward filling or interpolation."
                ),
                source="combined",
            ),
        ]
    )
    return combined, pd.DataFrame(quality_records)


def validate_manifest_records(
    sources: Sequence[EmpiricalSourceConfig],
    simulation_frequency: str,
    manifest: pd.DataFrame,
) -> None:
    """Validate provenance records for every configured source series."""
    missing_columns = set(MANIFEST_COLUMNS) - set(manifest.columns)
    if missing_columns:
        raise ValueError(
            "Data manifest is missing columns: "
            f"{sorted(missing_columns)}."
        )
    frequency = validate_fixed_frequency(simulation_frequency)
    errors = []

    for source in sources:
        for canonical, field in source.fields.items():
            records = manifest.loc[
                (manifest["source_name"].astype(str) == source.name)
                & (manifest["model_variable"].astype(str) == canonical)
            ]
            record_label = f"{source.name}/{canonical}"
            if records.empty:
                errors.append(f"missing manifest record: {record_label}")
                continue
            if len(records) > 1:
                errors.append(f"duplicate manifest records: {record_label}")
                continue
            record = records.iloc[0]
            empty_fields = [
                column
                for column in REQUIRED_MANIFEST_VALUE_COLUMNS
                if pd.isna(record[column]) or str(record[column]).strip() == ""
            ]
            if empty_fields:
                errors.append(
                    f"incomplete manifest record {record_label}: "
                    f"{', '.join(empty_fields)}"
                )
            if str(record["raw_filename"]).strip() != source.path.name:
                errors.append(
                    f"raw_filename mismatch for {record_label}: expected "
                    f"{source.path.name}"
                )
            processed_frequency = str(record["processed_frequency"]).strip()
            try:
                manifest_frequency = validate_fixed_frequency(
                    processed_frequency
                )
            except ValueError:
                errors.append(
                    f"invalid processed_frequency for {record_label}: "
                    f"{processed_frequency}"
                )
            else:
                if manifest_frequency != frequency:
                    errors.append(
                        f"processed_frequency mismatch for {record_label}: "
                        f"expected {frequency}"
                    )
            if str(record["currency_or_unit"]).strip() != field.source_unit:
                errors.append(
                    f"currency_or_unit mismatch for {record_label}: expected "
                    f"{field.source_unit}"
                )
            if str(record["timezone"]).strip() != source.source_timezone:
                errors.append(
                    f"timezone mismatch for {record_label}: expected "
                    f"{source.source_timezone}"
                )

    if errors:
        raise ValueError(
            "Data manifest validation failed:\n- " + "\n- ".join(errors)
        )


def validate_data_manifest(
    sources: Sequence[EmpiricalSourceConfig],
    simulation_frequency: str,
    manifest_path: Path,
) -> None:
    """Load and validate the configured provenance manifest."""
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Data manifest does not exist: {path}.")
    manifest = pd.read_csv(path, dtype=str)
    validate_manifest_records(sources, simulation_frequency, manifest)
