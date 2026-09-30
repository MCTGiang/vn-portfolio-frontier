"""Tests for scripts/fetch_fundamentals.py."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from vn_portfolio_frontier.config import get_settings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from fetch_fundamentals import (  # noqa: E402
    BATCH_SIZE,
    STATEMENT_METHODS,
    VN30_UNIVERSE,
    _ensure_utf8_streams,
    _is_valid_value,
    fetch_fundamentals,
    insert_rows,
)


class TestConstants:
    def test_vn30_universe_43_tickers(self):
        assert len(VN30_UNIVERSE) == 43

    def test_vn30_universe_all_unique(self):
        assert len(set(VN30_UNIVERSE)) == 43

    def test_statement_methods_3_types(self):
        assert set(STATEMENT_METHODS.keys()) == {"income", "ratio", "cash_flow"}

    def test_statement_methods_values(self):
        assert STATEMENT_METHODS["income"] == "income_statement"
        assert STATEMENT_METHODS["ratio"] == "ratio"
        assert STATEMENT_METHODS["cash_flow"] == "cash_flow"

    def test_batch_size(self):
        assert BATCH_SIZE == 5000


class TestIsValidValue:
    def test_none_returns_false(self):
        assert _is_valid_value(None) is False

    def test_nan_returns_false(self):
        assert _is_valid_value(float("nan")) is False

    def test_zero_returns_true(self):
        assert _is_valid_value(0.0) is True

    def test_int_returns_true(self):
        assert _is_valid_value(42) is True


class TestEnsureUtf8Streams:
    def test_idempotent(self):
        _ensure_utf8_streams()
        _ensure_utf8_streams()


class TestInsertRows:
    def test_empty_returns_zero(self):
        assert insert_rows(MagicMock(), []) == 0


class TestFetchFundamentalsOrchestrator:
    @pytest.fixture(autouse=True)
    def _mock_settings(self):
        with patch("fetch_fundamentals.get_settings") as m:
            m.return_value.neon_database_url.get_secret_value.return_value = "postgresql://fake"
            yield

    @patch("fetch_fundamentals.sync_ticker_statement")
    @patch("fetch_fundamentals.psycopg2.connect")
    def test_stats_dict_keys(self, mock_connect, mock_sync):
        mock_sync.return_value = (100, 100)
        result = fetch_fundamentals(tickers=["VCB"], statement_types=["income"], dry_run=True)
        assert set(result.keys()) == {
            "total_fetched",
            "total_inserted",
            "tickers_processed",
            "api_calls",
        }

    @patch("fetch_fundamentals.sync_ticker_statement")
    @patch("fetch_fundamentals.psycopg2.connect")
    def test_default_uses_all_universe(self, mock_connect, mock_sync):
        mock_sync.return_value = (0, 0)
        result = fetch_fundamentals(dry_run=True)
        assert result["api_calls"] == 129  # 43 × 3
        assert result["tickers_processed"] == 43


# ==================== Integration ====================
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

    def test_metric_snapshot_populated(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM fundamentals.metric_snapshot")
            assert cur.fetchone()[0] > 100000

    def test_all_43_tickers_present(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(DISTINCT ticker) FROM fundamentals.metric_snapshot")
            assert cur.fetchone()[0] == 43

    def test_3_statement_types(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT statement_type FROM fundamentals.metric_snapshot")
            types = {row[0] for row in cur.fetchall()}
            assert types == {"income", "ratio", "cash_flow"}

    def test_key_ratios_view_vcb(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pe_ratio, pb_ratio, roe_pct "
                "FROM fundamentals.key_ratios "
                "WHERE ticker='VCB' AND period='2026-Q2'"
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] is not None
            assert row[1] is not None
            assert row[2] is not None
