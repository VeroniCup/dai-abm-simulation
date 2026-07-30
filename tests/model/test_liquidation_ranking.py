"""Tests for additive mixed-collateral liquidation candidate ranking."""

from __future__ import annotations

import pandas as pd
import pytest

from dai_sim.model.collateral import (
    CollateralConfig,
    CollateralPortfolioConfig,
)
from dai_sim.model.liquidation import (
    LiquidationConfig,
    rank_liquidation_candidates,
)
from dai_sim.model.vault import Vault, vaults_to_dataframe


def _vault(
    vault_id: int,
    collateral_type: str,
    debt_dai: float,
    *,
    exact_ilk: str | None = None,
) -> Vault:
    return Vault(
        vault_id=vault_id,
        owner_id=vault_id,
        collateral_amount=0.5,
        debt_dai=debt_dai,
        liquidation_ratio=1.5,
        collateral_type=collateral_type,
        exact_ilk=exact_ilk,
    )


def _portfolio() -> CollateralPortfolioConfig:
    return CollateralPortfolioConfig(
        name="ranking_test",
        collaterals=(
            CollateralConfig(
                name="ETH",
                initial_price=1_000.0,
                liquidation_ratio=1.5,
                liquidation_penalty=0.10,
                target_debt_share=0.4,
                max_close_factor=1.0,
            ),
            CollateralConfig(
                name="BTC",
                initial_price=1_000.0,
                liquidation_ratio=1.5,
                liquidation_penalty=0.05,
                target_debt_share=0.4,
                max_close_factor=1.0,
            ),
            CollateralConfig(
                name="STABLE",
                initial_price=1.0,
                liquidation_ratio=1.1,
                liquidation_penalty=0.10,
                target_debt_share=0.2,
                max_close_factor=1.0,
            ),
        ),
    )


def test_exact_ilk_is_optional_normalised_metadata_in_vault_frame() -> None:
    with_ilk = _vault(1, "btc", 1_000.0, exact_ilk=" wbtc-b ")
    without_ilk = _vault(2, "eth", 1_000.0)

    assert with_ilk.collateral_type == "BTC"
    assert with_ilk.exact_ilk == "WBTC-B"
    assert without_ilk.exact_ilk is None

    frame = vaults_to_dataframe(
        [with_ilk, without_ilk],
        prices={"BTC": 1_000.0, "ETH": 1_000.0},
    )
    assert frame["exact_ilk"].tolist() == ["WBTC-B", None]


def test_blank_exact_ilk_is_rejected_without_changing_default() -> None:
    with pytest.raises(ValueError, match="exact_ilk must not be empty"):
        _vault(1, "ETH", 1_000.0, exact_ilk="  ")

    assert _vault(2, "ETH", 1_000.0).exact_ilk is None


def test_global_ranking_uses_profit_debt_and_vault_id_tie_breaks() -> None:
    vaults = [
        _vault(7, "ETH", 1_000.0, exact_ilk="ETH-A"),
        _vault(9, "BTC", 2_000.0, exact_ilk="WBTC-A"),
        _vault(3, "STABLE", 1_000.0, exact_ilk="USDC-A"),
    ]

    ranked = rank_liquidation_candidates(
        vaults,
        prices={"ETH": 1_000.0, "BTC": 1_000.0, "STABLE": 1.0},
        config=LiquidationConfig(gas_cost=0.0),
        portfolio=_portfolio(),
    )

    assert ranked["vault_id"].tolist() == [9, 3, 7]
    assert ranked["candidate_rank"].tolist() == [1, 2, 3]
    assert ranked["expected_profit"].tolist() == pytest.approx(
        [100.0, 100.0, 100.0]
    )
    assert ranked["debt_at_risk"].tolist() == [2_000.0, 1_000.0, 1_000.0]
    assert ranked["collateral_type"].tolist() == ["BTC", "STABLE", "ETH"]


def test_global_ranking_is_invariant_to_collateral_input_order() -> None:
    vaults = [
        _vault(8, "ETH", 1_000.0),
        _vault(4, "BTC", 2_000.0),
        _vault(2, "STABLE", 1_000.0),
    ]
    kwargs = {
        "prices": {"ETH": 1_000.0, "BTC": 1_000.0, "STABLE": 1.0},
        "config": LiquidationConfig(gas_cost=0.0),
        "portfolio": _portfolio(),
    }

    first = rank_liquidation_candidates(vaults, **kwargs)
    second = rank_liquidation_candidates(list(reversed(vaults)), **kwargs)
    pd.testing.assert_frame_equal(first, second)


def test_ranking_without_prices_treats_inputs_as_preselected_candidates() -> None:
    ranked = rank_liquidation_candidates(
        [_vault(2, "BTC", 2_000.0), _vault(1, "ETH", 1_000.0)],
        config=LiquidationConfig(
            liquidation_penalty=0.10,
            gas_cost=10.0,
            max_close_factor=0.5,
        ),
    )

    assert ranked["vault_id"].tolist() == [2, 1]
    assert ranked["debt_subject_to_close_factor"].tolist() == [
        1_000.0,
        500.0,
    ]
    assert ranked["expected_profit"].tolist() == pytest.approx([90.0, 40.0])
    assert ranked["is_liquidatable"].isna().all()


def test_ranking_rejects_duplicate_vault_identifiers() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        rank_liquidation_candidates(
            [_vault(1, "ETH", 1_000.0), _vault(1, "BTC", 2_000.0)]
        )
