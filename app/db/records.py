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
    categorisation_status: Optional[str]  # pending | processing | done | uncategorised | failed
    processing_started_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "ProcessingStateRecord":
        return cls(
            id=row["id"],
            document_id=row["document_id"],
            summary_status=row["summary_status"],
            categorisation_status=row.get("categorisation_status"),
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


@dataclass
class DocumentScopeAssignmentRecord:
    """Maps 1:1 to a vdr_agent.document_scope_assignments table row.

    Created/updated by Phase 13 (scope categorisation pipeline) after LLM response.
    Read by Phase 14 (API) via list_by_document and list_by_topic.
    """

    id: UUID
    document_id: UUID
    topic_id: UUID
    confidence: str  # HIGH | MEDIUM | LOW
    justification: Optional[str]
    needs_review: bool
    review_reason: Optional[str]
    raw_response: Optional[dict]  # JSONB deserialises to dict
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "DocumentScopeAssignmentRecord":
        return cls(
            id=row["id"],
            document_id=row["document_id"],
            topic_id=row["topic_id"],
            confidence=row["confidence"],
            justification=row.get("justification"),
            needs_review=row["needs_review"],
            review_reason=row.get("review_reason"),
            raw_response=row.get("raw_response"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class ScopeAssignmentDetailRecord:
    """Returned by DocumentScopeAssignmentDAO.list_by_topic cross-schema JOIN.

    Includes file metadata from ai_rag.documents and summary text from
    vdr_agent.document_summaries alongside the scope assignment fields.
    Used by Phase 14 (API) to populate ScopeDetails topic panel.
    """

    document_id: UUID
    file_name: str
    file_path: str
    file_type: str
    summary_text: Optional[str]
    confidence: str  # HIGH | MEDIUM | LOW
    justification: Optional[str]
    needs_review: bool
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict) -> "ScopeAssignmentDetailRecord":
        return cls(
            document_id=row["document_id"],
            file_name=row["file_name"],
            file_path=row["file_path"],
            file_type=row["file_type"],
            summary_text=row.get("summary_text"),
            confidence=row["confidence"],
            justification=row.get("justification"),
            needs_review=row["needs_review"],
            created_at=row["created_at"],
        )
