-- ============================================================================
-- Migration 002: prices.daily_ohlcv table
-- ============================================================================
-- VN30 daily OHLCV time series.
--
-- Grain:   1 row per (ticker, trade_date).
-- Volume:  29 tickers x ~1400 trading days (Project 1 window)  ~= 40K rows.
-- Query:   Time-range slicing per ticker is the dominant read pattern —
--          hence the composite PK and separate index on trade_date.
--
-- See docs/architecture.md ADR-009 for design rationale.
-- ============================================================================

CREATE TABLE IF NOT EXISTS prices.daily_ohlcv (
    ticker         VARCHAR(10)     NOT NULL,
    trade_date     DATE            NOT NULL,
    open_price     NUMERIC(12, 2),
    high_price     NUMERIC(12, 2),
    low_price      NUMERIC(12, 2),
    close_price    NUMERIC(12, 2)  NOT NULL,
    volume         BIGINT,
    source         VARCHAR(20)     NOT NULL DEFAULT 'vnstock',
    ingested_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_daily_ohlcv PRIMARY KEY (ticker, trade_date),

    CONSTRAINT chk_volume_nonneg
        CHECK (volume IS NULL OR volume >= 0),

    CONSTRAINT chk_source_known
        CHECK (source IN ('vnstock', 'yfinance', 'sqlite_project1'))
);

-- Time-range queries ("prices for VCB in 2026") are common — index accordingly.
CREATE INDEX IF NOT EXISTS idx_daily_ohlcv_date
    ON prices.daily_ohlcv (trade_date);

-- Provenance audit queries during migration ("which rows came from Project 1 SQLite?").
CREATE INDEX IF NOT EXISTS idx_daily_ohlcv_source
    ON prices.daily_ohlcv (source);

COMMENT ON TABLE prices.daily_ohlcv IS
    'VN30 daily OHLCV. Populated in Task 5 via hybrid strategy: bootstrap from Project 1 SQLite, then fresh vnstock fetch for delta.';

COMMENT ON COLUMN prices.daily_ohlcv.source IS
    'Data provenance: vnstock (primary Task 5 fresh fetch), yfinance (fallback), sqlite_project1 (bootstrap migration from Project 1).';
