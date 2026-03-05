-- Flyway Migration: V3 — Processing State Table
-- Tracks per-document AI processing status. One row per document (UNIQUE constraint).
-- The partial index below is the exact index the Phase 5 FOR UPDATE SKIP LOCKED
-- poll query will use — the WHERE clause must match the poll query precisely.

SET search_path TO vdr_agent, public;

CREATE TABLE IF NOT EXISTS processing_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    summary_status TEXT NOT NULL DEFAULT 'pending',
    processing_started_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_summary_status CHECK (summary_status IN ('pending', 'processing', 'done', 'failed')),
    CONSTRAINT processing_state_document_id_unique UNIQUE (document_id)
);

-- Partial index for Phase 5 poll query.
-- Only pending and failed rows are ever polled; done rows are the vast majority
-- and are excluded from the index to keep it small and fast.
-- Phase 5 MUST query WHERE summary_status IN ('pending', 'failed') to use this index.
CREATE INDEX IF NOT EXISTS idx_processing_state_pending_failed
    ON processing_state(summary_status, created_at)
    WHERE summary_status IN ('pending', 'failed');

DROP TRIGGER IF EXISTS update_processing_state_updated_at ON processing_state;
CREATE TRIGGER update_processing_state_updated_at
    BEFORE UPDATE ON processing_state
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE processing_state IS 'Per-document AI processing status — one row per document';
COMMENT ON COLUMN processing_state.document_id IS 'UUID reference to the source document — no cross-schema FK (managed at application level)';
COMMENT ON COLUMN processing_state.summary_status IS 'Pipeline status: pending (awaiting pickup), processing (claimed by worker), done (summary generated), failed (error occurred)';
COMMENT ON COLUMN processing_state.processing_started_at IS 'Set when a worker claims this row (status → processing). Used by poller to detect stale locks. NULL when status is pending/done/failed.';
COMMENT ON COLUMN processing_state.error_message IS 'Last error message if summary_status = failed';
COMMENT ON INDEX idx_processing_state_pending_failed IS 'Partial index for FOR UPDATE SKIP LOCKED poll query — only covers pending and failed rows';
