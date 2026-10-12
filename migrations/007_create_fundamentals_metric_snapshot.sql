-- 007_create_fundamentals_metric_snapshot.sql
-- Task 5B (Sprint 10): Fundamentals bronze layer + curated views
-- Depends on: 003 (fundamentals schema), 006 (vn30_membership tables)
-- Per ADR-014: long-form storage for extensibility; sector-aware views on top

BEGIN;

-- 1. Drop deprecated financial_report (Migration 003 created but never populated;
--    replaced by long-form metric_snapshot + wide-form view below)
DROP TABLE IF EXISTS fundamentals.financial_report CASCADE;

-- 2. Bronze layer: raw long-form storage
CREATE TABLE fundamentals.metric_snapshot (
    ticker VARCHAR(10) NOT NULL,
    period VARCHAR(10) NOT NULL,          -- '2026-Q2', '2018-Q1'
    statement_type VARCHAR(20) NOT NULL,  -- 'income', 'ratio', 'cash_flow'
    metric_id VARCHAR(100) NOT NULL,      -- 'IS_NET_INTEREST_INCOME', 'RT_VALUE_PE'
    metric_name TEXT NOT NULL,            -- Vietnamese name from vnstock_data
    metric_order SMALLINT,
    metric_level SMALLINT,
    unit VARCHAR(20),                     -- 'VND', '%', 'ratio', 'billion VND'
    value NUMERIC(28, 6),                 -- large enough for billion-VND values
    source VARCHAR(20) NOT NULL DEFAULT 'vnstock_data',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, period, statement_type, metric_id),
    CONSTRAINT chk_statement_type CHECK (
        statement_type IN ('income', 'ratio', 'cash_flow', 'balance', 'health')
    )
);

CREATE INDEX idx_metric_snapshot_ticker_period
    ON fundamentals.metric_snapshot(ticker, period);
CREATE INDEX idx_metric_snapshot_metric_id
    ON fundamentals.metric_snapshot(metric_id);
CREATE INDEX idx_metric_snapshot_ticker_stmt
    ON fundamentals.metric_snapshot(ticker, statement_type);

COMMENT ON TABLE fundamentals.metric_snapshot IS
    'Bronze layer: raw long-form storage for vnstock_data statement types. Source of truth. Curated views built on top per ADR-014.';

-- 3. Silver layer: universal key ratios (wide-form, applies bank + non-bank)
CREATE VIEW fundamentals.key_ratios AS
SELECT
    ticker,
    period,
    MAX(CASE WHEN metric_id = 'RT_VALUE_PE' THEN value END)              AS pe_ratio,
    MAX(CASE WHEN metric_id = 'RT_VALUE_PB' THEN value END)              AS pb_ratio,
    MAX(CASE WHEN metric_id = 'RT_VALUE_PS' THEN value END)              AS ps_ratio,
    MAX(CASE WHEN metric_id = 'RT_PRT_ROE' THEN value END)               AS roe_pct,
    MAX(CASE WHEN metric_id = 'RT_PRT_ROA' THEN value END)               AS roa_pct,
    MAX(CASE WHEN metric_id = 'RT_VALUE_EPS' THEN value END)             AS eps_vnd,
    MAX(CASE WHEN metric_id = 'RT_VALUE_BVPS' THEN value END)            AS bvps_vnd,
    MAX(CASE WHEN metric_id = 'RT_VALUE_MARKET_CAP' THEN value END)      AS market_cap_bnvnd,
    MAX(CASE WHEN metric_id = 'RT_VALUE_BETA' THEN value END)            AS beta,
    MAX(CASE WHEN metric_id = 'RT_VALUE_DIVIDEND_YIELD' THEN value END)  AS dividend_yield_pct,
    MAX(CASE WHEN metric_id = 'RT_LEV_DE' THEN value END)                AS debt_to_equity
FROM fundamentals.metric_snapshot
WHERE statement_type = 'ratio'
GROUP BY ticker, period;

COMMENT ON VIEW fundamentals.key_ratios IS
    'Silver layer: universal valuation + profitability ratios. Used by Feature 2 hybrid rebalancing (P/E, P/B filters) and P3 ML feature engineering.';

-- 4. Silver layer: income statement wide-form (bank/non-bank aware)
CREATE VIEW fundamentals.financial_report AS
SELECT
    ticker,
    period,
    -- Bank-specific columns (NULL for non-bank tickers)
    MAX(CASE WHEN metric_id = 'IS_NET_INTEREST_INCOME' THEN value END)          AS bank_nii_vnd,
    MAX(CASE WHEN metric_id = 'IS_NET_FEE_AND_COMMISSION_INCOME' THEN value END) AS bank_net_fee_income_vnd,
    -- Universal columns
    MAX(CASE WHEN metric_id = 'IS_TOTAL_OPERATING_INCOME' THEN value END)       AS operating_income_vnd,
    MAX(CASE WHEN metric_id = 'IS_OPERATING_EXPENSES' THEN value END)           AS operating_expenses_vnd,
    MAX(CASE WHEN metric_id = 'IS_PROFIT_BEFORE_TAX' THEN value END)            AS profit_before_tax_vnd,
    MAX(CASE WHEN metric_id = 'IS_NET_PROFIT_AFTER_TAX' THEN value END)         AS net_profit_after_tax_vnd,
    MAX(CASE WHEN metric_id = 'IS_BASIC_EARNINGS_PER_SHARE' THEN value END)     AS basic_eps_vnd,
    MAX(CASE WHEN metric_id = 'IS_DILUTED_EARNINGS_PER_SHARE' THEN value END)   AS diluted_eps_vnd
FROM fundamentals.metric_snapshot
WHERE statement_type = 'income'
GROUP BY ticker, period;

COMMENT ON VIEW fundamentals.financial_report IS
    'Silver layer: income statement key metrics. Bank tickers populate bank_* cols; non-bank fields may need additional non-bank IDs after Task 5B execute + verify.';

COMMIT;
