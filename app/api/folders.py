from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.container import AppContainer
from app.dependencies import get_container
from app.schemas import FolderCreate, FolderOut, FolderUpdate

router = APIRouter(prefix="/folders", tags=["folders"])


@router.get("", response_model=list[FolderOut])
async def list_folders(container: AppContainer = Depends(get_container)) -> list[FolderOut]:
    return await container.folder_service.list()


@router.post("", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(request: FolderCreate, container: AppContainer = Depends(get_container)) -> FolderOut:
    return await container.folder_service.create(request)


@router.patch("/{folder_id}", response_model=FolderOut)
async def rename_folder(folder_id: UUID, request: FolderUpdate, container: AppContainer = Depends(get_container)) -> FolderOut:
    return await container.folder_service.rename(folder_id, request)


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(folder_id: UUID, container: AppContainer = Depends(get_container)) -> Response:
    await container.folder_service.delete(folder_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
