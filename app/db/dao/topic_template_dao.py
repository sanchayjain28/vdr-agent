from __future__ import annotations

import logging
from typing import List

from app.db.pool import DatabasePool
from app.db.records import TopicTemplateRecord

LOGGER = logging.getLogger(__name__)


class TopicTemplateDAO:
    """Data Access Object for vdr_agent.topic_templates.

    Read-only — the table is seeded by V11 migration and never mutated at runtime.
    """

    @staticmethod
    async def list_all() -> List[TopicTemplateRecord]:
        """Return all 19 topic templates ordered by id ascending."""
        sql = """
            SELECT id, name, instruction
            FROM vdr_agent.topic_templates
            ORDER BY id ASC
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
        LOGGER.debug("Fetched %d topic templates", len(rows))
        return [TopicTemplateRecord.from_row(row) for row in rows]
