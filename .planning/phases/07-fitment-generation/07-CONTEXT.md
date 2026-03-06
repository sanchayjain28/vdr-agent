# Phase 7: Fitment Generation - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Extend `process_document()` in `app/worker/processor.py` to run fitment evaluations after the AI summary is complete. For each active topic in the document's project, call Claude with the AI summary + top-5 semantically relevant chunks + topic instruction, and upsert the result into `vdr_agent.fitment_results`. No new API endpoints, no schema changes, no new tables.

`processing_state.summary_status = 'done'` continues to mean **summary complete** (set by Phase 6, unchanged). Fitment is completely independent — tracked entirely in `fitment_results` rows.

</domain>

<decisions>
## Implementation Decisions

### Pipeline structure
- **Option A — same invocation**: `process_document()` runs summary → sets `summary_status = 'done'` → immediately runs fitment for all active topics → writes results to `fitment_results`
- Fitment runs in the same poller invocation, sequentially after summary completion
- Single poller, no second polling mechanism needed
- **Skip fitment if document already has a summary**: if `document_summaries` already has a row for this `document_id`, skip the summary generation step and proceed directly to fitment (avoids re-generating summaries on re-runs)

### project_id sourcing
- Fetch inline from `ai_rag.documents WHERE id = document_id` — short-lived DB connection, no signature change to `process_document(processing_state_id, document_id)`
- No changes to poller.py

### Topic filtering
- Evaluate **active topics only** (`WHERE is_active = true`)
- Add `TopicDAO.list_active_by_project(project_id)` — new DAO method with `WHERE project_id = %s AND is_active = true` (DB-level filter, not Python filter)
- If no active topics exist for the project, log a warning and skip fitment (no fitment_results rows created)

### Fitment prompt design — per-topic Claude call
- **Input context**: AI summary text + top-5 semantically relevant embedding chunks + topic instruction
- **Chunk selection**: embed `"{topic.name}: {topic.instruction}"` as the query, run cosine similarity search against `ai_rag.embeddings` for the document, retrieve top 5 chunks — one embedding call per topic via Bedrock (same `invoke()` pattern or a dedicated embedding call)
- **Prompt structure**:
  - System prompt: evaluator role + output format instruction ("You are an ESG analyst evaluating document relevance to a specific topic. Assess whether the document contains meaningful information about this topic. Provide a concise paragraph explaining your finding.")
  - User message: AI summary block → top-5 relevant chunks → topic instruction as the evaluation directive

### Parallel execution
- Fire all active topic fitment calls via `asyncio.gather(*topic_tasks, return_exceptions=True)` — same pattern as Phase 6 section summaries
- Each call wrapped in `async with get_rate_limiter().acquire():` before `invoke()`
- `return_exceptions=True` — all tasks run to completion; rate limiter slots cleanly released even on failure
- No DB connection held during any Bedrock call (short-lived connection for chunk fetch, released before AI calls)

### Per-topic failure handling
- If a topic's Bedrock call raises `ClaudeClientError` or any exception:
  - Upsert `fitment_results` row with `status='failed'`, `reasoning=None`
  - Other topics continue unaffected — do NOT abort the gather
- `processing_state.summary_status` is **not updated** by Phase 7 at all — it remains `'done'` (set by Phase 6 after summary)
- Per-topic outcomes are the sole responsibility of `fitment_results.status`

### processing_state — no changes
- `summary_status = 'done'` = AI summary complete. Set by Phase 6. Phase 7 does not touch `processing_state`.
- Fitment outcomes live entirely in `fitment_results` — one row per `(document_id, topic_id)` with own `status` and `reasoning`
- No schema migration needed

### Claude's Discretion
- How to obtain embeddings for topic query text (same Bedrock embedding model as ingestion-service, or a lightweight encode via the existing `invoke()` approach)
- Exact log format for per-topic completion (DEBUG vs INFO)
- Whether to batch the chunk-fetch queries (one query fetching top-5 per topic) or a single multi-topic query
- How to handle the case where `ai_rag.embeddings` has no vector column available (fallback to first-N chunks)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/worker/processor.py` — `process_document()` is the file to extend; fitment logic added after `DocumentSummaryDAO.upsert()` and `ProcessingStateDAO.update_status('done')`
- `app/core/llm/claude_client.invoke(prompt, system_prompt)` — ready; same call used for fitment as for summaries
- `app/core/llm/rate_limiter.get_rate_limiter()` — singleton, max 10 concurrent; wrap each topic call with `async with get_rate_limiter().acquire():`
- `app/db/dao/fitment_result_dao.FitmentResultDAO.upsert(document_id, topic_id, reasoning, status)` — ready with `ON CONFLICT ON CONSTRAINT fitment_results_doc_topic_unique DO UPDATE`
- `app/db/dao/topic_dao.TopicDAO.list_by_project(project_id)` — exists; Phase 7 adds `list_active_by_project(project_id)` alongside it
- `app/db/pool.DatabasePool.connection()` — `async with DatabasePool.connection() as conn:` pattern; must close before any Bedrock calls

### Established Patterns
- `from __future__ import annotations` at top of every module (Python 3.9)
- Short-lived DB connections: open → execute → close. Never held during Bedrock calls.
- `asyncio.gather(*tasks, return_exceptions=True)` for parallel AI calls (Phase 6)
- `async with get_rate_limiter().acquire(): result = await invoke(...)` wrapping every Bedrock call
- Config via `get_settings()` singleton; `VDR_AGENT_` prefix for new env vars

### Integration Points
- `app/worker/processor.py` — single file to extend; poller.py and signature unchanged
- `app/db/dao/topic_dao.py` — add `list_active_by_project()` method
- `ai_rag.documents` — cross-schema SELECT for `project_id`; works via existing `search_path = vdr_agent, ai_rag, public`
- `ai_rag.embeddings` — cross-schema vector similarity search for top-5 chunks per topic; pgvector `<=>` operator

</code_context>

<specifics>
## Specific Ideas

- Fitment runs immediately after summary in the same `process_document()` call — no second poller, no separate trigger
- Skip documents that already have a summary in `document_summaries` (re-run safety — go straight to fitment)
- The `fitment_results_doc_topic_unique` constraint (Phase 2) means re-runs are safe — `ON CONFLICT DO UPDATE` overwrites previous failed/partial results

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 07-fitment-generation*
*Context gathered: 2026-03-05*
