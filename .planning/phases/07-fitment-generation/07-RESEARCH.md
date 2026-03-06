# Phase 7: Fitment Generation - Research

**Researched:** 2026-03-05
**Domain:** Python async pipeline extension — pgvector cosine similarity, Bedrock embedding API, per-topic parallel Claude invocation
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Pipeline structure
- **Option A — same invocation**: `process_document()` runs summary → sets `summary_status = 'done'` → immediately runs fitment for all active topics → writes results to `fitment_results`
- Fitment runs in the same poller invocation, sequentially after summary completion
- Single poller, no second polling mechanism needed
- **Skip fitment if document already has a summary**: if `document_summaries` already has a row for this `document_id`, skip the summary generation step and proceed directly to fitment (avoids re-generating summaries on re-runs)

#### project_id sourcing
- Fetch inline from `ai_rag.documents WHERE id = document_id` — short-lived DB connection, no signature change to `process_document(processing_state_id, document_id)`
- No changes to poller.py

#### Topic filtering
- Evaluate **active topics only** (`WHERE is_active = true`)
- Add `TopicDAO.list_active_by_project(project_id)` — new DAO method with `WHERE project_id = %s AND is_active = true` (DB-level filter, not Python filter)
- If no active topics exist for the project, log a warning and skip fitment (no fitment_results rows created)

#### Fitment prompt design — per-topic Claude call
- **Input context**: AI summary text + top-5 semantically relevant embedding chunks + topic instruction
- **Chunk selection**: embed `"{topic.name}: {topic.instruction}"` as the query, run cosine similarity search against `ai_rag.embeddings` for the document, retrieve top 5 chunks — one embedding call per topic via Bedrock (same `invoke()` pattern or a dedicated embedding call)
- **Prompt structure**:
  - System prompt: evaluator role + output format instruction ("You are an ESG analyst evaluating document relevance to a specific topic. Assess whether the document contains meaningful information about this topic. Provide a concise paragraph explaining your finding.")
  - User message: AI summary block → top-5 relevant chunks → topic instruction as the evaluation directive

#### Parallel execution
- Fire all active topic fitment calls via `asyncio.gather(*topic_tasks, return_exceptions=True)` — same pattern as Phase 6 section summaries
- Each call wrapped in `async with get_rate_limiter().acquire():` before `invoke()`
- `return_exceptions=True` — all tasks run to completion; rate limiter slots cleanly released even on failure
- No DB connection held during any Bedrock call (short-lived connection for chunk fetch, released before AI calls)

#### Per-topic failure handling
- If a topic's Bedrock call raises `ClaudeClientError` or any exception:
  - Upsert `fitment_results` row with `status='failed'`, `reasoning=None`
  - Other topics continue unaffected — do NOT abort the gather
- `processing_state.summary_status` is **not updated** by Phase 7 at all — it remains `'done'` (set by Phase 6 after summary)
- Per-topic outcomes are the sole responsibility of `fitment_results.status`

#### processing_state — no changes
- `summary_status = 'done'` = AI summary complete. Set by Phase 6. Phase 7 does not touch `processing_state`.
- Fitment outcomes live entirely in `fitment_results` — one row per `(document_id, topic_id)` with own `status` and `reasoning`
- No schema migration needed

### Claude's Discretion
- How to obtain embeddings for topic query text (same Bedrock embedding model as ingestion-service, or a lightweight encode via the existing `invoke()` approach)
- Exact log format for per-topic completion (DEBUG vs INFO)
- Whether to batch the chunk-fetch queries (one query fetching top-5 per topic) or a single multi-topic query
- How to handle the case where `ai_rag.embeddings` has no vector column available (fallback to first-N chunks)

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROC-03 | System generates a fitment evaluation per active topic per document (uses AI summary + relevant sections + topic instruction) | Full pipeline documented: embedding-based chunk selection via pgvector, parallel topic invocations via asyncio.gather, FitmentResultDAO.upsert with ON CONFLICT, re-run safety via existing constraint |
</phase_requirements>

---

## Summary

Phase 7 extends `process_document()` in `app/worker/processor.py` to append a fitment generation pipeline after the AI summary is complete. The extension adds three new logical blocks: (1) project_id fetch from `ai_rag.documents`, (2) topic list fetch via a new `TopicDAO.list_active_by_project()` method, (3) per-topic parallel Bedrock calls using pgvector cosine similarity to select the top-5 most relevant chunks per topic. All of this reuses already-established patterns from Phase 6 — `asyncio.gather(return_exceptions=True)`, `get_rate_limiter().acquire()`, short-lived DB connections, and `FitmentResultDAO.upsert()`. No new infrastructure, no new tables, no changes to poller.py.

**Critical schema conflict discovered during research:** `vdr_agent.fitment_results.reasoning` is defined as `TEXT NOT NULL` in V5 migration, but `FitmentResultDAO.upsert()` accepts `reasoning: Optional[str]` and writes `None` for failed topics. A `reasoning=None` upsert will raise a PostgreSQL NOT NULL violation at runtime. The DAO was written in anticipation of Phase 7's failure-handling decision (which wants `NULL` reasoning for failed rows). This requires a V7 migration to `ALTER COLUMN reasoning DROP NOT NULL` before fitment generation is run.

The embedding approach for chunk selection is the key new capability. The ingestion-service uses `cohere.embed-english-v3` (1024 dimensions) via Bedrock. The vdr-agent must make the same Bedrock embedding call inside `asyncio.to_thread()` (boto3 is sync) using the existing `_bedrock_client` pattern. The pgvector `<=>` operator (cosine distance) is the correct operator for similarity search — it requires the stored vectors to have been generated by the same model (Cohere v3 via the ingestion-service). The `ai_rag.embeddings.embedding` column is `VECTOR(1024)` and is indexed for similarity search.

**Primary recommendation:** Implement in three plans — (1) schema fix V7 migration + `TopicDAO.list_active_by_project()` + embedding helper function, (2) `_evaluate_topic()` coroutine + full fitment block wiring into `process_document()`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg (async) | 3.3.3 | DB access for topic fetch, project_id fetch, chunk fetch | Already in use; all DAO methods use this |
| boto3 | (project pin) | Bedrock embedding call for topic query text | Same client pattern as `claude_client.py` |
| asyncio | stdlib | `gather(return_exceptions=True)` for parallel topic invocations | Phase 6 established this pattern |
| pgvector | (PostgreSQL extension) | `<=>` cosine distance for top-5 chunk selection | Already installed via ingestion-service migrations |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `app.core.llm.claude_client.invoke` | project | Claude API call per topic | Per-topic fitment generation |
| `app.core.llm.rate_limiter.get_rate_limiter` | project | Semaphore wrapping each Bedrock call | Mandatory for every invoke() call |
| `app.db.dao.fitment_result_dao.FitmentResultDAO` | project | Upsert per-topic result to DB | Already written, ready for use |
| `app.db.dao.topic_dao.TopicDAO` | project | `list_active_by_project()` — new method to add | Phase 7 adds this one new method |
| `app.db.dao.document_summary_dao.DocumentSummaryDAO` | project | `get_by_document()` — re-run check | Skip summary if row exists |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Per-topic Bedrock embedding call | Claude to classify relevance without embedding | Embedding-based approach is more precise; avoids prompt stuffing all chunks |
| pgvector `<=>` (cosine) | `<->` (L2 distance) or `<#>` (inner product) | Cosine distance is correct for normalized Cohere embeddings; inner product also works but cosine is standard |
| One DB query per topic (chunk fetch) | Single multi-topic query with LATERAL | Per-topic queries are simpler to implement and debug; multi-topic optimisation is a premature optimisation for ≤20 topics |

**Installation:** No new packages required. All dependencies already in `pyproject.toml`.

---

## Architecture Patterns

### Recommended Project Structure

```
app/worker/
├── processor.py      # EXTEND: add fitment block after summary completion
app/db/dao/
├── topic_dao.py      # ADD: list_active_by_project() method
vdr-agent/migrations/flyway/
├── V7__fitment_results_reasoning_nullable.sql   # CRITICAL: DROP NOT NULL on reasoning
```

### Pattern 1: Re-run Safety Check (Skip Summary if Already Done)

**What:** Before generating the summary, check `document_summaries`. If a row exists, skip the entire Phase 6 pipeline and jump straight to fitment.
**When to use:** Any time `process_document()` is called for a document that already has a summary (poller re-claim after crash, manual retry).

```python
# Source: CONTEXT.md locked decision + DocumentSummaryDAO.get_by_document() exists
existing_summary = await DocumentSummaryDAO.get_by_document(document_id)
if existing_summary is not None:
    LOGGER.info("Summary already exists for doc_id=%s — skipping to fitment", document_id)
    summary_text = existing_summary.summary_text
else:
    # ... full Phase 6 summary generation pipeline ...
    summary_text = final_summary
```

### Pattern 2: project_id Inline Fetch

**What:** SELECT `project_id` from `ai_rag.documents` using a short-lived DB connection immediately after the summary is confirmed.
**When to use:** Once, at the start of the fitment block. search_path includes `ai_rag` so no schema prefix needed in the SQL — but explicit `ai_rag.documents` is safer (matches existing ProcessingStateDAO style).

```python
# Source: app/db/pool.py — search_path = "vdr_agent, ai_rag, public" set on every connection
async with DatabasePool.connection() as conn:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT project_id FROM ai_rag.documents WHERE id = %s",
            (document_id,)
        )
        row = await cur.fetchone()
if row is None:
    LOGGER.error("Document not found in ai_rag.documents: doc_id=%s", document_id)
    return
project_id = row["project_id"]
```

### Pattern 3: TopicDAO.list_active_by_project()

**What:** New DAO method alongside existing `list_by_project()`. Uses DB-level filter `AND is_active = TRUE`.
**When to use:** Always for fitment — only active topics get evaluated.

```python
# Source: app/db/dao/topic_dao.py — list_by_project() with active_only parameter already exists
# The new method is a thin wrapper that calls list_by_project(project_id, active_only=True)
# OR a dedicated SQL method for clarity. Recommended: dedicated method for explicitness.

@staticmethod
async def list_active_by_project(project_id: UUID) -> List[TopicRecord]:
    """Return active topics for a project ordered by created_at ascending."""
    sql = """
        SELECT id, project_id, name, instruction, is_active, created_at, updated_at
        FROM vdr_agent.topics
        WHERE project_id = %s AND is_active = TRUE
        ORDER BY created_at ASC
    """
    async with DatabasePool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, (project_id,))
            rows = await cur.fetchall()
    return [TopicRecord.from_row(row) for row in rows]
```

**Note:** `list_by_project(active_only=True)` already does this — `list_active_by_project` is a dedicated shorthand for clarity. The CONTEXT.md decision locks the addition of this explicit method.

### Pattern 4: Embedding-Based Chunk Selection

**What:** Embed the topic query string `"{topic.name}: {topic.instruction}"` using Bedrock Cohere, then run a pgvector cosine similarity search against `ai_rag.embeddings` for the document to retrieve the top-5 most relevant chunks.

**Critical details about the embedding call:**
- Model: `cohere.embed-english-v3` (matches what ingestion-service stored)
- Input type: `search_query` (not `search_document` — Cohere uses different types for query vs stored docs)
- Dimension: 1024
- Must run in `asyncio.to_thread()` — boto3 is synchronous
- Rate limiter: embedding calls should also be wrapped (they consume Bedrock quota)

**pgvector operator:** `<=>` computes cosine distance (0 = identical, 2 = opposite). `ORDER BY embedding <=> %s::vector LIMIT 5` returns closest chunks.

```python
# Source: ingestion-service/app/core/embedding/service.py + V3 migration schema
# Embedding call pattern (sync, run via asyncio.to_thread):
def _embed_query(query_text: str, bedrock_client, model_id: str) -> list[float]:
    payload = {
        "texts": [query_text],
        "input_type": "search_query",  # Cohere: query vs document distinction
        "embedding_types": ["float"],
    }
    response = bedrock_client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(payload),
    )
    body = json.loads(response["body"].read())
    return body["embeddings"]["float"][0]

# Async wrapper:
query_vector = await asyncio.to_thread(_embed_query, query_text, bedrock_client, model_id)

# pgvector chunk selection (short-lived DB connection):
async with DatabasePool.connection() as conn:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT content
            FROM ai_rag.embeddings
            WHERE document_id = %s
              AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT 5
            """,
            (document_id, query_vector)
        )
        rows = await cur.fetchall()
top_chunks = [row["content"] for row in rows]
```

### Pattern 5: Per-Topic Fitment Coroutine

**What:** A single async coroutine `_evaluate_topic()` that encapsulates one topic's full work: embed query → fetch top-5 chunks → invoke Claude → upsert result. Called in parallel for all topics via `asyncio.gather`.

```python
# Source: processor.py _summarise_section() pattern (Phase 6)
async def _evaluate_topic(
    document_id: UUID,
    topic: TopicRecord,
    summary_text: str,
    bedrock_client,
    embedding_model: str,
) -> None:
    """Evaluate one topic under the global rate limiter.

    Called concurrently via asyncio.gather — must NOT hold any DB connection
    during Bedrock calls. Each call:
      1. Embeds topic query (asyncio.to_thread)
      2. Fetches top-5 chunks (short-lived DB connection — released before invoke)
      3. Invokes Claude for fitment reasoning (rate-limited)
      4. Upserts result to fitment_results
    On failure: upserts status='failed', reasoning=None.
    """
    try:
        query_text = f"{topic.name}: {topic.instruction}"
        query_vector = await asyncio.to_thread(
            _embed_query, query_text, bedrock_client, embedding_model
        )

        # Short-lived DB connection — released before any Bedrock call
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT content FROM ai_rag.embeddings
                    WHERE document_id = %s AND embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector LIMIT 5
                    """,
                    (document_id, query_vector),
                )
                rows = await cur.fetchall()
        top_chunks = [row["content"] for row in rows]

        # Build fitment prompt
        chunks_text = "\n\n".join(
            f"Chunk {i+1}:\n{c}" for i, c in enumerate(top_chunks)
        )
        user_message = (
            f"## Document Summary\n{summary_text}\n\n"
            f"## Relevant Sections\n{chunks_text}\n\n"
            f"## Topic to Evaluate\n{topic.instruction}"
        )

        async with get_rate_limiter().acquire():
            reasoning = await invoke(user_message, system_prompt=FITMENT_SYSTEM_PROMPT)

        await FitmentResultDAO.upsert(document_id, topic.id, reasoning, status="done")
        LOGGER.debug(
            "Fitment complete: doc_id=%s topic=%r chars=%d",
            document_id, topic.name, len(reasoning),
        )

    except Exception as exc:
        LOGGER.error(
            "Fitment failed: doc_id=%s topic=%r error=%s",
            document_id, topic.name, exc,
        )
        await FitmentResultDAO.upsert(document_id, topic.id, None, status="failed")
```

### Pattern 6: Parallel Gather with return_exceptions=True

**What:** Fire all topic coroutines concurrently, collect all results (including exceptions), log each failure separately. Does NOT re-raise — individual topic failures are self-contained.

```python
# Source: processor.py asyncio.gather pattern (Phase 6)
# Note: _evaluate_topic handles its own exception and upserts failed status.
# gather return_exceptions=True ensures semaphore slots are released even if a task raises.
topic_tasks = [
    _evaluate_topic(document_id, topic, summary_text, bedrock_client, embedding_model)
    for topic in active_topics
]
results = await asyncio.gather(*topic_tasks, return_exceptions=True)

# Log any unexpected exceptions that bypassed _evaluate_topic's try/except
for topic, result in zip(active_topics, results):
    if isinstance(result, BaseException):
        LOGGER.error(
            "Unhandled exception in _evaluate_topic for topic=%r: %s",
            topic.name, result,
        )

LOGGER.info(
    "Fitment complete: doc_id=%s topics_evaluated=%d",
    document_id, len(active_topics),
)
```

### Anti-Patterns to Avoid

- **Holding a DB connection during Bedrock calls:** Each `_evaluate_topic()` must close its DB connection before the `invoke()` call. Pool max_size=10; Bedrock calls take 5-30 seconds. Holding connections during AI calls exhausts the pool for all other operations.
- **Calling `asyncio.to_thread()` without a ThreadPoolExecutor:** The project already configures 50 workers (Phase 4). Embedding calls use the same `asyncio.to_thread()` mechanism — no additional configuration needed.
- **Using `input_type='search_document'` for topic queries:** Cohere Bedrock uses `search_query` for query texts and `search_document` for stored content. Using the wrong input type degrades similarity search quality.
- **Using `<->` (L2 distance) instead of `<=>` (cosine):** Cohere embeddings are not L2-normalized to unit length by default. Cosine distance is the correct operator. The ingestion-service comment in V3 migration confirms: `ivfflat (embedding vector_cosine_ops)`.
- **Passing `reasoning=None` to DB when column is NOT NULL:** The current V5 schema has `reasoning TEXT NOT NULL`. A V7 migration is required before Phase 7 code is deployed.
- **Updating `processing_state` in Phase 7:** The CONTEXT.md decision explicitly says Phase 7 does NOT touch `processing_state`. Only `fitment_results` rows are written by this phase.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cosine similarity search | Custom vector comparison in Python | pgvector `<=>` operator | Already installed; DB-side computation is orders of magnitude faster than fetching all vectors to Python |
| Topic embedding generation | Custom HTTP client to Bedrock | `asyncio.to_thread(_embed_query, ...)` with existing boto3 client | Same pattern as `invoke()`; reuse the existing `_bedrock_client` singleton |
| Parallel topic execution | Manual asyncio.Task management | `asyncio.gather(*tasks, return_exceptions=True)` | Phase 6 establishes this exact pattern; rate limiter slots are correctly released |
| Fitment result persistence | Custom INSERT with conflict handling | `FitmentResultDAO.upsert()` | Already written with correct constraint name (`fitment_results_doc_topic_unique`); re-run safe |

**Key insight:** Every building block for Phase 7 already exists. The implementation is purely about assembly — connecting existing components in the right order with the right connection-lifetime discipline.

---

## Common Pitfalls

### Pitfall 1: reasoning NOT NULL Constraint Violation

**What goes wrong:** `FitmentResultDAO.upsert(document_id, topic_id, None, status='failed')` raises `psycopg.errors.NotNullViolation: null value in column "reasoning" of relation "fitment_results"`.
**Why it happens:** V5 migration defines `reasoning TEXT NOT NULL`. The DAO was written to accept `Optional[str]` in anticipation of the Phase 7 failure-handling decision, but the schema was never updated.
**How to avoid:** Add V7 migration: `ALTER TABLE vdr_agent.fitment_results ALTER COLUMN reasoning DROP NOT NULL;` Run migration before deploying Phase 7 code.
**Warning signs:** Any attempt to upsert a failed fitment result will immediately fail with a DB constraint error, not a Bedrock error.

### Pitfall 2: Bedrock Embedding Client Initialization

**What goes wrong:** The existing `_bedrock_client` in `claude_client.py` is initialized to call `bedrock-runtime` Claude models. Embedding calls use the same service but a different model ID (`cohere.embed-english-v3`). The existing singleton does not need to change — a second `boto3.client("bedrock-runtime")` call is fine since boto3 clients are lightweight objects, or alternatively pass `modelId` differently.
**Why it happens:** The current `claude_client.py` `_get_bedrock_client()` constructs the client without a model ID (model is passed at call time in `invoke_model`). Embedding calls can reuse the same client.
**How to avoid:** Use the existing `_get_bedrock_client()` singleton for embedding calls — just pass the Cohere model ID in the embedding payload. No second client needed.
**Warning signs:** If a new boto3 client is initialized without the correct auth (bearer token), calls will fail with auth errors.

### Pitfall 3: Embeddings Indexed Without IVFFLAT (Slow Similarity Search)

**What goes wrong:** The V3 migration comment says: `Note: ivfflat index for vector similarity search should be created after data is inserted`. If the index was never created, `ORDER BY embedding <=> %s::vector LIMIT 5` does a full sequential scan. For large documents (1000+ chunks) this is slow but correct.
**Why it happens:** IVFFLAT indexes require data to be present when created; they're intentionally deferred.
**How to avoid:** Phase 7 still works without the index (correctness is unaffected). For production performance, the IVFFLAT index should be created separately. This is out of Phase 7 scope.
**Warning signs:** Chunk fetch queries taking >100ms per topic on large documents.

### Pitfall 4: Cohere input_type Mismatch

**What goes wrong:** Topic query text embedded with `input_type='search_document'` instead of `search_query`. The resulting vector is optimized for document storage, not retrieval — similarity scores will be degraded.
**Why it happens:** The ingestion-service `EmbeddingConfig` defaults to `input_type='search_document'`. Phase 7 must use `search_query` for the topic query text.
**How to avoid:** Hardcode `"input_type": "search_query"` in the embedding payload for the fitment chunk selection. Comment the distinction explicitly.
**Warning signs:** Similarity search returns chunks that are semantically unrelated to the topic.

### Pitfall 5: DB Connection Held Across asyncio.to_thread Embedding Call

**What goes wrong:** If the chunk fetch DB connection is opened before the embedding call and held open during `asyncio.to_thread(_embed_query, ...)`, the DB pool is exhausted by concurrent topic evaluations (max_size=10, rate limiter allows 10 concurrent Bedrock calls).
**Why it happens:** Natural code organization would fetch chunks after computing the query vector, but the embedding call is the slow step.
**How to avoid:** Order within `_evaluate_topic()` must be: embed → fetch chunks (short connection) → invoke Claude. Never hold a DB connection during embedding or Claude calls.
**Warning signs:** Pool exhaustion errors or timeouts on DB operations while Bedrock calls are in flight.

### Pitfall 6: asyncio.gather Collecting Wrong Results

**What goes wrong:** `_evaluate_topic()` already handles its own exception and upserts `status='failed'`. If `gather` is called with `return_exceptions=False` (the default), an unhandled exception in `_evaluate_topic()` that escapes its try/except would abort all remaining topics.
**Why it happens:** Developer forgets `return_exceptions=True` or the `_evaluate_topic` try/except is too narrow.
**How to avoid:** Always use `return_exceptions=True`. Make the top-level try/except in `_evaluate_topic` catch `BaseException` (not just `Exception`) to handle `CancelledError` scenarios.
**Warning signs:** Fewer fitment_results rows than expected after a run; some topics never evaluated.

---

## Code Examples

Verified patterns from existing codebase:

### FITMENT_SYSTEM_PROMPT (follows Phase 6 SECTION_SYSTEM_PROMPT style)
```python
# Source: processor.py lines 16-28 (Phase 6 prompt style)
FITMENT_SYSTEM_PROMPT = (
    "You are an ESG analyst evaluating whether a corporate disclosure document "
    "contains meaningful information about a specific ESG topic. "
    "Review the document summary and the most relevant sections provided. "
    "Assess whether the document addresses this topic in a substantive way. "
    "Write a concise paragraph (3-5 sentences) explaining your finding — "
    "what the document says about this topic, or why it does not address it."
)
```

### V7 Migration: Drop NOT NULL on reasoning
```sql
-- Source: vdr-agent/migrations/flyway/V5__create_fitment_results_table.sql (schema audit)
-- V7__fitment_results_reasoning_nullable.sql
SET search_path TO vdr_agent, public;

-- reasoning is NULL when topic fitment fails (status='failed').
-- Phase 7 decision: failed topics record status='failed', reasoning=NULL.
ALTER TABLE vdr_agent.fitment_results
    ALTER COLUMN reasoning DROP NOT NULL;
```

### Embedding Helper Function (sync, runs in asyncio.to_thread)
```python
# Source: ingestion-service/app/core/embedding/service.py _embed_batch() + EmbeddingConfig
# Cohere Bedrock response format: {"embeddings": {"float": [[...]]}}
def _embed_query_sync(query_text: str, bedrock_client) -> list[float]:
    """Embed a single topic query string using Cohere on Bedrock.

    Uses input_type='search_query' — distinct from 'search_document' used
    by ingestion-service when storing chunks. This difference is intentional
    and required for correct cosine similarity ordering.

    Run via asyncio.to_thread() — never call directly from async context.
    """
    import json
    payload = {
        "texts": [query_text],
        "input_type": "search_query",
        "embedding_types": ["float"],
    }
    response = bedrock_client.invoke_model(
        modelId="cohere.embed-english-v3",
        contentType="application/json",
        accept="application/json",
        body=json.dumps(payload),
    )
    body = json.loads(response["body"].read())
    return body["embeddings"]["float"][0]  # 1024-dim float list
```

### pgvector Cosine Similarity Query
```sql
-- Source: V3 migration — embedding VECTOR(1024), ivfflat vector_cosine_ops
-- <=> is cosine DISTANCE (lower = more similar). LIMIT 5 returns top 5 chunks.
SELECT content
FROM ai_rag.embeddings
WHERE document_id = %s
  AND embedding IS NOT NULL
ORDER BY embedding <=> %s::vector
LIMIT 5
```

### Complete process_document() Extension Skeleton
```python
# Source: processor.py (Phase 6) — extends after ProcessingStateDAO.update_status('done')
# Phase 7 fitment block appended to process_document():

    # ── Phase 7: Fitment Generation ──────────────────────────────────────────
    # Fetch project_id inline (short-lived connection; poller signature unchanged)
    try:
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT project_id FROM ai_rag.documents WHERE id = %s",
                    (document_id,)
                )
                doc_row = await cur.fetchone()
        if doc_row is None:
            LOGGER.error("ai_rag.documents row missing for doc_id=%s", document_id)
            return
        project_id = doc_row["project_id"]
    except Exception:
        LOGGER.exception("Failed to fetch project_id for doc_id=%s", document_id)
        return

    # Fetch active topics
    active_topics = await TopicDAO.list_active_by_project(project_id)
    if not active_topics:
        LOGGER.warning(
            "No active topics for project_id=%s doc_id=%s — skipping fitment",
            project_id, document_id,
        )
        return

    LOGGER.info(
        "Starting fitment: doc_id=%s topics=%d",
        document_id, len(active_topics),
    )

    bedrock_client = _get_bedrock_client()
    topic_tasks = [
        _evaluate_topic(document_id, topic, final_summary, bedrock_client)
        for topic in active_topics
    ]
    results = await asyncio.gather(*topic_tasks, return_exceptions=True)

    # Log any exceptions that escaped _evaluate_topic's own try/except
    for topic, result in zip(active_topics, results):
        if isinstance(result, BaseException):
            LOGGER.error(
                "Unhandled fitment error topic=%r doc_id=%s: %s",
                topic.name, document_id, result,
            )

    LOGGER.info(
        "Fitment done: doc_id=%s topics_evaluated=%d",
        document_id, len(active_topics),
    )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-query chunk selection via keyword search | pgvector cosine similarity with Cohere embeddings | Phase 2/3 (ingestion-service already stores vectors) | Semantic relevance rather than lexical match; no extra infra |
| Sequential topic evaluation | `asyncio.gather` parallel | Phase 6 established the pattern | For 10 topics: ~10x throughput improvement vs sequential |

**Deprecated/outdated:**
- `reasoning TEXT NOT NULL` in V5: must be changed to nullable via V7 migration before Phase 7 runs.

---

## Open Questions

1. **Bedrock embedding quota sharing**
   - What we know: Both ingestion-service and vdr-agent share the 200 RPM Bedrock quota. Phase 7 adds one embedding call per topic per document. For 10 topics, that's 10 embedding calls + 10 Claude calls per document.
   - What's unclear: Whether the embedding model (Cohere) and the Claude model share the same quota bucket in AWS Bedrock, or have separate limits.
   - Recommendation: The existing `GlobalRateLimiter` (max 10 concurrent) applies to Claude calls. The embedding calls are fast (~200ms) and infrequent; treat them as outside the rate limiter for now. Monitor in production.

2. **Embedding model config in vdr-agent settings**
   - What we know: The embedding model ID `cohere.embed-english-v3` is hardcoded in ingestion-service `EmbeddingConfig`. The CONTEXT.md marks the embedding approach as Claude's discretion.
   - What's unclear: Whether the embedding model ID should be added as a vdr-agent config field (`VDR_AGENT_EMBEDDING_MODEL`) or hardcoded inline.
   - Recommendation: Add a `bedrock_embedding_model: str` field to `Settings` with default `"cohere.embed-english-v3"` and prefix `VDR_AGENT_`. This follows the existing pattern for `bedrock_model`.

3. **Fallback when no vectors stored (empty embedding column)**
   - What we know: CONTEXT.md marks this as Claude's discretion. `ai_rag.embeddings.embedding` is `VECTOR(1024)` but the column allows NULL (`embedding IS NOT NULL` filter handles this).
   - What's unclear: Whether a document could have embeddings stored without the vector populated (status='failed' rows). The WHERE clause `embedding IS NOT NULL` covers this.
   - Recommendation: If `top_chunks` is empty after the pgvector query (all embeddings NULL or document has no chunks), fall back to using the first 5 chunks by `chunk_index` order. Log a WARNING.

---

## Sources

### Primary (HIGH confidence)
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/worker/processor.py` — Phase 6 patterns read directly
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/db/dao/fitment_result_dao.py` — Upsert signature and SQL verified
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/db/dao/topic_dao.py` — Existing `list_by_project(active_only=True)` verified
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/core/llm/claude_client.py` — `invoke()` and `_get_bedrock_client()` verified
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/core/llm/rate_limiter.py` — `get_rate_limiter().acquire()` pattern verified
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/migrations/flyway/V5__create_fitment_results_table.sql` — `reasoning TEXT NOT NULL` conflict confirmed
- `/Users/sanchayjain/Desktop/ERM/ingestion-service/migrations/flyway/V3__documents_and_embeddings.sql` — `embedding VECTOR(1024)`, `<=>` operator intent confirmed
- `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/core/embedding/service.py` — Cohere payload format, `input_type` values, response format verified
- `/Users/sanchayjain/Desktop/ERM/ingestion-service/app/models/embedding.py` — `EmbeddingConfig.model_name = "cohere.embed-english-v3"` confirmed
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/config/__init__.py` — Settings pattern, `VDR_AGENT_` prefix, `get_settings()` confirmed

### Secondary (MEDIUM confidence)
- CONTEXT.md locked decisions — all implementation decisions copied verbatim
- STATE.md accumulated context — confirmed DB connection discipline, `asyncio.to_thread` requirement, 50-worker ThreadPoolExecutor

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries read directly from existing source files
- Architecture: HIGH — all patterns are direct extensions of Phase 6 code already in the repo
- Pitfalls: HIGH for schema conflict (confirmed from migration SQL); MEDIUM for Bedrock quota/input_type (based on ingestion-service source, correct behavior is well-documented)

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (stable domain — pgvector and Cohere Bedrock API are not fast-moving)
