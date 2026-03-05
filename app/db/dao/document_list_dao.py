from __future__ import annotations

import logging
from typing import List
from uuid import UUID

from app.db.pool import DatabasePool
from app.db.records import DocumentListRecord

LOGGER = logging.getLogger(__name__)


class DocumentListDAO:

    @staticmethod
    async def list_by_project(project_id: UUID) -> List[DocumentListRecord]:
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        d.id,
                        d.file_name,
                        d.file_path,
                        d.file_type,
                        d.page_count,
                        COALESCE(ps.summary_status, 'pending') AS summary_status,
                        ds.summary_text,
                        COUNT(fr.id) FILTER (WHERE fr.status = 'done') AS fitment_done_count,
                        (
                            SELECT COUNT(*) FROM vdr_agent.topics t
                            WHERE t.project_id = d.project_id AND t.is_active = TRUE
                        ) AS fitment_total_count
                    FROM ai_rag.documents d
                    LEFT JOIN vdr_agent.processing_state ps ON ps.document_id = d.id
                    LEFT JOIN vdr_agent.document_summaries ds ON ds.document_id = d.id
                    LEFT JOIN vdr_agent.fitment_results fr ON fr.document_id = d.id
                    WHERE d.project_id = %s
                    GROUP BY d.id, d.file_name, d.file_path, d.file_type, d.page_count, ps.summary_status, ds.summary_text
                    ORDER BY d.created_at DESC
                    """,
                    (project_id,),
                )
                rows = await cur.fetchall()
        return [DocumentListRecord.from_row(r) for r in rows]
