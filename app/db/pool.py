from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

LOGGER = logging.getLogger(__name__)

SEARCH_PATH = "vdr_agent, ai_rag, public"


class DatabasePool:
    """Singleton AsyncConnectionPool for vdr-agent.

    Usage:
        await DatabasePool.initialize(host=..., port=..., database=..., user=..., password=...)
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
            await conn.commit()
        await DatabasePool.close()
    """

    _pool: Optional[AsyncConnectionPool] = None

    @classmethod
    async def initialize(
        cls,
        host: str,
        port: int,
        database: str,
        user: str,
        password: Optional[str] = None,
        min_size: int = 2,
        max_size: int = 10,
        timeout: float = 30.0,
    ) -> None:
        if cls._pool is not None:
            LOGGER.warning("DatabasePool already initialized — skipping")
            return

        conninfo = (
            f"host={host} port={port} dbname={database} "
            f"user={user}"
            + (f" password={password}" if password else "")
            + f" connect_timeout={int(timeout)}"
        )

        LOGGER.info(
            "Initializing DatabasePool: host=%s db=%s pool_size=%s-%s",
            host, database, min_size, max_size,
        )

        async def configure(conn) -> None:
            await conn.execute(f"SET search_path TO {SEARCH_PATH}")
            await conn.commit()

        pool = AsyncConnectionPool(
            conninfo=conninfo,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            kwargs={"row_factory": dict_row},
            configure=configure,
            open=False,
        )
        await pool.open()
        cls._pool = pool
        LOGGER.info("DatabasePool initialized successfully (search_path=%s)", SEARCH_PATH)

    @classmethod
    async def close(cls) -> None:
        if cls._pool is None:
            LOGGER.warning("DatabasePool.close() called but pool not initialized")
            return
        LOGGER.info("Closing DatabasePool")
        await cls._pool.close()
        cls._pool = None
        LOGGER.info("DatabasePool closed")

    @classmethod
    @asynccontextmanager
    async def connection(cls):
        """Yield a live AsyncConnection from the pool.

        Each DAO method must open and close its own connection.
        Do NOT hold a connection across awaits that call Bedrock or other slow I/O.
        """
        if cls._pool is None:
            raise RuntimeError(
                "DatabasePool not initialized. Call await DatabasePool.initialize() at startup."
            )
        async with cls._pool.connection() as conn:
            yield conn

    @classmethod
    def is_initialized(cls) -> bool:
        return cls._pool is not None
