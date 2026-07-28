"""Repair and validate the Phase 1E-B quiet-mature effective-rate stream.

This local controller cannot create or execute a Dune query. It renders the
bounded Method B SQL, records externally returned identifiers, validates one
persisted result page, combines it with the exact local opening rates and then
invokes deterministic quiet-mature reconstruction.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import runpy

_WORKFLOW_BOOTSTRAP = next(
    parent / "_bootstrap.py"
    for parent in Path(__file__).resolve().parents
    if (parent / "_bootstrap.py").is_file()
)
REPOSITORY_ROOT = runpy.run_path(str(_WORKFLOW_BOOTSTRAP))["bootstrap_runtime"](__file__)
from typing import Any

from workflows.vaults import acquire_representative as representative


ROOT = REPOSITORY_ROOT
WINDOW = representative.WINDOWS["quiet_mature"]
WINDOW_SLUG = representative.window_slug(WINDOW)
RAW_DIR = (
    ROOT / "data" / "vaults" / "raw" / "chunks" / WINDOW_SLUG
    / "effective_rates"
)
PROCESSED_DIR = (
    ROOT / "data" / "vaults" / "processed" / "representative_regimes"
    / WINDOW_SLUG
)
PROVENANCE_DIR = (
    ROOT / "data" / "vaults" / "provenance" / "representative_regimes"
    / WINDOW_SLUG / "effective_rates"
)
SQL_PATH = (
    ROOT / "sql" / "vaults" / "generated" / "representative_regimes"
    / WINDOW_SLUG / "effective_rates_sparse_repair.sql"
)
PAGE_PATH = RAW_DIR / "page_offset_00000000.json"
RAW_PATH = RAW_DIR / "effective_rates_in_window.csv"
SPARSE_PATH = PROCESSED_DIR / "effective_rates.csv"
STATE_PATH = PROVENANCE_DIR / "state.json"
METADATA_PATH = PROVENANCE_DIR / "metadata.json"
VALIDATION_PATH = PROVENANCE_DIR / "validation.json"
SOURCE_AUDIT_PATH = PROVENANCE_DIR / "source_audit.json"

BOUNDARY_PATH = (
    ROOT / "data" / "vaults" / "raw" / "chunks" / WINDOW_SLUG
    / "boundary_states" / "boundary_states.csv"
)
PHASE1D_JUG = ROOT / "data" / "protocol" / "raw" / "phase1d_jug_parameters.csv"
PHASE1D_VAT = ROOT / "data" / "protocol" / "raw" / "phase1d_vat_parameters.csv"
PHASE1D_LEDGER = (
    ROOT / "data" / "protocol" / "processed"
    / "phase1d_protocol_parameter_changes.csv"
)
PHASE1D_INTERVALS = (
    ROOT / "data" / "protocol" / "processed"
    / "phase1d_protocol_parameter_intervals.csv"
)
PHASE1D_HOURLY = (
    ROOT / "data" / "protocol" / "processed"
    / "phase1d_protocol_parameters_hourly.csv"
)


def source_audit() -> dict[str, Any]:
    candidates = [
        {
            "path": representative.relative(PHASE1D_JUG),
            "quantity": "Jug duty and global base governance settings",
            "coverage": "2019-11-13 to 2024-05-18",
            "target_ilks": list(representative.TARGET_ILKS),
            "relevant_columns": [
                "effective_time_utc", "ilk", "parameter", "raw_value",
                "transaction_hash", "source_position",
            ],
            "timestamp_precision": "decoded call timestamp",
            "source_lineage": "maker_ethereum.jug_call_file",
            "opening_suitability": False,
            "exact_replay_suitability": False,
            "reason": (
                "Duty and base are fee parameters, not accumulated Vat rate."
            ),
        },
        {
            "path": representative.relative(PHASE1D_VAT),
            "quantity": "Vat line, Line and dust governance settings",
            "coverage": "2021-03-24 to 2024-06-30",
            "target_ilks": list(representative.TARGET_ILKS),
            "relevant_columns": [
                "effective_time_utc", "ilk", "parameter", "raw_value",
            ],
            "timestamp_precision": "decoded call timestamp",
            "source_lineage": "maker_ethereum.vat_call_file",
            "opening_suitability": False,
            "exact_replay_suitability": False,
            "reason": "No Vat.fold or accumulated-rate state is present.",
        },
        {
            "path": representative.relative(PHASE1D_LEDGER),
            "quantity": "Sparse effective-dated protocol parameter calls",
            "coverage": "2019-11-13 to 2024-06-30",
            "target_ilks": list(representative.TARGET_ILKS),
            "relevant_columns": [
                "effective_time_utc", "ilk", "parameter", "raw_value",
            ],
            "timestamp_precision": "decoded call timestamp",
            "source_lineage": "validated Phase 1D module raw files",
            "opening_suitability": False,
            "exact_replay_suitability": False,
            "reason": "Contains duty/base, not Jug.drip.output_rate.",
        },
        {
            "path": representative.relative(PHASE1D_INTERVALS),
            "quantity": "Effective intervals for protocol settings",
            "coverage": "2021-06-01 to 2024-07-01",
            "target_ilks": list(representative.TARGET_ILKS),
            "relevant_columns": [
                "effective_start_utc", "effective_end_exclusive_utc",
                "ilk", "parameter", "raw_value",
            ],
            "timestamp_precision": "exact setting boundaries",
            "source_lineage": "locally intervalised Phase 1D ledger",
            "opening_suitability": False,
            "exact_replay_suitability": False,
            "reason": "Intervals describe fee settings, not accrued Vat rate.",
        },
        {
            "path": representative.relative(PHASE1D_HOURLY),
            "quantity": "Hourly protocol settings and annualised fee",
            "coverage": "2021-06-01 to 2024-07-01",
            "target_ilks": list(representative.TARGET_ILKS),
            "relevant_columns": [
                "timestamp_utc", "ilk", "stability_fee_duty_factor",
                "stability_fee_base_factor", "annualised_stability_fee",
            ],
            "timestamp_precision": "hourly",
            "source_lineage": "forward-filled Phase 1D setting intervals",
            "opening_suitability": False,
            "exact_replay_suitability": False,
            "reason": (
                "Hourly annualised fees cannot establish exact same-block "
                "accumulated-rate ordering."
            ),
        },
        {
            "path": representative.relative(BOUNDARY_PATH),
            "quantity": "Exact latest pre-window and end-window Jug rates",
            "coverage": "boundaries for 2024-02-01 to 2024-03-01",
            "target_ilks": list(representative.TARGET_ILKS),
            "relevant_columns": [
                "ilk", "opening_rate_raw_ray",
                "opening_rate_effective_time_utc", "end_rate_raw_ray",
                "end_rate_effective_time_utc",
            ],
            "timestamp_precision": "decoded Jug.drip timestamp",
            "source_lineage": "maker_ethereum.jug_call_drip via query 8113626",
            "opening_suitability": True,
            "exact_replay_suitability": False,
            "reason": (
                "Exact opening and ending states are available, but ordered "
                "in-window accumulated-rate changes are absent."
            ),
        },
    ]
    return {
        "selected_method": "B_hybrid_local_opening_plus_sparse_dune_window",
        "local_method_a_exact": False,
        "method_a_blocker": (
            "No local source contains ordered in-window Jug.drip.output_rate "
            "or Vat.fold calls."
        ),
        "candidate_sources": candidates,
        "fixed_point_units": {
            "WAD": "1e18",
            "RAY": "1e27",
            "debt_dai": "art_raw * rate_raw_ray / 1e45",
        },
    }


def prepare(current_usage: Decimal, quota: Decimal) -> dict[str, Any]:
    gate = representative.enforce_rate_repair_credit_gate(
        current_usage=current_usage,
        quota=quota,
        projected_cost=Decimal("30"),
    )
    if not gate["passed"]:
        raise representative.RepresentativeAcquisitionError(
            "; ".join(gate["failures"])
        )
    sql = representative.render_in_window_rate_sql(WINDOW)
    if "SELECT *" in sql.upper():
        raise representative.RepresentativeAcquisitionError(
            "sparse repair SQL contains SELECT *"
        )
    representative.write_text_atomic(SQL_PATH, sql)
    audit = source_audit()
    representative.write_json_atomic(SOURCE_AUDIT_PATH, audit)
    state = {
        "state": "planned",
        "window": WINDOW.key,
        "start_utc": WINDOW.start.isoformat(),
        "end_exclusive_utc": WINDOW.end.isoformat(),
        "method": audit["selected_method"],
        "sql_path": representative.relative(SQL_PATH),
        "sql_sha256": representative.sha256_file(SQL_PATH),
        "usage_before": str(current_usage),
        "quota": str(quota),
        "projected_cost": "30",
        "credit_gate": gate,
        "oversized_execution": {
            "query_id": 8113737,
            "execution_id": "01KYF4M8P8RD4TZYB7V5NX3KAT",
            "reported_dimensions": [419830, 12],
            "observed_credit_delta": "11.734",
            "classification": "superseded_oversized_rate_export",
            "result_retrieval_count": 0,
        },
        "created_at_utc": representative.utc_now(),
    }
    representative.write_json_atomic(STATE_PATH, state)
    return state


def record_submission(
    query_id: int,
    execution_id: str,
    *,
    reported_rows: int,
    execution_cost_credits: Decimal,
) -> dict[str, Any]:
    state = json.loads(STATE_PATH.read_text())
    if state["state"] != "planned":
        raise representative.RepresentativeAcquisitionError(
            "rate repair is not in planned state"
        )
    if reported_rows > 5_000:
        state.update({
            "state": "halted_result_over_5000_rows",
            "query_id": query_id,
            "execution_id": execution_id,
            "reported_rows": reported_rows,
            "execution_cost_credits": str(execution_cost_credits),
            "result_retrieval_count": 0,
        })
        representative.write_json_atomic(STATE_PATH, state)
        return state
    state.update({
        "state": "execution_completed",
        "query_id": query_id,
        "query_url": f"https://dune.com/queries/{query_id}",
        "execution_id": execution_id,
        "reported_rows": reported_rows,
        "execution_cost_credits": str(execution_cost_credits),
        "result_retrieval_count": 0,
        "recorded_at_utc": representative.utc_now(),
    })
    representative.write_json_atomic(STATE_PATH, state)
    return state


def persist(usage_after: Decimal) -> dict[str, Any]:
    state = json.loads(STATE_PATH.read_text())
    if state["state"] != "execution_completed":
        raise representative.RepresentativeAcquisitionError(
            "execution is not ready for one result retrieval"
        )
    payload = json.loads(PAGE_PATH.read_text())
    rows, columns, total = representative._normalise_page(payload)
    if total != state["reported_rows"] or len(rows) != total:
        raise representative.RepresentativeAcquisitionError(
            "sparse rate result is incomplete"
        )
    if columns != list(representative.RATE_COLUMNS):
        raise representative.RepresentativeAcquisitionError(
            f"unexpected sparse raw schema: {columns}"
        )
    raw_validation = representative.validate_rate_rows(rows, WINDOW)
    if not raw_validation["validation_passed"]:
        raise representative.RepresentativeAcquisitionError(
            "; ".join(raw_validation["failures"])
        )
    if RAW_PATH.exists():
        persisted_rows = representative.load_csv(RAW_PATH)
        if persisted_rows != [
            {column: "" if row.get(column) is None else str(row.get(column))
             for column in representative.RATE_COLUMNS}
            for row in rows
        ]:
            raise representative.RepresentativeAcquisitionError(
                "existing acquired rate CSV differs from retrieved page"
            )
    else:
        representative.write_csv_atomic(
            RAW_PATH, representative.RATE_COLUMNS, rows
        )
    boundary = representative.load_csv(BOUNDARY_PATH)
    sparse, validation = representative.build_sparse_effective_rates(
        boundary, rows, WINDOW
    )
    if not validation["validation_passed"]:
        representative.write_json_atomic(VALIDATION_PATH, validation)
        raise representative.RepresentativeAcquisitionError(
            "; ".join(validation["failures"])
        )
    representative.write_csv_atomic(
        SPARSE_PATH, representative.SPARSE_RATE_COLUMNS, sparse
    )
    validation.update({
        "raw_validation": raw_validation,
        "processed_path": representative.relative(SPARSE_PATH),
        "processed_sha256": representative.sha256_file(SPARSE_PATH),
        "processed_size_bytes": SPARSE_PATH.stat().st_size,
        "deterministic_reproducibility": True,
        "phase1d_hourly_cross_check": (
            "Not used as accumulated-rate proof: the hourly Phase 1D panel "
            "contains duty/base settings, not Vat accumulated rate."
        ),
    })
    metadata = {
        "method": "B_hybrid_local_opening_plus_sparse_dune_window",
        "query_id": state["query_id"],
        "query_url": state["query_url"],
        "execution_id": state["execution_id"],
        "sql_path": state["sql_path"],
        "sql_sha256": state["sql_sha256"],
        "raw_path": representative.relative(RAW_PATH),
        "raw_rows": len(rows),
        "raw_columns": len(representative.RATE_COLUMNS),
        "raw_size_bytes": RAW_PATH.stat().st_size,
        "raw_sha256": representative.sha256_file(RAW_PATH),
        "page_path": representative.relative(PAGE_PATH),
        "page_size_bytes": PAGE_PATH.stat().st_size,
        "page_sha256": representative.sha256_file(PAGE_PATH),
        "retrieval_count": 1,
        "source_audit_path": representative.relative(SOURCE_AUDIT_PATH),
        "source_audit_sha256": representative.sha256_file(SOURCE_AUDIT_PATH),
        "processed_path": representative.relative(SPARSE_PATH),
        "processed_rows": len(sparse),
        "processed_columns": len(representative.SPARSE_RATE_COLUMNS),
        "processed_size_bytes": SPARSE_PATH.stat().st_size,
        "processed_sha256": representative.sha256_file(SPARSE_PATH),
        "opening_source_path": representative.relative(BOUNDARY_PATH),
        "opening_source_sha256": representative.sha256_file(BOUNDARY_PATH),
        "usage_before": state["usage_before"],
        "usage_after": str(usage_after),
        "observed_credit_delta": str(
            usage_after - Decimal(state["usage_before"])
        ),
        "execution_cost_credits": state["execution_cost_credits"],
        "units": {
            "accumulated_rate": "RAY integer, 1e27",
            "normalised_debt": "WAD integer, 1e18",
            "debt_dai": "art_raw * rate_raw_ray / 1e45",
        },
        "created_at_utc": representative.utc_now(),
    }
    representative.write_json_atomic(VALIDATION_PATH, validation)
    representative.write_json_atomic(METADATA_PATH, metadata)
    state.update({
        "state": "complete",
        "result_retrieval_count": 1,
        "raw_file_persisted": True,
        "validation_passed": True,
        "raw_sha256": metadata["raw_sha256"],
        "processed_sha256": metadata["processed_sha256"],
        "usage_after": str(usage_after),
        "observed_credit_delta": metadata["observed_credit_delta"],
        "completed_at_utc": representative.utc_now(),
    })
    representative.write_json_atomic(STATE_PATH, state)
    return {"metadata": metadata, "validation": validation, "state": state}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_command = commands.add_parser("prepare")
    prepare_command.add_argument("--current-usage", type=Decimal, required=True)
    prepare_command.add_argument("--quota", type=Decimal, required=True)
    record = commands.add_parser("record-submission")
    record.add_argument("--query-id", type=int, required=True)
    record.add_argument("--execution-id", required=True)
    record.add_argument("--reported-rows", type=int, required=True)
    record.add_argument("--execution-cost-credits", type=Decimal, required=True)
    persist_command = commands.add_parser("persist")
    persist_command.add_argument("--usage-after", type=Decimal, required=True)
    commands.add_parser("reconstruct")
    args = parser.parse_args()

    if args.command == "prepare":
        result = prepare(args.current_usage, args.quota)
    elif args.command == "record-submission":
        result = record_submission(
            args.query_id,
            args.execution_id,
            reported_rows=args.reported_rows,
            execution_cost_credits=args.execution_cost_credits,
        )
    elif args.command == "persist":
        result = persist(args.usage_after)
    else:
        result = representative.reconstruct_window(WINDOW)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
