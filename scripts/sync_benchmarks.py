"""Sync benchmark Rf series from vnstock into Neon benchmark schema.

Fetches three series for the Rf injection pathway (Day 9 Step B, Sprint 11):
  1. VN Government Bond yields (5 tenors) -> benchmark.vn_bond_yield
  2. SBV refinance + discount rates -> benchmark.sbv_policy_rate
  3. Big-4 bank deposit rates per tenor -> benchmark.bank_deposit_rate

Idempotent upsert via INSERT ... ON CONFLICT DO UPDATE. Daily sync safe.

Usage:
    python scripts/sync_benchmarks.py --start 2021-01-04 --end 2026-10-15
    python scripts/sync_benchmarks.py --today
    python scripts/sync_benchmarks.py --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
from datetime import date, datetime

import psycopg2
import psycopg2.extras

try:
    from vn_portfolio_frontier.config import get_settings
except ImportError:
    print("ERROR: Run from repo root, or add src to PYTHONPATH", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# vnstock Sponsor Silver tier activation (Day 9 preamble pattern)
# ---------------------------------------------------------------------------
import os as _os_vn  # noqa: E402

_vn_api_key = _os_vn.environ.get("VNSTOCK_API_KEY")
if _vn_api_key:
    try:
        import vnstock as _vns_login

        _vns_login.login(_vn_api_key)
    except Exception as _e:
        print(f"[warn] vnstock.login failed: {_e}", file=sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _ensure_utf8_streams() -> None:
    """UTF-8 stdout/stderr for Windows (M5 pattern)."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_START = date(2021, 1, 4)
BOND_TENORS = ("1Y", "2Y", "3Y", "5Y", "10Y")
TARGET_BANKS = ("VCB", "BIDV", "CTG", "VPB", "VIB", "TCB", "MBB", "ACB")


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


def fetch_bond_yields(start: date, end: date) -> list[tuple]:
    """Fetch VN govt bond yields for 5 tenors in range."""
    from vnstock import Macro

    m = Macro()
    rows: list[tuple] = []
    for tenor in BOND_TENORS:
        logger.info("  fetching bond yield tenor=%s %s -> %s", tenor, start, end)
        try:
            df = m.global_macro.bond_yield(
                market="VN",
                tenor=tenor,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
            )
        except Exception as exc:
            logger.warning("    tenor %s fetch failed: %s", tenor, exc)
            continue
        if df is None or df.empty:
            logger.warning("    tenor %s returned empty", tenor)
            continue
        for _, row in df.iterrows():
            trade_date = row["time"].date() if hasattr(row["time"], "date") else row["time"]
            rows.append(
                (
                    trade_date,
                    tenor,
                    row.get("open"),
                    row.get("high"),
                    row.get("low"),
                    row["close"],
                )
            )
    return rows


def fetch_policy_rates(start: date, end: date) -> list[tuple]:
    """Fetch SBV refinance + discount rates in range."""
    from vnstock import Macro

    m = Macro()
    logger.info("  fetching SBV policy_rate %s -> %s", start, end)
    try:
        df = m.currency().policy_rate(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
        )
    except Exception as exc:
        logger.warning("    policy_rate fetch failed: %s", exc)
        return []
    if df is None or df.empty:
        logger.warning("    policy_rate returned empty")
        return []
    rows = []
    for _, row in df.iterrows():
        trade_date = row["time"].date() if hasattr(row["time"], "date") else row["time"]
        rows.append(
            (
                trade_date,
                row["refinance"],
                row.get("discount"),
            )
        )
    return rows


def fetch_deposit_rates() -> list[tuple]:
    """Fetch bank deposit rates (snapshot current, no history param)."""
    from vnstock import Macro

    m = Macro()
    logger.info("  fetching bank deposit_rate snapshot")
    try:
        df = m.currency().deposit_rate(mode="term")
    except Exception as exc:
        logger.warning("    deposit_rate fetch failed: %s", exc)
        return []
    if df is None or df.empty:
        logger.warning("    deposit_rate returned empty")
        return []
    rows = []
    for _, row in df.iterrows():
        bank_code = row.get("bank_code")
        if bank_code not in TARGET_BANKS:
            continue
        rate_date = row["time"].date() if hasattr(row["time"], "date") else row["time"]
        rows.append(
            (
                rate_date,
                bank_code,
                row.get("bank_name"),
                row.get("interest_1m"),
                row.get("interest_3m"),
                row.get("interest_6m"),
                row.get("interest_13m"),
                row.get("interest_36m"),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------


def upsert_bond_yields(conn, rows: list[tuple]) -> int:
    if not rows:
        return 0
    # Dedup by (yield_date, tenor) PK - vnstock can return multiple rows per key
    seen = {}
    for row in rows:
        seen[(row[0], row[1])] = row  # last wins
    rows = list(seen.values())
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO benchmark.vn_bond_yield
                (yield_date, tenor, yield_open, yield_high, yield_low, yield_close)
            VALUES %s
            ON CONFLICT (yield_date, tenor) DO UPDATE SET
                yield_open = EXCLUDED.yield_open,
                yield_high = EXCLUDED.yield_high,
                yield_low = EXCLUDED.yield_low,
                yield_close = EXCLUDED.yield_close,
                loaded_at = NOW()
            """,
            rows,
            page_size=1000,
        )
    conn.commit()
    return len(rows)


def upsert_policy_rates(conn, rows: list[tuple]) -> int:
    if not rows:
        return 0
    # Dedup by rate_date PK
    seen = {}
    for row in rows:
        seen[row[0]] = row
    rows = list(seen.values())
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO benchmark.sbv_policy_rate
                (rate_date, refinance_pct, discount_pct)
            VALUES %s
            ON CONFLICT (rate_date) DO UPDATE SET
                refinance_pct = EXCLUDED.refinance_pct,
                discount_pct = EXCLUDED.discount_pct,
                loaded_at = NOW()
            """,
            rows,
            page_size=1000,
        )
    conn.commit()
    return len(rows)


def upsert_deposit_rates(conn, rows: list[tuple]) -> int:
    if not rows:
        return 0
    # Dedup by (rate_date, bank_code) PK
    seen = {}
    for row in rows:
        seen[(row[0], row[1])] = row
    rows = list(seen.values())
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO benchmark.bank_deposit_rate
                (rate_date, bank_code, bank_name, interest_1m, interest_3m,
                 interest_6m, interest_13m, interest_36m)
            VALUES %s
            ON CONFLICT (rate_date, bank_code) DO UPDATE SET
                bank_name = EXCLUDED.bank_name,
                interest_1m = EXCLUDED.interest_1m,
                interest_3m = EXCLUDED.interest_3m,
                interest_6m = EXCLUDED.interest_6m,
                interest_13m = EXCLUDED.interest_13m,
                interest_36m = EXCLUDED.interest_36m,
                loaded_at = NOW()
            """,
            rows,
            page_size=1000,
        )
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def sync_benchmarks(start: date, end: date, dry_run: bool = False) -> dict:
    _ensure_utf8_streams()
    logger.info("Fetching benchmark Rf series: %s -> %s (dry_run=%s)", start, end, dry_run)

    bond_rows = fetch_bond_yields(start, end)
    policy_rows = fetch_policy_rates(start, end)
    deposit_rows = fetch_deposit_rates()

    logger.info(
        "Fetched: %d bond + %d policy + %d deposit rows",
        len(bond_rows),
        len(policy_rows),
        len(deposit_rows),
    )

    if dry_run:
        logger.info("DRY RUN - skipping Neon upsert")
        return {
            "bond_fetched": len(bond_rows),
            "policy_fetched": len(policy_rows),
            "deposit_fetched": len(deposit_rows),
            "bond_upserted": 0,
            "policy_upserted": 0,
            "deposit_upserted": 0,
        }

    settings = get_settings()
    neon_url = settings.neon_database_url.get_secret_value()
    with psycopg2.connect(neon_url) as conn:
        n_bond = upsert_bond_yields(conn, bond_rows)
        n_policy = upsert_policy_rates(conn, policy_rows)
        n_deposit = upsert_deposit_rates(conn, deposit_rows)

    logger.info(
        "Upserted: %d bond + %d policy + %d deposit = %d total rows",
        n_bond,
        n_policy,
        n_deposit,
        n_bond + n_policy + n_deposit,
    )

    return {
        "bond_fetched": len(bond_rows),
        "policy_fetched": len(policy_rows),
        "deposit_fetched": len(deposit_rows),
        "bond_upserted": n_bond,
        "policy_upserted": n_policy,
        "deposit_upserted": n_deposit,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync benchmark Rf series from vnstock to Neon")
    parser.add_argument("--start", type=str, help="Start date YYYY-MM-DD (default 2021-01-04)")
    parser.add_argument("--end", type=str, help="End date YYYY-MM-DD (default today)")
    parser.add_argument("--today", action="store_true", help="Fetch today only (shorthand)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + log, skip Neon insert")
    args = parser.parse_args()

    if args.today:
        start = end = date.today()
    else:
        start = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else DEFAULT_START
        end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else date.today()

    stats = sync_benchmarks(start=start, end=end, dry_run=args.dry_run)
    logger.info("DONE: %s", stats)


if __name__ == "__main__":
    main()
