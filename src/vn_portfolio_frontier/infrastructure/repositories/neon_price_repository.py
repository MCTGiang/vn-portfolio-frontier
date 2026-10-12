"""Concrete PriceRepository backed by Neon PostgreSQL (prices.daily_ohlcv).

Per ADR-015 section 2.4 Repository Pattern - this adapter sits in the
Infrastructure ring and implements the application/ports/PriceRepository
Protocol. It is wired by AppFactory and injected into RebalanceSimulator
at application startup.

Schema notes:
    - DB column names use the *_price suffix (open_price, high_price, low_price,
      close_price) per Migration 003. The DailyPrice entity exposes `open_price`
      but drops the suffix for `high`, `low`, `close`. Queries alias explicitly.
    - DB column `source` maps to entity field `data_source`.
    - batch_insert uses ON CONFLICT (ticker, trade_date) DO NOTHING for
      idempotent re-ingestion.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING

from psycopg2.extras import execute_values

from vn_portfolio_frontier.domain.entities.daily_price import DailyPrice

if TYPE_CHECKING:
    import psycopg2

ConnectionFactory = Callable[[], "psycopg2.extensions.connection"]


class NeonPriceRepository:
    """Neon-backed PriceRepository (duck-types the port Protocol).

    Parameters
    ----------
    connection_factory : callable
        Zero-arg callable returning a psycopg2 connection. Each method call
        acquires a fresh connection and closes it via context manager - this
        matches the per-call pattern used by Day 1 db.py and avoids leaking
        connections across request boundaries.
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._conn_factory = connection_factory

    def get_ohlcv(self, ticker: str, start: date, end: date) -> list[DailyPrice]:
        if start > end:
            raise ValueError(f"get_ohlcv: start ({start}) > end ({end})")
        sql = """
            SELECT
                ticker,
                trade_date,
                open_price,
                high_price,
                low_price,
                close_price,
                volume,
                source
            FROM prices.daily_ohlcv
            WHERE ticker = %s
              AND trade_date BETWEEN %s AND %s
            ORDER BY trade_date ASC
        """
        with self._conn_factory() as conn, conn.cursor() as cur:
            cur.execute(sql, (ticker, start, end))
            return [self._row_to_entity(row) for row in cur.fetchall()]

    def get_latest_dates(self) -> dict[str, date]:
        sql = """
            SELECT ticker, MAX(trade_date) AS latest
            FROM prices.daily_ohlcv
            GROUP BY ticker
        """
        with self._conn_factory() as conn, conn.cursor() as cur:
            cur.execute(sql)
            return dict(cur.fetchall())

    def batch_insert(self, records: list[DailyPrice]) -> int:
        if not records:
            return 0
        sql = """
            INSERT INTO prices.daily_ohlcv (
                ticker, trade_date, open_price, high_price,
                low_price, close_price, volume, source
            ) VALUES %s
            ON CONFLICT (ticker, trade_date) DO NOTHING
        """
        rows = [
            (
                r.ticker,
                r.trade_date,
                r.open_price,
                r.high,
                r.low,
                r.close,
                r.volume,
                None,  # source: DailyPrice entity has no field for this; DB column nullable
            )
            for r in records
        ]
        with self._conn_factory() as conn, conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=5000)
            conn.commit()
            # cur.rowcount reflects rows actually inserted (ON CONFLICT skipped)
            return cur.rowcount if cur.rowcount >= 0 else len(rows)

    @staticmethod
    def _row_to_entity(row: tuple) -> DailyPrice:
        ticker, trade_date, open_price, high_price, low_price, close_price, volume, _source = row
        # DailyPrice entity does not carry source - DB column dropped at boundary.
        return DailyPrice(
            ticker=ticker,
            trade_date=trade_date,
            open_price=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
        )
