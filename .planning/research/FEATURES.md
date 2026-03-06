# Feature Landscape

**Domain:** AI document analysis microservice — ESG topic fitment (vdr-agent)
**Researched:** 2026-03-05
**Confidence:** HIGH — derived from existing codebase, PROJECT.md, ARCHITECTURE_OVERVIEW.md, and direct inspection of vdr-frontend source

---

## Context

`vdr-agent` is a new FastAPI microservice being added to an existing ESG VDR platform. It sits alongside
`ingestion-service` (which handles ingestion into PostgreSQL) and serves `vdr-frontend` (React + Ant Design).
The service owns all AI analysis: topic/scope CRUD, document AI summary generation, and per-topic fitment
summaries. The frontend already has placeholder columns for "File Summary" and "Scope Fitting" — those columns
currently render `-` and need real data wired in.

This feature list is shaped by three hard constraints:
1. No Temporal — background polling loop is the trigger mechanism
2. No retries — failures are skipped silently in v1
3. No auth on vdr-agent APIs — internal service only

---

## Table Stakes

Features that must work or the system does not function at all.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Topic CRUD (list, create, update, delete) | Topics/scopes must exist before ingestion begins; the frontend's ProjectDetails page renders 19 hardcoded scopes that need a real data source | Low | `name`, `description`, `instructions` (free-text), `is_active` flag. Max ~30 topics per project. |
| Per-topic instruction field | Instructions drive what the AI looks for during fitment; without them fitment results are meaningless | Low | Free-text field stored alongside the topic record. Must be updateable independently of topic name. |
| AI document summary generation | Core value of the service — "What is this document?" | Medium | Section summaries in parallel (~10 calls), combined into 1 summary. Result stored in DB and returned via API. |
| Fitment summary generation per topic | Core value — "How does this document relate to Topic X?" | Medium | 1 Claude call per active topic per document (~20–30 calls). Uses AI summary + relevant sections retrieved via vector search. |
| DB polling loop | Trigger mechanism — vdr-agent has no event bus; it queries for `embedding_status = 'done' AND summary_status IS NULL` | Low | asyncio background task; runs on a configurable interval (e.g., 30–60s). |
| Result storage (summaries + fitment) | Results must be persisted for API reads; without storage the frontend can't display anything | Low | vdr-agent owns its own tables in a `vdr_agent` schema within the shared PostgreSQL cluster. |
| Document summary status field | Frontend needs to know whether a summary is pending, processing, done, or skipped | Low | `summary_status`: `pending | processing | done | skipped`. Drives the "Status" column already visible in ScopeDetails.tsx. |
| Fitment status per topic-document pair | Frontend needs to know if fitment for a given topic+document is ready or still processing | Low | `fitment_status`: `pending | processing | done | skipped` per `(document_id, topic_id)` row. |
| GET /documents endpoint with summary + fitment | vdr-frontend's ScopeDetails page renders a table of documents with "File Summary" and "Scope Fitting" columns; currently hardwired to `-` | Low | Must return documents enriched with their summary status and fitment summary for the currently-selected topic. |
| GET /topics endpoint | Frontend's scope list (ProjectDetails page) needs to be driven by real topic records from vdr-agent, not hardcoded data | Low | Returns list of topics with name, description, is_active. No heavy pagination needed (max 30). |
| Re-run fitment on topic instruction update | Architecture document calls this out explicitly: when instructions change, all fitment for that topic must be invalidated and re-queued | Medium | On `PATCH /topics/{id}` with changed instructions: set all `(document_id, topic_id)` fitment rows to `pending`, let the polling loop pick them up. AI summaries untouched. |
| Re-run fitment for new topic | If a new topic is added after documents are already processed, fitment must be generated for all existing documents for that new topic | Medium | On topic create, insert `pending` fitment rows for all documents with `summary_status = done`. Polling loop picks them up. |
| Health check endpoint | Required for Docker/K8s liveness probes | Low | `GET /health` returning `{"status": "ok"}`. |

---

## Differentiators

Features that set the product apart but are not required for v1 correctness.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Fitment relevance flag (relevant / not relevant / partial) | Allows frontend to colour-code or filter by fitment outcome without parsing free-text; ProjectDetails already has colour-coded risk levels that could map to this | Low | Add `relevance` enum (`relevant | not_relevant | partial`) to the fitment row. AI outputs this alongside the textual summary. |
| Progress counters on document list | The frontend can show "12/30 topics analysed" per document, giving users confidence the system is working | Low | Computed from COUNT of `fitment_status = done` vs total active topics; can be computed at query time. |
| Topic ordering / sort index | Allows users to define a preferred display order for topics (the frontend's ProjectDetails already renders topics 1–19 in a numbered list) | Low | Add an `order_index` integer to the topic table; default to insert order. |
| Fitment summary with evidence citations | Including the source page numbers and section headings where evidence was found makes summaries actionable, not just descriptive | Medium | Extract page numbers from embedding metadata (`source_pages` field in `embeddings.metadata`) and include in the fitment response. |
| Bulk re-run endpoint | `POST /topics/{id}/rerun-fitment` to manually trigger re-run for a topic without waiting for instruction change | Low | Useful for admin/debugging; sets all fitment rows for topic to `pending`. |
| Summary regeneration on document re-ingestion | If a document's content changes in SharePoint and is re-ingested, the AI summary should be regenerated | Medium | Detect by checking if the embedding's `updated_at` is newer than `summary_generated_at`. Out of scope for v1 per PROJECT.md, but a clear future need. |
| Topic activation / deactivation | Allows users to pause fitment for a topic without deleting it — useful when a topic is temporarily irrelevant | Low | `is_active` flag already in the data model; deactivated topics are skipped by the fitment loop. |

---

## Anti-Features

Features to deliberately NOT build in v1.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Temporal workflows in vdr-agent | Adding Temporal to vdr-agent would require standing up another worker process and entangles the service with ingestion-service's orchestration complexity. PROJECT.md explicitly rejects this. | DB polling with asyncio background task. Temporal can be added in a future phase if scale demands it. |
| Per-document manual re-trigger API | Encouraging manual triggers adds UI complexity and undermines the "automatic" value proposition. Users should not need to press a button to process a document. | DB polling handles this automatically. |
| Retry logic on AI generation failures | Retries add state machine complexity. A failed document silently stays with `summary_status = skipped`. PROJECT.md explicitly defers retries. | Log the failure with the error message, move on. Revisit in a future phase. |
| Streaming / Server-Sent Events for real-time progress | SSE requires server-side infrastructure changes and frontend complexity. The polling model is simpler and sufficient given the ~30–60 second document processing time. | Frontend polls `GET /documents` on a timer (e.g., every 10s). Incremental results appear naturally. |
| Webhooks or push notifications | No event bus exists in this architecture; adding one now is out of scope. | Frontend polling is the agreed pattern. |
| Multi-tenant topic isolation | The platform appears to use project-level scoping, but vdr-agent v1 does not need to enforce row-level security per tenant at the service boundary. Authentication is deferred to user-service. | Topics are project-scoped via `project_id` foreign key. Access control is enforced at a higher level. |
| Vector search within vdr-agent | The `embeddings` table and pgvector are owned by ingestion-service. vdr-agent should query them via shared DB (raw SQL), not replicate a search layer. | vdr-agent reads embeddings via raw SQL DAO in the same PostgreSQL cluster. |
| UI for topic management in vdr-agent | vdr-agent is a backend service. UI is owned by vdr-frontend. | Expose clean REST APIs; vdr-frontend renders the UI. |
| Caching layer (Redis) | The call volume (~41,000 AI calls for 1,000 docs) does not justify a caching layer in v1. AI summaries are write-once and read-many via the DB. | PostgreSQL is the cache. Results are stored on first generation, subsequent reads are DB reads. |

---

## API Design: Async AI Generation Patterns

This section captures the API patterns for returning async AI results that are produced incrementally.

### The Core Problem

Generating an AI summary takes ~30s–10min per document. Generating fitment for 20–30 topics adds another
~20–30 Claude calls. The frontend must not block waiting for all of this — it needs to render documents
as soon as ingestion is done and show AI content as it arrives.

### Recommended Pattern: Polling with Status Fields

The simplest pattern that fits this architecture. No SSE, no WebSockets, no webhooks.

**How it works:**

1. Ingestion service marks a document as `embedding_status = done`.
2. vdr-agent polling loop picks it up, sets `summary_status = processing`, starts AI generation.
3. When summary is ready, sets `summary_status = done`, stores the text.
4. Fitment runs in parallel: each topic's row is set `fitment_status = processing`, then `done` when complete.
5. Frontend polls `GET /documents?project_id={id}&topic_id={id}` every 10–15 seconds.
6. Each document row in the response includes `summary_status`, `summary_text`, `fitment_status`, `fitment_text`.

**Why this works here:**
- 1,000 documents processed over hours; 10s polling interval is imperceptible lag.
- No infrastructure beyond PostgreSQL is needed.
- The frontend already fetches documents on mount (see `ScopeDetails.tsx` calling `getProjectDocuments`).
- Status fields (`pending | processing | done | skipped`) are trivially renderable as loading spinners or text in Ant Design Table cells.

**API shape (document list endpoint):**

```
GET /vdr-agent/documents?project_id={uuid}&topic_id={uuid}&limit=50&offset=0

Response:
{
  "documents": [
    {
      "id": "uuid",
      "file_name": "sustainability-report-2024.pdf",
      "file_type": "application/pdf",
      "summary_status": "done",          // pending | processing | done | skipped
      "summary_text": "This annual...",   // null until done
      "fitment_status": "done",           // null if topic_id not provided
      "fitment_text": "This document...", // null until done
      "fitment_relevance": "relevant",    // relevant | not_relevant | partial | null
      "created_at": "2026-03-05T10:00:00Z",
      "updated_at": "2026-03-05T10:02:00Z"
    }
  ],
  "total": 1000,
  "offset": 0,
  "limit": 50
}
```

**Topic management API shape:**

```
GET    /vdr-agent/topics?project_id={uuid}
POST   /vdr-agent/topics
PATCH  /vdr-agent/topics/{topic_id}       -- triggers fitment re-run on instruction change
DELETE /vdr-agent/topics/{topic_id}

Topic object:
{
  "id": "uuid",
  "project_id": "uuid",
  "name": "ESG Strategy",
  "description": "...",
  "instructions": "Look for...",   // free-text, drives fitment AI prompt
  "is_active": true,
  "order_index": 1,
  "created_at": "...",
  "updated_at": "..."
}
```

**Re-run trigger:**

When `PATCH /vdr-agent/topics/{topic_id}` receives a changed `instructions` field:
- Set all `fitment` rows for that topic to `status = pending`.
- Return 200 immediately — do NOT block on re-generation.
- Polling loop picks up pending rows on its next iteration.

This means the API response is synchronous and instant; generation happens asynchronously in the background.

### What NOT to Use

| Pattern | Why Not |
|---------|---------|
| Server-Sent Events (SSE) | Requires persistent connections; NGINX reverse proxy timeouts and load balancer configurations add complexity. Overkill for 10s polling granularity. |
| WebSockets | Same reasons as SSE, plus vdr-frontend uses Axios (not a WebSocket client). |
| Long-polling | Holds server connections open; defeats FastAPI's async benefits under load. |
| Job queue with separate status endpoint | Adds a separate `GET /jobs/{job_id}/status` contract. Unnecessary when status lives on the document/fitment row itself. |

---

## Feature Dependencies

```
Topic CRUD
  └── Topic instructions field        (instructions are part of the topic record)
  └── Re-run fitment on change        (requires topic update to invalidate fitment rows)
  └── Re-run fitment for new topic    (requires topic create to seed pending rows)

DB polling loop
  └── AI summary generation           (polling loop drives this)
      └── Result storage              (summary stored before fitment starts)
      └── Fitment summary generation  (depends on summary being done first)
          └── Fitment status field    (updated per topic-document pair)

GET /documents endpoint
  └── Summary status field            (must be in DB schema before API can return it)
  └── Fitment status field            (must be in DB schema before API can return it)
  └── Topic CRUD                      (must know which topic to filter fitment by)

GET /topics endpoint
  └── Topic CRUD                      (topics must exist)
```

**Critical ordering constraint:** Topics must be created (with instructions) before the sync begins and before the polling loop processes documents. If documents are processed without any active topics, no fitment rows are seeded. Re-running fitment for a new topic retroactively handles this, but it is an extra step.

---

## MVP Recommendation

Build in this order:

1. **Topic CRUD API** — `GET /topics`, `POST /topics`, `PATCH /topics/{id}`, `DELETE /topics/{id}`. Simple, no async, no AI. Unblocks frontend wiring immediately.

2. **DB schema for summaries and fitment** — `document_summaries` table, `document_fitments` table. These must exist before anything else can write to them.

3. **DB polling loop** — Background asyncio task. Queries for unprocessed documents, drives all generation.

4. **AI summary generation** — Section summaries in parallel, combined summary. Write result to `document_summaries`.

5. **Fitment generation** — One Claude call per active topic, using summary + relevant embedding chunks. Write to `document_fitments`.

6. **GET /documents endpoint** — Join documents + summaries + fitments and return enriched list. This is what vdr-frontend needs to replace the hardcoded `-` in the table.

7. **Re-run on instruction change** — Wire into `PATCH /topics/{id}`: invalidate fitment rows, polling loop picks them up.

**Defer to later:**
- Fitment relevance flag (differentiator, low effort — can be added to the fitment row when implementing step 5 if prompt is designed for it)
- Evidence citations (medium complexity, add in a v2 iteration)
- Bulk re-run endpoint (nice for ops, low priority)
- Summary regeneration on document re-ingestion (meaningful but complex, deferred per PROJECT.md)

---

## Sources

- `/Users/sanchayjain/Desktop/ERM/.planning/PROJECT.md` — authoritative project constraints and out-of-scope list (HIGH confidence)
- `/Users/sanchayjain/Desktop/ERM/ARCHITECTURE_OVERVIEW.md` — system flow diagrams and design rationale (HIGH confidence)
- `/Users/sanchayjain/Desktop/ERM/vdr-frontend/src/pages/scopeDetails/ScopeDetails.tsx` — frontend table structure with placeholder "File Summary" and "Scope Fitting" columns (HIGH confidence)
- `/Users/sanchayjain/Desktop/ERM/vdr-frontend/src/pages/projectDetails/ProjectDetails.tsx` — 19 hardcoded ESG scope names confirming the topic domain (HIGH confidence)
- `/Users/sanchayjain/Desktop/ERM/vdr-frontend/src/store/scope/scopeInterface.ts` — existing Scope model shape (HIGH confidence)
- `/Users/sanchayjain/Desktop/ERM/vdr-frontend/src/store/sharepoint/sharepoint.interface.ts` — IProjectDocument shape showing status fields the frontend already handles (HIGH confidence)
- `/Users/sanchayjain/Desktop/ERM/vdr-frontend/src/services/apiClients.ts` — Axios client confirms polling-based fetch model (HIGH confidence)
- `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/db/dao/embedding_dao.py` — confirms `source_pages` in embedding metadata, relevant for citation feature (HIGH confidence)
- `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/models/document.py` — confirms DocumentStatus enum pattern to mirror in vdr-agent (HIGH confidence)
