"""Transparent statistical primitives used by Phase 2A."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable

import numpy as np
import pandas as pd


QUANTILES: tuple[float, ...] = (
    0.01,
    0.05,
    0.10,
    0.25,
    0.50,
    0.75,
    0.90,
    0.95,
    0.99,
)


def calculate_log_returns(prices: pd.Series) -> pd.Series:
    """Calculate log returns without filling invalid observations."""
    numeric = pd.to_numeric(prices, errors="coerce")
    if numeric.isna().any():
        raise ValueError("Price series contains null or non-numeric values.")
    if (numeric <= 0).any():
        raise ValueError("Price series contains non-positive values.")
    result = np.log(numeric).diff()
    result.name = f"{prices.name}_log_return" if prices.name else "log_return"
    return result


def distribution_summary(
    values: pd.Series | np.ndarray | Iterable[float],
) -> dict[str, float | int | None]:
    """Return a registered empirical summary using linear quantiles."""
    series = pd.Series(values, dtype="float64").replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if series.empty:
        return {
            "n": 0,
            "mean": None,
            "std": None,
            **{f"q{int(q * 100):02d}": None for q in QUANTILES},
            "min": None,
            "max": None,
        }
    result: dict[str, float | int | None] = {
        "n": int(len(series)),
        "mean": float(series.mean()),
        "std": float(series.std(ddof=1)) if len(series) > 1 else 0.0,
        "min": float(series.min()),
        "max": float(series.max()),
    }
    for quantile in QUANTILES:
        result[f"q{int(quantile * 100):02d}"] = float(
            series.quantile(quantile, interpolation="linear")
        )
    return result


def autocorrelation(series: pd.Series, lag: int) -> float:
    """Return aligned Pearson autocorrelation at one positive lag."""
    if lag <= 0:
        raise ValueError("lag must be positive.")
    clean = pd.Series(series, dtype="float64")
    return float(clean.autocorr(lag=lag))


def candidate_block_length(
    returns: pd.DataFrame,
    *,
    max_lag: int = 168,
) -> tuple[int, pd.DataFrame]:
    """Choose the first lag where absolute-return ACF falls below 1/e.

    The maximum persistence across aligned return columns is used. This is a
    transparent candidate for review, not an asserted optimal block length.
    """
    if returns.empty:
        raise ValueError("Cannot estimate a block length from an empty frame.")
    rows: list[dict[str, object]] = []
    chosen: list[int] = []
    for column in returns.columns:
        series = returns[column].abs()
        acf_one = autocorrelation(series, 1)
        threshold = acf_one / math.e if np.isfinite(acf_one) else 0.0
        selected = max_lag
        for lag in range(1, max_lag + 1):
            value = autocorrelation(series, lag)
            rows.append(
                {
                    "asset_return": column,
                    "lag_hours": lag,
                    "absolute_return_acf": value,
                    "one_over_e_threshold": threshold,
                }
            )
            if lag > 1 and np.isfinite(value) and value <= threshold:
                selected = lag
                break
        chosen.append(selected)
    return max(2, int(max(chosen))), pd.DataFrame(rows)


def moving_block_indices(
    n_observations: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate one circular moving-block bootstrap index."""
    if n_observations <= 0:
        raise ValueError("n_observations must be positive.")
    if not 1 <= block_length <= n_observations:
        raise ValueError("block_length must be within the sample.")
    blocks = math.ceil(n_observations / block_length)
    starts = rng.integers(0, n_observations, size=blocks)
    offsets = np.arange(block_length)
    indices = np.concatenate(
        [(start + offsets) % n_observations for start in starts]
    )
    return indices[:n_observations]


def moving_block_bootstrap_ci(
    values: pd.Series | np.ndarray,
    *,
    block_length: int,
    estimator: Callable[[np.ndarray], float],
    replications: int,
    seed: int,
    alpha: float = 0.05,
) -> dict[str, float | int]:
    """Estimate a moving-block bootstrap percentile interval."""
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if len(array) < block_length:
        raise ValueError("Sample is shorter than the bootstrap block.")
    rng = np.random.default_rng(seed)
    estimates = np.empty(replications, dtype=float)
    for replication in range(replications):
        indices = moving_block_indices(len(array), block_length, rng)
        estimates[replication] = estimator(array[indices])
    return {
        "replications": replications,
        "seed": seed,
        "lower": float(np.quantile(estimates, alpha / 2)),
        "median": float(np.quantile(estimates, 0.5)),
        "upper": float(np.quantile(estimates, 1 - alpha / 2)),
    }


def estimate_regime_thresholds(
    calibration: pd.DataFrame,
    *,
    return_quantile: float = 0.05,
    upper_quantile: float = 0.90,
) -> dict[str, float]:
    """Estimate the six documented stress thresholds on calibration only."""
    required = {
        "eth_log_return",
        "wbtc_log_return",
        "realised_crypto_volatility",
        "median_effective_gas_price_gwei",
        "dai_abs_peg_deviation",
        "liquidation_volume_dai",
    }
    missing = required.difference(calibration.columns)
    if missing:
        raise ValueError(f"Regime threshold inputs missing: {sorted(missing)}")
    return {
        "eth_return_q05": float(
            calibration["eth_log_return"].quantile(return_quantile)
        ),
        "wbtc_return_q05": float(
            calibration["wbtc_log_return"].quantile(return_quantile)
        ),
        "crypto_volatility_q90": float(
            calibration["realised_crypto_volatility"].quantile(upper_quantile)
        ),
        "gas_price_q90": float(
            calibration["median_effective_gas_price_gwei"].quantile(
                upper_quantile
            )
        ),
        "dai_abs_peg_deviation_q90": float(
            calibration["dai_abs_peg_deviation"].quantile(upper_quantile)
        ),
        "liquidation_volume_q90": float(
            calibration["liquidation_volume_dai"].quantile(upper_quantile)
        ),
    }


def classify_regimes(
    frame: pd.DataFrame,
    thresholds: dict[str, float],
    *,
    minimum_conditions: int = 2,
) -> pd.DataFrame:
    """Apply the documented two-state rule without fitting new thresholds."""
    result = frame.copy()
    conditions = {
        "stress_low_eth_return": (
            result["eth_log_return"] < thresholds["eth_return_q05"]
        ),
        "stress_low_wbtc_return": (
            result["wbtc_log_return"] < thresholds["wbtc_return_q05"]
        ),
        "stress_high_crypto_volatility": (
            result["realised_crypto_volatility"]
            > thresholds["crypto_volatility_q90"]
        ),
        "stress_high_gas": (
            result["median_effective_gas_price_gwei"]
            > thresholds["gas_price_q90"]
        ),
        "stress_high_dai_deviation": (
            result["dai_abs_peg_deviation"]
            > thresholds["dai_abs_peg_deviation_q90"]
        ),
        "stress_high_liquidation_volume": (
            result["liquidation_volume_dai"]
            > thresholds["liquidation_volume_q90"]
        ),
    }
    for name, values in conditions.items():
        result[name] = values.fillna(False).astype("int8")
    condition_columns = list(conditions)
    result["stress_condition_count"] = result[condition_columns].sum(axis=1)
    result["regime"] = np.where(
        result["stress_condition_count"] >= minimum_conditions,
        "stress",
        "normal",
    )
    result["panic_candidate"] = (
        result["stress_condition_count"] >= 4
    ).astype("int8")
    return result


def transition_counts(
    states: pd.Series,
    timestamps: pd.Series,
    *,
    allowed_mask: pd.Series | None = None,
    labels: tuple[str, ...] = ("normal", "stress"),
) -> pd.DataFrame:
    """Count only transitions between consecutive allowed hourly rows."""
    state = pd.Series(states).reset_index(drop=True)
    time = pd.to_datetime(timestamps, utc=True).reset_index(drop=True)
    allowed = (
        pd.Series(True, index=state.index)
        if allowed_mask is None
        else pd.Series(allowed_mask).reset_index(drop=True).astype(bool)
    )
    counts = pd.DataFrame(0, index=labels, columns=labels, dtype="int64")
    for index in range(1, len(state)):
        if not (allowed.iloc[index - 1] and allowed.iloc[index]):
            continue
        if time.iloc[index] - time.iloc[index - 1] != pd.Timedelta(hours=1):
            continue
        previous = state.iloc[index - 1]
        current = state.iloc[index]
        if previous in labels and current in labels:
            counts.loc[previous, current] += 1
    counts.index.name = "from_regime"
    return counts


def transition_probabilities(counts: pd.DataFrame) -> pd.DataFrame:
    """Row-normalise a transition-count matrix without inventing transitions."""
    totals = counts.sum(axis=1).replace(0, np.nan)
    result = counts.div(totals, axis=0)
    result.index.name = counts.index.name
    return result


def regime_durations(
    states: pd.Series,
    timestamps: pd.Series,
    *,
    allowed_mask: pd.Series | None = None,
) -> pd.DataFrame:
    """Construct deterministic contiguous regime runs."""
    state = pd.Series(states).reset_index(drop=True)
    time = pd.to_datetime(timestamps, utc=True).reset_index(drop=True)
    allowed = (
        pd.Series(True, index=state.index)
        if allowed_mask is None
        else pd.Series(allowed_mask).reset_index(drop=True).astype(bool)
    )
    rows: list[dict[str, object]] = []
    run_state: str | None = None
    run_start: pd.Timestamp | None = None
    run_end: pd.Timestamp | None = None
    run_length = 0
    run_id = 0
    for index in range(len(state)):
        contiguous = (
            run_end is not None
            and time.iloc[index] - run_end == pd.Timedelta(hours=1)
        )
        if not allowed.iloc[index]:
            if run_state is not None:
                rows.append(
                    {
                        "run_id": run_id,
                        "regime": run_state,
                        "start_utc": run_start,
                        "end_utc": run_end,
                        "duration_hours": run_length,
                    }
                )
            run_state = None
            run_start = run_end = None
            run_length = 0
            continue
        current = str(state.iloc[index])
        if run_state is None or current != run_state or not contiguous:
            if run_state is not None:
                rows.append(
                    {
                        "run_id": run_id,
                        "regime": run_state,
                        "start_utc": run_start,
                        "end_utc": run_end,
                        "duration_hours": run_length,
                    }
                )
            run_id += 1
            run_state = current
            run_start = time.iloc[index]
            run_length = 1
        else:
            run_length += 1
        run_end = time.iloc[index]
    if run_state is not None:
        rows.append(
            {
                "run_id": run_id,
                "regime": run_state,
                "start_utc": run_start,
                "end_utc": run_end,
                "duration_hours": run_length,
            }
        )
    return pd.DataFrame(rows)


def aligned_dependence(
    frame: pd.DataFrame,
    columns: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    """Return covariance, Pearson and Spearman matrices on identical rows."""
    aligned = frame[columns].replace([np.inf, -np.inf], np.nan).dropna()
    if len(aligned) < 2:
        raise ValueError("At least two aligned observations are required.")
    return (
        aligned.cov(),
        aligned.corr(method="pearson"),
        aligned.corr(method="spearman"),
        int(len(aligned)),
    )


def overdispersion_summary(counts: pd.Series) -> dict[str, float | str | None]:
    """Compare Poisson and method-of-moments negative-binomial benchmarks."""
    values = pd.to_numeric(counts, errors="coerce").dropna().astype(float)
    if values.empty or (values < 0).any():
        raise ValueError("Counts must be non-negative and non-empty.")
    mean = float(values.mean())
    variance = float(values.var(ddof=1))
    dispersion = variance / mean if mean > 0 else None
    poisson_log_likelihood = float(
        sum(
            value * math.log(mean) - mean - math.lgamma(value + 1)
            for value in values
        )
    ) if mean > 0 else 0.0
    poisson_aic = 2 - 2 * poisson_log_likelihood
    nb_size: float | None = None
    nb_probability: float | None = None
    nb_log_likelihood: float | None = None
    nb_aic: float | None = None
    if variance > mean and mean > 0:
        nb_size = mean * mean / (variance - mean)
        nb_probability = nb_size / (nb_size + mean)
        nb_log_likelihood = float(
            sum(
                math.lgamma(value + nb_size)
                - math.lgamma(nb_size)
                - math.lgamma(value + 1)
                + nb_size * math.log(nb_probability)
                + value * math.log(1 - nb_probability)
                for value in values
            )
        )
        nb_aic = 4 - 2 * nb_log_likelihood
    zero_frequency = float((values == 0).mean())
    if zero_frequency > 0.90:
        representation = "empirical_distribution"
    elif nb_aic is not None and nb_aic + 10 < poisson_aic:
        representation = "negative_binomial_benchmark"
    else:
        representation = "poisson_benchmark"
    return {
        "n": int(len(values)),
        "mean": mean,
        "variance": variance,
        "dispersion_index": dispersion,
        "zero_activity_frequency": zero_frequency,
        "poisson_lambda": mean,
        "poisson_log_likelihood": poisson_log_likelihood,
        "poisson_aic": poisson_aic,
        "negative_binomial_size": nb_size,
        "negative_binomial_probability": nb_probability,
        "negative_binomial_log_likelihood": nb_log_likelihood,
        "negative_binomial_aic": nb_aic,
        "recommended_representation": representation,
    }
