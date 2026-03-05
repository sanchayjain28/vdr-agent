from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from app.db.records import DocumentListRecord


class SummaryResponse(BaseModel):
    """Response for GET /documents/{id}/summary"""
    document_id: UUID
    status: str  # pending | processing | done | failed
    summary_text: Optional[str] = None


class FitmentItem(BaseModel):
    """One entry in the fitment response array"""
    topic_id: UUID
    topic_name: str
    status: str  # pending | done | failed
    reasoning: Optional[str] = None


class DocumentListItem(BaseModel):
    """One entry in GET /documents?project_id= response"""
    id: UUID
    file_name: str
    file_path: str
    file_type: str
    page_count: Optional[int] = None
    summary_status: str  # pending | processing | done | failed
    summary_text: Optional[str] = None
    fitment_done_count: int
    fitment_total_count: int

    @classmethod
    def from_record(cls, record: DocumentListRecord) -> "DocumentListItem":
        return cls(
            id=record.id,
            file_name=record.file_name,
            file_path=record.file_path,
            file_type=record.file_type,
            page_count=record.page_count,
            summary_status=record.summary_status,
            summary_text=record.summary_text,
            fitment_done_count=record.fitment_done_count,
            fitment_total_count=record.fitment_total_count,
        )
