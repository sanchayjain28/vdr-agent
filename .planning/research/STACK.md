# Technology Stack

**Project:** vdr-agent — AI-powered ESG document analysis microservice
**Researched:** 2026-03-05
**Research type:** Stack dimension — FastAPI + async DB polling + parallel LLM calls + PostgreSQL persistence

---

## Context

vdr-agent is a **new microservice** added to an existing platform. It must match the conventions of `ingestion-service` exactly:

- Poetry dependency management
- FastAPI with asynccontextmanager lifespan
- psycopg 3 (binary) + psycopg-pool with AsyncConnectionPool
- Raw SQL DAOs (no ORM)
- boto3 + ThreadPoolExecutor for AWS Bedrock (Claude is synchronous API, must run in executor)
- Pydantic Settings with `VDR_AGENT_*` env var prefix
- Python 3.12+

The ingestion-service codebase is the **authoritative reference** for all patterns. Deviation requires explicit justification.

---

## Recommended Stack

### Core Framework

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.12+ | Runtime | Matches ingestion-service; 3.12 brings free-threaded GIL experiments and faster async; 3.11 introduced significant asyncio speedups |
| FastAPI | >=0.115.0, <1.0 (current: 0.135.1) | HTTP API + lifespan management | Platform standard; lifespan context manager pattern is the canonical way to run background loops; strict_content_type added in 0.115+ |
| uvicorn | >=0.30.0 (current: 0.41.0) | ASGI server | Platform standard; standard[uvicorn] bundle recommended |
| Pydantic | >=2.0,<3.0 | Data validation, request/response models | Platform standard; V2 with Rust core is significantly faster than V1 |
| pydantic-settings | >=2.0,<3.0 (current: 2.13.1) | Config from env vars | Platform standard; BaseSettings pattern used throughout platform |

**Confidence:** HIGH — verified against existing ingestion-service pyproject.toml and PyPI current versions.

### Database

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| psycopg | >=3.1 [binary] (current: 3.3.3) | PostgreSQL async adapter | Platform standard; binary wheels avoid libpq dependency; psycopg3 native async avoids the run_in_executor dance required by psycopg2 |
| psycopg-pool | >=3.2.0 (current: 3.3.0) | AsyncConnectionPool | Platform standard; pool manager already implemented in ingestion-service/app/db/pool.py — vdr-agent should reuse this exact pattern |

**Connection pool sizing for vdr-agent:** min=5, max=20 is sufficient (polling loop is sequential between documents; parallel calls are all LLM, not DB).

**Confidence:** HIGH — psycopg 3.3.3 and psycopg-pool 3.3.0 confirmed on PyPI (Feb 2026).

### AWS Bedrock / LLM

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| boto3 | >=1.28.0 (current: 1.42.60) | AWS Bedrock Claude API | Platform standard; same client used in ingestion-service; no native async — must use loop.run_in_executor with dedicated ThreadPoolExecutor |
| ThreadPoolExecutor | stdlib (concurrent.futures) | Off-load synchronous boto3 calls to threads | boto3 invoke_model is blocking; run_in_executor prevents event loop starvation; ingestion-service uses 200 threads for heavy load — vdr-agent should size at 50 (40 max concurrent + headroom) |

**Claude model:** `global.anthropic.claude-sonnet-4-5-20250929-v1:0` — same as ingestion-service (verified in client.py line 245).

**Pattern to reuse:** The `ClaudeClient` in `ingestion-service/app/core/llm/claude/client.py` is production-ready. vdr-agent should copy or import this module — do NOT re-implement from scratch. The batch_complete method with semaphore-based concurrency control is the exact pattern needed for 40 parallel calls per document.

**Confidence:** HIGH — verified against existing codebase; boto3 sync-only confirmed by AWS docs and ingestion-service CLAUDE.md (TEMP-007 incident).

### Async Task Management (Background Polling)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| asyncio | stdlib | Background polling loop, parallel LLM calls | The canonical Python async runtime; no external dependency needed |
| asyncio.create_task | stdlib | Launch polling loop from lifespan | Correct pattern for long-running loops in FastAPI: create in lifespan startup, cancel in lifespan shutdown |
| asyncio.Semaphore | stdlib | Bound concurrent Bedrock calls | Platform standard — GlobalRateLimiter in ingestion-service uses this exact pattern with a rolling-window RPM counter |

**Background polling pattern (canonical for this project):**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize pool, clients
    await DatabasePool.initialize(...)

    poll_task = asyncio.create_task(polling_loop())
    app.state.poll_task = poll_task  # hold strong reference

    yield

    # Graceful shutdown
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass

    await DatabasePool.close()
```

**Polling loop pattern:**

```python
async def polling_loop():
    while True:
        try:
            docs = await poll_for_unprocessed_documents()
            for doc in docs:
                await process_document(doc)  # sequential — one doc at a time
        except asyncio.CancelledError:
            raise  # propagate cancellation
        except Exception:
            logger.exception("Polling error — sleeping before retry")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
```

**Important:** Each document triggers ~40 parallel asyncio tasks (section summaries + fitment calls) but documents themselves are processed sequentially by the polling loop. This avoids thundering-herd against Bedrock.

**Confidence:** HIGH — pattern verified against FastAPI official docs (lifespan events), Python asyncio docs, and existing ingestion-service implementation.

### Rate Limiting

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| GlobalRateLimiter (internal) | N/A | Rolling-window RPM enforcement + semaphore concurrency | Reuse from ingestion-service/app/core/llm/rate_limiter.py verbatim; handles lazy asyncio primitive initialization for multi-loop scenarios |

**Rate limit config for vdr-agent:**
- RPM limit: 200 (shared Bedrock quota with ingestion-service — use distributed limiter if both run simultaneously)
- max_concurrent: 40 (matches ~40 calls per document)
- safety_margin: 0.9 (platform standard)

**Critical:** If ingestion-service and vdr-agent run simultaneously against the same Bedrock endpoint, they share the 200 RPM quota. Enable the PostgreSQL-backed distributed rate limiter in that case (already implemented in `ingestion-service/app/core/llm/distributed_rate_limiter.py`).

**Confidence:** HIGH — validated against ingestion-service implementation and AWS Bedrock quota documentation.

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | >=1.0.0 | .env.local file loading | Platform standard; load env before Pydantic Settings |
| prometheus-client | >=0.19.0 | Metrics (optional) | Add if monitoring is desired; consistent with platform |
| pytest | >=7.4.0 | Unit testing | Platform standard |
| pytest-asyncio | >=0.21.0 | Async test support | Required for testing async DAOs and polling loop |
| black | >=23.0.0 | Code formatting | Platform standard |
| ruff | >=0.1.0 | Linting | Platform standard |
| mypy | >=1.5.0 | Static type checking | Platform standard |

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| DB polling trigger | asyncio background loop | Temporal workflow | PROJECT.md explicitly rules out Temporal in vdr-agent; DB polling is simpler and sufficient for this use case |
| DB polling trigger | asyncio background loop | Celery / RQ | Would introduce new broker infrastructure (Redis) not present on platform; defeats simplicity goal |
| DB polling trigger | asyncio background loop | LISTEN/NOTIFY (PostgreSQL) | More elegant but adds complexity; would require schema changes to ingestion-service to emit NOTIFY on embedding completion; polling is safe and sufficient |
| Bedrock client | boto3 + executor | anthropic SDK (direct) | Platform uses Bedrock exclusively for IAM-controlled access; direct Anthropic SDK bypasses AWS auth and cost tracking |
| Bedrock client | boto3 + executor | aioboto3 (async boto3) | aioboto3 is a community wrapper with slower update cadence; ingestion-service already solved the executor pattern with TEMP-007 fix — no need to introduce a new dependency |
| Concurrency control | asyncio.Semaphore (via GlobalRateLimiter) | asyncio.Queue | Semaphore is simpler for pure concurrency bounding; queue adds complexity with worker management; the existing GlobalRateLimiter is well-tested |
| HTTP framework | FastAPI | Flask / Starlette | FastAPI is platform standard; lifespan events are first-class; async support built-in |
| DB adapter | psycopg3 (binary) | asyncpg | psycopg3 is platform standard; asyncpg would require porting all existing DAO patterns; psycopg3 supports both sync and async on same codebase |
| Config | pydantic-settings | dynaconf / python-decouple | pydantic-settings is platform standard; Pydantic V2 validation catches misconfiguration at startup |

---

## Installation

```bash
# Core service dependencies
poetry add fastapi uvicorn[standard] pydantic "pydantic-settings>=2.0,<3.0"
poetry add "psycopg[binary]>=3.1" "psycopg-pool>=3.2.0"
poetry add "boto3>=1.28.0"
poetry add python-dotenv

# Dev/test dependencies
poetry add --group dev pytest pytest-asyncio black ruff mypy
```

**pyproject.toml template (matching ingestion-service convention):**

```toml
[tool.poetry]
name = "vdr-agent"
version = "0.1.0"
description = "AI-powered ESG document analysis service"
authors = ["ERM Team"]

[tool.poetry.dependencies]
python = ">=3.12,<4.0"
fastapi = ">=0.115.0"
uvicorn = {version = ">=0.30.0", extras = ["standard"]}
pydantic = ">=2.0,<3.0"
pydantic-settings = ">=2.0,<3.0"
psycopg = {version = ">=3.1", extras = ["binary"]}
psycopg-pool = ">=3.2.0"
boto3 = ">=1.28.0"
python-dotenv = ">=1.0.0"

[tool.poetry.group.dev.dependencies]
pytest = ">=7.4.0"
pytest-asyncio = ">=0.21.0"
black = ">=23.0.0"
ruff = ">=0.1.0"
mypy = ">=1.5.0"
```

---

## Key Patterns — Prescriptive Decisions

### 1. ThreadPoolExecutor sizing for boto3

The ingestion-service TEMP-007 incident demonstrated that an undersized thread pool causes deadlock when many concurrent boto3 calls are in flight. vdr-agent has a maximum of ~40 concurrent calls per document.

**Rule:** `max_workers = max_concurrent_calls + 10` headroom.

```python
executor = ThreadPoolExecutor(
    max_workers=50,  # 40 max concurrent + 10 headroom
    thread_name_prefix="bedrock-vdr"
)
```

**Do not share the executor with ingestion-service.** Each process has its own ThreadPoolExecutor.

**Confidence:** HIGH — learned from TEMP-007 in ingestion-service CLAUDE.md.

### 2. Async primitives must be lazily initialized

asyncio.Semaphore and asyncio.Lock must be created inside a running event loop, not at module import time. The ingestion-service implemented `_ensure_async_primitives()` to handle this. vdr-agent must follow the same pattern.

**Confidence:** HIGH — verified in ingestion-service/app/core/llm/rate_limiter.py and concurrency_manager.py.

### 3. asyncio.gather for parallel section summaries

For the ~10 parallel section summary calls per document:

```python
tasks = [call_claude_section_summary(section) for section in sections]
results = await asyncio.gather(*tasks, return_exceptions=True)
# Filter errors separately — do not fail whole document on one section failure
```

Use `return_exceptions=True` so a single section failure does not abort the whole document.

**Confidence:** HIGH — pattern from ingestion-service batch_complete implementation.

### 4. Semaphore-bounded gather for fitment calls

For 20–30 parallel fitment calls per document, bound concurrency:

```python
semaphore = asyncio.Semaphore(MAX_CONCURRENT_BEDROCK)

async def bounded_fitment(topic):
    async with semaphore:
        return await call_claude_fitment(topic)

tasks = [bounded_fitment(t) for t in active_topics]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

This is exactly what `batch_complete()` does in the existing Claude client.

**Confidence:** HIGH — verified in ingestion-service.

### 5. DB polling — skip-on-failure semantics

The PROJECT.md mandates no retry on failure — failures are skipped silently. This means:

```python
async def process_document(doc_id):
    try:
        await mark_summary_in_progress(doc_id)
        summary = await generate_summary(doc_id)
        await store_summary(doc_id, summary)
    except Exception:
        logger.exception("Document %s failed — marking as skipped", doc_id)
        await mark_summary_failed(doc_id)
        # Do NOT re-raise — polling loop continues
```

Mark failed documents with a status column so they are excluded from future polls.

**Confidence:** HIGH — from PROJECT.md requirements.

### 6. Env var naming convention

Follow the ingestion-service `ERM_RAG_*` prefix pattern. Use `VDR_AGENT_*` for vdr-agent-specific settings:

```
VDR_AGENT_DB_HOST
VDR_AGENT_DB_PORT
VDR_AGENT_DB_NAME
VDR_AGENT_DB_USER
VDR_AGENT_DB_PASSWORD
VDR_AGENT_DB_SCHEMA          # default: vdr_agent
VDR_AGENT_POLL_INTERVAL_SEC  # default: 30
VDR_AGENT_MAX_CONCURRENT_BEDROCK  # default: 40
VDR_AGENT_RPM_LIMIT          # default: 200
VDR_AGENT_LOG_LEVEL          # default: INFO
AWS_BEARER_TOKEN_BEDROCK      # shared with ingestion-service
AWS_REGION                    # shared with ingestion-service
```

**Confidence:** HIGH — consistent with platform convention.

---

## What NOT to Use

| Avoid | Reason |
|-------|--------|
| SQLAlchemy (sync or async) | Platform uses raw SQL DAOs exclusively; ORM adds unnecessary complexity and hides query performance |
| Temporal SDK | Explicitly out of scope per PROJECT.md |
| aioboto3 | Community async wrapper for boto3; slower update cadence; ingestion-service solved async boto3 correctly with run_in_executor — use that pattern |
| FastAPI BackgroundTasks | Designed for per-request background work, not persistent long-running loops; fires and forgets without lifecycle management |
| Celery / RQ | Overkill for single-service polling; adds broker infrastructure (Redis) not present on platform |
| asyncpg | Not platform-standard; would require rewriting DAO patterns from scratch |
| apscheduler | Third-party scheduler adds dependency for what is a simple while-True + asyncio.sleep pattern |
| psycopg2 | Legacy sync-only adapter; psycopg3 is platform standard with native async support |

---

## Confidence Assessment

| Area | Level | Source |
|------|-------|--------|
| Core framework (FastAPI, uvicorn) | HIGH | Verified against ingestion-service pyproject.toml + PyPI current versions |
| Database stack (psycopg3, pool) | HIGH | Verified against ingestion-service pool.py + PyPI (psycopg 3.3.3, psycopg-pool 3.3.0, Feb 2026) |
| Bedrock/boto3 integration | HIGH | Verified against ingestion-service claude/client.py; boto3 1.42.60 confirmed |
| Background polling pattern | HIGH | FastAPI lifespan docs + ingestion-service pattern + Python asyncio docs |
| Rate limiting approach | HIGH | Verified against ingestion-service rate_limiter.py and concurrency_manager.py |
| ThreadPoolExecutor sizing | HIGH | Verified against TEMP-007 incident in ingestion-service CLAUDE.md |
| Version numbers | HIGH | PyPI confirmed March 2026: FastAPI 0.135.1, uvicorn 0.41.0, pydantic-settings 2.13.1, psycopg 3.3.3, psycopg-pool 3.3.0, boto3 1.42.60 |

---

## Sources

- [FastAPI Lifespan Events — Official Docs](https://fastapi.tiangolo.com/advanced/events/)
- [psycopg 3 AsyncConnectionPool — Official Docs](https://www.psycopg.org/psycopg3/docs/advanced/pool.html)
- [psycopg PyPI](https://pypi.org/project/psycopg/) — v3.3.3 (Feb 18, 2026)
- [psycopg-pool PyPI](https://pypi.org/project/psycopg-pool/) — v3.3.0 (Dec 1, 2025)
- [FastAPI PyPI](https://pypi.org/project/fastapi/) — v0.135.1
- [uvicorn PyPI](https://pypi.org/project/uvicorn/) — v0.41.0 (Feb 16, 2026)
- [pydantic-settings PyPI](https://pypi.org/project/pydantic-settings/) — v2.13.1 (Feb 19, 2026)
- [boto3 documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/quickstart.html) — v1.42.60
- [AWS Bedrock Quotas](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html)
- [ingestion-service/app/core/llm/claude/client.py](../../../ingestion-service/app/core/llm/claude/client.py) — existing ClaudeClient implementation
- [ingestion-service/app/core/llm/rate_limiter.py](../../../ingestion-service/app/core/llm/rate_limiter.py) — GlobalRateLimiter with lazy async primitives
- [ingestion-service/app/db/pool.py](../../../ingestion-service/app/db/pool.py) — AsyncConnectionPool singleton pattern
- [ingestion-service/CLAUDE.md](../../../ingestion-service/CLAUDE.md) — TEMP-007 thread pool fix, rate limit config
- [ingestion-service/pyproject.toml](../../../ingestion-service/pyproject.toml) — authoritative version constraints
- [FastAPI Background Tasks pitfalls — Leapcell](https://leapcell.io/blog/understanding-pitfalls-of-async-task-management-in-fastapi-requests)
- [AWS Bedrock ThrottlingException deep dive — tech-reader.blog](https://www.tech-reader.blog/2025/02/deep-dive-into-problem-aws-bedrock_19.html)
