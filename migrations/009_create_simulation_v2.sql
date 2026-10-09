-- ============================================================================
-- Migration 009: Extend simulation schema cho Feature 2 build (Sprint 11)
-- ============================================================================
-- Context: Migration 005 (Sprint 10 Task 4b) created simulation.rebalance_run
-- as scenario header per ADR-012 cost model. Sprint 11 Feature 2 MUST tier
-- adds:
--   1. simulation.rebalance_decision  - 1 row per trigger event in a run
--   2. simulation.sensitivity_grid    - header per parameter sweep (UC-F2-02)
--   3. simulation.sensitivity_point   - grid cell linking to a rebalance_run
--
-- Also extends rebalance_run with execution tracking:
--   - status VARCHAR(20) DEFAULT 'completed'
--   - completed_at TIMESTAMPTZ
--   - error_message TEXT
--
-- Design decisions:
-- - All FK to rebalance_run use BIGINT (match Migration 005's BIGSERIAL run_id)
-- - sensitivity_grid uses UUID PK (independent lifecycle; allows client-side
--   pre-allocation when batch-submitting sweeps)
-- - ON DELETE CASCADE: deleting a run cascades to decisions + sensitivity_points
-- - JSONB for weights_before/after + orders_json (flexible per ADR-015)
-- - CHECK constraints enforce invariants at DB level
-- - UNIQUE (grid_id, x_name, x_value, y_name, y_value) prevents duplicate cells
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Part 1: Extend simulation.rebalance_run with execution tracking
-- ----------------------------------------------------------------------------

ALTER TABLE simulation.rebalance_run
    ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'completed',
    ADD COLUMN completed_at TIMESTAMPTZ,
    ADD COLUMN error_message TEXT;

ALTER TABLE simulation.rebalance_run
    ADD CONSTRAINT chk_run_status
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled'));

COMMENT ON COLUMN simulation.rebalance_run.status IS
    'Execution state. Default completed for synchronous Sprint 11 runs. Future async execution uses running/failed/cancelled.';

COMMENT ON COLUMN simulation.rebalance_run.completed_at IS
    'Timestamp when run reached terminal state (completed/failed/cancelled). NULL while status=running.';

COMMENT ON COLUMN simulation.rebalance_run.error_message IS
    'Error detail when status=failed. NULL otherwise.';


-- ----------------------------------------------------------------------------
-- Part 2: simulation.rebalance_decision - per-trigger event audit
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS simulation.rebalance_decision (
    decision_id             BIGSERIAL       PRIMARY KEY,
    run_id                  BIGINT          NOT NULL,

    trigger_date            DATE            NOT NULL,
    reason                  VARCHAR(100)    NOT NULL,

    weights_before          JSONB           NOT NULL,
    weights_after           JSONB           NOT NULL,
    weight_drift_bps        INTEGER,

    portfolio_value_before  NUMERIC(20, 2),
    portfolio_value_after   NUMERIC(20, 2),

    orders_json             JSONB           NOT NULL,
    order_count             INTEGER         NOT NULL DEFAULT 0,

    cost_brokerage          NUMERIC(20, 2)  NOT NULL DEFAULT 0,
    cost_slippage           NUMERIC(20, 2)  NOT NULL DEFAULT 0,
    cost_tax                NUMERIC(20, 2)  NOT NULL DEFAULT 0,
    cost_total              NUMERIC(20, 2)  NOT NULL DEFAULT 0,

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_decision_run
        FOREIGN KEY (run_id)
        REFERENCES simulation.rebalance_run(run_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_decision_order_count_nonneg
        CHECK (order_count >= 0),

    CONSTRAINT chk_decision_cost_nonneg
        CHECK (cost_brokerage >= 0
               AND cost_slippage >= 0
               AND cost_tax >= 0
               AND cost_total >= 0),

    CONSTRAINT chk_decision_reason_known
        CHECK (reason IN ('band_drift', 'calendar', 'window', 'hybrid', 'manual'))
);

CREATE INDEX IF NOT EXISTS idx_decision_run_id
    ON simulation.rebalance_decision (run_id);

CREATE INDEX IF NOT EXISTS idx_decision_trigger_date
    ON simulation.rebalance_decision (trigger_date);

COMMENT ON TABLE simulation.rebalance_decision IS
    '1 row per trigger event in a rebalance_run. ADR-015 §2.3 Template Method writes RebalanceDecision here.';

COMMENT ON COLUMN simulation.rebalance_decision.reason IS
    'Why trigger fired. band_drift (ThresholdBand), calendar (CalendarMonthly), window (FixedWindow), hybrid, or manual.';

COMMENT ON COLUMN simulation.rebalance_decision.weight_drift_bps IS
    'Max abs drift (bps) across tickers at trigger_date. Null for calendar/window triggers.';

COMMENT ON COLUMN simulation.rebalance_decision.orders_json IS
    'Order list as JSONB array: [{"ticker":"VCB","side":"BUY","shares":100,"est_price":125000}, ...]';


-- ----------------------------------------------------------------------------
-- Part 3: simulation.sensitivity_grid - sweep header
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS simulation.sensitivity_grid (
    grid_id             UUID            PRIMARY KEY,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,

    strategy_name       VARCHAR(30)     NOT NULL,
    param_grid_json     JSONB           NOT NULL,

    target_weights      JSONB           NOT NULL,
    backtest_start      DATE            NOT NULL,
    backtest_end        DATE            NOT NULL,

    grid_rows           INTEGER         NOT NULL,
    grid_cols           INTEGER         NOT NULL,

    CONSTRAINT chk_grid_strategy_known
        CHECK (strategy_name IN ('periodic', 'threshold_band', 'hybrid')),

    CONSTRAINT chk_grid_dates
        CHECK (backtest_end >= backtest_start),

    CONSTRAINT chk_grid_dimensions
        CHECK (grid_rows > 0
               AND grid_cols > 0
               AND grid_rows <= 50
               AND grid_cols <= 50)
);

CREATE INDEX IF NOT EXISTS idx_grid_strategy
    ON simulation.sensitivity_grid (strategy_name);

CREATE INDEX IF NOT EXISTS idx_grid_created
    ON simulation.sensitivity_grid (created_at DESC);

COMMENT ON TABLE simulation.sensitivity_grid IS
    'Header for parameter sensitivity sweep (UC-F2-02). Each grid spawns rows x cols rebalance_runs.';

COMMENT ON COLUMN simulation.sensitivity_grid.param_grid_json IS
    'Grid spec. Example: {"x":{"name":"brokerage_pct","min":0,"max":0.004,"steps":10},"y":{"name":"band_pct","min":1,"max":10,"steps":10}}';


-- ----------------------------------------------------------------------------
-- Part 4: simulation.sensitivity_point - grid cell
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS simulation.sensitivity_point (
    point_id            BIGSERIAL       PRIMARY KEY,
    grid_id             UUID            NOT NULL,
    run_id              BIGINT          NOT NULL,

    param_x_name        VARCHAR(50)     NOT NULL,
    param_x_value       NUMERIC(20, 8)  NOT NULL,
    param_y_name        VARCHAR(50)     NOT NULL,
    param_y_value       NUMERIC(20, 8)  NOT NULL,

    -- Metric cache (de-normalized from rebalance_run for fast grid query)
    sharpe_after_cost   NUMERIC(6, 4),
    total_cost_bps      SMALLINT,
    turnover_avg_pct    NUMERIC(5, 2),
    n_rebalances        INTEGER,

    CONSTRAINT fk_point_grid
        FOREIGN KEY (grid_id)
        REFERENCES simulation.sensitivity_grid(grid_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_point_run
        FOREIGN KEY (run_id)
        REFERENCES simulation.rebalance_run(run_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_point_grid_position
        UNIQUE (grid_id, param_x_name, param_x_value, param_y_name, param_y_value)
);

CREATE INDEX IF NOT EXISTS idx_point_grid_id
    ON simulation.sensitivity_point (grid_id);

CREATE INDEX IF NOT EXISTS idx_point_run_id
    ON simulation.sensitivity_point (run_id);

COMMENT ON TABLE simulation.sensitivity_point IS
    '1 cell in sensitivity_grid linking to its rebalance_run. UNIQUE on (grid, position) prevents duplicate cells.';

COMMENT ON COLUMN simulation.sensitivity_point.sharpe_after_cost IS
    'Cached from rebalance_run for fast grid heatmap rendering (avoids N+1 join).';
