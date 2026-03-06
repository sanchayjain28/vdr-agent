# Domain Pitfalls

**Domain:** FastAPI microservice with DB polling loop + high-concurrency LLM API calls (AWS Bedrock)
**Project:** vdr-agent
**Researched:** 2026-03-05

---

## Critical Pitfalls

Mistakes that cause rewrites, data corruption, or permanently stuck processing queues.

---

### Pitfall 1: Duplicate Document Processing from Polling Race Condition

**What goes wrong:** The polling loop runs `SELECT ... WHERE summary_status IS NULL` and then immediately begins processing. If two processes (or two iterations of the same loop with overlapping timing) both see a document as unprocessed before either writes the `in_progress` status, both will fire ~40 Claude API calls for the same document, wasting significant quota and potentially writing duplicate results to the DB.

**Why it happens:** A plain `SELECT` followed by an `UPDATE summary_status = 'in_progress'` is not atomic. There is a window between reading and writing where another reader sees the same `NULL` status. This is especially dangerous during service restart (old loop + new loop overlap) or if polling interval is shorter than processing time.

**Consequences:**
- Doubled Bedrock API calls per document (80 calls instead of 40)
- Duplicate rows in fitment/summary tables, or last-write-wins corruption
- Quota exhaustion for large backlogs (1,000 documents × 80 calls = 80,000 calls)

**Prevention:** Use a single atomic claim query with `FOR UPDATE SKIP LOCKED`. This pattern is PostgreSQL's native job-queue primitive:

```sql
UPDATE vdr_agent.documents
SET summary_status = 'in_progress', processing_started_at = NOW()
WHERE id = (
    SELECT id FROM vdr_agent.documents
    WHERE summary_status IS NULL
    ORDER BY created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING *;
```

`SKIP LOCKED` means concurrent pollers skip rows already claimed, with zero blocking. The `UPDATE` + `RETURNING` is atomic — no separate SELECT needed.

**Detection:**
- Multiple rows in fitment table for the same `(document_id, topic_id)` pair
- Bedrock quota exhausted faster than expected
- Logs showing two workers processing the same `document_id`

**Phase:** Must be addressed in the initial polling loop implementation (Phase 1 / polling foundation). Retrofitting later is risky.

---

### Pitfall 2: Status Stuck in `in_progress` Forever (No Failure Recovery)

**What goes wrong:** The poller marks a document `summary_status = 'in_progress'` and then the service crashes, restarts, or the Claude call silently times out. The document is now permanently invisible to the poller, because the query filters for `summary_status IS NULL`. With 1,000+ documents and the acknowledged decision to skip retries, this could strand a significant portion of the backlog.

**Why it happens:** The project spec explicitly defers retry logic. Without a timeout/expiry mechanism, any crash during processing creates a permanent `in_progress` ghost. This is different from intentional skip-on-failure — it prevents even manual observation of which documents are stuck.

**Consequences:**
- Documents that errored are silently invisible to both the poller and the frontend
- No way to distinguish "failed" from "genuinely processing"
- Operator cannot distinguish a 5-minute healthy processing run from a 5-hour stuck ghost

**Prevention:** Even without full retry logic, add a `processing_started_at` timestamp column. The poller should additionally pick up documents where:

```sql
WHERE summary_status = 'in_progress'
AND processing_started_at < NOW() - INTERVAL '30 minutes'
```

This resets stale locks without implementing full retry. Pair with a separate `summary_error` text column to record what failed, written in the exception handler before marking `summary_status = 'failed'`.

**Detection:**
- `SELECT COUNT(*) WHERE summary_status = 'in_progress' AND processing_started_at < NOW() - INTERVAL '1 hour'` returns non-zero
- Frontend shows documents that never transition from "processing"

**Phase:** Phase 1 (schema design). Add `processing_started_at` and `summary_error` columns from the start; do not defer this to "when retries are built."

---

### Pitfall 3: boto3 Blocking the asyncio Event Loop

**What goes wrong:** boto3 (the AWS SDK used by the existing ingestion-service for Bedrock) is entirely synchronous. Calling `bedrock_client.invoke_model(...)` inside an `async def` function blocks the entire asyncio event loop for the duration of the HTTP round-trip (typically 2–15 seconds per Claude call). When 40 calls are batched with `asyncio.gather()`, each one queues behind the others, serializing what should be parallel execution and stalling all FastAPI request handling in the same process.

**Why it happens:** Python's `async def` does not make blocking I/O non-blocking. boto3 uses the `urllib3` stack which issues a real blocking `socket.recv()`. The event loop cannot interleave other coroutines while one coroutine is blocked in kernel I/O.

**Consequences:**
- `asyncio.gather()` on 40 Claude calls does not actually run in parallel — it runs serially
- FastAPI health checks, topic CRUD endpoints, and status polling all hang during document processing
- Per-document processing time is 40× longer than expected (sequential instead of parallel)

**Prevention:** Wrap every boto3 call in `asyncio.to_thread()` (Python 3.9+):

```python
response = await asyncio.to_thread(
    bedrock_client.invoke_model,
    modelId=model_id,
    body=json.dumps(payload),
)
```

This offloads the blocking call to the default thread pool executor without blocking the event loop. All 40 calls via `asyncio.gather()` then truly run concurrently. The existing ingestion-service uses the same boto3 pattern inside Temporal activities (which are synchronous by design), so this pitfall does not exist there — it appears for the first time in vdr-agent's async context.

**Detection:**
- FastAPI `/health` endpoint is slow or times out during heavy processing
- CPU is near-idle during "parallel" Claude calls (serialization prevents true concurrency)
- `asyncio.get_event_loop().is_running()` check + profiling shows long gaps with no task switches

**Phase:** Phase 1 (Bedrock client wrapper). Must be built correctly from day one; performance cannot be validated until this is right.

---

### Pitfall 4: DB Connection Pool Exhaustion from Polling + API Serving

**What goes wrong:** The polling loop holds a DB connection for the duration of document processing (the status claim, then fetching chunks, then writing results). With ~40 Claude API calls averaging 5–15 seconds each, a single document processing run holds a connection for 2–10 minutes. Meanwhile, incoming API requests (topic CRUD, status queries) also need connections. The shared PostgreSQL cluster has finite connections, and the existing ingestion-service already uses 10–40 connections per worker.

**Why it happens:** The existing `PostgresClient` in `ingestion-service/app/db/clients/postgres_client.py` is a single synchronous connection per instance — not a pool. If vdr-agent follows the same pattern with sync psycopg3 and holds a connection across the full document processing lifecycle, connection exhaustion under load is nearly certain.

**Consequences:**
- API endpoints return 503 (DB connection timeout) during heavy processing
- Polling loop itself starves if it cannot acquire a connection for the status-claim query
- PostgreSQL `max_connections` exceeded, causing connection refused errors

**Prevention:**
- Use `psycopg_pool.AsyncConnectionPool` with a small pool (min=2, max=8 for vdr-agent)
- Acquire connections for the minimum required scope: claim a document → release connection → process with Bedrock → re-acquire to write results
- Never hold a connection across Claude API calls. The pattern should be: `async with pool.connection() as conn: claim_document()` then process outside the `with` block.
- Set `pool_timeout` (time to wait for an available connection) to fail fast rather than queue indefinitely

**Detection:**
- psycopg3 raises `PoolTimeout` exception during processing spikes
- PostgreSQL `pg_stat_activity` shows vdr-agent holding idle connections for minutes
- `SELECT count(*) FROM pg_stat_activity WHERE application_name = 'vdr-agent'` grows unboundedly

**Phase:** Phase 1 (DB client setup). Connection pooling must be designed before any polling or processing logic is written.

---

### Pitfall 5: Bedrock TPM Quota Exhaustion from Burst Parallelism

**What goes wrong:** Processing one document fires ~40 Claude calls simultaneously via `asyncio.gather()`. Each call has a `max_tokens` reservation that counts against the per-minute TPM quota before the response arrives (Bedrock pre-allocates output quota at a 5:1 burn rate: 1 output token = 5 input tokens worth of quota). On fresh AWS accounts, default on-demand quotas can be as low as 2–10 RPM. Even on accounts with higher quotas, starting 40 simultaneous requests causes a burst spike that triggers `ThrottlingException` on most of the batch.

**Why it happens:** Bedrock enforces throttling at both RPM and TPM dimensions simultaneously. Burst concurrency — many requests starting within the same second — is more likely to trigger throttling than the same requests spread over time, even if the per-minute total is the same. The `max_tokens` parameter is particularly dangerous: setting it to 4096 "for safety" reserves 20,480 quota tokens per call (4096 × 5), not 4096.

**Consequences:**
- Most of the 40 parallel calls fail with `ThrottlingException` (HTTP 429)
- Without retry logic (explicitly deferred in the project spec), all 429 errors are silently skipped
- Document ends up with partial results (some topic fitments missing)
- Repeated processing attempts exhaust quota further

**Prevention:**
- Adopt the semaphore-based rate limiter already built in ingestion-service (`GlobalRateLimiter`). Port or reference it directly — do not build a new one.
- Set `max_concurrent` to 5–10 for the initial implementation; increase after measuring actual quota headroom
- Set `max_tokens` to the minimum needed for each call type (summaries ≠ fitment evaluations)
- Stagger call starts with `asyncio.sleep(0)` between `gather()` groups or use `asyncio.Semaphore`
- Request quota increases via AWS Service Quotas console before processing large backlogs
- Log every 429 with document ID and call type so partial failures are visible

**Detection:**
- Bedrock returns `ThrottlingException` or HTTP 429 in logs
- Fitment results for a document have fewer rows than the number of active topics
- AWS Bedrock quota monitoring dashboard shows burst spikes at document processing start times

**Phase:** Phase 2 (parallel Claude calls). The rate limiter must be in place before the first multi-document processing run.

---

## Moderate Pitfalls

---

### Pitfall 6: asyncio Task Leak from Unmanaged Background Loop

**What goes wrong:** If the polling loop is launched with `asyncio.create_task()` and the task reference is not stored, Python's garbage collector may silently cancel it (Python 3.10+ emits a warning, but older Python discards it silently). Alternatively, if the task crashes with an unhandled exception and no `done_callback` is registered, the exception is silently swallowed and the loop stops — with no indication in logs.

**Why it happens:** `asyncio.create_task()` returns a `Task` object. Without storing a reference, the coroutine is eligible for GC. Even when stored, an unhandled exception in the coroutine causes the task to enter a "failed" state that is only surfaced if `.result()` is called or a done callback inspects it.

**Consequences:**
- Polling silently stops; no new documents are processed; frontend shows no progress
- Service appears healthy (FastAPI responds to requests), but processing has halted

**Prevention:**
- Store the task reference in `app.state.polling_task = asyncio.create_task(poll_loop())`
- Register a done callback: `polling_task.add_done_callback(log_task_result)` that logs any exception
- Wrap the poll loop body in `try/except Exception as e: logger.error(...)` and re-raise or restart
- In the FastAPI lifespan `finally` block: `polling_task.cancel(); await polling_task`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(poll_loop())
    task.add_done_callback(lambda t: logger.error("Poller crashed: %s", t.exception()) if not t.cancelled() and t.exception() else None)
    app.state.polling_task = task
    yield
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=10.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
```

**Detection:**
- No new documents are processed despite `embedding_status = 'done'` rows in DB
- Python warning: `Task was destroyed but it is pending!`
- No polling log entries in application logs

**Phase:** Phase 1 (polling loop foundation).

---

### Pitfall 7: Sync psycopg3 Connection Used in Async Code Path

**What goes wrong:** The ingestion-service uses synchronous psycopg3 (`psycopg.connect()`, synchronous cursors). vdr-agent will naturally copy this pattern. If sync psycopg3 connections are used inside `async def` functions without `asyncio.to_thread()`, every DB query blocks the event loop for its network round-trip, serializing all concurrent operations.

**Why it happens:** psycopg3 ships both `psycopg.connect()` (sync) and `psycopg.AsyncConnection.connect()` (async). The sync version works correctly inside sync def functions or Temporal activities (which run in threads). In async def context, it blocks.

**Consequences:**
- Same symptom as Pitfall 3 (boto3 blocking): API endpoints stall during DB operations
- Health checks fail under load
- The 10 parallel section-summary calls effectively serialize through DB status writes

**Prevention:** Choose one of two approaches and apply it consistently:
1. Use `psycopg.AsyncConnection` + `psycopg_pool.AsyncConnectionPool` throughout vdr-agent (preferred for new code)
2. Wrap all sync psycopg3 calls in `asyncio.to_thread()` (acceptable if DAO pattern is reused from ingestion-service)

Do not mix async and sync psycopg3 connections in the same service.

**Detection:**
- FastAPI endpoint latency spikes during DB write operations
- Profiler shows long gaps in event loop with no task switching during `cursor.execute()`

**Phase:** Phase 1 (DB client). Decision must be made before any DAO code is written.

---

### Pitfall 8: Large Document Chunk Payloads Causing Memory Pressure

**What goes wrong:** Each document's embedding chunks are fetched from PostgreSQL and held in memory while 10 parallel section-summary Claude calls are active. A 1,000-page document could have 100+ chunks of several KB each, plus each Claude response (the combined summary can be several KB). Multiplied by several documents processing concurrently, memory grows quickly without explicit bounds.

**Why it happens:** `asyncio.gather()` holds all task coroutines in memory simultaneously. Fetching all chunks in one `SELECT *` query loads the entire document into memory at once. Without pagination or streaming, the heap grows proportionally to document size.

**Consequences:**
- OOMKilled in Kubernetes (likely, given existing ingestion-service Helm chart pattern)
- Slow GC pauses as large byte strings are collected between documents
- Python process memory grows unboundedly in long-running polling loops

**Prevention:**
- Fetch chunks lazily: retrieve only the chunk IDs first, then fetch content per-chunk inside each Claude task
- Bound concurrency with `asyncio.Semaphore(10)` to cap simultaneous in-memory payloads
- After each document completes, explicitly `del chunk_data` and `gc.collect()` if memory pressure is observed
- Set Kubernetes `resources.limits.memory` conservatively and monitor with `kubectl top pod`

**Detection:**
- Python process RSS grows monotonically over hours in the polling loop
- OOMKilled pod events in Kubernetes
- `tracemalloc` snapshot shows chunk byte strings dominating heap

**Phase:** Phase 2 (parallel Claude call implementation). Test with a large document (100+ pages) during development.

---

### Pitfall 9: Fitment Re-run on Topic Change Causes Duplicate Concurrent Processing

**What goes wrong:** When a topic instruction changes, the system should re-run fitment for that topic only. If a document is also currently being processed by the main polling loop at the same moment, two concurrent writes to the same `(document_id, topic_id)` fitment row can occur. Without a unique constraint or explicit conflict handling, the last writer wins and the result is non-deterministic.

**Why it happens:** The polling loop and the re-run trigger are independent code paths that may overlap. Without row-level locking or `INSERT ... ON CONFLICT DO UPDATE` semantics, both will `INSERT` or `UPDATE` the fitment row simultaneously.

**Consequences:**
- Non-deterministic fitment results
- Duplicate fitment rows if using `INSERT` without `ON CONFLICT`
- Results from stale topic instruction used if new instruction's re-run loses the race

**Prevention:**
- Use `INSERT INTO fitment_results (...) VALUES (...) ON CONFLICT (document_id, topic_id) DO UPDATE SET ...`
- Add `UNIQUE (document_id, topic_id)` constraint to the fitment table at migration time
- Serialize re-run requests: write a `topic_rerun_queue` table entry and process it in the same polling loop, not via a separate code path

**Detection:**
- `SELECT count(*) ... GROUP BY document_id, topic_id HAVING count(*) > 1` returns rows
- Fitment results appear to revert after topic instruction changes

**Phase:** Phase 3 (topic instruction re-run). Design the re-run mechanism to go through the same queue, not a parallel fast path.

---

## Minor Pitfalls

---

### Pitfall 10: Unbounded Polling Batch Size Under Load

**What goes wrong:** The polling query fetches all documents with `summary_status IS NULL` (or a large batch) in one query. With 1,000+ pending documents, this query returns a massive result set that is processed sequentially. If the service restarts mid-batch, all those documents were never claimed (no status update), so the next restart re-fetches the same large batch.

**Prevention:** Always use `LIMIT N` on the polling query (N = 5 to 20 is reasonable for this concurrency profile). Process the batch, then loop. This bounds memory per iteration and makes progress incremental.

**Phase:** Phase 1.

---

### Pitfall 11: Missing Index on Polling Query

**What goes wrong:** `WHERE summary_status IS NULL AND embedding_status = 'done'` performs a full sequential scan on large tables without an index on these columns. As the document table grows to 1,000+ rows, every polling iteration incurs an expensive scan.

**Prevention:** Add a partial index at migration time:

```sql
CREATE INDEX idx_documents_pending_summary
ON vdr_agent.documents (created_at ASC)
WHERE embedding_status = 'done' AND summary_status IS NULL;
```

**Phase:** Phase 1 (schema migration).

---

### Pitfall 12: Polling Loop Sleep Interval Too Short or Too Long

**What goes wrong:** A polling interval of 1 second on a 1,000-document backlog wastes DB resources with repeated no-op queries. An interval of 5 minutes means newly ingested documents wait 5 minutes before processing starts.

**Prevention:** Start with a 10-second poll interval for batch-backlog scenarios. For near-realtime requirements, consider exponential backoff: if no documents found → double sleep (max 60s); if documents found → reset to 5s.

**Phase:** Phase 1.

---

### Pitfall 13: Silent Claude Response Truncation

**What goes wrong:** Bedrock Claude responses are truncated when output hits `max_tokens`. The truncated response is a valid JSON string (no error raised), but the content is incomplete. If the summarisation prompt requests structured JSON output, truncation silently produces malformed JSON that passes parsing with missing fields.

**Prevention:**
- Check `response['stop_reason'] == 'max_tokens'` on every Bedrock response and log a warning
- Set `max_tokens` to 2× the expected output size per call type, not a uniform global default
- Test with a real large document and inspect `stop_reason` values during development

**Phase:** Phase 2 (Claude client wrapper).

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Initial polling loop | Duplicate processing (Pitfall 1) | `FOR UPDATE SKIP LOCKED` from day one |
| Status column design | Stuck `in_progress` (Pitfall 2) | Add `processing_started_at` + `summary_error` at schema time |
| DB client choice | Sync psycopg3 in async (Pitfall 7) | Decide sync-vs-async before writing any DAO |
| Connection management | Pool exhaustion (Pitfall 4) | Do not hold connections across Claude calls |
| First Claude call | boto3 blocking (Pitfall 3) | Wrap in `asyncio.to_thread()` in the Bedrock client |
| Parallel section summaries | Bedrock quota burst (Pitfall 5) | Port rate limiter from ingestion-service; cap concurrency |
| Background task startup | Task leak on crash (Pitfall 6) | Store task ref; register done callback; cancel in lifespan |
| Large documents | Memory exhaustion (Pitfall 8) | Fetch chunks lazily; bound concurrency |
| Topic re-run feature | Duplicate write race (Pitfall 9) | `ON CONFLICT DO UPDATE` + queue-based re-run |
| Schema creation | Slow polling scan (Pitfall 11) | Partial index on status columns |

---

## Sources

- [The Unreasonable Effectiveness of SKIP LOCKED in PostgreSQL](https://www.inferable.ai/blog/posts/postgres-skip-locked) — MEDIUM confidence (community article, consistent with PostgreSQL docs)
- [PostgreSQL Advisory Locks for Concurrency-Safe Workflows](https://appmaster.io/blog/postgresql-advisory-locks-double-processing) — MEDIUM confidence
- [PostgreSQL Documentation: Explicit Locking](https://www.postgresql.org/docs/current/explicit-locking.html) — HIGH confidence (official docs)
- [Understanding Pitfalls of Async Task Management in FastAPI](https://leapcell.io/blog/understanding-pitfalls-of-async-task-management-in-fastapi-requests) — MEDIUM confidence
- [Python and boto3 Performance: Synchronous vs Asynchronous](https://joelmccoy.medium.com/python-and-boto3-performance-adventures-synchronous-vs-asynchronous-aws-api-interaction-22f625ec6909) — MEDIUM confidence (31% throughput improvement with `asyncio.to_thread()`)
- [psycopg3 Connection Pools Documentation](https://www.psycopg.org/psycopg3/docs/advanced/pool.html) — HIGH confidence (official psycopg3 docs)
- [AWS Bedrock Quotas — Token Burndown](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html) — HIGH confidence (official AWS docs)
- [Understanding Bedrock TPM Deductions with Parallel Workflows](https://repost.aws/questions/QU41JbEn0NStC1P3KB6cd5UA/understanding-bedrock-tpm-deductions-getting-too-many-tokens-with-parallel-langgraph-workflows) — MEDIUM confidence (AWS re:Post)
- [Cancelable tasks cannot safely use semaphores — Python discussion](https://discuss.python.org/t/cancelable-tasks-cannot-safely-use-semaphores/70949) — HIGH confidence (Python core discussion)
- [Why Claude 4 API Hits Rate Limits: Token Burndown Explained](https://builder.aws.com/content/2xVZmCM5E7XXw0yqTEGgXYxRowk/why-claude-4-api-hits-rate-limits-token-burndown-explained) — MEDIUM confidence (AWS Builder Center)
- [12 FastAPI Anti-Patterns Quietly Killing Throughput](https://medium.com/@Modexa/12-fastapi-anti-patterns-quietly-killing-throughput-bddaa961634a) — LOW confidence (unverified Medium article, consistent with official FastAPI docs)
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/) — HIGH confidence (official FastAPI docs)
- Ingestion-service codebase analysis: `ingestion-service/app/core/llm/rate_limiter.py`, `ingestion-service/app/db/clients/postgres_client.py`, `ingestion-service/CLAUDE.md` — HIGH confidence (direct code inspection)
- `.planning/codebase/CONCERNS.md` — HIGH confidence (existing project analysis)
