"""Structural tests for the domain-based SQL hierarchy."""

from __future__ import annotations

import csv
import importlib
from pathlib import Path
import re
import sys


from tests.support import REPOSITORY_ROOT
SQL_ROOT = REPOSITORY_ROOT / "sql"
PATH_MAP = REPOSITORY_ROOT / "docs/repository_restructuring_path_map.csv"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
HISTORICAL_TEMPLATE_TARGETS = {
    "sql/liquidations/generated/history/liquidation_actions_diagnostic.sql",
    "sql/liquidations/generated/history/liquidation_diagnostic.sql",
    "sql/protocol/generated/history/clipper_stopped_diagnostic.sql",
    "sql/protocol/generated/history/clipper_stopped_minimal_diagnostic.sql",
    "sql/protocol/generated/history/eth_a_debt_ceiling_diagnostic.sql",
    "sql/protocol/generated/history/vat_wbtc_activation_diagnostic.sql",
}
POST_RESTRUCTURING_ACTIVE_SQL = {
    "sql/market/templates/hourly_market_prices.sql",
}


def _sql_mapping() -> list[dict[str, str]]:
    with PATH_MAP.open(encoding="utf-8", newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row["current_path"].startswith("sql/")
        ]


def test_sql_inventory_maps_once_to_unique_targets() -> None:
    mapping = _sql_mapping()
    sources = [row["current_path"] for row in mapping]
    targets = [row["proposed_path"] for row in mapping]
    assert len(mapping) == 117
    assert len(sources) == len(set(sources))
    assert len(targets) == len(set(targets))
    assert all(row["migration_stage"] == "07_sql" for row in mapping)
    actual = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in SQL_ROOT.rglob("*.sql")
    }
    assert actual == set(targets) | POST_RESTRUCTURING_ACTIVE_SQL


def test_sql_hierarchy_contains_only_populated_semantic_domains() -> None:
    sql_files = tuple(SQL_ROOT.rglob("*.sql"))
    assert len(sql_files) == 117 + len(POST_RESTRUCTURING_ACTIVE_SQL)
    assert {path.relative_to(SQL_ROOT).parts[0] for path in sql_files} == {
        "gas",
        "liquidations",
        "market",
        "protocol",
        "vaults",
    }
    assert all(
        path.relative_to(SQL_ROOT).parts[1] in {"templates", "generated"}
        for path in sql_files
    )
    assert not any(path.name in {".gitkeep", "README", "README.md"} for path in sql_files)
    assert all(
        any(directory.rglob("*.sql"))
        for directory in SQL_ROOT.iterdir()
        if directory.is_dir()
    )


def test_template_and_generated_storage_matches_approved_map() -> None:
    mapping = _sql_mapping()
    target_rows = {row["proposed_path"]: row for row in mapping}
    template_paths = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (SQL_ROOT).glob("*/templates/**/*.sql")
    }
    generated_paths = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (SQL_ROOT).glob("*/generated/**/*.sql")
    }
    assert len(template_paths) == 14 + len(POST_RESTRUCTURING_ACTIVE_SQL)
    assert len(generated_paths) == 103
    assert POST_RESTRUCTURING_ACTIVE_SQL <= template_paths
    assert HISTORICAL_TEMPLATE_TARGETS <= generated_paths
    assert all(
        target_rows[path]["archive_status"] == "historical"
        for path in HISTORICAL_TEMPLATE_TARGETS
    )
    assert all(
        target_rows[path]["current_role"] == "SQL template or diagnostic"
        for path in HISTORICAL_TEMPLATE_TARGETS
    )


def test_obsolete_sql_paths_are_absent() -> None:
    for row in _sql_mapping():
        source = REPOSITORY_ROOT / row["current_path"]
        target = REPOSITORY_ROOT / row["proposed_path"]
        assert target.is_file()
        if source != target:
            assert not source.exists()
    assert not tuple(SQL_ROOT.glob("*.sql"))


def test_workflows_and_wrappers_have_no_obsolete_sql_literals() -> None:
    obsolete = {
        row["current_path"]
        for row in _sql_mapping()
        if row["current_path"] != row["proposed_path"]
    }
    for directory in ("workflows", "scripts"):
        for path in (REPOSITORY_ROOT / directory).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert not (obsolete & set(re.findall(r"sql/[A-Za-z0-9_./-]+\.sql", text)))
    assert not any(
        ".sql" in path.read_text(encoding="utf-8")
        for path in (REPOSITORY_ROOT / "scripts").rglob("*.py")
    )


def test_authoritative_workflow_sql_defaults_use_semantic_paths() -> None:
    market = importlib.import_module("workflows.market.acquire")
    gas = importlib.import_module("workflows.gas.acquire")
    liquidations = importlib.import_module("workflows.liquidations.acquire")
    protocol = importlib.import_module("workflows.protocol.acquire")
    vaults = importlib.import_module("workflows.vaults.acquire")

    assert market.DEFAULT_SQL_FILE == SQL_ROOT / "market/templates/hourly_prices.sql"
    assert gas.DEFAULT_TEMPLATE == SQL_ROOT / "gas/templates/hourly_conditions.sql"
    assert liquidations.SQL_ROOT == SQL_ROOT / "liquidations/generated/history"
    assert vaults.GENERATED_SQL_ROOT == SQL_ROOT / "vaults/generated"
    assert vaults.TEMPLATE_PATH == SQL_ROOT / "vaults/templates/vat_mutations_monthly.sql"
    assert {spec.sql_path for spec in protocol.MODULES.values()} == {
        SQL_ROOT / "protocol/templates/vat_parameters.sql",
        SQL_ROOT / "protocol/templates/spot_parameters.sql",
        SQL_ROOT / "protocol/templates/jug_parameters.sql",
        SQL_ROOT / "protocol/templates/dog_parameters.sql",
        SQL_ROOT / "protocol/templates/clipper_parameters.sql",
    }
