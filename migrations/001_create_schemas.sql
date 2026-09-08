-- ============================================================================
-- Migration 001: Create top-level schemas + migrations tracking table
-- ============================================================================
-- Runs first. Idempotent (IF NOT EXISTS) so re-running is safe.
--
-- Schemas:
--   prices          VN30 OHLCV time series (populated in Task 5 from
--                   Project 1 SQLite + fresh vnstock fetch for delta)
--   fundamentals    Quarterly + annual financial reports (VN30)
--   news_sentiment  Financial news articles + PhoBERT/RAG structured signals
--
-- Also creates public._migrations to track which SQL files have run.
-- See docs/architecture.md ADR-009 for schema design principles.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS prices;
CREATE SCHEMA IF NOT EXISTS fundamentals;
CREATE SCHEMA IF NOT EXISTS news_sentiment;

CREATE TABLE IF NOT EXISTS public._migrations (
    id              SERIAL PRIMARY KEY,
    filename        TEXT NOT NULL UNIQUE,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum_sha256 TEXT NOT NULL
);

COMMENT ON TABLE public._migrations IS
    'Tracks which SQL migration files have been applied. Prevents re-run and detects checksum drift.';
