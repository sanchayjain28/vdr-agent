-- Flyway Migration: V5 — Fitment Results Table
-- Stores one fitment evaluation per (document, topic) pair.
-- The UNIQUE constraint on (document_id, topic_id) enables:
--   INSERT ... ON CONFLICT (document_id, topic_id) DO UPDATE SET ...
-- in Phase 7 — making fitment generation safe to re-run without creating duplicates.

SET search_path TO vdr_agent, public;

CREATE TABLE IF NOT EXISTS fitment_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    topic_id UUID NOT NULL REFERENCES vdr_agent.topics(id) ON DELETE CASCADE,
    reasoning TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_fitment_status CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    CONSTRAINT fitment_results_doc_topic_unique UNIQUE (document_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_fitment_results_document_id ON fitment_results(document_id);
CREATE INDEX IF NOT EXISTS idx_fitment_results_topic_id ON fitment_results(topic_id);
CREATE INDEX IF NOT EXISTS idx_fitment_results_status ON fitment_results(status);

DROP TRIGGER IF EXISTS update_fitment_results_updated_at ON fitment_results;
CREATE TRIGGER update_fitment_results_updated_at
    BEFORE UPDATE ON fitment_results
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE fitment_results IS 'AI fitment evaluation results — one row per (document, topic) pair';
COMMENT ON COLUMN fitment_results.document_id IS 'FK to ai_rag.documents — cascades delete when source document is removed';
COMMENT ON COLUMN fitment_results.topic_id IS 'FK to vdr_agent.topics — cascades delete when topic is removed';
COMMENT ON COLUMN fitment_results.reasoning IS 'Raw Claude output explaining why the document is or is not relevant to the topic';
COMMENT ON COLUMN fitment_results.status IS 'Evaluation status: pending, processing, done, or failed';
COMMENT ON CONSTRAINT fitment_results_doc_topic_unique ON fitment_results IS 'Enables INSERT ... ON CONFLICT (document_id, topic_id) DO UPDATE for safe re-runs without duplicates';
