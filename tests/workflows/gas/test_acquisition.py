"""Tests for the bounded Dune gas-acquisition pipeline."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd


from tests.support import REPOSITORY_ROOT
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from workflows.gas import acquire as gas


def make_row(timestamp: pd.Timestamp) -> dict[str, object]:
    """Return one internally consistent synthetic hourly result row."""
    post = timestamp > gas.LONDON_HOUR
    mixed = timestamp == gas.LONDON_HOUR
    return {
        "timestamp_utc": timestamp.strftime("%Y-%m-%d %H:%M:%S.000 UTC"),
        "transaction_count": 100,
        "block_count": 10,
        "median_effective_gas_price_gwei": 10.0,
        "mean_effective_gas_price_gwei": 12.0,
        "p75_effective_gas_price_gwei": 15.0,
        "p90_effective_gas_price_gwei": 20.0,
        "p95_effective_gas_price_gwei": 25.0,
        "p99_effective_gas_price_gwei": 30.0,
        "median_base_fee_gwei": 8.0 if post or mixed else None,
        "p95_base_fee_gwei": 9.0 if post or mixed else None,
        "median_priority_fee_gwei": 2.0 if post or mixed else None,
        "block_utilisation": 0.5,
        "target_normalised_block_utilisation": 1.0,
        "transaction_total_gas_used": "1000000",
        "block_total_gas_used": "1000000",
        "gas_used_reconciliation_difference": 0.0,
        "failed_transaction_share": 0.05,
        "null_success_count": 0,
        "eip1559_block_share": 1.0 if post else (0.5 if mixed else 0.0),
    }


class ChunkPlanTests(unittest.TestCase):
    def test_authorised_plan_is_contiguous_and_complete(self) -> None:
        self.assertEqual(
            gas.validate_chunk_plan(),
            {"chunk_count": 13, "expected_hours": 27_024},
        )

    def test_plan_rejects_a_gap(self) -> None:
        broken = list(gas.CHUNKS)
        broken[1] = (2, "2021-07-02", "2021-10-01")
        with self.assertRaises(gas.GasAcquisitionError):
            gas.validate_chunk_plan(broken)

    def test_sql_rendering_changes_only_interval_tokens(self) -> None:
        template = gas.DEFAULT_TEMPLATE.read_text(encoding="utf-8")
        first, _ = gas.render_chunk_sql(gas.DEFAULT_TEMPLATE, 1)
        second, _ = gas.render_chunk_sql(gas.DEFAULT_TEMPLATE, 2)
        self.assertNotEqual(first, second)
        self.assertEqual(first.count("2021-06-01"), 4)
        self.assertEqual(first.count("2021-07-01"), 4)
        normalised_first = first.replace("2021-06-01", "{{START_DATE}}").replace(
            "2021-07-01", "{{END_DATE}}"
        )
        self.assertEqual(normalised_first, template)
        self.assertNotIn("SELECT *", first.upper())
        self.assertNotIn("ORDER BY", first.upper())

    def test_local_pipeline_has_no_network_or_retry_path(self) -> None:
        source = Path(gas.__file__).read_text(encoding="utf-8")
        self.assertNotIn("DUNE_API_KEY", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("time.sleep", source)


class ValidationTests(unittest.TestCase):
    def test_duplicate_and_missing_hours_are_detected(self) -> None:
        start = pd.Timestamp("2023-01-01T00:00:00Z")
        end = start + pd.Timedelta(hours=2)
        rows = [make_row(start), make_row(start)]
        report = gas.validate_rows(rows, start, end)
        self.assertFalse(report["validation_passed"])
        self.assertGreater(report["duplicate_hour_row_count"], 0)
        self.assertEqual(report["missing_hour_count"], 1)

    def test_london_pre_mixed_and_post_semantics_pass(self) -> None:
        start = gas.LONDON_HOUR - pd.Timedelta(hours=1)
        end = gas.LONDON_HOUR + pd.Timedelta(hours=2)
        rows = [make_row(start + pd.Timedelta(hours=offset)) for offset in range(3)]
        report = gas.validate_rows(rows, start, end)
        self.assertTrue(report["validation_passed"], report["failures"])
        self.assertEqual(report["pre_london_hour_count"], 1)
        self.assertEqual(report["mixed_london_hour_count"], 1)
        self.assertEqual(report["mixed_london_eip1559_block_share"], 0.5)
        self.assertEqual(report["fully_post_london_hour_count"], 1)

    def test_percentile_ordering_failure_is_reported(self) -> None:
        start = pd.Timestamp("2023-01-01T00:00:00Z")
        row = make_row(start)
        row["p90_effective_gas_price_gwei"] = 14.0
        report = gas.validate_rows([row], start, start + pd.Timedelta(hours=1))
        self.assertEqual(report["percentile_ordering_violation_count"], 1)
        self.assertFalse(report["validation_passed"])

    def test_gas_reconciliation_failure_is_reported(self) -> None:
        start = pd.Timestamp("2023-01-01T00:00:00Z")
        row = make_row(start)
        row["block_total_gas_used"] = "999999"
        row["gas_used_reconciliation_difference"] = 1.0
        report = gas.validate_rows([row], start, start + pd.Timedelta(hours=1))
        self.assertEqual(report["gas_reconciliation_violation_count"], 1)
        self.assertFalse(report["validation_passed"])


class AcquisitionStateTests(unittest.TestCase):
    def make_context(self, root: Path) -> dict[str, Path]:
        return {
            "state_dir": root / "chunks" / "state",
            "chunk_dir": root / "chunks",
            "ledger": root / "ledger.json",
            "payload": root / "chunks" / ".chunk_01.partial.json",
        }

    def realistic_payload(self) -> dict[str, object]:
        start, end = gas.chunk_bounds(1)
        rows = [
            make_row(timestamp)
            for timestamp in pd.date_range(
                start, end - pd.Timedelta(hours=1), freq="1h"
            )
        ]
        return {
            "executionId": "execution-1",
            "state": "COMPLETED",
            "resultMetadata": {
                "totalRowCount": len(rows),
                "columns": [
                    {"name": column, "type": "double"}
                    for column in gas.EXPECTED_COLUMNS
                ],
                "executionCostCredits": "0.1",
            },
            "data": {"rows": rows},
        }

    def prepare_execution(self, paths: dict[str, Path]) -> None:
        gas.initialise_chunk(1, paths["state_dir"], gas.DEFAULT_TEMPLATE)
        gas.update_chunk_state(
            paths["state_dir"],
            1,
            "query_created",
            query_id=123,
            query_url="https://dune.com/queries/123",
            usage_before=10.0,
            creation_timestamp_utc="2026-01-01T00:00:00Z",
        )
        gas.update_chunk_state(
            paths["state_dir"],
            1,
            "execution_submitted",
            execution_id="execution-1",
            execution_submitted_at_utc="2026-01-01T00:00:01Z",
        )
        gas.write_json(paths["payload"], self.realistic_payload())

    def persist(self, paths: dict[str, Path], fail_after: str | None = None) -> dict[str, object]:
        return gas.persist_chunk_payload(
            chunk_number=1,
            payload_file=paths["payload"],
            state_dir=paths["state_dir"],
            chunk_dir=paths["chunk_dir"],
            ledger_path=paths["ledger"],
            template=gas.DEFAULT_TEMPLATE,
            duration_seconds=1.0,
            fail_after=fail_after,
        )

    def test_combined_csv_is_deterministic_for_input_order(self) -> None:
        first = make_row(pd.Timestamp("2023-01-01T00:00:00Z"))
        second = make_row(pd.Timestamp("2023-01-01T01:00:00Z"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = root / "left.csv"
            right = root / "right.csv"
            gas.write_combined_rows(left, [second, first])
            gas.write_combined_rows(right, [first, second])
            self.assertEqual(left.read_bytes(), right.read_bytes())

    def test_closed_stdin_does_not_affect_filesystem_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.make_context(root)
            self.prepare_execution(paths)
            closed_stdin = io.StringIO()
            closed_stdin.close()
            with patch("sys.stdin", closed_stdin):
                record = self.persist(paths)
            self.assertTrue(record["validation_passed"])
            self.assertTrue(record["raw_file_persisted"])

    def test_realistic_result_persists_without_stdin_and_has_one_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.make_context(Path(directory))
            self.prepare_execution(paths)
            state = self.persist(paths)
            raw_path = gas.PROJECT_ROOT / state["raw_file_path"]
            if not raw_path.exists():
                raw_path = paths["chunk_dir"] / gas.chunk_stem(1)
                raw_path = raw_path.with_suffix(".csv")
            self.assertEqual(state["row_count"], 720)
            self.assertEqual(len(raw_path.read_text(encoding="utf-8").splitlines()), 721)

    def test_query_id_survives_failure_before_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.make_context(Path(directory))
            self.prepare_execution(paths)
            state = gas.update_chunk_state(
                paths["state_dir"], 1, "failed", failure="before retrieval"
            )
            recovered = gas.load_state(gas.state_path(paths["state_dir"], 1))
            self.assertEqual(recovered["query_id"], 123)
            self.assertEqual(recovered["execution_id"], "execution-1")
            self.assertFalse(state["result_retrieved"])

    def test_failure_after_retrieval_before_rename_preserves_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.make_context(Path(directory))
            self.prepare_execution(paths)
            with self.assertRaises(gas.GasAcquisitionError):
                self.persist(paths, "before_rename")
            state = gas.load_state(gas.state_path(paths["state_dir"], 1))
            self.assertTrue(state["result_retrieved"])
            self.assertFalse(state["raw_file_persisted"])
            self.assertTrue(any(paths["chunk_dir"].glob("*.partial.csv")))

    def test_failure_after_raw_persistence_before_validation_is_durable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.make_context(Path(directory))
            self.prepare_execution(paths)
            with self.assertRaises(gas.GasAcquisitionError):
                self.persist(paths, "raw_persistence")
            state = gas.load_state(gas.state_path(paths["state_dir"], 1))
            self.assertTrue(state["raw_file_persisted"])
            self.assertFalse(state["validation_passed"])
            self.assertTrue(Path(state["raw_file_path"]).exists())

    def test_completed_chunk_cannot_be_reexecuted_even_with_replace_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.make_context(Path(directory))
            self.prepare_execution(paths)
            self.persist(paths)
            with self.assertRaises(gas.GasAcquisitionError):
                gas.initialise_chunk(
                    1, paths["state_dir"], gas.DEFAULT_TEMPLATE,
                    replace_failed_chunk=True,
                )

    def test_failed_chunk_requires_explicit_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.make_context(Path(directory))
            gas.initialise_chunk(1, paths["state_dir"], gas.DEFAULT_TEMPLATE)
            gas.update_chunk_state(paths["state_dir"], 1, "failed", failure="test")
            with self.assertRaises(gas.GasAcquisitionError):
                gas.initialise_chunk(1, paths["state_dir"], gas.DEFAULT_TEMPLATE)
            replacement = gas.initialise_chunk(
                1, paths["state_dir"], gas.DEFAULT_TEMPLATE,
                replace_failed_chunk=True,
            )
            self.assertEqual(replacement["state"], "planned")
            self.assertTrue(replacement["replacement_explicitly_authorised"])

    def test_explicit_replacement_preserves_failed_raw_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.make_context(Path(directory))
            self.prepare_execution(paths)
            with self.assertRaises(gas.GasAcquisitionError):
                self.persist(paths, "raw_persistence")
            failed_state = gas.load_state(gas.state_path(paths["state_dir"], 1))
            failed_raw = Path(failed_state["raw_file_path"])
            self.assertTrue(failed_raw.exists())
            gas.initialise_chunk(
                1,
                paths["state_dir"],
                gas.DEFAULT_TEMPLATE,
                replace_failed_chunk=True,
            )
            self.assertFalse(failed_raw.exists())
            self.assertTrue(
                any(paths["chunk_dir"].glob(f"{gas.chunk_stem(1)}.replaced-*.csv"))
            )

    def test_atomic_ledger_write_is_valid_and_contains_no_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self.make_context(Path(directory))
            self.prepare_execution(paths)
            self.persist(paths)
            ledger_text = paths["ledger"].read_text(encoding="utf-8")
            json.loads(ledger_text)
            self.assertFalse(paths["ledger"].with_suffix(".json.tmp").exists())
            self.assertNotIn("api_key", ledger_text.lower())
            self.assertNotIn("secret", ledger_text.lower())

    def test_partial_ledger_never_concatenates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "ledger.json"
            gas.write_json(
                ledger,
                {"chunks": [{"chunk_number": 1, "state": "failed", "validation_passed": False}]},
            )
            args = type("Args", (), {
                "ledger": ledger,
                "combined": root / "combined.csv",
                "template": gas.DEFAULT_TEMPLATE,
                "validation": root / "validation.json",
                "metadata": root / "metadata.json",
            })()
            with self.assertRaises(gas.GasAcquisitionError):
                gas.finalise(args)
            self.assertFalse(args.combined.exists())


if __name__ == "__main__":
    unittest.main()
