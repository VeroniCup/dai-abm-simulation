"""Bounded Phase 1E-B representative-vault acquisition and reconstruction.

The module deliberately contains no Dune client and no credential handling.
It renders deterministic SQL, records immutable query provenance, validates
pages written by the one-request retrieval helper, and reconstructs each
authorised window locally using exact integer accounting.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, getcontext
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable, Iterator

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import acquire_dune_vaults as phase1e


getcontext().prec = 80

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "data" / "vaults" / "raw" / "chunks"
PROCESSED_ROOT = (
    ROOT / "data" / "vaults" / "processed" / "representative_regimes"
)
PROVENANCE_ROOT = (
    ROOT / "data" / "vaults" / "provenance" / "representative_regimes"
)
SQL_ROOT = (
    ROOT / "sql" / "vaults" / "generated" / "representative_regimes"
)
TRANCHE_MANIFEST = PROVENANCE_ROOT / "tranche_01_manifest.json"
MARKET_PATH = (
    ROOT / "data" / "market" / "processed"
    / "dune_hourly_market_prices_processed.csv"
)
PROTOCOL_PATH = (
    ROOT / "data" / "protocol" / "processed"
    / "phase1d_protocol_parameters_hourly.csv"
)
LIQUIDATION_ACTIONS_PATH = (
    ROOT / "data" / "liquidations" / "processed"
    / "phase1c_liquidation_actions_2021-06-01_2024-06-30.csv"
)
LIQUIDATION_AUCTIONS_PATH = (
    ROOT / "data" / "liquidations" / "processed"
    / "phase1c_liquidation_auctions_2021-06-01_2024-06-30.csv"
)
LIQUIDATION_TRANSACTIONS_PATH = (
    ROOT / "data" / "liquidations" / "processed"
    / "phase1c_liquidation_transactions_2021-06-01_2024-06-30.csv"
)
PHASE2B_CANDIDATES_PATH = (
    ROOT / "data" / "processed" / "estimation" / "phase2b_vaults"
    / "phase2b_parameter_candidates.json"
)

TARGET_ILKS = phase1e.TARGET_ILKS
CANONICAL_VAT = phase1e.CANONICAL_VAT
CANONICAL_MANAGER = phase1e.CANONICAL_MANAGER
CANONICAL_JUG = phase1e.CANONICAL_JUG
PAGE_LIMIT = 32_000
TRANCHE_CREDIT_CAP = Decimal("600")
MINIMUM_REMAINING_QUOTA = Decimal("800")
RATE_REPAIR_CREDIT_CAP = Decimal("100")
RATE_REPAIR_MINIMUM_REMAINING_QUOTA = Decimal("1400")
USDC_SVB_CREDIT_CAP = Decimal("180")
USDC_SVB_MINIMUM_REMAINING_QUOTA = Decimal("1350")
TERRA_CEFI_CREDIT_CAP = Decimal("300")
TERRA_CEFI_MINIMUM_REMAINING_QUOTA = Decimal("1100")
TERRA_CEFI_PER_QUERY_CREDIT_CAP = Decimal("100")
TERRA_CEFI_MAX_RATE_ROWS = 5_000
TERRA_CONTINUATION_CREDIT_CAP = Decimal("180")
TERRA_CONTINUATION_MINIMUM_REMAINING_QUOTA = Decimal("1250")
TERRA_OWNERSHIP_QUERY_CREDIT_CAP = Decimal("100")
TERRA_RATE_QUERY_CREDIT_CAP = Decimal("50")


@dataclass(frozen=True)
class RepresentativeWindow:
    key: str
    label: str
    start: pd.Timestamp
    end: pd.Timestamp
    estimated_mutation_rows_low: int
    estimated_mutation_rows_high: int
    estimated_credits_low: Decimal
    estimated_credits_high: Decimal


WINDOWS = {
    "quiet_mature": RepresentativeWindow(
        "quiet_mature",
        "Quiet mature market",
        pd.Timestamp("2024-02-01T00:00:00Z"),
        pd.Timestamp("2024-03-01T00:00:00Z"),
        7_250,
        14_500,
        Decimal("44"),
        Decimal("88"),
    ),
    "usdc_svb": RepresentativeWindow(
        "usdc_svb",
        "USDC/SVB depeg",
        pd.Timestamp("2023-03-06T00:00:00Z"),
        pd.Timestamp("2023-03-20T00:00:00Z"),
        7_000,
        14_000,
        Decimal("42"),
        Decimal("85"),
    ),
    "terra_cefi": RepresentativeWindow(
        "terra_cefi",
        "Terra and CeFi contagion",
        pd.Timestamp("2022-05-05T00:00:00Z"),
        pd.Timestamp("2022-06-20T00:00:00Z"),
        23_000,
        46_000,
        Decimal("139"),
        Decimal("277"),
    ),
}
WINDOW_ORDER = ("quiet_mature", "usdc_svb", "terra_cefi")

ILK_BYTES = {
    "ETH-A": "0x4554482d41000000000000000000000000000000000000000000000000000000",
    "ETH-B": "0x4554482d42000000000000000000000000000000000000000000000000000000",
    "ETH-C": "0x4554482d43000000000000000000000000000000000000000000000000000000",
    "WBTC-A": "0x574254432d410000000000000000000000000000000000000000000000000000",
    "WBTC-B": "0x574254432d420000000000000000000000000000000000000000000000000000",
    "WBTC-C": "0x574254432d430000000000000000000000000000000000000000000000000000",
}

BOUNDARY_COLUMNS = (
    "ilk", "urn", "opening_ink_raw", "opening_art_raw", "end_ink_raw",
    "end_art_raw", "pre_window_mutation_count", "window_mutation_count",
    "last_pre_window_mutation_time_utc", "last_window_mutation_time_utc",
    "opening_rate_raw_ray", "opening_rate_effective_time_utc",
    "end_rate_raw_ray", "end_rate_effective_time_utc",
    "canonical_vat_contract",
)
MUTATION_COLUMNS = phase1e.MUTATION_COLUMNS
OWNERSHIP_COLUMNS = (
    "record_type", "effective_time_utc", "block_number", "transaction_hash",
    "transaction_index", "trace_position", "event_index", "ilk", "cdp_id",
    "urn", "owner_or_proxy", "manager_contract", "source_table",
    "call_success",
)
RATE_COLUMNS = phase1e.RATE_COLUMNS
SPARSE_RATE_COLUMNS = (
    "ilk", "effective_time_utc", "block_number", "transaction_index",
    "trace_position", "transaction_hash", "source_type",
    "previous_rate_raw_ray", "resulting_rate_raw_ray", "raw_rate_delta",
    "opening_state_flag", "observed_call_flag",
    "provenance_classification", "source_contract", "source_table",
)
BARK_COLUMNS = (
    "block_time_utc", "block_number", "transaction_hash",
    "transaction_index", "event_index", "ilk", "urn", "auction_id",
    "keeper", "dog_contract", "clipper_contract", "ink_raw", "art_raw",
    "due_raw", "source_table",
)
BARK_GRAB_LINKAGE_COLUMNS = (
    "window", "transaction_hash", "ilk", "urn", "auction_id", "keeper",
    "grab_block_number", "grab_transaction_index", "grab_trace_position",
    "grab_dink_raw", "grab_dart_raw", "bark_ink_raw", "bark_art_raw",
    "linkage_status", "economic_treatment",
)
STREAM_COLUMNS = {
    "boundary_states": BOUNDARY_COLUMNS,
    "vat_mutations": MUTATION_COLUMNS,
    "ownership_history": OWNERSHIP_COLUMNS,
    "effective_rates": RATE_COLUMNS,
}
USDC_SVB_STREAM_ESTIMATES = {
    "boundary_states": {
        "rows_low": 3_000, "rows_high": 4_000,
        "credits_low": "20", "credits_high": "30",
    },
    "vat_mutations": {
        "rows_low": 1_000, "rows_high": 3_000,
        "credits_low": "8", "credits_high": "20",
    },
    "ownership_history": {
        "rows_low": 3_000, "rows_high": 4_500,
        "credits_low": "45", "credits_high": "70",
    },
    "bark_annotations": {
        "rows_low": 0, "rows_high": 100,
        "credits_low": "0", "credits_high": "0",
        "source": "local bounded extraction from validated Phase 1C",
    },
    "effective_rates": {
        "rows_low": 900, "rows_high": 1_500,
        "credits_low": "6", "credits_high": "12",
    },
}
TERRA_CEFI_STREAM_ESTIMATES = {
    "boundary_states": {
        "rows_low": 3_000, "rows_high": 4_500,
        "credits_low": "20", "credits_high": "35",
    },
    "vat_mutations": {
        "rows_low": 4_000, "rows_high": 16_000,
        "credits_low": "35", "credits_high": "100",
    },
    "ownership_history": {
        "rows_low": 3_000, "rows_high": 5_000,
        "credits_low": "45", "credits_high": "70",
    },
    "bark_annotations": {
        "rows_low": 600, "rows_high": 700,
        "credits_low": "0", "credits_high": "0",
        "source": "local bounded extraction from validated Phase 1C",
    },
    "effective_rates": {
        "rows_low": 3_500, "rows_high": 5_000,
        "credits_low": "18", "credits_high": "35",
    },
}


class RepresentativeAcquisitionError(RuntimeError):
    """Raised when a bounded acquisition or reconstruction gate fails."""


@dataclass
class ResultRequestGuard:
    """Prevent a recovery workflow from issuing more than one result request."""

    maximum_requests: int = 1
    requests_used: int = 0

    def mark_request(self) -> None:
        if self.requests_used >= self.maximum_requests:
            raise RepresentativeAcquisitionError(
                "the authorised result-request count has been exhausted"
            )
        self.requests_used += 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def write_json_atomic(path: Path, payload: Any) -> None:
    write_text_atomic(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


def write_csv_atomic(
    path: Path, columns: Iterable[str], rows: Iterable[dict[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(columns), lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def window_slug(window: RepresentativeWindow) -> str:
    return (
        f"{window.key}_{window.start:%Y-%m-%d}_{window.end:%Y-%m-%d}"
    )


def window_paths(window: RepresentativeWindow) -> dict[str, Path]:
    slug = window_slug(window)
    return {
        "raw": RAW_ROOT / slug,
        "processed": PROCESSED_ROOT / slug,
        "provenance": PROVENANCE_ROOT / slug,
        "sql": SQL_ROOT / slug,
    }


def stream_paths(
    window: RepresentativeWindow, stream: str
) -> dict[str, Path]:
    if stream not in STREAM_COLUMNS:
        raise RepresentativeAcquisitionError(f"unknown stream {stream}")
    base = window_paths(window)
    raw_directory = (
        "ownership"
        if window.key == "terra_cefi" and stream == "ownership_history"
        else stream
    )
    return {
        "sql": base["sql"] / f"{stream}.sql",
        "state": base["provenance"] / f"{stream}.state.json",
        "metadata": base["provenance"] / f"{stream}.metadata.json",
        "validation": base["provenance"] / f"{stream}.validation.json",
        "raw": base["raw"] / raw_directory / f"{stream}.csv",
        "pages": base["raw"] / raw_directory / "pages",
    }


def _window_credit_policy(
    window: RepresentativeWindow,
) -> tuple[Decimal, Decimal, dict[str, dict[str, Any]]]:
    if window.key == "terra_cefi":
        return (
            TERRA_CEFI_CREDIT_CAP,
            TERRA_CEFI_MINIMUM_REMAINING_QUOTA,
            TERRA_CEFI_STREAM_ESTIMATES,
        )
    if window.key == "usdc_svb":
        return (
            USDC_SVB_CREDIT_CAP,
            USDC_SVB_MINIMUM_REMAINING_QUOTA,
            USDC_SVB_STREAM_ESTIMATES,
        )
    return (
        TRANCHE_CREDIT_CAP,
        MINIMUM_REMAINING_QUOTA,
        {},
    )


def update_window_manifest(
    window: RepresentativeWindow,
    *,
    starting_usage: Decimal,
    current_usage: Decimal,
    quota: Decimal,
    status: str,
) -> dict[str, Any]:
    """Create or refresh the bounded representative-window manifest."""
    base = window_paths(window)
    credit_cap, reserve, stream_estimates = _window_credit_policy(window)
    manifest_path = base["provenance"] / "manifest.json"
    streams: dict[str, Any] = {}
    for stream in STREAM_COLUMNS:
        paths = stream_paths(window, stream)
        if paths["state"].exists():
            streams[stream] = json.loads(paths["state"].read_text())
        else:
            streams[stream] = {"state": "not_started"}
    bark_state = base["provenance"] / "bark_annotations.state.json"
    streams["bark_annotations"] = (
        json.loads(bark_state.read_text())
        if bark_state.exists() else {"state": "not_started"}
    )
    reconstruction_metadata_path = (
        base["provenance"] / "reconstruction_metadata.json"
    )
    reconstruction_validation_path = (
        base["provenance"] / "reconstruction_validation.json"
    )
    reconstruction: dict[str, Any] = {"state": "not_started"}
    if (
        reconstruction_metadata_path.exists()
        and reconstruction_validation_path.exists()
    ):
        reconstruction_metadata = json.loads(
            reconstruction_metadata_path.read_text(encoding="utf-8")
        )
        reconstruction_validation = json.loads(
            reconstruction_validation_path.read_text(encoding="utf-8")
        )
        reconstruction = {
            "state": (
                "complete"
                if reconstruction_validation.get("validation_passed")
                else "failed_validation"
            ),
            "metadata_path": relative(reconstruction_metadata_path),
            "metadata_sha256": sha256_file(reconstruction_metadata_path),
            "validation_path": relative(reconstruction_validation_path),
            "validation_sha256": sha256_file(reconstruction_validation_path),
            "validation_passed": bool(
                reconstruction_validation.get("validation_passed")
            ),
            "outputs": reconstruction_metadata.get("outputs", {}),
        }
    manifest = {
        "phase": "1E-B",
        "window": window.key,
        "window_label": window.label,
        "status": status,
        "start_utc": window.start.isoformat(),
        "end_exclusive_utc": window.end.isoformat(),
        "target_ilks": list(TARGET_ILKS),
        "target_ilk_rationale": (
            "Exact ETH and WBTC Maker vault ilks measure vault-owner response "
            f"within the approved {window.label} regime; PSM, stablecoin-backed "
            "and unrelated collateral accounting are outside scope."
        ),
        "engine": "small",
        "query_type": "private temporary bounded production",
        "stream_estimates": stream_estimates,
        "estimated_total_credits_low": str(
            sum(
                Decimal(item["credits_low"])
                for item in stream_estimates.values()
            )
        ),
        "estimated_total_credits_high": str(
            sum(
                Decimal(item["credits_high"])
                for item in stream_estimates.values()
            )
        ),
        "hard_additional_credit_cap": str(credit_cap),
        "minimum_remaining_quota": str(reserve),
        "starting_usage": str(starting_usage),
        "current_usage": str(current_usage),
        "observed_credit_delta": str(current_usage - starting_usage),
        "remaining_quota": str(quota - current_usage),
        "input_checksums": {
            "market_panel": {
                "path": relative(MARKET_PATH),
                "sha256": sha256_file(MARKET_PATH),
            },
            "protocol_panel": {
                "path": relative(PROTOCOL_PATH),
                "sha256": sha256_file(PROTOCOL_PATH),
            },
            "liquidation_actions": {
                "path": relative(LIQUIDATION_ACTIONS_PATH),
                "sha256": sha256_file(LIQUIDATION_ACTIONS_PATH),
            },
            "liquidation_auctions": {
                "path": relative(LIQUIDATION_AUCTIONS_PATH),
                "sha256": sha256_file(LIQUIDATION_AUCTIONS_PATH),
            },
            "quiet_reconstruction_metadata": {
                "path": relative(
                    PROVENANCE_ROOT
                    / window_slug(WINDOWS["quiet_mature"])
                    / "reconstruction_metadata.json"
                ),
                "sha256": sha256_file(
                    PROVENANCE_ROOT
                    / window_slug(WINDOWS["quiet_mature"])
                    / "reconstruction_metadata.json"
                ),
            },
        },
        "acquisition_script": {
            "path": relative(Path(__file__)),
            "sha256": sha256_file(Path(__file__)),
        },
        "streams": streams,
        "reconstruction": reconstruction,
        "automatic_retry_count": 0,
        "ftx_acquired_or_used": False,
        "ftx_scope_note": (
            "No FTX calibration or validation window, Vat-mutation sample, "
            "market sample or liquidation sample was acquired or used. "
            "Historical manager open/give records are retained only to "
            f"establish effective owner/proxy state at the {window.label} "
            "boundary and are not treated as FTX behavioural evidence."
        ),
        "updated_at_utc": utc_now(),
    }
    write_json_atomic(manifest_path, manifest)
    return manifest


def _selected_ilks_sql() -> str:
    values = ",\n        ".join(
        f"({ILK_BYTES[ilk]}, '{ilk}')" for ilk in TARGET_ILKS
    )
    return f"selected_ilks(ilk_raw, ilk) AS (\n    VALUES\n        {values}\n)"


def _date(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%d")


def _time(value: pd.Timestamp) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


def render_mutation_sql(window: RepresentativeWindow) -> str:
    template = phase1e.TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "{{START_DATE}}": _date(window.start),
        "{{END_DATE}}": _date(window.end),
        "{{START_TIMESTAMP}}": _time(window.start),
        "{{END_TIMESTAMP}}": _time(window.end),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    if not phase1e.query_has_deterministic_order(template):
        raise RepresentativeAcquisitionError(
            "mutation SQL lacks deterministic final ordering"
        )
    return template


def render_boundary_sql(window: RepresentativeWindow) -> str:
    scan_start = pd.Timestamp("2019-11-01T00:00:00Z")
    return f"""-- Phase 1E-B authoritative boundary states for {window.label}.
WITH
{_selected_ilks_sql()},
mutations AS (
    SELECT f.call_block_time AS block_time_utc, i.ilk, f.u AS urn,
           f.dink AS dink_raw, f.dart AS dart_raw
    FROM maker_ethereum.vat_call_frob f
    JOIN selected_ilks i ON i.ilk_raw = f.i
    WHERE f.call_block_date >= DATE '{_date(scan_start)}'
      AND f.call_block_date < DATE '{_date(window.end)}'
      AND f.call_block_time >= TIMESTAMP '{_time(scan_start)}'
      AND f.call_block_time < TIMESTAMP '{_time(window.end)}'
      AND f.contract_address = 0x{CANONICAL_VAT[2:]}
      AND f.call_success = true
    UNION ALL
    SELECT f.call_block_time, i.ilk, f.src, -f.dink, -f.dart
    FROM maker_ethereum.vat_call_fork f
    JOIN selected_ilks i ON i.ilk_raw = f.ilk
    WHERE f.call_block_date >= DATE '{_date(scan_start)}'
      AND f.call_block_date < DATE '{_date(window.end)}'
      AND f.call_block_time >= TIMESTAMP '{_time(scan_start)}'
      AND f.call_block_time < TIMESTAMP '{_time(window.end)}'
      AND f.contract_address = 0x{CANONICAL_VAT[2:]}
      AND f.call_success = true
    UNION ALL
    SELECT f.call_block_time, i.ilk, f.dst, f.dink, f.dart
    FROM maker_ethereum.vat_call_fork f
    JOIN selected_ilks i ON i.ilk_raw = f.ilk
    WHERE f.call_block_date >= DATE '{_date(scan_start)}'
      AND f.call_block_date < DATE '{_date(window.end)}'
      AND f.call_block_time >= TIMESTAMP '{_time(scan_start)}'
      AND f.call_block_time < TIMESTAMP '{_time(window.end)}'
      AND f.contract_address = 0x{CANONICAL_VAT[2:]}
      AND f.call_success = true
    UNION ALL
    SELECT g.call_block_time, i.ilk, g.u, g.dink, g.dart
    FROM maker_ethereum.vat_call_grab g
    JOIN selected_ilks i ON i.ilk_raw = g.i
    WHERE g.call_block_date >= DATE '{_date(scan_start)}'
      AND g.call_block_date < DATE '{_date(window.end)}'
      AND g.call_block_time >= TIMESTAMP '{_time(scan_start)}'
      AND g.call_block_time < TIMESTAMP '{_time(window.end)}'
      AND g.contract_address = 0x{CANONICAL_VAT[2:]}
      AND g.call_success = true
),
balances AS (
    SELECT ilk, urn,
           SUM(CASE WHEN block_time_utc < TIMESTAMP '{_time(window.start)}'
                    THEN dink_raw ELSE CAST(0 AS int256) END) AS opening_ink_raw,
           SUM(CASE WHEN block_time_utc < TIMESTAMP '{_time(window.start)}'
                    THEN dart_raw ELSE CAST(0 AS int256) END) AS opening_art_raw,
           SUM(dink_raw) AS end_ink_raw,
           SUM(dart_raw) AS end_art_raw,
           COUNT_IF(block_time_utc < TIMESTAMP '{_time(window.start)}')
               AS pre_window_mutation_count,
           COUNT_IF(block_time_utc >= TIMESTAMP '{_time(window.start)}')
               AS window_mutation_count,
           MAX(CASE WHEN block_time_utc < TIMESTAMP '{_time(window.start)}'
                    THEN block_time_utc END) AS last_pre_window_mutation_time_utc,
           MAX(CASE WHEN block_time_utc >= TIMESTAMP '{_time(window.start)}'
                    THEN block_time_utc END) AS last_window_mutation_time_utc
    FROM mutations
    GROUP BY ilk, urn
),
rate_observations AS (
    SELECT d.call_block_time AS effective_time_utc, i.ilk, d.output_rate,
           d.call_block_number, d.call_trace_address, d.call_tx_hash
    FROM maker_ethereum.jug_call_drip d
    JOIN selected_ilks i ON i.ilk_raw = d.ilk
    WHERE d.call_block_date >= DATE '{_date(scan_start)}'
      AND d.call_block_date < DATE '{_date(window.end)}'
      AND d.call_block_time >= TIMESTAMP '{_time(scan_start)}'
      AND d.call_block_time < TIMESTAMP '{_time(window.end)}'
      AND d.contract_address = 0x{CANONICAL_JUG[2:]}
      AND d.call_success = true
),
opening_rates AS (
    SELECT ilk, output_rate, effective_time_utc
    FROM (
        SELECT ilk, output_rate, effective_time_utc,
               ROW_NUMBER() OVER (
            PARTITION BY ilk
            ORDER BY call_block_number DESC, call_trace_address DESC,
                     call_tx_hash DESC
        ) AS rank
        FROM rate_observations
        WHERE effective_time_utc < TIMESTAMP '{_time(window.start)}'
    )
    WHERE rank = 1
),
end_rates AS (
    SELECT ilk, output_rate, effective_time_utc
    FROM (
        SELECT ilk, output_rate, effective_time_utc,
               ROW_NUMBER() OVER (
            PARTITION BY ilk
            ORDER BY call_block_number DESC, call_trace_address DESC,
                     call_tx_hash DESC
        ) AS rank
        FROM rate_observations
    )
    WHERE rank = 1
)
SELECT
    b.ilk,
    CONCAT('0x', TO_HEX(b.urn)) AS urn,
    CAST(b.opening_ink_raw AS varchar) AS opening_ink_raw,
    CAST(b.opening_art_raw AS varchar) AS opening_art_raw,
    CAST(b.end_ink_raw AS varchar) AS end_ink_raw,
    CAST(b.end_art_raw AS varchar) AS end_art_raw,
    b.pre_window_mutation_count,
    b.window_mutation_count,
    b.last_pre_window_mutation_time_utc,
    b.last_window_mutation_time_utc,
    CAST(o.output_rate AS varchar) AS opening_rate_raw_ray,
    o.effective_time_utc AS opening_rate_effective_time_utc,
    CAST(e.output_rate AS varchar) AS end_rate_raw_ray,
    e.effective_time_utc AS end_rate_effective_time_utc,
    '{CANONICAL_VAT}' AS canonical_vat_contract
FROM balances b
LEFT JOIN opening_rates o ON o.ilk = b.ilk
LEFT JOIN end_rates e ON e.ilk = b.ilk
WHERE b.opening_ink_raw <> 0 OR b.opening_art_raw <> 0
   OR b.end_ink_raw <> 0 OR b.end_art_raw <> 0
   OR b.window_mutation_count > 0
ORDER BY b.ilk, b.urn
"""


def render_rate_sql(window: RepresentativeWindow) -> str:
    scan_start = pd.Timestamp("2019-11-01T00:00:00Z")
    return f"""-- Phase 1E-B sparse effective rates for {window.label}.
WITH
{_selected_ilks_sql()},
historical_drips AS (
    SELECT d.call_block_time AS effective_time_utc, d.call_block_number,
           d.call_tx_hash, d.call_trace_address, i.ilk, d.output_rate,
           d.contract_address,
           ROW_NUMBER() OVER (
               PARTITION BY i.ilk
               ORDER BY d.call_block_number DESC, d.call_trace_address DESC,
                        d.call_tx_hash DESC
           ) AS pre_window_rank
    FROM maker_ethereum.jug_call_drip d
    JOIN selected_ilks i ON i.ilk_raw = d.ilk
    WHERE d.call_block_date >= DATE '{_date(scan_start)}'
      AND d.call_block_date < DATE '{_date(window.start)}'
      AND d.call_block_time >= TIMESTAMP '{_time(scan_start)}'
      AND d.call_block_time < TIMESTAMP '{_time(window.start)}'
      AND d.contract_address = 0x{CANONICAL_JUG[2:]}
      AND d.call_success = true
),
window_drips AS (
    SELECT d.call_block_time AS effective_time_utc, d.call_block_number,
           d.call_tx_hash, d.call_trace_address, i.ilk, d.output_rate,
           d.contract_address
    FROM maker_ethereum.jug_call_drip d
    JOIN selected_ilks i ON i.ilk_raw = d.ilk
    WHERE d.call_block_date >= DATE '{_date(window.start)}'
      AND d.call_block_date < DATE '{_date(window.end)}'
      AND d.call_block_time >= TIMESTAMP '{_time(window.start)}'
      AND d.call_block_time < TIMESTAMP '{_time(window.end)}'
      AND d.contract_address = 0x{CANONICAL_JUG[2:]}
      AND d.call_success = true
),
window_folds AS (
    SELECT f.call_block_time AS effective_time_utc, f.call_block_number,
           f.call_tx_hash, f.call_trace_address, i.ilk, f.rate,
           f.contract_address
    FROM maker_ethereum.vat_call_fold f
    JOIN selected_ilks i ON i.ilk_raw = f.i
    WHERE f.call_block_date >= DATE '{_date(window.start)}'
      AND f.call_block_date < DATE '{_date(window.end)}'
      AND f.call_block_time >= TIMESTAMP '{_time(window.start)}'
      AND f.call_block_time < TIMESTAMP '{_time(window.end)}'
      AND f.contract_address = 0x{CANONICAL_VAT[2:]}
      AND f.call_success = true
),
records AS (
    SELECT effective_time_utc, call_block_number AS block_number,
           call_tx_hash AS transaction_hash_raw, call_trace_address,
           ilk, 'drip' AS rate_record_type,
           CAST(output_rate AS varchar) AS raw_rate_ray,
           CAST(NULL AS varchar) AS raw_rate_delta,
           contract_address AS source_contract_raw,
           'maker_ethereum.jug_call_drip' AS source_table
    FROM historical_drips WHERE pre_window_rank = 1
    UNION ALL
    SELECT effective_time_utc, call_block_number, call_tx_hash,
           call_trace_address, ilk, 'drip', CAST(output_rate AS varchar),
           CAST(NULL AS varchar), contract_address,
           'maker_ethereum.jug_call_drip'
    FROM window_drips
    UNION ALL
    SELECT effective_time_utc, call_block_number, call_tx_hash,
           call_trace_address, ilk, 'fold', CAST(NULL AS varchar),
           CAST(rate AS varchar), contract_address,
           'maker_ethereum.vat_call_fold'
    FROM window_folds
),
transactions AS (
    SELECT hash, block_number, index AS transaction_index
    FROM ethereum.transactions
    WHERE block_date >= DATE '{_date(scan_start)}'
      AND block_date < DATE '{_date(window.end)}'
      AND block_time >= TIMESTAMP '{_time(scan_start)}'
      AND block_time < TIMESTAMP '{_time(window.end)}'
)
SELECT r.effective_time_utc, r.block_number,
       CONCAT('0x', TO_HEX(r.transaction_hash_raw)) AS transaction_hash,
       t.transaction_index,
       ARRAY_JOIN(
           TRANSFORM(r.call_trace_address, x -> CAST(x AS varchar)), '.'
       ) AS trace_position,
       r.ilk, r.rate_record_type, r.raw_rate_ray, r.raw_rate_delta,
       true AS call_success,
       CONCAT('0x', TO_HEX(r.source_contract_raw)) AS source_contract,
       r.source_table
FROM records r
JOIN transactions t ON t.hash = r.transaction_hash_raw
                   AND t.block_number = r.block_number
ORDER BY r.block_number, t.transaction_index, r.call_trace_address,
         r.transaction_hash_raw, r.rate_record_type, r.ilk
"""


def render_in_window_rate_sql(window: RepresentativeWindow) -> str:
    """Render the Method B query for exact, bounded accumulated-rate changes."""
    return f"""-- Phase 1E-B Method B: bounded accumulated-rate changes only.
WITH
{_selected_ilks_sql()},
window_drips AS (
    SELECT
        d.call_block_time AS effective_time_utc,
        d.call_block_number AS block_number,
        d.call_tx_hash AS transaction_hash_raw,
        d.call_trace_address AS trace_address_raw,
        i.ilk,
        'drip' AS rate_record_type,
        CAST(d.output_rate AS varchar) AS raw_rate_ray,
        CAST(NULL AS varchar) AS raw_rate_delta,
        d.call_success,
        d.contract_address AS source_contract_raw,
        'maker_ethereum.jug_call_drip' AS source_table
    FROM maker_ethereum.jug_call_drip d
    INNER JOIN selected_ilks i ON i.ilk_raw = d.ilk
    WHERE d.call_block_date >= DATE '{_date(window.start)}'
      AND d.call_block_date < DATE '{_date(window.end)}'
      AND d.call_block_time >= TIMESTAMP '{_time(window.start)}'
      AND d.call_block_time < TIMESTAMP '{_time(window.end)}'
      AND d.contract_address = 0x{CANONICAL_JUG[2:]}
      AND d.call_success = true
),
window_folds AS (
    SELECT
        f.call_block_time AS effective_time_utc,
        f.call_block_number AS block_number,
        f.call_tx_hash AS transaction_hash_raw,
        f.call_trace_address AS trace_address_raw,
        i.ilk,
        'fold' AS rate_record_type,
        CAST(NULL AS varchar) AS raw_rate_ray,
        CAST(f.rate AS varchar) AS raw_rate_delta,
        f.call_success,
        f.contract_address AS source_contract_raw,
        'maker_ethereum.vat_call_fold' AS source_table
    FROM maker_ethereum.vat_call_fold f
    INNER JOIN selected_ilks i ON i.ilk_raw = f.i
    WHERE f.call_block_date >= DATE '{_date(window.start)}'
      AND f.call_block_date < DATE '{_date(window.end)}'
      AND f.call_block_time >= TIMESTAMP '{_time(window.start)}'
      AND f.call_block_time < TIMESTAMP '{_time(window.end)}'
      AND f.contract_address = 0x{CANONICAL_VAT[2:]}
      AND f.call_success = true
),
rate_records AS (
    SELECT effective_time_utc, block_number, transaction_hash_raw,
           trace_address_raw, ilk, rate_record_type, raw_rate_ray,
           raw_rate_delta, call_success, source_contract_raw, source_table
    FROM window_drips
    UNION ALL
    SELECT effective_time_utc, block_number, transaction_hash_raw,
           trace_address_raw, ilk, rate_record_type, raw_rate_ray,
           raw_rate_delta, call_success, source_contract_raw, source_table
    FROM window_folds
),
transactions AS (
    SELECT hash, block_number, index AS transaction_index
    FROM ethereum.transactions
    WHERE block_date >= DATE '{_date(window.start)}'
      AND block_date < DATE '{_date(window.end)}'
      AND block_time >= TIMESTAMP '{_time(window.start)}'
      AND block_time < TIMESTAMP '{_time(window.end)}'
)
SELECT
    r.effective_time_utc,
    r.block_number,
    CONCAT('0x', TO_HEX(r.transaction_hash_raw)) AS transaction_hash,
    t.transaction_index,
    ARRAY_JOIN(
        TRANSFORM(r.trace_address_raw, x -> CAST(x AS varchar)), '.'
    ) AS trace_position,
    r.ilk,
    r.rate_record_type,
    r.raw_rate_ray,
    r.raw_rate_delta,
    r.call_success,
    CONCAT('0x', TO_HEX(r.source_contract_raw)) AS source_contract,
    r.source_table
FROM rate_records r
INNER JOIN transactions t
    ON t.hash = r.transaction_hash_raw
   AND t.block_number = r.block_number
ORDER BY
    r.block_number,
    t.transaction_index,
    r.trace_address_raw,
    r.transaction_hash_raw,
    r.rate_record_type,
    r.ilk
"""


def render_ownership_sql(
    window: RepresentativeWindow, urns: Iterable[str]
) -> str:
    values = sorted({str(value).lower() for value in urns})
    if not values:
        raise RepresentativeAcquisitionError(
            "ownership SQL requires at least one authoritative urn"
        )
    for value in values:
        if not re.fullmatch(r"0x[0-9a-f]{40}", value):
            raise RepresentativeAcquisitionError("invalid urn in ownership set")
    urn_values = ",\n        ".join(f"(0x{value[2:]})" for value in values)
    scan_start = pd.Timestamp("2019-11-01T00:00:00Z")
    return f"""-- Phase 1E-B manager identity history for authoritative window urns.
WITH
{_selected_ilks_sql()},
selected_urns(urn) AS (
    VALUES
        {urn_values}
),
opens AS (
    SELECT o.call_block_time, o.call_block_number, o.call_tx_hash,
           o.call_trace_address, i.ilk, o.output_0 AS cdp_id, o.usr,
           o.contract_address
    FROM maker_ethereum.cdp_manager_call_open o
    JOIN selected_ilks i ON i.ilk_raw = o.ilk
    WHERE o.call_block_date >= DATE '{_date(scan_start)}'
      AND o.call_block_date < DATE '{_date(window.end)}'
      AND o.call_block_time >= TIMESTAMP '{_time(scan_start)}'
      AND o.call_block_time < TIMESTAMP '{_time(window.end)}'
      AND o.contract_address = 0x{CANONICAL_MANAGER[2:]}
      AND o.call_success = true
),
creates AS (
    SELECT c.block_time, c.block_number, c.tx_hash, c.trace_address,
           c.address
    FROM ethereum.traces c
    JOIN selected_urns u ON u.urn = c.address
    WHERE c.block_date >= DATE '{_date(scan_start)}'
      AND c.block_date < DATE '{_date(window.end)}'
      AND c.block_time >= TIMESTAMP '{_time(scan_start)}'
      AND c.block_time < TIMESTAMP '{_time(window.end)}'
      AND c.type = 'create' AND c.success = true
      AND c."from" = 0x{CANONICAL_MANAGER[2:]}
),
open_mappings AS (
    SELECT o.*, c.address AS urn
    FROM opens o
    JOIN creates c
      ON c.tx_hash = o.call_tx_hash
     AND c.trace_address = CONCAT(
         o.call_trace_address, ARRAY[CAST(0 AS bigint)]
     )
),
gives AS (
    SELECT g.call_block_time, g.call_block_number, g.call_tx_hash,
           g.call_trace_address, g.cdp AS cdp_id, g.dst,
           g.contract_address, m.ilk, m.urn
    FROM maker_ethereum.cdp_manager_call_give g
    JOIN open_mappings m ON m.cdp_id = g.cdp
    WHERE g.call_block_date >= DATE '{_date(scan_start)}'
      AND g.call_block_date < DATE '{_date(window.end)}'
      AND g.call_block_time >= TIMESTAMP '{_time(scan_start)}'
      AND g.call_block_time < TIMESTAMP '{_time(window.end)}'
      AND g.contract_address = 0x{CANONICAL_MANAGER[2:]}
      AND g.call_success = true
),
transactions AS (
    SELECT hash, block_number, index AS transaction_index
    FROM ethereum.transactions
    WHERE block_date >= DATE '{_date(scan_start)}'
      AND block_date < DATE '{_date(window.end)}'
      AND block_time >= TIMESTAMP '{_time(scan_start)}'
      AND block_time < TIMESTAMP '{_time(window.end)}'
),
records AS (
    SELECT 'open' AS record_type, m.call_block_time AS effective_time_utc,
           m.call_block_number AS block_number, m.call_tx_hash AS tx_hash,
           m.call_trace_address AS trace_address, CAST(NULL AS bigint) AS event_index,
           m.ilk, m.cdp_id, m.urn, m.usr AS owner_or_proxy,
           m.contract_address, 'maker_ethereum.cdp_manager_call_open' AS source_table
    FROM open_mappings m
    UNION ALL
    SELECT 'give', g.call_block_time, g.call_block_number, g.call_tx_hash,
           g.call_trace_address, CAST(NULL AS bigint), g.ilk, g.cdp_id,
           g.urn, g.dst, g.contract_address,
           'maker_ethereum.cdp_manager_call_give'
    FROM gives g
)
SELECT r.record_type, r.effective_time_utc, r.block_number,
       CONCAT('0x', TO_HEX(r.tx_hash)) AS transaction_hash,
       t.transaction_index,
       ARRAY_JOIN(TRANSFORM(r.trace_address, x -> CAST(x AS varchar)), '.')
           AS trace_position,
       r.event_index, r.ilk, CAST(r.cdp_id AS varchar) AS cdp_id,
       CONCAT('0x', TO_HEX(r.urn)) AS urn,
       CONCAT('0x', TO_HEX(r.owner_or_proxy)) AS owner_or_proxy,
       CONCAT('0x', TO_HEX(r.contract_address)) AS manager_contract,
       r.source_table, true AS call_success
FROM records r
JOIN transactions t ON t.hash = r.tx_hash
                   AND t.block_number = r.block_number
ORDER BY r.block_number, t.transaction_index, r.trace_address,
         r.tx_hash, r.record_type, r.cdp_id
"""


def render_sql(
    window: RepresentativeWindow,
    stream: str,
    *,
    urns: Iterable[str] = (),
) -> str:
    if stream == "boundary_states":
        return render_boundary_sql(window)
    if stream == "vat_mutations":
        return render_mutation_sql(window)
    if stream == "ownership_history":
        return render_ownership_sql(window, urns)
    if stream == "effective_rates":
        return render_in_window_rate_sql(window)
    raise RepresentativeAcquisitionError(f"unknown stream {stream}")


def initialise_stream(
    window: RepresentativeWindow,
    stream: str,
    *,
    urns: Iterable[str] = (),
) -> dict[str, Any]:
    paths = stream_paths(window, stream)
    if paths["state"].exists():
        state = json.loads(paths["state"].read_text(encoding="utf-8"))
        if state.get("state") == "complete" and state.get("validation_passed"):
            return {**state, "skipped_completed": True}
        raise RepresentativeAcquisitionError(
            f"{window.key}/{stream} is incomplete; replacement is not authorised"
        )
    sql = render_sql(window, stream, urns=urns)
    if "ORDER BY" not in sql.upper():
        raise RepresentativeAcquisitionError("production SQL is unordered")
    write_text_atomic(paths["sql"], sql)
    state = {
        "window": window.key,
        "window_label": window.label,
        "start_utc": window.start.isoformat(),
        "end_exclusive_utc": window.end.isoformat(),
        "stream": stream,
        "state": "planned",
        "engine": "small",
        "query_type": "private temporary bounded production",
        "sql_path": relative(paths["sql"]),
        "sql_sha256": sha256_text(sql),
        "query_id": None,
        "execution_id": None,
        "retrieval_count": 0,
        "validation_passed": False,
        "created_at_utc": utc_now(),
    }
    write_json_atomic(paths["state"], state)
    return state


def record_submission(
    window: RepresentativeWindow,
    stream: str,
    *,
    query_id: int,
    execution_id: str,
    query_url: str,
    usage_before: Decimal,
) -> dict[str, Any]:
    paths = stream_paths(window, stream)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    if state.get("query_id") or state.get("execution_id"):
        raise RepresentativeAcquisitionError("submission already recorded")
    state.update({
        "state": "execution_submitted",
        "query_id": query_id,
        "execution_id": execution_id,
        "query_url": query_url,
        "usage_before": str(usage_before),
        "submitted_at_utc": utc_now(),
    })
    write_json_atomic(paths["state"], state)
    return state


def record_result_metadata(
    window: RepresentativeWindow,
    stream: str,
    *,
    total_rows: int,
    execution_state: str,
    execution_cost_credits: Decimal | None,
) -> dict[str, Any]:
    paths = stream_paths(window, stream)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    if total_rows < 0 or execution_state != "COMPLETED":
        raise RepresentativeAcquisitionError("execution is not retrievable")
    state.update({
        "state": "execution_completed",
        "execution_state": execution_state,
        "api_reported_total_rows": total_rows,
        "execution_cost_credits": (
            None if execution_cost_credits is None
            else str(execution_cost_credits)
        ),
        "completed_at_utc": utc_now(),
    })
    if (
        window.key == "terra_cefi"
        and stream == "effective_rates"
        and total_rows > TERRA_CEFI_MAX_RATE_ROWS
    ):
        state.update({
            "state": "halted_oversized_effective_rate_result",
            "validation_passed": False,
            "halt_reason": (
                f"effective-rate result has {total_rows} rows; authorised "
                f"maximum is {TERRA_CEFI_MAX_RATE_ROWS}"
            ),
        })
        write_json_atomic(paths["state"], state)
        raise RepresentativeAcquisitionError(state["halt_reason"])
    write_json_atomic(paths["state"], state)
    return state


def record_halt(
    window: RepresentativeWindow,
    stream: str,
    *,
    reason: str,
    usage_after: Decimal,
    projected_export_credits: Decimal,
) -> dict[str, Any]:
    """Persist a cost or retrieval stop without implying stream completion."""
    paths = stream_paths(window, stream)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    state.update({
        "state": "halted_before_result_retrieval",
        "halt_reason": reason,
        "usage_after": str(usage_after),
        "observed_credit_delta": str(
            usage_after - Decimal(state["usage_before"])
        ),
        "projected_export_credits": str(projected_export_credits),
        "retrieval_count": 0,
        "raw_file_persisted": False,
        "validation_passed": False,
        "halted_at_utc": utc_now(),
    })
    write_json_atomic(paths["state"], state)
    write_json_atomic(paths["metadata"], {
        "window": window.key,
        "stream": stream,
        "query_id": state["query_id"],
        "query_url": state["query_url"],
        "execution_id": state["execution_id"],
        "execution_state": state.get("execution_state"),
        "api_reported_total_rows": state.get("api_reported_total_rows"),
        "execution_cost_credits": state.get("execution_cost_credits"),
        "usage_before": state["usage_before"],
        "usage_after": state["usage_after"],
        "observed_credit_delta": state["observed_credit_delta"],
        "projected_export_credits": state["projected_export_credits"],
        "retrieval_count": 0,
        "raw_file_persisted": False,
        "validation_status": "not_run_result_not_retrieved",
        "halt_reason": reason,
        "recorded_at_utc": utc_now(),
    })
    return state


def page_plan(total_rows: int) -> tuple[tuple[int, int], ...]:
    return tuple(
        (offset, min(PAGE_LIMIT, total_rows - offset))
        for offset in range(0, total_rows, PAGE_LIMIT)
    ) or ((0, 1),)


def page_path(
    window: RepresentativeWindow, stream: str, offset: int, limit: int
) -> Path:
    return stream_paths(window, stream)["pages"] / (
        f"page_offset_{offset:08d}_limit_{limit:05d}.json"
    )


def _normalise_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], int]:
    if "data" in payload or "resultMetadata" in payload:
        rows = (payload.get("data") or {}).get("rows")
        metadata = payload.get("resultMetadata") or {}
        columns = [
            str(item.get("name") if isinstance(item, dict) else item)
            for item in metadata.get("columns", [])
        ]
        total = metadata.get("totalRowCount")
        if not isinstance(rows, list) or not isinstance(total, int):
            raise RepresentativeAcquisitionError(
                "malformed typed Dune result page"
            )
        return rows, columns, total
    result = payload.get("result") or {}
    rows = result.get("rows")
    metadata = result.get("metadata") or {}
    columns = [
        str(item.get("name") if isinstance(item, dict) else item)
        for item in metadata.get("column_names", [])
    ]
    total = metadata.get("total_row_count")
    if not isinstance(rows, list) or not isinstance(total, int):
        raise RepresentativeAcquisitionError("malformed Dune result page")
    return rows, columns, total


def typed_result_file_metadata(path: Path) -> dict[str, Any]:
    """Read the bounded typed-result header without loading its row array."""
    marker = '"data":{"rows":['
    prefix = ""
    with path.open(encoding="utf-8") as handle:
        while marker not in prefix:
            chunk = handle.read(65_536)
            if not chunk:
                raise RepresentativeAcquisitionError(
                    "typed result has no row-array marker"
                )
            prefix += chunk
            if len(prefix) > 2_000_000:
                raise RepresentativeAcquisitionError(
                    "typed result header exceeds the bounded parser limit"
                )
    metadata_marker = '"resultMetadata":'
    metadata_start = prefix.find(metadata_marker)
    if metadata_start < 0:
        raise RepresentativeAcquisitionError(
            "typed result has no result metadata"
        )
    metadata, _ = json.JSONDecoder().raw_decode(
        prefix, metadata_start + len(metadata_marker)
    )
    execution_marker = '"executionId":'
    execution_start = prefix.find(execution_marker)
    state_marker = '"state":'
    state_start = prefix.find(state_marker)
    if execution_start < 0 or state_start < 0:
        raise RepresentativeAcquisitionError(
            "typed result lacks execution identity or state"
        )
    execution_id, _ = json.JSONDecoder().raw_decode(
        prefix, execution_start + len(execution_marker)
    )
    state, _ = json.JSONDecoder().raw_decode(
        prefix, state_start + len(state_marker)
    )
    return {
        "executionId": execution_id,
        "state": state,
        "resultMetadata": metadata,
    }


def iter_typed_result_rows(
    path: Path,
    *,
    read_size: int = 65_536,
) -> Iterator[dict[str, Any]]:
    """Yield typed-result rows with a bounded incremental JSON buffer."""
    marker = '"data":{"rows":['
    decoder = json.JSONDecoder()
    with path.open(encoding="utf-8") as handle:
        buffer = ""
        while marker not in buffer:
            chunk = handle.read(read_size)
            if not chunk:
                raise RepresentativeAcquisitionError(
                    "typed result is incomplete before its row array"
                )
            buffer += chunk
            marker_index = buffer.find(marker)
            if marker_index >= 0:
                buffer = buffer[marker_index + len(marker):]
                break
            if len(buffer) > 2_000_000:
                raise RepresentativeAcquisitionError(
                    "typed result row marker exceeds parser bound"
                )
        while True:
            buffer = buffer.lstrip()
            if buffer.startswith("]"):
                return
            if buffer.startswith(","):
                buffer = buffer[1:].lstrip()
            while True:
                try:
                    row, end = decoder.raw_decode(buffer)
                    break
                except json.JSONDecodeError:
                    chunk = handle.read(read_size)
                    if not chunk:
                        raise RepresentativeAcquisitionError(
                            "typed result ended during a row"
                        )
                    buffer += chunk
                    if len(buffer) > 4_000_000:
                        raise RepresentativeAcquisitionError(
                            "one typed-result row exceeds parser bound"
                        )
            if not isinstance(row, dict):
                raise RepresentativeAcquisitionError(
                    "typed result contains a non-object row"
                )
            yield row
            buffer = buffer[end:]


def classify_raw_mutation(row: dict[str, Any]) -> str:
    """Classify a raw call without treating fork or grab as owner frob flow."""
    call_type = str(row["call_type"])
    if call_type == "fork":
        return "fork"
    if call_type == "grab":
        return "grab"
    dink = int(str(row["dink_raw"]))
    dart = int(str(row["dart_raw"]))
    if dink and dart:
        return "combined_adjustment"
    if dink > 0:
        return "deposit"
    if dink < 0:
        return "withdrawal"
    if dart > 0:
        return "draw"
    if dart < 0:
        return "repayment"
    return "no_state_change"


def persist_recovered_typed_mutations(
    *,
    window: RepresentativeWindow,
    page_path: Path,
    usage_before: Decimal,
    usage_after: Decimal,
    local_flush_rows: int = 2_000,
    result_request_count_total: int = 1,
    new_recovery_request_used: bool = False,
    fail_after_rows: int | None = None,
) -> dict[str, Any]:
    """Promote a complete typed response through bounded local CSV writes."""
    page_path = page_path.resolve()
    if local_flush_rows < 1:
        raise RepresentativeAcquisitionError(
            "local flush row count must be positive"
        )
    header = typed_result_file_metadata(page_path)
    metadata = header["resultMetadata"]
    columns = tuple(item["name"] for item in metadata.get("columns", []))
    total = metadata.get("totalRowCount")
    if (
        header["executionId"] != "01KYFDPTRNR88V6GFBY26EF3QW"
        or header["state"] != "COMPLETED"
    ):
        raise RepresentativeAcquisitionError(
            "typed result does not match the completed recovery execution"
        )
    if columns != MUTATION_COLUMNS or not isinstance(total, int):
        raise RepresentativeAcquisitionError(
            "typed result schema or API total does not match the contract"
        )
    paths = stream_paths(window, "vat_mutations")
    final_path = paths["raw"]
    if final_path.exists():
        raise RepresentativeAcquisitionError(
            "authoritative Vat-mutation CSV already exists"
        )
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = final_path.parent / ".mutation_result.recovery.rows.tmp"
    invalid = final_path.parent / ".mutation_result.recovery.rows.tmp.invalid"
    if temporary.exists() or invalid.exists():
        raise RepresentativeAcquisitionError(
            "a recovery temporary file already exists"
        )
    count = 0
    try:
        with temporary.open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(MUTATION_COLUMNS),
                lineterminator="\n",
                extrasaction="raise",
            )
            writer.writeheader()
            for row in iter_typed_result_rows(page_path):
                if tuple(row) != MUTATION_COLUMNS:
                    raise RepresentativeAcquisitionError(
                        f"row {count} has a schema or column-order mismatch"
                    )
                writer.writerow(row)
                count += 1
                if count % local_flush_rows == 0:
                    handle.flush()
                    os.fsync(handle.fileno())
                if fail_after_rows is not None and count >= fail_after_rows:
                    raise RepresentativeAcquisitionError(
                        "injected incomplete-stream failure"
                    )
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if temporary.exists():
            os.replace(temporary, invalid)
            fsync_directory(invalid.parent)
        raise
    if count != total:
        os.replace(temporary, invalid)
        fsync_directory(invalid.parent)
        raise RepresentativeAcquisitionError(
            f"persisted {count} rows but API reported {total}"
        )
    with temporary.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != MUTATION_COLUMNS:
            raise RepresentativeAcquisitionError(
                "persisted CSV header does not match the mutation contract"
            )
        rows = list(reader)
    chunk = phase1e.MonthChunk(0, window.start, window.end)
    validation = phase1e.validate_mutations(rows, chunk)
    deterministic_keys = [
        phase1e.deterministic_mutation_key(row) for row in rows
    ]
    order_failure_count = sum(
        left > right
        for left, right in zip(
            deterministic_keys, deterministic_keys[1:], strict=False
        )
    )
    classifications: dict[str, int] = {}
    for row in rows:
        label = classify_raw_mutation(row)
        classifications[label] = classifications.get(label, 0) + 1
    unique_urns = {
        str(value).lower()
        for row in rows
        for value in (row["urn"], row["source_urn"], row["destination_urn"])
        if value
    }
    validation.update({
        "api_reported_total_rows": total,
        "persisted_row_count": count,
        "deterministic_order_failure_count": order_failure_count,
        "mutation_classifications": classifications,
        "unique_urn_count": len(unique_urns),
        "unique_transaction_count": len({
            row["transaction_hash"].lower() for row in rows
        }),
        "header_occurrence_count": 1,
    })
    validation["validation_passed"] = (
        validation["validation_passed"]
        and order_failure_count == 0
        and count == total
    )
    if not validation["validation_passed"]:
        write_json_atomic(paths["validation"], validation)
        os.replace(temporary, invalid)
        fsync_directory(invalid.parent)
        raise RepresentativeAcquisitionError(
            "; ".join(validation["failures"])
            or "recovered mutation validation failed"
        )
    os.replace(temporary, final_path)
    fsync_directory(final_path.parent)
    raw_sha256 = sha256_file(final_path)
    recovery_root = window_paths(window)["provenance"] / "mutations"
    recovery_metadata = {
        "window": window.key,
        "query_id": 8114886,
        "execution_id": header["executionId"],
        "execution_state": header["state"],
        "sql_sha256": (
            "07610636d78525d9d9e6410a69d592ed4c73b8887ba69e1900d9dcfd8c723058"
        ),
        "recovery_method": (
            "late completion of the original typed-response persistence; "
            "incremental local JSON consumption and bounded CSV flushing"
        ),
        "response_type": "typed MCP JSON result page",
        "new_recovery_result_request_used": new_recovery_request_used,
        "total_result_request_count": result_request_count_total,
        "local_flush_rows": local_flush_rows,
        "api_reported_total_rows": total,
        "persisted_rows": count,
        "column_count": len(MUTATION_COLUMNS),
        "result_schema": list(MUTATION_COLUMNS),
        "typed_response_path": relative(page_path),
        "typed_response_size_bytes": page_path.stat().st_size,
        "typed_response_sha256": sha256_file(page_path),
        "final_path": relative(final_path),
        "final_size_bytes": final_path.stat().st_size,
        "final_sha256": raw_sha256,
        "usage_before_recovery": str(usage_before),
        "usage_after_recovery": str(usage_after),
        "observed_recovery_delta": str(usage_after - usage_before),
        "original_execution_observed_delta": "0.665",
        "warnings": [
            "The authorised second result request was not consumed because "
            "the first request's asynchronous persistence completed late."
        ],
        "promoted_at_utc": utc_now(),
    }
    recovery_state = {
        "state": "complete",
        "validation_passed": True,
        "raw_file_persisted": True,
        "new_recovery_result_request_used": new_recovery_request_used,
        "total_result_request_count": result_request_count_total,
        "query_id": 8114886,
        "execution_id": header["executionId"],
        "raw_path": relative(final_path),
        "raw_sha256": raw_sha256,
    }
    write_json_atomic(recovery_root / "recovery.metadata.json", recovery_metadata)
    write_json_atomic(recovery_root / "recovery.validation.json", validation)
    write_json_atomic(recovery_root / "recovery.state.json", recovery_state)
    write_json_atomic(paths["validation"], validation)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    state.update({
        "state": "complete",
        "execution_state": "COMPLETED",
        "raw_file_persisted": True,
        "validation_passed": True,
        "raw_path": relative(final_path),
        "raw_sha256": raw_sha256,
        "row_count": count,
        "api_reported_total_rows": total,
        "result_retrieved": True,
        "retrieval_count": result_request_count_total,
        "new_recovery_result_request_used": new_recovery_request_used,
        "late_persistence_recovery": recovery_metadata,
        "completed_at_utc": utc_now(),
    })
    write_json_atomic(paths["state"], state)
    return {
        "metadata": recovery_metadata,
        "validation": validation,
        "state": recovery_state,
    }


def finalise_recovered_mutation_metadata(
    *,
    window: RepresentativeWindow,
    page_path: Path,
    usage_before: Decimal,
    usage_after: Decimal,
    local_flush_rows: int = 2_000,
) -> dict[str, Any]:
    """Finish provenance after a validated atomic promotion already succeeded."""
    page_path = page_path.resolve()
    header = typed_result_file_metadata(page_path)
    metadata = header["resultMetadata"]
    columns = tuple(item["name"] for item in metadata.get("columns", []))
    total = metadata.get("totalRowCount")
    paths = stream_paths(window, "vat_mutations")
    final_path = paths["raw"]
    if (
        header["executionId"] != "01KYFDPTRNR88V6GFBY26EF3QW"
        or header["state"] != "COMPLETED"
        or columns != MUTATION_COLUMNS
        or not isinstance(total, int)
        or not final_path.exists()
    ):
        raise RepresentativeAcquisitionError(
            "promoted recovery inputs do not match the authorised result"
        )
    with final_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != MUTATION_COLUMNS:
            raise RepresentativeAcquisitionError(
                "promoted recovery CSV schema is invalid"
            )
        rows = list(reader)
    if len(rows) != total:
        raise RepresentativeAcquisitionError(
            "promoted recovery CSV does not match the API total"
        )
    validation = phase1e.validate_mutations(
        rows, phase1e.MonthChunk(0, window.start, window.end)
    )
    keys = [phase1e.deterministic_mutation_key(row) for row in rows]
    order_failures = sum(
        left > right for left, right in zip(keys, keys[1:], strict=False)
    )
    classifications: dict[str, int] = {}
    for row in rows:
        label = classify_raw_mutation(row)
        classifications[label] = classifications.get(label, 0) + 1
    unique_urns = {
        str(value).lower()
        for row in rows
        for value in (row["urn"], row["source_urn"], row["destination_urn"])
        if value
    }
    validation.update({
        "api_reported_total_rows": total,
        "persisted_row_count": len(rows),
        "deterministic_order_failure_count": order_failures,
        "mutation_classifications": classifications,
        "unique_urn_count": len(unique_urns),
        "unique_transaction_count": len({
            row["transaction_hash"].lower() for row in rows
        }),
        "header_occurrence_count": 1,
    })
    validation["validation_passed"] = (
        validation["validation_passed"] and order_failures == 0
    )
    if not validation["validation_passed"]:
        raise RepresentativeAcquisitionError(
            "; ".join(validation["failures"])
            or "promoted mutation recovery failed revalidation"
        )
    raw_sha256 = sha256_file(final_path)
    recovery_root = window_paths(window)["provenance"] / "mutations"
    recovery_metadata = {
        "window": window.key,
        "query_id": 8114886,
        "execution_id": header["executionId"],
        "execution_state": header["state"],
        "sql_sha256": (
            "07610636d78525d9d9e6410a69d592ed4c73b8887ba69e1900d9dcfd8c723058"
        ),
        "recovery_method": (
            "late completion of the original typed-response persistence; "
            "incremental local JSON consumption with 2,000-row flushes"
        ),
        "response_type": "typed MCP JSON result page",
        "new_recovery_result_request_used": False,
        "total_result_request_count": 1,
        "local_flush_rows": local_flush_rows,
        "api_reported_total_rows": total,
        "persisted_rows": len(rows),
        "column_count": len(MUTATION_COLUMNS),
        "result_schema": list(MUTATION_COLUMNS),
        "typed_response_path": relative(page_path),
        "typed_response_size_bytes": page_path.stat().st_size,
        "typed_response_sha256": sha256_file(page_path),
        "final_path": relative(final_path),
        "final_size_bytes": final_path.stat().st_size,
        "final_sha256": raw_sha256,
        "usage_before_recovery": str(usage_before),
        "usage_after_recovery": str(usage_after),
        "observed_recovery_delta": str(usage_after - usage_before),
        "original_execution_observed_delta": "0.665",
        "metadata_finalisation_note": (
            "Atomic promotion and semantic validation completed before a "
            "relative-path provenance formatting error; this finalisation "
            "revalidated the unchanged promoted CSV."
        ),
        "warnings": [
            "The authorised second result request was not consumed because "
            "the first request's asynchronous persistence completed late."
        ],
        "promoted_at_utc": utc_now(),
    }
    recovery_state = {
        "state": "complete",
        "validation_passed": True,
        "raw_file_persisted": True,
        "new_recovery_result_request_used": False,
        "total_result_request_count": 1,
        "query_id": 8114886,
        "execution_id": header["executionId"],
        "raw_path": relative(final_path),
        "raw_sha256": raw_sha256,
    }
    write_json_atomic(recovery_root / "recovery.metadata.json", recovery_metadata)
    write_json_atomic(recovery_root / "recovery.validation.json", validation)
    write_json_atomic(recovery_root / "recovery.state.json", recovery_state)
    write_json_atomic(paths["validation"], validation)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    state.update({
        "state": "complete",
        "execution_state": "COMPLETED",
        "raw_file_persisted": True,
        "validation_passed": True,
        "raw_path": relative(final_path),
        "raw_sha256": raw_sha256,
        "row_count": len(rows),
        "api_reported_total_rows": total,
        "result_retrieved": True,
        "retrieval_count": 1,
        "new_recovery_result_request_used": False,
        "late_persistence_recovery": recovery_metadata,
        "completed_at_utc": utc_now(),
    })
    write_json_atomic(paths["state"], state)
    return {
        "metadata": recovery_metadata,
        "validation": validation,
        "state": recovery_state,
    }


def _parse_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def validate_boundary_rows(
    rows: list[dict[str, Any]], window: RepresentativeWindow
) -> dict[str, Any]:
    failures: list[str] = []
    keys: set[tuple[str, str]] = set()
    negative_count = 0
    for index, row in enumerate(rows):
        key = (str(row.get("ilk")), str(row.get("urn", "")).lower())
        if key in keys:
            failures.append(f"duplicate boundary urn at row {index}")
        keys.add(key)
        if key[0] not in TARGET_ILKS or not phase1e._address(key[1]):
            failures.append(f"invalid boundary identity at row {index}")
        if str(row.get("canonical_vat_contract", "")).lower() != CANONICAL_VAT:
            failures.append(f"non-canonical Vat at row {index}")
        try:
            values = [
                int(str(row[name]))
                for name in (
                    "opening_ink_raw", "opening_art_raw",
                    "end_ink_raw", "end_art_raw",
                )
            ]
            opening_rate = int(str(row["opening_rate_raw_ray"]))
            end_rate = int(str(row["end_rate_raw_ray"]))
            int(str(row["pre_window_mutation_count"]))
            int(str(row["window_mutation_count"]))
        except (TypeError, ValueError):
            failures.append(f"invalid integer boundary fields at row {index}")
            continue
        if any(value < 0 for value in values):
            negative_count += 1
            failures.append(f"negative boundary state at row {index}")
        if (values[1] and opening_rate <= 0) or (values[3] and end_rate <= 0):
            failures.append(f"missing effective rate for debt at row {index}")
        try:
            opening_rate_time = _parse_timestamp(
                row["opening_rate_effective_time_utc"]
            )
            end_rate_time = _parse_timestamp(
                row["end_rate_effective_time_utc"]
            )
            if opening_rate_time >= window.start or end_rate_time >= window.end:
                failures.append(f"future rate leakage at row {index}")
        except Exception:
            failures.append(f"invalid rate timestamp at row {index}")
    return {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(rows),
        "unique_ilk_urn_count": len(keys),
        "negative_state_count": negative_count,
        "target_ilks_observed": sorted({key[0] for key in keys}),
    }


def validate_ownership_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    source_keys: set[tuple[Any, ...]] = set()
    cdp_to_urn: dict[str, str] = {}
    for index, row in enumerate(rows):
        if row.get("record_type") not in {"open", "give"}:
            failures.append(f"invalid ownership type at row {index}")
        if row.get("ilk") not in TARGET_ILKS:
            failures.append(f"invalid ownership ilk at row {index}")
        if (
            str(row.get("manager_contract", "")).lower() != CANONICAL_MANAGER
            or not phase1e._truth(row.get("call_success"))
        ):
            failures.append(f"invalid manager source at row {index}")
        if not phase1e._address(row.get("urn")) or not phase1e._address(
            row.get("owner_or_proxy")
        ):
            failures.append(f"invalid ownership address at row {index}")
        try:
            position = phase1e.parsed_trace_position(
                row, "trace_position", allow_serialised_root=True
            )
            int(str(row["transaction_index"]))
            int(str(row["block_number"]))
        except Exception as error:
            failures.append(f"invalid ownership ordering at row {index}: {error}")
            continue
        key = (
            row["source_table"], str(row["transaction_hash"]).lower(),
            position, str(row["cdp_id"]),
        )
        if key in source_keys:
            failures.append(f"duplicate ownership source at row {index}")
        source_keys.add(key)
        cdp = str(row["cdp_id"])
        urn = str(row["urn"]).lower()
        if cdp in cdp_to_urn and cdp_to_urn[cdp] != urn:
            failures.append(f"CDP {cdp} maps to multiple urns")
        cdp_to_urn[cdp] = urn
    return {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(rows),
        "unique_cdp_count": len(cdp_to_urn),
        "open_count": sum(row.get("record_type") == "open" for row in rows),
        "give_count": sum(row.get("record_type") == "give" for row in rows),
    }


def validate_rate_rows(
    rows: list[dict[str, Any]], window: RepresentativeWindow
) -> dict[str, Any]:
    report = phase1e.validate_stream("rate", rows)
    failures = list(report["failures"])
    ordering: set[tuple[Any, ...]] = set()
    for index, row in enumerate(rows):
        try:
            timestamp = _parse_timestamp(row["effective_time_utc"])
            if timestamp >= window.end:
                failures.append(f"future rate at row {index}")
            key = (
                int(str(row["block_number"])),
                int(str(row["transaction_index"])),
                phase1e.parsed_trace_position(
                    row, "trace_position", allow_serialised_root=True
                ),
                str(row["transaction_hash"]).lower(),
                str(row["rate_record_type"]),
                str(row["ilk"]),
            )
            if key in ordering:
                failures.append(f"duplicate rate ordering key at row {index}")
            ordering.add(key)
        except Exception as error:
            failures.append(f"invalid rate ordering at row {index}: {error}")
    return {
        **report,
        "validation_passed": not failures,
        "failures": failures,
    }


def enforce_rate_repair_credit_gate(
    *,
    current_usage: Decimal,
    quota: Decimal,
    projected_cost: Decimal,
) -> dict[str, Any]:
    failures: list[str] = []
    if projected_cost > RATE_REPAIR_CREDIT_CAP:
        failures.append("projected rate repair exceeds 100 credits")
    if quota - current_usage - projected_cost < RATE_REPAIR_MINIMUM_REMAINING_QUOTA:
        failures.append("projected remaining quota falls below 1,400 credits")
    return {
        "passed": not failures,
        "failures": failures,
        "current_usage": str(current_usage),
        "projected_cost": str(projected_cost),
        "projected_remaining_quota": str(
            quota - current_usage - projected_cost
        ),
    }


def _raw_rate_order(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _parse_timestamp(row["effective_time_utc"]),
        int(str(row["block_number"])),
        int(str(row["transaction_index"])),
        phase1e.parsed_trace_position(
            row, "trace_position", allow_serialised_root=True
        ),
        str(row["transaction_hash"]).lower(),
        str(row["rate_record_type"]),
        str(row["ilk"]),
    )


def build_sparse_effective_rates(
    boundary_rows: list[dict[str, Any]],
    in_window_rows: list[dict[str, Any]],
    window: RepresentativeWindow,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Combine local exact opening rates with bounded observed rate calls."""
    failures: list[str] = []
    opening_by_ilk: dict[str, tuple[int, pd.Timestamp]] = {}
    ending_by_ilk: dict[str, int] = {}
    for row in boundary_rows:
        ilk = str(row["ilk"])
        candidate = (
            int(str(row["opening_rate_raw_ray"])),
            _parse_timestamp(row["opening_rate_effective_time_utc"]),
        )
        end_rate = int(str(row["end_rate_raw_ray"]))
        prior = opening_by_ilk.setdefault(ilk, candidate)
        if prior != candidate:
            failures.append(f"conflicting opening rate for {ilk}")
        prior_end = ending_by_ilk.setdefault(ilk, end_rate)
        if prior_end != end_rate:
            failures.append(f"conflicting ending rate for {ilk}")
    if set(opening_by_ilk) != set(TARGET_ILKS):
        failures.append("opening rates do not cover exactly the six target ilks")

    raw_validation = validate_rate_rows(in_window_rows, window)
    failures.extend(raw_validation["failures"])
    for index, row in enumerate(in_window_rows):
        timestamp = _parse_timestamp(row["effective_time_utc"])
        if not window.start <= timestamp < window.end:
            failures.append(f"out-of-window rate row {index}")

    rows: list[dict[str, Any]] = []
    current: dict[str, int] = {}
    for ilk in TARGET_ILKS:
        if ilk not in opening_by_ilk:
            continue
        rate, timestamp = opening_by_ilk[ilk]
        if rate <= 0 or timestamp >= window.start:
            failures.append(f"invalid opening rate boundary for {ilk}")
        current[ilk] = rate
        rows.append({
            "ilk": ilk,
            "effective_time_utc": timestamp.isoformat(),
            "block_number": "",
            "transaction_index": "",
            "trace_position": "",
            "transaction_hash": "",
            "source_type": "opening_rate",
            "previous_rate_raw_ray": "",
            "resulting_rate_raw_ray": str(rate),
            "raw_rate_delta": "",
            "opening_state_flag": True,
            "observed_call_flag": True,
            "provenance_classification":
                "local_boundary_latest_pre_window_jug_drip",
            "source_contract": CANONICAL_JUG,
            "source_table": (
                f"{window.key}_boundary_states.opening_rate_raw_ray"
            ),
        })

    ordered = sorted(in_window_rows, key=_raw_rate_order)
    transaction_groups: dict[
        tuple[int, int, str, str], list[dict[str, Any]]
    ] = {}
    for row in ordered:
        transaction_groups.setdefault((
            int(str(row["block_number"])),
            int(str(row["transaction_index"])),
            str(row["transaction_hash"]).lower(),
            str(row["ilk"]),
        ), []).append(row)

    reconciliation_failures = 0
    matched_fold_keys: set[tuple[str, str, tuple[int, ...]]] = set()
    for key, group in transaction_groups.items():
        ilk = key[3]
        drips = [row for row in group if row["rate_record_type"] == "drip"]
        folds = [row for row in group if row["rate_record_type"] == "fold"]
        fold_by_parent: dict[tuple[int, ...], list[dict[str, Any]]] = {}
        for fold in folds:
            position = phase1e.parsed_trace_position(
                fold, "trace_position", allow_serialised_root=True
            )
            fold_by_parent.setdefault(position[:-1], []).append(fold)
        for drip in sorted(drips, key=_raw_rate_order):
            before = current.get(ilk)
            if before is None:
                failures.append(
                    f"no opening rate before observed calls for {ilk}"
                )
                continue
            drip_position = phase1e.parsed_trace_position(
                drip, "trace_position", allow_serialised_root=True
            )
            matches = fold_by_parent.get(drip_position, [])
            if len(matches) != 1:
                failures.append(
                    f"drip has {len(matches)} direct fold children "
                    f"for {key[2]}:{ilk}:{drip_position}"
                )
                continue
            fold = matches[0]
            fold_position = phase1e.parsed_trace_position(
                fold, "trace_position", allow_serialised_root=True
            )
            matched_fold_keys.add((key[2], ilk, fold_position))
            after = int(str(drip["raw_rate_ray"]))
            delta = int(str(fold["raw_rate_delta"]))
            if before + delta != after:
                reconciliation_failures += 1
                failures.append(
                    f"fold/drip reconciliation failed for "
                    f"{key[2]}:{ilk}:{drip_position}"
                )
            if after <= 0:
                failures.append(
                    f"non-positive resulting rate for {key[2]}:{ilk}"
                )
            for raw in (drip, fold):
                rows.append({
                    "ilk": ilk,
                    "effective_time_utc": _parse_timestamp(
                        raw["effective_time_utc"]
                    ).isoformat(),
                    "block_number": str(raw["block_number"]),
                    "transaction_index": str(raw["transaction_index"]),
                    "trace_position": str(raw["trace_position"]),
                    "transaction_hash": str(raw["transaction_hash"]).lower(),
                    "source_type": str(raw["rate_record_type"]),
                    "previous_rate_raw_ray": str(before),
                    "resulting_rate_raw_ray": str(after),
                    "raw_rate_delta": (
                        str(raw["raw_rate_delta"])
                        if raw["rate_record_type"] == "fold" else ""
                    ),
                    "opening_state_flag": False,
                    "observed_call_flag": True,
                    "provenance_classification":
                        "bounded_in_window_decoded_call",
                    "source_contract": str(raw["source_contract"]).lower(),
                    "source_table": str(raw["source_table"]),
                })
            current[ilk] = after
    for row in ordered:
        if row["rate_record_type"] != "fold":
            continue
        fold_key = (
            str(row["transaction_hash"]).lower(),
            str(row["ilk"]),
            phase1e.parsed_trace_position(
                row, "trace_position", allow_serialised_root=True
            ),
        )
        if fold_key not in matched_fold_keys:
            failures.append(
                f"unmatched fold {fold_key[0]}:{fold_key[1]}:{fold_key[2]}"
            )

    end_rate_mismatches = {
        ilk: {"reconstructed": current.get(ilk), "boundary": expected}
        for ilk, expected in ending_by_ilk.items()
        if current.get(ilk) != expected
    }
    if end_rate_mismatches:
        failures.append("reconstructed ending rates differ from boundary rates")

    return rows, {
        "validation_passed": not failures,
        "failures": failures,
        "row_count": len(rows),
        "opening_row_count": sum(
            bool(row["opening_state_flag"]) for row in rows
        ),
        "in_window_source_row_count": len(in_window_rows),
        "drip_count": sum(
            row["rate_record_type"] == "drip" for row in in_window_rows
        ),
        "fold_count": sum(
            row["rate_record_type"] == "fold" for row in in_window_rows
        ),
        "fold_drip_reconciliation_failure_count": reconciliation_failures,
        "end_rate_mismatches": end_rate_mismatches,
        "opening_rates": {
            ilk: {
                "raw_rate_ray": str(value[0]),
                "effective_time_utc": value[1].isoformat(),
            }
            for ilk, value in opening_by_ilk.items()
        },
        "ending_rates": {
            ilk: str(value) for ilk, value in ending_by_ilk.items()
        },
    }


def validate_stream_rows(
    stream: str,
    rows: list[dict[str, Any]],
    window: RepresentativeWindow,
) -> dict[str, Any]:
    if stream == "boundary_states":
        return validate_boundary_rows(rows, window)
    if stream == "vat_mutations":
        pseudo = phase1e.MonthChunk(0, window.start, window.end)
        return phase1e.validate_mutations(rows, pseudo)
    if stream == "ownership_history":
        return validate_ownership_rows(rows)
    if stream == "effective_rates":
        return validate_rate_rows(rows, window)
    raise RepresentativeAcquisitionError(f"unknown stream {stream}")


def persist_pages(
    window: RepresentativeWindow,
    stream: str,
    *,
    usage_after: Decimal,
) -> dict[str, Any]:
    paths = stream_paths(window, stream)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    total = int(state["api_reported_total_rows"])
    pages: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    columns: list[str] | None = None
    for offset, limit in page_plan(total):
        path = page_path(window, stream, offset, limit)
        if not path.exists():
            raise RepresentativeAcquisitionError(
                f"missing result page at offset {offset}"
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        page_rows, page_columns, page_total = _normalise_page(payload)
        expected_count = total if total == 0 else min(limit, total - offset)
        if page_total != total or len(page_rows) != expected_count:
            raise RepresentativeAcquisitionError(
                f"inconsistent page at offset {offset}"
            )
        if columns is None:
            columns = page_columns
        elif columns != page_columns:
            raise RepresentativeAcquisitionError("page schema changed")
        pages.append({
            "path": relative(path),
            "offset": offset,
            "limit": limit,
            "returned_rows": len(page_rows),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        })
        rows.extend(page_rows)
    expected_columns = list(STREAM_COLUMNS[stream])
    if columns != expected_columns:
        raise RepresentativeAcquisitionError(
            f"unexpected {stream} columns: {columns}"
        )
    validation = validate_stream_rows(stream, rows, window)
    write_json_atomic(paths["validation"], validation)
    if not validation["validation_passed"]:
        raise RepresentativeAcquisitionError("; ".join(validation["failures"]))
    write_csv_atomic(paths["raw"], expected_columns, rows)
    sparse_metadata: dict[str, Any] | None = None
    if stream == "effective_rates":
        boundary_path = stream_paths(window, "boundary_states")["raw"]
        if not boundary_path.exists():
            raise RepresentativeAcquisitionError(
                "boundary states must be persisted before sparse rates"
            )
        sparse_rows, sparse_validation = build_sparse_effective_rates(
            load_csv(boundary_path), rows, window
        )
        if not sparse_validation["validation_passed"]:
            raise RepresentativeAcquisitionError(
                "; ".join(sparse_validation["failures"])
            )
        sparse_path = window_paths(window)["processed"] / "effective_rates.csv"
        write_csv_atomic(sparse_path, SPARSE_RATE_COLUMNS, sparse_rows)
        validation["sparse_rate_validation"] = sparse_validation
        validation["processed_sparse_path"] = relative(sparse_path)
        validation["processed_sparse_sha256"] = sha256_file(sparse_path)
        sparse_metadata = {
            "path": relative(sparse_path),
            "rows": len(sparse_rows),
            "columns": len(SPARSE_RATE_COLUMNS),
            "size_bytes": sparse_path.stat().st_size,
            "sha256": sha256_file(sparse_path),
            "method": (
                "Method B: boundary opening rates plus bounded in-window "
                "Jug.drip/Vat.fold calls"
            ),
        }
        write_json_atomic(paths["validation"], validation)
    metadata = {
        "window": window.key,
        "stream": stream,
        "query_id": state["query_id"],
        "query_url": state["query_url"],
        "execution_id": state["execution_id"],
        "sql_path": state["sql_path"],
        "sql_sha256": state["sql_sha256"],
        "start_utc": window.start.isoformat(),
        "end_exclusive_utc": window.end.isoformat(),
        "row_count": len(rows),
        "column_count": len(expected_columns),
        "raw_path": relative(paths["raw"]),
        "raw_size_bytes": paths["raw"].stat().st_size,
        "raw_sha256": sha256_file(paths["raw"]),
        "pages": pages,
        "retrieval_count": len(pages),
        "usage_before": state["usage_before"],
        "usage_after": str(usage_after),
        "observed_credit_delta": str(
            usage_after - Decimal(state["usage_before"])
        ),
        "execution_cost_credits": state.get("execution_cost_credits"),
        "validation_status": "passed",
        "persisted_at_utc": utc_now(),
    }
    if sparse_metadata is not None:
        metadata["processed_sparse_rates"] = sparse_metadata
    write_json_atomic(paths["metadata"], metadata)
    state.update({
        "state": "complete",
        "execution_state": "COMPLETED",
        "retrieval_count": len(pages),
        "validation_passed": True,
        "raw_file_persisted": True,
        "row_count": len(rows),
        "raw_path": metadata["raw_path"],
        "raw_sha256": metadata["raw_sha256"],
        "usage_after": str(usage_after),
        "observed_credit_delta": metadata["observed_credit_delta"],
        "completed_at_utc": utc_now(),
    })
    write_json_atomic(paths["state"], state)
    return {"state": state, "metadata": metadata, "validation": validation}


def enforce_credit_gate(
    *,
    starting_usage: Decimal,
    current_usage: Decimal,
    quota: Decimal,
    projected_remaining_cost: Decimal,
) -> dict[str, Any]:
    observed = current_usage - starting_usage
    projected_usage = current_usage + projected_remaining_cost
    failures: list[str] = []
    if observed >= TRANCHE_CREDIT_CAP:
        failures.append("tranche credit cap reached")
    if projected_usage > starting_usage + TRANCHE_CREDIT_CAP:
        failures.append("projected tranche cost exceeds 600 credits")
    if quota - projected_usage < MINIMUM_REMAINING_QUOTA:
        failures.append("projected remaining quota falls below 800 credits")
    return {
        "passed": not failures,
        "failures": failures,
        "observed_tranche_usage": str(observed),
        "projected_remaining_cost": str(projected_remaining_cost),
        "projected_remaining_quota": str(quota - projected_usage),
    }


def enforce_usdc_svb_credit_gate(
    *,
    starting_usage: Decimal,
    current_usage: Decimal,
    quota: Decimal,
    projected_remaining_cost: Decimal,
    last_query_observed_cost: Decimal | None = None,
    last_query_estimated_cost: Decimal | None = None,
) -> dict[str, Any]:
    """Apply the authorised USDC/SVB tranche and reserve limits."""
    observed = current_usage - starting_usage
    projected_usage = current_usage + projected_remaining_cost
    failures: list[str] = []
    if observed >= USDC_SVB_CREDIT_CAP:
        failures.append("USDC/SVB observed credit cap reached")
    if observed + projected_remaining_cost > USDC_SVB_CREDIT_CAP:
        failures.append("projected USDC/SVB cost exceeds 180 credits")
    if quota - projected_usage < USDC_SVB_MINIMUM_REMAINING_QUOTA:
        failures.append("projected remaining quota falls below 1,350 credits")
    if last_query_observed_cost is not None:
        if last_query_observed_cost > Decimal("80"):
            failures.append("last query exceeded 80 observed credits")
        if (
            last_query_estimated_cost is not None
            and last_query_observed_cost > 2 * last_query_estimated_cost
        ):
            failures.append("last query exceeded twice its pre-query estimate")
    return {
        "passed": not failures,
        "failures": failures,
        "starting_usage": str(starting_usage),
        "current_usage": str(current_usage),
        "observed_usage": str(observed),
        "projected_remaining_cost": str(projected_remaining_cost),
        "projected_remaining_quota": str(quota - projected_usage),
    }


def enforce_terra_cefi_credit_gate(
    *,
    starting_usage: Decimal,
    current_usage: Decimal,
    quota: Decimal,
    projected_remaining_cost: Decimal,
    last_query_observed_cost: Decimal | None = None,
    last_query_estimated_cost: Decimal | None = None,
) -> dict[str, Any]:
    """Enforce the authorised Terra/CeFi cap, reserve and query stop."""
    observed = current_usage - starting_usage
    projected_usage = current_usage + projected_remaining_cost
    failures: list[str] = []
    if observed >= TERRA_CEFI_CREDIT_CAP:
        failures.append("Terra/CeFi observed credit cap reached")
    if observed + projected_remaining_cost > TERRA_CEFI_CREDIT_CAP:
        failures.append("projected Terra/CeFi cost exceeds 300 credits")
    if quota - projected_usage < TERRA_CEFI_MINIMUM_REMAINING_QUOTA:
        failures.append("projected remaining quota falls below 1,100 credits")
    if last_query_observed_cost is not None:
        if last_query_observed_cost > TERRA_CEFI_PER_QUERY_CREDIT_CAP:
            failures.append("last query exceeded 100 observed credits")
        if (
            last_query_estimated_cost is not None
            and last_query_observed_cost > 2 * last_query_estimated_cost
        ):
            failures.append("last query exceeded twice its pre-query estimate")
    return {
        "passed": not failures,
        "failures": failures,
        "starting_usage": str(starting_usage),
        "current_usage": str(current_usage),
        "observed_usage": str(observed),
        "projected_remaining_cost": str(projected_remaining_cost),
        "projected_remaining_quota": str(quota - projected_usage),
    }


def enforce_terra_continuation_credit_gate(
    *,
    starting_usage: Decimal,
    current_usage: Decimal,
    quota: Decimal,
    projected_remaining_cost: Decimal,
    stream: str | None = None,
    last_query_observed_cost: Decimal | None = None,
    last_query_estimated_cost: Decimal | None = None,
) -> dict[str, Any]:
    """Enforce the ownership/rate continuation cap and 1,250-credit reserve."""
    observed = current_usage - starting_usage
    projected_usage = current_usage + projected_remaining_cost
    failures: list[str] = []
    if observed >= TERRA_CONTINUATION_CREDIT_CAP:
        failures.append("Terra continuation observed credit cap reached")
    if observed + projected_remaining_cost > TERRA_CONTINUATION_CREDIT_CAP:
        failures.append("projected Terra continuation cost exceeds 180 credits")
    if quota - projected_usage < TERRA_CONTINUATION_MINIMUM_REMAINING_QUOTA:
        failures.append("projected remaining quota falls below 1,250 credits")
    if last_query_observed_cost is not None:
        stream_limit = (
            TERRA_RATE_QUERY_CREDIT_CAP
            if stream == "effective_rates"
            else TERRA_OWNERSHIP_QUERY_CREDIT_CAP
        )
        if last_query_observed_cost > stream_limit:
            failures.append(
                f"{stream or 'last'} query exceeded {stream_limit} credits"
            )
        if (
            last_query_estimated_cost is not None
            and last_query_observed_cost > 2 * last_query_estimated_cost
        ):
            failures.append("last query exceeded twice its pre-query estimate")
    return {
        "passed": not failures,
        "failures": failures,
        "starting_usage": str(starting_usage),
        "current_usage": str(current_usage),
        "observed_usage": str(observed),
        "projected_remaining_cost": str(projected_remaining_cost),
        "projected_remaining_quota": str(quota - projected_usage),
    }


def validate_active_ilks(
    window: RepresentativeWindow,
    protocol: pd.DataFrame,
) -> dict[str, Any]:
    """Require every authorised ilk to be active at both window boundaries."""
    frame = protocol.copy()
    frame["timestamp_utc"] = pd.to_datetime(
        frame["timestamp_utc"], utc=True
    )
    checks: dict[str, dict[str, bool]] = {}
    failures: list[str] = []
    for label, timestamp in (
        ("opening", window.start),
        ("closing", window.end - pd.Timedelta(hours=1)),
    ):
        boundary = frame.loc[frame["timestamp_utc"].eq(timestamp)]
        checks[label] = {}
        for ilk in TARGET_ILKS:
            rows = boundary.loc[boundary["ilk"].eq(ilk)]
            active = (
                len(rows) == 1
                and str(rows.iloc[0]["ilk_active"]).strip().lower()
                in {"true", "1"}
            )
            checks[label][ilk] = active
            if not active:
                failures.append(f"{ilk} is not active at {label} boundary")
    return {
        "validation_passed": not failures,
        "checks": checks,
        "failures": failures,
    }


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def extract_barks(window: RepresentativeWindow) -> list[dict[str, Any]]:
    transaction_indices = {
        row["tx_hash"].lower(): row["transaction_index"]
        for row in load_csv(LIQUIDATION_TRANSACTIONS_PATH)
    }
    rows: list[dict[str, Any]] = []
    with LIQUIDATION_ACTIONS_PATH.open(
        newline="", encoding="utf-8"
    ) as handle:
        for row in csv.DictReader(handle):
            if row["record_type"] != "bark_event" or row["ilk"] not in TARGET_ILKS:
                continue
            timestamp = _parse_timestamp(row["block_time"])
            if not window.start <= timestamp < window.end:
                continue
            transaction_hash = row["tx_hash"].lower()
            transaction_index = (
                row["transaction_index"]
                or transaction_indices.get(transaction_hash, "")
            )
            if not transaction_index:
                raise RepresentativeAcquisitionError(
                    f"Phase 1C transaction index missing for {transaction_hash}"
                )
            rows.append({
                "block_time_utc": timestamp.isoformat(),
                "block_number": row["block_number"],
                "transaction_hash": transaction_hash,
                "transaction_index": transaction_index,
                "event_index": row["event_index"],
                "ilk": row["ilk"],
                "urn": row["urn"].lower(),
                "auction_id": row["auction_id"],
                "keeper": row["kpr"].lower() if row["kpr"] else "",
                "dog_contract": row["dog_contract"].lower(),
                "clipper_contract": row["clipper_contract"].lower(),
                "ink_raw": row["ink_raw"],
                "art_raw": row["art_raw"],
                "due_raw": row["due_raw"],
                "source_table": row["source_table"],
            })
    rows.sort(key=lambda row: (
        int(row["block_number"]), int(row["transaction_index"]),
        int(row["event_index"]), row["transaction_hash"],
    ))
    return rows


def extract_phase1c_auctions(
    window: RepresentativeWindow,
) -> list[dict[str, str]]:
    """Select validated Phase 1C auctions initiated in the bounded window."""
    rows = load_csv(LIQUIDATION_AUCTIONS_PATH)
    selected: list[dict[str, str]] = []
    for row in rows:
        if row["ilk"] not in TARGET_ILKS:
            continue
        timestamp = _parse_timestamp(row["bark_time_utc"])
        if window.start <= timestamp < window.end:
            selected.append(row)
    selected.sort(key=lambda row: (
        _parse_timestamp(row["bark_time_utc"]),
        row["clipper_contract"].lower(),
        int(row["auction_id"]),
    ))
    return selected


def validate_bark_grab_rows(
    barks: list[dict[str, Any]],
    mutations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate deterministic Bark-to-grab linkage without adding state deltas."""
    bark_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for bark in barks:
        key = (
            bark["transaction_hash"].lower(), bark["ilk"], bark["urn"].lower()
        )
        bark_by_key.setdefault(key, []).append(bark)
    matched_barks: set[tuple[str, str, str, str]] = set()
    matched_grabs = 0
    ambiguous: list[str] = []
    unmatched_grabs: list[str] = []
    grabs = [row for row in mutations if row["call_type"] == "grab"]
    for grab in grabs:
        key = (
            grab["transaction_hash"].lower(),
            grab["ilk"],
            grab["urn"].lower(),
        )
        exact = [
            bark for bark in bark_by_key.get(key, [])
            if int(grab["dink_raw"]) == -int(bark["ink_raw"])
            and int(grab["dart_raw"]) == -int(bark["art_raw"])
        ]
        if len(exact) == 1:
            matched_grabs += 1
            matched_barks.add((
                exact[0]["transaction_hash"], exact[0]["ilk"],
                exact[0]["urn"], exact[0]["auction_id"],
            ))
        elif len(exact) > 1:
            ambiguous.append(
                f"{grab['transaction_hash']}:{grab['ilk']}:{grab['urn']}"
            )
        else:
            unmatched_grabs.append(
                f"{grab['transaction_hash']}:{grab['ilk']}:{grab['urn']}"
            )
    unmatched_barks = [
        (
            bark["transaction_hash"], bark["ilk"], bark["urn"],
            bark["auction_id"],
        )
        for bark in barks
        if (
            bark["transaction_hash"], bark["ilk"], bark["urn"],
            bark["auction_id"],
        ) not in matched_barks
    ]
    return {
        "validation_passed": (
            not ambiguous and not unmatched_grabs and not unmatched_barks
        ),
        "bark_count": len(barks),
        "grab_count": len(grabs),
        "matched_bark_count": len(matched_barks),
        "matched_grab_count": matched_grabs,
        "unmatched_bark_count": len(unmatched_barks),
        "unmatched_grab_count": len(unmatched_grabs),
        "ambiguous_link_count": len(ambiguous),
        "unmatched_barks": unmatched_barks[:100],
        "unmatched_grabs": unmatched_grabs[:100],
        "ambiguous_links": ambiguous[:100],
        "amount_rule": (
            "grab.dink = -Bark.ink and grab.dart = -Bark.art"
        ),
        "economic_treatment": (
            "Vat.grab is the mutation; Dog.Bark is annotation only"
        ),
    }


def persist_local_bark_annotations(
    window: RepresentativeWindow,
) -> dict[str, Any]:
    """Extract and validate bounded Bark annotations from Phase 1C locally."""
    mutation_path = stream_paths(window, "vat_mutations")["raw"]
    if not mutation_path.exists():
        raise RepresentativeAcquisitionError(
            "Vat mutations must be persisted before Bark validation"
        )
    mutations = load_csv(mutation_path)
    barks = extract_barks(window)
    validation = validate_bark_grab_rows(barks, mutations)
    base = window_paths(window)
    output = base["processed"] / "bark_annotations.csv"
    write_csv_atomic(output, BARK_COLUMNS, barks)
    metadata = {
        "window": window.key,
        "start_utc": window.start.isoformat(),
        "end_exclusive_utc": window.end.isoformat(),
        "source_path": relative(LIQUIDATION_ACTIONS_PATH),
        "source_sha256": sha256_file(LIQUIDATION_ACTIONS_PATH),
        "output_path": relative(output),
        "output_sha256": sha256_file(output),
        "output_size_bytes": output.stat().st_size,
        "row_count": len(barks),
        "dune_execution_count": 0,
        "created_at_utc": utc_now(),
    }
    write_json_atomic(
        base["provenance"] / "bark_annotations.validation.json", validation
    )
    write_json_atomic(
        base["provenance"] / "bark_annotations.metadata.json", metadata
    )
    write_json_atomic(base["provenance"] / "bark_annotations.state.json", {
        "state": "complete" if validation["validation_passed"] else "failed",
        "validation_passed": validation["validation_passed"],
        "local_source_only": True,
        "query_id": None,
        "execution_id": None,
        "completed_at_utc": utc_now(),
    })
    if not validation["validation_passed"]:
        raise RepresentativeAcquisitionError(
            "Bark/grab linkage validation failed"
        )
    return {"metadata": metadata, "validation": validation}


def _ownership_at(
    ownership: list[dict[str, str]], urn: str, timestamp: pd.Timestamp
) -> tuple[str, str]:
    candidates = [
        row for row in ownership
        if row["urn"].lower() == urn.lower()
        and _parse_timestamp(row["effective_time_utc"]) <= timestamp
    ]
    if not candidates:
        return "", ""
    candidates.sort(key=lambda row: (
        int(row["block_number"]), int(row["transaction_index"]),
        phase1e.parsed_trace_position(
            row, "trace_position", allow_serialised_root=True
        ),
        row["transaction_hash"].lower(), row["record_type"],
    ))
    latest = candidates[-1]
    return latest["cdp_id"], latest["owner_or_proxy"].lower()


def _rate_at(
    rates: list[dict[str, str]],
    ilk: str,
    timestamp: pd.Timestamp,
    *,
    block_number: int | None = None,
    transaction_index: int | None = None,
    trace_position: tuple[int, ...] | None = None,
) -> int | None:
    def is_effective(row: dict[str, str]) -> bool:
        row_timestamp = _parse_timestamp(row["effective_time_utc"])
        if row_timestamp < timestamp:
            return True
        if row_timestamp > timestamp:
            return False
        if block_number is None or not row.get("block_number"):
            return True
        row_key = (
            int(row["block_number"]),
            int(row["transaction_index"]),
            phase1e.parsed_trace_position(
                row, "trace_position", allow_serialised_root=True
            ),
        )
        event_key = (
            block_number,
            transaction_index if transaction_index is not None else 2**63,
            trace_position if trace_position is not None else (2**63,),
        )
        return row_key <= event_key

    candidates = []
    for row in rates:
        if row["ilk"] != ilk:
            continue
        if "source_type" in row:
            if row["source_type"] not in {"opening_rate", "drip", "fold"}:
                continue
        elif row["rate_record_type"] != "drip":
            continue
        if is_effective(row):
            candidates.append(row)
    if not candidates:
        return None

    def key(row: dict[str, str]) -> tuple[Any, ...]:
        if not row.get("block_number"):
            return (
                _parse_timestamp(row["effective_time_utc"]),
                -1, -1, (), "", str(row.get("source_type", "")),
            )
        return (
            _parse_timestamp(row["effective_time_utc"]),
            int(row["block_number"]),
            int(row["transaction_index"]),
            phase1e.parsed_trace_position(
                row, "trace_position", allow_serialised_root=True
            ),
            row["transaction_hash"].lower(),
            str(row.get("source_type", row.get("rate_record_type", ""))),
        )

    candidates.sort(key=key)
    selected = candidates[-1]
    if "resulting_rate_raw_ray" in selected:
        return int(selected["resulting_rate_raw_ray"])
    return int(selected["raw_rate_ray"])


def _price_and_ratio_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    market = pd.read_csv(MARKET_PATH)
    market["timestamp_utc"] = pd.to_datetime(
        market["timestamp_utc"], utc=True
    )
    market = market.set_index("timestamp_utc")
    protocol = pd.read_csv(PROTOCOL_PATH, low_memory=False)
    protocol["timestamp_utc"] = pd.to_datetime(
        protocol["timestamp_utc"], utc=True
    )
    protocol = protocol.set_index(["timestamp_utc", "ilk"])
    return market, protocol


def _enriched_state(
    *,
    window: RepresentativeWindow,
    timestamp: pd.Timestamp,
    ilk: str,
    urn: str,
    ink_raw: int,
    art_raw: int,
    rate_raw: int,
    ownership: list[dict[str, str]],
    market: pd.DataFrame,
    protocol: pd.DataFrame,
    state_label: str,
) -> dict[str, Any]:
    hour = timestamp.floor("h")
    price_column = "eth_price_usd" if ilk.startswith("ETH-") else "wbtc_price_usd"
    price = Decimal(str(market.loc[hour, price_column]))
    liquidation_ratio = Decimal(
        str(protocol.loc[(hour, ilk), "liquidation_ratio"])
    )
    debt = Decimal(art_raw) * Decimal(rate_raw) / Decimal(10**45)
    collateral = Decimal(ink_raw) / Decimal(10**18)
    value = collateral * price
    ratio = None if debt == 0 else value / debt
    cdp_id, owner = _ownership_at(ownership, urn, timestamp)
    return {
        "window": window.key,
        "state_label": state_label,
        "timestamp_utc": timestamp.isoformat(),
        "ilk": ilk,
        "urn": urn,
        "ink_raw": str(ink_raw),
        "art_raw": str(art_raw),
        "rate_raw_ray": str(rate_raw),
        "collateral_amount": str(collateral),
        "normalised_debt": str(Decimal(art_raw) / Decimal(10**18)),
        "debt_dai": str(debt),
        "collateral_price_usd": str(price),
        "collateral_value_usd": str(value),
        "collateral_ratio": "" if ratio is None else str(ratio),
        "liquidation_ratio": str(liquidation_ratio),
        "cdp_id": cdp_id,
        "owner_or_proxy": owner,
        "active": ink_raw != 0 or art_raw != 0,
    }


STATE_COLUMNS = (
    "window", "state_label", "timestamp_utc", "ilk", "urn", "ink_raw",
    "art_raw", "rate_raw_ray", "collateral_amount", "normalised_debt",
    "debt_dai", "collateral_price_usd", "collateral_value_usd",
    "collateral_ratio", "liquidation_ratio", "cdp_id", "owner_or_proxy",
    "active",
)
EVENT_COLUMNS = (
    "window", "timestamp_utc", "block_number", "transaction_index",
    "transaction_hash", "trace_position", "ilk", "urn", "cdp_id",
    "owner_or_proxy", "mutation_type", "fork_side", "dink_raw", "dart_raw",
    "mutation_classification",
    "ink_after_raw", "art_after_raw", "rate_raw_ray", "debt_after_dai",
    "collateral_ratio_after", "liquidation_flag", "auction_id", "keeper",
    "source_call_type", "source_contract", "source_table",
    "observed_or_derived",
)
CLOSE_FACTOR_COLUMNS = (
    "window", "timestamp_utc", "block_number", "transaction_index",
    "transaction_hash", "trace_position", "ilk", "urn", "auction_id",
    "keeper", "pre_grab_ink_raw", "pre_grab_art_raw", "grab_dink_raw",
    "grab_dart_raw", "post_grab_ink_raw", "post_grab_art_raw",
    "rate_raw_ray", "debt_reduction_dai", "debt_close_fraction",
    "collateral_close_fraction", "full_debt_closure",
    "full_collateral_removal", "bark_linkage", "model_semantic_mapping",
)


def liquidation_close_fraction_metrics(
    *,
    pre_ink_raw: int,
    pre_art_raw: int,
    dink_raw: int,
    dart_raw: int,
    rate_raw_ray: int,
) -> dict[str, Any]:
    """Calculate the simulator-aligned debt fraction and collateral analogue."""
    if pre_ink_raw < 0 or pre_art_raw < 0 or rate_raw_ray <= 0:
        raise RepresentativeAcquisitionError("invalid pre-grab state or rate")
    post_ink = pre_ink_raw + dink_raw
    post_art = pre_art_raw + dart_raw
    if dink_raw > 0 or dart_raw > 0 or post_ink < 0 or post_art < 0:
        raise RepresentativeAcquisitionError(
            "grab must remove state without producing a negative balance"
        )
    debt_fraction = (
        None
        if pre_art_raw == 0
        else Decimal(abs(dart_raw)) / Decimal(pre_art_raw)
    )
    collateral_fraction = (
        None
        if pre_ink_raw == 0
        else Decimal(abs(dink_raw)) / Decimal(pre_ink_raw)
    )
    return {
        "post_grab_ink_raw": post_ink,
        "post_grab_art_raw": post_art,
        "debt_reduction_dai": str(
            Decimal(abs(dart_raw)) * Decimal(rate_raw_ray) / Decimal(10**45)
        ),
        "debt_close_fraction": (
            "" if debt_fraction is None else str(debt_fraction)
        ),
        "collateral_close_fraction": (
            "" if collateral_fraction is None else str(collateral_fraction)
        ),
        "full_debt_closure": bool(pre_art_raw > 0 and post_art == 0),
        "full_collateral_removal": bool(pre_ink_raw > 0 and post_ink == 0),
    }


def cluster_liquidation_sequences(
    close_factors: list[dict[str, Any]],
    *,
    maximum_gap: pd.Timedelta = pd.Timedelta(hours=1),
) -> list[dict[str, Any]]:
    """Group chronologically adjacent grabs without claiming causal episodes."""
    ordered = sorted(
        close_factors,
        key=lambda row: (
            _parse_timestamp(row["timestamp_utc"]),
            int(row["block_number"]),
            int(row["transaction_index"]),
            phase1e.parsed_trace_position(
                row, "trace_position", allow_serialised_root=True
            ),
            row["transaction_hash"],
        ),
    )
    groups: list[list[dict[str, Any]]] = []
    for row in ordered:
        timestamp = _parse_timestamp(row["timestamp_utc"])
        if (
            not groups
            or timestamp - _parse_timestamp(
                groups[-1][-1]["timestamp_utc"]
            ) > maximum_gap
        ):
            groups.append([row])
        else:
            groups[-1].append(row)
    summaries: list[dict[str, Any]] = []
    for index, values in enumerate(groups, start=1):
        start = _parse_timestamp(values[0]["timestamp_utc"])
        end = _parse_timestamp(values[-1]["timestamp_utc"])
        summaries.append({
            "sequence_id": index,
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "duration_seconds": int((end - start).total_seconds()),
            "grab_count": len(values),
            "unique_urn_count": len({row["urn"] for row in values}),
            "unique_auction_count": len({
                row["auction_id"] for row in values if row["auction_id"]
            }),
            "ilks": ";".join(sorted({row["ilk"] for row in values})),
            "debt_reduction_dai": str(sum(
                Decimal(row["debt_reduction_dai"]) for row in values
            )),
            "full_debt_closure_count": sum(
                bool(row["full_debt_closure"]) for row in values
            ),
            "maximum_gap_rule": "new sequence after more than one hour",
        })
    return summaries


def classify_economic_mutation(row: dict[str, Any]) -> str:
    """Classify a canonical economic mutation without discarding joint moves."""
    call_type = str(row["call_type"])
    dink = int(row["economic_dink_raw"])
    dart = int(row["economic_dart_raw"])
    if call_type == "grab":
        return "liquidation_grab"
    if call_type == "fork":
        return f"fork_{row['fork_side']}"
    if dink and dart:
        return "combined_adjustment"
    if dink > 0:
        return "deposit"
    if dink < 0:
        return "withdrawal"
    if dart > 0:
        return "draw"
    if dart < 0:
        return "repayment"
    return "no_state_change"


def _decimal_quantile(values: list[Decimal], probability: Decimal) -> str:
    if not values:
        return ""
    ordered = sorted(values)
    position = probability * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return str(
        ordered[lower] + fraction * (ordered[upper] - ordered[lower])
    )


def phase2b_stress_share_candidate() -> Decimal:
    """Read, but never modify, the frozen Phase 2B stress-share candidate."""
    payload = json.loads(
        PHASE2B_CANDIDATES_PATH.read_text(encoding="utf-8")
    )
    matches = [
        row for row in payload["candidates"]
        if row["parameter_name"] == "max_stress_liquidatable_share"
    ]
    if len(matches) != 1:
        raise RepresentativeAcquisitionError(
            "Phase 2B stress-share candidate is not uniquely available"
        )
    return Decimal(str(matches[0]["estimate"]))


def build_stress_tail_diagnostics(
    *,
    window: RepresentativeWindow,
    boundary: list[dict[str, str]],
    expanded_mutations: list[dict[str, Any]],
    rates: list[dict[str, str]],
    barks: list[dict[str, Any]],
    market: pd.DataFrame,
    protocol: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Construct exact hourly exposure diagnostics without changing candidates."""
    states = {
        (row["ilk"], row["urn"].lower()): [
            int(row["opening_ink_raw"]), int(row["opening_art_raw"])
        ]
        for row in boundary
    }
    ordered = sorted(
        expanded_mutations,
        key=lambda row: (
            _parse_timestamp(row["block_time_utc"]),
            int(row["block_number"]),
            int(row["transaction_index"]),
            phase1e.parsed_trace_position(
                row, "trace_position", allow_serialised_root=True
            ),
            row["transaction_hash"],
            row["fork_side"],
        ),
    )
    mutation_index = 0
    stress_candidate = phase2b_stress_share_candidate()
    bark_hours: dict[tuple[pd.Timestamp, str], int] = {}
    for bark in barks:
        hour = _parse_timestamp(bark["block_time_utc"]).floor("h")
        bark_hours[(hour, bark["ilk"])] = (
            bark_hours.get((hour, bark["ilk"]), 0) + 1
        )
    grab_hours: dict[tuple[pd.Timestamp, str], int] = {}
    for mutation in ordered:
        if mutation["call_type"] != "grab":
            continue
        hour = _parse_timestamp(mutation["block_time_utc"]).floor("h")
        grab_hours[(hour, mutation["ilk"])] = (
            grab_hours.get((hour, mutation["ilk"]), 0) + 1
        )
    rows: list[dict[str, Any]] = []
    for hour in pd.date_range(
        window.start,
        window.end,
        freq="h",
        inclusive="left",
    ):
        while (
            mutation_index < len(ordered)
            and _parse_timestamp(
                ordered[mutation_index]["block_time_utc"]
            ) <= hour
        ):
            mutation = ordered[mutation_index]
            key = (mutation["ilk"], mutation["urn"].lower())
            state = states.setdefault(key, [0, 0])
            state[0] += int(mutation["economic_dink_raw"])
            state[1] += int(mutation["economic_dart_raw"])
            if state[0] < 0 or state[1] < 0:
                raise RepresentativeAcquisitionError(
                    f"negative stress-tail state at {hour}: {key}"
                )
            mutation_index += 1
        hourly_rates = {
            ilk: _rate_at(rates, ilk, hour) for ilk in TARGET_ILKS
        }
        hourly_prices = {
            "ETH": Decimal(str(market.loc[hour, "eth_price_usd"])),
            "WBTC": Decimal(str(market.loc[hour, "wbtc_price_usd"])),
        }
        hourly_liquidation_ratios = {
            ilk: Decimal(
                str(protocol.loc[(hour, ilk), "liquidation_ratio"])
            )
            for ilk in TARGET_ILKS
        }
        family_records: dict[str, list[dict[str, Decimal]]] = {
            ilk: [] for ilk in TARGET_ILKS
        }
        for (ilk, _urn), (ink_raw, art_raw) in states.items():
            if ink_raw == 0 and art_raw == 0:
                continue
            rate = hourly_rates[ilk]
            if rate is None and art_raw > 0:
                raise RepresentativeAcquisitionError(
                    f"no accumulated rate for {ilk} at {hour}"
                )
            rate = rate or 10**27
            family = "ETH" if ilk.startswith("ETH-") else "WBTC"
            price = hourly_prices[family]
            liquidation_ratio = hourly_liquidation_ratios[ilk]
            debt = (
                Decimal(art_raw) * Decimal(rate) / Decimal(10**45)
            )
            collateral_value = (
                Decimal(ink_raw) / Decimal(10**18) * price
            )
            ratio = None if debt <= 0 else collateral_value / debt
            family_records[ilk].append({
                "debt": debt,
                "collateral_value": collateral_value,
                "ratio": ratio,
                "liquidation_ratio": liquidation_ratio,
            })
        scopes = [("ALL", sum(family_records.values(), []))]
        scopes.extend((ilk, family_records[ilk]) for ilk in TARGET_ILKS)
        for scope, records in scopes:
            active = len(records)
            indebted_records = [
                record for record in records if record["debt"] > 0
            ]
            liquidatable = [
                record for record in indebted_records
                if record["ratio"] is not None
                and record["ratio"] < record["liquidation_ratio"]
            ]
            buffers = [
                record["ratio"] - record["liquidation_ratio"]
                for record in indebted_records
                if record["ratio"] is not None
            ]
            ratios = [
                record["ratio"] for record in indebted_records
                if record["ratio"] is not None
            ]
            share = (
                Decimal(0)
                if active == 0
                else Decimal(len(liquidatable)) / Decimal(active)
            )
            selected_ilks = (
                TARGET_ILKS if scope == "ALL" else (scope,)
            )
            bark_count = sum(
                bark_hours.get((hour, ilk), 0) for ilk in selected_ilks
            )
            grab_count = sum(
                grab_hours.get((hour, ilk), 0) for ilk in selected_ilks
            )
            rows.append({
                "window": window.key,
                "timestamp_utc": hour.isoformat(),
                "collateral_scope": scope,
                "active_vaults": active,
                "indebted_vaults": len(indebted_records),
                "liquidatable_vaults": len(liquidatable),
                "liquidatable_share_all_active": str(share),
                "debt_at_risk_dai": str(sum(
                    record["debt"] for record in liquidatable
                )),
                "collateral_shortfall_dai": str(sum(
                    record["debt"] * record["liquidation_ratio"]
                    - record["collateral_value"]
                    for record in liquidatable
                )),
                "buffer_q01": _decimal_quantile(
                    buffers, Decimal("0.01")
                ),
                "buffer_q05": _decimal_quantile(
                    buffers, Decimal("0.05")
                ),
                "buffer_q10": _decimal_quantile(
                    buffers, Decimal("0.10")
                ),
                "buffer_median": _decimal_quantile(
                    buffers, Decimal("0.50")
                ),
                "collateral_ratio_q01": _decimal_quantile(
                    ratios, Decimal("0.01")
                ),
                "collateral_ratio_q05": _decimal_quantile(
                    ratios, Decimal("0.05")
                ),
                "collateral_ratio_median": _decimal_quantile(
                    ratios, Decimal("0.50")
                ),
                "bark_initiations": bark_count,
                "grab_executions": grab_count,
                "above_phase2b_stress_candidate": share > stress_candidate,
                "above_current_stress_threshold_0_30": share > Decimal("0.30"),
                "phase2b_candidate_preserved": str(stress_candidate),
                "state_timing": "state at the start of the UTC hour",
            })
    return rows


def write_parameter_readiness(
    processed_path: Path,
    *,
    window: RepresentativeWindow,
    opening_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_path = PROVENANCE_ROOT / "tranche_01_parameter_evidence_readiness.csv"
    rows = load_csv(source_path)
    active = sum(bool(row["active"]) for row in opening_rows)
    indebted = sum(Decimal(row["debt_dai"]) > 0 for row in opening_rows)
    collateral_coverage = ";".join(sorted({row["ilk"] for row in opening_rows}))
    liquidation_count = sum(
        row["mutation_type"] == "grab" for row in event_rows
    )
    count_by_parameter = {
        "n_vaults": active,
        "target_debt_share": indebted,
        "debt_mean": indebted,
        "debt_std": indebted,
        "collateral_ratio_mean": indebted,
        "collateral_ratio_std": indebted,
        "min_collateral_ratio_buffer": indebted,
        "max_close_factor": liquidation_count,
        "max_normal_liquidatable_share": indebted,
        "max_stress_liquidatable_share": (
            indebted if window.key == "usdc_svb" else 0
        ),
    }
    for row in rows:
        parameter = row["parameter"]
        count = count_by_parameter[parameter]
        count_column = f"{window.key}_observation_count"
        row[count_column] = str(count)
        row["total_usable_observations"] = str(
            int(row["quiet_mature_observation_count"])
            + int(row["usdc_svb_observation_count"])
            + int(row.get("terra_cefi_observation_count", "0"))
        )
        row["opening_state_reconstruction_succeeded"] = "True"
        if count:
            row["collateral_coverage"] = collateral_coverage
        row["missingness"] = (
            "No missing state fields among usable opening observations; "
            "manager owner/proxy remains nullable for direct urns."
        )
        if window.key == "terra_cefi":
            if parameter == "max_close_factor":
                row["status"] = (
                    "ready_for_estimation"
                    if liquidation_count > 0
                    else "insufficient_observations"
                )
                row["notes"] = (
                    f"{liquidation_count} linked Terra/CeFi Vat.grab "
                    "observations provide simulator-aligned debt close "
                    "fractions; no value is adopted."
                )
            elif parameter == "max_normal_liquidatable_share":
                row["status"] = "ready_for_review"
                row["notes"] = (
                    "Quiet-window candidate is preserved; Terra/CeFi is a "
                    "stress sensitivity rather than normal-regime evidence."
                )
            else:
                row["status"] = "ready_for_review"
                row["notes"] = (
                    "Existing Phase 2B candidate is preserved and can now be "
                    "reviewed against Terra/CeFi stress-tail evidence."
                )
        elif parameter == "max_normal_liquidatable_share":
            row["status"] = "ready_for_estimation"
            row["notes"] = (
                "Quiet-mature opening, exact event replay and independently "
                "observed closing boundary all passed; no value was estimated."
            )
        elif parameter == "max_close_factor":
            total_liquidations = int(row["total_usable_observations"])
            row["status"] = (
                "ready_for_estimation"
                if total_liquidations >= 100
                else "insufficient_observations"
            )
            row["notes"] = (
                f"{total_liquidations} linked representative-window grabs; "
                "Phase 1C remains complementary liquidation evidence."
            )
        elif parameter == "max_stress_liquidatable_share":
            if int(row["usdc_svb_observation_count"]) > 0:
                row["status"] = "ready_for_estimation"
                row["notes"] = (
                    "USDC/SVB opening, exact event replay and independent "
                    "closing-boundary reconciliation passed."
                )
            else:
                row["status"] = "blocked_by_missing_window"
                row["opening_state_reconstruction_succeeded"] = "False"
                row["notes"] = (
                    "The authorised USDC/SVB stress window was not started."
                )
        elif (
            int(row["quiet_mature_observation_count"]) > 0
            and int(row["usdc_svb_observation_count"]) > 0
        ):
            row["status"] = "ready_for_estimation"
            row["notes"] = (
                "Both quiet-mature and USDC/SVB reconstructed evidence are "
                "available; no value was estimated."
            )
        else:
            row["status"] = "partially_identified"
            row["notes"] = (
                "Quiet-mature reconstruction passed; stress-window and "
                "cross-window evidence remains outstanding."
            )
    columns = tuple(rows[0])
    write_csv_atomic(processed_path, columns, rows)
    if window.key != "terra_cefi":
        write_csv_atomic(source_path, columns, rows)
    return rows


def write_quiet_parameter_readiness(
    processed_path: Path,
    *,
    opening_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Backward-compatible quiet-window readiness entry point."""
    return write_parameter_readiness(
        processed_path,
        window=WINDOWS["quiet_mature"],
        opening_rows=opening_rows,
        event_rows=event_rows,
    )


def expand_economic_mutations(
    mutations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expand raw Vat calls into ordered urn-level economic mutations."""
    expanded: list[dict[str, Any]] = []
    for row in mutations:
        base_row = dict(row)
        if row["call_type"] == "fork":
            for side, urn, sign in (
                ("source", row["source_urn"], -1),
                ("destination", row["destination_urn"], 1),
            ):
                expanded.append({
                    **base_row, "urn": urn, "fork_side": side,
                    "economic_dink_raw": sign * int(row["dink_raw"]),
                    "economic_dart_raw": sign * int(row["dart_raw"]),
                    "observed_or_derived": "derived_fork_expansion",
                })
        else:
            expanded.append({
                **base_row, "fork_side": "",
                "economic_dink_raw": int(row["dink_raw"]),
                "economic_dart_raw": int(row["dart_raw"]),
                "observed_or_derived": "observed_call",
            })
    expanded.sort(key=lambda row: (
        int(row["block_number"]), int(row["transaction_index"]),
        phase1e.parsed_trace_position(
            row, "trace_position", allow_serialised_root=True
        ),
        {"frob": 0, "fork": 1, "grab": 2}[row["call_type"]],
        row["transaction_hash"].lower(),
        0 if row["fork_side"] == "source" else 1,
    ))
    return expanded


COMPARISON_METRICS = (
    "opening_active_vaults", "opening_indebted_vaults",
    "closing_active_vaults", "closing_indebted_vaults",
    "opening_debt_median_dai", "opening_collateral_ratio_median",
    "deposits", "withdrawals", "draws", "repayments", "grabs",
    "entry_proxy_count", "exit_proxy_count", "active_intervention_urns",
    "intervention_frequency", "largest_owner_proxy_opening_share",
    "opening_debt_share", "opening_liquidatable_share",
)


def _comparison_metrics(
    window: RepresentativeWindow,
) -> dict[str, dict[str, Decimal]]:
    processed = window_paths(window)["processed"]
    opening = load_csv(processed / "opening_vault_state.csv")
    closing = load_csv(processed / "closing_vault_state.csv")
    summaries = {
        row["ilk"]: row
        for row in load_csv(processed / "vault_behaviour_summary.csv")
    }
    total_debt = sum(
        Decimal(row["debt_dai"]) for row in opening
        if Decimal(row["debt_dai"]) > 0
    )
    result: dict[str, dict[str, Decimal]] = {}
    for ilk in TARGET_ILKS:
        open_rows = [row for row in opening if row["ilk"] == ilk]
        close_rows = [row for row in closing if row["ilk"] == ilk]
        debts = [
            Decimal(row["debt_dai"]) for row in open_rows
            if Decimal(row["debt_dai"]) > 0
        ]
        ratios = [
            Decimal(row["collateral_ratio"]) for row in open_rows
            if row["collateral_ratio"]
        ]
        liquidatable = [
            row for row in open_rows
            if Decimal(row["debt_dai"]) > 0
            and row["collateral_ratio"]
            and Decimal(row["collateral_ratio"])
            < Decimal(row["liquidation_ratio"])
        ]
        summary = summaries[ilk]
        active = Decimal(summary["opening_active_vaults"])
        interventions = Decimal(summary["active_intervention_urns"])
        result[ilk] = {
            "opening_active_vaults": active,
            "opening_indebted_vaults": Decimal(
                summary["opening_indebted_vaults"]
            ),
            "closing_active_vaults": Decimal(sum(
                phase1e._truth(row["active"]) for row in close_rows
            )),
            "closing_indebted_vaults": Decimal(sum(
                Decimal(row["debt_dai"]) > 0 for row in close_rows
            )),
            "opening_debt_median_dai": (
                Decimal(_decimal_quantile(debts, Decimal("0.5")))
                if debts else Decimal(0)
            ),
            "opening_collateral_ratio_median": (
                Decimal(_decimal_quantile(ratios, Decimal("0.5")))
                if ratios else Decimal(0)
            ),
            "deposits": Decimal(summary["deposits"]),
            "withdrawals": Decimal(summary["withdrawals"]),
            "draws": Decimal(summary["draws"]),
            "repayments": Decimal(summary["repayments"]),
            "grabs": Decimal(summary["grab_count"]),
            "entry_proxy_count": Decimal(summary["entry_proxy_count"]),
            "exit_proxy_count": Decimal(summary["exit_proxy_count"]),
            "active_intervention_urns": interventions,
            "intervention_frequency": (
                interventions / active if active else Decimal(0)
            ),
            "largest_owner_proxy_opening_share": (
                Decimal(summary["largest_owner_proxy_opening_share"])
                if summary["largest_owner_proxy_opening_share"]
                else Decimal(0)
            ),
            "opening_debt_share": (
                sum(debts) / total_debt if total_debt else Decimal(0)
            ),
            "opening_liquidatable_share": (
                Decimal(len(liquidatable)) / Decimal(len(debts))
                if debts else Decimal(0)
            ),
        }
    all_opening = [row for row in opening if Decimal(row["debt_dai"]) > 0]
    all_ratios = [
        Decimal(row["collateral_ratio"]) for row in all_opening
        if row["collateral_ratio"]
    ]
    result["ALL"] = {
        metric: sum(result[ilk][metric] for ilk in TARGET_ILKS)
        for metric in COMPARISON_METRICS
    }
    result["ALL"].update({
        "opening_debt_median_dai": (
            Decimal(_decimal_quantile(
                [Decimal(row["debt_dai"]) for row in all_opening],
                Decimal("0.5"),
            )) if all_opening else Decimal(0)
        ),
        "opening_collateral_ratio_median": (
            Decimal(_decimal_quantile(all_ratios, Decimal("0.5")))
            if all_ratios else Decimal(0)
        ),
        "intervention_frequency": (
            result["ALL"]["active_intervention_urns"]
            / result["ALL"]["opening_active_vaults"]
            if result["ALL"]["opening_active_vaults"] else Decimal(0)
        ),
        "largest_owner_proxy_opening_share": max(
            result[ilk]["largest_owner_proxy_opening_share"]
            for ilk in TARGET_ILKS
        ),
        "opening_debt_share": Decimal(1) if total_debt else Decimal(0),
        "opening_liquidatable_share": (
            sum(
                result[ilk]["opening_liquidatable_share"]
                * result[ilk]["opening_indebted_vaults"]
                for ilk in TARGET_ILKS
            ) / Decimal(len(all_opening))
            if all_opening else Decimal(0)
        ),
    })
    return result


def write_cross_window_comparison(output: Path) -> list[dict[str, Any]]:
    """Write a descriptive, regime-labelled quiet-versus-stress comparison."""
    quiet = _comparison_metrics(WINDOWS["quiet_mature"])
    stress = _comparison_metrics(WINDOWS["usdc_svb"])
    rows: list[dict[str, Any]] = []
    for ilk in (*TARGET_ILKS, "ALL"):
        row: dict[str, Any] = {"ilk": ilk}
        for metric in COMPARISON_METRICS:
            quiet_value = quiet[ilk][metric]
            stress_value = stress[ilk][metric]
            row[f"quiet_mature_{metric}"] = str(quiet_value)
            row[f"usdc_svb_{metric}"] = str(stress_value)
            row[f"difference_{metric}"] = str(stress_value - quiet_value)
        row["interpretation_limit"] = (
            "Descriptive regime comparison only; no causal interpretation."
        )
        rows.append(row)
    write_csv_atomic(output, tuple(rows[0]), rows)
    return rows


def write_terra_cross_regime_comparison(
    output: Path,
) -> list[dict[str, Any]]:
    """Write a three-regime descriptive comparison with duration caveats."""
    windows = {
        key: WINDOWS[key]
        for key in ("quiet_mature", "usdc_svb", "terra_cefi")
    }
    metrics = {
        key: _comparison_metrics(window)
        for key, window in windows.items()
    }
    rows: list[dict[str, Any]] = []
    for ilk in (*TARGET_ILKS, "ALL"):
        row: dict[str, Any] = {"ilk": ilk}
        for key, window in windows.items():
            duration_days = Decimal(
                str((window.end - window.start).total_seconds())
            ) / Decimal(86_400)
            row[f"{key}_duration_days"] = str(duration_days)
            for metric in COMPARISON_METRICS:
                value = metrics[key][ilk][metric]
                row[f"{key}_{metric}"] = str(value)
                if metric in {
                    "deposits", "withdrawals", "draws", "repayments", "grabs",
                    "entry_proxy_count", "exit_proxy_count",
                }:
                    row[f"{key}_{metric}_per_day"] = str(
                        value / duration_days
                    )
        row["selection_caveat"] = (
            "Purposively selected unequal-duration regimes; descriptive "
            "comparison only and no causal interpretation."
        )
        rows.append(row)
    write_csv_atomic(output, tuple(rows[0]), rows)
    return rows


def write_terra_preflight(
    *,
    usage: Decimal,
    quota: Decimal,
) -> dict[str, Any]:
    """Persist the Terra/CeFi scope, integrity and cost gate before Dune."""
    window = WINDOWS["terra_cefi"]
    _, protocol = _price_and_ratio_inputs()
    active_ilks = validate_active_ilks(window, protocol.reset_index())
    barks = extract_barks(window)
    auctions = extract_phase1c_auctions(window)
    phase1c_ilks = sorted({row["ilk"] for row in barks})
    protected = {
        "AGENTS.md": {
            "expected": (
                "7686cca1a63f98865fb1d2742f50315636c0f3eab377cb7618a"
                "5870beffb01de"
            ),
            "observed": sha256_file(ROOT / "AGENTS.md"),
        },
        "data/DATA_ACQUISITION_PLAN.md": {
            "expected": (
                "05587f17600f148d90cc26df4f281258d299188dad8dd53d2ab"
                "00f351863ee60"
            ),
            "observed": sha256_file(
                ROOT / "data" / "DATA_ACQUISITION_PLAN.md"
            ),
        },
    }
    projected = sum(
        Decimal(stream["credits_high"])
        for stream in TERRA_CEFI_STREAM_ESTIMATES.values()
    )
    gate = enforce_terra_cefi_credit_gate(
        starting_usage=usage,
        current_usage=usage,
        quota=quota,
        projected_remaining_cost=projected,
    )
    failures = list(active_ilks["failures"])
    failures.extend(
        f"protected checksum mismatch: {path}"
        for path, values in protected.items()
        if values["expected"] != values["observed"]
    )
    if phase1c_ilks != list(TARGET_ILKS):
        failures.append("Phase 1C overlap does not cover all six target ilks")
    if not gate["passed"]:
        failures.extend(gate["failures"])
    payload = {
        "validation_passed": not failures,
        "failures": failures,
        "window": {
            "key": window.key,
            "start_utc": window.start.isoformat(),
            "end_exclusive_utc": window.end.isoformat(),
            "duration_hours": int(
                (window.end - window.start).total_seconds() // 3600
            ),
        },
        "target_ilks": list(TARGET_ILKS),
        "active_ilk_validation": active_ilks,
        "phase1c_overlap": {
            "bark_events": len(barks),
            "auctions": len(auctions),
            "ilks": phase1c_ilks,
            "actions_path": relative(LIQUIDATION_ACTIONS_PATH),
            "actions_sha256": sha256_file(LIQUIDATION_ACTIONS_PATH),
            "auctions_path": relative(LIQUIDATION_AUCTIONS_PATH),
            "auctions_sha256": sha256_file(LIQUIDATION_AUCTIONS_PATH),
            "transactions_path": relative(LIQUIDATION_TRANSACTIONS_PATH),
            "transactions_sha256": sha256_file(
                LIQUIDATION_TRANSACTIONS_PATH
            ),
        },
        "stream_estimates": TERRA_CEFI_STREAM_ESTIMATES,
        "planned_execution_sequence": [
            "boundary_states", "vat_mutations", "local_bark_validation",
            "ownership_history", "effective_rates", "local_reconstruction",
        ],
        "maximum_new_executions": 4,
        "maximum_authorised_executions": 5,
        "starting_usage": str(usage),
        "quota": str(quota),
        "remaining_quota": str(quota - usage),
        "conservative_projected_cost": str(projected),
        "credit_gate": gate,
        "protected_files": protected,
        "ftx_acquired_or_used": False,
        "bull_expansion_acquired": False,
        "created_at_utc": utc_now(),
    }
    path = window_paths(window)["provenance"] / "preflight.json"
    write_json_atomic(path, payload)
    if failures:
        raise RepresentativeAcquisitionError(
            "Terra/CeFi preflight failed: " + "; ".join(failures)
        )
    return payload


def reconstruct_window(window: RepresentativeWindow) -> dict[str, Any]:
    base = window_paths(window)
    boundary = load_csv(stream_paths(window, "boundary_states")["raw"])
    mutations = load_csv(stream_paths(window, "vat_mutations")["raw"])
    ownership = load_csv(stream_paths(window, "ownership_history")["raw"])
    barks = extract_barks(window)
    processed = base["processed"]
    provenance = base["provenance"]
    sparse_rate_path = processed / "effective_rates.csv"
    if sparse_rate_path.exists():
        rates = load_csv(sparse_rate_path)
        if tuple(rates[0]) != SPARSE_RATE_COLUMNS:
            raise RepresentativeAcquisitionError(
                "processed sparse-rate schema is not valid"
            )
    else:
        rates = load_csv(stream_paths(window, "effective_rates")["raw"])
        write_csv_atomic(sparse_rate_path, RATE_COLUMNS, rates)

    write_csv_atomic(processed / "vat_mutations.csv", MUTATION_COLUMNS, mutations)
    write_csv_atomic(processed / "bark_annotations.csv", BARK_COLUMNS, barks)
    phase1c_auctions = extract_phase1c_auctions(window)
    if phase1c_auctions:
        write_csv_atomic(
            processed / "phase1c_liquidation_auctions.csv",
            tuple(phase1c_auctions[0]),
            phase1c_auctions,
        )
    write_csv_atomic(
        processed / "ownership_history.csv", OWNERSHIP_COLUMNS, ownership
    )

    market, protocol = _price_and_ratio_inputs()
    states: dict[tuple[str, str], list[int]] = {}
    expected_end: dict[tuple[str, str], tuple[int, int]] = {}
    opening_rows: list[dict[str, Any]] = []
    for row in boundary:
        key = (row["ilk"], row["urn"].lower())
        ink = int(row["opening_ink_raw"])
        art = int(row["opening_art_raw"])
        states[key] = [ink, art]
        expected_end[key] = (int(row["end_ink_raw"]), int(row["end_art_raw"]))
        rate = int(row["opening_rate_raw_ray"])
        opening_rows.append(_enriched_state(
            window=window, timestamp=window.start, ilk=key[0], urn=key[1],
            ink_raw=ink, art_raw=art, rate_raw=rate, ownership=ownership,
            market=market, protocol=protocol, state_label="opening",
        ))
    write_csv_atomic(
        processed / "opening_vault_state.csv", STATE_COLUMNS, opening_rows
    )

    bark_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for bark in barks:
        key = (
            bark["transaction_hash"].lower(), bark["ilk"], bark["urn"].lower()
        )
        bark_by_key.setdefault(key, []).append(bark)

    expanded = expand_economic_mutations(mutations)

    event_rows: list[dict[str, Any]] = []
    close_factor_rows: list[dict[str, Any]] = []
    bark_grab_linkage_rows: list[dict[str, Any]] = []
    negative_events: list[str] = []
    matched_barks: set[tuple[str, str, str, str]] = set()
    ambiguous_bark_grab_links: list[str] = []
    for row in expanded:
        key = (row["ilk"], row["urn"].lower())
        state = states.setdefault(key, [0, 0])
        pre_ink_raw, pre_art_raw = state
        state[0] += int(row["economic_dink_raw"])
        state[1] += int(row["economic_dart_raw"])
        if state[0] < 0 or state[1] < 0:
            negative_events.append(
                f"{row['transaction_hash']}:{row['trace_position']}:{key}"
            )
        timestamp = _parse_timestamp(row["block_time_utc"])
        event_trace = phase1e.parsed_trace_position(
            row, "trace_position", allow_serialised_root=True
        )
        rate = _rate_at(
            rates,
            row["ilk"],
            timestamp,
            block_number=int(row["block_number"]),
            transaction_index=int(row["transaction_index"]),
            trace_position=event_trace,
        )
        if rate is None and state[1] != 0:
            raise RepresentativeAcquisitionError(
                f"no effective rate for {row['ilk']} at {timestamp}"
            )
        rate = rate or 10**27
        enriched = _enriched_state(
            window=window, timestamp=timestamp, ilk=row["ilk"], urn=key[1],
            ink_raw=state[0], art_raw=state[1], rate_raw=rate,
            ownership=ownership, market=market, protocol=protocol,
            state_label="after_event",
        )
        auction_id = ""
        keeper = ""
        bark_linkage = "not_applicable"
        if row["call_type"] == "grab":
            candidates = bark_by_key.get(
                (row["transaction_hash"].lower(), row["ilk"], key[1]), []
            )
            exact = [
                bark for bark in candidates
                if int(row["economic_dink_raw"]) == -int(bark["ink_raw"])
                and int(row["economic_dart_raw"]) == -int(bark["art_raw"])
            ]
            if len(exact) == 1:
                auction_id = exact[0]["auction_id"]
                keeper = exact[0]["keeper"]
                bark_linkage = "exact_amount_and_identity_match"
                matched_barks.add((
                    exact[0]["transaction_hash"], exact[0]["ilk"],
                    exact[0]["urn"], exact[0]["auction_id"],
                ))
            elif len(exact) > 1:
                bark_linkage = "ambiguous_multiple_exact_matches"
                ambiguous_bark_grab_links.append(
                    f"{row['transaction_hash']}:{row['ilk']}:{key[1]}"
                )
            else:
                bark_linkage = "unmatched"
            matched_bark = exact[0] if len(exact) == 1 else None
            bark_grab_linkage_rows.append({
                "window": window.key,
                "transaction_hash": row["transaction_hash"].lower(),
                "ilk": row["ilk"],
                "urn": key[1],
                "auction_id": "" if matched_bark is None else matched_bark["auction_id"],
                "keeper": "" if matched_bark is None else matched_bark["keeper"],
                "grab_block_number": row["block_number"],
                "grab_transaction_index": row["transaction_index"],
                "grab_trace_position": row["trace_position"],
                "grab_dink_raw": str(row["economic_dink_raw"]),
                "grab_dart_raw": str(row["economic_dart_raw"]),
                "bark_ink_raw": "" if matched_bark is None else matched_bark["ink_raw"],
                "bark_art_raw": "" if matched_bark is None else matched_bark["art_raw"],
                "linkage_status": bark_linkage,
                "economic_treatment": (
                    "Dog.Bark is annotation only; Vat.grab is the canonical "
                    "economic state mutation."
                ),
            })
            close_metrics = liquidation_close_fraction_metrics(
                pre_ink_raw=pre_ink_raw,
                pre_art_raw=pre_art_raw,
                dink_raw=int(row["economic_dink_raw"]),
                dart_raw=int(row["economic_dart_raw"]),
                rate_raw_ray=rate,
            )
            close_factor_rows.append({
                "window": window.key,
                "timestamp_utc": timestamp.isoformat(),
                "block_number": row["block_number"],
                "transaction_index": row["transaction_index"],
                "transaction_hash": row["transaction_hash"].lower(),
                "trace_position": row["trace_position"],
                "ilk": row["ilk"],
                "urn": key[1],
                "auction_id": auction_id,
                "keeper": keeper,
                "pre_grab_ink_raw": str(pre_ink_raw),
                "pre_grab_art_raw": str(pre_art_raw),
                "grab_dink_raw": str(row["economic_dink_raw"]),
                "grab_dart_raw": str(row["economic_dart_raw"]),
                **close_metrics,
                "rate_raw_ray": str(rate),
                "bark_linkage": bark_linkage,
                "model_semantic_mapping": (
                    "LiquidationConfig.max_close_factor is the proportion "
                    "of pre-liquidation debt repaid in one liquidation; "
                    "debt_close_fraction is the direct empirical analogue."
                ),
            })
        event_rows.append({
            "window": window.key,
            "timestamp_utc": timestamp.isoformat(),
            "block_number": row["block_number"],
            "transaction_index": row["transaction_index"],
            "transaction_hash": row["transaction_hash"].lower(),
            "trace_position": row["trace_position"],
            "ilk": row["ilk"],
            "urn": key[1],
            "cdp_id": enriched["cdp_id"],
            "owner_or_proxy": enriched["owner_or_proxy"],
            "mutation_type": row["call_type"],
            "fork_side": row["fork_side"],
            "dink_raw": str(row["economic_dink_raw"]),
            "dart_raw": str(row["economic_dart_raw"]),
            "mutation_classification": classify_economic_mutation(row),
            "ink_after_raw": str(state[0]),
            "art_after_raw": str(state[1]),
            "rate_raw_ray": str(rate),
            "debt_after_dai": enriched["debt_dai"],
            "collateral_ratio_after": enriched["collateral_ratio"],
            "liquidation_flag": row["call_type"] == "grab",
            "auction_id": auction_id,
            "keeper": keeper,
            "source_call_type": row["call_type"],
            "source_contract": row["source_contract"],
            "source_table": row["source_table"],
            "observed_or_derived": row["observed_or_derived"],
        })
    write_csv_atomic(
        processed / "reconstructed_vault_events.csv",
        EVENT_COLUMNS,
        event_rows,
    )
    write_csv_atomic(
        processed / "liquidation_close_factors.csv",
        CLOSE_FACTOR_COLUMNS,
        close_factor_rows,
    )
    write_csv_atomic(
        processed / "bark_grab_linkage.csv",
        BARK_GRAB_LINKAGE_COLUMNS,
        bark_grab_linkage_rows,
    )
    sequence_rows = cluster_liquidation_sequences(close_factor_rows)
    sequence_columns = (
        tuple(sequence_rows[0])
        if sequence_rows
        else (
            "sequence_id", "start_utc", "end_utc", "duration_seconds",
            "grab_count", "unique_urn_count", "unique_auction_count",
            "ilks", "debt_reduction_dai", "full_debt_closure_count",
            "maximum_gap_rule",
        )
    )
    write_csv_atomic(
        processed / "liquidation_sequence_summary.csv",
        sequence_columns,
        sequence_rows,
    )
    stress_tail_rows = build_stress_tail_diagnostics(
        window=window,
        boundary=boundary,
        expanded_mutations=expanded,
        rates=rates,
        barks=barks,
        market=market,
        protocol=protocol,
    )
    write_csv_atomic(
        processed / "stress_tail_diagnostics.csv",
        tuple(stress_tail_rows[0]),
        stress_tail_rows,
    )

    final_rows: list[dict[str, Any]] = []
    replay_mismatches: list[str] = []
    for key in sorted(set(states) | set(expected_end)):
        observed = tuple(states.get(key, [0, 0]))
        expected = expected_end.get(key, (0, 0))
        if observed != expected:
            replay_mismatches.append(f"{key}:{observed}!={expected}")
        rate = _rate_at(rates, key[0], window.end - pd.Timedelta(nanoseconds=1))
        if rate is None and observed[1] != 0:
            raise RepresentativeAcquisitionError(
                f"no end rate for active {key[0]}"
            )
        final_rows.append(_enriched_state(
            window=window, timestamp=window.end - pd.Timedelta(nanoseconds=1),
            ilk=key[0], urn=key[1], ink_raw=observed[0],
            art_raw=observed[1], rate_raw=rate or 10**27,
            ownership=ownership, market=market, protocol=protocol,
            state_label="window_end",
        ))
    snapshots = opening_rows + final_rows
    write_csv_atomic(
        processed / "reconstructed_vault_snapshots.csv",
        STATE_COLUMNS,
        snapshots,
    )
    write_csv_atomic(
        processed / "closing_vault_state.csv",
        STATE_COLUMNS,
        final_rows,
    )

    unmatched_barks = len(barks) - len(matched_barks)
    matched_grabs = sum(bool(row["auction_id"]) for row in event_rows)
    grab_count = sum(
        row["call_type"] == "grab" for row in mutations
    )
    summary_rows: list[dict[str, Any]] = []
    by_ilk = {ilk: [] for ilk in TARGET_ILKS}
    for row in event_rows:
        by_ilk[row["ilk"]].append(row)
    opening_by_key = {
        (row["ilk"], row["urn"]): row for row in opening_rows
    }
    final_by_key = {
        (row["ilk"], row["urn"]): row for row in final_rows
    }
    for ilk, values in by_ilk.items():
        ilk_opening = [row for row in opening_rows if row["ilk"] == ilk]
        debts = [
            Decimal(row["debt_dai"])
            for row in ilk_opening if Decimal(row["debt_dai"]) > 0
        ]
        ratios = [
            Decimal(row["collateral_ratio"])
            for row in ilk_opening if row["collateral_ratio"]
        ]
        mapped_owners = [
            row["owner_or_proxy"]
            for row in ilk_opening if row["owner_or_proxy"]
        ]
        owner_counts = {
            owner: mapped_owners.count(owner) for owner in set(mapped_owners)
        }
        keys = {
            key for key in set(opening_by_key) | set(final_by_key)
            if key[0] == ilk
        }
        entry_count = sum(
            not bool(opening_by_key.get(key, {}).get("active", False))
            and bool(final_by_key.get(key, {}).get("active", False))
            for key in keys
        )
        exit_count = sum(
            bool(opening_by_key.get(key, {}).get("active", False))
            and not bool(final_by_key.get(key, {}).get("active", False))
            for key in keys
        )
        summary_rows.append({
            "window": window.key,
            "ilk": ilk,
            "opening_active_vaults": sum(
                row["ilk"] == ilk and row["active"] for row in opening_rows
            ),
            "opening_indebted_vaults": len(debts),
            "opening_debt_p25_dai": _decimal_quantile(
                debts, Decimal("0.25")
            ),
            "opening_debt_median_dai": _decimal_quantile(
                debts, Decimal("0.5")
            ),
            "opening_debt_p75_dai": _decimal_quantile(
                debts, Decimal("0.75")
            ),
            "opening_debt_p90_dai": _decimal_quantile(
                debts, Decimal("0.90")
            ),
            "collateral_ratio_observation_count": len(ratios),
            "opening_collateral_ratio_p25": _decimal_quantile(
                ratios, Decimal("0.25")
            ),
            "opening_collateral_ratio_median": _decimal_quantile(
                ratios, Decimal("0.5")
            ),
            "opening_collateral_ratio_p75": _decimal_quantile(
                ratios, Decimal("0.75")
            ),
            "opening_collateral_ratio_p90": _decimal_quantile(
                ratios, Decimal("0.90")
            ),
            "unique_urns": len({row["urn"] for row in values}),
            "active_intervention_urns": len({
                row["urn"] for row in values
            }),
            "frob_count": sum(row["mutation_type"] == "frob" for row in values),
            "fork_expansion_count": sum(
                row["mutation_type"] == "fork" for row in values
            ),
            "grab_count": sum(row["mutation_type"] == "grab" for row in values),
            "deposits": sum(int(row["dink_raw"]) > 0 for row in values),
            "withdrawals": sum(int(row["dink_raw"]) < 0 for row in values),
            "draws": sum(int(row["dart_raw"]) > 0 for row in values),
            "repayments": sum(int(row["dart_raw"]) < 0 for row in values),
            "mapped_cdp_urns": len({
                row["urn"] for row in values if row["cdp_id"]
            }),
            "direct_or_unmapped_urns": len({
                row["urn"] for row in values if not row["cdp_id"]
            }),
            "entry_proxy_count": entry_count,
            "exit_proxy_count": exit_count,
            "opening_mapped_owner_proxy_count": len(set(mapped_owners)),
            "largest_owner_proxy_opening_share": (
                ""
                if not mapped_owners
                else str(
                    Decimal(max(owner_counts.values()))
                    / Decimal(len(mapped_owners))
                )
            ),
            "owner_identity_limitation":
                "manager owner/proxy; not necessarily beneficial owner",
        })
    summary_columns = tuple(summary_rows[0])
    write_csv_atomic(
        processed / "vault_behaviour_summary.csv",
        summary_columns,
        summary_rows,
    )
    readiness_rows = write_parameter_readiness(
        processed / "parameter_evidence_readiness.csv",
        window=window,
        opening_rows=opening_rows,
        event_rows=event_rows,
    )
    if window.key == "terra_cefi":
        write_terra_cross_regime_comparison(
            processed / "cross_regime_comparison.csv"
        )

    validation = {
        "validation_passed": (
            not negative_events and not replay_mismatches
            and unmatched_barks == 0 and matched_grabs == grab_count
        ),
        "negative_event_state_count": len(negative_events),
        "negative_event_states": negative_events[:100],
        "replay_mismatch_count": len(replay_mismatches),
        "replay_mismatches": replay_mismatches[:100],
        "bark_count": len(barks),
        "grab_count": grab_count,
        "matched_bark_count": len(matched_barks),
        "matched_grab_count": matched_grabs,
        "unmatched_bark_count": unmatched_barks,
        "unmatched_grab_count": grab_count - matched_grabs,
        "ambiguous_bark_grab_link_count": len(ambiguous_bark_grab_links),
        "ambiguous_bark_grab_links": ambiguous_bark_grab_links[:100],
        "raw_mutation_count": len(mutations),
        "economic_mutation_count": len(event_rows),
        "opening_state_count": len(opening_rows),
        "snapshot_count": len(snapshots),
        "ownership_record_count": len(ownership),
        "rate_record_count": len(rates),
        "parameter_readiness_row_count": len(readiness_rows),
        "close_factor_observation_count": len(close_factor_rows),
        "liquidation_sequence_count": len(sequence_rows),
        "stress_tail_row_count": len(stress_tail_rows),
        "phase1c_auction_count": len(phase1c_auctions),
    }
    if not validation["validation_passed"]:
        write_json_atomic(provenance / "reconstruction_validation.json", validation)
        raise RepresentativeAcquisitionError(
            "window reconstruction failed validation"
        )
    validation_csv = [{
        key: (
            json.dumps(value, sort_keys=True)
            if isinstance(value, (list, dict)) else value
        )
        for key, value in validation.items()
    }]
    write_csv_atomic(
        processed / "reconstruction_validation.csv",
        tuple(validation_csv[0]),
        validation_csv,
    )
    if window.key == "usdc_svb":
        write_cross_window_comparison(
            processed / "quiet_mature_vs_usdc_svb_comparison.csv"
        )

    outputs: dict[str, dict[str, Any]] = {}
    for name in (
        "opening_vault_state.csv", "vat_mutations.csv",
        "bark_annotations.csv", "ownership_history.csv",
        "effective_rates.csv", "reconstructed_vault_events.csv",
        "reconstructed_vault_snapshots.csv", "closing_vault_state.csv",
        "vault_behaviour_summary.csv", "parameter_evidence_readiness.csv",
        "reconstruction_validation.csv", "liquidation_close_factors.csv",
        "bark_grab_linkage.csv", "liquidation_sequence_summary.csv",
        "stress_tail_diagnostics.csv",
    ):
        path = processed / name
        with path.open(newline="", encoding="utf-8") as handle:
            row_count = sum(1 for _ in csv.reader(handle)) - 1
        outputs[name] = {
            "path": relative(path),
            "rows": row_count,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    phase1c_auction_extract = processed / "phase1c_liquidation_auctions.csv"
    if phase1c_auction_extract.exists():
        with phase1c_auction_extract.open(
            newline="", encoding="utf-8"
        ) as handle:
            extract_rows = sum(1 for _ in csv.reader(handle)) - 1
        outputs[phase1c_auction_extract.name] = {
            "path": relative(phase1c_auction_extract),
            "rows": extract_rows,
            "size_bytes": phase1c_auction_extract.stat().st_size,
            "sha256": sha256_file(phase1c_auction_extract),
        }
    comparison_path = processed / "quiet_mature_vs_usdc_svb_comparison.csv"
    if comparison_path.exists():
        with comparison_path.open(newline="", encoding="utf-8") as handle:
            comparison_rows = sum(1 for _ in csv.reader(handle)) - 1
        outputs[comparison_path.name] = {
            "path": relative(comparison_path),
            "rows": comparison_rows,
            "size_bytes": comparison_path.stat().st_size,
            "sha256": sha256_file(comparison_path),
        }
    terra_comparison = processed / "cross_regime_comparison.csv"
    if terra_comparison.exists():
        with terra_comparison.open(newline="", encoding="utf-8") as handle:
            terra_comparison_rows = sum(1 for _ in csv.reader(handle)) - 1
        outputs[terra_comparison.name] = {
            "path": relative(terra_comparison),
            "rows": terra_comparison_rows,
            "size_bytes": terra_comparison.stat().st_size,
            "sha256": sha256_file(terra_comparison),
        }
    metadata = {
        "window": window.key,
        "window_label": window.label,
        "start_utc": window.start.isoformat(),
        "end_exclusive_utc": window.end.isoformat(),
        "target_ilks": list(TARGET_ILKS),
        "state_equations": {
            "ink": "opening ink plus exact signed WAD dink",
            "art": "opening art plus exact signed WAD dart",
            "debt": "art_raw * effective_rate_raw_ray / 1e45 DAI",
            "fork": "source receives negative dink/dart; destination receives positive dink/dart",
        },
        "bark_treatment": "annotation only; Vat.grab is the economic mutation",
        "owner_treatment": "manager owner/proxy annotation; nullable for direct urns",
        "inputs": {
            "boundary_states": {
                "path": relative(
                    stream_paths(window, "boundary_states")["raw"]
                ),
                "sha256": sha256_file(
                    stream_paths(window, "boundary_states")["raw"]
                ),
            },
            "vat_mutations": {
                "path": relative(
                    stream_paths(window, "vat_mutations")["raw"]
                ),
                "sha256": sha256_file(
                    stream_paths(window, "vat_mutations")["raw"]
                ),
            },
            "ownership_history": {
                "path": relative(
                    stream_paths(window, "ownership_history")["raw"]
                ),
                "sha256": sha256_file(
                    stream_paths(window, "ownership_history")["raw"]
                ),
            },
            "effective_rates": {
                "path": relative(sparse_rate_path),
                "sha256": sha256_file(sparse_rate_path),
            },
            "market_panel": {
                "path": relative(MARKET_PATH),
                "sha256": sha256_file(MARKET_PATH),
            },
            "protocol_panel": {
                "path": relative(PROTOCOL_PATH),
                "sha256": sha256_file(PROTOCOL_PATH),
            },
            "liquidation_actions": {
                "path": relative(LIQUIDATION_ACTIONS_PATH),
                "sha256": sha256_file(LIQUIDATION_ACTIONS_PATH),
            },
            "liquidation_auctions": {
                "path": relative(LIQUIDATION_AUCTIONS_PATH),
                "sha256": sha256_file(LIQUIDATION_AUCTIONS_PATH),
            },
            "phase2b_candidates": {
                "path": relative(PHASE2B_CANDIDATES_PATH),
                "sha256": sha256_file(PHASE2B_CANDIDATES_PATH),
            },
        },
        "processing_script_path": relative(Path(__file__)),
        "processing_script_sha256": sha256_file(Path(__file__)),
        "fixed_point_precision": (
            "Python Decimal precision 80; state updates use exact integers; "
            "debt_dai = art_raw * rate_raw_ray / 1e45"
        ),
        "outputs": outputs,
        "created_at_utc": utc_now(),
    }
    write_json_atomic(provenance / "reconstruction_metadata.json", metadata)
    write_json_atomic(provenance / "reconstruction_validation.json", validation)
    return {"metadata": metadata, "validation": validation}


def _get_window(value: str) -> RepresentativeWindow:
    try:
        return WINDOWS[value]
    except KeyError as error:
        raise RepresentativeAcquisitionError(
            f"unknown representative window {value}"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    initialise = sub.add_parser("initialise")
    initialise.add_argument("--window", choices=WINDOWS, required=True)
    initialise.add_argument("--stream", choices=STREAM_COLUMNS, required=True)
    initialise.add_argument("--urn-file", type=Path)
    record = sub.add_parser("record-submission")
    record.add_argument("--window", choices=WINDOWS, required=True)
    record.add_argument("--stream", choices=STREAM_COLUMNS, required=True)
    record.add_argument("--query-id", type=int, required=True)
    record.add_argument("--execution-id", required=True)
    record.add_argument("--query-url", required=True)
    record.add_argument("--usage-before", type=Decimal, required=True)
    result = sub.add_parser("record-result")
    result.add_argument("--window", choices=WINDOWS, required=True)
    result.add_argument("--stream", choices=STREAM_COLUMNS, required=True)
    result.add_argument("--total-rows", type=int, required=True)
    result.add_argument("--execution-state", required=True)
    result.add_argument("--execution-cost-credits", type=Decimal)
    halt = sub.add_parser("halt")
    halt.add_argument("--window", choices=WINDOWS, required=True)
    halt.add_argument("--stream", choices=STREAM_COLUMNS, required=True)
    halt.add_argument("--reason", required=True)
    halt.add_argument("--usage-after", type=Decimal, required=True)
    halt.add_argument("--projected-export-credits", type=Decimal, required=True)
    persist = sub.add_parser("persist")
    persist.add_argument("--window", choices=WINDOWS, required=True)
    persist.add_argument("--stream", choices=STREAM_COLUMNS, required=True)
    persist.add_argument("--usage-after", type=Decimal, required=True)
    reconstruct = sub.add_parser("reconstruct")
    reconstruct.add_argument("--window", choices=WINDOWS, required=True)
    barks = sub.add_parser("validate-barks")
    barks.add_argument("--window", choices=WINDOWS, required=True)
    manifest = sub.add_parser("update-manifest")
    manifest.add_argument("--window", choices=WINDOWS, required=True)
    manifest.add_argument("--starting-usage", type=Decimal, required=True)
    manifest.add_argument("--current-usage", type=Decimal, required=True)
    manifest.add_argument("--quota", type=Decimal, required=True)
    manifest.add_argument("--status", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument(
        "--window", choices=("terra_cefi",), required=True
    )
    preflight.add_argument("--usage", type=Decimal, required=True)
    preflight.add_argument("--quota", type=Decimal, required=True)
    recovery = sub.add_parser("recover-local-mutation-page")
    recovery.add_argument(
        "--window", choices=("terra_cefi",), required=True
    )
    recovery.add_argument("--page-path", type=Path, required=True)
    recovery.add_argument("--usage-before", type=Decimal, required=True)
    recovery.add_argument("--usage-after", type=Decimal, required=True)
    recovery.add_argument("--local-flush-rows", type=int, default=2_000)
    args = parser.parse_args()
    window = _get_window(args.window)
    if args.command == "initialise":
        urns: list[str] = []
        if args.urn_file:
            urns = [
                row["urn"] for row in load_csv(args.urn_file)
            ]
        output = initialise_stream(window, args.stream, urns=urns)
    elif args.command == "record-submission":
        output = record_submission(
            window, args.stream, query_id=args.query_id,
            execution_id=args.execution_id, query_url=args.query_url,
            usage_before=args.usage_before,
        )
    elif args.command == "record-result":
        output = record_result_metadata(
            window, args.stream, total_rows=args.total_rows,
            execution_state=args.execution_state,
            execution_cost_credits=args.execution_cost_credits,
        )
    elif args.command == "persist":
        output = persist_pages(
            window, args.stream, usage_after=args.usage_after
        )
    elif args.command == "halt":
        output = record_halt(
            window, args.stream, reason=args.reason,
            usage_after=args.usage_after,
            projected_export_credits=args.projected_export_credits,
        )
    elif args.command == "validate-barks":
        output = persist_local_bark_annotations(window)
    elif args.command == "update-manifest":
        output = update_window_manifest(
            window,
            starting_usage=args.starting_usage,
            current_usage=args.current_usage,
            quota=args.quota,
            status=args.status,
        )
    elif args.command == "preflight":
        output = write_terra_preflight(usage=args.usage, quota=args.quota)
    elif args.command == "recover-local-mutation-page":
        output = persist_recovered_typed_mutations(
            window=window,
            page_path=args.page_path,
            usage_before=args.usage_before,
            usage_after=args.usage_after,
            local_flush_rows=args.local_flush_rows,
            result_request_count_total=1,
            new_recovery_request_used=False,
        )
    else:
        output = reconstruct_window(window)
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
