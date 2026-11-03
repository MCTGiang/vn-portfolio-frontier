-- Migration 016: Extend chk_strategy_name_known for F2 periodic strategies
-- Context: Sprint 12 Ginny ships CalendarMonthlyStrategy + FixedWindowStrategy
--          (Strategy Pattern GoF extensibility proof per ADR-015 section 7.8).
--          Current CHECK constraint allows only ('periodic', 'threshold_band',
--          'hybrid'); extend to include specific strategy names.
--
-- Affected tables:
--   simulation.rebalance_run        (CHECK extended)
--   simulation.sensitivity_grid     (CHECK extended for consistency)
--
-- Compatibility: additive change, no data migration. Existing rows unchanged.

BEGIN;

-- 1. simulation.rebalance_run.strategy_name
ALTER TABLE simulation.rebalance_run
    DROP CONSTRAINT IF EXISTS chk_strategy_name_known;

ALTER TABLE simulation.rebalance_run
    ADD CONSTRAINT chk_strategy_name_known
    CHECK (strategy_name IN (
        'periodic',           -- legacy generic periodic (Sprint 10)
        'threshold_band',     -- ThresholdBandStrategy (Sprint 11 MUST)
        'calendar_monthly',   -- CalendarMonthlyStrategy (Sprint 12 SHOULD)
        'fixed_window',       -- FixedWindowStrategy (Sprint 12 SHOULD)
        'hybrid'              -- future HybridStrategy (DATN)
    ));

COMMENT ON COLUMN simulation.rebalance_run.strategy_name IS
    'Strategy identifier. threshold_band (ThresholdBandStrategy), '
    'calendar_monthly (CalendarMonthlyStrategy), fixed_window '
    '(FixedWindowStrategy), periodic (legacy generic), hybrid (future).';

-- 2. simulation.sensitivity_grid.strategy_name
ALTER TABLE simulation.sensitivity_grid
    DROP CONSTRAINT IF EXISTS chk_strategy_name_known;

ALTER TABLE simulation.sensitivity_grid
    ADD CONSTRAINT chk_strategy_name_known
    CHECK (strategy_name IN (
        'periodic',
        'threshold_band',
        'calendar_monthly',
        'fixed_window',
        'hybrid'
    ));

COMMIT;
