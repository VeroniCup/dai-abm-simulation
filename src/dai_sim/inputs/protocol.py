"""Empirical protocol, vault and liquidation panel construction.

This module standardises user-supplied MakerDAO observations without estimating
simulation parameters. Source identifiers, partial field availability and
provenance are retained. Collateral classes are assigned only by explicit,
effective-dated mapping rules.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .sources import (
    AGGREGATION_RULES,
    MANIFEST_COLUMNS,
    REQUIRED_MANIFEST_VALUE_COLUMNS,
    EmpiricalFieldConfig,
    explicit_unit_conversion_from_mapping,
    parse_timestamps_to_utc,
    validate_fixed_frequency,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MODEL_COLLATERAL_TYPES = frozenset({"ETH", "BTC", "STABLE"})
MAPPING_COLUMNS = (
    "source_collateral_type",
    "model_collateral_type",
    "effective_start",
    "effective_end",
    "notes",
)

PROTOCOL_NUMERIC_FIELDS = (
    "outstanding_debt",
    "debt_ceiling",
    "liquidation_ratio",
    "liquidation_penalty",
    "stability_fee",
    "oracle_price",
    "market_price",
    "collateral_locked",
    "vault_count",
    "dust_limit",
    "close_factor",
    "auction_duration_limit",
    "auction_price_buffer",
)
VAULT_NUMERIC_FIELDS = (
    "collateral_amount",
    "collateral_value",
    "debt_dai",
    "collateral_ratio",
    "liquidation_ratio",
)
LIQUIDATION_NUMERIC_FIELDS = (
    "debt_at_risk",
    "debt_repaid",
    "collateral_sold",
    "collateral_value",
    "liquidation_penalty",
    "gas_cost_proxy",
    "keeper_reward",
    "auction_duration",
    "bad_debt",
)

PROTOCOL_COLUMNS = (
    "timestamp",
    "source_collateral_type",
    "model_collateral_type",
    *PROTOCOL_NUMERIC_FIELDS,
)
VAULT_COLUMNS = (
    "snapshot_timestamp",
    "vault_id",
    "source_collateral_type",
    "model_collateral_type",
    "collateral_amount",
    "collateral_value",
    "debt_dai",
    "collateral_ratio",
    "liquidation_ratio",
    "distance_to_liquidation",
    "collateral_ratio_source",
    "collateral_ratio_recomputed",
    "collateral_ratio_method",
)
LIQUIDATION_COLUMNS = (
    "timestamp",
    "event_id",
    "vault_id",
    "source_collateral_type",
    "model_collateral_type",
    *LIQUIDATION_NUMERIC_FIELDS,
    "successful",
)

EXPECTED_TARGET_UNITS = {
    "outstanding_debt": "DAI",
    "debt_ceiling": "DAI",
    "liquidation_ratio": "ratio",
    "liquidation_penalty": "proportion",
    "stability_fee": "proportion",
    "oracle_price": "quote_currency_per_collateral_unit",
    "market_price": "quote_currency_per_collateral_unit",
    "collateral_locked": "collateral_units",
    "vault_count": "count",
    "dust_limit": "DAI",
    "close_factor": "proportion",
    "auction_duration_limit": "seconds",
    "auction_price_buffer": "ratio",
    "collateral_amount": "collateral_units",
    "collateral_value": "DAI",
    "debt_dai": "DAI",
    "collateral_ratio": "ratio",
    "debt_at_risk": "DAI",
    "debt_repaid": "DAI",
    "collateral_sold": "collateral_units",
    "gas_cost_proxy": "DAI",
    "keeper_reward": "DAI",
    "auction_duration": "seconds",
    "bad_debt": "DAI",
}


@dataclass(frozen=True)
class PanelSourceConfig:
    """Configuration for one protocol, vault or liquidation CSV source."""

    name: str
    path: Path
    panel_kind: str
    timestamp_column: str
    source_timezone: str
    collateral_type_column: str
    fields: dict[str, EmpiricalFieldConfig]
    record_id_column: str | None = None
    vault_id_column: str | None = None
    successful_column: str | None = None
    duplicate_aggregation: str | None = None
    resample_frequency: str | None = None
    resample_aggregation: str | None = None

    def __post_init__(self) -> None:
        kind = str(self.panel_kind).strip().lower()
        if kind not in {"protocol", "vault", "liquidation"}:
            raise ValueError(f"Unsupported panel_kind '{self.panel_kind}'.")
        for label, value in (
            ("name", self.name),
            ("timestamp_column", self.timestamp_column),
            ("source_timezone", self.source_timezone),
            ("collateral_type_column", self.collateral_type_column),
        ):
            if not str(value).strip():
                raise ValueError(f"{label} is required for every {kind} source.")
        try:
            pd.Timestamp("2000-01-01").tz_localize(self.source_timezone)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid source_timezone '{self.source_timezone}' for "
                f"'{self.name}'."
            ) from exc
        allowed = {
            "protocol": set(PROTOCOL_NUMERIC_FIELDS),
            "vault": set(VAULT_NUMERIC_FIELDS),
            "liquidation": set(LIQUIDATION_NUMERIC_FIELDS),
        }[kind]
        unknown = set(self.fields) - allowed
        if unknown:
            raise ValueError(
                f"Unknown {kind} canonical fields for '{self.name}': "
                f"{sorted(unknown)}."
            )
        if kind in {"vault", "liquidation"} and not self.record_id_column:
            raise ValueError(f"record_id_column is required for {kind} sources.")
        for canonical, field in self.fields.items():
            expected = EXPECTED_TARGET_UNITS[canonical]
            if field.target_unit != expected:
                raise ValueError(
                    f"Field '{canonical}' in '{self.name}' must target explicit "
                    f"unit '{expected}', not '{field.target_unit}'."
                )
        source_columns = [field.source_column for field in self.fields.values()]
        if len(source_columns) != len(set(source_columns)):
            raise ValueError(f"Numeric source columns must map uniquely in '{self.name}'.")
        for label, rule in (
            ("duplicate_aggregation", self.duplicate_aggregation),
            ("resample_aggregation", self.resample_aggregation),
        ):
            if rule is not None and rule not in AGGREGATION_RULES:
                raise ValueError(
                    f"{label} for '{self.name}' must be one of "
                    f"{sorted(AGGREGATION_RULES)} or null."
                )
        if self.resample_frequency is not None:
            validate_fixed_frequency(self.resample_frequency)
            if self.resample_aggregation is None:
                raise ValueError(
                    f"'{self.name}' supplies resample_frequency without an "
                    "explicit resample_aggregation."
                )
        elif self.resample_aggregation is not None:
            raise ValueError(
                f"'{self.name}' supplies resample_aggregation without "
                "resample_frequency."
            )
        if kind != "protocol" and (
            self.duplicate_aggregation is not None
            or self.resample_frequency is not None
        ):
            raise ValueError(
                "Duplicate aggregation and resampling are supported only for "
                "protocol-time sources; vault and event keys must remain exact."
            )
        object.__setattr__(self, "name", str(self.name).strip())
        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "panel_kind", kind)
        object.__setattr__(self, "fields", dict(self.fields))


@dataclass(frozen=True)
class CollateralMappingRule:
    """One explicit, effective-dated source-to-model collateral mapping."""

    source_collateral_type: str
    model_collateral_type: str
    effective_start: pd.Timestamp
    effective_end: pd.Timestamp
    notes: str = ""


@dataclass(frozen=True)
class ProtocolDataConfig:
    """Complete input and output configuration for the protocol pipeline."""

    output_mode: str
    manifest_path: Path
    collateral_mapping_path: Path
    processed_data_dir: Path
    protocol_sources: tuple[PanelSourceConfig, ...]
    vault_sources: tuple[PanelSourceConfig, ...]
    liquidation_sources: tuple[PanelSourceConfig, ...]
    vault_ratio_tolerance: float = 1e-6
    liquidation_summary_frequency: str = "1D"

    def __post_init__(self) -> None:
        mode = str(self.output_mode).strip().lower()
        if mode not in {"baseline", "synthetic_validation"}:
            raise ValueError("output_mode must be 'baseline' or 'synthetic_validation'.")
        tolerance = float(self.vault_ratio_tolerance)
        if not np.isfinite(tolerance) or tolerance < 0:
            raise ValueError("vault_ratio_tolerance must be finite and non-negative.")
        frequency = validate_fixed_frequency(self.liquidation_summary_frequency)
        for label, sources in (
            ("protocol", self.protocol_sources),
            ("vault", self.vault_sources),
            ("liquidation", self.liquidation_sources),
        ):
            if not sources:
                raise ValueError(f"At least one {label} source is required.")
            names = [source.name for source in sources]
            if len(names) != len(set(names)):
                raise ValueError(f"{label} source names must be unique.")
        object.__setattr__(self, "output_mode", mode)
        object.__setattr__(self, "manifest_path", Path(self.manifest_path))
        object.__setattr__(self, "collateral_mapping_path", Path(self.collateral_mapping_path))
        object.__setattr__(self, "processed_data_dir", Path(self.processed_data_dir))
        object.__setattr__(self, "liquidation_summary_frequency", frequency)


@dataclass(frozen=True)
class ProtocolPipelineResults:
    """Detailed panels, diagnostics and descriptive summaries."""

    protocol_panel: pd.DataFrame
    vault_panel: pd.DataFrame
    liquidation_panel: pd.DataFrame
    protocol_quality: pd.DataFrame
    vault_quality: pd.DataFrame
    liquidation_quality: pd.DataFrame
    collateral_composition: pd.DataFrame
    vault_distribution: pd.DataFrame
    liquidation_outcomes: pd.DataFrame
    unmapped_collateral_types: pd.DataFrame


def _resolved_path(value: object, base_dir: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else base_dir / path


def _field_from_mapping(
    canonical: str,
    mapping: Mapping[str, Any],
) -> EmpiricalFieldConfig:
    required = ("source_column", "source_unit", "target_unit")
    missing = [name for name in required if mapping.get(name) in {None, ""}]
    if missing:
        raise ValueError(
            f"Field '{canonical}' is missing configuration: {missing}."
        )
    return EmpiricalFieldConfig(
        source_column=str(mapping["source_column"]),
        source_unit=str(mapping["source_unit"]),
        target_unit=str(mapping["target_unit"]),
        conversion=explicit_unit_conversion_from_mapping(
            mapping.get("unit_conversion")
        ),
    )


def panel_source_from_mapping(
    mapping: Mapping[str, Any],
    panel_kind: str,
    base_dir: Path,
) -> PanelSourceConfig:
    """Decode one fully specified panel-source mapping."""
    path_value = mapping.get("path")
    if path_value in {None, ""}:
        raise ValueError(f"Input path is required for {panel_kind} source.")
    raw_fields = mapping.get("columns", {})
    if not isinstance(raw_fields, Mapping):
        raise ValueError("columns must be a mapping.")
    fields: dict[str, EmpiricalFieldConfig] = {}
    for canonical, raw_field in raw_fields.items():
        if raw_field is None:
            continue
        if not isinstance(raw_field, Mapping):
            raise ValueError(f"Field '{canonical}' must be a mapping or null.")
        fields[str(canonical)] = _field_from_mapping(str(canonical), raw_field)
    return PanelSourceConfig(
        name=str(mapping.get("name") or ""),
        path=_resolved_path(path_value, base_dir),
        panel_kind=panel_kind,
        timestamp_column=str(mapping.get("timestamp_column") or ""),
        source_timezone=str(mapping.get("source_timezone") or ""),
        collateral_type_column=str(mapping.get("collateral_type_column") or ""),
        fields=fields,
        record_id_column=mapping.get("record_id_column"),
        vault_id_column=mapping.get("vault_id_column"),
        successful_column=mapping.get("successful_column"),
        duplicate_aggregation=mapping.get("duplicate_aggregation"),
        resample_frequency=mapping.get("resample_frequency"),
        resample_aggregation=mapping.get("resample_aggregation"),
    )


def load_protocol_config(
    path: Path | str = REPOSITORY_ROOT / "config/protocol/parameters.yaml",
) -> ProtocolDataConfig:
    """Load a complete real-data protocol configuration."""
    config_path = Path(path)
    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, Mapping):
        raise ValueError("Protocol configuration must decode to a mapping.")
    base_dir = REPOSITORY_ROOT
    issues = collect_baseline_configuration_issues(raw, base_dir)
    if issues:
        formatted = "\n - ".join(issues)
        raise ValueError(
            "Baseline protocol data are not configured. Supply:\n - " + formatted
        )
    return ProtocolDataConfig(
        output_mode=str(raw.get("output_mode")),
        manifest_path=_resolved_path(raw["manifest_path"], base_dir),
        collateral_mapping_path=_resolved_path(
            raw["collateral_mapping_path"], base_dir
        ),
        processed_data_dir=_resolved_path(raw["processed_data_dir"], base_dir),
        protocol_sources=tuple(
            panel_source_from_mapping(item, "protocol", base_dir)
            for item in raw.get("protocol_files", [])
        ),
        vault_sources=tuple(
            panel_source_from_mapping(item, "vault", base_dir)
            for item in raw.get("vault_files", [])
        ),
        liquidation_sources=tuple(
            panel_source_from_mapping(item, "liquidation", base_dir)
            for item in raw.get("liquidation_files", [])
        ),
        vault_ratio_tolerance=float(raw.get("vault_ratio_tolerance", 1e-6)),
        liquidation_summary_frequency=str(
            raw.get("liquidation_summary_frequency", "1D")
        ),
    )


def collect_baseline_configuration_issues(
    mapping: Mapping[str, Any],
    base_dir: Path = REPOSITORY_ROOT,
) -> list[str]:
    """List missing real-data configuration without substituting fixtures."""
    issues: list[str] = []
    if mapping.get("output_mode") != "baseline":
        issues.append("output_mode must be 'baseline'")
    for key in ("manifest_path", "collateral_mapping_path", "processed_data_dir"):
        if mapping.get(key) in {None, ""}:
            issues.append(key)
    manifest_path = mapping.get("manifest_path")
    if manifest_path not in {None, ""}:
        resolved_manifest = _resolved_path(manifest_path, base_dir)
        if not resolved_manifest.exists():
            issues.append(f"missing data manifest: {resolved_manifest}")
        else:
            manifest = pd.read_csv(resolved_manifest)
            if manifest.empty:
                issues.append("manifest_path contains no provenance records")
    for category, required in (
        ("protocol_files", ("name", "path", "timestamp_column", "source_timezone", "collateral_type_column")),
        ("vault_files", ("name", "path", "timestamp_column", "source_timezone", "collateral_type_column", "record_id_column")),
        ("liquidation_files", ("name", "path", "timestamp_column", "source_timezone", "collateral_type_column", "record_id_column")),
    ):
        sources = mapping.get(category)
        if not isinstance(sources, list) or not sources:
            issues.append(f"at least one configured {category} entry")
            continue
        for index, source in enumerate(sources):
            if not isinstance(source, Mapping):
                issues.append(f"{category}[{index}] must be a mapping")
                continue
            for field in required:
                if source.get(field) in {None, ""}:
                    issues.append(f"{category}[{index}].{field}")
            source_path = source.get("path")
            if source_path not in {None, ""}:
                resolved = _resolved_path(source_path, base_dir)
                if not resolved.exists():
                    issues.append(f"missing input file: {resolved}")
            columns = source.get("columns")
            if not isinstance(columns, Mapping) or not columns:
                issues.append(f"{category}[{index}].columns")
    mapping_path = mapping.get("collateral_mapping_path")
    if mapping_path not in {None, ""}:
        resolved_mapping = _resolved_path(mapping_path, base_dir)
        if not resolved_mapping.exists():
            issues.append(f"missing collateral mapping file: {resolved_mapping}")
        elif pd.read_csv(resolved_mapping).empty:
            issues.append(
                "collateral_mapping_path contains no approved mapping rules"
            )
    return issues


def load_collateral_mapping(path: Path | str) -> tuple[CollateralMappingRule, ...]:
    """Load and validate explicit collateral mapping rules."""
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = set(MAPPING_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Collateral mapping is missing columns: {sorted(missing)}.")
    rules: list[CollateralMappingRule] = []
    for index, row in frame.iterrows():
        source_type = row["source_collateral_type"].strip()
        model_type = row["model_collateral_type"].strip().upper()
        if not source_type:
            raise ValueError(f"Collateral mapping row {index + 2} has no source type.")
        if model_type not in MODEL_COLLATERAL_TYPES:
            raise ValueError(
                f"Collateral mapping row {index + 2} has unsupported model "
                f"type '{model_type}'."
            )
        try:
            start = pd.Timestamp(row["effective_start"])
            end = pd.Timestamp(row["effective_end"])
            if pd.isna(start) or pd.isna(end):
                raise ValueError
            start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
            end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Collateral mapping row {index + 2} requires valid effective dates."
            ) from exc
        if start > end:
            raise ValueError(
                f"Collateral mapping row {index + 2} starts after it ends."
            )
        rules.append(
            CollateralMappingRule(source_type, model_type, start, end, row["notes"].strip())
        )
    for left_index, left in enumerate(rules):
        for right in rules[left_index + 1 :]:
            if (
                left.source_collateral_type == right.source_collateral_type
                and max(left.effective_start, right.effective_start)
                <= min(left.effective_end, right.effective_end)
            ):
                raise ValueError(
                    "Overlapping effective mappings for source collateral "
                    f"'{left.source_collateral_type}'."
                )
    return tuple(rules)


def apply_collateral_mapping(
    frame: pd.DataFrame,
    timestamp_column: str,
    rules: Sequence[CollateralMappingRule],
    panel_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply exact effective-dated mappings and report every unmatched type."""
    mapped = frame.copy()
    model_types: list[object] = []
    for row in mapped.itertuples(index=False):
        source_type = str(getattr(row, "source_collateral_type"))
        timestamp = getattr(row, timestamp_column)
        matches = [
            rule
            for rule in rules
            if rule.source_collateral_type == source_type
            and rule.effective_start <= timestamp <= rule.effective_end
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Multiple mappings apply to '{source_type}' at {timestamp}."
            )
        model_types.append(matches[0].model_collateral_type if matches else pd.NA)
    mapped["model_collateral_type"] = pd.Series(model_types, dtype="string")
    unknown = mapped[mapped["model_collateral_type"].isna()]
    if unknown.empty:
        report = pd.DataFrame(
            columns=(
                "panel_name",
                "source_collateral_type",
                "first_observation",
                "last_observation",
                "observation_count",
                "reason",
            )
        )
    else:
        report = (
            unknown.groupby("source_collateral_type", dropna=False)[timestamp_column]
            .agg(first_observation="min", last_observation="max", observation_count="size")
            .reset_index()
        )
        report.insert(0, "panel_name", panel_name)
        report["reason"] = "no effective explicit mapping"
    return mapped, report


def _required_source_columns(source: PanelSourceConfig) -> set[str]:
    columns = {
        source.timestamp_column,
        source.collateral_type_column,
        *(field.source_column for field in source.fields.values()),
    }
    if source.record_id_column:
        columns.add(source.record_id_column)
    if source.vault_id_column:
        columns.add(source.vault_id_column)
    if source.successful_column:
        columns.add(source.successful_column)
    return columns


def _numeric_fields(raw: pd.DataFrame, source: PanelSourceConfig) -> pd.DataFrame:
    output = pd.DataFrame(index=raw.index)
    for canonical, field in source.fields.items():
        values = pd.to_numeric(raw[field.source_column], errors="coerce")
        invalid = raw[field.source_column].notna() & values.isna()
        if invalid.any():
            raise ValueError(
                f"Source '{source.name}' contains non-numeric values in "
                f"'{field.source_column}'."
            )
        finite = values.dropna().to_numpy(dtype=float)
        if not np.isfinite(finite).all():
            raise ValueError(
                f"Source '{source.name}' contains non-finite values in "
                f"'{field.source_column}'."
            )
        output[canonical] = field.conversion.apply(values) if field.conversion else values
    return output.astype(float)


def _parse_boolean(values: pd.Series, source_name: str) -> pd.Series:
    mapping = {
        "true": True,
        "false": False,
        "1": True,
        "0": False,
        "yes": True,
        "no": False,
    }
    result = values.astype("string").str.strip().str.lower().map(mapping)
    invalid = values.notna() & result.isna()
    if invalid.any():
        raise ValueError(f"Source '{source_name}' contains invalid successful values.")
    return result.astype("boolean")


def _validate_source_frame(raw: pd.DataFrame, source: PanelSourceConfig) -> None:
    missing = _required_source_columns(source) - set(raw.columns)
    if missing:
        raise ValueError(f"Source '{source.name}' is missing columns: {sorted(missing)}.")
    source_types = raw[source.collateral_type_column].astype("string").str.strip()
    if source_types.isna().any() or (source_types == "").any():
        raise ValueError(f"Source '{source.name}' contains blank collateral identifiers.")


def _validate_numeric_panel(frame: pd.DataFrame, panel_kind: str) -> None:
    non_negative = {
        "protocol": {
            "outstanding_debt", "debt_ceiling", "collateral_locked", "vault_count",
            "dust_limit", "auction_duration_limit",
        },
        "vault": {"collateral_amount", "collateral_value", "debt_dai"},
        "liquidation": set(LIQUIDATION_NUMERIC_FIELDS) - {"liquidation_penalty"},
    }[panel_kind]
    positive = {
        "protocol": {"liquidation_ratio", "oracle_price", "market_price", "auction_price_buffer"},
        "vault": {"liquidation_ratio"},
        "liquidation": set(),
    }[panel_kind]
    proportions = {
        "protocol": {"liquidation_penalty", "stability_fee", "close_factor"},
        "vault": set(),
        "liquidation": {"liquidation_penalty"},
    }[panel_kind]
    for field in non_negative:
        if field in frame and (frame[field].dropna() < 0).any():
            raise ValueError(f"{panel_kind} field '{field}' contains negative values.")
    for field in positive:
        if field in frame and (frame[field].dropna() <= 0).any():
            raise ValueError(f"{panel_kind} field '{field}' contains non-positive values.")
    for field in proportions:
        if field in frame and ((frame[field].dropna() < 0) | (frame[field].dropna() > 1)).any():
            raise ValueError(f"{panel_kind} field '{field}' must be in [0, 1].")


def _ensure_columns(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    complete = frame.copy()
    for column in columns:
        if column not in complete:
            complete[column] = pd.NA
    return complete.loc[:, columns]


def adapt_protocol_frame(raw: pd.DataFrame, source: PanelSourceConfig) -> pd.DataFrame:
    """Standardise one protocol-time source without mutating its raw frame."""
    _validate_source_frame(raw, source)
    timestamps = parse_timestamps_to_utc(raw[source.timestamp_column], source)
    frame = _numeric_fields(raw, source)
    frame.insert(0, "source_collateral_type", raw[source.collateral_type_column].astype(str).str.strip().to_numpy())
    frame.insert(0, "timestamp", timestamps)
    key = ["timestamp", "source_collateral_type"]
    duplicated = frame.duplicated(key, keep=False)
    if duplicated.any() and source.duplicate_aggregation is None:
        raise ValueError(
            f"Source '{source.name}' contains duplicate protocol keys; "
            "configure duplicate_aggregation explicitly."
        )
    if duplicated.any():
        frame = frame.groupby(key, as_index=False).agg(source.duplicate_aggregation)
    if source.resample_frequency is not None:
        pieces = []
        for collateral_type, group in frame.groupby("source_collateral_type"):
            numeric = group.drop(columns="source_collateral_type").set_index("timestamp")
            resampled = numeric.resample(source.resample_frequency).agg(source.resample_aggregation)
            resampled.insert(0, "source_collateral_type", collateral_type)
            pieces.append(resampled.reset_index())
        frame = pd.concat(pieces, ignore_index=True)
    frame = frame.sort_values(key).reset_index(drop=True)
    _validate_numeric_panel(frame, "protocol")
    return frame


def adapt_vault_frame(
    raw: pd.DataFrame,
    source: PanelSourceConfig,
    ratio_tolerance: float,
) -> pd.DataFrame:
    """Standardise one or more vault snapshots and derive available ratios."""
    _validate_source_frame(raw, source)
    timestamps = parse_timestamps_to_utc(raw[source.timestamp_column], source)
    frame = _numeric_fields(raw, source)
    frame.insert(0, "source_collateral_type", raw[source.collateral_type_column].astype(str).str.strip().to_numpy())
    frame.insert(0, "vault_id", raw[str(source.record_id_column)].astype("string").str.strip().to_numpy())
    frame.insert(0, "snapshot_timestamp", timestamps)
    if frame["vault_id"].isna().any() or (frame["vault_id"] == "").any():
        raise ValueError(f"Source '{source.name}' contains blank vault identifiers.")
    key = ["snapshot_timestamp", "vault_id", "source_collateral_type"]
    if frame.duplicated(key, keep=False).any():
        raise ValueError(f"Source '{source.name}' contains duplicate vault snapshot keys.")
    source_ratio = frame.get("collateral_ratio", pd.Series(np.nan, index=frame.index)).copy()
    recomputed = pd.Series(np.nan, index=frame.index, dtype=float)
    if {"collateral_value", "debt_dai"}.issubset(frame.columns):
        valid = frame["collateral_value"].notna() & frame["debt_dai"].notna() & (frame["debt_dai"] > 0)
        recomputed.loc[valid] = frame.loc[valid, "collateral_value"] / frame.loc[valid, "debt_dai"]
    comparable = source_ratio.notna() & recomputed.notna()
    disagreement = comparable & ~np.isclose(source_ratio, recomputed, rtol=ratio_tolerance, atol=ratio_tolerance)
    if disagreement.any():
        raise ValueError(
            f"Source '{source.name}' has {int(disagreement.sum())} supplied "
            "collateral ratios inconsistent with collateral value / debt."
        )
    final_ratio = recomputed.combine_first(source_ratio)
    method = pd.Series("unavailable", index=frame.index, dtype="string")
    method.loc[source_ratio.notna() & recomputed.isna()] = "source"
    method.loc[recomputed.notna() & source_ratio.isna()] = "recomputed"
    method.loc[comparable] = "recomputed_validated_against_source"
    zero_debt = frame.get("debt_dai", pd.Series(np.nan, index=frame.index)).eq(0)
    method.loc[zero_debt & source_ratio.isna()] = "undefined_zero_debt"
    frame["collateral_ratio_source"] = source_ratio
    frame["collateral_ratio_recomputed"] = recomputed
    frame["collateral_ratio"] = final_ratio
    if "liquidation_ratio" in frame:
        frame["distance_to_liquidation"] = final_ratio - frame["liquidation_ratio"]
    else:
        frame["distance_to_liquidation"] = np.nan
    frame["collateral_ratio_method"] = method
    _validate_numeric_panel(frame, "vault")
    return frame.sort_values(key).reset_index(drop=True)


def adapt_liquidation_frame(raw: pd.DataFrame, source: PanelSourceConfig) -> pd.DataFrame:
    """Standardise one liquidation-event source without inferring outcomes."""
    _validate_source_frame(raw, source)
    timestamps = parse_timestamps_to_utc(raw[source.timestamp_column], source)
    frame = _numeric_fields(raw, source)
    frame.insert(0, "source_collateral_type", raw[source.collateral_type_column].astype(str).str.strip().to_numpy())
    vault_ids = (
        raw[str(source.vault_id_column)].astype("string").str.strip()
        if source.vault_id_column else pd.Series(pd.NA, index=raw.index, dtype="string")
    )
    frame.insert(0, "vault_id", vault_ids.to_numpy())
    frame.insert(0, "event_id", raw[str(source.record_id_column)].astype("string").str.strip().to_numpy())
    frame.insert(0, "timestamp", timestamps)
    if frame["event_id"].isna().any() or (frame["event_id"] == "").any():
        raise ValueError(f"Source '{source.name}' contains blank event identifiers.")
    if source.successful_column:
        frame["successful"] = _parse_boolean(raw[source.successful_column], source.name).to_numpy()
    else:
        frame["successful"] = pd.Series(pd.NA, index=frame.index, dtype="boolean")
    key = ["timestamp", "event_id", "source_collateral_type"]
    if frame.duplicated(key, keep=False).any():
        raise ValueError(f"Source '{source.name}' contains duplicate liquidation event keys.")
    _validate_numeric_panel(frame, "liquidation")
    return frame.sort_values(key).reset_index(drop=True)


def _load_sources(
    sources: Sequence[PanelSourceConfig],
    ratio_tolerance: float,
) -> pd.DataFrame:
    pieces = []
    for source in sources:
        if not source.path.exists():
            raise FileNotFoundError(f"Configured {source.panel_kind} file does not exist: {source.path}")
        raw = pd.read_csv(source.path)
        if source.panel_kind == "protocol":
            piece = adapt_protocol_frame(raw, source)
        elif source.panel_kind == "vault":
            piece = adapt_vault_frame(raw, source, ratio_tolerance)
        else:
            piece = adapt_liquidation_frame(raw, source)
        piece["_source_name"] = source.name
        pieces.append(piece)
    if not pieces:
        raise ValueError("At least one source is required for each empirical panel.")
    return pd.concat(pieces, ignore_index=True)


def _validate_combined_keys(frame: pd.DataFrame, keys: Sequence[str], label: str) -> None:
    duplicates = frame.duplicated(list(keys), keep=False)
    if duplicates.any():
        raise ValueError(
            f"Combined {label} panel contains {int(duplicates.sum())} duplicate-key rows."
        )


def validate_panel_manifest(
    manifest: pd.DataFrame,
    sources: Sequence[PanelSourceConfig],
) -> None:
    """Require one complete provenance record for every configured raw file."""
    missing_columns = set(MANIFEST_COLUMNS) - set(manifest.columns)
    if missing_columns:
        raise ValueError(f"Data manifest is missing columns: {sorted(missing_columns)}.")
    missing_records = []
    incomplete_records = []
    for source in sources:
        matches = manifest[
            (manifest["source_name"].astype(str) == source.name)
            & (manifest["raw_filename"].astype(str) == source.path.name)
        ]
        if matches.empty:
            missing_records.append(f"{source.name}/{source.path.name}")
            continue
        complete = matches.copy()
        for column in REQUIRED_MANIFEST_VALUE_COLUMNS:
            complete = complete[
                complete[column].notna()
                & complete[column].astype(str).str.strip().ne("")
            ]
        if complete.empty:
            incomplete_records.append(f"{source.name}/{source.path.name}")
    if missing_records or incomplete_records:
        messages = []
        if missing_records:
            messages.append(f"missing records: {missing_records}")
        if incomplete_records:
            messages.append(f"incomplete records: {incomplete_records}")
        raise ValueError("Protocol data manifest validation failed; " + "; ".join(messages))


def _quality_report(
    panel: pd.DataFrame,
    sources: Sequence[PanelSourceConfig],
    canonical_fields: Sequence[str],
    timestamp_column: str,
    unmapped: pd.DataFrame,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for source in sources:
        raw_count = len(pd.read_csv(source.path))
        source_frame = panel[panel["_source_name"] == source.name]
        conversions = []
        for canonical, field in source.fields.items():
            if field.conversion:
                conversions.append(
                    f"{canonical}: {field.source_unit} * {field.conversion.factor:g} -> {field.target_unit}"
                )
            else:
                conversions.append(f"{canonical}: {field.source_unit} -> {field.target_unit} (no conversion)")
        base = {"category": "source", "source": source.name, "field": "", "notes": ""}
        for metric, value in (
            ("source_row_count", raw_count),
            ("processed_row_count", len(source_frame)),
            ("rows_removed", max(raw_count - len(source_frame), 0)),
            ("rows_added_by_resampling", max(len(source_frame) - raw_count, 0)),
            ("first_observation", source_frame[timestamp_column].min()),
            ("last_observation", source_frame[timestamp_column].max()),
            ("collateral_types_found", "|".join(sorted(source_frame["source_collateral_type"].unique()))),
            ("duplicate_keys", 0),
            ("invalid_values", 0),
            ("unit_conversions", " | ".join(conversions)),
        ):
            records.append({**base, "metric": metric, "value": value})
        records.append({
            **base,
            "category": "transformation",
            "metric": "notes",
            "value": "UTC conversion; no imputation; unavailable fields preserved",
        })
    for field in canonical_fields:
        records.append({
            "category": "missing_values",
            "source": "combined",
            "field": field,
            "metric": "missing_count",
            "value": int(panel[field].isna().sum()) if field in panel else len(panel),
            "notes": "Unavailable values are not fabricated.",
        })
    records.append({
        "category": "collateral_mapping",
        "source": "combined",
        "field": "model_collateral_type",
        "metric": "unmapped_collateral_types",
        "value": "|".join(sorted(unmapped["source_collateral_type"].unique())) if not unmapped.empty else "",
        "notes": "Unmapped identifiers require an explicit effective-dated rule.",
    })
    return pd.DataFrame(records)


def _weighted_average(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & (weights >= 0)
    if not valid.any():
        return np.nan
    if weights.loc[valid].sum() > 0:
        return float(np.average(values.loc[valid], weights=weights.loc[valid]))
    return float(values.loc[valid].mean())


def summarise_protocol_composition(panel: pd.DataFrame) -> pd.DataFrame:
    """Describe debt composition and observed risk settings by model class."""
    mapped = panel.dropna(subset=["model_collateral_type"])
    records = []
    for (timestamp, model_type), group in mapped.groupby(["timestamp", "model_collateral_type"], observed=True):
        debt = group["outstanding_debt"]
        weights = debt.fillna(0)
        records.append({
            "timestamp": timestamp,
            "model_collateral_type": model_type,
            "source_collateral_type_count": group["source_collateral_type"].nunique(),
            "outstanding_debt": debt.sum(min_count=1),
            "vault_count": group["vault_count"].sum(min_count=1),
            "liquidation_ratio_debt_weighted": _weighted_average(group["liquidation_ratio"], weights),
            "liquidation_ratio_min": group["liquidation_ratio"].min(),
            "liquidation_ratio_max": group["liquidation_ratio"].max(),
            "liquidation_penalty_debt_weighted": _weighted_average(group["liquidation_penalty"], weights),
            "liquidation_penalty_min": group["liquidation_penalty"].min(),
            "liquidation_penalty_max": group["liquidation_penalty"].max(),
        })
    summary = pd.DataFrame(records)
    if not summary.empty:
        totals = summary.groupby("timestamp")["outstanding_debt"].transform("sum")
        summary["debt_share"] = np.where(totals > 0, summary["outstanding_debt"] / totals, np.nan)
    return summary.sort_values(["timestamp", "model_collateral_type"]).reset_index(drop=True)


def _quantile(series: pd.Series, probability: float) -> float:
    return float(series.dropna().quantile(probability)) if series.notna().any() else np.nan


def summarise_vault_distributions(panel: pd.DataFrame) -> pd.DataFrame:
    """Describe vault debt, risk distance and concentration by snapshot."""
    mapped = panel.dropna(subset=["model_collateral_type"])
    records = []
    for (snapshot, model_type), group in mapped.groupby(["snapshot_timestamp", "model_collateral_type"], observed=True):
        debt = group["debt_dai"].dropna()
        total_debt = debt.sum(min_count=1)
        positive_total = pd.notna(total_debt) and total_debt > 0
        shares = debt / total_debt if positive_total else pd.Series(dtype=float)
        record = {
            "snapshot_timestamp": snapshot,
            "model_collateral_type": model_type,
            "vault_count": len(group),
            "debt_observation_count": len(debt),
            "total_debt": total_debt,
            "median_debt": debt.median() if not debt.empty else np.nan,
            "largest_vault_debt_share": shares.max() if not shares.empty else np.nan,
            "debt_hhi": float((shares ** 2).sum()) if not shares.empty else np.nan,
        }
        for name, series in (
            ("debt", group["debt_dai"]),
            ("collateral_ratio", group["collateral_ratio"]),
            ("distance_to_liquidation", group["distance_to_liquidation"]),
        ):
            for label, probability in (("q05", .05), ("q25", .25), ("q50", .5), ("q75", .75), ("q95", .95)):
                record[f"{name}_{label}"] = _quantile(series, probability)
        records.append(record)
    return pd.DataFrame(records).sort_values(["snapshot_timestamp", "model_collateral_type"]).reset_index(drop=True)


def summarise_liquidation_outcomes(
    panel: pd.DataFrame,
    frequency: str,
) -> pd.DataFrame:
    """Describe liquidation outcomes by fixed period and model class."""
    mapped = panel.dropna(subset=["model_collateral_type"]).copy()
    if mapped.empty:
        return pd.DataFrame()
    mapped["period_start"] = mapped["timestamp"].dt.floor(frequency)
    records = []
    for (period, model_type), group in mapped.groupby(["period_start", "model_collateral_type"], observed=True):
        record = {
            "period_start": period,
            "model_collateral_type": model_type,
            "event_count": len(group),
            "debt_at_risk": group["debt_at_risk"].sum(min_count=1),
            "debt_repaid": group["debt_repaid"].sum(min_count=1),
            "bad_debt": group["bad_debt"].sum(min_count=1),
            "successful_event_share": group["successful"].astype("Float64").mean(),
            "auction_duration_count": group["auction_duration"].count(),
            "auction_duration_mean": group["auction_duration"].mean(),
            "auction_duration_median": group["auction_duration"].median(),
            "auction_duration_max": group["auction_duration"].max(),
        }
        records.append(record)
    return pd.DataFrame(records).sort_values(["period_start", "model_collateral_type"]).reset_index(drop=True)


def run_protocol_pipeline(
    config: ProtocolDataConfig,
    allow_unmapped: bool = False,
) -> ProtocolPipelineResults:
    """Construct all panels, reports and descriptive summaries."""
    all_sources = (*config.protocol_sources, *config.vault_sources, *config.liquidation_sources)
    if config.output_mode == "baseline":
        if not config.manifest_path.exists():
            raise FileNotFoundError(f"Data manifest does not exist: {config.manifest_path}")
        validate_panel_manifest(pd.read_csv(config.manifest_path), all_sources)
    rules = load_collateral_mapping(config.collateral_mapping_path)
    protocol = _load_sources(config.protocol_sources, config.vault_ratio_tolerance)
    vaults = _load_sources(config.vault_sources, config.vault_ratio_tolerance)
    liquidations = _load_sources(config.liquidation_sources, config.vault_ratio_tolerance)
    protocol, protocol_unmapped = apply_collateral_mapping(protocol, "timestamp", rules, "protocol")
    vaults, vault_unmapped = apply_collateral_mapping(vaults, "snapshot_timestamp", rules, "vault")
    liquidations, liquidation_unmapped = apply_collateral_mapping(liquidations, "timestamp", rules, "liquidation")
    unmapped = pd.concat([protocol_unmapped, vault_unmapped, liquidation_unmapped], ignore_index=True)
    if not allow_unmapped and not unmapped.empty:
        types = sorted(unmapped["source_collateral_type"].unique())
        raise ValueError(
            "Unmapped collateral identifiers require explicit approval in the "
            f"mapping table: {types}."
        )
    _validate_combined_keys(protocol, ["timestamp", "source_collateral_type"], "protocol")
    _validate_combined_keys(vaults, ["snapshot_timestamp", "vault_id", "source_collateral_type"], "vault")
    _validate_combined_keys(liquidations, ["timestamp", "event_id", "source_collateral_type"], "liquidation")
    protocol_quality = _quality_report(protocol, config.protocol_sources, PROTOCOL_NUMERIC_FIELDS, "timestamp", protocol_unmapped)
    vault_quality = _quality_report(vaults, config.vault_sources, VAULT_COLUMNS[4:], "snapshot_timestamp", vault_unmapped)
    liquidation_quality = _quality_report(liquidations, config.liquidation_sources, (*LIQUIDATION_NUMERIC_FIELDS, "successful"), "timestamp", liquidation_unmapped)
    composition = summarise_protocol_composition(protocol)
    vault_distribution = summarise_vault_distributions(vaults)
    liquidation_outcomes = summarise_liquidation_outcomes(liquidations, config.liquidation_summary_frequency)
    return ProtocolPipelineResults(
        protocol_panel=_ensure_columns(protocol.drop(columns="_source_name"), PROTOCOL_COLUMNS),
        vault_panel=_ensure_columns(vaults.drop(columns="_source_name"), VAULT_COLUMNS),
        liquidation_panel=_ensure_columns(liquidations.drop(columns="_source_name"), LIQUIDATION_COLUMNS),
        protocol_quality=protocol_quality,
        vault_quality=vault_quality,
        liquidation_quality=liquidation_quality,
        collateral_composition=composition,
        vault_distribution=vault_distribution,
        liquidation_outcomes=liquidation_outcomes,
        unmapped_collateral_types=unmapped,
    )


OUTPUT_FILENAMES = {
    "protocol_panel": "protocol_time_panel.csv",
    "vault_panel": "vault_snapshot_panel.csv",
    "liquidation_panel": "liquidation_event_panel.csv",
    "protocol_quality": "protocol_data_quality_report.csv",
    "vault_quality": "vault_data_quality_report.csv",
    "liquidation_quality": "liquidation_data_quality_report.csv",
    "collateral_composition": "collateral_composition_summary.csv",
    "vault_distribution": "vault_distribution_summary.csv",
    "liquidation_outcomes": "liquidation_outcome_summary.csv",
    "unmapped_collateral_types": "unmapped_collateral_types.csv",
}


def write_protocol_outputs(results: ProtocolPipelineResults, output_dir: Path | str) -> None:
    """Write protocol outputs without touching market-panel files."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    for attribute, filename in OUTPUT_FILENAMES.items():
        getattr(results, attribute).to_csv(output_path / filename, index=False)


def _fixture_field(
    source_column: str,
    target_unit: str,
    source_unit: str | None = None,
    factor: float | None = None,
) -> EmpiricalFieldConfig:
    conversion = None
    if factor is not None:
        conversion = explicit_unit_conversion_from_mapping(
            {"operation": "multiply", "factor": factor}
        )
    return EmpiricalFieldConfig(
        source_column=source_column,
        source_unit=source_unit or target_unit,
        target_unit=target_unit,
        conversion=conversion,
    )


def create_synthetic_fixture_config() -> ProtocolDataConfig:
    """Return clearly labelled fixture-only configuration."""
    fixture_dir = REPOSITORY_ROOT / "tests/fixtures/protocol"
    protocol_source = PanelSourceConfig(
        name="synthetic_protocol",
        path=fixture_dir / "protocol_fixture.csv",
        panel_kind="protocol",
        timestamp_column="observed_at",
        source_timezone="UTC",
        collateral_type_column="ilk",
        fields={
            "outstanding_debt": _fixture_field("debt", "DAI"),
            "debt_ceiling": _fixture_field("ceiling", "DAI"),
            "liquidation_ratio": _fixture_field("liq_ratio", "ratio"),
            "liquidation_penalty": _fixture_field("penalty_pct", "proportion", "percent", .01),
            "stability_fee": _fixture_field("fee_pct", "proportion", "percent", .01),
            "oracle_price": _fixture_field("oracle", "quote_currency_per_collateral_unit"),
            "market_price": _fixture_field("market", "quote_currency_per_collateral_unit"),
            "collateral_locked": _fixture_field("locked", "collateral_units"),
            "vault_count": _fixture_field("vaults", "count"),
        },
    )
    vault_source = PanelSourceConfig(
        name="synthetic_vaults",
        path=fixture_dir / "vault_fixture.csv",
        panel_kind="vault",
        timestamp_column="snapshot_at",
        source_timezone="UTC",
        collateral_type_column="ilk",
        record_id_column="vault_key",
        fields={
            "collateral_amount": _fixture_field("collateral_amount", "collateral_units"),
            "collateral_value": _fixture_field("collateral_value", "DAI"),
            "debt_dai": _fixture_field("debt", "DAI"),
            "collateral_ratio": _fixture_field("ratio", "ratio"),
            "liquidation_ratio": _fixture_field("liq_ratio", "ratio"),
        },
    )
    liquidation_source = PanelSourceConfig(
        name="synthetic_liquidations",
        path=fixture_dir / "liquidation_fixture.csv",
        panel_kind="liquidation",
        timestamp_column="event_at",
        source_timezone="UTC",
        collateral_type_column="ilk",
        record_id_column="event_key",
        vault_id_column="vault_key",
        successful_column="successful",
        fields={
            "debt_at_risk": _fixture_field("debt_at_risk", "DAI"),
            "debt_repaid": _fixture_field("debt_repaid", "DAI"),
            "collateral_sold": _fixture_field("collateral_sold", "collateral_units"),
            "collateral_value": _fixture_field("collateral_value", "DAI"),
            "liquidation_penalty": _fixture_field("penalty_pct", "proportion", "percent", .01),
            "gas_cost_proxy": _fixture_field("gas_cost", "DAI"),
            "keeper_reward": _fixture_field("keeper_reward", "DAI"),
            "auction_duration": _fixture_field("auction_seconds", "seconds"),
            "bad_debt": _fixture_field("bad_debt", "DAI"),
        },
    )
    return ProtocolDataConfig(
        output_mode="synthetic_validation",
        manifest_path=REPOSITORY_ROOT / "data/provenance/data_manifest.csv",
        collateral_mapping_path=fixture_dir / "collateral_mapping_fixture.csv",
        processed_data_dir=REPOSITORY_ROOT / "data/processed",
        protocol_sources=(protocol_source,),
        vault_sources=(vault_source,),
        liquidation_sources=(liquidation_source,),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_output_checksums() -> dict[Path, str]:
    protected_roots = (
        REPOSITORY_ROOT / "outputs/experiments/multi_collateral",
        REPOSITORY_ROOT / "outputs/diagnostics/market/baseline",
        REPOSITORY_ROOT / "outputs/diagnostics/market/synthetic_validation",
    )
    protocol_output = (
        REPOSITORY_ROOT
        / "outputs/diagnostics/protocol/synthetic_validation"
    )
    checksums = {}
    for root in protected_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            if protocol_output in path.parents:
                continue
            checksums[path] = _sha256(path)
    return checksums


def _expect_value_error(function: Any, label: str) -> None:
    try:
        function()
    except (ValueError, FileNotFoundError):
        return
    raise AssertionError(f"Expected clear rejection for {label}.")


def run_synthetic_validation(write_outputs: bool = True) -> ProtocolPipelineResults:
    """Execute Milestone 9 software checks using synthetic files only."""
    config = create_synthetic_fixture_config()
    raw_paths = [source.path for source in (*config.protocol_sources, *config.vault_sources, *config.liquidation_sources)]
    raw_before = {path: _sha256(path) for path in raw_paths}
    protected_before = _protected_output_checksums()
    results = run_protocol_pipeline(config, allow_unmapped=True)

    # Mappings are explicit and unknown identifiers remain unclassified.
    known = results.protocol_panel.query("source_collateral_type == 'SYNTH_ETH'")
    assert set(known["model_collateral_type"]) == {"ETH"}
    assert "SYNTH_UNKNOWN" in set(results.unmapped_collateral_types["source_collateral_type"])
    assert results.protocol_panel.query("source_collateral_type == 'SYNTH_UNKNOWN'")["model_collateral_type"].isna().all()

    # Explicit percentage conversion, debt-share reconciliation and unique keys.
    assert np.isclose(known["liquidation_penalty"].iloc[0], .13)
    positive = results.collateral_composition.groupby("timestamp").filter(lambda group: group["outstanding_debt"].sum() > 0)
    share_sums = positive.groupby("timestamp")["debt_share"].sum()
    assert np.allclose(share_sums, 1.0)
    assert not results.protocol_panel.duplicated(["timestamp", "source_collateral_type"]).any()
    assert not results.vault_panel.duplicated(["snapshot_timestamp", "vault_id", "source_collateral_type"]).any()
    assert not results.liquidation_panel.duplicated(["timestamp", "event_id", "source_collateral_type"]).any()

    # Recomputed ratios and distance signs agree with direct threshold checks.
    comparable = results.vault_panel.dropna(subset=["collateral_ratio_source", "collateral_ratio_recomputed"])
    assert np.allclose(comparable["collateral_ratio_source"], comparable["collateral_ratio_recomputed"], rtol=config.vault_ratio_tolerance, atol=config.vault_ratio_tolerance)
    ratio_rows = results.vault_panel.dropna(subset=["collateral_ratio", "liquidation_ratio", "distance_to_liquidation"])
    assert np.array_equal(
        (ratio_rows["distance_to_liquidation"] < 0).to_numpy(),
        (ratio_rows["collateral_ratio"] < ratio_rows["liquidation_ratio"]).to_numpy(),
    )

    # Missing liquidation observations stay missing and summaries reconcile.
    stable_event = results.liquidation_panel.query("event_id == 'L3'").iloc[0]
    assert pd.isna(stable_event["gas_cost_proxy"]) and pd.isna(stable_event["keeper_reward"])
    mapped_protocol = results.protocol_panel.dropna(subset=["model_collateral_type"])
    assert np.isclose(results.collateral_composition["outstanding_debt"].sum(), mapped_protocol["outstanding_debt"].sum())
    mapped_vaults = results.vault_panel.dropna(subset=["model_collateral_type"])
    assert np.isclose(results.vault_distribution["total_debt"].sum(), mapped_vaults["debt_dai"].sum())
    mapped_liquidations = results.liquidation_panel.dropna(subset=["model_collateral_type"])
    for field in ("debt_at_risk", "debt_repaid", "bad_debt"):
        assert np.isclose(results.liquidation_outcomes[field].sum(), mapped_liquidations[field].sum())

    # Invalid duplicate keys, missing manifest records and incomplete baseline
    # configuration fail explicitly.
    source = config.vault_sources[0]
    duplicated = pd.read_csv(source.path)
    duplicated = pd.concat([duplicated, duplicated.iloc[[0]]], ignore_index=True)
    _expect_value_error(lambda: adapt_vault_frame(duplicated, source, config.vault_ratio_tolerance), "duplicate vault keys")
    protocol_source = config.protocol_sources[0]
    duplicated_protocol = pd.read_csv(protocol_source.path)
    duplicated_protocol = pd.concat(
        [duplicated_protocol, duplicated_protocol.iloc[[0]]], ignore_index=True
    )
    _expect_value_error(
        lambda: adapt_protocol_frame(duplicated_protocol, protocol_source),
        "duplicate protocol keys without aggregation",
    )
    _expect_value_error(
        lambda: EmpiricalFieldConfig(
            source_column="penalty_pct",
            source_unit="percent",
            target_unit="proportion",
            conversion=None,
        ),
        "implicit unit conversion",
    )
    empty_manifest = pd.DataFrame(columns=MANIFEST_COLUMNS)
    _expect_value_error(lambda: validate_panel_manifest(empty_manifest, (*config.protocol_sources, *config.vault_sources, *config.liquidation_sources)), "missing manifest records")
    _expect_value_error(lambda: load_protocol_config(), "missing baseline configuration and files")

    if write_outputs:
        write_protocol_outputs(
            results,
            REPOSITORY_ROOT
            / "outputs/diagnostics/protocol/synthetic_validation",
        )
    assert raw_before == {path: _sha256(path) for path in raw_paths}
    assert protected_before == _protected_output_checksums()
    return results


def run_baseline_protocol_pipeline(
    config_path: Path | str = REPOSITORY_ROOT / "config/protocol/parameters.yaml",
) -> ProtocolPipelineResults:
    """Run a configured real baseline and write only Milestone 9 outputs."""
    config = load_protocol_config(config_path)
    results = run_protocol_pipeline(config, allow_unmapped=False)
    write_protocol_outputs(
        results,
        REPOSITORY_ROOT / "outputs/diagnostics/protocol/baseline",
    )
    config.processed_data_dir.mkdir(parents=True, exist_ok=True)
    results.protocol_panel.to_csv(config.processed_data_dir / "protocol_time_panel.csv", index=False)
    results.vault_panel.to_csv(config.processed_data_dir / "vault_snapshot_panel.csv", index=False)
    results.liquidation_panel.to_csv(config.processed_data_dir / "liquidation_event_panel.csv", index=False)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("synthetic_validation", "baseline"), default="synthetic_validation")
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY_ROOT / "config/protocol/parameters.yaml",
    )
    arguments = parser.parse_args()
    if arguments.mode == "baseline":
        results = run_baseline_protocol_pipeline(arguments.config)
        label = "real baseline"
    else:
        results = run_synthetic_validation()
        label = "synthetic validation"
    print(
        f"Protocol data {label} passed: "
        f"{len(results.protocol_panel)} protocol rows, "
        f"{len(results.vault_panel)} vault rows and "
        f"{len(results.liquidation_panel)} liquidation rows."
    )
    if not results.unmapped_collateral_types.empty:
        types = sorted(results.unmapped_collateral_types["source_collateral_type"].unique())
        print(f"Fixture-only unmapped collateral identifiers reported: {types}")


if __name__ == "__main__":
    main()
