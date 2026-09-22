"""Integration tests for migration infrastructure and prices schema.

Assumes migrations have already been applied to the Neon database:

    python scripts/apply_migrations.py

Tests inspect information_schema to verify structural state. They do not
apply migrations themselves — that would risk running production DDL from
a test suite.

Skipped when NEON_DATABASE_URL is not configured (fresh clones, CI).
"""

from __future__ import annotations

import pytest

from vn_portfolio_frontier.db import (
    connection_scope,
    is_configured,
    list_schemas,
    list_tables,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_configured(),
        reason=(
            "NEON_DATABASE_URL not configured; " "run `cp .env.example .env` and set credentials"
        ),
    ),
]


def test_expected_schemas_exist() -> None:
    """Migration 001 created prices, fundamentals, news_sentiment."""
    schemas = set(list_schemas())
    assert {"prices", "fundamentals", "news_sentiment"}.issubset(schemas), (
        f"Missing schemas. Have: {sorted(schemas)}. "
        f"Did you run `python scripts/apply_migrations.py`?"
    )


def test_migrations_tracking_table_exists() -> None:
    """public._migrations tracking table was created by migration 001."""
    tables = set(list_tables("public"))
    assert (
        "_migrations" in tables
    ), "public._migrations missing. Did the migration runner set up correctly?"


def test_migrations_tracking_records_applied_files() -> None:
    """The tracking table records both migration 001 and 002."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("SELECT filename FROM public._migrations ORDER BY filename")
        recorded = {row[0] for row in cur.fetchall()}
    expected = {
        "001_create_schemas.sql",
        "002_create_prices_daily_ohlcv.sql",
    }
    assert expected.issubset(recorded), (
        f"Not all migrations recorded. Have: {sorted(recorded)}. "
        f"Missing: {sorted(expected - recorded)}"
    )


def test_prices_daily_ohlcv_table_exists() -> None:
    """Migration 002 created prices.daily_ohlcv."""
    tables = set(list_tables("prices"))
    assert "daily_ohlcv" in tables, f"prices.daily_ohlcv missing. Have in prices: {sorted(tables)}"


def test_prices_daily_ohlcv_has_expected_columns() -> None:
    """prices.daily_ohlcv has the columns the ADR-009 schema design specifies."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'prices'
              AND table_name = 'daily_ohlcv'
            ORDER BY ordinal_position
            """)
        columns = {row[0]: row[1] for row in cur.fetchall()}

    expected = {
        "ticker": "character varying",
        "trade_date": "date",
        "open_price": "numeric",
        "high_price": "numeric",
        "low_price": "numeric",
        "close_price": "numeric",
        "volume": "bigint",
        "source": "character varying",
        "ingested_at": "timestamp with time zone",
    }
    for name, expected_type in expected.items():
        actual_type = columns.get(name)
        assert (
            actual_type == expected_type
        ), f"Column {name}: expected {expected_type}, got {actual_type}"
