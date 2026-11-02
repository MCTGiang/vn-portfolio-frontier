-- migrations/015_predictions.sql
-- =============================================================
-- Live prediction tracking schema (ADR-019)
-- Author: Mai Cong Tra Giang (Ginny)
-- Date: 02/11/2026
-- Purpose: Capture daily predictions + evaluate actuals for
--          6-month live tracking before thesis defense (Jun 2027).
--          Target: N >= 125 trading observations (p<0.05).
-- =============================================================

BEGIN;

-- -----------------------------------------------------------
-- Pre-requisites
-- -----------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

CREATE SCHEMA IF NOT EXISTS predictions
    AUTHORIZATION CURRENT_USER;

COMMENT ON SCHEMA predictions IS
    'Live prediction tracking + evaluation per ADR-019. '
    'Populated by scripts/log_daily_prediction.py via Task Scheduler 16:30 Mon-Fri.';


-- -----------------------------------------------------------
-- Table 1: predictions.daily_prediction
-- -----------------------------------------------------------
CREATE TABLE predictions.daily_prediction (
    prediction_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Khi nao du doan (trading day sau 16:30)
    prediction_date    DATE NOT NULL,

    -- Nguon du doan (ADR-019 taxonomy)
    prediction_source  VARCHAR(32) NOT NULL,

    -- Ticker du doan
    ticker             VARCHAR(16) NOT NULL,

    -- F1 output: ty trong trong portfolio (0.0 - 1.0)
    -- NULL neu signal-based (BUY/SELL/HOLD) tu news
    weight_recommended NUMERIC(6, 5),

    -- F2/News output: BUY / SELL / HOLD / N_A
    action             VARCHAR(8) NOT NULL DEFAULT 'N_A',

    -- Horizon du doan (trading days)
    horizon_days       INTEGER NOT NULL DEFAULT 1,

    -- Confidence 0.0 - 1.0
    confidence         NUMERIC(4, 3),

    -- Gia tai thoi diem du doan (close hom do)
    price_at_prediction NUMERIC(12, 2),

    -- Ly do (free text, co the chua JSON)
    rationale          TEXT,

    -- Version mo hinh de ablation study
    model_version      VARCHAR(32) NOT NULL,

    -- Audit lineage
    sprint_tag         VARCHAR(16),

    created_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Metadata linh hoat (n_articles, events, etc.)
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Constraints
    CONSTRAINT chk_dp_source CHECK (prediction_source IN (
        'f1_optimizer_minvar',
        'f1_optimizer_maxsharpe',
        'f1_optimizer_riskparity',
        'f2_rebalance_signal',
        'claude_news_summary',
        'manual_override'
    )),
    CONSTRAINT chk_dp_action CHECK (action IN ('BUY', 'SELL', 'HOLD', 'N_A')),
    CONSTRAINT chk_dp_horizon CHECK (horizon_days BETWEEN 1 AND 252),
    CONSTRAINT chk_dp_weight CHECK (
        weight_recommended IS NULL
        OR (weight_recommended >= 0 AND weight_recommended <= 1)
    ),
    CONSTRAINT chk_dp_confidence CHECK (
        confidence IS NULL
        OR (confidence >= 0 AND confidence <= 1)
    ),

    -- Idempotency: cho phep re-run script khong duplicate
    CONSTRAINT uq_dp_signature UNIQUE (
        prediction_date, prediction_source, ticker, horizon_days, model_version
    )
);

CREATE INDEX idx_dp_date         ON predictions.daily_prediction(prediction_date);
CREATE INDEX idx_dp_ticker       ON predictions.daily_prediction(ticker);
CREATE INDEX idx_dp_source       ON predictions.daily_prediction(prediction_source);
CREATE INDEX idx_dp_source_date  ON predictions.daily_prediction(prediction_source, prediction_date);
CREATE INDEX idx_dp_metadata_gin ON predictions.daily_prediction USING GIN (metadata);

COMMENT ON TABLE predictions.daily_prediction IS
    'One row per prediction (source x ticker x horizon x model_version per day). '
    'Populated by log_daily_prediction.py at 16:30 after HOSE close.';


-- -----------------------------------------------------------
-- Table 2: predictions.daily_actual
-- -----------------------------------------------------------
CREATE TABLE predictions.daily_actual (
    actual_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- FK den prediction
    prediction_id      UUID NOT NULL
        REFERENCES predictions.daily_prediction(prediction_id)
        ON DELETE CASCADE,

    -- Ngay evaluate (= prediction_date + horizon_days trading days)
    evaluation_date    DATE NOT NULL,

    -- Gia tai evaluation_date
    price_at_evaluation NUMERIC(12, 2) NOT NULL,

    -- Return thuc te (simple return)
    return_actual      NUMERIC(10, 6),

    -- Du doan dung huong?
    -- TRUE khi (BUY & return > 0) hoac (SELL & return < 0) hoac (HOLD & |return| < 0.5%)
    -- NULL khi action = N_A (F1 weights khong co directional claim)
    directional_match  BOOLEAN,

    -- Benchmark return (VNIndex cung period) de tinh alpha
    benchmark_return   NUMERIC(10, 6),

    -- Alpha = return_actual - benchmark_return
    alpha              NUMERIC(10, 6),

    computed_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 1 prediction chi evaluate 1 lan
    CONSTRAINT uq_da_prediction UNIQUE (prediction_id)
);

CREATE INDEX idx_da_prediction    ON predictions.daily_actual(prediction_id);
CREATE INDEX idx_da_eval_date     ON predictions.daily_actual(evaluation_date);
CREATE INDEX idx_da_directional   ON predictions.daily_actual(directional_match)
    WHERE directional_match IS NOT NULL;

COMMENT ON TABLE predictions.daily_actual IS
    'One row per matured prediction with ground truth. '
    'Populated when prediction_date + horizon_days <= today.';


-- -----------------------------------------------------------
-- Materialized View: rolling evaluation metrics
-- -----------------------------------------------------------
CREATE MATERIALIZED VIEW predictions.evaluation_rolling AS
SELECT
    dp.prediction_source,
    dp.model_version,
    dp.horizon_days,
    DATE_TRUNC('week', dp.prediction_date)::DATE AS week_starting,
    COUNT(*)                                       AS n_predictions,
    AVG(CASE WHEN da.directional_match THEN 1.0
             WHEN da.directional_match IS FALSE THEN 0.0
             ELSE NULL END)                        AS mda,
    AVG(da.alpha)                                  AS mean_alpha,
    STDDEV(da.alpha)                               AS stddev_alpha,
    STDDEV(da.alpha) / NULLIF(SQRT(COUNT(*)), 0)   AS alpha_standard_error,
    CORR(dp.weight_recommended, da.return_actual)  AS ic_pearson,
    AVG(da.return_actual)                          AS mean_return,
    AVG(da.benchmark_return)                       AS mean_benchmark_return
FROM predictions.daily_prediction dp
INNER JOIN predictions.daily_actual da
    ON dp.prediction_id = da.prediction_id
GROUP BY
    dp.prediction_source,
    dp.model_version,
    dp.horizon_days,
    week_starting;

CREATE UNIQUE INDEX idx_er_pk
    ON predictions.evaluation_rolling(
        prediction_source, model_version, horizon_days, week_starting
    );

COMMENT ON MATERIALIZED VIEW predictions.evaluation_rolling IS
    'Weekly MDA, IC, Alpha, Standard Error per (source, model, horizon). '
    'REFRESH MATERIALIZED VIEW CONCURRENTLY sau moi batch update actuals.';


-- -----------------------------------------------------------

COMMIT;

-- =============================================================
-- Verification queries (run after migration)
-- =============================================================
-- SELECT COUNT(*) FROM predictions.daily_prediction;      -- expect 0
-- SELECT COUNT(*) FROM predictions.daily_actual;          -- expect 0
-- SELECT * FROM predictions.evaluation_rolling;           -- expect 0 rows
-- \d predictions.daily_prediction                         -- verify constraints
