# Phase 4: LLM Client - Research

**Researched:** 2026-03-05
**Domain:** boto3 Bedrock async wrapper, asyncio concurrency primitives
**Confidence:** HIGH

## Summary

Phase 4 delivers a minimal (~60–80 line) async Bedrock wrapper for vdr-agent. The entire client surface is two files: `app/core/llm/claude_client.py` (module-level `invoke()` function + `ClaudeClientError`) and `app/core/llm/rate_limiter.py` (`GlobalRateLimiter` with semaphore-only concurrency gating). A third change adds `ThreadPoolExecutor` setup to `app/startup.py` and three new fields to `app/config/__init__.py`.

All design decisions are locked in CONTEXT.md. The ingestion-service counterparts have been read in full and are used as reference — but NOT ported — because they carry retry, streaming, batch, RPM windowing and class-based structure that are explicitly out of scope. The key pattern difference: vdr-agent uses `asyncio.to_thread()` (modern, Python 3.9+) whereas ingestion-service uses the deprecated `loop.run_in_executor()`.

**Primary recommendation:** Write fresh, minimal files. Copy only the `_ensure_async_primitives()` lazy-init pattern from ingestion-service `rate_limiter.py` verbatim. Everything else is a fresh write.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- `invoke(prompt: str, system_prompt: str | None = None) -> str` — module-level function, not a class method
- Returns `str` directly; raises `ClaudeClientError` on failure (no retry)
- `stop_reason != "end_turn"` → log WARNING, still return text (no raise)
- Model: `VDR_AGENT_BEDROCK_MODEL` env var, default `global.anthropic.claude-sonnet-4-5-20250929-v1:0`
- `max_tokens`: `VDR_AGENT_BEDROCK_MAX_TOKENS` env var, default `4096`
- Write minimal fresh client — do NOT port ingestion-service `ClaudeClient`
- boto3 client created once at module level (lazy `_bedrock_client`)
- `GlobalRateLimiter` semaphore only (no RPM windowing), max_concurrent=10 default
- `max_concurrent`: `VDR_AGENT_BEDROCK_MAX_CONCURRENT` env var, default `10`
- Lazy semaphore init — copy `_ensure_async_primitives()` pattern from ingestion-service
- Module-level singleton: `_rate_limiter: GlobalRateLimiter | None = None` + `get_rate_limiter()`
- `ThreadPoolExecutor(max_workers=50, thread_name_prefix="bedrock")` set via `loop.set_default_executor()` in `startup.py`
- `asyncio.to_thread()` pattern (NOT `loop.run_in_executor()`)
- Catch `ClientError` and `BotoCoreError`, re-raise as `ClaudeClientError(message, original_exc)`
- Files: `app/core/llm/claude_client.py`, `app/core/llm/rate_limiter.py`

### Claude's Discretion
- Exact boto3 client configuration (timeout values, region fallback)
- Where to place the module-level boto3 client (lazy `_bedrock_client` vs. initialized in startup)
- Whether `ClaudeClientError` needs a `status_code` field or just `message` + `original_exc`
- Exact log format for truncation warnings

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| boto3 | Already in vdr-agent venv | AWS Bedrock `invoke_model()` | AWS SDK — no alternative for Bedrock |
| botocore | Bundled with boto3 | Exception types: `ClientError`, `BotoCoreError` | Same package |
| asyncio | stdlib | `asyncio.to_thread()`, `asyncio.Semaphore` | Python 3.9 stdlib — no install needed |
| contextlib | stdlib | `@asynccontextmanager` for `acquire()` | stdlib |
| concurrent.futures | stdlib | `ThreadPoolExecutor` for default loop executor | stdlib |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic-settings | Already installed (Phase 1) | Three new config fields in `Settings` | Config expansion only |
| logging | stdlib | WARNING for truncation, INFO for startup | All modules |

**Installation:** No new packages required. boto3 is already in `vdr-agent/pyproject.toml` (used by `app/config/__init__.py` for Secrets Manager).

## Architecture Patterns

### File Layout
```
vdr-agent/app/core/llm/
├── __init__.py          # empty or re-exports
├── claude_client.py     # invoke() function + ClaudeClientError + _bedrock_client singleton
└── rate_limiter.py      # GlobalRateLimiter dataclass + get_rate_limiter() singleton

vdr-agent/app/
├── config/__init__.py   # ADD: bedrock_model, bedrock_max_tokens, bedrock_max_concurrent fields
└── startup.py           # ADD: ThreadPoolExecutor setup + loop.set_default_executor()
```

### Pattern 1: Module-level lazy boto3 client
**What:** `_bedrock_client` is `None` at import; created on first `invoke()` call inside `_get_bedrock_client()`.
**When to use:** boto3 client creation is synchronous and cheap — lazy is fine; avoids import-time side effects.

```python
# Source: adapted from ingestion-service/app/core/llm/claude/client.py _ensure_client()
from __future__ import annotations

import boto3
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import BotoCoreError, ClientError

_bedrock_client = None

def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        settings = get_settings()
        boto_config = BotocoreConfig(
            read_timeout=300,        # 5 min — Claude responses can be slow
            connect_timeout=10,
            retries={"max_attempts": 0},  # no boto3 retries — vdr-agent has no retry policy
        )
        _bedrock_client = boto3.client(
            service_name="bedrock-runtime",
            region_name=settings.aws_region,
            config=boto_config,
        )
    return _bedrock_client
```

**Discretion recommendation:** `read_timeout=300` (5 min), `connect_timeout=10`, `retries={"max_attempts": 0}` (boto3 retry disabled — vdr-agent raises immediately on failure). `ClaudeClientError` needs only `message: str` and `original_exc: Exception` — no `status_code` field needed since callers don't branch on HTTP status.

### Pattern 2: asyncio.to_thread() for synchronous boto3 call
**What:** Offloads the blocking `invoke_model()` call to the default thread pool without blocking the event loop.
**When to use:** Any synchronous I/O call from async context. Python 3.9+.

```python
# Source: Python 3.9 stdlib docs — asyncio.to_thread()
import asyncio
import json

async def invoke(prompt: str, system_prompt: str | None = None) -> str:
    client = _get_bedrock_client()
    settings = get_settings()

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": settings.bedrock_max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt:
        body["system"] = system_prompt

    def _call() -> dict:
        response = client.invoke_model(
            modelId=settings.bedrock_model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        return json.loads(response["body"].read())

    try:
        response_body = await asyncio.to_thread(_call)
    except (ClientError, BotoCoreError) as exc:
        raise ClaudeClientError(f"Bedrock call failed: {exc}", exc) from exc

    stop_reason = response_body.get("stop_reason")
    if stop_reason != "end_turn":
        LOGGER.warning(
            "Bedrock response truncated or unexpected stop_reason=%r", stop_reason
        )

    return response_body["content"][0]["text"]
```

**Key detail:** `anthropic_version = "bedrock-2023-05-31"` is REQUIRED in the request body — Bedrock rejects calls without it. Confirmed from ingestion-service client (line 299) and the Bedrock API spec.

### Pattern 3: Lazy semaphore init (copy verbatim from ingestion-service)
**What:** Semaphore bound to the running event loop, not created at import time.
**When to use:** Any `asyncio.Semaphore` or `asyncio.Lock` that must survive across potential loop changes (or simply: always, to avoid the classic "no running event loop" import error).

```python
# Source: ingestion-service/app/core/llm/rate_limiter.py _ensure_async_primitives()
def _ensure_async_primitives(self) -> None:
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no running loop — will create when one exists

    if self._bound_loop is not current_loop or self._semaphore is None:
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._bound_loop = current_loop
```

### Pattern 4: GlobalRateLimiter stripped to semaphore-only
**What:** `@asynccontextmanager` wrapping semaphore acquire/release. No RPM tracking, no lock, no timestamp deque.
**When to use:** All Bedrock calls in Phases 6 and 7 go through `async with get_rate_limiter().acquire():`.

```python
# Source: adapted from ingestion-service/app/core/llm/rate_limiter.py
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional
import asyncio

@dataclass
class GlobalRateLimiter:
    max_concurrent: int = 10

    _semaphore: Optional[asyncio.Semaphore] = field(default=None, init=False)
    _bound_loop: Optional[asyncio.AbstractEventLoop] = field(default=None, init=False)

    def _ensure_async_primitives(self) -> None:
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._bound_loop is not current_loop or self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
            self._bound_loop = current_loop

    @asynccontextmanager
    async def acquire(self):
        self._ensure_async_primitives()
        await self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()


_rate_limiter: Optional[GlobalRateLimiter] = None

def get_rate_limiter() -> GlobalRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        from app.config import get_settings
        settings = get_settings()
        _rate_limiter = GlobalRateLimiter(max_concurrent=settings.bedrock_max_concurrent)
    return _rate_limiter
```

### Pattern 5: ThreadPoolExecutor as default loop executor
**What:** Set `ThreadPoolExecutor(max_workers=50)` as the loop's default executor in `startup.py`. `asyncio.to_thread()` uses the default executor automatically.
**When to use:** Set once at startup before any `asyncio.to_thread()` calls.

```python
# Source: Python asyncio docs — loop.set_default_executor()
# In startup.py lifespan(), before yield:
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=50, thread_name_prefix="bedrock")
loop = asyncio.get_event_loop()
loop.set_default_executor(executor)
```

**Why 50 workers:** GlobalRateLimiter caps concurrent Bedrock calls at 10, but the executor needs headroom for other `asyncio.to_thread()` uses (DB pool warmup, etc.) and to avoid queueing. 50 is the established project number from CONTEXT.md.

### Pattern 6: config/__init__.py field additions
Three new fields added to the existing `Settings` class with `VDR_AGENT_` prefix:

```python
bedrock_model: str = Field(
    default="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    description="AWS Bedrock model ID for Claude",
)
bedrock_max_tokens: int = Field(
    default=4096,
    description="Max tokens for Bedrock Claude responses",
)
bedrock_max_concurrent: int = Field(
    default=10,
    description="Max concurrent Bedrock API calls (semaphore)",
)
```

The env var names are `VDR_AGENT_BEDROCK_MODEL`, `VDR_AGENT_BEDROCK_MAX_TOKENS`, `VDR_AGENT_BEDROCK_MAX_CONCURRENT` (prefix comes from `env_prefix = "VDR_AGENT_"`).

### Anti-Patterns to Avoid
- **Creating `asyncio.Semaphore` at module import time:** Binds to whichever loop (if any) is running at import — fails in test environments with fresh loops. Always lazy-init.
- **Calling `boto3.client.invoke_model()` directly from async def:** Blocks the event loop thread. Always use `asyncio.to_thread()`.
- **Using `loop.run_in_executor()`:** Deprecated pattern (ingestion-service uses it — vdr-agent must not). `asyncio.to_thread()` is the modern replacement.
- **Raising on truncation:** CONTEXT.md explicitly requires warning + return, not raise. Callers should receive potentially-truncated text rather than failing.
- **Creating a new boto3 client per `invoke()` call:** Client creation is slow and creates new connections. Use the module-level singleton.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Thread-safe async semaphore | Custom lock-based counter | `asyncio.Semaphore` | stdlib, correct, no race conditions |
| Lazy async primitive init | try/except at every call site | `_ensure_async_primitives()` pattern | Centralised, tested pattern from ingestion-service |
| Boto3 exception mapping | String-parsing error messages | `ClientError.response['Error']['Code']` | boto3's structured error format |
| Thread pool for boto3 | Manual thread management | `ThreadPoolExecutor` + `asyncio.to_thread()` | stdlib, integrates with event loop lifecycle |

**Key insight:** The 50-worker ThreadPoolExecutor is not optional hardening — it directly prevents the deadlock described in ingestion-service TEMP-007. Without sufficient workers, concurrent `asyncio.to_thread()` calls queue behind each other and the semaphore creates a starvation scenario.

## Common Pitfalls

### Pitfall 1: asyncio.Semaphore created at module import time
**What goes wrong:** `asyncio.Semaphore()` at module level binds to the current event loop. In pytest, each test may have a fresh loop, causing "attached to a different loop" RuntimeError.
**Why it happens:** asyncio primitives capture `asyncio.get_event_loop()` at creation time in Python < 3.10; in 3.10+ they use `asyncio.get_running_loop()` but still fail if no loop is running at import time.
**How to avoid:** Always create inside `_ensure_async_primitives()` which calls `asyncio.get_running_loop()`.
**Warning signs:** `RuntimeError: This event loop is already running` or `got Future attached to a different loop`.

### Pitfall 2: Missing `anthropic_version` in request body
**What goes wrong:** Bedrock returns `ValidationException` with an opaque error message.
**Why it happens:** AWS Bedrock's Claude API requires `"anthropic_version": "bedrock-2023-05-31"` in the JSON body — it is not a header, it is a body field.
**How to avoid:** Always include it. Value is hardcoded — it does not change with model version.
**Warning signs:** `ClientError: ValidationException` on first `invoke_model()` call.

### Pitfall 3: Bedrock response body is a streaming object
**What goes wrong:** `response["body"]` from `invoke_model()` is a `StreamingBody` — calling `json.loads(response["body"])` raises `TypeError`.
**Why it happens:** boto3 wraps the HTTP response body in a `StreamingBody` that must be `.read()` before parsing.
**How to avoid:** Always `json.loads(response["body"].read())`.
**Warning signs:** `TypeError: the JSON object must be str, bytes or bytearray, not StreamingBody`.

### Pitfall 4: `asyncio.to_thread()` silently queues when pool is exhausted
**What goes wrong:** With a small default thread pool (Python default: `min(32, os.cpu_count() + 4)`), concurrent calls queue. Under high load this looks like a hang with no error.
**Why it happens:** Python's default ThreadPoolExecutor has far fewer workers than needed for 10+ concurrent blocking Bedrock calls.
**How to avoid:** Set 50-worker executor via `loop.set_default_executor()` in startup BEFORE any `to_thread()` calls.
**Warning signs:** Latency spikes with no errors; all tasks complete eventually but slowly.

### Pitfall 5: `get_rate_limiter()` called before settings are initialised
**What goes wrong:** `get_rate_limiter()` lazily reads `settings.bedrock_max_concurrent` — if called before `_bootstrap_config_sources()` runs, the default (10) is used regardless of env var.
**Why it happens:** Module-level singleton initialised on first import rather than first use inside lifespan.
**How to avoid:** `get_rate_limiter()` is called inside `acquire()`, which is only called from `invoke()`, which is only called from Phases 6/7 — well after lifespan startup. No issue in practice.

### Pitfall 6: `stop_reason` key location
**What goes wrong:** Checking `response["stop_reason"]` raises `KeyError`.
**Why it happens:** `stop_reason` is in the response body JSON, not the boto3 response dict. The boto3 response is `{"ResponseMetadata": ..., "body": StreamingBody}`.
**How to avoid:** Parse body first: `response_body = json.loads(response["body"].read())`, then `response_body["stop_reason"]`.
**Warning signs:** `KeyError: 'stop_reason'` immediately after `invoke_model()`.

## Code Examples

### Complete invoke() skeleton
```python
# Source: Pattern derived from ingestion-service/app/core/llm/claude/client.py + Python asyncio docs
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import boto3
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings

LOGGER = logging.getLogger(__name__)

_bedrock_client = None


class ClaudeClientError(Exception):
    def __init__(self, message: str, original_exc: Exception | None = None) -> None:
        super().__init__(message)
        self.original_exc = original_exc


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        settings = get_settings()
        _bedrock_client = boto3.client(
            service_name="bedrock-runtime",
            region_name=settings.aws_region,
            config=BotocoreConfig(
                read_timeout=300,
                connect_timeout=10,
                retries={"max_attempts": 0},
            ),
        )
    return _bedrock_client


async def invoke(prompt: str, system_prompt: Optional[str] = None) -> str:
    settings = get_settings()
    client = _get_bedrock_client()

    body: dict = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": settings.bedrock_max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt is not None:
        body["system"] = system_prompt

    def _call() -> dict:
        resp = client.invoke_model(
            modelId=settings.bedrock_model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        return json.loads(resp["body"].read())

    try:
        response_body = await asyncio.to_thread(_call)
    except (ClientError, BotoCoreError) as exc:
        raise ClaudeClientError(f"Bedrock call failed: {exc}", exc) from exc

    stop_reason = response_body.get("stop_reason")
    if stop_reason != "end_turn":
        LOGGER.warning(
            "Bedrock response stop_reason=%r (expected 'end_turn') — response may be truncated",
            stop_reason,
        )

    return response_body["content"][0]["text"]
```

### startup.py executor addition
```python
# In lifespan(), before yield — startup.py
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=50, thread_name_prefix="bedrock")
loop = asyncio.get_event_loop()
loop.set_default_executor(executor)
LOGGER.info("ThreadPoolExecutor configured: max_workers=50")
```

### Caller usage pattern (Phases 6 and 7)
```python
from app.core.llm.claude_client import invoke, ClaudeClientError
from app.core.llm.rate_limiter import get_rate_limiter

async def call_claude(prompt: str, system_prompt: str) -> str:
    async with get_rate_limiter().acquire():
        return await invoke(prompt, system_prompt)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `loop.run_in_executor(executor, fn)` | `asyncio.to_thread(fn)` | Python 3.9 | Cleaner, no explicit loop reference needed |
| Class-based client with context manager | Module-level functions with singletons | Phase 4 decision | ~60 lines vs 400+ lines |
| RPM windowing + concurrency semaphore | Concurrency semaphore only | Phase 4 decision | Simpler; RPM limit enforced externally by AWS |

**Deprecated/outdated:**
- `loop.run_in_executor()`: Still works but `asyncio.to_thread()` is preferred in Python 3.9+. ingestion-service uses the old pattern — do not replicate it.
- Class-based `ClaudeClient` with `__aenter__`/`__aexit__`: Over-engineered for a single-model, no-config-per-call use case.

## Open Questions

1. **boto3 read timeout value**
   - What we know: ingestion-service uses 300s. Claude responses for large documents can be slow.
   - What's unclear: max expected response time for vdr-agent's 4096-token max — likely under 60s.
   - Recommendation: Use 300s as a safe default matching ingestion-service. Can be reduced in Phase 6/7 tuning.

2. **`_bedrock_client` reset on test isolation**
   - What we know: Module-level singletons persist across test functions in the same pytest session.
   - What's unclear: Whether Phase 4 tests will mock boto3 at the module level or inject a fake client.
   - Recommendation: Keep `_bedrock_client` resettable by exposing a `_reset_for_testing()` function, or mock `boto3.client` at the boto3 module level in tests.

## Sources

### Primary (HIGH confidence)
- Ingestion-service source read directly: `ingestion-service/app/core/llm/rate_limiter.py` — lazy init pattern, singleton, acquire context manager
- Ingestion-service source read directly: `ingestion-service/app/core/llm/claude/client.py` — boto3 call structure, `anthropic_version`, response parsing, exception mapping
- vdr-agent source read directly: `vdr-agent/app/config/__init__.py` — existing Settings fields and env_prefix
- vdr-agent source read directly: `vdr-agent/app/startup.py` — lifespan structure for executor insertion
- CONTEXT.md — all locked decisions (primary authority for this phase)

### Secondary (MEDIUM confidence)
- Python 3.9 stdlib: `asyncio.to_thread()` introduced in Python 3.9 — verified by ingestion-service CLAUDE.md referencing Python 3.12 and STATE.md confirming vdr-agent is Python 3.9
- AWS Bedrock `anthropic_version` requirement — confirmed in ingestion-service client line 299 and consistent with AWS Bedrock API documentation

### Tertiary (LOW confidence)
- Thread pool sizing rationale (50 workers) — validated by ingestion-service TEMP-007 fix (200 threads for 5 concurrent activities * 40), scaled down proportionally for vdr-agent's 10 max concurrent Bedrock calls

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified from existing venv and pyproject.toml; all stdlib
- Architecture: HIGH — patterns copied/adapted directly from ingestion-service source + CONTEXT.md locked decisions
- Pitfalls: HIGH — pitfalls 1–4 are documented production bugs in ingestion-service (TEMP-007, CLAUDE.md); pitfalls 5–6 are verified from boto3 API structure

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (boto3 Bedrock API is stable; asyncio stdlib is stable)
