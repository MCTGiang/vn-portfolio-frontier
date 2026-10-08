"""Unit tests for domain entities (Sprint 11 Day 2).

Covers all 6 entity files in src/vn_portfolio_frontier/domain/entities/.
Tests isolate from Neon + external APIs — pure in-memory computation only.

Test organization:
    - One class per entity
    - Mix of concrete-example tests (edge cases, documented examples) and
      hypothesis property-based tests (invariants across the input space)
    - Each class has: happy path, validation errors, boundary cases
    - Portfolio class has the most tests (VWAP, weights, cash flow,
      short-sell rejection, budget exhaustion)

Why property-based tests here:
    - Validation invariants are universal (e.g. Holding.shares < 0 must
      always raise, regardless of ticker/avg_cost): hypothesis explores
      the input space faster than hand-written cases
    - Decimal arithmetic has edge cases around precision + sign + zero
      that example-based tests miss
    - Portfolio VWAP math and apply_orders cash flow are stateful;
      hypothesis-generated sequences catch ordering bugs

Not covered yet (Day 3+ scope):
    - BaseStrategy Template Method flow (Day 3)
    - CostCalculator computations (Day 3)
    - RebalanceSimulator orchestration (Day 6)
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vn_portfolio_frontier.domain.entities import (
    DailyPrice,
    Holding,
    Order,
    OrderSide,
    Portfolio,
    RebalanceContext,
    RebalanceDecision,
    TradingCost,
)

# =====================================================================
# Hypothesis strategies (shared helpers)
# =====================================================================

# Vietnamese tickers are 3-letter uppercase (VCB, FPT, VNM, ...)
tickers = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=3, max_size=3)

# Prices in a realistic VND range (1000 - 500000 per share for VN30)
prices_decimal = st.decimals(
    min_value=Decimal("1000"),
    max_value=Decimal("500000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Positive share counts (bounded to avoid Decimal overflow in large products)
positive_shares = st.integers(min_value=1, max_value=1_000_000)

# Non-negative Decimal cost components (bounded)
non_negative_cost = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("10000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


# =====================================================================
# Order + OrderSide
# =====================================================================


class TestOrder:
    def test_valid_order_gross_amount(self) -> None:
        buy = Order("VCB", OrderSide.BUY, 100, Decimal("125000"))
        assert buy.gross_amount() == Decimal("12500000")

    def test_order_is_frozen(self) -> None:
        buy = Order("VCB", OrderSide.BUY, 100, Decimal("125000"))
        with pytest.raises(FrozenInstanceError):
            buy.shares = 200  # type: ignore[misc]

    def test_order_equality_by_content(self) -> None:
        a = Order("VCB", OrderSide.BUY, 100, Decimal("125000"))
        b = Order("VCB", OrderSide.BUY, 100, Decimal("125000"))
        assert a == b
        assert hash(a) == hash(b)

    @pytest.mark.parametrize(
        "ticker,side,shares,price,msg",
        [
            ("", OrderSide.BUY, 100, Decimal("125000"), "ticker"),
            ("VCB", OrderSide.BUY, 0, Decimal("125000"), "shares"),
            ("VCB", OrderSide.BUY, -1, Decimal("125000"), "shares"),
            ("VCB", OrderSide.SELL, 100, Decimal("0"), "est_price"),
            ("VCB", OrderSide.SELL, 100, Decimal("-1"), "est_price"),
        ],
    )
    def test_invalid_order_raises(
        self, ticker: str, side: OrderSide, shares: int, price: Decimal, msg: str
    ) -> None:
        with pytest.raises(ValueError, match=msg):
            Order(ticker, side, shares, price)

    @given(
        ticker=tickers,
        side=st.sampled_from(OrderSide),
        shares=positive_shares,
        price=prices_decimal,
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_gross_amount_equals_shares_times_price(
        self, ticker: str, side: OrderSide, shares: int, price: Decimal
    ) -> None:
        order = Order(ticker, side, shares, price)
        assert order.gross_amount() == Decimal(shares) * price


# =====================================================================
# Holding
# =====================================================================


class TestHolding:
    def test_valid_holding(self) -> None:
        h = Holding("VCB", 100, Decimal("120000"))
        assert h.market_value(Decimal("125000")) == Decimal("12500000")
        assert h.unrealized_pnl(Decimal("125000")) == Decimal("500000")
        assert h.unrealized_pnl(Decimal("115000")) == Decimal("-500000")

    def test_flat_holding_allowed(self) -> None:
        """shares=0 + avg_cost=0 is a valid flat holding."""
        flat = Holding("FPT", 0, Decimal("0"))
        assert flat.market_value(Decimal("100000")) == Decimal("0")
        assert flat.unrealized_pnl(Decimal("100000")) == Decimal("0")

    @pytest.mark.parametrize(
        "ticker,shares,avg_cost,msg",
        [
            ("", 100, Decimal("120000"), "ticker"),
            ("VCB", -1, Decimal("120000"), "shares"),
            ("VCB", 100, Decimal("-1"), "avg_cost"),
        ],
    )
    def test_invalid_holding_raises(
        self, ticker: str, shares: int, avg_cost: Decimal, msg: str
    ) -> None:
        with pytest.raises(ValueError, match=msg):
            Holding(ticker, shares, avg_cost)

    @given(
        ticker=tickers, shares=st.integers(min_value=0, max_value=1_000_000), price=prices_decimal
    )
    def test_market_value_non_negative(self, ticker: str, shares: int, price: Decimal) -> None:
        h = Holding(ticker, shares, Decimal("1"))
        assert h.market_value(price) >= 0


# =====================================================================
# DailyPrice
# =====================================================================


class TestDailyPrice:
    def test_valid_bar(self) -> None:
        p = DailyPrice(
            ticker="VCB",
            trade_date=date(2026, 1, 15),
            open_price=Decimal("124000"),
            high=Decimal("126000"),
            low=Decimal("123500"),
            close=Decimal("125000"),
            volume=1_500_000,
        )
        assert p.daily_range() == Decimal("2500")
        assert p.price_for_execution() == Decimal("125000")

    def test_zero_volume_allowed(self) -> None:
        """Halted sessions have volume=0."""
        p = DailyPrice(
            ticker="VCB",
            trade_date=date(2026, 1, 20),
            open_price=Decimal("125000"),
            high=Decimal("125000"),
            low=Decimal("125000"),
            close=Decimal("125000"),
            volume=0,
        )
        assert p.volume == 0

    def test_return_from_prior(self) -> None:
        prior = DailyPrice(
            "VCB",
            date(2026, 1, 14),
            Decimal("124000"),
            Decimal("124000"),
            Decimal("123000"),
            Decimal("124000"),
            1_000_000,
        )
        current = DailyPrice(
            "VCB",
            date(2026, 1, 15),
            Decimal("124000"),
            Decimal("126000"),
            Decimal("123500"),
            Decimal("125000"),
            1_500_000,
        )
        # (125000 - 124000) / 124000
        expected = (Decimal("125000") - Decimal("124000")) / Decimal("124000")
        assert current.return_from(prior) == expected

    def test_return_from_prior_uses_adjusted_close(self) -> None:
        prior = DailyPrice(
            "VCB",
            date(2026, 1, 14),
            Decimal("124000"),
            Decimal("124000"),
            Decimal("123000"),
            Decimal("124000"),
            1_000_000,
            adjusted_close=Decimal("120000"),
        )
        current = DailyPrice(
            "VCB",
            date(2026, 1, 15),
            Decimal("124000"),
            Decimal("126000"),
            Decimal("123500"),
            Decimal("125000"),
            1_500_000,
            adjusted_close=Decimal("121000"),
        )
        expected = (Decimal("121000") - Decimal("120000")) / Decimal("120000")
        assert current.return_from(prior) == expected

    def test_return_from_cross_ticker_raises(self) -> None:
        a = DailyPrice(
            "VCB", date(2026, 1, 14), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        b = DailyPrice(
            "FPT", date(2026, 1, 15), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        with pytest.raises(ValueError, match="ticker mismatch"):
            b.return_from(a)

    def test_return_from_future_prior_raises(self) -> None:
        future = DailyPrice(
            "VCB", date(2026, 1, 20), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        past = DailyPrice(
            "VCB", date(2026, 1, 15), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        with pytest.raises(ValueError, match="strictly earlier"):
            past.return_from(future)

    @pytest.mark.parametrize(
        "field_,bad,msg",
        [
            ("open_price", Decimal("0"), "open_price"),
            ("high", Decimal("0"), "high"),
            ("low", Decimal("0"), "low"),
            ("close", Decimal("0"), "close"),
        ],
    )
    def test_non_positive_prices_raise(self, field_: str, bad: Decimal, msg: str) -> None:
        kwargs = {
            "ticker": "VCB",
            "trade_date": date(2026, 1, 15),
            "open_price": Decimal("1"),
            "high": Decimal("1"),
            "low": Decimal("1"),
            "close": Decimal("1"),
            "volume": 0,
        }
        kwargs[field_] = bad
        with pytest.raises(ValueError, match=msg):
            DailyPrice(**kwargs)  # type: ignore[arg-type]

    def test_high_less_than_low_raises(self) -> None:
        with pytest.raises(ValueError, match="high.*must be >= low"):
            DailyPrice(
                "VCB", date(2026, 1, 15), Decimal("1"), Decimal("1"), Decimal("2"), Decimal("1"), 0
            )


# =====================================================================
# RebalanceContext
# =====================================================================


class TestRebalanceContext:
    def test_valid_context(self) -> None:
        ctx = RebalanceContext(
            as_of=date(2026, 1, 15),
            prices={"VCB": Decimal("125000"), "FPT": Decimal("95000")},
            last_rebalance_date=date(2025, 12, 15),
            available_cash=Decimal("5000000"),
            flags={"dry_run": True},
        )
        assert ctx.price_of("VCB") == Decimal("125000")
        assert ctx.has_price("FPT")
        assert not ctx.has_price("MSFT")
        assert ctx.days_since_last_rebalance() == 31
        assert ctx.flags["dry_run"] is True

    def test_fresh_context_no_prior(self) -> None:
        ctx = RebalanceContext(as_of=date(2026, 1, 15), prices={})
        assert ctx.days_since_last_rebalance() is None

    def test_negative_cash_raises(self) -> None:
        with pytest.raises(ValueError, match="available_cash"):
            RebalanceContext(as_of=date(2026, 1, 15), prices={}, available_cash=Decimal("-1"))

    def test_zero_price_raises(self) -> None:
        with pytest.raises(ValueError, match="prices.*VCB.*must be positive"):
            RebalanceContext(as_of=date(2026, 1, 15), prices={"VCB": Decimal("0")})

    def test_future_last_rebalance_raises(self) -> None:
        with pytest.raises(ValueError, match="last_rebalance_date"):
            RebalanceContext(
                as_of=date(2026, 1, 15),
                prices={},
                last_rebalance_date=date(2026, 2, 15),
            )


# =====================================================================
# TradingCost
# =====================================================================


class TestTradingCost:
    def test_valid_cost_total(self) -> None:
        c = TradingCost(Decimal("15000"), Decimal("12500"), Decimal("12500"))
        assert c.total() == Decimal("40000")

    def test_zero_factory(self) -> None:
        z = TradingCost.zero()
        assert z.brokerage == Decimal("0")
        assert z.slippage == Decimal("0")
        assert z.tax == Decimal("0")
        assert z.total() == Decimal("0")

    @pytest.mark.parametrize("field_", ["brokerage", "slippage", "tax"])
    def test_negative_component_raises(self, field_: str) -> None:
        kwargs = {"brokerage": Decimal("0"), "slippage": Decimal("0"), "tax": Decimal("0")}
        kwargs[field_] = Decimal("-1")
        with pytest.raises(ValueError, match=field_):
            TradingCost(**kwargs)  # type: ignore[arg-type]

    @given(b=non_negative_cost, s=non_negative_cost, t=non_negative_cost)
    def test_total_equals_sum(self, b: Decimal, s: Decimal, t: Decimal) -> None:
        c = TradingCost(b, s, t)
        assert c.total() == b + s + t


# =====================================================================
# RebalanceDecision
# =====================================================================


class TestRebalanceDecision:
    def test_action_decision(self) -> None:
        order = Order("VCB", OrderSide.BUY, 100, Decimal("125000"))
        cost = TradingCost(Decimal("15000"), Decimal("12500"), Decimal("12500"))
        d = RebalanceDecision(
            strategy_name="threshold_band",
            triggered_at=date(2026, 1, 15),
            reason="band_drift",
            orders=(order,),
            costs=cost,
        )
        assert d.is_action
        assert d.order_count() == 1
        assert d.total_cost() == Decimal("40000")

    def test_no_action_factory(self) -> None:
        d = RebalanceDecision.no_action("threshold_band", date(2026, 1, 15))
        assert not d.is_action
        assert d.order_count() == 0
        assert d.total_cost() == Decimal("0")
        assert d.reason == "no_trigger"

    def test_no_action_custom_reason(self) -> None:
        d = RebalanceDecision.no_action(
            "threshold_band", date(2026, 1, 15), reason="insufficient_data"
        )
        assert d.reason == "insufficient_data"

    def test_orders_with_zero_cost_raises(self) -> None:
        """A real-action decision must have non-zero cost (unless free trading)."""
        order = Order("VCB", OrderSide.BUY, 100, Decimal("125000"))
        with pytest.raises(ValueError, match="zero total cost"):
            RebalanceDecision(
                strategy_name="threshold_band",
                triggered_at=date(2026, 1, 15),
                reason="band_drift",
                orders=(order,),
                costs=TradingCost.zero(),
            )

    @pytest.mark.parametrize("field_", ["strategy_name", "reason"])
    def test_empty_required_fields_raise(self, field_: str) -> None:
        kwargs = {
            "strategy_name": "threshold_band",
            "triggered_at": date(2026, 1, 15),
            "reason": "band_drift",
        }
        kwargs[field_] = ""
        with pytest.raises(ValueError, match=field_):
            RebalanceDecision(**kwargs)  # type: ignore[arg-type]


# =====================================================================
# Portfolio
# =====================================================================


class TestPortfolio:
    def test_initial_cash_only(self) -> None:
        p = Portfolio(cash=Decimal("100000000"))
        assert p.total_value({}) == Decimal("100000000")
        assert p.get_weights({}) == {}

    def test_buy_updates_cash_and_holdings(self) -> None:
        p = Portfolio(cash=Decimal("100000000"))
        buy = Order("VCB", OrderSide.BUY, 100, Decimal("125000"))
        p.apply_orders([buy], total_cost=Decimal("25000"))
        assert p.cash == Decimal("100000000") - Decimal("12500000") - Decimal("25000")
        assert p.holdings["VCB"].shares == 100
        assert p.holdings["VCB"].avg_cost == Decimal("125000")

    def test_buy_more_uses_vwap(self) -> None:
        p = Portfolio(cash=Decimal("100000000"))
        p.apply_orders([Order("VCB", OrderSide.BUY, 100, Decimal("125000"))])
        p.apply_orders([Order("VCB", OrderSide.BUY, 50, Decimal("130000"))])
        h = p.holdings["VCB"]
        # VWAP = (100*125000 + 50*130000) / 150 = 19000000 / 150
        expected_vwap = (
            Decimal("100") * Decimal("125000") + Decimal("50") * Decimal("130000")
        ) / Decimal("150")
        assert h.shares == 150
        assert h.avg_cost == expected_vwap

    def test_sell_partial_preserves_avg_cost(self) -> None:
        p = Portfolio(cash=Decimal("100000000"))
        p.apply_orders([Order("VCB", OrderSide.BUY, 100, Decimal("125000"))])
        avg_before = p.holdings["VCB"].avg_cost
        p.apply_orders([Order("VCB", OrderSide.SELL, 30, Decimal("130000"))])
        assert p.holdings["VCB"].shares == 70
        assert p.holdings["VCB"].avg_cost == avg_before

    def test_sell_all_resets_avg_cost(self) -> None:
        p = Portfolio(cash=Decimal("100000000"))
        p.apply_orders([Order("VCB", OrderSide.BUY, 100, Decimal("125000"))])
        p.apply_orders([Order("VCB", OrderSide.SELL, 100, Decimal("130000"))])
        assert p.holdings["VCB"].shares == 0
        assert p.holdings["VCB"].avg_cost == Decimal("0")

    def test_short_sell_rejected(self) -> None:
        p = Portfolio(cash=Decimal("100000000"))
        with pytest.raises(ValueError, match="Short selling not supported"):
            p.apply_orders([Order("VCB", OrderSide.SELL, 10, Decimal("125000"))])

    def test_budget_exhaustion_rejected(self) -> None:
        p = Portfolio(cash=Decimal("100"))
        with pytest.raises(ValueError, match="negative"):
            p.apply_orders([Order("VCB", OrderSide.BUY, 1, Decimal("10000"))])

    def test_negative_initial_cash_rejected(self) -> None:
        with pytest.raises(ValueError, match="cash must be non-negative"):
            Portfolio(cash=Decimal("-1"))

    def test_negative_total_cost_rejected(self) -> None:
        p = Portfolio(cash=Decimal("100000000"))
        with pytest.raises(ValueError, match="total_cost"):
            p.apply_orders(
                [Order("VCB", OrderSide.BUY, 100, Decimal("125000"))],
                total_cost=Decimal("-1"),
            )

    def test_weights_sum_matches_market_fraction(self) -> None:
        """Weights for held tickers + cash fraction = 1.0."""
        p = Portfolio(cash=Decimal("50000000"))
        p.apply_orders([Order("VCB", OrderSide.BUY, 100, Decimal("125000"))])
        prices = {"VCB": Decimal("130000")}  # Portfolio marked at 130000
        weights = p.get_weights(prices)
        total = p.total_value(prices)
        # VCB weight = (100 * 130000) / total
        expected_vcb_weight = float(Decimal("100") * Decimal("130000") / total)
        assert weights["VCB"] == pytest.approx(expected_vcb_weight)
        # Remaining fraction is cash (not in weights dict)
        cash_fraction = float(p.cash / total)
        assert weights["VCB"] + cash_fraction == pytest.approx(1.0)

    def test_weights_empty_when_zero_total_value(self) -> None:
        p = Portfolio(cash=Decimal("0"))
        assert p.get_weights({}) == {}

    def test_total_value_skips_missing_prices(self) -> None:
        """Missing prices treated as zero contribution (silent skip)."""
        p = Portfolio(cash=Decimal("100"))
        p.holdings["VCB"] = Holding("VCB", 10, Decimal("1000"))
        p.holdings["FPT"] = Holding("FPT", 20, Decimal("500"))
        # Price only for VCB
        total = p.total_value({"VCB": Decimal("1200")})
        assert total == Decimal("100") + Decimal("10") * Decimal("1200")  # 12100
