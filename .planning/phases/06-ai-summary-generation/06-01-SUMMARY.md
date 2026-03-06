---
phase: 06-ai-summary-generation
plan: "01"
subsystem: ai
tags: [bedrock, asyncio, rate-limiter, postgres, pydantic-settings]

requires:
  - phase: 05-polling-loop
    provides: process_document() stub and poller.py that calls it with (processing_state_id, document_id)
  - phase: 04-llm-client
    provides: invoke() coroutine and GlobalRateLimiter via get_rate_limiter()
  - phase: 03-db-layer
    provides: DocumentSummaryDAO.upsert(), ProcessingStateDAO.update_status(), DatabasePool.connection()
  - phase: 02-db-schema
    provides: ai_rag.embeddings table with content/chunk_index/document_id columns

provides:
  - Full AI summary generation pipeline in process_document() — fetch chunks, parallel section summaries, combined final summary
  - summary_section_size config field (default 5) mapped to VDR_AGENT_SUMMARY_SECTION_SIZE

affects:
  - 07-vdr-agent-service-foundation-topic-management
  - Phase 7 fitment relies on document_summaries table populated by this phase

tech-stack:
  added: []
  patterns:
    - "Fetch-then-compute: DB connection for chunk fetch closes before any Bedrock call (prevents pool exhaustion during multi-second AI waits)"
    - "asyncio.gather(*tasks, return_exceptions=True) for parallel section summarisation — all tasks run to completion before error inspection"
    - "Rate limiter gate: every invoke() call wrapped in async with get_rate_limiter().acquire():"
    - "0-chunk guard: missing embeddings logged as WARNING and marked failed (not done)"
    - "Top-level except Exception: any unhandled error sets summary_status = 'failed'"

key-files:
  created: []
  modified:
    - vdr-agent/app/config/__init__.py
    - vdr-agent/app/worker/processor.py

key-decisions:
  - "summary_section_size default=5 — each section sent to Claude as one invoke() call; sections fired in parallel"
  - "return_exceptions=True is mandatory in asyncio.gather — ensures rate limiter semaphore slots are cleanly released even when tasks fail"
  - "DB connection for chunk fetch must close before AI pipeline begins — no DatabasePool.connection() held during Bedrock calls"
  - "0-chunk documents marked 'failed' (not 'done') — prevents Phase 7 fitment from running against an empty summary"
  - "ClaudeClientError imported but not explicitly caught — it is a subclass of Exception; import documents the dependency"

patterns-established:
  - "SECTION_SYSTEM_PROMPT and COMBINE_SYSTEM_PROMPT are module-level constants matching exact ESG-aware wording from CONTEXT.md"
  - "_summarise_section() is a private async helper — never holds DB connection, always acquires rate limiter before invoke()"

requirements-completed:
  - PROC-02

duration: 3min
completed: "2026-03-05"
---

# Phase 6 Plan 01: AI Summary Generation Summary

**Three-phase AI pipeline replacing Phase 5 stub: parallel ESG section summaries via asyncio.gather with rate-limiter gates, combined into final document summary persisted to document_summaries table**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-05T08:27:00Z
- **Completed:** 2026-03-05T08:30:17Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `summary_section_size: int = Field(default=5, ...)` to Settings class, mapping to `VDR_AGENT_SUMMARY_SECTION_SIZE` env var
- Replaced Phase 5 stub in `process_document()` with full three-phase AI pipeline: chunk fetch (short-lived DB), parallel section summaries via `asyncio.gather(return_exceptions=True)`, final combine call
- All invoke() calls wrapped with `async with get_rate_limiter().acquire():` — prevents Bedrock quota breaches
- 0-chunk guard marks documents `failed` with WARNING log; top-level except marks `failed` on any AI/DB error

## Task Commits

Each task was committed atomically:

1. **Task 1: Add summary_section_size config field to Settings** - `daf24be` (feat)
2. **Task 2: Implement process_document() with full AI summary pipeline** - `fa1eee3` (feat)

## Files Created/Modified

- `vdr-agent/app/config/__init__.py` - Added `summary_section_size` field after `stale_lock_threshold_minutes`
- `vdr-agent/app/worker/processor.py` - Full AI summary pipeline replacing Phase 5 stub

## Decisions Made

None - followed plan as specified. All implementation choices (prompts, error handling patterns, asyncio.gather arguments, DB connection discipline) were locked decisions from CONTEXT.md carried into the plan verbatim.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 6 is the only plan in this phase — AI summary generation is complete
- `document_summaries` table will be populated for every document that has embedding chunks
- Phase 7 (fitment evaluation) can proceed: it reads from `document_summaries` and `vdr_agent.topics`
- No blockers. Bedrock quota concern (200 RPM shared with ingestion-service) noted as pre-existing concern in STATE.md

## Self-Check: PASSED

- FOUND: vdr-agent/app/config/__init__.py
- FOUND: vdr-agent/app/worker/processor.py
- FOUND: .planning/phases/06-ai-summary-generation/06-01-SUMMARY.md
- FOUND commit: daf24be (feat(06-01): add summary_section_size config field)
- FOUND commit: fa1eee3 (feat(06-01): implement process_document() with full AI summary pipeline)

---
*Phase: 06-ai-summary-generation*
*Completed: 2026-03-05*
