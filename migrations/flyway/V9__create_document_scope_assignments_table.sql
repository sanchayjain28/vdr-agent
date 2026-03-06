-- Flyway Migration: V9 — Document Scope Assignments Table
-- Stores one scope classification per (document, topic) pair produced by the LLM categorisation pipeline.
-- The UNIQUE constraint on (document_id, topic_id) enables:
--   INSERT ... ON CONFLICT (document_id, topic_id) DO UPDATE SET ...
-- in Phase 13 — making categorisation safe to re-run without creating duplicates.
-- No scope_type column — all assignments are equal; no primary/secondary distinction.

SET search_path TO vdr_agent, public;

CREATE TABLE IF NOT EXISTS document_scope_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    topic_id UUID NOT NULL REFERENCES vdr_agent.topics(id) ON DELETE CASCADE,
    confidence TEXT NOT NULL,
    justification TEXT,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    review_reason TEXT,
    raw_response JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_confidence CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
    CONSTRAINT doc_scope_assignments_doc_topic_unique UNIQUE (document_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_doc_scope_assignments_document_id ON document_scope_assignments(document_id);
CREATE INDEX IF NOT EXISTS idx_doc_scope_assignments_topic_id ON document_scope_assignments(topic_id);

DROP TRIGGER IF EXISTS update_document_scope_assignments_updated_at ON document_scope_assignments;
CREATE TRIGGER update_document_scope_assignments_updated_at
    BEFORE UPDATE ON document_scope_assignments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE document_scope_assignments IS 'LLM scope classification results — one row per (document, topic) pair; no scope_type distinction';
COMMENT ON COLUMN document_scope_assignments.document_id IS 'UUID reference to ai_rag.documents — no cross-schema FK (managed at application level)';
COMMENT ON COLUMN document_scope_assignments.topic_id IS 'FK to vdr_agent.topics — cascades delete when topic is removed';
COMMENT ON COLUMN document_scope_assignments.confidence IS 'LLM confidence level for this assignment: HIGH, MEDIUM, or LOW';
COMMENT ON COLUMN document_scope_assignments.justification IS 'LLM explanation of why this document was assigned to this topic';
COMMENT ON COLUMN document_scope_assignments.needs_review IS 'Flag set when confidence is LOW or LLM signals uncertainty — triggers human review workflow';
COMMENT ON COLUMN document_scope_assignments.review_reason IS 'Optional explanation of why this assignment was flagged for review';
COMMENT ON COLUMN document_scope_assignments.raw_response IS 'Full LLM JSON response for this document — stored for audit trail and debugging';
COMMENT ON CONSTRAINT doc_scope_assignments_doc_topic_unique ON document_scope_assignments IS 'Enables INSERT ... ON CONFLICT (document_id, topic_id) DO UPDATE for safe re-classification without duplicates';
