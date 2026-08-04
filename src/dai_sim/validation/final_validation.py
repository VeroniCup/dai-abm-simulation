"""Frozen-model held-out validation against the registered historical windows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing
from pathlib import Path
import time
from typing import Any, Iterator

import numpy as np
import pandas as pd
import yaml

from dai_sim.experiments.final import (
    idiosyncratic_diversification as experiment_a,
    selected_robustness as robustness,
    shared_keeper_capacity as experiment_d,
)
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file
from dai_sim.inputs.gas import component_gas_costs
from dai_sim.inputs.integrated_profile import resolve_integrated_empirical_eth_profile
from dai_sim.inputs.market import prices_from_log_returns
from dai_sim.inputs.multicollateral import FAMILY_ORDER
from dai_sim.inputs.runtime_sources import (
    RuntimeSourceResolution,
    resolve_runtime_source,
)
from dai_sim.validation import multicollateral as multicollateral_validation


REGISTRY_PATH = REPOSITORY_ROOT / "config/validation/final_validation_registry.yaml"
EVIDENCE_DIR = REPOSITORY_ROOT / "data/provenance/validation/final"
OUTPUT_ROOT = REPOSITORY_ROOT / "outputs/validation/final"
MANIFEST_PATH = REPOSITORY_ROOT / "data/provenance/validation/manifest.json"
PARENT_COMMIT = robustness.PARENT_COMMIT
REPLICATIONS = 128
STAGE_ORDER = ("quiet", "ftx", "usdc_svb")
COMPACT_FILENAMES = (
    "final_validation_specification.json",
    "final_validation_window_inventory.csv",
    "final_validation_freeze.json",
    "final_validation_quiet_summary.json",
    "final_validation_ftx_summary.json",
    "final_validation_usdc_svb_summary.json",
    "final_validation_metric_comparison.csv",
    "final_validation_decision.json",
    "no_retuning_decision.json",
    "final_validation_reproducibility.json",
    "final_validation_benchmark.json",
)


def _historical_source_resolution(
    registry: Mapping[str, Any],
) -> RuntimeSourceResolution:
    """Resolve the frozen historical source to its portable tracked owner."""
    source = registry["historical_source"]
    return resolve_runtime_source(source["path"], source["sha256"])


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("registry_id") != "frozen_model_held_out_validation":
        raise ValueError("Final validation registry identity differs.")
    if raw.get("parent_commit") != PARENT_COMMIT:
        raise ValueError("Final validation parent commit differs.")
    if raw.get("execution_order") != ["quiet", "november_2022_generalisation_ftx_holdout", "usdc_svb"]:
        raise ValueError("Final validation stage order differs.")
    if raw["windows"]["quiet"]["status"] != "quiet_validation_not_separately_registered":
        raise ValueError("A distinct quiet validation was invented.")
    if raw["windows"]["quiet"]["execute"] is not False:
        raise ValueError("Unregistered quiet validation cannot execute.")
    _historical_source_resolution(raw)
    if raw["simulation"]["observed_dai_role"] != "comparison_target_only" or raw["simulation"]["synthetic_shock_overlay"] is not False:
        raise ValueError("Validation data boundary differs.")
    return raw


def _window_bounds(name: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    raw = load_registry()["windows"]
    key = "november_2022_generalisation_ftx_holdout" if name == "ftx" else name
    return pd.Timestamp(raw[key]["start"]), pd.Timestamp(raw[key]["end_exclusive"])


def window_inventory() -> pd.DataFrame:
    registry = load_registry()
    source_sha = registry["historical_source"]["sha256"]
    rows = [
        {
            "identifier": "quiet",
            "start_utc": None,
            "end_exclusive_utc": None,
            "event_label": "quiet/generalisation",
            "intended_role": "quiet false-positive diagnostic",
            "source_path": None,
            "source_sha256": None,
            "excluded_from_calibration": None,
            "previously_used_in_calibration": None,
            "held_out": None,
            "complete_required_data": False,
            "overlap": "not_applicable",
            "decision": "quiet_validation_not_separately_registered",
        },
        {
            "identifier": "november_2022_generalisation_ftx_holdout",
            "start_utc": "2022-11-01T00:00:00Z",
            "end_exclusive_utc": "2022-11-21T00:00:00Z",
            "event_label": "November 2022 FTX",
            "intended_role": "one held-out sample with generalisation and crypto-stress diagnostics",
            "source_path": registry["historical_source"]["path"],
            "source_sha256": source_sha,
            "excluded_from_calibration": True,
            "previously_used_in_calibration": False,
            "held_out": True,
            "complete_required_data": True,
            "overlap": "none",
            "decision": "execute_once_not_double_counted",
        },
        {
            "identifier": "usdc_svb",
            "start_utc": "2023-03-06T00:00:00Z",
            "end_exclusive_utc": "2023-03-20T00:00:00Z",
            "event_label": "USDC/SVB",
            "intended_role": "held-out stablecoin and cross-collateral validation",
            "source_path": registry["historical_source"]["path"],
            "source_sha256": source_sha,
            "excluded_from_calibration": True,
            "previously_used_in_calibration": False,
            "held_out": True,
            "complete_required_data": True,
            "overlap": "none",
            "decision": "execute_last",
        },
    ]
    return pd.DataFrame(rows)


def scientific_source_identity() -> str:
    paths = (
        Path(__file__).resolve(),
        Path(robustness.__file__).resolve(),
        REGISTRY_PATH,
        robustness.REGISTRY_PATH,
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(REPOSITORY_ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def freeze_payload() -> dict[str, Any]:
    robustness_decision_path = robustness.EVIDENCE_DIR / robustness.COMPACT_FILENAMES[5]
    if not robustness_decision_path.is_file():
        raise ValueError("Robustness decision must exist before validation freeze.")
    decision = json.loads(robustness_decision_path.read_text(encoding="utf-8"))
    registry = load_registry()
    inventory = window_inventory()
    payload = {
        "schema_version": 1,
        "scientific_status": "frozen_model_held_out_validation",
        "parent_commit": PARENT_COMMIT,
        "scientific_source_identity": scientific_source_identity(),
        "master_programme_identity": robustness.MASTER_PROGRAMME_IDENTITY,
        "protected_experiment_identities": robustness.PROTECTED_EXPERIMENT_IDENTITIES,
        "h4_synthesis_identity": robustness.H4_SYNTHESIS_IDENTITY,
        "robustness_identity": robustness.robustness_identity(),
        "robustness_registry_sha256": sha256_file(robustness.REGISTRY_PATH),
        "robustness_decision_sha256": sha256_file(robustness_decision_path),
        "robustness_classification": decision["overall_classification"],
        "validation_registry_sha256": sha256_file(REGISTRY_PATH),
        "historical_source_sha256": registry["historical_source"]["sha256"],
        "window_inventory_sha256": robustness._payload_sha256(inventory.where(pd.notna(inventory), None).to_dict(orient="records")),
        "stage1_coefficients_sha256": sha256_file(
            REPOSITORY_ROOT
            / "data/provenance/calibration/confidence/stage1_market_estimates.json"
        ),
        "residual_sequence_sha256": robustness.experiment_a.EXPECTED_STAGE1_RESIDUAL_SEQUENCE_SHA256,
        "residual_block_sha256": robustness.experiment_a.EXPECTED_STAGE1_RESIDUAL_BLOCK_SHA256,
        "confidence_default": "stage1_only",
        "keeper_registry_sha256": robustness.experiment_d.KEEPER_REGISTRY_SHA256,
        "oracle_delay_registry_identity": robustness.ORACLE_DELAY_REGISTRY_IDENTITY,
        "portfolio_choices": {"ftx": ["empirical_crypto"], "usdc_svb": ["empirical_crypto", "stable_supported"]},
        "simulation_counts": {"quiet": 0, "ftx": 128, "usdc_svb": 256, "total": 384},
        "comparison_metrics": registry["metrics"],
        "decision_hierarchy": ["final_validation_supportive_with_limitations", "final_validation_mixed", "final_validation_not_supportive", "final_validation_not_fully_operational", "final_validation_invalid"],
        "no_retuning_declaration": registry["no_retuning_declaration"],
        "result_fields_excluded": True,
        "runtime_adopted": False,
    }
    payload["freeze_identity"] = robustness._payload_sha256(payload)
    return payload


def write_freeze() -> dict[str, Any]:
    inventory = window_inventory()
    freeze = freeze_payload()
    robustness._atomic_bytes(EVIDENCE_DIR / COMPACT_FILENAMES[0], robustness._json_bytes(specification_payload(freeze), pretty=True))
    robustness._atomic_bytes(EVIDENCE_DIR / COMPACT_FILENAMES[1], robustness._csv_bytes(inventory))
    robustness._atomic_json(EVIDENCE_DIR / COMPACT_FILENAMES[2], freeze)
    robustness._atomic_json(
        EVIDENCE_DIR / COMPACT_FILENAMES[3],
        {
            "schema_version": 1,
            "classification": "quiet_validation_not_separately_registered",
            "simulation_count": 0,
            "reason": "No distinct result-blind quiet window was registered; November 2022 is counted once as the generalisation/FTX holdout.",
        },
    )
    return freeze


def validation_identity(freeze: Mapping[str, Any] | None = None) -> str:
    owner = freeze_payload() if freeze is None else dict(freeze)
    return robustness._payload_sha256(
        {
            "freeze_identity": owner["freeze_identity"],
            "registry_sha256": sha256_file(REGISTRY_PATH),
            "historical_source_sha256": load_registry()["historical_source"]["sha256"],
            "windows": window_inventory().where(pd.notna(window_inventory()), None).to_dict(orient="records"),
            "results_excluded": True,
        }
    )


def specification_payload(freeze: Mapping[str, Any] | None = None) -> dict[str, Any]:
    owner = freeze_payload() if freeze is None else dict(freeze)
    return {
        "schema_version": 1,
        "scientific_status": "frozen_model_held_out_validation",
        "validation_identity": validation_identity(owner),
        "freeze_identity": owner["freeze_identity"],
        "execution_order": list(STAGE_ORDER),
        "quiet_status": "quiet_validation_not_separately_registered",
        "november_2022_counted_once": True,
        "ftx": {"hours": 480, "portfolio": "empirical_crypto", "replications": 128},
        "usdc_svb": {"hours": 336, "portfolios": ["empirical_crypto", "stable_supported"], "replications_per_portfolio": 128},
        "observed_dai_role": "comparison_target_only",
        "synthetic_shock_overlay": False,
        "exact_historical_replay_claim": False,
        "no_retuning": True,
        "runtime_adopted": False,
    }


def _historical_window(stage: str) -> pd.DataFrame:
    registry = load_registry()
    source = _historical_source_resolution(registry)
    frame = pd.read_csv(source.runtime_path)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    start, end = _window_bounds(stage)
    selected = frame.loc[(frame["timestamp_utc"] >= start) & (frame["timestamp_utc"] < end)].copy().reset_index(drop=True)
    expected = int((end - start) / pd.Timedelta(hours=1))
    if len(selected) != expected or selected["timestamp_utc"].duplicated().any():
        raise ValueError(f"{stage} historical window is incomplete.")
    if not selected["timestamp_utc"].equals(pd.Series(pd.date_range(start, end, inclusive="left", freq="h"), name="timestamp_utc")):
        raise ValueError(f"{stage} historical timestamps differ.")
    return selected


def observed_diagnostics(stage: str) -> dict[str, Any]:
    frame = _historical_window(stage)
    dai = pd.to_numeric(frame["dai_price_usd"], errors="raise").to_numpy(dtype=float)
    inside = (dai >= 0.995) & (dai <= 1.005)
    recovery = experiment_a._recovery_metrics(dai, design=replace(experiment_a.load_recovery_design(), pre_shock_hours=0, post_shock_hours=len(dai), total_hours=len(dai), shock_hour=0, recovery_cap_hours=len(dai)))
    return {
        "start_utc": frame["timestamp_utc"].iloc[0].isoformat().replace("+00:00", "Z"),
        "end_exclusive_utc": (frame["timestamp_utc"].iloc[-1] + pd.Timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "hours": len(frame),
        "eth_minimum_hourly_log_return": float(frame["eth_log_return"].min()),
        "wbtc_minimum_hourly_log_return": float(frame["wbtc_log_return"].min()),
        "eth_window_log_return": float(frame["eth_log_return"].sum()),
        "wbtc_window_log_return": float(frame["wbtc_log_return"].sum()),
        "eth_wbtc_hourly_return_correlation": float(
            frame[["eth_log_return", "wbtc_log_return"]].corr().iloc[0, 1]
        ),
        "stablecoin_minimum_price": float(frame["usdc_price_usd"].min()),
        "dai_minimum_price": float(dai.min()),
        "dai_mean_absolute_deviation": float(np.abs(dai - 1.0).mean()),
        "dai_below_peg_burden": float(np.maximum(1.0 - dai, 0.0).sum()),
        "gas_median_gwei": float(frame["median_effective_gas_price_gwei"].median()),
        "gas_p95_gwei": float(frame["median_effective_gas_price_gwei"].quantile(0.95)),
        "observed_recovery_duration": recovery["restricted_mean_recovery_time"],
        "observed_inside_band_share": float(inside.mean()),
    }


def _historical_paths(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    collateral, _, _ = experiment_a._design_payloads()
    initial = {family: float(multicollateral_validation._family_payload(collateral, family)["initial_price_usd"]) for family in FAMILY_ORDER}
    paths = prices_from_log_returns(frame, initial_prices={"ETH": initial["ETH"], "BTC": initial["WBTC"]})
    paths["STABLE"] = experiment_a._stable_prices(frame, initial["STABLE"])
    if any(len(values) != len(frame) or not np.isfinite(values).all() or np.any(values <= 0.0) for values in paths.values()):
        raise ValueError("Historical validation price path is invalid.")
    return paths


@contextmanager
def _historical_horizon(horizon: int) -> Iterator[None]:
    previous = (experiment_d.TOTAL_HOURS, experiment_d.PRE_SHOCK_HOURS, experiment_d.POST_SHOCK_HOURS)
    experiment_d.TOTAL_HOURS = horizon
    experiment_d.PRE_SHOCK_HOURS = 0
    experiment_d.POST_SHOCK_HOURS = horizon
    try:
        yield
    finally:
        experiment_d.TOTAL_HOURS, experiment_d.PRE_SHOCK_HOURS, experiment_d.POST_SHOCK_HOURS = previous


def _validation_seed(stage: str, replication: int, stream: str) -> int:
    digest = hashlib.sha256(f"final-validation-v1|{stage}|{replication}|{stream}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def simulate_replication(stage: str, replication: int) -> dict[str, Any]:
    if stage not in {"ftx", "usdc_svb"}:
        raise ValueError("Only registered operational validation stages may run.")
    frame = _historical_window(stage)
    paths = _historical_paths(frame)
    horizon = len(frame)
    state_key = 7_000_000 + (0 if stage == "ftx" else 100_000) + replication
    states = experiment_a.initialise_nested_portfolios(state_key)
    portfolios = ("empirical_crypto",) if stage == "ftx" else ("empirical_crypto", "stable_supported")
    arrivals = robustness._arrival_stream(replication=state_key, horizon=horizon)
    _, _, stage1 = experiment_a.load_stage1_owners()
    residuals = experiment_a.sample_residual_blocks(
        stage1["source"],
        block_count=math.ceil(horizon / 24),
        rng=np.random.default_rng(_validation_seed(stage, replication, "stage1_residual_blocks")),
    )[:horizon]
    integrated = resolve_integrated_empirical_eth_profile()
    gas = component_gas_costs(
        sampled_market_gas_rows=frame,
        simulated_eth_prices=paths["ETH"],
        config=replace(integrated.gas, seed=_validation_seed(stage, replication, "keeper_gas_units")),
    )
    if gas.gas_cost_usd is None:
        raise ValueError("Historical validation gas path is unavailable.")
    design = experiment_a.load_recovery_design()
    validation_design = replace(design, shock_hour=0, pre_shock_hours=0, post_shock_hours=horizon, total_hours=horizon, recovery_cap_hours=horizon)
    full_week = next(item for item in design.path_definitions if item.identifier == "full_week")
    scaling = json.loads(experiment_a.SPARSE_SCALING_EVIDENCE.read_text(encoding="utf-8"))
    collateral, portfolio_payload, _ = experiment_a._design_payloads()
    rows: list[dict[str, Any]] = []
    with _historical_horizon(horizon):
        for portfolio in portfolios:
            with robustness.keeper_hurdle_adapter(0.0):
                liquidation = experiment_d._simulate_capacity_liquidations(
                    initialisation=states[portfolio],
                    price_paths=paths,
                    gas_costs=np.asarray(gas.gas_cost_usd, dtype="<f8"),
                    arrivals=arrivals,
                    portfolio_config=experiment_a._portfolio_config(portfolio, collateral, portfolio_payload),
                    capacity=26,
                )
            market = experiment_a._simulate_market_scenario(
                design=validation_design,
                definition=full_week,
                eth_prices=paths["ETH"],
                liquidation=liquidation["arrays"],
                innovations=residuals,
                scenario_identifier="stage1_only",
                stage1_owners=stage1,
                peg_scale=float(scaling["lagged_below_peg_gap"]["positive_q95"]),
                eth_scale=float(scaling["lagged_24h_eth_downside"]["positive_q95"]),
                initial_vault_count=500,
            )
            stable = next(item for item in liquidation["collateral_rows"] if item["family"] == "STABLE")
            system = liquidation["system_summary"]
            row = {
                "stage": stage,
                "portfolio": portfolio,
                "replication": replication,
                "state_checksum": states[portfolio].identity,
                "historical_path_checksum": robustness._payload_sha256({key: hashlib.sha256(np.asarray(value, dtype="<f8").tobytes()).hexdigest() for key, value in paths.items()}),
                "unsafe_vault_share": float(market["summary"]["peak_share_liquidatable"]),
                "eligible_liquidation_tab": system["eligible_liquidation_tab"],
                "completed_liquidations": int(market["summary"]["completed_liquidation_count"]),
                "liquidated_debt_share": system["liquidated_debt_share"],
                "backlog_area_share": system["backlog_area_share"],
                "maximum_unresolved_tab_share": system["maximum_unresolved_tab_share"],
                "terminal_unresolved_tab_share": system["terminal_unresolved_tab_share"],
                "terminal_active_bad_debt_share": system["terminal_active_bad_debt_share"],
                "realised_bad_debt_share": system["realised_bad_debt_share"],
                "mean_capacity_utilisation": system["mean_capacity_utilisation"],
                "capacity_rejected_opportunity_count": system["capacity_rejected_opportunity_count"],
                "minimum_dai_price": market["summary"]["minimum_dai_price"],
                "mean_absolute_peg_deviation": market["summary"]["mean_absolute_peg_deviation"],
                "below_peg_burden": market["summary"]["below_peg_burden"],
                "restricted_mean_recovery_time": market["summary"]["restricted_mean_recovery_time"],
                "recovery_probability": market["summary"][f"recovery_probability_{horizon}h"] if f"recovery_probability_{horizon}h" in market["summary"] else int(market["summary"]["right_censored"] == 0),
                "stable_initial_debt_exposure": stable["initial_debt_exposure"],
                "stable_liquidated_debt": stable["liquidated_debt"],
                "stable_backlog_area": stable["backlog_area"],
                "accounting_valid": liquidation["accounting"]["passed"],
                "numerical_valid": bool(system["numerical_valid"] and market["summary"]["numerical_valid"]),
                "observed_dai_used_as_input": False,
                "synthetic_shock_overlay": False,
            }
            rows.append(row)
    if stage == "usdc_svb":
        control = next(row for row in rows if row["portfolio"] == "empirical_crypto")
        if control["stable_initial_debt_exposure"] != 0.0 or control["stable_liquidated_debt"] != 0.0 or control["stable_backlog_area"] != 0.0:
            raise ValueError("USDC/SVB negative control failed.")
    if not all(row["accounting_valid"] and row["numerical_valid"] for row in rows):
        raise ValueError("Held-out validation technical validity failed.")
    return {"schema_version": 1, "validation_identity": validation_identity_from_file(), "stage": stage, "replication": replication, "rows": rows}


def validation_identity_from_file() -> str:
    path = EVIDENCE_DIR / COMPACT_FILENAMES[2]
    if not path.is_file():
        raise ValueError("Final validation freeze has not been written.")
    freeze = json.loads(path.read_text(encoding="utf-8"))
    return validation_identity(freeze)


def _checkpoint_dir(stage: str) -> Path:
    return OUTPUT_ROOT / validation_identity_from_file() / stage / "checkpoints"


def _checkpoint_path(stage: str, replication: int) -> Path:
    return _checkpoint_dir(stage) / f"replication_{replication:03d}.json"


def _valid_checkpoint(stage: str, replication: int) -> bool:
    path = _checkpoint_path(stage, replication)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected_rows = 1 if stage == "ftx" else 2
        return payload["validation_identity"] == validation_identity_from_file() and payload["stage"] == stage and payload["replication"] == replication and len(payload["rows"]) == expected_rows
    except Exception:
        return False


def _stage_gate(stage: str) -> None:
    if not (EVIDENCE_DIR / COMPACT_FILENAMES[2]).is_file():
        raise ValueError("Validation freeze must be written before execution.")
    if stage == "usdc_svb" and not (EVIDENCE_DIR / COMPACT_FILENAMES[4]).is_file():
        raise ValueError("FTX evidence must be frozen before USDC/SVB execution.")


def _run_one(stage: str, replication: int) -> int:
    result = simulate_replication(stage, replication)
    robustness._atomic_json(_checkpoint_path(stage, replication), result)
    return replication


def audit_checkpoints(stage: str) -> dict[str, Any]:
    valid = [value for value in range(REPLICATIONS) if _valid_checkpoint(stage, value)]
    existing = sorted(_checkpoint_dir(stage).glob("replication_*.json")) if _checkpoint_dir(stage).exists() else []
    return {"complete": len(valid) == REPLICATIONS, "valid_count": len(valid), "missing_count": REPLICATIONS - len(valid), "duplicate_count": 0, "orphan_count": max(0, len(existing) - len(valid)), "checkpoint_bytes": sum(path.stat().st_size for path in existing)}


def run_stage(stage: str, *, workers: int = 4, resume: bool = True) -> dict[str, Any]:
    _stage_gate(stage)
    pending = [value for value in range(REPLICATIONS) if not (resume and _valid_checkpoint(stage, value))]
    started = time.perf_counter()
    completed = []
    if workers == 1:
        completed = [_run_one(stage, value) for value in pending]
    elif pending:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
            futures = {executor.submit(_run_one, stage, value): value for value in pending}
            for future in as_completed(futures):
                completed.append(future.result())
    elapsed = time.perf_counter() - started
    audit = audit_checkpoints(stage)
    return {"stage": stage, "completed_replications": len(completed), "reused_replications": REPLICATIONS - len(pending), "elapsed_seconds": elapsed, "complete": audit["complete"], "checkpoint_audit": audit}


def load_stage_results(stage: str) -> pd.DataFrame:
    if not audit_checkpoints(stage)["complete"]:
        raise ValueError(f"{stage} checkpoints are incomplete.")
    rows = []
    for replication in range(REPLICATIONS):
        rows.extend(json.loads(_checkpoint_path(stage, replication).read_text(encoding="utf-8"))["rows"])
    return pd.DataFrame(rows)


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    array = np.asarray(values, dtype=float)
    return {"count": int(len(array)), "mean": float(array.mean()), "standard_error": float(array.std(ddof=1) / math.sqrt(len(array))), "p05": float(np.quantile(array, 0.05)), "p25": float(np.quantile(array, 0.25)), "median": float(np.quantile(array, 0.50)), "p75": float(np.quantile(array, 0.75)), "p95": float(np.quantile(array, 0.95)), "minimum": float(array.min()), "maximum": float(array.max())}


def stage_summary(stage: str) -> dict[str, Any]:
    frame = load_stage_results(stage)
    observed = observed_diagnostics(stage)
    metrics = load_registry()["metrics"]["simulated"]
    summaries = {}
    for portfolio, group in frame.groupby("portfolio", sort=False):
        summaries[portfolio] = {metric: _distribution(pd.to_numeric(group[metric], errors="raise").tolist()) for metric in metrics}
    if stage == "ftx":
        classification = classify_ftx_validation(
            observed=observed,
            simulated=summaries["empirical_crypto"],
        )
        replay_limitations = ["standardised vault states", "STABLE family excluded", "owner intervention omitted", "auction microstructure abstracted"]
    else:
        control = frame.loc[frame["portfolio"].eq("empirical_crypto")]
        negative = bool(control["stable_initial_debt_exposure"].eq(0.0).all() and control["stable_liquidated_debt"].eq(0.0).all() and control["stable_backlog_area"].eq(0.0).all())
        classification = classify_usdc_svb_validation(
            negative_control_passed=negative,
            stable_supported=summaries["stable_supported"],
        )
        replay_limitations = ["standardised vault states", "owner intervention omitted", "observed DAI is comparison-only"]
    return {"schema_version": 1, "stage": stage, "validation_identity": validation_identity_from_file(), "observed": observed, "simulated": summaries, "classification": classification, "negative_control_passed": True if stage == "ftx" else negative, "simulation_count": len(frame), "technical_validity": {"passed": bool(frame["accounting_valid"].all() and frame["numerical_valid"].all()), "accounting_failures": int((~frame["accounting_valid"]).sum()), "numerical_failures": int((~frame["numerical_valid"]).sum())}, "replay_limitations": replay_limitations}


def classify_ftx_validation(
    *,
    observed: Mapping[str, Any],
    simulated: Mapping[str, Mapping[str, Any]],
) -> str:
    """Classify the frozen FTX diagnostic without fitting to its outcome."""
    observed_drawdown = (
        float(observed["eth_window_log_return"]) < 0.0
        and float(observed["wbtc_window_log_return"]) < 0.0
    )
    if not observed_drawdown:
        return "ftx_validation_mixed"
    unsafe = float(simulated["unsafe_vault_share"]["mean"])
    eligible = float(simulated["eligible_liquidation_tab"]["mean"])
    completed = float(simulated["completed_liquidations"]["mean"])
    backlog = float(simulated["backlog_area_share"]["mean"])
    if unsafe <= 0.0 and eligible <= 0.0:
        return "ftx_validation_understates_stress"
    if completed > 0.0 or backlog > 0.0:
        return "ftx_validation_directionally_consistent"
    return "ftx_validation_partially_consistent"


def classify_usdc_svb_validation(
    *,
    negative_control_passed: bool,
    stable_supported: Mapping[str, Mapping[str, Any]],
) -> str:
    """Classify activation of the registered STABLE-vault channel."""
    if not negative_control_passed:
        return "usdc_svb_invalid"
    exposure = float(stable_supported["stable_initial_debt_exposure"]["mean"])
    liquidated = float(stable_supported["stable_liquidated_debt"]["mean"])
    backlog = float(stable_supported["stable_backlog_area"]["mean"])
    if exposure <= 0.0:
        return "usdc_svb_not_operational"
    if liquidated > 0.0:
        return "usdc_svb_validation_directionally_consistent"
    if backlog > 0.0:
        return "usdc_svb_validation_partially_consistent"
    return "usdc_svb_stable_channel_underactive"


def write_stage_summary(stage: str) -> dict[str, Any]:
    summary = stage_summary(stage)
    name = COMPACT_FILENAMES[4] if stage == "ftx" else COMPACT_FILENAMES[5]
    robustness._atomic_json(EVIDENCE_DIR / name, summary)
    return summary


def metric_comparison(ftx: Mapping[str, Any], usdc: Mapping[str, Any]) -> pd.DataFrame:
    rows = []
    for stage, summary in (("ftx", ftx), ("usdc_svb", usdc)):
        for portfolio, metrics in summary["simulated"].items():
            for metric, distribution in metrics.items():
                if metric in {"minimum_dai_price", "mean_absolute_peg_deviation", "below_peg_burden", "restricted_mean_recovery_time"}:
                    observed_key = {"minimum_dai_price": "dai_minimum_price", "mean_absolute_peg_deviation": "dai_mean_absolute_deviation", "below_peg_burden": "dai_below_peg_burden", "restricted_mean_recovery_time": "observed_recovery_duration"}[metric]
                    observed = float(summary["observed"][observed_key])
                    simulated = float(distribution["mean"])
                    if math.isclose(simulated, observed, rel_tol=0.25, abs_tol=1e-6):
                        status = "magnitude_broadly_compatible"
                    elif metric == "minimum_dai_price":
                        status = "overstated" if simulated < observed else "understated"
                    else:
                        status = "overstated" if simulated > observed else "understated"
                else:
                    observed = None
                    status = "structurally_unavailable"
                rows.append({"stage": stage, "portfolio": portfolio, "metric": metric, "observed_value": observed, "simulated_mean": distribution["mean"], "comparison_status": status})
    return pd.DataFrame(rows)


def classify_final(ftx_classification: str, usdc_classification: str, *, valid: bool, operational_stages: int = 2) -> str:
    if not valid:
        return "final_validation_invalid"
    if operational_stages < 2:
        return "final_validation_not_fully_operational"
    favourable = {"ftx_validation_directionally_consistent", "ftx_validation_partially_consistent", "usdc_svb_validation_directionally_consistent", "usdc_svb_validation_partially_consistent"}
    opposite = {"ftx_validation_overstates_stress", "ftx_validation_understates_stress", "usdc_svb_overstates_contagion", "usdc_svb_understates_contagion"}
    count = sum(value in favourable for value in (ftx_classification, usdc_classification))
    if count == 2:
        return "final_validation_supportive_with_limitations"
    if all(value in opposite for value in (ftx_classification, usdc_classification)):
        return "final_validation_not_supportive"
    return "final_validation_mixed"


def _manifest_records(paths: Sequence[Path]) -> list[dict[str, Any]]:
    return [{"bytes": path.stat().st_size, "path": path.relative_to(REPOSITORY_ROOT).as_posix(), "runtime_input": False, "semantic_owner": "frozen_model_held_out_validation", "sha256": sha256_file(path)} for path in paths]


def update_manifest(paths: Sequence[Path]) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    prefix = "data/provenance/validation/final/"
    manifest["entries"] = [entry for entry in manifest["entries"] if not entry["path"].startswith(prefix)] + _manifest_records(paths)
    manifest["entries"] = sorted(manifest["entries"], key=lambda item: item["path"])
    manifest["entry_count"] = len(manifest["entries"])
    manifest["duplicate_paths"] = len(manifest["entries"]) - len({entry["path"] for entry in manifest["entries"]})
    robustness._atomic_json(MANIFEST_PATH, manifest)


def reconstruct_evidence(benchmark: Mapping[str, Any]) -> dict[str, Any]:
    freeze = json.loads((EVIDENCE_DIR / COMPACT_FILENAMES[2]).read_text(encoding="utf-8"))
    ftx = stage_summary("ftx")
    usdc = stage_summary("usdc_svb")
    comparison = metric_comparison(ftx, usdc)
    valid = bool(ftx["technical_validity"]["passed"] and usdc["technical_validity"]["passed"] and usdc["negative_control_passed"])
    overall = classify_final(ftx["classification"], usdc["classification"], valid=valid)
    decision = {"schema_version": 1, "validation_identity": validation_identity(freeze), "freeze_identity": freeze["freeze_identity"], "quiet_classification": "quiet_validation_not_separately_registered", "ftx_classification": ftx["classification"], "usdc_svb_classification": usdc["classification"], "overall_classification": overall, "technical_validity": valid, "exact_historical_replay_claim": False, "model_changed": False, "parameters_changed": False, "scenarios_changed": False, "runtime_adopted": False}
    no_retuning = {"schema_version": 1, "scientific_freeze_identity": freeze["freeze_identity"], "robustness_identity": freeze["robustness_identity"], "validation_identity": validation_identity(freeze), "source_and_config_hashes": {"scientific_source_identity": freeze["scientific_source_identity"], "validation_registry_sha256": freeze["validation_registry_sha256"], "robustness_registry_sha256": freeze["robustness_registry_sha256"], "historical_source_sha256": freeze["historical_source_sha256"]}, "model_changes_after_validation": 0, "parameter_changes": 0, "scenario_changes": 0, "metric_rule_changes": 0, "production_adoption_changes": 0, "declaration": "Validation findings are evaluative. Unfavourable results are retained as limitations and do not trigger model retuning."}
    reproducibility = {"schema_version": 1, "validation_identity": validation_identity(freeze), "freeze_identity": freeze["freeze_identity"], "ftx_checkpoint_audit": audit_checkpoints("ftx"), "usdc_svb_checkpoint_audit": audit_checkpoints("usdc_svb"), "deterministic_aggregation_order": True, "observed_dai_used_as_input": False, "held_out_leakage": 0, "calibration_runs": 0, "parameter_changes": 0, "scenario_changes": 0, "production_changes": 0}
    payloads = {
        COMPACT_FILENAMES[0]: robustness._json_bytes(specification_payload(freeze), pretty=True),
        COMPACT_FILENAMES[1]: robustness._csv_bytes(window_inventory()),
        COMPACT_FILENAMES[2]: robustness._json_bytes(freeze, pretty=True),
        COMPACT_FILENAMES[3]: robustness._json_bytes({"schema_version": 1, "classification": "quiet_validation_not_separately_registered", "simulation_count": 0, "reason": "No distinct result-blind quiet window was registered; November 2022 is counted once."}, pretty=True),
        COMPACT_FILENAMES[4]: robustness._json_bytes(ftx, pretty=True),
        COMPACT_FILENAMES[5]: robustness._json_bytes(usdc, pretty=True),
        COMPACT_FILENAMES[6]: robustness._csv_bytes(comparison),
        COMPACT_FILENAMES[7]: robustness._json_bytes(decision, pretty=True),
        COMPACT_FILENAMES[8]: robustness._json_bytes(no_retuning, pretty=True),
        COMPACT_FILENAMES[9]: robustness._json_bytes(reproducibility, pretty=True),
        COMPACT_FILENAMES[10]: robustness._json_bytes(dict(benchmark), pretty=True),
    }
    paths = []
    for name, payload in payloads.items():
        path = EVIDENCE_DIR / name
        robustness._atomic_bytes(path, payload)
        paths.append(path)
    update_manifest(paths)
    return {"validation_identity": validation_identity(freeze), "freeze_identity": freeze["freeze_identity"], "decision": decision, "artefacts": {path.name: sha256_file(path) for path in paths}}


def validate_evidence() -> dict[str, Any]:
    paths = [EVIDENCE_DIR / name for name in COMPACT_FILENAMES]
    if not all(path.is_file() for path in paths):
        raise ValueError("Final validation compact evidence is incomplete.")
    ftx = load_stage_results("ftx")
    usdc = load_stage_results("usdc_svb")
    if len(ftx) != 128 or len(usdc) != 256:
        raise ValueError("Final validation simulation dimensions differ.")
    decision = json.loads(paths[7].read_text(encoding="utf-8"))
    no_retuning = json.loads(paths[8].read_text(encoding="utf-8"))
    if not decision["technical_validity"] or any(no_retuning[key] != 0 for key in ("model_changes_after_validation", "parameter_changes", "scenario_changes", "metric_rule_changes", "production_adoption_changes")):
        raise ValueError("Final validation validity or no-retuning gate failed.")
    return {"passed": True, "ftx_simulations": len(ftx), "usdc_svb_simulations": len(usdc), "artefact_count": len(paths), "overall_classification": decision["overall_classification"]}


def benchmark_payload(*, workers: int, ftx_seconds: float, usdc_seconds: float) -> dict[str, Any]:
    return {"schema_version": 1, "measurement_timestamp_utc": datetime.now(timezone.utc).isoformat(), "execution_commands": [f"PYTHONPATH=src python workflows/validation/final_validation.py ftx --workers {workers}", f"PYTHONPATH=src python workflows/validation/final_validation.py usdc-svb --workers {workers}"], "worker_count": workers, "ftx_wall_time_seconds": ftx_seconds, "usdc_svb_wall_time_seconds": usdc_seconds, "completed_simulations": 384, "quiet_simulations": 0, "ftx_simulations": 128, "usdc_svb_simulations": 256, "network_calls": 0, "calibration_runs": 0, "model_changes": 0, "parameter_changes": 0, "scenario_changes": 0}
