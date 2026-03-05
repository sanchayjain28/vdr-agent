-- Flyway Migration: V8 — Remove cross-schema FK from processing_state
-- V3 originally had a FK to ai_rag.documents; V8 tried to redirect it to
-- ai_rag.documents. Both cross-schema FKs are fragile across independent
-- services, so the constraint is dropped entirely. document_id is a plain
-- UUID with referential integrity enforced at the application level.

SET search_path TO vdr_agent, public;

ALTER TABLE processing_state
    DROP CONSTRAINT IF EXISTS processing_state_document_id_fkey;
