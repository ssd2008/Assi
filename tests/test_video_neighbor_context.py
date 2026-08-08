from uuid import UUID, uuid4

import pytest

from app.qdrant_schema import ChunkPayload, calculate_content_hash
from app.repositories.vector_repository import StoredVectorChunk, VectorSearchResult
from app.schemas import QueryRequest, SourceType
from app.services.search_service import SearchService


class FakeEmbeddings:
    async def embed_query(self, query: str) -> list[float]:
        assert query
        return [1.0]


class FakeReranker:
    async def score(self, query: str, texts: list[str]) -> list[float]:
        raise AssertionError("reranker should not be called in this test")


class FakeVectors:
    def __init__(self, candidates: list[VectorSearchResult], stored: list[StoredVectorChunk]) -> None:
        self._candidates = candidates
        self._stored = stored

    async def search(self, *args, **kwargs) -> list[VectorSearchResult]:
        return self._candidates

    async def get_document_chunks(self, document_id: UUID, chunk_indexes: list[int]) -> list[StoredVectorChunk]:
        requested = set(chunk_indexes)
        return [chunk for chunk in self._stored if chunk.payload.document_id == document_id and chunk.payload.chunk_index in requested]


def _word_offsets(words: list[str]) -> tuple[str, list[int], list[int]]:
    text = " ".join(words)
    starts: list[int] = []
    ends: list[int] = []
    cursor = 0
    for word in words:
        start = text.index(word, cursor)
        end = start + len(word)
        starts.append(start)
        ends.append(end)
        cursor = end
    return text, starts, ends


def _payload(*, document_id: UUID, folder_id: UUID, source_text: str, starts: list[int], ends: list[int], chunk_index: int, start_word: int, end_word: int, time_start: float, time_end: float) -> ChunkPayload:
    char_start = starts[start_word]
    char_end = ends[end_word - 1]
    text = source_text[char_start:char_end]
    return ChunkPayload(
        document_id=document_id,
        chunk_index=chunk_index,
        text=text,
        token_count=end_word - start_word,
        char_start=char_start,
        char_end=char_end,
        time_start_seconds=time_start,
        time_end_seconds=time_end,
        document_title="Лекция",
        source_type=SourceType.VIDEO,
        folder_id=folder_id,
        folder_name="Кардиология",
        language="ru",
        content_hash=calculate_content_hash(text),
    )


@pytest.mark.asyncio
async def test_search_expands_video_hits_and_skips_adjacent_duplicate_windows() -> None:
    words = ["один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать"]
    source_text, starts, ends = _word_offsets(words)
    document_id = uuid4()
    folder_id = uuid4()
    payloads = [
        _payload(document_id=document_id, folder_id=folder_id, source_text=source_text, starts=starts, ends=ends, chunk_index=0, start_word=0, end_word=4, time_start=0, time_end=20),
        _payload(document_id=document_id, folder_id=folder_id, source_text=source_text, starts=starts, ends=ends, chunk_index=1, start_word=3, end_word=7, time_start=18, time_end=38),
        _payload(document_id=document_id, folder_id=folder_id, source_text=source_text, starts=starts, ends=ends, chunk_index=2, start_word=6, end_word=10, time_start=36, time_end=56),
        _payload(document_id=document_id, folder_id=folder_id, source_text=source_text, starts=starts, ends=ends, chunk_index=3, start_word=9, end_word=13, time_start=54, time_end=74),
        _payload(document_id=document_id, folder_id=folder_id, source_text=source_text, starts=starts, ends=ends, chunk_index=4, start_word=12, end_word=16, time_start=72, time_end=92),
    ]
    point_ids = [uuid4() for _ in payloads]
    stored = [StoredVectorChunk(point_id=point_id, payload=payload) for point_id, payload in zip(point_ids, payloads, strict=True)]
    candidates = [
        VectorSearchResult(point_id=point_ids[1], score=0.95, payload=payloads[1]),
        VectorSearchResult(point_id=point_ids[2], score=0.90, payload=payloads[2]),
        VectorSearchResult(point_id=point_ids[4], score=0.80, payload=payloads[4]),
    ]
    service = SearchService(vectors=FakeVectors(candidates, stored), embeddings=FakeEmbeddings(), reranker=FakeReranker(), video_context_neighbor_chunks=1)  # type: ignore[arg-type]
    response = await service.search(QueryRequest(query="учебный вопрос", top_k=2, candidate_k=3, use_reranker=False))
    assert [result.chunk_index for result in response.results] == [1, 4]
    first = response.results[0]
    assert first.text == " ".join(words[:10])
    assert first.char_start == starts[0]
    assert first.char_end == ends[9]
    assert first.time_start_seconds == 0
    assert first.time_end_seconds == 56
    assert first.retrieval_score == 0.95
