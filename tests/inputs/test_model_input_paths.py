"""Stage 4 domain-owned compact runtime-input and protocol path gates."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sys

import pandas as pd
import yaml

from tests.support import REPOSITORY_ROOT as ROOT
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dai_sim.inputs.gas import DEFAULT_LIQUIDATION_GAS_POOL_PATH
from dai_sim.inputs.liquidations import DEFAULT_LIQUIDATION_ARRIVAL_POOL_PATH
from dai_sim.inputs.market import DEFAULT_MARKET_GAS_POOL_PATH
from dai_sim.inputs.vaults import DEFAULT_POOL_MANIFEST, DEFAULT_POOL_PATH
from workflows.liquidations import build_inputs as arrival_builder
from workflows.market import build_inputs as environment_builder
from workflows.vaults import build_inputs as vault_builder


EXPECTED = {
    ROOT / "data/vaults/model_inputs/initialisation/pool.csv": (
        "5230a30aa2c2aebe69ef859ccdcbb785eb44f20a691b431f2fd01b0d16558892",
        (7208, 12),
    ),
    ROOT / "data/market/model_inputs/environment_blocks/pool.csv": (
        "b69276801bacf789f8ae91789983cc98a8a6d42d0a992940c0bcfa109ca25b7d",
        (27024, 16),
    ),
    ROOT / "data/liquidations/model_inputs/keeper_gas/pool.csv": (
        "37a5f49f4cc273b9d0d9526609be7f14b91b78939acf26e4dce00b66443e1594",
        (1287, 11),
    ),
    ROOT / "data/liquidations/model_inputs/arrival/hourly_pool.csv": (
        "cc29435bb0434237aba438ee98bded77f086704c7400bb5016e2b58703258c8a",
        (1104, 12),
    ),
    ROOT / "data/liquidations/model_inputs/arrival/sequence_pool.csv": (
        "9fdd5f3b5fb97e2dd41d0201bad34909ad05e423ad6b52f65219f49f02a1c7ed",
        (54, 10),
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runtime_input_hashes_shapes_and_authoritative_paths() -> None:
    for path, (checksum, shape) in EXPECTED.items():
        assert path.is_file()
        assert _sha256(path) == checksum
        assert pd.read_csv(path).shape == shape
    assert not list((ROOT / "config/empirical/data").glob("*.csv"))


def test_loader_defaults_use_only_domain_owned_paths() -> None:
    assert DEFAULT_POOL_PATH == next(path for path in EXPECTED if "initialisation" in str(path))
    assert DEFAULT_MARKET_GAS_POOL_PATH == next(
        path for path in EXPECTED if "environment_blocks" in str(path)
    )
    assert DEFAULT_LIQUIDATION_GAS_POOL_PATH == next(
        path for path in EXPECTED if "keeper_gas" in str(path)
    )
    assert DEFAULT_LIQUIDATION_ARRIVAL_POOL_PATH == next(
        path for path in EXPECTED if path.name == "hourly_pool.csv"
    )
    assert DEFAULT_POOL_MANIFEST == (
        ROOT / "data/vaults/model_inputs/initialisation/manifest.json"
    )


def test_moved_manifests_reference_new_paths_and_preserve_pool_hashes() -> None:
    manifests = (
        ROOT / "data/market/model_inputs/environment_blocks/manifest.json",
        ROOT / "data/vaults/model_inputs/initialisation/manifest.json",
        ROOT / "data/liquidations/model_inputs/keeper_gas/manifest.json",
        ROOT / "data/liquidations/model_inputs/arrival/manifest.json",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in manifests)
    assert "config/empirical/data/" not in text
    for checksum, _ in EXPECTED.values():
        assert checksum in text


def test_builder_defaults_target_domain_owned_paths_without_rebuilding() -> None:
    assert vault_builder.DEFAULT_OUTPUT == DEFAULT_POOL_PATH
    assert vault_builder.DEFAULT_METADATA == DEFAULT_POOL_MANIFEST
    assert environment_builder.MARKET_GAS_OUTPUT == DEFAULT_MARKET_GAS_POOL_PATH
    assert (
        environment_builder.LIQUIDATION_GAS_OUTPUT
        == DEFAULT_LIQUIDATION_GAS_POOL_PATH
    )
    assert arrival_builder.OUTPUT_DIR == (
        ROOT / "data/liquidations/model_inputs/arrival"
    )


def test_protocol_configuration_is_semantically_migrated() -> None:
    authoritative = yaml.safe_load(
        (ROOT / "config/protocol/parameters.yaml").read_text(encoding="utf-8")
    )
    compatibility = yaml.safe_load(
        (ROOT / "config/protocol.yaml").read_text(encoding="utf-8")
    )
    assert authoritative == compatibility
    assert authoritative["collateral_mapping_path"] == (
        "config/protocol/collateral_types.csv"
    )
    assert (
        (ROOT / "config/protocol/collateral_types.csv").read_bytes()
        == (ROOT / "config/collateral_mapping.csv").read_bytes()
    )


def test_parameter_adoption_manifest_has_semantic_profile_reference() -> None:
    path = ROOT / "data/protocol/provenance/parameter_adoption/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert "config/profiles/empirical.yaml" in manifest["legacy_default_preservation"]
    assert "config/empirical/phase2_empirical_baseline.yaml" not in (
        manifest["legacy_default_preservation"]
    )
