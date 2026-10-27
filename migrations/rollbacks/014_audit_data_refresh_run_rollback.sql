-- Rollback for Migration 014: Drop audit.data_refresh_run table + schema if empty

DROP TABLE IF EXISTS audit.data_refresh_run;

-- Only drop schema if no other tables exist (safe for future audit tables)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_schema = 'audit'
    ) THEN
        DROP SCHEMA audit;
    END IF;
END $$;
