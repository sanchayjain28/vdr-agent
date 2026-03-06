---
phase: 08-topic-crud-api
plan: 01
subsystem: api
tags: [pydantic, fastapi, postgres, flyway, topic, crud]

# Dependency graph
requires:
  - phase: 02-db-schema
    provides: topics table with instruction_text column (V2 migration)
  - phase: 03-db-layer
    provides: TopicDAO with insert/list/update/delete/get_by_id, TopicRecord dataclass, DatabasePool

provides:
  - V6 Flyway migration renaming instruction_text to instruction and adding partial unique index for case-insensitive topic name uniqueness per project
  - Enhanced TopicDAO.list_by_project() with active_only filter parameter
  - TopicDAO.bulk_insert() for atomic multi-topic insertion in one transaction
  - Pydantic v2 models: TopicCreate, TopicUpdate, TopicBulkItem, TopicBulkCreate, TopicResponse
  - TopicResponse.from_record() factory method converting TopicRecord to API response

affects:
  - 08-02-topic-router (consumes all models and DAO methods)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Partial unique index with lower(name) for case-insensitive uniqueness across active topics only
    - Pydantic v2 model_config = {"from_attributes": True} with classmethod factory from_record()
    - DAO bulk_insert uses single DatabasePool.connection() block for all-or-nothing transaction

key-files:
  created:
    - vdr-agent/migrations/flyway/V6__add_topics_unique_name_per_project.sql
    - vdr-agent/app/models/topic.py
  modified:
    - vdr-agent/app/db/dao/topic_dao.py
    - vdr-agent/app/models/__init__.py

key-decisions:
  - "V6 migration renames instruction_text to instruction (aligns DB with DAO/model layer) — canonical fix, no DAO SQL changes needed"
  - "Partial unique index on (project_id, lower(name)) WHERE is_active = TRUE — soft-deleted topics excluded, allowing name reuse after deletion"
  - "bulk_insert uses a single DatabasePool.connection() block — one transaction ensures all-or-nothing; UniqueViolation triggers implicit rollback"
  - "TopicBulkItem defined before TopicBulkCreate in topic.py — required for forward reference resolution even with from __future__ import annotations"

patterns-established:
  - "Pydantic response models use classmethod from_record() to convert DAO dataclasses — avoids coupling router to DB layer"
  - "Field(..., min_length=1) enforces non-empty strings — no separate validator needed in Pydantic v2"

requirements-completed: ["TOPIC-01", "TOPIC-02"]

# Metrics
duration: 7min
completed: 2026-03-05
---

# Phase 8 Plan 01: Topic CRUD API — Data Contracts Summary

**Pydantic v2 request/response models and enhanced TopicDAO with V6 migration fixing instruction_text → instruction column rename and adding partial unique index for case-insensitive topic name uniqueness per project**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-05T08:34:00Z
- **Completed:** 2026-03-05T08:41:10Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- V6 Flyway migration renames `instruction_text` column to `instruction` and creates partial unique index `idx_topics_unique_name_per_project` on `(project_id, lower(name)) WHERE is_active = TRUE`
- Enhanced `TopicDAO.list_by_project()` with `active_only: bool = True` parameter; added `TopicDAO.bulk_insert()` for atomic multi-topic insertion
- Created Pydantic v2 models: `TopicCreate`, `TopicUpdate`, `TopicBulkItem`, `TopicBulkCreate`, `TopicResponse` with `from_record()` factory

## Task Commits

Each task was committed atomically:

1. **Task 1: V6 migration + enhance TopicDAO with active filter and bulk_insert** - `afb318b` (feat)
2. **Task 2: Create Pydantic request/response models in app/models/topic.py** - `af8ea79` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `vdr-agent/migrations/flyway/V6__add_topics_unique_name_per_project.sql` - Renames instruction_text → instruction; adds partial unique index for active topic name uniqueness per project
- `vdr-agent/app/db/dao/topic_dao.py` - Added active_only parameter to list_by_project(); added bulk_insert() method
- `vdr-agent/app/models/topic.py` - All Pydantic v2 topic models (create, update, bulk, response)
- `vdr-agent/app/models/__init__.py` - Exports all topic models

## Decisions Made

- V6 migration renames `instruction_text` to `instruction` — canonical fix so DB aligns with DAO/model layer; no DAO SQL changes needed
- Partial unique index uses `lower(name)` for case-insensitive enforcement; `WHERE is_active = TRUE` excludes soft-deleted topics, allowing name reuse after deletion
- `bulk_insert` wraps all inserts in one `DatabasePool.connection()` context — psycopg's implicit transaction ensures UniqueViolation triggers full rollback

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All Pydantic models ready for 08-02 router consumption
- TopicDAO has all required methods: insert, list_by_project (with active_only), bulk_insert, update, delete, get_by_id
- V6 migration must be applied to the database before 08-02 endpoints can be tested end-to-end

## Self-Check: PASSED

All created files exist on disk and all task commits verified in git history.

---
*Phase: 08-topic-crud-api*
*Completed: 2026-03-05*
