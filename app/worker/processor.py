from __future__ import annotations

import asyncio
import json
import logging
from typing import List
from uuid import UUID

from app.config import get_settings
from app.core.llm.claude_client import ClaudeClientError, _get_bedrock_client, invoke
from app.core.llm.rate_limiter import get_rate_limiter
from app.db.dao.document_summary_dao import DocumentSummaryDAO
from app.db.dao.fitment_result_dao import FitmentResultDAO
from app.db.dao.processing_state_dao import ProcessingStateDAO
from app.db.dao.topic_dao import TopicDAO
from app.db.pool import DatabasePool
from app.db.records import TopicRecord

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

FITMENT_SYSTEM_PROMPT = (
    "You are an ESG analyst evaluating whether a corporate disclosure document "
    "contains meaningful information about a specific ESG topic. "
    "Review the document summary and the most relevant sections provided. "
    "Assess whether the document addresses this topic in a substantive way. "
    "Write a concise paragraph (3-5 sentences) explaining your finding — "
    "what the document says about this topic, or why it does not address it."
)


def _embed_query_sync(query_text: str, bedrock_client, model_id: str) -> list[float]:
    """Embed a single topic query string using Cohere on Bedrock.

    Uses input_type='search_query' — distinct from 'search_document' used
    by ingestion-service when storing chunks. This distinction is intentional
    and required for correct cosine similarity ordering.

    Run via asyncio.to_thread() — never call directly from an async context.
    """
    payload = {
        "texts": [query_text],
        "input_type": "search_query",  # Cohere: query vs document — do NOT use 'search_document'
        "embedding_types": ["float"],
    }
    response = bedrock_client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(payload),
    )
    body = json.loads(response["body"].read())
    return body["embeddings"]["float"][0]  # 1024-dim float list


async def _evaluate_topic(
    document_id: UUID,
    topic: TopicRecord,
    summary_text: str,
    bedrock_client,
    embedding_model: str,
) -> None:
    """Evaluate one topic under the global rate limiter.

    Called concurrently via asyncio.gather — must NOT hold any DB connection
    during Bedrock calls. Connection discipline:
      1. Embed topic query (asyncio.to_thread — no DB connection held)
      2. Fetch top-5 chunks (short-lived connection, released before invoke)
      3. Invoke Claude for fitment reasoning (rate-limited)
      4. Upsert result to fitment_results (short-lived connection)

    On any failure: upserts status='failed', reasoning=None.
    Other topics continue unaffected — this coroutine never re-raises.
    """
    try:
        query_text = f"{topic.name}: {topic.instruction}"

        # Step 1: Embed topic query — sync boto3 call, run in thread
        query_vector = await asyncio.to_thread(
            _embed_query_sync, query_text, bedrock_client, embedding_model
        )

        # Step 2: Fetch top-5 most relevant chunks — short-lived connection
        # released before any Bedrock call to avoid pool exhaustion
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT content
                    FROM ai_rag.embeddings
                    WHERE document_id = %s
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT 5
                    """,
                    (document_id, query_vector),
                )
                rows = await cur.fetchall()
        top_chunks = [row["content"] for row in rows]

        # Fallback: if pgvector returns no results (all embeddings NULL),
        # fetch first 5 chunks by chunk_index order
        if not top_chunks:
            LOGGER.warning(
                "No vector-indexed chunks for doc_id=%s topic=%r — falling back to first-5 chunks",
                document_id, topic.name,
            )
            async with DatabasePool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT content
                        FROM ai_rag.embeddings
                        WHERE document_id = %s
                        ORDER BY chunk_index
                        LIMIT 5
                        """,
                        (document_id,),
                    )
                    rows = await cur.fetchall()
            top_chunks = [row["content"] for row in rows]

        # Step 3: Build fitment prompt and invoke Claude (rate-limited)
        chunks_text = "\n\n".join(
            f"Chunk {i + 1}:\n{c}" for i, c in enumerate(top_chunks)
        )
        user_message = (
            f"## Document Summary\n{summary_text}\n\n"
            f"## Relevant Sections\n{chunks_text}\n\n"
            f"## Topic to Evaluate\n{topic.instruction}"
        )

        async with get_rate_limiter().acquire():
            reasoning = await invoke(user_message, system_prompt=FITMENT_SYSTEM_PROMPT)

        # Step 4: Persist result
        await FitmentResultDAO.upsert(document_id, topic.id, reasoning, status="done")
        LOGGER.debug(
            "Fitment complete: doc_id=%s topic=%r chars=%d",
            document_id, topic.name, len(reasoning),
        )

    except BaseException as exc:
        LOGGER.error(
            "Fitment failed: doc_id=%s topic=%r error=%s",
            document_id, topic.name, exc,
        )
        await FitmentResultDAO.upsert(document_id, topic.id, None, status="failed")


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
    """Generate an AI summary for one document, then run fitment for all active topics.

    Pipeline:
      Re-run safety: if summary already exists, skip to fitment.
      Else:
        Phase 1. Fetch all embedding chunks (short-lived DB connection).
        Phase 2+3. Parallel section summaries -> combine -> final_summary.
        Phase 4. Persist summary; set processing_state = 'done'.
      Phase 7. Fitment generation for all active topics (inside outer try).

    On summary pipeline failure: sets summary_status = 'failed' and returns.
    Phase 7 does NOT touch processing_state — it only writes to fitment_results.
    Signature is fixed — poller.py passes (processing_state_id, document_id) unchanged.
    """
    # ── Re-run safety: skip summary if already generated ────────────────────
    # If document_summaries already has a row, jump directly to fitment.
    # Prevents re-generating summaries when poller re-claims a crashed document.
    try:
        existing_summary = await DocumentSummaryDAO.get_by_document(document_id)
    except Exception:
        LOGGER.exception(
            "Failed to check existing summary for doc_id=%s", document_id
        )
        existing_summary = None

    if existing_summary is not None:
        LOGGER.info(
            "Summary already exists for doc_id=%s — skipping to fitment", document_id
        )
        final_summary = existing_summary.summary_text
        # Jump directly to the fitment block below — skip Phase 1-4 entirely.
    else:
        # ── Phase 1: Fetch chunks ────────────────────────────────────────────
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
            LOGGER.warning(
                "No embedding chunks found for doc_id=%s — marking failed", document_id
            )
            await ProcessingStateDAO.update_status(processing_state_id, "failed")
            return

        # ── Phase 2 + 3: AI calls — no DB connection held ───────────────────
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

            numbered = "\n\n".join(
                f"Section {i + 1}:\n{s}" for i, s in enumerate(section_summaries)
            )
            async with get_rate_limiter().acquire():
                final_summary = await invoke(numbered, system_prompt=COMBINE_SYSTEM_PROMPT)

            # ── Phase 4: Persist results (new short-lived DB connections) ────
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
            return  # Do not run fitment if summary generation failed

    # ── Phase 7: Fitment Generation ──────────────────────────────────────────
    # Runs whether summary was freshly generated (else branch) or already existed
    # (if branch). final_summary is set in both branches above.
    # Phase 7 does NOT update processing_state — summary_status remains 'done'
    # (set by Phase 6). Only fitment_results rows are written here.
    try:
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT project_id FROM ai_rag.documents WHERE id = %s",
                    (document_id,),
                )
                doc_row = await cur.fetchone()
        if doc_row is None:
            LOGGER.error(
                "ai_rag.documents row missing for doc_id=%s — cannot run fitment",
                document_id,
            )
            return
        project_id = doc_row["project_id"]
    except Exception:
        LOGGER.exception(
            "Failed to fetch project_id for doc_id=%s — skipping fitment", document_id
        )
        return

    active_topics = await TopicDAO.list_active_by_project(project_id)
    if not active_topics:
        LOGGER.warning(
            "No active topics for project_id=%s doc_id=%s — skipping fitment",
            project_id, document_id,
        )
        return

    LOGGER.info(
        "Starting fitment: doc_id=%s topics=%d", document_id, len(active_topics)
    )

    bedrock_client = _get_bedrock_client()
    embedding_model = get_settings().bedrock_embedding_model

    topic_tasks = [
        _evaluate_topic(document_id, topic, final_summary, bedrock_client, embedding_model)
        for topic in active_topics
    ]
    results = await asyncio.gather(*topic_tasks, return_exceptions=True)

    for topic, result in zip(active_topics, results):
        if isinstance(result, BaseException):
            LOGGER.error(
                "Unhandled fitment error topic=%r doc_id=%s: %s",
                topic.name, document_id, result,
            )

    LOGGER.info(
        "Fitment done: doc_id=%s topics_evaluated=%d", document_id, len(active_topics)
    )
