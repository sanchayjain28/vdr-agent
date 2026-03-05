-- Flyway Migration: V4 — Document Summaries Table
-- Stores one combined AI summary per document.
-- Section summaries are computed in memory during generation and are NOT persisted here.
-- This table contains only the final Claude output after section summaries are collapsed.

SET search_path TO vdr_agent, public;

CREATE TABLE IF NOT EXISTS document_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES ai_rag.documents(id) ON DELETE CASCADE,
    summary_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT document_summaries_document_id_unique UNIQUE (document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_summaries_document_id ON document_summaries(document_id);

DROP TRIGGER IF EXISTS update_document_summaries_updated_at ON document_summaries;
CREATE TRIGGER update_document_summaries_updated_at
    BEFORE UPDATE ON document_summaries
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE document_summaries IS 'One combined AI summary per document — final output after collapsing section summaries';
COMMENT ON COLUMN document_summaries.document_id IS 'FK to ai_rag.documents — cascades delete when source document is removed';
COMMENT ON COLUMN document_summaries.summary_text IS 'Final Claude-generated summary of the full document content (not scoped to any topic). Section summaries are ephemeral — not stored here.';
