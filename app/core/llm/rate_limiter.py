from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

LOGGER = logging.getLogger(__name__)

_rate_limiter: Optional["GlobalRateLimiter"] = None


@dataclass
class GlobalRateLimiter:
    max_concurrent: int = 10

    _semaphore: Optional[asyncio.Semaphore] = field(default=None, init=False, repr=False)
    _bound_loop: Optional[asyncio.AbstractEventLoop] = field(default=None, init=False, repr=False)

    def _ensure_async_primitives(self) -> None:
        """Lazily bind the semaphore to the running event loop.

        Called inside acquire() — guarantees semaphore is created in the correct loop.
        Handles test environments where each test may spin up a fresh event loop.
        """
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # No running loop — semaphore will be created when one exists
        if self._bound_loop is not current_loop or self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
            self._bound_loop = current_loop

    @asynccontextmanager
    async def acquire(self):
        """Async context manager that gates on the concurrency semaphore."""
        self._ensure_async_primitives()
        await self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()


def get_rate_limiter() -> GlobalRateLimiter:
    """Return the module-level GlobalRateLimiter singleton.

    Lazily reads settings.bedrock_max_concurrent on first call.
    Safe to call from any async context — settings are initialised well before
    the first invoke() call (lifespan startup runs first).
    """
    global _rate_limiter
    if _rate_limiter is None:
        from app.config import get_settings
        settings = get_settings()
        _rate_limiter = GlobalRateLimiter(max_concurrent=settings.bedrock_max_concurrent)
        LOGGER.info("GlobalRateLimiter initialised: max_concurrent=%d", settings.bedrock_max_concurrent)
    return _rate_limiter
