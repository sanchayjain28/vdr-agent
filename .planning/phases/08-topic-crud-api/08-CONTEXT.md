# Phase 8: Topic CRUD API - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

REST endpoints for creating, listing, updating, and deleting ESG topics — enabling the frontend to replace its 19 hardcoded scope names with project-specific topics. Covers TOPIC-01 through TOPIC-04 requirements. Does not include fitment re-run on topic change (v2 TOPIC-06) or new-topic backfill (v2 PROC-05).

</domain>

<decisions>
## Implementation Decisions

### Request/Response Shape
- Create payload: `name` (string) + `instruction` (string) only; `is_active` defaults to `true` server-side
- `project_id` passed as query param on GET list (`?project_id=<uuid>`), in JSON body on POST create
- PATCH accepts partial updates — only send fields to change; omitted fields stay unchanged
- All responses return full topic object: `id`, `project_id`, `name`, `instruction`, `is_active`, `created_at`, `updated_at`
- Endpoint paths: `POST /topics`, `GET /topics?project_id=<id>`, `PATCH /topics/{id}`, `DELETE /topics/{id}`

### Validation Rules
- Topic names must be unique within a project — return 409 Conflict on duplicate
- Name: 1-100 characters, non-empty required
- Instruction: 1-5000 characters, non-empty required
- On create: both name and instruction are required and non-empty (422 if missing/empty)
- On PATCH: any provided field must be non-empty (422 if empty string provided)
- `project_id` accepts any valid UUID — no cross-service validation against ingestion-service

### Delete Behavior
- DELETE is a soft delete — sets `is_active = false`, does NOT remove the row
- DELETE returns HTTP 204 No Content
- Fitment results are preserved (no cascade delete)
- Fitment generation (Phase 7) must skip inactive topics when evaluating documents

### List Filtering
- `GET /topics?project_id=<id>` returns only active topics (`is_active = true`) by default
- Optional `?include_inactive=true` query param to include soft-deleted topics in the response

### Bulk Create
- `POST /topics/bulk` accepts `{ "project_id": "uuid", "topics": [{ "name": "...", "instruction": "..." }, ...] }`
- All-or-nothing transaction — if any topic fails validation (duplicate name, empty field), none are created
- Returns 422 with details on which topic(s) failed
- No limit on array size
- Returns array of created topic objects on success

### Claude's Discretion
- Exact Pydantic model field naming conventions
- Error response body structure (beyond status codes)
- Field length limit values (reasonable defaults for name/instruction if team prefers different bounds)

</decisions>

<specifics>
## Specific Ideas

- Roadmap success criteria specify exact endpoint paths: `POST /vdr-agent/topics`, `GET /vdr-agent/topics?project_id=<id>`, `PATCH /vdr-agent/topics/{id}`, `DELETE /vdr-agent/topics/{id}` (note: `/vdr-agent` prefix comes from FastAPI `root_path`, not the router)
- Bulk create is an addition beyond the roadmap's 4 CRUD endpoints — supports the Phase 10 frontend migration from 19 hardcoded scopes
- Template/default ESG topic list is a frontend concern — vdr-agent API stays domain-agnostic

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TopicDAO` (`app/db/dao/topic_dao.py`): Full CRUD already implemented — `insert`, `list_by_project`, `update`, `delete`, `get_by_id`. All static async methods using `DatabasePool.connection()`
- `TopicRecord` (`app/db/records.py`): Dataclass with `from_row()` classmethod — maps directly to response schema
- `health.py` router: Establishes the `APIRouter()` pattern for the project
- `app/models/__init__.py`: Empty — Pydantic request/response models will be created here

### Established Patterns
- Router files live in `app/core/routers/`, exported via `__init__.py`, included in `main.py` via `app.include_router()`
- DAOs are static async classes — no FastAPI Depends injection, called directly from route handlers
- `DatabasePool.connection()` context manager handles connection lifecycle
- `from __future__ import annotations` required in all modules (Python 3.9 venv)
- Config via `app/config.get_settings()` — Pydantic Settings with `VDR_AGENT_` prefix

### Integration Points
- `main.py:create_app()` — new topic router must be included here alongside `health_router`
- `app/core/routers/__init__.py` — export new router for clean imports
- TopicDAO.update() already supports partial updates (skips None fields) — router can pass through Optional fields directly
- TopicDAO.delete() does hard delete — soft delete behavior means the router will call `TopicDAO.update(is_active=False)` instead of `TopicDAO.delete()`
- Phase 7 (fitment generation) will need to filter by `is_active = true` when fetching topics — this is a downstream concern, not Phase 8

</code_context>

<deferred>
## Deferred Ideas

- Fitment re-run when topic instruction changes — v2 requirement TOPIC-06
- New topic backfill (generate fitment for existing documents) — v2 requirement PROC-05
- Topic enable/disable toggle (separate from delete) — v2 requirement TOPIC-05
- Hard delete endpoint for permanent removal — not needed for v1

</deferred>

---

*Phase: 08-topic-crud-api*
*Context gathered: 2026-03-05*
