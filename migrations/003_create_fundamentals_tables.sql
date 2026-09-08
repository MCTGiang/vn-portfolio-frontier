-- ============================================================================
-- Migration 003: fundamentals domain — vn30_constituent + financial_report
-- ============================================================================
-- Scope-driven design (see ADR-009 refactor evaluation):
-- - vn30_constituent: static ticker registry, serves sentiment extraction's
--   ticker-validation needs + supports historical VN30 corpus for defense.
-- - financial_report: minimal time series (revenue, net_income, EPS) for
--   sentiment context enrichment. Derived ratios (PE, PB, ROE) intentionally
--   excluded — computable at query time from prices + fundamentals inputs.
--
-- Two-table shape (metadata vs quarterly time series) is what makes this a
-- genuinely heterogeneous second data source vs prices.daily_ohlcv.
-- ============================================================================

CREATE TABLE IF NOT EXISTS fundamentals.vn30_constituent (
    ticker                  VARCHAR(10)     PRIMARY KEY,
    company_name_vi         VARCHAR(200)    NOT NULL,
    company_name_en         VARCHAR(200),
    sector                  VARCHAR(50)     NOT NULL,
    exchange                VARCHAR(10)     NOT NULL DEFAULT 'HOSE',
    listing_date            DATE,
    added_to_vn30_date      DATE,
    removed_from_vn30_date  DATE,
    is_current              BOOLEAN         NOT NULL DEFAULT true,
    source                  VARCHAR(20)     NOT NULL DEFAULT 'manual',
    ingested_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_current_no_removal
        CHECK (is_current = false OR removed_from_vn30_date IS NULL),

    CONSTRAINT chk_removal_dates_ordered
        CHECK (
            removed_from_vn30_date IS NULL
            OR added_to_vn30_date IS NULL
            OR removed_from_vn30_date >= added_to_vn30_date
        ),

    CONSTRAINT chk_exchange_known
        CHECK (exchange IN ('HOSE', 'HNX', 'UPCOM'))
);

CREATE INDEX IF NOT EXISTS idx_vn30_constituent_sector
    ON fundamentals.vn30_constituent (sector);

CREATE INDEX IF NOT EXISTS idx_vn30_constituent_current
    ON fundamentals.vn30_constituent (is_current)
    WHERE is_current = true;

COMMENT ON TABLE fundamentals.vn30_constituent IS
    'VN30 ticker registry — current constituents + historical ex-members. Used by sentiment extraction for ticker validation and by dashboards for sector grouping.';

COMMENT ON COLUMN fundamentals.vn30_constituent.sector IS
    'Free-text sector label (banking, real_estate, retail, materials, etc.). Not constrained to enable evolution as VN market classification changes.';


CREATE TABLE IF NOT EXISTS fundamentals.financial_report (
    ticker           VARCHAR(10)     NOT NULL,
    period_end       DATE            NOT NULL,
    period_type      VARCHAR(20)     NOT NULL,
    is_audited       BOOLEAN         NOT NULL DEFAULT false,
    revenue_vnd      NUMERIC(20, 0),
    net_income_vnd   NUMERIC(20, 0),
    eps_vnd          NUMERIC(12, 2),
    source           VARCHAR(20)     NOT NULL DEFAULT 'vnstock',
    ingested_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_financial_report
        PRIMARY KEY (ticker, period_end, period_type),

    CONSTRAINT fk_financial_report_ticker
        FOREIGN KEY (ticker)
        REFERENCES fundamentals.vn30_constituent (ticker)
        ON DELETE RESTRICT,

    CONSTRAINT chk_period_type
        CHECK (period_type IN ('quarterly', 'annual')),

    CONSTRAINT chk_source_known
        CHECK (source IN ('vnstock', 'yfinance', 'manual'))
);

-- Recent-reports queries: "VCB's last 4 reports"
CREATE INDEX IF NOT EXISTS idx_financial_report_ticker_date
    ON fundamentals.financial_report (ticker, period_end DESC);

-- Filtered scans: "all audited annual reports"
CREATE INDEX IF NOT EXISTS idx_financial_report_period_type
    ON fundamentals.financial_report (period_type);

COMMENT ON TABLE fundamentals.financial_report IS
    'Minimal financial reports (revenue, net income, EPS) for VN30 tickers. Serves sentiment context enrichment. Ratios computed at query time.';

COMMENT ON COLUMN fundamentals.financial_report.period_type IS
    'Report cadence: quarterly (self-reported) or annual (typically audited).';
