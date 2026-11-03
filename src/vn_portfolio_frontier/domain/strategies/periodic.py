"""Periodic rebalance strategies -- time-based triggers.

Two subclasses of BaseStrategy implementing scheduled rebalance:

- CalendarMonthlyStrategy: trigger on first simulation day of each new calendar
  month (routine investor convention).
- FixedWindowStrategy: trigger when `window_days` calendar days elapsed since
  last rebalance (default 90 days ~= quarterly).

Design notes:
    - Stateless: both strategies derive trigger decision from
      `context.last_rebalance_date` (RebalanceContext field) -- no internal state,
      follows functional convention of ThresholdBandStrategy.
    - Static target: `compute_target_weights` returns Portfolio.target_weights
      unchanged (same as ThresholdBand). Alternative: recompute from Markowitz
      covariance each trigger -> defer DATN (adds complexity + FrontierOptimizer
      injection).
    - Reason labels match migration 009 CHECK constraint chk_decision_reason_known:
      "calendar" for CalendarMonthlyStrategy, "window" for FixedWindowStrategy.
    - Calendar days (not trading days) in FixedWindow for simplicity. 90 calendar
      days ~= 63 trading days ~= 1 quarter. Trading-day counting would require
      HOSE calendar lookup -> defer DATN.

Trade-offs:
    - Pros: trivially stateless + testable; routine investor UX; low rebalance
      frequency -> lower transaction cost than ThresholdBand.
    - Cons: not responsive to intraday drift (positions can drift significantly
      mid-month); fixed cadence may miss optimal rebalance moments.

Patterns considered + rejected cho F2 periodic strategies:
    - Observer (event-driven on price updates): rebalance in P2 is scheduled,
      not event-driven. Deferred to DATN.
    - State (strategy transitions after trigger): all periodic strategies are
      pure -- same behavior regardless of history length.
"""

from __future__ import annotations

from vn_portfolio_frontier.domain.entities.portfolio import Portfolio
from vn_portfolio_frontier.domain.entities.rebalance_context import RebalanceContext
from vn_portfolio_frontier.domain.services.cost_calculator import CostCalculator
from vn_portfolio_frontier.domain.strategies.base import BaseStrategy

# Default window for FixedWindowStrategy -- 90 calendar days ~= quarterly rebalance
DEFAULT_WINDOW_DAYS = 90

# Guard rails for window_days parameter
_MIN_WINDOW_DAYS = 1
_MAX_WINDOW_DAYS = 365  # 1 year sanity cap


class CalendarMonthlyStrategy(BaseStrategy):
    """Rebalance on first simulation day of each new calendar month.

    Trigger logic:
        - Bootstrap (first ever iteration, last_rebalance_date=None): always trigger
        - Subsequent: trigger when `context.as_of.month` differs from
          `context.last_rebalance_date.month`

    Target weights: static -- returns Portfolio.target_weights unchanged (same
    convention as ThresholdBandStrategy; recomputation deferred to DATN).

    Example:
        - Setup: 2026-01-15 Portfolio{VCB: 50%, FPT: 50%} created
        - 2026-01-15 -> bootstrap trigger (last=None), rebalance
        - 2026-01-16 -> same month 01, no trigger
        - 2026-01-31 -> same month 01, no trigger
        - 2026-02-02 -> month 02 != last 01, trigger (first day of February)
    """

    name = "calendar_monthly"

    def __init__(self, cost_calculator: CostCalculator) -> None:
        super().__init__(cost_calculator)

    def compute_target_weights(
        self,
        current: Portfolio,
        context: RebalanceContext,
    ) -> dict[str, float]:
        """Return Portfolio.target_weights unchanged (static strategy)."""
        return dict(current.target_weights)

    def should_trigger(
        self,
        current: Portfolio,
        target: dict[str, float],
        context: RebalanceContext,
    ) -> bool:
        """Return True if current month differs from last rebalance month."""
        if context.last_rebalance_date is None:
            return True  # bootstrap
        return context.as_of.month != context.last_rebalance_date.month

    def _reason(self) -> str:
        """Return 'calendar' per migration 009 CHECK constraint."""
        return "calendar"


class FixedWindowStrategy(BaseStrategy):
    """Rebalance when window_days calendar days elapsed since last rebalance.

    Trigger logic:
        - Bootstrap (first ever iteration, last_rebalance_date=None): always trigger
        - Subsequent: trigger when
          (context.as_of - context.last_rebalance_date).days >= window_days

    Parameters
    ----------
    cost_calculator : CostCalculator
        Injected cost service for the base class.
    window_days : int, default 90
        Calendar days between rebalances. Default 90 ~= quarterly (63 trading
        days). Common alternatives: 30 (monthly), 180 (semi-annual).

    Example:
        - 2026-01-01 -> bootstrap trigger (last=None), rebalance
        - 2026-02-01 -> 31 days elapsed, window=90 -> no trigger (31 < 90)
        - 2026-04-01 -> 90 days elapsed, window=90 -> trigger (exact boundary)
        - 2026-07-01 -> 91 days since 2026-04-01, trigger
    """

    name = "fixed_window"

    def __init__(
        self,
        cost_calculator: CostCalculator,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ) -> None:
        super().__init__(cost_calculator)
        if not (_MIN_WINDOW_DAYS <= window_days <= _MAX_WINDOW_DAYS):
            raise ValueError(
                f"FixedWindowStrategy.window_days must be in "
                f"[{_MIN_WINDOW_DAYS}, {_MAX_WINDOW_DAYS}], got {window_days}. "
                f"Hint: 30=monthly, 90=quarterly, 180=semi-annual."
            )
        self.window_days = window_days

    def compute_target_weights(
        self,
        current: Portfolio,
        context: RebalanceContext,
    ) -> dict[str, float]:
        """Return Portfolio.target_weights unchanged (static strategy)."""
        return dict(current.target_weights)

    def should_trigger(
        self,
        current: Portfolio,
        target: dict[str, float],
        context: RebalanceContext,
    ) -> bool:
        """Return True if elapsed days since last rebalance >= window_days."""
        if context.last_rebalance_date is None:
            return True  # bootstrap
        elapsed = (context.as_of - context.last_rebalance_date).days
        return elapsed >= self.window_days

    def _reason(self) -> str:
        """Return 'window' per migration 009 CHECK constraint."""
        return "window"
