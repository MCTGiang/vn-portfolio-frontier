-- ============================================================================
-- Migration 004: news_sentiment domain — article + extracted_signal
-- ============================================================================
-- Core schema for Feature 3 (structured sentiment extraction) per ADR-006:
-- outputs {ticker, event_type, sentiment_score, entities} — NOT return
-- prediction claims.
--
-- Design:
-- - article stores raw scraped news; UNIQUE(url) prevents duplicate ingestion.
-- - extracted_signal stores per-(ticker, event_type) signals; ticker is NOT
--   FK-constrained to vn30_constituent so news mentioning non-VN30 tickers
--   is preserved for downstream filtering.
-- - entities as JSONB (per Q3 decision) with GIN index for containment queries.
-- - extractor_version enables A/B comparison between model releases
--   (e.g. phobert-ft-v1 vs rag-gpt4-v1).
-- ============================================================================

CREATE TABLE IF NOT EXISTS news_sentiment.article (
    article_id      BIGSERIAL       PRIMARY KEY,
    source          VARCHAR(30)     NOT NULL,
    url             TEXT            NOT NULL,
    published_at    TIMESTAMPTZ     NOT NULL,
    title           TEXT            NOT NULL,
    body            TEXT,
    language        VARCHAR(10)     NOT NULL DEFAULT 'vi',
    scraped_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_article_url UNIQUE (url),

    CONSTRAINT chk_source_known
        CHECK (source IN ('vnexpress', 'cafef', 'vietstock', 'manual'))
);

-- Recent-news queries dominate — index accordingly.
CREATE INDEX IF NOT EXISTS idx_article_published_at
    ON news_sentiment.article (published_at DESC);

-- Per-source analysis (source volume, source quality).
CREATE INDEX IF NOT EXISTS idx_article_source
    ON news_sentiment.article (source);

COMMENT ON TABLE news_sentiment.article IS
    'Scraped Vietnamese financial news articles from VnExpress, CafeF, VietStock. UNIQUE(url) prevents duplicate ingestion; scrapers can UPSERT on conflict.';

COMMENT ON COLUMN news_sentiment.article.language IS
    'ISO 639-1 code. Default vi for Vietnamese; en reserved for future English coverage.';


CREATE TABLE IF NOT EXISTS news_sentiment.extracted_signal (
    signal_id             BIGSERIAL      PRIMARY KEY,
    article_id            BIGINT         NOT NULL,
    ticker                VARCHAR(10)    NOT NULL,
    event_type            VARCHAR(50)    NOT NULL,
    sentiment_score       NUMERIC(5, 4),
    sentiment_confidence  NUMERIC(5, 4),
    entities              JSONB,
    extractor_version     VARCHAR(50)    NOT NULL,
    extracted_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_signal_article
        FOREIGN KEY (article_id)
        REFERENCES news_sentiment.article (article_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_sentiment_score_range
        CHECK (sentiment_score IS NULL OR sentiment_score BETWEEN -1 AND 1),

    CONSTRAINT chk_sentiment_confidence_range
        CHECK (sentiment_confidence IS NULL OR sentiment_confidence BETWEEN 0 AND 1),

    CONSTRAINT uq_signal_dedupe
        UNIQUE (article_id, ticker, event_type, extractor_version)
);

-- Per-ticker signal history.
CREATE INDEX IF NOT EXISTS idx_signal_ticker
    ON news_sentiment.extracted_signal (ticker);

-- Recent signals for a ticker.
CREATE INDEX IF NOT EXISTS idx_signal_ticker_date
    ON news_sentiment.extracted_signal (ticker, extracted_at DESC);

-- Event-type filtered scans.
CREATE INDEX IF NOT EXISTS idx_signal_event_type
    ON news_sentiment.extracted_signal (event_type);

-- A/B comparison between extractor versions.
CREATE INDEX IF NOT EXISTS idx_signal_extractor_version
    ON news_sentiment.extracted_signal (extractor_version);

-- GIN index enables containment queries on entities JSONB:
--   WHERE entities @> '[{"type": "company", "name": "VCB"}]'
CREATE INDEX IF NOT EXISTS idx_signal_entities_gin
    ON news_sentiment.extracted_signal USING GIN (entities);

COMMENT ON TABLE news_sentiment.extracted_signal IS
    'Structured signals extracted from articles (per ADR-006 positioning). One row per (article, ticker, event_type, extractor_version) tuple.';

COMMENT ON COLUMN news_sentiment.extracted_signal.entities IS
    'Extracted entities as JSONB array: [{"type": "company"|"person"|"institution", "name": "...", "role": "..."}]. GIN-indexed for containment queries.';

COMMENT ON COLUMN news_sentiment.extracted_signal.extractor_version IS
    'Model identifier for reproducibility and A/B comparison. Format: <model>-<variant>-v<version>. Examples: phobert-ft-v1, rag-gpt4-v1, manual-v1 (human-labeled ground truth).';
