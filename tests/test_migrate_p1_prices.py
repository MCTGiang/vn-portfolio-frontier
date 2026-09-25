"""Tests for P1 SQLite → Neon migration (Task 5A B.2).

Two tiers:
- unit: pure logic on SQLite (no Neon), CI-safe.
- integration: verify Neon state post-migration.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from migrate_p1_prices import (  # noqa: E402
    DEFAULT_SQLITE_PATH,
    EXPECTED_ROW_COUNT,
    EXPECTED_TICKER_COUNT,
    SOURCE_TAG,
    load_p1_prices,
)

# ============================================================
# Unit tests (SQLite load logic, no Neon)
# ============================================================


@pytest.fixture(scope="module")
def p1_rows():
    if not DEFAULT_SQLITE_PATH.exists():
        pytest.skip(f"P1 SQLite not found at {DEFAULT_SQLITE_PATH}")
    return load_p1_prices(DEFAULT_SQLITE_PATH)


@pytest.mark.unit
def test_load_row_count(p1_rows):
    assert len(p1_rows) == EXPECTED_ROW_COUNT


@pytest.mark.unit
def test_load_row_shape(p1_rows):
    """Each row is an 8-tuple with source tag at last position."""
    for row in p1_rows[:5]:
        assert len(row) == 8
        assert row[-1] == SOURCE_TAG


@pytest.mark.unit
def test_load_ticker_count(p1_rows):
    tickers = {row[0] for row in p1_rows}
    assert len(tickers) == EXPECTED_TICKER_COUNT


@pytest.mark.unit
def test_load_date_range(p1_rows):
    """First row is earliest date, last row is latest date (sorted by ticker,date)."""
    all_dates = {row[1] for row in p1_rows}
    assert min(all_dates) == "2021-01-04"
    assert max(all_dates) == "2026-08-21"


@pytest.mark.unit
def test_no_null_close_prices(p1_rows):
    """Neon close_price is NOT NULL — verify source has no nulls."""
    nulls = [row for row in p1_rows if row[5] is None]
    assert not nulls, f"Found {len(nulls)} rows with NULL close price"


# ============================================================
# Integration tests (Neon post-migration)
# ============================================================

try:
    from vn_portfolio_frontier.config import get_settings

    _url = get_settings().neon_database_url.get_secret_value()
    NEON_URL = _url if _url and _url.startswith(("postgresql://", "postgres://")) else None
except Exception:
    NEON_URL = None

requires_neon = pytest.mark.skipif(
    not NEON_URL,
    reason="Neon URL not configured; integration tests require live DB",
)


@pytest.fixture(scope="module")
def db_conn():
    import psycopg2

    conn = psycopg2.connect(NEON_URL)
    yield conn
    conn.close()


@pytest.mark.integration
@requires_neon
def test_neon_row_count_matches_p1(db_conn):
    """Neon row count with source='sqlite_project1' equals P1 SQLite count."""
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM prices.daily_ohlcv WHERE source = %s",
            (SOURCE_TAG,),
        )
        n = cur.fetchone()[0]
    assert n == EXPECTED_ROW_COUNT


@pytest.mark.integration
@requires_neon
def test_neon_ticker_count(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(DISTINCT ticker) FROM prices.daily_ohlcv WHERE source = %s",
            (SOURCE_TAG,),
        )
        n = cur.fetchone()[0]
    assert n == EXPECTED_TICKER_COUNT


@pytest.mark.integration
@requires_neon
def test_neon_date_range(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(trade_date), MAX(trade_date) FROM prices.daily_ohlcv " "WHERE source = %s",
            (SOURCE_TAG,),
        )
        dmin, dmax = cur.fetchone()
    assert str(dmin) == "2021-01-04"
    assert str(dmax) == "2026-08-21"


@pytest.mark.integration
@requires_neon
def test_neon_sample_ohlcv_present(db_conn):
    """Spot-check ACB 2021-01-04 row (known first-row values from Cụm 3 dry-run)."""
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT open_price, high_price, low_price, close_price, volume "
            "FROM prices.daily_ohlcv "
            "WHERE ticker = 'ACB' AND trade_date = '2021-01-04' AND source = %s",
            (SOURCE_TAG,),
        )
        row = cur.fetchone()
    assert row is not None, "ACB 2021-01-04 not found"
    o, h, lo, c, v = row
    assert float(o) == 10.71
    assert float(h) == 10.82
    assert float(lo) == 10.69
    assert float(c) == 10.75
    assert v == 10776300
