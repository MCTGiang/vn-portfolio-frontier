-- ============================================================================
-- Rollback Migration 009: Revert simulation schema v2
-- ============================================================================
-- Drops 3 tables added in 009 + removes 3 columns added to rebalance_run.
-- CASCADE drops ensure dependent indexes/constraints are removed.
-- Data loss WARNING: all rebalance_decision + sensitivity_grid + sensitivity_point
-- rows are destroyed. Use only when migration was applied in error OR
-- during development schema reset.
-- ============================================================================

DROP TABLE IF EXISTS simulation.sensitivity_point CASCADE;
DROP TABLE IF EXISTS simulation.sensitivity_grid CASCADE;
DROP TABLE IF EXISTS simulation.rebalance_decision CASCADE;

ALTER TABLE simulation.rebalance_run
    DROP CONSTRAINT IF EXISTS chk_run_status;

ALTER TABLE simulation.rebalance_run
    DROP COLUMN IF EXISTS error_message,
    DROP COLUMN IF EXISTS completed_at,
    DROP COLUMN IF EXISTS status;
