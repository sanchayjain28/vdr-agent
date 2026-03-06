---
phase: 05-polling-loop
plan: 01
subsystem: database
tags: [psycopg3, pydantic-settings, postgres, cross-schema, polling]

# Dependency graph
requires:
  - phase: 03-db-layer
    provides: ProcessingStateDAO base class and DatabasePool connection pattern
  - phase: 04-llm-client
    provides: Settings class with env_prefix=VDR_AGENT_ pattern for new fields
provides:
  - "3 poller config fields in Settings: poll_interval_seconds, poll_batch_size, stale_lock_threshold_minutes"
  - "ProcessingStateDAO.find_unregistered_documents(limit) — cross-schema detection query"
affects: [05-02-polling-loop, poller.py, worker]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Field(default=N, description='... — override with VDR_AGENT_X') pattern for new Settings fields"
    - "Cross-schema SELECT using fully-qualified ai_rag.documents and vdr_agent.processing_state"

key-files:
  created: []
  modified:
    - vdr-agent/app/config/__init__.py
    - vdr-agent/app/db/dao/processing_state_dao.py

key-decisions:
  - "ai_rag.documents status column is `status` (NOT `embedding_status`) — value 'completed' means full pipeline done including embeddings"
  - "find_unregistered_documents is SELECT only — no commit issued, no connection held after fetchall"
  - "Cross-schema query works because configure() sets search_path=vdr_agent,ai_rag,public on every pooled connection"

patterns-established:
  - "Config fields: insert after bedrock_max_concurrent, before cors_origins; no other file changes needed"
  - "DAO static methods: SELECT-only methods close connection block after fetchall, no commit"

requirements-completed: [PROC-01]

# Metrics
duration: 5min
completed: 2026-03-05
---

# Phase 5 Plan 01: Poller Config Fields and find_unregistered_documents Summary

**3 tunable poller config fields added to Settings and cross-schema document detection query implemented in ProcessingStateDAO**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-05T07:30:00Z
- **Completed:** 2026-03-05T07:35:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added poll_interval_seconds (default 10), poll_batch_size (default 5), and stale_lock_threshold_minutes (default 30) to Settings, auto-mapped via existing VDR_AGENT_ env prefix
- Implemented ProcessingStateDAO.find_unregistered_documents(limit=5) with cross-schema SQL querying ai_rag.documents WHERE status='completed' NOT IN vdr_agent.processing_state
- Both modules import cleanly with no existing code changed

## Task Commits

Each task was committed atomically:

1. **Task 1: Add 3 poller config fields to Settings** - `1513308` (feat)
2. **Task 2: Add find_unregistered_documents() to ProcessingStateDAO** - `a4045bc` (feat)

## Files Created/Modified
- `vdr-agent/app/config/__init__.py` - Added poll_interval_seconds, poll_batch_size, stale_lock_threshold_minutes fields after bedrock_max_concurrent
- `vdr-agent/app/db/dao/processing_state_dao.py` - Appended find_unregistered_documents() static method at end of class

## Decisions Made
- ai_rag.documents uses column `status` (not `embedding_status`) — verified from ingestion-service V3 migration; value 'completed' means full pipeline including embeddings
- find_unregistered_documents is SELECT-only — no commit block needed, releases connection immediately after fetchall
- Cross-schema query uses fully-qualified schema prefixes (ai_rag.documents, vdr_agent.processing_state) matching the search_path set by pool.py configure()

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Plan 05-02 can now import get_settings().poll_interval_seconds, .poll_batch_size, .stale_lock_threshold_minutes
- Plan 05-02 can call ProcessingStateDAO.find_unregistered_documents(limit) to detect new documents each poll cycle
- No blockers for polling loop implementation

---
*Phase: 05-polling-loop*
*Completed: 2026-03-05*
