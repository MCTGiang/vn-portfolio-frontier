"""ThresholdBandStrategy — rebalance khi weight drift vượt ngưỡng band_bps.

Concrete subclass của BaseStrategy. Target weights là static (Portfolio.target_weights
set at init); trigger khi max absolute drift giữa current vs target > band_bps.

Example:
    - Target: VCB 50% + FPT 50% (set at Portfolio.target_weights)
    - Current (sau price move): VCB 55% + FPT 45%
    - Drift: VCB +500 bps, FPT -500 bps → max drift 500 bps
    - Band: 500 bps → không trigger (<=band = hold)
    - Band: 400 bps → trigger (>band = rebalance back to 50/50)

Design decisions:
    - **Static target**: compute_target_weights trả về Portfolio.target_weights
      không recompute. Alternative: recompute từ Markowitz covariance mỗi lần
      → defer Sprint 14 (adds complexity + requires FrontierOptimizer injection).
    - **Max drift test** (not avg or median): defensive. 1 ticker lệch mạnh
      đã đủ lý do rebalance; không đợi "nhiều ticker lệch cùng lúc".
    - **band_bps as int** không Decimal: band comparison in bps domain,
      precision loss float eps << bps granularity. Faster.
    - **Reason label "band_drift"**: match CHECK constraint trên
      simulation.rebalance_decision.reason.

Patterns considered + rejected cho F2 Sprint 11 MUST tier:
    - Observer: không fit vì rebalance là explicit user action, không event-driven
    - Chain of Responsibility: chỉ 1 strategy active, không cascade
    - State: strategies không chuyển state, user chọn upfront
"""

from __future__ import annotations

from vn_portfolio_frontier.domain.entities.portfolio import Portfolio
from vn_portfolio_frontier.domain.entities.rebalance_context import RebalanceContext
from vn_portfolio_frontier.domain.services.cost_calculator import CostCalculator
from vn_portfolio_frontier.domain.strategies.base import BaseStrategy

# Default band tolerance for VN30 rebalancing (industry convention 5%)
DEFAULT_BAND_BPS = 500

# Guard rails
_MAX_BAND_BPS = 10_000  # 100% drift upper bound (never trigger practically)
_MIN_BAND_BPS = 1  # 0.01% minimum (hyper-sensitive edge case for stress test)


class ThresholdBandStrategy(BaseStrategy):
    """Trigger rebalance khi max weight drift > band_bps.

    Parameters
    ----------
    cost_calculator : CostCalculator
        Injected cost service (per ADR-012 user-input parameters).
    band_bps : int, default 500
        Drift tolerance in basis points. 500 bps = 5% drift tolerance.
        Range [1, 10000]. Typical values:
            - 100 bps (1%): aggressive, high turnover
            - 500 bps (5%): balanced default
            - 1000 bps (10%): conservative, low turnover

    Raises
    ------
    ValueError
        If band_bps out of [1, 10000] range.

    Examples
    --------
    >>> from decimal import Decimal
    >>> from vn_portfolio_frontier.domain.services.cost_calculator import CostCalculator
    >>> calc = CostCalculator(brokerage_pct=Decimal("0.0015"))
    >>> strategy = ThresholdBandStrategy(calc, band_bps=500)
    >>> strategy.name
    'threshold_band'
    >>> strategy.band_bps
    500
    """

    name = "threshold_band"

    def __init__(
        self,
        cost_calculator: CostCalculator,
        band_bps: int = DEFAULT_BAND_BPS,
    ) -> None:
        super().__init__(cost_calculator)
        if not (_MIN_BAND_BPS <= band_bps <= _MAX_BAND_BPS):
            raise ValueError(
                f"ThresholdBandStrategy.band_bps must be in [{_MIN_BAND_BPS}, "
                f"{_MAX_BAND_BPS}], got {band_bps}. Hint: 500 = 5% drift tolerance."
            )
        self.band_bps = band_bps

    def compute_target_weights(
        self,
        current: Portfolio,
        context: RebalanceContext,
    ) -> dict[str, float]:
        """Return Portfolio.target_weights unchanged (static strategy).

        Parameters
        ----------
        current : Portfolio
            Current portfolio; its `target_weights` is the strategy target.
        context : RebalanceContext
            Unused for static strategy (reserved for dynamic subclass).

        Returns
        -------
        dict[str, float]
            Shallow copy of current.target_weights (prevent accidental
            mutation by caller).
        """
        return dict(current.target_weights)

    def should_trigger(
        self,
        current: Portfolio,
        target: dict[str, float],
        context: RebalanceContext,
    ) -> bool:
        """Return True nếu max absolute weight drift > band_bps.

        Parameters
        ----------
        current : Portfolio
            Current state.
        target : dict[str, float]
            Target weights (output of compute_target_weights).
        context : RebalanceContext
            Market snapshot — used để tính current weights từ prices.

        Returns
        -------
        bool
            True nếu ANY ticker in target has |current_weight - target| × 10000
            > band_bps; else False.

        Notes
        -----
        - Current weight for ticker không trong Portfolio.holdings = 0.0
          (treated as flat position with full drift to fund it)
        - Target weights for ticker không trong Portfolio = fully "below band"
          nếu target == 0 (no action needed on missing-untarget tickers)
        - Max drift test (not avg): defensive, 1 ticker đủ lý do rebalance
        """
        current_weights = current.get_weights(context.prices)

        max_drift_bps = 0.0
        for ticker, target_weight in target.items():
            current_weight = current_weights.get(ticker, 0.0)
            drift_bps = abs(current_weight - target_weight) * 10000.0
            if drift_bps > max_drift_bps:
                max_drift_bps = drift_bps

        return max_drift_bps > self.band_bps

    def _reason(self) -> str:
        """Return 'band_drift' label for RebalanceDecision.reason."""
        return "band_drift"
