from __future__ import annotations

import asyncio
import logging
from typing import List, Set

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from psycopg.errors import UniqueViolation

from app.db.dao.document_scope_assignment_dao import DocumentScopeAssignmentDAO
from app.db.dao.document_summary_dao import DocumentSummaryDAO
from app.db.dao.processing_state_dao import ProcessingStateDAO
from app.db.dao.topic_dao import TopicDAO
from app.db.dao.topic_template_dao import TopicTemplateDAO
from app.db.pool import DatabasePool
from app.models.document import TopicDocumentItem, TopicDocumentsResponse
from app.models.topic import (
    ReclassifyResponse,
    TopicBulkCreate,
    TopicCreate,
    TopicResponse,
    TopicTemplateResponse,
    TopicUpdate,
)
from app.worker.processor import _categorise_document

LOGGER = logging.getLogger(__name__)

# In-memory set of project_ids with active reclassification tasks.
# Lost on server restart — acceptable since reclassification is short-lived.
_reclassifying_projects: Set[UUID] = set()

router = APIRouter(prefix="/topics", tags=["topics"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TopicResponse)
async def create_topic(body: TopicCreate) -> TopicResponse:
    """Create a new ESG topic for a project."""
    try:
        record = await TopicDAO.insert(
            project_id=body.project_id,
            name=body.name,
            instruction=body.instruction,
        )
    except UniqueViolation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A topic named '{body.name}' already exists in this project",
        )
    return TopicResponse.from_record(record)


@router.get("", response_model=List[TopicResponse])
async def list_topics(
    project_id: UUID = Query(..., description="Project UUID to list topics for"),
    include_inactive: bool = Query(False, description="Include soft-deleted topics"),
) -> List[TopicResponse]:
    """List topics for a project. Returns only active topics by default."""
    records = await TopicDAO.list_by_project(
        project_id=project_id,
        active_only=not include_inactive,
    )
    return [TopicResponse.from_record(r) for r in records]


@router.get("/templates", response_model=List[TopicTemplateResponse])
async def list_topic_templates() -> List[TopicTemplateResponse]:
    """Return all 19 ESG topic templates ordered by id. Used to pre-populate topics on project creation."""
    records = await TopicTemplateDAO.list_all()
    return [TopicTemplateResponse.from_record(r) for r in records]


@router.post("/bulk", status_code=status.HTTP_201_CREATED, response_model=List[TopicResponse])
async def bulk_create_topics(body: TopicBulkCreate) -> List[TopicResponse]:
    """Create multiple topics in one transaction. All-or-nothing — if any fails, none are created."""
    topics_data = [{"name": t.name, "instruction": t.instruction} for t in body.topics]
    try:
        records = await TopicDAO.bulk_insert(
            project_id=body.project_id,
            topics=topics_data,
        )
    except UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Duplicate topic name in request or project: {exc.diag.message_detail or str(exc)}",
        )
    return [TopicResponse.from_record(r) for r in records]


@router.patch("/{topic_id}", response_model=TopicResponse)
async def update_topic(topic_id: UUID, body: TopicUpdate) -> TopicResponse:
    """Update a topic's name and/or instruction. Omitted fields stay unchanged."""
    if body.name is None and body.instruction is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one field (name or instruction) must be provided",
        )
    try:
        record = await TopicDAO.update(
            topic_id=topic_id,
            name=body.name,
            instruction=body.instruction,
        )
    except UniqueViolation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A topic named '{body.name}' already exists in this project",
        )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    return TopicResponse.from_record(record)


@router.delete("/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_topic(topic_id: UUID) -> Response:
    """Soft-delete a topic (sets is_active = false). Fitment results are preserved."""
    record = await TopicDAO.update(topic_id=topic_id, is_active=False)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _reclassify_all_documents(project_id: UUID) -> None:
    """Background task: re-classify ALL project documents.

    For each document with a processing_state row:
      1. Fetch summary_text from document_summaries
      2. Fetch chunks from ai_rag.document_pages (same SQL as processor.py)
      3. Delete existing scope assignments
      4. Call _categorise_document (handles its own error isolation)

    Concurrency guard is released in finally block.
    """
    try:
        # Fetch all processing_state rows for the project's documents
        async with DatabasePool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT ps.id AS processing_state_id, ps.document_id
                    FROM vdr_agent.processing_state ps
                    JOIN ai_rag.documents d ON d.id = ps.document_id
                    WHERE d.project_id = %s
                      AND d.status = 'completed'
                    """,
                    (project_id,),
                )
                doc_rows = await cur.fetchall()

        LOGGER.info(
            "Reclassify started: project_id=%s documents=%d",
            project_id, len(doc_rows),
        )

        for row in doc_rows:
            ps_id = row["processing_state_id"]
            doc_id = row["document_id"]

            # Fetch summary text
            summary_rec = await DocumentSummaryDAO.get_by_document(doc_id)
            if not summary_rec or not summary_rec.summary_text:
                LOGGER.warning(
                    "Reclassify skip: no summary for doc_id=%s", doc_id
                )
                continue

            # Fetch chunks (same pattern as processor.py re-run path)
            async with DatabasePool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT content
                        FROM ai_rag.document_pages
                        WHERE document_id = %s
                        ORDER BY page_number ASC
                        """,
                        (doc_id,),
                    )
                    chunk_rows = await cur.fetchall()
            chunks = [r["content"] for r in chunk_rows]

            # Delete existing assignments before re-categorisation
            await DocumentScopeAssignmentDAO.delete_by_document(doc_id)

            # Run categorisation (error-isolated, never re-raises)
            await _categorise_document(
                processing_state_id=ps_id,
                document_id=doc_id,
                project_id=project_id,
                summary_text=summary_rec.summary_text,
                chunks=chunks,
            )

        LOGGER.info("Reclassify completed: project_id=%s", project_id)
    except Exception as exc:
        LOGGER.error(
            "Reclassify failed: project_id=%s error=%s",
            project_id, exc, exc_info=True,
        )
    finally:
        _reclassifying_projects.discard(project_id)


@router.post("/{topic_id}/reclassify", status_code=status.HTTP_202_ACCEPTED, response_model=ReclassifyResponse)
async def reclassify_topic_documents(topic_id: UUID) -> ReclassifyResponse:
    """POST /topics/{id}/reclassify — trigger re-classification of all project documents.

    Returns 202 Accepted immediately. Re-classification runs as a background asyncio task.
    Returns 404 if topic_id does not exist.
    Returns 409 if a reclassification is already running for the same project.
    """
    topic = await TopicDAO.get_by_id(topic_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")

    project_id = topic.project_id

    if project_id in _reclassifying_projects:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Re-classification already in progress for this project",
        )

    _reclassifying_projects.add(project_id)
    asyncio.create_task(_reclassify_all_documents(project_id))

    return ReclassifyResponse(
        message="Re-classification started for all project documents",
        project_id=project_id,
    )


@router.get("/{topic_id}/documents", response_model=TopicDocumentsResponse)
async def list_topic_documents(
    topic_id: UUID,
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> TopicDocumentsResponse:
    """GET /topics/{id}/documents — paginated documents classified under a topic.

    Returns 404 when topic_id does not exist.
    Returns empty documents array (not 404) when topic exists but has no assignments.
    Pagination defaults: limit=20, offset=0. Max limit: 100.
    """
    topic = await TopicDAO.get_by_id(topic_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")

    records, total_count = await DocumentScopeAssignmentDAO.list_by_topic(
        topic_id, limit=limit, offset=offset
    )

    LOGGER.debug(
        "list_topic_documents topic_id=%s total_count=%d limit=%d offset=%d",
        topic_id,
        total_count,
        limit,
        offset,
    )

    return TopicDocumentsResponse(
        total_count=total_count,
        limit=limit,
        offset=offset,
        documents=[TopicDocumentItem.from_record(r) for r in records],
    )
