# Phase 5: Polling Loop - Research

**Researched:** 2026-03-05
**Domain:** asyncio background task, PostgreSQL FOR UPDATE SKIP LOCKED, cross-schema polling
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Document detection strategy
- **Two-step approach**: First detect new documents from `ai_rag.documents`, then insert + claim
  1. Query `ai_rag.documents WHERE embedding_status = 'completed' AND id NOT IN (SELECT document_id FROM vdr_agent.processing_state)` to find unregistered docs
  2. Call `ProcessingStateDAO.insert(document_id)` for each new doc — reuses existing `ON CONFLICT DO NOTHING` idempotency
  3. Call `ProcessingStateDAO.claim_documents(limit)` to atomically claim pending/failed rows
- Detection query must cross-schema (ai_rag → vdr_agent) — works because `search_path = vdr_agent, ai_rag, public` is set on the connection pool
- New detection query goes in a new method `ProcessingStateDAO.find_unregistered_documents(limit: int) -> List[UUID]` — returns document_ids not yet in processing_state

#### Batch concurrency model
- **Fire-and-forget with `asyncio.create_task`** per claimed document
- Poll loop does NOT await processing — each document gets its own task
- Poll loop stores task references to prevent GC and add done callbacks for logging
- `GlobalRateLimiter` (max 10 concurrent Bedrock calls) naturally throttles throughput across all in-flight tasks
- Next poll cycle can start while previous batch documents are still processing (maximises throughput for 1000+ docs)

#### Phase 5 processor stub
- Create `app/worker/processor.py` with `async def process_document(processing_state_id: UUID, document_id: UUID) -> None`
- Phase 5 stub: log receipt, then set `summary_status = 'done'` via `ProcessingStateDAO.update_status()` — simulates a completed document so the poll loop can be tested end-to-end
- Phase 6 replaces the stub body with real AI logic — poller.py interface stays unchanged
- Poller calls: `asyncio.create_task(process_document(ps_id, doc_id))`

#### Poller module structure
- New directory `app/worker/` for background task modules
- `app/worker/poller.py` — `async def run_poller() -> None` coroutine with poll loop
- `app/worker/processor.py` — `async def process_document(processing_state_id, document_id)` stub
- Wired into `startup.py` lifespan: `task = asyncio.create_task(run_poller())` before `yield`; task stored and cancelled in shutdown with `task.cancel(); await task`
- Done callback: `task.add_done_callback(lambda t: logger.info("poller task exited: %s", t.exception() or 'clean'))`

#### Config fields
- Three new fields added to `app/config/__init__.py`:
  - `poll_interval_seconds: int = 10` — env var `VDR_AGENT_POLL_INTERVAL_SECONDS`
  - `poll_batch_size: int = 5` — env var `VDR_AGENT_POLL_BATCH_SIZE`
  - `stale_lock_threshold_minutes: int = 30` — env var `VDR_AGENT_STALE_LOCK_THRESHOLD_MINUTES`
- Consistent with existing `VDR_AGENT_` prefix pattern; each tunable independently

#### Poll cycle logic
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

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROC-01 | System polls for documents with completed embeddings and no AI summary using `FOR UPDATE SKIP LOCKED` (atomic claim, no duplicates) | `ProcessingStateDAO.claim_documents()` already implements FOR UPDATE SKIP LOCKED; `find_unregistered_documents()` is the new query to add; asyncio background task via `asyncio.create_task(run_poller())` covers the autonomous polling requirement |
</phase_requirements>

---

## Summary

Phase 5 implements the autonomous background polling loop that bridges the ingestion-service document pipeline and the vdr-agent AI processing pipeline. The infrastructure — FOR UPDATE SKIP LOCKED claiming, stale lock recovery, and status tracking — was built in Phases 2 and 3. Phase 5 assembles these pieces into a running loop wired into FastAPI's lifespan.

The primary technical challenge is the cross-schema detection query: `ai_rag.documents` must be queried for documents not yet registered in `vdr_agent.processing_state`. This works without any special configuration because `search_path = vdr_agent, ai_rag, public` is set on every pooled connection in `pool.py`. The query uses `NOT IN (SELECT document_id FROM vdr_agent.processing_state)` to find the gap. The Phase 3 DAO already provides `insert()` with `ON CONFLICT DO NOTHING` for idempotent registration.

**Critical schema finding:** The CONTEXT.md references `ai_rag.documents WHERE embedding_status = 'completed'` but the actual `ai_rag.documents` column is `status` (not `embedding_status`). Verified from V3 ingestion-service migration: the column is `status TEXT DEFAULT 'uploaded'` with CHECK constraint `status IN ('pending', 'uploaded', 'processing', 'completed', 'failed', 'deleted', 'skipped')`. The correct query predicate is `WHERE status = 'completed'`. This is the sentinel value set by ingestion-service when a document has completed its full pipeline including embeddings.

**Primary recommendation:** Use `WHERE status = 'completed'` (not `embedding_status = 'completed'`) when querying `ai_rag.documents` in `find_unregistered_documents()`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python asyncio | stdlib (3.12) | Background task via `asyncio.create_task()` | Built-in, already used in startup.py; no external dep needed |
| FastAPI lifespan | >=0.115 | Async context manager for startup/shutdown hooks | Already wired in startup.py; poller task slots in before `yield` |
| psycopg3 (psycopg) | 3.3.3 | PostgreSQL FOR UPDATE SKIP LOCKED | Already installed; existing DAOs use this exact pattern |
| psycopg-pool | >=3.2 | Async connection pool | Already installed as `AsyncConnectionPool` in pool.py |
| pydantic-settings | >=2.0 | Config fields with env-var binding | Already in use with `VDR_AGENT_` prefix pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python logging | stdlib | Structured log output per cycle | All log calls use module-level `LOGGER = logging.getLogger(__name__)` |
| asyncio.CancelledError | stdlib | Clean shutdown detection in poller loop | Must be caught in the poll loop to allow clean cancellation |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| asyncio background task | APScheduler, Celery, Temporal | Zero additional deps; no infra overhead; sufficient for DB polling pattern |
| FOR UPDATE SKIP LOCKED | Redis lock, pessimistic retry | DB-native; no extra infra; already proven in claim_documents() |
| asyncio.create_task per doc | asyncio.gather() with limit | create_task is fire-and-forget; GlobalRateLimiter provides natural throttle |

**Installation:** No new packages required — all dependencies already in `pyproject.toml`.

---

## Architecture Patterns

### Recommended Project Structure
```
vdr-agent/app/
├── worker/              # New directory — background task modules
│   ├── __init__.py      # Empty init
│   ├── poller.py        # run_poller() coroutine with poll loop
│   └── processor.py     # process_document() stub (Phase 5) / real impl (Phase 6)
├── config/__init__.py   # Add 3 new Settings fields (poll_interval, batch_size, stale_threshold)
└── startup.py           # Wire poller task into lifespan before yield
```

### Pattern 1: asyncio Background Task in FastAPI Lifespan

**What:** Start a long-running coroutine as an `asyncio.Task` before the `yield` in the lifespan context manager. Store the task reference to prevent garbage collection. Cancel and await it on shutdown.

**When to use:** Any autonomous background work that should run for the application's lifetime and be cancelled cleanly on SIGTERM/SIGINT.

**Example:**
```python
# app/startup.py — modified lifespan (Pattern: before yield = startup, after yield = shutdown)
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db.pool import DatabasePool
from app.worker.poller import run_poller

LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    LOGGER.info("vdr-agent starting env=%s log_level=%s", settings.env, settings.log_level)

    executor = ThreadPoolExecutor(max_workers=50, thread_name_prefix="bedrock")
    loop = asyncio.get_event_loop()
    loop.set_default_executor(executor)

    await DatabasePool.initialize(
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        min_size=2,
        max_size=10,
    )

    # Phase 5: Start poller as background task
    poller_task = asyncio.create_task(run_poller())
    poller_task.add_done_callback(
        lambda t: LOGGER.info(
            "poller task exited: %s",
            t.exception() if not t.cancelled() else "cancelled"
        )
    )

    yield

    # Shutdown: cancel poller, close pool
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    await DatabasePool.close()
    LOGGER.info("vdr-agent shutdown complete")
```

### Pattern 2: Poll Loop with CancelledError Guard

**What:** An infinite `while True` loop inside a try/except that catches `asyncio.CancelledError` for clean exit and any other exception to continue polling.

**When to use:** Background poller that must survive transient errors (DB blips, network) but stop cleanly when cancelled.

**Example:**
```python
# app/worker/poller.py
from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.db.dao.processing_state_dao import ProcessingStateDAO

LOGGER = logging.getLogger(__name__)


async def run_poller() -> None:
    """Autonomous poll loop — runs for the application's lifetime.

    Each cycle:
      1. Reset stale processing rows (crashed workers)
      2. Detect + register new documents from ai_rag.documents
      3. Claim pending/failed rows atomically (FOR UPDATE SKIP LOCKED)
      4. Fire asyncio.create_task per claimed document
      5. Sleep poll_interval_seconds
    """
    settings = get_settings()
    LOGGER.info(
        "Poller started: interval=%ds batch=%d stale_threshold=%dmin",
        settings.poll_interval_seconds,
        settings.poll_batch_size,
        settings.stale_lock_threshold_minutes,
    )

    # Module-level set to hold task references and prevent GC
    active_tasks: set[asyncio.Task] = set()

    while True:
        try:
            await _poll_cycle(settings, active_tasks)
        except asyncio.CancelledError:
            LOGGER.info("Poller received cancellation — exiting")
            raise  # Must re-raise to propagate cancellation
        except Exception:
            LOGGER.exception("Uncaught error in poll cycle — continuing after sleep")

        await asyncio.sleep(settings.poll_interval_seconds)


async def _poll_cycle(settings, active_tasks: set) -> None:
    from app.worker.processor import process_document

    # Step 1: Reset stale claims
    reset_count = await ProcessingStateDAO.reset_stale_claims(
        settings.stale_lock_threshold_minutes
    )
    if reset_count:
        LOGGER.warning("Reset %d stale processing row(s)", reset_count)

    # Step 2+3: Detect and register new documents
    new_doc_ids = await ProcessingStateDAO.find_unregistered_documents(
        settings.poll_batch_size
    )
    for doc_id in new_doc_ids:
        await ProcessingStateDAO.insert(doc_id)
    if new_doc_ids:
        LOGGER.info("Registered %d new document(s)", len(new_doc_ids))

    # Step 4: Claim pending/failed rows atomically
    claimed = await ProcessingStateDAO.claim_documents(settings.poll_batch_size)
    if not claimed:
        LOGGER.debug("No documents to process this cycle")
        return

    LOGGER.info("Claimed %d document(s) for processing", len(claimed))

    # Step 5: Fire-and-forget per document
    for ps_id, doc_id in claimed:
        task = asyncio.create_task(process_document(ps_id, doc_id))
        active_tasks.add(task)
        task.add_done_callback(active_tasks.discard)
        task.add_done_callback(
            lambda t, pid=ps_id: LOGGER.debug(
                "process_document task done ps_id=%s err=%s",
                pid,
                t.exception() if not t.cancelled() and not t.exception() is None else None,
            )
        )
```

### Pattern 3: Cross-Schema Detection Query

**What:** Query `ai_rag.documents` for rows not yet in `vdr_agent.processing_state` using a correlated NOT IN subquery, within the existing connection pool (search_path already set).

**When to use:** Finding documents that have completed ingestion pipeline but are not yet tracked for AI processing.

**Example:**
```python
# app/db/dao/processing_state_dao.py — new method

@staticmethod
async def find_unregistered_documents(limit: int = 5) -> List[UUID]:
    """Find document IDs from ai_rag.documents not yet in vdr_agent.processing_state.

    Queries across schemas — works because search_path = vdr_agent, ai_rag, public
    is set on every pooled connection in pool.py configure().

    IMPORTANT: The ai_rag.documents column is `status` (not `embedding_status`).
    The value 'completed' means the full pipeline including embeddings has run.

    Returns at most `limit` document IDs to bound the INSERT loop.
    """
    sql = """
        SELECT d.id
        FROM ai_rag.documents d
        WHERE d.status = 'completed'
          AND d.id NOT IN (
              SELECT ps.document_id
              FROM vdr_agent.processing_state ps
          )
        LIMIT %s
    """
    async with DatabasePool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, (limit,))
            rows = await cur.fetchall()
    return [row["id"] for row in rows]
```

### Pattern 4: Phase 5 Processor Stub

**What:** A no-op processor that marks the document as `done` immediately, allowing the full poller lifecycle to be exercised without AI calls.

**When to use:** Phase 5 only. Phase 6 replaces the body; the function signature stays the same.

**Example:**
```python
# app/worker/processor.py
from __future__ import annotations

import logging
from uuid import UUID

from app.db.dao.processing_state_dao import ProcessingStateDAO

LOGGER = logging.getLogger(__name__)


async def process_document(processing_state_id: UUID, document_id: UUID) -> None:
    """Process a single document — Phase 5 stub.

    Logs receipt and marks processing_state as 'done' immediately.
    Phase 6 replaces this body with real AI summary logic.
    Interface (processing_state_id, document_id) is fixed — poller.py unchanged.
    """
    LOGGER.info(
        "process_document stub: ps_id=%s doc_id=%s → done",
        processing_state_id,
        document_id,
    )
    await ProcessingStateDAO.update_status(processing_state_id, "done")
```

### Pattern 5: Config Field Addition

**What:** Add three pydantic-settings fields to `Settings` class with `VDR_AGENT_` prefix (auto-applied from `model_config["env_prefix"]`).

**Example:**
```python
# app/config/__init__.py — add to Settings class body

poll_interval_seconds: int = Field(
    default=10,
    description="Poll loop sleep interval in seconds — override with VDR_AGENT_POLL_INTERVAL_SECONDS",
)
poll_batch_size: int = Field(
    default=5,
    description="Max documents per poll batch — override with VDR_AGENT_POLL_BATCH_SIZE",
)
stale_lock_threshold_minutes: int = Field(
    default=30,
    description="Minutes before processing row is considered stale — override with VDR_AGENT_STALE_LOCK_THRESHOLD_MINUTES",
)
```

### Anti-Patterns to Avoid

- **SELECT then UPDATE as separate transactions:** Never do a plain SELECT to find documents then a separate UPDATE in a new transaction to claim them. This is a race condition between two vdr-agent instances. `claim_documents()` does both in one transaction.
- **Holding a DB connection across `asyncio.sleep()`:** Never hold a connection context manager open during the sleep interval. All DAO methods open and close their own connections inside `DatabasePool.connection()`.
- **Not re-raising `asyncio.CancelledError`:** Always `raise` after catching `CancelledError` in the poll loop. Swallowing it prevents clean shutdown and causes FastAPI to hang on SIGTERM.
- **Not storing task references:** `asyncio.create_task()` returns a Task that can be garbage collected if no reference is held. Always add to a set and use `add_done_callback(active_tasks.discard)` to clean up naturally.
- **Using NOT EXISTS instead of NOT IN for small processing_state tables:** For the initial phase with modest document counts, NOT IN is readable and correct. If processing_state grows to millions of rows, a LEFT JOIN / IS NULL or NOT EXISTS may perform better. Flag for future review at scale.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic claim with duplicate prevention | Custom lock table, pessimistic retry loop | `FOR UPDATE SKIP LOCKED` in `ProcessingStateDAO.claim_documents()` | Already implemented in Phase 3; DB-native locking is race-condition-proof |
| Stale lock detection | Background watchdog process | `reset_stale_claims()` called at top of each poll cycle | Already implemented in Phase 3; simpler and already tested |
| Idempotent document registration | Custom de-dup logic | `ProcessingStateDAO.insert()` with `ON CONFLICT DO NOTHING` | Already implemented in Phase 3; handles all race conditions |
| Config with env-var override | Custom `os.getenv()` calls | Pydantic `Field()` on `Settings` with `env_prefix` | Already in use; consistent with all other settings |
| Background task lifecycle | Custom signal handler | FastAPI lifespan `asyncio.create_task()` + cancel on shutdown | Established pattern; startup.py already has the comment placeholder |

**Key insight:** Almost every building block for Phase 5 was deliberately pre-built in Phases 2 and 3. Phase 5 is an assembly task, not a construction task. The only genuinely new code is `find_unregistered_documents()`, the `app/worker/` directory, and the lifespan wiring.

---

## Common Pitfalls

### Pitfall 1: Wrong Column Name for Document Status
**What goes wrong:** Query uses `embedding_status = 'completed'` but the actual column in `ai_rag.documents` is `status`. psycopg3 will raise `UndefinedColumn` at runtime.
**Why it happens:** CONTEXT.md used `embedding_status` as a descriptive phrase, but the V3 ingestion-service migration defines `status TEXT DEFAULT 'uploaded'`.
**How to avoid:** Use `WHERE d.status = 'completed'` in `find_unregistered_documents()`. Confirmed from `/Users/sanchayjain/Desktop/ERM/ingestion-service/migrations/flyway/V3__documents_and_embeddings.sql` line 26.
**Warning signs:** `psycopg.errors.UndefinedColumn: column d.embedding_status does not exist` in logs at first poll cycle.

### Pitfall 2: Swallowing CancelledError in Poll Loop
**What goes wrong:** The poll loop catches `Exception` broadly (good for transient errors) but also catches `asyncio.CancelledError` if it inherits from `Exception` in Python 3.7. In Python 3.8+, `CancelledError` inherits from `BaseException` not `Exception`, so a bare `except Exception` will NOT catch it. However, wrapping the entire `while True` block in `try/except Exception` and forgetting to also handle `CancelledError` can leave unclear semantics.
**Why it happens:** Forgetting that `await asyncio.sleep()` raises `CancelledError` when the task is cancelled.
**How to avoid:** Always have an explicit `except asyncio.CancelledError: raise` before the general `except Exception` handler. The recommended pattern in Code Examples shows this correctly.
**Warning signs:** FastAPI hangs on shutdown; `poller_task.cancel()` in lifespan shutdown never resolves; SIGTERM timeout.

### Pitfall 3: GC of In-Flight Task References
**What goes wrong:** `asyncio.create_task(process_document(...))` creates a task but the reference is not stored. Python's garbage collector can collect the Task object, which logs a warning "Task was destroyed but it is pending!" and the processing coroutine is silently abandoned.
**Why it happens:** `create_task()` returns a Task but does not hold a strong reference itself; only the event loop holds a weak reference.
**How to avoid:** Maintain `active_tasks: set[asyncio.Task]` at the poll loop scope; add each task to the set; use `task.add_done_callback(active_tasks.discard)` to remove it when done.
**Warning signs:** Log line "Task was destroyed but it is pending!" from asyncio internals; processing_state rows stuck in `processing` status.

### Pitfall 4: Two poll cycles claiming the same document
**What goes wrong:** If `poll_interval_seconds` is very short and `claim_documents()` takes longer than the interval, a second cycle might start before the first finishes. Since `claim_documents()` uses FOR UPDATE SKIP LOCKED, the second cycle will skip the already-locked row and claim a different one — this is correct behavior. But if the developer is confused and adds an extra plain SELECT check, they re-introduce the race condition.
**Why it happens:** Misunderstanding that SKIP LOCKED alone is sufficient; adding defensive checks outside the transaction breaks the guarantee.
**How to avoid:** Never add any SELECT after `claim_documents()` to re-verify ownership. The atomic claim is the single source of truth.
**Warning signs:** Duplicate processing of the same document; two `process_document` tasks with the same `ps_id`.

### Pitfall 5: NOT IN subquery performance with large processing_state table
**What goes wrong:** `id NOT IN (SELECT document_id FROM vdr_agent.processing_state)` scans the entire processing_state table on each poll cycle. With 1000+ documents fully processed (status = 'done'), this grows over time.
**Why it happens:** NOT IN materializes the full subquery result before filtering.
**How to avoid:** For Phase 5 (modest volume), NOT IN is fine. Add a comment noting that if processing_state exceeds 100k rows, replace with `LEFT JOIN / WHERE ps.document_id IS NULL`. The partial index `idx_processing_state_pending_failed` only covers pending/failed — it does not help with the NOT IN scan (which needs all rows including done).
**Warning signs:** Poll cycle CPU spike; slow `find_unregistered_documents()` response; query plan shows sequential scan on processing_state.

### Pitfall 6: Missing `__init__.py` in `app/worker/`
**What goes wrong:** Python cannot import `app.worker.poller` or `app.worker.processor` if `app/worker/__init__.py` does not exist.
**Why it happens:** Forgetting to create the package init file when creating the new directory.
**How to avoid:** Create `app/worker/__init__.py` (empty) as the first task in the plan.
**Warning signs:** `ModuleNotFoundError: No module named 'app.worker'` on startup.

---

## Code Examples

### find_unregistered_documents() — Confirmed SQL Pattern
```python
# Correct column name verified from ingestion-service/migrations/flyway/V3__documents_and_embeddings.sql
# Column: `status TEXT DEFAULT 'uploaded'`
# Value: `'completed'` = full pipeline done including embeddings
sql = """
    SELECT d.id
    FROM ai_rag.documents d
    WHERE d.status = 'completed'
      AND d.id NOT IN (
          SELECT ps.document_id
          FROM vdr_agent.processing_state ps
      )
    LIMIT %s
"""
```

### Lifespan Task Wiring — Confirmed Insertion Point
```python
# app/startup.py — comment on line 23 says exactly:
# "Phase 5 will add document poller task here."
# Insert between loop.set_default_executor() and yield:

poller_task = asyncio.create_task(run_poller())
poller_task.add_done_callback(
    lambda t: LOGGER.info(
        "poller task exited: %s",
        t.exception() if not t.cancelled() else "cancelled",
    )
)

yield  # <-- application runs here

poller_task.cancel()
try:
    await poller_task
except asyncio.CancelledError:
    pass
await DatabasePool.close()
```

### claim_documents() — Already Implemented Reference
```python
# Exact SQL from app/db/dao/processing_state_dao.py (DO NOT MODIFY)
# Uses partial index idx_processing_state_pending_failed — WHERE clause MUST match exactly
select_sql = """
    SELECT id, document_id
    FROM vdr_agent.processing_state
    WHERE summary_status IN ('pending', 'failed')
    ORDER BY created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT %s
"""
```

### Settings Field Addition Pattern
```python
# Existing fields in Settings for reference (VDR_AGENT_ prefix auto-applied):
bedrock_max_concurrent: int = Field(default=10, description="...")
# New fields follow exact same pattern:
poll_interval_seconds: int = Field(default=10, description="...")
poll_batch_size: int = Field(default=5, description="...")
stale_lock_threshold_minutes: int = Field(default=30, description="...")
```

### Module Header Pattern
```python
# Every vdr-agent module starts with this header (established in Phase 1):
from __future__ import annotations

import logging
# ... stdlib imports
# ... third-party imports
# ... local imports

LOGGER = logging.getLogger(__name__)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Polling with SELECT + separate UPDATE | SELECT FOR UPDATE SKIP LOCKED + UPDATE in one txn | Phase 3 implementation | No race condition possible even with N concurrent instances |
| Single-process polling | Fire-and-forget asyncio.create_task per document | Phase 5 design | Poll cycle returns immediately; 1000+ docs can be in-flight concurrently |
| Blocking I/O in async context | boto3 via asyncio.to_thread() | Phase 4 design decision | Event loop never blocks; poller and processors coexist in same process |

**Deprecated/outdated in this context:**
- Temporal workflows: Explicitly out of scope for vdr-agent (STATE.md: "No Temporal in vdr-agent — DB polling with asyncio replaces workflow orchestration")
- Redis/external lock: Not needed; PostgreSQL advisory locks (via FOR UPDATE SKIP LOCKED) are sufficient

---

## Open Questions

1. **Column name discrepancy: `embedding_status` vs `status`**
   - What we know: CONTEXT.md says `WHERE embedding_status = 'completed'` but the actual `ai_rag.documents` column from V3 migration is `status`
   - What's unclear: Whether there is a newer migration that adds an `embedding_status` column separately (not found in any migration file)
   - Recommendation: Use `WHERE d.status = 'completed'` — confirmed from V3__documents_and_embeddings.sql. If the ingestion-service later adds a separate `embedding_status` column, update the query at that time. Add a code comment citing this research finding.

2. **Task reference storage: module-level set vs local set**
   - What we know: CONTEXT.md flags this as Claude's discretion
   - What's unclear: Module-level set persists across poll cycles (correct); function-local set resets each call to `_poll_cycle` (wrong)
   - Recommendation: Use a set defined in `run_poller()` scope (before the while loop), not inside `_poll_cycle`. Pass it as a parameter to `_poll_cycle`. This correctly accumulates tasks across cycles.

3. **Log level for "no documents found" cycle**
   - What we know: CONTEXT.md flags this as Claude's discretion
   - Recommendation: Use `DEBUG` for the no-documents case — at a 10-second interval, this fires 6x per minute and would flood INFO logs with no operational value. Reserve INFO for actual claims and registrations.

---

## Sources

### Primary (HIGH confidence)
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/db/dao/processing_state_dao.py` — existing DAO methods: `claim_documents()`, `reset_stale_claims()`, `insert()`, exact SQL verified
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/startup.py` — exact insertion point comment confirmed on line 23
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/db/pool.py` — `SEARCH_PATH = "vdr_agent, ai_rag, public"` confirmed; cross-schema queries work natively
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/app/config/__init__.py` — `VDR_AGENT_` prefix, `model_config["env_prefix"]`, Field() pattern confirmed
- `/Users/sanchayjain/Desktop/ERM/ingestion-service/migrations/flyway/V3__documents_and_embeddings.sql` — `ai_rag.documents.status` column name and `'completed'` value confirmed (line 26: CHECK constraint)
- `/Users/sanchayjain/Desktop/ERM/vdr-agent/migrations/flyway/V3__create_processing_state_table.sql` — partial index `idx_processing_state_pending_failed` on `WHERE summary_status IN ('pending', 'failed')` confirmed; `claim_documents()` WHERE clause must match exactly

### Secondary (MEDIUM confidence)
- Python asyncio documentation (training knowledge): `asyncio.create_task()` returns a Task that must be stored to prevent GC; `CancelledError` inherits from `BaseException` in Python 3.8+; confirmed consistent with pyproject.toml `python = "^3.12"`
- FastAPI lifespan pattern (training knowledge, verified by existing startup.py): `@asynccontextmanager async def lifespan(app)` with `yield` is the current FastAPI pattern (>=0.93.0)

### Tertiary (LOW confidence)
- None — all critical claims verified from source files

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already installed and in use; no new deps required
- Architecture: HIGH — all patterns verified from existing vdr-agent source code; only new files are `app/worker/poller.py`, `app/worker/processor.py`, `app/worker/__init__.py`
- SQL correctness: HIGH — all SQL verified from migration files and existing DAO implementations
- Column name finding: HIGH — `ai_rag.documents.status` confirmed from V3 migration; `embedding_status` does not exist as a column
- Pitfalls: HIGH — derived from code inspection, not speculation

**Research date:** 2026-03-05
**Valid until:** 2026-04-04 (stable domain — asyncio patterns, psycopg3 API, PostgreSQL SKIP LOCKED semantics are not fast-moving)
