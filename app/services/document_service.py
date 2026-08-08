from __future__ import annotations

import asyncio
import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from app.config import Settings
from app.exceptions import DocumentNotFoundError, FolderNotFoundError, InvalidDocumentError, UnsupportedMediaTypeError
from app.repositories.document_repository import DocumentRepository
from app.repositories.folder_repository import FolderRepository
from app.repositories.vector_repository import VectorRepository
from app.schemas import DocumentCreate, DocumentOut, DocumentsListResponse, DocumentStatus, SourceType
from app.services.extraction_service import ExtractionService

_VIDEO_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
}
_ALLOWED_VIDEO_MIME_TYPES = set(_VIDEO_TYPES.values()) | {"application/octet-stream", "video/matroska"}


class DocumentService:
    def __init__(self, *, settings: Settings, repository: DocumentRepository, folders: FolderRepository, vector_repository: VectorRepository, extraction_service: ExtractionService) -> None:
        self._settings = settings
        self._repository = repository
        self._folders = folders
        self._vectors = vector_repository
        self._extraction = extraction_service

    async def _require_folder(self, folder_id: UUID) -> None:
        if await self._folders.get(folder_id) is None:
            raise FolderNotFoundError("Folder not found", context={"folder_id": str(folder_id)})

    async def create(self, request: DocumentCreate) -> DocumentOut:
        await self._require_folder(request.folder_id)
        if request.source_type == SourceType.TEXT:
            extracted = self._extraction.extract_text(request.raw_text or "")
            source_url = None
        elif request.source_type == SourceType.URL:
            source_url = str(request.source_url)
            extracted = await self._extraction.extract_url(source_url)
        else:
            raise InvalidDocumentError("PDF and video documents must use their upload endpoints")
        return await self._repository.create(
            title=request.title,
            source_type=request.source_type,
            folder_id=request.folder_id,
            source_url=source_url,
            content_text=extracted.text,
            lecture_date=request.lecture_date,
            language=request.language,
            metadata=request.metadata,
        )

    @staticmethod
    def _parse_metadata(metadata_json: str | None) -> dict:
        try:
            metadata = json.loads(metadata_json) if metadata_json else {}
        except json.JSONDecodeError as exc:
            raise InvalidDocumentError("metadata must be a valid JSON object") from exc
        if not isinstance(metadata, dict):
            raise InvalidDocumentError("metadata must be a JSON object")
        return metadata

    async def upload_pdf(self, *, filename: str, content_type: str | None, data: bytes, title: str, folder_id: UUID, language: str, lecture_date, metadata_json: str | None) -> DocumentOut:
        await self._require_folder(folder_id)
        if not filename.lower().endswith(".pdf"):
            raise UnsupportedMediaTypeError("Only .pdf files are accepted")
        if content_type and content_type not in {"application/pdf", "application/octet-stream"}:
            raise UnsupportedMediaTypeError(f"Unsupported upload content type: {content_type}")
        if not data:
            raise InvalidDocumentError("Uploaded PDF is empty")
        if len(data) > self._settings.max_document_size_bytes:
            raise InvalidDocumentError(f"PDF exceeds the {self._settings.max_document_size_mb} MB limit")
        metadata = self._parse_metadata(metadata_json)
        extracted = await self._extraction.extract_pdf(data)
        upload_dir = self._settings.upload_dir
        await asyncio.to_thread(upload_dir.mkdir, parents=True, exist_ok=True)
        storage_path = upload_dir / f"{uuid4()}.pdf"
        await asyncio.to_thread(storage_path.write_bytes, data)
        checksum = hashlib.sha256(data).hexdigest()
        try:
            return await self._repository.create(
                title=title, source_type=SourceType.PDF, folder_id=folder_id,
                content_text=extracted.text, original_filename=Path(filename).name,
                storage_path=storage_path, mime_type="application/pdf", size_bytes=len(data),
                checksum_sha256=checksum, lecture_date=lecture_date, language=language,
                metadata={**metadata, "page_spans": [
                    {"page_number": span.page_number, "char_start": span.char_start, "char_end": span.char_end}
                    for span in extracted.page_spans
                ]},
            )
        except Exception:
            storage_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _store_video_stream(source: BinaryIO, storage_path: Path, max_size_bytes: int) -> tuple[int, str]:
        source.seek(0)
        checksum = hashlib.sha256()
        size_bytes = 0
        try:
            with storage_path.open("xb") as target:
                while chunk := source.read(8 * 1024 * 1024):
                    size_bytes += len(chunk)
                    if size_bytes > max_size_bytes:
                        limit_mb = max_size_bytes // (1024 * 1024)
                        raise InvalidDocumentError(f"Video exceeds the {limit_mb} MB limit")
                    checksum.update(chunk)
                    target.write(chunk)
            if size_bytes == 0:
                raise InvalidDocumentError("Uploaded video is empty")
            return size_bytes, checksum.hexdigest()
        except Exception:
            storage_path.unlink(missing_ok=True)
            raise

    async def upload_video(self, *, filename: str, content_type: str | None, data: bytes | None = None, file_object: BinaryIO | None = None, title: str, folder_id: UUID, language: str, lecture_date, metadata_json: str | None) -> DocumentOut:
        await self._require_folder(folder_id)
        suffix = Path(filename).suffix.lower()
        if suffix not in _VIDEO_TYPES:
            raise UnsupportedMediaTypeError("Supported video formats: .mp4, .mov, .mkv, .webm and .m4v")
        if content_type and content_type not in _ALLOWED_VIDEO_MIME_TYPES:
            raise UnsupportedMediaTypeError(f"Unsupported video content type: {content_type}")
        if (data is None) == (file_object is None):
            raise ValueError("Exactly one video input must be provided")
        metadata = self._parse_metadata(metadata_json)
        upload_dir = self._settings.upload_dir
        await asyncio.to_thread(upload_dir.mkdir, parents=True, exist_ok=True)
        storage_path = upload_dir / f"{uuid4()}{suffix}"
        source = file_object if file_object is not None else BytesIO(data or b"")
        size_bytes, checksum = await asyncio.to_thread(self._store_video_stream, source, storage_path, self._settings.max_video_size_bytes)
        try:
            return await self._repository.create(
                title=title, source_type=SourceType.VIDEO, folder_id=folder_id, content_text=None,
                original_filename=Path(filename).name, storage_path=storage_path,
                mime_type=_VIDEO_TYPES[suffix], size_bytes=size_bytes, checksum_sha256=checksum,
                lecture_date=lecture_date, language=language,
                metadata={**metadata, "transcription_status": "pending", "asr_model": self._settings.asr_model_name, "video_analysis_status": "pending"},
            )
        except Exception:
            storage_path.unlink(missing_ok=True)
            raise

    async def get(self, document_id: UUID) -> DocumentOut:
        document = await self._repository.get_by_id(document_id)
        if document is None:
            raise DocumentNotFoundError("Document not found", context={"document_id": str(document_id)})
        return document

    async def list(self, *, limit: int, offset: int, status: DocumentStatus | None, source_type: SourceType | None, folder_id: UUID | None) -> DocumentsListResponse:
        items, total = await asyncio.gather(
            self._repository.list_documents(limit=limit, offset=offset, status=status, source_type=source_type, folder_id=folder_id),
            self._repository.count_documents(status=status, source_type=source_type, folder_id=folder_id),
        )
        return DocumentsListResponse(items=items, total=total, limit=limit, offset=offset)

    async def delete(self, document_id: UUID) -> None:
        document = await self._repository.get_internal(document_id)
        if document is None:
            raise DocumentNotFoundError("Document not found", context={"document_id": str(document_id)})
        await self._vectors.delete_document(document_id)
        deleted = await self._repository.delete(document_id)
        if deleted and deleted.storage_path:
            await asyncio.to_thread(deleted.storage_path.unlink, missing_ok=True)
