"""Gas and liquidation-transaction estimators for calibration."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .data_loading import (
    PROJECT_ROOT,
    load_inputs,
    parse_utc_timestamp,
    phase2a_input_specs,
    require_hourly_index,
    sha256_file,
    validate_protocol_intervals,
    verify_all_inputs,
)
from .statistics import (
    _long_matrix,
    aligned_dependence,
    candidate_block_length,
    classify_regimes,
    distribution_summary,
    estimate_regime_thresholds,
    moving_block_bootstrap_ci,
    overdispersion_summary,
    regime_durations,
    transition_counts,
    transition_probabilities,
)




def _gas_outputs(
    hourly: pd.DataFrame,
    block_length: int,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    variables = [
        "median_effective_gas_price_gwei",
        "p90_effective_gas_price_gwei",
        "p99_effective_gas_price_gwei",
        "median_base_fee_gwei",
        "median_priority_fee_gwei",
        "failed_transaction_share",
        "target_normalised_block_utilisation",
    ]
    rows = []
    for sample, sample_mask in (
        ("calibration", hourly["is_calibration"]),
        ("validation_ftx", hourly["is_validation"]),
    ):
        for regime in ("all", "normal", "stress"):
            mask = sample_mask & (
                True if regime == "all" else hourly["regime"].eq(regime)
            )
            for variable in variables:
                rows.append(
                    {
                        "sample": sample,
                        "regime": regime,
                        "variable": variable,
                        **distribution_summary(hourly.loc[mask, variable]),
                    }
                )
    dependence_columns = [
        "median_effective_gas_price_gwei",
        "p99_effective_gas_price_gwei",
        "target_normalised_block_utilisation",
        "failed_transaction_share",
        "eth_log_return",
        "dai_abs_peg_deviation",
        "liquidation_volume_dai",
    ]
    calibration = hourly.loc[hourly["is_calibration"]].copy()
    calibration["absolute_eth_log_return"] = calibration[
        "eth_log_return"
    ].abs()
    dependence_columns.append("absolute_eth_log_return")
    _, pearson, spearman, observations = aligned_dependence(
        calibration, dependence_columns
    )
    matrices = pd.concat(
        [
            _long_matrix(
                pearson,
                matrix_type="pearson_correlation",
                sample="calibration",
                regime="all",
                observations=observations,
            ),
            _long_matrix(
                spearman,
                matrix_type="spearman_rank_correlation",
                sample="calibration",
                regime="all",
                observations=observations,
            ),
        ],
        ignore_index=True,
    )
    sampling = hourly.loc[
        :,
        [
            "timestamp_utc",
            "is_calibration",
            "is_validation",
            "regime",
        ],
    ].copy()
    sampling.insert(0, "source_row", np.arange(len(sampling)))
    sampling["recommended_block_length_hours"] = block_length
    outputs = {
        "gas/gas_distribution.csv": pd.DataFrame(rows),
        "gas/gas_market_dependence.csv": matrices,
        "gas/gas_sampling_index.csv": sampling,
    }
    details = {
        "sampling_representation": (
            "Timestamp/source-row index into the immutable Phase 1B panel; "
            "gas prices remain separate from gas units."
        ),
        "candidate_block_length_hours": block_length,
    }
    return outputs, details


def _classify_take_transactions(
    actions: pd.DataFrame,
    transactions: pd.DataFrame,
    hourly: pd.DataFrame,
) -> pd.DataFrame:
    action = actions.copy()
    action["tx_hash"] = action["tx_hash"].astype(str).str.lower()
    semantic = action.loc[
        action["record_type"].isin(
            ["bark_event", "kick_event", "take_event", "redo_event", "yank_event"]
        )
    ].copy()
    semantic["auction_key"] = (
        semantic["clipper_contract"].astype(str).str.lower()
        + ":"
        + semantic["auction_id"].astype(str)
    )
    grouped = semantic.groupby("tx_hash").agg(
        semantic_action_count=("record_type", "size"),
        take_event_count=("record_type", lambda x: int((x == "take_event").sum())),
        other_event_count=("record_type", lambda x: int((x != "take_event").sum())),
        unique_auctions=("auction_key", "nunique"),
        unique_ilks=("ilk", "nunique"),
    )
    takes = grouped.loc[grouped["take_event_count"] > 0].copy()
    conditions = [
        takes["unique_auctions"] > 1,
        (takes["take_event_count"] == 1) & (takes["other_event_count"] == 0),
        (takes["take_event_count"] > 1) & (takes["unique_auctions"] == 1)
        & (takes["other_event_count"] == 0),
        takes["other_event_count"] > 0,
    ]
    labels = [
        "multiple_auctions",
        "clean_single_take_single_auction",
        "multiple_takes_same_auction",
        "other_liquidation_actions_same_tx",
    ]
    takes["take_transaction_class"] = np.select(
        conditions, labels, default="ambiguous"
    )
    tx = transactions.copy()
    tx["tx_hash"] = tx["tx_hash"].astype(str).str.lower()
    if tx["tx_hash"].duplicated().any():
        raise ValueError("Transaction bridge contains duplicate hashes.")
    result = takes.reset_index().merge(
        tx,
        on="tx_hash",
        how="left",
        validate="one_to_one",
    )
    if result["gas_used"].isna().any():
        raise ValueError("Successful Take transactions lack gas records.")
    result["block_time"] = pd.to_datetime(
        result["block_time"], utc=True, errors="coerce"
    )
    if result["block_time"].isna().any():
        raise ValueError("Take transactions contain invalid timestamps.")
    result["timestamp_utc"] = result["block_time"].dt.floor("h")
    context = hourly[
        [
            "timestamp_utc",
            "eth_price_usd",
            "median_effective_gas_price_gwei",
            "p90_effective_gas_price_gwei",
            "p99_effective_gas_price_gwei",
            "regime",
            "is_calibration",
            "is_validation",
        ]
    ]
    result = result.merge(
        context, on="timestamp_utc", how="left", validate="many_to_one"
    )
    if result["eth_price_usd"].isna().any():
        raise ValueError("Take transactions do not fully join to market hours.")
    for column in ("gas_used", "gas_limit", "gas_price"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if (
        result[["gas_used", "gas_limit", "gas_price"]].isna().any().any()
        or (result["gas_used"] <= 0).any()
        or (result["gas_used"] > result["gas_limit"]).any()
        or (result["gas_price"] < 0).any()
    ):
        raise ValueError("Invalid gas values in successful Take transactions.")
    result["effective_gas_price_gwei"] = result["gas_price"] / 1e9
    cost = calculate_transaction_gas_cost(
        result["gas_used"],
        result["gas_price"],
        result["eth_price_usd"],
    )
    result["transaction_gas_cost_eth"] = cost["cost_eth"]
    result["transaction_gas_cost_usd"] = cost["cost_usd"]
    for label, column in (
        ("median", "median_effective_gas_price_gwei"),
        ("p90", "p90_effective_gas_price_gwei"),
        ("p99", "p99_effective_gas_price_gwei"),
    ):
        result[f"actual_to_hourly_{label}_ratio"] = (
            result["effective_gas_price_gwei"] / result[column]
        )
    return result


def calculate_transaction_gas_cost(
    gas_used: pd.Series,
    gas_price_wei: pd.Series,
    eth_price_usd: pd.Series,
) -> pd.DataFrame:
    """Convert gas units and gas price to ETH and USD without conflation."""
    cost_eth = gas_used.astype(float) * gas_price_wei.astype(float) * 1e-18
    return pd.DataFrame(
        {
            "cost_eth": cost_eth,
            "cost_usd": cost_eth * eth_price_usd.astype(float),
        },
        index=gas_used.index,
    )


def _liquidation_outputs(
    frames: dict[str, pd.DataFrame],
    hourly: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    liquidation = frames["liquidation_hourly"].copy()
    liquidation["timestamp_utc"] = parse_utc_timestamp(
        liquidation, "timestamp_utc", name="liquidation_hourly"
    )
    regime = hourly[
        ["timestamp_utc", "regime", "is_calibration", "is_validation"]
    ]
    liquidation = liquidation.merge(
        regime, on="timestamp_utc", how="left", validate="many_to_one"
    )
    measures = [
        "auctions_initiated",
        "auctions_completed",
        "successful_takes",
        "failed_take_attempts",
        "debt_targeted_dai",
        "debt_repaid_dai",
        "collateral_liquidated_wad",
        "unique_keepers",
        "gas_used_unambiguous",
        "gas_cost_eth_unambiguous",
        "gas_cost_usd_unambiguous",
        "bad_debt_proxy_dai",
    ]
    summaries = []
    for sample, sample_mask in (
        ("calibration", liquidation["is_calibration"]),
        ("validation_ftx", liquidation["is_validation"]),
    ):
        for scope, scope_frame in [
            ("ALL", liquidation.loc[sample_mask].groupby(
                "timestamp_utc", as_index=False
            )[measures].sum()),
            *[
                (
                    ilk,
                    liquidation.loc[sample_mask & liquidation["ilk"].eq(ilk)],
                )
                for ilk in sorted(liquidation["ilk"].unique())
            ],
        ]:
            for regime_name in ("all", "normal", "stress"):
                if scope == "ALL":
                    scoped = scope_frame.merge(
                        regime[["timestamp_utc", "regime"]],
                        on="timestamp_utc",
                        how="left",
                        validate="one_to_one",
                    )
                else:
                    scoped = scope_frame
                selected = scoped if regime_name == "all" else scoped.loc[
                    scoped["regime"].eq(regime_name)
                ]
                for measure in measures:
                    summaries.append(
                        {
                            "sample": sample,
                            "ilk": scope,
                            "regime": regime_name,
                            "measure": measure,
                            **distribution_summary(selected[measure]),
                        }
                    )
    calibration_total = (
        liquidation.loc[liquidation["is_calibration"]]
        .groupby("timestamp_utc")["auctions_initiated"]
        .sum()
    )
    count_rows = [
        {
            "sample": "calibration",
            "ilk": "ALL",
            "regime": "all",
            **overdispersion_summary(calibration_total),
        }
    ]
    for ilk in sorted(liquidation["ilk"].unique()):
        selected = liquidation.loc[
            liquidation["is_calibration"] & liquidation["ilk"].eq(ilk)
        ]
        count_rows.append(
            {
                "sample": "calibration",
                "ilk": ilk,
                "regime": "all",
                **overdispersion_summary(selected["auctions_initiated"]),
            }
        )
    for regime_name in ("normal", "stress"):
        selected = liquidation.loc[
            liquidation["is_calibration"]
            & liquidation["regime"].eq(regime_name)
        ].groupby("timestamp_utc")["auctions_initiated"].sum()
        count_rows.append(
            {
                "sample": "calibration",
                "ilk": "ALL",
                "regime": regime_name,
                **overdispersion_summary(selected),
            }
        )
    auctions = frames["liquidation_auctions"].copy()
    auctions["bark_time_utc"] = parse_utc_timestamp(
        auctions, "bark_time_utc", name="liquidation_auctions"
    )
    auctions["timestamp_utc"] = auctions["bark_time_utc"].dt.floor("h")
    auctions = auctions.merge(
        regime,
        on="timestamp_utc",
        how="left",
        validate="many_to_one",
    )
    if auctions["regime"].isna().any():
        raise ValueError("Liquidation auctions do not fully join to regimes.")
    auction_rows = []
    for sample, sample_mask in (
        ("calibration", auctions["is_calibration"]),
        ("validation_ftx", auctions["is_validation"]),
    ):
        sample_auctions = auctions.loc[sample_mask]
        for ilk, group in [
            ("ALL", sample_auctions),
            *list(sample_auctions.groupby("ilk")),
        ]:
            for regime_name in ("all", "normal", "stress"):
                selected = group if regime_name == "all" else group.loc[
                    group["regime"].eq(regime_name)
                ]
                for measure in (
                    "observed_duration_seconds",
                    "bark_due_dai",
                    "dai_paid",
                    "collateral_sold_wad",
                    "failed_take_attempt_count",
                    "unique_transaction_count",
                ):
                    auction_rows.append(
                        {
                            "sample": sample,
                            "ilk": ilk,
                            "regime": regime_name,
                            "measure": measure,
                            **distribution_summary(selected[measure]),
                        }
                    )
    take_transactions = _classify_take_transactions(
        frames["liquidation_actions"],
        frames["liquidation_transactions"],
        hourly,
    )
    gas_rows = []
    for group_name, group in [
        ("all_successful_take_transactions", take_transactions),
        *list(take_transactions.groupby("take_transaction_class")),
    ]:
        for variable in (
            "gas_used",
            "effective_gas_price_gwei",
            "transaction_gas_cost_eth",
            "transaction_gas_cost_usd",
            "actual_to_hourly_median_ratio",
            "actual_to_hourly_p90_ratio",
            "actual_to_hourly_p99_ratio",
        ):
            gas_rows.append(
                {
                    "transaction_group": group_name,
                    "variable": variable,
                    **distribution_summary(group[variable]),
                }
            )
    outputs = {
        "liquidations/hourly_liquidation_summary.csv": pd.DataFrame(
            summaries
        ),
        "liquidations/liquidation_count_models.csv": pd.DataFrame(count_rows),
        "liquidations/auction_distribution.csv": pd.DataFrame(auction_rows),
        "liquidations/liquidation_transaction_gas.csv": take_transactions,
        "liquidations/liquidation_transaction_gas_summary.csv": pd.DataFrame(
            gas_rows
        ),
    }
    clean = take_transactions.loc[
        take_transactions["take_transaction_class"].eq(
            "clean_single_take_single_auction"
        )
        & take_transactions["is_calibration"]
    ]
    details = {
        "unique_auctions": int(len(auctions)),
        "calibration_auctions": int(auctions["is_calibration"].sum()),
        "successful_take_transactions": int(len(take_transactions)),
        "clean_successful_take_transactions_calibration": int(len(clean)),
        "clean_take_gas_cost_usd": distribution_summary(
            clean["transaction_gas_cost_usd"]
        ),
        "hourly_completion_capacity_calibration": distribution_summary(
            liquidation.loc[liquidation["is_calibration"]]
            .groupby("timestamp_utc")["auctions_completed"]
            .sum()
        ),
        "bad_debt_is_proxy": True,
        "zero_gas_price_successful_take_transactions": int(
            (take_transactions["gas_price"] == 0).sum()
        ),
    }
    return outputs, details
