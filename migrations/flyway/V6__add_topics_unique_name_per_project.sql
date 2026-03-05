-- Flyway Migration: V6 — Rename instruction_text → instruction, unique topic name per project
-- 1. Renames column instruction_text to instruction (aligns DB with DAO/model layer).
-- 2. Enforces that no two active topics in the same project share a name.
-- Soft-deleted topics (is_active = false) are excluded — allows re-creating a deleted topic name.

SET search_path TO vdr_agent, public;

-- Step 1: Rename column to match DAO and Pydantic models
ALTER TABLE topics RENAME COLUMN instruction_text TO instruction;

-- Step 2: Partial unique index for case-insensitive name uniqueness
CREATE UNIQUE INDEX IF NOT EXISTS idx_topics_unique_name_per_project
    ON topics (project_id, lower(name))
    WHERE is_active = TRUE;
