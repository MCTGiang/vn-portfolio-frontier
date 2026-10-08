"""Portfolio aggregate root — mutable holder of ticker holdings + cash.

Portfolio is the sole aggregate root of the Feature 2 domain. All holding
and cash state changes flow through its methods; strategies read portfolio
state via `get_weights()` / `total_value()` but never mutate it directly.
The RebalanceSimulator (application layer) is the single caller that may
mutate a Portfolio by invoking `apply_orders()` after a strategy returns
an actionable RebalanceDecision.

Design decisions (ADR-015 §2.1 Hexagonal + §2.3 Template Method):
    - **Mutable aggregate root**, unlike the value objects in this module.
      This matches both the Design Class Diagram (chương 7) and the
      Streamlit usage pattern (st.session_state.portfolio mutates in
      place as the user interacts). Alternative — immutable with
      `apply_orders` returning a new Portfolio — considered and
      rejected: memory cost over a 5-year daily backtest + awkward
      session_state wiring.
    - **Cash accounting**: BUY debits cash by gross_amount; SELL credits
      cash by gross_amount. Trading cost is passed separately to
      `apply_orders` and debited after all orders settle, matching the
      conventional accounting of CTCK statements.
    - **Volume-weighted average cost on BUY**: when adding to an existing
      position, avg_cost is recomputed as the share-weighted average.
      Needed for Sprint 12+ realised P&L accounting (short-term vs
      long-term distinction per Thông tư 111/2013/TT-BTC).
    - **SELL preserves avg_cost**: residual shares keep the pre-SELL
      avg_cost. Realised P&L on sold shares = (sell_price - avg_cost) *
      shares_sold, computed outside Portfolio (ReturnDecomposer in
      Sprint 12). When SELL closes the position (0 shares left),
      avg_cost resets to 0 (empty-holding convention).
    - **No short selling in Sprint 11 MUST tier**: SELL more shares than
      held raises ValueError. Shorting would require signed shares and
      margin accounting — out of scope.
    - **No negative cash**: `apply_orders` validates that resulting cash
      is non-negative. If a strategy produces orders exceeding available
      budget, the caller must either scale down orders or skip the
      trigger. This defends NFR-R-02 transaction atomicity: a partial
      apply is never visible.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from vn_portfolio_frontier.domain.entities.holding import Holding
from vn_portfolio_frontier.domain.entities.order import Order, OrderSide


@dataclass
class Portfolio:
    """Aggregate root for a backtested or live portfolio.

    Parameters
    ----------
    cash : Decimal
        Current cash balance in VND. Required (no sensible default; a
        zero-cash portfolio is valid but must be stated explicitly).
    holdings : dict[str, Holding], default empty
        Ticker to Holding map. Missing keys mean "ticker is not held";
        a key with shares=0 means "tracked but currently flat".
    target_weights : dict[str, float], default empty
        Strategy-level target allocation. Values should sum to 1.0 (not
        enforced here; strategy-level InputValidator does the check).

    Raises
    ------
    ValueError
        If `cash` is negative at construction.

    Notes
    -----
    This is the only entity in `domain.entities` that is NOT a frozen
    dataclass. Mutability is intentional per the design decision above.
    Equality is still structural (dataclass default __eq__), so two
    portfolios with the same holdings + cash + target_weights are equal.

    Examples
    --------
    >>> from vn_portfolio_frontier.domain.entities.order import Order, OrderSide
    >>> p = Portfolio(cash=Decimal("100000000"))
    >>> p.total_value({})
    Decimal('100000000')

    >>> buy = Order("VCB", OrderSide.BUY, 100, Decimal("125000"))
    >>> p.apply_orders([buy], total_cost=Decimal("25000"))
    >>> p.cash
    Decimal('87475000')
    >>> p.holdings["VCB"].shares
    100
    """

    cash: Decimal
    holdings: dict[str, Holding] = field(default_factory=dict)
    target_weights: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cash < 0:
            raise ValueError(f"Portfolio.cash must be non-negative at init, got {self.cash}")

    def total_value(self, prices: Mapping[str, Decimal]) -> Decimal:
        """Return cash + mark-to-market value of all holdings.

        Parameters
        ----------
        prices : Mapping[str, Decimal]
            Ticker to current price. Missing tickers are treated as
            having zero value in the sum (silent skip rather than raise
            — allows partial-universe pricing during data outages).

        Returns
        -------
        Decimal
            cash + sum(holding.market_value(prices[ticker])) for all
            held tickers with available prices.
        """
        market = Decimal("0")
        for ticker, holding in self.holdings.items():
            if ticker in prices:
                market += holding.market_value(prices[ticker])
        return self.cash + market

    def get_weights(self, prices: Mapping[str, Decimal]) -> dict[str, float]:
        """Return current weight distribution across holdings.

        Parameters
        ----------
        prices : Mapping[str, Decimal]
            Ticker to current price. Weights for missing-price tickers
            are omitted from the result.

        Returns
        -------
        dict[str, float]
            Ticker to weight (0.0-1.0). Does NOT include a cash entry;
            weights sum to less than 1.0 by the cash fraction. Empty
            dict when total_value is zero.

        Notes
        -----
        float used here (not Decimal) because weights are inherently
        imprecise ratios; downstream band comparisons use bps thresholds
        well above float epsilon. Decimal for weights would propagate
        unnecessary precision overhead through strategy loops.
        """
        total = self.total_value(prices)
        if total == 0:
            return {}
        weights: dict[str, float] = {}
        for ticker, holding in self.holdings.items():
            if ticker in prices and holding.shares > 0:
                weights[ticker] = float(holding.market_value(prices[ticker]) / total)
        return weights

    def apply_orders(
        self,
        orders: Iterable[Order],
        total_cost: Decimal = Decimal("0"),
    ) -> None:
        """Apply a sequence of orders to the portfolio in place.

        Parameters
        ----------
        orders : Iterable[Order]
            BUY/SELL orders to execute in the given sequence. For a
            single trigger event, order is immaterial (all settle at
            the same price); for cross-day execution models (future),
            sequence matters.
        total_cost : Decimal, default Decimal("0")
            Total trading cost (brokerage + slippage + tax) to deduct
            from cash after all orders settle. Non-negative.

        Raises
        ------
        ValueError
            If a SELL order exceeds the current holding; if
            `total_cost` is negative; or if the resulting cash balance
            would be negative.

        Notes
        -----
        This method is NOT transactional in the strict sense — a failure
        mid-sequence may leave the portfolio in a partially-applied
        state. For NFR-R-02 strict atomicity, callers should snapshot
        the portfolio before calling and restore on exception. The
        RebalanceSimulator does this via dataclasses.replace-based
        snapshot before each trigger application.
        """
        if total_cost < 0:
            raise ValueError(
                f"Portfolio.apply_orders: total_cost must be non-negative, got {total_cost}"
            )

        for order in orders:
            if order.side == OrderSide.BUY:
                self._apply_buy(order)
            else:
                self._apply_sell(order)

        self.cash -= total_cost
        if self.cash < 0:
            raise ValueError(
                f"Portfolio.apply_orders: resulting cash {self.cash} is negative. "
                f"Orders consumed more than available budget (including total_cost "
                f"{total_cost}). Caller should scale down orders or skip trigger."
            )

    def _apply_buy(self, order: Order) -> None:
        """Apply a single BUY order: debit cash, update holding."""
        self.cash -= order.gross_amount()
        existing = self.holdings.get(order.ticker)
        if existing is None or existing.shares == 0:
            self.holdings[order.ticker] = Holding(
                ticker=order.ticker,
                shares=order.shares,
                avg_cost=order.est_price,
            )
        else:
            new_shares = existing.shares + order.shares
            new_cost = (
                Decimal(existing.shares) * existing.avg_cost
                + Decimal(order.shares) * order.est_price
            ) / Decimal(new_shares)
            self.holdings[order.ticker] = Holding(
                ticker=order.ticker,
                shares=new_shares,
                avg_cost=new_cost,
            )

    def _apply_sell(self, order: Order) -> None:
        """Apply a single SELL order: credit cash, reduce holding."""
        existing = self.holdings.get(order.ticker)
        if existing is None or existing.shares < order.shares:
            held = existing.shares if existing else 0
            raise ValueError(
                f"Portfolio.apply_orders: cannot sell {order.shares} shares of "
                f"{order.ticker}, only {held} held. Short selling not supported "
                f"in Sprint 11 MUST tier."
            )
        self.cash += order.gross_amount()
        remaining = existing.shares - order.shares
        self.holdings[order.ticker] = Holding(
            ticker=order.ticker,
            shares=remaining,
            avg_cost=existing.avg_cost if remaining > 0 else Decimal("0"),
        )
