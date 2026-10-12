"""RebalanceSimulator - orchestrator for Feature 2 end-to-end backtest.

Per ADR-015 section 2.5 Factory DI wiring. Composes:
    - Portfolio aggregate root (domain entity)
    - Strategy via injected factory (domain)
    - CostCalculator service (domain)
    - 3 Repository ports (application) injected at construction

Flow summary:
    1. Save initial RunRecord (status=running) -> get run_id
    2. Load price history for all tickers across backtest range
    3. Instantiate Portfolio + CostCalculator + Strategy via factory
    4. Daily loop: build RebalanceContext -> strategy.rebalance() ->
       apply_orders. Collect decisions + daily portfolio values.
    5. Compute KPIs (n_rebalances, total_cost_bps, turnover_avg_pct,
       sharpe_before_cost, sharpe_after_cost)
    6. Update RunRecord with status=completed + KPIs
    7. Batch save all decisions
    8. Return run_id

Error paths mark the Run with status=failed and error_message before raising
to preserve audit trail.

Example usage (Day 7 AppFactory wiring):
    >>> factory = AppFactory(settings)
    >>> simulator = factory.rebalance_simulator()
    >>> run_id = simulator.simulate(request)
    >>> record = factory.run_repo().find_by_id(run_id)
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from vn_portfolio_frontier.application.ports import (
    PriceRepository,
    RebalanceDecisionRepository,
    RebalanceRunRepository,
    RunRecord,
)
from vn_portfolio_frontier.domain.entities import (
    Portfolio,
    RebalanceContext,
    RebalanceDecision,
)
from vn_portfolio_frontier.domain.services import CostCalculator
from vn_portfolio_frontier.domain.strategies import BaseStrategy

# Strategy factory contract. Simulator passes (strategy_name, strategy_params,
# cost_calculator) and expects a configured BaseStrategy subclass. The
# cost_calculator is derived from request.brokerage_pct at simulate() time and
# must be wired by the factory into the strategy instance. Day 7 AppFactory
# will formalise the mapping from name -> concrete class.
StrategyFactory = Callable[[str, dict[str, Any], CostCalculator], BaseStrategy]

# Progress callback contract: (current_day, days_done, days_total).
# Streamlit UI subscribes to drive a progress bar. Pass None to disable.
ProgressCallback = Callable[[date, int, int], None]

# Vietnamese market trading days per year (approximate) for Sharpe annualisation.
TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class SimulateRequest:
    """Input contract for RebalanceSimulator.simulate().

    All config fields are required - no sensible defaults for a backtest. The
    __post_init__ validates (a) date range order, (b) target_weights sum ~ 1.0,
    (c) initial_capital positivity. More semantic validation (e.g., tickers
    exist in prices) happens inside simulate() where the price_repo is reachable.
    """

    # Portfolio
    target_weights: dict[str, float]
    initial_capital: Decimal

    # Backtest range
    backtest_start: date
    backtest_end: date

    # Strategy
    strategy_name: str
    strategy_params: dict[str, Any]

    # Cost model (ADR-012). brokerage_pct required; tax_pct and
    # market_impact_bps have Vietnamese-market defaults.
    brokerage_pct: Decimal

    # Reproducibility (NFR-R-07) - locked at run start, never mutated.
    git_commit_sha: str
    code_version: str

    tax_pct: Decimal = Decimal("0.001")
    market_impact_bps: int = 10

    def __post_init__(self) -> None:
        if self.backtest_start > self.backtest_end:
            raise ValueError(
                f"SimulateRequest: backtest_start ({self.backtest_start}) "
                f"> backtest_end ({self.backtest_end})"
            )
        total = sum(self.target_weights.values())
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"SimulateRequest: target_weights must sum to ~1.0, got {total:.4f}")
        if self.initial_capital <= Decimal("0"):
            raise ValueError(
                f"SimulateRequest: initial_capital must be positive, got " f"{self.initial_capital}"
            )


class RebalanceSimulator:
    """Orchestrator for Feature 2 end-to-end backtest with cost modeling.

    Instantiate once per application lifecycle via AppFactory (Day 7). Each
    simulate() call is independent - no cross-call state. Thread safety is a
    function of the injected repositories (Fake repos are not thread-safe;
    Neon adapters that use a per-call connection are).

    Parameters
    ----------
    price_repo : PriceRepository
        Reads bars for all target tickers upfront, keeps in memory for loop.
    run_repo : RebalanceRunRepository
        Saves initial Run record and transitions status throughout.
    decision_repo : RebalanceDecisionRepository
        Receives the final batch of decisions after the daily loop completes.
    strategy_factory : StrategyFactory
        Callable that maps (name, params, cost_calc) -> BaseStrategy instance.
    """

    def __init__(
        self,
        price_repo: PriceRepository,
        run_repo: RebalanceRunRepository,
        decision_repo: RebalanceDecisionRepository,
        strategy_factory: StrategyFactory,
    ) -> None:
        self._price_repo = price_repo
        self._run_repo = run_repo
        self._decision_repo = decision_repo
        self._strategy_factory = strategy_factory

    def simulate(
        self,
        request: SimulateRequest,
        on_progress: ProgressCallback | None = None,
    ) -> int:
        """Execute backtest end-to-end, persist Run + Decisions, return run_id.

        Parameters
        ----------
        request : SimulateRequest
            Fully-validated backtest configuration.
        on_progress : callable, optional
            Invoked once per processed trading day with
            (current_day, days_done, days_total). Defaults to None (no-op).

        Returns
        -------
        int
            BIGSERIAL run_id. Caller retrieves the full record via
            `run_repo.find_by_id(run_id)` and the decisions via
            `decision_repo.find_by_run(run_id)`.

        Raises
        ------
        ValueError
            - When no price data is available for any ticker (Run marked failed)
            - When strategy.rebalance() raises mid-loop (Run marked failed with
              the triggering day in the error message)
            - When Portfolio.apply_orders() raises - short-sell or over-budget
              per Day 2 Portfolio invariants (Run marked failed)
            - When the strategy_factory does not know `strategy_name`
        """
        initial_record = self._build_initial_record(request)
        run_id = self._run_repo.save(initial_record)

        try:
            price_history = self._load_price_history(request)
        except ValueError as exc:
            self._run_repo.update_status(run_id, status="failed", error_message=str(exc))
            raise

        trading_days = sorted({d for prices in price_history.values() for d in prices})

        cost_calculator = CostCalculator(
            brokerage_pct=request.brokerage_pct,
            market_impact_bps=request.market_impact_bps,
            tax_pct=request.tax_pct,
        )

        try:
            strategy = self._strategy_factory(
                request.strategy_name,
                dict(request.strategy_params),
                cost_calculator,
            )
        except ValueError as exc:
            self._run_repo.update_status(run_id, status="failed", error_message=str(exc))
            raise

        portfolio = Portfolio(
            cash=request.initial_capital,
            target_weights=dict(request.target_weights),
        )

        decisions, daily_values_after, daily_values_before = self._run_daily_loop(
            run_id=run_id,
            request=request,
            portfolio=portfolio,
            strategy=strategy,
            price_history=price_history,
            trading_days=trading_days,
            on_progress=on_progress,
        )

        kpis = self._compute_kpis(
            decisions=decisions,
            daily_values_after=daily_values_after,
            daily_values_before=daily_values_before,
        )

        self._run_repo.update_status(run_id, status="completed", kpis=kpis)
        self._decision_repo.save_batch(run_id, decisions)
        return run_id

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_initial_record(request: SimulateRequest) -> RunRecord:
        """Assemble a RunRecord with status='running' for initial persistence."""
        return RunRecord(
            brokerage_pct=request.brokerage_pct,
            tax_pct=request.tax_pct,
            market_impact_bps=request.market_impact_bps,
            strategy_name=request.strategy_name,
            strategy_params=dict(request.strategy_params),
            target_weights=dict(request.target_weights),
            backtest_start=request.backtest_start,
            backtest_end=request.backtest_end,
            git_commit_sha=request.git_commit_sha,
            code_version=request.code_version,
            initial_capital=request.initial_capital,
            status="running",
        )

    def _load_price_history(self, request: SimulateRequest) -> dict[str, dict[date, Decimal]]:
        """Pre-fetch close prices for every target ticker across the backtest range.

        One query per ticker (~43 max for VN30). Result is a nested dict for
        O(1) lookup inside the daily loop (vs re-querying 1250 x N tickers).
        """
        history: dict[str, dict[date, Decimal]] = {}
        for ticker in request.target_weights:
            bars = self._price_repo.get_ohlcv(
                ticker,
                start=request.backtest_start,
                end=request.backtest_end,
            )
            if not bars:
                raise ValueError(f"No price data for ticker {ticker}")
            history[ticker] = {bar.trade_date: bar.close for bar in bars}
        return history

    def _run_daily_loop(
        self,
        *,
        run_id: int,
        request: SimulateRequest,
        portfolio: Portfolio,
        strategy: BaseStrategy,
        price_history: dict[str, dict[date, Decimal]],
        trading_days: list[date],
        on_progress: ProgressCallback | None,
    ) -> tuple[list[RebalanceDecision], list[Decimal], list[Decimal]]:
        """Iterate trading days: build context, call strategy, apply orders.

        Also captures daily portfolio values before and after cost drag for
        Sharpe computation downstream.
        """
        decisions: list[RebalanceDecision] = []
        daily_values_after: list[Decimal] = []
        daily_values_before: list[Decimal] = []
        cumulative_cost = Decimal("0")
        last_rebalance_date: date | None = None
        total_days = len(trading_days)

        for i, day in enumerate(trading_days):
            prices_today = {
                ticker: price_history[ticker][day]
                for ticker in request.target_weights
                if day in price_history[ticker]
            }
            if not prices_today:
                if on_progress is not None:
                    on_progress(day, i + 1, total_days)
                continue

            context = RebalanceContext(
                as_of=day,
                prices=prices_today,
                last_rebalance_date=last_rebalance_date,
            )

            try:
                decision = strategy.rebalance(portfolio, context)
            except ValueError as exc:
                self._run_repo.update_status(
                    run_id,
                    status="failed",
                    error_message=f"Strategy raised at {day}: {exc}",
                )
                raise

            if decision.is_action:
                try:
                    portfolio.apply_orders(decision.orders)
                except ValueError as exc:
                    self._run_repo.update_status(
                        run_id,
                        status="failed",
                        error_message=f"Portfolio.apply_orders raised at {day}: {exc}",
                    )
                    raise
                last_rebalance_date = day
                cumulative_cost += decision.costs.total()

            decisions.append(decision)

            v_after = portfolio.total_value(prices_today)
            v_before = v_after + cumulative_cost
            daily_values_after.append(v_after)
            daily_values_before.append(v_before)

            if on_progress is not None:
                on_progress(day, i + 1, total_days)

        return decisions, daily_values_after, daily_values_before

    @staticmethod
    def _compute_kpis(
        decisions: list[RebalanceDecision],
        daily_values_after: list[Decimal],
        daily_values_before: list[Decimal],
    ) -> dict[str, Any]:
        """Aggregate output KPIs from the daily loop results.

        KPI definitions:
            - n_rebalances: count of action decisions (strategy triggered)
            - total_cost_bps: aggregate cost / aggregate gross trade value,
              expressed in basis points (bps). 0 when no rebalances.
            - turnover_avg_pct: mean of sum(|delta_weight|) across rebalances
            - sharpe_before_cost / sharpe_after_cost: see _sharpe() docstring
        """
        action_decisions = [d for d in decisions if d.is_action]
        n_rebalances = len(action_decisions)

        if action_decisions:
            total_gross = sum(
                (order.gross_amount() for d in action_decisions for order in d.orders),
                start=Decimal("0"),
            )
            total_cost = sum((d.costs.total() for d in action_decisions), start=Decimal("0"))
            total_cost_bps = (
                int((total_cost / total_gross) * Decimal(10000)) if total_gross > 0 else 0
            )
            turnovers = [
                sum(
                    abs(d.weights_after.get(t, 0.0) - d.weights_before.get(t, 0.0))
                    for t in set(d.weights_before) | set(d.weights_after)
                )
                for d in action_decisions
            ]
            turnover_avg_pct = Decimal(str(sum(turnovers) / len(turnovers))).quantize(
                Decimal("0.0001")
            )
        else:
            total_cost_bps = 0
            turnover_avg_pct = Decimal("0.0000")

        return {
            "n_rebalances": n_rebalances,
            "total_cost_bps": total_cost_bps,
            "turnover_avg_pct": turnover_avg_pct,
            "sharpe_before_cost": _sharpe(daily_values_before),
            "sharpe_after_cost": _sharpe(daily_values_after),
        }


def _sharpe(values: list[Decimal]) -> Decimal | None:
    """Annualised Sharpe ratio with risk-free rate = 0.

    Standard thesis simplification per Perold (1988) - more rigorous
    computation would subtract a risk-free rate (Vietnam 3M T-bill ~3-4% p.a.
    in 2026). Rf is parameterised in the F1 Efficient Frontier module and
    reused there when a per-run Sharpe is recomputed with Rf > 0.

    Methodology:
        returns[i] = (V[i] - V[i-1]) / V[i-1]           # daily simple returns
        mean, sample_std = statistics of returns
        sharpe = (mean / sample_std) * sqrt(252)        # annualised, Rf=0

    Returns None (-> NULL in DB) when the input has < 2 values or when the
    sample standard deviation is zero (e.g., 1-day backtest, flat value series).
    """
    if len(values) < 2:
        return None
    returns = [float((values[i] - values[i - 1]) / values[i - 1]) for i in range(1, len(values))]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    sharpe_annualised = (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)
    return Decimal(str(sharpe_annualised)).quantize(Decimal("0.0001"))
