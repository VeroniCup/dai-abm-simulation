"""Integration gates for the frozen final multi-collateral input contract."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pytest

from dai_sim.validation import multicollateral as validation
from dai_sim.inputs.multicollateral import (
    FAMILY_ORDER,
    PORTFOLIO_ORDER,
    SHOCK_ORDER,
    load_final_collateral_registry,
    load_final_market_pool,
    load_final_portfolio_registry,
    load_final_shock_registry,
)


@pytest.fixture(scope="module")
def design_payloads() -> tuple[dict[str, Any], ...]:
    """Load the four immutable design documents once per test module."""
    return validation._design_payloads()


@pytest.fixture(scope="module")
def market_pool() -> pd.DataFrame:
    """Load the frozen clean multi-collateral market owner."""
    return load_final_market_pool()


@pytest.fixture(scope="module")
def resolved_shocks(
    design_payloads: tuple[dict[str, Any], ...],
    market_pool: pd.DataFrame,
) -> tuple[pd.DataFrame, Mapping[str, Any]]:
    """Resolve empirical tails once without using model outcomes."""
    return validation.shock_registry_frame(design_payloads[2], market_pool)


@pytest.fixture(scope="module")
def shared_capacity(
    design_payloads: tuple[dict[str, Any], ...],
) -> validation.SharedCapacityValidation:
    """Run the six transparent shared-capacity smokes once."""
    return validation.run_shared_capacity_validation(design_payloads[0])


def test_final_collateral_registry_has_exact_empirical_and_proxy_owners() -> None:
    registry = load_final_collateral_registry()

    assert registry.family_order == FAMILY_ORDER
    assert tuple(registry.by_family) == FAMILY_ORDER
    assert tuple(
        item.identifier for item in registry.by_family["ETH"].exact_ilks
    ) == ("ETH-A", "ETH-B", "ETH-C")
    assert tuple(
        item.identifier for item in registry.by_family["WBTC"].exact_ilks
    ) == ("WBTC-A", "WBTC-B", "WBTC-C")
    stable = registry.by_family["STABLE"]
    assert stable.evidence_status == "counterfactual_stable_proxy"
    assert stable.exact_ilks == ()
    assert stable.initialisation["empirical_pool_used"] is False
    assert not registry.runtime_adopted


def test_exact_ilk_protocol_values_are_frozen_without_family_substitution() -> None:
    registry = load_final_collateral_registry()
    observed = {
        ilk.identifier: (
            ilk.liquidation_ratio,
            ilk.liquidation_penalty_rate,
            ilk.debt_ceiling_dai,
            ilk.minimum_debt_dai,
        )
        for family in ("ETH", "WBTC")
        for ilk in registry.by_family[family].exact_ilks
    }

    assert observed == {
        "ETH-A": (
            Decimal("1.45"),
            Decimal("0.13"),
            Decimal("428458674.3748652"),
            Decimal("7500.0"),
        ),
        "ETH-B": (
            Decimal("1.30"),
            Decimal("0.13"),
            Decimal("100404308.53013456"),
            Decimal("25000.0"),
        ),
        "ETH-C": (
            Decimal("1.70"),
            Decimal("0.13"),
            Decimal("549279584.9871001"),
            Decimal("3500.0"),
        ),
        "WBTC-A": (
            Decimal("1.45"),
            Decimal("0.13"),
            Decimal("53422807.487565525"),
            Decimal("7500.0"),
        ),
        "WBTC-B": (
            Decimal("1.30"),
            Decimal("0.13"),
            Decimal("31500670.72061268"),
            Decimal("25000.0"),
        ),
        "WBTC-C": (
            Decimal("1.75"),
            Decimal("0.13"),
            Decimal("55114489.672565565"),
            Decimal("3500.0"),
        ),
    }


@pytest.mark.parametrize(
    ("portfolio_id", "shares", "counts"),
    (
        ("eth_only", (1.0, 0.0, 0.0), (500, 0, 0)),
        (
            "empirical_crypto",
            (0.8483941126796408, 0.1516058873203592, 0.0),
            (424, 76, 0),
        ),
        ("balanced_crypto", (0.5, 0.5, 0.0), (250, 250, 0)),
        (
            "stable_supported",
            (0.6362955845097307, 0.11370441549026941, 0.25),
            (318, 57, 125),
        ),
        (
            "stable_heavy",
            (0.4241970563398204, 0.0758029436601796, 0.5),
            (212, 38, 250),
        ),
    ),
)
def test_five_portfolios_have_exact_shares_and_largest_remainder_counts(
    portfolio_id: str,
    shares: tuple[float, float, float],
    counts: tuple[int, int, int],
) -> None:
    registry = load_final_portfolio_registry()
    portfolio = registry.by_identifier[portfolio_id]

    assert tuple(float(portfolio.target_debt_shares[name]) for name in FAMILY_ORDER) == (
        shares
    )
    assert tuple(portfolio.expected_vault_counts[name] for name in FAMILY_ORDER) == (
        counts
    )
    assert registry.total_vaults == 500
    assert registry.total_debt_dai == Decimal("2500000.0")
    assert registry.common_system_target_collateral_ratio == Decimal(
        "3.6089387701260205"
    )


@pytest.mark.parametrize("portfolio_id", PORTFOLIO_ORDER)
def test_portfolio_initialisation_is_deterministic_exact_and_safe(
    portfolio_id: str,
    design_payloads: tuple[dict[str, Any], ...],
) -> None:
    collateral, portfolios, _, _ = design_payloads
    first = validation.initialise_portfolio(
        portfolio_id,
        replication=73,
        collateral_payload=collateral,
        portfolio_payload=portfolios,
    )
    replay = validation.initialise_portfolio(
        portfolio_id,
        replication=73,
        collateral_payload=collateral,
        portfolio_payload=portfolios,
    )
    definition = portfolios["portfolios"][portfolio_id]

    assert first.identity == replay.identity
    assert first.family_counts == definition["expected_vault_counts"]
    assert len(first.vaults) == 500
    assert len({vault.vault_id for vault in first.vaults}) == 500
    assert first.sampled["debt_dai"].sum() == pytest.approx(
        2_500_000.0, abs=1e-6
    )
    for family in FAMILY_ORDER:
        realised = first.sampled.loc[
            first.sampled["family"].eq(family), "debt_dai"
        ].sum()
        expected = 2_500_000.0 * float(
            definition["target_debt_shares"][family]
        )
        assert realised == pytest.approx(expected, abs=1e-6)
    assert first.final_system_collateral_ratio == pytest.approx(
        3.6089387701260205, abs=1e-10
    )
    assert first.minimum_liquidation_distance > 0.0
    assert all(
        vault.collateral_ratio(
            {
                "ETH": 2_000.0,
                "BTC": 30_000.0,
                "STABLE": 1.0,
            }
        )
        > vault.liquidation_ratio
        for vault in first.vaults
    )


def test_stable_initialisation_has_no_empirical_or_svb_fallback(
    design_payloads: tuple[dict[str, Any], ...],
) -> None:
    collateral, portfolios, _, _ = design_payloads
    result = validation.initialise_portfolio(
        "stable_heavy",
        replication=19,
        collateral_payload=collateral,
        portfolio_payload=portfolios,
    )
    stable = result.sampled.loc[result.sampled["family"].eq("STABLE")]
    empirical_pool = validation._quiet_empirical_pool(collateral)

    assert len(stable) == 250
    assert stable["source_status"].eq("counterfactual_stable_proxy").all()
    assert stable["exact_ilk"].isna().all()
    assert stable["source_row_id"].str.startswith("counterfactual_stable_").all()
    assert not stable["source_row_id"].isin(empirical_pool["pool_row_id"]).any()
    assert empirical_pool["source_window"].eq(
        "quiet_mature_2024-02-01_2024-03-01"
    ).all()
    assert not empirical_pool["source_window"].str.contains(
        "svb", case=False
    ).any()


def test_seven_shocks_use_result_blind_tails_and_exclude_usdc_svb(
    resolved_shocks: tuple[pd.DataFrame, Mapping[str, Any]],
) -> None:
    frame, metadata = resolved_shocks
    registry = load_final_shock_registry()

    assert tuple(registry.by_identifier) == SHOCK_ORDER
    assert frame.shape == (21, 16)
    assert frame["shock_identifier"].drop_duplicates().tolist() == list(
        SHOCK_ORDER
    )
    assert frame["selection_uses_model_outcomes"].eq(False).all()
    assert frame["usdc_svb_used"].eq(False).all()
    assert frame["final_validation_data_used"].eq(False).all()
    assert metadata["ETH"]["q01_log_return"] < 0.0
    assert metadata["WBTC"]["q01_log_return"] < 0.0
    assert metadata["joint_empirical"]["selection_uses_model_outcomes"] is False
    assert registry.exclusions["usdc_svb"] == {
        "start_utc": "2023-03-06T00:00:00Z",
        "end_exclusive_utc": "2023-03-20T00:00:00Z",
    }


@pytest.mark.parametrize(
    ("shock_id", "shocked_family", "expected_multiplier"),
    (
        ("eth_idiosyncratic_severe", "ETH", None),
        ("wbtc_idiosyncratic_severe", "WBTC", None),
        ("stable_depeg_severe", "STABLE", 0.90),
    ),
)
def test_idiosyncratic_and_stable_shocks_are_price_isolated(
    shock_id: str,
    shocked_family: str,
    expected_multiplier: float | None,
    resolved_shocks: tuple[pd.DataFrame, Mapping[str, Any]],
) -> None:
    frame, _ = resolved_shocks
    selected = frame.loc[frame["shock_identifier"].eq(shock_id)]
    own = selected.loc[selected["family"].eq(shocked_family)].iloc[0]
    others = selected.loc[~selected["family"].eq(shocked_family)]

    assert float(own["price_multiplier_at_trough"]) < 1.0
    if expected_multiplier is not None:
        assert float(own["price_multiplier_at_trough"]) == pytest.approx(
            expected_multiplier
        )
    assert others["price_multiplier_at_trough"].eq(1.0).all()


def test_shared_capacity_is_one_global_budget_with_persistent_backlog(
    shared_capacity: validation.SharedCapacityValidation,
) -> None:
    summary = shared_capacity.summary
    simultaneous = summary.loc[
        summary["smoke_identifier"].isin(
            (
                "eth_wbtc_simultaneous",
                "all_collateral_simultaneous",
                "permuted_all_collateral",
            )
        )
    ]

    assert shared_capacity.classification == "shared_capacity_contract_valid"
    assert len(summary) == 6
    assert summary["capacity_value"].eq(26).all()
    assert summary["total_attempts"].le(26).all()
    assert summary["accounting_validation"].all()
    assert summary["backlog_persistence_validation"].all()
    assert simultaneous["capacity_rejected_opportunities"].gt(0).all()
    assert simultaneous["backlog_tab_dai"].gt(0.0).all()
    assert not summary["duplicate_closure"].any()


def test_shared_capacity_ranking_is_global_and_causes_displacement(
    shared_capacity: validation.SharedCapacityValidation,
) -> None:
    summary = shared_capacity.summary.set_index("smoke_identifier")
    row = summary.loc["all_collateral_simultaneous"]
    trace = shared_capacity.traces.loc[
        shared_capacity.traces["smoke_identifier"].eq(
            "all_collateral_simultaneous"
        )
    ]
    reranked = trace.sort_values(
        ["expected_profit", "debt_at_risk", "vault_id"],
        ascending=[False, False, True],
        kind="mergesort",
    )

    assert trace["vault_id"].tolist() == reranked["vault_id"].tolist()
    assert int(row["unsafe_opportunities"]) == 108
    assert int(row["total_attempts"]) == 26
    assert sum(
        int(row[f"{family}_selected_attempts"]) for family in FAMILY_ORDER
    ) == 26
    assert sum(
        int(row[f"capacity_displacement_{family}_from_other_collateral"])
        for family in FAMILY_ORDER
    ) > 0
    assert all(int(row[f"{family}_selected_attempts"]) > 0 for family in FAMILY_ORDER)


def test_shared_capacity_selection_is_invariant_to_candidate_permutation(
    shared_capacity: validation.SharedCapacityValidation,
) -> None:
    summary = shared_capacity.summary.set_index("smoke_identifier")
    original = summary.loc["all_collateral_simultaneous"]
    permuted = summary.loc["permuted_all_collateral"]

    assert original["selected_vault_ids_checksum"] == (
        permuted["selected_vault_ids_checksum"]
    )
    assert bool(original["permutation_validation"])
    assert bool(permuted["permutation_validation"])


@pytest.mark.parametrize(
    ("volatile_valid", "stable_status", "expected"),
    (
        (True, "empirical", "final_collateral_universe_ready"),
        (
            True,
            "counterfactual_stable_proxy",
            "final_collateral_universe_ready_with_counterfactual_stable",
        ),
        (
            True,
            "blocked",
            "final_collateral_universe_crypto_ready_stable_blocked",
        ),
        (False, "empirical", "final_collateral_universe_invalid"),
    ),
)
def test_collateral_classification_branches(
    volatile_valid: bool,
    stable_status: str,
    expected: str,
) -> None:
    assert validation.classify_collateral_universe(
        volatile_owners_valid=volatile_valid,
        stable_status=stable_status,
    ) == expected


@pytest.mark.parametrize(
    ("valid", "stable_admissible", "expected"),
    (
        (True, True, "final_portfolio_registry_ready"),
        (
            True,
            False,
            "final_portfolio_registry_ready_with_blocked_stable_cases",
        ),
        (False, True, "final_portfolio_registry_invalid"),
    ),
)
def test_portfolio_classification_branches(
    valid: bool,
    stable_admissible: bool,
    expected: str,
) -> None:
    assert validation.classify_portfolio_registry(
        registry_valid=valid,
        stable_admissible=stable_admissible,
    ) == expected


@pytest.mark.parametrize(
    ("valid", "stable_status", "expected"),
    (
        (True, "empirical", "final_shock_registry_ready"),
        (
            True,
            "counterfactual_stable_proxy",
            "final_shock_registry_ready_with_counterfactual_stable_depegs",
        ),
        (False, "empirical", "final_shock_registry_invalid"),
    ),
)
def test_shock_classification_branches(
    valid: bool,
    stable_status: str,
    expected: str,
) -> None:
    assert validation.classify_shock_registry(
        registry_valid=valid,
        stable_status=stable_status,
    ) == expected


@pytest.mark.parametrize(
    ("valid", "blocked", "caveats", "expected"),
    (
        (True, False, False, "shared_capacity_contract_valid"),
        (
            True,
            False,
            True,
            "shared_capacity_contract_valid_with_caveats",
        ),
        (True, True, False, "shared_capacity_contract_blocked"),
        (False, False, False, "shared_capacity_contract_invalid"),
    ),
)
def test_shared_capacity_classification_branches(
    valid: bool,
    blocked: bool,
    caveats: bool,
    expected: str,
) -> None:
    assert validation.classify_shared_capacity(
        contract_valid=valid,
        blocked=blocked,
        caveats=caveats,
    ) == expected


@pytest.mark.parametrize(
    (
        "collateral",
        "portfolio",
        "shock",
        "capacity",
        "ordinary_valid",
        "expected",
    ),
    (
        (
            "final_collateral_universe_ready",
            "final_portfolio_registry_ready",
            "final_shock_registry_ready",
            "shared_capacity_contract_valid",
            True,
            "final_multicollateral_inputs_ready",
        ),
        (
            "final_collateral_universe_ready_with_counterfactual_stable",
            "final_portfolio_registry_ready",
            "final_shock_registry_ready_with_counterfactual_stable_depegs",
            "shared_capacity_contract_valid",
            True,
            "final_multicollateral_inputs_ready_with_caveats",
        ),
        (
            "final_collateral_universe_crypto_ready_stable_blocked",
            "final_portfolio_registry_ready_with_blocked_stable_cases",
            "final_shock_registry_blocked",
            "shared_capacity_contract_valid",
            True,
            "final_multicollateral_inputs_blocked",
        ),
        (
            "final_collateral_universe_ready",
            "final_portfolio_registry_ready",
            "final_shock_registry_invalid",
            "shared_capacity_contract_valid",
            True,
            "final_multicollateral_inputs_invalid",
        ),
    ),
)
def test_overall_classification_branches(
    collateral: str,
    portfolio: str,
    shock: str,
    capacity: str,
    ordinary_valid: bool,
    expected: str,
) -> None:
    assert validation.classify_overall_inputs(
        collateral_classification=collateral,
        portfolio_classification=portfolio,
        shock_classification=shock,
        shared_capacity_classification=capacity,
        ordinary_validation_valid=ordinary_valid,
    ) == expected


def test_one_dynamic_replication_preserves_metadata_and_accounting(
    design_payloads: tuple[dict[str, Any], ...],
    market_pool: pd.DataFrame,
) -> None:
    collateral, portfolios, _, _ = design_payloads
    _, _, stage1 = validation.load_stage1_owners()
    record, hourly_rows = validation._dynamic_replication(
        portfolio_id="stable_supported",
        portfolio_index=PORTFOLIO_ORDER.index("stable_supported"),
        replication=0,
        collateral_payload=collateral,
        portfolio_payload=portfolios,
        vault_pool=validation._quiet_empirical_pool(collateral),
        market_pool=market_pool,
        stage1=stage1,
        valid_market_starts=validation._valid_market_block_starts(market_pool),
    )
    hourly = pd.DataFrame(hourly_rows)

    assert record["vault_count"] == 500
    assert record["initial_total_debt_dai"] == pytest.approx(
        2_500_000.0, abs=1e-6
    )
    assert record["capacity"] == 26
    assert record["maximum_attempts_one_hour"] <= 26
    assert record["capacity_semantics"] == "system_wide_shared_capacity"
    assert record["hurdle_profile_id"] == "direct_cost_only"
    assert record["oracle_delay_steps"] == 0
    assert record["confidence_scenario_id"] == "stage1_only"
    assert record["numerical_valid"]
    assert record["collateral_system_reconciliation"]
    assert record["price_isolation"]
    assert not record["silent_fallback"]
    assert not record["state_invalid"]
    assert not record["duplicate_attempt"]
    assert not record["duplicate_closure"]
    assert record["hourly_reconciliation_failure_count"] == 0
    assert record["maximum_debt_conservation_error"] <= 1e-5
    assert record["maximum_collateral_conservation_error"] <= 1e-5
    assert len(hourly) == 168 * 4
    assert not hourly.duplicated(
        subset=["portfolio", "replication", "step", "family"]
    ).any()
    metrics = (
        "selected_attempts",
        "successful_closures",
        "completed_debt_dai",
        "backlog_tab_dai",
        "active_bad_debt_dai",
        "keeper_profit_dai",
    )
    family = hourly.loc[~hourly["family"].eq("SYSTEM")].groupby("step")[
        list(metrics)
    ].sum()
    system = hourly.loc[hourly["family"].eq("SYSTEM")].set_index("step")[
        list(metrics)
    ]
    assert np.allclose(
        family.to_numpy(dtype=float),
        system.to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-8,
    )


def test_compact_evidence_validates_when_generated() -> None:
    if not all(
        (validation.EVIDENCE_DIR / name).is_file()
        for name in validation.COMPACT_FILENAMES
    ):
        pytest.skip("Compact integration evidence has not been generated yet.")

    result = validation.validate_compact_evidence()
    assert result["overall_classification"] == (
        "final_multicollateral_inputs_ready_with_caveats"
    )
