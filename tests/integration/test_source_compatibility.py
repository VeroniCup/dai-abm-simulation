"""Compatibility tests for legacy source imports retained during Stage 3."""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
import sys


from tests.support import REPOSITORY_ROOT
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


ONE_TO_ONE_MODULES = {
    "collateral": "dai_sim.model.collateral",
    "confidence": "dai_sim.model.confidence",
    "dai_market": "dai_sim.model.market",
    "empirical_config": "dai_sim.inputs.configuration",
    "empirical_sources": "dai_sim.inputs.sources",
    "environment_inputs": "dai_sim.inputs.environment",
    "gas_process": "dai_sim.inputs.gas",
    "liquidation": "dai_sim.model.liquidation",
    "liquidation_demand": "dai_sim.inputs.liquidations",
    "market_bootstrap": "dai_sim.inputs.market",
    "metrics": "dai_sim.model.metrics",
    "plot_results": "dai_sim.experiments.plots",
    "price_process": "dai_sim.model.collateral_prices",
    "protocol_data": "dai_sim.inputs.protocol",
    "vault": "dai_sim.model.vault",
    "vault_initialisation": "dai_sim.inputs.vaults",
}

ESTIMATION_MODULES = {
    "adoption_review": "dai_sim.calibration.adoption",
    "data_loading": "dai_sim.calibration.data_loading",
    "phase2a_review": "dai_sim.calibration.validation",
    "phase2b_vaults": "dai_sim.calibration.vaults",
    "phase2c_liquidations": "dai_sim.calibration.liquidations",
    "statistics": "dai_sim.calibration.statistics",
}

SPLIT_COMPATIBILITY_MODULES = (
    "empirical_data",
    "simulation",
    "src.estimation.phase2a",
)


def test_legacy_flat_and_src_imports_succeed() -> None:
    legacy_modules = (
        *ONE_TO_ONE_MODULES,
        "empirical_data",
        "experiments",
        "simulation",
    )
    for name in legacy_modules:
        importlib.import_module(name)
        importlib.import_module(f"src.{name}")
    for name in (*ESTIMATION_MODULES, "phase2a"):
        importlib.import_module(f"src.estimation.{name}")


def test_one_to_one_legacy_modules_alias_authoritative_modules() -> None:
    for legacy_name, authoritative_name in ONE_TO_ONE_MODULES.items():
        authoritative = importlib.import_module(authoritative_name)
        assert importlib.import_module(legacy_name) is authoritative
        assert importlib.import_module(f"src.{legacy_name}") is authoritative
    for legacy_name, authoritative_name in ESTIMATION_MODULES.items():
        assert importlib.import_module(
            f"src.estimation.{legacy_name}"
        ) is importlib.import_module(authoritative_name)


def test_split_compatibility_exports_resolve_to_authoritative_objects() -> None:
    empirical = importlib.import_module("empirical_data")
    input_market = importlib.import_module("dai_sim.inputs.market")
    calibration_market = importlib.import_module("dai_sim.calibration.market")
    assert empirical.EmpiricalConfig is input_market.EmpiricalConfig
    assert (
        empirical.build_market_time_panel is input_market.build_market_time_panel
    )
    assert (
        empirical.estimate_regime_thresholds
        is calibration_market.estimate_regime_thresholds
    )

    phase2a = importlib.import_module("src.estimation.phase2a")
    gas = importlib.import_module("dai_sim.calibration.gas")
    statistics = importlib.import_module("dai_sim.calibration.statistics")
    assert (
        phase2a.calculate_transaction_gas_cost
        is gas.calculate_transaction_gas_cost
    )
    assert (
        phase2a.transition_probabilities is statistics.transition_probabilities
    )

    simulation = importlib.import_module("simulation")
    model_simulation = importlib.import_module("dai_sim.model.simulation")
    liquidation_inputs = importlib.import_module("dai_sim.inputs.liquidations")
    assert (
        simulation.run_simulation_with_price_path
        is model_simulation.run_simulation_with_price_path
    )
    assert (
        simulation.LiquidationDemandProcess
        is liquidation_inputs.LiquidationDemandProcess
    )


def test_legacy_signatures_match_authoritative_signatures() -> None:
    pairs = (
        ("collateral", "dai_sim.model.collateral", "normalise_collateral_prices"),
        ("liquidation", "dai_sim.model.liquidation", "liquidate_vaults"),
        ("vault", "dai_sim.model.vault", "create_vault_from_target_cr"),
        (
            "price_process",
            "dai_sim.model.collateral_prices",
            "generate_gbm_price_path",
        ),
        (
            "src.estimation.statistics",
            "dai_sim.calibration.statistics",
            "estimate_regime_thresholds",
        ),
    )
    for legacy_name, authoritative_name, symbol in pairs:
        legacy = getattr(importlib.import_module(legacy_name), symbol)
        authoritative = getattr(
            importlib.import_module(authoritative_name), symbol
        )
        assert legacy is authoritative
        assert inspect.signature(legacy) == inspect.signature(authoritative)


def test_legacy_module_monkeypatch_reaches_authoritative_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    legacy = importlib.import_module("experiments")
    authoritative = importlib.import_module("dai_sim.experiments.runner")
    assert legacy is authoritative
    monkeypatch.setattr(legacy, "RESULTS_DIR", tmp_path)
    assert authoritative.RESULTS_DIR == tmp_path


def test_compatibility_modules_contain_no_implementation_definitions() -> None:
    paths = [
        *(SRC_ROOT / f"{name}.py" for name in ONE_TO_ONE_MODULES),
        *(SRC_ROOT / "estimation" / f"{name}.py" for name in ESTIMATION_MODULES),
        *(SRC_ROOT / f"{name}.py" for name in ("experiments",)),
        SRC_ROOT / "empirical_data.py",
        SRC_ROOT / "simulation.py",
        SRC_ROOT / "estimation/phase2a.py",
    ]
    definitions: list[tuple[str, str]] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
            ):
                definitions.append((str(path.relative_to(REPOSITORY_ROOT)), type(node).__name__))
    assert definitions == []
