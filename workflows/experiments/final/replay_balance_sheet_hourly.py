"""Replay two frozen Experiment A cells for passive animation reporting."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
from pathlib import Path
import runpy
import subprocess
import time
from typing import Any

import numpy as np
import pandas as pd

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)

from dai_sim.experiments.final import (  # noqa: E402
    idiosyncratic_diversification as experiment,
)
from dai_sim.experiments.mechanism import eth_recovery as market_owner  # noqa: E402
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file  # noqa: E402
from dai_sim.inputs.gas import component_gas_costs  # noqa: E402
from dai_sim.inputs.integrated_profile import (  # noqa: E402
    resolve_integrated_empirical_eth_profile,
)


AUTHORIZED_SHOCK = "eth_idiosyncratic_severe"
AUTHORIZED_PORTFOLIOS = ("eth_only", "stable_supported")
AUTHORIZED_CELLS = tuple(
    f"{AUTHORIZED_SHOCK}__{portfolio}" for portfolio in AUTHORIZED_PORTFOLIOS
)
SELECTION_METRIC = "backlog_area_share"
SELECTION_FORMULA = "eth_only.backlog_area_share - stable_supported.backlog_area_share"
EXPERIMENT_IDENTITY = experiment.REGISTERED_EXPERIMENT_IDENTITY
EXPERIMENT_OUTPUT = experiment.OUTPUT_ROOT / EXPERIMENT_IDENTITY
CHECKPOINT_DIR = EXPERIMENT_OUTPUT / "checkpoints"
OUTPUT_ROOT = (
    REPOSITORY_ROOT
    / "outputs/reporting/reproduction/balance_sheet_hourly_replay"
    / EXPERIMENT_IDENTITY
)
SPECIFICATION_PATH = (
    experiment.EVIDENCE_DIR / "idiosyncratic_diversification_specification.json"
)
CELL_SUMMARY_PATH = (
    experiment.EVIDENCE_DIR / "idiosyncratic_diversification_cell_summary.csv"
)
COLLATERAL_SUMMARY_PATH = (
    experiment.EVIDENCE_DIR / "idiosyncratic_diversification_collateral_summary.csv"
)
CONFIGURATION_PATHS = (
    REPOSITORY_ROOT / "config/sensitivities/final_experiment_programme.yaml",
    REPOSITORY_ROOT / "config/sensitivities/final_portfolio_registry.yaml",
    REPOSITORY_ROOT / "config/sensitivities/final_shock_registry.yaml",
    REPOSITORY_ROOT / "config/sensitivities/keeper_execution.yaml",
    REPOSITORY_ROOT / "config/sensitivities/confidence_scenarios.yaml",
    REPOSITORY_ROOT / "config/sensitivities/eth_recovery_matrix.yaml",
    REPOSITORY_ROOT / "config/protocol/final_collateral_registry.yaml",
    REPOSITORY_ROOT / "config/profiles/empirical_integrated_multicollateral.yaml",
)
SYSTEM_COLUMNS = (
    "replication",
    "hour",
    "shock",
    "treatment",
    "eth_price_index",
    "wbtc_price_index",
    "stable_price_index",
    "unresolved_debt_share",
    "cumulative_liquidated_debt_share",
    "dai_price",
)
VAULT_COLUMNS = (
    "hour",
    "replication",
    "treatment",
    "vault_id",
    "collateral_family",
    "vault_debt",
    "collateral_ratio",
    "liquidation_ratio",
    "liquidation_margin",
    "canonical_vault_state",
    "selected_for_attempt",
)


class ReplayReconciliationError(RuntimeError):
    """Raised immediately when derived reporting evidence stops reconciling."""


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _git(*arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_state() -> dict[str, Any]:
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "status_porcelain": _git("status", "--porcelain=v1").splitlines(),
        "staged_paths": _git("diff", "--cached", "--name-only").splitlines(),
    }


def _checkpoint_path(replication: int) -> Path:
    return CHECKPOINT_DIR / f"replication_{replication:03d}.json"


def _read_checkpoint(replication: int) -> dict[str, Any]:
    return json.loads(_checkpoint_path(replication).read_text(encoding="utf-8"))


def select_representative_replication() -> dict[str, Any]:
    """Select from frozen scalar checkpoints without consulting hourly paths."""
    contrasts: list[dict[str, Any]] = []
    for replication in range(experiment.REPLICATIONS):
        payload = _read_checkpoint(replication)
        rows = {row["cell_identifier"]: row for row in payload["cell_rows"]}
        if not set(AUTHORIZED_CELLS).issubset(rows):
            raise ReplayReconciliationError(
                f"Replication {replication} lacks an authorised frozen scalar row."
            )
        left = float(rows[AUTHORIZED_CELLS[0]][SELECTION_METRIC])
        right = float(rows[AUTHORIZED_CELLS[1]][SELECTION_METRIC])
        contrasts.append(
            {
                "replication": replication,
                "eth_only": left,
                "stable_supported": right,
                "contrast": left - right,
            }
        )
    median = float(np.median([row["contrast"] for row in contrasts]))
    selected = min(
        contrasts,
        key=lambda row: (abs(float(row["contrast"]) - median), row["replication"]),
    )
    return {
        "source": "frozen scalar checkpoints only",
        "metric": SELECTION_METRIC,
        "metric_definition": (
            "sum of post-shock hourly unresolved_tab_dai divided by initial system debt"
        ),
        "formula": SELECTION_FORMULA,
        "sample_median": median,
        "selected_replication": int(selected["replication"]),
        "selected_contrast": float(selected["contrast"]),
        "absolute_distance_from_median": abs(float(selected["contrast"]) - median),
        "selected_components": {
            "eth_only": float(selected["eth_only"]),
            "stable_supported": float(selected["stable_supported"]),
        },
        "tie_rule": "smallest replication identifier",
        "candidate_count": len(contrasts),
    }


@contextmanager
def _passive_dai_capture() -> Iterable[list[float]]:
    captured: list[float] = []
    original = market_owner.coefficient_normalised_market_response

    def observe(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        captured.append(float(result.clipped_next_price))
        return result

    market_owner.coefficient_normalised_market_response = observe
    try:
        yield captured
    finally:
        market_owner.coefficient_normalised_market_response = original


def _simulate_market_with_capture(**kwargs: Any) -> tuple[dict[str, Any], np.ndarray]:
    with _passive_dai_capture() as captured:
        result = experiment._simulate_market_scenario(**kwargs)
    path = np.asarray(captured, dtype="<f8")
    if path.shape != (experiment.TOTAL_HOURS,):
        raise ReplayReconciliationError(
            f"Passive DAI capture returned {len(path)} values, expected "
            f"{experiment.TOTAL_HOURS}."
        )
    returned = np.asarray(result["dai_price_path"], dtype="<f8")
    if not np.array_equal(path[experiment.PRE_SHOCK_HOURS :], returned):
        raise ReplayReconciliationError(
            "Passive full DAI path differs from the canonical returned post path."
        )
    return result, path


def _scalar_mismatches(
    replayed: Mapping[str, Any], frozen: Mapping[str, Any]
) -> list[dict[str, Any]]:
    mismatches = []
    for key in sorted(set(replayed) | set(frozen)):
        left = replayed.get(key, "<missing>")
        right = frozen.get(key, "<missing>")
        if left != right:
            row: dict[str, Any] = {"field": key, "replayed": left, "frozen": right}
            if (
                isinstance(left, (int, float))
                and not isinstance(left, bool)
                and isinstance(right, (int, float))
                and not isinstance(right, bool)
            ):
                row["absolute_difference"] = abs(float(left) - float(right))
            mismatches.append(row)
    return mismatches


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    experiment._atomic_bytes(path, frame.to_csv(index=False).encode("utf-8"))


def _observer_rows(
    *, replication: int, treatment: str, target: list[dict[str, Any]]
) -> Any:
    def observe(
        hour: int,
        _prices: tuple[tuple[str, float], ...],
        active_snapshot: tuple[tuple[Any, ...], ...],
    ) -> None:
        for (
            vault_id,
            family,
            debt,
            collateral_ratio,
            liquidation_ratio,
            liquidatable,
            selected,
        ) in active_snapshot:
            margin = collateral_ratio / liquidation_ratio - 1.0
            target.append(
                {
                    "hour": hour,
                    "replication": replication,
                    "treatment": treatment,
                    "vault_id": vault_id,
                    "collateral_family": family,
                    "vault_debt": debt,
                    "collateral_ratio": collateral_ratio,
                    "liquidation_ratio": liquidation_ratio,
                    "liquidation_margin": margin,
                    "canonical_vault_state": (
                        "liquidatable_unresolved" if liquidatable else "safe"
                    ),
                    "selected_for_attempt": selected,
                }
            )

    return observe


def _system_row(
    *,
    cell: Any,
    portfolio: str,
    replication: int,
    streams: Mapping[str, Any],
    nested_audit: Mapping[str, Any],
    state: Any,
    gas_checksum: str,
    path_audit: Mapping[str, Any],
    liquidation: Mapping[str, Any],
    market: Mapping[str, Any],
) -> dict[str, Any]:
    system = {
        **liquidation["system_summary"],
        **{
            key: market["summary"][key]
            for key in (
                "below_peg_burden",
                "mean_absolute_peg_deviation",
                "minimum_dai_price",
                "restricted_mean_recovery_time",
                "recovery_probability_720h",
                "right_censored",
            )
        },
        "cell_order": cell.order,
        "cell_identifier": cell.identifier,
        "shock": AUTHORIZED_SHOCK,
        "portfolio": portfolio,
        "replication": replication,
        "capacity": experiment.CAPACITY,
        "hurdle": "direct_cost_only",
        "confidence": "stage1_only",
        "oracle_delay": 0,
        "paired_stream_checksum": streams["paired_stream_checksum"],
        "state_checksum": state.identity,
        "gas_component_draw_checksum": gas_checksum,
        "price_path_checksum": experiment._payload_sha256(
            path_audit["full_price_checksums"]
        ),
        "price_isolation_valid": path_audit["price_isolation_valid"],
        "nested_initialisation_valid": nested_audit["passed"],
    }
    system["numerical_valid"] = bool(
        system["numerical_valid"] and market["summary"]["numerical_valid"]
    )
    return system


def _validate_vault_accounting(
    vault: pd.DataFrame, arrays: Mapping[str, np.ndarray]
) -> dict[str, Any]:
    grouped = vault.groupby("hour", sort=True)
    unresolved = grouped.apply(
        lambda frame: float(
            frame.loc[
                frame["canonical_vault_state"].eq("liquidatable_unresolved"),
                "vault_debt",
            ].sum()
        ),
        include_groups=False,
    ).reindex(range(experiment.TOTAL_HOURS), fill_value=0.0)
    target = np.asarray(arrays["unresolved_tab_dai"], dtype=float)
    difference = np.abs(unresolved.to_numpy(dtype=float) - target)
    maximum = float(difference.max())
    if maximum > 1e-8:
        raise ReplayReconciliationError(
            f"Representative vault unresolved debt differs by {maximum}."
        )
    active = grouped.size().reindex(range(experiment.TOTAL_HOURS), fill_value=0)
    closed = experiment.VAULT_COUNT - active.to_numpy(dtype=int)
    expected_closed = np.cumsum(np.asarray(arrays["successful_closures"], dtype=int))
    if not np.array_equal(closed, expected_closed):
        raise ReplayReconciliationError(
            "Representative active-vault counts do not reconcile with closures."
        )
    return {
        "passed": True,
        "unresolved_debt_absolute_tolerance": 1e-8,
        "maximum_unresolved_debt_absolute_difference": maximum,
        "active_count_comparison": "exact",
    }


def replay_replication(
    replication: int, output_root: Path, selected_replication: int
) -> dict[str, Any]:
    started = time.perf_counter()
    frozen = _read_checkpoint(replication)
    frozen_cells = {
        row["cell_identifier"]: row
        for row in frozen["cell_rows"]
        if row["cell_identifier"] in AUTHORIZED_CELLS
    }
    frozen_collateral = {
        (row["cell_identifier"], row["family"]): row
        for row in frozen["collateral_rows"]
        if row["cell_identifier"] in AUTHORIZED_CELLS
    }
    if set(frozen_cells) != set(AUTHORIZED_CELLS):
        raise ReplayReconciliationError(
            f"Replication {replication} frozen cell scope differs."
        )
    streams = experiment._prepare_replication_streams(replication)
    nested_audit = experiment.audit_nested_initialisations(streams["states"])
    collateral_payload, portfolio_payload, _ = experiment._design_payloads()
    recovery_design = experiment.load_recovery_design()
    full_week = next(
        item
        for item in recovery_design.path_definitions
        if item.identifier == "full_week"
    )
    scaling = json.loads(experiment.SPARSE_SCALING_EVIDENCE.read_text())
    cells = {
        cell.identifier: cell
        for cell in experiment.build_cell_registry()
        if cell.identifier in AUTHORIZED_CELLS
    }
    price_paths, path_audit = experiment.build_price_paths(
        streams["sampled_market"], AUTHORIZED_SHOCK
    )
    integrated = resolve_integrated_empirical_eth_profile()
    gas = component_gas_costs(
        sampled_market_gas_rows=streams["sampled_market"],
        simulated_eth_prices=price_paths["ETH"],
        config=replace(
            integrated.gas,
            seed=experiment.derive_seed(replication, "keeper_gas_units"),
        ),
    )
    if gas.gas_cost_usd is None or gas.sampled_rows is None:
        raise ReplayReconciliationError("Registered gas path is missing.")
    gas_checksum = experiment._payload_sha256(
        gas.sampled_rows[
            ["gas_pool_row_id", "gas_units", "network_gas_price_gwei"]
        ].to_dict(orient="records")
    )
    system_rows: list[dict[str, Any]] = []
    scalar_rows: list[dict[str, Any]] = []
    collateral_rows: list[dict[str, Any]] = []
    vault_rows: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    vault_reconciliation: list[dict[str, Any]] = []
    for portfolio, identifier in zip(
        AUTHORIZED_PORTFOLIOS, AUTHORIZED_CELLS, strict=True
    ):
        state = streams["states"][portfolio]
        local_vault_rows: list[dict[str, Any]] = []
        observer = (
            _observer_rows(
                replication=replication,
                treatment=portfolio,
                target=local_vault_rows,
            )
            if replication == selected_replication
            else None
        )
        liquidation = experiment._simulate_cell_liquidations(
            initialisation=state,
            price_paths=price_paths,
            gas_costs=np.asarray(gas.gas_cost_usd, dtype="<f8"),
            arrivals=streams["arrivals"],
            portfolio_config=experiment._portfolio_config(
                portfolio, collateral_payload, portfolio_payload
            ),
            reporting_observer=observer,
        )
        market, dai_path = _simulate_market_with_capture(
            design=recovery_design,
            definition=full_week,
            eth_prices=price_paths["ETH"],
            liquidation=liquidation["arrays"],
            innovations=streams["residuals"],
            scenario_identifier="stage1_only",
            stage1_owners=streams["stage1"],
            peg_scale=float(scaling["lagged_below_peg_gap"]["positive_q95"]),
            eth_scale=float(scaling["lagged_24h_eth_downside"]["positive_q95"]),
            initial_vault_count=experiment.VAULT_COUNT,
        )
        cell = cells[identifier]
        scalar = _system_row(
            cell=cell,
            portfolio=portfolio,
            replication=replication,
            streams=streams,
            nested_audit=nested_audit,
            state=state,
            gas_checksum=gas_checksum,
            path_audit=path_audit,
            liquidation=liquidation,
            market=market,
        )
        mismatches = _scalar_mismatches(scalar, frozen_cells[identifier])
        if mismatches:
            raise ReplayReconciliationError(
                f"Replication {replication}, {identifier} scalar mismatch: "
                f"{mismatches[:5]}"
            )
        scalar_rows.append(scalar)
        reconciliation.append(
            {
                "replication": replication,
                "cell_identifier": identifier,
                "exact_match": True,
                "field_count": len(scalar),
                "numerical_tolerance": 0.0,
            }
        )
        for family_row in liquidation["collateral_rows"]:
            row = {
                "cell_order": cell.order,
                "cell_identifier": identifier,
                "shock": AUTHORIZED_SHOCK,
                "portfolio": portfolio,
                "replication": replication,
                "numerical_valid": scalar["numerical_valid"],
                "accounting_valid": scalar["accounting_valid"],
                "price_isolation_valid": scalar["price_isolation_valid"],
                "nested_initialisation_valid": scalar["nested_initialisation_valid"],
                **family_row,
            }
            mismatch = _scalar_mismatches(
                row, frozen_collateral[(identifier, row["family"])]
            )
            if mismatch:
                raise ReplayReconciliationError(
                    f"Replication {replication}, {identifier}/{row['family']} "
                    f"collateral mismatch: {mismatch[:5]}"
                )
            collateral_rows.append(row)
        arrays = liquidation["arrays"]
        cumulative_liquidated = (
            np.cumsum(np.asarray(arrays["cleared_tab_dai"], dtype=float))
            / experiment.TOTAL_DEBT_DAI
        )
        initial_prices = {
            "ETH": float(price_paths["ETH"][0]),
            "WBTC": float(price_paths["BTC"][0]),
            "STABLE": float(price_paths["STABLE"][0]),
        }
        for hour in range(experiment.TOTAL_HOURS):
            system_rows.append(
                {
                    "replication": replication,
                    "hour": hour,
                    "shock": AUTHORIZED_SHOCK,
                    "treatment": portfolio,
                    "eth_price_index": 100.0
                    * float(price_paths["ETH"][hour])
                    / initial_prices["ETH"],
                    "wbtc_price_index": 100.0
                    * float(price_paths["BTC"][hour])
                    / initial_prices["WBTC"],
                    "stable_price_index": 100.0
                    * float(price_paths["STABLE"][hour])
                    / initial_prices["STABLE"],
                    "unresolved_debt_share": float(
                        arrays["unresolved_tab_dai"][hour] / experiment.TOTAL_DEBT_DAI
                    ),
                    "cumulative_liquidated_debt_share": float(
                        cumulative_liquidated[hour]
                    ),
                    "dai_price": float(dai_path[hour]),
                }
            )
        if local_vault_rows:
            local = pd.DataFrame(local_vault_rows, columns=VAULT_COLUMNS)
            accounting = _validate_vault_accounting(local, arrays)
            vault_reconciliation.append({"treatment": portfolio, **accounting})
            vault_rows.extend(local_vault_rows)
    replication_dir = output_root / "replications"
    system_path = replication_dir / f"replication_{replication:03d}_system.csv"
    scalar_path = replication_dir / f"replication_{replication:03d}_scalars.json"
    collateral_path = replication_dir / f"replication_{replication:03d}_collateral.json"
    _atomic_csv(system_path, pd.DataFrame(system_rows, columns=SYSTEM_COLUMNS))
    experiment._atomic_json(scalar_path, scalar_rows)
    experiment._atomic_json(collateral_path, collateral_rows)
    result = {
        "replication": replication,
        "system_path": _relative(system_path),
        "system_sha256": sha256_file(system_path),
        "system_rows": len(system_rows),
        "scalar_path": _relative(scalar_path),
        "scalar_sha256": sha256_file(scalar_path),
        "collateral_path": _relative(collateral_path),
        "collateral_sha256": sha256_file(collateral_path),
        "row_reconciliation": reconciliation,
        "elapsed_seconds": time.perf_counter() - started,
    }
    if replication == selected_replication:
        vault_path = replication_dir / f"replication_{replication:03d}_vaults.csv"
        _atomic_csv(vault_path, pd.DataFrame(vault_rows, columns=VAULT_COLUMNS))
        result.update(
            {
                "vault_path": _relative(vault_path),
                "vault_sha256": sha256_file(vault_path),
                "vault_rows": len(vault_rows),
                "vault_accounting": vault_reconciliation,
            }
        )
    return result


def _worker(
    replication: int, output_root: str, selected_replication: int
) -> dict[str, Any]:
    multiprocessing.current_process().authkey = b"dai-sim-balance-sheet-reporting"
    return replay_replication(replication, Path(output_root), selected_replication)


def _aggregate_reconciliation(
    scalar: pd.DataFrame, collateral: pd.DataFrame, programme_identity: str
) -> dict[str, Any]:
    original_cells, original_collateral = experiment.load_results(programme_identity)
    retained_cells = original_cells.loc[
        ~original_cells["cell_identifier"].isin(AUTHORIZED_CELLS)
    ]
    reconstructed_cells = pd.concat([scalar, retained_cells], ignore_index=True)
    reconstructed_cells = reconstructed_cells.sort_values(
        ["cell_order", "replication"], kind="mergesort"
    ).reset_index(drop=True)
    cell_summary = experiment.cell_summary(reconstructed_cells)
    cell_bytes = experiment._csv_bytes(cell_summary)
    if cell_bytes != CELL_SUMMARY_PATH.read_bytes():
        raise ReplayReconciliationError(
            "Aggregate Experiment A cell summary failed exact reconciliation."
        )
    retained_collateral = original_collateral.loc[
        ~original_collateral["cell_identifier"].isin(AUTHORIZED_CELLS)
    ]
    reconstructed_collateral = pd.concat(
        [collateral, retained_collateral], ignore_index=True
    )
    reconstructed_collateral = reconstructed_collateral.sort_values(
        ["cell_order", "replication", "family"], kind="mergesort"
    ).reset_index(drop=True)
    collateral_summary = experiment.collateral_summary(reconstructed_collateral)
    collateral_bytes = experiment._csv_bytes(collateral_summary)
    if collateral_bytes != COLLATERAL_SUMMARY_PATH.read_bytes():
        raise ReplayReconciliationError(
            "Aggregate Experiment A collateral summary failed exact reconciliation."
        )
    return {
        "passed": True,
        "comparison": "exact canonical CSV bytes",
        "numerical_tolerance": 0.0,
        "cell_summary": {
            "path": _relative(CELL_SUMMARY_PATH),
            "sha256": sha256_file(CELL_SUMMARY_PATH),
            "reconstructed_sha256": hashlib.sha256(cell_bytes).hexdigest(),
        },
        "collateral_summary": {
            "path": _relative(COLLATERAL_SUMMARY_PATH),
            "sha256": sha256_file(COLLATERAL_SUMMARY_PATH),
            "reconstructed_sha256": hashlib.sha256(collateral_bytes).hexdigest(),
        },
    }


def _checkpoint_inventory() -> list[dict[str, Any]]:
    return [
        {
            "replication": replication,
            "path": _relative(_checkpoint_path(replication)),
            "sha256": sha256_file(_checkpoint_path(replication)),
        }
        for replication in range(experiment.REPLICATIONS)
    ]


def run_replay(*, output_root: Path = OUTPUT_ROOT, workers: int = 4) -> Path:
    if output_root.exists():
        raise FileExistsError(f"Refusing to overwrite replay directory: {output_root}")
    registered = tuple(
        cell.identifier
        for cell in experiment.build_cell_registry()
        if cell.shock == AUTHORIZED_SHOCK and cell.portfolio in AUTHORIZED_PORTFOLIOS
    )
    if registered != AUTHORIZED_CELLS:
        raise ReplayReconciliationError("Authorised Experiment A scope drifted.")
    if workers < 1:
        raise ValueError("Worker count must be positive.")
    selection = select_representative_replication()
    selected_replication = int(selection["selected_replication"])
    checkpoint_inventory = _checkpoint_inventory()
    before = {row["replication"]: row["sha256"] for row in checkpoint_inventory}
    source_git = _git_state()
    output_root.mkdir(parents=True)
    started = time.perf_counter()
    completed: list[dict[str, Any]] = []
    failures: dict[int, str] = {}
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
        futures = {
            executor.submit(
                _worker, replication, str(output_root), selected_replication
            ): replication
            for replication in range(experiment.REPLICATIONS)
        }
        for future in as_completed(futures):
            replication = futures[future]
            try:
                completed.append(future.result())
            except Exception as exc:  # pragma: no cover - real replay stop path
                failures[replication] = f"{type(exc).__name__}: {exc}"
                for pending in futures:
                    pending.cancel()
                break
    if failures:
        raise ReplayReconciliationError(f"Reporting replay stopped: {failures}")
    completed.sort(key=lambda row: row["replication"])
    if [row["replication"] for row in completed] != list(
        range(experiment.REPLICATIONS)
    ):
        raise ReplayReconciliationError(
            "Reporting replay replication set is incomplete."
        )
    system = pd.concat(
        [pd.read_csv(REPOSITORY_ROOT / row["system_path"]) for row in completed],
        ignore_index=True,
    ).sort_values(["replication", "treatment", "hour"], kind="mergesort")
    system_path = output_root / "balance_sheet_system_hourly.csv"
    _atomic_csv(system_path, system.reset_index(drop=True))
    selected_result = next(
        row for row in completed if row["replication"] == selected_replication
    )
    vault = pd.read_csv(REPOSITORY_ROOT / selected_result["vault_path"])
    vault = vault.sort_values(
        ["treatment", "hour", "vault_id"], kind="mergesort"
    ).reset_index(drop=True)
    vault_path = output_root / "balance_sheet_vault_hourly.csv"
    _atomic_csv(vault_path, vault)
    scalar_rows = [
        row
        for completed_row in completed
        for row in json.loads(
            (REPOSITORY_ROOT / completed_row["scalar_path"]).read_text()
        )
    ]
    collateral_rows = [
        row
        for completed_row in completed
        for row in json.loads(
            (REPOSITORY_ROOT / completed_row["collateral_path"]).read_text()
        )
    ]
    scalar = pd.DataFrame(scalar_rows).sort_values(
        ["cell_order", "replication"], kind="mergesort"
    )
    collateral = pd.DataFrame(collateral_rows).sort_values(
        ["cell_order", "replication", "family"], kind="mergesort"
    )
    scalar_path = output_root / "balance_sheet_replayed_scalar_rows.json"
    collateral_path = output_root / "balance_sheet_replayed_collateral_rows.json"
    experiment._atomic_json(scalar_path, scalar_rows)
    experiment._atomic_json(collateral_path, collateral_rows)
    programme_identity = str(_read_checkpoint(0)["programme_identity"])
    aggregate = _aggregate_reconciliation(scalar, collateral, programme_identity)
    after = {
        replication: sha256_file(_checkpoint_path(replication))
        for replication in range(experiment.REPLICATIONS)
    }
    if after != before:
        raise ReplayReconciliationError("Original Experiment A checkpoints changed.")
    manifest = {
        "schema_version": 1,
        "producer": "workflows.experiments.final.replay_balance_sheet_hourly",
        "classification": "derived_reporting_replay_not_replacement_scientific_evidence",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_git": source_git,
        "working_tree_after_replay": _git_state(),
        "registered_identity": {
            "experiment_id": experiment.EXPERIMENT_ID,
            "experiment_identity": EXPERIMENT_IDENTITY,
            "programme_identity": programme_identity,
            "registered_execution_scientific_code_identity": (
                experiment.REGISTERED_EXECUTION_SCIENTIFIC_CODE_IDENTITY
            ),
            "profile_identity": experiment.PROFILE_IDENTITY,
            "seed_namespace": experiment.EXPERIMENT_NAMESPACE,
            "seed_registry_sha256": experiment.seed_registry_checksum(),
        },
        "authorised_scope": {
            "shock": AUTHORIZED_SHOCK,
            "portfolios": list(AUTHORIZED_PORTFOLIOS),
            "cells": list(AUTHORIZED_CELLS),
            "replications": experiment.REPLICATIONS,
            "simulation_count": experiment.REPLICATIONS * len(AUTHORIZED_CELLS),
            "unrelated_treatments_executed": 0,
        },
        "representative_replication_selection": selection,
        "registered_seeds": [
            experiment.seed_record(replication)
            for replication in range(experiment.REPLICATIONS)
        ],
        "registered_configuration": {
            "specification_path": _relative(SPECIFICATION_PATH),
            "specification_sha256": sha256_file(SPECIFICATION_PATH),
            "files": [
                {"path": _relative(path), "sha256": sha256_file(path)}
                for path in CONFIGURATION_PATHS
            ],
        },
        "original_checkpoints": checkpoint_inventory,
        "passive_retention": {
            "random_draws_added": 0,
            "observer_default": "disabled",
            "observer_timing": "after canonical per-hour accounting reconciliation",
            "observer_payload": "immutable scalar tuples for active vaults only",
            "dai_capture": (
                "temporary wrapper records clipped_next_price already returned by "
                "the deterministic market-response owner"
            ),
            "post_path_exactly_matches_canonical_return": True,
        },
        "row_level_reconciliation": {
            "passed": True,
            "comparison": "exact Python scalar equality after JSON round trip",
            "numerical_tolerance": 0.0,
            "row_count": sum(len(row["row_reconciliation"]) for row in completed),
            "results": [
                result for row in completed for result in row["row_reconciliation"]
            ],
        },
        "aggregate_reconciliation": aggregate,
        "vault_accounting": selected_result["vault_accounting"],
        "schemas": {
            "system_hourly": list(SYSTEM_COLUMNS),
            "representative_active_vault_hourly": list(VAULT_COLUMNS),
            "liquidation_margin": "collateral_ratio / liquidation_ratio - 1",
            "closed_vault_handling": (
                "closed vaults leave the active snapshot; active-count counters "
                "retain their cumulative effect"
            ),
        },
        "outputs": {
            "system_hourly": {
                "path": _relative(system_path),
                "sha256": sha256_file(system_path),
                "rows": len(system),
            },
            "representative_vault_hourly": {
                "path": _relative(vault_path),
                "sha256": sha256_file(vault_path),
                "rows": len(vault),
            },
            "replayed_scalar_rows": {
                "path": _relative(scalar_path),
                "sha256": sha256_file(scalar_path),
                "rows": len(scalar_rows),
            },
            "replayed_collateral_rows": {
                "path": _relative(collateral_path),
                "sha256": sha256_file(collateral_path),
                "rows": len(collateral_rows),
            },
            "replications": completed,
        },
        "execution": {
            "command": (
                "PYTHONPATH=src:. python workflows/experiments/final/"
                f"replay_balance_sheet_hourly.py run --workers {workers}"
            ),
            "workers": workers,
            "elapsed_seconds": time.perf_counter() - started,
            "network_calls": 0,
        },
        "original_checkpoints_unchanged": True,
        "final_conclusions_changed": False,
    }
    manifest_path = output_root / "balance_sheet_reporting_replay_manifest.json"
    experiment._atomic_json(manifest_path, manifest)
    return manifest_path


def run_smoke(*, replication: int, output_root: Path) -> dict[str, Any]:
    if not 0 <= replication < experiment.REPLICATIONS:
        raise ValueError("Smoke replication is outside the registered set.")
    if output_root.exists():
        raise FileExistsError(f"Refusing to overwrite smoke directory: {output_root}")
    selection = select_representative_replication()
    output_root.mkdir(parents=True)
    return replay_replication(
        replication,
        output_root,
        int(selection["selected_replication"]),
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("smoke", "run"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--replication", type=int, default=4)
    parser.add_argument("--output-root", type=Path)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.operation == "smoke":
            if args.output_root is None:
                raise ValueError("Smoke replay requires --output-root.")
            result: Any = run_smoke(
                replication=args.replication, output_root=args.output_root
            )
        else:
            result = run_replay(
                output_root=OUTPUT_ROOT
                if args.output_root is None
                else args.output_root,
                workers=args.workers,
            )
    except (FileExistsError, ReplayReconciliationError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
