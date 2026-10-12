"""Rebalance strategies for Feature 2 (ADR-015 section 2.2 Strategy Pattern).

Public exports:
    - BaseStrategy: abstract Template Method base (`rebalance` is the template)
    - ThresholdBandStrategy: concrete - trigger when max drift > band_bps

Future strategies (Sprint 12):
    - CalendarMonthlyStrategy: trigger first trading day of each month
    - FixedWindowStrategy: trigger every N trading days since last rebalance
    - HybridStrategy: ThresholdBand AND (Calendar OR Window)

Example
-------
>>> from decimal import Decimal
>>> from vn_portfolio_frontier.domain.services.cost_calculator import CostCalculator
>>> from vn_portfolio_frontier.domain.strategies import ThresholdBandStrategy
>>> calc = CostCalculator(brokerage_pct=Decimal("0.0015"))
>>> strategy = ThresholdBandStrategy(calc, band_bps=500)
"""

from vn_portfolio_frontier.domain.strategies.base import BaseStrategy
from vn_portfolio_frontier.domain.strategies.threshold_band import ThresholdBandStrategy

__all__ = [
    "BaseStrategy",
    "ThresholdBandStrategy",
]
