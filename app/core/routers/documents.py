from __future__ import annotations

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.db.dao.document_list_dao import DocumentListDAO
from app.db.dao.document_scope_assignment_dao import DocumentScopeAssignmentDAO
from app.db.dao.document_summary_dao import DocumentSummaryDAO
from app.db.dao.fitment_result_dao import FitmentResultDAO
from app.db.dao.processing_state_dao import ProcessingStateDAO
from app.db.dao.topic_dao import TopicDAO
from app.db.pool import DatabasePool
from app.models.document import DocumentListItem, FitmentItem, ScopeAssignmentItem, ScopesResponse, SummaryResponse

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


async def _get_document_or_404(document_id: UUID) -> dict:
    """Fetch document row from ai_rag.documents; raise 404 if not found.
    Returns dict with 'id' and 'project_id' keys.
    Source: established pattern from processor.py (Phase 7).
    """
    async with DatabasePool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, project_id FROM ai_rag.documents WHERE id = %s",
                (document_id,),
            )
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    col_names = ["id", "project_id"]
    return dict(zip(col_names, row))


@router.get("/{document_id}/summary", response_model=SummaryResponse)
async def get_document_summary(document_id: UUID) -> SummaryResponse:
    """GET /documents/{id}/summary — AI summary text and processing status.

    Returns 200 for ALL known documents regardless of processing state.
    Returns 404 only when document_id does not exist in ai_rag.documents.
    If no processing_state row exists, synthesizes status='pending'.
    """
    await _get_document_or_404(document_id)
    state = await ProcessingStateDAO.get_by_document(document_id)
    summary = await DocumentSummaryDAO.get_by_document(document_id)
    return SummaryResponse(
        document_id=document_id,
        status=state.summary_status if state else "pending",
        summary_text=summary.summary_text if summary else None,
    )


@router.get("/{document_id}/fitment", response_model=List[FitmentItem])
async def get_document_fitment(document_id: UUID) -> List[FitmentItem]:
    """GET /documents/{id}/fitment — per-topic fitment results for one document.

    Returns one FitmentItem per ACTIVE topic for the document's project.
    Topics with no fitment_results row get synthesized {status: 'pending', reasoning: null}.
    Stale fitment rows for soft-deleted topics are excluded (authoritative list = active topics only).
    Returns 404 only when document_id does not exist in ai_rag.documents.
    """
    doc_row = await _get_document_or_404(document_id)
    project_id = doc_row["project_id"]

    topics = await TopicDAO.list_active_by_project(project_id)
    fitment_rows = await FitmentResultDAO.list_by_document(document_id)

    # Index by topic_id for O(1) lookup — avoids nested loops
    fitment_by_topic = {r.topic_id: r for r in fitment_rows}

    result = []
    for topic in topics:
        row = fitment_by_topic.get(topic.id)
        result.append(FitmentItem(
            topic_id=topic.id,
            topic_name=topic.name,
            status=row.status if row else "pending",
            reasoning=row.reasoning if row else None,
        ))
    return result


@router.get("/{document_id}/scopes", response_model=ScopesResponse)
async def get_document_scopes(document_id: UUID) -> ScopesResponse:
    """GET /documents/{id}/scopes — scope assignments with topic names and categorisation status.

    Returns 200 for ALL known documents regardless of categorisation state.
    Returns 404 only when document_id does not exist in ai_rag.documents.
    Returns empty scopes array (not 404) when no assignments exist yet.
    categorisation_status falls back to 'pending' when no processing_state row exists.
    Uses active_only=False when resolving topic names — assignments may reference
    soft-deleted topics.
    """
    doc_row = await _get_document_or_404(document_id)
    project_id = doc_row["project_id"]

    state = await ProcessingStateDAO.get_by_document(document_id)
    assignments = await DocumentScopeAssignmentDAO.list_by_document(document_id)

    # Batch-fetch all topics (including inactive) once for O(1) name lookup
    all_topics = await TopicDAO.list_by_project(project_id, active_only=False)
    topic_name_by_id = {t.id: t.name for t in all_topics}

    scopes = [
        ScopeAssignmentItem(
            topic_id=a.topic_id,
            topic_name=topic_name_by_id.get(a.topic_id, str(a.topic_id)),
            confidence=a.confidence,
            justification=a.justification,
            needs_review=a.needs_review,
            review_reason=a.review_reason,
            rank=idx + 1,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for idx, a in enumerate(assignments)
    ]

    LOGGER.debug(
        "get_document_scopes document_id=%s categorisation_status=%s scopes=%d",
        document_id,
        state.categorisation_status if state else "pending",
        len(scopes),
    )

    return ScopesResponse(
        document_id=document_id,
        categorisation_status=state.categorisation_status if state else "pending",
        scopes=scopes,
    )


@router.get("", response_model=List[DocumentListItem])
async def list_documents(
    project_id: UUID = Query(..., description="Project UUID to list documents for"),
) -> List[DocumentListItem]:
    """GET /documents?project_id=<id> — all documents for a project with processing status.

    Returns 404 when project_id has no documents in ai_rag.documents.
    (Proxy for project existence — vdr-agent has no projects table.)
    Documents with no processing_state row appear with summary_status='pending'.
    Ordered by created_at DESC.
    """
    records = await DocumentListDAO.list_by_project(project_id)
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No documents found for this project",
        )
    return [DocumentListItem.from_record(r) for r in records]
