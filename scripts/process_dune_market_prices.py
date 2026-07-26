"""Construct and validate the Phase 1A processed Dune market-price panel.

This command is entirely local. It verifies the immutable raw result, pivots
the four price series without aggregation, calculates transparent derived
variables, writes an exception-review table, and records complete provenance.
It does not estimate model parameters or classify historical stress periods.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.acquire_dune_market_prices import sha256_file, write_json  # noqa: E402
from scripts.validate_dune_market_prices import (  # noqa: E402
    EXPECTED,
    REQUIRED_COLUMNS,
    parse_strict_utc,
    validate_prices,
)
EXPECTED_RAW_SHA256 = (
    "99487a45d4e56cd27ee8f108413f0677af0e87efc4d2af3e071fe80d89e524d5"
)
DEFAULT_INPUT = Path(
    "data/raw/market/dune_prices_hourly_2021-06-01_2024-06-30.csv"
)
DEFAULT_RAW_VALIDATION = Path(
    "data/provenance/market/dune_prices_hourly_2021-06-01_2024-06-30.validation.json"
)
DEFAULT_OUTPUT_DIRECTORY = Path("data/processed/market")
DEFAULT_PROVENANCE_DIRECTORY = Path("data/provenance/market")
DEFAULT_MANIFEST = Path("data/provenance/manifests/data_manifest.csv")
DEFAULT_START = pd.Timestamp("2021-06-01T00:00:00Z")
DEFAULT_END_EXCLUSIVE = pd.Timestamp("2024-07-01T00:00:00Z")
ASSET_PRICE_COLUMNS = {
    "ETH": "eth_price_usd",
    "WBTC": "wbtc_price_usd",
    "DAI": "dai_price_usd",
    "USDC": "usdc_price_usd",
}
ASSET_RETURN_COLUMNS = {
    "ETH": "eth_log_return",
    "WBTC": "wbtc_log_return",
    "DAI": "dai_log_return",
    "USDC": "usdc_log_return",
}
PROCESSED_COLUMNS = (
    "timestamp_utc",
    "eth_price_usd",
    "wbtc_price_usd",
    "dai_price_usd",
    "usdc_price_usd",
    "eth_log_return",
    "wbtc_log_return",
    "dai_log_return",
    "usdc_log_return",
    "dai_peg_deviation",
    "usdc_peg_deviation",
    "dai_abs_peg_deviation",
    "usdc_abs_peg_deviation",
    "dai_below_peg",
    "usdc_below_peg",
    "dai_source",
    "usdc_source",
)
REVIEW_COLUMNS = (
    "timestamp_utc",
    "asset",
    "price_usd",
    "peg_deviation",
    "abs_peg_deviation",
    "rolling_median_24h",
    "deviation_from_rolling_median",
    "previous_hour_price_usd",
    "next_hour_price_usd",
    "other_stablecoin_asset",
    "other_stablecoin_price_usd",
    "eth_price_usd",
    "eth_log_return",
    "wbtc_price_usd",
    "wbtc_log_return",
    "both_stablecoins_abs_peg_above_0_02",
    "flag_price_below_0_95",
    "flag_price_above_1_05",
    "flag_abs_peg_deviation_above_0_02",
    "flag_abs_rolling_median_deviation_above_0_02",
    "flagged_run_id",
    "flagged_run_length_hours",
)
MANIFEST_PROCESSING_COLUMNS = (
    "processed_file_path",
    "processed_file_size_bytes",
    "processed_sha256",
    "processing_script_path",
    "processing_script_sha256",
    "processing_timestamp_utc",
    "processed_row_count",
    "processed_column_count",
    "processed_validation_status",
    "processed_validation_report_path",
    "processing_metadata_path",
    "stablecoin_review_path",
    "stablecoin_review_row_count",
    "stablecoin_review_sha256",
    "processed_transformation",
)


class ProcessingError(RuntimeError):
    """Raised when an integrity or processing invariant fails."""


def expected_hourly_index(
    start: pd.Timestamp = DEFAULT_START,
    end_exclusive: pd.Timestamp = DEFAULT_END_EXCLUSIVE,
) -> pd.DatetimeIndex:
    """Return the complete requested half-open hourly UTC index."""
    return pd.date_range(
        start=start,
        end=end_exclusive - pd.Timedelta(hours=1),
        freq="1h",
        tz="UTC",
        name="timestamp_utc",
    )


def _read_raw(path: Path) -> pd.DataFrame:
    """Read raw values using round-trip float parsing and strict UTC timestamps."""
    frame = pd.read_csv(
        path,
        dtype={
            "asset": "string",
            "dune_instrument": "string",
            "blockchain": "string",
            "contract_address": "string",
            "source": "string",
        },
        float_precision="round_trip",
    )
    timestamps, naive, non_utc, invalid = parse_strict_utc(frame["timestamp_utc"])
    if naive or non_utc or invalid:
        raise ProcessingError(
            "Raw timestamps failed strict UTC parsing: "
            f"naive={naive}, non_utc={non_utc}, invalid={invalid}."
        )
    frame["timestamp_utc"] = timestamps
    frame["price_usd"] = pd.to_numeric(frame["price_usd"], errors="coerce")
    return frame


def validate_raw_integrity(
    raw_path: Path,
    raw_validation_path: Path,
    expected_sha256: str = EXPECTED_RAW_SHA256,
    start: pd.Timestamp = DEFAULT_START,
    end_exclusive: pd.Timestamp = DEFAULT_END_EXCLUSIVE,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Enforce the Phase 1A structural gate before any processing occurs."""
    if not raw_path.exists():
        raise ProcessingError(f"Raw Dune file does not exist: {raw_path}.")
    if not raw_validation_path.exists():
        raise ProcessingError(
            f"Raw validation report does not exist: {raw_validation_path}."
        )

    raw_checksum = sha256_file(raw_path)
    if raw_checksum != expected_sha256:
        raise ProcessingError(
            "Raw SHA-256 does not match the authorised acquisition: "
            f"expected {expected_sha256}, observed {raw_checksum}."
        )

    documented_report = json.loads(raw_validation_path.read_text(encoding="utf-8"))
    if not documented_report.get("validation_passed"):
        raise ProcessingError("The documented raw validation report did not pass.")

    recalculated_report, failures = validate_prices(
        raw_path,
        requested_start=start,
        requested_end=end_exclusive,
    )
    if failures:
        raise ProcessingError(
            "Recalculated raw validation failed: " + "; ".join(failures)
        )

    frame = _read_raw(raw_path)
    expected_rows = len(expected_hourly_index(start, end_exclusive)) * len(EXPECTED)
    expected_counts = {
        asset: len(expected_hourly_index(start, end_exclusive)) for asset in EXPECTED
    }
    observed_counts = {
        str(asset): int(count)
        for asset, count in frame.groupby("asset", observed=True).size().items()
    }
    volume_text = frame["volume_usd"].astype("string").str.strip().str.lower()
    unavailable_volume_count = int(
        (frame["volume_usd"].isna() | volume_text.isin({"", "<nil>", "nil", "null", "none"})).sum()
    )
    checks = {
        "raw_sha256_matches": raw_checksum == expected_sha256,
        "row_count_matches": len(frame) == expected_rows,
        "column_count_matches": len(frame.columns) == len(REQUIRED_COLUMNS),
        "required_columns_match": tuple(frame.columns) == tuple(REQUIRED_COLUMNS),
        "expected_assets_match": set(frame["asset"].dropna()) == set(EXPECTED),
        "per_asset_counts_match": observed_counts == expected_counts,
        "duplicate_asset_hour_count": int(
            frame.duplicated(["asset", "timestamp_utc"]).sum()
        ),
        "null_price_count": int(frame["price_usd"].isna().sum()),
        "non_positive_price_count": int((frame["price_usd"] <= 0).sum()),
        "unavailable_volume_count": unavailable_volume_count,
        "raw_validation_recalculated_passed": not failures,
        "documented_validation_passed": bool(
            documented_report.get("validation_passed")
        ),
    }
    failed_boolean_checks = [
        key for key, value in checks.items() if isinstance(value, bool) and not value
    ]
    failed_count_checks = [
        key
        for key in (
            "duplicate_asset_hour_count",
            "null_price_count",
            "non_positive_price_count",
        )
        if checks[key] != 0
    ]
    if failed_boolean_checks or failed_count_checks:
        raise ProcessingError(
            "Raw structural gate failed: "
            + ", ".join(failed_boolean_checks + failed_count_checks)
        )

    return frame, {
        "raw_sha256": raw_checksum,
        "input_dimensions": {"rows": int(len(frame)), "columns": int(len(frame.columns))},
        "per_asset_row_counts": observed_counts,
        "unavailable_volume_count": unavailable_volume_count,
        "checks": checks,
        "recalculated_validation": recalculated_report,
    }


def build_processed_panel(
    raw: pd.DataFrame,
    start: pd.Timestamp = DEFAULT_START,
    end_exclusive: pd.Timestamp = DEFAULT_END_EXCLUSIVE,
) -> pd.DataFrame:
    """Pivot validated raw prices and calculate the requested derived series."""
    expected_index = expected_hourly_index(start, end_exclusive)
    prices = raw.pivot(
        index="timestamp_utc",
        columns="asset",
        values="price_usd",
    ).sort_index()
    sources = raw.pivot(
        index="timestamp_utc",
        columns="asset",
        values="source",
    ).sort_index()
    if not prices.index.equals(expected_index) or not sources.index.equals(expected_index):
        raise ProcessingError("Raw pivots do not equal the complete requested UTC grid.")

    panel = pd.DataFrame(index=expected_index)
    for asset, output_column in ASSET_PRICE_COLUMNS.items():
        panel[output_column] = prices[asset].to_numpy(dtype=float)
    for asset, output_column in ASSET_RETURN_COLUMNS.items():
        price_column = ASSET_PRICE_COLUMNS[asset]
        panel[output_column] = np.log(panel[price_column]).diff()

    for stablecoin in ("dai", "usdc"):
        price = panel[f"{stablecoin}_price_usd"]
        deviation = price - 1.0
        panel[f"{stablecoin}_peg_deviation"] = deviation
        panel[f"{stablecoin}_abs_peg_deviation"] = deviation.abs()
        panel[f"{stablecoin}_below_peg"] = (price < 1.0).astype("int8")
        panel[f"{stablecoin}_source"] = sources[stablecoin.upper()].astype("string").to_numpy()

    return panel.reset_index().loc[:, PROCESSED_COLUMNS]


def build_stablecoin_extreme_review(panel: pd.DataFrame) -> pd.DataFrame:
    """Create an evidence-only review table for all requested extreme flags."""
    indexed = panel.set_index("timestamp_utc").copy()
    records = []
    both_abs = (
        (indexed["dai_abs_peg_deviation"] > 0.02)
        & (indexed["usdc_abs_peg_deviation"] > 0.02)
    )

    for asset, other in (("DAI", "USDC"), ("USDC", "DAI")):
        label = asset.lower()
        other_label = other.lower()
        price = indexed[f"{label}_price_usd"]
        peg = indexed[f"{label}_peg_deviation"]
        absolute = indexed[f"{label}_abs_peg_deviation"]
        rolling_median = price.rolling(
            window="24h",
            center=True,
            min_periods=1,
        ).median()
        rolling_deviation = price - rolling_median
        below = price < 0.95
        above = price > 1.05
        peg_extreme = absolute > 0.02
        rolling_extreme = rolling_deviation.abs() > 0.02
        flagged = below | above | peg_extreme | rolling_extreme

        asset_review = pd.DataFrame(
            {
                "timestamp_utc": indexed.index,
                "asset": asset,
                "price_usd": price,
                "peg_deviation": peg,
                "abs_peg_deviation": absolute,
                "rolling_median_24h": rolling_median,
                "deviation_from_rolling_median": rolling_deviation,
                "previous_hour_price_usd": price.shift(1),
                "next_hour_price_usd": price.shift(-1),
                "other_stablecoin_asset": other,
                "other_stablecoin_price_usd": indexed[
                    f"{other_label}_price_usd"
                ],
                "eth_price_usd": indexed["eth_price_usd"],
                "eth_log_return": indexed["eth_log_return"],
                "wbtc_price_usd": indexed["wbtc_price_usd"],
                "wbtc_log_return": indexed["wbtc_log_return"],
                "both_stablecoins_abs_peg_above_0_02": both_abs.astype("int8"),
                "flag_price_below_0_95": below.astype("int8"),
                "flag_price_above_1_05": above.astype("int8"),
                "flag_abs_peg_deviation_above_0_02": peg_extreme.astype("int8"),
                "flag_abs_rolling_median_deviation_above_0_02": (
                    rolling_extreme.astype("int8")
                ),
            }
        ).loc[flagged.to_numpy()]
        records.append(asset_review)

    review = pd.concat(records, ignore_index=True).sort_values(
        ["asset", "timestamp_utc"],
        kind="stable",
    )
    if review.empty:
        review["flagged_run_id"] = pd.Series(dtype="string")
        review["flagged_run_length_hours"] = pd.Series(dtype="int64")
        return review.loc[:, REVIEW_COLUMNS]

    new_run = review.groupby("asset", sort=False)["timestamp_utc"].diff().ne(
        pd.Timedelta(hours=1)
    )
    run_number = new_run.groupby(review["asset"], sort=False).cumsum().astype(int)
    review["flagged_run_id"] = [
        f"{asset}-{number:04d}"
        for asset, number in zip(review["asset"], run_number, strict=True)
    ]
    review["flagged_run_length_hours"] = review.groupby(
        "flagged_run_id", sort=False
    )["timestamp_utc"].transform("size").astype(int)
    return review.loc[:, REVIEW_COLUMNS].reset_index(drop=True)


def _timestamp_record(row: pd.Series) -> dict[str, Any]:
    """Serialise a stablecoin observation for descriptive metadata."""
    return {
        "timestamp_utc": pd.Timestamp(row["timestamp_utc"]).isoformat(),
        "price_usd": float(row["price_usd"]),
        "peg_deviation": float(row["peg_deviation"]),
        "absolute_peg_deviation": float(abs(row["peg_deviation"])),
    }


def build_descriptive_review(
    panel: pd.DataFrame,
    review: pd.DataFrame,
) -> dict[str, Any]:
    """Summarise observed stablecoin extremes without classifying errors."""
    stable_long = pd.concat(
        [
            pd.DataFrame(
                {
                    "timestamp_utc": panel["timestamp_utc"],
                    "asset": asset.upper(),
                    "price_usd": panel[f"{asset}_price_usd"],
                    "peg_deviation": panel[f"{asset}_peg_deviation"],
                    "abs_peg_deviation": panel[f"{asset}_abs_peg_deviation"],
                }
            )
            for asset in ("dai", "usdc")
        ],
        ignore_index=True,
    )
    result: dict[str, Any] = {"by_asset": {}}
    quantile_probabilities = (0.0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0)

    for asset in ("DAI", "USDC"):
        observations = stable_long.loc[stable_long["asset"] == asset].copy()
        asset_review = review.loc[review["asset"] == asset].copy()
        run_records = []
        for run_id, run in asset_review.groupby("flagged_run_id", sort=False):
            peak_index = run["abs_peg_deviation"].idxmax()
            peak = run.loc[peak_index]
            run_records.append(
                {
                    "run_id": str(run_id),
                    "start_utc": pd.Timestamp(run["timestamp_utc"].min()).isoformat(),
                    "end_utc": pd.Timestamp(run["timestamp_utc"].max()).isoformat(),
                    "duration_hours": int(len(run)),
                    "peak_timestamp_utc": pd.Timestamp(
                        peak["timestamp_utc"]
                    ).isoformat(),
                    "peak_price_usd": float(peak["price_usd"]),
                    "peak_peg_deviation": float(peak["peg_deviation"]),
                    "peak_absolute_peg_deviation": float(
                        peak["abs_peg_deviation"]
                    ),
                }
            )
        run_records.sort(
            key=lambda item: item["peak_absolute_peg_deviation"], reverse=True
        )

        annual_records = []
        annual = observations.assign(
            year=pd.to_datetime(observations["timestamp_utc"], utc=True).dt.year
        )
        flagged_by_year = (
            asset_review.assign(
                year=pd.to_datetime(asset_review["timestamp_utc"], utc=True).dt.year
            )
            .groupby("year")
            .size()
            .to_dict()
        )
        for year, sample in annual.groupby("year", sort=True):
            annual_records.append(
                {
                    "year": int(year),
                    "observation_count": int(len(sample)),
                    "mean_peg_deviation": float(sample["peg_deviation"].mean()),
                    "minimum_peg_deviation": float(sample["peg_deviation"].min()),
                    "maximum_peg_deviation": float(sample["peg_deviation"].max()),
                    "mean_absolute_peg_deviation": float(
                        sample["abs_peg_deviation"].mean()
                    ),
                    "maximum_absolute_peg_deviation": float(
                        sample["abs_peg_deviation"].max()
                    ),
                    "count_abs_deviation_above_0_01": int(
                        (sample["abs_peg_deviation"] > 0.01).sum()
                    ),
                    "count_abs_deviation_above_0_02": int(
                        (sample["abs_peg_deviation"] > 0.02).sum()
                    ),
                    "count_abs_deviation_above_0_05": int(
                        (sample["abs_peg_deviation"] > 0.05).sum()
                    ),
                    "flagged_review_observations": int(flagged_by_year.get(year, 0)),
                }
            )

        run_lengths = [record["duration_hours"] for record in run_records]
        result["by_asset"][asset] = {
            "top_ten_positive_peg_deviations": [
                _timestamp_record(row)
                for _, row in observations.nlargest(10, "peg_deviation").iterrows()
            ],
            "top_ten_negative_peg_deviations": [
                _timestamp_record(row)
                for _, row in observations.nsmallest(10, "peg_deviation").iterrows()
            ],
            "peg_deviation_quantiles": {
                str(probability): float(observations["peg_deviation"].quantile(probability))
                for probability in quantile_probabilities
            },
            "absolute_peg_deviation_quantiles": {
                str(probability): float(
                    observations["abs_peg_deviation"].quantile(probability)
                )
                for probability in quantile_probabilities
            },
            "absolute_deviation_threshold_counts": {
                "above_0_01": int((observations["abs_peg_deviation"] > 0.01).sum()),
                "above_0_02": int((observations["abs_peg_deviation"] > 0.02).sum()),
                "above_0_05": int((observations["abs_peg_deviation"] > 0.05).sum()),
            },
            "flagged_observation_count": int(len(asset_review)),
            "flagged_run_count": int(len(run_records)),
            "isolated_single_hour_run_count": int(sum(length == 1 for length in run_lengths)),
            "persistent_multi_hour_run_count": int(sum(length > 1 for length in run_lengths)),
            "maximum_flagged_run_length_hours": int(max(run_lengths, default=0)),
            "largest_deviation_runs": run_records[:10],
            "annual_summaries": annual_records,
        }

    indexed = panel.set_index("timestamp_utc")
    flagged_timestamps = pd.DatetimeIndex(review["timestamp_utc"].unique())
    flagged_sample = indexed.loc[indexed.index.intersection(flagged_timestamps)]
    full_correlation = float(
        indexed[["dai_peg_deviation", "usdc_peg_deviation"]].corr().iloc[0, 1]
    )
    flagged_correlation = (
        float(
            flagged_sample[["dai_peg_deviation", "usdc_peg_deviation"]]
            .corr()
            .iloc[0, 1]
        )
        if len(flagged_sample) >= 2
        else None
    )
    sign_concordance = (
        float(
            (
                np.sign(flagged_sample["dai_peg_deviation"])
                == np.sign(flagged_sample["usdc_peg_deviation"])
            ).mean()
        )
        if len(flagged_sample)
        else None
    )
    both_abs_count = int(
        (
            (indexed["dai_abs_peg_deviation"] > 0.02)
            & (indexed["usdc_abs_peg_deviation"] > 0.02)
        ).sum()
    )
    result["stablecoin_comovement"] = {
        "full_sample_peg_deviation_correlation": full_correlation,
        "flagged_timestamp_peg_deviation_correlation": flagged_correlation,
        "flagged_timestamp_sign_concordance_share": sign_concordance,
        "flagged_unique_timestamp_count": int(len(flagged_sample)),
        "both_stablecoins_abs_deviation_above_0_02_count": both_abs_count,
    }

    crypto_thresholds = {
        "ETH": float(indexed["eth_log_return"].abs().quantile(0.99)),
        "WBTC": float(indexed["wbtc_log_return"].abs().quantile(0.99)),
    }
    coincidence: dict[str, Any] = {
        "definition": (
            "A large crypto move is an absolute hourly log return at or above "
            "that series' full-sample 99th percentile."
        ),
        "absolute_log_return_thresholds": crypto_thresholds,
        "by_stablecoin": {},
    }
    for asset in ("DAI", "USDC"):
        timestamps = pd.DatetimeIndex(
            review.loc[review["asset"] == asset, "timestamp_utc"].unique()
        )
        sample = indexed.loc[indexed.index.intersection(timestamps)]
        eth_large = sample["eth_log_return"].abs() >= crypto_thresholds["ETH"]
        wbtc_large = sample["wbtc_log_return"].abs() >= crypto_thresholds["WBTC"]
        coincidence["by_stablecoin"][asset] = {
            "flagged_unique_timestamp_count": int(len(sample)),
            "coincident_large_eth_move_count": int(eth_large.sum()),
            "coincident_large_wbtc_move_count": int(wbtc_large.sum()),
            "coincident_large_either_crypto_move_count": int(
                (eth_large | wbtc_large).sum()
            ),
            "coincident_large_either_crypto_move_share": (
                float((eth_large | wbtc_large).mean()) if len(sample) else None
            ),
        }
    result["crypto_move_coincidence"] = coincidence
    return result


def validate_processed_panel(
    processed_path: Path,
    raw_path: Path,
    start: pd.Timestamp = DEFAULT_START,
    end_exclusive: pd.Timestamp = DEFAULT_END_EXCLUSIVE,
) -> tuple[dict[str, Any], list[str]]:
    """Validate the written panel against raw values and all formulas."""
    processed = pd.read_csv(processed_path, float_precision="round_trip")
    failures = []
    missing_columns = sorted(set(PROCESSED_COLUMNS) - set(processed.columns))
    unexpected_columns = sorted(set(processed.columns) - set(PROCESSED_COLUMNS))
    if missing_columns:
        failures.append(f"missing processed columns: {missing_columns}")
    if unexpected_columns:
        failures.append(f"unexpected processed columns: {unexpected_columns}")
    if missing_columns:
        return {
            "validation_passed": False,
            "failures": failures,
            "missing_columns": missing_columns,
            "unexpected_columns": unexpected_columns,
        }, failures

    timestamps, naive, non_utc, invalid = parse_strict_utc(processed["timestamp_utc"])
    processed["timestamp_utc"] = timestamps
    expected_index = expected_hourly_index(start, end_exclusive)
    observed_index = pd.DatetimeIndex(timestamps)
    row_count_matches = len(processed) == len(expected_index)
    strictly_increasing = observed_index.is_monotonic_increasing
    duplicate_count = int(observed_index.duplicated().sum())
    missing_timestamps = expected_index.difference(observed_index)
    unexpected_timestamps = observed_index.difference(expected_index)

    for label, condition in (
        ("processed row count", row_count_matches),
        ("strictly increasing timestamps", strictly_increasing),
        ("no duplicate timestamps", duplicate_count == 0),
        ("no missing timestamps", len(missing_timestamps) == 0),
        ("no unexpected timestamps", len(unexpected_timestamps) == 0),
        ("timestamps declare UTC", naive == 0 and non_utc == 0 and invalid == 0),
    ):
        if not condition:
            failures.append(label)

    raw = _read_raw(raw_path)
    raw_prices = raw.pivot(
        index="timestamp_utc", columns="asset", values="price_usd"
    ).sort_index()
    raw_sources = raw.pivot(
        index="timestamp_utc", columns="asset", values="source"
    ).sort_index()

    numeric_columns = [
        column
        for column in PROCESSED_COLUMNS
        if column not in {"timestamp_utc", "dai_source", "usdc_source"}
    ]
    for column in numeric_columns:
        processed[column] = pd.to_numeric(processed[column], errors="coerce")
    non_numeric_counts = {
        column: int(processed[column].isna().sum())
        for column in (
            "eth_price_usd",
            "wbtc_price_usd",
            "dai_price_usd",
            "usdc_price_usd",
            "dai_peg_deviation",
            "usdc_peg_deviation",
            "dai_abs_peg_deviation",
            "usdc_abs_peg_deviation",
            "dai_below_peg",
            "usdc_below_peg",
        )
    }
    if any(non_numeric_counts.values()):
        failures.append("required numeric columns contain missing or non-numeric values")

    exact_price_matches = {}
    return_formula_max_absolute_error = {}
    return_formula_matches = {}
    first_return_only_missing = {}
    for asset, price_column in ASSET_PRICE_COLUMNS.items():
        expected_prices = raw_prices[asset].to_numpy(dtype=float)
        observed_prices = processed[price_column].to_numpy(dtype=float)
        price_match = bool(np.array_equal(observed_prices, expected_prices))
        exact_price_matches[asset] = price_match
        if not price_match:
            failures.append(f"{asset} processed prices differ from raw values")

        return_column = ASSET_RETURN_COLUMNS[asset]
        expected_returns = (
            np.log(processed[price_column]) - np.log(processed[price_column].shift(1))
        )
        observed_returns = processed[return_column]
        difference = (observed_returns - expected_returns).abs().dropna()
        maximum_error = float(difference.max()) if not difference.empty else 0.0
        return_formula_max_absolute_error[asset] = maximum_error
        formula_match = bool(
            np.allclose(
                observed_returns.to_numpy(dtype=float),
                expected_returns.to_numpy(dtype=float),
                rtol=0.0,
                atol=1e-15,
                equal_nan=True,
            )
        )
        return_formula_matches[asset] = formula_match
        if not formula_match:
            failures.append(f"{asset} log-return formula mismatch")
        missing_mask = observed_returns.isna().to_numpy()
        correct_missing = bool(
            missing_mask.sum() == 1 and missing_mask[0] and not missing_mask[1:].any()
        )
        first_return_only_missing[asset] = correct_missing
        if not correct_missing:
            failures.append(f"{asset} return missingness is not limited to row one")

    peg_formula_matches = {}
    for stablecoin in ("dai", "usdc"):
        price = processed[f"{stablecoin}_price_usd"]
        peg = processed[f"{stablecoin}_peg_deviation"]
        absolute = processed[f"{stablecoin}_abs_peg_deviation"]
        below = processed[f"{stablecoin}_below_peg"]
        checks = {
            "peg_deviation": bool(np.array_equal(peg.to_numpy(), (price - 1.0).to_numpy())),
            "absolute_peg_deviation": bool(
                np.array_equal(absolute.to_numpy(), (price - 1.0).abs().to_numpy())
            ),
            "below_peg": bool(
                np.array_equal(below.to_numpy(), (price < 1.0).astype(int).to_numpy())
            ),
        }
        peg_formula_matches[stablecoin.upper()] = checks
        if not all(checks.values()):
            failures.append(f"{stablecoin.upper()} peg-derived formula mismatch")

    source_matches = {}
    for stablecoin in ("DAI", "USDC"):
        column = f"{stablecoin.lower()}_source"
        matches = bool(
            np.array_equal(
                processed[column].astype(str).to_numpy(),
                raw_sources[stablecoin].astype(str).to_numpy(),
            )
        )
        source_matches[stablecoin] = matches
        if not matches:
            failures.append(f"{stablecoin} source provenance differs from raw values")

    numeric_values = processed[numeric_columns].to_numpy(dtype=float)
    infinity_count = int(np.isinf(numeric_values).sum())
    if infinity_count:
        failures.append(f"processed panel contains {infinity_count} infinities")

    indicator_values_valid = {
        column: set(processed[column].dropna().astype(int).unique()).issubset({0, 1})
        for column in ("dai_below_peg", "usdc_below_peg")
    }
    if not all(indicator_values_valid.values()):
        failures.append("below-peg indicator values are not binary")

    report = {
        "validation_passed": not failures,
        "failures": failures,
        "processed_file": str(processed_path),
        "raw_file": str(raw_path),
        "dimensions": {"rows": int(len(processed)), "columns": int(len(processed.columns))},
        "expected_row_count": int(len(expected_index)),
        "expected_columns": list(PROCESSED_COLUMNS),
        "observed_dtypes": {column: str(dtype) for column, dtype in processed.dtypes.items()},
        "timestamp_checks": {
            "strictly_increasing": bool(strictly_increasing),
            "duplicate_count": duplicate_count,
            "missing_hour_count": int(len(missing_timestamps)),
            "unexpected_timestamp_count": int(len(unexpected_timestamps)),
            "naive_timestamp_count": int(naive),
            "non_utc_timestamp_count": int(non_utc),
            "invalid_timestamp_count": int(invalid),
            "minimum_timestamp_utc": observed_index.min().isoformat(),
            "maximum_timestamp_utc": observed_index.max().isoformat(),
        },
        "exact_raw_price_matches": exact_price_matches,
        "return_formula_matches": return_formula_matches,
        "return_formula_max_absolute_error": return_formula_max_absolute_error,
        "only_first_return_missing": first_return_only_missing,
        "peg_formula_matches": peg_formula_matches,
        "source_matches_raw": source_matches,
        "source_distributions": {
            "DAI": processed["dai_source"].value_counts().to_dict(),
            "USDC": processed["usdc_source"].value_counts().to_dict(),
        },
        "indicator_values_valid": indicator_values_valid,
        "infinity_count": infinity_count,
        "numeric_missing_counts": {
            column: int(processed[column].isna().sum()) for column in numeric_columns
        },
    }
    return report, failures


def write_csv_atomically(frame: pd.DataFrame, path: Path) -> None:
    """Write a deterministic CSV without exposing a partial output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(
        temporary,
        index=False,
        date_format="%Y-%m-%dT%H:%M:%SZ",
    )
    temporary.replace(path)


def update_manifest(
    manifest_path: Path,
    raw_path: Path,
    processed_path: Path,
    processed_checksum: str,
    script_path: Path,
    script_checksum: str,
    created_at: datetime,
    validation_path: Path,
    metadata_path: Path,
    review_path: Path,
    review_checksum: str,
    review_row_count: int,
) -> int:
    """Attach processed-data provenance to the four existing Dune records."""
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for column in MANIFEST_PROCESSING_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)

    transformation = (
        "Exact long-to-wide pivot; hourly log returns; price-minus-one peg "
        "deviations; absolute peg deviations; below-peg indicators; no filling, "
        "clipping, smoothing, winsorisation or observation removal."
    )
    updated = 0
    for row in rows:
        if row.get("raw_file_path") != str(raw_path):
            continue
        row.update(
            {
                "processed_file_path": str(processed_path),
                "processed_file_size_bytes": str(processed_path.stat().st_size),
                "processed_sha256": processed_checksum,
                "processing_script_path": str(script_path),
                "processing_script_sha256": script_checksum,
                "processing_timestamp_utc": created_at.isoformat(),
                "processed_row_count": "27024",
                "processed_column_count": str(len(PROCESSED_COLUMNS)),
                "processed_validation_status": "passed",
                "processed_validation_report_path": str(validation_path),
                "processing_metadata_path": str(metadata_path),
                "stablecoin_review_path": str(review_path),
                "stablecoin_review_row_count": str(review_row_count),
                "stablecoin_review_sha256": review_checksum,
                "processed_transformation": transformation,
            }
        )
        updated += 1
    if updated != 4:
        raise ProcessingError(
            f"Expected to update four Dune manifest records, updated {updated}."
        )

    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(manifest_path)
    return updated


def parse_args() -> argparse.Namespace:
    """Parse deterministic local-processing arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--raw-validation-report",
        type=Path,
        default=DEFAULT_RAW_VALIDATION,
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
    )
    parser.add_argument(
        "--provenance-directory",
        type=Path,
        default=DEFAULT_PROVENANCE_DIRECTORY,
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> int:
    """Run the complete local Phase 1A processing workflow."""
    args = parse_args()
    output_directory = args.output_directory
    provenance_directory = args.provenance_directory
    processed_path = output_directory / "dune_hourly_market_prices_processed.csv"
    review_path = output_directory / "stablecoin_extreme_review.csv"
    metadata_path = (
        provenance_directory / "dune_hourly_market_prices_processing_metadata.json"
    )
    validation_path = (
        provenance_directory / "dune_hourly_market_prices_processed_validation.json"
    )
    script_path = Path(__file__).resolve()

    raw, integrity = validate_raw_integrity(
        args.input,
        args.raw_validation_report,
    )
    raw_checksum_before = integrity["raw_sha256"]
    panel = build_processed_panel(raw)
    review = build_stablecoin_extreme_review(panel)
    descriptive_review = build_descriptive_review(panel, review)

    write_csv_atomically(panel, processed_path)
    write_csv_atomically(review, review_path)
    validation_report, validation_failures = validate_processed_panel(
        processed_path,
        args.input,
    )
    processed_checksum = sha256_file(processed_path)
    review_checksum = sha256_file(review_path)
    script_checksum = sha256_file(script_path)
    created_at = datetime.now(timezone.utc)
    validation_report.update(
        {
            "raw_file_sha256": raw_checksum_before,
            "processed_file_sha256": processed_checksum,
            "processing_script_sha256": script_checksum,
            "creation_timestamp_utc": created_at.isoformat(),
        }
    )
    write_json(validation_path, validation_report)
    if validation_failures:
        raise ProcessingError(
            "Processed validation failed: " + "; ".join(validation_failures)
        )

    raw_checksum_after = sha256_file(args.input)
    if raw_checksum_after != raw_checksum_before:
        raise ProcessingError("Raw-file checksum changed during local processing.")

    metadata = {
        "phase": "Phase 1A processed hourly market prices",
        "creation_timestamp_utc": created_at.isoformat(),
        "network_access": False,
        "input": {
            "raw_file_path": str(args.input),
            "raw_validation_report_path": str(args.raw_validation_report),
            "raw_sha256_before": raw_checksum_before,
            "raw_sha256_after": raw_checksum_after,
            "dimensions": integrity["input_dimensions"],
            "per_asset_row_counts": integrity["per_asset_row_counts"],
            "unavailable_volume_count": integrity["unavailable_volume_count"],
            "integrity_checks": integrity["checks"],
        },
        "output": {
            "processed_panel_path": str(processed_path),
            "processed_panel_sha256": processed_checksum,
            "processed_panel_dimensions": {
                "rows": int(len(panel)),
                "columns": int(len(panel.columns)),
            },
            "stablecoin_review_path": str(review_path),
            "stablecoin_review_sha256": review_checksum,
            "stablecoin_review_row_count": int(len(review)),
            "processed_validation_report_path": str(validation_path),
        },
        "processing_code": {
            "script_path": str(script_path.relative_to(REPOSITORY_ROOT)),
            "script_sha256": script_checksum,
        },
        "coverage": {
            "start_utc": DEFAULT_START.isoformat(),
            "end_exclusive_utc": DEFAULT_END_EXCLUSIVE.isoformat(),
            "last_observation_utc": (
                DEFAULT_END_EXCLUSIVE - pd.Timedelta(hours=1)
            ).isoformat(),
            "frequency": "1h",
        },
        "transformations": {
            "pivot": "Exact asset-hour long-to-wide pivot without aggregation.",
            "log_return": (
                "log(current price) minus log(previous-hour price); the first "
                "observation remains missing."
            ),
            "peg_deviation": "Stablecoin price minus 1.",
            "absolute_peg_deviation": "Absolute value of price minus 1.",
            "below_peg": "One where price is below 1; zero otherwise.",
            "rolling_median": (
                "Centred time-based 24-hour rolling median with min_periods=1; "
                "boundary windows use available observations only."
            ),
            "prohibited_transformations": (
                "No winsorisation, clipping, smoothing, interpolation, forward "
                "filling, deduplication, imputation or observation removal."
            ),
        },
        "stablecoin_descriptive_review": descriptive_review,
        "validation_status": "passed",
    }
    write_json(metadata_path, metadata)
    updated_records = update_manifest(
        args.manifest,
        args.input,
        processed_path,
        processed_checksum,
        script_path.relative_to(REPOSITORY_ROOT),
        script_checksum,
        created_at,
        validation_path,
        metadata_path,
        review_path,
        review_checksum,
        len(review),
    )

    print(f"Raw integrity passed: {raw_checksum_before}")
    print(
        f"Processed panel: {processed_path} ({len(panel)} rows, "
        f"{len(panel.columns)} columns, SHA-256 {processed_checksum})"
    )
    print(f"Stablecoin review: {review_path} ({len(review)} rows)")
    print(f"Processed validation: passed; manifest records updated: {updated_records}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProcessingError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
