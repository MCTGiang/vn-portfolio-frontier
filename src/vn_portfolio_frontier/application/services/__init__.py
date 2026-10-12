"""Application services for Feature 2 (ADR-015 section 2.5).

Services orchestrate domain objects + repository ports to deliver use cases.
Unlike domain services (CostCalculator), application services are allowed to
depend on ports and are the natural seam for Factory DI wiring.

Public exports:
    - RebalanceSimulator: orchestrator for end-to-end backtest + persistence
    - SimulateRequest: frozen DTO input contract
    - StrategyFactory, ProgressCallback: type aliases exposed for callers
      building the Simulator (AppFactory, tests)
"""

from vn_portfolio_frontier.application.services.rebalance_simulator import (
    ProgressCallback,
    RebalanceSimulator,
    SimulateRequest,
    StrategyFactory,
)

__all__ = [
    "ProgressCallback",
    "RebalanceSimulator",
    "SimulateRequest",
    "StrategyFactory",
]
