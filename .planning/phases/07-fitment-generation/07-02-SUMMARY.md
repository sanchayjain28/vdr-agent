---
phase: 07-fitment-generation
plan: 02
subsystem: api
tags: [bedrock, pgvector, asyncio, cohere, fitment, processor]

# Dependency graph
requires:
  - phase: 07-01
    provides: V7 migration (reasoning nullable), TopicDAO.list_active_by_project(), Settings.bedrock_embedding_model
  - phase: 06-ai-summary-generation
    provides: DocumentSummaryDAO, ProcessingStateDAO, invoke(), rate_limiter, processor.py baseline
provides:
  - "_embed_query_sync: sync Cohere Bedrock embedding with input_type='search_query'"
  - "_evaluate_topic: async per-topic fitment with pgvector top-5 chunk selection, Claude invocation, upsert"
  - "FITMENT_SYSTEM_PROMPT constant"
  - "process_document() with re-run safety check and full fitment block (Phase 7)"
affects: [08-topic-crud-api, 09-results-api, 10-frontend]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Re-run safety check via DocumentSummaryDAO.get_by_document() before summary generation"
    - "if/else convergence pattern: both branches set final_summary before shared fitment block"
    - "asyncio.to_thread() for sync boto3 embedding call — never called directly from async context"
    - "Short-lived DB connections released before Bedrock calls to prevent pool exhaustion"
    - "Per-topic BaseException catch with failed-status upsert — other topics continue unaffected"
    - "pgvector cosine similarity: ORDER BY embedding <=> %s::vector LIMIT 5 for top-5 chunk selection"

key-files:
  created: []
  modified:
    - vdr-agent/app/worker/processor.py

key-decisions:
  - "process_document() uses if/else re-run safety: existing summary path sets final_summary and falls through to fitment; no outer try wraps the whole function"
  - "Fitment block is top-level in function body (not nested in else) — runs after both summary paths on success"
  - "Phase 7 does NOT touch processing_state at all — summary_status remains 'done' from Phase 6 (locked decision)"
  - "_get_bedrock_client() reused for embedding calls — same boto3 bedrock-runtime singleton, modelId passed at call time"
  - "Cohere input_type='search_query' for topic embedding — intentionally distinct from 'search_document' used by ingestion-service"
  - "Fallback to first-5 chunks by chunk_index if no vector-indexed chunks (all embeddings NULL)"

patterns-established:
  - "Connection discipline in _evaluate_topic: embed (thread) -> fetch chunks (short-lived) -> invoke (rate-limited) -> upsert (short-lived)"
  - "asyncio.gather(*topic_tasks, return_exceptions=True) fires all topic evaluations in parallel; errors logged per-topic"

requirements-completed: [PROC-03]

# Metrics
duration: 2min
completed: 2026-03-05
---

# Phase 7 Plan 02: Fitment Generation Pipeline Summary

**Embedding-based per-topic fitment with parallel Bedrock invocations using Cohere pgvector top-5 chunk selection, wired into process_document() with re-run safety and no processing_state writes**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-05T08:52:37Z
- **Completed:** 2026-03-05T08:54:41Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Added `_embed_query_sync` using Cohere Bedrock with `input_type='search_query'` for correct cosine similarity ordering against ingestion-service's `search_document` chunks
- Added `_evaluate_topic` coroutine: embeds topic query, fetches top-5 chunks via pgvector `<=>` operator, invokes Claude under rate limiter, upserts result or writes `status='failed'` on any exception
- Added `FITMENT_SYSTEM_PROMPT` ESG analyst evaluation prompt
- Restructured `process_document()` with re-run safety check (skip summary if DocumentSummaryDAO row exists) and fitment block wired in after both summary paths

## Task Commits

Each task was committed atomically:

1. **Task 1: Add _embed_query_sync, FITMENT_SYSTEM_PROMPT, _evaluate_topic** - `94cd870` (feat)
2. **Task 2: Wire re-run safety check and fitment block into process_document()** - `832694b` (feat)

## Files Created/Modified
- `vdr-agent/app/worker/processor.py` - Added fitment helpers and restructured process_document() with re-run safety + Phase 7 fitment block

## Decisions Made
- `process_document()` uses separate try blocks (not one outer try) — re-run check, Phase 1 chunk fetch, and Phase 2+3 AI calls each handle their own failure mode independently
- Fitment block placed as top-level statement after the if/else — runs whether summary was freshly generated or already existed; only unreachable if summary generation fails (which returns early)
- No `ProcessingStateDAO` calls anywhere in the fitment block — `summary_status` is intentionally left as `'done'` from Phase 6 (locked decision from CONTEXT.md)
- `_get_bedrock_client()` reused from `claude_client.py` for embedding — same boto3 `bedrock-runtime` singleton; `modelId` is passed at call time, not at client creation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `process_document()` now implements the full end-to-end pipeline: summary generation + fitment evaluation for all active topics
- Every document with a completed summary automatically gets fitment results written to `fitment_results` for all active project topics
- Phase 9 (Results API) can now serve `FitmentResultDAO.list_by_document()` data populated by this pipeline

---
*Phase: 07-fitment-generation*
*Completed: 2026-03-05*
