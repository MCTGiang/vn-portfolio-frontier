"""Integration tests for news_sentiment schema (article + extracted_signal).

Assumes migrations applied. Verifies structural state per ADR-006 positioning
(structured extraction, NOT return prediction) + Q3 decision (JSONB entities).
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


def test_news_sentiment_has_both_tables() -> None:
    """Migration 004 created article + extracted_signal."""
    tables = set(list_tables("news_sentiment"))
    assert {"article", "extracted_signal"}.issubset(
        tables
    ), f"Missing tables in news_sentiment. Have: {sorted(tables)}"


def test_migration_004_recorded() -> None:
    """The tracking table records migration 004."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT filename FROM public._migrations WHERE filename = %s",
            ("004_create_news_sentiment_tables.sql",),
        )
        row = cur.fetchone()
    assert row is not None, "004_create_news_sentiment_tables.sql not recorded"


def test_article_has_expected_columns() -> None:
    """article schema matches design: URL-keyed dedup, source enum, bilingual-ready."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'news_sentiment'
              AND table_name = 'article'
            ORDER BY ordinal_position
            """)
        rows = cur.fetchall()

    columns = {row[0]: (row[1], row[2]) for row in rows}

    expected: dict[str, tuple[str, str]] = {
        "article_id": ("bigint", "NO"),
        "source": ("character varying", "NO"),
        "url": ("text", "NO"),
        "published_at": ("timestamp with time zone", "NO"),
        "title": ("text", "NO"),
        "body": ("text", "YES"),
        "language": ("character varying", "NO"),
        "scraped_at": ("timestamp with time zone", "NO"),
    }
    for name, (dtype, nullable) in expected.items():
        actual = columns.get(name)
        assert actual == (
            dtype,
            nullable,
        ), f"article.{name}: expected {(dtype, nullable)}, got {actual}"


def test_extracted_signal_has_expected_columns() -> None:
    """extracted_signal schema matches: entities JSONB, extractor_version, no direct ticker FK."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'news_sentiment'
              AND table_name = 'extracted_signal'
            ORDER BY ordinal_position
            """)
        rows = cur.fetchall()

    columns = {row[0]: (row[1], row[2]) for row in rows}

    expected: dict[str, tuple[str, str]] = {
        "signal_id": ("bigint", "NO"),
        "article_id": ("bigint", "NO"),
        "ticker": ("character varying", "NO"),
        "event_type": ("character varying", "NO"),
        "sentiment_score": ("numeric", "YES"),
        "sentiment_confidence": ("numeric", "YES"),
        "entities": ("jsonb", "YES"),
        "extractor_version": ("character varying", "NO"),
        "extracted_at": ("timestamp with time zone", "NO"),
    }
    for name, (dtype, nullable) in expected.items():
        actual = columns.get(name)
        assert actual == (
            dtype,
            nullable,
        ), f"extracted_signal.{name}: expected {(dtype, nullable)}, got {actual}"


def test_signal_fk_to_article_uses_cascade() -> None:
    """extracted_signal.article_id → article.article_id must use ON DELETE CASCADE."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT rc.delete_rule, kcu.column_name, ccu.table_name, ccu.column_name
            FROM information_schema.referential_constraints rc
            JOIN information_schema.key_column_usage kcu
                ON rc.constraint_name = kcu.constraint_name
                AND rc.constraint_schema = kcu.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
                ON rc.unique_constraint_name = ccu.constraint_name
                AND rc.unique_constraint_schema = ccu.constraint_schema
            WHERE rc.constraint_schema = 'news_sentiment'
              AND kcu.table_name = 'extracted_signal'
            """)
        row = cur.fetchone()

    assert row is not None, "No FK found on extracted_signal"
    delete_rule, column, foreign_table, foreign_column = row
    assert delete_rule == "CASCADE", f"Expected CASCADE, got {delete_rule}"
    assert column == "article_id"
    assert foreign_table == "article"
    assert foreign_column == "article_id"


def test_signal_dedupe_unique_constraint_exists() -> None:
    """UNIQUE (article_id, ticker, event_type, extractor_version) prevents rescore duplicates."""
    with connection_scope() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            WHERE tc.table_schema = 'news_sentiment'
              AND tc.table_name = 'extracted_signal'
              AND tc.constraint_type = 'UNIQUE'
              AND tc.constraint_name = 'uq_signal_dedupe'
            """)
        row = cur.fetchone()

    assert row is not None, "uq_signal_dedupe UNIQUE constraint missing"
