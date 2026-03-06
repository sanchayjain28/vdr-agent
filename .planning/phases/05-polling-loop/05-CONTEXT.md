# Phase 5: Polling Loop - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Autonomous background asyncio task that: (1) detects newly-embedded documents in `ai_rag.documents`, (2) registers them in `vdr_agent.processing_state`, (3) atomically claims them via FOR UPDATE SKIP LOCKED, and (4) hands them off to a processor stub. No AI calls in this phase — just the polling loop infrastructure. Phase 6 fills in the actual AI processing.

</domain>

<decisions>
## Implementation Decisions

### Document detection strategy
- **Two-step approach**: First detect new documents from `ai_rag.documents`, then insert + claim
  1. Query `ai_rag.documents WHERE embedding_status = 'completed' AND id NOT IN (SELECT document_id FROM vdr_agent.processing_state)` to find unregistered docs
  2. Call `ProcessingStateDAO.insert(document_id)` for each new doc — reuses existing `ON CONFLICT DO NOTHING` idempotency
  3. Call `ProcessingStateDAO.claim_documents(limit)` to atomically claim pending/failed rows
- Detection query must cross-schema (ai_rag → vdr_agent) — works because `search_path = vdr_agent, ai_rag, public` is set on the connection pool
- New detection query goes in a new method `ProcessingStateDAO.find_unregistered_documents(limit: int) -> List[UUID]` — returns document_ids not yet in processing_state

### Batch concurrency model
- **Fire-and-forget with `asyncio.create_task`** per claimed document
- Poll loop does NOT await processing — each document gets its own task
- Poll loop stores task references to prevent GC and add done callbacks for logging
- `GlobalRateLimiter` (max 10 concurrent Bedrock calls) naturally throttles throughput across all in-flight tasks
- Next poll cycle can start while previous batch documents are still processing (maximises throughput for 1000+ docs)

### Phase 5 processor stub
- Create `app/worker/processor.py` with `async def process_document(processing_state_id: UUID, document_id: UUID) -> None`
- Phase 5 stub: log receipt, then set `summary_status = 'done'` via `ProcessingStateDAO.update_status()` — simulates a completed document so the poll loop can be tested end-to-end
- Phase 6 replaces the stub body with real AI logic — poller.py interface stays unchanged
- Poller calls: `asyncio.create_task(process_document(ps_id, doc_id))`

### Poller module structure
- New directory `app/worker/` for background task modules
- `app/worker/poller.py` — `async def run_poller() -> None` coroutine with poll loop
- `app/worker/processor.py` — `async def process_document(processing_state_id, document_id)` stub
- Wired into `startup.py` lifespan: `task = asyncio.create_task(run_poller())` before `yield`; task stored and cancelled in shutdown with `task.cancel(); await task`
- Done callback: `task.add_done_callback(lambda t: logger.info("poller task exited: %s", t.exception() or 'clean'))`

### Config fields
- Three new fields added to `app/config/__init__.py`:
  - `poll_interval_seconds: int = 10` — env var `VDR_AGENT_POLL_INTERVAL_SECONDS`
  - `poll_batch_size: int = 5` — env var `VDR_AGENT_POLL_BATCH_SIZE`
  - `stale_lock_threshold_minutes: int = 30` — env var `VDR_AGENT_STALE_LOCK_THRESHOLD_MINUTES`
- Consistent with existing `VDR_AGENT_` prefix pattern; each tunable independently

### Poll cycle logic
Each poll cycle in order:
1. `reset_stale_claims(threshold_minutes)` — reset stuck rows from crashed workers
2. `find_unregistered_documents(limit)` — detect new docs from ai_rag
3. `ProcessingStateDAO.insert(doc_id)` for each new doc — register them
4. `claim_documents(limit)` — atomically claim pending/failed rows
5. `asyncio.create_task(process_document(ps_id, doc_id))` for each claimed doc
6. `await asyncio.sleep(poll_interval_seconds)`

If no documents claimed, sleep as normal — no busy-wait.

### Claude's Discretion
- Exact log format and log levels for each poll cycle step
- Whether to log "no documents found" at DEBUG vs INFO
- Task reference storage mechanism (module-level list vs set)
- Whether `find_unregistered_documents` is on `ProcessingStateDAO` or a standalone query in poller.py

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/db/dao/processing_state_dao.py` → `ProcessingStateDAO.claim_documents(limit)`: Already implemented — claims pending/failed rows atomically with FOR UPDATE SKIP LOCKED. Phase 5 calls this directly.
- `app/db/dao/processing_state_dao.py` → `ProcessingStateDAO.reset_stale_claims(threshold_minutes)`: Already implemented — Phase 5 calls at start of each poll cycle.
- `app/db/dao/processing_state_dao.py` → `ProcessingStateDAO.insert(document_id)`: Already implemented with ON CONFLICT DO NOTHING — Phase 5 calls for each newly-detected document.
- `app/startup.py` → has comment `# Phase 5 will add document poller task here` — exact insertion point is clear

### Established Patterns
- `from __future__ import annotations` at top of every module (Python 3.9)
- `async with DatabasePool.connection() as conn` for all DB access — short-lived connections, never held during Bedrock calls
- Static async class methods on DAOs
- Config via `get_settings()` singleton
- `asyncio.create_task()` used for background work (established in startup.py executor pattern)

### Integration Points
- `app/startup.py` — add poller task start/stop in lifespan (before `yield` for start, after for cancel+await)
- `app/config/__init__.py` — add 3 new Settings fields for poll timing
- `app/db/pool.py` — `search_path = vdr_agent, ai_rag, public` already set; cross-schema queries work natively
- Phase 6 — replaces `app/worker/processor.py` stub body with real AI summary logic; interface `process_document(processing_state_id, document_id)` stays the same
- `ai_rag.documents` table — Phase 5 reads `embedding_status` column; must confirm exact column name and 'completed' value (matches ingestion-service convention)

</code_context>

<specifics>
## Specific Ideas

- The partial index `idx_processing_state_pending_failed` from Phase 2 covers `WHERE summary_status IN ('pending', 'failed')` — the `claim_documents()` query already uses this exact predicate, so it's index-hot
- `find_unregistered_documents()` needs a `LIMIT` to bound the INSERT loop — use `poll_batch_size` as the cap so we don't register thousands at once
- Phase 5 processor stub should update status to `'done'` (not leave as `'processing'`) so stale-lock recovery doesn't reset it on the next cycle during testing

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-polling-loop*
*Context gathered: 2026-03-05*
