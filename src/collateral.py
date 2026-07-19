"""
collateral.py

Collateral configuration utilities for the multi-collateral DAI simulation.

This module defines:
- collateral-specific risk parameters;
- portfolio-level collateral compositions;
- validation helpers for multi-collateral experiments.

The first implementation assumes that each vault holds exactly one collateral
type. Multi-asset vaults are intentionally left outside the current scope.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollateralConfig:
    """
    Configuration for one collateral type.

    Parameters
    ----------
    name:
        Unique collateral identifier, for example "ETH", "BTC", or "STABLE".
    initial_price:
        Initial market price of one unit of collateral.
    liquidation_ratio:
        Optional minimum collateral ratio required before liquidation.
        Example: 1.50 means 150%. ``None`` uses the global simulation value.
    liquidation_penalty:
        Optional fractional liquidation penalty.
        Example: 0.13 means 13%. ``None`` uses the global liquidation value.
    target_debt_share:
        Target share of total system debt assigned to this collateral type.
        Shares across a portfolio must sum to 1.
    max_close_factor:
        Optional maximum share of vault debt repaid by one liquidation.
        ``None`` uses the global liquidation value.
    """

    name: str
    initial_price: float
    liquidation_ratio: float | None
    liquidation_penalty: float | None
    target_debt_share: float
    max_close_factor: float | None = None

    def __post_init__(self) -> None:
        normalised_name = self.name.strip().upper()

        if not normalised_name:
            raise ValueError(
                "Collateral name must not be empty."
            )

        object.__setattr__(
            self,
            "name",
            normalised_name,
        )

        if self.initial_price <= 0:
            raise ValueError(
                "initial_price must be positive."
            )

        if (
            self.liquidation_ratio is not None
            and self.liquidation_ratio <= 1.0
        ):
            raise ValueError(
                "liquidation_ratio must be greater than 1.0."
            )

        if (
            self.liquidation_penalty is not None
            and self.liquidation_penalty < 0
        ):
            raise ValueError(
                "liquidation_penalty must be non-negative."
            )

        if (
            self.max_close_factor is not None
            and not 0.0 < self.max_close_factor <= 1.0
        ):
            raise ValueError(
                "max_close_factor must lie in (0, 1]."
            )

        if not 0.0 <= self.target_debt_share <= 1.0:
            raise ValueError(
                "target_debt_share must lie between 0 and 1."
            )


@dataclass(frozen=True)
class CollateralPortfolioConfig:
    """
    Configuration for a portfolio of collateral types.

    Parameters
    ----------
    name:
        Human-readable portfolio identifier.
    collaterals:
        Tuple of collateral configurations.

    Notes
    -----
    Collateral target debt shares must sum to 1.
    """

    name: str
    collaterals: tuple[CollateralConfig, ...]

    def __post_init__(self) -> None:
        portfolio_name = self.name.strip()

        if not portfolio_name:
            raise ValueError(
                "Portfolio name must not be empty."
            )

        object.__setattr__(
            self,
            "name",
            portfolio_name,
        )

        if not self.collaterals:
            raise ValueError(
                "At least one collateral type is required."
            )

        collateral_names = [
            collateral.name
            for collateral in self.collaterals
        ]

        if len(collateral_names) != len(set(collateral_names)):
            raise ValueError(
                "Collateral names must be unique within a portfolio."
            )

        total_share = sum(
            collateral.target_debt_share
            for collateral in self.collaterals
        )

        if abs(total_share - 1.0) > 1e-9:
            raise ValueError(
                "Collateral target debt shares must sum to 1.0. "
                f"Received total share: {total_share:.12f}."
            )

    @property
    def collateral_names(self) -> tuple[str, ...]:
        """
        Return collateral names in portfolio order.
        """
        return tuple(
            collateral.name
            for collateral in self.collaterals
        )

    @property
    def initial_prices(self) -> dict[str, float]:
        """
        Return initial prices keyed by collateral name.
        """
        return {
            collateral.name: collateral.initial_price
            for collateral in self.collaterals
        }

    @property
    def target_debt_shares(self) -> dict[str, float]:
        """
        Return target debt shares keyed by collateral name.
        """
        return {
            collateral.name: collateral.target_debt_share
            for collateral in self.collaterals
        }

    def get(
        self,
        collateral_type: str,
    ) -> CollateralConfig:
        """
        Return the configuration for one collateral type.

        Parameters
        ----------
        collateral_type:
            Collateral identifier.

        Returns
        -------
        CollateralConfig
            Matching collateral configuration.

        Raises
        ------
        KeyError
            If the collateral type is not in the portfolio.
        """
        normalised_type = collateral_type.strip().upper()

        for collateral in self.collaterals:
            if collateral.name == normalised_type:
                return collateral

        raise KeyError(
            f"Unknown collateral type '{collateral_type}' "
            f"in portfolio '{self.name}'."
        )

    def contains(
        self,
        collateral_type: str,
    ) -> bool:
        """
        Return whether the portfolio contains a collateral type.
        """
        normalised_type = collateral_type.strip().upper()

        return normalised_type in self.collateral_names


def normalise_collateral_prices(
    prices: float | dict[str, float],
) -> dict[str, float]:
    """
    Convert legacy scalar ETH price input into a price dictionary.

    Parameters
    ----------
    prices:
        Either:
        - a scalar ETH price for backward compatibility; or
        - a dictionary of collateral prices.

    Returns
    -------
    dict[str, float]
        Normalised collateral price map.
    """
    if isinstance(prices, dict):
        normalised_prices: dict[str, float] = {}

        for collateral_type, price in prices.items():
            normalised_type = str(
                collateral_type
            ).strip().upper()

            if not normalised_type:
                raise ValueError(
                    "Collateral price keys must not be empty."
                )

            numeric_price = float(price)

            if numeric_price <= 0:
                raise ValueError(
                    f"Price for {normalised_type} must be positive."
                )

            normalised_prices[normalised_type] = numeric_price

        if not normalised_prices:
            raise ValueError(
                "Collateral price dictionary must not be empty."
            )

        return normalised_prices

    scalar_price = float(prices)

    if scalar_price <= 0:
        raise ValueError(
            "ETH price must be positive."
        )

    return {
        "ETH": scalar_price,
    }


def validate_price_map_for_portfolio(
    prices: float | dict[str, float],
    portfolio: CollateralPortfolioConfig,
) -> dict[str, float]:
    """
    Validate that a price map covers every collateral in a portfolio.

    Parameters
    ----------
    prices:
        Scalar ETH price or collateral price dictionary.
    portfolio:
        Portfolio configuration.

    Returns
    -------
    dict[str, float]
        Normalised and validated price map.
    """
    price_map = normalise_collateral_prices(prices)

    missing_collaterals = (
        set(portfolio.collateral_names)
        - set(price_map)
    )

    if missing_collaterals:
        raise ValueError(
            "Missing prices for collateral types: "
            f"{sorted(missing_collaterals)}."
        )

    return price_map


def create_eth_only_portfolio() -> CollateralPortfolioConfig:
    """
    Create the backward-compatible ETH-only portfolio.
    """
    return CollateralPortfolioConfig(
        name="eth_only",
        collaterals=(
            CollateralConfig(
                name="ETH",
                initial_price=2000.0,
                liquidation_ratio=None,
                liquidation_penalty=None,
                target_debt_share=1.00,
            ),
        ),
    )


def create_crypto_diversified_portfolio() -> CollateralPortfolioConfig:
    """
    Create a portfolio split between ETH and BTC.
    """
    return CollateralPortfolioConfig(
        name="crypto_diversified",
        collaterals=(
            CollateralConfig(
                name="ETH",
                initial_price=2000.0,
                liquidation_ratio=1.50,
                liquidation_penalty=0.13,
                target_debt_share=0.60,
            ),
            CollateralConfig(
                name="BTC",
                initial_price=30000.0,
                liquidation_ratio=1.60,
                liquidation_penalty=0.13,
                target_debt_share=0.40,
            ),
        ),
    )


def create_balanced_portfolio() -> CollateralPortfolioConfig:
    """
    Create a balanced ETH, BTC, and stable-collateral portfolio.
    """
    return CollateralPortfolioConfig(
        name="balanced",
        collaterals=(
            CollateralConfig(
                name="ETH",
                initial_price=2000.0,
                liquidation_ratio=1.50,
                liquidation_penalty=0.13,
                target_debt_share=0.50,
            ),
            CollateralConfig(
                name="BTC",
                initial_price=30000.0,
                liquidation_ratio=1.60,
                liquidation_penalty=0.13,
                target_debt_share=0.25,
            ),
            CollateralConfig(
                name="STABLE",
                initial_price=1.0,
                liquidation_ratio=1.10,
                liquidation_penalty=0.05,
                target_debt_share=0.25,
            ),
        ),
    )


def create_stable_heavy_portfolio() -> CollateralPortfolioConfig:
    """
    Create a portfolio with a large stable-collateral share.
    """
    return CollateralPortfolioConfig(
        name="stable_heavy",
        collaterals=(
            CollateralConfig(
                name="ETH",
                initial_price=2000.0,
                liquidation_ratio=1.50,
                liquidation_penalty=0.13,
                target_debt_share=0.30,
            ),
            CollateralConfig(
                name="BTC",
                initial_price=30000.0,
                liquidation_ratio=1.60,
                liquidation_penalty=0.13,
                target_debt_share=0.20,
            ),
            CollateralConfig(
                name="STABLE",
                initial_price=1.0,
                liquidation_ratio=1.10,
                liquidation_penalty=0.05,
                target_debt_share=0.50,
            ),
        ),
    )


def create_btc_concentrated_portfolio() -> CollateralPortfolioConfig:
    """
    Create a portfolio concentrated in BTC collateral.
    """
    return CollateralPortfolioConfig(
        name="btc_concentrated",
        collaterals=(
            CollateralConfig(
                name="ETH",
                initial_price=2000.0,
                liquidation_ratio=1.50,
                liquidation_penalty=0.13,
                target_debt_share=0.20,
            ),
            CollateralConfig(
                name="BTC",
                initial_price=30000.0,
                liquidation_ratio=1.60,
                liquidation_penalty=0.13,
                target_debt_share=0.80,
            ),
        ),
    )


def create_default_multicollateral_portfolios(
) -> dict[str, CollateralPortfolioConfig]:
    """
    Return the default portfolio set for experiment 06.
    """
    portfolios = (
        create_eth_only_portfolio(),
        create_crypto_diversified_portfolio(),
        create_balanced_portfolio(),
        create_stable_heavy_portfolio(),
        create_btc_concentrated_portfolio(),
    )

    return {
        portfolio.name: portfolio
        for portfolio in portfolios
    }


if __name__ == "__main__":
    # Run:
    # python src/collateral.py

    portfolios = create_default_multicollateral_portfolios()

    print("Available collateral portfolios:")

    for portfolio_name, portfolio in portfolios.items():
        print(f"\n{portfolio_name}")

        for collateral in portfolio.collaterals:
            liquidation_ratio = (
                "global"
                if collateral.liquidation_ratio is None
                else f"{collateral.liquidation_ratio:.2f}"
            )
            liquidation_penalty = (
                "global"
                if collateral.liquidation_penalty is None
                else f"{collateral.liquidation_penalty:.2%}"
            )
            close_factor = (
                "global"
                if collateral.max_close_factor is None
                else f"{collateral.max_close_factor:.2%}"
            )
            print(
                f"  {collateral.name}: "
                f"price={collateral.initial_price}, "
                f"LR={liquidation_ratio}, "
                f"penalty={liquidation_penalty}, "
                f"close_factor={close_factor}, "
                f"debt_share={collateral.target_debt_share:.2%}"
            )

    eth_only = portfolios["eth_only"]

    validated_prices = validate_price_map_for_portfolio(
        prices=2000.0,
        portfolio=eth_only,
    )

    print("\nLegacy scalar ETH price normalised to:")
    print(validated_prices)
