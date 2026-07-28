"""Path-only regression gates for the post-Stage-11 correction."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from dai_sim.calibration import data_loading, liquidations, vaults
from workflows.inputs import (
    validate_environment,
    validate_liquidations,
    validate_vaults,
)
from workflows.liquidations import acquire as liquidation_acquisition
from workflows.protocol import acquire as protocol_acquisition
from workflows.vaults import acquire_representative


def test_input_validation_destinations_are_semantic() -> None:
    root = data_loading.PROJECT_ROOT
    assert validate_vaults.OUTPUT_DIR == (
        root / "outputs/diagnostics/input_construction/vaults"
    )
    assert validate_environment.OUTPUT_DIR == (
        root / "outputs/diagnostics/input_construction/market_gas"
    )
    assert validate_liquidations.OUTPUT_DIR == (
        root / "outputs/diagnostics/input_construction/liquidations"
    )
    assert not (root / "data/processed/estimation").exists()


def test_input_validation_filenames_are_semantic() -> None:
    root = data_loading.PROJECT_ROOT
    expected = {
        "workflows/inputs/validate_vaults.py": (
            "vault_initialisation_smoke_results.csv",
            "vault_initialisation_metadata.json",
        ),
        "workflows/inputs/validate_environment.py": (
            "market_gas_smoke_results.csv",
            "market_gas_metadata.json",
        ),
        "workflows/inputs/validate_liquidations.py": (
            "liquidation_input_smoke_results.csv",
            "liquidation_input_metadata.json",
        ),
    }
    obsolete = (
        "tranche_b_smoke_results.csv",
        "tranche_b_run_metadata.json",
        "tranche_c_smoke_results.csv",
        "tranche_c_run_metadata.json",
        "tranche_d_smoke_results.csv",
        "tranche_d_run_metadata.json",
    )
    for relative, names in expected.items():
        source = (root / Path(relative)).read_text(encoding="utf-8")
        assert all(name in source for name in names)
        assert not any(name in source for name in obsolete)


def test_protocol_and_liquidation_products_use_semantic_filenames() -> None:
    root = data_loading.PROJECT_ROOT
    assert protocol_acquisition.HOURLY_PATH == (
        root / "data/protocol/processed/hourly_protocol_parameters.csv"
    )
    assert vaults.PROTOCOL_PATH == protocol_acquisition.HOURLY_PATH
    assert liquidations.PROTOCOL_PANEL == protocol_acquisition.HOURLY_PATH
    assert acquire_representative.PROTOCOL_PATH == protocol_acquisition.HOURLY_PATH

    expected = {
        "liquidation_actions_2021-06-01_2024-06-30.csv",
        "liquidation_transactions_2021-06-01_2024-06-30.csv",
        "liquidation_auctions_2021-06-01_2024-06-30.csv",
        "liquidation_hourly_by_ilk_2021-06-01_2024-06-30.csv",
    }
    assert {spec.path.name for spec in data_loading._liquidation_specs()} == expected
    assert liquidation_acquisition.ACTION_COMBINED.name in expected
    assert liquidation_acquisition.TRANSACTION_COMBINED.name in expected
    assert liquidation_acquisition.AUCTION_SUMMARY.name in expected
    assert liquidation_acquisition.HOURLY_PANEL.name in expected
    assert acquire_representative.LIQUIDATION_ACTIONS_PATH.name in expected
    assert acquire_representative.LIQUIDATION_AUCTIONS_PATH.name in expected
    assert acquire_representative.LIQUIDATION_TRANSACTIONS_PATH.name in expected


def test_representative_auction_extract_has_a_semantic_filename() -> None:
    assert "phase" not in "liquidation_auctions.csv"
    assert "tranche" not in "liquidation_auctions.csv"
    assert acquire_representative.TRANCHE_MANIFEST.name == (
        "representative_windows_manifest.json"
    )


def test_authorised_path_modules_are_import_safe(tmp_path: Path) -> None:
    """Importing path-only modules must not acquire data or create outputs."""
    modules = (
        "dai_sim.calibration.data_loading",
        "dai_sim.calibration.liquidations",
        "dai_sim.calibration.vaults",
        "workflows.inputs.validate_environment",
        "workflows.inputs.validate_liquidations",
        "workflows.inputs.validate_vaults",
        "workflows.liquidations.acquire",
        "workflows.protocol.acquire",
        "workflows.vaults.acquire_representative",
    )
    code = f"""
import importlib
import pathlib
import urllib.request

pathlib.Path.mkdir = lambda *args, **kwargs: (_ for _ in ()).throw(
    AssertionError("import created a directory")
)
urllib.request.urlopen = lambda *args, **kwargs: (_ for _ in ()).throw(
    AssertionError("import accessed the network")
)
for name in {modules!r}:
    importlib.import_module(name)
"""
    subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=tmp_path,
        env={
            "PYTHONPATH": os.pathsep.join(
                (str(data_loading.PROJECT_ROOT), str(data_loading.PROJECT_ROOT / "src"))
            ),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=True,
    )
    assert list(tmp_path.iterdir()) == []
