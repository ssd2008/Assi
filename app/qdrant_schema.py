from __future__ import annotations

from datetime import date
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import SourceType

DENSE_VECTOR_NAME = "dense"
PAYLOAD_SCHEMA_VERSION = 3


class ChunkPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[3] = PAYLOAD_SCHEMA_VERSION
    document_id: UUID
    folder_id: UUID
    folder_name: str = Field(min_length=1, max_length=120)
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    token_count: int = Field(gt=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    time_start_seconds: float | None = Field(default=None, ge=0)
    time_end_seconds: float | None = Field(default=None, ge=0)
    section_title: str | None = Field(default=None, max_length=500)
    document_title: str = Field(min_length=1, max_length=1000)
    source_type: SourceType
    source_url: str | None = Field(default=None, max_length=4000)
    lecture_date: date | None = None
    lecture_date_ordinal: int | None = Field(default=None, ge=1)
    language: str = Field(min_length=2, max_length=16)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_ranges(self) -> "ChunkPayload":
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError("page_start and page_end must be set together")
        if self.page_start is not None and self.page_end is not None and self.page_end < self.page_start:
            raise ValueError("page_end cannot be smaller than page_start")
        if (self.time_start_seconds is None) != (self.time_end_seconds is None):
            raise ValueError("time_start_seconds and time_end_seconds must be set together")
        if self.time_start_seconds is not None and self.time_end_seconds is not None and self.time_end_seconds < self.time_start_seconds:
            raise ValueError("time_end_seconds cannot be smaller than time_start_seconds")
        if self.lecture_date is None and self.lecture_date_ordinal is not None:
            raise ValueError("lecture_date_ordinal requires lecture_date")
        if self.lecture_date is not None and self.lecture_date_ordinal != self.lecture_date.toordinal():
            raise ValueError("lecture_date_ordinal does not match lecture_date")
        return self

    def to_qdrant_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)


def calculate_content_hash(text: str) -> str:
    return sha256(text.strip().encode("utf-8")).hexdigest()


def build_chunk_point_id(document_id: UUID, chunk_index: int, content_hash: str) -> UUID:
    if chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    if len(content_hash) != 64:
        raise ValueError("content_hash must be a SHA-256 hexadecimal digest")
    return uuid5(document_id, f"{chunk_index}:{content_hash}")
