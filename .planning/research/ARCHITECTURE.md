# Architecture Patterns

**Domain:** FastAPI microservice with HTTP API + DB polling loop + parallel LLM calls
**Researched:** 2026-03-05
**Confidence:** HIGH — based on direct codebase analysis of ingestion-service + verified FastAPI patterns

---

## Recommended Architecture

`vdr-agent` is a single Python service with two concurrent concerns: serving HTTP requests from `vdr-frontend` and running a background polling loop that drives AI generation. Both live in the same process, coordinated by asyncio.

```
vdr-agent/
├── main.py                        # FastAPI app factory + lifespan
├── app/
│   ├── config/                    # Pydantic Settings (VDR_AGENT_ prefix)
│   ├── logging/                   # Logging configuration (match ingestion-service)
│   ├── startup.py                 # startup_event / shutdown_event
│   ├── core/
│   │   ├── routers/               # FastAPI HTTP endpoints
│   │   │   ├── __init__.py        # api_router aggregator
│   │   │   ├── topics.py          # Topic CRUD
│   │   │   ├── documents.py       # Document status + results
│   │   │   └── health.py          # /health endpoint
│   │   ├── polling/               # Background loop
│   │   │   ├── poller.py          # Main polling loop (asyncio.create_task)
│   │   │   └── processor.py       # Per-document orchestration logic
│   │   ├── generation/            # AI generation logic
│   │   │   ├── summary.py         # Section summarisation + combine
│   │   │   └── fitment.py         # Per-topic fitment evaluation
│   │   └── llm/                   # Bedrock/Claude client + rate limiting
│   │       ├── client.py          # boto3 Bedrock wrapper (async-safe)
│   │       └── rate_limiter.py    # asyncio.Semaphore-based limiter
│   ├── db/
│   │   ├── pool.py                # AsyncConnectionPool (psycopg_pool)
│   │   └── dao/
│   │       ├── base.py            # AsyncBaseDAO (async version)
│   │       ├── topic_dao.py       # Topic CRUD
│   │       ├── document_summary_dao.py  # Read embeddings, write summaries
│   │       └── fitment_dao.py     # Write fitment results
│   ├── models/                    # Pydantic API request/response models
│   └── migrations/flyway/         # SQL migrations for vdr-agent tables
```

---

## Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| **HTTP API layer** (`core/routers/`) | Serve REST endpoints to `vdr-frontend`. Topic CRUD, document status queries, result retrieval. | DB layer (read) |
| **Polling loop** (`core/polling/poller.py`) | Periodic async task: query for unprocessed documents, claim each one atomically, hand off to processor. Runs continuously inside lifespan. | DB layer (read + write), Processor |
| **Processor** (`core/polling/processor.py`) | Per-document orchestration: fetch chunks from DB, call generation functions in the right order, write results back. | DB layer, Generation layer |
| **Generation layer** (`core/generation/`) | Stateless AI logic. Summary: parallel section calls + combine. Fitment: per-topic calls in parallel (bounded). Returns text results, does not touch DB directly. | LLM client |
| **LLM client** (`core/llm/client.py`) | Wraps boto3 Bedrock InvokeModel. Single point for model ID, request format, retry on transient errors, semaphore enforcement. | AWS Bedrock |
| **DB layer** (`db/`) | Async connection pool + DAOs. Reads `ai_rag.documents` and `ai_rag.embeddings` (owned by ingestion-service). Writes to `vdr_agent.*` tables (owned by vdr-agent). | PostgreSQL |

**Boundary rule:** Generation layer is pure computation — it accepts text inputs and returns text outputs. It never reads from or writes to the database. The processor owns all DB interactions for a document's lifecycle.

---

## Data Flow

### Document Processing Flow

```
PostgreSQL (ai_rag schema)
    documents table: status = 'completed', embedding columns populated
    embeddings table: chunks available for document_id
         |
         | (poll every N seconds)
         v
Polling Loop (poller.py)
    SELECT id FROM ai_rag.documents
    WHERE embedding_status = 'completed'
      AND NOT EXISTS (SELECT 1 FROM vdr_agent.document_summaries WHERE document_id = d.id)
    FOR UPDATE SKIP LOCKED   ← atomic claim, safe for multiple replicas
    LIMIT 1
         |
         | document_id
         v
Processor (processor.py)
    1. Mark document as processing in vdr_agent.processing_state
    2. Fetch all embedding chunks for document_id from ai_rag.embeddings
         |
         | chunks (list of text strings)
         v
Generation: Summary (generation/summary.py)
    section_summaries = await asyncio.gather(
        *[summarise_section(chunk) for chunk in sections]
    )                          ← up to ~10 parallel Bedrock calls
    final_summary = await combine_summaries(section_summaries)
         |
         | final_summary (text)
         v
Processor
    Write final_summary to vdr_agent.document_summaries
         |
         | final_summary + document_id
         v
Generation: Fitment (generation/fitment.py)
    topics = fetch all active topics with instructions
    fitment_results = await asyncio.gather(
        *[evaluate_fitment(topic, final_summary, relevant_chunks) for topic in topics],
        return_exceptions=True    ← prevent one topic failure from killing others
    )                              ← up to ~30 parallel Bedrock calls (semaphore-bounded)
         |
         | list of FitmentResult
         v
Processor
    Write each fitment result to vdr_agent.fitment_results
    Mark document as done in vdr_agent.processing_state
         |
         v
vdr-frontend (polling /documents endpoint)
    Sees updated status + populated results
```

### Topic Instruction Update Flow

```
vdr-frontend → PUT /topics/{id}
    → Topic DAO: update instruction in vdr_agent.topics
    → Fitment DAO: DELETE FROM vdr_agent.fitment_results WHERE topic_id = id
      (or mark as stale)
    → Polling loop picks up documents needing fitment re-run on next cycle
      (detected by: document_id in summaries but fitment_results missing for topic_id)
```

### New Topic Added Flow

```
vdr-frontend → POST /topics
    → Topic DAO: insert new topic
    → Documents already have summaries in vdr_agent.document_summaries
    → Polling loop detects: summaries exist but no fitment for new topic_id
    → Runs fitment-only generation for all documents (skips summary generation)
```

---

## DB Schema Design

### Schema ownership
- `ai_rag.*` — owned by ingestion-service. vdr-agent reads only.
- `vdr_agent.*` — owned by vdr-agent. All vdr-agent writes go here.

### Tables

```sql
-- vdr_agent.topics
-- User-defined ESG topics with per-topic AI instructions
CREATE TABLE vdr_agent.topics (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    description TEXT,
    instructions TEXT NOT NULL,   -- What the AI looks for when evaluating fitment
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- vdr_agent.processing_state
-- Tracks per-document AI generation progress (independent of ingestion status)
-- This is the polling trigger table: poller reads ai_rag.documents,
-- then consults this table to find what needs processing.
CREATE TABLE vdr_agent.processing_state (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL UNIQUE,   -- FK to ai_rag.documents.id
    summary_status  TEXT NOT NULL DEFAULT 'pending',
    summary_error   TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT valid_summary_status
        CHECK (summary_status IN ('pending', 'processing', 'done', 'failed'))
);
-- Index for the hot poll query
CREATE INDEX ON vdr_agent.processing_state (summary_status, created_at)
    WHERE summary_status IN ('pending', 'failed');

-- vdr_agent.document_summaries
-- Stores generated AI summaries for each document
CREATE TABLE vdr_agent.document_summaries (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL UNIQUE,   -- FK to ai_rag.documents.id
    summary     TEXT NOT NULL,
    model_id    TEXT NOT NULL,          -- Which Bedrock model generated this
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- vdr_agent.fitment_results
-- Per-document, per-topic fitment evaluations
CREATE TABLE vdr_agent.fitment_results (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,          -- FK to ai_rag.documents.id
    topic_id    UUID NOT NULL REFERENCES vdr_agent.topics(id) ON DELETE CASCADE,
    is_relevant BOOLEAN NOT NULL,
    fitment_summary TEXT NOT NULL,      -- Plain-English explanation
    status      TEXT NOT NULL DEFAULT 'done',
    model_id    TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT unique_document_topic UNIQUE (document_id, topic_id)
);
-- Index for the re-run query (find docs missing fitment for a given topic)
CREATE INDEX ON vdr_agent.fitment_results (topic_id, document_id);
-- Index for per-document retrieval (frontend queries)
CREATE INDEX ON vdr_agent.fitment_results (document_id);
```

### Status state machine for `processing_state.summary_status`

```
[document embedded in ingestion-service]
         |
         v
      pending          ← row inserted by poller when document first detected
         |
         v (poller claims it)
     processing        ← row updated atomically via FOR UPDATE SKIP LOCKED
         |
    +---------+
    |         |
    v         v
   done     failed     ← failed = skip (no retry for now); done = summaries written
```

### Poll query (canonical)

```sql
-- Run inside a transaction; commit after updating to 'processing'
WITH claimed AS (
    SELECT ps.document_id
    FROM vdr_agent.processing_state ps
    WHERE ps.summary_status = 'pending'
    ORDER BY ps.created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE vdr_agent.processing_state
SET summary_status = 'processing',
    started_at = NOW(),
    updated_at = NOW()
WHERE document_id = (SELECT document_id FROM claimed)
RETURNING document_id;
```

This query is the foundation of the poller. `FOR UPDATE SKIP LOCKED` ensures that if vdr-agent runs as multiple replicas, each replica claims a different document without deadlocks or double-processing.

### New document detection query (insert-before-claim pattern)

```sql
-- Run periodically to register newly-embedded documents
INSERT INTO vdr_agent.processing_state (document_id, summary_status)
SELECT d.id, 'pending'
FROM ai_rag.documents d
WHERE d.status = 'completed'
  AND NOT EXISTS (
      SELECT 1 FROM vdr_agent.processing_state ps WHERE ps.document_id = d.id
  )
ON CONFLICT (document_id) DO NOTHING;
```

Run this before the claim query on each poll cycle. Separating detection from claiming keeps both queries simple and atomic.

---

## Patterns to Follow

### Pattern 1: Polling Loop via `asyncio.create_task` in Lifespan

**What:** Start a long-running coroutine as a background task in the FastAPI lifespan. Store the task reference and cancel it on shutdown.

**When:** Any persistent background job that must run for the lifetime of the service.

**Example:**
```python
# app/startup.py
import asyncio
from fastapi import FastAPI
from app.core.polling.poller import run_polling_loop

async def startup_event(app: FastAPI) -> None:
    await DatabasePool.initialize(...)
    task = asyncio.create_task(run_polling_loop(app))
    app.state.polling_task = task

async def shutdown_event(app: FastAPI) -> None:
    if hasattr(app.state, "polling_task"):
        app.state.polling_task.cancel()
        try:
            await asyncio.wait_for(app.state.polling_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    await DatabasePool.close()
```

```python
# app/core/polling/poller.py
import asyncio
import logging

LOGGER = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 10

async def run_polling_loop(app) -> None:
    """Continuous polling loop. Runs forever until cancelled."""
    while True:
        try:
            await poll_once(app)
        except asyncio.CancelledError:
            LOGGER.info("Polling loop cancelled — shutting down")
            raise
        except Exception:
            LOGGER.exception("Polling loop error (continuing)")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
```

### Pattern 2: Bounded Parallel LLM Calls via Semaphore + `asyncio.gather`

**What:** Run up to N Bedrock API calls in parallel using a semaphore to cap concurrency. Use `return_exceptions=True` so one topic failure does not abort the entire document.

**When:** Any batch of independent async calls to an external API with rate limits.

**Example:**
```python
# app/core/generation/fitment.py
import asyncio
from app.core.llm.client import invoke_model

# Cap concurrent Bedrock calls across the whole service
_BEDROCK_SEMAPHORE = asyncio.Semaphore(10)

async def _evaluate_one(topic, summary, chunks) -> FitmentResult:
    async with _BEDROCK_SEMAPHORE:
        response = await invoke_model(
            prompt=build_fitment_prompt(topic, summary, chunks)
        )
        return parse_fitment_response(response, topic)

async def evaluate_all_topics(topics, summary, chunks) -> list[FitmentResult]:
    results = await asyncio.gather(
        *[_evaluate_one(t, summary, chunks) for t in topics],
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, Exception)]
    for r in results:
        if isinstance(r, Exception):
            LOGGER.error("Fitment failed for topic: %s", r)
    return successes
```

**Semaphore sizing note:** The Bedrock Claude Sonnet default TPS limit is 200 RPM (~3.3 RPS). With ~40 calls per document and a 10-second poll interval, a semaphore of 10 allows ~1 document processed per ~40 seconds at full concurrency. Adjust `Semaphore(N)` based on actual Bedrock quota.

### Pattern 3: Async DAO Pattern (match ingestion-service)

**What:** All DB access goes through DAOs that use the async connection pool. DAOs take a connection or pool reference, execute raw SQL, and return dataclasses.

**When:** Any database read or write in vdr-agent.

**Example:**
```python
# app/db/dao/topic_dao.py
from dataclasses import dataclass
from uuid import UUID
from psycopg_pool import AsyncConnectionPool

@dataclass
class TopicRecord:
    id: UUID
    name: str
    instructions: str
    is_active: bool

class TopicDAO:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def list_active(self) -> list[TopicRecord]:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, name, instructions, is_active "
                    "FROM vdr_agent.topics WHERE is_active = TRUE ORDER BY name"
                )
                rows = await cur.fetchall()
        return [TopicRecord(*r) for r in rows]
```

### Pattern 4: Processor Owns All DB Side-Effects

**What:** The processor module is the only caller of DAO write methods during document processing. Generation functions are pure: they accept inputs and return outputs without touching the DB.

**When:** Designing the boundary between AI logic and persistence.

**Why:** Makes generation functions independently testable. Separates concerns cleanly. Avoids hidden DB calls inside deeply nested AI code.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Using FastAPI `BackgroundTasks` for the Polling Loop

**What:** Attaching the polling loop to a per-request `BackgroundTasks` instance.

**Why bad:** `BackgroundTasks` runs tasks after a single HTTP response and is tied to the request lifecycle. It is not a persistent loop. The polling loop must survive for the entire process lifetime — use `asyncio.create_task` in lifespan instead.

**Instead:** `asyncio.create_task(run_polling_loop(app))` in `startup_event`.

### Anti-Pattern 2: Polling with `SELECT ... WHERE status = 'pending'` Without `FOR UPDATE SKIP LOCKED`

**What:** Reading pending rows then updating them in a separate statement.

**Why bad:** Race condition if multiple replicas run simultaneously. Two replicas can read the same document and both start processing it, resulting in duplicate API calls and conflicting DB writes.

**Instead:** `SELECT ... FOR UPDATE SKIP LOCKED` inside a single transaction atomically claims and marks the row. See canonical poll query above.

### Anti-Pattern 3: Running Blocking boto3 Calls Directly in Async Coroutines

**What:** Calling `boto3_client.invoke_model(...)` (which is synchronous) directly from an `async def` function without offloading to a thread.

**Why bad:** boto3 is synchronous. A direct call blocks the entire event loop, freezing all concurrent tasks (including the HTTP server) for the duration of the Bedrock API call.

**Instead:** Wrap in `asyncio.to_thread`:
```python
response = await asyncio.to_thread(
    bedrock_client.invoke_model,
    modelId=MODEL_ID,
    body=json.dumps(payload),
    contentType="application/json",
)
```
Or use the async Bedrock client via `aioboto3` if adopted. `asyncio.to_thread` is the zero-dependency path that matches ingestion-service conventions.

### Anti-Pattern 4: Writing to `ai_rag.*` Tables from vdr-agent

**What:** Adding summary or fitment columns directly to `ai_rag.documents` or creating rows in ingestion-service tables.

**Why bad:** Cross-service schema coupling. Ingestion-service migrations would need to account for vdr-agent's columns. Undeployment of vdr-agent would leave orphan columns. Schema ownership becomes unclear.

**Instead:** vdr-agent owns `vdr_agent.*` tables exclusively. References to ingestion-service data go through `document_id` as a foreign key reference, not schema co-location.

### Anti-Pattern 5: Semaphore Defined Inside the Per-Call Function

**What:** Creating a new `asyncio.Semaphore` inside a helper function that is called once per topic/section.

**Why bad:** Each call gets its own semaphore with limit=N, which does not bound concurrency at all.

**Instead:** Define the semaphore once at module level (or pass it from the poller) so all concurrent coroutines share the same lock.

---

## Scalability Considerations

| Concern | At 100 docs | At 1,000 docs | At 10,000 docs |
|---------|-------------|---------------|----------------|
| Poll latency | 10s interval is fine | 10s interval is fine | Consider reducing interval or batching |
| Bedrock throughput | ~40 calls/doc = 4,000 total calls; semaphore(10) handles fine | 40,000 calls; monitor Bedrock quota | Request quota increase; consider batching |
| Concurrent processing | Single doc at a time is safe | May want 2–3 concurrent docs with separate semaphore slots | Horizontal scaling (multiple replicas + SKIP LOCKED) |
| DB connections | Pool of 5–10 sufficient | Pool of 10–20 | Pool of 20–40; monitor wait times |
| Fitment re-runs | DELETE + re-insert for one topic; fast | DELETE + re-insert for one topic across 1,000 docs; consider batching | Background re-run queue (same polling mechanism) |

**Multi-replica note:** The `FOR UPDATE SKIP LOCKED` pattern means vdr-agent can scale horizontally without any coordination service. Each replica independently claims work. The semaphore must be defined at the service instance level (not shared across replicas) — each replica enforces its own Bedrock rate limit.

---

## Build Order Implications

The component dependencies form a clear build order:

1. **DB schema + migrations** — All other layers depend on tables existing. Build first.
   - `vdr_agent.topics`, `vdr_agent.processing_state`, `vdr_agent.document_summaries`, `vdr_agent.fitment_results`

2. **Config + DB pool + DAOs** — Foundation for all application code.
   - Pydantic Settings, `DatabasePool` initialization, `TopicDAO`, `DocumentSummaryDAO`, `FitmentDAO`

3. **LLM client** — Stateless wrapper; no DB dependency. Can be built and tested in isolation.
   - boto3 Bedrock wrapper, `asyncio.to_thread` wiring, semaphore

4. **Generation layer** — Depends only on LLM client. Pure functions, no DB.
   - `generation/summary.py`, `generation/fitment.py`

5. **Processor** — Composes DAOs + generation layer. First component touching full pipeline.
   - `polling/processor.py`

6. **Polling loop** — Depends on processor. The background engine.
   - `polling/poller.py`, poll query, detection query

7. **HTTP API routers** — Depends on DAOs. Can be built in parallel with polling loop.
   - `routers/topics.py`, `routers/documents.py`

8. **FastAPI app wiring** — Composes everything: lifespan, routers, middleware.
   - `main.py`, `startup.py`

**Phases should respect this order.** The DB schema + DAOs + LLM client are the foundation phase. Polling loop + generation logic are the core engine phase. HTTP API is the integration phase.

---

## Sources

- FastAPI lifespan documentation: [https://fastapi.tiangolo.com/advanced/events/](https://fastapi.tiangolo.com/advanced/events/) — HIGH confidence
- PostgreSQL SKIP LOCKED pattern: [The Unreasonable Effectiveness of SKIP LOCKED](https://www.inferable.ai/blog/posts/postgres-skip-locked) — HIGH confidence (documented PostgreSQL feature since 9.5)
- asyncio.Semaphore for LLM rate limiting: [Unite.AI Async LLM Guide](https://www.unite.ai/asynchronous-llm-api-calls-in-python-a-comprehensive-guide/) — MEDIUM confidence (community pattern, verified against official asyncio docs)
- FastAPI background tasks comparison: [BackgroundTasks vs Threads vs Async](https://hussainwali.medium.com/fastapi-backgroundtasks-vs-threads-vs-async-f0020540bb87) — MEDIUM confidence
- Ingestion-service codebase: Direct analysis of `/Users/sanchayjain/Desktop/ERM/ingestion-service/` — HIGH confidence (primary source for conventions)
