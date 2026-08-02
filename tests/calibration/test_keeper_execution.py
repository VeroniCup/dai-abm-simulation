"""Tests for the non-adopted keeper-execution calibration."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from dai_sim.calibration.keeper_execution import (
    KeeperExecutionDesign,
    audit_runtime_semantics,
    collateral_comparability,
    estimate_profit_hurdle,
    mixed_collateral_smoke,
    nearest_rank,
    scientific_identity,
)
from dai_sim.inputs.keeper_execution import resolve_keeper_execution_candidate

from tests.evidence_contracts import validate_keeper_execution_compact_evidence


def test_runtime_semantics_are_global_and_profit_gated() -> None:
    audit = audit_runtime_semantics()
    assert audit["verified"]
    assert audit["capacity_scope"] == (
        "global shared count after cross-collateral ranking"
    )
    assert audit["execution_rule"] == "expected_profit > 0"


def test_nearest_rank_preserves_integer_count_support() -> None:
    values = [0, 2, 5, 9]
    assert nearest_rank(values, 0.75) == 5
    assert nearest_rank(values, 0.90) == 9
    with pytest.raises(ValueError, match="empty"):
        nearest_rank([], 0.90)


def test_preregistration_is_result_blind_and_excludes_validation() -> None:
    payload = validate_keeper_execution_compact_evidence()["specification"]
    encoded = json.dumps(payload, sort_keys=True)
    assert "candidate_value" not in encoded
    assert payload["no_runtime_adoption"]
    assert payload["no_final_validation_use"]
    assert "usdc_svb" in payload["scope"]["excluded_estimation_windows"]
    assert payload["scope"]["capacity_scope"].startswith("one system-wide")


def test_preregistration_snapshot_is_immutable(tmp_path: Path) -> None:
    evidence = validate_keeper_execution_compact_evidence()
    source = Path("data/provenance/calibration/keeper/keeper_execution_specification.json")
    path = tmp_path / source.name
    path.write_bytes(source.read_bytes())
    assert path.read_bytes() == source.read_bytes()
    assert evidence["reproducibility"]["preregistration_sha256"] == (
        "5b0ac9d1372dd1306f8dea9490f5acc3ab80e9044f89de059f069acf2789ba7a"
    )


def test_scientific_identity_changes_with_design_not_results() -> None:
    first = validate_keeper_execution_compact_evidence()["specification"]
    second = deepcopy(first)
    second["design"]["bootstrap_replications"] += 1
    assert scientific_identity(first) != scientific_identity(second)


def test_collateral_comparability_is_explicit() -> None:
    frame = collateral_comparability()
    included = frame[
        frame["inclusion_status"].eq("primary_capacity_sample")
    ]
    assert set(included["collateral_identifier"]) == {
        "ETH-A",
        "ETH-B",
        "ETH-C",
        "WBTC-A",
        "WBTC-B",
        "WBTC-C",
    }
    assert frame.loc[
        frame["collateral_identifier"].eq("OTHER_MAKER_COLLATERAL"),
        "exclusion_reason",
    ].str.len().gt(0).all()
    assert included["comparability_classification"].eq(
        "primary_comparable"
    ).all()


def test_full_panel_reconciles_system_and_excludes_usdc_svb() -> None:
    evidence = validate_keeper_execution_compact_evidence()
    panel = evidence["panel"]
    system = [
        row for row in panel
        if row["sample_identifier"] in {
            "window=terra_cefi;scope=SYSTEM_ALL",
            "window=quiet_mature;scope=SYSTEM_ALL",
        }
    ]
    assert sum(int(row["observation_count"]) for row in system) == 1_800
    assert not any("usdc" in row["sample_identifier"].lower() for row in panel)
    assert {
        "observation_count",
        "closure_mean",
        "debt_throughput_mean",
        "active_liquidator_mean",
        "missing_newly_unsafe_share",
        "missing_gas_cost_share",
        "source_checksum",
    }.issubset(evidence["panel_columns"])
    terra = next(row for row in system if "terra_cefi" in row["sample_identifier"])
    assert round(float(terra["closure_mean"]) * int(terra["observation_count"])) == 649


def test_capacity_hierarchy_and_composition_are_reported() -> None:
    evidence = validate_keeper_execution_compact_evidence()
    frontier = evidence["frontier"]
    decision = evidence["decision"]["capacity"]
    assert decision["classification"] in {
        "shared_effective_capacity_frontier_identified",
        "shared_capacity_partially_identified",
        "shared_capacity_not_identified_use_sensitivity",
    }
    assert decision["composition_classification"] in {
        "composition_stable",
        "composition_sensitive_shared_capacity",
        "composition_unresolved",
    }
    assert decision["profiles"]["low"] <= decision["profiles"]["central"]
    assert decision["profiles"]["central"] <= decision["profiles"]["high"]
    assert not decision["physical_maximum_claim"]
    assert {
        "frontier",
        "calendar_block_p90",
        "composition",
    }.issubset({row["row_type"] for row in frontier})
    assert decision["capacity_scale"] == "direct_system_count"
    assert decision["composition_classification"] == "composition_unresolved"
    assert decision["composition_estimates"]["mixed_collateral"]["hours"] == 19
    assert decision["composition_estimates"][
        "single_collateral_dominant"
    ]["hours"] == 4
    assert decision["demand_categories"][
        "category_b_plausibly_high_demand_hours"
    ] == decision["high_demand_hours"]


def test_profit_hurdle_uses_clean_calibration_opportunities_only() -> None:
    evidence = validate_keeper_execution_compact_evidence()
    decision = evidence["decision"]["profit_hurdle"]
    specification = evidence["specification"]
    assert decision["eligible_successful_opportunities"] == 1_064
    assert specification["no_final_validation_use"]
    assert "usdc_svb" in specification["scope"]["excluded_estimation_windows"]
    assert decision["direct_cost_only_hurdle"] == 0
    assert decision["classification"] in {
        "profit_hurdle_estimated",
        "profit_hurdle_partially_identified",
        "profit_hurdle_not_identified",
    }
    assert (
        decision["genuinely_negative_or_rejected_evidence_count"] == 0
    )


def test_profit_hurdle_level2_is_not_a_rejection_estimate() -> None:
    frame = pd.DataFrame(
        {
            "estimation_eligible": [True] * 60,
            "direct_profit_dai": list(range(1, 61)),
            "direct_profit_margin": [value / 1_000 for value in range(1, 61)],
            "gas_share_of_gross_reward": [0.1] * 60,
            "debt_to_gas_cost_turnover": [10.0] * 60,
            "genuinely_negative_or_rejected_evidence": [False] * 60,
        }
    )
    decision = estimate_profit_hurdle(
        frame, KeeperExecutionDesign(bootstrap_replications=20)
    )
    assert decision["classification"] == "profit_hurdle_partially_identified"
    assert decision["risk_cost_rate_profiles"]["direct_cost_only"] == 0
    assert decision["risk_cost_rate_profiles"]["keeper_hurdle_low"] > 0
    assert decision["risk_cost_rate_profiles"]["keeper_hurdle_high"] > (
        decision["risk_cost_rate_profiles"]["keeper_hurdle_low"]
    )


def test_mixed_collateral_smoke_applies_one_global_cap() -> None:
    smoke = mixed_collateral_smoke(2, 0.0)
    assert smoke["global_capacity_respected"]
    assert smoke["global_executed_count"] == 2
    assert smoke["capacity_not_duplicated_by_collateral"]
    assert smoke["cross_collateral_ranking_observed"]
    assert smoke["unresolved_opportunities_preserved"] == 2
    assert smoke["hurdle_reasons"]["11"] == "unprofitable"
    assert smoke["hurdle_reasons"]["12"] == "profitable"


def test_typed_registry_resolver_is_explicit_and_non_adopted(
    tmp_path: Path,
) -> None:
    path = tmp_path / "keeper.yaml"
    payload = {
        "schema_version": 1,
        "runtime_adopted": False,
        "capacity_identification_classification": (
            "shared_capacity_partially_identified"
        ),
        "composition_status": "composition_unresolved",
        "population_mapping_status": "direct_system_count",
        "hurdle_identification_status": (
            "profit_hurdle_partially_identified"
        ),
        "system_wide_status": "shared_across_all_collateral_types",
        "included_collateral_types": list(
            ("ETH-A", "ETH-B", "ETH-C", "WBTC-A", "WBTC-B", "WBTC-C")
        ),
        "source_sample": ["terra_cefi", "quiet_mature"],
        "source_evidence_checksums": {
            "keeper_execution_specification.json": "a" * 64
        },
        "direct_gas_treatment": "transaction_gas_cost_usd_subtracted",
        "profitability_equation_checksum": "b" * 64,
        "parameter_source": "empirical_candidate_registry",
        "shared_capacity_profiles": {
            "shared_keeper_capacity_low": {
                "maximum_liquidations_per_step": 5
            },
            "shared_keeper_capacity_central": {
                "maximum_liquidations_per_step": 20
            },
            "shared_keeper_capacity_high": {
                "maximum_liquidations_per_step": 40
            },
        },
        "profit_hurdle_profiles": {
            "direct_cost_only": {"risk_cost_rate": 0.0},
        },
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    candidate = resolve_keeper_execution_candidate(
        "shared_keeper_capacity_central",
        "direct_cost_only",
        registry_path=path,
    )
    assert candidate.maximum_liquidations_per_step == 20
    assert candidate.risk_cost_rate == 0
    assert candidate.population_mapping_status == "direct_system_count"
    assert candidate.source_checksum == "a" * 64
    assert not candidate.runtime_adopted


def test_resolver_rejects_extra_capacity_profiles(tmp_path: Path) -> None:
    path = tmp_path / "keeper.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "runtime_adopted": False,
                "capacity_identification_classification": (
                    "shared_capacity_partially_identified"
                ),
                "composition_status": "composition_unresolved",
                "population_mapping_status": "direct_system_count",
                "hurdle_identification_status": (
                    "profit_hurdle_partially_identified"
                ),
                "system_wide_status": "shared_across_all_collateral_types",
                "included_collateral_types": list(
                    (
                        "ETH-A",
                        "ETH-B",
                        "ETH-C",
                        "WBTC-A",
                        "WBTC-B",
                        "WBTC-C",
                    )
                ),
                "source_sample": ["terra_cefi", "quiet_mature"],
                "source_evidence_checksums": {
                    "keeper_execution_specification.json": "a" * 64
                },
                "direct_gas_treatment": (
                    "transaction_gas_cost_usd_subtracted"
                ),
                "profitability_equation_checksum": "b" * 64,
                "parameter_source": "empirical_candidate_registry",
                "shared_capacity_profiles": {
                    "shared_keeper_capacity_low": {
                        "maximum_liquidations_per_step": 5
                    },
                    "shared_keeper_capacity_central": {
                        "maximum_liquidations_per_step": 20
                    },
                    "shared_keeper_capacity_high": {
                        "maximum_liquidations_per_step": 40
                    },
                    "eth_keeper_capacity": {
                        "maximum_liquidations_per_step": 10
                    },
                },
                "profit_hurdle_profiles": {
                    "direct_cost_only": {
                        "risk_cost_rate": 0.0
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exactly"):
        resolve_keeper_execution_candidate(
            "shared_keeper_capacity_central",
            "direct_cost_only",
            registry_path=path,
        )
