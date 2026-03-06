# Phase 6: AI Summary Generation - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the `process_document()` stub in `app/worker/processor.py` with real AI logic:
1. Fetch all `ai_rag.embeddings` rows for the document (ordered by `chunk_index`)
2. Partition chunks into sections for parallel summarisation
3. Generate section summaries in parallel via `invoke()` + `GlobalRateLimiter`
4. Call `invoke()` once more to combine section summaries into a final document summary
5. Write final summary to `vdr_agent.document_summaries` via `DocumentSummaryDAO.upsert()`
6. Set `summary_status = 'done'` on success; `'failed'` on any `ClaudeClientError`

No new DAOs, no new DB tables, no API endpoints in this phase — pure AI processing logic inside the worker.

</domain>

<decisions>
## Implementation Decisions

### Section grouping strategy
- Group consecutive chunks into fixed-size sections of **5 chunks each** (ordered by `chunk_index`)
- If the document has fewer than 5 chunks total, the whole document is one section
- Rationale: balances granularity vs. API call count; prevents sending single tiny chunks while avoiding context overload per call
- The `metadata.chunk_type` field may not be consistently populated across all ingested documents — do not rely on it for section boundaries; use `chunk_index` ordering only

### Section summary prompt
- **ESG-aware system prompt** for section summaries:
  - Instruction: "You are summarising a section of an ESG (Environmental, Social, Governance) corporate disclosure document. Extract the key findings, metrics, data points, and topics discussed in this section. Be concise and factual."
  - User message: the concatenated `content` text of all chunks in the section, separated by `\n\n`
- Rationale: these summaries feed into fitment evaluation (Phase 7); ESG-aware framing improves relevance signal

### Final combined summary prompt
- **ESG-aware system prompt** for the combination call:
  - Instruction: "You are writing a document summary for an ESG disclosure. Below are summaries of each section of the document. Combine them into a single coherent summary covering: (1) the document's main purpose and scope, (2) key ESG topics and metrics mentioned, (3) notable findings or data points. Write in clear, factual prose. 2–4 paragraphs."
  - User message: all section summaries numbered and concatenated, e.g. `Section 1:\n{summary}\n\nSection 2:\n{summary}\n\n...`
- Output is stored as-is in `document_summaries.summary_text`

### Parallel execution pattern
- Use `asyncio.gather(*section_tasks, return_exceptions=True)` to collect all section summary results
- After gather: check results for exceptions — if **any** result is a `ClaudeClientError` or other exception, log all errors and raise (triggering `failed` status)
- Do NOT abort mid-gather on first error — let all tasks complete, then check; this avoids leaving rate limiter slots locked by cancelled tasks
- Each section call wrapped in `async with get_rate_limiter().acquire():` before calling `invoke()`

### Error handling
- Locked from Phase 4: any `ClaudeClientError` → `summary_status = 'failed'`, no retry
- `process_document()` catches exception at the top level:  `try/except Exception` → log, `await ProcessingStateDAO.update_status(ps_id, 'failed')`
- DB connections are NOT held during Bedrock calls — fetch all chunks first (short-lived connection), close, then run AI calls, then write results (new short-lived connection)

### Claude's Discretion
- Exact number of chunks per section can be configurable via a new `VDR_AGENT_SUMMARY_SECTION_SIZE` config field (default 5) — or hardcoded if simpler; planner decides
- Log format for per-section completion (DEBUG vs INFO)
- Whether to log elapsed time per document
- How to handle documents with 0 chunks (log warning, mark as failed or done)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/core/llm/claude_client.invoke(prompt, system_prompt)` — ready; call with `async with get_rate_limiter().acquire():`
- `app/core/llm/rate_limiter.get_rate_limiter()` — singleton, max 10 concurrent Bedrock calls
- `app/db/dao/document_summary_dao.DocumentSummaryDAO.upsert(document_id, summary_text)` — ready; commits and releases connection
- `app/db/dao/processing_state_dao.ProcessingStateDAO.update_status(ps_id, status)` — ready; short-lived commit
- `app/db/pool.DatabasePool.connection()` — `async with DatabasePool.connection() as conn:` pattern for all DB access
- `app/worker/processor.py` — the stub to replace; function signature `async def process_document(processing_state_id: UUID, document_id: UUID) -> None` must not change

### Established Patterns
- `from __future__ import annotations` at top of every module (Python 3.9)
- Short-lived DB connections: open → execute → commit → close. Never hold across Bedrock calls.
- `asyncio.to_thread()` handles sync boto3 inside `invoke()` — callers just `await invoke()`
- Config via `get_settings()` singleton; new fields follow `VDR_AGENT_` prefix

### Integration Points
- `ai_rag.embeddings` table (cross-schema read): `SELECT content, chunk_index FROM ai_rag.embeddings WHERE document_id = %s ORDER BY chunk_index` — needs a new read method (EmbeddingDAO or inline query in processor.py)
- `app/worker/processor.py` — single file to replace; poller.py unchanged
- `app/config/__init__.py` — optional: add `VDR_AGENT_SUMMARY_SECTION_SIZE` config field

</code_context>

<specifics>
## Specific Ideas

- Fetch chunks using a simple inline query in `processor.py` (no separate DAO needed for Phase 6) — keeps the change self-contained; Phase 9 can add a proper read DAO if needed
- `asyncio.gather` with `return_exceptions=True` is the right pattern here: avoids cancellation side-effects on the rate limiter semaphore

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-ai-summary-generation*
*Context gathered: 2026-03-05*
