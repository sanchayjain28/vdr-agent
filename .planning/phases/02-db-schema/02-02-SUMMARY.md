---
phase: 02-db-schema
plan: 02
subsystem: database
tags: [postgresql, flyway, sql, migrations, vdr-agent]

# Dependency graph
requires:
  - phase: 02-db-schema/02-01
    provides: vdr_agent schema, topics table (V2), processing_state table (V3), update_updated_at_column() trigger function
provides:
  - vdr_agent.document_summaries table — one combined AI summary per document (V4)
  - vdr_agent.fitment_results table — one fitment evaluation per (document, topic) pair with upsert-safe UNIQUE constraint (V5)
  - vdr-agent/scripts/run_flyway_migration.sh — Flyway CLI runner using VDR_AGENT_DB_* env vars
affects: [03-db-access-layer, 05-poller-dispatcher, 06-summarization-agent, 07-fitment-agent, 08-api-routes]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Flyway versioned migrations with IF NOT EXISTS for idempotency"
    - "DROP TRIGGER IF EXISTS before CREATE TRIGGER to make trigger creation idempotent"
    - "Composite UNIQUE constraint (document_id, topic_id) named for ON CONFLICT DO UPDATE targeting"
    - "CHECK constraint for status enum values instead of PG ENUM type (ALTER-friendly)"
    - "Cross-schema FK references (ai_rag.documents) with ON DELETE CASCADE"
    - "VDR_AGENT_ENV=local pattern for env file hydration without overriding explicit vars"

key-files:
  created:
    - vdr-agent/migrations/flyway/V4__create_document_summaries_table.sql
    - vdr-agent/migrations/flyway/V5__create_fitment_results_table.sql
    - vdr-agent/scripts/run_flyway_migration.sh
  modified: []

key-decisions:
  - "document_summaries has no status column — processing status lives in processing_state.summary_status; document_summaries only holds the completed result"
  - "fitment_results.reasoning is TEXT only — no boolean is_relevant, no numeric score (locked decision from CONTEXT.md)"
  - "fitment_results composite UNIQUE named fitment_results_doc_topic_unique — Phase 7 must use this exact name in ON CONFLICT clause"
  - "Flyway -schemas=vdr_agent scopes flyway_schema_history to vdr_agent schema, independent of ai_rag history"
  - "Flyway -baselineVersion=0 (not 1) so all V1-V5 migrations run on first execution"

patterns-established:
  - "Pattern 1: All migration tables use CREATE TABLE IF NOT EXISTS for idempotency"
  - "Pattern 2: All status columns use TEXT + CHECK constraint, not PG ENUM, for ALTER-friendliness"
  - "Pattern 3: Updated_at triggers use DROP TRIGGER IF EXISTS before CREATE TRIGGER"
  - "Pattern 4: Flyway runner uses load_env_file_preserving_existing() — never overrides explicit env vars"

requirements-completed: [PROC-01, PROC-04]

# Metrics
duration: 2min
completed: 2026-03-05
---

# Phase 2 Plan 02: DB Schema (Part 2) Summary

**V4 document_summaries and V5 fitment_results Flyway migrations plus Flyway CLI runner script — completing the four-table vdr_agent schema**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-05T06:19:39Z
- **Completed:** 2026-03-05T06:21:32Z
- **Tasks:** 3
- **Files modified:** 3 created

## Accomplishments

- Created V4 migration for `vdr_agent.document_summaries` — stores one combined AI summary per document with UNIQUE(document_id) and FK to ai_rag.documents ON DELETE CASCADE
- Created V5 migration for `vdr_agent.fitment_results` — stores one fitment evaluation per (document, topic) pair with composite UNIQUE(document_id, topic_id) enabling Phase 7 upserts via ON CONFLICT DO UPDATE
- Created `vdr-agent/scripts/run_flyway_migration.sh` — Flyway CLI runner mirroring ingestion-service pattern with VDR_AGENT_DB_* env vars, env validation, and -schemas=vdr_agent scoping

## Task Commits

Each task was committed atomically:

1. **Task 1: Write V4 — document_summaries table** - `74f8186` (feat)
2. **Task 2: Write V5 — fitment_results table** - `e6caf31` (feat)
3. **Task 3: Write run_flyway_migration.sh script** - `40bbe69` (feat)

**Plan metadata:** (docs commit to follow)

## Files Created/Modified

- `vdr-agent/migrations/flyway/V4__create_document_summaries_table.sql` - Creates document_summaries table with summary_text TEXT, UNIQUE(document_id), FK to ai_rag.documents ON DELETE CASCADE, index, updated_at trigger
- `vdr-agent/migrations/flyway/V5__create_fitment_results_table.sql` - Creates fitment_results table with reasoning TEXT, status CHECK constraint, composite UNIQUE(document_id, topic_id), FKs to ai_rag.documents and vdr_agent.topics both ON DELETE CASCADE, three indexes, updated_at trigger
- `vdr-agent/scripts/run_flyway_migration.sh` - Flyway CLI runner with VDR_AGENT_DB_* env var validation, load_env_file_preserving_existing(), -schemas=vdr_agent, -baselineOnMigrate=true, -baselineVersion=0

## Decisions Made

- `document_summaries` has no status column — status lives in `processing_state.summary_status`; this table only stores completed results
- `fitment_results.reasoning` is TEXT only (no boolean is_relevant, no numeric score) per locked CONTEXT.md decision
- Composite UNIQUE constraint named `fitment_results_doc_topic_unique` — Phase 7 must use this exact name as the ON CONFLICT target
- `-schemas=vdr_agent` keeps Flyway history independent from ai_rag's flyway_schema_history table
- `-baselineVersion=0` (not 1) ensures all five migrations V1-V5 execute on first run

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all three files created and verified without issues.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All five Flyway migrations V1-V5 exist in `vdr-agent/migrations/flyway/` — schema is complete
- `vdr-agent/scripts/run_flyway_migration.sh` is executable and ready to apply migrations against any PostgreSQL instance with VDR_AGENT_DB_* env vars set
- Phase 3 (DB access layer) can now build DAO classes against the complete schema
- Phase 7 (fitment agent) can use `INSERT ... ON CONFLICT (document_id, topic_id) DO UPDATE` targeting `fitment_results_doc_topic_unique`

---
*Phase: 02-db-schema*
*Completed: 2026-03-05*

## Self-Check: PASSED

- FOUND: vdr-agent/migrations/flyway/V4__create_document_summaries_table.sql
- FOUND: vdr-agent/migrations/flyway/V5__create_fitment_results_table.sql
- FOUND: vdr-agent/scripts/run_flyway_migration.sh
- FOUND: .planning/phases/02-db-schema/02-02-SUMMARY.md
- FOUND: commit 74f8186 (Task 1 — V4 migration)
- FOUND: commit e6caf31 (Task 2 — V5 migration)
- FOUND: commit 40bbe69 (Task 3 — runner script)
