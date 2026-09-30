"""Fetch VN30 company metadata from vnstock_data Company API.

Populates fundamentals.vn30_constituent with static metadata:
- ticker, listing_date, exchange, sector (from company_type field)
- is_current: derived from vn30_membership_snapshot latest (2026-07)

company_name_vi/en left NULL — vnstock_data overview() does not expose
canonical company names. Sprint 11 follow-up: enrich from HOSE ticker
directory or vnstock Listing() API.

Usage:
    python scripts/fetch_metadata.py --dry-run
    python scripts/fetch_metadata.py --tickers VCB,FPT
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
from datetime import date, datetime


def _ensure_utf8_streams() -> None:
    """Force UTF-8 stdout/stderr on Windows (M5 pattern)."""
    for stream in (sys.stdout, sys.stderr):
        if (
            hasattr(stream, "reconfigure")
            and stream.encoding
            and stream.encoding.lower() != "utf-8"
        ):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8", errors="replace")


import psycopg2  # noqa: E402

try:
    from vn_portfolio_frontier.config import get_settings
except ImportError:
    print("ERROR: Run from repo root", file=sys.stderr)
    sys.exit(1)

# Reuse universe from fetch_fundamentals to avoid duplication
sys.path.insert(0, "scripts")
from fetch_fundamentals import VN30_UNIVERSE  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def parse_dd_mm_yyyy(s) -> date | None:
    """Parse '30/06/2009' → date(2009, 6, 30). Return None on failure."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return None


def fetch_ticker_metadata(ticker: str) -> dict:
    """Fetch overview for one ticker. Returns dict with mapped fields."""
    from vnstock_data import Company

    c = Company(symbol=ticker)
    df = c.overview()

    if df is None or df.empty:
        return {}

    row = df.iloc[0]

    return {
        "ticker": ticker,
        "listing_date": parse_dd_mm_yyyy(row.get("listing_date")),
        "exchange": str(row["exchange"]) if row.get("exchange") else None,
        "sector": str(row["company_type"]) if row.get("company_type") else None,
    }


def get_current_vn30_tickers(conn) -> set:
    """Return set of tickers in latest vn30_membership_snapshot."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker FROM fundamentals.vn30_membership_snapshot "
            "WHERE effective_date = "
            "(SELECT MAX(effective_date) FROM fundamentals.vn30_membership_snapshot)"
        )
        return {row[0] for row in cur.fetchall()}


def upsert_constituent(conn, ticker: str, meta: dict, is_current: bool) -> None:
    """Insert or update vn30_constituent row with metadata."""
    sql = """
        INSERT INTO fundamentals.vn30_constituent
            (ticker, listing_date, exchange, sector, is_current, source)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker) DO UPDATE SET
            listing_date = EXCLUDED.listing_date,
            exchange = EXCLUDED.exchange,
            sector = EXCLUDED.sector,
            is_current = EXCLUDED.is_current,
            source = EXCLUDED.source,
            updated_at = NOW()
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                ticker,
                meta.get("listing_date"),
                meta.get("exchange"),
                meta.get("sector"),
                is_current,
                "vnstock_data",
            ),
        )


def main() -> int:
    _ensure_utf8_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated tickers (default: all 43)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else VN30_UNIVERSE
    )

    settings = get_settings()
    dsn = settings.neon_database_url.get_secret_value()

    logger.info(f"Fetch metadata target: {len(tickers)} ticker(s), dry_run={args.dry_run}")

    conn = psycopg2.connect(dsn)
    conn.autocommit = True  # per-statement commit; per-ticker isolation
    try:
        current_set = get_current_vn30_tickers(conn)
        logger.info(f"Current VN30 (latest snapshot): {len(current_set)} tickers")

        stats = {"processed": 0, "upserted": 0, "failed": 0}
        for ticker in tickers:
            try:
                meta = fetch_ticker_metadata(ticker)
                is_current = ticker in current_set
                if args.dry_run:
                    logger.info(
                        f"  {ticker}: [DRY-RUN] listing_date={meta.get('listing_date')} "
                        f"exchange={meta.get('exchange')} "
                        f"sector={meta.get('sector')} is_current={is_current}"
                    )
                else:
                    upsert_constituent(conn, ticker, meta, is_current)
                    logger.info(
                        f"  {ticker}: upserted listing_date={meta.get('listing_date')} "
                        f"sector={meta.get('sector')} is_current={is_current}"
                    )
                    stats["upserted"] += 1
                stats["processed"] += 1
            except Exception as exc:
                logger.error(f"  {ticker}: FAILED ({exc.__class__.__name__}: {exc})")
                stats["failed"] += 1

        logger.info(f"DONE: {stats}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
