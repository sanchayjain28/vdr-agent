from __future__ import annotations

import asyncio
import json
import logging
from typing import List
from uuid import UUID

from app.config import get_settings
from app.core.llm.claude_client import ClaudeClientError, _get_bedrock_client, invoke
from app.core.llm.rate_limiter import get_rate_limiter
from app.db.dao.document_scope_assignment_dao import DocumentScopeAssignmentDAO
from app.db.dao.document_summary_dao import DocumentSummaryDAO
from app.db.dao.fitment_result_dao import FitmentResultDAO
from app.db.dao.processing_state_dao import ProcessingStateDAO
from app.db.dao.topic_dao import TopicDAO
from app.db.pool import DatabasePool
from app.db.records import TopicRecord
from app.prompts.categorisation import CATEGORISATION_SYSTEM_PROMPT, build_categorisation_prompt

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


async def _categorise_document(
    processing_state_id: UUID,
    document_id: UUID,
    project_id: UUID,
    summary_text: str,
    chunks: list[str],
) -> None:
    """Classify a document into ESG scopes using a single LLM call.

    Pipeline:
      1. Set categorisation_status to 'processing'.
      2. Fetch active topics for the project (for prompt injection, EINST-01).
      3. Fetch document metadata (file_name, file_path, file_type).
      4. Build the categorisation prompt.
      5. Invoke Claude under rate limiter (exactly one call per document, SCPIPE-01).
      6. Parse JSON response.
      7. Handle empty scopes -> mark 'uncategorised' (SCPIPE-05).
      8. Resolve scope names to topic_ids via case-insensitive match (SCPIPE-03).
      9. Build assignment dicts (SCPIPE-04).
      10. Persist via DocumentScopeAssignmentDAO.bulk_upsert.
      11. Set categorisation_status to 'done'.

    On any error: logs, sets categorisation_status='failed', does NOT re-raise.
    DB connections are always released before the LLM call.
    """
    try:
        # Step 1: Set categorisation_status to 'processing'
        await ProcessingStateDAO.update_categorisation_status(processing_state_id, "processing")

        # Step 2: Fetch active topics for project
        active_topics = await TopicDAO.list_active_by_project(project_id)

        # Step 3: Fetch document metadata — short-lived connection released before LLM call
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT file_name, file_path, file_type FROM ai_rag.documents WHERE id = %s",
                    (document_id,),
                )
                doc_meta = await cur.fetchone()

        if doc_meta is None:
            LOGGER.error(
                "ai_rag.documents row missing for doc_id=%s — cannot run categorisation",
                document_id,
            )
            await ProcessingStateDAO.update_categorisation_status(processing_state_id, "failed")
            return

        # Step 4: Build the categorisation prompt
        user_prompt = build_categorisation_prompt(
            file_name=doc_meta["file_name"],
            file_path=doc_meta["file_path"],
            file_type=doc_meta["file_type"],
            summary_text=summary_text,
            chunks=chunks,
            topics=active_topics,
        )

        # Step 5: Invoke LLM under rate limiter (exactly one call per document, SCPIPE-01)
        async with get_rate_limiter().acquire():
            response_text = await invoke(user_prompt, system_prompt=CATEGORISATION_SYSTEM_PROMPT)

        # Step 6: Parse JSON response — strip markdown code fences if present
        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            # Remove opening fence (```json or ```) and closing fence (```)
            clean_text = clean_text.split("\n", 1)[1] if "\n" in clean_text else clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()
        try:
            parsed = json.loads(clean_text)
        except (json.JSONDecodeError, ValueError) as exc:
            LOGGER.error(
                "Failed to parse categorisation JSON for doc_id=%s: %s — response: %.200r",
                document_id, exc, response_text,
            )
            await ProcessingStateDAO.update_categorisation_status(processing_state_id, "failed")
            return

        scopes = parsed.get("scopes", [])

        # Step 7: Handle empty scopes — mark 'uncategorised', no sentinel rows (SCPIPE-05)
        if not scopes:
            await ProcessingStateDAO.update_categorisation_status(processing_state_id, "uncategorised")
            LOGGER.info(
                "No scopes returned for doc_id=%s — marking uncategorised", document_id
            )
            return

        # Step 8: Resolve scope names to topic_ids via case-insensitive match (SCPIPE-03)
        topic_lookup = {t.name.lower(): t.id for t in active_topics}
        matched_assignments = []
        unmatched_names = []

        for scope in scopes:
            scope_name = scope.get("name", "")
            topic_id = topic_lookup.get(scope_name.lower())
            if topic_id is not None:
                matched_assignments.append((topic_id, scope))
            else:
                unmatched_names.append(scope_name)
                LOGGER.warning(
                    "Unmatched scope name %r for doc_id=%s — no topic found",
                    scope_name, document_id,
                )

        # If any scope name was unmatched, flag ALL matched assignments as needs_review (SCPIPE-03)
        has_unmatched = bool(unmatched_names)
        review_reason_text = (
            f"Unmatched scope names: {', '.join(unmatched_names)}" if has_unmatched else None
        )

        # Step 9: Build assignment dicts for bulk_upsert (SCPIPE-04)
        assignments = [
            {
                "document_id": document_id,
                "topic_id": topic_id,
                "confidence": scope.get("confidence"),  # HIGH|MEDIUM|LOW
                "justification": scope.get("justification"),
                "needs_review": has_unmatched,
                "review_reason": review_reason_text if has_unmatched else None,
                "raw_response": parsed,  # Full LLM JSON for audit
            }
            for topic_id, scope in matched_assignments
        ]

        # Step 10: Persist via bulk_upsert
        if assignments:
            await DocumentScopeAssignmentDAO.bulk_upsert(assignments)

        # Step 11: Set categorisation_status to 'done'
        await ProcessingStateDAO.update_categorisation_status(processing_state_id, "done")

        LOGGER.info(
            "Categorisation complete: doc_id=%s scopes_matched=%d unmatched=%d",
            document_id, len(assignments), len(unmatched_names),
        )

    except Exception:
        LOGGER.exception(
            "Categorisation failed: ps_id=%s doc_id=%s", processing_state_id, document_id
        )
        await ProcessingStateDAO.update_categorisation_status(processing_state_id, "failed")
        # Do NOT re-raise — summary remains accessible and usable


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
    """Generate an AI summary for one document, then run scope categorisation.

    Pipeline:
      Re-run safety: if summary already exists, skip to categorisation.
      Else:
        Phase 1. Fetch all embedding chunks (short-lived DB connection).
        Phase 2+3. Parallel section summaries -> combine -> final_summary.
        Phase 4. Persist summary; set summary_status = 'done'.
      Phase 5. Fetch project_id for categorisation.
      Phase 6. Scope categorisation via _categorise_document().
      Phase 7 (Fitment): Skipped — replaced by scope categorisation above. Code retained for potential future use.

    On summary pipeline failure: sets summary_status = 'failed' and returns.
    Categorisation errors are handled inside _categorise_document (sets categorisation_status).
    Signature is fixed — poller.py passes (processing_state_id, document_id) unchanged.
    """
    # ── Re-run safety: skip summary if already generated ────────────────────
    # If document_summaries already has a row, jump directly to categorisation.
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
            "Summary already exists for doc_id=%s — skipping to categorisation", document_id
        )
        final_summary = existing_summary.summary_text
        # Re-run path: chunks must be fetched for categorisation prompt
        sql_chunks = """
            SELECT content, chunk_index
            FROM ai_rag.embeddings
            WHERE document_id = %s
            ORDER BY chunk_index
        """
        try:
            async with DatabasePool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql_chunks, (document_id,))
                    chunk_rows = await cur.fetchall()
            chunks = [row["content"] for row in chunk_rows]
        except Exception:
            LOGGER.exception(
                "Failed to fetch chunks for re-run categorisation doc_id=%s ps_id=%s",
                document_id, processing_state_id,
            )
            chunks = []
        # Jump directly to the categorisation block below — skip Phase 1-4 entirely.
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

    # ── Phase 5: Fetch project_id for categorisation ─────────────────────────
    # Runs whether summary was freshly generated (else branch) or already existed
    # (if branch). final_summary and chunks are set in both branches above.
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
                "ai_rag.documents row missing for doc_id=%s — cannot run categorisation",
                document_id,
            )
            return
        project_id = doc_row["project_id"]
    except Exception:
        LOGGER.exception(
            "Failed to fetch project_id for doc_id=%s — skipping categorisation", document_id
        )
        return

    # ── Phase 6: Scope Categorisation ────────────────────────────────────────
    # Exactly one LLM call per document (SCPIPE-01).
    # Errors are handled inside _categorise_document — never propagated here.
    await _categorise_document(
        processing_state_id=processing_state_id,
        document_id=document_id,
        project_id=project_id,
        summary_text=final_summary,
        chunks=chunks,
    )

    # ── Phase 7 (Fitment): Skipped — replaced by scope categorisation above. Code retained for potential future use. ──
