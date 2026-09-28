"""Tests for scripts/sync_prices.py — universe-aware VN30 price sync.

Coverage:
- Unit tests (fast, no external deps): constants, cascade logic, skip logic,
  UTF-8 stream reconfigure, insert path.
- Integration tests (require NEON_URL env): schema column names verification,
  universe coverage, P1 source frozen invariant, get_latest_dates real query.
"""

from __future__ import annotations

import contextlib
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from vn_portfolio_frontier.config import get_settings

# Import script by path (scripts/ not on default PYTHONPATH)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from sync_prices import (  # noqa: E402
    BATCH_SIZE,
    DEFAULT_START,
    VN30_UNIVERSE,
    VNSTOCK_SOURCES,
    _ensure_utf8_streams,
    fetch_with_cascade,
    get_latest_dates,
    insert_rows,
    sync_ticker,
)

# ============================================================
# Unit tests (fast, no external deps)
# ============================================================


class TestConstants:
    def test_vn30_universe_has_43_tickers(self):
        assert len(VN30_UNIVERSE) == 43

    def test_vn30_universe_all_unique(self):
        assert len(set(VN30_UNIVERSE)) == 43

    def test_vn30_universe_sorted(self):
        assert sorted(VN30_UNIVERSE) == VN30_UNIVERSE

    def test_cascade_order_kbs_then_vci(self):
        assert VNSTOCK_SOURCES == ["kbs", "vci"]

    def test_default_start_is_first_vn30_snapshot(self):
        assert date(2021, 1, 4) == DEFAULT_START

    def test_batch_size_matches_p1_migrator(self):
        # Same batch size as scripts/migrate_p1_prices.py for execute_values page_size
        assert BATCH_SIZE == 5000


class TestEnsureUtf8Streams:
    def test_is_idempotent_and_safe(self):
        # Must never raise; safe to call multiple times
        _ensure_utf8_streams()
        _ensure_utf8_streams()


class TestGetLatestDates:
    def test_returns_all_43_universe_keys_even_when_db_partial(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("VCB", date(2026, 9, 25)),
            ("ACB", date(2026, 8, 21)),
        ]

        result = get_latest_dates(mock_conn)

        assert len(result) == 43
        assert result["VCB"] == date(2026, 9, 25)
        assert result["ACB"] == date(2026, 8, 21)
        # Unknown tickers get None (initial-fetch case)
        assert result["MCH"] is None

    def test_query_scopes_to_universe(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        get_latest_dates(mock_conn)

        call_args = mock_cursor.execute.call_args
        assert call_args[0][1] == (VN30_UNIVERSE,)


class TestSyncTicker:
    def test_skip_when_latest_equals_end_date(self):
        result = sync_ticker(
            MagicMock(),
            "VCB",
            latest=date(2026, 9, 25),
            end_date=date(2026, 9, 25),
            dry_run=True,
        )
        assert result == 0

    def test_skip_when_latest_beyond_end_date(self):
        result = sync_ticker(
            MagicMock(),
            "VCB",
            latest=date(2026, 10, 1),
            end_date=date(2026, 9, 25),
            dry_run=True,
        )
        assert result == 0

    @patch("sync_prices.fetch_with_cascade")
    def test_dry_run_calls_fetch_but_no_insert(self, mock_fetch):
        mock_fetch.return_value = (
            [("VCB", "2026-09-24", 60, 61, 59, 60.5, 1000, "vnstock")],
            "kbs",
        )
        result = sync_ticker(
            MagicMock(),
            "VCB",
            latest=date(2026, 9, 23),
            end_date=date(2026, 9, 25),
            dry_run=True,
        )
        assert result == 0
        mock_fetch.assert_called_once()

    @patch("sync_prices.fetch_with_cascade")
    def test_initial_fetch_uses_default_start(self, mock_fetch):
        mock_fetch.return_value = ([], "kbs")
        sync_ticker(
            MagicMock(),
            "VCB",
            latest=None,
            end_date=date(2026, 9, 25),
            dry_run=True,
        )
        # First positional arg to fetch_with_cascade is ticker, second is start_date
        called_start = mock_fetch.call_args[0][1]
        assert called_start == DEFAULT_START


class TestFetchWithCascade:
    @patch("sync_prices.fetch_via_vnstock")
    def test_all_sources_exhausted_raises_runtime_error(self, mock_fetch):
        mock_fetch.return_value = []
        with pytest.raises(RuntimeError, match="all sources exhausted"):
            fetch_with_cascade("VCB", date(2026, 8, 22), date(2026, 9, 25))

    @patch("sync_prices.fetch_via_vnstock")
    def test_kbs_success_skips_vci(self, mock_fetch):
        rows = [("VCB", "2026-09-24", 60, 61, 59, 60.5, 1000, "vnstock")]
        mock_fetch.return_value = rows

        result, source = fetch_with_cascade("VCB", date(2026, 8, 22), date(2026, 9, 25))

        assert source == "kbs"
        assert len(result) == 1
        assert mock_fetch.call_count == 1

    @patch("sync_prices.fetch_via_vnstock")
    def test_kbs_exception_falls_through_to_vci(self, mock_fetch):
        rows = [("VCB", "2026-09-24", 60, 61, 59, 60.5, 1000, "vnstock")]
        mock_fetch.side_effect = [Exception("kbs down"), rows]

        result, source = fetch_with_cascade("VCB", date(2026, 8, 22), date(2026, 9, 25))

        assert source == "vci"
        assert len(result) == 1


class TestInsertRows:
    def test_empty_rows_returns_zero(self):
        mock_conn = MagicMock()
        assert insert_rows(mock_conn, []) == 0

    def test_uses_price_suffixed_column_names(self):
        # Regression guard: schema uses open_price/high_price/low_price/close_price
        # (not open/high/low/close). Bug caught during initial B.3 execute.
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.rowcount = 1

        rows = [("VCB", "2026-09-24", 60, 61, 59, 60.5, 1000, "vnstock")]

        with patch("sync_prices.psycopg2.extras.execute_values") as mock_exec:
            insert_rows(mock_conn, rows)
            sql = mock_exec.call_args[0][1]
            assert "open_price" in sql
            assert "high_price" in sql
            assert "low_price" in sql
            assert "close_price" in sql
            # Ensure short names not used
            assert " open," not in sql
            assert " high," not in sql


# ============================================================
# Integration tests (require NEON_URL configured)
# ============================================================

NEON_AVAILABLE = False
with contextlib.suppress(Exception):
    NEON_AVAILABLE = bool(get_settings().neon_database_url.get_secret_value())


@pytest.mark.skipif(not NEON_AVAILABLE, reason="NEON_URL not configured")
class TestIntegration:
    @pytest.fixture
    def conn(self):
        dsn = get_settings().neon_database_url.get_secret_value()
        c = psycopg2.connect(dsn)
        yield c
        c.close()

    def test_get_latest_dates_returns_all_43_universe(self, conn):
        result = get_latest_dates(conn)
        assert len(result) == 43
        assert set(result.keys()) == set(VN30_UNIVERSE)

    def test_daily_ohlcv_schema_columns_match_insert_sql(self, conn):
        # Regression guard: script INSERT column list must match live schema
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='prices' AND table_name='daily_ohlcv'
                ORDER BY ordinal_position
            """)
            cols = [r[0] for r in cur.fetchall()]
        expected = [
            "ticker",
            "trade_date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "source",
            "ingested_at",
        ]
        assert cols == expected

    def test_all_43_tickers_reach_2026_09_25(self, conn):
        # Post-sync invariant: every VN30 ticker has data through 2026-09-25
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT ticker
                    FROM prices.daily_ohlcv
                    WHERE ticker = ANY(%s)
                    GROUP BY ticker
                    HAVING MAX(trade_date) >= '2026-09-25'
                ) t
                """,
                (VN30_UNIVERSE,),
            )
            count = cur.fetchone()[0]
        assert count == 43

    def test_p1_source_frozen_at_2026_08_21(self, conn):
        # Invariant: sqlite_project1 rows never updated by sync_prices script.
        # All post-2026-08-21 data must come from vnstock source only.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(trade_date) FROM prices.daily_ohlcv WHERE source = 'sqlite_project1'"
            )
            latest = cur.fetchone()[0]
        assert latest == date(2026, 8, 21)

    def test_vnstock_source_covers_full_universe(self, conn):
        # vnstock source must have all 43 tickers (14 initial + 29 delta post-B.3)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT ticker) FROM prices.daily_ohlcv WHERE source = 'vnstock'"
            )
            count = cur.fetchone()[0]
        assert count == 43
