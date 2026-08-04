"""Structural checks for the semantic output hierarchy."""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

import pandas as pd

from dai_sim.experiments import plots, runner
from dai_sim.inputs import configuration, protocol
from dai_sim.model import metrics

from tests.support import REPOSITORY_ROOT


SEMANTIC_EXPERIMENTS = {
    "baseline": "baseline",
    "oracle_delay": "oracle_delay",
    "shock_severity": "shock_severity",
    "confidence_sensitivity": "confidence",
    "peg_recovery": "peg_recovery",
    "multicollateral": "multi_collateral",
}


def test_experiment_result_figure_and_table_paths_are_semantic() -> None:
    for key, directory in SEMANTIC_EXPERIMENTS.items():
        assert plots.get_experiment_dir(key, "results") == (
            REPOSITORY_ROOT / "outputs/experiments" / directory
        )
        assert plots.get_experiment_dir(key, "figures") == (
            REPOSITORY_ROOT / "outputs/figures" / directory
        )
        assert plots.get_experiment_dir(key, "tables") == (
            REPOSITORY_ROOT / "outputs/tables" / directory
        )


def test_runner_defaults_cover_all_four_output_categories() -> None:
    assert runner.RESULTS_DIR == REPOSITORY_ROOT / "outputs/experiments/baseline"
    assert runner.BASELINE_TABLES_DIR == REPOSITORY_ROOT / "outputs/tables/baseline"
    assert runner.MULTICOLLATERAL_FIGURES_DIR == (
        REPOSITORY_ROOT / "outputs/figures/multi_collateral"
    )
    assert runner.MULTICOLLATERAL_DIAGNOSTICS_DIR == (
        REPOSITORY_ROOT
        / "outputs/diagnostics/regression_validation/multi_collateral"
    )


def test_clean_summary_default_uses_table_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    frame = pd.DataFrame({"scenario": ["baseline"], "value": [1.25]})
    table_dir = tmp_path / "tables" / "baseline"
    monkeypatch.setitem(metrics.EXPERIMENT_TABLE_DIRS, "baseline", table_dir)

    path = metrics.save_clean_summary(frame, experiment_name="baseline")

    assert path == table_dir / "summary_clean.csv"
    assert path.read_bytes() == b"scenario,value\nbaseline,1.25\n"


def test_clean_summary_explicit_path_behaviour_is_preserved(
    tmp_path: Path,
) -> None:
    frame = pd.DataFrame({"scenario": ["explicit"], "value": [2]})
    path = tmp_path / "caller" / "chosen.csv"

    returned = metrics.save_clean_summary(frame, path=path)

    assert returned == path
    assert path.read_bytes() == b"scenario,value\nexplicit,2\n"


def test_multicollateral_explicit_output_path_behaviour_is_preserved(
    tmp_path: Path,
) -> None:
    frames = [
        pd.DataFrame({"value": [value]})
        for value in (1, 2, 3, 4)
    ]

    paths = runner.save_multicollateral_outputs(
        *frames,
        output_dir=tmp_path,
    )

    assert set(paths.values()) == {
        tmp_path / "system_results.csv",
        tmp_path / "collateral_results.csv",
        tmp_path / "system_summary.csv",
        tmp_path / "collateral_summary.csv",
    }
    assert all(path.is_file() for path in paths.values())


def test_multicollateral_default_separates_results_and_tables() -> None:
    default = inspect.signature(
        runner.save_multicollateral_outputs
    ).parameters["output_dir"].default
    assert default == REPOSITORY_ROOT / "outputs/experiments/multi_collateral"
    assert runner.MULTICOLLATERAL_TABLES_DIR == (
        REPOSITORY_ROOT / "outputs/tables/multi_collateral"
    )


def test_version_control_output_surface_contains_policy_only() -> None:
    content_manifest = REPOSITORY_ROOT / "SUBMISSION_CONTENT_MANIFEST.json"
    if content_manifest.is_file():
        payload = json.loads(content_manifest.read_text(encoding="utf-8"))
        version_controlled = [
            item["path"]
            for item in payload["included_files"]
            if item["path"].startswith("outputs/")
        ]
        assert version_controlled == []
        return

    version_controlled = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "outputs",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert version_controlled == ["outputs/README.md"]


def test_active_code_has_no_obsolete_output_root() -> None:
    roots = (
        REPOSITORY_ROOT / "src/dai_sim",
        REPOSITORY_ROOT / "workflows",
    )
    obsolete = (
        "outputs/results",
        "outputs/empirical",
        "outputs/estimation",
        "data/processed/estimation",
    )
    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert not any(value in text for value in obsolete), path


def test_importing_output_modules_does_not_create_files(
    tmp_path: Path,
) -> None:
    before = list(tmp_path.rglob("*"))
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import dai_sim.experiments.runner;"
                "import dai_sim.experiments.plots;"
                "import dai_sim.model.metrics"
            ),
        ],
        cwd=tmp_path,
        check=True,
        env={
            **os.environ,
            "PYTHONPATH": str(REPOSITORY_ROOT / "src"),
        },
    )
    assert list(tmp_path.rglob("*")) == before


def test_protocol_synthetic_validation_uses_semantic_destination(
    monkeypatch,
) -> None:
    captured: list[Path] = []

    def _capture(_results, output_dir: Path) -> None:
        captured.append(output_dir)

    monkeypatch.setattr(protocol, "write_protocol_outputs", _capture)
    protocol.run_synthetic_validation(write_outputs=True)

    assert captured == [
        REPOSITORY_ROOT
        / "outputs/diagnostics/protocol/synthetic_validation"
    ]


def test_configuration_loads_same_moved_adoption_evidence() -> None:
    observed = configuration.verify_adoption_review_checksums()
    assert observed == configuration.EXPECTED_ADOPTION_REVIEW_CHECKSUMS
    assert configuration.CONFIGURATION_READY_CANDIDATES == (
        REPOSITORY_ROOT
        / "data/provenance/calibration/parameter_adoption/"
        "configuration_ready_candidates.csv"
    )


def test_market_input_builder_reads_moved_evidence_without_output_change(
    tmp_path: Path,
) -> None:
    namespace = runpy.run_path(
        str(REPOSITORY_ROOT / "workflows/market/build_inputs.py")
    )
    assert namespace["AUDIT_DIR"] == (
        REPOSITORY_ROOT
        / "outputs/diagnostics/input_construction/market_gas"
    )
    module_globals = namespace["build_market_gas_pool"].__globals__
    module_globals["REPOSITORY_ROOT"] = tmp_path
    paths = {
        "data/market/processed/combined/hourly_market_gas_panel.csv": (
            tmp_path
            / "data/market/processed/combined/hourly_market_gas_panel.csv"
        ),
        "outputs/diagnostics/calibration/market_gas_protocol/gas/gas_sampling_index.csv": (
            tmp_path
            / "outputs/diagnostics/calibration/market_gas_protocol/gas/"
            "gas_sampling_index.csv"
        ),
        "outputs/diagnostics/calibration/market_gas_protocol/diagnostics/calibration_validation_split.csv": (
            tmp_path
            / "outputs/diagnostics/calibration/market_gas_protocol/diagnostics/"
            "calibration_validation_split.csv"
        ),
        "outputs/diagnostics/calibration/market_gas_protocol/liquidations/liquidation_transaction_gas.csv": (
            tmp_path
            / "outputs/diagnostics/calibration/market_gas_protocol/liquidations/"
            "liquidation_transaction_gas.csv"
        ),
        "outputs/diagnostics/calibration/market_gas_protocol/review/gas_cost_sensitivity.csv": (
            tmp_path
            / "outputs/diagnostics/calibration/market_gas_protocol/review/"
            "gas_cost_sensitivity.csv"
        ),
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)

    timestamps = pd.date_range(
        "2022-10-31T00:00:00Z", periods=3, freq="h"
    )
    pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "eth_price_usd": [1500.0, 1490.0, 1510.0],
            "wbtc_price_usd": [20000.0, 19900.0, 20100.0],
            "eth_log_return": [0.0, -0.01, 0.02],
            "wbtc_log_return": [0.0, -0.005, 0.01],
            "median_effective_gas_price_gwei": [10.0, 20.0, 30.0],
            "p90_effective_gas_price_gwei": [15.0, 25.0, 35.0],
            "p99_effective_gas_price_gwei": [20.0, 30.0, 40.0],
            "target_normalised_block_utilisation": [0.8, 1.0, 1.2],
        }
    ).to_csv(paths[next(iter(paths))], index=False, lineterminator="\n")
    pd.DataFrame(
        {
            "source_row": [0, 1, 2],
            "timestamp_utc": timestamps,
            "is_calibration": [True, True, True],
            "is_validation": [False, False, False],
            "regime": ["normal", "stress", "extreme"],
        }
    ).to_csv(
        paths[
            "outputs/diagnostics/calibration/market_gas_protocol/gas/gas_sampling_index.csv"
        ],
        index=False,
        lineterminator="\n",
    )
    pd.DataFrame(
        {
            "sample": ["withheld_validation_ftx"],
            "start_utc": ["2022-10-31T01:00:00Z"],
            "end_utc": ["2022-10-31T01:00:00Z"],
        }
    ).to_csv(
        paths[
            "outputs/diagnostics/calibration/market_gas_protocol/diagnostics/calibration_validation_split.csv"
        ],
        index=False,
        lineterminator="\n",
    )
    pd.DataFrame(
        {
            "take_transaction_class": [
                "clean_single_take_single_auction",
                "clean_single_take_single_auction",
            ],
            "is_calibration": [True, True],
            "timestamp_utc": timestamps[:2],
            "block_number": [1, 2],
            "transaction_index": [0, 1],
            "gas_used": [100000, 200000],
            "effective_gas_price_gwei": [10.0, 0.0],
            "eth_price_usd": [1500.0, 1490.0],
            "transaction_gas_cost_eth": [0.001, 0.0],
            "transaction_gas_cost_usd": [1.5, 0.0],
            "regime": ["normal", "stress"],
        }
    ).to_csv(
        paths[
            "outputs/diagnostics/calibration/market_gas_protocol/liquidations/liquidation_transaction_gas.csv"
        ],
        index=False,
        lineterminator="\n",
    )
    pd.DataFrame({"policy": ["fixture"]}).to_csv(
        paths[
            "outputs/diagnostics/calibration/market_gas_protocol/review/gas_cost_sensitivity.csv"
        ],
        index=False,
        lineterminator="\n",
    )
    module_globals["SOURCE_CHECKSUMS"] = {
        relative: namespace["sha256_file"](path)
        for relative, path in paths.items()
    }

    assert namespace["verify_source_checksums"]() == module_globals[
        "SOURCE_CHECKSUMS"
    ]
    first_market, first_market_audit = namespace["build_market_gas_pool"]()
    first_liquidation, first_liquidation_audit = namespace[
        "build_liquidation_gas_pool"
    ]()
    second_market, second_market_audit = namespace["build_market_gas_pool"]()
    second_liquidation, second_liquidation_audit = namespace[
        "build_liquidation_gas_pool"
    ]()
    pd.testing.assert_frame_equal(first_market, second_market)
    pd.testing.assert_frame_equal(first_market_audit, second_market_audit)
    pd.testing.assert_frame_equal(first_liquidation, second_liquidation)
    pd.testing.assert_frame_equal(
        first_liquidation_audit, second_liquidation_audit
    )
    assert len(first_market) == 3
    assert int(first_market["is_withheld_ftx"].sum()) == 1
    assert len(first_liquidation) == 2
    assert int(first_liquidation["is_zero_gas_observation"].sum()) == 1
