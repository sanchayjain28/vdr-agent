from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db.pool import DatabasePool
from app.worker.poller import run_poller

LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager.

    Startup: validate settings, initialize DB pool, start document poller.
    Shutdown: cancel poller, close DB connection pool cleanly.
    """
    settings = get_settings()
    LOGGER.info("vdr-agent starting env=%s log_level=%s", settings.env, settings.log_level)

    executor = ThreadPoolExecutor(max_workers=50, thread_name_prefix="bedrock")
    loop = asyncio.get_event_loop()
    loop.set_default_executor(executor)
    LOGGER.info("ThreadPoolExecutor configured: max_workers=50 thread_name_prefix=bedrock")

    await DatabasePool.initialize(
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        min_size=2,
        max_size=10,
    )

    # Start document poller as a background asyncio task
    poller_task = asyncio.create_task(run_poller())
    poller_task.add_done_callback(
        lambda t: LOGGER.info(
            "poller task exited: %s",
            t.exception() if not t.cancelled() else "cancelled",
        )
    )

    yield

    # Shutdown: cancel poller first, then close DB pool
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    await DatabasePool.close()
    LOGGER.info("vdr-agent shutdown complete")
