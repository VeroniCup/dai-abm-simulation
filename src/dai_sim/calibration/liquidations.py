"""Local-only Phase 2C liquidation and stress-tail candidate review."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .data_loading import PROJECT_ROOT, sha256_file


getcontext().prec = 80

TARGET_ILKS = ("ETH-A", "ETH-B", "ETH-C", "WBTC-A", "WBTC-B", "WBTC-C")
TERRA_START = pd.Timestamp("2022-05-05T00:00:00Z")
TERRA_END = pd.Timestamp("2022-06-20T00:00:00Z")
DEFAULT_OUTPUT = PROJECT_ROOT / "data/processed/estimation/phase2c_liquidations"
TERRA_DIR = (
    PROJECT_ROOT
    / "data/vaults/processed/representative_regimes/"
    "terra_cefi_2022-05-05_2022-06-20"
)
TERRA_PROVENANCE = (
    PROJECT_ROOT
    / "data/vaults/provenance/representative_regimes/"
    "terra_cefi_2022-05-05_2022-06-20"
)
PHASE1C_ACTIONS = (
    PROJECT_ROOT
    / "data/liquidations/processed/"
    "phase1c_liquidation_actions_2021-06-01_2024-06-30.csv"
)
MARKET_PANEL = (
    PROJECT_ROOT
    / "data/market/processed/dune_hourly_market_prices_processed.csv"
)
PROTOCOL_PANEL = (
    PROJECT_ROOT
    / "data/protocol/processed/phase1d_protocol_parameters_hourly.csv"
)
PHASE2A_REGIMES = (
    PROJECT_ROOT
    / "data/processed/estimation/phase2a/regimes/hourly_regimes.csv"
)
PHASE2B_CANDIDATES = (
    PROJECT_ROOT
    / "data/processed/estimation/phase2b_vaults/"
    "phase2b_parameter_candidates.json"
)
PROTECTED_PATHS = (
    PROJECT_ROOT / "AGENTS.md",
    PROJECT_ROOT / "data/DATA_ACQUISITION_PLAN.md",
)
ALLOWED_STATUSES = {
    "ready_for_review",
    "protocol_value_ready_for_review",
    "provisional_semantic_mismatch",
    "provisional_distribution_choice",
    "blocked_by_model_interface",
    "scenario_only",
    "descriptive_only",
    "insufficient_evidence",
}
CANDIDATE_FIELDS = (
    "parameter",
    "current simulator meaning",
    "empirical analogue",
    "candidate value or distribution reference",
    "units",
    "regime",
    "collateral scope",
    "estimator",
    "sample size",
    "uncertainty",
    "semantic compatibility",
    "review status",
    "adoption prerequisite",
    "notes",
)


@dataclass(frozen=True)
class Phase2CConfig:
    """Controls for a deterministic, network-free review run."""

    output_dir: Path = DEFAULT_OUTPUT
    random_seed: int = 20_260_726
    bootstrap_replications: int = 400
    sequence_gap_seconds: int = 3600
    near_liquidation_relative_buffer: float = 0.05


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    _atomic_text(
        path,
        frame.to_csv(
            index=False,
            lineterminator="\n",
            float_format="%.12g",
        ),
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return _relative(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def _write_json(path: Path, payload: Any) -> None:
    _atomic_text(
        path,
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=_json_default,
        )
        + "\n",
    )


def decimal_fraction(numerator: Any, denominator: Any) -> Decimal | None:
    """Return an exact non-negative fraction, or None for a zero denominator."""
    numerator_decimal = Decimal(str(numerator))
    denominator_decimal = Decimal(str(denominator))
    if denominator_decimal == 0:
        return None
    return abs(numerator_decimal) / abs(denominator_decimal)


def close_factor_distribution(values: Iterable[Decimal | None]) -> dict[str, Any]:
    """Summarise close factors without adding numerical variation."""
    usable = [value for value in values if value is not None]
    if not usable:
        return {
            "usable": 0,
            "excluded": 0,
            "mean": None,
            "standard_deviation": None,
            "minimum": None,
            "median": None,
            "maximum": None,
            "degenerate": False,
        }
    array = np.array([float(value) for value in usable], dtype=float)
    return {
        "usable": len(usable),
        "excluded": sum(value is None for value in values),
        "mean": float(array.mean()),
        "standard_deviation": float(array.std(ddof=0)),
        "minimum": float(array.min()),
        "median": float(np.median(array)),
        "maximum": float(array.max()),
        "degenerate": bool(np.all(array == array[0])),
    }


def collateral_buffers(
    collateral_ratio: pd.Series, liquidation_ratio: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """Return absolute and relative liquidation-ratio buffers."""
    absolute = collateral_ratio - liquidation_ratio
    relative = collateral_ratio / liquidation_ratio - 1.0
    return absolute, relative


def assign_sequences(
    frame: pd.DataFrame, gap_seconds: int = 3600
) -> pd.Series:
    """Assign deterministic sequence IDs after gaps strictly over one hour."""
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if not timestamps.is_monotonic_increasing:
        raise ValueError("Liquidation input must be chronologically sorted")
    starts = timestamps.diff().dt.total_seconds().fillna(np.inf).gt(gap_seconds)
    return starts.cumsum().astype(int)


def _quantiles(series: pd.Series) -> dict[str, float | None]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {
            name: None
            for name in ("minimum", "q01", "q05", "q10", "q25", "median",
                         "mean", "q75", "q90", "q95", "q99", "maximum")
        }
    return {
        "minimum": float(values.min()),
        "q01": float(values.quantile(0.01)),
        "q05": float(values.quantile(0.05)),
        "q10": float(values.quantile(0.10)),
        "q25": float(values.quantile(0.25)),
        "median": float(values.median()),
        "mean": float(values.mean()),
        "q75": float(values.quantile(0.75)),
        "q90": float(values.quantile(0.90)),
        "q95": float(values.quantile(0.95)),
        "q99": float(values.quantile(0.99)),
        "maximum": float(values.max()),
    }


def bootstrap_quantile(
    frame: pd.DataFrame,
    value_column: str,
    quantile: float,
    *,
    seed: int,
    replications: int,
    cluster_column: str | None = None,
) -> tuple[float | None, float | None]:
    """Return a deterministic percentile interval for an empirical quantile."""
    work = frame.dropna(subset=[value_column]).copy()
    if work.empty:
        return None, None
    rng = np.random.default_rng(seed)
    estimates: list[float] = []
    if cluster_column is None:
        values = work[value_column].to_numpy(float)
        for _ in range(replications):
            sample = rng.choice(values, len(values), replace=True)
            estimates.append(float(np.quantile(sample, quantile)))
    else:
        clusters = work[cluster_column].drop_duplicates().tolist()
        cluster_index = {key: index for index, key in enumerate(clusters)}
        values = work[value_column].to_numpy(float)
        codes = work[cluster_column].map(cluster_index).to_numpy(int)
        order = np.argsort(values, kind="stable")
        sorted_values = values[order]
        sorted_codes = codes[order]
        for _ in range(replications):
            counts = rng.multinomial(
                len(clusters),
                np.full(len(clusters), 1.0 / len(clusters)),
            )
            weights = counts[sorted_codes]
            cumulative = np.cumsum(weights)
            target = quantile * max(int(cumulative[-1]) - 1, 0)
            index = int(np.searchsorted(cumulative, target, side="right"))
            estimates.append(float(sorted_values[min(index, len(sorted_values) - 1)]))
    return (
        float(np.quantile(estimates, 0.025)),
        float(np.quantile(estimates, 0.975)),
    )


def semantic_audit() -> pd.DataFrame:
    """Extract and validate the present simulator semantics."""
    model_root = PROJECT_ROOT / "src/dai_sim/model"
    liquidation = (model_root / "liquidation.py").read_text(encoding="utf-8")
    vault = (model_root / "vault.py").read_text(encoding="utf-8")
    required = (
        "debt_repaid = vault.debt_dai * max_close_factor",
        "profitable_df.head(config.max_liquidations_per_step)",
        "vault.partial_liquidate(",
    )
    missing = [fragment for fragment in required if fragment not in liquidation]
    if (
        missing
        or "target_collateral_value_removed = actual_debt_repaid * (" not in vault
    ):
        raise ValueError(f"Simulator semantic extraction failed: {missing}")
    rows = [
        {
            "interpretation": "current_simulator_field",
            "field": "LiquidationConfig.max_close_factor",
            "observed_semantics": (
                "Maximum fraction of one vault's outstanding debt repaid in one "
                "simulated liquidation; collateral removal follows debt repaid "
                "times one plus the penalty, capped by available collateral."
            ),
            "is_throughput_control": False,
            "empirical_analogue": "Vat.grab debt and collateral closure fractions",
            "compatibility": "direct at protocol unsafe-position transition level",
            "recommendation": "Retain the name and review 1.0 as protocol close cap.",
        },
        {
            "interpretation": "separate_capacity_control",
            "field": "LiquidationConfig.max_liquidations_per_step",
            "observed_semantics": (
                "Maximum number of profitable liquidatable vaults executed in one "
                "simulation step after profit ranking."
            ),
            "is_throughput_control": True,
            "empirical_analogue": "hourly grabs, sequence sizes and congestion",
            "compatibility": "compatible after timestep-specific scalar reduction",
            "recommendation": "Do not reinterpret max_close_factor as throughput.",
        },
        {
            "interpretation": "maker_protocol_transition",
            "field": "Maker Vat.grab",
            "observed_semantics": (
                "Transfers the unsafe urn position into liquidation accounting; "
                "all 649 linked Terra/CeFi grabs remove the full urn ink and art."
            ),
            "is_throughput_control": False,
            "empirical_analogue": "protocol full-vault closure",
            "compatibility": "1.0 protocol analogue; not evidence about Take size",
            "recommendation": "Use 1.0 only for the protocol-close interpretation.",
        },
        {
            "interpretation": "maker_auction_execution",
            "field": "Clipper Take progression",
            "observed_semantics": (
                "Auction debt and collateral can be executed through one or more "
                "keeper Takes after Bark/grab."
            ),
            "is_throughput_control": False,
            "empirical_analogue": "per-Take and cumulative auction fractions",
            "compatibility": "requires a distinct distribution or execution field",
            "recommendation": (
                "Do not silently replace max_close_factor with a Take fraction."
            ),
        },
    ]
    return pd.DataFrame(rows)


def _manifest_and_checksums() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_path = TERRA_PROVENANCE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    outputs = manifest["reconstruction"]["outputs"]
    for name in (
        "liquidation_close_factors.csv",
        "bark_grab_linkage.csv",
        "stress_tail_diagnostics.csv",
        "reconstructed_vault_events.csv",
        "reconstructed_vault_snapshots.csv",
        "reconstruction_validation.csv",
        "phase1c_liquidation_auctions.csv",
    ):
        path = PROJECT_ROOT / outputs[name]["path"]
        actual = sha256_file(path)
        expected = outputs[name]["sha256"]
        checks.append({
            "path": _relative(path),
            "expected_sha256": expected,
            "actual_sha256": actual,
            "passed": actual == expected,
        })
    for key in ("liquidation_actions", "market_panel", "protocol_panel"):
        record = manifest["input_checksums"][key]
        path = PROJECT_ROOT / record["path"]
        actual = sha256_file(path)
        checks.append({
            "path": _relative(path),
            "expected_sha256": record["sha256"],
            "actual_sha256": actual,
            "passed": actual == record["sha256"],
        })
    if not all(item["passed"] for item in checks):
        raise ValueError("An authoritative Terra/CeFi checksum differs")
    return manifest, checks


def _validate_inputs() -> dict[str, Any]:
    manifest, checks = _manifest_and_checksums()
    validation = pd.read_csv(TERRA_DIR / "reconstruction_validation.csv").iloc[0]
    close = pd.read_csv(TERRA_DIR / "liquidation_close_factors.csv")
    linkage = pd.read_csv(TERRA_DIR / "bark_grab_linkage.csv")
    events = pd.read_csv(TERRA_DIR / "reconstructed_vault_events.csv")
    debt_fractions = [
        decimal_fraction(numerator, denominator)
        for numerator, denominator in zip(
            close["grab_dart_raw"], close["pre_grab_art_raw"], strict=True
        )
    ]
    collateral_fractions = [
        decimal_fraction(numerator, denominator)
        for numerator, denominator in zip(
            close["grab_dink_raw"], close["pre_grab_ink_raw"], strict=True
        )
    ]
    debt_reduction = [
        float(
            abs(Decimal(str(dart))) * Decimal(str(rate)) / Decimal(10**45)
        )
        for dart, rate in zip(
            close["grab_dart_raw"], close["rate_raw_ray"], strict=True
        )
    ]
    if not bool(validation["validation_passed"]):
        raise ValueError("Terra reconstruction did not pass validation")
    gates = {
        "exact_bark_grab_matches": (
            len(close) == 649
            and len(linkage) == 649
            and linkage["linkage_status"].eq(
                "exact_amount_and_identity_match"
            ).all()
        ),
        "zero_closing_state_mismatches": int(validation["replay_mismatch_count"]) == 0,
        "zero_negative_states": int(validation["negative_event_state_count"]) == 0,
        "six_ilks": set(events["ilk"].dropna()) == set(TARGET_ILKS),
        "phase1c_overlap": int(validation["phase1c_auction_count"]) == 649,
        "close_fraction_formula_reproduced": (
            all(value == Decimal(1) for value in debt_fractions)
            and all(value == Decimal(1) for value in collateral_fractions)
            and np.allclose(
                debt_reduction,
                close["debt_reduction_dai"].to_numpy(float),
                rtol=1e-11,
                atol=1e-8,
            )
        ),
        "bark_grab_amounts_reconcile": (
            (
                linkage["grab_dink_raw"].map(lambda value: abs(Decimal(str(value))))
                == linkage["bark_ink_raw"].map(lambda value: abs(Decimal(str(value))))
            ).all()
            and (
                linkage["grab_dart_raw"].map(lambda value: abs(Decimal(str(value))))
                == linkage["bark_art_raw"].map(lambda value: abs(Decimal(str(value))))
            ).all()
        ),
        "ftx_or_bull_absent": (
            manifest.get("ftx_acquired_or_used") is False
            and not events["window"].astype(str).str.contains(
                "ftx|bull", case=False, regex=True
            ).any()
        ),
    }
    if not all(gates.values()):
        raise ValueError(f"Phase 2C input gate failed: {gates}")
    return {"checksums": checks, "gates": gates}


def _pre_grab_context(close: pd.DataFrame) -> pd.DataFrame:
    work = close.copy()
    work["timestamp_utc"] = pd.to_datetime(work["timestamp_utc"], utc=True)
    work["hour"] = work["timestamp_utc"].dt.floor("h")
    protocol = pd.read_csv(
        PROTOCOL_PANEL, usecols=["timestamp_utc", "ilk", "liquidation_ratio"]
    )
    protocol["hour"] = pd.to_datetime(protocol["timestamp_utc"], utc=True)
    market = pd.read_csv(
        MARKET_PANEL, usecols=["timestamp_utc", "eth_price_usd", "wbtc_price_usd"]
    )
    market["hour"] = pd.to_datetime(market["timestamp_utc"], utc=True)
    work = work.merge(
        protocol[["hour", "ilk", "liquidation_ratio"]],
        on=["hour", "ilk"],
        how="left",
        validate="many_to_one",
    ).merge(
        market[["hour", "eth_price_usd", "wbtc_price_usd"]],
        on="hour",
        how="left",
        validate="many_to_one",
    )
    work["collateral_price_usd"] = np.where(
        work["ilk"].str.startswith("ETH"),
        work["eth_price_usd"],
        work["wbtc_price_usd"],
    )
    ink = work["pre_grab_ink_raw"].map(lambda value: float(Decimal(str(value)) / Decimal(10**18)))
    art = work["pre_grab_art_raw"].map(Decimal)
    rate = work["rate_raw_ray"].map(Decimal)
    work["pre_grab_debt_dai"] = [
        float(a * r / Decimal(10**45)) for a, r in zip(art, rate, strict=True)
    ]
    work["pre_grab_collateral_ratio"] = (
        ink * work["collateral_price_usd"] / work["pre_grab_debt_dai"]
    )
    work["absolute_buffer"] = (
        work["pre_grab_collateral_ratio"] - work["liquidation_ratio"]
    )
    work["relative_buffer"] = (
        work["pre_grab_collateral_ratio"] / work["liquidation_ratio"] - 1.0
    )
    if work[["liquidation_ratio", "collateral_price_usd"]].isna().any().any():
        raise ValueError("Pre-grab price or liquidation ratio join is incomplete")
    return work


def _close_factor_estimates(close: pd.DataFrame, gap_seconds: int) -> pd.DataFrame:
    work = _pre_grab_context(close)
    work = work.sort_values(
        ["timestamp_utc", "block_number", "transaction_index",
         "transaction_hash", "trace_position"],
        kind="stable",
    ).reset_index(drop=True)
    work["sequence_id"] = assign_sequences(work, gap_seconds)
    work["calendar_day"] = work["timestamp_utc"].dt.date.astype(str)
    work["debt_size_quantile"] = pd.qcut(
        work["pre_grab_debt_dai"], 4, labels=["Q1", "Q2", "Q3", "Q4"]
    ).astype(str)
    work["buffer_quantile"] = pd.qcut(
        work["absolute_buffer"], 4, labels=["Q1", "Q2", "Q3", "Q4"]
    ).astype(str)
    groups: list[tuple[str, str, pd.DataFrame]] = [("overall", "ALL", work)]
    for dimension in (
        "ilk", "calendar_day", "sequence_id",
        "debt_size_quantile", "buffer_quantile"
    ):
        groups.extend(
            (dimension, str(value), group)
            for value, group in work.groupby(dimension, observed=True)
        )
    rows: list[dict[str, Any]] = []
    for dimension, value, group in groups:
        for measure, numerator, denominator in (
            ("debt_close_fraction", "grab_dart_raw", "pre_grab_art_raw"),
            ("collateral_close_fraction", "grab_dink_raw", "pre_grab_ink_raw"),
        ):
            exact = [
                decimal_fraction(num, den)
                for num, den in zip(group[numerator], group[denominator], strict=True)
            ]
            summary = close_factor_distribution(exact)
            numeric = pd.Series([float(item) for item in exact if item is not None])
            rows.append({
                "group_dimension": dimension,
                "group_value": value,
                "measure": measure,
                "observations": len(group),
                "usable_observations": summary["usable"],
                "excluded_observations": summary["excluded"],
                "zero_denominator_cases": summary["excluded"],
                "full_closure_count": int((numeric == 1.0).sum()),
                "partial_closure_count": int(((numeric > 0) & (numeric < 1)).sum()),
                "mean": summary["mean"],
                "standard_deviation": summary["standard_deviation"],
                "minimum": summary["minimum"],
                "q10": None if numeric.empty else float(numeric.quantile(0.10)),
                "q25": None if numeric.empty else float(numeric.quantile(0.25)),
                "median": summary["median"],
                "q75": None if numeric.empty else float(numeric.quantile(0.75)),
                "q90": None if numeric.empty else float(numeric.quantile(0.90)),
                "maximum": summary["maximum"],
                "degenerate_exactly_one": (
                    bool(summary["degenerate"]) and summary["minimum"] == 1.0
                ),
                "numerical_uncertainty": (
                    "exact degenerate distribution; no artificial standard error"
                ),
            })
    return pd.DataFrame(rows)


def auction_execution_fractions(
    actions: pd.DataFrame, auctions: pd.DataFrame
) -> pd.DataFrame:
    """Construct exact per-Take and cumulative auction progress where supported."""
    action = actions.copy()
    action["clipper_contract"] = action["clipper_contract"].str.lower()
    action["auction_id"] = pd.to_numeric(action["auction_id"], errors="coerce")
    auction = auctions.copy()
    auction["clipper_contract"] = auction["clipper_contract"].str.lower()
    keys = set(zip(auction["clipper_contract"], auction["auction_id"], strict=True))
    takes = action.loc[action["record_type"].eq("take_event")].copy()
    takes = takes.loc[
        [
            (contract, auction_id) in keys
            for contract, auction_id in zip(
                takes["clipper_contract"], takes["auction_id"], strict=True
            )
        ]
    ]
    takes["block_time"] = pd.to_datetime(takes["block_time"], utc=True)
    takes["event_index"] = pd.to_numeric(takes["event_index"], errors="coerce")
    takes["block_number"] = pd.to_numeric(takes["block_number"], errors="raise")
    auction_lookup = auction.set_index(["clipper_contract", "auction_id"])
    rows: list[dict[str, Any]] = []
    for key, auction_row in auction_lookup.iterrows():
        group = takes.loc[
            takes["clipper_contract"].eq(key[0])
            & takes["auction_id"].eq(key[1])
        ].sort_values(
            ["block_number", "event_index", "tx_hash"], kind="stable"
        )
        initial_tab = float(auction_row["kick_tab_dai"])
        initial_lot = float(auction_row["kick_lot_wad"])
        bark_time = pd.to_datetime(auction_row["bark_time_utc"], utc=True)
        previous_tab = initial_tab
        previous_lot = initial_lot
        take_rows: list[dict[str, Any]] = []
        if group.empty:
            rows.append({
                "row_type": "zero_take_auction",
                "clipper_contract": key[0],
                "auction_id": key[1],
                "ilk": auction_row["ilk"],
                "take_ordinal": None,
                "take_count": 0,
                "take_time_utc": None,
                "seconds_since_bark": None,
                "debt_settled_dai": None,
                "collateral_purchased_wad": None,
                "debt_fraction_of_initial_auction": None,
                "collateral_fraction_of_initial_lot": None,
                "cumulative_debt_fraction": 0.0,
                "cumulative_collateral_fraction": 0.0,
                "remaining_tab_dai": initial_tab,
                "remaining_lot_wad": initial_lot,
                "state_delta_vs_owe_absolute": None,
                "state_delta_vs_owe_relative": None,
                "time_to_25_seconds": None,
                "time_to_50_seconds": None,
                "time_to_75_seconds": None,
                "time_to_100_seconds": None,
                "terminal_classification": auction_row["terminal_classification"],
                "calculation_status": "no successful Take event",
            })
            continue
        for ordinal, (_, take) in enumerate(group.iterrows(), start=1):
            remaining_tab = float(take["remaining_tab_dai"])
            remaining_lot = float(take["remaining_lot_wad"])
            owe = float(take["owe_dai"])
            debt_delta = previous_tab - remaining_tab
            collateral_delta = previous_lot - remaining_lot
            debt_fraction = owe / initial_tab if initial_tab > 0 else np.nan
            collateral_fraction = (
                collateral_delta / initial_lot if initial_lot > 0 else np.nan
            )
            cumulative_debt = (
                (initial_tab - remaining_tab) / initial_tab
                if initial_tab > 0 else np.nan
            )
            cumulative_collateral = (
                (initial_lot - remaining_lot) / initial_lot
                if initial_lot > 0 else np.nan
            )
            discrepancy = abs(debt_delta - owe)
            take_rows.append({
                "row_type": "successful_take",
                "clipper_contract": key[0],
                "auction_id": key[1],
                "ilk": auction_row["ilk"],
                "take_ordinal": ordinal,
                "take_count": len(group),
                "take_time_utc": take["block_time"].isoformat(),
                "seconds_since_bark": (
                    take["block_time"] - bark_time
                ).total_seconds(),
                "debt_settled_dai": owe,
                "collateral_purchased_wad": collateral_delta,
                "debt_fraction_of_initial_auction": debt_fraction,
                "collateral_fraction_of_initial_lot": collateral_fraction,
                "cumulative_debt_fraction": cumulative_debt,
                "cumulative_collateral_fraction": cumulative_collateral,
                "remaining_tab_dai": remaining_tab,
                "remaining_lot_wad": remaining_lot,
                "state_delta_vs_owe_absolute": discrepancy,
                "state_delta_vs_owe_relative": (
                    discrepancy / owe if owe > 0 else None
                ),
                "terminal_classification": auction_row["terminal_classification"],
                "calculation_status": (
                    "exact decoded Take state progression"
                    if collateral_delta >= -1e-12 and debt_delta >= -1e-8
                    else "non-monotonic state; review required"
                ),
            })
            previous_tab = remaining_tab
            previous_lot = remaining_lot
        for threshold in (0.25, 0.50, 0.75, 1.0):
            time_value = next(
                (
                    row["seconds_since_bark"]
                    for row in take_rows
                    if row["cumulative_debt_fraction"] >= threshold - 1e-12
                ),
                None,
            )
            for row in take_rows:
                row[f"time_to_{int(threshold * 100)}_seconds"] = time_value
        rows.extend(take_rows)
    return pd.DataFrame(rows)


def _sequence_estimates(
    close: pd.DataFrame,
    gap_seconds: int,
    *,
    seed: int = 20_260_726,
    replications: int = 400,
) -> pd.DataFrame:
    work = close.copy()
    work["timestamp_utc"] = pd.to_datetime(work["timestamp_utc"], utc=True)
    work = work.sort_values(
        ["timestamp_utc", "block_number", "transaction_index",
         "transaction_hash", "trace_position"],
        kind="stable",
    ).reset_index(drop=True)
    work["sequence_id"] = assign_sequences(work, gap_seconds)
    work["collateral_removed"] = (
        work["grab_dink_raw"].map(lambda value: float(abs(Decimal(str(value))) / Decimal(10**18)))
    )
    rows: list[dict[str, Any]] = []
    for sequence_id, group in work.groupby("sequence_id"):
        intervals = group["timestamp_utc"].diff().dt.total_seconds().dropna()
        counts = group["ilk"].value_counts()
        duration = (
            group["timestamp_utc"].max() - group["timestamp_utc"].min()
        ).total_seconds()
        rows.append({
            "row_type": "sequence",
            "sequence_id": int(sequence_id),
            "start_utc": group["timestamp_utc"].min().isoformat(),
            "end_utc": group["timestamp_utc"].max().isoformat(),
            "duration_seconds": duration,
            "grab_count": len(group),
            "unique_urn_count": group["urn"].nunique(),
            "unique_auction_count": group["auction_id"].nunique(),
            "debt_removed_dai": float(group["debt_reduction_dai"].sum()),
            "collateral_removed": float(group["collateral_removed"].sum()),
            "interarrival_min_seconds": (
                None if intervals.empty else float(intervals.min())
            ),
            "interarrival_median_seconds": (
                None if intervals.empty else float(intervals.median())
            ),
            "interarrival_mean_seconds": (
                None if intervals.empty else float(intervals.mean())
            ),
            "interarrival_max_seconds": (
                None if intervals.empty else float(intervals.max())
            ),
            "dominant_ilk": counts.index[0],
            "dominant_ilk_share": float(counts.iloc[0] / len(group)),
            "ilk_count": int(group["ilk"].nunique()),
            "model_representation": "raw empirical sequence",
            "diagnostic_value": None,
        })
    hours = pd.date_range(TERRA_START, TERRA_END, inclusive="left", freq="h")
    hourly = (
        work.set_index("timestamp_utc").resample("h").size().reindex(hours, fill_value=0)
    )
    daily = work.set_index("timestamp_utc").resample("D").size()
    mean = float(hourly.mean())
    variance = float(hourly.var(ddof=1))
    zero_share = float((hourly == 0).mean())
    diagnostics = {
        "hourly_grab_mean": mean,
        "hourly_grab_variance": variance,
        "hourly_variance_to_mean": variance / mean if mean else None,
        "hourly_zero_share": zero_share,
        "poisson_expected_zero_share": math.exp(-mean),
        "maximum_hourly_grabs": int(hourly.max()),
        "maximum_daily_grabs": int(daily.max()),
        "sequence_count": len(rows),
    }
    sequence_frame = pd.DataFrame(rows)
    rng = np.random.default_rng(seed)
    for column in ("grab_count", "debt_removed_dai", "duration_seconds"):
        values = sequence_frame[column].to_numpy(float)
        estimates = [
            float(rng.choice(values, len(values), replace=True).mean())
            for _ in range(replications)
        ]
        diagnostics[f"sequence_bootstrap_mean_{column}_ci_lower"] = float(
            np.quantile(estimates, 0.025)
        )
        diagnostics[f"sequence_bootstrap_mean_{column}_ci_upper"] = float(
            np.quantile(estimates, 0.975)
        )
    for name, value in diagnostics.items():
        rows.append({
            "row_type": "arrival_model_diagnostic",
            "sequence_id": None,
            "start_utc": None,
            "end_utc": None,
            "duration_seconds": None,
            "grab_count": None,
            "unique_urn_count": None,
            "unique_auction_count": None,
            "debt_removed_dai": None,
            "collateral_removed": None,
            "interarrival_min_seconds": None,
            "interarrival_median_seconds": None,
            "interarrival_mean_seconds": None,
            "interarrival_max_seconds": None,
            "dominant_ilk": None,
            "dominant_ilk_share": None,
            "ilk_count": None,
            "model_representation": name,
            "diagnostic_value": value,
        })
    rows.extend([
        {
            "row_type": "model_comparison",
            "sequence_id": None,
            "start_utc": None,
            "end_utc": None,
            "duration_seconds": None,
            "grab_count": None,
            "unique_urn_count": None,
            "unique_auction_count": None,
            "debt_removed_dai": None,
            "collateral_removed": None,
            "interarrival_min_seconds": None,
            "interarrival_median_seconds": None,
            "interarrival_mean_seconds": None,
            "interarrival_max_seconds": None,
            "dominant_ilk": None,
            "dominant_ilk_share": None,
            "ilk_count": None,
            "model_representation": representation,
            "diagnostic_value": conclusion,
        }
        for representation, conclusion in (
            ("Poisson", "not preferred: observed zero mass and overdispersion differ"),
            ("negative_binomial", "can represent overdispersion but not explicit quiet hurdle"),
            ("hurdle_empirical", "preferred transparent candidate: quiet/stress occurrence plus empirical positive counts"),
            ("self_exciting", "descriptively plausible clustering; complex Hawkes fit deferred"),
        )
    ])
    return pd.DataFrame(rows)


def _duration_above(series: pd.Series, threshold: float) -> dict[str, int]:
    mask = pd.to_numeric(series, errors="coerce").gt(threshold)
    groups = mask.ne(mask.shift(fill_value=False)).cumsum()
    runs = mask.groupby(groups).sum()
    positive = runs[runs > 0]
    return {
        "hours_above": int(mask.sum()),
        "episodes_above": int(len(positive)),
        "longest_run_hours": int(positive.max()) if len(positive) else 0,
    }


def _stress_share_review(
    stress: pd.DataFrame, config: Phase2CConfig
) -> pd.DataFrame:
    work = stress.copy()
    work["timestamp_utc"] = pd.to_datetime(work["timestamp_utc"], utc=True)
    regimes = pd.read_csv(PHASE2A_REGIMES, usecols=["timestamp_utc", "regime"])
    regimes["timestamp_utc"] = pd.to_datetime(regimes["timestamp_utc"], utc=True)
    work = work.merge(regimes, on="timestamp_utc", how="left", validate="many_to_one")
    work["calendar_day"] = work["timestamp_utc"].dt.date.astype(str)
    thresholds = {
        "phase2b_usdc_svb_candidate": 0.0005775460206379942,
        "current_configuration": 0.30,
    }
    rows: list[dict[str, Any]] = []
    for scope, group in work.groupby("collateral_scope", sort=False):
        series = group["liquidatable_share_all_active"]
        summary = _quantiles(series)
        for conditioning, conditioned in (
            ("named_terra_cefi_window", group),
            ("phase2a_classifier_stress", group.loc[group["regime"].eq("stress")]),
            ("phase2a_classifier_normal", group.loc[group["regime"].eq("normal")]),
        ):
            conditioned_summary = _quantiles(
                conditioned["liquidatable_share_all_active"]
            )
            ci = bootstrap_quantile(
                conditioned.assign(
                    calendar_day=conditioned["timestamp_utc"].dt.date.astype(str)
                ),
                "liquidatable_share_all_active",
                0.95,
                seed=config.random_seed,
                replications=config.bootstrap_replications,
                cluster_column="calendar_day",
            )
            row = {
                "collateral_scope": scope,
                "conditioning": conditioning,
                "denominator": "all active urns in scope at start of UTC hour",
                "hours": len(conditioned),
                **conditioned_summary,
                "q95_day_block_ci_lower": ci[0],
                "q95_day_block_ci_upper": ci[1],
            }
            for name, threshold in thresholds.items():
                durations = _duration_above(
                    conditioned["liquidatable_share_all_active"], threshold
                )
                row[f"{name}_threshold"] = threshold
                row[f"{name}_hours_above"] = durations["hours_above"]
                row[f"{name}_episodes_above"] = durations["episodes_above"]
                row[f"{name}_longest_run_hours"] = durations["longest_run_hours"]
            rows.append(row)
        if scope == "ALL" and not math.isclose(
            float(summary["maximum"]), 0.0284697508896797, rel_tol=0, abs_tol=1e-12
        ):
            raise ValueError("Unexpected Terra/CeFi maximum liquidatable share")
    return pd.DataFrame(rows)


def _stress_buffer_review(
    close: pd.DataFrame, config: Phase2CConfig
) -> pd.DataFrame:
    opening = pd.read_csv(TERRA_DIR / "opening_vault_state.csv")
    opening = opening.loc[
        opening["active"].astype(str).str.lower().isin(["true", "1"])
        & opening["debt_dai"].gt(0)
    ].copy()
    opening["absolute_buffer"] = (
        opening["collateral_ratio"] - opening["liquidation_ratio"]
    )
    opening["relative_buffer"] = (
        opening["collateral_ratio"] / opening["liquidation_ratio"] - 1.0
    )
    opening["urn_cluster"] = opening["urn"].str.lower()

    events = pd.read_csv(TERRA_DIR / "reconstructed_vault_events.csv")
    events = events.loc[
        events["debt_after_dai"].gt(0)
        & events["collateral_ratio_after"].notna()
    ].copy()
    events["hour"] = pd.to_datetime(events["timestamp_utc"], utc=True).dt.floor("h")
    protocol = pd.read_csv(
        PROTOCOL_PANEL, usecols=["timestamp_utc", "ilk", "liquidation_ratio"]
    )
    protocol["hour"] = pd.to_datetime(protocol["timestamp_utc"], utc=True)
    events = events.merge(
        protocol[["hour", "ilk", "liquidation_ratio"]],
        on=["hour", "ilk"],
        how="left",
        validate="many_to_one",
    )
    events["absolute_buffer"] = (
        events["collateral_ratio_after"] - events["liquidation_ratio"]
    )
    events["relative_buffer"] = (
        events["collateral_ratio_after"] / events["liquidation_ratio"] - 1.0
    )
    events["urn_cluster"] = events["urn"].str.lower()

    pre = _pre_grab_context(close)
    pre["urn_cluster"] = pre["urn"].str.lower()

    rows: list[dict[str, Any]] = []
    for state_type, frame in (
        ("opening_state", opening),
        ("pre_liquidation_state", pre),
        ("all_reconstructed_stress_post_event_states", events),
    ):
        scopes = [("ALL", frame), ("ETH", frame[frame["ilk"].str.startswith("ETH")]),
                  ("WBTC", frame[frame["ilk"].str.startswith("WBTC")])]
        scopes.extend((ilk, frame[frame["ilk"].eq(ilk)]) for ilk in TARGET_ILKS)
        for scope, group in scopes:
            for measure in ("absolute_buffer", "relative_buffer"):
                summary = _quantiles(group[measure])
                ci = bootstrap_quantile(
                    group,
                    measure,
                    0.05,
                    seed=config.random_seed,
                    replications=config.bootstrap_replications,
                    cluster_column="urn_cluster",
                )
                values = pd.to_numeric(group[measure], errors="coerce").dropna()
                near_threshold = (
                    config.near_liquidation_relative_buffer
                    if measure == "relative_buffer" else 0.05
                )
                rows.append({
                    "state_type": state_type,
                    "collateral_scope": scope,
                    "measure": measure,
                    "observations": len(values),
                    **summary,
                    "q05_urn_cluster_ci_lower": ci[0],
                    "q05_urn_cluster_ci_upper": ci[1],
                    "frequency_at_or_below_zero": (
                        None if values.empty else float((values <= 0).mean())
                    ),
                    "near_liquidation_threshold": near_threshold,
                    "frequency_near_liquidation": (
                        None if values.empty
                        else float((values <= near_threshold).mean())
                    ),
                    "phase2b_quiet_candidate": 0.4927578319238673,
                    "interpretation": (
                        "normal-initialisation evidence remains separate from "
                        "stress-state diagnostics"
                    ),
                })
    return pd.DataFrame(rows)


def _model_interface_review(
    close: pd.DataFrame,
    sequences: pd.DataFrame,
    stress_review: pd.DataFrame,
) -> pd.DataFrame:
    all_stress = stress_review.loc[
        stress_review["collateral_scope"].eq("ALL")
        & stress_review["conditioning"].eq("named_terra_cefi_window")
    ].iloc[0]
    maximum_hourly = sequences.loc[
        sequences["model_representation"].eq("maximum_hourly_grabs"),
        "diagnostic_value",
    ].iloc[0]
    return pd.DataFrame([
        {
            "reviewed_quantity": "protocol close fraction",
            "simulator_field": "LiquidationConfig.max_close_factor",
            "current_value": 1.0,
            "empirical_candidate": 1.0,
            "expected_units": "fraction of one vault's debt",
            "timestep_frequency": "per simulated liquidation",
            "representation": "scalar with collateral override",
            "collateral_specificity": "optional",
            "regime_specificity": "none currently",
            "compatibility_classification": "directly compatible",
            "numerical_difference": 0.0,
            "comparison_meaningful": True,
            "likely_experiment_impact": (
                "Existing scenarios using 0.3 or 0.5 would close more debt per "
                "event if later changed to 1.0."
            ),
        },
        {
            "reviewed_quantity": "liquidation throughput",
            "simulator_field": "LiquidationConfig.max_liquidations_per_step",
            "current_value": "None default; 2-20 in established experiments",
            "empirical_candidate": f"empirical hourly positive-count distribution; maximum {maximum_hourly}",
            "expected_units": "vault liquidations per simulation step",
            "timestep_frequency": "simulation step (normally hourly)",
            "representation": "scalar",
            "collateral_specificity": "global shared keeper capacity",
            "regime_specificity": "needed",
            "compatibility_classification": "compatible after scalar reduction",
            "numerical_difference": None,
            "comparison_meaningful": False,
            "likely_experiment_impact": "May alter backlog, clustering and bad debt.",
        },
        {
            "reviewed_quantity": "stress liquidatable-share threshold",
            "simulator_field": "ConfidenceConfig.max_stress_liquidatable_share",
            "current_value": 0.30,
            "empirical_candidate": {
                "moderate_stress_q95": 0.0005775460206379942,
                "terra_cefi_q95": float(all_stress["q95"]),
                "terra_cefi_maximum": float(all_stress["maximum"]),
            },
            "expected_units": "share of all active vaults",
            "timestep_frequency": "hourly state",
            "representation": "scalar threshold",
            "collateral_specificity": "global in current confidence model",
            "regime_specificity": "evidence is explicitly regime-labelled",
            "compatibility_classification": "compatible after scalar reduction",
            "numerical_difference": float(all_stress["maximum"] - 0.30),
            "comparison_meaningful": True,
            "likely_experiment_impact": (
                "Any empirical threshold is far below 0.30 and would make the "
                "liquidatable-share panic trigger materially more sensitive."
            ),
        },
        {
            "reviewed_quantity": "normal initial collateral-ratio buffer",
            "simulator_field": "generate_*_vaults(min_collateral_ratio_buffer)",
            "current_value": 0.05,
            "empirical_candidate": 0.4927578319238673,
            "expected_units": "absolute collateral-ratio difference",
            "timestep_frequency": "initialisation only",
            "representation": "scalar floor",
            "collateral_specificity": "global",
            "regime_specificity": "quiet normal initialisation",
            "compatibility_classification": "directly compatible",
            "numerical_difference": 0.4427578319238673,
            "comparison_meaningful": True,
            "likely_experiment_impact": (
                "Would raise the generated minimum initial collateral ratio; "
                "Terra stress buffers do not replace this normal-state evidence."
            ),
        },
        {
            "reviewed_quantity": "auction execution fractions",
            "simulator_field": "no distinct field",
            "current_value": None,
            "empirical_candidate": "auction_execution_fractions.csv",
            "expected_units": "fraction of initial auction tab or lot per Take",
            "timestep_frequency": "per Take and elapsed seconds",
            "representation": "empirical distribution",
            "collateral_specificity": "exact ilk",
            "regime_specificity": "Terra/CeFi",
            "compatibility_classification": "requires a new field",
            "numerical_difference": None,
            "comparison_meaningful": False,
            "likely_experiment_impact": "Would separate liquidation initiation from execution.",
        },
        {
            "reviewed_quantity": "liquidation arrival process",
            "simulator_field": "no stochastic arrival-process field",
            "current_value": None,
            "empirical_candidate": "hurdle plus empirical positive hourly counts",
            "expected_units": "count and probability",
            "timestep_frequency": "hourly",
            "representation": "distribution",
            "collateral_specificity": "global with exact-ilk diagnostics",
            "regime_specificity": "Terra/CeFi",
            "compatibility_classification": "requires a distribution interface",
            "numerical_difference": None,
            "comparison_meaningful": False,
            "likely_experiment_impact": "Would introduce exogenous clustered liquidation pressure.",
        },
        {
            "reviewed_quantity": "auction duration",
            "simulator_field": "no auction-duration field",
            "current_value": None,
            "empirical_candidate": "descriptive milestone-time distribution",
            "expected_units": "seconds",
            "timestep_frequency": "auction lifecycle",
            "representation": "distribution",
            "collateral_specificity": "exact ilk",
            "regime_specificity": "Terra/CeFi",
            "compatibility_classification": "descriptive-only",
            "numerical_difference": None,
            "comparison_meaningful": False,
            "likely_experiment_impact": "Cannot affect the current one-stage liquidation model.",
        },
    ])


def _candidate(**record: Any) -> dict[str, Any]:
    missing = [field for field in CANDIDATE_FIELDS if field not in record]
    if missing:
        raise ValueError(f"Phase 2C candidate lacks fields: {missing}")
    if record["review status"] not in ALLOWED_STATUSES:
        raise ValueError("Invalid Phase 2C review status")
    return {field: record[field] for field in CANDIDATE_FIELDS}


def _candidates(
    close: pd.DataFrame,
    auction: pd.DataFrame,
    sequences: pd.DataFrame,
    stress: pd.DataFrame,
    buffers: pd.DataFrame,
) -> list[dict[str, Any]]:
    all_stress = stress.loc[
        stress["collateral_scope"].eq("ALL")
        & stress["conditioning"].eq("named_terra_cefi_window")
    ].iloc[0]
    sequence_rows = sequences.loc[sequences["row_type"].eq("sequence")]
    takes = auction.loc[auction["row_type"].eq("successful_take")]
    return [
        _candidate(**{
            "parameter": "max_close_factor",
            "current simulator meaning": (
                "maximum share of an individual vault's debt repaid in one "
                "simulated liquidation"
            ),
            "empirical analogue": "full unsafe-position transition by Vat.grab",
            "candidate value or distribution reference": 1.0,
            "units": "fraction of pre-liquidation vault debt",
            "regime": "Terra/CeFi",
            "collateral scope": "six ilks; optional collateral override exists",
            "estimator": "abs(grab.dart) / pre-grab art using exact integer values",
            "sample size": len(close),
            "uncertainty": (
                "exact degenerate distribution; structural uncertainty is the "
                "protocol-transition versus simulator-stage mapping"
            ),
            "semantic compatibility": (
                "compatible only at protocol close stage; not keeper throughput "
                "or per-Take execution size"
            ),
            "review status": "protocol_value_ready_for_review",
            "adoption prerequisite": (
                "explicit model-design decision to retain the one-stage "
                "liquidation abstraction and backward-compatibility review"
            ),
            "notes": "No candidate was adopted; all 649 usable values equal 1.0.",
        }),
        _candidate(**{
            "parameter": "auction_execution_fraction",
            "current simulator meaning": "no separate simulator field",
            "empirical analogue": "debt and collateral progressed per Clipper Take",
            "candidate value or distribution reference": "auction_execution_fractions.csv",
            "units": "fraction of initial auction tab or lot",
            "regime": "Terra/CeFi",
            "collateral scope": "six exact ilks",
            "estimator": "decoded remaining state difference and owe per Take",
            "sample size": int(len(takes)),
            "uncertainty": "empirical distribution; state reconciliation flags retained",
            "semantic compatibility": "distinct from max_close_factor",
            "review status": "blocked_by_model_interface",
            "adoption prerequisite": "new auction-execution distribution field",
            "notes": "Zero-Take and incomplete auctions remain explicit.",
        }),
        _candidate(**{
            "parameter": "max_liquidations_per_step",
            "current simulator meaning": "global count cap after keeper-profit ranking",
            "empirical analogue": "hourly grab throughput and positive sequence counts",
            "candidate value or distribution reference": "liquidation_sequence_estimates.csv",
            "units": "liquidations per hourly simulation step",
            "regime": "Terra/CeFi",
            "collateral scope": "shared global capacity; exact-ilk concentration retained",
            "estimator": "empirical hourly counts and 54 one-hour-gap sequences",
            "sample size": int(len(close)),
            "uncertainty": "sequence/day dependence; raw empirical distribution preferred",
            "semantic compatibility": "compatible only after scalar reduction",
            "review status": "provisional_distribution_choice",
            "adoption prerequisite": "choose scalar sensitivity or add regime distribution",
            "notes": (
                f"{len(sequence_rows)} sequences; do not treat max_close_factor "
                "as this capacity control."
            ),
        }),
        _candidate(**{
            "parameter": "liquidation_arrival_process",
            "current simulator meaning": "no distinct exogenous arrival process",
            "empirical analogue": "quiet-hour hurdle and clustered positive grab counts",
            "candidate value or distribution reference": "hurdle + empirical positive counts",
            "units": "hourly occurrence probability and conditional count",
            "regime": "Terra/CeFi",
            "collateral scope": "global; ilk concentration diagnostic",
            "estimator": "empirical zero mass, overdispersion and sequence distribution",
            "sample size": 46 * 24,
            "uncertainty": "one purposive stress window; no complex Hawkes fit",
            "semantic compatibility": "not present in current model",
            "review status": "blocked_by_model_interface",
            "adoption prerequisite": "new distribution interface and cross-window review",
            "notes": "Poisson is not preferred; a transparent hurdle is recommended.",
        }),
        _candidate(**{
            "parameter": "max_stress_liquidatable_share",
            "current simulator meaning": "panic trigger share among all active vaults",
            "empirical analogue": "hourly liquidatable urns divided by all active urns",
            "candidate value or distribution reference": {
                "moderate_usdc_svb_q95": 0.0005775460206379942,
                "terra_cefi_q95": float(all_stress["q95"]),
                "terra_cefi_maximum": float(all_stress["maximum"]),
            },
            "units": "share of all active vaults",
            "regime": "labelled hierarchy: moderate USDC/SVB and severe Terra/CeFi",
            "collateral scope": "global primary; exact-ilk diagnostics",
            "estimator": "hourly empirical q95 and maximum with day-block interval",
            "sample size": int(all_stress["hours"]),
            "uncertainty": {
                "terra_q95_day_block_interval": [
                    all_stress["q95_day_block_ci_lower"],
                    all_stress["q95_day_block_ci_upper"],
                ]
            },
            "semantic compatibility": "scalar interface cannot preserve severity hierarchy",
            "review status": "provisional_distribution_choice",
            "adoption prerequisite": "choose declared stress severity or add regime-specific threshold",
            "notes": (
                "Retain 0.000577546 as moderate-stress evidence; do not pool "
                "labelled windows or supersede it silently."
            ),
        }),
        _candidate(**{
            "parameter": "min_collateral_ratio_buffer",
            "current simulator meaning": "absolute floor above liquidation ratio at initialisation",
            "empirical analogue": "lower tail of opening collateral-ratio buffer",
            "candidate value or distribution reference": 0.4927578319238673,
            "units": "absolute collateral-ratio difference",
            "regime": "quiet normal initialisation; Terra/CeFi is stress validation",
            "collateral scope": "global scalar with exact-ilk review",
            "estimator": "quiet opening q05 retained from Phase 2B",
            "sample size": int(
                buffers.loc[
                    buffers["state_type"].eq("opening_state")
                    & buffers["collateral_scope"].eq("ALL")
                    & buffers["measure"].eq("absolute_buffer"),
                    "observations",
                ].iloc[0]
            ),
            "uncertainty": "Phase 2B urn-cluster interval; Terra tail shown separately",
            "semantic compatibility": "direct for normal initialisation only",
            "review status": "ready_for_review",
            "adoption prerequisite": "review clipping and collateral-specific sensitivity",
            "notes": "Do not replace with the Terra minimum or use it as stress dynamics.",
        }),
        _candidate(**{
            "parameter": "auction_duration",
            "current simulator meaning": "no explicit auction lifecycle",
            "empirical analogue": "Bark-to-completion milestone times",
            "candidate value or distribution reference": "auction_execution_fractions.csv",
            "units": "seconds",
            "regime": "Terra/CeFi",
            "collateral scope": "six exact ilks",
            "estimator": "elapsed time from Bark to cumulative debt milestones",
            "sample size": int(
                auction[["clipper_contract", "auction_id"]]
                .drop_duplicates()
                .shape[0]
            ),
            "uncertainty": "bounded Phase 1C lifecycle and decoded state limitations",
            "semantic compatibility": "cannot be represented by current one-stage model",
            "review status": "descriptive_only",
            "adoption prerequisite": "explicit multi-stage auction mechanics",
            "notes": "Descriptive review only; no simulator mechanics changed.",
        }),
    ]


def _status(candidates: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "parameter": candidate["parameter"],
            "status": candidate["review status"],
            "has_review_candidate": True,
            "adopted": False,
            "semantic_compatibility": candidate["semantic compatibility"],
            "adoption_prerequisite": candidate["adoption prerequisite"],
        }
        for candidate in candidates
    ])


def run_phase2c(config: Phase2CConfig = Phase2CConfig()) -> dict[str, Any]:
    """Run the complete local Phase 2C review and write deterministic artefacts."""
    protected_initial = {
        _relative(path): sha256_file(path) for path in PROTECTED_PATHS
    }
    input_validation = _validate_inputs()
    audit = semantic_audit()
    close = pd.read_csv(TERRA_DIR / "liquidation_close_factors.csv", dtype={
        "pre_grab_ink_raw": str,
        "pre_grab_art_raw": str,
        "grab_dink_raw": str,
        "grab_dart_raw": str,
        "rate_raw_ray": str,
    })
    close_estimates = _close_factor_estimates(
        close, config.sequence_gap_seconds
    )
    actions = pd.read_csv(PHASE1C_ACTIONS, low_memory=False)
    auctions = pd.read_csv(TERRA_DIR / "phase1c_liquidation_auctions.csv")
    auction_estimates = auction_execution_fractions(actions, auctions)
    sequence_estimates = _sequence_estimates(
        close,
        config.sequence_gap_seconds,
        seed=config.random_seed,
        replications=config.bootstrap_replications,
    )
    stress = pd.read_csv(TERRA_DIR / "stress_tail_diagnostics.csv")
    stress_review = _stress_share_review(stress, config)
    buffer_review = _stress_buffer_review(close, config)
    interface = _model_interface_review(
        close, sequence_estimates, stress_review
    )
    candidates = _candidates(
        close, auction_estimates, sequence_estimates, stress_review, buffer_review
    )
    status = _status(candidates)

    outputs = {
        "close_factor_semantic_audit.csv": audit,
        "close_factor_estimates.csv": close_estimates,
        "auction_execution_fractions.csv": auction_estimates,
        "liquidation_sequence_estimates.csv": sequence_estimates,
        "stress_liquidatable_share_review.csv": stress_review,
        "stress_buffer_review.csv": buffer_review,
        "model_interface_review.csv": interface,
        "phase2c_parameter_status.csv": status,
    }
    for name, frame in outputs.items():
        _write_csv(config.output_dir / name, frame)

    registry = {
        "phase": "2C",
        "status": "review_only_not_adopted",
        "random_seed": config.random_seed,
        "bootstrap_replications": config.bootstrap_replications,
        "candidate_schema": list(CANDIDATE_FIELDS),
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "candidates": candidates,
        "recommended_model_design_decision": (
            "Retain max_close_factor as a protocol-close fraction and review 1.0; "
            "keep max_liquidations_per_step as the separate capacity control. "
            "If auction execution is later modelled, add a distinct Take-size or "
            "completion distribution without changing established experiment "
            "semantics silently."
        ),
        "no_candidate_adopted": True,
    }
    registry_path = config.output_dir / "phase2c_parameter_candidates.json"
    _write_json(registry_path, registry)

    protected_final = {
        _relative(path): sha256_file(path) for path in PROTECTED_PATHS
    }
    if protected_initial != protected_final:
        raise ValueError("A protected working-tree file changed during Phase 2C")
    output_records: dict[str, Any] = {}
    for path in sorted(config.output_dir.glob("*")):
        if path.is_file() and path.name != "phase2c_run_metadata.json":
            if path.suffix == ".csv":
                frame = pd.read_csv(path)
                dimensions = [len(frame), len(frame.columns)]
            else:
                json.loads(path.read_text(encoding="utf-8"))
                dimensions = None
            output_records[path.name] = {
                "path": _relative(path),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                "dimensions": dimensions,
            }
    metadata = {
        "phase": "2C",
        "method": "local review-only estimation",
        "network_access": False,
        "configuration_written": False,
        "simulator_mechanics_written": False,
        "candidate_adopted": False,
        "random_seed": config.random_seed,
        "bootstrap_replications": config.bootstrap_replications,
        "input_validation": input_validation,
        "protected_initial_sha256": protected_initial,
        "protected_final_sha256": protected_final,
        "outputs": output_records,
        "source_checksums": {
            "estimation_script": sha256_file(Path(__file__)),
            "phase2b_candidates": sha256_file(PHASE2B_CANDIDATES),
            "phase2a_regimes": sha256_file(PHASE2A_REGIMES),
            "liquidation_implementation": sha256_file(
                PROJECT_ROOT / "src/dai_sim/model/liquidation.py"
            ),
            "vault_implementation": sha256_file(
                PROJECT_ROOT / "src/dai_sim/model/vault.py"
            ),
        },
        "substantive_counts": {
            "close_factor_observations": len(close),
            "exact_full_debt_closures": int(
                close["debt_close_fraction"].eq(1).sum()
            ),
            "partial_debt_closures": int(
                close["debt_close_fraction"].between(0, 1, inclusive="neither").sum()
            ),
            "sequences": int(
                sequence_estimates["row_type"].eq("sequence").sum()
            ),
            "auctions": int(auctions["auction_id"].count()),
            "successful_takes": int(
                auction_estimates["row_type"].eq("successful_take").sum()
            ),
        },
    }
    metadata_path = config.output_dir / "phase2c_run_metadata.json"
    _write_json(metadata_path, metadata)
    json.loads(metadata_path.read_text(encoding="utf-8"))
    return {
        "output_dir": _relative(config.output_dir),
        "registry_path": _relative(registry_path),
        "metadata_path": _relative(metadata_path),
        "candidate_count": len(candidates),
        "output_checksums": {
            name: record["sha256"] for name, record in output_records.items()
        },
    }
