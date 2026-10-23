"""Unit tests for FrontierService (Day 11 Cum 4).

Covers:
    - FrontierRequest DTO validation (tickers count, date order, rf_source,
      upper_bound range, n_frontier_points min)
    - Happy path: compute() returns FrontierResult with 3 refs + N points
      + metadata (rf_annual_pct, universe_size, data_window_days, returns_rows)
    - Rf fetcher integration (called with correct window + source)
    - Error paths: no price data, too few overlapping days (< 60)
    - Edge: 2-ticker minimum universe
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import numpy as np
import pytest

from tests.unit.fakes import FakePriceRepository
from vn_portfolio_frontier.application.services import (
    FrontierRequest,
    FrontierResult,
    FrontierService,
)
from vn_portfolio_frontier.domain.entities import DailyPrice
from vn_portfolio_frontier.domain.services import FrontierCurve

# =====================================================================
# Fixtures
# =====================================================================

TICKERS = ("VCB", "FPT", "VHM")
START_DATE = date(2024, 1, 1)
END_DATE = date(2024, 12, 31)


def _generate_synthetic_bars(
    ticker: str, start: date, days: int, seed: int = 42
) -> list[DailyPrice]:
    """Generate reproducible synthetic OHLCV bars for a ticker."""
    rng = np.random.default_rng(seed + hash(ticker) % 1000)
    bars = []
    price = 100.0
    for i in range(days):
        trade_date = start + timedelta(days=i)
        # Skip weekends roughly (simplified)
        if trade_date.weekday() >= 5:
            continue
        daily_return = rng.normal(0, 0.015)
        price *= 1 + daily_return
        bars.append(
            DailyPrice(
                ticker=ticker,
                trade_date=trade_date,
                open_price=Decimal(f"{price * 0.998:.2f}"),
                high=Decimal(f"{price * 1.005:.2f}"),
                low=Decimal(f"{price * 0.995:.2f}"),
                close=Decimal(f"{price:.2f}"),
                volume=1_000_000 + i * 100,
                source="SYNTHETIC",
            )
        )
    return bars


@pytest.fixture
def price_repo_with_data() -> FakePriceRepository:
    """FakePriceRepository with 100 trading days of synthetic data for 3 tickers."""
    repo = FakePriceRepository()
    for ticker in TICKERS:
        repo.batch_insert(_generate_synthetic_bars(ticker, START_DATE, days=200))
    return repo


@pytest.fixture
def mock_rf_fetcher() -> MagicMock:
    """Mock rf_fetcher returning Decimal('5.00')."""
    m = MagicMock(return_value=Decimal("5.00"))
    return m


@pytest.fixture
def frontier_service(
    price_repo_with_data: FakePriceRepository, mock_rf_fetcher: MagicMock
) -> FrontierService:
    return FrontierService(price_repo=price_repo_with_data, rf_fetcher=mock_rf_fetcher)


@pytest.fixture
def valid_request() -> FrontierRequest:
    return FrontierRequest(
        tickers=TICKERS,
        backtest_start=START_DATE,
        backtest_end=END_DATE,
        rf_source="vn_bond_1y",
        upper_bound=0.4,
        n_frontier_points=10,
    )


# =====================================================================
# FrontierRequest validation
# =====================================================================


class TestFrontierRequestValidation:
    def test_valid_request(self) -> None:
        req = FrontierRequest(
            tickers=("VCB", "FPT"),
            backtest_start=date(2024, 1, 1),
            backtest_end=date(2024, 12, 31),
        )
        assert req.tickers == ("VCB", "FPT")
        assert req.rf_source == "zero"
        assert req.upper_bound == 0.4
        assert req.n_frontier_points == 20

    def test_insufficient_tickers_raises(self) -> None:
        with pytest.raises(ValueError, match=">= 2 tickers"):
            FrontierRequest(
                tickers=("VCB",),
                backtest_start=date(2024, 1, 1),
                backtest_end=date(2024, 12, 31),
            )

    def test_invalid_date_order_raises(self) -> None:
        with pytest.raises(ValueError, match="must be <"):
            FrontierRequest(
                tickers=("VCB", "FPT"),
                backtest_start=date(2024, 12, 31),
                backtest_end=date(2024, 1, 1),
            )

    def test_equal_dates_raises(self) -> None:
        with pytest.raises(ValueError, match="must be <"):
            FrontierRequest(
                tickers=("VCB", "FPT"),
                backtest_start=date(2024, 6, 1),
                backtest_end=date(2024, 6, 1),
            )

    def test_invalid_rf_source_raises(self) -> None:
        with pytest.raises(ValueError, match="rf_source must be one of"):
            FrontierRequest(
                tickers=("VCB", "FPT"),
                backtest_start=date(2024, 1, 1),
                backtest_end=date(2024, 12, 31),
                rf_source="invalid_source",
            )

    def test_valid_rf_sources_accepted(self) -> None:
        for src in ["zero", "vcb_13m_deposit", "sbv_refinance", "vn_bond_1y"]:
            req = FrontierRequest(
                tickers=("VCB", "FPT"),
                backtest_start=date(2024, 1, 1),
                backtest_end=date(2024, 12, 31),
                rf_source=src,
            )
            assert req.rf_source == src

    def test_upper_bound_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="upper_bound must be in"):
            FrontierRequest(
                tickers=("VCB", "FPT"),
                backtest_start=date(2024, 1, 1),
                backtest_end=date(2024, 12, 31),
                upper_bound=0.0,
            )

    def test_upper_bound_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="upper_bound must be in"):
            FrontierRequest(
                tickers=("VCB", "FPT"),
                backtest_start=date(2024, 1, 1),
                backtest_end=date(2024, 12, 31),
                upper_bound=1.5,
            )

    def test_n_points_too_low_raises(self) -> None:
        with pytest.raises(ValueError, match="n_frontier_points must be >= 2"):
            FrontierRequest(
                tickers=("VCB", "FPT"),
                backtest_start=date(2024, 1, 1),
                backtest_end=date(2024, 12, 31),
                n_frontier_points=1,
            )


# =====================================================================
# compute() happy path
# =====================================================================


class TestComputeHappyPath:
    def test_returns_frontier_result(
        self, frontier_service: FrontierService, valid_request: FrontierRequest
    ) -> None:
        result = frontier_service.compute(valid_request)
        assert isinstance(result, FrontierResult)

    def test_frontier_curve_in_result(
        self, frontier_service: FrontierService, valid_request: FrontierRequest
    ) -> None:
        result = frontier_service.compute(valid_request)
        assert isinstance(result.frontier_curve, FrontierCurve)
        assert len(result.frontier_curve.points) == 10  # n_frontier_points

    def test_universe_size(
        self, frontier_service: FrontierService, valid_request: FrontierRequest
    ) -> None:
        result = frontier_service.compute(valid_request)
        assert result.universe_size == 3

    def test_data_window_days(
        self, frontier_service: FrontierService, valid_request: FrontierRequest
    ) -> None:
        result = frontier_service.compute(valid_request)
        # Days between 2024-01-01 and 2024-12-31 = 365
        assert result.data_window_days == (END_DATE - START_DATE).days

    def test_returns_rows_positive(
        self, frontier_service: FrontierService, valid_request: FrontierRequest
    ) -> None:
        result = frontier_service.compute(valid_request)
        # Synthetic data: ~143 weekdays in 200 cal days, minus 1 for log diff
        assert result.returns_rows >= 50

    def test_rf_annual_pct_from_fetcher(
        self,
        frontier_service: FrontierService,
        valid_request: FrontierRequest,
        mock_rf_fetcher: MagicMock,
    ) -> None:
        result = frontier_service.compute(valid_request)
        assert result.rf_annual_pct == Decimal("5.00")

    def test_rf_fetcher_called_with_window_and_source(
        self,
        frontier_service: FrontierService,
        valid_request: FrontierRequest,
        mock_rf_fetcher: MagicMock,
    ) -> None:
        frontier_service.compute(valid_request)
        mock_rf_fetcher.assert_called_once_with(START_DATE, END_DATE, "vn_bond_1y")

    def test_tickers_preserved_in_weights(
        self, frontier_service: FrontierService, valid_request: FrontierRequest
    ) -> None:
        result = frontier_service.compute(valid_request)
        assert set(result.frontier_curve.ref_min_variance.weights.keys()) == set(TICKERS)


# =====================================================================
# compute() error paths
# =====================================================================


class TestComputeErrors:
    def test_no_price_data_for_ticker_raises(self, mock_rf_fetcher: MagicMock) -> None:
        """Empty repo -> raise ValueError."""
        empty_repo = FakePriceRepository()
        service = FrontierService(price_repo=empty_repo, rf_fetcher=mock_rf_fetcher)
        req = FrontierRequest(
            tickers=("VCB", "FPT"),
            backtest_start=date(2024, 1, 1),
            backtest_end=date(2024, 12, 31),
        )
        with pytest.raises(ValueError, match="no price data for ticker"):
            service.compute(req)

    def test_too_few_overlapping_days_raises(self, mock_rf_fetcher: MagicMock) -> None:
        """< 60 overlapping trading days -> raise ValueError."""
        repo = FakePriceRepository()
        # Only 30 cal days of data (~22 weekdays)
        for ticker in ("VCB", "FPT"):
            repo.batch_insert(_generate_synthetic_bars(ticker, START_DATE, days=30))
        service = FrontierService(price_repo=repo, rf_fetcher=mock_rf_fetcher)
        req = FrontierRequest(
            tickers=("VCB", "FPT"),
            backtest_start=START_DATE,
            backtest_end=START_DATE + timedelta(days=30),
        )
        with pytest.raises(ValueError, match="too few overlapping"):
            service.compute(req)


# =====================================================================
# Edge cases
# =====================================================================


class TestEdgeCases:
    def test_two_ticker_minimum(self, mock_rf_fetcher: MagicMock) -> None:
        """Minimum universe = 2 tickers. Upper bound = 1.0 because 2
        tickers with max 40% each would be infeasible (sum < 1).
        """
        repo = FakePriceRepository()
        for ticker in ("VCB", "FPT"):
            repo.batch_insert(_generate_synthetic_bars(ticker, START_DATE, days=200))
        service = FrontierService(price_repo=repo, rf_fetcher=mock_rf_fetcher)
        req = FrontierRequest(
            tickers=("VCB", "FPT"),
            backtest_start=START_DATE,
            backtest_end=END_DATE,
            upper_bound=1.0,
            n_frontier_points=5,
        )
        result = service.compute(req)
        assert result.universe_size == 2
        assert len(result.frontier_curve.points) == 5

    def test_rf_source_zero(
        self, price_repo_with_data: FakePriceRepository, mock_rf_fetcher: MagicMock
    ) -> None:
        """rf_source='zero' should still fetch via injected (fetcher may return 0)."""
        mock_rf_fetcher.return_value = Decimal("0.00")
        service = FrontierService(price_repo=price_repo_with_data, rf_fetcher=mock_rf_fetcher)
        req = FrontierRequest(
            tickers=TICKERS,
            backtest_start=START_DATE,
            backtest_end=END_DATE,
            rf_source="zero",
        )
        result = service.compute(req)
        assert result.rf_annual_pct == Decimal("0.00")

    def test_different_n_points_values(self, frontier_service: FrontierService) -> None:
        """Verify different n_frontier_points values produce matching curve lengths."""
        for n in [2, 10, 50]:
            req = FrontierRequest(
                tickers=TICKERS,
                backtest_start=START_DATE,
                backtest_end=END_DATE,
                n_frontier_points=n,
            )
            result = frontier_service.compute(req)
            assert len(result.frontier_curve.points) == n
