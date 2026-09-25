"""Migrate Project 1 SQLite prices dataset to Neon prices.daily_ohlcv.

Bootstrap step of Sprint 10 Task 5A B.2 (hybrid data population).

Reads Stock_Prices table from Project 1's SQLite (29 VN30 tickers, 5.7-year
daily OHLCV, ~40K rows) and INSERTs into Neon prices.daily_ohlcv with
source='sqlite_project1'.

Idempotent via ON CONFLICT (ticker, trade_date) DO NOTHING.

Usage:
    python -m scripts.migrate_p1_prices --dry-run   # inspect, no DB write
    python -m scripts.migrate_p1_prices             # execute
    python -m scripts.migrate_p1_prices --sqlite-path <path>

Related: Migration 002, P1 handoff (data/raw/portfolio.db).
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import psycopg2
import psycopg2.extras

from vn_portfolio_frontier.config import get_settings

DEFAULT_SQLITE_PATH = Path("D:/Projects/vn-portfolio-optimizer/data/raw/portfolio.db")
SOURCE_TAG = "sqlite_project1"
BATCH_SIZE = 5000

EXPECTED_TICKER_COUNT = 29
EXPECTED_ROW_COUNT = 40661  # verified 2026-09-25 during Cụm 1 discovery


def load_p1_prices(sqlite_path: Path) -> list[tuple]:
    """Read Stock_Prices from SQLite; return list of tuples for Neon INSERT."""
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite file not found: {sqlite_path}")

    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT Ticker, Date, Open, High, Low, Close, Volume
            FROM Stock_Prices
            ORDER BY Ticker, Date
            """)
        rows = cur.fetchall()
    finally:
        conn.close()

    # Transform: append source tag to each row (P2 schema column order)
    return [
        (ticker, date_str, o, h, lo, c, v, SOURCE_TAG)
        for (ticker, date_str, o, h, lo, c, v) in rows
    ]


def insert_prices(conn, rows: list[tuple]) -> int:
    """Batch INSERT with ON CONFLICT DO NOTHING. Returns total rows inserted."""
    total_inserted = 0
    insert_sql = """
        INSERT INTO prices.daily_ohlcv
            (ticker, trade_date, open_price, high_price, low_price,
             close_price, volume, source)
        VALUES %s
        ON CONFLICT (ticker, trade_date) DO NOTHING
    """
    with conn.cursor() as cur:
        for batch_start in range(0, len(rows), BATCH_SIZE):
            batch = rows[batch_start : batch_start + BATCH_SIZE]
            psycopg2.extras.execute_values(cur, insert_sql, batch, page_size=BATCH_SIZE)
            total_inserted += cur.rowcount
            print(
                f"[batch] rows {batch_start:>6}-{batch_start + len(batch):>6}: "
                f"inserted={cur.rowcount}"
            )
    return total_inserted


def verify_migration(conn) -> None:
    """Assert post-migration row count + ticker set + date range."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), COUNT(DISTINCT ticker), MIN(trade_date), MAX(trade_date) "
            "FROM prices.daily_ohlcv WHERE source = %s",
            (SOURCE_TAG,),
        )
        n, n_tickers, dmin, dmax = cur.fetchone()

    print(f"[verify] rows={n}, tickers={n_tickers}, dates {dmin} to {dmax}")
    assert (
        n == EXPECTED_ROW_COUNT
    ), f"expected {EXPECTED_ROW_COUNT} rows with source='{SOURCE_TAG}', got {n}"
    assert (
        n_tickers == EXPECTED_TICKER_COUNT
    ), f"expected {EXPECTED_TICKER_COUNT} tickers, got {n_tickers}"
    print("[ok] All migration assertions passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=DEFAULT_SQLITE_PATH,
        help=f"P1 SQLite file path (default: {DEFAULT_SQLITE_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load SQLite and validate row shape, skip DB write.",
    )
    args = parser.parse_args()

    print(f"Reading P1 SQLite: {args.sqlite_path}")
    rows = load_p1_prices(args.sqlite_path)
    print(f"[ok] Loaded {len(rows):,} rows from Stock_Prices")

    if args.dry_run:
        print("[dry-run] Sample first 3 rows:")
        for r in rows[:3]:
            print(f"  {r}")
        print("[dry-run] Sample last 3 rows:")
        for r in rows[-3:]:
            print(f"  {r}")
        print("[dry-run] Skipping DB write.")
        return

    dsn = get_settings().neon_database_url.get_secret_value()
    with psycopg2.connect(dsn) as conn:
        n_inserted = insert_prices(conn, rows)
        conn.commit()
        print(f"[ok] Committed transaction, total inserted: {n_inserted}")
        verify_migration(conn)


if __name__ == "__main__":
    main()
