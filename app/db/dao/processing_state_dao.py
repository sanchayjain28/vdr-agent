from __future__ import annotations

import logging
from typing import List, Optional, Tuple
from uuid import UUID

from app.db.pool import DatabasePool
from app.db.records import ProcessingStateRecord

LOGGER = logging.getLogger(__name__)


class ProcessingStateDAO:
    """Data Access Object for vdr_agent.processing_state.

    Critical: claim_documents() uses SELECT FOR UPDATE SKIP LOCKED.
    The SELECT and UPDATE happen in the same transaction — never split into two calls.
    Connections are never held across Bedrock calls.
    """

    @staticmethod
    async def claim_documents(limit: int = 5) -> List[Tuple[UUID, UUID]]:
        """Atomically claim pending/failed documents for processing.

        Performs SELECT FOR UPDATE SKIP LOCKED followed by UPDATE to 'processing'
        in a single transaction. Returns list of (processing_state_id, document_id)
        tuples that the caller must process. On failure, caller must call
        update_status(ps_id, 'failed').

        The WHERE clause MUST use summary_status IN ('pending', 'failed') exactly —
        this matches the partial index idx_processing_state_pending_failed from V3 migration.
        """
        select_sql = """
            SELECT id, document_id
            FROM vdr_agent.processing_state
            WHERE summary_status IN ('pending', 'failed')
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        """
        update_sql = """
            UPDATE vdr_agent.processing_state
            SET summary_status = 'processing',
                processing_started_at = NOW(),
                updated_at = NOW()
            WHERE id = ANY(%s)
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(select_sql, (limit,))
                rows = await cur.fetchall()
                if not rows:
                    return []
                ids = [row["id"] for row in rows]
                await cur.execute(update_sql, (ids,))
            await conn.commit()

        claimed = [(row["id"], row["document_id"]) for row in rows]
        LOGGER.info("Claimed %d document(s) for processing", len(claimed))
        return claimed

    @staticmethod
    async def update_status(
        processing_state_id: UUID,
        status: str,
    ) -> None:
        """Update summary_status for a single processing_state row.

        Called after Bedrock processing completes (status='done') or fails (status='failed').
        This is intentionally a short, separate transaction — not the same connection
        used during claim_documents() or Bedrock calls.

        Valid statuses: 'pending', 'processing', 'done', 'failed'.
        """
        sql = """
            UPDATE vdr_agent.processing_state
            SET summary_status = %s,
                updated_at = NOW()
            WHERE id = %s
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (status, processing_state_id))
            await conn.commit()
        LOGGER.debug("Updated processing_state id=%s status=%s", processing_state_id, status)

    @staticmethod
    async def reset_stale_claims(threshold_minutes: int = 30) -> int:
        """Reset stale 'processing' rows back to 'pending'.

        Called at the start of each poll cycle. Detects rows where
        processing_started_at is older than threshold_minutes and no worker
        has completed them (likely crashed or was killed). Resets to 'pending'
        so they can be re-claimed on the next cycle.

        Returns count of rows reset.
        """
        sql = """
            UPDATE vdr_agent.processing_state
            SET summary_status = 'pending',
                processing_started_at = NULL,
                updated_at = NOW()
            WHERE summary_status = 'processing'
              AND processing_started_at < NOW() - INTERVAL '%s minutes'
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (threshold_minutes,))
                reset_count = cur.rowcount
            await conn.commit()
        if reset_count > 0:
            LOGGER.warning(
                "Reset %d stale processing_state row(s) (threshold=%d min)",
                reset_count, threshold_minutes,
            )
        return reset_count

    @staticmethod
    async def get_by_document(document_id: UUID) -> Optional[ProcessingStateRecord]:
        """Fetch processing state for a document. Returns None if no row exists."""
        sql = """
            SELECT id, document_id, summary_status, processing_started_at,
                   created_at, updated_at
            FROM vdr_agent.processing_state
            WHERE document_id = %s
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (document_id,))
                row = await cur.fetchone()
        if row is None:
            return None
        return ProcessingStateRecord.from_row(row)

    @staticmethod
    async def insert(document_id: UUID) -> ProcessingStateRecord:
        """Insert a new processing_state row in 'pending' status.

        Called when a new document is detected by the poller (Phase 5).
        Uses INSERT ... ON CONFLICT DO NOTHING to handle idempotent calls
        (document may already have a row if poller races with itself).
        """
        sql = """
            INSERT INTO vdr_agent.processing_state (document_id, summary_status)
            VALUES (%s, 'pending')
            ON CONFLICT (document_id) DO NOTHING
            RETURNING id, document_id, summary_status, processing_started_at,
                      created_at, updated_at
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (document_id,))
                row = await cur.fetchone()
            await conn.commit()
        if row is None:
            # Conflict — row already exists; fetch current state
            existing = await ProcessingStateDAO.get_by_document(document_id)
            LOGGER.debug("processing_state already exists for document_id=%s", document_id)
            return existing
        return ProcessingStateRecord.from_row(row)

    @staticmethod
    async def find_unregistered_documents(limit: int = 5) -> List[UUID]:
        """Find document IDs from ai_rag.documents not yet in vdr_agent.processing_state.

        Queries across schemas — works because search_path = vdr_agent, ai_rag, public
        is set on every pooled connection in pool.py configure().

        IMPORTANT: The ai_rag.documents column is `status` (not `embedding_status`).
        The value 'completed' means the full pipeline including embeddings has run.
        Verified from ingestion-service/migrations/flyway/V3__documents_and_embeddings.sql.

        Returns at most `limit` document IDs to bound the INSERT loop in the poller.
        """
        sql = """
            SELECT d.id
            FROM ai_rag.documents d
            WHERE d.status = 'completed'
              AND d.id NOT IN (
                  SELECT ps.document_id
                  FROM vdr_agent.processing_state ps
              )
            LIMIT %s
        """
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (limit,))
                rows = await cur.fetchall()
        return [row["id"] for row in rows]
