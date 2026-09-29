"""Sync daily OHLCV prices for the full VN30 universe from vnstock into Neon.

Universe-aware incremental sync: detects each ticker's latest trade_date in
prices.daily_ohlcv, fetches delta from vnstock (kbs primary -> vci fallback ->
fail-loud per ADR-013 data source cascade), and inserts new rows with source
tag 'vnstock' (ADR-009 feature-driven schema).

Handles both initial ingestion (ticker has no rows -> fetch from DEFAULT_START)
and delta sync (ticker has partial history -> fetch from latest_date + 1).
Idempotent: re-run inserts 0 rows if all tickers already reach end_date.

Usage:
    python scripts/sync_prices.py --end-date 2026-09-25
    python scripts/sync_prices.py --end-date 2026-09-25 --dry-run
    python scripts/sync_prices.py --end-date 2026-09-25 --tickers VCB,ACB
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta

import psycopg2
import psycopg2.extras

try:
    from vn_portfolio_frontier.config import get_settings
except ImportError:
    print("ERROR: Run from repo root, or add src to PYTHONPATH", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Full 43-ticker VN30 all-time universe (2021-2026 union per ADR-013 event-sourcing)
VN30_UNIVERSE: list[str] = [
    "ACB",
    "BCM",
    "BID",
    "BSR",
    "BVH",
    "CTG",
    "DGC",
    "FPT",
    "GAS",
    "GVR",
    "HDB",
    "HPG",
    "KDH",
    "LPB",
    "MBB",
    "MCH",
    "MSN",
    "MWG",
    "NVL",
    "PDR",
    "PLX",
    "PNJ",
    "POW",
    "REE",
    "SAB",
    "SBT",
    "SHB",
    "SSB",
    "SSI",
    "STB",
    "TCB",
    "TCH",
    "TCX",
    "TPB",
    "VCB",
    "VHM",
    "VIB",
    "VIC",
    "VJC",
    "VNM",
    "VPB",
    "VPL",
    "VRE",
]

VNSTOCK_SOURCES: list[str] = ["kbs", "vci"]  # cascade order per B.3 lock 28/09/2026
DEFAULT_START = date(2021, 1, 4)  # 4 Jan 2021 first VN30 snapshot per Migration 006 seed
BATCH_SIZE = 5000


def get_latest_dates(conn) -> dict[str, date | None]:
    """Return {ticker: latest_trade_date or None} for VN30 universe."""
    sql = """
        SELECT ticker, MAX(trade_date) AS latest
        FROM prices.daily_ohlcv
        WHERE ticker = ANY(%s)
        GROUP BY ticker
    """
    with conn.cursor() as cur:
        cur.execute(sql, (VN30_UNIVERSE,))
        found = dict(cur.fetchall())
    return {t: found.get(t) for t in VN30_UNIVERSE}


def fetch_via_vnstock(ticker: str, start: date, end: date, source: str) -> list[tuple]:
    """Fetch OHLCV rows via vnstock Quote API. Returns list of insert tuples."""
    from vnstock.api.quote import Quote

    q = Quote(symbol=ticker, source=source)
    df = q.history(start=str(start), end=str(end), interval="1D")
    if df is None or df.empty:
        return []
    rows = [
        (
            ticker,
            row["time"].strftime("%Y-%m-%d"),
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            int(row["volume"]) if row["volume"] else 0,
            "vnstock",  # bare tag per ADR-009 feature-driven schema
        )
        for _, row in df.iterrows()
    ]
    return rows


def fetch_with_cascade(ticker: str, start: date, end: date) -> tuple[list[tuple], str]:
    """Fetch via cascade kbs -> vci -> fail-loud. Returns (rows, source_used)."""
    last_error: Exception | None = None
    for source in VNSTOCK_SOURCES:
        try:
            rows = fetch_via_vnstock(ticker, start, end, source)
            if rows:
                return rows, source
            logger.warning(f"  {ticker}: source={source} returned empty, trying next")
        except Exception as exc:
            last_error = exc
            logger.warning(
                f"  {ticker}: source={source} failed "
                f"({exc.__class__.__name__}: {exc}), trying next"
            )
    raise RuntimeError(
        f"{ticker}: all sources exhausted ({VNSTOCK_SOURCES}). " f"Last error: {last_error}"
    )


def insert_rows(conn, rows: list[tuple]) -> int:
    """Batch insert with ON CONFLICT DO NOTHING. Returns rowcount."""
    if not rows:
        return 0
    sql = """
        INSERT INTO prices.daily_ohlcv
            (ticker, trade_date, open_price, high_price, low_price, close_price, volume, source)
        VALUES %s
        ON CONFLICT (ticker, trade_date) DO NOTHING
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=BATCH_SIZE)
        return cur.rowcount


def sync_ticker(
    conn,
    ticker: str,
    latest: date | None,
    end_date: date,
    dry_run: bool,
) -> int:
    """Sync one ticker. Returns rows inserted (0 if up-to-date or dry-run)."""
    start = (latest + timedelta(days=1)) if latest else DEFAULT_START
    if start > end_date:
        logger.info(f"  {ticker}: up-to-date (latest={latest}), skip")
        return 0
    logger.info(f"  {ticker}: fetching {start} -> {end_date}")
    rows, source = fetch_with_cascade(ticker, start, end_date)
    if dry_run:
        logger.info(f"  {ticker}: [DRY-RUN] would insert {len(rows)} rows via {source}")
        return 0
    inserted = insert_rows(conn, rows)
    logger.info(f"  {ticker}: inserted {inserted} rows via {source}")
    return inserted


def sync_universe(
    end_date: date,
    tickers: list[str] | None = None,
    dry_run: bool = False,
    progress_callback: Callable[[int, int, str, int], None] | None = None,
) -> dict:
    """Sync VN30 universe prices from vnstock to Neon (public API).

    Callable from CLI, Streamlit UI, cron jobs. Handles VNSTOCK_API_KEY env
    setup + Neon connection + per-ticker delta sync + commit.

    Args:
        end_date: Fetch through this date (inclusive).
        tickers: Subset of VN30_UNIVERSE; None means all 43.
        dry_run: If True, skip INSERT.
        progress_callback: Called after each ticker with
            (index_1based, total, ticker, rows_inserted). Streamlit UI uses
            this for per-ticker progress updates.

    Returns:
        Dict {total_inserted, tickers_processed, tickers_fetched (had delta),
        tickers_up_to_date (skipped)}.
    """
    import os

    if tickers is None:
        tickers = VN30_UNIVERSE
    settings = get_settings()
    if settings.vnstock_api_key is not None:
        os.environ["VNSTOCK_API_KEY"] = settings.vnstock_api_key.get_secret_value()

    dsn = settings.neon_database_url.get_secret_value()
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    stats = {
        "total_inserted": 0,
        "tickers_processed": 0,
        "tickers_fetched": 0,
        "tickers_up_to_date": 0,
    }
    try:
        latest_dates = get_latest_dates(conn)
        total = len(tickers)
        for idx, ticker in enumerate(tickers, start=1):
            latest = latest_dates.get(ticker)
            inserted = sync_ticker(conn, ticker, latest, end_date, dry_run)
            stats["total_inserted"] += inserted
            stats["tickers_processed"] += 1
            if latest is not None and latest >= end_date:
                stats["tickers_up_to_date"] += 1
            else:
                stats["tickers_fetched"] += 1
            if progress_callback is not None:
                progress_callback(idx, total, ticker, inserted)
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return stats


def _ensure_utf8_streams() -> None:
    """Force stdout/stderr to UTF-8 to prevent cp1252 encode errors on Windows.

    vnstock 4.x may print Vietnamese status/warning messages during
    Quote.history() calls (e.g. delisting or status notices). Windows Python
    default codec (cp1252) can't encode Vietnamese characters, causing
    UnicodeEncodeError inside vnstock which propagates as a fetch failure.
    Reconfigure both streams to UTF-8 with replace-on-error fallback.
    """
    for stream in (sys.stdout, sys.stderr):
        if (
            hasattr(stream, "reconfigure")
            and stream.encoding
            and stream.encoding.lower() != "utf-8"
        ):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _ensure_utf8_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--end-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="Fetch up to this date (inclusive), YYYY-MM-DD (mutex --today)",
    )
    parser.add_argument(
        "--today",
        action="store_true",
        help="Shortcut for --end-date=<today> (mutex --end-date)",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated ticker subset (default: all 43 VN30 universe)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Validate --today vs --end-date (exactly one required)
    if args.today and args.end_date is not None:
        parser.error("--today and --end-date are mutually exclusive")
    if not args.today and args.end_date is None:
        parser.error("Either --today or --end-date is required")
    if args.today:
        args.end_date = date.today()

    tickers_list = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None

    # Log tier (sync_universe reads settings again silently)
    settings = get_settings()
    if settings.vnstock_api_key is not None:
        logger.info("vnstock tier: Community (API key configured, 60 req/min)")
    else:
        logger.warning(
            "vnstock tier: Guest (no API key, 20 req/min limit) — "
            "fetch of full VN30 universe will hit rate limit"
        )

    target_count = len(tickers_list) if tickers_list else len(VN30_UNIVERSE)
    logger.info(
        f"Sync target: {target_count} ticker(s), "
        f"end_date={args.end_date}, dry_run={args.dry_run}"
    )

    stats = sync_universe(
        end_date=args.end_date,
        tickers=tickers_list,
        dry_run=args.dry_run,
    )
    logger.info(f"DONE: total_inserted={stats['total_inserted']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
