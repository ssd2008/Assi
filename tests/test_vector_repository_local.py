from datetime import date
from uuid import uuid4

import pytest
from qdrant_client import AsyncQdrantClient

from app.qdrant_schema import ChunkPayload, build_chunk_point_id, calculate_content_hash
from app.repositories.vector_repository import VectorChunk, VectorRepository
from app.schemas import SearchFilters, SourceType


@pytest.mark.asyncio
async def test_vector_repository_round_trip() -> None:
    client = AsyncQdrantClient(location=":memory:")
    repository = VectorRepository(client, collection_name="test_chunks", vector_size=8)
    try:
        await repository.ensure_collection()
        document_id = uuid4()
        folder_id = uuid4()
        text = "лечение артериальной гипертензии"
        content_hash = calculate_content_hash(text)
        lecture_date = date(2026, 7, 14)
        payload = ChunkPayload(
            document_id=document_id,
            chunk_index=0,
            text=text,
            token_count=3,
            char_start=0,
            char_end=len(text),
            document_title="Лекция",
            source_type=SourceType.TEXT,
            folder_id=folder_id,
            folder_name="Кардиология",
            lecture_date=lecture_date,
            lecture_date_ordinal=lecture_date.toordinal(),
            language="ru",
            content_hash=content_hash,
        )
        count = await repository.replace_document_chunks(
            document_id,
            [VectorChunk(point_id=build_chunk_point_id(document_id, 0, content_hash), vector=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], payload=payload)],
        )
        assert count == 1
        results = await repository.search(
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            limit=5,
            score_threshold=None,
            filters=SearchFilters(folder_ids=[folder_id]),
        )
        assert len(results) == 1
        assert results[0].payload.document_id == document_id
        await repository.delete_document(document_id)
        assert not await repository.search(
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            limit=5,
            score_threshold=None,
            filters=SearchFilters(),
        )
    finally:
        await client.close()
