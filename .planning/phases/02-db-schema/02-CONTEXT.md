# Phase 2: DB Schema - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Create the four `vdr_agent.*` tables in PostgreSQL: topics, processing_state, document_summaries, and fitment_results. Includes all columns, constraints, partial indexes, and stale-lock recovery column. No application code — pure schema definition via Flyway migrations.

</domain>

<decisions>
## Implementation Decisions

### Migration file structure
- **Separate Flyway file per table** — 4 migration files (V1 through V4), one table each
- Naming: `V1__create_vdr_agent_schema.sql`, `V2__create_topics_table.sql`, `V3__create_processing_state_table.sql`, `V4__create_document_summaries_table.sql`, `V5__create_fitment_results_table.sql`
  - V1 creates the schema (`CREATE SCHEMA IF NOT EXISTS vdr_agent`) and any shared trigger functions
  - One file per table after that
- Each file is idempotent: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`

### Cross-schema FK strategy
- `document_id` columns in `processing_state`, `document_summaries`, and `fitment_results` use **actual FK constraints** referencing `ai_rag.documents(id)`
- `ON DELETE CASCADE` — if a document is deleted from ai_rag, its vdr_agent rows are cleaned up automatically
- `topic_id` in `fitment_results` FK references `vdr_agent.topics(id)` with `ON DELETE CASCADE`

### Document summaries scope
- `document_summaries` stores **one combined final summary per document** — not per-section, not per-topic
- Single `summary_text TEXT` column — the final Claude output after section summaries are collapsed
- Section summaries are ephemeral (computed in memory during generation, not persisted)
- One row per document, enforced by UNIQUE constraint on `document_id`

### Fitment result data model
- `fitment_results` stores **reasoning text only** — no boolean relevant/not-relevant, no score
- Columns: `id`, `document_id` (FK), `topic_id` (FK), `reasoning TEXT`, `status TEXT`, `created_at`, `updated_at`
- UNIQUE constraint on `(document_id, topic_id)` — enables `ON CONFLICT DO UPDATE` for safe re-runs
- `status` enum: `pending | processing | done | failed` (same pattern as processing_state)

### Claude's Discretion
- Whether to create a shared `update_updated_at_column()` trigger function in `vdr_agent` schema or reference the one in `ai_rag` (prefer creating own copy in `vdr_agent` schema to avoid cross-schema dependency)
- Exact column ordering and SQL comment style (follow ingestion-service conventions)
- Whether `processing_state` needs a UNIQUE constraint on `document_id` (yes — one row per document)
- Stale-lock threshold value is app config only, not a DB default

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ingestion-service/migrations/flyway/V1__core_schema_setup.sql`: Creates `update_updated_at_column()` trigger function — copy into `vdr_agent` V1 migration (scoped to vdr_agent schema)
- `ingestion-service/migrations/flyway/V3__documents_and_embeddings.sql`: Idempotent `CREATE TABLE IF NOT EXISTS` + `DO $$ BEGIN ... END $$` pattern for adding missing columns — use same style

### Established Patterns
- **Flyway** migrations in `vdr-agent/migrations/flyway/` (directory exists, currently empty `.gitkeep`)
- **Idempotent SQL**: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `CREATE EXTENSION IF NOT EXISTS`
- **UUIDs**: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()` — matches ai_rag tables
- **Timestamps**: `created_at TIMESTAMPTZ DEFAULT NOW()`, `updated_at TIMESTAMPTZ DEFAULT NOW()` + trigger
- **Status CHECK constraints**: `CHECK (status IN ('pending', 'processing', 'done', 'failed'))` — matches ingestion pattern
- **`DROP TRIGGER IF EXISTS` before `CREATE TRIGGER`** — ensures idempotency of trigger creation

### Integration Points
- `ai_rag.documents(id)` — target of FK constraints from 3 vdr_agent tables
- `vdr_agent.topics(id)` — target of FK constraint from fitment_results (topics table created in V2, referenced in V5)
- Migration files land in `vdr-agent/migrations/flyway/` — Flyway runs this directory on startup

</code_context>

<specifics>
## Specific Ideas

- Document summary is computed once and is independent of topics — it's a general-purpose AI summary of the document content, not scoped to any ESG evaluation
- Fitment reasoning text is what gets displayed to the user — the raw Claude output explaining why a document is or isn't relevant to a topic

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-db-schema*
*Context gathered: 2026-03-05*
