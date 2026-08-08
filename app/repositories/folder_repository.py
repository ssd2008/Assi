from __future__ import annotations

from uuid import UUID, uuid4

import asyncpg

from app.schemas import FolderOut

SYSTEM_FOLDER_ID = UUID("00000000-0000-0000-0000-000000000001")
SYSTEM_FOLDER_NAME = "Без папки"

_FOLDER_COLUMNS = "f.id, f.name, f.is_system, f.created_at, f.updated_at"


class FolderRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @staticmethod
    def _to_public(record: asyncpg.Record) -> FolderOut:
        return FolderOut(
            id=record["id"],
            name=record["name"],
            is_system=record["is_system"],
            document_count=int(record["document_count"] or 0),
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )

    async def list(self) -> list[FolderOut]:
        records = await self._pool.fetch(
            f"""
            SELECT {_FOLDER_COLUMNS}, COUNT(d.id) AS document_count
            FROM folders f
            LEFT JOIN documents d ON d.folder_id = f.id
            GROUP BY f.id, f.name, f.is_system, f.created_at, f.updated_at
            ORDER BY f.is_system ASC, LOWER(f.name) ASC
            """
        )
        return [self._to_public(record) for record in records]

    async def get(self, folder_id: UUID) -> FolderOut | None:
        record = await self._pool.fetchrow(
            f"""
            SELECT {_FOLDER_COLUMNS}, COUNT(d.id) AS document_count
            FROM folders f
            LEFT JOIN documents d ON d.folder_id = f.id
            WHERE f.id = $1
            GROUP BY f.id, f.name, f.is_system, f.created_at, f.updated_at
            """,
            folder_id,
        )
        return self._to_public(record) if record else None

    async def create(self, name: str) -> FolderOut:
        record = await self._pool.fetchrow(
            """
            INSERT INTO folders (id, name, is_system)
            VALUES ($1, $2, FALSE)
            RETURNING id, name, is_system, created_at, updated_at, 0::BIGINT AS document_count
            """,
            uuid4(),
            name,
        )
        if record is None:
            raise RuntimeError("PostgreSQL did not return the created folder")
        return self._to_public(record)

    async def rename(self, folder_id: UUID, name: str) -> FolderOut | None:
        record = await self._pool.fetchrow(
            """
            UPDATE folders
            SET name = $2
            WHERE id = $1 AND is_system = FALSE
            RETURNING id, name, is_system, created_at, updated_at,
                (SELECT COUNT(*) FROM documents d WHERE d.folder_id = folders.id)::BIGINT AS document_count
            """,
            folder_id,
            name,
        )
        return self._to_public(record) if record else None

    async def delete_and_move_documents(self, folder_id: UUID) -> int | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                folder = await connection.fetchrow(
                    "SELECT id, is_system FROM folders WHERE id = $1 FOR UPDATE",
                    folder_id,
                )
                if folder is None:
                    return None
                if folder["is_system"]:
                    return -1
                moved = await connection.fetchval(
                    """
                    WITH moved AS (
                        UPDATE documents
                        SET folder_id = $2
                        WHERE folder_id = $1
                        RETURNING id
                    )
                    SELECT COUNT(*) FROM moved
                    """,
                    folder_id,
                    SYSTEM_FOLDER_ID,
                )
                await connection.execute("DELETE FROM folders WHERE id = $1", folder_id)
                return int(moved or 0)
