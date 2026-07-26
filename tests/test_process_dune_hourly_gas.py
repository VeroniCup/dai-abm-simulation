"""Deterministic tests for local Phase 1B gas and market--gas processing."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import acquire_dune_hourly_gas as acquisition
from scripts import process_dune_hourly_gas as processing


def gas_fixture() -> pd.DataFrame:
    timestamps = pd.date_range(
        acquisition.LONDON_HOUR - pd.Timedelta(hours=2), periods=7, freq="1h"
    )
    medians = [10.0, 20.0, 30.0, 40.0, 60.0, 100.0, 200.0]
    rows = []
    for index, (timestamp, median) in enumerate(zip(timestamps, medians, strict=True)):
        post = timestamp > acquisition.LONDON_HOUR
        mixed = timestamp == acquisition.LONDON_HOUR
        rows.append(
            {
                "timestamp_utc": timestamp,
                "transaction_count": 100 + index,
                "block_count": 10,
                "median_effective_gas_price_gwei": median,
                "mean_effective_gas_price_gwei": median + 1.0,
                "p75_effective_gas_price_gwei": median + 2.0,
                "p90_effective_gas_price_gwei": median + 4.0,
                "p95_effective_gas_price_gwei": median + 6.0,
                "p99_effective_gas_price_gwei": median + 10.0 + index,
                "median_base_fee_gwei": median * 0.7 if post or mixed else np.nan,
                "p95_base_fee_gwei": median * 0.8 if post or mixed else np.nan,
                "median_priority_fee_gwei": median * 0.2 if post or mixed else np.nan,
                "block_utilisation": 0.5 + index * 0.01,
                "target_normalised_block_utilisation": 0.8 + index * 0.05,
                "transaction_total_gas_used": 1_000_000 + index,
                "block_total_gas_used": 1_000_000 + index,
                "gas_used_reconciliation_difference": 0.0,
                "failed_transaction_share": 0.01 + index * 0.01,
                "null_success_count": 0,
                "eip1559_block_share": 1.0 if post else (0.5 if mixed else 0.0),
            }
        )
    return pd.DataFrame(rows, columns=acquisition.EXPECTED_COLUMNS)


def market_fixture(timestamps: pd.Series) -> pd.DataFrame:
    count = len(timestamps)
    eth = np.linspace(2_000.0, 2_060.0, count)
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(timestamps, utc=True),
            "eth_price_usd": eth,
            "wbtc_price_usd": np.linspace(30_000.0, 30_600.0, count),
            "dai_price_usd": np.linspace(0.998, 1.002, count),
            "usdc_price_usd": np.linspace(0.999, 1.001, count),
        }
    )
    for asset in ("eth", "wbtc", "dai", "usdc"):
        frame[f"{asset}_log_return"] = np.log(frame[f"{asset}_price_usd"]).diff()
    frame["dai_peg_deviation"] = frame["dai_price_usd"] - 1.0
    frame["usdc_peg_deviation"] = frame["usdc_price_usd"] - 1.0
    frame["dai_abs_peg_deviation"] = frame["dai_peg_deviation"].abs()
    frame["usdc_abs_peg_deviation"] = frame["usdc_peg_deviation"].abs()
    frame["dai_below_peg"] = frame["dai_price_usd"].lt(1.0).astype(int)
    frame["usdc_below_peg"] = frame["usdc_price_usd"].lt(1.0).astype(int)
    frame["dai_source"] = "fixture"
    frame["usdc_source"] = "fixture"
    return frame.loc[:, processing.MARKET_COLUMNS]


class IntegrityTests(unittest.TestCase):
    def test_checksum_gate_stops_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.csv"
            validation = root / "validation.json"
            raw.write_text("not,the,authorised,file\n", encoding="utf-8")
            validation.write_text('{"validation_passed": true}\n', encoding="utf-8")
            with self.assertRaisesRegex(processing.GasProcessingError, "SHA-256"):
                processing.validate_raw_gas_integrity(
                    raw, validation, expected_sha256="0" * 64
                )

    def test_source_has_no_external_network_or_api_path(self) -> None:
        source = Path(processing.__file__).read_text(encoding="utf-8")
        for forbidden in ("requests", "urlopen", "socket", "DUNE_API_KEY"):
            self.assertNotIn(forbidden, source)


class FormulaTests(unittest.TestCase):
    def test_raw_columns_are_preserved_and_formulas_are_exact(self) -> None:
        raw = gas_fixture()
        panel, _, zeros = processing.build_processed_gas_panel(raw)
        self.assertEqual(zeros, {column: 0 for column in processing.LOG_PRICE_COLUMNS})
        for column in acquisition.EXPECTED_COLUMNS:
            if column == "timestamp_utc":
                pd.testing.assert_series_equal(
                    pd.to_datetime(panel[column], utc=True),
                    pd.to_datetime(raw[column], utc=True),
                    check_names=False,
                )
            else:
                np.testing.assert_array_equal(panel[column], raw[column])
        expected_spread = raw["p90_effective_gas_price_gwei"] - raw[
            "median_effective_gas_price_gwei"
        ]
        np.testing.assert_allclose(
            panel["effective_gas_price_spread_p90_median_gwei"], expected_spread
        )
        np.testing.assert_allclose(
            panel["effective_gas_price_ratio_p99_median"],
            raw["p99_effective_gas_price_gwei"] / raw["median_effective_gas_price_gwei"],
        )
        expected_change = np.log(raw["median_effective_gas_price_gwei"]).diff()
        np.testing.assert_allclose(
            panel["median_effective_gas_price_log_change"],
            expected_change,
            equal_nan=True,
        )
        self.assertEqual(int(panel["median_effective_gas_price_log_change"].isna().sum()), 1)

    def test_london_structural_nulls_and_mixed_hour_are_preserved(self) -> None:
        panel, _, _ = processing.build_processed_gas_panel(gas_fixture())
        pre = panel["fee_market_regime"].eq("pre_london")
        mixed = panel["fee_market_regime"].eq("mixed_london_hour")
        post = panel["fee_market_regime"].eq("post_london")
        self.assertTrue(panel.loc[pre, "base_fee_share_of_median_effective_price"].isna().all())
        self.assertTrue(panel.loc[pre, "priority_fee_share_of_median_effective_price"].isna().all())
        self.assertEqual(panel.loc[mixed, "eip1559_block_share"].item(), 0.5)
        self.assertTrue(panel.loc[mixed | post, "base_fee_share_of_median_effective_price"].notna().all())

    def test_exact_join_and_standardised_cost_formula(self) -> None:
        gas, _, _ = processing.build_processed_gas_panel(gas_fixture())
        market = market_fixture(gas["timestamp_utc"])
        joined = processing.build_joined_panel(market, gas)
        self.assertEqual(len(joined), len(gas))
        column = "cost_usd_300k_p90_gas"
        expected = 300_000 * joined["p90_effective_gas_price_gwei"] * 1e-9 * joined["eth_price_usd"]
        np.testing.assert_allclose(joined[column], expected)
        broken = market.iloc[:-1].copy()
        with self.assertRaisesRegex(processing.GasProcessingError, "timestamps"):
            processing.build_joined_panel(broken, gas)

    def test_candidate_a_boundaries_are_inclusive_as_documented(self) -> None:
        raw = gas_fixture().iloc[:4].copy()
        raw["median_effective_gas_price_gwei"] = [10.0, 20.0, 30.0, 31.0]
        raw["p75_effective_gas_price_gwei"] = [11.0, 21.0, 31.0, 32.0]
        raw["p90_effective_gas_price_gwei"] = [12.0, 22.0, 32.0, 33.0]
        raw["p95_effective_gas_price_gwei"] = [13.0, 23.0, 33.0, 34.0]
        raw["p99_effective_gas_price_gwei"] = [14.0, 24.0, 34.0, 35.0]
        thresholds = processing.regime_thresholds(raw)
        thresholds["classification_a_median_p75_gwei"] = 20.0
        thresholds["classification_a_median_p95_gwei"] = 30.0
        panel, _, _ = processing.build_processed_gas_panel(raw, thresholds)
        self.assertEqual(
            panel["gas_regime_candidate_a"].tolist(),
            ["normal", "normal", "stress", "extreme"],
        )


class RegimeAndReviewTests(unittest.TestCase):
    def test_transition_matrix_counts_known_pairs(self) -> None:
        regimes = pd.Series(["normal", "normal", "stress", "extreme", "extreme"])
        timestamps = pd.Series(pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC"))
        records = processing.transition_matrix(
            regimes, timestamps, processing.CLASSIFICATION_A_STATES, "a"
        )
        lookup = {(row["from_regime"], row["to_regime"]): row["transition_count"] for row in records}
        self.assertEqual(lookup[("normal", "normal")], 1)
        self.assertEqual(lookup[("normal", "stress")], 1)
        self.assertEqual(lookup[("stress", "extreme")], 1)
        self.assertEqual(lookup[("extreme", "extreme")], 1)

    def test_run_construction_is_deterministic(self) -> None:
        timestamps = pd.Series(pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC"))
        flags = pd.Series([False, True, True, False, True])
        first = processing.construct_flagged_runs(flags, timestamps)
        second = processing.construct_flagged_runs(flags, timestamps)
        pd.testing.assert_series_equal(first[0], second[0])
        pd.testing.assert_series_equal(first[1], second[1])
        self.assertEqual(first[1].dropna().astype(int).tolist(), [2, 2, 1])

    def test_extreme_review_selects_union_and_context(self) -> None:
        gas, thresholds, _ = processing.build_processed_gas_panel(gas_fixture())
        market = market_fixture(gas["timestamp_utc"])
        joined = processing.build_joined_panel(market, gas)
        thresholds.update(
            {
                "review_median_p95_gwei": 150.0,
                "review_p99_p95_gwei": 10_000.0,
                "review_utilisation_p95": 10.0,
                "review_failed_share_p95": 10.0,
                "review_abs_median_log_change_p99": 10.0,
            }
        )
        review = processing.build_extreme_review(joined, thresholds)
        self.assertEqual(len(review), 1)
        self.assertTrue(review["trigger_median_effective_gas_price_above_p95"].item())
        self.assertEqual(review["consecutive_flagged_run_length_hours"].item(), 1)
        self.assertTrue(review["previous_hour_median_gas_price_gwei"].notna().all())

    def test_deterministic_csv_serialisation_checksum(self) -> None:
        gas, _, _ = processing.build_processed_gas_panel(gas_fixture())
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.csv"
            second = Path(directory) / "second.csv"
            processing.write_csv_atomically(gas, first)
            processing.write_csv_atomically(gas, second)
            self.assertEqual(processing.sha256_file(first), processing.sha256_file(second))


if __name__ == "__main__":
    unittest.main()
