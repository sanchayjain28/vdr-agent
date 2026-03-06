from __future__ import annotations

import logging
from typing import List, Optional, Tuple
from uuid import UUID

from psycopg.types.json import Json

from app.db.pool import DatabasePool
from app.db.records import DocumentScopeAssignmentRecord, ScopeAssignmentDetailRecord

LOGGER = logging.getLogger(__name__)


class DocumentScopeAssignmentDAO:
    """Data Access Object for vdr_agent.document_scope_assignments.

    Called by Phase 13 (scope categorisation pipeline) after LLM response to
    persist assignments via bulk_upsert. Called by Phase 14 (API) via
    list_by_topic and list_by_document.

    All upserts use ON CONFLICT ON CONSTRAINT doc_scope_assignments_doc_topic_unique
    — the exact constraint name from V9 migration. Safe for re-runs.
    """

    _UPSERT_SQL = """
        INSERT INTO vdr_agent.document_scope_assignments
            (document_id, topic_id, confidence, justification, needs_review, review_reason, raw_response)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT ON CONSTRAINT doc_scope_assignments_doc_topic_unique DO UPDATE
            SET confidence    = EXCLUDED.confidence,
                justification = EXCLUDED.justification,
                needs_review  = EXCLUDED.needs_review,
                review_reason = EXCLUDED.review_reason,
                raw_response  = EXCLUDED.raw_response,
                updated_at    = NOW()
        RETURNING id, document_id, topic_id, confidence, justification,
                  needs_review, review_reason, raw_response, created_at, updated_at
    """

    @staticmethod
    async def upsert(
        document_id: UUID,
        topic_id: UUID,
        confidence: str,
        justification: Optional[str],
        needs_review: bool,
        review_reason: Optional[str],
        raw_response: Optional[dict],
    ) -> DocumentScopeAssignmentRecord:
        """Insert or update a scope assignment for a (document, topic) pair.

        Uses ON CONFLICT ON CONSTRAINT doc_scope_assignments_doc_topic_unique.
        raw_response is wrapped with psycopg Json adapter so the dict is stored
        as JSONB. Pass None to store NULL.

        confidence values: 'HIGH' | 'MEDIUM' | 'LOW'
        """
        params = (
            document_id,
            topic_id,
            confidence,
            justification,
            needs_review,
            review_reason,
            Json(raw_response) if raw_response is not None else None,
        )
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(DocumentScopeAssignmentDAO._UPSERT_SQL, params)
                row = await cur.fetchone()
            await conn.commit()
        LOGGER.debug(
            "Upserted scope_assignment document_id=%s topic_id=%s confidence=%s needs_review=%s",
            document_id,
            topic_id,
            confidence,
            needs_review,
        )
        return DocumentScopeAssignmentRecord.from_row(row)

    @staticmethod
    async def bulk_upsert(
        assignments: List[dict],
    ) -> List[DocumentScopeAssignmentRecord]:
        """Upsert multiple scope assignments from one LLM response in a single transaction.

        Each dict in assignments must have keys:
            document_id, topic_id, confidence, justification, needs_review,
            review_reason, raw_response

        All rows are written inside one connection+transaction for atomicity.
        Returns the persisted records in the same order as the input list.
        """
        results: List[DocumentScopeAssignmentRecord] = []
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                for a in assignments:
                    raw = a.get("raw_response")
                    params = (
                        a["document_id"],
                        a["topic_id"],
                        a["confidence"],
                        a.get("justification"),
                        a["needs_review"],
                        a.get("review_reason"),
                        Json(raw) if raw is not None else None,
                    )
                    await cur.execute(DocumentScopeAssignmentDAO._UPSERT_SQL, params)
                    row = await cur.fetchone()
                    results.append(DocumentScopeAssignmentRecord.from_row(row))
            await conn.commit()
        LOGGER.debug(
            "bulk_upsert persisted %d scope_assignments document_id=%s",
            len(results),
            assignments[0]["document_id"] if assignments else None,
        )
        return results

    @staticmethod
    async def list_by_document(document_id: UUID) -> List[DocumentScopeAssignmentRecord]:
        """Return all scope assignments for a document ordered by creation time.

        Called by Phase 14 (API) to return per-document assignment data.
        """
        sql = """
            SELECT id, document_id, topic_id, confidence, justification,
                   needs_review, review_reason, raw_response, created_at, updated_at
            FROM vdr_agent.document_scope_assignments
            WHERE document_id = %s
            ORDER BY created_at ASC
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (document_id,))
                rows = await cur.fetchall()
        return [DocumentScopeAssignmentRecord.from_row(row) for row in rows]

    @staticmethod
    async def list_by_topic(
        topic_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[ScopeAssignmentDetailRecord], int]:
        """Return paginated scope assignments for a topic with file metadata and summary text.

        Cross-schema LEFT JOIN (same pattern as DocumentListDAO):
          - ai_rag.documents for file_name, file_path, file_type
          - vdr_agent.document_summaries for summary_text (LEFT JOIN — may be NULL)

        Called by Phase 14 (API) to populate the ScopeDetails topic panel.
        Ordered by file_name for stable, human-readable listing.

        Returns:
            (records, total_count) tuple — total_count is the unpaged count.
        """
        count_sql = """
            SELECT COUNT(*)
            FROM vdr_agent.document_scope_assignments
            WHERE topic_id = %s
        """
        select_sql = """
            SELECT
                d.id          AS document_id,
                d.file_name,
                d.file_path,
                d.file_type,
                ds.summary_text,
                dsa.confidence,
                dsa.justification,
                dsa.needs_review,
                dsa.created_at
            FROM vdr_agent.document_scope_assignments dsa
            JOIN ai_rag.documents d ON d.id = dsa.document_id
            LEFT JOIN vdr_agent.document_summaries ds ON ds.document_id = dsa.document_id
            WHERE dsa.topic_id = %s
            ORDER BY d.file_name ASC
            LIMIT %s OFFSET %s
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(count_sql, (topic_id,))
                count_row = await cur.fetchone()
                total_count = count_row["count"] if count_row else 0
                await cur.execute(select_sql, (topic_id, limit, offset))
                rows = await cur.fetchall()
        return [ScopeAssignmentDetailRecord.from_row(row) for row in rows], total_count

    @staticmethod
    async def delete_by_document(document_id: UUID) -> int:
        """Delete all scope assignments for a document.

        Returns the number of rows deleted (cur.rowcount).
        Called when a document is re-ingested or removed to keep assignments
        consistent with active document state.
        """
        sql = """
            DELETE FROM vdr_agent.document_scope_assignments
            WHERE document_id = %s
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (document_id,))
                deleted = cur.rowcount
            await conn.commit()
        LOGGER.debug(
            "Deleted %d scope_assignments for document_id=%s",
            deleted,
            document_id,
        )
        return deleted
