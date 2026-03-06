# Phase 9: Results API - Research

**Researched:** 2026-03-05
**Domain:** FastAPI read-only REST endpoints over existing PostgreSQL DAOs
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Document list response shape (GET /documents?project_id=)**
- Returns full document metadata per entry — cross-schema JOIN between `ai_rag.documents` and `vdr_agent.processing_state`
- Fields per document: `id`, `file_name`, `file_path`, `file_type`, `page_count`, `summary_status`, `fitment_done_count`, `fitment_total_count`
- `summary_status` from `vdr_agent.processing_state` (pending | processing | done | failed)
- `fitment_done_count` / `fitment_total_count` — count of `fitment_results` rows with `status='done'` vs total active topics for the project
- Documents in `ai_rag.documents` with no `processing_state` row are included with `summary_status='pending'` (LEFT JOIN)
- No existing DAO covers this — new `DocumentListDAO` or inline query in the router needed

**Fitment response for unevaluated topics (GET /documents/{id}/fitment)**
- Returns one entry per active topic, whether or not a `fitment_results` row exists
- For topics with no row: synthesize `{topic_id, topic_name, status: "pending", reasoning: null}`
- For topics with a row: return actual `{topic_id, topic_name, status, reasoning}` from `fitment_results`
- Requires: fetch active topics via `TopicDAO.list_active_by_project(project_id)` + LEFT JOIN against `FitmentResultDAO.list_by_document(document_id)`
- Need `project_id` to fetch active topics — fetch from `ai_rag.documents WHERE id = document_id` (same pattern as processor.py)

**404 boundary — what counts as a "known" document**
- A document that exists in `ai_rag.documents` is known — never return 404 for it
- If `ai_rag.documents` has the document but `processing_state` has no row → return `{status: "pending"}` (not 404)
- Only return HTTP 404 if the document ID does not exist in `ai_rag.documents` at all
- Same rule applies to all three endpoints — 404 = unknown to ingestion-service, not unknown to vdr-agent

**Summary response shape (GET /documents/{id}/summary)**
- Always returns `{document_id, status, summary_text}` — never an error for known documents
- `status` from `processing_state.summary_status` (pending | processing | done | failed)
- `summary_text` from `document_summaries.summary_text` — null if no summary yet
- If no `processing_state` row: `{status: "pending", summary_text: null}`

**HTTP status codes**
- 200 for all known documents regardless of processing state
- 404 only when `document_id` not found in `ai_rag.documents`
- 404 when `project_id` returns zero documents from `ai_rag.documents`
- 422 for malformed UUIDs (FastAPI default)

### Claude's Discretion
- Whether to create a new `DocumentListDAO` or use an inline query in the router
- Exact Pydantic response model field naming
- Whether `fitment_total_count` is computed via COUNT(active topics) or COUNT(fitment_results rows regardless of status)
- Order of documents in list response (created_at DESC is a reasonable default)

### Deferred Ideas (OUT OF SCOPE)
- Pagination on document list — v2 concern
- Filter documents by processing status — v2 concern
- API-04: filter documents by topic relevance — v2 requirement
- FE-04: AI summary in document detail view — Phase 10 concern
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| API-01 | User can retrieve the AI summary for a document | `GET /vdr-agent/documents/{id}/summary` — compose `ProcessingStateDAO.get_by_document()` + `DocumentSummaryDAO.get_by_document()`; synthesize pending if no state row |
| API-02 | User can retrieve all fitment results for a document (one result per topic) | `GET /vdr-agent/documents/{id}/fitment` — fetch project_id from ai_rag.documents, call `TopicDAO.list_active_by_project()` + `FitmentResultDAO.list_by_document()`, merge in Python |
| API-03 | User can list documents for a project with their summary and fitment processing status | `GET /vdr-agent/documents?project_id=<id>` — LEFT JOIN query across ai_rag.documents + processing_state + fitment_results aggregate; new DocumentListDAO method needed |
</phase_requirements>

---

## Summary

Phase 9 is a pure read layer — three GET endpoints that expose data already written to the database by Phases 5–8. No writes occur. No new tables are required. The primary challenge is query composition: the document list endpoint needs a new cross-schema JOIN (ai_rag → vdr_agent) with aggregate counts, while the two per-document endpoints compose existing DAOs with Python-level merging for the fitment synthesis.

The established patterns from Phase 8 (topics router) are the direct template: `APIRouter` with prefix, static async DAOs called directly (no FastAPI `Depends`), Pydantic response models in `app/models/`, router exported via `app/core/routers/__init__.py` and included in `main.py`. The `search_path = vdr_agent, ai_rag, public` on pool connections means cross-schema references work without fully-qualified names in most queries, but using fully-qualified names is safer.

The fitment endpoint's merge logic (active topics LEFT JOIN fitment_results, synthesizing pending entries for gaps) is done in Python after two sequential DAO calls — not in SQL — because the existing `FitmentResultDAO.list_by_document()` and `TopicDAO.list_active_by_project()` already exist and cover the needed reads. The document list is the exception: it requires a single SQL query with LEFT JOINs and a subquery aggregate, best placed in a new `DocumentListDAO.list_by_project()` method.

**Primary recommendation:** Create `app/core/routers/documents.py` following the exact `topics.py` pattern; add `DocumentListDAO` in `app/db/dao/document_list_dao.py` for the aggregate list query; compose existing DAOs for the two per-document endpoints.

---

## Standard Stack

### Core (already in project — no new installs needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | 0.115+ | Router, HTTPException, Query, status | Already used; topics.py is the exact template |
| psycopg3 | 3.3.3 | Async DB access via `DatabasePool.connection()` | Established in Phase 3; all DAOs use it |
| Pydantic v2 | (project pin) | Response models with field validation | `app/models/` pattern from Phase 8 |
| Python UUID | stdlib | `UUID` type for path/query params | FastAPI auto-validates and returns 422 on malformed |

### No New Dependencies

All required libraries are already installed. Phase 9 adds zero new packages.

---

## Architecture Patterns

### Recommended Project Structure

```
vdr-agent/
├── app/
│   ├── core/
│   │   └── routers/
│   │       ├── __init__.py          # add documents_router export
│   │       ├── documents.py         # NEW — three endpoints
│   │       ├── health.py            # existing
│   │       └── topics.py            # existing — template
│   ├── db/
│   │   └── dao/
│   │       ├── document_list_dao.py # NEW — list_by_project() cross-schema JOIN
│   │       ├── document_summary_dao.py  # existing — get_by_document()
│   │       ├── fitment_result_dao.py    # existing — list_by_document()
│   │       ├── processing_state_dao.py  # existing — get_by_document()
│   │       └── topic_dao.py             # existing — list_active_by_project()
│   └── models/
│       ├── __init__.py              # existing
│       ├── topic.py                 # existing
│       └── document.py              # NEW — response models for documents endpoints
└── main.py                          # add documents_router include
```

### Pattern 1: Router File Structure (copy from topics.py)

**What:** APIRouter with prefix, static async DAO calls, Pydantic response models, HTTPException for errors.
**When to use:** All three endpoints in documents.py.

```python
# app/core/routers/documents.py
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.db.dao.document_list_dao import DocumentListDAO
from app.db.dao.document_summary_dao import DocumentSummaryDAO
from app.db.dao.fitment_result_dao import FitmentResultDAO
from app.db.dao.processing_state_dao import ProcessingStateDAO
from app.db.dao.topic_dao import TopicDAO
from app.models.document import DocumentListItem, FitmentItem, SummaryResponse

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])
```

### Pattern 2: Per-Document 404 Guard

**What:** Every per-document endpoint first verifies the document exists in ai_rag.documents. Returns 404 if not found, proceeds with processing state logic otherwise.
**When to use:** Both `/documents/{id}/summary` and `/documents/{id}/fitment`.

```python
# Source: established pattern from processor.py (Phase 7)
async def _get_document_or_404(document_id: UUID):
    """Fetch document row from ai_rag.documents; raise 404 if not found."""
    async with DatabasePool.connection() as conn:
        row = await conn.fetchrow(
            "SELECT id, project_id FROM ai_rag.documents WHERE id = %s",
            document_id,
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return row
```

### Pattern 3: Summary Endpoint — Compose Two DAOs

**What:** Fetch processing state (may be None → synthesize pending) and document summary (may be None → null text). Return unified response.
**When to use:** `GET /documents/{id}/summary`

```python
@router.get("/{document_id}/summary", response_model=SummaryResponse)
async def get_document_summary(document_id: UUID) -> SummaryResponse:
    await _get_document_or_404(document_id)
    state = await ProcessingStateDAO.get_by_document(document_id)
    summary = await DocumentSummaryDAO.get_by_document(document_id)
    return SummaryResponse(
        document_id=document_id,
        status=state.summary_status if state else "pending",
        summary_text=summary.summary_text if summary else None,
    )
```

### Pattern 4: Fitment Endpoint — Two DAOs + Python Merge

**What:** Get project_id from ai_rag.documents, fetch active topics and fitment rows separately, merge in Python to produce one entry per topic.
**When to use:** `GET /documents/{id}/fitment`

```python
@router.get("/{document_id}/fitment", response_model=List[FitmentItem])
async def get_document_fitment(document_id: UUID) -> List[FitmentItem]:
    doc_row = await _get_document_or_404(document_id)
    project_id = doc_row["project_id"]

    topics = await TopicDAO.list_active_by_project(project_id)
    fitment_rows = await FitmentResultDAO.list_by_document(document_id)

    # Index fitment results by topic_id for O(1) lookup
    fitment_by_topic = {r.topic_id: r for r in fitment_rows}

    result = []
    for topic in topics:
        row = fitment_by_topic.get(topic.id)
        result.append(FitmentItem(
            topic_id=topic.id,
            topic_name=topic.name,
            status=row.status if row else "pending",
            reasoning=row.reasoning if row else None,
        ))
    return result
```

### Pattern 5: Document List — New DAO with Cross-Schema JOIN

**What:** Single SQL query with LEFT JOINs across ai_rag.documents, vdr_agent.processing_state, and a subquery aggregate over vdr_agent.fitment_results. 404 if no documents found for project_id.
**When to use:** `GET /documents?project_id=<id>`

```python
# app/db/dao/document_list_dao.py
from __future__ import annotations

from uuid import UUID
from typing import List

from app.db.pool import DatabasePool
from app.db.records import DocumentListRecord


class DocumentListDAO:

    @staticmethod
    async def list_by_project(project_id: UUID) -> List[DocumentListRecord]:
        async with DatabasePool.connection() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    d.id,
                    d.file_name,
                    d.file_path,
                    d.file_type,
                    d.page_count,
                    COALESCE(ps.summary_status, 'pending') AS summary_status,
                    COUNT(fr.id) FILTER (WHERE fr.status = 'done') AS fitment_done_count,
                    (
                        SELECT COUNT(*) FROM vdr_agent.topics t
                        WHERE t.project_id = d.project_id AND t.is_active = TRUE
                    ) AS fitment_total_count
                FROM ai_rag.documents d
                LEFT JOIN vdr_agent.processing_state ps ON ps.document_id = d.id
                LEFT JOIN vdr_agent.fitment_results fr ON fr.document_id = d.id
                WHERE d.project_id = %s
                GROUP BY d.id, d.file_name, d.file_path, d.file_type, d.page_count, ps.summary_status
                ORDER BY d.created_at DESC
                """,
                project_id,
            )
        return [DocumentListRecord(**dict(r)) for r in rows]
```

### Pattern 6: Pydantic Response Models

**What:** Models in `app/models/document.py` with Optional fields for nullable data. Use `from_record()` classmethods consistent with TopicResponse pattern.
**When to use:** All three endpoints.

```python
# app/models/document.py
from __future__ import annotations

from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class SummaryResponse(BaseModel):
    document_id: UUID
    status: str  # pending | processing | done | failed
    summary_text: Optional[str] = None


class FitmentItem(BaseModel):
    topic_id: UUID
    topic_name: str
    status: str  # pending | processing | done | failed
    reasoning: Optional[str] = None


class DocumentListItem(BaseModel):
    id: UUID
    file_name: str
    file_path: str
    file_type: str
    page_count: Optional[int] = None
    summary_status: str
    fitment_done_count: int
    fitment_total_count: int
```

### Pattern 7: Register Router in main.py

**What:** Import `documents_router` from `app.core.routers`, add `app.include_router(documents_router)` in `create_app()`.

```python
# main.py additions
from app.core.routers import health_router, topics_router, documents_router

# in create_app():
app.include_router(documents_router)
```

### Anti-Patterns to Avoid

- **Holding DB connection across multiple DAO calls:** Each DAO call gets its own `DatabasePool.connection()` context. Never open one connection and pass it to multiple DAO methods.
- **Returning 404 for unprocessed documents:** A document in `ai_rag.documents` with no `processing_state` row is KNOWN — return `{status: "pending"}`, not 404.
- **404 when project has documents:** Only return 404 for the document list endpoint if the project_id returns zero rows from `ai_rag.documents`. If it has documents, return the list (even if all pending).
- **Using f-strings for SQL parameters:** Always use parameterized queries — `WHERE id = %s` with `(project_id,)` tuple. Never `f"WHERE id = '{project_id}'"`.
- **Importing processor.py from router:** Never import from `app.worker` in routers — that path caused Phase 5 circular import concern. Routers only import DAOs and models.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| UUID path param validation | Custom regex validator | FastAPI `UUID` type annotation | FastAPI auto-validates, returns 422 on malformed |
| Cross-schema query routing | Manual connection switching | Existing search_path on pool connections | Phase 3 configure() sets `search_path = vdr_agent, ai_rag, public` |
| JSON serialization of UUID/datetime | Custom serializers | Pydantic BaseModel | Handles UUID→string automatically |
| Optional field handling | Manual None checks in response | Pydantic `Optional[str] = None` | Correct OpenAPI schema generated automatically |

---

## Common Pitfalls

### Pitfall 1: project_id Not Available on Per-Document Endpoints
**What goes wrong:** `/documents/{id}/summary` and `/documents/{id}/fitment` receive only a document UUID. The fitment endpoint needs project_id to call `TopicDAO.list_active_by_project()`.
**Why it happens:** Endpoints are document-scoped, not project-scoped.
**How to avoid:** Follow processor.py pattern — fetch `project_id` from `ai_rag.documents WHERE id = document_id` as the first DB call. If that row is missing, raise 404. project_id is then available for downstream DAO calls.
**Warning signs:** AttributeError on None when accessing `.project_id` without a guard.

### Pitfall 2: fitment_results Rows vs Active Topics Mismatch
**What goes wrong:** A document may have fitment rows for topics that have since been soft-deleted (is_active=False). If you return all fitment rows, you expose stale topic data.
**Why it happens:** Phase 7 writes fitment rows at processing time; Phase 8 allows topic soft-delete afterward.
**How to avoid:** The authoritative list is `TopicDAO.list_active_by_project()` (active topics only). Build `fitment_by_topic` dict from DB rows, iterate over active topics — stale rows are simply not included.
**Warning signs:** Returning more fitment entries than there are active topics.

### Pitfall 3: Document List 404 Logic
**What goes wrong:** Returning 404 when a project_id has no documents yet (empty project), OR returning 200 with an empty list when the project doesn't exist.
**Why it happens:** The locked decision says 404 when "project_id returns zero documents from ai_rag.documents" — this is a proxy for project existence since vdr-agent has no projects table.
**How to avoid:** `if not rows: raise HTTPException(404)` after the list query. Empty list = unknown project (or project with no documents ingested — acceptable tradeoff in v1).
**Warning signs:** Frontend never seeing 404 for bad project IDs.

### Pitfall 4: DocumentListRecord Dataclass Field Names
**What goes wrong:** SQL column aliases like `fitment_done_count` must exactly match the dataclass field names used in `DocumentListRecord(**dict(r))`.
**Why it happens:** psycopg3 rows are dict-like; mismatched keys cause TypeError.
**How to avoid:** Define `DocumentListRecord` dataclass fields to match SQL aliases exactly. Verify with a quick `print(dict(row))` in development.

### Pitfall 5: COALESCE for Missing processing_state Rows
**What goes wrong:** Documents in `ai_rag.documents` with no `processing_state` row return NULL for `summary_status` when using LEFT JOIN.
**Why it happens:** LEFT JOIN produces NULL for unmatched right-side columns.
**How to avoid:** Use `COALESCE(ps.summary_status, 'pending')` in the SELECT. This ensures the locked decision ("docs with no poller row get summary_status='pending'") is enforced in SQL, not Python.

---

## Code Examples

### Checking ai_rag.documents for document existence

```python
# Source: established pattern from vdr-agent/app/worker/processor.py (Phase 7)
# project_id fetch pattern used in process_document()
async with DatabasePool.connection() as conn:
    row = await conn.fetchrow(
        "SELECT id, project_id FROM ai_rag.documents WHERE id = %s",
        document_id,
    )
if row is None:
    raise HTTPException(status_code=404, detail="Document not found")
project_id = row["project_id"]
```

### Router registration pattern (from main.py + topics router)

```python
# Source: vdr-agent/main.py + vdr-agent/app/core/routers/__init__.py
# Existing pattern — replicate for documents_router
from app.core.routers import health_router, topics_router, documents_router

app.include_router(health_router)
app.include_router(topics_router)
app.include_router(documents_router)  # new
```

### TopicResponse.from_record() classmethod pattern (from app/models/topic.py)

```python
# Source: vdr-agent/app/models/topic.py (Phase 8 pattern)
# DocumentListItem should follow the same from_record() convention
@classmethod
def from_record(cls, record: DocumentListRecord) -> "DocumentListItem":
    return cls(
        id=record.id,
        file_name=record.file_name,
        ...
    )
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Inline SQL in router functions | DAO class with static async methods | Phase 3 established this; maintain it for document list |
| Separate DB connection per field | Single query with JOINs + COALESCE | Correct for document list — one round-trip not three |
| Boolean is_relevant on fitment | TEXT reasoning only | Phase 2 locked decision — no boolean field exists |

---

## Open Questions

1. **fitment_total_count computation method**
   - What we know: CONTEXT.md leaves this to Claude's discretion — "COUNT(active topics) or COUNT(fitment_results rows regardless of status)"
   - What's unclear: Should a project with 5 active topics always show fitment_total_count=5, or should it reflect only topics that have been evaluated?
   - Recommendation: Use COUNT of active topics (subquery on `vdr_agent.topics WHERE project_id = X AND is_active = TRUE`) — this is the canonical "how many fitments should this document have" answer, independent of processing state. Consistent with the fitment endpoint which shows one entry per active topic.

2. **DocumentListRecord — new dataclass or inline dict**
   - What we know: `app/db/records.py` holds existing dataclass records; Phase 3 pattern is dataclasses for all DAO return types
   - Recommendation: Add `DocumentListRecord` to `app/db/records.py` alongside existing records — consistent with established pattern.

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/core/routers/topics.py` — router pattern, HTTPException usage, Pydantic model pattern
- Direct code inspection: `/Users/sanchayjain/Desktop/ERM/vdr-agent/main.py` — router registration, `root_path="/vdr-agent"` confirmed
- Direct code inspection: `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/db/dao/` — existing DAO files confirmed present and named
- `.planning/phases/09-results-api/09-CONTEXT.md` — locked decisions, response shapes, 404 boundary rules

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` — accumulated decisions from Phases 1–8; search_path, DAO patterns, COALESCE behavior verified
- `.planning/REQUIREMENTS.md` — API-01, API-02, API-03 definitions

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already installed and in use; no new dependencies
- Architecture: HIGH — topics.py is a direct, complete template; patterns verified in actual code
- Pitfalls: HIGH — derived from locked decisions in CONTEXT.md and accumulated STATE.md decisions

**Research date:** 2026-03-05
**Valid until:** 2026-04-04 (stable — FastAPI/psycopg3/Pydantic patterns don't shift quickly)
