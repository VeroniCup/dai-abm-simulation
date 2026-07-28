"""Structural checks for the semantic Stage 10 output hierarchy."""

from __future__ import annotations

import inspect
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
        / "outputs/diagnostics/calibration/parameter_adoption/"
        "configuration_ready_candidates.csv"
    )


def test_market_input_builder_reads_moved_evidence_without_output_change() -> None:
    namespace = runpy.run_path(
        str(REPOSITORY_ROOT / "workflows/market/build_inputs.py")
    )
    assert namespace["AUDIT_DIR"] == (
        REPOSITORY_ROOT
        / "outputs/diagnostics/input_construction/market_gas"
    )
    assert namespace["verify_source_checksums"]() == namespace["SOURCE_CHECKSUMS"]

    market, _market_audit = namespace["build_market_gas_pool"]()
    liquidation, _liquidation_audit = namespace["build_liquidation_gas_pool"]()
    assert market.to_csv(index=False).encode() == (
        REPOSITORY_ROOT / "data/market/model_inputs/environment_blocks/pool.csv"
    ).read_bytes()
    assert liquidation.to_csv(index=False).encode() == (
        REPOSITORY_ROOT / "data/liquidations/model_inputs/keeper_gas/pool.csv"
    ).read_bytes()
