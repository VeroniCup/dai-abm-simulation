"""Validate the untouched Dune hourly market-price CSV."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import runpy

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
REPOSITORY_ROOT = runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = (
    "timestamp_utc",
    "asset",
    "dune_instrument",
    "price_usd",
    "blockchain",
    "contract_address",
    "source",
    "volume_usd",
)
EXPECTED = {
    "ETH": {
        "dune_instrument": "WETH",
        "contract_address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    },
    "WBTC": {
        "dune_instrument": "WBTC",
        "contract_address": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",
    },
    "DAI": {
        "dune_instrument": "DAI",
        "contract_address": "0x6b175474e89094c44da98b954eedeac495271d0f",
    },
    "USDC": {
        "dune_instrument": "USDC",
        "contract_address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    },
}
ALLOWED_SOURCES = {"coinpaprika", "dex.trades"}
DEFAULT_START = pd.Timestamp("2021-06-01 00:00:00", tz="UTC")
DEFAULT_END = pd.Timestamp("2024-07-01 00:00:00", tz="UTC")


def maximum_consecutive_missing_hours(
    expected_hours: pd.DatetimeIndex,
    observed_hours: pd.DatetimeIndex,
) -> int:
    """Return the longest run of absent hourly timestamps."""
    observed = set(observed_hours)
    longest = 0
    current = 0
    for timestamp in expected_hours:
        if timestamp in observed:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def parse_strict_utc(values: pd.Series) -> tuple[pd.Series, int, int, int]:
    """Parse timestamps while counting naive, non-UTC and invalid values."""
    parsed: list[Any] = []
    naive_count = 0
    non_utc_count = 0
    invalid_count = 0
    for value in values:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError):
            parsed.append(pd.NaT)
            invalid_count += 1
            continue
        if pd.isna(timestamp):
            parsed.append(pd.NaT)
            invalid_count += 1
        elif timestamp.tzinfo is None:
            parsed.append(timestamp.tz_localize("UTC"))
            naive_count += 1
        else:
            if timestamp.utcoffset().total_seconds() != 0:
                non_utc_count += 1
            parsed.append(timestamp.tz_convert("UTC"))
    return (
        pd.Series(parsed, index=values.index, dtype="datetime64[ns, UTC]"),
        naive_count,
        non_utc_count,
        invalid_count,
    )


def validate_prices(
    path: Path,
    requested_start: pd.Timestamp = DEFAULT_START,
    requested_end: pd.Timestamp = DEFAULT_END,
) -> tuple[dict[str, Any], list[str]]:
    """Validate raw data and return a serialisable report and failures."""
    frame = pd.read_csv(path, dtype={"contract_address": "string"})
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing_columns:
        return {"missing_required_columns": missing_columns}, [
            f"missing required columns: {missing_columns}"
        ]

    failures: list[str] = []
    timestamps, naive_count, non_utc_count, invalid_count = parse_strict_utc(
        frame["timestamp_utc"]
    )
    frame = frame.assign(_timestamp=timestamps)
    frame["contract_address"] = frame["contract_address"].str.lower()
    frame["price_usd"] = pd.to_numeric(frame["price_usd"], errors="coerce")
    volume_text = frame["volume_usd"].astype("string").str.strip().str.lower()
    frame["_volume_missing"] = frame["volume_usd"].isna() | volume_text.isin(
        {"", "<nil>", "nil", "null", "none"}
    )

    if invalid_count:
        failures.append(f"{invalid_count} timestamps could not be parsed")
    if naive_count:
        failures.append(f"{naive_count} timestamps do not declare a timezone")
    if non_utc_count:
        failures.append(f"{non_utc_count} timestamps are not expressed in UTC")

    valid_timestamps = frame["_timestamp"].dropna()
    out_of_bounds = int(
        ((valid_timestamps < requested_start) | (valid_timestamps >= requested_end)).sum()
    )
    if out_of_bounds:
        failures.append(f"{out_of_bounds} rows are outside the requested interval")

    actual_assets = set(frame["asset"].dropna().astype(str))
    expected_assets = set(EXPECTED)
    missing_assets = sorted(expected_assets - actual_assets)
    unexpected_assets = sorted(actual_assets - expected_assets)
    if missing_assets:
        failures.append(f"missing assets: {missing_assets}")
    if unexpected_assets:
        failures.append(f"unexpected assets: {unexpected_assets}")

    null_identifier_counts = {
        column: int(frame[column].isna().sum())
        for column in (
            "asset",
            "dune_instrument",
            "blockchain",
            "contract_address",
            "source",
        )
    }
    for column, count in null_identifier_counts.items():
        if count:
            failures.append(f"{count} rows have null {column}")

    duplicate_count = int(
        frame.duplicated(subset=["asset", "_timestamp"], keep=False).sum()
    )
    if duplicate_count:
        failures.append(f"{duplicate_count} rows participate in duplicate asset-hours")

    null_price_count = int(frame["price_usd"].isna().sum())
    non_positive_price_count = int((frame["price_usd"] <= 0).sum())
    if null_price_count:
        failures.append(f"{null_price_count} prices are null or non-numeric")
    if non_positive_price_count:
        failures.append(f"{non_positive_price_count} prices are non-positive")

    unexpected_blockchains = sorted(
        set(frame["blockchain"].dropna().astype(str)) - {"ethereum"}
    )
    if unexpected_blockchains:
        failures.append(f"unexpected blockchain values: {unexpected_blockchains}")

    expected_hours = pd.date_range(
        requested_start,
        requested_end - pd.Timedelta(hours=1),
        freq="1h",
    )
    by_asset: dict[str, Any] = {}
    for asset, identifiers in EXPECTED.items():
        subset = frame.loc[frame["asset"] == asset]
        duplicate_asset_hour_count = int(
            subset.duplicated(subset=["_timestamp"], keep=False).sum()
        )
        observed = pd.DatetimeIndex(subset["_timestamp"].dropna().unique()).sort_values()
        missing = expected_hours.difference(observed)
        instruments = sorted(set(subset["dune_instrument"].dropna().astype(str)))
        addresses = sorted(set(subset["contract_address"].dropna().astype(str)))
        unexpected_addresses = sorted(
            set(addresses) - {identifiers["contract_address"]}
        )
        unexpected_asset_blockchains = sorted(
            set(subset["blockchain"].dropna().astype(str)) - {"ethereum"}
        )
        if instruments != [identifiers["dune_instrument"]]:
            failures.append(f"{asset} has unexpected Dune instruments: {instruments}")
        if addresses != [identifiers["contract_address"]]:
            failures.append(f"{asset} has unexpected contract addresses: {addresses}")
        if len(missing):
            failures.append(f"{asset} is missing {len(missing)} requested hours")
        starts_at_boundary = len(observed) > 0 and observed.min() == requested_start
        ends_at_boundary = (
            len(observed) > 0
            and observed.max() == requested_end - pd.Timedelta(hours=1)
        )
        if not starts_at_boundary:
            failures.append(f"{asset} does not start at the requested boundary")
        if not ends_at_boundary:
            failures.append(f"{asset} does not end at the requested boundary")

        prices = subset["price_usd"]
        source_order = subset.loc[
            subset["_timestamp"].notna(), ["_timestamp", "source"]
        ].sort_values("_timestamp")
        previous_source = source_order["source"].shift()
        source_change_mask = (
            source_order["source"].notna()
            & previous_source.notna()
            & source_order["source"].ne(previous_source)
        )
        source_change_dates = [
            timestamp.isoformat()
            for timestamp in source_order.loc[source_change_mask, "_timestamp"]
        ]
        stablecoin_warning = None
        if asset in {"DAI", "USDC"} and prices.notna().any():
            minimum = float(prices.min())
            maximum = float(prices.max())
            if minimum < 0.95 or maximum > 1.05:
                stablecoin_warning = (
                    "Observed price leaves the 0.95–1.05 diagnostic band; "
                    "investigate rather than imputing or deleting it."
                )
        by_asset[asset] = {
            "row_count": int(len(subset)),
            "expected_row_count": int(len(expected_hours)),
            "distinct_hour_count": int(len(observed)),
            "duplicate_asset_hour_count": duplicate_asset_hour_count,
            "missing_hour_count": int(len(missing)),
            "maximum_consecutive_missing_hours": maximum_consecutive_missing_hours(
                expected_hours, observed
            ),
            "minimum_timestamp_utc": None if not len(observed) else observed.min().isoformat(),
            "maximum_timestamp_utc": None if not len(observed) else observed.max().isoformat(),
            "minimum_price_usd": None if not prices.notna().any() else float(prices.min()),
            "maximum_price_usd": None if not prices.notna().any() else float(prices.max()),
            "null_price_count": int(prices.isna().sum()),
            "non_positive_price_count": int((prices <= 0).sum()),
            "source_distribution": dict(
                Counter(subset["source"].dropna().astype(str))
            ),
            "source_change_count": len(source_change_dates),
            "source_change_dates_utc": source_change_dates,
            "unexpected_contract_addresses": unexpected_addresses,
            "unexpected_blockchain_values": unexpected_asset_blockchains,
            "null_volume_count": int(subset["_volume_missing"].sum()),
            "stablecoin_price_warning": stablecoin_warning,
        }

    source_values = set(frame["source"].dropna().astype(str))
    unexpected_sources = sorted(source_values - ALLOWED_SOURCES)
    if unexpected_sources:
        failures.append(f"unexpected source values: {unexpected_sources}")

    report = {
        "file": str(path),
        "requested_start_utc": requested_start.isoformat(),
        "requested_end_exclusive_utc": requested_end.isoformat(),
        "expected_assets": sorted(expected_assets),
        "expected_hours_per_asset": len(expected_hours),
        "expected_total_rows": len(expected_hours) * len(expected_assets),
        "actual_total_rows": int(len(frame)),
        "duplicate_asset_hour_row_count": duplicate_count,
        "null_price_count": null_price_count,
        "null_volume_count": int(frame["_volume_missing"].sum()),
        "non_positive_price_count": non_positive_price_count,
        "invalid_timestamp_count": invalid_count,
        "naive_timestamp_count": naive_count,
        "non_utc_timestamp_count": non_utc_count,
        "out_of_bounds_row_count": out_of_bounds,
        "missing_assets": missing_assets,
        "unexpected_assets": unexpected_assets,
        "unexpected_blockchains": unexpected_blockchains,
        "unexpected_sources": unexpected_sources,
        "null_identifier_counts": null_identifier_counts,
        "by_asset": by_asset,
        "validation_passed": not failures,
        "failures": failures,
    }
    return report, failures


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    """Run validation without modifying raw data."""
    args = parse_args()
    report, failures = validate_prices(args.csv_path)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
