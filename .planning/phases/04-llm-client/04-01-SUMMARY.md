---
phase: 04-llm-client
plan: "01"
subsystem: llm-client
tags: [bedrock, async, rate-limiter, boto3]
dependency_graph:
  requires: []
  provides: [app.core.llm.claude_client, app.core.llm.rate_limiter]
  affects: [phase-06, phase-07]
tech_stack:
  added: []
  patterns: [asyncio.to_thread, asynccontextmanager, lazy-singleton, dataclass]
key_files:
  created:
    - vdr-agent/app/core/llm/__init__.py
    - vdr-agent/app/core/llm/claude_client.py
    - vdr-agent/app/core/llm/rate_limiter.py
  modified: []
decisions:
  - "asyncio.to_thread() wraps blocking boto3 call — never loop.run_in_executor()"
  - "stop_reason != end_turn logs WARNING but does not raise — callers get text"
  - "Semaphore created lazily inside _ensure_async_primitives() not at import time"
  - "get_rate_limiter() defers app.config import to avoid circular import at module load"
metrics:
  duration: "3 min"
  completed_date: "2026-03-05"
  tasks_completed: 2
  files_created: 3
---

# Phase 4 Plan 1: LLM Client — Bedrock Async Wrapper Summary

**One-liner:** Async boto3 Bedrock wrapper with asyncio.to_thread() offload and semaphore-based concurrency gating via lazy singleton pattern.

## What Was Built

Two new files forming the Bedrock integration layer consumed by Phases 6 and 7:

- `app/core/llm/claude_client.py` — `invoke()` async function offloads blocking boto3 call to thread pool via `asyncio.to_thread()`. Lazy `_bedrock_client` singleton. `ClaudeClientError` wraps `ClientError`/`BotoCoreError`. Non-`end_turn` stop reasons log WARNING but still return text.
- `app/core/llm/rate_limiter.py` — `GlobalRateLimiter` dataclass with `_ensure_async_primitives()` lazy semaphore init bound to the running event loop. `acquire()` asynccontextmanager. `get_rate_limiter()` module-level singleton reads `settings.bedrock_max_concurrent` (added in Plan 04-02).
- `app/core/llm/__init__.py` — empty package marker.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Create claude_client.py + __init__.py | 5cb55c2 |
| 2 | Create rate_limiter.py | 8d1a335 |

## Deviations from Plan

None - plan executed exactly as written.

## Verification

All assertions passed:
- `asyncio.iscoroutinefunction(invoke)` — True
- `inspect.isclass(ClaudeClientError)` — True
- `hasattr(GlobalRateLimiter, '_ensure_async_primitives')` — True
- Both module imports succeed without error

## Self-Check: PASSED

Files exist:
- vdr-agent/app/core/llm/__init__.py — FOUND
- vdr-agent/app/core/llm/claude_client.py — FOUND
- vdr-agent/app/core/llm/rate_limiter.py — FOUND

Commits exist:
- 5cb55c2 — FOUND
- 8d1a335 — FOUND
