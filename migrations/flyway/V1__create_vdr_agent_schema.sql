-- Flyway Migration: V1 — Create vdr_agent Schema
-- Creates the vdr_agent schema and the shared updated_at trigger function.
-- The trigger function is intentionally redefined here (not referenced from ai_rag)
-- to avoid a cross-schema function dependency.

CREATE SCHEMA IF NOT EXISTS vdr_agent;

SET search_path TO vdr_agent, public;

-- Auto-update updated_at timestamp on row modification.
-- Scoped to vdr_agent schema — not shared with ai_rag.
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_updated_at_column IS 'Auto-update updated_at timestamp on row modification. Scoped to vdr_agent schema.';
