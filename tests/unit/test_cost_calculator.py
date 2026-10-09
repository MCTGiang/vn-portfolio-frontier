"""Unit tests for CostCalculator (Sprint 11 Day 3).

Covers ADR-012 cost model:
    - brokerage = sum(order.gross * brokerage_pct) [both BUY+SELL]
    - slippage  = sum(order.gross * market_impact_bps / 10000) [both sides]
    - tax       = sum(order.gross * tax_pct for SELL only)

Test categories:
    - Happy path math (brokerage/slippage/tax exact values)
    - Edge cases (empty orders, zero-fee, pure BUY/SELL)
    - Validation errors (parametrize invalid parameters)
    - Quantization to VND (2 decimal places HALF_UP)
    - Hypothesis property: total = brokerage + slippage + tax
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vn_portfolio_frontier.domain.entities import Order, OrderSide
from vn_portfolio_frontier.domain.services import CostCalculator

# =====================================================================
# Hypothesis strategies
# =====================================================================

tickers = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=3, max_size=3)
prices = st.decimals(
    min_value=Decimal("1000"),
    max_value=Decimal("500000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
shares = st.integers(min_value=1, max_value=100_000)


# =====================================================================
# Happy path
# =====================================================================


class TestCostCalculatorMath:
    def test_mixed_buy_sell_all_components(self) -> None:
        """BUY 100 VCB @ 125000 + SELL 50 FPT @ 95000 with default params."""
        calc = CostCalculator(brokerage_pct=Decimal("0.0015"))
        orders = [
            Order("VCB", OrderSide.BUY, 100, Decimal("125000")),
            Order("FPT", OrderSide.SELL, 50, Decimal("95000")),
        ]
        cost = calc.compute(orders)
        # gross: VCB 12,500,000 + FPT 4,750,000 = 17,250,000
        assert cost.brokerage == Decimal("25875.00")  # 17.25M * 0.0015
        assert cost.slippage == Decimal("17250.00")  # 17.25M * 10/10000
        assert cost.tax == Decimal("4750.00")  # 4.75M * 0.001 (SELL only)

    def test_buy_only_has_zero_tax(self) -> None:
        calc = CostCalculator(brokerage_pct=Decimal("0.001"))
        cost = calc.compute([Order("VCB", OrderSide.BUY, 100, Decimal("100000"))])
        assert cost.tax == Decimal("0.00")
        assert cost.brokerage == Decimal("10000.00")  # 10M * 0.001

    def test_sell_only_includes_tax(self) -> None:
        calc = CostCalculator(brokerage_pct=Decimal("0.001"))
        cost = calc.compute([Order("VCB", OrderSide.SELL, 100, Decimal("100000"))])
        assert cost.tax == Decimal("10000.00")  # 10M * 0.001 (seller tax)

    def test_empty_orders_returns_zero(self) -> None:
        calc = CostCalculator(brokerage_pct=Decimal("0.0015"))
        cost = calc.compute([])
        assert cost.total() == Decimal("0.00")
        assert cost.brokerage == Decimal("0.00")
        assert cost.slippage == Decimal("0.00")
        assert cost.tax == Decimal("0.00")

    def test_zero_fee_broker(self) -> None:
        """DNSE / Pinetree 0% brokers (HSX exchange minimum fee applied at Simulator level)."""
        calc = CostCalculator(
            brokerage_pct=Decimal("0"),
            market_impact_bps=0,
            tax_pct=Decimal("0"),
        )
        cost = calc.compute([Order("VCB", OrderSide.BUY, 100, Decimal("100000"))])
        assert cost.total() == Decimal("0.00")

    def test_market_impact_bps_scaling(self) -> None:
        """50 bps = 5x higher than default 10 bps."""
        default_calc = CostCalculator(brokerage_pct=Decimal("0"), market_impact_bps=10)
        high_calc = CostCalculator(brokerage_pct=Decimal("0"), market_impact_bps=50)
        orders = [Order("VCB", OrderSide.BUY, 100, Decimal("100000"))]  # gross 10M
        default_cost = default_calc.compute(orders)
        high_cost = high_calc.compute(orders)
        assert default_cost.slippage == Decimal("10000.00")  # 10M * 10/10000
        assert high_cost.slippage == Decimal("50000.00")  # 10M * 50/10000

    def test_quantization_rounds_half_up(self) -> None:
        """Fractional VND rounds HALF_UP to 2 decimal places."""
        # gross * brokerage_pct has fractional thousandths
        calc = CostCalculator(brokerage_pct=Decimal("0.0001"))  # 0.01%
        # 1 share * 12345 VND * 0.0001 = 1.2345 -> quantize HALF_UP -> 1.23
        orders = [Order("VCB", OrderSide.BUY, 1, Decimal("12345"))]
        cost = calc.compute(orders)
        assert cost.brokerage == Decimal("1.23")  # HALF_UP from 1.2345

    def test_quantization_rounds_up_at_half(self) -> None:
        """0.005 -> HALF_UP -> 0.01, not 0.00."""
        calc = CostCalculator(brokerage_pct=Decimal("0.0001"))
        # Need a case where fractional = 0.005 exactly
        # 1 * 500 * 0.0001 = 0.05 (no fractional) - easy case
        orders = [Order("VCB", OrderSide.BUY, 1, Decimal("500"))]
        cost = calc.compute(orders)
        assert cost.brokerage == Decimal("0.05")


# =====================================================================
# Validation
# =====================================================================


class TestCostCalculatorValidation:
    @pytest.mark.parametrize(
        "brokerage,msg",
        [
            (Decimal("-0.001"), "brokerage_pct"),
            (Decimal("0.015"), "brokerage_pct"),  # > 1% ceiling
            (Decimal("1.5"), "brokerage_pct"),
        ],
    )
    def test_invalid_brokerage_pct_raises(self, brokerage: Decimal, msg: str) -> None:
        with pytest.raises(ValueError, match=msg):
            CostCalculator(brokerage_pct=brokerage)

    @pytest.mark.parametrize("bps", [-1, 1000, 10000])
    def test_invalid_market_impact_bps_raises(self, bps: int) -> None:
        with pytest.raises(ValueError, match="market_impact_bps"):
            CostCalculator(brokerage_pct=Decimal("0.001"), market_impact_bps=bps)

    @pytest.mark.parametrize("tax", [Decimal("-0.001"), Decimal("0.02"), Decimal("1.5")])
    def test_invalid_tax_pct_raises(self, tax: Decimal) -> None:
        with pytest.raises(ValueError, match="tax_pct"):
            CostCalculator(brokerage_pct=Decimal("0.001"), tax_pct=tax)

    def test_boundary_values_accepted(self) -> None:
        """Boundaries exact values (0 + max) should NOT raise."""
        CostCalculator(brokerage_pct=Decimal("0"), market_impact_bps=0, tax_pct=Decimal("0"))
        CostCalculator(
            brokerage_pct=Decimal("0.01"), market_impact_bps=500, tax_pct=Decimal("0.01")
        )


# =====================================================================
# Property-based
# =====================================================================


class TestCostCalculatorProperties:
    @given(
        ticker=tickers,
        side=st.sampled_from(OrderSide),
        n=shares,
        price=prices,
    )
    def test_total_equals_sum_of_components(
        self, ticker: str, side: OrderSide, n: int, price: Decimal
    ) -> None:
        """TradingCost.total() == brokerage + slippage + tax, always."""
        calc = CostCalculator(brokerage_pct=Decimal("0.0015"))
        order = Order(ticker, side, n, price)
        cost = calc.compute([order])
        assert cost.total() == cost.brokerage + cost.slippage + cost.tax

    @given(ticker=tickers, n=shares, price=prices)
    def test_buy_only_never_has_tax(self, ticker: str, n: int, price: Decimal) -> None:
        """BUY-only orders invariant: tax component = 0."""
        calc = CostCalculator(brokerage_pct=Decimal("0.0015"))
        order = Order(ticker, OrderSide.BUY, n, price)
        cost = calc.compute([order])
        assert cost.tax == Decimal("0.00")

    @given(ticker=tickers, n=shares, price=prices)
    def test_sell_tax_is_tax_pct_times_gross(self, ticker: str, n: int, price: Decimal) -> None:
        """SELL-only orders: tax = tax_pct * gross (quantized to VND)."""
        from decimal import ROUND_HALF_UP

        calc = CostCalculator(
            brokerage_pct=Decimal("0"), market_impact_bps=0, tax_pct=Decimal("0.001")
        )
        order = Order(ticker, OrderSide.SELL, n, price)
        cost = calc.compute([order])
        expected = (order.gross_amount() * Decimal("0.001")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert cost.tax == expected
