"""
Build compact Tranche D liquidation-arrival runtime pools.

This script is deterministic and local-only. It verifies already-produced
Phase 2C artefacts, then writes compact runtime pools for the optional
liquidation-arrival demand layer. It does not estimate new parameters.
"""

from __future__ import annotations

from pathlib import Path
import json
import sys

import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from empirical_config import sha256_file  # noqa: E402


TERRA_DIR = (
    REPOSITORY_ROOT
    / "data"
    / "processed"
    / "vaults"
    / "representative_regimes"
    / "terra_cefi_2022-05-05_2022-06-20"
)
PHASE2C_DIR = (
    REPOSITORY_ROOT / "data" / "processed" / "estimation" / "phase2c_liquidations"
)
OUTPUT_DIR = (
    REPOSITORY_ROOT / "data" / "liquidations" / "model_inputs" / "arrival"
)

INPUTS = {
    "stress_tail_diagnostics": {
        "path": TERRA_DIR / "stress_tail_diagnostics.csv",
        "sha256": "d83c82ddda0e7dfe46849b75206f85a1587896355ffde75264566e60e2b8356b",
    },
    "bark_grab_linkage": {
        "path": TERRA_DIR / "bark_grab_linkage.csv",
        "sha256": "e852969ccb4ae1ec9488e9aa1b75953cfcea090af9514ffc51d39c1339007734",
    },
    "liquidation_sequence_summary": {
        "path": TERRA_DIR / "liquidation_sequence_summary.csv",
        "sha256": "afba1e9d5d5b49e375efb52b5c3835a0bdd84fb0fa89dafb6e18be3eef43660d",
    },
    "phase2c_sequence_estimates": {
        "path": PHASE2C_DIR / "liquidation_sequence_estimates.csv",
        "sha256": "8812a42ae6b4942acf2590d2608b426815aea0cef7ffa38375d6aebddba144c2",
    },
}


def _relative(path: Path) -> str:
    return str(path.relative_to(REPOSITORY_ROOT))


def _verify_inputs() -> dict[str, str]:
    observed = {}
    for label, payload in INPUTS.items():
        path = payload["path"]
        actual = sha256_file(path)
        expected = payload["sha256"]
        if actual != expected:
            raise RuntimeError(
                f"{label} checksum mismatch: expected {expected}, observed {actual}."
            )
        observed[_relative(path)] = actual
    return observed


def _source_diagnostics(hourly: pd.DataFrame) -> dict[str, float | int]:
    positive = hourly.loc[hourly["grab_count"] > 0, "grab_count"]
    conditional = hourly["liquidatable_vault_count"] > 0
    conditional_activity = conditional & hourly["activity_indicator"].astype(bool)
    daily = hourly.assign(
        date=pd.to_datetime(hourly["timestamp_utc"], utc=True).dt.date
    ).groupby("date", sort=True)["grab_count"].sum()
    return {
        "hour_count": int(len(hourly)),
        "bark_count": int(hourly["bark_count"].sum()),
        "grab_count": int(hourly["grab_count"].sum()),
        "positive_hour_count": int((hourly["grab_count"] > 0).sum()),
        "zero_hour_share": float((hourly["grab_count"] == 0).mean()),
        "unconditional_activity_probability": float(hourly["activity_indicator"].mean()),
        "conditional_inventory_positive_hours": int(conditional.sum()),
        "conditional_activity_count": int(conditional_activity.sum()),
        "conditional_activity_probability": float(
            conditional_activity.sum() / conditional.sum()
        ),
        "positive_count_minimum": int(positive.min()),
        "positive_count_maximum": int(positive.max()),
        "positive_count_mean": float(positive.mean()),
        "positive_count_median": float(positive.median()),
        "hourly_count_mean": float(hourly["grab_count"].mean()),
        "hourly_count_variance": float(hourly["grab_count"].var(ddof=1)),
        "hourly_variance_to_mean": float(
            hourly["grab_count"].var(ddof=1) / hourly["grab_count"].mean()
        ),
        "maximum_hourly_grabs": int(hourly["grab_count"].max()),
        "maximum_daily_grabs": int(daily.max()),
        "maximum_liquidatable_share": float(hourly["liquidatable_share"].max()),
    }


def build_hourly_pool(stress_tail: pd.DataFrame) -> pd.DataFrame:
    """Return the ALL-scope hourly arrival pool."""
    hourly = stress_tail.loc[stress_tail["collateral_scope"].eq("ALL")].copy()
    hourly["timestamp_utc"] = pd.to_datetime(hourly["timestamp_utc"], utc=True)
    hourly = hourly.sort_values("timestamp_utc").reset_index(drop=True)
    if len(hourly) != 1104:
        raise RuntimeError(f"Expected 1,104 ALL-scope hours, found {len(hourly)}.")
    if hourly["timestamp_utc"].diff().dropna().ne(pd.Timedelta(hours=1)).any():
        raise RuntimeError("ALL-scope stress-tail rows are not hourly contiguous.")
    result = pd.DataFrame(
        {
            "arrival_pool_row_id": range(1, len(hourly) + 1),
            "relative_hour": range(len(hourly)),
            "timestamp_utc": hourly["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source_window": hourly["window"].astype(str),
            "empirical_regime_label": "terra_cefi",
            "liquidatable_vault_count": hourly["liquidatable_vaults"].astype(int),
            "liquidatable_share": hourly["liquidatable_share_all_active"].astype(float),
            "bark_count": hourly["bark_initiations"].astype(int),
            "grab_count": hourly["grab_executions"].astype(int),
        }
    )
    result["activity_indicator"] = (result["grab_count"] > 0).astype(int)
    result["positive_count_eligible"] = result["activity_indicator"]
    result["sequence_id"] = ""
    return result


def build_sequence_pool(sequence_summary: pd.DataFrame) -> pd.DataFrame:
    """Return one compact row per Phase 2C liquidation sequence."""
    sequences = sequence_summary.sort_values(["start_utc", "sequence_id"]).copy()
    starts = pd.to_datetime(sequences["start_utc"], utc=True)
    ends = pd.to_datetime(sequences["end_utc"], utc=True)
    preceding_zero_hours = starts.diff().dt.total_seconds().div(3600).sub(1).clip(lower=0)
    preceding_zero_hours.iloc[0] = 0
    return pd.DataFrame(
        {
            "sequence_id": sequences["sequence_id"].astype(int),
            "relative_sequence_position": range(1, len(sequences) + 1),
            "sequence_start_utc": starts.dt.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "sequence_end_utc": ends.dt.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "hourly_count": sequences["grab_count"].astype(int),
            "positive_run_length": 1,
            "preceding_zero_run_length_hours": preceding_zero_hours.round(6),
            "sequence_size": sequences["grab_count"].astype(int),
            "duration_seconds": sequences["duration_seconds"].astype(int),
            "dominant_ilks": sequences["ilks"].astype(str),
        }
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source_checksums = _verify_inputs()
    stress_tail = pd.read_csv(INPUTS["stress_tail_diagnostics"]["path"])
    bark_grab = pd.read_csv(INPUTS["bark_grab_linkage"]["path"])
    sequences = pd.read_csv(INPUTS["liquidation_sequence_summary"]["path"])
    sequence_estimates = pd.read_csv(INPUTS["phase2c_sequence_estimates"]["path"])

    if len(bark_grab) != 649:
        raise RuntimeError(f"Expected 649 Bark-grab matches, found {len(bark_grab)}.")
    if not bark_grab["linkage_status"].eq("exact_amount_and_identity_match").all():
        raise RuntimeError("Not all Bark-grab rows are exact matches.")
    if len(sequences) != 54:
        raise RuntimeError(f"Expected 54 liquidation sequences, found {len(sequences)}.")
    sequence_rows = sequence_estimates.loc[sequence_estimates["row_type"].eq("sequence")]
    if len(sequence_rows) != 54:
        raise RuntimeError("Phase 2C sequence-estimate row count changed.")

    hourly = build_hourly_pool(stress_tail)
    diagnostics = _source_diagnostics(hourly)
    if diagnostics["bark_count"] != 649 or diagnostics["grab_count"] != 649:
        raise RuntimeError("Hourly Bark/grab counts do not reproduce 649 matches.")
    sequence_pool = build_sequence_pool(sequences)

    hourly_path = OUTPUT_DIR / "hourly_pool.csv"
    sequence_path = OUTPUT_DIR / "sequence_pool.csv"
    hourly.to_csv(hourly_path, index=False, lineterminator="\n")
    sequence_pool.to_csv(sequence_path, index=False, lineterminator="\n")

    manifest = {
        "phase": "tranche_d_liquidation_arrival_runtime_pools",
        "status": "complete",
        "method": (
            "Phase 2C runtime-pool construction only; no parameter estimation "
            "or data acquisition"
        ),
        "source_checksums": source_checksums,
        "outputs": {
            _relative(hourly_path): {
                "rows": int(len(hourly)),
                "columns": int(hourly.shape[1]),
                "sha256": sha256_file(hourly_path),
            },
            _relative(sequence_path): {
                "rows": int(len(sequence_pool)),
                "columns": int(sequence_pool.shape[1]),
                "sha256": sha256_file(sequence_path),
            },
        },
        "diagnostics": diagnostics,
        "sequence_sensitivity": {
            "implemented_in_simulator": False,
            "reason": (
                "The 54 transaction-time sequences are retained as diagnostics, "
                "but Tranche D only activates the primary independent hurdle-count mode."
            ),
        },
        "forbidden_fields_excluded": [
            "transaction_hash",
            "urn",
            "owner",
            "auction_id",
            "raw_event_payload",
        ],
    }
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
