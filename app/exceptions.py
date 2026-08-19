from __future__ import annotations

from typing import Any


class AppError(RuntimeError):
    """Base domain error converted to the public API error format."""

    status_code = 400
    code = "application_error"

    def __init__(self, detail: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.context = context or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class DocumentNotFoundError(NotFoundError):
    code = "document_not_found"


class FolderNotFoundError(NotFoundError):
    code = "folder_not_found"


class JobNotFoundError(NotFoundError):
    code = "job_not_found"


class FolderConflictError(ConflictError):
    code = "folder_conflict"


class InvalidDocumentError(AppError):
    status_code = 422
    code = "invalid_document"


class InvalidRangeError(AppError):
    status_code = 416
    code = "invalid_range"


class UnsupportedMediaTypeError(AppError):
    status_code = 415
    code = "unsupported_media_type"


class DependencyUnavailableError(AppError):
    status_code = 503
    code = "dependency_unavailable"


class IndexingError(AppError):
    status_code = 500
    code = "indexing_failed"


class IndexingCancellationTimeoutError(AppError):
    status_code = 409
    code = "indexing_cancellation_timeout"


class IndexingCancelledError(RuntimeError):
    """Internal signal used to stop an indexing pipeline without marking it failed."""
