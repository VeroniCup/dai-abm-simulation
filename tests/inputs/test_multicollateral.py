"""Tests for the dormant final multi-collateral empirical-input freeze."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest

from dai_sim.inputs.multicollateral import (
    FAMILY_ORDER,
    PORTFOLIO_ORDER,
    SHOCK_ORDER,
    build_final_market_pool,
    build_final_market_pool_manifest,
    largest_remainder_counts,
    load_final_collateral_registry,
    load_final_market_pool,
    load_final_portfolio_registry,
    load_final_shock_registry,
    load_integrated_multicollateral_profile,
    resolve_multicollateral_inputs,
)


def test_collateral_registry_preserves_empirical_and_counterfactual_owners() -> None:
    registry = load_final_collateral_registry()
    assert registry.family_order == FAMILY_ORDER
    assert tuple(registry.by_family) == FAMILY_ORDER
    assert not registry.runtime_adopted
    assert tuple(ilk.identifier for ilk in registry.by_family["ETH"].exact_ilks) == (
        "ETH-A",
        "ETH-B",
        "ETH-C",
    )
    assert tuple(ilk.identifier for ilk in registry.by_family["WBTC"].exact_ilks) == (
        "WBTC-A",
        "WBTC-B",
        "WBTC-C",
    )
    stable = registry.by_family["STABLE"]
    assert stable.evidence_status == "counterfactual_stable_proxy"
    assert stable.initialisation["mode"] == "stylised_parametric"
    assert stable.initialisation["empirical_pool_used"] is False
    assert stable.exact_ilks == ()


def test_portfolio_registry_is_exact_and_uses_largest_remainders() -> None:
    registry = load_final_portfolio_registry()
    assert tuple(registry.by_identifier) == PORTFOLIO_ORDER
    assert registry.total_vaults == 500
    expected = (
        (500, 0, 0),
        (424, 76, 0),
        (250, 250, 0),
        (318, 57, 125),
        (212, 38, 250),
    )
    observed = tuple(
        tuple(portfolio.expected_vault_counts[name] for name in FAMILY_ORDER)
        for portfolio in registry.portfolios
    )
    assert observed == expected
    assert registry.common_system_target_collateral_ratio == Decimal(
        "3.6089387701260205"
    )


def test_largest_remainder_ties_follow_explicit_family_order() -> None:
    counts = largest_remainder_counts(
        {
            "ETH": Decimal("0.3333333333333333"),
            "WBTC": Decimal("0.3333333333333333"),
            "STABLE": Decimal("0.3333333333333334"),
        },
        2,
        FAMILY_ORDER,
    )
    assert counts == {"ETH": 1, "WBTC": 0, "STABLE": 1}
    with pytest.raises(ValueError, match="family order"):
        largest_remainder_counts(
            {"WBTC": Decimal("0.5"), "ETH": Decimal("0.5"), "STABLE": Decimal(0)},
            10,
            FAMILY_ORDER,
        )


def test_shock_registry_is_exact_and_result_blind() -> None:
    registry = load_final_shock_registry()
    assert tuple(registry.by_identifier) == SHOCK_ORDER
    assert registry.onset_hour == 24
    assert registry.tail_quantile == Decimal("0.01")
    assert registry.joint_lambda == Decimal("0.5")
    moderate = registry.by_identifier["stable_depeg_moderate"].rules[2]
    severe = registry.by_identifier["stable_depeg_severe"].rules[2]
    assert (moderate.price_floor, moderate.duration_hours) == (Decimal("0.95"), 72)
    assert (severe.price_floor, severe.duration_hours) == (Decimal("0.90"), 168)
    eth_tail = registry.by_identifier["eth_idiosyncratic_severe"].rules[0]
    assert eth_tail.magnitude is None
    assert eth_tail.status == "pending_result_blind_derivation"


def test_integrated_profile_is_dormant_and_fixed() -> None:
    profile = load_integrated_multicollateral_profile()
    assert profile.identifier == "empirical_integrated_multicollateral"
    assert profile.experiment_ready
    assert not profile.runtime_adopted
    assert profile.total_vaults == 500
    assert profile.total_debt_dai == Decimal("2500000.0")
    assert profile.maximum_liquidations_per_step == 26
    assert profile.keeper_capacity_semantics == "system_wide_shared_capacity"
    assert profile.keeper_hurdle_profile_id == "direct_cost_only"
    assert profile.confidence_scenario_id == "stage1_only"
    assert profile.oracle_delay_steps == 0


def test_resolution_is_deterministic_and_rejects_unknown_choices() -> None:
    first = resolve_multicollateral_inputs(
        "stable_supported", "joint_crypto_stable_stress"
    )
    second = resolve_multicollateral_inputs(
        "stable_supported", "joint_crypto_stable_stress"
    )
    assert first.vault_counts == second.vault_counts == {
        "ETH": 318,
        "WBTC": 57,
        "STABLE": 125,
    }
    assert first.shock is not None
    assert first.shock.identifier == "joint_crypto_stable_stress"
    with pytest.raises(ValueError, match="Unknown final portfolio"):
        resolve_multicollateral_inputs("not_registered")
    with pytest.raises(ValueError, match="Unknown final shock"):
        resolve_multicollateral_inputs("eth_only", "not_registered")


def test_profile_registry_checksum_tampering_is_rejected(tmp_path: Path) -> None:
    source = Path("config/profiles/empirical_integrated_multicollateral.yaml")
    text = source.read_text(encoding="utf-8").replace(
        "75268fed6b3db5a80a822a80b8629291491cd73ce62b4c3e6cf3975060b4eb6d",
        "f" * 64,
    )
    path = tmp_path / "profile.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_integrated_multicollateral_profile(path)


def test_final_market_pool_is_deterministic_aligned_and_excludes_validation() -> None:
    first = build_final_market_pool()
    second = build_final_market_pool()
    pd.testing.assert_frame_equal(first, second)
    assert first.shape == (26208, 22)
    timestamps = pd.to_datetime(first["timestamp_utc"], utc=True)
    assert not (
        (timestamps >= "2022-11-01T00:00:00Z")
        & (timestamps < "2022-11-21T00:00:00Z")
    ).any()
    assert not (
        (timestamps >= "2023-03-06T00:00:00Z")
        & (timestamps < "2023-03-20T00:00:00Z")
    ).any()
    assert first["calibration_segment_id"].nunique() == 3
    assert int(first["eth_24h_log_return"].isna().sum()) == 72
    assert int(first["wbtc_24h_log_return"].isna().sum()) == 72
    assert int(first["usdc_24h_log_return"].isna().sum()) == 72
    manifest = build_final_market_pool_manifest(first)
    assert manifest["output_sha256"] == (
        "e97570b94b2140f9a6dc6436b386ba0ea9e91d9de73b755cc38d8e971d91ed2e"
    )


def test_final_market_pool_loader_validates_checksum(tmp_path: Path) -> None:
    frame = build_final_market_pool()
    path = tmp_path / "pool.csv"
    frame.to_csv(path, index=False, lineterminator="\n")
    checksum = sha256(path.read_bytes()).hexdigest()
    loaded = load_final_market_pool(path, checksum)
    pd.testing.assert_frame_equal(loaded, frame, check_dtype=False)
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_final_market_pool(path, "0" * 64)
