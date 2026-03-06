# Research Summary

**Project:** vdr-agent — AI-powered ESG document analysis microservice
**Synthesized:** 2026-03-05
**Research files:** STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md

---

## Executive Summary

`vdr-agent` is a new FastAPI microservice to be added to an existing ESG Virtual Data Room platform. Its core job is two-fold: expose a REST API for topic (ESG scope) management consumed by `vdr-frontend`, and run a continuous background polling loop that picks up documents after ingestion-service finishes embedding them, generates AI summaries via AWS Bedrock (Claude Sonnet), and evaluates each document's relevance to every active ESG topic (fitment). The service is intentionally narrow in scope: no Temporal, no retry logic, no event bus, no caching layer beyond PostgreSQL itself.

The recommended approach closely mirrors the patterns already established in `ingestion-service`. The stack is non-negotiable: Python 3.12, FastAPI with asynccontextmanager lifespan, psycopg 3 (binary) with AsyncConnectionPool, raw SQL DAOs, and boto3 wrapped in `asyncio.to_thread()` for Bedrock calls. The existing `ClaudeClient`, `GlobalRateLimiter`, and `DatabasePool` implementations in `ingestion-service` are production-proven and should be ported or referenced directly rather than re-implemented. The AI processing pipeline processes documents sequentially (one at a time through the polling loop) but fires up to ~40 parallel Bedrock calls per document — section summaries in parallel, then per-topic fitment in parallel — bounded by a semaphore.

The critical risks cluster around three areas: DB concurrency (duplicate document processing without `FOR UPDATE SKIP LOCKED`), asyncio correctness (blocking boto3 or psycopg3 sync calls stalling the event loop), and Bedrock rate limits (burst parallelism triggering throttling that silently drops results with no retry). All three must be addressed in Phase 1 foundation work — retrofitting them is architecturally dangerous. The feature set is well-understood from direct codebase inspection; the vdr-frontend already has placeholder columns for "File Summary" and "Scope Fitting" that are waiting for this service.

---

## Key Findings

### From STACK.md

| Technology | Rationale |
|------------|-----------|
| Python 3.12 + FastAPI 0.115+ | Platform standard; asynccontextmanager lifespan is the canonical background loop pattern |
| psycopg 3.3.3 (binary) + psycopg-pool 3.3.0 | Platform standard; AsyncConnectionPool singleton pattern verified in ingestion-service/app/db/pool.py |
| boto3 1.42.60 + ThreadPoolExecutor(max_workers=50) | boto3 is synchronous; must run in executor; TEMP-007 incident proves undersized thread pools deadlock |
| asyncio.Semaphore (via GlobalRateLimiter) | Port rate_limiter.py from ingestion-service verbatim; lazy async primitive initialization is required |
| Pydantic Settings with VDR_AGENT_* prefix | Platform standard; catches misconfiguration at startup |

**Critical version rule:** Async primitives (Semaphore, Lock) must be lazily initialized inside a running event loop, not at module import time. This is a known pitfall documented in `ingestion-service/app/core/llm/rate_limiter.py`.

**What NOT to use:** Temporal, Celery/RQ, aioboto3, asyncpg, SQLAlchemy, apscheduler, FastAPI BackgroundTasks (for the polling loop), or psycopg2.

### From FEATURES.md

**Table stakes (must-have for v1):**

- Topic CRUD with per-topic instruction field (drives AI fitment; frontend has 19 hardcoded scopes to replace)
- DB polling loop (`embedding_status = 'completed'` detection, asyncio background task)
- AI document summary generation (parallel section summaries ~10 calls, combined)
- Fitment summary generation per active topic (~20–30 calls per document)
- Result storage (`vdr_agent` schema: topics, processing_state, document_summaries, fitment_results)
- Status fields: `pending | processing | done | failed` on both summary and fitment rows
- `GET /vdr-agent/documents?project_id=&topic_id=` returning enriched document list
- `GET /vdr-agent/topics?project_id=` replacing hardcoded frontend data
- Re-run fitment on topic instruction change (invalidate + re-queue via polling loop)
- Re-run fitment for newly created topics (seed pending rows for all existing processed documents)
- Health check at `GET /health`

**Differentiators (v2 candidates, low effort):**

- Fitment relevance flag (`relevant | not_relevant | partial`) — can be added to fitment row when building step 5
- Progress counters ("12/30 topics analysed") — computed at query time, no schema change
- Topic ordering / sort index
- Bulk re-run endpoint (`POST /topics/{id}/rerun-fitment`)

**Deliberate anti-features:** No SSE, no WebSockets, no retry logic, no Redis, no Temporal, no per-document manual trigger.

**Frontend integration pattern:** Polling. vdr-frontend's Axios client polls `GET /documents` every 10–15 seconds. Status fields drive loading spinners in Ant Design Table cells.

### From ARCHITECTURE.md

**Component map:**

| Component | Responsibility |
|-----------|---------------|
| `core/routers/` | REST API to vdr-frontend; topic CRUD + document status queries |
| `core/polling/poller.py` | Background asyncio task; detects + claims unprocessed documents via `FOR UPDATE SKIP LOCKED` |
| `core/polling/processor.py` | Per-document orchestration; owns all DB side-effects; composes generation layer |
| `core/generation/summary.py` | Stateless: parallel section summaries → combined summary |
| `core/generation/fitment.py` | Stateless: parallel per-topic fitment evaluations (semaphore-bounded) |
| `core/llm/client.py` | boto3 Bedrock wrapper; single point for model ID, request format, `asyncio.to_thread` offloading |
| `db/dao/` | AsyncConnectionPool + raw SQL DAOs; reads `ai_rag.*`, writes `vdr_agent.*` |

**Boundary rule:** Generation layer is pure computation — no DB access. Processor owns all persistence for a document's lifecycle.

**Schema ownership:** vdr-agent reads `ai_rag.*` (owned by ingestion-service) and writes only to `vdr_agent.*`. No cross-schema writes.

**Four canonical DB tables:** `vdr_agent.topics`, `vdr_agent.processing_state`, `vdr_agent.document_summaries`, `vdr_agent.fitment_results`

**Key queries:** `FOR UPDATE SKIP LOCKED` poll claim + insert-before-claim detection (run both on every poll cycle). Partial index on `(summary_status, created_at) WHERE summary_status IN ('pending', 'failed')` is mandatory for performance.

**Scale headroom:** `FOR UPDATE SKIP LOCKED` supports horizontal replica scaling with zero coordination. Each replica enforces its own Bedrock rate limit.

### From PITFALLS.md

**Top 5 pitfalls with phase anchoring:**

| # | Pitfall | Phase | Prevention |
|---|---------|-------|-----------|
| 1 | Duplicate document processing (race condition) | Phase 1 | `FOR UPDATE SKIP LOCKED` atomic claim — no plain SELECT then UPDATE |
| 2 | Stuck `in_progress` documents (crash with no expiry) | Phase 1 (schema) | `processing_started_at` column + stale-lock recovery query in poller |
| 3 | boto3 blocking asyncio event loop | Phase 1 (LLM client) | `asyncio.to_thread()` on every invoke_model call, or port existing executor pattern |
| 4 | DB connection pool exhaustion (holding connections across Claude calls) | Phase 1 (DB setup) | `async with pool.connection()` scoped tightly; never hold connection during Bedrock calls |
| 5 | Bedrock TPM quota burst (40 simultaneous calls) | Phase 2 (parallel calls) | Port `GlobalRateLimiter` from ingestion-service; start with max_concurrent=5–10 |

**Additional moderate pitfalls:**
- Pitfall 6: asyncio task leak (store task ref + done callback + cancel in lifespan finally)
- Pitfall 7: Sync psycopg3 in async context (choose AsyncConnection and apply consistently)
- Pitfall 8: Large document memory pressure (lazy chunk fetch + bounded concurrency)
- Pitfall 9: Fitment re-run concurrent write race (`ON CONFLICT DO UPDATE` + UNIQUE constraint)

**Minor pitfalls:** Unbounded poll batch size (use LIMIT), missing partial index, bad poll interval (start at 10s), silent Claude response truncation (check `stop_reason`).

---

## Implications for Roadmap

### Suggested Phase Structure

The component dependency graph from ARCHITECTURE.md + the phase warnings from PITFALLS.md together prescribe a clear 3-phase structure:

---

**Phase 1: Service Foundation — Schema, DB Layer, LLM Client, Polling Loop**

*Rationale:* Everything else depends on this. The three most critical pitfalls (race condition, event loop blocking, connection exhaustion) are all schema/infrastructure decisions that cannot be safely retrofitted. This phase must be correct before any AI generation logic is built.

*What it delivers:* A running FastAPI service that polls PostgreSQL, atomically claims documents, and can make a single (correctly offloaded) Bedrock call. No frontend value yet, but the skeleton is solid.

*Features from FEATURES.md:*
- DB polling loop (detection + atomic claim)
- DB schema (all four vdr_agent tables with correct indexes)
- Health check endpoint

*Pitfalls to avoid:* 1 (SKIP LOCKED), 2 (processing_started_at), 3 (asyncio.to_thread), 4 (connection scope), 6 (task ref + done callback), 7 (async psycopg3), 10 (LIMIT on poll), 11 (partial index), 12 (poll interval)

*Research flag:* Standard pattern — no additional research needed. ingestion-service is the authoritative reference.

---

**Phase 2: AI Generation Pipeline — Summaries + Fitment + Rate Limiting**

*Rationale:* The generation layer is pure computation with no DB coupling, so it can be built and tested in isolation against the Phase 1 foundation. Rate limiting must be in place before the first multi-document processing run to avoid Bedrock quota exhaustion.

*What it delivers:* End-to-end AI processing. Documents with `embedding_status = completed` automatically get AI summaries and per-topic fitment results written to the DB. Core product value is live; frontend can start reading real data.

*Features from FEATURES.md:*
- AI document summary generation (parallel section summaries)
- Fitment summary generation per active topic
- Result storage (write to document_summaries + fitment_results)
- Summary and fitment status fields (`processing | done | failed`)

*Pitfalls to avoid:* 5 (Bedrock burst throttling — port GlobalRateLimiter before first run), 8 (memory pressure — lazy chunk fetch), 13 (stop_reason truncation check)

*Research flag:* LLM prompt design for section summaries and fitment evaluation may benefit from a targeted `/gsd:research-phase` to nail the prompt structure and output schema. Everything else is well-understood from ingestion-service.

---

**Phase 3: HTTP API + Topic Management + Frontend Integration**

*Rationale:* The REST API is largely read-oriented (reads from DB populated by Phase 2) plus Topic CRUD. Topic CRUD is simple synchronous logic. This phase can be partially parallelized with Phase 2 since routers only depend on DAOs (Phase 1), not generation logic. The re-run feature is the only complex interaction and should be the last piece.

*What it delivers:* Full integration with vdr-frontend. The "File Summary" and "Scope Fitting" columns are populated with real data. Topic management replaces the 19 hardcoded ESG scopes. The product is usable end-to-end.

*Features from FEATURES.md:*
- Topic CRUD API (GET, POST, PATCH, DELETE /topics)
- GET /documents endpoint with summary + fitment enrichment
- Re-run fitment on topic instruction change
- Re-run fitment for newly created topics

*Pitfalls to avoid:* 9 (fitment re-run concurrent write race — ON CONFLICT DO UPDATE + serialize through polling queue)

*Research flag:* Standard REST patterns — no additional research needed. Frontend API contract is well-defined by inspecting vdr-frontend source.

---

### Build Order Within Phases

Based on ARCHITECTURE.md component dependency graph:

```
Phase 1:
  DB schema + migrations
    → Config + DB pool
      → DAOs (TopicDAO, ProcessingStateDAO)
        → LLM client (boto3 wrapper + asyncio.to_thread)
          → Polling loop skeleton (detect + claim only, no generation yet)
            → FastAPI lifespan wiring + health check

Phase 2:
  Generation: summary.py (parallel section calls)
    → Generation: fitment.py (parallel topic calls + semaphore)
      → Rate limiter port from ingestion-service
        → Processor (compose DAOs + generation)
          → Wire processor into polling loop

Phase 3:
  HTTP routers: topics.py (CRUD)
    → HTTP routers: documents.py (enriched list)
      → Re-run logic in PATCH /topics/{id}
        → New topic fitment seeding in POST /topics
```

---

### Research Flags

| Phase | Research Needed? | Reason |
|-------|-----------------|--------|
| Phase 1 (Foundation) | No | ingestion-service is authoritative reference; patterns fully documented |
| Phase 2 (AI Generation) | Maybe — prompt design | LLM prompt structure for section summaries + fitment evaluation is not pre-specified; a targeted research spike on prompt engineering for ESG document analysis could improve output quality |
| Phase 3 (HTTP API) | No | Frontend contract is defined by inspecting vdr-frontend source; standard FastAPI REST patterns |

---

### Gaps to Address During Planning

1. **Prompt design for AI generation** — The research documents the architectural pattern for calling Claude but do not specify the actual prompts for section summarisation or fitment evaluation. These need to be drafted and possibly iterated on. Low risk of blocking; can be refined after initial implementation.

2. **Bedrock quota headroom** — The current 200 RPM quota is shared with ingestion-service. If both run simultaneously at full load, this becomes a bottleneck. A decision is needed: enable the existing PostgreSQL-backed distributed rate limiter, or stagger service operation windows. Not blocking for Phase 1–2 but must be resolved before production rollout.

3. **project_id scoping on topics** — FEATURES.md notes topics should be project-scoped, but the detailed schema does not confirm whether `project_id` is a FK to an existing users/projects table or a plain UUID. This needs clarification against the user-service schema before Phase 3 API routes are finalized.

4. **vdr-frontend API client wiring** — The frontend currently calls `getProjectDocuments` (observed in ScopeDetails.tsx). The exact URL prefix (`/vdr-agent/`, `/api/vdr-agent/`, etc.) and whether it goes through the existing API gateway needs to be confirmed before Phase 3 integration testing.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|-----------|-------|
| Stack (technologies + versions) | HIGH | All versions verified against PyPI (March 2026) and ingestion-service pyproject.toml |
| Features (what to build) | HIGH | Derived from direct frontend source inspection + PROJECT.md; placeholder columns confirm the need |
| Architecture (patterns + schema) | HIGH | Based on direct ingestion-service code analysis + FastAPI/PostgreSQL official docs |
| Pitfalls (risks + mitigations) | HIGH | Most critical pitfalls verified against ingestion-service CLAUDE.md (TEMP-007) and official docs; minor pitfalls from community sources (MEDIUM) |
| AI prompt design | LOW | Not researched; this is the only significant gap |
| Bedrock quota in shared environment | MEDIUM | Quota limits documented by AWS; actual headroom in this AWS account is unknown |

**Overall confidence: HIGH** — The architecture, stack, and feature set are well-understood. The main unknowns are prompt content (not architecture) and operational quota management.

---

## Sources

*Aggregated from all research files.*

**Official documentation (HIGH confidence):**
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)
- [psycopg 3 AsyncConnectionPool](https://www.psycopg.org/psycopg3/docs/advanced/pool.html)
- [PostgreSQL Explicit Locking (SKIP LOCKED)](https://www.postgresql.org/docs/current/explicit-locking.html)
- [AWS Bedrock Quotas](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html)
- [AWS Bedrock Token Burndown](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html)

**PyPI (versions confirmed March 2026):**
- FastAPI 0.135.1, uvicorn 0.41.0, pydantic-settings 2.13.1, psycopg 3.3.3, psycopg-pool 3.3.0, boto3 1.42.60

**Internal codebase (HIGH confidence — primary sources):**
- `ingestion-service/app/core/llm/claude/client.py` — ClaudeClient + batch_complete pattern
- `ingestion-service/app/core/llm/rate_limiter.py` — GlobalRateLimiter with lazy async primitives
- `ingestion-service/app/db/pool.py` — AsyncConnectionPool singleton
- `ingestion-service/CLAUDE.md` — TEMP-007 thread pool fix; rate limit config
- `ingestion-service/pyproject.toml` — authoritative version constraints
- `vdr-frontend/src/pages/scopeDetails/ScopeDetails.tsx` — placeholder columns + document table
- `vdr-frontend/src/pages/projectDetails/ProjectDetails.tsx` — 19 hardcoded ESG scope names
- `.planning/PROJECT.md` — authoritative constraints (no Temporal, no retry, no auth on vdr-agent)
- `ARCHITECTURE_OVERVIEW.md` — system flow diagrams

**Community / blog (MEDIUM confidence):**
- [SKIP LOCKED effectiveness — inferable.ai](https://www.inferable.ai/blog/posts/postgres-skip-locked)
- [boto3 async performance — joelmccoy.medium.com](https://joelmccoy.medium.com/python-and-boto3-performance-adventures-synchronous-vs-asynchronous-aws-api-interaction-22f625ec6909)
- [FastAPI async task pitfalls — leapcell.io](https://leapcell.io/blog/understanding-pitfalls-of-async-task-management-in-fastapi-requests)
- [Bedrock TPM parallel workflows — AWS re:Post](https://repost.aws/questions/QU41JbEn0NStC1P3KB6cd5UA)
