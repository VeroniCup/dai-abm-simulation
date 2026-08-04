from __future__ import annotations

import importlib
import json
import sys

import yaml


from tests.support import REPOSITORY_ROOT as ROOT
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def assert_paths(*paths: str) -> None:
    for path in paths:
        assert (ROOT / path).exists(), path


def test_model_journey() -> None:
    assert_paths(
        "README.md",
        "docs/components.md",
        "src/dai_sim/model",
    )
    importlib.import_module("dai_sim.model.simulation")


def test_liquidation_mechanics_journey() -> None:
    assert_paths(
        "docs/components.md",
        "src/dai_sim/model/liquidation.py",
    )
    module = importlib.import_module("dai_sim.model.liquidation")
    assert hasattr(module, "LiquidationConfig")
    assert hasattr(module, "liquidate_vaults")


def test_empirical_liquidation_input_journey() -> None:
    assert_paths(
        "docs/components.md",
        "data/liquidations/model_inputs",
        "src/dai_sim/inputs/liquidations.py",
    )
    importlib.import_module("dai_sim.inputs.liquidations")


def test_empirical_profile_journey() -> None:
    assert_paths(
        "docs/running.md",
        "config/profiles/empirical.yaml",
        "src/dai_sim/experiments/runner.py",
    )
    profile = yaml.safe_load(
        (ROOT / "config/profiles/empirical.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(profile, dict)
    importlib.import_module("dai_sim.experiments.runner")


def test_multi_collateral_journey() -> None:
    assert_paths(
        "README.md",
        "docs/components.md",
        "src/dai_sim/experiments/scenarios.py",
        "src/dai_sim/experiments/runner.py",
    )
    runner = importlib.import_module("dai_sim.experiments.runner")
    assert hasattr(runner, "run_multicollateral_experiment")


def test_market_and_gas_calibration_journey() -> None:
    assert_paths(
        "docs/components.md",
        "data/market/model_inputs/environment_blocks",
        "src/dai_sim/calibration/market.py",
        "src/dai_sim/calibration/gas.py",
        "workflows/calibration/market_gas_protocol.py",
    )


def test_data_provenance_journey() -> None:
    assert_paths(
        "docs/repository_structure.md",
        "data/provenance/index.json",
        "data/provenance/calibration/manifest.json",
        "sql/market/templates/hourly_prices.sql",
        "workflows/market/acquire.py",
    )


def test_regression_journey() -> None:
    record_path = (
        ROOT
        / "data/provenance/maintenance/submission_portability/"
        "historical_document_checksums.json"
    )
    assert_paths(
        "docs/running.md",
        record_path.relative_to(ROOT).as_posix(),
        "tests",
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["classification"] == "historical_document_checksum_record"
