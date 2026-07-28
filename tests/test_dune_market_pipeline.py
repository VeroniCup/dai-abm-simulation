"""Unit tests for the Dune hourly market-price acquisition pipeline."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from workflows.market import acquire as acquisition
from workflows.market import validate as validation


class AcquisitionTests(unittest.TestCase):
    """Check execution controls and lossless paginated retrieval."""

    def test_saved_query_execution_uses_small_engine_once(self) -> None:
        with patch.object(
            acquisition,
            "_request_json",
            return_value={"execution_id": "execution-1"},
        ) as request:
            execution_id = acquisition.execute_saved_query("not-a-real-key", 123)

        self.assertEqual(execution_id, "execution-1")
        request.assert_called_once_with(
            "not-a-real-key",
            "POST",
            f"{acquisition.API_ROOT}/query/123/execute",
            {"performance": "small"},
        )

    def test_mode_is_required(self) -> None:
        with patch.object(sys, "argv", ["acquire", "--query-id", "123"]):
            with self.assertRaises(SystemExit):
                acquisition.parse_args()

    def test_csv_pages_are_requested_once_and_joined_without_row_changes(self) -> None:
        first_page = b"timestamp_utc,asset\n2024-06-01 00:00:00 UTC,ETH\n"
        second_page = b"timestamp_utc,asset\n2024-06-01 01:00:00 UTC,ETH\n"
        responses = [
            (first_page, {"X-Dune-Next-Offset": "1"}),
            (second_page, {}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "raw.csv"
            with patch.object(
                acquisition,
                "_request",
                side_effect=responses,
            ) as request:
                page_count = acquisition.download_csv_once_per_page(
                    "not-a-real-key", "execution-1", output, 1
                )

            self.assertEqual(page_count, 2)
            self.assertEqual(
                output.read_bytes(),
                first_page + b"2024-06-01 01:00:00 UTC,ETH\n",
            )
            self.assertEqual(request.call_count, 2)
            requested_urls = [call.args[2] for call in request.call_args_list]
            self.assertEqual(len(requested_urls), len(set(requested_urls)))

    def test_api_key_is_read_from_environment_not_arguments(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["acquire", "--mode", "saved-query", "--query-id", "123"],
        ):
            arguments = acquisition.parse_args()

        self.assertFalse(hasattr(arguments, "api_key"))


class ValidationTests(unittest.TestCase):
    """Check complete and incomplete hourly grids without changing raw input."""

    @staticmethod
    def _complete_frame() -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for timestamp in ("2024-06-01T00:00:00Z", "2024-06-01T01:00:00Z"):
            for asset, identifiers in validation.EXPECTED.items():
                rows.append(
                    {
                        "timestamp_utc": timestamp,
                        "asset": asset,
                        "dune_instrument": identifiers["dune_instrument"],
                        "price_usd": 1.0,
                        "blockchain": "ethereum",
                        "contract_address": identifiers["contract_address"].upper(),
                        "source": "coinpaprika",
                        "volume_usd": 0.0,
                    }
                )
        return pd.DataFrame(rows, columns=validation.REQUIRED_COLUMNS)

    def test_complete_grid_passes_and_address_comparison_is_case_insensitive(self) -> None:
        frame = self._complete_frame()
        with tempfile.TemporaryDirectory() as directory:
            raw_path = Path(directory) / "raw.csv"
            frame.to_csv(raw_path, index=False)
            checksum_before = acquisition.sha256_file(raw_path)
            report, failures = validation.validate_prices(
                raw_path,
                requested_start=pd.Timestamp("2024-06-01T00:00:00Z"),
                requested_end=pd.Timestamp("2024-06-01T02:00:00Z"),
            )
            checksum_after = acquisition.sha256_file(raw_path)

        self.assertEqual(failures, [])
        self.assertTrue(report["validation_passed"])
        self.assertEqual(report["actual_total_rows"], 8)
        self.assertEqual(checksum_before, checksum_after)
        for asset_report in report["by_asset"].values():
            self.assertEqual(asset_report["missing_hour_count"], 0)
            self.assertEqual(asset_report["duplicate_asset_hour_count"], 0)

    def test_missing_hour_is_reported_without_imputation(self) -> None:
        frame = self._complete_frame()
        frame = frame.loc[
            ~(
                (frame["asset"] == "ETH")
                & (frame["timestamp_utc"] == "2024-06-01T01:00:00Z")
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            raw_path = Path(directory) / "raw.csv"
            frame.to_csv(raw_path, index=False)
            report, failures = validation.validate_prices(
                raw_path,
                requested_start=pd.Timestamp("2024-06-01T00:00:00Z"),
                requested_end=pd.Timestamp("2024-06-01T02:00:00Z"),
            )

        self.assertFalse(report["validation_passed"])
        self.assertEqual(report["by_asset"]["ETH"]["missing_hour_count"], 1)
        self.assertTrue(any("ETH is missing 1 requested hours" in item for item in failures))

    def test_dune_nil_volume_placeholder_is_reported_as_unavailable(self) -> None:
        frame = self._complete_frame()
        frame["volume_usd"] = "<nil>"
        with tempfile.TemporaryDirectory() as directory:
            raw_path = Path(directory) / "raw.csv"
            frame.to_csv(raw_path, index=False)
            report, failures = validation.validate_prices(
                raw_path,
                requested_start=pd.Timestamp("2024-06-01T00:00:00Z"),
                requested_end=pd.Timestamp("2024-06-01T02:00:00Z"),
            )

        self.assertEqual(failures, [])
        self.assertEqual(report["null_volume_count"], 8)
        for asset_report in report["by_asset"].values():
            self.assertEqual(asset_report["null_volume_count"], 2)


if __name__ == "__main__":
    unittest.main()
