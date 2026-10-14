-- Rollback migration 012: drop lot_rule_source column
ALTER TABLE simulation.rebalance_run DROP COLUMN IF EXISTS lot_rule_source;
