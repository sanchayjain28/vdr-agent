from __future__ import annotations

import logging
from typing import List

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from psycopg.errors import UniqueViolation

from app.db.dao.topic_dao import TopicDAO
from app.models.topic import (
    TopicBulkCreate,
    TopicCreate,
    TopicResponse,
    TopicUpdate,
)

LOGGER = logging.getLogger(__name__)

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
