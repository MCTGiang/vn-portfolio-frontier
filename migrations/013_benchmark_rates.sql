-- Migration 013: Benchmark rates for Rf injection (Day 9 Step B, Sprint 11)
--
-- Three tables under new benchmark schema cover all practical Rf references:
--   1. vn_bond_yield: VN Government Bond daily yield by tenor (academic Rf)
--      Source: vnstock Macro().global_macro.bond_yield(market='VN', tenor=X)
--   2. sbv_policy_rate: SBV refinance + discount policy rates (P1 convention)
--      Source: vnstock Macro().currency().policy_rate()
--   3. bank_deposit_rate: VCB + big-4 bank deposit rates per tenor (RETAIL REALISTIC)
--      Source: vnstock Macro().currency().deposit_rate(mode='term')
--
-- Default Rf for P2 Sharpe = VCB 13M deposit (retail opportunity cost).
-- Rationale: retail investor NOT investing in stocks typically parks cash in
-- big-4 bank 12-month term deposit (~5.9% as of Oct 2026), NOT govt bonds
-- (3.69%, institutional-only large lots) nor SBV refi (4.5%, interbank-only).

CREATE SCHEMA IF NOT EXISTS benchmark;

-- Table 1: VN Government Bond yield (academic Rf baseline, Sharpe 1994)
CREATE TABLE IF NOT EXISTS benchmark.vn_bond_yield (
    yield_date DATE NOT NULL,
    tenor VARCHAR(5) NOT NULL,
    yield_open NUMERIC(6,3),
    yield_high NUMERIC(6,3),
    yield_low NUMERIC(6,3),
    yield_close NUMERIC(6,3) NOT NULL,
    source TEXT NOT NULL DEFAULT 'vnstock_global_macro',
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (yield_date, tenor),
    CONSTRAINT chk_tenor_known CHECK (tenor IN ('1Y','2Y','3Y','5Y','10Y')),
    CONSTRAINT chk_yield_sane CHECK (yield_close >= 0 AND yield_close <= 50)
);

CREATE INDEX IF NOT EXISTS idx_vn_bond_yield_date ON benchmark.vn_bond_yield(yield_date);
CREATE INDEX IF NOT EXISTS idx_vn_bond_yield_tenor ON benchmark.vn_bond_yield(tenor, yield_date);

-- Table 2: SBV policy rates (P1 convention + sensitivity analysis)
CREATE TABLE IF NOT EXISTS benchmark.sbv_policy_rate (
    rate_date DATE PRIMARY KEY,
    refinance_pct NUMERIC(6,3) NOT NULL,
    discount_pct NUMERIC(6,3),
    source TEXT NOT NULL DEFAULT 'vnstock_currency',
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_refinance_sane CHECK (refinance_pct >= 0 AND refinance_pct <= 50)
);

CREATE INDEX IF NOT EXISTS idx_sbv_policy_rate_date ON benchmark.sbv_policy_rate(rate_date);

-- Table 3: Bank deposit rates per bank per tenor (DEFAULT P2 Rf source)
CREATE TABLE IF NOT EXISTS benchmark.bank_deposit_rate (
    rate_date DATE NOT NULL,
    bank_code VARCHAR(10) NOT NULL,
    bank_name TEXT,
    interest_1m NUMERIC(6,3),
    interest_3m NUMERIC(6,3),
    interest_6m NUMERIC(6,3),
    interest_13m NUMERIC(6,3),
    interest_36m NUMERIC(6,3),
    source TEXT NOT NULL DEFAULT 'vnstock_currency',
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (rate_date, bank_code),
    CONSTRAINT chk_deposit_rates_sane CHECK (
        (interest_13m IS NULL OR (interest_13m >= 0 AND interest_13m <= 50))
    )
);

CREATE INDEX IF NOT EXISTS idx_bank_deposit_rate_date ON benchmark.bank_deposit_rate(rate_date);
CREATE INDEX IF NOT EXISTS idx_bank_deposit_rate_bank ON benchmark.bank_deposit_rate(bank_code, rate_date);

COMMENT ON SCHEMA benchmark IS 'Reference benchmark series for Rf injection and comparative analysis';
COMMENT ON TABLE benchmark.vn_bond_yield IS 'VN Government Bond daily yield by tenor (academic Rf baseline Sharpe 1994)';
COMMENT ON TABLE benchmark.sbv_policy_rate IS 'SBV refinance + discount policy rates (P1 convention, interbank reference)';
COMMENT ON TABLE benchmark.bank_deposit_rate IS 'Big-4 bank deposit rates per tenor (DEFAULT P2 Rf source = VCB interest_13m, retail opportunity cost)';
