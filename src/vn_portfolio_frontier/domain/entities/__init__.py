"""Domain entities for Feature 2 Rebalancing Simulator (ADR-015 §2.1).

This package exports the full set of domain-level entities and value
objects that strategies, services, and repositories work with. The
convention is to import from this module (not submodules) so that
future entity relocations stay transparent to callers.

Entities:
    - Portfolio: mutable aggregate root (cash + holdings + target_weights)
    - RebalanceDecision: record of one trigger evaluation outcome

Value objects (all frozen dataclasses):
    - Holding: single-ticker position inside a Portfolio
    - Order: BUY/SELL instruction with gross_amount
    - OrderSide: BUY | SELL enum
    - DailyPrice: one trading day OHLCV bar
    - RebalanceContext: snapshot of world state at a trigger
    - TradingCost: brokerage + slippage + tax breakdown

Example
-------
>>> from vn_portfolio_frontier.domain.entities import (
...     Portfolio, Order, OrderSide, Holding,
...     RebalanceDecision, TradingCost, RebalanceContext,
...     DailyPrice,
... )
"""

from vn_portfolio_frontier.domain.entities.daily_price import DailyPrice
from vn_portfolio_frontier.domain.entities.holding import Holding
from vn_portfolio_frontier.domain.entities.order import Order, OrderSide
from vn_portfolio_frontier.domain.entities.portfolio import Portfolio
from vn_portfolio_frontier.domain.entities.rebalance_context import RebalanceContext
from vn_portfolio_frontier.domain.entities.rebalance_decision import (
    RebalanceDecision,
    TradingCost,
)

__all__ = [
    "DailyPrice",
    "Holding",
    "Order",
    "OrderSide",
    "Portfolio",
    "RebalanceContext",
    "RebalanceDecision",
    "TradingCost",
]
