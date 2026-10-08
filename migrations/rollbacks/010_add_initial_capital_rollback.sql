-- Rollback for Migration 010
ALTER TABLE simulation.rebalance_run
    DROP COLUMN IF EXISTS initial_capital;
