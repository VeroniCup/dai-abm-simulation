"""
vault.py

Vault mechanics for the simplified collateral-backed DAI simulation.

A vault represents a collateralised debt position:
- the owner locks one collateral asset;
- the owner mints/borrows DAI as debt;
- the vault becomes liquidatable if its collateral ratio falls below
  the liquidation ratio.

This module intentionally starts simple. It does not model the full MakerDAO
protocol. The goal is to create transparent vault-level mechanics for stress
testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .collateral import (
    CollateralPortfolioConfig,
    normalise_collateral_prices,
    validate_price_map_for_portfolio,
)


@dataclass
class Vault:
    """
    A simplified collateral-backed DAI vault.

    Attributes
    ----------
    vault_id:
        Unique identifier of the vault.
    owner_id:
        Identifier of the vault owner.
    collateral_amount:
        Amount of the collateral asset locked in the vault.
    debt_dai:
        Amount of DAI debt minted/borrowed.
    liquidation_ratio:
        Minimum collateral ratio required before liquidation.
        Example: 1.5 means 150%.
    collateral_type:
        Identifier of the single collateral asset held by the vault.
    is_active:
        Whether the vault is still active.
    is_liquidated:
        Whether the vault has been liquidated.
    """

    vault_id: int
    owner_id: int
    collateral_amount: float
    debt_dai: float
    liquidation_ratio: float = 1.5
    collateral_type: str = "ETH"
    is_active: bool = True
    is_liquidated: bool = False

    def __post_init__(self) -> None:
        """Normalise the collateral identifier and validate the vault."""
        self.collateral_type = str(self.collateral_type).strip().upper()
        self.validate()

    def validate(self) -> None:
        """Validate vault values."""
        if not self.collateral_type:
            raise ValueError("collateral_type must not be empty.")
        if self.collateral_amount < 0:
            raise ValueError("collateral_amount cannot be negative.")
        if self.debt_dai < 0:
            raise ValueError("debt_dai cannot be negative.")
        if self.liquidation_ratio <= 1:
            raise ValueError("liquidation_ratio should be greater than 1.")

    def collateral_value(self, prices: float | dict[str, float]) -> float:
        """
        Calculate the USD value of the vault's collateral.

        Scalar prices are interpreted as ETH prices for backward compatibility.
        """
        price_map = normalise_collateral_prices(prices)

        if self.collateral_type not in price_map:
            raise ValueError(
                f"Missing price for collateral type '{self.collateral_type}'."
            )

        collateral_price = price_map[self.collateral_type]
        return self.collateral_amount * collateral_price

    def collateral_ratio(self, prices: float | dict[str, float]) -> float:
        """
        Calculate the collateral ratio.

        Collateral ratio = collateral value / debt.

        If debt is zero, the vault has no liquidation risk, so we return infinity.

        Parameters
        ----------
        prices:
            Scalar ETH price or collateral price map.

        Returns
        -------
        float
            Collateral ratio.
        """
        if self.debt_dai == 0:
            return float("inf")

        return self.collateral_value(prices) / self.debt_dai

    def is_liquidatable(self, prices: float | dict[str, float]) -> bool:
        """
        Check whether the vault is eligible for liquidation.

        Parameters
        ----------
        prices:
            Scalar ETH price or collateral price map.

        Returns
        -------
        bool
            True if active vault collateral ratio is below liquidation ratio.
        """
        if not self.is_active:
            return False

        return self.collateral_ratio(prices) < self.liquidation_ratio

    def bad_debt(self, prices: float | dict[str, float]) -> float:
        """
        Calculate bad debt amount.

        Bad debt exists when debt exceeds collateral value.

        Parameters
        ----------
        prices:
            Scalar ETH price or collateral price map.

        Returns
        -------
        float
            Bad debt amount in DAI/USD terms.
        """
        return max(self.debt_dai - self.collateral_value(prices), 0.0)

    def add_collateral(self, amount: float) -> None:
        """
        Add collateral to the vault.

        Parameters
        ----------
        amount:
            Amount of the vault's collateral asset to add.
        """
        if amount < 0:
            raise ValueError("amount cannot be negative.")

        self.collateral_amount += amount

    def repay_debt(self, amount_dai: float) -> float:
        """
        Repay part or all of the DAI debt.

        Parameters
        ----------
        amount_dai:
            Amount of DAI to repay.

        Returns
        -------
        float
            Actual amount repaid.
        """
        if amount_dai < 0:
            raise ValueError("amount_dai cannot be negative.")

        actual_repayment = min(amount_dai, self.debt_dai)
        self.debt_dai -= actual_repayment
        return actual_repayment

    def mint_dai(
        self,
        amount_dai: float,
        prices: float | dict[str, float],
    ) -> bool:
        """
        Try to mint additional DAI.

        The mint succeeds only if the vault remains above the liquidation ratio
        after minting.

        Parameters
        ----------
        amount_dai:
            Amount of DAI to mint.
        prices:
            Scalar ETH price or collateral price map.

        Returns
        -------
        bool
            True if minting succeeds, False otherwise.
        """
        if amount_dai < 0:
            raise ValueError("amount_dai cannot be negative.")

        old_debt = self.debt_dai
        self.debt_dai += amount_dai

        if self.collateral_ratio(prices) < self.liquidation_ratio:
            self.debt_dai = old_debt
            return False

        return True

    def liquidate(self, prices: float | dict[str, float]) -> dict:
        """
        Liquidate the vault.

        This simplified liquidation closes the vault and records collateral value,
        debt, and bad debt. Keeper profit is handled separately in liquidation.py.

        Parameters
        ----------
        prices:
            Scalar ETH price or collateral price map.

        Returns
        -------
        dict
            Liquidation summary.
        """
        if not self.is_active:
            return {
                "vault_id": self.vault_id,
                "liquidated": False,
                "reason": "inactive",
                "collateral_value": 0.0,
                "debt_dai": 0.0,
                "bad_debt": 0.0,
            }

        collateral_value = self.collateral_value(prices)
        debt = self.debt_dai
        bad_debt = self.bad_debt(prices)

        self.is_active = False
        self.is_liquidated = True
        self.collateral_amount = 0.0
        self.debt_dai = 0.0

        return {
            "vault_id": self.vault_id,
            "liquidated": True,
            "reason": "liquidated",
            "collateral_value": collateral_value,
            "debt_dai": debt,
            "bad_debt": bad_debt,
        }

    def partial_liquidate(
        self,
        prices: float | dict[str, float],
        debt_repaid: float,
        liquidation_penalty: float = 0.13,
    ) -> dict:
        """
        Partially liquidate the vault.

        The keeper repays part of the vault's DAI debt and receives collateral
        worth debt_repaid * (1 + liquidation_penalty), if enough collateral exists.

        If partial liquidation would worsen bad debt, the vault is treated as
        terminally liquidated. This prevents the model from leaving a worse
        undercollateralised active vault after liquidation.
        """
        if not self.is_active:
            return {
                "vault_id": self.vault_id,
                "liquidated": False,
                "fully_liquidated": False,
                "reason": "inactive",
                "collateral_value_removed": 0.0,
                "collateral_amount_removed": 0.0,
                "debt_repaid": 0.0,
                "remaining_debt": self.debt_dai,
                "remaining_collateral_amount": self.collateral_amount,
                "bad_debt": 0.0,
            }

        price_map = normalise_collateral_prices(prices)

        if self.collateral_type not in price_map:
            raise ValueError(
                f"Missing price for collateral type '{self.collateral_type}'."
            )

        collateral_price = price_map[self.collateral_type]

        if debt_repaid <= 0:
            raise ValueError("debt_repaid must be positive.")
        if liquidation_penalty < 0:
            raise ValueError("liquidation_penalty cannot be negative.")

        bad_debt_before = self.bad_debt(prices)

        original_debt = self.debt_dai
        original_collateral_amount = self.collateral_amount
        original_collateral_value = original_collateral_amount * collateral_price

        actual_debt_repaid = min(debt_repaid, original_debt)

        target_collateral_value_removed = actual_debt_repaid * (
                1.0 + liquidation_penalty
        )

        collateral_value_removed = min(
            target_collateral_value_removed,
            original_collateral_value,
        )
        collateral_amount_removed = collateral_value_removed / collateral_price

        self.debt_dai -= actual_debt_repaid
        self.collateral_amount -= collateral_amount_removed

        bad_debt_after = self.bad_debt(prices)

        fully_liquidated = (
                self.debt_dai <= 1e-9
                or self.collateral_amount <= 1e-9
                or bad_debt_after > bad_debt_before
        )

        bad_debt_realised = bad_debt_after if fully_liquidated else bad_debt_after

        if fully_liquidated:
            self.debt_dai = 0.0
            self.collateral_amount = 0.0
            self.is_active = False
            self.is_liquidated = True

        return {
            "vault_id": self.vault_id,
            "liquidated": True,
            "fully_liquidated": fully_liquidated,
            "reason": "partial_liquidation",
            "collateral_value_removed": collateral_value_removed,
            "collateral_amount_removed": collateral_amount_removed,
            "debt_repaid": actual_debt_repaid,
            "remaining_debt": self.debt_dai,
            "remaining_collateral_amount": self.collateral_amount,
            "bad_debt": bad_debt_realised,
        }

def create_vault_from_target_cr(
    vault_id: int,
    owner_id: int,
    debt_dai: float,
    target_collateral_ratio: float,
    prices: float | dict[str, float],
    liquidation_ratio: float = 1.5,
    collateral_type: str = "ETH",
) -> Vault:
    """
    Create a vault with a target initial collateral ratio.

    This is useful for generating synthetic vault populations.

    Example:
    If debt_dai = 1000, collateral price = 2000, target CR = 2.0,
    required collateral value = 2000 USD,
    required collateral amount = 1 unit.

    Parameters
    ----------
    vault_id:
        Unique vault ID.
    owner_id:
        Owner ID.
    debt_dai:
        Initial DAI debt.
    target_collateral_ratio:
        Desired initial collateral ratio.
    prices:
        Scalar ETH price or collateral price map.
    liquidation_ratio:
        Liquidation ratio.
    collateral_type:
        Collateral identifier for the vault.

    Returns
    -------
    Vault
        Created vault.
    """
    if debt_dai <= 0:
        raise ValueError("debt_dai must be positive.")
    if target_collateral_ratio <= liquidation_ratio:
        raise ValueError(
            "target_collateral_ratio should be greater than liquidation_ratio."
        )

    normalised_type = str(collateral_type).strip().upper()
    if not normalised_type:
        raise ValueError("collateral_type must not be empty.")

    price_map = normalise_collateral_prices(prices)
    if normalised_type not in price_map:
        raise ValueError(
            f"Missing price for collateral type '{normalised_type}'."
        )

    collateral_value = debt_dai * target_collateral_ratio
    collateral_amount = collateral_value / price_map[normalised_type]

    vault = Vault(
        vault_id=vault_id,
        owner_id=owner_id,
        collateral_amount=collateral_amount,
        debt_dai=debt_dai,
        liquidation_ratio=liquidation_ratio,
        collateral_type=normalised_type,
    )
    return vault


def generate_random_vaults(
    n_vaults: int,
    prices: float | dict[str, float],
    liquidation_ratio: float = 1.5,
    debt_mean: float = 5_000.0,
    debt_std: float = 1_000.0,
    collateral_ratio_mean: float = 2.0,
    collateral_ratio_std: float = 0.25,
    min_collateral_ratio_buffer: float = 0.05,
    random_seed: Optional[int] = 42,
    collateral_type: str = "ETH",
) -> list[Vault]:
    """
    Generate a synthetic population of vaults.

    Debt is sampled from a normal distribution and clipped to remain positive.
    Collateral ratios are sampled from a normal distribution and clipped so that
    vaults start above the liquidation ratio.

    Parameters
    ----------
    n_vaults:
        Number of vaults to generate.
    prices:
        Scalar ETH price or collateral price map.
    liquidation_ratio:
        Liquidation ratio, e.g. 1.5.
    debt_mean:
        Mean DAI debt.
    debt_std:
        Standard deviation of DAI debt.
    collateral_ratio_mean:
        Mean initial collateral ratio.
    collateral_ratio_std:
        Standard deviation of initial collateral ratio.
    min_collateral_ratio_buffer:
        Minimum buffer above liquidation ratio.
    random_seed:
        Optional random seed.
    collateral_type:
        Collateral identifier assigned to every generated vault.

    Returns
    -------
    list[Vault]
        Generated vaults.
    """
    if n_vaults <= 0:
        raise ValueError("n_vaults must be positive.")

    normalised_type = str(collateral_type).strip().upper()
    price_map = normalise_collateral_prices(prices)
    if normalised_type not in price_map:
        raise ValueError(
            f"Missing price for collateral type '{normalised_type}'."
        )

    debts, collateral_ratios = _sample_vault_characteristics(
        n_vaults=n_vaults,
        liquidation_ratio=liquidation_ratio,
        debt_mean=debt_mean,
        debt_std=debt_std,
        collateral_ratio_mean=collateral_ratio_mean,
        collateral_ratio_std=collateral_ratio_std,
        min_collateral_ratio_buffer=min_collateral_ratio_buffer,
        random_seed=random_seed,
    )

    vaults = [
        create_vault_from_target_cr(
            vault_id=i,
            owner_id=i,
            debt_dai=float(debts[i]),
            target_collateral_ratio=float(collateral_ratios[i]),
            prices=price_map,
            liquidation_ratio=liquidation_ratio,
            collateral_type=normalised_type,
        )
        for i in range(n_vaults)
    ]

    return vaults


def _sample_vault_characteristics(
    n_vaults: int,
    liquidation_ratio: float,
    debt_mean: float,
    debt_std: float,
    collateral_ratio_mean: float,
    collateral_ratio_std: float,
    min_collateral_ratio_buffer: float,
    random_seed: Optional[int],
    clip_to_liquidation_ratio: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample debt and collateral ratios using the existing random sequence."""
    rng = np.random.default_rng(random_seed)

    debts = rng.normal(debt_mean, debt_std, size=n_vaults)
    debts = np.clip(debts, a_min=100.0, a_max=None)

    collateral_ratios = rng.normal(
        collateral_ratio_mean,
        collateral_ratio_std,
        size=n_vaults,
    )

    if clip_to_liquidation_ratio:
        min_cr = liquidation_ratio + min_collateral_ratio_buffer
        collateral_ratios = np.clip(
            collateral_ratios,
            a_min=min_cr,
            a_max=None,
        )

    return debts, collateral_ratios


def _allocate_collateral_types_by_debt(
    debts: np.ndarray,
    portfolio: CollateralPortfolioConfig,
) -> list[str]:
    """Assign sampled vault debts to collateral types near target debt shares."""
    positive_collaterals = tuple(
        collateral
        for collateral in portfolio.collaterals
        if collateral.target_debt_share > 0
    )
    total_debt = float(debts.sum())
    target_debt = {
        collateral.name: total_debt * collateral.target_debt_share
        for collateral in positive_collaterals
    }
    assigned_debt = {
        collateral.name: 0.0
        for collateral in positive_collaterals
    }
    assignments = [""] * len(debts)

    # Allocate the largest sampled positions first. At each assignment, the
    # collateral type with the largest remaining debt deficit is selected.
    # Vault identifiers and sampled values retain their original order.
    ordered_indices = sorted(
        range(len(debts)),
        key=lambda index: (-float(debts[index]), index),
    )

    for index in ordered_indices:
        collateral = max(
            positive_collaterals,
            key=lambda item: target_debt[item.name] - assigned_debt[item.name],
        )
        assignments[index] = collateral.name
        assigned_debt[collateral.name] += float(debts[index])

    return assignments


def generate_portfolio_vaults(
    n_vaults: int,
    prices: float | dict[str, float],
    portfolio: CollateralPortfolioConfig,
    liquidation_ratio: float = 1.5,
    debt_mean: float = 5_000.0,
    debt_std: float = 1_000.0,
    collateral_ratio_mean: float = 2.0,
    collateral_ratio_std: float = 0.25,
    min_collateral_ratio_buffer: float = 0.05,
    random_seed: Optional[int] = 42,
) -> list[Vault]:
    """
    Generate one-asset vaults allocated by portfolio target debt shares.

    Debt and collateral ratios use the existing sampling process. Collateral
    types are then assigned deterministically so that realised system debt
    shares closely follow the supplied portfolio. A collateral-specific
    liquidation ratio takes precedence over the shared ``liquidation_ratio``;
    ``None`` falls back to the shared value.
    """
    if n_vaults <= 0:
        raise ValueError("n_vaults must be positive.")

    price_map = validate_price_map_for_portfolio(prices, portfolio)

    if len(portfolio.collaterals) == 1:
        collateral = portfolio.collaterals[0]
        resolved_liquidation_ratio = (
            liquidation_ratio
            if collateral.liquidation_ratio is None
            else collateral.liquidation_ratio
        )
        return generate_random_vaults(
            n_vaults=n_vaults,
            prices=price_map,
            liquidation_ratio=resolved_liquidation_ratio,
            debt_mean=debt_mean,
            debt_std=debt_std,
            collateral_ratio_mean=collateral_ratio_mean,
            collateral_ratio_std=collateral_ratio_std,
            min_collateral_ratio_buffer=min_collateral_ratio_buffer,
            random_seed=random_seed,
            collateral_type=collateral.name,
        )

    debts, collateral_ratios = _sample_vault_characteristics(
        n_vaults=n_vaults,
        liquidation_ratio=liquidation_ratio,
        debt_mean=debt_mean,
        debt_std=debt_std,
        collateral_ratio_mean=collateral_ratio_mean,
        collateral_ratio_std=collateral_ratio_std,
        min_collateral_ratio_buffer=min_collateral_ratio_buffer,
        random_seed=random_seed,
        clip_to_liquidation_ratio=False,
    )
    collateral_types = _allocate_collateral_types_by_debt(
        debts=debts,
        portfolio=portfolio,
    )

    vaults = []

    for index in range(n_vaults):
        collateral = portfolio.get(collateral_types[index])
        resolved_liquidation_ratio = (
            liquidation_ratio
            if collateral.liquidation_ratio is None
            else collateral.liquidation_ratio
        )
        target_collateral_ratio = max(
            float(collateral_ratios[index]),
            resolved_liquidation_ratio + min_collateral_ratio_buffer,
        )
        vaults.append(
            create_vault_from_target_cr(
                vault_id=index,
                owner_id=index,
                debt_dai=float(debts[index]),
                target_collateral_ratio=target_collateral_ratio,
                prices=price_map,
                liquidation_ratio=resolved_liquidation_ratio,
                collateral_type=collateral.name,
            )
        )

    return vaults


def vaults_to_dataframe(
    vaults: list[Vault],
    prices: float | dict[str, float],
) -> pd.DataFrame:
    """
    Convert a list of vaults to a DataFrame.

    Parameters
    ----------
    vaults:
        List of Vault objects.
    prices:
        Scalar ETH price or collateral price map.

    Returns
    -------
    pd.DataFrame
        Vault-level summary.
    """
    records = []

    for vault in vaults:
        records.append(
            {
                "vault_id": vault.vault_id,
                "owner_id": vault.owner_id,
                "collateral_type": vault.collateral_type,
                "collateral_amount": vault.collateral_amount,
                "collateral_value": vault.collateral_value(prices),
                "debt_dai": vault.debt_dai,
                "collateral_ratio": vault.collateral_ratio(prices),
                "liquidation_ratio": vault.liquidation_ratio,
                "is_active": vault.is_active,
                "is_liquidated": vault.is_liquidated,
                "is_liquidatable": vault.is_liquidatable(prices),
                "bad_debt": vault.bad_debt(prices),
            }
        )

    return pd.DataFrame(records)


if __name__ == "__main__":
    # Quick smoke test. Run:
    # python src/vault.py

    initial_prices = 2_000.0
    shocked_prices = 1_140.0

    vaults = generate_random_vaults(
        n_vaults=10,
        prices=initial_prices,
        liquidation_ratio=1.5,
        random_seed=42,
    )

    before = vaults_to_dataframe(vaults, prices=initial_prices)
    after = vaults_to_dataframe(vaults, prices=shocked_prices)

    print("Before ETH shock:")
    print(before[["vault_id", "debt_dai", "collateral_ratio", "is_liquidatable"]])

    print("\nAfter ETH shock:")
    print(after[["vault_id", "debt_dai", "collateral_ratio", "is_liquidatable", "bad_debt"]])

    print("\nNumber liquidatable after shock:")
    print(after["is_liquidatable"].sum())
