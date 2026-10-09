"""PriceRepository Port - abstraction cho daily_ohlcv access.

Per ADR-015 §2.4 Repository Pattern + Hexagonal Dependency Inversion.
Application services (RebalanceSimulator Day 6+) depend on this Protocol,
NOT on concrete `NeonPriceRepository` from infrastructure. Factory wires
the Neon implementation at runtime; tests inject Fake implementations.

Protocol vs ABC decision (ADR-015 §2.4):
    - Protocol = structural typing (duck typing + mypy static check)
    - ABC = nominal typing (explicit inheritance required)
    - Chosen: Protocol -> NeonPriceRepository doesn't need to inherit; just
      match method signatures. mypy catches missing methods at CI time.
    - @runtime_checkable: enables `isinstance(obj, PriceRepository)` at
      Factory wire-time cho fail-fast on misconfigured deps.

Alternative rejected: 2 Repositories (ReadPriceRepository + WritePriceRepository
in CQRS style). Over-engineering for Sprint 11 MUST tier - same object does
both read + write. Can split later if scale requires separate caching layer.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from vn_portfolio_frontier.domain.entities.daily_price import DailyPrice


@runtime_checkable
class PriceRepository(Protocol):
    """Port cho prices.daily_ohlcv access.

    Methods:
        - get_ohlcv: read bars cho một ticker trong date range
        - get_latest_dates: dict of ticker -> max(trade_date) cho delta sync
        - batch_insert: idempotent upsert cho sync pipeline

    Concrete implementations (Sprint 11+):
        - NeonPriceRepository (infrastructure/repositories/) - SQL via psycopg2
        - FakePriceRepository (tests/unit/fakes/) - in-memory dict for unit tests

    Example
    -------
    >>> def demo_usage(repo: PriceRepository) -> None:
    ...     bars = repo.get_ohlcv("VCB", date(2026, 1, 1), date(2026, 1, 31))
    ...     latest = repo.get_latest_dates()
    ...     inserted = repo.batch_insert(bars)
    """

    def get_ohlcv(
        self,
        ticker: str,
        start: date,
        end: date,
    ) -> list[DailyPrice]:
        """Return bars cho `ticker` trong [start, end] inclusive.

        Parameters
        ----------
        ticker : str
            Instrument identifier.
        start : date
            Start of range (inclusive).
        end : date
            End of range (inclusive).

        Returns
        -------
        list[DailyPrice]
            Chronologically sorted bars. Empty list if no data (not an error).
            Caller handles sparse-data cases (vd market holiday).

        Raises
        ------
        ValueError
            If start > end (invariant violation).
        """
        ...

    def get_latest_dates(self) -> dict[str, date]:
        """Return dict of ticker -> max(trade_date) across all tickers.

        Used by sync_prices.py for incremental delta fetch:
        `fetch_from = latest_dates[ticker] + 1 day`.

        Returns
        -------
        dict[str, date]
            Empty dict if no data in prices.daily_ohlcv yet (fresh DB).
            Tickers absent from DB are absent from result (caller must
            handle via `.get(ticker, SOME_DEFAULT)`).
        """
        ...

    def batch_insert(self, records: list[DailyPrice]) -> int:
        """Insert `records` with idempotent semantics (ON CONFLICT DO NOTHING).

        Parameters
        ----------
        records : list[DailyPrice]
            Bars to insert. Empty list is a no-op (returns 0, not an error).

        Returns
        -------
        int
            Count of rows actually inserted (duplicates skipped per PK
            `(ticker, trade_date)`). May be < len(records) when re-running
            after partial failure.

        Notes
        -----
        - Idempotent: safe to retry - duplicates don't raise, just skip
        - Not transactional across tickers: a batch of 100 may partially
          commit if DB connection fails mid-batch; caller should re-run
          to backfill missing rows
        """
        ...
