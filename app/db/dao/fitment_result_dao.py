from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from app.db.pool import DatabasePool
from app.db.records import FitmentResultRecord

LOGGER = logging.getLogger(__name__)


class FitmentResultDAO:
    """Data Access Object for vdr_agent.fitment_results.

    Called by Phase 7 (Fitment Generation) after Bedrock returns each topic's
    fitment evaluation. Each upsert is a short transaction — connection released
    before any further Bedrock calls. Safe for re-runs via ON CONFLICT DO UPDATE.
    """

    @staticmethod
    async def upsert(
        document_id: UUID,
        topic_id: UUID,
        reasoning: Optional[str],
        status: str = "done",
    ) -> FitmentResultRecord:
        """Insert or update a fitment result for a (document, topic) pair.

        Uses ON CONFLICT ON CONSTRAINT fitment_results_doc_topic_unique — the exact
        constraint name from V5 migration. This is required; do NOT use
        ON CONFLICT (document_id, topic_id) without the constraint name.

        status values: 'pending' | 'done' | 'failed'
        reasoning: TEXT or None (stored as NULL if Bedrock failed)
        """
        sql = """
            INSERT INTO vdr_agent.fitment_results (document_id, topic_id, reasoning, status)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT ON CONSTRAINT fitment_results_doc_topic_unique DO UPDATE
                SET reasoning = EXCLUDED.reasoning,
                    status = EXCLUDED.status,
                    updated_at = NOW()
            RETURNING id, document_id, topic_id, reasoning, status, created_at, updated_at
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (document_id, topic_id, reasoning, status))
                row = await cur.fetchone()
            await conn.commit()
        LOGGER.debug(
            "Upserted fitment_result document_id=%s topic_id=%s status=%s",
            document_id, topic_id, status,
        )
        return FitmentResultRecord.from_row(row)

    @staticmethod
    async def list_by_document(document_id: UUID) -> List[FitmentResultRecord]:
        """Return all fitment results for a document ordered by topic_id.

        Called by Phase 9 (Results API) to return fitment data to the frontend.
        """
        sql = """
            SELECT id, document_id, topic_id, reasoning, status, created_at, updated_at
            FROM vdr_agent.fitment_results
            WHERE document_id = %s
            ORDER BY topic_id ASC
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (document_id,))
                rows = await cur.fetchall()
        return [FitmentResultRecord.from_row(row) for row in rows]

    @staticmethod
    async def get_by_document_and_topic(
        document_id: UUID, topic_id: UUID
    ) -> Optional[FitmentResultRecord]:
        """Fetch a single fitment result. Returns None if not yet evaluated."""
        sql = """
            SELECT id, document_id, topic_id, reasoning, status, created_at, updated_at
            FROM vdr_agent.fitment_results
            WHERE document_id = %s AND topic_id = %s
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (document_id, topic_id))
                row = await cur.fetchone()
        if row is None:
            return None
        return FitmentResultRecord.from_row(row)
