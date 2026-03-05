from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.config import get_settings
from app.core.llm.claude_client import ClaudeClientError, invoke
from app.core.llm.rate_limiter import get_rate_limiter
from app.db.dao.document_summary_dao import DocumentSummaryDAO
from app.db.dao.processing_state_dao import ProcessingStateDAO
from app.db.pool import DatabasePool

LOGGER = logging.getLogger(__name__)

SECTION_SYSTEM_PROMPT = (
    "You are summarising a section of an ESG (Environmental, Social, Governance) "
    "corporate disclosure document. Extract the key findings, metrics, data points, "
    "and topics discussed in this section. Be concise and factual."
)

COMBINE_SYSTEM_PROMPT = (
    "You are writing a document summary for an ESG disclosure. Below are summaries "
    "of each section of the document. Combine them into a single coherent summary "
    "covering: (1) the document's main purpose and scope, (2) key ESG topics and "
    "metrics mentioned, (3) notable findings or data points. "
    "Write in clear, factual prose. 2–4 paragraphs."
)


async def _summarise_section(section_chunks: list[str], section_index: int) -> str:
    """Summarise one section under the global rate limiter.

    Called concurrently via asyncio.gather — must NOT hold any DB connection.
    Each call acquires one rate limiter slot, invokes Claude, releases on exit.
    """
    user_message = "\n\n".join(section_chunks)
    async with get_rate_limiter().acquire():
        result = await invoke(user_message, system_prompt=SECTION_SYSTEM_PROMPT)
    LOGGER.debug(
        "Section %d summary complete (%d chars)", section_index, len(result)
    )
    return result


async def process_document(processing_state_id: UUID, document_id: UUID) -> None:
    """Generate an AI summary for one document and persist it.

    Three-phase pipeline:
      1. Fetch all embedding chunks (short-lived DB connection — closes before AI calls).
      2. Partition chunks into sections; fire parallel section summaries via asyncio.gather.
      3. Combine section summaries into a final document summary; persist to DB.

    On any failure: sets summary_status = 'failed'. No retry (v1 decision).
    Signature is fixed — poller.py passes (processing_state_id, document_id) unchanged.
    """
    # ── Phase 1: Fetch chunks ────────────────────────────────────────────────
    # Short-lived connection — must be closed before any Bedrock call to avoid
    # exhausting the DB pool (max_size=10) during multi-second AI waits.
    sql = """
        SELECT content, chunk_index
        FROM ai_rag.embeddings
        WHERE document_id = %s
        ORDER BY chunk_index
    """
    try:
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (document_id,))
                rows = await cur.fetchall()
    except Exception:
        LOGGER.exception(
            "Failed to fetch chunks for doc_id=%s ps_id=%s",
            document_id,
            processing_state_id,
        )
        await ProcessingStateDAO.update_status(processing_state_id, "failed")
        return

    chunks = [row["content"] for row in rows]

    if not chunks:
        # No embeddings — embeddings pipeline may have failed without flagging the doc.
        # Marking 'failed' prevents Phase 7 fitment from running against an empty summary.
        LOGGER.warning(
            "No embedding chunks found for doc_id=%s — marking failed", document_id
        )
        await ProcessingStateDAO.update_status(processing_state_id, "failed")
        return

    # ── Phase 2 + 3: AI calls — no DB connection held ───────────────────────
    try:
        section_size = get_settings().summary_section_size
        sections = [
            chunks[i : i + section_size]
            for i in range(0, len(chunks), section_size)
        ]

        LOGGER.info(
            "Starting summary: doc_id=%s chunks=%d sections=%d",
            document_id,
            len(chunks),
            len(sections),
        )

        # Parallel section summaries — return_exceptions=True ensures all tasks
        # run to completion so rate limiter semaphore slots are cleanly released.
        section_tasks = [
            _summarise_section(section, idx)
            for idx, section in enumerate(sections)
        ]
        results = await asyncio.gather(*section_tasks, return_exceptions=True)

        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            for err in errors:
                LOGGER.error(
                    "Section summary failed for doc_id=%s: %s", document_id, err
                )
            raise errors[0]

        section_summaries: list[str] = results  # type: ignore[assignment]

        # Combine section summaries into a final document summary
        numbered = "\n\n".join(
            f"Section {i + 1}:\n{s}" for i, s in enumerate(section_summaries)
        )
        async with get_rate_limiter().acquire():
            final_summary = await invoke(numbered, system_prompt=COMBINE_SYSTEM_PROMPT)

        # ── Phase 4: Persist results (new short-lived DB connections) ────────
        await DocumentSummaryDAO.upsert(document_id, final_summary)
        await ProcessingStateDAO.update_status(processing_state_id, "done")

        LOGGER.info(
            "Summary complete: doc_id=%s ps_id=%s sections=%d summary_chars=%d",
            document_id,
            processing_state_id,
            len(sections),
            len(final_summary),
        )

    except Exception:
        LOGGER.exception(
            "process_document failed: ps_id=%s doc_id=%s",
            processing_state_id,
            document_id,
        )
        await ProcessingStateDAO.update_status(processing_state_id, "failed")
