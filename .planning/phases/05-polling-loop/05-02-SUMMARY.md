---
phase: 05-polling-loop
plan: 02
subsystem: worker
tags: [asyncio, polling, background-task, fastapi-lifespan, psycopg3]

# Dependency graph
requires:
  - phase: 05-polling-loop/05-01
    provides: "3 poller config fields in Settings and ProcessingStateDAO.find_unregistered_documents()"
  - phase: 03-db-layer
    provides: "ProcessingStateDAO with reset_stale_claims, insert, claim_documents, update_status"
  - phase: 04-llm-client
    provides: "startup.py ThreadPoolExecutor wiring and lifespan pattern"
provides:
  - "app/worker/__init__.py: package marker enabling app.worker.* imports"
  - "app/worker/poller.py: run_poller() autonomous poll loop coroutine with active_tasks set and CancelledError handling"
  - "app/worker/processor.py: process_document(processing_state_id, document_id) Phase 5 stub calling update_status('done')"
  - "app/startup.py: poller_task wired into lifespan — starts before yield, cancelled and awaited after yield"
affects: [06-ai-processing, processor.py]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "active_tasks Set[asyncio.Task] in run_poller() scope — persists across cycles, prevents GC of in-flight tasks"
    - "CancelledError caught + re-raised in BOTH try blocks (poll cycle and sleep) — two await points where cancellation can arrive"
    - "Local import of process_document inside _poll_cycle to avoid circular import at module level"
    - "task.add_done_callback(active_tasks.discard) for automatic task reference cleanup"
    - "lifespan poller_task.cancel() + await with CancelledError suppressed before DB pool close"

key-files:
  created:
    - vdr-agent/app/worker/__init__.py
    - vdr-agent/app/worker/poller.py
    - vdr-agent/app/worker/processor.py
  modified:
    - vdr-agent/app/startup.py

key-decisions:
  - "active_tasks set lives in run_poller() scope (not _poll_cycle) — task refs must persist across cycles or GC destroys in-flight coroutines"
  - "process_document imported locally inside _poll_cycle to avoid circular dependency if processor.py ever imports from poller.py"
  - "Shutdown sequence: cancel poller first, await it (suppress CancelledError), then close DB pool — ensures no DAO calls after pool close"
  - "Phase 5 stub marks status 'done' immediately — makes end-to-end poll loop testable without Bedrock credentials"

patterns-established:
  - "Worker package: _poll_cycle() helper keeps run_poller() clean; all 5 steps in _poll_cycle in order"
  - "Fire-and-forget asyncio tasks: create_task + add to set + add_done_callback(set.discard) is the canonical pattern"

requirements-completed: [PROC-01]

# Metrics
duration: 4min
completed: 2026-03-05
---

# Phase 5 Plan 02: Worker Package and Poller Wiring Summary

**asyncio poll loop coroutine with FOR UPDATE SKIP LOCKED claim cycle wired into FastAPI lifespan as cancellable background task**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-05T07:55:12Z
- **Completed:** 2026-03-05T07:59:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created app/worker/ package with run_poller() coroutine implementing 5-step poll cycle: reset stale claims, detect + register new docs, atomically claim rows, fire asyncio tasks per doc, sleep
- Implemented process_document() Phase 5 stub that immediately marks processing_state as 'done' — makes full loop testable without AI calls
- Wired poller into startup.py lifespan: task starts before yield with done callback, cancelled and awaited cleanly on shutdown before DB pool close
- active_tasks set held in run_poller() scope prevents 'Task was destroyed but it is pending!' asyncio warnings

## Task Commits

Each task was committed atomically:

1. **Task 1: Create app/worker/ package with poller.py and processor.py** - `095e406` (feat)
2. **Task 2: Wire poller task into startup.py lifespan** - `a486ce2` (feat)

## Files Created/Modified
- `vdr-agent/app/worker/__init__.py` - Empty package marker
- `vdr-agent/app/worker/poller.py` - run_poller() poll loop and _poll_cycle() helper; CancelledError handled and re-raised in both await points
- `vdr-agent/app/worker/processor.py` - process_document(processing_state_id, document_id) stub; calls update_status(ps_id, 'done')
- `vdr-agent/app/startup.py` - Added run_poller import, poller_task creation with done callback, shutdown cancel/await sequence

## Decisions Made
- active_tasks set defined in run_poller() outer scope so task references survive across poll cycles; done callback removes completed tasks
- process_document imported locally inside _poll_cycle (not at module top) to break potential future circular imports
- Shutdown: cancel poller before closing DB pool to guarantee no DAO calls on closed pool
- Phase 5 stub marks 'done' immediately — enables end-to-end polling smoke test without Bedrock credentials or AI logic

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 6 can replace process_document() body with real Bedrock AI calls without changing poller.py at all — interface is fixed
- poll_interval_seconds, poll_batch_size, stale_lock_threshold_minutes are all tunable via VDR_AGENT_ env vars
- Phase 5 complete: vdr-agent starts with background poller running, claims documents atomically, fires tasks, shuts down cleanly

## Self-Check: PASSED

All files exist:
- vdr-agent/app/worker/__init__.py: FOUND
- vdr-agent/app/worker/poller.py: FOUND
- vdr-agent/app/worker/processor.py: FOUND
- vdr-agent/app/startup.py: FOUND
- .planning/phases/05-polling-loop/05-02-SUMMARY.md: FOUND

All commits exist:
- 095e406: FOUND
- a486ce2: FOUND

---
*Phase: 05-polling-loop*
*Completed: 2026-03-05*
