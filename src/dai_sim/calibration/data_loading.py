"""Manifest-backed loading and validation for Phase 2A inputs."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class InputSpec:
    """Expected identity and dimensions for one empirical input."""

    name: str
    path: Path
    sha256: str
    rows: int
    columns: int

    def relative_path(self) -> str:
        """Return the repository-relative path used in provenance records."""
        return self.path.relative_to(PROJECT_ROOT).as_posix()


REQUIRED_COLUMNS: dict[str, set[str]] = {
    "market": {
        "timestamp_utc",
        "eth_price_usd",
        "wbtc_price_usd",
        "dai_price_usd",
        "usdc_price_usd",
        "eth_log_return",
        "wbtc_log_return",
        "dai_log_return",
        "usdc_log_return",
        "dai_abs_peg_deviation",
        "usdc_abs_peg_deviation",
    },
    "gas": {
        "timestamp_utc",
        "median_effective_gas_price_gwei",
        "p90_effective_gas_price_gwei",
        "p99_effective_gas_price_gwei",
        "median_base_fee_gwei",
        "median_priority_fee_gwei",
        "failed_transaction_share",
        "target_normalised_block_utilisation",
        "fee_market_regime",
    },
    "combined": {
        "timestamp_utc",
        "eth_log_return",
        "wbtc_log_return",
        "dai_abs_peg_deviation",
        "median_effective_gas_price_gwei",
        "p90_effective_gas_price_gwei",
        "p99_effective_gas_price_gwei",
    },
    "liquidation_actions": {
        "record_type",
        "tx_hash",
        "clipper_contract",
        "auction_id",
        "ilk",
        "block_time",
    },
    "liquidation_transactions": {
        "tx_hash",
        "success",
        "gas_limit",
        "gas_used",
        "gas_price",
        "block_time",
    },
    "liquidation_auctions": {
        "clipper_contract",
        "auction_id",
        "ilk",
        "bark_time_utc",
        "observed_duration_seconds",
        "bark_due_dai",
        "dai_paid",
        "terminal_classification",
    },
    "liquidation_hourly": {
        "timestamp_utc",
        "ilk",
        "auctions_initiated",
        "auctions_completed",
        "debt_targeted_dai",
        "debt_repaid_dai",
        "successful_takes",
        "failed_take_attempts",
        "unique_keepers",
        "gas_used_unambiguous",
        "bad_debt_proxy_dai",
    },
    "protocol_changes": {
        "module",
        "ilk",
        "parameter",
        "effective_time_utc",
        "raw_value",
        "converted_value",
        "converted_unit",
        "state_source",
        "is_observed_call",
    },
    "protocol_intervals": {
        "module",
        "ilk",
        "parameter",
        "effective_start_utc",
        "effective_end_exclusive_utc",
        "converted_value",
    },
    "protocol_hourly": {
        "timestamp_utc",
        "ilk",
        "liquidation_ratio",
        "liquidation_penalty_rate",
        "debt_ceiling_dai",
        "minimum_debt_dai",
        "annualised_stability_fee",
        "auction_stopped",
        "ilk_active",
    },
}


def sha256_file(path: Path) -> str:
    """Calculate a file SHA-256 without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def csv_dimensions(path: Path) -> tuple[int, int]:
    """Return data-row and header-column counts for a UTF-8 CSV."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"CSV is empty: {path}") from exc
        return sum(1 for _ in reader), len(header)


def _market_and_gas_specs() -> list[InputSpec]:
    manifest_path = (
        PROJECT_ROOT / "data/provenance/data_manifest.csv"
    )
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 5:
        raise ValueError(
            "Expected five rows in the Phase 1A/1B data manifest; "
            f"found {len(rows)}."
        )
    market = rows[0]
    gas = rows[-1]
    return [
        InputSpec(
            "market",
            PROJECT_ROOT / market["processed_file_path"],
            market["processed_sha256"],
            int(market["processed_row_count"]),
            int(market["processed_column_count"]),
        ),
        InputSpec(
            "gas",
            PROJECT_ROOT / gas["processed_file_path"],
            gas["processed_sha256"],
            int(gas["processed_row_count"]),
            int(gas["processed_column_count"]),
        ),
        InputSpec(
            "combined",
            PROJECT_ROOT / gas["joined_file_path"],
            gas["joined_sha256"],
            27_024,
            66,
        ),
    ]


def _liquidation_specs() -> list[InputSpec]:
    manifest = json.loads(
        (
            PROJECT_ROOT / "data/liquidations/provenance/manifest.json"
        ).read_text(encoding="utf-8")
    )
    known = {
        "liquidation_actions_2021-06-01_2024-06-30.csv": (
            "liquidation_actions",
            7_997,
            48,
        ),
        "liquidation_transactions_2021-06-01_2024-06-30.csv": (
            "liquidation_transactions",
            2_485,
            15,
        ),
        "liquidation_auctions_2021-06-01_2024-06-30.csv": (
            "liquidation_auctions",
            1_157,
            33,
        ),
        "liquidation_hourly_by_ilk_2021-06-01_2024-06-30.csv": (
            "liquidation_hourly",
            162_144,
            26,
        ),
    }
    specs: list[InputSpec] = []
    for relative, metadata in manifest["combined_outputs"].items():
        name, rows, columns = known[Path(relative).name]
        specs.append(
            InputSpec(
                name,
                PROJECT_ROOT / relative,
                metadata["sha256"],
                rows,
                columns,
            )
        )
    return specs


def _protocol_specs() -> list[InputSpec]:
    manifest = json.loads(
        (
            PROJECT_ROOT / "data/protocol/provenance/manifest.json"
        ).read_text(encoding="utf-8")
    )
    reconstruction = manifest["local_reconstruction"]
    mapping = {
        "sparse_ledger": "protocol_changes",
        "interval": "protocol_intervals",
        "hourly": "protocol_hourly",
    }
    specs: list[InputSpec] = []
    for prefix, name in mapping.items():
        rows, columns = reconstruction[f"{prefix}_dimensions"]
        specs.append(
            InputSpec(
                name,
                PROJECT_ROOT / reconstruction[f"{prefix}_path"],
                reconstruction[f"{prefix}_sha256"],
                int(rows),
                int(columns),
            )
        )
    return specs


def phase2a_input_specs() -> list[InputSpec]:
    """Build all authoritative Phase 2A input specifications."""
    specs = (
        _market_and_gas_specs()
        + _liquidation_specs()
        + _protocol_specs()
    )
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise ValueError("Phase 2A input specification names are not unique.")
    return specs


def verify_input(spec: InputSpec) -> dict[str, object]:
    """Verify one input against its manifest-backed identity."""
    if not spec.path.exists():
        raise FileNotFoundError(
            f"Required Phase 2A input does not exist: {spec.path}"
        )
    actual_sha = sha256_file(spec.path)
    if actual_sha != spec.sha256:
        raise ValueError(
            f"Checksum mismatch for {spec.relative_path()}: "
            f"expected {spec.sha256}, found {actual_sha}."
        )
    actual_rows, actual_columns = csv_dimensions(spec.path)
    if (actual_rows, actual_columns) != (spec.rows, spec.columns):
        raise ValueError(
            f"Dimension mismatch for {spec.relative_path()}: expected "
            f"{spec.rows} x {spec.columns}, found "
            f"{actual_rows} x {actual_columns}."
        )
    return {
        "path": spec.relative_path(),
        "sha256": actual_sha,
        "rows": actual_rows,
        "columns": actual_columns,
    }


def verify_all_inputs(
    specs: Iterable[InputSpec] | None = None,
) -> dict[str, dict[str, object]]:
    """Verify every required input before any estimator is run."""
    selected = list(specs if specs is not None else phase2a_input_specs())
    return {spec.name: verify_input(spec) for spec in selected}


def load_inputs(
    specs: Iterable[InputSpec] | None = None,
) -> dict[str, pd.DataFrame]:
    """Load validated CSV inputs and enforce required schemas."""
    selected = list(specs if specs is not None else phase2a_input_specs())
    frames: dict[str, pd.DataFrame] = {}
    for spec in selected:
        frame = pd.read_csv(spec.path, low_memory=False)
        missing = REQUIRED_COLUMNS[spec.name].difference(frame.columns)
        if missing:
            raise ValueError(
                f"{spec.name} is missing required columns: "
                f"{sorted(missing)}."
            )
        frames[spec.name] = frame
    return frames


def parse_utc_timestamp(
    frame: pd.DataFrame,
    column: str,
    *,
    name: str,
) -> pd.Series:
    """Parse a timestamp column as UTC and fail on invalid observations."""
    parsed = pd.to_datetime(frame[column], utc=True, errors="coerce")
    invalid = int(parsed.isna().sum())
    if invalid:
        raise ValueError(
            f"{name}.{column} contains {invalid} invalid timestamps."
        )
    return parsed


def require_hourly_index(
    timestamps: pd.Series,
    *,
    name: str,
) -> None:
    """Require a unique, strictly increasing and gap-free hourly series."""
    index = pd.DatetimeIndex(timestamps)
    if index.has_duplicates:
        raise ValueError(f"{name} contains duplicate timestamps.")
    if not index.is_monotonic_increasing:
        raise ValueError(f"{name} timestamps are not strictly increasing.")
    expected = pd.date_range(index.min(), index.max(), freq="h", tz="UTC")
    if not index.equals(expected):
        missing = expected.difference(index)
        raise ValueError(
            f"{name} has {len(missing)} missing hourly timestamps."
        )


def validate_protocol_intervals(frame: pd.DataFrame) -> pd.DataFrame:
    """Parse and validate non-overlapping effective-dated protocol intervals."""
    required = REQUIRED_COLUMNS["protocol_intervals"]
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(
            "protocol_intervals is missing required columns: "
            f"{sorted(missing)}."
        )
    result = frame.copy()
    result["effective_start_utc"] = pd.to_datetime(
        result["effective_start_utc"], utc=True, errors="coerce"
    )
    result["effective_end_exclusive_utc"] = pd.to_datetime(
        result["effective_end_exclusive_utc"], utc=True, errors="coerce"
    )
    if result["effective_start_utc"].isna().any():
        raise ValueError("Protocol intervals contain invalid start times.")
    bounded = result["effective_end_exclusive_utc"].notna()
    if (
        result.loc[bounded, "effective_end_exclusive_utc"]
        <= result.loc[bounded, "effective_start_utc"]
    ).any():
        raise ValueError("Protocol intervals contain non-positive durations.")
    keys = ["module", "ilk", "parameter"]
    ordered = result.sort_values(keys + ["effective_start_utc"])
    previous_end = ordered.groupby(keys, dropna=False)[
        "effective_end_exclusive_utc"
    ].shift()
    overlaps = previous_end.notna() & (
        ordered["effective_start_utc"] < previous_end
    )
    if overlaps.any():
        raise ValueError(
            f"Protocol intervals contain {int(overlaps.sum())} overlaps."
        )
    return result
