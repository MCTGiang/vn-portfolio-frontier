-- Migration 010: Add initial_capital column to simulation.rebalance_run
--
-- Context: F-H3 Day 5 review finding - RunRecord DTO (Day 4) + Portfolio
-- aggregate root (Day 2) need an initial_capital value to instantiate
-- Portfolio(cash=initial_capital) at Simulator start (Day 6+). The column
-- was missing from Migration 005 which created the base rebalance_run table.

ALTER TABLE simulation.rebalance_run
    ADD COLUMN initial_capital NUMERIC(20,2) NOT NULL
        DEFAULT 1000000000.00
        CHECK (initial_capital > 0);

COMMENT ON COLUMN simulation.rebalance_run.initial_capital IS
    'Starting cash balance in VND for Portfolio aggregate at run start. '
    'Required: Simulator cannot run without an initial funding amount. '
    'Precision NUMERIC(20,2) matches cost columns + est_price (ADR-012).';
