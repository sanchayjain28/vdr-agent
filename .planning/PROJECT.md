# VDR Agent Service

## What This Is

A FastAPI microservice (`vdr-agent`) that automates AI-powered document analysis for the ESG VDR platform. It polls for ingested documents, generates plain-English AI summaries via Claude on AWS Bedrock, and evaluates each document's fitment against user-defined ESG topics. Results surface in `vdr-frontend` as documents are processed — topic names from API, processing status indicators, and fitment progress counts.

## Core Value

Every ingested document automatically gets an AI summary and a fitment evaluation per ESG topic — with no manual trigger required from the user.

## Requirements

### Validated

- ✓ Document ingestion pipeline (download, convert, chunk, embed) — existing ingestion-service
- ✓ SharePoint folder sync via Temporal — existing ingestion-service
- ✓ Vector embeddings stored in PostgreSQL — existing ingestion-service
- ✓ vdr-frontend shell exists (React + Vite + Ant Design) — existing vdr-frontend
- ✓ Topic/scope management — CRUD for ESG topics with per-topic instructions — v1.0
- ✓ DB polling — detect newly-embedded documents and trigger AI generation — v1.0
- ✓ AI Summary generation — parallel section summarisation → combined document summary — v1.0
- ✓ Fitment summary generation — per-topic evaluation using AI summary + relevant sections — v1.0
- ✓ Result storage — persist summaries and fitment results in PostgreSQL — v1.0
- ✓ vdr-frontend integration — wire existing frontend to vdr-agent APIs — v1.0 (partial: per-topic fitment display and topic deletion UI deferred)

### Active

- [ ] Per-topic fitment detail view — render getDocumentFitment() data in UI (FE-02 gap from v1.0)
- [ ] Topic deletion UI — add delete button to frontend for TOPIC-04
- [ ] Fix AddScope instruction validation — enforce required instruction field in form
- [ ] Re-run fitment on topic instruction change — TOPIC-06
- [ ] New topic backfill — generate fitment for existing documents when topic added — PROC-05
- [ ] Failed document retry — automatic retry on next poll cycle — PROC-06
- [ ] AI summary in document detail view — FE-04
- [ ] Filter documents by topic relevance — FE-05
- [ ] Non-localhost config URLs — set real VDR_AGENT_BASE_URL for DEV/PRE_PROD

### Out of Scope

- Temporal workflows — DB polling with asyncio is sufficient; Temporal adds infra overhead not justified at this stage
- Document upload — documents come from SharePoint via ingestion-service only
- Authentication in vdr-agent — internal service; defer to user-service SSO
- Offline mode — real-time polling is core UX

## Context

**Shipped v1.0** with 2,299 LOC Python across 10 phases and 21 plans.

**Tech stack:** FastAPI 0.115+ / Python 3.12 / psycopg 3.3.3 / AsyncConnectionPool / boto3 (Bedrock) / Poetry / Docker

**Architecture:**
- `vdr-agent` — FastAPI service on port 8001 (host 8004), owns `vdr_agent` schema (4 tables: topics, processing_state, document_summaries, fitment_results)
- Background poller (`run_poller()`) detects completed docs via cross-schema query against `ai_rag.documents`, claims via `FOR UPDATE SKIP LOCKED`
- AI pipeline: section summaries (parallel via `asyncio.gather`) → combined summary → per-topic fitment (parallel, rate-limited via `GlobalRateLimiter` semaphore)
- REST API: 5 topic CRUD endpoints + 3 results endpoints
- Frontend: `vdr-frontend` wired via `vdrAgentApi` Axios instance, polling every 12s

**Known issues:**
- CORS wildcard needs restriction for production
- `VDR_AGENT_BASE_URL` placeholder in DEV/PRE_PROD configs
- `getDocumentFitment()` is dead code — per-topic fitment detail never rendered
- AddScope form allows empty instruction, causing 422 from API

## Constraints

- **Tech stack**: FastAPI + PostgreSQL + asyncio — must match ingestion-service conventions (Poetry, psycopg, raw SQL DAOs, Pydantic settings)
- **No Temporal**: background polling loop replaces workflow orchestration
- **LLM provider**: AWS Bedrock only (Claude Sonnet via boto3)
- **Database**: Share PostgreSQL cluster with ingestion-service; vdr-agent owns vdr_agent schema
- **Retries**: None for now — failures are skipped silently, to be revisited

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| No Temporal in vdr-agent | AI generation is simpler than ingestion pipeline; DB polling sufficient | ✓ Good — 9-day build with zero workflow infra overhead |
| DB polling instead of HTTP callback | No changes needed in ingestion-service; vdr-agent is fully autonomous | ✓ Good — clean separation, no cross-service coupling |
| Skip retries initially | Simplifies implementation; failures can be re-queued in future | ✓ Good — deferred to v2 PROC-06 |
| Separate microservice | Clean separation of concerns; ingestion owns pipeline, vdr-agent owns AI analysis | ✓ Good — independent deployment and scaling |
| FOR UPDATE SKIP LOCKED from day 1 | Cannot be safely retrofitted; prevents duplicate processing | ✓ Good — zero concurrency bugs |
| asyncio.to_thread for boto3 | Keeps event loop non-blocking for all Bedrock calls | ✓ Good — 50-worker ThreadPoolExecutor prevents deadlock |
| Soft-delete for topics | Preserves fitment_results FK references | ✓ Good — no CASCADE data loss |
| DB connection discipline | No connection held during Bedrock calls; short-lived per-operation blocks | ✓ Good — prevents pool exhaustion under load |
| Text CHECK constraints over PG ENUM | ALTER-friendly for future status additions | ✓ Good — easier schema evolution |
| V6 column rename (instruction_text → instruction) | Align DB with DAO/model naming | ✓ Good — single migration, no API impact |

---
*Last updated: 2026-03-06 after v1.0 milestone*
