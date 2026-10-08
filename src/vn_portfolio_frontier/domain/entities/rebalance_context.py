"""RebalanceContext value object — world state at a trigger evaluation.

A RebalanceContext bundles the snapshot a RebalanceStrategy needs to
answer `should_trigger()` and `compute_target_weights()` at one trading
day. It is passed through BaseStrategy.rebalance() unchanged and makes
strategy evaluation a pure function of (Portfolio, Context).

Design decisions:
    - Frozen dataclass with the same immutability guarantee as other
      value objects: equality by content, hashable, no mutation.
    - `prices` is `Mapping[str, Decimal]` not `dict`: communicates
      read-only intent at the type level. Callers may pass a plain
      dict, but downstream strategies should not mutate it.
    - `flags` kept as `dict` with the documented convention that it
      is treated as read-only. True immutability would require
      MappingProxyType or frozenset-of-items, but that complicates
      construction without clear Sprint 11 payoff. Will tighten in
      Sprint 12 if a bug surfaces from accidental mutation.
    - Renamed the `date` field from the Design Class Diagram to
      `as_of` to avoid shadowing the `datetime.date` import locally
      and in callers.
    - `available_cash` carried in Context (not read off Portfolio) so
      that dry-run and sensitivity scenarios can override it without
      mutating the Portfolio under test.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class RebalanceContext:
    """Snapshot of market + portfolio surroundings at one trigger date.

    Parameters
    ----------
    as_of : date
        Trading date being evaluated. Strategies compare this to
        `last_rebalance_date` for window / calendar triggers.
    prices : Mapping[str, Decimal]
        Ticker to close price in VND for every ticker in the current
        universe. Missing tickers signal insufficient data; strategies
        must either skip the day or raise InsufficientDataError.
    last_rebalance_date : date | None, default None
        Date of the previous trigger in the current backtest run. None
        before any trigger has fired (first iteration).
    available_cash : Decimal, default 0
        Cash balance available to fund BUY orders. Overridable in
        dry-run / sensitivity scenarios.
    flags : dict[str, Any], default empty
        Open bag of strategy-specific flags: dry_run=True, debug=True,
        force_trigger=True. Keep names short; prefer first-class
        parameters when a flag matures.

    Raises
    ------
    ValueError
        If `as_of` is unset (dataclass default would be field=None), or
        `available_cash` is negative, or any price in `prices` is
        non-positive.

    Notes
    -----
    Prices-dict order is irrelevant for strategy logic (strategies index
    by ticker key). We do not enforce universe membership here; that is
    the Portfolio's responsibility.

    Examples
    --------
    >>> from datetime import date
    >>> ctx = RebalanceContext(
    ...     as_of=date(2026, 1, 15),
    ...     prices={"VCB": Decimal("125000"), "FPT": Decimal("95000")},
    ...     available_cash=Decimal("5000000"),
    ... )
    >>> ctx.price_of("VCB")
    Decimal('125000')
    >>> ctx.has_price("MSFT")
    False
    """

    as_of: date
    prices: Mapping[str, Decimal]
    last_rebalance_date: date | None = None
    available_cash: Decimal = Decimal("0")
    flags: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.available_cash < 0:
            raise ValueError(
                f"RebalanceContext.available_cash must be non-negative, "
                f"got {self.available_cash}"
            )
        for ticker, price in self.prices.items():
            if price <= 0:
                raise ValueError(
                    f"RebalanceContext.prices[{ticker!r}] must be positive, " f"got {price}"
                )
        if self.last_rebalance_date is not None and self.last_rebalance_date > self.as_of:
            raise ValueError(
                f"RebalanceContext.last_rebalance_date ({self.last_rebalance_date}) "
                f"must not be in the future of as_of ({self.as_of})"
            )

    def price_of(self, ticker: str) -> Decimal:
        """Return the close price for `ticker`.

        Parameters
        ----------
        ticker : str
            Instrument identifier.

        Returns
        -------
        Decimal
            Close price in VND.

        Raises
        ------
        KeyError
            If `ticker` is not in prices.
        """
        return self.prices[ticker]

    def has_price(self, ticker: str) -> bool:
        """Return True if `ticker` has a price in this context.

        Parameters
        ----------
        ticker : str
            Instrument identifier.

        Returns
        -------
        bool
            True if present (safe to call `price_of`), else False.
        """
        return ticker in self.prices

    def days_since_last_rebalance(self) -> int | None:
        """Return calendar days since last rebalance, or None if no prior.

        Returns
        -------
        int | None
            `(as_of - last_rebalance_date).days` when prior rebalance
            exists, else None. Note this is CALENDAR days not trading
            days; strategies that need trading-day semantics should
            compute from a trading-calendar helper.
        """
        if self.last_rebalance_date is None:
            return None
        return (self.as_of - self.last_rebalance_date).days
