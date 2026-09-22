"""Integration tests for fundamentals schema (vn30_constituent + financial_report).

Assumes migrations applied. Verifies structural state per ADR-009 refactored
2-table design serving sentiment extraction ticker validation + context.
"""

from __future__ import annotations

import pytest

from vn_portfolio_frontier.db import connection_scope, is_configured, list_tables

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_configured(),
        reason=(
            "NEON_DATABASE_URL not configured; " "run `cp .env.example .env` and set credentials"
        ),
    ),
]


def test_fundamentals_has_both_tables() -> None:
    """Migration 003 created vn30_constituent + financial_report."""
    tables = set(list_tables("fundamentals"))
    assert {"vn30_constituent", "financial_report"}.issubset(
        tables
    ), f"Missing tables in fundamentals. Have: {sorted(tables)}"


def test_migration_003_recorded() -> None:
    """The tracking table records migration 003."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT filename FROM public._migrations WHERE filename = %s",
            ("003_create_fundamentals_tables.sql",),
        )
        row = cur.fetchone()
    assert row is not None, "003_create_fundamentals_tables.sql not recorded"


def test_vn30_constituent_has_expected_columns() -> None:
    """vn30_constituent has bilingual name + sector + historical tracking columns."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'fundamentals'
              AND table_name = 'vn30_constituent'
            ORDER BY ordinal_position
            """)
        rows = cur.fetchall()

    columns = {row[0]: (row[1], row[2]) for row in rows}

    expected: dict[str, tuple[str, str]] = {
        "ticker": ("character varying", "NO"),
        "company_name_vi": ("character varying", "NO"),
        "company_name_en": ("character varying", "YES"),
        "sector": ("character varying", "NO"),
        "exchange": ("character varying", "NO"),
        "listing_date": ("date", "YES"),
        "added_to_vn30_date": ("date", "YES"),
        "removed_from_vn30_date": ("date", "YES"),
        "is_current": ("boolean", "NO"),
        "source": ("character varying", "NO"),
        "ingested_at": ("timestamp with time zone", "NO"),
        "updated_at": ("timestamp with time zone", "NO"),
    }
    for name, (dtype, nullable) in expected.items():
        actual = columns.get(name)
        assert actual == (
            dtype,
            nullable,
        ), f"Column {name}: expected {(dtype, nullable)}, got {actual}"


def test_financial_report_has_expected_columns() -> None:
    """financial_report has minimal scope: revenue + net_income + EPS + metadata."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'fundamentals'
              AND table_name = 'financial_report'
            ORDER BY ordinal_position
            """)
        columns = {row[0]: row[1] for row in cur.fetchall()}

    expected = {
        "ticker": "character varying",
        "period_end": "date",
        "period_type": "character varying",
        "is_audited": "boolean",
        "revenue_vnd": "numeric",
        "net_income_vnd": "numeric",
        "eps_vnd": "numeric",
        "source": "character varying",
        "ingested_at": "timestamp with time zone",
    }
    for name, expected_type in expected.items():
        actual_type = columns.get(name)
        assert (
            actual_type == expected_type
        ), f"Column {name}: expected {expected_type}, got {actual_type}"

    # Ratios (PE, PB, ROE) intentionally NOT present — see ADR-009 evaluation.
    assert "pe_ratio" not in columns, "pe_ratio should not be in schema"
    assert "pb_ratio" not in columns, "pb_ratio should not be in schema"
    assert "roe_percent" not in columns, "roe_percent should not be in schema"


def test_financial_report_has_fk_to_vn30_constituent() -> None:
    """financial_report.ticker has FK to vn30_constituent.ticker."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT
                tc.constraint_name,
                kcu.column_name,
                ccu.table_schema AS foreign_table_schema,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'fundamentals'
              AND tc.table_name = 'financial_report'
            """)
        fks = cur.fetchall()

    assert len(fks) == 1, f"Expected exactly 1 FK on financial_report, got {len(fks)}"
    _, column, foreign_schema, foreign_table, foreign_column = fks[0]
    assert column == "ticker"
    assert foreign_schema == "fundamentals"
    assert foreign_table == "vn30_constituent"
    assert foreign_column == "ticker"
