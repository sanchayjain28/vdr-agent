from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.records import TopicRecord


class TopicCreate(BaseModel):
    """Request body for POST /topics."""

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=100)
    instruction: str = Field(..., min_length=1, max_length=5000)


class TopicUpdate(BaseModel):
    """Request body for PATCH /topics/{id}. All fields optional but non-empty if provided."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    instruction: Optional[str] = Field(None, min_length=1, max_length=5000)


class TopicBulkItem(BaseModel):
    """Single topic within a bulk create request."""

    name: str = Field(..., min_length=1, max_length=100)
    instruction: str = Field(..., min_length=1, max_length=5000)


class TopicBulkCreate(BaseModel):
    """Request body for POST /topics/bulk."""

    project_id: UUID
    topics: List[TopicBulkItem] = Field(..., min_length=1)


class TopicResponse(BaseModel):
    """Response body for all topic endpoints that return a topic."""

    id: UUID
    project_id: UUID
    name: str
    instruction: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_record(cls, record: TopicRecord) -> TopicResponse:
        """Convert a TopicRecord dataclass to a TopicResponse Pydantic model."""
        return cls(
            id=record.id,
            project_id=record.project_id,
            name=record.name,
            instruction=record.instruction,
            is_active=record.is_active,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
