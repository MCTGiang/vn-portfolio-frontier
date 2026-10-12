"""BaseStrategy - abstract Template Method cho rebalance strategies.

Pattern: Template Method (GoF Behavioral) combined with Strategy (GoF Behavioral).
Base class `BaseStrategy` defines the common `rebalance()` flow that must not be
overridden; concrete subclasses only fill 2 hook methods: `compute_target_weights`
and `should_trigger`. Shared logic `_compute_orders` + `_cost_calculator.compute`
lives in the base class.

Flow (per ADR-015 section 2.3):
    1. target = compute_target_weights()         [subclass hook]
    2. if not should_trigger(): no_action        [subclass hook]
    3. orders = _compute_orders(target)          [shared base logic]
    4. costs = _cost_calculator.compute(orders)  [delegate to service]
    5. return RebalanceDecision(orders, costs)   [shared base logic]

Why Template Method here:
    - 4 strategies trong Sprint 11-12 (ThresholdBand, CalendarMonthly,
      FixedWindow, Hybrid) share identical steps 3-5. Copy-pasting
      that logic 4 times -> maintenance nightmare + bugs when fixing orders logic
      in 1 place but not others.
    - Steps 1-2 are strategy-specific (band drift vs calendar date), so
      they are split into hooks for subclasses to override.
    - Zero-cost at runtime (just Python method dispatch), unlike visitor
      pattern alternatives.

Patterns considered + rejected:
    - **Strategy pattern alone** (no Template Method): each strategy
      implements both flow + specific logic -> copy-paste steps 3-5. Rejected.
    - **Chain of Responsibility**: does not fit - only 1 strategy is active per
      run, no "pass to next handler" semantics.
    - **State pattern**: strategies do not transition state between themselves, the user
      picks one upfront -> overkill.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from vn_portfolio_frontier.domain.entities.order import Order, OrderSide
from vn_portfolio_frontier.domain.entities.portfolio import Portfolio
from vn_portfolio_frontier.domain.entities.rebalance_context import RebalanceContext
from vn_portfolio_frontier.domain.entities.rebalance_decision import RebalanceDecision
from vn_portfolio_frontier.domain.services.cost_calculator import CostCalculator


class BaseStrategy(ABC):
    """Abstract base for every rebalance strategy - Template Method pattern.

    Parameters
    ----------
    cost_calculator : CostCalculator
        Injected service that computes TradingCost for orders. Dependency injection
        pattern: strategy does not construct CostCalculator but receives it via
        constructor, allowing Factory wiring + tests injecting a fake.

    Attributes
    ----------
    name : str
        Subclass sets the strategy name ("threshold_band", "calendar_monthly", etc.).
        Must match CHECK constraint on simulation.rebalance_run.strategy_name.

    Notes
    -----
    - Subclass MUST set `self.name` trong __init__
    - Subclass MUST implement `compute_target_weights` + `should_trigger`
    - Subclass MAY override `_reason()` to customize the decision.reason label
    - Subclass should NOT override `rebalance()` - breaks Template Method
    """

    name: str = ""

    def __init__(self, cost_calculator: CostCalculator) -> None:
        self._cost_calculator = cost_calculator

    def rebalance(
        self,
        current: Portfolio,
        context: RebalanceContext,
    ) -> RebalanceDecision:
        """Evaluate strategy at `context.as_of` and return a RebalanceDecision.

        Template Method - DO NOT override in subclass.

        Parameters
        ----------
        current : Portfolio
            Portfolio before potential rebalance. Read-only from strategy's
            perspective (strategy does not mutate; Simulator calls `apply_orders`
            downstream if decision.is_action).
        context : RebalanceContext
            Snapshot of market + portfolio surroundings at `as_of` date.

        Returns
        -------
        RebalanceDecision
            Either an action-decision with orders + costs + weight shift,
            or a no_action decision when strategy did not trigger.
        """
        # Step 1: strategy-specific target computation (hook)
        target = self.compute_target_weights(current, context)

        # Step 2: strategy-specific trigger check (hook)
        if not self.should_trigger(current, target, context):
            return RebalanceDecision.no_action(
                strategy_name=self.name,
                triggered_at=context.as_of,
                reason="no_trigger",
            )

        # Step 3: compute orders from weight delta (shared)
        orders = self._compute_orders(current, target, context)

        # Edge case: computed zero orders despite trigger (e.g., weight shift
        # too small to fund a whole share). Treat as no-action to avoid
        # TradingCost=zero + orders=non-empty validation error downstream.
        if not orders:
            return RebalanceDecision.no_action(
                strategy_name=self.name,
                triggered_at=context.as_of,
                reason="zero_shares_after_rounding",
            )

        # Step 4: compute cost (delegate to injected service)
        costs = self._cost_calculator.compute(orders)

        # Step 5: assemble decision (shared)
        weights_before = current.get_weights(context.prices)
        return RebalanceDecision(
            strategy_name=self.name,
            triggered_at=context.as_of,
            reason=self._reason(),
            orders=tuple(orders),
            costs=costs,
            weights_before=weights_before,
            weights_after=dict(target),
        )

    # ------------------------------------------------------------------
    # Abstract hooks - subclass MUST override
    # ------------------------------------------------------------------

    @abstractmethod
    def compute_target_weights(
        self,
        current: Portfolio,
        context: RebalanceContext,
    ) -> dict[str, float]:
        """Return the strategy's target weight distribution at `context.as_of`.

        Static strategies (ThresholdBand) return Portfolio.target_weights
        unchanged. Dynamic strategies (optimization-based, Sprint 14+)
        may recompute from fresh covariance estimates.

        Returns
        -------
        dict[str, float]
            Ticker -> target weight (0.0-1.0). Should sum to ~1.0; strategy
            is responsible for normalization.
        """

    @abstractmethod
    def should_trigger(
        self,
        current: Portfolio,
        target: dict[str, float],
        context: RebalanceContext,
    ) -> bool:
        """Decide whether to execute a rebalance at `context.as_of`.

        Parameters
        ----------
        current : Portfolio
            Current state.
        target : dict[str, float]
            Output of compute_target_weights() for this iteration.
        context : RebalanceContext
            Market + timing context.

        Returns
        -------
        bool
            True -> fire rebalance (steps 3-5 run); False -> no-action decision.
        """

    # ------------------------------------------------------------------
    # Shared base logic - subclass MAY override cautiously
    # ------------------------------------------------------------------

    def _compute_orders(
        self,
        current: Portfolio,
        target: dict[str, float],
        context: RebalanceContext,
    ) -> list[Order]:
        """Convert weight delta -> BUY/SELL orders using current prices.

        Logic:
            1. Compute total_value for the Portfolio at context.prices
            2. For each ticker trong target: target_shares = int(target_weight * total_value / price)
            3. delta_shares = target_shares - current_shares (0 if not in Portfolio)
            4. delta > 0 -> BUY delta shares at close price
            5. delta < 0 -> SELL abs(delta) shares at close price
            6. Skip orders where delta == 0 or ticker missing from context.prices
            7. Floor rounding (int cast) to prevent over-buy at the budget edge

        Precision contract (F-H1)
        -------------------------
        Mixing float (target_weight) with Decimal (prices, total_value) is
        intentional and deterministic:

        1. `target_weight: float` - portfolio weights are ratios in [0, 1],
           not currency units, so NFR-R-07 Decimal constraint does not apply.
           float provides sufficient precision for all realistic weights
           (IEEE 754 double gives ~15 significant digits; human-readable
           weights like 0.4 round-trip exactly against band_bps granularity
           of 1 bps = 0.0001).

        2. `Decimal(str(target_weight)) * total_value` - the `str()` detour
           PREVENTS binary float artifacts from entering currency math:
               Decimal(0.1)       # -> Decimal('0.1000000000000000055511...')
               Decimal(str(0.1))  # -> Decimal('0.1')  (exact)
           Downstream multiplication by total_value, division by price, and
           int() truncation stay bit-identical across platforms.

        3. `int(target_capital / price)` - floor rounding in the Decimal
           domain, not float. Decimal.__truediv__ returns Decimal; int()
           truncates toward zero (equivalent to floor for non-negative
           operands guaranteed by target_weight >= 0 and total_value >= 0
           invariants). Same inputs always produce the same share count.

        Reproducibility guarantee (NFR-R-07): identical (portfolio, target,
        prices) tuples always yield identical orders. Covered by
        property-based tests in Day 2
        (test_portfolio_apply_orders_vwap_hypothesis).

        Other notes
        -----------
        - Does NOT enforce HOSE lot-size of 100; deferred to Sprint 12
          RoundLotRefinement.
        - Price = context.prices[ticker] (close). Future TWAP/VWAP execution
          would be plugged in by subclass overriding _compute_orders.
        - Short selling is never emitted: current < target_sell raises
          ValueError inside Portfolio.apply_orders (deferred to that layer,
          not caught here).

        Returns
        -------
        list[Order]
            Orders list, possibly empty when all deltas round to 0.
        """
        total_value = current.total_value(context.prices)
        orders: list[Order] = []

        for ticker, target_weight in target.items():
            if ticker not in context.prices:
                continue

            price = context.prices[ticker]
            target_capital = Decimal(str(target_weight)) * total_value
            target_shares = int(target_capital / price)

            current_shares = current.holdings[ticker].shares if ticker in current.holdings else 0

            delta_shares = target_shares - current_shares

            if delta_shares > 0:
                orders.append(
                    Order(
                        ticker=ticker,
                        side=OrderSide.BUY,
                        shares=delta_shares,
                        est_price=price,
                    )
                )
            elif delta_shares < 0:
                orders.append(
                    Order(
                        ticker=ticker,
                        side=OrderSide.SELL,
                        shares=-delta_shares,
                        est_price=price,
                    )
                )
            # delta_shares == 0: skip (no order needed)

        return orders

    def _reason(self) -> str:
        """Return the reason label for RebalanceDecision.reason.

        Default implementation returns self.name. Subclass override for
        more granular reasons (e.g., HybridStrategy might return
        'band_drift' vs 'calendar' based on which clause triggered).

        Returns
        -------
        str
            Label matching CHECK constraint on simulation.rebalance_decision.reason:
            'band_drift', 'calendar', 'window', 'hybrid', 'manual'.
        """
        return self.name
