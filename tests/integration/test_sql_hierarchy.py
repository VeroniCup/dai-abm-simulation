"""Structural tests for the domain-based SQL hierarchy."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import re
import sys


from tests.support import REPOSITORY_ROOT
SQL_ROOT = REPOSITORY_ROOT / "sql"
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
CURRENT_SQL_INVENTORY_SHA256 = (
    "74789454e55f5d2f68e16cd8422b8ba797a47388712ac1c9b535010e49a5e554"
)


def _sql_paths() -> list[Path]:
    return sorted(SQL_ROOT.rglob("*.sql"))


def test_sql_inventory_maps_once_to_unique_targets() -> None:
    paths = _sql_paths()
    rows = "".join(
        f"{path.relative_to(REPOSITORY_ROOT).as_posix()}\0"
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}\n"
        for path in paths
    )
    assert len(paths) == 118
    assert len(paths) == len(set(paths))
    assert hashlib.sha256(rows.encode()).hexdigest() == (
        CURRENT_SQL_INVENTORY_SHA256
    )


def test_sql_hierarchy_contains_only_populated_semantic_domains() -> None:
    sql_files = tuple(_sql_paths())
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
        "/generated/history/" in path
        for path in HISTORICAL_TEMPLATE_TARGETS
    )


def test_obsolete_sql_paths_are_absent() -> None:
    assert not tuple(SQL_ROOT.glob("*.sql"))
    assert not tuple(REPOSITORY_ROOT.glob("sql/dune_*.sql"))


def test_workflows_and_wrappers_have_no_obsolete_sql_literals() -> None:
    for directory in ("workflows", "scripts"):
        for path in (REPOSITORY_ROOT / directory).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            references = set(
                re.findall(r"sql/[A-Za-z0-9_./-]+\.sql", text)
            )
            assert not any(reference.startswith("sql/dune_") for reference in references)
            assert all((REPOSITORY_ROOT / reference).is_file() for reference in references)
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
