from __future__ import annotations

from uuid import UUID

import asyncpg

from app.exceptions import FolderConflictError, FolderNotFoundError
from app.repositories.folder_repository import FolderRepository, SYSTEM_FOLDER_ID, SYSTEM_FOLDER_NAME
from app.repositories.vector_repository import VectorRepository
from app.schemas import FolderCreate, FolderOut, FolderUpdate


class FolderService:
    def __init__(self, *, repository: FolderRepository, vectors: VectorRepository) -> None:
        self._repository = repository
        self._vectors = vectors

    async def list(self) -> list[FolderOut]:
        return await self._repository.list()

    async def get(self, folder_id: UUID) -> FolderOut:
        folder = await self._repository.get(folder_id)
        if folder is None:
            raise FolderNotFoundError("Folder not found", context={"folder_id": str(folder_id)})
        return folder

    async def create(self, request: FolderCreate) -> FolderOut:
        try:
            return await self._repository.create(request.name)
        except asyncpg.UniqueViolationError as exc:
            raise FolderConflictError("A folder with this name already exists") from exc

    async def rename(self, folder_id: UUID, request: FolderUpdate) -> FolderOut:
        current = await self.get(folder_id)
        if current.is_system:
            raise FolderConflictError("The system folder cannot be renamed")
        try:
            folder = await self._repository.rename(folder_id, request.name)
        except asyncpg.UniqueViolationError as exc:
            raise FolderConflictError("A folder with this name already exists") from exc
        if folder is None:
            raise FolderNotFoundError("Folder not found", context={"folder_id": str(folder_id)})
        await self._vectors.update_folder_name(folder_id, folder.name)
        return folder

    async def delete(self, folder_id: UUID) -> int:
        folder = await self.get(folder_id)
        if folder.is_system:
            raise FolderConflictError("The system folder cannot be deleted")
        moved = await self._repository.delete_and_move_documents(folder_id)
        if moved is None:
            raise FolderNotFoundError("Folder not found", context={"folder_id": str(folder_id)})
        if moved < 0:
            raise FolderConflictError("The system folder cannot be deleted")
        await self._vectors.update_folder(
            folder_id,
            folder_id=SYSTEM_FOLDER_ID,
            folder_name=SYSTEM_FOLDER_NAME,
        )
        return moved
