-- ============================================================================
-- Migration 005: simulation domain — rebalance_run
-- ============================================================================
-- Persistent storage for Feature 2 (Auto-rebalancing simulator) runs per
-- ADR-012 (user-parameterized cost, cost-agnostic framework).
--
-- Every row = one scenario:
--   input (cost params + strategy + target universe + backtest window)
--   + output (Sharpe before/after cost, turnover, n_rebalances)
--   + reproducibility (git SHA + code version at run time).
--
-- Design:
-- - schema `simulation` created here (not in 001) so this migration stays
--   self-contained; existing schemas prices/fundamentals/news_sentiment
--   remain untouched.
-- - strategy_params + target_weights as JSONB for flexible strategy types
--   (periodic vs threshold_band vs hybrid) — see ADR-012 for locked API.
-- - CHECK constraints enforce ADR-012 validation rules at DB level:
--     * brokerage_pct in [0, 1.0]  (unit trap — reject 15 = "meant 15 bps")
--       (double defense: NUMERIC(5,4) type also caps at 9.9999)
--     * tax_pct default 0.10 (Thông tư 111/2013/TT-BTC)
--     * market_impact_bps non-negative
--     * strategy_name in known set (extend when new strategy added)
--     * backtest_end >= backtest_start
-- - Indexes support: strategy filter, brokerage sensitivity curves,
--   recency queries, and git SHA lookup for defense-time reproducibility.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS simulation;


CREATE TABLE IF NOT EXISTS simulation.rebalance_run (
    run_id              BIGSERIAL       PRIMARY KEY,
    run_timestamp       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Input: cost parameters (per ADR-012)
    brokerage_pct       NUMERIC(5, 4)   NOT NULL,
    tax_pct             NUMERIC(5, 4)   NOT NULL DEFAULT 0.10,
    market_impact_bps   SMALLINT        NOT NULL DEFAULT 10,

    -- Input: strategy
    strategy_name       VARCHAR(30)     NOT NULL,
    strategy_params     JSONB           NOT NULL,

    -- Input: target universe + backtest window
    target_weights      JSONB           NOT NULL,
    backtest_start      DATE            NOT NULL,
    backtest_end        DATE            NOT NULL,

    -- Output: performance metrics
    sharpe_before_cost  NUMERIC(6, 4),
    sharpe_after_cost   NUMERIC(6, 4),
    total_cost_bps      SMALLINT,
    turnover_avg_pct    NUMERIC(5, 2),
    n_rebalances        INTEGER,

    -- Reproducibility (locked at run time)
    git_commit_sha      VARCHAR(40)     NOT NULL,
    code_version        VARCHAR(20)     NOT NULL,

    CONSTRAINT chk_brokerage_pct_range
        CHECK (brokerage_pct BETWEEN 0 AND 1.0),

    CONSTRAINT chk_tax_pct_range
        CHECK (tax_pct BETWEEN 0 AND 1.0),

    CONSTRAINT chk_market_impact_bps_nonneg
        CHECK (market_impact_bps >= 0),

    CONSTRAINT chk_strategy_name_known
        CHECK (strategy_name IN ('periodic', 'threshold_band', 'hybrid')),

    CONSTRAINT chk_backtest_dates
        CHECK (backtest_end >= backtest_start)
);


-- Per-strategy grouping (Sharpe comparison across strategies).
CREATE INDEX IF NOT EXISTS idx_run_strategy
    ON simulation.rebalance_run (strategy_name);

-- Sensitivity curve queries: WHERE brokerage_pct BETWEEN X AND Y.
CREATE INDEX IF NOT EXISTS idx_run_brokerage
    ON simulation.rebalance_run (brokerage_pct);

-- Recent-runs queries dominate the UI (last N runs).
CREATE INDEX IF NOT EXISTS idx_run_timestamp
    ON simulation.rebalance_run (run_timestamp DESC);

-- Reproducibility lookup: "what runs came from commit XYZ?"
CREATE INDEX IF NOT EXISTS idx_run_git_sha
    ON simulation.rebalance_run (git_commit_sha);


COMMENT ON TABLE simulation.rebalance_run IS
    'Persistent record of Feature 2 rebalancing simulator runs. Every row = one scenario. Enables reproducibility and sensitivity analysis (ADR-012).';

COMMENT ON COLUMN simulation.rebalance_run.brokerage_pct IS
    'User-input broker fee % (0.15 = 0.15%). Framework cost-agnostic per ADR-012 — no broker-specific presets.';

COMMENT ON COLUMN simulation.rebalance_run.tax_pct IS
    'Vietnam seller tax rate. Default 0.10% per Thông tư 111/2013/TT-BTC. Overridable for fund exemptions.';

COMMENT ON COLUMN simulation.rebalance_run.market_impact_bps IS
    'Market impact assumption in basis points. Default 10 for VN30 liquid; override for small-cap.';

COMMENT ON COLUMN simulation.rebalance_run.strategy_params IS
    'Strategy-specific parameters as JSONB. Examples: {"period_days": 90} for periodic; {"band_pct": 5.0} for threshold_band.';

COMMENT ON COLUMN simulation.rebalance_run.target_weights IS
    'Target portfolio weights as JSONB. Format: {"TICKER": weight_fraction}. Example: {"VCB": 0.15, "VNM": 0.12}.';

COMMENT ON COLUMN simulation.rebalance_run.git_commit_sha IS
    'Git commit SHA at time of run — enables reproducibility. Populated by application code, not defaulted.';
