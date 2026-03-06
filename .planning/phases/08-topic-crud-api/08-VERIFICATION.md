---
phase: 08-topic-crud-api
verified: 2026-03-05T09:00:00Z
status: passed
score: 14/14 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "POST /topics via HTTP client returns 201 with full topic JSON body"
    expected: "Response body contains id, project_id, name, instruction, is_active, created_at, updated_at"
    why_human: "Requires live DB connection — cannot assert response body shape without running DB"
  - test: "POST /topics/bulk with a duplicate name returns 409 before any rows are inserted"
    expected: "No topics created, 409 body mentions duplicate name, DB row count unchanged"
    why_human: "All-or-nothing transactional rollback can only be confirmed against a live DB"
  - test: "DELETE /topics/{id} returns 204 and GET /topics still lists the topic when include_inactive=true"
    expected: "Topic row is_active=false; 204 response has empty body; excluded from default list"
    why_human: "Soft-delete behavior requires live DB to confirm row update rather than row deletion"
---

# Phase 8: Topic CRUD API Verification Report

**Phase Goal:** ESG topics can be created, listed, updated, and deleted via REST endpoints — enabling the frontend to replace its 19 hardcoded scope names with project-specific topics
**Verified:** 2026-03-05T09:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

The following truths are derived from the must_haves in the two PLAN files and from the phase goal itself.

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Creating two topics with the same name in the same project returns 409 Conflict | VERIFIED | `topics.py` lines 33-37 catch `UniqueViolation` and raise `HTTP_409_CONFLICT` |
| 2 | POST /topics/bulk is all-or-nothing: if any topic name duplicates, no topics are created | VERIFIED | `bulk_insert` wraps all INSERTs in one `DatabasePool.connection()` block — UniqueViolation triggers implicit rollback; router catches at lines 63-67 and returns 409 |
| 3 | TopicDAO.list_by_project() can filter by is_active status | VERIFIED | `topic_dao.py` lines 43-66 — `active_only: bool = True` parameter appends `AND is_active = TRUE` when True |
| 4 | TopicDAO.bulk_insert() inserts multiple topics in a single transaction and returns all created records | VERIFIED | `topic_dao.py` lines 69-97 — single `async with DatabasePool.connection()` block, returns `List[TopicRecord]` |
| 5 | Pydantic request models validate name (1-100 chars) and instruction (1-5000 chars) as non-empty | VERIFIED | `topic.py` lines 16-17: `Field(..., min_length=1, max_length=100)` and `Field(..., min_length=1, max_length=5000)`; confirmed by live Python validation run |
| 6 | Pydantic response model serialises TopicRecord with all fields including id, project_id, is_active, timestamps | VERIFIED | `TopicResponse` lines 41-65 — all 7 fields; `from_record()` classmethod at line 54 maps every field from `TopicRecord` |
| 7 | POST /topics creates a topic with name and instruction, returns 201 with full topic object | VERIFIED | Router line 24: `status_code=status.HTTP_201_CREATED, response_model=TopicResponse`; endpoint calls `TopicDAO.insert()` and wraps result in `TopicResponse.from_record()` |
| 8 | GET /topics?project_id=<uuid> returns active topics for a project as a JSON array | VERIFIED | Router lines 41-51: `list_topics()` calls `TopicDAO.list_by_project(active_only=not include_inactive)`; default `include_inactive=False` means `active_only=True` |
| 9 | GET /topics?project_id=<uuid>&include_inactive=true returns all topics including soft-deleted | VERIFIED | Router line 44: `include_inactive: bool = Query(False)` — when True, passes `active_only=False` to DAO |
| 10 | PATCH /topics/{id} updates name and/or instruction, returns 200 with updated topic | VERIFIED | Router lines 71-92: calls `TopicDAO.update()`, catches `UniqueViolation` as 409, returns `None`-guarded 404, otherwise `TopicResponse.from_record(record)` |
| 11 | DELETE /topics/{id} soft-deletes (sets is_active=false), returns 204 No Content | VERIFIED | Router lines 95-101: calls `TopicDAO.update(topic_id=topic_id, is_active=False)` — NOT `TopicDAO.delete()` — returns `Response(status_code=204)` |
| 12 | POST /topics/bulk creates multiple topics atomically, returns 201 with array of created topics | VERIFIED | Router lines 54-68: `status_code=201`, `response_model=List[TopicResponse]`, calls `TopicDAO.bulk_insert()` |
| 13 | Non-existent topic ID on PATCH/DELETE returns 404 Not Found | VERIFIED | PATCH line 90-91: `if record is None: raise HTTPException(404)`; DELETE line 99-100: same guard |
| 14 | /bulk route is registered before /{topic_id} to prevent path parameter collision | VERIFIED | Runtime check confirms: bulk at index 2, `{topic_id}` at index 3 in router route list |

**Score:** 14/14 truths verified

---

## Required Artifacts

### Plan 08-01 Artifacts

| Artifact | Expected | Exists | Substantive | Wired | Status |
|----------|----------|--------|-------------|-------|--------|
| `vdr-agent/migrations/flyway/V6__add_topics_unique_name_per_project.sql` | Partial unique index on (project_id, lower(name)) WHERE is_active = TRUE; column rename | Yes | Yes (14 lines, ALTER TABLE + CREATE UNIQUE INDEX) | N/A (migration file) | VERIFIED |
| `vdr-agent/app/db/dao/topic_dao.py` | Enhanced TopicDAO with active filter on list and bulk_insert method | Yes | Yes (167 lines, all 6 methods fully implemented) | Yes — imported by `topics.py` line 11 | VERIFIED |
| `vdr-agent/app/models/topic.py` | Pydantic request/response models for topic endpoints | Yes | Yes (66 lines, 5 models with full field definitions and from_record()) | Yes — imported by `topics.py` lines 12-17 and `models/__init__.py` | VERIFIED |

### Plan 08-02 Artifacts

| Artifact | Expected | Exists | Substantive | Wired | Status |
|----------|----------|--------|-------------|-------|--------|
| `vdr-agent/app/core/routers/topics.py` | Topic CRUD router with 5 endpoints | Yes | Yes (102 lines, 5 real endpoints with full error handling) | Yes — imported by `routers/__init__.py` and included in `main.py` | VERIFIED |
| `vdr-agent/app/core/routers/__init__.py` | Exports both health_router and topics_router | Yes | Yes (4 lines, both routers exported in `__all__`) | Yes — imported by `main.py` line 12 | VERIFIED |
| `vdr-agent/main.py` | FastAPI app with topics_router included | Yes | Yes — `app.include_router(topics_router)` at line 60, confirmed by runtime route listing | Yes — `topics_router` imported and registered | VERIFIED |

---

## Key Link Verification

| From | To | Via | Status | Evidence |
|------|----|-----|--------|----------|
| `vdr-agent/app/models/topic.py` | `vdr-agent/app/db/records.py` | `TopicResponse.from_record()` converts TopicRecord to API response | VERIFIED | `topic.py` line 9: `from app.db.records import TopicRecord`; `from_record()` classmethod at lines 54-65 maps every field |
| `vdr-agent/app/db/dao/topic_dao.py` | `vdr-agent/migrations/flyway/V6__add_topics_unique_name_per_project.sql` | bulk_insert relies on unique constraint for conflict detection | VERIFIED | V6 migration creates `idx_topics_unique_name_per_project`; DAO raises UniqueViolation which the router converts to 409 |
| `vdr-agent/app/core/routers/topics.py` | `vdr-agent/app/db/dao/topic_dao.py` | Direct static method calls (TopicDAO.insert, list_by_project, update, bulk_insert) | VERIFIED | `topics.py` line 11: `from app.db.dao.topic_dao import TopicDAO`; 4 DAO methods called across 5 endpoints |
| `vdr-agent/app/core/routers/topics.py` | `vdr-agent/app/models/topic.py` | Request body parsing and response serialisation | VERIFIED | `topics.py` lines 12-17 import all 4 model classes; `TopicResponse.from_record()` called in every endpoint that returns a topic |
| `vdr-agent/main.py` | `vdr-agent/app/core/routers/topics.py` | `app.include_router(topics_router)` | VERIFIED | `main.py` line 12: `from app.core.routers import health_router, topics_router`; line 60: `app.include_router(topics_router)`; runtime confirmed all 5 endpoints present |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| TOPIC-01 | 08-01, 08-02 | User can create a topic for a project with a name and instruction text | SATISFIED | `POST /topics` endpoint in `topics.py` line 25; `TopicDAO.insert()` called; returns 201 |
| TOPIC-02 | 08-01, 08-02 | User can list all topics for a project | SATISFIED | `GET /topics?project_id=<uuid>` endpoint in `topics.py` line 42; `TopicDAO.list_by_project()` with `active_only` filter |
| TOPIC-03 | 08-02 | User can update a topic's name and instruction text | SATISFIED | `PATCH /topics/{topic_id}` endpoint in `topics.py` line 72; `TopicDAO.update()` with optional fields; 409/404 error handling |
| TOPIC-04 | 08-02 | User can delete a topic from a project | SATISFIED | `DELETE /topics/{topic_id}` endpoint in `topics.py` line 96; soft-delete via `TopicDAO.update(is_active=False)`; returns 204 |

**Orphaned requirements check:** No requirements mapped to Phase 8 in REQUIREMENTS.md traceability table beyond TOPIC-01 through TOPIC-04. All four are accounted for.

---

## Anti-Patterns Found

Scanned files: `topics.py`, `topic.py`, `topic_dao.py`, `V6__add_topics_unique_name_per_project.sql`

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | None found | — | — |

No TODO/FIXME/placeholder comments, no stub returns (null/empty object/empty array without DB queries), no console.log-only handlers, no empty `=> {}` implementations.

One notable item in `main.py` line 36:

```python
# TODO: Restrict wildcard CORS once frontend origin is finalised.
```

This is pre-existing from Phase 1 and is not in scope for Phase 8. Categorised as INFO only — does not affect topic CRUD goal.

---

## Human Verification Required

### 1. Live create/list round-trip

**Test:** POST to `/vdr-agent/topics` with `{"project_id": "<valid-uuid>", "name": "Climate Risk", "instruction": "Evaluate exposure to physical and transition climate risks"}`. Then GET `/vdr-agent/topics?project_id=<same-uuid>`.
**Expected:** POST returns 201 with full topic JSON (id, project_id, name, instruction, is_active=true, created_at, updated_at). GET returns array containing the created topic.
**Why human:** Requires live PostgreSQL DB with V6 migration applied. Can only confirm DB column rename (instruction_text -> instruction) is in effect by doing a real insert.

### 2. Duplicate name returns 409 before any insert (bulk)

**Test:** POST to `/vdr-agent/topics/bulk` with two topics where the second name already exists in the project.
**Expected:** HTTP 409. No new rows in the `topics` table. The non-duplicate topic from the batch is also absent.
**Why human:** All-or-nothing transactional rollback requires DB to verify row count before and after the request.

### 3. Soft-delete preserves row

**Test:** DELETE `/vdr-agent/topics/{id}`. Then query the DB directly or GET with `include_inactive=true`.
**Expected:** HTTP 204 with empty body. Row still exists with `is_active=false`. GET without `include_inactive` does not return the topic. GET with `include_inactive=true` does return it.
**Why human:** Confirming that no physical DELETE occurred requires inspecting DB state.

---

## Commits Verified

All four commit hashes documented in SUMMARY files are present in the git log:

| Hash | Message |
|------|---------|
| `afb318b` | feat(08-01): add V6 migration and enhance TopicDAO with active filter and bulk_insert |
| `af8ea79` | feat(08-01): create Pydantic request/response models for topic endpoints |
| `39ba49e` | feat(08-02): create topic CRUD router with 5 endpoints and error handling |
| `c98665d` | feat(08-02): wire topics_router into routers/__init__.py and main.py |

---

## Gaps Summary

None. All 14 must-have truths are verified. All 6 artifacts exist, are substantive (real implementations, not stubs), and are correctly wired together. All 5 key links are confirmed. All 4 requirement IDs (TOPIC-01 through TOPIC-04) are satisfied by the implemented code.

The three items in the human verification section require a live database to confirm transactional behaviour and DB state — they are not blockers for code-level goal achievement.

---

_Verified: 2026-03-05T09:00:00Z_
_Verifier: Claude (gsd-verifier)_
