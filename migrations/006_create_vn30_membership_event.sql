-- Migration 006: VN30 membership event log + flattened constituent snapshot
--
-- Implements ADR-013 Schema section (Decision 1: event-sourcing with
-- hybrid materialization for VN30 constituent tracking).
--
-- Two tables:
--   1. fundamentals.vn30_membership_event -- append-only source of truth
--      for HOSE rebalance events. Seeded with 11 events (2021-2026) from
--      data/seed/vn30_history.yaml by scripts/seed_vn30_history.py.
--   2. fundamentals.vn30_membership_snapshot -- flattened (effective_date, ticker)
--      snapshot (360 rows = 12 periods x 30 tickers) for sub-ms indexed
--      queries by Streamlit UI dropdown and backtest engine.
--
-- Invariant enforced by tests/test_vn30_reconcile.py: folding the event
-- log at any effective_date must produce the same 30-ticker set as
-- querying vn30_membership_snapshot for that date.
--
-- Related ADRs: ADR-013 (this decision), ADR-002 (Neon PostgreSQL),
-- ADR-009 (feature-driven schema methodology).

CREATE SCHEMA IF NOT EXISTS fundamentals;

-- ============================================================
-- Event log: append-only source of truth
-- ============================================================

CREATE TABLE IF NOT EXISTS fundamentals.vn30_membership_event (
    event_id         BIGSERIAL PRIMARY KEY,
    effective_date   DATE NOT NULL,
    announced_date   DATE NOT NULL,
    rebalance_type   VARCHAR(20) NOT NULL,
    tickers_added    JSONB NOT NULL,
    tickers_removed  JSONB NOT NULL,
    source_ref       TEXT NOT NULL,
    notes            TEXT,
    logged_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_rebalance_type
        CHECK (rebalance_type IN ('january_review', 'july_review', 'special')),
    CONSTRAINT chk_dates
        CHECK (announced_date <= effective_date)
);

CREATE INDEX IF NOT EXISTS idx_vn30_event_effective_date
    ON fundamentals.vn30_membership_event (effective_date);

CREATE INDEX IF NOT EXISTS idx_vn30_event_type
    ON fundamentals.vn30_membership_event (rebalance_type);

-- ============================================================
-- Flattened snapshot: prepopulated view for fast reads
-- ============================================================

CREATE TABLE IF NOT EXISTS fundamentals.vn30_membership_snapshot (
    effective_date  DATE NOT NULL,
    ticker          VARCHAR(10) NOT NULL,
    PRIMARY KEY (effective_date, ticker)
);

CREATE INDEX IF NOT EXISTS idx_vn30_membership_snapshot_ticker
    ON fundamentals.vn30_membership_snapshot (ticker);
