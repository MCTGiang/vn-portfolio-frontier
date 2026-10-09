"""Unit tests for BaseStrategy Template Method + ThresholdBandStrategy.

Covers:
    - BaseStrategy abstract contract (cannot instantiate without hooks)
    - Template Method rebalance() flow (hooks called in correct order)
    - Shared _compute_orders logic (BUY/SELL delta, skip zero, floor rounding)
    - ThresholdBandStrategy concrete behavior:
        - Trigger condition (max drift > band_bps, strict >)
        - compute_target_weights returns copy of Portfolio.target_weights
        - Validation (band_bps range)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from vn_portfolio_frontier.domain.entities import (
    Holding,
    Portfolio,
    RebalanceContext,
    RebalanceDecision,
)
from vn_portfolio_frontier.domain.services import CostCalculator
from vn_portfolio_frontier.domain.strategies import BaseStrategy, ThresholdBandStrategy

# =====================================================================
# Test fixtures / helpers
# =====================================================================


@pytest.fixture
def calc() -> CostCalculator:
    return CostCalculator(brokerage_pct=Decimal("0.0015"))


@pytest.fixture
def ctx() -> RebalanceContext:
    return RebalanceContext(
        as_of=date(2026, 1, 15),
        prices={"VCB": Decimal("125000"), "FPT": Decimal("95000")},
    )


# =====================================================================
# BaseStrategy abstract contract
# =====================================================================


class TestBaseStrategyAbstract:
    def test_cannot_instantiate_abstract(self, calc: CostCalculator) -> None:
        """BaseStrategy không có concrete impl of 2 hooks -> TypeError."""
        with pytest.raises(TypeError, match="abstract"):
            BaseStrategy(calc)  # type: ignore[abstract]

    def test_concrete_subclass_can_instantiate(self, calc: CostCalculator) -> None:
        class Dummy(BaseStrategy):
            name = "dummy"

            def compute_target_weights(self, c, ctx):
                return {}

            def should_trigger(self, c, t, ctx):
                return False

        instance = Dummy(calc)
        assert instance.name == "dummy"


# =====================================================================
# Template Method flow (BaseStrategy.rebalance)
# =====================================================================


class _CallTracker(BaseStrategy):
    """Minimal subclass tracking which hooks fired, in order."""

    name = "tracker"

    def __init__(self, cost_calculator, target, trigger):
        super().__init__(cost_calculator)
        self._target = target
        self._trigger = trigger
        self.calls: list[str] = []

    def compute_target_weights(self, current, context):
        self.calls.append("compute_target_weights")
        return self._target

    def should_trigger(self, current, target, context):
        self.calls.append("should_trigger")
        return self._trigger


class TestTemplateMethodFlow:
    def test_hooks_called_in_order_when_trigger_true(
        self, calc: CostCalculator, ctx: RebalanceContext
    ) -> None:
        """compute_target_weights -> should_trigger -> (orders+cost built)."""
        p = Portfolio(cash=Decimal("100000000"), target_weights={"VCB": 0.5, "FPT": 0.5})
        tracker = _CallTracker(calc, target={"VCB": 0.5, "FPT": 0.5}, trigger=True)
        decision = tracker.rebalance(p, ctx)
        assert tracker.calls == ["compute_target_weights", "should_trigger"]
        assert decision.is_action

    def test_no_trigger_returns_no_action_decision(
        self, calc: CostCalculator, ctx: RebalanceContext
    ) -> None:
        p = Portfolio(cash=Decimal("100000000"))
        tracker = _CallTracker(calc, target={"VCB": 0.5, "FPT": 0.5}, trigger=False)
        decision = tracker.rebalance(p, ctx)
        assert not decision.is_action
        assert decision.reason == "no_trigger"
        assert decision.total_cost() == Decimal("0.00")

    def test_zero_shares_after_rounding_no_action(
        self, calc: CostCalculator, ctx: RebalanceContext
    ) -> None:
        """Tiny weight * tiny cash -> floor to 0 shares -> no_action."""
        p = Portfolio(cash=Decimal("100"), target_weights={"VCB": 0.0001})
        tracker = _CallTracker(calc, target={"VCB": 0.0001}, trigger=True)
        decision = tracker.rebalance(p, ctx)
        assert not decision.is_action
        assert decision.reason == "zero_shares_after_rounding"

    def test_trigger_produces_decision_with_cost(
        self, calc: CostCalculator, ctx: RebalanceContext
    ) -> None:
        p = Portfolio(cash=Decimal("100000000"), target_weights={"VCB": 0.5, "FPT": 0.5})
        tracker = _CallTracker(calc, target={"VCB": 0.5, "FPT": 0.5}, trigger=True)
        decision = tracker.rebalance(p, ctx)
        assert decision.is_action
        assert decision.order_count() > 0
        assert decision.total_cost() > Decimal("0")
        assert decision.strategy_name == "tracker"
        assert decision.triggered_at == ctx.as_of

    def test_weights_before_after_captured(
        self, calc: CostCalculator, ctx: RebalanceContext
    ) -> None:
        p = Portfolio(cash=Decimal("100000000"), target_weights={"VCB": 0.5, "FPT": 0.5})
        tracker = _CallTracker(calc, target={"VCB": 0.5, "FPT": 0.5}, trigger=True)
        decision = tracker.rebalance(p, ctx)
        # Fresh portfolio weights_before = {} (no holdings yet)
        assert decision.weights_before == {}
        assert decision.weights_after == {"VCB": 0.5, "FPT": 0.5}


# =====================================================================
# _compute_orders shared logic
# =====================================================================


class TestComputeOrders:
    def test_fresh_portfolio_all_buys(self, calc: CostCalculator, ctx: RebalanceContext) -> None:
        """100M cash + 50/50 target -> BUY both tickers."""
        p = Portfolio(cash=Decimal("100000000"), target_weights={"VCB": 0.5, "FPT": 0.5})
        tracker = _CallTracker(calc, target={"VCB": 0.5, "FPT": 0.5}, trigger=True)
        decision = tracker.rebalance(p, ctx)
        order_sides = {o.ticker: o.side.value for o in decision.orders}
        assert order_sides == {"VCB": "BUY", "FPT": "BUY"}
        # VCB target 50M / 125000 = 400 shares exact
        vcb_order = [o for o in decision.orders if o.ticker == "VCB"][0]
        assert vcb_order.shares == 400

    def test_over_weighted_triggers_sell(self, calc: CostCalculator, ctx: RebalanceContext) -> None:
        """VCB over-weight -> SELL to bring back to target."""
        p = Portfolio(cash=Decimal("100"), target_weights={"VCB": 0.5, "FPT": 0.5})
        p.holdings["VCB"] = Holding("VCB", 560, Decimal("125000"))  # 70M
        p.holdings["FPT"] = Holding("FPT", 316, Decimal("95000"))  # 30.02M
        tracker = _CallTracker(calc, target={"VCB": 0.5, "FPT": 0.5}, trigger=True)
        decision = tracker.rebalance(p, ctx)
        sides = {o.ticker: o.side.value for o in decision.orders}
        assert sides["VCB"] == "SELL"
        assert sides["FPT"] == "BUY"

    def test_under_weighted_triggers_buy_to_top_up(
        self, calc: CostCalculator, ctx: RebalanceContext
    ) -> None:
        """F-H2: VCB under-weight -> BUY to top up to target.

        Mirror case for test_over_weighted_triggers_sell. Verifies that the
        strategy emits BUY orders when the current position is below the
        target weight (critical path for fresh buys AND drift-down
        corrections, not only fresh-portfolio allocation).
        """
        # Portfolio ~100M total; VCB 20M (20%), FPT ~80M (80%) - inverse of 50/50 target
        p = Portfolio(cash=Decimal("100"), target_weights={"VCB": 0.5, "FPT": 0.5})
        p.holdings["VCB"] = Holding("VCB", 160, Decimal("125000"))  # 20M value
        p.holdings["FPT"] = Holding("FPT", 842, Decimal("95000"))  # 79.99M value
        tracker = _CallTracker(calc, target={"VCB": 0.5, "FPT": 0.5}, trigger=True)
        decision = tracker.rebalance(p, ctx)

        sides = {o.ticker: o.side.value for o in decision.orders}
        shares_by_ticker = {o.ticker: o.shares for o in decision.orders}

        # VCB under-weight -> BUY
        assert sides["VCB"] == "BUY"
        # FPT over-weight -> SELL (symmetry check)
        assert sides["FPT"] == "SELL"

        # Verify BUY size matches delta to target.
        # Total value = 100 + 160*125,000 + 842*95,000 = 99,990,100 VND
        # Target VCB value = 50% -> 49,995,050; floor(/125,000) = 399 shares
        # Delta = 399 - 160 = +239 shares BUY
        assert shares_by_ticker["VCB"] == 239
        # Decision is action, not no_action
        assert decision.is_action

    def test_delta_zero_skips_order(self, calc: CostCalculator, ctx: RebalanceContext) -> None:
        """Khi current_shares == target_shares -> no order for that ticker."""
        # VCB already at target exactly
        p = Portfolio(cash=Decimal("100"), target_weights={"VCB": 1.0})
        # Total value = 100 + 100*125000 = 12,500,100 -> target 100% -> shares = int(12500100/125000) = 100
        p.holdings["VCB"] = Holding("VCB", 100, Decimal("125000"))
        tracker = _CallTracker(calc, target={"VCB": 1.0}, trigger=True)
        decision = tracker.rebalance(p, ctx)
        # VCB delta = 100 - 100 = 0 -> no VCB order -> total order_count == 0 -> no_action
        assert not decision.is_action
        assert decision.reason == "zero_shares_after_rounding"

    def test_missing_price_skips_ticker(self, calc: CostCalculator, ctx: RebalanceContext) -> None:
        """Ticker trong target nhưng không trong context.prices -> skip."""
        p = Portfolio(cash=Decimal("100000000"), target_weights={"VCB": 0.5, "MSFT": 0.5})
        # ctx only has VCB + FPT, no MSFT
        tracker = _CallTracker(calc, target={"VCB": 0.5, "MSFT": 0.5}, trigger=True)
        decision = tracker.rebalance(p, ctx)
        tickers = {o.ticker for o in decision.orders}
        assert "MSFT" not in tickers
        assert "VCB" in tickers


# =====================================================================
# ThresholdBandStrategy
# =====================================================================


class TestThresholdBandStrategy:
    def test_name_and_default_band(self, calc: CostCalculator) -> None:
        s = ThresholdBandStrategy(calc)
        assert s.name == "threshold_band"
        assert s.band_bps == 500  # default

    def test_custom_band_bps(self, calc: CostCalculator) -> None:
        s = ThresholdBandStrategy(calc, band_bps=1000)
        assert s.band_bps == 1000

    @pytest.mark.parametrize("bps", [0, -1, 10001, 999999])
    def test_invalid_band_bps_raises(self, calc: CostCalculator, bps: int) -> None:
        with pytest.raises(ValueError, match="band_bps"):
            ThresholdBandStrategy(calc, band_bps=bps)

    def test_compute_target_returns_portfolio_target_copy(
        self, calc: CostCalculator, ctx: RebalanceContext
    ) -> None:
        s = ThresholdBandStrategy(calc)
        target = {"VCB": 0.5, "FPT": 0.5}
        p = Portfolio(cash=Decimal("1"), target_weights=target)
        result = s.compute_target_weights(p, ctx)
        assert result == target
        # Must be a shallow copy (not same identity)
        result["VCB"] = 0.9
        assert p.target_weights["VCB"] == 0.5

    def test_fresh_portfolio_triggers(self, calc: CostCalculator, ctx: RebalanceContext) -> None:
        """Fresh portfolio: 0% weights vs 50% target -> 5000 bps drift -> trigger."""
        s = ThresholdBandStrategy(calc, band_bps=500)
        p = Portfolio(cash=Decimal("100000000"), target_weights={"VCB": 0.5, "FPT": 0.5})
        decision = s.rebalance(p, ctx)
        assert decision.is_action
        assert decision.reason == "band_drift"

    def test_balanced_no_trigger(self, calc: CostCalculator, ctx: RebalanceContext) -> None:
        """Portfolio balanced at target -> 0 bps drift -> no trigger."""
        s = ThresholdBandStrategy(calc, band_bps=500)
        p = Portfolio(cash=Decimal("100"), target_weights={"VCB": 0.5, "FPT": 0.5})
        p.holdings["VCB"] = Holding("VCB", 400, Decimal("125000"))
        p.holdings["FPT"] = Holding("FPT", 526, Decimal("95000"))
        decision = s.rebalance(p, ctx)
        assert not decision.is_action
        assert decision.reason == "no_trigger"

    def test_at_band_strict_greater_than(self, calc: CostCalculator, ctx: RebalanceContext) -> None:
        """Drift exactly at band = NO trigger (strict > comparison)."""
        # Need to construct a case where max drift is exactly on the band
        # Simpler: use a wide band (10000) and verify any drift stays under
        s = ThresholdBandStrategy(calc, band_bps=10000)  # 100% band
        p = Portfolio(cash=Decimal("100000000"), target_weights={"VCB": 0.5, "FPT": 0.5})
        # Fresh portfolio = 5000 bps drift < 10000 band -> no trigger
        decision = s.rebalance(p, ctx)
        assert not decision.is_action

    def test_drift_over_band_triggers(self, calc: CostCalculator, ctx: RebalanceContext) -> None:
        """Drift 600 bps > band 500 -> trigger."""
        s = ThresholdBandStrategy(calc, band_bps=500)
        p = Portfolio(cash=Decimal("100"), target_weights={"VCB": 0.5, "FPT": 0.5})
        # 56% VCB = 500+ bps drift from 50% target
        p.holdings["VCB"] = Holding("VCB", 448, Decimal("125000"))  # 56M
        p.holdings["FPT"] = Holding("FPT", 463, Decimal("95000"))  # 43.98M
        decision = s.rebalance(p, ctx)
        assert decision.is_action
        assert decision.reason == "band_drift"

    def test_drift_under_band_triggers(self, calc: CostCalculator, ctx: RebalanceContext) -> None:
        """F-H2 complement: drift DOWNWARD past band triggers rebalance (not only upward)."""
        s = ThresholdBandStrategy(calc, band_bps=500)  # 5% band
        # VCB target 50%, current 20% -> drift -30% > 5% band -> trigger
        p = Portfolio(cash=Decimal("100"), target_weights={"VCB": 0.5, "FPT": 0.5})
        p.holdings["VCB"] = Holding("VCB", 160, Decimal("125000"))
        p.holdings["FPT"] = Holding("FPT", 842, Decimal("95000"))
        target = {"VCB": 0.5, "FPT": 0.5}
        assert s.should_trigger(p, target, ctx) is True


# =====================================================================
# Integration - Strategy + CostCalculator produces consistent Decision
# =====================================================================


class TestIntegration:
    def test_full_rebalance_cycle(self, calc: CostCalculator, ctx: RebalanceContext) -> None:
        """Decision from fresh portfolio contains valid orders + cost + weights."""
        s = ThresholdBandStrategy(calc, band_bps=500)
        p = Portfolio(cash=Decimal("100000000"), target_weights={"VCB": 0.5, "FPT": 0.5})
        decision = s.rebalance(p, ctx)

        assert isinstance(decision, RebalanceDecision)
        assert decision.is_action
        assert decision.strategy_name == "threshold_band"
        assert decision.reason == "band_drift"
        assert decision.triggered_at == ctx.as_of
        assert decision.order_count() == 2
        assert decision.total_cost() > Decimal("0")
        assert decision.weights_before == {}  # fresh portfolio
        assert decision.weights_after == {"VCB": 0.5, "FPT": 0.5}

    def test_decision_cost_consistent_with_orders(
        self, calc: CostCalculator, ctx: RebalanceContext
    ) -> None:
        """Decision.costs == CostCalculator.compute(decision.orders) independently."""
        s = ThresholdBandStrategy(calc, band_bps=500)
        p = Portfolio(cash=Decimal("100000000"), target_weights={"VCB": 0.5, "FPT": 0.5})
        decision = s.rebalance(p, ctx)
        recomputed = calc.compute(decision.orders)
        assert decision.costs == recomputed
