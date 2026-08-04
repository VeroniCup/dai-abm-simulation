"""Build the compact held-out market/gas runtime derivative.

This maintenance workflow is intentionally local and deterministic. It reads
the frozen processed source only when that optional provenance source is
available, verifies its registered checksum, and copies the exact CSV field
strings required by the two held-out validation windows. It performs no
acquisition, interpolation, resampling, rounding or scientific calculation.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import tempfile
from typing import Final


REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
SOURCE_PATH: Final = (
    REPOSITORY_ROOT
    / "data/market/processed/combined/hourly_market_gas_panel.csv"
)
SOURCE_SHA256: Final = (
    "86ed2ac5a5d364cc57e8b41e137ef369a0fce7a393d386b4b38fc1ebd1be0545"
)
OUTPUT_PATH: Final = (
    REPOSITORY_ROOT
    / "data/model_inputs/validation/final_validation_market_gas_paths.csv"
)
EQUIVALENCE_REPORT_PATH: Final = (
    REPOSITORY_ROOT
    / "outputs/maintenance/runtime_portability_migration/full_compact_equivalence.json"
)
TRANSFORMATION_ID: Final = "final_validation_held_out_exact_columns_v1"
COLUMNS: Final = (
    "timestamp_utc",
    "eth_log_return",
    "wbtc_log_return",
    "dai_price_usd",
    "usdc_price_usd",
    "usdc_log_return",
    "median_effective_gas_price_gwei",
)
WINDOWS: Final = (
    (
        datetime(2022, 11, 1, tzinfo=timezone.utc),
        datetime(2022, 11, 21, tzinfo=timezone.utc),
        480,
    ),
    (
        datetime(2023, 3, 6, tzinfo=timezone.utc),
        datetime(2023, 3, 20, tzinfo=timezone.utc),
        336,
    ),
)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of *path*."""
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Runtime derivative timestamps must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def selected_rows(source: Path = SOURCE_PATH) -> list[dict[str, str]]:
    """Return exact source strings for the two registered held-out windows."""
    if not source.is_file():
        raise FileNotFoundError(f"Optional processed source is unavailable: {source}")
    observed_sha = sha256_file(source)
    if observed_sha != SOURCE_SHA256:
        raise ValueError(
            "Processed market/gas source checksum differs: "
            f"expected {SOURCE_SHA256}, observed {observed_sha}."
        )
    rows: list[dict[str, str]] = []
    window_counts = [0] * len(WINDOWS)
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or any(
            column not in reader.fieldnames for column in COLUMNS
        ):
            raise ValueError("Processed market/gas source schema differs.")
        for source_row in reader:
            timestamp = _timestamp(source_row["timestamp_utc"])
            for index, (start, end, _) in enumerate(WINDOWS):
                if start <= timestamp < end:
                    rows.append({column: source_row[column] for column in COLUMNS})
                    window_counts[index] += 1
                    break
    expected_counts = [expected for _, _, expected in WINDOWS]
    if window_counts != expected_counts:
        raise ValueError(
            "Held-out source coverage differs: "
            f"expected {expected_counts}, observed {window_counts}."
        )
    timestamps = [_timestamp(row["timestamp_utc"]) for row in rows]
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise ValueError("Held-out runtime rows are not uniquely chronological.")
    return rows


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    """Write *payload* durably and replace *path* atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def build(
    source: Path = SOURCE_PATH,
    destination: Path = OUTPUT_PATH,
) -> dict[str, object]:
    """Build and return deterministic derivative metadata."""
    rows = selected_rows(source)
    payload = _csv_bytes(rows)
    atomic_write(destination, payload)
    return {
        "transformation_id": TRANSFORMATION_ID,
        "path": destination.relative_to(REPOSITORY_ROOT).as_posix(),
        "sha256": sha256(payload).hexdigest(),
        "bytes": len(payload),
        "rows": len(rows),
        "columns": list(COLUMNS),
        "minimum_timestamp": rows[0]["timestamp_utc"],
        "maximum_timestamp": rows[-1]["timestamp_utc"],
        "source_path": source.relative_to(REPOSITORY_ROOT).as_posix(),
        "source_sha256": SOURCE_SHA256,
        "network_calls": 0,
    }


def validate_equivalence(
    source: Path = SOURCE_PATH,
    derivative: Path = OUTPUT_PATH,
) -> dict[str, object]:
    """Prove exact equality of every runtime-consumed full/compact value."""
    import numpy as np
    import pandas as pd

    from dai_sim.inputs.multicollateral import (
        _csv_bytes as market_pool_bytes,
        build_final_market_pool,
        load_final_collateral_registry,
        load_integrated_multicollateral_profile,
    )
    from dai_sim.validation import final_validation

    exact_source_rows = selected_rows(source)
    with derivative.open("r", encoding="utf-8", newline="") as handle:
        compact_rows = list(csv.DictReader(handle))
    exact_strings_equal = exact_source_rows == compact_rows
    if not exact_strings_equal:
        raise ValueError("Compact held-out CSV strings differ from the source.")

    full = pd.read_csv(source, usecols=COLUMNS)
    full["timestamp_utc"] = pd.to_datetime(full["timestamp_utc"], utc=True)
    mask = pd.Series(False, index=full.index)
    for start, end, _ in WINDOWS:
        mask |= (full["timestamp_utc"] >= start) & (full["timestamp_utc"] < end)
    full = full.loc[mask, COLUMNS].reset_index(drop=True)
    compact = pd.read_csv(derivative, usecols=COLUMNS)
    compact["timestamp_utc"] = pd.to_datetime(compact["timestamp_utc"], utc=True)
    if not full.equals(compact):
        raise ValueError("Parsed compact held-out values differ from the source.")
    missingness_equal = np.array_equal(full.isna().to_numpy(), compact.isna().to_numpy())
    if not missingness_equal:
        raise ValueError("Compact held-out missingness differs from the source.")

    downstream_equal = True
    maximum_numeric_difference = 0.0
    stage_rows: dict[str, int] = {}
    for stage, (start, end, expected) in zip(("ftx", "usdc_svb"), WINDOWS):
        full_stage = full.loc[
            (full["timestamp_utc"] >= start) & (full["timestamp_utc"] < end)
        ].reset_index(drop=True)
        compact_stage = final_validation._historical_window(stage)
        compact_stage = compact_stage.loc[:, COLUMNS]
        compact_stage["timestamp_utc"] = pd.to_datetime(
            compact_stage["timestamp_utc"], utc=True
        )
        if len(full_stage) != expected or not full_stage.equals(compact_stage):
            downstream_equal = False
        for column in COLUMNS[1:]:
            left = pd.to_numeric(full_stage[column], errors="raise").to_numpy()
            right = pd.to_numeric(compact_stage[column], errors="raise").to_numpy()
            if not np.array_equal(left, right, equal_nan=True):
                downstream_equal = False
            if left.size:
                finite = np.isfinite(left) & np.isfinite(right)
                if finite.any():
                    maximum_numeric_difference = max(
                        maximum_numeric_difference,
                        float(np.max(np.abs(left[finite] - right[finite]))),
                    )
        full_paths = final_validation._historical_paths(full_stage)
        compact_paths = final_validation._historical_paths(compact_stage)
        for family in full_paths:
            if not np.array_equal(
                full_paths[family], compact_paths[family], equal_nan=True
            ):
                downstream_equal = False
        stage_rows[stage] = len(compact_stage)
    if not downstream_equal or maximum_numeric_difference != 0.0:
        raise ValueError("Downstream held-out runtime arrays differ.")

    rebuilt_pool = build_final_market_pool()
    rebuilt_pool_sha = sha256(market_pool_bytes(rebuilt_pool)).hexdigest()
    expected_pool_sha = (
        "e97570b94b2140f9a6dc6436b386ba0ea9e91d9de73b755cc38d8e971d91ed2e"
    )
    if rebuilt_pool_sha != expected_pool_sha:
        raise ValueError("Existing tracked market-block pool is not reproducible.")

    collateral = load_final_collateral_registry()
    profile = load_integrated_multicollateral_profile()
    return {
        "schema_version": 1,
        "classification": "full_compact_exact_equivalence",
        "exact_csv_strings_equal": exact_strings_equal,
        "parsed_values_equal": True,
        "missingness_masks_equal": missingness_equal,
        "downstream_arrays_equal": downstream_equal,
        "maximum_numeric_difference": maximum_numeric_difference,
        "scientific_value_differences": 0,
        "validation_rows": stage_rows,
        "collateral_family_order": list(collateral.family_order),
        "profile_identifier": profile.identifier,
        "profile_checksum": profile.checksum,
        "market_block_pool_rows": len(rebuilt_pool),
        "market_block_pool_sha256": rebuilt_pool_sha,
        "compact_derivative_rows": len(compact),
        "compact_derivative_sha256": sha256_file(derivative),
        "historical_source_sha256": sha256_file(source),
        "network_calls": 0,
    }


def parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--source", type=Path, default=SOURCE_PATH)
    result.add_argument("--output", type=Path, default=OUTPUT_PATH)
    result.add_argument(
        "--equivalence-report",
        type=Path,
        default=EQUIVALENCE_REPORT_PATH,
    )
    return result


def main() -> None:
    """Build the derivative and print compact metadata."""
    import json

    args = parser().parse_args()
    built = build(args.source, args.output)
    equivalence = validate_equivalence(args.source, args.output)
    atomic_write(
        args.equivalence_report,
        (json.dumps(equivalence, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    print(
        json.dumps(
            {"derivative": built, "equivalence": equivalence},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
