from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from app.db.pool import DatabasePool
from app.db.records import DocumentSummaryRecord

LOGGER = logging.getLogger(__name__)


class DocumentSummaryDAO:
    """Data Access Object for vdr_agent.document_summaries.

    Called by Phase 6 (AI Summary Generation) after Bedrock returns the combined
    document summary. The connection is opened only to execute the upsert and commit
    — never held open while waiting for Bedrock.
    """

    @staticmethod
    async def upsert(document_id: UUID, summary_text: str) -> DocumentSummaryRecord:
        """Insert or update the AI summary for a document.

        Uses ON CONFLICT (document_id) DO UPDATE so re-runs overwrite the
        previous summary rather than failing with a duplicate-key error.
        Commits and releases the connection before returning.
        """
        sql = """
            INSERT INTO vdr_agent.document_summaries (document_id, summary_text)
            VALUES (%s, %s)
            ON CONFLICT (document_id) DO UPDATE
                SET summary_text = EXCLUDED.summary_text,
                    updated_at = NOW()
            RETURNING id, document_id, summary_text, created_at, updated_at
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (document_id, summary_text))
                row = await cur.fetchone()
            await conn.commit()
        LOGGER.debug("Upserted document_summary for document_id=%s", document_id)
        return DocumentSummaryRecord.from_row(row)

    @staticmethod
    async def get_by_document(document_id: UUID) -> Optional[DocumentSummaryRecord]:
        """Fetch the summary for a document. Returns None if not yet generated."""
        sql = """
            SELECT id, document_id, summary_text, created_at, updated_at
            FROM vdr_agent.document_summaries
            WHERE document_id = %s
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (document_id,))
                row = await cur.fetchone()
        if row is None:
            return None
        return DocumentSummaryRecord.from_row(row)
