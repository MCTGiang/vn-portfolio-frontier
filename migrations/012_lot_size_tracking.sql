-- Migration 012: Lot size tracking (NFR-R-02 regulatory compliance, Day 9 Sprint 11)
--
-- Adds lot_rule_source column to simulation.rebalance_run for audit lineage.
-- Default 'HSX_2021' = Quyet dinh 496/QD-SGDHCM (HoSE 04/01/2021, lot 100 shares).
-- Multi-exchange extension (HNX/UPCoM 100-share rule, HSX pre-2021 10-share rule)
-- deferred to thesis Phase 2 - would require per-order exchange tag.

ALTER TABLE simulation.rebalance_run
    ADD COLUMN IF NOT EXISTS lot_rule_source TEXT NOT NULL DEFAULT 'HSX_2021';

COMMENT ON COLUMN simulation.rebalance_run.lot_rule_source IS
    'Lot size rule identifier applied during simulation. Default HSX_2021 = Quyet dinh 496/QD-SGDHCM, 100 shares from 2021-01-04.';
