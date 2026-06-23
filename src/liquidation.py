"""
liquidation.py

Simplified keeper/liquidation mechanics for the ETH-backed DAI simulation.

In MakerDAO-like systems, vaults do not liquidate themselves automatically.
External actors, often called keepers, must be incentivised to trigger and
participate in liquidations.

This module models a simplified liquidation decision:
- a vault is liquidatable if its collateral ratio is below the liquidation ratio;
- a keeper liquidates only if the expected profit is positive after gas and risk costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from vault import Vault


@dataclass(frozen=True)
class LiquidationConfig:
    """
    Configuration for simplified liquidation mechanics.

    Attributes
    ----------
    liquidation_penalty:
        Penalty/reward rate applied to repaid debt.
        Example: 0.13 means 13% liquidation penalty.
    gas_cost:
        Fixed cost of attempting liquidation, denominated in USD/DAI.
    risk_cost_rate:
        Extra proportional cost representing auction delay, price risk,
        slippage, or operational uncertainty.
        Example: 0.02 means 2% of repaid debt.
    max_close_factor:
        Maximum proportion of debt repaid in one liquidation.
        For simplicity, 1.0 means full liquidation.
    """

    liquidation_penalty: float = 0.13
    gas_cost: float = 100.0
    risk_cost_rate: float = 0.00
    max_close_factor: float = 1.0
    max_liquidations_per_step: int | None = None

    def validate(self) -> None:
        """Validate liquidation configuration."""
        if self.liquidation_penalty < 0:
            raise ValueError("liquidation_penalty cannot be negative.")
        if self.gas_cost < 0:
            raise ValueError("gas_cost cannot be negative.")
        if self.risk_cost_rate < 0:
            raise ValueError("risk_cost_rate cannot be negative.")
        if not 0 < self.max_close_factor <= 1:
            raise ValueError("max_close_factor must be in (0, 1].")
        if self.max_liquidations_per_step is not None:
            if self.max_liquidations_per_step <= 0:
                raise ValueError("max_liquidations_per_step must be positive or None.")


def expected_liquidation_profit(
    vault: Vault,
    eth_price: float,
    config: LiquidationConfig,
) -> float:
    """
    Estimate keeper profit from liquidating a vault.

    This simplified model treats the liquidation penalty as the keeper's gross
    reward and subtracts gas cost plus a risk cost.

    Parameters
    ----------
    vault:
        Vault object.
    eth_price:
        Current ETH price.
    config:
        LiquidationConfig object.

    Returns
    -------
    float
        Expected liquidation profit in USD/DAI terms.
    """
    config.validate()

    if not vault.is_liquidatable(eth_price):
        return 0.0

    debt_repaid = vault.debt_dai * config.max_close_factor

    gross_reward = debt_repaid * config.liquidation_penalty
    risk_cost = debt_repaid * config.risk_cost_rate

    return gross_reward - config.gas_cost - risk_cost


def keeper_will_liquidate(
    vault: Vault,
    eth_price: float,
    config: LiquidationConfig,
) -> bool:
    """
    Decide whether a keeper liquidates a vault.

    Parameters
    ----------
    vault:
        Vault object.
    eth_price:
        Current ETH price.
    config:
        LiquidationConfig object.

    Returns
    -------
    bool
        True if the vault is liquidatable and expected profit is positive.
    """
    return expected_liquidation_profit(vault, eth_price, config) > 0


def execute_keeper_liquidation(
    vault: Vault,
    eth_price: float,
    config: LiquidationConfig,
) -> dict:
    """
    Execute liquidation if profitable.

    Parameters
    ----------
    vault:
        Vault object.
    eth_price:
        Current ETH price.
    config:
        LiquidationConfig object.

    Returns
    -------
    dict
        Liquidation attempt summary.
    """
    config.validate()

    expected_profit = expected_liquidation_profit(vault, eth_price, config)

    if not vault.is_liquidatable(eth_price):
        return {
            "vault_id": vault.vault_id,
            "attempted": False,
            "liquidated": False,
            "fully_liquidated": False,
            "reason": "not_liquidatable",
            "expected_profit": expected_profit,
            "realised_keeper_profit": 0.0,
            "bad_debt": vault.bad_debt(eth_price),
            "debt_repaid": 0.0,
            "collateral_value": vault.collateral_value(eth_price),
            "collateral_value_before": vault.collateral_value(eth_price),
            "remaining_debt": vault.debt_dai,
            "remaining_collateral_eth": vault.collateral_eth,
        }

    if expected_profit <= 0:
        return {
            "vault_id": vault.vault_id,
            "attempted": True,
            "liquidated": False,
            "fully_liquidated": False,
            "reason": "unprofitable",
            "expected_profit": expected_profit,
            "realised_keeper_profit": 0.0,
            "bad_debt": vault.bad_debt(eth_price),
            "debt_repaid": 0.0,
            "collateral_value": vault.collateral_value(eth_price),
            "collateral_value_before": vault.collateral_value(eth_price),
            "remaining_debt": vault.debt_dai,
            "remaining_collateral_eth": vault.collateral_eth,
        }

    debt_repaid = vault.debt_dai * config.max_close_factor
    collateral_value_before = vault.collateral_value(eth_price)
    bad_debt_before = vault.bad_debt(eth_price)

    liquidation_summary = vault.partial_liquidate(
        eth_price=eth_price,
        debt_repaid=debt_repaid,
        liquidation_penalty=config.liquidation_penalty,
    )

    return {
        "vault_id": vault.vault_id,
        "attempted": True,
        "liquidated": liquidation_summary["liquidated"],
        "fully_liquidated": liquidation_summary["fully_liquidated"],
        "reason": "profitable",
        "expected_profit": expected_profit,
        "realised_keeper_profit": expected_profit,
        "bad_debt": liquidation_summary["bad_debt"],
        "debt_repaid": liquidation_summary["debt_repaid"],
        "collateral_value": liquidation_summary["collateral_value_removed"],
        "collateral_value_before": collateral_value_before,
        "remaining_debt": liquidation_summary["remaining_debt"],
        "remaining_collateral_eth": liquidation_summary["remaining_collateral_eth"],
    }


def liquidate_vaults(
    vaults: list[Vault],
    eth_price: float,
    config: LiquidationConfig,
) -> pd.DataFrame:
    """
    Apply keeper liquidation decision to all vaults.

    Profitable liquidation opportunities are ranked by expected profit.
    If max_liquidations_per_step is set, only the most profitable opportunities
    are executed in the current step.

    Parameters
    ----------
    vaults:
        List of Vault objects.
    eth_price:
        Current ETH price.
    config:
        LiquidationConfig object.

    Returns
    -------
    pd.DataFrame
        Liquidation attempt records for all vaults.
    """
    config.validate()

    preliminary_records = []

    for vault in vaults:
        expected_profit = expected_liquidation_profit(
            vault=vault,
            eth_price=eth_price,
            config=config,
        )

        preliminary_records.append(
            {
                "vault": vault,
                "vault_id": vault.vault_id,
                "is_liquidatable": vault.is_liquidatable(eth_price),
                "expected_profit": expected_profit,
                "is_profitable": expected_profit > 0,
            }
        )

    preliminary_df = pd.DataFrame(preliminary_records)

    profitable_df = preliminary_df[
        preliminary_df["is_liquidatable"] & preliminary_df["is_profitable"]
    ].copy()

    profitable_df = profitable_df.sort_values(
        "expected_profit",
        ascending=False,
    )

    if config.max_liquidations_per_step is not None:
        executable_vault_ids = set(
            profitable_df.head(config.max_liquidations_per_step)["vault_id"]
        )
    else:
        executable_vault_ids = set(profitable_df["vault_id"])

    final_records = []

    for row in preliminary_records:
        vault = row["vault"]
        vault_id = row["vault_id"]

        if vault_id in executable_vault_ids:
            # This uses execute_keeper_liquidation(), which now calls
            # vault.partial_liquidate().
            record = execute_keeper_liquidation(
                vault=vault,
                eth_price=eth_price,
                config=config,
            )

        else:
            if not vault.is_liquidatable(eth_price):
                record = {
                    "vault_id": vault.vault_id,
                    "attempted": False,
                    "liquidated": False,
                    "fully_liquidated": False,
                    "reason": "not_liquidatable",
                    "expected_profit": row["expected_profit"],
                    "realised_keeper_profit": 0.0,
                    "bad_debt": vault.bad_debt(eth_price),
                    "debt_repaid": 0.0,
                    "collateral_value": vault.collateral_value(eth_price),
                    "collateral_value_before": vault.collateral_value(eth_price),
                    "remaining_debt": vault.debt_dai,
                    "remaining_collateral_eth": vault.collateral_eth,
                }

            elif row["expected_profit"] <= 0:
                record = {
                    "vault_id": vault.vault_id,
                    "attempted": True,
                    "liquidated": False,
                    "fully_liquidated": False,
                    "reason": "unprofitable",
                    "expected_profit": row["expected_profit"],
                    "realised_keeper_profit": 0.0,
                    "bad_debt": vault.bad_debt(eth_price),
                    "debt_repaid": 0.0,
                    "collateral_value": vault.collateral_value(eth_price),
                    "collateral_value_before": vault.collateral_value(eth_price),
                    "remaining_debt": vault.debt_dai,
                    "remaining_collateral_eth": vault.collateral_eth,
                }

            else:
                record = {
                    "vault_id": vault.vault_id,
                    "attempted": True,
                    "liquidated": False,
                    "fully_liquidated": False,
                    "reason": "capacity_limited",
                    "expected_profit": row["expected_profit"],
                    "realised_keeper_profit": 0.0,
                    "bad_debt": vault.bad_debt(eth_price),
                    "debt_repaid": 0.0,
                    "collateral_value": vault.collateral_value(eth_price),
                    "collateral_value_before": vault.collateral_value(eth_price),
                    "remaining_debt": vault.debt_dai,
                    "remaining_collateral_eth": vault.collateral_eth,
                }

        final_records.append(record)

    return pd.DataFrame(final_records)


def summarise_liquidations(liquidation_df: pd.DataFrame) -> dict:
    """
    Summarise liquidation attempt records.

    Important distinction:
    - n_liquidated counts vaults that received a liquidation action.
      With partial liquidation, these vaults may still remain active.
    - n_fully_liquidated counts vaults whose debt was fully closed.
      These vaults become inactive.

    Parameters
    ----------
    liquidation_df:
        DataFrame produced by liquidate_vaults.

    Returns
    -------
    dict
        Aggregate liquidation summary.
    """
    if liquidation_df.empty:
        return {
            "n_attempted": 0,
            "n_liquidated": 0,
            "n_fully_liquidated": 0,
            "n_unprofitable": 0,
            "n_capacity_limited": 0,
            "keeper_profit": 0.0,
            "bad_debt_realised": 0.0,
            "debt_repaid": 0.0,
            "collateral_liquidated": 0.0,
        }

    n_attempted = int(liquidation_df["attempted"].sum())

    # A successful liquidation action happened.
    # Under partial liquidation, this does not necessarily mean the vault is closed.
    n_liquidated = int(liquidation_df["liquidated"].sum())

    # A vault was completely closed.
    # This only happens when the liquidation repays all remaining debt.
    n_fully_liquidated = int(liquidation_df["fully_liquidated"].sum())

    # Liquidation was possible but not economically attractive.
    n_unprofitable = int((liquidation_df["reason"] == "unprofitable").sum())

    # Liquidation was profitable but not executed because keeper capacity was exhausted.
    n_capacity_limited = int(
        (liquidation_df["reason"] == "capacity_limited").sum()
    )

    return {
        "n_attempted": n_attempted,
        "n_liquidated": n_liquidated,
        "n_fully_liquidated": n_fully_liquidated,
        "n_unprofitable": n_unprofitable,
        "n_capacity_limited": n_capacity_limited,
        "keeper_profit": liquidation_df["realised_keeper_profit"].sum(),
        "bad_debt_realised": liquidation_df.loc[
            liquidation_df["liquidated"], "bad_debt"
        ].sum(),
        "debt_repaid": liquidation_df["debt_repaid"].sum(),
        "collateral_liquidated": liquidation_df.loc[
            liquidation_df["liquidated"], "collateral_value"
        ].sum(),
    }


if __name__ == "__main__":
    # Quick smoke test. Run:
    # python src/liquidation.py

    from vault import generate_random_vaults, vaults_to_dataframe

    initial_eth_price = 2_000.0
    shocked_eth_price = 1_140.0

    vaults = generate_random_vaults(
        n_vaults=10,
        eth_price=initial_eth_price,
        liquidation_ratio=1.5,
        random_seed=42,
    )

    liq_config = LiquidationConfig(
        liquidation_penalty=0.13,
        gas_cost=100.0,
        risk_cost_rate=0.00,
        max_close_factor=0.5,
        max_liquidations_per_step=3,
    )

    before = vaults_to_dataframe(vaults, eth_price=shocked_eth_price)
    print("Vaults after ETH shock, before liquidation:")
    print(
        before[
            [
                "vault_id",
                "debt_dai",
                "collateral_ratio",
                "is_liquidatable",
                "bad_debt",
            ]
        ]
    )

    liquidation_df = liquidate_vaults(
        vaults=vaults,
        eth_price=shocked_eth_price,
        config=liq_config,
    )

    print("\nLiquidation attempts:")
    print(
        liquidation_df[
            [
                "vault_id",
                "attempted",
                "liquidated",
                "fully_liquidated",
                "reason",
                "expected_profit",
                "debt_repaid",
                "remaining_debt",
                "bad_debt",
            ]
        ]
    )

    print("\nLiquidation summary:")
    print(summarise_liquidations(liquidation_df))

    after = vaults_to_dataframe(vaults, eth_price=shocked_eth_price)
    print("\nVaults after liquidation:")
    print(
        after[
            [
                "vault_id",
                "debt_dai",
                "collateral_ratio",
                "is_active",
                "is_liquidated",
                "bad_debt",
            ]
        ]
    )