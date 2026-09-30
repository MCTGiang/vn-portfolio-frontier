-- Migration 008: relax vn30_constituent name columns NOT NULL constraints
-- Rationale: vnstock_data Company.overview() does not provide canonical company
-- names. Names deferred to Sprint 11 enrichment task (HOSE ticker directory
-- or vnstock Listing() API).

BEGIN;

ALTER TABLE fundamentals.vn30_constituent
    ALTER COLUMN company_name_vi DROP NOT NULL,
    ALTER COLUMN company_name_en DROP NOT NULL;

COMMIT;
