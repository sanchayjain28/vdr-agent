---
phase: 02-db-schema
plan: 01
subsystem: database
tags: [postgres, flyway, sql, migrations, vdr_agent, schema]

# Dependency graph
requires:
  - phase: 01-service-scaffold
    provides: vdr-agent directory structure and migrations/flyway directory

provides:
  - vdr_agent schema in PostgreSQL
  - update_updated_at_column() trigger function scoped to vdr_agent schema
  - vdr_agent.topics table with project_id (plain UUID, no FK), ESG topic columns, two indexes, and updated_at trigger
  - vdr_agent.processing_state table with ai_rag.documents FK, CHECK constraint, UNIQUE(document_id), partial index for FOR UPDATE SKIP LOCKED polling
affects:
  - 02-02 (document_summaries and fitment_results tables depend on vdr_agent schema from V1)
  - 05-poller (FOR UPDATE SKIP LOCKED poll query must use WHERE summary_status IN ('pending', 'failed') to use partial index)
  - 07-topic-management (API routes query topics table)
  - 08-api-routes (project_id FK to user-service schema deferred to this phase)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Flyway migration files: V{N}__description.sql naming with SET search_path TO vdr_agent, public"
    - "Idempotent SQL: CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS, CREATE SCHEMA IF NOT EXISTS"
    - "Trigger idempotency: DROP TRIGGER IF EXISTS before CREATE TRIGGER (not CREATE OR REPLACE TRIGGER)"
    - "Cross-schema FK: REFERENCES ai_rag.documents(id) ON DELETE CASCADE"
    - "Partial index for polling: WHERE summary_status IN ('pending', 'failed') — must be reproduced exactly in Phase 5 poll queries"
    - "Own trigger function copy in vdr_agent schema — avoids cross-schema function dependency on ai_rag"

key-files:
  created:
    - vdr-agent/migrations/flyway/V1__create_vdr_agent_schema.sql
    - vdr-agent/migrations/flyway/V2__create_topics_table.sql
    - vdr-agent/migrations/flyway/V3__create_processing_state_table.sql
  modified: []

key-decisions:
  - "project_id in topics is a plain UUID with no FK — FK to user-service deferred to Phase 8 (correct target table unconfirmed)"
  - "update_updated_at_column() trigger function redefined in vdr_agent schema — not referenced from ai_rag to avoid cross-schema function dependency"
  - "Partial index idx_processing_state_pending_failed covers only pending/failed rows — Phase 5 poll query MUST use WHERE summary_status IN ('pending', 'failed') to hit this index"
  - "processing_started_at is nullable (no NOT NULL) — NULL until worker claims row, used by poller to detect stale locks"
  - "UNIQUE(document_id) inline in CREATE TABLE definition — DO block not needed since CREATE TABLE IF NOT EXISTS handles idempotency"

patterns-established:
  - "Flyway naming: V{N}__create_{table}_table.sql — one file per table after V1 schema setup"
  - "SET search_path TO vdr_agent, public at top of every migration file"
  - "DROP TRIGGER IF EXISTS + CREATE TRIGGER pattern for idempotency"

requirements-completed: [PROC-01, PROC-04]

# Metrics
duration: 2min
completed: 2026-03-05
---

# Phase 2 Plan 01: DB Schema — V1/V2/V3 Migrations Summary

**Three idempotent Flyway SQL migrations establishing vdr_agent schema, ESG topics table, and processing_state table with partial index for FOR UPDATE SKIP LOCKED polling**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-05T06:19:36Z
- **Completed:** 2026-03-05T06:20:52Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- V1 creates the vdr_agent schema and defines update_updated_at_column() trigger function scoped to vdr_agent (no cross-schema function dependency)
- V2 creates vdr_agent.topics with project_id as plain UUID (FK deferred to Phase 8), two indexes (one partial for active topics), and updated_at trigger
- V3 creates vdr_agent.processing_state with cross-schema FK to ai_rag.documents ON DELETE CASCADE, nullable processing_started_at, CHECK constraint on summary_status, UNIQUE(document_id), and partial index idx_processing_state_pending_failed that Phase 5 FOR UPDATE SKIP LOCKED polling depends on

## Task Commits

Each task was committed atomically:

1. **Task 1: Write V1 — schema and trigger function** - `0cf42fe` (feat)
2. **Task 2: Write V2 — topics table** - `c200043` (feat)
3. **Task 3: Write V3 — processing_state table with partial index** - `6b66539` (feat)

## Files Created/Modified
- `vdr-agent/migrations/flyway/V1__create_vdr_agent_schema.sql` - Creates vdr_agent schema and update_updated_at_column() trigger function
- `vdr-agent/migrations/flyway/V2__create_topics_table.sql` - ESG topics table with project_id (plain UUID), indexes, and updated_at trigger
- `vdr-agent/migrations/flyway/V3__create_processing_state_table.sql` - Processing state table with cross-schema FK, partial index, and CHECK constraint

## Decisions Made
- project_id in topics is intentionally a plain UUID with no FK constraint — the correct target table (user-service vs ai_rag) is unconfirmed until Phase 8; FK will be added then
- update_updated_at_column() trigger function is redefined in vdr_agent schema rather than referenced from ai_rag, avoiding a cross-schema function dependency
- Partial index idx_processing_state_pending_failed uses WHERE summary_status IN ('pending', 'failed') — Phase 5 poll query must reproduce this clause exactly for the planner to use the index
- processing_started_at is nullable (no NOT NULL constraint) — it is NULL until a worker claims the row, per RESEARCH.md anti-patterns guidance

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- V1, V2, V3 migrations ready for Flyway execution against the PostgreSQL database
- Phase 02-02 can now create V4 (document_summaries) and V5 (fitment_results) tables — both reference the vdr_agent schema established in V1 and the topics table from V2
- Phase 05 poller must use WHERE summary_status IN ('pending', 'failed') in its poll query to leverage the partial index from V3
- Cross-schema FK to ai_rag.documents requires VDR_AGENT_DB_USER to have REFERENCES privilege on ai_rag.documents (verify during first Flyway run)

---
*Phase: 02-db-schema*
*Completed: 2026-03-05*
