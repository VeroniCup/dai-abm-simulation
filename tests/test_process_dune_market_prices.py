"""Tests for deterministic local Phase 1A market-price processing."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.process_dune_market_prices import (  # noqa: E402
    ASSET_PRICE_COLUMNS,
    ProcessingError,
    build_processed_panel,
    build_stablecoin_extreme_review,
    sha256_file,
    validate_processed_panel,
    validate_raw_integrity,
    write_csv_atomically,
)


class ProcessDuneMarketPricesTests(unittest.TestCase):
    """Exercise exact pivots, formulas, flags and integrity stops."""

    @staticmethod
    def _raw_frame(hours: int = 5) -> pd.DataFrame:
        timestamps = pd.date_range("2024-06-01T00:00:00Z", periods=hours, freq="1h")
        price_paths = {
            "ETH": [2000.0, 2010.0, 1980.0, 2020.0, 2050.0],
            "WBTC": [60000.0, 60200.0, 59000.0, 61000.0, 62000.0],
            "DAI": [1.0, 0.97, 0.96, 1.0, 1.001],
            "USDC": [1.0, 1.0, 0.96, 0.97, 1.0],
        }
        rows = []
        for asset, values in price_paths.items():
            for timestamp, price in zip(timestamps, values, strict=True):
                rows.append(
                    {
                        "timestamp_utc": timestamp,
                        "asset": asset,
                        "dune_instrument": "WETH" if asset == "ETH" else asset,
                        "price_usd": price,
                        "blockchain": "ethereum",
                        "contract_address": "0xfixture",
                        "source": "coinpaprika",
                        "volume_usd": "<nil>",
                    }
                )
        return pd.DataFrame(rows)

    def test_processed_panel_preserves_prices_and_first_returns_are_missing(self) -> None:
        raw = self._raw_frame()
        start = pd.Timestamp("2024-06-01T00:00:00Z")
        end = pd.Timestamp("2024-06-01T05:00:00Z")
        panel = build_processed_panel(raw, start=start, end_exclusive=end)

        self.assertEqual(panel.shape, (5, 17))
        for asset, column in ASSET_PRICE_COLUMNS.items():
            expected = (
                raw.loc[raw["asset"] == asset]
                .sort_values("timestamp_utc")["price_usd"]
                .to_numpy()
            )
            np.testing.assert_array_equal(panel[column].to_numpy(), expected)
            return_column = f"{asset.lower()}_log_return"
            self.assertTrue(pd.isna(panel[return_column].iloc[0]))
            self.assertEqual(int(panel[return_column].isna().sum()), 1)

    def test_extreme_review_retains_consecutive_runs_and_context(self) -> None:
        raw = self._raw_frame()
        start = pd.Timestamp("2024-06-01T00:00:00Z")
        end = pd.Timestamp("2024-06-01T05:00:00Z")
        panel = build_processed_panel(raw, start=start, end_exclusive=end)
        review = build_stablecoin_extreme_review(panel)

        dai = review.loc[review["asset"] == "DAI"]
        usdc = review.loc[review["asset"] == "USDC"]
        self.assertEqual(len(dai), 2)
        self.assertEqual(len(usdc), 2)
        self.assertEqual(set(dai["flagged_run_length_hours"]), {2})
        self.assertEqual(set(usdc["flagged_run_length_hours"]), {2})
        overlap = review.loc[
            review["timestamp_utc"] == pd.Timestamp("2024-06-01T02:00:00Z")
        ]
        self.assertTrue((overlap["both_stablecoins_abs_peg_above_0_02"] == 1).all())
        self.assertTrue(overlap["eth_price_usd"].notna().all())

    def test_written_panel_validates_against_raw_without_price_changes(self) -> None:
        raw = self._raw_frame()
        start = pd.Timestamp("2024-06-01T00:00:00Z")
        end = pd.Timestamp("2024-06-01T05:00:00Z")
        panel = build_processed_panel(raw, start=start, end_exclusive=end)
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            raw_path = directory_path / "raw.csv"
            processed_path = directory_path / "processed.csv"
            raw.to_csv(raw_path, index=False)
            write_csv_atomically(panel, processed_path)
            report, failures = validate_processed_panel(
                processed_path,
                raw_path,
                start=start,
                end_exclusive=end,
            )

        self.assertEqual(failures, [])
        self.assertTrue(report["validation_passed"])
        self.assertTrue(all(report["exact_raw_price_matches"].values()))
        self.assertEqual(report["infinity_count"], 0)

    def test_checksum_mismatch_stops_before_raw_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            raw_path = directory_path / "raw.csv"
            report_path = directory_path / "validation.json"
            raw_path.write_text("not,the,authorised,file\n", encoding="utf-8")
            report_path.write_text('{"validation_passed": true}\n', encoding="utf-8")
            observed = sha256_file(raw_path)
            self.assertNotEqual(observed, "0" * 64)
            with self.assertRaisesRegex(ProcessingError, "Raw SHA-256"):
                validate_raw_integrity(
                    raw_path,
                    report_path,
                    expected_sha256="0" * 64,
                )


if __name__ == "__main__":
    unittest.main()
