"""
vault.py

Vault mechanics for the simplified ETH-backed DAI simulation.

A vault represents an ETH-collateralised debt position:
- the owner locks ETH as collateral;
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

from collateral import normalise_collateral_prices


@dataclass
class Vault:
    """
    A simplified ETH-backed DAI vault.

    Attributes
    ----------
    vault_id:
        Unique identifier of the vault.
    owner_id:
        Identifier of the vault owner.
    collateral_amount:
        Amount of ETH locked in the vault.
    debt_dai:
        Amount of DAI debt minted/borrowed.
    liquidation_ratio:
        Minimum collateral ratio required before liquidation.
        Example: 1.5 means 150%.
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

    def validate(self) -> None:
        """Validate vault values."""
        if self.collateral_amount < 0:
            raise ValueError("collateral_amount cannot be negative.")
        if self.debt_dai < 0:
            raise ValueError("debt_dai cannot be negative.")
        if self.liquidation_ratio <= 1:
            raise ValueError("liquidation_ratio should be greater than 1.")

    def collateral_value(self, prices: float | dict[str, float]) -> float:
        """
        Calculate the USD value of collateral.
        """
        price_map = normalise_collateral_prices(prices)
        collateral_price = price_map[self.collateral_type]
        return self.collateral_amount * collateral_price

    def collateral_ratio(self, prices: float) -> float:
        """
        Calculate the collateral ratio.

        Collateral ratio = collateral value / debt.

        If debt is zero, the vault has no liquidation risk, so we return infinity.

        Parameters
        ----------
        prices:
            ETH price in USD.

        Returns
        -------
        float
            Collateral ratio.
        """
        if self.debt_dai == 0:
            return float("inf")

        return self.collateral_value(prices) / self.debt_dai

    def is_liquidatable(self, prices: float) -> bool:
        """
        Check whether the vault is eligible for liquidation.

        Parameters
        ----------
        prices:
            ETH price in USD.

        Returns
        -------
        bool
            True if active vault collateral ratio is below liquidation ratio.
        """
        if not self.is_active:
            return False

        return self.collateral_ratio(prices) < self.liquidation_ratio

    def bad_debt(self, prices: float) -> float:
        """
        Calculate bad debt amount.

        Bad debt exists when debt exceeds collateral value.

        Parameters
        ----------
        prices:
            ETH price in USD.

        Returns
        -------
        float
            Bad debt amount in DAI/USD terms.
        """
        return max(self.debt_dai - self.collateral_value(prices), 0.0)

    def add_collateral(self, amount: float) -> None:
        """
        Add ETH collateral to the vault.

        Parameters
        ----------
        amount:
            Amount of ETH to add.
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

    def mint_dai(self, amount_dai: float, prices: float) -> bool:
        """
        Try to mint additional DAI.

        The mint succeeds only if the vault remains above the liquidation ratio
        after minting.

        Parameters
        ----------
        amount_dai:
            Amount of DAI to mint.
        prices:
            Current ETH price.

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

    def liquidate(self, prices: float) -> dict:
        """
        Liquidate the vault.

        This simplified liquidation closes the vault and records collateral value,
        debt, and bad debt. Keeper profit is handled separately in liquidation.py.

        Parameters
        ----------
        prices:
            ETH price in USD.

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
            prices: float,
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

        if prices <= 0:
            raise ValueError("prices must be positive.")
        if debt_repaid <= 0:
            raise ValueError("debt_repaid must be positive.")
        if liquidation_penalty < 0:
            raise ValueError("liquidation_penalty cannot be negative.")

        bad_debt_before = self.bad_debt(prices)

        original_debt = self.debt_dai
        original_collateral_amount = self.collateral_amount
        original_collateral_value = original_collateral_amount * prices

        actual_debt_repaid = min(debt_repaid, original_debt)

        target_collateral_value_removed = actual_debt_repaid * (
                1.0 + liquidation_penalty
        )

        collateral_value_removed = min(
            target_collateral_value_removed,
            original_collateral_value,
        )
        collateral_amount_removed = collateral_value_removed / prices

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
    prices: float,
    liquidation_ratio: float = 1.5,
) -> Vault:
    """
    Create a vault with a target initial collateral ratio.

    This is useful for generating synthetic vault populations.

    Example:
    If debt_dai = 1000, ETH price = 2000, target CR = 2.0,
    required collateral value = 2000 USD,
    required ETH = 1 ETH.

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
        ETH price in USD.
    liquidation_ratio:
        Liquidation ratio.

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
    if prices <= 0:
        raise ValueError("prices must be positive.")

    collateral_value = debt_dai * target_collateral_ratio
    collateral_amount = collateral_value / prices

    vault = Vault(
        vault_id=vault_id,
        owner_id=owner_id,
        collateral_amount=collateral_amount,
        debt_dai=debt_dai,
        liquidation_ratio=liquidation_ratio,
    )
    vault.validate()
    return vault


def generate_random_vaults(
    n_vaults: int,
    prices: float,
    liquidation_ratio: float = 1.5,
    debt_mean: float = 5_000.0,
    debt_std: float = 1_000.0,
    collateral_ratio_mean: float = 2.0,
    collateral_ratio_std: float = 0.25,
    min_collateral_ratio_buffer: float = 0.05,
    random_seed: Optional[int] = 42,
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
        Initial ETH price.
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

    Returns
    -------
    list[Vault]
        Generated vaults.
    """
    if n_vaults <= 0:
        raise ValueError("n_vaults must be positive.")
    if prices <= 0:
        raise ValueError("prices must be positive.")

    rng = np.random.default_rng(random_seed)

    debts = rng.normal(debt_mean, debt_std, size=n_vaults)
    debts = np.clip(debts, a_min=100.0, a_max=None)

    min_cr = liquidation_ratio + min_collateral_ratio_buffer
    collateral_ratios = rng.normal(
        collateral_ratio_mean, collateral_ratio_std, size=n_vaults
    )
    collateral_ratios = np.clip(collateral_ratios, a_min=min_cr, a_max=None)

    vaults = [
        create_vault_from_target_cr(
            vault_id=i,
            owner_id=i,
            debt_dai=float(debts[i]),
            target_collateral_ratio=float(collateral_ratios[i]),
            prices=prices,
            liquidation_ratio=liquidation_ratio,
        )
        for i in range(n_vaults)
    ]

    return vaults


def vaults_to_dataframe(vaults: list[Vault], prices: float) -> pd.DataFrame:
    """
    Convert a list of vaults to a DataFrame.

    Parameters
    ----------
    vaults:
        List of Vault objects.
    prices:
        Current ETH price.

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