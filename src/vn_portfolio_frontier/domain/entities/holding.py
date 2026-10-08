"""Holding value object — one ticker position inside a Portfolio.

A Holding represents the state of ownership for a single ticker: how many
shares, at what average cost. It carries no identity of its own; equality
is defined by all fields (dataclass default).

Design decisions:
    - Frozen dataclass: immutable snapshot per rebalance iteration. When
      a trade modifies the holding, Portfolio replaces the Holding
      instance rather than mutating it in place. This gives us free
      undo/replay semantics in backtest loops.
    - shares as int: whole lots convention (HOSE lot size 100 is enforced
      at the strategy / cost calculator level, not here).
    - avg_cost as Decimal: carried for Vietnam tax calculation
      (chi phí vốn determines capital gain basis). Not used in Sprint 11
      MUST tier (no tax beyond flat 0.1% per Thông tư 111/2013/TT-BTC),
      but ready for Sprint 12+ when short-term vs long-term distinction
      is added.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Holding:
    """A single-ticker position inside a Portfolio.

    Parameters
    ----------
    ticker : str
        Instrument identifier. Validated non-empty.
    shares : int
        Current share count. Must be non-negative (zero is a valid
        "flat" holding, kept in the portfolio dict so that later
        rebalance iterations can re-open it without a key error).
    avg_cost : Decimal
        Volume-weighted average purchase price in VND per share. Must be
        non-negative. Zero is valid when shares == 0 (empty holding).

    Raises
    ------
    ValueError
        If ticker is empty, shares < 0, or avg_cost < 0.

    Notes
    -----
    An "empty" holding (shares=0, avg_cost=0) is semantically different
    from a missing holding: it signals the ticker is tracked in the
    universe but currently flat. Portfolio.get_weights() treats both as
    weight 0.0, but Portfolio.apply_orders() uses the presence of the
    key to decide between re-open vs new-open.

    Examples
    --------
    >>> h = Holding("VCB", 100, Decimal("120000"))
    >>> h.market_value(Decimal("125000"))
    Decimal('12500000')
    >>> h.unrealized_pnl(Decimal("125000"))
    Decimal('500000')
    """

    ticker: str
    shares: int
    avg_cost: Decimal

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ValueError("Holding.ticker must not be empty")
        if self.shares < 0:
            raise ValueError(f"Holding.shares must be non-negative, got {self.shares}")
        if self.avg_cost < 0:
            raise ValueError(f"Holding.avg_cost must be non-negative, got {self.avg_cost}")

    def market_value(self, current_price: Decimal) -> Decimal:
        """Return the current market value of this holding.

        Parameters
        ----------
        current_price : Decimal
            Latest market price per share in VND.

        Returns
        -------
        Decimal
            shares * current_price. Always non-negative.
        """
        return Decimal(self.shares) * current_price

    def unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """Return mark-to-market unrealised P&L vs average cost.

        Parameters
        ----------
        current_price : Decimal
            Latest market price per share.

        Returns
        -------
        Decimal
            shares * (current_price - avg_cost). Positive = gain,
            negative = loss, zero = flat or empty holding.

        Notes
        -----
        This is the pre-tax, pre-cost figure. Realised P&L on sale is
        computed by Portfolio.apply_orders() in combination with
        TradingCost from CostCalculator.
        """
        return Decimal(self.shares) * (current_price - self.avg_cost)
