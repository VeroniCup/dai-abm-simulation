"""Historical market-evidence validation for behavioural-confidence Design C.

The functions in this module are deliberately estimator-free.  They validate
and harmonise hourly DAI/ETH observations, compare a full-range candidate with
the existing panel, and apply the pre-registered burden and sparse-predictor
feasibility gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd


HISTORICAL_START = pd.Timestamp("2019-12-31T00:00:00Z")
HISTORICAL_END = pd.Timestamp("2024-07-01T00:00:00Z")
OVERLAP_START = pd.Timestamp("2021-06-01T00:00:00Z")
QUIET_START = pd.Timestamp("2022-11-01T00:00:00Z")
QUIET_END = pd.Timestamp("2022-11-21T00:00:00Z")
FINAL_STRESS_START = pd.Timestamp("2023-03-06T00:00:00Z")
FINAL_STRESS_END = pd.Timestamp("2023-03-20T00:00:00Z")

ASSET_IDENTITIES = {
    "ETH": {
        "dune_instrument": "WETH",
        "contract_address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    },
    "DAI": {
        "dune_instrument": "DAI",
        "contract_address": "0x6b175474e89094c44da98b954eedeac495271d0f",
    },
}

LONG_COLUMNS = (
    "timestamp_utc",
    "asset",
    "dune_instrument",
    "price_usd",
    "blockchain",
    "contract_address",
    "source",
    "volume_usd",
)


class HistoricalMarketEvidenceError(ValueError):
    """Raised when evidence cannot be harmonised without repair."""


@dataclass(frozen=True)
class SparseScale:
    """Calibration-owned positive-quantile scale and its declared gate."""

    positive_count: int
    positive_months: int
    positive_years: int
    distinct_positive_values: int
    positive_q95: float | None
    capped_share: float | None
    gate_passed: bool


def hourly_grid(
    start: pd.Timestamp = HISTORICAL_START,
    end_exclusive: pd.Timestamp = HISTORICAL_END,
) -> pd.DatetimeIndex:
    """Return the verified half-open UTC grid."""
    if start.tzinfo is None or end_exclusive.tzinfo is None:
        raise HistoricalMarketEvidenceError("Grid boundaries must be timezone-aware.")
    start = start.tz_convert("UTC")
    end_exclusive = end_exclusive.tz_convert("UTC")
    if start >= end_exclusive:
        raise HistoricalMarketEvidenceError("Grid start must precede its end.")
    return pd.date_range(start, end_exclusive, freq="h", inclusive="left")


def _strict_utc(values: Iterable[object]) -> pd.DatetimeIndex:
    parsed: list[pd.Timestamp] = []
    for value in values:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError) as exc:
            raise HistoricalMarketEvidenceError(
                f"Invalid market timestamp: {value!r}."
            ) from exc
        if pd.isna(timestamp) or timestamp.tzinfo is None:
            raise HistoricalMarketEvidenceError(
                f"Market timestamp does not declare a timezone: {value!r}."
            )
        if timestamp.utcoffset().total_seconds() != 0:
            raise HistoricalMarketEvidenceError(
                f"Market timestamp is not expressed in UTC: {value!r}."
            )
        parsed.append(timestamp.tz_convert("UTC"))
    return pd.DatetimeIndex(parsed)


def _normalise_volume(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.strip().str.lower()
    missing = values.isna() | text.isin({"", "<nil>", "nil", "null", "none"})
    numeric = pd.to_numeric(values.mask(missing), errors="coerce")
    malformed = ~missing & numeric.isna()
    if malformed.any():
        raise HistoricalMarketEvidenceError(
            f"{int(malformed.sum())} non-missing volumes are non-numeric."
        )
    return numeric.astype(float)


def harmonise_dune_hourly(
    raw: pd.DataFrame,
    start: pd.Timestamp = HISTORICAL_START,
    end_exclusive: pd.Timestamp = HISTORICAL_END,
) -> pd.DataFrame:
    """Create a complete two-asset UTC panel without filling observations."""
    missing_columns = sorted(set(LONG_COLUMNS) - set(raw.columns))
    if missing_columns:
        raise HistoricalMarketEvidenceError(
            f"Raw market evidence is missing columns: {missing_columns}."
        )

    frame = raw.loc[:, LONG_COLUMNS].copy()
    frame["timestamp_utc"] = _strict_utc(frame["timestamp_utc"])
    frame["asset"] = frame["asset"].astype(str)
    if set(frame["asset"]) != set(ASSET_IDENTITIES):
        raise HistoricalMarketEvidenceError(
            f"Unexpected asset population: {sorted(set(frame['asset']))}."
        )
    frame["contract_address"] = frame["contract_address"].astype(str).str.lower()
    if set(frame["blockchain"].astype(str)) != {"ethereum"}:
        raise HistoricalMarketEvidenceError("Only Ethereum observations are allowed.")

    for asset, identity in ASSET_IDENTITIES.items():
        subset = frame.loc[frame["asset"].eq(asset)]
        instruments = set(subset["dune_instrument"].astype(str))
        addresses = set(subset["contract_address"].astype(str))
        if instruments != {identity["dune_instrument"]}:
            raise HistoricalMarketEvidenceError(
                f"{asset} has unexpected Dune instruments: {sorted(instruments)}."
            )
        if addresses != {identity['contract_address']}:
            raise HistoricalMarketEvidenceError(
                f"{asset} has unexpected contract addresses: {sorted(addresses)}."
            )

    if frame.duplicated(["asset", "timestamp_utc"]).any():
        raise HistoricalMarketEvidenceError("Duplicate asset-hour rows are present.")
    prices = pd.to_numeric(frame["price_usd"], errors="coerce")
    if prices.isna().any() or not np.isfinite(prices).all():
        raise HistoricalMarketEvidenceError("Prices must be finite and observed.")
    if (prices <= 0).any():
        raise HistoricalMarketEvidenceError("Prices must be strictly positive.")
    frame["price_usd"] = prices.astype(float)
    frame["volume_usd"] = _normalise_volume(frame["volume_usd"])

    expected = hourly_grid(start, end_exclusive)
    observed = pd.DatetimeIndex(frame["timestamp_utc"].unique()).sort_values()
    missing = expected.difference(observed)
    extra = observed.difference(expected)
    if len(missing) or len(extra):
        raise HistoricalMarketEvidenceError(
            f"Hourly coverage differs from the requested grid: "
            f"{len(missing)} missing, {len(extra)} extra."
        )
    for asset in ASSET_IDENTITIES:
        asset_hours = pd.DatetimeIndex(
            frame.loc[frame["asset"].eq(asset), "timestamp_utc"]
        ).sort_values()
        if not asset_hours.equals(expected):
            raise HistoricalMarketEvidenceError(
                f"{asset} does not contain every requested hour exactly once."
            )

    frame = frame.sort_values(["timestamp_utc", "asset"], kind="stable")
    output = pd.DataFrame({"timestamp_utc": expected})
    for asset, prefix in (("ETH", "eth"), ("DAI", "dai")):
        subset = frame.loc[frame["asset"].eq(asset)].set_index("timestamp_utc")
        output[f"{prefix}_price_usd"] = subset.loc[expected, "price_usd"].to_numpy()
        output[f"{prefix}_source"] = subset.loc[expected, "source"].astype(str).to_numpy()
        output[f"{prefix}_source_volume_usd"] = subset.loc[
            expected, "volume_usd"
        ].to_numpy()
        identity = ASSET_IDENTITIES[asset]
        output[f"{prefix}_source_identifier"] = (
            "prices.hour:"
            + output[f"{prefix}_source"]
            + ":ethereum:"
            + identity["contract_address"]
        )
        output[f"{prefix}_data_quality_flags"] = np.where(
            output[f"{prefix}_source_volume_usd"].isna(),
            "source_volume_unavailable",
            "",
        )
    output["eth_log_return"] = np.log(output["eth_price_usd"]).diff()
    return output


def identical_price_runs(
    panel: pd.DataFrame,
    asset_prefix: str,
    minimum_hours: int = 6,
) -> list[dict[str, Any]]:
    """Report consecutive equal-price runs without treating them as errors."""
    price_column = f"{asset_prefix}_price_usd"
    source_column = f"{asset_prefix}_source"
    volume_column = f"{asset_prefix}_source_volume_usd"
    timestamps = pd.DatetimeIndex(panel["timestamp_utc"])
    prices = panel[price_column].to_numpy(dtype=float)
    records: list[dict[str, Any]] = []
    run_start = 0
    for position in range(1, len(panel) + 1):
        continues = (
            position < len(panel)
            and prices[position] == prices[position - 1]
            and timestamps[position] - timestamps[position - 1]
            == pd.Timedelta(hours=1)
        )
        if continues:
            continue
        length = position - run_start
        if length >= minimum_hours:
            subset = panel.iloc[run_start:position]
            volume = subset[volume_column]
            records.append(
                {
                    "start_utc": timestamps[run_start].isoformat(),
                    "end_utc": timestamps[position - 1].isoformat(),
                    "hours": int(length),
                    "price_usd": float(prices[run_start]),
                    "source_changes": int(
                        subset[source_column].astype(str).ne(
                            subset[source_column].astype(str).shift()
                        ).sum()
                        - 1
                    ),
                    "zero_or_missing_volume_hours": int(
                        (volume.isna() | volume.eq(0)).sum()
                    ),
                }
            )
        run_start = position
    return records


def _summary_statistics(values: pd.Series) -> dict[str, float | int | None]:
    finite = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if finite.empty:
        return {"count": 0}
    return {
        "count": int(len(finite)),
        "mean": float(finite.mean()),
        "median": float(finite.median()),
        "p95": float(finite.quantile(0.95)),
        "p99": float(finite.quantile(0.99)),
        "maximum": float(finite.max()),
    }


def _continuous_burden(prices: pd.Series) -> pd.Series:
    severity = np.minimum(1.0, np.maximum(0.0, 0.995 - prices) / 0.005)
    return pd.Series(severity, index=prices.index).rolling(
        6, min_periods=6
    ).mean().shift(-5)


def compare_overlap(
    candidate: pd.DataFrame,
    existing: pd.DataFrame,
    overlap_start: pd.Timestamp = OVERLAP_START,
    overlap_end: pd.Timestamp = HISTORICAL_END,
) -> dict[str, Any]:
    """Compare candidate and current observations on their exact common grid."""
    left = candidate.copy()
    right = existing.copy()
    left["timestamp_utc"] = pd.to_datetime(left["timestamp_utc"], utc=True)
    right["timestamp_utc"] = pd.to_datetime(right["timestamp_utc"], utc=True)
    left = left.set_index("timestamp_utc").sort_index().loc[
        overlap_start:overlap_end - pd.Timedelta(hours=1)
    ]
    right = right.set_index("timestamp_utc").sort_index().loc[
        overlap_start:overlap_end - pd.Timedelta(hours=1)
    ]
    expected = hourly_grid(overlap_start, overlap_end)
    report: dict[str, Any] = {
        "requested_overlap_hours": int(len(expected)),
        "candidate_missing_timestamps": [
            value.isoformat() for value in expected.difference(left.index)
        ],
        "existing_missing_timestamps": [
            value.isoformat() for value in expected.difference(right.index)
        ],
        "assets": {},
    }
    common = left.index.intersection(right.index)
    for prefix in ("dai", "eth"):
        column = f"{prefix}_price_usd"
        candidate_values = left.loc[common, column].astype(float)
        existing_values = right.loc[common, column].astype(float)
        difference = candidate_values - existing_values
        absolute = difference.abs()
        relative = absolute / existing_values.abs()
        largest = absolute.nlargest(min(10, len(absolute)))
        asset_report: dict[str, Any] = {
            "matched_timestamps": int(len(common)),
            "exact_matches": int(candidate_values.eq(existing_values).sum()),
            "absolute_difference": _summary_statistics(absolute),
            "relative_difference_quantiles": {
                "p50": float(relative.quantile(0.50)),
                "p95": float(relative.quantile(0.95)),
                "p99": float(relative.quantile(0.99)),
                "maximum": float(relative.max()),
            },
            "price_correlation": float(candidate_values.corr(existing_values)),
            "largest_discrepancies": [
                {
                    "timestamp_utc": timestamp.isoformat(),
                    "candidate": float(candidate_values.loc[timestamp]),
                    "existing": float(existing_values.loc[timestamp]),
                    "absolute_difference": float(value),
                }
                for timestamp, value in largest.items()
            ],
        }
        if prefix == "eth":
            candidate_returns = np.log(candidate_values).diff()
            existing_returns = np.log(existing_values).diff()
            asset_report["log_return_correlation"] = float(
                candidate_returns.corr(existing_returns)
            )
        else:
            candidate_burden = _continuous_burden(candidate_values)
            existing_burden = _continuous_burden(existing_values)
            burden_difference = (candidate_burden - existing_burden).abs()
            asset_report["label_disagreements"] = {
                "below_0_995": int(
                    candidate_values.lt(0.995).ne(existing_values.lt(0.995)).sum()
                ),
                "below_0_99": int(
                    candidate_values.lt(0.99).ne(existing_values.lt(0.99)).sum()
                ),
                "outside_symmetric_recovery_band": int(
                    candidate_values.between(0.995, 1.005).ne(
                        existing_values.between(0.995, 1.005)
                    ).sum()
                ),
                "six_hour_burden_numerically_different": int(
                    burden_difference.gt(0).sum()
                ),
                "six_hour_burden_materially_different": int(
                    burden_difference.gt(1e-12).sum()
                ),
            }
            asset_report["total_six_hour_burden"] = {
                "candidate": float(candidate_burden.sum()),
                "existing": float(existing_burden.sum()),
                "absolute_difference": float(burden_difference.sum()),
            }
            asset_report["episode_disagreements"] = {}
            for name, start, end in (
                ("november_2022", QUIET_START, QUIET_END),
                (
                    "terra_cefi",
                    pd.Timestamp("2022-05-05T00:00:00Z"),
                    pd.Timestamp("2022-06-20T00:00:00Z"),
                ),
                ("usdc_svb", FINAL_STRESS_START, FINAL_STRESS_END),
            ):
                mask = (common >= start) & (common < end)
                asset_report["episode_disagreements"][name] = {
                    "price_hours_different": int(absolute.loc[mask].gt(1e-15).sum()),
                    "burden_absolute_difference": float(
                        burden_difference.loc[mask].sum()
                    ),
                }
        report["assets"][prefix.upper()] = asset_report
    return report


def sparse_positive_scale(
    values: pd.Series,
    timestamps: pd.Series | pd.DatetimeIndex,
) -> tuple[pd.Series, SparseScale]:
    """Apply the frozen positive-Q95 scaling rule and report its gate."""
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    time_index = pd.DatetimeIndex(timestamps)
    positive = numeric.gt(0) & np.isfinite(numeric)
    positive_values = numeric.loc[positive]
    q95 = (
        float(positive_values.quantile(0.95))
        if len(positive_values) and np.isfinite(positive_values).all()
        else None
    )
    months = pd.PeriodIndex(time_index[positive], freq="M").nunique()
    years = pd.Index(time_index[positive].year).nunique()
    distinct = int(positive_values.nunique())
    eligible_scale = q95 is not None and np.isfinite(q95) and q95 > 0
    scaled = pd.Series(np.nan, index=values.index, dtype=float)
    finite = numeric.notna() & np.isfinite(numeric)
    if eligible_scale:
        scaled.loc[finite] = np.minimum(1.0, numeric.loc[finite] / q95)
    gate = (
        int(positive.sum()) >= 100
        and int(months) >= 12
        and int(years) >= 2
        and distinct >= 20
        and eligible_scale
    )
    summary = SparseScale(
        positive_count=int(positive.sum()),
        positive_months=int(months),
        positive_years=int(years),
        distinct_positive_values=distinct,
        positive_q95=q95,
        capped_share=(
            float(scaled.loc[finite].eq(1.0).mean())
            if eligible_scale and finite.any()
            else None
        ),
        gate_passed=bool(gate),
    )
    return scaled, summary


def design_c_partition(timestamp: pd.Timestamp) -> str:
    """Return the fixed Design C partition for one UTC timestamp."""
    if QUIET_START <= timestamp < QUIET_END:
        return "quiet_validation"
    if FINAL_STRESS_START <= timestamp < FINAL_STRESS_END:
        return "final_stress_validation"
    return "calibration"


def downside_episode_map(
    prices: pd.Series,
) -> tuple[pd.Series, list[dict[str, Any]]]:
    """Label one-sided episodes closed by 24 consecutive normal hours."""
    labels = pd.Series(index=prices.index, dtype="object")
    episodes: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    normal_run = 0
    for position, (timestamp, price) in enumerate(prices.items()):
        below = float(price) < 0.995
        if active is None and below:
            prior = prices.iloc[max(0, position - 24):position]
            if position >= 24 and prior.ge(0.995).all():
                active = {
                    "episode_id": f"E{len(episodes) + 1:03d}",
                    "start_utc": timestamp.isoformat(),
                    "left_censored": False,
                }
            elif position == 0:
                active = {
                    "episode_id": f"E{len(episodes) + 1:03d}",
                    "start_utc": timestamp.isoformat(),
                    "left_censored": True,
                }
        if active is not None:
            if below:
                labels.loc[timestamp] = active["episode_id"]
                normal_run = 0
            else:
                normal_run += 1
                if normal_run == 24:
                    active["end_utc"] = timestamp.isoformat()
                    active["right_censored"] = False
                    episodes.append(active)
                    active = None
                    normal_run = 0
    if active is not None:
        active["end_utc"] = prices.index[-1].isoformat()
        active["right_censored"] = True
        episodes.append(active)
    return labels, episodes


def build_design_c_origins(
    panel: pd.DataFrame,
    anchor: int = 0,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Build deterministic no-fit Design C origins for one six-hour anchor."""
    if anchor not in range(6):
        raise HistoricalMarketEvidenceError("Anchor must be an integer from 0 to 5.")
    frame = panel.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame = frame.set_index("timestamp_utc").sort_index()
    expected = hourly_grid()
    if not frame.index.equals(expected):
        raise HistoricalMarketEvidenceError("Design C requires the exact full grid.")
    required = {"dai_price_usd", "eth_price_usd", "eth_log_return"}
    if not required.issubset(frame.columns):
        raise HistoricalMarketEvidenceError(
            f"Design C panel is missing: {sorted(required - set(frame.columns))}."
        )
    if frame[["dai_price_usd", "eth_price_usd"]].isna().any().any():
        raise HistoricalMarketEvidenceError("Design C prices may not be missing.")

    partition = pd.Series(
        [design_c_partition(timestamp) for timestamp in frame.index],
        index=frame.index,
    )
    episode_labels, episodes = downside_episode_map(frame["dai_price_usd"])
    rows: list[dict[str, Any]] = []
    for position, timestamp in enumerate(frame.index):
        if timestamp.hour % 6 != anchor:
            continue
        if position < 24 or position + 5 >= len(frame):
            continue
        span = partition.iloc[position - 24:position + 6]
        if not span.eq(partition.iloc[position]).all():
            continue
        returns = frame["eth_log_return"].iloc[position - 24:position]
        future = frame["dai_price_usd"].iloc[position:position + 6]
        if returns.isna().any() or future.isna().any():
            continue
        severity = np.minimum(
            1.0,
            np.maximum(0.0, 0.995 - future.to_numpy(dtype=float)) / 0.005,
        )
        future_episodes = (
            episode_labels.iloc[position:position + 6].dropna().unique().tolist()
        )
        if len(future_episodes) > 1:
            raise HistoricalMarketEvidenceError(
                f"Origin {timestamp.isoformat()} spans multiple downside episodes."
            )
        rows.append(
            {
                "timestamp_utc": timestamp,
                "partition": partition.iloc[position],
                "anchor": anchor,
                "year": int(timestamp.year),
                "month": timestamp.strftime("%Y-%m"),
                "burden": float(severity.mean()),
                "episode_id": future_episodes[0] if future_episodes else None,
                "lagged_below_peg_gap": max(
                    1.0 - float(frame["dai_price_usd"].iloc[position - 1]), 0.0
                ),
                "lagged_24h_eth_downside": max(0.0, -float(returns.sum())),
            }
        )
    return pd.DataFrame(rows), episodes


def burden_summary(origins: pd.DataFrame) -> dict[str, Any]:
    """Summarise the fixed continuous burden target."""
    values = origins["burden"].astype(float)
    positive = origins.loc[values.gt(0)]
    episode_burden = (
        positive.groupby("episode_id", dropna=True)["burden"]
        .sum()
        .sort_values(ascending=False)
    )
    total = float(values.sum())
    positive_values = positive["burden"].to_numpy(dtype=float)
    by_year = origins.groupby("year")["burden"].sum()
    return {
        "retained_origins": int(len(origins)),
        "nonzero_origins": int(values.gt(0).sum()),
        "burden_ge_0_10": int(values.ge(0.10).sum()),
        "burden_ge_0_25": int(values.ge(0.25).sum()),
        "burden_ge_0_50": int(values.ge(0.50).sum()),
        "mean_burden": float(values.mean()) if len(values) else None,
        "positive_burden_median": (
            float(np.median(positive_values)) if len(positive_values) else None
        ),
        "positive_burden_iqr": (
            float(np.quantile(positive_values, 0.75) - np.quantile(positive_values, 0.25))
            if len(positive_values)
            else None
        ),
        "p90_burden": float(values.quantile(0.90)) if len(values) else None,
        "p95_burden": float(values.quantile(0.95)) if len(values) else None,
        "p99_burden": float(values.quantile(0.99)) if len(values) else None,
        "total_burden": total,
        "burden_by_year": {str(key): float(value) for key, value in by_year.items()},
        "burden_by_episode": {
            str(key): float(value) for key, value in episode_burden.items()
        },
        "distinct_contributing_episodes": int(episode_burden.index.nunique()),
        "largest_episode_share": (
            float(episode_burden.iloc[0] / total)
            if total > 0 and len(episode_burden)
            else None
        ),
        "unassigned_nonzero_origins": int(positive["episode_id"].isna().sum()),
    }


def _quintile_burden(values: pd.Series, burden: pd.Series) -> list[dict[str, Any]]:
    ranks = values.rank(method="first")
    bins = pd.qcut(ranks, 5, labels=False)
    records = []
    for quintile in range(5):
        mask = bins.eq(quintile)
        records.append(
            {
                "quintile": quintile + 1,
                "origins": int(mask.sum()),
                "mean_burden": float(burden.loc[mask].mean()),
                "total_burden": float(burden.loc[mask].sum()),
            }
        )
    return records


def _validation_extrapolation(
    values: pd.Series,
    scale: float | None,
) -> dict[str, Any]:
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if numeric.empty or scale is None or not np.isfinite(scale) or scale <= 0:
        return {"observations": int(len(numeric)), "scale_available": False}
    above = numeric.gt(scale)
    return {
        "observations": int(len(numeric)),
        "scale_available": True,
        "maximum_raw_value": float(numeric.max()),
        "above_calibration_positive_q95_count": int(above.sum()),
        "above_calibration_positive_q95_share": float(above.mean()),
        "maximum_scaled_value_after_capping": float(
            np.minimum(1.0, numeric / scale).max()
        ),
    }


def evaluate_design_c(panel: pd.DataFrame) -> dict[str, Any]:
    """Apply all pre-registered no-fit Design C gates."""
    primary, episodes = build_design_c_origins(panel, anchor=0)
    calibration = primary.loc[primary["partition"].eq("calibration")].copy()
    quiet = primary.loc[primary["partition"].eq("quiet_validation")]
    final = primary.loc[primary["partition"].eq("final_stress_validation")]
    peg_scaled, peg_scale = sparse_positive_scale(
        calibration["lagged_below_peg_gap"], calibration["timestamp_utc"]
    )
    eth_scaled, eth_scale = sparse_positive_scale(
        calibration["lagged_24h_eth_downside"], calibration["timestamp_utc"]
    )
    calibration["scaled_lagged_below_peg_gap"] = peg_scaled
    calibration["scaled_lagged_24h_eth_downside"] = eth_scaled
    burden = burden_summary(calibration)
    positive_years = sum(
        value > 0 for value in burden["burden_by_year"].values()
    )
    burden_gates = {
        "at_least_100_nonzero_origins": burden["nonzero_origins"] >= 100,
        "at_least_50_origins_ge_0_10": burden["burden_ge_0_10"] >= 50,
        "at_least_20_episodes": burden["distinct_contributing_episodes"] >= 20,
        "largest_episode_at_most_25pct": (
            burden["largest_episode_share"] is not None
            and burden["largest_episode_share"] <= 0.25
        ),
        "nonzero_burden_in_two_years": positive_years >= 2,
        "positive_burden_iqr": (
            burden["positive_burden_iqr"] is not None
            and burden["positive_burden_iqr"] > 0
        ),
    }
    anchor_sensitivity = {}
    for anchor in range(6):
        origins, _ = build_design_c_origins(panel, anchor=anchor)
        anchor_sensitivity[str(anchor)] = burden_summary(
            origins.loc[origins["partition"].eq("calibration")]
        )
    scaling = {
        "lagged_below_peg_gap": peg_scale.__dict__,
        "lagged_24h_eth_downside": eth_scale.__dict__,
        "correlation": float(
            calibration["scaled_lagged_below_peg_gap"].corr(
                calibration["scaled_lagged_24h_eth_downside"]
            )
        ),
        "burden_by_predictor_quintile": {
            "lagged_below_peg_gap": _quintile_burden(
                calibration["scaled_lagged_below_peg_gap"],
                calibration["burden"],
            ),
            "lagged_24h_eth_downside": _quintile_burden(
                calibration["scaled_lagged_24h_eth_downside"],
                calibration["burden"],
            ),
        },
        "validation_extrapolation": {
            "quiet_validation": {
                "lagged_below_peg_gap": _validation_extrapolation(
                    quiet["lagged_below_peg_gap"], peg_scale.positive_q95
                ),
                "lagged_24h_eth_downside": _validation_extrapolation(
                    quiet["lagged_24h_eth_downside"], eth_scale.positive_q95
                ),
            },
            "final_stress_validation": {
                "lagged_below_peg_gap": _validation_extrapolation(
                    final["lagged_below_peg_gap"], peg_scale.positive_q95
                ),
                "lagged_24h_eth_downside": _validation_extrapolation(
                    final["lagged_24h_eth_downside"], eth_scale.positive_q95
                ),
            },
        },
    }
    all_gates = all(burden_gates.values()) and peg_scale.gate_passed and eth_scale.gate_passed
    return {
        "partition": {
            "calibration": (
                "[2019-12-31T00:00:00Z, 2024-07-01T00:00:00Z) excluding "
                "quiet and final-stress validation"
            ),
            "quiet_validation": (
                "[2022-11-01T00:00:00Z, 2022-11-21T00:00:00Z)"
            ),
            "final_stress_validation": (
                "[2023-03-06T00:00:00Z, 2023-03-20T00:00:00Z)"
            ),
        },
        "calibration_burden": burden,
        "quiet_validation_burden": burden_summary(quiet),
        "final_stress_validation_burden": burden_summary(final),
        "burden_gates": burden_gates,
        "predictor_scaling": scaling,
        "anchor_sensitivity": anchor_sensitivity,
        "episodes": episodes,
        "coefficient_fitted": False,
        "classification": (
            "Ready for bounded fitting"
            if all_gates
            else "Market extension acquired, but fitting still unsupported"
        ),
    }
