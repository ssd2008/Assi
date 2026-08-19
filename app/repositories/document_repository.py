from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from app.schemas import DocumentOut, DocumentStatus, SourceType

_DOCUMENT_COLUMNS = """
    id, title, source_type, status, source_url, original_filename,
    storage_path, mime_type, size_bytes, checksum_sha256, content_text,
    folder_id, lecture_date, language, metadata, chunk_count,
    error_message, created_at, updated_at
"""


@dataclass(frozen=True, slots=True)
class DocumentInternal:
    id: UUID
    title: str
    source_type: SourceType
    status: DocumentStatus
    source_url: str | None
    original_filename: str | None
    storage_path: Path | None
    mime_type: str | None
    size_bytes: int | None
    checksum_sha256: str | None
    content_text: str | None
    folder_id: UUID
    lecture_date: date | None
    language: str
    metadata: dict[str, Any]
    chunk_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    def to_public(self) -> DocumentOut:
        return DocumentOut(
            id=self.id,
            title=self.title,
            source_type=self.source_type,
            status=self.status,
            folder_id=self.folder_id,
            source_url=self.source_url,
            original_filename=self.original_filename,
            mime_type=self.mime_type,
            size_bytes=self.size_bytes,
            lecture_date=self.lecture_date,
            language=self.language,
            metadata=self.metadata,
            chunk_count=self.chunk_count,
            error_message=self.error_message,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class DocumentRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @staticmethod
    def _to_internal(record: asyncpg.Record) -> DocumentInternal:
        data = dict(record)
        return DocumentInternal(
            id=data["id"], title=data["title"], source_type=SourceType(data["source_type"]),
            status=DocumentStatus(data["status"]), source_url=data["source_url"],
            original_filename=data["original_filename"],
            storage_path=Path(data["storage_path"]) if data["storage_path"] else None,
            mime_type=data["mime_type"], size_bytes=data["size_bytes"],
            checksum_sha256=data["checksum_sha256"], content_text=data["content_text"],
            folder_id=data["folder_id"], lecture_date=data["lecture_date"],
            language=data["language"], metadata=data["metadata"] or {},
            chunk_count=data["chunk_count"], error_message=data["error_message"],
            created_at=data["created_at"], updated_at=data["updated_at"],
        )

    async def ping(self) -> bool:
        return await self._pool.fetchval("SELECT 1") == 1

    async def create(
        self, *, title: str, source_type: SourceType, content_text: str | None,
        folder_id: UUID, source_url: str | None = None, original_filename: str | None = None,
        storage_path: Path | None = None, mime_type: str | None = None,
        size_bytes: int | None = None, checksum_sha256: str | None = None,
        lecture_date: date | None = None, language: str = "ru",
        metadata: dict[str, Any] | None = None,
    ) -> DocumentOut:
        record = await self._pool.fetchrow(
            f"""
            INSERT INTO documents (
                id, title, source_type, status, source_url, original_filename,
                storage_path, mime_type, size_bytes, checksum_sha256, content_text,
                folder_id, lecture_date, language, metadata
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            RETURNING {_DOCUMENT_COLUMNS}
            """,
            uuid4(), title, source_type.value, DocumentStatus.UPLOADED.value, source_url,
            original_filename, str(storage_path) if storage_path else None, mime_type, size_bytes,
            checksum_sha256.lower() if checksum_sha256 else None, content_text, folder_id,
            lecture_date, language, metadata or {},
        )
        if record is None:
            raise RuntimeError("PostgreSQL did not return the created document")
        return self._to_internal(record).to_public()

    async def get_internal(self, document_id: UUID) -> DocumentInternal | None:
        record = await self._pool.fetchrow(f"SELECT {_DOCUMENT_COLUMNS} FROM documents WHERE id=$1", document_id)
        return self._to_internal(record) if record else None

    async def get_by_id(self, document_id: UUID) -> DocumentOut | None:
        document = await self.get_internal(document_id)
        return document.to_public() if document else None

    @staticmethod
    def _filters(*, status: DocumentStatus | None, source_type: SourceType | None, folder_id: UUID | None) -> tuple[str, list[object]]:
        conditions: list[str] = []
        args: list[object] = []
        for column, value in (("status", status.value if status else None), ("source_type", source_type.value if source_type else None), ("folder_id", folder_id)):
            if value is not None:
                args.append(value)
                conditions.append(f"{column} = ${len(args)}")
        return ("WHERE " + " AND ".join(conditions) if conditions else "", args)

    async def list_documents(self, *, limit: int, offset: int, status: DocumentStatus | None = None, source_type: SourceType | None = None, folder_id: UUID | None = None) -> list[DocumentOut]:
        where, args = self._filters(status=status, source_type=source_type, folder_id=folder_id)
        args.extend([limit, offset])
        records = await self._pool.fetch(
            f"SELECT {_DOCUMENT_COLUMNS} FROM documents {where} ORDER BY created_at DESC LIMIT ${len(args)-1} OFFSET ${len(args)}",
            *args,
        )
        return [self._to_internal(record).to_public() for record in records]

    async def count_documents(self, *, status: DocumentStatus | None = None, source_type: SourceType | None = None, folder_id: UUID | None = None) -> int:
        where, args = self._filters(status=status, source_type=source_type, folder_id=folder_id)
        return int(await self._pool.fetchval(f"SELECT COUNT(*) FROM documents {where}", *args))

    async def update_status(self, document_id: UUID, status: DocumentStatus, *, error_message: str | None = None) -> DocumentOut | None:
        error_message = (error_message or "Unknown indexing error").strip() if status == DocumentStatus.FAILED else None
        record = await self._pool.fetchrow(
            f"UPDATE documents SET status=$2,error_message=$3 WHERE id=$1 RETURNING {_DOCUMENT_COLUMNS}",
            document_id, status.value, error_message,
        )
        return self._to_internal(record).to_public() if record else None

    async def update_extracted_content(self, document_id: UUID, *, content_text: str, metadata: dict[str, Any]) -> DocumentOut | None:
        record = await self._pool.fetchrow(
            f"UPDATE documents SET content_text=$2,metadata=$3,error_message=NULL WHERE id=$1 RETURNING {_DOCUMENT_COLUMNS}",
            document_id, content_text, metadata,
        )
        return self._to_internal(record).to_public() if record else None

    async def update_metadata(self, document_id: UUID, metadata: dict[str, Any]) -> DocumentOut | None:
        record = await self._pool.fetchrow(
            f"UPDATE documents SET metadata=$2 WHERE id=$1 RETURNING {_DOCUMENT_COLUMNS}",
            document_id, metadata,
        )
        return self._to_internal(record).to_public() if record else None

    async def finish_indexing(self, document_id: UUID, chunk_count: int) -> DocumentOut | None:
        record = await self._pool.fetchrow(
            f"UPDATE documents SET status=$2,chunk_count=$3,error_message=NULL WHERE id=$1 RETURNING {_DOCUMENT_COLUMNS}",
            document_id, DocumentStatus.READY.value, chunk_count,
        )
        return self._to_internal(record).to_public() if record else None

    async def delete(self, document_id: UUID) -> DocumentInternal | None:
        record = await self._pool.fetchrow(f"DELETE FROM documents WHERE id=$1 RETURNING {_DOCUMENT_COLUMNS}", document_id)
        return self._to_internal(record) if record else None
