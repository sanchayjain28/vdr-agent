# Phase 9: Results API - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Three read-only REST endpoints exposing AI summary and fitment results to consumers:
1. `GET /vdr-agent/documents/{id}/summary` — AI summary text + status for one document
2. `GET /vdr-agent/documents/{id}/fitment` — per-topic fitment results for one document
3. `GET /vdr-agent/documents?project_id=<id>` — document list with processing status

No write operations. No auth. No pagination in v1. Pure read layer over existing DB tables.

</domain>

<decisions>
## Implementation Decisions

### Document list response shape (GET /documents?project_id=)
- Returns **full document metadata** per entry — cross-schema JOIN between `ai_rag.documents` and `vdr_agent.processing_state`
- Fields per document: `id`, `file_name`, `file_path`, `file_type`, `page_count`, `summary_status`, `fitment_done_count`, `fitment_total_count`
- `summary_status` from `vdr_agent.processing_state` (pending | processing | done | failed)
- `fitment_done_count` / `fitment_total_count` — count of `fitment_results` rows with `status='done'` vs total active topics for the project
- Documents in `ai_rag.documents` with no `processing_state` row are included with `summary_status='pending'` (LEFT JOIN)
- No existing DAO covers this — new `DocumentListDAO` or inline query in the router needed

### Fitment response for unevaluated topics (GET /documents/{id}/fitment)
- Returns **one entry per active topic**, whether or not a `fitment_results` row exists
- For topics with no row: synthesize `{topic_id, topic_name, status: "pending", reasoning: null}`
- For topics with a row: return actual `{topic_id, topic_name, status, reasoning}` from `fitment_results`
- Requires: fetch active topics via `TopicDAO.list_active_by_project(project_id)` + LEFT JOIN against `FitmentResultDAO.list_by_document(document_id)`
- Need `project_id` to fetch active topics — fetch from `ai_rag.documents WHERE id = document_id` (same pattern as processor.py)

### 404 boundary — what counts as a "known" document
- A document that exists in `ai_rag.documents` is **known** — never return 404 for it
- If `ai_rag.documents` has the document but `processing_state` has no row → return `{status: "pending"}` (not 404)
- Only return HTTP 404 if the document ID does not exist in `ai_rag.documents` at all
- Same rule applies to all three endpoints — 404 = unknown to ingestion-service, not unknown to vdr-agent

### Summary response shape (GET /documents/{id}/summary)
- Always returns `{document_id, status, summary_text}` — never an error for known documents
- `status` from `processing_state.summary_status` (pending | processing | done | failed)
- `summary_text` from `document_summaries.summary_text` — null if no summary yet
- If no `processing_state` row: `{status: "pending", summary_text: null}`

### HTTP status codes
- 200 for all known documents regardless of processing state
- 404 only when `document_id` not found in `ai_rag.documents`
- 404 when `project_id` returns zero documents from `ai_rag.documents`
- 422 for malformed UUIDs (FastAPI default)

### Claude's Discretion
- Whether to create a new `DocumentListDAO` or use an inline query in the router
- Exact Pydantic response model field naming
- Whether `fitment_total_count` is computed via COUNT(active topics) or COUNT(fitment_results rows regardless of status)
- Order of documents in list response (created_at DESC is a reasonable default)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `DocumentSummaryDAO.get_by_document(document_id)` — returns `DocumentSummaryRecord | None`
- `FitmentResultDAO.list_by_document(document_id)` — returns all fitment rows for a doc
- `ProcessingStateDAO.get_by_document(document_id)` — returns `ProcessingStateRecord | None`
- `TopicDAO.list_active_by_project(project_id)` — returns active topics (Phase 7 addition)
- `topics.py` router — establishes `APIRouter` + Pydantic model pattern for Phase 9 to follow
- `app/models/__init__.py` — empty, Phase 8 added Pydantic models here; Phase 9 adds response models

### Established Patterns
- `from __future__ import annotations` in all modules (Python 3.9)
- Router files in `app/core/routers/`, exported via `__init__.py`, included in `main.py`
- DAOs are static async — called directly, no FastAPI Depends
- `DatabasePool.connection()` for all DB access — short-lived, never held during AI calls
- `search_path = vdr_agent, ai_rag, public` on pool connections — cross-schema queries work natively

### Integration Points
- `main.py:create_app()` — new documents router included here
- `app/core/routers/__init__.py` — export new router
- `ai_rag.documents` — cross-schema read for document metadata and project_id; works via existing search_path
- `vdr_agent.processing_state` — LEFT JOIN target for summary status
- `vdr_agent.fitment_results` — LEFT JOIN target for per-topic results

</code_context>

<specifics>
## Specific Ideas

- The fitment endpoint needs two sources: `TopicDAO.list_active_by_project()` for the full topic list, then merge with `FitmentResultDAO.list_by_document()` results — topics with no fitment row get synthesized pending entries
- project_id for fitment/summary endpoints: fetch from `ai_rag.documents WHERE id = document_id` (same inline pattern established in processor.py Phase 7)
- Documents list endpoint is the only one requiring a new DAO method or raw SQL — the other two endpoints can compose existing DAOs

</specifics>

<deferred>
## Deferred Ideas

- Pagination on document list — v2 concern
- Filter documents by processing status — v2 concern
- API-04: filter documents by topic relevance — v2 requirement
- FE-04: AI summary in document detail view — Phase 10 concern

</deferred>

---

*Phase: 09-results-api*
*Context gathered: 2026-03-05*
