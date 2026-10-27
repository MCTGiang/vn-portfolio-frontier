-- Migration 014: Audit log for scheduled data refresh runs (Day 12, Sprint 11)
--
-- Table tracks execution of scripts/sync_prices.py and scripts/sync_benchmarks.py
-- triggered by GitHub Actions daily cron (per ADR-018).
--
-- Lineage: 1 cron fire -> N script runs (currently 2: prices + benchmarks)
-- Each run_id corresponds to 1 script invocation (not 1 cron fire).
--
-- Status enum covers full lifecycle: pending (started, not finished) -> succeeded
-- (clean exit, rows_fetched >= 0) OR failed (error_message populated).
-- Scheduler sets status=pending at script start, updates to succeeded/failed on exit.

CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.data_refresh_run (
    run_id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    script_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'pending',
    rows_fetched INTEGER DEFAULT 0,
    error_message TEXT,
    github_run_id TEXT,
    github_run_url TEXT,
    source TEXT NOT NULL DEFAULT 'github_actions_cron',
    CONSTRAINT chk_status_known CHECK (status IN ('pending','succeeded','failed')),
    CONSTRAINT chk_script_name_known CHECK (script_name IN ('sync_prices','sync_benchmarks','sync_universe')),
    CONSTRAINT chk_rows_nonneg CHECK (rows_fetched >= 0),
    CONSTRAINT chk_finished_requires_status CHECK (
        (status = 'pending' AND finished_at IS NULL)
        OR (status IN ('succeeded','failed') AND finished_at IS NOT NULL)
    ),
    CONSTRAINT chk_failed_requires_error CHECK (
        status != 'failed' OR error_message IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_data_refresh_run_started
    ON audit.data_refresh_run(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_data_refresh_run_script_status
    ON audit.data_refresh_run(script_name, status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_data_refresh_run_github
    ON audit.data_refresh_run(github_run_id)
    WHERE github_run_id IS NOT NULL;

COMMENT ON TABLE audit.data_refresh_run IS
    'Audit log for daily GitHub Actions cron data refresh runs. 1 row per script invocation. See ADR-018.';
COMMENT ON COLUMN audit.data_refresh_run.github_run_id IS
    'GitHub Actions run ID (${{ github.run_id }}) for cross-referencing with workflow logs (90-day retention).';
COMMENT ON COLUMN audit.data_refresh_run.source IS
    'Trigger source: github_actions_cron | github_actions_dispatch | local_dev | manual_backfill.';
