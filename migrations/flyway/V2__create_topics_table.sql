-- Flyway Migration: V2 — Topics Table
-- ESG evaluation topics. One project has many topics.
-- project_id is a plain UUID (no FK) — the correct target table (user-service vs ai_rag)
-- is unconfirmed until Phase 8; FK will be added then.

SET search_path TO vdr_agent, public;

CREATE TABLE IF NOT EXISTS topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL,
    name TEXT NOT NULL,
    instruction_text TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_topics_project_id ON topics(project_id);
CREATE INDEX IF NOT EXISTS idx_topics_project_active ON topics(project_id, is_active) WHERE is_active = TRUE;

DROP TRIGGER IF EXISTS update_topics_updated_at ON topics;
CREATE TRIGGER update_topics_updated_at
    BEFORE UPDATE ON topics
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMENT ON TABLE topics IS 'ESG evaluation topics — each topic has a name and instruction for fitment evaluation';
COMMENT ON COLUMN topics.project_id IS 'UUID of the project this topic belongs to — no FK constraint until user-service schema confirmed (Phase 8 concern)';
COMMENT ON COLUMN topics.instruction_text IS 'Instruction text passed to Claude for fitment evaluation against this topic';
COMMENT ON COLUMN topics.is_active IS 'Controls whether this topic participates in fitment evaluations';
