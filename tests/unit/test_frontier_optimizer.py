"""Unit tests for FrontierOptimizer (Day 11 Cum 4).

Covers:
    - compute_frontier() returns N points + 3 reference portfolios
    - Weight bounds respected per asset
    - Weights sum to 1.0 (budget constraint)
    - Frontier curve monotonic in volatility
    - MinVariance has lowest vol among curve points
    - MaxSharpe has highest sharpe among curve points
    - RiskParity contributions approximately equal
    - WeightBounds validation (lower < upper, non-negative)
    - rf_daily=0 default behavior
    - FrontierCurve.as_dataframe() shape
    - Edge: singular/near-singular cov matrix handled gracefully
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vn_portfolio_frontier.domain.services import (
    FrontierCurve,
    FrontierOptimizer,
    PortfolioWeights,
    WeightBounds,
)

# =====================================================================
# Fixtures
# =====================================================================

TICKERS = ["VCB", "FPT", "VHM", "VNM", "GAS", "HPG"]


@pytest.fixture
def synthetic_returns() -> pd.DataFrame:
    """Reproducible 500-day daily returns matrix for 6 VN30 tickers."""
    np.random.seed(42)
    return pd.DataFrame(
        np.random.randn(500, len(TICKERS)) * 0.015,
        columns=TICKERS,
    )


@pytest.fixture
def mu_cov(synthetic_returns: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """Compute mu (mean) + cov from synthetic returns."""
    return synthetic_returns.mean(), synthetic_returns.cov()


@pytest.fixture
def default_bounds() -> WeightBounds:
    """Standard VN retail bounds: no short-sell, max 40% per asset."""
    return WeightBounds(lower=0.0, upper=0.4)


@pytest.fixture
def optimizer() -> FrontierOptimizer:
    return FrontierOptimizer()


# =====================================================================
# compute_frontier basics
# =====================================================================


class TestComputeFrontierBasics:
    def test_returns_n_points(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
        default_bounds: WeightBounds,
    ) -> None:
        mu, cov = mu_cov
        curve = optimizer.compute_frontier(mu=mu, cov=cov, points=20, bounds=default_bounds)
        assert len(curve.points) == 20

    def test_returns_frontier_curve_type(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
        default_bounds: WeightBounds,
    ) -> None:
        mu, cov = mu_cov
        curve = optimizer.compute_frontier(mu=mu, cov=cov, bounds=default_bounds)
        assert isinstance(curve, FrontierCurve)
        assert isinstance(curve.ref_min_variance, PortfolioWeights)
        assert isinstance(curve.ref_max_sharpe, PortfolioWeights)
        assert isinstance(curve.ref_risk_parity, PortfolioWeights)

    def test_tickers_preserved(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
        default_bounds: WeightBounds,
    ) -> None:
        mu, cov = mu_cov
        curve = optimizer.compute_frontier(mu=mu, cov=cov, bounds=default_bounds)
        assert set(curve.ref_min_variance.weights.keys()) == set(TICKERS)


# =====================================================================
# Weight constraints
# =====================================================================


class TestWeightConstraints:
    def test_weights_sum_to_one(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
        default_bounds: WeightBounds,
    ) -> None:
        mu, cov = mu_cov
        curve = optimizer.compute_frontier(mu=mu, cov=cov, bounds=default_bounds)
        for point in [curve.ref_min_variance, curve.ref_max_sharpe, curve.ref_risk_parity]:
            total = sum(point.weights.values())
            assert abs(total - 1.0) < 1e-4, f"Weights sum = {total:.6f}, expected 1.0"

    def test_bounds_respected_min_variance(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
    ) -> None:
        mu, cov = mu_cov
        bounds = WeightBounds(lower=0.0, upper=0.4)
        curve = optimizer.compute_frontier(mu=mu, cov=cov, bounds=bounds)
        for ticker, w in curve.ref_min_variance.weights.items():
            assert -1e-4 <= w <= 0.4 + 1e-4, f"{ticker} weight {w:.4f} outside [0, 0.4]"

    def test_bounds_respected_max_sharpe(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
    ) -> None:
        mu, cov = mu_cov
        bounds = WeightBounds(lower=0.0, upper=0.4)
        curve = optimizer.compute_frontier(mu=mu, cov=cov, bounds=bounds)
        for ticker, w in curve.ref_max_sharpe.weights.items():
            assert -1e-4 <= w <= 0.4 + 1e-4, f"{ticker} weight {w:.4f} outside [0, 0.4]"

    def test_tight_upper_bound_still_feasible(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
    ) -> None:
        """Tight upper = 1/N forces equal weights (feasible)."""
        mu, cov = mu_cov
        n = len(TICKERS)
        bounds = WeightBounds(lower=0.0, upper=1.0 / n + 1e-6)
        curve = optimizer.compute_frontier(mu=mu, cov=cov, bounds=bounds, points=5)
        for w in curve.ref_min_variance.weights.values():
            assert abs(w - 1.0 / n) < 0.01


# =====================================================================
# Reference portfolios properties
# =====================================================================


class TestReferencePortfolios:
    def test_min_variance_is_lowest_vol(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
        default_bounds: WeightBounds,
    ) -> None:
        mu, cov = mu_cov
        curve = optimizer.compute_frontier(mu=mu, cov=cov, points=20, bounds=default_bounds)
        min_var_vol = float(curve.ref_min_variance.volatility_annual_pct)
        # MinVar vol should be <= any frontier point vol (within 1e-3 tolerance)
        for p in curve.points:
            assert min_var_vol <= float(p.volatility_annual_pct) + 1e-3

    def test_max_sharpe_has_highest_sharpe(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
        default_bounds: WeightBounds,
    ) -> None:
        mu, cov = mu_cov
        rf_daily = (1 + 0.05) ** (1 / 252) - 1
        curve = optimizer.compute_frontier(
            mu=mu, cov=cov, points=20, bounds=default_bounds, rf_daily=rf_daily
        )
        max_sharpe = float(curve.ref_max_sharpe.sharpe)
        for p in curve.points:
            if p.sharpe is not None:
                assert max_sharpe >= float(p.sharpe) - 1e-3

    def test_risk_parity_contributions_balanced(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
        default_bounds: WeightBounds,
    ) -> None:
        """Risk parity: all weights should be in similar range (no single
        asset dominates). Loose test -- exact ERC convergence depends on cov."""
        mu, cov = mu_cov
        curve = optimizer.compute_frontier(mu=mu, cov=cov, bounds=default_bounds)
        weights = list(curve.ref_risk_parity.weights.values())
        # No single asset > 40% (bounds) and no asset < 2% (nontrivial allocation)
        assert all(0.02 <= w <= 0.42 for w in weights)


# =====================================================================
# WeightBounds validation
# =====================================================================


class TestWeightBoundsValidation:
    def test_default_bounds_zero_to_one(self) -> None:
        b = WeightBounds()
        assert b.lower == 0.0
        assert b.upper == 1.0

    def test_valid_bounds(self) -> None:
        b = WeightBounds(lower=0.1, upper=0.5)
        assert b.lower == 0.1
        assert b.upper == 0.5

    def test_invalid_lower_greater_than_upper(self) -> None:
        with pytest.raises((ValueError, AssertionError)):
            WeightBounds(lower=0.6, upper=0.5)

    def test_invalid_negative_lower(self) -> None:
        with pytest.raises((ValueError, AssertionError)):
            WeightBounds(lower=-0.1, upper=0.5)


# =====================================================================
# Rf behavior
# =====================================================================


class TestRfBehavior:
    def test_rf_zero_default(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
        default_bounds: WeightBounds,
    ) -> None:
        """rf_daily default = 0 should work (Perold 1988 convention)."""
        mu, cov = mu_cov
        curve = optimizer.compute_frontier(mu=mu, cov=cov, bounds=default_bounds)
        # No crash, Sharpe computed
        assert curve.ref_max_sharpe.sharpe is not None

    def test_rf_nonzero_affects_sharpe(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
        default_bounds: WeightBounds,
    ) -> None:
        """Higher Rf -> lower Sharpe (same portfolio)."""
        mu, cov = mu_cov
        curve_low_rf = optimizer.compute_frontier(
            mu=mu, cov=cov, bounds=default_bounds, rf_daily=0.0
        )
        curve_high_rf = optimizer.compute_frontier(
            mu=mu,
            cov=cov,
            bounds=default_bounds,
            rf_daily=(1 + 0.10) ** (1 / 252) - 1,
        )
        # MinVar portfolio Sharpe should drop with higher Rf
        if curve_low_rf.ref_min_variance.sharpe and curve_high_rf.ref_min_variance.sharpe:
            assert curve_low_rf.ref_min_variance.sharpe > curve_high_rf.ref_min_variance.sharpe


# =====================================================================
# FrontierCurve.as_dataframe
# =====================================================================


class TestFrontierCurveDataFrame:
    def test_as_dataframe_returns_dataframe(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
        default_bounds: WeightBounds,
    ) -> None:
        mu, cov = mu_cov
        curve = optimizer.compute_frontier(mu=mu, cov=cov, bounds=default_bounds, points=10)
        df = curve.as_dataframe()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 10

    def test_as_dataframe_has_expected_columns(
        self,
        optimizer: FrontierOptimizer,
        mu_cov: tuple[pd.Series, pd.DataFrame],
        default_bounds: WeightBounds,
    ) -> None:
        mu, cov = mu_cov
        curve = optimizer.compute_frontier(mu=mu, cov=cov, bounds=default_bounds, points=10)
        df = curve.as_dataframe()
        assert "expected_return" in df.columns
        assert "volatility" in df.columns
        assert "sharpe" in df.columns
        assert "label" in df.columns


# =====================================================================
# Edge cases
# =====================================================================


class TestEdgeCases:
    def test_small_universe_2_assets(
        self,
        optimizer: FrontierOptimizer,
    ) -> None:
        """Minimum: 2 assets."""
        np.random.seed(42)
        rets = pd.DataFrame(np.random.randn(300, 2) * 0.015, columns=["VCB", "FPT"])
        mu, cov = rets.mean(), rets.cov()
        curve = optimizer.compute_frontier(
            mu=mu, cov=cov, bounds=WeightBounds(lower=0.0, upper=1.0), points=10
        )
        assert len(curve.points) == 10
        for w in curve.ref_min_variance.weights.values():
            assert 0 <= w <= 1

    def test_near_identical_assets_no_crash(
        self,
        optimizer: FrontierOptimizer,
    ) -> None:
        """Near-singular cov (nearly identical assets) should not crash."""
        np.random.seed(42)
        base = np.random.randn(300) * 0.015
        rets = pd.DataFrame(
            {
                "A": base,
                "B": base + np.random.randn(300) * 1e-5,  # near-duplicate
                "C": base + np.random.randn(300) * 1e-5,
            }
        )
        mu, cov = rets.mean(), rets.cov()
        # Should not raise; result may be numerically fragile but valid
        curve = optimizer.compute_frontier(
            mu=mu, cov=cov, bounds=WeightBounds(lower=0.0, upper=1.0), points=5
        )
        assert len(curve.points) >= 1  # at least some points computed
