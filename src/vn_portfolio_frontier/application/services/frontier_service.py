"""FrontierService - orchestrates PriceRepository + FrontierOptimizer for F1.

Application-ring service composing:
    - PriceRepository (port) -> fetch OHLCV history for universe
    - Daily log returns computation (pandas)
    - Covariance + mean return matrix construction
    - Rf fetch (reuses Simulator._fetch_rf_annual_pct inline helper)
    - FrontierOptimizer (domain) -> compute 3 refs + N-point curve

Hex boundary: this service is in application ring per ADR-015, can import
from domain (FrontierOptimizer) and ports (PriceRepository), but NOT from
infrastructure. Caller (Streamlit) wires via AppFactory.

Day 11 F1 Sprint 11.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd

from vn_portfolio_frontier.application.ports.price_repository import PriceRepository
from vn_portfolio_frontier.domain.services.frontier_optimizer import (
    FrontierCurve,
    FrontierOptimizer,
    WeightBounds,
)

# Reuse constants from existing Simulator (Day 6)
TRADING_DAYS_PER_YEAR = 252

VALID_RF_SOURCES = frozenset(
    {
        "zero",
        "vcb_13m_deposit",
        "sbv_refinance",
        "vn_bond_1y",
    }
)


@dataclass(frozen=True)
class FrontierRequest:
    """Input DTO for FrontierService.compute().

    Parameters
    ----------
    tickers : tuple[str, ...]
        Universe (must have >= 2 tickers for frontier to be meaningful).
        Order preserved in output weights dict.
    backtest_start : date
        Historical window start for cov/mu computation.
    backtest_end : date
        Historical window end (inclusive).
    rf_source : str, default 'zero'
        Risk-free rate source. One of: zero | vcb_13m_deposit |
        sbv_refinance | vn_bond_1y. Values from Day 9 Step B schema.
    upper_bound : float, default 0.4
        Max weight per asset (diversification constraint). Default 0.4 =
        40% max, VN retail convention. Range (0, 1].
    n_frontier_points : int, default 20
        Number of discrete points on the frontier curve.
    """

    tickers: tuple[str, ...]
    backtest_start: date
    backtest_end: date
    rf_source: str = "zero"
    upper_bound: float = 0.4
    n_frontier_points: int = 20

    def __post_init__(self) -> None:
        if len(self.tickers) < 2:
            raise ValueError(
                f"FrontierRequest.tickers must have >= 2 tickers, got {len(self.tickers)}"
            )
        if self.backtest_start >= self.backtest_end:
            raise ValueError(
                f"backtest_start ({self.backtest_start}) must be < "
                f"backtest_end ({self.backtest_end})"
            )
        if self.rf_source not in VALID_RF_SOURCES:
            raise ValueError(f"rf_source must be one of {VALID_RF_SOURCES}, got {self.rf_source!r}")
        if not (0.0 < self.upper_bound <= 1.0):
            raise ValueError(f"upper_bound must be in (0, 1], got {self.upper_bound}")
        if self.n_frontier_points < 2:
            raise ValueError(f"n_frontier_points must be >= 2, got {self.n_frontier_points}")


@dataclass(frozen=True)
class FrontierResult:
    """Output DTO for FrontierService.compute().

    Parameters
    ----------
    frontier_curve : FrontierCurve
        Domain object with N curve points + 3 reference portfolios.
    rf_annual_pct : Decimal
        Period-mean Rf % used in max_sharpe + Sharpe ratios.
    universe_size : int
        Number of tickers in universe.
    data_window_days : int
        Days between backtest_start and backtest_end.
    returns_rows : int
        Number of daily return observations used (excludes NaNs).
    """

    frontier_curve: FrontierCurve
    rf_annual_pct: Decimal
    universe_size: int
    data_window_days: int
    returns_rows: int


RfFetcher = Callable[[date, date, str], Decimal]


class FrontierService:
    """Compute efficient frontier for a given universe + period + Rf.

    Parameters
    ----------
    price_repo : PriceRepository
        Port for fetching OHLCV history.
    rf_fetcher : callable
        Function (start, end, source) -> Decimal annual Rf %. Reuses
        RebalanceSimulator._fetch_rf_annual_pct to avoid duplicating
        benchmark schema query logic. Typically bound via AppFactory.

    Notes
    -----
    Thread safety: no cross-call state. Multiple compute() calls are
    independent. Thread safety depends on injected price_repo + rf_fetcher.
    """

    def __init__(self, price_repo: PriceRepository, rf_fetcher: RfFetcher) -> None:
        self._price_repo = price_repo
        self._rf_fetcher = rf_fetcher

    def compute(self, request: FrontierRequest) -> FrontierResult:
        """Compute efficient frontier end-to-end.

        Flow:
            1. Load OHLCV history for each ticker (one query each)
            2. Build price matrix (date x ticker) + compute log returns
            3. Fetch Rf (period mean annual %) via injected rf_fetcher
            4. Compute mu (daily mean) + cov (daily covariance) matrices
            5. Delegate to FrontierOptimizer for 3 refs + N-point curve
            6. Return FrontierResult DTO

        Returns
        -------
        FrontierResult
            Carrying FrontierCurve + metadata (Rf used, universe size, data window).

        Raises
        ------
        ValueError
            From FrontierRequest validation, or if price history is too thin
            (< 60 days of overlapping observations) for stable cov estimate.
        """
        # 1. Load price history for each ticker
        price_series_per_ticker = {}
        for ticker in request.tickers:
            bars = self._price_repo.get_ohlcv(
                ticker=ticker,
                start=request.backtest_start,
                end=request.backtest_end,
            )
            if not bars:
                raise ValueError(f"FrontierService: no price data for ticker {ticker}")
            prices = pd.Series(
                {bar.trade_date: float(bar.close) for bar in bars},
                name=ticker,
            )
            price_series_per_ticker[ticker] = prices

        # 2. Build aligned price matrix (date x ticker), drop days missing any ticker
        price_df = pd.DataFrame(price_series_per_ticker).sort_index().dropna(how="any")
        if len(price_df) < 60:
            raise ValueError(
                f"FrontierService: too few overlapping trading days ({len(price_df)}) "
                f"for stable covariance estimate; need >= 60. "
                f"Widen the backtest window or reduce ticker count."
            )

        # Compute daily log returns
        returns_df = np.log(price_df / price_df.shift(1)).dropna(how="any")

        # 3. Fetch Rf via injected helper (reuses Simulator Day 9 Step B logic)
        rf_annual_pct = self._rf_fetcher(
            request.backtest_start, request.backtest_end, request.rf_source
        )
        rf_daily = float(rf_annual_pct) / 100.0 / TRADING_DAYS_PER_YEAR

        # 4. Compute mu + cov (daily, align ordering to request.tickers)
        mu = returns_df.mean().reindex(list(request.tickers))
        cov = returns_df.cov().reindex(index=list(request.tickers), columns=list(request.tickers))

        # 5. Delegate to domain optimizer
        optimizer = FrontierOptimizer()
        bounds = WeightBounds(lower=0.0, upper=request.upper_bound)
        curve = optimizer.compute_frontier(
            mu=mu,
            cov=cov,
            points=request.n_frontier_points,
            bounds=bounds,
            rf_daily=rf_daily,
        )

        return FrontierResult(
            frontier_curve=curve,
            rf_annual_pct=rf_annual_pct,
            universe_size=len(request.tickers),
            data_window_days=(request.backtest_end - request.backtest_start).days,
            returns_rows=len(returns_df),
        )
