"""Order value object + OrderSide enum for Feature 2 rebalancing.

An Order represents a single buy/sell instruction produced by a
RebalanceStrategy at a trigger event. Orders are immutable value objects
with no identity of their own - they live inside a RebalanceDecision.

Design decisions (ADR-015 §2):
    - Frozen dataclass: enforces immutability at runtime (FrozenInstanceError
      on mutation attempts). Chosen over Pydantic for zero overhead in
      backtest loops (10K+ decisions per sensitivity sweep point).
    - Decimal for prices and shares * price computations: NFR-R-07
      deterministic reproducibility requires no float precision drift when
      summing cost components across many trades.
    - Shares are int (whole lots convention for Vietnamese equities;
      HOSE enforces lot size 100 but that is a strategy-level concern,
      not an entity-level one).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class OrderSide(Enum):
    """Direction of a trade.

    Attributes
    ----------
    BUY : str
        Increase holding of the given ticker (consumes cash).
    SELL : str
        Decrease holding of the given ticker (releases cash minus costs).
    """

    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Order:
    """A single buy/sell instruction at a trigger event.

    Parameters
    ----------
    ticker : str
        Instrument identifier (e.g. "VCB", "FPT"). Validated non-empty at
        __post_init__.
    side : OrderSide
        BUY or SELL direction.
    shares : int
        Number of shares to transact. Must be positive; a zero-share order
        is semantically a no-op and should not be created.
    est_price : Decimal
        Estimated execution price in VND per share at the trigger date
        (close of day in the current cost model). Must be positive.

    Raises
    ------
    ValueError
        If ticker is empty, shares <= 0, or est_price <= 0.

    Notes
    -----
    Orders are value objects: two orders with identical attributes compare
    equal (via dataclass-generated __eq__) and hash identically (frozen).
    This lets cost caching layers key on an order's content safely.

    Examples
    --------
    >>> buy = Order("VCB", OrderSide.BUY, 100, Decimal("125000"))
    >>> buy.ticker
    'VCB'
    >>> buy.gross_amount()
    Decimal('12500000')
    """

    ticker: str
    side: OrderSide
    shares: int
    est_price: Decimal

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ValueError("Order.ticker must not be empty")
        if self.shares <= 0:
            raise ValueError(f"Order.shares must be positive, got {self.shares}")
        if self.est_price <= 0:
            raise ValueError(f"Order.est_price must be positive, got {self.est_price}")

    def gross_amount(self) -> Decimal:
        """Return the pre-cost cash value of this order.

        Returns
        -------
        Decimal
            shares * est_price, always positive.

        Notes
        -----
        For a BUY, this is cash consumed before brokerage/slippage/tax.
        For a SELL, this is gross proceeds before costs are deducted.
        """
        return Decimal(self.shares) * self.est_price
