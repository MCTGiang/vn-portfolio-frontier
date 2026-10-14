"""Tests for lot_size.py (NFR-R-02 regulatory compliance, Day 9 Sprint 11)."""

from datetime import date
from decimal import Decimal

import pytest

from vn_portfolio_frontier.domain.entities.lot_size import (
    HSX_LOT_RULES,
    LotSizeRule,
    get_lot_size,
    round_to_lot,
)
from vn_portfolio_frontier.domain.entities.order import Order, OrderSide

# ---------------------------------------------------------------------------
# LotSizeRule.applies_on
# ---------------------------------------------------------------------------


class TestLotSizeRuleAppliesOn:
    """applies_on() must gate correctly on effective_from / effective_to."""

    def test_before_effective_from_returns_false(self):
        rule = LotSizeRule(
            exchange="HSX",
            lot_size=100,
            effective_from=date(2021, 1, 4),
            effective_to=None,
        )
        assert rule.applies_on(date(2021, 1, 3)) is False

    def test_on_effective_from_returns_true(self):
        rule = LotSizeRule(
            exchange="HSX",
            lot_size=100,
            effective_from=date(2021, 1, 4),
            effective_to=None,
        )
        assert rule.applies_on(date(2021, 1, 4)) is True

    def test_after_effective_to_returns_false(self):
        rule = LotSizeRule(
            exchange="HSX",
            lot_size=10,
            effective_from=date(2015, 1, 1),
            effective_to=date(2021, 1, 3),
        )
        assert rule.applies_on(date(2021, 1, 4)) is False

    def test_on_effective_to_returns_true(self):
        rule = LotSizeRule(
            exchange="HSX",
            lot_size=10,
            effective_from=date(2015, 1, 1),
            effective_to=date(2021, 1, 3),
        )
        assert rule.applies_on(date(2021, 1, 3)) is True


# ---------------------------------------------------------------------------
# get_lot_size (HSX reform boundary 04/01/2021)
# ---------------------------------------------------------------------------


class TestGetLotSize:
    """get_lot_size() must return correct rule for exchange + date."""

    def test_hsx_pre_reform_returns_10(self):
        assert get_lot_size("HSX", date(2020, 12, 31)) == 10

    def test_hsx_day_before_reform_returns_10(self):
        assert get_lot_size("HSX", date(2021, 1, 3)) == 10

    def test_hsx_reform_date_returns_100(self):
        """Quyet dinh 496/QD-SGDHCM effective 04/01/2021."""
        assert get_lot_size("HSX", date(2021, 1, 4)) == 100

    def test_hsx_post_reform_returns_100(self):
        assert get_lot_size("HSX", date(2026, 10, 14)) == 100

    def test_unsupported_exchange_raises(self):
        with pytest.raises(ValueError, match="No lot rules defined"):
            get_lot_size("NYSE", date(2026, 1, 1))

    def test_date_before_any_rule_raises(self):
        """Pre-2015 is outside HSX rule coverage."""
        with pytest.raises(ValueError, match="No applicable lot rule"):
            get_lot_size("HSX", date(2010, 1, 1))


# ---------------------------------------------------------------------------
# round_to_lot
# ---------------------------------------------------------------------------


class TestRoundToLot:
    """round_to_lot() must round DOWN conservatively."""

    def test_fractional_rounds_down(self):
        assert round_to_lot(Decimal("123.45"), 100) == 100

    def test_exact_multiple_unchanged(self):
        assert round_to_lot(Decimal("300"), 100) == 300

    def test_below_lot_returns_zero(self):
        assert round_to_lot(Decimal("50"), 100) == 0

    def test_just_below_lot_returns_zero(self):
        assert round_to_lot(Decimal("99.99"), 100) == 0

    def test_zero_input_returns_zero(self):
        assert round_to_lot(Decimal("0"), 100) == 0

    def test_negative_input_returns_zero(self):
        """Defensive: negative shares makes no sense, treat as zero."""
        assert round_to_lot(Decimal("-50"), 100) == 0

    def test_large_number(self):
        assert round_to_lot(Decimal("1234567"), 100) == 1234500

    def test_hsx_pre_reform_lot_10(self):
        assert round_to_lot(Decimal("55"), 10) == 50

    def test_zero_lot_size_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            round_to_lot(Decimal("100"), 0)

    def test_negative_lot_size_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            round_to_lot(Decimal("100"), -10)


# ---------------------------------------------------------------------------
# Order.enforce_lot_size (integration with Order entity)
# ---------------------------------------------------------------------------


class TestOrderEnforceLotSize:
    """Order.enforce_lot_size preserves immutability + handles edge cases."""

    def test_rounded_down_returns_new_order(self):
        orig = Order("VCB", OrderSide.BUY, 123, Decimal("125000"))
        enforced = orig.enforce_lot_size(100)
        assert enforced is not orig
        assert enforced.shares == 100
        assert enforced.ticker == "VCB"
        assert enforced.side == OrderSide.BUY
        assert enforced.est_price == Decimal("125000")

    def test_already_aligned_returns_same_instance(self):
        """Micro-optimization: no new object if no change needed."""
        orig = Order("FPT", OrderSide.SELL, 300, Decimal("85000"))
        enforced = orig.enforce_lot_size(100)
        assert enforced is orig

    def test_below_lot_returns_none(self):
        """Position too small to open - drop entirely."""
        orig = Order("MWG", OrderSide.BUY, 50, Decimal("45000"))
        assert orig.enforce_lot_size(100) is None

    def test_preserves_immutability_of_original(self):
        """Original Order must remain unchanged (frozen)."""
        orig = Order("ACB", OrderSide.BUY, 1234, Decimal("22000"))
        _ = orig.enforce_lot_size(100)
        assert orig.shares == 1234  # unchanged


# ---------------------------------------------------------------------------
# Rule tuple sanity
# ---------------------------------------------------------------------------


class TestHSXLotRules:
    """HSX_LOT_RULES tuple must cover 2015-01-01 to today with no gaps."""

    def test_rules_are_frozen_tuple(self):
        assert isinstance(HSX_LOT_RULES, tuple)

    def test_no_gap_at_reform_boundary(self):
        """2021-01-03 covered by old rule, 2021-01-04 by new rule."""
        assert get_lot_size("HSX", date(2021, 1, 3)) == 10
        assert get_lot_size("HSX", date(2021, 1, 4)) == 100

    def test_current_rule_has_no_end_date(self):
        """Latest rule must be open-ended (effective_to is None)."""
        latest = HSX_LOT_RULES[-1]
        assert latest.effective_to is None
