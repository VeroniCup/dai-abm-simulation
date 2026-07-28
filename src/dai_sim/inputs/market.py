"""
Opt-in empirical market-return block bootstrap for Tranche C.

Legacy GBM remains the default market process. This module constructs external
ETH/WBTC price paths from compact hourly log-return pools only when explicitly
selected by a Tranche C configuration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
import hashlib

import numpy as np
import pandas as pd
import yaml

from .configuration import REPOSITORY_ROOT, sha256_file
from .sources import (
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

PROJECT_ROOT = REPOSITORY_ROOT
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "empirical.yaml"
DEFAULT_PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "market" / "processed"

DEFAULT_MARKET_GAS_POOL_PATH = (
    REPOSITORY_ROOT
    / "data"
    / "market"
    / "model_inputs"
    / "environment_blocks"
    / "pool.csv"
)
VALID_MARKET_MODES = {"legacy_gbm", "empirical_block_bootstrap"}
VALID_MARKET_POOLS = {"all_calibration", "normal", "stress"}
VALID_ALIGNMENT_MODES = {"shared_market_gas", "market_only"}
VALID_RETURN_TYPES = {"log_return"}

MARKET_GAS_POOL_COLUMNS = {
    "pool_row_id",
    "source_row",
    "timestamp_utc",
    "calibration_pool_label",
    "regime_label",
    "is_calibration",
    "is_withheld_ftx",
    "return_observation_valid",
    "eth_price_usd",
    "wbtc_price_usd",
    "eth_log_return",
    "wbtc_log_return",
    "median_effective_gas_price_gwei",
    "p90_effective_gas_price_gwei",
    "p99_effective_gas_price_gwei",
    "target_normalised_block_utilisation",
}


@dataclass(frozen=True)
class MarketProcessConfig:
    """Configuration for opt-in market path generation."""

    mode: str = "legacy_gbm"
    pool_path: Path | None = None
    pool_sha256: str | None = None
    pool_label: str = "all_calibration"
    block_length_hours: int = 168
    seed: int | None = None
    return_type: str = "log_return"
    alignment_mode: str = "shared_market_gas"
    withheld_period_policy: str = "exclude_ftx"
    shock_overlay_enabled: bool = False

    def validate(self) -> None:
        """Validate market-process controls."""
        if self.mode not in VALID_MARKET_MODES:
            raise ValueError(f"Unknown market process mode: {self.mode}.")
        if self.pool_label not in VALID_MARKET_POOLS:
            raise ValueError(f"Unknown market pool label: {self.pool_label}.")
        if self.block_length_hours <= 0:
            raise ValueError("market block length must be positive.")
        if self.return_type not in VALID_RETURN_TYPES:
            raise ValueError(f"Unknown market return type: {self.return_type}.")
        if self.alignment_mode not in VALID_ALIGNMENT_MODES:
            raise ValueError(f"Unknown market alignment mode: {self.alignment_mode}.")
        if self.withheld_period_policy != "exclude_ftx":
            raise ValueError("Only exclude_ftx is currently supported.")


@dataclass(frozen=True)
class MarketBootstrapResult:
    """Generated empirical price paths and sidecar provenance."""

    price_paths: dict[str, np.ndarray]
    sampled_rows: pd.DataFrame
    provenance: dict[str, Any]


def load_market_gas_pool(
    path: Path | str = DEFAULT_MARKET_GAS_POOL_PATH,
    expected_sha256: str | None = None,
) -> pd.DataFrame:
    """Load and validate the compact Tranche C hourly market/gas pool."""
    pool_path = Path(path)
    if expected_sha256 is not None:
        observed = sha256_file(pool_path)
        if observed != expected_sha256:
            raise ValueError(
                f"Market/gas pool checksum mismatch: expected {expected_sha256}, "
                f"observed {observed}."
            )
    pool = pd.read_csv(pool_path)
    missing = MARKET_GAS_POOL_COLUMNS - set(pool.columns)
    if missing:
        raise ValueError(f"Market/gas pool missing columns: {sorted(missing)}.")
    pool["timestamp_utc"] = pd.to_datetime(pool["timestamp_utc"], utc=True)
    if pool["timestamp_utc"].duplicated().any():
        raise ValueError("Market/gas pool contains duplicate timestamps.")
    if not pool["timestamp_utc"].is_monotonic_increasing:
        raise ValueError("Market/gas pool must be chronologically sorted.")
    for column in [
        "eth_price_usd",
        "wbtc_price_usd",
        "median_effective_gas_price_gwei",
        "p90_effective_gas_price_gwei",
        "p99_effective_gas_price_gwei",
    ]:
        pool[column] = pd.to_numeric(pool[column], errors="coerce")
        if pool[column].le(0).any() or not np.isfinite(pool[column]).all():
            raise ValueError(f"{column} must be finite and positive.")
    return pool


def _pool_mask(pool: pd.DataFrame, pool_label: str) -> pd.Series:
    if pool_label == "all_calibration":
        return pool["is_calibration"].astype(bool)
    return pool["is_calibration"].astype(bool) & pool["regime_label"].eq(pool_label)


def valid_block_starts(
    pool: pd.DataFrame,
    *,
    block_length_hours: int,
    pool_label: str = "all_calibration",
) -> list[int]:
    """Return deterministic valid moving-block start indexes."""
    if block_length_hours <= 0:
        raise ValueError("block_length_hours must be positive.")
    timestamps = pool["timestamp_utc"]
    hourly_steps = timestamps.diff().dropna().eq(pd.Timedelta(hours=1))
    if not hourly_steps.all():
        raise ValueError("Market/gas pool contains a timestamp gap.")

    eligible = (
        _pool_mask(pool, pool_label)
        & pool["return_observation_valid"].astype(bool)
        & ~pool["is_withheld_ftx"].astype(bool)
    ).to_numpy(dtype=bool)
    regimes = pool["regime_label"].to_numpy()
    starts: list[int] = []
    max_start = len(pool) - block_length_hours
    for start in range(max_start + 1):
        stop = start + block_length_hours
        window = eligible[start:stop]
        if len(window) != block_length_hours or not window.all():
            continue
        if pool_label in {"normal", "stress"} and not (regimes[start:stop] == pool_label).all():
            continue
        starts.append(start)
    return starts


def sample_market_gas_blocks(
    pool: pd.DataFrame,
    *,
    horizon: int,
    block_length_hours: int,
    seed: int | None,
    pool_label: str = "all_calibration",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Sample aligned market/gas rows using a moving-block bootstrap."""
    if horizon <= 0:
        raise ValueError("horizon must be positive.")
    starts = valid_block_starts(
        pool,
        block_length_hours=block_length_hours,
        pool_label=pool_label,
    )
    if not starts:
        raise ValueError("No valid empirical block starts are available.")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(horizon / block_length_hours))
    chosen_starts = rng.choice(np.asarray(starts, dtype=int), size=n_blocks, replace=True)
    pieces = [
        pool.iloc[start : start + block_length_hours].copy()
        for start in chosen_starts
    ]
    sampled = pd.concat(pieces, ignore_index=True).iloc[:horizon].copy()
    sampled.insert(0, "simulation_step", np.arange(horizon, dtype=int))
    final_block_length = horizon - block_length_hours * (n_blocks - 1)
    provenance = {
        "block_length_hours": block_length_hours,
        "n_blocks": n_blocks,
        "sampled_start_indexes": [int(value) for value in chosen_starts],
        "replacement_used": True,
        "final_truncated_block_length": int(final_block_length),
        "available_block_start_count": len(starts),
        "pool_label": pool_label,
    }
    return sampled, provenance


def prices_from_log_returns(
    sampled_rows: pd.DataFrame,
    *,
    initial_prices: dict[str, float],
) -> dict[str, np.ndarray]:
    """Construct positive price paths by applying sampled log returns."""
    required = {"ETH", "BTC"}
    if set(initial_prices) & required != required:
        raise ValueError("Initial prices must include ETH and BTC.")
    paths: dict[str, np.ndarray] = {}
    for collateral_type, column in (
        ("ETH", "eth_log_return"),
        ("BTC", "wbtc_log_return"),
    ):
        returns = pd.to_numeric(sampled_rows[column], errors="coerce").to_numpy(dtype=float)
        if np.isnan(returns).any() or not np.isfinite(returns).all():
            raise ValueError(f"{column} contains missing or non-finite returns.")
        prices = np.empty(len(returns), dtype=float)
        prices[0] = float(initial_prices[collateral_type])
        for index in range(1, len(returns)):
            prices[index] = prices[index - 1] * np.exp(returns[index])
        if not np.isfinite(prices).all() or (prices <= 0).any():
            raise ValueError(f"Generated {collateral_type} price path is invalid.")
        paths[collateral_type] = prices
    return paths


def generate_empirical_price_paths(
    *,
    n_steps: int,
    initial_prices: dict[str, float],
    config: MarketProcessConfig,
) -> MarketBootstrapResult:
    """Generate opt-in empirical ETH/BTC price paths."""
    config.validate()
    if config.mode != "empirical_block_bootstrap":
        raise ValueError("Empirical price path generation requires empirical_block_bootstrap.")
    pool_path = config.pool_path or DEFAULT_MARKET_GAS_POOL_PATH
    pool = load_market_gas_pool(pool_path, config.pool_sha256)
    sampled, provenance = sample_market_gas_blocks(
        pool,
        horizon=n_steps,
        block_length_hours=config.block_length_hours,
        seed=config.seed,
        pool_label=config.pool_label,
    )
    price_paths = prices_from_log_returns(sampled, initial_prices=initial_prices)
    provenance.update(
        {
            "market_process_mode": config.mode,
            "market_pool_path": str(Path(pool_path).relative_to(REPOSITORY_ROOT)),
            "market_pool_checksum": sha256_file(Path(pool_path)),
            "market_return_type": config.return_type,
            "market_alignment_mode": config.alignment_mode,
            "withheld_period_policy": config.withheld_period_policy,
            "shock_overlay_enabled": config.shock_overlay_enabled,
        }
    )
    return MarketBootstrapResult(
        price_paths=price_paths,
        sampled_rows=sampled,
        provenance=provenance,
    )


# Empirical market loading and time-panel adaptation

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
