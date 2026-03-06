-- Flyway Migration: V10 — Add categorisation_status to processing_state
-- Extends the existing processing_state table with a categorisation lifecycle column.
-- This column tracks LLM scope classification state per document, separate from summary_status.
-- Uncategorised documents (where no topic matched) are detected via this column,
-- NOT via sentinel rows in document_scope_assignments.

SET search_path TO vdr_agent, public;

ALTER TABLE processing_state
    ADD COLUMN categorisation_status TEXT NOT NULL DEFAULT 'pending';

ALTER TABLE processing_state
    ADD CONSTRAINT valid_categorisation_status
        CHECK (categorisation_status IN ('pending', 'processing', 'done', 'uncategorised', 'failed'));

-- Partial index for Phase 13 categorisation poll query.
-- Only pending and failed rows are ever polled; done and uncategorised rows are excluded
-- from the index to keep it small and fast.
-- Phase 13 MUST query WHERE categorisation_status IN ('pending', 'failed') to use this index.
CREATE INDEX IF NOT EXISTS idx_processing_state_cat_pending
    ON processing_state(categorisation_status, created_at)
    WHERE categorisation_status IN ('pending', 'failed');

COMMENT ON COLUMN processing_state.categorisation_status IS 'Scope categorisation status: pending (awaiting), processing (running LLM), done (assigned), uncategorised (no scope matched), failed (error)';
COMMENT ON INDEX idx_processing_state_cat_pending IS 'Partial index for FOR UPDATE SKIP LOCKED categorisation poll query — only covers pending and failed rows';
