"""Tests for scripts/fetch_metadata.py."""

from __future__ import annotations

import contextlib
import sys
from datetime import date
from pathlib import Path

import psycopg2
import pytest

from vn_portfolio_frontier.config import get_settings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from fetch_metadata import get_current_vn30_tickers, parse_dd_mm_yyyy  # noqa: E402


class TestParseDDMMYYYY:
    def test_valid_date(self):
        assert parse_dd_mm_yyyy("30/06/2009") == date(2009, 6, 30)

    def test_with_spaces(self):
        assert parse_dd_mm_yyyy("  30/06/2009  ") == date(2009, 6, 30)

    def test_invalid_format(self):
        assert parse_dd_mm_yyyy("2009-06-30") is None

    def test_empty_string(self):
        assert parse_dd_mm_yyyy("") is None

    def test_none(self):
        assert parse_dd_mm_yyyy(None) is None

    def test_invalid_date_returns_none(self):
        assert parse_dd_mm_yyyy("32/13/2020") is None


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

    def test_43_rows_populated(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM fundamentals.vn30_constituent")
            assert cur.fetchone()[0] == 43

    def test_30_current_tickers(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM fundamentals.vn30_constituent WHERE is_current")
            assert cur.fetchone()[0] == 30

    def test_14_banks(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM fundamentals.vn30_constituent " "WHERE sector='Ngân hàng'"
            )
            assert cur.fetchone()[0] == 14

    def test_get_current_vn30_returns_30_set(self, conn):
        result = get_current_vn30_tickers(conn)
        assert isinstance(result, set)
        assert len(result) == 30
        assert "VCB" in result
