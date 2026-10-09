"""Application ports (Protocol interfaces) per ADR-015 Hexagonal Architecture.

Ports là contracts giữa Application core và Infrastructure adapters. Application
services (RebalanceSimulator Day 6+) depend on these abstractions, never on
concrete Neon/vnstock implementations.

Public exports:
    - PriceRepository: prices.daily_ohlcv access (get_ohlcv + batch_insert + get_latest_dates)
    - RebalanceRunRepository: simulation.rebalance_run access (save + find_by_id + list_recent)
    - RebalanceDecisionRepository: simulation.rebalance_decision access (save_batch + find_by_run)
    - RunRecord: DTO for RebalanceRunRepository.save() input + find_by_id() output
    - RunSummary: lightweight DTO for RebalanceRunRepository.list_recent()

Example - DI pattern (Factory wiring Day 6):
    >>> from vn_portfolio_frontier.application.ports import PriceRepository
    >>> def consume_repo(repo: PriceRepository) -> None:  # type-hint on Protocol
    ...     bars = repo.get_ohlcv("VCB", start, end)
    ...     # Static type checker (mypy) verifies repo has get_ohlcv at CI
    ...     # Factory wires NeonPriceRepository; tests wire FakePriceRepository
"""

from vn_portfolio_frontier.application.ports.decision_repository import (
    RebalanceDecisionRepository,
)
from vn_portfolio_frontier.application.ports.price_repository import PriceRepository
from vn_portfolio_frontier.application.ports.run_repository import (
    RebalanceRunRepository,
    RunRecord,
    RunSummary,
)

__all__ = [
    "PriceRepository",
    "RebalanceDecisionRepository",
    "RebalanceRunRepository",
    "RunRecord",
    "RunSummary",
]
