---
phase: 03-db-layer
plan: "03"
subsystem: database
tags: [postgres, psycopg3, asyncio, select-for-update, skip-locked, dao]

# Dependency graph
requires:
  - phase: 03-db-layer/03-01
    provides: DatabasePool with async connection() context manager
  - phase: 03-db-layer/03-02
    provides: ProcessingStateRecord dataclass with from_row() factory
  - phase: 02-db-schema
    provides: vdr_agent.processing_state table with partial index idx_processing_state_pending_failed
provides:
  - ProcessingStateDAO with atomic claim_documents(), update_status(), reset_stale_claims(), get_by_document(), insert()
affects: [04-db-layer, 05-polling-loop, 06-bedrock-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SELECT FOR UPDATE SKIP LOCKED + batched UPDATE in single transaction for atomic claim"
    - "Short separate transactions for post-Bedrock status updates (no connection held during slow I/O)"
    - "INTERVAL '%s minutes' parameterization for stale claim detection"
    - "INSERT ... ON CONFLICT DO NOTHING with fallback get_by_document() for idempotent inserts"

key-files:
  created:
    - vdr-agent/app/db/dao/processing_state_dao.py
  modified: []

key-decisions:
  - "claim_documents() does SELECT and UPDATE in one DatabasePool.connection() block — atomicity guarantee cannot be split"
  - "WHERE id = ANY(%s) with list of UUIDs for batched UPDATE — psycopg3 handles list-to-array cast automatically"
  - "reset_stale_claims() uses INTERVAL '%s minutes' with parameterized threshold — never f-string interpolation"

patterns-established:
  - "Atomic claim pattern: SELECT FOR UPDATE SKIP LOCKED then UPDATE in same transaction, return only (id, document_id) tuples"
  - "Status update pattern: separate short transaction called after slow I/O (Bedrock) completes"

requirements-completed: []

# Metrics
duration: 1min
completed: 2026-03-05
---

# Phase 3 Plan 03: ProcessingStateDAO Summary

**ProcessingStateDAO with SELECT FOR UPDATE SKIP LOCKED atomic claim pattern preventing duplicate Bedrock calls across concurrent vdr-agent workers**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-05T06:58:04Z
- **Completed:** 2026-03-05T06:59:05Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Atomic claim_documents() using SELECT FOR UPDATE SKIP LOCKED + batched UPDATE in single transaction
- update_status() as short separate transaction (no connection held during Bedrock calls)
- reset_stale_claims() to recover stale processing rows with parameterized threshold
- get_by_document() lookup returning ProcessingStateRecord or None
- insert() with ON CONFLICT DO NOTHING for idempotent document registration

## Task Commits

Each task was committed atomically:

1. **Task 1: ProcessingStateDAO implementation** - `0ca335f` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `vdr-agent/app/db/dao/processing_state_dao.py` - ProcessingStateDAO with five static async methods; critical claim_documents() uses FOR UPDATE SKIP LOCKED

## Decisions Made
- `claim_documents()` SELECT and UPDATE share one `DatabasePool.connection()` block — splitting into two separate connections would break the atomicity guarantee
- `WHERE id = ANY(%s)` with a Python list for batched UPDATE — psycopg3 automatically casts list to PostgreSQL array
- `INTERVAL '%s minutes'` in reset_stale_claims() keeps threshold parameterized rather than using f-string interpolation (SQL injection safety)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- ProcessingStateDAO complete; Phase 5 polling loop can now call claim_documents() to atomically acquire documents for processing
- All four DAOs required by Phase 5 are now available (TopicDAO from 03-02, ProcessingStateDAO from this plan)
- Phase 4 (DocumentSummaryDAO and FitmentResultDAO) still needed before Phase 5 can write results back

---
*Phase: 03-db-layer*
*Completed: 2026-03-05*

## Self-Check: PASSED
- vdr-agent/app/db/dao/processing_state_dao.py: FOUND
- .planning/phases/03-db-layer/03-03-SUMMARY.md: FOUND
- Task commit 0ca335f: FOUND
