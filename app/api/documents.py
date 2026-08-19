from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Response, UploadFile, status

from app.container import AppContainer
from app.dependencies import get_container
from app.schemas import DocumentCreate, DocumentOut, DocumentsListResponse, DocumentStatus, IndexDocumentRequest, IndexDocumentResponse, SourceType

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def create_document(request: DocumentCreate, container: AppContainer = Depends(get_container)) -> DocumentOut:
    return await container.document_service.create(request)


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=300),
    folder_id: UUID = Form(...),
    language: str = Form(default="ru", min_length=2, max_length=16),
    lecture_date: date | None = Form(default=None),
    metadata: str | None = Form(default=None),
    container: AppContainer = Depends(get_container),
) -> DocumentOut:
    data = await file.read(container.settings.max_document_size_bytes + 1)
    return await container.document_service.upload_pdf(
        filename=file.filename or "upload.pdf", content_type=file.content_type, data=data,
        title=title, folder_id=folder_id, language=language, lecture_date=lecture_date, metadata_json=metadata,
    )


@router.post("/upload/video", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_video(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=300),
    folder_id: UUID = Form(...),
    language: str = Form(default="ru", min_length=2, max_length=16),
    lecture_date: date | None = Form(default=None),
    metadata: str | None = Form(default=None),
    container: AppContainer = Depends(get_container),
) -> DocumentOut:
    await file.seek(0)
    return await container.document_service.upload_video(
        filename=file.filename or "upload.mp4", content_type=file.content_type, file_object=file.file,
        title=title, folder_id=folder_id, language=language, lecture_date=lecture_date, metadata_json=metadata,
    )


@router.get("", response_model=DocumentsListResponse)
async def list_documents(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    document_status: DocumentStatus | None = Query(default=None, alias="status"),
    source_type: SourceType | None = Query(default=None),
    folder_id: UUID | None = Query(default=None),
    container: AppContainer = Depends(get_container),
) -> DocumentsListResponse:
    return await container.document_service.list(
        limit=limit, offset=offset, status=document_status, source_type=source_type, folder_id=folder_id,
    )


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: UUID, container: AppContainer = Depends(get_container)) -> DocumentOut:
    return await container.document_service.get(document_id)


@router.post("/{document_id}/index", response_model=IndexDocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def index_document(
    document_id: UUID,
    request: IndexDocumentRequest,
    background_tasks: BackgroundTasks,
    container: AppContainer = Depends(get_container),
) -> IndexDocumentResponse:
    job = await container.indexing_service.create_job(document_id, chunk_size=request.chunk_size, chunk_overlap=request.chunk_overlap)
    background_tasks.add_task(container.indexing_service.run_job, job.id, document_id)
    return IndexDocumentResponse(document_id=document_id, job_id=job.id, status=job.status)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, container: AppContainer = Depends(get_container)) -> Response:
    await container.indexing_service.cancel_document(document_id)
    await container.document_service.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
