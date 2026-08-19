from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from app.qdrant_schema import ChunkPayload
from app.repositories.vector_repository import VectorRepository, VectorSearchResult
from app.schemas import QueryRequest, SearchResponse, SearchResult, SourceType
from app.services.embedding_service import EmbeddingService
from app.services.rerank_service import RerankService


class SearchService:
    def __init__(self, *, vectors: VectorRepository, embeddings: EmbeddingService, reranker: RerankService, reranker_enabled: bool = False, video_context_neighbor_chunks: int = 1) -> None:
        if video_context_neighbor_chunks < 0:
            raise ValueError("video_context_neighbor_chunks must be non-negative")
        self._vectors = vectors
        self._embeddings = embeddings
        self._reranker = reranker
        self._reranker_enabled = reranker_enabled
        self._video_context_neighbor_chunks = video_context_neighbor_chunks

    async def search(self, request: QueryRequest) -> SearchResponse:
        started = time.perf_counter()
        query_vector = await self._embeddings.embed_query(request.query)
        candidates = await self._vectors.search(query_vector, limit=request.candidate_k, score_threshold=request.min_retrieval_score, filters=request.filters)
        if self._reranker_enabled and request.use_reranker and candidates:
            rerank_scores = list(await self._reranker.score(request.query, [candidate.payload.text for candidate in candidates]))
        else:
            rerank_scores = [None] * len(candidates)
        ranked = [(candidate, score, self._final_score(candidate, score)) for candidate, score in zip(candidates, rerank_scores, strict=True)]
        ranked.sort(key=lambda item: item[2], reverse=True)
        selected = self._select_distinct_candidates(ranked, request.top_k)
        expanded = await asyncio.gather(*(self._expand_video_context(candidate) for candidate, _, _ in selected))
        results = [self._to_result(rank, candidate, rerank_score, final_score) for rank, (candidate, (_, rerank_score, final_score)) in enumerate(zip(expanded, selected, strict=True), start=1)]
        return SearchResponse(query=request.query, results=results, total_candidates=len(candidates), took_ms=(time.perf_counter() - started) * 1000)

    def _select_distinct_candidates(self, ranked: Sequence[tuple[VectorSearchResult, float | None, float]], limit: int) -> list[tuple[VectorSearchResult, float | None, float]]:
        selected = []
        accepted_video_indexes: dict[object, list[int]] = {}
        radius = self._video_context_neighbor_chunks
        for item in ranked:
            payload = item[0].payload
            if payload.source_type == SourceType.VIDEO and radius > 0:
                indexes = accepted_video_indexes.setdefault(payload.document_id, [])
                if any(abs(payload.chunk_index - index) <= radius for index in indexes):
                    continue
                indexes.append(payload.chunk_index)
            selected.append(item)
            if len(selected) == limit:
                break
        return selected

    async def _expand_video_context(self, candidate: VectorSearchResult) -> VectorSearchResult:
        payload = candidate.payload
        radius = self._video_context_neighbor_chunks
        if payload.source_type != SourceType.VIDEO or radius == 0:
            return candidate
        indexes = range(max(0, payload.chunk_index - radius), payload.chunk_index + radius + 1)
        stored = await self._vectors.get_document_chunks(payload.document_id, list(indexes))
        chunks_by_index = {chunk.payload.chunk_index: chunk.payload for chunk in stored}
        chunks_by_index[payload.chunk_index] = payload
        ordered = [chunks_by_index[index] for index in sorted(chunks_by_index)]
        if len(ordered) <= 1:
            return candidate
        return VectorSearchResult(point_id=candidate.point_id, score=candidate.score, payload=self._merge_payloads(payload, ordered))

    @classmethod
    def _merge_payloads(cls, central: ChunkPayload, chunks: Sequence[ChunkPayload]) -> ChunkPayload:
        merged_text = cls._merge_text(chunks)
        time_starts = [chunk.time_start_seconds for chunk in chunks if chunk.time_start_seconds is not None]
        time_ends = [chunk.time_end_seconds for chunk in chunks if chunk.time_end_seconds is not None]
        page_starts = [chunk.page_start for chunk in chunks if chunk.page_start is not None]
        page_ends = [chunk.page_end for chunk in chunks if chunk.page_end is not None]
        return central.model_copy(update={
            "text": merged_text,
            "token_count": len(merged_text.split()),
            "char_start": min(chunk.char_start for chunk in chunks),
            "char_end": max(chunk.char_end for chunk in chunks),
            "page_start": min(page_starts) if page_starts else None,
            "page_end": max(page_ends) if page_ends else None,
            "time_start_seconds": min(time_starts) if time_starts else None,
            "time_end_seconds": max(time_ends) if time_ends else None,
        })

    @staticmethod
    def _merge_text(chunks: Sequence[ChunkPayload]) -> str:
        ordered = sorted(chunks, key=lambda chunk: (chunk.char_start, chunk.chunk_index))
        first = ordered[0]
        pieces = [first.text]
        covered_end = first.char_end
        for chunk in ordered[1:]:
            if chunk.char_end <= covered_end:
                continue
            overlap_chars = max(0, covered_end - chunk.char_start)
            suffix = chunk.text[overlap_chars:].lstrip()
            if suffix:
                pieces.append(suffix)
            covered_end = chunk.char_end
        return " ".join(piece.strip() for piece in pieces if piece.strip())

    @staticmethod
    def _final_score(candidate: VectorSearchResult, rerank_score: float | None) -> float:
        retrieval_normalized = max(0.0, min(1.0, (candidate.score + 1.0) / 2.0))
        return retrieval_normalized if rerank_score is None else 0.25 * retrieval_normalized + 0.75 * rerank_score

    @staticmethod
    def _to_result(rank: int, candidate: VectorSearchResult, rerank_score: float | None, final_score: float) -> SearchResult:
        payload = candidate.payload
        return SearchResult(
            rank=rank,
            chunk_id=candidate.point_id,
            document_id=payload.document_id,
            document_title=payload.document_title,
            folder_id=payload.folder_id,
            folder_name=payload.folder_name,
            chunk_index=payload.chunk_index,
            text=payload.text,
            source_type=payload.source_type,
            source_url=payload.source_url,
            lecture_date=payload.lecture_date,
            language=payload.language,
            page_start=payload.page_start,
            page_end=payload.page_end,
            time_start_seconds=payload.time_start_seconds,
            time_end_seconds=payload.time_end_seconds,
            section_title=payload.section_title,
            char_start=payload.char_start,
            char_end=payload.char_end,
            retrieval_score=candidate.score,
            rerank_score=rerank_score,
            final_score=final_score,
        )
