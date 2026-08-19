from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.container import AppContainer
from app.dependencies import get_container
from app.exceptions import InvalidRangeError
from app.schemas import AnswerOut, VideoAskRequest, VideoWorkspaceOut

router = APIRouter(prefix="/videos", tags=["videos"])
_CHUNK_SIZE = 1024 * 1024


def _parse_range(value: str | None, size: int) -> tuple[int, int, bool]:
    if not value:
        return 0, size - 1, False
    if not value.startswith("bytes=") or "," in value:
        raise InvalidRangeError("Only one byte range is supported")
    raw = value[6:].strip()
    if "-" not in raw:
        raise InvalidRangeError("Invalid Range header")
    left, right = raw.split("-", 1)
    try:
        if left:
            start = int(left)
            end = int(right) if right else size - 1
        else:
            suffix = int(right)
            if suffix <= 0:
                raise ValueError
            start = max(0, size - suffix)
            end = size - 1
    except ValueError as exc:
        raise InvalidRangeError("Invalid Range header") from exc
    if start < 0 or start >= size or end < start:
        raise InvalidRangeError("Requested range is outside the video")
    return start, min(end, size - 1), True


def _iter_file(path: Path, start: int, end: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as source:
        source.seek(start)
        while remaining > 0:
            chunk = source.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/{document_id}", response_model=VideoWorkspaceOut)
async def get_video_workspace(document_id: UUID, container: AppContainer = Depends(get_container)) -> VideoWorkspaceOut:
    return await container.video_service.workspace(document_id)


@router.get("/{document_id}/stream")
async def stream_video(document_id: UUID, request: Request, container: AppContainer = Depends(get_container)) -> StreamingResponse:
    path, mime_type, size = await container.video_service.stream_source(document_id)
    start, end, partial = _parse_range(request.headers.get("range"), size)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Cache-Control": "private, max-age=0",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _iter_file(path, start, end),
        status_code=206 if partial else 200,
        media_type=mime_type,
        headers=headers,
    )


@router.post("/{document_id}/ask", response_model=AnswerOut)
async def ask_video(document_id: UUID, request: VideoAskRequest, container: AppContainer = Depends(get_container)) -> AnswerOut:
    return await container.video_service.ask(document_id, request)
