# Phase 4: LLM Client - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

A minimal async boto3 Bedrock wrapper for vdr-agent: `ClaudeClient.invoke()` that offloads `invoke_model()` to `asyncio.to_thread()`, and `GlobalRateLimiter` that gates all concurrent Bedrock calls via a semaphore. No streaming, no batch processing, no retry logic. Pure infrastructure consumed by Phases 6 and 7.

</domain>

<decisions>
## Implementation Decisions

### invoke() signature
- `ClaudeClient.invoke(prompt: str, system_prompt: str | None = None) -> str`
- Separate `system_prompt` param — Phase 6 (section summaries, combined summary) and Phase 7 (fitment per topic) both need system message (instructions) + user message (document content)
- Returns the response text string directly (not a response object) — callers only need the text
- `stop_reason` is checked internally: if `stop_reason != "end_turn"`, log a WARNING and still return the (possibly truncated) text — do not raise on truncation, just warn

### Model selection
- Configurable via `VDR_AGENT_BEDROCK_MODEL` env var with default `global.anthropic.claude-sonnet-4-5-20250929-v1:0` (matches ingestion-service)
- Single model for all call types (summaries + fitment) — no per-call override needed in Phase 4
- `max_tokens` configurable via `VDR_AGENT_BEDROCK_MAX_TOKENS` env var, default `4096`
- Both added to Pydantic Settings in `app/config/__init__.py` (already exists from Phase 1)

### Reuse vs. fresh write
- **Write minimal fresh client** — do NOT port ingestion-service `ClaudeClient`
- ingestion-service client is 400+ lines with retry, streaming, batch, exception hierarchy — all unwanted complexity for vdr-agent
- ingestion-service uses `loop.run_in_executor()` (deprecated pattern); vdr-agent must use `asyncio.to_thread()` (required by roadmap)
- Target: ~60–80 lines in `app/core/llm/claude_client.py`
- Boto3 client created once at module level (or lazily on first call) — no async context manager needed
- `ThreadPoolExecutor(max_workers=50, thread_name_prefix="bedrock")` set on the event loop at startup (or as a module-level executor passed to `asyncio.to_thread`)

### Error handling
- **Raise exception** on Bedrock failure — `ClaudeClientError(message, original_exc)` — simple custom exception
- Callers (Phase 6/7) catch `ClaudeClientError` per-call and set the relevant row's status to `failed`
- No retry in `invoke()` — retries are out of scope per PROJECT.md
- `boto3.exceptions.ClientError` and `BotoCoreError` are both caught and re-raised as `ClaudeClientError`

### GlobalRateLimiter
- **Copy and adapt from ingestion-service** `app/core/llm/rate_limiter.py` — but strip RPM tracking (timestamp deque, `_enforce_rpm_limit`)
- vdr-agent `GlobalRateLimiter` needs only the concurrency semaphore (`asyncio.Semaphore`), not RPM windowing
- `max_concurrent` configurable via `VDR_AGENT_BEDROCK_MAX_CONCURRENT` env var, default `10`
- Lazy init: semaphore created on first `acquire()` call inside a running event loop (not at import time) — same pattern as ingestion-service `_ensure_async_primitives()`
- Module-level singleton: `_rate_limiter: GlobalRateLimiter | None = None` + `get_rate_limiter() -> GlobalRateLimiter`
- Lives at `app/core/llm/rate_limiter.py`

### ThreadPoolExecutor
- `ThreadPoolExecutor(max_workers=50, thread_name_prefix="bedrock")` created as a module-level singleton in `app/core/llm/claude_client.py`
- Passed explicitly to `asyncio.to_thread()` is NOT how `to_thread` works — instead, set it as the default executor on the loop at startup: `loop.set_default_executor(executor)`
- This is done in `startup.py` alongside pool initialization
- 50 workers ensures concurrent `asyncio.to_thread()` calls don't queue behind each other when `GlobalRateLimiter` allows up to 10 concurrent; headroom for other async thread usage

### Claude's Discretion
- Exact boto3 client configuration (timeout values, region fallback)
- Where to place the module-level boto3 client (lazy `_bedrock_client` vs. initialized in startup)
- Whether `ClaudeClientError` needs a `status_code` field or just `message` + `original_exc`
- Exact log format for truncation warnings

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ingestion-service/app/core/llm/rate_limiter.py` → `GlobalRateLimiter._ensure_async_primitives()`: Copy the lazy semaphore init pattern verbatim — it correctly handles event loop binding
- `ingestion-service/app/core/llm/claude/client.py` → `_map_exception()`: Reference for which boto3 error codes to catch; vdr-agent needs only `ThrottlingException` and `AccessDeniedException` handling
- `ingestion-service/app/startup.py` → executor setup pattern: Add `loop.set_default_executor(ThreadPoolExecutor(max_workers=50))` in the lifespan startup block

### Established Patterns
- `from __future__ import annotations` at top of every module (Python 3.9)
- `AWS_BEARER_TOKEN_BEDROCK` env var is already set in `.env.local` — shared with ingestion-service, no `VDR_AGENT_` prefix
- `anthropic_version = "bedrock-2023-05-31"` required in Bedrock request body (see ingestion-service client)
- `stop_reason` is in Bedrock response body as `response_body["stop_reason"]`; `"end_turn"` = normal completion

### Integration Points
- `app/config/__init__.py` (Phase 1) — add `VDR_AGENT_BEDROCK_MODEL`, `VDR_AGENT_BEDROCK_MAX_TOKENS`, `VDR_AGENT_BEDROCK_MAX_CONCURRENT` to Pydantic Settings
- `app/startup.py` (Phase 1/3) — add `loop.set_default_executor(ThreadPoolExecutor(max_workers=50))` before the yield
- Phase 6 (AI Summary) — calls `await ClaudeClient.invoke(prompt, system_prompt)` per section + once for combined summary
- Phase 7 (Fitment) — calls `await ClaudeClient.invoke(prompt, system_prompt)` per active topic per document
- `get_rate_limiter()` singleton imported and used as `async with get_rate_limiter().acquire():` wrapping each `invoke()` call

</code_context>

<specifics>
## Specific Ideas

- `ClaudeClient` should be stateless — no instance needed, just a module-level function `async def invoke(prompt, system_prompt=None)` that uses the module-level boto3 client and rate limiter internally. Callers: `from app.core.llm.claude_client import invoke`
- This is simpler than the ingestion-service class-based approach and fits vdr-agent's single-model, no-config-per-call usage pattern
- `GlobalRateLimiter` acquire is an `@asynccontextmanager`: `async with get_rate_limiter().acquire(): result = await invoke(...)`

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-llm-client*
*Context gathered: 2026-03-05*
