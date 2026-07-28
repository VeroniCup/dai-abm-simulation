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
import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

import numpy as np
import pandas as pd
import yaml

from dai_sim.inputs.sources import (
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
from dai_sim.inputs.market import (
    DEFAULT_CONFIG_PATH,
    EmpiricalConfig,
    _consecutive_log_return,
    _quality_record,
    _rolling_realised_volatility,
    _sample_labels,
    build_market_time_panel,
    collect_baseline_configuration_issues,
    empirical_config_from_mapping,
    load_baseline_config,
    load_empirical_config,
)
from .data_loading import (
    load_inputs,
    parse_utc_timestamp,
    phase2a_input_specs,
    require_hourly_index,
    sha256_file,
    validate_protocol_intervals,
    verify_all_inputs,
)
from .gas import _gas_outputs, _liquidation_outputs
from .protocol import _protocol_outputs
from .statistics import (
    _long_matrix,
    aligned_dependence,
    candidate_block_length,
    classify_regimes,
    distribution_summary,
    estimate_regime_thresholds as _estimate_phase2a_regime_thresholds,
    moving_block_bootstrap_ci,
    overdispersion_summary,
    regime_durations,
    transition_counts,
    transition_probabilities,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "empirical.yaml"
EMPIRICAL_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "empirical"
SYNTHETIC_OUTPUT_DIR = EMPIRICAL_OUTPUT_DIR / "synthetic_validation"
BASELINE_OUTPUT_DIR = EMPIRICAL_OUTPUT_DIR / "baseline"
DEFAULT_OUTPUT_DIR = SYNTHETIC_OUTPUT_DIR
DEFAULT_PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "market" / "processed"
SYNTHETIC_FIXTURE_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "empirical_market_fixture.csv"
)

POOL_COLUMNS = (
    "eth_log_return",
    "btc_log_return",
    "stable_log_return",
    "gas_cost_proxy",
)


























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


# Phase 2A market and cross-domain orchestration

CALIBRATION_START = pd.Timestamp("2021-06-01T00:00:00Z")

CALIBRATION_END_EXCLUSIVE = pd.Timestamp("2024-07-01T00:00:00Z")

FTX_VALIDATION_START = pd.Timestamp("2022-11-01T00:00:00Z")

FTX_VALIDATION_END_EXCLUSIVE = pd.Timestamp("2022-11-21T00:00:00Z")

DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data/processed/estimation/phase2a"
)

DEFAULT_FIGURES = PROJECT_ROOT / "outputs/estimation/phase2a"

DEFAULT_REPORT = PROJECT_ROOT / "docs/phase2a_parameter_estimation_report.md"

PARAMETER_PLAN = PROJECT_ROOT / "docs/parameter_estimation_plan.md"

PARAMETER_STATUSES: dict[str, str] = {
    "4.1.1": "scenario_only",
    "4.1.2": "blocked_pending_phase1e_b",
    "4.1.3": "scenario_only",
    "4.1.4": "scenario_only",
    "4.1.5": "scenario_only",
    "4.1.6": "protocol_constant",
    "4.1.7": "scenario_only",
    "4.2.1": "phase2a_estimable",
    "4.2.2": "phase2a_estimable",
    "4.2.3": "blocked_pending_phase1e_b",
    "4.2.4": "blocked_pending_phase1e_b",
    "4.2.5": "blocked_pending_phase1e_b",
    "4.2.6": "blocked_pending_phase1e_b",
    "4.2.7": "blocked_pending_phase1e_b",
    "4.2.8": "blocked_pending_phase1e_b",
    "4.3.1": "phase2a_estimable",
    "4.3.2": "phase2a_estimable",
    "4.3.3": "phase2a_estimable",
    "4.3.4": "scenario_only",
    "4.3.5": "scenario_only",
    "4.3.6": "scenario_only",
    "4.3.7": "phase2a_estimable",
    "4.3.8": "scenario_only",
    "4.3.9": "scenario_only",
    "4.3.10": "scenario_only",
    "4.3.11": "scenario_only",
    "4.3.12": "literature_required",
    "4.4.1": "protocol_constant",
    "4.4.2": "protocol_constant",
    "4.4.3": "phase2a_estimable",
    "4.4.4": "requires_model_calibration",
    "4.4.5": "blocked_pending_phase1e_b",
    "4.4.6": "phase2a_estimable",
    "4.5.1": "phase2a_estimable",
    "4.5.2": "phase2a_estimable",
    "4.5.3": "phase2a_estimable",
    "4.5.4": "blocked_pending_phase1e_b",
    "4.5.5": "blocked_pending_phase1e_b",
    "4.5.6": "requires_model_calibration",
    "4.5.7": "requires_model_calibration",
    "4.5.8": "requires_model_calibration",
    "4.5.9": "requires_model_calibration",
    "4.5.10": "requires_model_calibration",
    "4.6.1": "protocol_constant",
    "4.6.2": "requires_model_calibration",
    "4.6.3": "requires_model_calibration",
    "4.6.4": "requires_model_calibration",
    "4.6.5": "requires_model_calibration",
    "4.6.6": "requires_model_calibration",
    "4.6.7": "scenario_only",
    "4.6.8": "scenario_only",
    "4.6.9": "scenario_only",
    "4.6.10": "requires_model_calibration",
    "4.6.11": "requires_model_calibration",
    "4.6.12": "requires_model_calibration",
    "4.6.13": "requires_model_calibration",
}

ESTIMABLE_SOURCES: dict[str, tuple[str, str, str, str]] = {
    "4.2.1": (
        "Phase 1A market panel",
        "timestamp_utc;eth_price_usd;wbtc_price_usd;usdc_price_usd",
        "Exact replay-start observation",
        "market/initial_prices.csv",
    ),
    "4.2.2": (
        "Phase 1A market panel",
        "timestamp_utc;dai_price_usd",
        "Exact replay-start observation",
        "market/initial_prices.csv",
    ),
    "4.3.1": (
        "Phase 1A market panel",
        "timestamp_utc;eth_log_return;wbtc_log_return;usdc_log_return",
        "Aligned empirical moving blocks",
        "market/return_block_index.csv",
    ),
    "4.3.2": (
        "Phase 1A market panel",
        "eth_log_return;wbtc_log_return;usdc_log_return",
        "Hourly sample mean with moving-block-bootstrap uncertainty",
        "market/return_distribution.csv",
    ),
    "4.3.3": (
        "Phase 1A market panel",
        "eth_log_return;wbtc_log_return;usdc_log_return",
        "Hourly sample standard deviation by regime",
        "market/return_distribution.csv",
    ),
    "4.3.7": (
        "Phase 1A market panel",
        "eth_log_return;wbtc_log_return;usdc_log_return",
        "Empirical lower-tail quantiles",
        "market/return_distribution.csv",
    ),
    "4.4.3": (
        "Phase 1C actions and transactions; Phase 1A ETH price",
        "record_type;tx_hash;gas_used;gas_price;block_time;eth_price_usd",
        "Clean successful-Take top-level transaction distribution",
        "liquidations/liquidation_transaction_gas.csv",
    ),
    "4.4.6": (
        "Phase 1C hourly liquidation panel",
        "timestamp_utc;auctions_completed;successful_takes;unique_keepers",
        "Regime-conditioned empirical hourly throughput distribution",
        "liquidations/hourly_liquidation_summary.csv",
    ),
    "4.5.1": (
        "Phase 1A DAI price panel",
        "dai_price_usd",
        "Calibration-sample fifth percentile",
        "market/dai_peg_distribution.csv",
    ),
    "4.5.2": (
        "Phase 1A DAI price panel",
        "dai_price_usd",
        "Calibration-sample ninety-fifth percentile",
        "market/dai_peg_distribution.csv",
    ),
    "4.5.3": (
        "Phase 1A DAI price panel",
        "dai_price_usd",
        "Calibration-sample first percentile",
        "market/dai_peg_distribution.csv",
    ),
}

REQUIRED_CANDIDATE_FIELDS = {
    "simulator_field",
    "estimate_name",
    "estimate_value",
    "distribution_reference",
    "units",
    "simulation_frequency",
    "collateral_scope",
    "regime_scope",
    "estimator",
    "input_dataset",
    "input_columns",
    "estimation_window",
    "sample_size",
    "uncertainty_measure",
    "validation_status",
    "provenance_classification",
    "implementation_status",
    "notes",
    "review_required_before_adoption",
}

@dataclass(frozen=True)
class Phase2AConfig:
    """Execution controls for one reproducible Phase 2A run."""

    output_dir: Path = DEFAULT_OUTPUT
    figure_dir: Path = DEFAULT_FIGURES
    report_path: Path = DEFAULT_REPORT
    random_seed: int = 20_260_726
    bootstrap_replications: int = 200
    rolling_volatility_hours: int = 24
    minimum_stress_conditions: int = 2
    write_figures: bool = True
    write_report: bool = True

def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        try:
            return value.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return value.as_posix()
    if pd.isna(value):
        return None
    raise TypeError(f"Cannot serialise {type(value).__name__}.")

def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        default=_json_default,
        allow_nan=False,
    )
    path.write_text(text + "\n", encoding="utf-8")

def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        float_format="%.12g",
    )

def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()

def _parameter_plan_sections() -> list[tuple[str, str]]:
    text = PARAMETER_PLAN.read_text(encoding="utf-8")
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^#### (4\.\d+\.\d+) (.+)$", line)
        if not match:
            continue
        number, title = match.groups()
        continuation = index + 1
        while continuation < len(lines):
            next_line = lines[continuation]
            if not next_line or next_line.startswith("#"):
                break
            title = f"{title} {next_line.strip()}"
            continuation += 1
        sections.append((number, title))
    if set(number for number, _ in sections) != set(PARAMETER_STATUSES):
        raise ValueError(
            "Parameter-status mapping does not match the authoritative "
            "numbered subsections."
        )
    return sections

def build_parameter_status() -> pd.DataFrame:
    """Audit every numbered parameter-plan subsection."""
    rows: list[dict[str, str]] = []
    for number, title in _parameter_plan_sections():
        status = PARAMETER_STATUSES[number]
        field = re.sub(r"[`*]", "", title).replace("\n", " ").strip()
        if number in ESTIMABLE_SOURCES:
            source, columns, estimator, output = ESTIMABLE_SOURCES[number]
        elif status == "protocol_constant":
            source = "Phase 1D protocol parameter panel"
            columns = (
                "timestamp_utc;ilk;parameter-specific effective value"
            )
            estimator = "Effective-dated direct protocol-state extraction"
            output = "protocol/protocol_parameter_summary.csv"
        elif status == "blocked_pending_phase1e_b":
            source = "Planned Phase 1E-B representative vault panels"
            columns = ""
            estimator = ""
            output = ""
        elif status == "requires_model_calibration":
            source = "Phase 1A–1C target moments and later simulator outputs"
            columns = ""
            estimator = "Deferred minimum-distance or SMM calibration"
            output = ""
        elif status == "literature_required":
            source = "Phase 1D mappings plus oracle documentation/literature"
            columns = "oracle_adapter"
            estimator = "Literature/protocol-bounded scenario set"
            output = ""
        else:
            source = "Experimental design"
            columns = ""
            estimator = "No empirical estimator"
            output = ""
        provenance = {
            "phase2a_estimable": "empirical_estimation",
            "protocol_constant": "protocol_constant",
            "blocked_pending_phase1e_b": "empirical_pending",
            "requires_model_calibration": "model_calibration",
            "scenario_only": "experimental_scenario",
            "literature_required": "literature",
            "not_currently_identifiable": "unidentified",
        }[status]
        blocker = {
            "blocked_pending_phase1e_b": (
                "Representative vault opening states and mutations"
            ),
            "requires_model_calibration": (
                "Observable inputs must be fixed before simulator calibration"
            ),
            "literature_required": (
                "Historical oracle update delay is not present in Phase 1D"
            ),
        }.get(status, "")
        rows.append(
            {
                "parameter_subsection": f"{number} {title}",
                "simulator_field": field,
                "provenance_class": provenance,
                "current_status": status,
                "source_dataset": source,
                "source_columns": columns,
                "estimator": estimator,
                "output_artefact": output,
                "blocking_dependency": blocker,
                "notes": (
                    "No numerical value is assigned while blocked or deferred."
                    if blocker
                    else "Review is required before simulator adoption."
                ),
            }
        )
    return pd.DataFrame(rows)

def aggregate_liquidation_volume(
    liquidation_hourly: pd.DataFrame,
    hourly_index: pd.Series,
) -> pd.DataFrame:
    """Aggregate exact-ilk debt targets and retain explicit zero-activity hours."""
    required = {"timestamp_utc", "debt_targeted_dai"}
    missing = required.difference(liquidation_hourly.columns)
    if missing:
        raise ValueError(
            f"Liquidation aggregation is missing columns: {sorted(missing)}."
        )
    liquidation = liquidation_hourly.copy()
    liquidation["timestamp_utc"] = pd.to_datetime(
        liquidation["timestamp_utc"], utc=True, errors="coerce"
    )
    if liquidation["timestamp_utc"].isna().any():
        raise ValueError("Liquidation aggregation contains invalid timestamps.")
    liquidation["debt_targeted_dai"] = pd.to_numeric(
        liquidation["debt_targeted_dai"], errors="coerce"
    )
    if liquidation["debt_targeted_dai"].isna().any():
        raise ValueError("Liquidation debt targets contain invalid values.")
    totals = (
        liquidation.groupby("timestamp_utc", as_index=False)[
            "debt_targeted_dai"
        ]
        .sum()
        .rename(columns={"debt_targeted_dai": "liquidation_volume_dai"})
    )
    base = pd.DataFrame(
        {"timestamp_utc": pd.to_datetime(hourly_index, utc=True)}
    )
    result = base.merge(
        totals, on="timestamp_utc", how="left", validate="one_to_one"
    )
    result["liquidation_volume_dai"] = result[
        "liquidation_volume_dai"
    ].fillna(0.0)
    return result

def _prepare_hourly_panel(
    frames: dict[str, pd.DataFrame],
    config: Phase2AConfig,
) -> pd.DataFrame:
    market = frames["market"].copy()
    gas = frames["gas"].copy()
    combined = frames["combined"].copy()
    for name, frame in (
        ("market", market),
        ("gas", gas),
        ("combined", combined),
    ):
        frame["timestamp_utc"] = parse_utc_timestamp(
            frame, "timestamp_utc", name=name
        )
        require_hourly_index(frame["timestamp_utc"], name=name)
    if not market["timestamp_utc"].equals(gas["timestamp_utc"]):
        raise ValueError("Phase 1A and Phase 1B timestamps do not align.")
    if not market["timestamp_utc"].equals(combined["timestamp_utc"]):
        raise ValueError("Combined panel timestamps do not align.")
    for column in (
        "eth_log_return",
        "wbtc_log_return",
        "dai_log_return",
        "usdc_log_return",
        "eth_price_usd",
        "dai_price_usd",
    ):
        left = pd.to_numeric(market[column], errors="coerce")
        right = pd.to_numeric(combined[column], errors="coerce")
        if not np.allclose(left, right, equal_nan=True, rtol=0, atol=0):
            raise ValueError(f"Combined panel changed Phase 1A column {column}.")
    hourly = combined.copy()
    liquidation = frames["liquidation_hourly"].copy()
    liquidation["timestamp_utc"] = parse_utc_timestamp(
        liquidation, "timestamp_utc", name="liquidation_hourly"
    )
    totals = aggregate_liquidation_volume(
        liquidation, hourly["timestamp_utc"]
    )
    hourly = hourly.merge(
        totals, on="timestamp_utc", how="left", validate="one_to_one"
    )
    hourly["liquidation_volume_dai"] = hourly[
        "liquidation_volume_dai"
    ].fillna(0.0)
    eth_var = (
        pd.to_numeric(hourly["eth_log_return"], errors="coerce")
        .rolling(config.rolling_volatility_hours, min_periods=config.rolling_volatility_hours)
        .var(ddof=0)
    )
    wbtc_var = (
        pd.to_numeric(hourly["wbtc_log_return"], errors="coerce")
        .rolling(config.rolling_volatility_hours, min_periods=config.rolling_volatility_hours)
        .var(ddof=0)
    )
    hourly["realised_crypto_volatility"] = np.sqrt(
        (eth_var + wbtc_var) / 2
    )
    hourly["is_validation"] = (
        (hourly["timestamp_utc"] >= FTX_VALIDATION_START)
        & (hourly["timestamp_utc"] < FTX_VALIDATION_END_EXCLUSIVE)
    )
    hourly["is_calibration"] = ~hourly["is_validation"]
    calibration = hourly.loc[hourly["is_calibration"]]
    thresholds = _estimate_phase2a_regime_thresholds(calibration)
    hourly = classify_regimes(
        hourly,
        thresholds,
        minimum_conditions=config.minimum_stress_conditions,
    )
    hourly.attrs["thresholds"] = thresholds
    return hourly

def _market_outputs(
    hourly: pd.DataFrame,
    config: Phase2AConfig,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    return_columns = [
        "eth_log_return",
        "wbtc_log_return",
        "usdc_log_return",
        "dai_log_return",
    ]
    summaries: list[dict[str, Any]] = []
    dependence: list[pd.DataFrame] = []
    for sample, sample_mask in (
        ("calibration", hourly["is_calibration"]),
        ("validation_ftx", hourly["is_validation"]),
    ):
        for regime in ("all", "normal", "stress"):
            mask = sample_mask & (
                True if regime == "all" else hourly["regime"].eq(regime)
            )
            subset = hourly.loc[mask]
            for column in return_columns:
                summary = distribution_summary(subset[column])
                summaries.append(
                    {
                        "sample": sample,
                        "regime": regime,
                        "asset": column.removesuffix("_log_return").upper(),
                        "frequency": "hourly",
                        "unit": "log_return",
                        **summary,
                    }
                )
            if len(subset) >= 2:
                covariance, pearson, spearman, observations = (
                    aligned_dependence(subset, return_columns)
                )
                for name, matrix in (
                    ("covariance", covariance),
                    ("pearson_correlation", pearson),
                    ("spearman_rank_correlation", spearman),
                ):
                    dependence.append(
                        _long_matrix(
                            matrix,
                            matrix_type=name,
                            sample=sample,
                            regime=regime,
                            observations=observations,
                        )
                    )
    calibration_returns = hourly.loc[
        hourly["is_calibration"], return_columns
    ].dropna()
    segment_masks = [
        hourly["timestamp_utc"] < FTX_VALIDATION_START,
        hourly["timestamp_utc"] >= FTX_VALIDATION_END_EXCLUSIVE,
    ]
    block_candidates = []
    acf_frames = []
    for segment_id, segment_mask in enumerate(segment_masks, start=1):
        segment = hourly.loc[
            hourly["is_calibration"] & segment_mask, return_columns
        ].dropna()
        length, acf = candidate_block_length(segment, max_lag=168)
        acf["segment_id"] = segment_id
        acf_frames.append(acf)
        block_candidates.append(length)
    block_length = max(block_candidates)
    block_rows = []
    block_id = 0
    for segment_id, segment_mask in enumerate(segment_masks, start=1):
        segment = hourly.loc[
            hourly["is_calibration"] & segment_mask
        ].reset_index()
        for start in range(0, len(segment) - block_length + 1):
            block_id += 1
            block_rows.append(
                {
                    "block_id": block_id,
                    "segment_id": segment_id,
                    "source_start_row": int(segment.loc[start, "index"]),
                    "start_timestamp_utc": segment.loc[start, "timestamp_utc"],
                    "end_timestamp_utc": segment.loc[
                        start + block_length - 1, "timestamp_utc"
                    ],
                    "block_length_hours": block_length,
                }
            )
    uncertainty_rows = []
    for offset, column in enumerate(return_columns):
        values = calibration_returns[column].to_numpy(dtype=float)
        estimators = {
            "mean": np.mean,
            "std": lambda array: float(np.std(array, ddof=1)),
            "q05": lambda array: float(np.quantile(array, 0.05)),
            "q95": lambda array: float(np.quantile(array, 0.95)),
        }
        for name, estimator in estimators.items():
            interval = moving_block_bootstrap_ci(
                values,
                block_length=block_length,
                estimator=estimator,
                replications=config.bootstrap_replications,
                seed=config.random_seed + offset * 10 + len(name),
            )
            uncertainty_rows.append(
                {
                    "asset": column.removesuffix("_log_return").upper(),
                    "estimate": name,
                    "frequency": "hourly",
                    "block_length_hours": block_length,
                    **interval,
                }
            )
    initial_rows = []
    for timestamp, label in (
        (CALIBRATION_START, "sample_start"),
        (FTX_VALIDATION_START, "validation_start"),
    ):
        selected = hourly.loc[hourly["timestamp_utc"].eq(timestamp)]
        if len(selected) != 1:
            raise ValueError(f"Initial price timestamp not found: {timestamp}")
        row = selected.iloc[0]
        for asset, column in (
            ("ETH", "eth_price_usd"),
            ("WBTC", "wbtc_price_usd"),
            ("DAI", "dai_price_usd"),
            ("USDC", "usdc_price_usd"),
        ):
            initial_rows.append(
                {
                    "timestamp_utc": timestamp,
                    "role": label,
                    "asset": asset,
                    "price_usd": row[column],
                }
            )
    peg_rows = []
    for sample, mask in (
        ("calibration", hourly["is_calibration"]),
        ("validation_ftx", hourly["is_validation"]),
    ):
        subset = hourly.loc[mask]
        for variable in (
            "dai_price_usd",
            "dai_log_return",
            "dai_peg_deviation",
            "dai_abs_peg_deviation",
        ):
            peg_rows.append(
                {
                    "sample": sample,
                    "variable": variable,
                    **distribution_summary(subset[variable]),
                }
            )
    outputs = {
        "market/return_distribution.csv": pd.DataFrame(summaries),
        "market/dependence_matrices.csv": pd.concat(
            dependence, ignore_index=True
        ),
        "market/return_bootstrap_uncertainty.csv": pd.DataFrame(
            uncertainty_rows
        ),
        "market/return_block_index.csv": pd.DataFrame(block_rows),
        "market/absolute_return_autocorrelation.csv": pd.concat(
            acf_frames, ignore_index=True
        ),
        "market/initial_prices.csv": pd.DataFrame(initial_rows),
        "market/dai_peg_distribution.csv": pd.DataFrame(peg_rows),
    }
    details = {
        "candidate_block_length_hours": block_length,
        "bootstrap_replications": config.bootstrap_replications,
        "return_columns": return_columns,
        "calibration_return_observations": int(len(calibration_returns)),
    }
    return outputs, details

def _regime_outputs(
    hourly: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    calibration_mask = hourly["is_calibration"]
    counts = transition_counts(
        hourly["regime"],
        hourly["timestamp_utc"],
        allowed_mask=calibration_mask,
    )
    probabilities = transition_probabilities(counts)
    durations = regime_durations(
        hourly["regime"],
        hourly["timestamp_utc"],
        allowed_mask=calibration_mask,
    )
    transition_rows = []
    for previous in counts.index:
        for current in counts.columns:
            transition_rows.append(
                {
                    "from_regime": previous,
                    "to_regime": current,
                    "transition_count": int(counts.loc[previous, current]),
                    "transition_probability": probabilities.loc[
                        previous, current
                    ],
                }
            )
    prevalence = (
        hourly.loc[calibration_mask, "regime"]
        .value_counts(normalize=False)
        .rename_axis("regime")
        .reset_index(name="hours")
    )
    prevalence["share"] = prevalence["hours"] / prevalence["hours"].sum()
    hourly_export_columns = [
        "timestamp_utc",
        "is_calibration",
        "is_validation",
        "regime",
        "stress_condition_count",
        "panic_candidate",
        "stress_low_eth_return",
        "stress_low_wbtc_return",
        "stress_high_crypto_volatility",
        "stress_high_gas",
        "stress_high_dai_deviation",
        "stress_high_liquidation_volume",
    ]
    panic = hourly.loc[calibration_mask, "panic_candidate"]
    panic_runs = regime_durations(
        panic.map({0: "not_panic", 1: "panic_candidate"}),
        hourly.loc[calibration_mask, "timestamp_utc"],
    )
    panic_only = panic_runs.loc[
        panic_runs["regime"].eq("panic_candidate")
    ]
    panic_share = float(panic.mean())
    identifiable = bool(panic_share >= 0.005 and len(panic_only) >= 20)
    details = {
        "thresholds": hourly.attrs["thresholds"],
        "normal_hours": int(
            (hourly.loc[calibration_mask, "regime"] == "normal").sum()
        ),
        "stress_hours": int(
            (hourly.loc[calibration_mask, "regime"] == "stress").sum()
        ),
        "stress_entry_probability": float(
            probabilities.loc["normal", "stress"]
        ),
        "stress_exit_probability": float(
            probabilities.loc["stress", "normal"]
        ),
        "stress_persistence_probability": float(
            probabilities.loc["stress", "stress"]
        ),
        "panic_candidate_share": panic_share,
        "panic_candidate_runs": int(len(panic_only)),
        "three_state_statistically_populated": identifiable,
        "three_state_adopted": False,
        "three_state_decision": (
            "Not adopted: incremental held-out model improvement has not been "
            "demonstrated."
        ),
    }
    outputs = {
        "regimes/hourly_regimes.csv": hourly[hourly_export_columns],
        "regimes/regime_prevalence.csv": prevalence,
        "regimes/regime_transitions.csv": pd.DataFrame(transition_rows),
        "regimes/regime_durations.csv": durations,
    }
    return outputs, details

def validate_candidate_registry(payload: dict[str, Any]) -> None:
    """Validate candidate schema and prevent values for blocked parameters."""
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Candidate registry must contain a non-empty list.")
    for index, candidate in enumerate(candidates):
        missing = REQUIRED_CANDIDATE_FIELDS.difference(candidate)
        if missing:
            raise ValueError(
                f"Candidate {index} is missing fields: {sorted(missing)}"
            )
        if (
            candidate["estimate_value"] is None
            and not candidate["distribution_reference"]
        ):
            raise ValueError(
                f"Candidate {index} has neither a value nor a distribution."
            )
        if candidate["implementation_status"] in {
            "blocked_pending_phase1e_b",
            "requires_model_calibration",
        }:
            raise ValueError("Blocked parameters must not enter the registry.")
        if not candidate["units"] or not candidate["simulation_frequency"]:
            raise ValueError(f"Candidate {index} lacks units or frequency.")

def _candidate(
    *,
    field: str,
    name: str,
    value: Any = None,
    reference: str = "",
    units: str,
    frequency: str,
    collateral: str,
    regime: str,
    estimator: str,
    dataset: str,
    columns: str,
    sample_size: int,
    uncertainty: Any,
    provenance: str = "empirical_estimation",
    notes: str = "",
) -> dict[str, Any]:
    return {
        "simulator_field": field,
        "estimate_name": name,
        "estimate_value": value,
        "distribution_reference": reference,
        "units": units,
        "simulation_frequency": frequency,
        "collateral_scope": collateral,
        "regime_scope": regime,
        "estimator": estimator,
        "input_dataset": dataset,
        "input_columns": columns,
        "estimation_window": (
            "[2021-06-01, 2024-07-01), excluding "
            "[2022-11-01, 2022-11-21)"
        ),
        "sample_size": sample_size,
        "uncertainty_measure": uncertainty,
        "validation_status": "candidate_validated_for_review",
        "provenance_classification": provenance,
        "implementation_status": (
            "estimated_not_adopted"
            if provenance == "empirical_estimation"
            else "extracted_not_adopted"
        ),
        "notes": notes,
        "review_required_before_adoption": True,
    }

def _build_candidates(
    outputs: dict[str, pd.DataFrame],
    market_details: dict[str, Any],
    regime_details: dict[str, Any],
    liquidation_details: dict[str, Any],
    *,
    random_seed: int,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    returns = outputs["market/return_distribution.csv"]
    uncertainty = outputs["market/return_bootstrap_uncertainty.csv"]
    calibration_all = returns.loc[
        returns["sample"].eq("calibration") & returns["regime"].eq("all")
    ]
    for _, row in calibration_all.iterrows():
        asset = row["asset"]
        if asset == "DAI":
            continue
        ci_rows = uncertainty.loc[uncertainty["asset"].eq(asset)]
        for estimate, field, units in (
            ("mean", "PriceProcessConfig.mu", "log_return_per_hour"),
            ("std", "PriceProcessConfig.sigma", "log_return_per_sqrt_hour"),
        ):
            ci = ci_rows.loc[ci_rows["estimate"].eq(estimate)].iloc[0]
            candidates.append(
                _candidate(
                    field=field,
                    name=f"{asset.lower()}_hourly_{estimate}",
                    value=float(row[estimate]),
                    units=units,
                    frequency="hourly",
                    collateral=asset,
                    regime="all_calibration",
                    estimator="Empirical moment",
                    dataset="Phase 1A processed market panel",
                    columns=f"{asset.lower()}_log_return",
                    sample_size=int(row["n"]),
                    uncertainty={
                        "method": "moving_block_bootstrap_95pct",
                        "lower": float(ci["lower"]),
                        "upper": float(ci["upper"]),
                        "replications": int(ci["replications"]),
                    },
                )
            )
        candidates.append(
            _candidate(
                field="price_path",
                name=f"{asset.lower()}_aligned_empirical_return_blocks",
                reference="market/return_block_index.csv",
                units="source_row_indices",
                frequency="hourly",
                collateral=asset,
                regime="mixed",
                estimator="Aligned moving-block empirical resampling",
                dataset="Phase 1A processed market panel",
                columns="timestamp_utc;eth_log_return;wbtc_log_return;usdc_log_return",
                sample_size=market_details["calibration_return_observations"],
                uncertainty={
                    "candidate_block_length_hours": market_details[
                        "candidate_block_length_hours"
                    ]
                },
            )
        )
        candidates.append(
            _candidate(
                field="shock_size",
                name=f"{asset.lower()}_hourly_lower_tail",
                reference="market/return_distribution.csv",
                units="log_return",
                frequency="hourly",
                collateral=asset,
                regime="all_calibration",
                estimator="Empirical q01 and q05 tail distribution",
                dataset="Phase 1A processed market panel",
                columns=f"{asset.lower()}_log_return",
                sample_size=int(row["n"]),
                uncertainty="See moving-block-bootstrap quantile intervals.",
                notes="A selected deterministic severity remains a scenario choice.",
            )
        )
    thresholds = regime_details["thresholds"]
    candidates.append(
        _candidate(
            field="market_regime",
            name="two_state_regime_rule",
            reference="regimes/hourly_regimes.csv",
            units="categorical_state",
            frequency="hourly",
            collateral="system",
            regime="normal_or_stress",
            estimator="At least two of six calibration-quantile conditions",
            dataset="Phase 1A–1C hourly panels",
            columns=(
                "ETH/WBTC returns;24h volatility;gas;DAI deviation;"
                "liquidation volume"
            ),
            sample_size=(
                regime_details["normal_hours"] + regime_details["stress_hours"]
            ),
            uncertainty="Threshold sensitivity retained for later review.",
        )
    )
    for field, name, value in (
        (
            "ConfidenceConfig.normal_lower_price",
            "dai_normal_lower_candidate",
            float(
                outputs["market/dai_peg_distribution.csv"]
                .query("sample == 'calibration' and variable == 'dai_price_usd'")
                .iloc[0]["q05"]
            ),
        ),
        (
            "ConfidenceConfig.normal_upper_price",
            "dai_normal_upper_candidate",
            float(
                outputs["market/dai_peg_distribution.csv"]
                .query("sample == 'calibration' and variable == 'dai_price_usd'")
                .iloc[0]["q95"]
            ),
        ),
        (
            "ConfidenceConfig.stress_lower_price",
            "dai_stress_lower_candidate",
            float(
                outputs["market/dai_peg_distribution.csv"]
                .query("sample == 'calibration' and variable == 'dai_price_usd'")
                .iloc[0]["q01"]
            ),
        ),
    ):
        candidates.append(
            _candidate(
                field=field,
                name=name,
                value=value,
                units="USD_per_DAI",
                frequency="hourly",
                collateral="DAI",
                regime="calibration",
                estimator="Registered empirical quantile",
                dataset="Phase 1A processed market panel",
                columns="dai_price_usd",
                sample_size=int(
                    outputs["market/dai_peg_distribution.csv"]
                    .query(
                        "sample == 'calibration' and variable == 'dai_price_usd'"
                    )
                    .iloc[0]["n"]
                ),
                uncertainty="Nearby-threshold sensitivity required.",
            )
        )
    gas_distribution = outputs["gas/gas_distribution.csv"]
    gas_units = {
        "median_effective_gas_price_gwei": "gwei",
        "p90_effective_gas_price_gwei": "gwei",
        "p99_effective_gas_price_gwei": "gwei",
        "median_base_fee_gwei": "gwei",
        "median_priority_fee_gwei": "gwei",
        "failed_transaction_share": "fraction",
        "target_normalised_block_utilisation": "target_multiple",
    }
    for variable, units in gas_units.items():
        row = gas_distribution.loc[
            gas_distribution["sample"].eq("calibration")
            & gas_distribution["regime"].eq("all")
            & gas_distribution["variable"].eq(variable)
        ].iloc[0]
        candidates.append(
            _candidate(
                field=f"gas_environment.{variable}",
                name=f"empirical_{variable}",
                reference="gas/gas_distribution.csv",
                units=units,
                frequency="hourly",
                collateral="Ethereum network",
                regime="normal_and_stress",
                estimator="Regime-conditional empirical distribution",
                dataset="Phase 1B processed gas panel",
                columns=variable,
                sample_size=int(row["n"]),
                uncertainty="Empirical q01–q99 range; no parametric fit adopted.",
                notes=(
                    "Gas environment candidate only; it is not a substitute "
                    "for liquidation-specific gas units."
                ),
            )
        )
    candidates.append(
        _candidate(
            field="gas_environment.empirical_sampling",
            name="aligned_hourly_gas_market_blocks",
            reference="gas/gas_sampling_index.csv",
            units="source_hour_indices",
            frequency="hourly",
            collateral="system",
            regime="mixed",
            estimator="Aligned empirical block-sampling representation",
            dataset="Phase 1B joined market–gas panel",
            columns=(
                "timestamp_utc;median/p90/p99 gas;utilisation;"
                "failed share;market regime"
            ),
            sample_size=market_details["calibration_return_observations"],
            uncertainty={
                "candidate_block_length_hours": market_details[
                    "candidate_block_length_hours"
                ]
            },
        )
    )
    candidates.append(
        _candidate(
            field="liquidation.arrival_process",
            name="hourly_liquidation_arrival_distribution",
            reference="liquidations/liquidation_count_models.csv",
            units="auctions_per_hour",
            frequency="hourly",
            collateral="exact_ilk_and_system",
            regime="normal_and_stress",
            estimator=(
                "Empirical distribution with Poisson and negative-binomial "
                "benchmarks"
            ),
            dataset="Phase 1C hourly liquidation panel",
            columns="timestamp_utc;ilk;auctions_initiated",
            sample_size=market_details["calibration_return_observations"],
            uncertainty="Zero frequency, dispersion and AIC diagnostics retained.",
            notes=(
                "The empirical zero-heavy representation remains primary; "
                "the count benchmarks are not automatically adopted."
            ),
        )
    )
    candidates.append(
        _candidate(
            field="liquidation.auction_duration",
            name="observed_auction_duration_distribution",
            reference="liquidations/auction_distribution.csv",
            units="seconds",
            frequency="auction",
            collateral="ETH-A/B/C and WBTC-A/B/C",
            regime="normal_and_stress",
            estimator="Empirical observed-duration distribution",
            dataset="Phase 1C auction summary",
            columns="bark_time_utc;observed_duration_seconds;ilk",
            sample_size=int(liquidation_details["calibration_auctions"]),
            uncertainty="Empirical collateral- and regime-specific quantiles.",
            notes="Open or unresolved lifecycles remain explicitly classified.",
        )
    )
    clean_cost = liquidation_details["clean_take_gas_cost_usd"]
    candidates.append(
        _candidate(
            field="LiquidationConfig.gas_cost",
            name="clean_take_transaction_gas_cost_usd",
            reference="liquidations/liquidation_transaction_gas.csv",
            units="USD_per_top_level_transaction",
            frequency="transaction",
            collateral="ETH-A/B/C and WBTC-A/B/C",
            regime="calibration",
            estimator="Empirical clean single-Take/single-auction distribution",
            dataset="Phase 1C transaction bridge joined to Phase 1A",
            columns="gas_used;gas_price;block_time;eth_price_usd",
            sample_size=int(clean_cost["n"]),
            uncertainty="Transaction-level empirical quantiles; adoption requires review.",
            notes=(
                "Top-level transaction cost; gas units, gas price and USD cost "
                "remain separate."
            ),
        )
    )
    capacity = liquidation_details["hourly_completion_capacity_calibration"]
    candidates.append(
        _candidate(
            field="LiquidationConfig.max_liquidations_per_step",
            name="observed_hourly_completion_capacity",
            reference="liquidations/hourly_liquidation_summary.csv",
            units="completed_auctions_per_hour",
            frequency="hourly",
            collateral="shared_system_capacity",
            regime="calibration",
            estimator="Empirical throughput distribution",
            dataset="Phase 1C hourly liquidation panel",
            columns="auctions_completed;successful_takes;unique_keepers",
            sample_size=int(capacity["n"]),
            uncertainty="Empirical q90/q95/q99; fixed cap remains reduced-form.",
        )
    )
    protocol_summary = outputs["protocol/protocol_parameter_summary.csv"]
    protocol_map = {
        "liquidation_ratio": (
            "CollateralConfig.liquidation_ratio",
            "ratio",
        ),
        "liquidation_penalty_rate": (
            "CollateralConfig.liquidation_penalty",
            "fraction_of_debt",
        ),
        "debt_ceiling_dai": ("protocol.debt_ceiling", "DAI"),
        "minimum_debt_dai": ("protocol.minimum_debt", "DAI"),
        "annualised_stability_fee": (
            "protocol.annualised_stability_fee",
            "annual_fraction",
        ),
        "auction_stopped": ("protocol.auction_stopped", "integer_state"),
    }
    for parameter, (field, units) in protocol_map.items():
        for ilk, group in protocol_summary.loc[
            protocol_summary["parameter"].eq(parameter)
        ].groupby("ilk"):
            row = group.iloc[0]
            candidates.append(
                _candidate(
                    field=field,
                    name=f"{ilk}_{parameter}_effective_history",
                    reference="protocol/protocol_parameter_summary.csv",
                    units=units,
                    frequency="effective_dated_hourly",
                    collateral=ilk,
                    regime="historical_replay",
                    estimator="Direct effective-state extraction",
                    dataset="Phase 1D hourly protocol panel",
                    columns=f"timestamp_utc;ilk;{parameter}",
                    sample_size=int(row["observed_hours"]),
                    uncertainty="Deterministic on-chain setting; no sampling interval.",
                    provenance="protocol_constant",
                    notes=(
                        "Time variation and exact-ilk identity are retained; "
                        "no pooled governance average is adopted."
                    ),
                )
            )
    payload = {
        "schema_version": 1,
        "phase": "2A",
        "random_seed": random_seed,
        "withheld_validation_window": (
            "[2022-11-01T00:00:00Z, 2022-11-21T00:00:00Z)"
        ),
        "candidates": candidates,
    }
    validate_candidate_registry(payload)
    return payload

def _write_outputs(
    output_dir: Path,
    outputs: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    records = []
    for relative, frame in sorted(outputs.items()):
        path = output_dir / relative
        _write_csv(path, frame)
        records.append(
            {
                "path": _relative(path),
                "rows": int(len(frame)),
                "columns": int(len(frame.columns)),
                "sha256": sha256_file(path),
            }
        )
    return records

def _write_figures(
    hourly: pd.DataFrame,
    outputs: dict[str, pd.DataFrame],
    figure_dir: Path,
) -> list[str]:
    os.environ.setdefault(
        "MPLCONFIGDIR",
        str(Path(tempfile.gettempdir()) / "dai-abm-matplotlib"),
    )
    import matplotlib.pyplot as plt

    figure_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    fig, ax = plt.subplots(figsize=(10, 3))
    stress = hourly["regime"].eq("stress").astype(int)
    ax.fill_between(hourly["timestamp_utc"], stress, step="post", alpha=0.7)
    ax.set(title="Phase 2A two-state empirical regime", ylabel="Stress")
    ax.set_yticks([0, 1])
    fig.tight_layout()
    path = figure_dir / "regime_timeline.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(_relative(path))

    calibration = hourly.loc[hourly["is_calibration"]]
    fig, ax = plt.subplots(figsize=(7, 4))
    groups = [
        calibration.loc[
            calibration["regime"].eq(label),
            "median_effective_gas_price_gwei",
        ].dropna()
        for label in ("normal", "stress")
    ]
    ax.boxplot(groups, tick_labels=["normal", "stress"], showfliers=False)
    ax.set(
        title="Median effective gas price by regime",
        ylabel="Gwei",
    )
    fig.tight_layout()
    path = figure_dir / "gas_by_regime.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(_relative(path))

    counts = outputs["liquidations/liquidation_count_models.csv"]
    total = counts.loc[
        counts["ilk"].eq("ALL") & counts["regime"].eq("all")
    ].iloc[0]
    fig, ax = plt.subplots(figsize=(7, 4))
    series = (
        hourly.loc[hourly["is_calibration"], "liquidation_volume_dai"] > 0
    ).astype(int)
    ax.bar(["zero liquidation", "positive liquidation"], [
        int((series == 0).sum()),
        int((series == 1).sum()),
    ])
    ax.set(
        title=(
            "Hourly liquidation activity "
            f"(dispersion index {total['dispersion_index']:.2f})"
        ),
        ylabel="Hours",
    )
    fig.tight_layout()
    path = figure_dir / "liquidation_activity.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(_relative(path))
    return paths

def _code_version() -> str:
    digest = hashlib.sha256()
    paths = sorted((PROJECT_ROOT / "src/estimation").glob("*.py"))
    paths.append(PROJECT_ROOT / "scripts/run_phase2a_parameter_estimation.py")
    for path in paths:
        if path.exists():
            digest.update(path.relative_to(PROJECT_ROOT).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()

def _write_report(
    path: Path,
    *,
    parameter_status: pd.DataFrame,
    regime_details: dict[str, Any],
    market_details: dict[str, Any],
    liquidation_details: dict[str, Any],
    output_records: list[dict[str, Any]],
    figure_paths: list[str],
) -> None:
    counts = parameter_status["current_status"].value_counts().to_dict()
    clean = liquidation_details["clean_take_gas_cost_usd"]
    text = f"""# Phase 2A Parameter Estimation Report

## Scope

Phase 2A estimates only quantities identifiable from the completed Phase
1A--1D market, gas, liquidation and protocol datasets. It does not alter
simulator configuration or estimate vault-owner behaviour. The authoritative
plan contains 56 numbered parameter subsections, although the commissioning
brief referred to 55; all 56 were audited.

## Datasets and sample split

The continuous hourly coverage is 2021-06-01 00:00 UTC to 2024-07-01 00:00
UTC, exclusive. The FTX interval 2022-11-01 to 2022-11-21 is withheld from all
thresholds and candidate estimates and is used only for validation
diagnostics. All inputs passed manifest dimension and SHA-256 checks.

## Implemented estimators

- aligned empirical ETH, WBTC, USDC and DAI hourly return distributions;
- Pearson, Spearman and covariance matrices by two-state regime;
- moving-block-bootstrap uncertainty and a {market_details['candidate_block_length_hours']}-hour candidate block;
- the documented two-of-six normal/stress classifier;
- gas-price, base-fee, priority-fee, utilisation and failure distributions;
- liquidation count overdispersion and Poisson/negative-binomial benchmarks;
- auction, throughput, keeper-transaction gas and USD-cost distributions; and
- exact-ilk, effective-dated Phase 1D protocol histories.

## Key candidate evidence

The calibration sample contains {regime_details['normal_hours']:,} normal hours
and {regime_details['stress_hours']:,} stress hours. Estimated stress entry,
exit and persistence probabilities are
{regime_details['stress_entry_probability']:.6f},
{regime_details['stress_exit_probability']:.6f} and
{regime_details['stress_persistence_probability']:.6f}, respectively.

There are {liquidation_details['clean_successful_take_transactions_calibration']:,}
clean successful-Take transactions in the calibration sample. Their
transaction-level USD gas-cost median is {clean['q50']:.4f}; this remains a
candidate distribution and has not been written to `LiquidationConfig`.

## Three-state assessment

The provisional four-condition panic candidate accounts for
{regime_details['panic_candidate_share']:.4%} of calibration hours across
{regime_details['panic_candidate_runs']} runs. A three-state model is not
adopted because incremental held-out improvement has not been demonstrated.

## Parameter status

The audit statuses are:

{chr(10).join(f'- `{key}`: {value}' for key, value in sorted(counts.items()))}

Blocked or deferred parameters have no numerical placeholders.

## Uncertainty and diagnostics

Moving-block-bootstrap percentile intervals use a fixed seed and {market_details['bootstrap_replications']}
replications. Count-model diagnostics retain the empirical distribution as the
primary representation where zero activity dominates. Protocol settings are
deterministic effective states rather than sampled averages.

The liquidation-volume calibration q90 is
{regime_details['thresholds']['liquidation_volume_q90']:.6g} DAI because
liquidation hours are sparse; the threshold is retained transparently rather
than adjusted after inspection. There are
{liquidation_details['zero_gas_price_successful_take_transactions']} successful
Take transactions with observed top-level gas price equal to zero. They remain
unchanged and require sensitivity review before a gas-cost candidate is
adopted.

Figures generated for review:

{chr(10).join(f'- `{item}`' for item in figure_paths) if figure_paths else '- None.'}

## Outputs

{chr(10).join(f"- `{record['path']}` ({record['rows']:,} x {record['columns']}, SHA-256 `{record['sha256']}`)" for record in output_records)}

## Limitations

Phase 2A cannot identify vault-size, leverage, owner intervention or
population-composition parameters without Phase 1E-B. Manager identities are
not beneficial-owner identities. Phase 1C bad debt is retained as a proxy.
Top-level transaction gas is not inner-call gas. Behavioural DAI, confidence,
panic and unobserved keeper-risk coefficients require later model calibration.

## Recommended next step

Review the candidate registry and threshold sensitivity, then acquire the
highest-information Phase 1E-B windows before estimating vault-population
parameters. Simulator YAML values and mechanics should remain unchanged until
that review is complete.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def run_phase2a(config: Phase2AConfig | None = None) -> dict[str, Any]:
    """Verify inputs, execute estimators and persist the Phase 2A bundle."""
    selected = config or Phase2AConfig()
    input_records = verify_all_inputs()
    frames = load_inputs()
    hourly = _prepare_hourly_panel(frames, selected)
    outputs: dict[str, pd.DataFrame] = {}
    parameter_status = build_parameter_status()
    outputs["parameter_status.csv"] = parameter_status
    market_outputs, market_details = _market_outputs(hourly, selected)
    outputs.update(market_outputs)
    regime_outputs, regime_details = _regime_outputs(hourly)
    outputs.update(regime_outputs)
    gas_outputs, gas_details = _gas_outputs(
        hourly, market_details["candidate_block_length_hours"]
    )
    outputs.update(gas_outputs)
    liquidation_outputs, liquidation_details = _liquidation_outputs(
        frames, hourly
    )
    outputs.update(liquidation_outputs)
    protocol_outputs, protocol_details = _protocol_outputs(frames)
    outputs.update(protocol_outputs)
    outputs["diagnostics/input_integrity.csv"] = pd.DataFrame(
        [
            {"input_name": name, **record, "validation_status": "passed"}
            for name, record in sorted(input_records.items())
        ]
    )
    split_rows = []
    for sample, mask in (
        ("calibration", hourly["is_calibration"]),
        ("withheld_validation_ftx", hourly["is_validation"]),
    ):
        selected_hours = hourly.loc[mask, "timestamp_utc"]
        split_rows.append(
            {
                "sample": sample,
                "hours": int(len(selected_hours)),
                "start_utc": selected_hours.min(),
                "end_utc": selected_hours.max(),
                "threshold_estimation_allowed": sample == "calibration",
            }
        )
    outputs["diagnostics/calibration_validation_split.csv"] = pd.DataFrame(
        split_rows
    )
    outputs["diagnostics/regime_thresholds.csv"] = pd.DataFrame(
        [
            {
                "threshold": name,
                "value": value,
                "estimated_from": "calibration_only",
                "withheld_ftx_used": False,
            }
            for name, value in regime_details["thresholds"].items()
        ]
    )
    outputs["diagnostics/validation_gates.csv"] = pd.DataFrame(
        [
            {
                "gate": "manifest_dimensions_and_checksums",
                "status": "passed",
                "details": f"{len(input_records)} inputs verified",
            },
            {
                "gate": "hourly_market_gas_alignment",
                "status": "passed",
                "details": f"{len(hourly)} exact UTC hours",
            },
            {
                "gate": "withheld_threshold_leakage",
                "status": "passed",
                "details": "FTX hours excluded before threshold estimation",
            },
            {
                "gate": "blocked_parameter_values",
                "status": "passed",
                "details": (
                    f"{int(parameter_status['current_status'].isin([
                        'blocked_pending_phase1e_b',
                        'requires_model_calibration',
                    ]).sum())} blocked or deferred rows have no candidates"
                ),
            },
            {
                "gate": "protocol_interval_overlap",
                "status": "passed",
                "details": (
                    f"{protocol_details['validated_interval_rows']} intervals "
                    "validated"
                ),
            },
        ]
    )
    output_records = _write_outputs(selected.output_dir, outputs)
    registry = _build_candidates(
        outputs,
        market_details,
        regime_details,
        liquidation_details,
        random_seed=selected.random_seed,
    )
    registry_path = selected.output_dir / "phase2a_candidate_parameters.json"
    _write_json(registry_path, registry)
    registry_record = {
        "path": _relative(registry_path),
        "sha256": sha256_file(registry_path),
        "rows": len(registry["candidates"]),
        "columns": len(REQUIRED_CANDIDATE_FIELDS),
        "candidates": len(registry["candidates"]),
    }
    figure_paths = (
        _write_figures(hourly, outputs, selected.figure_dir)
        if selected.write_figures
        else []
    )
    metadata = {
        "phase": "2A",
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            text=True,
        ).strip(),
        "branch": subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "branch", "--show-current"],
            text=True,
        ).strip(),
        "input_paths": {
            name: record["path"] for name, record in input_records.items()
        },
        "input_checksums": {
            name: record["sha256"] for name, record in input_records.items()
        },
        "input_dimensions": {
            name: [record["rows"], record["columns"]]
            for name, record in input_records.items()
        },
        "code_version_sha256": _code_version(),
        "random_seed": selected.random_seed,
        "bootstrap_replications": selected.bootstrap_replications,
        "calibration_window": (
            "[2021-06-01T00:00:00Z, 2024-07-01T00:00:00Z) "
            "excluding the withheld interval"
        ),
        "withheld_validation_window": (
            "[2022-11-01T00:00:00Z, 2022-11-21T00:00:00Z)"
        ),
        "estimators_executed": [
            "empirical_distribution",
            "moving_block_bootstrap",
            "two_state_regime_classifier",
            "pearson_and_spearman_dependence",
            "poisson_and_negative_binomial_benchmarks",
            "transaction_level_gas_cost",
            "effective_dated_protocol_extraction",
        ],
        "outputs": output_records + [registry_record],
        "warnings": [
            (
                "The authoritative plan contains 56 numbered subsections; "
                "the commissioning brief referred to 55."
            ),
            "FTX observations are withheld from every calibration estimate.",
            (
                "The calibration liquidation-volume q90 threshold is zero "
                "because hourly liquidation activity is highly sparse; any "
                "positive volume activates that condition."
            ),
            (
                f"{liquidation_details[
                    'zero_gas_price_successful_take_transactions'
                ]} successful-Take transactions have an observed top-level "
                "gas price of zero and remain unchanged for sensitivity review."
            ),
            "Phase 1E-B-dependent parameters have no candidate values.",
            "Bad debt remains an explicitly labelled Phase 1C proxy.",
            "No simulator configuration value has been modified.",
        ],
        "failures": [],
        "details": {
            "market": market_details,
            "regimes": regime_details,
            "gas": gas_details,
            "liquidations": liquidation_details,
            "protocol": protocol_details,
        },
    }
    metadata_path = selected.output_dir / "estimation_run_metadata.json"
    _write_json(metadata_path, metadata)
    if selected.write_report:
        _write_report(
            selected.report_path,
            parameter_status=parameter_status,
            regime_details=regime_details,
            market_details=market_details,
            liquidation_details=liquidation_details,
            output_records=output_records + [registry_record],
            figure_paths=figure_paths,
        )
    return {
        "metadata_path": _relative(metadata_path),
        "registry_path": _relative(registry_path),
        "parameter_count": len(parameter_status),
        "candidate_count": len(registry["candidates"]),
        "outputs": output_records,
        "figures": figure_paths,
        "details": metadata["details"],
    }
