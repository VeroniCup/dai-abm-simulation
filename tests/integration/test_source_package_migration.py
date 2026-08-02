"""Characterisation tests for the semantic source package."""

from __future__ import annotations

import ast
from dataclasses import fields
import importlib
from pathlib import Path
import subprocess
import sys


from tests.support import REPOSITORY_ROOT
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


AUTHORITATIVE_MODULES = (
    "dai_sim.model.collateral",
    "dai_sim.model.vault",
    "dai_sim.model.liquidation",
    "dai_sim.model.market",
    "dai_sim.model.collateral_prices",
    "dai_sim.model.confidence",
    "dai_sim.model.simulation",
    "dai_sim.model.metrics",
    "dai_sim.inputs.configuration",
    "dai_sim.inputs.sources",
    "dai_sim.inputs.environment",
    "dai_sim.inputs.market",
    "dai_sim.inputs.gas",
    "dai_sim.inputs.vaults",
    "dai_sim.inputs.liquidations",
    "dai_sim.inputs.protocol",
    "dai_sim.inputs.confidence_scenarios",
    "dai_sim.calibration.data_loading",
    "dai_sim.calibration.statistics",
    "dai_sim.calibration.market",
    "dai_sim.calibration.gas",
    "dai_sim.calibration.vaults",
    "dai_sim.calibration.liquidations",
    "dai_sim.calibration.protocol",
    "dai_sim.calibration.adoption",
    "dai_sim.calibration.validation",
    "dai_sim.validation.confidence_scenarios",
    "dai_sim.validation.integrated_eth",
    "dai_sim.validation.multicollateral",
    "dai_sim.experiments.scenarios",
    "dai_sim.experiments.runner",
    "dai_sim.experiments.summaries",
    "dai_sim.experiments.plots",
    "dai_sim.experiments.mechanism.eth_recovery",
    "dai_sim.experiments.mechanism.constrained_eth_recovery",
    "dai_sim.experiments.final",
)


def test_every_authoritative_module_imports() -> None:
    imported = [importlib.import_module(name) for name in AUTHORITATIVE_MODULES]
    assert [module.__name__ for module in imported] == list(AUTHORITATIVE_MODULES)


def test_authoritative_imports_do_not_use_compatibility_paths() -> None:
    forbidden_roots = {
        "collateral",
        "confidence",
        "dai_market",
        "empirical_config",
        "empirical_data",
        "empirical_sources",
        "environment_inputs",
        "experiments",
        "gas_process",
        "liquidation",
        "liquidation_demand",
        "market_bootstrap",
        "metrics",
        "plot_results",
        "price_process",
        "protocol_data",
        "simulation",
        "vault",
        "vault_initialisation",
    }
    violations: list[tuple[str, str]] = []
    for module_name in AUTHORITATIVE_MODULES:
        module = importlib.import_module(module_name)
        path = Path(module.__file__)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: str | None = None
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                imported = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in forbidden_roots or alias.name.startswith(
                        ("src.estimation", "scripts", "tests")
                    ):
                        violations.append((module_name, alias.name))
            if imported is None:
                continue
            root = imported.split(".", 1)[0]
            if root in forbidden_roots or imported.startswith(
                ("src.estimation", "scripts", "tests")
            ):
                violations.append((module_name, imported))
    assert violations == []


def test_imports_do_not_read_empirical_data_or_create_rng(tmp_path: Path) -> None:
    module_literal = repr(AUTHORITATIVE_MODULES)
    source = f"""
import importlib
import numpy as np
import pandas as pd

def forbidden(*args, **kwargs):
    raise AssertionError("import-time empirical loading or RNG creation")

pd.read_csv = forbidden
pd.read_parquet = forbidden
np.random.default_rng = forbidden
for name in {module_literal}:
    importlib.import_module(name)
"""
    completed = subprocess.run(
        [sys.executable, "-c", source],
        cwd=tmp_path,
        env={"PYTHONPATH": str(SRC_ROOT)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_core_dataclass_field_order_is_stable() -> None:
    expected = {
        "dai_sim.model.collateral.CollateralConfig": (
            "name",
            "initial_price",
            "liquidation_ratio",
            "liquidation_penalty",
            "target_debt_share",
            "max_close_factor",
        ),
        "dai_sim.model.collateral.CollateralPortfolioConfig": (
            "name",
            "collaterals",
        ),
        "dai_sim.model.vault.Vault": (
            "vault_id",
            "owner_id",
            "collateral_amount",
            "debt_dai",
            "liquidation_ratio",
                "collateral_type",
                "is_active",
                "is_liquidated",
                "exact_ilk",
            ),
        "dai_sim.model.liquidation.LiquidationConfig": (
            "liquidation_penalty",
            "gas_cost",
            "risk_cost_rate",
            "max_close_factor",
            "max_liquidations_per_step",
        ),
        "dai_sim.model.confidence.ConfidenceConfig": (
            "normal_lower_price",
            "normal_upper_price",
            "stress_lower_price",
            "max_normal_liquidatable_share",
            "max_stress_liquidatable_share",
            "bad_debt_panic_threshold",
            "normal_confidence",
            "stress_confidence",
            "panic_confidence",
            "panic_selling_multiplier",
        ),
        "dai_sim.model.market.DAIMarketConfig": (
            "peg_price",
            "price_adjustment_speed",
            "arbitrage_strength",
            "above_peg_supply_strength",
            "panic_strength",
            "noise_std",
            "min_price",
            "max_price",
            "enable_peg_recovery",
            "arbitrage_recovery_strength",
            "policy_feedback_strength",
            "bad_debt_recovery_drag",
            "min_recovery_confidence",
        ),
        "dai_sim.model.collateral_prices.PriceProcessConfig": (
            "n_steps",
            "initial_price",
            "random_seed",
        ),
        "dai_sim.model.simulation.SimulationConfig": (
            "n_steps",
            "n_vaults",
            "initial_eth_price",
            "liquidation_ratio",
            "oracle_delay_steps",
            "debt_mean",
            "debt_std",
            "collateral_ratio_mean",
            "collateral_ratio_std",
            "random_seed",
            "collateral_portfolio",
        ),
    }
    actual = {}
    for qualified_name in expected:
        module_name, class_name = qualified_name.rsplit(".", 1)
        cls = getattr(importlib.import_module(module_name), class_name)
        actual[qualified_name] = tuple(field.name for field in fields(cls))
    assert actual == expected
