"""Domain services for Feature 2 (ADR-015 section 2.1).

Services differ from entities in that they contain business logic that
doesn't belong to a single entity (e.g., CostCalculator processes a batch
Order and returns an aggregated TradingCost - neither Order nor TradingCost
owns that computation).

Public exports:
    - CostCalculator: ADR-012 brokerage + slippage + tax model

Future services (Sprint 12+):
    - ReturnDecomposer: factor decomposition cho attribution
    - InputValidator: cross-cutting validation (universe membership, weight sum)

Example
-------
>>> from decimal import Decimal
>>> from vn_portfolio_frontier.domain.services import CostCalculator
>>> calc = CostCalculator(brokerage_pct=Decimal("0.0015"))
"""

from vn_portfolio_frontier.domain.services.cost_calculator import CostCalculator

__all__ = [
    "CostCalculator",
]
