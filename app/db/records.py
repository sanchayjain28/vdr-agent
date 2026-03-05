from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class TopicRecord:
    id: UUID
    project_id: UUID
    name: str
    instruction: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "TopicRecord":
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"],
            instruction=row["instruction"],
            is_active=row["is_active"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class ProcessingStateRecord:
    id: UUID
    document_id: UUID
    summary_status: str  # pending | processing | done | failed
    processing_started_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "ProcessingStateRecord":
        return cls(
            id=row["id"],
            document_id=row["document_id"],
            summary_status=row["summary_status"],
            processing_started_at=row.get("processing_started_at"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class DocumentSummaryRecord:
    id: UUID
    document_id: UUID
    summary_text: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "DocumentSummaryRecord":
        return cls(
            id=row["id"],
            document_id=row["document_id"],
            summary_text=row["summary_text"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class FitmentResultRecord:
    id: UUID
    document_id: UUID
    topic_id: UUID
    reasoning: Optional[str]
    status: str  # pending | done | failed
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "FitmentResultRecord":
        return cls(
            id=row["id"],
            document_id=row["document_id"],
            topic_id=row["topic_id"],
            reasoning=row.get("reasoning"),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class DocumentListRecord:
    id: UUID
    file_name: str
    file_path: str
    file_type: str
    page_count: Optional[int]
    summary_status: str  # COALESCE ensures this is never None
    summary_text: Optional[str]
    fitment_done_count: int
    fitment_total_count: int

    @classmethod
    def from_row(cls, row: dict) -> "DocumentListRecord":
        return cls(
            id=row["id"],
            file_name=row["file_name"],
            file_path=row["file_path"],
            file_type=row["file_type"],
            page_count=row.get("page_count"),
            summary_status=row["summary_status"],
            summary_text=row.get("summary_text"),
            fitment_done_count=row["fitment_done_count"],
            fitment_total_count=row["fitment_total_count"],
        )
