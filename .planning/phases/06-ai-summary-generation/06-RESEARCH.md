# Phase 6: AI Summary Generation - Research

**Researched:** 2026-03-05
**Domain:** asyncio parallel AI calls, cross-schema PostgreSQL reads, Python async patterns
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Section grouping strategy:**
- Group consecutive chunks into fixed-size sections of 5 chunks each (ordered by `chunk_index`)
- If the document has fewer than 5 chunks total, the whole document is one section
- Do NOT rely on `metadata.chunk_type` for section boundaries — use `chunk_index` ordering only

**Section summary prompt:**
- System: "You are summarising a section of an ESG (Environmental, Social, Governance) corporate disclosure document. Extract the key findings, metrics, data points, and topics discussed in this section. Be concise and factual."
- User message: concatenated `content` of all chunks in the section, separated by `\n\n`

**Final combined summary prompt:**
- System: "You are writing a document summary for an ESG disclosure. Below are summaries of each section of the document. Combine them into a single coherent summary covering: (1) the document's main purpose and scope, (2) key ESG topics and metrics mentioned, (3) notable findings or data points. Write in clear, factual prose. 2–4 paragraphs."
- User message: all section summaries numbered and concatenated, e.g. `Section 1:\n{summary}\n\nSection 2:\n{summary}\n\n...`

**Parallel execution pattern:**
- Use `asyncio.gather(*section_tasks, return_exceptions=True)` — do NOT abort mid-gather on first error
- After gather: check results for exceptions — if any result is a `ClaudeClientError` or other exception, log all errors and raise
- Each section call wrapped in `async with get_rate_limiter().acquire():` before calling `invoke()`

**Error handling:**
- Any `ClaudeClientError` → `summary_status = 'failed'`, no retry
- `process_document()` catches at top level: `try/except Exception` → log, `await ProcessingStateDAO.update_status(ps_id, 'failed')`
- DB connections NOT held during Bedrock calls — fetch all chunks first (short-lived connection), close, then run AI calls, then write results (new short-lived connection)

**Chunk data access:**
- Use a simple inline query in `processor.py` — no separate DAO needed for Phase 6
- Query: `SELECT content, chunk_index FROM ai_rag.embeddings WHERE document_id = %s ORDER BY chunk_index`

### Claude's Discretion

- Exact section size can be configurable via `VDR_AGENT_SUMMARY_SECTION_SIZE` config field (default 5) — or hardcoded if simpler; planner decides
- Log format for per-section completion (DEBUG vs INFO)
- Whether to log elapsed time per document
- How to handle documents with 0 chunks (log warning, mark as failed or done)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROC-02 | System generates an AI summary per document (parallel section summaries → combined final summary) | Covered by: asyncio.gather pattern, invoke() + rate limiter wiring, DocumentSummaryDAO.upsert(), ProcessingStateDAO.update_status(), inline cross-schema query for embeddings |
</phase_requirements>

---

## Summary

Phase 6 replaces the stub body of `app/worker/processor.py::process_document()` with real AI logic. All infrastructure is already in place: `invoke()` (Bedrock wrapper), `get_rate_limiter()` (semaphore), `DocumentSummaryDAO.upsert()` (write results), and `ProcessingStateDAO.update_status()` (status bookkeeping). The only new read access needed is a plain `SELECT content, chunk_index FROM ai_rag.embeddings WHERE document_id = %s ORDER BY chunk_index` — the cross-schema access works because `search_path = vdr_agent, ai_rag, public` is set on every pool connection.

The core of the phase is one function: fetch chunks, partition into sections of 5, fire `asyncio.gather` for section summaries, combine into a final summary, persist. The `return_exceptions=True` pattern is mandatory — it ensures all semaphore slots are cleanly released even if some calls fail, before the error check raises and triggers the `failed` status path.

The only discretionary decision for the planner is whether `SUMMARY_SECTION_SIZE` becomes a config field or a module constant. Given the established config pattern (`get_settings()` singleton, `VDR_AGENT_` prefix), adding a config field is trivially cheap and consistent — but hardcoding 5 is also acceptable since it won't need tuning in v1.

**Primary recommendation:** Implement `process_document()` as a single cohesive function (~80 lines) with three clearly separated phases: (1) fetch + partition, (2) parallel section summarisation via gather, (3) combine + persist. Keep the inline query in processor.py per the CONTEXT.md decision.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncio` (stdlib) | Python 3.9 | Parallel task coordination via `gather` | Built-in; no dependency |
| `app.core.llm.claude_client.invoke` | existing | Single Bedrock call with async/thread offload | Already wired; callers just `await invoke()` |
| `app.core.llm.rate_limiter.get_rate_limiter` | existing | Semaphore cap (default 10) on concurrent Bedrock calls | Already wired; used as `async with get_rate_limiter().acquire():` |
| `app.db.dao.document_summary_dao.DocumentSummaryDAO` | existing | Upsert final summary to `vdr_agent.document_summaries` | Already built and tested in Phase 3 |
| `app.db.dao.processing_state_dao.ProcessingStateDAO` | existing | `update_status(ps_id, 'done'/'failed')` | Already built and tested in Phase 3 |
| `app.db.pool.DatabasePool` | existing | `async with DatabasePool.connection() as conn:` for the chunk fetch | Already wired in lifespan |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `app.config.get_settings` | existing | Optional: read `summary_section_size` if made configurable | If planner adds `VDR_AGENT_SUMMARY_SECTION_SIZE` config field |
| `logging` (stdlib) | Python 3.9 | Per-section and per-document progress logging | Always — follow established LOGGER pattern |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Inline SQL in processor.py | New EmbeddingDAO | DAO is cleaner but adds Phase 9 work; CONTEXT.md explicitly deferred this |
| `asyncio.gather(return_exceptions=True)` | `asyncio.TaskGroup` (Python 3.11+) | TaskGroup cancels sibling tasks on first error — wrong here; venv is Python 3.9 anyway |
| Hardcoded section size of 5 | `VDR_AGENT_SUMMARY_SECTION_SIZE` config field | Config field costs ~3 lines and aligns with project convention; either is valid |

**Installation:** No new packages required — all dependencies are already installed.

---

## Architecture Patterns

### Recommended Project Structure

Phase 6 touches exactly one file plus optionally one config file:

```
vdr-agent/
├── app/
│   ├── config/
│   │   └── __init__.py          # optional: add summary_section_size field
│   └── worker/
│       └── processor.py         # PRIMARY: replace stub body with real logic
```

### Pattern 1: Fetch-Then-Compute (DB connection discipline)

**What:** Open a DB connection, fetch all chunks, close the connection. Then run all Bedrock calls without any open DB connection. Then open a new connection to persist results.

**When to use:** Always — this is a project-wide invariant. Violating it causes connections to be held idle during multi-second Bedrock calls, exhausting the pool (max_size=10) when multiple documents process concurrently.

**Example:**
```python
# Source: app/db/pool.py DatabasePool pattern + CONTEXT.md decision
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.core.llm.claude_client import ClaudeClientError, invoke
from app.core.llm.rate_limiter import get_rate_limiter
from app.db.dao.document_summary_dao import DocumentSummaryDAO
from app.db.dao.processing_state_dao import ProcessingStateDAO
from app.db.pool import DatabasePool

LOGGER = logging.getLogger(__name__)
SUMMARY_SECTION_SIZE = 5  # or read from get_settings() if made configurable

SECTION_SYSTEM_PROMPT = (
    "You are summarising a section of an ESG (Environmental, Social, Governance) "
    "corporate disclosure document. Extract the key findings, metrics, data points, "
    "and topics discussed in this section. Be concise and factual."
)

COMBINE_SYSTEM_PROMPT = (
    "You are writing a document summary for an ESG disclosure. Below are summaries "
    "of each section of the document. Combine them into a single coherent summary "
    "covering: (1) the document's main purpose and scope, (2) key ESG topics and "
    "metrics mentioned, (3) notable findings or data points. "
    "Write in clear, factual prose. 2–4 paragraphs."
)


async def _summarise_section(section_chunks: list[str], section_index: int) -> str:
    """Summarise one section under the rate limiter."""
    user_message = "\n\n".join(section_chunks)
    async with get_rate_limiter().acquire():
        result = await invoke(user_message, system_prompt=SECTION_SYSTEM_PROMPT)
    LOGGER.debug("Section %d summary complete (%d chars)", section_index, len(result))
    return result


async def process_document(processing_state_id: UUID, document_id: UUID) -> None:
    # --- Phase 1: Fetch chunks (short-lived DB connection) ---
    sql = """
        SELECT content, chunk_index
        FROM ai_rag.embeddings
        WHERE document_id = %s
        ORDER BY chunk_index
    """
    try:
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (document_id,))
                rows = await cur.fetchall()
    except Exception:
        LOGGER.exception("Failed to fetch chunks for doc_id=%s", document_id)
        await ProcessingStateDAO.update_status(processing_state_id, "failed")
        return

    chunks = [row["content"] for row in rows]
    if not chunks:
        LOGGER.warning("No chunks found for doc_id=%s — marking failed", document_id)
        await ProcessingStateDAO.update_status(processing_state_id, "failed")
        return

    # --- Phase 2: Partition + parallel section summaries ---
    sections = [
        chunks[i : i + SUMMARY_SECTION_SIZE]
        for i in range(0, len(chunks), SUMMARY_SECTION_SIZE)
    ]

    try:
        section_tasks = [
            _summarise_section(section, idx) for idx, section in enumerate(sections)
        ]
        results = await asyncio.gather(*section_tasks, return_exceptions=True)

        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            for err in errors:
                LOGGER.error("Section summary failed: %s", err)
            raise errors[0]

        section_summaries: list[str] = results  # type: ignore[assignment]

        # --- Phase 3: Combine summaries ---
        numbered = "\n\n".join(
            f"Section {i + 1}:\n{s}" for i, s in enumerate(section_summaries)
        )
        async with get_rate_limiter().acquire():
            final_summary = await invoke(numbered, system_prompt=COMBINE_SYSTEM_PROMPT)

        # --- Phase 4: Persist (new short-lived DB connection) ---
        await DocumentSummaryDAO.upsert(document_id, final_summary)
        await ProcessingStateDAO.update_status(processing_state_id, "done")
        LOGGER.info("Summary complete: doc_id=%s sections=%d", document_id, len(sections))

    except Exception:
        LOGGER.exception("process_document failed: ps_id=%s doc_id=%s", processing_state_id, document_id)
        await ProcessingStateDAO.update_status(processing_state_id, "failed")
```

### Pattern 2: `asyncio.gather` with `return_exceptions=True`

**What:** Fire all coroutines concurrently and collect results — including exceptions — without cancelling siblings on first failure.

**When to use:** Whenever multiple independent async calls must all complete before a decision is made. Do NOT use `asyncio.TaskGroup` (Python 3.11+ only) or bare `asyncio.gather` without `return_exceptions=True` (raises immediately, leaving rate limiter semaphore slots un-released from other in-flight tasks).

**Why `return_exceptions=True` is critical here:** The `GlobalRateLimiter.acquire()` context manager uses an asyncio Semaphore. If a task is cancelled mid-execution after acquiring the semaphore but before `finally` releases it, the semaphore count is permanently decremented (Python 3.9 semaphore does call `release()` in the context manager's `finally` block, but cancellation during `await self._semaphore.acquire()` itself before yielding means the slot was never taken — so cancellation mid-gather could leave slots locked from tasks that were interrupted after acquire but before `yield`). Letting all tasks run to completion (success or exception) avoids any partial-release ambiguity. [Confidence: HIGH — verified in rate_limiter.py source; asynccontextmanager semantics ensure finally runs on normal exceptions but cancellation of the outer task can bypass finally.]

### Pattern 3: `from __future__ import annotations` header

**What:** Every module in vdr-agent must start with this import for Python 3.9 forward-reference compatibility.

**When to use:** Always — project-wide convention, enforced in Phase 1.

### Anti-Patterns to Avoid

- **Holding DB connection during Bedrock calls:** `async with DatabasePool.connection() as conn: [Bedrock call inside]` — exhausts pool when 5+ documents process concurrently. The pool has max_size=10 and Bedrock calls take 2-15 seconds.
- **`asyncio.gather` without `return_exceptions=True`:** Raises on first error and may cancel sibling tasks that have already acquired the rate limiter semaphore, potentially causing slot leaks.
- **`asyncio.TaskGroup` (Python 3.11+):** Not available in Python 3.9. venv is Python 3.9 (confirmed from Phase 1 decisions).
- **Calling `boto3.invoke_model` directly from `processor.py`:** All Bedrock calls must go through `invoke()` which handles `asyncio.to_thread()` offloading. Direct boto3 calls would block the event loop.
- **Creating a new EmbeddingDAO for this phase:** CONTEXT.md explicitly says to use an inline query in processor.py; a DAO can be added in Phase 9 if needed.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bedrock API call + thread offload | Custom boto3 wrapper | `invoke()` in `claude_client.py` | Already handles asyncio.to_thread, ClaudeClientError, stop_reason logging |
| Concurrency cap on Bedrock calls | Custom semaphore | `get_rate_limiter().acquire()` | Singleton, lazy init, loop-safe, already wired to bedrock_max_concurrent config |
| Persisting the final summary | Direct SQL in processor.py | `DocumentSummaryDAO.upsert()` | Already handles ON CONFLICT, commit, connection release |
| Status bookkeeping | Direct SQL in processor.py | `ProcessingStateDAO.update_status()` | Already handles commit and connection release |

**Key insight:** Phase 6 is purely orchestration — all primitives exist. The risk is in the wiring (connection discipline, gather semantics, error propagation), not in building new infrastructure.

---

## Common Pitfalls

### Pitfall 1: DB Connection Held Across Bedrock Calls

**What goes wrong:** Fetch chunks and Bedrock calls share one `async with DatabasePool.connection()` block. With 5 documents processing simultaneously (poll_batch_size=5), each holding a connection during 5-15 second Bedrock waits, the pool (max_size=10) is exhausted. New connections queue and timeout.

**Why it happens:** It feels natural to open one connection for the whole function. The explicit rule (from Phase 3 and Phase 4 decisions) is easy to miss.

**How to avoid:** Fetch chunks in a short-lived connection block, `await cur.fetchall()`, close. Then run all AI calls outside any connection block. Then open a new connection to call `DocumentSummaryDAO.upsert()`.

**Warning signs:** `psycopg_pool.PoolTimeout` exceptions; DB pool exhaustion logs; documents processing sequentially instead of concurrently.

### Pitfall 2: Using `asyncio.gather` Without `return_exceptions=True`

**What goes wrong:** If one section summary raises `ClaudeClientError`, `asyncio.gather` without `return_exceptions=True` re-raises immediately. Other section tasks are left running (not cancelled by default in Python's gather). The rate limiter semaphore slots for those tasks may still be held. The calling code cannot distinguish "some completed, some failed".

**Why it happens:** Default gather behaviour for single-exception propagation feels like "fail fast". For AI pipelines the better invariant is "collect all, then decide".

**How to avoid:** Always use `return_exceptions=True`. After gather, filter `isinstance(r, BaseException)` to find failures, log all of them, then raise the first.

**Warning signs:** Sporadic rate limiter deadlocks under load; semaphore count drifts below `bedrock_max_concurrent`.

### Pitfall 3: 0-Chunk Documents Causing Silent Hangs

**What goes wrong:** If a document has no embedding rows (embeddings pipeline failed without marking the document properly), the chunk list is empty. Section partitioning produces zero sections. `asyncio.gather()` with zero tasks returns `[]` immediately — `section_summaries` is `[]`. The combine call then invokes Claude with an empty user message, which returns a nonsense summary. It gets persisted as "done".

**Why it happens:** The 0-chunk edge case looks like a trivially valid input to the gather/combine logic.

**How to avoid:** Add an explicit guard: `if not chunks: log warning; update_status('failed'); return`. This is a Claude's Discretion item — planner chooses `'failed'` vs `'done'` — research recommends `'failed'` since there is nothing to summarise and Phase 7 (fitment) would receive a meaningless summary.

**Warning signs:** `document_summaries` rows with empty or boilerplate summary_text; no section summary logs for certain documents.

### Pitfall 4: `from __future__ import annotations` Missing

**What goes wrong:** `list[str]` type hints in Python 3.9 without this import cause `TypeError` at module load time.

**Why it happens:** Easy to forget when adding a new file or editing an existing one.

**How to avoid:** First line of every module (after `#` comments if any) must be `from __future__ import annotations`. Confirmed project convention from Phase 1.

### Pitfall 5: Rate Limiter Semaphore Not Wrapping `invoke()`

**What goes wrong:** Calling `await invoke()` directly without `async with get_rate_limiter().acquire():` bypasses the concurrency cap. Under load, this fires more than `bedrock_max_concurrent` (default 10) simultaneous Bedrock calls, risking 429 throttling. The Bedrock 200 RPM quota is shared with ingestion-service (noted in STATE.md blockers).

**How to avoid:** Every `invoke()` call must be inside `async with get_rate_limiter().acquire():`. The combine call (single call per document) still needs the gate — it fires concurrently with other documents' section summarisation tasks.

---

## Code Examples

### Embedding Chunk Fetch (Verified Pattern)

```python
# Source: ai_rag.embeddings schema from V3__documents_and_embeddings.sql
# search_path = vdr_agent, ai_rag, public — set in pool.py configure()
sql = """
    SELECT content, chunk_index
    FROM ai_rag.embeddings
    WHERE document_id = %s
    ORDER BY chunk_index
"""
async with DatabasePool.connection() as conn:
    async with conn.cursor() as cur:
        await cur.execute(sql, (document_id,))
        rows = await cur.fetchall()
chunks = [row["content"] for row in rows]
```

Note: `row_factory = dict_row` is configured on the pool (verified in `pool.py` line 67), so `row["content"]` and `row["chunk_index"]` work directly.

### Section Partitioning

```python
# Pure Python — no library needed
SUMMARY_SECTION_SIZE = 5
sections = [
    chunks[i : i + SUMMARY_SECTION_SIZE]
    for i in range(0, len(chunks), SUMMARY_SECTION_SIZE)
]
# 17 chunks → [[c0..c4], [c5..c9], [c10..c14], [c15..c16]]
# 3 chunks  → [[c0, c1, c2]]  (one section, whole doc)
```

### Parallel Section Summarisation

```python
# Source: CONTEXT.md parallel execution decision + rate_limiter.py pattern
async def _summarise_section(section_chunks: list[str], section_index: int) -> str:
    user_message = "\n\n".join(section_chunks)
    async with get_rate_limiter().acquire():
        result = await invoke(user_message, system_prompt=SECTION_SYSTEM_PROMPT)
    LOGGER.debug("Section %d summary complete", section_index)
    return result

section_tasks = [
    _summarise_section(section, idx) for idx, section in enumerate(sections)
]
results = await asyncio.gather(*section_tasks, return_exceptions=True)

errors = [r for r in results if isinstance(r, BaseException)]
if errors:
    for err in errors:
        LOGGER.error("Section summary error: %s", err)
    raise errors[0]

section_summaries: list[str] = results  # type: ignore[assignment]
```

### Combined Summary Call

```python
# Source: CONTEXT.md combine prompt decision
numbered = "\n\n".join(
    f"Section {i + 1}:\n{s}" for i, s in enumerate(section_summaries)
)
async with get_rate_limiter().acquire():
    final_summary = await invoke(numbered, system_prompt=COMBINE_SYSTEM_PROMPT)
```

### Error Handler (Top-Level)

```python
# Wraps entire AI processing block
try:
    # ... partition, gather, combine, persist ...
except Exception:
    LOGGER.exception(
        "process_document failed: ps_id=%s doc_id=%s",
        processing_state_id,
        document_id,
    )
    await ProcessingStateDAO.update_status(processing_state_id, "failed")
```

### Optional Config Field

```python
# Source: app/config/__init__.py Settings class pattern
summary_section_size: int = Field(
    default=5,
    description="Number of embedding chunks per summary section — override with VDR_AGENT_SUMMARY_SECTION_SIZE",
)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `asyncio.TaskGroup` (Python 3.11+) | `asyncio.gather(return_exceptions=True)` | N/A — venv is Python 3.9 | TaskGroup would cancel siblings on first error; gather collects all |
| Raw boto3 calls | `asyncio.to_thread(_call)` inside `invoke()` | Phase 4 | Frees event loop during blocking network I/O |

**Deprecated/outdated:**
- Direct psycopg2 sync connections: not used anywhere in vdr-agent; all connections are psycopg3 AsyncConnectionPool.
- `asyncio.ensure_future()`: replaced by `asyncio.create_task()` in modern Python; not needed here anyway (gather handles task scheduling).

---

## Open Questions

1. **0-chunk document handling: `failed` or `done`?**
   - What we know: CONTEXT.md marks this as Claude's Discretion
   - What's unclear: Phase 7 (fitment) will call `process_document` output; a 'done' document with no summary would produce nonsense fitment results
   - Recommendation: Mark `failed` — it signals the embeddings pipeline didn't produce usable data and prevents Phase 7 from generating meaningless fitment evaluations

2. **Should `SUMMARY_SECTION_SIZE` be a config field or a constant?**
   - What we know: CONTEXT.md marks this as Claude's Discretion; config field costs ~3 lines following established pattern
   - What's unclear: Whether operational teams will ever want to tune this without a code deploy
   - Recommendation: Add `summary_section_size` config field (default 5, `VDR_AGENT_SUMMARY_SECTION_SIZE` env var) — consistent with existing tunable fields (`poll_batch_size`, `bedrock_max_concurrent`, etc.); trivial cost

3. **Bedrock quota contention with ingestion-service**
   - What we know: STATE.md documents this as a post-Phase-6 concern; 200 RPM shared; vdr-agent GlobalRateLimiter caps at 10 concurrent calls within the service
   - What's unclear: At full load (5 docs × (N sections + 1 combine) calls simultaneously), actual RPM could be high
   - Recommendation: No action in Phase 6; the concern is documented in STATE.md and assigned post-Phase-6

---

## Sources

### Primary (HIGH confidence)

- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/core/llm/claude_client.py` — `invoke()` signature, `ClaudeClientError`, `asyncio.to_thread` pattern
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/core/llm/rate_limiter.py` — `GlobalRateLimiter`, `acquire()` asynccontextmanager, semaphore lifecycle
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/db/dao/document_summary_dao.py` — `upsert()` signature and connection discipline
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/db/dao/processing_state_dao.py` — `update_status()` signature and connection discipline
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/db/pool.py` — `DatabasePool.connection()`, `dict_row` factory, `search_path` configuration
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/worker/processor.py` — stub to replace; fixed signature `process_document(processing_state_id, document_id) -> None`
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/config/__init__.py` — Settings class, `VDR_AGENT_` prefix convention, `get_settings()` singleton
- `/Users/sanchayjain/Desktop/ERM/ingestion-service/migrations/flyway/V3__documents_and_embeddings.sql` — `ai_rag.embeddings` table schema: columns `content`, `chunk_index`, `document_id`, `metadata`
- `.planning/phases/06-ai-summary-generation/06-CONTEXT.md` — all locked decisions and discretion areas

### Secondary (MEDIUM confidence)

- `.planning/STATE.md` — accumulated project decisions (Python 3.9 venv, `from __future__ import annotations`, 50-thread executor, pool max_size=10, Bedrock quota concern)
- `.planning/REQUIREMENTS.md` — PROC-02 requirement definition
- `.planning/ROADMAP.md` — Phase 6 success criteria

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are existing code read directly from source
- Architecture: HIGH — patterns derived from existing DAOs and verified against pool/client source
- Pitfalls: HIGH — connection discipline, gather semantics, and 0-chunk edge case verified against actual source code and established project decisions
- Prompts: HIGH — verbatim from CONTEXT.md locked decisions

**Research date:** 2026-03-05
**Valid until:** 2026-04-04 (stable — no external dependencies being introduced)
