"""FrontierOptimizer - Efficient Frontier computation via scipy.optimize.

Pure math domain service. Zero infrastructure deps - takes (cov, mu, Rf, bounds)
and returns PortfolioWeights / FrontierCurve value objects. Testable without
any external vendor SDK or auth.

ADR-017 (updated 20/10): Use scipy.optimize (SLSQP method) for all 4 compute
functions (min_variance, max_sharpe, risk_parity, frontier). Previously
vnstock_quant.portfolio was planned but it requires valid vnstock auth
internally - couples optimization math to vendor SDK state. Scipy keeps
domain layer pure per ADR-015 Hexagonal boundaries.

Rationale for scipy:
    - Industry-standard: scipy.optimize is default in LEAN/zipline/backtrader
    - No vendor auth dependency - works offline, mock-friendly for tests
    - Markowitz 1952 QP solver via SLSQP (Sequential Least Squares Programming)
    - Deterministic + reproducible (same inputs -> same outputs)
    - Already standard dep in P1 vn-portfolio-optimizer
    - Zero additional install footprint

Performance note:
    - scipy SLSQP ~ms per optimization at 6-30 asset scale
    - Full 20-point frontier: ~0.5-1s total
    - vnstock_quant.portfolio (Rust-core) would be ~25x faster but not critical
      at this scale; perf matters more at 100+ asset portfolios

See also:
    - tests/unit/test_frontier_optimizer.py (unit tests)
    - vn_portfolio_frontier.application.services.frontier_service (orchestrator)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd
from scipy.optimize import minimize

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class WeightBounds:
    """Per-asset weight constraint [lower, upper]."""

    lower: float = 0.0
    upper: float = 1.0

    def __post_init__(self) -> None:
        if self.lower < 0.0:
            raise ValueError(
                f"WeightBounds.lower must be >= 0 (no short selling), got {self.lower}"
            )
        if self.upper > 1.0:
            raise ValueError(f"WeightBounds.upper must be <= 1.0, got {self.upper}")
        if self.lower > self.upper:
            raise ValueError(f"WeightBounds.lower ({self.lower}) must be <= upper ({self.upper})")


@dataclass(frozen=True)
class PortfolioWeights:
    """Immutable value object for a single portfolio allocation."""

    label: str
    weights: dict[str, float]
    expected_return_annual_pct: Decimal
    volatility_annual_pct: Decimal
    sharpe: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("PortfolioWeights.label must not be empty")
        if not self.weights:
            raise ValueError("PortfolioWeights.weights must not be empty")
        weight_sum = sum(self.weights.values())
        if abs(weight_sum - 1.0) > 0.01:
            raise ValueError(
                f"PortfolioWeights.weights must sum to ~1.0 (tolerance 1%), "
                f"got {weight_sum:.4f} for label '{self.label}'"
            )


@dataclass(frozen=True)
class FrontierCurve:
    """Efficient frontier curve + 3 reference portfolios."""

    points: tuple[PortfolioWeights, ...]
    ref_min_variance: PortfolioWeights
    ref_max_sharpe: PortfolioWeights
    ref_risk_parity: PortfolioWeights
    tickers: tuple[str, ...]

    def as_dataframe(self) -> pd.DataFrame:
        """Return curve as DataFrame for plotting."""
        rows = []
        for p in self.points:
            row = {
                "label": p.label,
                "expected_return": float(p.expected_return_annual_pct),
                "volatility": float(p.volatility_annual_pct),
                "sharpe": float(p.sharpe) if p.sharpe is not None else None,
            }
            for ticker, weight in p.weights.items():
                row[f"w_{ticker}"] = weight
            rows.append(row)
        return pd.DataFrame(rows)

    def reference_portfolios_summary(self) -> list[tuple[str, PortfolioWeights]]:
        """Return (display_label, portfolio) tuples for 3 reference portfolios."""
        return [
            ("Min Variance", self.ref_min_variance),
            ("Max Sharpe", self.ref_max_sharpe),
            ("Risk Parity", self.ref_risk_parity),
        ]


# =====================================================================
# scipy.optimize helpers (SLSQP - Sequential Least Squares Programming)
# =====================================================================


def _scipy_min_variance(cov: pd.DataFrame, bounds: WeightBounds) -> pd.Series:
    """Global minimum variance portfolio via SLSQP.

    Solves: min w^T Sigma w s.t. sum(w) = 1, lower <= w_i <= upper.
    """
    n = len(cov)
    cov_arr = cov.to_numpy(dtype=float)
    x0 = np.ones(n) / n

    def objective(w: np.ndarray) -> float:
        return float(w @ cov_arr @ w)

    constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
    bounds_list = [(bounds.lower, bounds.upper)] * n

    result = minimize(
        objective,
        x0,
        method="SLSQP",
        bounds=bounds_list,
        constraints=constraints,
        options={"ftol": 1e-10, "maxiter": 500},
    )
    if not result.success:
        raise RuntimeError(
            f"scipy SLSQP min_variance failed: {result.message}. "
            f"Covariance may be ill-conditioned or bounds infeasible."
        )
    return pd.Series(result.x, index=cov.index)


def _scipy_max_sharpe(
    mu: pd.Series, cov: pd.DataFrame, rf: float, bounds: WeightBounds
) -> pd.Series:
    """Maximum Sharpe (tangency) portfolio via SLSQP.

    Solves: max (w^T mu - rf) / sqrt(w^T Sigma w)
    Equivalent minimize: -(w^T mu - rf) / sqrt(w^T Sigma w)
    """
    n = len(cov)
    cov_arr = cov.to_numpy(dtype=float)
    mu_arr = mu.reindex(cov.index).fillna(0.0).to_numpy(dtype=float)
    x0 = np.ones(n) / n

    def neg_sharpe(w: np.ndarray) -> float:
        ret = float(w @ mu_arr)
        var = float(w @ cov_arr @ w)
        if var < 1e-12:
            return 0.0
        vol = float(np.sqrt(var))
        return -(ret - rf) / vol

    constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
    bounds_list = [(bounds.lower, bounds.upper)] * n

    result = minimize(
        neg_sharpe,
        x0,
        method="SLSQP",
        bounds=bounds_list,
        constraints=constraints,
        options={"ftol": 1e-10, "maxiter": 500},
    )
    if not result.success:
        raise RuntimeError(f"scipy SLSQP max_sharpe failed: {result.message}")
    return pd.Series(result.x, index=cov.index)


def _scipy_risk_parity(cov: pd.DataFrame) -> pd.Series:
    """Equal risk contribution portfolio (Roncalli 2013).

    Solves: minimize variance of risk contributions.
    Each ticker contributes equal portion to total portfolio variance.
    """
    n = len(cov)
    cov_arr = cov.to_numpy(dtype=float)
    x0 = np.ones(n) / n

    def risk_contrib_variance(w: np.ndarray) -> float:
        var = float(w @ cov_arr @ w)
        if var < 1e-12:
            return 1e10
        vol = float(np.sqrt(var))
        marginal_contrib = cov_arr @ w / vol
        risk_contrib = w * marginal_contrib
        target = vol / n
        return float(np.sum((risk_contrib - target) ** 2))

    constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
    bounds_list = [(1e-4, 1.0)] * n  # Risk parity needs strictly positive weights

    result = minimize(
        risk_contrib_variance,
        x0,
        method="SLSQP",
        bounds=bounds_list,
        constraints=constraints,
        options={"ftol": 1e-10, "maxiter": 1000},
    )
    if not result.success:
        raise RuntimeError(f"scipy SLSQP risk_parity failed: {result.message}")
    return pd.Series(result.x, index=cov.index)


def _scipy_frontier(
    mu: pd.Series, cov: pd.DataFrame, n_points: int, bounds: WeightBounds
) -> pd.DataFrame:
    """Efficient frontier curve by sweeping target returns.

    For each target return R: min w^T Sigma w s.t. w^T mu = R, sum(w) = 1, bounds.
    Returns DataFrame with 'expected_return' + 'volatility' columns, plus
    .attrs['weights'] DataFrame (n_points x n_assets) matching vnstock_quant API.
    """
    n = len(cov)
    cov_arr = cov.to_numpy(dtype=float)
    mu_arr = mu.reindex(cov.index).fillna(0.0).to_numpy(dtype=float)

    # Find min variance return (left endpoint) and max return (right endpoint)
    mv_series = _scipy_min_variance(cov, bounds)
    mv_ret = float(mv_series.to_numpy() @ mu_arr)

    # Max return given bounds: concentrate in highest-mu assets up to upper bound
    sorted_idx = np.argsort(mu_arr)[::-1]
    max_w = np.zeros(n)
    remaining = 1.0
    for i in sorted_idx:
        alloc = min(bounds.upper, remaining)
        max_w[i] = alloc
        remaining -= alloc
        if remaining <= 1e-6:
            break
    max_ret = float(max_w @ mu_arr)

    if max_ret <= mv_ret + 1e-9:
        # Degenerate: all assets have same expected return
        max_ret = mv_ret + 1e-6

    target_returns = np.linspace(mv_ret, max_ret, n_points)

    curve_rows = []
    weights_rows = []
    for target in target_returns:
        x0 = np.ones(n) / n

        def objective(w: np.ndarray) -> float:
            return float(w @ cov_arr @ w)

        constraints = [
            {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)},
            {"type": "eq", "fun": lambda w, t=target: float(w @ mu_arr - t)},
        ]
        bounds_list = [(bounds.lower, bounds.upper)] * n

        result = minimize(
            objective,
            x0,
            method="SLSQP",
            bounds=bounds_list,
            constraints=constraints,
            options={"ftol": 1e-10, "maxiter": 500},
        )

        if result.success:
            w = result.x
            ret = float(w @ mu_arr)
            vol = float(np.sqrt(w @ cov_arr @ w))
            curve_rows.append({"expected_return": ret, "volatility": vol})
            weights_rows.append(w)
        else:
            # Skip infeasible point (should be rare with proper bounds)
            continue

    if not curve_rows:
        raise RuntimeError(
            "scipy frontier: no feasible points. Check covariance matrix "
            "+ bounds + target return range."
        )

    df = pd.DataFrame(curve_rows)
    weights_df = pd.DataFrame(weights_rows, columns=cov.index)
    df.attrs["weights"] = weights_df
    return df


# =====================================================================
# Public API -- FrontierOptimizer class
# =====================================================================


class FrontierOptimizer:
    """Compute efficient frontier using scipy.optimize (SLSQP method).

    Pure math wrapper around 4 scipy-based helper functions. Returns
    PortfolioWeights/FrontierCurve DTOs. Handles input validation + annualization
    + Sharpe computation.
    """

    def compute_frontier(
        self,
        mu: pd.Series,
        cov: pd.DataFrame,
        points: int = 20,
        bounds: WeightBounds | None = None,
        rf_daily: float = 0.0,
    ) -> FrontierCurve:
        """Compute the full efficient frontier plus 3 reference portfolios.

        Parameters
        ----------
        mu : pd.Series
            Expected daily returns per asset, indexed by ticker.
        cov : pd.DataFrame
            Daily covariance matrix, square, rows/cols indexed by ticker.
        points : int, default 20
            Number of discrete points on the frontier curve.
        bounds : WeightBounds, optional
            Per-asset weight constraints. Default WeightBounds() = [0, 1].
        rf_daily : float, default 0.0
            Daily risk-free rate for max_sharpe + Sharpe computations.

        Returns
        -------
        FrontierCurve
            N frontier points + 3 reference portfolios + ticker list.
        """
        if points < 2:
            raise ValueError(
                f"FrontierOptimizer.compute_frontier: points must be >= 2, got {points}"
            )
        if not mu.index.equals(cov.index):
            raise ValueError(
                f"mu index ({list(mu.index)}) must equal cov index ({list(cov.index)})"
            )

        b = bounds or WeightBounds()
        tickers = tuple(cov.index)

        # 1. Three reference portfolios
        mv_series = _scipy_min_variance(cov, b)
        ms_series = _scipy_max_sharpe(mu, cov, rf_daily, b)
        rp_series = _scipy_risk_parity(cov)

        ref_mv = self._series_to_portfolio(
            mv_series, "min_variance", mu=mu, cov=cov, rf_daily=rf_daily
        )
        ref_ms = self._series_to_portfolio(
            ms_series, "max_sharpe", mu=mu, cov=cov, rf_daily=rf_daily
        )
        ref_rp = self._series_to_portfolio(
            rp_series, "risk_parity", mu=mu, cov=cov, rf_daily=rf_daily
        )

        # 2. Efficient frontier curve
        fr_df = _scipy_frontier(mu, cov, points, b)
        fr_weights = fr_df.attrs["weights"]

        curve_points = tuple(
            self._row_to_portfolio(
                index=i,
                return_daily=float(row["expected_return"]),
                volatility_daily=float(row["volatility"]),
                weights_row=fr_weights.iloc[i],
                rf_daily=rf_daily,
            )
            for i, row in fr_df.iterrows()
        )

        return FrontierCurve(
            points=curve_points,
            ref_min_variance=ref_mv,
            ref_max_sharpe=ref_ms,
            ref_risk_parity=ref_rp,
            tickers=tickers,
        )

    @staticmethod
    def _series_to_portfolio(
        series: pd.Series,
        label: str,
        mu: pd.Series,
        cov: pd.DataFrame,
        rf_daily: float,
    ) -> PortfolioWeights:
        """Convert scipy output Series -> PortfolioWeights DTO with annualized metrics."""
        weights = {str(k): float(v) for k, v in series.items()}

        w = series.reindex(cov.index).fillna(0.0).to_numpy(dtype=float)
        mu_arr = mu.reindex(cov.index).fillna(0.0).to_numpy(dtype=float)
        cov_arr = cov.to_numpy(dtype=float)

        daily_return = float(w @ mu_arr)
        daily_variance = float(w @ cov_arr @ w)
        daily_vol = float(np.sqrt(max(daily_variance, 0.0)))

        annual_return_pct = Decimal(str(round(daily_return * TRADING_DAYS_PER_YEAR * 100, 4)))
        annual_vol_pct = Decimal(str(round(daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR) * 100, 4)))

        rf_annual_pct = rf_daily * TRADING_DAYS_PER_YEAR * 100
        sharpe = None
        if annual_vol_pct > 0:
            sharpe = Decimal(
                str(
                    round(
                        (float(annual_return_pct) - rf_annual_pct) / float(annual_vol_pct),
                        4,
                    )
                )
            )

        return PortfolioWeights(
            label=label,
            weights=weights,
            expected_return_annual_pct=annual_return_pct,
            volatility_annual_pct=annual_vol_pct,
            sharpe=sharpe,
        )

    @staticmethod
    def _row_to_portfolio(
        index: int,
        return_daily: float,
        volatility_daily: float,
        weights_row: pd.Series,
        rf_daily: float,
    ) -> PortfolioWeights:
        """Convert single frontier row -> PortfolioWeights DTO."""
        weights = {str(k): float(v) for k, v in weights_row.items()}

        annual_return_pct = Decimal(str(round(return_daily * TRADING_DAYS_PER_YEAR * 100, 4)))
        annual_vol_pct = Decimal(
            str(round(volatility_daily * np.sqrt(TRADING_DAYS_PER_YEAR) * 100, 4))
        )

        rf_annual_pct = rf_daily * TRADING_DAYS_PER_YEAR * 100
        sharpe = None
        if annual_vol_pct > 0:
            sharpe = Decimal(
                str(
                    round(
                        (float(annual_return_pct) - rf_annual_pct) / float(annual_vol_pct),
                        4,
                    )
                )
            )

        return PortfolioWeights(
            label=f"frontier_point_{index}",
            weights=weights,
            expected_return_annual_pct=annual_return_pct,
            volatility_annual_pct=annual_vol_pct,
            sharpe=sharpe,
        )
