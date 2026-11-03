"""Unit tests cho CalendarMonthlyStrategy + FixedWindowStrategy.

Covers:
    - Bootstrap trigger (last_rebalance_date=None)
    - Trigger / no-trigger cases per strategy logic
    - Static target weights returned unchanged
    - Reason label matches migration 009 CHECK constraint
    - Guard rail validation (FixedWindow window_days range)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from vn_portfolio_frontier.domain.entities.portfolio import Portfolio
from vn_portfolio_frontier.domain.entities.rebalance_context import RebalanceContext
from vn_portfolio_frontier.domain.strategies.periodic import (
    DEFAULT_WINDOW_DAYS,
    CalendarMonthlyStrategy,
    FixedWindowStrategy,
)


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def cost_calculator():
    """Mock CostCalculator -- periodic strategies don't invoke it in should_trigger."""
    return MagicMock()


@pytest.fixture
def portfolio():
    """Minimal Portfolio with 2 target weights."""
    return Portfolio(
        holdings={},  # empty -- strategies don't use for should_trigger
        target_weights={"VCB": 0.5, "FPT": 0.5},
        cash=Decimal("100000000"),
    )


def _make_context(as_of: date, last_rebalance: date | None = None) -> RebalanceContext:
    """Build minimal RebalanceContext fixture."""
    return RebalanceContext(
        as_of=as_of,
        prices={"VCB": Decimal("90000"), "FPT": Decimal("120000")},
        last_rebalance_date=last_rebalance,
    )


# ============================================================
# CalendarMonthlyStrategy
# ============================================================
class TestCalendarMonthlyStrategy:
    def test_name_and_reason_labels(self, cost_calculator):
        strategy = CalendarMonthlyStrategy(cost_calculator)
        assert strategy.name == "calendar_monthly"
        assert strategy._reason() == "calendar"  # noqa: SLF001

    def test_bootstrap_triggers_with_last_none(self, cost_calculator, portfolio):
        strategy = CalendarMonthlyStrategy(cost_calculator)
        context = _make_context(as_of=date(2026, 1, 15), last_rebalance=None)
        assert strategy.should_trigger(portfolio, {}, context) is True

    def test_same_month_no_trigger(self, cost_calculator, portfolio):
        strategy = CalendarMonthlyStrategy(cost_calculator)
        context = _make_context(
            as_of=date(2026, 1, 20),
            last_rebalance=date(2026, 1, 15),
        )
        assert strategy.should_trigger(portfolio, {}, context) is False

    def test_new_month_triggers(self, cost_calculator, portfolio):
        strategy = CalendarMonthlyStrategy(cost_calculator)
        context = _make_context(
            as_of=date(2026, 2, 2),
            last_rebalance=date(2026, 1, 20),
        )
        assert strategy.should_trigger(portfolio, {}, context) is True

    def test_cross_year_triggers(self, cost_calculator, portfolio):
        """Dec -> Jan next year -- month 12 != 1, trigger."""
        strategy = CalendarMonthlyStrategy(cost_calculator)
        context = _make_context(
            as_of=date(2027, 1, 2),
            last_rebalance=date(2026, 12, 15),
        )
        assert strategy.should_trigger(portfolio, {}, context) is True

    def test_target_weights_returned_unchanged(self, cost_calculator, portfolio):
        strategy = CalendarMonthlyStrategy(cost_calculator)
        context = _make_context(as_of=date(2026, 1, 15))
        target = strategy.compute_target_weights(portfolio, context)
        assert target == {"VCB": 0.5, "FPT": 0.5}

    def test_target_weights_shallow_copy_isolated(self, cost_calculator, portfolio):
        """Mutate returned dict should not affect source Portfolio."""
        strategy = CalendarMonthlyStrategy(cost_calculator)
        context = _make_context(as_of=date(2026, 1, 15))
        target = strategy.compute_target_weights(portfolio, context)
        target["VCB"] = 0.99
        assert portfolio.target_weights["VCB"] == 0.5


# ============================================================
# FixedWindowStrategy
# ============================================================
class TestFixedWindowStrategy:
    def test_name_and_reason_labels(self, cost_calculator):
        strategy = FixedWindowStrategy(cost_calculator)
        assert strategy.name == "fixed_window"
        assert strategy._reason() == "window"  # noqa: SLF001

    def test_default_window_is_90_days(self, cost_calculator):
        strategy = FixedWindowStrategy(cost_calculator)
        assert strategy.window_days == DEFAULT_WINDOW_DAYS == 90

    def test_bootstrap_triggers_with_last_none(self, cost_calculator, portfolio):
        strategy = FixedWindowStrategy(cost_calculator, window_days=90)
        context = _make_context(as_of=date(2026, 1, 15), last_rebalance=None)
        assert strategy.should_trigger(portfolio, {}, context) is True

    def test_within_window_no_trigger(self, cost_calculator, portfolio):
        """31 days elapsed, window=90 -> no trigger."""
        strategy = FixedWindowStrategy(cost_calculator, window_days=90)
        context = _make_context(
            as_of=date(2026, 2, 1),
            last_rebalance=date(2026, 1, 1),
        )
        assert strategy.should_trigger(portfolio, {}, context) is False

    def test_exact_window_boundary_triggers(self, cost_calculator, portfolio):
        """Exactly 90 days elapsed, window=90 -> trigger (>= boundary)."""
        strategy = FixedWindowStrategy(cost_calculator, window_days=90)
        context = _make_context(
            as_of=date(2026, 4, 1),  # 90 days after 2026-01-01
            last_rebalance=date(2026, 1, 1),
        )
        elapsed = (context.as_of - context.last_rebalance_date).days
        assert elapsed == 90
        assert strategy.should_trigger(portfolio, {}, context) is True

    def test_beyond_window_triggers(self, cost_calculator, portfolio):
        strategy = FixedWindowStrategy(cost_calculator, window_days=90)
        context = _make_context(
            as_of=date(2026, 5, 1),  # 120 days after
            last_rebalance=date(2026, 1, 1),
        )
        assert strategy.should_trigger(portfolio, {}, context) is True

    def test_custom_window_30_days_monthly(self, cost_calculator, portfolio):
        strategy = FixedWindowStrategy(cost_calculator, window_days=30)
        context = _make_context(
            as_of=date(2026, 2, 1),  # 31 days after
            last_rebalance=date(2026, 1, 1),
        )
        assert strategy.should_trigger(portfolio, {}, context) is True

    def test_custom_window_180_days_semiannual(self, cost_calculator, portfolio):
        strategy = FixedWindowStrategy(cost_calculator, window_days=180)
        context = _make_context(
            as_of=date(2026, 4, 1),  # 90 days after
            last_rebalance=date(2026, 1, 1),
        )
        assert strategy.should_trigger(portfolio, {}, context) is False

    def test_window_days_below_min_raises(self, cost_calculator):
        with pytest.raises(ValueError, match="window_days must be in"):
            FixedWindowStrategy(cost_calculator, window_days=0)

    def test_window_days_above_max_raises(self, cost_calculator):
        with pytest.raises(ValueError, match="window_days must be in"):
            FixedWindowStrategy(cost_calculator, window_days=366)

    def test_target_weights_returned_unchanged(self, cost_calculator, portfolio):
        strategy = FixedWindowStrategy(cost_calculator)
        context = _make_context(as_of=date(2026, 1, 15))
        target = strategy.compute_target_weights(portfolio, context)
        assert target == {"VCB": 0.5, "FPT": 0.5}

    def test_target_weights_shallow_copy_isolated(self, cost_calculator, portfolio):
        strategy = FixedWindowStrategy(cost_calculator)
        context = _make_context(as_of=date(2026, 1, 15))
        target = strategy.compute_target_weights(portfolio, context)
        target["FPT"] = 0.99
        assert portfolio.target_weights["FPT"] == 0.5
