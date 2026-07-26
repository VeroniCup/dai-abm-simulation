"""
Empirical market-data alignment and two-state regime classification.

This module is deliberately independent of the simulation engine. It prepares
timestamp-aligned observations for later calibration and moving-block bootstrap
work without changing any simulation parameter or economic equation.

Run the executable synthetic validation with:

    python src/empirical_data.py

The bundled fixture is synthetic and must not be interpreted as an empirical
result.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
import yaml

try:
    from empirical_sources import (
        CANONICAL_INPUT_COLUMNS,
        MANIFEST_COLUMNS,
        PRICE_COLUMNS,
        REQUIRED_BASELINE_COLUMNS,
        EmpiricalFieldConfig,
        EmpiricalSourceConfig,
        ExplicitUnitConversion,
        adapt_source_frame,
        empirical_source_from_mapping,
        load_and_align_sources,
        validate_data_manifest,
        validate_fixed_frequency,
        validate_manifest_records,
    )
except ModuleNotFoundError:
    from .empirical_sources import (
        CANONICAL_INPUT_COLUMNS,
        MANIFEST_COLUMNS,
        PRICE_COLUMNS,
        REQUIRED_BASELINE_COLUMNS,
        EmpiricalFieldConfig,
        EmpiricalSourceConfig,
        ExplicitUnitConversion,
        adapt_source_frame,
        empirical_source_from_mapping,
        load_and_align_sources,
        validate_data_manifest,
        validate_fixed_frequency,
        validate_manifest_records,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "empirical.yaml"
EMPIRICAL_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "empirical"
SYNTHETIC_OUTPUT_DIR = EMPIRICAL_OUTPUT_DIR / "synthetic_validation"
BASELINE_OUTPUT_DIR = EMPIRICAL_OUTPUT_DIR / "baseline"
DEFAULT_OUTPUT_DIR = SYNTHETIC_OUTPUT_DIR
DEFAULT_PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
SYNTHETIC_FIXTURE_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "empirical_market_fixture.csv"
)

POOL_COLUMNS = (
    "eth_log_return",
    "btc_log_return",
    "stable_log_return",
    "gas_cost_proxy",
)


def _normalise_timestamp(value: object, label: str) -> pd.Timestamp:
    """Parse one required timestamp and normalise it to UTC."""
    if value is None or str(value).strip() == "":
        raise ValueError(f"{label} must be supplied.")

    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not a valid timestamp: {value!r}.") from exc

    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _frequency_timedelta(frequency: str) -> pd.Timedelta:
    """Convert a validated fixed frequency into a timedelta."""
    offset = pd.tseries.frequencies.to_offset(frequency)
    return pd.Timedelta(offset.nanos, unit="ns")


@dataclass(frozen=True)
class EmpiricalConfig:
    """Configuration for empirical alignment and regime estimation."""

    simulation_frequency: str
    calibration_start: pd.Timestamp
    calibration_end: pd.Timestamp
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp
    sources: tuple[EmpiricalSourceConfig, ...]
    rolling_volatility_window: int = 24
    return_lower_quantile: float = 0.05
    volatility_upper_quantile: float = 0.90
    gas_upper_quantile: float = 0.90
    dai_peg_upper_quantile: float = 0.90
    liquidation_upper_quantile: float = 0.90
    minimum_stress_conditions: int = 2
    data_label: str = "user_supplied_empirical_data"
    output_mode: str = "baseline"
    output_timezone: str = "UTC"
    manifest_path: Path | None = None
    processed_data_dir: Path | None = None

    def __post_init__(self) -> None:
        frequency = validate_fixed_frequency(self.simulation_frequency)
        calibration_start = _normalise_timestamp(
            self.calibration_start,
            "calibration start",
        )
        calibration_end = _normalise_timestamp(
            self.calibration_end,
            "calibration end",
        )
        validation_start = _normalise_timestamp(
            self.validation_start,
            "validation start",
        )
        validation_end = _normalise_timestamp(
            self.validation_end,
            "validation end",
        )

        if calibration_start > calibration_end:
            raise ValueError("Calibration start must not follow calibration end.")
        if validation_start > validation_end:
            raise ValueError("Validation start must not follow validation end.")
        if not (
            calibration_end < validation_start
            or validation_end < calibration_start
        ):
            raise ValueError("Calibration and validation periods must not overlap.")
        for label, timestamp in (
            ("calibration start", calibration_start),
            ("calibration end", calibration_end),
            ("validation start", validation_start),
            ("validation end", validation_end),
        ):
            if timestamp.floor(frequency) != timestamp:
                raise ValueError(
                    f"{label} must align with simulation_frequency "
                    f"'{frequency}'."
                )
        if not self.sources:
            raise ValueError("At least one empirical input source is required.")
        if self.rolling_volatility_window < 2:
            raise ValueError("rolling_volatility_window must be at least 2.")
        if self.minimum_stress_conditions < 1:
            raise ValueError("minimum_stress_conditions must be positive.")

        quantiles = {
            "return_lower_quantile": self.return_lower_quantile,
            "volatility_upper_quantile": self.volatility_upper_quantile,
            "gas_upper_quantile": self.gas_upper_quantile,
            "dai_peg_upper_quantile": self.dai_peg_upper_quantile,
            "liquidation_upper_quantile": self.liquidation_upper_quantile,
        }
        for label, quantile in quantiles.items():
            if not 0.0 < float(quantile) < 1.0:
                raise ValueError(f"{label} must lie strictly between 0 and 1.")

        source_names = [source.name for source in self.sources]
        if len(source_names) != len(set(source_names)):
            raise ValueError("Empirical input source names must be unique.")

        data_label = str(self.data_label).strip()
        if not data_label:
            raise ValueError("data_label must not be empty.")
        output_mode = str(self.output_mode).strip().lower()
        if output_mode not in {"synthetic_validation", "baseline"}:
            raise ValueError(
                "output_mode must be 'synthetic_validation' or 'baseline'."
            )
        output_timezone = str(self.output_timezone).strip()
        if output_timezone != "UTC":
            raise ValueError(
                "The canonical empirical panel currently supports UTC output "
                "only; set output_timezone to 'UTC'."
            )
        if output_mode == "baseline" and self.manifest_path is None:
            raise ValueError("manifest_path must be supplied for baseline mode.")

        object.__setattr__(self, "simulation_frequency", frequency)
        object.__setattr__(self, "calibration_start", calibration_start)
        object.__setattr__(self, "calibration_end", calibration_end)
        object.__setattr__(self, "validation_start", validation_start)
        object.__setattr__(self, "validation_end", validation_end)
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "data_label", data_label)
        object.__setattr__(self, "output_mode", output_mode)
        object.__setattr__(self, "output_timezone", output_timezone)
        if self.manifest_path is not None:
            object.__setattr__(self, "manifest_path", Path(self.manifest_path))
        if self.processed_data_dir is not None:
            object.__setattr__(
                self,
                "processed_data_dir",
                Path(self.processed_data_dir),
            )


def empirical_config_from_mapping(
    mapping: Mapping[str, Any],
    base_dir: Path = PROJECT_ROOT,
) -> EmpiricalConfig:
    """Construct and validate an empirical configuration mapping."""
    calibration = mapping.get("calibration_period")
    validation = mapping.get("validation_period")
    regime = mapping.get("regime")
    input_files = mapping.get("input_files")
    if not isinstance(calibration, Mapping):
        raise ValueError("calibration_period must be a mapping.")
    if not isinstance(validation, Mapping):
        raise ValueError("validation_period must be a mapping.")
    if not isinstance(regime, Mapping):
        raise ValueError("regime must be a mapping.")
    if not isinstance(input_files, Sequence) or isinstance(
        input_files,
        (str, bytes),
    ):
        raise ValueError("input_files must be a sequence of source mappings.")

    sources = tuple(
        empirical_source_from_mapping(source, base_dir=base_dir)
        for source in input_files
        if isinstance(source, Mapping)
    )
    if len(sources) != len(input_files):
        raise ValueError("Every input_files entry must be a mapping.")

    manifest_value = mapping.get("manifest_path")
    manifest_path = None
    if manifest_value is not None and str(manifest_value).strip():
        manifest_path = Path(str(manifest_value))
        if not manifest_path.is_absolute():
            manifest_path = base_dir / manifest_path
    processed_value = mapping.get("processed_data_dir")
    processed_data_dir = None
    if processed_value is not None and str(processed_value).strip():
        processed_data_dir = Path(str(processed_value))
        if not processed_data_dir.is_absolute():
            processed_data_dir = base_dir / processed_data_dir

    return EmpiricalConfig(
        simulation_frequency=str(mapping.get("simulation_frequency", "")),
        calibration_start=calibration.get("start"),
        calibration_end=calibration.get("end"),
        validation_start=validation.get("start"),
        validation_end=validation.get("end"),
        sources=sources,
        rolling_volatility_window=int(
            mapping.get("rolling_volatility_window", 24)
        ),
        return_lower_quantile=float(
            regime.get("return_lower_quantile", 0.05)
        ),
        volatility_upper_quantile=float(
            regime.get("volatility_upper_quantile", 0.90)
        ),
        gas_upper_quantile=float(regime.get("gas_upper_quantile", 0.90)),
        dai_peg_upper_quantile=float(
            regime.get("dai_peg_upper_quantile", 0.90)
        ),
        liquidation_upper_quantile=float(
            regime.get("liquidation_upper_quantile", 0.90)
        ),
        minimum_stress_conditions=int(
            regime.get("minimum_stress_conditions", 2)
        ),
        data_label=str(
            mapping.get("data_label", "user_supplied_empirical_data")
        ),
        output_mode=str(mapping.get("output_mode", "baseline")),
        output_timezone=str(mapping.get("output_timezone", "UTC")),
        manifest_path=manifest_path,
        processed_data_dir=processed_data_dir,
    )


def load_empirical_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> EmpiricalConfig:
    """Load an empirical YAML configuration with project-relative paths."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Empirical configuration file does not exist: {path}."
        )
    with path.open("r", encoding="utf-8") as stream:
        mapping = yaml.safe_load(stream)
    if not isinstance(mapping, Mapping):
        raise ValueError("Empirical configuration must contain a YAML mapping.")
    return empirical_config_from_mapping(mapping, base_dir=PROJECT_ROOT)


def collect_baseline_configuration_issues(
    mapping: Mapping[str, Any],
    base_dir: Path = PROJECT_ROOT,
) -> list[str]:
    """Collect missing baseline settings and input files without substituting data."""
    issues = []
    if mapping.get("output_mode") != "baseline":
        issues.append("output_mode must be set to 'baseline'")
    if mapping.get("output_timezone") != "UTC":
        issues.append("output_timezone must be set to 'UTC'")

    for period_name in ("calibration_period", "validation_period"):
        period = mapping.get(period_name)
        if not isinstance(period, Mapping):
            issues.append(f"{period_name} must be configured")
            continue
        for boundary in ("start", "end"):
            if period.get(boundary) is None:
                issues.append(f"{period_name}.{boundary} is not configured")

    for path_field in ("manifest_path", "processed_data_dir"):
        value = mapping.get(path_field)
        if value is None or str(value).strip() == "":
            issues.append(f"{path_field} is not configured")
        elif path_field == "manifest_path":
            manifest_path = Path(str(value))
            if not manifest_path.is_absolute():
                manifest_path = base_dir / manifest_path
            if not manifest_path.exists():
                issues.append(f"data manifest does not exist: {manifest_path}")

    input_files = mapping.get("input_files")
    configured_variables = set()
    if not isinstance(input_files, Sequence) or isinstance(
        input_files,
        (str, bytes),
    ) or not input_files:
        issues.append("input_files must contain at least one configured source")
        return issues

    for index, source in enumerate(input_files):
        prefix = f"input_files[{index}]"
        if not isinstance(source, Mapping):
            issues.append(f"{prefix} must be a mapping")
            continue
        source_name = source.get("name")
        if source_name is None or not str(source_name).strip():
            issues.append(f"{prefix}.name is not configured")
        path_value = source.get("path")
        if path_value is None or not str(path_value).strip():
            issues.append(f"{prefix}.path is not configured")
        else:
            source_path = Path(str(path_value))
            if not source_path.is_absolute():
                source_path = base_dir / source_path
            if not source_path.exists():
                issues.append(f"input file does not exist: {source_path}")
        for field_name in ("timestamp_column", "source_timezone"):
            value = source.get(field_name)
            if value is None or not str(value).strip():
                issues.append(f"{prefix}.{field_name} is not configured")

        columns = source.get("columns")
        if not isinstance(columns, Mapping):
            issues.append(f"{prefix}.columns must be configured")
            continue
        for canonical, field_mapping in columns.items():
            if field_mapping is None:
                continue
            configured_variables.add(str(canonical))
            if not isinstance(field_mapping, Mapping):
                issues.append(
                    f"{prefix}.columns.{canonical} must be a field mapping"
                )
                continue
            for field_name in (
                "source_column",
                "source_unit",
                "target_unit",
            ):
                value = field_mapping.get(field_name)
                if value is None or not str(value).strip():
                    issues.append(
                        f"{prefix}.columns.{canonical}.{field_name} is not "
                        "configured"
                    )

    missing_variables = set(REQUIRED_BASELINE_COLUMNS) - configured_variables
    if missing_variables:
        issues.append(
            "required baseline variables are not configured: "
            + ", ".join(sorted(missing_variables))
        )
    return issues


def load_baseline_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> EmpiricalConfig:
    """Load baseline configuration after reporting all missing inputs."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Empirical configuration file does not exist: {path}."
        )
    with path.open("r", encoding="utf-8") as stream:
        mapping = yaml.safe_load(stream)
    if not isinstance(mapping, Mapping):
        raise ValueError("Empirical configuration must contain a YAML mapping.")
    issues = collect_baseline_configuration_issues(mapping)
    if issues:
        raise ValueError(
            "Baseline empirical run cannot start:\n- "
            + "\n- ".join(issues)
        )
    return empirical_config_from_mapping(mapping, base_dir=PROJECT_ROOT)


def _quality_record(
    category: str,
    metric: str,
    value: object,
    source: str = "combined",
    field: str = "",
    notes: str = "",
) -> dict[str, object]:
    """Build one long-format data-quality record."""
    return {
        "category": category,
        "source": source,
        "field": field,
        "metric": metric,
        "value": value,
        "notes": notes,
    }


def _sample_labels(
    index: pd.DatetimeIndex,
    config: EmpiricalConfig,
) -> pd.Series:
    """Assign inclusive calibration and validation labels."""
    labels = pd.Series("unassigned", index=index, dtype="string")
    calibration = index.to_series().between(
        config.calibration_start,
        config.calibration_end,
        inclusive="both",
    )
    validation = index.to_series().between(
        config.validation_start,
        config.validation_end,
        inclusive="both",
    )
    labels.loc[calibration.to_numpy()] = "calibration"
    labels.loc[validation.to_numpy()] = "validation"
    return labels


def _consecutive_log_return(series: pd.Series) -> pd.Series:
    """Calculate log returns only when adjacent grid values are both valid."""
    previous = series.shift(1)
    valid = series.notna() & previous.notna()
    returns = pd.Series(np.nan, index=series.index, dtype=float)
    returns.loc[valid] = np.log(
        series.loc[valid].astype(float) / previous.loc[valid].astype(float)
    )
    return returns


def _rolling_realised_volatility(
    returns: pd.Series,
    window: int,
) -> pd.Series:
    """Calculate rolling root-sum-of-squared log returns."""
    return returns.rolling(window=window, min_periods=window).apply(
        lambda values: float(np.sqrt(np.square(values).sum())),
        raw=True,
    )


def build_market_time_panel(
    config: EmpiricalConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the canonical aligned market-time panel and quality report."""
    standardised_output_dir = (
        config.processed_data_dir
        if config.output_mode == "baseline"
        else None
    )
    panel, quality = load_and_align_sources(
        sources=config.sources,
        simulation_frequency=config.simulation_frequency,
        standardised_output_dir=standardised_output_dir,
    )
    panel["sample_label"] = _sample_labels(panel.index, config)
    input_columns = [
        column for column in CANONICAL_INPUT_COLUMNS if column in panel
    ]
    for sample_label in ("calibration", "validation"):
        sample = panel.loc[panel["sample_label"] == sample_label]
        if sample.empty or sample[input_columns].dropna(how="all").empty:
            raise ValueError(
                f"No usable observations fall within the {sample_label} "
                "period."
            )

    for collateral in ("eth", "btc", "stable"):
        price_column = f"{collateral}_market_price"
        if price_column in panel:
            panel[f"{collateral}_log_return"] = _consecutive_log_return(
                panel[price_column]
            )

    if "stable_market_price" in panel:
        panel["stable_deviation_from_par"] = (
            panel["stable_market_price"] - 1.0
        )
    if "dai_market_price" in panel:
        panel["dai_peg_deviation"] = panel["dai_market_price"] - 1.0
        panel["dai_absolute_peg_deviation"] = panel[
            "dai_peg_deviation"
        ].abs()

    for collateral in ("eth", "btc"):
        return_column = f"{collateral}_log_return"
        if return_column in panel:
            panel[f"{collateral}_realised_volatility"] = (
                _rolling_realised_volatility(
                    panel[return_column],
                    window=config.rolling_volatility_window,
                )
            )

    volatility_columns = [
        column
        for column in (
            "eth_realised_volatility",
            "btc_realised_volatility",
        )
        if column in panel
    ]
    if volatility_columns:
        panel["crypto_realised_volatility"] = panel[
            volatility_columns
        ].max(axis=1, skipna=False)

    quality_records = [
        _quality_record(
            "processed",
            "processed_row_count",
            int(len(panel)),
        ),
        _quality_record(
            "processed",
            "coverage_start",
            panel.index.min().isoformat(),
        ),
        _quality_record(
            "processed",
            "coverage_end",
            panel.index.max().isoformat(),
        ),
        _quality_record(
            "processed",
            "data_label",
            config.data_label,
            notes=(
                "Synthetic fixture labels identify validation-only data; they "
                "are not empirical findings."
            ),
        ),
    ]
    for column in panel.columns:
        quality_records.append(
            _quality_record(
                "missing_values",
                "missing_value_count",
                int(panel[column].isna().sum()),
                field=column,
            )
        )
    quality = pd.concat(
        [quality, pd.DataFrame(quality_records)],
        ignore_index=True,
    )

    preferred_order = [
        *CANONICAL_INPUT_COLUMNS,
        "eth_log_return",
        "btc_log_return",
        "stable_log_return",
        "stable_deviation_from_par",
        "dai_peg_deviation",
        "dai_absolute_peg_deviation",
        "eth_realised_volatility",
        "btc_realised_volatility",
        "crypto_realised_volatility",
        "sample_label",
    ]
    ordered_columns = [
        column for column in preferred_order if column in panel.columns
    ]
    ordered_columns.extend(
        column for column in panel.columns if column not in ordered_columns
    )
    return panel.loc[:, ordered_columns], quality


def estimate_regime_thresholds(
    panel: pd.DataFrame,
    config: EmpiricalConfig,
) -> pd.DataFrame:
    """Estimate all available stress thresholds from calibration rows only."""
    calibration = panel.loc[panel["sample_label"] == "calibration"]
    if calibration.empty:
        raise ValueError("No observations fall within the calibration period.")

    specifications = (
        (
            "stress_eth_return_low",
            "eth_log_return",
            config.return_lower_quantile,
            "below",
        ),
        (
            "stress_btc_return_low",
            "btc_log_return",
            config.return_lower_quantile,
            "below",
        ),
        (
            "stress_crypto_volatility_high",
            "crypto_realised_volatility",
            config.volatility_upper_quantile,
            "above",
        ),
        (
            "stress_gas_cost_high",
            "gas_cost_proxy",
            config.gas_upper_quantile,
            "above",
        ),
        (
            "stress_dai_peg_deviation_high",
            "dai_absolute_peg_deviation",
            config.dai_peg_upper_quantile,
            "above",
        ),
        (
            "stress_liquidation_volume_high",
            "liquidation_volume",
            config.liquidation_upper_quantile,
            "above",
        ),
    )
    records = []

    for condition, source_column, quantile, direction in specifications:
        if source_column not in panel:
            continue
        observations = calibration[source_column].dropna()
        if observations.empty:
            raise ValueError(
                f"No calibration observations are available for "
                f"'{source_column}'."
            )
        records.append(
            {
                "condition": condition,
                "source_column": source_column,
                "quantile": float(quantile),
                "direction": direction,
                "threshold": float(observations.quantile(quantile)),
                "calibration_observations": int(len(observations)),
                "estimation_sample": "calibration",
            }
        )

    if not records:
        raise ValueError("No supported regime-condition variables are available.")
    if config.minimum_stress_conditions > len(records):
        raise ValueError(
            "minimum_stress_conditions exceeds the number of available "
            "regime conditions."
        )
    return pd.DataFrame(records)


def classify_market_regimes(
    panel: pd.DataFrame,
    thresholds: pd.DataFrame,
    minimum_stress_conditions: int,
) -> pd.DataFrame:
    """Apply calibration thresholds to classify normal and stress intervals."""
    classified = panel.copy()
    condition_columns = []

    for threshold in thresholds.itertuples(index=False):
        values = classified[threshold.source_column]
        flag = pd.Series(pd.NA, index=classified.index, dtype="boolean")
        valid = values.notna()
        if threshold.direction == "below":
            flag.loc[valid] = values.loc[valid] < threshold.threshold
        elif threshold.direction == "above":
            flag.loc[valid] = values.loc[valid] > threshold.threshold
        else:
            raise ValueError(
                f"Unknown threshold direction '{threshold.direction}'."
            )
        classified[threshold.condition] = flag
        condition_columns.append(threshold.condition)

    if minimum_stress_conditions > len(condition_columns):
        raise ValueError(
            "minimum_stress_conditions exceeds the number of estimated "
            "conditions."
        )

    flags = classified[condition_columns]
    active = flags.fillna(False).astype(int).sum(axis=1)
    observed = flags.notna().sum(axis=1)
    pool_columns_available = set(POOL_COLUMNS).issubset(classified.columns)
    if pool_columns_available:
        joint_observation_complete = classified.loc[
            :,
            POOL_COLUMNS,
        ].notna().all(axis=1)
    else:
        joint_observation_complete = pd.Series(
            True,
            index=classified.index,
        )
    fully_observed = (
        (observed == len(condition_columns))
        & joint_observation_complete
    )
    regime = pd.Series(pd.NA, index=classified.index, dtype="string")
    regime.loc[fully_observed & (active < minimum_stress_conditions)] = (
        "normal"
    )
    regime.loc[fully_observed & (active >= minimum_stress_conditions)] = (
        "stress"
    )

    classified["active_stress_conditions"] = active.astype("Int64")
    classified["observed_stress_conditions"] = observed.astype("Int64")
    classified["available_stress_conditions"] = len(condition_columns)
    classified["market_regime"] = regime
    return classified


def estimate_regime_transition_matrix(
    panel: pd.DataFrame,
    config: EmpiricalConfig,
    sample_label: str = "calibration",
) -> pd.DataFrame:
    """Estimate two-state transition counts and row probabilities."""
    sample = panel.loc[panel["sample_label"] == sample_label].sort_index()
    regimes = sample["market_regime"]
    previous = regimes.shift(1)
    interval = sample.index.to_series().diff()
    consecutive = interval == _frequency_timedelta(
        config.simulation_frequency
    )
    valid = (
        regimes.isin(("normal", "stress"))
        & previous.isin(("normal", "stress"))
        & consecutive.to_numpy()
    )
    transition_pairs = pd.DataFrame(
        {
            "from_regime": previous.loc[valid],
            "to_regime": regimes.loc[valid],
        }
    )
    counts = transition_pairs.value_counts()
    transitions_used = int(len(transition_pairs))
    classified_observations = int(
        regimes.isin(("normal", "stress")).sum()
    )
    records = []

    for from_regime in ("normal", "stress"):
        origin_total = int(
            sum(
                counts.get((from_regime, to_regime), 0)
                for to_regime in ("normal", "stress")
            )
        )
        for to_regime in ("normal", "stress"):
            count = int(counts.get((from_regime, to_regime), 0))
            probability = (
                count / origin_total if origin_total > 0 else np.nan
            )
            records.append(
                {
                    "from_regime": from_regime,
                    "to_regime": to_regime,
                    "transition_count": count,
                    "transition_probability": probability,
                    "origin_transition_count": origin_total,
                    "origin_has_transitions": origin_total > 0,
                    "classified_observations": classified_observations,
                    "transitions_used": transitions_used,
                    "estimation_sample": sample_label,
                }
            )

    return pd.DataFrame(records)


def create_regime_conditioned_pools(
    panel: pd.DataFrame,
    sample_label: str = "calibration",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create contemporaneously aligned normal and stress bootstrap pools."""
    missing_columns = set(POOL_COLUMNS) - set(panel.columns)
    if missing_columns:
        raise ValueError(
            "Regime-conditioned pools require columns: "
            f"{sorted(missing_columns)}."
        )

    eligible = (
        (panel["sample_label"] == sample_label)
        & panel["market_regime"].isin(("normal", "stress"))
        & panel.loc[:, POOL_COLUMNS].notna().all(axis=1)
    )
    output_columns = ["sample_label", "market_regime", *POOL_COLUMNS]

    def build_pool(regime: str) -> pd.DataFrame:
        pool = panel.loc[
            eligible & (panel["market_regime"] == regime),
            output_columns,
        ].reset_index()
        return pool.rename(columns={"market_regime": "regime"})

    normal_pool = build_pool("normal")
    stress_pool = build_pool("stress")
    normal_timestamps = set(normal_pool["timestamp"])
    stress_timestamps = set(stress_pool["timestamp"])
    if normal_timestamps & stress_timestamps:
        raise ValueError("Normal and stress empirical pools overlap.")
    if len(normal_pool) + len(stress_pool) != int(eligible.sum()):
        raise ValueError(
            "Regime-conditioned pools do not reconcile with eligible "
            "classified observations."
        )
    return normal_pool, stress_pool


def create_sample_overlap_report(
    panel: pd.DataFrame,
    config: EmpiricalConfig,
) -> pd.DataFrame:
    """Report per-series coverage and validate the usable joint sample."""
    configured_columns = [
        canonical
        for source in config.sources
        for canonical in source.fields
    ]
    missing_required = set(REQUIRED_BASELINE_COLUMNS) - set(
        configured_columns
    )
    if missing_required:
        raise ValueError(
            "The empirical joint sample requires configured series: "
            f"{sorted(missing_required)}."
        )

    joint_columns = list(REQUIRED_BASELINE_COLUMNS)
    joint_mask = panel.loc[:, joint_columns].notna().all(axis=1)
    joint_panel = panel.loc[joint_mask]
    if joint_panel.empty:
        raise ValueError(
            "Configured empirical series have no complete aligned observations."
        )
    joint_start = joint_panel.index.min()
    joint_end = joint_panel.index.max()

    sample_windows = {
        "calibration": (config.calibration_start, config.calibration_end),
        "validation": (config.validation_start, config.validation_end),
    }
    outside_windows = []
    for sample_label, (sample_start, sample_end) in sample_windows.items():
        if sample_start < joint_start or sample_end > joint_end:
            outside_windows.append(
                f"{sample_label} [{sample_start.isoformat()}, "
                f"{sample_end.isoformat()}]"
            )
    if outside_windows:
        raise ValueError(
            "Configured sample windows lie outside the usable joint sample "
            f"[{joint_start.isoformat()}, {joint_end.isoformat()}]: "
            + "; ".join(outside_windows)
        )

    records = []
    joint_count = int(joint_mask.sum())
    for column in configured_columns:
        valid = panel[column].dropna()
        observation_count = int(len(valid))
        if valid.empty:
            first_valid_value = ""
            last_valid_value = ""
            expected_count = 0
        else:
            first_valid = valid.index.min()
            last_valid = valid.index.max()
            expected_count = int(
                len(
                    pd.date_range(
                        start=first_valid,
                        end=last_valid,
                        freq=config.simulation_frequency,
                        tz="UTC",
                    )
                )
            )
            first_valid_value = first_valid.isoformat()
            last_valid_value = last_valid.isoformat()
        records.append(
            {
                "record_type": "series",
                "series_name": column,
                "sample_label": "all",
                "first_valid_observation": first_valid_value,
                "last_valid_observation": last_valid_value,
                "observation_count": observation_count,
                "missing_value_count": int(panel[column].isna().sum()),
                "expected_intervals": expected_count,
                "observed_intervals": observation_count,
                "joint_data_start": joint_start.isoformat(),
                "joint_data_end": joint_end.isoformat(),
                "complete_aligned_observations": joint_count,
                "observations_lost_to_alignment": int(
                    (panel[column].notna() & ~joint_mask).sum()
                ),
                "sample_start": "",
                "sample_end": "",
                "sample_expected_intervals": np.nan,
                "sample_complete_observations": np.nan,
                "sample_coverage_fraction": np.nan,
            }
        )

    records.append(
        {
            "record_type": "joint",
            "series_name": "complete_joint_sample",
            "sample_label": "all",
            "first_valid_observation": joint_start.isoformat(),
            "last_valid_observation": joint_end.isoformat(),
            "observation_count": joint_count,
            "missing_value_count": int(len(panel) - joint_count),
            "expected_intervals": int(len(panel)),
            "observed_intervals": joint_count,
            "joint_data_start": joint_start.isoformat(),
            "joint_data_end": joint_end.isoformat(),
            "complete_aligned_observations": joint_count,
            "observations_lost_to_alignment": int(len(panel) - joint_count),
            "sample_start": "",
            "sample_end": "",
            "sample_expected_intervals": np.nan,
            "sample_complete_observations": np.nan,
            "sample_coverage_fraction": np.nan,
        }
    )

    for sample_label, (sample_start, sample_end) in sample_windows.items():
        expected = pd.date_range(
            start=sample_start,
            end=sample_end,
            freq=config.simulation_frequency,
            tz="UTC",
        )
        in_sample = panel.index.to_series().between(
            sample_start,
            sample_end,
            inclusive="both",
        ).to_numpy()
        complete_count = int((joint_mask & in_sample).sum())
        expected_count = int(len(expected))
        records.append(
            {
                "record_type": "sample",
                "series_name": "complete_joint_sample",
                "sample_label": sample_label,
                "first_valid_observation": "",
                "last_valid_observation": "",
                "observation_count": complete_count,
                "missing_value_count": expected_count - complete_count,
                "expected_intervals": expected_count,
                "observed_intervals": complete_count,
                "joint_data_start": joint_start.isoformat(),
                "joint_data_end": joint_end.isoformat(),
                "complete_aligned_observations": joint_count,
                "observations_lost_to_alignment": (
                    expected_count - complete_count
                ),
                "sample_start": sample_start.isoformat(),
                "sample_end": sample_end.isoformat(),
                "sample_expected_intervals": expected_count,
                "sample_complete_observations": complete_count,
                "sample_coverage_fraction": (
                    complete_count / expected_count
                    if expected_count > 0
                    else np.nan
                ),
            }
        )

    return pd.DataFrame(records)


def _summary_record(
    category: str,
    variable: str,
    statistic: str,
    value: float | int,
    observations: int,
    sample_label: str = "all",
    regime: str = "all",
    unit: str = "",
) -> dict[str, object]:
    """Build one long-format empirical summary record."""
    return {
        "category": category,
        "sample_label": sample_label,
        "regime": regime,
        "variable": variable,
        "statistic": statistic,
        "value": value,
        "observations": observations,
        "unit": unit,
    }


def _regime_episode_lengths(
    panel: pd.DataFrame,
    config: EmpiricalConfig,
) -> dict[str, list[int]]:
    """Return consecutive episode lengths in configured time intervals."""
    ordered = panel.sort_index()
    regimes = ordered["market_regime"]
    previous_regime = regimes.shift(1)
    consecutive = (
        ordered.index.to_series().diff()
        == _frequency_timedelta(config.simulation_frequency)
    )
    valid = regimes.isin(("normal", "stress"))
    new_episode = (
        ~valid.shift(1, fill_value=False)
        | (regimes != previous_regime)
        | ~consecutive.to_numpy()
    )
    episode_ids = new_episode.cumsum()
    episodes = {"normal": [], "stress": []}
    for _, episode in ordered.loc[valid].groupby(episode_ids.loc[valid]):
        regime = str(episode["market_regime"].iloc[0])
        episodes[regime].append(int(len(episode)))
    return episodes


def compute_empirical_summary(
    panel: pd.DataFrame,
    config: EmpiricalConfig,
) -> pd.DataFrame:
    """Compute descriptive sample, regime and market-variable statistics."""
    records = []

    for sample_label in ("calibration", "validation"):
        sample = panel.loc[panel["sample_label"] == sample_label]
        classified_count = int(
            sample["market_regime"].isin(("normal", "stress")).sum()
        )
        records.extend(
            [
                _summary_record(
                    "sample",
                    "observations",
                    "row_count",
                    int(len(sample)),
                    int(len(sample)),
                    sample_label=sample_label,
                    unit="intervals",
                ),
                _summary_record(
                    "sample",
                    "classified_observations",
                    "count",
                    classified_count,
                    int(len(sample)),
                    sample_label=sample_label,
                    unit="intervals",
                ),
            ]
        )

    for sample_label, sample in (
        ("all", panel),
        (
            "calibration",
            panel.loc[panel["sample_label"] == "calibration"],
        ),
        (
            "validation",
            panel.loc[panel["sample_label"] == "validation"],
        ),
    ):
        sample_classified = sample["market_regime"].isin(
            ("normal", "stress")
        )
        denominator = int(sample_classified.sum())
        for regime in ("normal", "stress"):
            count = int((sample["market_regime"] == regime).sum())
            share = count / denominator if denominator > 0 else np.nan
            records.extend(
                [
                    _summary_record(
                        "regime",
                        "observations",
                        "count",
                        count,
                        denominator,
                        sample_label=sample_label,
                        regime=regime,
                        unit="intervals",
                    ),
                    _summary_record(
                        "regime",
                        "observations",
                        "share",
                        share,
                        denominator,
                        sample_label=sample_label,
                        regime=regime,
                        unit="proportion",
                    ),
                ]
            )

    episodes = _regime_episode_lengths(panel, config)
    for regime, lengths in episodes.items():
        values = np.asarray(lengths, dtype=float)
        episode_count = int(len(values))
        statistics = {
            "episode_count": episode_count,
            "mean_duration": (
                float(values.mean()) if episode_count else np.nan
            ),
            "median_duration": (
                float(np.median(values)) if episode_count else np.nan
            ),
            "maximum_duration": (
                float(values.max()) if episode_count else np.nan
            ),
        }
        for statistic, value in statistics.items():
            records.append(
                _summary_record(
                    "regime_episode",
                    "duration",
                    statistic,
                    value,
                    episode_count,
                    regime=regime,
                    unit=(
                        "episodes"
                        if statistic == "episode_count"
                        else "intervals"
                    ),
                )
            )

    scopes = [("all", panel)]
    scopes.extend(
        (
            regime,
            panel.loc[panel["market_regime"] == regime],
        )
        for regime in ("normal", "stress")
    )
    for regime, sample in scopes:
        paired_returns = sample[["eth_log_return", "btc_log_return"]].dropna()
        correlation = (
            float(paired_returns.corr().iloc[0, 1])
            if len(paired_returns) >= 2
            else np.nan
        )
        records.append(
            _summary_record(
                "dependence",
                "eth_btc_log_return",
                "pearson_correlation",
                correlation,
                int(len(paired_returns)),
                regime=regime,
            )
        )

        variables = (
            "eth_log_return",
            "btc_log_return",
            "stable_log_return",
            "gas_cost_proxy",
            "dai_absolute_peg_deviation",
            "stable_deviation_from_par",
        )
        for variable in variables:
            values = sample[variable].dropna()
            moments = {
                "mean": values.mean(),
                "median": values.median(),
                "standard_deviation": values.std(),
                "variance": values.var(),
                "skewness": values.skew(),
                "excess_kurtosis": values.kurt(),
                "minimum": values.min(),
                "maximum": values.max(),
            }
            for statistic, value in moments.items():
                records.append(
                    _summary_record(
                        "distribution",
                        variable,
                        statistic,
                        float(value) if pd.notna(value) else np.nan,
                        int(len(values)),
                        regime=regime,
                    )
                )

    return pd.DataFrame(records)


def write_empirical_outputs(
    outputs: Mapping[str, pd.DataFrame],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Path]:
    """Write processed empirical tables to the dedicated output directory."""
    filenames = {
        "market_time_panel": "market_time_panel.csv",
        "regime_thresholds": "regime_thresholds.csv",
        "regime_transition_matrix": "regime_transition_matrix.csv",
        "normal_return_gas_pool": "normal_return_gas_pool.csv",
        "stress_return_gas_pool": "stress_return_gas_pool.csv",
        "data_quality_report": "data_quality_report.csv",
        "sample_overlap_report": "sample_overlap_report.csv",
        "empirical_summary": "empirical_summary.csv",
    }
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    paths = {}

    for name, filename in filenames.items():
        frame = outputs[name]
        path = output_path / filename
        if name == "market_time_panel":
            frame.reset_index().to_csv(path, index=False)
        else:
            frame.to_csv(path, index=False)
        paths[name] = path
    return paths


def run_empirical_pipeline(
    config: EmpiricalConfig,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    save_outputs: bool = True,
) -> dict[str, pd.DataFrame]:
    """Run empirical alignment, classification and pool construction."""
    if config.output_mode == "baseline":
        if config.manifest_path is None:
            raise ValueError("manifest_path is required for baseline mode.")
        validate_data_manifest(
            sources=config.sources,
            simulation_frequency=config.simulation_frequency,
            manifest_path=config.manifest_path,
        )
    panel, quality = build_market_time_panel(config)
    overlap_report = create_sample_overlap_report(panel, config)
    thresholds = estimate_regime_thresholds(panel, config)
    classified_panel = classify_market_regimes(
        panel,
        thresholds,
        minimum_stress_conditions=config.minimum_stress_conditions,
    )
    transitions = estimate_regime_transition_matrix(
        classified_panel,
        config,
        sample_label="calibration",
    )
    normal_pool, stress_pool = create_regime_conditioned_pools(
        classified_panel,
        sample_label="calibration",
    )
    empirical_summary = compute_empirical_summary(classified_panel, config)

    quality_additions = pd.DataFrame(
        [
            _quality_record(
                "classification",
                "classified_calibration_observations",
                int(
                    (
                        (classified_panel["sample_label"] == "calibration")
                        & classified_panel["market_regime"].isin(
                            ("normal", "stress")
                        )
                    ).sum()
                ),
            ),
            _quality_record(
                "classification",
                "unclassified_observations",
                int(classified_panel["market_regime"].isna().sum()),
                notes=(
                    "Intervals remain unclassified when an estimated condition "
                    "input or joint return-gas pool variable is missing."
                ),
            ),
            _quality_record(
                "pools",
                "normal_pool_rows",
                int(len(normal_pool)),
            ),
            _quality_record(
                "pools",
                "stress_pool_rows",
                int(len(stress_pool)),
            ),
        ]
    )
    quality = pd.concat([quality, quality_additions], ignore_index=True)
    outputs = {
        "market_time_panel": classified_panel,
        "regime_thresholds": thresholds,
        "regime_transition_matrix": transitions,
        "normal_return_gas_pool": normal_pool,
        "stress_return_gas_pool": stress_pool,
        "data_quality_report": quality,
        "sample_overlap_report": overlap_report,
        "empirical_summary": empirical_summary,
    }
    if save_outputs:
        write_empirical_outputs(outputs, output_dir=output_dir)
        if (
            config.output_mode == "baseline"
            and config.processed_data_dir is not None
        ):
            config.processed_data_dir.mkdir(parents=True, exist_ok=True)
            classified_panel.reset_index().to_csv(
                config.processed_data_dir / "aligned_market_time_panel.csv",
                index=False,
            )
    return outputs


def create_synthetic_fixture_config() -> EmpiricalConfig:
    """Return the explicitly synthetic configuration used for validation."""
    source = EmpiricalSourceConfig(
        name="synthetic_market_fixture",
        path=SYNTHETIC_FIXTURE_PATH,
        timestamp_column="timestamp",
        source_timezone="UTC",
        fields={
            "eth_market_price": EmpiricalFieldConfig(
                "eth_usd",
                "USD_per_ETH",
                "USD_per_ETH",
            ),
            "btc_market_price": EmpiricalFieldConfig(
                "btc_usd",
                "USD_per_BTC",
                "USD_per_BTC",
            ),
            "stable_market_price": EmpiricalFieldConfig(
                "stable_usd",
                "USD_per_STABLE",
                "USD_per_STABLE",
            ),
            "dai_market_price": EmpiricalFieldConfig(
                "dai_usd",
                "USD_per_DAI",
                "USD_per_DAI",
            ),
            "gas_cost_proxy": EmpiricalFieldConfig(
                "gas_proxy",
                "synthetic_gas_proxy_unit",
                "synthetic_gas_proxy_unit",
            ),
            "liquidation_volume": EmpiricalFieldConfig(
                "liquidation_volume",
                "synthetic_DAI_volume",
                "synthetic_DAI_volume",
            ),
        },
    )
    return EmpiricalConfig(
        simulation_frequency="1h",
        calibration_start=pd.Timestamp("2000-01-01T00:00:00Z"),
        calibration_end=pd.Timestamp("2000-01-01T11:00:00Z"),
        validation_start=pd.Timestamp("2000-01-01T12:00:00Z"),
        validation_end=pd.Timestamp("2000-01-01T19:00:00Z"),
        sources=(source,),
        rolling_volatility_window=3,
        return_lower_quantile=0.20,
        volatility_upper_quantile=0.80,
        gas_upper_quantile=0.80,
        dai_peg_upper_quantile=0.80,
        liquidation_upper_quantile=0.80,
        minimum_stress_conditions=2,
        data_label="synthetic_validation_fixture",
        output_mode="synthetic_validation",
        output_timezone="UTC",
    )


def _expect_value_error(function: Any, message: str) -> None:
    """Assert that a synthetic invalid-input check raises ValueError."""
    try:
        function()
    except ValueError:
        return
    raise AssertionError(message)


def _file_sha1(path: Path) -> str:
    """Return a file hash used to prove validation inputs were not modified."""
    digest = hashlib.sha1()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_synthetic_validation(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, pd.DataFrame]:
    """Run and validate the bundled synthetic fixture pipeline."""
    config = create_synthetic_fixture_config()
    raw_hash_before = _file_sha1(SYNTHETIC_FIXTURE_PATH)
    outputs = run_empirical_pipeline(
        config,
        output_dir=output_dir,
        save_outputs=True,
    )
    panel = outputs["market_time_panel"]
    thresholds = outputs["regime_thresholds"]
    transitions = outputs["regime_transition_matrix"]
    normal_pool = outputs["normal_return_gas_pool"]
    stress_pool = outputs["stress_return_gas_pool"]
    quality = outputs["data_quality_report"]
    overlap = outputs["sample_overlap_report"]

    modified_panel = panel.copy()
    validation_rows = modified_panel["sample_label"] == "validation"
    for threshold in thresholds.itertuples(index=False):
        replacement = -1_000_000.0 if threshold.direction == "below" else 1_000_000.0
        modified_panel.loc[validation_rows, threshold.source_column] = (
            replacement
        )
    modified_thresholds = estimate_regime_thresholds(modified_panel, config)
    pd.testing.assert_frame_equal(thresholds, modified_thresholds)

    for _, origin_rows in transitions.groupby("from_regime", sort=False):
        if bool(origin_rows["origin_has_transitions"].iloc[0]):
            if not np.isclose(
                origin_rows["transition_probability"].sum(),
                1.0,
            ):
                raise AssertionError(
                    "Transition probabilities do not sum to one."
                )

    if set(normal_pool["timestamp"]) & set(stress_pool["timestamp"]):
        raise AssertionError("Normal and stress fixture pools overlap.")
    pool_eligible = (
        (panel["sample_label"] == "calibration")
        & panel["market_regime"].isin(("normal", "stress"))
        & panel.loc[:, POOL_COLUMNS].notna().all(axis=1)
    )
    if len(normal_pool) + len(stress_pool) != int(pool_eligible.sum()):
        raise AssertionError(
            "Fixture pools do not reconcile with classified observations."
        )
    if normal_pool.empty or stress_pool.empty:
        raise AssertionError(
            "Synthetic validation must exercise both market regimes."
        )

    missing_timestamp = pd.Timestamp("2000-01-01T10:00:00Z")
    after_gap_timestamp = pd.Timestamp("2000-01-01T11:00:00Z")
    if not panel.loc[missing_timestamp, list(PRICE_COLUMNS)].isna().all():
        raise AssertionError("The missing fixture interval was not retained.")
    return_columns = [
        "eth_log_return",
        "btc_log_return",
        "stable_log_return",
    ]
    if not panel.loc[after_gap_timestamp, return_columns].isna().all():
        raise AssertionError("Returns were incorrectly calculated across a gap.")

    no_stress_panel = panel.copy()
    no_stress_panel.loc[
        no_stress_panel["market_regime"] == "stress",
        "market_regime",
    ] = "normal"
    absent_transitions = estimate_regime_transition_matrix(
        no_stress_panel,
        config,
    )
    stress_origins = absent_transitions.loc[
        absent_transitions["from_regime"] == "stress"
    ]
    if (
        stress_origins["origin_has_transitions"].any()
        or stress_origins["transition_probability"].notna().any()
    ):
        raise AssertionError("Absent originating regimes were not explicit.")

    source = config.sources[0]
    raw = pd.read_csv(source.path)
    duplicated = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
    _expect_value_error(
        lambda: adapt_source_frame(
            duplicated,
            source,
            config.simulation_frequency,
        ),
        "Duplicated timestamps were not rejected.",
    )
    invalid_price = raw.copy()
    invalid_price.loc[0, "eth_usd"] = 0.0
    _expect_value_error(
        lambda: adapt_source_frame(
            invalid_price,
            source,
            config.simulation_frequency,
        ),
        "A non-positive market price was not rejected.",
    )

    timezone_source = EmpiricalSourceConfig(
        name="timezone_resampling_check",
        path=SYNTHETIC_FIXTURE_PATH,
        timestamp_column="local_time",
        source_timezone="Europe/London",
        fields={
            "eth_market_price": EmpiricalFieldConfig(
                source_column="eth_price_pence",
                source_unit="pence_per_ETH",
                target_unit="GBP_per_ETH",
                conversion=ExplicitUnitConversion("multiply", 0.01),
            )
        },
        resample_aggregation="mean",
    )
    timezone_raw = pd.DataFrame(
        {
            "local_time": [
                "2000-07-01 01:15:00",
                "2000-07-01 01:45:00",
            ],
            "eth_price_pence": [10_000.0, 10_200.0],
        }
    )
    timezone_raw_before = timezone_raw.copy(deep=True)
    timezone_frame, _ = adapt_source_frame(
        timezone_raw,
        timezone_source,
        "1h",
    )
    expected_utc = pd.Timestamp("2000-07-01T00:00:00Z")
    if (
        list(timezone_frame.index) != [expected_utc]
        or not np.isclose(
            timezone_frame["eth_market_price"].iloc[0],
            101.0,
        )
    ):
        raise AssertionError(
            "Explicit timezone conversion, unit conversion or resampling "
            "failed."
        )
    pd.testing.assert_frame_equal(timezone_raw, timezone_raw_before)

    _expect_value_error(
        lambda: EmpiricalFieldConfig("price", "unknown", "USD_per_ETH"),
        "An invalid unit label was not rejected.",
    )
    _expect_value_error(
        lambda: EmpiricalFieldConfig(
            "price",
            "pence_per_ETH",
            "GBP_per_ETH",
        ),
        "An unsupported implicit unit conversion was not rejected.",
    )

    empty_manifest = pd.DataFrame(columns=MANIFEST_COLUMNS)
    _expect_value_error(
        lambda: validate_manifest_records(
            config.sources,
            config.simulation_frequency,
            empty_manifest,
        ),
        "Missing data-manifest records were not rejected.",
    )

    missing_interval_rows = quality.loc[
        (quality["category"] == "alignment")
        & (quality["source"] == source.name)
        & (quality["metric"] == "missing_expected_intervals")
    ]
    if missing_interval_rows.empty or int(
        missing_interval_rows["value"].iloc[0]
    ) != 1:
        raise AssertionError(
            "The synthetic missing interval was not reported correctly."
        )

    missing_source = replace(
        source,
        path=PROJECT_ROOT / "tests" / "fixtures" / "does_not_exist.csv",
    )
    missing_config = replace(config, sources=(missing_source,))
    try:
        load_and_align_sources(
            missing_config.sources,
            missing_config.simulation_frequency,
        )
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("A missing configured input file was not rejected.")

    joint_row = overlap.loc[overlap["record_type"] == "joint"].iloc[0]
    calibration_row = overlap.loc[
        (overlap["record_type"] == "sample")
        & (overlap["sample_label"] == "calibration")
    ].iloc[0]
    validation_row = overlap.loc[
        (overlap["record_type"] == "sample")
        & (overlap["sample_label"] == "validation")
    ].iloc[0]
    if (
        int(joint_row["complete_aligned_observations"]) != 19
        or int(calibration_row["sample_complete_observations"]) != 11
        or int(validation_row["sample_complete_observations"]) != 8
    ):
        raise AssertionError("Synthetic sample-overlap calculations failed.")

    outside_config = replace(
        config,
        calibration_start=pd.Timestamp("1999-12-31T23:00:00Z"),
    )
    _expect_value_error(
        lambda: create_sample_overlap_report(panel, outside_config),
        "A sample window outside the joint sample was not rejected.",
    )
    _expect_value_error(
        lambda: load_baseline_config(DEFAULT_CONFIG_PATH),
        "An incomplete baseline configuration did not fail clearly.",
    )

    if _file_sha1(SYNTHETIC_FIXTURE_PATH) != raw_hash_before:
        raise AssertionError("The synthetic input file was modified in place.")

    print("Synthetic empirical fixture validation passed.")
    print(
        f"Panel rows: {len(panel)}; normal pool: {len(normal_pool)}; "
        f"stress pool: {len(stress_pool)}."
    )
    print(
        "Synthetic outputs are validation artefacts, not empirical findings: "
        f"{Path(output_dir)}"
    )
    return outputs


def run_baseline_empirical_pipeline(
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_dir: Path = BASELINE_OUTPUT_DIR,
) -> dict[str, pd.DataFrame]:
    """Run a configured real-data baseline without synthetic substitution."""
    config = load_baseline_config(config_path)
    return run_empirical_pipeline(
        config,
        output_dir=output_dir,
        save_outputs=True,
    )


def main() -> None:
    """Run synthetic validation by default or an explicitly requested baseline."""
    parser = argparse.ArgumentParser(
        description="Construct aligned empirical DAI market-data panels.",
    )
    parser.add_argument(
        "--mode",
        choices=("synthetic_validation", "baseline"),
        default="synthetic_validation",
        help="Run the synthetic software validation or configured real baseline.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Baseline YAML configuration path.",
    )
    args = parser.parse_args()

    if args.mode == "synthetic_validation":
        run_synthetic_validation(output_dir=SYNTHETIC_OUTPUT_DIR)
        return
    try:
        run_baseline_empirical_pipeline(
            config_path=args.config,
            output_dir=BASELINE_OUTPUT_DIR,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
