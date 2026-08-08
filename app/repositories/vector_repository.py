from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from pydantic import ValidationError
from qdrant_client import AsyncQdrantClient, models

from app.qdrant_schema import DENSE_VECTOR_NAME, ChunkPayload
from app.schemas import SearchFilters


class VectorRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VectorChunk:
    point_id: UUID
    vector: Sequence[float]
    payload: ChunkPayload


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    point_id: UUID
    score: float
    payload: ChunkPayload


@dataclass(frozen=True, slots=True)
class StoredVectorChunk:
    point_id: UUID
    payload: ChunkPayload


class VectorRepository:
    def __init__(self, client: AsyncQdrantClient, *, collection_name: str, vector_size: int, upsert_batch_size: int = 64) -> None:
        self._client = client
        self._collection_name = collection_name
        self._vector_size = vector_size
        self._upsert_batch_size = upsert_batch_size

    @property
    def collection_name(self) -> str:
        return self._collection_name

    async def ping(self) -> bool:
        await self._client.get_collections()
        return True

    async def ensure_collection(self) -> None:
        if not await self._client.collection_exists(self._collection_name):
            await self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config={DENSE_VECTOR_NAME: models.VectorParams(size=self._vector_size, distance=models.Distance.COSINE)},
                on_disk_payload=True,
            )
        info = await self._client.get_collection(self._collection_name)
        vectors = info.config.params.vectors
        if not isinstance(vectors, dict) or DENSE_VECTOR_NAME not in vectors:
            raise VectorRepositoryError("Qdrant collection does not have the required named vector")
        config = vectors[DENSE_VECTOR_NAME]
        if config.size != self._vector_size or config.distance != models.Distance.COSINE:
            raise VectorRepositoryError("Qdrant collection schema is incompatible; create a new versioned collection")
        existing = set(info.payload_schema)
        indexes = {
            "document_id": models.PayloadSchemaType.UUID,
            "folder_id": models.PayloadSchemaType.UUID,
            "chunk_index": models.PayloadSchemaType.INTEGER,
            "source_type": models.PayloadSchemaType.KEYWORD,
            "language": models.PayloadSchemaType.KEYWORD,
            "lecture_date_ordinal": models.PayloadSchemaType.INTEGER,
        }
        for field, schema in indexes.items():
            if field not in existing:
                await self._client.create_payload_index(
                    collection_name=self._collection_name,
                    field_name=field,
                    field_schema=schema,
                    wait=True,
                )

    def _validate_vector(self, vector: Sequence[float]) -> list[float]:
        if len(vector) != self._vector_size:
            raise ValueError(f"Expected vector dimension {self._vector_size}, got {len(vector)}")
        values = [float(value) for value in vector]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Vector contains a non-finite value")
        return values

    @staticmethod
    def _parse_payload(payload: dict | None) -> ChunkPayload:
        try:
            return ChunkPayload.model_validate(payload or {})
        except ValidationError as exc:
            raise VectorRepositoryError("Invalid chunk payload stored in Qdrant") from exc

    async def replace_document_chunks(self, document_id: UUID, chunks: Sequence[VectorChunk]) -> int:
        await self.delete_document(document_id)
        if not chunks:
            return 0
        points = [
            models.PointStruct(
                id=str(chunk.point_id),
                vector={DENSE_VECTOR_NAME: self._validate_vector(chunk.vector)},
                payload=chunk.payload.to_qdrant_payload(),
            )
            for chunk in chunks
        ]
        for start in range(0, len(points), self._upsert_batch_size):
            await self._client.upsert(
                collection_name=self._collection_name,
                points=points[start:start + self._upsert_batch_size],
                wait=True,
            )
        return len(points)

    async def delete_document(self, document_id: UUID) -> None:
        await self._client.delete(
            collection_name=self._collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=str(document_id)))])
            ),
            wait=True,
        )

    async def update_folder(self, old_folder_id: UUID, *, folder_id: UUID, folder_name: str) -> None:
        await self._client.set_payload(
            collection_name=self._collection_name,
            payload={"folder_id": str(folder_id), "folder_name": folder_name},
            points=models.Filter(must=[models.FieldCondition(key="folder_id", match=models.MatchValue(value=str(old_folder_id)))]),
            wait=True,
        )

    async def update_folder_name(self, folder_id: UUID, folder_name: str) -> None:
        await self._client.set_payload(
            collection_name=self._collection_name,
            payload={"folder_name": folder_name},
            points=models.Filter(must=[models.FieldCondition(key="folder_id", match=models.MatchValue(value=str(folder_id)))]),
            wait=True,
        )

    @staticmethod
    def _date_ordinal(value: date | None) -> int | None:
        return value.toordinal() if value else None

    @classmethod
    def _build_filter(cls, filters: SearchFilters) -> models.Filter | None:
        must: list[models.Condition] = []
        if filters.document_ids:
            must.append(models.FieldCondition(key="document_id", match=models.MatchAny(any=[str(value) for value in filters.document_ids])))
        if filters.folder_ids:
            must.append(models.FieldCondition(key="folder_id", match=models.MatchAny(any=[str(value) for value in filters.folder_ids])))
        if filters.source_types:
            must.append(models.FieldCondition(key="source_type", match=models.MatchAny(any=[value.value for value in filters.source_types])))
        if filters.language:
            must.append(models.FieldCondition(key="language", match=models.MatchValue(value=filters.language)))
        if filters.lecture_date_from or filters.lecture_date_to:
            must.append(
                models.FieldCondition(
                    key="lecture_date_ordinal",
                    range=models.Range(gte=cls._date_ordinal(filters.lecture_date_from), lte=cls._date_ordinal(filters.lecture_date_to)),
                )
            )
        return models.Filter(must=must) if must else None

    async def search(self, query_vector: Sequence[float], *, limit: int, score_threshold: float | None, filters: SearchFilters) -> list[VectorSearchResult]:
        response = await self._client.query_points(
            collection_name=self._collection_name,
            query=self._validate_vector(query_vector),
            using=DENSE_VECTOR_NAME,
            query_filter=self._build_filter(filters),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=False,
        )
        return [VectorSearchResult(point_id=UUID(str(point.id)), score=float(point.score), payload=self._parse_payload(point.payload)) for point in response.points]

    async def get_document_chunks(self, document_id: UUID, chunk_indexes: Sequence[int]) -> list[StoredVectorChunk]:
        indexes = sorted({int(index) for index in chunk_indexes if index >= 0})
        if not indexes:
            return []
        records, _ = await self._client.scroll(
            collection_name=self._collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(key="document_id", match=models.MatchValue(value=str(document_id))),
                    models.FieldCondition(key="chunk_index", match=models.MatchAny(any=indexes)),
                ]
            ),
            limit=len(indexes),
            with_payload=True,
            with_vectors=False,
        )
        chunks = [StoredVectorChunk(point_id=UUID(str(record.id)), payload=self._parse_payload(record.payload)) for record in records]
        chunks.sort(key=lambda chunk: chunk.payload.chunk_index)
        return chunks
