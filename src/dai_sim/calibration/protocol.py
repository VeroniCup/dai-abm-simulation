"""Protocol-parameter summaries for empirical calibration."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .data_loading import parse_utc_timestamp, validate_protocol_intervals


def _protocol_outputs(
    frames: dict[str, pd.DataFrame],
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    intervals = validate_protocol_intervals(frames["protocol_intervals"])
    hourly = frames["protocol_hourly"].copy()
    hourly["timestamp_utc"] = parse_utc_timestamp(
        hourly, "timestamp_utc", name="protocol_hourly"
    )
    changes = frames["protocol_changes"].copy()
    changes["effective_time_utc"] = parse_utc_timestamp(
        changes, "effective_time_utc", name="protocol_changes"
    )
    parameters = [
        "liquidation_ratio",
        "liquidation_penalty_rate",
        "debt_ceiling_dai",
        "minimum_debt_dai",
        "annualised_stability_fee",
        "ilk_liquidation_capacity_dai",
        "auction_price_buffer",
        "auction_tail_seconds",
        "auction_cusp",
        "auction_keeper_fraction",
        "auction_keeper_fixed_dai",
        "auction_stopped",
        "effective_liquidation_spot_dai_per_collateral",
    ]
    rows = []
    activations = []
    for ilk, group in hourly.groupby("ilk", sort=True):
        active = group.loc[group["ilk_active"].astype(str).str.lower().isin(
            ["true", "1"]
        )]
        activations.append(
            {
                "ilk": ilk,
                "activation_start_utc": (
                    active["timestamp_utc"].min() if len(active) else None
                ),
                "last_active_hour_utc": (
                    active["timestamp_utc"].max() if len(active) else None
                ),
                "active_hours": int(len(active)),
            }
        )
        for parameter in parameters:
            values = pd.to_numeric(group[parameter], errors="coerce")
            valid = group.loc[values.notna(), ["timestamp_utc"]].copy()
            valid["value"] = values.loc[values.notna()].to_numpy()
            rows.append(
                {
                    "ilk": ilk,
                    "parameter": parameter,
                    "observed_hours": int(len(valid)),
                    "first_effective_hour_utc": (
                        valid["timestamp_utc"].iloc[0]
                        if len(valid) else None
                    ),
                    "last_effective_hour_utc": (
                        valid["timestamp_utc"].iloc[-1]
                        if len(valid) else None
                    ),
                    "first_value": (
                        float(valid["value"].iloc[0]) if len(valid) else None
                    ),
                    "last_value": (
                        float(valid["value"].iloc[-1]) if len(valid) else None
                    ),
                    "minimum_value": (
                        float(valid["value"].min()) if len(valid) else None
                    ),
                    "maximum_value": (
                        float(valid["value"].max()) if len(valid) else None
                    ),
                    "distinct_values": int(valid["value"].nunique()),
                }
            )
    change_counts = (
        changes.groupby(["module", "ilk", "parameter"], dropna=False)
        .size()
        .reset_index(name="change_ledger_rows")
    )
    stopped_defaults = changes.loc[
        changes["parameter"].eq("auction_stopped")
        & changes["state_source"].eq("contract_default")
        & ~changes["is_observed_call"].astype(str).str.lower().isin(
            ["true", "1"]
        )
    ]
    details = {
        "target_ilks": sorted(hourly["ilk"].unique().tolist()),
        "validated_interval_rows": int(len(intervals)),
        "clipper_stopped_default_rows": int(len(stopped_defaults)),
        "clipper_stopped_interpretation": (
            "Contract-default initial state; not an observed governance call."
        ),
    }
    outputs = {
        "protocol/protocol_parameter_summary.csv": pd.DataFrame(rows),
        "protocol/collateral_activation_periods.csv": pd.DataFrame(
            activations
        ),
        "protocol/protocol_change_counts.csv": change_counts,
    }
    return outputs, details
