"""Tests for the non-adopted keeper-execution calibration."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from dai_sim.calibration.keeper_execution import (
    KeeperExecutionDesign,
    audit_runtime_semantics,
    build_hourly_panel,
    build_profit_opportunities,
    collateral_comparability,
    estimate_capacity,
    estimate_profit_hurdle,
    mixed_collateral_smoke,
    nearest_rank,
    preregistration_payload,
    scientific_identity,
    write_preregistration,
)
from dai_sim.inputs.keeper_execution import resolve_keeper_execution_candidate


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
    payload = preregistration_payload(
        KeeperExecutionDesign(bootstrap_replications=20)
    )
    encoded = json.dumps(payload, sort_keys=True)
    assert "candidate_value" not in encoded
    assert payload["no_runtime_adoption"]
    assert payload["no_final_validation_use"]
    assert "usdc_svb" in payload["scope"]["excluded_estimation_windows"]
    assert payload["scope"]["capacity_scope"].startswith("one system-wide")


def test_preregistration_snapshot_is_immutable(tmp_path: Path) -> None:
    design = KeeperExecutionDesign(bootstrap_replications=20)
    path = write_preregistration(tmp_path, design)
    first = path.read_bytes()
    assert write_preregistration(tmp_path, design).read_bytes() == first
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="immutable"):
        write_preregistration(tmp_path, design)


def test_scientific_identity_changes_with_design_not_results() -> None:
    first = preregistration_payload(
        KeeperExecutionDesign(bootstrap_replications=20)
    )
    second = preregistration_payload(
        KeeperExecutionDesign(bootstrap_replications=21)
    )
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
    panel, thresholds = build_hourly_panel()
    system = panel[panel["is_system_aggregate"]]
    assert set(panel["source_window"]) == {"terra_cefi", "quiet_mature"}
    assert len(system) == 1_800
    assert not panel["timestamp_utc"].between(
        "2023-03-06", "2023-03-20", inclusive="left"
    ).any()
    assert thresholds["threshold_sample_hours"] > 20_000
    assert {
        "observed_liquidation_arrivals",
        "observed_protocol_closures",
        "observed_successful_takes",
        "completed_debt_dai",
        "completed_collateral_value_usd",
        "unique_liquidator_count",
        "eth_return_24h",
        "market_return_24h",
        "realised_volatility_24h",
        "liquidation_ratio",
        "gas_stress",
        "market_stress",
        "data_quality_flags",
    }.issubset(panel.columns)
    assert (
        system.loc[
            system["source_window"].eq("terra_cefi"),
            "successful_protocol_closures",
        ].sum()
        == 649
    )


def test_capacity_hierarchy_and_composition_are_reported() -> None:
    panel, _ = build_hourly_panel()
    frontier, decision = estimate_capacity(
        panel, KeeperExecutionDesign(bootstrap_replications=20)
    )
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
    }.issubset(set(frontier["row_type"]))
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
    opportunities = build_profit_opportunities()
    decision = estimate_profit_hurdle(
        opportunities, KeeperExecutionDesign(bootstrap_replications=20)
    )
    eligible = opportunities[opportunities["estimation_eligible"]]
    assert len(eligible) > 50
    assert eligible["model_mappable"].all()
    assert not eligible["is_validation"].any()
    assert not eligible["excluded_usdc_svb"].any()
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
