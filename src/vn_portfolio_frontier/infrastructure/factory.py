"""AppFactory - production DI wiring per ADR-015 section 2.5.

Composes Pydantic Settings + db connection + concrete Neon adapters +
strategy factory + RebalanceSimulator. Single entry point from
interface/ layer (Streamlit, CLI) into the application core.

Example usage from Streamlit:
    >>> from vn_portfolio_frontier.infrastructure.factory import AppFactory
    >>> factory = AppFactory()
    >>> simulator = factory.rebalance_simulator()
    >>> run_id = simulator.simulate(request)
    >>> record = factory.run_repo().find_by_id(run_id)

Lifecycle: AppFactory is intended to be built once per application process.
Repositories are created on demand (each call returns a fresh instance that
shares the same connection_factory). Connection factories read from the
Settings singleton (get_settings()) so a running process picks up updated
NEON_DATABASE_URL only after restart.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import psycopg2

from vn_portfolio_frontier.application.services import (
    FrontierService,
    RebalanceSimulator,
    StrategyFactory,
)
from vn_portfolio_frontier.config import get_settings
from vn_portfolio_frontier.domain.services import CostCalculator
from vn_portfolio_frontier.domain.strategies import BaseStrategy, ThresholdBandStrategy
from vn_portfolio_frontier.infrastructure.repositories import (
    NeonPriceRepository,
    NeonRebalanceDecisionRepository,
    NeonRebalanceRunRepository,
)

if TYPE_CHECKING:
    from vn_portfolio_frontier.application.ports import (
        PriceRepository,
        RebalanceDecisionRepository,
        RebalanceRunRepository,
    )

ConnectionFactory = Callable[[], "psycopg2.extensions.connection"]


def _default_connection_factory() -> psycopg2.extensions.connection:
    """Build a fresh psycopg2 connection from Pydantic Settings."""
    settings = get_settings()
    dsn = settings.neon_database_url.get_secret_value()
    if not dsn:
        raise RuntimeError(
            "AppFactory: NEON_DATABASE_URL is not configured. "
            "Set it in .env for local development or in the deployment "
            "environment for production."
        )
    return psycopg2.connect(dsn)


def _default_strategy_factory(
    name: str,
    params: dict[str, Any],
    cost_calc: CostCalculator,
) -> BaseStrategy:
    """Map strategy_name -> concrete BaseStrategy subclass.

    Add new strategies here as Sprint 12+ expands the SHOULD tier
    (CalendarMonthlyStrategy, HybridStrategy).
    """
    if name == "threshold_band":
        return ThresholdBandStrategy(cost_calc, **params)
    raise ValueError(f"Unknown strategy: {name}")


class AppFactory:
    """Production DI composition root.

    Parameters
    ----------
    connection_factory : callable, optional
        Override for the psycopg2 connection builder. Defaults to
        _default_connection_factory which reads NEON_DATABASE_URL via
        Pydantic Settings. Tests inject a mock to avoid touching Neon.
    strategy_factory : callable, optional
        Override for the strategy_name -> BaseStrategy mapping. Defaults
        to _default_strategy_factory (threshold_band only). Sprint 12
        adds more strategies; this seam lets tests inject fakes.
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory | None = None,
        strategy_factory: StrategyFactory | None = None,
    ) -> None:
        self._conn_factory = connection_factory or _default_connection_factory
        self._strategy_factory = strategy_factory or _default_strategy_factory

    def price_repo(self) -> PriceRepository:
        return NeonPriceRepository(self._conn_factory)

    def run_repo(self) -> RebalanceRunRepository:
        return NeonRebalanceRunRepository(self._conn_factory)

    def decision_repo(self) -> RebalanceDecisionRepository:
        return NeonRebalanceDecisionRepository(self._conn_factory)

    def rebalance_simulator(self) -> RebalanceSimulator:
        return RebalanceSimulator(
            price_repo=self.price_repo(),
            run_repo=self.run_repo(),
            decision_repo=self.decision_repo(),
            strategy_factory=self._strategy_factory,
        )

    def frontier_service(self) -> FrontierService:
        """Build FrontierService for F1 Efficient Frontier (Day 11).

        Reuses Simulator._fetch_rf_annual_pct for Rf fetching (Day 9 Step B
        benchmark schema). The method is stateless (reads Settings directly),
        so binding via a disposable Simulator instance is safe. Sprint 15
        polish option: extract to standalone RfFetcher utility module.
        """
        disposable_sim = self.rebalance_simulator()
        return FrontierService(
            price_repo=self.price_repo(),
            rf_fetcher=disposable_sim._fetch_rf_annual_pct,  # noqa: SLF001
        )
