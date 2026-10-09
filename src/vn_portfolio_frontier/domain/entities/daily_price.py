"""DailyPrice value object - one trading day OHLCV bar for a ticker.

Represents the price action of a single ticker on a single trading date.
This is the fundamental unit consumed by RebalanceStrategy.should_trigger()
and compute_target_weights() when deciding whether and how to rebalance.

Design decisions:
    - Frozen dataclass: each row from prices.daily_ohlcv is immutable.
      Backtest loops iterate day-by-day, never mutate a bar.
    - Decimal for all four OHLC prices: NFR-R-07 requires that two runs
      with the same input produce identical outputs (no float drift when
      summing returns across 1250+ trading days of a 5-year backtest).
    - volume as int: Vietnamese equities trade in whole shares, no partial
      shares exist (unlike some foreign exchanges with fractional trading).
    - adjusted_close is optional: Sprint 10 sync_prices.py populates it
      when vnstock Silver supplies it, else NULL. Downstream Strategy
      should fall back to close if adj_close is None.
    - source string: tracks data provider (KBS / VCI cascade per ADR-012
      §2.4 B.3 lock) for audit when prices differ between sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class DailyPrice:
    """One trading day OHLCV bar for a single ticker.

    Parameters
    ----------
    ticker : str
        Instrument identifier. Validated non-empty.
    trade_date : date
        Session date (not timestamp). Vietnamese equities trade 9:00-15:00
        local time; this date represents the full session.
    open_price : Decimal
        Opening price in VND. Must be positive.
    high : Decimal
        Session high. Must be >= low and >= open and >= close.
    low : Decimal
        Session low. Must be <= high and <= open and <= close and positive.
    close : Decimal
        Closing price. Must be positive.
    volume : int
        Session trading volume in shares. Must be non-negative (zero is
        valid for halted/suspended sessions).
    adjusted_close : Decimal | None, default None
        Dividend-and-split adjusted close for return calculations. None
        when provider did not supply.
    source : str, default "KBS"
        Data provider. One of "KBS", "VCI" per ADR-012 §2.4 cascade.

    Raises
    ------
    ValueError
        If ticker empty, any price non-positive (except volume=0 allowed),
        or OHLC invariants violated (high < low, high < open, etc.).

    Notes
    -----
    The OHLC invariant check is loose intentionally: high == low is valid
    (session with 1 trade or no price movement). We only reject strictly
    inconsistent bars (high < low), not degenerate ones.

    Examples
    --------
    >>> p = DailyPrice(
    ...     ticker="VCB",
    ...     trade_date=date(2026, 1, 15),
    ...     open_price=Decimal("124000"),
    ...     high=Decimal("126000"),
    ...     low=Decimal("123500"),
    ...     close=Decimal("125000"),
    ...     volume=1_500_000,
    ... )
    >>> p.daily_range()
    Decimal('2500')
    >>> p.price_for_execution()
    Decimal('125000')
    """

    ticker: str
    trade_date: date
    open_price: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    adjusted_close: Decimal | None = None
    source: str = "KBS"

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ValueError("DailyPrice.ticker must not be empty")

        for name, val in [
            ("open_price", self.open_price),
            ("high", self.high),
            ("low", self.low),
            ("close", self.close),
        ]:
            if val <= 0:
                raise ValueError(f"DailyPrice.{name} must be positive, got {val}")

        if self.volume < 0:
            raise ValueError(f"DailyPrice.volume must be non-negative, got {self.volume}")

        if self.high < self.low:
            raise ValueError(
                f"DailyPrice.high ({self.high}) must be >= low ({self.low}) "
                f"for {self.ticker} on {self.trade_date}"
            )

        if self.adjusted_close is not None and self.adjusted_close <= 0:
            raise ValueError(
                f"DailyPrice.adjusted_close must be positive when provided, "
                f"got {self.adjusted_close}"
            )

    def daily_range(self) -> Decimal:
        """Return intraday range (high - low).

        Returns
        -------
        Decimal
            Non-negative difference. Zero on flat sessions.
        """
        return self.high - self.low

    def price_for_execution(self) -> Decimal:
        """Return the price used to execute rebalance orders.

        Returns
        -------
        Decimal
            Close price. This is the convention for end-of-day rebalancing
            per the current Feature 2 scope. Future enhancements may add
            VWAP or TWAP execution models in a strategy-specific override.
        """
        return self.close

    def return_from(self, prior: DailyPrice) -> Decimal:
        """Return the simple return from a prior bar to this one.

        Parameters
        ----------
        prior : DailyPrice
            Previous bar for the same ticker. Must be strictly earlier
            trade_date.

        Returns
        -------
        Decimal
            (close - prior.close) / prior.close. Uses adjusted_close if
            both bars have it, else raw close.

        Raises
        ------
        ValueError
            If prior.ticker != self.ticker or prior.trade_date >= self.trade_date.
        """
        if prior.ticker != self.ticker:
            raise ValueError(
                f"DailyPrice.return_from: ticker mismatch " f"({prior.ticker} vs {self.ticker})"
            )
        if prior.trade_date >= self.trade_date:
            raise ValueError(
                f"DailyPrice.return_from: prior bar must be strictly earlier, "
                f"got prior={prior.trade_date} vs self={self.trade_date}"
            )

        if self.adjusted_close is not None and prior.adjusted_close is not None:
            current = self.adjusted_close
            previous = prior.adjusted_close
        else:
            current = self.close
            previous = prior.close

        return (current - previous) / previous
