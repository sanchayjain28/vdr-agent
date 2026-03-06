---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: completed
stopped_at: "Completed 10-01-PLAN.md — Frontend HTTP infrastructure: config.ts VDR_AGENT_BASE_URL, vdrAgentApi in apiClients.ts, vdrAgent.ts service layer"
last_updated: "2026-03-06T04:08:37.562Z"
last_activity: "2026-03-05 — Completed 10-02 Tasks 1-2: ScopeSidebar getTopics, ScopeDetails Tag + polling + fitment"
progress:
  total_phases: 10
  completed_phases: 10
  total_plans: 21
  completed_plans: 21
  percent: 99
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-05)

**Core value:** Every ingested document automatically gets an AI summary and a fitment evaluation per ESG topic — with no manual trigger required.
**Current focus:** Phase 9 — Results API

## Current Position

Phase: 10 of 10 (Frontend Integration) — AWAITING HUMAN VERIFY
Plan: 2 of 2 in current phase — Plan 10-02 tasks complete, Task 3 checkpoint pending human verification
Status: Phase 10 nearly complete — ScopeSidebar API topics + ScopeDetails polling + Tags wired; TypeScript build passing
Last activity: 2026-03-05 — Completed 10-02 Tasks 1-2: ScopeSidebar getTopics, ScopeDetails Tag + polling + fitment

Progress: [██████████] 99%

## Performance Metrics

**Velocity:**
- Total plans completed: 2
- Average duration: 3 min
- Total execution time: 0.10 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-service-scaffold | 2 | 6 min | 3 min |

**Recent Trend:**
- Last 5 plans: 01-01 (4 min), 01-02 (2 min)
- Trend: baseline established

*Updated after each plan completion*
| Phase 02-db-schema P01 | 2 | 3 tasks | 3 files |
| Phase 02-db-schema P02 | 2 | 3 tasks | 3 files |
| Phase 03-db-layer P01 | 5 | 2 tasks | 2 files |
| Phase 03-db-layer P02 | 3 | 2 tasks | 3 files |
| Phase 03-db-layer P04 | 3 | 2 tasks | 2 files |
| Phase 04-llm-client P01 | 3 | 2 tasks | 3 files |
| Phase 04-llm-client P02 | 2 | 2 tasks | 2 files |
| Phase 05-polling-loop P01 | 5 | 2 tasks | 2 files |
| Phase 05-polling-loop P02 | 4 | 2 tasks | 4 files |
| Phase 08-topic-crud-api P01 | 7 | 2 tasks | 4 files |
| Phase 08-topic-crud-api P02 | 2 | 2 tasks | 3 files |
| Phase 07-fitment-generation P01 | 2 | 2 tasks | 3 files |
| Phase 07-fitment-generation P02 | 2 | 2 tasks | 1 files |
| Phase 09-results-api P01 | 5 | 3 tasks | 3 files |
| Phase 09-results-api P02 | 1 | 2 tasks | 3 files |
| Phase 10-frontend-integration P01 | 2 | 2 tasks | 3 files |
| Phase 10-frontend-integration P02 | 15 | 2 tasks | 3 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Roadmap: No Temporal in vdr-agent — DB polling with asyncio replaces workflow orchestration
- Roadmap: FOR UPDATE SKIP LOCKED is mandatory in Phase 2 schema + Phase 5 poller — not retrofittable
- Roadmap: boto3 must run in asyncio.to_thread() — never called directly from async context
- Roadmap: AsyncConnectionPool connections must not be held during Bedrock calls
- 01-01: db_host/db_name/db_user have no defaults — missing VDR_AGENT_DB_HOST causes immediate Pydantic ValidationError
- 01-01: from __future__ import annotations required in vdr-agent modules for str | None union syntax (venv is Python 3.9)
- 01-01: app/logging/__init__.py is standalone (no app.config import) to avoid circular imports
- 01-02: Host port 8004 used for vdr-agent (8001 occupied by ingestion-service mapping 8001:8000)
- 01-02: No postgres container in compose stack — VDR_AGENT_DB_HOST set to host.docker.internal
- [Phase 02-db-schema]: 02-db-schema: project_id in topics is plain UUID — FK to user-service deferred to Phase 8
- [Phase 02-db-schema]: 02-db-schema: update_updated_at_column() redefined in vdr_agent schema to avoid cross-schema function dependency
- [Phase 02-db-schema]: 02-db-schema: Partial index idx_processing_state_pending_failed — Phase 5 poll query must use WHERE summary_status IN ('pending', 'failed') exactly
- [Phase 02-02]: document_summaries has no status column — status lives in processing_state.summary_status; only completed results stored
- [Phase 02-02]: fitment_results.reasoning is TEXT only — no boolean is_relevant, no numeric score (locked decision)
- [Phase 02-02]: fitment_results_doc_topic_unique is the exact UNIQUE constraint name — Phase 7 ON CONFLICT clause must reference it
- [Phase 02-02]: Flyway -schemas=vdr_agent scopes history table to vdr_agent schema independent of ai_rag; -baselineVersion=0 ensures all V1-V5 run on first execution
- [Phase 03-db-layer]: psycopg-pool 3.2.8 installed into shared .venv; psycopg_pool.AsyncConnectionPool with open=False+await pool.open() pattern
- [Phase 03-db-layer]: configure() sets search_path TO vdr_agent, ai_rag, public AND commits — leaves connection idle not intrans
- [Phase 03-db-layer]: min_size=2, max_size=10 hardcoded in lifespan — no config fields for pool sizing needed in Phase 3
- [Phase 03-02]: TopicDAO.update() calls get_by_id() as no-op fallback when no fields provided — avoids issuing UPDATE with empty SET
- [Phase 03-02]: All TopicDAO SQL uses fully qualified vdr_agent.topics — safe even if search_path misconfigured at connection level
- [Phase 03-03]: claim_documents() does SELECT FOR UPDATE SKIP LOCKED + UPDATE in one DatabasePool.connection() block — splitting into two connections breaks atomicity
- [Phase 03-03]: WHERE id = ANY(%s) with Python list for batched UPDATE — psycopg3 handles list-to-array cast automatically
- [Phase 03-03]: reset_stale_claims() uses INTERVAL '%s minutes' with parameterized threshold — never f-string interpolation
- [Phase 03-04]: DocumentSummaryDAO.upsert() uses ON CONFLICT (document_id) DO UPDATE — inline UNIQUE on document_id; no named constraint needed
- [Phase 03-04]: FitmentResultDAO.upsert() uses ON CONFLICT ON CONSTRAINT fitment_results_doc_topic_unique — exact constraint name from V5 migration is mandatory
- [Phase 03-04]: Both DAOs commit and release connection inside DatabasePool.connection() block — no connection held during Bedrock calls
- [Phase 04-02]: 50 workers chosen for ThreadPoolExecutor to prevent asyncio.to_thread() queueing above GlobalRateLimiter cap of 10 concurrent Bedrock calls
- [Phase 05-polling-loop]: 05-01: ai_rag.documents status column is 'status' not 'embedding_status'; value 'completed' means full pipeline done
- [Phase 05-polling-loop]: 05-01: find_unregistered_documents is SELECT-only — no commit, releases connection after fetchall
- [Phase 05-polling-loop]: active_tasks set lives in run_poller() scope not _poll_cycle — task refs persist across cycles to prevent GC of in-flight coroutines
- [Phase 05-polling-loop]: process_document imported locally inside _poll_cycle to avoid circular import if processor.py ever imports from poller.py
- [Phase 05-polling-loop]: Shutdown sequence: cancel poller first, await (suppress CancelledError), then close DB pool — prevents DAO calls on closed pool
- [Phase 06-ai-summary-generation]: summary_section_size default=5 — each section sent to Claude as one invoke() call; sections fired in parallel via asyncio.gather(return_exceptions=True)
- [Phase 06-ai-summary-generation]: DB connection for chunk fetch closes before AI pipeline begins — no DatabasePool.connection() held during Bedrock calls (prevents pool exhaustion)
- [Phase 06-ai-summary-generation]: 0-chunk documents marked 'failed' not 'done' — prevents Phase 7 fitment from running against empty summary
- [Phase 06-ai-summary-generation]: return_exceptions=True is mandatory in asyncio.gather — ensures rate limiter semaphore slots are cleanly released even on failure
- [Phase 08-topic-crud-api]: V6 migration renames instruction_text to instruction — canonical fix so DB aligns with DAO/model layer
- [Phase 08-topic-crud-api]: bulk_insert wraps all inserts in one DatabasePool.connection() — UniqueViolation triggers full rollback, ensuring all-or-nothing semantics
- [Phase 08-topic-crud-api]: /bulk route defined before /{topic_id} in APIRouter — prevents path parameter collision on UUID routes
- [Phase 08-topic-crud-api]: Soft-delete uses TopicDAO.update(is_active=False) not TopicDAO.delete() — preserves fitment results
- [Phase 07-fitment-generation]: fitment_results.reasoning is now nullable (V7 migration) — failed-topic upserts write reasoning=NULL with status='failed'
- [Phase 07-fitment-generation]: list_active_by_project() coexists with list_by_project() — explicit shorthand for processor.py; not a replacement
- [Phase 07-fitment-generation]: bedrock_embedding_model defaults to 'cohere.embed-english-v3'; overridable via VDR_AGENT_BEDROCK_EMBEDDING_MODEL
- [Phase 07-fitment-generation]: process_document() uses if/else re-run safety: existing summary path sets final_summary and falls through to fitment; no outer try wraps the whole function
- [Phase 07-fitment-generation]: Fitment block is top-level in function body after if/else — runs after both summary paths on success; unreachable only when summary generation fails (returns early)
- [Phase 07-fitment-generation]: Phase 7 does NOT touch processing_state — summary_status remains 'done' from Phase 6 (locked decision)
- [Phase 07-fitment-generation]: Cohere input_type='search_query' for topic embedding — intentionally distinct from 'search_document' used by ingestion-service for correct cosine similarity
- [Phase 07-fitment-generation]: Fallback to first-5 chunks by chunk_index when all embeddings are NULL (no vector-indexed chunks)
- [Phase 09-results-api]: COALESCE(ps.summary_status, 'pending') in SQL — LEFT JOIN nulls become 'pending' at query level
- [Phase 09-results-api]: fitment_total_count uses subquery COUNT of active topics per project — canonical source of truth
- [Phase 09-results-api]: Route '' (empty string) used for list endpoint to avoid FastAPI redirect on trailing-slash queries
- [Phase 09-results-api]: fitment endpoint returns one item per active topic only — stale fitment rows for soft-deleted topics excluded
- [Phase 10-frontend-integration]: VDR_AGENT_BASE_URL localhost value is http://localhost:8004/vdr-agent/ — port 8004 plus root_path prefix
- [Phase 10-frontend-integration]: getVdrDocuments 404 returns [] not undefined — empty project is valid state, not error; no toast on error for polled function
- [Phase 10-frontend-integration]: vdrAgentApi uses same no-op request interceptor as ingestionApi — no auth token injection at this stage
- [Phase 10-frontend-integration]: combinedScopes unifies ITopic and Scope into { id, displayName }[] — avoids conditional rendering on different field names
- [Phase 10-frontend-integration]: POLL_INTERVAL_MS = 12000 defined as module-level constant for easy tuning
- [Phase 10-frontend-integration]: Status defaults to pending Tag when no vdrDoc found — safe UX default before first poll returns

### Pending Todos

None yet.

### Blockers/Concerns

- [Pre-Phase 3] project_id scoping on topics — confirm whether project_id is FK to existing table or plain UUID (check user-service schema before Phase 8 API routes)
- [Pre-Phase 10] vdr-frontend URL prefix — confirm whether routes are /vdr-agent/ or /api/vdr-agent/ and whether requests go through existing API gateway
- [Post-Phase 6] Bedrock quota — 200 RPM shared with ingestion-service; if both run at full load simultaneously, throttling may occur; decide on stagger vs distributed rate limiter before production

## Session Continuity

Last session: 2026-03-05
Stopped at: Completed 10-01-PLAN.md — Frontend HTTP infrastructure: config.ts VDR_AGENT_BASE_URL, vdrAgentApi in apiClients.ts, vdrAgent.ts service layer
Resume file: None
