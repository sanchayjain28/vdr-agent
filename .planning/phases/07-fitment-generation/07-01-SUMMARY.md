---
phase: 07-fitment-generation
plan: 01
subsystem: database
tags: [postgres, flyway, migration, psycopg, pydantic-settings, bedrock]

# Dependency graph
requires:
  - phase: 06-ai-summary-generation
    provides: process_document() pipeline that Phase 7 extends with fitment evaluation
  - phase: 03-db-layer
    provides: TopicDAO, DatabasePool, TopicRecord pattern used here
provides:
  - V7 Flyway migration dropping NOT NULL on fitment_results.reasoning
  - TopicDAO.list_active_by_project() static async method for fitment processor
  - Settings.bedrock_embedding_model field (default 'cohere.embed-english-v3')
affects:
  - 07-fitment-generation-02
  - any phase importing TopicDAO or Settings

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Flyway double-underscore naming (V7__...) continuing V6 sequence
    - Dedicated explicit DAO shorthand for processor call sites

key-files:
  created:
    - vdr-agent/migrations/flyway/V7__fitment_results_reasoning_nullable.sql
  modified:
    - vdr-agent/app/db/dao/topic_dao.py
    - vdr-agent/app/config/__init__.py

key-decisions:
  - "fitment_results.reasoning is now nullable — failed-topic upserts write reasoning=NULL with status='failed'"
  - "list_active_by_project() is a dedicated explicit method, NOT a replacement for list_by_project() — coexist intentionally"
  - "bedrock_embedding_model defaults to 'cohere.embed-english-v3'; overridable via VDR_AGENT_BEDROCK_EMBEDDING_MODEL"

patterns-established:
  - "New DAO shorthand methods sit immediately after the generic variant they specialise"

requirements-completed: [PROC-03]

# Metrics
duration: 2min
completed: 2026-03-05
---

# Phase 7 Plan 01: Fitment Generation Prerequisites Summary

**V7 migration drops NOT NULL on fitment_results.reasoning; TopicDAO gains list_active_by_project(); Settings exposes bedrock_embedding_model for Cohere embed calls**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-05T10:08:56Z
- **Completed:** 2026-03-05T10:10:03Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `V7__fitment_results_reasoning_nullable.sql` — removes NOT NULL constraint on `fitment_results.reasoning` so Phase 7 processor can write `status='failed'` rows with `reasoning=NULL` without raising `NotNullViolation`
- Added `TopicDAO.list_active_by_project(project_id)` — static async method with DB-level `WHERE is_active = TRUE` filter; coexists with `list_by_project()` as an explicit processor call-site shorthand
- Added `Settings.bedrock_embedding_model` — defaults to `'cohere.embed-english-v3'`, overridable via `VDR_AGENT_BEDROCK_EMBEDDING_MODEL`, follows existing `VDR_AGENT_` prefix pattern

## Task Commits

Each task was committed atomically:

1. **Task 1: V7 migration — make reasoning nullable** - `b5cd7c3` (feat)
2. **Task 2: TopicDAO.list_active_by_project() + bedrock_embedding_model config** - `3111261` (feat)

## Files Created/Modified

- `vdr-agent/migrations/flyway/V7__fitment_results_reasoning_nullable.sql` - Flyway V7 migration; `ALTER TABLE vdr_agent.fitment_results ALTER COLUMN reasoning DROP NOT NULL`
- `vdr-agent/app/db/dao/topic_dao.py` - Added `list_active_by_project(project_id)` static async method after `list_by_project()`
- `vdr-agent/app/config/__init__.py` - Added `bedrock_embedding_model` field after `bedrock_max_concurrent`

## Decisions Made

- `fitment_results.reasoning` is now nullable — Phase 7 processor upserts failed topics with `reasoning=NULL` and `status='failed'`; the existing V5 `NOT NULL` constraint would have caused `NotNullViolation` on any such upsert
- `list_active_by_project()` deliberately coexists with `list_by_project()` — explicit name improves processor.py readability; the generic variant stays untouched for Topic CRUD API use
- `bedrock_embedding_model` uses same `VDR_AGENT_` prefix as all other Settings fields; no special alias needed

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 07-02 can now safely import `TopicDAO.list_active_by_project()` and `get_settings().bedrock_embedding_model`
- V7 migration must be applied to the database (via Flyway or manual run) before any fitment upsert with `reasoning=NULL` is attempted
- All three prerequisites locked by Plan 07-02's `depends_on` are now satisfied

---
*Phase: 07-fitment-generation*
*Completed: 2026-03-05*

## Self-Check: PASSED

- FOUND: vdr-agent/migrations/flyway/V7__fitment_results_reasoning_nullable.sql
- FOUND: vdr-agent/app/db/dao/topic_dao.py
- FOUND: vdr-agent/app/config/__init__.py
- FOUND: .planning/phases/07-fitment-generation/07-01-SUMMARY.md
- FOUND: commit b5cd7c3 (Task 1)
- FOUND: commit 3111261 (Task 2)
