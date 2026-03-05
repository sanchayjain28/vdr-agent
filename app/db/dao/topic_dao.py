from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from app.db.pool import DatabasePool
from app.db.records import TopicRecord

LOGGER = logging.getLogger(__name__)


class TopicDAO:
    """Data Access Object for vdr_agent.topics.

    All methods are static async — no instance creation needed.
    Each method opens and closes its own connection from DatabasePool.
    Called directly from route handlers and polling loop (no FastAPI Depends injection).
    """

    @staticmethod
    async def insert(
        project_id: UUID,
        name: str,
        instruction: str,
        is_active: bool = True,
    ) -> TopicRecord:
        """Insert a new ESG topic and return the created record."""
        sql = """
            INSERT INTO vdr_agent.topics (project_id, name, instruction, is_active)
            VALUES (%s, %s, %s, %s)
            RETURNING id, project_id, name, instruction, is_active, created_at, updated_at
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (project_id, name, instruction, is_active))
                row = await cur.fetchone()
            await conn.commit()
        LOGGER.debug("Inserted topic id=%s project_id=%s name=%r", row["id"], project_id, name)
        return TopicRecord.from_row(row)

    @staticmethod
    async def list_by_project(
        project_id: UUID,
        active_only: bool = True,
    ) -> List[TopicRecord]:
        """Return topics for a project ordered by created_at ascending.

        Args:
            project_id: Project UUID to filter by.
            active_only: If True (default), only return active topics.
        """
        sql = """
            SELECT id, project_id, name, instruction, is_active, created_at, updated_at
            FROM vdr_agent.topics
            WHERE project_id = %s
        """
        params: list = [project_id]
        if active_only:
            sql += " AND is_active = TRUE"
        sql += " ORDER BY created_at ASC"
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                rows = await cur.fetchall()
        return [TopicRecord.from_row(row) for row in rows]

    @staticmethod
    async def bulk_insert(
        project_id: UUID,
        topics: list[dict],
    ) -> List[TopicRecord]:
        """Insert multiple topics in one transaction. Returns all created records.

        Args:
            project_id: Project UUID for all topics.
            topics: List of dicts with 'name' and 'instruction' keys.

        Raises:
            psycopg.errors.UniqueViolation if any name conflicts with an existing active topic.
            The entire transaction is rolled back — no partial inserts.
        """
        sql = """
            INSERT INTO vdr_agent.topics (project_id, name, instruction, is_active)
            VALUES (%s, %s, %s, TRUE)
            RETURNING id, project_id, name, instruction, is_active, created_at, updated_at
        """
        records: list[TopicRecord] = []
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                for topic in topics:
                    await cur.execute(sql, (project_id, topic["name"], topic["instruction"]))
                    row = await cur.fetchone()
                    records.append(TopicRecord.from_row(row))
            await conn.commit()
        LOGGER.debug("Bulk inserted %d topics for project_id=%s", len(records), project_id)
        return records

    @staticmethod
    async def update(
        topic_id: UUID,
        name: Optional[str] = None,
        instruction: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[TopicRecord]:
        """Update a topic's fields. Returns updated record or None if not found.

        Only updates fields that are explicitly passed (not None).
        """
        sets = []
        params: list = []
        if name is not None:
            sets.append("name = %s")
            params.append(name)
        if instruction is not None:
            sets.append("instruction = %s")
            params.append(instruction)
        if is_active is not None:
            sets.append("is_active = %s")
            params.append(is_active)
        if not sets:
            # Nothing to update — fetch and return current state
            return await TopicDAO.get_by_id(topic_id)

        sql = f"""
            UPDATE vdr_agent.topics
            SET {', '.join(sets)}, updated_at = NOW()
            WHERE id = %s
            RETURNING id, project_id, name, instruction, is_active, created_at, updated_at
        """
        params.append(topic_id)
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                row = await cur.fetchone()
            await conn.commit()
        if row is None:
            return None
        return TopicRecord.from_row(row)

    @staticmethod
    async def delete(topic_id: UUID) -> bool:
        """Delete a topic. Returns True if a row was deleted, False if not found."""
        sql = "DELETE FROM vdr_agent.topics WHERE id = %s"
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (topic_id,))
                deleted = cur.rowcount
            await conn.commit()
        return deleted > 0

    @staticmethod
    async def get_by_id(topic_id: UUID) -> Optional[TopicRecord]:
        """Fetch a single topic by primary key. Returns None if not found."""
        sql = """
            SELECT id, project_id, name, instruction, is_active, created_at, updated_at
            FROM vdr_agent.topics
            WHERE id = %s
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (topic_id,))
                row = await cur.fetchone()
        if row is None:
            return None
        return TopicRecord.from_row(row)
