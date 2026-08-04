"""Focused checks for Stage 10 output and empirical-data ignore rules."""

from __future__ import annotations

from tests.support import REPOSITORY_ROOT, is_ignored


def _ignored(path: str) -> bool:
    return is_ignored(path)


def test_generated_output_categories_are_ignored() -> None:
    assert _ignored("outputs/experiments/baseline/new_run.csv")
    assert _ignored("outputs/figures/baseline/new_plot.png")
    assert _ignored("outputs/diagnostics/calibration/new_review.csv")
    assert _ignored("outputs/tables/baseline/new_summary.csv")
    assert _ignored("outputs/reporting/dissertation/figures/new_figure.png")


def test_empirical_payload_and_transient_provenance_policy_is_preserved() -> None:
    assert _ignored("data/market/raw/new_payload.csv")
    assert _ignored("data/market/processed/new_panel.csv")
    assert _ignored("data/vaults/provenance/state/new_state.json")


def test_local_environment_and_operating_system_noise_is_ignored() -> None:
    assert _ignored(".env")
    assert _ignored(".DS_Store")


def test_source_inputs_manifests_sql_docs_and_fixtures_remain_addable() -> None:
    addable = (
        "src/dai_sim/model/new_module.py",
        "config/profiles/new_profile.yaml",
        "data/market/model_inputs/environment_blocks/new_pool.csv",
        "data/provenance/data_manifest.csv",
        "sql/market/templates/new_query.sql",
        "docs/overview/new_guide.md",
        "tests/fixtures/market/new_fixture.csv",
        "outputs/README.md",
    )
    assert all(not _ignored(path) for path in addable)


def test_ignore_file_has_no_global_generated_extension_rule() -> None:
    text = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.csv", "*.json", "*.png", "*.yaml"):
        assert pattern not in {
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }


def test_old_output_and_estimation_roots_are_not_compatibility_targets() -> None:
    assert not (REPOSITORY_ROOT / "outputs/results").exists()
    assert not (REPOSITORY_ROOT / "outputs/empirical").exists()
    assert not (REPOSITORY_ROOT / "outputs/estimation").exists()
    assert not (REPOSITORY_ROOT / "data/processed/estimation").exists()
