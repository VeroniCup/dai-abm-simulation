"""
liquidation.py

Simplified keeper/liquidation mechanics for the collateral-backed DAI simulation.

In MakerDAO-like systems, vaults do not liquidate themselves automatically.
External actors, often called keepers, must be incentivised to trigger and
participate in liquidations.

This module models a simplified liquidation decision:
- a vault is liquidatable if its collateral ratio is below the liquidation ratio;
- a keeper liquidates only if the expected profit is positive after gas and risk costs.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .collateral import CollateralPortfolioConfig
from .vault import Vault


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


def resolve_liquidation_parameters(
    vault: Vault,
    config: LiquidationConfig,
    portfolio: CollateralPortfolioConfig | None = None,
) -> tuple[float, float]:
    """
    Resolve liquidation penalty and close factor for one vault.

    Explicit collateral parameters take precedence. Missing collateral
    overrides, or an omitted portfolio, use the existing global configuration.
    """
    liquidation_penalty = config.liquidation_penalty
    max_close_factor = config.max_close_factor

    if portfolio is not None:
        collateral = portfolio.get(vault.collateral_type)

        if collateral.liquidation_penalty is not None:
            liquidation_penalty = collateral.liquidation_penalty
        if collateral.max_close_factor is not None:
            max_close_factor = collateral.max_close_factor

    return liquidation_penalty, max_close_factor


def expected_liquidation_profit(
    vault: Vault,
    prices: float | dict[str, float],
    config: LiquidationConfig,
    portfolio: CollateralPortfolioConfig | None = None,
) -> float:
    """
    Estimate keeper profit from liquidating a vault.

    This simplified model treats the liquidation penalty as the keeper's gross
    reward and subtracts gas cost plus a risk cost.

    Parameters
    ----------
    vault:
        Vault object.
    prices:
        Scalar ETH price or collateral price map.
    config:
        LiquidationConfig object.
    portfolio:
        Optional collateral configuration used to resolve explicit overrides.

    Returns
    -------
    float
        Expected liquidation profit in USD/DAI terms.
    """
    config.validate()

    if not vault.is_liquidatable(prices):
        return 0.0

    liquidation_penalty, max_close_factor = resolve_liquidation_parameters(
        vault=vault,
        config=config,
        portfolio=portfolio,
    )
    debt_repaid = vault.debt_dai * max_close_factor

    gross_reward = debt_repaid * liquidation_penalty
    risk_cost = debt_repaid * config.risk_cost_rate

    return gross_reward - config.gas_cost - risk_cost


def keeper_will_liquidate(
    vault: Vault,
    prices: float | dict[str, float],
    config: LiquidationConfig,
    portfolio: CollateralPortfolioConfig | None = None,
) -> bool:
    """
    Decide whether a keeper liquidates a vault.

    Parameters
    ----------
    vault:
        Vault object.
    prices:
        Scalar ETH price or collateral price map.
    config:
        LiquidationConfig object.
    portfolio:
        Optional collateral configuration used to resolve explicit overrides.

    Returns
    -------
    bool
        True if the vault is liquidatable and expected profit is positive.
    """
    return expected_liquidation_profit(
        vault,
        prices,
        config,
        portfolio=portfolio,
    ) > 0


def execute_keeper_liquidation(
    vault: Vault,
    prices: float | dict[str, float],
    config: LiquidationConfig,
    portfolio: CollateralPortfolioConfig | None = None,
) -> dict:
    """
    Execute liquidation if profitable.

    Parameters
    ----------
    vault:
        Vault object.
    prices:
        Scalar ETH price or collateral price map.
    config:
        LiquidationConfig object.
    portfolio:
        Optional collateral configuration used to resolve explicit overrides.

    Returns
    -------
    dict
        Liquidation attempt summary.
    """
    config.validate()

    expected_profit = expected_liquidation_profit(
        vault,
        prices,
        config,
        portfolio=portfolio,
    )

    if not vault.is_liquidatable(prices):
        return {
            "vault_id": vault.vault_id,
            "collateral_type": vault.collateral_type,
            "attempted": False,
            "liquidated": False,
            "fully_liquidated": False,
            "reason": "not_liquidatable",
            "expected_profit": expected_profit,
            "realised_keeper_profit": 0.0,
            "bad_debt": vault.bad_debt(prices),
            "debt_repaid": 0.0,
            "collateral_value": vault.collateral_value(prices),
            "collateral_value_before": vault.collateral_value(prices),
            "remaining_debt": vault.debt_dai,
            "remaining_collateral_amount": vault.collateral_amount,
        }

    if expected_profit <= 0:
        return {
            "vault_id": vault.vault_id,
            "collateral_type": vault.collateral_type,
            "attempted": True,
            "liquidated": False,
            "fully_liquidated": False,
            "reason": "unprofitable",
            "expected_profit": expected_profit,
            "realised_keeper_profit": 0.0,
            "bad_debt": vault.bad_debt(prices),
            "debt_repaid": 0.0,
            "collateral_value": vault.collateral_value(prices),
            "collateral_value_before": vault.collateral_value(prices),
            "remaining_debt": vault.debt_dai,
            "remaining_collateral_amount": vault.collateral_amount,
        }

    liquidation_penalty, max_close_factor = resolve_liquidation_parameters(
        vault=vault,
        config=config,
        portfolio=portfolio,
    )
    debt_repaid = vault.debt_dai * max_close_factor
    collateral_value_before = vault.collateral_value(prices)
    bad_debt_before = vault.bad_debt(prices)

    liquidation_summary = vault.partial_liquidate(
        prices=prices,
        debt_repaid=debt_repaid,
        liquidation_penalty=liquidation_penalty,
    )

    return {
        "vault_id": vault.vault_id,
        "collateral_type": vault.collateral_type,
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
        "remaining_collateral_amount": liquidation_summary[
            "remaining_collateral_amount"
        ],
    }


def liquidate_vaults(
    vaults: list[Vault],
    prices: float | dict[str, float],
    config: LiquidationConfig,
    portfolio: CollateralPortfolioConfig | None = None,
    bounded_demand: int | None = None,
    attempt_budget: int | None = None,
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
    prices:
        Scalar ETH price or collateral price map.
    config:
        LiquidationConfig object.
    portfolio:
        Optional collateral configuration used to resolve explicit overrides.

    Returns
    -------
    pd.DataFrame
        Liquidation attempt records for all vaults.
    """
    config.validate()
    if bounded_demand is not None and bounded_demand < 0:
        raise ValueError("bounded_demand cannot be negative.")
    if attempt_budget is not None and attempt_budget < 0:
        raise ValueError("attempt_budget cannot be negative.")
    if (
        bounded_demand is None
        and attempt_budget is not None
    ) or (
        bounded_demand is not None
        and attempt_budget is None
    ):
        raise ValueError("bounded_demand and attempt_budget must be supplied together.")
    if (
        bounded_demand is not None
        and attempt_budget is not None
        and attempt_budget > bounded_demand
    ):
        raise ValueError("attempt_budget cannot exceed bounded_demand.")

    preliminary_records = []

    for vault in vaults:
        expected_profit = expected_liquidation_profit(
            vault=vault,
            prices=prices,
            config=config,
            portfolio=portfolio,
        )

        preliminary_records.append(
            {
                "vault": vault,
                "vault_id": vault.vault_id,
                "is_liquidatable": vault.is_liquidatable(prices),
                "expected_profit": expected_profit,
                "is_profitable": expected_profit > 0,
            }
        )

    preliminary_df = pd.DataFrame(preliminary_records)

    if bounded_demand is None:
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
        demand_selected_vault_ids: set[int] | None = None
    else:
        liquidatable_df = preliminary_df[
            preliminary_df["is_liquidatable"]
        ].copy()
        liquidatable_df = liquidatable_df.sort_values(
            ["expected_profit", "vault_id"],
            ascending=[False, True],
        )
        demand_selected_vault_ids = set(
            liquidatable_df.head(bounded_demand)["vault_id"]
        )
        executable_vault_ids = set(
            liquidatable_df.head(attempt_budget)["vault_id"]
        )

    final_records = []

    for row in preliminary_records:
        vault = row["vault"]
        vault_id = row["vault_id"]

        if vault_id in executable_vault_ids:
            # This uses execute_keeper_liquidation(), which now calls
            # vault.partial_liquidate().
            record = execute_keeper_liquidation(
                vault=vault,
                prices=prices,
                config=config,
                portfolio=portfolio,
            )

        else:
            if not vault.is_liquidatable(prices):
                record = {
                    "vault_id": vault.vault_id,
                    "collateral_type": vault.collateral_type,
                    "attempted": False,
                    "liquidated": False,
                    "fully_liquidated": False,
                    "reason": "not_liquidatable",
                    "expected_profit": row["expected_profit"],
                    "realised_keeper_profit": 0.0,
                    "bad_debt": vault.bad_debt(prices),
                    "debt_repaid": 0.0,
                    "collateral_value": vault.collateral_value(prices),
                    "collateral_value_before": vault.collateral_value(prices),
                    "remaining_debt": vault.debt_dai,
                    "remaining_collateral_amount": vault.collateral_amount,
                }

            elif demand_selected_vault_ids is not None and vault_id not in demand_selected_vault_ids:
                record = {
                    "vault_id": vault.vault_id,
                    "collateral_type": vault.collateral_type,
                    "attempted": False,
                    "liquidated": False,
                    "fully_liquidated": False,
                    "reason": "demand_not_sampled",
                    "expected_profit": row["expected_profit"],
                    "realised_keeper_profit": 0.0,
                    "bad_debt": vault.bad_debt(prices),
                    "debt_repaid": 0.0,
                    "collateral_value": vault.collateral_value(prices),
                    "collateral_value_before": vault.collateral_value(prices),
                    "remaining_debt": vault.debt_dai,
                    "remaining_collateral_amount": vault.collateral_amount,
                }

            elif demand_selected_vault_ids is not None:
                # Demand-selected rows outside the ranked attempt budget are
                # capacity-limited even when their ex-post profit is negative.
                # They were not sent to execute_keeper_liquidation and must
                # not consume the authoritative attempt budget.
                record = {
                    "vault_id": vault.vault_id,
                    "collateral_type": vault.collateral_type,
                    "attempted": False,
                    "liquidated": False,
                    "fully_liquidated": False,
                    "reason": "capacity_limited",
                    "expected_profit": row["expected_profit"],
                    "realised_keeper_profit": 0.0,
                    "bad_debt": vault.bad_debt(prices),
                    "debt_repaid": 0.0,
                    "collateral_value": vault.collateral_value(prices),
                    "collateral_value_before": vault.collateral_value(prices),
                    "remaining_debt": vault.debt_dai,
                    "remaining_collateral_amount": vault.collateral_amount,
                }

            elif row["expected_profit"] <= 0:
                record = {
                    "vault_id": vault.vault_id,
                    "collateral_type": vault.collateral_type,
                    "attempted": True,
                    "liquidated": False,
                    "fully_liquidated": False,
                    "reason": "unprofitable",
                    "expected_profit": row["expected_profit"],
                    "realised_keeper_profit": 0.0,
                    "bad_debt": vault.bad_debt(prices),
                    "debt_repaid": 0.0,
                    "collateral_value": vault.collateral_value(prices),
                    "collateral_value_before": vault.collateral_value(prices),
                    "remaining_debt": vault.debt_dai,
                    "remaining_collateral_amount": vault.collateral_amount,
                }

            else:
                record = {
                    "vault_id": vault.vault_id,
                    "collateral_type": vault.collateral_type,
                    "attempted": True,
                    "liquidated": False,
                    "fully_liquidated": False,
                    "reason": "capacity_limited",
                    "expected_profit": row["expected_profit"],
                    "realised_keeper_profit": 0.0,
                    "bad_debt": vault.bad_debt(prices),
                    "debt_repaid": 0.0,
                    "collateral_value": vault.collateral_value(prices),
                    "collateral_value_before": vault.collateral_value(prices),
                    "remaining_debt": vault.debt_dai,
                    "remaining_collateral_amount": vault.collateral_amount,
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
    # Quick smoke test: PYTHONPATH=src python -m dai_sim.model.liquidation

    from .vault import generate_random_vaults, vaults_to_dataframe

    initial_prices = 2_000.0
    shocked_prices = 1_140.0

    vaults = generate_random_vaults(
        n_vaults=10,
        prices=initial_prices,
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

    before = vaults_to_dataframe(vaults, prices=shocked_prices)
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
        prices=shocked_prices,
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

    after = vaults_to_dataframe(vaults, prices=shocked_prices)
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
