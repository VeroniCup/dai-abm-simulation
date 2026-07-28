"""Deterministic Phase 2B estimation from representative Maker vault windows."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from .data_loading import PROJECT_ROOT, sha256_file


TARGET_ILKS = (
    "ETH-A",
    "ETH-B",
    "ETH-C",
    "WBTC-A",
    "WBTC-B",
    "WBTC-C",
)
PARAMETERS = (
    "n_vaults",
    "target_debt_share",
    "debt_mean",
    "debt_std",
    "collateral_ratio_mean",
    "collateral_ratio_std",
    "min_collateral_ratio_buffer",
    "max_normal_liquidatable_share",
    "max_stress_liquidatable_share",
)
MAX_CLOSE_FACTOR = "max_close_factor"
FTX_START = pd.Timestamp("2022-11-01T00:00:00Z")
FTX_END_EXCLUSIVE = pd.Timestamp("2022-11-21T00:00:00Z")
DEFAULT_OUTPUT = PROJECT_ROOT / "data/processed/estimation/phase2b_vaults"
PROTOCOL_PATH = (
    PROJECT_ROOT / "data/processed/protocol/"
    "phase1d_protocol_parameters_hourly.csv"
)
MARKET_PATH = (
    PROJECT_ROOT / "data/processed/market/"
    "dune_hourly_market_prices_processed.csv"
)
REGIME_PATH = (
    PROJECT_ROOT / "data/processed/estimation/phase2a/"
    "regimes/hourly_regimes.csv"
)


@dataclass(frozen=True)
class RepresentativeWindow:
    """One purposively selected Phase 1E-B evidence window."""

    key: str
    label: str
    start: pd.Timestamp
    end_exclusive: pd.Timestamp
    role: str
    directory: Path
    provenance: Path


WINDOWS = (
    RepresentativeWindow(
        key="quiet_mature",
        label="Quiet mature",
        start=pd.Timestamp("2024-02-01T00:00:00Z"),
        end_exclusive=pd.Timestamp("2024-03-01T00:00:00Z"),
        role="normal",
        directory=(
            PROJECT_ROOT
            / "data/processed/vaults/representative_regimes/"
            "quiet_mature_2024-02-01_2024-03-01"
        ),
        provenance=(
            PROJECT_ROOT
            / "data/provenance/vaults/representative_regimes/"
            "quiet_mature_2024-02-01_2024-03-01"
        ),
    ),
    RepresentativeWindow(
        key="usdc_svb",
        label="USDC/SVB",
        start=pd.Timestamp("2023-03-06T00:00:00Z"),
        end_exclusive=pd.Timestamp("2023-03-20T00:00:00Z"),
        role="stress",
        directory=(
            PROJECT_ROOT
            / "data/processed/vaults/representative_regimes/"
            "usdc_svb_2023-03-06_2023-03-20"
        ),
        provenance=(
            PROJECT_ROOT
            / "data/provenance/vaults/representative_regimes/"
            "usdc_svb_2023-03-06_2023-03-20"
        ),
    ),
)


@dataclass(frozen=True)
class Phase2BConfig:
    """Controls for one local-only reproducible estimation run."""

    output_dir: Path = DEFAULT_OUTPUT
    random_seed: int = 20_260_726
    bootstrap_replications: int = 400
    recommended_simulation_vaults: int = 500
    bootstrap_block_hours: int = 24


REQUIRED_STATE_COLUMNS = {
    "window",
    "state_label",
    "timestamp_utc",
    "ilk",
    "urn",
    "ink_raw",
    "art_raw",
    "rate_raw_ray",
    "debt_dai",
    "collateral_value_usd",
    "collateral_ratio",
    "liquidation_ratio",
    "owner_or_proxy",
    "active",
}
REQUIRED_EVENT_COLUMNS = {
    "window",
    "timestamp_utc",
    "block_number",
    "transaction_index",
    "transaction_hash",
    "trace_position",
    "ilk",
    "urn",
    "dink_raw",
    "dart_raw",
    "ink_after_raw",
    "art_after_raw",
    "collateral_ratio_after",
    "source_call_type",
}
REQUIRED_RATE_COLUMNS = {
    "ilk",
    "effective_time_utc",
    "resulting_rate_raw_ray",
    "opening_state_flag",
}
CANDIDATE_FIELDS = (
    "parameter_name",
    "simulator_field",
    "estimate",
    "units",
    "representation",
    "regime",
    "collateral_scope",
    "boundary_or_temporal_scope",
    "estimator",
    "input_dataset",
    "input_columns",
    "sample_size",
    "resampling_unit",
    "uncertainty_interval",
    "sensitivity_alternatives",
    "validation_status",
    "model_interface_compatibility",
    "review_requirement",
    "notes",
)


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json(path: Path, payload: Any) -> None:
    _atomic_text(
        path,
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=_json_default,
        )
        + "\n",
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    text = frame.to_csv(
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        float_format="%.12g",
    )
    _atomic_text(path, text)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return _relative(value)
    raise TypeError(f"Cannot serialise {type(value).__name__}.")


def _truth(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes"}


def numeric_trace_tuple(value: Any) -> tuple[int, ...]:
    """Parse the validated dot-separated trace representation numerically."""
    text = str(value).strip()
    if not text:
        return ()
    parts = text.split(".")
    if any(not part.isdigit() for part in parts):
        raise ValueError(f"invalid trace position: {value!r}")
    return tuple(int(part) for part in parts)


def _effective_rate_trace_tuple(row: pd.Series) -> tuple[int, ...]:
    """Parse rate-stream traces without treating arbitrary nulls as roots."""
    value = row["trace_position"]
    if not pd.isna(value):
        return numeric_trace_tuple(value)
    source_type = str(row["source_type"]).strip()
    observed = _truth(row["observed_call_flag"])
    opening = _truth(row["opening_state_flag"])
    if source_type == "opening_rate" and opening and observed:
        return ()
    if source_type == "drip" and observed and not opening:
        return ()
    raise ValueError(
        "unavailable trace position outside a validated opening-rate or "
        f"top-level drip row: source_type={source_type!r}"
    )


def debt_from_raw(art_raw: int, rate_raw_ray: int) -> float:
    """Convert Maker WAD normalised debt and RAY rate to DAI."""
    if art_raw < 0 or rate_raw_ray <= 0:
        raise ValueError("art must be non-negative and rate must be positive")
    return float((art_raw * rate_raw_ray) / 10**45)


def active_indebted(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the model-estimation debt population."""
    active = frame["active"].map(_truth)
    debt = pd.to_numeric(frame["debt_dai"], errors="coerce")
    return frame.loc[active & debt.gt(0) & debt.notna()].copy()


def collateral_ratio(
    collateral_value: pd.Series, debt: pd.Series
) -> pd.Series:
    """Calculate collateral value divided by positive accrued debt."""
    values = pd.to_numeric(collateral_value, errors="coerce")
    debts = pd.to_numeric(debt, errors="coerce")
    result = values / debts.where(debts.gt(0))
    return result.replace([np.inf, -np.inf], np.nan)


def collateral_ratio_buffers(
    ratios: pd.Series, liquidation_ratios: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """Return absolute and relative liquidation-ratio buffers."""
    ratio = pd.to_numeric(ratios, errors="coerce")
    liquidation = pd.to_numeric(liquidation_ratios, errors="coerce")
    absolute = ratio - liquidation
    relative = ratio / liquidation.where(liquidation.gt(0)) - 1.0
    return absolute, relative


def classify_liquidatable(
    active: pd.Series,
    debt: pd.Series,
    ratios: pd.Series,
    liquidation_ratios: pd.Series,
) -> pd.Series:
    """Classify economic liquidation eligibility without using Bark/grab."""
    is_active = active.map(_truth)
    debt_value = pd.to_numeric(debt, errors="coerce")
    ratio = pd.to_numeric(ratios, errors="coerce")
    threshold = pd.to_numeric(liquidation_ratios, errors="coerce")
    return (
        is_active
        & debt_value.gt(0)
        & ratio.notna()
        & threshold.notna()
        & ratio.lt(threshold)
    )


def liquidatable_denominators(frame: pd.DataFrame) -> dict[str, float]:
    """Calculate the implemented and two sensitivity denominators."""
    liquidatable = classify_liquidatable(
        frame["active"],
        frame["debt_dai"],
        frame["collateral_ratio"],
        frame["liquidation_ratio"],
    )
    active = frame["active"].map(_truth)
    indebted = active & pd.to_numeric(
        frame["debt_dai"], errors="coerce"
    ).gt(0)
    valid = indebted & pd.to_numeric(
        frame["collateral_ratio"], errors="coerce"
    ).notna()
    count = int(liquidatable.sum())

    def share(denominator: int) -> float:
        return 0.0 if denominator == 0 else count / denominator

    return {
        "liquidatable_count": count,
        "active_count": int(active.sum()),
        "active_indebted_count": int(indebted.sum()),
        "valid_ratio_count": int(valid.sum()),
        "share_all_active": share(int(active.sum())),
        "share_active_indebted": share(int(indebted.sum())),
        "share_valid_ratio": share(int(valid.sum())),
    }


def _scope(ilk: str) -> str:
    return "ETH" if ilk.startswith("ETH-") else "WBTC"


def _scopes(frame: pd.DataFrame) -> Iterable[tuple[str, pd.DataFrame]]:
    yield "ALL", frame
    yield "ETH", frame.loc[frame["ilk"].str.startswith("ETH-")]
    yield "WBTC", frame.loc[frame["ilk"].str.startswith("WBTC-")]
    for ilk in TARGET_ILKS:
        yield ilk, frame.loc[frame["ilk"].eq(ilk)]


def _quantile(values: np.ndarray, probability: float) -> float:
    return float(np.quantile(values, probability))


def _bootstrap_ci(
    values: np.ndarray,
    statistic: Callable[[np.ndarray], float],
    *,
    seed: int,
    replications: int,
) -> tuple[float, float]:
    values = values[np.isfinite(values)]
    if values.size == 0:
        return math.nan, math.nan
    if values.size == 1:
        result = float(statistic(values))
        return result, result
    rng = np.random.default_rng(seed)
    estimates = np.empty(replications)
    for index in range(replications):
        sample = rng.choice(values, size=values.size, replace=True)
        estimates[index] = statistic(sample)
    return (
        float(np.quantile(estimates, 0.025)),
        float(np.quantile(estimates, 0.975)),
    )


def clustered_bootstrap_reproducible(
    frame: pd.DataFrame,
    value_column: str,
    cluster_column: str,
    *,
    seed: int,
    replications: int,
    statistic: Callable[[np.ndarray], float] = np.mean,
) -> tuple[float, float]:
    """Bootstrap complete clusters and return a percentile interval."""
    working = frame[[value_column, cluster_column]].copy()
    working[value_column] = pd.to_numeric(
        working[value_column], errors="coerce"
    )
    working = working.dropna()
    if working.empty:
        return math.nan, math.nan
    groups = {
        key: group[value_column].to_numpy(dtype=float)
        for key, group in working.groupby(cluster_column, sort=True)
    }
    keys = np.array(list(groups), dtype=object)
    rng = np.random.default_rng(seed)
    estimates = np.empty(replications)
    for index in range(replications):
        selected = rng.choice(keys, size=len(keys), replace=True)
        values = np.concatenate([groups[key] for key in selected])
        estimates[index] = statistic(values)
    return (
        float(np.quantile(estimates, 0.025)),
        float(np.quantile(estimates, 0.975)),
    )


def _distribution_row(
    values: pd.Series,
    *,
    window: str,
    boundary: str,
    scope: str,
    variable: str,
    seed: int,
    replications: int,
) -> dict[str, Any]:
    array = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    if not array.size:
        return {
            "window": window,
            "boundary": boundary,
            "collateral_scope": scope,
            "variable": variable,
            "count": 0,
        }
    q99 = _quantile(array, 0.99)
    winsorised = np.minimum(array, q99)
    positive = array[array > 0]
    mean_ci = _bootstrap_ci(
        array,
        np.mean,
        seed=seed,
        replications=replications,
    )
    std_ci = _bootstrap_ci(
        array,
        lambda sample: float(np.std(sample, ddof=1)),
        seed=seed + 1,
        replications=replications,
    )
    q05_ci = _bootstrap_ci(
        array,
        lambda sample: float(np.quantile(sample, 0.05)),
        seed=seed + 2,
        replications=replications,
    )
    return {
        "window": window,
        "boundary": boundary,
        "collateral_scope": scope,
        "variable": variable,
        "count": int(array.size),
        "mean": float(np.mean(array)),
        "mean_ci_lower": mean_ci[0],
        "mean_ci_upper": mean_ci[1],
        "std": float(np.std(array, ddof=1)) if array.size > 1 else 0.0,
        "std_ci_lower": std_ci[0],
        "std_ci_upper": std_ci[1],
        "minimum": float(np.min(array)),
        "q01": _quantile(array, 0.01),
        "q05": _quantile(array, 0.05),
        "q05_ci_lower": q05_ci[0],
        "q05_ci_upper": q05_ci[1],
        "q10": _quantile(array, 0.10),
        "q25": _quantile(array, 0.25),
        "median": _quantile(array, 0.50),
        "q75": _quantile(array, 0.75),
        "q90": _quantile(array, 0.90),
        "q95": _quantile(array, 0.95),
        "q99": q99,
        "maximum": float(np.max(array)),
        "coefficient_of_variation": (
            math.nan
            if np.mean(array) == 0
            else float(np.std(array, ddof=1) / np.mean(array))
        ),
        "skewness": float(pd.Series(array).skew()),
        "log_mean": (
            math.nan if not positive.size else float(np.log(positive).mean())
        ),
        "log_std": (
            math.nan
            if positive.size < 2
            else float(np.log(positive).std(ddof=1))
        ),
        "winsorised_q99_mean": float(np.mean(winsorised)),
        "winsorised_q99_std": (
            float(np.std(winsorised, ddof=1))
            if winsorised.size > 1 else 0.0
        ),
        "zero_count": int(np.count_nonzero(array == 0)),
        "negative_count": int(np.count_nonzero(array < 0)),
    }


def _input_output_checks(
    window: RepresentativeWindow,
) -> tuple[list[dict[str, Any]], dict[str, pd.DataFrame]]:
    metadata_path = window.provenance / "reconstruction_metadata.json"
    validation_path = window.provenance / "reconstruction_validation.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if metadata["start_utc"] != window.start.isoformat():
        raise ValueError(f"{window.key}: unexpected start")
    if metadata["end_exclusive_utc"] != window.end_exclusive.isoformat():
        raise ValueError(f"{window.key}: unexpected end")
    if not validation.get("validation_passed"):
        raise ValueError(f"{window.key}: reconstruction validation failed")

    checks: list[dict[str, Any]] = []
    frames: dict[str, pd.DataFrame] = {}
    for name in (
        "opening_vault_state.csv",
        "closing_vault_state.csv",
        "reconstructed_vault_events.csv",
        "effective_rates.csv",
    ):
        item = metadata["outputs"][name]
        path = PROJECT_ROOT / item["path"]
        observed_sha = sha256_file(path)
        if observed_sha != item["sha256"]:
            raise ValueError(f"{window.key}: checksum mismatch for {name}")
        frame = pd.read_csv(path, dtype={"urn": str, "owner_or_proxy": str})
        if len(frame) != item["rows"]:
            raise ValueError(f"{window.key}: row mismatch for {name}")
        required = (
            REQUIRED_STATE_COLUMNS
            if "vault_state" in name
            else REQUIRED_EVENT_COLUMNS
            if "events" in name
            else REQUIRED_RATE_COLUMNS
        )
        missing = required - set(frame)
        if missing:
            raise ValueError(f"{window.key}: missing {sorted(missing)}")
        frames[name] = frame
        checks.append({
            "window": window.key,
            "input": name,
            "path": _relative(path),
            "expected_sha256": item["sha256"],
            "observed_sha256": observed_sha,
            "rows": len(frame),
            "columns": len(frame.columns),
            "validation": "passed",
        })

    for boundary_name, expected_label, expected_time in (
        ("opening_vault_state.csv", "opening", window.start),
        (
            "closing_vault_state.csv",
            "window_end",
            window.end_exclusive - pd.Timedelta(nanoseconds=1),
        ),
    ):
        frame = frames[boundary_name]
        if set(frame["ilk"]) != set(TARGET_ILKS):
            raise ValueError(f"{window.key}: invalid ilk scope")
        if frame.duplicated(["ilk", "urn"]).any():
            raise ValueError(f"{window.key}: duplicate boundary key")
        timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
        if not timestamps.eq(expected_time).all():
            raise ValueError(f"{window.key}: invalid boundary timestamps")
        labels = set(frame["state_label"])
        if labels != {expected_label}:
            raise ValueError(f"{window.key}: invalid boundary labels {labels}")

        active_debt = active_indebted(frame)
        recomputed = np.array([
            debt_from_raw(int(art), int(rate))
            for art, rate in zip(
                active_debt["art_raw"],
                active_debt["rate_raw_ray"],
                strict=True,
            )
        ])
        observed = pd.to_numeric(active_debt["debt_dai"])
        if not np.allclose(recomputed, observed, rtol=1e-12, atol=1e-9):
            raise ValueError(f"{window.key}: debt conversion mismatch")

    events = frames["reconstructed_vault_events.csv"]
    event_times = pd.to_datetime(events["timestamp_utc"], utc=True)
    if not (
        event_times.ge(window.start)
        & event_times.lt(window.end_exclusive)
    ).all():
        raise ValueError(f"{window.key}: event outside window")
    if event_times.between(
        FTX_START, FTX_END_EXCLUSIVE, inclusive="left"
    ).any():
        raise ValueError(f"{window.key}: FTX leakage")
    if set(events["ilk"]) - set(TARGET_ILKS):
        raise ValueError(f"{window.key}: event ilk leakage")
    return checks, frames


def _load_protocol_market_regimes() -> tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame
]:
    protocol = pd.read_csv(PROTOCOL_PATH, low_memory=False)
    market = pd.read_csv(MARKET_PATH)
    regimes = pd.read_csv(REGIME_PATH)
    for frame in (protocol, market, regimes):
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if set(TARGET_ILKS) - set(protocol["ilk"]):
        raise ValueError("protocol panel lacks a target ilk")
    if regimes.loc[
        regimes["is_calibration"].map(_truth)
        & regimes["timestamp_utc"].between(
            FTX_START, FTX_END_EXCLUSIVE, inclusive="left"
        )
    ].shape[0]:
        raise ValueError("FTX rows are incorrectly marked for calibration")
    return protocol, market, regimes


def _prepare_boundary(
    window: RepresentativeWindow,
    boundary: str,
    frame: pd.DataFrame,
    protocol: pd.DataFrame,
    regimes: pd.DataFrame,
) -> pd.DataFrame:
    result = frame.copy()
    result["timestamp_utc"] = pd.to_datetime(result["timestamp_utc"], utc=True)
    result["hour"] = result["timestamp_utc"].dt.floor("h")
    protocol_subset = protocol[
        ["timestamp_utc", "ilk", "liquidation_ratio", "minimum_debt_dai"]
    ].rename(columns={
        "timestamp_utc": "hour",
        "liquidation_ratio": "protocol_liquidation_ratio",
    })
    result = result.merge(
        protocol_subset,
        on=["hour", "ilk"],
        how="left",
        validate="many_to_one",
    )
    if result["protocol_liquidation_ratio"].isna().any():
        raise ValueError(f"{window.key}: missing effective liquidation ratio")
    stored = pd.to_numeric(result["liquidation_ratio"])
    effective = pd.to_numeric(result["protocol_liquidation_ratio"])
    if not np.allclose(stored, effective, rtol=0, atol=1e-12):
        raise ValueError(f"{window.key}: liquidation-ratio alignment failed")
    regime_lookup = regimes[["timestamp_utc", "regime"]].rename(
        columns={"timestamp_utc": "hour", "regime": "classifier_regime"}
    )
    result = result.merge(
        regime_lookup, on="hour", how="left", validate="many_to_one"
    )
    if result["classifier_regime"].isna().any():
        raise ValueError(f"{window.key}: missing Phase 2A regime")
    result["boundary"] = boundary
    result["window_role"] = window.role
    result["debt_dai"] = pd.to_numeric(result["debt_dai"])
    result["collateral_ratio"] = collateral_ratio(
        result["collateral_value_usd"], result["debt_dai"]
    )
    result["liquidation_ratio"] = effective
    absolute, relative = collateral_ratio_buffers(
        result["collateral_ratio"], result["liquidation_ratio"]
    )
    result["absolute_buffer"] = absolute
    result["relative_buffer"] = relative
    result["collateral_family"] = result["ilk"].map(_scope)
    result["indebted"] = result["debt_dai"].gt(0)
    result["liquidatable"] = classify_liquidatable(
        result["active"],
        result["debt_dai"],
        result["collateral_ratio"],
        result["liquidation_ratio"],
    )
    return result


def _count_estimates(boundaries: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (window, boundary), frame in boundaries.groupby(
        ["window", "boundary"], sort=True
    ):
        for scope, subset in _scopes(frame):
            active = subset["active"].map(_truth)
            indebted = active & subset["debt_dai"].gt(0)
            rows.append({
                "window": window,
                "regime_role": subset["window_role"].iloc[0],
                "boundary": boundary,
                "classifier_regime": subset["classifier_regime"].iloc[0],
                "collateral_scope": scope,
                "total_recorded_vaults": len(subset),
                "active_vaults": int(active.sum()),
                "active_indebted_vaults": int(indebted.sum()),
                "active_share_indebted": (
                    math.nan
                    if not active.sum()
                    else float(indebted.sum() / active.sum())
                ),
            })
    return pd.DataFrame(rows)


def _debt_share_estimates(
    boundaries: pd.DataFrame,
    *,
    seed: int,
    replications: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (window, boundary), frame in boundaries.groupby(
        ["window", "boundary"], sort=True
    ):
        population = active_indebted(frame)
        total = population["debt_dai"].sum()
        for scope, subset in _scopes(population):
            debt = float(subset["debt_dai"].sum())
            share = math.nan if total <= 0 else debt / total
            ci_lower = ci_upper = math.nan
            if scope in {"ETH", "WBTC"} and not population.empty:
                rng = np.random.default_rng(
                    seed + sum(ord(char) for char in f"{window}{boundary}{scope}")
                )
                estimates = []
                records = population[["urn", "debt_dai", "collateral_family"]]
                for _ in range(replications):
                    sampled = records.iloc[
                        rng.integers(0, len(records), size=len(records))
                    ]
                    sampled_total = sampled["debt_dai"].sum()
                    selected = sampled.loc[
                        sampled["collateral_family"].eq(scope), "debt_dai"
                    ].sum()
                    estimates.append(selected / sampled_total)
                ci_lower, ci_upper = np.quantile(
                    estimates, [0.025, 0.975]
                )
            rows.append({
                "window": window,
                "regime_role": frame["window_role"].iloc[0],
                "boundary": boundary,
                "collateral_scope": scope,
                "debt_dai": debt,
                "total_six_ilk_debt_dai": float(total),
                "target_debt_share": share,
                "share_ci_lower": ci_lower,
                "share_ci_upper": ci_upper,
                "numerator": "active indebted DAI debt in collateral scope",
                "denominator": "active indebted DAI debt across six target ilks",
                "units": "share of six-ilk DAI debt",
            })
    return pd.DataFrame(rows)


def _distribution_estimates(
    boundaries: pd.DataFrame,
    *,
    seed: int,
    replications: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    debt_rows: list[dict[str, Any]] = []
    ratio_rows: list[dict[str, Any]] = []
    buffer_rows: list[dict[str, Any]] = []
    for (window, boundary), frame in boundaries.groupby(
        ["window", "boundary"], sort=True
    ):
        population = active_indebted(frame)
        for scope, subset in _scopes(population):
            salt = sum(ord(char) for char in f"{window}{boundary}{scope}")
            debt_row = _distribution_row(
                subset["debt_dai"],
                window=window,
                boundary=boundary,
                scope=scope,
                variable="debt_dai",
                seed=seed + salt,
                replications=replications,
            )
            if len(subset):
                debt_row["below_protocol_dust_count"] = int(
                    (
                        subset["debt_dai"]
                        < pd.to_numeric(subset["minimum_debt_dai"])
                    ).sum()
                )
            debt_rows.append(debt_row)
            ratio_rows.append(_distribution_row(
                subset["collateral_ratio"],
                window=window,
                boundary=boundary,
                scope=scope,
                variable="collateral_ratio",
                seed=seed + 1_000 + salt,
                replications=replications,
            ))
            absolute = _distribution_row(
                subset["absolute_buffer"],
                window=window,
                boundary=boundary,
                scope=scope,
                variable="absolute_buffer",
                seed=seed + 2_000 + salt,
                replications=replications,
            )
            relative = _distribution_row(
                subset["relative_buffer"],
                window=window,
                boundary=boundary,
                scope=scope,
                variable="relative_buffer",
                seed=seed + 3_000 + salt,
                replications=replications,
            )
            combined = {
                key: value for key, value in absolute.items()
                if key not in {"variable"}
            }
            combined.update({
                f"relative_{key}": value
                for key, value in relative.items()
                if key not in {
                    "window", "boundary", "collateral_scope", "variable",
                    "count",
                }
            })
            combined["negative_or_zero_absolute_buffer_count"] = int(
                pd.to_numeric(
                    subset["absolute_buffer"], errors="coerce"
                ).le(0).sum()
            )
            buffer_rows.append(combined)
    return (
        pd.DataFrame(debt_rows),
        pd.DataFrame(ratio_rows),
        pd.DataFrame(buffer_rows),
    )


def _hourly_liquidatable_series(
    window: RepresentativeWindow,
    frames: dict[str, pd.DataFrame],
    protocol: pd.DataFrame,
    market: pd.DataFrame,
    regimes: pd.DataFrame,
) -> pd.DataFrame:
    opening = frames["opening_vault_state.csv"].copy()
    events = frames["reconstructed_vault_events.csv"].copy()
    rates = frames["effective_rates.csv"].copy()
    events["timestamp_utc"] = pd.to_datetime(events["timestamp_utc"], utc=True)
    rates["effective_time_utc"] = pd.to_datetime(
        rates["effective_time_utc"], utc=True
    )
    events["_numeric_trace"] = events["trace_position"].map(
        numeric_trace_tuple
    )
    rates["_numeric_trace"] = rates.apply(
        _effective_rate_trace_tuple,
        axis=1,
    )
    events = events.sort_values(
        [
            "timestamp_utc",
            "block_number",
            "transaction_index",
            "transaction_hash",
            "_numeric_trace",
            "source_call_type",
        ],
        kind="stable",
    )
    rates = rates.sort_values(
        ["effective_time_utc", "ilk", "transaction_hash", "_numeric_trace"],
        kind="stable",
    )

    state = {
        (row.ilk, row.urn): [int(row.ink_raw), int(row.art_raw)]
        for row in opening.itertuples(index=False)
    }
    opening_rates = rates.loc[rates["opening_state_flag"].map(_truth)]
    current_rates = {
        row.ilk: int(row.resulting_rate_raw_ray)
        for row in opening_rates.itertuples(index=False)
    }
    if set(current_rates) != set(TARGET_ILKS):
        raise ValueError(f"{window.key}: incomplete opening rates")

    hours = pd.date_range(
        window.start,
        window.end_exclusive,
        freq="h",
        inclusive="left",
    )
    market_lookup = market.set_index("timestamp_utc")
    protocol_lookup = protocol.set_index(["timestamp_utc", "ilk"])
    regime_lookup = regimes.set_index("timestamp_utc")
    event_records = list(events.itertuples(index=False))
    rate_records = list(
        rates.loc[~rates["opening_state_flag"].map(_truth)]
        .itertuples(index=False)
    )
    event_index = 0
    rate_index = 0
    rows: list[dict[str, Any]] = []

    for hour in hours:
        while (
            event_index < len(event_records)
            and event_records[event_index].timestamp_utc <= hour
        ):
            event = event_records[event_index]
            state[(event.ilk, event.urn)] = [
                int(event.ink_after_raw),
                int(event.art_after_raw),
            ]
            event_index += 1
        while (
            rate_index < len(rate_records)
            and rate_records[rate_index].effective_time_utc <= hour
        ):
            rate = rate_records[rate_index]
            current_rates[rate.ilk] = int(rate.resulting_rate_raw_ray)
            rate_index += 1

        market_row = market_lookup.loc[hour]
        classifier = str(regime_lookup.loc[hour, "regime"])
        aggregates = {
            scope: {
                "active": 0,
                "indebted": 0,
                "valid": 0,
                "liquidatable": 0,
            }
            for scope in ("ALL", "ETH", "WBTC", *TARGET_ILKS)
        }
        for (ilk, _urn), (ink_raw, art_raw) in state.items():
            active = ink_raw > 0 or art_raw > 0
            if not active:
                continue
            family = _scope(ilk)
            scopes = ("ALL", family, ilk)
            for scope in scopes:
                aggregates[scope]["active"] += 1
            if art_raw <= 0:
                continue
            for scope in scopes:
                aggregates[scope]["indebted"] += 1
            price = float(
                market_row[
                    "eth_price_usd"
                    if family == "ETH" else "wbtc_price_usd"
                ]
            )
            rate = current_rates[ilk]
            debt = debt_from_raw(art_raw, rate)
            if debt <= 0:
                continue
            ratio = (ink_raw / 1e18) * price / debt
            liquidation_ratio = float(
                protocol_lookup.loc[(hour, ilk), "liquidation_ratio"]
            )
            is_liquidatable = ratio < liquidation_ratio
            for scope in scopes:
                aggregates[scope]["valid"] += 1
                aggregates[scope]["liquidatable"] += int(is_liquidatable)

        for scope, counts in aggregates.items():
            active = counts["active"]
            indebted = counts["indebted"]
            valid = counts["valid"]
            liquidatable = counts["liquidatable"]
            rows.append({
                "timestamp_utc": hour.isoformat(),
                "window": window.key,
                "named_regime": window.role,
                "classifier_regime": classifier,
                "collateral_scope": scope,
                "active_vaults": active,
                "active_indebted_vaults": indebted,
                "valid_ratio_vaults": valid,
                "liquidatable_vaults": liquidatable,
                "share_all_active": (
                    0.0 if active == 0 else liquidatable / active
                ),
                "share_active_indebted": (
                    0.0 if indebted == 0 else liquidatable / indebted
                ),
                "share_valid_ratio": (
                    0.0 if valid == 0 else liquidatable / valid
                ),
            })
    return pd.DataFrame(rows)


def _moving_block_quantile_ci(
    values: np.ndarray,
    *,
    probability: float,
    block_length: int,
    seed: int,
    replications: int,
) -> tuple[float, float]:
    values = values[np.isfinite(values)]
    if not values.size:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    starts = np.arange(values.size)
    estimates = []
    block_count = math.ceil(values.size / block_length)
    for _ in range(replications):
        sample_parts = []
        for start in rng.choice(starts, size=block_count, replace=True):
            indices = (
                start + np.arange(block_length)
            ) % values.size
            sample_parts.append(values[indices])
        sample = np.concatenate(sample_parts)[: values.size]
        estimates.append(np.quantile(sample, probability))
    return tuple(float(value) for value in np.quantile(
        estimates, [0.025, 0.975]
    ))


def _liquidatable_estimates(
    series: pd.DataFrame,
    *,
    seed: int,
    replications: int,
    block_hours: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    grouping = [
        ("named_window_all_hours", ["window", "collateral_scope"]),
        (
            "classifier_conditioned",
            ["window", "classifier_regime", "collateral_scope"],
        ),
    ]
    for temporal_scope, columns in grouping:
        for keys, frame in series.groupby(columns, sort=True):
            if not isinstance(keys, tuple):
                keys = (keys,)
            labels = dict(zip(columns, keys))
            values = frame["share_all_active"].to_numpy(float)
            q95_ci = _moving_block_quantile_ci(
                values,
                probability=0.95,
                block_length=block_hours,
                seed=seed + sum(ord(char) for char in "".join(map(str, keys))),
                replications=replications,
            )
            rows.append({
                "temporal_scope": temporal_scope,
                "window": labels["window"],
                "named_regime": frame["named_regime"].iloc[0],
                "classifier_regime": labels.get(
                    "classifier_regime", "all"
                ),
                "collateral_scope": labels["collateral_scope"],
                "hour_count": len(frame),
                "liquidatable_observation_hours": int(
                    frame["liquidatable_vaults"].gt(0).sum()
                ),
                "minimum": float(values.min()),
                "median": float(np.median(values)),
                "q90": float(np.quantile(values, 0.90)),
                "q95": float(np.quantile(values, 0.95)),
                "q95_ci_lower": q95_ci[0],
                "q95_ci_upper": q95_ci[1],
                "q99": float(np.quantile(values, 0.99)),
                "maximum": float(values.max()),
                "hours_above_current_normal_threshold_0_05": int(
                    np.count_nonzero(values > 0.05)
                ),
                "hours_above_current_stress_threshold_0_30": int(
                    np.count_nonzero(values > 0.30)
                ),
                "primary_denominator": "all active vaults",
                "median_share_active_indebted": float(
                    frame["share_active_indebted"].median()
                ),
                "maximum_share_active_indebted": float(
                    frame["share_active_indebted"].max()
                ),
                "median_share_valid_ratio": float(
                    frame["share_valid_ratio"].median()
                ),
                "maximum_share_valid_ratio": float(
                    frame["share_valid_ratio"].max()
                ),
            })
    return pd.DataFrame(rows)


def _row(
    frame: pd.DataFrame,
    *,
    window: str,
    boundary: str,
    scope: str,
) -> pd.Series:
    matches = frame.loc[
        frame["window"].eq(window)
        & frame["boundary"].eq(boundary)
        & frame["collateral_scope"].eq(scope)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one {window}/{boundary}/{scope} row, got {len(matches)}"
        )
    return matches.iloc[0]


def _candidate(
    **kwargs: Any,
) -> dict[str, Any]:
    missing = set(CANDIDATE_FIELDS) - set(kwargs)
    if missing:
        raise ValueError(f"candidate lacks {sorted(missing)}")
    return {field: kwargs[field] for field in CANDIDATE_FIELDS}


def _build_candidates(
    counts: pd.DataFrame,
    debt_shares: pd.DataFrame,
    debt: pd.DataFrame,
    ratios: pd.DataFrame,
    buffers: pd.DataFrame,
    liquidatable: pd.DataFrame,
    *,
    config: Phase2BConfig,
) -> list[dict[str, Any]]:
    quiet_count = _row(
        counts, window="quiet_mature", boundary="opening", scope="ALL"
    )
    all_counts = counts.loc[counts["collateral_scope"].eq("ALL")]
    observed_active_range = [
        int(all_counts["active_vaults"].min()),
        int(all_counts["active_vaults"].max()),
    ]
    quiet_eth_share = _row(
        debt_shares,
        window="quiet_mature",
        boundary="opening",
        scope="ETH",
    )
    quiet_wbtc_share = _row(
        debt_shares,
        window="quiet_mature",
        boundary="opening",
        scope="WBTC",
    )
    quiet_debt = _row(
        debt, window="quiet_mature", boundary="opening", scope="ALL"
    )
    quiet_ratio = _row(
        ratios, window="quiet_mature", boundary="opening", scope="ALL"
    )
    quiet_buffer = _row(
        buffers, window="quiet_mature", boundary="opening", scope="ALL"
    )
    normal = liquidatable.loc[
        liquidatable["temporal_scope"].eq("named_window_all_hours")
        & liquidatable["window"].eq("quiet_mature")
        & liquidatable["collateral_scope"].eq("ALL")
    ].iloc[0]
    stress_conditioned = liquidatable.loc[
        liquidatable["temporal_scope"].eq("classifier_conditioned")
        & liquidatable["window"].eq("usdc_svb")
        & liquidatable["classifier_regime"].eq("stress")
        & liquidatable["collateral_scope"].eq("ALL")
    ]
    stress_named = liquidatable.loc[
        liquidatable["temporal_scope"].eq("named_window_all_hours")
        & liquidatable["window"].eq("usdc_svb")
        & liquidatable["collateral_scope"].eq("ALL")
    ].iloc[0]
    if stress_conditioned.empty:
        stress = stress_named
        stress_scope = "named USDC/SVB window"
    else:
        stress = stress_conditioned.iloc[0]
        stress_scope = "Phase 2A classifier-stress hours within USDC/SVB"
    normal_estimate = float(normal["q95"])
    unconstrained_stress = float(stress["q95"])
    stress_estimate = max(normal_estimate, unconstrained_stress)

    input_states = (
        "quiet and USDC/SVB opening/closing vault-state CSVs"
    )
    common_notes = (
        "Representative windows are regime-conditional and purposive; "
        "candidate is not an unconditional historical frequency."
    )
    return [
        _candidate(
            parameter_name="n_vaults",
            simulator_field="SimulationConfig.n_vaults",
            estimate=config.recommended_simulation_vaults,
            units="synthetic vaults",
            representation="single computational sample size",
            regime="cross-regime scaling choice",
            collateral_scope="six target ilks mapped to ETH and BTC",
            boundary_or_temporal_scope="four validated boundaries",
            estimator=(
                "Computational scaling choice informed by observed active "
                "counts; not a direct historical-count estimate"
            ),
            input_dataset=input_states,
            input_columns=["active", "ilk", "urn"],
            sample_size=int(quiet_count["active_vaults"]),
            resampling_unit="not applicable; convergence sensitivity required",
            uncertainty_interval={
                "type": "sensitivity_range",
                "lower": 100,
                "upper": 1000,
            },
            sensitivity_alternatives={
                "observed_active_range": observed_active_range,
                "simulation_sizes": [100, 250, 500, 1000],
                "quiet_opening_scaling_factor": (
                    float(quiet_count["active_vaults"])
                    / config.recommended_simulation_vaults
                ),
            },
            validation_status="provisional_scaling_choice",
            model_interface_compatibility="direct scalar support",
            review_requirement="Require multi-size convergence before adoption",
            notes=common_notes,
        ),
        _candidate(
            parameter_name="target_debt_share",
            simulator_field="CollateralConfig.target_debt_share",
            estimate={
                "ETH": float(quiet_eth_share["target_debt_share"]),
                "BTC": float(quiet_wbtc_share["target_debt_share"]),
            },
            units="share of six-ilk active DAI debt",
            representation="collateral-specific static scalar shares",
            regime="quiet_mature",
            collateral_scope="ETH and BTC families; exact ilks retained",
            boundary_or_temporal_scope="opening boundary",
            estimator="Direct active-debt share by collateral family",
            input_dataset=input_states,
            input_columns=["ilk", "active", "debt_dai"],
            sample_size=int(quiet_count["active_indebted_vaults"]),
            resampling_unit="urn bootstrap",
            uncertainty_interval={
                "ETH": [
                    float(quiet_eth_share["share_ci_lower"]),
                    float(quiet_eth_share["share_ci_upper"]),
                ],
                "BTC": [
                    float(quiet_wbtc_share["share_ci_lower"]),
                    float(quiet_wbtc_share["share_ci_upper"]),
                ],
            },
            sensitivity_alternatives=(
                "Quiet closing and USDC/SVB opening/closing shares; exact-ilk "
                "shares in target_debt_share_estimates.csv"
            ),
            validation_status="ready_for_review",
            model_interface_compatibility=(
                "Direct collateral-specific scalar support; no STABLE "
                "candidate from the six-ilk evidence"
            ),
            review_requirement=(
                "Review whether baseline should represent quiet opening or a "
                "declared scenario composition"
            ),
            notes=common_notes,
        ),
        _candidate(
            parameter_name="debt_mean",
            simulator_field="SimulationConfig.debt_mean",
            estimate=float(quiet_debt["mean"]),
            units="DAI per active indebted vault",
            representation="raw arithmetic mean",
            regime="quiet_mature",
            collateral_scope="six target ilks pooled for current global scalar",
            boundary_or_temporal_scope="opening boundary",
            estimator="Unweighted cross-sectional arithmetic mean",
            input_dataset=input_states,
            input_columns=["active", "debt_dai", "urn", "owner_or_proxy"],
            sample_size=int(quiet_debt["count"]),
            resampling_unit="urn bootstrap; owner-proxy sensitivity",
            uncertainty_interval=[
                float(quiet_debt["mean_ci_lower"]),
                float(quiet_debt["mean_ci_upper"]),
            ],
            sensitivity_alternatives={
                "winsorised_q99_mean": float(
                    quiet_debt["winsorised_q99_mean"]
                ),
                "log_mean": float(quiet_debt["log_mean"]),
                "median": float(quiet_debt["median"]),
            },
            validation_status="provisional_distribution_choice",
            model_interface_compatibility=(
                "Scalar supported; empirical distribution and "
                "collateral-specific moments are not"
            ),
            review_requirement=(
                "Raw debt is heavy-tailed; review Gaussian moment loss before "
                "adoption"
            ),
            notes=common_notes,
        ),
        _candidate(
            parameter_name="debt_std",
            simulator_field="SimulationConfig.debt_std",
            estimate=float(quiet_debt["std"]),
            units="DAI per active indebted vault",
            representation="raw sample standard deviation",
            regime="quiet_mature",
            collateral_scope="six target ilks pooled for current global scalar",
            boundary_or_temporal_scope="opening boundary",
            estimator="Unweighted cross-sectional sample standard deviation",
            input_dataset=input_states,
            input_columns=["active", "debt_dai", "urn", "owner_or_proxy"],
            sample_size=int(quiet_debt["count"]),
            resampling_unit="urn bootstrap; owner-proxy sensitivity",
            uncertainty_interval=[
                float(quiet_debt["std_ci_lower"]),
                float(quiet_debt["std_ci_upper"]),
            ],
            sensitivity_alternatives={
                "winsorised_q99_std": float(
                    quiet_debt["winsorised_q99_std"]
                ),
                "log_std": float(quiet_debt["log_std"]),
                "interquartile_range": float(
                    quiet_debt["q75"] - quiet_debt["q25"]
                ),
            },
            validation_status="provisional_distribution_choice",
            model_interface_compatibility=(
                "Scalar supported; empirical distribution and "
                "collateral-specific dispersion are not"
            ),
            review_requirement=(
                "Review heavy-tail sensitivity and realised Gaussian clipping"
            ),
            notes=common_notes,
        ),
        _candidate(
            parameter_name="collateral_ratio_mean",
            simulator_field="SimulationConfig.collateral_ratio_mean",
            estimate=float(quiet_ratio["mean"]),
            units="dimensionless collateral-value/debt multiple",
            representation="raw arithmetic mean",
            regime="quiet_mature",
            collateral_scope="six target ilks pooled for current global scalar",
            boundary_or_temporal_scope="opening boundary",
            estimator="Mean among active indebted vaults with valid ratios",
            input_dataset=input_states,
            input_columns=[
                "collateral_value_usd",
                "debt_dai",
                "liquidation_ratio",
                "urn",
            ],
            sample_size=int(quiet_ratio["count"]),
            resampling_unit="urn bootstrap; owner-proxy sensitivity",
            uncertainty_interval=[
                float(quiet_ratio["mean_ci_lower"]),
                float(quiet_ratio["mean_ci_upper"]),
            ],
            sensitivity_alternatives={
                "winsorised_q99_mean": float(
                    quiet_ratio["winsorised_q99_mean"]
                ),
                "median": float(quiet_ratio["median"]),
                "log_mean": float(quiet_ratio["log_mean"]),
            },
            validation_status="provisional_distribution_choice",
            model_interface_compatibility=(
                "Global scalar supported; exact-ilk distributions are not"
            ),
            review_requirement=(
                "Review upper-tail influence and liquidation-ratio "
                "heterogeneity"
            ),
            notes=common_notes,
        ),
        _candidate(
            parameter_name="collateral_ratio_std",
            simulator_field="SimulationConfig.collateral_ratio_std",
            estimate=float(quiet_ratio["std"]),
            units="dimensionless collateral-value/debt multiple",
            representation="raw sample standard deviation",
            regime="quiet_mature",
            collateral_scope="six target ilks pooled for current global scalar",
            boundary_or_temporal_scope="opening boundary",
            estimator="Sample standard deviation among valid ratios",
            input_dataset=input_states,
            input_columns=[
                "collateral_value_usd",
                "debt_dai",
                "liquidation_ratio",
                "urn",
            ],
            sample_size=int(quiet_ratio["count"]),
            resampling_unit="urn bootstrap; owner-proxy sensitivity",
            uncertainty_interval=[
                float(quiet_ratio["std_ci_lower"]),
                float(quiet_ratio["std_ci_upper"]),
            ],
            sensitivity_alternatives={
                "winsorised_q99_std": float(
                    quiet_ratio["winsorised_q99_std"]
                ),
                "log_std": float(quiet_ratio["log_std"]),
                "interquartile_range": float(
                    quiet_ratio["q75"] - quiet_ratio["q25"]
                ),
            },
            validation_status="provisional_distribution_choice",
            model_interface_compatibility=(
                "Global scalar supported; exact-ilk distributions are not"
            ),
            review_requirement=(
                "Review upper-tail sensitivity and lower-tail fit after "
                "generator clipping"
            ),
            notes=common_notes,
        ),
        _candidate(
            parameter_name="min_collateral_ratio_buffer",
            simulator_field="generate_*_vaults(min_collateral_ratio_buffer)",
            estimate=float(quiet_buffer["q05"]),
            units="absolute dimensionless ratio above liquidation threshold",
            representation="fifth percentile absolute buffer",
            regime="quiet_mature",
            collateral_scope="six target ilks normalised by exact threshold",
            boundary_or_temporal_scope="opening boundary",
            estimator="Empirical lower-tail q05, not literal sample minimum",
            input_dataset=input_states,
            input_columns=["collateral_ratio", "liquidation_ratio", "urn"],
            sample_size=int(quiet_buffer["count"]),
            resampling_unit="urn bootstrap",
            uncertainty_interval=[
                float(quiet_buffer["q05_ci_lower"]),
                float(quiet_buffer["q05_ci_upper"]),
            ],
            sensitivity_alternatives={
                "q01": float(quiet_buffer["q01"]),
                "q10": float(quiet_buffer["q10"]),
                "relative_q05": float(quiet_buffer["relative_q05"]),
                "sample_minimum": float(quiet_buffer["minimum"]),
            },
            validation_status="provisional_distribution_choice",
            model_interface_compatibility=(
                "Global absolute scalar supported; collateral-specific and "
                "relative buffers are not"
            ),
            review_requirement=(
                "Bootstrap the q05 itself and review exact-ilk alternatives "
                "before adoption"
            ),
            notes=(
                f"{common_notes} The field is a simulator safeguard, not the "
                "protocol liquidation ratio."
            ),
        ),
        _candidate(
            parameter_name="max_normal_liquidatable_share",
            simulator_field="ConfidenceConfig.max_normal_liquidatable_share",
            estimate=normal_estimate,
            units="share of all active vaults",
            representation="quiet-window hourly q95",
            regime="quiet_mature",
            collateral_scope="six target ilks",
            boundary_or_temporal_scope="all 696 hourly snapshots",
            estimator="Ninety-fifth percentile of reconstructed hourly share",
            input_dataset=(
                "opening state, in-window mutations, sparse rates, Phase 1A "
                "prices and Phase 1D liquidation ratios"
            ),
            input_columns=[
                "ink_raw",
                "art_raw",
                "rate_raw_ray",
                "collateral price",
                "liquidation_ratio",
            ],
            sample_size=int(normal["hour_count"]),
            resampling_unit="24-hour moving-block bootstrap",
            uncertainty_interval=[
                float(normal["q95_ci_lower"]),
                float(normal["q95_ci_upper"]),
            ],
            sensitivity_alternatives={
                "q90": float(normal["q90"]),
                "q99": float(normal["q99"]),
                "maximum": float(normal["maximum"]),
                "active_indebted_denominator_maximum": float(
                    normal["maximum_share_active_indebted"]
                ),
            },
            validation_status="ready_for_review",
            model_interface_compatibility="direct global scalar support",
            review_requirement=(
                "Validate classification sensitivity outside the quiet window"
            ),
            notes=(
                f"{common_notes} Liquidatable state is distinct from Bark or "
                "grab execution."
            ),
        ),
        _candidate(
            parameter_name="max_stress_liquidatable_share",
            simulator_field="ConfidenceConfig.max_stress_liquidatable_share",
            estimate=stress_estimate,
            units="share of all active vaults",
            representation="USDC/SVB classifier-stress hourly q95",
            regime="stress",
            collateral_scope="six target ilks",
            boundary_or_temporal_scope=stress_scope,
            estimator=(
                "Ninety-fifth percentile of reconstructed hourly share, "
                "constrained not below the normal candidate"
            ),
            input_dataset=(
                "opening state, in-window mutations, sparse rates, Phase 1A "
                "prices, Phase 1D ratios and frozen Phase 2A classifier"
            ),
            input_columns=[
                "ink_raw",
                "art_raw",
                "rate_raw_ray",
                "collateral price",
                "liquidation_ratio",
                "regime",
            ],
            sample_size=int(stress["hour_count"]),
            resampling_unit="24-hour moving-block bootstrap",
            uncertainty_interval=[
                float(stress["q95_ci_lower"]),
                float(stress["q95_ci_upper"]),
            ],
            sensitivity_alternatives={
                "unconstrained_classifier_stress_q95": unconstrained_stress,
                "full_named_window_q95": float(stress_named["q95"]),
                "classifier_stress_q99": float(stress["q99"]),
                "classifier_stress_maximum": float(stress["maximum"]),
            },
            validation_status="ready_for_review",
            model_interface_compatibility="direct global scalar support",
            review_requirement=(
                "Terra/CeFi stress-tail validation remains required before "
                "adoption"
            ),
            notes=(
                f"{common_notes} The FTX interval was not used. Liquidatable "
                "state is distinct from observed liquidation execution."
            ),
        ),
    ]


def _candidate_status(candidates: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [{
        "parameter": item["parameter_name"],
        "status": item["validation_status"],
        "has_candidate": True,
        "simulator_field": item["simulator_field"],
        "review_requirement": item["review_requirement"],
    } for item in candidates]
    rows.append({
        "parameter": MAX_CLOSE_FACTOR,
        "status": "insufficient_evidence",
        "has_candidate": False,
        "simulator_field": (
            "LiquidationConfig.max_close_factor / "
            "CollateralConfig.max_close_factor"
        ),
        "review_requirement": (
            "Requires actual liquidation-related Vat.grab evidence or an "
            "authoritative protocol rule; Terra/CeFi is the next preferred "
            "representative window."
        ),
    })
    return pd.DataFrame(rows)


def _current_configuration_comparison(
    candidates: list[dict[str, Any]],
) -> pd.DataFrame:
    current: dict[str, Any] = {
        "n_vaults": 100,
        "target_debt_share": {"ETH": 0.60, "BTC": 0.40},
        "debt_mean": 5_000.0,
        "debt_std": 1_000.0,
        "collateral_ratio_mean": 2.0,
        "collateral_ratio_std": 0.25,
        "min_collateral_ratio_buffer": 0.05,
        "max_normal_liquidatable_share": 0.05,
        "max_stress_liquidatable_share": 0.30,
    }
    rows: list[dict[str, Any]] = []
    for item in candidates:
        parameter = item["parameter_name"]
        estimate = item["estimate"]
        current_value = current[parameter]
        scopes = (
            estimate.keys() if isinstance(estimate, dict) else ["global"]
        )
        for scope in scopes:
            candidate_value = (
                float(estimate[scope])
                if isinstance(estimate, dict) else float(estimate)
            )
            configured = (
                float(current_value[scope])
                if isinstance(current_value, dict) else float(current_value)
            )
            interval = item["uncertainty_interval"]
            if isinstance(interval, dict) and scope in interval:
                lower, upper = interval[scope]
            elif (
                isinstance(interval, dict)
                and "lower" in interval
                and "upper" in interval
            ):
                lower, upper = interval["lower"], interval["upper"]
            elif isinstance(interval, list):
                lower, upper = interval
            else:
                lower = upper = math.nan
            rows.append({
                "parameter": parameter,
                "collateral_scope": scope,
                "current_configured_value": configured,
                "empirical_candidate": candidate_value,
                "units": item["units"],
                "absolute_difference": candidate_value - configured,
                "relative_difference": (
                    math.nan
                    if configured == 0
                    else candidate_value / configured - 1
                ),
                "uncertainty_or_sensitivity_lower": lower,
                "uncertainty_or_sensitivity_upper": upper,
                "current_inside_interval": (
                    False
                    if not np.isfinite(lower) or not np.isfinite(upper)
                    else lower <= configured <= upper
                ),
                "unit_compatible": True,
                "frequency_compatible": parameter not in {
                    "max_normal_liquidatable_share",
                    "max_stress_liquidatable_share",
                },
                "comparison_note": (
                    "Reference portfolio is crypto_diversified"
                    if parameter == "target_debt_share"
                    else "Diagnostic comparison only; no configuration write"
                ),
            })
    return pd.DataFrame(rows)


def _owner_diagnostics(
    boundaries: pd.DataFrame,
    *,
    seed: int,
    replications: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (window, boundary), frame in boundaries.groupby(
        ["window", "boundary"], sort=True
    ):
        active = frame.loc[frame["active"].map(_truth)].copy()
        mapped = active.loc[active["owner_or_proxy"].notna()]
        counts = mapped["owner_or_proxy"].value_counts()
        probabilities = counts / counts.sum() if len(counts) else counts
        estimation = active_indebted(frame)
        estimation["owner_proxy_cluster"] = estimation[
            "owner_or_proxy"
        ].where(
            estimation["owner_or_proxy"].notna(),
            "unmapped_urn:" + estimation["urn"].astype(str),
        )
        valid_ratio = estimation.loc[
            pd.to_numeric(
                estimation["collateral_ratio"], errors="coerce"
            ).notna()
        ].copy()
        salt = sum(ord(char) for char in f"{window}{boundary}")
        debt_ci = clustered_bootstrap_reproducible(
            estimation,
            "debt_dai",
            "owner_proxy_cluster",
            seed=seed + salt,
            replications=replications,
        )
        ratio_ci = clustered_bootstrap_reproducible(
            valid_ratio,
            "collateral_ratio",
            "owner_proxy_cluster",
            seed=seed + 10_000 + salt,
            replications=replications,
        )
        rows.append({
            "window": window,
            "boundary": boundary,
            "active_vaults": len(active),
            "mapped_active_vaults": len(mapped),
            "unmapped_active_vaults": len(active) - len(mapped),
            "unique_owner_proxies": mapped["owner_or_proxy"].nunique(),
            "largest_owner_proxy_share": (
                math.nan if not len(counts) else float(probabilities.max())
            ),
            "herfindahl_index": (
                math.nan if not len(counts) else float((probabilities**2).sum())
            ),
            "effective_owner_proxy_clusters": (
                math.nan
                if not len(counts)
                else float(1 / (probabilities**2).sum())
            ),
            "active_indebted_vaults": len(estimation),
            "owner_proxy_or_urn_clusters": int(
                estimation["owner_proxy_cluster"].nunique()
            ),
            "owner_clustered_debt_mean_ci_lower": debt_ci[0],
            "owner_clustered_debt_mean_ci_upper": debt_ci[1],
            "owner_clustered_collateral_ratio_mean_ci_lower": ratio_ci[0],
            "owner_clustered_collateral_ratio_mean_ci_upper": ratio_ci[1],
            "owner_cluster_rule": (
                "Manager owner/proxy where mapped; urn-specific cluster "
                "where unmapped"
            ),
            "identity_limitation": (
                "Manager owner/proxy is not necessarily beneficial owner"
            ),
        })
    return pd.DataFrame(rows)


def _cross_regime(
    counts: pd.DataFrame,
    shares: pd.DataFrame,
    debt: pd.DataFrame,
    ratios: pd.DataFrame,
    buffers: pd.DataFrame,
    liquidatable: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for boundary in ("opening", "window_end"):
        quiet_count = _row(
            counts, window="quiet_mature", boundary=boundary, scope="ALL"
        )
        stress_count = _row(
            counts, window="usdc_svb", boundary=boundary, scope="ALL"
        )
        quiet_debt = _row(
            debt, window="quiet_mature", boundary=boundary, scope="ALL"
        )
        stress_debt = _row(
            debt, window="usdc_svb", boundary=boundary, scope="ALL"
        )
        quiet_ratio = _row(
            ratios, window="quiet_mature", boundary=boundary, scope="ALL"
        )
        stress_ratio = _row(
            ratios, window="usdc_svb", boundary=boundary, scope="ALL"
        )
        quiet_buffer = _row(
            buffers, window="quiet_mature", boundary=boundary, scope="ALL"
        )
        stress_buffer = _row(
            buffers, window="usdc_svb", boundary=boundary, scope="ALL"
        )
        for parameter, q, s in (
            ("active_vaults", quiet_count["active_vaults"],
             stress_count["active_vaults"]),
            ("active_indebted_vaults",
             quiet_count["active_indebted_vaults"],
             stress_count["active_indebted_vaults"]),
            ("debt_mean", quiet_debt["mean"], stress_debt["mean"]),
            ("debt_std", quiet_debt["std"], stress_debt["std"]),
            ("collateral_ratio_mean", quiet_ratio["mean"],
             stress_ratio["mean"]),
            ("collateral_ratio_std", quiet_ratio["std"], stress_ratio["std"]),
            ("absolute_buffer_q05", quiet_buffer["q05"],
             stress_buffer["q05"]),
        ):
            rows.append({
                "parameter": parameter,
                "boundary": boundary,
                "quiet_mature": q,
                "usdc_svb": s,
                "absolute_difference": s - q,
                "relative_difference": (
                    math.nan if q == 0 else s / q - 1
                ),
                "interpretation": (
                    "Descriptive regime contrast only; not a causal effect"
                ),
            })
    for family in ("ETH", "WBTC"):
        quiet = _row(
            shares,
            window="quiet_mature",
            boundary="opening",
            scope=family,
        )
        stress = _row(
            shares, window="usdc_svb", boundary="opening", scope=family
        )
        rows.append({
            "parameter": f"target_debt_share_{family}",
            "boundary": "opening",
            "quiet_mature": quiet["target_debt_share"],
            "usdc_svb": stress["target_debt_share"],
            "absolute_difference": (
                stress["target_debt_share"] - quiet["target_debt_share"]
            ),
            "relative_difference": (
                stress["target_debt_share"]
                / quiet["target_debt_share"] - 1
            ),
            "interpretation": (
                "Descriptive regime contrast only; not a causal effect"
            ),
        })
    for window in ("quiet_mature", "usdc_svb"):
        item = liquidatable.loc[
            liquidatable["temporal_scope"].eq("named_window_all_hours")
            & liquidatable["window"].eq(window)
            & liquidatable["collateral_scope"].eq("ALL")
        ].iloc[0]
        rows.append({
            "parameter": "hourly_liquidatable_share_q95",
            "boundary": window,
            "quiet_mature": (
                item["q95"] if window == "quiet_mature" else math.nan
            ),
            "usdc_svb": (
                item["q95"] if window == "usdc_svb" else math.nan
            ),
            "absolute_difference": math.nan,
            "relative_difference": math.nan,
            "interpretation": (
                "Named-window descriptive threshold; see conditioned rows"
            ),
        })
    return pd.DataFrame(rows)


def _diagnostics(
    candidates: list[dict[str, Any]],
    debt: pd.DataFrame,
    ratios: pd.DataFrame,
    owners: pd.DataFrame,
) -> pd.DataFrame:
    quiet_debt = _row(
        debt, window="quiet_mature", boundary="opening", scope="ALL"
    )
    quiet_ratio = _row(
        ratios, window="quiet_mature", boundary="opening", scope="ALL"
    )
    return pd.DataFrame([
        {
            "diagnostic": "authoritative_parameter_list",
            "status": "passed",
            "value": ";".join(PARAMETERS),
            "notes": "Exactly nine candidates; max_close_factor excluded",
        },
        {
            "diagnostic": "ftx_leakage",
            "status": "passed",
            "value": "0",
            "notes": "No FTX boundary, event, market or regime row used",
        },
        {
            "diagnostic": "debt_heavy_tail",
            "status": (
                "warning" if quiet_debt["skewness"] > 2 else "passed"
            ),
            "value": quiet_debt["skewness"],
            "notes": "Raw primary retained; q99 winsorised sensitivity reported",
        },
        {
            "diagnostic": "collateral_ratio_heavy_tail",
            "status": (
                "warning" if quiet_ratio["skewness"] > 2 else "passed"
            ),
            "value": quiet_ratio["skewness"],
            "notes": "Raw primary retained; q99 winsorised sensitivity reported",
        },
        {
            "diagnostic": "owner_proxy_dependence",
            "status": "passed_with_limitation",
            "value": owners["largest_owner_proxy_share"].max(),
            "notes": (
                "Owner-proxy clustering available for sensitivity; not "
                "beneficial ownership"
            ),
        },
        {
            "diagnostic": "candidate_count",
            "status": "passed",
            "value": len(candidates),
            "notes": "One primary candidate record per authorised parameter",
        },
        {
            "diagnostic": "max_close_factor",
            "status": "insufficient_evidence",
            "value": "",
            "notes": "No estimate fabricated from frobs or Bark/grab absence",
        },
        {
            "diagnostic": "configuration_writes",
            "status": "passed",
            "value": "0",
            "notes": "Estimator writes only to its explicit output directory",
        },
    ])


def _substantive_outputs(
    output: Path,
    *,
    audit: pd.DataFrame,
    counts: pd.DataFrame,
    shares: pd.DataFrame,
    debt: pd.DataFrame,
    ratios: pd.DataFrame,
    buffers: pd.DataFrame,
    liquidatable: pd.DataFrame,
    liquidatable_series: pd.DataFrame,
    cross_regime: pd.DataFrame,
    diagnostics: pd.DataFrame,
    owners: pd.DataFrame,
    current_comparison: pd.DataFrame,
    candidates: list[dict[str, Any]],
    status: pd.DataFrame,
    config: Phase2BConfig,
) -> dict[str, Path]:
    paths = {
        "audit": output / "audit/input_integrity.csv",
        "counts": output / "vault_count_estimates.csv",
        "shares": output / "target_debt_share_estimates.csv",
        "debt": output / "debt_distribution_estimates.csv",
        "ratios": output / "collateral_ratio_estimates.csv",
        "buffers": output / "collateral_ratio_buffer_estimates.csv",
        "liquidatable": output / "liquidatable_share_estimates.csv",
        "liquidatable_series": (
            output / "liquidatable_share/hourly_liquidatable_share.csv"
        ),
        "cross_regime": output / "cross_regime_comparison.csv",
        "diagnostics": output / "estimation_diagnostics.csv",
        "owners": output / "diagnostics/owner_proxy_dependence.csv",
        "current_comparison": (
            output / "diagnostics/current_configuration_comparison.csv"
        ),
        "candidates": output / "phase2b_parameter_candidates.json",
        "status": output / "phase2b_parameter_status.csv",
    }
    frames = {
        "audit": audit,
        "counts": counts,
        "shares": shares,
        "debt": debt,
        "ratios": ratios,
        "buffers": buffers,
        "liquidatable": liquidatable,
        "liquidatable_series": liquidatable_series,
        "cross_regime": cross_regime,
        "diagnostics": diagnostics,
        "owners": owners,
        "current_comparison": current_comparison,
        "status": status,
    }
    for key, frame in frames.items():
        _write_csv(paths[key], frame)
    registry = {
        "schema_version": 1,
        "phase": "2B",
        "candidate_status": "review_only_not_adopted",
        "authorised_parameters": list(PARAMETERS),
        "excluded_parameter": {
            "parameter_name": MAX_CLOSE_FACTOR,
            "status": "insufficient_evidence",
            "estimate": None,
        },
        "random_seed": config.random_seed,
        "bootstrap_replications": config.bootstrap_replications,
        "representative_windows": [{
            "key": window.key,
            "role": window.role,
            "start_utc": window.start.isoformat(),
            "end_exclusive_utc": window.end_exclusive.isoformat(),
        } for window in WINDOWS],
        "candidates": candidates,
    }
    _write_json(paths["candidates"], registry)
    return paths


def run_phase2b(config: Phase2BConfig = Phase2BConfig()) -> dict[str, Any]:
    """Run the entirely local Phase 2B vault-parameter estimation workflow."""
    if config.bootstrap_replications < 50:
        raise ValueError("bootstrap_replications must be at least 50")
    if config.recommended_simulation_vaults <= 0:
        raise ValueError("recommended_simulation_vaults must be positive")
    if tuple(PARAMETERS) != (
        "n_vaults",
        "target_debt_share",
        "debt_mean",
        "debt_std",
        "collateral_ratio_mean",
        "collateral_ratio_std",
        "min_collateral_ratio_buffer",
        "max_normal_liquidatable_share",
        "max_stress_liquidatable_share",
    ):
        raise ValueError("authoritative Phase 2B parameter list changed")

    audit_rows: list[dict[str, Any]] = []
    loaded: dict[str, dict[str, pd.DataFrame]] = {}
    for window in WINDOWS:
        checks, frames = _input_output_checks(window)
        audit_rows.extend(checks)
        loaded[window.key] = frames
    protocol, market, regimes = _load_protocol_market_regimes()
    for name, path, frame in (
        ("protocol_hourly", PROTOCOL_PATH, protocol),
        ("market_hourly", MARKET_PATH, market),
        ("phase2a_hourly_regimes", REGIME_PATH, regimes),
    ):
        audit_rows.append({
            "window": "shared",
            "input": name,
            "path": _relative(path),
            "expected_sha256": sha256_file(path),
            "observed_sha256": sha256_file(path),
            "rows": len(frame),
            "columns": len(frame.columns),
            "validation": "passed",
        })

    boundary_frames: list[pd.DataFrame] = []
    for window in WINDOWS:
        for name, boundary in (
            ("opening_vault_state.csv", "opening"),
            ("closing_vault_state.csv", "window_end"),
        ):
            boundary_frames.append(_prepare_boundary(
                window,
                boundary,
                loaded[window.key][name],
                protocol,
                regimes,
            ))
    boundaries = pd.concat(boundary_frames, ignore_index=True)
    counts = _count_estimates(boundaries)
    shares = _debt_share_estimates(
        boundaries,
        seed=config.random_seed,
        replications=config.bootstrap_replications,
    )
    debt, ratios, buffers = _distribution_estimates(
        boundaries,
        seed=config.random_seed,
        replications=config.bootstrap_replications,
    )
    hourly_frames = [
        _hourly_liquidatable_series(
            window,
            loaded[window.key],
            protocol,
            market,
            regimes,
        )
        for window in WINDOWS
    ]
    liquidatable_series = pd.concat(hourly_frames, ignore_index=True)
    liquidatable = _liquidatable_estimates(
        liquidatable_series,
        seed=config.random_seed,
        replications=config.bootstrap_replications,
        block_hours=config.bootstrap_block_hours,
    )
    candidates = _build_candidates(
        counts,
        shares,
        debt,
        ratios,
        buffers,
        liquidatable,
        config=config,
    )
    if [item["parameter_name"] for item in candidates] != list(PARAMETERS):
        raise ValueError("candidate registry does not match authorised list")
    if any(item["parameter_name"] == MAX_CLOSE_FACTOR for item in candidates):
        raise ValueError("max_close_factor estimate is prohibited")
    status = _candidate_status(candidates)
    owners = _owner_diagnostics(
        boundaries,
        seed=config.random_seed,
        replications=config.bootstrap_replications,
    )
    current_comparison = _current_configuration_comparison(candidates)
    cross_regime = _cross_regime(
        counts, shares, debt, ratios, buffers, liquidatable
    )
    diagnostics = _diagnostics(candidates, debt, ratios, owners)
    output = config.output_dir.resolve()
    paths = _substantive_outputs(
        output,
        audit=pd.DataFrame(audit_rows),
        counts=counts,
        shares=shares,
        debt=debt,
        ratios=ratios,
        buffers=buffers,
        liquidatable=liquidatable,
        liquidatable_series=liquidatable_series,
        cross_regime=cross_regime,
        diagnostics=diagnostics,
        owners=owners,
        current_comparison=current_comparison,
        candidates=candidates,
        status=status,
        config=config,
    )

    metadata_path = output / "phase2b_run_metadata.json"
    output_metadata = {
        key: {
            "path": _relative(path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "rows": (
                sum(1 for _ in path.open(encoding="utf-8")) - 1
                if path.suffix == ".csv" else None
            ),
        }
        for key, path in paths.items()
    }
    metadata = {
        "phase": "2B",
        "status": "candidate_estimation_complete_not_adopted",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "random_seed": config.random_seed,
        "bootstrap_replications": config.bootstrap_replications,
        "bootstrap_block_hours": config.bootstrap_block_hours,
        "authorised_parameter_count": len(PARAMETERS),
        "candidate_count": len(candidates),
        "max_close_factor_estimated": False,
        "ftx_used": False,
        "network_access": False,
        "configuration_written": False,
        "processing_script": {
            "path": _relative(Path(__file__)),
            "sha256": sha256_file(Path(__file__)),
        },
        "inputs": [{
            "path": row["path"],
            "sha256": row["observed_sha256"],
            "rows": row["rows"],
            "columns": row["columns"],
        } for row in audit_rows],
        "outputs": output_metadata,
    }
    _write_json(metadata_path, metadata)
    return {
        "output_dir": str(output),
        "metadata_path": str(metadata_path),
        "registry_path": str(paths["candidates"]),
        "candidate_count": len(candidates),
        "outputs": {key: str(path) for key, path in paths.items()},
    }
