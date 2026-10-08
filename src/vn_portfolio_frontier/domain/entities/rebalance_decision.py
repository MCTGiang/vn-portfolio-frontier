"""RebalanceDecision entity + TradingCost value object.

A RebalanceDecision records what the strategy did at one trigger date:
either a set of BUY/SELL orders with their execution cost, or an explicit
"no-action" with a reason. One run of UC-F2-01 produces a time-ordered
sequence of RebalanceDecisions, persisted to simulation.rebalance_decision.

Design decisions:
    - TradingCost: frozen dataclass with 3 Decimal cost components
      (brokerage per ADR-012 user-input, slippage from market_impact_bps,
      tax from Thông tư 111/2013/TT-BTC seller-only 0.1%). Non-negative
      invariants. `total()` sums; `zero()` factory for no-action.
    - RebalanceDecision as frozen dataclass: although conceptually an
      "entity" (has identity in simulation.rebalance_decision via
      decision_id), the domain layer treats it as an immutable record.
      Repository assigns id on save(). To "update" a decision use
      dataclasses.replace() for a new instance.
    - orders stored as tuple[Order, ...] (not list) so the whole decision
      is hashable + truly immutable at the collection level.
    - weights_before/after kept as dict[str, float] with the documented
      convention that they are treated as read-only (same compromise as
      RebalanceContext.flags). Tightening to MappingProxyType deferred
      to Sprint 12 if a mutation bug surfaces.
    - `no_action()` classmethod factory: canonical constructor for the
      "strategy did not trigger" case. Returns a decision with empty
      orders tuple, zero costs, and no weight shift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from vn_portfolio_frontier.domain.entities.order import Order


@dataclass(frozen=True)
class TradingCost:
    """Breakdown of execution cost per rebalance decision.

    Parameters
    ----------
    brokerage : Decimal
        Broker commission in VND. User-input `brokerage_pct` times gross
        trade value (ADR-012). Non-negative.
    slippage : Decimal
        Market-impact cost in VND. Default model: `market_impact_bps`
        times gross trade value / 10000. Non-negative.
    tax : Decimal
        Vietnam seller tax (Thông tư 111/2013/TT-BTC) in VND. 0.1% of
        gross SELL proceeds; zero for pure-BUY decisions. Non-negative.

    Raises
    ------
    ValueError
        If any component is negative.

    Notes
    -----
    All three components in the same currency unit (VND, same as the
    rest of the system). Rounding to the nearest VND is the caller's
    responsibility (typically CostCalculator applies HALF_UP quantization
    before constructing TradingCost).

    Examples
    --------
    >>> cost = TradingCost(
    ...     brokerage=Decimal("15000"),
    ...     slippage=Decimal("12500"),
    ...     tax=Decimal("12500"),
    ... )
    >>> cost.total()
    Decimal('40000')
    >>> TradingCost.zero().total()
    Decimal('0')
    """

    brokerage: Decimal
    slippage: Decimal
    tax: Decimal

    def __post_init__(self) -> None:
        for name in ("brokerage", "slippage", "tax"):
            value: Decimal = getattr(self, name)
            if value < 0:
                raise ValueError(f"TradingCost.{name} must be non-negative, got {value}")

    def total(self) -> Decimal:
        """Return the sum of all three cost components.

        Returns
        -------
        Decimal
            brokerage + slippage + tax. Always non-negative.
        """
        return self.brokerage + self.slippage + self.tax

    @classmethod
    def zero(cls) -> TradingCost:
        """Return a zero-cost instance (no-action decision marker).

        Returns
        -------
        TradingCost
            All three components set to Decimal('0').
        """
        return cls(Decimal("0"), Decimal("0"), Decimal("0"))


@dataclass(frozen=True)
class RebalanceDecision:
    """One rebalance evaluation outcome at a trigger date.

    Parameters
    ----------
    strategy_name : str
        Logical name of the strategy that produced this decision
        (e.g. "threshold_band", "calendar_monthly"). Must match the
        CHECK constraint on simulation.rebalance_run.strategy_name.
    triggered_at : date
        The RebalanceContext.as_of date when this evaluation ran.
    reason : str
        Short label explaining the decision: 'band_drift', 'calendar',
        'window', 'hybrid', 'manual', or 'no_trigger' for no-action.
        Matches CHECK constraint on simulation.rebalance_decision.reason.
    orders : tuple[Order, ...], default empty
        BUY/SELL orders produced. Empty for no-action decisions.
    costs : TradingCost, default zero
        Execution cost breakdown. Zero for no-action.
    weights_before : dict[str, float], default empty
        Portfolio weight distribution before this decision applied.
    weights_after : dict[str, float], default empty
        Portfolio weight distribution after orders executed. Equals
        `weights_before` for no-action decisions.

    Raises
    ------
    ValueError
        If strategy_name or reason is empty, or if orders is non-empty
        but costs is zero (inconsistent: real trade with zero cost
        signals a cost calculator bug upstream).

    Notes
    -----
    Treat the dict fields as read-only after construction. The frozen
    dataclass prevents rebinding (`decision.weights_before = {...}`
    raises FrozenInstanceError), but does NOT prevent in-place mutation
    (`decision.weights_before['x'] = y` succeeds silently).

    Examples
    --------
    >>> from vn_portfolio_frontier.domain.entities.order import Order, OrderSide
    >>> order = Order("VCB", OrderSide.BUY, 100, Decimal("125000"))
    >>> cost = TradingCost(Decimal("18750"), Decimal("6250"), Decimal("0"))
    >>> d = RebalanceDecision(
    ...     strategy_name="threshold_band",
    ...     triggered_at=date(2026, 1, 15),
    ...     reason="band_drift",
    ...     orders=(order,),
    ...     costs=cost,
    ...     weights_before={"VCB": 0.10, "FPT": 0.90},
    ...     weights_after={"VCB": 0.15, "FPT": 0.85},
    ... )
    >>> d.is_action
    True
    >>> d.total_cost()
    Decimal('25000')
    >>> d.order_count()
    1

    >>> skip = RebalanceDecision.no_action(
    ...     strategy_name="threshold_band",
    ...     triggered_at=date(2026, 1, 16),
    ...     reason="no_trigger",
    ... )
    >>> skip.is_action
    False
    """

    strategy_name: str
    triggered_at: date
    reason: str
    orders: tuple[Order, ...] = ()
    costs: TradingCost = field(default_factory=TradingCost.zero)
    weights_before: dict[str, float] = field(default_factory=dict)
    weights_after: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.strategy_name:
            raise ValueError("RebalanceDecision.strategy_name must not be empty")
        if not self.reason:
            raise ValueError("RebalanceDecision.reason must not be empty")
        if self.orders and self.costs.total() == 0:
            raise ValueError(
                "RebalanceDecision has orders but zero total cost — "
                "CostCalculator upstream likely has a bug (brokerage_pct=0 "
                "+ slippage_bps=0 + no SELL leg?). Use no_action() for "
                "intentional zero-order decisions."
            )

    @property
    def is_action(self) -> bool:
        """Return True if this decision carries at least one order.

        Returns
        -------
        bool
            True if `orders` is non-empty, else False.
        """
        return len(self.orders) > 0

    def order_count(self) -> int:
        """Return the number of orders in this decision.

        Returns
        -------
        int
            Non-negative count. Zero for no-action.
        """
        return len(self.orders)

    def total_cost(self) -> Decimal:
        """Return the total trading cost.

        Returns
        -------
        Decimal
            Shortcut for `self.costs.total()`. Non-negative.
        """
        return self.costs.total()

    @classmethod
    def no_action(
        cls,
        strategy_name: str,
        triggered_at: date,
        reason: str = "no_trigger",
    ) -> RebalanceDecision:
        """Construct a no-action decision (strategy did not trigger).

        Parameters
        ----------
        strategy_name : str
            Strategy that evaluated (even though it did not fire).
        triggered_at : date
            The date on which the no-fire evaluation occurred.
        reason : str, default "no_trigger"
            Why the strategy did not trigger. Common values: "no_trigger"
            (band not exceeded), "flat_portfolio" (nothing to rebalance),
            "insufficient_data" (missing prices).

        Returns
        -------
        RebalanceDecision
            Empty-orders, zero-cost decision instance.
        """
        return cls(
            strategy_name=strategy_name,
            triggered_at=triggered_at,
            reason=reason,
        )
