---
phase: 08-topic-crud-api
plan: "02"
subsystem: api

tags: [fastapi, psycopg, pydantic, rest-api, crud]

requires:
  - phase: 08-01
    provides: TopicDAO static methods (insert, list_by_project, update, bulk_insert), Pydantic models (TopicCreate, TopicUpdate, TopicBulkCreate, TopicBulkItem, TopicResponse), V6 migration with unique index on (project_id, name)

provides:
  - FastAPI APIRouter with 5 topic endpoints mounted at /topics in the vdr-agent app
  - POST /topics — create one topic, returns 201 TopicResponse
  - GET /topics?project_id=X — list active topics (include_inactive=true for all)
  - POST /topics/bulk — atomic multi-topic create, returns 201 array
  - PATCH /topics/{topic_id} — partial update with 409/404 handling
  - DELETE /topics/{topic_id} — soft-delete via is_active=False, returns 204

affects:
  - 10-vdr-frontend (consumes these endpoints to replace 19 hardcoded ESG scope names)

tech-stack:
  added: [httpx (installed for FastAPI TestClient verification)]
  patterns:
    - APIRouter with prefix="/topics" — no double-slash; empty string "" for root POST/GET
    - /bulk route registered before /{topic_id} to prevent path parameter collision
    - UniqueViolation caught directly around DAO call (minimal exception scope), raised as 409 HTTPException
    - Soft-delete via TopicDAO.update(is_active=False) — never calls TopicDAO.delete()
    - 204 No Content returned as Response(status_code=204) not a dict

key-files:
  created:
    - vdr-agent/app/core/routers/topics.py
  modified:
    - vdr-agent/app/core/routers/__init__.py
    - vdr-agent/main.py

key-decisions:
  - "/bulk route must precede /{topic_id} in APIRouter definition — FastAPI matches top-to-bottom; /bulk as string would otherwise match as UUID param and fail"
  - "Soft-delete uses TopicDAO.update(is_active=False), not TopicDAO.delete() — preserves fitment results"
  - "UniqueViolation catch scope is minimal (wraps only the DAO call) — keeps error handling precise"

patterns-established:
  - "Empty string '' not '/' for APIRouter root POST/GET to avoid double-slash with prefix"
  - "Response(status_code=204) for no-body responses — Pydantic model not used"

requirements-completed: ["TOPIC-01", "TOPIC-02", "TOPIC-03", "TOPIC-04"]

duration: 2min
completed: 2026-03-05
---

# Phase 8 Plan 02: Topic CRUD API Router Summary

**Five FastAPI REST endpoints for ESG topic CRUD wired into vdr-agent app: create, list, bulk-create, update, soft-delete with 409/404 error handling**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-05T08:43:14Z
- **Completed:** 2026-03-05T08:45:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `vdr-agent/app/core/routers/topics.py` with all 5 endpoints ordered correctly (/bulk before /{topic_id})
- Wired `topics_router` into `routers/__init__.py` and `main.py` alongside the existing health router
- UniqueViolation from psycopg caught at the DAO call boundary and converted to 409 Conflict; 404 returned for missing topic IDs

## Task Commits

Each task was committed atomically:

1. **Task 1: Create topic CRUD router with all endpoints and error handling** - `39ba49e` (feat)
2. **Task 2: Wire topics router into routers/__init__.py and main.py** - `c98665d` (feat)

**Plan metadata:** (docs commit — created after summary)

## Files Created/Modified

- `vdr-agent/app/core/routers/topics.py` - Topic APIRouter with 5 endpoints: POST /topics, GET /topics, POST /topics/bulk, PATCH /topics/{topic_id}, DELETE /topics/{topic_id}
- `vdr-agent/app/core/routers/__init__.py` - Exports health_router and topics_router
- `vdr-agent/main.py` - Imports and includes topics_router in create_app()

## Decisions Made

- `/bulk` route defined before `/{topic_id}` in file order — FastAPI routes are matched top-to-bottom; without this ordering, a request to `/topics/bulk` would match `topic_id="bulk"` and fail UUID parsing
- Soft-delete implemented as `TopicDAO.update(topic_id, is_active=False)` not `TopicDAO.delete()` — preserves all associated fitment results in the database
- `UniqueViolation` exception scope is minimal (wraps only the DAO call) — precise error attribution

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing httpx dependency for TestClient**
- **Found during:** Task 1 verification
- **Issue:** `fastapi.testclient.TestClient` requires `httpx` which was not installed in the .venv
- **Fix:** Ran `pip install httpx` — installed httpx 0.28.1 with httpcore and certifi
- **Files modified:** .venv (not committed)
- **Verification:** TestClient imports successfully; 409 conflict path tested end-to-end
- **Committed in:** Part of Task 1 verification flow (httpx not tracked in requirements.txt — deviation within venv only)

---

**Total deviations:** 1 auto-fixed (1 blocking — missing test dependency)
**Impact on plan:** Auto-fix necessary for verification only. No scope changes to production code.

## Issues Encountered

None — the plan router code executed exactly as specified. Only the test infrastructure needed the httpx install.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All four TOPIC requirements (TOPIC-01 through TOPIC-04) are complete
- Phase 8 is now fully done — vdr-agent exposes topic CRUD endpoints at /vdr-agent/topics
- Phase 10 (vdr-frontend) can now replace the 19 hardcoded ESG scope names by calling these endpoints

---
*Phase: 08-topic-crud-api*
*Completed: 2026-03-05*
