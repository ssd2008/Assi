from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class APIModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        from_attributes=True,
        use_enum_values=False,
    )


class SourceType(StrEnum):
    PDF = "pdf"
    URL = "url"
    TEXT = "text"
    VIDEO = "video"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FolderCreate(APIModel):
    name: str = Field(min_length=1, max_length=120)


class FolderUpdate(APIModel):
    name: str = Field(min_length=1, max_length=120)


class FolderOut(APIModel):
    id: UUID
    name: str
    is_system: bool = False
    document_count: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class DocumentCreate(APIModel):
    title: str = Field(min_length=1, max_length=300)
    source_type: SourceType
    folder_id: UUID
    source_url: AnyHttpUrl | None = None
    raw_text: str | None = Field(default=None, min_length=1)
    lecture_date: date | None = None
    language: str = Field(default="ru", min_length=2, max_length=16)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source_payload(self) -> "DocumentCreate":
        if self.source_type in {SourceType.PDF, SourceType.VIDEO}:
            raise ValueError("PDF and video files must be uploaded through their upload endpoints")
        if self.source_type == SourceType.URL and self.source_url is None:
            raise ValueError("source_url is required for source_type='url'")
        if self.source_type == SourceType.TEXT and not self.raw_text:
            raise ValueError("raw_text is required for source_type='text'")
        if self.source_type != SourceType.URL and self.source_url is not None:
            raise ValueError("source_url is only valid for source_type='url'")
        if self.source_type != SourceType.TEXT and self.raw_text is not None:
            raise ValueError("raw_text is only valid for source_type='text'")
        return self


class DocumentOut(APIModel):
    id: UUID
    title: str
    source_type: SourceType
    status: DocumentStatus
    folder_id: UUID
    source_url: str | None = None
    original_filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    lecture_date: date | None = None
    language: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_count: int = Field(default=0, ge=0)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentsListResponse(APIModel):
    items: list[DocumentOut]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class IndexDocumentRequest(APIModel):
    chunk_size: int | None = Field(default=None, ge=50, le=5000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=2000)

    @model_validator(mode="after")
    def validate_overlap(self) -> "IndexDocumentRequest":
        if self.chunk_size is not None and self.chunk_overlap is not None and self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class IndexDocumentResponse(APIModel):
    document_id: UUID
    job_id: UUID
    status: JobStatus


class JobOut(APIModel):
    id: UUID
    document_id: UUID
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    chunk_size: int = Field(ge=1)
    chunk_overlap: int = Field(ge=0)
    result: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class SearchFilters(APIModel):
    document_ids: list[UUID] | None = None
    folder_ids: list[UUID] | None = None
    source_types: list[SourceType] | None = None
    language: str | None = Field(default=None, min_length=2, max_length=16)
    lecture_date_from: date | None = None
    lecture_date_to: date | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> "SearchFilters":
        if self.lecture_date_from is not None and self.lecture_date_to is not None and self.lecture_date_from > self.lecture_date_to:
            raise ValueError("lecture_date_from cannot be later than lecture_date_to")
        return self


class QueryRequest(APIModel):
    query: str = Field(min_length=2, max_length=5000)
    top_k: int = Field(default=10, ge=1, le=100)
    candidate_k: int = Field(default=30, ge=1, le=300)
    use_reranker: bool = False
    min_retrieval_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @model_validator(mode="after")
    def validate_limits(self) -> "QueryRequest":
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k cannot be smaller than top_k")
        return self


class SearchResult(APIModel):
    rank: int = Field(ge=1)
    chunk_id: UUID
    document_id: UUID
    document_title: str
    folder_id: UUID
    folder_name: str
    chunk_index: int = Field(ge=0)
    text: str
    source_type: SourceType
    source_url: str | None = None
    lecture_date: date | None = None
    language: str
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    time_start_seconds: float | None = Field(default=None, ge=0)
    time_end_seconds: float | None = Field(default=None, ge=0)
    section_title: str | None = None
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    retrieval_score: float
    rerank_score: float | None = None
    final_score: float


class SearchResponse(APIModel):
    query: str
    results: list[SearchResult]
    total_candidates: int = Field(ge=0)
    took_ms: float = Field(ge=0)


class AnswerRequest(QueryRequest):
    max_context_chunks: int = Field(default=6, ge=1, le=30)
    response_style: Literal["brief", "detailed", "study_notes"] = "detailed"
    include_citations: bool = True

    @model_validator(mode="after")
    def validate_context_limit(self) -> "AnswerRequest":
        if self.max_context_chunks > self.top_k:
            raise ValueError("max_context_chunks cannot exceed top_k")
        return self


class Citation(APIModel):
    number: int = Field(ge=1)
    document_id: UUID
    chunk_id: UUID
    document_title: str
    quote: str = Field(min_length=1)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    time_start_seconds: float | None = Field(default=None, ge=0)
    time_end_seconds: float | None = Field(default=None, ge=0)
    section_title: str | None = None
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    retrieval_score: float
    rerank_score: float | None = None


class AnswerOut(APIModel):
    answer: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    used_chunks: int = Field(ge=0)
    took_ms: float = Field(ge=0)


class TranscriptSegment(APIModel):
    index: int = Field(ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str = Field(min_length=1)


class VideoChapter(APIModel):
    index: int = Field(ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    title: str = Field(min_length=1, max_length=200)


class VideoHighlight(APIModel):
    index: int = Field(ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    title: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=1000)
    importance: int = Field(default=3, ge=1, le=5)


class VideoWorkspaceOut(APIModel):
    document: DocumentOut
    transcript: list[TranscriptSegment]
    chapters: list[VideoChapter]
    highlights: list[VideoHighlight]
    analysis_status: Literal["pending", "local", "generated", "failed"] = "pending"
    generative_features_enabled: bool = False


class ChatMessage(APIModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class VideoAskRequest(APIModel):
    message: str = Field(min_length=2, max_length=5000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=30)


class FeedbackRequest(APIModel):
    query: str = Field(min_length=1, max_length=5000)
    answer: str = Field(min_length=1, max_length=50000)
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=5000)
    document_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeedbackOut(APIModel):
    id: UUID
    created_at: datetime


class ComponentHealth(APIModel):
    status: Literal["ok", "error", "disabled"]
    detail: str | None = None


class HealthOut(APIModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    components: dict[str, ComponentHealth]


class ErrorOut(APIModel):
    code: str
    detail: str
    context: dict[str, Any] = Field(default_factory=dict)
