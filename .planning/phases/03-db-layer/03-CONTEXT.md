# Phase 3: DB Layer - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

All database access for vdr-agent centralised in async DAOs that use a shared `AsyncConnectionPool` singleton. No direct connection management scattered across business logic code (polling loop, API routes). Pure infrastructure layer — no AI calls, no HTTP endpoints in this phase.

</domain>

<decisions>
## Implementation Decisions

### Pool singleton design
- Write a **vdr-agent-specific `DatabasePool`** — do NOT copy ingestion-service pool verbatim
- The ingestion-service pool has multi-platform complexity (ERM, VDR, registry) that vdr-agent does not need
- vdr-agent pool: single `AsyncConnectionPool`, `psycopg_pool`, `dict_row` row factory
- `search_path = vdr_agent, ai_rag, public` — vdr_agent first (owns its tables), ai_rag second (poll queries cross-schema to `ai_rag.documents`)
- No pgvector registration needed — vdr-agent never reads embedding vectors directly
- Pool sizing: min=2, max=10 (vdr-agent has lower concurrency than ingestion-service; Bedrock calls happen outside connections)
- Single class method `DatabasePool.connection()` as `@asynccontextmanager` — same API surface as ingestion-service for consistency

### DAO class style
- **Static async class methods** matching `AsyncProjectDAO` / `AsyncDocumentDAO` pattern in `ingestion-service/app/db/dao/async_dao.py`
- Each method opens its own `async with DatabasePool.connection() as conn` — short-lived connections
- No FastAPI `Depends()` injection for DAOs — DAOs are called directly from polling loop and route handlers
- FastAPI `Depends(get_db_connection)` pattern is NOT used — it adds indirection that complicates the polling loop (which is not a request handler)

### SKIP LOCKED transaction scope
- `ProcessingStateDAO.claim_documents(limit: int)` does the full claim atomically:
  1. `SELECT id, document_id FROM vdr_agent.processing_state WHERE summary_status IN ('pending', 'failed') ... FOR UPDATE SKIP LOCKED LIMIT {limit}`
  2. `UPDATE ... SET summary_status='processing', processing_started_at=NOW() WHERE id = ANY(%s)`
  3. COMMIT — all within a single `async with pool.connection()` block
- Returns list of claimed `(processing_state_id, document_id)` tuples — poller uses these to drive Bedrock calls
- Subsequent status updates (`update_status('done' | 'failed')`) are separate short transactions — no long-held connection across Bedrock calls

### Return types
- **Dataclasses** for all DAO return values — matching `DocumentRecord` pattern in ingestion-service
- One dataclass per table row type: `TopicRecord`, `ProcessingStateRecord`, `DocumentSummaryRecord`, `FitmentResultRecord`
- `@classmethod from_row(cls, row: dict) -> "XRecord"` factory on each — safe dict access
- Plain `UUID` or `None` for write operations that only need the created ID

### Stale-lock recovery
- `ProcessingStateDAO.reset_stale_claims(threshold_minutes: int)` — separate method, called at start of each poll cycle
- Updates rows WHERE `summary_status = 'processing'` AND `processing_started_at < NOW() - interval '{threshold_minutes} minutes'` → `summary_status = 'pending'`, `processing_started_at = NULL`
- Short transaction, no SKIP LOCKED needed (safe to update stale rows regardless of other workers)

### Claude's Discretion
- Exact pool connection timeout and keepalive values
- Whether to expose `DatabasePool.close()` as a class method or module-level function
- Logger naming convention for each DAO module
- Whether to add a `DatabasePool.health_check()` method for the `/health` endpoint

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ingestion-service/app/db/pool.py` → `DatabasePool` class: Copy `__new__`, `initialize()`, `connection()`, `close()` skeleton — strip multi-platform (`_pools` dict, `platform` param, registry fallback) and replace with single `_pool: AsyncConnectionPool | None`
- `ingestion-service/app/db/dao/async_dao.py` → `AsyncProjectDAO` / `AsyncDocumentDAO`: Direct model for DAO structure — static methods, `async with DatabasePool.connection() as conn`, `async with conn.cursor() as cur`, `await conn.commit()`
- `ingestion-service/app/db/dao/document_dao.py` → `DocumentRecord` + `from_row()`: Copy the dataclass + factory pattern verbatim for vdr-agent record types
- `ingestion-service/app/startup.py` → `await DatabasePool.initialize(...)` in lifespan startup, `await DatabasePool.close()` in lifespan shutdown

### Established Patterns
- `from __future__ import annotations` at top of every module (Python 3.9 union syntax requirement)
- `psycopg_pool.AsyncConnectionPool` with `open=False` then `await pool.open()` — matches ingestion-service pool init
- `kwargs={"row_factory": dict_row}` on pool constructor — all cursor results are dicts
- `async with conn.cursor() as cur:` then `await cur.execute(sql, params)` then `await conn.commit()` — standard async psycopg3 pattern
- UUIDs passed as `UUID` objects (not strings) to psycopg3 — it handles the cast natively

### Integration Points
- `app/startup.py` (vdr-agent lifespan) — add `await DatabasePool.initialize(...)` in startup, `await DatabasePool.close()` in shutdown (already exists from Phase 1 scaffold; just add DB pool calls)
- Phase 5 (Polling Loop) — calls `ProcessingStateDAO.claim_documents()`, `ProcessingStateDAO.reset_stale_claims()`, `ProcessingStateDAO.update_status()`
- Phase 6 (AI Summary) — calls `DocumentSummaryDAO.upsert()`, `ProcessingStateDAO.update_status('done' | 'failed')`
- Phase 7 (Fitment) — calls `FitmentResultDAO.upsert()` (ON CONFLICT DO UPDATE, using `fitment_results_doc_topic_unique` constraint name)
- Phase 8 (Topic CRUD API) — calls `TopicDAO.insert()`, `TopicDAO.list_by_project()`, `TopicDAO.update()`, `TopicDAO.delete()`
- Phase 9 (Results API) — calls `DocumentSummaryDAO.get_by_document()`, `FitmentResultDAO.list_by_document()`, `ProcessingStateDAO.get_by_document()`

</code_context>

<specifics>
## Specific Ideas

- `search_path = vdr_agent, ai_rag, public` is critical — poll-claim query will JOIN against `ai_rag.documents` to filter documents with `embedding_status = 'completed'`; without ai_rag in path, queries need fully-qualified `ai_rag.documents` everywhere
- No connection is held open during Bedrock calls — this is a hard constraint from Phase 1 decisions; each DAO method must commit and release before returning to caller
- The `fitment_results_doc_topic_unique` UNIQUE constraint name is already locked (from Phase 2) — `FitmentResultDAO.upsert()` must reference it by that exact name in `ON CONFLICT ON CONSTRAINT fitment_results_doc_topic_unique`

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-db-layer*
*Context gathered: 2026-03-05*
