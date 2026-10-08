"""Contract tests for application.ports Protocols + Fake implementations.

Verifies:
    1. Each Fake duck-types to its Protocol (isinstance returns True)
    2. Missing-method stubs do NOT satisfy Protocol (negative check)
    3. Round-trip insert/get preserves data
    4. Edge cases: empty insert, missing lookups, idempotent re-insert
    5. Validation errors (list_recent limit, out-of-order date ranges)

Why contract tests separate from implementation tests:
    - Day 7+ sẽ add Neon implementations — same contract tests should pass
      against both Fake AND Neon (via parametrize) để prove swap-ability
    - For Day 4 scope: just Fake contract pass. Neon tests added Day 7.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from tests.unit.fakes import (
    FakePriceRepository,
    FakeRebalanceDecisionRepository,
    FakeRebalanceRunRepository,
)
from vn_portfolio_frontier.application.ports import (
    PriceRepository,
    RebalanceDecisionRepository,
    RebalanceRunRepository,
    RunRecord,
)
from vn_portfolio_frontier.domain.entities import (
    DailyPrice,
    Order,
    OrderSide,
    RebalanceDecision,
    TradingCost,
)

# =====================================================================
# Shared fixtures
# =====================================================================


@pytest.fixture
def price_repo() -> FakePriceRepository:
    return FakePriceRepository()


@pytest.fixture
def run_repo() -> FakeRebalanceRunRepository:
    return FakeRebalanceRunRepository()


@pytest.fixture
def decision_repo() -> FakeRebalanceDecisionRepository:
    return FakeRebalanceDecisionRepository()


@pytest.fixture
def sample_bar() -> DailyPrice:
    return DailyPrice(
        ticker="VCB",
        trade_date=date(2026, 1, 15),
        open_price=Decimal("124000"),
        high=Decimal("126000"),
        low=Decimal("123500"),
        close=Decimal("125000"),
        volume=1_500_000,
    )


@pytest.fixture
def sample_run_record() -> RunRecord:
    return RunRecord(
        brokerage_pct=Decimal("0.0015"),
        tax_pct=Decimal("0.001"),
        market_impact_bps=10,
        strategy_name="threshold_band",
        strategy_params={"band_bps": 500},
        target_weights={"VCB": 0.5, "FPT": 0.5},
        backtest_start=date(2024, 1, 1),
        backtest_end=date(2025, 12, 31),
        git_commit_sha="a" * 40,
        code_version="v2.0-sprint11",
        initial_capital=Decimal("1000000000.00"),
    )


# =====================================================================
# Protocol satisfaction (positive checks)
# =====================================================================


class TestProtocolSatisfaction:
    def test_fake_price_repo_satisfies_protocol(self, price_repo) -> None:
        assert isinstance(price_repo, PriceRepository)

    def test_fake_run_repo_satisfies_protocol(self, run_repo) -> None:
        assert isinstance(run_repo, RebalanceRunRepository)

    def test_fake_decision_repo_satisfies_protocol(self, decision_repo) -> None:
        assert isinstance(decision_repo, RebalanceDecisionRepository)

    def test_missing_method_does_not_satisfy(self) -> None:
        """Negative check: a stub missing one method MUST fail isinstance."""

        class IncompletePriceRepo:
            def get_ohlcv(self, ticker, start, end):
                return []

            # Missing get_latest_dates + batch_insert

        assert not isinstance(IncompletePriceRepo(), PriceRepository)


# =====================================================================
# PriceRepository contract
# =====================================================================


class TestFakePriceRepository:
    def test_round_trip_insert_and_get(
        self, price_repo: FakePriceRepository, sample_bar: DailyPrice
    ) -> None:
        inserted = price_repo.batch_insert([sample_bar])
        assert inserted == 1
        retrieved = price_repo.get_ohlcv("VCB", date(2026, 1, 1), date(2026, 1, 31))
        assert retrieved == [sample_bar]

    def test_idempotent_duplicate_insert(
        self, price_repo: FakePriceRepository, sample_bar: DailyPrice
    ) -> None:
        price_repo.batch_insert([sample_bar])
        duplicate_count = price_repo.batch_insert([sample_bar])
        assert duplicate_count == 0  # skipped
        assert len(price_repo.get_ohlcv("VCB", date(2026, 1, 1), date(2026, 12, 31))) == 1

    def test_empty_insert_returns_zero(self, price_repo: FakePriceRepository) -> None:
        assert price_repo.batch_insert([]) == 0

    def test_get_ohlcv_returns_sorted_chronologically(
        self, price_repo: FakePriceRepository
    ) -> None:
        bar_jan = DailyPrice(
            "VCB", date(2026, 1, 15), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        bar_feb = DailyPrice(
            "VCB", date(2026, 2, 15), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        bar_mar = DailyPrice(
            "VCB", date(2026, 3, 15), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        # Insert out-of-order
        price_repo.batch_insert([bar_mar, bar_jan, bar_feb])
        result = price_repo.get_ohlcv("VCB", date(2026, 1, 1), date(2026, 12, 31))
        assert [b.trade_date for b in result] == [
            date(2026, 1, 15),
            date(2026, 2, 15),
            date(2026, 3, 15),
        ]

    def test_get_ohlcv_filters_by_ticker(self, price_repo: FakePriceRepository) -> None:
        bar_vcb = DailyPrice(
            "VCB", date(2026, 1, 15), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        bar_fpt = DailyPrice(
            "FPT", date(2026, 1, 15), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        price_repo.batch_insert([bar_vcb, bar_fpt])
        vcb_only = price_repo.get_ohlcv("VCB", date(2026, 1, 1), date(2026, 12, 31))
        assert len(vcb_only) == 1
        assert vcb_only[0].ticker == "VCB"

    def test_get_ohlcv_range_exclusive_out_of_range(self, price_repo: FakePriceRepository) -> None:
        bar = DailyPrice(
            "VCB", date(2026, 1, 15), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        price_repo.batch_insert([bar])
        # Range excludes jan 15
        result = price_repo.get_ohlcv("VCB", date(2026, 2, 1), date(2026, 2, 28))
        assert result == []

    def test_get_latest_dates_empty(self, price_repo: FakePriceRepository) -> None:
        assert price_repo.get_latest_dates() == {}

    def test_get_latest_dates_multiple_tickers(self, price_repo: FakePriceRepository) -> None:
        bar_vcb_jan = DailyPrice(
            "VCB", date(2026, 1, 15), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        bar_vcb_feb = DailyPrice(
            "VCB", date(2026, 2, 15), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        bar_fpt = DailyPrice(
            "FPT", date(2026, 1, 10), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), 0
        )
        price_repo.batch_insert([bar_vcb_jan, bar_vcb_feb, bar_fpt])
        latest = price_repo.get_latest_dates()
        assert latest == {"VCB": date(2026, 2, 15), "FPT": date(2026, 1, 10)}

    def test_get_ohlcv_rejects_out_of_order_range(self, price_repo: FakePriceRepository) -> None:
        with pytest.raises(ValueError, match="start.*end"):
            price_repo.get_ohlcv("VCB", date(2026, 2, 1), date(2026, 1, 1))


# =====================================================================
# RebalanceRunRepository contract
# =====================================================================


class TestFakeRebalanceRunRepository:
    def test_save_returns_incrementing_id(
        self, run_repo: FakeRebalanceRunRepository, sample_run_record: RunRecord
    ) -> None:
        rid1 = run_repo.save(sample_run_record)
        rid2 = run_repo.save(sample_run_record)
        assert rid1 == 1
        assert rid2 == 2

    def test_find_by_id_round_trip(
        self, run_repo: FakeRebalanceRunRepository, sample_run_record: RunRecord
    ) -> None:
        rid = run_repo.save(sample_run_record)
        retrieved = run_repo.find_by_id(rid)
        assert retrieved == sample_run_record

    def test_find_by_id_unknown_returns_none(self, run_repo: FakeRebalanceRunRepository) -> None:
        assert run_repo.find_by_id(999) is None

    def test_list_recent_empty(self, run_repo: FakeRebalanceRunRepository) -> None:
        assert run_repo.list_recent() == []

    def test_list_recent_descending_order(
        self, run_repo: FakeRebalanceRunRepository, sample_run_record: RunRecord
    ) -> None:
        rid1 = run_repo.save(sample_run_record)
        rid2 = run_repo.save(sample_run_record)
        rid3 = run_repo.save(sample_run_record)
        summaries = run_repo.list_recent(limit=10)
        assert [s.run_id for s in summaries] == [rid3, rid2, rid1]

    def test_list_recent_respects_limit(
        self, run_repo: FakeRebalanceRunRepository, sample_run_record: RunRecord
    ) -> None:
        for _ in range(5):
            run_repo.save(sample_run_record)
        assert len(run_repo.list_recent(limit=3)) == 3

    def test_list_recent_rejects_non_positive_limit(
        self, run_repo: FakeRebalanceRunRepository
    ) -> None:
        with pytest.raises(ValueError, match="limit"):
            run_repo.list_recent(limit=0)
        with pytest.raises(ValueError, match="limit"):
            run_repo.list_recent(limit=-5)

    def test_summary_carries_timestamp(
        self, run_repo: FakeRebalanceRunRepository, sample_run_record: RunRecord
    ) -> None:
        rid = run_repo.save(sample_run_record)
        summary = run_repo.list_recent(limit=1)[0]
        assert summary.run_id == rid
        assert isinstance(summary.run_timestamp, datetime)


# =====================================================================
# RebalanceDecisionRepository contract
# =====================================================================


class TestFakeRebalanceDecisionRepository:
    def _make_decision(self, dt: date, reason: str = "band_drift") -> RebalanceDecision:
        order = Order("VCB", OrderSide.BUY, 100, Decimal("125000"))
        cost = TradingCost(Decimal("18750"), Decimal("12500"), Decimal("0"))
        return RebalanceDecision(
            strategy_name="threshold_band",
            triggered_at=dt,
            reason=reason,
            orders=(order,),
            costs=cost,
        )

    def test_save_batch_round_trip(self, decision_repo: FakeRebalanceDecisionRepository) -> None:
        d1 = self._make_decision(date(2026, 1, 15))
        d2 = self._make_decision(date(2026, 2, 15))
        inserted = decision_repo.save_batch(run_id=1, decisions=[d1, d2])
        assert inserted == 2
        retrieved = decision_repo.find_by_run(1)
        assert retrieved == [d1, d2]

    def test_save_batch_empty_returns_zero(
        self, decision_repo: FakeRebalanceDecisionRepository
    ) -> None:
        assert decision_repo.save_batch(1, []) == 0

    def test_find_by_run_sorted_chronologically(
        self, decision_repo: FakeRebalanceDecisionRepository
    ) -> None:
        d_mar = self._make_decision(date(2026, 3, 15))
        d_jan = self._make_decision(date(2026, 1, 15))
        d_feb = self._make_decision(date(2026, 2, 15))
        decision_repo.save_batch(1, [d_mar, d_jan, d_feb])
        result = decision_repo.find_by_run(1)
        assert [d.triggered_at for d in result] == [
            date(2026, 1, 15),
            date(2026, 2, 15),
            date(2026, 3, 15),
        ]

    def test_find_by_run_unknown_returns_empty(
        self, decision_repo: FakeRebalanceDecisionRepository
    ) -> None:
        assert decision_repo.find_by_run(999) == []

    def test_save_batch_not_idempotent(
        self, decision_repo: FakeRebalanceDecisionRepository
    ) -> None:
        """save_batch với same decisions twice doubles the stored count (per Protocol)."""
        d = self._make_decision(date(2026, 1, 15))
        decision_repo.save_batch(1, [d])
        decision_repo.save_batch(1, [d])  # intentional double
        assert len(decision_repo.find_by_run(1)) == 2


# =====================================================================
# RunRecord validation (F-H3)
# =====================================================================


class TestRunRecordValidation:
    def test_rejects_zero_initial_capital(self) -> None:
        """F-H3: initial_capital must be positive (Portfolio needs funding)."""
        with pytest.raises(ValueError, match="initial_capital must be positive"):
            RunRecord(
                brokerage_pct=Decimal("0.0015"),
                tax_pct=Decimal("0.001"),
                market_impact_bps=10,
                strategy_name="threshold_band",
                strategy_params={"band_bps": 500},
                target_weights={"VCB": 1.0},
                backtest_start=date(2024, 1, 1),
                backtest_end=date(2025, 12, 31),
                git_commit_sha="a" * 40,
                code_version="v2.0-sprint11",
                initial_capital=Decimal("0"),  # invalid
            )

    def test_rejects_negative_initial_capital(self) -> None:
        """F-H3: negative capital also rejected."""
        with pytest.raises(ValueError, match="initial_capital must be positive"):
            RunRecord(
                brokerage_pct=Decimal("0.0015"),
                tax_pct=Decimal("0.001"),
                market_impact_bps=10,
                strategy_name="threshold_band",
                strategy_params={"band_bps": 500},
                target_weights={"VCB": 1.0},
                backtest_start=date(2024, 1, 1),
                backtest_end=date(2025, 12, 31),
                git_commit_sha="a" * 40,
                code_version="v2.0-sprint11",
                initial_capital=Decimal("-100"),  # invalid
            )
