"""Fetch fundamentals data (income, ratio, cash_flow) for VN30 universe.

Uses vnstock_data (Silver tier) for full 34-quarter historical depth.
Inserts long-form rows into fundamentals.metric_snapshot.

Idempotency via UNIQUE constraint (ticker, period, statement_type, metric_id).
ON CONFLICT DO NOTHING preserves earliest ingested_at timestamp.

Rate limit: Silver tier 300 req/min > 43 * 3 = 129 calls needed. No throttle required.

Usage:
    python scripts/fetch_fundamentals.py --dry-run
    python scripts/fetch_fundamentals.py --tickers VCB,FPT
    python scripts/fetch_fundamentals.py --statements income,ratio
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys

import psycopg2
import psycopg2.extras


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


try:
    from vn_portfolio_frontier.config import get_settings
except ImportError:
    print("ERROR: Run from repo root", file=sys.stderr)
    sys.exit(1)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# 43-ticker VN30 all-time universe (2021-2026)
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


# Statement types -> vnstock_data equity method names
STATEMENT_METHODS: dict[str, str] = {
    "income": "income_statement",  # 26 items * 34 periods
    "ratio": "ratio",  # 60 items * 33 periods (P/E, P/B, ROE, ROA)
    "cash_flow": "cash_flow",  # 51 items * 34 periods
}


BATCH_SIZE = 5000


def _is_valid_value(v) -> bool:
    """Check value is not None and not NaN (float NaN != NaN)."""
    if v is None:
        return False
    return not (isinstance(v, float) and v != v)  # NaN check


def fetch_statement(ticker: str, statement_type: str) -> list[tuple]:
    """Fetch one statement for one ticker. Returns list of insert tuples.

    Row shape:
        (ticker, period, statement_type, metric_id, metric_name,
         metric_order, metric_level, unit, value, source)
    """
    from vnstock_data import Fundamental

    method_name = STATEMENT_METHODS[statement_type]
    fa = Fundamental()
    eq = fa.equity(symbol=ticker)
    df = getattr(eq, method_name)(period="quarter")

    if df is None or df.empty:
        return []

    # Filter out rows with NaN period (balance_sheet edge case, not in scope but defensive)
    df = df.dropna(subset=["period"])

    rows = []
    for _, row in df.iterrows():
        # Skip category headers (RT_CAT_* have empty unit)
        unit = row.get("unit", "")
        if not unit:
            continue
        value = row["value"]
        if not _is_valid_value(value):
            continue
        rows.append(
            (
                ticker,
                str(row["period"]),
                statement_type,
                str(row["id"]),
                str(row["name"]),
                int(row["order"]) if _is_valid_value(row.get("order")) else None,
                int(row["level"]) if _is_valid_value(row.get("level")) else None,
                str(unit),
                float(value),
                "vnstock_data",
            )
        )
    return rows


def insert_rows(conn, rows: list[tuple]) -> int:
    """Batch insert with ON CONFLICT DO NOTHING. Returns rowcount."""
    if not rows:
        return 0
    sql = """
        INSERT INTO fundamentals.metric_snapshot
            (ticker, period, statement_type, metric_id, metric_name,
             metric_order, metric_level, unit, value, source)
        VALUES %s
        ON CONFLICT (ticker, period, statement_type, metric_id) DO NOTHING
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=BATCH_SIZE)
        return cur.rowcount


def sync_ticker_statement(conn, ticker: str, statement_type: str, dry_run: bool) -> tuple[int, int]:
    """Sync one (ticker, statement) pair. Returns (rows_fetched, rows_inserted)."""
    logger.info(f"  {ticker}: fetching {statement_type}...")
    rows = fetch_statement(ticker, statement_type)
    if dry_run:
        logger.info(f"  {ticker}: [DRY-RUN] {statement_type} = {len(rows)} rows")
        return len(rows), 0
    inserted = insert_rows(conn, rows)
    logger.info(f"  {ticker}: {statement_type} inserted {inserted}/{len(rows)} rows")
    return len(rows), inserted


def fetch_fundamentals(
    tickers: list[str] | None = None,
    statement_types: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Public API: fetch fundamentals for tickers * statement_types.

    Args:
        tickers: subset of VN30_UNIVERSE, None = all 43
        statement_types: subset of STATEMENT_METHODS keys, None = all 3
        dry_run: skip INSERT if True

    Returns:
        dict {total_fetched, total_inserted, tickers_processed, api_calls}
    """
    if tickers is None:
        tickers = VN30_UNIVERSE
    if statement_types is None:
        statement_types = list(STATEMENT_METHODS.keys())

    settings = get_settings()
    dsn = settings.neon_database_url.get_secret_value()

    stats = {
        "total_fetched": 0,
        "total_inserted": 0,
        "tickers_processed": 0,
        "api_calls": 0,
    }

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    try:
        for ticker in tickers:
            for stmt in statement_types:
                fetched, inserted = sync_ticker_statement(conn, ticker, stmt, dry_run)
                stats["total_fetched"] += fetched
                stats["total_inserted"] += inserted
                stats["api_calls"] += 1
            stats["tickers_processed"] += 1
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return stats


def main() -> int:
    _ensure_utf8_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated tickers (default: all 43 VN30 universe)",
    )
    parser.add_argument(
        "--statements",
        type=str,
        default=None,
        help="Comma-separated: income,ratio,cash_flow (default: all 3)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    statement_types = [s.strip() for s in args.statements.split(",")] if args.statements else None

    # Validate statement types
    if statement_types:
        invalid = [s for s in statement_types if s not in STATEMENT_METHODS]
        if invalid:
            parser.error(
                f"Invalid statement types: {invalid}. " f"Valid: {list(STATEMENT_METHODS.keys())}"
            )

    target_count = len(tickers) if tickers else len(VN30_UNIVERSE)
    stmt_count = len(statement_types) if statement_types else len(STATEMENT_METHODS)
    logger.info(
        f"Fetch target: {target_count} ticker(s) x {stmt_count} statement type(s), "
        f"dry_run={args.dry_run}"
    )

    stats = fetch_fundamentals(
        tickers=tickers,
        statement_types=statement_types,
        dry_run=args.dry_run,
    )
    logger.info(f"DONE: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
