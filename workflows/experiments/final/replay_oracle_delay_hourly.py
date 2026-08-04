"""Replay the frozen empirical-crypto Experiment E cells for hourly reporting.

The scientific implementation is not modified.  This workflow calls the exact
registered owners and passively observes the full DAI path by temporarily
wrapping the deterministic market-response function in each worker process.
The wrapper records the already-computed return value, adds no random draw and
is restored immediately after each cell.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
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

from dai_sim.experiments.final import oracle_delay as experiment  # noqa: E402
from dai_sim.experiments.mechanism import eth_recovery as market_owner  # noqa: E402
from dai_sim.inputs.configuration import REPOSITORY_ROOT, sha256_file  # noqa: E402
from dai_sim.inputs.gas import component_gas_costs  # noqa: E402
from dai_sim.inputs.integrated_profile import (  # noqa: E402
    resolve_integrated_empirical_eth_profile,
)


AUTHORIZED_PORTFOLIO = "empirical_crypto"
AUTHORIZED_SHOCK = "joint_crypto_high_correlation"
AUTHORIZED_ANCHOR = f"{AUTHORIZED_PORTFOLIO}__{AUTHORIZED_SHOCK}"
AUTHORIZED_CELLS = experiment.CELL_ORDER[:3]
OUTPUT_ROOT = (
    REPOSITORY_ROOT
    / "outputs"
    / "reporting"
    / "reproduction"
    / "oracle_delay_hourly_replay"
    / experiment.experiment_identity(experiment.MASTER_PROGRAMME_IDENTITY)
)
SPECIFICATION_PATH = experiment.EVIDENCE_DIR / "oracle_delay_specification.json"
CELL_SUMMARY_PATH = experiment.EVIDENCE_DIR / "oracle_delay_cell_summary.csv"
CONFIGURATION_PATHS = (
    REPOSITORY_ROOT / "config/sensitivities/final_experiment_programme.yaml",
    REPOSITORY_ROOT / "config/sensitivities/final_oracle_delay_registry.yaml",
    REPOSITORY_ROOT / "config/protocol/final_collateral_registry.yaml",
    REPOSITORY_ROOT / "config/sensitivities/final_portfolio_registry.yaml",
    REPOSITORY_ROOT / "config/sensitivities/final_shock_registry.yaml",
    REPOSITORY_ROOT / "config/sensitivities/keeper_execution.yaml",
    REPOSITORY_ROOT / "config/sensitivities/confidence_scenarios.yaml",
    REPOSITORY_ROOT / "config/sensitivities/eth_recovery_matrix.yaml",
    REPOSITORY_ROOT / "config/profiles/empirical_integrated_multicollateral.yaml",
)
HOURLY_COLUMNS = (
    "replication",
    "hour",
    "anchor",
    "portfolio",
    "shock",
    "delay_hours",
    "treatment",
    "market_unsafe_debt",
    "market_unsafe_debt_share",
    "oracle_unsafe_debt",
    "oracle_unsafe_debt_share",
    "false_safe_debt",
    "cumulative_absolute_mismatch",
    "dai_price",
)


class ReplayReconciliationError(RuntimeError):
    """Raised as soon as replayed evidence differs from a frozen checkpoint."""


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_state() -> dict[str, Any]:
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "status_porcelain": _git("status", "--porcelain=v1").splitlines(),
        "staged_paths": _git("diff", "--cached", "--name-only").splitlines(),
    }


def _checkpoint_path(replication: int) -> Path:
    return experiment._checkpoint_path(
        experiment._output_dir(experiment.MASTER_PROGRAMME_IDENTITY), replication
    )


def _read_checkpoint(replication: int) -> dict[str, Any]:
    return json.loads(_checkpoint_path(replication).read_text(encoding="utf-8"))


@contextmanager
def _passive_dai_capture() -> Iterable[list[float]]:
    """Observe deterministic return values without changing model arguments."""
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


def _simulate_market_with_passive_capture(
    **kwargs: Any,
) -> tuple[dict[str, Any], np.ndarray]:
    with _passive_dai_capture() as captured:
        result = experiment.experiment_a._simulate_market_scenario(**kwargs)
    path = np.asarray(captured, dtype="<f8")
    if path.size != experiment.TOTAL_HOURS:
        raise ReplayReconciliationError(
            f"Passive DAI capture retained {path.size} values; expected "
            f"{experiment.TOTAL_HOURS}."
        )
    registered_post = np.asarray(result["dai_price_path"], dtype="<f8")
    if not np.array_equal(path[experiment.PRE_SHOCK_HOURS :], registered_post):
        raise ReplayReconciliationError(
            "Passive full DAI capture differs from the function's returned post-shock path."
        )
    return result, path


def _scalar_mismatches(
    replayed: Mapping[str, Any], frozen: Mapping[str, Any]
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for key in sorted(set(replayed) | set(frozen)):
        left = replayed.get(key, "<missing>")
        right = frozen.get(key, "<missing>")
        if left != right:
            record: dict[str, Any] = {"field": key, "replayed": left, "frozen": right}
            if (
                isinstance(left, (int, float))
                and not isinstance(left, bool)
                and isinstance(right, (int, float))
                and not isinstance(right, bool)
            ):
                record["absolute_difference"] = abs(float(left) - float(right))
            mismatches.append(record)
    return mismatches


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    experiment._atomic_bytes(path, frame.to_csv(index=False).encode("utf-8"))


def _build_system_row(
    *,
    cells: Mapping[str, Any],
    identifier: str,
    portfolio: str,
    shock: str,
    treatment: str,
    delay: int,
    replication: int,
    streams: Mapping[str, Any],
    state: Any,
    market_checksum: str,
    gas_checksum: str,
    oracle_audit: Mapping[str, Any],
    path_audit: Mapping[str, Any],
    mismatch_system: Mapping[str, Any],
    liquidation: Mapping[str, Any],
    market: Mapping[str, Any],
) -> dict[str, Any]:
    system = {
        **mismatch_system,
        **liquidation["system_summary"],
        **{key: market["summary"][key] for key in experiment.PEG_METRICS},
        "cell_order": cells[identifier].order,
        "cell_identifier": identifier,
        "anchor": f"{portfolio}__{shock}",
        "portfolio": portfolio,
        "shock": shock,
        "oracle_treatment": treatment,
        "oracle_delay_steps": delay,
        "oracle_delay_hours": delay,
        "capacity": experiment.CAPACITY,
        "replication": replication,
        "hurdle": "direct_cost_only",
        "risk_cost_rate": 0.0,
        "confidence": "stage1_only",
        "paired_stream_checksum": streams["paired_stream_checksum"],
        "state_checksum": state.identity,
        "market_path_checksum": market_checksum,
        "gas_component_checksum": gas_checksum,
        "arrival_checksum": streams["arrivals"]["checksum"],
        "residual_checksum": streams["stream_components"]["residual_checksum"],
        "oracle_path_checksum": oracle_audit["combined_checksum"],
        "path_valid": bool(path_audit["path_valid"] and oracle_audit["passed"]),
        "nested_initialisation_valid": streams["nested_audit"]["passed"],
    }
    system["numerical_valid"] = bool(
        system["numerical_valid"]
        and market["summary"]["numerical_valid"]
        and system["path_valid"]
    )
    return system


def replay_replication(replication: int, output_root: Path) -> dict[str, Any]:
    """Replay exactly three authorised cells and persist only after reconciliation."""
    started = time.perf_counter()
    frozen_payload = _read_checkpoint(replication)
    frozen_rows = {
        row["cell_identifier"]: row
        for row in frozen_payload["cell_rows"]
        if row["cell_identifier"] in AUTHORIZED_CELLS
    }
    if tuple(frozen_rows) != AUTHORIZED_CELLS:
        raise ReplayReconciliationError(
            f"Replication {replication} frozen authorised-cell set differs."
        )
    streams = experiment._prepare_replication_streams(replication)
    collateral_payload, portfolio_payload, _ = (
        experiment.experiment_a._design_payloads()
    )
    recovery_design = experiment.experiment_a.load_recovery_design()
    full_week = next(
        item
        for item in recovery_design.path_definitions
        if item.identifier == "full_week"
    )
    scaling = json.loads(
        experiment.experiment_a.SPARSE_SCALING_EVIDENCE.read_text(encoding="utf-8")
    )
    cells = {
        cell.identifier: cell
        for cell in experiment.build_cell_registry()
        if cell.identifier in AUTHORIZED_CELLS
    }
    if tuple(cells) != AUTHORIZED_CELLS:
        raise ReplayReconciliationError("Replay attempted an unregistered cell set.")
    market_paths, gas_rows, path_audit = experiment.experiment_c.build_treatment_paths(
        streams["sampled_market"], AUTHORIZED_SHOCK
    )
    if not path_audit["path_valid"]:
        raise ReplayReconciliationError("Authorised replay market path is invalid.")
    gas = component_gas_costs(
        sampled_market_gas_rows=gas_rows,
        simulated_eth_prices=market_paths["ETH"],
        config=replace(
            resolve_integrated_empirical_eth_profile().gas,
            seed=experiment.derive_seed(replication, "keeper_gas_units"),
        ),
    )
    if gas.gas_cost_usd is None or gas.sampled_rows is None:
        raise ReplayReconciliationError("Authorised replay gas path is missing.")
    gas_checksum = experiment._payload_sha256(
        gas.sampled_rows[
            [
                "gas_pool_row_id",
                "gas_units",
                "network_gas_price_gwei",
                "runtime_eth_price_usd",
                "component_transaction_gas_cost_usd",
            ]
        ].to_dict(orient="records")
    )
    state = streams["states"][AUTHORIZED_PORTFOLIO]
    initial_debt = {
        family: float(
            sum(
                vault.debt_dai
                for vault in state.vaults
                if experiment._family(vault.collateral_type) == family
            )
        )
        for family in experiment.FAMILY_ORDER
    }
    market_checksum = experiment._payload_sha256(path_audit["full_price_checksums"])
    hourly_rows: list[dict[str, Any]] = []
    scalar_rows: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    for delay, treatment, identifier in zip(
        experiment.DELAY_ORDER,
        experiment.TREATMENT_ORDER,
        AUTHORIZED_CELLS,
        strict=True,
    ):
        oracle_paths, oracle_audit = experiment.build_oracle_paths(market_paths, delay)
        mismatch_system, _ = experiment.mismatch_diagnostics(
            market_paths, oracle_paths, initial_debt
        )
        liquidation = experiment._simulate_delay_liquidations(
            initialisation=state,
            market_paths=market_paths,
            oracle_paths=oracle_paths,
            gas_costs=np.asarray(gas.gas_cost_usd, dtype="<f8"),
            arrivals=streams["arrivals"],
            portfolio_config=experiment.experiment_a._portfolio_config(
                AUTHORIZED_PORTFOLIO, collateral_payload, portfolio_payload
            ),
        )
        market, dai_path = _simulate_market_with_passive_capture(
            design=recovery_design,
            definition=full_week,
            eth_prices=market_paths["ETH"],
            liquidation=liquidation["arrays"],
            innovations=streams["residuals"],
            scenario_identifier="stage1_only",
            stage1_owners=streams["stage1"],
            peg_scale=float(scaling["lagged_below_peg_gap"]["positive_q95"]),
            eth_scale=float(scaling["lagged_24h_eth_downside"]["positive_q95"]),
            initial_vault_count=experiment.VAULT_COUNT,
        )
        system = _build_system_row(
            cells=cells,
            identifier=identifier,
            portfolio=AUTHORIZED_PORTFOLIO,
            shock=AUTHORIZED_SHOCK,
            treatment=treatment,
            delay=delay,
            replication=replication,
            streams=streams,
            state=state,
            market_checksum=market_checksum,
            gas_checksum=gas_checksum,
            oracle_audit=oracle_audit,
            path_audit=path_audit,
            mismatch_system=mismatch_system,
            liquidation=liquidation,
            market=market,
        )
        mismatches = _scalar_mismatches(system, frozen_rows[identifier])
        if mismatches:
            raise ReplayReconciliationError(
                f"Replication {replication}, cell {identifier} failed exact scalar "
                f"reconciliation: {mismatches[:10]}"
            )
        scalar_rows.append(system)
        reconciliation.append(
            {
                "replication": replication,
                "cell_identifier": identifier,
                "exact_match": True,
                "field_count": len(system),
                "numerical_tolerance": 0.0,
            }
        )
        arrays = liquidation["arrays"]
        market_debt = np.asarray(arrays["market_unsafe_debt"], dtype="<f8")
        oracle_debt = np.asarray(arrays["oracle_unsafe_debt"], dtype="<f8")
        false_safe = np.asarray(arrays["false_safe_debt"], dtype="<f8")
        market_share = market_debt / experiment.TOTAL_DEBT_DAI
        oracle_share = oracle_debt / experiment.TOTAL_DEBT_DAI
        cumulative = np.cumsum(
            np.abs(market_share - oracle_share)
            * experiment.MATERIALITY_THRESHOLDS["simulation_step_hours"]
        )
        for hour in range(experiment.TOTAL_HOURS):
            hourly_rows.append(
                {
                    "replication": replication,
                    "hour": hour,
                    "anchor": AUTHORIZED_ANCHOR,
                    "portfolio": AUTHORIZED_PORTFOLIO,
                    "shock": AUTHORIZED_SHOCK,
                    "delay_hours": delay,
                    "treatment": treatment,
                    "market_unsafe_debt": market_debt[hour],
                    "market_unsafe_debt_share": market_share[hour],
                    "oracle_unsafe_debt": oracle_debt[hour],
                    "oracle_unsafe_debt_share": oracle_share[hour],
                    "false_safe_debt": false_safe[hour],
                    "cumulative_absolute_mismatch": cumulative[hour],
                    "dai_price": dai_path[hour],
                }
            )
    hourly = pd.DataFrame(hourly_rows, columns=HOURLY_COLUMNS)
    if len(hourly) != len(AUTHORIZED_CELLS) * experiment.TOTAL_HOURS:
        raise ReplayReconciliationError(
            f"Replication {replication} retained an unexpected hourly row count."
        )
    replication_dir = output_root / "replications"
    hourly_path = replication_dir / f"replication_{replication:03d}.csv"
    scalar_path = replication_dir / f"replication_{replication:03d}_scalars.json"
    _atomic_csv(hourly_path, hourly)
    experiment._atomic_json(scalar_path, scalar_rows)
    return {
        "replication": replication,
        "elapsed_seconds": time.perf_counter() - started,
        "hourly_path": _relative(hourly_path),
        "hourly_sha256": sha256_file(hourly_path),
        "hourly_rows": len(hourly),
        "scalar_path": _relative(scalar_path),
        "scalar_sha256": sha256_file(scalar_path),
        "reconciliation": reconciliation,
    }


def _worker(replication: int, output_root: str) -> dict[str, Any]:
    multiprocessing.current_process().authkey = b"dai-sim-oracle-reporting-replay"
    return replay_replication(replication, Path(output_root))


def _aggregate_reconciliation(scalar_rows: pd.DataFrame) -> dict[str, Any]:
    original, _ = experiment.load_results(experiment.MASTER_PROGRAMME_IDENTITY)
    retained = original.loc[~original["cell_identifier"].isin(AUTHORIZED_CELLS)]
    reconstructed_input = pd.concat([scalar_rows, retained], ignore_index=True)
    reconstructed_input = reconstructed_input.sort_values(
        ["cell_order", "replication"], kind="mergesort"
    ).reset_index(drop=True)
    reconstructed = experiment.cell_summary(reconstructed_input)
    reconstructed_bytes = experiment._csv_bytes(reconstructed)
    registered_bytes = CELL_SUMMARY_PATH.read_bytes()
    if reconstructed_bytes != registered_bytes:
        raise ReplayReconciliationError(
            "Aggregate Experiment E cell summary failed exact byte reconciliation."
        )
    return {
        "passed": True,
        "comparison": "exact canonical CSV bytes",
        "numerical_tolerance": 0.0,
        "registered_path": _relative(CELL_SUMMARY_PATH),
        "registered_sha256": sha256_file(CELL_SUMMARY_PATH),
        "reconstructed_sha256": experiment.hashlib.sha256(
            reconstructed_bytes
        ).hexdigest(),
    }


def _configuration_inventory() -> list[dict[str, Any]]:
    return [
        {"path": _relative(path), "sha256": sha256_file(path)}
        for path in CONFIGURATION_PATHS
    ]


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
    """Run all and only the 384 authorised reporting-replay simulations."""
    experiment._assert_preregistered_identities(experiment.MASTER_PROGRAMME_IDENTITY)
    registered_cells = tuple(
        cell.identifier
        for cell in experiment.build_cell_registry()
        if cell.portfolio == AUTHORIZED_PORTFOLIO and cell.shock == AUTHORIZED_SHOCK
    )
    if registered_cells != AUTHORIZED_CELLS:
        raise ReplayReconciliationError(
            "Authorised replay scope differs from registry."
        )
    if output_root.exists():
        raise FileExistsError(f"Refusing to overwrite replay directory: {output_root}")
    if workers < 1:
        raise ValueError("Replay worker count must be positive.")
    git_before = _git_state()
    checkpoint_inventory = _checkpoint_inventory()
    checkpoints_before = {
        row["replication"]: row["sha256"] for row in checkpoint_inventory
    }
    output_root.mkdir(parents=True)
    started = time.perf_counter()
    completed: list[dict[str, Any]] = []
    failures: dict[int, str] = {}
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
        futures = {
            executor.submit(_worker, replication, str(output_root)): replication
            for replication in range(experiment.REPLICATIONS)
        }
        for future in as_completed(futures):
            replication = futures[future]
            try:
                completed.append(future.result())
            except Exception as exc:  # pragma: no cover - real worker failure path
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
    hourly_frames = [
        pd.read_csv(REPOSITORY_ROOT / row["hourly_path"]) for row in completed
    ]
    combined_hourly = pd.concat(hourly_frames, ignore_index=True)
    combined_hourly = combined_hourly.sort_values(
        ["replication", "delay_hours", "hour"], kind="mergesort"
    ).reset_index(drop=True)
    combined_path = output_root / "oracle_delay_hourly_paths.csv"
    _atomic_csv(combined_path, combined_hourly)
    scalar_payloads = [
        json.loads((REPOSITORY_ROOT / row["scalar_path"]).read_text(encoding="utf-8"))
        for row in completed
    ]
    scalar_rows = [row for payload in scalar_payloads for row in payload]
    scalar_frame = pd.DataFrame(scalar_rows).sort_values(
        ["cell_order", "replication"], kind="mergesort"
    )
    scalar_path = output_root / "oracle_delay_replayed_scalar_rows.json"
    experiment._atomic_json(scalar_path, scalar_rows)
    aggregate = _aggregate_reconciliation(scalar_frame)
    checkpoints_after = {
        replication: sha256_file(_checkpoint_path(replication))
        for replication in range(experiment.REPLICATIONS)
    }
    if checkpoints_after != checkpoints_before:
        raise ReplayReconciliationError("Original Experiment E checkpoints changed.")
    specification = json.loads(SPECIFICATION_PATH.read_text(encoding="utf-8"))
    manifest_path = output_root / "oracle_delay_reporting_replay_manifest.json"
    manifest = {
        "schema_version": 1,
        "producer": "workflows.experiments.final.replay_oracle_delay_hourly",
        "classification": "derived_reporting_replay_not_replacement_scientific_evidence",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_git": git_before,
        "working_tree_after_replay": _git_state(),
        "registered_identity": {
            "experiment_id": experiment.EXPERIMENT_ID,
            "experiment_identity": experiment.experiment_identity(
                experiment.MASTER_PROGRAMME_IDENTITY
            ),
            "programme_identity": experiment.MASTER_PROGRAMME_IDENTITY,
            "scientific_code_identity": experiment.scientific_code_identity(),
            "simulation_core_identity": experiment.simulation_core_identity(),
            "profile_identity": experiment.PROFILE_IDENTITY,
            "seed_namespace": experiment.EXPERIMENT_NAMESPACE,
            "seed_registry_sha256": experiment.seed_registry_checksum(),
        },
        "authorised_scope": {
            "portfolio": AUTHORIZED_PORTFOLIO,
            "shock": AUTHORIZED_SHOCK,
            "cells": list(AUTHORIZED_CELLS),
            "delays_hours": list(experiment.DELAY_ORDER),
            "replications": experiment.REPLICATIONS,
            "simulation_count": len(AUTHORIZED_CELLS) * experiment.REPLICATIONS,
            "unrelated_treatments_executed": 0,
        },
        "registered_configuration": {
            "specification_path": _relative(SPECIFICATION_PATH),
            "specification_sha256": sha256_file(SPECIFICATION_PATH),
            "registry_checksums": specification["registry_checksums"],
            "configuration_files": _configuration_inventory(),
        },
        "registered_seeds": [
            experiment.seed_record(replication)
            for replication in range(experiment.REPLICATIONS)
        ],
        "registered_stream_components": [
            {
                "replication": replication,
                **_read_checkpoint(replication)["stream_components"],
            }
            for replication in range(experiment.REPLICATIONS)
        ],
        "original_checkpoints": checkpoint_inventory,
        "passive_retention": {
            "model_files_modified": False,
            "random_draws_added": 0,
            "execution_order_changed_within_cell": False,
            "dai_capture": (
                "temporary reporting-side wrapper records clipped_next_price returned "
                "by each original coefficient_normalised_market_response call"
            ),
            "post_path_exactly_matches_original_return": True,
        },
        "row_level_reconciliation": {
            "passed": True,
            "comparison": "exact Python scalar equality after JSON round trip",
            "numerical_tolerance": 0.0,
            "row_count": sum(len(row["reconciliation"]) for row in completed),
            "results": [
                result for row in completed for result in row["reconciliation"]
            ],
        },
        "aggregate_reconciliation": aggregate,
        "outputs": {
            "combined_hourly": {
                "path": _relative(combined_path),
                "sha256": sha256_file(combined_path),
                "rows": len(combined_hourly),
            },
            "replayed_scalar_rows": {
                "path": _relative(scalar_path),
                "sha256": sha256_file(scalar_path),
                "rows": len(scalar_rows),
            },
            "replications": completed,
        },
        "execution": {
            "command": (
                "PYTHONPATH=src:. python "
                "workflows/experiments/final/replay_oracle_delay_hourly.py run --workers "
                f"{workers}"
            ),
            "workers": workers,
            "elapsed_seconds": time.perf_counter() - started,
            "network_calls": 0,
        },
        "original_checkpoints_unchanged": True,
        "final_conclusions_changed": False,
    }
    experiment._atomic_json(manifest_path, manifest)
    return manifest_path


def run_smoke(*, replication: int, output_root: Path) -> dict[str, Any]:
    experiment._assert_preregistered_identities(experiment.MASTER_PROGRAMME_IDENTITY)
    if not 0 <= replication < experiment.REPLICATIONS:
        raise ValueError("Smoke replication is outside the registered set.")
    if output_root.exists():
        raise FileExistsError(f"Refusing to overwrite smoke directory: {output_root}")
    output_root.mkdir(parents=True)
    return replay_replication(replication, output_root)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("smoke", "run"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--replication", type=int, default=0)
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
