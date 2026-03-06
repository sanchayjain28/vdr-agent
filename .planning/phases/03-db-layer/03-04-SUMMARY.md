---
phase: 03-db-layer
plan: "04"
subsystem: database
tags: [psycopg3, asyncpg, dao, upsert, postgresql, python]

requires:
  - phase: 03-01
    provides: DatabasePool with async context manager for short-lived connections
  - phase: 03-02
    provides: DocumentSummaryRecord and FitmentResultRecord dataclasses with from_row() factories
  - phase: 02-02
    provides: vdr_agent.document_summaries and vdr_agent.fitment_results schema with named UNIQUE constraints

provides:
  - DocumentSummaryDAO with upsert() using ON CONFLICT (document_id) DO UPDATE and get_by_document()
  - FitmentResultDAO with upsert() using ON CONFLICT ON CONSTRAINT fitment_results_doc_topic_unique DO UPDATE, list_by_document(), and get_by_document_and_topic()

affects: [phase-6-ai-summary, phase-7-fitment, phase-9-results-api]

tech-stack:
  added: []
  patterns:
    - Short connection scope — open pool connection, execute, commit, release; never hold across Bedrock calls
    - ON CONFLICT DO UPDATE for idempotent upserts — safe for re-runs without manual deduplication
    - ON CONFLICT ON CONSTRAINT <name> required for named constraints (not column-list form)
    - Python None maps to SQL NULL natively in psycopg3 — no explicit null coercion needed

key-files:
  created:
    - vdr-agent/app/db/dao/document_summary_dao.py
    - vdr-agent/app/db/dao/fitment_result_dao.py
  modified: []

key-decisions:
  - "DocumentSummaryDAO.upsert() uses ON CONFLICT (document_id) DO UPDATE — inline UNIQUE on document_id from V4 migration; no named constraint needed here"
  - "FitmentResultDAO.upsert() uses ON CONFLICT ON CONSTRAINT fitment_results_doc_topic_unique — exact constraint name from V5 migration is mandatory; column-list form must not be used"
  - "Both DAOs commit inside the DatabasePool.connection() block before returning — no connection held during any Bedrock call"
  - "FitmentResultDAO.upsert() status defaults to 'done' — callers pass 'failed' explicitly on Bedrock error; reasoning stored as NULL on failure"

patterns-established:
  - "DAO pattern: all methods static async, one DatabasePool.connection() block per method, commit before exiting block"
  - "Upsert pattern: RETURNING clause on INSERT...ON CONFLICT DO UPDATE to get back the final row as a record dataclass"

requirements-completed: []

duration: 3min
completed: 2026-03-05
---

# Phase 3 Plan 4: DocumentSummaryDAO and FitmentResultDAO Summary

**Two async DAOs for upsert-safe writes to document_summaries and fitment_results — short connection scope guarantees no pool starvation during Bedrock calls**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-05T06:58:12Z
- **Completed:** 2026-03-05T07:01:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- DocumentSummaryDAO with idempotent upsert via `ON CONFLICT (document_id) DO UPDATE` and a `get_by_document()` reader
- FitmentResultDAO with upsert via the exact named constraint `ON CONFLICT ON CONSTRAINT fitment_results_doc_topic_unique DO UPDATE`, `list_by_document()` for Phase 9 results API, and `get_by_document_and_topic()` for single-record lookup
- Both DAOs commit and release the connection within a single `async with DatabasePool.connection()` block — no long-held connections

## Task Commits

Each task was committed atomically:

1. **Task 1: DocumentSummaryDAO** - `dc2d741` (feat)
2. **Task 2: FitmentResultDAO** - `0bc6227` (feat)

**Plan metadata:** (docs commit — see final commit)

## Files Created/Modified
- `vdr-agent/app/db/dao/document_summary_dao.py` — DocumentSummaryDAO with upsert and get_by_document
- `vdr-agent/app/db/dao/fitment_result_dao.py` — FitmentResultDAO with upsert, list_by_document, get_by_document_and_topic

## Decisions Made
- `ON CONFLICT (document_id) DO UPDATE` used in DocumentSummaryDAO because document_summaries has an inline `UNIQUE(document_id)` — no named constraint needed
- `ON CONFLICT ON CONSTRAINT fitment_results_doc_topic_unique` used in FitmentResultDAO — this is the exact constraint name from V5 migration; using column-list form would fail at runtime if the column-list does not match a single named constraint
- Both DAOs commit inside the connection block before returning — caller does not need to manage transactions

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 6 (AI Summary Generation) can call `DocumentSummaryDAO.upsert()` immediately after Bedrock returns
- Phase 7 (Fitment Generation) can call `FitmentResultDAO.upsert()` per topic after each Bedrock result
- Phase 9 (Results API) can call `FitmentResultDAO.list_by_document()` to return fitment data to the frontend
- All DAOs follow identical short-connection pattern — no pool starvation risk

---
*Phase: 03-db-layer*
*Completed: 2026-03-05*
